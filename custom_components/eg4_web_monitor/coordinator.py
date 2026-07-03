"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from collections.abc import Callable, Collection
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
from pylxpweb.devices import Station
from pylxpweb.devices.inverters.base import BaseInverter
from .const import (
    BLOCK_SIZE_PRESET_REGISTERS,
    CONF_BASE_URL,
    CONF_CHARGE_CONTROL_MODE,
    CONF_CONNECTION_TYPE,
    CONF_DATA_VALIDATION,
    CONF_DISCHARGE_CONTROL_MODE,
    CONF_DONGLE_HOST,
    CONF_MODBUS_BLOCK_SIZE,
    CONTROL_MODE_SOC,
    CONTROL_MODE_VOLTAGE,
    DEFAULT_CONTROL_MODE,
    DEFAULT_MODBUS_BLOCK_SIZE,
    PARAM_FUNC_BAT_CHARGE_CONTROL,
    PARAM_FUNC_BAT_DISCHARGE_CONTROL,
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
from .battery_migration import async_migrate_battery_keys
from .coordinator_mappings import (
    _derive_model_from_family,
    _parse_inverter_family,
    input_block_size_kwargs,
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
from .const.sensors import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)

# Sensor keys with state_class=total_increasing.  On startup (self.data is
# None), zeros for these keys are replaced with None in the coordinator cache
# to prevent HA's statistics from recording false counter resets.
_TOTAL_INCREASING_KEYS: frozenset[str] = frozenset(
    k
    for k, v in SENSOR_TYPES.items()
    if isinstance(v, dict) and v.get("state_class") == "total_increasing"
)


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

        # Plant ID (only used for HTTP and Hybrid modes). Entries created
        # before the #275 fix may store it as int; normalize to str so all
        # derived identifiers (f-string based) stay identical either way.
        plant_id = entry.data.get(CONF_PLANT_ID)
        self.plant_id: str | None = str(plant_id) if plant_id is not None else None

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

        # Modbus input-register read block size (#254): preset option mapped
        # to pylxpweb's max registers per coalesced read. Conservative (40)
        # keeps the plain grouped reads; Fast (120) consolidates them on
        # hardware that supports large reads. Passed to every local transport
        # via input_block_size_kwargs() (feature-detected, so released
        # pylxpweb without the parameter stays silently conservative).
        self._max_input_block_size: int = BLOCK_SIZE_PRESET_REGISTERS.get(
            entry.options.get(CONF_MODBUS_BLOCK_SIZE, DEFAULT_MODBUS_BLOCK_SIZE),
            BLOCK_SIZE_PRESET_REGISTERS[DEFAULT_MODBUS_BLOCK_SIZE],
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
                    **input_block_size_kwargs(self._max_input_block_size),
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
                    **input_block_size_kwargs(self._max_input_block_size),
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
        # Serials whose local-transport attach failed (commonly: the dongle's
        # single TCP slot still held by the previous session right after an
        # HA restart). Retried with a bounded interval each update cycle and
        # cleared on success — without this, a transient boot-time failure
        # parked the device on cloud data until a manual reload (eg4-05l).
        self._failed_attach_serials: set[str] = set()
        self._last_attach_retry: float = 0.0
        # Per-serial monotonic stamps for DEGRADED cloud refreshes: a hybrid
        # coordinator can tick at the fastest LOCAL interval (5s) — degraded
        # devices' cloud fallback must stay throttled to the cloud-safe HTTP
        # interval regardless (review HIGH on eg4-o5m).
        self._last_degraded_cloud_refresh: dict[str, float] = {}
        # Serials with an open transport_link_down Repairs issue (eg4-57g):
        # one-shot per down transition, cleared when the link recovers.
        self._link_down_notified: set[str] = set()

        # Parameter refresh tracking - read from options or use default
        self._last_parameter_refresh: datetime | None = None
        param_refresh_minutes = entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )
        self._parameter_refresh_interval = timedelta(minutes=param_refresh_minutes)
        # Sticky-parameter retry tracking (#282): ``_last_parameter_attempt``
        # rate-floors the early retries a failed/partial/missed read re-arms.
        self._last_parameter_attempt: datetime | None = None
        # Whether the most recent _read_modbus_parameters() call read every
        # register range (LOCAL/HYBRID targeted entity-parameter reads).
        self._last_param_read_complete: bool = True
        # Per-device parameter retry queue (#282 P1-A): inverters that did not
        # COMPLETE their targeted parameter read on a due cycle (transport-
        # interval skip, pre-param failure, or partial read).  Retried on
        # floored cycles without re-reading healthy siblings; drained on each
        # device's own successful read.
        self._param_retry_pending: set[str] = set()
        # Per-cycle state for the retry queue (reset in the local update loop).
        self._param_retry_due: bool = False
        self._param_completed_this_cycle: set[str] = set()
        self._param_attempted_this_cycle: bool = False

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

        # Per-serial Quick Charge duration preference (minutes), set via the
        # Quick Charge Duration number entity. Defaults to
        # QUICK_CHARGE_DURATION_DEFAULT when a serial has no stored value.
        self._quick_charge_minutes: dict[str, int] = {}

        # MID device (GridBOSS) cache for LOCAL mode
        self._mid_device_cache: dict[str, Any] = {}

        # Round-robin battery cache for LOCAL/HYBRID Modbus.
        # Some inverter firmware rotates which physical batteries appear in the
        # fixed register slots (5002+) on each CAN bus poll.  We accumulate
        # readings keyed by battery serial so that all batteries eventually
        # appear as entities regardless of which slot they occupied.
        # Outer key = inverter serial, inner key = battery serial.
        self._battery_rr_cache: dict[str, dict[str, dict[str, Any]]] = {}
        # Legacy positional key shadow: battery serial → "inverter-NN" key in
        # first-seen order — the exact assignment the pre-#252 LOCAL path used.
        # Kept only so existing registry entries can be migrated to the
        # canonical serial-based keys (see battery_migration.py).
        self._battery_serial_to_key: dict[str, dict[str, str]] = {}
        # Next available index per inverter for the legacy shadow assignment.
        self._battery_next_index: dict[str, int] = {}
        # One-shot guard for #252 battery-identity registry migrations:
        # (inverter serial, legacy key) pairs already migrated this session.
        self._battery_key_migrations_done: set[tuple[str, str]] = set()
        # Cache keys created by the no-serial positional fallback (per
        # inverter).  When a serial later claims the same slot, the fallback
        # entry is retired — it was the same physical battery (#252 P0).
        self._battery_fallback_keys: dict[str, set[str]] = {}
        # Consecutive serial-less polls per (inverter, slot).  A positional
        # fallback entity is only exposed after _NO_SERIAL_EXPOSE_POLLS so a
        # slow-to-arrive serial can claim the identity before any positional
        # entity is instantiated (#252 cold start).
        self._battery_noserial_polls: dict[str, dict[int, int]] = {}
        # Inverters whose battery-identity migration is disabled this session
        # (rotating pack with unattributable positional history, or a
        # duplicate/misreported battery serial).  Sticky until restart;
        # positional registry rows are left untouched as orphans.
        self._battery_migration_suppressed: set[str] = set()
        # Last published battery mapping per inverter (#258 beta.18): battery
        # entity availability is key-presence in device_data["batteries"], and
        # the HYBRID/CLOUD paths rebuild that dict from the cloud payload as
        # the BASELINE every cycle — a battery the cloud momentarily omits
        # (rotating >4 packs feed the cloud through the same firmware page
        # rotation) vanished and its entities flipped unavailable.  A battery
        # once published is carried forward with its last-known data instead;
        # staleness stays visible via battery_last_seen, never via
        # availability flapping.  Outer key = inverter serial.
        self._battery_carry_forward: dict[str, dict[str, dict[str, Any]]] = {}

        # Shared-battery secondary inverters: in parallel systems the CAN bus
        # connects only to the primary.  Secondaries (role >= 2) with
        # battery_count=0 get their battery bank sensors mirrored from the
        # primary.  This set tracks serials we've already logged about (one-shot).
        self._shared_battery_logged: set[str] = set()

        # Track whether local parameters have been loaded (deferred from first refresh
        # to avoid Modbus traffic overload during HA setup timeout window)
        self._local_parameters_loaded: bool = False

        # Static-data phase: first local refresh returns pre-populated sensor keys
        # with None values for immediate entity creation (zero Modbus reads).
        self._local_static_phase_done: bool = False

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

            # On startup (no prior cache), suppress 0 values for
            # total_increasing sensors.  These zeros are not real readings —
            # they come from default-initialized device models before the
            # first genuine Modbus/API response.  Publishing 0 causes HA's
            # statistics to record a false counter reset, permanently
            # inflating long-term energy totals.
            if self.data is None:
                for device_data in data.get("devices", {}).values():
                    sensors = device_data.get("sensors")
                    if not sensors:
                        continue
                    for key in _TOTAL_INCREASING_KEYS:
                        if key in sensors and sensors[key] == 0:
                            sensors[key] = None

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

    def _align_inverter_cache_ttls(
        self, inverter: BaseInverter, transport_type: str
    ) -> None:
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
        inverter.set_cache_ttls(runtime=ttl, energy=ttl, battery=ttl)

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

    def _suppress_battery_migration(
        self, inverter_serial: str, reason: str, *, level: int = logging.INFO
    ) -> None:
        """Disable #252 battery-identity migration for an inverter (sticky).

        Used when the legacy positional history cannot be attributed safely:
        rotating packs (positional keys were assigned in an order this
        session cannot reconstruct) or duplicate/misreported battery serials.
        Positional registry rows are left untouched as orphans — safe beats
        clever.  Logged once per inverter per session.
        """
        if inverter_serial in self._battery_migration_suppressed:
            return
        self._battery_migration_suppressed.add(inverter_serial)
        _LOGGER.log(
            level,
            "Battery identity migration disabled for inverter %s this "
            "session: %s. Existing positional battery entities are left "
            "untouched; stale ones can be removed manually from the device "
            "page (#252)",
            inverter_serial,
            reason,
        )

    def _register_battery_key_migrations(
        self,
        inverter_serial: str,
        pairs: dict[str, str],
        active_keys: Collection[str],
    ) -> None:
        """Run the #252 legacy→canonical battery-key registry migration.

        Called from the battery processing paths (LOCAL round-robin merge,
        HYBRID cloud baseline, CLOUD fallback) once the legacy positional key
        each battery *would* have had is known alongside its canonical
        serial-based key.

        Args:
            inverter_serial: Parent inverter serial number.
            pairs: Mapping of legacy positional key → canonical key.
            active_keys: Battery keys currently in use for this inverter
                (including debounced no-serial fallback slots).  A legacy key
                that is still an active key belongs to a live battery (mixed
                serial/no-serial pack) and is never migrated.
        """
        if inverter_serial in self._battery_migration_suppressed:
            return

        active = set(active_keys)
        pending: dict[str, str] = {}
        for old_key, new_key in pairs.items():
            if old_key == new_key:
                continue
            if (inverter_serial, old_key) in self._battery_key_migrations_done:
                continue
            if old_key in active:
                _LOGGER.debug(
                    "Skipping battery key migration %s -> %s for %s: "
                    "legacy key still active (mixed serial/no-serial pack)",
                    old_key,
                    new_key,
                    inverter_serial,
                )
                continue
            pending[old_key] = new_key

        if not pending:
            return

        # Same-inverter canonical-key collision safety: two legacy keys
        # resolving to one canonical target means two physical batteries
        # claim one identity — renaming would misbind history and the
        # duplicate-removal branch could delete a live battery's rows.
        # Drop the colliding pairs and warn.
        targets = list(pending.values())
        colliding = {t for t in targets if targets.count(t) > 1}
        if colliding:
            _LOGGER.warning(
                "Skipping battery key migration for inverter %s: multiple "
                "legacy keys resolve to the same canonical key(s) %s "
                "(duplicate battery identity in the payload?)",
                inverter_serial,
                sorted(colliding),
            )
            pending = {o: n for o, n in pending.items() if n not in colliding}
            if not pending:
                return

        # The done-guard is intentionally in-memory only: after a restart the
        # migration re-runs once per battery and finds nothing left to rename
        # (a proven no-op), so a persistent marker isn't warranted.  Retiring
        # the legacy shadow map entirely is deferred to 3.5.0.
        try:
            migrated = async_migrate_battery_keys(
                self.hass, self.entry.entry_id, inverter_serial, pending
            )
        except Exception:
            # Never let a registry problem take down the refresh; the pairs
            # are re-derived and retried (HYBRID/CLOUD: next refresh; LOCAL:
            # next restart/reload).
            _LOGGER.exception(
                "Battery identity migration failed for inverter %s; "
                "data refresh continues",
                inverter_serial,
            )
            return
        # Mark only the keys whose registry operations completed, so a
        # per-key failure or live-entity deferral is retried instead of
        # being lost for the session.
        for old_key in migrated:
            self._battery_key_migrations_done.add((inverter_serial, old_key))

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

    async def write_raw_parameter(
        self,
        address: int,
        value: int,
        serial: str | None = None,
    ) -> bool:
        """Write a single holding register by raw address via the local transport.

        For registers with no pylxpweb name-map entry AND no cloud parameter
        name — e.g. HOLD 117 (PtoUserStartchg, GH #272), which the cloud
        remoteRead names ``<EMPTY>`` on every scanned model. Named writes
        (:meth:`write_named_parameter`) remain the path for any register
        pylxpweb knows; raw writes bypass the name map entirely, so callers
        must pass the exact unsigned 16-bit register value (mask signed
        values with ``& 0xFFFF``).

        Args:
            address: Holding register address.
            value: Unsigned 16-bit register value to write.
            serial: Device serial for LOCAL mode with multiple devices.

        Returns:
            True if write succeeded.

        Raises:
            HomeAssistantError: If no local transport or write fails.
        """
        transport = self.get_local_transport(serial)
        if not transport:
            raise HomeAssistantError("No local transport available for parameter write")

        try:
            if not transport.is_connected:
                _LOGGER.debug(
                    "Reconnecting transport for %s before writing register %d",
                    serial,
                    address,
                )
                await transport.connect()

            await transport.write_parameters({address: value})
            _LOGGER.debug("Wrote raw register %d = %s", address, value)
            return True

        except Exception as err:
            _LOGGER.error("Failed to write register %d: %s", address, err)
            raise HomeAssistantError(
                f"Failed to write register {address}: {err}"
            ) from err

    async def write_register(
        self,
        register: int,
        value: int,
        serial: str | None = None,
    ) -> bool:
        """Write a raw holding register through the local transport.

        The raw-register sibling of :meth:`write_named_parameter`, for
        registers whose local name mapping is absent or wrong (e.g. the
        packed AC-charge schedule registers 68-73, issue #277 — their
        pylxpweb names misdescribe the packed hour|minute layout). A single
        register is written per call, which the transports send as a Modbus
        FC06 single-register write — schedule registers reject FC16
        multi-register writes.

        NOTE: functionally overlaps :meth:`write_raw_parameter` (GH #272);
        consolidating the two is a documented deferred cleanup — do not
        merge them piecemeal.

        Args:
            register: Holding register address.
            value: Raw 16-bit register value to write.
            serial: Device serial for LOCAL mode with multiple devices.

        Returns:
            True if write succeeded.

        Raises:
            HomeAssistantError: If no local transport or write fails.
        """
        transport = self.get_local_transport(serial)
        if not transport:
            raise HomeAssistantError("No local transport available for register write")

        try:
            if not transport.is_connected:
                _LOGGER.debug(
                    "Reconnecting transport for %s before writing register %d",
                    serial,
                    register,
                )
                await transport.connect()

            await transport.write_parameters({register: value})
            _LOGGER.debug("Wrote register %d = %s", register, value)
            return True

        except Exception as err:
            _LOGGER.error("Failed to write register %d: %s", register, err)
            raise HomeAssistantError(
                f"Failed to write register {register}: {err}"
            ) from err

    # ── Battery control regime (SOC vs Voltage, register 179 bits 9/10) ──────

    def get_configured_control_modes(self) -> tuple[str, str]:
        """Return the configured ``(charge_mode, discharge_mode)`` for entity gating.

        Reads the stored options, defaulting to SOC (closed-loop) so existing
        installs keep their historical behavior (only SOC limit controls
        enabled). Used to compute ``entity_registry_enabled_default``.
        """
        options = self.entry.options
        charge = options.get(CONF_CHARGE_CONTROL_MODE, DEFAULT_CONTROL_MODE)
        discharge = options.get(CONF_DISCHARGE_CONTROL_MODE, DEFAULT_CONTROL_MODE)
        return str(charge), str(discharge)

    def get_live_control_mode(self, serial: str, *, discharge: bool = False) -> str:
        """Return the live battery control regime for a device from polled params.

        Reads register 179 bit 9 (charge) or bit 10 (discharge) as surfaced in
        ``data["parameters"][serial]``. Returns ``CONTROL_MODE_VOLTAGE`` or
        ``CONTROL_MODE_SOC``; defaults to SOC when the parameter is not (yet)
        available. This reflects what the inverter is actually honoring, used
        for the "is this control effective?" indicator and config pre-fill.
        """
        params = (self.data or {}).get("parameters", {}).get(serial, {})
        key = (
            PARAM_FUNC_BAT_DISCHARGE_CONTROL
            if discharge
            else PARAM_FUNC_BAT_CHARGE_CONTROL
        )
        raw = params.get(key)
        if raw is None:
            return CONTROL_MODE_SOC
        return CONTROL_MODE_VOLTAGE if bool(raw) else CONTROL_MODE_SOC

    async def async_write_battery_control_mode(
        self, serial: str, charge_mode: str, discharge_mode: str
    ) -> None:
        """Write the battery charge/discharge control regime to the inverter.

        Sets register 179 bit 9 (charge) and bit 10 (discharge): SOC clears the
        bit, Voltage sets it. Routes through the local transport when available,
        else the cloud function-control API.

        Raises:
            HomeAssistantError: If no write path is available or a write fails.
        """
        charge_voltage = charge_mode == CONTROL_MODE_VOLTAGE
        discharge_voltage = discharge_mode == CONTROL_MODE_VOLTAGE

        if self.has_local_transport(serial):
            await self.write_named_parameter(
                PARAM_FUNC_BAT_CHARGE_CONTROL, charge_voltage, serial=serial
            )
            await self.write_named_parameter(
                PARAM_FUNC_BAT_DISCHARGE_CONTROL, discharge_voltage, serial=serial
            )
        elif self.client is not None:
            charge_result = await self.client.api.control.control_function(
                serial, PARAM_FUNC_BAT_CHARGE_CONTROL, charge_voltage
            )
            discharge_result = await self.client.api.control.control_function(
                serial, PARAM_FUNC_BAT_DISCHARGE_CONTROL, discharge_voltage
            )
            if not (charge_result.success and discharge_result.success):
                raise HomeAssistantError(
                    f"Failed to set battery control mode for {serial}"
                )
        else:
            raise HomeAssistantError(
                "No local transport or cloud API available to set battery control mode."
            )

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
