"""Sensor mapping functions and constants for the EG4 coordinator.

Pure data-transformation functions extracted from coordinator.py for
maintainability. These map pylxpweb transport/device objects to sensor
key dictionaries used by Home Assistant entities.
"""

import logging
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_MODBUS_UNIT_ID,
    GRID_TYPE_SINGLE_PHASE,
    GRID_TYPE_SPLIT_PHASE,
    GRID_TYPE_THREE_PHASE,
    INVERTER_FAMILY_DEFAULT_MODELS,
    LEGACY_FAMILY_MAP,
)

_LOGGER = logging.getLogger(__name__)


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
        "pv_total_power",
        "battery_voltage",
        "battery_current",
        "state_of_charge",
        "battery_charge_power",
        "battery_discharge_power",
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
        "grid_current_l1",
        "grid_current_l2",
        "grid_current_l3",
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
    }
)

BATTERY_BANK_KEYS: frozenset[str] = frozenset(
    {
        "battery_bank_soc",
        "battery_bank_voltage",
        "battery_bank_current",
        "battery_bank_charge_power",
        "battery_bank_discharge_power",
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
        "battery_bank_min_soh",
        "battery_bank_max_cell_temp",
        "battery_bank_temp_delta",
        "battery_bank_cell_voltage_delta_max",
        "battery_bank_soc_delta",
        "battery_bank_soh_delta",
        "battery_bank_voltage_delta",
        "battery_bank_cycle_count_delta",
    }
)

INVERTER_COMPUTED_KEYS: frozenset[str] = frozenset(
    {
        "consumption_power",
        "total_load_power",
        "battery_power",
        "rectifier_power",
        "grid_import_power",
        "eps_power_l1",
        "eps_power_l2",
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
    | BATTERY_BANK_KEYS
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
        "hybrid_power",
        "phase_lock_frequency",
        "off_grid",
        "smart_port1_status",
        "smart_port2_status",
        "smart_port3_status",
        "smart_port4_status",
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
        "firmware_version",
        "connection_transport",
        "transport_host",
        "midbox_last_polled",
    }
)

# Smart port power keys that should NOT be included in static entity creation.
# These are dynamically added by _filter_unused_smart_port_sensors() based on
# actual port status, so only active ports get entities.
# Includes per-port L1/L2 keys AND per-port aggregate keys (computed by
# _calculate_gridboss_aggregates from L1+L2), plus total aggregates.
GRIDBOSS_SMART_PORT_POWER_KEYS: frozenset[str] = frozenset(
    [
        f"{prefix}{port}_power_l{phase}"
        for prefix in ("smart_load", "ac_couple")
        for port in range(1, 5)
        for phase in (1, 2)
    ]
    + [
        f"{prefix}{port}_power"
        for prefix in ("smart_load", "ac_couple")
        for port in range(1, 5)
    ]
    + ["smart_load_power", "ac_couple_power"]
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
        "parallel_battery_charge_power",
        "parallel_battery_discharge_power",
        "parallel_battery_power",
        "parallel_battery_soc",
        "parallel_battery_max_capacity",
        "parallel_battery_current_capacity",
        "parallel_battery_voltage",
        "parallel_battery_current",
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


def _build_runtime_sensor_mapping(runtime_data: Any) -> dict[str, Any]:
    """Build sensor mapping from runtime data object.

    This helper extracts runtime data from a transport's RuntimeData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Args:
        runtime_data: RuntimeData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
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
        "grid_power": runtime_data.grid_power,
        "grid_export_power": runtime_data.power_to_grid,
        # Inverter output
        "ac_power": runtime_data.inverter_power,
        # Note: load_power removed - register 27 (pToUser) is grid import, NOT consumption
        # Use consumption_power sensor instead (computed from energy balance)
        # EPS/Backup - 3-phase R/S/T (LXP) and split-phase L1/L2 (EG4_OFFGRID/EG4_HYBRID)
        "eps_voltage_r": runtime_data.eps_voltage_r,
        "eps_voltage_s": runtime_data.eps_voltage_s,
        "eps_voltage_t": runtime_data.eps_voltage_t,
        "eps_voltage_l1": runtime_data.eps_l1_voltage,
        "eps_voltage_l2": runtime_data.eps_l2_voltage,
        "eps_frequency": runtime_data.eps_frequency,
        "eps_power": runtime_data.eps_power,
        # Note: consumption_power is NOT set here - it's computed by the coordinator
        # using inverter.consumption_power (energy balance calculation from pylxpweb)
        # Output power (split-phase total)
        "output_power": runtime_data.output_power,
        # Generator
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
        # BT Temperature (Modbus register 108, local-only)
        # Only include if value is present (not available via HTTP API)
        **(
            {"bt_temperature": runtime_data.temperature_t1}
            if runtime_data.temperature_t1 is not None
            else {}
        ),
        # Status
        "status_code": runtime_data.device_status,
        # Inverter RMS current (3-phase R/S/T mapped to L1/L2/L3)
        # For local mode (Modbus): I_IINV_RMS (reg 18), I_IINV_RMS_S (reg 190), I_IINV_RMS_T (reg 191)
        # For HTTP mode: These values are not returned by the cloud API
        "grid_current_l1": runtime_data.inverter_rms_current_r,
        "grid_current_l2": runtime_data.inverter_rms_current_s,
        "grid_current_l3": runtime_data.inverter_rms_current_t,
    }


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


def _build_energy_sensor_mapping(energy_data: Any) -> dict[str, Any]:
    """Build sensor mapping from energy data object.

    This helper extracts energy data from a transport's EnergyData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Consumption is computed from energy balance rather than reading the
    ``load_energy_*`` registers, which are actually Erec (AC charge from grid).

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
    }


def _build_battery_bank_sensor_mapping(battery_data: Any) -> dict[str, Any]:
    """Build sensor mapping from battery bank data object.

    Computes cross-battery diagnostic metrics directly from the transport
    BatteryData objects, mirroring BatteryBank's OOP properties for LOCAL mode.

    Args:
        battery_data: BatteryBankData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    # Calculate battery_power with fallback:
    # Primary: charge_power - discharge_power (matches charge/discharge sensors)
    # Fallback: voltage * current (from battery_power property)
    charge = battery_data.charge_power
    discharge = battery_data.discharge_power

    _LOGGER.debug(
        "LOCAL battery_bank: count=%s, voltage=%s, current=%s, "
        "charge=%s, discharge=%s, soc=%s, capacity=%s",
        battery_data.battery_count,
        battery_data.voltage,
        battery_data.current,
        charge,
        discharge,
        battery_data.soc,
        battery_data.max_capacity,
    )

    battery_power: float | None = None
    if charge is not None and discharge is not None:
        battery_power = charge - discharge
    elif battery_data.battery_power is not None:
        battery_power = battery_data.battery_power
    else:
        _LOGGER.warning(
            "LOCAL battery_bank_power: cannot calculate - "
            "voltage=%s, current=%s, charge=%s, discharge=%s",
            battery_data.voltage,
            battery_data.current,
            charge,
            discharge,
        )

    sensors: dict[str, Any] = {
        "battery_bank_soc": battery_data.soc,
        "battery_bank_voltage": battery_data.voltage,
        "battery_bank_current": battery_data.current,
        "battery_bank_charge_power": battery_data.charge_power,
        "battery_bank_discharge_power": battery_data.discharge_power,
        "battery_bank_power": battery_power,
        "battery_bank_max_capacity": battery_data.max_capacity,
        "battery_bank_current_capacity": battery_data.current_capacity,
        "battery_bank_remain_capacity": battery_data.remain_capacity,
        "battery_bank_full_capacity": battery_data.full_capacity,
        "battery_bank_capacity_percent": battery_data.capacity_percent,
        "battery_bank_count": battery_data.battery_count,
        "battery_bank_status": battery_data.status,
        "battery_status": battery_data.status,
        # Last polled timestamp for battery bank device
        "battery_bank_last_polled": dt_util.utcnow(),
    }

    # Cross-battery diagnostics — computed by BatteryBankData properties.
    # Properties return None when insufficient data, so only add non-None values.
    diagnostic_sensors = {
        "battery_bank_min_soh": battery_data.min_soh,
        "battery_bank_max_cell_temp": battery_data.max_cell_temp,
        "battery_bank_temp_delta": battery_data.temp_delta,
        "battery_bank_cell_voltage_delta_max": battery_data.cell_voltage_delta_max,
        "battery_bank_soc_delta": battery_data.soc_delta,
        "battery_bank_soh_delta": battery_data.soh_delta,
        "battery_bank_voltage_delta": battery_data.voltage_delta,
        "battery_bank_cycle_count_delta": battery_data.cycle_count_delta,
    }
    sensors.update({k: v for k, v in diagnostic_sensors.items() if v is not None})

    return sensors


def _build_individual_battery_mapping(battery: Any) -> dict[str, Any]:
    """Build sensor mapping from individual BatteryData object (LOCAL mode).

    Maps pylxpweb transport's BatteryData fields to sensor keys that match
    the expected format used by HTTP mode (from Battery objects).

    Args:
        battery: BatteryData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
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
    }


def _build_gridboss_sensor_mapping(mid_device: Any) -> dict[str, Any]:
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


def _features_from_family(
    family_str: str | None,
    device_type_code: int | None = None,
    grid_type: str | None = None,
) -> dict[str, Any]:
    """Derive feature flags from inverter family and device type code.

    Used by the static-data first refresh to provide correct feature-based
    sensor filtering without reading Modbus registers. The four feature
    keys control which phase-specific and capability-specific sensors are
    created by _should_create_sensor() in sensor.py.

    Args:
        family_str: Inverter family from config (e.g., "EG4_HYBRID", "EG4_OFFGRID", "LXP").
        device_type_code: Raw device type code from register 19, stored in config
            during discovery. Used to distinguish LXP-EU (12, three-phase) from
            LXP-LB (44, single/split-phase).
        grid_type: User-selected grid type override. When provided, overrides
            the hardcoded split/three-phase flags. None means no override
            (backward compatible with existing configs).

    Returns:
        Feature dict suitable for _should_create_sensor() filtering.
        Empty dict when family is unknown (conservative: creates all sensors).
    """
    if not family_str:
        return {}

    # Normalise legacy names (e.g., "SNA" → "EG4_OFFGRID")
    mapped = LEGACY_FAMILY_MAP.get(family_str, family_str)

    # Feature mapping mirrors pylxpweb FAMILY_DEFAULT_FEATURES.
    # Only the four keys used by _should_create_sensor() are needed here.
    features: dict[str, Any] = {}

    # EG4_OFFGRID (12000XP, 6000XP): US split-phase, discharge recovery
    if mapped == "EG4_OFFGRID":
        features = {
            "inverter_family": mapped,
            "supports_split_phase": True,
            "supports_three_phase": False,
            "supports_discharge_recovery_hysteresis": True,
            "supports_volt_watt_curve": False,
        }

    # EG4_HYBRID (18kPV, 12kPV, FlexBOSS): US split-phase, volt-watt
    # US market — L1/L2 registers valid, R/S/T registers contain garbage
    elif mapped == "EG4_HYBRID":
        features = {
            "inverter_family": mapped,
            "supports_split_phase": True,
            "supports_three_phase": False,
            "supports_discharge_recovery_hysteresis": False,
            "supports_volt_watt_curve": True,
        }

    # LXP family: device_type_code distinguishes EU from LB variants.
    # - LXP-EU (device_type_code 12): three-phase, no split-phase
    # - LXP-LB (device_type_code 44): NOT three-phase, volt-watt capable
    #   LXP-LB includes US (split-phase) and BR (single-phase) variants;
    #   the us_version flag from HOLD_MODEL determines split vs single,
    #   but we can safely rule out three-phase from device_type_code alone.
    elif mapped == "LXP" and device_type_code == 12:  # DEVICE_TYPE_CODE_LXP_EU
        features = {
            "inverter_family": mapped,
            "supports_split_phase": False,
            "supports_three_phase": True,
            "supports_discharge_recovery_hysteresis": False,
            "supports_volt_watt_curve": True,
        }
    elif mapped == "LXP" and device_type_code == 44:  # DEVICE_TYPE_CODE_LXP_BR/LXP_LB
        features = {
            "inverter_family": mapped,
            "supports_split_phase": True,
            "supports_three_phase": False,
            "supports_discharge_recovery_hysteresis": False,
            "supports_volt_watt_curve": True,
        }

    # Unknown family or LXP without device_type_code → conservative fallback
    # creates all sensors; real feature detection after Modbus reads refines.

    # Apply user-selected grid type override once, regardless of family branch
    if features and grid_type:
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


def _build_transport_configs(
    config_list: list[dict[str, Any]],
) -> list[Any]:
    """Convert stored config dicts to TransportConfig objects.

    Args:
        config_list: List of transport config dicts from CONF_LOCAL_TRANSPORTS.
            Each dict should have: serial, transport_type, host, port, and
            type-specific fields (unit_id for modbus, dongle_serial for dongle).

    Returns:
        List of TransportConfig objects ready for Station.attach_local_transports().
    """
    from pylxpweb.transports.config import TransportConfig, TransportType

    configs = []
    for item in config_list:
        try:
            transport_type_str = item.get("transport_type", "modbus_tcp")
            transport_type = TransportType(transport_type_str)

            inverter_family = _parse_inverter_family(item.get("inverter_family"))

            # Build type-specific kwargs
            extra_kwargs: dict[str, Any] = {}
            if transport_type == TransportType.MODBUS_TCP:
                extra_kwargs["unit_id"] = item.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
            elif transport_type == TransportType.WIFI_DONGLE:
                extra_kwargs["dongle_serial"] = item.get("dongle_serial", "")
            elif transport_type == TransportType.MODBUS_SERIAL:
                extra_kwargs["unit_id"] = item.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
                extra_kwargs["serial_port"] = item.get("serial_port", "")
                extra_kwargs["serial_baudrate"] = item.get("serial_baudrate", 19200)
                extra_kwargs["serial_parity"] = item.get("serial_parity", "N")
                extra_kwargs["serial_stopbits"] = item.get("serial_stopbits", 1)

            # For serial transport, host/port are optional
            if transport_type == TransportType.MODBUS_SERIAL:
                config = TransportConfig(
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

        except (KeyError, ValueError) as err:
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
