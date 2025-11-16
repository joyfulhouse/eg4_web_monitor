"""Tests for utility functions in EG4 Web Monitor integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from custom_components.eg4_web_monitor.utils import (
    validate_api_response,
    validate_sensor_value,
    safe_division,
    apply_sensor_scaling,
    should_filter_zero_sensor,
    to_camel_case,
    clean_battery_display_name,
    extract_individual_battery_sensors,
    clean_model_name,
    create_device_info,
    generate_entity_id,
    generate_unique_id,
    create_entity_name,
    safe_get_nested_value,
    validate_device_data,
    CircuitBreaker,
    read_device_parameters_ranges,
    process_parameter_responses,
    DIVIDE_BY_10_SENSORS,
    DIVIDE_BY_100_SENSORS,
    ESSENTIAL_SENSORS,
)


class TestValidateApiResponse:
    """Test validate_api_response function."""

    def test_valid_response_no_required_fields(self):
        """Test validation with no required fields."""
        data = {"key1": "value1", "key2": "value2"}
        assert validate_api_response(data) is True

    def test_valid_response_with_required_fields(self):
        """Test validation with all required fields present."""
        data = {"key1": "value1", "key2": "value2", "key3": "value3"}
        required = ["key1", "key2"]
        assert validate_api_response(data, required) is True

    def test_invalid_response_missing_fields(self):
        """Test validation fails when required fields are missing."""
        data = {"key1": "value1"}
        required = ["key1", "key2", "key3"]
        assert validate_api_response(data, required) is False

    def test_empty_dict_no_required_fields(self):
        """Test empty dict validates when no fields required."""
        assert validate_api_response({}) is True


class TestValidateSensorValue:
    """Test validate_sensor_value function."""

    def test_none_value(self):
        """Test that None returns None."""
        assert validate_sensor_value(None, "test_sensor") is None

    def test_empty_string_value(self):
        """Test that empty string returns None."""
        assert validate_sensor_value("", "test_sensor") is None

    def test_na_value(self):
        """Test that N/A returns None."""
        assert validate_sensor_value("N/A", "test_sensor") is None

    def test_numeric_sensor_valid_value(self):
        """Test numeric sensor with valid value."""
        result = validate_sensor_value(123, "ac_voltage")
        assert result == 123.0

    def test_numeric_sensor_string_number(self):
        """Test numeric sensor with string number."""
        result = validate_sensor_value("45.6", "battery_voltage")
        assert result == 45.6

    def test_numeric_sensor_invalid_value(self):
        """Test numeric sensor with invalid value."""
        result = validate_sensor_value("invalid", "ac_voltage")
        assert result is None

    def test_string_sensor_from_int(self):
        """Test string conversion from int."""
        result = validate_sensor_value(42, "status")
        assert result == "42"

    def test_string_sensor_from_float(self):
        """Test string conversion from float."""
        result = validate_sensor_value(3.14, "mode")
        assert result == "3.14"

    def test_string_sensor_strip_whitespace(self):
        """Test string strips whitespace."""
        result = validate_sensor_value("  test  ", "status")
        assert result == "test"


class TestSafeDivision:
    """Test safe_division function."""

    def test_valid_division(self):
        """Test valid division."""
        result = safe_division(100, 10, "test_sensor")
        assert result == 10.0

    def test_none_value(self):
        """Test None value returns None."""
        result = safe_division(None, 10, "test_sensor")
        assert result is None

    def test_division_by_zero(self):
        """Test division by zero returns None."""
        result = safe_division(100, 0, "test_sensor")
        assert result is None

    def test_invalid_value_type(self):
        """Test invalid value type returns None."""
        result = safe_division("invalid", 10, "test_sensor")
        assert result is None

    def test_string_numeric_value(self):
        """Test string numeric value converts correctly."""
        result = safe_division("100", 10, "test_sensor")
        assert result == 10.0


class TestApplySensorScaling:
    """Test apply_sensor_scaling function."""

    def test_none_value(self):
        """Test None value returns None."""
        result = apply_sensor_scaling("test_sensor", None)
        assert result is None

    def test_divide_by_10_sensor(self):
        """Test sensor that divides by 10."""
        result = apply_sensor_scaling("ac_voltage", 2400)
        assert result == 240.0

    def test_divide_by_100_sensor(self):
        """Test sensor that divides by 100."""
        result = apply_sensor_scaling("frequency", 5000)
        assert result == 50.0

    def test_kw_sensor(self):
        """Test sensor that divides by 1000 (kW)."""
        result = apply_sensor_scaling("ac_power", 5000)
        assert result == 5.0

    def test_gridboss_scaling(self):
        """Test GridBOSS device scaling."""
        # GridBOSS voltage sensors divide by 10
        result = apply_sensor_scaling("grid_voltage_l1", 1200, device_type="gridboss")
        assert result == 120.0

    def test_no_scaling_needed(self):
        """Test sensor with no scaling."""
        # Sensors not in any scaling set should return validated value as-is
        # Integer values get converted to strings by validate_sensor_value
        result = apply_sensor_scaling("unknown_sensor", 85)
        assert result == "85"  # validate_sensor_value converts int to string

    def test_invalid_value(self):
        """Test invalid value returns None."""
        result = apply_sensor_scaling("ac_voltage", "invalid")
        assert result is None


class TestShouldFilterZeroSensor:
    """Test should_filter_zero_sensor function."""

    def test_non_zero_value(self):
        """Test non-zero value is not filtered."""
        assert should_filter_zero_sensor("grid_power", 100) is False

    def test_essential_sensor_zero(self):
        """Test essential sensor with zero is not filtered."""
        assert should_filter_zero_sensor("grid_power", 0) is False

    def test_power_sensor_zero(self):
        """Test power sensor with zero is filtered."""
        assert should_filter_zero_sensor("load_power", 0) is True

    def test_non_numeric_value(self):
        """Test non-numeric value is not filtered."""
        assert should_filter_zero_sensor("status", "active") is False

    def test_string_zero(self):
        """Test string zero is not filtered."""
        assert should_filter_zero_sensor("test", "0") is False


class TestToCamelCase:
    """Test to_camel_case function."""

    def test_spaces(self):
        """Test conversion with spaces."""
        assert to_camel_case("hello world") == "helloWorld"

    def test_underscores(self):
        """Test conversion with underscores."""
        assert to_camel_case("hello_world") == "helloWorld"

    def test_mixed(self):
        """Test conversion with mixed separators."""
        assert to_camel_case("hello_world test") == "helloWorldTest"

    def test_empty_string(self):
        """Test empty string."""
        assert to_camel_case("") == ""

    def test_single_word(self):
        """Test single word."""
        assert to_camel_case("hello") == "hello"

    def test_multiple_words(self):
        """Test multiple words."""
        assert to_camel_case("one two three four") == "oneTwoThreeFour"


class TestCleanBatteryDisplayName:
    """Test clean_battery_display_name function."""

    def test_empty_key(self):
        """Test empty battery key."""
        assert clean_battery_display_name("", "1234567890") == "01"

    def test_battery_id_format(self):
        """Test Battery_ID format."""
        assert clean_battery_display_name("Battery_ID_01", "1234567890") == "1234567890-01"

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
        assert clean_battery_display_name("some_key_name", "1234567890") == "some-key-name"


class TestExtractIndividualBatterySensors:
    """Test extract_individual_battery_sensors function."""

    def test_core_sensors(self):
        """Test extraction of core battery sensors."""
        bat_data = {
            "totalVoltage": 5120,
            "current": 100,
            "soc": 85,
            "soh": 98,
            "cycleCnt": 50,
        }
        result = extract_individual_battery_sensors(bat_data)

        assert "battery_real_voltage" in result
        assert result["battery_real_voltage"] == 51.2  # Divided by 100
        assert "battery_real_current" in result
        assert result["battery_real_current"] == 10.0  # Divided by 10
        assert result["state_of_charge"] == 85
        assert result["state_of_health"] == 98
        assert result["cycle_count"] == 50

    def test_temperature_sensors(self):
        """Test extraction of temperature sensors."""
        bat_data = {
            "soc": 85,
            "batMaxCellTemp": 250,
            "batMinCellTemp": 200,
            "ambientTemp": 230,
            "mosTemp": 280,
        }
        result = extract_individual_battery_sensors(bat_data)

        assert "battery_cell_temp_max" in result
        assert result["battery_cell_temp_max"] == 25.0  # Divided by 10
        assert "battery_cell_temp_min" in result
        assert result["battery_cell_temp_min"] == 20.0

    def test_voltage_sensors(self):
        """Test extraction of voltage sensors."""
        bat_data = {
            "soc": 85,
            "batMaxCellVoltage": 3400,
            "batMinCellVoltage": 3200,
        }
        result = extract_individual_battery_sensors(bat_data)

        assert "battery_cell_voltage_max" in result
        assert result["battery_cell_voltage_max"] == 3.4  # Divided by 1000
        assert "battery_cell_voltage_min" in result
        assert result["battery_cell_voltage_min"] == 3.2

    def test_skip_invalid_temperature(self):
        """Test skipping invalid temperature values."""
        bat_data = {
            "soc": 85,
            "batMaxCellTemp": "",
            "batMinCellTemp": "N/A",
        }
        result = extract_individual_battery_sensors(bat_data)

        assert "battery_cell_temp_max" not in result
        assert "battery_cell_temp_min" not in result

    def test_cell_number_sensors(self):
        """Test extraction of cell number sensors."""
        bat_data = {
            "soc": 85,
            "batMaxCellNumTemp": "5",
            "batMinCellNumTemp": "2",
            "batMaxCellNumVolt": "8",
            "batMinCellNumVolt": "3",
        }
        result = extract_individual_battery_sensors(bat_data)

        assert result["battery_max_cell_temp_num"] == 5
        assert result["battery_min_cell_temp_num"] == 2
        assert result["battery_max_cell_voltage_num"] == 8
        assert result["battery_min_cell_voltage_num"] == 3


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


class TestCreateDeviceInfo:
    """Test create_device_info function."""

    def test_inverter_device(self):
        """Test inverter device info creation."""
        info = create_device_info("1234567890", "FlexBOSS21", "inverter")

        assert info["identifiers"] == {("eg4_web_monitor", "1234567890")}
        assert info["name"] == "FlexBOSS21 1234567890"
        assert info["manufacturer"] == "EG4 Electronics"
        assert info["model"] == "FlexBOSS21"
        assert info["serial_number"] == "1234567890"

    def test_gridboss_device(self):
        """Test GridBOSS device info creation."""
        info = create_device_info("9876543210", "GridBOSS", "gridboss")

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


class TestCreateEntityName:
    """Test create_entity_name function."""

    def test_entity_name(self):
        """Test entity name creation."""
        name = create_entity_name("FlexBOSS21", "1234567890", "AC Power")
        assert name == "FlexBOSS21 1234567890 AC Power"


class TestSafeGetNestedValue:
    """Test safe_get_nested_value function."""

    def test_valid_path(self):
        """Test valid nested path."""
        data = {"level1": {"level2": {"level3": "value"}}}
        result = safe_get_nested_value(data, ["level1", "level2", "level3"])
        assert result == "value"

    def test_missing_key(self):
        """Test missing key returns default."""
        data = {"level1": {"level2": "value"}}
        result = safe_get_nested_value(data, ["level1", "missing", "key"], default="default")
        assert result == "default"

    def test_none_intermediate(self):
        """Test None intermediate value."""
        data = {"level1": None}
        result = safe_get_nested_value(data, ["level1", "level2"], default="default")
        assert result == "default"

    def test_no_default(self):
        """Test no default specified."""
        data = {"key": "value"}
        result = safe_get_nested_value(data, ["missing"])
        assert result is None


class TestValidateDeviceData:
    """Test validate_device_data function."""

    def test_valid_data(self):
        """Test valid device data."""
        data = {"serial": "1234567890", "model": "FlexBOSS21", "status": "online"}
        assert validate_device_data(data, ["serial", "model"]) is True

    def test_missing_field(self):
        """Test missing required field."""
        data = {"serial": "1234567890"}
        assert validate_device_data(data, ["serial", "model"]) is False

    def test_none_value(self):
        """Test None value for required field."""
        data = {"serial": "1234567890", "model": None}
        assert validate_device_data(data, ["serial", "model"]) is False

    def test_empty_required_fields(self):
        """Test with empty required fields list."""
        data = {"serial": "1234567890"}
        assert validate_device_data(data, []) is True


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    async def test_successful_call(self):
        """Test successful function call."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == "closed"
        assert breaker.failure_count == 0

    async def test_failure_tracking(self):
        """Test failure count tracking."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        async def fail_func():
            raise ValueError("Test error")

        # First failure
        with pytest.raises(ValueError):
            await breaker.call(fail_func)
        assert breaker.failure_count == 1
        assert breaker.state == "closed"

        # Second failure
        with pytest.raises(ValueError):
            await breaker.call(fail_func)
        assert breaker.failure_count == 2
        assert breaker.state == "closed"

    async def test_circuit_opens_after_threshold(self):
        """Test circuit opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        async def fail_func():
            raise ValueError("Test error")

        # Reach threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail_func)

        assert breaker.state == "open"
        assert breaker.failure_count == 3

    async def test_open_circuit_blocks_calls(self):
        """Test open circuit blocks calls."""
        breaker = CircuitBreaker(failure_threshold=1, timeout=60)

        async def fail_func():
            raise ValueError("Test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await breaker.call(fail_func)

        # Should now raise RuntimeError
        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            await breaker.call(fail_func)

    async def test_half_open_recovery(self):
        """Test half-open state allows retry after timeout."""
        breaker = CircuitBreaker(failure_threshold=1, timeout=0)  # 0 second timeout

        async def fail_func():
            raise ValueError("Test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await breaker.call(fail_func)
        assert breaker.state == "open"

        # Wait for timeout
        await asyncio.sleep(0.1)

        # Success should close circuit
        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == "closed"
        assert breaker.failure_count == 0


class TestReadDeviceParametersRanges:
    """Test read_device_parameters_ranges function."""

    async def test_successful_read(self):
        """Test successful parameter read."""
        mock_api = MagicMock()
        mock_api.read_parameters = AsyncMock(
            side_effect=[
                {"register_0": "value0"},
                {"register_127": "value127"},
                {"register_240": "value240"},
            ]
        )

        results = await read_device_parameters_ranges(mock_api, "1234567890")

        assert len(results) == 3
        assert results[0] == {"register_0": "value0"}
        assert results[1] == {"register_127": "value127"}
        assert results[2] == {"register_240": "value240"}

    async def test_partial_failure(self):
        """Test partial failure handling."""
        mock_api = MagicMock()
        mock_api.read_parameters = AsyncMock(
            side_effect=[
                {"register_0": "value0"},
                Exception("Read failed"),
                {"register_240": "value240"},
            ]
        )

        results = await read_device_parameters_ranges(mock_api, "1234567890")

        assert len(results) == 3
        assert results[0] == {"register_0": "value0"}
        assert isinstance(results[1], Exception)
        assert results[2] == {"register_240": "value240"}


class TestProcessParameterResponses:
    """Test process_parameter_responses function."""

    def test_successful_responses(self):
        """Test processing successful responses."""
        responses = [
            {"register_0": "value0"},
            {"register_127": "value127"},
            {"register_240": "value240"},
        ]

        mock_logger = MagicMock()
        results = list(process_parameter_responses(responses, "1234567890", mock_logger))

        assert len(results) == 3
        assert results[0] == (0, {"register_0": "value0"}, 0)
        assert results[1] == (1, {"register_127": "value127"}, 127)
        assert results[2] == (2, {"register_240": "value240"}, 240)

    def test_exception_handling(self):
        """Test exception in responses is skipped."""
        responses = [
            {"register_0": "value0"},
            Exception("Read failed"),
            {"register_240": "value240"},
        ]

        mock_logger = MagicMock()
        results = list(process_parameter_responses(responses, "1234567890", mock_logger))

        # Should only get 2 results (exception is skipped)
        assert len(results) == 2
        assert results[0] == (0, {"register_0": "value0"}, 0)
        assert results[1] == (2, {"register_240": "value240"}, 240)

        # Should log the exception
        mock_logger.debug.assert_called_once()

    def test_all_exceptions(self):
        """Test all responses are exceptions."""
        responses = [
            Exception("Failed 1"),
            Exception("Failed 2"),
            Exception("Failed 3"),
        ]

        mock_logger = MagicMock()
        results = list(process_parameter_responses(responses, "1234567890", mock_logger))

        assert len(results) == 0
        assert mock_logger.debug.call_count == 3
