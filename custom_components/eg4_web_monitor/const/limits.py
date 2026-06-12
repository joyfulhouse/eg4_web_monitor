"""Number entity limit constants for the EG4 Web Monitor integration.

This module contains min/max/step values for number entities that control
inverter parameters like charge power, current limits, and SOC thresholds.
"""

from __future__ import annotations

# =============================================================================
# PV Start Voltage (V)
# =============================================================================
# Firmware rejects <140V (error code 3) despite API claiming 90V min.

PV_START_VOLTAGE_MIN = 140
PV_START_VOLTAGE_MAX = 500
PV_START_VOLTAGE_STEP = 1

# =============================================================================
# AC Charge Power (kW)
# =============================================================================

AC_CHARGE_POWER_MIN = 0.0
AC_CHARGE_POWER_MAX = 15.0
AC_CHARGE_POWER_STEP = 0.1

# =============================================================================
# PV Charge Power (kW)
# =============================================================================

PV_CHARGE_POWER_MIN = 0
PV_CHARGE_POWER_MAX = 15
PV_CHARGE_POWER_STEP = 1

# =============================================================================
# Grid Peak Shaving Power (kW)
# =============================================================================

GRID_PEAK_SHAVING_POWER_MIN = 0.0
GRID_PEAK_SHAVING_POWER_MAX = 25.5
GRID_PEAK_SHAVING_POWER_STEP = 0.1

# =============================================================================
# Battery Charge/Discharge Current (A)
# =============================================================================

BATTERY_CURRENT_MIN = 0
BATTERY_CURRENT_MAX = 250
BATTERY_CURRENT_STEP = 1

# =============================================================================
# SOC Limits (%)
# =============================================================================

SOC_LIMIT_MIN = 0
SOC_LIMIT_MAX = 100
SOC_LIMIT_STEP = 1

# =============================================================================
# Forced Discharge (regs 82/83, GH #207 / PR #249)
# Reg 82 is kW (raw 100W units, 0-255 = 0-25.5 kW — hardware-verified in
# PR #249: panel 2.5 kW reads raw 25; cloud UI takes float kW [0, 25.5]).
# Reg 83 is percent.
# =============================================================================

FORCED_DISCHARGE_POWER_MIN = 0.0
FORCED_DISCHARGE_POWER_MAX = 25.5
FORCED_DISCHARGE_POWER_STEP = 0.1
FORCED_DISCHARGE_SOC_LIMIT_MIN = 0
FORCED_DISCHARGE_SOC_LIMIT_MAX = 100
FORCED_DISCHARGE_SOC_LIMIT_STEP = 1

# =============================================================================
# Grid Sell Back Power (reg 103, GH #135)
# Whole percent on both paths: the cloud named read returns 0-100 and the raw
# register is documented 0-100 (live-pinned via single-register named reads on
# 18kPV + FlexBOSS21, 2026-06-12 — cloud key HOLD_FEED_IN_GRID_POWER_PERCENT).
# =============================================================================

GRID_SELL_BACK_POWER_MIN = 0
GRID_SELL_BACK_POWER_MAX = 100
GRID_SELL_BACK_POWER_STEP = 1

# =============================================================================
# System Charge SOC Limit (%)
# =============================================================================

SYSTEM_CHARGE_SOC_LIMIT_MIN = 10
SYSTEM_CHARGE_SOC_LIMIT_MAX = 101
SYSTEM_CHARGE_SOC_LIMIT_STEP = 1

# =============================================================================
# Battery Voltage Limits (V) — open-loop (Voltage) control mode
# =============================================================================
# Registers store decivolts (value ×10). Ranges sized for 48 V LiFePO4 / lead-acid
# banks with margin. AC charge start/stop voltages are whole-volt only (firmware
# rejects fractional volts).

# System charge voltage ceiling (reg 228)
SYSTEM_CHARGE_VOLT_LIMIT_MIN = 40.0
SYSTEM_CHARGE_VOLT_LIMIT_MAX = 64.0
SYSTEM_CHARGE_VOLT_LIMIT_STEP = 0.1

# On-grid / Off-grid end-of-discharge cutoff voltage (regs 169 / 100)
CUTOFF_VOLTAGE_MIN = 40.0
CUTOFF_VOLTAGE_MAX = 58.0
CUTOFF_VOLTAGE_STEP = 0.1

# Forced-discharge stop voltage (reg 202) — cloud maintain UI range [40, 56] V;
# fractional volts accepted (live round-trip 40 -> 41.5 -> 40 V on an 18kPV
# and a FlexBOSS21).
STOP_DISCHARGE_VOLTAGE_MIN = 40.0
STOP_DISCHARGE_VOLTAGE_MAX = 56.0
STOP_DISCHARGE_VOLTAGE_STEP = 0.1

# AC charge start/stop voltage (regs 158 / 159) — whole volts only
AC_CHARGE_VOLTAGE_MIN = 38
AC_CHARGE_VOLTAGE_MAX = 60
AC_CHARGE_VOLTAGE_STEP = 1
