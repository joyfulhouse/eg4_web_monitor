"""Sensor mapping functions and constants for the EG4 coordinator.

Pure data-transformation functions extracted from coordinator.py for
maintainability. These map pylxpweb transport/device objects to sensor
key dictionaries used by Home Assistant entities.
"""

import dataclasses
import inspect
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.util import dt as dt_util

from .const import (
    BLOCK_SIZE_CONSERVATIVE,
    BLOCK_SIZE_PRESET_REGISTERS,
    DEFAULT_MODBUS_UNIT_ID,
    GRID_TYPE_SINGLE_PHASE,
    GRID_TYPE_SPLIT_PHASE,
    GRID_TYPE_THREE_PHASE,
    INVERTER_FAMILY_DEFAULT_MODELS,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_LXP,
    LEGACY_FAMILY_MAP,
    MODEL_NAME_FAMILY_FALLBACK,
    operating_state_slug,
)

if TYPE_CHECKING:
    from pylxpweb.devices import Battery, BatteryBank, MIDDevice
    from pylxpweb.devices.inverters import InverterFeatures
    from pylxpweb.transports.data import (
        BatteryBankData,
        BatteryData,
        InverterEnergyData,
        InverterRuntimeData,
    )

_LOGGER = logging.getLogger(__name__)


def _compute_charge_rate(
    current: float | None,
    capacity_ah: float | None,
) -> float | None:
    """Compute signed C-rate from current and capacity.

    Positive = charging, negative = discharging.  For example, 11.6 A on
    a 280 Ah battery → 4.1 %/h; −11.6 A → −4.1 %/h.

    Args:
        current: Battery current in amps (positive = charging, negative = discharging).
        capacity_ah: Total battery capacity in amp-hours (Ah).

    Returns:
        Signed C-rate as %/h, or None if capacity is unavailable/zero.
    """
    if current is None or capacity_ah is None or capacity_ah <= 0:
        return None
    return current / capacity_ah * 100


def _safe_float(value: Any) -> float | None:
    """Coerce *value* to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_charge_rate(
    sensors: dict[str, Any],
    key: str,
    current: float | None,
    capacity_ah: float | None,
) -> None:
    """Compute signed C-rate and write rounded value into *sensors*.

    Calls ``_compute_charge_rate`` and writes non-None result rounded to
    2 decimal places.  Centralises the compute-and-store pattern used at
    bank, parallel-group, and individual-battery levels.
    """
    rate = _compute_charge_rate(current, capacity_ah)
    if rate is not None:
        sensors[key] = round(rate, 2)


def compute_bank_charge_rate(sensors: dict[str, Any]) -> None:
    """Compute battery bank signed C-rate from merged sensor dict.

    Reads ``battery_bank_current`` and ``battery_bank_full_capacity`` from
    *sensors* and writes ``battery_bank_charge_rate`` back as signed %/h
    (positive = charging, negative = discharging).

    Called from both LOCAL and HTTP coordinator paths after runtime and
    battery bank sensors have been merged.
    """
    _write_charge_rate(
        sensors,
        "battery_bank_charge_rate",
        _safe_float(sensors.get("battery_bank_current")),
        _safe_float(sensors.get("battery_bank_full_capacity")),
    )


def compute_parallel_group_charge_rate(
    group_sensors: dict[str, Any],
) -> None:
    """Compute parallel group signed C-rate from aggregated capacity.

    Reads ``parallel_battery_current`` and ``parallel_battery_max_capacity``
    from *group_sensors* and writes ``parallel_battery_charge_rate`` as
    signed %/h (positive = charging, negative = discharging).

    Called from both LOCAL and HTTP coordinator paths after parallel group
    sensors have been aggregated.
    """
    _write_charge_rate(
        group_sensors,
        "parallel_battery_charge_rate",
        _safe_float(group_sensors.get("parallel_battery_current")),
        _safe_float(group_sensors.get("parallel_battery_max_capacity")),
    )


def alias_common_voltage_sensors(
    sensors: dict[str, Any], features: dict[str, Any]
) -> None:
    """Alias R-phase voltage readings to phase-neutral names for non-three-phase.

    For single-phase and split-phase configurations, copies grid_voltage_r
    and eps_voltage_r to grid_voltage and eps_voltage respectively. Three-phase
    configurations use the R/S/T naming convention and skip this aliasing.

    Args:
        sensors: Mutable sensor dict to update.
        features: Feature flags dict (must contain "supports_three_phase").
    """
    if features.get("supports_three_phase", False):
        return
    if (v := sensors.get("grid_voltage_r")) is not None:
        sensors["grid_voltage"] = v
    if (v := sensors.get("eps_voltage_r")) is not None:
        sensors["eps_voltage"] = v


# NOTE (#335): the former apply_eps_load_power_sensors() helper (#197) that
# aliased eps_power_l1/l2 onto eps_load_power_l1/l2 and summed them into
# eps_load_power was DELETED.  Regs 129/130 / cloud pEpsL1N/pEpsL2N are the
# COMBINED backup-path output (smart load + EPS loads) — the #197 "sum matches
# cloud epsLoadPower" validation was a coincidence (smart load idle).  The
# eps_load_power_l1/l2 keys are retired (no per-leg EPS-load source exists on
# any path) and eps_load_power now maps the real cloud epsLoadPower field via
# the HTTP property map (cloud-only; see _get_inverter_property_map()).


# Families whose cloud pLoad170 mirror is trustworthy for output_power:
# EG4_HYBRID is live-verified (18kPV pLoad170=2395 / FlexBOSS21 2365,
# 2026-06-10) and LXP carries the canonical reg-170 pairing with no
# zeroing evidence.  EG4_OFFGRID is excluded (#197: the cloud zeroes the
# mirror), and so is UNKNOWN or any unrecognized family — the pylxpweb
# InverterFamily enum emits the truthy string "UNKNOWN" on failed
# detection, so membership in this allowlist (not a not-OFFGRID check)
# is the only safe test (codex r2 HIGH).
_CLOUD_PLOAD170_TRUSTED_FAMILIES: frozenset[str] = frozenset(
    {INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP}
)


def drop_offgrid_cloud_output_power(
    sensors: dict[str, Any],
    inverter_family: str | None,
    has_transport_runtime: bool,
) -> None:
    """Drop cloud-sourced ``output_power`` unless its mirror is trusted.

    ``output_power`` carries reg-170 load-output semantics on every path,
    but the cloud ZEROES its reg-170 mirror (``pLoad170``) for EG4_OFFGRID
    models (12000XP/6000XP, issue #197).  Without transport runtime the
    cloud-mapped value is that bogus zero — remove the key rather than
    publish a false 0 W load.  Fail-closed like the #197 entity gate in
    sensor.py: the value survives only when it came from the local register
    (transport runtime present) or the family is in the positively-known
    trusted allowlist.  A transiently unknown family costs one cycle of
    the sensor on cloud-connected EG4_HYBRID/LXP systems; the alternative
    is corrupt data on EG4_OFFGRID.

    Called from the cloud/hybrid device processing path only — the LOCAL
    mapping reads reg 170 directly, which is always genuine.

    Args:
        sensors: Mutable sensor dict to update.
        inverter_family: Detected family string, or None when unknown.
        has_transport_runtime: True when Modbus transport runtime backs the
            mapped value (pylxpweb ``power_output`` prefers the transport).
    """
    if has_transport_runtime:
        return
    if inverter_family in _CLOUD_PLOAD170_TRUSTED_FAMILIES:
        return
    sensors.pop("output_power", None)


# Sensor keys that stay populated while the cloud reports the inverter lost
# (dongle link down, ``lost=true``).  Everything else is a measurement mirror
# the portal keeps serving frozen at its pre-outage value, so it is blanked to
# None (HA "unknown") instead — see blank_lost_inverter_measurements (#479).
LOST_KEEP_SENSOR_KEYS: frozenset[str] = frozenset(
    {
        # Device identity / capability diagnostics — static, never stale.
        "firmware_version",
        "has_data",
        "inverter_family",
        "device_type_code",
        "grid_type",
        # Static ratings — never stale ("12kW" cannot age out).
        "power_rating",
        "inverter_power_rating",
        # Status: the cloud's own "offline" verdict is the one fresh datum,
        # and inverter_lost_status IS the Connection Lost entity — blanking
        # it would read "unknown" at the exact moment it must read lost.
        "status_text",
        "operating_state",
        "inverter_lost_status",
        # Fault/warning codes are sticky by design across outages (#261):
        # a stale code beats a gap and cannot be observed while down.
        "fault_code",
        "warning_code",
        # Honest poll timestamp, not a measurement.
        "battery_bank_last_polled",
    }
)

# Individual-battery keys that stay populated while the parent inverter is
# cloud-lost: identity/spec metadata and the freshness timestamps.  Every
# other key is a measurement mirror frozen by the portal — blanked to None
# by blank_lost_battery_measurements (#479).
LOST_KEEP_BATTERY_KEYS: frozenset[str] = frozenset(
    {
        "battery_serial_number",
        "battery_index",
        "battery_model",
        "battery_bms_model",
        "battery_type",
        "battery_type_text",
        "battery_firmware_version",
        # Design capacity is a spec, not a reading.
        "battery_design_capacity",
        # Freshness timestamps are data about the poll, not measurements.
        "battery_last_seen",
        "battery_last_polled",
    }
)

# Cloud-supplemental sensors that keep reading the HTTP runtime even when a
# local transport is attached (the #222 load split has no local register).
# In HYBRID with a live transport the inverter is NOT lost, but a lost cloud
# mirror still freezes exactly these keys — they are blanked separately.
CLOUD_SUPPLEMENTAL_LOST_KEYS: frozenset[str] = frozenset(
    {
        "smart_load_power",
        "grid_load_power",
        "eps_load_power",
    }
)


def blank_lost_battery_measurements(battery_sensors: dict[str, Any]) -> None:
    """Blank one battery's measurement values for a cloud-lost parent (#479).

    Same portal behavior one level down from the inverter: getBatteryInfo
    keeps mirroring the pre-outage per-module voltage/current/SoC/cell data
    while the dongle is offline, and the #258 carry-forward would otherwise
    republish it verbatim.  Values go to None (HA "unknown"); keys stay
    present so the battery entities remain available rather than vanishing.
    """
    for key in battery_sensors:
        if key not in LOST_KEEP_BATTERY_KEYS:
            battery_sensors[key] = None


def blank_lost_inverter_measurements(processed: dict[str, Any]) -> None:
    """Blank measurement sensors for a cloud-lost inverter (issue #479).

    When the dongle loses its internet link the portal keeps answering with
    ``success:true`` and the last register mirror it received, flagged only by
    ``lost:true`` — so without this gate every runtime/energy sensor freezes
    at its pre-outage value for the whole outage.  Publish None (HA "unknown")
    for the measurements instead, keeping the diagnostic/status keys
    (``status_text`` reads "offline", the Lost binary sensor reads on) so the
    device stays present and clearly reports the outage rather than blacking
    out (#256 philosophy: present-but-unknown).

    No grace period is needed: the cloud only raises ``lost`` after its own
    multi-minute reporting timeout, and pylxpweb's ``is_lost`` already returns
    False whenever live local transport data is attached (HYBRID stays on the
    local readings).

    Args:
        processed: The per-device dict under construction; ``sensors`` and
            ``binary_sensors`` are mutated in place.
    """
    sensors = processed["sensors"]
    for key in sensors:
        if key not in LOST_KEEP_SENSOR_KEYS:
            sensors[key] = None
    binary_sensors = processed["binary_sensors"]
    for key in binary_sensors:
        if key != "is_lost":
            binary_sensors[key] = None


# ---------------------------------------------------------------------------
# Static sensor key sets — extracted from the mapping function dicts below.
# Used by _build_static_local_data() for immediate entity creation during
# the first coordinator refresh so that HA doesn't wait for Modbus reads.
# ---------------------------------------------------------------------------
INVERTER_RUNTIME_KEYS: frozenset[str] = frozenset(
    {
        "pv1_voltage",
        "pv1_power",
        "pv2_voltage",
        "pv2_power",
        "pv3_voltage",
        "pv3_power",
        # PV strings 4-6 (MPPT 4-6) — only materialized for models whose
        # pv_string_count >= 4/5/6 (gated by _should_create_sensor).  Present
        # in the static set so the count-driven entities and parity checks see
        # them; 3-string models simply never create or populate them.
        "pv4_voltage",
        "pv4_power",
        "pv5_voltage",
        "pv5_power",
        "pv6_voltage",
        "pv6_power",
        "pv_total_power",
        # Per-string PV currents — DERIVED (power / voltage), gated by
        # pv_string_count like the voltage/power keys above (issue #243).
        "pv1_current",
        "pv2_current",
        "pv3_current",
        "pv4_current",
        "pv5_current",
        "pv6_current",
        "battery_voltage",
        "battery_current",
        "state_of_charge",
        "battery_temperature",
        "grid_voltage_r",
        "grid_voltage_s",
        "grid_voltage_t",
        "grid_voltage_l1",
        "grid_voltage_l2",
        "grid_frequency",
        "grid_power",
        "grid_export_power",
        "ac_power",
        "power_factor",
        "eps_voltage_r",
        "eps_voltage_s",
        "eps_voltage_t",
        "eps_voltage_l1",
        "eps_voltage_l2",
        "eps_frequency",
        "eps_power",
        "output_power",
        "generator_voltage",
        "generator_frequency",
        "generator_power",
        "bus1_voltage",
        "bus2_voltage",
        "internal_temperature",
        "radiator1_temperature",
        "radiator2_temperature",
        "bt_temperature",
        "status_code",
        # Friendly decode of status_code (issue #262); same value all modes.
        "operating_state",
        # Inverter fault/warning codes (regs 60-61 / 62-63, 32-bit bitfields;
        # BMS code merged in as fallback by pylxpweb).  LOCAL/HYBRID only —
        # the cloud runtime endpoint has no faultCode/warningCode (eg4-23a6).
        "fault_code",
        "warning_code",
        "grid_current_l1",
        "grid_current_l2",
        "grid_current_l3",
        "max_charge_current",
        "max_discharge_current",
        # EPS per-leg (split-phase, regs 129-132)
        "eps_power_l1",
        "eps_power_l2",
        "eps_apparent_power_l1",
        "eps_apparent_power_l2",
        # EG4_OFFGRID confirmed registers (issue #197): load power (reg 170)
        # and battery discharge power (reg 11).  Entity creation is
        # family-gated via OFFGRID_ONLY_SENSORS in sensor.py.
        # NOTE (#335): eps_load_power is NOT here — it is a CLOUD-ONLY sensor
        # (cloud epsLoadPower field) like smart_load_power/grid_load_power;
        # regs 129/130 carry the COMBINED backup output (eps_power_l1/l2
        # above), and no local register for the EPS-loads subset is known
        # (needs XP hardware probing).  The former eps_load_power_l1/l2
        # aliases were retired for the same reason.
        "load_power",
        "battery_discharge_power",
        # US split-phase per-leg power (regs 195-204)
        "inverter_power_l1",
        "inverter_power_l2",
        "rectifier_power_l1",
        "rectifier_power_l2",
        "grid_export_power_l1",
        "grid_export_power_l2",
        "grid_import_power_l1",
        "grid_import_power_l2",
        "generator_voltage_l1",
        "generator_voltage_l2",
    }
)

INVERTER_ENERGY_KEYS: frozenset[str] = frozenset(
    {
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
        # Load Energy (Eload, regs 171/172) — per-inverter served load.  NOT
        # added to PARALLEL_GROUP_SENSOR_KEYS: it is inverter-scoped only (the
        # group carries whole-home `consumption`).
        "load_energy",
        "load_energy_lifetime",
        # EPS per-leg energy (split-phase, regs 133-138)
        "eps_energy_today_l1",
        "eps_energy_today_l2",
        "eps_energy_total_l1",
        "eps_energy_total_l2",
        # Granular per-string / per-component energy (regs 28-37 / 40+),
        # disabled-by-default, LOCAL/HYBRID only.
        "pv1_yield",
        "pv2_yield",
        "pv3_yield",
        "pv4_yield",
        "pv5_yield",
        "pv6_yield",
        "pv1_yield_lifetime",
        "pv2_yield_lifetime",
        "pv3_yield_lifetime",
        "pv4_yield_lifetime",
        "pv5_yield_lifetime",
        "pv6_yield_lifetime",
        "inverter_energy",
        "inverter_energy_lifetime",
        "ac_charge_energy",
        "ac_charge_energy_lifetime",
        "eps_energy",
        "eps_energy_lifetime",
        "generator_energy",
        "generator_energy_lifetime",
    }
)

BATTERY_BANK_CORE_KEYS: frozenset[str] = frozenset(
    {
        "battery_bank_soc",
        "battery_bank_voltage",
        "battery_bank_current",
        "battery_bank_power",
        "battery_bank_max_capacity",
        "battery_bank_current_capacity",
        "battery_bank_remain_capacity",
        "battery_bank_full_capacity",
        "battery_bank_capacity_percent",
        "battery_bank_count",
        "battery_bank_status",
        "battery_status",
        "battery_bank_last_polled",
        # Bank-level BMS register data (always available, no CAN bus needed):
        "battery_bank_min_soh",  # reg 5 SOH (fallback when no individual batteries)
        "battery_bank_cycle_count",  # reg 106
        "battery_bank_max_cell_temp",  # reg 103
        "battery_bank_min_cell_temp",  # reg 104
        "battery_bank_temp_delta",  # reg 103-104
        "battery_bank_cell_voltage_delta_max",  # reg 101-102
        "battery_bank_min_cell_voltage",  # reg 102
        "battery_bank_bms_charge_current_limit",  # reg 81
        "battery_bank_bms_discharge_current_limit",  # reg 82
        "battery_bank_bms_charge_voltage_ref",  # reg 83
        "battery_bank_bms_discharge_cutoff",  # reg 84
        "battery_bank_bms_battery_type",  # reg 80
        "battery_bank_voltage_inv_sample",  # reg 107
        "battery_bank_charge_rate",
        # BMS permission/request flags (reg 95 bitmap / cloud bmsCharge, #232).
        # Enum states; available in both LOCAL and CLOUD via the parent inverter.
        "battery_bank_charge_allowed",  # reg 95 bit 0x01 / bmsCharge
        "battery_bank_discharge_allowed",  # reg 95 bit 0x02 / bmsDischarge
        "battery_bank_force_charge",  # reg 95 bit 0x20 / bmsForceCharge
    }
)

BATTERY_BANK_CAN_DIAGNOSTIC_KEYS: frozenset[str] = frozenset(
    {
        # Cross-battery diagnostics that require individual battery data from
        # CAN bus registers (5002+).  These are only added dynamically when
        # BatteryBankData.batteries contains real data — never pre-created
        # statically, so entities won't exist when CAN data is unavailable.
        "battery_bank_soc_delta",
        "battery_bank_soh_delta",
        "battery_bank_voltage_delta",
        "battery_bank_cycle_count_delta",
    }
)

BATTERY_BANK_KEYS: frozenset[str] = (
    BATTERY_BANK_CORE_KEYS | BATTERY_BANK_CAN_DIAGNOSTIC_KEYS
)

INVERTER_COMPUTED_KEYS: frozenset[str] = frozenset(
    {
        "consumption_power",
        "total_load_power",
        "battery_power",
        "rectifier_power",
        "grid_import_power",
        "grid_voltage",
        "eps_voltage",
    }
)

INVERTER_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "firmware_version",
        "connection_transport",
        "transport_host",
        "last_polled",
    }
)

ALL_INVERTER_SENSOR_KEYS: frozenset[str] = (
    INVERTER_RUNTIME_KEYS
    | INVERTER_ENERGY_KEYS
    | BATTERY_BANK_CORE_KEYS
    | INVERTER_COMPUTED_KEYS
    | INVERTER_METADATA_KEYS
)

GRIDBOSS_SENSOR_KEYS: frozenset[str] = frozenset(
    {
        "grid_power",
        "grid_voltage",
        "frequency",
        "grid_power_l1",
        "grid_power_l2",
        "grid_voltage_l1",
        "grid_voltage_l2",
        "grid_current_l1",
        "grid_current_l2",
        "ups_power",
        "ups_voltage",
        "ups_power_l1",
        "ups_power_l2",
        "load_voltage_l1",
        "load_voltage_l2",
        "ups_current_l1",
        "ups_current_l2",
        "load_power",
        "load_power_l1",
        "load_power_l2",
        "load_current_l1",
        "load_current_l2",
        "consumption_power",
        "generator_power",
        "generator_voltage",
        "generator_frequency",
        "generator_power_l1",
        "generator_power_l2",
        "generator_current_l1",
        "generator_current_l2",
        "generator_voltage_l1",
        "generator_voltage_l2",
        "hybrid_power",
        "phase_lock_frequency",
        "off_grid",
        "smart_load1_power_l1",
        "smart_load1_power_l2",
        "smart_load2_power_l1",
        "smart_load2_power_l2",
        "smart_load3_power_l1",
        "smart_load3_power_l2",
        "smart_load4_power_l1",
        "smart_load4_power_l2",
        "ac_couple1_power_l1",
        "ac_couple1_power_l2",
        "ac_couple2_power_l1",
        "ac_couple2_power_l2",
        "ac_couple3_power_l1",
        "ac_couple3_power_l2",
        "ac_couple4_power_l1",
        "ac_couple4_power_l2",
        "ups_today",
        "ups_total",
        "grid_export_today",
        "grid_export_total",
        "grid_import_today",
        "grid_import_total",
        "load_today",
        "load_total",
        "ac_couple1_today",
        "ac_couple1_total",
        "ac_couple2_today",
        "ac_couple2_total",
        "ac_couple3_today",
        "ac_couple3_total",
        "ac_couple4_today",
        "ac_couple4_total",
        "smart_load1_today",
        "smart_load1_total",
        "smart_load2_today",
        "smart_load2_total",
        "smart_load3_today",
        "smart_load3_total",
        "smart_load4_today",
        "smart_load4_total",
        "firmware_version",
        "connection_transport",
        "transport_host",
        "midbox_last_polled",
    }
)

# Smart port status keys (smart_port{1-4}_status).  Written into the GridBOSS
# sensors dict by _filter_unused_smart_port_sensors() on every successful real
# poll — including its skip-filtering path for invalid statuses — but never
# present in the static first-refresh placeholder data.
SMART_PORT_STATUS_KEYS: frozenset[str] = frozenset(
    f"smart_port{port}_status" for port in range(1, 5)
)

# Per-cycle authority marker for the stale smart-port registry cleanup in
# __init__.py (#217).  _filter_unused_smart_port_sensors() writes it ONLY when
# the current cycle had a fresh, complete good status read (all 4 ports
# present and in range 0-2).  Static placeholder data, suspect-skip cycles,
# cached-fallback cycles, and partial reads never carry it — the cleanup must
# not remove registry entries based on any of those (codex r1 HIGH, r2
# HIGH/MEDIUM: stale session caches and partial reads are not proof that the
# dynamic power/energy keys reflect the real port configuration).
SMART_PORT_VALIDATED_KEY = "smart_port_statuses_validated"

# Keys that live in the coordinator sensors dict but must NOT become HA sensor
# entities.  They are read by select entities and internal coordinator logic,
# but are excluded from both the static entity-creation path and the
# late-registration listener in sensor.py.
GRIDBOSS_COORDINATOR_INTERNAL_KEYS: frozenset[str] = SMART_PORT_STATUS_KEYS | {
    SMART_PORT_VALIDATED_KEY
}

# Smart port keys that should NOT be included in static entity creation.
# These are dynamically added by _filter_unused_smart_port_sensors() based on
# actual port status, so only active ports get entities.
# Includes per-port L1/L2 power keys, per-port aggregate power keys (computed by
# _calculate_gridboss_aggregates from L1+L2), total aggregates, and per-port
# energy keys (today/total).
GRIDBOSS_SMART_PORT_DYNAMIC_KEYS: frozenset[str] = frozenset(
    [
        f"{prefix}{port}_{suffix}"
        for prefix in ("smart_load", "ac_couple")
        for port in range(1, 5)
        for suffix in (
            "power_l1",
            "power_l2",
            "power",
            "current_l1",
            "current_l2",
            "today",
            "total",
        )
    ]
    + ["smart_load_power", "ac_couple_power"]
)

# Keys used for static GridBOSS entity creation: everything in GRIDBOSS_SENSOR_KEYS
# except keys that are added dynamically after the first real poll (smart port power /
# energy) and keys that are coordinator-internal (smart_port*_status).
GRIDBOSS_STATIC_ENTITY_KEYS: frozenset[str] = (
    GRIDBOSS_SENSOR_KEYS
    - GRIDBOSS_SMART_PORT_DYNAMIC_KEYS
    - GRIDBOSS_COORDINATOR_INTERNAL_KEYS
)

PARALLEL_GROUP_SENSOR_KEYS: frozenset[str] = frozenset(
    {
        # Power sensors (from inverter summing)
        "pv_total_power",
        "grid_power",
        "grid_import_power",
        "grid_export_power",
        "consumption_power",
        "eps_power",
        "ac_power",
        "output_power",
        # Energy sensors (today)
        "yield",
        "charging",
        "discharging",
        "grid_import",
        "grid_export",
        "consumption",
        # Energy sensors (lifetime)
        "yield_lifetime",
        "charging_lifetime",
        "discharging_lifetime",
        "grid_import_lifetime",
        "grid_export_lifetime",
        "consumption_lifetime",
        # Battery aggregate sensors (remapped to parallel_battery_* prefix)
        "parallel_battery_power",
        "parallel_battery_soc",
        "parallel_battery_max_capacity",
        "parallel_battery_current_capacity",
        "parallel_battery_voltage",
        "parallel_battery_current",
        "parallel_battery_charge_rate",
        "parallel_battery_count",
        # Grid voltage (from primary/master inverter — same grid, no averaging)
        "grid_voltage_l1",
        "grid_voltage_l2",
        # Timestamp
        "parallel_group_last_polled",
    }
)

# Additional keys populated when a GridBOSS overlays data onto a parallel group.
# These come from the GridBOSS CT measurements (grid/load per-phase) and are
# only added to parallel groups when a GridBOSS device is present.
PARALLEL_GROUP_GRIDBOSS_KEYS: frozenset[str] = frozenset(
    {
        "grid_power_l1",
        "grid_power_l2",
        "load_power",
        "load_power_l1",
        "load_power_l2",
    }
)


def _build_runtime_sensor_mapping(
    runtime_data: "InverterRuntimeData",
) -> dict[str, Any]:
    """Build sensor mapping from runtime data object.

    This helper extracts runtime data from a transport's RuntimeData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Args:
        runtime_data: RuntimeData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    # Net grid flow (eg4-9wf): grid_power = import − export (positive = import),
    # from regs 27/26 (power_to_user/power_to_grid) — the same formula the
    # CLOUD path computes in _process_inverter_object and the GridBOSS sign
    # convention.  Reg 17 (Prec) is RECTIFIER power and feeds the separate
    # rectifier_power sensor; it must never masquerade as grid power.
    grid_import = runtime_data.power_from_grid
    grid_export = runtime_data.power_to_grid
    net_grid_power = (
        grid_import - grid_export
        if grid_import is not None and grid_export is not None
        else None
    )
    mapping: dict[str, Any] = {
        # PV/Solar input
        "pv1_voltage": runtime_data.pv1_voltage,
        "pv1_power": runtime_data.pv1_power,
        "pv2_voltage": runtime_data.pv2_voltage,
        "pv2_power": runtime_data.pv2_power,
        "pv3_voltage": runtime_data.pv3_voltage,
        "pv3_power": runtime_data.pv3_power,
        # PV strings 4-6 (V23 extended) — only populated for >3-string models;
        # RuntimeData leaves these None for residential 3-string inverters.
        "pv4_voltage": runtime_data.pv4_voltage,
        "pv4_power": runtime_data.pv4_power,
        "pv5_voltage": runtime_data.pv5_voltage,
        "pv5_power": runtime_data.pv5_power,
        "pv6_voltage": runtime_data.pv6_voltage,
        "pv6_power": runtime_data.pv6_power,
        "pv_total_power": runtime_data.pv_total_power,
        # PV string currents — DERIVED (power / voltage) in pylxpweb; no EG4
        # firmware register or cloud field exists for them (issue #243).
        "pv1_current": runtime_data.pv1_current,
        "pv2_current": runtime_data.pv2_current,
        "pv3_current": runtime_data.pv3_current,
        "pv4_current": runtime_data.pv4_current,
        "pv5_current": runtime_data.pv5_current,
        "pv6_current": runtime_data.pv6_current,
        # Battery
        "battery_voltage": runtime_data.battery_voltage,
        "battery_current": runtime_data.battery_current,
        "state_of_charge": runtime_data.battery_soc,
        "battery_temperature": runtime_data.battery_temperature,
        # Battery discharge power (reg 11 / cloud pDisCharge) — entity gated
        # to EG4_OFFGRID via OFFGRID_ONLY_SENSORS (issue #197).
        "battery_discharge_power": runtime_data.battery_discharge_power,
        # Grid - 3-phase R/S/T (LXP) and split-phase L1/L2 (EG4_OFFGRID/EG4_HYBRID)
        # Note: R/S/T registers valid on LXP, garbage on US split-phase systems
        # Note: L1/L2 registers valid on EG4_OFFGRID/EG4_HYBRID split-phase systems
        # Sensor platform filters based on inverter family
        "grid_voltage_r": runtime_data.grid_voltage_r,
        "grid_voltage_s": runtime_data.grid_voltage_s,
        "grid_voltage_t": runtime_data.grid_voltage_t,
        "grid_voltage_l1": runtime_data.grid_l1_voltage,
        "grid_voltage_l2": runtime_data.grid_l2_voltage,
        "grid_frequency": runtime_data.grid_frequency,
        "grid_power": net_grid_power,
        "grid_export_power": runtime_data.power_to_grid,
        # Inverter output
        "ac_power": runtime_data.inverter_power,
        # Power factor (Modbus reg 19, 0.0-1.0). Also available from cloud "pf"
        # via the inverter property map; surfaced here so LOCAL exposes it too.
        "power_factor": runtime_data.power_factor,
        # Note: the OLD load_power (register 27 pToUser) was removed — that
        # register is grid import, NOT consumption.  load_power now carries
        # register 170 (Pload) below; whole-home consumption stays on the
        # consumption_power sensor (energy balance).
        # EPS/Backup - 3-phase R/S/T (LXP) and split-phase L1/L2 (EG4_OFFGRID/EG4_HYBRID)
        "eps_voltage_r": runtime_data.eps_voltage_r,
        "eps_voltage_s": runtime_data.eps_voltage_s,
        "eps_voltage_t": runtime_data.eps_voltage_t,
        "eps_voltage_l1": runtime_data.eps_l1_voltage,
        "eps_voltage_l2": runtime_data.eps_l2_voltage,
        "eps_frequency": runtime_data.eps_frequency,
        "eps_power": runtime_data.eps_power,
        # EPS per-leg power (split-phase, regs 129-132)
        "eps_power_l1": runtime_data.eps_l1_power,
        "eps_power_l2": runtime_data.eps_l2_power,
        "eps_apparent_power_l1": runtime_data.eps_l1_apparent_power,
        "eps_apparent_power_l2": runtime_data.eps_l2_apparent_power,
        # Note: consumption_power is NOT set here - it's computed by the coordinator
        # using inverter.consumption_power (energy balance calculation from pylxpweb)
        # Output power (split-phase total)
        "output_power": runtime_data.output_power,
        # Load power (reg 170, "Pload" in the 6kXP Modbus PDF).  Valid both
        # grid-tied and in EPS mode on EG4_OFFGRID; the cloud zeroes its
        # reg-170 mirror for that family, so the LOCAL register is the only
        # trusted source (issue #197).  Entity gated to EG4_OFFGRID.
        "load_power": runtime_data.output_power,
        # Generator
        "generator_voltage": runtime_data.generator_voltage,
        "generator_frequency": runtime_data.generator_frequency,
        "generator_power": runtime_data.generator_power,
        # US split-phase per-leg power (regs 195-204)
        "generator_voltage_l1": runtime_data.generator_l1_voltage,
        "generator_voltage_l2": runtime_data.generator_l2_voltage,
        "inverter_power_l1": runtime_data.inverter_power_l1,
        "inverter_power_l2": runtime_data.inverter_power_l2,
        "rectifier_power_l1": runtime_data.rectifier_power_l1,
        "rectifier_power_l2": runtime_data.rectifier_power_l2,
        "grid_export_power_l1": runtime_data.grid_export_power_l1,
        "grid_export_power_l2": runtime_data.grid_export_power_l2,
        "grid_import_power_l1": runtime_data.grid_import_power_l1,
        "grid_import_power_l2": runtime_data.grid_import_power_l2,
        # Bus voltages
        "bus1_voltage": runtime_data.bus_voltage_1,
        "bus2_voltage": runtime_data.bus_voltage_2,
        # Temperatures
        "internal_temperature": runtime_data.internal_temperature,
        "radiator1_temperature": runtime_data.radiator_temperature_1,
        "radiator2_temperature": runtime_data.radiator_temperature_2,
        # BT Temperature (Modbus register 108, local-only)
        # Always include key so entity is created during static phase;
        # value will be None until bms_data register group is read.
        "bt_temperature": runtime_data.temperature_t1,
        # Status
        "status_code": runtime_data.device_status,
        # Friendly operating-state slug decoded from status_code (issue #262).
        # Shared decode -> identical to the CLOUD/HYBRID path.
        "operating_state": operating_state_slug(runtime_data.device_status),
        # Fault/warning codes (regs 60-61 / 62-63, 32-bit bitfields) — raw
        # passthrough; pylxpweb already merged the BMS code in as a fallback
        # when the inverter code reads 0 (eg4-23a6).
        "fault_code": runtime_data.fault_code,
        "warning_code": runtime_data.warning_code,
        # Inverter RMS current (3-phase R/S/T mapped to L1/L2/L3)
        # For local mode (Modbus): I_IINV_RMS (reg 18), I_IINV_RMS_S (reg 190), I_IINV_RMS_T (reg 191)
        # For HTTP mode: These values are not returned by the cloud API
        "grid_current_l1": runtime_data.inverter_rms_current_r,
        "grid_current_l2": runtime_data.inverter_rms_current_s,
        "grid_current_l3": runtime_data.inverter_rms_current_t,
        # BMS charge/discharge current limits (registers 81-82).
        # Not in SENSOR_TYPES — used as intermediate data for computing
        # battery_bank_charge_rate.
        "max_charge_current": runtime_data.bms_charge_current_limit,
        "max_discharge_current": runtime_data.bms_discharge_current_limit,
    }
    # NOTE (#335): eps_load_power (the EPS-loads subset of the backup output)
    # is deliberately NOT mapped here.  Regs 129/130 are the COMBINED
    # backup-path legs (already on eps_power_l1/l2 above) — with a GEN-port
    # smart load active they include the smart-load draw (#222: 6000XP live,
    # L1+L2 3371 W = smartLoadPower 2999 + epsLoadPower 365).  No local
    # register for the subset is validated (needs XP hardware probing), so
    # the sensor is CLOUD-ONLY for now: absent in pure LOCAL, populated in
    # CLOUD/HYBRID whenever cloud runtime is fetched (HTTP property map).
    return mapping


def _energy_balance(
    pv: float | None,
    discharge: float | None,
    grid_import: float | None,
    charge: float | None,
    grid_export: float | None,
) -> float | None:
    """Compute consumption from energy balance.

    consumption = yield + discharge + grid_import - charge - grid_export

    This mirrors the consumption_power computation in pylxpweb but for
    accumulated energy (kWh) instead of instantaneous power (W).

    The cloud API's ``totalUsage`` is server-computed and does not correspond
    to any single Modbus register.  The ``load_energy_total`` register
    (Erec_all, regs 48-49) is AC charge from grid — NOT consumption.
    Energy balance is the best local approximation.

    Returns:
        Consumption in kWh (clamped >= 0), or None if all inputs are None.
    """
    if all(v is None for v in (pv, discharge, grid_import, charge, grid_export)):
        return None
    result = (
        float(pv or 0)
        + float(discharge or 0)
        + float(grid_import or 0)
        - float(charge or 0)
        - float(grid_export or 0)
    )
    return max(0.0, result)


def _build_energy_sensor_mapping(energy_data: "InverterEnergyData") -> dict[str, Any]:
    """Build sensor mapping from energy data object.

    This helper extracts energy data from a transport's EnergyData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Two distinct meters are surfaced (see docs/DATA_MAPPING.md
    "Consumption vs Load Energy"):

    * ``load_energy``/``load_energy_lifetime`` — the inverter-served load
      (Eload, regs 171/172).  Raw register, equals the cloud's per-inverter
      ``todayUsage``/``totalUsage`` exactly.  In a parallel group a master can
      read 0 while the home draws power (grid-direct loads bypass it).
    * ``consumption``/``consumption_lifetime`` — whole-home consumption, derived
      from the energy balance because Eload does NOT include grid-direct loads.
      (``ac_charge_energy_*`` carries Erec, the AC-charge-from-grid register.)

    Args:
        energy_data: EnergyData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # Daily energy (kWh)
        "yield": energy_data.pv_energy_today,
        "charging": energy_data.charge_energy_today,
        "discharging": energy_data.discharge_energy_today,
        "grid_import": energy_data.grid_import_today,
        "grid_export": energy_data.grid_export_today,
        "consumption": _energy_balance(
            energy_data.pv_energy_today,
            energy_data.discharge_energy_today,
            energy_data.grid_import_today,
            energy_data.charge_energy_today,
            energy_data.grid_export_today,
        ),
        # Lifetime energy (kWh)
        "yield_lifetime": energy_data.pv_energy_total,
        "charging_lifetime": energy_data.charge_energy_total,
        "discharging_lifetime": energy_data.discharge_energy_total,
        "grid_import_lifetime": energy_data.grid_import_total,
        "grid_export_lifetime": energy_data.grid_export_total,
        "consumption_lifetime": _energy_balance(
            energy_data.pv_energy_total,
            energy_data.discharge_energy_total,
            energy_data.grid_import_total,
            energy_data.charge_energy_total,
            energy_data.grid_export_total,
        ),
        # Load Energy (Eload, regs 171/172) — inverter-served load, raw register.
        # Equals the cloud per-inverter todayUsage/totalUsage exactly.  Separate
        # meter from whole-home `consumption` above.
        "load_energy": energy_data.load_energy_today,
        "load_energy_lifetime": energy_data.load_energy_total,
        # EPS per-leg energy (split-phase, regs 133-138)
        "eps_energy_today_l1": energy_data.eps_l1_energy_today,
        "eps_energy_today_l2": energy_data.eps_l2_energy_today,
        "eps_energy_total_l1": energy_data.eps_l1_energy_total,
        "eps_energy_total_l2": energy_data.eps_l2_energy_total,
        # Granular per-string / per-component energy (regs 28-37 daily, 40+
        # lifetime).  Disabled-by-default sensors; LOCAL/HYBRID only (the cloud
        # energy endpoint returns only aggregates).  pv4-6 gated by string count.
        "pv1_yield": energy_data.pv1_energy_today,
        "pv2_yield": energy_data.pv2_energy_today,
        "pv3_yield": energy_data.pv3_energy_today,
        "pv4_yield": energy_data.pv4_energy_today,
        "pv5_yield": energy_data.pv5_energy_today,
        "pv6_yield": energy_data.pv6_energy_today,
        "pv1_yield_lifetime": energy_data.pv1_energy_total,
        "pv2_yield_lifetime": energy_data.pv2_energy_total,
        "pv3_yield_lifetime": energy_data.pv3_energy_total,
        "pv4_yield_lifetime": energy_data.pv4_energy_total,
        "pv5_yield_lifetime": energy_data.pv5_energy_total,
        "pv6_yield_lifetime": energy_data.pv6_energy_total,
        "inverter_energy": energy_data.inverter_energy_today,
        "inverter_energy_lifetime": energy_data.inverter_energy_total,
        "ac_charge_energy": energy_data.ac_charge_energy_today,
        "ac_charge_energy_lifetime": energy_data.ac_charge_energy_total,
        "eps_energy": energy_data.eps_energy_today,
        "eps_energy_lifetime": energy_data.eps_energy_total,
        "generator_energy": energy_data.generator_energy_today,
        "generator_energy_lifetime": energy_data.generator_energy_total,
    }


# ---------------------------------------------------------------------------
# Canonical battery-bank field tables (shared LOCAL/CLOUD/HYBRID adapter).
#
# These tables are the SINGLE source of truth for which battery-bank sensors
# exist and which source attribute feeds each one.  Both the LOCAL path
# (BatteryBankData transport dataclass) and the CLOUD path (BatteryBank device
# object) consume them through build_battery_bank_sensors(), and the cloud
# property map is DERIVED from the passthrough tables — so adding a passthrough
# bank sensor in one place surfaces it in every mode (structural cure for the M2
# "fix-one-miss-the-other" duplication).  Behaviour that genuinely differs per
# source is preserved exactly inside the adapter and documented on each
# table/helper:
#   * CLOUD reads computed properties defensively and skips None/"" (parity
#     with _map_device_properties); LOCAL reads dataclass fields directly and
#     writes every key (incl. None) to keep the sensors present.
#   * battery_bank_power priority is reversed (see _compute_bank_power).
#   * BMS *numeric limit* registers (charge/discharge current, voltage ref,
#     cutoff, type) are LOCAL-only (_BATTERY_BANK_LOCAL_REGISTER_FIELDS); cloud
#     min-cell values are derived from per-battery data (_derive_cloud_min_cell).
#   * BMS *permission/request flags* (reg 95 bits, issue #232) ARE both-mode:
#     they need a bool->enum encoder so they live in the separate
#     _BATTERY_BANK_BMS_PERMISSION_FIELDS table (NOT the derived property map),
#     and CLOUD gets them via the BatteryBank's parent-inverter delegation.
# ---------------------------------------------------------------------------

# Common bank fields exposed by BOTH BatteryBankData and BatteryBank.
# sensor_key -> source attribute name.
_BATTERY_BANK_FIELDS: dict[str, str] = {
    "battery_bank_soc": "soc",
    "battery_bank_voltage": "voltage",
    "battery_bank_current": "current",
    "battery_bank_max_capacity": "max_capacity",
    "battery_bank_current_capacity": "current_capacity",
    "battery_bank_remain_capacity": "remain_capacity",
    "battery_bank_full_capacity": "full_capacity",
    "battery_bank_capacity_percent": "capacity_percent",
    "battery_bank_count": "battery_count",
    "battery_bank_status": "status",
    # Bank-level register data (always available, no CAN bus needed)
    "battery_bank_cycle_count": "cycle_count",
    "battery_bank_min_soh": "min_soh",
    "battery_bank_max_cell_temp": "max_cell_temp",
    "battery_bank_temp_delta": "temp_delta",
    "battery_bank_cell_voltage_delta_max": "cell_voltage_delta_max",
}

# CAN-dependent cross-battery diagnostics — require individual battery data
# (registers 5002+ / cloud per-battery array).  Properties return None when no
# CAN data is available, so these are None-skipped in BOTH modes (never
# fabricate; not part of ALL_INVERTER_SENSOR_KEYS).
_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS: dict[str, str] = {
    "battery_bank_soc_delta": "soc_delta",
    "battery_bank_soh_delta": "soh_delta",
    "battery_bank_voltage_delta": "voltage_delta",
    "battery_bank_cycle_count_delta": "cycle_count_delta",
}

# LOCAL-only Modbus bank registers (numeric BMS limits + min-cell values).  The
# cloud BatteryBank object does NOT expose these (cloud min-cell values are
# derived from per-battery data instead — see _derive_cloud_min_cell).  Written
# unconditionally in LOCAL mode (incl. None) to keep the sensors present.
# NOTE: only LOCAL-exclusive registers belong here.  A new BMS field the cloud
# can also supply (like the reg-95 permission flags) goes in a both-mode table
# (see _BATTERY_BANK_BMS_PERMISSION_FIELDS), not here.
_BATTERY_BANK_LOCAL_REGISTER_FIELDS: dict[str, str] = {
    "battery_bank_min_cell_temp": "min_cell_temperature",
    "battery_bank_min_cell_voltage": "min_cell_voltage",
    "battery_bank_bms_charge_current_limit": "bms_charge_current_limit",
    "battery_bank_bms_discharge_current_limit": "bms_discharge_current_limit",
    "battery_bank_bms_charge_voltage_ref": "bms_charge_voltage_ref",
    "battery_bank_bms_discharge_cutoff": "bms_discharge_cutoff",
    "battery_bank_bms_battery_type": "bms_battery_type",
    "battery_bank_voltage_inv_sample": "battery_voltage_inv_sample",
}


def get_battery_bank_property_map() -> dict[str, str]:
    """Cloud battery-bank property map, DERIVED from the canonical tables.

    Maps a pylxpweb BatteryBank property name -> sensor key, for the cross-repo
    contract test and any other consumer.  Built from the two PASSTHROUGH field
    tables the adapter uses, so the cloud map can never silently drift from the
    LOCAL sensor set.  charge_power/discharge_power are intermediates consumed by
    the power calc; battery_power maps to the final power sensor.

    Scope: this covers only the passthrough tables.  The encoder-based
    _BATTERY_BANK_BMS_PERMISSION_FIELDS (reg 95 flags, issue #232) is NOT here —
    its bool->enum encoding can't be expressed as a flat attr->key map — and is
    seam-guarded separately by test_register_contract.py and the
    test_bms_permission_* adapter tests.

    Returns:
        Dictionary mapping battery bank property names to sensor keys.
    """
    property_map: dict[str, str] = {
        attr: key
        for key, attr in {
            **_BATTERY_BANK_FIELDS,
            **_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
        }.items()
    }
    property_map["charge_power"] = "_battery_bank_charge_power"
    property_map["discharge_power"] = "_battery_bank_discharge_power"
    property_map["battery_power"] = "battery_bank_power"
    return property_map


def _read_bank_value(bank: Any, attr: str, *, defensive: bool) -> Any:
    """Read *attr* from a battery-bank source object.

    LOCAL transport dataclass fields are plain attributes (safe direct read).
    CLOUD BatteryBank exposes computed properties that may call float()/int()
    on not-yet-populated internal data and raise; ``defensive=True`` mirrors
    ``_map_device_properties`` exactly: it returns None on
    TypeError/ValueError/AttributeError AND treats an empty string as "no data"
    (the generic mapper skipped both None and "").  Normalising "" -> None here
    keeps every consumer (common loop, CAN diagnostics, power calc) faithful to
    the original cloud behaviour without repeating the "" check at each site.
    """
    if not defensive:
        return getattr(bank, attr, None)
    try:
        value = getattr(bank, attr, None)
    except (TypeError, ValueError, AttributeError) as exc:
        _LOGGER.debug(
            "battery_bank property %s raised %s: %s", attr, type(exc).__name__, exc
        )
        return None
    return None if value == "" else value


def _compute_bank_power(
    charge: float | None,
    discharge: float | None,
    api_power: float | None,
    *,
    prefer_api: bool,
) -> float | None:
    """Compute battery_bank_power, preserving each source's priority.

    LOCAL prefers the authoritative charge−discharge difference (its
    battery_power is only a voltage×current fallback).  CLOUD prefers the API's
    batPower value and falls back to charge−discharge.
    """
    charge_discharge = (
        charge - discharge if charge is not None and discharge is not None else None
    )
    if prefer_api:
        return api_power if api_power is not None else charge_discharge
    return charge_discharge if charge_discharge is not None else api_power


def _derive_cloud_min_cell(bank: Any, sensors: dict[str, Any]) -> None:
    """Derive bank min cell temp/voltage from per-battery data (CLOUD only).

    The cloud BatteryBank object does not expose min_cell_temperature/
    min_cell_voltage (those are Modbus bank registers in LOCAL mode), but each
    per-battery object does.  Mirror LOCAL's battery_bank_min_cell_* sensors
    when CAN/per-battery data is available; otherwise omit (never fabricate).
    """
    batteries = getattr(bank, "batteries", None) or []
    min_cell_temps = [
        t for b in batteries if (t := getattr(b, "min_cell_temp", None)) is not None
    ]
    if min_cell_temps:
        sensors["battery_bank_min_cell_temp"] = min(min_cell_temps)
    min_cell_voltages = [
        v for b in batteries if (v := getattr(b, "min_cell_voltage", None)) is not None
    ]
    if min_cell_voltages:
        sensors["battery_bank_min_cell_voltage"] = min(min_cell_voltages)


def _bms_permission_state(value: bool | None) -> str | None:
    """Map a BMS allow-charge / allow-discharge flag to its enum sensor state.

    Returns display-ready English values (matching the codebase convention of
    English status strings, e.g. battery_bank_status="Charging"); ``None`` keeps
    the entity ``unavailable`` when the flag is unknown.
    """
    if value is None:
        return None
    return "Allowed" if value else "Blocked"


def _bms_force_charge_state(value: bool | None) -> str | None:
    """Map the BMS force-charge request flag to its enum sensor state."""
    if value is None:
        return None
    return "Requested" if value else "Idle"


# BMS permission/request flags (issue #232): sensor key -> (bank source attr,
# bool->enum-state encoder).  Both BatteryBankData (LOCAL, reg 95 decode) and
# BatteryBank (CLOUD, parent-inverter delegation) expose these attrs, so the
# flags surface in every mode.
_BATTERY_BANK_BMS_PERMISSION_FIELDS: tuple[
    tuple[str, str, Callable[[bool | None], str | None]], ...
] = (
    ("battery_bank_charge_allowed", "allow_charge", _bms_permission_state),
    ("battery_bank_discharge_allowed", "allow_discharge", _bms_permission_state),
    ("battery_bank_force_charge", "force_charge", _bms_force_charge_state),
)


def build_battery_bank_sensors(
    bank: "BatteryBankData | BatteryBank",
    *,
    source: Literal["local", "cloud"],
) -> dict[str, Any]:
    """Canonical battery-bank sensor adapter for LOCAL/CLOUD/HYBRID.

    Produces the battery-bank sensor dict from either a LOCAL transport
    ``BatteryBankData`` object (``source="local"``) or a CLOUD ``BatteryBank``
    device object (``source="cloud"``).  Both paths share the canonical field
    tables so the common sensor set cannot drift; per-source differences
    documented on the tables/helpers are preserved exactly.

    The C-rate sensor (``battery_bank_charge_rate``) is computed separately by
    ``compute_bank_charge_rate()`` at the call site, after this adapter runs.

    Args:
        bank: ``BatteryBankData`` (LOCAL/HYBRID transport) or ``BatteryBank``
            (CLOUD device) object.
        source: ``"local"`` or ``"cloud"`` — selects read semantics.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    is_cloud = source == "cloud"
    sensors: dict[str, Any] = {}

    # Common fields.  LOCAL writes every key (incl. None) to keep sensors
    # present; CLOUD skips None exactly like _map_device_properties (""
    # already normalised to None by _read_bank_value's defensive read).
    for key, attr in _BATTERY_BANK_FIELDS.items():
        value = _read_bank_value(bank, attr, defensive=is_cloud)
        if is_cloud and value is None:
            continue
        sensors[key] = value

    # BMS permission/request flags (issue #232).  Available in BOTH modes:
    # LOCAL decodes input register 95 onto BatteryBankData; CLOUD's BatteryBank
    # delegates to its parent inverter's bmsCharge/bmsDischarge/bmsForceCharge.
    # Encoded as enum states.  LOCAL writes every key (incl. None) to keep the
    # entity present; CLOUD skips None (parity with the common loop).
    for perm_key, perm_attr, encode in _BATTERY_BANK_BMS_PERMISSION_FIELDS:
        state = encode(_read_bank_value(bank, perm_attr, defensive=is_cloud))
        if is_cloud and state is None:
            continue
        sensors[perm_key] = state

    # CAN cross-battery diagnostics: None-skipped in BOTH modes.
    for key, attr in _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS.items():
        value = _read_bank_value(bank, attr, defensive=is_cloud)
        if value is not None:
            sensors[key] = value

    # battery_bank_power — source-specific priority.  LOCAL always writes the
    # key (incl. None); CLOUD writes only when computable.
    charge = _read_bank_value(bank, "charge_power", defensive=is_cloud)
    discharge = _read_bank_value(bank, "discharge_power", defensive=is_cloud)
    api_power = _read_bank_value(bank, "battery_power", defensive=is_cloud)
    power = _compute_bank_power(charge, discharge, api_power, prefer_api=is_cloud)
    if not is_cloud or power is not None:
        sensors["battery_bank_power"] = power
    if power is None:
        # Debug, not warning: this is the expected state for an offline or
        # partially-reported bank (e.g. cloud-lost inverter, #479) and would
        # otherwise repeat every poll for the whole outage.
        _LOGGER.debug(
            "%s battery_bank_power for %s: cannot calculate - "
            "charge=%s, discharge=%s, battery_power=%s",
            source.upper(),
            getattr(bank, "serial_number", None) or "unknown serial",
            charge,
            discharge,
            api_power,
        )

    # Source-specific extras.
    if is_cloud:
        _derive_cloud_min_cell(bank, sensors)
    else:
        for key, attr in _BATTERY_BANK_LOCAL_REGISTER_FIELDS.items():
            sensors[key] = getattr(bank, attr, None)

    # battery_status backwards-compat alias (v2.2.x mapped batStatus at the
    # inverter level).  LOCAL always mirrors status (incl. None); CLOUD mirrors
    # only when present.
    if not is_cloud:
        sensors["battery_status"] = sensors.get("battery_bank_status")
    elif "battery_bank_status" in sensors:
        sensors["battery_status"] = sensors["battery_bank_status"]

    # Poll timestamp for the battery bank device (both modes).
    sensors["battery_bank_last_polled"] = dt_util.utcnow()

    return sensors


def _build_battery_bank_sensor_mapping(
    battery_data: "BatteryBankData",
) -> dict[str, Any]:
    """Build sensor mapping from LOCAL transport battery bank data.

    Thin wrapper over :func:`build_battery_bank_sensors` (``source="local"``);
    retained as the LOCAL entry point used by the coordinator and tests.

    Args:
        battery_data: BatteryBankData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return build_battery_bank_sensors(battery_data, source="local")


def _build_individual_battery_mapping(
    battery: "Battery | BatteryData",
) -> dict[str, Any]:
    """Build sensor mapping from a BatteryData or Battery object.

    Works with both pylxpweb transport BatteryData (LOCAL/HYBRID overlay)
    and Battery device objects (HYBRID cloud baseline) via shared attribute
    names defined on both classes.

    Args:
        battery: BatteryData (transport) or Battery (device) object.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    sensors: dict[str, Any] = {
        # Core battery metrics
        "battery_real_voltage": battery.voltage,
        "battery_real_current": battery.current,
        "battery_real_power": battery.power,
        "battery_rsoc": battery.soc,
        "state_of_health": battery.soh,
        # Temperature sensors
        "battery_max_cell_temp": battery.max_cell_temperature,
        "battery_min_cell_temp": battery.min_cell_temperature,
        "battery_max_cell_temp_num": battery.max_cell_num_temp,
        "battery_min_cell_temp_num": battery.min_cell_num_temp,
        # Cell voltage sensors
        "battery_max_cell_voltage": battery.max_cell_voltage,
        "battery_min_cell_voltage": battery.min_cell_voltage,
        "battery_max_cell_voltage_num": battery.max_cell_num_voltage,
        "battery_min_cell_voltage_num": battery.min_cell_num_voltage,
        "battery_cell_voltage_delta": battery.cell_voltage_delta,
        "battery_cell_temp_delta": battery.cell_temp_delta,
        # Capacity sensors
        # Use remaining_capacity (computed: max_capacity * soc / 100) not current_capacity
        # which returns 0 from Modbus individual battery registers
        "battery_remaining_capacity": battery.remaining_capacity,
        "battery_full_capacity": battery.max_capacity,
        "battery_capacity_percentage": battery.capacity_percent,
        # BMS limits
        "battery_max_charge_current": battery.charge_current_limit,
        "battery_charge_voltage_ref": battery.charge_voltage_ref,
        # Lifecycle
        "cycle_count": battery.cycle_count,
        "battery_firmware_version": battery.firmware_version,
        # Metadata
        "battery_type": battery.battery_type,
        "battery_type_text": battery.battery_type_text,
        "battery_serial_number": battery.serial_number,
        "battery_model": battery.model,
        "battery_index": battery.battery_index,
        # Last polled timestamp for individual battery device
        "battery_last_polled": dt_util.utcnow(),
        # Last seen: when this battery's register data was actually read from
        # the inverter (round-robin may serve stale cached data for >4 systems)
        "battery_last_seen": (
            dt_util.as_utc(last_seen)
            if (last_seen := getattr(battery, "last_seen", None))
            else dt_util.utcnow()
        ),
    }

    # Signed C-rate as percentage of capacity per hour
    _write_charge_rate(
        sensors,
        "battery_charge_rate",
        battery.current,
        battery.max_capacity,
    )

    return sensors


def _build_gridboss_sensor_mapping(mid_device: "MIDDevice") -> dict[str, Any]:
    """Build sensor mapping from MIDDevice object for GridBOSS.

    Extracts data from a MIDDevice's runtime properties (provided by
    MIDRuntimePropertiesMixin) and maps it to sensor keys matching
    SENSOR_TYPES definitions.  Uses direct attribute access since all
    properties are defined by the mixin and return None when no data.

    This follows the same pattern as ``_build_runtime_sensor_mapping()``
    for inverters — both read from device property accessors that handle
    the transport/HTTP dual-source dispatch internally.

    Note: Metadata fields (firmware_version, connection_transport,
    off_grid, transport_host) are set at the call site, not here,
    matching the inverter pattern in ``_build_local_device_data()``.

    Args:
        mid_device: MIDDevice object from pylxpweb with runtime data.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # Grid sensors
        "grid_power": mid_device.grid_power,
        "grid_voltage": mid_device.grid_voltage,
        "frequency": mid_device.grid_frequency,
        "grid_power_l1": mid_device.grid_l1_power,
        "grid_power_l2": mid_device.grid_l2_power,
        "grid_voltage_l1": mid_device.grid_l1_voltage,
        "grid_voltage_l2": mid_device.grid_l2_voltage,
        "grid_current_l1": mid_device.grid_l1_current,
        "grid_current_l2": mid_device.grid_l2_current,
        # UPS sensors
        "ups_power": mid_device.ups_power,
        "ups_voltage": mid_device.ups_voltage,
        "ups_power_l1": mid_device.ups_l1_power,
        "ups_power_l2": mid_device.ups_l2_power,
        "load_voltage_l1": mid_device.ups_l1_voltage,
        "load_voltage_l2": mid_device.ups_l2_voltage,
        "ups_current_l1": mid_device.ups_l1_current,
        "ups_current_l2": mid_device.ups_l2_current,
        # Load sensors
        "load_power": mid_device.load_power,
        "load_power_l1": mid_device.load_l1_power,
        "load_power_l2": mid_device.load_l2_power,
        "load_current_l1": mid_device.load_l1_current,
        "load_current_l2": mid_device.load_l2_current,
        # Consumption power for GridBOSS = load_power (CT measurement)
        "consumption_power": mid_device.load_power,
        # Generator sensors
        "generator_power": mid_device.generator_power,
        "generator_voltage": mid_device.generator_voltage,
        "generator_frequency": mid_device.generator_frequency,
        "generator_power_l1": mid_device.generator_l1_power,
        "generator_power_l2": mid_device.generator_l2_power,
        "generator_current_l1": mid_device.generator_l1_current,
        "generator_current_l2": mid_device.generator_l2_current,
        "generator_voltage_l1": mid_device.generator_l1_voltage,
        "generator_voltage_l2": mid_device.generator_l2_voltage,
        # Other sensors
        "hybrid_power": mid_device.hybrid_power,
        "phase_lock_frequency": mid_device.phase_lock_frequency,
        "off_grid": mid_device.is_off_grid,
        # Smart port status
        "smart_port1_status": mid_device.smart_port1_status,
        "smart_port2_status": mid_device.smart_port2_status,
        "smart_port3_status": mid_device.smart_port3_status,
        "smart_port4_status": mid_device.smart_port4_status,
        # Smart load power (L1/L2)
        "smart_load1_power_l1": mid_device.smart_load1_l1_power,
        "smart_load1_power_l2": mid_device.smart_load1_l2_power,
        "smart_load2_power_l1": mid_device.smart_load2_l1_power,
        "smart_load2_power_l2": mid_device.smart_load2_l2_power,
        "smart_load3_power_l1": mid_device.smart_load3_l1_power,
        "smart_load3_power_l2": mid_device.smart_load3_l2_power,
        "smart_load4_power_l1": mid_device.smart_load4_l1_power,
        "smart_load4_power_l2": mid_device.smart_load4_l2_power,
        # Smart port current (L1/L2) — Modbus only, regs 18-25
        # Mapped as smart_load by default; _filter_unused_smart_port_sensors()
        # will remap to ac_couple keys for ports in AC Couple mode.
        "smart_load1_current_l1": mid_device.smart_port1_l1_current,
        "smart_load1_current_l2": mid_device.smart_port1_l2_current,
        "smart_load2_current_l1": mid_device.smart_port2_l1_current,
        "smart_load2_current_l2": mid_device.smart_port2_l2_current,
        "smart_load3_current_l1": mid_device.smart_port3_l1_current,
        "smart_load3_current_l2": mid_device.smart_port3_l2_current,
        "smart_load4_current_l1": mid_device.smart_port4_l1_current,
        "smart_load4_current_l2": mid_device.smart_port4_l2_current,
        # AC couple power (L1/L2)
        "ac_couple1_power_l1": mid_device.ac_couple1_l1_power,
        "ac_couple1_power_l2": mid_device.ac_couple1_l2_power,
        "ac_couple2_power_l1": mid_device.ac_couple2_l1_power,
        "ac_couple2_power_l2": mid_device.ac_couple2_l2_power,
        "ac_couple3_power_l1": mid_device.ac_couple3_l1_power,
        "ac_couple3_power_l2": mid_device.ac_couple3_l2_power,
        "ac_couple4_power_l1": mid_device.ac_couple4_l1_power,
        "ac_couple4_power_l2": mid_device.ac_couple4_l2_power,
        # Energy sensors - aggregate only (L2 energy registers always read 0)
        "ups_today": mid_device.e_ups_today,
        "ups_total": mid_device.e_ups_total,
        "grid_export_today": mid_device.e_to_grid_today,
        "grid_export_total": mid_device.e_to_grid_total,
        "grid_import_today": mid_device.e_to_user_today,
        "grid_import_total": mid_device.e_to_user_total,
        "load_today": mid_device.e_load_today,
        "load_total": mid_device.e_load_total,
        # AC Couple energy (all 4 ports)
        "ac_couple1_today": mid_device.e_ac_couple1_today,
        "ac_couple1_total": mid_device.e_ac_couple1_total,
        "ac_couple2_today": mid_device.e_ac_couple2_today,
        "ac_couple2_total": mid_device.e_ac_couple2_total,
        "ac_couple3_today": mid_device.e_ac_couple3_today,
        "ac_couple3_total": mid_device.e_ac_couple3_total,
        "ac_couple4_today": mid_device.e_ac_couple4_today,
        "ac_couple4_total": mid_device.e_ac_couple4_total,
        # Smart Load energy (all 4 ports)
        "smart_load1_today": mid_device.e_smart_load1_today,
        "smart_load1_total": mid_device.e_smart_load1_total,
        "smart_load2_today": mid_device.e_smart_load2_today,
        "smart_load2_total": mid_device.e_smart_load2_total,
        "smart_load3_today": mid_device.e_smart_load3_today,
        "smart_load3_total": mid_device.e_smart_load3_total,
        "smart_load4_today": mid_device.e_smart_load4_today,
        "smart_load4_total": mid_device.e_smart_load4_total,
        # Last polled timestamp for midbox/GridBOSS device
        "midbox_last_polled": dt_util.utcnow(),
    }


def _parse_inverter_family(family_str: str | None) -> Any:
    """Convert inverter family string to InverterFamily enum.

    Args:
        family_str: Family string from config (e.g., "EG4_HYBRID", "EG4_OFFGRID", "LXP").
            Also handles legacy names (e.g., "PV_SERIES", "SNA", "LXP_EU", "LXP_LV").

    Returns:
        InverterFamily enum value, or None if invalid/not provided.
    """
    if not family_str or family_str == "MID_DEVICE":
        # MID_DEVICE is a GridBOSS/MIDBox — not an inverter family
        return None

    # Map legacy family names to current names
    mapped_family = LEGACY_FAMILY_MAP.get(family_str, family_str)
    if mapped_family != family_str:
        _LOGGER.debug(
            "Mapped legacy inverter family '%s' to '%s'", family_str, mapped_family
        )

    try:
        from pylxpweb.devices.inverters import InverterFamily

        return InverterFamily(mapped_family)
    except ValueError:
        _LOGGER.warning("Unknown inverter family '%s', using default", family_str)
        return None


def _family_from_model_name(model: str | None) -> str | None:
    """Map a device model name to its inverter family (fallback path).

    Only consulted when register/cloud-based family detection could not
    resolve the family. Matching is case-insensitive against
    :data:`MODEL_NAME_FAMILY_FALLBACK`.

    Args:
        model: Device model string (e.g. "6000XP", "FlexBOSS21").

    Returns:
        Family string ("EG4_OFFGRID"/"EG4_HYBRID") or None if unrecognized.
    """
    if not model:
        return None
    return MODEL_NAME_FAMILY_FALLBACK.get(model.strip().upper())


def _model_fallback_profile(model: str | None) -> dict[str, Any] | None:
    """Derive a full family feature profile from a device model name.

    Builds the same feature dict shape as :func:`_features_from_family` by
    routing the model-mapped family through pylxpweb's canonical
    ``InverterFeatures`` — so the fallback profile is complete (phase flags,
    discharge recovery, volt-watt, PV string count, grid type), not just a
    split-phase patch.

    Args:
        model: Device model string.

    Returns:
        Feature dict, or None when the model does not map to a family.
    """
    family_str = _family_from_model_name(model)
    if family_str is None:
        return None

    from pylxpweb.devices.inverters import InverterFamily, InverterFeatures

    feat = InverterFeatures.from_family(InverterFamily(family_str))
    if feat is None:
        # Defensive: all fallback families have a representative profile.
        return None
    return _features_dict_from_inverter_features(feat)


def _apply_model_family_fallback(
    features: dict[str, Any], model: str | None, serial: str | None = None
) -> dict[str, Any]:
    """Re-derive the feature profile from the model name when family is UNKNOWN.

    Some firmware reports a HOLD_DEVICE_TYPE_CODE that pylxpweb cannot map
    (e.g. 6000XP on ccaa-140A0A, issue #219). ``detect_features()`` then
    yields family=UNKNOWN whose conservative defaults set
    ``split_phase=False`` — silently starving all L1/L2 sensors (eps_power_l1,
    eps_power_l2, ...). When the device *model* string identifies a known
    family, the family-default layer is rebuilt from it instead.

    Detection-derived refinements survive the fallback: any detected value
    that deviates from the pure-UNKNOWN baseline was set by something real —
    pylxpweb's runtime register probing (``_probe_optional_features``) or an
    explicit PV string count — and overrides the family profile, mirroring
    pylxpweb's own family-defaults-then-probe layering. The real (unmapped)
    ``device_type_code`` is always preserved for diagnostics so users can
    report it for proper mapping.

    Args:
        features: Feature dict from ``_features_dict_from_inverter_features``.
        model: Device model string (cloud ``deviceTypeText`` or config model).
        serial: Device serial for logging context.

    Returns:
        The fallback feature dict, or *features* unchanged when detection
        resolved a real family or the model is unrecognized.
    """
    from pylxpweb.devices.inverters import InverterFamily, InverterFeatures

    if features.get("inverter_family") != InverterFamily.UNKNOWN.value:
        return features

    fallback = _model_fallback_profile(model)
    if fallback is None:
        return features

    # Pure-UNKNOWN baseline (no probe refinements): fields where the detected
    # dict matches this baseline carry no information and take the fallback
    # profile's value; deviations were genuinely detected and win.
    baseline = _features_dict_from_inverter_features(InverterFeatures())

    merged = dict(fallback)
    for key, detected_value in features.items():
        if key in ("inverter_family", "device_type_code"):
            # inverter_family: replacing UNKNOWN is the whole point.
            # device_type_code: handled explicitly below.
            continue
        if key not in baseline or detected_value != baseline[key]:
            merged[key] = detected_value

    # Keep the real (unmapped) code — the representative profile's code is
    # synthetic and would hide the value users need to report.
    if "device_type_code" in features:
        merged["device_type_code"] = features["device_type_code"]

    # pv_string_count: the baseline default is itself a VALID probed value, so
    # value-difference is not usable as provenance for this field — a probe
    # that landed exactly on the default would be clobbered by the profile.
    # An explicitly detected count always wins over the fallback profile.
    if "pv_string_count" in features:
        merged["pv_string_count"] = features["pv_string_count"]

    # Provenance breadcrumbs: the diagnostic inverter_family sensor reports
    # the EFFECTIVE family (so downstream gating works), and these companion
    # keys keep the raw detection visible in coordinator data/diagnostics so
    # the upstream pylxpweb mapping gap stays reportable.
    merged["family_source"] = "model_fallback"
    merged["detected_inverter_family"] = features.get(
        "inverter_family", InverterFamily.UNKNOWN.value
    )

    _LOGGER.info(
        "Inverter family UNKNOWN for %s (device_type_code=%s); derived family "
        "%s from model name %r",
        serial or "unknown serial",
        features.get("device_type_code"),
        merged["inverter_family"],
        model,
    )
    return merged


def _apply_grid_type_override(features: dict[str, Any], grid_type: str) -> None:
    """Override phase-specific feature flags based on user-selected grid type.

    Mutates the features dict in-place.

    Args:
        features: Feature dict to modify.
        grid_type: One of GRID_TYPE_SPLIT_PHASE, GRID_TYPE_SINGLE_PHASE,
            or GRID_TYPE_THREE_PHASE.
    """
    if grid_type == GRID_TYPE_SPLIT_PHASE:
        features["supports_split_phase"] = True
        features["supports_three_phase"] = False
    elif grid_type == GRID_TYPE_SINGLE_PHASE:
        features["supports_split_phase"] = False
        features["supports_three_phase"] = False
    elif grid_type == GRID_TYPE_THREE_PHASE:
        features["supports_split_phase"] = False
        features["supports_three_phase"] = True


def _features_dict_from_inverter_features(feat: "InverterFeatures") -> dict[str, Any]:
    """Map a pylxpweb ``InverterFeatures`` instance to the integration feature dict.

    Single source of truth for translating pylxpweb's canonical
    ``InverterFeatures`` capability flags into the keys consumed by
    ``_should_create_sensor`` (``supports_*``, ``pv_string_count``) and the
    diagnostic feature sensors (``inverter_family``, ``grid_type``,
    ``device_type_code``). Both the static-data path (:func:`_features_from_family`)
    and the live detection path (``DeviceProcessingMixin._extract_inverter_features``)
    route through this function, so the two always agree for a given device.

    Args:
        feat: pylxpweb ``InverterFeatures`` instance (from ``detect_features()``
            or ``from_device_type_code``/``from_family``).

    Returns:
        Feature dict for ``_should_create_sensor`` filtering and diagnostics.
    """
    from pylxpweb.devices.inverters import InverterFamily

    family = feat.model_family
    return {
        "inverter_family": (
            family.value if isinstance(family, InverterFamily) else str(family)
        ),
        "grid_type": str(feat.grid_type.value),
        "device_type_code": feat.device_type_code,
        "supports_split_phase": feat.split_phase,
        "supports_three_phase": feat.three_phase_capable,
        "supports_off_grid": feat.off_grid_capable,
        "supports_parallel": feat.parallel_support,
        "supports_volt_watt_curve": feat.volt_watt_curve,
        "supports_grid_peak_shaving": feat.grid_peak_shaving,
        "supports_drms": feat.drms_support,
        "supports_discharge_recovery_hysteresis": feat.discharge_recovery_hysteresis,
        "pv_string_count": int(feat.pv_string_count),
    }


def _features_from_family(
    family_str: str | None,
    device_type_code: int | None = None,
    grid_type: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Derive feature flags from inverter family and device type code.

    Used by the static-data first refresh to provide correct feature-based
    sensor filtering without reading Modbus registers, before pylxpweb's
    register-based ``detect_features()`` runs on the first real poll.

    Capabilities are sourced from pylxpweb's canonical ``InverterFeatures`` (via
    :meth:`InverterFeatures.from_family`) and mapped through
    :func:`_features_dict_from_inverter_features` — the same mapper the live
    detection path uses — so the static and live paths agree for a given device.
    The only integration-specific layer is the optional user-selected grid-type
    override.

    Args:
        family_str: Inverter family from config (e.g. "EG4_HYBRID", "EG4_OFFGRID",
            "LXP"). Legacy names ("SNA", "PV_SERIES", "LXP_EU", "LXP_LV") are
            accepted.
        device_type_code: Raw device type code from register 19, stored in config
            during discovery. Disambiguates families that need it (LXP-EU vs
            LXP-LB).
        grid_type: User-selected grid type override. When provided, overrides the
            phase flags. None means no override (backward compatible).
        model: Device model string from config. Used as a last-resort family
            fallback (issue #219) when the family is missing/UNKNOWN — a known
            model (e.g. "6000XP") then supplies its family profile. A
            known-but-ambiguous family (LXP without device type code) is never
            model-overridden.

    Returns:
        Feature dict suitable for ``_should_create_sensor`` filtering. Empty dict
        when the family is unknown or cannot be resolved without a device type
        code (conservative: creates all sensors).
    """
    family = _parse_inverter_family(family_str)

    from pylxpweb.devices.inverters import InverterFamily, InverterFeatures

    feat = (
        InverterFeatures.from_family(family, device_type_code)
        if family is not None
        else None
    )

    if feat is None:
        # A resolved-but-ambiguous family (LXP needs a device type code to
        # pick EU three-phase vs LB split-phase) keeps the conservative
        # create-all fallback — a contradictory model must not pick a side.
        if family is not None and family != InverterFamily.UNKNOWN:
            return {}

        # Model-name fallback (issue #219): family missing or UNKNOWN.
        features = _model_fallback_profile(model)
        if features is None:
            return {}
        # Provenance breadcrumbs (mirror _apply_model_family_fallback): keep
        # the raw config family visible and let the static-data builder
        # detect that the fallback engaged (Repairs notice for legacy
        # UNKNOWN entries whose create-all sensor set is now pruned).
        features["family_source"] = "model_fallback"
        features["detected_inverter_family"] = (
            str(family_str) if family_str else InverterFamily.UNKNOWN.value
        )
        _LOGGER.info(
            "Inverter family %r unresolved in config; derived family %s from "
            "model name %r",
            family_str,
            features["inverter_family"],
            model,
        )
    else:
        features = _features_dict_from_inverter_features(feat)

    # The only integration-specific layer on top of pylxpweb's canonical
    # capabilities: apply the user-selected grid-type override when present.
    if grid_type:
        _apply_grid_type_override(features, grid_type)

    return features


def _derive_model_from_family(
    config_model: str, family_str: str, fallback: str = "18kPV"
) -> str:
    """Derive inverter model from config or family.

    Args:
        config_model: Explicit model from config entry (preferred if non-empty).
        family_str: Inverter family string (e.g., "pv_series", "sna", "lxp_eu").
        fallback: Default model if neither config nor family mapping exists.

    Returns:
        Inverter model string for entity compatibility.
    """
    if config_model:
        return config_model
    return INVERTER_FAMILY_DEFAULT_MODELS.get(family_str, fallback)


# ---------------------------------------------------------------------------
# Modbus input-register block size (#254)
# ---------------------------------------------------------------------------

# The conservative register count — anything at or below this means "plain
# grouped reads", which needs no transport parameter at all.
_CONSERVATIVE_BLOCK_REGISTERS = BLOCK_SIZE_PRESET_REGISTERS[BLOCK_SIZE_CONSERVATIVE]


@lru_cache(maxsize=1)
def _warn_block_size_unsupported() -> bool:
    """Warn once per HA run that the installed pylxpweb lacks the parameter."""
    _LOGGER.warning(
        "Modbus read block size is set to Fast, but the installed pylxpweb "
        "does not support max_input_block_size yet — using the conservative "
        "grouped reads. Update pylxpweb to enable faster polling."
    )
    return True


def input_block_size_kwargs(max_input_block_size: int) -> dict[str, Any]:
    """Feature-detected transport kwargs for the configured read block size.

    Returns ``{"max_input_block_size": N}`` when a non-conservative size is
    configured AND the installed pylxpweb transports accept the parameter
    (added after 0.9.36b19); otherwise ``{}``, so transport construction
    stays silently conservative on released library versions (#254, same
    fallback approach as #281).

    Detection uses ``ModbusTransport`` as the representative signature — the
    parameter ships on all local transports in the same pylxpweb release.
    """
    if max_input_block_size <= _CONSERVATIVE_BLOCK_REGISTERS:
        return {}
    from pylxpweb.transports import ModbusTransport

    if (
        "max_input_block_size"
        not in inspect.signature(ModbusTransport.__init__).parameters
    ):
        _warn_block_size_unsupported()
        return {}
    return {"max_input_block_size": max_input_block_size}


def transport_config_block_size_kwargs(max_input_block_size: int) -> dict[str, Any]:
    """Feature-detected ``TransportConfig`` kwargs for the read block size.

    ``TransportConfig`` is a dataclass — passing an unknown field raises
    TypeError on released pylxpweb (0.9.36b19), so the field is included
    only when the installed library defines it (#254).
    """
    if max_input_block_size <= _CONSERVATIVE_BLOCK_REGISTERS:
        return {}
    from pylxpweb.transports.config import TransportConfig

    if not any(
        f.name == "max_input_block_size" for f in dataclasses.fields(TransportConfig)
    ):
        _warn_block_size_unsupported()
        return {}
    return {"max_input_block_size": max_input_block_size}


def _build_transport_configs(
    config_list: list[dict[str, Any]],
    max_input_block_size: int | None = None,
) -> list[Any]:
    """Convert stored config dicts to TransportConfig objects.

    Args:
        config_list: List of transport config dicts from CONF_LOCAL_TRANSPORTS.
            Each dict should have: serial, transport_type, host, port, and
            type-specific fields (unit_id for modbus, dongle_serial for dongle).
        max_input_block_size: Configured Modbus read block size in registers
            (#254). Included in the configs only when non-conservative AND the
            installed pylxpweb supports it; None means "not configured".

    Returns:
        List of TransportConfig objects ready for Station.attach_local_transports().
    """
    from pylxpweb.transports.config import TransportConfig, TransportType

    block_size_kwargs = (
        transport_config_block_size_kwargs(max_input_block_size)
        if max_input_block_size is not None
        else {}
    )

    configs = []
    for item in config_list:
        try:
            transport_type_str = item.get("transport_type", "modbus_tcp")
            transport_type = TransportType(transport_type_str)

            inverter_family = _parse_inverter_family(item.get("inverter_family"))

            # Build type-specific kwargs
            extra_kwargs: dict[str, Any] = dict(block_size_kwargs)
            if transport_type == TransportType.MODBUS_TCP:
                extra_kwargs["unit_id"] = item.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
            elif transport_type == TransportType.WIFI_DONGLE:
                extra_kwargs["dongle_serial"] = item.get("dongle_serial", "")
            elif transport_type == TransportType.MODBUS_SERIAL:
                # Coerce numeric fields defensively: entries stored by older
                # versions (or hand-edited) may hold strings/None, which would
                # raise TypeError deep in TransportConfig validation and abort
                # the whole setup instead of skipping one bad config (#233).
                extra_kwargs["unit_id"] = int(
                    item.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
                )
                extra_kwargs["serial_port"] = str(item.get("serial_port", ""))
                extra_kwargs["serial_baudrate"] = int(
                    item.get("serial_baudrate", 19200)
                )
                extra_kwargs["serial_parity"] = str(item.get("serial_parity", "N"))
                extra_kwargs["serial_stopbits"] = int(item.get("serial_stopbits", 1))

            # Serial transports have no host/port in stored config dicts;
            # TransportConfig requires both positionally but skips them in
            # MODBUS_SERIAL validation, so pass placeholders (#233).
            if transport_type == TransportType.MODBUS_SERIAL:
                config = TransportConfig(
                    host=item.get("host", ""),
                    port=item.get("port", 0),
                    serial=item["serial"],
                    transport_type=transport_type,
                    inverter_family=inverter_family,
                    **extra_kwargs,
                )
                _LOGGER.debug(
                    "Built TransportConfig for %s: type=%s, port=%s",
                    item["serial"],
                    transport_type_str,
                    item.get("serial_port", ""),
                )
            else:
                config = TransportConfig(
                    host=item["host"],
                    port=item["port"],
                    serial=item["serial"],
                    transport_type=transport_type,
                    inverter_family=inverter_family,
                    **extra_kwargs,
                )
                _LOGGER.debug(
                    "Built TransportConfig for %s: type=%s, host=%s:%d",
                    item["serial"],
                    transport_type_str,
                    item["host"],
                    item["port"],
                )

            configs.append(config)

        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Failed to build TransportConfig from %s: %s", item, err)
            continue

    return configs


def _get_transport_label(connection_type: str) -> str:
    """Return a human-readable transport label for the connection_transport sensor.

    Args:
        connection_type: One of the CONNECTION_TYPE_* constants or transport type.

    Returns:
        Human-readable label like "Cloud", "Modbus", "Dongle".
    """
    labels = {
        "http": "Cloud",
        "modbus": "Modbus",
        "dongle": "Dongle",
        "hybrid": "Hybrid",
        "local": "Local",
    }
    return labels.get(connection_type, connection_type.capitalize())
