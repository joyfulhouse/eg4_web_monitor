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
    # TODO: Re-enable when AC-coupled PV feature is implemented
    # CONF_INCLUDE_AC_COUPLE_PV,
    CONF_LIBRARY_DEBUG,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    # TODO: Re-enable when AC-coupled PV feature is implemented
    # DEFAULT_INCLUDE_AC_COUPLE_PV,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    MAX_PARAMETER_REFRESH_INTERVAL,
    MAX_SENSOR_UPDATE_INTERVAL,
    MIN_PARAMETER_REFRESH_INTERVAL,
    MIN_SENSOR_UPDATE_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


class EG4OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for EG4 Web Monitor.

    Gold tier requirement: Configurable options through UI.

    Options available:
    - Sensor update interval: How often to poll for sensor data (5-300 seconds)
    - Parameter refresh interval: How often to refresh configuration data (5-1440 minutes)

    Local connection types (Modbus, Dongle, Hybrid, Local) default to faster
    polling (5 seconds) while HTTP-only defaults to 30 seconds.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Handle the initial options step.

        Shows a form for configuring polling and refresh intervals.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - form or create_entry result.
        """
        if user_input is not None:
            _LOGGER.debug(
                "Options updated for %s: sensor=%ss, params=%sm",
                self.config_entry.entry_id,
                user_input.get(CONF_SENSOR_UPDATE_INTERVAL),
                user_input.get(CONF_PARAMETER_REFRESH_INTERVAL),
            )
            return self.async_create_entry(title="", data=user_input)

        # Determine default sensor update interval based on connection type
        connection_type = self.config_entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )
        is_local_connection = connection_type in (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        default_sensor_interval = (
            DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
            if is_local_connection
            else DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
        )

        # Get current values from options, falling back to defaults
        current_sensor_interval = self.config_entry.options.get(
            CONF_SENSOR_UPDATE_INTERVAL, default_sensor_interval
        )
        current_param_interval = self.config_entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )

        # Library debug: check options first, fall back to data for migration
        current_library_debug = self.config_entry.options.get(
            CONF_LIBRARY_DEBUG,
            self.config_entry.data.get(CONF_LIBRARY_DEBUG, False),
        )

        # TODO: Re-enable when AC-coupled PV feature is implemented
        # AC couple PV inclusion option
        # current_include_ac_couple = self.config_entry.options.get(
        #     CONF_INCLUDE_AC_COUPLE_PV,
        #     self.config_entry.data.get(
        #         CONF_INCLUDE_AC_COUPLE_PV, DEFAULT_INCLUDE_AC_COUPLE_PV
        #     ),
        # )

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SENSOR_UPDATE_INTERVAL,
                    default=current_sensor_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SENSOR_UPDATE_INTERVAL,
                        max=MAX_SENSOR_UPDATE_INTERVAL,
                    ),
                ),
                vol.Required(
                    CONF_PARAMETER_REFRESH_INTERVAL,
                    default=current_param_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_PARAMETER_REFRESH_INTERVAL,
                        max=MAX_PARAMETER_REFRESH_INTERVAL,
                    ),
                ),
                vol.Optional(
                    CONF_LIBRARY_DEBUG,
                    default=current_library_debug,
                ): bool,
                # TODO: Re-enable when AC-coupled PV feature is implemented
                # vol.Optional(
                #     CONF_INCLUDE_AC_COUPLE_PV,
                #     default=current_include_ac_couple,
                # ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "min_sensor_interval": str(MIN_SENSOR_UPDATE_INTERVAL),
                "max_sensor_interval": str(MAX_SENSOR_UPDATE_INTERVAL),
                "min_param_interval": str(MIN_PARAMETER_REFRESH_INTERVAL),
                "max_param_interval": str(MAX_PARAMETER_REFRESH_INTERVAL),
            },
        )
