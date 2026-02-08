"""Update platform for EG4 Web Monitor integration."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ENTITY_PREFIX
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 update entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[UpdateEntity] = []

    if not coordinator.data or "devices" not in coordinator.data:
        return

    # Create update entities for inverters and GridBOSS devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type")

        # Only create update entities for inverters and GridBOSS
        if device_type in ["inverter", "gridboss"]:
            entities.append(EG4FirmwareUpdateEntity(coordinator, serial))

    async_add_entities(entities)


class EG4FirmwareUpdateEntity(
    CoordinatorEntity[EG4DataUpdateCoordinator], UpdateEntity
):
    """Firmware update entity for EG4 devices."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._serial = serial

        # Get device data for naming
        device_data: dict[str, Any] = {}
        if coordinator.data and "devices" in coordinator.data:
            device_data = coordinator.data["devices"].get(serial, {})
        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "device")

        # Set unique ID and entity ID
        self._attr_unique_id = f"{serial}_firmware_update"

        if device_type == "gridboss":
            self._attr_entity_id = f"update.{ENTITY_PREFIX}_gridboss_{serial}_firmware"
        else:
            model_clean = model.replace(" ", "_").replace("-", "_").lower()
            self._attr_entity_id = (
                f"update.{ENTITY_PREFIX}_{model_clean}_{serial}_firmware"
            )

        # Entity naming
        self._attr_name = "Firmware"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for entity grouping."""
        return cast(DeviceInfo | None, self.coordinator.get_device_info(self._serial))

    def _device_data(self) -> dict[str, Any] | None:
        """Return device data dict for this serial, or None."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        result: dict[str, Any] | None = self.coordinator.data["devices"].get(
            self._serial
        )
        return result

    def _update_info_field(self, key: str) -> str | None:
        """Return a string field from firmware_update_info, or None."""
        device_data = self._device_data()
        if not device_data:
            return None
        update_info = device_data.get("firmware_update_info")
        if update_info:
            val = update_info.get(key)
            return str(val) if val is not None else None
        return None

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed firmware version."""
        device_data = self._device_data()
        if not device_data:
            return None
        version = device_data.get("firmware_version")
        return str(version) if version is not None else None

    @property
    def latest_version(self) -> str | None:
        """Return the latest available firmware version."""
        latest = self._update_info_field("latest_version")
        if latest is not None:
            return latest
        # If no update info, current version is latest
        return self.installed_version

    @property
    def release_summary(self) -> str | None:
        """Return release summary."""
        return self._update_info_field("release_summary")

    @property
    def release_url(self) -> str | None:
        """Return release URL."""
        return self._update_info_field("release_url")

    @property
    def title(self) -> str | None:
        """Return update title."""
        title = self._update_info_field("title")
        if title is not None:
            return title
        device_data = self._device_data()
        if not device_data:
            return None
        model = device_data.get("model", "Device")
        return f"{model} Firmware"

    @property
    def in_progress(self) -> bool:
        """Return if firmware update is in progress."""
        device_data = self._device_data()
        if not device_data:
            return False
        update_info = device_data.get("firmware_update_info")
        if update_info:
            return bool(update_info.get("in_progress", False))
        return False

    @property
    def update_percentage(self) -> int | None:
        """Return firmware update progress percentage (0-100)."""
        device_data = self._device_data()
        if not device_data:
            return None
        update_info = device_data.get("firmware_update_info")
        if update_info:
            percentage = update_info.get("update_percentage")
            return int(percentage) if percentage is not None else None
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "devices" in self.coordinator.data
            and self._serial in self.coordinator.data["devices"]
        )

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install firmware update."""
        _LOGGER.info("Installing firmware update for %s", self._serial)

        # Get device object from coordinator
        device = self.coordinator._get_device_object(self._serial)
        if not device:
            _LOGGER.error("Device %s not found for firmware update", self._serial)
            return

        try:
            # Start firmware update
            await device.start_firmware_update()
            _LOGGER.info("Firmware update initiated for %s", self._serial)

            # Refresh coordinator data to update status
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error(
                "Failed to start firmware update for %s: %s", self._serial, err
            )
            raise
