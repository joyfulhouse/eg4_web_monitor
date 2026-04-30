"""Tests for EG4 select entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError
from pylxpweb import OperatingMode

from custom_components.eg4_web_monitor.select import (
    async_setup_entry,
    EG4OperatingModeSelect,
    EG4SmartPortModeSelect,
    OPERATING_MODE_OPTIONS,
    SMART_PORT_MODE_OPTIONS,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    serial: str = "1234567890",
    model: str = "FlexBOSS21",
    parameters: dict | None = None,
) -> MagicMock:
    """Build a mock EG4DataUpdateCoordinator for select tests."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_refresh_device_parameters = AsyncMock()

    coordinator.data = {
        "devices": {serial: {"type": "inverter", "model": model}},
        "parameters": {serial: parameters or {}},
    }
    coordinator.get_device_info = MagicMock(return_value=None)

    # Mock inverter
    mock_inverter = MagicMock()
    mock_inverter.set_operating_mode = AsyncMock(return_value=True)
    mock_inverter.refresh = AsyncMock()
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    return coordinator


# ── Platform setup ───────────────────────────────────────────────────


class TestSelectPlatformSetup:
    """Test select platform setup."""

    @pytest.mark.asyncio
    async def test_setup_with_inverter(self, hass):
        """FlexBOSS inverter creates OperatingModeSelect and PVInputModeSelect."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 2
        type_names = [type(e).__name__ for e in entities]
        assert "EG4OperatingModeSelect" in type_names
        assert "EG4PVInputModeSelect" in type_names

    @pytest.mark.asyncio
    async def test_setup_creates_gridboss_selects(self, hass):
        """GridBOSS devices get 4 smart port mode select entities."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"] = {
            "gb123": {"type": "gridboss", "model": "GridBOSS"}
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 4
        type_names = [type(e).__name__ for e in entities]
        assert all(name == "EG4SmartPortModeSelect" for name in type_names)

    @pytest.mark.asyncio
    async def test_setup_skips_unsupported_model(self, hass):
        """Unknown model should not get select entities."""
        coordinator = _mock_coordinator(model="UnknownInverter")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 0


# ── OperatingModeSelect ──────────────────────────────────────────────


class TestOperatingModeSelect:
    """Test OperatingModeSelect entity."""

    def test_current_option_normal(self):
        """FUNC_SET_TO_STANDBY=True -> Normal."""
        coordinator = _mock_coordinator(parameters={"FUNC_SET_TO_STANDBY": True})
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        assert select.current_option == "Normal"

    def test_current_option_standby(self):
        """FUNC_SET_TO_STANDBY=False -> Standby."""
        coordinator = _mock_coordinator(parameters={"FUNC_SET_TO_STANDBY": False})
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        assert select.current_option == "Standby"

    def test_current_option_default_normal(self):
        """Missing parameter -> defaults to Normal."""
        coordinator = _mock_coordinator()
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        assert select.current_option == "Normal"

    def test_optimistic_state_overrides(self):
        """Optimistic state takes precedence."""
        coordinator = _mock_coordinator(parameters={"FUNC_SET_TO_STANDBY": True})
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        select._optimistic_state = "Standby"
        assert select.current_option == "Standby"

    def test_options_list(self):
        """Options should be Normal and Standby."""
        coordinator = _mock_coordinator()
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        assert select.options == OPERATING_MODE_OPTIONS
        assert "Normal" in select.options
        assert "Standby" in select.options

    def test_available(self):
        """Available when device type is inverter."""
        coordinator = _mock_coordinator()
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        assert select.available is True

    @pytest.mark.asyncio
    async def test_select_normal(self):
        """Select Normal calls set_operating_mode(NORMAL)."""
        coordinator = _mock_coordinator()
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        select.hass = MagicMock()
        select.entity_id = "select.test_operating_mode"
        select.async_write_ha_state = MagicMock()
        await select.async_select_option("Normal")

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_operating_mode.assert_called_once_with(OperatingMode.NORMAL)

    @pytest.mark.asyncio
    async def test_select_standby(self):
        """Select Standby calls set_operating_mode(STANDBY)."""
        coordinator = _mock_coordinator()
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        select.hass = MagicMock()
        select.entity_id = "select.test_operating_mode"
        select.async_write_ha_state = MagicMock()
        await select.async_select_option("Standby")

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_operating_mode.assert_called_once_with(OperatingMode.STANDBY)

    @pytest.mark.asyncio
    async def test_select_failure_raises(self):
        """set_operating_mode returning False raises HomeAssistantError."""
        coordinator = _mock_coordinator()
        mock_inverter = coordinator.get_inverter_object("1234567890")
        mock_inverter.set_operating_mode = AsyncMock(return_value=False)

        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        select.hass = MagicMock()
        select.entity_id = "select.test_operating_mode"
        select.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="Failed to set"):
            await select.async_select_option("Standby")

    def test_extra_state_attributes(self):
        """Extra attributes include device_serial and standby parameter."""
        coordinator = _mock_coordinator(parameters={"FUNC_SET_TO_STANDBY": True})
        device_data = coordinator.data["devices"]["1234567890"]
        select = EG4OperatingModeSelect(coordinator, "1234567890", device_data)
        attrs = select.extra_state_attributes
        assert attrs["device_serial"] == "1234567890"
        assert attrs["standby_parameter"] is True


# ── SmartPortModeSelect ──────────────────────────────────────────────


def _mock_gridboss_coordinator(
    *,
    serial: str = "gb123",
    sensors: dict | None = None,
) -> MagicMock:
    """Build a mock coordinator with a GridBOSS device for smart port tests."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.write_smart_port_mode = AsyncMock(return_value=True)

    coordinator.data = {
        "devices": {
            serial: {
                "type": "gridboss",
                "model": "GridBOSS",
                "sensors": sensors or {},
            }
        },
    }
    coordinator.get_device_info = MagicMock(return_value=None)

    # Mock client for cloud API path
    coordinator.client = MagicMock()
    coordinator.client.api.control.set_smart_port_mode = AsyncMock()

    return coordinator


class TestSmartPortModeSelect:
    """Test SmartPortModeSelect entity."""

    def test_current_option_smart_load(self):
        """smart_load status maps to Smart Load."""
        coordinator = _mock_gridboss_coordinator(
            sensors={"smart_port1_status": "smart_load"}
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        assert select.current_option == "Smart Load"

    def test_current_option_ac_couple(self):
        """ac_couple status maps to AC Couple."""
        coordinator = _mock_gridboss_coordinator(
            sensors={"smart_port2_status": "ac_couple"}
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=2)
        assert select.current_option == "AC Couple"

    def test_current_option_unused(self):
        """unused status maps to Unused."""
        coordinator = _mock_gridboss_coordinator(
            sensors={"smart_port3_status": "unused"}
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=3)
        assert select.current_option == "Unused"

    def test_current_option_missing(self):
        """Missing sensor returns None."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=4)
        assert select.current_option is None

    def test_optimistic_state_overrides(self):
        """Optimistic state takes precedence over sensor data."""
        coordinator = _mock_gridboss_coordinator(
            sensors={"smart_port1_status": "unused"}
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        select._optimistic_state = "AC Couple"
        assert select.current_option == "AC Couple"

    def test_options_list(self):
        """Options should be Off, Smart Load, AC Couple."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        assert select.options == SMART_PORT_MODE_OPTIONS

    def test_available_gridboss(self):
        """Available when device type is gridboss."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        assert select.available is True

    def test_unavailable_non_gridboss(self):
        """Unavailable when device type is not gridboss."""
        coordinator = _mock_gridboss_coordinator()
        coordinator.data["devices"]["gb123"]["type"] = "inverter"
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        assert select.available is False

    def test_entity_name(self):
        """Name includes port number."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=3)
        assert select.name == "Smart Port 3 Mode"

    @pytest.mark.asyncio
    async def test_select_option_delegates_to_coordinator(self):
        """Select delegates to coordinator.write_smart_port_mode()."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=2)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_2_mode"
        select.async_write_ha_state = MagicMock()

        await select.async_select_option("AC Couple")

        coordinator.write_smart_port_mode.assert_called_once_with("gb123", 2, 2)
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_option_smart_load(self):
        """Smart Load maps to value 1."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_1_mode"
        select.async_write_ha_state = MagicMock()

        await select.async_select_option("Smart Load")

        coordinator.write_smart_port_mode.assert_called_once_with("gb123", 1, 1)
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_option_unused(self):
        """Unused maps to value 0."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=3)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_3_mode"
        select.async_write_ha_state = MagicMock()

        await select.async_select_option("Unused")

        coordinator.write_smart_port_mode.assert_called_once_with("gb123", 3, 0)

    @pytest.mark.asyncio
    async def test_select_option_failure_raises(self):
        """Coordinator write failure raises HomeAssistantError."""
        coordinator = _mock_gridboss_coordinator()
        coordinator.write_smart_port_mode = AsyncMock(
            side_effect=HomeAssistantError("No local transport or cloud API available")
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_1_mode"
        select.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="No local transport"):
            await select.async_select_option("Smart Load")

    @pytest.mark.asyncio
    async def test_select_invalid_option(self):
        """Invalid option raises HomeAssistantError."""
        coordinator = _mock_gridboss_coordinator()
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_1_mode"
        select.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="Invalid smart port mode"):
            await select.async_select_option("Invalid")

    @pytest.mark.asyncio
    async def test_select_clears_optimistic_state_on_failure(self):
        """Optimistic state is cleared on write failure."""
        coordinator = _mock_gridboss_coordinator()
        coordinator.write_smart_port_mode = AsyncMock(
            side_effect=HomeAssistantError("Write failed")
        )
        device_data = coordinator.data["devices"]["gb123"]
        select = EG4SmartPortModeSelect(coordinator, "gb123", device_data, port=1)
        select.hass = MagicMock()
        select.entity_id = "select.test_smart_port_1_mode"
        select.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError):
            await select.async_select_option("Smart Load")

        # Optimistic state should be cleared after failure
        assert select._optimistic_state is None
