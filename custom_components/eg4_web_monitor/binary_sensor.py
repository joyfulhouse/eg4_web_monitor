"""Binary sensor platform for the EG4 Web Monitor integration.

Provides an "Off-Grid" binary sensor that is ON whenever the inverter's
operating-mode code (status_code / INPUT reg 0 / cloud ``status``) is an
off-grid state. This gives automations a single boolean to detect islanded
operation instead of matching individual ``operating_state`` slugs (issue #262).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EG4ConfigEntry
from .base_entity import EG4DeviceEntity
from .const import DEVICE_TYPE_INVERTER, ENTITY_PREFIX, is_off_grid
from .coordinator import EG4DataUpdateCoordinator
from .utils import clean_model_name

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 2


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

    if entities:
        _LOGGER.info("Setup complete: %d binary sensor entities created", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No binary sensor entities created - no compatible devices")


class EG4OffGridBinarySensor(EG4DeviceEntity, BinarySensorEntity):
    """Binary sensor indicating the inverter is running off-grid (islanded)."""

    _attr_has_entity_name = True
    _attr_translation_key = "off_grid"
    _attr_icon = "mdi:transmission-tower-off"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the off-grid binary sensor."""
        super().__init__(coordinator, serial)
        # Name comes from the translation key (entity.binary_sensor.off_grid.name)
        # so it localizes; setting _attr_name here would override translations.
        self._attr_unique_id = f"{serial}_off_grid"
        model = device_data.get("model", "Unknown")
        model_clean = clean_model_name(model, use_underscores=True)
        self._attr_entity_id = (
            f"binary_sensor.{ENTITY_PREFIX}_{model_clean}_{serial}_off_grid"
        )

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
        when the device is gone or errored. Keep in sync with EG4BaseSensor.
        """
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
            and "error" not in self.coordinator.data["devices"][self._serial]
        )
