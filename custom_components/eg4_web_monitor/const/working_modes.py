"""Working mode configuration constants for the EG4 Web Monitor integration.

This module contains configurations for inverter working modes and SOC limit
parameters used by switch and number entities.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory

# =============================================================================
# Working Mode Configurations
# =============================================================================
# These define switch entities for various inverter operational modes

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

# =============================================================================
# SOC Limit Parameters
# =============================================================================
# These parameters control battery state of charge thresholds
# Note: No entity_category set - these appear in Controls section

SOC_LIMIT_PARAMS = {
    "system_charge_soc_limit": {
        "name": "System Charge SOC Limit",
        "param": "HOLD_SYSTEM_CHARGE_SOC_LIMIT",
        "description": "Maximum battery SOC during normal charging (10-100%, or 101% for top balancing)",
        "icon": "mdi:battery-charging",
        "min": 10,
        "max": 101,
        "step": 1,
        "unit": "%",
    },
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

# =============================================================================
# Function Parameter Mapping
# =============================================================================
# Maps function control parameters to their corresponding status parameters

FUNCTION_PARAM_MAPPING = {
    "FUNC_BATTERY_BACKUP_CTRL": "FUNC_BATTERY_BACKUP_CTRL",
    "FUNC_GRID_PEAK_SHAVING": "FUNC_GRID_PEAK_SHAVING",
    "FUNC_AC_CHARGE": "FUNC_AC_CHARGE",
    "FUNC_FORCED_CHG_EN": "FUNC_FORCED_CHG_EN",
    "FUNC_FORCED_DISCHG_EN": "FUNC_FORCED_DISCHG_EN",
    "FUNC_SET_TO_STANDBY": "FUNC_SET_TO_STANDBY",
}
