"""Test select entity functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eg4_web_monitor.select import EG4OperatingModeSelect


class TestEG4OperatingModeSelect:
    """Test the operating mode select entity."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            },
            "device_info": {
                "1234567890": {
                    "deviceTypeText4APP": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {
                    "FUNC_SET_TO_STANDBY": True,  # Normal mode
                }
            },
        }
        coordinator.api = MagicMock()
        coordinator.api.control_function_parameter = AsyncMock()
        coordinator.async_refresh_device_parameters = AsyncMock()
        return coordinator

    def test_initialization(self, mock_coordinator):
        """Test select entity initialization."""
        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter", "model": "FlexBOSS21"},
        )

        assert select._serial == "1234567890"
        assert select.unique_id is not None
        assert "operating_mode" in select.unique_id
        assert select.name == "Operating Mode"
        assert select.options == ["Normal", "Standby"]

    def test_current_option_normal_mode(self, mock_coordinator):
        """Test current option returns Normal when parameter is True."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        assert select.current_option == "Normal"

    def test_current_option_standby_mode(self, mock_coordinator):
        """Test current option returns Standby when parameter is False."""

        mock_coordinator.data["parameters"]["1234567890"]["FUNC_SET_TO_STANDBY"] = False

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        assert select.current_option == "Standby"

    def test_current_option_no_parameter_data(self, mock_coordinator):
        """Test current option defaults to Normal when no parameter data."""

        mock_coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        # Should default to Normal
        assert select.current_option == "Normal"

    def test_current_option_with_optimistic_state(self, mock_coordinator):
        """Test that optimistic state takes precedence."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        # Set optimistic state
        select._optimistic_state = "Standby"

        # Should return optimistic state, not coordinator data
        assert select.current_option == "Standby"

    def test_extra_state_attributes(self, mock_coordinator):
        """Test extra state attributes."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        attrs = select.extra_state_attributes
        assert attrs is not None
        assert attrs["device_serial"] == "1234567890"
        assert attrs["standby_parameter"] is True

    def test_extra_state_attributes_with_optimistic(self, mock_coordinator):
        """Test extra state attributes with optimistic state."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        select._optimistic_state = "Standby"
        attrs = select.extra_state_attributes

        assert attrs["optimistic_state"] == "Standby"

    def test_available_for_inverter(self, mock_coordinator):
        """Test entity is available for inverter devices."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        assert select.available is True

    def test_available_for_non_inverter(self, mock_coordinator):
        """Test entity is not available for non-inverter devices."""

        mock_coordinator.data["devices"]["1234567890"]["type"] = "gridboss"

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "gridboss"},
        )

        assert select.available is False

    @pytest.mark.asyncio
    async def test_async_select_option_normal(self, mock_coordinator):
        """Test selecting Normal mode."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        # Mock async_write_ha_state
        select.async_write_ha_state = MagicMock()

        await select.async_select_option("Normal")

        # Verify API was called with correct parameters
        mock_coordinator.api.control_function_parameter.assert_called_once_with(
            "1234567890", "FUNC_SET_TO_STANDBY", True
        )

        # Verify coordinator refresh was requested
        mock_coordinator.async_refresh_device_parameters.assert_called_once_with(
            "1234567890"
        )

    @pytest.mark.asyncio
    async def test_async_select_option_standby(self, mock_coordinator):
        """Test selecting Standby mode."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        select.async_write_ha_state = MagicMock()

        await select.async_select_option("Standby")

        # Verify API was called with False for Standby
        mock_coordinator.api.control_function_parameter.assert_called_once_with(
            "1234567890", "FUNC_SET_TO_STANDBY", False
        )

    @pytest.mark.asyncio
    async def test_async_select_option_invalid(self, mock_coordinator):
        """Test selecting invalid option is handled gracefully."""

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        # Should not raise exception, just log error and return
        await select.async_select_option("InvalidMode")

        # API should not be called
        mock_coordinator.api.control_function_parameter.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_select_option_api_error(self, mock_coordinator):
        """Test handling of API errors when setting option."""

        mock_coordinator.api.control_function_parameter = AsyncMock(
            side_effect=Exception("API Error")
        )

        select = EG4OperatingModeSelect(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
        )

        select.async_write_ha_state = MagicMock()

        with pytest.raises(Exception, match="API Error"):
            await select.async_select_option("Normal")

        # Optimistic state should be cleared on error
        assert select._optimistic_state is None
