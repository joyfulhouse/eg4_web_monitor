"""Base entity classes for EG4 Web Monitor integration."""

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from .coordinator import EG4DataUpdateCoordinator


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
    def device_info(self) -> DeviceInfo:
        """Return device information for entity grouping.

        Returns:
            DeviceInfo dictionary containing device identifiers, name, model, etc.
            Returns empty dict if device info cannot be retrieved.
        """
        device_info = self.coordinator.get_device_info(self._serial)
        return device_info if device_info else {}

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
    def device_info(self) -> DeviceInfo:
        """Return device information for battery entity grouping.

        Returns:
            DeviceInfo dictionary containing battery device identifiers.
            Returns empty dict if battery device info cannot be retrieved.
        """
        device_info = self.coordinator.get_battery_device_info(
            self._parent_serial, self._battery_key
        )
        return device_info if device_info else {}

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
    def device_info(self) -> DeviceInfo:
        """Return device information for station entity grouping.

        Returns:
            DeviceInfo dictionary containing station identifiers.
            Returns empty dict if station device info cannot be retrieved.
        """
        device_info = self.coordinator.get_station_device_info()
        return device_info if device_info else {}

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
