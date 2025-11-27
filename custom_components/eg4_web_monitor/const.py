"""Constants for the EG4 Web Monitor integration."""

from typing import TypedDict

from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)


class SensorConfig(TypedDict, total=False):
    """TypedDict for sensor configuration.

    Attributes:
        name: Display name for the sensor
        unit: Unit of measurement (e.g., UnitOfPower.WATT)
        device_class: Home Assistant device class (power, energy, voltage, etc.)
        state_class: Home Assistant state class (measurement, total, total_increasing)
        icon: MDI icon string (e.g., "mdi:solar-power")
        entity_category: Entity category (diagnostic, config, etc.)
        suggested_display_precision: Number of decimal places to display
    """

    name: str
    unit: str | None
    device_class: str | None
    state_class: str | None
    icon: str
    entity_category: EntityCategory | None
    suggested_display_precision: int


# Integration constants
DOMAIN = "eg4_web_monitor"
DEFAULT_UPDATE_INTERVAL = 30  # seconds
DEFAULT_BASE_URL = "https://monitor.eg4electronics.com"

# Configuration keys
CONF_BASE_URL = "base_url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_PLANT_ID = "plant_id"
CONF_PLANT_NAME = "plant_name"
CONF_DST_SYNC = "dst_sync"
CONF_LIBRARY_DEBUG = "library_debug"

# Device types
DEVICE_TYPE_INVERTER = "inverter"
DEVICE_TYPE_GRIDBOSS = "gridboss"
DEVICE_TYPE_BATTERY = "battery"

# Number entity limits
# AC Charge Power (kW)
AC_CHARGE_POWER_MIN = 0.0
AC_CHARGE_POWER_MAX = 15.0
AC_CHARGE_POWER_STEP = 0.1

# PV Charge Power (kW)
PV_CHARGE_POWER_MIN = 0
PV_CHARGE_POWER_MAX = 15
PV_CHARGE_POWER_STEP = 1

# Grid Peak Shaving Power (kW)
GRID_PEAK_SHAVING_POWER_MIN = 0.0
GRID_PEAK_SHAVING_POWER_MAX = 25.5
GRID_PEAK_SHAVING_POWER_STEP = 0.1

# Battery Charge/Discharge Current (A)
BATTERY_CURRENT_MIN = 0
BATTERY_CURRENT_MAX = 250
BATTERY_CURRENT_STEP = 1

# SOC Limits (%)
SOC_LIMIT_MIN = 0
SOC_LIMIT_MAX = 100
SOC_LIMIT_STEP = 1

# System Charge SOC Limit (%)
SYSTEM_CHARGE_SOC_LIMIT_MIN = 10
SYSTEM_CHARGE_SOC_LIMIT_MAX = 101
SYSTEM_CHARGE_SOC_LIMIT_STEP = 1

# Sensor types and their units
SENSOR_TYPES = {
    # Power sensors
    "ac_power": {
        "name": "AC Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
    },
    "dc_power": {
        "name": "DC Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
    },
    "load_power": {
        "name": "Load Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "consumption_power": {
        "name": "Consumption Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "grid_power": {
        "name": "Grid Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_import_power": {
        "name": "Grid Import Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower-import",
    },
    "grid_export_power": {
        "name": "Grid Export Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower-export",
    },
    "battery_power": {
        "name": "Battery Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "hybrid_power": {
        "name": "Hybrid Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power-variant-outline",
    },
    "battery_charge_power": {
        "name": "Battery Charge Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "battery_discharge_power": {
        "name": "Battery Discharge Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-minus",
    },
    "battery_status": {
        "name": "Battery Status",
        "icon": "mdi:battery-heart",
    },
    # Voltage sensors
    "ac_voltage": {
        "name": "AC Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:flash",
        "suggested_display_precision": 1,
    },
    "dc_voltage": {
        "name": "DC Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:flash",
    },
    "battery_voltage": {
        "name": "Battery Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    # Current sensors
    "ac_current": {
        "name": "AC Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-ac",
    },
    "dc_current": {
        "name": "DC Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-dc",
    },
    "battery_current": {
        "name": "Battery Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    # Energy sensors
    "total_energy": {
        "name": "Total Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:lightning-bolt",
    },
    "daily_energy": {
        "name": "Daily Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:calendar-today",
    },
    "monthly_energy": {
        "name": "Monthly Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:calendar-month",
    },
    "yearly_energy": {
        "name": "Yearly Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:calendar-year",
    },
    # Current day energy sensors (values need to be divided by 10)
    "yield": {
        "name": "Yield",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "discharging": {
        "name": "Discharging",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-arrow-down",
    },
    "charging": {
        "name": "Charging",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-arrow-up",
    },
    "consumption": {
        "name": "Consumption",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    "grid_export": {
        "name": "Grid Export",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    "grid_import": {
        "name": "Grid Import",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    # Lifetime energy sensors (values need to be divided by 10)
    "yield_lifetime": {
        "name": "Yield (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "discharging_lifetime": {
        "name": "Discharging (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-arrow-down",
    },
    "charging_lifetime": {
        "name": "Charging (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-arrow-up",
    },
    "consumption_lifetime": {
        "name": "Consumption (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    "grid_export_lifetime": {
        "name": "Grid Export (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    "grid_import_lifetime": {
        "name": "Grid Import (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    # Battery charge/discharge energy sensors (pylxpweb 0.3.3+)
    "battery_charge": {
        "name": "Battery Charge",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging",
    },
    "battery_discharge": {
        "name": "Battery Discharge",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-minus",
    },
    "battery_charge_lifetime": {
        "name": "Battery Charge (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging",
    },
    "battery_discharge_lifetime": {
        "name": "Battery Discharge (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-minus",
    },
    # Frequency
    "frequency": {
        "name": "Frequency",
        "unit": UnitOfFrequency.HERTZ,
        "device_class": "frequency",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
    },
    # Temperature
    "temperature": {
        "name": "Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    # Battery specific
    "state_of_charge": {
        "name": "State of Charge",
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "state_of_health": {
        "name": "State of Health",
        "unit": "%",
        "state_class": "measurement",
        "icon": "mdi:battery-heart",
    },
    "cycle_count": {
        "name": "Cycle Count",
        "state_class": "total_increasing",
        "icon": "mdi:counter",
    },
    # Battery Bank aggregate sensors (pylxpweb 0.3.3+)
    "battery_bank_voltage": {
        "name": "Battery Bank Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_bank_soc": {
        "name": "Battery Bank SOC",
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_bank_charge_power": {
        "name": "Battery Bank Charge Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "battery_bank_discharge_power": {
        "name": "Battery Bank Discharge Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-minus",
    },
    "battery_bank_power": {
        "name": "Battery Bank Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "battery_bank_max_capacity": {
        "name": "Battery Bank Max Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery-high",
    },
    "battery_bank_current_capacity": {
        "name": "Battery Bank Current Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery-medium",
    },
    "battery_bank_remain_capacity": {
        "name": "Battery Bank Remaining Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_bank_full_capacity": {
        "name": "Battery Bank Full Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery-high",
    },
    "battery_bank_capacity_percent": {
        "name": "Battery Bank Capacity Percent",
        "unit": "%",
        "state_class": "measurement",
        "icon": "mdi:battery-heart",
    },
    "battery_bank_count": {
        "name": "Battery Count",
        "state_class": "measurement",
        "icon": "mdi:counter",
        "entity_category": "diagnostic",
    },
    "battery_bank_status": {
        "name": "Battery Bank Status",
        "icon": "mdi:information",
        "entity_category": "diagnostic",
    },
    # Additional battery sensors from batteryArray
    "battery_real_voltage": {
        "name": "Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_real_current": {
        "name": "Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_real_power": {
        "name": "Real Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_cell_voltage_max": {
        "name": "Cell Voltage Max",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-plus-variant",
    },
    "battery_cell_voltage_min": {
        "name": "Cell Voltage Min",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-minus-variant",
    },
    "battery_cell_voltage_diff": {
        "name": "Cell Voltage Difference",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-sync",
    },
    "battery_mos_temperature": {
        "name": "MOS Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    "battery_env_temperature": {
        "name": "Environment Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    "battery_cell_temp_max": {
        "name": "Max Cell Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-up",
    },
    "battery_cell_temp_min": {
        "name": "Min Cell Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer-chevron-down",
    },
    "battery_ambient_temperature": {
        "name": "Ambient Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:home-thermometer",
    },
    "battery_remaining_capacity": {
        "name": "Remaining Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_full_capacity": {
        "name": "Full Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_design_capacity": {
        "name": "Design Capacity",
        "unit": "Ah",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_rsoc": {
        "name": "Relative SOC",
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_asoc": {
        "name": "Absolute SOC",
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "icon": "mdi:battery",
    },
    "battery_firmware_version": {
        "name": "Firmware Version",
        "icon": "mdi:chip",
        "entity_category": "diagnostic",
    },
    "battery_capacity_percentage": {
        "name": "Capacity Percentage",
        "unit": "%",
        "state_class": "measurement",
        "icon": "mdi:battery-charging-100",
    },
    "battery_max_charge_current": {
        "name": "Max Charge Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-dc",
    },
    "battery_max_cell_temp_num": {
        "name": "Max Temp Cell Number",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    "battery_min_cell_temp_num": {
        "name": "Min Temp Cell Number",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    "battery_max_cell_voltage_num": {
        "name": "Max Voltage Cell Number",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    "battery_min_cell_voltage_num": {
        "name": "Min Voltage Cell Number",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    "firmware_version": {
        "name": "Firmware Version",
        "icon": "mdi:chip",
        "entity_category": "diagnostic",
    },
    "battery_balance_status": {
        "name": "Balance Status",
        "icon": "mdi:scale-balance",
    },
    "battery_protection_status": {
        "name": "Protection Status",
        "icon": "mdi:shield-check",
    },
    "battery_fault_status": {
        "name": "Fault Status",
        "icon": "mdi:alert-circle",
    },
    "battery_warning_status": {
        "name": "Warning Status",
        "icon": "mdi:alert",
    },
    # Battery temperature sensors (pylxpweb 0.3.3+)
    "battery_max_cell_temp": {
        "name": "Max Cell Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer-high",
    },
    "battery_min_cell_temp": {
        "name": "Min Cell Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer-low",
    },
    # Battery cell voltage sensors (pylxpweb 0.3.3+)
    "battery_max_cell_voltage": {
        "name": "Max Cell Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-plus",
    },
    "battery_min_cell_voltage": {
        "name": "Min Cell Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-minus",
    },
    "battery_cell_voltage_delta": {
        "name": "Cell Voltage Delta",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:delta",
        "suggested_display_precision": 3,
    },
    "battery_cell_temp_delta": {
        "name": "Cell Temperature Delta",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:delta",
    },
    # Battery capacity sensors (pylxpweb 0.3.3+)
    "battery_discharge_capacity": {
        "name": "Discharge Capacity",
        "unit": "Ah",
        "icon": "mdi:battery-arrow-down",
        "entity_category": "diagnostic",
    },
    "battery_charge_voltage_ref": {
        "name": "Charge Voltage Reference",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    # Battery metadata sensors (pylxpweb 0.3.3+)
    "battery_serial_number": {
        "name": "Serial Number",
        "icon": "mdi:identifier",
        "entity_category": "diagnostic",
    },
    "battery_type": {
        "name": "Battery Type Code",
        "icon": "mdi:battery",
        "entity_category": "diagnostic",
    },
    "battery_type_text": {
        "name": "Battery Type",
        "icon": "mdi:battery-sync",
        "entity_category": "diagnostic",
    },
    "battery_bms_model": {
        "name": "BMS Model",
        "icon": "mdi:chip",
        "entity_category": "diagnostic",
    },
    "battery_index": {
        "name": "Index",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    # PV String sensors
    "pv1_voltage": {
        "name": "PV1 Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    "pv2_voltage": {
        "name": "PV2 Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    "pv3_voltage": {
        "name": "PV3 Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    "pv1_power": {
        "name": "PV1 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    "pv2_power": {
        "name": "PV2 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    "pv3_power": {
        "name": "PV3 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-panel",
    },
    # GridBOSS MidBox specific sensors
    "grid_voltage_l1": {
        "name": "Grid Voltage L1",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_voltage_l2": {
        "name": "Grid Voltage L2",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_voltage_l3": {
        "name": "Grid Voltage L3",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_current_l1": {
        "name": "Grid Current L1",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_current_l2": {
        "name": "Grid Current L2",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_current_l3": {
        "name": "Grid Current L3",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "load_voltage_l1": {
        "name": "Load Voltage L1",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_voltage_l2": {
        "name": "Load Voltage L2",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_voltage_l3": {
        "name": "Load Voltage L3",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_current_l1": {
        "name": "Load Current L1",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_current_l2": {
        "name": "Load Current L2",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_current_l3": {
        "name": "Load Current L3",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_power_l1": {
        "name": "Load Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_power_l2": {
        "name": "Load Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_power_l3": {
        "name": "Load Power L3",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-lightning-bolt",
    },
    "grid_power_l1": {
        "name": "Grid Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_power_l2": {
        "name": "Grid Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "grid_power_l3": {
        "name": "Grid Power L3",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
    },
    "ups_voltage": {
        "name": "UPS Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_current": {
        "name": "UPS Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_current_l1": {
        "name": "UPS Current L1",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_current_l2": {
        "name": "UPS Current L2",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_power": {
        "name": "UPS Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_power_l1": {
        "name": "UPS Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    "ups_power_l2": {
        "name": "UPS Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:battery-charging",
    },
    # Status sensors (diagnostic)
    "status_code": {
        "name": "Status Code",
        "icon": "mdi:numeric",
        "entity_category": "diagnostic",
    },
    "status_text": {
        "name": "Status",
        "icon": "mdi:information",
        "entity_category": "diagnostic",
    },
    "has_data": {
        "name": "Has Runtime Data",
        "icon": "mdi:database-check",
        "entity_category": "diagnostic",
    },
    # New runtime sensors
    "pv_total_power": {
        "name": "PV Total Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
    },
    "internal_temperature": {
        "name": "Internal Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
        "entity_category": "diagnostic",
    },
    "radiator1_temperature": {
        "name": "Radiator 1 Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:radiator",
        "entity_category": "diagnostic",
    },
    "radiator2_temperature": {
        "name": "Radiator 2 Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:radiator",
        "entity_category": "diagnostic",
    },
    # GridBOSS Smart Load sensors
    "smart_load_power": {
        "name": "Smart Load Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load1_power": {
        "name": "Smart Load 1 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_power": {
        "name": "Smart Load 2 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_power": {
        "name": "Smart Load 3 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_power": {
        "name": "Smart Load 4 Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    # GridBOSS Smart Port Status sensors
    "smart_port1_status": {
        "name": "Smart Port 1 Status",
        "icon": "mdi:electric-switch",
        "entity_category": "diagnostic",
    },
    "smart_port2_status": {
        "name": "Smart Port 2 Status",
        "icon": "mdi:electric-switch",
        "entity_category": "diagnostic",
    },
    "smart_port3_status": {
        "name": "Smart Port 3 Status",
        "icon": "mdi:electric-switch",
        "entity_category": "diagnostic",
    },
    "smart_port4_status": {
        "name": "Smart Port 4 Status",
        "icon": "mdi:electric-switch",
        "entity_category": "diagnostic",
    },
    # GridBOSS AC Couple energy sensors
    "ac_couple1_today": {
        "name": "AC Couple 1 Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple1_total": {
        "name": "AC Couple 1 Total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_today": {
        "name": "AC Couple 2 Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_total": {
        "name": "AC Couple 2 Total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_today": {
        "name": "AC Couple 3 Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_total": {
        "name": "AC Couple 3 Total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_today": {
        "name": "AC Couple 4 Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_total": {
        "name": "AC Couple 4 Total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    # GridBOSS Generator sensors
    "generator_voltage": {
        "name": "Generator Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    "generator_frequency": {
        "name": "Generator Frequency",
        "unit": UnitOfFrequency.HERTZ,
        "device_class": "frequency",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    "generator_power": {
        "name": "Generator Power",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    # GridBOSS Phase Lock Frequency
    "phase_lock_frequency": {
        "name": "Phase Lock Frequency",
        "unit": UnitOfFrequency.HERTZ,
        "device_class": "frequency",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
    },
    # GridBOSS Generator L1/L2 sensors
    "generator_current_l1": {
        "name": "Generator Current L1",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    "generator_current_l2": {
        "name": "Generator Current L2",
        "unit": UnitOfElectricCurrent.AMPERE,
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    "generator_power_l1": {
        "name": "Generator Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    "generator_power_l2": {
        "name": "Generator Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:engine",
    },
    # GridBOSS Smart Load L1/L2 Power sensors
    "smart_load1_power_l1": {
        "name": "Smart Load 1 Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load1_power_l2": {
        "name": "Smart Load 1 Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_power_l1": {
        "name": "Smart Load 2 Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_power_l2": {
        "name": "Smart Load 2 Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_power_l1": {
        "name": "Smart Load 3 Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_power_l2": {
        "name": "Smart Load 3 Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_power_l1": {
        "name": "Smart Load 4 Power L1",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_power_l2": {
        "name": "Smart Load 4 Power L2",
        "unit": UnitOfPower.WATT,
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:electric-switch",
    },
    # GridBOSS UPS Energy sensors
    "ups_l1": {
        "name": "UPS Consumption L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging-wireless",
    },
    "ups_l2": {
        "name": "UPS Consumption L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging-wireless",
    },
    "ups_lifetime_l1": {
        "name": "UPS Consumption L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging-wireless",
    },
    "ups_lifetime_l2": {
        "name": "UPS Consumption L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:battery-charging-wireless",
    },
    # GridBOSS Grid Export Energy sensors
    "grid_export_l1": {
        "name": "Grid Export L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    "grid_export_l2": {
        "name": "Grid Export L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    "grid_export_lifetime_l1": {
        "name": "Grid Export L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    "grid_export_lifetime_l2": {
        "name": "Grid Export L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-export",
    },
    # GridBOSS Grid Import Energy sensors
    "grid_import_l1": {
        "name": "Grid Import L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    "grid_import_l2": {
        "name": "Grid Import L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    "grid_import_lifetime_l1": {
        "name": "Grid Import L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    "grid_import_lifetime_l2": {
        "name": "Grid Import L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:transmission-tower-import",
    },
    # GridBOSS Load Energy sensors
    "load_l1": {
        "name": "Load L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_l2": {
        "name": "Load L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_lifetime_l1": {
        "name": "Load L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    "load_lifetime_l2": {
        "name": "Load L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:home-lightning-bolt",
    },
    # GridBOSS AC Couple Energy sensors L1/L2
    "ac_couple1_l1": {
        "name": "AC Couple 1 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple1_l2": {
        "name": "AC Couple 1 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple1_lifetime_l1": {
        "name": "AC Couple 1 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple1_lifetime_l2": {
        "name": "AC Couple 1 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_l1": {
        "name": "AC Couple 2 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_l2": {
        "name": "AC Couple 2 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_lifetime_l1": {
        "name": "AC Couple 2 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple2_lifetime_l2": {
        "name": "AC Couple 2 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_l1": {
        "name": "AC Couple 3 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_l2": {
        "name": "AC Couple 3 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_lifetime_l1": {
        "name": "AC Couple 3 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple3_lifetime_l2": {
        "name": "AC Couple 3 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_l1": {
        "name": "AC Couple 4 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_l2": {
        "name": "AC Couple 4 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_lifetime_l1": {
        "name": "AC Couple 4 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    "ac_couple4_lifetime_l2": {
        "name": "AC Couple 4 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
    },
    # GridBOSS Smart Load Energy sensors L1/L2
    "smart_load1_l1": {
        "name": "Smart Load 1 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load1_l2": {
        "name": "Smart Load 1 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load1_lifetime_l1": {
        "name": "Smart Load 1 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load1_lifetime_l2": {
        "name": "Smart Load 1 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_l1": {
        "name": "Smart Load 2 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_l2": {
        "name": "Smart Load 2 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_lifetime_l1": {
        "name": "Smart Load 2 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load2_lifetime_l2": {
        "name": "Smart Load 2 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_l1": {
        "name": "Smart Load 3 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_l2": {
        "name": "Smart Load 3 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_lifetime_l1": {
        "name": "Smart Load 3 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load3_lifetime_l2": {
        "name": "Smart Load 3 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_l1": {
        "name": "Smart Load 4 L1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_l2": {
        "name": "Smart Load 4 L2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_lifetime_l1": {
        "name": "Smart Load 4 L1 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    "smart_load4_lifetime_l2": {
        "name": "Smart Load 4 L2 (Lifetime)",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:electric-switch",
    },
    # Individual Inverter Energy API additional sensors
    "inverter_power_rating": {
        "name": "Power Rating",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:lightning-bolt",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "inverter_lost_status": {
        "name": "Connection Lost",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:access-point-network-off",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "inverter_has_runtime_data": {
        "name": "Has Runtime Data",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:database-check",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
}


# Sensor field mappings to reduce duplication
INVERTER_RUNTIME_FIELD_MAPPING = {
    # System information sensors
    "status": "status_code",
    "statusText": "status_text",
    # Power sensors
    "pinv": "ac_power",
    "ppv": "pv_total_power",
    "ppv1": "pv1_power",
    "ppv2": "pv2_power",
    "ppv3": "pv3_power",
    "pCharge": "battery_charge_power",
    "pDisCharge": "battery_discharge_power",
    "batPower": "battery_power",
    "batStatus": "battery_status",
    "consumptionPower": "consumption_power",
    # Note: grid_power calculated from pToUser - pToGrid in coordinator
    # Voltage sensors
    "acVoltage": "ac_voltage",
    "dcVoltage": "dc_voltage",
    "vacr": "ac_voltage",  # AC Voltage (needs division by 10)
    "vBat": "battery_voltage",
    "vpv1": "pv1_voltage",
    "vpv2": "pv2_voltage",
    "vpv3": "pv3_voltage",
    # Current sensors
    "acCurrent": "ac_current",
    "dcCurrent": "dc_current",
    # Other sensors
    "soc": "state_of_charge",
    "frequency": "frequency",
    "tinner": "internal_temperature",
    "tradiator1": "radiator1_temperature",
    "tradiator2": "radiator2_temperature",
    # Energy sensors (today values - need division by 10)
    "todayYielding": "yield",
    "todayDischarging": "discharging",
    "todayCharging": "charging",
    "todayLoad": "load",
    "todayGridFeed": "grid_export",
    "todayGridConsumption": "grid_import",
    # Total energy values (need division by 10)
    "totalYielding": "yield_lifetime",
    "totalDischarging": "discharging_lifetime",
    "totalCharging": "charging_lifetime",
    "totalLoad": "load_lifetime",
    "totalGridFeed": "grid_export_lifetime",
    "totalGridConsumption": "grid_import_lifetime",
}


GRIDBOSS_FIELD_MAPPING = {
    # Frequency sensors (need division by 100)
    "gridFreq": "frequency",
    "genFreq": "generator_frequency",
    "phaseLockFreq": "phase_lock_frequency",
    # GridBOSS MidBox voltage sensors (need division by 10)
    "gridL1RmsVolt": "grid_voltage_l1",
    "gridL2RmsVolt": "grid_voltage_l2",
    "upsL1RmsVolt": "load_voltage_l1",
    "upsL2RmsVolt": "load_voltage_l2",
    "upsRmsVolt": "ups_voltage",
    "gridRmsVolt": "grid_voltage",
    "genRmsVolt": "generator_voltage",
    # GridBOSS MidBox current sensors (need division by 10)
    "gridL1RmsCurr": "grid_current_l1",
    "gridL2RmsCurr": "grid_current_l2",
    "loadL1RmsCurr": "load_current_l1",
    "loadL2RmsCurr": "load_current_l2",
    "upsL1RmsCurr": "ups_current_l1",
    "upsL2RmsCurr": "ups_current_l2",
    "genL1RmsCurr": "generator_current_l1",
    "genL2RmsCurr": "generator_current_l2",
    # Power sensors
    "gridL1ActivePower": "grid_power_l1",
    "gridL2ActivePower": "grid_power_l2",
    "loadL1ActivePower": "load_power_l1",
    "loadL2ActivePower": "load_power_l2",
    "upsL1ActivePower": "ups_power_l1",
    "upsL2ActivePower": "ups_power_l2",
    "genL1ActivePower": "generator_power_l1",
    "genL2ActivePower": "generator_power_l2",
    "smartLoad1L1ActivePower": "smart_load1_power_l1",
    "smartLoad1L2ActivePower": "smart_load1_power_l2",
    "smartLoad2L1ActivePower": "smart_load2_power_l1",
    "smartLoad2L2ActivePower": "smart_load2_power_l2",
    "smartLoad3L1ActivePower": "smart_load3_power_l1",
    "smartLoad3L2ActivePower": "smart_load3_power_l2",
    "smartLoad4L1ActivePower": "smart_load4_power_l1",
    "smartLoad4L2ActivePower": "smart_load4_power_l2",
    # Smart Port status sensors
    "smartPort1Status": "smart_port1_status",
    "smartPort2Status": "smart_port2_status",
    "smartPort3Status": "smart_port3_status",
    "smartPort4Status": "smart_port4_status",
    # Energy sensors - UPS daily and lifetime values (need division by 10)
    "eUpsTodayL1": "ups_l1",
    "eUpsTodayL2": "ups_l2",
    "eUpsTotalL1": "ups_lifetime_l1",
    "eUpsTotalL2": "ups_lifetime_l2",
    # Energy sensors - Grid interaction daily and lifetime values (need division by 10)
    "eToGridTodayL1": "grid_export_l1",
    "eToGridTodayL2": "grid_export_l2",
    "eToUserTodayL1": "grid_import_l1",
    "eToUserTodayL2": "grid_import_l2",
    "eToGridTotalL1": "grid_export_lifetime_l1",
    "eToGridTotalL2": "grid_export_lifetime_l2",
    "eToUserTotalL1": "grid_import_lifetime_l1",
    "eToUserTotalL2": "grid_import_lifetime_l2",
    # Energy sensors - Load daily and lifetime values (need division by 10)
    "eLoadTodayL1": "load_l1",
    "eLoadTodayL2": "load_l2",
    "eLoadTotalL1": "load_lifetime_l1",
    "eLoadTotalL2": "load_lifetime_l2",
    # Energy sensors - AC Couple daily values (need division by 10)
    "eACcouple1TodayL1": "ac_couple1_l1",
    "eACcouple1TodayL2": "ac_couple1_l2",
    "eACcouple2TodayL1": "ac_couple2_l1",
    "eACcouple2TodayL2": "ac_couple2_l2",
    "eACcouple3TodayL1": "ac_couple3_l1",
    "eACcouple3TodayL2": "ac_couple3_l2",
    "eACcouple4TodayL1": "ac_couple4_l1",
    "eACcouple4TodayL2": "ac_couple4_l2",
    # Energy sensors - AC Couple lifetime values (need division by 10)
    "eACcouple1TotalL1": "ac_couple1_lifetime_l1",
    "eACcouple1TotalL2": "ac_couple1_lifetime_l2",
    "eACcouple2TotalL1": "ac_couple2_lifetime_l1",
    "eACcouple2TotalL2": "ac_couple2_lifetime_l2",
    "eACcouple3TotalL1": "ac_couple3_lifetime_l1",
    "eACcouple3TotalL2": "ac_couple3_lifetime_l2",
    "eACcouple4TotalL1": "ac_couple4_lifetime_l1",
    "eACcouple4TotalL2": "ac_couple4_lifetime_l2",
    # Energy sensors - Smart Load daily values (need division by 10)
    "eSmartLoad1TodayL1": "smart_load1_l1",
    "eSmartLoad1TodayL2": "smart_load1_l2",
    "eSmartLoad2TodayL1": "smart_load2_l1",
    "eSmartLoad2TodayL2": "smart_load2_l2",
    "eSmartLoad3TodayL1": "smart_load3_l1",
    "eSmartLoad3TodayL2": "smart_load3_l2",
    "eSmartLoad4TodayL1": "smart_load4_l1",
    "eSmartLoad4TodayL2": "smart_load4_l2",
    # Energy sensors - Smart Load lifetime values (need division by 10)
    "eSmartLoad1TotalL1": "smart_load1_lifetime_l1",
    "eSmartLoad1TotalL2": "smart_load1_lifetime_l2",
    "eSmartLoad2TotalL1": "smart_load2_lifetime_l1",
    "eSmartLoad2TotalL2": "smart_load2_lifetime_l2",
    "eSmartLoad3TotalL1": "smart_load3_lifetime_l1",
    "eSmartLoad3TotalL2": "smart_load3_lifetime_l2",
    "eSmartLoad4TotalL1": "smart_load4_lifetime_l1",
    "eSmartLoad4TotalL2": "smart_load4_lifetime_l2",
    # Other energy sensors (need division by 10)
    "eEnergyToUser": "energy_to_user",
    "eUpsEnergy": "ups_energy",
}

PARALLEL_GROUP_FIELD_MAPPING = {
    # Today energy values (need division by 10)
    "todayYielding": "yield",
    "todayDischarging": "discharging",
    "todayCharging": "charging",
    "todayExport": "grid_export",
    "todayImport": "grid_import",
    "todayUsage": "consumption",
    # Total energy values (need division by 10)
    "totalYielding": "yield_lifetime",
    "totalDischarging": "discharging_lifetime",
    "totalCharging": "charging_lifetime",
    "totalExport": "grid_export_lifetime",
    "totalImport": "grid_import_lifetime",
    "totalUsage": "consumption_lifetime",
}

# Add individual inverter energy fields to the existing parallel group mapping
# This extends the parallel group mapping to include additional fields from individual inverter API
PARALLEL_GROUP_FIELD_MAPPING.update(
    {
        # Additional fields from individual inverter energy API
        "soc": "state_of_charge",
        "powerRatingText": "inverter_power_rating",
        "lost": "inverter_lost_status",
        "hasRuntimeData": "inverter_has_runtime_data",
    }
)

# Use the same field mapping for both parallel group and individual inverter energy data
# This ensures consistent entity creation across different API endpoints
INVERTER_ENERGY_FIELD_MAPPING = PARALLEL_GROUP_FIELD_MAPPING.copy()

# Add basic energy information fields that might come from other endpoints
INVERTER_ENERGY_FIELD_MAPPING.update(
    {
        "totalEnergy": "total_energy",
        "dailyEnergy": "daily_energy",
        "monthlyEnergy": "monthly_energy",
        "yearlyEnergy": "yearly_energy",
    }
)

# Shared sensor lists to reduce duplication
DIVIDE_BY_10_SENSORS = {
    "yield",
    "discharging",
    "charging",
    "load",
    "grid_export",
    "grid_import",
    "consumption",
    "yield_lifetime",
    "discharging_lifetime",
    "charging_lifetime",
    "load_lifetime",
    "grid_export_lifetime",
    "grid_import_lifetime",
    "consumption_lifetime",
    # GridBOSS energy sensors
    "ups_l1",
    "ups_l2",
    "ups_lifetime_l1",
    "ups_lifetime_l2",
    "grid_export_l1",
    "grid_export_l2",
    "grid_import_l1",
    "grid_import_l2",
    "grid_export_lifetime_l1",
    "grid_export_lifetime_l2",
    "grid_import_lifetime_l1",
    "grid_import_lifetime_l2",
    "load_l1",
    "load_l2",
    "load_lifetime_l1",
    "load_lifetime_l2",
    "ac_couple1_l1",
    "ac_couple1_l2",
    "ac_couple1_lifetime_l1",
    "ac_couple1_lifetime_l2",
    "ac_couple2_l1",
    "ac_couple2_l2",
    "ac_couple2_lifetime_l1",
    "ac_couple2_lifetime_l2",
    "ac_couple3_l1",
    "ac_couple3_l2",
    "ac_couple3_lifetime_l1",
    "ac_couple3_lifetime_l2",
    "ac_couple4_l1",
    "ac_couple4_l2",
    "ac_couple4_lifetime_l1",
    "ac_couple4_lifetime_l2",
    "smart_load1_l1",
    "smart_load1_l2",
    "smart_load1_lifetime_l1",
    "smart_load1_lifetime_l2",
    "smart_load2_l1",
    "smart_load2_l2",
    "smart_load2_lifetime_l1",
    "smart_load2_lifetime_l2",
    "smart_load3_l1",
    "smart_load3_l2",
    "smart_load3_lifetime_l1",
    "smart_load3_lifetime_l2",
    "smart_load4_l1",
    "smart_load4_l2",
    "smart_load4_lifetime_l1",
    "smart_load4_lifetime_l2",
}

# GridBOSS-specific sensor lists
DIVIDE_BY_100_SENSORS = {
    "frequency",
    "generator_frequency",
    "phase_lock_frequency",
}

VOLTAGE_SENSORS = {
    "grid_voltage_l1",
    "grid_voltage_l2",
    "load_voltage_l1",
    "load_voltage_l2",
    "ups_voltage",
    "grid_voltage",
    "generator_voltage",
}

CURRENT_SENSORS = {
    "grid_current_l1",
    "grid_current_l2",
    "load_current_l1",
    "load_current_l2",
    "ups_current_l1",
    "ups_current_l2",
    "generator_current_l1",
    "generator_current_l2",
}

GRIDBOSS_ENERGY_SENSORS = {
    # UPS energy sensors
    "ups_l1",
    "ups_l2",
    "ups_lifetime_l1",
    "ups_lifetime_l2",
    # Grid export/import energy sensors
    "grid_export_l1",
    "grid_export_l2",
    "grid_import_l1",
    "grid_import_l2",
    "grid_export_lifetime_l1",
    "grid_export_lifetime_l2",
    "grid_import_lifetime_l1",
    "grid_import_lifetime_l2",
    # Load energy sensors
    "load_l1",
    "load_l2",
    "load_lifetime_l1",
    "load_lifetime_l2",
    # AC Couple energy sensors
    "ac_couple1_l1",
    "ac_couple1_l2",
    "ac_couple1_lifetime_l1",
    "ac_couple1_lifetime_l2",
    "ac_couple2_l1",
    "ac_couple2_l2",
    "ac_couple2_lifetime_l1",
    "ac_couple2_lifetime_l2",
    "ac_couple3_l1",
    "ac_couple3_l2",
    "ac_couple3_lifetime_l1",
    "ac_couple3_lifetime_l2",
    "ac_couple4_l1",
    "ac_couple4_l2",
    "ac_couple4_lifetime_l1",
    "ac_couple4_lifetime_l2",
    # Smart Load energy sensors
    "smart_load1_l1",
    "smart_load1_l2",
    "smart_load1_lifetime_l1",
    "smart_load1_lifetime_l2",
    "smart_load2_l1",
    "smart_load2_l2",
    "smart_load2_lifetime_l1",
    "smart_load2_lifetime_l2",
    "smart_load3_l1",
    "smart_load3_l2",
    "smart_load3_lifetime_l1",
    "smart_load3_lifetime_l2",
    "smart_load4_l1",
    "smart_load4_l2",
    "smart_load4_lifetime_l1",
    "smart_load4_lifetime_l2",
    # Other energy sensors
    "energy_to_user",
    "ups_energy",
}

# Working Mode Configurations
WORKING_MODES = {
    "ac_charge_mode": {
        "name": "AC Charge Mode",
        "param": "FUNC_AC_CHARGE",
        "description": "Allow battery charging from AC grid power",
        "icon": "mdi:battery-charging-medium",
        "entity_category": EntityCategory.CONFIG,
    },
    "pv_charge_priority_mode": {
        "name": "PV Charge Priority Mode",
        "param": "FUNC_FORCED_CHG_EN",
        "description": "Prioritize PV charging during specified hours",
        "icon": "mdi:solar-power",
        "entity_category": EntityCategory.CONFIG,
    },
    "forced_discharge_mode": {
        "name": "Forced Discharge Mode",
        "param": "FUNC_FORCED_DISCHG_EN",
        "description": "Force battery discharge for grid export",
        "icon": "mdi:battery-arrow-down",
        "entity_category": EntityCategory.CONFIG,
    },
    "peak_shaving_mode": {
        "name": "Grid Peak Shaving Mode",
        "param": "FUNC_GRID_PEAK_SHAVING",
        "description": "Grid peak shaving to reduce demand charges",
        "icon": "mdi:chart-bell-curve-cumulative",
        "entity_category": EntityCategory.CONFIG,
    },
    "battery_backup_mode": {
        "name": "Battery Backup Mode",
        "param": "FUNC_BATTERY_BACKUP_CTRL",
        "description": "Emergency Power Supply (EPS) backup functionality",
        "icon": "mdi:home-battery",
        "entity_category": EntityCategory.CONFIG,
    },
}

# SOC Limit Parameters
# These parameters control battery state of charge thresholds for charging and discharging
# Note: No entity_category set - these appear in Controls section like System Charge SOC Limit
SOC_LIMIT_PARAMS = {
    "ac_charge_soc_limit": {
        "name": "AC Charge SOC Limit",
        "param": "HOLD_AC_CHARGE_SOC_LIMIT",
        "description": "Stop AC charging when battery reaches this SOC percentage",
        "icon": "mdi:battery-charging-medium",
        "min": 0,
        "max": 100,
        "step": 1,
        "unit": "%",
    },
    "on_grid_soc_cutoff": {
        "name": "On-Grid SOC Cut-Off",
        "param": "HOLD_DISCHG_CUT_OFF_SOC_EOD",
        "description": "Minimum battery SOC when connected to grid (on-grid discharge cutoff)",
        "icon": "mdi:battery-alert",
        "min": 0,
        "max": 100,
        "step": 1,
        "unit": "%",
    },
    "off_grid_soc_cutoff": {
        "name": "Off-Grid SOC Cut-Off",
        "param": "HOLD_SOC_LOW_LIMIT_EPS_DISCHG",
        "description": "Minimum battery SOC when off-grid (EPS mode discharge cutoff)",
        "icon": "mdi:battery-outline",
        "min": 0,
        "max": 100,
        "step": 1,
        "unit": "%",
    },
}

# Function parameter to parameter register mapping
# Maps function control parameters to their corresponding status parameters
FUNCTION_PARAM_MAPPING = {
    "FUNC_BATTERY_BACKUP_CTRL": "FUNC_BATTERY_BACKUP_CTRL",  # Working mode for backup control
    "FUNC_GRID_PEAK_SHAVING": "FUNC_GRID_PEAK_SHAVING",  # Working mode for peak shaving
    "FUNC_AC_CHARGE": "FUNC_AC_CHARGE",  # Working mode for AC charging
    "FUNC_FORCED_CHG_EN": "FUNC_FORCED_CHG_EN",  # Working mode for forced charge
    "FUNC_FORCED_DISCHG_EN": "FUNC_FORCED_DISCHG_EN",  # Working mode for forced discharge
    "FUNC_SET_TO_STANDBY": "FUNC_SET_TO_STANDBY",  # Operating mode control
}

# Station/Plant Configuration Constants

# Add station device type
DEVICE_TYPE_STATION = "station"

# Timezone options for plant/station configuration
# Note: Station configuration data (Continent, Region, Country, Timezone) are read-only
# informational fields from the EG4 API. They are displayed as-is without mapping since
# they don't need to be used in automations. Only DST (Daylight Saving Time) is controllable.

# Station sensor types - read-only display sensors
STATION_SENSOR_TYPES = {
    "station_name": {
        "name": "Station Name",
        "icon": "mdi:home-lightning-bolt-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_country": {
        "name": "Country",
        "icon": "mdi:map-marker",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_timezone": {
        "name": "Timezone",
        "icon": "mdi:clock-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_create_date": {
        "name": "Created",
        "icon": "mdi:calendar",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_address": {
        "name": "Address",
        "icon": "mdi:map-marker-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
}

# Battery data parsing constants
# These constants define the separators and formats used in battery identification
BATTERY_KEY_SEPARATOR = "_Battery_ID_"
BATTERY_KEY_PREFIX = "Battery_ID_"
BATTERY_KEY_SHORT_PREFIX = "BAT"

# Diagnostic sensor keys - centralized for consistency across platforms
# These sensor keys are assigned EntityCategory.DIAGNOSTIC
DIAGNOSTIC_DEVICE_SENSOR_KEYS = frozenset(
    {
        "temperature",
        "cycle_count",
        "state_of_health",
        "status_code",
        "status_text",
        "internal_temperature",
        "radiator1_temperature",
        "radiator2_temperature",
        "firmware_version",
        "has_data",
    }
)

# Diagnostic battery sensor keys - additional sensors specific to batteries
DIAGNOSTIC_BATTERY_SENSOR_KEYS = frozenset(
    {
        "temperature",
        "cycle_count",
        "state_of_health",
        "battery_firmware_version",
        "battery_max_cell_temp_num",
        "battery_min_cell_temp_num",
        "battery_max_cell_voltage_num",
        "battery_min_cell_voltage_num",
        "battery_serial_number",
        "battery_type",
        "battery_type_text",
        "battery_bms_model",
        "battery_index",
        "battery_discharge_capacity",
    }
)

# Supported inverter models for number/switch entities
SUPPORTED_INVERTER_MODELS = frozenset(
    {
        "flexboss",
        "18kpv",
        "18k",
        "12kpv",
        "12k",
        "xp",
    }
)

# Battery data scaling factors
# Raw API values are scaled by these factors and need division for proper units
BATTERY_VOLTAGE_SCALE_MILLIVOLTS = 1000  # Battery cell voltage in mV (÷1000 for V)
BATTERY_VOLTAGE_SCALE_CENTIVOLTS = 100  # Total battery voltage in cV (÷100 for V)
BATTERY_CURRENT_SCALE_DECIAMPS = 10  # Battery current in dA (÷10 for A)
BATTERY_TEMPERATURE_SCALE_DECIDEGREES = 10  # Battery temperature in dC (÷10 for °C)

# Task cleanup constants
BACKGROUND_TASK_CLEANUP_TIMEOUT = 5  # Seconds to wait for background task cancellation
