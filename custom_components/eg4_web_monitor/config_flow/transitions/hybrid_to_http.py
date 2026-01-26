"""Hybrid to HTTP transition builder.

This module provides the builder for transitioning from Hybrid (cloud + local)
to HTTP-only (cloud) connection type. The transition preserves cloud credentials
and removes local transport configuration.
"""

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
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_NAME,
    CONNECTION_TYPE_HTTP,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
)
from ..helpers import format_entry_title
from .base import TransitionBuilder, TransitionRequest

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


class HybridToHttpBuilder(TransitionBuilder):
    """Builder for transitioning Hybrid to HTTP-only mode.

    This transition:
    1. Preserves existing HTTP credentials (username, password, plant)
    2. Shows warning about slower polling (30s vs 5s)
    3. Removes local transport configuration
    4. Updates config entry to HTTP type
    5. Reloads the integration

    Flow steps:
    - transition_confirm_removal: Confirm removal and show warnings
    """

    # Step identifiers
    STEP_CONFIRM_REMOVAL = "transition_confirm_removal"

    def __init__(
        self,
        hass: "HomeAssistant",
        flow: "ConfigFlowProtocol",
        request: TransitionRequest,
    ) -> None:
        """Initialize the Hybrid to HTTP transition builder."""
        super().__init__(hass, flow, request)

    async def validate(self) -> bool:
        """Validate that the transition can proceed.

        Checks:
        - Entry is currently Hybrid type
        - Entry has valid cloud credentials (username, plant_id)

        Returns:
            True if transition can proceed.
        """
        entry_data = self.entry.data

        # Must be Hybrid type
        if entry_data.get(CONF_CONNECTION_TYPE) != "hybrid":
            _LOGGER.warning(
                "Cannot transition non-Hybrid entry %s to HTTP",
                self.entry.entry_id,
            )
            return False

        self._log_transition_start()

        # Add warnings about the transition
        local_type = entry_data.get(CONF_HYBRID_LOCAL_TYPE)
        if local_type == HYBRID_LOCAL_MODBUS:
            local_desc = "Modbus TCP"
        elif local_type == HYBRID_LOCAL_DONGLE:
            local_desc = "WiFi Dongle"
        else:
            local_desc = "local transport"

        self.add_warning(
            f"Removing {local_desc} will switch to cloud-only polling (30s intervals). "
            "Local transport provides faster 5-second updates."
        )
        self.add_warning(
            "You can re-add local transport later by transitioning back to Hybrid mode."
        )

        return True

    async def collect_input(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Collect user input for the transition.

        This transition only has a confirmation step.

        Args:
            step_id: The current step identifier.
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - form or completion.
        """
        self._current_step = step_id

        if step_id == self.STEP_CONFIRM_REMOVAL:
            return await self._handle_confirm_removal(user_input)

        # Default to confirmation step
        return await self._handle_confirm_removal(None)

    async def _handle_confirm_removal(
        self, user_input: dict[str, Any] | None
    ) -> "ConfigFlowResult":
        """Handle transition confirmation step.

        Shows warnings about losing local transport and allows user to confirm.

        Args:
            user_input: Form data (empty dict confirms, None shows form).

        Returns:
            Form or execute result.
        """
        if user_input is not None:
            # User confirmed - execute the transition
            return await self.execute()

        # Get current local transport info for display
        entry_data = self.entry.data
        local_type = entry_data.get(CONF_HYBRID_LOCAL_TYPE)

        if local_type == HYBRID_LOCAL_MODBUS:
            local_type_display = "Modbus TCP"
            local_host = entry_data.get(CONF_MODBUS_HOST, "Unknown")
        elif local_type == HYBRID_LOCAL_DONGLE:
            local_type_display = "WiFi Dongle"
            local_host = entry_data.get(CONF_DONGLE_HOST, "Unknown")
        else:
            local_type_display = "Unknown"
            local_host = "N/A"

        # Build warnings text
        warnings_text = "\n".join(f"• {w}" for w in self.context.warnings)

        return self.flow.async_show_form(
            step_id=self.STEP_CONFIRM_REMOVAL,
            data_schema=vol.Schema({}),  # Empty form, just confirm/cancel
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_plant": entry_data.get(CONF_PLANT_NAME, "Unknown"),
                "local_type": local_type_display,
                "local_host": local_host,
                "warnings": warnings_text or "No warnings.",
            },
        )

    async def execute(self) -> "ConfigFlowResult":
        """Execute the transition and update the config entry.

        Preserves HTTP credentials, removes local transport config,
        and changes connection type to HTTP.

        Returns:
            Abort result indicating success.
        """
        # Build updated config data by copying and filtering
        entry_data = dict(self.entry.data)

        # Update connection type
        entry_data[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_HTTP

        # Remove local transport configuration keys
        keys_to_remove = [
            CONF_HYBRID_LOCAL_TYPE,
            CONF_LOCAL_TRANSPORTS,
            # Modbus keys
            CONF_MODBUS_HOST,
            CONF_MODBUS_PORT,
            CONF_MODBUS_UNIT_ID,
            # Dongle keys
            CONF_DONGLE_HOST,
            CONF_DONGLE_PORT,
            CONF_DONGLE_SERIAL,
            # Common local keys
            CONF_INVERTER_SERIAL,
            CONF_INVERTER_FAMILY,
        ]

        for key in keys_to_remove:
            entry_data.pop(key, None)

        # Update entry title to reflect HTTP mode
        plant_name = entry_data.get(CONF_PLANT_NAME, "Unknown")
        title = format_entry_title("http", plant_name)

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
                "new_type": "Cloud API (HTTP)",
            },
        )
