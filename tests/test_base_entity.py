"""Tests for base entity classes."""

from unittest.mock import MagicMock

import pytest

from custom_components.eg4_web_monitor.base_entity import (
    EG4BatteryEntity,
    EG4DeviceEntity,
    EG4StationEntity,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "FlexBOSS 18K",
                "batteries": {
                    "Battery_ID_01": {"soc": 95},
                    "Battery_ID_02": {"soc": 93},
                },
            }
        },
        "station": {
            "name": "Test Station",
            "plantId": "test-plant-123",
        },
    }
    coordinator.plant_id = "test-plant-123"
    coordinator.last_update_success = True
    return coordinator


class TestEG4DeviceEntity:
    """Test EG4DeviceEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test device entity initialization."""
        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.coordinator == mock_coordinator
        assert entity._serial == "1234567890"

    def test_device_info(self, mock_coordinator):
        """Test device_info property."""
        mock_coordinator.get_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "1234567890")},
                "name": "FlexBOSS 18K 1234567890",
                "manufacturer": "EG4 Electronics",
            }
        )

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")
        device_info = entity.device_info

        assert device_info["name"] == "FlexBOSS 18K 1234567890"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_device_info.assert_called_once_with("1234567890")

    def test_device_info_none_fallback(self, mock_coordinator):
        """Test device_info returns None when not available."""
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_device_exists(self, mock_coordinator):
        """Test entity is available when device exists."""
        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is True

    def test_not_available_when_device_missing(self, mock_coordinator):
        """Test entity is not available when device is missing."""
        entity = EG4DeviceEntity(mock_coordinator, "9999999999")

        assert entity.available is False

    def test_not_available_when_no_data(self, mock_coordinator):
        """Test entity is not available when coordinator has no data."""
        mock_coordinator.data = None

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is False

    def test_not_available_when_no_devices_key(self, mock_coordinator):
        """Test entity is not available when coordinator data has no devices key."""
        mock_coordinator.data = {"station": {}}

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is False


class TestEG4BatteryEntity:
    """Test EG4BatteryEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test battery entity initialization."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.coordinator == mock_coordinator
        assert entity._parent_serial == "1234567890"
        assert entity._battery_key == "Battery_ID_01"

    def test_device_info(self, mock_coordinator):
        """Test battery device_info property."""
        mock_coordinator.get_battery_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "1234567890_Battery_ID_01")},
                "name": "Battery Battery_ID_01",
                "manufacturer": "EG4 Electronics",
                "via_device": ("eg4_web_monitor", "1234567890"),
            }
        )

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")
        device_info = entity.device_info

        assert device_info["name"] == "Battery Battery_ID_01"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_battery_device_info.assert_called_once_with(
            "1234567890", "Battery_ID_01"
        )

    def test_device_info_empty_fallback(self, mock_coordinator):
        """Test battery device_info returns None when not available."""
        mock_coordinator.get_battery_device_info = MagicMock(return_value=None)

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_battery_exists(self, mock_coordinator):
        """Test battery entity is available when battery exists."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.available is True

    def test_not_available_when_battery_missing(self, mock_coordinator):
        """Test battery entity is not available when battery is missing."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_99")

        assert entity.available is False

    def test_not_available_when_parent_missing(self, mock_coordinator):
        """Test battery entity is not available when parent device is missing."""
        entity = EG4BatteryEntity(mock_coordinator, "9999999999", "Battery_ID_01")

        assert entity.available is False

    def test_not_available_when_no_batteries_key(self, mock_coordinator):
        """Test battery entity is not available when parent has no batteries."""
        mock_coordinator.data["devices"]["1234567890"].pop("batteries")

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.available is False


class TestEG4StationEntity:
    """Test EG4StationEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test station entity initialization."""
        entity = EG4StationEntity(mock_coordinator)

        assert entity.coordinator == mock_coordinator

    def test_device_info(self, mock_coordinator):
        """Test station device_info property."""
        mock_coordinator.get_station_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "station_test-plant-123")},
                "name": "Test Station",
                "manufacturer": "EG4 Electronics",
            }
        )

        entity = EG4StationEntity(mock_coordinator)
        device_info = entity.device_info

        assert device_info["name"] == "Test Station"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_station_device_info.assert_called_once()

    def test_device_info_none_fallback(self, mock_coordinator):
        """Test station device_info returns None when not available."""
        mock_coordinator.get_station_device_info = MagicMock(return_value=None)

        entity = EG4StationEntity(mock_coordinator)
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_station_exists(self, mock_coordinator):
        """Test station entity is available when station data exists."""
        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is True

    def test_not_available_when_update_failed(self, mock_coordinator):
        """Test station entity is not available when last update failed."""
        mock_coordinator.last_update_success = False

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_not_available_when_no_data(self, mock_coordinator):
        """Test station entity is not available when coordinator has no data."""
        mock_coordinator.data = None

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_not_available_when_no_station_key(self, mock_coordinator):
        """Test station entity is not available when data has no station key."""
        mock_coordinator.data = {"devices": {}}

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_extra_state_attributes(self, mock_coordinator):
        """Test station extra_state_attributes includes plant_id."""
        entity = EG4StationEntity(mock_coordinator)
        attributes = entity.extra_state_attributes

        assert attributes is not None
        assert attributes["plant_id"] == "test-plant-123"
