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
# Grid Sell Back enable (reg 21 bit 15, GH #135) — "Feed-in Grid" in the
# protocol, "Grid Sell Back" in the EG4 web UI.
PARAM_FUNC_FEED_IN_GRID_EN = "FUNC_FEED_IN_GRID_EN"

# Bit field parameter names (register 110)
PARAM_FUNC_GREEN_EN = "FUNC_GREEN_EN"
# Charge Last (reg 110 bit 4): when enabled, PV surplus serves loads/export
# first and charges the battery last (issue #177).
PARAM_FUNC_CHARGE_LAST = "FUNC_CHARGE_LAST"

# Extended bit field parameter names (registers 179, 233)
PARAM_FUNC_GRID_PEAK_SHAVING = "FUNC_GRID_PEAK_SHAVING"
# Export PV Only (reg 179 bit 3, GH #135). Bit pinned 2026-06-12 via
# authorized live cloud toggles raw-verified on BOTH 12K-hybrid models —
# FlexBOSS21 52842P0581 and 18kPV 4512670118 each toggled reg-179 raw
# 0x104c <-> 0x1044 (XOR 0x0008 = single bit 3) in lockstep with the named
# param, restores verified by re-read. Local writes resolve through
# pylxpweb's REGISTER_TO_PARAM_KEYS (>= 0.9.36b6).
PARAM_FUNC_PV_SELL_TO_GRID_EN = "FUNC_PV_SELL_TO_GRID_EN"
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
# Forced discharge controls (regs 82/83, GH #207 / PR #249). Reg 82 uses the
# same 100W-unit encoding as reg 74 above (0-255 = 0-25.5 kW; hardware-verified
# in PR #249: panel 2.5 kW reads raw 25). Reg 83 is percent (0-100).
PARAM_HOLD_FORCED_DISCHG_POWER = "HOLD_FORCED_DISCHG_POWER_CMD"
PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT = "HOLD_FORCED_DISCHG_SOC_LIMIT"
# Grid Sell Back power limit (reg 103, GH #135). Whole percent 0-100 on both
# paths — cloud key live-pinned via single-register named reads (18kPV +
# FlexBOSS21, 2026-06-12); the protocol spec's "MaxBackflowPower" name for
# reg 103 is not used by the cloud API.
PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT = "HOLD_FEED_IN_GRID_POWER_PERCENT"
PARAM_HOLD_AC_CHARGE_POWER = "HOLD_AC_CHARGE_POWER_CMD"
PARAM_HOLD_AC_CHARGE_SOC_LIMIT = "HOLD_AC_CHARGE_SOC_LIMIT"
PARAM_HOLD_CHARGE_CURRENT = "HOLD_LEAD_ACID_CHARGE_RATE"
PARAM_HOLD_DISCHARGE_CURRENT = "HOLD_LEAD_ACID_DISCHARGE_RATE"
PARAM_HOLD_ONGRID_DISCHG_SOC = "HOLD_DISCHG_CUT_OFF_SOC_EOD"
PARAM_HOLD_OFFGRID_DISCHG_SOC = "HOLD_SOC_LOW_LIMIT_EPS_DISCHG"
PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT = "HOLD_SYSTEM_CHARGE_SOC_LIMIT"
# Quick Charge duration in minutes (holding reg 234). Writable setpoint that
# also reads as the live remaining-minutes countdown while a charge runs.
PARAM_SNA_QUICK_CHARGE_MINUTE = "SNA_HOLD_QUICK_CHARGE_MINUTE"
# Grid peak shaving power, time period 1 (PS1). Lives at reg 206, NOT reg 231
# (eg4-gfu5: single-register cloud reads on an 18kPV and a FlexBOSS21 name PS1
# at (206,1); (231,1) names nothing — the old pylxpweb 231 mapping was wrong,
# so historical local name-writes landed in unrelated register 231). Cloud
# read/write uses float kW [0, 25.5]; the RAW register encoding is presumed
# deci-kW but unverified, so this control is cloud-write-only — never write it
# through the local transport name map.
PARAM_HOLD_GRID_PEAK_SHAVING_POWER = "_12K_HOLD_GRID_PEAK_SHAVING_POWER"

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
# Forced-discharge stop voltage (reg 202, bead eg4-aa3t) — the voltage-regime
# counterpart of PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT (cloud UI gates the field
# with disChgVoltEnable). Decivolts raw (raw 400 == cloud 40 V, raw-verified
# 2026-06-11); cloud read/write is float volts [40, 56].
PARAM_HOLD_STOP_DISCHARGE_VOLTAGE = "_12K_HOLD_STOP_DISCHG_VOLT"  # reg 202

# Raw register addresses (cloud writes via control.write_parameters key by address,
# avoiding the read/write name aliasing on AC charge voltage).
REG_SYSTEM_CHARGE_VOLT_LIMIT = 228
REG_ONGRID_EOD_VOLTAGE = 169
REG_OFFGRID_EOD_VOLTAGE = 100
REG_AC_CHARGE_START_VOLTAGE = 158
REG_AC_CHARGE_END_VOLTAGE = 159
