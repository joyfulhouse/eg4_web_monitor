"""Config flow package for EG4 Web Monitor integration.

This package provides a modular, mixin-based config flow architecture.
The classes are assembled here and exported for use by the integration.

Directory Structure:
    config_flow/
    ├── __init__.py      # This file - assembles & exports classes
    ├── base.py          # Base class + shared logic
    ├── schemas.py       # Schema builders
    ├── helpers.py       # Utility functions
    ├── options.py       # EG4OptionsFlow
    ├── onboarding/      # Onboarding mixins
    ├── reconfigure/     # Reconfigure mixins
    └── transitions/     # Transition mixins

BACKWARD COMPATIBILITY:
During the transition to mixin-based architecture, the original config flow
classes (EG4WebMonitorConfigFlow, EG4OptionsFlow) are imported from
_config_flow_legacy.py and re-exported here to maintain API compatibility.
"""

# =============================================================================
# BACKWARD COMPATIBILITY - Re-export everything from legacy module
# =============================================================================
# The legacy module contains the full working config flow implementation.
# All imports that previously targeted config_flow.py will now work through
# this package's re-exports.

# Import everything from legacy module for backward compatibility
# This ensures all existing imports continue to work
from .._config_flow_legacy import (
    # Module-level helpers (underscore prefix)
    _timezone_observes_dst,
    _build_user_data_schema,
    # Main classes
    EG4WebMonitorConfigFlow,
    EG4OptionsFlow,
    # Exception classes
    CannotConnectError,
    InvalidAuthError,
    # Re-export imports that the legacy module exposes
    LuxpowerClient,
)

# =============================================================================
# NEW MODULAR COMPONENTS
# =============================================================================
# These are the new refactored components that will eventually replace the
# legacy implementation.

# Import from helpers module (these replace module-level functions)
from .helpers import (
    build_unique_id,
    format_entry_title,
    get_ha_timezone,
    timezone_observes_dst,
)

# Import base class and protocol
from .base import ConfigFlowProtocol, EG4ConfigFlowBase

# Import schemas
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

__all__ = [
    # Legacy classes (full backward compatibility)
    "EG4WebMonitorConfigFlow",
    "EG4OptionsFlow",
    "CannotConnectError",
    "InvalidAuthError",
    "LuxpowerClient",
    # Legacy helper functions (underscore prefix preserved)
    "_timezone_observes_dst",
    "_build_user_data_schema",
    # New base components
    "ConfigFlowProtocol",
    "EG4ConfigFlowBase",
    # New helpers
    "build_unique_id",
    "format_entry_title",
    "get_ha_timezone",
    "timezone_observes_dst",
    # New schemas
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
