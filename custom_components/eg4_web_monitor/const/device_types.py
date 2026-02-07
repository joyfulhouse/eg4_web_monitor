"""Device type constants for the EG4 Web Monitor integration.

This module contains all device type and inverter family constants including:
- Device type identifiers
- Inverter family constants
- Feature-based sensor classification sets
- Inverter family to default model mapping

Deprecated Constants (v3.2.0):
    The following constants are deprecated and will be removed in a future version:
    - INVERTER_FAMILY_SNA → use INVERTER_FAMILY_EG4_OFFGRID
    - INVERTER_FAMILY_PV_SERIES → use INVERTER_FAMILY_EG4_HYBRID
    - INVERTER_FAMILY_LXP_EU → use INVERTER_FAMILY_LXP
    - INVERTER_FAMILY_LXP_LV → use INVERTER_FAMILY_LXP
"""

from __future__ import annotations

import warnings
from typing import Any

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
#
# Family naming convention:
# - EG4_* families: EG4 Electronics branded inverters (US market)
# - LXP: Luxpower branded inverters (EU, Brazil, low-voltage - all use same registers)

INVERTER_FAMILY_EG4_OFFGRID = (
    "EG4_OFFGRID"  # Off-grid (12000XP, 6000XP) - no grid sellback
)
INVERTER_FAMILY_EG4_HYBRID = "EG4_HYBRID"  # Grid-tied hybrid (18kPV, 12kPV, FlexBOSS)
INVERTER_FAMILY_LXP = "LXP"  # Luxpower (LXP-EU, LXP-LB-BR, LXP-LV)

# =============================================================================
# Deprecated Legacy Aliases
# =============================================================================
# These emit DeprecationWarning when accessed via module-level __getattr__
_DEPRECATED_FAMILY_CONSTANTS: dict[str, tuple[str, str]] = {
    # name -> (value, replacement_name)
    "INVERTER_FAMILY_SNA": ("EG4_OFFGRID", "INVERTER_FAMILY_EG4_OFFGRID"),
    "INVERTER_FAMILY_PV_SERIES": ("EG4_HYBRID", "INVERTER_FAMILY_EG4_HYBRID"),
    "INVERTER_FAMILY_LXP_EU": ("LXP", "INVERTER_FAMILY_LXP"),
    "INVERTER_FAMILY_LXP_LV": ("LXP", "INVERTER_FAMILY_LXP"),
}


def __getattr__(name: str) -> Any:
    """Module-level attribute access for deprecation warnings.

    Emits DeprecationWarning when deprecated constants are accessed.
    """
    if name in _DEPRECATED_FAMILY_CONSTANTS:
        value, replacement = _DEPRECATED_FAMILY_CONSTANTS[name]
        warnings.warn(
            f"'{name}' is deprecated since v3.2.0. Use '{replacement}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Map legacy family names to new names for config entry migration
LEGACY_FAMILY_MAP: dict[str, str] = {
    "SNA": "EG4_OFFGRID",
    "PV_SERIES": "EG4_HYBRID",
    "LXP_EU": "LXP",
    "LXP_LV": "LXP",
}

# Mapping from inverter family to default model for entity compatibility checks
# Used when inverter_model is not provided in config entry (Modbus/Dongle modes)
INVERTER_FAMILY_DEFAULT_MODELS: dict[str, str] = {
    "EG4_HYBRID": "18kPV",  # Matches "18kpv" in SUPPORTED_INVERTER_MODELS
    "EG4_OFFGRID": "12000XP",  # Matches "xp" in SUPPORTED_INVERTER_MODELS
    "LXP": "LXP",  # Luxpower models - matches "lxp" in SUPPORTED_INVERTER_MODELS
    # Legacy keys for backwards compatibility
    "PV_SERIES": "18kPV",
    "SNA": "12000XP",
    "LXP_EU": "LXP",
}

# =============================================================================
# Feature-based Sensor Classification
# =============================================================================
# These sets define which sensors are only available on specific device families

# Sensors only available on split-phase (EG4_OFFGRID) inverters (12000XP, 6000XP)
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

# Sensors only available on three-phase capable inverters (EG4_HYBRID, LXP)
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

# Sensors related to discharge recovery hysteresis (EG4_OFFGRID series only)
# These parameters prevent oscillation when SOC is near the cutoff threshold
DISCHARGE_RECOVERY_SENSORS: frozenset[str] = frozenset(
    {
        "discharge_recovery_lag_soc",
        "discharge_recovery_lag_volt",
    }
)

# Sensors related to Volt-Watt curve (EG4_HYBRID, LXP only)
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
