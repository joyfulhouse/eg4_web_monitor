"""Tests for EG4 number entities and shared read/write helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_FORCED_CHG_POWER,
)
from custom_components.eg4_web_monitor.number import (
    async_setup_entry,
    ACChargePowerNumber,
    ACChargeSOCLimitNumber,
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
    ForcedDischargePowerNumber,
    ForcedDischargeSOCLimitNumber,
    OnGridSOCCutoffNumber,
    PVChargePowerNumber,
    SystemChargeSOCLimitNumber,
)


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
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.write_named_parameter = AsyncMock()
    coordinator.async_write_battery_control_mode = AsyncMock()
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
    mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
    mock_inverter.set_battery_charge_current = AsyncMock(return_value=True)
    mock_inverter.set_battery_discharge_current = AsyncMock(return_value=True)
    mock_inverter.set_grid_peak_shaving_power = AsyncMock(return_value=True)
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

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
        """FlexBOSS inverter creates 17 number entities (12 base + 5 voltage)."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 17
        type_names = [type(e).__name__ for e in entities]
        assert "ACChargePowerNumber" in type_names
        assert "SystemChargeSOCLimitNumber" in type_names
        assert "PVStartVoltageNumber" in type_names
        # Forced discharge controls (regs 82/83, GH #207 / PR #249)
        assert "ForcedDischargePowerNumber" in type_names
        assert "ForcedDischargeSOCLimitNumber" in type_names
        # New voltage limit controls
        assert "SystemChargeVoltLimitNumber" in type_names
        assert "OnGridCutoffVoltageNumber" in type_names
        assert "OffGridCutoffVoltageNumber" in type_names
        assert "ACChargeStartVoltageNumber" in type_names
        assert "ACChargeEndVoltageNumber" in type_names

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
    async def test_async_setup_entry_with_xp(self, hass):
        """XP device creates number entities."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) > 0


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
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 200},  # > 100
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value is None


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
