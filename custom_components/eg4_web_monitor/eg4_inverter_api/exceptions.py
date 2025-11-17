"""Exceptions for EG4 Inverter API."""


class EG4APIError(Exception):
    """Base exception for EG4 API errors."""


class EG4AuthError(EG4APIError):
    """Authentication related errors."""


class EG4ConnectionError(EG4APIError):
    """Connection related errors."""


class EG4DeviceError(EG4APIError):
    """Device operation errors."""
