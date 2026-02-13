"""Tests for EG4 switch entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    INVERTER_FAMILY_EG4_OFFGRID,
    PARAM_FUNC_EPS_EN,
    PARAM_FUNC_GREEN_EN,
    PARAM_FUNC_AC_CHARGE,
    WORKING_MODES,
)
from custom_components.eg4_web_monitor.switch import (
    _supports_eps_battery_backup,
    async_setup_entry,
    EG4QuickChargeSwitch,
    EG4BatteryBackupSwitch,
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
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

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
        assert any(n == "EG4WorkingModeSwitch" for n in type_names)

    @pytest.mark.asyncio
    async def test_setup_no_quick_charge_without_http(self, hass):
        """Local-only mode should skip QuickCharge."""
        coordinator = _mock_coordinator(has_http=False, has_local=True, local_only=True)
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
    async def test_local_only_excludes_cloud_only_working_modes(self, hass):
        """LOCAL-only mode should NOT create switches for cloud-only working modes.

        FUNC_BATTERY_BACKUP_CTRL and FUNC_GRID_PEAK_SHAVING have no Modbus
        register mappings and can only be controlled via the Cloud API.
        Regression test for issue #153.
        """
        coordinator = _mock_coordinator(has_http=False, has_local=True, local_only=True)
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        working_modes = [
            e for e in entities if isinstance(e, EG4WorkingModeSwitch)
        ]
        working_mode_params = {e._mode_config["param"] for e in working_modes}

        # These three have Modbus register support (register 21 bit fields)
        assert "FUNC_AC_CHARGE" in working_mode_params
        assert "FUNC_FORCED_CHG_EN" in working_mode_params
        assert "FUNC_FORCED_DISCHG_EN" in working_mode_params

        # These are Cloud API-only — must NOT be created in LOCAL mode
        assert "FUNC_BATTERY_BACKUP_CTRL" not in working_mode_params
        assert "FUNC_GRID_PEAK_SHAVING" not in working_mode_params

    @pytest.mark.asyncio
    async def test_cloud_mode_includes_all_working_modes(self, hass):
        """Cloud mode should create ALL working mode switches."""
        coordinator = _mock_coordinator(has_http=True, has_local=False, local_only=False)
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

    @pytest.mark.asyncio
    async def test_turn_on(self):
        """Turn on calls enable_quick_charge via cloud API."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_quick_charge.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off(self):
        """Turn off calls disable_quick_charge via cloud API."""
        coordinator = _mock_coordinator()
        switch = EG4QuickChargeSwitch(coordinator, "1234567890")
        _prep(switch)
        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.disable_quick_charge.assert_called_once()


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


# ── WorkingModeSwitch ────────────────────────────────────────────────


class TestWorkingModeSwitch:
    """Test WorkingMode switch entity."""

    def test_is_on_from_params_bool(self):
        """Boolean parameter value -> is_on."""
        coordinator = _mock_coordinator(parameters={"FUNC_AC_CHARGE": True})
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
        assert switch.is_on is True

    def test_is_on_from_params_int(self):
        """Integer param value 1 -> True."""
        coordinator = _mock_coordinator(parameters={"FUNC_AC_CHARGE": 1})
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
        assert switch.is_on is True

    def test_is_on_false_when_missing(self):
        """Missing parameter -> False."""
        coordinator = _mock_coordinator()
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_local_ac_charge(self):
        """Local mode: writes PARAM_FUNC_AC_CHARGE."""
        coordinator = _mock_coordinator(has_local=True, has_http=True)
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
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
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
        _prep(switch)
        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.enable_ac_charge_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_peak_shaving_no_local_raises(self):
        """Peak shaving has no Modbus mapping: local-only should raise."""
        coordinator = _mock_coordinator(
            has_local=False, has_http=False, local_only=True
        )
        mode_config = WORKING_MODES["peak_shaving_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "peak_shaving_mode", mode_config
        )
        _prep(switch)

        with pytest.raises(
            HomeAssistantError, match="not available via local transport"
        ):
            await switch.async_turn_on()

    def test_extra_state_attributes(self):
        """Extra attributes include description and function_parameter."""
        coordinator = _mock_coordinator()
        mode_config = WORKING_MODES["ac_charge_mode"]
        switch = EG4WorkingModeSwitch(
            coordinator, "1234567890", "ac_charge_mode", mode_config
        )
        attrs = switch.extra_state_attributes
        assert attrs["function_parameter"] == "FUNC_AC_CHARGE"
        assert "description" in attrs


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
