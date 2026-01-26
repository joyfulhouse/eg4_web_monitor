"""Base classes for connection type transitions.

This module provides the foundational abstractions for transitioning between
connection types (e.g., HTTP to Hybrid, Hybrid to HTTP). The builder pattern
ensures a consistent workflow: validate → collect_input → execute.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


class TransitionType(Enum):
    """Supported connection type transitions."""

    HTTP_TO_HYBRID = "http_to_hybrid"
    HYBRID_TO_HTTP = "hybrid_to_http"
    MODBUS_TO_DONGLE = "modbus_to_dongle"
    DONGLE_TO_MODBUS = "dongle_to_modbus"


@dataclass
class TransitionRequest:
    """Request to transition between connection types.

    Attributes:
        source_type: Current connection type (e.g., "http", "hybrid").
        target_type: Desired connection type.
        entry: The config entry being transitioned.
    """

    source_type: str
    target_type: str
    entry: "config_entries.ConfigEntry[Any]"

    @property
    def transition_type(self) -> TransitionType | None:
        """Get the transition type enum, if valid.

        Returns:
            TransitionType enum or None if not a supported transition.
        """
        key = f"{self.source_type}_to_{self.target_type}"
        try:
            return TransitionType(key)
        except ValueError:
            return None


@dataclass
class TransitionContext:
    """Context accumulated during the transition workflow.

    This dataclass holds validated data collected during the transition,
    such as credentials, local transport configuration, and test results.

    Attributes:
        validated_credentials: HTTP credentials (username, password, etc.)
            that have been validated against the cloud API.
        local_transport_config: Local transport configuration (Modbus or Dongle)
            if applicable to the target connection type.
        test_results: Results from connection tests (connection latency, etc.).
        warnings: List of warnings to show the user before completing.
    """

    validated_credentials: dict[str, Any] = field(default_factory=dict)
    local_transport_config: dict[str, Any] | None = None
    test_results: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class TransitionBuilder(ABC):
    """Abstract base class for connection type transition builders.

    Builders follow a three-phase workflow:
    1. validate() - Verify the transition is possible
    2. collect_input() - Show forms and collect user input
    3. execute() - Update the config entry and reload

    Subclasses implement the abstract methods for specific transitions
    (e.g., HttpToHybridBuilder, HybridToHttpBuilder).

    Requires:
        - hass: HomeAssistant instance
        - flow: The ConfigFlow instance (for showing forms and updating entries)
    """

    def __init__(
        self,
        hass: "HomeAssistant",
        flow: "ConfigFlowProtocol",
        request: TransitionRequest,
    ) -> None:
        """Initialize the transition builder.

        Args:
            hass: Home Assistant instance.
            flow: The config flow instance for showing forms.
            request: The transition request with source/target types and entry.
        """
        self.hass = hass
        self.flow = flow
        self.request = request
        self.context = TransitionContext()
        self._current_step: str | None = None

    @property
    def entry(self) -> "config_entries.ConfigEntry[Any]":
        """Get the config entry being transitioned."""
        return self.request.entry

    @abstractmethod
    async def validate(self) -> bool:
        """Validate that the transition can proceed.

        Checks preconditions like:
        - Entry is in a valid state for transition
        - Required data exists in the current entry
        - No conflicting entries exist

        Returns:
            True if transition can proceed, False otherwise.
        """
        ...

    @abstractmethod
    async def collect_input(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult":
        """Collect user input for the transition.

        This method may be called multiple times for multi-step flows.
        Each call returns either a form to show or proceeds to the next step.

        Args:
            step_id: The current step identifier.
            user_input: Form data from user, or None for initial display.

        Returns:
            ConfigFlowResult - either a form, abort, or success result.
        """
        ...

    @abstractmethod
    async def execute(self) -> "ConfigFlowResult":
        """Execute the transition and update the config entry.

        Called after all input has been collected and validated.
        Updates the config entry with the new connection type and data,
        then reloads the integration.

        Returns:
            ConfigFlowResult - abort with success reason.
        """
        ...

    def add_warning(self, warning: str) -> None:
        """Add a warning to show the user before completing.

        Args:
            warning: Warning message to display.
        """
        self.context.warnings.append(warning)

    def _log_transition_start(self) -> None:
        """Log the start of a transition."""
        _LOGGER.info(
            "Starting transition %s -> %s for entry %s",
            self.request.source_type,
            self.request.target_type,
            self.request.entry.entry_id,
        )

    def _log_transition_complete(self) -> None:
        """Log successful transition completion."""
        _LOGGER.info(
            "Transition %s -> %s completed for entry %s",
            self.request.source_type,
            self.request.target_type,
            self.request.entry.entry_id,
        )
