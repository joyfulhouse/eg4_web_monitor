"""WiFi Dongle onboarding mixin for EG4 Web Monitor config flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONNECTION_TYPE_DONGLE,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
)
from ..helpers import build_unique_id, format_entry_title
from ..schemas import INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


def _build_dongle_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the WiFi Dongle configuration schema.

    Args:
        defaults: Optional default values for reconfiguration.

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


class DongleOnboardingMixin:
    """Mixin providing WiFi Dongle onboarding flow steps.

    This mixin handles the initial setup for local WiFi Dongle connections:
    1. Collect dongle connection details (host, port, dongle serial)
    2. Collect inverter details (serial, model, family)
    3. Test the connection
    4. Create the config entry

    Requires:
        - ConfigFlowProtocol attributes (_dongle_host, _dongle_port, etc.)
        - _test_dongle_connection() method from EG4ConfigFlowBase
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        _dongle_host: str | None
        _dongle_port: int | None
        _dongle_serial: str | None
        _inverter_serial: str | None
        _inverter_model: str | None
        _inverter_family: str | None

        async def _test_dongle_connection(self: ConfigFlowProtocol) -> None: ...
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

    async def async_step_dongle(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle TCP connection configuration step.

        This is the main entry point for Dongle-only onboarding.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect dongle settings, or entry creation on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store dongle configuration in instance state
            self._dongle_host = user_input[CONF_DONGLE_HOST]
            self._dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            self._dongle_serial = user_input[CONF_DONGLE_SERIAL]
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test dongle connection
            try:
                await self._test_dongle_connection()
                return await self._create_dongle_entry()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="dongle",
            data_schema=_build_dongle_schema(),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _create_dongle_entry(self: ConfigFlowProtocol) -> ConfigFlowResult:
        """Create config entry for WiFi dongle connection.

        Returns:
            Config entry creation result.
        """
        # Validate required state
        assert self._dongle_host is not None
        assert self._dongle_port is not None
        assert self._dongle_serial is not None
        assert self._inverter_serial is not None

        # Set unique ID and check for duplicates
        unique_id = build_unique_id("dongle", serial=self._inverter_serial)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create title with optional model suffix
        title = format_entry_title("dongle", self._inverter_serial)
        if self._inverter_model:
            title = f"{title} ({self._inverter_model})"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_DONGLE,
            CONF_DONGLE_HOST: self._dongle_host,
            CONF_DONGLE_PORT: self._dongle_port,
            CONF_DONGLE_SERIAL: self._dongle_serial,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

        return self.async_create_entry(title=title, data=data)
