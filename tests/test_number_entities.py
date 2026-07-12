"""Tests for EG4 number entities and shared read/write helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.number import RestoreNumber
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.eg4_web_monitor.const import (
    PARAM_FUNC_GRID_PEAK_SHAVING,
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_FORCED_CHG_POWER,
)
from custom_components.eg4_web_monitor.number import (
    async_setup_entry,
    ACChargeEndBatterySOCNumber,
    ACChargePowerNumber,
    ACChargeSOCLimitNumber,
    ACChargeStartBatterySOCNumber,
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
    EG4VoltageNumber,
    ForcedDischargePowerNumber,
    ForcedDischargeSOCLimitNumber,
    GridPeakShavingPowerNumber,
    GridSellBackPowerNumber,
    OnGridSOCCutoffNumber,
    PVChargePowerNumber,
    QuickChargeDurationNumber,
    StartChargePowerNumber,
    StartDischargePowerNumber,
    StopDischargeVoltageNumber,
    SystemChargeSOCLimitNumber,
)
from tests.conftest import wire_coordinator_write_helpers


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    serial: str = "1234567890",
    model: str = "FlexBOSS21",
    has_local: bool = False,
    has_http: bool = True,
    local_only: bool = False,
    parameters: dict | None = None,
    inverter_attrs: dict | None = None,
) -> MagicMock:
    """Build a mock coordinator for number entity tests."""
    coordinator = MagicMock()
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.has_configured_local_transport = MagicMock(return_value=has_local)
    # Mirrors the real predicate for the common shapes (local-only modes and
    # per-serial configured transports). Tests for the deprecated flat
    # single-transport format override this directly (GH #272 / codex P2 on
    # PR #284); the real branch logic is covered in test_coordinator_local.
    coordinator.has_local_register_path = MagicMock(
        return_value=(has_local or local_only)
    )
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.write_named_parameter = AsyncMock()
    coordinator.write_raw_parameter = AsyncMock()
    coordinator.async_write_battery_control_mode = AsyncMock()
    # Live quick-charge active check (reg 233 bit 0). Default idle; the
    # QuickChargeDurationNumber gates its reg 234 write on this.
    coordinator.is_quick_charge_active_live = AsyncMock(return_value=False)
    # Real dict (not an auto-Mock) so QuickChargeDurationNumber reads a true
    # per-serial duration preference.
    coordinator._quick_charge_minutes = {}
    # Battery control regime helpers (used by regime-gated control entities)
    coordinator.get_configured_control_modes = MagicMock(return_value=("soc", "soc"))
    coordinator.get_live_control_mode = MagicMock(return_value="soc")

    coordinator.data = {
        "devices": {serial: {"type": "inverter", "model": model}},
        "device_info": {serial: {"deviceTypeText4APP": model}},
        "parameters": {serial: parameters or {}},
    }
    coordinator.get_device_info = MagicMock(return_value=None)

    # Mock inverter object with configurable attributes
    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    # pylxpweb transport attachment mirrors has_local (modern HYBRID attach);
    # legacy flat-hybrid tests override with inverter_attrs={"transport": None}
    mock_inverter.transport = object() if has_local else None
    attrs = inverter_attrs or {}
    for attr_name, attr_value in attrs.items():
        setattr(mock_inverter, attr_name, attr_value)
    # Default cloud methods
    mock_inverter.set_ac_charge_power = AsyncMock(return_value=True)
    mock_inverter.set_pv_charge_power = AsyncMock(return_value=True)
    mock_inverter.set_ac_charge_soc_limit = AsyncMock(return_value=True)
    mock_inverter.set_forced_discharge_power = AsyncMock(return_value=True)
    mock_inverter.set_forced_discharge_soc_limit = AsyncMock(return_value=True)
    mock_inverter.set_stop_discharge_voltage = AsyncMock(return_value=True)
    mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
    mock_inverter.set_battery_charge_current = AsyncMock(return_value=True)
    mock_inverter.set_battery_discharge_current = AsyncMock(return_value=True)
    mock_inverter.set_grid_peak_shaving_power = AsyncMock(return_value=True)
    mock_inverter.set_feed_in_grid_power_percent = AsyncMock(return_value=True)
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    wire_coordinator_write_helpers(coordinator)
    return coordinator


def _prep(entity: object) -> None:
    """Prepare entity for async action tests (set hass + entity_id)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "number.test_entity"  # type: ignore[attr-defined]
    entity.platform = None  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


# ── Platform setup ───────────────────────────────────────────────────


class TestNumberPlatformSetup:
    """Test number platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_inverter(self, hass):
        """FlexBOSS creates 21 number entities.

        12 base + 6 voltage + grid sell + start discharge threshold + Quick
        Charge Duration (HTTP-only). The reg-117 start CHARGE threshold is
        absent: no local transport and the register has no cloud param name
        (GH #272).
        """
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 21
        type_names = [type(e).__name__ for e in entities]
        assert "ACChargePowerNumber" in type_names
        # Quick Charge Duration preference (HTTP-only, #251)
        assert "QuickChargeDurationNumber" in type_names
        assert "SystemChargeSOCLimitNumber" in type_names
        # Forced discharge controls (regs 82/83, GH #207 / PR #249)
        assert "ForcedDischargePowerNumber" in type_names
        assert "ForcedDischargeSOCLimitNumber" in type_names
        # Grid sell back power cap (reg 103, GH #135)
        assert "GridSellBackPowerNumber" in type_names
        # Start Discharge P_import threshold (reg 116, GH #272)
        assert "StartDischargePowerNumber" in type_names
        # Reg 117 needs a local transport (no cloud param name, GH #272)
        assert "StartChargePowerNumber" not in type_names
        # New voltage limit controls
        assert "SystemChargeVoltLimitNumber" in type_names
        voltage_entities = [e for e in entities if isinstance(e, EG4VoltageNumber)]
        assert len(voltage_entities) == 5
        assert {
            entity.unique_id.removeprefix("flexboss21_1234567890_")
            for entity in voltage_entities
        } == {
            "on_grid_cutoff_voltage",
            "off_grid_cutoff_voltage",
            "ac_charge_start_voltage",
            "ac_charge_end_voltage",
            # PV Start Voltage folded into the spec table (unique_id and
            # entity identity preserved from the retired dedicated class).
            "pv_start_voltage",
        }
        # Forced-discharge stop voltage (reg 202, bead eg4-aa3t)
        assert "StopDischargeVoltageNumber" in type_names
        # Reg 67 keeps working on grid-tied families (GH #331)
        assert "ACChargeSOCLimitNumber" in type_names
        # The off-grid AC-charge SOC window (regs 160/161) is offgrid-only
        assert "ACChargeStartBatterySOCNumber" not in type_names
        assert "ACChargeEndBatterySOCNumber" not in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_gridboss(self, hass):
        """GridBOSS should not create number entities."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"] = {
            "gb123": {"type": "gridboss", "model": "GridBOSS"}
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 0

    @pytest.mark.asyncio
    async def test_quick_charge_duration_local_mode(self, hass):
        """LOCAL mode with a configured transport creates the duration number.

        In LOCAL/HYBRID the duration is also written to holding register 234.
        """
        coordinator = _mock_coordinator(has_http=False, has_local=True, local_only=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "QuickChargeDurationNumber" in type_names

    @pytest.mark.asyncio
    async def test_quick_charge_duration_skipped_without_transport(self, hass):
        """Neither cloud nor local transport -> no Quick Charge Duration number."""
        coordinator = _mock_coordinator(
            has_http=False, has_local=False, local_only=False
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "QuickChargeDurationNumber" not in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_xp(self, hass):
        """XP device creates number entities, minus grid sell back (GH #135)."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) > 0
        type_names = [type(e).__name__ for e in entities]
        # Off-grid family has no grid sell-back
        assert "GridSellBackPowerNumber" not in type_names
        # ... and no CT grid-import thresholds either (GH #272)
        assert "StartDischargePowerNumber" not in type_names
        assert "StartChargePowerNumber" not in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_offgrid_features_skip_grid_sell(self, hass):
        """Feature-detected EG4_OFFGRID family skips grid sell back even when
        the model string alone would not identify it (GH #135 gating)."""
        coordinator = _mock_coordinator(model="6000XP")
        serial = "1234567890"
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "GridSellBackPowerNumber" not in type_names
        assert "StartDischargePowerNumber" not in type_names
        assert "StartChargePowerNumber" not in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_sna_15k_offgrid_creates_config_controls(
        self, hass
    ):
        """#259: cloud "SNA-US 15K" (EG4_OFFGRID) gets its Configuration controls.

        The model string matches no SUPPORTED_INVERTER_MODELS substring, so the
        legacy gate created zero number entities (empty Configuration block).
        The detected family backstops the gate; off-grid still omits the
        grid-tied-only power controls.
        """
        coordinator = _mock_coordinator(model="SNA-US 15K")
        serial = "1234567890"
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        # Core configuration controls are present again
        assert "ACChargePowerNumber" in type_names
        assert "SystemChargeSOCLimitNumber" in type_names
        assert "BatteryChargeCurrentNumber" in type_names
        # Off-grid family still omits the grid-tied-only controls
        assert "GridSellBackPowerNumber" not in type_names
        assert "GridPeakShavingPowerNumber" not in type_names
        assert "ForcedDischargePowerNumber" not in type_names
        assert "StartDischargePowerNumber" not in type_names
        assert "StartChargePowerNumber" not in type_names
        # ... and swaps the family-rejected reg-67 AC Charge SOC Limit for
        # the reg-160/161 AC-charge SOC window (GH #331)
        assert "ACChargeSOCLimitNumber" not in type_names
        assert "ACChargeStartBatterySOCNumber" in type_names
        assert "ACChargeEndBatterySOCNumber" in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_lxp_creates_start_thresholds(self, hass):
        """LXP family with a local transport gets both P_to_user thresholds.

        The reporter's LXP-LB (CT-equipped, HYBRID via dongle, GH #272): the
        reg-116 start-discharge threshold is created for grid-tied families,
        and the reg-117 start-charge threshold additionally requires a local
        transport (the cloud API has no parameter name for reg 117).
        """
        coordinator = _mock_coordinator(model="LXP-LB-EU 12k", has_local=True)
        serial = "1234567890"
        coordinator.data["devices"][serial]["features"] = {"inverter_family": "LXP"}
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "StartDischargePowerNumber" in type_names
        assert "StartChargePowerNumber" in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_local_only_creates_start_charge(self, hass):
        """Legacy flat LOCAL mode (is_local_only) also gets the reg-117 number
        even without a CONF_LOCAL_TRANSPORTS entry for the serial (GH #272)."""
        coordinator = _mock_coordinator(has_http=False, local_only=True)
        coordinator.has_configured_local_transport = MagicMock(return_value=False)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "StartDischargePowerNumber" in type_names
        assert "StartChargePowerNumber" in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_legacy_flat_hybrid_creates_both(self, hass):
        """Deprecated flat-format HYBRID entry creates BOTH threshold numbers.

        Codex P2 on PR #284: the original gate checked only
        CONF_LOCAL_TRANSPORTS (has_configured_local_transport), but the
        pre-v3.2 flat single-transport HYBRID format initializes the global
        _modbus_transport/_dongle_transport directly — those users got Start
        Discharge but silently no Start Charge. The gate now goes through
        has_local_register_path(), which recognizes the flat config too
        (real branch logic covered in test_coordinator_local).
        """
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        # Flat-format shape: no per-serial transport config, not local-only,
        # but a legacy global transport exists -> register path available.
        coordinator.has_configured_local_transport = MagicMock(return_value=False)
        coordinator.is_local_only = MagicMock(return_value=False)
        coordinator.has_local_register_path = MagicMock(return_value=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "StartDischargePowerNumber" in type_names
        assert "StartChargePowerNumber" in type_names


# ── _read_param_value (via ACChargeSOCLimitNumber) ───────────────────


class TestReadParamValue:
    """Test the _read_param_value helper via concrete entities."""

    def test_optimistic_takes_precedence(self):
        """Optimistic value overrides all data sources."""
        coordinator = _mock_coordinator(parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 80})
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        entity._optimistic_value = 42.0
        assert entity.native_value == 42

    def test_local_only_reads_params(self):
        """Local-only mode reads from parameter data."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 75},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 75

    def test_inverter_first_then_params_fallback(self):
        """Default order: inverter -> params fallback."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_soc_limit": 60},
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 70},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 60

    def test_params_fallback_when_no_inverter(self):
        """Falls back to params when inverter value is None."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_soc_limit": None},
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 80},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 80

    def test_none_when_no_data(self):
        """Returns None when no data is available."""
        coordinator = _mock_coordinator()
        coordinator.get_inverter_object = MagicMock(return_value=None)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_out_of_range_returns_none(self):
        """Values outside min/max range return None."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 200},  # > 101
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_reads_101_not_none(self):
        """A live 101% reads back as 101, not None (GH #158).

        101 = never stop AC charging (cell balancing). Before the fix the
        100 ceiling made a real 101 read out-of-range -> None (NaN in the UI).
        """
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 101},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 101


class TestReadParamValueFloat:
    """Test _read_param_value with as_float=True (via ACChargePowerNumber)."""

    def test_float_from_params_with_transform(self):
        """Param value in 100W units transformed to kW."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_AC_CHARGE_POWER: 50},  # 50 * 100W = 5.0 kW
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 5.0

    def test_float_from_inverter(self):
        """Inverter attribute value as float."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_power_limit": 3.5},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 3.5

    def test_float_precision(self):
        """Float value rounds to 1 decimal."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_power_limit": 3.456},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 3.5

    def test_hybrid_small_value_not_10x(self):
        """GH #207 (icepop456): HYBRID raw values that PASS the kW bound must
        not display 10x. inverter.parameters is locally populated, so the
        pylxpweb property surfaces raw 7 (= 0.7 kW), which passes the <=15
        bound — the entity must ignore the property when a local transport
        is attached and scale the param cache instead: 0.7, never 7.0."""
        coordinator = _mock_coordinator(
            has_local=True,
            inverter_attrs={"ac_charge_power_limit": 7},
            parameters={PARAM_HOLD_AC_CHARGE_POWER: 7},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 0.7

    def test_legacy_flat_hybrid_cloud_params_not_rescaled(self):
        """Legacy single-transport HYBRID: has_local_transport() reports True
        via the deprecated global fallback, but the inverter object has NO
        attached transport — its params were cloud-populated (kW-scaled).
        The gate keys off the object's transport, not has_local_transport():
        12 kW must display 12.0, never 1.2 (codex MEDIUM)."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={PARAM_HOLD_AC_CHARGE_POWER: 12},
            inverter_attrs={"ac_charge_power_limit": 12.0, "transport": None},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 12.0


class TestReadParamValueDict:
    """Test _read_param_value with inverter_dict_attr (via OnGridSOCCutoffNumber)."""

    def test_reads_from_dict(self):
        """Reads from inverter dict attribute."""
        coordinator = _mock_coordinator(
            inverter_attrs={"battery_soc_limits": {"on_grid_limit": 20}},
        )
        entity = OnGridSOCCutoffNumber(coordinator, "1234567890")
        assert entity.native_value == 20

    def test_dict_missing_returns_none(self):
        """Missing dict key returns None, falls to params."""
        coordinator = _mock_coordinator(
            inverter_attrs={"battery_soc_limits": {}},
            parameters={"HOLD_DISCHG_CUT_OFF_SOC_EOD": 15},
        )
        entity = OnGridSOCCutoffNumber(coordinator, "1234567890")
        assert entity.native_value == 15


class TestReadParamValueParamsFirst:
    """Test _read_param_value with params_first=True (via SystemChargeSOCLimitNumber)."""

    def test_params_first_order(self):
        """With params_first, reads params before inverter."""
        coordinator = _mock_coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 90},
            inverter_attrs={"system_charge_soc_limit": 80},
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 90

    def test_params_first_falls_to_inverter(self):
        """params_first with no params falls back to inverter."""
        coordinator = _mock_coordinator(
            inverter_attrs={"system_charge_soc_limit": 80},
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 80


# ── PVChargePowerNumber (reg 74, 100W units) ─────────────────────────


class TestPVChargePowerNativeValue:
    """PV Charge Power reads reg 74 (HOLD_FORCED_CHG_POWER_CMD) in 100W units."""

    def test_from_params_100w_units_to_kw(self):
        """Local param raw 100W units scaled to kW (reg 74 raw 120 -> 12 kW)."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_FORCED_CHG_POWER: 120},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 12

    def test_no_bounce_low_value(self):
        """Regression for the set-1-reads-0 bounce: raw 10 -> 1 kW (not 0)."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_FORCED_CHG_POWER: 10},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 1

    def test_from_inverter_positive_value(self):
        """Cloud pv_charge_power_limit is already kW and returned directly."""
        coordinator = _mock_coordinator(
            inverter_attrs={"pv_charge_power_limit": 10},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 10

    def test_zero_kw_is_valid(self):
        """0 kW (reg 74 = 0) is a valid setting, not 'unset'."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_FORCED_CHG_POWER: 0},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 0

    def test_hybrid_small_value_not_10x(self):
        """GH #207 (icepop456) PV variant: raw 10 (= 1 kW) passes the <=15
        bound via the property; the local-transport gate must yield 1."""
        coordinator = _mock_coordinator(
            has_local=True,
            inverter_attrs={"pv_charge_power_limit": 10},
            parameters={PARAM_HOLD_FORCED_CHG_POWER: 10},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 1

    def test_hybrid_out_of_range_inverter_falls_back_to_params(self):
        """If the inverter attr holds a raw 100W value (>15), the >15 guard

        rejects it and the local param (raw 100W) is used with ÷10 scaling.
        Guards against double-scaling: result must be 12, never 1.2 or None.
        (With the local-transport gate the property is no longer consulted
        at all — kept as the double-scaling canary.)
        """
        coordinator = _mock_coordinator(
            has_local=True,
            inverter_attrs={"pv_charge_power_limit": 120},  # raw, out of kW range
            parameters={PARAM_HOLD_FORCED_CHG_POWER: 120},  # raw 100W units
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 12

    @pytest.mark.asyncio
    async def test_write_local_targets_reg74_in_100w_units(self):
        """Local write of 1 kW resolves to reg 74 param with raw 10 (1 kW)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = PVChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(1)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == PARAM_HOLD_FORCED_CHG_POWER
        assert call_args[0][1] == 10  # 1 kW -> 100W units

    @pytest.mark.asyncio
    async def test_write_cloud_passes_kw(self):
        """Cloud write passes integer kW to set_pv_charge_power."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = PVChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(2)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_pv_charge_power.assert_called_once_with(power_kw=2)


# ── _write_parameter (via ACChargeSOCLimitNumber) ────────────────────


class TestWriteParameter:
    """Test the _write_parameter helper via concrete entities."""

    @pytest.mark.asyncio
    async def test_write_local(self):
        """Local transport writes named parameter."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(75.0)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][1] == 75  # int(value)

    @pytest.mark.asyncio
    async def test_write_cloud(self):
        """Cloud mode calls inverter method."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(80.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_called_once_with(soc_percent=80)

    @pytest.mark.asyncio
    async def test_write_validation_range(self):
        """Out of range values raise HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(150.0)

    @pytest.mark.asyncio
    async def test_write_validation_integer(self):
        """Non-integer value for integer entity raises HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be an integer"):
            await entity.async_set_native_value(50.5)

    @pytest.mark.asyncio
    async def test_write_101_accepted(self):
        """101% is accepted and written (never-stop / cell balancing, GH #158)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(101.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_called_once_with(soc_percent=101)

    @pytest.mark.asyncio
    async def test_write_102_rejected(self):
        """102% is past the 101 cap and raises (GH #158)."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between 0-101%"):
            await entity.async_set_native_value(102.0)

    def test_bounds_allow_101(self):
        """Entity native bounds expose 0-101 (GH #158), distinct from the
        on-grid/off-grid discharge cutoffs which stay 0-100."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_min_value == 0
        assert entity.native_max_value == 101


class TestHybridCloudFallback:
    """HYBRID number writes fall back to the cloud when the local write
    fails (switch parity — pylxpweb keeps the transport attached while the
    link is down, so attachment alone must not pin the local path)."""

    @pytest.mark.asyncio
    async def test_write_parameter_local_failure_falls_back_to_cloud(self):
        """_write_parameter: local raises -> inverter cloud method used."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(80.0)

        coordinator.write_named_parameter.assert_awaited_once()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_called_once_with(soc_percent=80)

    @pytest.mark.asyncio
    async def test_write_parameter_local_only_failure_still_raises(self):
        """LOCAL-only: no cloud client -> the local error propagates."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="timeout"):
            await entity.async_set_native_value(80.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_parameter_link_down_prefers_cloud_immediately(self):
        """Known-down link: the doomed local write is skipped entirely."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.is_transport_link_down = MagicMock(return_value=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(75.0)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_called_once_with(soc_percent=75)

    @pytest.mark.asyncio
    async def test_link_down_write_skips_local_param_refresh_and_seeds_cache(self):
        """Known-down link: the cloud write must NOT be followed by a local
        parameter read (pylxpweb's param fetch has no link gate and would
        hang); instead the acknowledged value is seeded into the cache so
        the entity converges on the written value, not the stale pre-write
        cache (codex P1 on PR #301)."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.is_transport_link_down = MagicMock(return_value=True)
        result = MagicMock()
        result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
            return_value=result
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.refresh.assert_not_awaited()
        coordinator.note_parameters_written.assert_called_once_with(
            "1234567890", {"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 90}
        )

    @pytest.mark.asyncio
    async def test_fallback_write_seeds_cache_with_local_raw_value(self):
        """Attempt-then-fallback (link not yet flagged down): the cloud
        write also seeds the local-raw cache so a failed follow-up local
        read cannot revert the entity (#282 carry-forward keeps the seed)."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(80.0)

        coordinator.note_parameters_written.assert_called_once()
        serial_arg, values = coordinator.note_parameters_written.call_args[0]
        assert serial_arg == "1234567890"
        assert list(values.values()) == [80]

    @pytest.mark.asyncio
    async def test_cloud_only_write_does_not_seed_cache(self):
        """Pure-cloud (no local transport): no seeding — the cloud param
        cache is refreshed normally and uses cloud-scaled values."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(80.0)

        coordinator.note_parameters_written.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_charge_soc_local_failure_falls_back_to_cloud(self):
        """Inline 3-way site (system charge SOC): cloud API branch used."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        result = MagicMock()
        result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
            return_value=result
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.write_named_parameter.assert_awaited_once()
        coordinator.client.api.control.set_system_charge_soc_limit.assert_called_once_with(
            "1234567890", 90
        )


class TestACChargePowerWrite:
    """Test ACChargePower write (kW -> 100W units conversion)."""

    @pytest.mark.asyncio
    async def test_write_local_converts_kw_to_100w(self):
        """Local transport converts kW to 100W units for register."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ACChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        # 5.0 kW * 10 = 50 (100W units)
        assert call_args[0][1] == 50


class TestBatteryCurrentWrite:
    """Test BatteryChargeCurrent and BatteryDischargeCurrent write."""

    @pytest.mark.asyncio
    async def test_charge_current_write_cloud(self):
        """Cloud mode calls set_battery_charge_current."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = BatteryChargeCurrentNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(100.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_battery_charge_current.assert_called_once_with(current_amps=100)

    @pytest.mark.asyncio
    async def test_discharge_current_no_integer_check(self):
        """BatteryDischargeCurrent intentionally skips fraction check."""
        coordinator = _mock_coordinator(has_local=True)
        entity = BatteryDischargeCurrentNumber(coordinator, "1234567890")
        _prep(entity)

        # This should NOT raise — discharge current has no fraction check
        await entity.async_set_native_value(100.0)
        coordinator.write_named_parameter.assert_called_once()


class TestSystemChargeSOCWrite:
    """Test SystemChargeSOCLimit's custom 3-way write path."""

    @pytest.mark.asyncio
    async def test_write_local(self):
        """Local transport writes named parameter."""
        coordinator = _mock_coordinator(has_local=True)
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.write_named_parameter.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_cloud_api(self):
        """Cloud uses client.api.control.set_system_charge_soc_limit."""
        coordinator = _mock_coordinator(has_local=False)
        # Mock client.api.control path
        mock_result = MagicMock()
        mock_result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
            return_value=mock_result
        )

        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.client.api.control.set_system_charge_soc_limit.assert_called_once_with(
            "1234567890", 90
        )

    @pytest.mark.asyncio
    async def test_write_no_transport_raises(self):
        """No local or cloud raises HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False)
        coordinator.client = None

        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="No local transport or cloud API"):
            await entity.async_set_native_value(90.0)

    @pytest.mark.asyncio
    async def test_write_range_101_allowed(self):
        """101% (top balancing) is within valid range."""
        coordinator = _mock_coordinator(has_local=True)
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(101.0)
        coordinator.write_named_parameter.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_below_range_raises(self):
        """Below 10% raises HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        entity.hass = MagicMock()

        with pytest.raises(
            HomeAssistantError, match="must be an integer between 10-101"
        ):
            await entity.async_set_native_value(5.0)


# ── Forced discharge controls (regs 82/83, GH #207 / PR #249) ────────


class TestForcedDischargeNumbers:
    """Forced Discharge Power (reg 82, kW) + SOC Limit (reg 83, %).

    Reg 82 stores 100W units (0-255 = 0-25.5 kW) — hardware-verified in
    PR #249 (panel 2.5 kW reads raw 25); cloud UI takes float kW [0, 25.5].
    """

    def test_power_definition(self):
        coordinator = _mock_coordinator()
        entity = ForcedDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_min_value == 0.0
        assert entity.native_max_value == 25.5
        assert entity.native_step == 0.1
        assert entity.native_unit_of_measurement == "kW"
        assert entity.unique_id.endswith("_forced_discharge_power")

    def test_soc_limit_definition_and_regime_key(self):
        coordinator = _mock_coordinator()
        entity = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_min_value == 0
        assert entity.native_max_value == 100
        assert entity.native_unit_of_measurement == "%"
        assert entity.unique_id.endswith("_forced_discharge_soc_limit")
        # SOC-regime stop limit: participates in reg-179 discharge gating
        assert entity._control_key == "forced_discharge_soc_limit"

    def test_regime_classification(self):
        """SOC limit is a discharge/SOC-regime control; the power command is
        NOT regime-gated (a power level, not a stop limit — the cloud UI
        likewise gates only the SOC field with disChgSocEnable)."""
        from custom_components.eg4_web_monitor.const.device_types import (
            DISCHARGE_SOC_CONTROLS,
            REGIME_GATED_CONTROLS,
            control_side_and_mode,
        )

        assert "forced_discharge_soc_limit" in DISCHARGE_SOC_CONTROLS
        assert control_side_and_mode("forced_discharge_soc_limit") == (
            "discharge",
            "soc",
        )
        assert "forced_discharge_power" not in REGIME_GATED_CONTROLS
        assert control_side_and_mode("forced_discharge_power") is None

    def test_native_value_from_params_local(self):
        """LOCAL: raw 100W values from the parameter cache scale to kW
        (read via the widened (64, 20) range -> REGISTER_TO_PARAM_KEYS)."""
        coordinator = _mock_coordinator(
            local_only=True,
            has_local=True,
            parameters={
                "HOLD_FORCED_DISCHG_POWER_CMD": 25,
                "HOLD_FORCED_DISCHG_SOC_LIMIT": 20,
            },
        )
        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        soc = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        # PR #249 hardware round-trip: panel 2.5 kW == raw 25
        assert power.native_value == 2.5
        assert soc.native_value == 20

    def test_native_value_from_inverter_cloud(self):
        """CLOUD: pylxpweb cached-parameter properties feed the value
        (the cloud property already returns kW — no rescale here)."""
        coordinator = _mock_coordinator(
            inverter_attrs={
                "forced_discharge_power": 4.0,
                "forced_discharge_soc_limit": 15,
            },
        )
        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        soc = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        assert power.native_value == 4.0
        assert soc.native_value == 15

    def test_native_value_hybrid_ignores_raw_property(self):
        """HYBRID: with a local transport, inverter.parameters is populated
        from that transport, so the pylxpweb property surfaces the RAW 100W
        value — raw 25 would pass the 25.5 kW bound and display 25 kW with
        a 10x write-back hazard (codex HIGH). The entity must read only the
        param cache (raw, scaled /10) when a local transport is attached."""
        coordinator = _mock_coordinator(
            has_local=True,
            local_only=False,
            parameters={"HOLD_FORCED_DISCHG_POWER_CMD": 25},
            inverter_attrs={"forced_discharge_power": 25.0},
        )
        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        assert power.native_value == 2.5

    def test_native_value_legacy_flat_hybrid_cloud_params(self):
        """Legacy flat HYBRID (global transport, none attached to the
        inverter object): params are cloud kW — must NOT be rescaled.
        12 kW displays 12.0, never 1.2 (codex MEDIUM parity)."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_FORCED_DISCHG_POWER_CMD": 12},
            inverter_attrs={"forced_discharge_power": 12.0, "transport": None},
        )
        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        assert power.native_value == 12.0

    @pytest.mark.asyncio
    async def test_power_write_local(self):
        """Local transport writes the raw 100W value by name (2.5 kW -> 25)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ForcedDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(2.5)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "HOLD_FORCED_DISCHG_POWER_CMD"
        assert call_args[0][1] == 25

    @pytest.mark.asyncio
    async def test_power_write_local_float_rounding(self):
        """kW->raw conversion rounds instead of truncating float artifacts
        (2.3 * 10 = 22.999... must write 23, not 22)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ForcedDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(2.3)

        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][1] == 23

    @pytest.mark.asyncio
    async def test_power_write_cloud(self):
        """Cloud mode calls inverter.set_forced_discharge_power(power_kw=...)
        — the cloud API takes float kW directly."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ForcedDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(2.5)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_forced_discharge_power.assert_called_once_with(power_kw=2.5)

    @pytest.mark.asyncio
    async def test_soc_limit_write_local(self):
        """Local transport writes HOLD_FORCED_DISCHG_SOC_LIMIT by name."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(20.0)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "HOLD_FORCED_DISCHG_SOC_LIMIT"
        assert call_args[0][1] == 20

    @pytest.mark.asyncio
    async def test_soc_limit_write_cloud(self):
        """Cloud mode calls inverter.set_forced_discharge_soc_limit(...)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(20.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_forced_discharge_soc_limit.assert_called_once_with(soc_percent=20)

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Out-of-range kW/SOC and non-integer SOC raise HomeAssistantError.

        The power command accepts fractional kW (0.1 kW register
        granularity), so only the SOC keeps the integer restriction.
        """
        coordinator = _mock_coordinator()
        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        soc = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        _prep(power)
        _prep(soc)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await power.async_set_native_value(25.6)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await power.async_set_native_value(-0.1)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await soc.async_set_native_value(-1.0)
        with pytest.raises(HomeAssistantError, match="must be an integer"):
            await soc.async_set_native_value(50.5)

    @pytest.mark.asyncio
    async def test_cloud_write_guard_on_old_pylxpweb(self):
        """Installed pylxpweb without the new setters raises a clean error
        instead of AttributeError (codex r1 HIGH: version coupling)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        inverter = coordinator.get_inverter_object("1234567890")
        del inverter.set_forced_discharge_power
        del inverter.set_forced_discharge_soc_limit

        power = ForcedDischargePowerNumber(coordinator, "1234567890")
        soc = ForcedDischargeSOCLimitNumber(coordinator, "1234567890")
        _prep(power)
        _prep(soc)

        with pytest.raises(HomeAssistantError, match="newer pylxpweb"):
            await power.async_set_native_value(2.5)
        with pytest.raises(HomeAssistantError, match="newer pylxpweb"):
            await soc.async_set_native_value(20.0)


# ── Grid Peak Shaving Power (PS1 = reg 206, cloud-write-only; eg4-gfu5) ──


class TestGridPeakShavingPowerNumber:
    """PS1 is cloud-write-only: the old local name-write path resolved to
    register 231, which is NOT the peak shaving power register (the 2026-06-12
    sweep pins PS1 at reg 206), so local writes were landing in an unknown
    register. The raw encoding of reg 206 is unverified, so writes must go
    through the cloud name-write until a write window proves the encoding."""

    @pytest.mark.asyncio
    async def test_write_routes_to_cloud_even_with_local_transport(self):
        """HYBRID (local transport + cloud): the write must use the cloud
        name-write, NEVER coordinator.write_named_parameter (which would
        target whatever register the installed pylxpweb maps the name to)."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.5)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.5)
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_cloud_mode(self):
        """Cloud-only mode writes float kW via the pylxpweb setter."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(7.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=7.0)
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_pure_local_raises(self):
        """Pure-LOCAL (no cloud client): a clear error, and absolutely no
        local register write."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.client = None
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="requires the cloud API"):
            await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_not_called()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_cloud_failure_raises(self):
        """Cloud setter returning False surfaces as HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power = AsyncMock(return_value=False)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="Failed to set"):
            await entity.async_set_native_value(3.0)

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Out-of-range kW raises before any write is attempted."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(25.6)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(-0.1)
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_not_called()

    @staticmethod
    def _mock_live_mode_read(coordinator, parameters: dict) -> AsyncMock:
        """Mock the live reg-179 cloud read used by verify-then-block."""
        response = MagicMock()
        response.parameters = parameters
        read = AsyncMock(return_value=response)
        coordinator.client.api.control.read_parameters = read
        return read

    @pytest.mark.asyncio
    async def test_write_mode_disabled_raises(self):
        """#328: Peak Shaving mode known-OFF refuses the write up front —
        the firmware rejects it (DATAFRAME_TIMEOUT) and clears the setpoint
        while the mode is off, so a silent attempt would misreport success.
        The cached False is confirmed by the live reg-179 read first."""
        coordinator = _mock_coordinator(
            has_local=False,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": False},
        )
        live_read = self._mock_live_mode_read(
            coordinator, {"FUNC_GRID_PEAK_SHAVING": False}
        )
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(ServiceValidationError, match="Peak Shaving mode"):
            await entity.async_set_native_value(5.0)

        live_read.assert_awaited_once_with(
            "1234567890", start_register=179, point_number=1
        )
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_mode_disabled_int_zero_raises(self):
        """#328: local param refreshes report FUNC bits as 0/1 ints — a raw
        0 must gate exactly like False."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": 0},
        )
        self._mock_live_mode_read(coordinator, {"FUNC_GRID_PEAK_SHAVING": 0})
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(ServiceValidationError, match="Peak Shaving mode"):
            await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_stale_cache_live_mode_on_proceeds(self):
        """#328 review P2 (stale-cache lockout): the cache refreshes ~hourly,
        so a mode just enabled on the portal/LCD can be cached False. The
        live reg-179 read says ON — the write proceeds and the fresh truth
        is seeded into the coordinator cache."""
        coordinator = _mock_coordinator(
            has_local=False,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": False},
        )
        self._mock_live_mode_read(coordinator, {"FUNC_GRID_PEAK_SHAVING": True})
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.0)
        coordinator.note_parameters_written.assert_called_once_with(
            "1234567890", {PARAM_FUNC_GRID_PEAK_SHAVING: True}
        )

    @pytest.mark.asyncio
    async def test_write_cached_false_live_read_fails_open(self):
        """#328: the live confirmation read failing must NOT block the write
        — the firmware is the final arbiter (fail-open)."""
        coordinator = _mock_coordinator(
            has_local=False,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": False},
        )
        coordinator.client.api.control.read_parameters = AsyncMock(
            side_effect=TimeoutError("cloud read failed")
        )
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.0)
        coordinator.note_parameters_written.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_cached_false_live_read_omits_bit_fails_open(self):
        """#328: a live response without the FUNC bit is unknown state —
        proceed fail-open, and don't seed anything into the cache."""
        coordinator = _mock_coordinator(
            has_local=False,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": False},
        )
        self._mock_live_mode_read(coordinator, {})
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.0)
        coordinator.note_parameters_written.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_mode_enabled_proceeds(self):
        """#328: Peak Shaving mode ON — the write goes through normally,
        with NO extra live read on the happy path."""
        coordinator = _mock_coordinator(
            has_local=False,
            has_http=True,
            parameters={"FUNC_GRID_PEAK_SHAVING": True},
        )
        live_read = self._mock_live_mode_read(coordinator, {})
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        live_read.assert_not_awaited()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.0)

    @pytest.mark.asyncio
    async def test_write_mode_unknown_fails_open(self):
        """#328: mode param absent from coordinator data (e.g. params not
        yet fetched) — proceed with the write rather than blocking on
        missing data (fail-open)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_grid_peak_shaving_power.assert_called_once_with(power_kw=5.0)

    def test_native_value_from_inverter_attr(self):
        """Cloud modes read the kW value from the pylxpweb property."""
        coordinator = _mock_coordinator(
            inverter_attrs={"grid_peak_shaving_power_limit": 7.0},
        )
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        assert entity.native_value == 7.0

    def test_native_value_pure_local_is_unavailable(self):
        """Pure-LOCAL has no trustworthy source: the coordinator no longer
        reads registers 231-232, so the value is unknown rather than a
        misread of an unrelated register."""
        coordinator = _mock_coordinator(has_local=True, local_only=True)
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_native_value_hybrid_key_miss_is_unknown_not_zero(self):
        """HYBRID after a cloud write (codex HIGH): the local-transport
        parameter refresh cannot name the PS1 key, so the pylxpweb property
        returns None — the entity must show unknown, never a fabricated 0.0.
        (pylxpweb>=0.9.36b6 pins the None-on-key-miss property semantics.)"""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            # Transport-named parameter dict: raw string key, no PS1 name
            parameters={"206": 55},
            inverter_attrs={"grid_peak_shaving_power_limit": None},
        )
        entity = GridPeakShavingPowerNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_disabled_by_default_in_pure_local(self):
        """Pure-LOCAL registers the entity disabled (it cannot work without
        cloud); cloud-capable modes keep it enabled."""
        local_coord = _mock_coordinator(has_local=True, local_only=True)
        local_entity = GridPeakShavingPowerNumber(local_coord, "1234567890")
        assert local_entity.entity_registry_enabled_default is False

        cloud_coord = _mock_coordinator(has_http=True)
        cloud_entity = GridPeakShavingPowerNumber(cloud_coord, "1234567890")
        assert cloud_entity.entity_registry_enabled_default is True


class TestGridSellBackPowerNumber:
    """Grid Sell Back Power control (reg 103, kW, GH #135 / #274).

    The register stores 100 W units — the reg-66/74/82 encoding — NOT the
    percent the protocol PDF claims: the 2026-04-13 live probe read raw 160
    on an 18kPV + FlexBOSS21 while the same 18kPV's cloud named read
    returned "16", and both web UIs label the field "Grid Sell Back
    Power(kW)" (GH #135 + #274 screenshots; the #274 LXP shows 12.1 kW =
    raw 121, impossible as a 0-100 percent). Cloud named reads/writes are
    kW floats; local raw needs the ÷10/×10 scaling.
    """

    def test_entity_definition_kw(self):
        """Unit is kW with 0.1 steps; unique_id suffix unchanged (#274)."""
        coordinator = _mock_coordinator()
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_unit_of_measurement == "kW"
        assert entity.native_min_value == 0
        assert entity.native_max_value == 25.5
        assert entity.native_step == 0.1
        assert entity.unique_id.endswith("_grid_sell_back_power")
        # Localizable name: translation_key, no hardcoded _attr_name
        assert entity.translation_key == "grid_sell_back_power"
        assert getattr(entity, "_attr_name", None) is None

    def test_native_value_cloud_kw_float(self):
        """Cloud named reads return kW floats — LXP shows 12.1 (GH #274)."""
        coordinator = _mock_coordinator(
            inverter_attrs={"parameters": {"HOLD_FEED_IN_GRID_POWER_PERCENT": "12.1"}},
        )
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_value == 12.1

    def test_native_value_cloud_kw_int_string(self):
        """18kPV cloud named read "16" is 16.0 kW (raw 160), not 16 %."""
        coordinator = _mock_coordinator(
            inverter_attrs={"parameters": {"HOLD_FEED_IN_GRID_POWER_PERCENT": "16"}},
        )
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_value == 16.0

    def test_native_value_local_raw_scaled(self):
        """Local-only mode scales the raw 100 W register value (121 -> 12.1)."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_FEED_IN_GRID_POWER_PERCENT": 121},
        )
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_value == 12.1

    def test_native_value_hybrid_transport_raw(self):
        """HYBRID with an attached transport holds raw values (160 -> 16.0),
        mirroring the ForcedDischargePowerNumber 10x-hazard guard."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_FEED_IN_GRID_POWER_PERCENT": 160},
        )
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_value == 16.0

    def test_native_value_rejects_out_of_range(self):
        """Garbage raw values above 255 (25.5 kW) read as None."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_FEED_IN_GRID_POWER_PERCENT": 2560},
        )
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_write_local_named_parameter_raw(self):
        """Local transport writes the raw 100 W value (12.1 kW -> 121)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(12.1)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "HOLD_FEED_IN_GRID_POWER_PERCENT"
        assert call_args[0][1] == 121

    @pytest.mark.asyncio
    async def test_write_cloud_method_kw(self):
        """Cloud mode calls inverter.set_feed_in_grid_power_kw(power_kw=...)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_feed_in_grid_power_kw = AsyncMock(return_value=True)
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(12.1)

        inverter.set_feed_in_grid_power_kw.assert_called_once_with(power_kw=12.1)

    @pytest.mark.asyncio
    async def test_write_cloud_fallback_write_parameter(self):
        """Installed pylxpweb without set_feed_in_grid_power_kw falls back to
        the generic named-parameter write (kW string, the website's call)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        inverter = coordinator.get_inverter_object("1234567890")
        del inverter.set_feed_in_grid_power_kw
        result = MagicMock()
        result.success = True
        coordinator.client.api.control.write_parameter = AsyncMock(return_value=result)
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(12.1)

        coordinator.client.api.control.write_parameter.assert_called_once_with(
            "1234567890", "HOLD_FEED_IN_GRID_POWER_PERCENT", "12.1"
        )

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Out-of-range kW values raise HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = GridSellBackPowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(25.6)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(-1.0)


class TestStartDischargePowerNumber:
    """Start Discharge P_import threshold (HOLD 116, W, GH #272).

    Protocol register table: ``PtoUserStartdischg``, scale **1 W** (default
    50 W) — "device starts discharging when Ptouser higher than this value";
    the Luxpower web UI labels it "Start Discharge P_import(W)" with a
    ``[50, ]`` range hint. Raw register IS whole watts — NOT the 100 W
    encoding of regs 66/74/82/103 (fleet reads: raw 100 == cloud "100" ==
    100 W). The live cloud param is HOLD_P_TO_USER_START_DISCHG (reporter's
    browser console + every docs/inverters scanner dump); pylxpweb's LOCAL
    name map spells reg 116 HOLD_PTOUSER_START_DISCHARGE.
    """

    def test_entity_definition_w(self):
        """Unit W, protocol bounds 50-10000, 1 W steps, enabled by default."""
        coordinator = _mock_coordinator()
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_unit_of_measurement == "W"
        assert entity.native_min_value == 50
        assert entity.native_max_value == 10000
        assert entity.native_step == 1
        assert entity.unique_id.endswith("_start_discharge_power_threshold")
        # Localizable name: translation_key, no hardcoded _attr_name
        assert entity.translation_key == "start_discharge_power_threshold"
        assert getattr(entity, "_attr_name", None) is None
        # Live-verified register (reporter's LXP-LB): enabled by default
        assert entity.entity_registry_enabled_default is True

    def test_native_value_local_raw_w(self):
        """LOCAL mode reads the raw watt value under pylxpweb's name-map key."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_PTOUSER_START_DISCHARGE": 100},
        )
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 100

    def test_native_value_hybrid_transport_raw_w(self):
        """HYBRID with an attached transport also holds raw watts."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_PTOUSER_START_DISCHARGE": 150},
        )
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 150

    def test_native_value_cloud_named_param(self):
        """CLOUD reads the live cloud key (watt string, e.g. '100')."""
        coordinator = _mock_coordinator(
            inverter_attrs={"parameters": {"HOLD_P_TO_USER_START_DISCHG": "100"}},
        )
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 100

    def test_native_value_cloud_params_dict_fallback(self):
        """Cloud value in the coordinator parameter cache also resolves."""
        coordinator = _mock_coordinator(
            parameters={"HOLD_P_TO_USER_START_DISCHG": "250"},
            inverter_attrs={"transport": None, "parameters": {}},
        )
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 250

    def test_native_value_rejects_out_of_range(self):
        """Garbage above 10000 W (and below the 50 W floor) reads as None."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_PTOUSER_START_DISCHARGE": 20000},
        )
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_write_local_named_parameter_w(self):
        """Local transport writes the watt value under the name-map key."""
        coordinator = _mock_coordinator(has_local=True)
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(150)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "HOLD_PTOUSER_START_DISCHARGE"
        assert call_args[0][1] == 150

    @pytest.mark.asyncio
    async def test_write_cloud_named_parameter(self):
        """Cloud mode issues the website's own remoteSet call:
        holdParam=HOLD_P_TO_USER_START_DISCHG with the watt value as text
        (reporter-verified in the GH #272 browser console)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        result = MagicMock()
        result.success = True
        coordinator.client.api.control.write_parameter = AsyncMock(return_value=result)
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(150)

        coordinator.client.api.control.write_parameter.assert_called_once_with(
            "1234567890", "HOLD_P_TO_USER_START_DISCHG", "150"
        )

    @pytest.mark.asyncio
    async def test_write_cloud_failure_raises(self):
        """A failed cloud write surfaces as HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        result = MagicMock()
        result.success = False
        coordinator.client.api.control.write_parameter = AsyncMock(return_value=result)
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="Failed to set"):
            await entity.async_set_native_value(150)

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Values outside 50-10000 W (and non-integers) raise."""
        coordinator = _mock_coordinator()
        entity = StartDischargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(49)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(10001)
        with pytest.raises(HomeAssistantError, match="integer"):
            await entity.async_set_native_value(100.5)


class TestStartChargePowerNumber:
    """Start Charge P_import threshold (HOLD 117, signed W, GH #272).

    Protocol register table: ``PtoUserStartchg``, scale 1 W, default
    **-50 W** (signed: start charging when P_to_user drops below the value,
    i.e. exporting more than 50 W). The register is absent from the Luxpower
    web UI AND from the cloud API (remoteRead names reg 117 ``<EMPTY>`` on
    every scanned model, incl. LXP-EU), so the entity is LOCAL/HYBRID-only,
    reads the raw "117" key read_named_parameters surfaces for unmapped
    registers, writes the raw register (two's-complement masked), and ships
    disabled by default (documentation-only register, GH #272 asks for it
    for field testing).
    """

    def test_entity_definition_signed_w(self):
        """Signed watt range, disabled by default (untested register)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = StartChargePowerNumber(coordinator, "1234567890")
        assert entity.native_unit_of_measurement == "W"
        assert entity.native_min_value == -10000
        assert entity.native_max_value == 10000
        assert entity.native_step == 1
        assert entity.unique_id.endswith("_start_charge_power_threshold")
        assert entity.translation_key == "start_charge_power_threshold"
        assert getattr(entity, "_attr_name", None) is None
        # Untested register: disabled by default
        assert entity.entity_registry_enabled_default is False

    def test_native_value_positive_raw(self):
        """Positive raw watt values pass through unchanged."""
        coordinator = _mock_coordinator(local_only=True, parameters={"117": 100})
        entity = StartChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 100

    def test_native_value_signed_negative(self):
        """Protocol default -50 W arrives as two's-complement 65486."""
        coordinator = _mock_coordinator(local_only=True, parameters={"117": 65486})
        entity = StartChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == -50

    def test_native_value_hybrid_transport(self):
        """HYBRID with an attached transport reads the same raw key."""
        coordinator = _mock_coordinator(has_local=True, parameters={"117": 65486})
        entity = StartChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == -50

    def test_native_value_rejects_out_of_range(self):
        """Garbage outside ±10000 W reads as None."""
        coordinator = _mock_coordinator(local_only=True, parameters={"117": 20000})
        entity = StartChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_write_local_raw_register_positive(self):
        """Positive watts write the raw register value as-is."""
        coordinator = _mock_coordinator(has_local=True)
        coordinator.write_raw_parameter = AsyncMock(return_value=True)
        entity = StartChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(250)

        coordinator.write_raw_parameter.assert_called_once_with(
            117, 250, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_write_local_raw_register_negative_masked(self):
        """-50 W writes the two's-complement 65486 (W round-trip with the
        signed read decode above)."""
        coordinator = _mock_coordinator(has_local=True)
        coordinator.write_raw_parameter = AsyncMock(return_value=True)
        entity = StartChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(-50)

        coordinator.write_raw_parameter.assert_called_once_with(
            117, 65486, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_write_requires_local_transport(self):
        """Without a local transport the write fails clearly: the cloud API
        has no parameter name for register 117."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        coordinator.write_raw_parameter = AsyncMock(return_value=True)
        entity = StartChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="local"):
            await entity.async_set_native_value(-50)
        coordinator.write_raw_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Values outside ±10000 W (and non-integers) raise."""
        coordinator = _mock_coordinator(has_local=True)
        coordinator.write_raw_parameter = AsyncMock(return_value=True)
        entity = StartChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(10001)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(-10001)
        with pytest.raises(HomeAssistantError, match="integer"):
            await entity.async_set_native_value(-50.5)


class TestStopDischargeVoltageNumber:
    """Forced-discharge Stop Discharge Voltage (reg 202, V — bead eg4-aa3t).

    The voltage-regime counterpart of the reg-83 stop SOC. Register stores
    decivolts (raw 400 == 40.0 V, raw-verified 2026-06-11); the cloud takes
    float volts [40, 56] (live round-trip 40 -> 41.5 -> 40 V on an 18kPV
    and a FlexBOSS21).
    """

    def test_definition_and_regime_key(self):
        coordinator = _mock_coordinator()
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        assert entity.native_min_value == 40.0
        assert entity.native_max_value == 56.0
        assert entity.native_step == 0.1
        assert entity.native_unit_of_measurement == "V"
        assert entity.unique_id.endswith("_stop_discharge_voltage")
        # Voltage-regime stop limit: participates in reg-179 discharge gating
        assert entity._control_key == "stop_discharge_voltage"

    def test_regime_classification(self):
        """The entity belongs to the discharge/Voltage regime set — the
        cloud UI gates the field with disChgVoltEnable, the voltage twin
        of forced_discharge_soc_limit's disChgSocEnable."""
        from custom_components.eg4_web_monitor.const.device_types import (
            DISCHARGE_VOLTAGE_CONTROLS,
            control_side_and_mode,
        )

        assert "stop_discharge_voltage" in DISCHARGE_VOLTAGE_CONTROLS
        assert control_side_and_mode("stop_discharge_voltage") == (
            "discharge",
            "voltage",
        )

    def test_native_value_scales_decivolts_local(self):
        """LOCAL: raw decivolts from the parameter cache scale to volts
        (raw 400 -> 40.0 V, the 2026-06-11 raw-verified pair)."""
        coordinator = _mock_coordinator(
            local_only=True,
            has_local=True,
            parameters={"_12K_HOLD_STOP_DISCHG_VOLT": 400},
        )
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        assert entity.native_value == 40.0

    def test_native_value_cloud_already_volts(self):
        """CLOUD: already-scaled float volts must NOT be divided again
        (the PVStartVoltage cloud-broken failure class)."""
        coordinator = _mock_coordinator(parameters={"_12K_HOLD_STOP_DISCHG_VOLT": 41.5})
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        assert entity.native_value == 41.5

    def test_native_value_hybrid_decivolts(self):
        """HYBRID with attached transport: params hold raw decivolts and
        the magnitude normalization (>=100 -> /10) applies."""
        coordinator = _mock_coordinator(
            has_local=True,
            local_only=False,
            parameters={"_12K_HOLD_STOP_DISCHG_VOLT": 415},
        )
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        assert entity.native_value == 41.5

    @pytest.mark.asyncio
    async def test_write_local_decivolts(self):
        """Local transport writes raw decivolts by name (41.5 V -> 415)."""
        coordinator = _mock_coordinator(has_local=True)
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(41.5)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "_12K_HOLD_STOP_DISCHG_VOLT"
        assert call_args[0][1] == 415

    @pytest.mark.asyncio
    async def test_write_cloud_float_volts(self):
        """Cloud mode calls inverter.set_stop_discharge_voltage(voltage=...)
        — the cloud API takes float volts directly."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(41.5)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_stop_discharge_voltage.assert_called_once_with(voltage=41.5)

    @pytest.mark.asyncio
    async def test_write_validation(self):
        """Volts outside [40, 56] raise HomeAssistantError (both directions);
        fractional volts are allowed (cloud-verified 41.5); NaN is rejected
        by the non-negated chained comparison (codex r1 LOW)."""
        coordinator = _mock_coordinator()
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(39.9)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(56.1)
        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(float("nan"))

    @pytest.mark.asyncio
    async def test_write_normalizes_to_tenth_volt(self):
        """Service-call values are normalized to 0.1 V before validation and
        write, so local and cloud paths carry the same value and boundary
        float artifacts are accepted (codex r1 LOW): 56.0000001 -> 56.0 is
        valid, and 41.55 (float 41.549999...) writes 415, not 416."""
        coordinator = _mock_coordinator(has_local=True)
        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(56.0000001)
        assert coordinator.write_named_parameter.call_args[0][1] == 560

        await entity.async_set_native_value(41.55)
        assert coordinator.write_named_parameter.call_args[0][1] == 415

    @pytest.mark.asyncio
    async def test_cloud_write_guard_on_old_pylxpweb(self):
        """Installed pylxpweb without set_stop_discharge_voltage raises a
        clean error instead of AttributeError (version-skew guard — the
        setter ships after 0.9.36b5)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        inverter = coordinator.get_inverter_object("1234567890")
        del inverter.set_stop_discharge_voltage

        entity = StopDischargeVoltageNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="newer pylxpweb"):
            await entity.async_set_native_value(41.5)


# ── EG4_OFFGRID grid-tied control suppression (PR #220 / #197, eg4-juzg) ──


class TestOffgridGridTiedNumberSuppression:
    """Peak Shaving / Forced Discharge numbers are inert on EG4_OFFGRID.

    Mirrors the switch-side suppression: the SNA platform (12000XP/6000XP)
    has no grid sellback or grid-parallel operation, so the Grid Peak Shaving
    Power, Forced Discharge Power and Forced Discharge SOC Limit numbers are
    suppressed for positively-identified EG4_OFFGRID devices.
    """

    @pytest.mark.asyncio
    async def test_offgrid_family_suppresses_grid_tied_numbers(self, hass):
        coordinator = _mock_coordinator(model="6000XP")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "GridPeakShavingPowerNumber" not in type_names
        assert "ForcedDischargePowerNumber" not in type_names
        assert "ForcedDischargeSOCLimitNumber" not in type_names
        # AC Charge SOC Limit (reg 67) is family-rejected on offgrid (GH #331)
        assert "ACChargeSOCLimitNumber" not in type_names
        # ... replaced by the family's real AC-charge SOC window (regs 160/161)
        assert "ACChargeStartBatterySOCNumber" in type_names
        assert "ACChargeEndBatterySOCNumber" in type_names
        # The rest of the control set is unaffected: 19 grid-tied (incl. Stop
        # Discharge Voltage, eg4-aa3t) minus the 3 suppressed grid-tied controls
        # minus Grid Sell Back (no sell-back on offgrid, GH #135) minus the
        # reg-67 AC Charge SOC Limit (GH #331) = 14, plus the HTTP-only Quick
        # Charge Duration preference (#251) and the two reg-160/161 AC-charge
        # SOC window numbers (GH #331) = 17.
        assert len(entities) == 17
        assert "ACChargePowerNumber" in type_names
        assert "OffGridSOCCutoffNumber" in type_names
        assert "SystemChargeVoltLimitNumber" in type_names
        assert "QuickChargeDurationNumber" in type_names

    @pytest.mark.asyncio
    async def test_xp_model_without_family_fails_open(self, hass):
        """Model name alone must not suppress — positive family ID required."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "GridPeakShavingPowerNumber" in type_names
        assert "ForcedDischargePowerNumber" in type_names
        assert "ForcedDischargeSOCLimitNumber" in type_names
        # Fail-open keeps the reg-67 AC Charge SOC Limit too (GH #331), and
        # the offgrid-only reg-160/161 window is NOT created without a
        # positive family ID.
        assert "ACChargeSOCLimitNumber" in type_names
        assert "ACChargeStartBatterySOCNumber" not in type_names
        assert "ACChargeEndBatterySOCNumber" not in type_names
        # Fail-open keeps every control except Grid Sell Back, whose own
        # XP-model gate (GH #135) fires on the model name alone = 18, plus the
        # HTTP-only Quick Charge Duration preference (#251) = 19
        assert len(entities) == 19

    @pytest.mark.asyncio
    async def test_repairs_issue_for_previously_registered_numbers(self, hass):
        """A previously-registered suppressed number raises the Repairs issue."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        # 6000XP → clean model "6000xp" (clean_model_name with underscores).
        registry.async_get_or_create(
            "number", DOMAIN, f"6000xp_{serial}_forced_discharge_power"
        )

        coordinator = _mock_coordinator(model="6000XP", serial=serial)
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_grid_controls_removed_{serial}"
        )
        assert issue is not None

    @pytest.mark.asyncio
    async def test_repairs_issue_for_legacy_model_prefix_uid(self, hass):
        """Suffix matching catches registry entries from a misdetected-model era.

        A 6000XP that ran as model "Unknown" before the beta.2 family fixes
        (#219/#222) registered numbers under the ``unknown_`` prefix. The
        Repairs probe must still fire for those (codex MEDIUM fix).
        """
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        registry.async_get_or_create(
            "number", DOMAIN, f"unknown_{serial}_forced_discharge_power"
        )

        coordinator = _mock_coordinator(model="6000XP", serial=serial)
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_grid_controls_removed_{serial}"
        )
        assert issue is not None


# ── Off-grid AC-charge SOC window (regs 160/161, GH #331) ─────────────


class TestOffgridACChargeSOCWindow:
    """Reg 67 is family-rejected on EG4_OFFGRID; regs 160/161 replace it.

    GH #331 (12000XP v2, CLOUD): writing HOLD_AC_CHARGE_SOC_LIMIT returns
    REMOTE_SET_ERROR, reg 67 reads 0 on the reference dump and the off-grid
    portal page omits it. The family's real AC-charge SOC window is
    HOLD_AC_CHARGE_START_BATTERY_SOC (160) / HOLD_AC_CHARGE_END_BATTERY_SOC
    (161), portal-verified writable holdParams.
    """

    @staticmethod
    def _offgrid_coordinator(**kwargs):
        coordinator = _mock_coordinator(model="12000XP", **kwargs)
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        return coordinator

    # ── Repairs issue (one-shot, previously-registered only) ──────────

    @pytest.mark.asyncio
    async def test_repairs_issue_for_previously_registered_soc_limit(self, hass):
        """A previously-registered reg-67 number raises the #331 Repairs issue."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        registry.async_get_or_create(
            "number", DOMAIN, f"12000xp_{serial}_ac_charge_soc_limit"
        )

        coordinator = self._offgrid_coordinator(serial=serial)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_ac_charge_soc_limit_removed_{serial}"
        )
        assert issue is not None

    @pytest.mark.asyncio
    async def test_no_repairs_issue_without_prior_registration(self, hass):
        """Fresh installs (nothing registered) get no Repairs noise."""
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        coordinator = self._offgrid_coordinator(serial=serial)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_ac_charge_soc_limit_removed_{serial}"
        )
        assert issue is None

    @pytest.mark.asyncio
    async def test_suffix_collision_serial_does_not_trigger_issue(self, hass):
        """Serial-boundary hardening (PR #332 review): a sibling device whose
        serial merely ENDS with this device's serial must not trip the probe
        ("1234567890" vs "91234567890" — endswith alone would match)."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        # The SIBLING's reg-67 entity — longer serial ending in ours.
        registry.async_get_or_create(
            "number", DOMAIN, f"12000xp_9{serial}_ac_charge_soc_limit"
        )

        coordinator = self._offgrid_coordinator(serial=serial)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_ac_charge_soc_limit_removed_{serial}"
        )
        assert issue is None

    @pytest.mark.asyncio
    async def test_bare_unique_id_still_triggers_issue(self, hass):
        """The boundary check keeps matching a bare {serial}_{key} unique ID
        (no model prefix at all) — the whole-ID branch of the probe."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        registry.async_get_or_create("number", DOMAIN, f"{serial}_ac_charge_soc_limit")

        coordinator = self._offgrid_coordinator(serial=serial)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_ac_charge_soc_limit_removed_{serial}"
        )
        assert issue is not None

    @pytest.mark.asyncio
    async def test_system_charge_soc_limit_does_not_trigger_issue(self, hass):
        """The suffix probe must not match the System Charge SOC Limit."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        registry.async_get_or_create(
            "number", DOMAIN, f"12000xp_{serial}_system_charge_soc_limit"
        )

        coordinator = self._offgrid_coordinator(serial=serial)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_ac_charge_soc_limit_removed_{serial}"
        )
        assert issue is None

    # ── Reads (parameter data, both key spellings) ────────────────────

    def test_start_soc_reads_named_param(self):
        coordinator = self._offgrid_coordinator(
            parameters={"HOLD_AC_CHARGE_START_BATTERY_SOC": 90}
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        assert entity.native_value == 90

    def test_end_soc_reads_named_param(self):
        coordinator = self._offgrid_coordinator(
            parameters={"HOLD_AC_CHARGE_END_BATTERY_SOC": 100}
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        assert entity.native_value == 100

    def test_end_soc_reads_named_param_local_only(self):
        """LOCAL register reads surface reg 161 under the same named key
        (pylxpweb >= 0.9.36b28 maps 161 in the transport name map)."""
        coordinator = self._offgrid_coordinator(
            has_local=True,
            local_only=True,
            has_http=False,
            parameters={"HOLD_AC_CHARGE_END_BATTERY_SOC": 95},
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        assert entity.native_value == 95

    def test_start_soc_out_of_range_reads_none(self):
        coordinator = self._offgrid_coordinator(
            parameters={"HOLD_AC_CHARGE_START_BATTERY_SOC": 150}
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_missing_params_read_none(self):
        coordinator = self._offgrid_coordinator(parameters={})
        assert (
            ACChargeStartBatterySOCNumber(coordinator, "1234567890").native_value
            is None
        )
        assert (
            ACChargeEndBatterySOCNumber(coordinator, "1234567890").native_value is None
        )

    # ── Writes (named local + named cloud holdParam, both registers) ──

    @pytest.mark.asyncio
    async def test_start_soc_local_write_uses_named_param(self):
        coordinator = self._offgrid_coordinator(has_local=True)
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(85)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_START_BATTERY_SOC", 85, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_end_soc_local_write_uses_named_param(self):
        """Reg 161 is in the transport name map (pylxpweb >= 0.9.36b28) —
        the End entity mirrors Start's named write path exactly."""
        coordinator = self._offgrid_coordinator(has_local=True)
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(95)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_END_BATTERY_SOC", 95, serial="1234567890"
        )
        coordinator.write_raw_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_soc_cloud_write_uses_named_holdparam(self):
        """CLOUD mode (the #331 reporter's): the portal's own holdParam write."""
        coordinator = self._offgrid_coordinator(has_local=False)
        coordinator.client.api.control.write_parameter = AsyncMock(
            return_value=MagicMock(success=True)
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(85)

        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            "1234567890", "HOLD_AC_CHARGE_START_BATTERY_SOC", "85"
        )
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_end_soc_cloud_write_uses_named_holdparam(self):
        coordinator = self._offgrid_coordinator(has_local=False)
        coordinator.client.api.control.write_parameter = AsyncMock(
            return_value=MagicMock(success=True)
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(100)

        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            "1234567890", "HOLD_AC_CHARGE_END_BATTERY_SOC", "100"
        )
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_end_soc_hybrid_local_failure_falls_back_to_cloud(self):
        """HYBRID: a failed local named write retries via the cloud named
        write and seeds the named parameter-cache key (#301 pattern)."""
        coordinator = self._offgrid_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("boom")
        )
        coordinator.client.api.control.write_parameter = AsyncMock(
            return_value=MagicMock(success=True)
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(95)

        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            "1234567890", "HOLD_AC_CHARGE_END_BATTERY_SOC", "95"
        )
        coordinator.note_parameters_written.assert_called_once_with(
            "1234567890",
            {"HOLD_AC_CHARGE_END_BATTERY_SOC": 95},
        )

    @pytest.mark.asyncio
    async def test_cloud_write_failure_raises(self):
        coordinator = self._offgrid_coordinator(has_local=False)
        coordinator.client.api.control.write_parameter = AsyncMock(
            return_value=MagicMock(success=False)
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="Failed to set"):
            await entity.async_set_native_value(85)

    # ── Range / integer validation ─────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", [-1, 101, 150])
    async def test_start_soc_rejects_out_of_range(self, bad_value):
        coordinator = self._offgrid_coordinator()
        entity = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="between 0-100"):
            await entity.async_set_native_value(bad_value)
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", [-1, 101, 150])
    async def test_end_soc_rejects_out_of_range(self, bad_value):
        coordinator = self._offgrid_coordinator()
        entity = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="between 0-100"):
            await entity.async_set_native_value(bad_value)
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_non_integer_values(self):
        coordinator = self._offgrid_coordinator()
        for entity in (
            ACChargeStartBatterySOCNumber(coordinator, "1234567890"),
            ACChargeEndBatterySOCNumber(coordinator, "1234567890"),
        ):
            _prep(entity)
            with pytest.raises(HomeAssistantError, match="integer value"):
                await entity.async_set_native_value(85.5)

    # ── Entity attributes ─────────────────────────────────────────────

    def test_entity_attributes(self):
        coordinator = self._offgrid_coordinator()
        start = ACChargeStartBatterySOCNumber(coordinator, "1234567890")
        end = ACChargeEndBatterySOCNumber(coordinator, "1234567890")
        assert start.unique_id == "12000xp_1234567890_ac_charge_start_battery_soc"
        assert end.unique_id == "12000xp_1234567890_ac_charge_end_battery_soc"
        for entity in (start, end):
            assert entity.native_min_value == 0
            assert entity.native_max_value == 100
            assert entity.native_step == 1
            # ENABLED by default: the family's primary AC-charge SOC control
            # (the #331 reporter's automation target).
            assert entity.registry_entry is None
            assert entity.entity_registry_enabled_default is True


# ── QuickChargeDurationNumber (preference, no register) ───────────────


class TestQuickChargeDurationNumber:
    """Test the Quick Charge Duration preference number entity."""

    def test_default_value_is_60(self):
        """With no register reading and no stored preference, defaults to 60."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_value == 60

    def test_reads_stored_preference_without_register(self):
        """Cloud (no quickChargeMinute) returns the per-serial preference."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = 120
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_value == 120

    def test_native_value_mirrors_register_while_charging(self):
        """LOCAL/HYBRID: native_value mirrors the live holding reg 234 value
        (quickChargeMinute), not the stored preference."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = 60  # preference (ignored)
        coordinator.data["devices"]["1234567890"]["quick_charge_status"] = {
            "hasUnclosedQuickChargeTask": True,
            "remainTimeBeforeQuickChargeStop": 320,
            "quickChargeMinute": 58,
        }
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_value == 58
        # Mirrors the int register, never a one-decimal float ("58", not "58.0").
        assert isinstance(entity.native_value, int)
        assert not isinstance(entity.native_value, bool)

    @pytest.mark.parametrize(
        ("preference", "register"),
        [
            # Firmware zeroes reg 234 at session end — the idle register
            # mirror was a useless constant 0, the preference must win.
            pytest.param(45, 0, id="idle-register-zeroed"),
            # Even a nonzero idle reg 234 reading (e.g. mid-transition) does
            # not override — the register only wins while a charge runs.
            pytest.param(60, 2, id="idle-register-nonzero"),
            # Cloud status has no register (quickChargeMinute=None).
            pytest.param(45, None, id="cloud-register-absent"),
        ],
    )
    def test_native_value_idle_shows_preference_not_register(
        self, preference, register
    ):
        """Idle, the entity shows the start preference the switch will apply,
        regardless of what (if anything) the register read reports."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = preference
        coordinator.data["devices"]["1234567890"]["quick_charge_status"] = {
            "hasUnclosedQuickChargeTask": False,
            "remainTimeBeforeQuickChargeStop": 0,
            "quickChargeMinute": register,
        }
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_value == preference

    def test_bounds(self):
        """Entity advertises the 1–1440 minute bounds."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_min_value == 1
        assert entity.native_max_value == 1440
        assert entity.native_step == 1
        assert entity.native_unit_of_measurement == "min"

    @pytest.mark.asyncio
    async def test_set_persists_to_coordinator(self):
        """Setting the value stores it on the coordinator (no inverter write)."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        assert coordinator._quick_charge_minutes["1234567890"] == 45
        # Preference only — no parameter write to the inverter.
        coordinator.write_named_parameter.assert_not_called()
        entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_coerces_to_int(self):
        """Float values are stored as ints."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        assert coordinator._quick_charge_minutes["1234567890"] == 90

    @pytest.mark.asyncio
    async def test_set_cloud_only_does_not_write_register(self):
        """Cloud-only (no local transport): preference only, no reg 234 write."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        assert coordinator._quick_charge_minutes["1234567890"] == 45
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_local_active_writes_reg234(self):
        """LOCAL/HYBRID with a running charge (live check True): reg 234 is
        written live to extend/reduce the active charge. No cloud preference is
        stored — on local the entity mirrors the register, not a preference."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=True)
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        coordinator.is_quick_charge_active_live.assert_awaited_once_with("1234567890")
        coordinator.write_named_parameter.assert_called_once()
        args = coordinator.write_named_parameter.call_args
        assert args.args[0] == "SNA_HOLD_QUICK_CHARGE_MINUTE"
        assert args.args[1] == 45
        assert args.kwargs.get("serial") == "1234567890"
        # No hidden cloud preference stored on the local path.
        assert "1234567890" not in coordinator._quick_charge_minutes

    @pytest.mark.asyncio
    async def test_set_local_active_seeds_stale_cache_so_state_reflects_write(self):
        """The quick-charge status cache can be up to 30s stale. After a live
        reg-234 write confirmed by the fresh active check, a stale-IDLE cache
        would make the immediately-published state fall back to the untouched
        preference — the write must seed the cache so native_value shows the
        accepted value (codex P2)."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=True)
        coordinator._quick_charge_minutes["1234567890"] = 60  # untouched pref
        coordinator.data["devices"]["1234567890"]["quick_charge_status"] = {
            "hasUnclosedQuickChargeTask": False,  # stale: pre-start reading
            "quickChargeMinute": 0,
        }
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        status = coordinator.data["devices"]["1234567890"]["quick_charge_status"]
        assert status["hasUnclosedQuickChargeTask"] is True
        assert status["quickChargeMinute"] == 45
        assert entity.native_value == 45
        # The stored start preference is a one-off live adjustment away —
        # it must remain untouched.
        assert coordinator._quick_charge_minutes["1234567890"] == 60

    @pytest.mark.asyncio
    async def test_set_local_idle_stores_start_preference(self):
        """LOCAL/HYBRID while quick charge is OFF (live check False): the value
        is stored as the start preference the switch applies at the next start
        (the reg 234 half of the paired-frame start) — no register write (a
        lone idle reg 234 write is firmware-rejected, #251)."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        # is_quick_charge_active_live defaults to False (idle).
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        assert coordinator._quick_charge_minutes["1234567890"] == 45
        coordinator.write_named_parameter.assert_not_called()
        entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_local_uses_live_check_not_cached_status(self):
        """The reg 234 gate uses the LIVE active check, not the throttled cached
        quick_charge_status: a stale-active cache must not trigger a write the
        firmware would reject right after auto-expiry — the live False routes
        the value to the start-preference store instead."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        # Cache says active, but the live read says the charge has ended.
        coordinator.data["devices"]["1234567890"]["quick_charge_status"] = {
            "hasUnclosedQuickChargeTask": True
        }
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=False)
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(45)

        coordinator.write_named_parameter.assert_not_called()
        assert coordinator._quick_charge_minutes["1234567890"] == 45

    @pytest.mark.asyncio
    async def test_set_local_unknown_state_raises_and_does_not_commit(self):
        """If the live state can't be read (None), surface an error rather than
        silently storing the preference and reporting success — a failed live
        adjust must never look successful."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=None)
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_native_value(45)

        # Nothing committed: no preference store, no register write, no state.
        assert "1234567890" not in coordinator._quick_charge_minutes
        coordinator.write_named_parameter.assert_not_called()
        entity.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", [0, 1441, 30.5, float("nan"), float("inf")])
    async def test_set_rejects_invalid(self, bad_value):
        """Out-of-bounds or non-integer values raise without touching the store."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_native_value(bad_value)

        assert "1234567890" not in coordinator._quick_charge_minutes
        entity.async_write_ha_state.assert_not_called()

    def test_seed_restored_preference_valid_cloud_only(self):
        """A valid restored value seeds the store on a cloud-only install."""
        coordinator = _mock_coordinator()  # has_local=False -> cloud-only
        entity = QuickChargeDurationNumber(coordinator, "1234567890")

        entity._seed_restored_preference(120)

        assert coordinator._quick_charge_minutes["1234567890"] == 120

    def test_seed_restored_preference_seeds_with_local_transport(self):
        """LOCAL/HYBRID: the idle display IS the preference now, so the value
        RestoreNumber saved is the preference in the common (idle-shutdown)
        case and is seeded. (A restart mid-charge saves the live countdown —
        a shorter-than-intended preference until re-set, which beats losing
        the preference on every restart.)"""
        coordinator = _mock_coordinator(has_local=True, has_http=True)  # HYBRID
        entity = QuickChargeDurationNumber(coordinator, "1234567890")

        entity._seed_restored_preference(90)

        assert coordinator._quick_charge_minutes["1234567890"] == 90

    @pytest.mark.parametrize(
        "bad_value", [None, 30.5, float("nan"), float("inf"), 0, 99999]
    )
    def test_seed_restored_preference_ignores_invalid(self, bad_value):
        """Fractional, non-finite, out-of-range or missing values are ignored.

        A corrupt restore must never raise or store a bad value (the default
        then applies).
        """
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")

        entity._seed_restored_preference(bad_value)

        assert "1234567890" not in coordinator._quick_charge_minutes
        assert entity.native_value == 60

    def test_extra_state_attributes_carry_start_preference(self):
        """The attribute always exposes the real preference, even while the
        displayed state is the live countdown — it is the preference's own
        persistence channel across restarts."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = 90
        coordinator.data["devices"]["1234567890"]["quick_charge_status"] = {
            "hasUnclosedQuickChargeTask": True,
            "quickChargeMinute": 3,  # live countdown shown as state
        }
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        assert entity.native_value == 3
        assert entity.extra_state_attributes == {"start_preference": 90}

    @pytest.mark.asyncio
    async def test_async_added_to_hass_seeds_and_calls_super(self):
        """async_added_to_hass calls super (wires the listener) then restores
        (legacy path: no start_preference attribute in the saved state)."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)
        restored = MagicMock()
        restored.native_value = 120
        super_mock = AsyncMock()
        with (
            patch.object(RestoreNumber, "async_added_to_hass", super_mock),
            patch.object(entity, "async_get_last_state", AsyncMock(return_value=None)),
            patch.object(
                entity, "async_get_last_number_data", AsyncMock(return_value=restored)
            ),
        ):
            await entity.async_added_to_hass()

        # super() must be awaited (in production this is what wires the
        # coordinator listener through the base classes).
        super_mock.assert_awaited_once()
        assert coordinator._quick_charge_minutes["1234567890"] == 120

    @pytest.mark.asyncio
    async def test_restore_prefers_attribute_over_countdown_state(self):
        """A restart mid-charge saves the live countdown as the state, but the
        start_preference attribute carries the real preference — restore must
        seed the attribute, never the countdown (codex P1: a leaked countdown
        would silently become the next start's duration)."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)  # HYBRID
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)
        last_state = MagicMock()
        last_state.attributes = {"start_preference": 90}
        countdown = MagicMock()
        countdown.native_value = 3  # mid-charge countdown reading
        with (
            patch.object(RestoreNumber, "async_added_to_hass", AsyncMock()),
            patch.object(
                entity, "async_get_last_state", AsyncMock(return_value=last_state)
            ),
            patch.object(
                entity, "async_get_last_number_data", AsyncMock(return_value=countdown)
            ),
        ):
            await entity.async_added_to_hass()

        assert coordinator._quick_charge_minutes["1234567890"] == 90

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_attr",
        [None, "90", True, MagicMock()],
        ids=["absent", "string", "bool", "object"],
    )
    async def test_restore_invalid_attribute_falls_back_to_state(self, bad_attr):
        """A missing or non-numeric attribute (legacy save, corrupt data)
        falls back to the saved state value."""
        coordinator = _mock_coordinator()
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)
        last_state = MagicMock()
        last_state.attributes = {"start_preference": bad_attr}
        restored = MagicMock()
        restored.native_value = 120
        with (
            patch.object(RestoreNumber, "async_added_to_hass", AsyncMock()),
            patch.object(
                entity, "async_get_last_state", AsyncMock(return_value=last_state)
            ),
            patch.object(
                entity, "async_get_last_number_data", AsyncMock(return_value=restored)
            ),
        ):
            await entity.async_added_to_hass()

        assert coordinator._quick_charge_minutes["1234567890"] == 120

    @pytest.mark.asyncio
    async def test_async_added_to_hass_skips_fetch_when_session_value_set(self):
        """An in-session value is preserved and the restore fetch is skipped."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = 45
        entity = QuickChargeDurationNumber(coordinator, "1234567890")
        _prep(entity)
        get_last = AsyncMock()
        get_last_state = AsyncMock()
        with (
            patch.object(RestoreNumber, "async_added_to_hass", AsyncMock()),
            patch.object(entity, "async_get_last_state", get_last_state),
            patch.object(entity, "async_get_last_number_data", get_last),
        ):
            await entity.async_added_to_hass()

        assert coordinator._quick_charge_minutes["1234567890"] == 45
        get_last.assert_not_called()
        get_last_state.assert_not_called()
