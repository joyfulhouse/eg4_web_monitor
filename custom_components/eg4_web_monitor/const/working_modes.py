"""Working mode configuration constants for the EG4 Web Monitor integration.

This module contains configurations for inverter working modes and SOC limit
parameters used by switch and number entities.

Optional per-mode gating keys (read by switch.py setup):
- ``grid_tied_only``: skip the switch on EG4_OFFGRID inverters (12000XP /
  6000XP have no grid sell-back).
- ``requires_cloud_params``: the state parameter only exists in the CLOUD
  parameter cache (no local register/bit mapping), so the switch is skipped
  whenever the parameter cache holds local-raw register data (LOCAL mode, or
  HYBRID with a local transport attached) — otherwise is_on could never
  reflect the true state.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory

# =============================================================================
# Working Mode Configurations
# =============================================================================
# These define switch entities for various inverter operational modes

WORKING_MODES: dict[str, dict[str, Any]] = {
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
    # Grid Sell Back enable (reg 21 bit 15, GH #135) — "Feed-in Grid" in the
    # protocol. Works on all transports: the bit is live-verified and named
    # in pylxpweb's local register map.
    "grid_sell_back_mode": {
        "name": "Grid Sell Back",
        "param": "FUNC_FEED_IN_GRID_EN",
        "description": "Allow exporting (selling) surplus power to the grid",
        "icon": "mdi:transmission-tower-export",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
    },
    # Export PV Only (FUNC_PV_SELL_TO_GRID_EN, GH #135). Cloud-only: the
    # parameter lives in the register 179 family but its bit position is
    # unpinned, so there is no local read/write path.
    "export_pv_only_mode": {
        "name": "Export PV Only",
        "param": "FUNC_PV_SELL_TO_GRID_EN",
        "description": "Only export PV surplus to the grid (never battery)",
        "icon": "mdi:solar-power-variant",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
        "requires_cloud_params": True,
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
    "FUNC_FEED_IN_GRID_EN": "FUNC_FEED_IN_GRID_EN",
    "FUNC_PV_SELL_TO_GRID_EN": "FUNC_PV_SELL_TO_GRID_EN",
}
