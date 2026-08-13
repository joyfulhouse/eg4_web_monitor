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

# The UNRESOLVED family. pylxpweb's ``InverterFeatures.model_family`` defaults
# to ``InverterFamily.UNKNOWN`` and ``detect_features()`` returns that default
# WITHOUT raising when the parameter fetch leaves ``parameters`` unavailable —
# so this truthy string is the value the pipeline actually emits for a device
# whose family could not be determined, not an absent key.  Never treat it as
# "family known": ``is_offgrid_family`` and ``is_family_control_supported``
# both classify it as unresolved.
INVERTER_FAMILY_UNKNOWN = "UNKNOWN"

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

# Fallback mapping from device model name to inverter family (issue #219).
#
# Used ONLY when register/cloud-based family detection cannot identify the
# family: some firmware reports a HOLD_DEVICE_TYPE_CODE that pylxpweb cannot
# map (e.g. 6000XP on ccaa-140A0A in CLOUD mode), yielding family=UNKNOWN
# whose conservative defaults disable split-phase — silently starving all
# L1/L2 sensors. The model name then identifies the family profile instead.
#
# Keys are normalized model names — lookups must use str.strip().upper().
MODEL_NAME_FAMILY_FALLBACK: dict[str, str] = {
    # EG4 Off-Grid series — US split-phase (L1/L2)
    "6000XP": INVERTER_FAMILY_EG4_OFFGRID,
    "12000XP": INVERTER_FAMILY_EG4_OFFGRID,
    "12000XP-US": INVERTER_FAMILY_EG4_OFFGRID,
    # EG4 Hybrid series — US split-phase grid-tied
    "FLEXBOSS21": INVERTER_FAMILY_EG4_HYBRID,
    "FLEXBOSS18": INVERTER_FAMILY_EG4_HYBRID,
    "18KPV": INVERTER_FAMILY_EG4_HYBRID,
    "12KPV": INVERTER_FAMILY_EG4_HYBRID,
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
# NOTE: output_power is deliberately NOT in this set (eg4-9e4).  It carries
# reg 170 (Pload) locally and its cloud mirror pLoad170 — available on every
# family (canonical models=ALL) — so gating it by supports_split_phase starved
# the sensor on devices with a non-split-phase grid_type override while the
# duplicate pinv-based cloud value made it look redundant.
SPLIT_PHASE_ONLY_SENSORS: frozenset[str] = frozenset(
    {
        "eps_power_l1",
        "eps_power_l2",
        "eps_voltage_l1",
        "eps_voltage_l2",
        "grid_voltage_l1",
        "grid_voltage_l2",
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
        "eps_apparent_power_r",
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
        "eps_apparent_power",
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

# Sensors confirmed meaningful on EG4_OFFGRID hardware only (12000XP/6000XP —
# live Modbus sweep + cloud cross-reference, issues #197/#222/#335):
#   - load_power: input reg 170 ("Pload" in the 6kXP Modbus PDF, W).  The cloud
#     zeroes its reg-170 mirror for EG4_OFFGRID, so the value comes from the
#     LOCAL register only (LOCAL mapping + HYBRID transport overlay).
#   - battery_discharge_power: input reg 11 / cloud pDisCharge (W)
#   - smart_load_power / grid_load_power / eps_load_power: the cloud
#     smartLoadPower / gridLoadPower / epsLoadPower fields (W) — the GEN-port
#     smart load + grid-side + EPS-loads split of the backup output (issue
#     #222: consumption = epsLoadPower + smartLoadPower + gridLoadPower).
#     CLOUD/HYBRID supplemental only: no validated local register on this
#     family (the 18kPV firmware RE names input reg 232 "smart_load_power"
#     but it is unvalidated on EG4_OFFGRID hardware, and regs 129/130 are the
#     COMBINED backup legs, not the epsLoadPower subset), so these keys are
#     intentionally absent from ALL_INVERTER_SENSOR_KEYS and the LOCAL
#     mapping.
#   - The former eps_load_power_l1/_l2 sensors (#197) were RETIRED (#335):
#     they aliased the combined regs 129/130 / pEpsL1N/L2N values and so
#     duplicated eps_power_l1/l2 — no per-leg source for the EPS-loads
#     subset exists on any path.
# NOTE: "load_power" is also a GridBOSS/parallel-group sensor key — this gate
# only applies to inverter entities (GridBOSS devices carry no inverter
# features, so _should_create_sensor passes them through).
OFFGRID_ONLY_SENSORS: frozenset[str] = frozenset(
    {
        "eps_load_power",
        "load_power",
        "battery_discharge_power",
        "smart_load_power",
        "grid_load_power",
    }
)

# Sensors that are MEANINGLESS on EG4_OFFGRID and must not be created there —
# the inverse gate of OFFGRID_ONLY_SENSORS (issue #544).
#
# Proven from the 12000XP's own firmware (ceaa-0709); full derivation with
# addresses in docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md:
#   - generator_power (input reg 123): the FC04 handler returns a 16-bit word of
#     the ARM comms processor's own RAM that a timer task increments once per
#     second with no bound check, so it wraps at 65536.  It is seconds-since-boot,
#     not watts.  A whole-image audit found exactly two writers — that increment
#     and the power-on memset — and no DSP measurement path.
#   - generator_energy / generator_energy_lifetime (input regs 124/125/126):
#     ARM-local status words, not accumulators.  124 is a byte-assembled status
#     construction; 125/126 are the two halves of one 32-bit status bitfield
#     (a reported "135,494.5 kWh" is the bit pattern 0x0014ACC1).
#
# NOT suppressed, because they are genuine DSP measurements on this family and
# correctly read 0 with no generator attached: generator_voltage (reg 121),
# generator_frequency (reg 122), generator_voltage_l1/l2 (regs 195/196).
#
# EVIDENCE SCOPE: the firmware proof is the 12000XP / SNA-US 15K (ceaa-0709).
# The 6000XP shares the family and shows the SAME structure — 121/122 read the
# DSP receive-frame block, 153/170 the DSP power block, while 123 alone reads a
# separate base whose neighbouring fields are demonstrably time counters (one
# saturating at 3600) — but its increment site was not located, so that half is
# structural inference, not proof.  If a 6000XP owner ever reports a plausible
# Generator Power reading, treat it as falsifying and narrow this set to the
# 12000XP.  See §7 of the firmware doc.
#
# EG4_HYBRID is deliberately untouched: there reg 123 is measurement-derived
# (two DSP-fed operands) and on a GridBOSS parallel system the inverters' values
# sum to the GridBOSS AC-Couple-1 total within 0.13%.  This gate must stay
# family-scoped.
#
# NOTE: GridBOSS/MID devices carry their own real generator_power from dedicated
# CT registers.  They are unaffected because _should_create_sensor applies this
# gate only when device_type == "inverter".
OFFGRID_EXCLUDED_SENSORS: frozenset[str] = frozenset(
    {
        "generator_power",
        "generator_energy",
        "generator_energy_lifetime",
    }
)

# Registers 131/132 have different meanings on EG4_HYBRID; they remain genuine
# per-leg apparent-power measurements on EG4_OFFGRID.  See
# docs/reference/firmware/HYBRID_EPS_REGISTERS.md.
HYBRID_EXCLUDED_SENSORS: frozenset[str] = frozenset(
    {
        "eps_apparent_power_l1",
        "eps_apparent_power_l2",
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
        # Forced discharge stops at this SOC (reg 83) — an SOC-regime stop
        # limit (the cloud UI gates the same field with disChgSocEnable).
        # The companion power command (reg 82, kW) is a power level, not a
        # stop limit, so it is deliberately NOT regime-gated (GH #207).
        "forced_discharge_soc_limit",
    }
)
DISCHARGE_VOLTAGE_CONTROLS: frozenset[str] = frozenset(
    {
        "on_grid_cutoff_voltage",
        "off_grid_cutoff_voltage",
        # Forced discharge stops at this battery voltage (reg 202) — the
        # voltage-regime counterpart of forced_discharge_soc_limit (the
        # cloud UI gates the field with disChgVoltEnable). Bead eg4-aa3t.
        "stop_discharge_voltage",
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
