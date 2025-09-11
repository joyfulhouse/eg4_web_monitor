"""Sensor validation tests for EG4 Inverter integration."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)

from custom_components.eg4_inverter.sensor import EG4InverterSensor, async_setup_entry
from custom_components.eg4_inverter.const import SENSOR_DEFINITIONS
from custom_components.eg4_inverter.coordinator import EG4DataUpdateCoordinator


class TestSensorValidation:
    """Test sensor validation and attributes."""

    def test_sensor_definitions_completeness(self):
        """Test that all sensor definitions have required attributes."""
        required_fields = ["name", "unit", "device_class", "state_class"]
        
        for sensor_key, definition in SENSOR_DEFINITIONS.items():
            # Check all required fields are present
            for field in required_fields:
                assert field in definition, f"Sensor {sensor_key} missing {field}"
            
            # Validate unit types
            unit = definition["unit"]
            if unit is not None:
                valid_units = {
                    UnitOfPower.WATT, UnitOfPower.KILO_WATT,
                    UnitOfElectricCurrent.AMPERE,
                    UnitOfElectricPotential.VOLT,
                    UnitOfEnergy.WATT_HOUR, UnitOfEnergy.KILO_WATT_HOUR,
                    UnitOfTemperature.CELSIUS,
                    UnitOfFrequency.HERTZ,
                    "%"
                }
                assert unit in valid_units, f"Sensor {sensor_key} has invalid unit: {unit}"
            
            # Validate device classes
            device_class = definition["device_class"]
            if device_class is not None:
                valid_device_classes = {
                    SensorDeviceClass.POWER,
                    SensorDeviceClass.ENERGY,
                    SensorDeviceClass.CURRENT,
                    SensorDeviceClass.VOLTAGE,
                    SensorDeviceClass.TEMPERATURE,
                    SensorDeviceClass.FREQUENCY,
                    SensorDeviceClass.BATTERY,
                    None
                }
                assert device_class in valid_device_classes, f"Sensor {sensor_key} has invalid device_class: {device_class}"
            
            # Validate state classes
            state_class = definition["state_class"]
            if state_class is not None:
                valid_state_classes = {
                    SensorStateClass.MEASUREMENT,
                    SensorStateClass.TOTAL,
                    SensorStateClass.TOTAL_INCREASING,
                    None
                }
                assert state_class in valid_state_classes, f"Sensor {sensor_key} has invalid state_class: {state_class}"

    def test_sensor_entity_categories(self):
        """Test sensor entity categories are properly assigned."""
        diagnostic_sensors = {
            "status_code", "status_text", "firmware_version",
            "battery_firmware_version"
        }
        
        for sensor_key, definition in SENSOR_DEFINITIONS.items():
            entity_category = definition.get("entity_category")
            
            if sensor_key in diagnostic_sensors:
                assert entity_category == EntityCategory.DIAGNOSTIC, \
                    f"Sensor {sensor_key} should be diagnostic"
            else:
                # Most sensors should not have entity category (default sensors)
                if entity_category is not None:
                    assert entity_category in {EntityCategory.DIAGNOSTIC, EntityCategory.CONFIG}, \
                        f"Sensor {sensor_key} has invalid entity_category: {entity_category}"

    def test_energy_sensor_state_classes(self):
        """Test energy sensors have correct state classes."""
        energy_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                         if v.get("device_class") == SensorDeviceClass.ENERGY]
        
        for sensor_key in energy_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            state_class = definition.get("state_class")
            
            if "lifetime" in sensor_key or "total" in sensor_key:
                assert state_class == SensorStateClass.TOTAL_INCREASING, \
                    f"Lifetime/total energy sensor {sensor_key} should use TOTAL_INCREASING"
            elif sensor_key in ["yield", "discharging", "charging", "consumption", "import", "export"]:
                assert state_class == SensorStateClass.TOTAL_INCREASING, \
                    f"Daily energy sensor {sensor_key} should use TOTAL_INCREASING"

    def test_power_sensor_attributes(self):
        """Test power sensors have correct attributes."""
        power_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                        if v.get("device_class") == SensorDeviceClass.POWER]
        
        for sensor_key in power_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            # Power sensors should use MEASUREMENT state class
            assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                f"Power sensor {sensor_key} should use MEASUREMENT state_class"
            
            # Power sensors should use WATT unit
            unit = definition.get("unit")
            assert unit in {UnitOfPower.WATT, UnitOfPower.KILO_WATT}, \
                f"Power sensor {sensor_key} should use WATT or KILO_WATT unit, got {unit}"

    def test_voltage_sensor_attributes(self):
        """Test voltage sensors have correct attributes."""
        voltage_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                          if v.get("device_class") == SensorDeviceClass.VOLTAGE]
        
        for sensor_key in voltage_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            # Voltage sensors should use MEASUREMENT state class
            assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                f"Voltage sensor {sensor_key} should use MEASUREMENT state_class"
            
            # Voltage sensors should use VOLT unit
            assert definition.get("unit") == UnitOfElectricPotential.VOLT, \
                f"Voltage sensor {sensor_key} should use VOLT unit"

    def test_current_sensor_attributes(self):
        """Test current sensors have correct attributes."""
        current_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                          if v.get("device_class") == SensorDeviceClass.CURRENT]
        
        for sensor_key in current_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            # Current sensors should use MEASUREMENT state class
            assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                f"Current sensor {sensor_key} should use MEASUREMENT state_class"
            
            # Current sensors should use AMPERE unit
            assert definition.get("unit") == UnitOfElectricCurrent.AMPERE, \
                f"Current sensor {sensor_key} should use AMPERE unit"

    def test_temperature_sensor_attributes(self):
        """Test temperature sensors have correct attributes."""
        temperature_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                             if v.get("device_class") == SensorDeviceClass.TEMPERATURE]
        
        for sensor_key in temperature_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            # Temperature sensors should use MEASUREMENT state class
            assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                f"Temperature sensor {sensor_key} should use MEASUREMENT state_class"
            
            # Temperature sensors should use CELSIUS unit
            assert definition.get("unit") == UnitOfTemperature.CELSIUS, \
                f"Temperature sensor {sensor_key} should use CELSIUS unit"

    def test_frequency_sensor_attributes(self):
        """Test frequency sensors have correct attributes."""
        frequency_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                           if v.get("device_class") == SensorDeviceClass.FREQUENCY]
        
        for sensor_key in frequency_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            # Frequency sensors should use MEASUREMENT state class
            assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                f"Frequency sensor {sensor_key} should use MEASUREMENT state_class"
            
            # Frequency sensors should use HERTZ unit
            assert definition.get("unit") == UnitOfFrequency.HERTZ, \
                f"Frequency sensor {sensor_key} should use HERTZ unit"

    def test_battery_sensor_attributes(self):
        """Test battery sensors have correct attributes."""
        battery_sensors = [k for k, v in SENSOR_DEFINITIONS.items() 
                          if v.get("device_class") == SensorDeviceClass.BATTERY or "soc" in k or "soh" in k]
        
        for sensor_key in battery_sensors:
            definition = SENSOR_DEFINITIONS[sensor_key]
            
            if "soc" in sensor_key or "soh" in sensor_key:
                # State of charge/health should use % unit
                assert definition.get("unit") == "%", \
                    f"Battery percentage sensor {sensor_key} should use % unit"
                
                # Should use MEASUREMENT state class
                assert definition.get("state_class") == SensorStateClass.MEASUREMENT, \
                    f"Battery sensor {sensor_key} should use MEASUREMENT state_class"


class TestEG4InverterSensorClass:
    """Test EG4InverterSensor class functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
        self.mock_coordinator.data = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {
                        "ac_power": 1500,
                        "ac_voltage": 241.7,
                        "temperature": 45.0,
                        "status_text": "normal"
                    }
                }
            }
        }
        
        # Mock device info
        self.mock_coordinator.get_device_info.return_value = {
            "name": "FlexBOSS21 44300E0585",
            "manufacturer": "EG4 Electronics",
            "model": "FlexBOSS21",
            "serial_number": "44300E0585"
        }

    def test_sensor_initialization(self):
        """Test sensor initialization."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power",
            battery_key=None
        )
        
        assert sensor._device_serial == "44300E0585"
        assert sensor._sensor_key == "ac_power"
        assert sensor._battery_key is None
        assert sensor._sensor_definition == SENSOR_DEFINITIONS["ac_power"]

    def test_sensor_unique_id(self):
        """Test sensor unique ID generation."""
        # Regular sensor
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585", 
            sensor_key="ac_power",
            battery_key=None
        )
        assert sensor.unique_id == "44300E0585_inverter_ac_power"
        
        # Battery sensor
        battery_sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="state_of_charge",
            battery_key="44300E0585-01"
        )
        assert battery_sensor.unique_id == "44300E0585_battery_state_of_charge_44300E0585-01"

    def test_sensor_entity_id(self):
        """Test sensor entity ID generation."""
        # Regular sensor
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power", 
            battery_key=None
        )
        assert sensor.entity_id == "sensor.flexboss21_44300e0585_ac_power"
        
        # Battery sensor
        battery_sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="state_of_charge",
            battery_key="44300E0585-01"
        )
        assert battery_sensor.entity_id == "sensor.battery_44300e0585_01_state_of_charge"

    def test_sensor_name_generation(self):
        """Test sensor name generation."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power",
            battery_key=None
        )
        
        expected_name = f"FlexBOSS21 44300E0585 {SENSOR_DEFINITIONS['ac_power']['name']}"
        assert sensor.name == expected_name

    def test_sensor_state_retrieval(self):
        """Test sensor state retrieval."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power",
            battery_key=None
        )
        
        assert sensor.native_value == 1500

    def test_sensor_attributes(self):
        """Test sensor attributes."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power",
            battery_key=None
        )
        
        # Check sensor attributes from definition
        definition = SENSOR_DEFINITIONS["ac_power"]
        assert sensor.native_unit_of_measurement == definition["unit"]
        assert sensor.device_class == definition["device_class"]
        assert sensor.state_class == definition["state_class"]

    def test_sensor_availability(self):
        """Test sensor availability."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="ac_power",
            battery_key=None
        )
        
        # Sensor should be available when coordinator has data
        self.mock_coordinator.last_update_success = True
        assert sensor.available is True
        
        # Sensor should be unavailable when coordinator update fails
        self.mock_coordinator.last_update_success = False
        assert sensor.available is False

    def test_battery_sensor_state_retrieval(self):
        """Test battery sensor state retrieval."""
        # Add battery data to coordinator
        self.mock_coordinator.data["devices"]["44300E0585"]["batteries"] = {
            "44300E0585-01": {
                "state_of_charge": 69,
                "battery_real_voltage": 51.2
            }
        }
        
        battery_sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="state_of_charge",
            battery_key="44300E0585-01"
        )
        
        assert battery_sensor.native_value == 69

    def test_missing_sensor_data(self):
        """Test handling of missing sensor data."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="44300E0585",
            sensor_key="missing_sensor",
            battery_key=None
        )
        
        assert sensor.native_value is None

    def test_missing_device_data(self):
        """Test handling of missing device data."""
        sensor = EG4InverterSensor(
            coordinator=self.mock_coordinator,
            device_serial="missing_device",
            sensor_key="ac_power",
            battery_key=None
        )
        
        assert sensor.native_value is None


class TestSensorPlatformSetup:
    """Test sensor platform setup."""

    @patch('custom_components.eg4_inverter.sensor.async_add_entities')
    async def test_async_setup_entry(self, mock_add_entities, mock_hass, mock_config_entry):
        """Test sensor platform setup."""
        # Mock coordinator with sample data
        mock_coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
        mock_coordinator.data = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {"ac_power": 1500, "temperature": 45.0},
                    "batteries": {
                        "44300E0585-01": {"state_of_charge": 69}
                    }
                },
                "4524850115": {
                    "type": "gridboss", 
                    "model": "Grid Boss",
                    "sensors": {"grid_power_l1": 0}
                }
            }
        }
        
        mock_hass.data = {
            "eg4_inverter": {
                mock_config_entry.entry_id: mock_coordinator
            }
        }
        
        # Call setup
        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
        
        # Verify entities were added
        mock_add_entities.assert_called_once()
        entities = mock_add_entities.call_args[0][0]
        
        # Should have sensors for both devices and battery
        assert len(entities) > 0
        
        # Check that different device types are handled
        device_serials = {entity._device_serial for entity in entities}
        assert "44300E0585" in device_serials  # Inverter
        assert "4524850115" in device_serials  # GridBOSS

    async def test_async_setup_entry_no_data(self, mock_hass, mock_config_entry):
        """Test sensor platform setup with no coordinator data."""
        # Mock coordinator with no data
        mock_coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
        mock_coordinator.data = None
        
        mock_hass.data = {
            "eg4_inverter": {
                mock_config_entry.entry_id: mock_coordinator
            }
        }
        
        mock_add_entities = MagicMock()
        
        # Call setup
        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
        
        # Should not add any entities
        mock_add_entities.assert_called_once_with([])


if __name__ == "__main__":
    pytest.main([__file__])