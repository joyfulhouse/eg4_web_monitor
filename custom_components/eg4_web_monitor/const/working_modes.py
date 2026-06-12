"""Working mode configuration constants for the EG4 Web Monitor integration.

This module contains configurations for inverter working modes and SOC limit
parameters used by switch and number entities.

Optional per-mode gating keys (read by switch.py setup):
- ``grid_tied_only``: skip the switch on EG4_OFFGRID inverters (12000XP /
  6000XP have no grid sell-back).

Cloud-only state parameters need no per-mode flag: switch.py setup probes
the installed pylxpweb register map (``_local_params_can_carry``) and skips
any mode whose state key cannot be decoded from local registers whenever
the parameter cache holds local-raw register data (LOCAL mode, or HYBRID
with a local transport attached) — otherwise is_on could never reflect the
true state. The probe doubles as the version guard for newly pinned bits.
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
    # Export PV Only (FUNC_PV_SELL_TO_GRID_EN, GH #135) — register 179
    # bit 3, pinned 2026-06-12 via authorized live cloud toggles
    # raw-verified on BOTH 12K-hybrid models (FlexBOSS21 52842P0581 and
    # 18kPV 4512670118: reg-179 raw 0x104c <-> 0x1044, single bit 3,
    # restores verified by re-read). Local read/write resolves through
    # pylxpweb's register map from 0.9.36b6 on; against older installs the
    # switch.py setup probe keeps it cloud-only.
    "export_pv_only_mode": {
        "name": "Export PV Only",
        "param": "FUNC_PV_SELL_TO_GRID_EN",
        "description": "Only export PV surplus to the grid (never battery)",
        "icon": "mdi:solar-power-variant",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
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
