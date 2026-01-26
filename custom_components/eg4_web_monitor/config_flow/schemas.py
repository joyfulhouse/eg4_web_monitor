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
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_PLANT_ID,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_VERIFY_SSL,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
    MAX_PARAMETER_REFRESH_INTERVAL,
    MAX_SENSOR_UPDATE_INTERVAL,
    MIN_PARAMETER_REFRESH_INTERVAL,
    MIN_SENSOR_UPDATE_INTERVAL,
)

# Inverter family options for register map selection
INVERTER_FAMILY_OPTIONS: dict[str, str] = {
    INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
    INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
    INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
}

# Connection type options
CONNECTION_TYPE_OPTIONS: dict[str, str] = {
    CONNECTION_TYPE_HTTP: "Cloud API (HTTP)",
    CONNECTION_TYPE_MODBUS: "Local Modbus TCP (RS485 adapter)",
    CONNECTION_TYPE_DONGLE: "Local WiFi Dongle (no extra hardware)",
    CONNECTION_TYPE_HYBRID: "Hybrid (Local + Cloud)",
}

# Hybrid local transport type options
HYBRID_LOCAL_TYPE_OPTIONS: dict[str, str] = {
    HYBRID_LOCAL_MODBUS: "Modbus TCP (RS485 adapter - fastest)",
    HYBRID_LOCAL_DONGLE: "WiFi Dongle (no extra hardware)",
}


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
            vol.Optional(
                CONF_INVERTER_SERIAL,
                default=defaults.get(CONF_INVERTER_SERIAL, ""),
            ): str,
            vol.Optional(
                CONF_INVERTER_MODEL,
                default=defaults.get(CONF_INVERTER_MODEL, ""),
            ): str,
            vol.Optional(
                CONF_INVERTER_FAMILY,
                default=defaults.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY),
            ): vol.In(INVERTER_FAMILY_OPTIONS),
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
            vol.Optional(
                CONF_INVERTER_MODEL, default=defaults.get(CONF_INVERTER_MODEL, "")
            ): str,
            vol.Optional(
                CONF_INVERTER_FAMILY,
                default=defaults.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY),
            ): vol.In(INVERTER_FAMILY_OPTIONS),
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
    inverter_family_default: str = DEFAULT_INVERTER_FAMILY,
) -> vol.Schema:
    """Build schema for Modbus configuration in hybrid mode.

    Args:
        serial_default: Default inverter serial (from cloud discovery).
        inverter_family_default: Default inverter family.

    Returns:
        Voluptuous schema for hybrid Modbus step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_MODBUS_HOST): str,
            vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
            vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
            vol.Required(CONF_INVERTER_SERIAL, default=serial_default): str,
            vol.Optional(CONF_INVERTER_FAMILY, default=inverter_family_default): vol.In(
                INVERTER_FAMILY_OPTIONS
            ),
        }
    )


def build_hybrid_dongle_schema(
    serial_default: str = "",
    inverter_family_default: str = DEFAULT_INVERTER_FAMILY,
) -> vol.Schema:
    """Build schema for WiFi Dongle configuration in hybrid mode.

    Args:
        serial_default: Default inverter serial (from cloud discovery).
        inverter_family_default: Default inverter family.

    Returns:
        Voluptuous schema for hybrid dongle step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_DONGLE_HOST): str,
            vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
            vol.Required(CONF_DONGLE_SERIAL): str,
            vol.Required(CONF_INVERTER_SERIAL, default=serial_default): str,
            vol.Optional(CONF_INVERTER_FAMILY, default=inverter_family_default): vol.In(
                INVERTER_FAMILY_OPTIONS
            ),
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
