"""Exceptions for EG4 Inverter API."""


class EG4APIError(Exception):
    """Base exception for EG4 API errors."""

    pass


class EG4AuthError(EG4APIError):
    """Authentication related errors."""

    pass


class EG4ConnectionError(EG4APIError):
    """Connection related errors."""

    pass


class EG4DeviceError(EG4APIError):
    """Device operation errors."""

    pass
