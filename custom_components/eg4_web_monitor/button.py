"""Button platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.button import ButtonEntity, ButtonEntityDescription  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import CoordinatorEntity  # type: ignore[assignment]

from . import EG4ConfigEntry
from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    generate_entity_id,
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor button entities."""
    _LOGGER.info(
        "Setting up EG4 Web Monitor button entities for entry %s", entry.entry_id
    )
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: List[ButtonEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for button setup")
        return

    # Create station refresh button if station data is available
    if "station" in coordinator.data:
        entities.append(EG4StationRefreshButton(coordinator))
        _LOGGER.info("✅ Added refresh button for station")

    # Skip device buttons if no device data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data available for button setup, only creating station buttons"
        )
        if entities:
            async_add_entities(entities)
        return

    _LOGGER.info(
        "Found %d devices for button setup: %s",
        len(coordinator.data["devices"]),
        list(coordinator.data["devices"].keys()),
    )

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
                entities.append(
                    EG4BatteryRefreshButton(
                        coordinator=coordinator,
                        parent_serial=serial,
                        battery_key=battery_key,
                        parent_model=parent_model,
                        battery_id=battery_key,  # Use battery_key as the display ID
                    )
                )
                _LOGGER.info(
                    "✅ Added refresh button for battery %s (parent: %s)",
                    battery_key,
                    serial,
                )

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
        self.coordinator: EG4DataUpdateCoordinator = coordinator

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
            # Use the same suffix for unique_id to ensure new entity registration
            self._attr_unique_id = entity_id_suffix
        else:
            # Normal device entity ID generation using consolidated utilities
            self._attr_unique_id = generate_unique_id(serial, "refresh_data")
            self._attr_entity_id = generate_entity_id(
                "button", model, serial, "refresh_data"
            )

        # Set device attributes using consolidated utilities
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Device info will be provided by the device_info property

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{serial}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_device_info(self._serial)
        return device_info if device_info else {}

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

        # Add device type info
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            device_type = device_data.get("type", "unknown")
            attributes["device_type"] = device_type

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.debug(
                "Refresh button pressed for device %s - using device object",
                self._serial,
            )

            # Get device object and refresh using high-level method
            device_data = self.coordinator.data.get("devices", {}).get(self._serial, {})
            device_type = device_data.get("type", "unknown")

            if device_type == "inverter":
                # Get inverter object and refresh
                inverter = self.coordinator.get_inverter_object(self._serial)
                if inverter:
                    _LOGGER.debug("Refreshing inverter device object for %s", self._serial)
                    await inverter.refresh()
                    _LOGGER.debug("Successfully refreshed inverter %s", self._serial)
                else:
                    _LOGGER.warning("Inverter object not found for %s", self._serial)

            # For other device types or as fallback, trigger coordinator refresh
            await self.coordinator.async_request_refresh()
            _LOGGER.debug("Successfully refreshed data for device %s", self._serial)

        except Exception as e:
            _LOGGER.error("Failed to refresh data for device %s: %s", self._serial, e)
            raise


class EG4BatteryRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh individual battery data and invalidate cache."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        coordinator: EG4DataUpdateCoordinator,
        parent_serial: str,
        battery_key: str,
        parent_model: str,
        battery_id: str,
    ) -> None:
        """Initialize the battery refresh button."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._parent_serial = parent_serial
        self._battery_key = battery_key
        self._parent_model = parent_model
        self._battery_id = battery_id

        # Create unique identifiers - match battery device pattern
        self._attr_unique_id = f"{parent_serial}_{battery_key}_refresh_data"
        self._attr_entity_id = (
            f"button.battery_{parent_serial}_{battery_key}_refresh_data"
        )

        # Set device attributes
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Device info for grouping with battery
        # Must match coordinator.get_battery_device_info()
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{parent_serial}_{battery_key}")},
            "name": f"Battery {battery_key}",  # Will be cleaned by coordinator
            "manufacturer": "EG4 Electronics",
            "model": f"{parent_model} Battery",
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
            parent_device = self.coordinator.data["devices"].get(
                self._parent_serial, {}
            )
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

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.info(
                "Battery refresh button pressed for battery %s (parent: %s) - "
                "using device object methods",
                self._battery_key,
                self._parent_serial,
            )

            # Get parent inverter object and refresh (which refreshes all batteries)
            inverter = self.coordinator.get_inverter_object(self._parent_serial)
            if inverter:
                _LOGGER.debug(
                    "Refreshing parent inverter %s to update battery %s",
                    self._parent_serial,
                    self._battery_key,
                )
                await inverter.refresh()
                _LOGGER.debug(
                    "Successfully refreshed battery %s via parent inverter",
                    self._battery_key,
                )
            else:
                _LOGGER.warning(
                    "Parent inverter object not found for %s", self._parent_serial
                )

            # Force immediate coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()
            _LOGGER.debug(
                "Successfully refreshed data for battery %s", self._battery_key
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh data for battery %s: %s", self._battery_key, e
            )
            raise


class EG4StationRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh station/plant data."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
    ) -> None:
        """Initialize the station refresh button."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        # Create unique identifiers
        self._attr_unique_id = f"station_{coordinator.plant_id}_refresh_data"
        self._attr_entity_id = f"button.station_{coordinator.plant_id}_refresh_data"

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"station_{coordinator.plant_id}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_station_device_info()
        return device_info if device_info else {}

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "station" in self.coordinator.data
        )

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return extra state attributes."""
        attributes = {}

        # Add station/plant ID
        attributes["plant_id"] = self.coordinator.plant_id

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.info(
                "Station refresh button pressed for plant %s - refreshing station data",
                self.coordinator.plant_id,
            )

            # Force immediate coordinator refresh to fetch fresh station data
            await self.coordinator.async_request_refresh()

            _LOGGER.info(
                "Successfully refreshed station data for plant %s",
                self.coordinator.plant_id,
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh station data for plant %s: %s",
                self.coordinator.plant_id,
                e,
            )
            raise
