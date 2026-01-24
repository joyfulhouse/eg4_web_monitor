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
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_DONGLE_PORT,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    DONGLE_UPDATE_INTERVAL,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
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

        # Determine hybrid local transport type (modbus > dongle priority)
        # For hybrid mode, check which local transport is configured
        self._hybrid_local_type: str | None = None
        if self.connection_type == CONNECTION_TYPE_HYBRID:
            self._hybrid_local_type = entry.data.get(
                CONF_HYBRID_LOCAL_TYPE, HYBRID_LOCAL_MODBUS
            )

        # Initialize Modbus transport for Modbus mode or Hybrid with Modbus local
        self._modbus_transport: ModbusTransport | None = None
        should_init_modbus = self.connection_type == CONNECTION_TYPE_MODBUS or (
            self.connection_type == CONNECTION_TYPE_HYBRID
            and self._hybrid_local_type == HYBRID_LOCAL_MODBUS
        )
        if should_init_modbus:
            from pylxpweb.devices.inverters._features import InverterFamily
            from pylxpweb.transports import create_modbus_transport

            # Convert string family to InverterFamily enum
            inverter_family = None
            family_str = entry.data.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY)
            if family_str:
                try:
                    inverter_family = InverterFamily(family_str)
                except ValueError:
                    _LOGGER.warning(
                        "Unknown inverter family '%s', using default", family_str
                    )

            self._modbus_transport = create_modbus_transport(
                host=entry.data[CONF_MODBUS_HOST],
                port=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                unit_id=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                timeout=DEFAULT_MODBUS_TIMEOUT,
                inverter_family=inverter_family,
            )
            self._modbus_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
            self._modbus_model = entry.data.get(CONF_INVERTER_MODEL, "Unknown")

        # Initialize Dongle transport for Dongle mode or Hybrid with Dongle local
        self._dongle_transport: Any = None
        should_init_dongle = self.connection_type == CONNECTION_TYPE_DONGLE or (
            self.connection_type == CONNECTION_TYPE_HYBRID
            and self._hybrid_local_type == HYBRID_LOCAL_DONGLE
        )
        if should_init_dongle:
            from pylxpweb.devices.inverters._features import InverterFamily
            from pylxpweb.transports import create_dongle_transport

            # Convert string family to InverterFamily enum
            inverter_family = None
            family_str = entry.data.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY)
            if family_str:
                try:
                    inverter_family = InverterFamily(family_str)
                except ValueError:
                    _LOGGER.warning(
                        "Unknown inverter family '%s', using default", family_str
                    )

            self._dongle_transport = create_dongle_transport(
                host=entry.data[CONF_DONGLE_HOST],
                dongle_serial=entry.data[CONF_DONGLE_SERIAL],
                inverter_serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                port=entry.data.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                timeout=DEFAULT_DONGLE_TIMEOUT,
                inverter_family=inverter_family,
            )
            self._dongle_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
            self._dongle_model = entry.data.get(CONF_INVERTER_MODEL, "Unknown")

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
        # Modbus, Dongle, and Hybrid can poll faster since they use local network
        if self.connection_type == CONNECTION_TYPE_MODBUS:
            update_interval = timedelta(seconds=MODBUS_UPDATE_INTERVAL)
        elif self.connection_type == CONNECTION_TYPE_HYBRID:
            # Use appropriate interval based on hybrid local transport type
            if self._hybrid_local_type == HYBRID_LOCAL_DONGLE:
                update_interval = timedelta(seconds=DONGLE_UPDATE_INTERVAL)
            else:
                update_interval = timedelta(seconds=MODBUS_UPDATE_INTERVAL)
        elif self.connection_type == CONNECTION_TYPE_DONGLE:
            update_interval = timedelta(seconds=DONGLE_UPDATE_INTERVAL)
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
        if self.connection_type == CONNECTION_TYPE_DONGLE:
            return await self._async_update_dongle_data()
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

            # Map runtime data to sensors using SENSOR_TYPES keys
            # Note: Keys must match SENSOR_TYPES definitions in const.py
            device_data["sensors"].update(
                {
                    # PV/Solar input
                    "pv1_voltage": runtime_data.pv1_voltage,
                    "pv1_power": runtime_data.pv1_power,
                    "pv2_voltage": runtime_data.pv2_voltage,
                    "pv2_power": runtime_data.pv2_power,
                    "pv3_voltage": runtime_data.pv3_voltage,
                    "pv3_power": runtime_data.pv3_power,
                    "pv_total_power": runtime_data.pv_total_power,
                    # Battery
                    "battery_voltage": runtime_data.battery_voltage,
                    "battery_current": runtime_data.battery_current,
                    "state_of_charge": runtime_data.battery_soc,
                    "battery_charge_power": runtime_data.battery_charge_power,
                    "battery_discharge_power": runtime_data.battery_discharge_power,
                    "battery_temperature": runtime_data.battery_temperature,
                    # Grid - all phases (use _l1/_l2/_l3 to match SENSOR_TYPES)
                    "grid_voltage_r": runtime_data.grid_voltage_r,
                    "grid_voltage_s": runtime_data.grid_voltage_s,
                    "grid_voltage_t": runtime_data.grid_voltage_t,
                    "grid_current_l1": runtime_data.grid_current_r,
                    "grid_current_l2": runtime_data.grid_current_s,
                    "grid_current_l3": runtime_data.grid_current_t,
                    "grid_frequency": runtime_data.grid_frequency,
                    "grid_power": runtime_data.grid_power,
                    "grid_export_power": runtime_data.power_to_grid,
                    # Inverter output
                    "ac_power": runtime_data.inverter_power,
                    "load_power": runtime_data.load_power,
                    # EPS/Backup
                    "eps_voltage_r": runtime_data.eps_voltage_r,
                    "eps_voltage_s": runtime_data.eps_voltage_s,
                    "eps_voltage_t": runtime_data.eps_voltage_t,
                    "eps_frequency": runtime_data.eps_frequency,
                    "eps_power": runtime_data.eps_power,
                    # Generator (if available from Modbus)
                    "generator_voltage": runtime_data.generator_voltage,
                    "generator_frequency": runtime_data.generator_frequency,
                    "generator_power": runtime_data.generator_power,
                    # Bus voltages
                    "bus1_voltage": runtime_data.bus_voltage_1,
                    "bus2_voltage": runtime_data.bus_voltage_2,
                    # Temperatures
                    "internal_temperature": runtime_data.internal_temperature,
                    "radiator1_temperature": runtime_data.radiator_temperature_1,
                    "radiator2_temperature": runtime_data.radiator_temperature_2,
                    # Status
                    "status_code": runtime_data.device_status,
                }
            )

            # Map energy data to sensors using SENSOR_TYPES keys
            device_data["sensors"].update(
                {
                    # Daily energy (kWh)
                    "yield": energy_data.pv_energy_today,
                    "charging": energy_data.charge_energy_today,
                    "discharging": energy_data.discharge_energy_today,
                    "grid_import": energy_data.grid_import_today,
                    "grid_export": energy_data.grid_export_today,
                    "load": energy_data.load_energy_today,
                    # Lifetime energy (kWh)
                    "yield_lifetime": energy_data.pv_energy_total,
                    "charging_lifetime": energy_data.charge_energy_total,
                    "discharging_lifetime": energy_data.discharge_energy_total,
                    "grid_import_lifetime": energy_data.grid_import_total,
                    "grid_export_lifetime": energy_data.grid_export_total,
                    "load_lifetime": energy_data.load_energy_total,
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

    async def _async_update_dongle_data(self) -> dict[str, Any]:
        """Fetch data from local WiFi dongle transport.

        This method is used for Dongle-only connections where we have
        direct access to the inverter via the WiFi dongle's TCP interface
        on port 8000, without requiring additional RS485 hardware.

        Returns:
            Dictionary containing device data from dongle registers.
        """
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        if self._dongle_transport is None:
            raise UpdateFailed("Dongle transport not initialized")

        try:
            _LOGGER.debug("Fetching dongle data for inverter %s", self._dongle_serial)

            # Ensure transport is connected
            if not self._dongle_transport.is_connected:
                await self._dongle_transport.connect()

            # Read data from dongle
            runtime_data = await self._dongle_transport.read_runtime()
            energy_data = await self._dongle_transport.read_energy()
            battery_data = await self._dongle_transport.read_battery()

            # Build device data structure from transport data models
            processed = {
                "plant_id": None,  # No plant for Dongle-only
                "devices": {},
                "device_info": {},
                "last_update": dt_util.utcnow(),
                "connection_type": CONNECTION_TYPE_DONGLE,
            }

            # Create device entry for the inverter
            serial = self._dongle_serial
            device_data: dict[str, Any] = {
                "type": "inverter",
                "model": self._dongle_model,
                "serial": serial,
                "sensors": {},
                "batteries": {},
            }

            # Map runtime data to sensors using SENSOR_TYPES keys (same as Modbus)
            # Note: Keys must match SENSOR_TYPES definitions in const.py
            device_data["sensors"].update(
                {
                    # PV/Solar input
                    "pv1_voltage": runtime_data.pv1_voltage,
                    "pv1_power": runtime_data.pv1_power,
                    "pv2_voltage": runtime_data.pv2_voltage,
                    "pv2_power": runtime_data.pv2_power,
                    "pv3_voltage": runtime_data.pv3_voltage,
                    "pv3_power": runtime_data.pv3_power,
                    "pv_total_power": runtime_data.pv_total_power,
                    # Battery
                    "battery_voltage": runtime_data.battery_voltage,
                    "battery_current": runtime_data.battery_current,
                    "state_of_charge": runtime_data.battery_soc,
                    "battery_charge_power": runtime_data.battery_charge_power,
                    "battery_discharge_power": runtime_data.battery_discharge_power,
                    "battery_temperature": runtime_data.battery_temperature,
                    # Grid - all phases (use _l1/_l2/_l3 to match SENSOR_TYPES)
                    "grid_voltage_r": runtime_data.grid_voltage_r,
                    "grid_voltage_s": runtime_data.grid_voltage_s,
                    "grid_voltage_t": runtime_data.grid_voltage_t,
                    "grid_current_l1": runtime_data.grid_current_r,
                    "grid_current_l2": runtime_data.grid_current_s,
                    "grid_current_l3": runtime_data.grid_current_t,
                    "grid_frequency": runtime_data.grid_frequency,
                    "grid_power": runtime_data.grid_power,
                    "grid_export_power": runtime_data.power_to_grid,
                    # Inverter output
                    "ac_power": runtime_data.inverter_power,
                    "load_power": runtime_data.load_power,
                    # EPS/Backup
                    "eps_voltage_r": runtime_data.eps_voltage_r,
                    "eps_voltage_s": runtime_data.eps_voltage_s,
                    "eps_voltage_t": runtime_data.eps_voltage_t,
                    "eps_frequency": runtime_data.eps_frequency,
                    "eps_power": runtime_data.eps_power,
                    # Generator (if available from Dongle)
                    "generator_voltage": runtime_data.generator_voltage,
                    "generator_frequency": runtime_data.generator_frequency,
                    "generator_power": runtime_data.generator_power,
                    # Bus voltages
                    "bus1_voltage": runtime_data.bus_voltage_1,
                    "bus2_voltage": runtime_data.bus_voltage_2,
                    # Temperatures
                    "internal_temperature": runtime_data.internal_temperature,
                    "radiator1_temperature": runtime_data.radiator_temperature_1,
                    "radiator2_temperature": runtime_data.radiator_temperature_2,
                    # Status
                    "status_code": runtime_data.device_status,
                }
            )

            # Map energy data to sensors using SENSOR_TYPES keys
            device_data["sensors"].update(
                {
                    # Daily energy (kWh)
                    "yield": energy_data.pv_energy_today,
                    "charging": energy_data.charge_energy_today,
                    "discharging": energy_data.discharge_energy_today,
                    "grid_import": energy_data.grid_import_today,
                    "grid_export": energy_data.grid_export_today,
                    "load": energy_data.load_energy_today,
                    # Lifetime energy (kWh)
                    "yield_lifetime": energy_data.pv_energy_total,
                    "charging_lifetime": energy_data.charge_energy_total,
                    "discharging_lifetime": energy_data.discharge_energy_total,
                    "grid_import_lifetime": energy_data.grid_import_total,
                    "grid_export_lifetime": energy_data.grid_export_total,
                    "load_lifetime": energy_data.load_energy_total,
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
                    "EG4 Dongle connection restored for inverter %s",
                    self._dongle_serial,
                )
                self._last_available_state = True

            _LOGGER.debug(
                "Dongle update complete - PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                runtime_data.pv_total_power,
                runtime_data.battery_soc,
                runtime_data.grid_power,
            )

            return processed

        except TransportConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle connection lost for inverter %s: %s",
                    self._dongle_serial,
                    e,
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle connection failed: {e}") from e

        except TransportTimeoutError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle timeout for inverter %s: %s", self._dongle_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle timeout: {e}") from e

        except (TransportReadError, TransportError) as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle read error for inverter %s: %s", self._dongle_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle read error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Unexpected Dongle error for inverter %s: %s",
                    self._dongle_serial,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected Dongle error: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _async_update_hybrid_data(self) -> dict[str, Any]:
        """Fetch data using local transport (Modbus/Dongle) + HTTP (discovery/battery).

        Hybrid mode provides the best of both worlds:
        - Fast 1-5 second runtime updates via local transport (Modbus or Dongle)
        - Device discovery and individual battery data via HTTP cloud API

        Priority: Modbus > Dongle > HTTP-only (based on configured local transport)

        Returns:
            Dictionary containing merged data from both sources.
        """
        from pylxpweb.transports.exceptions import TransportError

        # Try to get local data from configured transport (Modbus or Dongle)
        local_data: dict[str, Any] | None = None
        local_serial: str = ""
        local_transport_name: str = ""

        # Priority 1: Try Modbus if configured
        if self._modbus_transport is not None:
            local_transport_name = "Modbus"
            local_serial = self._modbus_serial
            try:
                if not self._modbus_transport.is_connected:
                    await self._modbus_transport.connect()

                # Read sequentially to avoid transaction ID desync issues
                runtime_data = await self._modbus_transport.read_runtime()
                energy_data = await self._modbus_transport.read_energy()
                local_data = {
                    "runtime": runtime_data,
                    "energy": energy_data,
                }
                _LOGGER.debug(
                    "Hybrid: %s runtime - PV: %.0fW, SOC: %d%%",
                    local_transport_name,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                )
            except TransportError as e:
                _LOGGER.warning(
                    "Hybrid: %s read failed, falling back to HTTP: %s",
                    local_transport_name,
                    e,
                )
                local_data = None

        # Priority 2: Try Dongle if configured and Modbus not available/failed
        if local_data is None and self._dongle_transport is not None:
            local_transport_name = "Dongle"
            local_serial = self._dongle_serial
            try:
                if not self._dongle_transport.is_connected:
                    await self._dongle_transport.connect()

                runtime_data = await self._dongle_transport.read_runtime()
                energy_data = await self._dongle_transport.read_energy()
                local_data = {
                    "runtime": runtime_data,
                    "energy": energy_data,
                }
                _LOGGER.debug(
                    "Hybrid: %s runtime - PV: %.0fW, SOC: %d%%",
                    local_transport_name,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                )
            except TransportError as e:
                _LOGGER.warning(
                    "Hybrid: %s read failed, falling back to HTTP-only: %s",
                    local_transport_name,
                    e,
                )
                local_data = None

        # Get HTTP data for discovery, batteries, and features not in local transport
        http_data = await self._async_update_http_data()

        # If we have local data, merge it with HTTP data for the matching inverter
        if local_data is not None and local_serial in http_data.get("devices", {}):
            self._merge_local_data_with_http(
                http_data["devices"][local_serial],
                local_data["runtime"],
                local_data["energy"],
                local_serial,
                local_transport_name,
            )

        http_data["connection_type"] = CONNECTION_TYPE_HYBRID
        return http_data

    def _merge_local_data_with_http(
        self,
        device: dict[str, Any],
        runtime: Any,
        energy: Any,
        serial: str,
        transport_name: str,
    ) -> None:
        """Merge local transport data with HTTP device data.

        This method overrides HTTP sensor values with faster local transport values.
        All sensors available from local transport are merged, not just a subset.

        Args:
            device: The device dictionary from HTTP data to update
            runtime: InverterRuntimeData from local transport
            energy: InverterEnergyData from local transport
            serial: Inverter serial number for logging
            transport_name: Name of local transport for logging (Modbus/Dongle)
        """
        # Override runtime sensors with faster local values
        # Uses SENSOR_TYPES keys to match HTTP data structure
        # Include ALL available sensors from local transport for maximum coverage
        device["sensors"].update(
            {
                # PV/Solar input - all strings
                "pv1_voltage": runtime.pv1_voltage,
                "pv1_power": runtime.pv1_power,
                "pv2_voltage": runtime.pv2_voltage,
                "pv2_power": runtime.pv2_power,
                "pv3_voltage": runtime.pv3_voltage,
                "pv3_power": runtime.pv3_power,
                "pv_total_power": runtime.pv_total_power,
                # Battery
                "battery_voltage": runtime.battery_voltage,
                "battery_current": runtime.battery_current,
                "state_of_charge": runtime.battery_soc,
                "battery_charge_power": runtime.battery_charge_power,
                "battery_discharge_power": runtime.battery_discharge_power,
                "battery_temperature": runtime.battery_temperature,
                # Grid - all phases (use _l1/_l2/_l3 to match SENSOR_TYPES)
                "grid_voltage_r": runtime.grid_voltage_r,
                "grid_voltage_s": runtime.grid_voltage_s,
                "grid_voltage_t": runtime.grid_voltage_t,
                "grid_current_l1": runtime.grid_current_r,
                "grid_current_l2": runtime.grid_current_s,
                "grid_current_l3": runtime.grid_current_t,
                "grid_frequency": runtime.grid_frequency,
                "grid_power": runtime.grid_power,
                "grid_export_power": runtime.power_to_grid,
                # Inverter output
                "ac_power": runtime.inverter_power,
                "load_power": runtime.load_power,
                # EPS/Backup - all phases
                "eps_voltage_r": runtime.eps_voltage_r,
                "eps_voltage_s": runtime.eps_voltage_s,
                "eps_voltage_t": runtime.eps_voltage_t,
                "eps_frequency": runtime.eps_frequency,
                "eps_power": runtime.eps_power,
                # Generator (if available from Modbus/Dongle)
                "generator_voltage": runtime.generator_voltage,
                "generator_frequency": runtime.generator_frequency,
                "generator_power": runtime.generator_power,
                # Bus voltages
                "bus1_voltage": runtime.bus_voltage_1,
                "bus2_voltage": runtime.bus_voltage_2,
                # Temperatures
                "internal_temperature": runtime.internal_temperature,
                "radiator1_temperature": runtime.radiator_temperature_1,
                "radiator2_temperature": runtime.radiator_temperature_2,
                # Status
                "status_code": runtime.device_status,
            }
        )

        # Override energy sensors with local values
        device["sensors"].update(
            {
                # Daily energy (kWh)
                "yield": energy.pv_energy_today,
                "charging": energy.charge_energy_today,
                "discharging": energy.discharge_energy_today,
                "grid_import": energy.grid_import_today,
                "grid_export": energy.grid_export_today,
                "load": energy.load_energy_today,
                # Lifetime energy (kWh)
                "yield_lifetime": energy.pv_energy_total,
                "charging_lifetime": energy.charge_energy_total,
                "discharging_lifetime": energy.discharge_energy_total,
                "grid_import_lifetime": energy.grid_import_total,
                "grid_export_lifetime": energy.grid_export_total,
                "load_lifetime": energy.load_energy_total,
            }
        )

        _LOGGER.debug(
            "Hybrid: Merged %s runtime with HTTP data for %s",
            transport_name,
            serial,
        )

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
