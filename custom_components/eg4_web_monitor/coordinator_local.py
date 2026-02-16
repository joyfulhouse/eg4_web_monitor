"""Local transport coordinator mixin for EG4 Web Monitor integration.

This mixin handles all local transport logic (Modbus TCP, WiFi Dongle,
Modbus Serial) including device discovery, data reading, parallel group
aggregation, and static entity creation.
"""

import asyncio
import logging
from typing import Any

from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import LuxpowerDeviceError

from .const import (
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
    GRID_TYPE_SINGLE_PHASE,
    GRID_TYPE_SPLIT_PHASE,
    GRID_TYPE_THREE_PHASE,
    INVERTER_FAMILY_DEFAULT_MODELS,
    MANUFACTURER,
    SPLIT_PHASE_ONLY_SENSORS,
    THREE_PHASE_ONLY_SENSORS,
)
from .coordinator_mixins import (
    _MixinBase,
    apply_gridboss_overlay,
    compute_total_inverter_power_kw,
)
from .coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    GRIDBOSS_SENSOR_KEYS,
    GRIDBOSS_SMART_PORT_POWER_KEYS,
    PARALLEL_GROUP_GRIDBOSS_KEYS,
    PARALLEL_GROUP_SENSOR_KEYS,
    _build_battery_bank_sensor_mapping,
    _build_energy_sensor_mapping,
    _build_gridboss_sensor_mapping,
    _build_individual_battery_mapping,
    _build_runtime_sensor_mapping,
    _build_transport_configs,
    _features_from_family,
    _get_transport_label,
    _parse_inverter_family,
    compute_bank_charge_rate,
    compute_parallel_group_charge_rate,
)

_LOGGER = logging.getLogger(__name__)

# Derived from energy balance arithmetic; small decreases are normal
# timing artifacts (not corruption).  Clamped to prevent HA
# total_increasing warnings.
_COMPUTED_ENERGY_KEYS = frozenset({"consumption", "consumption_lifetime"})


class LocalTransportMixin(_MixinBase):
    """Mixin handling local transport operations for the coordinator."""

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
                (21, 1),  # Function enable register (bit fields)
                (64, 16),  # Power settings + AC charge/discharge (64-79)
                (101, 2),  # Charge/discharge current limits (101-102)
                (105, 2),  # On-grid SOC cutoff (105-106)
                (110, 1),  # System function register (bit fields)
                (125, 1),  # Off-grid SOC cutoff (HOLD_SOC_LOW_LIMIT_EPS_DISCHG)
                (179, 1),  # Extended functions (FUNC_GRID_PEAK_SHAVING, etc.)
                (227, 1),  # System charge SOC limit (HOLD_SYSTEM_CHARGE_SOC_LIMIT)
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

    def _check_grid_type_mismatch(
        self,
        serial: str,
        model: str,
        config: dict[str, Any],
        live_features: dict[str, Any],
    ) -> None:
        """Detect mismatch between config grid_type and live feature detection.

        When the user selected a wrong grid_type during setup (e.g., single_phase
        for a three-phase inverter), static entity creation skips phase-specific
        sensors. This creates a Repairs issue telling the user to reconfigure.
        """
        config_grid_type = config.get("grid_type")
        if not config_grid_type:
            return

        live_three = live_features.get("supports_three_phase", False)
        live_split = live_features.get("supports_split_phase", False)

        # Derive what grid_type the live detection implies
        if live_three:
            detected_type = GRID_TYPE_THREE_PHASE
        elif live_split:
            detected_type = GRID_TYPE_SPLIT_PHASE
        else:
            detected_type = GRID_TYPE_SINGLE_PHASE

        if config_grid_type == detected_type:
            return

        # Count phase-specific sensors that are missing due to the mismatch
        phase_sensor_counts = {
            GRID_TYPE_THREE_PHASE: len(THREE_PHASE_ONLY_SENSORS),
            GRID_TYPE_SPLIT_PHASE: len(SPLIT_PHASE_ONLY_SENSORS),
        }
        skipped = phase_sensor_counts.get(detected_type, 0)

        _LOGGER.warning(
            "Grid type mismatch for %s (%s): config=%s, detected=%s. "
            "%d phase-specific sensors are missing. "
            "Reconfigure the integration with the correct grid type.",
            serial,
            model,
            config_grid_type,
            detected_type,
            skipped,
        )

        self._grid_type_mismatch_notified.add(serial)

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"grid_type_mismatch_{serial}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="grid_type_mismatch",
            translation_placeholders={
                "serial": serial,
                "model": model,
                "config_grid_type": config_grid_type,
                "detected_grid_type": detected_type,
                "skipped_count": str(skipped),
            },
        )

    def _check_missing_grid_type(
        self,
        serial: str,
        model: str,
        features: dict[str, Any],
    ) -> None:
        """Surface a Repairs issue when LXP device has no grid_type configured.

        LXP-EU defaults to three-phase but many residential users run
        single-phase. Without explicit grid_type, incorrect three-phase
        sensors are created.
        """
        if serial in self._grid_type_mismatch_notified:
            return
        family = features.get("inverter_family")
        if family != "LXP":
            return
        if not features.get("supports_three_phase", False):
            return

        self._grid_type_mismatch_notified.add(serial)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"grid_type_missing_{serial}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="grid_type_missing",
            translation_placeholders={"serial": serial, "model": model},
        )

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
        device_data: dict[str, Any] = {
            "type": "inverter",
            "model": model,
            "serial": serial,
            "firmware_version": firmware_version,
            "sensors": _build_runtime_sensor_mapping(inverter._transport_runtime),
            "batteries": {},
        }

        if energy_data := inverter._transport_energy:
            device_data["sensors"].update(_build_energy_sensor_mapping(energy_data))

        if battery_data := inverter._transport_battery:
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
        # EPS per-leg power (computed from total EPS + voltage ratio)
        device_data["sensors"]["eps_power_l1"] = inverter.eps_power_l1
        device_data["sensors"]["eps_power_l2"] = inverter.eps_power_l2

        transport = getattr(inverter, "_transport", None)
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

            if inverter._transport_runtime is None:
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

            runtime = inverter._transport_runtime
            _LOGGER.debug(
                "%s update complete - FW: %s, PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                transport_name,
                firmware_version,
                runtime.pv_total_power,
                runtime.battery_soc,
                runtime.grid_power,
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

    def _clamp_computed_energy(
        self,
        device_id: str,
        sensors: dict[str, Any],
    ) -> None:
        """Clamp computed energy values so they never decrease.

        Small decreases are normal timing artifacts from reading multiple
        registers at different instants.  Clamping prevents HA
        total_increasing state class warnings.
        """
        if not self.data:
            return
        prev_sensors = (
            self.data.get("devices", {}).get(device_id, {}).get("sensors", {})
        )
        if not prev_sensors:
            return

        for key in _COMPUTED_ENERGY_KEYS:
            prev = prev_sensors.get(key)
            curr = sensors.get(key)
            if prev is not None and curr is not None and curr < prev:
                _LOGGER.debug(
                    "Clamping %s for %s: %.1f -> %.1f (keeping %.1f)",
                    key,
                    device_id,
                    prev,
                    curr,
                    prev,
                )
                sensors[key] = prev

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

                transport = mid_device._transport
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

                transport = inverter._transport
                if transport and not transport.is_connected:
                    await transport.connect()

                # Use the per-cycle decision computed in _async_update_local_data
                # (or fall back to the direct check for the deprecated single-
                # device path which doesn't set _include_params_this_cycle).
                include_params = getattr(self, "_include_params_this_cycle", False)
                await inverter.refresh(include_parameters=include_params)

                features: dict[str, Any] = {}
                if include_params and hasattr(inverter, "detect_features"):
                    try:
                        await inverter.detect_features()
                        features = self._extract_inverter_features(inverter)
                        _LOGGER.debug(
                            "LOCAL: Detected features for %s: family=%s, "
                            "split_phase=%s, three_phase=%s",
                            serial,
                            features.get("inverter_family"),
                            features.get("supports_split_phase"),
                            features.get("supports_three_phase"),
                        )
                    except Exception as e:
                        _LOGGER.warning(
                            "LOCAL: Could not detect features for %s: %s",
                            serial,
                            e,
                        )

                # Check for grid_type mismatch between config and live detection
                if features and serial not in self._grid_type_mismatch_notified:
                    if config.get("grid_type") is None:
                        self._check_missing_grid_type(serial, model, features)
                    else:
                        self._check_grid_type_mismatch(serial, model, config, features)

                if serial not in self._firmware_cache:
                    fw = "Unknown"
                    transport = inverter._transport
                    read_fw = (
                        getattr(transport, "read_firmware_version", None)
                        if transport
                        else None
                    )
                    if read_fw is not None:
                        fw = await read_fw() or "Unknown"
                    self._firmware_cache[serial] = fw
                firmware_version = self._firmware_cache[serial]

                runtime_data = inverter._transport_runtime
                energy_data = inverter._transport_energy

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

                battery_data = inverter._transport_battery
                if battery_data:
                    device_data["sensors"].update(
                        _build_battery_bank_sensor_mapping(battery_data)
                    )
                    # Compute battery bank charge/discharge rate from merged sensor data
                    compute_bank_charge_rate(device_data["sensors"])

                    if hasattr(battery_data, "batteries") and battery_data.batteries:
                        for batt in battery_data.batteries:
                            # Skip batteries with no CAN bus data (Modbus
                            # exception on 5002+ registers).  BMS aggregate
                            # data (regs 80-112) is always reliable via
                            # battery_bank sensors.
                            if batt.voltage is None and batt.soc is None:
                                continue
                            battery_key = f"{serial}-{batt.battery_index + 1:02d}"
                            device_data["batteries"][battery_key] = (
                                _build_individual_battery_mapping(batt)
                            )
                        _LOGGER.debug(
                            "LOCAL: Added %d individual batteries for %s",
                            len(device_data["batteries"]),
                            serial,
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
                # EPS per-leg power (computed from total EPS + voltage ratio)
                sensors["eps_power_l1"] = inverter.eps_power_l1
                sensors["eps_power_l2"] = inverter.eps_power_l2

                # Add last_polled timestamp so users can see when data was last fetched
                # (not just when it last changed)
                sensors["last_polled"] = dt_util.utcnow()

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

                self._clamp_computed_energy(serial, sensors)

                processed["devices"][serial] = device_data
                device_availability[serial] = True

                if include_params:
                    transport = inverter._transport
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
                    "LOCAL: Updated %s (%s) - FW: %s, PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                    serial,
                    transport_type,
                    firmware_version,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                    runtime_data.grid_power,
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
            # Build serial→config lookup for grid_type mismatch checks
            config_by_serial: dict[str, dict[str, Any]] = {
                c.get("serial", ""): c for c in self._local_transport_configs
            }

            loaded = 0
            for serial, inverter in self._inverter_cache.items():
                try:
                    # force=False: reuse cached runtime/energy/battery from
                    # the poll cycle, only fetch parameters (holding registers)
                    await inverter.refresh(force=False, include_parameters=True)
                    if hasattr(inverter, "detect_features"):
                        await inverter.detect_features()
                        # Check grid_type mismatch on first feature detection
                        if serial not in self._grid_type_mismatch_notified:
                            features = self._extract_inverter_features(inverter)
                            config = config_by_serial.get(serial, {})
                            model = config.get("model", "")
                            if features:
                                if config.get("grid_type") is None:
                                    self._check_missing_grid_type(
                                        serial, model, features
                                    )
                                else:
                                    self._check_grid_type_mismatch(
                                        serial, model, config, features
                                    )
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
                # Exclude smart port power keys from static creation — they are
                # added dynamically by _filter_unused_smart_port_sensors() based
                # on actual port status so only active ports get entities.
                sensor_keys = GRIDBOSS_SENSOR_KEYS - GRIDBOSS_SMART_PORT_POWER_KEYS
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
            # even before Modbus-based feature detection runs.
            family_str = config.get("inverter_family")
            dtc = config.get("device_type_code")
            grid_type = config.get("grid_type")
            features = (
                _features_from_family(family_str, dtc, grid_type=grid_type)
                if not is_gridboss
                else {}
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

            # Aggregate battery_bank_current from member inverters
            total_battery_current = 0.0
            has_battery_current = False
            for _, dd in group_devices:
                bat_current = dd.get("sensors", {}).get("battery_bank_current")
                if bat_current is not None:
                    total_battery_current += float(bat_current)
                    has_battery_current = True
            if has_battery_current:
                group_sensors["parallel_battery_current"] = total_battery_current

            # Sum battery_bank_count from all member devices
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
                gb_sensors = device_data.get("sensors", {})
                apply_gridboss_overlay(group_sensors, gb_sensors, group_name)

                # Recompute consumption_power from energy balance using the
                # MID device's authoritative grid_power (from CTs).  The
                # inverters' own grid registers are unreliable in MID systems,
                # so their energy-balance consumption_power (already summed
                # above) is garbage.  We replace it here.
                #
                # Formula: consumption = pv + battery_net + grid_power
                #   pv_total_power  — from inverters (they know their own PV)
                #   battery_net     — negative of parallel_battery_power
                #     (parallel_battery_power: positive=charging, so negate for consumption)
                #   grid_power      — from MID overlay (positive = importing)
                pv = float(group_sensors.get("pv_total_power", 0.0))
                bat_power = float(group_sensors.get("parallel_battery_power", 0.0))
                # grid_power already replaced by overlay above
                grid = float(group_sensors.get("grid_power", 0.0))
                battery_net = -bat_power
                consumption = max(0.0, pv + battery_net + grid)
                group_sensors["consumption_power"] = consumption
                _LOGGER.debug(
                    "LOCAL: Parallel group %s: consumption_power = "
                    "pv(%s) + bat_net(%s) + grid(%s) = %s",
                    group_name,
                    pv,
                    battery_net,
                    grid,
                    consumption,
                )

                # Add AC couple power to pv_total_power for smart ports in AC couple mode
                # Smart port status 2 = AC Couple (solar inverter connected)
                # This is configurable via options (default: disabled)
                include_ac_couple = self.entry.options.get(
                    CONF_INCLUDE_AC_COUPLE_PV,
                    self.entry.data.get(CONF_INCLUDE_AC_COUPLE_PV, False),
                )
                if include_ac_couple:
                    ac_couple_total = 0.0
                    for port_num in range(1, 5):  # Ports 1-4
                        status_key = f"smart_port{port_num}_status"
                        status = gb_sensors.get(status_key)
                        if status == 2:  # AC Couple mode
                            l1_power = (
                                gb_sensors.get(f"ac_couple{port_num}_power_l1") or 0
                            )
                            l2_power = (
                                gb_sensors.get(f"ac_couple{port_num}_power_l2") or 0
                            )
                            port_power = float(l1_power) + float(l2_power)
                            ac_couple_total += port_power
                            _LOGGER.debug(
                                "LOCAL: Parallel group %s: AC couple port %d power=%sW",
                                group_name,
                                port_num,
                                port_power,
                            )

                    if ac_couple_total > 0:
                        current_pv = group_sensors.get("pv_total_power", 0.0)
                        group_sensors["pv_total_power"] = current_pv + ac_couple_total
                        _LOGGER.debug(
                            "LOCAL: Parallel group %s: pv_total_power=%sW "
                            "(inverters=%sW + AC couple=%sW)",
                            group_name,
                            group_sensors["pv_total_power"],
                            current_pv,
                            ac_couple_total,
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

            # Clamp computed energy values before storing the parallel group.
            group_device_id = f"parallel_group_{group_name.lower()}"
            self._clamp_computed_energy(group_device_id, group_sensors)

            group_sensors["parallel_group_last_polled"] = dt_util.utcnow()

            # Create groups even with 1 inverter if parallel_number > 0,
            # since this indicates the inverter is configured for parallel
            # operation (e.g., single inverter + GridBOSS setup).
            processed["devices"][group_device_id] = {
                "type": "parallel_group",
                "name": f"Parallel Group {group_name}",
                "group_name": group_name,
                "first_device_serial": first_serial,
                "member_count": device_count,
                "member_serials": [serial for serial, _ in group_devices],
                "sensors": group_sensors,
            }

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
        (Modbus TCP or WiFi Dongle) to devices discovered via HTTP API.
        After attachment, devices will use local transport for data fetching
        with automatic fallback to HTTP on failure.

        Uses the new Station.attach_local_transports() API from pylxpweb.
        """
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

        try:
            result = await self.station.attach_local_transports(configs)

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

            # Configure each inverter with a local transport:
            # 1. Propagate data validation (prevents GridBOSS data spikes)
            # 2. Align cache TTLs with coordinator's user-configured intervals
            # 3. Force initial transport read so _transport_runtime is
            #    populated on the first _process_station_data() call
            validation_enabled = self._data_validation_enabled
            for inverter in self.station.all_inverters:
                transport = getattr(inverter, "_transport", None)
                if transport is not None:
                    inverter.validate_data = validation_enabled
                    tt = getattr(transport, "transport_type", "modbus_tcp")
                    self._align_inverter_cache_ttls(inverter, tt)
                    try:
                        await inverter.refresh(force=True)
                    except Exception:
                        _LOGGER.warning(
                            "HYBRID: forced transport read failed for %s",
                            inverter.serial_number,
                        )

            # Propagate validation to MID devices.  set_max_system_power()
            # cannot be called here because inverter features have not been
            # detected yet — it runs later in _deferred_local_parameter_load().
            for mid in self.station.all_mid_devices:
                if getattr(mid, "_transport", None) is not None:
                    mid.validate_data = validation_enabled

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
            if inverter and hasattr(inverter, "_transport") and inverter._transport:
                return inverter._transport

        # Check LOCAL mode inverter cache
        if serial and self.connection_type == CONNECTION_TYPE_LOCAL:
            inverter = self._inverter_cache.get(serial)
            if inverter and hasattr(inverter, "_transport"):
                return inverter._transport

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
