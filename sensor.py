"""Sensor platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.sensor import (
        SensorDeviceClass,
        SensorEntity,
        SensorStateClass,
    )
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.sensor import (  # type: ignore[assignment]
        SensorDeviceClass,
        SensorEntity,
        SensorStateClass,
    )
    from homeassistant.helpers.update_coordinator import CoordinatorEntity  # type: ignore[assignment]

from . import EG4ConfigEntry
from .const import DOMAIN, SENSOR_TYPES
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
# Limit concurrent sensor updates to prevent overwhelming the coordinator
MAX_PARALLEL_UPDATES = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor sensor entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

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
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for an inverter device."""
    entities = []

    # Create main inverter sensors
    for sensor_key in device_data.get("sensors", {}):
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
        for sensor_key in battery_sensors:
            if sensor_key in SENSOR_TYPES:
                entities.append(
                    EG4BatterySensor(
                        coordinator=coordinator,
                        serial=serial,
                        battery_key=battery_key,
                        sensor_key=sensor_key,
                    )
                )

        # Create calculated Cell Voltage Delta sensor for each battery
        # Check if we have the required cell voltage data
        if (
            battery_sensors.get("battery_cell_voltage_max") is not None
            and battery_sensors.get("battery_cell_voltage_min") is not None
        ):
            entities.append(
                EG4BatteryCellVoltageDeltaSensor(
                    coordinator=coordinator,
                    serial=serial,
                    battery_key=battery_key,
                )
            )

    return entities


def _create_gridboss_sensors(
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for a GridBOSS device."""
    entities = []

    # Create GridBOSS sensors
    for sensor_key in device_data.get("sensors", {}):
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
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for a Parallel Group device."""
    entities = []

    # Create Parallel Group sensors
    for sensor_key in device_data.get("sensors", {}):
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


class EG4InverterSensor(CoordinatorEntity, SensorEntity):  # type: ignore[misc]
    """Representation of an EG4 Web Monitor sensor."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
        device_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

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

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = self._sensor_config.get("name", sensor_key)

        # Keep entity_id for backwards compatibility
        if device_type == "gridboss":
            self._attr_entity_id = f"sensor.eg4_gridboss_{serial}_{sensor_key}"
        elif device_type == "parallel_group":
            self._attr_entity_id = f"sensor.eg4_parallel_group_{sensor_key}"
        else:
            model_clean = model.lower().replace(" ", "_")
            self._attr_entity_id = f"sensor.eg4_{model_clean}_{serial}_{sensor_key}"

        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")

        # Set display precision for voltage sensors
        if self._attr_device_class == "voltage":
            self._attr_suggested_display_precision = 2

        # Set entity category if applicable
        diagnostic_sensors = [
            "temperature",
            "cycle_count",
            "state_of_health",
            "status_code",
            "status_text",
        ]
        if sensor_key in diagnostic_sensors:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        device_info = self.coordinator.get_device_info(self._serial)
        return dict(device_info) if device_info else {}

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


class EG4BatterySensor(CoordinatorEntity, SensorEntity):  # type: ignore[misc]
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
        self.coordinator: EG4DataUpdateCoordinator = coordinator

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

        # Clean up battery ID for entity ID generation
        clean_battery_id = battery_key.replace("_", "").lower()

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = self._sensor_config.get("name", sensor_key)

        # Keep entity_id for backwards compatibility
        model_clean = model.lower().replace(" ", "_")
        self._attr_entity_id = f"sensor.eg4_{model_clean}_{serial}_battery_{clean_battery_id}_{sensor_key}"

        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")

        # Set display precision for voltage sensors
        if self._attr_device_class == "voltage":
            self._attr_suggested_display_precision = 2

        # Set entity category
        diagnostic_battery_sensors = [
            "temperature",
            "cycle_count",
            "state_of_health",
            "battery_firmware_version",
            "battery_max_cell_temp_num",
            "battery_min_cell_temp_num",
            "battery_max_cell_voltage_num",
            "battery_min_cell_voltage_num",
        ]
        if sensor_key in diagnostic_battery_sensors:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif self._sensor_config.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        device_info = self.coordinator.get_battery_device_info(self._serial, self._battery_key)
        return dict(device_info) if device_info else {}

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
        device_exists = (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._serial]
        )
        battery_exists = device_exists and self._battery_key in self.coordinator.data["devices"][self._serial].get(
            "batteries", {}
        )
        return battery_exists


class EG4BatteryCellVoltageDeltaSensor(CoordinatorEntity, SensorEntity):  # type: ignore[misc]
    """Representation of an EG4 Battery Cell Voltage Delta sensor."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        battery_key: str,
    ) -> None:
        """Initialize the battery cell voltage delta sensor."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._battery_key = battery_key

        # Clean up battery ID for entity ID generation
        clean_battery_id = battery_key.replace("_", "").replace("-", "").lower()

        # Entity configuration
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Cell Voltage Delta"
        self._attr_unique_id = f"{serial}_{battery_key}_cell_voltage_delta"
        serial_clean = serial.lower()
        self._attr_entity_id = f"sensor.battery_{serial_clean}_{clean_battery_id}_cell_voltage_delta"

        # Sensor configuration
        self._attr_native_unit_of_measurement = "V"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-sync"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_suggested_display_precision = 3

        # Device registry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{serial}_{battery_key}")},
        }

    @property
    def native_value(self) -> Optional[float]:
        """Return the calculated cell voltage delta."""
        device_data = self.coordinator.data["devices"].get(self._serial, {})
        batteries = device_data.get("batteries", {})
        battery_data = batteries.get(self._battery_key, {})

        # Get cell voltage max and min
        cell_voltage_max = battery_data.get("battery_cell_voltage_max")
        cell_voltage_min = battery_data.get("battery_cell_voltage_min")

        if cell_voltage_max is None or cell_voltage_min is None:
            return None

        # Calculate absolute difference (delta)
        voltage_delta = abs(cell_voltage_max - cell_voltage_min)

        return float(voltage_delta)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device_exists = (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._serial]
        )
        battery_exists = device_exists and self._battery_key in self.coordinator.data["devices"][self._serial].get(
            "batteries", {}
        )
        return battery_exists
