"""Sensor platform for EG4 Web Monitor integration."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.sensor import (
        SensorEntity,
    )
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.sensor import (  # type: ignore[assignment]
        SensorEntity,
    )
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from . import EG4ConfigEntry
from .const import DOMAIN, SENSOR_TYPES, STATION_SENSOR_TYPES
from .coordinator import EG4DataUpdateCoordinator
from .utils import clean_model_name

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
# Limit concurrent sensor updates to prevent overwhelming the coordinator
MAX_PARALLEL_UPDATES = 5

# Sensors that should never decrease (lifetime values)
# All other total_increasing sensors can reset at date boundaries
LIFETIME_SENSORS = {
    "total_energy",
    "yield_lifetime",
    "discharging_lifetime",
    "charging_lifetime",
    "consumption_lifetime",
    "grid_export_lifetime",
    "grid_import_lifetime",
    "cycle_count",  # Battery cycle count is lifetime
}


def _get_current_date(coordinator: EG4DataUpdateCoordinator) -> str | None:
    """Get current date in station's timezone as YYYY-MM-DD string.

    Returns None if timezone cannot be determined, falling back to allowing resets.
    """
    try:
        # Try to get timezone from station data
        tz_str = None
        if coordinator.data and "station" in coordinator.data:
            tz_str = coordinator.data["station"].get("timezone")

        # Parse timezone string like "GMT -8" or "GMT+8"
        if tz_str and "GMT" in tz_str:
            offset_str = tz_str.replace("GMT", "").strip()
            if offset_str:
                # Parse offset (e.g., "-8" or "+8")
                offset_hours = int(offset_str)
                # Create timezone with offset
                from datetime import timedelta, timezone

                tz = timezone(timedelta(hours=offset_hours))
                return datetime.now(tz).strftime("%Y-%m-%d")

        # Fallback to UTC if timezone not available
        return datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d")
    except Exception as e:
        _LOGGER.debug("Error getting current date in timezone: %s", e)
        # Return None to allow resets when we can't determine date
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor sensor entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []

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

        _LOGGER.debug(
            f"Sensor setup for device {serial}: type={device_type}, "
            f"has batteries={len(device_data.get('batteries', {}))} battery keys"
        )

        if device_type == "inverter":
            inverter_entities = _create_inverter_sensors(
                coordinator, serial, device_data
            )
            _LOGGER.debug(
                f"Created {len(inverter_entities)} entities for inverter {serial}"
            )
            entities.extend(inverter_entities)
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
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: dict[str, Any]
) -> list[SensorEntity]:
    """Create sensor entities for an inverter device."""
    entities: list[SensorEntity] = []

    # Create main inverter sensors (excluding battery_bank sensors)
    for sensor_key in device_data.get("sensors", {}):
        if sensor_key in SENSOR_TYPES:
            # Skip battery_bank sensors - they'll be created separately for battery bank device
            if not sensor_key.startswith("battery_bank_"):
                entities.append(
                    EG4InverterSensor(
                        coordinator=coordinator,
                        serial=serial,
                        sensor_key=sensor_key,
                        device_type="inverter",
                    )
                )

    # Create battery bank sensors (separate device)
    battery_bank_sensor_count = 0
    for sensor_key in device_data.get("sensors", {}):
        if sensor_key.startswith("battery_bank_") and sensor_key in SENSOR_TYPES:
            entities.append(
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
        # Log the battery bank device info that will be used
        battery_bank_device_info = coordinator.get_battery_bank_device_info(serial)
        if battery_bank_device_info:
            _LOGGER.debug(
                "Battery bank device_info for %s: identifiers=%s, via_device=%s",
                serial,
                battery_bank_device_info.get("identifiers"),
                battery_bank_device_info.get("via_device"),
            )
        else:
            _LOGGER.warning(
                "No battery_bank device_info returned for inverter %s", serial
            )

    # Create individual battery sensors
    batteries = device_data.get("batteries", {})
    _LOGGER.debug(
        "Creating battery sensors for %s: found %d batteries",
        serial,
        len(batteries),
    )

    for battery_key, battery_sensors in batteries.items():
        _LOGGER.debug(
            "Processing battery %s for %s: %d sensors",
            battery_key,
            serial,
            len(battery_sensors),
        )

        # Log device info that will be used for this battery
        battery_device_info = coordinator.get_battery_device_info(serial, battery_key)
        if battery_device_info:
            _LOGGER.debug(
                "Battery %s device_info: identifiers=%s, via_device=%s",
                battery_key,
                battery_device_info.get("identifiers"),
                battery_device_info.get("via_device"),
            )
        else:
            _LOGGER.warning(
                "No device_info returned for battery %s (inverter %s)",
                battery_key,
                serial,
            )

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

    _LOGGER.debug(f"Total entities created for inverter {serial}: {len(entities)}")

    return entities


def _create_gridboss_sensors(
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: dict[str, Any]
) -> list[SensorEntity]:
    """Create sensor entities for a GridBOSS device."""
    entities: list[SensorEntity] = []

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
    coordinator: EG4DataUpdateCoordinator, serial: str, device_data: dict[str, Any]
) -> list[SensorEntity]:
    """Create sensor entities for a Parallel Group device."""
    entities: list[SensorEntity] = []

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
        self._sensor_config: dict[str, Any] = cast(
            "dict[str, Any]", SENSOR_TYPES.get(sensor_key, {})
        )

        # Monotonic state tracking for total_increasing sensors
        self._last_valid_state: float | None = None
        self._last_update_date: str | None = (
            None  # Track date for daily reset detection
        )

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
            model_clean = clean_model_name(model, use_underscores=True)
            self._attr_entity_id = f"sensor.eg4_{model_clean}_{serial}_{sensor_key}"

        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")

        # Set display precision from config, or default to 2 for voltage sensors
        if "suggested_display_precision" in self._sensor_config:
            self._attr_suggested_display_precision = self._sensor_config[
                "suggested_display_precision"
            ]
        elif self._attr_device_class == "voltage":
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
                current_date = _get_current_date(self.coordinator)

                # Check if this is a lifetime sensor (never resets)
                is_lifetime = self._sensor_key in LIFETIME_SENSORS

                # Detect date boundary crossing for non-lifetime sensors
                date_changed = False
                if not is_lifetime and current_date and self._last_update_date:
                    date_changed = current_date != self._last_update_date

                # If date changed, force reset to 0 for non-lifetime sensors
                # This prevents API stale data anomalies at date boundary
                if date_changed:
                    _LOGGER.info(
                        "Sensor %s: Date boundary crossed from %s to %s, "
                        "forcing reset from %.2f to 0.0 (API reported %.2f)",
                        self._attr_unique_id,
                        self._last_update_date,
                        current_date,
                        self._last_valid_state if self._last_valid_state else 0,
                        current_value,
                    )
                    self._last_valid_state = 0.0
                    self._last_update_date = current_date
                    return 0.0

                # If we have a previous valid state, ensure we never decrease (for lifetime)
                # or only decrease if value went to 0 (likely a reset)
                if (
                    self._last_valid_state is not None
                    and current_value < self._last_valid_state
                ):
                    # Allow reset to 0 for non-lifetime sensors (manual/API reset)
                    if not is_lifetime and current_value == 0:
                        _LOGGER.info(
                            "Sensor %s: Allowing reset to 0 for non-lifetime sensor",
                            self._attr_unique_id,
                        )
                        self._last_valid_state = current_value
                        self._last_update_date = current_date
                        return current_value

                    # Prevent decrease for lifetime sensors or non-zero decreases
                    _LOGGER.debug(
                        "Sensor %s: Preventing state decrease from %.2f to %.2f, "
                        "maintaining %.2f (lifetime=%s)",
                        self._attr_unique_id,
                        self._last_valid_state,
                        current_value,
                        self._last_valid_state,
                        is_lifetime,
                    )
                    return self._last_valid_state

                # Update last valid state and date, return current value
                self._last_valid_state = current_value
                self._last_update_date = current_date
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


class EG4BatteryBankSensor(CoordinatorEntity, SensorEntity):
    """Representation of an EG4 Battery Bank sensor (aggregate of all batteries)."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
    ) -> None:
        """Initialize the battery bank sensor."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._sensor_key = sensor_key

        # Get sensor configuration
        self._sensor_config: dict[str, Any] = cast(
            "dict[str, Any]", SENSOR_TYPES.get(sensor_key, {})
        )

        # Generate unique ID
        self._attr_unique_id = f"{serial}_battery_bank_{sensor_key}"

        # Set entity attributes
        device_data = self.coordinator.data["devices"].get(serial, {})
        model = device_data.get("model", "Unknown")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = self._sensor_config.get("name", sensor_key)

        # Keep entity_id for backwards compatibility
        model_clean = clean_model_name(model, use_underscores=True)
        self._attr_entity_id = (
            f"sensor.eg4_{model_clean}_{serial}_battery_bank_{sensor_key}"
        )

        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")

        # Set entity category
        if self._sensor_config.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for battery bank."""
        device_info = self.coordinator.get_battery_bank_device_info(self._serial)
        if device_info is None:
            # Fallback device info if coordinator doesn't have it yet
            return {
                "identifiers": {(DOMAIN, f"{self._serial}_battery_bank")},
                "name": f"Battery Bank ({self._serial})",
                "manufacturer": "EG4 Electronics",
                "model": "Battery Bank",
                "via_device": (DOMAIN, self._serial),
            }
        return device_info

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        device_exists = (
            self.coordinator.data
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
        )

        # Battery bank sensor is available if device exists and has battery bank data
        battery_bank_exists = (
            device_exists
            and self._sensor_key
            in self.coordinator.data["devices"][self._serial].get("sensors", {})
        )

        return bool(battery_bank_exists)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        device_data = self.coordinator.data["devices"].get(self._serial, {})
        sensors = device_data.get("sensors", {})
        return sensors.get(self._sensor_key)


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
        self._sensor_config: dict[str, Any] = cast(
            "dict[str, Any]", SENSOR_TYPES.get(sensor_key, {})
        )

        # Monotonic state tracking for total_increasing sensors
        self._last_valid_state: float | None = None
        self._last_update_date: str | None = (
            None  # Track date for daily reset detection
        )

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
        model_clean = clean_model_name(model, use_underscores=True)
        self._attr_entity_id = (
            f"sensor.eg4_{model_clean}_{serial}_battery_{clean_battery_id}_{sensor_key}"
        )

        # Set sensor properties from configuration
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        self._attr_icon = self._sensor_config.get("icon")

        # Set display precision from config, or default to 2 for voltage sensors
        if "suggested_display_precision" in self._sensor_config:
            self._attr_suggested_display_precision = self._sensor_config[
                "suggested_display_precision"
            ]
        elif self._attr_device_class == "voltage":
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
        if (
            sensor_key in diagnostic_battery_sensors
            or self._sensor_config.get("entity_category") == "diagnostic"
        ):
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
                current_date = _get_current_date(self.coordinator)

                # Check if this is a lifetime sensor (never resets)
                is_lifetime = self._sensor_key in LIFETIME_SENSORS

                # Detect date boundary crossing for non-lifetime sensors
                date_changed = False
                if not is_lifetime and current_date and self._last_update_date:
                    date_changed = current_date != self._last_update_date

                # If date changed, force reset to 0 for non-lifetime sensors
                # This prevents API stale data anomalies at date boundary
                if date_changed:
                    _LOGGER.info(
                        "Sensor %s: Date boundary crossed from %s to %s, "
                        "forcing reset from %.2f to 0.0 (API reported %.2f)",
                        self._attr_unique_id,
                        self._last_update_date,
                        current_date,
                        self._last_valid_state if self._last_valid_state else 0,
                        current_value,
                    )
                    self._last_valid_state = 0.0
                    self._last_update_date = current_date
                    return 0.0

                # If we have a previous valid state, ensure we never decrease (for lifetime)
                # or only decrease if value went to 0 (likely a reset)
                if (
                    self._last_valid_state is not None
                    and current_value < self._last_valid_state
                ):
                    # Allow reset to 0 for non-lifetime sensors (manual/API reset)
                    if not is_lifetime and current_value == 0:
                        _LOGGER.info(
                            "Sensor %s: Allowing reset to 0 for non-lifetime sensor",
                            self._attr_unique_id,
                        )
                        self._last_valid_state = current_value
                        self._last_update_date = current_date
                        return current_value

                    # Prevent decrease for lifetime sensors or non-zero decreases
                    _LOGGER.debug(
                        "Sensor %s: Preventing state decrease from %.2f to %.2f, "
                        "maintaining %.2f (lifetime=%s)",
                        self._attr_unique_id,
                        self._last_valid_state,
                        current_value,
                        self._last_valid_state,
                        is_lifetime,
                    )
                    return self._last_valid_state

                # Update last valid state and date, return current value
                self._last_valid_state = current_value
                self._last_update_date = current_date
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
        self._attr_entity_category = sensor_config.get("entity_category")

        if "device_class" in sensor_config:
            self._attr_device_class = sensor_config["device_class"]

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
        if self._sensor_key == "station_country":
            return station_data.get("country")
        if self._sensor_key == "station_timezone":
            # The API returns display text like "GMT -8"
            return station_data.get("timezone")
        if self._sensor_key == "station_create_date":
            return station_data.get("createDate")
        if self._sensor_key == "station_address":
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
