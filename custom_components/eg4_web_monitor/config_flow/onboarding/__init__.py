"""Onboarding mixins for EG4 Web Monitor config flow.

This package contains mixins for initial setup flows, one for each connection type:
- HttpOnboardingMixin: Cloud API (HTTP) only setup
- ModbusOnboardingMixin: Local Modbus TCP setup
- DongleOnboardingMixin: Local WiFi Dongle setup
- HybridOnboardingMixin: Cloud + Local combined setup
- LocalOnboardingMixin: Pure local multi-device setup (no cloud)
"""

from .dongle import DongleOnboardingMixin
from .http import HttpOnboardingMixin
from .hybrid import HybridOnboardingMixin
from .local import LocalOnboardingMixin
from .modbus import ModbusOnboardingMixin

__all__ = [
    "HttpOnboardingMixin",
    "ModbusOnboardingMixin",
    "DongleOnboardingMixin",
    "HybridOnboardingMixin",
    "LocalOnboardingMixin",
]
