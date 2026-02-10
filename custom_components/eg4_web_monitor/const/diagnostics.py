"""Diagnostic and utility constants for the EG4 Web Monitor integration.

This module contains diagnostic sensor keys, battery data parsing constants,
scaling factors, supported model identifiers, and task management constants.
"""

from __future__ import annotations

# =============================================================================
# Battery Data Parsing Constants
# =============================================================================
# These constants define the separators and formats used in battery identification

BATTERY_KEY_SEPARATOR = "_Battery_ID_"
BATTERY_KEY_PREFIX = "Battery_ID_"
BATTERY_KEY_SHORT_PREFIX = "BAT"

# =============================================================================
# Diagnostic Sensor Keys
# =============================================================================
# Centralized for consistency across platforms - these sensor keys are assigned
# EntityCategory.DIAGNOSTIC

DIAGNOSTIC_DEVICE_SENSOR_KEYS = frozenset(
    {
        "temperature",
        "cycle_count",
        "state_of_health",
        "status_code",
        "status_text",
        "internal_temperature",
        "radiator1_temperature",
        "radiator2_temperature",
        "firmware_version",
        "has_data",
        "connection_transport",
        "transport_host",
    }
)

# Diagnostic battery sensor keys - additional sensors specific to batteries
DIAGNOSTIC_BATTERY_SENSOR_KEYS = frozenset(
    {
        "temperature",
        "cycle_count",
        "state_of_health",
        "battery_firmware_version",
        "battery_max_cell_temp_num",
        "battery_min_cell_temp_num",
        "battery_max_cell_voltage_num",
        "battery_min_cell_voltage_num",
        "battery_serial_number",
        "battery_type",
        "battery_type_text",
        "battery_bms_model",
        "battery_index",
        "battery_discharge_capacity",
    }
)

# =============================================================================
# Supported Inverter Models
# =============================================================================
# Model identifiers for number/switch entities that require model-specific logic

SUPPORTED_INVERTER_MODELS = frozenset(
    {
        "flexboss",
        "18kpv",
        "18k",
        "12kpv",
        "12k",
        "xp",
        "lxp",
    }
)

# =============================================================================
# Task Management Constants
# =============================================================================

BACKGROUND_TASK_CLEANUP_TIMEOUT = 5  # Seconds to wait for background task cancellation
