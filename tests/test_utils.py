"""Tests for utility functions in EG4 Web Monitor integration."""

from custom_components.eg4_web_monitor.utils import (
    clean_battery_display_name,
    clean_model_name,
    create_device_info,
    generate_entity_id,
    generate_unique_id,
)


class TestCleanBatteryDisplayName:
    """Test clean_battery_display_name function."""

    def test_empty_key(self):
        """Test empty battery key."""
        assert clean_battery_display_name("", "1234567890") == "01"

    def test_battery_id_format(self):
        """Test Battery_ID format."""
        assert (
            clean_battery_display_name("Battery_ID_01", "1234567890") == "1234567890-01"
        )

    def test_serial_battery_id_format(self):
        """Test serial_Battery_ID format."""
        result = clean_battery_display_name("1234567890_Battery_ID_02", "1234567890")
        assert result == "1234567890-02"

    def test_bat_prefix(self):
        """Test BAT prefix format."""
        assert clean_battery_display_name("BAT001", "1234567890") == "BAT001"

    def test_numeric_key(self):
        """Test numeric key."""
        assert clean_battery_display_name("1", "1234567890") == "1234567890-01"

    def test_two_digit_numeric(self):
        """Test two-digit numeric key."""
        assert clean_battery_display_name("05", "1234567890") == "1234567890-05"

    def test_generic_key(self):
        """Test generic key with underscores."""
        assert (
            clean_battery_display_name("some_key_name", "1234567890") == "some-key-name"
        )


class TestCleanModelName:
    """Test clean_model_name function."""

    def test_normal_model(self):
        """Test normal model name."""
        assert clean_model_name("FlexBOSS21") == "flexboss21"

    def test_with_spaces(self):
        """Test model with spaces."""
        assert clean_model_name("Flex BOSS 21") == "flexboss21"

    def test_with_hyphens(self):
        """Test model with hyphens."""
        assert clean_model_name("Flex-BOSS-21") == "flexboss21"

    def test_empty_string(self):
        """Test empty string."""
        assert clean_model_name("") == "unknown"

    def test_mixed_case(self):
        """Test mixed case."""
        assert clean_model_name("GridBOSS-MID") == "gridbossmid"

    def test_with_underscores_option(self):
        """Test with use_underscores option."""
        assert clean_model_name("Flex BOSS 21", use_underscores=True) == "flex_boss_21"


class TestCreateDeviceInfo:
    """Test create_device_info function."""

    def test_inverter_device(self):
        """Test inverter device info creation."""
        info = create_device_info("1234567890", "FlexBOSS21")

        assert info["identifiers"] == {("eg4_web_monitor", "1234567890")}
        assert info["name"] == "FlexBOSS21 1234567890"
        assert info["manufacturer"] == "EG4 Electronics"
        assert info["model"] == "FlexBOSS21"
        assert info["serial_number"] == "1234567890"

    def test_gridboss_device(self):
        """Test GridBOSS device info creation."""
        info = create_device_info("9876543210", "GridBOSS")

        assert info["name"] == "GridBOSS 9876543210"
        assert info["model"] == "GridBOSS"


class TestGenerateEntityId:
    """Test generate_entity_id function."""

    def test_basic_entity_id(self):
        """Test basic entity ID generation."""
        entity_id = generate_entity_id("sensor", "FlexBOSS21", "1234567890", "ac_power")
        assert entity_id == "sensor.flexboss21_1234567890_ac_power"

    def test_with_suffix(self):
        """Test entity ID with suffix."""
        entity_id = generate_entity_id(
            "sensor", "FlexBOSS21", "1234567890", "battery", "01"
        )
        assert entity_id == "sensor.flexboss21_1234567890_battery_01"

    def test_model_cleaning(self):
        """Test model name is cleaned."""
        entity_id = generate_entity_id(
            "sensor", "Flex-BOSS 21", "1234567890", "voltage"
        )
        assert entity_id == "sensor.flexboss21_1234567890_voltage"


class TestGenerateUniqueId:
    """Test generate_unique_id function."""

    def test_basic_unique_id(self):
        """Test basic unique ID generation."""
        unique_id = generate_unique_id("1234567890", "ac_power")
        assert unique_id == "1234567890_ac_power"

    def test_with_suffix(self):
        """Test unique ID with suffix."""
        unique_id = generate_unique_id("1234567890", "battery", "01")
        assert unique_id == "1234567890_battery_01"
