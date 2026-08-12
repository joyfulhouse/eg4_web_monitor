"""Base entity classes for EG4 Web Monitor integration.

This module provides base classes that eliminate code duplication across platforms.
All entity classes should inherit from these bases to ensure consistent behavior.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import time as dt_time
import logging
import time
from typing import TYPE_CHECKING, Any, Generator, cast

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.components.select import SelectEntity
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.select import SelectEntity  # type: ignore[assignment]
    from homeassistant.components.switch import SwitchEntity  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from .const import (
    DIAGNOSTIC_BATTERY_SENSOR_KEYS,
    DIAGNOSTIC_DEVICE_SENSOR_KEYS,
    DOMAIN,
    MANUFACTURER,
    SENSOR_TYPES,
)
from .coordinator import (
    STATION_LISTENER_CONTEXT,
    EG4DataUpdateCoordinator,
    device_listener_context,
)
from .utils import (
    async_write_with_cloud_fallback,
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# Bound on retained optimistic switch state after a write-ok + refresh-fail
# (#362). Retention normally ends when fresh device data arrives, but a
# firmware-silently-NAKed write (#251 reg-233, #331 reg-67 precedent) plus
# one failed refresh would otherwise wedge it forever: every healthy poll
# keeps returning the pre-write value, indistinguishable from a stale tick.
# Follows the QUICK_CHARGE_OPTIMISTIC_TTL precedent (switch.py) and is kept
# NUMERICALLY EQUAL to it on purpose: after a quick-charge write-ok +
# refresh-fail BOTH holds arm within the same call, and nothing couples them
# afterwards — equal TTLs are what keep them expiring together. Change both
# or neither.
RETAINED_OPTIMISTIC_TTL: float = 300.0


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
        super().__init__(coordinator, context=device_listener_context(serial))
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
        super().__init__(coordinator, context=device_listener_context(parent_serial))
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
        super().__init__(coordinator, context=STATION_LISTENER_CONTEXT)
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


def device_present_and_healthy(
    coordinator: EG4DataUpdateCoordinator, serial: str
) -> bool:
    """Whether the device is present in coordinator data without an error.

    The sensor-level availability rule (stricter than
    ``EG4DeviceEntity.available``): present-but-unknown when the device is
    online without data, unavailable only when the device is gone or errored
    (#256). Shared by :attr:`EG4BaseSensor.available` and the off-grid binary
    sensor so the two cannot drift.
    """
    return (
        coordinator.last_update_success
        and coordinator.data is not None
        and "devices" in coordinator.data
        and serial in coordinator.data["devices"]
        and "error" not in coordinator.data["devices"][serial]
    )


# HA's recorder treats a drop greater than 10% as a meter reset (silent);
# smaller dips trigger a "state is not strictly increasing" warning
# (homeassistant/components/sensor/recorder.py). We suppress dips that fall
# in that warning zone — they are virtually always cloud-API rounding noise
# (e.g. consumption_lifetime stepping 2917.1 → 2917.0). Genuine resets
# (midnight rollover for daily totals, inverter replacement, lifetime
# counter wrap) are larger than 10% and pass through unchanged.
_RESET_DETECTION_THRESHOLD = 0.9


def _guard_total_increasing(
    state_class: Any, raw_value: Any, last_reported: float | None
) -> tuple[Any, float | None]:
    """Pin small downward dips for ``total_increasing`` sensors.

    Returns ``(value_to_report, new_last_reported)``. When a dip is suppressed,
    the cache stays at the previous high so subsequent dips remain aligned with
    what HA's recorder has stored. Non-numeric, ``None``, and non-
    ``total_increasing`` values are returned untouched and never update the
    cache.
    """
    if raw_value is None:
        return raw_value, last_reported

    state_class_str = (
        state_class.value if hasattr(state_class, "value") else state_class
    )
    if state_class_str != "total_increasing":
        return raw_value, last_reported

    try:
        new_val = float(raw_value)
    except (TypeError, ValueError):
        return raw_value, last_reported

    if (
        last_reported is not None
        and last_reported > 0
        and new_val < last_reported
        and new_val >= _RESET_DETECTION_THRESHOLD * last_reported
    ):
        return last_reported, last_reported

    return raw_value, new_val


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
    entity._attr_native_unit_of_measurement = sensor_config.get("unit")
    entity._attr_device_class = sensor_config.get("device_class")
    entity._attr_state_class = sensor_config.get("state_class")
    entity._attr_icon = sensor_config.get("icon")
    options = sensor_config.get("options")
    if options is not None:
        entity._attr_options = options

    # Opt-in translation key for sensors whose STATE is one of a fixed set of
    # slugs (e.g. the operating_state enum). Setting it activates HA's
    # entity.sensor.<key>.state translations; the display name still comes from
    # the "name" field below. Only sensors that declare it are affected.
    translation_key = sensor_config.get("translation_key")
    if translation_key is not None:
        entity._attr_translation_key = translation_key

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

    # Allow sensors to be disabled by default (e.g. noisy last_polled
    # timestamps). Truthiness, not an ``is False`` identity check, so a
    # non-bool falsy value can't silently ship the entity enabled (#310).
    if not sensor_config.get("enabled_default", True):
        entity._attr_entity_registry_enabled_default = False

    return sensor_config


class EG4BaseSensor(EG4DeviceEntity):
    """Base class for EG4 sensor entities with shared configuration logic.

    This class provides common sensor functionality:
    - Sensor configuration from SENSOR_TYPES
    - Display precision handling
    - Diagnostic entity category detection
    - Dip suppression for ``total_increasing`` sensors (see
      :func:`_guard_total_increasing`)

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _last_reported_value: Last reported numeric value for monotonic guard.
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
        self._last_reported_value: float | None = None

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(
            self, sensor_key, diagnostic_keys=DIAGNOSTIC_DEVICE_SENSOR_KEYS
        )

        # Generate unique ID
        self._attr_unique_id = f"{serial}_{sensor_key}"

        # Modern entity naming. When a translation_key is declared, leave
        # _attr_name unset so HA resolves the (localizable) name from
        # entity.<platform>.<key>.name; setting _attr_name would override it.
        self._attr_has_entity_name = True
        if not sensor_config.get("translation_key"):
            self._attr_name = sensor_config.get("name", sensor_key)

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

        For ``total_increasing`` sensors, suppress small downward dips (≤10%)
        that arise from cloud-API rounding noise. Larger drops (e.g. midnight
        resets for daily totals) pass through, matching HA recorder's reset
        threshold.
        """
        raw_value = self._get_raw_value()
        value, self._last_reported_value = _guard_total_increasing(
            getattr(self, "_attr_state_class", None),
            raw_value,
            self._last_reported_value,
        )
        return value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return device_present_and_healthy(self.coordinator, self._serial)


class EG4BaseBatterySensor(EG4BatteryEntity):
    """Base class for EG4 individual battery sensor entities.

    Provides common functionality for battery-specific sensors:
    - Sensor configuration from SENSOR_TYPES
    - Battery-specific entity category detection
    - Dip suppression for ``total_increasing`` sensors (see
      :func:`_guard_total_increasing`)

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _last_reported_value: Last reported numeric value for monotonic guard.
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
        self._last_reported_value: float | None = None

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(
            self, sensor_key, diagnostic_keys=DIAGNOSTIC_BATTERY_SENSOR_KEYS
        )

        # Generate unique ID
        self._attr_unique_id = f"{serial}_{battery_key}_{sensor_key}"

        # Modern entity naming. When a translation_key is declared, leave
        # _attr_name unset so HA resolves the (localizable) name from
        # entity.<platform>.<key>.name; setting _attr_name would override it.
        self._attr_has_entity_name = True
        if not sensor_config.get("translation_key"):
            self._attr_name = sensor_config.get("name", sensor_key)

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

        For ``total_increasing`` sensors, suppress small downward dips (≤10%)
        that arise from cloud-API rounding noise. Larger drops (e.g. midnight
        resets for daily totals) pass through, matching HA recorder's reset
        threshold.
        """
        raw_value = self._get_raw_value()
        value, self._last_reported_value = _guard_total_increasing(
            getattr(self, "_attr_state_class", None),
            raw_value,
            self._last_reported_value,
        )
        return value

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
    connected to an inverter. ``total_increasing`` sensors get the same dip
    suppression as :class:`EG4BaseSensor`.

    Attributes:
        _sensor_key: The sensor key for lookup in SENSOR_TYPES.
        _last_reported_value: Last reported numeric value for monotonic guard.
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
        self._last_reported_value: float | None = None

        # Apply shared sensor config (unit, device_class, state_class, icon, precision, category)
        sensor_config = _apply_sensor_config(self, sensor_key)

        # Generate unique ID
        self._attr_unique_id = f"{serial}_battery_bank_{sensor_key}"

        # Modern entity naming. When a translation_key is declared, leave
        # _attr_name unset so HA resolves the (localizable) name from
        # entity.<platform>.<key>.name; setting _attr_name would override it.
        self._attr_has_entity_name = True
        if not sensor_config.get("translation_key"):
            self._attr_name = sensor_config.get("name", sensor_key)

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
        device_data = self.coordinator.data["devices"][self._serial]
        # Battery-bank sensors are MEASUREMENTS: an error-marked (link-down)
        # device must read unavailable, not frozen-fresh (eg4-57g review).
        if "error" in device_data:
            return False
        return bool(self._sensor_key in device_data.get("sensors", {}))

    def _get_raw_value(self) -> Any:
        """Get raw sensor value from battery bank aggregate sensors."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        device_data = self.coordinator.data["devices"].get(self._serial, {})
        sensors = device_data.get("sensors", {})
        return sensors.get(self._sensor_key)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor.

        For ``total_increasing`` sensors, suppress small downward dips (≤10%)
        that arise from cloud-API rounding noise. Larger drops (e.g. midnight
        resets for daily totals) pass through, matching HA recorder's reset
        threshold.
        """
        raw_value = self._get_raw_value()
        value, self._last_reported_value = _guard_total_increasing(
            getattr(self, "_attr_state_class", None),
            raw_value,
            self._last_reported_value,
        )
        return value


# ========== Optimistic Write Retention ==========


class EG4OptimisticEntity(CoordinatorEntity):
    """Coordinator entity with BOUNDED retention of an acknowledged write.

    Every EG4 control platform publishes an optimistic value the moment the
    user acts, then runs a post-write refresh so the entity can settle on
    real device data. When that refresh fails, clearing the optimistic value
    republishes the STALE pre-write value and the UI visibly reverts a write
    the device already accepted (#362).

    Retaining the acknowledged value instead is only safe while the
    retention is BOUNDED and SELF-CLEARING. A post-write refresh fails for
    routine reasons — pylxpweb reports ``parameters_complete=False`` whenever
    a single register range times out, which #282 already absorbs with a
    retry floor and sticky carry-forward — and that can coincide with the
    firmware SILENTLY rejecting the write (#251 reg 233, #331 reg 67).
    Unbounded retention would then show a value the device never applied,
    indefinitely and without warning. Retention therefore ends at the first
    of:

    - **convergence** — a coordinator tick whose decoded value is the
      written value, or anything else no longer equal to the pre-write value
      (an external portal/LCD change counts: it is fresh device truth). A
      tick still carrying the stale pre-write value is NOT convergence;
      clearing there would be the same silent revert, delayed one poll.
    - **expiry** — ``RETAINED_OPTIMISTIC_TTL`` elapses with no convergence,
      which is exactly the silent-NAK signature. The entity reverts to the
      reported state and logs a WARNING so the divergence is visible instead
      of being hidden behind a value the hardware never took.

    Subclasses supply :attr:`_retention_serial` and three hooks
    (:meth:`_cache_state`, :meth:`_published_optimistic`,
    :meth:`_clear_optimistic`) because each platform holds its optimistic
    value in its own attribute and decodes its own value type.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator) -> None:
        """Initialize the retention bookkeeping.

        Args:
            coordinator: The data update coordinator.
        """
        super().__init__(coordinator)
        self._optimistic_retained = False
        self._pre_write_state: Any = None
        self._retention_expires: float = 0.0
        self._retained_action: str = ""
        # Directly-constructed entities remain supported by default.  Platform
        # discovery overrides this bit and keeps it current as late model/family
        # metadata arrives or disappears.
        self._control_discovery_supported = True

    def _set_control_discovery_supported(self, supported: bool) -> None:
        """Set whether this entity is in the platform's current candidate set."""
        self._control_discovery_supported = supported

    def _control_device_available(self, expected_type: str = "inverter") -> bool:
        """Return whether a discovered control still has an applicable device.

        The LOCAL staleness ``error`` key is deliberately NOT consulted here:
        controls are setpoints, not live readings, and stay available through
        a transport link-down or a transient processing failure (the same
        contract documented on ``_sync_transport_link_state`` and applied to
        never-attached ``transport_attach_failed`` devices).
        """
        devices = (self.coordinator.data or {}).get("devices", {})
        device_data = devices.get(self._retention_serial)
        return bool(
            self.coordinator.last_update_success
            and self._control_discovery_supported
            and device_data
            and device_data.get("type") == expected_type
        )

    def _stable_control_unique_id(self, entity_key: str) -> str:
        """Build a registry identity from immutable device identity and purpose."""
        return generate_unique_id(self._retention_serial.lower(), entity_key)

    # ── Subclass hooks ──────────────────────────────────────────────

    @property
    def _retention_serial(self) -> str:
        """Serial number of the device this entity writes to (for logging)."""
        raise NotImplementedError

    def _cache_state(self) -> Any:
        """Return the entity's value as decoded from coordinator data.

        Contract: SIDE-EFFECT-FREE, and it must read GENUINE device data —
        implementations mask the optimistic value (and any other held
        command, e.g. quick charge's #296 ``_pending_state``) while
        decoding. A peek that echoes a held command back would look like
        convergence and defeat the TTL escape.
        """
        raise NotImplementedError

    def _published_optimistic(self) -> Any:
        """Return the currently published optimistic value, or None."""
        raise NotImplementedError

    def _clear_optimistic(self) -> None:
        """Drop the published optimistic value."""
        raise NotImplementedError

    # ── Retention lifecycle ─────────────────────────────────────────

    def _begin_retention_window(self) -> Any:
        """Snapshot the pre-write cache value and disarm earlier retention.

        Returns what the cache decodes to BEFORE the write, so a later
        retained value can tell fresh device data from a stale tick. Any
        retention armed by an earlier write is superseded by this one.
        """
        pre_write_state = self._cache_state()
        self._optimistic_retained = False
        self._pre_write_state = None
        return pre_write_state

    def _arm_retention(self, action_name: str, pre_write_state: Any) -> None:
        """Retain the optimistic value after write-ok + refresh-fail."""
        self._optimistic_retained = True
        self._pre_write_state = pre_write_state
        self._retention_expires = time.monotonic() + RETAINED_OPTIMISTIC_TTL
        self._retained_action = action_name
        _LOGGER.debug(
            "Retaining optimistic state for %s on device %s until fresh "
            "device data arrives (bounded to %.0f s)",
            action_name,
            self._retention_serial,
            RETAINED_OPTIMISTIC_TTL,
        )

    def _end_retention(self) -> None:
        """Drop the retained optimistic value and its bookkeeping."""
        self._clear_optimistic()
        self._optimistic_retained = False
        self._pre_write_state = None
        self._retained_action = ""

    async def _settle_acknowledged_write(
        self,
        action_name: str,
        pre_write_state: Any,
        refresh: Callable[[], Awaitable[bool]] | None,
    ) -> None:
        """Run the post-write refresh phase for an ACKNOWLEDGED write (#362).

        Never raises: a successful write must not be converted into a
        user-facing write failure. On a completed refresh the optimistic
        value clears (coordinator data is fresh); on a failed refresh
        (reported False or raised) it is retained via :meth:`_arm_retention`
        instead of publishing the stale pre-write value.

        ``refresh=None`` means the caller DELIBERATELY skipped the refresh
        phase (the known-down cloud fallback route, #485). That takes the
        same retain branch, but it is not a failure and must not be logged
        as one: pairing a "did not complete" WARNING with the link-down
        WARNING already emitted by the router described the intended path as
        a broken one on every toggle during an outage.

        Either way the retention is BOUNDED — a deliberate skip cannot tell
        an acknowledged-but-unreadable write apart from a silently NAKed
        one, so ``RETAINED_OPTIMISTIC_TTL`` bounds the wait for both (#379).
        """
        refresh_ok = False
        if refresh is None:
            _LOGGER.debug(
                "Post-write refresh skipped after %s for device %s; retaining "
                "the acknowledged state until the hourly parameter refresh "
                "reads it back",
                action_name,
                self._retention_serial,
            )
        else:
            try:
                refresh_ok = await refresh()
                if not refresh_ok:
                    _LOGGER.warning(
                        "Post-write refresh did not complete after %s for device "
                        "%s (the write itself succeeded)",
                        action_name,
                        self._retention_serial,
                    )
            except Exception as e:
                _LOGGER.warning(
                    "Post-write refresh failed after %s for device %s "
                    "(the write itself succeeded): %s",
                    action_name,
                    self._retention_serial,
                    e,
                )

        if refresh_ok:
            # Coordinator data reflects the new state — publish it.
            self._clear_optimistic()
        else:
            self._arm_retention(action_name, pre_write_state)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Resolve a retained optimistic value against each coordinator tick.

        Clears on convergence, or on TTL expiry with a WARNING — see the
        class docstring for why both exits are required.
        """
        optimistic = self._published_optimistic()
        if self._optimistic_retained and optimistic is not None:
            current = self._cache_state()
            if current == optimistic or current != self._pre_write_state:
                self._end_retention()
            elif time.monotonic() >= self._retention_expires:
                _LOGGER.warning(
                    "Optimistic state for %s on device %s expired without "
                    "device confirmation; reverting to the reported state, "
                    "which may decode as unknown (the device may have "
                    "rejected the write)",
                    self._retained_action or "control write",
                    self._retention_serial,
                )
                self._end_retention()
        super()._handle_coordinator_update()


# ========== Number Base Classes ==========


class OptimisticWrite:
    """Outcome handle yielded by :func:`optimistic_value_context`.

    The body of the ``with`` block reports whether its post-write refresh
    actually completed. Defaults to True — "nothing reported a failure" — so
    a write path with no refresh at all (its convergence channel is a direct
    cache seed) settles immediately instead of arming retention it can never
    clear.
    """

    __slots__ = ("refresh_ok",)

    def __init__(self) -> None:
        """Initialize with the optimistic assumption of a settled write."""
        self.refresh_ok = True


@contextmanager
def optimistic_value_context(
    entity: "EG4BaseNumber", target_value: float, action_name: str = "number write"
) -> Generator[OptimisticWrite, None, None]:
    """Context manager for optimistic value handling in number entities.

    Publishes the optimistic value before yielding, then settles it:

    - body raised (the write failed) → clear, re-raise (unchanged).
    - body completed, refresh reported OK → clear; coordinator data is fresh.
    - body completed, refresh reported FAILURE → RETAIN the acknowledged
      value under the bounded retention of :class:`EG4OptimisticEntity`
      (#379/#362) instead of republishing the stale pre-write value.

    Args:
        entity: The number entity to manage the optimistic value for.
        target_value: The optimistic value to publish.
        action_name: Human-readable label used in retention log messages.

    Yields:
        The :class:`OptimisticWrite` handle whose ``refresh_ok`` the body
        sets from its post-write refresh result.

    Example:
        with optimistic_value_context(self, 50.0, "SOC limit") as write:
            await inverter.set_soc_limit(50)
            write.refresh_ok = await self._refresh_related_entities()
    """
    pre_write_state = entity._begin_retention_window()
    entity._optimistic_value = target_value
    entity.async_write_ha_state()
    outcome = OptimisticWrite()
    try:
        yield outcome
    except Exception:
        entity._end_retention()
        entity.async_write_ha_state()
        raise
    if outcome.refresh_ok:
        entity._clear_optimistic()
    else:
        entity._arm_retention(action_name, pre_write_state)
    entity.async_write_ha_state()


class EG4BaseNumber(EG4OptimisticEntity):
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

        # Device info
        self._attr_device_info = coordinator.get_device_info(serial)

    @property
    def _retention_serial(self) -> str:
        """Serial number of the device this entity writes to."""
        return self.serial

    def _published_optimistic(self) -> float | None:
        """Return the currently published optimistic value, or None."""
        return self._optimistic_value

    def _clear_optimistic(self) -> None:
        """Drop the published optimistic value."""
        self._optimistic_value = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._control_device_available()

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


# ========== Time Base Classes ==========
# NOTE: time entities manage their optimistic value explicitly instead of a
# finally-always-clears context manager: a successful write whose follow-up
# refresh fails RETAINS the optimistic value (PR #283 review P2 — clearing
# would look like a silent revert to the stale cached time), bounded by
# :class:`EG4OptimisticEntity`'s TTL escape (#379).


class EG4BaseTime(EG4OptimisticEntity):
    """Base class for all EG4 time entities.

    The time-typed mirror of :class:`EG4BaseNumber`: coordinator integration
    with device data access, optimistic value management for UI
    responsiveness, device information lookup, availability checking, and
    parameter data access.

    Attributes:
        coordinator: The data update coordinator managing device data.
        serial: The device serial number.
        _optimistic_value: Temporary value for immediate UI feedback.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base time entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial
        self._optimistic_value: dt_time | None = None

        # Device info
        self._attr_device_info = coordinator.get_device_info(serial)

    @property
    def _retention_serial(self) -> str:
        """Serial number of the device this entity writes to."""
        return self.serial

    def _published_optimistic(self) -> dt_time | None:
        """Return the currently published optimistic value, or None."""
        return self._optimistic_value

    def _clear_optimistic(self) -> None:
        """Drop the published optimistic value."""
        self._optimistic_value = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._control_device_available()

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


# ========== Select Base Classes ==========


class EG4BaseSelect(EG4OptimisticEntity, SelectEntity):
    """Base class for all EG4 select entities.

    Holds only what the shared optimistic-retention machinery needs — the
    serial, the string optimistic state, and the three retention hooks.
    Naming, icons, options and device info stay with the concrete selects,
    which build them from platform-specific tables.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base select entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._serial = serial

        # Optimistic state for immediate UI feedback
        self._optimistic_state: str | None = None

    @property
    def _retention_serial(self) -> str:
        """Serial number of the device this entity writes to."""
        return self._serial

    def _published_optimistic(self) -> str | None:
        """Return the currently published optimistic option, or None."""
        return self._optimistic_state

    def _clear_optimistic(self) -> None:
        """Drop the published optimistic option."""
        self._optimistic_state = None

    def _cache_state(self) -> str | None:
        """Return ``current_option`` as decoded from coordinator data.

        Masks the optimistic state so the subclass's ``current_option``
        decodes the underlying parameter cache (every subclass prefers
        ``_optimistic_state`` when set). Synchronous — the mask never spans
        an await point.
        """
        saved = self._optimistic_state
        self._optimistic_state = None
        try:
            return self.current_option
        finally:
            self._optimistic_state = saved

    def _begin_optimistic_write(self, option: str) -> str | None:
        """Publish the optimistic option and capture the pre-write cache value."""
        pre_write_state: str | None = self._begin_retention_window()
        self._optimistic_state = option
        self.async_write_ha_state()
        return pre_write_state


# ========== Switch Base Classes ==========


class EG4BaseSwitch(EG4OptimisticEntity, SwitchEntity):
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
        translation_key: str | None = None,
    ) -> None:
        """Initialize the base switch entity.

        Args:
            coordinator: The data update coordinator.
            serial: The device serial number.
            entity_key: Unique key for this entity (used in entity_id and unique_id).
            name: Display name for the entity. Ignored when ``translation_key``
                is provided — a set ``_attr_name`` overrides the translated
                name in HA (issue #262 gotcha).
            icon: MDI icon for the entity.
            entity_category: Optional entity category (CONFIG, DIAGNOSTIC, etc.).
            translation_key: Localize the entity name via strings.json.
        """
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._serial = serial

        # Optimistic state for immediate UI feedback. When a successful
        # write's post-write refresh fails (#362) it is RETAINED — the
        # acknowledged write IS device truth — under the bounded retention
        # of :class:`EG4OptimisticEntity`.
        self._optimistic_state: bool | None = None

        # Get device model from coordinator data
        self._model = _get_model_from_coordinator(coordinator, serial)

        # Set entity attributes
        self._attr_has_entity_name = True
        if translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = generate_unique_id(serial, entity_key)

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
            True if the coordinator is healthy and the device is an inverter,
            False otherwise.
        """
        return self._control_device_available()

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

    @property
    def _retention_serial(self) -> str:
        """Serial number of the device this entity writes to."""
        return self._serial

    def _published_optimistic(self) -> bool | None:
        """Return the currently published optimistic state, or None."""
        return self._optimistic_state

    def _clear_optimistic(self) -> None:
        """Drop the published optimistic state."""
        self._optimistic_state = None

    def _cache_state(self) -> bool | None:
        """Return ``is_on`` as decoded from coordinator data.

        Temporarily masks the optimistic state so the subclass's ``is_on``
        decodes the underlying cache/device data (every subclass prefers
        ``_optimistic_state`` when set). Synchronous — the mask never spans
        an await point.

        Contract: this peek must be SIDE-EFFECT-FREE and must read genuine
        device data. Subclasses whose ``is_on`` consults additional hold
        state after the optimistic check (e.g. quick charge's #296
        ``_pending_state``) must override this to mask that state too —
        otherwise the peek echoes the held command back (false retention
        convergence) or mutates the hold as a side effect of the read.
        """
        saved = self._optimistic_state
        self._optimistic_state = None
        try:
            return self.is_on
        finally:
            self._optimistic_state = saved

    def _begin_optimistic_write(self, value: bool) -> bool | None:
        """Publish the optimistic state and capture the pre-write cache state.

        Returns what the cache decodes to BEFORE the write so a later
        retained optimistic state can detect fresh device data (#362); any
        retained state from an earlier write is superseded by this one. The
        "begin" counterpart of :meth:`_settle_acknowledged_write`.
        """
        pre_write_state: bool | None = self._begin_retention_window()
        self._optimistic_state = value
        self.async_write_ha_state()
        return pre_write_state

    async def _refresh_coordinator_data(self) -> bool:
        """Run a full coordinator refresh; True only when it produced fresh data.

        ``last_update_success`` alone LIES during the coordinator's 3-strike
        tolerance window: the first two consecutive ``UpdateFailed`` cycles
        return the OLD ``self.data`` object unchanged without flipping the
        flag, so a post-write refresh could serve stale pre-write data as if
        it were fresh (#362 review). A same-identity data object after the
        refresh is therefore treated as failure — every genuinely successful
        cycle builds a new data dict.
        """
        data_before = self.coordinator.data
        await self.coordinator.async_refresh()
        return bool(self.coordinator.last_update_success) and (
            self.coordinator.data is not data_before
        )

    async def _optimistic_write_envelope(
        self,
        action_name: str,
        value: bool,
        *,
        do_write: Callable[[], Awaitable[None]],
        do_refresh: Callable[[], Awaitable[bool]],
        pre_delay_refresh: Callable[[], Awaitable[None]] | None = None,
        api_delay: float = 1.0,
        seed_param_key: str | None = None,
        refresh_after_write: bool = True,
    ) -> None:
        """Execute a write with optimistic state and post-write refreshes.

        Shared by ``_execute_switch_action`` and ``_execute_cloud_function_action``;
        the LOCAL named-parameter path (``_execute_named_parameter_action``)
        shares the identical write/refresh semantics through the same
        :meth:`_settle_acknowledged_write` helper. ``do_write`` performs its
        own precondition/success checks and raises ``HomeAssistantError`` on
        failure — there is no false-return branch here; failure flows through
        the write exception handlers below. ``do_refresh`` returns whether
        the refresh completed AND produced fresh data (see
        :meth:`_refresh_coordinator_data` for the tolerated-stale caveat).

        Write and refresh sit in SEPARATE exception boundaries (#362):

        - write fails → clear optimistic state, raise (user-facing failure).
        - write ok + refresh ok → clear optimistic state AFTER the refresh
          completes, preventing the "bounce" effect where the entity briefly
          shows the wrong state while waiting for API data to propagate.
        - write ok + refresh fails (reported or raised) → RETAIN the
          optimistic state until fresh device data arrives or the retention
          TTL expires (:meth:`_handle_coordinator_update`) and log; a
          successful write is NEVER converted into a user-facing write
          failure, and the entity never publishes the stale pre-write cache
          value the device already superseded.

        ``refresh_after_write=False`` skips the whole refresh phase — no
        ``pre_delay_refresh`` probe, no propagation delay, no ``do_refresh``
        — and flows through the retain branch above, logged as a deliberate
        skip rather than a refresh failure (#485). Known-down cloud fallback
        routes pass False so no local recovery probe can block or revert the
        acknowledged write; the HOURLY parameter refresh cycle — not the
        20-30 s data poll, which carries no parameter reads — clears the
        retained state once it observes fresh data, and
        ``RETAINED_OPTIMISTIC_TTL`` bounds the wait.

        Callers emit their path-specific debug log BEFORE invoking this
        envelope — the pinned log ordering is debug → optimistic publish →
        write.
        """
        action_verb = "Enabling" if value else "Disabling"

        pre_write_state = self._begin_optimistic_write(value)

        try:
            await do_write()
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

        # The write is acknowledged: from here on nothing may raise a
        # user-facing write failure or publish the stale pre-write value.

        # Seed the acknowledged value BEFORE the refresh/optimistic-clear
        # (#310): under a down local link the parameter refresh below
        # cannot read the device locally (LOCAL-only: no data at all;
        # HYBRID: cloud re-read can lag or fail), so without the seed
        # this method could publish the STALE pre-write state when it
        # clears the optimistic value — a wrong-then-corrected double
        # transition (recorder pollution, automation misfires on the
        # intermediate value).
        if seed_param_key is not None:
            self._seed_cloud_written_parameter(seed_param_key, value)

        async def refresh_phase() -> bool:
            if pre_delay_refresh is not None:
                await pre_delay_refresh()

            # Wait for API to propagate changes before refreshing.
            await asyncio.sleep(api_delay)
            return await do_refresh()

        await self._settle_acknowledged_write(
            action_name,
            pre_write_state,
            refresh_phase if refresh_after_write else None,
        )

    async def _execute_switch_action(
        self,
        action_name: str,
        enable_method: str | Callable[..., Awaitable[bool]],
        disable_method: str | Callable[..., Awaitable[bool]],
        turn_on: bool,
        refresh_params: bool = False,
        api_delay: float = 1.0,
        enable_kwargs: dict[str, Any] | None = None,
        seed_param_key: str | None = None,
        refresh_after_write: bool = True,
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
            enable_method: Method to call when turning on — either the name of
                a method on the inverter object, or an awaitable callable
                (e.g. a cloud-direct bound method for families whose local
                register is firmware-rejected, #296).
            disable_method: Method to call when turning off (same forms).
            turn_on: True to enable, False to disable.
            refresh_params: If True, perform one targeted parameter refresh.
                Runtime/status actions retain the pre-delay inverter refresh
                followed by their full coordinator refresh.
            api_delay: Seconds to wait for API to propagate changes (default 1.0).
            enable_kwargs: Optional keyword arguments passed to the enable method
                on the turn-on path only (the disable method is always called with
                no arguments).
            seed_param_key: Parameter-cache key to seed with the acknowledged
                ``turn_on`` boolean when a local transport is attached (#310).
                Pass only for parameter-backed switches whose ``is_on`` reads
                this key; leave ``None`` for status-based actions (e.g. quick
                charge) and pure-cloud-only callers.
            refresh_after_write: Forwarded to
                :meth:`_optimistic_write_envelope`; False skips the whole
                post-write refresh phase (known-down cloud fallback, #485).

        Raises:
            HomeAssistantError: If the action fails.
        """
        method_ref = enable_method if turn_on else disable_method
        method_name = (
            method_ref
            if isinstance(method_ref, str)
            else getattr(method_ref, "__name__", action_name)
        )
        action_verb = "Enabling" if turn_on else "Disabling"

        # The routing (local transport vs cloud API) is decided by the called
        # method itself, so the log names the method, not a transport.
        _LOGGER.debug(
            "%s %s (%s) for device %s",
            action_verb,
            action_name,
            method_name,
            self._serial,
        )

        inverter: Any = None

        async def do_write() -> None:
            nonlocal inverter
            inverter = self._get_inverter_or_raise()

            # Call the appropriate method: an inverter method looked up by
            # name, or a pre-bound callable (cloud-direct path, #296).
            method = (
                getattr(inverter, method_ref, None)
                if isinstance(method_ref, str)
                else method_ref
            )
            if method is None:
                raise HomeAssistantError(f"Method {method_name} not found on inverter")

            # Only the enable (turn_on) path forwards enable_kwargs; the disable
            # method is always called with no arguments.
            success = (
                await method(**(enable_kwargs or {})) if turn_on else await method()
            )
            if not success:
                raise HomeAssistantError(
                    f"Failed to {action_verb.lower()} {action_name}"
                )

            _LOGGER.info(
                "Successfully %s %s for device %s",
                action_verb.lower()[:-3] + "ed",  # Enabling -> enabled
                action_name,
                self._serial,
            )

        async def pre_delay_refresh() -> None:
            await inverter.refresh()

        async def do_refresh() -> bool:
            if refresh_params:
                return await self.coordinator.async_refresh_device_parameters(
                    self._serial
                )
            return await self._refresh_coordinator_data()

        await self._optimistic_write_envelope(
            action_name,
            turn_on,
            do_write=do_write,
            do_refresh=do_refresh,
            pre_delay_refresh=None if refresh_params else pre_delay_refresh,
            api_delay=api_delay,
            seed_param_key=seed_param_key,
            refresh_after_write=refresh_after_write,
        )

    async def _execute_local_with_fallback(
        self,
        action_name: str,
        parameter: str,
        value: bool,
        cloud_enable_method: str | None = None,
        cloud_disable_method: str | None = None,
        after_local_write: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Execute a switch action preferring local transport, falling back to cloud.

        In HYBRID mode, if the local Modbus write fails (e.g. timeout due to bus
        contention), transparently retries via the cloud API. Both paths are
        idempotent (set specific state, not toggle), so a double-write is safe.

        Delegates transport routing to
        :func:`utils.async_write_with_cloud_fallback` (GH #485), so switches
        share the same local-first, cloud-fallback, and known-down
        short-circuit policy as number/select/time controls.

        Args:
            action_name: Human-readable name of the action for logging.
            parameter: HTTP API-style parameter name (e.g., "FUNC_EPS_EN").
            value: True to enable, False to disable.
            cloud_enable_method: Inverter method name to call when enabling.
                When omitted, the cloud path writes ``parameter`` directly via
                the function-control API instead.
            cloud_disable_method: Inverter method name to call when disabling.
            after_local_write: Optional coroutine run ONLY when the local
                route succeeded, before this method returns. Exists so a
                caller that needs an extra post-write step (e.g. the AC
                Couple readback, #472) does not also run it after a cloud
                FALLBACK write — the cloud envelope already refreshes
                parameters, and running both coalesces to two forced reads
                for one logical write. Never invoked on the cloud route.

        Raises:
            ValueError: If exactly one of ``cloud_enable_method`` /
                ``cloud_disable_method`` is provided. They must be supplied
                together (named-method route) or both omitted (function-control
                route) — a one-sided call would otherwise silently write
                ``parameter`` via control_function, which may be the wrong
                FUNC_ key for the intended action.
            HomeAssistantError: If all available transports fail.
        """
        if bool(cloud_enable_method) != bool(cloud_disable_method):
            raise ValueError(
                "cloud_enable_method and cloud_disable_method must be provided "
                "together or both omitted; got "
                f"enable={cloud_enable_method!r}, disable={cloud_disable_method!r}"
            )

        local_attached = self.coordinator.has_local_transport(self._serial)
        cloud_available = self.coordinator.has_http_api()
        if not local_attached and not cloud_available:
            raise HomeAssistantError(f"No transport available for {action_name}")

        async def local_write() -> None:
            # When a cloud fallback exists, keep the optimistic state on local
            # failure: clearing it there would publish the stale pre-write
            # value for one transition before the cloud retry re-asserts it
            # (#310 review — recorder pollution/automation misfire). The cloud
            # path clears it if that retry fails too.
            await self._execute_named_parameter_action(
                action_name=action_name,
                parameter=parameter,
                value=value,
                clear_optimistic_on_error=not cloud_available,
            )
            # Reached only when the local write was acknowledged — a failure
            # above raises into the cloud-fallback route instead.
            #
            # The hook's own failure must NOT propagate: this runs inside
            # local_write(), so an exception here is indistinguishable to the
            # router from a failed local WRITE, and would trigger a redundant
            # cloud re-write of a command the device already accepted. The
            # write succeeded; only the follow-up step did not.
            if after_local_write is not None:
                try:
                    await after_local_write()
                except Exception:  # noqa: BLE001 - see above
                    _LOGGER.exception(
                        "Post-write step for %s on device %s failed; the write "
                        "itself was acknowledged",
                        action_name,
                        self._serial,
                    )

        async def cloud_write() -> None:
            # A failed local attempt can mark the link down, so evaluate this
            # at cloud-route execution time rather than before the shared
            # router runs. On a known-down link, both cloud envelopes report
            # the post-write refresh incomplete without scheduling local reads.
            refresh_after_write = not (
                self.coordinator.has_local_transport(self._serial)
                and self.coordinator.is_transport_link_down(self._serial)
            )
            if cloud_enable_method and cloud_disable_method:
                await self._execute_switch_action(
                    action_name=action_name,
                    enable_method=cloud_enable_method,
                    disable_method=cloud_disable_method,
                    turn_on=value,
                    refresh_params=True,
                    seed_param_key=parameter,
                    refresh_after_write=refresh_after_write,
                )
            else:
                await self._execute_cloud_function_action(
                    action_name=action_name,
                    parameter=parameter,
                    value=value,
                    seed_param_key=parameter,
                    refresh_after_write=refresh_after_write,
                )

        # The switch envelope seeds the acknowledged value before its refresh
        # phase, so local_values deliberately stays omitted here; passing it
        # would notify listeners twice and would seed too late to prevent a
        # stale post-write refresh from publishing.
        await async_write_with_cloud_fallback(
            self.coordinator,
            self._serial,
            action_name,
            local_write=local_write,
            cloud_write=cloud_write if cloud_available else None,
        )

    def _seed_cloud_written_parameter(self, param_key: str, value: bool) -> None:
        """Seed an acknowledged cloud-written FUNC_ bit into the parameter cache.

        Convergence for cloud-fallback writes while a local transport is
        attached (GH #310, the switch counterpart of
        :func:`utils.async_write_with_cloud_fallback` seeding): under a down
        local link the post-write parameter refresh cannot read the device
        locally (pylxpweb skips the local read — LOCAL-only installs get no
        data at all, and a HYBRID cloud re-read can lag or fail), so without
        the seed ``is_on`` could revert to the stale pre-write cache value
        once the optimistic state clears. The seed is the local-raw representation
        (bit params read back as ``bool``), and a later successful parameter
        read overwrites it with fresh device data.

        Never fires for pure-cloud installs (no transport attached): their
        parameter cache is cloud-fed and refreshes normally.
        """
        if self.coordinator.has_local_transport(self._serial):
            self.coordinator.note_parameters_written(self._serial, {param_key: value})

    async def _execute_cloud_function_action(
        self,
        action_name: str,
        parameter: str,
        value: bool,
        api_delay: float = 1.0,
        seed_param_key: str | None = None,
        refresh_after_write: bool = True,
    ) -> None:
        """Execute a switch action via the cloud function-control API.

        For FUNC_* bit parameters without dedicated enable/disable methods in
        pylxpweb (e.g. ``FUNC_CHARGE_LAST``), write directly via
        ``client.api.control.control_function(serial, parameter, value)`` —
        the same route pylxpweb's dual-path setters use in cloud mode. The
        server applies the bit update atomically (no read-modify-write race
        across the HTTP round-trip).

        Args:
            action_name: Human-readable name of the action for logging.
            parameter: Cloud function parameter name (e.g., "FUNC_CHARGE_LAST").
            value: True to enable, False to disable.
            api_delay: Seconds to wait for the API to propagate changes.
            seed_param_key: Parameter-cache key to seed with the acknowledged
                ``value`` when a local transport is attached (#310) — pass
                only for parameter-backed switches whose ``is_on`` reads this
                key; leave ``None`` for actions whose state is not parameter
                cache backed (e.g. status-based quick charge).
            refresh_after_write: Forwarded to
                :meth:`_optimistic_write_envelope`; False skips the whole
                post-write refresh phase (known-down cloud fallback, #485).

        Raises:
            HomeAssistantError: If no cloud client exists or the write fails.
        """
        action_verb = "Enabling" if value else "Disabling"
        client = self.coordinator.client
        if client is None:
            raise HomeAssistantError(f"No cloud API available for {action_name}")

        _LOGGER.debug(
            "%s %s via CLOUD function control for device %s (parameter %s)",
            action_verb,
            action_name,
            self._serial,
            parameter,
        )

        async def do_write() -> None:
            response = await client.api.control.control_function(
                self._serial, parameter, value
            )
            if not response.success:
                raise HomeAssistantError(
                    f"Failed to {action_verb.lower()} {action_name}"
                )

            _LOGGER.info(
                "Successfully %s %s via CLOUD function control for device %s",
                action_verb.lower()[:-3] + "ed",
                action_name,
                self._serial,
            )

        async def do_refresh() -> bool:
            return await self.coordinator.async_refresh_device_parameters(self._serial)

        await self._optimistic_write_envelope(
            action_name,
            value,
            do_write=do_write,
            do_refresh=do_refresh,
            api_delay=api_delay,
            seed_param_key=seed_param_key,
            refresh_after_write=refresh_after_write,
        )

    async def _execute_named_parameter_action(
        self,
        action_name: str,
        parameter: str,
        value: bool,
        clear_optimistic_on_error: bool = True,
    ) -> None:
        """Execute a switch action by writing a named parameter.

        Uses pylxpweb's write_named_parameters() which handles register mapping
        and bit field combination automatically.

        Shares the #362 write/refresh semantics with the optimistic write
        envelope (via :meth:`_settle_acknowledged_write`): a failed
        post-write refresh — including a tolerated-stale one — retains the
        optimistic state instead of unconditionally clearing it. The
        in-place parameter update below converges concurrent cycles
        immediately, but lives on the LIVE dict a full data rebuild replaces
        wholesale; the retention is what guards the revert when that
        happens.

        Args:
            action_name: Human-readable name of the action for logging.
            parameter: HTTP API-style parameter name (e.g., "FUNC_EPS_EN").
            value: True to enable, False to disable.
            clear_optimistic_on_error: Whether a failed write clears the
                optimistic state (and publishes). The fallback wrapper passes
                False when a cloud retry follows, so the entity never
                publishes the stale pre-write value between the local failure
                and the cloud attempt (#310 review).

        Raises:
            HomeAssistantError: If the parameter write fails.
        """
        action_verb = "Enabling" if value else "Disabling"

        _LOGGER.debug(
            "%s %s via LOCAL transport for device %s (parameter %s)",
            action_verb,
            action_name,
            self._serial,
            parameter,
        )

        # On the HYBRID fallback path the envelope re-arms retention if the
        # cloud retry's own refresh fails.
        pre_write_state = self._begin_optimistic_write(value)

        try:
            # Write the named parameter via coordinator
            await self.coordinator.write_named_parameter(
                parameter, value, serial=self._serial
            )
        except HomeAssistantError:
            if clear_optimistic_on_error:
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
            if clear_optimistic_on_error:
                self._optimistic_state = None
                self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action_verb.lower()} {action_name}: {e}"
            ) from e

        # Write acknowledged. Optimistically update coordinator parameter
        # data so any concurrent coordinator cycle sees the new value
        # immediately (deliberately NOT note_parameters_written: that is the
        # cloud-fallback seeding channel and notifies all listeners; this
        # in-place hint needs neither).
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

        async def refresh_phase() -> bool:
            # Wait briefly for register write to take effect.
            await asyncio.sleep(0.5)
            return await self._refresh_coordinator_data()

        await self._settle_acknowledged_write(
            action_name, pre_write_state, refresh_phase
        )
