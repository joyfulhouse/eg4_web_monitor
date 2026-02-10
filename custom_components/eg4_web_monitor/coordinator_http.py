"""HTTP/cloud update mixin for EG4 Web Monitor coordinator.

This mixin handles all HTTP cloud API data fetching and processing,
including hybrid mode (local transport + cloud API fallback).

Methods rely on coordinator attributes (self.client, self.station,
self._http_polling_interval, etc.) accessed via mixin protocol.
"""

import asyncio
import logging
import time as _time
from datetime import timedelta
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
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DOMAIN,
)
from .coordinator_mappings import (
    _build_individual_battery_mapping,
    _get_transport_label,
)
from .coordinator_mixins import _MixinBase, apply_gridboss_overlay
from .utils import clean_battery_display_name

_LOGGER = logging.getLogger(__name__)


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
        data = await self._async_update_http_data()
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
            transport = getattr(device, "_transport", None) if device else None
            if transport is not None:
                transport_type = getattr(transport, "transport_type", "local")
                label = _get_transport_label(transport_type)
                device_data["sensors"]["connection_transport"] = f"Hybrid ({label})"
                if hasattr(transport, "host"):
                    device_data["sensors"]["transport_host"] = transport.host
            else:
                device_data["sensors"]["connection_transport"] = "Cloud"

        return data

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
            "plant_id": self.station.id,
            "station_last_polled": dt_util.utcnow(),
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

                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            mid_data = await self._process_mid_device_object(
                                group.mid_device
                            )
                            processed["devices"][group.mid_device.serial_number] = (
                                mid_data
                            )

                            # Apply GridBOSS CT overlay to parallel group.
                            # GridBOSS CTs are the authoritative source for
                            # grid and consumption measurements — inverter
                            # register sums are internal estimates that diverge
                            # from actual panel readings.  This mirrors the
                            # overlay in _process_local_parallel_groups().
                            apply_gridboss_overlay(
                                group_data.get("sensors", {}),
                                mid_data.get("sensors", {}),
                                group.name,
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
                continue

            # Get cloud battery metadata (already cached, no API call)
            battery_bank = getattr(inverter, "_battery_bank", None)
            cloud_batteries = (
                getattr(battery_bank, "batteries", None) if battery_bank else None
            )

            # Get transport battery data (local Modbus real-time values)
            transport_battery = getattr(inverter, "_transport_battery", None)
            transport_batteries = (
                transport_battery.batteries
                if transport_battery and hasattr(transport_battery, "batteries")
                else None
            )

            # HYBRID MODE: Merge cloud metadata with transport real-time data
            # Cloud provides: model, serial_number, bms_model, battery_type_text
            # Transport provides: fresh voltage, current, SOC, cell voltages, temps
            if transport_batteries and cloud_batteries:
                if "batteries" not in device_data:
                    device_data["batteries"] = {}

                # Build lookup of cloud batteries by index for merging
                cloud_by_index: dict[int, Any] = {}
                for cloud_batt in cloud_batteries:
                    idx = getattr(cloud_batt, "battery_index", None)
                    if idx is not None:
                        cloud_by_index[idx] = cloud_batt

                for batt in transport_batteries:
                    battery_key = f"{serial}-{batt.battery_index + 1:02d}"
                    # Start with transport data (real-time values)
                    battery_sensors = _build_individual_battery_mapping(batt)

                    # Merge cloud-only metadata if available (no API call - already cached)
                    cloud_batt = cloud_by_index.get(batt.battery_index)
                    if cloud_batt:
                        # Cloud-only fields that transport doesn't have
                        if hasattr(cloud_batt, "battery_sn") and cloud_batt.battery_sn:
                            battery_sensors["battery_serial_number"] = (
                                cloud_batt.battery_sn
                            )
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

                _LOGGER.debug(
                    "HYBRID: Merged %d batteries (transport + cloud metadata) for %s",
                    len(transport_batteries),
                    serial,
                )
                continue

            # LOCAL-ONLY: Use transport battery data without cloud metadata
            if transport_batteries:
                if "batteries" not in device_data:
                    device_data["batteries"] = {}
                for batt in transport_batteries:
                    battery_key = f"{serial}-{batt.battery_index + 1:02d}"
                    device_data["batteries"][battery_key] = (
                        _build_individual_battery_mapping(batt)
                    )
                _LOGGER.debug(
                    "LOCAL: Added %d individual batteries for %s",
                    len(transport_batteries),
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
                    battery_sensors["battery_last_polled"] = dt_util.utcnow()

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
