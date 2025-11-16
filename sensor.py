"""Sensor platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

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
from .const import DOMAIN, SENSOR_TYPES, STATION_SENSOR_TYPES
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

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for sensor setup")
        return

    # Create station sensors if station data is available
    if "station" in coordinator.data:
        entities.extend(_create_station_sensors(coordinator))
        _LOGGER.info(
            "Created %d station sensors",
            len([e for e in entities if isinstance(e, EG4StationSensor)]),
        )

    # Skip device sensors if no devices data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data available for sensor setup, only creating station sensors"
        )
        if entities:
            async_add_entities(entities, True)
        return

    # Create sensor entities for each device
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")

        if device_type == "inverter":
            entities.extend(_create_inverter_sensors(coordinator, serial, device_data))
        elif device_type == "gridboss":
            entities.extend(_create_gridboss_sensors(coordinator, serial, device_data))
        elif device_type == "parallel_group":
            entities.extend(
                _create_parallel_group_sensors(coordinator, serial, device_data)
            )
        else:
            _LOGGER.warning(
                "Unknown device type '%s' for device %s", device_type, serial
            )

    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Added %d sensor entities", len(entities))
    else:
        _LOGGER.warning("No sensor entities created")


def _create_inverter_sensors(
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: Dict[str, Any]
) -> List[SensorEntity]:
    """Create sensor entities for an inverter device."""
    entities: List[SensorEntity] = []

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
    entities: List[SensorEntity] = []

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
    entities: List[SensorEntity] = []

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


class EG4InverterSensor(CoordinatorEntity, SensorEntity):
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

        # Get sensor configuration - cast needed because const dict .get() returns object
        self._sensor_config: Dict[str, Any] = cast(
            Dict[str, Any], SENSOR_TYPES.get(sensor_key, {})
        )

        # Monotonic state tracking for total_increasing sensors
        self._last_valid_state: Optional[float] = None

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
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_device_info(self._serial)
        return device_info if device_info else {}

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None

        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None

        sensors = device_data.get("sensors", {})
        raw_value = sensors.get(self._sensor_key)

        # Apply monotonic state tracking for total_increasing sensors
        if self._attr_state_class == "total_increasing" and raw_value is not None:
            try:
                current_value = float(raw_value)

                # If we have a previous valid state, ensure we never decrease
                if self._last_valid_state is not None:
                    if current_value < self._last_valid_state:
                        _LOGGER.debug(
                            "Sensor %s: Preventing state decrease from %.2f to %.2f, "
                            "maintaining %.2f",
                            self._attr_unique_id,
                            self._last_valid_state,
                            current_value,
                            self._last_valid_state,
                        )
                        return self._last_valid_state

                # Update last valid state and return current value
                self._last_valid_state = current_value
                return current_value
            except (ValueError, TypeError):
                # If conversion fails, return raw value
                return raw_value

        return raw_value

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
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._battery_key = battery_key
        self._sensor_key = sensor_key

        # Get sensor configuration - cast needed because const dict .get() returns object
        self._sensor_config: Dict[str, Any] = cast(
            Dict[str, Any], SENSOR_TYPES.get(sensor_key, {})
        )

        # Monotonic state tracking for total_increasing sensors
        self._last_valid_state: Optional[float] = None

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
        self._attr_entity_id = (
            f"sensor.eg4_{model_clean}_{serial}_battery_{clean_battery_id}_{sensor_key}"
        )

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
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_battery_device_info(
            self._serial, self._battery_key
        )
        return device_info if device_info else {}

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
        raw_value = battery_data.get(self._sensor_key)

        # Apply monotonic state tracking for total_increasing sensors
        if self._attr_state_class == "total_increasing" and raw_value is not None:
            try:
                current_value = float(raw_value)

                # If we have a previous valid state, ensure we never decrease
                if self._last_valid_state is not None:
                    if current_value < self._last_valid_state:
                        _LOGGER.debug(
                            "Sensor %s: Preventing state decrease from %.2f to %.2f, "
                            "maintaining %.2f",
                            self._attr_unique_id,
                            self._last_valid_state,
                            current_value,
                            self._last_valid_state,
                        )
                        return self._last_valid_state

                # Update last valid state and return current value
                self._last_valid_state = current_value
                return current_value
            except (ValueError, TypeError):
                # If conversion fails, return raw value
                return raw_value

        return raw_value

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
        battery_exists = device_exists and self._battery_key in self.coordinator.data[
            "devices"
        ][self._serial].get("batteries", {})
        return battery_exists


class EG4BatteryCellVoltageDeltaSensor(CoordinatorEntity, SensorEntity):
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
        self._attr_entity_id = (
            f"sensor.battery_{serial_clean}_{clean_battery_id}_cell_voltage_delta"
        )

        # Sensor configuration
        self._attr_native_unit_of_measurement = "V"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-sync"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_suggested_display_precision = 3

        # Device registry
        self._attr_device_info = cast(
            DeviceInfo,
            {
                "identifiers": {(DOMAIN, f"{serial}_{battery_key}")},
            },
        )

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
        battery_exists = device_exists and self._battery_key in self.coordinator.data[
            "devices"
        ][self._serial].get("batteries", {})
        return battery_exists


def _create_station_sensors(
    coordinator: EG4DataUpdateCoordinator,
) -> List[SensorEntity]:
    """Create sensor entities for station/plant configuration."""
    entities: List[SensorEntity] = []

    for sensor_key in STATION_SENSOR_TYPES:
        entities.append(
            EG4StationSensor(
                coordinator=coordinator,
                sensor_key=sensor_key,
            )
        )

    _LOGGER.debug("Created %d station sensors", len(entities))
    return entities


class EG4StationSensor(CoordinatorEntity[EG4DataUpdateCoordinator], SensorEntity):
    """Sensor entity for station/plant configuration data."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        sensor_key: str,
    ) -> None:
        """Initialize the station sensor."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._attr_has_entity_name = True

        # Get sensor configuration
        sensor_config = STATION_SENSOR_TYPES[sensor_key]
        self._attr_name = sensor_config["name"]
        self._attr_icon = sensor_config.get("icon")
        # Type ignore for entity_category - config dict returns Any
        self._attr_entity_category = sensor_config.get("entity_category")  # type: ignore[assignment]

        if "device_class" in sensor_config:
            # Type ignore for device_class - config dict returns Any
            self._attr_device_class = sensor_config["device_class"]  # type: ignore[assignment]

        # Build unique ID
        self._attr_unique_id = f"station_{coordinator.plant_id}_{sensor_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_station_device_info()
        return device_info if device_info else {}

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "station" not in self.coordinator.data:
            return None

        station_data = self.coordinator.data["station"]

        # Map sensor keys to station data fields
        if self._sensor_key == "station_name":
            return station_data.get("name")
        elif self._sensor_key == "station_country":
            return station_data.get("country")
        elif self._sensor_key == "station_timezone":
            # The API returns display text like "GMT -8"
            return station_data.get("timezone")
        elif self._sensor_key == "station_create_date":
            return station_data.get("createDate")
        elif self._sensor_key == "station_address":
            return station_data.get("address")

        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "station" in self.coordinator.data
        )
