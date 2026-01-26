"""Modbus reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for local Modbus TCP connections, allowing
users to update host, port, unit ID, and inverter family settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
)
from ..helpers import format_entry_title, get_reconfigure_entry
from ..schemas import INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


class ModbusReconfigureMixin:
    """Mixin providing Modbus reconfiguration flow steps.

    This mixin handles reconfiguration for local Modbus TCP connections:

    1. Show Modbus settings form with current values
    2. Test new connection settings
    3. Update config entry and reload

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        _inverter_serial: str | None
        _inverter_model: str | None
        _inverter_family: str | None

        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> Any: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_abort(
            self: ConfigFlowProtocol,
            *,
            reason: str,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...

    async def async_step_reconfigure_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus reconfiguration flow.

        Gold tier requirement: Reconfiguration available through UI.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to update Modbus settings, or abort on completion.
        """
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection
            try:
                await self._test_modbus_connection()
                return await self._update_modbus_entry(entry)

            except ImportError:
                errors["base"] = "modbus_not_installed"
            except TimeoutError:
                errors["base"] = "modbus_timeout"
            except OSError as e:
                _LOGGER.error("Modbus connection error: %s", e)
                errors["base"] = "modbus_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected Modbus error: %s", e)
                errors["base"] = "unknown"

        # Build Modbus reconfiguration schema with current values
        modbus_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST, default=entry.data.get(CONF_MODBUS_HOST, "")
                ): str,
                vol.Optional(
                    CONF_MODBUS_PORT,
                    default=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                ): int,
                vol.Optional(
                    CONF_MODBUS_UNIT_ID,
                    default=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                ): int,
                vol.Required(
                    CONF_INVERTER_SERIAL,
                    default=entry.data.get(CONF_INVERTER_SERIAL, ""),
                ): str,
                vol.Optional(
                    CONF_INVERTER_MODEL,
                    default=entry.data.get(CONF_INVERTER_MODEL, ""),
                ): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY,
                    default=entry.data.get(
                        CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
                    ),
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_host": entry.data.get(CONF_MODBUS_HOST, "Unknown"),
            },
        )

    async def _update_modbus_entry(
        self: ConfigFlowProtocol, entry: config_entries.ConfigEntry[Any]
    ) -> ConfigFlowResult:
        """Update the Modbus config entry with new data.

        Args:
            entry: The config entry to update.

        Returns:
            Abort result indicating success or conflict.
        """
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        assert self._inverter_serial is not None

        # Use inverter serial as unique ID
        unique_id = f"modbus_{self._inverter_serial}"

        # Check for conflicts
        existing_entry = await self.async_set_unique_id(unique_id)
        if existing_entry and existing_entry.entry_id != entry.entry_id:
            _LOGGER.warning(
                "Cannot reconfigure to serial %s - already configured",
                self._inverter_serial,
            )
            return self.async_abort(reason="already_configured")

        # Update title
        model_suffix = f" ({self._inverter_model})" if self._inverter_model else ""
        title = f"{format_entry_title('modbus', self._inverter_serial)}{model_suffix}"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS,
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

        self.hass.config_entries.async_update_entry(
            entry,
            title=title,
            data=data,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)

        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )
