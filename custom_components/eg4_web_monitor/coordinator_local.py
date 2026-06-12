"""Local transport coordinator mixin for EG4 Web Monitor integration.

This mixin handles all local transport logic (Modbus TCP, WiFi Dongle,
Modbus Serial) including device discovery, data reading, parallel group
aggregation, and static entity creation.
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import LuxpowerDeviceError
from pylxpweb.transports import (
    DongleTransport,
    ModbusSerialTransport,
    ModbusTransport,
)

from .const import (
    CONF_GRID_TYPE,
    CONF_INCLUDE_AC_COUPLE_PV,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DOMAIN,
    GRID_TYPE_SPLIT_PHASE,
    INVERTER_FAMILY_DEFAULT_MODELS,
    MANUFACTURER,
)
from .coordinator_mixins import (
    _MixinBase,
    apply_gridboss_to_parallel_group,
    compute_total_inverter_power_kw,
    drop_dead_inverter_grid_legs,
    is_transport_link_down,
)
from .coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    GRIDBOSS_STATIC_ENTITY_KEYS,
    PARALLEL_GROUP_GRIDBOSS_KEYS,
    PARALLEL_GROUP_SENSOR_KEYS,
    _build_battery_bank_sensor_mapping,
    _build_energy_sensor_mapping,
    _build_gridboss_sensor_mapping,
    _build_individual_battery_mapping,
    _build_runtime_sensor_mapping,
    _apply_grid_type_override,
    _build_transport_configs,
    _features_from_family,
    _get_transport_label,
    _parse_inverter_family,
    alias_common_voltage_sensors,
    compute_bank_charge_rate,
    compute_parallel_group_charge_rate,
)

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pylxpweb.transports.data import BatteryData

# Local network transports that carry the split-phase per-leg-fallback flag.
# inverter.transport is typed as the generic InverterTransport protocol (which
# HTTP transports also satisfy and which has no split_phase); narrowing to these
# concrete local types lets the typed seam verify the split_phase write.
_LOCAL_REGISTER_TRANSPORTS = (ModbusTransport, ModbusSerialTransport, DongleTransport)

# Minimum battery serial length to consider valid.  Shorter serials are
# likely truncated register reads from incomplete CAN bus transfers and
# are skipped to avoid creating phantom battery entities.
_MIN_SERIAL_LENGTH = 10

# Minimum seconds between retries of failed local-transport attaches
# (eg4-05l).  Long enough that a wedged dongle isn't hammered (each attempt
# costs up to 3 connect timeouts), short enough that the post-restart
# stale-TCP-slot window — typically 1-5 minutes — recovers promptly.
ATTACH_RETRY_INTERVAL_SECONDS = 60.0


class LocalTransportMixin(_MixinBase):
    """Mixin handling local transport operations for the coordinator."""

    def _merge_round_robin_batteries(
        self,
        inverter_serial: str,
        transport_batteries: list["BatteryData"],
    ) -> dict[str, dict[str, Any]]:
        """Merge transport battery slot data into the round-robin cache.

        Some inverter firmware rotates which physical batteries appear in the
        fixed Modbus register slots (5002+) on each CAN bus poll.  This method
        accumulates readings keyed by battery serial so that all batteries
        eventually appear as HA entities.

        Args:
            inverter_serial: Parent inverter serial number.
            transport_batteries: List of BatteryData from current poll.

        Returns:
            Full battery dict for device_data["batteries"], containing all
            batteries seen so far (not just this poll cycle).
        """
        if inverter_serial not in self._battery_rr_cache:
            self._battery_rr_cache[inverter_serial] = {}
            self._battery_serial_to_key[inverter_serial] = {}
            self._battery_next_index[inverter_serial] = 1

        cache = self._battery_rr_cache[inverter_serial]
        key_map = self._battery_serial_to_key[inverter_serial]

        poll_serials: list[str] = []
        poll_slots_skipped = 0
        new_serials: list[str] = []

        for batt in transport_batteries:
            # Skip ghost batteries with no CAN bus data — BatteryData voltage/soc
            # are non-optional (default 0), so an empty slot reads 0/0 not None.
            if batt.voltage == 0 and batt.soc == 0:
                poll_slots_skipped += 1
                _LOGGER.debug(
                    "RR [%s] slot %d: skipped (no CAN data, voltage=%s soc=%s)",
                    inverter_serial,
                    getattr(batt, "battery_index", -1),
                    batt.voltage,
                    batt.soc,
                )
                continue

            bat_serial: str = getattr(batt, "serial_number", "") or ""
            if not bat_serial:
                # No serial → fall back to slot-index keying (pre-round-robin
                # firmware or battery without CAN serial).
                fallback_key = f"{inverter_serial}-{batt.battery_index + 1:02d}"
                cache[fallback_key] = _build_individual_battery_mapping(batt)
                _LOGGER.debug(
                    "RR [%s] slot %d: no serial, fallback key %s (V=%.1f SoC=%s)",
                    inverter_serial,
                    getattr(batt, "battery_index", -1),
                    fallback_key,
                    batt.voltage or 0.0,
                    batt.soc,
                )
                continue

            # Skip truncated serials from incomplete register reads.
            # e.g. "Batter" or "y_ID_03" instead of "Battery_ID_03".
            # The real battery will appear with its full serial on a
            # future rotation cycle.
            if len(bat_serial) < _MIN_SERIAL_LENGTH:
                poll_slots_skipped += 1
                _LOGGER.debug(
                    "RR [%s] slot %d: skipping truncated serial %r (len=%d < %d)",
                    inverter_serial,
                    getattr(batt, "battery_index", -1),
                    bat_serial,
                    len(bat_serial),
                    _MIN_SERIAL_LENGTH,
                )
                continue

            poll_serials.append(bat_serial)

            # Assign a stable battery_key on first encounter
            if bat_serial not in key_map:
                idx = self._battery_next_index[inverter_serial]
                key_map[bat_serial] = f"{inverter_serial}-{idx:02d}"
                self._battery_next_index[inverter_serial] = idx + 1
                new_serials.append(bat_serial)

            battery_key = key_map[bat_serial]
            cache[battery_key] = _build_individual_battery_mapping(batt)
            _LOGGER.debug(
                "RR [%s] slot %d: serial=%s → key=%s (V=%.1f SoC=%d%%)",
                inverter_serial,
                getattr(batt, "battery_index", -1),
                bat_serial,
                battery_key,
                batt.voltage or 0.0,
                batt.soc or 0,
            )

        _LOGGER.debug(
            "RR [%s] poll summary: %d responded, %d skipped, "
            "%d new serials, %d total cached | "
            "this_poll=%s | all_known=%s",
            inverter_serial,
            len(poll_serials),
            poll_slots_skipped,
            len(new_serials),
            len(cache),
            poll_serials,
            list(key_map.keys()),
        )

        return dict(cache)

    async def _read_modbus_parameters(self, transport: Any) -> dict[str, Any]:
        """Read configuration parameters using library's named parameter mapping.

        Uses pylxpweb's read_named_parameters() which maps Modbus registers
        to HTTP API-style parameter names automatically.

        Args:
            transport: ModbusTransport or DongleTransport instance

        Returns:
            Dictionary of parameter keys to values matching HTTP API format
        """
        params: dict[str, Any] = {}

        try:
            # Read all parameter ranges using library's register-to-name mapping
            # The library handles bit field extraction automatically
            register_ranges = [
                (
                    20,
                    3,
                ),  # PV input mode (20), function enable (21), PV start voltage (22)
                # Power settings + AC charge/discharge (64-79) + forced
                # discharge power/SOC (82-83, GH #207) — one widened read
                # keeps the Modbus budget flat vs a separate (82, 2) read.
                (64, 20),
                (
                    100,
                    4,
                ),  # Off-grid cutoff voltage (100), charge/discharge current
                # (101-102), grid sell back power percent (103, GH #135)
                (105, 2),  # On-grid SOC cutoff (105-106)
                (110, 1),  # System function register (bit fields)
                (125, 1),  # Off-grid SOC cutoff (HOLD_SOC_LOW_LIMIT_EPS_DISCHG)
                (158, 2),  # AC charge start/stop voltage (158-159)
                (169, 1),  # On-grid end-of-discharge voltage (HOLD_ONGRID_EOD_VOLTAGE)
                (
                    179,
                    1,
                ),  # Extended functions (FUNC_BAT_CHARGE/DISCHARGE_CONTROL, etc.)
                (227, 2),  # System charge SOC limit (227) + voltage limit (228)
                (231, 2),  # Grid peak shaving power (_12K_HOLD_GRID_PEAK_SHAVING_POWER)
                (233, 1),  # Extended functions 2 (FUNC_BATTERY_BACKUP_CTRL, etc.)
            ]

            for start, count in register_ranges:
                try:
                    named_params = await transport.read_named_parameters(start, count)
                    params.update(named_params)
                except Exception as range_err:
                    _LOGGER.warning(
                        "Failed to read param registers %d-%d: %s",
                        start,
                        start + count - 1,
                        range_err,
                    )

            _LOGGER.debug("Read %d parameters from Modbus registers", len(params))
            # Debug: log key number entity parameters
            key_params = {
                k: v
                for k, v in params.items()
                if k
                in (
                    "HOLD_CHG_POWER_PERCENT_CMD",  # PV Charge Power (reg 64)
                    "HOLD_DISCHG_POWER_PERCENT_CMD",  # Discharge Power (reg 65)
                    "HOLD_AC_CHARGE_POWER_CMD",  # AC Charge Power (reg 66)
                    "HOLD_AC_CHARGE_SOC_LIMIT",  # AC Charge SOC Limit (reg 67)
                    "HOLD_LEAD_ACID_CHARGE_RATE",  # Charge Current (reg 101)
                    "HOLD_LEAD_ACID_DISCHARGE_RATE",  # Discharge Current (reg 102)
                    "HOLD_DISCHG_CUT_OFF_SOC_EOD",  # On-Grid SOC (reg 105)
                    "HOLD_SOC_LOW_LIMIT_EPS_DISCHG",  # Off-Grid SOC (reg 125)
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT",  # System Charge SOC (reg 227)
                    "_12K_HOLD_GRID_PEAK_SHAVING_POWER",  # Grid Peak Shaving Power (reg 231)
                )
            }
            if key_params:
                _LOGGER.debug("Number entity params: %s", key_params)

        except Exception as err:
            _LOGGER.warning("Failed to read parameters from Modbus: %s", err)

        return params

    def _build_local_device_data(
        self,
        inverter: BaseInverter,
        serial: str,
        model: str,
        firmware_version: str,
        connection_type: str,
    ) -> dict[str, Any]:
        """Build device data structure for local transport (Modbus/Dongle).

        Args:
            inverter: BaseInverter with populated transport data
            serial: Device serial number
            model: Device model name
            firmware_version: Firmware version string
            connection_type: CONNECTION_TYPE_MODBUS or CONNECTION_TYPE_DONGLE

        Returns:
            Dictionary with device data, sensors, and features
        """
        runtime = inverter.transport_runtime
        if runtime is None:
            from pylxpweb.transports.exceptions import TransportReadError

            raise TransportReadError(f"No transport runtime data for {serial}")
        device_data: dict[str, Any] = {
            "type": "inverter",
            "model": model,
            "serial": serial,
            "firmware_version": firmware_version,
            "sensors": _build_runtime_sensor_mapping(runtime),
            "batteries": {},
        }

        if energy_data := inverter.transport_energy:
            device_data["sensors"].update(_build_energy_sensor_mapping(energy_data))

        if battery_data := inverter.transport_battery:
            device_data["sensors"].update(
                _build_battery_bank_sensor_mapping(battery_data)
            )
            # Compute battery bank charge/discharge rate from merged sensor data
            compute_bank_charge_rate(device_data["sensors"])

        device_data["sensors"]["firmware_version"] = firmware_version
        device_data["sensors"]["connection_transport"] = _get_transport_label(
            connection_type
        )

        # Add computed sensors from inverter properties (for deprecated code path)
        if (val := inverter.consumption_power) is not None:
            device_data["sensors"]["consumption_power"] = val
        if (val := inverter.total_load_power) is not None:
            device_data["sensors"]["total_load_power"] = val
        if (val := inverter.battery_power) is not None:
            device_data["sensors"]["battery_power"] = val
        if (val := inverter.rectifier_power) is not None:
            device_data["sensors"]["rectifier_power"] = val
        if (val := inverter.power_to_user) is not None:
            device_data["sensors"]["grid_import_power"] = val

        transport = inverter.transport
        if transport and hasattr(transport, "host"):
            device_data["sensors"]["transport_host"] = transport.host

        # Add last_polled timestamp so users can see when data was last fetched
        # (not just when it last changed)
        device_data["sensors"]["last_polled"] = dt_util.utcnow()

        # Extract features for capability-based sensor filtering
        if features := self._extract_inverter_features(inverter):
            device_data["features"] = features
            _LOGGER.debug(
                "%s: Features for %s: %s",
                connection_type.upper(),
                serial,
                features,
            )
            alias_common_voltage_sensors(device_data["sensors"], features)

        # Drop per-inverter grid per-leg voltage when it reads 0/None (regs
        # 193/194 are firmware-zero on EG4 split-phase; real per-leg grid
        # voltage comes from the GridBOSS CTs — issue #243).
        drop_dead_inverter_grid_legs(device_data["sensors"])

        return device_data

    async def _async_update_local_transport_data(
        self,
        transport: Any,
        serial: str,
        model: str,
        connection_type: str,
    ) -> dict[str, Any]:
        """Fetch data from a single local transport (Modbus or Dongle).

        DEPRECATED: Used by _async_update_modbus_data/_async_update_dongle_data.
        Remove in v4.0 — use CONNECTION_TYPE_LOCAL with local_transports instead.
        Does NOT support GridBOSS devices (only creates BaseInverter).

        Args:
            transport: The transport instance to use
            serial: Device serial number
            model: Device model name
            connection_type: CONNECTION_TYPE_MODBUS or CONNECTION_TYPE_DONGLE

        Returns:
            Dictionary containing device data from registers.
        """
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        transport_name = connection_type.capitalize()

        try:
            _LOGGER.debug("Fetching %s data for inverter %s", transport_name, serial)

            if not transport.is_connected:
                await transport.connect()

            # Create or reuse BaseInverter via factory
            if serial not in self._inverter_cache:
                _LOGGER.debug(
                    "Creating BaseInverter from %s transport for %s",
                    transport_name,
                    serial,
                )
                if connection_type == "dongle":
                    inverter = await BaseInverter.from_dongle_transport(
                        transport, model=model
                    )
                    self._align_inverter_cache_ttls(inverter, "wifi_dongle")
                else:
                    inverter = await BaseInverter.from_modbus_transport(
                        transport, model=model
                    )
                    self._align_inverter_cache_ttls(inverter, "modbus_tcp")
                self._inverter_cache[serial] = inverter
            else:
                inverter = self._inverter_cache[serial]

            include_params = self._local_parameters_loaded
            await inverter.refresh(include_parameters=include_params)

            # Cache firmware version - only read once from transport, reuse on subsequent updates
            if serial not in self._firmware_cache:
                self._firmware_cache[serial] = (
                    await transport.read_firmware_version() or "Unknown"
                )
            firmware_version = self._firmware_cache[serial]

            if inverter.transport_runtime is None:
                raise TransportReadError(
                    f"Failed to read runtime data from {transport_name}"
                )

            device_data = self._build_local_device_data(
                inverter=inverter,
                serial=serial,
                model=model,
                firmware_version=firmware_version,
                connection_type=connection_type,
            )

            processed: dict[str, Any] = {
                "plant_id": None,
                "devices": {serial: device_data},
                "device_info": {},
                "last_update": dt_util.utcnow(),
                "connection_type": connection_type,
            }

            if include_params:
                param_data = await self._read_modbus_parameters(transport)
            else:
                param_data = {}
            processed["parameters"] = {serial: param_data}

            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 %s connection restored for inverter %s", transport_name, serial
                )
                self._last_available_state = True

            runtime = inverter.transport_runtime
            _LOGGER.debug(
                "%s update complete - FW: %s, PV: %.0fW, SOC: %d%%, Rect: %.0fW",
                transport_name,
                firmware_version,
                runtime.pv_total_power,
                runtime.battery_soc,
                runtime.rectifier_power,
            )

            # Schedule deferred parameter load on first successful refresh
            if not self._local_parameters_loaded:
                self._local_parameters_loaded = True
                _LOGGER.info(
                    "%s: First refresh complete. Scheduling background parameter load.",
                    transport_name,
                )
                task = self.hass.async_create_task(
                    self._deferred_local_parameter_load()
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            return processed

        except TransportConnectionError as e:
            self._log_transport_error(f"{transport_name} connection lost", serial, e)
            raise UpdateFailed(f"{transport_name} connection failed: {e}") from e

        except TransportTimeoutError as e:
            self._log_transport_error(f"{transport_name} timeout", serial, e)
            raise UpdateFailed(f"{transport_name} timeout: {e}") from e

        except (TransportReadError, TransportError) as e:
            self._log_transport_error(f"{transport_name} read error", serial, e)
            raise UpdateFailed(f"{transport_name} read error: {e}") from e

        except Exception as e:
            self._log_transport_error(
                f"Unexpected {transport_name} error", serial, e, log_exception=True
            )
            raise UpdateFailed(f"Unexpected error: {e}") from e

    def _log_transport_error(
        self,
        message: str,
        serial: str,
        error: Exception,
        log_exception: bool = False,
    ) -> None:
        """Log transport error and update availability state."""
        if self._last_available_state:
            _LOGGER.warning("%s for inverter %s: %s", message, serial, error)
            self._last_available_state = False
        if log_exception:
            _LOGGER.exception("%s: %s", message, error)

    async def _async_update_modbus_data(self) -> dict[str, Any]:
        """Fetch data from local Modbus transport.

        DEPRECATED: Used by old CONNECTION_TYPE_MODBUS single-device configs.
        Remove in v4.0 — use CONNECTION_TYPE_LOCAL with local_transports instead.
        Does NOT support GridBOSS devices (only BaseInverter).
        """
        if self._modbus_transport is None:
            raise UpdateFailed("Modbus transport not initialized")
        return await self._async_update_local_transport_data(
            transport=self._modbus_transport,
            serial=self._modbus_serial,
            model=self._modbus_model,
            connection_type=CONNECTION_TYPE_MODBUS,
        )

    async def _async_update_dongle_data(self) -> dict[str, Any]:
        """Fetch data from local WiFi dongle transport.

        DEPRECATED: Used by old CONNECTION_TYPE_DONGLE single-device configs.
        Remove in v4.0 — use CONNECTION_TYPE_LOCAL with local_transports instead.
        Does NOT support GridBOSS devices (only BaseInverter).
        """
        if self._dongle_transport is None:
            raise UpdateFailed("Dongle transport not initialized")
        return await self._async_update_local_transport_data(
            transport=self._dongle_transport,
            serial=self._dongle_serial,
            model=self._dongle_model,
            connection_type=CONNECTION_TYPE_DONGLE,
        )

    async def _process_local_transport_group(
        self,
        configs: list[dict[str, Any]],
        processed: dict[str, Any],
        device_availability: dict[str, bool],
    ) -> None:
        """Process a group of local transport configs that share an endpoint.

        Configs within a group are processed sequentially (they share a
        physical connection), but different groups can run concurrently.

        Args:
            configs: Transport configs sharing the same host:port or serial_port
            processed: Shared output dict (devices, parameters, etc.)
            device_availability: Shared per-device availability tracking
        """

        for config in configs:
            await self._process_single_local_device(
                config,
                processed,
                device_availability,
            )

    def _register_pg_device(self, group_device_id: str, group_name: str) -> None:
        """Pre-register a parallel group in the HA device registry.

        Ensures inverter entities referencing this PG via ``via_device`` do not
        trigger 'non existing via_device' warnings during entity setup.
        """
        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, group_device_id)},
            name=f"Parallel Group {group_name}",
            manufacturer=MANUFACTURER,
            model="Parallel Group",
        )

    async def _process_single_local_device(
        self,
        config: dict[str, Any],
        processed: dict[str, Any],
        device_availability: dict[str, bool],
    ) -> None:
        """Process a single local transport device config.

        Args:
            config: Transport configuration dict
            processed: Shared output dict
            device_availability: Shared per-device availability tracking
        """
        from pylxpweb.devices import MIDDevice
        from pylxpweb.transports import create_transport
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        serial = config.get("serial", "")
        transport_type = config.get("transport_type", "modbus_tcp")
        host = config.get("host", "")
        port = config.get("port", DEFAULT_MODBUS_PORT)

        # Serial transport doesn't require host
        if not serial or (not host and transport_type != "modbus_serial"):
            _LOGGER.warning(
                "LOCAL: Skipping invalid config (missing serial or host): %s",
                config,
            )
            return

        try:
            # Convert inverter family string to enum
            family_str = config.get("inverter_family", DEFAULT_INVERTER_FAMILY)
            inverter_family = _parse_inverter_family(family_str)

            # Get model from config, or derive from family
            model = config.get("model", "")
            if not model:
                model = INVERTER_FAMILY_DEFAULT_MODELS.get(family_str, "18kPV")

            # Create or reuse transport based on type
            is_gridboss = config.get("is_gridboss", False) or (
                serial in self._mid_device_cache
            )

            needs_creation = (
                serial not in self._mid_device_cache
                and serial not in self._inverter_cache
            )

            if needs_creation:
                transport: Any = None
                if transport_type == "modbus_tcp":
                    transport = create_transport(
                        "modbus",
                        host=host,
                        serial=serial,
                        port=port,
                        unit_id=config.get("unit_id", DEFAULT_MODBUS_UNIT_ID),
                        timeout=DEFAULT_MODBUS_TIMEOUT,
                        inverter_family=inverter_family,
                    )
                elif transport_type == "wifi_dongle":
                    transport = create_transport(
                        "dongle",
                        host=host,
                        dongle_serial=config.get("dongle_serial", ""),
                        inverter_serial=serial,
                        port=port,
                        timeout=DEFAULT_DONGLE_TIMEOUT,
                        inverter_family=inverter_family,
                    )
                elif transport_type == "modbus_serial":
                    transport = create_transport(
                        "serial",
                        port=config.get("serial_port", ""),
                        serial=serial,
                        baudrate=config.get("serial_baudrate", 19200),
                        parity=config.get("serial_parity", "N"),
                        stopbits=config.get("serial_stopbits", 1),
                        unit_id=config.get("unit_id", DEFAULT_MODBUS_UNIT_ID),
                        timeout=DEFAULT_MODBUS_TIMEOUT,
                        inverter_family=inverter_family,
                    )
                else:
                    _LOGGER.error(
                        "LOCAL: Unknown transport type '%s' for %s",
                        transport_type,
                        serial,
                    )
                    device_availability[serial] = False
                    return

                if not transport.is_connected:
                    await transport.connect()

                # Propagate split-phase config for per-leg power fallback
                grid_type = config.get(CONF_GRID_TYPE)
                transport.split_phase = grid_type == GRID_TYPE_SPLIT_PHASE

                if is_gridboss:
                    _LOGGER.debug(
                        "LOCAL: Creating GridBOSS/MIDDevice from %s transport for %s",
                        transport_type,
                        serial,
                    )
                    mid_device = await MIDDevice.from_transport(
                        transport, model="GridBOSS"
                    )
                    mid_device.validate_data = self._data_validation_enabled
                    self._mid_device_cache[serial] = mid_device
                else:
                    try:
                        _LOGGER.debug(
                            "LOCAL: Creating inverter from %s transport for %s",
                            transport_type,
                            serial,
                        )
                        if transport_type == "wifi_dongle":
                            inverter = await BaseInverter.from_dongle_transport(
                                transport, model=model
                            )
                        else:
                            inverter = await BaseInverter.from_modbus_transport(
                                transport, model=model
                            )
                        inverter.validate_data = self._data_validation_enabled
                        self._align_inverter_cache_ttls(inverter, transport_type)
                        self._inverter_cache[serial] = inverter
                    except LuxpowerDeviceError as e:
                        if "GridBOSS" in str(e) or "MIDbox" in str(e):
                            _LOGGER.info(
                                "LOCAL: Device %s is a GridBOSS, creating MIDDevice",
                                serial,
                            )
                            mid_device = await MIDDevice.from_transport(
                                transport, model="GridBOSS"
                            )
                            mid_device.validate_data = self._data_validation_enabled
                            self._mid_device_cache[serial] = mid_device
                            is_gridboss = True
                        else:
                            raise

            # Process based on device type
            if is_gridboss:
                mid_device = self._mid_device_cache[serial]

                transport = mid_device.transport
                if transport and not transport.is_connected:
                    await transport.connect()

                await mid_device.refresh()

                if serial not in self._firmware_cache:
                    fw = "Unknown"
                    read_fw = getattr(transport, "read_firmware_version", None)
                    if read_fw is not None:
                        fw = await read_fw() or "Unknown"
                    self._firmware_cache[serial] = fw
                firmware_version = self._firmware_cache[serial]

                if not mid_device.has_data:
                    raise TransportReadError(
                        f"Failed to read runtime data for GridBOSS {serial}"
                    )

                sensors = _build_gridboss_sensor_mapping(mid_device)
                sensors = {k: v for k, v in sensors.items() if v is not None}
                self._filter_unused_smart_port_sensors(sensors, mid_device)
                self._calculate_gridboss_aggregates(sensors)
                sensors["firmware_version"] = firmware_version
                sensors["connection_transport"] = _get_transport_label(
                    "dongle" if transport_type == "wifi_dongle" else "modbus"
                )
                sensors["transport_host"] = host

                device_data: dict[str, Any] = {
                    "type": "gridboss",
                    "model": "GridBOSS",
                    "serial": serial,
                    "firmware_version": firmware_version,
                    "sensors": sensors,
                    "binary_sensors": {},
                }

                processed["devices"][serial] = device_data
                device_availability[serial] = True

                processed["parameters"][serial] = {}

                _LOGGER.debug(
                    "LOCAL: Updated GridBOSS %s (%s) - FW: %s, Grid: %sW, Load: %sW",
                    serial,
                    transport_type,
                    firmware_version,
                    sensors.get("grid_power", "N/A"),
                    sensors.get("load_power", "N/A"),
                )
            else:
                inverter = self._inverter_cache[serial]

                transport = inverter.transport
                if transport and not transport.is_connected:
                    await transport.connect()

                # Use the per-cycle decision computed in _async_update_local_data
                # (or fall back to the direct check for the deprecated single-
                # device path which doesn't set _include_params_this_cycle).
                include_params = getattr(self, "_include_params_this_cycle", False)
                await inverter.refresh(include_parameters=include_params)

                features: dict[str, Any] = {}
                if hasattr(inverter, "detect_features"):
                    # detect_features() reads holding registers and is therefore
                    # throttled to parameter-refresh polls; it persists the
                    # InverterFeatures on the (cached) inverter object.
                    # _extract_inverter_features() just reads that cached state,
                    # so run it on EVERY poll — the sensor mapping/gating and the
                    # voltage alias below need the feature flags on every cycle,
                    # not only on param-refresh cycles.  Previously features were
                    # populated solely on param polls, leaving the aggregate
                    # eps_voltage/grid_voltage alias starved on the common path
                    # so it never fired (issue #243).
                    if include_params:
                        try:
                            await inverter.detect_features()
                        except Exception as e:
                            _LOGGER.warning(
                                "LOCAL: Could not detect features for %s: %s",
                                serial,
                                e,
                            )
                    features = self._extract_inverter_features(inverter)
                    # Re-apply the user's grid-type override AFTER extraction:
                    # the model-family fallback inside the extractor can flip
                    # phase flags, and without this the override only survived
                    # the static first refresh — the second poll flipped the
                    # features back and churned phase sensors (#219 review).
                    grid_type_override = config.get(CONF_GRID_TYPE)
                    if features and grid_type_override:
                        _apply_grid_type_override(features, grid_type_override)
                    if include_params and features:
                        _LOGGER.debug(
                            "LOCAL: Detected features for %s: family=%s, "
                            "split_phase=%s, three_phase=%s",
                            serial,
                            features.get("inverter_family"),
                            features.get("supports_split_phase"),
                            features.get("supports_three_phase"),
                        )

                if serial not in self._firmware_cache:
                    fw = "Unknown"
                    transport = inverter.transport
                    read_fw = (
                        getattr(transport, "read_firmware_version", None)
                        if transport
                        else None
                    )
                    if read_fw is not None:
                        fw = await read_fw() or "Unknown"
                    self._firmware_cache[serial] = fw
                firmware_version = self._firmware_cache[serial]

                runtime_data = inverter.transport_runtime
                energy_data = inverter.transport_energy

                if runtime_data is None:
                    raise TransportReadError(
                        f"Failed to read runtime data for {serial}"
                    )

                parallel_number = runtime_data.parallel_number or 0
                parallel_master_slave = runtime_data.parallel_master_slave or 0
                parallel_phase = runtime_data.parallel_phase or 0

                if parallel_number == 0:
                    parallel_number = config.get("parallel_number", 0)
                    parallel_master_slave = config.get("parallel_master_slave", 0)
                    parallel_phase = config.get("parallel_phase", 0)

                if parallel_number > 0:
                    _LOGGER.debug(
                        "LOCAL: Parallel config for %s: group=%d, role=%d (from %s)",
                        serial,
                        parallel_number,
                        parallel_master_slave,
                        "runtime"
                        if (runtime_data.parallel_number or 0) > 0
                        else "config",
                    )

                device_data = {
                    "type": "inverter",
                    "model": model,
                    "serial": serial,
                    "firmware_version": firmware_version,
                    "sensors": _build_runtime_sensor_mapping(runtime_data),
                    "batteries": {},
                    "features": features,
                    "parallel_number": parallel_number,
                    "parallel_master_slave": parallel_master_slave,
                    "parallel_phase": parallel_phase,
                }

                if energy_data:
                    device_data["sensors"].update(
                        _build_energy_sensor_mapping(energy_data)
                    )

                battery_data = inverter.transport_battery
                if battery_data:
                    # Skip battery bank creation when battery_count is 0.
                    # In parallel systems with shared batteries, the secondary
                    # inverter reports battery_count=0 at reg 96 because the
                    # CAN bus is wired only to the primary.  Per-inverter
                    # sensors (battery_voltage, battery_current, state_of_charge)
                    # from runtime registers still report accurate values.
                    # This matches CLOUD path behavior where the API returns
                    # totalNumber=0 for secondary inverters (issue #169).
                    bank_count = battery_data.battery_count or 0

                    if bank_count == 0:
                        if serial not in self._shared_battery_logged:
                            _LOGGER.info(
                                "LOCAL: Skipping battery bank for %s "
                                "(battery_count=0, shared battery secondary)",
                                serial,
                            )
                            self._shared_battery_logged.add(serial)
                    else:
                        device_data["sensors"].update(
                            _build_battery_bank_sensor_mapping(battery_data)
                        )
                        # Compute battery bank charge/discharge rate
                        compute_bank_charge_rate(device_data["sensors"])

                        if (
                            hasattr(battery_data, "batteries")
                            and battery_data.batteries
                        ):
                            # Round-robin merge: some firmware rotates which
                            # physical batteries appear in the fixed register
                            # slots.  Accumulate by battery serial so all
                            # batteries eventually appear as entities.
                            device_data["batteries"] = (
                                self._merge_round_robin_batteries(
                                    serial, list(battery_data.batteries)
                                )
                            )
                            _LOGGER.debug(
                                "LOCAL: %d individual batteries for %s "
                                "(%d this poll, %d cached)",
                                len(device_data["batteries"]),
                                serial,
                                len(battery_data.batteries),
                                len(self._battery_rr_cache.get(serial, {})),
                            )
                        elif serial in self._battery_rr_cache:
                            # Individual battery registers unavailable this poll
                            # (e.g. transient read failure).  Serve cached data
                            # so entities stay available rather than going
                            # unavailable until the next successful read.
                            device_data["batteries"] = dict(
                                self._battery_rr_cache[serial]
                            )
                            _LOGGER.debug(
                                "LOCAL: %s serving %d individual batteries "
                                "from cache (no battery data this poll)",
                                serial,
                                len(device_data["batteries"]),
                            )

                device_data["sensors"]["firmware_version"] = firmware_version
                device_data["sensors"]["connection_transport"] = _get_transport_label(
                    "dongle" if transport_type == "wifi_dongle" else "modbus"
                )
                device_data["sensors"]["transport_host"] = host

                # Add computed sensors from inverter properties
                # These use stable library interfaces for consistency
                sensors = device_data["sensors"]

                # Computed power sensors from pylxpweb library
                if (val := inverter.consumption_power) is not None:
                    sensors["consumption_power"] = val
                if (val := inverter.total_load_power) is not None:
                    sensors["total_load_power"] = val
                if (val := inverter.battery_power) is not None:
                    sensors["battery_power"] = val
                if (val := inverter.rectifier_power) is not None:
                    sensors["rectifier_power"] = val
                if (val := inverter.power_to_user) is not None:
                    sensors["grid_import_power"] = val

                # Add last_polled timestamp so users can see when data was last fetched
                # (not just when it last changed)
                sensors["last_polled"] = dt_util.utcnow()

                # Derive phase-neutral aggregate voltages (grid_voltage,
                # eps_voltage) from the R-phase registers for non-three-phase
                # configs.  This active multi-transport poll path builds the
                # sensor dict inline, unlike the deprecated single-device path
                # (_build_local_device_data), so the alias must be applied here
                # too.  Without it, split-phase models (18kPV/FlexBOSS) report
                # "unknown" for the aggregate EPS/grid voltage even though the
                # per-leg L1/L2 sensors populate correctly (issue #243).
                if features:
                    alias_common_voltage_sensors(sensors, features)

                # Drop per-inverter grid per-leg voltage when it reads 0/None.
                # EG4 split-phase firmware leaves regs 193/194 at 0; the real
                # per-leg grid voltage comes from the GridBOSS CTs (#243).
                drop_dead_inverter_grid_legs(sensors)

                _LOGGER.debug(
                    "LOCAL: Computed sensors for %s: consumption=%s, total_load=%s, "
                    "battery=%s, rectifier=%s, grid_import=%s",
                    serial,
                    sensors.get("consumption_power"),
                    sensors.get("total_load_power"),
                    sensors.get("battery_power"),
                    sensors.get("rectifier_power"),
                    sensors.get("grid_import_power"),
                )

                processed["devices"][serial] = device_data
                device_availability[serial] = True

                if include_params:
                    transport = inverter.transport
                    if transport:
                        param_data = await self._read_modbus_parameters(transport)
                    else:
                        param_data = {}
                    processed["parameters"][serial] = param_data
                elif serial not in processed["parameters"]:
                    # No param read this cycle — preserve existing data or
                    # defer on first refresh (empty dict is safe — switch/number
                    # entities show unknown until background load completes).
                    processed["parameters"][serial] = {}

                _LOGGER.debug(
                    "LOCAL: Updated %s (%s) - FW: %s, PV: %.0fW, SOC: %d%%, Rect: %.0fW",
                    serial,
                    transport_type,
                    firmware_version,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                    runtime_data.rectifier_power,
                )

                _LOGGER.debug(
                    "LOCAL: Extended sensors for %s: gen_freq=%s, gen_volt=%s, "
                    "grid_l1=%s, grid_l2=%s, eps_l1=%s, eps_l2=%s, out_pwr=%s",
                    serial,
                    getattr(runtime_data, "generator_frequency", None),
                    getattr(runtime_data, "generator_voltage", None),
                    getattr(runtime_data, "grid_l1_voltage", None),
                    getattr(runtime_data, "grid_l2_voltage", None),
                    getattr(runtime_data, "eps_l1_voltage", None),
                    getattr(runtime_data, "eps_l2_voltage", None),
                    getattr(runtime_data, "output_power", None),
                )

        except (
            TransportConnectionError,
            TransportTimeoutError,
            TransportReadError,
            TransportError,
        ) as e:
            device = self._inverter_cache.get(serial) or self._mid_device_cache.get(
                serial
            )
            if device is not None and is_transport_link_down(device):
                # Link already declared down: the transition logged one
                # warning and raised a Repairs issue — keep the per-cycle
                # noise at debug while the outage lasts (eg4-57g).
                _LOGGER.debug(
                    "LOCAL: %s (%s) still link-down: %s",
                    serial,
                    transport_type,
                    e,
                )
            else:
                _LOGGER.warning(
                    "LOCAL: Failed to update %s (%s): %s",
                    serial,
                    transport_type,
                    e,
                )
            device_availability[serial] = False

        except Exception as e:
            _LOGGER.exception(
                "LOCAL: Unexpected error updating %s (%s): %s",
                serial,
                transport_type,
                e,
            )
            device_availability[serial] = False

    async def _deferred_local_parameter_load(self) -> None:
        """Background task: load parameters and detect features for local devices.

        Runs after the first successful local refresh so that HA setup isn't
        blocked by the heavy holding-register reads (~8 reads per inverter).
        Triggers a coordinator refresh when done so entities pick up the new
        parameter and feature data.

        Uses force=False so that runtime/energy/battery caches (populated by
        the normal poll cycle) are respected — only parameters (never loaded,
        so cache-expired) will actually trigger Modbus reads.  This avoids
        concurrent Modbus access with the regular poll cycle.
        """
        try:
            loaded = 0
            for serial, inverter in self._inverter_cache.items():
                try:
                    # force=False: reuse cached runtime/energy/battery from
                    # the poll cycle, only fetch parameters (holding registers)
                    await inverter.refresh(force=False, include_parameters=True)
                    if hasattr(inverter, "detect_features"):
                        await inverter.detect_features()
                    loaded += 1
                    _LOGGER.debug(
                        "LOCAL: Background parameter load complete for %s",
                        serial,
                    )
                except Exception as e:
                    _LOGGER.warning(
                        "LOCAL: Background parameter load failed for %s: %s",
                        serial,
                        e,
                    )

            # Propagate total inverter rated power to GridBOSS devices so
            # their energy delta and power canary thresholds scale correctly.
            detected = (
                inv
                for inv in self._inverter_cache.values()
                if getattr(inv, "_features_detected", False)
            )
            total_kw = compute_total_inverter_power_kw(detected)
            if total_kw > 0:
                for mid in self._mid_device_cache.values():
                    mid.set_max_system_power(total_kw)

            if loaded > 0:
                _LOGGER.info(
                    "LOCAL: Background parameter load finished (%d/%d devices). "
                    "Requesting coordinator refresh.",
                    loaded,
                    len(self._inverter_cache),
                )
                await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("LOCAL: Background parameter load error: %s", e)

    def _warn_dongle_validation_disabled(self) -> None:
        """Create a Repairs issue if a WiFi dongle is configured without data validation."""
        if not self._has_dongle_transport() or self._data_validation_enabled:
            return
        _LOGGER.warning(
            "WiFi dongle detected but data validation is disabled. "
            "Enable it in Options to prevent corrupt register data."
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "dongle_validation_disabled",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dongle_validation_disabled",
        )

    def _build_static_local_data(self) -> dict[str, Any]:
        """Build device data from config entry metadata without register reads.

        Used for immediate entity creation during the first coordinator refresh.
        Sensor keys are pre-populated with None values — real values arrive from
        the background refresh that follows.
        """
        processed: dict[str, Any] = {
            "plant_id": None,
            "devices": {},
            "device_info": {},
            "parameters": {},
            "last_update": dt_util.utcnow(),
            "connection_type": CONNECTION_TYPE_LOCAL,
        }

        for config in self._local_transport_configs:
            serial = config.get("serial", "")
            model = config.get("model", "")
            is_gridboss = config.get("is_gridboss", False)
            firmware = config.get("firmware_version", "Unknown")

            if is_gridboss:
                sensor_keys = GRIDBOSS_STATIC_ENTITY_KEYS
                device_type = "gridboss"
            else:
                sensor_keys = ALL_INVERTER_SENSOR_KEYS
                device_type = "inverter"

            # Pre-populate sensors: keys present (for entity creation), values None
            sensors: dict[str, Any] = {k: None for k in sensor_keys}
            # Fill in known metadata from config entry
            sensors["firmware_version"] = firmware
            transport_type = config.get("transport_type", "modbus_tcp")
            sensors["connection_transport"] = _get_transport_label(
                "dongle" if transport_type == "wifi_dongle" else "modbus"
            )
            sensors["transport_host"] = config.get("host", "")

            # Derive feature flags from inverter family and device_type_code so
            # that _should_create_sensor() filters phase-specific sensors correctly
            # even before Modbus-based feature detection runs. The model name is
            # the last-resort family fallback when config stored an UNKNOWN or
            # missing family (issue #219).
            family_str = config.get("inverter_family")
            dtc = config.get("device_type_code")
            grid_type = config.get("grid_type")
            features = (
                _features_from_family(family_str, dtc, grid_type=grid_type, model=model)
                if not is_gridboss
                else {}
            )

            if features.get("family_source") == "model_fallback":
                # Behavior change for legacy UNKNOWN-family entries: the static
                # path used to create ALL sensors for them (including bogus
                # three-phase R/S/T ones that never had data). The fallback now
                # prunes to the model's real profile — surface that loudly so
                # automations referencing the dropped sensors don't break
                # silently (#219 review).
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"unknown_family_fallback_{serial}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="unknown_family_fallback",
                    translation_placeholders={
                        "serial": str(serial),
                        "model": str(model),
                        "family": str(features.get("inverter_family", "")),
                    },
                )

            device_data: dict[str, Any] = {
                "type": device_type,
                "model": model or ("GridBOSS" if is_gridboss else "Unknown"),
                "serial": serial,
                "firmware_version": firmware,
                "sensors": sensors,
                "batteries": {},
                "features": features,
                "parallel_number": config.get("parallel_number", 0),
                "parallel_master_slave": config.get("parallel_master_slave", 0),
                "parallel_phase": config.get("parallel_phase", 0),
            }

            if is_gridboss:
                device_data["binary_sensors"] = {}

            processed["devices"][serial] = device_data
            processed["parameters"][serial] = {}

        self._add_static_parallel_groups(processed)
        self._warn_dongle_validation_disabled()

        return processed

    def _add_static_parallel_groups(self, processed: dict[str, Any]) -> None:
        """Add parallel group device entries to static data when inferable.

        Groups non-gridboss configs by parallel_number (mirroring the real
        _process_local_parallel_groups logic) so device IDs stay consistent
        across static and real refresh phases.

        Falls back to a device-count heuristic (2+ non-gridboss devices) when
        no parallel_number info is stored in config (e.g., legacy entries).
        """
        # Group non-gridboss configs by parallel_number
        parallel_groups: dict[int, list[dict[str, Any]]] = {}
        non_gridboss_configs: list[dict[str, Any]] = []
        has_gridboss = False

        for config in self._local_transport_configs:
            if config.get("is_gridboss", False):
                has_gridboss = True
                continue
            non_gridboss_configs.append(config)
            pn = config.get("parallel_number", 0)
            if pn > 0:
                parallel_groups.setdefault(pn, []).append(config)

        # Fallback: no parallel_number info but 2+ inverters/devices
        if not parallel_groups and len(non_gridboss_configs) >= 2:
            parallel_groups[1] = non_gridboss_configs

        if not parallel_groups:
            return

        for group_index, (_, group_configs) in enumerate(
            sorted(parallel_groups.items())
        ):
            group_name = chr(ord("A") + group_index)

            # Find master (parallel_master_slave == 1) or use first serial
            first_serial = group_configs[0].get("serial", "")
            for cfg in group_configs:
                if cfg.get("parallel_master_slave", 0) == 1:
                    first_serial = cfg.get("serial", "")
                    break

            # Use group name as device ID for consistency with cloud API.
            # Cloud API identifies groups by parallelGroup name ("A", "B").
            # Using the name instead of a device serial ensures entity IDs
            # remain stable across LOCAL/HYBRID/cloud mode transitions.
            group_device_id = f"parallel_group_{group_name.lower()}"

            sensor_keys = PARALLEL_GROUP_SENSOR_KEYS
            if has_gridboss:
                sensor_keys = sensor_keys | PARALLEL_GROUP_GRIDBOSS_KEYS

            processed["devices"][group_device_id] = {
                "type": "parallel_group",
                "name": f"Parallel Group {group_name}",
                "group_name": group_name,
                "first_device_serial": first_serial,
                "member_count": len(group_configs),
                "member_serials": [c.get("serial", "") for c in group_configs],
                "sensors": {k: None for k in sensor_keys},
            }

            self._register_pg_device(group_device_id, group_name)

            _LOGGER.debug(
                "LOCAL: Static parallel group %s created with %d members "
                "(device_id=%s, %d sensor keys)",
                group_name,
                len(group_configs),
                group_device_id,
                len(sensor_keys),
            )

    async def _async_update_local_data(self) -> dict[str, Any]:
        """Fetch data from multiple local transports (Modbus + Dongle mix).

        LOCAL mode allows configuring multiple inverters with different transport
        types in a single config entry, without any cloud credentials.

        Transports on different endpoints (host:port or serial port) are polled
        concurrently via asyncio.gather. Transports sharing the same endpoint
        are processed sequentially to avoid contention on the shared connection.

        Individual device failures are isolated - one device failing doesn't
        break others. Only if ALL devices fail does this method raise
        UpdateFailed.

        Returns:
            Dictionary containing data from all local devices.

        Raises:
            UpdateFailed: If no transports configured or ALL devices failed.
        """
        if not self._local_transport_configs:
            raise UpdateFailed("No local transports configured")

        # Phase 1: Return static data for immediate entity creation.
        # Real data follows from the background refresh scheduled below.
        if not self._local_static_phase_done:
            self._local_static_phase_done = True
            _LOGGER.info(
                "LOCAL: Returning static device data for %d devices "
                "(real data follows via background refresh)",
                len(self._local_transport_configs),
            )
            # Schedule an immediate follow-up refresh to load real register data.
            # This runs AFTER async_config_entry_first_refresh() completes and
            # entity platforms finish setup.
            self.hass.async_create_task(self.async_request_refresh())
            return self._build_static_local_data()

        # Phase 2+: Normal register read path
        # Build processed data structure
        processed: dict[str, Any] = {
            "plant_id": None,  # No plant for LOCAL mode
            "devices": {},
            "device_info": {},
            "parameters": {},
            "last_update": dt_util.utcnow(),
            "connection_type": CONNECTION_TYPE_LOCAL,
        }

        # Pre-populate with cached data from previous update so that
        # skipped transports (interval not elapsed) retain prior values.
        if self.data:
            processed["devices"].update(self.data.get("devices", {}))
            processed["parameters"].update(self.data.get("parameters", {}))

        # Track per-device availability for partial failure handling
        device_availability: dict[str, bool] = {}

        # Partition configs: only poll transports whose interval has elapsed.
        # Skipped devices retain cached data from the pre-population above.
        # Pre-compute which transport types should poll this tick so that the
        # interval gate fires once per type, not once per device.  Without this,
        # the first device of a type stamps the timestamp and all subsequent
        # devices of the same type get skipped.
        transport_types_seen: set[str] = set()
        pollable_types: set[str] = set()
        for config in self._local_transport_configs:
            tt = config.get("transport_type", "modbus_tcp")
            if tt not in transport_types_seen:
                transport_types_seen.add(tt)
                if self._should_poll_transport(tt):
                    pollable_types.add(tt)

        # Pre-compute parameter refresh decision once for the entire poll cycle
        # so every device sees the same answer.  Stored as instance attr because
        # _process_single_local_device reads it without a parameter change.
        self._include_params_this_cycle = (
            self._local_parameters_loaded and self._should_refresh_parameters()
        )

        configs_to_poll: list[dict[str, Any]] = []
        for config in self._local_transport_configs:
            transport_type = config.get("transport_type", "modbus_tcp")
            serial = config.get("serial", "")
            if transport_type in pollable_types:
                configs_to_poll.append(config)
            else:
                if serial:
                    device_availability[serial] = True
                _LOGGER.debug(
                    "LOCAL: Skipping %s device %s (interval not elapsed)",
                    transport_type,
                    serial,
                )

        if not configs_to_poll and processed["devices"]:
            # All transports skipped but we have cached data — return it
            return processed

        # Group transports by connection endpoint so that devices sharing
        # the same physical connection are polled sequentially, while
        # independent endpoints are polled concurrently.
        endpoint_groups: dict[str, list[dict[str, Any]]] = {}
        for config in configs_to_poll:
            transport_type = config.get("transport_type", "modbus_tcp")
            if transport_type == "modbus_serial":
                key = config.get("serial_port", "")
            else:
                key = f"{config.get('host', '')}:{config.get('port', DEFAULT_MODBUS_PORT)}"
            endpoint_groups.setdefault(key, []).append(config)

        # Process groups concurrently — devices within each group sequentially
        if len(endpoint_groups) > 1:
            _LOGGER.debug(
                "LOCAL: Polling %d endpoint groups concurrently",
                len(endpoint_groups),
            )
            results = await asyncio.gather(
                *(
                    self._process_local_transport_group(
                        group,
                        processed,
                        device_availability,
                    )
                    for group in endpoint_groups.values()
                ),
                return_exceptions=True,
            )
            # Log any unexpected exceptions from gather
            for result in results:
                if isinstance(result, Exception):
                    _LOGGER.exception(
                        "LOCAL: Unexpected error in transport group: %s",
                        result,
                    )
        else:
            # Single group — process directly without gather overhead
            for group in endpoint_groups.values():
                await self._process_local_transport_group(
                    group,
                    processed,
                    device_availability,
                )

        # Mark link-down devices (error key -> entities unavailable) and
        # sync their Repairs issues.  Runs BEFORE the all-failed check so a
        # full-outage cycle still raises/clears the issues (eg4-57g).
        self._sync_transport_link_state(processed)

        # Check if we got any device data
        successful_devices = sum(1 for v in device_availability.values() if v)
        total_devices = len(self._local_transport_configs)

        if successful_devices == 0:
            # Silver tier logging: Log when all devices become unavailable
            if self._last_available_state:
                _LOGGER.warning(
                    "LOCAL: All %d devices unavailable",
                    total_devices,
                )
                self._last_available_state = False
            # Full outage raises BEFORE _process_local_parallel_groups()
            # runs, so the carried-forward PG entries would otherwise keep
            # passing entity availability and serve the stale aggregate
            # during the wrapper's suppressed-failure window (cached data
            # returned, last_update_success still True) — eg4-57g review r2.
            self._error_mark_stale_parallel_groups(processed)
            raise UpdateFailed(f"All {total_devices} local transports failed to update")

        # Silver tier logging: Log when service becomes available again
        if not self._last_available_state:
            _LOGGER.warning(
                "LOCAL: Connection restored - %d/%d devices available",
                successful_devices,
                total_devices,
            )
            self._last_available_state = True

        # Log partial failure if some devices failed
        if successful_devices < total_devices:
            _LOGGER.warning(
                "LOCAL: Partial update - %d/%d devices updated successfully",
                successful_devices,
                total_devices,
            )
        else:
            _LOGGER.debug(
                "LOCAL: Successfully updated all %d devices",
                total_devices,
            )

        # Process local parallel groups from device config
        await self._process_local_parallel_groups(processed)

        # Stamp parameter refresh timestamp if params were read this cycle.
        if self._include_params_this_cycle and successful_devices > 0:
            self._last_parameter_refresh = dt_util.utcnow()

        # On first successful refresh, schedule background parameter +
        # feature detection load so that switch/number entities and
        # capability-based sensor filtering become available on the
        # next coordinator cycle without blocking HA setup.
        if not self._local_parameters_loaded and successful_devices > 0:
            self._local_parameters_loaded = True
            _LOGGER.info(
                "LOCAL: First refresh complete (%d/%d devices). "
                "Scheduling background parameter load.",
                successful_devices,
                total_devices,
            )
            task = self.hass.async_create_task(self._deferred_local_parameter_load())
            self._background_tasks.add(task)
            task.add_done_callback(self._remove_task_from_set)
            task.add_done_callback(self._log_task_exception)

        return processed

    async def _process_local_parallel_groups(self, processed: dict[str, Any]) -> None:
        """Create local parallel groups from devices sharing the same parallel_number.

        In LOCAL mode, we don't have the cloud API to tell us about parallel groups.
        Instead, we read the parallel configuration from each device's registers
        (either from config or at runtime) and group devices with the same
        parallel_number together.

        This method creates aggregate "parallel_group_X" device entries with
        combined power/energy sensors calculated from the member devices.

        Args:
            processed: The processed data dict to update with parallel group entries.
        """
        # Group devices by their parallel_number from device_data (includes runtime reads)
        parallel_groups: dict[int, list[tuple[str, dict[str, Any]]]] = {}

        for serial, device_data in processed.get("devices", {}).items():
            # Skip non-inverter devices (GridBOSS, parallel groups themselves)
            if device_data.get("type") != "inverter":
                continue

            parallel_number = device_data.get("parallel_number", 0)
            if parallel_number == 0:
                # Standalone device, not in a parallel group
                continue

            if parallel_number not in parallel_groups:
                parallel_groups[parallel_number] = []

            parallel_groups[parallel_number].append((serial, device_data))

        if not parallel_groups:
            _LOGGER.debug("LOCAL: No parallel groups detected")
            return

        _LOGGER.debug(
            "LOCAL: Processing %d parallel groups: %s",
            len(parallel_groups),
            list(parallel_groups.keys()),
        )

        # Process each parallel group
        # Use enumerate to get sequential names (A, B, C...) regardless of parallel_number value
        for group_index, (parallel_number, group_devices) in enumerate(
            parallel_groups.items()
        ):
            # Group name: 'A' for first group, 'B' for second, etc.
            group_name = chr(ord("A") + group_index)

            # Find the master device (parallel_master_slave == 1)
            # If no master found, use the first device
            master_serial = None
            for serial, device_data in group_devices:
                if device_data.get("parallel_master_slave", 0) == 1:
                    master_serial = serial
                    break
            if master_serial is None:
                master_serial = group_devices[0][0]

            first_serial = master_serial

            # Members whose device data is error-marked (link-down — see
            # _sync_transport_link_state, which runs before this method).
            # Their carried-forward sensors are STALE: an aggregate mixing
            # stale and fresh members is wrong in both directions, so the
            # group is error-marked below — honest unavailability beats a
            # quietly wrong total (eg4-57g review).
            link_down_members = sorted(
                member_serial
                for member_serial, member_data in group_devices
                if "error" in member_data
            )

            # Collect sensor data from all devices in the group
            group_sensors: dict[str, Any] = {}
            device_count = 0

            # Power sensors to sum (battery handled separately as parallel_battery_*)
            # Note: PV string sensors (pv1/2/3) excluded — per-inverter detail
            # is not useful at group level; pv_total_power covers the aggregate.
            power_sensors = [
                "pv_total_power",
                "grid_power",
                "grid_import_power",
                "grid_export_power",
                "consumption_power",
                "eps_power",
                "battery_power",
                "ac_power",  # Inverter output power (matches HTTP mode)
                "output_power",  # Split-phase total output
            ]

            # Energy sensors to sum
            energy_sensors = [
                "yield",
                "charging",
                "discharging",
                "grid_import",
                "grid_export",
                "consumption",
                "yield_lifetime",
                "charging_lifetime",
                "discharging_lifetime",
                "grid_import_lifetime",
                "grid_export_lifetime",
                "consumption_lifetime",
            ]

            # Battery sensors - need weighted average for SOC
            total_soc = 0.0
            soc_count = 0
            total_battery_voltage = 0.0
            voltage_count = 0

            for serial, device_data in group_devices:
                device_count += 1
                device_sensors = device_data.get("sensors", {})

                # Sum power sensors
                for sensor_key in power_sensors:
                    value = device_sensors.get(sensor_key)
                    if value is not None:
                        group_sensors[sensor_key] = group_sensors.get(
                            sensor_key, 0.0
                        ) + float(value)

                # Sum energy sensors
                for sensor_key in energy_sensors:
                    value = device_sensors.get(sensor_key)
                    if value is not None:
                        group_sensors[sensor_key] = group_sensors.get(
                            sensor_key, 0.0
                        ) + float(value)

                # Collect SOC for averaging
                soc = device_sensors.get("state_of_charge")
                if soc is not None:
                    total_soc += float(soc)
                    soc_count += 1

                # Collect voltage for averaging
                voltage = device_sensors.get("battery_voltage")
                if voltage is not None:
                    total_battery_voltage += float(voltage)
                    voltage_count += 1

                _LOGGER.debug(
                    "LOCAL: Parallel group %s member %s: "
                    "battery_power=%s, pv=%s, soc=%s",
                    group_name,
                    serial,
                    device_sensors.get("battery_power"),
                    device_sensors.get("pv_total_power"),
                    device_sensors.get("state_of_charge"),
                )

            # Remap summed battery_power to parallel_battery_power for consistency
            # with cloud mode (which uses _process_parallel_group_object).
            # battery_power: positive = charging, negative = discharging
            net_power = group_sensors.pop("battery_power", 0.0)
            group_sensors["parallel_battery_power"] = net_power

            _LOGGER.debug(
                "LOCAL: Parallel group %s battery aggregation: "
                "net=%.1f (positive=charging)",
                group_name,
                net_power,
            )

            if soc_count > 0:
                group_sensors["parallel_battery_soc"] = round(total_soc / soc_count, 1)

            if voltage_count > 0:
                group_sensors["parallel_battery_voltage"] = round(
                    total_battery_voltage / voltage_count, 1
                )

            # Aggregate battery_bank_current from member inverters.
            # Secondaries with battery_count=0 have no battery_bank_* sensors,
            # so they naturally contribute nothing to the sum.
            total_battery_current = 0.0
            has_battery_current = False
            for _, dd in group_devices:
                bat_current = dd.get("sensors", {}).get("battery_bank_current")
                if bat_current is not None:
                    total_battery_current += float(bat_current)
                    has_battery_current = True
            if has_battery_current:
                group_sensors["parallel_battery_current"] = total_battery_current

            # Sum battery_bank_count from all member devices.
            # Use battery_bank_count from sensors (from Modbus register 96 or cloud batParallelNum)
            # rather than counting batteries dict entries, which may be empty if CAN bus
            # communication with battery BMS isn't established (common with LXP-EU devices)
            total_batteries = 0
            for _, dd in group_devices:
                ds = dd.get("sensors", {})
                bat_count = ds.get("battery_bank_count")
                if bat_count is not None and bat_count > 0:
                    total_batteries += bat_count
            group_sensors["parallel_battery_count"] = total_batteries

            # Sum max/current capacity from inverter battery bank sensors
            total_max_cap = 0.0
            total_cur_cap = 0.0
            for _, dd in group_devices:
                ds = dd.get("sensors", {})
                max_cap = ds.get("battery_bank_max_capacity")
                if max_cap is not None:
                    total_max_cap += float(max_cap)
                cur_cap = ds.get("battery_bank_current_capacity")
                if cur_cap is not None:
                    total_cur_cap += float(cur_cap)
            if total_max_cap > 0:
                group_sensors["parallel_battery_max_capacity"] = total_max_cap
            if total_cur_cap > 0:
                group_sensors["parallel_battery_current_capacity"] = total_cur_cap

            # Compute parallel group charge/discharge C-rates (%/h)
            compute_parallel_group_charge_rate(group_sensors)

            # Override grid/load power, energy, and voltage with MID device
            # (GridBOSS) data if available.  The MID device has grid CTs and is
            # the authoritative source for grid interaction — inverters don't
            # see the actual grid import/export.
            has_mid_device = False
            for serial, device_data in processed.get("devices", {}).items():
                if device_data.get("type") != "gridboss":
                    continue
                has_mid_device = True
                # The GridBOSS CTs are authoritative contributors to the
                # group's grid/consumption values — a link-down (error-
                # marked) GridBOSS taints the aggregate the same way a
                # link-down inverter member does.
                if "error" in device_data and serial not in link_down_members:
                    link_down_members.append(serial)
                gb_sensors = device_data.get("sensors", {})

                # Apply the canonical GridBOSS workflow to the parallel group.
                # The MID device has grid CTs and is the authoritative source
                # for grid interaction — inverters don't see actual grid
                # import/export, so LOCAL recomputes consumption_power from the
                # energy balance (recompute_consumption=True).  Shared with the
                # HTTP/HYBRID path so the overlay/AC-couple sequence cannot
                # diverge.  AC-couple PV inclusion is configurable via options.
                include_ac_couple = self.entry.options.get(
                    CONF_INCLUDE_AC_COUPLE_PV,
                    self.entry.data.get(CONF_INCLUDE_AC_COUPLE_PV, False),
                )
                apply_gridboss_to_parallel_group(
                    group_sensors,
                    gb_sensors,
                    group_name,
                    include_ac_couple=include_ac_couple,
                    recompute_consumption=True,
                )

                break  # Only one MID device per system

            # Fallback: copy grid voltage from master inverter when no MID
            # device is present.  MID devices provide authoritative grid
            # voltage via the overlay above; inverter regs 193-194 return 0
            # on 18kPV/FlexBOSS firmware so the overlay is preferred.
            if not has_mid_device:
                for serial, dd in group_devices:
                    if serial == first_serial:
                        master_sensors = dd.get("sensors", {})
                        for vkey in ("grid_voltage_l1", "grid_voltage_l2"):
                            val = master_sensors.get(vkey)
                            if val is not None:
                                group_sensors[vkey] = val
                        break

            group_device_id = f"parallel_group_{group_name.lower()}"

            if link_down_members:
                # Don't claim a fresh poll for an aggregate built from stale
                # members — carry the previous stamp forward (if any) so it
                # reflects the last genuinely fresh aggregate.
                prev_stamp = (
                    processed["devices"]
                    .get(group_device_id, {})
                    .get("sensors", {})
                    .get("parallel_group_last_polled")
                )
                if prev_stamp is not None:
                    group_sensors["parallel_group_last_polled"] = prev_stamp
            else:
                group_sensors["parallel_group_last_polled"] = dt_util.utcnow()

            # Create groups even with 1 inverter if parallel_number > 0,
            # since this indicates the inverter is configured for parallel
            # operation (e.g., single inverter + GridBOSS setup).
            pg_device_data: dict[str, Any] = {
                "type": "parallel_group",
                "name": f"Parallel Group {group_name}",
                "group_name": group_name,
                "first_device_serial": first_serial,
                "member_count": device_count,
                "member_serials": [serial for serial, _ in group_devices],
                "sensors": group_sensors,
            }
            if link_down_members:
                # Error key -> all PG sensor entities go unavailable
                # (base_entity availability contract), exactly like the
                # link-down members themselves.
                pg_device_data["error"] = (
                    f"Local transport link down for member(s): "
                    f"{', '.join(sorted(link_down_members))}"
                )
            processed["devices"][group_device_id] = pg_device_data

            self._register_pg_device(group_device_id, group_name)

            _LOGGER.info(
                "LOCAL: Created parallel group %s with %d devices: %s sensors",
                group_name,
                device_count,
                len(group_sensors),
            )

    async def _attach_local_transports_to_station(self) -> None:
        """Attach local transports to HTTP-discovered station devices.

        This method enables hybrid mode by connecting local transports
        (Modbus TCP, WiFi Dongle, or Modbus Serial) to devices discovered
        via HTTP API. After attachment, devices will use local transport
        for data fetching with automatic fallback to HTTP on failure.

        Network transports use the Station.attach_local_transports() API
        from pylxpweb; serial transports are attached integration-side
        because that API only dispatches modbus_tcp and wifi_dongle (#233).
        """
        from pylxpweb.transports.config import AttachResult, TransportType

        if self.station is None or not self._local_transport_configs:
            return

        _LOGGER.info(
            "Attaching %d local transport(s) to station devices",
            len(self._local_transport_configs),
        )

        # Convert stored config dicts to TransportConfig objects
        configs = _build_transport_configs(self._local_transport_configs)
        if not configs:
            _LOGGER.warning("No valid transport configs to attach")
            return

        # pylxpweb's Station.attach_local_transports() only dispatches
        # modbus_tcp and wifi_dongle ("Unknown transport type: modbus_serial"
        # otherwise), so USB/RS485 serial configs are attached here instead,
        # mirroring the LOCAL-only dispatch path (#233).
        serial_configs = [
            c for c in configs if c.transport_type == TransportType.MODBUS_SERIAL
        ]
        network_configs = [
            c for c in configs if c.transport_type != TransportType.MODBUS_SERIAL
        ]

        try:
            if network_configs:
                result = await self.station.attach_local_transports(network_configs)
            else:
                result = AttachResult()

            if serial_configs:
                await self._attach_serial_transports_to_station(serial_configs, result)

            _LOGGER.info(
                "Local transport attachment complete: %d matched, %d unmatched, %d failed",
                result.matched,
                result.unmatched,
                result.failed,
            )

            if result.unmatched_serials:
                _LOGGER.warning(
                    "No devices found for serials: %s",
                    ", ".join(result.unmatched_serials),
                )

            if result.failed_serials:
                _LOGGER.warning(
                    "Failed to connect transports for serials: %s",
                    ", ".join(result.failed_serials),
                )

            self._local_transports_attached = True

            # Track failed serials for bounded retry on later update cycles
            # (eg4-05l): a transient connect failure at boot — commonly the
            # dongle's single TCP slot still held by the previous HA session —
            # must not park the device on cloud data until a manual reload.
            self._failed_attach_serials = set(result.failed_serials)
            network_serials = {c.serial for c in network_configs}
            for serial in sorted(self._failed_attach_serials & network_serials):
                cfg = next(c for c in network_configs if c.serial == serial)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"transport_attach_failed_{serial}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="transport_attach_failed",
                    translation_placeholders={
                        "serial": str(serial),
                        "host": str(getattr(cfg, "host", "?")),
                    },
                )
            # Clear stale issues for serials that attached this time (a
            # reload after a degraded run must not leave ghost repairs).
            for cfg in configs:
                if cfg.serial not in self._failed_attach_serials:
                    ir.async_delete_issue(
                        self.hass, DOMAIN, f"transport_attach_failed_{cfg.serial}"
                    )
                    ir.async_delete_issue(
                        self.hass, DOMAIN, f"serial_attach_failed_{cfg.serial}"
                    )

            # Configure devices that received a transport.
            #
            # NOTE: We intentionally do NOT await inverter.refresh() here.
            # asyncio.wait_for() with Python 3.11 does NOT interrupt in-flight
            # pymodbus reads — it waits for the inner task to finish before
            # raising TimeoutError. On HA restart, the Waveshare gateway has
            # stale RS485 responses buffered from the previous session, causing
            # reads to fail for 3–5 minutes. A blocking refresh here hangs
            # async_config_entry_first_refresh() for that entire duration,
            # causing HA's setup timeout to fire and cancel entity setup.
            # Instead, a background task drains the buffer after setup returns.
            modbus_inverters = self._configure_attached_devices()
            if modbus_inverters:
                task = self.hass.async_create_task(
                    self._drain_modbus_buffers(modbus_inverters)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            # Log hybrid mode status
            if self.station.is_hybrid_mode:
                _LOGGER.info(
                    "Station is now in hybrid mode with %d local transport(s) attached",
                    result.matched,
                )

            self._warn_dongle_validation_disabled()

        except Exception as err:
            _LOGGER.error("Failed to attach local transports: %s", err)
            # Don't mark as attached so we can retry on next update
            self._local_transports_attached = False

    def _configure_attached_devices(self) -> list[Any]:
        """Propagate validation/cache/grid-type settings to attached devices.

        Idempotent — safe to re-run after an attach retry succeeds. Returns
        the modbus_tcp inverters; the CALLER decides whether to schedule a
        Waveshare buffer drain (only the initial attach does — re-draining a
        healthy, already-polling bus would disturb it).
        """
        modbus_inverters: list[Any] = []
        if self.station is None:
            return modbus_inverters
        validation_enabled = self._data_validation_enabled
        for inverter in self.station.all_inverters:
            transport = inverter.transport
            if transport is not None:
                inverter.validate_data = validation_enabled
                # Propagate split-phase config for per-leg power fallback
                grid_type = self._get_device_grid_type(inverter.serial_number)
                if isinstance(transport, _LOCAL_REGISTER_TRANSPORTS):
                    transport.split_phase = grid_type == GRID_TYPE_SPLIT_PHASE
                tt = getattr(transport, "transport_type", "modbus_tcp")
                self._align_inverter_cache_ttls(inverter, tt)
                if tt == "modbus_tcp":
                    modbus_inverters.append(inverter)

        # Propagate validation to MID devices.  set_max_system_power()
        # cannot be called here because inverter features have not been
        # detected yet — it runs later in _deferred_local_parameter_load().
        for mid in self.station.all_mid_devices:
            if mid.transport is not None:
                mid.validate_data = validation_enabled
        return modbus_inverters

    async def _maybe_retry_failed_attaches(self) -> None:
        """Retry local-transport attaches that failed at setup (eg4-05l).

        A transient connect failure at boot — commonly the dongle's single
        TCP slot still held by the previous HA session — used to park the
        device on cloud data until a manual reload. Retry the failed serials
        with a bounded interval; on success, configure the device, clear its
        Repairs issue, and resume local polling.
        """
        if not self._failed_attach_serials or self.station is None:
            return
        now = time.monotonic()
        if now - self._last_attach_retry < ATTACH_RETRY_INTERVAL_SECONDS:
            return
        self._last_attach_retry = now

        from pylxpweb.transports.config import AttachResult, TransportType

        retry_dicts = [
            c
            for c in self._local_transport_configs
            if str(c.get("serial")) in self._failed_attach_serials
        ]
        configs = _build_transport_configs(retry_dicts)
        if not configs:
            self._failed_attach_serials = set()
            return
        serial_configs = [
            c for c in configs if c.transport_type == TransportType.MODBUS_SERIAL
        ]
        network_configs = [
            c for c in configs if c.transport_type != TransportType.MODBUS_SERIAL
        ]
        _LOGGER.debug(
            "Retrying local transport attach for: %s",
            sorted(self._failed_attach_serials),
        )
        try:
            if network_configs:
                result = await self.station.attach_local_transports(network_configs)
            else:
                result = AttachResult()
            if serial_configs:
                await self._attach_serial_transports_to_station(serial_configs, result)
        except Exception as err:
            _LOGGER.debug("Local transport attach retry failed: %s", err)
            return

        still_failed = set(result.failed_serials) | set(result.unmatched_serials)
        recovered = {c.serial for c in configs} - still_failed
        if not recovered:
            return
        self._failed_attach_serials -= recovered
        for serial in sorted(recovered):
            ir.async_delete_issue(
                self.hass, DOMAIN, f"transport_attach_failed_{serial}"
            )
            ir.async_delete_issue(self.hass, DOMAIN, f"serial_attach_failed_{serial}")
            _LOGGER.info(
                "Local transport attached for %s after retry — resuming local polling",
                serial,
            )
        modbus_inverters = self._configure_attached_devices()
        # A freshly-recovered Modbus transport needs the same Waveshare
        # stale-buffer drain the initial attach schedules (review MEDIUM) —
        # but ONLY for the recovered serials; re-draining a healthy,
        # already-polling bus would disturb it. The drain and the param
        # reload below share the bus, so they run in ONE ordered task.
        recovered_modbus = [
            inv for inv in modbus_inverters if str(inv.serial_number) in recovered
        ]
        task = self.hass.async_create_task(
            self._finish_attach_recovery(recovered_modbus, sorted(recovered))
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._remove_task_from_set)
        task.add_done_callback(self._log_task_exception)

    async def _finish_attach_recovery(
        self, recovered_modbus: list[Any], recovered_serials: list[str]
    ) -> None:
        """Drain recovered Modbus buffers, then reload parameters via transport.

        The parameter caches for recovered serials were cloud-populated
        (kW-scaled) while the transport was down; once the transport is
        attached, ``_params_are_local_raw()`` treats the cache as raw, so the
        stale kW values would display ÷10 (12 kW as 1.2) until the next
        scheduled refresh (codex r2 MEDIUM). Reloading through the transport
        replaces them with raw register values within seconds. Runs in the
        background after the Waveshare drain so the two never interleave on
        the same bus.
        """
        if recovered_modbus:
            await self._drain_modbus_buffers(recovered_modbus)
        for serial in recovered_serials:
            # Pre-blank BOTH caches before the reload: pylxpweb swallows
            # parameter-read failures inside refresh() and returns with the
            # old (cloud-kW) dict intact, so success must be proven by
            # repopulation — the absence of an exception proves nothing
            # (codex r4). Unknown beats wrong-by-10x in the meantime; a
            # successful transport read repopulates raw values seconds later,
            # and a failed one self-heals at the next parameter refresh.
            inverter = self.get_inverter_object(serial)
            if inverter is not None:
                inverter.parameters = None
            if self.data and serial in self.data.get("parameters", {}):
                self.data["parameters"][serial] = {}
            try:
                await self._refresh_device_parameters(serial)
            except Exception as err:
                _LOGGER.warning(
                    "Parameter reload after attach recovery failed for %s: %s",
                    serial,
                    err,
                )

    def _sync_transport_link_state(self, processed: dict[str, Any] | None) -> None:
        """Sync Repairs issues and device error keys with transport link state.

        Called each update cycle from BOTH paths (eg4-57g):

        - LOCAL passes the processed data dict — there is no cloud to fall
          back to, so a link-down device gets an ``"error"`` key and its
          entities go unavailable instead of frozen-fresh (base_entity
          ``available`` checks for the key).
        - HYBRID passes ``None`` — link-down devices keep serving
          cloud-fallback data, so only the Repairs issues are synced.

        Error-key scope (deliberate): the key is honored by MEASUREMENT
        entities — EG4BaseSensor, EG4BaseBatterySensor, and
        EG4BatteryBankEntity — because frozen measurements are the bug.
        Control-entity availability (numbers, switches, selects, update
        entities) is intentionally unchanged: those are setpoints, not
        live readings, and this matches the never-attached degraded
        precedent (transport_attach_failed devices also keep their
        controls).  Parallel groups whose members are error-marked get
        error-marked too in _process_local_parallel_groups, which runs
        after this method.

        One-shot semantics: the issue is created once per down transition
        (tracked in ``_link_down_notified``) and deleted on recovery.  The
        healthy-path delete is an idempotent registry no-op, which also
        clears stale issues left behind by a restart mid-outage.
        """
        devices: dict[str, Any] = {}
        if self.station is not None:
            # HYBRID: the station owns all devices (caches mirror it).
            for inv in self.station.all_inverters:
                devices[str(inv.serial_number)] = inv
            for mid in self.station.all_mid_devices:
                devices[str(mid.serial_number)] = mid
        else:
            # LOCAL: devices live in the coordinator caches.
            devices.update(self._inverter_cache)
            devices.update(self._mid_device_cache)

        for serial, device in devices.items():
            transport = getattr(device, "transport", None)
            if transport is None:
                continue
            if is_transport_link_down(device):
                if processed is not None:
                    device_data = processed.get("devices", {}).get(serial)
                    if device_data is not None:
                        device_data["error"] = "Local transport link down"
                if serial in self._link_down_notified:
                    continue
                self._link_down_notified.add(serial)
                host = getattr(transport, "host", None) or getattr(
                    transport, "port", "?"
                )
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"transport_link_down_{serial}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="transport_link_down",
                    translation_placeholders={
                        "serial": str(serial),
                        "host": str(host),
                    },
                )
            else:
                if serial in self._link_down_notified:
                    self._link_down_notified.discard(serial)
                    _LOGGER.info(
                        "Local transport link restored for %s — clearing Repairs issue",
                        serial,
                    )
                ir.async_delete_issue(
                    self.hass, DOMAIN, f"transport_link_down_{serial}"
                )

    def _error_mark_stale_parallel_groups(self, processed: dict[str, Any]) -> None:
        """Error-mark carried-forward parallel groups on a full-outage cycle.

        On a full LOCAL outage the ``successful_devices == 0`` branch raises
        UpdateFailed BEFORE ``_process_local_parallel_groups()`` runs, so
        the carried-forward PG entries never get the partial-path marking —
        their sensors would keep passing entity availability and serve the
        stale aggregate while the coordinator wrapper suppresses the first
        UpdateFailed cycles.  Apply the same rule the partial path uses: a
        group is tainted when any of its members — or the GridBOSS CT
        contributor — is error-marked (link-down).  A transient full outage
        with no link-down marks leaves the groups alone, matching the
        member entities (which also stay available on cached values then).
        The carried ``parallel_group_last_polled`` stamp is left untouched
        (no fresh-poll claim is ever made on this path).

        DEPENDENCY: like the device-level marks from
        ``_sync_transport_link_state``, this mark becomes visible through
        the coordinator's RETAINED data only because the carry-forward in
        ``_async_update_local_data`` shares dict references with
        ``self.data`` (``processed["devices"].update(self.data...)``).
        If that carry-forward ever becomes a deep copy, both marks break
        together — the suppressed-failure window would silently serve
        stale data as available again.
        """
        devices: dict[str, Any] = processed.get("devices", {})
        error_serials = {
            serial
            for serial, device_data in devices.items()
            if device_data.get("type") in ("inverter", "gridboss")
            and "error" in device_data
        }
        if not error_serials:
            return
        gridboss_down = [
            serial
            for serial in error_serials
            if devices[serial].get("type") == "gridboss"
        ]
        for device_data in devices.values():
            if device_data.get("type") != "parallel_group" or "error" in device_data:
                continue
            members = device_data.get("member_serials") or []
            stale = set(members) & error_serials
            # GridBOSS CTs contribute to every group (partial-path parity).
            stale.update(gridboss_down)
            if stale:
                device_data["error"] = (
                    f"Local transport link down for member(s): "
                    f"{', '.join(sorted(stale))}"
                )

    async def _attach_serial_transports_to_station(
        self, configs: list[Any], result: Any
    ) -> None:
        """Attach Modbus serial (USB/RS485) transports to station devices.

        pylxpweb's Station.attach_local_transports() only dispatches
        modbus_tcp and wifi_dongle configs, so serial transports are
        created and attached here with the same factory the LOCAL-only
        path uses, mirroring the pylxpweb attach semantics (#233).

        Args:
            configs: MODBUS_SERIAL TransportConfig objects.
            result: AttachResult updated in place with matched/unmatched/
                failed counts so the caller's summary logging stays accurate.
        """
        from pylxpweb.transports import create_transport

        assert self.station is not None
        device_lookup: dict[str, Any] = {
            inv.serial_number: inv for inv in self.station.all_inverters
        }
        for mid in self.station.all_mid_devices:
            device_lookup[mid.serial_number] = mid

        for config in configs:
            device = device_lookup.get(config.serial)
            if device is None:
                _LOGGER.warning(
                    "No device found with serial %s in station %s",
                    config.serial,
                    self.station.id,
                )
                result.unmatched += 1
                result.unmatched_serials.append(config.serial)
                continue

            try:
                transport = create_transport(
                    "serial",
                    port=config.serial_port,
                    serial=config.serial,
                    baudrate=config.serial_baudrate,
                    parity=config.serial_parity,
                    stopbits=config.serial_stopbits,
                    unit_id=config.unit_id,
                    timeout=DEFAULT_MODBUS_TIMEOUT,
                    inverter_family=config.inverter_family,
                )
                await transport.connect()
                device._transport = transport
                result.matched += 1

                # Tighten cache TTLs for local transport speed (inverters only,
                # matching Station.attach_local_transports() semantics)
                if isinstance(device, BaseInverter):
                    device.set_transport_cache_ttls()

                _LOGGER.info(
                    "Attached modbus_serial transport to %s (%s)",
                    config.serial,
                    config.serial_port,
                )
            except Exception as err:
                _LOGGER.error(
                    "Failed to attach serial transport to device %s: %s",
                    config.serial,
                    err,
                )
                result.failed += 1
                result.failed_serials.append(config.serial)
                # Surface the degradation: the device silently falls back to
                # cloud-only until the next reload, which is exactly the class
                # of quiet failure #233 was filed about. Issue id includes the
                # serial so HA de-duplicates repeat attach failures per device.
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"serial_attach_failed_{config.serial}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="serial_attach_failed",
                    translation_placeholders={
                        "serial": str(config.serial),
                        "serial_port": str(config.serial_port),
                    },
                )

    async def _drain_modbus_buffers(self, inverters: list[Any]) -> None:
        """Background task: drain stale Waveshare RS485 buffer after HA restart.

        On restart, the Waveshare RS485-to-Ethernet gateway may have buffered
        stale responses from the previous HA session. These stale responses
        arrive at pymodbus as mismatched TID/function-code errors, causing
        read failures until the buffer is consumed.

        asyncio.wait_for() does NOT interrupt in-flight pymodbus reads in
        Python 3.11, so this cannot block setup. Instead, it runs as a
        background task that drains the buffer after setup returns — reads
        fail quickly via pymodbus's own per-read timeout, consuming one
        stale response per attempt until the buffer is empty.

        The per-read timeout * retries * register groups determines the
        maximum drain time (typically <60 s for a Waveshare with a few
        stale frames). Failures are expected and ignored; the regular poll
        cycle will populate _transport_runtime once reads succeed.
        """
        await asyncio.sleep(2)  # Let setup and first static refresh complete
        for inverter in inverters:
            try:
                _LOGGER.debug(
                    "Draining Modbus buffer for %s after restart",
                    inverter.serial_number,
                )
                await inverter.refresh(force=True)
                _LOGGER.debug(
                    "Modbus buffer drained successfully for %s",
                    inverter.serial_number,
                )
            except Exception as err:
                _LOGGER.debug(
                    "Modbus buffer drain failed for %s (expected on restart): %s",
                    inverter.serial_number,
                    err,
                )

    def get_local_transport(self, serial: str | None = None) -> Any | None:
        """Get the Modbus or Dongle transport for local register operations.

        Args:
            serial: Optional device serial. Required for LOCAL/HYBRID modes
                    with multiple devices attached via local_transports config.

        Returns:
            ModbusTransport, DongleTransport, or None if using HTTP-only mode.
        """
        # Check for transport attached to Station device (HYBRID with local_transports)
        if serial and self.station:
            inverter = self.get_inverter_object(serial)
            transport = inverter.transport if inverter else None
            if transport:
                return transport

        # Check LOCAL mode inverter cache
        if serial and self.connection_type == CONNECTION_TYPE_LOCAL:
            inverter = self._inverter_cache.get(serial)
            transport = inverter.transport if inverter else None
            if transport:
                return transport

        # Check MID device cache (GridBOSS devices in LOCAL/HYBRID mode)
        if serial:
            mid_device = self._mid_device_cache.get(serial)
            transport = mid_device.transport if mid_device else None
            if transport:
                return transport

        # Deprecated single-device modes (MODBUS, DONGLE, old HYBRID format)
        if self._modbus_transport:
            return self._modbus_transport
        if self._dongle_transport:
            return self._dongle_transport
        return None

    def has_local_transport(self, serial: str | None = None) -> bool:
        """Check if local Modbus or Dongle transport is available for a device.

        Args:
            serial: Device serial to check. Required for accurate check in
                    LOCAL/HYBRID modes with multiple devices.

        Returns:
            True if local transport is available for the specified device.
        """
        if serial:
            return self.get_local_transport(serial) is not None
        # Fallback for no serial: check deprecated single-transport fields
        return self._modbus_transport is not None or self._dongle_transport is not None

    def has_configured_local_transport(self, serial: str) -> bool:
        """Whether a per-device local transport is CONFIGURED for this serial.

        Config-based and stable from setup, unlike ``has_local_transport()``
        which reflects the live attachment state. Setup-time gates that must
        not flip across the failed-attach-then-recover window (eg4-05l) use
        this: a configured HYBRID transport makes the parameter cache
        local-raw as soon as the attach succeeds, even if that happens after
        the entity platforms were set up.

        Args:
            serial: Device serial to check.

        Returns:
            True if CONF_LOCAL_TRANSPORTS contains an entry for the serial.
        """
        return any(c.get("serial") == serial for c in self._local_transport_configs)

    def is_local_only(self) -> bool:
        """Check if using local-only connection (Modbus, Dongle, or Local multi-device).

        Returns:
            True if Modbus, Dongle, or Local mode without HTTP fallback.
        """
        return self.connection_type in (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_LOCAL,
        )
