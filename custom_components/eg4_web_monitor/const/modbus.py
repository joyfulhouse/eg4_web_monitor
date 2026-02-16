"""Modbus register constants for the EG4 Web Monitor integration.

This module contains Modbus holding register addresses and bit field positions
used for local Modbus/Dongle register write operations.

Source: EG4-18KPV Modbus Protocol specification
"""

from __future__ import annotations

# =============================================================================
# HTTP API Parameter Names
# =============================================================================
# These names match the HTTP API parameters returned by pylxpweb's
# read_named_parameters() and accepted by write_named_parameters().

# Bit field parameter names (register 21)
PARAM_FUNC_EPS_EN = "FUNC_EPS_EN"
PARAM_FUNC_AC_CHARGE = "FUNC_AC_CHARGE"
PARAM_FUNC_FORCED_DISCHG_EN = "FUNC_FORCED_DISCHG_EN"
PARAM_FUNC_FORCED_CHG_EN = "FUNC_FORCED_CHG_EN"

# Bit field parameter names (register 110)
PARAM_FUNC_GREEN_EN = "FUNC_GREEN_EN"
PARAM_FUNC_ECO_MODE = "FUNC_ECO_MODE"

# Extended bit field parameter names (registers 179, 233)
PARAM_FUNC_GRID_PEAK_SHAVING = "FUNC_GRID_PEAK_SHAVING"
PARAM_FUNC_BATTERY_BACKUP_CTRL = "FUNC_BATTERY_BACKUP_CTRL"

# Direct value parameter names
PARAM_HOLD_CHG_POWER_PERCENT = "HOLD_CHG_POWER_PERCENT_CMD"
PARAM_HOLD_AC_CHARGE_POWER = "HOLD_AC_CHARGE_POWER_CMD"
PARAM_HOLD_AC_CHARGE_SOC_LIMIT = "HOLD_AC_CHARGE_SOC_LIMIT"
PARAM_HOLD_CHARGE_CURRENT = "HOLD_LEAD_ACID_CHARGE_RATE"
PARAM_HOLD_DISCHARGE_CURRENT = "HOLD_LEAD_ACID_DISCHARGE_RATE"
PARAM_HOLD_ONGRID_DISCHG_SOC = "HOLD_DISCHG_CUT_OFF_SOC_EOD"
PARAM_HOLD_OFFGRID_DISCHG_SOC = "HOLD_SOC_LOW_LIMIT_EPS_DISCHG"
PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT = "HOLD_SYSTEM_CHARGE_SOC_LIMIT"
PARAM_HOLD_AC_COUPLE_START_SOC = "HOLD_AC_COUPLE_START_SOC"
PARAM_HOLD_AC_COUPLE_END_SOC = "HOLD_AC_COUPLE_END_SOC"
PARAM_HOLD_AC_COUPLE_START_VOLT = "HOLD_AC_COUPLE_START_VOLT"
PARAM_HOLD_AC_COUPLE_END_VOLT = "HOLD_AC_COUPLE_END_VOLT"
