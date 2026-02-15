"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import aiohttp_client

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )

    from pylxpweb.transports import (
        DongleTransport,
        ModbusSerialTransport,
        ModbusTransport,
    )
else:
    from homeassistant.helpers.update_coordinator import (  # type: ignore[assignment]
        DataUpdateCoordinator,
        UpdateFailed,
    )

from pylxpweb import LuxpowerClient
from pylxpweb.devices import Battery, Station
from pylxpweb.devices.inverters.base import BaseInverter
from .const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DATA_VALIDATION,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DONGLE_UPDATE_INTERVAL,
    CONF_DST_SYNC,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_MODBUS_UPDATE_INTERVAL,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_PLANT_ID,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_DONGLE_PORT,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_DONGLE_UPDATE_INTERVAL,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_MODBUS_UPDATE_INTERVAL,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    DOMAIN,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
)
from .coordinator_mappings import (
    _derive_model_from_family,
    _parse_inverter_family,
)
from .coordinator_http import HTTPUpdateMixin
from .coordinator_local import LocalTransportMixin
from .coordinator_mixins import (
    BackgroundTaskMixin,
    DeviceInfoMixin,
    DeviceProcessingMixin,
    DSTSyncMixin,
    FirmwareUpdateMixin,
    ParameterManagementMixin,
)

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(
    HTTPUpdateMixin,
    LocalTransportMixin,
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
    - HTTPUpdateMixin: HTTP/cloud API data fetching and processing
    - LocalTransportMixin: Local transport (Modbus/Dongle) operations
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

        # Initialize local transports from local_transports list (new format)
        # or fall back to flat keys (old format for backward compatibility)
        self._modbus_transport: ModbusTransport | ModbusSerialTransport | None = None
        self._dongle_transport: DongleTransport | None = None
        self._hybrid_local_type: str | None = None
        local_transports: list[dict[str, Any]] = entry.data.get(
            CONF_LOCAL_TRANSPORTS, []
        )

        if not local_transports:
            # DEPRECATED: Old flat-key config format (pre-v3.2).
            # Remove in v4.0 — all new configs use local_transports list.
            # This path only supports single Modbus or Dongle transport
            # and does NOT support GridBOSS devices.
            if self.connection_type == CONNECTION_TYPE_HYBRID:
                self._hybrid_local_type = entry.data.get(
                    CONF_HYBRID_LOCAL_TYPE, HYBRID_LOCAL_MODBUS
                )

            should_init_modbus = self.connection_type == CONNECTION_TYPE_MODBUS or (
                self.connection_type == CONNECTION_TYPE_HYBRID
                and self._hybrid_local_type == HYBRID_LOCAL_MODBUS
            )
            if should_init_modbus and CONF_MODBUS_HOST in entry.data:
                from pylxpweb.transports import create_transport

                family_str = entry.data.get(
                    CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
                )
                self._modbus_transport = create_transport(
                    "modbus",
                    host=entry.data[CONF_MODBUS_HOST],
                    serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                    port=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                    unit_id=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                    timeout=DEFAULT_MODBUS_TIMEOUT,
                    inverter_family=_parse_inverter_family(family_str),
                )
                self._modbus_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
                self._modbus_model = _derive_model_from_family(
                    entry.data.get(CONF_INVERTER_MODEL, ""), family_str
                )

            should_init_dongle = self.connection_type == CONNECTION_TYPE_DONGLE or (
                self.connection_type == CONNECTION_TYPE_HYBRID
                and self._hybrid_local_type == HYBRID_LOCAL_DONGLE
            )
            if should_init_dongle and CONF_DONGLE_HOST in entry.data:
                from pylxpweb.transports import create_transport

                family_str = entry.data.get(
                    CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
                )
                self._dongle_transport = create_transport(
                    "dongle",
                    host=entry.data[CONF_DONGLE_HOST],
                    dongle_serial=entry.data[CONF_DONGLE_SERIAL],
                    inverter_serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                    port=entry.data.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                    timeout=DEFAULT_DONGLE_TIMEOUT,
                    inverter_family=_parse_inverter_family(family_str),
                )
                self._dongle_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
                self._dongle_model = _derive_model_from_family(
                    entry.data.get(CONF_INVERTER_MODEL, ""), family_str
                )

        # DST sync configuration (only for HTTP/Hybrid)
        self.dst_sync_enabled = entry.data.get(CONF_DST_SYNC, True)

        # Station object for device hierarchy (HTTP/Hybrid only)
        self.station: Station | None = None

        # Local transport configs for hybrid mode (new format from CONF_LOCAL_TRANSPORTS)
        # When present, these will be used with Station.attach_local_transports()
        self._local_transport_configs: list[dict[str, Any]] = entry.data.get(
            CONF_LOCAL_TRANSPORTS, []
        )
        self._local_transports_attached = False

        # Parameter refresh tracking - read from options or use default
        self._last_parameter_refresh: datetime | None = None
        param_refresh_minutes = entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )
        self._parameter_refresh_interval = timedelta(minutes=param_refresh_minutes)

        # DST sync tracking
        self._last_dst_sync: datetime | None = None
        self._dst_sync_interval = timedelta(hours=1)

        # Background task tracking for proper cleanup
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._shutdown_listener_fired: bool = False

        # Track availability state for Silver tier logging requirement
        self._last_available_state: bool = True

        # Inverter lookup cache for O(1) access (rebuilt when station loads)
        self._inverter_cache: dict[str, BaseInverter] = {}
        self._firmware_cache: dict[str, str] = {}

        # MID device (GridBOSS) cache for LOCAL mode
        self._mid_device_cache: dict[str, Any] = {}

        # Track whether local parameters have been loaded (deferred from first refresh
        # to avoid Modbus traffic overload during HA setup timeout window)
        self._local_parameters_loaded: bool = False

        # Static-data phase: first local refresh returns pre-populated sensor keys
        # with None values for immediate entity creation (zero Modbus reads).
        self._local_static_phase_done: bool = False

        # Track serials that have already been notified about grid_type mismatch
        # to avoid creating duplicate repair issues on every poll cycle.
        self._grid_type_mismatch_notified: set[str] = set()

        # Data validation: opt-in corruption detection for local register reads.
        # When enabled, corrupt Modbus reads are rejected at two levels:
        # 1. Transport: canary-field checks (SoC>100, freq out-of-range) discard bad reads
        # 2. Device: lifetime energy monotonicity checks reject decreasing counters
        #    (validated in pylxpweb device refresh methods, not coordinator)
        self._data_validation_enabled: bool = entry.options.get(
            CONF_DATA_VALIDATION, False
        )

        # Semaphore to limit concurrent API calls and prevent rate limiting
        self._api_semaphore = asyncio.Semaphore(3)

        # Consecutive update failure counter for stale data tolerance
        self._consecutive_update_failures: int = 0

        # Read both polling intervals from options
        is_local_connection = self.connection_type in (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        default_sensor_interval = (
            DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
            if is_local_connection
            else DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
        )
        sensor_interval_seconds = entry.options.get(
            CONF_SENSOR_UPDATE_INTERVAL, default_sensor_interval
        )
        http_interval_seconds = entry.options.get(
            CONF_HTTP_POLLING_INTERVAL, DEFAULT_HTTP_POLLING_INTERVAL
        )

        # Per-transport intervals for LOCAL mode with mixed transports.
        # Fallback chain: per-transport key → legacy sensor_update_interval → default.
        legacy_sensor_interval = entry.options.get(CONF_SENSOR_UPDATE_INTERVAL)
        self._modbus_interval: int = entry.options.get(
            CONF_MODBUS_UPDATE_INTERVAL,
            legacy_sensor_interval
            if legacy_sensor_interval is not None
            else DEFAULT_MODBUS_UPDATE_INTERVAL,
        )
        self._dongle_interval: int = entry.options.get(
            CONF_DONGLE_UPDATE_INTERVAL,
            legacy_sensor_interval
            if legacy_sensor_interval is not None
            else DEFAULT_DONGLE_UPDATE_INTERVAL,
        )

        # Per-transport last-poll timestamps (monotonic)
        self._last_modbus_poll: float = 0.0
        self._last_dongle_poll: float = 0.0

        # Store HTTP polling interval for client cache alignment
        self._http_polling_interval: int = http_interval_seconds

        # Daily API counter persistence — survives config entry reloads via
        # hass.data (client instance gets destroyed/recreated on reload).
        # On reload: offset = stored total, client starts at 0, coordinator
        # returns offset + client_today. On day change: both reset to 0.
        today_ymd = time.localtime()[:3]
        daily_store = hass.data.get(f"{DOMAIN}_daily_api_count_{self.plant_id}")
        if daily_store and daily_store.get("ymd") == today_ymd:
            self._daily_api_offset: int = daily_store["count"]
        else:
            self._daily_api_offset = 0
        self._daily_api_ymd: tuple[int, int, int] = today_ymd

        # Coordinator interval depends on connection type:
        # HTTP-only: runs at HTTP polling interval (no local transport)
        # LOCAL with mixed transports: tick at fastest transport rate
        # Other local modes: use sensor interval directly
        if self.connection_type == CONNECTION_TYPE_HTTP:
            update_interval = timedelta(seconds=http_interval_seconds)
        elif self.connection_type in (CONNECTION_TYPE_LOCAL, CONNECTION_TYPE_HYBRID):
            # Both LOCAL and HYBRID use per-transport intervals.
            # HYBRID: coordinator ticks at fastest transport rate;
            # _should_poll_hybrid_local() gates MID refresh per dongle interval.
            transport_intervals = self._get_active_transport_intervals()
            fastest = (
                min(transport_intervals)
                if transport_intervals
                else sensor_interval_seconds
            )
            update_interval = timedelta(seconds=fastest)
        else:
            # MODBUS, DONGLE: single transport, use its interval directly
            update_interval = timedelta(seconds=sensor_interval_seconds)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

        # Register shutdown listener to cancel background tasks on Home Assistant stop
        # Initialize flag before registering to ensure it exists
        self._shutdown_listener_fired = False
        self._shutdown_listener_remove: Callable[[], None] | None = (
            hass.bus.async_listen_once(
                "homeassistant_stop", self._async_handle_shutdown
            )
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from appropriate transport based on connection type.

        This is the main data update method called by Home Assistant's coordinator
        at regular intervals. Implements stale data tolerance: on transport failure,
        returns last-known-good data for up to 3 consecutive failures before marking
        entities unavailable.

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails (always immediate).
            UpdateFailed: If connection or API errors occur after 3 consecutive failures.
        """
        # Clear device_info caches at the start of each update cycle
        # so fresh data is used for any new entity registrations
        self.clear_device_info_caches()

        try:
            data = await self._route_update_by_connection_type()
            self._consecutive_update_failures = 0
            return data
        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed as err:
            self._consecutive_update_failures += 1
            if self._consecutive_update_failures < 3 and self.data is not None:
                _LOGGER.warning(
                    "Update failure %d/3, serving cached data: %s",
                    self._consecutive_update_failures,
                    err,
                )
                return cast(dict[str, Any], self.data)
            raise

    async def _route_update_by_connection_type(self) -> dict[str, Any]:
        """Route to the appropriate update method based on connection type."""
        if self.connection_type == CONNECTION_TYPE_MODBUS:
            return await self._async_update_modbus_data()
        if self.connection_type == CONNECTION_TYPE_DONGLE:
            return await self._async_update_dongle_data()
        if self.connection_type == CONNECTION_TYPE_HYBRID:
            return await self._async_update_hybrid_data()
        if self.connection_type == CONNECTION_TYPE_LOCAL:
            return await self._async_update_local_data()
        # Default to HTTP
        return await self._async_update_http_data()

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

    def has_http_api(self) -> bool:
        """Check if HTTP API is available (HTTP or Hybrid mode).

        Used to determine if HTTP-only features like Quick Charge are available.

        Returns:
            True if HTTP client is configured (HTTP or Hybrid mode).
        """
        return self.client is not None

    def _has_modbus_transport(self) -> bool:
        """Check if any Modbus TCP/Serial transport is configured."""
        if self._modbus_transport is not None:
            return True
        return any(
            c.get("transport_type") in ("modbus_tcp", "modbus_serial")
            for c in self._local_transport_configs
        )

    def _has_dongle_transport(self) -> bool:
        """Check if any WiFi Dongle transport is configured."""
        if self._dongle_transport is not None:
            return True
        return any(
            c.get("transport_type") == "wifi_dongle"
            for c in self._local_transport_configs
        )

    def _get_active_transport_intervals(self) -> list[int]:
        """Return per-transport intervals for all configured transport types."""
        intervals: list[int] = []
        if self._has_modbus_transport():
            intervals.append(self._modbus_interval)
        if self._has_dongle_transport():
            intervals.append(self._dongle_interval)
        return intervals

    def _align_inverter_cache_ttls(self, inverter: Any, transport_type: str) -> None:
        """Set inverter cache TTLs to match coordinator's configured intervals.

        pylxpweb's ``set_transport_cache_ttls()`` uses hardcoded values, but the
        coordinator's intervals are user-configurable via the options flow.  This
        method overrides the pylxpweb defaults so the cache TTLs honour the
        user's settings.

        Args:
            inverter: BaseInverter instance whose cache TTLs should be set.
            transport_type: Transport type string (``modbus_tcp``, ``wifi_dongle``, etc.).
        """
        interval_map: dict[str, int] = {
            "modbus_tcp": self._modbus_interval,
            "modbus_serial": self._modbus_interval,
            "wifi_dongle": self._dongle_interval,
        }
        interval = interval_map.get(transport_type)
        if interval is None:
            return
        ttl = timedelta(seconds=interval)
        inverter._runtime_cache_ttl = ttl
        inverter._energy_cache_ttl = ttl
        inverter._battery_cache_ttl = ttl

    def _should_poll_transport(self, transport_type: str) -> bool:
        """Check whether enough time has elapsed to poll this transport type.

        Uses monotonic timestamps. Returns True on first call (timestamp==0.0).
        Updates the timestamp when returning True.
        """
        interval_map: dict[str, tuple[str, str]] = {
            "modbus_tcp": ("_last_modbus_poll", "_modbus_interval"),
            "modbus_serial": ("_last_modbus_poll", "_modbus_interval"),
            "wifi_dongle": ("_last_dongle_poll", "_dongle_interval"),
        }
        attrs = interval_map.get(transport_type)
        if attrs is None:
            return True  # Unknown type: always poll

        ts_attr, interval_attr = attrs
        now = time.monotonic()
        last_poll: float = getattr(self, ts_attr)
        interval: int = getattr(self, interval_attr)

        if now - last_poll < interval:
            return False

        setattr(self, ts_attr, now)
        return True

    async def write_named_parameter(
        self,
        parameter: str,
        value: Any,
        serial: str | None = None,
    ) -> bool:
        """Write a parameter using its HTTP API-style name.

        Uses pylxpweb's write_named_parameters() which handles:
        - Mapping parameter names to register addresses
        - Combining bit fields into register values
        - Inverter family-specific register layouts

        Args:
            parameter: Parameter name (e.g., "FUNC_EPS_EN", "HOLD_AC_CHARGE_SOC_LIMIT")
            value: Value to write (bool for FUNC_*/BIT_* params, int for others)
            serial: Device serial for LOCAL mode with multiple devices

        Returns:
            True if write succeeded, False otherwise.

        Raises:
            HomeAssistantError: If no local transport or write fails.

        Example:
            # Write a boolean bit field
            await coordinator.write_named_parameter("FUNC_EPS_EN", True)

            # Write an integer value
            await coordinator.write_named_parameter("HOLD_AC_CHARGE_SOC_LIMIT", 95)
        """
        transport = self.get_local_transport(serial)
        if not transport:
            raise HomeAssistantError("No local transport available for parameter write")

        try:
            if not transport.is_connected:
                _LOGGER.debug(
                    "Reconnecting transport for %s before writing %s", serial, parameter
                )
                await transport.connect()

            await transport.write_named_parameters({parameter: value})
            _LOGGER.debug("Wrote parameter %s = %s", parameter, value)
            return True

        except Exception as err:
            _LOGGER.error("Failed to write parameter %s: %s", parameter, err)
            raise HomeAssistantError(
                f"Failed to write parameter {parameter}: {err}"
            ) from err

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
