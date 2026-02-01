"""Device type constants for the EG4 Web Monitor integration.

This module contains all device type and inverter family constants including:
- Device type identifiers
- Inverter family constants
- Feature-based sensor classification sets
- Inverter family to default model mapping
"""

from __future__ import annotations

# =============================================================================
# Device Types
# =============================================================================

DEVICE_TYPE_INVERTER = "inverter"
DEVICE_TYPE_GRIDBOSS = "gridboss"
DEVICE_TYPE_BATTERY = "battery"
DEVICE_TYPE_STATION = "station"

# =============================================================================
# Inverter Family Constants
# =============================================================================
# From pylxpweb InverterFamily enum - used for feature-based sensor filtering

INVERTER_FAMILY_SNA = "SNA"  # Split-phase, North America (12000XP, 6000XP)
INVERTER_FAMILY_PV_SERIES = "PV_SERIES"  # High-voltage DC (18KPV, etc.)
INVERTER_FAMILY_LXP_EU = "LXP_EU"  # European market
INVERTER_FAMILY_LXP_LV = "LXP_LV"  # Low-voltage DC
INVERTER_FAMILY_UNKNOWN = "UNKNOWN"

# Mapping from inverter family to default model for entity compatibility checks
# Used when inverter_model is not provided in config entry (Modbus/Dongle modes)
INVERTER_FAMILY_DEFAULT_MODELS: dict[str, str] = {
    "PV_SERIES": "18kPV",  # Matches "18kpv" in SUPPORTED_INVERTER_MODELS
    "SNA": "12000XP",  # Matches "xp" in SUPPORTED_INVERTER_MODELS
    "LXP_EU": "LXP-EU",  # LuxPower EU models - matches "lxp" in SUPPORTED_INVERTER_MODELS
}

# =============================================================================
# Feature-based Sensor Classification
# =============================================================================
# These sets define which sensors are only available on specific device families

# Sensors only available on split-phase (SNA) inverters (12000XP, 6000XP)
# These inverters use L1/L2 phase naming convention
SPLIT_PHASE_ONLY_SENSORS: frozenset[str] = frozenset(
    {
        "eps_power_l1",
        "eps_power_l2",
        "eps_voltage_l1",
        "eps_voltage_l2",
        "grid_voltage_l1",
        "grid_voltage_l2",
        "output_power",
    }
)

# Sensors only available on three-phase capable inverters (PV Series, LXP-EU)
# These inverters use R/S/T phase naming convention
THREE_PHASE_ONLY_SENSORS: frozenset[str] = frozenset(
    {
        "grid_voltage_r",
        "grid_voltage_s",
        "grid_voltage_t",
        "grid_current_l1",
        "grid_current_l2",
        "grid_current_l3",
        "eps_voltage_r",
        "eps_voltage_s",
        "eps_voltage_t",
    }
)

# Sensors related to discharge recovery hysteresis (SNA series only)
# These parameters prevent oscillation when SOC is near the cutoff threshold
DISCHARGE_RECOVERY_SENSORS: frozenset[str] = frozenset(
    {
        "discharge_recovery_lag_soc",
        "discharge_recovery_lag_volt",
    }
)

# Sensors related to Volt-Watt curve (PV Series, LXP-EU only)
VOLT_WATT_SENSORS: frozenset[str] = frozenset(
    {
        "volt_watt_v1",
        "volt_watt_v2",
        "volt_watt_v3",
        "volt_watt_v4",
        "volt_watt_p1",
        "volt_watt_p2",
        "volt_watt_p3",
        "volt_watt_p4",
    }
)
