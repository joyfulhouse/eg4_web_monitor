"""Button platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
else:
    from homeassistant.components.button import (  # type: ignore[assignment]
        ButtonEntity,
        ButtonEntityDescription,
    )

from . import EG4ConfigEntry
from .base_entity import EG4BatteryEntity, EG4DeviceEntity, EG4StationEntity
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
    """Set up EG4 Web Monitor button entities.

    Entity registration is split into two phases to ensure proper device hierarchy:
    1. Phase 1: Station and device refresh buttons (creates parent devices first)
    2. Phase 2: Individual battery refresh buttons (can safely reference battery bank)

    This ordering prevents HA warning about non-existing via_device references.
    See: https://github.com/joyfulhouse/eg4_web_monitor/issues/81
    """
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    # Phase 1 entities: devices that don't reference battery bank via via_device
    phase1_entities: list[ButtonEntity] = []
    # Phase 2 entities: individual batteries that reference battery bank via via_device
    phase2_entities: list[ButtonEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for button setup")
        return

    # Create station refresh button if station data is available
    if "station" in coordinator.data:
        phase1_entities.append(EG4StationRefreshButton(coordinator))

    # Skip device buttons if no device data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data available for button setup, only creating station buttons"
        )
        if phase1_entities:
            async_add_entities(phase1_entities)
        return

    # Create refresh diagnostic buttons for all devices (phase 1)
    for serial, device_data in coordinator.data["devices"].items():
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
        phase1_entities.append(
            EG4RefreshButton(coordinator, serial, device_data, model)
        )

    # Create refresh buttons for individual batteries (phase 2)
    for serial, device_data in coordinator.data["devices"].items():
        # Check if this device has individual batteries
        if "batteries" in device_data:
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            parent_model = device_info.get("deviceTypeText4APP", "Unknown")

            for battery_key in device_data["batteries"]:
                # Create refresh button for each individual battery
                phase2_entities.append(
                    EG4BatteryRefreshButton(
                        coordinator=coordinator,
                        parent_serial=serial,
                        battery_key=battery_key,
                        parent_model=parent_model,
                        battery_id=battery_key,
                    )
                )

    # Phase 1: Register parent device buttons first
    # This ensures battery bank devices exist before individual batteries reference them
    if phase1_entities:
        async_add_entities(phase1_entities)
        _LOGGER.debug(
            "Phase 1: Added %d button entities (station, devices)", len(phase1_entities)
        )

    # Phase 2: Register individual battery buttons (reference battery bank via via_device)
    if phase2_entities:
        async_add_entities(phase2_entities)
        _LOGGER.debug(
            "Phase 2: Added %d individual battery button entities", len(phase2_entities)
        )


class EG4RefreshButton(EG4DeviceEntity, ButtonEntity):
    """Button to refresh device data and invalidate cache.

    Inherits common functionality from EG4DeviceEntity including:
    - Device info lookup via coordinator
    - Serial number management
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
        model: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, serial)

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

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{serial}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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
                    _LOGGER.debug(
                        "Refreshing inverter device object for %s", self._serial
                    )
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


class EG4BatteryRefreshButton(EG4BatteryEntity, ButtonEntity):
    """Button to refresh individual battery data and invalidate cache.

    Inherits common functionality from EG4BatteryEntity including:
    - Battery device info lookup via coordinator
    - Parent serial and battery key management
    - Availability checking for battery presence
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        coordinator: EG4DataUpdateCoordinator,
        parent_serial: str,
        battery_key: str,
        parent_model: str,
        battery_id: str,
    ) -> None:
        """Initialize the battery refresh button."""
        super().__init__(coordinator, parent_serial, battery_key)

        self._parent_model = parent_model
        self._battery_id = battery_id

        # Create unique identifiers - match battery device pattern
        self._attr_unique_id = f"{parent_serial}_{battery_key}_refresh_data"
        self._attr_entity_id = (
            f"button.battery_{parent_serial}_{battery_key}_refresh_data"
        )

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{battery_key}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add parent device info
        attributes["parent_device"] = self._parent_serial
        attributes["battery_id"] = self._battery_id

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.debug(
                "Refresh button pressed for battery %s",
                self._battery_key,
            )

            # Get parent inverter object and refresh (which refreshes all batteries)
            inverter = self.coordinator.get_inverter_object(self._parent_serial)
            if inverter:
                await inverter.refresh()
            else:
                _LOGGER.warning(
                    "Parent inverter object not found for %s", self._parent_serial
                )

            # Force immediate coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh data for battery %s: %s", self._battery_key, e
            )
            raise


class EG4StationRefreshButton(EG4StationEntity, ButtonEntity):
    """Button to refresh station/plant data.

    Inherits common functionality from EG4StationEntity including:
    - Station device info lookup via coordinator
    - Availability checking for station data
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
    ) -> None:
        """Initialize the station refresh button."""
        super().__init__(coordinator)

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

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            # Force immediate coordinator refresh to fetch fresh station data
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh station data for plant %s: %s",
                self.coordinator.plant_id,
                e,
            )
            raise
