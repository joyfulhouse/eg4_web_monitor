"""Working mode configuration constants for the EG4 Web Monitor integration.

This module contains configurations for inverter working modes and SOC limit
parameters used by switch and number entities.

Optional per-mode gating keys (read by switch.py setup):
- ``grid_tied_only``: skip the switch on EG4_OFFGRID inverters (12000XP /
  6000XP have no grid sell-back).

Optional per-mode presentation keys (read by EG4WorkingModeSwitch):
- ``entity_key``: override for the unique_id/entity_id key when the
  param-derived default would mislead (e.g. FUNC_RUN_WITHOUT_GRID is the
  web UIs' "Fast Zero Export").
- ``translation_key``: localize the entity name via strings.json instead
  of the hardcoded ``name`` (which HA would otherwise let override the
  translation — issue #262 gotcha).
- ``enabled_default``: set False to register the switch disabled by
  default (niche features, e.g. Share Battery — GH #288).
- ``requires_known_state``: set True so an ABSENT state key reads
  unavailable/None instead of a confident OFF. Opt in for any mode without a
  family gate — there, a device that simply lacks the parameter is a live
  possibility rather than a contradiction (GH #484). Carried to Charge Last
  and Share Battery in GH #497; still OPT-IN rather than the shared base,
  because the remaining modes are family- or capability-gated and flipping
  all of them would change long-standing behavior for no established
  exposure.
- ``legacy_attrs``: map legacy state-attribute names to parameter keys when
  folding a standalone switch into the table must preserve its exact
  attribute shape (including returning None when no value is available).
- ``action_name``: override the action label used in errors and logs when a
  folded standalone switch has an established user-visible label.

Cloud-only state parameters need no per-mode flag: switch.py setup probes
the installed pylxpweb register map (``_local_params_can_carry``) and skips
any mode whose state key cannot be decoded from local registers whenever
the parameter cache holds local-raw register data (LOCAL mode, or HYBRID
with a local transport attached) — otherwise is_on could never reflect the
true state. The probe doubles as the version guard for newly pinned bits.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory

# =============================================================================
# Working Mode Configurations
# =============================================================================
# These define switch entities for various inverter operational modes

WORKING_MODES: dict[str, dict[str, Any]] = {
    # AC Charge Mode (FUNC_AC_CHARGE, reg 21 bit 7). Kept for grid-tied
    # families; suppressed on EG4_OFFGRID via FAMILY_UNSUPPORTED_CONTROL_PARAMS
    # (GH #563): the SNA portal models AC Charge as a schedule-defined working
    # mode (time windows, no master toggle) and the off-grid firmware RE
    # session graded the backing bit firmware-proven-inert there — stored and
    # readback-visible but never consumed by the ARM→DSP mapper or charge
    # logic. The schedule itself stays fully editable through the AC Charge
    # time entities (SCHEDULE_TIME_TYPES).
    "ac_charge_mode": {
        "name": "AC Charge Mode",
        "param": "FUNC_AC_CHARGE",
        "description": "Allow battery charging from AC grid power",
        "icon": "mdi:battery-charging-medium",
        "entity_category": EntityCategory.CONFIG,
    },
    # Charge Last (FUNC_CHARGE_LAST, register 110 bit 4, GH #177) flips PV
    # surplus priority. Disabled ("charge first"), PV charges the battery
    # before exporting surplus; enabled, PV serves house loads and grid
    # export first, reserving battery headroom for peak production. The bit
    # is available to every control-capable family and has no dedicated
    # pylxpweb enable/disable methods, so cloud writes use the generic
    # function-control API. ``legacy_attrs`` preserves the exact attribute
    # contract of the former standalone switch during the table-driven fold.
    "charge_last_mode": {
        "name": "Charge Last",
        "param": "FUNC_CHARGE_LAST",
        "description": "Prioritize house loads and grid export before battery charging",
        "icon": "mdi:battery-clock",
        "entity_category": EntityCategory.CONFIG,
        "legacy_attrs": {"func_charge_last": "FUNC_CHARGE_LAST"},
        "action_name": "charge last",
        # Ungated by family, so "this device does not report the function"
        # is reachable and a toggleable OFF there is indistinguishable from
        # a real one (GH #497). Reading it from reg 110 bit 4 does NOT make
        # the key optional: a bit-field register decodes every one of its
        # names on each successful read, so LOCAL/HYBRID populate this key
        # whatever the bit's value, and the #282 carry-forward keeps it once
        # seen. The absent window is therefore the pre-first-read one — an
        # accepted, briefly-visible change from OFF to unavailable.
        "requires_known_state": True,
    },
    "pv_charge_priority_mode": {
        "name": "PV Charge Priority Mode",
        "param": "FUNC_FORCED_CHG_EN",
        "description": "Prioritize PV charging during specified hours",
        "icon": "mdi:solar-power",
        "entity_category": EntityCategory.CONFIG,
    },
    "forced_discharge_mode": {
        "name": "Forced Discharge Mode",
        "param": "FUNC_FORCED_DISCHG_EN",
        "description": "Force battery discharge for grid export",
        "icon": "mdi:battery-arrow-down",
        "entity_category": EntityCategory.CONFIG,
    },
    "peak_shaving_mode": {
        "name": "Grid Peak Shaving Mode",
        "param": "FUNC_GRID_PEAK_SHAVING",
        "description": "Grid peak shaving to reduce demand charges",
        "icon": "mdi:chart-bell-curve-cumulative",
        "entity_category": EntityCategory.CONFIG,
    },
    "battery_backup_mode": {
        "name": "Battery Backup Mode",
        "param": "FUNC_BATTERY_BACKUP_CTRL",
        "description": "Emergency Power Supply (EPS) backup functionality",
        "icon": "mdi:home-battery",
        "entity_category": EntityCategory.CONFIG,
    },
    # Grid Sell Back enable (reg 21 bit 15, GH #135) — "Feed-in Grid" in the
    # protocol. Works on all transports: the bit is live-verified and named
    # in pylxpweb's local register map.
    "grid_sell_back_mode": {
        "name": "Grid Sell Back",
        "param": "FUNC_FEED_IN_GRID_EN",
        "description": "Allow exporting (selling) surplus power to the grid",
        "icon": "mdi:transmission-tower-export",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
    },
    # Export PV Only (FUNC_PV_SELL_TO_GRID_EN, GH #135) — register 179
    # bit 3, pinned 2026-06-12 via authorized live cloud toggles
    # raw-verified on BOTH 12K-hybrid models (FlexBOSS21 52842P0581 and
    # 18kPV 4512670118: reg-179 raw 0x104c <-> 0x1044, single bit 3,
    # restores verified by re-read). Local read/write resolves through
    # pylxpweb's register map from 0.9.36b6 on; against older installs the
    # switch.py setup probe keeps it cloud-only.
    "export_pv_only_mode": {
        "name": "Export PV Only",
        "param": "FUNC_PV_SELL_TO_GRID_EN",
        "description": "Only export PV surplus to the grid (never battery)",
        "icon": "mdi:solar-power-variant",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
    },
    # Fast Zero Export (FUNC_RUN_WITHOUT_GRID, GH #274) — register 110
    # bit 1 ("FunctionEn1.ubFastZeroExport" in the LXP protocol PDF; same
    # bit in pylxpweb's base AND SNA register-110 tables). Both web UIs
    # expose the toggle on their Grid Sell tab (EG4: GH #135 screenshot;
    # Luxpower: GH #274 screenshot) and both flip cloud param
    # FUNC_RUN_WITHOUT_GRID. Vendor help text: speeds up the zero-export
    # control loop (import control slows down); select as the opposite of
    # Grid Sell Back. Grid-tied families only — off-grid units have no
    # export to suppress. No dedicated pylxpweb enable/disable methods:
    # the cloud path uses the generic function-control API, so no
    # version guard is needed.
    "fast_zero_export_mode": {
        "name": "Fast Zero Export",
        "param": "FUNC_RUN_WITHOUT_GRID",
        "description": "Speed up zero-export control (opposite of Grid Sell Back)",
        "icon": "mdi:transmission-tower-off",
        "entity_category": EntityCategory.CONFIG,
        "grid_tied_only": True,
        # entity_key/translation_key: the param name would yield
        # "run_without_grid", which misdescribes the function — the web
        # UIs and the protocol PDF both call it Fast Zero Export.
        "entity_key": "fast_zero_export",
        "translation_key": "fast_zero_export",
    },
    # Share Battery (FUNC_BAT_SHARED, GH #288) — register 110 bit 3. The
    # portals show a per-inverter "Share Battery" toggle for multi-inverter
    # systems sharing one battery bank (only the primary sits on the battery
    # CAN bus; a sharing secondary legitimately reads battery_count reg96=0).
    # Reporter-verified: the portal write is cloud function FUNC_BAT_SHARED
    # (generic function-control API — no dedicated pylxpweb methods, so no
    # version guard needed). Bit 3 is a register-110 position where the base
    # (18kPV) and SNA/OFFGRID tables agree in pylxpweb, and battery sharing
    # is a paralleling feature rather than a grid-tied one, so it gets the
    # same gate as Charge Last (all control-capable inverters). Disabled by
    # default: niche multi-inverter feature (avoid entity noise).
    "share_battery_mode": {
        "name": "Share Battery",
        "param": "FUNC_BAT_SHARED",
        "description": "Share one battery bank across paralleled inverters",
        "icon": "mdi:battery-sync",
        "entity_category": EntityCategory.CONFIG,
        "entity_key": "share_battery",
        "translation_key": "share_battery",
        "enabled_default": False,
        # Same reasoning as Charge Last (GH #497): family-neutral gate, so an
        # absent key must read unavailable rather than a confident OFF.
        "requires_known_state": True,
    },
    # Grid Always On (FUNC_ON_GRID_ALWAYS_ON, GH #484 / #559) — the portal's
    # Maintenance -> Remote Set "Smart Load Port" section, "Smart Load" tab,
    # second row (the reporter's 12000XP screenshot); sibling of the "AC
    # coupling" tab that GH #471/#352 already expose. Keeps the smart load
    # port energized from the grid instead of dropping it when the Smart
    # Load Start/End SOC window closes.
    #
    # LOCAL + HYBRID + CLOUD, and no family gate. Both halves are evidence-driven:
    #   - Read-only probe 2026-07-27 against the maintainer's own account:
    #     the cloud returns FUNC_ON_GRID_ALWAYS_ON among reg 179's 16 named
    #     params on an 18kPV, a FlexBOSS21 and a GridBOSS, in the very
    #     127-253 range read that builds the cloud parameter cache. The
    #     reporter's screenshot shows the control live and ENABLED on a
    #     12000XP (EG4_OFFGRID), so the function spans the grid-tied AND
    #     off-grid families — a fail-closed is_hybrid_family() gate would
    #     strip it from the device that asked for it, and there is no
    #     family with evidence of absence to fail-open suppress. The gate
    #     is therefore the enclosing is_supported_control_model() only,
    #     exactly as GH #471's AC Couple switch reasoned. NEVER family-gate
    #     (#490).
    #   - Reg-179 bit 15 pinned (GH #559): hardware-toggle-proven 2026-08-12
    #     on FlexBOSS21 52842P0581 — portal toggle flipped local raw 0x1048
    #     -> 0x9048 (XOR exactly 0x8000), clean restore verified cloud and
    #     local. (Originally app-write-path-proven 2026-08-11 via the EG4
    #     mobile app's name->bit resolver, 4-for-4 against anchors bits
    #     3/7/9/10.) _local_params_can_carry() remains the version guard for
    #     installed pylxpweb builds that still carry the FUNC_179_BIT15
    #     placeholder (pre-0.9.39b11 installs).
    # No dedicated pylxpweb enable/disable methods: local path is the named
    # reg-179 bit write; cloud path uses the generic function-control API.
    # Disabled by default like Share Battery: only meaningful once the smart
    # load port is configured, so it stays out of everyone else's entity list.
    "grid_always_on_mode": {
        "name": "Grid Always On",
        "param": "FUNC_ON_GRID_ALWAYS_ON",
        "description": "Keep the smart load port energized from the grid",
        "icon": "mdi:transmission-tower-import",
        "entity_category": EntityCategory.CONFIG,
        # entity_key/translation_key: the param name would yield
        # "on_grid_always_on"; the portal calls the control "Grid Always On".
        "entity_key": "grid_always_on",
        "translation_key": "grid_always_on",
        "enabled_default": False,
        # No family gate means "device lacks this param" is a real case, not
        # a contradiction — so an absent key must read unavailable, never a
        # fake OFF. This is the half of the #471 AC Couple precedent that
        # makes its family-neutral gate safe; citing that precedent without
        # carrying this over was a PR-review finding.
        "requires_known_state": True,
    },
}

# =============================================================================
# Function Parameter Mapping
# =============================================================================
# Maps function control parameters to their corresponding status parameters

FUNCTION_PARAM_MAPPING = {
    "FUNC_BATTERY_BACKUP_CTRL": "FUNC_BATTERY_BACKUP_CTRL",
    "FUNC_GRID_PEAK_SHAVING": "FUNC_GRID_PEAK_SHAVING",
    "FUNC_AC_CHARGE": "FUNC_AC_CHARGE",
    "FUNC_CHARGE_LAST": "FUNC_CHARGE_LAST",
    "FUNC_FORCED_CHG_EN": "FUNC_FORCED_CHG_EN",
    "FUNC_FORCED_DISCHG_EN": "FUNC_FORCED_DISCHG_EN",
    "FUNC_SET_TO_STANDBY": "FUNC_SET_TO_STANDBY",
    "FUNC_FEED_IN_GRID_EN": "FUNC_FEED_IN_GRID_EN",
    "FUNC_PV_SELL_TO_GRID_EN": "FUNC_PV_SELL_TO_GRID_EN",
    "FUNC_RUN_WITHOUT_GRID": "FUNC_RUN_WITHOUT_GRID",
    "FUNC_BAT_SHARED": "FUNC_BAT_SHARED",
    "FUNC_ON_GRID_ALWAYS_ON": "FUNC_ON_GRID_ALWAYS_ON",
}
