"""Modbus register constants for the EG4 Web Monitor integration.

This module contains Modbus holding register addresses and bit field positions
used for local Modbus/Dongle register write operations.

Source: EG4-18KPV Modbus Protocol specification
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
# Fast Zero Export (reg 110 bit 1, GH #274) — "FunctionEn1.ubFastZeroExport"
# in the LXP protocol PDF; both the EG4 and Luxpower web UIs toggle cloud
# param FUNC_RUN_WITHOUT_GRID for their "Fast Zero Export" button (GH #135
# + #274 screenshots). Speeds up the zero-export control loop; the vendors
# advise selecting it as the opposite of the Grid Sell Back setting.
PARAM_FUNC_RUN_WITHOUT_GRID = "FUNC_RUN_WITHOUT_GRID"
# Share Battery (reg 110 bit 3, GH #288) — "Share Battery" toggle in the
# Luxpower/EG4 portals for multi-inverter systems sharing one battery bank
# (only the primary sits on the battery CAN bus; secondaries read reg96=0).
# Reporter-verified: the portal write is cloud function FUNC_BAT_SHARED.
# Bit 3 is one of the register-110 positions where every source agrees for
# both the base (18kPV) and SNA/OFFGRID layouts in pylxpweb.
PARAM_FUNC_BAT_SHARED = "FUNC_BAT_SHARED"

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
# Power-to-User start-discharge threshold (reg 116, whole watts, GH #272):
# "Start Discharge P_import(W)" in the Luxpower web UI. TWO keys for ONE
# register — pylxpweb's local name map spells it HOLD_PTOUSER_START_DISCHARGE
# (read_named_parameters/write_named_parameters), while the live cloud API
# uses HOLD_P_TO_USER_START_DISCHG (reporter-verified remoteSet call in the
# GH #272 browser console + every docs/inverters scanner dump; pylxpweb's
# guessed api_param_key does not exist on the server). Watts on both paths.
PARAM_HOLD_PTOUSER_START_DISCHARGE = "HOLD_PTOUSER_START_DISCHARGE"
PARAM_HOLD_P_TO_USER_START_DISCHG = "HOLD_P_TO_USER_START_DISCHG"
# Power-to-User start-charge threshold (reg 117, SIGNED whole watts, GH
# #272): unmapped in pylxpweb and unnamed in the cloud API (remoteRead names
# reg 117 <EMPTY> on every scanned model) — local reads surface it under the
# raw "117" string key read_named_parameters emits for unmapped registers,
# and writes must go through the raw register address. LOCAL/HYBRID only.
PARAM_RAW_PTOUSER_START_CHARGE = "117"
PARAM_HOLD_AC_CHARGE_POWER = "HOLD_AC_CHARGE_POWER_CMD"
PARAM_HOLD_AC_CHARGE_SOC_LIMIT = "HOLD_AC_CHARGE_SOC_LIMIT"
# Off-grid AC-charge SOC window (regs 160/161, GH #331): the EG4_OFFGRID
# family's REAL AC-charge SOC controls — portal-verified writable holdParams
# on the off-grid working-mode page (reference dump reads 90/100, matching
# the reporter's portal config). Reg 67 (HOLD_AC_CHARGE_SOC_LIMIT above) is
# family-REJECTED there: live REMOTE_SET_ERROR on a 12000XP v2, reads 0 on
# the reference dump, and the off-grid portal page does not carry it. Whole
# percent (SCALE_NONE) on both paths; both registers are in pylxpweb's
# transport name map (reg 161 from 0.9.36b28), so named reads/writes work
# on every path.
PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC = "HOLD_AC_CHARGE_START_BATTERY_SOC"  # reg 160
PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC = "HOLD_AC_CHARGE_END_BATTERY_SOC"  # reg 161
# AC Couple Start/End SOC window (GH #352): SOC thresholds for the AC-coupled
# source on the smart port — enabled when SOC drops below START, disabled
# above END. Portal-verified writable holdParams, NOT family-specific: the
# off-grid reporter's 12000XP v2 capture, the SNA12K-US probe, factory
# END=255/START=100 pairs on grid-tied 12KPV/FlexBOSS18/21 dumps, and
# ivanfmartinez's live 90/95 thresholds on an on-grid hybrid LXP. CLOUD-ONLY:
# the local Modbus register is deliberately unpinned (probe evidence ambiguous
# — see pylxpweb PR #235). The integration serves them from the dedicated
# coordinator ``ac_couple_soc`` store (NOT the parameter cache, which a HYBRID
# local refresh rebuilds without them); never write them through the local
# transport name map. These constants document the wire names for the
# register-contract harness — entity reads/writes go through pylxpweb's
# get/set_inverter_ac_couple_*_soc methods.
PARAM_AC_COUPLE_START_SOC = "_12K_HOLD_AC_COUPLE_START_SOC"
PARAM_AC_COUPLE_END_SOC = "_12K_HOLD_AC_COUPLE_END_SOC"
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
# PV start voltage (MPPT activation floor). Cloud writes go by name in
# human-readable volts (verified route) — the address is spec metadata only.
REG_START_PV_VOLT = 22
# Start-charge threshold (GH #272): no name anywhere, LOCAL raw writes only.
REG_PTOUSER_START_CHARGE = 117

# =============================================================================
# AC charge time schedule (registers 68-73, issue #277)
# =============================================================================
# Three daily windows × (start, end) = six registers from base 68:
#   reg 68/69 = window 1 start/end, 70/71 = window 2, 72/73 = window 3.
# Each 16-bit register PACKS both fields: hour in the LOW byte, minute in the
# HIGH byte (pylxpweb pack_time()/unpack_time(); EG4-18KPV-12LV Modbus spec).
# Live cloud probe evidence (pylxpweb docs/inverters/FlexBOSS21_52XXXXXX78.json):
# reading ONE register returns BOTH cloud params — e.g. reg 68 →
# HOLD_AC_CHARGE_START_HOUR + HOLD_AC_CHARGE_START_MINUTE (window 1,
# unsuffixed) and reg 72 → HOLD_AC_CHARGE_START_HOUR_2 + ..._MINUTE_2
# (window 3, suffix _2) — proving the packed layout and the cloud naming
# (window N uses suffix "" / "_1" / "_2" for N = 1 / 2 / 3).
AC_CHARGE_SCHEDULE_BASE_REGISTER = 68

# Parameter-cache keys under which pylxpweb's LOCAL read_named_parameters()
# surfaces the RAW PACKED values of registers 68-73. The primary names are
# pre-live-probe artifacts still in pylxpweb's REGISTER_TO_PARAM_KEYS that
# MISDESCRIBE the registers (e.g. reg 69 — window 1 END — surfaces as
# "HOLD_AC_CHARGE_START_MINUTE_1", and reg 72 — window 3 START — as
# "HOLD_AC_CHARGE_ENABLE_1"); the value under each key is nonetheless the
# packed register, which the integration unpacks itself. Each chain lists
# fallbacks for a future pylxpweb that renames the registers to their
# canonical packed names or drops the mapping (unmapped registers surface as
# the plain address string). First present key wins.
LOCAL_AC_CHARGE_TIME_PARAM_KEYS: dict[int, tuple[str, ...]] = {
    68: ("HOLD_AC_CHARGE_START_HOUR_1", "HOLD_AC_CHARGE_TIME_0_START", "68"),
    69: ("HOLD_AC_CHARGE_START_MINUTE_1", "HOLD_AC_CHARGE_TIME_0_END", "69"),
    70: ("HOLD_AC_CHARGE_END_HOUR_1", "HOLD_AC_CHARGE_TIME_1_START", "70"),
    71: ("HOLD_AC_CHARGE_END_MINUTE_1", "HOLD_AC_CHARGE_TIME_1_END", "71"),
    72: ("HOLD_AC_CHARGE_ENABLE_1", "HOLD_AC_CHARGE_TIME_2_START", "72"),
    73: ("HOLD_AC_CHARGE_ENABLE_2", "HOLD_AC_CHARGE_TIME_2_END", "73"),
}


# =============================================================================
# Schedule time-window types (issues #277 + #295)
# =============================================================================
# Four schedule types share one packed-time layout: 6 consecutive holding
# registers = 3 daily windows × (start, end), each 16-bit register packing
# hour (low byte) | minute (high byte). The cloud API addresses the same
# data as separated named params {cloud_prefix}_{START|END}_{HOUR|MINUTE}
# with window suffixes ""/"_1"/"_2" (portal holdParam convention, verified
# by the live register probes in pylxpweb docs/inverters/).
#
# This table is the single source of truth consumed by the time platform
# (time.py); it mirrors pylxpweb's SCHEDULE_CONFIGS (constants/registers.py)
# and a drift-guard test asserts the two stay in agreement.


@dataclass(frozen=True)
class ScheduleTimeSpec:
    """Declarative description of one packed-time schedule type.

    Attributes:
        key: Stable identifier — the translation-key/unique-id prefix and
            the value of the matching pylxpweb ``ScheduleType`` member.
        cloud_prefix: Cloud named-parameter prefix (e.g. ``HOLD_AC_CHARGE``).
        base_register: First packed register; the schedule occupies
            ``base_register .. base_register + 5``.
        gate: Which devices get the entities —
            ``control``: every control-capable family (model substring or
            family backstop, #259);
            ``control_grid_tied``: control-capable but suppressed on
            positively-identified EG4_OFFGRID hardware (forced discharge is
            inert on the SNA platform, PR #220 / issue #197 adjudication;
            forced charge schedule writes are cloud-rejected on the family,
            issue #295 live report);
            ``offgrid``: only positively-identified EG4_OFFGRID hardware
            (the portal shows the AC First section only on the SNA
            working-mode page, issue #295);
            ``hybrid``: only positively-identified EG4_HYBRID hardware (the
            families verified on the FlexBOSS21, fails closed);
            ``hybrid_or_offgrid``: EG4_HYBRID or EG4_OFFGRID (Generator
            charge — regs 256-259 carry gen-schedule params on the SNA12K-US
            probe too).
        local_param_keys: Per-register alias chains under which the LOCAL
            parameter cache (pylxpweb ``read_named_parameters``) surfaces the
            raw packed value; the last entry is always the plain
            register-address fallback for unmapped registers.
        windows: Number of daily schedule windows (2 or 3). The schedule
            occupies ``2 * windows`` consecutive registers.
        bare_first_window: When True (classic families), window 1's cloud
            params are unsuffixed and windows 2/3 use ``_1``/``_2``. When
            False (Generator/Off-Grid/Peak Shaving), ALL windows are suffixed
            ``_1..._N`` with no bare window.
        write_via_time_api: When True, cloud writes use pylxpweb's atomic
            ``write_time_parameter`` (portal ``writeTime`` endpoint) with the
            composite ``{cloud_prefix}_{START|END}_TIME{suffix}`` param instead
            of separate hour/minute writes.
        read_lsp_base: When set (Peak Shaving), cloud reads pull hour/minute
            from the interleaved ``LSP_HOLD_DIS_CHG_POWER_TIME_{n}`` params;
            index ``read_lsp_base + period*4`` gives start-hour, ``+1``
            start-minute, ``+2`` end-hour, ``+3`` end-minute.
    """

    key: str
    cloud_prefix: str
    base_register: int
    gate: Literal[
        "control", "control_grid_tied", "offgrid", "hybrid", "hybrid_or_offgrid"
    ]
    local_param_keys: dict[int, tuple[str, ...]]
    windows: int = 3
    bare_first_window: bool = True
    write_via_time_api: bool = False
    read_lsp_base: int | None = None


def _canonical_time_param_keys(
    cloud_prefix: str, base_register: int, windows: int = 3
) -> dict[int, tuple[str, ...]]:
    """Alias chains for schedule registers named canonically in pylxpweb.

    pylxpweb maps these registers to the canonical packed-time names
    ``{cloud_prefix}_TIME_{period}_{START|END}``; older releases leave them
    unmapped, so ``read_named_parameters`` falls back to the plain
    register-address string key (the #272 reg-117 precedent).
    """
    return {
        base_register + period * 2 + offset: (
            f"{cloud_prefix}_TIME_{period}_{'END' if offset else 'START'}",
            str(base_register + period * 2 + offset),
        )
        for period in range(windows)
        for offset in (0, 1)
    }


SCHEDULE_TIME_TYPES: tuple[ScheduleTimeSpec, ...] = (
    # AC Charge (#277): regs 68-73, probe FlexBOSS21_52XXXXXX78.json. Keeps
    # the stale pylxpweb alias chains above — and the shipped unique_ids.
    ScheduleTimeSpec(
        key="ac_charge",
        cloud_prefix="HOLD_AC_CHARGE",
        base_register=AC_CHARGE_SCHEDULE_BASE_REGISTER,
        gate="control",
        local_param_keys=LOCAL_AC_CHARGE_TIME_PARAM_KEYS,
    ),
    # AC First (#295): regs 152-157, probe SNA12KUS_52XXXXXX68.json blocks
    # 106-111 + the portal's SNA working-mode page holdParams. SNA-only UI.
    ScheduleTimeSpec(
        key="ac_first",
        cloud_prefix="HOLD_AC_FIRST",
        base_register=152,
        gate="offgrid",
        local_param_keys=_canonical_time_param_keys("HOLD_AC_FIRST", 152),
    ),
    # Forced Charge (PV charge priority, #295): regs 76-81 (EG4-18KPV spec,
    # pylxpweb SCHEDULE_CONFIGS). Suppressed on EG4_OFFGRID: the cloud
    # rejects HOLD_FORCED_CHARGE_* writes on a 12000XP v2 (REMOTE_SET_ERROR,
    # serial 61062J0147, #295 live report) and the SNA working-mode portal
    # page contains ZERO HOLD_FORCED_CHARGE params (vs a full Forced
    # Discharge schedule widget) — same evidence standard as the #307
    # Battery Backup gate.
    ScheduleTimeSpec(
        key="forced_charge",
        cloud_prefix="HOLD_FORCED_CHARGE",
        base_register=76,
        gate="control_grid_tied",
        local_param_keys=_canonical_time_param_keys("HOLD_FORCED_CHARGE", 76),
    ),
    # Forced Discharge (#295): regs 84-89; suppressed on EG4_OFFGRID like the
    # forced discharge power/SOC numbers (PR #220 / issue #197).
    ScheduleTimeSpec(
        key="forced_discharge",
        cloud_prefix="HOLD_FORCED_DISCHARGE",
        base_register=84,
        gate="control_grid_tied",
        local_param_keys=_canonical_time_param_keys("HOLD_FORCED_DISCHARGE", 84),
    ),
    # Peak Shaving: regs 209-212, 2 windows. Live write-verified on a
    # FlexBOSS21 (FAAB-2525): writeTime 01:05 -> reg 211=1281. Cloud reads
    # report the schedule under interleaved LSP_HOLD_DIS_CHG_POWER_TIME_37..44
    # params; cloud writes use the atomic writeTime composites. EG4_HYBRID only
    # (absent on the SNA12K-US probe). pylxpweb ScheduleType.PEAK_SHAVING.
    ScheduleTimeSpec(
        key="peak_shaving",
        cloud_prefix="HOLD_PEAK_SHAVING",
        base_register=209,
        gate="hybrid",
        local_param_keys=_canonical_time_param_keys(
            "HOLD_PEAK_SHAVING", 209, windows=2
        ),
        windows=2,
        bare_first_window=False,
        write_via_time_api=True,
        read_lsp_base=37,
    ),
    # Generator Charge: regs 256-259, 2 windows. Live-verified on the
    # FlexBOSS21; the SNA12K-US probe (blocks 255-259) carries the same
    # HOLD_GEN_{START|END}_{HOUR|MINUTE}_{1,2} names, so this family also
    # applies to EG4_OFFGRID. pylxpweb ScheduleType.GEN_CHARGE.
    ScheduleTimeSpec(
        key="gen_charge",
        cloud_prefix="HOLD_GEN",
        base_register=256,
        gate="hybrid_or_offgrid",
        local_param_keys=_canonical_time_param_keys("HOLD_GEN", 256, windows=2),
        windows=2,
        bare_first_window=False,
        write_via_time_api=True,
    ),
    # Off-Grid: regs 269-274, 3 windows. Live-correlated end1=23:59 on the
    # FlexBOSS21; writes not live-tested (off-grid transitions on live home
    # hardware). EG4_HYBRID only. pylxpweb ScheduleType.OFF_GRID.
    ScheduleTimeSpec(
        key="off_grid",
        cloud_prefix="HOLD_OFF_GRID",
        base_register=269,
        gate="hybrid",
        local_param_keys=_canonical_time_param_keys("HOLD_OFF_GRID", 269, windows=3),
        windows=3,
        bare_first_window=False,
        write_via_time_api=True,
    ),
)
