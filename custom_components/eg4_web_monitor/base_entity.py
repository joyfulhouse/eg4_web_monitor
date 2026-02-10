"""Base entity classes for EG4 Web Monitor integration.

This module provides base classes that eliminate code duplication across platforms.
All entity classes should inherit from these bases to ensure consistent behavior.
"""

import asyncio
from contextlib import contextmanager
import logging
from typing import TYPE_CHECKING, Any, Generator, cast

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.switch import SwitchEntity  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from .const import (
    DIAGNOSTIC_BATTERY_SENSOR_KEYS,
    DIAGNOSTIC_DEVICE_SENSOR_KEYS,
    DOMAIN,
    ENTITY_PREFIX,
    MANUFACTURER,
    SENSOR_TYPES,
)
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    clean_model_name,
    generate_entity_id,
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)


class EG4DeviceEntity(CoordinatorEntity):
    """Base class for all EG4 device entities.

    This class provides common functionality for all EG4 device entities including:
    - Coordinator integration
    - Device information lookup
    - Availability checking
    - Serial number management

    Attributes:
        coordinator: The data update coordinator managing device data.
        _serial: The device serial number.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base device entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._serial = serial

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for entity grouping.

        Returns:
            DeviceInfo dictionary containing device identifiers, name, model, etc.
            Returns None if device info cannot be retrieved.
        """
        return self.coordinator.get_device_info(self._serial)

    @property
    def available(self) -> bool:
        """Return if entity is available.

        An entity is considered available if:
        - The coordinator has valid data
        - The device exists in the coordinator's device list

        Returns:
            True if entity is available, False otherwise.
        """
        if self.coordinator.data and "devices" in self.coordinator.data:
            return self._serial in self.coordinator.data["devices"]
        return False


class EG4BatteryEntity(CoordinatorEntity):
    """Base class for all EG4 battery entities.

    This class provides common functionality for individual battery entities including:
    - Parent device tracking
    - Battery-specific device information
    - Availability checking for battery presence

    Attributes:
        coordinator: The data update coordinator managing device data.
        _parent_serial: The serial number of the parent inverter.
        _battery_key: The unique key identifying this battery.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        parent_serial: str,
        battery_key: str,
    ) -> None:
        """Initialize the base battery entity.

        Args:
            coordinator: The data update coordinator.
            parent_serial: The serial number of the parent inverter device.
            battery_key: The unique key identifying this battery.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._parent_serial = parent_serial
        self._battery_key = battery_key

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for battery entity grouping.

        Returns:
            DeviceInfo dictionary containing battery device identifiers.
            Returns None if battery device info cannot be retrieved.
        """
        return self.coordinator.get_battery_device_info(
            self._parent_serial, self._battery_key
        )

    @property
    def available(self) -> bool:
        """Return if battery entity is available.

        A battery entity is considered available if:
        - The coordinator has valid data
        - The parent device exists
        - The specific battery exists in the parent device's battery list

        Returns:
            True if battery entity is available, False otherwise.
        """
        if self.coordinator.data and "devices" in self.coordinator.data:
            parent_device = self.coordinator.data["devices"].get(
                self._parent_serial, {}
            )
            if parent_device and "batteries" in parent_device:
                return self._battery_key in parent_device["batteries"]
        return False


class EG4StationEntity(CoordinatorEntity):
    """Base class for all EG4 station/plant entities.

    This class provides common functionality for station-level entities including:
    - Station device information
    - Availability checking for station data

    Attributes:
        coordinator: The data update coordinator managing station data.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator) -> None:
        """Initialize the base station entity.

        Args:
            coordinator: The data update coordinator.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for station entity grouping.

        Returns:
            DeviceInfo dictionary containing station identifiers.
            Returns None if station device info cannot be retrieved.
        """
        return self.coordinator.get_station_device_info()

    @property
    def available(self) -> bool:
        """Return if station entity is available.

        A station entity is considered available if:
        - The last coordinator update was successful
        - The coordinator has valid data
        - Station data exists in the coordinator

        Returns:
            True if station entity is available, False otherwise.
        """
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "station" in self.coordinator.data
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes for station entities.

        Returns:
            Dictionary containing plant_id attribute.
            Returns None if no attributes are available.
        """
        attributes = {}
        attributes["plant_id"] = self.coordinator.plant_id
        return attributes if attributes else None


# ========== Sensor Base Classes ==========


def _get_display_precision(
    sensor_config: dict[str, Any], device_class: str | None
) -> int | None:
    """Get display precision from config or device class defaults.

    Args:
        sensor_config: Sensor configuration dictionary
        device_class: Device class string (e.g., "voltage")

    Returns:
        Suggested display precision or None if not specified
    """
    if "suggested_display_precision" in sensor_config:
        return int(sensor_config["suggested_display_precision"])
    if device_class == "voltage":
        return 2
    return None


def _get_model_from_coordinator(
    coordinator: EG4DataUpdateCoordinator, serial: str
) -> str:
    """Get device model from coordinator data.

    Args:
        coordinator: The data update coordinator.
        serial: The device serial number.

    Returns:
        The device model name or 'Unknown' if not available.
    """
    if coordinator.data and "devices" in coordinator.data:
        return str(coordinator.data["devices"].get(serial, {}).get("model", "Unknown"))
    return "Unknown"


def _apply_sensor_config(
    entity: Any,
    sensor_key: str,
    diagnostic_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Apply SENSOR_TYPES configuration to a sensor entity.

    Extracts sensor configuration from SENSOR_TYPES and sets standard entity
    attributes: unit, device_class, state_class, icon, display precision,
    and entity_category.

    Args:
        entity: The entity to configure (must support _attr_* properties).
        sensor_key: The key for this sensor in SENSOR_TYPES.
        diagnostic_keys: Optional frozenset of keys that should be marked diagnostic.

    Returns:
        The sensor configuration dictionary for further use.
    """
    sensor_config: dict[str, Any] = cast(
        "dict[str, Any]", SENSOR_TYPES.get(sensor_key, {})
    )
    entity._sensor_config = sensor_config

    entity._attr_native_unit_of_measurement = sensor_config.get("unit")
    entity._attr_device_class = sensor_config.get("device_class")
    entity._attr_state_class = sensor_config.get("state_class")
    entity._attr_icon = sensor_config.get("icon")
    options = sensor_config.get("options")
    if options is not None:
        entity._attr_options = options

    # Set display precision
    precision = _get_display_precision(sensor_config, entity._attr_device_class)
    if precision is not None:
        entity._attr_suggested_display_precision = precision

    # Set entity category for diagnostic sensors
    entity_category = sensor_config.get("entity_category")
    is_diagnostic = (
        diagnostic_keys is not None and sensor_key in diagnostic_keys
    ) or entity_category is not None
    if is_diagnostic:
        if isinstance(entity_category, str):
            entity_category = EntityCategory(entity_category)
        entity._attr_entity_category = (
            entity_category
            if entity_category is not None
            else EntityCategory.DIAGNOSTIC
        )

    return sensor_config


class EG4BaseSensor(EG4DeviceEntity):
    """Base class for EG4 sensor entities with shared configuration logic.

    This class provides common sensor functionality:
    - Sensor configuration from SENSOR_TYPES
    - Display precision handling
    - Diagnostic entity category detection

    Note: Monotonic value enforcement for TOTAL_INCREASING sensors is handled
    by Home Assistant's statistics system, not by this integration.

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _sensor_config: Configuration dictionary for this sensor.
    """

    _attr_suggested_display_precision: int | None = None

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
        device_type: str = "inverter",
    ) -> None:
        """Initialize the base sensor entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
            sensor_key: The key for this sensor in SENSOR_TYPES.
            device_type: Type of device (inverter, gridboss, parallel_group).
        """
        super().__init__(coordinator, serial)
        self._sensor_key = sensor_key
        self._device_type = device_type

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(
            self, sensor_key, diagnostic_keys=DIAGNOSTIC_DEVICE_SENSOR_KEYS
        )

        # Generate unique ID
        self._attr_unique_id = f"{serial}_{sensor_key}"

        # Modern entity naming
        self._attr_has_entity_name = True
        self._attr_name = sensor_config.get("name", sensor_key)

        # Generate entity_id based on device type
        model = _get_model_from_coordinator(coordinator, serial)
        self._setup_entity_id(model, device_type)

    def _setup_entity_id(self, model: str, device_type: str) -> None:
        """Set up entity_id based on device type."""
        if device_type == "gridboss":
            self._attr_entity_id = (
                f"sensor.{ENTITY_PREFIX}_gridboss_{self._serial}_{self._sensor_key}"
            )
        elif device_type == "parallel_group":
            self._attr_entity_id = (
                f"sensor.{ENTITY_PREFIX}_parallel_group_{self._sensor_key}"
            )
        else:
            model_clean = clean_model_name(model, use_underscores=True)
            self._attr_entity_id = f"sensor.{ENTITY_PREFIX}_{model_clean}_{self._serial}_{self._sensor_key}"

    def _get_raw_value(self) -> Any:
        """Get raw sensor value from coordinator data.

        Override in subclasses to change where value is retrieved from.
        """
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None

        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None

        sensors = device_data.get("sensors", {})
        return sensors.get(self._sensor_key)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor.

        Note: Home Assistant's TOTAL_INCREASING state class handles
        meter resets automatically - no integration-level enforcement needed.
        """
        return self._get_raw_value()

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


class EG4BaseBatterySensor(EG4BatteryEntity):
    """Base class for EG4 individual battery sensor entities.

    Provides common functionality for battery-specific sensors:
    - Sensor configuration from SENSOR_TYPES
    - Battery-specific entity category detection

    Note: Monotonic value enforcement for TOTAL_INCREASING sensors is handled
    by Home Assistant's statistics system, not by this integration.

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _sensor_config: Configuration dictionary for this sensor.
    """

    _attr_suggested_display_precision: int | None = None

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        battery_key: str,
        sensor_key: str,
    ) -> None:
        """Initialize the base battery sensor entity.

        Args:
            coordinator: The data update coordinator.
            serial: The parent device serial number.
            battery_key: The unique key identifying this battery.
            sensor_key: The key for this sensor in SENSOR_TYPES.
        """
        super().__init__(coordinator, serial, battery_key)
        # Also store as _serial for compatibility
        self._serial = serial
        self._sensor_key = sensor_key

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(
            self, sensor_key, diagnostic_keys=DIAGNOSTIC_BATTERY_SENSOR_KEYS
        )

        # Generate unique ID
        self._attr_unique_id = f"{serial}_{battery_key}_{sensor_key}"

        # Modern entity naming
        self._attr_has_entity_name = True
        self._attr_name = sensor_config.get("name", sensor_key)

        # Generate entity_id
        model = _get_model_from_coordinator(coordinator, serial)
        clean_battery_id = battery_key.replace("_", "").lower()
        model_clean = clean_model_name(model, use_underscores=True)
        self._attr_entity_id = f"sensor.{ENTITY_PREFIX}_{model_clean}_{serial}_battery_{clean_battery_id}_{sensor_key}"

    def _get_raw_value(self) -> Any:
        """Get raw sensor value from battery data."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None

        device_data = self.coordinator.data["devices"].get(self._parent_serial)
        if not device_data:
            return None

        batteries = device_data.get("batteries", {})
        battery_data = batteries.get(self._battery_key, {})
        return battery_data.get(self._sensor_key)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor.

        Note: Home Assistant's TOTAL_INCREASING state class handles
        meter resets automatically - no integration-level enforcement needed.
        """
        return self._get_raw_value()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device_exists = (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._parent_serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._parent_serial]
        )
        if not device_exists or self.coordinator.data is None:
            return False
        return self._battery_key in self.coordinator.data["devices"][
            self._parent_serial
        ].get("batteries", {})


class EG4BatteryBankEntity(EG4DeviceEntity):
    """Base class for EG4 battery bank entities (aggregate of all batteries).

    Battery bank entities represent the combined state of all batteries
    connected to an inverter.

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _sensor_config: Configuration dictionary for this sensor.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        sensor_key: str,
    ) -> None:
        """Initialize the battery bank entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
            sensor_key: The key for this sensor in SENSOR_TYPES.
        """
        super().__init__(coordinator, serial)
        self._sensor_key = sensor_key

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(self, sensor_key)

        # Generate unique ID
        self._attr_unique_id = f"{serial}_battery_bank_{sensor_key}"

        # Modern entity naming
        self._attr_has_entity_name = True
        self._attr_name = sensor_config.get("name", sensor_key)

        # Generate entity_id
        model = _get_model_from_coordinator(coordinator, serial)
        model_clean = clean_model_name(model, use_underscores=True)
        self._attr_entity_id = (
            f"sensor.{ENTITY_PREFIX}_{model_clean}_{serial}_battery_bank_{sensor_key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for battery bank."""
        device_info = self.coordinator.get_battery_bank_device_info(self._serial)
        if device_info is None:
            # Construct fallback DeviceInfo if coordinator returns None
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._serial}_battery_bank")},
                name=f"Battery Bank ({self._serial})",
                manufacturer=MANUFACTURER,
                model="Battery Bank",
                via_device=(DOMAIN, self._serial),
            )
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

        if not device_exists or self.coordinator.data is None:
            return False
        return bool(
            self._sensor_key
            in self.coordinator.data["devices"][self._serial].get("sensors", {})
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        device_data = self.coordinator.data["devices"].get(self._serial, {})
        sensors = device_data.get("sensors", {})
        return sensors.get(self._sensor_key)


# ========== Number Base Classes ==========


@contextmanager
def optimistic_value_context(
    entity: "EG4BaseNumber", target_value: float
) -> Generator[None, None, None]:
    """Context manager for optimistic value handling in number entities.

    Sets the optimistic value before yielding and clears it afterward,
    ensuring proper cleanup even if an exception occurs.

    Args:
        entity: The number entity to manage optimistic value for.
        target_value: The optimistic value to set.

    Yields:
        None - allows the caller to perform the actual number operation.

    Example:
        with optimistic_value_context(self, 50.0):
            await inverter.set_soc_limit(50)
    """
    entity._optimistic_value = target_value
    entity.async_write_ha_state()
    try:
        yield
    finally:
        entity._optimistic_value = None
        entity.async_write_ha_state()


class EG4BaseNumber(CoordinatorEntity):
    """Base class for all EG4 number entities.

    This class provides common functionality for number entities including:
    - Coordinator integration with device data access
    - Optimistic value management for UI responsiveness
    - Device information lookup
    - Availability checking
    - Common entity attributes

    Attributes:
        coordinator: The data update coordinator managing device data.
        serial: The device serial number.
        _model: The device model name.
        _clean_model: Cleaned model name for entity IDs.
        _optimistic_value: Temporary value for immediate UI feedback.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base number entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial
        self._optimistic_value: float | None = None

        # Get device info for subclasses
        self._model = _get_model_from_coordinator(coordinator, serial)
        self._clean_model = clean_model_name(self._model, use_underscores=True)

        # Device info
        self._attr_device_info = coordinator.get_device_info(serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    def _get_inverter_or_raise(self) -> Any:
        """Get inverter device object or raise HomeAssistantError.

        Returns:
            The inverter device object.

        Raises:
            HomeAssistantError: If inverter is not found.
        """
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            raise HomeAssistantError(f"Inverter {self.serial} not found")
        return inverter

    @property
    def _parameter_data(self) -> dict[str, Any]:
        """Get parameter data for this device from coordinator.

        Returns:
            Parameter data dictionary or empty dict if not available.
        """
        if self.coordinator.data and "parameters" in self.coordinator.data:
            params: dict[str, Any] = self.coordinator.data["parameters"].get(
                self.serial, {}
            )
            return params
        return {}


# ========== Switch Base Classes ==========


class EG4BaseSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for all EG4 switch entities.

    This class provides common functionality for switch entities including:
    - Coordinator integration with device data access
    - Optimistic state management for UI responsiveness
    - Device information lookup
    - Availability checking
    - Standard entity ID and unique ID generation

    Attributes:
        coordinator: The data update coordinator managing device data.
        _serial: The device serial number.
        _model: The device model name.
        _optimistic_state: Temporary state for immediate UI feedback.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        entity_key: str,
        name: str,
        icon: str = "mdi:toggle-switch",
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the base switch entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
            entity_key: Unique key for this entity (used in entity_id and unique_id).
            name: Display name for the entity.
            icon: MDI icon for the entity.
            entity_category: Optional entity category (CONFIG, DIAGNOSTIC, etc.).
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._serial = serial

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

        # Get device model from coordinator data
        self._model = _get_model_from_coordinator(coordinator, serial)

        # Set entity attributes
        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = generate_unique_id(serial, entity_key)
        self._attr_entity_id = generate_entity_id(
            "switch", self._model, serial, entity_key
        )

        if entity_category is not None:
            self._attr_entity_category = entity_category

        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=f"{self._model} {serial}",
            manufacturer=MANUFACTURER,
            model=self._model,
            serial_number=serial,
        )

    @property
    def _device_data(self) -> dict[str, Any]:
        """Get device data from coordinator.

        Returns:
            Device data dictionary or empty dict if not available.
        """
        if self.coordinator.data and "devices" in self.coordinator.data:
            data: dict[str, Any] = self.coordinator.data["devices"].get(
                self._serial, {}
            )
            return data
        return {}

    @property
    def _parameter_data(self) -> dict[str, Any]:
        """Get parameter data for this device from coordinator.

        Returns:
            Parameter data dictionary or empty dict if not available.
        """
        if self.coordinator.data and "parameters" in self.coordinator.data:
            params: dict[str, Any] = self.coordinator.data["parameters"].get(
                self._serial, {}
            )
            return params
        return {}

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Returns:
            True if the device is an inverter and available, False otherwise.
        """
        return bool(self._device_data.get("type") == "inverter")

    def _get_inverter_or_raise(self) -> Any:
        """Get inverter device object or raise HomeAssistantError.

        Returns:
            The inverter device object.

        Raises:
            HomeAssistantError: If inverter is not found.
        """
        inverter = self.coordinator.get_inverter_object(self._serial)
        if not inverter:
            raise HomeAssistantError(f"Inverter {self._serial} not found")
        return inverter

    async def _execute_switch_action(
        self,
        action_name: str,
        enable_method: str,
        disable_method: str,
        turn_on: bool,
        refresh_params: bool = False,
        api_delay: float = 1.0,
    ) -> None:
        """Execute a switch action with optimistic state handling.

        This is a helper method that handles the common pattern of:
        1. Setting optimistic state for immediate UI feedback
        2. Getting inverter object
        3. Calling enable/disable method
        4. Waiting for API to propagate changes
        5. Refreshing coordinator data (blocking)
        6. Clearing optimistic state only after refresh completes

        The optimistic state is cleared AFTER the coordinator refresh completes
        to prevent the "bounce" effect where the switch briefly shows the wrong
        state while waiting for API data to propagate.

        Args:
            action_name: Human-readable name of the action for logging.
            enable_method: Name of the method to call when turning on.
            disable_method: Name of the method to call when turning off.
            turn_on: True to enable, False to disable.
            refresh_params: If True, refresh parameters instead of just data.
            api_delay: Seconds to wait for API to propagate changes (default 1.0).

        Raises:
            HomeAssistantError: If the action fails.
        """
        method_name = enable_method if turn_on else disable_method
        action_verb = "Enabling" if turn_on else "Disabling"

        try:
            _LOGGER.debug(
                "%s %s via CLOUD API for device %s",
                action_verb,
                action_name,
                self._serial,
            )

            # Set optimistic state immediately for UI feedback
            self._optimistic_state = turn_on
            self.async_write_ha_state()

            inverter = self._get_inverter_or_raise()

            # Call the appropriate method
            method = getattr(inverter, method_name, None)
            if method is None:
                self._optimistic_state = None
                self.async_write_ha_state()
                raise HomeAssistantError(f"Method {method_name} not found on inverter")

            success = await method()
            if not success:
                self._optimistic_state = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Failed to {action_verb.lower()} {action_name}"
                )

            _LOGGER.info(
                "Successfully %s %s via CLOUD API for device %s",
                action_verb.lower()[:-3] + "ed",  # Enabling -> enabled
                action_name,
                self._serial,
            )

            # Refresh inverter data from API
            await inverter.refresh()

            # Wait for API to propagate changes before refreshing coordinator
            # This prevents reading stale data during the coordinator refresh
            await asyncio.sleep(api_delay)

            # Request coordinator refresh (blocking wait for completion)
            if refresh_params:
                await self.coordinator.async_refresh_device_parameters(self._serial)
            else:
                await self.coordinator.async_refresh()

            # Clear optimistic state AFTER refresh completes
            # At this point coordinator data should reflect the new state
            self._optimistic_state = None
            self.async_write_ha_state()

        except HomeAssistantError:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        except Exception as e:
            _LOGGER.error(
                "Failed to %s %s for device %s: %s",
                action_verb.lower(),
                action_name,
                self._serial,
                e,
            )
            self._optimistic_state = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action_verb.lower()} {action_name}: {e}"
            ) from e

    async def _execute_named_parameter_action(
        self,
        action_name: str,
        parameter: str,
        value: bool,
    ) -> None:
        """Execute a switch action by writing a named parameter.

        Uses pylxpweb's write_named_parameters() which handles register mapping
        and bit field combination automatically.

        Args:
            action_name: Human-readable name of the action for logging.
            parameter: HTTP API-style parameter name (e.g., "FUNC_EPS_EN").
            value: True to enable, False to disable.

        Raises:
            HomeAssistantError: If the parameter write fails.
        """
        action_verb = "Enabling" if value else "Disabling"

        try:
            _LOGGER.debug(
                "%s %s via LOCAL transport for device %s (parameter %s)",
                action_verb,
                action_name,
                self._serial,
                parameter,
            )

            # Set optimistic state immediately for UI feedback
            self._optimistic_state = value
            self.async_write_ha_state()

            # Write the named parameter via coordinator
            await self.coordinator.write_named_parameter(
                parameter, value, serial=self._serial
            )

            # Optimistically update coordinator parameter data so any
            # concurrent coordinator cycle sees the new value immediately
            if self.coordinator.data and "parameters" in self.coordinator.data:
                params = self.coordinator.data["parameters"].get(self._serial)
                if params is not None:
                    params[parameter] = value

            _LOGGER.info(
                "Successfully %s %s via LOCAL transport for device %s",
                action_verb.lower()[:-3] + "ed",
                action_name,
                self._serial,
            )

            # Wait briefly for register write to take effect
            await asyncio.sleep(0.5)

            # Request coordinator refresh
            await self.coordinator.async_refresh()

            # Clear optimistic state after refresh
            self._optimistic_state = None
            self.async_write_ha_state()

        except HomeAssistantError:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        except Exception as e:
            _LOGGER.error(
                "Failed to %s %s for device %s: %s",
                action_verb.lower(),
                action_name,
                self._serial,
                e,
            )
            self._optimistic_state = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action_verb.lower()} {action_name}: {e}"
            ) from e
