"""Select platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pylxpweb.devices.inverters.base import OperatingMode

if TYPE_CHECKING:
    from homeassistant.components.select import SelectEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.select import SelectEntity  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from . import EG4ConfigEntry
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    create_device_info,
    generate_entity_id,
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 2

# Operating mode options
OPERATING_MODE_OPTIONS = ["Normal", "Standby"]
OPERATING_MODE_MAPPING = {
    "Normal": True,  # True = normal mode (FUNC_SET_TO_STANDBY = true means Normal)
    "Standby": False,  # False = standby mode (FUNC_SET_TO_STANDBY = false means Standby)
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor select entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[SelectEntity] = []

    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for select setup")
        return

    # Create select entities for compatible devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type: %s", serial, device_type)

        # Only create selects for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check
            model = device_data.get("model", "Unknown")
            model_lower = model.lower()

            _LOGGER.debug(
                "Evaluating select compatibility: device=%s, model=%s",
                serial,
                model,
            )

            # Check if device model is known to support select functions
            # Based on the feature request, this appears to be for standard inverters
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                # Add operating mode select
                entities.append(
                    EG4OperatingModeSelect(coordinator, serial, device_data)
                )
                _LOGGER.debug(
                    "Added operating mode select for device %s (%s)",
                    serial,
                    model,
                )
            else:
                _LOGGER.debug(
                    "Skipping select for device %s (%s) - unsupported model",
                    serial,
                    model,
                )
        else:
            _LOGGER.debug(
                "Skipping device %s - not an inverter (type: %s)", serial, device_type
            )

    if entities:
        _LOGGER.info("Setup complete: %d select entities created", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No select entities created - no compatible devices found")


class EG4OperatingModeSelect(CoordinatorEntity, SelectEntity):
    """Select to control operating mode (Normal/Standby)."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the operating mode select."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: str | None = None

        # Get device info from coordinator data
        self._model = (
            coordinator.data.get("devices", {}).get(serial, {}).get("model", "Unknown")
        )

        # Create unique identifiers using consolidated utilities
        self._attr_unique_id = generate_unique_id(serial, "operating_mode")
        self._attr_entity_id = generate_entity_id(
            "select", self._model, serial, "operating_mode"
        )

        # Set device attributes
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Operating Mode"
        self._attr_icon = "mdi:power-settings"
        self._attr_options = OPERATING_MODE_OPTIONS

        # Device info for grouping using consolidated utility
        self._attr_device_info = create_device_info(serial, self._model)

    @property
    def current_option(self) -> str | None:
        """Return the current operating mode."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Try to get the current mode from coordinator data
        # Based on user clarification: FUNC_SET_TO_STANDBY parameter mapping:
        # - true = Normal mode
        # - false = Standby mode
        if self.coordinator.data and "parameters" in self.coordinator.data:
            device_params = self.coordinator.data["parameters"].get(self._serial, {})
            standby_status = device_params.get("FUNC_SET_TO_STANDBY")
            if standby_status is not None:
                # FUNC_SET_TO_STANDBY true = Normal, false = Standby
                return "Normal" if standby_status else "Standby"

        # Default to Normal if we don't have status information
        return "Normal"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add device serial for reference
        attributes["device_serial"] = self._serial

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        # Add any relevant parameter information if available
        if self.coordinator.data and "parameters" in self.coordinator.data:
            device_params = self.coordinator.data["parameters"].get(self._serial, {})
            standby_status = device_params.get("FUNC_SET_TO_STANDBY")
            if standby_status is not None:
                attributes["standby_parameter"] = standby_status

        return attributes if attributes else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if the device supports operating mode control
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            # Only available for inverter devices (not GridBOSS)
            return bool(device_data.get("type") == "inverter")
        return False

    async def async_select_option(self, option: str) -> None:
        """Change the operating mode using device object method."""
        if option not in OPERATING_MODE_OPTIONS:
            _LOGGER.error("Invalid operating mode option: %s", option)
            return

        try:
            _LOGGER.debug(
                "Setting operating mode to %s for device %s", option, self._serial
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = option
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self._serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial} not found")

            # Use device object convenience method
            # Convert string to OperatingMode enum
            mode_value = OperatingMode[
                option.upper()
            ]  # "Normal" -> NORMAL, "Standby" -> STANDBY
            success = await inverter.set_operating_mode(mode_value)
            if not success:
                raise HomeAssistantError(f"Failed to set operating mode to {option}")

            _LOGGER.info(
                "Successfully set operating mode to %s for device %s",
                option,
                self._serial,
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error(
                "Failed to set operating mode to %s for device %s: %s",
                option,
                self._serial,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
