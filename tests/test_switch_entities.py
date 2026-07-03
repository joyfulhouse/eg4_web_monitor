"""Tests for EG4 switch entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    INVERTER_FAMILY_EG4_OFFGRID,
    PARAM_FUNC_AC_CHARGE,
    PARAM_FUNC_BATTERY_BACKUP_CTRL,
    PARAM_FUNC_CHARGE_LAST,
    PARAM_FUNC_EPS_EN,
    PARAM_FUNC_GREEN_EN,
    PARAM_FUNC_GRID_PEAK_SHAVING,
    WORKING_MODES,
)
import custom_components.eg4_web_monitor.switch as switch_module
from custom_components.eg4_web_monitor.switch import (
    _supports_eps_battery_backup,
    async_setup_entry,
    EG4QuickChargeSwitch,
    EG4BatteryBackupSwitch,
    EG4ChargeLastSwitch,
    EG4OffGridModeSwitch,
    EG4WorkingModeSwitch,
    EG4DSTSwitch,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    has_http: bool = True,
    has_local: bool = False,
    local_only: bool = False,
    transport_attached: bool | None = None,
    model: str = "FlexBOSS21",
    serial: str = "1234567890",
    device_data: dict | None = None,
    parameters: dict | None = None,
    station_data: dict | None = None,
) -> MagicMock:
    """Build a mock EG4DataUpdateCoordinator for switch tests."""
    coordinator = MagicMock()
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.plant_id = "plant_123"
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock()
    coordinator.write_named_parameter = AsyncMock()
    # Real dict (not an auto-Mock) so QuickChargeDurationNumber / the Quick
    # Charge switch read a true per-serial duration preference.
    coordinator._quick_charge_minutes = {}

    # Build coordinator.data
    dev_data = device_data if device_data is not None else {}
    data: dict = {
        "devices": {
            serial: {"type": "inverter", "model": model, **dev_data},
        },
        "parameters": {serial: parameters or {}},
    }
    if station_data is not None:
        data["station"] = station_data
    coordinator.data = data

    # Mock inverter object
    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    mock_inverter.enable_quick_charge = AsyncMock(return_value=True)
    mock_inverter.disable_quick_charge = AsyncMock(return_value=True)
    mock_inverter.enable_battery_backup = AsyncMock(return_value=True)
    mock_inverter.disable_battery_backup = AsyncMock(return_value=True)
    mock_inverter.enable_green_mode = AsyncMock(return_value=True)
    mock_inverter.disable_green_mode = AsyncMock(return_value=True)
    mock_inverter.enable_ac_charge_mode = AsyncMock(return_value=True)
    mock_inverter.disable_ac_charge_mode = AsyncMock(return_value=True)
    mock_inverter.enable_pv_charge_priority = AsyncMock(return_value=True)
    mock_inverter.disable_pv_charge_priority = AsyncMock(return_value=True)
    mock_inverter.enable_forced_discharge = AsyncMock(return_value=True)
    mock_inverter.disable_forced_discharge = AsyncMock(return_value=True)
    mock_inverter.enable_peak_shaving_mode = AsyncMock(return_value=True)
    mock_inverter.disable_peak_shaving_mode = AsyncMock(return_value=True)
    mock_inverter.enable_battery_backup_ctrl = AsyncMock(return_value=True)
    mock_inverter.disable_battery_backup_ctrl = AsyncMock(return_value=True)
    mock_inverter.enable_feed_in_grid = AsyncMock(return_value=True)
    mock_inverter.disable_feed_in_grid = AsyncMock(return_value=True)
    mock_inverter.enable_pv_sell_to_grid = AsyncMock(return_value=True)
    mock_inverter.disable_pv_sell_to_grid = AsyncMock(return_value=True)
    # pylxpweb transport attachment: None for cloud, object for local/HYBRID
    # (mirrors BaseInverter.transport; drives the local-raw parameter gate)
    if transport_attached is None:
        transport_attached = has_local
    mock_inverter.transport = object() if transport_attached else None
    # Config-based hybrid transport predicate mirrors the attachment state
    # by default (a configured transport is normally attached by setup time)
    coordinator.has_configured_local_transport = MagicMock(
        return_value=transport_attached
    )
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    # Cloud client (function-control API) for FUNC_ params without
    # dedicated enable/disable inverter methods (e.g. FUNC_CHARGE_LAST)
    if has_http:
        control_response = MagicMock()
        control_response.success = True
        mock_client = MagicMock()
        mock_client.api.control.control_function = AsyncMock(
            return_value=control_response
        )
        coordinator.client = mock_client
    else:
        coordinator.client = None

    # Station device info
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.get_station_device_info = MagicMock(return_value=None)

    # Station object for DST switch
    mock_station = MagicMock()
    mock_station.set_daylight_saving_time = AsyncMock(return_value=True)
    coordinator.station = mock_station

    return coordinator


def _prep(entity: object) -> None:
    """Prepare entity for action tests (set hass + entity_id)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "switch.test_entity"  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


# ── _supports_eps_battery_backup ─────────────────────────────────────


class TestSupportsEpsBatteryBackup:
    """Test the EPS feature-detection helper."""

    def test_feature_offgrid_family(self):
        """Off-grid family with supports_off_grid=True -> True."""
        device_data = {
            "features": {
                "inverter_family": INVERTER_FAMILY_EG4_OFFGRID,
                "supports_off_grid": True,
            }
        }
        assert _supports_eps_battery_backup(device_data) is True

    def test_feature_hybrid_family(self):
        """Hybrid family without explicit off_grid flag defaults True."""
        device_data = {"features": {"inverter_family": "EG4_HYBRID"}}
        assert _supports_eps_battery_backup(device_data) is True

    def test_fallback_xp_model(self):
        """XP models are excluded when no features available."""
        assert _supports_eps_battery_backup({"model": "12000XP"}) is False
        assert _supports_eps_battery_backup({"model": "6000xp"}) is False

    def test_fallback_flexboss_model(self):
        """FlexBOSS models are supported when no features available."""
        assert _supports_eps_battery_backup({"model": "FlexBOSS21"}) is True


# ── async_setup_entry ────────────────────────────────────────────────


class TestSwitchPlatformSetup:
    """Test switch platform setup."""

    @pytest.mark.asyncio
    async def test_setup_with_inverter(self, hass):
        """FlexBOSS creates quick charge + EPS + off-grid + working modes."""
        coordinator = _mock_coordinator(has_http=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4QuickChargeSwitch" in type_names
        assert "EG4BatteryBackupSwitch" in type_names
        assert "EG4OffGridModeSwitch" in type_names
        assert "EG4ChargeLastSwitch" in type_names
        assert any(n == "EG4WorkingModeSwitch" for n in type_names)

    @pytest.mark.asyncio
    async def test_setup_sna_15k_offgrid_creates_controls(self, hass):
        """#259: cloud "SNA-US 15K" (EG4_OFFGRID) gets control switches.

        Its deviceTypeText matches no SUPPORTED_INVERTER_MODELS substring
        ("15k" is not in the set, no "xp"/"sna" token), so the legacy
        model-only gate created zero switches. The detected family backstops
        the gate so the Controls block is populated again.
        """
        coordinator = _mock_coordinator(
            has_http=True,
            model="SNA-US 15K",
            device_data={"features": {"inverter_family": "EG4_OFFGRID"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4QuickChargeSwitch" in type_names
        assert "EG4OffGridModeSwitch" in type_names
        assert "EG4ChargeLastSwitch" in type_names

    @pytest.mark.asyncio
    async def test_setup_unknown_model_and_family_creates_no_controls(self, hass):
        """No substring match and no known family -> no inverter switches.

        Guards the family backstop from over-firing: a genuinely unrecognized
        device must still be skipped (only the station DST switch may remain).
        """
        coordinator = _mock_coordinator(
            has_http=True,
            model="SNA-US 15K",
            device_data={"features": {"inverter_family": "UNKNOWN"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4QuickChargeSwitch" not in type_names
        assert "EG4OffGridModeSwitch" not in type_names
        assert "EG4ChargeLastSwitch" not in type_names

    @pytest.mark.asyncio
    async def test_setup_quick_charge_local_mode(self, hass):
        """LOCAL mode with a configured transport creates QuickCharge.

        Quick Charge now works over local registers 233/234, so a supported
        model with a local transport gets the switch even without the cloud API.
        """
        coordinator = _mock_coordinator(has_http=False, has_local=True, local_only=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4QuickChargeSwitch" in type_names

    @pytest.mark.asyncio
    async def test_setup_no_quick_charge_without_transport(self, hass):
        """Neither cloud API nor local transport -> no QuickCharge switch."""
        coordinator = _mock_coordinator(
            has_http=False, has_local=False, local_only=False
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4QuickChargeSwitch" not in type_names

    @pytest.mark.asyncio
    async def test_setup_skips_gridboss(self, hass):
        """GridBOSS devices should not get switch entities."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"]["gb123"] = {"type": "gridboss", "model": "GridBOSS"}
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        for entity in entities:
            if hasattr(entity, "_serial"):
                assert entity._serial != "gb123"

    @pytest.mark.asyncio
    async def test_setup_xp_skips_eps(self, hass):
        """XP model should not get EPS Battery Backup switch."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4BatteryBackupSwitch" not in type_names

    @pytest.mark.asyncio
    async def test_setup_creates_dst_switch_with_station(self, hass):
        """Station data present -> DST switch created."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": True})
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        type_names = [type(e).__name__ for e in entities]
        assert "EG4DSTSwitch" in type_names

    @pytest.mark.asyncio
    async def test_local_only_includes_all_modbus_working_modes(
        self, hass, monkeypatch
    ):
        """LOCAL-only mode creates switches for all Modbus-backed working modes.

        All wired working modes have holding register bit field mappings:
        - FUNC_AC_CHARGE (reg 21 bit 7), FUNC_FORCED_CHG_EN (reg 21 bit 11),
          FUNC_FORCED_DISCHG_EN (reg 21 bit 10), FUNC_GRID_PEAK_SHAVING
          (reg 179 bit 7), FUNC_BATTERY_BACKUP_CTRL (reg 233 bit 1),
          FUNC_FEED_IN_GRID_EN (reg 21 bit 15), and — since the 2026-06-12
          bit-3 pin — FUNC_PV_SELL_TO_GRID_EN (reg 179 bit 3).
        Regression test for issue #153; the local-map probe is pinned to the
        post-pin (pylxpweb >= 0.9.36b6) answer so the test encodes the new
        contract deterministically on either side of the coupling.
        """
        monkeypatch.setattr(
            switch_module, "_local_params_can_carry", lambda param: True
        )
        coordinator = _mock_coordinator(has_http=False, has_local=True, local_only=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        working_modes = [e for e in entities if isinstance(e, EG4WorkingModeSwitch)]
        working_mode_params = {e._mode_config["param"] for e in working_modes}

        # All of these have Modbus register support
        assert "FUNC_AC_CHARGE" in working_mode_params  # Register 21, bit 7
        assert "FUNC_FORCED_CHG_EN" in working_mode_params  # Register 21, bit 11
        assert "FUNC_FORCED_DISCHG_EN" in working_mode_params  # Register 21, bit 10
        assert "FUNC_GRID_PEAK_SHAVING" in working_mode_params  # Register 179, bit 7
        assert "FUNC_BATTERY_BACKUP_CTRL" in working_mode_params  # Register 233, bit 1
        # Grid Sell Back has a pinned register (21 bit 15) -> available locally
        assert "FUNC_FEED_IN_GRID_EN" in working_mode_params
        # Export PV Only pinned to reg 179 bit 3 (GH #135) -> available locally
        assert "FUNC_PV_SELL_TO_GRID_EN" in working_mode_params

    @pytest.mark.asyncio
    async def test_cloud_mode_includes_all_working_modes(self, hass):
        """Cloud mode should create ALL working mode switches."""
        coordinator = _mock_coordinator(
            has_http=True, has_local=False, local_only=False
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        working_modes_created = [
            e for e in entities if isinstance(e, EG4WorkingModeSwitch)
        ]
        working_mode_params = {e._mode_config["param"] for e in working_modes_created}

        # Cloud mode creates all working modes including cloud-only ones
        assert "FUNC_AC_CHARGE" in working_mode_params
        assert "FUNC_BATTERY_BACKUP_CTRL" in working_mode_params
        assert "FUNC_GRID_PEAK_SHAVING" in working_mode_params
        # Grid sell controls (GH #135): both available with cloud parameters
        assert "FUNC_FEED_IN_GRID_EN" in working_mode_params
        assert "FUNC_PV_SELL_TO_GRID_EN" in working_mode_params

    @pytest.mark.asyncio
    async def test_setup_never_writes_to_inverter(self, hass):
        """Entity construction / async_setup_entry must never write.

        Regression guard for the no-write-on-startup invariant: creating
        switch entities (including Charge Last) must not touch the inverter
        via either the local named-parameter path or the cloud
        function-control API. Writes may only happen from explicit
        turn_on/turn_off service calls.
        """
        coordinator = _mock_coordinator(has_http=True, has_local=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        # Charge Last entity was created via setup...
        assert any(isinstance(e, EG4ChargeLastSwitch) for e in entities)
        # ...without any write on either transport
        coordinator.write_named_parameter.assert_not_called()
        coordinator.client.api.control.control_function.assert_not_called()


# ── QuickChargeSwitch ────────────────────────────────────────────────


class TestQuickChargeSwitch:
    """Test QuickCharge switch entity."""

    def test_is_on_default_false(self):
        """Default state should be False."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        assert switch.is_on is False

    def test_is_on_from_status(self):
        """Device data quick_charge_status drives is_on."""
        coordinator = _mock_coordinator(
            device_data={"quick_charge_status": {"hasUnclosedQuickChargeTask": True}}
        )
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        assert switch.is_on is True

    def test_is_on_optimistic_overrides(self):
        """Optimistic state takes precedence."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        switch._optimistic_state = True
        assert switch.is_on is True

    def test_available_on_healthy_coordinator(self):
        """Available with healthy coordinator + inverter device."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        assert switch.available is True

    def test_unavailable_on_coordinator_failure(self):
        """Coordinator failure makes the switch unavailable (parity with
        number/time entities — EG4BaseSwitch gates on last_update_success)."""
        coordinator = _mock_coordinator()
        coordinator.last_update_success = False
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        assert switch.available is False

    @pytest.mark.asyncio
    async def test_turn_on(self):
        """Turn on calls enable_quick_charge with the default duration (60)."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_quick_charge.assert_called_once_with(minute=60)

    @pytest.mark.asyncio
    async def test_turn_on_uses_stored_duration(self):
        """Turn on forwards the per-serial duration preference as minute."""
        coordinator = _mock_coordinator()
        coordinator._quick_charge_minutes["1234567890"] = 25
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_quick_charge.assert_called_once_with(minute=25)

    @pytest.mark.asyncio
    async def test_turn_off(self):
        """Turn off calls disable_quick_charge via cloud API (no minute)."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_quick_charge.assert_called_once_with()

    def test_extra_attributes_minutes_remaining(self):
        """A running timed charge exposes minutes_remaining (rounded up)."""
        coordinator = _mock_coordinator(
            device_data={
                "quick_charge_status": {
                    "hasUnclosedQuickChargeTask": True,
                    "remainTimeBeforeQuickChargeStop": 598,
                    "unclosedQuickChargeTaskId": 42,
                    "unclosedQuickChargeTaskStatus": "WAIT_CHARGE",
                }
            }
        )
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        attrs = switch.extra_state_attributes
        assert attrs is not None
        assert attrs["minutes_remaining"] == 10
        assert attrs["task_id"] == 42
        assert attrs["task_status"] == "WAIT_CHARGE"

    def test_extra_attributes_no_minutes_remaining_when_idle(self):
        """No minutes_remaining attribute when there is no remaining time."""
        coordinator = _mock_coordinator(
            device_data={
                "quick_charge_status": {
                    "hasUnclosedQuickChargeTask": False,
                    "remainTimeBeforeQuickChargeStop": 0,
                }
            }
        )
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        attrs = switch.extra_state_attributes
        assert attrs is None or "minutes_remaining" not in attrs


# ── BatteryBackupSwitch ──────────────────────────────────────────────


class TestBatteryBackupSwitch:
    """Test BatteryBackup (EPS) switch entity."""

    def test_is_on_from_status_dict(self):
        """battery_backup_status dict drives is_on."""
        coordinator = _mock_coordinator(
            device_data={"battery_backup_status": {"enabled": True}}
        )
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        assert switch.is_on is True

    def test_is_on_fallback_to_params(self):
        """Falls back to FUNC_EPS_EN parameter."""
        coordinator = _mock_coordinator(parameters={"FUNC_EPS_EN": True})
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        assert switch.is_on is True

    def test_is_on_false_when_param_false(self):
        """FUNC_EPS_EN=False -> is_on False."""
        coordinator = _mock_coordinator(parameters={"FUNC_EPS_EN": False})
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_local(self):
        """Local transport: writes PARAM_FUNC_EPS_EN."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_EPS_EN, True, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_on_cloud(self):
        """Cloud only: calls enable_battery_backup."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_battery_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_local(self):
        """Local transport: writes PARAM_FUNC_EPS_EN=False."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_EPS_EN, False, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_off_cloud(self):
        """Cloud only: calls disable_battery_backup."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_battery_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_transport_raises(self):
        """No local or HTTP raises HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False, has_http=False)
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="No transport available"):
            await switch.async_turn_on()


# ── OffGridModeSwitch ────────────────────────────────────────────────


class TestOffGridModeSwitch:
    """Test OffGridMode (Green Mode) switch entity."""

    def test_is_on_from_params(self):
        """FUNC_GREEN_EN parameter drives is_on."""
        coordinator = _mock_coordinator(parameters={"FUNC_GREEN_EN": True})
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        assert switch.is_on is True

    def test_is_on_false_default(self):
        """Default state should be False when param missing."""
        coordinator = _mock_coordinator()
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_local(self):
        """Local transport: writes PARAM_FUNC_GREEN_EN."""
        coordinator = _mock_coordinator(has_local=True)
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_GREEN_EN, True, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_on_cloud(self):
        """Cloud only: calls enable_green_mode."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_green_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_transport_raises(self):
        """No local or HTTP raises HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False, has_http=False)
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="No transport available"):
            await switch.async_turn_on()


# ── ChargeLastSwitch ─────────────────────────────────────────────────


class TestChargeLastSwitch:
    """Test Charge Last switch entity (FUNC_CHARGE_LAST, reg 110 bit 4)."""

    def test_is_on_from_params(self):
        """FUNC_CHARGE_LAST parameter drives is_on."""
        coordinator = _mock_coordinator(parameters={"FUNC_CHARGE_LAST": True})
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        assert switch.is_on is True

    def test_is_on_false_default(self):
        """Default state should be False when param missing."""
        coordinator = _mock_coordinator()
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        assert switch.is_on is False

    def test_is_on_optimistic_overrides(self):
        """Optimistic state takes precedence over parameter data."""
        coordinator = _mock_coordinator(parameters={"FUNC_CHARGE_LAST": False})
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        switch._optimistic_state = True
        assert switch.is_on is True

    def test_extra_state_attributes(self):
        """Extra attributes expose the raw FUNC_CHARGE_LAST parameter."""
        coordinator = _mock_coordinator(parameters={"FUNC_CHARGE_LAST": True})
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        attrs = switch.extra_state_attributes
        assert attrs["func_charge_last"] is True

    @pytest.mark.asyncio
    async def test_turn_on_local(self):
        """Local transport: writes PARAM_FUNC_CHARGE_LAST=True."""
        coordinator = _mock_coordinator(has_local=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_CHARGE_LAST, True, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_off_local(self):
        """Local transport: writes PARAM_FUNC_CHARGE_LAST=False."""
        coordinator = _mock_coordinator(has_local=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_CHARGE_LAST, False, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_on_cloud(self):
        """Cloud only: writes via control_function(serial, param, True)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", PARAM_FUNC_CHARGE_LAST, True
        )
        coordinator.async_refresh_device_parameters.assert_called_once_with(
            "1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_off_cloud(self):
        """Cloud only: writes via control_function(serial, param, False)."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", PARAM_FUNC_CHARGE_LAST, False
        )

    @pytest.mark.asyncio
    async def test_cloud_failure_raises_and_clears_optimistic(self):
        """Cloud control_function failure raises and clears optimistic state."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        failed_response = MagicMock()
        failed_response.success = False
        coordinator.client.api.control.control_function = AsyncMock(
            return_value=failed_response
        )
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="charge last"):
            await switch.async_turn_on()
        assert switch._optimistic_state is None

    @pytest.mark.asyncio
    async def test_local_fail_falls_back_to_cloud(self):
        """HYBRID: local write fails -> cloud control_function called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", PARAM_FUNC_CHARGE_LAST, True
        )

    @pytest.mark.asyncio
    async def test_local_success_no_cloud_call(self):
        """Local write succeeds -> cloud API NOT called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        coordinator.client.api.control.control_function.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_transport_raises(self):
        """No local or HTTP raises HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False, has_http=False)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="No transport available"):
            await switch.async_turn_on()

    @pytest.mark.asyncio
    async def test_fallback_one_sided_cloud_methods_raises(self):
        """Exactly one cloud method name is a programming error.

        Guard against a future caller supplying only one of
        cloud_enable_method/cloud_disable_method — without the guard the
        call would silently take the control_function route with a
        possibly-wrong FUNC_ key. Valid states: both present or both omitted.
        The guard fires at call time, before any write is attempted.
        """
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        switch = EG4ChargeLastSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(ValueError, match="together or both omitted"):
            await switch._execute_local_with_fallback(
                action_name="charge last",
                parameter=PARAM_FUNC_CHARGE_LAST,
                value=True,
                cloud_enable_method="enable_something",
            )

        with pytest.raises(ValueError, match="together or both omitted"):
            await switch._execute_local_with_fallback(
                action_name="charge last",
                parameter=PARAM_FUNC_CHARGE_LAST,
                value=True,
                cloud_disable_method="disable_something",
            )

        # Guard fired before any local or cloud write
        coordinator.write_named_parameter.assert_not_called()
        coordinator.client.api.control.control_function.assert_not_called()


# ── WorkingModeSwitch ────────────────────────────────────────────────


class TestWorkingModeSwitch:
    """Test WorkingMode switch entity."""

    def test_is_on_from_params_bool(self):
        """Boolean parameter value -> is_on."""
        coordinator = _mock_coordinator(parameters={"FUNC_AC_CHARGE": True})
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        assert switch.is_on is True

    def test_is_on_from_params_int(self):
        """Integer param value 1 -> True."""
        coordinator = _mock_coordinator(parameters={"FUNC_AC_CHARGE": 1})
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        assert switch.is_on is True

    def test_is_on_false_when_missing(self):
        """Missing parameter -> False."""
        coordinator = _mock_coordinator()
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_local_ac_charge(self):
        """Local mode: writes PARAM_FUNC_AC_CHARGE."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_AC_CHARGE, True, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_turn_on_cloud_ac_charge(self):
        """Cloud mode: calls enable_ac_charge_mode."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_ac_charge_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_peak_shaving_local_write(self):
        """Peak shaving uses local named parameter write (reg 179 bit 7)."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        mode_config = WORKING_MODES["peak_shaving_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_GRID_PEAK_SHAVING, True, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_battery_backup_ctrl_local_write(self):
        """Battery backup ctrl uses local named parameter write (reg 233 bit 1)."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        mode_config = WORKING_MODES["battery_backup_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once_with(
            PARAM_FUNC_BATTERY_BACKUP_CTRL, True, serial="1234567890"
        )

    def test_extra_state_attributes(self):
        """Extra attributes include description and function_parameter."""
        coordinator = _mock_coordinator()
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        attrs = switch.extra_state_attributes
        assert attrs["function_parameter"] == "FUNC_AC_CHARGE"
        assert "description" in attrs


# ── Cloud Fallback ──────────────────────────────────────────────────


class TestCloudFallback:
    """Test local-write-with-cloud-fallback for HYBRID mode switches."""

    @pytest.mark.asyncio
    async def test_battery_backup_local_fail_falls_back_to_cloud(self):
        """HYBRID: local write fails -> cloud API called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        # Local was attempted
        coordinator.write_named_parameter.assert_called_once()
        # Cloud fallback fired
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_battery_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_battery_backup_local_fail_no_cloud_raises(self):
        """LOCAL-only: local write fails -> error propagates."""
        coordinator = _mock_coordinator(has_local=True, has_http=False)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        switch = EG4BatteryBackupSwitch(coordinator, "1234567890")
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="Modbus timeout"):
            await switch.async_turn_on()

    @pytest.mark.asyncio
    async def test_offgrid_local_fail_falls_back_to_cloud(self):
        """HYBRID: off-grid local write fails -> cloud API called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        switch = EG4OffGridModeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_green_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_working_mode_local_fail_falls_back_to_cloud(self):
        """HYBRID: working mode local write fails -> cloud API called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        mode_config = WORKING_MODES["battery_backup_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_battery_backup_ctrl.assert_called_once()

    @pytest.mark.asyncio
    async def test_working_mode_local_success_no_cloud_call(self):
        """Local write succeeds -> cloud API NOT called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        # Local succeeded
        coordinator.write_named_parameter.assert_called_once()
        # Cloud was NOT called
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_ac_charge_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_peak_shaving_local_fail_falls_back_to_cloud(self):
        """HYBRID: peak shaving local fail -> cloud API called."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        mode_config = WORKING_MODES["peak_shaving_mode"]
        switch = EG4WorkingModeSwitch(coordinator, "1234567890", mode_config)
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_peak_shaving_mode.assert_called_once()


# ── DSTSwitch ────────────────────────────────────────────────────────


class TestDSTSwitch:
    """Test DSTSwitch entity (station-level)."""

    def test_is_on_from_station_data(self):
        """Station daylightSavingTime=True -> is_on True."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": True})
        switch = EG4DSTSwitch(coordinator)
        assert switch.is_on is True

    def test_is_on_false(self):
        """Station daylightSavingTime=False -> is_on False."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": False})
        switch = EG4DSTSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_missing_station(self):
        """No station data -> False."""
        coordinator = _mock_coordinator()
        switch = EG4DSTSwitch(coordinator)
        assert switch.is_on is False

    def test_available(self):
        """Available when station data present and last_update_success."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": True})
        switch = EG4DSTSwitch(coordinator)
        assert switch.available is True

    def test_not_available_no_station(self):
        """Not available when station data missing."""
        coordinator = _mock_coordinator()
        switch = EG4DSTSwitch(coordinator)
        assert switch.available is False

    @pytest.mark.asyncio
    async def test_turn_on(self):
        """Turn on calls station.set_daylight_saving_time(True)."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": False})
        switch = EG4DSTSwitch(coordinator)
        _prep(switch)
        await switch.async_turn_on()

        coordinator.station.set_daylight_saving_time.assert_called_once_with(
            enabled=True
        )

    @pytest.mark.asyncio
    async def test_turn_off(self):
        """Turn off calls station.set_daylight_saving_time(False)."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": True})
        switch = EG4DSTSwitch(coordinator)
        _prep(switch)
        await switch.async_turn_off()

        coordinator.station.set_daylight_saving_time.assert_called_once_with(
            enabled=False
        )

    @pytest.mark.asyncio
    async def test_turn_on_failure_raises(self):
        """Station method returning False raises HomeAssistantError."""
        coordinator = _mock_coordinator(station_data={"daylightSavingTime": False})
        coordinator.station.set_daylight_saving_time = AsyncMock(return_value=False)
        switch = EG4DSTSwitch(coordinator)
        _prep(switch)

        with pytest.raises(HomeAssistantError, match="Failed to"):
            await switch.async_turn_on()


# ── Grid sell-back controls (GH #135) ────────────────────────────────


class TestSupportsGridSellback:
    """Family gating helper for the grid sell controls."""

    def test_offgrid_family_features(self):
        """Feature-detected EG4_OFFGRID family has no sell-back."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert not supports_grid_sellback(
            {"model": "6000XP", "features": {"inverter_family": "EG4_OFFGRID"}}
        )

    def test_hybrid_family_features(self):
        """EG4_HYBRID family supports sell-back."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert supports_grid_sellback(
            {"model": "FlexBOSS21", "features": {"inverter_family": "EG4_HYBRID"}}
        )

    def test_lxp_family_features(self):
        """LXP (EU/BR grid-tied) family supports sell-back."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert supports_grid_sellback(
            {"model": "LXP-EU 3650", "features": {"inverter_family": "LXP"}}
        )

    def test_unknown_family_falls_back_to_model(self):
        """UNKNOWN family classifies by model name (issue #219 pattern)."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert not supports_grid_sellback(
            {"model": "12000XP", "features": {"inverter_family": "UNKNOWN"}}
        )
        assert supports_grid_sellback(
            {"model": "18KPV", "features": {"inverter_family": "UNKNOWN"}}
        )

    def test_no_features_model_fallback(self):
        """Missing features dict classifies by model name."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert not supports_grid_sellback({"model": "6000XP"})
        assert supports_grid_sellback({"model": "FlexBOSS21"})

    def test_unrecognized_model_defaults_to_allow(self):
        """Unknown model + unknown family defaults to creating the controls."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        assert supports_grid_sellback({"model": "FutureModel 9000"})

    def test_xp_variant_model_strings_blocked(self):
        """XP-series variants that miss the exact-name table are still
        classified off-grid by the digits-before-XP pattern (codex HIGH):
        these pass SUPPORTED_INVERTER_MODELS' "xp" substring and would
        otherwise default to allowed."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        for model in ("EG4 12000XP", "12000XP-US V2", "EG4-6000XP", "18000XP"):
            assert not supports_grid_sellback({"model": model}), model

    def test_lxp_models_not_caught_by_xp_pattern(self):
        """Grid-tied LXP models contain "XP" with a letter before it and
        must NOT be classified as the off-grid XP series."""
        from custom_components.eg4_web_monitor.utils import supports_grid_sellback

        for model in ("LXP-EU 3650", "LXP-LB-BR 5K", "LXP 12K"):
            assert supports_grid_sellback({"model": model}), model


class TestLocalParamsCanCarry:
    """The pylxpweb register-map probe behind the local-raw setup gate."""

    def test_long_pinned_function_params_resolve(self):
        """Params pinned in every supported pylxpweb resolve True — the
        generalized gate must never skip the existing local switches."""
        for param in (
            "FUNC_AC_CHARGE",
            "FUNC_FORCED_CHG_EN",
            "FUNC_FORCED_DISCHG_EN",
            "FUNC_GRID_PEAK_SHAVING",
            "FUNC_BATTERY_BACKUP_CTRL",
            "FUNC_FEED_IN_GRID_EN",
        ):
            assert switch_module._local_params_can_carry(param), param

    def test_unknown_name_does_not_resolve(self):
        assert not switch_module._local_params_can_carry("FUNC_NOT_A_REAL_PARAM")

    def test_all_wired_working_mode_parameters_resolve_or_are_the_b6_pin(self):
        """Every name wired in _WORKING_MODE_PARAMETERS resolves in the
        installed pylxpweb, except FUNC_PV_SELL_TO_GRID_EN which resolves
        exactly when the installed pylxpweb carries the reg-179 bit-3 pin
        (0.9.36b6+).  Guards the generalized gate against silently dropping
        a wired switch."""
        from pylxpweb.constants.registers import REGISTER_TO_PARAM_KEYS

        for func, param in switch_module._WORKING_MODE_PARAMETERS.items():
            if param is None:
                continue
            if func == "FUNC_PV_SELL_TO_GRID_EN":
                expected = any(
                    param in names for names in REGISTER_TO_PARAM_KEYS.values()
                )
                assert switch_module._local_params_can_carry(param) == expected
            else:
                assert switch_module._local_params_can_carry(param), param


class TestGridSellbackSwitchGating:
    """Setup gating for Grid Sell Back / Export PV Only (GH #135)."""

    @pytest.mark.asyncio
    async def test_offgrid_model_skips_both_sell_controls(self, hass):
        """12000XP gets neither Grid Sell Back nor Export PV Only."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_FEED_IN_GRID_EN" not in params
        assert "FUNC_PV_SELL_TO_GRID_EN" not in params

    @pytest.mark.asyncio
    async def test_offgrid_features_skip_both_sell_controls(self, hass):
        """Feature-detected EG4_OFFGRID skips both sell controls."""
        coordinator = _mock_coordinator(
            model="6000XP",
            device_data={"features": {"inverter_family": "EG4_OFFGRID"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_FEED_IN_GRID_EN" not in params
        assert "FUNC_PV_SELL_TO_GRID_EN" not in params

    @pytest.mark.asyncio
    async def test_hybrid_attached_transport_skips_export_pv_only_pre_pin(
        self, hass, monkeypatch
    ):
        """Pre-pin pylxpweb (< 0.9.36b6): HYBRID keeps Grid Sell Back but
        skips Export PV Only — the parameter cache is local-raw and an old
        pylxpweb cannot decode FUNC_PV_SELL_TO_GRID_EN from registers, so
        is_on would lie OFF.  The probe is pinned to the old-map answer so
        this version-guard branch stays covered after the b6 coupling."""
        monkeypatch.setattr(
            switch_module,
            "_local_params_can_carry",
            lambda param: param != "FUNC_PV_SELL_TO_GRID_EN",
        )
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, transport_attached=True
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_FEED_IN_GRID_EN" in params
        assert "FUNC_PV_SELL_TO_GRID_EN" not in params

    @pytest.mark.asyncio
    async def test_hybrid_attached_transport_keeps_export_pv_only_when_pinned(
        self, hass, monkeypatch
    ):
        """Pinned pylxpweb (>= 0.9.36b6): HYBRID creates Export PV Only —
        reg 179 bit 3 decodes by name in the local-raw cache and local
        writes RMW it (GH #135 unlock)."""
        monkeypatch.setattr(
            switch_module, "_local_params_can_carry", lambda param: True
        )
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, transport_attached=True
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_FEED_IN_GRID_EN" in params
        assert "FUNC_PV_SELL_TO_GRID_EN" in params

    @pytest.mark.asyncio
    async def test_export_pv_only_gate_tracks_installed_pylxpweb(self, hass):
        """Reality check (no probe patching): the gate's answer for Export
        PV Only in HYBRID must equal what the INSTALLED pylxpweb register
        map says — green on both sides of the b6 coupling, and exercises
        the real probe end to end."""
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, transport_attached=True
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        expected = switch_module._local_params_can_carry("FUNC_PV_SELL_TO_GRID_EN")
        assert ("FUNC_PV_SELL_TO_GRID_EN" in params) == expected

    @pytest.mark.asyncio
    async def test_configured_but_unattached_transport_gates_export_pv_only(
        self, hass, monkeypatch
    ):
        """A HYBRID transport that failed to attach at startup (eg4-05l) still
        drives the local-raw gate: with a pre-pin pylxpweb the config promises
        a local-raw parameter cache the moment the retry succeeds, so the
        switch must not be created."""
        monkeypatch.setattr(
            switch_module,
            "_local_params_can_carry",
            lambda param: param != "FUNC_PV_SELL_TO_GRID_EN",
        )
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, transport_attached=False
        )
        coordinator.has_configured_local_transport = MagicMock(return_value=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_FEED_IN_GRID_EN" in params
        assert "FUNC_PV_SELL_TO_GRID_EN" not in params

    @pytest.mark.asyncio
    async def test_legacy_flat_hybrid_keeps_export_pv_only(self, hass):
        """Legacy flat HYBRID (global transport, no per-inverter attachment)
        populates parameters from the cloud, so Export PV Only stays."""
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, transport_attached=False
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_PV_SELL_TO_GRID_EN" in params


class TestGridSellbackSwitchBehavior:
    """State reads and writes for the two new working-mode switches."""

    def _make_switch(self, coordinator, param: str) -> EG4WorkingModeSwitch:
        mode_key = (
            "grid_sell_back_mode"
            if param == "FUNC_FEED_IN_GRID_EN"
            else "export_pv_only_mode"
        )
        return EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_config=WORKING_MODES[mode_key],
        )

    def test_grid_sell_back_is_on_from_params(self):
        """Grid Sell Back reads FUNC_FEED_IN_GRID_EN from the param cache."""
        coordinator = _mock_coordinator(parameters={"FUNC_FEED_IN_GRID_EN": True})
        switch = self._make_switch(coordinator, "FUNC_FEED_IN_GRID_EN")
        assert switch.is_on is True

    def test_export_pv_only_is_on_from_params(self):
        """Export PV Only reads FUNC_PV_SELL_TO_GRID_EN from the param cache."""
        coordinator = _mock_coordinator(parameters={"FUNC_PV_SELL_TO_GRID_EN": True})
        switch = self._make_switch(coordinator, "FUNC_PV_SELL_TO_GRID_EN")
        assert switch.is_on is True

    @pytest.mark.asyncio
    async def test_grid_sell_back_turn_on_local(self):
        """Local transport writes FUNC_FEED_IN_GRID_EN by name (reg 21 bit 15)."""
        coordinator = _mock_coordinator(has_http=False, has_local=True)
        switch = self._make_switch(coordinator, "FUNC_FEED_IN_GRID_EN")
        _prep(switch)

        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "FUNC_FEED_IN_GRID_EN"
        assert call_args[0][1] is True

    @pytest.mark.asyncio
    async def test_grid_sell_back_turn_off_cloud(self):
        """Cloud path calls inverter.disable_feed_in_grid()."""
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        switch = self._make_switch(coordinator, "FUNC_FEED_IN_GRID_EN")
        _prep(switch)

        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_feed_in_grid.assert_called_once()
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_pv_only_turn_on_local(self, monkeypatch):
        """Local transport writes FUNC_PV_SELL_TO_GRID_EN by name (reg 179
        bit 3, pinned 2026-06-12) — the GH #135 local-wiring unlock.  The
        probe is pinned to the post-pin (pylxpweb >= 0.9.36b6) answer."""
        monkeypatch.setattr(
            switch_module, "_local_params_can_carry", lambda param: True
        )
        coordinator = _mock_coordinator(has_http=False, has_local=True)
        switch = self._make_switch(coordinator, "FUNC_PV_SELL_TO_GRID_EN")
        _prep(switch)

        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "FUNC_PV_SELL_TO_GRID_EN"
        assert call_args[0][1] is True
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_pv_sell_to_grid.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_pv_only_legacy_flat_hybrid_pre_pin_uses_cloud(
        self, monkeypatch
    ):
        """Legacy flat HYBRID + pre-pin pylxpweb: the entity exists (its
        parameter cache is cloud-fed) and a local transport is reported,
        but the installed pylxpweb cannot resolve the name — the write must
        go straight to the cloud method with NO doomed local attempt
        (codex adversarial-review finding)."""
        monkeypatch.setattr(
            switch_module,
            "_local_params_can_carry",
            lambda param: param != "FUNC_PV_SELL_TO_GRID_EN",
        )
        coordinator = _mock_coordinator(has_http=True, has_local=True)
        switch = self._make_switch(coordinator, "FUNC_PV_SELL_TO_GRID_EN")
        _prep(switch)

        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_not_called()
        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_pv_sell_to_grid.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_pv_only_turn_on_cloud(self):
        """Without a local transport the cloud enable method is used."""
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        switch = self._make_switch(coordinator, "FUNC_PV_SELL_TO_GRID_EN")
        _prep(switch)

        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_pv_sell_to_grid.assert_called_once()
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_pv_only_turn_off_cloud(self):
        """Export PV Only off routes through the cloud disable method."""
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        switch = self._make_switch(coordinator, "FUNC_PV_SELL_TO_GRID_EN")
        _prep(switch)

        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_pv_sell_to_grid.assert_called_once()


# ── Off Grid Mode (Green) write-path safety on EG4_OFFGRID ──────────


# ── EG4_OFFGRID grid-tied control suppression (PR #220 / #197, eg4-juzg) ──


# ── Fast Zero Export (FUNC_RUN_WITHOUT_GRID, reg 110 bit 1, GH #274) ──


def _make_fast_zero_export_switch(coordinator) -> EG4WorkingModeSwitch:
    """Build the Fast Zero Export working-mode switch under test."""
    return EG4WorkingModeSwitch(
        coordinator=coordinator,
        serial="1234567890",
        mode_config=WORKING_MODES["fast_zero_export_mode"],
    )


class TestFastZeroExportGating:
    """Setup gating for the Fast Zero Export switch (GH #274).

    Both web UIs (EG4 monitor, GH #135 screenshot; Luxpower, GH #274
    screenshot) expose the toggle on grid-tied models, so creation follows
    the grid_tied_only/supports_grid_sellback gate: EG4_HYBRID and LXP get
    it, EG4_OFFGRID does not.
    """

    @pytest.mark.asyncio
    async def test_lxp_family_creates_fast_zero_export(self, hass):
        """LXP (grid-tied three-phase) family gets the switch (GH #274)."""
        coordinator = _mock_coordinator(
            model="LXP-LB 12K",
            device_data={"features": {"inverter_family": "LXP"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_RUN_WITHOUT_GRID" in params

    @pytest.mark.asyncio
    async def test_hybrid_family_creates_fast_zero_export(self, hass):
        """EG4_HYBRID gets the switch too — the EG4 web UI has the same
        toggle on the Grid Sell tab (GH #135 screenshot)."""
        coordinator = _mock_coordinator(
            model="FlexBOSS21",
            device_data={"features": {"inverter_family": "EG4_HYBRID"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_RUN_WITHOUT_GRID" in params

    @pytest.mark.asyncio
    async def test_offgrid_family_skips_fast_zero_export(self, hass):
        """EG4_OFFGRID has no grid sell-back — no Fast Zero Export switch."""
        coordinator = _mock_coordinator(
            model="12000XP",
            device_data={"features": {"inverter_family": "EG4_OFFGRID"}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_RUN_WITHOUT_GRID" not in params

    def test_local_map_carries_run_without_grid(self):
        """The installed pylxpweb decodes FUNC_RUN_WITHOUT_GRID from local
        registers (base table reg 110 bit 1) — no version guard needed."""
        assert switch_module._local_params_can_carry("FUNC_RUN_WITHOUT_GRID")


class TestFastZeroExportSwitchBehavior:
    """State reads and writes for the Fast Zero Export switch (GH #274).

    Register HOLD 110 bit 1 — ``FunctionEn1.ubFastZeroExport`` in the LXP
    protocol PDF; the web UIs toggle cloud param ``FUNC_RUN_WITHOUT_GRID``.
    """

    def test_entity_identity(self):
        """entity_key 'fast_zero_export' (not the raw param name) and a
        translation_key instead of a hardcoded _attr_name."""
        coordinator = _mock_coordinator()
        switch = _make_fast_zero_export_switch(coordinator)
        assert switch.unique_id == "1234567890_fast_zero_export"
        assert switch.translation_key == "fast_zero_export"
        # Localizable name: translation_key must not be overridden by name
        assert getattr(switch, "_attr_name", None) is None

    def test_is_on_from_params(self):
        """State decodes from the FUNC_RUN_WITHOUT_GRID parameter."""
        coordinator = _mock_coordinator(parameters={"FUNC_RUN_WITHOUT_GRID": True})
        switch = _make_fast_zero_export_switch(coordinator)
        assert switch.is_on is True

    def test_is_off_from_params(self):
        coordinator = _mock_coordinator(parameters={"FUNC_RUN_WITHOUT_GRID": False})
        switch = _make_fast_zero_export_switch(coordinator)
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_local(self):
        """Local transport writes FUNC_RUN_WITHOUT_GRID by name (reg 110
        bit 1 read-modify-write in pylxpweb)."""
        coordinator = _mock_coordinator(has_http=False, has_local=True)
        switch = _make_fast_zero_export_switch(coordinator)
        _prep(switch)

        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "FUNC_RUN_WITHOUT_GRID"
        assert call_args[0][1] is True

    @pytest.mark.asyncio
    async def test_turn_off_local(self):
        coordinator = _mock_coordinator(has_http=False, has_local=True)
        switch = _make_fast_zero_export_switch(coordinator)
        _prep(switch)

        await switch.async_turn_off()

        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][0] == "FUNC_RUN_WITHOUT_GRID"
        assert call_args[0][1] is False

    @pytest.mark.asyncio
    async def test_turn_on_cloud_uses_function_control(self):
        """Cloud path writes FUNC_RUN_WITHOUT_GRID via the generic
        function-control API — the exact call the website makes (GH #274)."""
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        switch = _make_fast_zero_export_switch(coordinator)
        _prep(switch)

        await switch.async_turn_on()

        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", "FUNC_RUN_WITHOUT_GRID", True
        )
        coordinator.write_named_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_cloud_uses_function_control(self):
        coordinator = _mock_coordinator(has_http=True, has_local=False)
        switch = _make_fast_zero_export_switch(coordinator)
        _prep(switch)

        await switch.async_turn_off()

        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", "FUNC_RUN_WITHOUT_GRID", False
        )

    @pytest.mark.asyncio
    async def test_hybrid_local_fail_falls_back_to_cloud(self):
        """HYBRID: failed local write falls back to cloud function control."""
        coordinator = _mock_coordinator(has_http=True, has_local=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Modbus timeout")
        )
        switch = _make_fast_zero_export_switch(coordinator)
        _prep(switch)

        await switch.async_turn_on()

        coordinator.write_named_parameter.assert_called_once()
        coordinator.client.api.control.control_function.assert_called_once_with(
            "1234567890", "FUNC_RUN_WITHOUT_GRID", True
        )
