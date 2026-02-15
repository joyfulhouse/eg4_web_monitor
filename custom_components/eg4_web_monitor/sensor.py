"""Sensor platform for EG4 Web Monitor integration."""

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.sensor import SensorEntity
else:
    from homeassistant.components.sensor import SensorEntity  # type: ignore[assignment]

from . import EG4ConfigEntry
from .base_entity import (
    EG4BaseBatterySensor,
    EG4BaseSensor,
    EG4BatteryBankEntity,
    EG4StationEntity,
)
from .const import (
    DISCHARGE_RECOVERY_SENSORS,
    SENSOR_TYPES,
    SPLIT_PHASE_ONLY_SENSORS,
    STATION_SENSOR_TYPES,
    THREE_PHASE_ONLY_SENSORS,
    VOLT_WATT_SENSORS,
)
from .coordinator import EG4DataUpdateCoordinator
from .coordinator_mappings import GRIDBOSS_SMART_PORT_POWER_KEYS

_LOGGER = logging.getLogger(__name__)


def _should_create_sensor(sensor_key: str, features: dict[str, Any] | None) -> bool:
    """Determine if a sensor should be created based on device features.

    This function implements feature-based sensor filtering to avoid creating
    sensors for capabilities that the inverter doesn't support.

    Args:
        sensor_key: The sensor key to check
        features: Device features dictionary from feature detection, or None

    Returns:
        True if the sensor should be created, False if it should be skipped
    """
    # If no features detected, create all sensors (conservative fallback)
    if not features:
        return True

    # Check split-phase sensors (only for EG4_OFFGRID series)
    if sensor_key in SPLIT_PHASE_ONLY_SENSORS:
        return bool(features.get("supports_split_phase", True))

    # Check three-phase sensors (only for EG4_HYBRID, LXP)
    if sensor_key in THREE_PHASE_ONLY_SENSORS:
        return bool(features.get("supports_three_phase", True))

    # Check discharge recovery sensors (only for EG4_OFFGRID series)
    if sensor_key in DISCHARGE_RECOVERY_SENSORS:
        return bool(features.get("supports_discharge_recovery_hysteresis", True))

    # Check Volt-Watt sensors (only for EG4_HYBRID, LXP)
    if sensor_key in VOLT_WATT_SENSORS:
        return bool(features.get("supports_volt_watt_curve", True))

    # Default: create the sensor
    return True


# Silver tier requirement: Specify parallel update count
# Limit concurrent sensor updates to prevent overwhelming the coordinator
MAX_PARALLEL_UPDATES = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor sensor entities.

    Entity registration is split into three phases to ensure proper device hierarchy:
    1. Phase 1: Station + parallel group entities (root devices, no via_device)
    2. Phase 2: Inverter, gridboss, and battery bank entities (via_device → parallel group)
    3. Phase 3: Individual battery entities (via_device → battery bank)

    This ordering prevents HA warning about non-existing via_device references.
    See: https://github.com/joyfulhouse/eg4_web_monitor/issues/81
    See: https://github.com/joyfulhouse/eg4_web_monitor/issues/154
    """
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    # Phase 1 entities: root devices (station, parallel groups) - no via_device
    phase1_entities: list[SensorEntity] = []
    # Phase 2 entities: inverters, gridboss, battery banks (via_device → parallel group)
    phase2_entities: list[SensorEntity] = []
    # Phase 3 entities: individual batteries (via_device → battery bank)
    phase3_entities: list[SensorEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for sensor setup")
        return

    # Create station sensors if station data is available
    if "station" in coordinator.data:
        phase1_entities.extend(_create_station_sensors(coordinator))
        station_count = len(
            [e for e in phase1_entities if isinstance(e, EG4StationSensor)]
        )
        _LOGGER.info("Created %d station sensors", station_count)

    # Skip device sensors if no devices data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data available for sensor setup, only creating station sensors"
        )
        if phase1_entities:
            async_add_entities(phase1_entities, True)
        return

    # Create sensor entities for each device
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        battery_count = len(device_data.get("batteries", {}))

        _LOGGER.debug(
            "Sensor setup for device %s: type=%s, batteries=%d",
            serial,
            device_type,
            battery_count,
        )

        if device_type == "inverter":
            inverter_entities, battery_entities = _create_inverter_sensors(
                coordinator, serial, device_data
            )
            _LOGGER.debug(
                "Created %d inverter/battery-bank entities and %d individual battery "
                "entities for inverter %s",
                len(inverter_entities),
                len(battery_entities),
                serial,
            )
            phase2_entities.extend(inverter_entities)
            phase3_entities.extend(battery_entities)
        elif device_type == "parallel_group":
            phase1_entities.extend(
                _create_simple_device_sensors(
                    coordinator, serial, device_data, device_type
                )
            )
        elif device_type == "gridboss":
            phase2_entities.extend(
                _create_simple_device_sensors(
                    coordinator, serial, device_data, device_type
                )
            )
        else:
            _LOGGER.warning(
                "Unknown device type '%s' for device %s", device_type, serial
            )

    # Phase 1: Register root devices (station + parallel groups)
    if phase1_entities:
        async_add_entities(phase1_entities, True)
        _LOGGER.info(
            "Phase 1: Added %d root entities (station, parallel groups)",
            len(phase1_entities),
        )

    # Phase 2: Register child devices (inverters, gridboss, battery banks)
    # These reference parallel groups via via_device
    if phase2_entities:
        async_add_entities(phase2_entities, True)
        _LOGGER.info(
            "Phase 2: Added %d device entities (inverters, gridboss, battery banks)",
            len(phase2_entities),
        )

    # Phase 3: Register individual battery entities (reference battery bank via via_device)
    if phase3_entities:
        async_add_entities(phase3_entities, True)
        _LOGGER.info(
            "Phase 3: Added %d individual battery sensor entities", len(phase3_entities)
        )

    if not phase1_entities and not phase2_entities and not phase3_entities:
        _LOGGER.warning("No sensor entities created")

    # Track known battery sensor keys for late registration.
    # Individual batteries are discovered only when real Modbus reads complete
    # (after the static-data first refresh). Additionally, some sensor keys
    # (e.g. discharge_rate) may only appear once transport data is available,
    # so we track at the sensor-key level to catch new keys on known batteries.
    known_battery_sensor_keys: dict[str, set[str]] = {}
    for serial, device_data in coordinator.data.get("devices", {}).items():
        for battery_key, battery_sensors in device_data.get("batteries", {}).items():
            known_battery_sensor_keys[battery_key] = {
                k for k in battery_sensors if k in SENSOR_TYPES
            }

    @callback
    def _async_discover_new_batteries() -> None:
        """Register battery entities that appear after initial setup."""
        if not coordinator.data or "devices" not in coordinator.data:
            return
        new_entities: list[SensorEntity] = []
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            for battery_key, battery_sensors in device_data.get(
                "batteries", {}
            ).items():
                known_keys = known_battery_sensor_keys.get(battery_key, set())
                for sensor_key in battery_sensors:
                    if sensor_key in SENSOR_TYPES and sensor_key not in known_keys:
                        known_keys.add(sensor_key)
                        new_entities.append(
                            EG4BatterySensor(
                                coordinator, serial, battery_key, sensor_key
                            )
                        )
                known_battery_sensor_keys[battery_key] = known_keys
        if new_entities:
            _LOGGER.info(
                "Late battery registration: adding %d entities for new batteries/sensors",
                len(new_entities),
            )
            async_add_entities(new_entities, True)

    entry.async_on_unload(coordinator.async_add_listener(_async_discover_new_batteries))

    # Track known smart port sensor keys for late registration.
    # Smart port power keys are excluded from static entity creation because
    # port statuses are unknown until the first real Modbus/API read. Once
    # _filter_unused_smart_port_sensors() populates keys for active ports,
    # this listener registers the corresponding entities.
    known_smart_port_keys: dict[str, set[str]] = {}
    for serial, device_data in coordinator.data.get("devices", {}).items():
        if device_data.get("type") == "gridboss":
            known_smart_port_keys[serial] = {
                k
                for k in device_data.get("sensors", {})
                if k in GRIDBOSS_SMART_PORT_POWER_KEYS
            }

    @callback
    def _async_discover_smart_port_sensors() -> None:
        """Register smart port entities that appear after initial setup."""
        if not coordinator.data or "devices" not in coordinator.data:
            return
        new_entities: list[SensorEntity] = []
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "gridboss":
                continue
            known = known_smart_port_keys.setdefault(serial, set())
            for sensor_key in device_data.get("sensors", {}):
                if sensor_key not in GRIDBOSS_SMART_PORT_POWER_KEYS:
                    continue
                if sensor_key in known:
                    continue
                known.add(sensor_key)
                if sensor_key in SENSOR_TYPES:
                    new_entities.append(
                        EG4InverterSensor(
                            coordinator=coordinator,
                            serial=serial,
                            sensor_key=sensor_key,
                            device_type="gridboss",
                        )
                    )
        if new_entities:
            _LOGGER.info(
                "Late smart port registration: adding %d entities", len(new_entities)
            )
            async_add_entities(new_entities, True)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_discover_smart_port_sensors)
    )


def _create_inverter_sensors(
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: dict[str, Any]
) -> tuple[list[SensorEntity], list[SensorEntity]]:
    """Create sensor entities for an inverter device.

    Returns a tuple of two lists:
    - First list: Inverter and battery bank entities (phase 2)
    - Second list: Individual battery entities (phase 3)

    This separation ensures battery bank devices are registered before individual
    batteries that reference them via via_device.
    """
    # Inverter sensors and battery bank sensors (phase 2)
    inverter_entities: list[SensorEntity] = []
    # Individual battery sensors (phase 3 - reference battery bank via via_device)
    battery_entities: list[SensorEntity] = []

    # Get device features for capability-based filtering
    features = device_data.get("features")
    skipped_sensors: list[str] = []

    # Create main inverter sensors (excluding battery_bank sensors)
    for sensor_key in device_data.get("sensors", {}):
        if sensor_key in SENSOR_TYPES:
            # Skip battery_bank sensors - they'll be created separately
            if not sensor_key.startswith("battery_bank_"):
                # Check if sensor should be created based on device features
                if _should_create_sensor(sensor_key, features):
                    inverter_entities.append(
                        EG4InverterSensor(
                            coordinator=coordinator,
                            serial=serial,
                            sensor_key=sensor_key,
                            device_type="inverter",
                        )
                    )
                else:
                    skipped_sensors.append(sensor_key)

    if skipped_sensors:
        _LOGGER.debug(
            "Skipped %d sensors for %s based on feature detection: %s",
            len(skipped_sensors),
            serial,
            skipped_sensors,
        )

    # Create battery bank sensors (separate device, phase 2)
    # Battery bank is a parent device for individual batteries
    battery_bank_sensor_count = 0
    for sensor_key in device_data.get("sensors", {}):
        if sensor_key.startswith("battery_bank_") and sensor_key in SENSOR_TYPES:
            inverter_entities.append(
                EG4BatteryBankSensor(
                    coordinator=coordinator,
                    serial=serial,
                    sensor_key=sensor_key,
                )
            )
            battery_bank_sensor_count += 1

    if battery_bank_sensor_count > 0:
        _LOGGER.debug(
            "Created %d battery bank sensors for %s", battery_bank_sensor_count, serial
        )

    # Create individual battery sensors (phase 3 - these reference battery bank)
    batteries = device_data.get("batteries", {})
    _LOGGER.debug(
        "Creating battery sensors for %s: found %d batteries",
        serial,
        len(batteries),
    )

    for battery_key, battery_sensors in batteries.items():
        for sensor_key in battery_sensors:
            if sensor_key in SENSOR_TYPES:
                battery_entities.append(
                    EG4BatterySensor(
                        coordinator=coordinator,
                        serial=serial,
                        battery_key=battery_key,
                        sensor_key=sensor_key,
                    )
                )

    _LOGGER.debug(
        "Total entities for inverter %s: %d inverter/battery-bank + %d individual battery",
        serial,
        len(inverter_entities),
        len(battery_entities),
    )
    return inverter_entities, battery_entities


def _create_simple_device_sensors(
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    device_data: dict[str, Any],
    device_type: str,
) -> list[SensorEntity]:
    """Create sensor entities for a GridBOSS or Parallel Group device."""
    return [
        EG4InverterSensor(
            coordinator=coordinator,
            serial=serial,
            sensor_key=sensor_key,
            device_type=device_type,
        )
        for sensor_key in device_data.get("sensors", {})
        if sensor_key in SENSOR_TYPES
    ]


class EG4InverterSensor(EG4BaseSensor, SensorEntity):
    """Representation of an EG4 Web Monitor sensor.

    Inherits common functionality from EG4BaseSensor including:
    - Sensor configuration from SENSOR_TYPES
    - Display precision handling
    - Monotonic state tracking for lifetime sensors
    - Diagnostic entity category detection
    """

    pass  # All functionality provided by EG4BaseSensor


class EG4BatteryBankSensor(EG4BatteryBankEntity, SensorEntity):
    """Representation of an EG4 Battery Bank sensor (aggregate of all batteries).

    Inherits common functionality from EG4BatteryBankEntity including:
    - Sensor configuration from SENSOR_TYPES
    - Battery bank device info
    - Availability checking
    """

    pass  # All functionality provided by EG4BatteryBankEntity


class EG4BatterySensor(EG4BaseBatterySensor, SensorEntity):
    """Representation of an EG4 Battery sensor.

    Inherits common functionality from EG4BaseBatterySensor including:
    - Sensor configuration from SENSOR_TYPES
    - Display precision handling
    - Monotonic state tracking for lifetime sensors
    - Battery-specific entity category detection
    """

    pass  # All functionality provided by EG4BaseBatterySensor


def _create_station_sensors(
    coordinator: EG4DataUpdateCoordinator,
) -> list[SensorEntity]:
    """Create sensor entities for station/plant configuration."""
    entities: list[SensorEntity] = []

    for sensor_key in STATION_SENSOR_TYPES:
        entities.append(
            EG4StationSensor(
                coordinator=coordinator,
                sensor_key=sensor_key,
            )
        )

    _LOGGER.debug("Created %d station sensors", len(entities))
    return entities


class EG4StationSensor(EG4StationEntity, SensorEntity):
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
        entity_category = sensor_config.get("entity_category")
        if entity_category:
            self._attr_entity_category = EntityCategory(entity_category)

        device_class = sensor_config.get("device_class")
        if device_class:
            self._attr_device_class = SensorDeviceClass(device_class)

        state_class = sensor_config.get("state_class")
        if state_class:
            self._attr_state_class = SensorStateClass(state_class)

        if uom := sensor_config.get("unit_of_measurement"):
            self._attr_native_unit_of_measurement = uom

        # Build unique ID
        self._attr_unique_id = f"station_{coordinator.plant_id}_{sensor_key}"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "station" not in self.coordinator.data:
            return None

        station_data = self.coordinator.data["station"]

        # Map sensor keys to station data fields
        if self._sensor_key == "station_name":
            return station_data.get("name")
        if self._sensor_key == "station_country":
            return station_data.get("country")
        if self._sensor_key == "station_timezone":
            return station_data.get("timezone")
        if self._sensor_key == "station_create_date":
            return station_data.get("createDate")
        if self._sensor_key == "station_address":
            return station_data.get("address")
        if self._sensor_key == "station_last_polled":
            return station_data.get("station_last_polled")
        if self._sensor_key == "api_request_rate":
            return station_data.get("api_request_rate")
        if self._sensor_key == "api_peak_request_rate":
            return station_data.get("api_peak_request_rate")
        if self._sensor_key == "api_requests_today":
            return station_data.get("api_requests_today")

        return None
