"""Configuration key constants for the EG4 Web Monitor integration.

This module contains all configuration-related constants including:
- Configuration keys (CONF_*)
- Connection type constants
- Default values for various settings
- Options flow limits
"""

from __future__ import annotations

# =============================================================================
# Configuration Keys
# =============================================================================

# Basic configuration keys
CONF_BASE_URL = "base_url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_PLANT_ID = "plant_id"
CONF_PLANT_NAME = "plant_name"
CONF_DST_SYNC = "dst_sync"
CONF_LIBRARY_DEBUG = "library_debug"
CONF_DATA_VALIDATION = "data_validation"

# Battery control regime: whether charge/discharge limits are governed by
# State-of-Charge (closed-loop) or battery Voltage (open-loop). Backed by the
# inverter's register 179 bit 9 (charge) / bit 10 (discharge). These gate which
# limit control entities are enabled by default to reduce entity clutter.
CONF_CHARGE_CONTROL_MODE = "charge_control_mode"
CONF_DISCHARGE_CONTROL_MODE = "discharge_control_mode"

# Battery control mode values (must match pylxpweb BatteryControlMode values)
CONTROL_MODE_SOC = "soc"
CONTROL_MODE_VOLTAGE = "voltage"

# Default to SOC (closed-loop) — preserves the historical behavior where only
# the SOC limit entities were created/enabled.
DEFAULT_CONTROL_MODE = CONTROL_MODE_SOC

# Options flow configuration keys (configurable via UI after setup)
CONF_SENSOR_UPDATE_INTERVAL = "sensor_update_interval"
CONF_HTTP_POLLING_INTERVAL = "http_polling_interval"
CONF_PARAMETER_REFRESH_INTERVAL = "parameter_refresh_interval"
CONF_INCLUDE_AC_COUPLE_PV = "include_ac_couple_pv"  # Add AC couple power to PV totals

# Per-transport polling intervals (LOCAL mode with mixed transports)
CONF_MODBUS_UPDATE_INTERVAL = "modbus_update_interval"
CONF_DONGLE_UPDATE_INTERVAL = "dongle_update_interval"

# Modbus input-register read block size preset (#254). Conservative keeps the
# plain per-group reads every dongle/firmware handles; Fast coalesces adjacent
# register groups into up to 120-register reads (fewer round-trips -> faster
# polls) on hardware that supports large reads. pylxpweb latches back to the
# conservative reads automatically if a large read fails.
CONF_MODBUS_BLOCK_SIZE = "modbus_block_size"
BLOCK_SIZE_CONSERVATIVE = "conservative"
BLOCK_SIZE_FAST = "fast"
DEFAULT_MODBUS_BLOCK_SIZE = BLOCK_SIZE_CONSERVATIVE
# Preset -> max registers per coalesced read (pylxpweb max_input_block_size).
# 40 = the documented cap of the oldest dongle firmware (no coalescing);
# 120 = the field-proven fast setting (DG dongle fw 2.04-2.09, 40-multiple).
BLOCK_SIZE_PRESET_REGISTERS: dict[str, int] = {
    BLOCK_SIZE_CONSERVATIVE: 40,
    BLOCK_SIZE_FAST: 120,
}

# Connection type configuration
CONF_CONNECTION_TYPE = "connection_type"

# Hybrid mode local transport selection
CONF_HYBRID_LOCAL_TYPE = "hybrid_local_type"

# Multi-transport configuration for hybrid mode (list of transport configs)
# Each item is a dict with: serial, transport_type (modbus_tcp/wifi_dongle),
# and transport-specific fields
CONF_LOCAL_TRANSPORTS = "local_transports"

# Modbus configuration keys
CONF_MODBUS_HOST = "modbus_host"
CONF_MODBUS_PORT = "modbus_port"
CONF_MODBUS_UNIT_ID = "modbus_unit_id"
CONF_INVERTER_SERIAL = "inverter_serial"
CONF_INVERTER_MODEL = "inverter_model"
CONF_INVERTER_FAMILY = "inverter_family"  # pylxpweb 0.5.12+ for register map selection

# WiFi Dongle configuration keys (pylxpweb 0.5.15+)
CONF_DONGLE_HOST = "dongle_host"
CONF_DONGLE_PORT = "dongle_port"
CONF_DONGLE_SERIAL = "dongle_serial"

# Modbus Serial (RS485) configuration keys
CONF_SERIAL_PORT = "serial_port"
CONF_SERIAL_BAUDRATE = "serial_baudrate"
CONF_SERIAL_PARITY = "serial_parity"
CONF_SERIAL_STOPBITS = "serial_stopbits"

# Grid type configuration (per-device, stored in local_transports dict)
CONF_GRID_TYPE = "grid_type"

# Grid type values
GRID_TYPE_SPLIT_PHASE = "split_phase"
GRID_TYPE_SINGLE_PHASE = "single_phase"
GRID_TYPE_THREE_PHASE = "three_phase"

# =============================================================================
# Connection Types
# =============================================================================

CONNECTION_TYPE_HTTP = "http"
CONNECTION_TYPE_MODBUS = "modbus"
CONNECTION_TYPE_DONGLE = "dongle"  # WiFi dongle local TCP (no additional hardware)
CONNECTION_TYPE_HYBRID = "hybrid"  # Local (Modbus/Dongle) + Cloud HTTP for best of both
CONNECTION_TYPE_LOCAL = (
    "local"  # Pure local (Modbus/Dongle only) - no cloud credentials
)

# Hybrid mode local transport options (priority: modbus > dongle > cloud-only)
HYBRID_LOCAL_MODBUS = "modbus"  # RS485 via Waveshare or similar adapter
HYBRID_LOCAL_DONGLE = "dongle"  # WiFi dongle on port 8000

# =============================================================================
# Default Values
# =============================================================================

# Options flow default values
DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP = (
    90  # seconds for HTTP mode (rate limit protection)
)
DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL = 5  # seconds for Modbus/Dongle modes
DEFAULT_PARAMETER_REFRESH_INTERVAL = 60  # minutes (1 hour)
DEFAULT_INCLUDE_AC_COUPLE_PV = (
    False  # AC couple power NOT included in PV totals by default
)

# Options flow limits
MIN_SENSOR_UPDATE_INTERVAL = 5  # seconds
MAX_SENSOR_UPDATE_INTERVAL = 300  # seconds (5 minutes)
MIN_PARAMETER_REFRESH_INTERVAL = 5  # minutes
MAX_PARAMETER_REFRESH_INTERVAL = 1440  # minutes (24 hours)

# Per-transport polling defaults (LOCAL mode with mixed transports)
DEFAULT_MODBUS_UPDATE_INTERVAL = 5  # seconds (wired, low overhead)
DEFAULT_DONGLE_UPDATE_INTERVAL = 30  # seconds (WiFi dongle reads take ~8-10s)

# Per-transport polling limits
MIN_MODBUS_UPDATE_INTERVAL = 3  # seconds
MAX_MODBUS_UPDATE_INTERVAL = 300  # seconds (5 minutes)
MIN_DONGLE_UPDATE_INTERVAL = 5  # seconds (user-configurable; reads take ~7-10s)
MAX_DONGLE_UPDATE_INTERVAL = 300  # seconds (5 minutes)

# HTTP/Cloud polling interval limits (rate limit protection)
DEFAULT_HTTP_POLLING_INTERVAL = 120  # seconds
MIN_HTTP_POLLING_INTERVAL = 60  # seconds — prevent cloud over-polling
MAX_HTTP_POLLING_INTERVAL = 600  # seconds (10 minutes)

# Modbus default values
DEFAULT_MODBUS_PORT = 502
DEFAULT_MODBUS_UNIT_ID = 1
DEFAULT_MODBUS_TIMEOUT = 10.0  # seconds
DEFAULT_INVERTER_FAMILY = (
    "EG4_HYBRID"  # Default to EG4 Hybrid (18kPV, FlexBOSS) register map
)

# WiFi Dongle default values (pylxpweb 0.5.15+)
DEFAULT_DONGLE_PORT = 8000
DEFAULT_DONGLE_TIMEOUT = 10.0  # seconds

# Modbus Serial (RS485) default values
DEFAULT_SERIAL_BAUDRATE = 19200
DEFAULT_SERIAL_PARITY = "N"  # None
DEFAULT_SERIAL_STOPBITS = 1
DEFAULT_SERIAL_TIMEOUT = 10.0  # seconds
