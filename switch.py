"""Switch platform for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor switch entities."""
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: List[SwitchEntity] = []

    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for switch setup")
        return

    # Create quick charge switch entities for compatible devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type: %s", serial, device_type)

        # Only create quick charge switches for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")
            model_lower = model.lower()
            
            _LOGGER.info(
                "Evaluating quick charge compatibility for device %s: model='%s' (original), model_lower='%s'",
                serial, model, model_lower
            )

            # Check if device model is known to support quick charge
            # Based on the feature request, this appears to be for standard inverters
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                entities.append(EG4QuickChargeSwitch(coordinator, serial, device_data))
                _LOGGER.info(
                    "✅ Added quick charge switch for compatible device %s (%s)", serial, model
                )
            else:
                _LOGGER.warning(
                    "❌ Skipping quick charge switch for device %s (%s) - model not in supported list %s",
                    serial, model, supported_models
                )
        else:
            _LOGGER.debug("Skipping device %s - not an inverter (type: %s)", serial, device_type)

    if entities:
        _LOGGER.info("Adding %d quick charge switch entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.info("No quick charge switch entities to add")


class EG4QuickChargeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control quick charge functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: Dict[str, Any],
    ) -> None:
        """Initialize the quick charge switch."""
        super().__init__(coordinator)

        self._serial = serial
        self._device_data = device_data

        # Get device info from coordinator data
        device_info = coordinator.data.get("device_info", {}).get(serial, {})
        self._model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create unique identifiers
        model_clean = self._model.lower().replace(" ", "").replace("-", "")
        self._attr_unique_id = f"{serial}_quick_charge"
        self._attr_entity_id = f"switch.{model_clean}_{serial}_quick_charge"

        # Set device attributes
        self._attr_name = f"{self._model}_{serial} Quick Charge"
        self._attr_icon = "mdi:battery-charging-fast"

        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"{self._model}_{serial}",
            "manufacturer": "EG4 Electronics",
            "model": self._model,
            "serial_number": serial,
        }

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if quick charge is on."""
        # Check if we have quick charge status data
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            quick_charge_status = device_data.get("quick_charge_status")

            if quick_charge_status:
                # Parse the quick charge status response
                # This will depend on the actual API response format
                status = quick_charge_status.get("status")
                if status is not None:
                    # Assuming status is a boolean or integer where 1/True means active
                    return bool(status)

        # Default to False if we don't have status information
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if the device supports quick charge
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            # Only available for inverter devices (not GridBOSS)
            return device_data.get("type") == "inverter"
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn on quick charge."""
        try:
            _LOGGER.debug("Starting quick charge for device %s", self._serial)
            await self.coordinator.api.start_quick_charge(self._serial)

            # Request immediate coordinator update to reflect the change
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to start quick charge for device %s: %s", self._serial, e)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn off quick charge."""
        try:
            _LOGGER.debug("Stopping quick charge for device %s", self._serial)
            await self.coordinator.api.stop_quick_charge(self._serial)

            # Request immediate coordinator update to reflect the change
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to stop quick charge for device %s: %s", self._serial, e)
            raise
