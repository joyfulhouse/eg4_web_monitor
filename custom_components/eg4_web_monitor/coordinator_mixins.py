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
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from pylxpweb import LuxpowerClient
    from pylxpweb.devices import Battery, BatteryBank, MIDDevice, ParallelGroup, Station
    from pylxpweb.devices.inverters.base import BaseInverter
    from pylxpweb.transports import (
        DongleTransport,
        ModbusSerialTransport,
        ModbusTransport,
    )
    from pylxpweb.transports.data import BatteryData

    # The device objects accepted by the generic property mapper.
    _DeviceObject = BaseInverter | Battery | BatteryBank | MIDDevice | ParallelGroup

from .const import (
    CONF_LOCAL_TRANSPORTS,
    DOMAIN,
    INVERTER_FAMILY_EG4_OFFGRID,
    MANUFACTURER,
    operating_state_slug,
)
from .coordinator_mappings import (
    SMART_PORT_VALIDATED_KEY,
    _apply_grid_type_override,
    _apply_model_family_fallback,
    _build_battery_bank_sensor_mapping,
    _energy_balance,
    _features_dict_from_inverter_features,
    _safe_float,
    _write_charge_rate,
    alias_common_voltage_sensors,
    build_battery_bank_sensors,
    compute_bank_charge_rate,
    drop_offgrid_cloud_output_power,
    get_battery_bank_property_map,
)
from .utils import clean_battery_display_name, is_offgrid_family, normalize_event_row

_LOGGER = logging.getLogger(__name__)

# Bound (seconds) on the offgrid cloud quick-charge status read (#296). The
# read shares the pylxpweb client's station-wide retry/backoff state; during a
# cloud 502 storm an escalated backoff can sleep up to ~60s inside the call,
# which would hold a coordinator semaphore slot for the storm's duration. A
# timeout is treated as a failed read (carry-forward). Full backoff-domain
# isolation is a pylxpweb architectural item deliberately not attempted here.
QUICK_CHARGE_CLOUD_STATUS_TIMEOUT = 10.0

# Portal event-log poll throttle (#327).  Events are pushed to the cloud
# out-of-band by the device (some never surface in registers), so the Last
# Event sensor polls /WManage/api/analyze/event/list — but events are rare,
# so the fetch follows the 5-minute smart-cache tier (same as battery info)
# to keep the added API pressure minimal.
EVENT_LOG_FETCH_INTERVAL = 300.0

# Bound (seconds) on the event-log cloud read — same rationale as
# QUICK_CHARGE_CLOUD_STATUS_TIMEOUT: the call shares the client's station-wide
# retry/backoff state and must not hold a coordinator slot through a 502-storm
# backoff sleep. A timeout is a failed read (carry-forward).
EVENT_LOG_CLOUD_TIMEOUT = 10.0

# HA caps entity state strings at 255 chars; longer states are rejected
# outright. The Last Event sensor state (event text) is truncated defensively.
_MAX_STATE_LENGTH = 255

# AC Couple SOC window (GH #352): cloud-only holdParams with no pinned local
# register, refreshed through pylxpweb's get_inverter_ac_couple_soc_limits —
# which costs THREE cloud parameter-range reads per inverter per fetch, so it
# sits on the 5-minute tier (matching the battery-info class volatility of a
# working-mode setpoint) with carry-forward between fetches.
AC_COUPLE_SOC_FETCH_INTERVAL = 300.0
# The getter's three range reads run concurrently, but each is a remoteRead
# relayed through the dongle — bound the whole call so a backoff-stalled cloud
# session cannot hold a coordinator slot (the quick-charge timeout precedent).
AC_COUPLE_SOC_FETCH_TIMEOUT = 30.0

# Rate floor between parameter refresh ATTEMPTS (#282).  A failed/partial
# parameter read no longer stamps _last_parameter_refresh, so the refresh
# re-arms early instead of serving a degraded snapshot for the whole
# parameter interval — but retries are floored at this spacing so a long
# dongle outage doesn't add a full parameter read to every ~20-30 s poll.
_PARAMETER_RETRY_INTERVAL = timedelta(minutes=2)

# Eviction bound for once-published batteries served from cache (#258 review).
# The carry-forward and the LOCAL round-robin re-serve absorb seconds-to-
# minutes cloud/transport gaps; without a bound a PHYSICALLY REMOVED pack
# would survive until restart with frozen SoC feeding bank aggregates and
# automations, negating pylxpweb's empty-bank convergence.  6 hours is far
# above every transient this covers, and safe versus the 2026-06-28 9-hour
# firmware page pinning: during pinning the accumulator still SERVES the
# batteries as fresh current-cycle data, so cached-serve is not what holds
# them — only a battery gone from BOTH cloud and accumulator ages here.
BATTERY_CARRY_FORWARD_MAX_AGE = timedelta(hours=6)

# Track devices that have already been warned about invalid smart port status
# to avoid log spam on every poll cycle
_warned_smart_port_devices: set[str] = set()

# Cache the last known good smart port statuses per MID device serial.
# WiFi dongles return corrupt status register data ~3% of polls (out-of-range
# values like status=3). Using cached values prevents the filter from being
# skipped, which would allow raw AC couple data to leak through as
# smart_load sensor values. Note: all-zeros is a valid state (all ports
# unused) and should NOT be treated as corrupt (#195/#248).
_last_good_smart_port_statuses: dict[str, dict[int, int]] = {}

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

# Per-inverter grid per-leg voltage keys (input regs 193/194).  EG4 US
# split-phase inverters (18kPV, FlexBOSS, 12kPV) do NOT populate these — the
# inverter measures only aggregate grid voltage (reg 12 ≈ 240 V); the real
# per-leg grid voltage comes from the GridBOSS CTs (already surfaced on the
# GridBOSS and parallel-group entities).  Confirmed firmware-zero on live
# 18kPV and FlexBOSS21 across the entire 193-204 block (issue #243 follow-up).
_INVERTER_DEAD_GRID_LEG_KEYS: tuple[str, ...] = ("grid_voltage_l1", "grid_voltage_l2")

# Transport-exclusive runtime sensor overlay (HYBRID mode).
# (sensor_key, InverterRuntimeData attribute) pairs applied in
# _process_inverter_object() when a local transport is attached: these are
# Modbus-only values the cloud API does not provide (e.g. bt_temperature
# reg 108, grid current regs 18/190/191, battery current reg 98) plus
# split-phase per-leg voltages and the reg-170 load power (#197/#243).
# Module-level so the register contract harness can verify each pair against
# the canonical register tables (tests/test_register_contract_harness.py).
_TRANSPORT_OVERLAY: tuple[tuple[str, str], ...] = (
    ("bt_temperature", "temperature_t1"),
    ("grid_current_l1", "inverter_rms_current_r"),
    ("grid_current_l2", "inverter_rms_current_s"),
    ("grid_current_l3", "inverter_rms_current_t"),
    ("battery_current", "battery_current"),
    # Split-phase per-leg voltages (Modbus regs 12/13 grid, 127/128
    # EPS).  The cloud API has no per-leg field, so in HYBRID these
    # are only available from the local transport — surface them here
    # so HYBRID matches LOCAL parity (issue #243).  Pure CLOUD has no
    # transport_runtime, so they stay correctly absent there.
    ("grid_voltage_l1", "grid_l1_voltage"),
    ("grid_voltage_l2", "grid_l2_voltage"),
    ("eps_voltage_l1", "eps_l1_voltage"),
    ("eps_voltage_l2", "eps_l2_voltage"),
    # Load power (reg 170, "Pload").  The cloud zeroes its reg-170
    # mirror for EG4_OFFGRID, so in HYBRID the value must come
    # from the local register, never a cloud property (#197).
    # Entity creation is gated to EG4_OFFGRID in sensor.py.
    ("load_power", "output_power"),
    # Inverter fault/warning codes (regs 60-61 / 62-63, 32-bit
    # bitfields; pylxpweb merges the BMS code in as a fallback when
    # the inverter code reads 0).  The cloud getInverterRuntime
    # response has no faultCode/warningCode field (canonical table
    # cloud_api_field=None), so HYBRID overlays the local registers
    # and pure CLOUD correctly stays without the keys (eg4-23a6).
    ("fault_code", "fault_code"),
    ("warning_code", "warning_code"),
)

# Transport-exclusive energy sensor overlay (HYBRID mode).
# (sensor_key, InverterEnergyData attribute) pairs applied in
# _process_inverter_object(): per-leg EPS energy (regs 133-138) and the
# granular per-string / per-component energy registers, none of which the
# cloud energy endpoint provides (#243).  Module-level for the same
# contract-harness reason as _TRANSPORT_OVERLAY above.
_ENERGY_OVERLAY: tuple[tuple[str, str], ...] = (
    ("eps_energy_today_l1", "eps_l1_energy_today"),
    ("eps_energy_today_l2", "eps_l2_energy_today"),
    ("eps_energy_total_l1", "eps_l1_energy_total"),
    ("eps_energy_total_l2", "eps_l2_energy_total"),
    # Granular per-string / per-component energy — register-backed,
    # absent from the cloud energy endpoint, so overlaid from the
    # local transport in HYBRID (disabled-by-default sensors, #243).
    ("pv1_yield", "pv1_energy_today"),
    ("pv2_yield", "pv2_energy_today"),
    ("pv3_yield", "pv3_energy_today"),
    ("pv4_yield", "pv4_energy_today"),
    ("pv5_yield", "pv5_energy_today"),
    ("pv6_yield", "pv6_energy_today"),
    ("pv1_yield_lifetime", "pv1_energy_total"),
    ("pv2_yield_lifetime", "pv2_energy_total"),
    ("pv3_yield_lifetime", "pv3_energy_total"),
    ("pv4_yield_lifetime", "pv4_energy_total"),
    ("pv5_yield_lifetime", "pv5_energy_total"),
    ("pv6_yield_lifetime", "pv6_energy_total"),
    ("inverter_energy", "inverter_energy_today"),
    ("inverter_energy_lifetime", "inverter_energy_total"),
    ("ac_charge_energy", "ac_charge_energy_today"),
    ("ac_charge_energy_lifetime", "ac_charge_energy_total"),
    ("eps_energy", "eps_energy_today"),
    ("eps_energy_lifetime", "eps_energy_total"),
    ("generator_energy", "generator_energy_today"),
    ("generator_energy_lifetime", "generator_energy_total"),
)


def drop_dead_inverter_grid_legs(sensors: dict[str, Any]) -> None:
    """Drop per-inverter grid per-leg voltage when it reads 0/None.

    A live grid leg is never truly 0 V, so a 0/None reading on regs 193/194
    means the inverter firmware isn't populating it — publish nothing rather
    than a misleading 0, leaving the entity unavailable.  A genuine non-zero
    reading still flows through unchanged, so this asserts nothing about other
    topologies (e.g. a hypothetical grid-direct install without a GridBOSS).

    Inverter-scoped: callers apply this only to inverter sensor dicts, never to
    GridBOSS or parallel-group sensors, whose grid_voltage_l1/l2 come from the
    authoritative CT registers (GridBOSS regs 4/5).
    """
    for key in _INVERTER_DEAD_GRID_LEG_KEYS:
        if not sensors.get(key):  # None, 0, or 0.0 — never a live grid leg
            sensors.pop(key, None)


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


def apply_ac_couple_pv_adjustment(
    pg_sensors: dict[str, Any],
    gb_sensors: dict[str, Any],
    group_name: str,
    *,
    include_ac_couple: bool,
) -> None:
    """Add AC-coupled smart-port power into the parallel group's pv_total_power.

    AC-coupled solar inverters feed through GridBOSS smart ports, so their
    production is invisible to the EG4 inverters' own PV registers.  When the
    user opts in (CONF_INCLUDE_AC_COUPLE_PV), add the AC-couple smart-port
    power to pv_total_power so total solar production is represented.

    Called from both the LOCAL path and the HTTP path (hybrid mode) so that
    pv_total_power is consistent regardless of connection mode.

    Args:
        pg_sensors: Parallel group sensor dict (modified in place).
        gb_sensors: GridBOSS/MID device sensor dict.
        group_name: Parallel group name for debug logging.
        include_ac_couple: Whether AC-couple inclusion is enabled.
    """
    if not include_ac_couple:
        return

    ac_couple_total = 0.0
    for port_num in range(1, 5):  # Ports 1-4
        # Smart port status 2 = AC Couple (solar inverter connected)
        if gb_sensors.get(f"smart_port{port_num}_status") != "ac_couple":
            continue
        l1_power = gb_sensors.get(f"ac_couple{port_num}_power_l1") or 0
        l2_power = gb_sensors.get(f"ac_couple{port_num}_power_l2") or 0
        port_power = float(l1_power) + float(l2_power)
        ac_couple_total += port_power
        _LOGGER.debug(
            "Parallel group %s: AC couple port %d power=%sW",
            group_name,
            port_num,
            port_power,
        )

    if ac_couple_total > 0:
        current_pv = float(pg_sensors.get("pv_total_power", 0.0) or 0.0)
        pg_sensors["pv_total_power"] = current_pv + ac_couple_total
        _LOGGER.debug(
            "Parallel group %s: pv_total_power=%sW (inverters=%sW + AC couple=%sW)",
            group_name,
            pg_sensors["pv_total_power"],
            current_pv,
            ac_couple_total,
        )


def _recompute_consumption_from_balance(
    pg_sensors: dict[str, Any], group_name: str
) -> None:
    """Recompute consumption_power from the energy balance (LOCAL only).

    In MID (GridBOSS) systems the inverters' own grid registers are unreliable,
    so the energy-balance consumption_power summed from inverters is garbage.
    Replace it using the MID device's authoritative grid_power (already overlaid
    onto ``grid_power`` by :func:`apply_gridboss_overlay`).

    Formula: consumption = pv + battery_net + grid_power
        pv          — inverters' own PV (pv_total_power)
        battery_net — negative of parallel_battery_power (positive = charging)
        grid_power  — from the GridBOSS overlay (positive = importing)

    Args:
        pg_sensors: Parallel group sensor dict (modified in place).
        group_name: Parallel group name for debug logging.
    """
    pv = float(pg_sensors.get("pv_total_power", 0.0))
    bat_power = float(pg_sensors.get("parallel_battery_power", 0.0))
    grid = float(pg_sensors.get("grid_power", 0.0))
    battery_net = -bat_power
    consumption = max(0.0, pv + battery_net + grid)
    pg_sensors["consumption_power"] = consumption
    _LOGGER.debug(
        "LOCAL: Parallel group %s: consumption_power = "
        "pv(%s) + bat_net(%s) + grid(%s) = %s",
        group_name,
        pv,
        battery_net,
        grid,
        consumption,
    )


def apply_gridboss_to_parallel_group(
    pg_sensors: dict[str, Any],
    gb_sensors: dict[str, Any],
    group_name: str,
    *,
    include_ac_couple: bool,
    recompute_consumption: bool,
) -> None:
    """Apply the full GridBOSS workflow to a parallel group's sensors.

    Single canonical sequence shared by the HTTP/HYBRID and LOCAL coordinators,
    so the GridBOSS overlay call sites can no longer diverge (cure for F4):

      1. overlay GridBOSS CT measurements (authoritative grid/consumption);
      2. (LOCAL only, ``recompute_consumption=True``) recompute
         consumption_power from the energy balance using the overlaid
         grid_power — folds the LOCAL-only M3 post-step behind a flag;
      3. add AC-coupled smart-port PV into pv_total_power when enabled.

    Args:
        pg_sensors: Parallel group sensor dict (modified in place).
        gb_sensors: GridBOSS/MID device sensor dict.
        group_name: Parallel group name for debug logging.
        include_ac_couple: Whether AC-couple PV inclusion is enabled.
        recompute_consumption: Whether to recompute consumption_power from the
            energy balance (LOCAL path); the HTTP path keeps the cloud value.
    """
    apply_gridboss_overlay(pg_sensors, gb_sensors, group_name)
    if recompute_consumption:
        _recompute_consumption_from_balance(pg_sensors, group_name)
    apply_ac_couple_pv_adjustment(
        pg_sensors, gb_sensors, group_name, include_ac_couple=include_ac_couple
    )


def compute_total_inverter_power_kw(
    inverters: Any,
) -> float:
    """Sum the rated power (kW) of all inverters whose features have been detected.

    Used by both HTTP and LOCAL paths to propagate the total inverter power
    rating to GridBOSS/MID devices for energy delta and power canary scaling.

    Args:
        inverters: Iterable of inverter objects (BaseInverter instances).

    Returns:
        Total rated power in kW, or 0.0 if no ratings are available.
    """
    total_kw: float = 0.0
    for inv in inverters:
        inv_feat: Any = getattr(inv, "_features", None)
        if inv_feat is None:
            continue
        inv_model_info: Any = getattr(inv_feat, "model_info", None)
        if inv_model_info is None:
            continue
        dtc: int = getattr(inv_feat, "device_type_code", 0)
        kw: Any = inv_model_info.get_power_rating_kw(dtc)
        if isinstance(kw, (int, float)) and kw > 0:
            total_kw += kw
    return total_kw


def is_transport_link_down(device: Any) -> bool:
    """Check whether a device's attached local transport link is down.

    Duck-types pylxpweb's ``transport_link_down`` property (eg4-57g): the
    device must have a transport attached AND explicitly report the link
    as down.  The strict ``isinstance(..., bool)`` check keeps older
    pylxpweb versions (attribute missing -> default) and non-device
    objects from ever being treated as degraded.

    Args:
        device: BaseInverter or MIDDevice (or any object).

    Returns:
        True only when the device reports an attached-but-dead link.
    """
    if getattr(device, "transport", None) is None:
        return False
    link_down = getattr(device, "transport_link_down", False)
    return isinstance(link_down, bool) and link_down


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
        _failed_attach_serials: set[str]
        _last_attach_retry: float
        _last_degraded_cloud_refresh: dict[str, float]
        _local_parameters_loaded: bool
        _local_static_phase_done: bool
        _data_validation_enabled: bool
        _max_input_block_size: int
        _include_params_this_cycle: bool
        _last_available_state: bool
        _last_parameter_refresh: datetime | None
        _last_parameter_attempt: datetime | None
        _param_retry_pending: set[str]
        _param_retry_due: bool
        _param_completed_this_cycle: set[str]
        _param_attempted_this_cycle: bool
        _parameter_refresh_interval: timedelta
        _last_dst_sync: datetime | None
        _dst_sync_interval: timedelta
        _last_status_fetch: dict[str, float]
        # AC couple write-seed registry (GH #471): {serial: {store_key:
        # {"value": int|bool, "at": monotonic}}} — survives self.data
        # replacement so a mid-cycle write is not reverted; per-field
        # timestamps keep each key's seed lifecycle independent (round-2).
        _ac_couple_soc_seeds: dict[str, dict[str, dict[str, Any]]]
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
        def _get_device_grid_type(self, serial: str) -> str | None: ...
        async def _fetch_quick_charge_status(
            self, inverter: BaseInverter, target: dict[str, Any]
        ) -> None: ...
        async def is_quick_charge_active_live(self, serial: str) -> bool | None: ...
        async def _process_inverter_object(
            self, inverter: BaseInverter
        ) -> dict[str, Any]: ...
        async def _process_parallel_group_object(
            self, group: "ParallelGroup"
        ) -> dict[str, Any]: ...
        async def _process_mid_device_object(
            self, mid_device: "MIDDevice"
        ) -> dict[str, Any]: ...
        @staticmethod
        def _extract_inverter_features(
            inverter: BaseInverter,
        ) -> dict[str, Any]: ...
        def _extract_battery_from_object(self, battery: Battery) -> dict[str, Any]: ...
        @staticmethod
        def _filter_unused_smart_port_sensors(
            sensors: dict[str, Any], mid_device: "MIDDevice"
        ) -> None: ...
        @staticmethod
        def _calculate_gridboss_aggregates(
            sensors: dict[str, Any],
        ) -> None: ...

        # ── FirmwareUpdateMixin methods ──
        def _extract_firmware_update_info(
            self, device: "BaseInverter | MIDDevice"
        ) -> dict[str, Any] | None: ...

        # ── ParameterManagementMixin methods ──
        def _should_refresh_parameters(self) -> bool: ...
        async def _hourly_parameter_refresh(self) -> None: ...
        async def _refresh_device_parameters(self, serial: str) -> None: ...
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
            self, inverter: "BaseInverter", transport_type: str
        ) -> None: ...

        # ── Battery identity migration (#252, coordinator.py) ──
        _battery_key_migrations_done: set[tuple[str, str]]
        _battery_fallback_keys: dict[str, set[str]]
        _battery_noserial_polls: dict[str, dict[int, int]]
        _battery_migration_suppressed: set[str]
        _battery_shift_retire_logged: set[str]
        # ── Battery carry-forward (#258, coordinator.py) ──
        _battery_carry_forward: dict[str, dict[str, dict[str, Any]]]

        def _register_battery_key_migrations(
            self,
            inverter_serial: str,
            pairs: dict[str, str],
            active_keys: Collection[str],
        ) -> None: ...
        def _suppress_battery_migration(
            self, inverter_serial: str, reason: str, *, level: int = ...
        ) -> None: ...

        # ── LocalTransportMixin attributes ──
        _battery_rr_cache: dict[str, dict[str, dict[str, Any]]]
        _battery_serial_to_key: dict[str, dict[str, str]]
        _battery_next_index: dict[str, int]
        _shared_battery_logged: set[str]

        # ── Transport link health (eg4-57g) ──
        _link_down_notified: set[str]

        # ── LocalTransportMixin methods ──
        async def _attach_local_transports_to_station(self) -> None: ...
        async def _maybe_retry_failed_attaches(self) -> None: ...
        async def _ensure_local_transports(self) -> None: ...
        def _configure_attached_devices(self) -> list[Any]: ...
        def _sync_transport_link_state(
            self, processed: dict[str, Any] | None
        ) -> None: ...
        def _merge_round_robin_batteries(
            self,
            inverter_serial: str,
            transport_batteries: list["BatteryData"],
            reported_count: int | None = None,
        ) -> dict[str, dict[str, Any]]: ...

else:
    _MixinBase = object


# ===== Utility Functions =====


def _map_device_properties(
    device: "_DeviceObject", property_map: dict[str, str]
) -> dict[str, Any]:
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


def _bank_battery_count(bank: Any) -> int:
    """Return a battery bank's reported module count as an int (0 when absent).

    ``battery_count`` is reg 96 for a transport ``BatteryBankData`` and the
    cloud ``BatteryBank.battery_count`` property (parallel-count / totalNumber /
    battery-array length) for a cloud bank; both are None/0 for a device that
    owns no bank.  Returns 0 whenever the bank or its count is absent, None, or
    unreadable (cloud computed properties may raise on partial data) so callers
    can treat "no usable count" uniformly.
    """
    if bank is None:
        return 0
    try:
        raw = getattr(bank, "battery_count", None)
        return int(raw) if raw else 0
    except (TypeError, ValueError, AttributeError):
        return 0


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

    def _quick_charge_prefers_cloud(
        self, inverter: "BaseInverter", device_data: dict[str, Any]
    ) -> bool:
        """True when quick charge state/control must come from the cloud API.

        The EG4_OFFGRID family (12000XP/6000XP) firmware rejects holding
        register 233 with ILLEGAL DATA ADDRESS (issue #296) — the register
        pylxpweb's transport-preferring quick-charge paths read and write.
        A quick charge started via the cloud endpoint (the local-write
        fallback, and what the EG4 app reflects) is therefore invisible to
        the local read. When such a device has a transport attached AND a
        cloud client is available (HYBRID), bypass the transport and use the
        cloud getStatusInfo/start/stop endpoints directly. Fails closed
        (False) for every other family, cloud-only devices (whose pylxpweb
        paths already use the cloud), and LOCAL-only installs (no cloud to
        prefer).
        """
        return (
            is_offgrid_family(device_data)
            and self.client is not None
            and getattr(inverter, "transport", None) is not None
        )

    async def _read_offgrid_quick_charge_minute(
        self, inverter: "BaseInverter"
    ) -> int | None:
        """Best-effort local read of holding reg 234 (minutes) for offgrid HYBRID.

        The offgrid cloud-status route (#296) bypasses pylxpweb's reg 233+234
        detail read, but the Quick Charge Duration number mirrors — and its
        setter writes — reg 234 whenever a local transport is configured. So
        the register read is kept local here to keep the number's read and
        write sides pointing at the same truth. Only reg 233 is proven
        firmware-rejected on the XP; if reg 234 turns out equally unsupported
        this read fails and returns None, and the number falls back to the
        stored cloud-start preference (the setter's reg-234 write would then
        surface its own error).

        Skipped while the transport link is down: a raw ``read_parameters``
        on an attached-but-dead link is the multi-minute pymodbus hang class
        that Python 3.11's ``asyncio.wait_for`` cannot interrupt (pylxpweb's
        ``_fetch_parameters`` link-down guard does not cover raw transport
        reads like this one) — and this read fires on every 30s-throttled
        status poll, in exactly the HYBRID configuration where the link can
        be down. Degrades to None like a failed read.
        """
        transport = getattr(inverter, "transport", None)
        if transport is None:
            return None
        if is_transport_link_down(inverter):
            _LOGGER.debug(
                "Skipping reg 234 read for %s: local transport link is down "
                "(Quick Charge Duration falls back to the stored preference)",
                inverter.serial_number,
            )
            return None
        try:
            regs = await transport.read_parameters(234, 1)
            raw = regs.get(234)
            return int(raw) if raw is not None else None
        except Exception as e:
            _LOGGER.debug(
                "Could not read holding reg 234 for %s: %s (Quick Charge "
                "Duration falls back to the stored preference)",
                inverter.serial_number,
                e,
            )
            return None

    async def _read_quick_charge_status(
        self, inverter: "BaseInverter", device_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Read the live quick-charge status into the coordinator dict shape.

        Transport-aware via pylxpweb (cloud getStatusInfo; LOCAL/HYBRID
        registers 233/234), except for EG4_OFFGRID + HYBRID where register
        233 is firmware-rejected and the cloud endpoint is authoritative
        (#296). ``fetched_at`` (monotonic) records when the data was actually
        read so consumers can distinguish a fresh read from a carried-forward
        one. Returns None when the installed pylxpweb exposes no read method.
        """
        quick_charge_minute: int | None = None
        client = self.client
        if client is not None and self._quick_charge_prefers_cloud(
            inverter, device_data
        ):
            # Bound the cloud read: it shares the pylxpweb client's
            # station-wide retry/backoff state, and during a 502 storm an
            # escalated backoff sleep (up to ~60s) would otherwise hold a
            # coordinator slot for the whole storm. A timeout is a failed
            # read — the caller's carry-forward path handles it.
            status = await asyncio.wait_for(
                client.api.control.get_quick_charge_status(inverter.serial_number),
                timeout=QUICK_CHARGE_CLOUD_STATUS_TIMEOUT,
            )
            # Active flag from the cloud, duration register read locally so
            # the Duration number's read and write sides agree (#296 round 2).
            quick_charge_minute = await self._read_offgrid_quick_charge_minute(inverter)
        elif hasattr(inverter, "get_quick_charge_detail"):
            # Prefer the full detail (remaining time + task metadata);
            # version-guard for older pylxpweb exposing only the boolean.
            status = await inverter.get_quick_charge_detail()
            # Raw holding reg 234 (minutes); None on cloud. Lets the duration
            # number mirror the live register on LOCAL/HYBRID instead of a
            # stored preference. getattr guards older pylxpweb without it.
            quick_charge_minute = getattr(status, "quickChargeMinute", None)
        elif hasattr(inverter, "get_quick_charge_status"):
            return {
                "hasUnclosedQuickChargeTask": (
                    await inverter.get_quick_charge_status()
                ),
                "fetched_at": time.monotonic(),
            }
        else:
            return None
        return {
            "hasUnclosedQuickChargeTask": status.hasUnclosedQuickChargeTask,
            "remainTimeBeforeQuickChargeStop": (status.remainTimeBeforeQuickChargeStop),
            "unclosedQuickChargeTaskId": status.unclosedQuickChargeTaskId,
            "unclosedQuickChargeTaskStatus": status.unclosedQuickChargeTaskStatus,
            "quickChargeMinute": quick_charge_minute,
            "fetched_at": time.monotonic(),
        }

    def _carry_forward_quick_charge_status(
        self, serial: str, target: dict[str, Any]
    ) -> None:
        """Copy the previous cycle's quick-charge status into ``target``.

        The carried dict keeps its original ``fetched_at`` stamp, so consumers
        (the Quick Charge switch's post-write retention, #296) still see it as
        stale data rather than a fresh confirming read.
        """
        if self.data and serial in self.data.get("devices", {}):
            prev = self.data["devices"][serial].get("quick_charge_status")
            if prev is not None:
                target["quick_charge_status"] = prev

    async def _fetch_quick_charge_status(
        self, inverter: "BaseInverter", target: dict[str, Any]
    ) -> None:
        """Fetch + store ``quick_charge_status`` into ``target`` (throttled).

        Transport-aware via pylxpweb: cloud reads getStatusInfo; LOCAL/HYBRID
        reads registers 233 (active) + 234 (remaining minutes) — except the
        EG4_OFFGRID family in HYBRID, which reads the cloud endpoint because
        register 233 is firmware-rejected there (#296). Shared by the
        HTTP/HYBRID (`_process_inverter_object`) and LOCAL
        (`_process_single_local_device`) paths so the Quick Charge switch and
        remaining sensor work in every mode. Carries the previous value
        forward when the throttle window has not elapsed or the read failed
        (a transient error must not flip the switch to a lying OFF).
        """
        interval = 30  # seconds
        if not hasattr(self, "_last_status_fetch"):
            self._last_status_fetch = {}
        now = time.monotonic()
        serial = inverter.serial_number
        qc_key = f"qc_{serial}"
        if now - self._last_status_fetch.get(qc_key, 0.0) >= interval:
            try:
                status_dict = await self._read_quick_charge_status(inverter, target)
                if status_dict is not None:
                    target["quick_charge_status"] = status_dict
                self._last_status_fetch[qc_key] = now
                _LOGGER.debug(
                    "Quick charge status for %s: %s",
                    serial,
                    target.get("quick_charge_status"),
                )
            except Exception as e:
                self._last_status_fetch[qc_key] = now
                _LOGGER.debug(
                    "Could not fetch quick charge status for %s: %s", serial, e
                )
                self._carry_forward_quick_charge_status(serial, target)
        else:
            self._carry_forward_quick_charge_status(serial, target)

    def _carry_forward_last_event(self, serial: str, target: dict[str, Any]) -> None:
        """Copy the previous cycle's last-event data into ``target``.

        Keeps the Last Event sensor stable between throttled fetches and
        across transient cloud read failures (an event must not flicker to
        unknown because one poll failed). When no previous value exists the
        ``last_event`` sensor key is still published as None so the entity is
        created (state "unknown") on the first cycle.
        """
        prev_devices = (self.data or {}).get("devices", {})
        prev = prev_devices.get(serial, {})
        prev_sensors = prev.get("sensors", {})
        target["sensors"]["last_event"] = prev_sensors.get("last_event")
        target["last_event_detail"] = prev.get("last_event_detail")

    async def _fetch_last_event(self, serial: str, target: dict[str, Any]) -> None:
        """Fetch the newest portal event-log entry into ``target`` (throttled).

        CLOUD/HYBRID only (#327): some events exist ONLY in the portal's event
        log — transients between polls that the device pushes to the cloud
        out-of-band — so they never surface in the register-backed
        fault/warning sensors. Publishes:

        - ``target["sensors"]["last_event"]``: newest event text (state,
          truncated to HA's 255-char limit), or None when the device has no
          events yet.
        - ``target["last_event_detail"]``: normalized event dict (code, type,
          start/end time, status) consumed as sensor attributes.

        Throttled to EVENT_LOG_FETCH_INTERVAL (5-minute smart-cache tier).
        Inside the throttle window, or on a failed read OR parse, the previous
        cycle's value is carried forward. No-op (key not published, so no
        entity is created) without a cloud client or on a pylxpweb without
        the endpoint.

        The fetch AND the row parsing sit inside one exception boundary
        (whole-operation wrap, like _fetch_quick_charge_status): the row
        schema is effectively unvalidated upstream, and both call sites run
        under the outer per-device try/except in coordinator_http.py — an
        escaping parse error there replaces the whole device dict with an
        error stub, blanking EVERY sensor on the device for the cycle (and on
        the no-runtime-data path re-introducing the #256 offline-diagnostics
        regression class).
        """
        client = self.client
        if client is None:
            return
        fetch = getattr(getattr(client, "analytics", None), "get_event_list", None)
        if not callable(fetch):
            _LOGGER.debug(
                "pylxpweb analytics.get_event_list unavailable; "
                "skipping event log for %s",
                serial,
            )
            return

        if not hasattr(self, "_last_status_fetch"):
            self._last_status_fetch = {}
        now = time.monotonic()
        event_key = f"events_{serial}"
        # "Never fetched" is a None sentinel, NOT a 0.0 default:
        # time.monotonic() is host uptime on Linux, so on a freshly booted
        # host (HAOS reboot, container host, CI runner) `now` is smaller than
        # the interval and a 0.0 default would classify the FIRST-EVER fetch
        # as inside the throttle window — silently skipping the event log for
        # the first 5 minutes of uptime. Caught by CI (runner uptime < 5 min);
        # the sibling 30s quick-charge throttle masks the same pattern only
        # because no host reaches the fetch in under 30s of uptime.
        last_fetch = self._last_status_fetch.get(event_key)
        if last_fetch is not None and now - last_fetch < EVENT_LOG_FETCH_INTERVAL:
            self._carry_forward_last_event(serial, target)
            return

        try:
            response = await asyncio.wait_for(
                fetch(serial, rows=1), timeout=EVENT_LOG_CLOUD_TIMEOUT
            )
            rows = response.get("rows") or []
            had_rows = bool(rows)
            event = normalize_event_row(rows[0]) if had_rows else None
        except Exception as e:
            self._last_status_fetch[event_key] = now
            _LOGGER.debug("Could not fetch event log for %s: %s", serial, e)
            self._carry_forward_last_event(serial, target)
            return

        self._last_status_fetch[event_key] = now
        if had_rows and event is None:
            # Malformed (non-dict) row — a parse failure, not "no events":
            # keep the last good value rather than lying with unknown.
            _LOGGER.debug(
                "Malformed event row for %s; carrying previous event forward",
                serial,
            )
            self._carry_forward_last_event(serial, target)
            return
        if event is None:
            # No events for this device: state is unknown (None), never "".
            target["sensors"]["last_event"] = None
            target["last_event_detail"] = None
            return
        event_text = event.get("event_text")
        target["sensors"]["last_event"] = (
            event_text[:_MAX_STATE_LENGTH] if isinstance(event_text, str) else None
        )
        target["last_event_detail"] = event
        _LOGGER.debug("Last event for %s: %s", serial, event)

    async def is_quick_charge_active_live(self, serial: str) -> bool | None:
        """Return whether a quick charge is running *right now* for ``serial``.

        Reads the live enable state (LOCAL/HYBRID: holding register 233 bit 0;
        cloud: getStatusInfo) bypassing the throttled status cache. Callers that
        must act on the current state use this so a stale cached status — right
        after the Quick Charge switch toggles, or just after a charge auto-
        expires — does not mislead them. In particular the Quick Charge Duration
        write targets register 234, which the firmware only accepts while a
        charge is running; gating that write on this live read avoids both
        silently dropping a wanted write (stale-idle) and surfacing a rejected
        write (stale-active).

        Returns ``True``/``False`` for a *confirmed* live state. Returns
        ``None`` when the state cannot be determined (no inverter object, or the
        read failed): callers must treat ``None`` as "unknown" and surface it
        rather than silently assume idle, otherwise a live duration adjust that
        actually failed would be reported as success.
        """
        inverter = self.get_inverter_object(serial)
        if inverter is None:
            return None
        try:
            client = self.client
            device_data: dict[str, Any] = (
                (self.data or {}).get("devices", {}).get(serial, {})
            )
            if client is not None and self._quick_charge_prefers_cloud(
                inverter, device_data
            ):
                # EG4_OFFGRID + HYBRID: register 233 is firmware-rejected, so
                # the cloud getStatusInfo is the authoritative live state
                # (#296). Bounded like the throttled fetch — a backoff-stalled
                # cloud call must not hang the caller; timeout -> unknown.
                status = await asyncio.wait_for(
                    client.api.control.get_quick_charge_status(serial),
                    timeout=QUICK_CHARGE_CLOUD_STATUS_TIMEOUT,
                )
                return bool(status.hasUnclosedQuickChargeTask)
            if hasattr(inverter, "get_quick_charge_detail"):
                detail = await inverter.get_quick_charge_detail()
                return bool(detail.hasUnclosedQuickChargeTask)
            if hasattr(inverter, "get_quick_charge_status"):
                return bool(await inverter.get_quick_charge_status())
        except Exception as e:  # transport/cloud read failure -> unknown
            _LOGGER.debug(
                "Could not read live quick charge state for %s: %s", serial, e
            )
            return None
        return None  # neither read method available -> unknown

    def _carry_forward_ac_couple_soc(self, serial: str, target: dict[str, Any]) -> None:
        """Copy the previous cycle's AC couple SOC store into ``target``.

        The carried dict keeps its original ``fetched_at`` stamp so staleness
        stays visible; the throttle window and transient fetch failures must
        not blank the entities (quick-charge carry-forward precedent).
        """
        if self.data and serial in self.data.get("devices", {}):
            prev = self.data["devices"][serial].get("ac_couple_soc")
            if prev is not None:
                target["ac_couple_soc"] = self._overlay_ac_couple_seeds(serial, prev)

    def _overlay_ac_couple_seeds(
        self, serial: str, store: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-apply acknowledged-write seeds on top of a store dict.

        Closes the mid-cycle race (PR #471 review): a refresh cycle snapshots
        the store early (throttled carry-forward), so a write acknowledged
        while that cycle is in flight lands its ``note_ac_couple_soc_written``
        seed in the CURRENT ``self.data`` — which the cycle's stale snapshot
        then replaces on publish, silently reverting the UI until the next
        5-minute cloud read. The seed registry survives cycles; every carried
        store re-applies it here, and ``_fetch_ac_couple_soc`` clears it once
        a cloud read initiated after the write confirms. Identity is
        preserved when no seed is pending (the carried-dict staleness
        provenance and the existing identity assertions rely on that).

        A carry-forward cycle never initiated a cloud read, so every pending
        per-field seed still wins here (no timestamp comparison — that lives
        in the fetch path, which is the only place a fresh read can supersede
        a seed).
        """
        seeds = getattr(self, "_ac_couple_soc_seeds", {}).get(serial)
        if not seeds:
            return store
        merged = dict(store)
        latest = store.get("fetched_at") or 0.0
        for field, seed in seeds.items():
            merged[field] = seed["value"]
            latest = max(latest, seed["at"])
        merged["fetched_at"] = latest
        return merged

    async def _fetch_ac_couple_soc(
        self, inverter: "BaseInverter", target: dict[str, Any]
    ) -> None:
        """Fetch + store ``ac_couple_soc`` into ``target`` (throttled, cloud).

        The AC Couple Start/End SOC window (GH #352) is CLOUD-ONLY — the
        ``_12K_HOLD_AC_COUPLE_{START,END}_SOC`` holdParams have no pinned
        local register, so the parameter cache CANNOT serve them: with an
        attached local transport pylxpweb rebuilds ``inverter.parameters``
        from local register reads alone, wiping anything cloud-seeded there
        (PR #380 review P1). This dedicated device-data store is refreshed
        through pylxpweb's ``get_inverter_ac_couple_soc_limits`` on the
        5-minute tier — the periodic read is also what picks up portal-side
        edits in HYBRID — and carried forward between fetches and on
        failures. Values are whole percent ints, ``None`` when the device
        does not carry the param (models without AC couple support), and
        the END value 255 is the factory disabled/"never stop" sentinel.

        The store also carries ``enabled`` — the FUNC_AC_COUPLING_FUNCTION
        state backing the AC Couple switch (GH #471), same cloud-only
        rationale and same getter read. ``None`` when the param is absent
        or the installed pylxpweb getter predates it (< 0.9.39b3).
        """
        client = self.client
        if client is None:
            return  # pure-LOCAL: the params are unreachable by design
        getter = getattr(client.api.control, "get_inverter_ac_couple_soc_limits", None)
        if getter is None:
            return  # pylxpweb < 0.9.39b2
        if not hasattr(self, "_last_status_fetch"):
            self._last_status_fetch = {}
        serial = inverter.serial_number
        key = f"ac_couple_{serial}"
        now = time.monotonic()
        # "Never fetched" is a None sentinel, NOT a 0.0 default (the d66cc92
        # / #327-CI bug class): time.monotonic() is host uptime on Linux, so
        # on a freshly booted host (HAOS reboot, container host, CI runner)
        # `now` is smaller than the interval and a 0.0 default would classify
        # the FIRST-EVER fetch as inside the throttle window — silently
        # skipping the AC couple SOC read for the first 5 minutes of uptime.
        last_fetch = self._last_status_fetch.get(key)
        if last_fetch is not None and now - last_fetch < AC_COUPLE_SOC_FETCH_INTERVAL:
            self._carry_forward_ac_couple_soc(serial, target)
            return
        self._last_status_fetch[key] = now
        try:
            # Whole-operation boundary (PR #380 round-3 P2-1, matching
            # _fetch_quick_charge_status): result PARSING sits inside the
            # try too — an unexpected result shape must degrade to
            # carry-forward here, not escape to the per-device handler and
            # blank the whole inverter for the cycle (the #378 round-2 bug
            # class).
            limits: dict[str, int | bool | None] = await asyncio.wait_for(
                getter(serial), timeout=AC_COUPLE_SOC_FETCH_TIMEOUT
            )
            start_soc = limits.get("start_soc")
            end_soc = limits.get("end_soc")
            enabled = limits.get("enabled")
            if not isinstance(enabled, bool):
                # Absent key (pylxpweb < 0.9.39b3 getter) or unparseable —
                # never let a fake truthy/falsy value reach the switch.
                enabled = None
            prev = (
                self.data["devices"][serial].get("ac_couple_soc")
                if self.data and serial in self.data.get("devices", {})
                else None
            ) or {}
            if start_soc is None and end_soc is None and enabled is None:
                if (
                    prev.get("start_soc") is not None
                    or prev.get("end_soc") is not None
                    or prev.get("enabled") is not None
                ):
                    # An all-None read is indistinguishable from a total cloud
                    # range-read failure (pylxpweb's range gather swallows
                    # per-range errors and returns an empty dict) — never wipe
                    # known values on what may be a transient blip. Devices
                    # that genuinely lack the params never had values to keep.
                    # Deliberately NO staleness ceiling: a device whose params
                    # permanently vanished would pin the last-known values
                    # forever — accepted (the capability is static in
                    # practice); revisit if a real report shows otherwise.
                    target["ac_couple_soc"] = self._overlay_ac_couple_seeds(
                        serial, prev
                    )
                    return
            else:
                # Per-field carry-forward (PR #471 review, found independently
                # by two reviewers): a None FIELD on an otherwise-successful
                # read is likewise indistinguishable from a PARTIAL range-read
                # failure — the params' true registers are unpinned, so
                # same-range locality cannot be assumed and one range can fail
                # while another succeeds. A known value is never overwritten
                # with None; genuinely-lacking devices never had one to keep
                # (same static-capability trade as the all-None branch).
                if start_soc is None:
                    start_soc = prev.get("start_soc")
                if end_soc is None:
                    end_soc = prev.get("end_soc")
                if enabled is None:
                    prev_enabled = prev.get("enabled")
                    if isinstance(prev_enabled, bool):
                        enabled = prev_enabled
            store = {
                "start_soc": start_soc,
                "end_soc": end_soc,
                "enabled": enabled,
                "fetched_at": now,
            }
            # Acknowledged-write seeds, evaluated PER FIELD (round-2 review):
            # a field whose seed landed while this read was in flight (stamp
            # newer than the read's start) is newer device truth than the
            # read — apply it and keep the seed; a field whose read started
            # after its write supersedes that seed — drop just that field, so
            # a later write to a DIFFERENT key never renews this one and
            # clobbers a legitimate external change the read picked up.
            #
            # This timestamp-gated apply-or-clear is DELIBERATELY separate from
            # _overlay_ac_couple_seeds (used by the carry-forward paths), which
            # applies every pending seed unconditionally: only this path has a
            # fresh read to compare a seed against and thus to supersede it. Do
            # NOT merge the two into one helper (PR #471 review LOW).
            serial_seeds = getattr(self, "_ac_couple_soc_seeds", {}).get(serial)
            if serial_seeds:
                for field in list(serial_seeds):
                    if serial_seeds[field]["at"] > now:
                        store[field] = serial_seeds[field]["value"]
                    else:
                        del serial_seeds[field]
                if not serial_seeds:
                    self._ac_couple_soc_seeds.pop(serial, None)
            target["ac_couple_soc"] = store
            _LOGGER.debug(
                "AC couple SOC limits for %s: start=%s end=%s enabled=%s",
                serial,
                store["start_soc"],
                store["end_soc"],
                store["enabled"],
            )
        except Exception as e:
            _LOGGER.debug("Could not fetch AC couple SOC limits for %s: %s", serial, e)
            self._carry_forward_ac_couple_soc(serial, target)

    async def _poll_firmware_update_info(self, device: Any) -> dict[str, Any] | None:
        """Poll and extract firmware update information for a device.

        A transient refresh failure (network blip, or an unexpected API
        payload) must NOT blank the entity's in_progress/percentage mid-update:
        the device object caches its last firmware state, so we extract from it
        even when the refresh calls above raise. Otherwise an active firmware
        update would flicker to idle on any poll error (issue #353).
        """
        if not hasattr(device, "check_firmware_updates"):
            return None
        try:
            await device.check_firmware_updates()
            if hasattr(device, "get_firmware_update_progress"):
                await device.get_firmware_update_progress()
        except Exception as e:
            _LOGGER.debug(
                "Could not refresh firmware updates for %s (using last cached state): %s",
                device.serial_number,
                e,
            )
        # Extract from the device's cached state regardless of refresh outcome.
        return self._extract_firmware_update_info(device)

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
        firmware_update_info = await self._poll_firmware_update_info(inverter)

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
            # Operating State is a primary, always-present entity. Publish None
            # (HA "unknown") even with no runtime data so CLOUD/HYBRID create it
            # too (LOCAL always does via the static key set), rather than letting
            # it vanish for a no-data inverter (issue #262; #256 philosophy).
            processed["sensors"]["operating_state"] = None
            # Portal event log (#327) — fetched even without runtime data: an
            # offline/faulted inverter is exactly when the event log matters.
            await self._fetch_last_event(inverter.serial_number, processed)
            # AC couple SOC store (#352, PR #380 round-3 P2-2): cheap
            # no-network carry-forward so a no-data cycle does not blank the
            # entities (#256/#258 philosophy — transient blips must not wipe
            # last-known state). Unlike the event log there is nothing new to
            # learn from the cloud while the device is down that the next
            # healthy cycle's throttled fetch won't pick up.
            self._carry_forward_ac_couple_soc(inverter.serial_number, processed)
            return processed

        # Map inverter properties to sensor keys
        property_map = self._get_inverter_property_map()
        processed["sensors"] = _map_device_properties(inverter, property_map)

        # Friendly operating-state slug decoded from the status code (issue
        # #262). Shared decode -> identical to the LOCAL path. None (unknown
        # code / offline inverter) is published so the enum reads "unknown".
        processed["sensors"]["operating_state"] = operating_state_slug(
            processed["sensors"].get("status_code")
        )

        # The cloud zeroes its reg-170 mirror (pLoad170) for EG4_OFFGRID, so
        # the mapped output_power is a bogus 0 there unless the value came
        # from the local register — never publish that zero (eg4-9e4 / #197).
        drop_offgrid_cloud_output_power(
            processed["sensors"],
            features.get("inverter_family"),
            inverter.transport_runtime is not None,
        )

        # Load Energy (Eload, regs 171/172) — the inverter-served load.  This is
        # a SEPARATE meter from whole-home `consumption` (overridden below).
        # energy_today_usage/energy_lifetime_usage return the transport register
        # (LOCAL/HYBRID) or the cloud todayUsage/totalUsage (CLOUD) uniformly —
        # and both equal Eload per inverter.  getattr keeps this consistent with
        # _map_device_properties' defensive access.  See docs/DATA_MAPPING.md.
        processed["sensors"]["load_energy"] = getattr(
            inverter, "energy_today_usage", None
        )
        processed["sensors"]["load_energy_lifetime"] = getattr(
            inverter, "energy_lifetime_usage", None
        )

        # Override `consumption` with the energy balance when transport data is
        # present.  The property map above set `consumption` from
        # energy_today_usage (Eload, regs 171/172) — but Eload is the
        # inverter-served load, which omits grid-direct loads and so understates
        # whole-home consumption in a parallel/GridBOSS setup.  Energy balance
        # (pv + discharge + import − charge − export) is the whole-home figure and
        # mirrors how consumption_power is computed in pylxpweb.  (Eload itself is
        # still surfaced verbatim as `load_energy` above.)
        #
        # Note: GridBOSS uses a different aggregation strategy — CT summation
        # (L1 + L2) via _safe_sum() in MIDRuntimePropertiesMixin, not energy
        # balance.  See pylxpweb _mid_runtime_properties.py for details.
        if inverter.transport is not None:
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
        transport_runtime = inverter.transport_runtime
        if transport_runtime is not None:
            sensors = processed["sensors"]
            # Pairs defined at module level (_TRANSPORT_OVERLAY) so the
            # register contract harness can verify them against the
            # canonical register tables.
            for sensor_key, runtime_attr in _TRANSPORT_OVERLAY:
                value = getattr(transport_runtime, runtime_attr, None)
                if value is not None:
                    sensors[sensor_key] = value
            if (val := getattr(inverter, "total_load_power", None)) is not None:
                sensors["total_load_power"] = val
        elif features.get("inverter_family") == INVERTER_FAMILY_EG4_OFFGRID:
            # No transport runtime — pure CLOUD, or HYBRID inside a link-down
            # cloud-fallback window (#226). The off-grid family is the one
            # case where the cloud carries an authoritative load figure:
            # pylxpweb sums the epsLoadPower + smartLoadPower + gridLoadPower
            # split, so the Loads sensor stays honest instead of going
            # unknown mid-outage. Grid-tied families intentionally remain
            # transport-only here — their per-inverter cloud consumptionPower
            # is unreliable.
            if (val := getattr(inverter, "total_load_power", None)) is not None:
                processed["sensors"]["total_load_power"] = val

        # Carry the last-known fault/warning code forward across a HYBRID local
        # link-down (#261).  These codes are transport-exclusive (the cloud
        # getInverterRuntime response has no faultCode/warningCode field), so the
        # overlay above only sets them while the link is up.  When pylxpweb
        # clears _transport_runtime on a link-down the keys would otherwise
        # vanish and the Fault Code sensor flickers to "unknown" — while
        # cloud-backed Status Code stays alive — on every transient Modbus drop.
        # A status code is safe to hold: unlike a measurement a stale code is
        # more useful than a gap, and the true state can't be observed locally
        # during the outage anyway (the cloud carries no fault field).  Scoped to
        # the codes only; measurements stay honestly absent during an outage
        # (#226).  Gated on an ATTACHED transport so this is a HYBRID-only path —
        # pure CLOUD (no transport) never sets these codes, and the gate keeps
        # that a deliberate no-op rather than an incidental one.  The carry is
        # intentionally sticky for the whole outage (no expiry): the value is
        # the last live reading, other sensors (connection_transport, status)
        # already signal the link state, and reverting to unknown would just
        # reintroduce the flicker this fixes (codex review, risk-accepted #261).
        if transport_runtime is None and inverter.transport is not None:
            prev_devices = (self.data or {}).get("devices", {})
            prev_sensors = prev_devices.get(inverter.serial_number, {}).get(
                "sensors", {}
            )
            for code_key in ("fault_code", "warning_code"):
                if code_key not in processed["sensors"] and code_key in prev_sensors:
                    processed["sensors"][code_key] = prev_sensors[code_key]

        # Overlay transport-exclusive energy sensors (Modbus-only, regs 133-138).
        # Cloud API does not provide per-leg EPS energy; only available via Modbus.
        transport_energy = inverter.transport_energy
        if transport_energy is not None:
            sensors = processed["sensors"]
            # Pairs defined at module level (_ENERGY_OVERLAY) so the
            # register contract harness can verify them against the
            # canonical register tables.
            for sensor_key, energy_attr in _ENERGY_OVERLAY:
                value = getattr(transport_energy, energy_attr, None)
                if value is not None:
                    sensors[sensor_key] = value

        # Drop per-inverter grid per-leg voltage when it reads 0/None.  In
        # HYBRID it is only ever set by the transport overlay above (the cloud
        # API has no inverter grid L1/L2 field), and EG4 split-phase firmware
        # leaves regs 193/194 at 0 — see drop_dead_inverter_grid_legs (#243).
        drop_dead_inverter_grid_legs(processed["sensors"])

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
            # Alias R-phase voltages to common names for non-three-phase configs
            alias_common_voltage_sensors(processed["sensors"], features)

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

        # Process battery bank aggregate data.  (This path serves HYBRID and
        # pure CLOUD; LOCAL builds its bank in _process_single_local_device.)
        #
        # Prefer the live local transport bank in HYBRID and fall back to the
        # cloud bank when the transport count is 0/None.  The presence gate
        # is ``battery_count > 0`` so a genuine shared-battery secondary stays
        # skipped: in a parallel system the secondary reports 0 (cloud
        # totalNumber=0, local reg 96=0) because the CAN bus is wired only to
        # the primary, and a bank device with no batteries yields
        # Unknown/Unavailable entities (#169).
        #
        # BUT reg 96 (the transport ``battery_count``) is unreliable on
        # parallel/multi-battery systems and intermittently reads 0 even for a
        # real bank (#258/#170) — the #261 log shows ``reg 96 = 0`` while the
        # cloud reports 8 batteries.  When that happens, fall back to the cloud
        # bank (an independent source, unaffected by the flaky local Modbus
        # read) instead of dropping every battery_bank_* sensor and flicking the
        # aggregate entities to Unavailable.  A genuine secondary reports 0 on
        # BOTH sources and is still skipped.
        transport_battery = inverter.transport_battery
        cloud_battery_bank = getattr(inverter, "_battery_bank", None)
        transport_count = _bank_battery_count(transport_battery)
        cloud_count = _bank_battery_count(cloud_battery_bank)

        if transport_battery is not None and transport_count > 0:
            _LOGGER.debug(
                "Battery bank for %s: using LOCAL transport data "
                "(hybrid/local mode, battery_count=%d)",
                inverter.serial_number,
                transport_count,
            )
            try:
                processed["sensors"].update(
                    _build_battery_bank_sensor_mapping(transport_battery)
                )
            except Exception as e:
                _LOGGER.warning(
                    "Error extracting transport battery bank data for inverter %s: %s",
                    inverter.serial_number,
                    e,
                )
        elif cloud_count > 0:
            # Cloud-only mode, or HYBRID where the transport reg-96 count
            # flickered to 0/None while the cloud bank stayed populated (#261).
            _LOGGER.debug(
                "Battery bank for %s: using CLOUD data (battery_count=%d, "
                "transport reg-96 count=%d)",
                inverter.serial_number,
                cloud_count,
                transport_count,
            )
            try:
                processed["sensors"].update(
                    self._extract_battery_bank_from_object(cloud_battery_bank)
                )
            except Exception as e:
                _LOGGER.warning(
                    "Error extracting battery bank data for inverter %s: %s",
                    inverter.serial_number,
                    e,
                )
        else:
            _LOGGER.debug(
                "Battery bank for %s: skipping — no usable bank "
                "(transport count=%d, cloud count=%d, shared battery secondary)",
                inverter.serial_number,
                transport_count,
                cloud_count,
            )

        # Compute battery bank charge/discharge rate percentages.
        # At this point sensors dict has battery_bank_current (from battery
        # bank data) and max_charge_current / max_discharge_current (from
        # _map_device_properties).
        compute_bank_charge_rate(processed["sensors"])

        # Fetch quick charge and battery backup status with 30s throttle
        # These are cloud API calls that should not run every update cycle
        _STATUS_FETCH_INTERVAL = 30  # seconds
        if not hasattr(self, "_last_status_fetch"):
            self._last_status_fetch: dict[str, float] = {}
        now = time.monotonic()
        serial = inverter.serial_number

        # Quick charge status (shared cloud/local fetch; transport-aware).
        await self._fetch_quick_charge_status(inverter, processed)

        # Latest portal event-log entry (#327, cloud endpoint, 5-min throttle).
        await self._fetch_last_event(serial, processed)

        # AC Couple SOC window (GH #352): cloud-only dedicated store, 5-min
        # throttle — the parameter cache cannot carry these (no local
        # register), so this is the entities' single read source in both
        # CLOUD and HYBRID.
        await self._fetch_ac_couple_soc(inverter, processed)

        # Battery backup (EPS) status
        # Skip cloud API call when local transport is attached — the parameter
        # data from local Modbus already provides FUNC_EPS_EN which the switch
        # entity uses as a fallback. The cloud remoteRead endpoint frequently
        # returns apiBlocked anyway since the dongle relay is often busy.
        has_local_transport = inverter.transport is not None
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
            # power_output carries unified LOAD-OUTPUT semantics (eg4-9e4):
            # transport reg 170 (Pload) in HYBRID, cloud pLoad170 in CLOUD —
            # matching the LOCAL table's output_power (reg 170) exactly.
            "power_output": "output_power",
            "pv_total_power": "pv_total_power",
            "pv1_power": "pv1_power",
            "pv2_power": "pv2_power",
            "pv3_power": "pv3_power",
            # PV strings 4-6 (only present on >3-string models; absent on
            # residential inverters where the inverter property returns None)
            "pv4_power": "pv4_power",
            "pv5_power": "pv5_power",
            "pv6_power": "pv6_power",
            "battery_power": "battery_power",
            # Battery discharge power (cloud pDisCharge / transport reg 11) —
            # entity gated to EG4_OFFGRID via OFFGRID_ONLY_SENSORS (#197).
            "battery_discharge_power": "battery_discharge_power",
            "consumption_power": "consumption_power",
            "inverter_power": "ac_power",
            "rectifier_power": "rectifier_power",
            "ac_couple_power": "ac_couple_power",
            "generator_power": "generator_power",
            "eps_power": "eps_power",
            "eps_power_l1": "eps_power_l1",
            "eps_power_l2": "eps_power_l2",
            "eps_apparent_power_l1": "eps_apparent_power_l1",
            "eps_apparent_power_l2": "eps_apparent_power_l2",
            # Smart load (GEN port) + grid-side load split — cloud-only
            # smartLoadPower/gridLoadPower fields (#222), entities gated to
            # EG4_OFFGRID via OFFGRID_ONLY_SENSORS.  The pylxpweb properties
            # read the HTTP runtime even when a transport is attached, so
            # HYBRID gets them as cloud-supplemental data; pure LOCAL has no
            # source (no validated register) and never creates the keys.
            "smart_load_power": "smart_load_power",
            "grid_load_power": "grid_load_power",
            # EPS-loads subset of the backup output — cloud-only epsLoadPower
            # field, the third leg of the #222 split (consumption =
            # epsLoadPower + smartLoadPower + gridLoadPower).  NOT the same
            # quantity as eps_power/peps/pEpsL1N, which carry the COMBINED
            # backup output — the former eps_power_l1+l2 aliasing was a #197
            # coincidence (smart load idle) and produced duplicate sensors
            # (#335).  No per-leg epsLoad fields exist, and regs 129/130 are
            # the combined legs, so there is no LOCAL source (needs XP
            # hardware probing).  Same HYBRID cloud-supplemental behavior as
            # its siblings above.  Backed by the pylxpweb eps_load_power
            # property (>=0.9.36); no cloud runtime → None → key absent.
            "eps_load_power": "eps_load_power",
            # US split-phase per-leg power
            "inverter_power_l1": "inverter_power_l1",
            "inverter_power_l2": "inverter_power_l2",
            "rectifier_power_l1": "rectifier_power_l1",
            "rectifier_power_l2": "rectifier_power_l2",
            "grid_export_power_l1": "grid_export_power_l1",
            "grid_export_power_l2": "grid_export_power_l2",
            "grid_import_power_l1": "grid_import_power_l1",
            "grid_import_power_l2": "grid_import_power_l2",
            # Voltage sensors
            "pv1_voltage": "pv1_voltage",
            "pv2_voltage": "pv2_voltage",
            "pv3_voltage": "pv3_voltage",
            # PV strings 4-6 (only present on >3-string models)
            "pv4_voltage": "pv4_voltage",
            "pv5_voltage": "pv5_voltage",
            "pv6_voltage": "pv6_voltage",
            # PV string currents — DERIVED (power / voltage) by the inverter
            # property; no EG4 register or cloud field exists (issue #243).
            "pv1_current": "pv1_current",
            "pv2_current": "pv2_current",
            "pv3_current": "pv3_current",
            "pv4_current": "pv4_current",
            "pv5_current": "pv5_current",
            "pv6_current": "pv6_current",
            "battery_voltage": "battery_voltage",
            "grid_voltage_r": "grid_voltage_r",
            "grid_voltage_s": "grid_voltage_s",
            "grid_voltage_t": "grid_voltage_t",
            "eps_voltage_r": "eps_voltage_r",
            "eps_voltage_s": "eps_voltage_s",
            "eps_voltage_t": "eps_voltage_t",
            "generator_voltage": "generator_voltage",
            "generator_l1_voltage": "generator_voltage_l1",
            "generator_l2_voltage": "generator_voltage_l2",
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
            # NOTE: ``has_runtime_data`` is intentionally NOT mapped — it is the
            # same value as ``has_data`` (both: runtime or transport data
            # present) and mapping it created a duplicate "Has Runtime Data"
            # sensor (#253).
        }

    @staticmethod
    def _extract_inverter_features(inverter: "BaseInverter") -> dict[str, Any]:
        """Extract feature capabilities from a detected inverter object.

        Reads the pylxpweb ``InverterFeatures`` populated by ``detect_features()``
        and maps it to the integration feature dict via the shared
        :func:`_features_dict_from_inverter_features` mapper — the same mapper the
        static-data path (:func:`_features_from_family`) uses — so the live and
        static feature paths always agree for a given device.

        When detection resolved family=UNKNOWN (firmware reporting an unmapped
        HOLD_DEVICE_TYPE_CODE, e.g. 6000XP on ccaa-140A0A — issue #219), the
        feature profile is re-derived from the device model name via
        :func:`_apply_model_family_fallback` so split-phase sensors are not
        silently starved.

        Args:
            inverter: BaseInverter object with features detected.

        Returns:
            Feature dict for sensor filtering, or empty when features are absent.
        """
        inverter_features = getattr(inverter, "_features", None)
        if inverter_features is None:
            return {}
        features = _features_dict_from_inverter_features(inverter_features)
        return _apply_model_family_fallback(
            features,
            getattr(inverter, "model", None),
            getattr(inverter, "serial_number", None),
        )

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

        # Compute signed C-rate as percentage of capacity per hour.
        # Use _safe_float() to handle non-numeric values from mock objects.
        _write_charge_rate(
            sensors,
            "battery_charge_rate",
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
        """Extract sensor data from a CLOUD BatteryBank object.

        Thin wrapper over the shared :func:`build_battery_bank_sensors`
        (``source="cloud"``); retained as the CLOUD/HYBRID entry point used by
        the coordinator and tests.

        Args:
            battery_bank: BatteryBank object from pylxpweb.

        Returns:
            Dictionary of sensor_key -> value mappings.
        """
        return build_battery_bank_sensors(battery_bank, source="cloud")

    @staticmethod
    def _get_battery_bank_property_map() -> dict[str, str]:
        """Get battery bank property mapping dictionary.

        Derived from the canonical battery-bank field tables (see
        :func:`get_battery_bank_property_map`) so the cloud map cannot drift
        from the LOCAL sensor set.

        Returns:
            Dictionary mapping battery bank property names to sensor keys.
        """
        return get_battery_bank_property_map()

    async def _process_parallel_group_object(
        self, group: "ParallelGroup"
    ) -> dict[str, Any]:
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

        # Override consumption with energy balance when inverters have local
        # transport.  pylxpweb's _compute_energy_from_inverters() historically
        # summed load_energy_today (AC charge rectifier energy, reg 32) instead
        # of household consumption.  Energy balance is the correct formula.
        # This mirrors the individual inverter override at line ~507.
        # See: eg4_web_monitor issue #163
        if any(
            inv.transport_energy is not None for inv in getattr(group, "inverters", [])
        ):
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
            "battery_power": "parallel_battery_power",
            "battery_soc": "parallel_battery_soc",
            "battery_max_capacity": "parallel_battery_max_capacity",
            "battery_current_capacity": "parallel_battery_current_capacity",
            "battery_voltage": "parallel_battery_voltage",
            "battery_count": "parallel_battery_count",
        }

    async def _process_mid_device_object(
        self, mid_device: "MIDDevice"
    ) -> dict[str, Any]:
        """Process GridBOSS/MID device data from device object using properties.

        Args:
            mid_device: MIDDevice object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        model = getattr(mid_device, "model", "GridBOSS")
        firmware_version = getattr(mid_device, "firmware_version", "1.0.0")

        firmware_update_info = await self._poll_firmware_update_info(mid_device)

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
            processed["sensors"].update(
                _map_device_properties(
                    mid_device, self._get_mid_device_property_aliases()
                )
            )
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

        # Latest portal event-log entry (#327). GridBOSS/MID devices report
        # events too (live-validated 2026-07-15: eventType=MIDBOX_WARNING).
        await self._fetch_last_event(mid_device.serial_number, processed)

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
            "generator_frequency": "generator_frequency",
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
            # Smart Port Current sensors (Modbus regs 18-25, local-only)
            # Mapped as smart_load by default; filter remaps to ac_couple
            "smart_port1_l1_current": "smart_load1_current_l1",
            "smart_port1_l2_current": "smart_load1_current_l2",
            "smart_port2_l1_current": "smart_load2_current_l1",
            "smart_port2_l2_current": "smart_load2_current_l2",
            "smart_port3_l1_current": "smart_load3_current_l1",
            "smart_port3_l2_current": "smart_load3_current_l2",
            "smart_port4_l1_current": "smart_load4_current_l1",
            "smart_port4_l2_current": "smart_load4_current_l2",
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
    def _get_mid_device_property_aliases() -> dict[str, str]:
        """Get MID device property -> alias sensor key pairs.

        ``_get_mid_device_property_map()`` is keyed by property name, so a
        property that feeds a SECOND sensor key cannot be expressed there
        (the dict key would collide).  These pairs are applied after the
        main map in ``_process_mid_device_object()`` and mirror the aliases
        in the LOCAL table (``coordinator_mappings.
        _build_gridboss_sensor_mapping``) so both paths surface the same
        sensors (eg4-7uz).

        Returns:
            Dictionary mapping MID device property names to alias sensor keys
        """
        return {
            # Consumption power for GridBOSS = load_power (CT measurement)
            "load_power": "consumption_power",
        }

    @staticmethod
    def _filter_unused_smart_port_sensors(
        sensors: dict[str, Any], mid_device: "MIDDevice"
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

        Invalid status values (None, or outside 0-2 range) are logged as warnings.
        When a cache of known-good statuses exists, the cached values are used
        instead.  On the first poll with no cache, filtering is skipped (to avoid
        removing sensors that may be in use) but all status values are converted
        to valid labels (out-of-range values default to "unused") so raw integers
        never reach HA's enum validation.

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

        # Determine if this read is valid or corrupt.
        # A valid read has all values in range 0-2. All-zeros is valid (all
        # ports unused) and must NOT be rejected — doing so causes raw integer
        # 0 to leak through as the sensor state, which HA's enum validation
        # rejects with ValueError (fixes #195, re-landed for #248).
        serial = getattr(mid_device, "serial_number", "unknown")
        all_valid_range = all(
            s is not None and s in _SMART_PORT_STATUS_LABELS
            for s in smart_port_statuses.values()
        )
        is_good_read = bool(smart_port_statuses) and all_valid_range

        # Log invalid values from the raw read before any cache substitution
        if not is_good_read:
            raw_invalid: dict[int, int | None] = {
                p: s
                for p, s in smart_port_statuses.items()
                if s is None or s not in _SMART_PORT_STATUS_LABELS
            }
            if raw_invalid and serial not in _warned_smart_port_devices:
                _warned_smart_port_devices.add(serial)
                firmware = getattr(mid_device, "firmware_version", "unknown")
                has_transport = (
                    hasattr(mid_device, "_transport")
                    and mid_device.transport is not None
                )
                _LOGGER.warning(
                    "Invalid Smart Port status values detected for MID device %s "
                    "(firmware: %s, has_local_transport: %s). "
                    "Invalid ports: %s. Valid values are 0=Unused, 1=SmartLoad, 2=ACCouple. "
                    "This may indicate firmware that doesn't support these registers. "
                    "Please report this issue with your dongle firmware version.",
                    serial,
                    firmware,
                    has_transport,
                    raw_invalid,
                )

        if is_good_read:
            # Cache the validated statuses (is_good_read guarantees all non-None)
            _last_good_smart_port_statuses[serial] = {
                p: s for p, s in smart_port_statuses.items() if s is not None
            }
            if len(smart_port_statuses) == 4:
                # Per-cycle authority marker for the stale smart-port registry
                # cleanup (#217): only a FRESH and COMPLETE good read proves
                # the dynamic keys reflect the real port configuration.
                # Cached-fallback and suspect-skip cycles must not authorize
                # registry removal (codex r2 HIGH), nor partial reads where
                # some ports were never validated (codex r2 MEDIUM).
                sensors[SMART_PORT_VALIDATED_KEY] = True
        elif serial in _last_good_smart_port_statuses:
            # Corrupt read -- fall back to cached statuses
            _LOGGER.debug(
                "Smart Port status read looks corrupt (%s), using cached statuses: %s",
                smart_port_statuses,
                _last_good_smart_port_statuses[serial],
            )
            smart_port_statuses = {
                p: s for p, s in _last_good_smart_port_statuses[serial].items()
            }
        else:
            # No cache yet and current read is suspect -- skip filtering
            # to avoid removing sensors that may be in use.  Still convert
            # any in-range integers to string labels so raw ints never reach
            # HA's enum validation (defense-in-depth for #195/#248).
            _LOGGER.debug(
                "Smart Port statuses invalid with no cache — "
                "skipping sensor filtering on initial poll"
            )
            for port, status in smart_port_statuses.items():
                sensors[f"smart_port{port}_status"] = _SMART_PORT_STATUS_LABELS.get(
                    status if status is not None else -1, "unused"
                )
            return

        # Convert raw status integers to enum string labels
        for port, status in smart_port_statuses.items():
            if status is not None and status in _SMART_PORT_STATUS_LABELS:
                sensors[f"smart_port{port}_status"] = _SMART_PORT_STATUS_LABELS[status]

        sensors_to_remove: list[str] = []
        for port, status in smart_port_statuses.items():
            # Build per-port key groups for smart_load and ac_couple
            smart_load_keys = [
                f"smart_load{port}_power_l1",
                f"smart_load{port}_power_l2",
                f"smart_load{port}_power",
                f"smart_load{port}_current_l1",
                f"smart_load{port}_current_l2",
                f"smart_load{port}_today",
                f"smart_load{port}_total",
            ]
            ac_couple_keys = [
                f"ac_couple{port}_power_l1",
                f"ac_couple{port}_power_l2",
                f"ac_couple{port}_power",
                f"ac_couple{port}_current_l1",
                f"ac_couple{port}_current_l2",
                f"ac_couple{port}_today",
                f"ac_couple{port}_total",
            ]

            if status is None or status not in _SMART_PORT_STATUS_LABELS or status == 0:
                # Unused or invalid port - remove all sensors
                sensors_to_remove.extend(smart_load_keys)
                sensors_to_remove.extend(ac_couple_keys)
            elif status == 1:
                # Smart Load mode: ensure smart_load power keys exist,
                # remove ac_couple sensors (wrong type for this port)
                for key in smart_load_keys[:3]:  # power_l1, power_l2, power
                    sensors.setdefault(key, 0.0)
                sensors_to_remove.extend(ac_couple_keys)
            elif status == 2:
                # AC Couple mode: remap smart_load current → ac_couple current,
                # ensure ac_couple power keys exist,
                # remove smart_load sensors (wrong type for this port)
                for key in ac_couple_keys[:3]:  # power_l1, power_l2, power
                    sensors.setdefault(key, 0.0)
                # Remap current values from smart_load to ac_couple
                for phase in ("l1", "l2"):
                    val = sensors.pop(f"smart_load{port}_current_{phase}", None)
                    if val is not None:
                        sensors[f"ac_couple{port}_current_{phase}"] = val
                sensors_to_remove.extend(smart_load_keys)

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

        # Check if battery bank sensors exist AND battery_count > 0.
        # In shared-battery parallel systems, the secondary inverter has
        # battery_count=0 (no batteries directly connected).  We must not
        # create a battery bank device for it — doing so yields
        # Unknown/Unavailable entities (issue #169).
        has_battery_bank_data = any(
            key.startswith("battery_bank_") for key in sensors.keys()
        )
        if not has_battery_bank_data:
            return None

        battery_count = sensors.get("battery_bank_count") or 0
        if battery_count == 0:
            return None
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
            _LOGGER.debug(
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

            _LOGGER.debug(
                "Successfully refreshed parameters for %d/%d inverters",
                success_count,
                len(inverter_serials),
            )

        except Exception as e:
            _LOGGER.error("Error during all-device parameter refresh: %s", e)

    async def async_refresh_device_parameters(self, serial: str) -> bool:
        """Public method to refresh parameters for a specific device.

        Returns:
            True when the refresh completed; False when it failed. Errors
            are logged, never raised (#362): post-write callers must be able
            to distinguish "write+refresh ok" from "write ok, refresh
            failed" — the old swallow-and-return-None contract made a failed
            refresh indistinguishable from success, so entities cleared
            their optimistic state onto the stale pre-write cache value and
            visibly reverted a write the device had acknowledged.
        """
        try:
            _LOGGER.debug("Refreshing parameters for device %s", serial)
            await self._refresh_device_parameters(serial)
            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)
            return False
        return True

    async def _refresh_device_parameters(self, serial: str) -> None:
        """Refresh parameters for a specific device using device object.

        Link-down handling is delegated to pylxpweb's ``_fetch_parameters``
        guard (pylxpweb#206, shipped in the 0.9.36b24 floor pinned by
        manifest.json): while the local transport link is down it skips the
        local Modbus read (no uninterruptible pymodbus hang) and falls back
        to cloud named-parameter reads in HYBRID, or skips cleanly in LOCAL
        with ``parameters_complete`` set False.  Gating here would BLOCK
        that cloud fallback — in HYBRID with a dead link parameters could
        refresh via cloud but never would (#322 review).
        """
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
        """Perform hourly parameter refresh for all inverters.

        The throttle timestamp is stamped only when every inverter's last
        parameter fetch was COMPLETE (#282): a misrouted dongle response used
        to fail one register range, publish a partial parameter snapshot, and
        still arm the 60-minute throttle — leaving parameter-backed entities
        (e.g. System Charge SOC Limit, reg 227) degraded for up to an hour.
        An incomplete fetch now re-arms an early retry instead (rate-floored
        by ``_PARAMETER_RETRY_INTERVAL`` via ``_should_refresh_parameters``).
        """
        # Stamp the attempt at task START (#282 review P2): this runs as a
        # background task while update cycles continue every ~20-30 s, so a
        # slow in-flight refresh could otherwise be spawned a second time.
        # The attempt floor in _should_refresh_parameters blocks re-spawning
        # while this one runs (and after a crash, until the floor elapses).
        self._last_parameter_attempt = dt_util.utcnow()
        try:
            await self.refresh_all_device_parameters()
            self._last_parameter_attempt = dt_util.utcnow()
            if self._all_parameter_fetches_complete():
                self._last_parameter_refresh = dt_util.utcnow()
            else:
                _LOGGER.debug(
                    "Parameter refresh incomplete for at least one inverter; "
                    "serving last-known values and retrying in ~%d minutes "
                    "instead of waiting the full parameter interval",
                    int(_PARAMETER_RETRY_INTERVAL.total_seconds() // 60),
                )
        except Exception as e:
            _LOGGER.error("Error during hourly parameter refresh: %s", e)

    def _all_parameter_fetches_complete(self) -> bool:
        """True when every inverter's last parameter fetch read all ranges.

        Uses pylxpweb's ``parameters_complete`` flag; a pylxpweb without it
        (pre-#282) defaults to True, keeping the previous stamping behavior.
        """
        if not self.data or "devices" not in self.data:
            return True
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            inverter = self.get_inverter_object(serial)
            if inverter is not None and not getattr(
                inverter, "parameters_complete", True
            ):
                return False
        return True

    def _should_refresh_parameters(self) -> bool:
        """Check if the parameter refresh — or a post-failure retry — is due."""
        attempt = getattr(self, "_last_parameter_attempt", None)
        if (
            attempt is not None
            and dt_util.utcnow() - attempt < _PARAMETER_RETRY_INTERVAL
        ):
            # Rate floor between attempts: a failed read re-arms an early
            # retry (the refresh timestamp was not stamped), but never
            # tighter than this (#282).
            return False
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
            # detect_dst_status() returns the ACTUAL DST state for the
            # configured IANA timezone (True=DST in effect, False=not,
            # None=cannot determine). It says nothing about whether the
            # API flag matches — sync_dst_setting() performs that
            # comparison itself and no-ops when already correct.
            dst_status = self.station.detect_dst_status()
            if dst_status is None:
                _LOGGER.debug(
                    "DST status could not be determined for station %s",
                    self.plant_id,
                )
                self._last_dst_sync = dt_util.utcnow()
                return

            # Re-read the cloud-side DST flag before syncing.
            # sync_dst_setting() compares the detected status against the
            # CACHED daylight_saving_time flag, which is otherwise only set
            # at Station.load and by our own writes — without this refresh
            # a portal-side toggle would leave the cache (and the HA
            # switch) stale forever and turn the sync into a no-op. On
            # fetch failure, proceed with the cached value.
            try:
                self.station.daylight_saving_time = bool(
                    await self.station.get_daylight_saving_time_enabled()
                )
            except Exception as err:
                _LOGGER.debug(
                    "Could not refresh DST flag for station %s: %s",
                    self.plant_id,
                    err,
                )

            sync_result = await self.station.sync_dst_setting()
            if sync_result:
                _LOGGER.debug(
                    "DST setting verified/synchronized for station %s (actual DST: %s)",
                    self.plant_id,
                    dst_status,
                )
            else:
                _LOGGER.warning(
                    "Failed to synchronize DST setting for station %s",
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

        await self._disconnect_all_transports()

        if hasattr(self, "_debounced_refresh") and self._debounced_refresh:
            self._debounced_refresh.async_cancel()
            await asyncio.sleep(0)
            _LOGGER.debug("Cancelled debounced refresh")

        await self._cancel_background_tasks()
        _LOGGER.debug("All background tasks cancelled and cleaned up")

    async def async_shutdown(self) -> None:
        """Clean up transports, background tasks, and event listeners on shutdown.

        Transport disconnection happens FIRST so that any in-flight
        asyncio.gather() waiting on Modbus/dongle I/O unblocks immediately
        (closed socket raises an exception instead of waiting for timeout).
        Without this, options-change reloads time out because the
        DataUpdateCoordinator's refresh task can't complete.
        """
        # 1. Disconnect all transports to unblock in-flight I/O
        await self._disconnect_all_transports()

        # 2. Remove our homeassistant_stop event listener
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

        # 3. Cancel our background tasks (parameter loads, DST sync, etc.)
        await self._cancel_background_tasks()

        # 4. Call base class shutdown to set _shutdown_requested, unsub
        #    the refresh timer, and shut down the debounced refresh.
        await super().async_shutdown()  # type: ignore[misc]
        _LOGGER.debug("Coordinator shutdown complete, all background tasks cleaned up")

    async def _disconnect_all_transports(self) -> None:
        """Disconnect all active transports (legacy and cached).

        Covers three transport sources:
        1. Legacy single-device _modbus_transport / _dongle_transport
        2. Inverters in _inverter_cache (LOCAL/HYBRID mode)
        3. MID devices in _mid_device_cache (LOCAL/HYBRID mode)
        """
        # Legacy transports (old single-device config format)
        for attr in ("_modbus_transport", "_dongle_transport"):
            transport = getattr(self, attr, None)
            if transport is not None and getattr(transport, "is_connected", False):
                try:
                    await transport.disconnect()
                    _LOGGER.debug("Disconnected legacy transport %s", attr)
                except Exception:
                    _LOGGER.debug(
                        "Error disconnecting %s (ignored)", attr, exc_info=True
                    )

        # Cached inverter transports (LOCAL/HYBRID with local_transports config)
        for serial, inverter in self._inverter_cache.items():
            transport = inverter.transport
            if transport is not None and getattr(transport, "is_connected", False):
                try:
                    await transport.disconnect()
                    _LOGGER.debug("Disconnected transport for inverter %s", serial)
                except Exception:
                    _LOGGER.debug(
                        "Error disconnecting inverter %s transport (ignored)",
                        serial,
                        exc_info=True,
                    )

        # Cached MID device transports (GridBOSS in LOCAL/HYBRID mode)
        for serial, mid_device in self._mid_device_cache.items():
            transport = mid_device.transport
            if transport is not None and getattr(transport, "is_connected", False):
                try:
                    await transport.disconnect()
                    _LOGGER.debug("Disconnected transport for MID device %s", serial)
                except Exception:
                    _LOGGER.debug(
                        "Error disconnecting MID %s transport (ignored)",
                        serial,
                        exc_info=True,
                    )

        # Station-attached transports (HYBRID attach path). Devices attached
        # via Station.attach_local_transports() or the serial attach helper
        # are not guaranteed to appear in the caches above — notably MID
        # devices, since _rebuild_inverter_cache() only caches inverters —
        # which leaked open serial ports across reloads (#233). De-dup by
        # object identity so a transport shared with a cache entry closes once.
        station = getattr(self, "station", None)
        if station is not None:
            seen: set[int] = set()
            for cache in (self._inverter_cache, self._mid_device_cache):
                for cached in cache.values():
                    if cached.transport is not None:
                        seen.add(id(cached.transport))
            station_devices: list[Any] = list(
                getattr(station, "all_inverters", None) or []
            )
            station_devices.extend(getattr(station, "all_mid_devices", None) or [])
            for device in station_devices:
                transport = getattr(device, "transport", None)
                if (
                    transport is None
                    or id(transport) in seen
                    or not getattr(transport, "is_connected", False)
                ):
                    continue
                seen.add(id(transport))
                try:
                    await transport.disconnect()
                    _LOGGER.debug(
                        "Disconnected station transport for %s",
                        getattr(device, "serial_number", "?"),
                    )
                except Exception:
                    _LOGGER.debug(
                        "Error disconnecting station transport for %s (ignored)",
                        getattr(device, "serial_number", "?"),
                        exc_info=True,
                    )

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
        self, device: "BaseInverter | MIDDevice"
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
