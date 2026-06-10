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

from .config_keys import CONTROL_MODE_SOC, CONTROL_MODE_VOLTAGE

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
        # EPS per-leg apparent power and energy
        "eps_apparent_power_l1",
        "eps_apparent_power_l2",
        "eps_energy_today_l1",
        "eps_energy_today_l2",
        "eps_energy_total_l1",
        "eps_energy_total_l2",
        # Per-leg grid power breakdowns
        "inverter_power_l1",
        "inverter_power_l2",
        "rectifier_power_l1",
        "rectifier_power_l2",
        "grid_export_power_l1",
        "grid_export_power_l2",
        "grid_import_power_l1",
        "grid_import_power_l2",
        "generator_voltage_l1",
        "generator_voltage_l2",
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

# Common voltage sensors for single-phase and split-phase configurations.
# These alias register 12 (grid_voltage_r) and register 20 (eps_voltage_r)
# with phase-neutral names. Not created for three-phase (R/S/T sensors used instead).
NON_THREE_PHASE_SENSORS: frozenset[str] = frozenset(
    {
        "grid_voltage",
        "eps_voltage",
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

# Sensors backed by registers confirmed working on EG4_OFFGRID hardware only
# (12000XP/6000XP — live Modbus sweep + cloud cross-reference, issue #197):
#   - eps_load_power_l1/_l2: input regs 129/130 (per-phase EPS load, W)
#   - eps_load_power: L1+L2 sum (matches cloud epsLoadPower within timing skew)
#   - load_power: input reg 170 ("Pload" in the 6kXP Modbus PDF, W).  The cloud
#     zeroes its reg-170 mirror for EG4_OFFGRID, so the value comes from the
#     LOCAL register only (LOCAL mapping + HYBRID transport overlay).
#   - battery_discharge_power: input reg 11 / cloud pDisCharge (W)
# NOTE: "load_power" is also a GridBOSS/parallel-group sensor key — this gate
# only applies to inverter entities (GridBOSS devices carry no inverter
# features, so _should_create_sensor passes them through).
OFFGRID_ONLY_SENSORS: frozenset[str] = frozenset(
    {
        "eps_load_power_l1",
        "eps_load_power_l2",
        "eps_load_power",
        "load_power",
        "battery_discharge_power",
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

# =============================================================================
# Battery Control Regime Classification (SOC vs Voltage limit controls)
# =============================================================================
# These map a control entity's unique-id suffix to the side (charge/discharge)
# and regime (SOC/Voltage) it belongs to. They drive both the default-enabled
# state of the entity and the runtime "is this control currently effective?"
# indicator. Keys must match the unique-id suffixes used in number.py.

# Charge-side controls gated by the charge control mode (reg 179 bit 9)
CHARGE_SOC_CONTROLS: frozenset[str] = frozenset(
    {
        "system_charge_soc_limit",
        "ac_charge_soc_limit",
    }
)
CHARGE_VOLTAGE_CONTROLS: frozenset[str] = frozenset(
    {
        "system_charge_volt_limit",
        "ac_charge_start_voltage",
        "ac_charge_end_voltage",
    }
)

# Discharge-side controls gated by the discharge control mode (reg 179 bit 10)
DISCHARGE_SOC_CONTROLS: frozenset[str] = frozenset(
    {
        "on_grid_soc_cutoff",
        "off_grid_soc_cutoff",
    }
)
DISCHARGE_VOLTAGE_CONTROLS: frozenset[str] = frozenset(
    {
        "on_grid_cutoff_voltage",
        "off_grid_cutoff_voltage",
    }
)

# All regime-gated control entity keys (used by tests for drift prevention)
REGIME_GATED_CONTROLS: frozenset[str] = (
    CHARGE_SOC_CONTROLS
    | CHARGE_VOLTAGE_CONTROLS
    | DISCHARGE_SOC_CONTROLS
    | DISCHARGE_VOLTAGE_CONTROLS
)


def control_side_and_mode(key: str) -> tuple[str, str] | None:
    """Return ``(side, mode)`` for a regime-gated control, else ``None``.

    ``side`` is ``"charge"`` or ``"discharge"``; ``mode`` is
    :data:`CONTROL_MODE_SOC` or :data:`CONTROL_MODE_VOLTAGE`. Controls that are
    not regime-gated (power, current, etc.) return ``None`` (always shown).
    """
    if key in CHARGE_SOC_CONTROLS:
        return ("charge", CONTROL_MODE_SOC)
    if key in CHARGE_VOLTAGE_CONTROLS:
        return ("charge", CONTROL_MODE_VOLTAGE)
    if key in DISCHARGE_SOC_CONTROLS:
        return ("discharge", CONTROL_MODE_SOC)
    if key in DISCHARGE_VOLTAGE_CONTROLS:
        return ("discharge", CONTROL_MODE_VOLTAGE)
    return None


def is_control_active(key: str, charge_mode: str, discharge_mode: str) -> bool:
    """Whether a regime-gated control is active under the given modes.

    A charge-side control is active when its regime matches ``charge_mode``; a
    discharge-side control when its regime matches ``discharge_mode``. Non-gated
    controls are always active. Used both for ``entity_registry_enabled_default``
    (configured modes) and the live "is_effective" attribute (live modes).
    """
    classification = control_side_and_mode(key)
    if classification is None:
        return True
    side, mode = classification
    active_mode = charge_mode if side == "charge" else discharge_mode
    return mode == active_mode
