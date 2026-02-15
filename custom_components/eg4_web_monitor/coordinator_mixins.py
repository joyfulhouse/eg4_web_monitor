"""Coordinator mixins for EG4 Web Monitor integration.

This module provides mixins that separate coordinator responsibilities into
logical units for better maintainability and testability.

Mypy Note: Mixins access attributes defined in the main coordinator class.
The CoordinatorProtocol documents the expected interface, but mypy cannot
verify this at the mixin level. Runtime type safety is guaranteed by the
final coordinator class inheriting all mixins together.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from pylxpweb import LuxpowerClient
    from pylxpweb.devices import Battery, Station
    from pylxpweb.devices.inverters.base import BaseInverter
    from pylxpweb.transports import (
        DongleTransport,
        ModbusSerialTransport,
        ModbusTransport,
    )

from pylxpweb.devices.inverters import InverterFamily

from .const import CONF_LOCAL_TRANSPORTS, DOMAIN, MANUFACTURER
from .coordinator_mappings import (
    _apply_grid_type_override,
    _build_battery_bank_sensor_mapping,
    _energy_balance,
    _safe_float,
    _write_rounded_rates,
    compute_bank_charge_rates,
)
from .utils import clean_battery_display_name

_LOGGER = logging.getLogger(__name__)

# Track devices that have already been warned about invalid smart port status
# to avoid log spam on every poll cycle
_warned_smart_port_devices: set[str] = set()

# Map raw smart port status integers to human-readable enum labels
_SMART_PORT_STATUS_LABELS: dict[int, str] = {
    0: "unused",
    1: "smart_load",
    2: "ac_couple",
}

# GridBOSS sensor → parallel group sensor overlay mapping.
# GridBOSS CTs are the authoritative measurement point for grid power
# and energy — inverter registers are internal estimates that diverge
# from actual panel readings.  Used by both HTTP and LOCAL paths to
# ensure consistent parallel group values regardless of connection mode.
_GRIDBOSS_PG_OVERLAY: dict[str, str] = {
    # Power sensors (real-time CT measurements)
    "grid_power": "grid_power",
    "grid_power_l1": "grid_power_l1",
    "grid_power_l2": "grid_power_l2",
    "load_power": "load_power",
    "load_power_l1": "load_power_l1",
    "load_power_l2": "load_power_l2",
    # Voltage sensors (MID device has authoritative grid voltage readings;
    # inverter regs 193-194 return 0 on 18kPV/FlexBOSS firmware)
    "grid_voltage_l1": "grid_voltage_l1",
    "grid_voltage_l2": "grid_voltage_l2",
    # Energy sensors (accumulated CT totals)
    "grid_export_today": "grid_export",
    "grid_export_total": "grid_export_lifetime",
    "grid_import_today": "grid_import",
    "grid_import_total": "grid_import_lifetime",
    # Note: consumption energy (ups + load) is computed separately after
    # the overlay loop because it requires summing two MID sources that
    # the simple key-to-key overlay cannot handle.
}


def apply_gridboss_overlay(
    pg_sensors: dict[str, Any],
    gb_sensors: dict[str, Any],
    group_name: str,
) -> None:
    """Overlay GridBOSS CT measurements onto parallel group sensors.

    GridBOSS CTs directly measure grid and load current at the main panel,
    providing authoritative values for grid power/energy and consumption.
    Inverter-derived values are estimates and can diverge significantly.

    Called from both the HTTP path (hybrid mode) and the LOCAL path to
    ensure consistent parallel group data regardless of connection mode.

    Args:
        pg_sensors: Parallel group sensor dict (modified in place).
        gb_sensors: GridBOSS/MID device sensor dict.
        group_name: Parallel group name for debug logging.
    """
    for gb_key, pg_key in _GRIDBOSS_PG_OVERLAY.items():
        gb_val = gb_sensors.get(gb_key)
        if gb_val is not None:
            pg_sensors[pg_key] = float(gb_val)
            _LOGGER.debug(
                "Parallel group %s: GridBOSS %s=%s -> %s",
                group_name,
                gb_key,
                gb_val,
                pg_key,
            )

    # Consumption energy = UPS (backup loads) + Load (non-backup loads).
    # UPS CTs measure inverter output; Load CTs measure direct-from-grid
    # loads that bypass the inverter.  Both contribute to total consumption.
    for period, pg_key in (("today", "consumption"), ("total", "consumption_lifetime")):
        ups = gb_sensors.get(f"ups_{period}")
        load = gb_sensors.get(f"load_{period}")
        if ups is not None or load is not None:
            total = float(ups or 0) + float(load or 0)
            pg_sensors[pg_key] = total
            _LOGGER.debug(
                "Parallel group %s: consumption %s = ups(%s) + load(%s) = %s",
                group_name,
                period,
                ups,
                load,
                total,
            )


if TYPE_CHECKING:

    class _MixinBase:
        """Type stubs for coordinator attributes and cross-mixin methods.

        Provides mypy with the interface that mixins can access on ``self``.
        At runtime this is replaced by ``object`` so the MRO is unchanged.
        """

        # ── Coordinator public attributes ──
        # Declared as Any to avoid diamond-inheritance conflict with
        # DataUpdateCoordinator[dict[str, Any]].data in the final class.
        data: Any
        hass: HomeAssistant
        client: LuxpowerClient | None
        station: Station | None
        plant_id: str | None
        connection_type: str
        entry: ConfigEntry
        dst_sync_enabled: bool

        # ── Coordinator private attributes ──
        _inverter_cache: dict[str, BaseInverter]
        _mid_device_cache: dict[str, Any]
        _firmware_cache: dict[str, str]
        _background_tasks: set[asyncio.Task[Any]]
        _api_semaphore: asyncio.Semaphore
        _http_polling_interval: int
        _local_transport_configs: list[dict[str, Any]]
        _local_transports_attached: bool
        _local_parameters_loaded: bool
        _local_static_phase_done: bool
        _data_validation_enabled: bool
        _grid_type_mismatch_notified: set[str]
        _include_params_this_cycle: bool
        _last_available_state: bool
        _last_parameter_refresh: datetime | None
        _parameter_refresh_interval: timedelta
        _last_dst_sync: datetime | None
        _dst_sync_interval: timedelta
        _last_status_fetch: dict[str, float]
        _daily_api_offset: int
        _daily_api_ymd: tuple[int, int, int]
        _modbus_transport: ModbusTransport | ModbusSerialTransport | None
        _dongle_transport: DongleTransport | None
        _modbus_serial: str
        _modbus_model: str
        _dongle_serial: str
        _dongle_model: str
        _modbus_interval: int
        _dongle_interval: int
        _last_modbus_poll: float
        _last_dongle_poll: float
        _shutdown_listener_remove: Callable[[], None] | None
        _shutdown_listener_fired: bool
        _debounced_refresh: Any
        _device_info_cache: dict[str, DeviceInfo]
        _battery_device_info_cache: dict[str, DeviceInfo]
        _battery_bank_device_info_cache: dict[str, DeviceInfo]

        # ── DataUpdateCoordinator / coordinator.py methods ──
        def get_inverter_object(self, serial: str) -> BaseInverter | None: ...
        async def async_request_refresh(self) -> None: ...
        def _rebuild_inverter_cache(self) -> None: ...

        # ── DeviceProcessingMixin methods ──
        async def _process_inverter_object(
            self, inverter: BaseInverter
        ) -> dict[str, Any]: ...
        async def _process_parallel_group_object(
            self, group: Any
        ) -> dict[str, Any]: ...
        async def _process_mid_device_object(
            self, mid_device: Any
        ) -> dict[str, Any]: ...
        @staticmethod
        def _extract_inverter_features(
            inverter: BaseInverter,
        ) -> dict[str, Any]: ...
        def _extract_battery_from_object(self, battery: Battery) -> dict[str, Any]: ...
        @staticmethod
        def _filter_unused_smart_port_sensors(
            sensors: dict[str, Any], mid_device: Any
        ) -> None: ...
        @staticmethod
        def _calculate_gridboss_aggregates(
            sensors: dict[str, Any],
        ) -> None: ...

        # ── FirmwareUpdateMixin methods ──
        def _extract_firmware_update_info(
            self, device: BaseInverter
        ) -> dict[str, Any] | None: ...

        # ── ParameterManagementMixin methods ──
        def _should_refresh_parameters(self) -> bool: ...
        async def _hourly_parameter_refresh(self) -> None: ...
        async def _refresh_missing_parameters(
            self, inverter_serials: list[str], processed_data: dict[str, Any]
        ) -> None: ...

        # ── BackgroundTaskMixin methods ──
        def _remove_task_from_set(self, task: asyncio.Task[Any]) -> None: ...
        def _log_task_exception(self, task: asyncio.Task[Any]) -> None: ...

        # ── DSTSyncMixin methods ──
        def _should_sync_dst(self) -> bool: ...
        async def _perform_dst_sync(self) -> None: ...

        # ── Per-transport interval methods (coordinator.py) ──
        def _should_poll_transport(self, transport_type: str) -> bool: ...
        def _has_modbus_transport(self) -> bool: ...
        def _has_dongle_transport(self) -> bool: ...
        def _get_active_transport_intervals(self) -> list[int]: ...
        def _align_inverter_cache_ttls(
            self, inverter: Any, transport_type: str
        ) -> None: ...

        # ── LocalTransportMixin methods ──
        async def _attach_local_transports_to_station(self) -> None: ...

else:
    _MixinBase = object


# ===== Utility Functions =====


def _map_device_properties(device: Any, property_map: dict[str, str]) -> dict[str, Any]:
    """Map device properties to sensor keys using a property mapping dictionary.

    This is a generic utility that extracts properties from any device object
    (inverter, MID device, parallel group, battery) and maps them to sensor keys.

    Args:
        device: The device object to extract properties from
        property_map: Dictionary mapping property_name -> sensor_key

    Returns:
        Dictionary of {sensor_key: value} for all found properties with valid values
    """
    sensors: dict[str, Any] = {}

    for property_name, sensor_key in property_map.items():
        try:
            value = getattr(device, property_name, None)
        except (TypeError, ValueError, AttributeError) as exc:
            # Property getter may call float()/int() on None internal data
            # when the device object hasn't been fully populated yet.
            # Note: hasattr() is not safe here — it only catches AttributeError,
            # so a property raising TypeError (e.g. float(None)) propagates.
            _LOGGER.debug(
                "Property %s on %s raised %s: %s",
                property_name,
                getattr(device, "serial_number", "unknown"),
                type(exc).__name__,
                exc,
            )
            continue
        # Skip None values and empty strings (which indicate no data)
        if value is not None and value != "":
            sensors[sensor_key] = value

    return sensors


def _safe_numeric(value: Any) -> float:
    """Safely convert value to numeric, defaulting to 0.

    Args:
        value: Any value to convert to float

    Returns:
        Float value or 0.0 if conversion fails
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class DeviceProcessingMixin(_MixinBase):
    """Mixin for device data processing logic.

    Handles processing of inverters, batteries, MID devices, and parallel groups.
    Provides static methods for property mapping.
    """

    def _get_device_grid_type(self, serial: str) -> str | None:
        """Look up user-selected grid type for a device from config entry.

        Searches the local_transports list in config_entry.data for a
        device with the matching serial number and returns its grid_type.

        Args:
            serial: Device serial number.

        Returns:
            Grid type string or None if not found (cloud-only or legacy config).
        """
        local_transports: list[dict[str, Any]] = self.entry.data.get(
            CONF_LOCAL_TRANSPORTS, []
        )
        for transport in local_transports:
            if transport.get("serial") == serial:
                return transport.get("grid_type")
        return None

    async def _process_inverter_object(
        self, inverter: "BaseInverter"
    ) -> dict[str, Any]:
        """Process inverter device data from device object using pylxpweb 0.3.3+ properties.

        pylxpweb 0.3.3+ exposes all data through properties - never access .runtime, .energy,
        or .battery_bank directly. All scaling is handled by the library.

        Note: GridBOSS/MID devices are processed separately via _process_mid_device_object()
        and accessed through parallel_group.mid_device, not as inverters.

        Args:
            inverter: BaseInverter object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        # Refresh inverter to load firmware version
        await inverter.refresh()

        # Detect inverter features for capability-based sensor filtering (pylxpweb 0.4.0+)
        features: dict[str, Any] = {}
        try:
            if hasattr(inverter, "detect_features"):
                await inverter.detect_features()
                features = self._extract_inverter_features(inverter)
                _LOGGER.debug(
                    "Detected features for inverter %s: family=%s, split_phase=%s, "
                    "three_phase=%s, parallel=%s",
                    inverter.serial_number,
                    features.get("inverter_family"),
                    features.get("supports_split_phase"),
                    features.get("supports_three_phase"),
                    features.get("supports_parallel"),
                )
        except Exception as e:
            _LOGGER.debug(
                "Could not detect features for inverter %s: %s",
                inverter.serial_number,
                e,
            )

        # Override phase features if user specified grid type in config
        grid_type = self._get_device_grid_type(inverter.serial_number)
        if grid_type and features:
            _apply_grid_type_override(features, grid_type)

        # Get model and firmware from properties
        model = getattr(inverter, "model", "Unknown")
        firmware_version = getattr(inverter, "firmware_version", "1.0.0")

        # Check for firmware updates (pylxpweb 0.3.7+)
        firmware_update_info = None
        try:
            if hasattr(inverter, "check_firmware_updates"):
                await inverter.check_firmware_updates()
                if hasattr(inverter, "get_firmware_update_progress"):
                    await inverter.get_firmware_update_progress()
                firmware_update_info = self._extract_firmware_update_info(inverter)
        except Exception as e:
            _LOGGER.debug(
                "Could not check firmware updates for %s: %s",
                inverter.serial_number,
                e,
            )

        processed: dict[str, Any] = {
            "serial": inverter.serial_number,
            "type": "inverter",
            "model": model,
            "firmware_version": firmware_version,
            "firmware_update_info": firmware_update_info,
            "features": features,  # Device capabilities for sensor filtering
            "sensors": {},
            "binary_sensors": {},
            "batteries": {},
        }

        # Check if inverter has runtime data
        if not inverter.has_data:
            # Log detailed diagnostics to help debug missing sensor issues
            runtime_attr = getattr(inverter, "_runtime", "NOT_FOUND")
            energy_attr = getattr(inverter, "_energy", "NOT_FOUND")
            _LOGGER.warning(
                "Inverter %s (%s) has no runtime data available (has_data=False). "
                "Runtime sensors will not be created. "
                "Debug: _runtime=%s, _energy=%s. "
                "This may indicate an API issue or unsupported device model.",
                inverter.serial_number,
                model,
                "None" if runtime_attr is None else "present",
                "None" if energy_attr is None else "present",
            )
            # Still add diagnostic sensors even without runtime data
            processed["sensors"]["firmware_version"] = firmware_version
            processed["sensors"]["has_data"] = False
            if features:
                if "inverter_family" in features:
                    processed["sensors"]["inverter_family"] = features[
                        "inverter_family"
                    ]
                if "device_type_code" in features:
                    processed["sensors"]["device_type_code"] = features[
                        "device_type_code"
                    ]
                if "grid_type" in features:
                    processed["sensors"]["grid_type"] = features["grid_type"]
            return processed

        # Map inverter properties to sensor keys
        property_map = self._get_inverter_property_map()
        processed["sensors"] = _map_device_properties(inverter, property_map)

        # Override consumption with energy balance when transport data is present.
        # pylxpweb's energy_today_usage/energy_lifetime_usage properties read from
        # load_energy registers (Erec = AC charge from grid) when transport data
        # is attached.  The cloud API's totalUsage is server-computed and correct,
        # but there is no equivalent Modbus register.  Energy balance mirrors how
        # consumption_power is already computed in pylxpweb for instantaneous power.
        #
        # Note: GridBOSS uses a different aggregation strategy — CT summation
        # (L1 + L2) via _safe_sum() in MIDRuntimePropertiesMixin, not energy
        # balance.  See pylxpweb _mid_runtime_properties.py for details.
        if getattr(inverter, "_transport", None) is not None:
            sensors = processed["sensors"]
            sensors["consumption"] = _energy_balance(
                sensors.get("yield"),
                sensors.get("discharging"),
                sensors.get("grid_import"),
                sensors.get("charging"),
                sensors.get("grid_export"),
            )
            sensors["consumption_lifetime"] = _energy_balance(
                sensors.get("yield_lifetime"),
                sensors.get("discharging_lifetime"),
                sensors.get("grid_import_lifetime"),
                sensors.get("charging_lifetime"),
                sensors.get("grid_export_lifetime"),
            )

        # Overlay transport-exclusive sensors (Modbus-only, not in cloud API).
        # When a local transport is attached in hybrid mode, _transport_runtime
        # contains real-time Modbus register data for sensors the cloud API
        # does not provide (e.g. bt_temperature reg 108, grid current regs
        # 18/190/191, battery current reg 4).
        transport_runtime = getattr(inverter, "_transport_runtime", None)
        if transport_runtime is not None:
            sensors = processed["sensors"]
            _TRANSPORT_OVERLAY = (
                ("bt_temperature", "temperature_t1"),
                ("grid_current_l1", "inverter_rms_current_r"),
                ("grid_current_l2", "inverter_rms_current_s"),
                ("grid_current_l3", "inverter_rms_current_t"),
                ("battery_current", "battery_current"),
            )
            for sensor_key, runtime_attr in _TRANSPORT_OVERLAY:
                value = getattr(transport_runtime, runtime_attr, None)
                if value is not None:
                    sensors[sensor_key] = value
            if (val := getattr(inverter, "total_load_power", None)) is not None:
                sensors["total_load_power"] = val

        # Add firmware_version as diagnostic sensor
        processed["sensors"]["firmware_version"] = firmware_version

        # Add feature detection sensors for diagnostics
        if features:
            if "inverter_family" in features:
                processed["sensors"]["inverter_family"] = features["inverter_family"]
            if "device_type_code" in features:
                processed["sensors"]["device_type_code"] = features["device_type_code"]
            if "grid_type" in features:
                processed["sensors"]["grid_type"] = features["grid_type"]

        # Calculate net grid power
        if hasattr(inverter, "power_to_user") and hasattr(inverter, "power_to_grid"):
            power_to_user = _safe_numeric(inverter.power_to_user)
            power_to_grid = _safe_numeric(inverter.power_to_grid)
            processed["sensors"]["grid_power"] = power_to_user - power_to_grid

        # Note: load_power sensor removed - it was confusingly named as grid_import
        # Use consumption_power instead, which represents actual household consumption
        # calculated as: pv_total + grid_import - grid_export (clamped to >= 0)
        #
        # total_load_power is now computed in pylxpweb as alias for consumption_power

        # Add legacy ac_voltage sensor
        if hasattr(inverter, "eps_voltage_r"):
            processed["sensors"]["ac_voltage"] = inverter.eps_voltage_r

        # Binary sensors
        if hasattr(inverter, "is_lost"):
            processed["binary_sensors"]["is_lost"] = inverter.is_lost
        if hasattr(inverter, "is_using_generator"):
            processed["binary_sensors"]["is_using_generator"] = (
                inverter.is_using_generator
            )

        # Process battery bank aggregate data if available
        # Prefer transport battery data (local Modbus) over cloud battery_bank
        # In hybrid mode, _transport_battery is refreshed each cycle while
        # _battery_bank may be stale from initial cloud station load
        transport_battery = getattr(inverter, "_transport_battery", None)
        if transport_battery:
            _LOGGER.debug(
                "Battery bank for %s: using LOCAL transport data (hybrid/local mode)",
                inverter.serial_number,
            )
            try:
                battery_bank_sensors = _build_battery_bank_sensor_mapping(
                    transport_battery
                )
                processed["sensors"].update(battery_bank_sensors)
            except Exception as e:
                _LOGGER.warning(
                    "Error extracting transport battery bank data for inverter %s: %s",
                    inverter.serial_number,
                    e,
                )
        else:
            # Fall back to cloud battery_bank for cloud-only mode
            battery_bank = getattr(inverter, "_battery_bank", None)
            if battery_bank:
                _LOGGER.debug(
                    "Battery bank for %s: using CLOUD data (no local transport attached)",
                    inverter.serial_number,
                )
                try:
                    battery_bank_sensors = self._extract_battery_bank_from_object(
                        battery_bank
                    )
                    processed["sensors"].update(battery_bank_sensors)
                except Exception as e:
                    _LOGGER.warning(
                        "Error extracting battery bank data for inverter %s: %s",
                        inverter.serial_number,
                        e,
                    )
            else:
                _LOGGER.debug(
                    "Battery bank for %s: NO DATA (no transport or cloud battery_bank)",
                    inverter.serial_number,
                )

        # Compute battery bank charge/discharge rate percentages.
        # At this point sensors dict has battery_bank_current (from battery
        # bank data) and max_charge_current / max_discharge_current (from
        # _map_device_properties).
        compute_bank_charge_rates(processed["sensors"])

        # Fetch quick charge and battery backup status with 30s throttle
        # These are cloud API calls that should not run every update cycle
        _STATUS_FETCH_INTERVAL = 30  # seconds
        if not hasattr(self, "_last_status_fetch"):
            self._last_status_fetch: dict[str, float] = {}
        now = time.monotonic()
        serial = inverter.serial_number

        # Quick charge status
        qc_key = f"qc_{serial}"
        last_qc = self._last_status_fetch.get(qc_key, 0.0)
        if now - last_qc >= _STATUS_FETCH_INTERVAL:
            try:
                if hasattr(inverter, "get_quick_charge_status"):
                    quick_charge_active = await inverter.get_quick_charge_status()
                    processed["quick_charge_status"] = {
                        "hasUnclosedQuickChargeTask": quick_charge_active,
                    }
                    self._last_status_fetch[qc_key] = now
                    _LOGGER.debug(
                        "Quick charge status for %s: %s",
                        serial,
                        quick_charge_active,
                    )
            except Exception as e:
                self._last_status_fetch[qc_key] = now
                _LOGGER.debug(
                    "Could not fetch quick charge status for %s: %s",
                    serial,
                    e,
                )
        elif self.data and serial in self.data.get("devices", {}):
            prev = self.data["devices"][serial].get("quick_charge_status")
            if prev is not None:
                processed["quick_charge_status"] = prev

        # Battery backup (EPS) status
        # Skip cloud API call when local transport is attached — the parameter
        # data from local Modbus already provides FUNC_EPS_EN which the switch
        # entity uses as a fallback. The cloud remoteRead endpoint frequently
        # returns apiBlocked anyway since the dongle relay is often busy.
        has_local_transport = getattr(inverter, "_transport", None) is not None
        if not has_local_transport:
            bb_key = f"bb_{serial}"
            last_bb = self._last_status_fetch.get(bb_key, 0.0)
            if now - last_bb >= _STATUS_FETCH_INTERVAL:
                try:
                    if hasattr(inverter, "get_battery_backup_status"):
                        battery_backup_enabled = (
                            await inverter.get_battery_backup_status()
                        )
                        processed["battery_backup_status"] = {
                            "enabled": battery_backup_enabled,
                        }
                        self._last_status_fetch[bb_key] = now
                        _LOGGER.debug(
                            "Battery backup status for %s: %s",
                            serial,
                            battery_backup_enabled,
                        )
                except Exception as e:
                    self._last_status_fetch[bb_key] = now
                    _LOGGER.debug(
                        "Could not fetch battery backup status for %s: %s",
                        serial,
                        e,
                    )
            elif self.data and serial in self.data.get("devices", {}):
                prev = self.data["devices"][serial].get("battery_backup_status")
                if prev is not None:
                    processed["battery_backup_status"] = prev

        # Add last_polled timestamps so users can see when data was last fetched
        # (not just when it last changed)
        processed["sensors"]["last_polled"] = dt_util.utcnow()
        # Battery bank last_polled — only when battery bank data exists
        if any(k.startswith("battery_bank_") for k in processed["sensors"]):
            processed["sensors"]["battery_bank_last_polled"] = dt_util.utcnow()

        return processed

    @staticmethod
    def _get_inverter_property_map() -> dict[str, str]:
        """Get inverter property mapping dictionary.

        Returns:
            Dictionary mapping inverter property names to sensor keys
        """
        return {
            # Power sensors
            # Note: pylxpweb uses power_output property, but we map to output_power
            # for consistency with local mode (which uses output_power from Modbus)
            "power_output": "output_power",
            "pv_total_power": "pv_total_power",
            "pv1_power": "pv1_power",
            "pv2_power": "pv2_power",
            "pv3_power": "pv3_power",
            "battery_power": "battery_power",
            "battery_charge_power": "battery_charge_power",
            "battery_discharge_power": "battery_discharge_power",
            "consumption_power": "consumption_power",
            "inverter_power": "ac_power",
            "rectifier_power": "rectifier_power",
            "ac_couple_power": "ac_couple_power",
            "generator_power": "generator_power",
            "eps_power": "eps_power",
            "eps_power_l1": "eps_power_l1",
            "eps_power_l2": "eps_power_l2",
            # Voltage sensors
            "pv1_voltage": "pv1_voltage",
            "pv2_voltage": "pv2_voltage",
            "pv3_voltage": "pv3_voltage",
            "battery_voltage": "battery_voltage",
            "grid_voltage_r": "grid_voltage_r",
            "grid_voltage_s": "grid_voltage_s",
            "grid_voltage_t": "grid_voltage_t",
            "eps_voltage_r": "eps_voltage_r",
            "eps_voltage_s": "eps_voltage_s",
            "eps_voltage_t": "eps_voltage_t",
            "generator_voltage": "generator_voltage",
            "bus1_voltage": "bus1_voltage",
            "bus2_voltage": "bus2_voltage",
            # Frequency sensors
            "grid_frequency": "grid_frequency",
            "eps_frequency": "eps_frequency",
            "generator_frequency": "generator_frequency",
            # Temperature sensors
            "battery_temperature": "battery_temperature",
            "inverter_temperature": "internal_temperature",
            "radiator1_temperature": "radiator1_temperature",
            "radiator2_temperature": "radiator2_temperature",
            # Battery sensors
            "battery_soc": "state_of_charge",
            # Note: battery_status is extracted from BatteryBank.status in
            # _extract_battery_bank_from_object(), not from the inverter directly
            # Energy sensors - Generation
            "total_energy_today": "yield",
            "total_energy_lifetime": "yield_lifetime",
            # Energy sensors - Grid Import/Export
            "energy_today_import": "grid_import",
            "energy_today_export": "grid_export",
            "energy_lifetime_import": "grid_import_lifetime",
            "energy_lifetime_export": "grid_export_lifetime",
            # Energy sensors - Consumption
            "energy_today_usage": "consumption",
            "energy_lifetime_usage": "consumption_lifetime",
            # Energy sensors - Battery Charging/Discharging
            "energy_today_charging": "charging",
            "energy_today_discharging": "discharging",
            "energy_lifetime_charging": "charging_lifetime",
            "energy_lifetime_discharging": "discharging_lifetime",
            # Current sensors
            "max_charge_current": "max_charge_current",
            "max_discharge_current": "max_discharge_current",
            # Grid power sensors (instantaneous)
            "power_to_user": "grid_import_power",
            "power_to_grid": "grid_export_power",
            # Other sensors
            "power_rating": "power_rating",
            "power_rating_text": "inverter_power_rating",
            "power_factor": "power_factor",
            "status_text": "status_text",
            "status": "status_code",
            "has_data": "has_data",
            # Diagnostic sensors from energy API
            "is_lost": "inverter_lost_status",
            "has_runtime_data": "inverter_has_runtime_data",
        }

    @staticmethod
    def _extract_inverter_features(inverter: "BaseInverter") -> dict[str, Any]:
        """Extract feature capabilities from inverter object.

        This method extracts the detected features from a pylxpweb inverter
        object after detect_features() has been called. The features are used
        for capability-based sensor filtering.

        Args:
            inverter: BaseInverter object with features detected

        Returns:
            Dictionary of feature flags for sensor filtering
        """
        features: dict[str, Any] = {}

        # Get the features object if available
        inverter_features = getattr(inverter, "_features", None)
        if inverter_features is None:
            return features

        # Extract inverter family (EG4_OFFGRID, EG4_HYBRID, LXP, etc.)
        if hasattr(inverter_features, "model_family"):
            family = inverter_features.model_family
            features["inverter_family"] = (
                family.value if isinstance(family, InverterFamily) else str(family)
            )
        else:
            features["inverter_family"] = InverterFamily.UNKNOWN.value

        # Extract grid type
        if hasattr(inverter_features, "grid_type"):
            features["grid_type"] = str(inverter_features.grid_type.value)

        # Extract device type code for debugging
        if hasattr(inverter_features, "device_type_code"):
            features["device_type_code"] = inverter_features.device_type_code

        # Extract boolean capability flags using supports_* properties
        # Maps feature key to InverterFeatures attribute name
        # Some attributes don't follow simple "supports_X" -> "X" pattern
        capability_mapping: dict[str, str] = {
            "supports_split_phase": "split_phase",
            "supports_three_phase": "three_phase_capable",
            "supports_off_grid": "off_grid_capable",
            "supports_parallel": "parallel_support",
            "supports_volt_watt_curve": "volt_watt_curve",
            "supports_grid_peak_shaving": "grid_peak_shaving",
            "supports_drms": "drms_support",
            "supports_discharge_recovery_hysteresis": "discharge_recovery_hysteresis",
        }

        for prop, attr_name in capability_mapping.items():
            if hasattr(inverter, prop):
                features[prop] = getattr(inverter, prop, False)
            elif hasattr(inverter_features, attr_name):
                # Fallback to features object attribute using correct mapping
                features[prop] = getattr(inverter_features, attr_name, False)

        return features

    def _extract_battery_from_object(self, battery: "Battery") -> dict[str, Any]:
        """Extract sensor data from Battery object using properties.

        Args:
            battery: Battery object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        property_map = self._get_battery_property_map()
        sensors = _map_device_properties(battery, property_map)
        self._calculate_battery_derived_sensors(sensors)

        # Compute charge/discharge C-rate as percentage of capacity per hour.
        # Use _safe_float() to handle non-numeric values from mock objects.
        _write_rounded_rates(
            sensors,
            "battery_charge_rate",
            "battery_discharge_rate",
            _safe_float(sensors.get("battery_real_current")),
            _safe_float(sensors.get("battery_full_capacity")),
        )

        return sensors

    @staticmethod
    def _get_battery_property_map() -> dict[str, str]:
        """Get battery property mapping dictionary.

        Returns:
            Dictionary mapping battery property names to sensor keys
        """
        return {
            # Core battery metrics
            "voltage": "battery_real_voltage",
            "current": "battery_real_current",
            "power": "battery_real_power",
            "soc": "battery_rsoc",
            "soh": "state_of_health",
            # Temperature sensors
            "mos_temp": "battery_mos_temperature",
            "ambient_temp": "battery_ambient_temperature",
            "max_cell_temp": "battery_max_cell_temp",
            "min_cell_temp": "battery_min_cell_temp",
            "max_cell_temp_num": "battery_max_cell_temp_num",
            "min_cell_temp_num": "battery_min_cell_temp_num",
            # Cell voltage sensors
            "max_cell_voltage": "battery_max_cell_voltage",
            "min_cell_voltage": "battery_min_cell_voltage",
            "max_cell_voltage_num": "battery_max_cell_voltage_num",
            "min_cell_voltage_num": "battery_min_cell_voltage_num",
            "cell_voltage_delta": "battery_cell_voltage_delta",
            "cell_temp_delta": "battery_cell_temp_delta",
            # Capacity sensors
            "current_remain_capacity": "battery_remaining_capacity",
            "current_full_capacity": "battery_full_capacity",
            "charge_capacity": "battery_design_capacity",
            "discharge_capacity": "battery_discharge_capacity",
            "capacity_percent": "battery_capacity_percentage",
            # Current limits
            "charge_max_current": "battery_max_charge_current",
            "charge_voltage_ref": "battery_charge_voltage_ref",
            # Lifecycle
            "cycle_count": "cycle_count",
            "firmware_version": "battery_firmware_version",
            # Metadata
            "battery_sn": "battery_serial_number",
            "battery_type": "battery_type",
            "battery_type_text": "battery_type_text",
            "bms_model": "battery_bms_model",
            "model": "battery_model",
            "battery_index": "battery_index",
        }

    @staticmethod
    def _calculate_battery_derived_sensors(sensors: dict[str, Any]) -> None:
        """Calculate derived battery sensors from raw sensor data.

        Modifies the sensors dictionary in place to add calculated values.

        Args:
            sensors: Dictionary of sensor values to modify
        """
        # Calculate cell voltage difference only if not provided by library
        if (
            "battery_cell_voltage_diff" not in sensors
            and "battery_cell_voltage_max" in sensors
            and "battery_cell_voltage_min" in sensors
        ):
            sensors["battery_cell_voltage_diff"] = round(
                sensors["battery_cell_voltage_max"]
                - sensors["battery_cell_voltage_min"],
                3,
            )

        # Calculate capacity percentage only if not provided by library
        if (
            "battery_capacity_percentage" not in sensors
            and "battery_remaining_capacity" in sensors
            and "battery_full_capacity" in sensors
            and sensors["battery_full_capacity"] > 0
        ):
            sensors["battery_capacity_percentage"] = round(
                sensors["battery_remaining_capacity"]
                / sensors["battery_full_capacity"]
                * 100,
                1,
            )

    def _extract_battery_bank_from_object(self, battery_bank: Any) -> dict[str, Any]:
        """Extract sensor data from BatteryBank object using properties.

        Args:
            battery_bank: BatteryBank object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        property_map = self._get_battery_bank_property_map()
        sensors = _map_device_properties(battery_bank, property_map)

        # Add battery_status as alias for battery_bank_status for backwards compatibility
        # In v2.2.x, the batStatus field was mapped to battery_status at the inverter level
        # This maintains the sensor for users upgrading from v2.2.x
        if "battery_bank_status" in sensors:
            sensors["battery_status"] = sensors["battery_bank_status"]

        # Calculate battery_bank_power if not available from API (batPower is optional)
        # Formula: charge_power - discharge_power (positive = charging, negative = discharging)
        battery_power = sensors.get("battery_bank_power")
        charge = sensors.get("battery_bank_charge_power")
        discharge = sensors.get("battery_bank_discharge_power")

        if battery_power is not None:
            _LOGGER.debug(
                "HTTP battery_bank_power: from API batPower=%s "
                "(charge=%s, discharge=%s)",
                battery_power,
                charge,
                discharge,
            )
        elif charge is not None and discharge is not None:
            sensors["battery_bank_power"] = charge - discharge
            _LOGGER.debug(
                "HTTP battery_bank_power: using charge-discharge fallback: "
                "charge=%s, discharge=%s, result=%s",
                charge,
                discharge,
                sensors["battery_bank_power"],
            )
        else:
            _LOGGER.warning(
                "HTTP battery_bank_power: cannot calculate - "
                "batPower=%s, charge=%s, discharge=%s",
                battery_power,
                charge,
                discharge,
            )

        return sensors

    @staticmethod
    def _get_battery_bank_property_map() -> dict[str, str]:
        """Get battery bank property mapping dictionary.

        Returns:
            Dictionary mapping battery bank property names to sensor keys
        """
        return {
            # Core metrics
            "voltage": "battery_bank_voltage",
            "current": "battery_bank_current",
            "soc": "battery_bank_soc",
            "charge_power": "battery_bank_charge_power",
            "discharge_power": "battery_bank_discharge_power",
            "battery_power": "battery_bank_power",
            # Capacity metrics
            "max_capacity": "battery_bank_max_capacity",
            "current_capacity": "battery_bank_current_capacity",
            "remain_capacity": "battery_bank_remain_capacity",
            "full_capacity": "battery_bank_full_capacity",
            "capacity_percent": "battery_bank_capacity_percent",
            # Status and metadata
            "battery_count": "battery_bank_count",
            "status": "battery_bank_status",
            # Cross-battery diagnostics (pylxpweb >= 0.6.7)
            "soc_delta": "battery_bank_soc_delta",
            "min_soh": "battery_bank_min_soh",
            "soh_delta": "battery_bank_soh_delta",
            "voltage_delta": "battery_bank_voltage_delta",
            "cell_voltage_delta_max": "battery_bank_cell_voltage_delta_max",
            "cycle_count_delta": "battery_bank_cycle_count_delta",
            "max_cell_temp": "battery_bank_max_cell_temp",
            "temp_delta": "battery_bank_temp_delta",
        }

    async def _process_parallel_group_object(self, group: Any) -> dict[str, Any]:
        """Process parallel group data from group object using properties.

        Args:
            group: ParallelGroup object from pylxpweb

        Returns:
            Processed device data dictionary with sensors
        """
        member_serials = [
            inv.serial_number
            for inv in getattr(group, "inverters", [])
            if hasattr(inv, "serial_number")
        ]
        first_serial = getattr(group, "first_device_serial", "")

        processed: dict[str, Any] = {
            "name": f"Parallel Group {group.name}"
            if hasattr(group, "name") and group.name
            else "Parallel Group",
            "type": "parallel_group",
            "model": "Parallel Group",
            "first_device_serial": first_serial,
            "member_serials": member_serials,
            "member_count": len(member_serials),
            "sensors": {},
            "binary_sensors": {},
        }

        property_map = self._get_parallel_group_property_map()
        processed["sensors"] = _map_device_properties(group, property_map)
        processed["sensors"]["parallel_group_last_polled"] = dt_util.utcnow()

        return processed

    @staticmethod
    def _get_parallel_group_property_map() -> dict[str, str]:
        """Get parallel group property mapping dictionary.

        Returns:
            Dictionary mapping parallel group property names to sensor keys
        """
        return {
            # Aggregate power properties (calculated from all inverters)
            "pv_total_power": "pv_total_power",
            "inverter_power": "ac_power",
            "grid_power": "grid_power",
            "grid_import_power": "grid_import_power",
            "grid_export_power": "grid_export_power",
            "consumption_power": "consumption_power",
            "eps_power": "eps_power",
            # Today energy values
            "today_yielding": "yield",
            "today_discharging": "discharging",
            "today_charging": "charging",
            "today_export": "grid_export",
            "today_import": "grid_import",
            "today_usage": "consumption",
            # Lifetime energy values
            "total_yielding": "yield_lifetime",
            "total_discharging": "discharging_lifetime",
            "total_charging": "charging_lifetime",
            "total_export": "grid_export_lifetime",
            "total_import": "grid_import_lifetime",
            "total_usage": "consumption_lifetime",
            # Aggregate battery properties (calculated from all inverters)
            "battery_charge_power": "parallel_battery_charge_power",
            "battery_discharge_power": "parallel_battery_discharge_power",
            "battery_power": "parallel_battery_power",
            "battery_soc": "parallel_battery_soc",
            "battery_max_capacity": "parallel_battery_max_capacity",
            "battery_current_capacity": "parallel_battery_current_capacity",
            "battery_voltage": "parallel_battery_voltage",
            "battery_count": "parallel_battery_count",
        }

    async def _process_mid_device_object(self, mid_device: Any) -> dict[str, Any]:
        """Process GridBOSS/MID device data from device object using properties.

        Args:
            mid_device: MIDDevice object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        model = getattr(mid_device, "model", "GridBOSS")
        firmware_version = getattr(mid_device, "firmware_version", "1.0.0")

        firmware_update_info = None
        try:
            if hasattr(mid_device, "check_firmware_updates"):
                await mid_device.check_firmware_updates()
                if hasattr(mid_device, "get_firmware_update_progress"):
                    await mid_device.get_firmware_update_progress()
                firmware_update_info = self._extract_firmware_update_info(mid_device)
        except Exception as e:
            _LOGGER.debug(
                "Could not check firmware updates for %s: %s",
                mid_device.serial_number,
                e,
            )

        processed: dict[str, Any] = {
            "serial": mid_device.serial_number,
            "type": "gridboss",
            "model": model,
            "firmware_version": firmware_version,
            "firmware_update_info": firmware_update_info,
            "sensors": {},
            "binary_sensors": {},
        }

        if mid_device.has_data:
            property_map = self._get_mid_device_property_map()
            processed["sensors"] = _map_device_properties(mid_device, property_map)
            processed["sensors"]["firmware_version"] = firmware_version

            # Diagnostic logging for smart port energy (issue #146)
            _LOGGER.debug(
                "MID %s smart port energy: "
                "today=[%s, %s, %s, %s] total=[%s, %s, %s, %s] "
                "power=[%s, %s, %s, %s] status=[%s, %s, %s, %s]",
                mid_device.serial_number,
                getattr(mid_device, "e_smart_load1_today", None),
                getattr(mid_device, "e_smart_load2_today", None),
                getattr(mid_device, "e_smart_load3_today", None),
                getattr(mid_device, "e_smart_load4_today", None),
                getattr(mid_device, "e_smart_load1_total", None),
                getattr(mid_device, "e_smart_load2_total", None),
                getattr(mid_device, "e_smart_load3_total", None),
                getattr(mid_device, "e_smart_load4_total", None),
                processed["sensors"].get("smart_load1_power_l1"),
                processed["sensors"].get("smart_load2_power_l1"),
                processed["sensors"].get("smart_load3_power_l1"),
                processed["sensors"].get("smart_load4_power_l1"),
                getattr(mid_device, "smart_port1_status", None),
                getattr(mid_device, "smart_port2_status", None),
                getattr(mid_device, "smart_port3_status", None),
                getattr(mid_device, "smart_port4_status", None),
            )

            self._filter_unused_smart_port_sensors(processed["sensors"], mid_device)
            self._calculate_gridboss_aggregates(processed["sensors"])
            processed["sensors"]["midbox_last_polled"] = dt_util.utcnow()
        else:
            _LOGGER.warning("MID device %s has no data", mid_device.serial_number)

        return processed

    @staticmethod
    def _get_mid_device_property_map() -> dict[str, str]:
        """Get MID device property mapping dictionary.

        Returns:
            Dictionary mapping MID device property names to sensor keys
        """
        return {
            # Grid sensors
            "grid_power": "grid_power",
            "grid_voltage": "grid_voltage",
            "grid_frequency": "frequency",
            "grid_l1_power": "grid_power_l1",
            "grid_l2_power": "grid_power_l2",
            "grid_l1_voltage": "grid_voltage_l1",
            "grid_l2_voltage": "grid_voltage_l2",
            "grid_l1_current": "grid_current_l1",
            "grid_l2_current": "grid_current_l2",
            # UPS sensors
            "ups_power": "ups_power",
            "ups_voltage": "ups_voltage",
            "ups_l1_power": "ups_power_l1",
            "ups_l2_power": "ups_power_l2",
            "ups_l1_voltage": "load_voltage_l1",
            "ups_l2_voltage": "load_voltage_l2",
            "ups_l1_current": "ups_current_l1",
            "ups_l2_current": "ups_current_l2",
            # Load sensors
            "load_power": "load_power",
            "load_l1_power": "load_power_l1",
            "load_l2_power": "load_power_l2",
            "load_l1_current": "load_current_l1",
            "load_l2_current": "load_current_l2",
            # Generator sensors
            "generator_power": "generator_power",
            "generator_voltage": "generator_voltage",
            "generator_l1_power": "generator_power_l1",
            "generator_l2_power": "generator_power_l2",
            "generator_l1_voltage": "generator_voltage_l1",
            "generator_l2_voltage": "generator_voltage_l2",
            "generator_l1_current": "generator_current_l1",
            "generator_l2_current": "generator_current_l2",
            # Other sensors
            "hybrid_power": "hybrid_power",
            "phase_lock_frequency": "phase_lock_frequency",
            "is_off_grid": "off_grid",
            "smart_port1_status": "smart_port1_status",
            "smart_port2_status": "smart_port2_status",
            "smart_port3_status": "smart_port3_status",
            "smart_port4_status": "smart_port4_status",
            # Smart Load Power sensors (runtime data - L1/L2 have valid data)
            # Property names match MIDRuntimePropertiesMixin in pylxpweb 0.5.5+
            "smart_load1_l1_power": "smart_load1_power_l1",
            "smart_load1_l2_power": "smart_load1_power_l2",
            "smart_load2_l1_power": "smart_load2_power_l1",
            "smart_load2_l2_power": "smart_load2_power_l2",
            "smart_load3_l1_power": "smart_load3_power_l1",
            "smart_load3_l2_power": "smart_load3_power_l2",
            "smart_load4_l1_power": "smart_load4_power_l1",
            "smart_load4_l2_power": "smart_load4_power_l2",
            # AC Couple Power sensors (runtime data - L1/L2 have valid data)
            # Property names match MIDRuntimePropertiesMixin in pylxpweb 0.5.5+
            "ac_couple1_l1_power": "ac_couple1_power_l1",
            "ac_couple1_l2_power": "ac_couple1_power_l2",
            "ac_couple2_l1_power": "ac_couple2_power_l1",
            "ac_couple2_l2_power": "ac_couple2_power_l2",
            "ac_couple3_l1_power": "ac_couple3_power_l1",
            "ac_couple3_l2_power": "ac_couple3_power_l2",
            "ac_couple4_l1_power": "ac_couple4_power_l1",
            "ac_couple4_l2_power": "ac_couple4_power_l2",
            # Energy sensors - aggregate only (L2 energy registers always read 0)
            # UPS energy
            "e_ups_today": "ups_today",
            "e_ups_total": "ups_total",
            # Grid energy
            "e_to_grid_today": "grid_export_today",
            "e_to_grid_total": "grid_export_total",
            "e_to_user_today": "grid_import_today",
            "e_to_user_total": "grid_import_total",
            # Load energy
            "e_load_today": "load_today",
            "e_load_total": "load_total",
            # AC Couple energy (all 4 ports)
            "e_ac_couple1_today": "ac_couple1_today",
            "e_ac_couple1_total": "ac_couple1_total",
            "e_ac_couple2_today": "ac_couple2_today",
            "e_ac_couple2_total": "ac_couple2_total",
            "e_ac_couple3_today": "ac_couple3_today",
            "e_ac_couple3_total": "ac_couple3_total",
            "e_ac_couple4_today": "ac_couple4_today",
            "e_ac_couple4_total": "ac_couple4_total",
            # Smart Load energy (all 4 ports)
            "e_smart_load1_today": "smart_load1_today",
            "e_smart_load1_total": "smart_load1_total",
            "e_smart_load2_today": "smart_load2_today",
            "e_smart_load2_total": "smart_load2_total",
            "e_smart_load3_today": "smart_load3_today",
            "e_smart_load3_total": "smart_load3_total",
            "e_smart_load4_today": "smart_load4_today",
            "e_smart_load4_total": "smart_load4_total",
        }

    @staticmethod
    def _filter_unused_smart_port_sensors(
        sensors: dict[str, Any], mid_device: Any
    ) -> None:
        """Filter smart port sensors based on port status from the MID device.

        For active ports (status 1 or 2), correct-type power sensor keys are
        ensured via setdefault and wrong-type power and energy keys are removed.
        Raw integer status values are also converted to string enum labels.

        - Status 0: Unused - remove all sensors for this port
        - Status 1: Smart Load - ensure smart_load power keys, remove all
          ac_couple keys
        - Status 2: AC Couple - ensure ac_couple power keys, remove all
          smart_load keys

        Invalid status values (None, or outside 0-2 range) are logged as warnings
        and treated as unused. This can occur with certain WiFi dongle firmware
        versions that don't properly expose these registers.

        Modifies the sensors dictionary in place.

        Args:
            sensors: Dictionary of sensor values to modify
            mid_device: MID device object to read port statuses from
        """
        smart_port_statuses: dict[int, int | None] = {}
        for port in range(1, 5):
            status_property = f"smart_port{port}_status"
            if hasattr(mid_device, status_property):
                status_value = getattr(mid_device, status_property)
                smart_port_statuses[port] = status_value

        _LOGGER.debug(
            "Smart Port statuses for filtering: %s (0=Unused, 1=SmartLoad, 2=ACCouple)",
            smart_port_statuses,
        )

        # Check for invalid values and log warnings with diagnostic info
        invalid_ports: dict[int, int | None] = {}
        for port, status in smart_port_statuses.items():
            if status is None or status not in _SMART_PORT_STATUS_LABELS:
                invalid_ports[port] = status

        if invalid_ports:
            # Get device info for troubleshooting
            serial = getattr(mid_device, "serial_number", "unknown")
            firmware = getattr(mid_device, "firmware_version", "unknown")
            has_transport = (
                hasattr(mid_device, "_transport") and mid_device._transport is not None
            )

            # Only log warning once per device to avoid log spam
            if serial not in _warned_smart_port_devices:
                _warned_smart_port_devices.add(serial)
                _LOGGER.warning(
                    "Invalid Smart Port status values detected for MID device %s "
                    "(firmware: %s, has_local_transport: %s). "
                    "Invalid ports: %s. Valid values are 0=Unused, 1=SmartLoad, 2=ACCouple. "
                    "This may indicate firmware that doesn't support these registers. "
                    "Please report this issue with your dongle firmware version.",
                    serial,
                    firmware,
                    has_transport,
                    invalid_ports,
                )

        # Convert raw status integers to enum string labels (always, even
        # when we skip power sensor filtering on all-zeros below)
        for port, status in smart_port_statuses.items():
            if status is not None and status in _SMART_PORT_STATUS_LABELS:
                sensors[f"smart_port{port}_status"] = _SMART_PORT_STATUS_LABELS[status]

        # If all statuses are 0 or None, the dongle likely returned unreliable data.
        # Skip filtering entirely to avoid removing sensors for ports that are
        # actually in use. On subsequent polls with correct data, the filter will
        # correctly remove sensors for genuinely unused ports.
        valid_statuses = [s for s in smart_port_statuses.values() if s is not None]
        if valid_statuses and all(s == 0 for s in valid_statuses):
            _LOGGER.debug(
                "All Smart Port statuses are 0 — skipping sensor filtering "
                "(dongle may have returned unreliable data on initial poll)"
            )
            return

        sensors_to_remove: list[str] = []
        for port, status in smart_port_statuses.items():
            smart_load_power_keys = [
                f"smart_load{port}_power_l1",
                f"smart_load{port}_power_l2",
                f"smart_load{port}_power",
            ]
            smart_load_energy_keys = [
                f"smart_load{port}_today",
                f"smart_load{port}_total",
            ]
            ac_couple_power_keys = [
                f"ac_couple{port}_power_l1",
                f"ac_couple{port}_power_l2",
                f"ac_couple{port}_power",
            ]
            ac_couple_energy_keys = [
                f"ac_couple{port}_today",
                f"ac_couple{port}_total",
            ]

            if status is None or status not in _SMART_PORT_STATUS_LABELS or status == 0:
                # Unused or invalid port - remove all sensors
                sensors_to_remove.extend(smart_load_power_keys)
                sensors_to_remove.extend(smart_load_energy_keys)
                sensors_to_remove.extend(ac_couple_power_keys)
                sensors_to_remove.extend(ac_couple_energy_keys)
            elif status == 1:
                # Smart Load mode: ensure smart_load power keys exist,
                # remove ac_couple power + energy (wrong type for this port)
                for key in smart_load_power_keys:
                    sensors.setdefault(key, 0.0)
                sensors_to_remove.extend(ac_couple_power_keys)
                sensors_to_remove.extend(ac_couple_energy_keys)
            elif status == 2:
                # AC Couple mode: ensure ac_couple power keys exist,
                # remove smart_load power + energy (wrong type for this port)
                for key in ac_couple_power_keys:
                    sensors.setdefault(key, 0.0)
                sensors_to_remove.extend(smart_load_power_keys)
                sensors_to_remove.extend(smart_load_energy_keys)

        if sensors_to_remove:
            _LOGGER.debug(
                "Removing %d Smart Port sensors based on status: %s",
                len(sensors_to_remove),
                sensors_to_remove,
            )
        for sensor_key in sensors_to_remove:
            sensors.pop(sensor_key, None)

    @staticmethod
    def _calculate_gridboss_aggregates(sensors: dict[str, Any]) -> None:
        """Calculate aggregate power sensor values from individual L1/L2 values.

        Note: Energy aggregates are provided directly by pylxpweb 0.5.2+
        since L2 energy registers always read 0. Only power sensors need
        aggregation here as they have valid L1/L2 data.

        Modifies the sensors dictionary in place.

        Args:
            sensors: Dictionary of sensor values to modify
        """

        def sum_l1_l2(l1_key: str, l2_key: str) -> float | None:
            """Sum L1 and L2 values if both exist, return None otherwise."""
            if l1_key in sensors and l2_key in sensors:
                l1_val = sensors[l1_key]
                l2_val = sensors[l2_key]
                if l1_val is None and l2_val is None:
                    return None
                return _safe_numeric(l1_val) + _safe_numeric(l2_val)
            return None

        # Calculate per-port and total aggregate power for smart port types
        for prefix in ("smart_load", "ac_couple"):
            port_powers: list[float] = []
            for port in range(1, 5):
                port_power = sum_l1_l2(
                    f"{prefix}{port}_power_l1", f"{prefix}{port}_power_l2"
                )
                if port_power is not None:
                    sensors[f"{prefix}{port}_power"] = port_power
                    port_powers.append(port_power)
            if port_powers:
                sensors[f"{prefix}_power"] = sum(port_powers)

        # Calculate aggregate power for simple L1/L2 sensor pairs
        l1_l2_aggregates = [
            ("grid_power_l1", "grid_power_l2", "grid_power"),
            ("ups_power_l1", "ups_power_l2", "ups_power"),
            ("load_power_l1", "load_power_l2", "load_power"),
            ("generator_power_l1", "generator_power_l2", "generator_power"),
        ]
        for l1_key, l2_key, output_key in l1_l2_aggregates:
            total = sum_l1_l2(l1_key, l2_key)
            if total is not None:
                sensors[output_key] = total


class DeviceInfoMixin(_MixinBase):
    """Mixin for device info retrieval methods.

    Caches DeviceInfo objects per update cycle to avoid redundant construction
    and logging. HA calls each entity's device_info property during registration,
    so without caching, get_battery_device_info() would log 2 DEBUG lines × 162
    battery sensors = 324 redundant log lines per setup.
    """

    def clear_device_info_caches(self) -> None:
        """Clear all device_info caches. Call at the start of each update cycle."""
        self._device_info_cache: dict[str, DeviceInfo] = {}
        self._battery_device_info_cache: dict[str, DeviceInfo] = {}
        self._battery_bank_device_info_cache: dict[str, DeviceInfo] = {}

    def _get_cache(self, attr: str) -> dict[str, DeviceInfo]:
        """Get a cache dict by attribute name, lazily initializing if needed."""
        cache: dict[str, DeviceInfo] | None = getattr(self, attr, None)
        if cache is None:
            cache = {}
            setattr(self, attr, cache)
        return cache

    def get_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for a specific serial number."""
        cache = self._get_cache("_device_info_cache")
        if serial in cache:
            return cache[serial]

        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "unknown")

        if device_type == "parallel_group":
            device_name = device_data.get("name", model)
        else:
            device_name = f"{model} {serial}"

        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": model,
        }

        if device_type != "parallel_group":
            device_info["serial_number"] = serial
            sw_version = "1.0.0"
            if device_type in ["gridboss", "inverter"]:
                sw_version = device_data.get("firmware_version", "1.0.0")
            device_info["sw_version"] = sw_version

        if device_type in ["inverter", "gridboss"]:
            parallel_group_serial = self._get_parallel_group_for_device(serial)
            if parallel_group_serial:
                device_info["via_device"] = (DOMAIN, parallel_group_serial)

        result = cast(DeviceInfo, device_info)
        cache[serial] = result
        return result

    def _get_parallel_group_for_device(self, device_serial: str) -> str | None:
        """Get the parallel group serial that contains this device.

        Checks both HTTP mode (via Station.parallel_groups) and LOCAL mode
        (via member_serials list in device data).
        """
        if not self.data or "devices" not in self.data:
            return None

        # HTTP/Hybrid mode: Check Station's parallel groups
        if self.station and hasattr(self.station, "parallel_groups"):
            for group in self.station.parallel_groups:
                if hasattr(group, "inverters"):
                    for inverter in group.inverters:
                        if inverter.serial_number == device_serial:
                            return f"parallel_group_{group.name.lower()}"

        # LOCAL mode: Check parallel group device data for member_serials
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                member_serials = device_data.get("member_serials", [])
                if device_serial in member_serials:
                    return str(serial)

        return None

    def get_battery_device_info(
        self, serial: str, battery_key: str
    ) -> DeviceInfo | None:
        """Get device information for a specific battery."""
        cache = self._get_cache("_battery_device_info_cache")
        cache_key = f"{serial}_{battery_key}"
        if cache_key in cache:
            return cache[cache_key]

        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data or battery_key not in device_data.get("batteries", {}):
            return None

        battery_data = device_data.get("batteries", {}).get(battery_key, {})
        battery_firmware = battery_data.get("battery_firmware_version", "1.0.0")

        bms_model = battery_data.get("battery_bms_model")
        battery_model_name = battery_data.get("battery_model")
        battery_type_text = battery_data.get("battery_type_text")
        model = bms_model or battery_model_name or battery_type_text or "Battery Module"

        clean_battery_name = clean_battery_display_name(battery_key, serial)
        battery_bank_identifier = f"{serial}_battery_bank"

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, battery_key)},
            "name": f"Battery {clean_battery_name}",
            "manufacturer": MANUFACTURER,
            "model": model,
            "sw_version": battery_firmware,
            "via_device": (DOMAIN, battery_bank_identifier),
        }

        _LOGGER.debug(
            "Created battery device_info for %s: name='%s', model='%s', "
            "identifier='%s', via_device=%s",
            battery_key,
            device_info["name"],
            model,
            battery_key,
            battery_bank_identifier,
        )

        cache[cache_key] = device_info
        return device_info

    def get_battery_bank_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for battery bank (aggregate of all batteries)."""
        cache = self._get_cache("_battery_bank_device_info_cache")
        if serial in cache:
            return cache[serial]

        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        sensors = device_data.get("sensors", {})

        # Check if any battery_bank sensors exist (not just count > 0)
        # Aggregate data like soc, voltage can exist even when totalNumber=0
        has_battery_bank_data = any(
            key.startswith("battery_bank_") for key in sensors.keys()
        )
        if not has_battery_bank_data:
            return None

        battery_count = sensors.get("battery_bank_count") or 0
        model = device_data.get("model", "Unknown")

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, f"{serial}_battery_bank")},
            "name": f"Battery Bank {serial}",
            "manufacturer": MANUFACTURER,
            "model": f"{model} Battery Bank",
            "via_device": (DOMAIN, serial),
        }

        _LOGGER.debug(
            "Created battery_bank device_info for %s: name='%s', model='%s', "
            "battery_count=%d, via_device=%s",
            serial,
            device_info["name"],
            device_info["model"],
            battery_count,
            serial,
        )

        cache[serial] = device_info
        return device_info

    def get_station_device_info(self) -> DeviceInfo | None:
        """Get device information for the station/plant."""
        if not self.data or "station" not in self.data:
            return None

        station_data = self.data["station"]
        station_name = station_data.get("name", f"Station {self.plant_id}")

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, f"station_{self.plant_id}")},
            "name": f"Station {station_name}",
            "manufacturer": MANUFACTURER,
            "model": "Station",
        }

        # Add configuration URL if HTTP client is available
        if self.client is not None:
            device_info["configuration_url"] = (
                f"{self.client.base_url}/WManage/web/config/plant/edit/{self.plant_id}"
            )

        return device_info


class ParameterManagementMixin(_MixinBase):
    """Mixin for device parameter refresh operations."""

    async def refresh_all_device_parameters(self) -> None:
        """Refresh parameters for all inverter devices when any parameter changes."""
        try:
            _LOGGER.info(
                "Refreshing parameters for all inverter devices due to parameter change"
            )

            if not self.data or "devices" not in self.data:
                _LOGGER.debug(
                    "No device data available for parameter refresh - "
                    "integration may still be initializing"
                )
                return

            inverter_serials = []
            for serial, device_data in self.data["devices"].items():
                device_type = device_data.get("type", "unknown")
                if device_type == "inverter":
                    inverter_serials.append(serial)

            if not inverter_serials:
                _LOGGER.warning("No inverter devices found for parameter refresh")
                return

            refresh_tasks = []
            for serial in inverter_serials:
                task = self._refresh_device_parameters(serial)
                refresh_tasks.append(task)

            results = await asyncio.gather(*refresh_tasks, return_exceptions=True)

            success_count = 0
            for i, result in enumerate(results):
                serial = inverter_serials[i]
                if isinstance(result, Exception):
                    _LOGGER.error(
                        "Failed to refresh parameters for %s: %s", serial, result
                    )
                else:
                    success_count += 1

            _LOGGER.info(
                "Successfully refreshed parameters for %d/%d inverters",
                success_count,
                len(inverter_serials),
            )

        except Exception as e:
            _LOGGER.error("Error during all-device parameter refresh: %s", e)

    async def async_refresh_device_parameters(self, serial: str) -> None:
        """Public method to refresh parameters for a specific device."""
        try:
            _LOGGER.debug("Refreshing parameters for device %s", serial)
            await self._refresh_device_parameters(serial)
            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)

    async def _refresh_device_parameters(self, serial: str) -> None:
        """Refresh parameters for a specific device using device object."""
        try:
            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.warning("Cannot find inverter object for serial %s", serial)
                return

            # Use force=True to bypass cache when refreshing parameters after changes
            await inverter.refresh(force=True, include_parameters=True)

            if hasattr(inverter, "parameters") and inverter.parameters:
                if not self.data:
                    return

                if "parameters" not in self.data:
                    self.data["parameters"] = {}

                self.data["parameters"][serial] = inverter.parameters
            else:
                _LOGGER.warning(
                    "Inverter %s has no parameters attribute or empty parameters",
                    serial,
                )

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)
            raise

    async def _refresh_missing_parameters(
        self, inverter_serials: list[str], processed_data: dict[str, Any]
    ) -> None:
        """Refresh parameters for inverters that don't have them yet."""
        try:
            for serial in inverter_serials:
                try:
                    await self._refresh_device_parameters(serial)
                    if (
                        self.data
                        and "parameters" in self.data
                        and serial in self.data["parameters"]
                    ):
                        processed_data["parameters"][serial] = self.data["parameters"][
                            serial
                        ]
                except Exception as e:
                    _LOGGER.error(
                        "Failed to refresh missing parameters for %s: %s", serial, e
                    )

            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error during missing parameter refresh: %s", e)

    async def _hourly_parameter_refresh(self) -> None:
        """Perform hourly parameter refresh for all inverters."""
        try:
            await self.refresh_all_device_parameters()
            self._last_parameter_refresh = dt_util.utcnow()
        except Exception as e:
            _LOGGER.error("Error during hourly parameter refresh: %s", e)

    def _should_refresh_parameters(self) -> bool:
        """Check if hourly parameter refresh is due."""
        if self._last_parameter_refresh is None:
            return True

        time_since_refresh = dt_util.utcnow() - self._last_parameter_refresh
        return bool(time_since_refresh >= self._parameter_refresh_interval)


class DSTSyncMixin(_MixinBase):
    """Mixin for daylight saving time synchronization operations."""

    def _should_sync_dst(self) -> bool:
        """Check if DST sync is due.

        Performs DST sync one minute before the top of each hour.
        """
        now = dt_util.utcnow()

        minutes_to_hour = 60 - now.minute
        is_near_hour = minutes_to_hour <= 1

        if not is_near_hour:
            return False

        if self._last_dst_sync is None:
            return True

        time_since_sync = now - self._last_dst_sync
        return bool(time_since_sync >= self._dst_sync_interval)

    async def _perform_dst_sync(self) -> None:
        """Perform DST synchronization if needed."""
        if not self.dst_sync_enabled or not self.station:
            return

        try:
            dst_status = self.station.detect_dst_status()
            if dst_status is False:
                _LOGGER.info(
                    "DST mismatch detected for station %s, syncing DST setting",
                    self.plant_id,
                )
                sync_result = await self.station.sync_dst_setting()
                if sync_result:
                    _LOGGER.info(
                        "DST setting synchronized successfully for station %s",
                        self.plant_id,
                    )
                else:
                    _LOGGER.warning(
                        "Failed to synchronize DST setting for station %s",
                        self.plant_id,
                    )
                self._last_dst_sync = dt_util.utcnow()
            elif dst_status is True:
                _LOGGER.debug(
                    "DST setting is already correct for station %s",
                    self.plant_id,
                )
                self._last_dst_sync = dt_util.utcnow()
            else:
                _LOGGER.debug(
                    "DST status could not be determined for station %s",
                    self.plant_id,
                )
                self._last_dst_sync = dt_util.utcnow()
        except Exception as e:
            _LOGGER.warning(
                "Error during DST sync for station %s: %s", self.plant_id, e
            )
            self._last_dst_sync = dt_util.utcnow()


class BackgroundTaskMixin(_MixinBase):
    """Mixin for background task management operations."""

    async def _cancel_background_tasks(self) -> None:
        """Cancel all background tasks and wait for them to finish."""
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

    async def _async_handle_shutdown(self, event: Any) -> None:
        """Handle Home Assistant stop event to cancel background tasks.

        When this fires, the listener auto-removes itself from the event bus.
        We set flags so async_shutdown() doesn't try to remove it again.
        """
        _LOGGER.debug("Handling Home Assistant stop event, cancelling background tasks")
        self._shutdown_listener_fired = True
        # Mark removal function as used - the one-time listener auto-removes itself
        self._shutdown_listener_remove = None

        if hasattr(self, "_debounced_refresh") and self._debounced_refresh:
            self._debounced_refresh.async_cancel()
            await asyncio.sleep(0)
            _LOGGER.debug("Cancelled debounced refresh")

        await self._cancel_background_tasks()
        _LOGGER.debug("All background tasks cancelled and cleaned up")

    async def async_shutdown(self) -> None:
        """Clean up background tasks and event listeners on shutdown."""
        # Only try to remove listener if:
        # - It exists (not None)
        # - The shutdown event hasn't fired (which auto-removes the one-time listener)
        remove_func = getattr(self, "_shutdown_listener_remove", None)
        listener_fired = getattr(self, "_shutdown_listener_fired", False)

        if remove_func is not None and not listener_fired:
            try:
                remove_func()
                _LOGGER.debug("Removed homeassistant_stop event listener")
            except ValueError:
                # Listener already removed (e.g. integration re-added in same session)
                _LOGGER.debug("Shutdown listener already removed")
            finally:
                # Mark as removed to prevent double-removal attempts
                self._shutdown_listener_remove = None

        await self._cancel_background_tasks()
        _LOGGER.debug("Coordinator shutdown complete, all background tasks cleaned up")

    def _remove_task_from_set(self, task: asyncio.Task[Any]) -> None:
        """Remove completed task from background tasks set."""
        self._background_tasks.discard(task)

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        """Log exception from completed task if not cancelled."""
        if not task.cancelled():
            exception = task.exception()
            if exception:
                _LOGGER.error(
                    "Background task failed with exception: %s",
                    exception,
                    exc_info=exception,
                )


class FirmwareUpdateMixin(_MixinBase):
    """Mixin for firmware update information extraction."""

    def _extract_firmware_update_info(
        self, device: "BaseInverter"
    ) -> dict[str, Any] | None:
        """Extract firmware update information from device object.

        Args:
            device: Inverter or MID device object with FirmwareUpdateMixin

        Returns:
            Dictionary with firmware update info or None if no update available
        """
        if not hasattr(device, "firmware_update_available"):
            return None

        if not device.firmware_update_available:
            return None

        update_info: dict[str, Any] = {
            "latest_version": device.latest_firmware_version,
            "title": device.firmware_update_title,
            "release_summary": device.firmware_update_summary,
            "release_url": device.firmware_update_url,
            "in_progress": False,
            "update_percentage": None,
        }

        if hasattr(device, "firmware_update_in_progress"):
            update_info["in_progress"] = device.firmware_update_in_progress

        if hasattr(device, "firmware_update_percentage"):
            update_info["update_percentage"] = device.firmware_update_percentage

        return update_info
