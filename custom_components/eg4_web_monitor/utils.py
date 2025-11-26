"""Utility functions for EG4 Inverter integration."""

import logging
import time
from typing import (
    Any,
    Callable,
)

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    BATTERY_KEY_PREFIX,
    BATTERY_KEY_SEPARATOR,
    BATTERY_KEY_SHORT_PREFIX,
    DOMAIN,
    LIFETIME_SENSOR_KEYS,
)

_LOGGER = logging.getLogger(__name__)


def get_monotonic_value(
    raw_value: Any,
    last_valid_state: float | None,
    sensor_key: str,
    entity_id: str | None = None,
) -> tuple[float | None, float | None]:
    """Apply monotonic tracking for lifetime sensors.

    Lifetime/cumulative sensors should never decrease. When the API returns
    a lower value (due to temporary glitches), we preserve the last known
    valid value to prevent incorrect statistics.

    Args:
        raw_value: The raw value from the API
        last_valid_state: The last known valid state for this sensor
        sensor_key: The sensor key to check if it's a lifetime sensor
        entity_id: Optional entity ID for logging purposes

    Returns:
        A tuple of (value_to_use, updated_last_valid_state).
        - value_to_use: The value to report (may be last_valid_state if raw decreased)
        - updated_last_valid_state: The new last_valid_state to store
    """
    # Check if this is a lifetime sensor that should never decrease
    is_lifetime_sensor = sensor_key in LIFETIME_SENSOR_KEYS

    if raw_value is None:
        return None, last_valid_state

    # Try to convert to float
    try:
        numeric_value = float(raw_value)
    except (ValueError, TypeError):
        return raw_value, last_valid_state

    if not is_lifetime_sensor:
        # For non-lifetime sensors, just return the value as-is
        # Don't update last_valid_state (return None) since we don't track them
        return numeric_value, None

    # For lifetime sensors, apply monotonic protection
    if last_valid_state is not None and numeric_value < last_valid_state:
        # Value decreased - this is likely an API glitch
        # Return the last valid state to prevent statistics issues
        _LOGGER.debug(
            "Monotonic protection: %s value decreased from %s to %s, using last valid",
            entity_id or sensor_key,
            last_valid_state,
            numeric_value,
        )
        return last_valid_state, last_valid_state

    # Value is same or increased - update tracking
    return numeric_value, numeric_value


def clean_battery_display_name(battery_key: str, serial: str) -> str:
    """Clean up battery key for display in entity names.

    Args:
        battery_key: Raw battery key from API (e.g., "1234567890_Battery_ID_01")
        serial: Parent device serial number

    Returns:
        Cleaned battery display name for UI

    Examples:
        "1234567890_Battery_ID_01" -> "1234567890-01"
        "Battery_ID_01" -> "SERIAL-01"
        "BAT001" -> "BAT001"
    """
    if not battery_key:
        return "01"

    # Handle keys like "1234567890_Battery_ID_01" -> "1234567890-01"
    if BATTERY_KEY_SEPARATOR in battery_key:
        parts = battery_key.split(BATTERY_KEY_SEPARATOR)
        if len(parts) == 2:
            device_serial = parts[0]
            battery_num = parts[1]
            return f"{device_serial}-{battery_num}"

    # Handle keys like "Battery_ID_01" -> "01"
    if battery_key.startswith(BATTERY_KEY_PREFIX):
        battery_num = battery_key.replace(BATTERY_KEY_PREFIX, "")
        return f"{serial}-{battery_num}"

    # Handle keys like "BAT001" -> "BAT001"
    if battery_key.startswith(BATTERY_KEY_SHORT_PREFIX):
        return battery_key

    # If it already looks clean (like "01", "02"), use it with serial
    if battery_key.isdigit() and len(battery_key) <= 2:
        return f"{serial}-{battery_key.zfill(2)}"

    # Fallback: use the raw key but try to make it cleaner
    return battery_key.replace("_", "-")


# ========== CONSOLIDATED UTILITY FUNCTIONS ==========
# These functions eliminate code duplication across multiple platform files


def clean_model_name(model: str, use_underscores: bool = False) -> str:
    """Clean model name for consistent entity ID generation.

    Args:
        model: Raw model name from device
        use_underscores: If True, replace spaces/hyphens with underscores instead of removing them

    Returns:
        Cleaned model name suitable for entity IDs
    """
    if not model:
        return "unknown"

    cleaned = model.lower()
    if use_underscores:
        return cleaned.replace(" ", "_").replace("-", "_")
    return cleaned.replace(" ", "").replace("-", "")


def create_device_info(serial: str, model: str) -> DeviceInfo:
    """Create standardized device info dictionary for Home Assistant entities.

    Args:
        serial: Device serial number
        model: Device model name

    Returns:
        Device info dictionary for Home Assistant
    """
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=f"{model} {serial}",
        manufacturer="EG4 Electronics",
        model=model,
        serial_number=serial,
        sw_version="1.0.0",  # Default version, can be updated from API
    )


def generate_entity_id(
    platform: str,
    model: str,
    serial: str,
    entity_type: str,
    suffix: str | None = None,
) -> str:
    """Generate standardized entity IDs across all platforms.

    Args:
        platform: Platform name (sensor, switch, button, number)
        model: Device model name
        serial: Device serial number
        entity_type: Type of entity (e.g., "refresh_data", "ac_charge")
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized entity ID
    """
    clean_model = clean_model_name(model)
    base_id = f"{platform}.{clean_model}_{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id


def generate_unique_id(serial: str, entity_type: str, suffix: str | None = None) -> str:
    """Generate standardized unique IDs for entity registry.

    Args:
        serial: Device serial number
        entity_type: Type of entity
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized unique ID
    """
    base_id = f"{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id


class CircuitBreaker:
    """Simple circuit breaker pattern for API calls."""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Timeout in seconds before trying again
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = "closed"  # closed, open, half-open

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result or raises exception
        """
        if self.state == "open":
            if self.last_failure_time and (
                time.monotonic() - self.last_failure_time > self.timeout
            ):
                self.state = "half-open"
            else:
                raise RuntimeError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"

            raise e
