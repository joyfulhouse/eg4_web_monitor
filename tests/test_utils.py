"""Tests for EG4 Inverter utility functions."""

import pytest

from custom_components.eg4_inverter.utils import (
    validate_api_response,
    validate_sensor_value,
    safe_division,
    apply_sensor_scaling,
    should_filter_zero_sensor,
    clean_battery_display_name,
    extract_individual_battery_sensors,
    DIVIDE_BY_10_SENSORS,
    DIVIDE_BY_100_SENSORS,
    GRIDBOSS_DIVIDE_BY_10_SENSORS,
    POWER_ENERGY_SENSORS,
    ESSENTIAL_SENSORS
)


class TestValidationFunctions:
    """Test validation utility functions."""

    def test_validate_api_response_valid(self):
        """Test API response validation with valid data."""
        data = {"success": True, "serialNum": "123"}
        
        assert validate_api_response(data) is True
        assert validate_api_response(data, ["success"]) is True
        assert validate_api_response(data, ["success", "serialNum"]) is True

    def test_validate_api_response_invalid(self):
        """Test API response validation with invalid data."""
        # Non-dict data
        assert validate_api_response("not a dict") is False
        assert validate_api_response(None) is False
        assert validate_api_response([1, 2, 3]) is False
        
        # Missing required fields
        data = {"success": True}
        assert validate_api_response(data, ["missing_field"]) is False
        assert validate_api_response(data, ["success", "missing_field"]) is False

    def test_validate_sensor_value_valid(self):
        """Test sensor value validation with valid data."""
        assert validate_sensor_value(42, "temperature") == 42
        assert validate_sensor_value("123.45", "ac_voltage") == 123.45
        assert validate_sensor_value(0, "ac_power") == 0
        assert validate_sensor_value("normal", "status_text") == "normal"

    def test_validate_sensor_value_invalid(self):
        """Test sensor value validation with invalid data."""
        assert validate_sensor_value(None, "temperature") is None
        assert validate_sensor_value("", "temperature") is None
        assert validate_sensor_value("N/A", "temperature") is None
        assert validate_sensor_value("invalid", "ac_voltage") is None

    def test_safe_division_valid(self):
        """Test safe division with valid inputs."""
        assert safe_division(100, 10.0, "test_sensor") == 10.0
        assert safe_division("100", 10.0, "test_sensor") == 10.0
        assert safe_division(0, 10.0, "test_sensor") == 0.0

    def test_safe_division_invalid(self):
        """Test safe division with invalid inputs."""
        assert safe_division(None, 10.0, "test_sensor") is None
        assert safe_division("invalid", 10.0, "test_sensor") is None
        assert safe_division(100, 0.0, "test_sensor") is None


class TestSensorScaling:
    """Test sensor scaling functions."""

    def test_apply_sensor_scaling_inverter(self):
        """Test sensor scaling for inverter devices."""
        # Test divide by 10 sensors
        assert apply_sensor_scaling("ac_voltage", 2417, "inverter") == 241.7
        assert apply_sensor_scaling("temperature", 450, "inverter") == 45.0
        
        # Test divide by 100 sensors
        assert apply_sensor_scaling("frequency", 5998, "inverter") == 59.98
        
        # Test no scaling
        assert apply_sensor_scaling("ac_power", 1500, "inverter") == 1500

    def test_apply_sensor_scaling_gridboss(self):
        """Test sensor scaling for GridBOSS devices."""
        # Test GridBOSS divide by 10 sensors
        assert apply_sensor_scaling("grid_voltage_l1", 2415, "gridboss") == 241.5
        assert apply_sensor_scaling("ups_l1", 125, "gridboss") == 12.5
        
        # Test divide by 100 sensors (frequency)
        assert apply_sensor_scaling("frequency", 5998, "gridboss") == 59.98
        
        # Test no scaling
        assert apply_sensor_scaling("grid_power_l1", 0, "gridboss") == 0

    def test_apply_sensor_scaling_invalid_values(self):
        """Test sensor scaling with invalid values."""
        assert apply_sensor_scaling("ac_voltage", None, "inverter") is None
        assert apply_sensor_scaling("ac_voltage", "N/A", "inverter") is None
        assert apply_sensor_scaling("ac_voltage", "", "inverter") is None


class TestZeroFiltering:
    """Test zero value filtering functions."""

    def test_should_filter_zero_sensor_essential(self):
        """Test filtering of essential sensors (should never be filtered)."""
        # Essential sensors should never be filtered
        assert should_filter_zero_sensor("grid_power", 0) is False
        assert should_filter_zero_sensor("grid_power_l1", 0) is False
        assert should_filter_zero_sensor("smart_port1_status", 0) is False

    def test_should_filter_zero_sensor_power_energy(self):
        """Test filtering of power/energy sensors."""
        # Power/energy sensors should be filtered when zero
        assert should_filter_zero_sensor("load_power", 0) is True
        assert should_filter_zero_sensor("smart_load_power", 0) is True
        assert should_filter_zero_sensor("generator_power", 0) is True
        
        # But not when non-zero
        assert should_filter_zero_sensor("load_power", 100) is False
        assert should_filter_zero_sensor("smart_load_power", 50) is False

    def test_should_filter_zero_sensor_non_power(self):
        """Test filtering of non-power sensors."""
        # Non-power sensors should not be filtered
        assert should_filter_zero_sensor("temperature", 0) is False
        assert should_filter_zero_sensor("frequency", 0) is False
        assert should_filter_zero_sensor("status_text", 0) is False

    def test_should_filter_zero_sensor_non_zero(self):
        """Test that non-zero values are never filtered."""
        assert should_filter_zero_sensor("load_power", 100) is False
        assert should_filter_zero_sensor("smart_load_power", 0.1) is False
        assert should_filter_zero_sensor("generator_power", -50) is False


class TestBatteryUtilities:
    """Test battery-related utility functions."""

    def test_clean_battery_display_name_formats(self):
        """Test various battery key formats."""
        serial = "4512670118"
        
        # Test full format with serial
        assert clean_battery_display_name("4512670118_Battery_ID_01", serial) == "4512670118-01"
        
        # Test battery ID format
        assert clean_battery_display_name("Battery_ID_02", serial) == "4512670118-02"
        
        # Test BAT format
        assert clean_battery_display_name("BAT001", serial) == "BAT001"
        
        # Test numeric format
        assert clean_battery_display_name("3", serial) == "4512670118-03"
        assert clean_battery_display_name("10", serial) == "4512670118-10"
        
        # Test empty/None
        assert clean_battery_display_name("", serial) == "01"
        assert clean_battery_display_name(None, serial) == "01"
        
        # Test underscore format
        assert clean_battery_display_name("test_key_format", serial) == "test-key-format"

    def test_extract_individual_battery_sensors_complete(self):
        """Test battery sensor extraction with complete data."""
        bat_data = {
            "totalVoltage": 5120,  # Should be divided by 100
            "current": -154,       # Should be divided by 10
            "soc": 69,
            "soh": 100,
            "cycleCnt": 145,
            "fwVersionText": "2.17",
            "batMaxCellVoltage": 3210,  # Should be divided by 100
            "batMinCellVoltage": 3190,  # Should be divided by 100
            "batMaxCellTemp": 245,      # Should be divided by 10
            "batMinCellTemp": 230,      # Should be divided by 10
            "currentRemainCapacity": 280000,  # Should be divided by 1000
            "currentFullCapacity": 300000,    # Should be divided by 1000
            "batMaxCellNumVolt": 1,
            "batMinCellNumVolt": 16
        }
        
        sensors = extract_individual_battery_sensors(bat_data)
        
        # Check core sensors
        assert sensors["battery_real_voltage"] == 51.20
        assert sensors["battery_real_current"] == -15.4
        assert sensors["state_of_charge"] == 69
        assert sensors["state_of_health"] == 100
        assert sensors["cycle_count"] == 145
        assert sensors["battery_firmware_version"] == "2.17"
        
        # Check voltage sensors
        assert sensors["battery_cell_voltage_max"] == 32.10
        assert sensors["battery_cell_voltage_min"] == 31.90
        
        # Check temperature sensors
        assert sensors["battery_cell_temp_max"] == 24.5
        assert sensors["battery_cell_temp_min"] == 23.0
        
        # Check capacity sensors
        assert sensors["battery_remaining_capacity"] == 280.0
        assert sensors["battery_full_capacity"] == 300.0
        
        # Check cell number sensors
        assert sensors["battery_max_cell_voltage_num"] == 1
        assert sensors["battery_min_cell_voltage_num"] == 16

    def test_extract_individual_battery_sensors_minimal(self):
        """Test battery sensor extraction with minimal data."""
        bat_data = {
            "totalVoltage": 5120,
            "current": -154,
            "soc": 69
        }
        
        sensors = extract_individual_battery_sensors(bat_data)
        
        # Should only have the available sensors
        assert len(sensors) == 3
        assert sensors["battery_real_voltage"] == 51.20
        assert sensors["battery_real_current"] == -15.4
        assert sensors["state_of_charge"] == 69
        
        # Should not have missing sensors
        assert "battery_cell_temp_max" not in sensors
        assert "battery_firmware_version" not in sensors

    def test_extract_individual_battery_sensors_invalid_data(self):
        """Test battery sensor extraction with invalid data."""
        bat_data = {
            "totalVoltage": "N/A",
            "current": "",
            "soc": None,
            "batMaxCellTemp": "invalid"
        }
        
        sensors = extract_individual_battery_sensors(bat_data)
        
        # Should filter out invalid values
        assert len(sensors) == 0


class TestConstants:
    """Test utility constants."""

    def test_scaling_sensor_sets(self):
        """Test that scaling sensor sets contain expected values."""
        # Check some known sensors exist in appropriate sets
        assert "ac_voltage" in DIVIDE_BY_10_SENSORS
        assert "temperature" in DIVIDE_BY_10_SENSORS
        
        assert "frequency" in DIVIDE_BY_100_SENSORS
        assert "generator_frequency" in DIVIDE_BY_100_SENSORS
        
        assert "grid_voltage_l1" in GRIDBOSS_DIVIDE_BY_10_SENSORS
        assert "ups_l1" in GRIDBOSS_DIVIDE_BY_10_SENSORS

    def test_filtering_sensor_sets(self):
        """Test that filtering sensor sets contain expected values."""
        # Check essential sensors
        assert "grid_power" in ESSENTIAL_SENSORS
        assert "grid_power_l1" in ESSENTIAL_SENSORS
        assert "smart_port1_status" in ESSENTIAL_SENSORS
        
        # Check power/energy sensors
        assert "load_power" in POWER_ENERGY_SENSORS
        assert "smart_load_power" in POWER_ENERGY_SENSORS

    def test_sensor_set_overlaps(self):
        """Test appropriate overlaps between sensor sets."""
        # Power/energy sensors should include some scaling sensors
        gridboss_energy_overlap = POWER_ENERGY_SENSORS & GRIDBOSS_DIVIDE_BY_10_SENSORS
        assert len(gridboss_energy_overlap) > 0  # Should have some overlap
        
        # Essential sensors should not overlap with power sensors that get filtered
        filterable_power = POWER_ENERGY_SENSORS - ESSENTIAL_SENSORS
        essential_overlap = ESSENTIAL_SENSORS & filterable_power
        assert len(essential_overlap) == 0  # Should have no overlap


if __name__ == "__main__":
    pytest.main([__file__])