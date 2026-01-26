"""Modbus TCP onboarding mixin for EG4 Web Monitor config flow."""

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
from ..helpers import build_unique_id, format_entry_title
from ..schemas import INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


def _build_modbus_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the Modbus configuration schema.

    Args:
        defaults: Optional default values for reconfiguration.

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


class ModbusOnboardingMixin:
    """Mixin providing Modbus TCP onboarding flow steps.

    This mixin handles the initial setup for local Modbus TCP connections:
    1. Collect Modbus connection details (host, port, unit ID)
    2. Optionally collect inverter details (serial, model, family)
    3. Test the connection and auto-detect serial if not provided
    4. Create the config entry

    Requires:
        - ConfigFlowProtocol attributes (_modbus_host, _modbus_port, etc.)
        - _test_modbus_connection() method from EG4ConfigFlowBase
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        _inverter_serial: str | None
        _inverter_model: str | None
        _inverter_family: str | None

        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> None: ...
        def _abort_if_unique_id_configured(self: ConfigFlowProtocol) -> None: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_create_entry(
            self: ConfigFlowProtocol,
            *,
            title: str,
            data: dict[str, Any],
        ) -> ConfigFlowResult: ...

    async def async_step_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus TCP connection configuration step.

        This is the main entry point for Modbus-only onboarding.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect Modbus settings, or entry creation on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store Modbus configuration in instance state
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            # Serial is optional - will be auto-detected if not provided
            self._inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection and auto-detect serial if not provided
            try:
                detected_serial = await self._test_modbus_connection()
                # Use detected serial if user didn't provide one
                if not self._inverter_serial and detected_serial:
                    self._inverter_serial = detected_serial
                    _LOGGER.info(
                        "Auto-detected inverter serial from Modbus: %s",
                        detected_serial,
                    )
                return await self._create_modbus_entry()

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

        return self.async_show_form(
            step_id="modbus",
            data_schema=_build_modbus_schema(),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _create_modbus_entry(self: ConfigFlowProtocol) -> ConfigFlowResult:
        """Create config entry for Modbus connection.

        Returns:
            Config entry creation result.
        """
        # Validate required state
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        # Serial should have been auto-detected if not provided by user
        assert self._inverter_serial, "Serial number must be provided or auto-detected"

        # Set unique ID and check for duplicates
        unique_id = build_unique_id("modbus", serial=self._inverter_serial)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create title with optional model suffix
        title = format_entry_title("modbus", self._inverter_serial)
        if self._inverter_model:
            title = f"{title} ({self._inverter_model})"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS,
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

        return self.async_create_entry(title=title, data=data)
