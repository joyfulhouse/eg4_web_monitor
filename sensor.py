"""Sensor platform for EG4 Inverter integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES
from .coordinator import EG4DataUpdateCoordinator
from .utils import clean_battery_display_name

_LOGGER = logging.getLogger(__name__)




async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Inverter sensor entities."""
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities: List[SensorEntity] = []
    
    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for sensor setup")
        return
    
    # Create sensor entities for each device
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        
        if device_type == "inverter":
            entities.extend(_create_inverter_sensors(coordinator, serial, device_data))
        elif device_type == "gridboss":
            entities.extend(_create_gridboss_sensors(coordinator, serial, device_data))
        elif device_type == "parallel_group":
            entities.extend(_create_parallel_group_sensors(coordinator, serial, device_data))
        else:
            _LOGGER.warning("Unknown device type '%s' for device %s", device_type, serial)
    
    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Added %d sensor entities", len(entities))
    else:
        _LOGGER.warning("No sensor entities created")


def _create_inverter_sensors(
    coordinator: EG4DataUpdateCoordinator, 
    serial: str, 
    device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for an inverter device."""
    entities = []
    
    # Create main inverter sensors
    for sensor_key, value in device_data.get("sensors", {}).items():
        if sensor_key in SENSOR_TYPES:
            entities.append(
                EG4InverterSensor(
                    coordinator=coordinator,
                    serial=serial,
                    sensor_key=sensor_key,
                    device_type="inverter",
                )
            )
    
    # Create individual battery sensors
    for battery_key, battery_sensors in device_data.get("batteries", {}).items():
        for sensor_key, value in battery_sensors.items():
            if sensor_key in SENSOR_TYPES:
                entities.append(
                    EG4BatterySensor(
                        coordinator=coordinator,
                        serial=serial,
                        battery_key=battery_key,
                        sensor_key=sensor_key,
                    )
                )
    
    return entities


def _create_gridboss_sensors(
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for a GridBOSS device."""
    entities = []
    
    # Create GridBOSS sensors
    for sensor_key, value in device_data.get("sensors", {}).items():
        if sensor_key in SENSOR_TYPES:
            entities.append(
                EG4InverterSensor(
                    coordinator=coordinator,
                    serial=serial,
                    sensor_key=sensor_key,
                    device_type="gridboss",
                )
            )
    
    return entities


def _create_parallel_group_sensors(
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for a Parallel Group device."""
    entities = []
    
    # Create Parallel Group sensors
    for sensor_key, value in device_data.get("sensors", {}).items():
        if sensor_key in SENSOR_TYPES:
            entities.append(
                EG4InverterSensor(
                    coordinator=coordinator,
                    serial=serial,
                    sensor_key=sensor_key,
                    device_type="parallel_group",
                )
            )
    
    return entities


class EG4InverterSensor(CoordinatorEntity, SensorEntity):
    """Representation of an EG4 Inverter sensor."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
        device_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._serial = serial
        self._sensor_key = sensor_key
        self._device_type = device_type
        
        # Get sensor configuration
        self._sensor_config = SENSOR_TYPES.get(sensor_key, {})
        
        # Generate unique ID
        self._attr_unique_id = f"{serial}_{sensor_key}"
        
        # Set entity attributes
        device_data = self.coordinator.data["devices"].get(serial, {})
        model = device_data.get("model", "Unknown")
        
        if device_type == "gridboss":
            self._attr_name = self._sensor_config.get('name', sensor_key)
            self._attr_entity_id = f"sensor.eg4_gridboss_{serial}_{sensor_key}"
        elif device_type == "parallel_group":
            self._attr_name = f"{model} {self._sensor_config.get('name', sensor_key)}"
            self._attr_entity_id = f"sensor.eg4_parallel_group_{sensor_key}"
        else:
            self._attr_name = f"{model} {serial} {self._sensor_config.get('name', sensor_key)}"
            self._attr_entity_id = f"sensor.eg4_{model.lower().replace(' ', '_')}_{serial}_{sensor_key}"
        
        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")
        
        # Set display precision for voltage sensors
        if self._attr_device_class == "voltage":
            self._attr_suggested_display_precision = 2
        
        # Set entity category if applicable
        if sensor_key in ["temperature", "cycle_count", "state_of_health", "status_code", "status_text"]:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        return self.coordinator.get_device_info(self._serial)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
            
        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None
            
        sensors = device_data.get("sensors", {})
        return sensors.get(self._sensor_key)

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


class EG4BatterySensor(CoordinatorEntity, SensorEntity):
    """Representation of an EG4 Battery sensor."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        battery_key: str,
        sensor_key: str,
    ) -> None:
        """Initialize the battery sensor."""
        super().__init__(coordinator)
        
        self._serial = serial
        self._battery_key = battery_key
        self._sensor_key = sensor_key
        
        # Get sensor configuration
        self._sensor_config = SENSOR_TYPES.get(sensor_key, {})
        
        # Generate unique ID
        self._attr_unique_id = f"{serial}_{battery_key}_{sensor_key}"
        
        # Set entity attributes
        device_data = self.coordinator.data["devices"].get(serial, {})
        model = device_data.get("model", "Unknown")
        
        # Clean up battery display name to remove redundant serial numbers
        clean_battery_name = clean_battery_display_name(battery_key, serial)
        clean_battery_id = battery_key.replace("_", "").lower()
        
        self._attr_name = f"Battery {clean_battery_name} {self._sensor_config.get('name', sensor_key)}"
        self._attr_entity_id = f"sensor.eg4_{model.lower().replace(' ', '_')}_{serial}_battery_{clean_battery_id}_{sensor_key}"
        
        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")
        
        # Set display precision for voltage sensors
        if self._attr_device_class == "voltage":
            self._attr_suggested_display_precision = 2
        
        # Set entity category
        if sensor_key in ["temperature", "cycle_count", "state_of_health", "battery_firmware_version", 
                         "battery_max_cell_temp_num", "battery_min_cell_temp_num", 
                         "battery_max_cell_voltage_num", "battery_min_cell_voltage_num"]:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif self._sensor_config.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        # Use cleaned battery name for device info
        clean_battery_name = clean_battery_display_name(self._battery_key, self._serial)
        
        # Get firmware version from battery data
        sw_version = "1.0.0"  # Default fallback
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial)
            if device_data and "batteries" in device_data:
                battery_data = device_data["batteries"].get(self._battery_key, {})
                if "battery_firmware_version" in battery_data:
                    sw_version = battery_data["battery_firmware_version"]
        
        return {
            "identifiers": {(DOMAIN, f"{self._serial}_{self._battery_key}")},
            "name": f"Battery {clean_battery_name}",
            "manufacturer": "EG4 Electronics", 
            "model": "Battery Module",
            "serial_number": clean_battery_name,
            "sw_version": sw_version,
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
            
        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None
            
        batteries = device_data.get("batteries", {})
        battery_data = batteries.get(self._battery_key, {})
        return battery_data.get(self._sensor_key)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._serial]
            and self._battery_key in self.coordinator.data["devices"][self._serial].get("batteries", {})
        )