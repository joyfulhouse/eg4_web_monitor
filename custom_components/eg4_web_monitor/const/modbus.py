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
# Charge Last (reg 110 bit 4): when enabled, PV surplus serves loads/export
# first and charges the battery last (issue #177).
PARAM_FUNC_CHARGE_LAST = "FUNC_CHARGE_LAST"

# Extended bit field parameter names (registers 179, 233)
PARAM_FUNC_GRID_PEAK_SHAVING = "FUNC_GRID_PEAK_SHAVING"
PARAM_FUNC_BATTERY_BACKUP_CTRL = "FUNC_BATTERY_BACKUP_CTRL"

# PV configuration parameter names (registers 20, 22)
PARAM_HOLD_PV_INPUT_MODE = "HOLD_PV_INPUT_MODE"
PARAM_HOLD_START_PV_VOLT = "HOLD_START_PV_VOLT"

# Direct value parameter names
PARAM_HOLD_CHG_POWER_PERCENT = "HOLD_CHG_POWER_PERCENT_CMD"  # reg 64: charge power %
# reg 74: forced/PV charge (ChgFirst) power command, 100W units (0-150 = 0-15 kW).
# This is the register the "PV Charge Power" control targets — same one the cloud
# path uses. (Local path historically mis-targeted reg 64 % with a lossy kW<->%
# conversion.)
PARAM_HOLD_FORCED_CHG_POWER = "HOLD_FORCED_CHG_POWER_CMD"
# Forced discharge controls (regs 82/83, GH #207 / PR #249). Both PERCENT
# (0-100) per the canonical holding table and the cloud parameter names —
# unlike the reg-74 100W forced-charge encoding above.
PARAM_HOLD_FORCED_DISCHG_POWER = "HOLD_FORCED_DISCHG_POWER_CMD"
PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT = "HOLD_FORCED_DISCHG_SOC_LIMIT"
PARAM_HOLD_AC_CHARGE_POWER = "HOLD_AC_CHARGE_POWER_CMD"
PARAM_HOLD_AC_CHARGE_SOC_LIMIT = "HOLD_AC_CHARGE_SOC_LIMIT"
PARAM_HOLD_CHARGE_CURRENT = "HOLD_LEAD_ACID_CHARGE_RATE"
PARAM_HOLD_DISCHARGE_CURRENT = "HOLD_LEAD_ACID_DISCHARGE_RATE"
PARAM_HOLD_ONGRID_DISCHG_SOC = "HOLD_DISCHG_CUT_OFF_SOC_EOD"
PARAM_HOLD_OFFGRID_DISCHG_SOC = "HOLD_SOC_LOW_LIMIT_EPS_DISCHG"
PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT = "HOLD_SYSTEM_CHARGE_SOC_LIMIT"

# =============================================================================
# Battery control regime (register 179 bits 9/10) and voltage limits
# =============================================================================
# Regime selector bit fields (0 = SOC mode, 1 = Voltage mode).
PARAM_FUNC_BAT_CHARGE_CONTROL = "FUNC_BAT_CHARGE_CONTROL"  # reg 179 bit 9
PARAM_FUNC_BAT_DISCHARGE_CONTROL = "FUNC_BAT_DISCHARGE_CONTROL"  # reg 179 bit 10

# Voltage limit parameter names (read + local write via transport name map).
# Values are decivolts (×10). AC charge start/stop use the cloud-aliased
# "...BATTERY_VOLTAGE" names that read_named_parameters surfaces.
PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT = "HOLD_SYSTEM_CHARGE_VOLT_LIMIT"  # reg 228
PARAM_HOLD_ONGRID_EOD_VOLTAGE = (
    "HOLD_ON_GRID_EOD_VOLTAGE"  # reg 169 (cloud-confirmed name)
)
PARAM_HOLD_OFFGRID_EOD_VOLTAGE = "HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT"  # reg 100
PARAM_HOLD_AC_CHARGE_START_VOLTAGE = "HOLD_AC_CHARGE_START_BATTERY_VOLTAGE"  # reg 158
PARAM_HOLD_AC_CHARGE_END_VOLTAGE = "HOLD_AC_CHARGE_END_BATTERY_VOLTAGE"  # reg 159

# Raw register addresses (cloud writes via control.write_parameters key by address,
# avoiding the read/write name aliasing on AC charge voltage).
REG_SYSTEM_CHARGE_VOLT_LIMIT = 228
REG_ONGRID_EOD_VOLTAGE = 169
REG_OFFGRID_EOD_VOLTAGE = 100
REG_AC_CHARGE_START_VOLTAGE = 158
REG_AC_CHARGE_END_VOLTAGE = 159
