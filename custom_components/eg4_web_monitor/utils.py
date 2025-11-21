"""Utility functions for EG4 Inverter integration."""

import asyncio
import logging
from typing import (
    Dict,
    Any,
    Set,
    Optional,
    List,
    Callable,
    Tuple,
    Iterator,
    TYPE_CHECKING,
)

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DIVIDE_BY_100_SENSORS as CONST_DIVIDE_BY_100_SENSORS,
    GRIDBOSS_ENERGY_SENSORS,
    VOLTAGE_SENSORS,
    CURRENT_SENSORS,
    DOMAIN,
)

if TYPE_CHECKING:
    from pylxpweb.devices.inverters.base import BaseInverter

_LOGGER = logging.getLogger(__name__)

# Scaling constants - consolidated from duplicated sets across coordinator
DIVIDE_BY_10_SENSORS: Set[str] = {
    "ac_voltage",
    "ac_frequency",
    "battery_voltage",
    "battery_temperature",
    "temperature",
    "radiator_1_temperature",
    "radiator_2_temperature",
    "pv_voltage_1",
    "pv_voltage_2",
    "pv_voltage_3",
    "internal_temperature",
    # Individual battery voltage sensors from batteryArray
    "battery_real_voltage",
    # PV voltage sensors from runtime data
    "pv1_voltage",
    "pv2_voltage",
    "pv3_voltage",
    "dc_voltage",
}

# Using const.py to avoid duplication
DIVIDE_BY_100_SENSORS: Set[str] = CONST_DIVIDE_BY_100_SENSORS

# GridBOSS specific scaling sets - using const.py to avoid duplication
GRIDBOSS_DIVIDE_BY_10_SENSORS: Set[str] = (
    GRIDBOSS_ENERGY_SENSORS | VOLTAGE_SENSORS | CURRENT_SENSORS
)

# Power and energy sensors that should be filtered when zero (except essential ones)
POWER_ENERGY_SENSORS: Set[str] = (
    {
        # GridBOSS power sensors
        "load_power",
        "smart_load_power",
        "generator_power",
        "load_power_l1",
        "load_power_l2",
        "ups_power_l1",
        "ups_power_l2",
        "generator_power_l1",
        "generator_power_l2",
        "smart_load1_power_l1",
        "smart_load1_power_l2",
        "smart_load2_power_l1",
        "smart_load2_power_l2",
        "smart_load3_power_l1",
        "smart_load3_power_l2",
        "smart_load4_power_l1",
        "smart_load4_power_l2",
        # Runtime power sensors from inverter data that need zero filtering
        "eps_load_power",
        "grid_load_power",
        "gen_power",
        "hybrid_power",
    }
    | DIVIDE_BY_100_SENSORS
    | GRIDBOSS_DIVIDE_BY_10_SENSORS
)  # Include all energy sensors for filtering

# Essential sensors that should never be filtered out even when 0
ESSENTIAL_SENSORS: Set[str] = {
    "grid_power",
    "grid_power_l1",
    "grid_power_l2",
    # Smart Port status sensors should always be shown, even when 0 (Unused)
    "smart_port1_status",
    "smart_port2_status",
    "smart_port3_status",
    "smart_port4_status",
}


def validate_api_response(
    data: Dict[str, Any], required_fields: Optional[List[str]] = None
) -> bool:
    """Validate API response data structure."""
    # No runtime check needed - type hint guarantees data is dict
    # Mypy ensures this at compile time

    if required_fields:
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            _LOGGER.warning(
                "Missing required fields in API response: %s", missing_fields
            )
            return False

    return True


def validate_sensor_value(value: Any, sensor_type: str) -> Any:
    """Validate and sanitize sensor values."""
    # Early returns for None and empty/invalid values
    if value is None or value in ("", "N/A"):
        return None

    # Handle numeric sensors that need type conversion
    if (
        sensor_type
        in DIVIDE_BY_10_SENSORS | DIVIDE_BY_100_SENSORS | GRIDBOSS_DIVIDE_BY_10_SENSORS
    ):
        try:
            return float(value)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Could not convert %s value %s to float for sensor %s",
                type(value),
                value,
                sensor_type,
            )
            return None

    # Handle string sensors - convert numbers to strings or strip existing strings
    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        return value.strip()

    # Return value as-is for other types
    return value


def safe_division(value: Any, divisor: float, sensor_type: str) -> Any:
    """Safely perform division with error handling."""
    if value is None:
        return None

    try:
        numeric_value = float(value)
        result = numeric_value / divisor
        return result
    except (ValueError, TypeError, ZeroDivisionError) as e:
        _LOGGER.warning(
            "Could not divide %s value %s by %s for sensor %s: %s",
            type(value),
            value,
            divisor,
            sensor_type,
            e,
        )
        return None


def apply_sensor_scaling(
    sensor_type: str, value: Any, device_type: str = "inverter"
) -> Any:
    """Apply appropriate scaling to sensor values based on sensor type and device type."""
    # Early return for None values
    if value is None:
        return None

    # Validate the sensor value first
    validated_value = validate_sensor_value(value, sensor_type)
    if validated_value is None:
        return None

    # Define scaling mappings
    # Note: battery_power is NOT in kw_sensors because batPower from API is already in Watts
    kw_sensors = {"ac_power", "dc_power", "load_power", "pv_total_power"}

    # Determine scaling factor based on device type and sensor type
    scaling_factor = None

    if device_type == "gridboss":
        if sensor_type in GRIDBOSS_DIVIDE_BY_10_SENSORS:
            scaling_factor = 10.0
        elif sensor_type in DIVIDE_BY_100_SENSORS:
            scaling_factor = 100.0
    else:
        # Standard inverter scaling
        if sensor_type in kw_sensors:
            scaling_factor = 1000.0
        elif sensor_type in DIVIDE_BY_10_SENSORS:
            scaling_factor = 10.0
        elif sensor_type in DIVIDE_BY_100_SENSORS:
            scaling_factor = 100.0

    # Apply scaling if needed, otherwise return validated value
    return (
        safe_division(validated_value, scaling_factor, sensor_type)
        if scaling_factor is not None
        else validated_value
    )


def should_filter_zero_sensor(sensor_type: str, value: Any) -> bool:
    """Determine if a sensor with zero value should be filtered out."""
    if not isinstance(value, (int, float)) or value != 0:
        return False

    # Never filter essential sensors
    if sensor_type in ESSENTIAL_SENSORS:
        return False

    # Filter power/energy sensors that are zero
    return sensor_type in POWER_ENERGY_SENSORS


def to_camel_case(text: str) -> str:
    """Convert text to camelCase format.

    Args:
        text: Input text with spaces or underscores

    Returns:
        Text converted to camelCase format
    """
    if not text:
        return text

    # Convert spaces and underscores to title case
    words = text.replace("_", " ").split()
    if not words:
        return text

    # First word lowercase, subsequent words title case
    result = words[0].lower()
    for word in words[1:]:
        result += word.capitalize()

    return result


def clean_battery_display_name(battery_key: str, serial: str) -> str:
    """Clean up battery key for display in entity names."""
    if not battery_key:
        return "01"

    # Handle keys like "1234567890_Battery_ID_01" -> "1234567890-01"
    if "_Battery_ID_" in battery_key:
        parts = battery_key.split("_Battery_ID_")
        if len(parts) == 2:
            device_serial = parts[0]
            battery_num = parts[1]
            return f"{device_serial}-{battery_num}"

    # Handle keys like "Battery_ID_01" -> "01"
    if battery_key.startswith("Battery_ID_"):
        battery_num = battery_key.replace("Battery_ID_", "")
        return f"{serial}-{battery_num}"

    # Handle keys like "BAT001" -> "BAT001"
    if battery_key.startswith("BAT"):
        return battery_key

    # If it already looks clean (like "01", "02"), use it with serial
    if battery_key.isdigit() and len(battery_key) <= 2:
        return f"{serial}-{battery_key.zfill(2)}"

    # Fallback: use the raw key but try to make it cleaner
    return battery_key.replace("_", "-")


def _is_valid_numeric(value: Any) -> bool:
    """Check if a value is valid numeric data."""
    if value is None or value == "" or value == "N/A":
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _process_sensor_value(api_field: str, value: Any, _sensor_type: str) -> Any:
    """Process sensor value with proper scaling based on API field."""
    if value is None or value == "" or value == "N/A":
        return None

    # Apply scaling based on API field type
    if api_field in [
        "batMaxCellVoltage",
        "batMinCellVoltage",
    ] and isinstance(value, (int, float)):
        # Cell voltage fields are scaled by 1000x (millivolts), need to divide by 1000
        value = value / 1000.0
    elif api_field in ["totalVoltage"] and isinstance(value, (int, float)):
        # Total voltage is scaled by 100x, need to divide by 100
        value = value / 100.0
    elif api_field in ["current"] and isinstance(value, (int, float)):
        # Current is scaled by 10x, need to divide by 10
        value = value / 10.0
    elif api_field in [
        "batMaxCellTemp",
        "batMinCellTemp",
        "ambientTemp",
        "mosTemp",
    ] and isinstance(value, (int, float)):
        # Temperature fields are scaled by 10x, need to divide by 10
        value = value / 10.0
    # Capacity fields are already in Ah, no scaling needed
    # elif api_field in ["currentRemainCapacity", "currentFullCapacity"] and isinstance(
    #     value, (int, float)
    # ):
    #     # Capacity fields are in mAh, convert to Ah by dividing by 1000
    #     value = value / 1000.0

    return value


def extract_individual_battery_sensors(bat_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract sensor data for individual battery with conditional creation."""
    sensors = {}

    # Core battery sensors - always create if available
    core_sensors = {
        "totalVoltage": "battery_real_voltage",
        "current": "battery_real_current",
        "soc": "state_of_charge",
        "soh": "state_of_health",
        "cycleCnt": "cycle_count",
        "fwVersionText": "battery_firmware_version",
        "currentRemainCapacity": "battery_remaining_capacity",
        "currentFullCapacity": "battery_full_capacity",
    }

    # Conditional temperature sensors - only create if data exists and is not empty
    temperature_sensors = {
        "batMaxCellTemp": "battery_cell_temp_max",
        "batMinCellTemp": "battery_cell_temp_min",
        "ambientTemp": "battery_ambient_temperature",
        "mosTemp": "battery_mos_temperature",
    }

    # Conditional voltage sensors - only create if data exists and is not empty
    voltage_sensors = {
        "batMaxCellVoltage": "battery_cell_voltage_max",
        "batMinCellVoltage": "battery_cell_voltage_min",
    }

    # Conditional cell number sensors - only create if data exists
    cell_number_sensors = {
        "batMaxCellNumTemp": "battery_max_cell_temp_num",
        "batMinCellNumTemp": "battery_min_cell_temp_num",
        "batMaxCellNumVolt": "battery_max_cell_voltage_num",
        "batMinCellNumVolt": "battery_min_cell_voltage_num",
    }

    # Process core sensors
    for api_field, sensor_type in core_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if value is not None and value != "" and value != "N/A":
                sensors[sensor_type] = _process_sensor_value(
                    api_field, value, sensor_type
                )

    # Process conditional temperature sensors - only if data exists and not empty
    for api_field, sensor_type in temperature_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if (
                value is not None
                and value != ""
                and value != "N/A"
                and _is_valid_numeric(value)
            ):
                sensors[sensor_type] = _process_sensor_value(
                    api_field, value, sensor_type
                )
                _LOGGER.debug(
                    "Created temperature sensor %s with value %s", sensor_type, value
                )

    # Process conditional voltage sensors - only if data exists and not empty
    for api_field, sensor_type in voltage_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if (
                value is not None
                and value != ""
                and value != "N/A"
                and _is_valid_numeric(value)
            ):
                sensors[sensor_type] = _process_sensor_value(
                    api_field, value, sensor_type
                )
                _LOGGER.debug(
                    "Created voltage sensor %s with value %s", sensor_type, value
                )

    # Process conditional cell number sensors - only if data exists
    for api_field, sensor_type in cell_number_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if value is not None and value != "" and value != "N/A":
                # Cell numbers are typically integers, convert if needed
                try:
                    if isinstance(value, str):
                        value = int(value)
                    sensors[sensor_type] = value
                    _LOGGER.debug(
                        "Created cell number sensor %s with value %s",
                        sensor_type,
                        value,
                    )
                except (ValueError, TypeError):
                    _LOGGER.debug(
                        "Skipping invalid cell number for %s: %s", sensor_type, value
                    )

    _LOGGER.debug(
        "Extracted %d battery sensors for battery: %s",
        len(sensors),
        list(sensors.keys()),
    )
    return sensors


async def read_device_parameters_ranges(
    inverter: "BaseInverter",
) -> List[Any]:
    """Shared function to read all parameter ranges for a device using device objects.

    Consolidates the duplicate register reading logic used in coordinator.py and number.py.

    Args:
        inverter: BaseInverter device object

    Returns:
        List of parameter read responses
    """

    # Define standard register ranges
    register_ranges = [
        (0, 127),  # Base parameters
        (127, 127),  # Extended parameters range 1
        (240, 127),  # Extended parameters range 2
    ]

    # Read all register ranges simultaneously for better performance
    tasks = []
    for start_register, point_number in register_ranges:
        # Use inverter object's read_parameters method directly!
        task = inverter.read_parameters(
            start_register=start_register,
            point_number=point_number,
        )
        tasks.append(task)

    # Execute all reads in parallel
    results: List[Any] = list(await asyncio.gather(*tasks, return_exceptions=True))
    return results


def process_parameter_responses(
    responses: List[Any], device_serial: str, _logger: logging.Logger
) -> Iterator[Tuple[int, Any, int]]:
    """Process parameter responses and handle exceptions.

    Consolidates duplicate response processing logic.
    """
    register_starts = [0, 127, 240]  # Corresponding to the ranges above
    for i, response in enumerate(responses):
        if isinstance(response, Exception):
            start_register = register_starts[i]
            _logger.debug(
                "Failed to read register range %d for %s: %s",
                start_register,
                device_serial,
                response,
            )
            continue
        yield i, response, register_starts[i]


# ========== CONSOLIDATED UTILITY FUNCTIONS ==========
# These functions eliminate code duplication across multiple platform files


def clean_model_name(model: str) -> str:
    """Clean model name for consistent entity ID generation.

    Args:
        model: Raw model name from device

    Returns:
        Cleaned model name suitable for entity IDs
    """
    if not model:
        return "unknown"
    return model.lower().replace(" ", "").replace("-", "")


def create_device_info(
    serial: str, model: str, device_type: str = "inverter"
) -> DeviceInfo:  # pylint: disable=unused-argument
    """Create standardized device info dictionary for Home Assistant entities.

    Args:
        serial: Device serial number
        model: Device model name
        device_type: Type of device (inverter, gridboss, battery, etc.)

    Returns:
        Device info dictionary for Home Assistant
    """
    # Cast to DeviceInfo type to satisfy mypy
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=f"{model} {serial}",
        manufacturer="EG4 Electronics",
        model=model,
        serial_number=serial,
        sw_version="1.0.0",  # Default version, can be updated from API
    )


def generate_entity_id(
    platform: str,
    model: str,
    serial: str,
    entity_type: str,
    suffix: Optional[str] = None,
) -> str:
    """Generate standardized entity IDs across all platforms.

    Args:
        platform: Platform name (sensor, switch, button, number)
        model: Device model name
        serial: Device serial number
        entity_type: Type of entity (e.g., "refresh_data", "ac_charge")
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized entity ID
    """
    clean_model = clean_model_name(model)
    base_id = f"{platform}.{clean_model}_{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id


def generate_unique_id(
    serial: str, entity_type: str, suffix: Optional[str] = None
) -> str:
    """Generate standardized unique IDs for entity registry.

    Args:
        serial: Device serial number
        entity_type: Type of entity
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized unique ID
    """
    base_id = f"{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id


def create_entity_name(model: str, serial: str, entity_name: str) -> str:
    """Create standardized entity display names.

    Args:
        model: Device model name
        serial: Device serial number
        entity_name: Human-readable entity name

    Returns:
        Standardized entity display name
    """
    return f"{model} {serial} {entity_name}"


def safe_get_nested_value(
    data: Dict[str, Any], keys: List[str], default: Any = None
) -> Any:
    """Safely get nested dictionary values with fallback.

    Args:
        data: Dictionary to search
        keys: List of keys for nested access
        default: Default value if key path not found

    Returns:
        Value at key path or default
    """
    try:
        current = data
        for key in keys:
            current = current[key]
        return current
    except (KeyError, TypeError, AttributeError):
        return default


def validate_device_data(
    device_data: Dict[str, Any], required_fields: List[str]
) -> bool:
    """Validate device data contains required fields.

    Args:
        device_data: Device data dictionary
        required_fields: List of required field names

    Returns:
        True if all required fields present, False otherwise
    """
    # No runtime check needed - type hint guarantees device_data is dict
    # Mypy ensures this at compile time

    for field in required_fields:
        if field not in device_data or device_data[field] is None:
            _LOGGER.warning("Missing required device field: %s", field)
            return False

    return True


class CircuitBreaker:
    """Simple circuit breaker pattern for API calls."""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Timeout in seconds before trying again
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result or raises exception
        """
        if self.state == "open":
            if self.last_failure_time and (
                asyncio.get_event_loop().time() - self.last_failure_time > self.timeout
            ):
                self.state = "half-open"
            else:
                raise RuntimeError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = asyncio.get_event_loop().time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"

            raise e
