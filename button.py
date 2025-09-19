"""Button platform for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator
from .utils import clean_battery_display_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor button entities."""
    _LOGGER.info("Setting up EG4 Web Monitor button entities for entry %s", entry.entry_id)
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: List[ButtonEntity] = []

    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for button setup - coordinator.data: %s", coordinator.data)
        return

    _LOGGER.info("Found %d devices for button setup: %s",
                 len(coordinator.data["devices"]), list(coordinator.data["devices"].keys()))

    # Create refresh diagnostic buttons for all devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type: %s", serial, device_type)

        # Get device info for proper naming
        device_type = device_data.get("type", "unknown")
        if device_type == "parallel_group":
            # For parallel groups, get model from device data itself
            model = device_data.get("model", "Parallel Group")
        else:
            # For other devices, get model from device_info from API
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create refresh button for all device types
        entities.append(EG4RefreshButton(coordinator, serial, device_data, model))
        _LOGGER.info("✅ Added refresh button for device %s (%s)", serial, model)

    # Also create refresh buttons for individual batteries
    for serial, device_data in coordinator.data["devices"].items():
        # Check if this device has individual batteries
        if "batteries" in device_data:
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            parent_model = device_info.get("deviceTypeText4APP", "Unknown")

            for battery_key, _ in device_data["batteries"].items():
                # Create refresh button for each individual battery
                entities.append(EG4BatteryRefreshButton(
                    coordinator=coordinator,
                    parent_serial=serial,
                    battery_key=battery_key,
                    parent_model=parent_model,
                    battery_id=battery_key,  # Use battery_key as the display ID
                ))
                _LOGGER.info("✅ Added refresh button for battery %s (parent: %s)", battery_key, serial)

    if entities:
        _LOGGER.info("Adding %d refresh button entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.info("No refresh button entities to add")


class EG4RefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh device data and invalidate cache."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: Dict[str, Any],
        model: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)

        self._serial = serial
        self._device_data = device_data
        self._model = model

        # Create unique identifiers
        device_type = device_data.get("type", "unknown")
        if device_type == "parallel_group":
            # Special handling for parallel group entity IDs
            if "Parallel Group" in model and len(model) > len("Parallel Group"):
                # Extract letter from "Parallel Group A" -> "parallel_group_a"
                group_letter = model.replace("Parallel Group", "").strip().lower()
                entity_id_suffix = f"parallel_group_{group_letter}_refresh_data"
            else:
                # Fallback for just "Parallel Group" -> "parallel_group_refresh_data"
                entity_id_suffix = "parallel_group_refresh_data"
            self._attr_entity_id = f"button.{entity_id_suffix}"
            self._attr_unique_id = f"{serial}_refresh_data"
        else:
            # Normal device entity ID generation
            model_clean = model.lower().replace(" ", "").replace("-", "")
            self._attr_unique_id = f"{serial}_refresh_data"
            self._attr_entity_id = f"button.{model_clean}_{serial}_refresh_data"

        # Set device attributes
        if device_type == "parallel_group":
            # For parallel groups, don't include the "parallel_group" serial in the name
            self._attr_name = f"{model} Refresh Data"
        else:
            # For other devices, include serial number
            self._attr_name = f"{model} {serial} Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"{model}_{serial}",
            "manufacturer": "EG4 Electronics",
            "model": model,
            "serial_number": serial,
        }

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{serial}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Button is always available if device exists
        if self.coordinator.data and "devices" in self.coordinator.data:
            return self._serial in self.coordinator.data["devices"]
        return False

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return extra state attributes."""
        attributes = {}

        # Add cache statistics if available
        if hasattr(self.coordinator.api, 'get_cache_stats'):
            cache_stats = self.coordinator.api.get_cache_stats()
            if cache_stats:
                attributes["cache_entries"] = cache_stats.get("total_entries", 0)
                attributes["cache_hits"] = cache_stats.get("cache_hits", 0)
                attributes["cache_misses"] = cache_stats.get("cache_misses", 0)

        # Add device type info
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            device_type = device_data.get("type", "unknown")
            attributes["device_type"] = device_type

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.info("Refresh button pressed for device %s - clearing cache and refreshing data", self._serial)

            # Step 1: Clear all cache for this device
            if hasattr(self.coordinator.api, '_invalidate_cache_for_device'):
                self.coordinator.api._invalidate_cache_for_device(self._serial)
                _LOGGER.debug("Cleared device-specific cache for %s", self._serial)

            # Step 2: Clear parameter cache to ensure fresh parameter reads
            if hasattr(self.coordinator.api, '_clear_parameter_cache'):
                self.coordinator.api._clear_parameter_cache()
                _LOGGER.debug("Cleared parameter cache")

            # Step 3: Force immediate coordinator refresh
            await self.coordinator.async_request_refresh()
            _LOGGER.info("Successfully refreshed data for device %s", self._serial)

            # Step 4: Also refresh device parameters if it's an inverter
            device_data = self.coordinator.data.get("devices", {}).get(self._serial, {})
            if device_data.get("type") == "inverter":
                await self.coordinator.async_refresh_device_parameters(self._serial)
                _LOGGER.debug("Refreshed parameters for inverter %s", self._serial)
        except Exception as e:
            _LOGGER.error("Failed to refresh data for device %s: %s", self._serial, e)
            raise


class EG4BatteryRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh individual battery data and invalidate cache."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        parent_serial: str,
        battery_key: str,
        parent_model: str,
        battery_id: str,
    ) -> None:
        """Initialize the battery refresh button."""
        super().__init__(coordinator)

        self._parent_serial = parent_serial
        self._battery_key = battery_key
        self._parent_model = parent_model
        self._battery_id = battery_id

        # Create unique identifiers - match battery device pattern
        self._attr_unique_id = f"{parent_serial}_{battery_key}_refresh_data"
        self._attr_entity_id = f"button.battery_{parent_serial}_{battery_key}_refresh_data"

        # Set device attributes - use clean battery name format
        clean_battery_name = clean_battery_display_name(battery_key, parent_serial)
        self._attr_name = f"Battery {clean_battery_name} Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Device info for grouping with battery - must match coordinator.get_battery_device_info()
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{parent_serial}_{battery_key}")},
            "name": f"Battery {battery_key}",  # Will be cleaned by coordinator
            "manufacturer": "EG4 Electronics", 
            "model": f"{parent_model} Battery",
            "serial_number": f"{parent_serial}_{battery_key}",
            "via_device": (DOMAIN, parent_serial),
        }

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{battery_key}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Button is available if parent device exists and has this specific battery
        if self.coordinator.data and "devices" in self.coordinator.data:
            parent_device = self.coordinator.data["devices"].get(self._parent_serial, {})
            if parent_device and "batteries" in parent_device:
                return self._battery_key in parent_device["batteries"]
        return False

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return extra state attributes."""
        attributes = {}

        # Add parent device info
        attributes["parent_device"] = self._parent_serial
        attributes["battery_id"] = self._battery_id

        # Add cache statistics if available
        if hasattr(self.coordinator.api, 'get_cache_stats'):
            cache_stats = self.coordinator.api.get_cache_stats()
            if cache_stats:
                attributes["cache_entries"] = cache_stats.get("total_entries", 0)

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.info(
                "Battery refresh button pressed for battery %s (parent: %s) - clearing cache and refreshing data",
                self._battery_key, self._parent_serial
            )

            # Step 1: Clear cache for parent device (which includes battery data)
            if hasattr(self.coordinator.api, '_invalidate_cache_for_device'):
                self.coordinator.api._invalidate_cache_for_device(self._parent_serial)
                _LOGGER.debug("Cleared device-specific cache for parent %s", self._parent_serial)

            # Step 2: Clear battery-related cache entries
            if hasattr(self.coordinator.api, 'clear_cache'):
                # Clear entire cache to ensure fresh battery data
                self.coordinator.api.clear_cache()
                _LOGGER.debug("Cleared all cache for fresh battery data")

            # Step 3: Force immediate API call for battery data (most targeted)
            try:
                _LOGGER.debug("Calling battery API directly for fresh data")
                await self.coordinator.api.get_battery_info(self._parent_serial)
                _LOGGER.debug("Successfully fetched fresh battery data from API")
            except Exception as api_error:
                _LOGGER.warning("Direct battery API call failed: %s", api_error)

            # Step 4: Force immediate coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()
            _LOGGER.info("Successfully refreshed data for battery %s", self._battery_key)
        except Exception as e:
            _LOGGER.error("Failed to refresh data for battery %s: %s", self._battery_key, e)
            raise
