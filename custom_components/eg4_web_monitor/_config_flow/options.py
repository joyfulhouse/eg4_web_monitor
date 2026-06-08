"""Options flow for EG4 Web Monitor integration.

This module provides the OptionsFlow class for configuring integration settings
after initial setup, such as polling intervals and refresh rates.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from ..const import (
    BRAND_NAME,
    CONF_CHARGE_CONTROL_MODE,
    CONF_CONNECTION_TYPE,
    CONF_DATA_VALIDATION,
    CONF_DISCHARGE_CONTROL_MODE,
    CONTROL_MODE_SOC,
    CONTROL_MODE_VOLTAGE,
    DEVICE_TYPE_INVERTER,
    PARAM_FUNC_BAT_CHARGE_CONTROL,
    PARAM_FUNC_BAT_DISCHARGE_CONTROL,
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
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._apply_battery_control_mode(user_input)
            except Exception as err:
                _LOGGER.warning("Failed to apply battery control mode: %s", err)
                errors["base"] = "control_mode_write_failed"

            if not errors:
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

        # Battery control mode (SOC vs Voltage) — always shown. Pre-filled from
        # the inverter's live regime so the user sees their actual setting.
        # Changing it reconfigures the inverter (see field description).
        charge_default, discharge_default = self._current_control_modes()
        schema_fields[
            vol.Required(CONF_CHARGE_CONTROL_MODE, default=charge_default)
        ] = self._control_mode_selector()
        schema_fields[
            vol.Required(CONF_DISCHARGE_CONTROL_MODE, default=discharge_default)
        ] = self._control_mode_selector()

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
            errors=errors,
        )

    # ── Battery control mode (SOC vs Voltage) helpers ───────────────────────

    @staticmethod
    def _control_mode_selector() -> SelectSelector:
        """Build the SOC/Voltage dropdown selector for a control mode field."""
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=CONTROL_MODE_SOC, label="SOC (closed-loop)"),
                    SelectOptionDict(
                        value=CONTROL_MODE_VOLTAGE, label="Voltage (open-loop)"
                    ),
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

    def _first_inverter_serial(self) -> str | None:
        """Return the first inverter serial in the station, or None."""
        coordinator = self.config_entry.runtime_data
        for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
            if device_data.get("type") == DEVICE_TYPE_INVERTER:
                return str(serial)
        return None

    def _current_control_modes(self) -> tuple[str, str]:
        """Return display defaults for the control-mode pickers.

        Prefers the inverter's live regime (reg 179) so the form reflects the
        user's actual setting — but ONLY when that register has actually been
        polled. If the live value is unknown (e.g. inverter momentarily
        unreachable), the stored option is shown instead of a misleading SOC
        default, so saving the form cannot silently overwrite the user's mode.
        """
        coordinator = self.config_entry.runtime_data
        charge = self.config_entry.options.get(
            CONF_CHARGE_CONTROL_MODE, CONTROL_MODE_SOC
        )
        discharge = self.config_entry.options.get(
            CONF_DISCHARGE_CONTROL_MODE, CONTROL_MODE_SOC
        )
        serial = self._first_inverter_serial()
        if serial is not None:
            params = (coordinator.data or {}).get("parameters", {}).get(serial, {})
            if PARAM_FUNC_BAT_CHARGE_CONTROL in params:
                charge = coordinator.get_live_control_mode(serial)
            if PARAM_FUNC_BAT_DISCHARGE_CONTROL in params:
                discharge = coordinator.get_live_control_mode(serial, discharge=True)
        return charge, discharge

    async def _apply_battery_control_mode(self, user_input: dict[str, Any]) -> None:
        """Write the chosen control mode to each inverter when it differs from live.

        Skips inverters whose live regime is unknown (reg 179 not yet polled) to
        avoid a spurious write based on a guessed default.

        Raises:
            HomeAssistantError: If a write fails (surfaced as a form error).
        """
        charge_mode = user_input.get(CONF_CHARGE_CONTROL_MODE, CONTROL_MODE_SOC)
        discharge_mode = user_input.get(CONF_DISCHARGE_CONTROL_MODE, CONTROL_MODE_SOC)
        coordinator = self.config_entry.runtime_data
        for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
            if device_data.get("type") != DEVICE_TYPE_INVERTER:
                continue
            params = (coordinator.data or {}).get("parameters", {}).get(serial, {})
            if (
                PARAM_FUNC_BAT_CHARGE_CONTROL not in params
                and PARAM_FUNC_BAT_DISCHARGE_CONTROL not in params
            ):
                # Live regime unknown — don't guess and write.
                continue
            live_charge = coordinator.get_live_control_mode(serial)
            live_discharge = coordinator.get_live_control_mode(serial, discharge=True)
            if charge_mode == live_charge and discharge_mode == live_discharge:
                continue
            await coordinator.async_write_battery_control_mode(
                serial, charge_mode, discharge_mode
            )
