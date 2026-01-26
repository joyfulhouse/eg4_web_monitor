"""Transition builders for connection type switching.

This package provides builders for transitioning between connection types:
- HttpToHybridBuilder: Add local transport to HTTP-only setup
- HybridToHttpBuilder: Remove local transport from Hybrid setup
- TransitionMixin: Config flow mixin for integrating transitions

Each builder follows the builder pattern with validate(), collect_input(),
and execute() methods for a consistent transition workflow.
"""

from .base import (
    TransitionBuilder,
    TransitionContext,
    TransitionRequest,
    TransitionType,
)
from .http_to_hybrid import HttpToHybridBuilder
from .hybrid_to_http import HybridToHttpBuilder
from .mixin import TransitionMixin

__all__ = [
    "TransitionType",
    "TransitionRequest",
    "TransitionContext",
    "TransitionBuilder",
    "HttpToHybridBuilder",
    "HybridToHttpBuilder",
    "TransitionMixin",
]
