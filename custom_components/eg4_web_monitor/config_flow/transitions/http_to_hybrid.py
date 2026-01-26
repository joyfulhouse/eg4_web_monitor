"""HTTP to Hybrid transition builder.

This module provides the builder for transitioning from HTTP-only (cloud)
to Hybrid (cloud + local) connection type. The transition preserves existing
cloud credentials and adds local transport configuration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import CONF_USERNAME

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
)
from ..helpers import format_entry_title
from .base import TransitionBuilder, TransitionRequest

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)

# Inverter family options for register map selection
INVERTER_FAMILY_OPTIONS = {
    INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
    INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
    INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
}

# Local transport type options
LOCAL_TYPE_OPTIONS = {
    HYBRID_LOCAL_MODBUS: "Modbus TCP (RS485 adapter - fastest)",
    HYBRID_LOCAL_DONGLE: "WiFi Dongle (no extra hardware)",
}


class HttpToHybridBuilder(TransitionBuilder):
    """Builder for transitioning HTTP-only to Hybrid mode.

    This transition:
    1. Preserves existing HTTP credentials (username, password, plant)
    2. Shows warning about new polling behavior with local transport
    3. Collects local transport configuration (Modbus or Dongle)
    4. Updates config entry to Hybrid type
    5. Reloads the integration

    Flow steps:
    - transition_select_local_type: Choose Modbus or Dongle
    - transition_modbus: Configure Modbus TCP settings
    - transition_dongle: Configure WiFi Dongle settings
    - transition_confirm: Show warnings and confirm
    """

    # Step identifiers
    STEP_SELECT_LOCAL_TYPE = "transition_select_local_type"
    STEP_MODBUS = "transition_modbus"
    STEP_DONGLE = "transition_dongle"
    STEP_CONFIRM = "transition_confirm"

    def __init__(
        self,
        hass: "HomeAssistant",
        flow: "ConfigFlowProtocol",
        request: TransitionRequest,
    ) -> None:
        """Initialize the HTTP to Hybrid transition builder."""
        super().__init__(hass, flow, request)

        # Local transport configuration collected during flow
        self._local_type: str | None = None
        self._modbus_host: str | None = None
        self._modbus_port: int = DEFAULT_MODBUS_PORT
        self._modbus_unit_id: int = DEFAULT_MODBUS_UNIT_ID
        self._dongle_host: str | None = None
        self._dongle_port: int = DEFAULT_DONGLE_PORT
        self._dongle_serial: str | None = None
        self._inverter_serial: str | None = None
        self._inverter_family: str = DEFAULT_INVERTER_FAMILY

    async def validate(self) -> bool:
        """Validate that the transition can proceed.

        Checks:
        - Entry is currently HTTP type
        - Entry has valid cloud credentials (username, plant_id)

        Returns:
            True if transition can proceed.
        """
        entry_data = self.entry.data

        # Must be HTTP type
        if entry_data.get(CONF_CONNECTION_TYPE) != "http":
            _LOGGER.warning(
                "Cannot transition non-HTTP entry %s to Hybrid",
                self.entry.entry_id,
            )
            return False

        # Must have cloud credentials
        if not entry_data.get(CONF_USERNAME) or not entry_data.get(CONF_PLANT_ID):
            _LOGGER.warning(
                "Entry %s missing required HTTP credentials for transition",
                self.entry.entry_id,
            )
            return False

        self._log_transition_start()
        return True

    async def collect_input(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Collect user input for the transition.

        Args:
            step_id: The current step identifier.
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - form, next step, or completion.
        """
        self._current_step = step_id

        if step_id == self.STEP_SELECT_LOCAL_TYPE:
            return await self._handle_select_local_type(user_input)
        if step_id == self.STEP_MODBUS:
            return await self._handle_modbus(user_input)
        if step_id == self.STEP_DONGLE:
            return await self._handle_dongle(user_input)
        if step_id == self.STEP_CONFIRM:
            return await self._handle_confirm(user_input)

        # Default to local type selection
        return await self._handle_select_local_type(None)

    async def _handle_select_local_type(
        self, user_input: dict[str, Any] | None
    ) -> "ConfigFlowResult":
        """Handle local transport type selection step.

        Args:
            user_input: Form data with local type selection.

        Returns:
            Form or next step result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._local_type = user_input[CONF_HYBRID_LOCAL_TYPE]

            # Route to appropriate configuration step
            if self._local_type == HYBRID_LOCAL_MODBUS:
                return await self._handle_modbus(None)
            if self._local_type == HYBRID_LOCAL_DONGLE:
                return await self._handle_dongle(None)

        # Build schema for local type selection
        schema = vol.Schema(
            {
                vol.Required(CONF_HYBRID_LOCAL_TYPE): vol.In(LOCAL_TYPE_OPTIONS),
            }
        )

        return self.flow.async_show_form(
            step_id=self.STEP_SELECT_LOCAL_TYPE,
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_plant": self.entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def _handle_modbus(
        self, user_input: dict[str, Any] | None
    ) -> "ConfigFlowResult":
        """Handle Modbus TCP configuration step.

        Args:
            user_input: Form data with Modbus settings.

        Returns:
            Form or confirmation step result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store Modbus configuration
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Copy to flow for connection testing
            self.flow._modbus_host = self._modbus_host
            self.flow._modbus_port = self._modbus_port
            self.flow._modbus_unit_id = self._modbus_unit_id
            self.flow._inverter_serial = self._inverter_serial
            self.flow._inverter_family = self._inverter_family

            # Test Modbus connection
            try:
                detected_serial = await self.flow._test_modbus_connection()

                # Auto-fill serial if not provided
                if not self._inverter_serial and detected_serial:
                    self._inverter_serial = detected_serial
                    self.flow._inverter_serial = detected_serial

                # Store local transport config
                self.context.local_transport_config = {
                    "serial": self._inverter_serial or "",
                    "transport_type": "modbus_tcp",
                    "host": self._modbus_host,
                    "port": self._modbus_port,
                    "unit_id": self._modbus_unit_id,
                    "inverter_family": self._inverter_family,
                }

                # Add warning about polling behavior change
                self.add_warning(
                    "Local transport will enable 5-second polling (vs 30s for cloud-only). "
                    "This provides faster updates but increases local network traffic."
                )

                # Proceed to confirmation
                return await self._handle_confirm(None)

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

        # Build Modbus configuration schema
        schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.flow.async_show_form(
            step_id=self.STEP_MODBUS,
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _handle_dongle(
        self, user_input: dict[str, Any] | None
    ) -> "ConfigFlowResult":
        """Handle WiFi Dongle configuration step.

        Args:
            user_input: Form data with Dongle settings.

        Returns:
            Form or confirmation step result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store Dongle configuration
            self._dongle_host = user_input[CONF_DONGLE_HOST]
            self._dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            self._dongle_serial = user_input[CONF_DONGLE_SERIAL]
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Copy to flow for connection testing
            self.flow._dongle_host = self._dongle_host
            self.flow._dongle_port = self._dongle_port
            self.flow._dongle_serial = self._dongle_serial
            self.flow._inverter_serial = self._inverter_serial
            self.flow._inverter_family = self._inverter_family

            # Test Dongle connection
            try:
                await self.flow._test_dongle_connection()

                # Store local transport config
                self.context.local_transport_config = {
                    "serial": self._inverter_serial,
                    "transport_type": "wifi_dongle",
                    "host": self._dongle_host,
                    "port": self._dongle_port,
                    "dongle_serial": self._dongle_serial,
                    "inverter_family": self._inverter_family,
                }

                # Add warning about polling behavior change
                self.add_warning(
                    "Local transport will enable 5-second polling (vs 30s for cloud-only). "
                    "This provides faster updates but increases local network traffic."
                )

                # Proceed to confirmation
                return await self._handle_confirm(None)

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected Dongle error: %s", e)
                errors["base"] = "unknown"

        # Build Dongle configuration schema
        schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.flow.async_show_form(
            step_id=self.STEP_DONGLE,
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _handle_confirm(
        self, user_input: dict[str, Any] | None
    ) -> "ConfigFlowResult":
        """Handle transition confirmation step.

        Shows warnings and allows user to confirm or cancel.

        Args:
            user_input: Form data (empty dict confirms, None shows form).

        Returns:
            Form, abort (cancel), or execute result.
        """
        if user_input is not None:
            # User confirmed - execute the transition
            return await self.execute()

        # Build confirmation message with warnings
        warnings_text = "\n".join(f"• {w}" for w in self.context.warnings)
        local_type_display = LOCAL_TYPE_OPTIONS.get(self._local_type or "", "Unknown")

        return self.flow.async_show_form(
            step_id=self.STEP_CONFIRM,
            data_schema=vol.Schema({}),  # Empty form, just confirm/cancel
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_plant": self.entry.data.get(CONF_PLANT_NAME, "Unknown"),
                "local_type": local_type_display,
                "warnings": warnings_text or "No warnings.",
            },
        )

    async def execute(self) -> "ConfigFlowResult":
        """Execute the transition and update the config entry.

        Preserves HTTP credentials, adds local transport config,
        and changes connection type to Hybrid.

        Returns:
            Abort result indicating success.
        """
        # Build updated config data
        entry_data = dict(self.entry.data)

        # Update connection type
        entry_data[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_HYBRID

        # Set local transport type
        entry_data[CONF_HYBRID_LOCAL_TYPE] = self._local_type

        # Add local transport config to list
        local_transports: list[dict[str, Any]] = []
        if self.context.local_transport_config:
            local_transports.append(self.context.local_transport_config)
        entry_data[CONF_LOCAL_TRANSPORTS] = local_transports

        # Add transport-specific fields based on type
        if self._local_type == HYBRID_LOCAL_MODBUS:
            entry_data[CONF_MODBUS_HOST] = self._modbus_host
            entry_data[CONF_MODBUS_PORT] = self._modbus_port
            entry_data[CONF_MODBUS_UNIT_ID] = self._modbus_unit_id
        elif self._local_type == HYBRID_LOCAL_DONGLE:
            entry_data[CONF_DONGLE_HOST] = self._dongle_host
            entry_data[CONF_DONGLE_PORT] = self._dongle_port
            entry_data[CONF_DONGLE_SERIAL] = self._dongle_serial

        # Add common local fields
        entry_data[CONF_INVERTER_SERIAL] = self._inverter_serial or ""
        entry_data[CONF_INVERTER_FAMILY] = self._inverter_family

        # Update entry title to reflect Hybrid mode
        plant_name = entry_data.get(CONF_PLANT_NAME, "Unknown")
        title = format_entry_title("hybrid", plant_name)

        # Update the config entry
        self.hass.config_entries.async_update_entry(
            self.entry,
            title=title,
            data=entry_data,
        )

        # Reload the integration
        await self.hass.config_entries.async_reload(self.entry.entry_id)

        self._log_transition_complete()

        return self.flow.async_abort(
            reason="transition_successful",
            description_placeholders={
                "brand_name": BRAND_NAME,
                "new_type": "Hybrid (Cloud + Local)",
            },
        )
