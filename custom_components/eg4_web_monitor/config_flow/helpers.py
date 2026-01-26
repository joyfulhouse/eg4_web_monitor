"""Utility functions for config flow operations."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from ..const import BRAND_NAME

if TYPE_CHECKING:
    from homeassistant import config_entries

_LOGGER = logging.getLogger(__name__)


def timezone_observes_dst(timezone_name: str | None) -> bool:
    """Check if a timezone observes Daylight Saving Time.

    Args:
        timezone_name: IANA timezone name (e.g., 'America/New_York', 'UTC')

    Returns:
        True if the timezone observes DST, False otherwise.
    """
    if not timezone_name:
        return False

    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        # Invalid timezone name, default to False
        _LOGGER.debug("Invalid timezone name: %s", timezone_name)
        return False

    # Check UTC offsets at two different times in the year
    # January 15 and July 15 are typically in different DST states for most zones
    current_year = datetime.now().year
    winter = datetime(current_year, 1, 15, 12, 0, 0, tzinfo=tz)
    summer = datetime(current_year, 7, 15, 12, 0, 0, tzinfo=tz)

    # If UTC offsets differ, the timezone observes DST
    return winter.utcoffset() != summer.utcoffset()


def get_ha_timezone(hass: HomeAssistant) -> str | None:
    """Get the Home Assistant timezone name.

    Args:
        hass: Home Assistant instance.

    Returns:
        The timezone name or None if not configured.
    """
    return hass.config.time_zone


def format_entry_title(mode: str, name: str) -> str:
    """Format the config entry title.

    Args:
        mode: Connection type (http, modbus, dongle, hybrid, local).
        name: Station/plant name or serial number.

    Returns:
        Formatted entry title.
    """
    # Map mode to display text
    mode_display = {
        "http": "Web Monitor",
        "modbus": "Modbus",
        "dongle": "Dongle",
        "hybrid": "Hybrid",
        "local": "Local",
    }.get(mode, mode.title())

    return f"{BRAND_NAME} {mode_display} - {name}"


def build_unique_id(
    mode: str,
    username: str | None = None,
    plant_id: str | None = None,
    serial: str | None = None,
    station_name: str | None = None,
) -> str:
    """Build a unique ID for a config entry.

    Args:
        mode: Connection type (http, hybrid, modbus, dongle, local).
        username: Username for cloud-based modes.
        plant_id: Plant ID for cloud-based modes.
        serial: Serial number for local-only modes.
        station_name: Station name for local multi-device mode.

    Returns:
        Unique ID string.

    Raises:
        ValueError: If required parameters are missing for the mode.
    """
    if mode == "http":
        if not username or not plant_id:
            raise ValueError("HTTP mode requires username and plant_id")
        return f"{username}_{plant_id}"

    if mode == "hybrid":
        if not username or not plant_id:
            raise ValueError("Hybrid mode requires username and plant_id")
        return f"hybrid_{username}_{plant_id}"

    if mode == "modbus":
        if not serial:
            raise ValueError("Modbus mode requires serial")
        return f"modbus_{serial}"

    if mode == "dongle":
        if not serial:
            raise ValueError("Dongle mode requires serial")
        return f"dongle_{serial}"

    if mode == "local":
        if not station_name:
            raise ValueError("Local mode requires station_name")
        # Normalize station name: lowercase, replace spaces with underscores
        normalized = station_name.lower().replace(" ", "_")
        return f"local_{normalized}"

    raise ValueError(f"Unknown mode: {mode}")


def get_reconfigure_entry(
    hass: HomeAssistant, context: dict[str, Any]
) -> config_entries.ConfigEntry[Any] | None:
    """Get the config entry being reconfigured from context.

    This is a common pattern used in all reconfigure flows:
    1. Get entry_id from context
    2. Lookup entry from config_entries

    Args:
        hass: Home Assistant instance.
        context: Config flow context containing entry_id.

    Returns:
        The config entry if found, None otherwise.
    """
    entry_id = context.get("entry_id")
    if not entry_id:
        return None
    return hass.config_entries.async_get_entry(entry_id)


def find_plant_by_id(
    plants: list[dict[str, Any]] | None, plant_id: str
) -> dict[str, Any] | None:
    """Find a plant in the plants list by its ID.

    Args:
        plants: List of plant dictionaries with 'plantId' keys.
        plant_id: The plant ID to search for.

    Returns:
        The plant dictionary if found, None otherwise.
    """
    if not plants:
        return None

    for plant in plants:
        if plant.get("plantId") == plant_id:
            return plant
    return None
