"""Transition mixin for connection type switching.

This module provides the TransitionMixin class that integrates transition
builders into the config flow, allowing users to switch between connection
types (e.g., HTTP → Hybrid, Hybrid → HTTP) from the reconfigure flow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
)
from .base import TransitionRequest
from .http_to_hybrid import HttpToHybridBuilder
from .hybrid_to_http import HybridToHttpBuilder

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


# Transition type options for user selection
TRANSITION_OPTIONS_HTTP = {
    "upgrade_to_hybrid": "Add Local Transport (Hybrid Mode)",
    "no_change": "Keep Current Configuration",
}

TRANSITION_OPTIONS_HYBRID = {
    "downgrade_to_http": "Remove Local Transport (Cloud Only)",
    "no_change": "Keep Current Configuration",
}


class TransitionMixin:
    """Mixin providing connection type transition flow steps.

    This mixin integrates with reconfigure flows to offer users the ability
    to switch between connection types:

    - HTTP → Hybrid: Add local transport (Modbus or Dongle) to cloud connection
    - Hybrid → HTTP: Remove local transport, keeping cloud credentials

    Flow Steps:
    - async_step_transition_select: Choose transition type
    - async_step_transition_http_to_hybrid: Delegate to HttpToHybridBuilder
    - async_step_transition_hybrid_to_http: Delegate to HybridToHttpBuilder

    Usage:
        Add this mixin to the ConfigFlow class and call async_step_transition_select()
        from the appropriate reconfigure step when user requests a mode change.
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]

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

    # Store active transition builder
    _transition_builder: HttpToHybridBuilder | HybridToHttpBuilder | None = None

    async def async_step_transition_select(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle transition type selection.

        Presents options based on the current connection type:
        - HTTP: Can upgrade to Hybrid
        - Hybrid: Can downgrade to HTTP

        Args:
            user_input: Form data with transition selection.

        Returns:
            Form for selection, next step, or abort.
        """
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="entry_not_found")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.async_abort(reason="entry_not_found")

        current_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

        if user_input is not None:
            transition_choice = user_input.get("transition_type")

            if transition_choice == "no_change":
                # User wants to keep current config - return to reconfigure
                if current_type == CONNECTION_TYPE_HTTP:
                    return await self.async_step_reconfigure_http()
                if current_type == CONNECTION_TYPE_HYBRID:
                    return await self.async_step_reconfigure_hybrid()
                return self.async_abort(reason="unknown_connection_type")

            if transition_choice == "upgrade_to_hybrid":
                return await self.async_step_transition_http_to_hybrid()

            if transition_choice == "downgrade_to_http":
                return await self.async_step_transition_hybrid_to_http()

        # Build options based on current connection type
        if current_type == CONNECTION_TYPE_HTTP:
            options = TRANSITION_OPTIONS_HTTP
        elif current_type == CONNECTION_TYPE_HYBRID:
            options = TRANSITION_OPTIONS_HYBRID
        else:
            return self.async_abort(reason="transition_not_supported")

        schema = vol.Schema(
            {
                vol.Required("transition_type", default="no_change"): vol.In(options),
            }
        )

        return self.async_show_form(
            step_id="transition_select",
            data_schema=schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_type": "Cloud API (HTTP)"
                if current_type == CONNECTION_TYPE_HTTP
                else "Hybrid (Cloud + Local)",
            },
        )

    async def async_step_transition_http_to_hybrid(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP to Hybrid transition.

        Creates and delegates to HttpToHybridBuilder for the multi-step
        transition flow.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="entry_not_found")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.async_abort(reason="entry_not_found")

        # Create or reuse builder
        if self._transition_builder is None or not isinstance(
            self._transition_builder, HttpToHybridBuilder
        ):
            request = TransitionRequest(
                source_type=CONNECTION_TYPE_HTTP,
                target_type=CONNECTION_TYPE_HYBRID,
                entry=entry,
            )
            self._transition_builder = HttpToHybridBuilder(self.hass, self, request)

            # Validate transition can proceed
            if not await self._transition_builder.validate():
                self._transition_builder = None
                return self.async_abort(reason="transition_validation_failed")

        # Determine which step to show based on builder state
        builder = self._transition_builder
        current_step = (
            builder._current_step or HttpToHybridBuilder.STEP_SELECT_LOCAL_TYPE
        )

        # Delegate to builder's collect_input
        return await builder.collect_input(current_step, user_input)

    async def async_step_transition_select_local_type(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle local transport type selection for HTTP→Hybrid transition.

        This is a pass-through step that delegates to the builder.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        if self._transition_builder is None:
            return await self.async_step_transition_http_to_hybrid(user_input)

        return await self._transition_builder.collect_input(
            HttpToHybridBuilder.STEP_SELECT_LOCAL_TYPE, user_input
        )

    async def async_step_transition_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus configuration for HTTP→Hybrid transition.

        This is a pass-through step that delegates to the builder.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        if self._transition_builder is None:
            return await self.async_step_transition_http_to_hybrid(user_input)

        return await self._transition_builder.collect_input(
            HttpToHybridBuilder.STEP_MODBUS, user_input
        )

    async def async_step_transition_dongle(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Dongle configuration for HTTP→Hybrid transition.

        This is a pass-through step that delegates to the builder.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        if self._transition_builder is None:
            return await self.async_step_transition_http_to_hybrid(user_input)

        return await self._transition_builder.collect_input(
            HttpToHybridBuilder.STEP_DONGLE, user_input
        )

    async def async_step_transition_confirm(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle transition confirmation step.

        This is a pass-through step that delegates to the builder.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        if self._transition_builder is None:
            return self.async_abort(reason="transition_not_started")

        if isinstance(self._transition_builder, HttpToHybridBuilder):
            return await self._transition_builder.collect_input(
                HttpToHybridBuilder.STEP_CONFIRM, user_input
            )
        if isinstance(self._transition_builder, HybridToHttpBuilder):
            return await self._transition_builder.collect_input(
                HybridToHttpBuilder.STEP_CONFIRM_REMOVAL, user_input
            )

        return self.async_abort(reason="unknown_transition")

    async def async_step_transition_hybrid_to_http(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Hybrid to HTTP transition.

        Creates and delegates to HybridToHttpBuilder for the transition flow.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="entry_not_found")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.async_abort(reason="entry_not_found")

        # Create or reuse builder
        if self._transition_builder is None or not isinstance(
            self._transition_builder, HybridToHttpBuilder
        ):
            request = TransitionRequest(
                source_type=CONNECTION_TYPE_HYBRID,
                target_type=CONNECTION_TYPE_HTTP,
                entry=entry,
            )
            self._transition_builder = HybridToHttpBuilder(self.hass, self, request)

            # Validate transition can proceed
            if not await self._transition_builder.validate():
                self._transition_builder = None
                return self.async_abort(reason="transition_validation_failed")

        # Delegate to builder's collect_input
        return await self._transition_builder.collect_input(
            HybridToHttpBuilder.STEP_CONFIRM_REMOVAL, user_input
        )

    async def async_step_transition_confirm_removal(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle removal confirmation for Hybrid→HTTP transition.

        This is a pass-through step that delegates to the builder.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult from the builder.
        """
        if self._transition_builder is None:
            return await self.async_step_transition_hybrid_to_http(user_input)

        return await self._transition_builder.collect_input(
            HybridToHttpBuilder.STEP_CONFIRM_REMOVAL, user_input
        )
