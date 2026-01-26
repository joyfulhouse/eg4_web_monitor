"""Config flow package for EG4 Web Monitor integration.

This package provides a modular, mixin-based config flow architecture.
The classes are assembled here and exported for use by the integration.

Architecture:
    EG4WebMonitorConfigFlow (final class)
    ├── HttpOnboardingMixin      - Cloud API setup (async_step_http_credentials, async_step_plant)
    ├── ModbusOnboardingMixin    - Local Modbus setup (async_step_modbus)
    ├── DongleOnboardingMixin    - Local WiFi Dongle setup (async_step_dongle)
    ├── HybridOnboardingMixin    - Cloud + Local setup (async_step_hybrid_*)
    ├── LocalOnboardingMixin     - Pure local multi-device (async_step_local_*)
    ├── HttpReconfigureMixin     - Reconfigure cloud (async_step_reconfigure_http)
    ├── ModbusReconfigureMixin   - Reconfigure Modbus (async_step_reconfigure_modbus)
    ├── HybridReconfigureMixin   - Reconfigure hybrid (async_step_reconfigure_hybrid)
    ├── LocalReconfigureMixin    - Reconfigure local (async_step_reconfigure_local)
    ├── ReauthMixin              - Reauthentication (async_step_reauth*)
    ├── EG4ConfigFlowBase        - Shared state and connection testing
    └── config_entries.ConfigFlow - Home Assistant ConfigFlow base

Directory Structure:
    config_flow/
    ├── __init__.py      # This file - assembles & exports classes
    ├── base.py          # Base class + shared logic
    ├── schemas.py       # Schema builders
    ├── helpers.py       # Utility functions
    ├── options.py       # EG4OptionsFlow
    ├── onboarding/      # Onboarding mixins
    ├── reconfigure/     # Reconfigure mixins
    └── transitions/     # Transition builders
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries

from ..const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DOMAIN,
)
from .base import ConfigFlowProtocol, EG4ConfigFlowBase
from .helpers import (
    build_unique_id,
    format_entry_title,
    get_ha_timezone,
    timezone_observes_dst,
)
from .onboarding import (
    DongleOnboardingMixin,
    HttpOnboardingMixin,
    HybridOnboardingMixin,
    LocalOnboardingMixin,
    ModbusOnboardingMixin,
)
from .options import EG4OptionsFlow
from .reconfigure import (
    HttpReconfigureMixin,
    HybridReconfigureMixin,
    LocalReconfigureMixin,
    ModbusReconfigureMixin,
    ReauthMixin,
)
from .transitions import TransitionMixin
from .schemas import (
    INVERTER_FAMILY_OPTIONS,
    build_connection_type_schema,
    build_dongle_schema,
    build_http_credentials_schema,
    build_http_reconfigure_schema,
    build_hybrid_dongle_schema,
    build_hybrid_local_type_schema,
    build_hybrid_modbus_schema,
    build_interval_options_schema,
    build_modbus_schema,
    build_plant_selection_schema,
    build_reauth_schema,
)

# Re-export exceptions from pylxpweb for backward compatibility
from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import LuxpowerAuthError as InvalidAuthError
from pylxpweb.exceptions import LuxpowerConnectionError as CannotConnectError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)

# =============================================================================
# LEGACY BACKWARD COMPATIBILITY
# =============================================================================
# Re-export private helper functions for any external code that may use them


def _timezone_observes_dst(timezone_name: str | None) -> bool:
    """Legacy wrapper for timezone_observes_dst.

    This function is deprecated. Use timezone_observes_dst() from helpers module.

    Args:
        timezone_name: The timezone name to check (e.g., "America/New_York").

    Returns:
        True if the timezone observes DST, False otherwise.
    """
    return timezone_observes_dst(timezone_name)


def _build_user_data_schema() -> None:
    """Legacy placeholder - no longer used.

    The original function built a voluptuous schema. Now use build_http_credentials_schema().
    """
    raise NotImplementedError(
        "Use build_http_credentials_schema() from config_flow.schemas"
    )


# =============================================================================
# ASSEMBLED CONFIG FLOW CLASS
# =============================================================================


class EG4WebMonitorConfigFlow(
    # Onboarding mixins (provide async_step_* for initial setup)
    HttpOnboardingMixin,
    ModbusOnboardingMixin,
    DongleOnboardingMixin,
    HybridOnboardingMixin,
    LocalOnboardingMixin,
    # Reconfigure mixins (provide async_step_reconfigure_* methods)
    HttpReconfigureMixin,
    ModbusReconfigureMixin,
    HybridReconfigureMixin,
    LocalReconfigureMixin,
    ReauthMixin,
    # Transition mixin (provides async_step_transition_* methods)
    TransitionMixin,
    # Base class (provides shared state and connection testing)
    EG4ConfigFlowBase,
    # Home Assistant ConfigFlow base (must be last for proper MRO)
    config_entries.ConfigFlow,
    domain=DOMAIN,  # type: ignore[call-arg]
):
    """Handle a config flow for EG4 Web Monitor.

    This class assembles all mixins to provide a complete config flow for:
    - Initial setup (onboarding) of HTTP, Modbus, Dongle, Hybrid, and Local modes
    - Reconfiguration of existing entries
    - Reauthentication when credentials expire
    - Connection type transitions (HTTP ↔ Hybrid)

    Mixins provide the step methods, while this class provides routing.

    MRO Order Notes:
        - Onboarding mixins come first (most specific step methods)
        - Reconfigure mixins next
        - ReauthMixin provides reauth steps
        - TransitionMixin provides connection type transition steps
        - EG4ConfigFlowBase provides shared state and _test_* methods
        - ConfigFlow base must be last for proper method resolution
    """

    VERSION = 1

    @staticmethod
    @config_entries.HANDLERS.register(DOMAIN)
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EG4OptionsFlow:
        """Get the options flow for this handler."""
        return EG4OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Handle the initial step - connection type selection.

        Routes to the appropriate onboarding flow based on connection type:
        - HTTP → async_step_http_credentials (HttpOnboardingMixin)
        - Modbus → async_step_modbus (ModbusOnboardingMixin)
        - Dongle → async_step_dongle (DongleOnboardingMixin)
        - Hybrid → async_step_hybrid_http (HybridOnboardingMixin)
        - Local → async_step_local_setup (LocalOnboardingMixin)

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - form or routing to next step.
        """
        if user_input is not None:
            connection_type = user_input[CONF_CONNECTION_TYPE]
            self._connection_type = connection_type

            if connection_type == CONNECTION_TYPE_HTTP:
                return await self.async_step_http_credentials()
            if connection_type == CONNECTION_TYPE_MODBUS:
                return await self.async_step_modbus()
            if connection_type == CONNECTION_TYPE_DONGLE:
                return await self.async_step_dongle()
            if connection_type == CONNECTION_TYPE_LOCAL:
                return await self.async_step_local_setup()
            # CONNECTION_TYPE_HYBRID - start with HTTP credentials
            return await self.async_step_hybrid_http()

        # Show connection type selection form
        return self.async_show_form(
            step_id="user",
            data_schema=build_connection_type_schema(),
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Handle reconfiguration entry point.

        Routes to the appropriate reconfigure flow based on the existing entry's
        connection type:
        - HTTP → async_step_reconfigure_http (HttpReconfigureMixin)
        - Modbus → async_step_reconfigure_modbus (ModbusReconfigureMixin)
        - Hybrid → async_step_reconfigure_hybrid (HybridReconfigureMixin)
        - Local → async_step_reconfigure_local (LocalReconfigureMixin)

        Note: Dongle mode reconfiguration uses the same flow as Modbus.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - routing to appropriate reconfigure step.
        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

        if connection_type == CONNECTION_TYPE_MODBUS:
            return await self.async_step_reconfigure_modbus(user_input)
        if connection_type == CONNECTION_TYPE_DONGLE:
            # Dongle reconfigure is similar to Modbus
            return await self.async_step_reconfigure_modbus(user_input)
        if connection_type == CONNECTION_TYPE_HYBRID:
            return await self.async_step_reconfigure_hybrid(user_input)
        if connection_type == CONNECTION_TYPE_LOCAL:
            return await self.async_step_reconfigure_local(user_input)

        # Default to HTTP reconfigure
        return await self.async_step_reconfigure_http(user_input)


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Main config flow classes
    "EG4WebMonitorConfigFlow",
    "EG4OptionsFlow",
    # Exception classes (for backward compatibility)
    "CannotConnectError",
    "InvalidAuthError",
    # Client (for backward compatibility)
    "LuxpowerClient",
    # Legacy helper functions (underscore prefix preserved)
    "_timezone_observes_dst",
    "_build_user_data_schema",
    # Base components
    "ConfigFlowProtocol",
    "EG4ConfigFlowBase",
    # Helper functions
    "build_unique_id",
    "format_entry_title",
    "get_ha_timezone",
    "timezone_observes_dst",
    # Schema builders
    "INVERTER_FAMILY_OPTIONS",
    "build_connection_type_schema",
    "build_dongle_schema",
    "build_http_credentials_schema",
    "build_http_reconfigure_schema",
    "build_hybrid_dongle_schema",
    "build_hybrid_local_type_schema",
    "build_hybrid_modbus_schema",
    "build_interval_options_schema",
    "build_modbus_schema",
    "build_plant_selection_schema",
    "build_reauth_schema",
]
