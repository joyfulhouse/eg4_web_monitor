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
# Off-grid ceiling for reg 66: the CEAA/CCAA firmware writer rejects raw >100
# (10 kW) with exception 03 — firmware-proven (#570); pylxpweb PR #273 capped
# the canonical definition to match. The 15 kW ceiling above is kept ONLY for
# positively resolved non-off-grid families (shipped status quo, backed by
# DATA_MAPPING's raw/UI examples 0-150 = 0-15 kW; not firmware-proven there).
# Unresolved families fail closed to this firmware-proven bound.
AC_CHARGE_POWER_OFFGRID_MAX = 10.0

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

# On-grid discharge cutoff (reg 105) WRITE bounds. These mirror pylxpweb's
# canonical H105 definition and set_battery_soc_limits so an off-grid
# cloud-only route never surfaces a raw ValueError at a boundary (#570
# review round 2). The 90 ceiling that round copied from the library was the
# portal's arrow-button hint, not a firmware bound: a portal-typed 95 is
# stored (reporter diagnostics, LXP-LB-US 10K, #603) and only >100 is
# rejected by the inverter, so the ceiling is 100. The 10 floor is the same
# kind of hint — unproven either way — and is kept as shipped. The READ
# plausibility window is the tolerant SOC_LIMIT_* 0-100 regardless, so a
# register value the portal stored never blanks to unknown (#603). The
# off-grid cutoff (reg 125) is genuinely 0-100 and keeps SOC_LIMIT_*.
ONGRID_SOC_CUTOFF_MIN = 10
ONGRID_SOC_CUTOFF_MAX = 100

# AC Charge SOC Limit (reg 67). Separate from the shared SOC_LIMIT_* (used by
# the on-grid/off-grid discharge cutoffs) because the inverter accepts 101% =
# "never stop AC charging" (the stop threshold is unreachable since SOC <= 100),
# used for battery cell balancing. Matches SYSTEM_CHARGE_SOC_LIMIT_MAX = 101.
# GH #158.
AC_CHARGE_SOC_LIMIT_MIN = 0
AC_CHARGE_SOC_LIMIT_MAX = 101
AC_CHARGE_SOC_LIMIT_STEP = 1

# AC-charge SOC window (regs 160/161, GH #331): whole-percent start/end
# thresholds for the AC Charge working mode. No 101 top-balance sentinel
# here — the portal fields are plain percent. The Start (reg 160) WRITE cap
# is 90, matching pylxpweb's register definition and its hybrid setter
# (set_ac_charge_soc_limits caps start_soc at 90); the 0-100 pair remains
# the READ-validation window so an out-of-spec register value still
# displays rather than blanking to unknown.
AC_CHARGE_BATTERY_SOC_MIN = 0
AC_CHARGE_BATTERY_SOC_MAX = 100
AC_CHARGE_START_BATTERY_SOC_MAX = 90
# Off-grid floor for reg 161: the CEAA/CCAA firmware writer enforces
# 20..100 (and >= H160 — firmware-enforced, not validated entity-side for
# the same stale-sibling reason as the voltage window). The 0 floor is kept
# ONLY for positively resolved non-off-grid families (where reg 161 is
# inert/read-only per the keeper anyway).
AC_CHARGE_END_SOC_OFFGRID_MIN = 20
# Off-grid floor for reg 160: the CEAA/CCAA firmware writer rejects 0 with
# exception 03 — firmware-proven (#570; the sweep deliberately never wrote 0);
# pylxpweb PR #273 set the canonical minimum to 1 to match. The 0 floor above
# is kept ONLY for positively resolved non-off-grid families (shipped status
# quo; 0's semantics there are unverified but nothing proves it invalid).
# Unresolved families fail closed to this firmware-proven bound.
AC_CHARGE_START_SOC_OFFGRID_MIN = 1
AC_CHARGE_BATTERY_SOC_STEP = 1

# AC Couple Start/End SOC window (GH #352): whole-percent thresholds for the
# AC-coupled source on the inverter's smart port (any family with a cloud
# client; devices lacking the params read None and the entities go
# unavailable) — the source is enabled when SOC drops below START and
# disabled above END. Writable range is
# 0-100 %; END additionally READS 255 as the factory disabled / "never stop"
# sentinel (paired with START=100 on factory-state dumps), which the entity
# renders as unknown + a ``disabled_sentinel`` attribute rather than a fake
# slider value. Cloud-only holdParams — no pinned local register.
AC_COUPLE_SOC_MIN = 0
AC_COUPLE_SOC_MAX = 100
AC_COUPLE_SOC_STEP = 1
AC_COUPLE_END_SOC_DISABLED_SENTINEL = 255

# =============================================================================
# Smart Load panel (GH #499, cloud-only holdParams — no pinned local register)
# Maintenance -> Remote Set -> Smart Load Port -> "Smart Load" tab. The port is
# energized once the start condition is met and dropped at the end condition.
# The SOC pair and the voltage pair APPEAR to be alternatives selected by a
# configured mode — the reporter's 12000XP greys the volt pair out while SOC
# mode is active — but which pair an inverter acts on is UNTESTED here, and no
# mode parameter has been found in the cloud data to gate on. Both pairs are
# therefore exposed and writable rather than one being hidden on inference.
# =============================================================================
SMART_LOAD_SOC_MIN = 0
SMART_LOAD_SOC_MAX = 100
SMART_LOAD_SOC_STEP = 1
# Battery-bank thresholds. The bounds are deliberately WIDER than a 48 V bank's
# working range (our own units read 54/48 V, and the sibling AC-couple
# holdParam reads as high as 80 V): the wire carries volts at 0.1 resolution
# with no documented ceiling, and a too-narrow range would render a legal
# portal value as unknown. No sentinel is known for this pair.
SMART_LOAD_VOLT_MIN = 0.0
SMART_LOAD_VOLT_MAX = 100.0
SMART_LOAD_VOLT_STEP = 0.1
# PV power above which the smart load port starts. Portal unit is kW at 0.1
# resolution (our units read 0.5). The ceiling is a defensive sanity bound, not
# a firmware-confirmed maximum.
SMART_LOAD_PV_POWER_MIN = 0.0
SMART_LOAD_PV_POWER_MAX = 100.0
SMART_LOAD_PV_POWER_STEP = 0.1

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
# Grid Sell Back Power (reg 103, GH #135 / #274)
# kW with 100 W raw units — the reg-66/74/82 encoding, NOT the percent the
# protocol PDF claims: the 2026-04-13 live local probe read raw 160 on an
# 18kPV + FlexBOSS21 while the same 18kPV's cloud named read returned "16"
# (kW), and both the EG4 and Luxpower web UIs label the field "Grid Sell
# Back Power(kW)" (GH #135 + #274 screenshots; the #274 LXP shows 12.1 kW =
# raw 121, impossible as a 0-100 percent). Cloud key stays
# HOLD_FEED_IN_GRID_POWER_PERCENT — the "PERCENT" is the vendor's mislabel.
# =============================================================================

GRID_SELL_BACK_POWER_MIN = 0
GRID_SELL_BACK_POWER_MAX = 25.5
GRID_SELL_BACK_POWER_STEP = 0.1

# =============================================================================
# Power-to-User Start Discharge / Charge thresholds (regs 116/117, GH #272)
# Raw register IS whole watts — the protocol register table pins scale "1W"
# for both, NOT the 100 W encoding of regs 66/74/82/103 (fleet scanner
# reads: reg 116 raw 100 == cloud "100" == 100 W in the Luxpower UI).
# Reg 116 (PtoUserStartdischg) defaults to 50 W and the Luxpower web UI
# shows a "[50, ]" range hint; the 10000 W ceiling comes from pylxpweb's
# holding-register table. Reg 117 (PtoUserStartchg) is SIGNED — protocol
# default -50 W means "start charging once exporting more than 50 W" —
# hence the symmetric range.
# =============================================================================

START_DISCHARGE_POWER_MIN = 50
START_DISCHARGE_POWER_MAX = 10000
START_DISCHARGE_POWER_STEP = 1

START_CHARGE_POWER_MIN = -10000
START_CHARGE_POWER_MAX = 10000
START_CHARGE_POWER_STEP = 1

# =============================================================================
# System Charge SOC Limit (%) — reg 227
# =============================================================================
# 0-101: pylxpweb's canonical definition and set_system_charge_soc_limit both
# accept 0, and the ledger grades 0-101 hardware-toggle-proven on an 18kPV.
# The former 10 floor had no evidence and blanked a portal-set 0-9 to unknown
# (same defect class as #603).

SYSTEM_CHARGE_SOC_LIMIT_MIN = 0
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
# Off-grid firmware bounds for the AC-charge voltage window (CEAA/CCAA
# FC06/FC16 writer range checks, firmware-proven #570): H158 raw 384..570
# (38.4-57.0 V); H159 raw 480..590 (48.0-59.0 V). The shared 38-60 V range
# above is kept ONLY for positively resolved non-off-grid families. These
# entities are whole-volt (require_whole, 1 V step), so the ADVERTISED
# bounds are the whole-volt values inside the firmware windows — H158's
# floor is 39, not 38.4: advertising 38.4 made HA accept a boundary the
# whole-volt validation then rejected (#570 review round 7). Every
# advertised boundary below is writable as-is.
# The cross-register constraint (H158 <= H159, firmware-enforced) is
# deliberately NOT validated entity-side: the sibling's cached value can
# be stale, and a false rejection is worse than the writer's own error.
AC_CHARGE_START_VOLTAGE_OFFGRID_MIN = 39
AC_CHARGE_START_VOLTAGE_OFFGRID_MAX = 57
AC_CHARGE_END_VOLTAGE_OFFGRID_MIN = 48
AC_CHARGE_END_VOLTAGE_OFFGRID_MAX = 59
AC_CHARGE_VOLTAGE_STEP = 1

# =============================================================================
# Quick Charge Duration (minutes)
# =============================================================================
# Per-serial start preference, stored on the coordinator and applied when
# Quick Charge is turned on: as the cloud "minute" parameter, or as the reg
# 234 half of the LOCAL/HYBRID paired-frame start. 1440 = 24 hours.

QUICK_CHARGE_DURATION_MIN = 1
QUICK_CHARGE_DURATION_MAX = 1440
QUICK_CHARGE_DURATION_STEP = 1
QUICK_CHARGE_DURATION_DEFAULT = 60

# State attribute persisting the start preference independently of the
# entity's multiplexed displayed value (live countdown while charging).
ATTR_QC_START_PREFERENCE = "start_preference"
