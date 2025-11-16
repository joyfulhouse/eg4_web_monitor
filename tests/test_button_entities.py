"""Unit tests for button entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.eg4_web_monitor.button import (
    EG4RefreshButton,
    EG4BatteryRefreshButton,
    EG4StationRefreshButton,
)


class TestEG4RefreshButton:
    """Test EG4RefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            }
        }
        coordinator.get_device_info.return_value = {
            "identifiers": {("eg4_web_monitor", "1234567890")},
            "name": "FlexBOSS21 1234567890",
            "model": "FlexBOSS21",
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        assert entity._serial == "1234567890"
        assert entity._model == "FlexBOSS21"
        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing button refreshes coordinator."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.get_device_info.return_value = {}
        coordinator.async_request_refresh = AsyncMock()
        coordinator.refresh_all_device_parameters = AsyncMock()
        coordinator.api = MagicMock()
        device_data = {"type": "inverter"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        await entity.async_press()

        coordinator.async_request_refresh.assert_called_once()

    def test_device_info(self):
        """Test device info is correctly set."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        device_info = {
            "identifiers": {("eg4_web_monitor", "1234567890")},
            "name": "FlexBOSS21 1234567890",
            "model": "FlexBOSS21",
            "manufacturer": "EG4 Electronics",
        }
        coordinator.get_device_info.return_value = device_info
        device_data = {"type": "inverter"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        assert entity.device_info == device_info


class TestEG4BatteryRefreshButton:
    """Test EG4BatteryRefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {"batteries": {"1234567890-01": {"state_of_charge": 85}}}
            }
        }

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
            parent_model="FlexBOSS21",
            battery_id="1234567890-01",
        )

        assert entity._parent_serial == "1234567890"
        assert entity._battery_key == "1234567890-01"
        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing battery refresh button."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"batteries": {"1234567890-01": {}}}}
        }
        coordinator.async_request_refresh = AsyncMock()
        coordinator.api = MagicMock()
        coordinator.api.get_battery_info = AsyncMock()

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
            parent_model="FlexBOSS21",
            battery_id="1234567890-01",
        )

        await entity.async_press()

        coordinator.async_request_refresh.assert_called_once()

    def test_unique_id(self):
        """Test unique ID includes battery key."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"batteries": {"1234567890-01": {}}}}
        }

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
            parent_model="FlexBOSS21",
            battery_id="1234567890-01",
        )

        assert "1234567890" in entity.unique_id
        assert "1234567890-01" in entity.unique_id
        assert "refresh" in entity.unique_id.lower()


class TestEG4StationRefreshButton:
    """Test EG4StationRefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing station refresh button."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4StationRefreshButton(coordinator=coordinator)

        await entity.async_press()

        coordinator.async_request_refresh.assert_called_once()

    def test_device_info(self):
        """Test station device info."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.get_station_device_info.return_value = {
            "identifiers": {("eg4_web_monitor", "station_12345")},
            "name": "Test Plant",
            "manufacturer": "EG4 Electronics",
        }

        entity = EG4StationRefreshButton(coordinator=coordinator)

        device_info = entity.device_info
        assert device_info is not None
        assert ("eg4_web_monitor", "station_12345") in device_info["identifiers"]
        assert "Test Plant" in device_info["name"]

    def test_unique_id(self):
        """Test station unique ID."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert "12345" in entity.unique_id
        assert "refresh" in entity.unique_id.lower()
