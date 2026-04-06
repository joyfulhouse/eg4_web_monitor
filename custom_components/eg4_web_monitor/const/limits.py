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
# System Charge SOC Limit (%)
# =============================================================================

SYSTEM_CHARGE_SOC_LIMIT_MIN = 10
SYSTEM_CHARGE_SOC_LIMIT_MAX = 101
SYSTEM_CHARGE_SOC_LIMIT_STEP = 1

# =============================================================================
# AC Charge Start SOC (%)
# =============================================================================
# Battery SOC to start AC charging (register 160)

AC_CHARGE_START_SOC_MIN = 0
AC_CHARGE_START_SOC_MAX = 90
AC_CHARGE_START_SOC_STEP = 1

# =============================================================================
# AC Charge End SOC (%)
# =============================================================================
# Battery SOC to stop AC charging (register 161)

AC_CHARGE_END_SOC_MIN = 20
AC_CHARGE_END_SOC_MAX = 100
AC_CHARGE_END_SOC_STEP = 1

# =============================================================================
# AC Charge Start Voltage (V)
# =============================================================================
# Battery voltage to start AC charging (register 158, DIV_10)

AC_CHARGE_START_VOLTAGE_MIN = 38.4
AC_CHARGE_START_VOLTAGE_MAX = 52.0
AC_CHARGE_START_VOLTAGE_STEP = 0.1

# =============================================================================
# AC Charge End Voltage (V)
# =============================================================================
# Battery voltage to stop AC charging (register 159, DIV_10)

AC_CHARGE_END_VOLTAGE_MIN = 48.0
AC_CHARGE_END_VOLTAGE_MAX = 59.0
AC_CHARGE_END_VOLTAGE_STEP = 0.1
