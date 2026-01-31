"""Config flow for EG4 Web Monitor integration.

This thin wrapper re-exports from the _config_flow package to satisfy
Home Assistant's hassfest requirement that config_flow.py exists as a file.
The actual implementation lives in _config_flow/ for better code organization.
"""

from custom_components.eg4_web_monitor._config_flow import (  # noqa: F401
    EG4ConfigFlow,
    EG4OptionsFlow,
)

__all__ = ["EG4ConfigFlow", "EG4OptionsFlow"]
