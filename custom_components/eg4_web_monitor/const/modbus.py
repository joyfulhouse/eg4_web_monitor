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
# Direct Value Registers - Charge/Discharge Power
# =============================================================================

MODBUS_REG_CHARGE_POWER_PERCENT = 64  # PV/Battery charge power (0-100%)
MODBUS_REG_DISCHARGE_POWER_PERCENT = 65  # Discharge power (0-100%)
MODBUS_REG_AC_CHARGE_POWER = 66  # AC charge power (0-100%, represents 0-15kW)
MODBUS_REG_AC_CHARGE_SOC_LIMIT = 67  # AC charge SOC limit (0-100%)

# =============================================================================
# Direct Value Registers - Battery/Discharge Current and SOC
# =============================================================================

MODBUS_REG_CHARGE_CURRENT = 101  # Max charge current (A)
MODBUS_REG_DISCHARGE_CURRENT = 102  # Max discharge current (A)
MODBUS_REG_ONGRID_DISCHG_SOC = 105  # On-grid discharge cutoff SOC (10-90%)
MODBUS_REG_OFFGRID_DISCHG_SOC = 106  # Off-grid SOC low limit (0-100%)
