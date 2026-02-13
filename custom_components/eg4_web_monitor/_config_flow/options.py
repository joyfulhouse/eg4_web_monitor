"""Options flow for EG4 Web Monitor integration.

This module provides the OptionsFlow class for configuring integration settings
after initial setup, such as polling intervals and refresh rates.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries

from ..const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_DATA_VALIDATION,
    CONF_DONGLE_UPDATE_INTERVAL,
    # TODO: Re-enable when AC-coupled PV feature is implemented
    # CONF_INCLUDE_AC_COUPLE_PV,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_UPDATE_INTERVAL,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    # TODO: Re-enable when AC-coupled PV feature is implemented
    # DEFAULT_INCLUDE_AC_COUPLE_PV,
    DEFAULT_DONGLE_UPDATE_INTERVAL,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_MODBUS_UPDATE_INTERVAL,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    MAX_DONGLE_UPDATE_INTERVAL,
    MAX_HTTP_POLLING_INTERVAL,
    MAX_MODBUS_UPDATE_INTERVAL,
    MAX_PARAMETER_REFRESH_INTERVAL,
    MAX_SENSOR_UPDATE_INTERVAL,
    MIN_DONGLE_UPDATE_INTERVAL,
    MIN_HTTP_POLLING_INTERVAL,
    MIN_MODBUS_UPDATE_INTERVAL,
    MIN_PARAMETER_REFRESH_INTERVAL,
    MIN_SENSOR_UPDATE_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


class EG4OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for EG4 Web Monitor.

    Gold tier requirement: Configurable options through UI.

    Shows connection-type-aware polling interval fields:
    - HTTP-only: HTTP polling interval
    - MODBUS-only: Modbus update interval
    - DONGLE-only: Dongle update interval
    - LOCAL (mixed): Modbus and/or Dongle intervals based on configured transports
    - HYBRID: Relevant local interval(s) + HTTP polling interval
    - Always: Parameter refresh interval, Library debug
    """

    def _has_transport_type(self, transport_type: str) -> bool:
        """Check if a specific transport type exists in local_transports config."""
        transports: list[dict[str, Any]] = self.config_entry.data.get(
            CONF_LOCAL_TRANSPORTS, []
        )
        return any(c.get("transport_type") == transport_type for c in transports)

    def _current_option(
        self, key: str, default: Any, fallback_key: str | None = None
    ) -> Any:
        """Read current option value with optional fallback to a legacy key.

        Checks options[key] first, then options[fallback_key] (if given),
        then returns default.
        """
        value = self.config_entry.options.get(key)
        if value is not None:
            return value
        if fallback_key is not None:
            fallback = self.config_entry.options.get(fallback_key)
            if fallback is not None:
                return fallback
        return default

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Handle the initial options step.

        Shows a connection-type-aware form for configuring polling intervals.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - form or create_entry result.
        """
        if user_input is not None:
            _LOGGER.debug(
                "Options updated for %s: %s",
                self.config_entry.entry_id,
                user_input,
            )
            return self.async_create_entry(title="", data=user_input)

        connection_type = self.config_entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )

        # Library debug: check options first, fall back to data for migration
        current_library_debug = self.config_entry.options.get(
            CONF_LIBRARY_DEBUG,
            self.config_entry.data.get(CONF_LIBRARY_DEBUG, False),
        )

        current_param_interval = self.config_entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )

        # Build schema fields based on connection type
        schema_fields: dict[Any, Any] = {}
        placeholders: dict[str, str] = {"brand_name": BRAND_NAME}

        # Determine which polling interval fields to show based on connection type
        # and configured transports. LOCAL/HYBRID modes check local_transports list.
        has_local_transports = connection_type in (
            CONNECTION_TYPE_LOCAL,
            CONNECTION_TYPE_HYBRID,
        )
        show_http = connection_type in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID)
        show_modbus = connection_type == CONNECTION_TYPE_MODBUS or (
            has_local_transports
            and (
                self._has_transport_type("modbus_tcp")
                or self._has_transport_type("modbus_serial")
            )
        )
        show_dongle = connection_type == CONNECTION_TYPE_DONGLE or (
            has_local_transports and self._has_transport_type("wifi_dongle")
        )
        show_legacy_sensor = not show_modbus and not show_dongle and not show_http

        if show_modbus:
            current_modbus = self._current_option(
                CONF_MODBUS_UPDATE_INTERVAL,
                DEFAULT_MODBUS_UPDATE_INTERVAL,
                fallback_key=CONF_SENSOR_UPDATE_INTERVAL,
            )
            schema_fields[
                vol.Required(CONF_MODBUS_UPDATE_INTERVAL, default=current_modbus)
            ] = vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_MODBUS_UPDATE_INTERVAL, max=MAX_MODBUS_UPDATE_INTERVAL
                ),
            )
            placeholders["min_modbus_interval"] = str(MIN_MODBUS_UPDATE_INTERVAL)
            placeholders["max_modbus_interval"] = str(MAX_MODBUS_UPDATE_INTERVAL)

        if show_dongle:
            current_dongle = self._current_option(
                CONF_DONGLE_UPDATE_INTERVAL,
                DEFAULT_DONGLE_UPDATE_INTERVAL,
                fallback_key=CONF_SENSOR_UPDATE_INTERVAL,
            )
            schema_fields[
                vol.Required(CONF_DONGLE_UPDATE_INTERVAL, default=current_dongle)
            ] = vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_DONGLE_UPDATE_INTERVAL, max=MAX_DONGLE_UPDATE_INTERVAL
                ),
            )
            placeholders["min_dongle_interval"] = str(MIN_DONGLE_UPDATE_INTERVAL)
            placeholders["max_dongle_interval"] = str(MAX_DONGLE_UPDATE_INTERVAL)

        if show_http:
            current_http = self._current_option(
                CONF_HTTP_POLLING_INTERVAL,
                DEFAULT_HTTP_POLLING_INTERVAL,
            )
            schema_fields[
                vol.Required(CONF_HTTP_POLLING_INTERVAL, default=current_http)
            ] = vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_HTTP_POLLING_INTERVAL, max=MAX_HTTP_POLLING_INTERVAL),
            )
            placeholders["min_http_interval"] = str(MIN_HTTP_POLLING_INTERVAL)
            placeholders["max_http_interval"] = str(MAX_HTTP_POLLING_INTERVAL)

        if show_legacy_sensor:
            # Fallback: show generic sensor_update_interval for edge cases
            is_local = connection_type in (
                CONNECTION_TYPE_MODBUS,
                CONNECTION_TYPE_DONGLE,
                CONNECTION_TYPE_HYBRID,
                CONNECTION_TYPE_LOCAL,
            )
            default_sensor = (
                DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
                if is_local
                else DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
            )
            current_sensor = self.config_entry.options.get(
                CONF_SENSOR_UPDATE_INTERVAL, default_sensor
            )
            schema_fields[
                vol.Required(CONF_SENSOR_UPDATE_INTERVAL, default=current_sensor)
            ] = vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_SENSOR_UPDATE_INTERVAL,
                    max=MAX_SENSOR_UPDATE_INTERVAL,
                ),
            )
            placeholders["min_sensor_interval"] = str(MIN_SENSOR_UPDATE_INTERVAL)
            placeholders["max_sensor_interval"] = str(MAX_SENSOR_UPDATE_INTERVAL)

        # Always show parameter refresh and library debug
        schema_fields[
            vol.Required(
                CONF_PARAMETER_REFRESH_INTERVAL,
                default=current_param_interval,
            )
        ] = vol.All(
            vol.Coerce(int),
            vol.Range(
                min=MIN_PARAMETER_REFRESH_INTERVAL,
                max=MAX_PARAMETER_REFRESH_INTERVAL,
            ),
        )
        placeholders["min_param_interval"] = str(MIN_PARAMETER_REFRESH_INTERVAL)
        placeholders["max_param_interval"] = str(MAX_PARAMETER_REFRESH_INTERVAL)

        schema_fields[
            vol.Optional(CONF_LIBRARY_DEBUG, default=current_library_debug)
        ] = bool

        # Data validation toggle: only shown when local transports are configured
        if show_modbus or show_dongle:
            current_data_validation = self.config_entry.options.get(
                CONF_DATA_VALIDATION, False
            )
            schema_fields[
                vol.Optional(CONF_DATA_VALIDATION, default=current_data_validation)
            ] = bool

        # TODO: Re-enable when AC-coupled PV feature is implemented
        # schema_fields[
        #     vol.Optional(
        #         CONF_INCLUDE_AC_COUPLE_PV,
        #         default=current_include_ac_couple,
        #     )
        # ] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            description_placeholders=placeholders,
        )
