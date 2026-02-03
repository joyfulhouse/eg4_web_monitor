"""Modbus register constants for the EG4 Web Monitor integration.

This module contains Modbus holding register addresses and bit field positions
used for local Modbus/Dongle register write operations.

Source: EG4-18KPV Modbus Protocol specification
"""

from __future__ import annotations

# =============================================================================
# Function Enable Register (21)
# =============================================================================
# Critical control register with bit fields for various inverter functions

MODBUS_REG_FUNC_EN = 21
MODBUS_BIT_EPS_EN = 0  # Off-grid mode enable (EPS/Battery Backup)
MODBUS_BIT_AC_CHARGE_EN = 7  # AC charge enable
MODBUS_BIT_SET_TO_STANDBY = 9  # Operating mode: 0=Standby, 1=Power On
MODBUS_BIT_FORCED_DISCHG_EN = 10  # Forced discharge enable
MODBUS_BIT_FORCED_CHG_EN = 11  # Force charge enable

# =============================================================================
# System Function Register (110)
# =============================================================================
# Additional control bit fields for system-level functions

MODBUS_REG_SYS_FUNC = 110
MODBUS_BIT_PV_GRID_OFF_EN = 0  # PV grid-off mode enable
MODBUS_BIT_RUN_WITHOUT_GRID = 1  # Run without grid
MODBUS_BIT_MICRO_GRID_EN = 2  # Micro-grid enable
MODBUS_BIT_BAT_SHARED = 3  # Battery shared mode
MODBUS_BIT_CHARGE_LAST = 4  # Charge last mode
MODBUS_BIT_BUZZER_EN = 5  # Buzzer enable
MODBUS_BIT_GREEN_EN = 8  # Green mode / Off-grid priority (FUNC_GREEN_EN)
MODBUS_BIT_BATTERY_ECO_EN = 9  # Battery ECO mode

# =============================================================================
# Function Enable Register 2 (179) - 18kPV/12kPV Only
# =============================================================================
# Generator port mode control - PV series inverters only (not FlexBOSS)
# These modes are mutually exclusive - enabling one disables the others

MODBUS_REG_FUNC_EN_2 = 179  # uFunctionEn2
MODBUS_BIT_AC_COUPLING_FUNCTION = 11  # AC coupling on generator port (0x0800)
MODBUS_BIT_SMART_LOAD_ENABLE = 13  # Smart load on generator port (0x2000)

# =============================================================================
# Direct Value Registers - Charge/Discharge Power
# =============================================================================

MODBUS_REG_CHARGE_POWER_PERCENT = 64  # PV/Battery charge power (0-100%)
MODBUS_REG_DISCHARGE_POWER_PERCENT = 65  # Discharge power (0-100%)
MODBUS_REG_AC_CHARGE_POWER = 66  # AC charge power in 100W units (120 = 12kW)
MODBUS_REG_AC_CHARGE_SOC_LIMIT = 67  # AC charge SOC limit (0-100%)

# =============================================================================
# Direct Value Registers - Battery/Discharge Current and SOC
# =============================================================================

MODBUS_REG_CHARGE_CURRENT = 101  # Max charge current (A)
MODBUS_REG_DISCHARGE_CURRENT = 102  # Max discharge current (A)
MODBUS_REG_ONGRID_DISCHG_SOC = 105  # On-grid discharge cutoff SOC (10-90%)
MODBUS_REG_OFFGRID_DISCHG_SOC = (
    125  # Off-grid SOC low limit (0-100%) - verified 2026-01-27
)

# =============================================================================
# HTTP API Parameter Names
# =============================================================================
# These names match the HTTP API parameters returned by pylxpweb's
# read_named_parameters() and accepted by write_named_parameters().

# Bit field parameter names (register 21)
PARAM_FUNC_EPS_EN = "FUNC_EPS_EN"
PARAM_FUNC_AC_CHARGE = "FUNC_AC_CHARGE"
PARAM_FUNC_SET_TO_STANDBY = "FUNC_SET_TO_STANDBY"
PARAM_FUNC_FORCED_DISCHG_EN = "FUNC_FORCED_DISCHG_EN"
PARAM_FUNC_FORCED_CHG_EN = "FUNC_FORCED_CHG_EN"

# Bit field parameter names (register 110)
PARAM_FUNC_GREEN_EN = "FUNC_GREEN_EN"
PARAM_FUNC_BATTERY_ECO_EN = "FUNC_BATTERY_ECO_EN"
PARAM_FUNC_MICRO_GRID_EN = "FUNC_MICRO_GRID_EN"

# Bit field parameter names (register 179) - 18kPV/12kPV generator port modes
PARAM_FUNC_AC_COUPLING_FUNCTION = "FUNC_AC_COUPLING_FUNCTION"
PARAM_FUNC_SMART_LOAD_ENABLE = "FUNC_SMART_LOAD_ENABLE"

# Direct value parameter names
PARAM_HOLD_CHG_POWER_PERCENT = "HOLD_CHG_POWER_PERCENT_CMD"
PARAM_HOLD_DISCHG_POWER_PERCENT = "HOLD_DISCHG_POWER_PERCENT_CMD"
PARAM_HOLD_AC_CHARGE_POWER = "HOLD_AC_CHARGE_POWER_CMD"
PARAM_HOLD_AC_CHARGE_SOC_LIMIT = "HOLD_AC_CHARGE_SOC_LIMIT"
PARAM_HOLD_CHARGE_CURRENT = "HOLD_LEAD_ACID_CHARGE_RATE"
PARAM_HOLD_DISCHARGE_CURRENT = "HOLD_LEAD_ACID_DISCHARGE_RATE"
PARAM_HOLD_ONGRID_DISCHG_SOC = "HOLD_DISCHG_CUT_OFF_SOC_EOD"
PARAM_HOLD_OFFGRID_DISCHG_SOC = "HOLD_SOC_LOW_LIMIT_EPS_DISCHG"
PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT = "HOLD_SYSTEM_CHARGE_SOC_LIMIT"
