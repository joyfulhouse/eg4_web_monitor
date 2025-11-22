"""Tests for refactored entities using device object methods.

This module tests entities that have been refactored to use pylxpweb device
object convenience methods instead of direct API calls.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.number import (
    SystemChargeSOCLimitNumber,
    OnGridSOCCutoffNumber,
    OffGridSOCCutoffNumber,
)
from custom_components.eg4_web_monitor.button import (
    EG4RefreshButton,
    EG4BatteryRefreshButton,
    EG4StationRefreshButton,
)


class TestSystemChargeSOCLimitNumber:
    """Test SystemChargeSOCLimitNumber entity with device objects."""

    def test_initialization(self):
        """Test entity initializes correctly."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity._attr_name == "System Charge SOC Limit"
        assert entity._attr_native_min_value == 10
        assert entity._attr_native_max_value == 101
        assert entity._attr_native_step == 1
        assert entity._attr_native_unit_of_measurement == "%"

    def test_native_value_from_coordinator(self):
        """Test reading SOC limit from coordinator data."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"model": "FlexBOSS21"}},
            "parameters": {"1234567890": {"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 90.0}},
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 90

    def test_native_value_none_when_no_data(self):
        """Test native_value returns None when no data available."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_async_set_native_value_success(self):
        """Test setting SOC limit using device object method."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})
        coordinator.async_request_refresh = AsyncMock()

        # Mock inverter device object
        mock_inverter = MagicMock()
        mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock Home Assistant components
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Set value to 85%
        await entity.async_set_native_value(85)

        # Verify device object method was called correctly
        mock_inverter.set_battery_soc_limits.assert_called_once_with(on_grid_limit=85)
        mock_inverter.refresh.assert_called_once()
        entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_native_value_inverter_not_found(self):
        """Test error handling when inverter not found."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})
        coordinator.get_inverter_object = MagicMock(return_value=None)

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()

        # Should raise HomeAssistantError when inverter not found
        with pytest.raises(HomeAssistantError, match="Inverter 1234567890 not found"):
            await entity.async_set_native_value(85)

    @pytest.mark.asyncio
    async def test_async_set_native_value_set_fails(self):
        """Test error handling when set_battery_soc_limits fails."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})

        # Mock inverter that fails to set limits
        mock_inverter = MagicMock()
        mock_inverter.set_battery_soc_limits = AsyncMock(return_value=False)
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()

        # Should raise HomeAssistantError when set fails
        with pytest.raises(HomeAssistantError, match="Failed to set SOC limit"):
            await entity.async_set_native_value(85)

    @pytest.mark.asyncio
    async def test_async_set_native_value_validates_range(self):
        """Test value validation (10-101%)."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()

        # Test below minimum - ValueError wrapped in HomeAssistantError
        with pytest.raises(
            HomeAssistantError, match="must be an integer between 10-101%"
        ):
            await entity.async_set_native_value(5)

        # Test above maximum
        with pytest.raises(
            HomeAssistantError, match="must be an integer between 10-101%"
        ):
            await entity.async_set_native_value(105)

    @pytest.mark.asyncio
    async def test_async_set_native_value_validates_integer(self):
        """Test that only integer values are accepted."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.get_device_info = MagicMock(return_value={})

        entity = SystemChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()

        # Test decimal value - ValueError wrapped in HomeAssistantError
        with pytest.raises(HomeAssistantError, match="must be an integer value"):
            await entity.async_set_native_value(85.5)


class TestOnGridSOCCutoffNumberRefactored:
    """Test OnGridSOCCutoffNumber with device objects."""

    @pytest.mark.asyncio
    async def test_uses_on_grid_limit_parameter(self):
        """Test that on-grid cutoff uses on_grid_limit parameter."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.async_request_refresh = AsyncMock()

        mock_inverter = MagicMock()
        mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = OnGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(25)

        # Verify correct parameter name used
        mock_inverter.set_battery_soc_limits.assert_called_once_with(on_grid_limit=25)


class TestOffGridSOCCutoffNumberRefactored:
    """Test OffGridSOCCutoffNumber with device objects."""

    @pytest.mark.asyncio
    async def test_uses_off_grid_limit_parameter(self):
        """Test that off-grid cutoff uses off_grid_limit parameter."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.async_request_refresh = AsyncMock()

        mock_inverter = MagicMock()
        mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = OffGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(15)

        # Verify correct parameter name used
        mock_inverter.set_battery_soc_limits.assert_called_once_with(off_grid_limit=15)


class TestEG4RefreshButtonRefactored:
    """Test EG4RefreshButton with device objects."""

    @pytest.mark.asyncio
    async def test_refresh_inverter_device(self):
        """Test refresh button calls inverter.refresh()."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.get_device_info = MagicMock(return_value={})
        coordinator.async_request_refresh = AsyncMock()

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
            model="FlexBOSS21",
        )

        await entity.async_press()

        # Verify device object refresh was called
        coordinator.get_inverter_object.assert_called_once_with("1234567890")
        mock_inverter.refresh.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_handles_missing_inverter(self):
        """Test refresh gracefully handles missing inverter object."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.get_device_info = MagicMock(return_value={})
        coordinator.async_request_refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=None)

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data={"type": "inverter"},
            model="FlexBOSS21",
        )

        # Should not raise exception, just log warning
        await entity.async_press()

        # Coordinator refresh should still be called
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_non_inverter_device(self):
        """Test refresh for non-inverter devices."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "parallel_group"}}}
        coordinator.get_device_info = MagicMock(return_value={})
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data={"type": "parallel_group"},
            model="Parallel Group",
        )

        await entity.async_press()

        # Should only call coordinator refresh for non-inverter types
        coordinator.async_request_refresh.assert_called_once()


class TestEG4BatteryRefreshButtonRefactored:
    """Test EG4BatteryRefreshButton with device objects."""

    @pytest.mark.asyncio
    async def test_refresh_via_parent_inverter(self):
        """Test battery refresh calls parent inverter.refresh()."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"batteries": {"BAT001": {}}}}}
        coordinator.async_request_refresh = AsyncMock()

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="BAT001",
            parent_model="FlexBOSS21",
            battery_id="BAT001",
        )

        await entity.async_press()

        # Verify parent inverter refresh was called
        coordinator.get_inverter_object.assert_called_once_with("1234567890")
        mock_inverter.refresh.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_handles_missing_parent_inverter(self):
        """Test battery refresh handles missing parent inverter."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"batteries": {"BAT001": {}}}}}
        coordinator.async_request_refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=None)

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="BAT001",
            parent_model="FlexBOSS21",
            battery_id="BAT001",
        )

        # Should not raise exception
        await entity.async_press()

        # Coordinator refresh should still be called
        coordinator.async_request_refresh.assert_called_once()


class TestEG4StationRefreshButtonRefactored:
    """Test EG4StationRefreshButton functionality."""

    @pytest.mark.asyncio
    async def test_refresh_station(self):
        """Test station refresh button."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.data = {"station": {}}
        coordinator.last_update_success = True
        coordinator.get_station_device_info = MagicMock(return_value={})
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4StationRefreshButton(coordinator=coordinator)

        await entity.async_press()

        # Should call coordinator refresh
        coordinator.async_request_refresh.assert_called_once()

    def test_available_when_station_exists(self):
        """Test availability when station data exists."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.last_update_success = True
        coordinator.data = {"station": {}}

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert entity.available is True

    def test_unavailable_when_no_station_data(self):
        """Test unavailability when station data missing."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.last_update_success = True
        coordinator.data = {}

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert entity.available is False
