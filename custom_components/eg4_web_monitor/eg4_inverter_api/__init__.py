"""EG4 Inverter API Client Library."""

from .client import EG4InverterAPI
from .exceptions import EG4APIError, EG4AuthError, EG4ConnectionError

__version__ = "1.0.0"
__all__ = ["EG4InverterAPI", "EG4APIError", "EG4AuthError", "EG4ConnectionError"]
