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

    from pylxpweb.transports import ModbusTransport
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
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODBUS_UPDATE_INTERVAL,
)
from .coordinator_mixins import (
    BackgroundTaskMixin,
    DeviceInfoMixin,
    DeviceProcessingMixin,
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
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry

        # Determine connection type (default to HTTP for backwards compatibility)
        self.connection_type: str = entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )

        # Plant ID (only used for HTTP and Hybrid modes)
        self.plant_id: str | None = entry.data.get(CONF_PLANT_ID)

        # Get Home Assistant timezone as IANA timezone string for DST detection
        iana_timezone = str(hass.config.time_zone) if hass.config.time_zone else None

        # Initialize HTTP client for HTTP and Hybrid modes
        self.client: LuxpowerClient | None = None
        if self.connection_type in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID):
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

        # Initialize Modbus transport for Modbus and Hybrid modes
        self._modbus_transport: ModbusTransport | None = None
        if self.connection_type in (CONNECTION_TYPE_MODBUS, CONNECTION_TYPE_HYBRID):
            from pylxpweb.transports import create_modbus_transport

            self._modbus_transport = create_modbus_transport(
                host=entry.data[CONF_MODBUS_HOST],
                port=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                unit_id=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                timeout=DEFAULT_MODBUS_TIMEOUT,
            )
            self._modbus_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
            self._modbus_model = entry.data.get(CONF_INVERTER_MODEL, "Unknown")

        # DST sync configuration (only for HTTP/Hybrid)
        self.dst_sync_enabled = entry.data.get(CONF_DST_SYNC, True)

        # Station object for device hierarchy (HTTP/Hybrid only)
        self.station: Station | None = None

        # Device tracking
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_sensors: dict[str, list[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: datetime | None = None
        self._parameter_refresh_interval = timedelta(hours=1)

        # DST sync tracking
        self._last_dst_sync: datetime | None = None
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

        # Inverter lookup cache for O(1) access (rebuilt when station loads)
        self._inverter_cache: dict[str, BaseInverter] = {}

        # Semaphore to limit concurrent API calls and prevent rate limiting
        self._api_semaphore = asyncio.Semaphore(3)

        # Determine update interval based on connection type
        # Modbus and Hybrid can poll faster since they use local network
        if self.connection_type in (CONNECTION_TYPE_MODBUS, CONNECTION_TYPE_HYBRID):
            update_interval = timedelta(seconds=MODBUS_UPDATE_INTERVAL)
        else:
            update_interval = timedelta(seconds=DEFAULT_UPDATE_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

        # Register shutdown listener to cancel background tasks on Home Assistant stop
        self._shutdown_listener_remove = hass.bus.async_listen_once(
            "homeassistant_stop", self._async_handle_shutdown
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from appropriate transport based on connection type.

        This is the main data update method called by Home Assistant's coordinator
        at regular intervals.

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If connection or API errors occur.
        """
        if self.connection_type == CONNECTION_TYPE_MODBUS:
            return await self._async_update_modbus_data()
        if self.connection_type == CONNECTION_TYPE_HYBRID:
            return await self._async_update_hybrid_data()
        # Default to HTTP
        return await self._async_update_http_data()

    async def _async_update_modbus_data(self) -> dict[str, Any]:
        """Fetch data from local Modbus transport.

        This method is used for Modbus-only connections where we have
        direct access to the inverter but no cloud API access.

        Returns:
            Dictionary containing device data from Modbus registers.
        """
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        if self._modbus_transport is None:
            raise UpdateFailed("Modbus transport not initialized")

        try:
            _LOGGER.debug("Fetching Modbus data for inverter %s", self._modbus_serial)

            # Ensure transport is connected
            if not self._modbus_transport.is_connected:
                await self._modbus_transport.connect()

            # Read data sequentially to avoid transaction ID desync issues
            # See: https://github.com/joyfulhouse/pylxpweb/issues/95
            runtime_data = await self._modbus_transport.read_runtime()
            energy_data = await self._modbus_transport.read_energy()
            battery_data = await self._modbus_transport.read_battery()

            # Build device data structure from transport data models
            processed = {
                "plant_id": None,  # No plant for Modbus-only
                "devices": {},
                "device_info": {},
                "last_update": dt_util.utcnow(),
                "connection_type": CONNECTION_TYPE_MODBUS,
            }

            # Create device entry for the inverter
            serial = self._modbus_serial
            device_data: dict[str, Any] = {
                "type": "inverter",
                "model": self._modbus_model,
                "serial": serial,
                "sensors": {},
                "batteries": {},
            }

            # Map runtime data to sensors
            device_data["sensors"].update(
                {
                    "pv1_voltage": runtime_data.pv1_voltage,
                    "pv1_power": runtime_data.pv1_power,
                    "pv2_voltage": runtime_data.pv2_voltage,
                    "pv2_power": runtime_data.pv2_power,
                    "pv3_voltage": runtime_data.pv3_voltage,
                    "pv3_power": runtime_data.pv3_power,
                    "ppv": runtime_data.pv_total_power,
                    "vBat": runtime_data.battery_voltage,
                    "soc": runtime_data.battery_soc,
                    "pCharge": runtime_data.battery_charge_power,
                    "pDisCharge": runtime_data.battery_discharge_power,
                    "tBat": runtime_data.battery_temperature,
                    "vacr": runtime_data.grid_voltage_r,
                    "vacs": runtime_data.grid_voltage_s,
                    "vact": runtime_data.grid_voltage_t,
                    "fac": runtime_data.grid_frequency,
                    "prec": runtime_data.grid_power,
                    "pToGrid": runtime_data.power_to_grid,
                    "pinv": runtime_data.inverter_power,
                    "pToUser": runtime_data.load_power,
                    "vepsr": runtime_data.eps_voltage_r,
                    "vepss": runtime_data.eps_voltage_s,
                    "vepst": runtime_data.eps_voltage_t,
                    "feps": runtime_data.eps_frequency,
                    "peps": runtime_data.eps_power,
                    "seps": runtime_data.eps_status,
                    "vBus1": runtime_data.bus_voltage_1,
                    "vBus2": runtime_data.bus_voltage_2,
                    "tinner": runtime_data.internal_temperature,
                    "tradiator1": runtime_data.radiator_temperature_1,
                    "tradiator2": runtime_data.radiator_temperature_2,
                    "status": runtime_data.device_status,
                }
            )

            # Map energy data to sensors
            device_data["sensors"].update(
                {
                    "todayYielding": energy_data.pv_energy_today,
                    "todayCharging": energy_data.charge_energy_today,
                    "todayDischarging": energy_data.discharge_energy_today,
                    "todayImport": energy_data.grid_import_today,
                    "todayExport": energy_data.grid_export_today,
                    "todayUsage": energy_data.load_energy_today,
                    "totalYielding": energy_data.pv_energy_total,
                    "totalCharging": energy_data.charge_energy_total,
                    "totalDischarging": energy_data.discharge_energy_total,
                    "totalImport": energy_data.grid_import_total,
                    "totalExport": energy_data.grid_export_total,
                    "totalUsage": energy_data.load_energy_total,
                }
            )

            # Add battery bank data if available
            if battery_data:
                device_data["sensors"]["battery_bank_soc"] = battery_data.soc
                device_data["sensors"]["battery_bank_voltage"] = battery_data.voltage
                device_data["sensors"]["battery_bank_charge_power"] = (
                    battery_data.charge_power
                )
                device_data["sensors"]["battery_bank_discharge_power"] = (
                    battery_data.discharge_power
                )

            processed["devices"][serial] = device_data

            # Silver tier logging
            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 Modbus connection restored for inverter %s",
                    self._modbus_serial,
                )
                self._last_available_state = True

            _LOGGER.debug(
                "Modbus update complete - PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                runtime_data.pv_total_power,
                runtime_data.battery_soc,
                runtime_data.grid_power,
            )

            return processed

        except TransportConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus connection lost for inverter %s: %s",
                    self._modbus_serial,
                    e,
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus connection failed: {e}") from e

        except TransportTimeoutError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus timeout for inverter %s: %s", self._modbus_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus timeout: {e}") from e

        except (TransportReadError, TransportError) as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus read error for inverter %s: %s", self._modbus_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus read error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Unexpected Modbus error for inverter %s: %s",
                    self._modbus_serial,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected Modbus error: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _async_update_hybrid_data(self) -> dict[str, Any]:
        """Fetch data using both Modbus (fast runtime) and HTTP (discovery/battery).

        Hybrid mode provides the best of both worlds:
        - Fast 1-second runtime updates via local Modbus
        - Device discovery and individual battery data via HTTP cloud API

        Returns:
            Dictionary containing merged data from both sources.
        """
        from pylxpweb.transports.exceptions import TransportError

        # First, get runtime data from Modbus (fast path)
        modbus_data: dict[str, Any] | None = None
        if self._modbus_transport is not None:
            try:
                if not self._modbus_transport.is_connected:
                    await self._modbus_transport.connect()

                # Read sequentially to avoid transaction ID desync issues
                runtime_data = await self._modbus_transport.read_runtime()
                energy_data = await self._modbus_transport.read_energy()
                modbus_data = {
                    "runtime": runtime_data,
                    "energy": energy_data,
                }
                _LOGGER.debug(
                    "Hybrid: Modbus runtime - PV: %.0fW, SOC: %d%%",
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                )
            except TransportError as e:
                _LOGGER.warning(
                    "Hybrid: Modbus read failed, falling back to HTTP: %s", e
                )
                modbus_data = None

        # Get HTTP data for discovery, batteries, and features not in Modbus
        http_data = await self._async_update_http_data()

        # If we have Modbus data, merge it with HTTP data for the matching inverter
        if modbus_data is not None and self._modbus_serial in http_data.get(
            "devices", {}
        ):
            device = http_data["devices"][self._modbus_serial]
            runtime = modbus_data["runtime"]
            energy = modbus_data["energy"]

            # Override runtime sensors with faster Modbus values
            device["sensors"].update(
                {
                    "pv1_voltage": runtime.pv1_voltage,
                    "pv1_power": runtime.pv1_power,
                    "pv2_voltage": runtime.pv2_voltage,
                    "pv2_power": runtime.pv2_power,
                    "ppv": runtime.pv_total_power,
                    "vBat": runtime.battery_voltage,
                    "soc": runtime.battery_soc,
                    "pCharge": runtime.battery_charge_power,
                    "pDisCharge": runtime.battery_discharge_power,
                    "vacr": runtime.grid_voltage_r,
                    "fac": runtime.grid_frequency,
                    "prec": runtime.grid_power,
                    "pToGrid": runtime.power_to_grid,
                    "pinv": runtime.inverter_power,
                    "pToUser": runtime.load_power,
                    "peps": runtime.eps_power,
                    "tinner": runtime.internal_temperature,
                }
            )

            # Override energy sensors with Modbus values
            device["sensors"].update(
                {
                    "todayYielding": energy.pv_energy_today,
                    "todayCharging": energy.charge_energy_today,
                    "todayDischarging": energy.discharge_energy_today,
                    "todayImport": energy.grid_import_today,
                    "todayExport": energy.grid_export_today,
                    "todayUsage": energy.load_energy_today,
                }
            )

            _LOGGER.debug(
                "Hybrid: Merged Modbus runtime with HTTP data for %s",
                self._modbus_serial,
            )

        http_data["connection_type"] = CONNECTION_TYPE_HYBRID
        return http_data

    async def _async_update_http_data(self) -> dict[str, Any]:
        """Fetch data from HTTP cloud API using device objects.

        This is the original HTTP-based update method using LuxpowerClient
        and Station/Inverter device objects.

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If connection or API errors occur.
        """
        if self.client is None:
            raise UpdateFailed("HTTP client not initialized")

        try:
            _LOGGER.debug("Fetching HTTP data for plant %s", self.plant_id)

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
                # Build inverter cache for O(1) lookups
                self._rebuild_inverter_cache()
            else:
                _LOGGER.debug("Refreshing station data for plant %s", self.plant_id)
                await self.station.refresh_all_data()

            # Log inverter data status after refresh
            for inverter in self.station.all_inverters:
                battery_bank = getattr(inverter, "_battery_bank", None)
                battery_count = 0
                battery_array_len = 0
                if battery_bank:
                    battery_count = getattr(battery_bank, "battery_count", 0)
                    batteries = getattr(battery_bank, "batteries", [])
                    battery_array_len = len(batteries) if batteries else 0
                _LOGGER.debug(
                    "Inverter %s (%s): has_data=%s, _runtime=%s, _energy=%s, "
                    "_battery_bank=%s, battery_count=%s, batteries_len=%s",
                    inverter.serial_number,
                    getattr(inverter, "model", "Unknown"),
                    inverter.has_data,
                    "present"
                    if getattr(inverter, "_runtime", None) is not None
                    else "None",
                    "present"
                    if getattr(inverter, "_energy", None) is not None
                    else "None",
                    "present" if battery_bank else "None",
                    battery_count,
                    battery_array_len,
                )

            # Perform DST sync if enabled and due
            if self.dst_sync_enabled and self.station and self._should_sync_dst():
                await self._perform_dst_sync()

            # Process and structure the device data
            processed_data = await self._process_station_data()
            processed_data["connection_type"] = CONNECTION_TYPE_HTTP

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

        # Process all inverters concurrently with semaphore to prevent rate limiting
        async def process_inverter_with_semaphore(
            inv: BaseInverter,
        ) -> tuple[str, dict[str, Any]]:
            """Process a single inverter with semaphore protection."""
            async with self._api_semaphore:
                try:
                    result = await self._process_inverter_object(inv)
                    return (inv.serial_number, result)
                except Exception as e:
                    _LOGGER.error(
                        "Error processing inverter %s: %s", inv.serial_number, e
                    )
                    return (
                        inv.serial_number,
                        {
                            "type": "unknown",
                            "model": "Unknown",
                            "error": str(e),
                            "sensors": {},
                            "batteries": {},
                        },
                    )

        # Process all inverters concurrently (max 3 at a time via semaphore)
        inverter_tasks = [
            process_inverter_with_semaphore(inv) for inv in self.station.all_inverters
        ]
        inverter_results = await asyncio.gather(*inverter_tasks)

        # Populate processed devices from results
        for serial, device_data in inverter_results:
            processed["devices"][serial] = device_data

        # Process parallel group data if available
        if hasattr(self.station, "parallel_groups") and self.station.parallel_groups:
            _LOGGER.debug(
                "Processing %d parallel groups", len(self.station.parallel_groups)
            )
            for group in self.station.parallel_groups:
                try:
                    await group.refresh()
                    _LOGGER.debug(
                        "Parallel group %s refreshed: energy=%s, today_yielding=%.2f kWh",
                        group.name,
                        group._energy is not None,
                        group.today_yielding,
                    )

                    group_data = await self._process_parallel_group_object(group)
                    _LOGGER.debug(
                        "Parallel group %s sensors: %s",
                        group.name,
                        list(group_data.get("sensors", {}).keys()),
                    )
                    processed["devices"][
                        f"parallel_group_{group.first_device_serial}"
                    ] = group_data

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

        # Process standalone MID devices (GridBOSS without inverters) - fixes #86
        if hasattr(self.station, "standalone_mid_devices"):
            for mid_device in self.station.standalone_mid_devices:
                try:
                    processed["devices"][
                        mid_device.serial_number
                    ] = await self._process_mid_device_object(mid_device)
                    _LOGGER.debug(
                        "Processed standalone MID device %s",
                        mid_device.serial_number,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing standalone MID device %s: %s",
                        mid_device.serial_number,
                        e,
                    )

        # Process batteries through inverter hierarchy (fixes #76)
        # This approach uses the known parent serial from the inverter object,
        # rather than trying to parse it from batteryKey (which may not contain it)
        for serial, device_data in processed["devices"].items():
            if device_data.get("type") != "inverter":
                continue

            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.debug("No inverter object found for serial %s", serial)
                continue

            # Access battery_bank through the inverter object
            battery_bank = getattr(inverter, "_battery_bank", None)
            if not battery_bank:
                _LOGGER.debug(
                    "No battery_bank for inverter %s (battery_bank=%s)",
                    serial,
                    battery_bank,
                )
                continue

            batteries = getattr(battery_bank, "batteries", None)
            if not batteries:
                _LOGGER.debug(
                    "No batteries in battery_bank for inverter %s (batteries=%s, "
                    "battery_bank.data=%s)",
                    serial,
                    batteries,
                    getattr(battery_bank, "data", None),
                )
                continue

            _LOGGER.debug("Found %d batteries for inverter %s", len(batteries), serial)

            for battery in batteries:
                try:
                    battery_key = clean_battery_display_name(
                        getattr(
                            battery,
                            "battery_key",
                            f"BAT{battery.battery_index:03d}",
                        ),
                        serial,  # Parent serial is known from inverter iteration
                    )
                    battery_sensors = self._extract_battery_from_object(battery)

                    if "batteries" not in device_data:
                        device_data["batteries"] = {}
                    device_data["batteries"][battery_key] = battery_sensors

                    _LOGGER.debug(
                        "Processed battery %s for inverter %s",
                        battery_key,
                        serial,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing battery %s for inverter %s: %s",
                        getattr(battery, "battery_sn", "unknown"),
                        serial,
                        e,
                    )

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
            task = self.hass.async_create_task(
                self._refresh_missing_parameters(inverters_needing_params, processed)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._remove_task_from_set)
            task.add_done_callback(self._log_task_exception)

        return processed

    def _rebuild_inverter_cache(self) -> None:
        """Rebuild inverter lookup cache after station load."""
        self._inverter_cache = {}
        if self.station:
            for inverter in self.station.all_inverters:
                self._inverter_cache[inverter.serial_number] = inverter
            _LOGGER.debug(
                "Rebuilt inverter cache with %d inverters",
                len(self._inverter_cache),
            )

    def get_inverter_object(self, serial: str) -> BaseInverter | None:
        """Get inverter device object by serial number (O(1) cached lookup)."""
        return self._inverter_cache.get(serial)

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

        # Check standalone MID devices (GridBOSS without inverters)
        if hasattr(self.station, "standalone_mid_devices"):
            for mid_device in self.station.standalone_mid_devices:
                if mid_device.serial_number == serial:
                    return mid_device

        return None
