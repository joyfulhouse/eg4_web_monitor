"""Binary sensor platform for EG4 Web Monitor integration."""

import logging
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EG4ConfigEntry
from .const import ENTITY_PREFIX
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor binary sensor entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for binary sensor setup")
        return

    # Skip if no devices data
    if "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for binary sensor setup")
        return

    # Create dongle connectivity sensors for each inverter
    # Dongle status is fetched via get_datalog_list() during coordinator updates
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")

        # Only create dongle sensors for inverters (not parallel groups or GridBOSS)
        # Sensor is created regardless of current dongle status - status will be
        # updated on coordinator refresh. This ensures sensors exist even if
        # the first datalog fetch hasn't completed yet.
        if device_type == "inverter":
            entities.append(
                EG4DongleConnectivitySensor(
                    coordinator=coordinator,
                    serial=serial,
                )
            )
            _LOGGER.debug(
                "Created dongle connectivity sensor for inverter %s", serial
            )

    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Added %d binary sensor entities", len(entities))
    else:
        _LOGGER.debug("No binary sensor entities created")


class EG4DongleConnectivitySensor(
    CoordinatorEntity[EG4DataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for dongle (datalog) connectivity status.

    The dongle is the communication module that connects inverters to the
    cloud monitoring service. This sensor indicates whether the dongle is
    currently online and actively communicating.

    When the dongle is offline, inverter data shown in Home Assistant may
    be stale since no new data is being received from the device.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the dongle connectivity sensor.

        Args:
            coordinator: The data coordinator
            serial: Inverter serial number
        """
        super().__init__(coordinator)
        self._serial = serial

        # Get model from device data for entity naming
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Get datalog serial for additional context
        datalog_serial = coordinator.get_datalog_serial_for_inverter(serial)

        # Entity attributes
        self._attr_name = "Dongle Connectivity"
        self._attr_unique_id = f"{serial}_dongle_connectivity"

        # Generate entity_id following project conventions
        # Format: binary_sensor.eg4_{model}_{serial}_dongle_connectivity
        model_slug = model.lower().replace(" ", "_").replace("-", "_")
        self.entity_id = (
            f"binary_sensor.{ENTITY_PREFIX}_{model_slug}_{serial}_dongle_connectivity"
        )

        # Store datalog serial for extra state attributes
        self._datalog_serial = datalog_serial

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for device registry."""
        return cast(DeviceInfo | None, self.coordinator.get_device_info(self._serial))

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        The sensor is available as long as the coordinator has data.
        """
        return bool(self.coordinator.last_update_success)

    @property
    def is_on(self) -> bool | None:
        """Return True if the dongle is online.

        Returns:
            True if dongle is connected, False if disconnected, None if unknown
        """
        status = cast(
            bool | None, self.coordinator.get_dongle_status_for_inverter(self._serial)
        )
        return status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes.

        Includes the datalog serial number for reference.
        """
        attrs: dict[str, Any] = {}

        if self._datalog_serial:
            attrs["datalog_serial"] = self._datalog_serial

        # Add status text for clarity
        status = self.coordinator.get_dongle_status_for_inverter(self._serial)
        if status is not None:
            attrs["status"] = "Online" if status else "Offline"
        else:
            attrs["status"] = "Unknown"

        return attrs
