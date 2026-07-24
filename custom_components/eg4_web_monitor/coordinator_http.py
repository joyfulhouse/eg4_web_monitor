"""HTTP/cloud update mixin for EG4 Web Monitor coordinator.

This mixin handles all HTTP cloud API data fetching and processing,
including hybrid mode (local transport + cloud API fallback).

Methods rely on coordinator attributes (self.client, self.station,
self._http_polling_interval, etc.) accessed via mixin protocol.
"""

import asyncio
import logging
import time as _time
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from pylxpweb.devices.inverters.base import BaseInverter
else:
    from homeassistant.helpers.update_coordinator import UpdateFailed  # type: ignore[assignment]

from pylxpweb.devices import Station
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from .const import (
    CONF_INCLUDE_AC_COUPLE_PV,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DOMAIN,
)
from .coordinator_mappings import (
    _build_individual_battery_mapping,
    _get_transport_label,
    blank_lost_battery_measurements,
    compute_parallel_group_charge_rate,
)
from .coordinator_mixins import (
    BATTERY_CARRY_FORWARD_MAX_AGE,
    _MixinBase,
    apply_gridboss_to_parallel_group,
    compute_total_inverter_power_kw,
    is_transport_link_down,
)
from .utils import cloud_battery_key

_LOGGER = logging.getLogger(__name__)

# HYBRID battery overlay freshness window.
#
# pylxpweb's serial-keyed battery accumulator never evicts (#170 round-robin):
# a battery the firmware rotates — or stops surfacing — out of the local
# register page keeps its last-read block indefinitely. In HYBRID mode the
# cloud baseline is refreshed independently (cloud battery cache TTL ~5 min), so
# overlaying a *stale* transport block would hide fresher cloud data. Some
# firmware exposes only a subset of batteries per page for many hours (#258: an
# 18kPV surfaces one battery by day, all of them at night), which froze the
# cloud-backed batteries. Transport blocks not read within this window are
# therefore skipped in HYBRID so the fresh cloud value stands. The window
# matches the cloud battery cache TTL: once local data is older than the cloud
# refresh interval, the cloud copy is at least as current. LOCAL-only mode keeps
# the never-evict block (it has no cloud fallback).
HYBRID_TRANSPORT_FRESHNESS = timedelta(minutes=5)


def _maybe_bust_degraded_cloud_cache(
    client: Any,
    last_refresh: dict[str, float],
    http_interval: float,
    serial: str,
) -> bool:
    """Throttled per-serial cloud cache bust for DEGRADED devices.

    Degraded = locally configured but currently served by the cloud (attach
    failed, or attached transport link down).  Their cloud caches are
    aligned to the slow HTTP interval on the assumption local is primary,
    which froze their sensors for the whole cache window — bust them so
    degraded devices keep updating.  The bust is throttled per serial to
    the HTTP polling interval: a hybrid coordinator can tick at the fastest
    LOCAL interval (5s), which must never leak into the cloud call rate.

    Args:
        client: LuxpowerClient (or None — returns False).
        last_refresh: Per-serial monotonic stamps (mutated on a fired bust).
        http_interval: Cloud-safe HTTP polling interval in seconds.
        serial: Device serial number.

    Returns:
        True when the bust fired (cloud window elapsed), False inside the
        throttle window or without a client.
    """
    if client is None:
        return False
    now = _time.monotonic()
    last = last_refresh.get(serial, 0.0)
    if now - last < http_interval:
        return False
    last_refresh[serial] = now
    client.invalidate_cache_for_device(serial)
    return True


class HTTPUpdateMixin(_MixinBase):
    """Mixin providing HTTP/cloud data update methods for the coordinator."""

    def _align_client_cache_with_http_interval(self) -> None:
        """Set client cache TTLs to match HTTP polling interval.

        This ensures ALL HTTP API calls respect the configured HTTP polling
        rate. In hybrid mode, local transport bypasses these caches entirely.
        In HTTP-only mode the coordinator interval already controls the rate,
        but we still align caches as a safety net.
        """
        if self.client is None:
            return
        http_ttl = timedelta(seconds=self._http_polling_interval)
        for key in (
            "battery_info",
            "midbox_runtime",
            "quick_charge_status",
            "inverter_runtime",
            "inverter_energy",
            "parameter_read",
        ):
            self.client._cache_ttl_config[key] = http_ttl

    def _should_poll_hybrid_local(self) -> bool:
        """Check if the dongle transport interval has elapsed for MID refresh.

        In HYBRID mode, MID devices (GridBOSS) are refreshed via WiFi dongle.
        This method gates MID refresh specifically on the dongle interval,
        not on any transport.  Evaluates ALL transport types so monotonic
        timestamps are stamped for each (pre-compute pattern from cc8d4e2).
        """
        if not self._local_transport_configs:
            return True  # No local transports -> always refresh (HTTP-only fallback)
        unique_types = {
            c.get("transport_type", "modbus_tcp") for c in self._local_transport_configs
        }
        # Eagerly evaluate ALL types so every transport's monotonic timestamp
        # is stamped even when an earlier one is True.
        results = {tt: self._should_poll_transport(tt) for tt in unique_types}
        # MID device is on the dongle — gate its refresh by dongle interval.
        # If no dongle transport exists, fall back to any-transport-ready.
        if "wifi_dongle" in results:
            should_poll = results["wifi_dongle"]
            _LOGGER.debug(
                "HYBRID poll gate: transports=%s, dongle_ready=%s",
                results,
                should_poll,
            )
            return should_poll
        return any(results.values())

    async def _ensure_local_transports(self) -> None:
        """Recover local transports after setup-time failures (eg4-05l).

        Two failure shapes need post-setup recovery, both bounded to
        ATTACH_RETRY_INTERVAL_SECONDS:

        - a whole-attach EXCEPTION left ``_local_transports_attached`` False
          with an empty failed set — re-run the full attach;
        - per-serial failures (tracked in ``_failed_attach_serials``) —
          retry just those serials.
        """
        if self.connection_type != CONNECTION_TYPE_HYBRID:
            return
        if self._local_transport_configs and not self._local_transports_attached:
            from .coordinator_local import ATTACH_RETRY_INTERVAL_SECONDS

            now = _time.monotonic()
            if now - self._last_attach_retry < ATTACH_RETRY_INTERVAL_SECONDS:
                return
            self._last_attach_retry = now
            await self._attach_local_transports_to_station()
        elif self._failed_attach_serials:
            await self._maybe_retry_failed_attaches()

    async def _refresh_station_devices(self, include_mid: bool = True) -> None:
        """Refresh station devices, serializing by transport endpoint.

        WiFi dongles are simple embedded devices that cannot handle concurrent
        Modbus TCP connections reliably.  When multiple devices (inverters +
        GridBOSS) share the same dongle, concurrent ``asyncio.gather()`` calls
        overwhelm the dongle and produce corrupt register data (voltage spikes,
        energy value spikes).

        This method groups devices by their transport endpoint (host:port) and
        refreshes devices within the same group sequentially.  Groups on
        different endpoints — or devices without local transports — are still
        refreshed concurrently.

        Falls back to ``station.refresh_all_data()`` when no local transports
        are attached (pure HTTP mode), since concurrent HTTP API calls are safe.

        Args:
            include_mid: Whether to include MID/GridBOSS devices in the refresh.
        """
        if self.station is None:
            return

        # Fast path: no local transports → concurrent HTTP is safe
        if not self._local_transports_attached:
            if include_mid:
                await self.station.refresh_all_data()
            else:
                tasks = [inv.refresh() for inv in self.station.all_inverters]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            return

        # Group devices by transport endpoint for serialized access
        endpoint_groups: dict[str, list[Any]] = {}
        no_transport: list[Any] = []

        all_devices: list[Any] = list(self.station.all_inverters)
        if include_mid:
            all_devices.extend(self.station.all_mid_devices)

        for device in all_devices:
            transport = device.transport
            if transport is None:
                no_transport.append(device)
                continue
            # Group by the PUBLIC host/port (network transports — TCP dongle).
            host = getattr(transport, "host", None)
            port = getattr(transport, "port", None)
            if host is not None and port is not None:
                endpoint = f"{host}:{port}"
            elif isinstance(port, str) and port:
                # Serial transports carry the tty path in ``port`` and have no
                # host. Devices sharing one RS485 adapter MUST refresh
                # sequentially — serial buses are single-client and concurrent
                # frames interleave/corrupt (#233). Distinct ports still
                # parallelize via separate groups. (Avoids the bogus ":0"
                # collapse of the eg4-xi7 silent-default bug.)
                endpoint = f"serial:{port}"
            else:
                no_transport.append(device)
                continue
            endpoint_groups.setdefault(endpoint, []).append(device)

        async def _refresh_group_sequentially(devices: list[Any]) -> None:
            """Refresh devices on the same endpoint one at a time.

            A device whose attached transport link is DOWN (eg4-57g) still
            refreshes every cycle — the refresh probes the dead link (so
            recovery can happen) and falls back to the cloud inside
            pylxpweb.  Its per-device cloud caches are busted (throttled to
            the HTTP interval) so the fallback serves moving values instead
            of interval-aligned stale cache.
            """
            for device in devices:
                try:
                    if is_transport_link_down(device):
                        _maybe_bust_degraded_cloud_cache(
                            self.client,
                            self._last_degraded_cloud_refresh,
                            self._http_polling_interval,
                            str(getattr(device, "serial_number", "?")),
                        )
                    await device.refresh()
                except Exception as exc:
                    _LOGGER.debug(
                        "Device %s refresh failed: %s",
                        getattr(device, "serial_number", "?"),
                        exc,
                    )

        # Build concurrent coroutines:
        #  - Each endpoint group is one sequential coroutine
        #  - Cloud-only devices (no transport) refresh concurrently
        coros: list[Any] = []
        for endpoint, devices in endpoint_groups.items():
            _LOGGER.debug(
                "HYBRID: Serializing %d device(s) on endpoint %s",
                len(devices),
                endpoint,
            )
            coros.append(_refresh_group_sequentially(devices))

        # Cloud-only devices can refresh concurrently (HTTP API)
        locally_configured = {
            str(c.get("serial")) for c in self._local_transport_configs
        }

        async def _refresh_cloud_device(device: Any) -> None:
            """Cloud refresh with degraded-mode cache bust + visible failures.

            A device configured for local polling that has NO transport is
            running degraded (attach failed — eg4-05l/o5m). Its cloud caches
            are busted (throttled per serial to the HTTP polling interval —
            see _maybe_bust_degraded_cloud_cache) so degraded devices keep
            updating, and its refresh is skipped entirely inside the
            throttle window. Genuinely cloud-only devices keep their normal
            caches. Failures are logged instead of being silently swallowed
            by gather(return_exceptions=True).
            """
            serial = str(getattr(device, "serial_number", "?"))
            try:
                if serial in locally_configured and self.client is not None:
                    if not _maybe_bust_degraded_cloud_cache(
                        self.client,
                        self._last_degraded_cloud_refresh,
                        self._http_polling_interval,
                        serial,
                    ):
                        return  # cached data stands until the cloud-safe window
                await device.refresh()
            except Exception as exc:
                _LOGGER.warning(
                    "Cloud refresh failed for %s (no local transport): %s",
                    serial,
                    exc,
                )

        for device in no_transport:
            coros.append(_refresh_cloud_device(device))

        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def _async_update_hybrid_data(self) -> dict[str, Any]:
        """Fetch data using library transport routing (local + cloud).

        When local transports are attached via Station.attach_local_transports(),
        inverter.refresh() automatically routes runtime/energy through the local
        transport and battery data through the cloud API. Internal cache TTLs
        prevent redundant calls. This method simply delegates to the HTTP path
        and overrides the connection type label.

        Returns:
            Dictionary containing device data with transport-aware labels.
        """
        include_mid = self._should_poll_hybrid_local()
        if not include_mid and self.station is not None:
            # A degraded MID device refreshes via the CLOUD, not the dongle —
            # the dongle-interval gate must not slow its fallback to one
            # update per dongle window (eg4-o5m). Degraded covers BOTH a
            # failed attach (no transport) and an attached-but-dead link
            # (eg4-57g). Only escalate while a MID is actually degraded.
            for mid in self.station.all_mid_devices:
                if str(
                    mid.serial_number
                ) in self._failed_attach_serials or is_transport_link_down(mid):
                    include_mid = True
                    break
        data = await self._async_update_http_data(
            include_mid_refresh=include_mid,
        )
        data["connection_type"] = CONNECTION_TYPE_HYBRID

        # Set transport labels per device based on attached transports
        # In hybrid mode, devices are in the station object, not local caches
        for serial, device_data in data.get("devices", {}).items():
            if "sensors" not in device_data:
                continue
            if device_data.get("type") == "parallel_group":
                continue
            # Look up device from station (hybrid mode) or local caches (fallback)
            device: Any = None
            if self.station:
                # Check station inverters
                for inv in self.station.all_inverters:
                    if inv.serial_number == serial:
                        device = inv
                        break
                # Check station MID devices
                if device is None:
                    for mid in self.station.all_mid_devices:
                        if mid.serial_number == serial:
                            device = mid
                            break
            # Fallback to local caches
            if device is None:
                device = self._inverter_cache.get(serial) or self._mid_device_cache.get(
                    serial
                )
            transport = device.transport if device else None
            if transport is not None:
                transport_type = getattr(transport, "transport_type", "local")
                label = _get_transport_label(transport_type)
                if is_transport_link_down(device):
                    # Attached but dead (eg4-57g): values come from the cloud
                    # fallback — dashboards must show the truth.
                    device_data["sensors"]["connection_transport"] = (
                        f"Hybrid ({label} — link down)"
                    )
                else:
                    device_data["sensors"]["connection_transport"] = f"Hybrid ({label})"
                if hasattr(transport, "host"):
                    device_data["sensors"]["transport_host"] = transport.host
            else:
                device_data["sensors"]["connection_transport"] = "Cloud"

        # Raise/clear Repairs issues for link-down transitions (one-shot).
        self._sync_transport_link_state(None)

        return data

    async def _async_update_http_data(
        self,
        include_mid_refresh: bool = True,
    ) -> dict[str, Any]:
        """Fetch data from HTTP cloud API using device objects.

        This is the original HTTP-based update method using LuxpowerClient
        and Station/Inverter device objects.

        Args:
            include_mid_refresh: When True (default), refresh all devices
                including MID/GridBOSS via station.refresh_all_data().
                When False (HYBRID mode, dongle interval not elapsed),
                only refresh inverters — MID device retains data from
                the previous cycle.

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
                _LOGGER.debug(
                    "Hourly parameter refresh is due, refreshing all device parameters"
                )
                task = self.hass.async_create_task(self._hourly_parameter_refresh())
                self._background_tasks.add(task)
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            # Load or refresh station data using device objects
            if self.station is None:
                _LOGGER.info("Loading station data for plant %s", self.plant_id)
                assert self.plant_id is not None
                self.station = await Station.load(self.client, int(self.plant_id))
                _LOGGER.debug(
                    "Refreshing all data after station load to populate battery details"
                )
                await self.station.refresh_all_data()
                # Build inverter cache for O(1) lookups
                self._rebuild_inverter_cache()

                # Align client cache TTLs with HTTP polling interval
                self._align_client_cache_with_http_interval()

                # For hybrid mode: Attach local transports to devices (new API)
                # This enables devices to use local transport with HTTP fallback
                if (
                    self.connection_type == CONNECTION_TYPE_HYBRID
                    and self._local_transport_configs
                    and not self._local_transports_attached
                ):
                    await self._attach_local_transports_to_station()
            else:
                # Recover from setup-time attach failures (eg4-05l) — both
                # per-serial failures and a whole-attach exception.
                await self._ensure_local_transports()
                if include_mid_refresh:
                    _LOGGER.debug(
                        "Refreshing all station data for plant %s", self.plant_id
                    )
                    await self._refresh_station_devices(include_mid=True)
                else:
                    _LOGGER.debug(
                        "Refreshing inverters only for plant %s "
                        "(MID dongle interval not elapsed)",
                        self.plant_id,
                    )
                    await self._refresh_station_devices(include_mid=False)

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

            # Set transport label for all devices (skip virtual devices)
            for device_data in processed_data.get("devices", {}).values():
                if (
                    "sensors" in device_data
                    and device_data.get("type") != "parallel_group"
                ):
                    device_data["sensors"]["connection_transport"] = "Cloud"

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

    def _apply_battery_carry_forward(
        self,
        inverter_serial: str,
        device_data: dict[str, Any],
        exclude: Collection[str] = (),
    ) -> None:
        """Keep once-published batteries published across transient gaps (#258).

        Battery entity availability is literally key-presence in
        ``device_data["batteries"]``, and the HYBRID/CLOUD paths rebuild that
        dict from the cloud payload as the *baseline* every cycle.  On rotating
        >4-battery packs the cloud is fed through the same firmware page
        rotation as the local reads, so a fresh ``getBatteryInfo`` can
        momentarily omit a subset of batteries — beta.18 field logs show
        subsets of battery entities flipping unavailable seconds after a cloud
        refresh while pylxpweb's local accumulator still held every battery.

        A battery that has ever been published for this inverter is carried
        forward with its last-known mapping instead of being dropped.  The
        carried mapping keeps its original ``battery_last_seen`` /
        ``battery_last_polled`` stamps, so staleness stays visible as data —
        never as availability flapping (the #261/#282 sticky precedent).

        Two guards keep identities from doubling, and one bound keeps carried
        keys from becoming immortal:

        - ``exclude``: legacy positional keys that are aliases of a battery
          published under its canonical key this cycle (#252 migration pairs).
          Carrying one would re-mint the positional entity and permanently
          block the registry migration ("legacy key still active").
        - serial supersede: a cached key whose ``battery_serial_number`` is
          already published under a different key was re-keyed by the payload;
          carrying the old key would publish the same physical pack twice.
          The published-serial set grows as carried mappings are admitted, so
          two cached keys sharing one serial can never both be carried.
        - eviction bound: a cached key whose ``battery_last_seen`` aged past
          ``BATTERY_CARRY_FORWARD_MAX_AGE`` is a physically removed (or
          permanently vanished) pack, not a transient gap — it is evicted
          (one INFO) so removal converges without a Home Assistant restart.

        Args:
            inverter_serial: Parent inverter serial number.
            device_data: The inverter's device data dict (mutated in place).
            exclude: Keys never to carry forward (legacy migration aliases).
        """
        current: dict[str, dict[str, Any]] = device_data.get("batteries") or {}
        cache = self._battery_carry_forward.get(inverter_serial)

        if cache:
            now = dt_util.utcnow()
            current_serials = {
                sn
                for mapping in current.values()
                if isinstance(sn := mapping.get("battery_serial_number"), str) and sn
            }
            carried: list[str] = []
            evicted: list[str] = []
            for key, mapping in list(cache.items()):
                if key in current:
                    continue
                last_seen = mapping.get("battery_last_seen")
                if (
                    isinstance(last_seen, datetime)
                    and now - dt_util.as_utc(last_seen) > BATTERY_CARRY_FORWARD_MAX_AGE
                ):
                    del cache[key]
                    evicted.append(key)
                    continue
                if key in exclude:
                    continue
                sn = mapping.get("battery_serial_number")
                if isinstance(sn, str) and sn in current_serials:
                    continue
                current[key] = mapping
                carried.append(key)
                if isinstance(sn, str) and sn:
                    current_serials.add(sn)
            if evicted:
                _LOGGER.info(
                    "Evicting %d batteries for %s not seen for over %s "
                    "(physically removed or permanently vanished): %s",
                    len(evicted),
                    inverter_serial,
                    BATTERY_CARRY_FORWARD_MAX_AGE,
                    evicted,
                )
            if carried:
                _LOGGER.debug(
                    "Carrying forward %d batteries missing from this cycle for %s: %s",
                    len(carried),
                    inverter_serial,
                    carried,
                )

        if not current:
            return
        device_data["batteries"] = current
        self._battery_carry_forward[inverter_serial] = dict(current)

    def _resolve_cloud_battery_key(
        self, serial: str, battery: Any, seen_keys: dict[str, int]
    ) -> tuple[str, str, tuple[str, str] | None]:
        """Return (resolved_key, identity_key, migration_pair | None).

        ``identity_key`` is the pre-disambiguation cloud ``batteryKey`` — the
        caller needs it to format the collision warning (``{identity_key!r}``)
        and to look up ``seen_keys[identity_key]`` (the index of the battery
        that first claimed the identity). On collision ``resolved_key`` is the
        positional key (``f"{serial}-{c_idx+1:02d}"``) and ``migration_pair``
        is ``None``; otherwise ``resolved_key == identity_key`` and
        ``migration_pair`` is ``(legacy_positional_key, canonical_key)`` to
        record. Side-effect free: does NOT mutate ``seen_keys``, register
        migrations, or suppress.
        """
        identity_key = cloud_battery_key(serial, battery)
        c_idx = getattr(battery, "battery_index", None)
        if c_idx is None:
            return identity_key, identity_key, None
        if identity_key in seen_keys:
            return f"{serial}-{c_idx + 1:02d}", identity_key, None
        return (
            identity_key,
            identity_key,
            (f"{serial}-{c_idx + 1:02d}", identity_key),
        )

    async def _process_station_data(self) -> dict[str, Any]:
        """Process station data using device objects."""
        if not self.station:
            raise UpdateFailed("Station not loaded")

        processed: dict[str, Any] = {
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
            "plant_id": str(self.station.id),
            "station_last_polled": dt_util.utcnow(),
        }

        # DST flag consumed by the Daylight Saving Time switch. Refreshes at
        # station load, on HA-side writes (set_daylight_saving_time), and is
        # re-read from the cloud during each hourly DST sync — with DST sync
        # disabled, portal-side toggles are only picked up on entry reload.
        processed["station"]["daylightSavingTime"] = bool(
            getattr(self.station, "daylight_saving_time", False)
        )

        if timezone := getattr(self.station, "timezone", None):
            processed["station"]["timezone"] = timezone

        if location := getattr(self.station, "location", None):
            if country := getattr(location, "country", None):
                processed["station"]["country"] = country
            if address := getattr(location, "address", None):
                processed["station"]["address"] = address

        if created_date := getattr(self.station, "created_date", None):
            processed["station"]["createDate"] = created_date.isoformat()

        # API metrics from client — only tracked when an HTTP client exists
        if self.client is not None:
            processed["station"]["api_request_rate"] = (
                self.client.api_requests_last_hour
            )
            processed["station"]["api_peak_request_rate"] = (
                self.client.api_peak_rate_per_hour
            )

            # Daily counter: offset (pre-reload total) + client's count since reload.
            # Persisted in hass.data to survive config entry reloads.
            today_ymd = _time.localtime()[:3]
            if today_ymd != self._daily_api_ymd:
                self._daily_api_offset = 0
                self._daily_api_ymd = today_ymd
            total_today = self._daily_api_offset + self.client.api_requests_today
            processed["station"]["api_requests_today"] = total_today
            self.hass.data[f"{DOMAIN}_daily_api_count_{self.plant_id}"] = {
                "count": total_today,
                "ymd": today_ymd,
            }

        # Process all inverters concurrently with semaphore to prevent rate limiting
        async def process_inverter_with_semaphore(
            inv: "BaseInverter",
        ) -> tuple[str, dict[str, Any]]:
            """Process a single inverter with semaphore protection."""
            async with self._api_semaphore:
                try:
                    result = await self._process_inverter_object(inv)
                    return (inv.serial_number, result)
                except Exception as e:
                    _LOGGER.exception(
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

        # Propagate total inverter power rating to MID devices (one-time).
        # Features are detected inside _process_inverter_object(), so the
        # ratings become available only after the first inverter processing.
        if self.station.all_mid_devices and not getattr(
            self, "_mid_power_rating_set", False
        ):
            total_kw = compute_total_inverter_power_kw(self.station.all_inverters)
            if total_kw > 0:
                for mid in self.station.all_mid_devices:
                    mid.set_max_system_power(total_kw)
                self._mid_power_rating_set = True
                _LOGGER.info(
                    "Set max system power %.1f kW on %d MID device(s)",
                    total_kw,
                    len(self.station.all_mid_devices),
                )

        # Process parallel group data if available
        if hasattr(self.station, "parallel_groups") and self.station.parallel_groups:
            groups = self.station.parallel_groups
            _LOGGER.debug("Processing %d parallel groups", len(groups))

            # Refresh PG energy data.
            # When inverters have local transport, energy is computed from
            # inverter data (no cloud call). Otherwise, throttle cloud API
            # to 60s intervals since energy data changes slowly.
            has_local = any(
                group._has_local_energy() for group in groups if group.inverters
            )

            if has_local:
                # Local computation — cheap, run every cycle
                energy_tasks = []
                for group in groups:
                    if group.inverters:
                        energy_tasks.append(
                            group._fetch_energy_data(group.inverters[0].serial_number)
                        )
                if energy_tasks:
                    await asyncio.gather(*energy_tasks, return_exceptions=True)
            else:
                # Cloud API — throttle to 60s intervals
                _PG_ENERGY_INTERVAL = 60  # seconds
                now_mono = _time.monotonic()
                last_pg = getattr(self, "_last_pg_energy_fetch", 0.0)
                if now_mono - last_pg >= _PG_ENERGY_INTERVAL:
                    energy_tasks = []
                    for group in groups:
                        if group.inverters:
                            energy_tasks.append(
                                group._fetch_energy_data(
                                    group.inverters[0].serial_number
                                )
                            )
                    if energy_tasks:
                        await asyncio.gather(*energy_tasks, return_exceptions=True)
                    self._last_pg_energy_fetch = now_mono

            for group in groups:
                try:
                    _LOGGER.debug(
                        "Parallel group %s: energy=%s, today_yielding=%.2f kWh",
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
                    processed["devices"][f"parallel_group_{group.name.lower()}"] = (
                        group_data
                    )

                    # Aggregate member inverter battery data for parallel group.
                    # Single pass collects both battery count (override when
                    # cloud returns 0) and battery current sum.  Skipped when a
                    # member is cloud-lost (#479): the loop would silently sum
                    # only the live members' (blanked-to-None-excluded) values
                    # and resurrect a plausible-looking partial total over the
                    # group blanking.
                    pg_sensors = group_data.get("sensors", {})
                    has_lost_member = bool(group_data.get("has_lost_member"))
                    need_bat_count = (
                        not has_lost_member
                        and pg_sensors.get("parallel_battery_count", 0) == 0
                    )
                    total_bats = 0
                    total_current = 0.0
                    has_current = False
                    for inv in getattr(group, "inverters", []):
                        inv_serial = getattr(inv, "serial_number", None)
                        if not inv_serial:
                            continue
                        inv_sensors = (
                            processed["devices"].get(inv_serial, {}).get("sensors", {})
                        )
                        if need_bat_count:
                            bat_count = inv_sensors.get("battery_bank_count")
                            if bat_count is not None and bat_count > 0:
                                total_bats += bat_count
                        current = inv_sensors.get("battery_bank_current")
                        if current is not None:
                            total_current += float(current)
                            has_current = True
                    if need_bat_count and total_bats > 0:
                        pg_sensors["parallel_battery_count"] = total_bats
                    if has_current and not has_lost_member:
                        pg_sensors["parallel_battery_current"] = total_current

                    # Compute parallel group charge/discharge C-rates (%/h)
                    compute_parallel_group_charge_rate(pg_sensors)

                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            mid_data = await self._process_mid_device_object(
                                group.mid_device
                            )
                            processed["devices"][group.mid_device.serial_number] = (
                                mid_data
                            )

                            # Apply the canonical GridBOSS workflow to the
                            # parallel group (overlay + AC-couple PV).  GridBOSS
                            # CTs are the authoritative source for grid and
                            # consumption measurements — inverter register sums
                            # are internal estimates that diverge from actual
                            # panel readings.  Shared with the LOCAL path; the
                            # HTTP path keeps the cloud consumption value
                            # (recompute_consumption=False).
                            include_ac_couple = self.entry.options.get(
                                CONF_INCLUDE_AC_COUPLE_PV,
                                self.entry.data.get(CONF_INCLUDE_AC_COUPLE_PV, False),
                            )
                            apply_gridboss_to_parallel_group(
                                group_data.get("sensors", {}),
                                mid_data.get("sensors", {}),
                                group.name,
                                include_ac_couple=include_ac_couple,
                                recompute_consumption=False,
                            )

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
                self._apply_battery_carry_forward(serial, device_data)
                continue

            # Get cloud battery metadata (already cached, no API call)
            battery_bank = getattr(inverter, "_battery_bank", None)
            cloud_batteries = (
                getattr(battery_bank, "batteries", None) if battery_bank else None
            )

            # Get transport battery data (local Modbus real-time values)
            transport_battery = inverter.transport_battery
            transport_batteries = (
                transport_battery.batteries
                if transport_battery and hasattr(transport_battery, "batteries")
                else None
            )

            # HYBRID MODE: Merge cloud metadata with transport real-time data
            # Cloud provides: model, serial_number, bms_model, battery_type_text
            # Transport provides: fresh voltage, current, SOC, cell voltages, temps
            #
            # Transport battery slots use round-robin: firmware rotates which
            # physical batteries appear in the fixed register slots each poll.
            # Match transport → cloud by serial number (not slot index).
            #
            # Batteries are keyed by the canonical cloud batteryKey derivation
            # — identical to the CLOUD-only path — so a cloud→hybrid migration
            # never re-keys a battery (#252).
            #
            # Defense-in-depth (#258): also run the merge when the transport
            # battery list is momentarily EMPTY (a dropped 5002+ block read on
            # pylxpweb <= 0.9.36b18 published a bank with batteries=[]) or
            # None (link down clears the transport cache), instead of falling
            # through to the CLOUD-ONLY branch for that cycle.  Since #252,
            # both branches derive the same canonical keys, so the fallthrough
            # no longer re-keys entities — but staying in the hybrid merge
            # keeps the sensor mapping and freshness-overlay semantics
            # identical across outage cycles (the cloud-only branch extracts a
            # different sensor set and re-stamps battery_last_seen).
            has_transport = bool(getattr(inverter, "has_transport", False))
            if cloud_batteries and (has_transport or transport_batteries is not None):
                if "batteries" not in device_data:
                    device_data["batteries"] = {}

                # Build lookup of cloud batteries by serial for merging
                cloud_by_serial: dict[str, Any] = {}
                for cloud_batt in cloud_batteries:
                    c_sn = getattr(cloud_batt, "battery_sn", "") or ""
                    if c_sn:
                        cloud_by_serial[c_sn] = cloud_batt

                # First, populate all cloud batteries as baseline
                key_migrations: dict[str, str] = {}
                baseline_keys: dict[str, int] = {}
                for cloud_batt in cloud_batteries:
                    c_idx = getattr(cloud_batt, "battery_index", None)
                    if c_idx is None:
                        continue
                    battery_key, identity_key, migration_pair = (
                        self._resolve_cloud_battery_key(
                            serial, cloud_batt, baseline_keys
                        )
                    )
                    if migration_pair is None:
                        # Duplicate battery identity in one payload: keep
                        # positional disambiguation for the colliding battery
                        # and stop trusting registry migration for this
                        # inverter (last-write-wins would hide a battery and
                        # the migration could misbind history).
                        self._suppress_battery_migration(
                            serial,
                            f"cloud batteries {baseline_keys[identity_key]} "
                            f"and {c_idx} both resolve to identity "
                            f"{identity_key!r}",
                            level=logging.WARNING,
                        )
                    else:
                        baseline_keys[identity_key] = c_idx
                        legacy_key, canonical_key = migration_pair
                        key_migrations[legacy_key] = canonical_key
                    device_data["batteries"][battery_key] = (
                        _build_individual_battery_mapping(cloud_batt)
                    )

                # Overlay transport real-time data matched by serial
                transport_matched = 0
                for batt in transport_batteries or []:
                    # Skip ghost batteries (no real data) — matches pylxpweb's
                    # canonical ghost definition (BatteryData voltage/soc are
                    # non-optional, defaulting to 0, so an empty 5002+ slot reads
                    # 0/0 rather than None).
                    if batt.voltage == 0 and batt.soc == 0:
                        continue
                    bat_serial: str = getattr(batt, "serial_number", "") or ""
                    if not bat_serial or bat_serial not in cloud_by_serial:
                        continue
                    # Skip a frozen transport block so the fresh cloud baseline
                    # stands (#258). pylxpweb's accumulator never evicts, so a
                    # battery the firmware stopped surfacing locally keeps its
                    # last-read block indefinitely; overlaying that stale block
                    # would hide the independently-refreshed cloud value. Only
                    # overlay when the block was read within the freshness window.
                    last_seen = getattr(batt, "last_seen", None)
                    if (
                        last_seen is not None
                        and dt_util.utcnow() - dt_util.as_utc(last_seen)
                        > HYBRID_TRANSPORT_FRESHNESS
                    ):
                        _LOGGER.debug(
                            "HYBRID: battery %s transport block stale "
                            "(last seen %s) — keeping fresh cloud value",
                            bat_serial,
                            last_seen,
                        )
                        continue
                    cloud_batt = cloud_by_serial[bat_serial]
                    battery_key = cloud_battery_key(serial, cloud_batt)
                    # Transport data overwrites cloud for real-time values
                    battery_sensors = _build_individual_battery_mapping(batt)
                    # Preserve cloud-only metadata
                    if hasattr(cloud_batt, "battery_sn") and cloud_batt.battery_sn:
                        battery_sensors["battery_serial_number"] = cloud_batt.battery_sn
                    if hasattr(cloud_batt, "model") and cloud_batt.model:
                        battery_sensors["battery_model"] = cloud_batt.model
                    if hasattr(cloud_batt, "bms_model") and cloud_batt.bms_model:
                        battery_sensors["battery_bms_model"] = cloud_batt.bms_model
                    if (
                        hasattr(cloud_batt, "battery_type_text")
                        and cloud_batt.battery_type_text
                    ):
                        battery_sensors["battery_type_text"] = (
                            cloud_batt.battery_type_text
                        )
                    device_data["batteries"][battery_key] = battery_sensors
                    transport_matched += 1

                # Rename any pre-#252 positional registry entries to the
                # canonical keys (one-shot; no-op when nothing matches).
                # Runs BEFORE the carry-forward so carried legacy keys can
                # never count as "still active" and block the migration.
                self._register_battery_key_migrations(
                    serial, key_migrations, device_data["batteries"].keys()
                )

                # Batteries the fresh cloud payload momentarily omitted keep
                # their last-known data instead of flipping unavailable
                # (#258 beta.18).  The legacy aliases of batteries published
                # this cycle are never carried.
                self._apply_battery_carry_forward(
                    serial, device_data, exclude=key_migrations.keys()
                )

                _LOGGER.debug(
                    "HYBRID: %d batteries for %s (%d with live transport data)",
                    len(device_data.get("batteries", {})),
                    serial,
                    transport_matched,
                )
                continue

            # LOCAL-ONLY: Use transport battery data without cloud metadata.
            # Round-robin merge: accumulate by battery serial across polls.
            if transport_batteries:
                device_data["batteries"] = self._merge_round_robin_batteries(
                    serial,
                    list(transport_batteries),
                    getattr(transport_battery, "battery_count", None),
                )
                # The round-robin cache never evicts, but a session that
                # earlier published cloud-keyed batteries (hybrid → local
                # fallback flip) must not drop them (#258).  Legacy positional
                # aliases of serials the rr merge knows are excluded — a
                # no-serial pack whose serial just arrived had its positional
                # key retired by the merge, and the cached positional mapping
                # carries no serial for the supersede guard to match.
                self._apply_battery_carry_forward(
                    serial,
                    device_data,
                    exclude=set(self._battery_serial_to_key.get(serial, {}).values()),
                )
                _LOGGER.debug(
                    "LOCAL: %d individual batteries for %s (round-robin cache)",
                    len(device_data.get("batteries", {})),
                    serial,
                )
                continue

            # CLOUD-ONLY: Fall back to cloud battery_bank
            if not battery_bank:
                _LOGGER.debug(
                    "No battery_bank for inverter %s (battery_bank=%s)",
                    serial,
                    battery_bank,
                )
                self._apply_battery_carry_forward(serial, device_data)
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
                self._apply_battery_carry_forward(serial, device_data)
                continue

            _LOGGER.debug("Found %d batteries for inverter %s", len(batteries), serial)

            cloud_key_migrations: dict[str, str] = {}
            cloud_seen_keys: dict[str, int] = {}
            for battery in batteries:
                try:
                    c_idx = getattr(battery, "battery_index", None)
                    battery_key, identity_key, migration_pair = (
                        self._resolve_cloud_battery_key(
                            serial, battery, cloud_seen_keys
                        )
                    )
                    if c_idx is not None:
                        if migration_pair is None:
                            # Duplicate battery identity in one payload — keep
                            # positional disambiguation and stop trusting
                            # registry migration for this inverter (#252).
                            self._suppress_battery_migration(
                                serial,
                                f"cloud batteries {cloud_seen_keys[identity_key]} "
                                f"and {c_idx} both resolve to identity "
                                f"{identity_key!r}",
                                level=logging.WARNING,
                            )
                        else:
                            cloud_seen_keys[identity_key] = c_idx
                            # Legacy positional key a pre-#252 HYBRID/LOCAL
                            # install would have used for this battery.
                            legacy_key, canonical_key = migration_pair
                            cloud_key_migrations[legacy_key] = canonical_key
                    battery_sensors = self._extract_battery_from_object(battery)
                    battery_sensors["battery_last_polled"] = dt_util.utcnow()
                    battery_sensors["battery_last_seen"] = dt_util.utcnow()

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

            if cloud_key_migrations:
                self._register_battery_key_migrations(
                    serial,
                    cloud_key_migrations,
                    device_data.get("batteries", {}).keys(),
                )

            # Batteries the fresh cloud payload momentarily omitted keep their
            # last-known data instead of flipping unavailable (#258 beta.18).
            self._apply_battery_carry_forward(
                serial, device_data, exclude=cloud_key_migrations.keys()
            )

        # Blank the battery measurements of every cloud-lost inverter (#479).
        # Runs AFTER the loop above because each of its branches (cloud
        # extraction, #258 carry-forward, hybrid merge) republishes the
        # frozen portal mirror; a second pass catches them all at one choke
        # point.  Same gate as the inverter-sensor blanking: a genuinely
        # lost-flagged cloud payload only — live local transport data reads
        # is_lost=False and keeps HYBRID batteries fresh.
        #
        # The in-place mutation deliberately ALIASES into the #258
        # carry-forward store: _apply_battery_carry_forward snapshots
        # dict(current) — a shallow copy sharing these per-battery dicts —
        # so blanking here also blanks the cached copy, and a later
        # carry-forward cycle cannot resurrect the frozen values.  Pinned by
        # test_blanking_propagates_into_carry_forward_cache; if either side
        # ever deep-copies, that test fails.
        for serial, device_data in processed["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            inverter = self.get_inverter_object(serial)
            if (
                inverter is not None
                and getattr(inverter, "is_lost", False)
                and getattr(inverter, "has_runtime_data", False)
            ):
                for battery_sensors in device_data.get("batteries", {}).values():
                    blank_lost_battery_measurements(battery_sensors)

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
