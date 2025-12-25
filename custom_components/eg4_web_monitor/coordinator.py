"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )
else:
    from homeassistant.helpers.update_coordinator import (  # type: ignore[assignment]
        DataUpdateCoordinator,
        UpdateFailed,
    )

from pylxpweb import LuxpowerClient
from pylxpweb.devices import Battery, Station
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from .const import (
    BATTERY_KEY_SEPARATOR,
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .coordinator_mixins import (
    BackgroundTaskMixin,
    DeviceInfoMixin,
    DeviceProcessingMixin,
    DongleStatusMixin,
    DSTSyncMixin,
    FirmwareUpdateMixin,
    ParameterManagementMixin,
)
from .utils import (
    CircuitBreaker,
    clean_battery_display_name,
)

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(
    DeviceProcessingMixin,
    DeviceInfoMixin,
    ParameterManagementMixin,
    DSTSyncMixin,
    BackgroundTaskMixin,
    FirmwareUpdateMixin,
    DongleStatusMixin,
    DataUpdateCoordinator[dict[str, Any]],
):
    """Class to manage fetching EG4 Web Monitor data from the API using device objects.

    This coordinator inherits from several mixins to separate concerns:
    - DeviceProcessingMixin: Processing inverters, batteries, MID devices, parallel groups
    - DeviceInfoMixin: Device info retrieval methods
    - ParameterManagementMixin: Parameter refresh operations
    - DSTSyncMixin: Daylight saving time synchronization
    - BackgroundTaskMixin: Background task management
    - FirmwareUpdateMixin: Firmware update information extraction
    - DongleStatusMixin: Dongle connection status monitoring
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]

        # Get Home Assistant timezone as IANA timezone string for DST detection
        iana_timezone = str(hass.config.time_zone) if hass.config.time_zone else None

        # Initialize Luxpower API client with injected session (Platinum tier requirement)
        self.client = LuxpowerClient(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(
                CONF_BASE_URL, "https://monitor.eg4electronics.com"
            ),
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
            session=aiohttp_client.async_get_clientsession(hass),
            iana_timezone=iana_timezone,
        )

        # DST sync configuration
        self.dst_sync_enabled = entry.data.get(CONF_DST_SYNC, True)

        # Station object for device hierarchy
        self.station: Station | None = None

        # Device tracking
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_sensors: dict[str, list[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: datetime | None = None  # type: ignore[assignment]
        self._parameter_refresh_interval = timedelta(hours=1)

        # DST sync tracking
        self._last_dst_sync: datetime | None = None  # type: ignore[assignment]
        self._dst_sync_interval = timedelta(hours=1)

        # Background task tracking for proper cleanup
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Circuit breaker for API resilience
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)

        # Temporary device info storage for model extraction
        self._temp_device_info: dict[str, Any] = {}

        # Individual energy processing queue
        self._pending_individual_energy_serials: list[str] = []

        # Track availability state for Silver tier logging requirement
        self._last_available_state: bool = True

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )

        # Register shutdown listener to cancel background tasks on Home Assistant stop
        self._shutdown_listener_remove = hass.bus.async_listen_once(
            "homeassistant_stop", self._async_handle_shutdown
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint using device objects.

        This is the main data update method called by Home Assistant's coordinator
        at regular intervals (default: 30 seconds).

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If connection or API errors occur.
        """
        try:
            _LOGGER.debug("Fetching data for plant %s", self.plant_id)

            # Check if hourly parameter refresh is due
            if self._should_refresh_parameters():
                _LOGGER.info(
                    "Hourly parameter refresh is due, refreshing all device parameters"
                )
                task = self.hass.async_create_task(self._hourly_parameter_refresh())
                self._background_tasks.add(task)
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            # Load or refresh station data using device objects
            if self.station is None:
                _LOGGER.info("Loading station data for plant %s", self.plant_id)
                self.station = await Station.load(self.client, self.plant_id)
                _LOGGER.debug(
                    "Refreshing all data after station load to populate battery details"
                )
                await self.station.refresh_all_data()
            else:
                _LOGGER.debug("Refreshing station data for plant %s", self.plant_id)
                await self.station.refresh_all_data()

            # Log inverter data status after refresh
            for inverter in self.station.all_inverters:
                _LOGGER.debug(
                    "Inverter %s (%s): has_data=%s, _runtime=%s, _energy=%s",
                    inverter.serial_number,
                    getattr(inverter, "model", "Unknown"),
                    inverter.has_data,
                    "present"
                    if getattr(inverter, "_runtime", None) is not None
                    else "None",
                    "present"
                    if getattr(inverter, "_energy", None) is not None
                    else "None",
                )

            # Perform DST sync if enabled and due
            if self.dst_sync_enabled and self.station and self._should_sync_dst():
                await self._perform_dst_sync()

            # Fetch dongle status for connectivity monitoring
            # First ensure we have datalog serial mappings (cached after first fetch)
            await self._fetch_datalog_serials()
            # Then fetch current dongle statuses (60-second cache)
            await self._fetch_dongle_statuses()

            # Process and structure the device data
            processed_data = await self._process_station_data()

            device_count = len(processed_data.get("devices", {}))
            _LOGGER.debug("Successfully updated data for %d devices", device_count)

            # Silver tier requirement: Log when service becomes available again
            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service reconnected successfully for plant %s",
                    self.plant_id,
                )
                self._last_available_state = True

            return processed_data

        except LuxpowerAuthError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to authentication error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("Authentication error: %s", e)
            raise ConfigEntryAuthFailed(f"Authentication failed: {e}") from e

        except LuxpowerConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to connection error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("Connection error: %s", e)
            raise UpdateFailed(f"Connection failed: {e}") from e

        except LuxpowerAPIError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to API error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("API error: %s", e)
            raise UpdateFailed(f"API error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to unexpected error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected error updating data: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _process_station_data(self) -> dict[str, Any]:
        """Process station data using device objects."""
        if not self.station:
            raise UpdateFailed("Station not loaded")

        processed = {
            "plant_id": self.plant_id,
            "devices": {},
            "device_info": {},
            "last_update": dt_util.utcnow(),
        }

        # Preserve existing parameter data from previous updates
        if self.data and "parameters" in self.data:
            processed["parameters"] = self.data["parameters"]

        # Add station data
        processed["station"] = {
            "name": self.station.name,
            "plant_id": self.station.id,
        }

        if timezone := getattr(self.station, "timezone", None):
            processed["station"]["timezone"] = timezone

        if location := getattr(self.station, "location", None):
            if country := getattr(location, "country", None):
                processed["station"]["country"] = country
            if address := getattr(location, "address", None):
                processed["station"]["address"] = address

        if created_date := getattr(self.station, "created_date", None):
            processed["station"]["createDate"] = created_date.isoformat()

        # Process all inverters in the station
        for inverter in self.station.all_inverters:
            try:
                processed["devices"][
                    inverter.serial_number
                ] = await self._process_inverter_object(inverter)  # type: ignore[misc]
            except Exception as e:
                _LOGGER.error(
                    "Error processing inverter %s: %s", inverter.serial_number, e
                )
                processed["devices"][inverter.serial_number] = {
                    "type": "unknown",
                    "model": "Unknown",
                    "error": str(e),
                    "sensors": {},
                    "batteries": {},
                }

        # Process parallel group data if available
        if hasattr(self.station, "parallel_groups") and self.station.parallel_groups:
            for group in self.station.parallel_groups:
                try:
                    await group.refresh()

                    processed["devices"][
                        f"parallel_group_{group.first_device_serial}"
                    ] = await self._process_parallel_group_object(group)

                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            processed["devices"][
                                group.mid_device.serial_number
                            ] = await self._process_mid_device_object(group.mid_device)
                        except Exception as e:
                            _LOGGER.error(
                                "Error processing MID device %s: %s",
                                group.mid_device.serial_number,
                                e,
                            )
                except Exception as e:
                    _LOGGER.error("Error processing parallel group: %s", e)

        # Process all batteries from station (pylxpweb 0.3.3+)
        if hasattr(self.station, "all_batteries"):
            for battery in self.station.all_batteries:
                try:
                    parent_serial = (
                        getattr(battery, "parent_serial", None)
                        or getattr(battery, "inverter_serial", None)
                        or getattr(battery, "inverter_sn", None)
                    )

                    if not parent_serial:
                        battery_key_raw = getattr(battery, "battery_key", "")
                        if battery_key_raw and BATTERY_KEY_SEPARATOR in battery_key_raw:
                            parent_serial = battery_key_raw.split(
                                BATTERY_KEY_SEPARATOR
                            )[0]
                        elif battery_key_raw and "_" in battery_key_raw:
                            parts = battery_key_raw.split("_")
                            if len(parts) > 0 and parts[0].isdigit():
                                parent_serial = parts[0]

                    if parent_serial and parent_serial in processed["devices"]:
                        battery_key = clean_battery_display_name(
                            getattr(
                                battery,
                                "battery_key",
                                f"BAT{battery.battery_index:03d}",
                            ),
                            parent_serial,
                        )
                        battery_sensors = self._extract_battery_from_object(battery)

                        if "batteries" not in processed["devices"][parent_serial]:
                            processed["devices"][parent_serial]["batteries"] = {}
                        processed["devices"][parent_serial]["batteries"][
                            battery_key
                        ] = battery_sensors
                    else:
                        _LOGGER.warning(
                            "Battery %s parent inverter '%s' not found in processed devices",
                            getattr(battery, "battery_sn", "unknown"),
                            parent_serial,
                        )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing battery %s: %s",
                        getattr(battery, "battery_sn", "unknown"),
                        e,
                    )
        else:
            _LOGGER.warning("Station does not have 'all_batteries' attribute")

        # Check if we need to refresh parameters for any inverters
        if "parameters" not in processed:
            processed["parameters"] = {}

        inverters_needing_params = []
        for serial, device_data in processed["devices"].items():
            if (
                device_data.get("type") == "inverter"
                and serial not in processed["parameters"]
            ):
                inverters_needing_params.append(serial)

        if inverters_needing_params:
            _LOGGER.info(
                "Refreshing parameters for %d new inverters: %s",
                len(inverters_needing_params),
                inverters_needing_params,
            )
            self.hass.async_create_task(
                self._refresh_missing_parameters(inverters_needing_params, processed)
            )

        return processed

    def get_inverter_object(self, serial: str) -> BaseInverter | None:
        """Get inverter device object by serial number."""
        if not self.station:
            return None

        for inverter in self.station.all_inverters:
            if inverter.serial_number == serial:
                return inverter

        return None

    def get_battery_object(self, serial: str, battery_index: int) -> Battery | None:
        """Get battery object by inverter serial and battery index."""
        inverter = self.get_inverter_object(serial)
        battery_bank = getattr(inverter, "_battery_bank", None) if inverter else None
        if not battery_bank:
            return None

        if not hasattr(battery_bank, "batteries"):
            return None

        for battery in battery_bank.batteries:
            if battery.index == battery_index:
                return cast(Battery, battery)

        return None

    def _get_device_object(self, serial: str) -> BaseInverter | Any | None:
        """Get device object (inverter or MID device) by serial number.

        Used by Update platform to get device objects for firmware updates.
        Returns BaseInverter for inverters, or MIDDevice (typed as Any) for MID devices.
        """
        if not self.station:
            return None

        for inverter in self.station.all_inverters:
            if inverter.serial_number == serial:
                return inverter

        if hasattr(self.station, "parallel_groups"):
            for group in self.station.parallel_groups:
                if hasattr(group, "mid_device") and group.mid_device:
                    if group.mid_device.serial_number == serial:
                        return group.mid_device

        return None
