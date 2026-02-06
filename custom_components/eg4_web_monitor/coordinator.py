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
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )

    from pylxpweb.transports import ModbusSerialTransport, ModbusTransport
else:
    from homeassistant.helpers.update_coordinator import (  # type: ignore[assignment]
        DataUpdateCoordinator,
        UpdateFailed,
    )

from pylxpweb import LuxpowerClient
from pylxpweb.devices import Battery, Station
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
    LuxpowerDeviceError,
)

from .const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INCLUDE_AC_COUPLE_PV,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
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
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    MANUFACTURER,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    DOMAIN,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_DEFAULT_MODELS,
    LEGACY_FAMILY_MAP,
)
from .coordinator_mixins import (
    BackgroundTaskMixin,
    DeviceInfoMixin,
    DeviceProcessingMixin,
    DSTSyncMixin,
    FirmwareUpdateMixin,
    ParameterManagementMixin,
)
from .utils import (
    CircuitBreaker,
    clean_battery_display_name,
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
        "load",
        "yield_lifetime",
        "charging_lifetime",
        "discharging_lifetime",
        "grid_import_lifetime",
        "grid_export_lifetime",
        "load_lifetime",
    }
)

BATTERY_BANK_KEYS: frozenset[str] = frozenset(
    {
        "battery_bank_soc",
        "battery_bank_voltage",
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


def _build_energy_sensor_mapping(energy_data: Any) -> dict[str, Any]:
    """Build sensor mapping from energy data object.

    This helper extracts energy data from a transport's EnergyData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

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
        "load": energy_data.load_energy_today,
        # Lifetime energy (kWh)
        "yield_lifetime": energy_data.pv_energy_total,
        "charging_lifetime": energy_data.charge_energy_total,
        "discharging_lifetime": energy_data.discharge_energy_total,
        "grid_import_lifetime": energy_data.grid_import_total,
        "grid_export_lifetime": energy_data.grid_export_total,
        "load_lifetime": energy_data.load_energy_total,
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
    # Calculate battery_power with fallback if voltage/current unavailable
    # Primary: charge_power - discharge_power (positive = charging, negative = discharging)
    # This matches the charge/discharge sensors for consistency
    # Fallback: voltage * current (from battery_power property)
    charge = battery_data.charge_power
    discharge = battery_data.discharge_power
    voltage = battery_data.voltage
    current = battery_data.current

    # Log battery_bank_count for debugging issue #129
    battery_count = battery_data.battery_count
    _LOGGER.debug(
        "LOCAL battery_bank: count=%s, voltage=%s, current=%s, "
        "charge=%s, discharge=%s, soc=%s, capacity=%s",
        battery_count,
        voltage,
        current,
        charge,
        discharge,
        battery_data.soc,
        battery_data.max_capacity,
    )

    battery_power: float | None = None
    if charge is not None and discharge is not None:
        # Use charge - discharge for consistency with charge/discharge power sensors
        battery_power = charge - discharge
        _LOGGER.debug(
            "LOCAL battery_bank_power: using charge-discharge: "
            "charge=%s, discharge=%s, result=%s",
            charge,
            discharge,
            battery_power,
        )
    elif battery_data.battery_power is not None:
        # Fallback to V*I calculation
        battery_power = battery_data.battery_power
        _LOGGER.debug(
            "LOCAL battery_bank_power: using V*I fallback: "
            "voltage=%s, current=%s, result=%s",
            voltage,
            current,
            battery_power,
        )
    else:
        _LOGGER.warning(
            "LOCAL battery_bank_power: cannot calculate - "
            "voltage=%s, current=%s, charge=%s, discharge=%s",
            voltage,
            current,
            charge,
            discharge,
        )

    sensors: dict[str, Any] = {
        "battery_bank_soc": battery_data.soc,
        "battery_bank_voltage": battery_data.voltage,
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

    # Cross-battery diagnostics — computed by BatteryBankData properties
    # Properties return None when insufficient data, so only add if available
    diagnostic_map = {
        "battery_bank_min_soh": battery_data.min_soh,
        "battery_bank_max_cell_temp": battery_data.max_cell_temp,
        "battery_bank_temp_delta": battery_data.temp_delta,
        "battery_bank_cell_voltage_delta_max": battery_data.cell_voltage_delta_max,
        "battery_bank_soc_delta": battery_data.soc_delta,
        "battery_bank_soh_delta": battery_data.soh_delta,
        "battery_bank_voltage_delta": battery_data.voltage_delta,
        "battery_bank_cycle_count_delta": battery_data.cycle_count_delta,
    }
    for key, value in diagnostic_map.items():
        if value is not None:
            sensors[key] = value

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

    This helper extracts data from a MIDDevice's runtime properties
    and maps it to sensor keys matching SENSOR_TYPES definitions.

    Args:
        mid_device: MIDDevice object from pylxpweb with runtime data.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # Grid sensors
        "grid_power": getattr(mid_device, "grid_power", None),
        "grid_voltage": getattr(mid_device, "grid_voltage", None),
        "frequency": getattr(mid_device, "grid_frequency", None),
        "grid_power_l1": getattr(mid_device, "grid_l1_power", None),
        "grid_power_l2": getattr(mid_device, "grid_l2_power", None),
        "grid_voltage_l1": getattr(mid_device, "grid_l1_voltage", None),
        "grid_voltage_l2": getattr(mid_device, "grid_l2_voltage", None),
        "grid_current_l1": getattr(mid_device, "grid_l1_current", None),
        "grid_current_l2": getattr(mid_device, "grid_l2_current", None),
        # UPS sensors
        "ups_power": getattr(mid_device, "ups_power", None),
        "ups_voltage": getattr(mid_device, "ups_voltage", None),
        "ups_power_l1": getattr(mid_device, "ups_l1_power", None),
        "ups_power_l2": getattr(mid_device, "ups_l2_power", None),
        "load_voltage_l1": getattr(mid_device, "ups_l1_voltage", None),
        "load_voltage_l2": getattr(mid_device, "ups_l2_voltage", None),
        "ups_current_l1": getattr(mid_device, "ups_l1_current", None),
        "ups_current_l2": getattr(mid_device, "ups_l2_current", None),
        # Load sensors
        "load_power": getattr(mid_device, "load_power", None),
        "load_power_l1": getattr(mid_device, "load_l1_power", None),
        "load_power_l2": getattr(mid_device, "load_l2_power", None),
        "load_current_l1": getattr(mid_device, "load_l1_current", None),
        "load_current_l2": getattr(mid_device, "load_l2_current", None),
        # Consumption power for GridBOSS = load_power (CT measurement)
        "consumption_power": getattr(mid_device, "load_power", None),
        # Generator sensors
        "generator_power": getattr(mid_device, "generator_power", None),
        "generator_voltage": getattr(mid_device, "generator_voltage", None),
        "generator_frequency": getattr(mid_device, "generator_frequency", None),
        "generator_power_l1": getattr(mid_device, "generator_l1_power", None),
        "generator_power_l2": getattr(mid_device, "generator_l2_power", None),
        "generator_current_l1": getattr(mid_device, "generator_l1_current", None),
        "generator_current_l2": getattr(mid_device, "generator_l2_current", None),
        # Other sensors
        "hybrid_power": getattr(mid_device, "hybrid_power", None),
        "phase_lock_frequency": getattr(mid_device, "phase_lock_frequency", None),
        "off_grid": getattr(mid_device, "is_off_grid", None),
        # Smart port status
        "smart_port1_status": getattr(mid_device, "smart_port1_status", None),
        "smart_port2_status": getattr(mid_device, "smart_port2_status", None),
        "smart_port3_status": getattr(mid_device, "smart_port3_status", None),
        "smart_port4_status": getattr(mid_device, "smart_port4_status", None),
        # Smart load power (L1/L2)
        "smart_load1_power_l1": getattr(mid_device, "smart_load1_l1_power", None),
        "smart_load1_power_l2": getattr(mid_device, "smart_load1_l2_power", None),
        "smart_load2_power_l1": getattr(mid_device, "smart_load2_l1_power", None),
        "smart_load2_power_l2": getattr(mid_device, "smart_load2_l2_power", None),
        "smart_load3_power_l1": getattr(mid_device, "smart_load3_l1_power", None),
        "smart_load3_power_l2": getattr(mid_device, "smart_load3_l2_power", None),
        "smart_load4_power_l1": getattr(mid_device, "smart_load4_l1_power", None),
        "smart_load4_power_l2": getattr(mid_device, "smart_load4_l2_power", None),
        # AC couple power (L1/L2)
        "ac_couple1_power_l1": getattr(mid_device, "ac_couple1_l1_power", None),
        "ac_couple1_power_l2": getattr(mid_device, "ac_couple1_l2_power", None),
        "ac_couple2_power_l1": getattr(mid_device, "ac_couple2_l1_power", None),
        "ac_couple2_power_l2": getattr(mid_device, "ac_couple2_l2_power", None),
        "ac_couple3_power_l1": getattr(mid_device, "ac_couple3_l1_power", None),
        "ac_couple3_power_l2": getattr(mid_device, "ac_couple3_l2_power", None),
        "ac_couple4_power_l1": getattr(mid_device, "ac_couple4_l1_power", None),
        "ac_couple4_power_l2": getattr(mid_device, "ac_couple4_l2_power", None),
        # Energy sensors - aggregate only (L2 energy registers always read 0)
        "ups_today": getattr(mid_device, "e_ups_today", None),
        "ups_total": getattr(mid_device, "e_ups_total", None),
        "grid_export_today": getattr(mid_device, "e_to_grid_today", None),
        "grid_export_total": getattr(mid_device, "e_to_grid_total", None),
        "grid_import_today": getattr(mid_device, "e_to_user_today", None),
        "grid_import_total": getattr(mid_device, "e_to_user_total", None),
        "load_today": getattr(mid_device, "e_load_today", None),
        "load_total": getattr(mid_device, "e_load_total", None),
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
        from pylxpweb.devices.inverters._features import InverterFamily

        return InverterFamily(mapped_family)
    except ValueError:
        _LOGGER.warning("Unknown inverter family '%s', using default", family_str)
        return None


def _features_from_family(
    family_str: str | None,
    device_type_code: int | None = None,
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
    #
    # EG4_OFFGRID (12000XP, 6000XP): US split-phase, discharge recovery
    if mapped == "EG4_OFFGRID":
        return {
            "inverter_family": mapped,
            "supports_split_phase": True,
            "supports_three_phase": False,
            "supports_discharge_recovery_hysteresis": True,
            "supports_volt_watt_curve": False,
        }

    # EG4_HYBRID (18kPV, 12kPV, FlexBOSS): US split-phase, volt-watt
    # US market — L1/L2 registers valid, R/S/T registers contain garbage
    if mapped == "EG4_HYBRID":
        return {
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
    if mapped == "LXP" and device_type_code is not None:
        # LXP-EU: European three-phase inverter
        if device_type_code == 12:  # DEVICE_TYPE_CODE_LXP_EU
            return {
                "inverter_family": mapped,
                "supports_split_phase": False,
                "supports_three_phase": True,
                "supports_discharge_recovery_hysteresis": False,
                "supports_volt_watt_curve": True,
            }
        # LXP-LB: US/Brazil single or split-phase (never three-phase)
        if device_type_code == 44:  # DEVICE_TYPE_CODE_LXP_BR/LXP_LB
            return {
                "inverter_family": mapped,
                "supports_split_phase": True,
                "supports_three_phase": False,
                "supports_discharge_recovery_hysteresis": False,
                "supports_volt_watt_curve": True,
            }

    # Unknown family or LXP without device_type_code → conservative fallback
    # creates all sensors; real feature detection after Modbus reads refines.
    return {}


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


class EG4DataUpdateCoordinator(
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
        self._dongle_transport: Any = None
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
                    inverter_family=self._get_inverter_family(family_str),
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
                    inverter_family=self._get_inverter_family(family_str),
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

        # Device tracking
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_sensors: dict[str, list[str]] = {}

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

        # Circuit breaker for API resilience
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)

        # Temporary device info storage for model extraction
        self._temp_device_info: dict[str, Any] = {}

        # Individual energy processing queue
        self._pending_individual_energy_serials: list[str] = []

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
        # Local/Hybrid: runs at sensor interval (local transport polls fast)
        if self.connection_type == CONNECTION_TYPE_HTTP:
            update_interval = timedelta(seconds=http_interval_seconds)
        else:
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
                return self.data
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
                (227, 1),  # System charge SOC limit (HOLD_SYSTEM_CHARGE_SOC_LIMIT)
                (231, 2),  # Grid peak shaving power (_12K_HOLD_GRID_PEAK_SHAVING_POWER)
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

    @staticmethod
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

    def _build_local_device_data(
        self,
        inverter: "BaseInverter",
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

        device_data["sensors"]["firmware_version"] = firmware_version
        device_data["sensors"]["connection_transport"] = self._get_transport_label(
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
                else:
                    inverter = await BaseInverter.from_modbus_transport(
                        transport, model=model
                    )
                self._inverter_cache[serial] = inverter
            else:
                inverter = self._inverter_cache[serial]

            include_params = self._local_parameters_loaded
            await inverter.refresh(force=True, include_parameters=include_params)

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
            inverter_family = self._get_inverter_family(family_str)

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

                firmware_version: str = "Unknown"
                if hasattr(mid_device, "firmware_version"):
                    firmware_version = mid_device.firmware_version or "Unknown"

                if not mid_device.has_data:
                    raise TransportReadError(
                        f"Failed to read runtime data for GridBOSS {serial}"
                    )

                sensors = _build_gridboss_sensor_mapping(mid_device)
                sensors = {k: v for k, v in sensors.items() if v is not None}
                self._filter_unused_smart_port_sensors(sensors, mid_device)
                self._calculate_gridboss_aggregates(sensors)
                sensors["firmware_version"] = firmware_version
                sensors["connection_transport"] = self._get_transport_label(
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

                # Skip parameters on first refresh to reduce Modbus traffic
                # during HA's setup timeout window. Parameters + feature
                # detection are deferred to a background task after setup.
                include_params = self._local_parameters_loaded
                await inverter.refresh(force=True, include_parameters=include_params)

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

                if serial not in self._firmware_cache:
                    fw = "Unknown"
                    transport = inverter._transport
                    if transport and hasattr(transport, "read_firmware_version"):
                        read_fw = getattr(transport, "read_firmware_version")
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

                    if hasattr(battery_data, "batteries") and battery_data.batteries:
                        for batt in battery_data.batteries:
                            battery_key = f"{serial}-{batt.battery_index + 1:02d}"
                            device_data["batteries"][battery_key] = (
                                _build_individual_battery_mapping(batt)
                            )
                        _LOGGER.debug(
                            "LOCAL: Added %d individual batteries for %s",
                            len(battery_data.batteries),
                            serial,
                        )

                device_data["sensors"]["firmware_version"] = firmware_version
                device_data["sensors"]["connection_transport"] = (
                    self._get_transport_label(
                        "dongle" if transport_type == "wifi_dongle" else "modbus"
                    )
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

                if self._local_parameters_loaded:
                    transport = inverter._transport
                    if transport:
                        param_data = await self._read_modbus_parameters(transport)
                    else:
                        param_data = {}
                    processed["parameters"][serial] = param_data
                else:
                    # Defer parameter reads on first refresh to stay within
                    # HA's setup timeout. Empty dict is safe — switch/number
                    # entities will show unknown until background load completes.
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
                sensor_keys = GRIDBOSS_SENSOR_KEYS
                device_type = "gridboss"
            else:
                sensor_keys = ALL_INVERTER_SENSOR_KEYS
                device_type = "inverter"

            # Pre-populate sensors: keys present (for entity creation), values None
            sensors: dict[str, Any] = {k: None for k in sensor_keys}
            # Fill in known metadata from config entry
            sensors["firmware_version"] = firmware
            transport_type = config.get("transport_type", "modbus_tcp")
            sensors["connection_transport"] = self._get_transport_label(
                "dongle" if transport_type == "wifi_dongle" else "modbus"
            )
            sensors["transport_host"] = config.get("host", "")

            # Derive feature flags from inverter family and device_type_code so
            # that _should_create_sensor() filters phase-specific sensors correctly
            # even before Modbus-based feature detection runs.
            family_str = config.get("inverter_family")
            dtc = config.get("device_type_code")
            features = _features_from_family(family_str, dtc) if not is_gridboss else {}

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

        return processed

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

        # Track per-device availability for partial failure handling
        device_availability: dict[str, bool] = {}

        # Group transports by connection endpoint so that devices sharing
        # the same physical connection are polled sequentially, while
        # independent endpoints are polled concurrently.
        endpoint_groups: dict[str, list[dict[str, Any]]] = {}
        for config in self._local_transport_configs:
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
            # Note: grid_export_power is redundant — grid_power is signed
            # (positive=import, negative=export).
            power_sensors = [
                "pv_total_power",
                "grid_power",
                "consumption_power",
                "eps_power",
                "battery_charge_power",
                "battery_discharge_power",
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

            # Remap battery sensors to parallel_battery_* keys for consistency
            # with cloud mode (which uses _process_parallel_group_object).
            # This ensures the same entity IDs regardless of connection mode.
            charge = group_sensors.pop("battery_charge_power", 0.0)
            discharge = group_sensors.pop("battery_discharge_power", 0.0)
            group_sensors["parallel_battery_charge_power"] = charge
            group_sensors["parallel_battery_discharge_power"] = discharge
            # Battery power: positive = discharging (adds to sources), negative = charging
            group_sensors["parallel_battery_power"] = discharge - charge

            if soc_count > 0:
                group_sensors["parallel_battery_soc"] = round(total_soc / soc_count, 1)

            if voltage_count > 0:
                group_sensors["parallel_battery_voltage"] = round(
                    total_battery_voltage / voltage_count, 1
                )

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

            # Override grid/load power and energy with GridBOSS data if available.
            # The GridBOSS has the grid CTs and is the authoritative source for
            # grid interaction — inverters don't see the actual grid import/export.
            gridboss_sensor_mapping = {
                # Power sensors (real-time CT measurements)
                "grid_power": "grid_power",
                "grid_power_l1": "grid_power_l1",
                "grid_power_l2": "grid_power_l2",
                "load_power": "load_power",
                "load_power_l1": "load_power_l1",
                "load_power_l2": "load_power_l2",
                # Energy sensors (accumulated totals)
                "grid_export_today": "grid_export",
                "grid_export_total": "grid_export_lifetime",
                "grid_import_today": "grid_import",
                "grid_import_total": "grid_import_lifetime",
                "load_today": "consumption",
                "load_total": "consumption_lifetime",
            }
            for serial, device_data in processed.get("devices", {}).items():
                if device_data.get("type") != "gridboss":
                    continue
                gb_sensors = device_data.get("sensors", {})
                for gb_key, pg_key in gridboss_sensor_mapping.items():
                    gb_val = gb_sensors.get(gb_key)
                    if gb_val is not None:
                        group_sensors[pg_key] = float(gb_val)
                        _LOGGER.debug(
                            "LOCAL: Parallel group %s: using GridBOSS %s=%s for %s",
                            group_name,
                            gb_key,
                            gb_val,
                            pg_key,
                        )
                # Add GridBOSS load_power to consumption_power total.
                # Total consumption = inverter eps_power (already aggregated) + GridBOSS load_power
                # The GridBOSS CT measures main panel loads; inverter EPS loads are on separate
                # backup circuits not measured by GridBOSS.
                load_power = gb_sensors.get("load_power")
                if load_power is not None:
                    existing = group_sensors.get("consumption_power", 0.0)
                    group_sensors["consumption_power"] = existing + float(load_power)
                    _LOGGER.debug(
                        "LOCAL: Parallel group %s: consumption_power = inverter_sum(%s) + "
                        "gridboss_load(%s) = %s",
                        group_name,
                        existing,
                        load_power,
                        group_sensors["consumption_power"],
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

                # Calculate AC couple power for consumption (always include, regardless of option)
                ac_couple_for_consumption = 0.0
                for port_num in range(1, 5):
                    status_key = f"smart_port{port_num}_status"
                    status = gb_sensors.get(status_key)
                    if status == 2:  # AC Couple mode
                        l1 = gb_sensors.get(f"ac_couple{port_num}_power_l1") or 0
                        l2 = gb_sensors.get(f"ac_couple{port_num}_power_l2") or 0
                        ac_couple_for_consumption += float(l1) + float(l2)

                # Skip energy balance recalculation - GridBOSS load_power (CT measurement)
                # is the authoritative source for consumption, already set above

                break  # Only one GridBOSS per system

            # Add last polled timestamp for parallel group
            group_sensors["parallel_group_last_polled"] = dt_util.utcnow()

            # Create parallel group device entry
            # Note: We create groups even with 1 inverter if parallel_number > 0,
            # since this indicates the inverter is configured for parallel operation
            # (e.g., single inverter + GridBOSS setup)
            group_device_id = f"parallel_group_{first_serial}"
            processed["devices"][group_device_id] = {
                "type": "parallel_group",
                "name": f"Parallel Group {group_name}",
                "group_name": group_name,
                "first_device_serial": first_serial,
                "member_count": device_count,
                "member_serials": [serial for serial, _ in group_devices],
                "sensors": group_sensors,
            }

            # Register parallel group device in device registry immediately
            # This must happen BEFORE entity platforms create entities that
            # reference this device via via_device
            from homeassistant.helpers import device_registry as dr

            device_registry = dr.async_get(self.hass)
            device_registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, group_device_id)},
                name=f"Parallel Group {group_name}",
                manufacturer=MANUFACTURER,
                model="Parallel Group",
            )

            _LOGGER.info(
                "LOCAL: Created parallel group %s with %d devices: %s sensors",
                group_name,
                device_count,
                len(group_sensors),
            )

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
                label = self._get_transport_label(transport_type)
                device_data["sensors"]["connection_transport"] = f"Hybrid ({label})"
                if hasattr(transport, "host"):
                    device_data["sensors"]["transport_host"] = transport.host
            else:
                device_data["sensors"]["connection_transport"] = "Cloud"

        return data

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

            # Log hybrid mode status
            if self.station.is_hybrid_mode:
                _LOGGER.info(
                    "Station is now in hybrid mode with %d local transport(s) attached",
                    result.matched,
                )

        except Exception as err:
            _LOGGER.error("Failed to attach local transports: %s", err)
            # Don't mark as attached so we can retry on next update
            self._local_transports_attached = False

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
            today_ymd = time.localtime()[:3]
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
            inv: BaseInverter,
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
            import time as _time

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
                    processed["devices"][
                        f"parallel_group_{group.first_device_serial}"
                    ] = group_data

                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            processed["devices"][
                                group.mid_device.serial_number
                            ] = await self._process_mid_device_object(group.mid_device)
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

    @staticmethod
    def _get_inverter_family(family_str: str | None) -> Any:
        """Convert inverter family string to InverterFamily enum.

        Delegates to module-level _parse_inverter_family().
        """
        return _parse_inverter_family(family_str)

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

    def has_http_api(self) -> bool:
        """Check if HTTP API is available (HTTP or Hybrid mode).

        Used to determine if HTTP-only features like Quick Charge are available.

        Returns:
            True if HTTP client is configured (HTTP or Hybrid mode).
        """
        return self.client is not None

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
