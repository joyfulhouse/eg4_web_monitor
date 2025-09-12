"""Utility functions for EG4 Inverter integration."""

import logging
from typing import Dict, Any, Set

_LOGGER = logging.getLogger(__name__)

# Scaling constants - consolidated from duplicated sets across coordinator
DIVIDE_BY_10_SENSORS: Set[str] = {
    "ac_voltage", "ac_frequency", "battery_voltage", "battery_temperature",
    "temperature", "radiator_1_temperature", "radiator_2_temperature",
    "pv_voltage_1", "pv_voltage_2", "pv_voltage_3", "internal_temperature",
    # Individual battery voltage sensors from batteryArray
    "battery_real_voltage", "battery_cell_voltage_max", "battery_cell_voltage_min",
    # PV voltage sensors from runtime data
    "pv1_voltage", "pv2_voltage", "pv3_voltage", "dc_voltage"
}

DIVIDE_BY_100_SENSORS: Set[str] = {
    # Frequency sensors (convert to Hz from centihertz)
    "frequency", "generator_frequency", "phase_lock_frequency",
    # Standard inverter energy sensors (convert to kWh from Wh/100)
    "daily_energy_generation", "daily_energy_consumption", "daily_energy_charging",
    "daily_energy_discharging", "daily_energy_import", "daily_energy_export",
    "total_energy_generation", "total_energy_consumption", "charging_lifetime",
    "discharging_lifetime", "yield_lifetime", "load_lifetime", "total_energy_import", "total_energy_export"
}

# GridBOSS specific scaling sets
GRIDBOSS_DIVIDE_BY_10_SENSORS: Set[str] = {
    # Voltage sensors (convert to V from decivolts)
    "grid_voltage_l1", "grid_voltage_l2", "load_voltage_l1", "load_voltage_l2",
    "ups_voltage", "grid_voltage", "generator_voltage",
    # Current sensors (convert to A from deciamps)
    "grid_current_l1", "grid_current_l2", "load_current_l1", "load_current_l2",
    "ups_current_l1", "ups_current_l2", "generator_current_l1", "generator_current_l2",
    # GridBOSS energy sensors (convert to kWh from Wh/10)
    "ups_l1", "ups_l2", "ups_lifetime_l1", "ups_lifetime_l2",
    "grid_export_l1", "grid_export_l2", "grid_import_l1", "grid_import_l2",
    "grid_export_lifetime_l1", "grid_export_lifetime_l2", "grid_import_lifetime_l1", "grid_import_lifetime_l2",
    "load_l1", "load_l2", "load_lifetime_l1", "load_lifetime_l2",
    "ac_couple1_l1", "ac_couple1_l2", "ac_couple1_lifetime_l1", "ac_couple1_lifetime_l2",
    "ac_couple2_l1", "ac_couple2_l2", "ac_couple2_lifetime_l1", "ac_couple2_lifetime_l2",
    "ac_couple3_l1", "ac_couple3_l2", "ac_couple3_lifetime_l1", "ac_couple3_lifetime_l2",
    "ac_couple4_l1", "ac_couple4_l2", "ac_couple4_lifetime_l1", "ac_couple4_lifetime_l2",
    "smart_load1_l1", "smart_load1_l2", "smart_load1_lifetime_l1", "smart_load1_lifetime_l2",
    "smart_load2_l1", "smart_load2_l2", "smart_load2_lifetime_l1", "smart_load2_lifetime_l2",
    "smart_load3_l1", "smart_load3_l2", "smart_load3_lifetime_l1", "smart_load3_lifetime_l2",
    "smart_load4_l1", "smart_load4_l2", "smart_load4_lifetime_l1", "smart_load4_lifetime_l2",
    "energy_to_user", "ups_energy"
}

# Power and energy sensors that should be filtered when zero (except essential ones)
POWER_ENERGY_SENSORS: Set[str] = {
    # GridBOSS power sensors
    "load_power", "smart_load_power", "generator_power",
    "load_power_l1", "load_power_l2",
    "ups_power_l1", "ups_power_l2", "generator_power_l1", "generator_power_l2",
    "smart_load1_power_l1", "smart_load1_power_l2", "smart_load2_power_l1", "smart_load2_power_l2",
    "smart_load3_power_l1", "smart_load3_power_l2", "smart_load4_power_l1", "smart_load4_power_l2",
    # Runtime power sensors from inverter data that need zero filtering
    "eps_load_power", "grid_load_power", "gen_power", "hybrid_power",
} | DIVIDE_BY_100_SENSORS | GRIDBOSS_DIVIDE_BY_10_SENSORS  # Include all energy sensors for filtering

# Essential sensors that should never be filtered out even when 0
ESSENTIAL_SENSORS: Set[str] = {
    "grid_power", "grid_power_l1", "grid_power_l2",
    # Smart Port status sensors should always be shown, even when 0 (Unused)
    "smart_port1_status", "smart_port2_status", "smart_port3_status", "smart_port4_status"
}


def validate_api_response(data: Dict[str, Any], required_fields: list = None) -> bool:
    """Validate API response data structure."""
    if not isinstance(data, dict):
        _LOGGER.error("API response is not a dictionary: %s", type(data))
        return False

    if required_fields:
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            _LOGGER.warning("Missing required fields in API response: %s", missing_fields)
            return False

    return True


def validate_sensor_value(value: Any, sensor_type: str) -> Any:
    """Validate and sanitize sensor values."""
    if value is None:
        return None

    # Handle empty strings and "N/A" values
    if value == "" or value == "N/A":
        return None

    # For numeric sensors, try to convert to appropriate type
    if sensor_type in DIVIDE_BY_10_SENSORS | DIVIDE_BY_100_SENSORS | GRIDBOSS_DIVIDE_BY_10_SENSORS:
        try:
            return float(value)
        except (ValueError, TypeError):
            _LOGGER.warning("Could not convert %s value %s to float for sensor %s", type(value), value, sensor_type)
            return None

    # For string sensors, ensure it's a valid string
    if isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        return value.strip()

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
        _LOGGER.warning("Could not divide %s value %s by %s for sensor %s: %s",
                       type(value), value, divisor, sensor_type, e)
        return None


def apply_sensor_scaling(sensor_type: str, value: Any, device_type: str = "inverter") -> Any:
    """Apply appropriate scaling to sensor values based on sensor type and device type."""
    if value is None:
        return None

    # Validate the sensor value first
    validated_value = validate_sensor_value(value, sensor_type)
    if validated_value is None:
        return None

    # Power sensors that display in kW (divide by 1000 from W)
    kw_sensors = {"ac_power", "dc_power", "battery_power", "load_power", "pv_total_power"}

    # Apply device-specific scaling with safe division
    if device_type == "gridboss":
        if sensor_type in GRIDBOSS_DIVIDE_BY_10_SENSORS:
            return safe_division(validated_value, 10.0, sensor_type)
        elif sensor_type in DIVIDE_BY_100_SENSORS:
            return safe_division(validated_value, 100.0, sensor_type)
    else:
        # Standard inverter scaling
        if sensor_type in kw_sensors:
            return safe_division(validated_value, 1000.0, sensor_type)
        elif sensor_type in DIVIDE_BY_10_SENSORS:
            return safe_division(validated_value, 10.0, sensor_type)
        elif sensor_type in DIVIDE_BY_100_SENSORS:
            return safe_division(validated_value, 100.0, sensor_type)

    return validated_value


def should_filter_zero_sensor(sensor_type: str, value: Any) -> bool:
    """Determine if a sensor with zero value should be filtered out."""
    if not isinstance(value, (int, float)) or value != 0:
        return False

    # Never filter essential sensors
    if sensor_type in ESSENTIAL_SENSORS:
        return False

    # Filter power/energy sensors that are zero
    return sensor_type in POWER_ENERGY_SENSORS


def clean_battery_display_name(battery_key: str, serial: str) -> str:
    """Clean up battery key for display in entity names."""
    if not battery_key:
        return "01"

    # Handle keys like "4512670118_Battery_ID_01" -> "4512670118-01"
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


def _is_valid_numeric(value) -> bool:
    """Check if a value is valid numeric data."""
    if value is None or value == "" or value == "N/A":
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _process_sensor_value(api_field: str, value: Any, sensor_type: str) -> Any:
    """Process sensor value with proper scaling based on API field."""
    if value is None or value == "" or value == "N/A":
        return None

    # Apply scaling based on API field type
    if api_field in ["totalVoltage", "batMaxCellVoltage", "batMinCellVoltage"] and isinstance(value, (int, float)):
        # Voltage fields are scaled by 100x, need to divide by 100
        value = value / 100.0
    elif api_field in ["current"] and isinstance(value, (int, float)):
        # Current is scaled by 10x, need to divide by 10
        value = value / 10.0
    elif api_field in ["batMaxCellTemp", "batMinCellTemp", "ambientTemp", "mosTemp"] and isinstance(value, (int, float)):
        # Temperature fields are scaled by 10x, need to divide by 10
        value = value / 10.0
    # Capacity fields are already in Ah, no scaling needed
    # elif api_field in ["currentRemainCapacity", "currentFullCapacity"] and isinstance(value, (int, float)):
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
                sensors[sensor_type] = _process_sensor_value(api_field, value, sensor_type)

    # Process conditional temperature sensors - only if data exists and not empty
    for api_field, sensor_type in temperature_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if value is not None and value != "" and value != "N/A" and _is_valid_numeric(value):
                sensors[sensor_type] = _process_sensor_value(api_field, value, sensor_type)
                _LOGGER.debug("Created temperature sensor %s with value %s", sensor_type, value)

    # Process conditional voltage sensors - only if data exists and not empty
    for api_field, sensor_type in voltage_sensors.items():
        if api_field in bat_data:
            value = bat_data[api_field]
            if value is not None and value != "" and value != "N/A" and _is_valid_numeric(value):
                sensors[sensor_type] = _process_sensor_value(api_field, value, sensor_type)
                _LOGGER.debug("Created voltage sensor %s with value %s", sensor_type, value)

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
                    _LOGGER.debug("Created cell number sensor %s with value %s", sensor_type, value)
                except (ValueError, TypeError):
                    _LOGGER.debug("Skipping invalid cell number for %s: %s", sensor_type, value)

    _LOGGER.debug("Extracted %d battery sensors for battery: %s", len(sensors), list(sensors.keys()))
    return sensors


async def read_device_parameters_ranges(api_client, inverter_sn: str):
    """Shared function to read all parameter ranges for a device.
    
    Consolidates the duplicate register reading logic used in coordinator.py and number.py.
    """
    import asyncio
    
    # Define standard register ranges
    register_ranges = [
        (0, 127),      # Base parameters
        (127, 127),    # Extended parameters range 1
        (240, 127),    # Extended parameters range 2
    ]

    # Read all register ranges simultaneously for better performance
    tasks = []
    for start_register, point_number in register_ranges:
        task = api_client.read_parameters(
            inverter_sn=inverter_sn,
            start_register=start_register,
            point_number=point_number
        )
        tasks.append(task)

    # Execute all reads in parallel
    return await asyncio.gather(*tasks, return_exceptions=True)
