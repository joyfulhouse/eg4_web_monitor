"""Tests for EG4 select entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError
from pylxpweb import OperatingMode

from custom_components.eg4_web_monitor.select import (
    async_setup_entry,
    EG4OperatingModeSelect,
    OPERATING_MODE_OPTIONS,
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
        """FlexBOSS inverter creates OperatingModeSelect."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 1
        assert type(entities[0]).__name__ == "EG4OperatingModeSelect"

    @pytest.mark.asyncio
    async def test_setup_skips_gridboss(self, hass):
        """GridBOSS devices should not get select entities."""
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
