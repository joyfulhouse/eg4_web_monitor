"""Tests for new entity naming convention."""

import pytest
from unittest.mock import MagicMock, patch

from custom_components.eg4_inverter.sensor import EG4InverterSensor
from custom_components.eg4_inverter.const import SENSOR_TYPES


class TestEntityNamingConvention:
    """Test the new simplified sensor naming convention."""

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_simplified_yield_sensor_names(self, mock_api_class):
        """Test that yield sensors use simplified names."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {
                        "yield": 12.5,
                        "yield_lifetime": 1563.4
                    }
                }
            }
        }

        # Test current day yield sensor
        yield_sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585",
            sensor_key="yield",
            device_type="inverter"
        )

        assert yield_sensor._sensor_key == "yield"
        assert "FlexBOSS21 44300E0585 Yield" in yield_sensor._attr_name
        assert "44300e0585_yield" in yield_sensor._attr_entity_id.lower()

        # Test lifetime yield sensor
        yield_lifetime_sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="44300E0585", 
            sensor_key="yield_lifetime",
            device_type="inverter"
        )

        assert yield_lifetime_sensor._sensor_key == "yield_lifetime"
        assert "FlexBOSS21 44300E0585 Yield (Lifetime)" in yield_lifetime_sensor._attr_name
        assert "44300e0585_yield_lifetime" in yield_lifetime_sensor._attr_entity_id.lower()

    def test_sensor_type_definitions(self):
        """Test that sensor type definitions are correct."""
        # Test yield sensor (current day)
        assert "yield" in SENSOR_TYPES
        yield_config = SENSOR_TYPES["yield"]
        assert yield_config["name"] == "Yield"
        assert yield_config["unit"].value == "kWh"
        assert yield_config["device_class"] == "energy"
        assert yield_config["state_class"] == "total_increasing"

        # Test yield lifetime sensor
        assert "yield_lifetime" in SENSOR_TYPES
        yield_lifetime_config = SENSOR_TYPES["yield_lifetime"]
        assert yield_lifetime_config["name"] == "Yield (Lifetime)"
        assert yield_lifetime_config["unit"].value == "kWh"
        assert yield_lifetime_config["device_class"] == "energy"
        assert yield_lifetime_config["state_class"] == "total_increasing"

    def test_other_energy_sensors_simplified(self):
        """Test that other energy sensors follow same pattern."""
        # Current day sensors (no prefix)
        assert "charging" in SENSOR_TYPES
        assert SENSOR_TYPES["charging"]["name"] == "Charging"

        assert "discharging" in SENSOR_TYPES
        assert SENSOR_TYPES["discharging"]["name"] == "Discharging"

        assert "load" in SENSOR_TYPES
        assert SENSOR_TYPES["load"]["name"] == "Load"

        # Lifetime sensors (_lifetime suffix)
        assert "charging_lifetime" in SENSOR_TYPES
        assert SENSOR_TYPES["charging_lifetime"]["name"] == "Charging (Lifetime)"

        assert "discharging_lifetime" in SENSOR_TYPES
        assert SENSOR_TYPES["discharging_lifetime"]["name"] == "Discharging (Lifetime)"

        assert "load_lifetime" in SENSOR_TYPES
        assert SENSOR_TYPES["load_lifetime"]["name"] == "Load (Lifetime)"

    def test_old_sensor_names_removed(self):
        """Test that old sensor naming patterns are removed."""
        # Old today_ prefixed sensors should not exist
        assert "today_yield" not in SENSOR_TYPES
        assert "today_charging" not in SENSOR_TYPES
        assert "today_discharging" not in SENSOR_TYPES
        assert "today_load" not in SENSOR_TYPES

        # Old total_ prefixed sensors should not exist
        assert "total_yield" not in SENSOR_TYPES
        assert "total_charging" not in SENSOR_TYPES
        assert "total_discharging" not in SENSOR_TYPES
        assert "total_load" not in SENSOR_TYPES

        # Original yielding sensors should not exist
        assert "today_yielding" not in SENSOR_TYPES
        assert "total_yielding" not in SENSOR_TYPES
        
        # GridBOSS sensors should use simplified naming
        assert "ups_today_l1" not in SENSOR_TYPES
        assert "ups_total_l1" not in SENSOR_TYPES
        assert "grid_export_today_l1" not in SENSOR_TYPES  
        assert "grid_export_total_l1" not in SENSOR_TYPES
        assert "smart_load1_today_l1" not in SENSOR_TYPES
        assert "smart_load1_total_l1" not in SENSOR_TYPES

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_example_entity_ids(self, mock_api_class):
        """Test that entity IDs match the expected patterns from requirements."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "4512670118": {
                    "type": "inverter",
                    "model": "18KPV",
                    "sensors": {
                        "yield": 12.5,
                        "yield_lifetime": 1563.4
                    }
                }
            }
        }

        # Test yield sensor (should be sensor.18kpv_4512670118_yield)
        yield_sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="4512670118",
            sensor_key="yield",
            device_type="inverter"
        )

        expected_entity_id = "sensor.eg4_18kpv_4512670118_yield"
        assert yield_sensor._attr_entity_id == expected_entity_id
        assert "18KPV 4512670118 Yield" in yield_sensor._attr_name

        # Test yield lifetime sensor (should be sensor.18kpv_4512670118_yield_lifetime)
        yield_lifetime_sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="4512670118",
            sensor_key="yield_lifetime", 
            device_type="inverter"
        )

        expected_entity_id_lifetime = "sensor.eg4_18kpv_4512670118_yield_lifetime"
        assert yield_lifetime_sensor._attr_entity_id == expected_entity_id_lifetime
        assert "18KPV 4512670118 Yield (Lifetime)" in yield_lifetime_sensor._attr_name

    def test_gridboss_sensor_naming_simplified(self):
        """Test that GridBOSS sensors use simplified naming convention."""
        # Test that new GridBOSS sensors exist with simplified names
        assert "ups_l1" in SENSOR_TYPES
        assert "ups_l2" in SENSOR_TYPES
        assert "ups_lifetime_l1" in SENSOR_TYPES
        assert "ups_lifetime_l2" in SENSOR_TYPES
        assert SENSOR_TYPES["ups_l1"]["name"] == "UPS Consumption L1"
        assert SENSOR_TYPES["ups_lifetime_l1"]["name"] == "UPS Consumption L1 (Lifetime)"

        # Test grid export sensors
        assert "grid_export_l1" in SENSOR_TYPES
        assert "grid_export_lifetime_l1" in SENSOR_TYPES
        assert SENSOR_TYPES["grid_export_l1"]["name"] == "Grid Export L1"
        assert SENSOR_TYPES["grid_export_lifetime_l1"]["name"] == "Grid Export L1 (Lifetime)"

        # Test smart load sensors
        assert "smart_load1_l1" in SENSOR_TYPES
        assert "smart_load1_lifetime_l1" in SENSOR_TYPES
        assert SENSOR_TYPES["smart_load1_l1"]["name"] == "Smart Load 1 L1"
        assert SENSOR_TYPES["smart_load1_lifetime_l1"]["name"] == "Smart Load 1 L1 (Lifetime)"


if __name__ == "__main__":
    pytest.main([__file__])