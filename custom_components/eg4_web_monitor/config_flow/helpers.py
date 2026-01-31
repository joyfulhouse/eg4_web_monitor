"""Utility functions for config flow operations."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from ..const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)

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
    """Get the Home Assistant timezone name."""
    return hass.config.time_zone


def format_entry_title(mode: str, name: str) -> str:
    """Format the config entry title."""
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

    Raises ValueError if required parameters are missing for the mode.
    """
    if mode in ("http", "hybrid"):
        if not username or not plant_id:
            raise ValueError(
                f"{'HTTP' if mode == 'http' else 'Hybrid'} mode requires username and plant_id"
            )
        prefix = "hybrid_" if mode == "hybrid" else ""
        return f"{prefix}{username}_{plant_id}"

    if mode in ("modbus", "dongle"):
        if not serial:
            raise ValueError(f"{mode.title()} mode requires serial")
        return f"{mode}_{serial}"

    if mode == "local":
        if not station_name:
            raise ValueError("Local mode requires station_name")
        normalized = station_name.lower().replace(" ", "_")
        return f"local_{normalized}"

    raise ValueError(f"Unknown mode: {mode}")


def find_serial_conflict(
    hass: HomeAssistant,
    serials: set[str],
    exclude_entry_id: str | None = None,
) -> tuple[str, str] | None:
    """Check if any serial is already configured in another config entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue

        # Check single-inverter entries (Modbus/Dongle)
        entry_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
        if entry_serial and entry_serial in serials:
            return (entry_serial, entry.title)

        # Check multi-inverter entries (Hybrid/Local with transport list)
        local_transports = entry.data.get(CONF_LOCAL_TRANSPORTS, [])
        for transport in local_transports:
            transport_serial = transport.get("serial", "")
            if transport_serial and transport_serial in serials:
                return (transport_serial, entry.title)

    return None


def find_plant_by_id(
    plants: list[dict[str, Any]] | None, plant_id: str
) -> dict[str, Any] | None:
    """Find a plant in the plants list by its ID."""
    if not plants:
        return None
    return next((p for p in plants if p.get("plantId") == plant_id), None)


def migrate_legacy_entry(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate a legacy modbus/dongle config entry to the unified local format."""
    connection_type = data.get(CONF_CONNECTION_TYPE, "")
    if connection_type not in ("modbus", "dongle"):
        return data

    migrated = dict(data)
    serial = migrated.pop(CONF_INVERTER_SERIAL, "")
    family = migrated.pop(CONF_INVERTER_FAMILY, "PV_SERIES")

    if connection_type == "modbus":
        transport: dict[str, Any] = {
            "transport_type": "modbus_tcp",
            "serial": serial,
            "family": family,
            "host": migrated.pop(CONF_MODBUS_HOST, ""),
            "port": migrated.pop(CONF_MODBUS_PORT, 502),
            "unit_id": migrated.pop(CONF_MODBUS_UNIT_ID, 1),
        }
    else:
        # dongle
        transport = {
            "transport_type": "wifi_dongle",
            "serial": serial,
            "family": family,
            "host": migrated.pop(CONF_DONGLE_HOST, ""),
            "port": migrated.pop(CONF_DONGLE_PORT, 8000),
            "dongle_serial": migrated.pop(CONF_DONGLE_SERIAL, ""),
        }

    migrated[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_LOCAL
    migrated[CONF_LOCAL_TRANSPORTS] = [transport]

    _LOGGER.info(
        "Migrated legacy %s entry (serial=%s) to unified local format",
        connection_type,
        serial,
    )
    return migrated
