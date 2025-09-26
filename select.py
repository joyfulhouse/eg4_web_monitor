"""Select platform for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    create_device_info,
    generate_entity_id,
    generate_unique_id,
    create_entity_name
)

_LOGGER = logging.getLogger(__name__)

# Operating mode options
OPERATING_MODE_OPTIONS = ["Normal", "Standby"]
OPERATING_MODE_MAPPING = {
    "Normal": True,    # True = normal mode (FUNC_SET_TO_STANDBY = true means Normal)
    "Standby": False   # False = standby mode (FUNC_SET_TO_STANDBY = false means Standby)
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor select entities."""
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: List[SelectEntity] = []

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
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")
            model_lower = model.lower()

            _LOGGER.info(
                "Evaluating select compatibility for device %s: "
                "model='%s' (original), model_lower='%s'",
                serial, model, model_lower
            )

            # Check if device model is known to support select functions
            # Based on the feature request, this appears to be for standard inverters
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                # Add operating mode select
                entities.append(EG4OperatingModeSelect(coordinator, serial, device_data))
                _LOGGER.info(
                    "✅ Added operating mode select for compatible device %s (%s)", serial, model
                )
            else:
                _LOGGER.warning(
                    "❌ Skipping select for device %s (%s) - "
                    "model not in supported list %s",
                    serial, model, supported_models
                )
        else:
            _LOGGER.debug("Skipping device %s - not an inverter (type: %s)", serial, device_type)

    if entities:
        _LOGGER.info("Adding %d select entities (operating mode)", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.info("No select entities to add")


class EG4OperatingModeSelect(CoordinatorEntity, SelectEntity):
    """Select to control operating mode (Normal/Standby)."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: Dict[str, Any],
    ) -> None:
        """Initialize the operating mode select."""
        super().__init__(coordinator)

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: Optional[str] = None

        # Get device info from coordinator data
        device_info = coordinator.data.get("device_info", {}).get(serial, {})
        self._model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create unique identifiers using consolidated utilities
        self._attr_unique_id = generate_unique_id(serial, "operating_mode")
        self._attr_entity_id = generate_entity_id("select", self._model, serial, "operating_mode")

        # Set device attributes
        self._attr_name = create_entity_name(self._model, serial, "Operating Mode")
        self._attr_icon = "mdi:power-settings"
        self._attr_options = OPERATING_MODE_OPTIONS

        # Device info for grouping using consolidated utility
        self._attr_device_info = create_device_info(serial, self._model)

    @property
    def current_option(self) -> Optional[str]:
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
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
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
            return device_data.get("type") == "inverter"
        return False

    async def async_select_option(self, option: str) -> None:
        """Change the operating mode."""
        if option not in OPERATING_MODE_OPTIONS:
            _LOGGER.error("Invalid operating mode option: %s", option)
            return

        try:
            _LOGGER.debug("Setting operating mode to %s for device %s", option, self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = option
            self.async_write_ha_state()

            # Get the mode setting from mapping
            # Based on user clarification:
            # Normal = FUNC_SET_TO_STANDBY = true
            # Standby = FUNC_SET_TO_STANDBY = false
            standby_param_value = OPERATING_MODE_MAPPING[option]

            # Call the API to set the mode using control_function_parameter directly
            await self.coordinator.api.control_function_parameter(
                self._serial,
                "FUNC_SET_TO_STANDBY",
                standby_param_value
            )
            _LOGGER.info(
                "Successfully set operating mode to %s for device %s", option, self._serial
            )

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error(
                "Failed to set operating mode to %s for device %s: %s", option, self._serial, e
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
