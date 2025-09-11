"""Binary sensor platform for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_SENSOR_TYPES, DOMAIN
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor binary sensor entities."""
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities: List[BinarySensorEntity] = []
    
    # Wait for initial data fetch if not already available
    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.debug("Waiting for coordinator data to become available for binary sensor setup")
        await coordinator.async_config_entry_first_refresh()
    
    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available after coordinator refresh for binary sensor setup")
        return
    
    # Create binary sensor entities for each device
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type %s, binary_sensors: %s", 
                     serial, device_type, device_data.get("binary_sensors", {}))
        
        if device_type in ["inverter", "gridboss", "parallel_group"]:
            entities.extend(_create_device_binary_sensors(coordinator, serial, device_data, device_type))
        else:
            _LOGGER.warning("Unknown device type '%s' for device %s", device_type, serial)
    
    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Added %d binary sensor entities", len(entities))
    else:
        _LOGGER.debug("No binary sensor entities created (no binary sensors defined in BINARY_SENSOR_TYPES)")


def _create_device_binary_sensors(
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    device_data: Dict[str, Any],
    device_type: str,
) -> List[BinarySensorEntity]:
    """Create binary sensor entities for a device."""
    entities = []
    
    binary_sensors = device_data.get("binary_sensors", {})
    _LOGGER.debug("Creating binary sensors for device %s: available=%s, known_types=%s", 
                 serial, list(binary_sensors.keys()), list(BINARY_SENSOR_TYPES.keys()))
    
    # Create binary sensors for the device
    for sensor_key, value in binary_sensors.items():
        if sensor_key in BINARY_SENSOR_TYPES:
            _LOGGER.debug("Creating binary sensor %s for device %s", sensor_key, serial)
            entities.append(
                EG4BinarySensor(
                    coordinator=coordinator,
                    serial=serial,
                    sensor_key=sensor_key,
                    device_type=device_type,
                )
            )
        else:
            _LOGGER.debug("Skipping unknown binary sensor type: %s", sensor_key)
    
    return entities


class EG4BinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an EG4 Web Monitor binary sensor."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
        device_type: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        
        self._serial = serial
        self._sensor_key = sensor_key
        self._device_type = device_type
        
        # Get sensor configuration
        self._sensor_config = BINARY_SENSOR_TYPES.get(sensor_key, {})
        
        # Generate unique ID
        self._attr_unique_id = f"{serial}_{sensor_key}"
        
        # Set entity attributes
        device_data = self.coordinator.data["devices"].get(serial, {})
        model = device_data.get("model", "Unknown")
        
        if device_type == "gridboss":
            self._attr_name = self._sensor_config.get('name', sensor_key)
            self._attr_entity_id = f"binary_sensor.eg4_gridboss_{serial}_{sensor_key}"
        elif device_type == "parallel_group":
            self._attr_name = f"{model} {self._sensor_config.get('name', sensor_key)}"
            self._attr_entity_id = f"binary_sensor.eg4_parallel_group_{sensor_key}"
        else:
            self._attr_name = f"{model} {serial} {self._sensor_config.get('name', sensor_key)}"
            self._attr_entity_id = f"binary_sensor.eg4_{model.lower().replace(' ', '_')}_{serial}_{sensor_key}"
        
        # Set binary sensor properties from configuration
        device_class_name = self._sensor_config.get("device_class")
        if device_class_name:
            try:
                self._attr_device_class = getattr(BinarySensorDeviceClass, device_class_name.upper())
            except AttributeError:
                _LOGGER.warning("Unknown binary sensor device class: %s", device_class_name)
                self._attr_device_class = None
        
        self._attr_icon = self._sensor_config.get("icon")
        
        # Set entity category for diagnostic sensors
        if sensor_key in ["system_fault"]:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        return self.coordinator.get_device_info(self._serial)

    @property
    def is_on(self) -> Optional[bool]:
        """Return the state of the binary sensor."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
            
        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None
            
        binary_sensors = device_data.get("binary_sensors", {})
        return binary_sensors.get(self._sensor_key)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._serial]
        )