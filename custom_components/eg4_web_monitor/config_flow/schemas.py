"""Schema builders for config flow forms."""

from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from ..const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_PLANT_ID,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONF_SERIAL_BAUDRATE,
    CONF_SERIAL_PARITY,
    CONF_SERIAL_PORT,
    CONF_SERIAL_STOPBITS,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_SERIAL_BAUDRATE,
    DEFAULT_SERIAL_PARITY,
    DEFAULT_SERIAL_STOPBITS,
    DEFAULT_VERIFY_SSL,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    MAX_PARAMETER_REFRESH_INTERVAL,
    MAX_SENSOR_UPDATE_INTERVAL,
    MIN_PARAMETER_REFRESH_INTERVAL,
    MIN_SENSOR_UPDATE_INTERVAL,
)

# Connection type options
# Note: Modbus and Dongle single-device modes are deprecated.
# Users should use LOCAL mode which supports 1-N devices with auto-detection.
CONNECTION_TYPE_OPTIONS: dict[str, str] = {
    CONNECTION_TYPE_HTTP: "Cloud API (HTTP)",
    CONNECTION_TYPE_LOCAL: "Local Only (no cloud required)",
    CONNECTION_TYPE_HYBRID: "Hybrid (Local + Cloud)",
}

# Hybrid local transport type options
HYBRID_LOCAL_TYPE_OPTIONS: dict[str, str] = {
    HYBRID_LOCAL_MODBUS: "Modbus TCP (RS485 adapter - fastest)",
    HYBRID_LOCAL_DONGLE: "WiFi Dongle (no extra hardware)",
}

# Local device type options
LOCAL_DEVICE_TYPE_OPTIONS: dict[str, str] = {
    "modbus": "Modbus TCP (RS485-to-Ethernet adapter)",
    "serial": "Modbus Serial (USB-to-RS485 adapter)",
    "dongle": "WiFi Dongle",
}

# Serial parity options
SERIAL_PARITY_OPTIONS: dict[str, str] = {
    "N": "None",
    "E": "Even",
    "O": "Odd",
}

# Serial stopbits options
SERIAL_STOPBITS_OPTIONS: dict[int, str] = {
    1: "1 bit",
    2: "2 bits",
}

# Common baudrate options for EG4 inverters
SERIAL_BAUDRATE_OPTIONS: list[int] = [9600, 19200, 38400, 57600, 115200]


def build_connection_type_schema() -> vol.Schema:
    """Build schema for connection type selection.

    Returns:
        Voluptuous schema for connection type step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_HTTP): vol.In(
                CONNECTION_TYPE_OPTIONS
            ),
        }
    )


def build_http_credentials_schema(dst_sync_default: bool = True) -> vol.Schema:
    """Build the HTTP credentials schema with dynamic DST sync default.

    Args:
        dst_sync_default: Default value for DST sync checkbox.

    Returns:
        Voluptuous schema for HTTP credentials step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
            vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            vol.Optional(CONF_DST_SYNC, default=dst_sync_default): bool,
            vol.Optional(CONF_LIBRARY_DEBUG, default=False): bool,
        }
    )


def build_modbus_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build schema for Modbus TCP configuration.

    Args:
        defaults: Optional dict of default values for reconfiguration.

    Returns:
        Voluptuous schema for Modbus step.
    """
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_MODBUS_HOST, default=defaults.get(CONF_MODBUS_HOST, "")
            ): str,
            vol.Optional(
                CONF_MODBUS_PORT,
                default=defaults.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
            ): int,
            vol.Optional(
                CONF_MODBUS_UNIT_ID,
                default=defaults.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
            ): int,
        }
    )


def build_dongle_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build schema for WiFi Dongle TCP configuration.

    Args:
        defaults: Optional dict of default values for reconfiguration.

    Returns:
        Voluptuous schema for dongle step.
    """
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_DONGLE_HOST, default=defaults.get(CONF_DONGLE_HOST, "")
            ): str,
            vol.Optional(
                CONF_DONGLE_PORT,
                default=defaults.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
            ): int,
            vol.Required(
                CONF_DONGLE_SERIAL, default=defaults.get(CONF_DONGLE_SERIAL, "")
            ): str,
            vol.Required(
                CONF_INVERTER_SERIAL, default=defaults.get(CONF_INVERTER_SERIAL, "")
            ): str,
        }
    )


def build_serial_schema(
    port_options: dict[str, str] | None = None,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build schema for Modbus Serial (RS485) configuration.

    Args:
        port_options: Dict of {device_path: description} from list_serial_ports().
            If None, shows text input only.
        defaults: Optional dict of default values for reconfiguration.

    Returns:
        Voluptuous schema for serial Modbus step.
    """
    defaults = defaults or {}

    # Build the schema fields
    schema_fields: dict[Any, Any] = {}

    # Port selector - dropdown if ports detected, text input otherwise
    if port_options:
        schema_fields[
            vol.Required(CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT, ""))
        ] = vol.In(port_options)
    else:
        schema_fields[
            vol.Required(CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT, ""))
        ] = str

    # Baudrate selector
    schema_fields[
        vol.Optional(
            CONF_SERIAL_BAUDRATE,
            default=defaults.get(CONF_SERIAL_BAUDRATE, DEFAULT_SERIAL_BAUDRATE),
        )
    ] = vol.In(SERIAL_BAUDRATE_OPTIONS)

    # Parity selector
    schema_fields[
        vol.Optional(
            CONF_SERIAL_PARITY,
            default=defaults.get(CONF_SERIAL_PARITY, DEFAULT_SERIAL_PARITY),
        )
    ] = vol.In(SERIAL_PARITY_OPTIONS)

    # Stopbits selector
    schema_fields[
        vol.Optional(
            CONF_SERIAL_STOPBITS,
            default=defaults.get(CONF_SERIAL_STOPBITS, DEFAULT_SERIAL_STOPBITS),
        )
    ] = vol.In(SERIAL_STOPBITS_OPTIONS)

    # Unit ID
    schema_fields[
        vol.Optional(
            CONF_MODBUS_UNIT_ID,
            default=defaults.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
        )
    ] = int

    return vol.Schema(schema_fields)


def build_serial_manual_entry_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build schema for manual serial port entry.

    Used when user selects "manual_entry" from the port dropdown.

    Args:
        defaults: Optional dict of default values.

    Returns:
        Voluptuous schema for manual serial port entry step.
    """
    defaults = defaults or {}

    return vol.Schema(
        {
            vol.Required(
                CONF_SERIAL_PORT,
                default=defaults.get(CONF_SERIAL_PORT, "/dev/ttyUSB0"),
            ): str,
        }
    )


def build_hybrid_local_type_schema() -> vol.Schema:
    """Build schema for hybrid local transport type selection.

    Returns:
        Voluptuous schema for hybrid local type step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_HYBRID_LOCAL_TYPE, default=HYBRID_LOCAL_MODBUS): vol.In(
                HYBRID_LOCAL_TYPE_OPTIONS
            ),
        }
    )


def build_hybrid_modbus_schema(
    serial_default: str = "",
) -> vol.Schema:
    """Build schema for Modbus configuration in hybrid mode.

    Args:
        serial_default: Default inverter serial (from cloud discovery).

    Returns:
        Voluptuous schema for hybrid Modbus step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_MODBUS_HOST): str,
            vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
            vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
            vol.Required(CONF_INVERTER_SERIAL, default=serial_default): str,
        }
    )


def build_hybrid_dongle_schema(
    serial_default: str = "",
) -> vol.Schema:
    """Build schema for WiFi Dongle configuration in hybrid mode.

    Args:
        serial_default: Default inverter serial (from cloud discovery).

    Returns:
        Voluptuous schema for hybrid dongle step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_DONGLE_HOST): str,
            vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
            vol.Required(CONF_DONGLE_SERIAL): str,
            vol.Required(CONF_INVERTER_SERIAL, default=serial_default): str,
        }
    )


def build_plant_selection_schema(
    plants: list[dict[str, Any]],
    current: str | None = None,
) -> vol.Schema:
    """Build schema for plant/station selection.

    Args:
        plants: List of plant dicts with plantId and name keys.
        current: Currently selected plant ID (for reconfigure).

    Returns:
        Voluptuous schema for plant selection step.
    """
    plant_options = {plant["plantId"]: plant["name"] for plant in plants}

    if current:
        return vol.Schema(
            {
                vol.Required(CONF_PLANT_ID, default=current): vol.In(plant_options),
            }
        )

    return vol.Schema(
        {
            vol.Required(CONF_PLANT_ID): vol.In(plant_options),
        }
    )


def build_reauth_schema() -> vol.Schema:
    """Build schema for reauthentication.

    Returns:
        Voluptuous schema for reauth confirmation step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_PASSWORD): str,
        }
    )


def build_http_reconfigure_schema(
    current_username: str | None = None,
    current_base_url: str = DEFAULT_BASE_URL,
    current_verify_ssl: bool = True,
    current_dst_sync: bool = True,
) -> vol.Schema:
    """Build schema for HTTP reconfiguration.

    Args:
        current_username: Current username.
        current_base_url: Current base URL.
        current_verify_ssl: Current SSL verification setting.
        current_dst_sync: Current DST sync setting.

    Returns:
        Voluptuous schema for HTTP reconfigure step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=current_username): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_BASE_URL, default=current_base_url): str,
            vol.Optional(CONF_VERIFY_SSL, default=current_verify_ssl): bool,
            vol.Optional(CONF_DST_SYNC, default=current_dst_sync): bool,
        }
    )


def build_interval_options_schema(
    current_sensor: int,
    current_param: int,
) -> vol.Schema:
    """Build schema for polling interval options.

    Args:
        current_sensor: Current sensor update interval (seconds).
        current_param: Current parameter refresh interval (minutes).

    Returns:
        Voluptuous schema for options step.
    """
    return vol.Schema(
        {
            vol.Required(
                CONF_SENSOR_UPDATE_INTERVAL,
                default=current_sensor,
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_SENSOR_UPDATE_INTERVAL,
                    max=MAX_SENSOR_UPDATE_INTERVAL,
                ),
            ),
            vol.Required(
                CONF_PARAMETER_REFRESH_INTERVAL,
                default=current_param,
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_PARAMETER_REFRESH_INTERVAL,
                    max=MAX_PARAMETER_REFRESH_INTERVAL,
                ),
            ),
        }
    )
