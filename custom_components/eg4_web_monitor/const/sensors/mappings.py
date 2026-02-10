"""Field mappings and sensor lists for the EG4 Web Monitor integration.

This module contains API field to sensor key mappings and categorized
sensor lists used for data processing and scaling.
"""

from __future__ import annotations


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
    "todayLoad": "consumption",
    "todayGridFeed": "grid_export",
    "todayGridConsumption": "grid_import",
    # Total energy values (need division by 10)
    "totalYielding": "yield_lifetime",
    "totalDischarging": "discharging_lifetime",
    "totalCharging": "charging_lifetime",
    "totalLoad": "consumption_lifetime",
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
    # Connection status (same as inverter)
    "lost": "inverter_lost_status",
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
    "grid_export",
    "grid_import",
    "consumption",
    "yield_lifetime",
    "discharging_lifetime",
    "charging_lifetime",
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
    # Aggregate energy sensors (L2 energy registers always read 0, so only aggregates are useful)
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
}
