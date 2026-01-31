"""EG4 Web Monitor integration for Home Assistant."""

import asyncio
import logging
from typing import Any, TypeAlias

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, MANUFACTURER
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Type alias for typed ConfigEntry (Python 3.11 compatible)
EG4ConfigEntry: TypeAlias = ConfigEntry[EG4DataUpdateCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

SERVICE_REFRESH_DATA = "refresh_data"

REFRESH_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)

# Config entry only - no YAML configuration supported
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the EG4 Web Monitor component."""

    async def handle_refresh_data(call: ServiceCall) -> None:
        """Handle refresh data service call with validation."""
        entry_id = call.data.get("entry_id")
        coordinators_to_refresh = []

        if entry_id:
            # Validate entry exists
            entry = hass.config_entries.async_get_entry(entry_id)
            if not entry:
                raise ServiceValidationError(
                    f"Config entry {entry_id} not found",
                    translation_domain=DOMAIN,
                    translation_key="entry_not_found",
                )

            # Validate entry is loaded
            if entry.state != ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    f"Config entry {entry_id} is not loaded",
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                )

            # Get coordinator from runtime_data
            coordinator = entry.runtime_data
            coordinators_to_refresh.append(coordinator)
        else:
            # Refresh all loaded coordinators
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                if config_entry.state == ConfigEntryState.LOADED:
                    coordinators_to_refresh.append(config_entry.runtime_data)

        if not coordinators_to_refresh:
            raise ServiceValidationError(
                "No EG4 coordinators found to refresh",
                translation_domain=DOMAIN,
                translation_key="no_coordinators",
            )

        # Refresh all coordinators
        for coordinator in coordinators_to_refresh:
            _LOGGER.info(
                "Refreshing EG4 data for coordinator %s", coordinator.entry.entry_id
            )
            await coordinator.async_request_refresh()

        _LOGGER.info(
            "Refresh completed for %d coordinator(s)", len(coordinators_to_refresh)
        )

    # Register service in async_setup to remain available for validation
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DATA,
        handle_refresh_data,
        schema=REFRESH_DATA_SCHEMA,
    )

    return True


async def _async_update_device_registry(
    hass: HomeAssistant, coordinator: EG4DataUpdateCoordinator
) -> None:
    """Update device registry with current firmware versions.

    This function ensures device sw_version field is updated with current firmware.
    Home Assistant's device registry doesn't auto-update from entity device_info,
    so we must explicitly update devices after data refresh.
    """
    if not coordinator.data or "devices" not in coordinator.data:
        return

    device_registry = dr.async_get(hass)

    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type")

        # Only update firmware for inverter and GridBOSS devices
        if device_type not in ["inverter", "gridboss"]:
            continue

        # Get firmware version from device data
        firmware_version = device_data.get("firmware_version")
        if not firmware_version:
            continue

        # Get device info for this device
        device_info_dict = coordinator.get_device_info(serial)
        if not device_info_dict:
            continue

        # Use async_get_or_create to ensure sw_version is set correctly
        # This handles cases where device registry wasn't updated properly
        model = device_data.get("model", "Unknown")
        device_name = f"{model} {serial}"

        device_registry.async_get_or_create(
            config_entry_id=coordinator.entry.entry_id,
            identifiers={(DOMAIN, serial)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=model,
            serial_number=serial,
            sw_version=firmware_version,
        )


async def async_setup_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Set up EG4 Web Monitor from a config entry."""
    _LOGGER.debug("Setting up EG4 Web Monitor entry: %s", entry.entry_id)

    # Configure library debug logging based on user preference
    library_debug = entry.data.get("library_debug", False)
    pylxpweb_logger = logging.getLogger("pylxpweb")

    if library_debug:
        pylxpweb_logger.setLevel(logging.DEBUG)
        _LOGGER.info("Enabled DEBUG logging for pylxpweb library")
    else:
        # Set to WARNING to suppress INFO logs from library
        pylxpweb_logger.setLevel(logging.WARNING)

    # Initialize the coordinator
    coordinator = EG4DataUpdateCoordinator(hass, entry)

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime_data
    entry.runtime_data = coordinator

    # One-time migration: remove stale local-format battery entities
    # Old local keys used numeric-only battery indices (e.g., "0", "1")
    # New format uses "{serial}-{nn}" to match HTTP key format
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    for entity in entities:
        if entity.domain != "sensor":
            continue
        parts = entity.unique_id.split("_")
        # Match pattern: {serial}_{short_numeric_index}_{sensor_key}
        # where serial is a long numeric string (10+ digits) and index is 1-2 digits
        if (
            len(parts) >= 3
            and parts[0].isdigit()
            and len(parts[0]) >= 10
            and parts[1].isdigit()
            and len(parts[1]) <= 2
        ):
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed stale local-format battery entity: %s", entity.entity_id
            )

    # Forward entry setup to platforms (creates devices and entities)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except asyncio.CancelledError:
        _LOGGER.warning(
            "Platform setup for %s was cancelled; will retry on next reload",
            entry.title,
        )
        raise

    # Update device registry with current firmware versions AFTER devices are created
    await _async_update_device_registry(hass, coordinator)

    # Register options update listener - reload when options change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Handle options update - reload the integration to apply new settings."""
    _LOGGER.info("Options updated for %s, reloading integration", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading EG4 Web Monitor entry: %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = entry.runtime_data

        # Clean up coordinator background tasks
        await coordinator.async_shutdown()

        # Clean up HTTP client if present
        if coordinator.client is not None:
            await coordinator.client.close()

        # Clean up Modbus transport if present
        if (
            hasattr(coordinator, "_modbus_transport")
            and coordinator._modbus_transport is not None
        ):
            await coordinator._modbus_transport.disconnect()

        # Clean up Dongle transport if present
        if (
            hasattr(coordinator, "_dongle_transport")
            and coordinator._dongle_transport is not None
        ):
            await coordinator._dongle_transport.disconnect()

        # Clean up hybrid transport cache (multiple local transports)
        if hasattr(coordinator, "_hybrid_transport_cache"):
            for transport in coordinator._hybrid_transport_cache.values():
                if transport is not None and transport.is_connected:
                    await transport.disconnect()
            coordinator._hybrid_transport_cache.clear()

    return bool(unload_ok)


async def async_remove_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Handle removal of an entry.

    This is called when the user deletes the integration from the UI.
    It purges all statistics for this integration's entities, allowing
    TOTAL_INCREASING sensors to reset when the integration is re-added.

    Entity Registry entries (names, areas, labels) are NOT deleted,
    so they will be automatically restored when re-adding the integration.
    """
    _LOGGER.info("Removing EG4 Web Monitor entry: %s", entry.entry_id)

    # Get entity registry
    entity_registry = er.async_get(hass)

    # Get all entities for this config entry
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    # Purge statistics for each entity
    entity_ids = [entity.entity_id for entity in entities]

    if entity_ids:
        _LOGGER.info(
            "Purging statistics for %d entities to allow fresh sensor history",
            len(entity_ids),
        )

        # Call recorder service to purge statistics
        # This removes all historical data but preserves Entity Registry entries
        try:
            if hass.services.has_service("recorder", "purge_entities"):
                await hass.services.async_call(
                    "recorder",
                    "purge_entities",
                    {
                        "entity_id": entity_ids,
                        "keep_days": 0,  # Delete all history
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "Statistics purge complete for %d entities", len(entity_ids)
                )
            else:
                _LOGGER.debug(
                    "Recorder service not available, skipping statistics purge"
                )
        except Exception as e:
            _LOGGER.warning("Failed to purge entity statistics: %s", e)
    else:
        _LOGGER.debug("No entities found to purge statistics for")
