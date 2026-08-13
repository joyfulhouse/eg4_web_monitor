"""Binary sensor platform for the EG4 Web Monitor integration.

Provides an "Off-Grid" binary sensor that is ON whenever the inverter's
operating-mode code (status_code / INPUT reg 0 / cloud ``status``) is an
off-grid state. This gives automations a single boolean to detect islanded
operation instead of matching individual ``operating_state`` slugs (issue #262).

Also provides the schedule-state binary sensors (issue #563): on the
EG4_OFFGRID family the portal models AC Charge / AC First as schedule-defined
working modes with no master enable toggle, so "is any window of the schedule
configured" is the only honest state signal the integration can publish.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EG4ConfigEntry
from .base_entity import EG4DeviceEntity, device_present_and_healthy
from .const import (
    DEVICE_TYPE_INVERTER,
    SCHEDULE_TIME_TYPES,
    ScheduleTimeSpec,
    is_off_grid,
)
from .coordinator import (
    DISCOVERY_LISTENER_CONTEXT,
    EG4DataUpdateCoordinator,
)
from .time import decode_schedule_window
from .utils import is_offgrid_family

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 2

# Schedule types exposed as state binary sensors on the EG4_OFFGRID family
# (#563): the two schedule-defined working modes of the SNA working-mode
# portal page. Keys into SCHEDULE_TIME_TYPES.
_OFFGRID_SCHEDULE_STATE_KEYS: tuple[str, ...] = ("ac_charge", "ac_first")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor binary sensor entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for binary sensor setup")
        return

    entities: list[BinarySensorEntity] = []
    for serial, device_data in coordinator.data["devices"].items():
        # Off-grid state comes from the inverter operating-mode register;
        # GridBOSS / batteries do not have it.
        if device_data.get("type") == DEVICE_TYPE_INVERTER:
            entities.append(EG4OffGridBinarySensor(coordinator, serial, device_data))

    # Schedule-state sensors (#563) for inverters whose family is already
    # positively resolved as EG4_OFFGRID at setup.
    schedule_sensors, known_schedule_sensors = _new_schedule_state_sensors(
        coordinator, set()
    )
    entities.extend(schedule_sensors)

    if entities:
        _LOGGER.info("Setup complete: %d binary sensor entities created", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No binary sensor entities created - no compatible devices")

    # The inverter family can resolve to EG4_OFFGRID only on a later refresh
    # (UNKNOWN while the parameter fetch fails), so re-check on each update —
    # the same late-registration pattern as the button platform's batteries.
    @callback
    def _async_discover_schedule_sensors() -> None:
        """Add schedule-state sensors for newly resolved off-grid inverters."""
        new_entities, _ = _new_schedule_state_sensors(
            coordinator, known_schedule_sensors
        )
        if new_entities:
            _LOGGER.info(
                "Late schedule-state sensor registration: adding %d entities",
                len(new_entities),
            )
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(
            _async_discover_schedule_sensors, DISCOVERY_LISTENER_CONTEXT
        )
    )


def _new_schedule_state_sensors(
    coordinator: EG4DataUpdateCoordinator,
    known: set[tuple[str, str]],
) -> tuple[list[EG4ScheduleActiveBinarySensor], set[tuple[str, str]]]:
    """Build schedule-state sensors for off-grid inverters not in ``known``.

    Gated on a POSITIVELY resolved EG4_OFFGRID family (fails closed on
    UNKNOWN/missing, like the time platform's ``offgrid`` gate): the sensors
    exist because the family has no AC Charge enable toggle, so creating them
    on grid-tied hardware — where the real switch exists — would be noise.

    Args:
        coordinator: The data update coordinator.
        known: ``(serial, schedule key)`` pairs already registered; updated
            in place with every pair this call returns.

    Returns:
        The newly built entities and the updated known set.
    """
    specs = {spec.key: spec for spec in SCHEDULE_TIME_TYPES}
    entities: list[EG4ScheduleActiveBinarySensor] = []
    for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
        if device_data.get("type") != DEVICE_TYPE_INVERTER:
            continue
        if not is_offgrid_family(device_data):
            continue
        for key in _OFFGRID_SCHEDULE_STATE_KEYS:
            if (serial, key) in known:
                continue
            known.add((serial, key))
            entities.append(
                EG4ScheduleActiveBinarySensor(coordinator, serial, specs[key])
            )
    return entities, known


class EG4OffGridBinarySensor(EG4DeviceEntity, BinarySensorEntity):
    """Binary sensor indicating the inverter is running off-grid (islanded)."""

    _attr_has_entity_name = True
    _attr_translation_key = "off_grid"
    _attr_icon = "mdi:transmission-tower-off"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        _device_data: dict[str, Any],
    ) -> None:
        """Initialize the off-grid binary sensor."""
        super().__init__(coordinator, serial)
        # Name comes from the translation key (entity.binary_sensor.off_grid.name)
        # so it localizes; setting _attr_name here would override translations.
        self._attr_unique_id = f"{serial}_off_grid"

    def _status_code(self) -> int | None:
        """Return the inverter operating-mode code from coordinator data."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        device_data = self.coordinator.data["devices"].get(self._serial)
        if not device_data:
            return None
        code = device_data.get("sensors", {}).get("status_code")
        return code if isinstance(code, int) else None

    @property
    def is_on(self) -> bool | None:
        """Return True if off-grid, False if on-grid, None if unknown."""
        return is_off_grid(self._status_code())

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Intentionally mirrors ``EG4BaseSensor.available`` (not the looser
        ``EG4DeviceEntity.available``) so the off-grid sensor follows the same
        availability rules as the inverter's other sensors: present-but-unknown
        when the device is online without a status code (#256), unavailable only
        when the device is gone or errored.
        """
        return device_present_and_healthy(self.coordinator, self._serial)


class EG4ScheduleActiveBinarySensor(EG4DeviceEntity, BinarySensorEntity):
    """Whether any window of an off-grid schedule is configured (#563).

    On the EG4_OFFGRID family AC Charge / AC First are schedule-defined
    working modes: the inverter charges from the grid (or passes AC through)
    whenever the clock is inside a configured window, and there is no master
    enable toggle for the integration to mirror. This sensor is named as
    SCHEDULE state on purpose — "configured" never means "charging right
    now"; it answers the question the removed AC Charge switch could not
    answer honestly.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: ScheduleTimeSpec,
    ) -> None:
        """Initialize the schedule-state binary sensor.

        Args:
            coordinator: The data update coordinator.
            serial: Inverter serial number.
            spec: The schedule type's declarative table entry.
        """
        super().__init__(coordinator, serial)
        self._spec = spec
        # Name comes from the translation key
        # (entity.binary_sensor.{key}_schedule_active.name) so it localizes.
        self._attr_translation_key = f"{spec.key}_schedule_active"
        self._attr_unique_id = f"{serial}_{spec.key}_schedule_active"

    @property
    def is_on(self) -> bool | None:
        """Return True when at least one window has a non-zero duration.

        A window whose start equals its end spans zero minutes and cannot
        run, so the structural ``start != end`` test is the configuration
        signal. The portal convention that an all-00:00 window DISABLES the
        schedule (#277/#295 live reports) remains asserted-unverified and is
        deliberately NOT load-bearing here. Returns None when any boundary is
        undecodable — the schedule state is then unknown, never assumed clear.
        """
        if not self.coordinator.data:
            return None
        params = self.coordinator.data.get("parameters", {}).get(self._serial, {})
        if not params:
            return None
        local_raw = self.coordinator.params_are_local_raw(self._serial)
        configured = False
        for window in range(1, self._spec.windows + 1):
            decoded = decode_schedule_window(
                self._spec, window, params, local_raw=local_raw
            )
            if decoded is None:
                return None
            start, end = decoded
            if start != end:
                configured = True
        return configured

    @property
    def available(self) -> bool:
        """Unavailable only when the device is gone or errored.

        Mirrors the off-grid binary sensor above: a polled device whose
        schedule params have not arrived yet is present-but-unknown
        (``is_on`` None), not unavailable.
        """
        return device_present_and_healthy(self.coordinator, self._serial)
