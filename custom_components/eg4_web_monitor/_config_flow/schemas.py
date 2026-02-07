"""Schema builders for config flow forms."""

from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from ..const import (
    CONF_BASE_URL,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_SERIAL_BAUDRATE,
    CONF_SERIAL_PARITY,
    CONF_SERIAL_PORT,
    CONF_SERIAL_STOPBITS,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_SERIAL_BAUDRATE,
    DEFAULT_SERIAL_PARITY,
    DEFAULT_SERIAL_STOPBITS,
    DEFAULT_VERIFY_SSL,
)

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


def build_network_scan_schema(
    default_ip_range: str | None = None,
) -> vol.Schema:
    """Build schema for network scan configuration.

    Args:
        default_ip_range: Auto-detected from HA network adapters.

    Returns:
        Voluptuous schema for scan config step.
    """
    return vol.Schema(
        {
            vol.Required("ip_range", default=default_ip_range or "192.168.1.0/24"): str,
            vol.Optional("scan_modbus", default=True): bool,
            vol.Optional("scan_dongle", default=True): bool,
            vol.Optional("timeout", default=0.5): vol.All(
                vol.Coerce(float),
                vol.Range(min=0.3, max=5.0),
            ),
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
