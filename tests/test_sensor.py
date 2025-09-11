"""Tests for EG4 Inverter sensor platform."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory

from custom_components.eg4_inverter.sensor import (
    async_setup_entry,
    EG4InverterSensor,
    EG4BatterySensor,
    _create_inverter_sensors,
    _create_gridboss_sensors,
    _create_parallel_group_sensors
)
from custom_components.eg4_inverter.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_inverter.const import DOMAIN, SENSOR_TYPES


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MagicMock(spec=ConfigEntry)


@pytest.fixture
def sample_coordinator_data():
    """Sample coordinator data."""
    return {
        "devices": {
            "44300E0585": {
                "type": "inverter",
                "model": "FlexBOSS21", 
                "firmware_version": "FAAB-2122",
                "sensors": {
                    "ac_power": 1500,
                    "pv_total_power": 401,
                    "internal_temperature": 40,
                    "frequency": 59.98,
                    "yield": 12.5,
                    "yield_lifetime": 1563.4
                },
                "batteries": {
                    "44300E0585-01": {
                        "battery_real_voltage": 51.20,
                        "battery_real_current": -1.54,
                        "state_of_charge": 69,
                        "state_of_health": 100,
                        "cycle_count": 145
                    },
                    "44300E0585-02": {
                        "battery_real_voltage": 51.21,
                        "battery_real_current": -1.55,
                        "state_of_charge": 70,
                        "state_of_health": 99,
                        "cycle_count": 144
                    }
                }
            },
            "4524850115": {
                "type": "gridboss",
                "model": "Grid Boss",
                "firmware_version": "IAAB-1300",
                "sensors": {
                    "frequency": 59.98,
                    "grid_voltage_l1": 241.5,
                    "grid_power_l1": 0,
                    "smart_port1_status": "Smart Load",
                    "smart_port2_status": "Unused"
                }
            },
            "parallel_group": {
                "type": "parallel_group",
                "model": "Parallel Group A",
                "sensors": {
                    "yield": 25.0,
                    "yield_lifetime": 3126.8,
                    "load": 18.9
                }
            }
        }
    }


@pytest.fixture
def mock_coordinator(sample_coordinator_data):
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
    coordinator.data = sample_coordinator_data
    coordinator.get_device_info.return_value = {
        "identifiers": {(DOMAIN, "44300E0585")},
        "name": "FlexBOSS21 44300E0585",
        "manufacturer": "EG4 Electronics",
        "model": "FlexBOSS21",
        "serial_number": "44300E0585",
        "sw_version": "FAAB-2122"
    }
    return coordinator


class TestSensorSetup:
    """Test sensor platform setup."""

    async def test_async_setup_entry_success(self, mock_hass, mock_config_entry, mock_coordinator):
        """Test successful sensor setup."""
        mock_hass.data = {DOMAIN: {mock_config_entry.entry_id: mock_coordinator}}
        
        entities_added = []
        
        async def mock_add_entities(entities, update_before_add=False):
            entities_added.extend(entities)
        
        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
        
        # Should create entities for all device types
        assert len(entities_added) > 0
        
        # Check for different entity types
        inverter_sensors = [e for e in entities_added if isinstance(e, EG4InverterSensor)]
        battery_sensors = [e for e in entities_added if isinstance(e, EG4BatterySensor)]
        
        assert len(inverter_sensors) > 0
        assert len(battery_sensors) > 0

    async def test_async_setup_entry_no_data(self, mock_hass, mock_config_entry):
        """Test sensor setup with no coordinator data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = None
        mock_hass.data = {DOMAIN: {mock_config_entry.entry_id: mock_coordinator}}
        
        entities_added = []
        
        async def mock_add_entities(entities, update_before_add=False):
            entities_added.extend(entities)
        
        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
        
        # Should not create any entities
        assert len(entities_added) == 0


class TestInverterSensorCreation:
    """Test inverter sensor creation."""

    def test_create_inverter_sensors(self, mock_coordinator, sample_coordinator_data):
        """Test inverter sensor creation."""
        device_data = sample_coordinator_data["devices"]["44300E0585"]
        
        sensors = _create_inverter_sensors(mock_coordinator, "44300E0585", device_data)
        
        # Should create main inverter sensors
        inverter_sensors = [s for s in sensors if isinstance(s, EG4InverterSensor)]
        battery_sensors = [s for s in sensors if isinstance(s, EG4BatterySensor)]
        
        assert len(inverter_sensors) > 0
        assert len(battery_sensors) > 0  # Should create battery sensors for each battery
        
        # Check specific sensors exist
        sensor_keys = [s._sensor_key for s in inverter_sensors]
        assert "ac_power" in sensor_keys
        assert "pv_total_power" in sensor_keys
        assert "yield" in sensor_keys  # Renamed and simplified from today_yielding
        assert "yield_lifetime" in sensor_keys  # Renamed from total_yielding

    def test_create_gridboss_sensors(self, mock_coordinator, sample_coordinator_data):
        """Test GridBOSS sensor creation.""" 
        device_data = sample_coordinator_data["devices"]["4524850115"]
        
        sensors = _create_gridboss_sensors(mock_coordinator, "4524850115", device_data)
        
        assert len(sensors) > 0
        
        # Check specific sensors exist
        sensor_keys = [s._sensor_key for s in sensors]
        assert "frequency" in sensor_keys
        assert "grid_voltage_l1" in sensor_keys
        assert "smart_port1_status" in sensor_keys

    def test_create_parallel_group_sensors(self, mock_coordinator, sample_coordinator_data):
        """Test parallel group sensor creation."""
        device_data = sample_coordinator_data["devices"]["parallel_group"]
        
        sensors = _create_parallel_group_sensors(mock_coordinator, "parallel_group", device_data)
        
        assert len(sensors) > 0
        
        # Check specific sensors exist
        sensor_keys = [s._sensor_key for s in sensors]
        assert "yield" in sensor_keys
        assert "yield_lifetime" in sensor_keys


class TestEG4InverterSensor:
    """Test EG4InverterSensor class."""

    def test_inverter_sensor_init(self, mock_coordinator, sample_coordinator_data):
        """Test inverter sensor initialization."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="ac_power", 
            device_type="inverter"
        )
        
        assert sensor._serial == "44300E0585"
        assert sensor._sensor_key == "ac_power"
        assert sensor._device_type == "inverter"
        assert sensor._attr_unique_id == "44300E0585_ac_power"
        assert "FlexBOSS21 44300E0585 AC Power" in sensor._attr_name

    def test_inverter_sensor_gridboss_naming(self, mock_coordinator, sample_coordinator_data):
        """Test GridBOSS sensor naming."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="4524850115",
            sensor_key="frequency",
            device_type="gridboss"
        )
        
        assert sensor._attr_name == "Frequency"  # GridBOSS sensors don't include model in name
        assert "gridboss_4524850115_frequency" in sensor._attr_entity_id

    def test_inverter_sensor_parallel_group_naming(self, mock_coordinator, sample_coordinator_data):
        """Test parallel group sensor naming."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="parallel_group",
            sensor_key="yield",
            device_type="parallel_group"
        )
        
        assert "Parallel Group A Yield" in sensor._attr_name
        assert "parallel_group_yield" in sensor._attr_entity_id

    def test_sensor_properties(self, mock_coordinator, sample_coordinator_data):
        """Test sensor properties from SENSOR_TYPES."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="ac_power",
            device_type="inverter"
        )
        
        # Check properties are set from SENSOR_TYPES
        assert sensor._attr_native_unit_of_measurement == "W"
        assert sensor._attr_device_class == "power"
        assert sensor._attr_state_class == "measurement"
        assert sensor._attr_icon == "mdi:solar-power"

    def test_diagnostic_entity_category(self, mock_coordinator, sample_coordinator_data):
        """Test diagnostic sensors get proper entity category."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="status_code",
            device_type="inverter"
        )
        
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_sensor_native_value(self, mock_coordinator, sample_coordinator_data):
        """Test sensor native value retrieval."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="ac_power",
            device_type="inverter"
        )
        
        assert sensor.native_value == 1500

    def test_sensor_availability(self, mock_coordinator, sample_coordinator_data):
        """Test sensor availability."""
        mock_coordinator.data = sample_coordinator_data
        mock_coordinator.last_update_success = True
        
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="ac_power",
            device_type="inverter"
        )
        
        assert sensor.available is True
        
        # Test with failed update
        mock_coordinator.last_update_success = False
        assert sensor.available is False
        
        # Test with device error
        mock_coordinator.last_update_success = True
        sample_coordinator_data["devices"]["44300E0585"]["error"] = "Device offline"
        assert sensor.available is False


class TestEG4BatterySensor:
    """Test EG4BatterySensor class."""

    def test_battery_sensor_init(self, mock_coordinator, sample_coordinator_data):
        """Test battery sensor initialization."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="state_of_charge"
        )
        
        assert sensor._serial == "44300E0585"
        assert sensor._battery_key == "44300E0585-01"
        assert sensor._sensor_key == "state_of_charge"
        assert sensor._attr_unique_id == "44300E0585_44300E0585-01_state_of_charge"
        assert "Battery 44300E0585-01 State of Charge" in sensor._attr_name

    def test_battery_sensor_properties(self, mock_coordinator, sample_coordinator_data):
        """Test battery sensor properties."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="state_of_charge"
        )
        
        # Check properties from SENSOR_TYPES
        assert sensor._attr_native_unit_of_measurement == "%"
        assert sensor._attr_device_class == "battery"
        assert sensor._attr_state_class == "measurement"

    def test_battery_sensor_diagnostic_category(self, mock_coordinator, sample_coordinator_data):
        """Test battery diagnostic sensors."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="cycle_count"
        )
        
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_battery_sensor_native_value(self, mock_coordinator, sample_coordinator_data):
        """Test battery sensor native value retrieval."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="state_of_charge"
        )
        
        assert sensor.native_value == 69

    def test_battery_sensor_device_info(self, mock_coordinator, sample_coordinator_data):
        """Test battery sensor device info."""
        mock_coordinator.data = sample_coordinator_data
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="state_of_charge"
        )
        
        device_info = sensor.device_info
        
        assert device_info["name"] == "Battery 44300E0585-01"
        assert device_info["manufacturer"] == "EG4 Electronics"
        assert device_info["model"] == "Battery Module"
        assert device_info["serial_number"] == "44300E0585-01"

    def test_battery_sensor_availability(self, mock_coordinator, sample_coordinator_data):
        """Test battery sensor availability."""
        mock_coordinator.data = sample_coordinator_data
        mock_coordinator.last_update_success = True
        
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            battery_key="44300E0585-01",
            sensor_key="state_of_charge"
        )
        
        assert sensor.available is True
        
        # Test with missing battery data
        del sample_coordinator_data["devices"]["44300E0585"]["batteries"]["44300E0585-01"]
        assert sensor.available is False


if __name__ == "__main__":
    pytest.main([__file__])