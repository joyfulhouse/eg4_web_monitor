"""EG4 Web Monitor integration for Home Assistant."""

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]

SERVICE_REFRESH_DATA = "refresh_data"

REFRESH_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EG4 Web Monitor from a config entry."""
    _LOGGER.debug("Setting up EG4 Web Monitor entry: %s", entry.entry_id)

    # Initialize the coordinator
    coordinator = EG4DataUpdateCoordinator(hass, entry)

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in hass data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register refresh service (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_DATA,
            _handle_refresh_data,
            schema=REFRESH_DATA_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading EG4 Web Monitor entry: %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up coordinator
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.api.close()

        # Remove from hass data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _handle_refresh_data(call: ServiceCall) -> None:
    """Handle refresh data service call."""
    hass = call.hass
    entry_id = call.data.get("entry_id")

    coordinators_to_refresh = []

    if entry_id:
        # Refresh specific coordinator
        if entry_id in hass.data.get(DOMAIN, {}):
            coordinators_to_refresh.append(hass.data[DOMAIN][entry_id])
        else:
            _LOGGER.error("Config entry %s not found", entry_id)
            return
    else:
        # Refresh all coordinators
        coordinators_to_refresh = list(hass.data.get(DOMAIN, {}).values())

    if not coordinators_to_refresh:
        _LOGGER.warning("No EG4 coordinators found to refresh")
        return

    # Refresh all coordinators
    for coordinator in coordinators_to_refresh:
        _LOGGER.info(
            "Refreshing EG4 data for coordinator %s", coordinator.entry.entry_id
        )
        await coordinator.async_request_refresh()

    _LOGGER.info(
        "Refresh completed for %d coordinator(s)", len(coordinators_to_refresh)
    )
