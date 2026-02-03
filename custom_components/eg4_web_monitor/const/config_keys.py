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

# Options flow configuration keys (configurable via UI after setup)
CONF_SENSOR_UPDATE_INTERVAL = "sensor_update_interval"
CONF_PARAMETER_REFRESH_INTERVAL = "parameter_refresh_interval"
CONF_INCLUDE_AC_COUPLE_PV = "include_ac_couple_pv"  # Add AC couple power to PV totals

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
HYBRID_LOCAL_NONE = "none"  # Cloud-only fallback (no local transport)

# =============================================================================
# Default Values
# =============================================================================

# Options flow default values
DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP = 30  # seconds for HTTP mode
DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL = 5  # seconds for Modbus/Dongle modes
DEFAULT_PARAMETER_REFRESH_INTERVAL = 60  # minutes (1 hour)
DEFAULT_INCLUDE_AC_COUPLE_PV = False  # AC couple power NOT included in PV totals by default

# Options flow limits
MIN_SENSOR_UPDATE_INTERVAL = 5  # seconds
MAX_SENSOR_UPDATE_INTERVAL = 300  # seconds (5 minutes)
MIN_PARAMETER_REFRESH_INTERVAL = 5  # minutes
MAX_PARAMETER_REFRESH_INTERVAL = 1440  # minutes (24 hours)

# Modbus default values
DEFAULT_MODBUS_PORT = 502
DEFAULT_MODBUS_UNIT_ID = 1
DEFAULT_MODBUS_TIMEOUT = 10.0  # seconds
DEFAULT_INVERTER_FAMILY = "PV_SERIES"  # Default to EG4-18KPV register map

# WiFi Dongle default values (pylxpweb 0.5.15+)
DEFAULT_DONGLE_PORT = 8000
DEFAULT_DONGLE_TIMEOUT = 10.0  # seconds

# Modbus Serial (RS485) default values
DEFAULT_SERIAL_BAUDRATE = 19200
DEFAULT_SERIAL_PARITY = "N"  # None
DEFAULT_SERIAL_STOPBITS = 1
DEFAULT_SERIAL_TIMEOUT = 10.0  # seconds

# Update intervals for local connections (faster than HTTP due to local network)
MODBUS_UPDATE_INTERVAL = 5  # seconds (vs 30 for HTTP)
DONGLE_UPDATE_INTERVAL = 5  # seconds (same as Modbus - local network)
