"""Number entity limit constants for the EG4 Web Monitor integration.

This module contains min/max/step values for number entities that control
inverter parameters like charge power, current limits, and SOC thresholds.
"""

from __future__ import annotations

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
