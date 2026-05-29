#!/usr/bin/env bash
# Seed the bd backlog for the maintainability / contract-hardening initiative.
#
# Source of findings: docs/claude/MAINTAINABILITY_FINDINGS.md (Claude + Codex peer review, 2026-05-29)
#
# Prereq: a HEALTHY bd workspace. As of 2026-05-29 the local bd DB had a
# schema-migration block (bd v1.0.5 vs older cloned remote schema, "dirty tables").
# Resolve that first (match the team's bd version / repair the Dolt working set),
# verify with `bd status` showing the 127 issues + a configured prefix, THEN run:
#
#     ./scripts/bd_seed_maintainability.sh
#
# Idempotency: NOT idempotent — running twice creates duplicate epics. Run once.
# Dry preview: pass --dry-run to echo the bd commands without executing.
set -euo pipefail

DRY="${1:-}"
run() {
  if [[ "$DRY" == "--dry-run" ]]; then
    printf 'bd %s\n' "$*"
    # emit a fake id so dependent commands echo coherently in dry-run
    echo "eg4-DRY"
  else
    bd "$@"
  fi
}

# ---- Standing policy embedded in every epic's acceptance criteria ----
SHIP_GATE="SHIP GATE (mandatory before any PR/merge of work under this epic): \
run a Codex ADVERSARIAL review on the diff via /codex:adversarial-review \
(or the codex:codex-rescue subagent). Resolve or explicitly justify EVERY Codex \
finding; do not ship without a clean or acknowledged Codex pass. Pre-gate checks \
must also pass in each affected repo: \
'uv run ruff check --fix && uv run ruff format && uv run mypy --strict . && uv run pytest'."

echo "==> Creating epics"
E1=$(run create "Live bug hotfixes (scaling + mapping)" --type epic -p P0 -l live-bug --silent \
  -d "Fix concrete LOCAL/CLOUD data bugs surfaced by the maintainability review (docs/claude/MAINTAINABILITY_FINDINGS.md). User-facing; prove the root-cause thesis." \
  --acceptance "$SHIP_GATE")

E2=$(run create "Register-derived contract-validation harness" --type epic -p P1 -l contract,ci --silent \
  -d "Make the register table the single source of truth and assert it in CI. Highest-leverage change (both reviewers ranked #1): closes the innermost seam; would have caught genuine #172-style mismatches and PV-string-count gaps. MUST compare resulting physical values against real payloads, not scale symbols (the maxChgCurr false positive proved symbol-comparison is insufficient)." \
  --acceptance "$SHIP_GATE")

E3=$(run create "Real-object test fixtures (eliminate MagicMock shape-blindness)" --type epic -p P1 -l tests --silent \
  -d "Replace MagicMock with real pylxpweb objects / create_autospec(spec_set=True). MagicMock fabricates any attribute, so the suite cannot catch F1/F7 shape drift today." \
  --acceptance "$SHIP_GATE")

E4=$(run create "Typed contract at the pylxpweb<->integration seam" --type epic -p P2 -l contract,typing --silent \
  -d "pylxpweb publishes Protocol/DTOs for consumed shapes + a public cache-TTL API; integration drops Any and stops poking private attrs. Makes mypy --strict enforce the seam (F1/F6/F7 become build failures)." \
  --acceptance "$SHIP_GATE")

E5=$(run create "Consolidate duplicated cloud/local/hybrid paths" --type epic -p P2 -l refactor --silent \
  -d "Collapse duplicated battery-bank extractors and the triple parallel-group/GridBOSS-overlay implementations into single canonical workflows. Structural cure for F4/M2/M3 (fix-one-miss-the-other)." \
  --acceptance "$SHIP_GATE")

E6=$(run create "Unify feature detection on pylxpweb" --type epic -p P3 -l refactor --silent \
  -d "Integration consumes pylxpweb detect_features/InverterFeatures instead of re-deriving under different key names; keep only the user grid-type override. Kills F6." \
  --acceptance "$SHIP_GATE")

E7=$(run create "Dead code cleanup" --type epic -p P3 -l cleanup --silent \
  -d "Remove shadowed/unreachable code and document authoritative sources. Reduces surface area; stops misleading greps (F2)." \
  --acceptance "$SHIP_GATE")

echo "    E1=$E1 E2=$E2 E3=$E3 E4=$E4 E5=$E5 E6=$E6 E7=$E7"

mk() { # mk <parent> <priority> <labels> <title> <description>
  run create "$4" --type task -p "$2" --parent "$1" -l "$3" --silent -d "$5"
}

echo "==> E1 tasks (live bugs)"
mk "$E1" P3 chore,pylxpweb "maxChgCurr scaling: VALIDATED not-a-bug (keep guard test)" \
  "RESOLVED 2026-05-29: cloud maxChgCurr raw=6000 (0.01A, /100 -> 60A) and modbus reg81 raw=600 (0.1A, /10 -> 60A) yield the same physical amps; scaling.py SCALE_100 is correct. A prior blind flip to SCALE_10 was reverted; guard test test_bms_current_limit_cloud_local_same_physical_amps added. No code change needed — task exists for the audit trail." >/dev/null
mk "$E1" P2 feature,pylxpweb,integration "PV strings: explicit declarative per-model pv_string_count (0-n)" \
  "Add an EXPLICIT, declarative per-inverter-MODEL pv_string_count (0..n) that the model sets directly — single obvious source of truth, easy to maintain. Create exactly pv1..pvN sensors (0 => none, for battery-only/AC-coupled inverters; generalizes downward too). 3 is NOT a default (our 18kPV/FlexBOSS21 coincidentally have 3). Known: 18kPV=3, FlexBOSS21=3. Unmapped models fall back to the register-set-implied count (registers_for_model) so pv1-3 never regresses, with TODO(confirm) markers. Relates to E6 (feature detection). TDD, per-count tests." >/dev/null
mk "$E1" P1 live-bug,integration "Fix cloud battery-bank sensor omission (M2)" \
  "_extract_battery_bank_from_object() (coordinator_mixins.py:1121-1130) emits only cycle/SoH/max-cell-temp/temp-delta; LOCAL emits min-cell-temp, min-cell-voltage, BMS limits, BMS type (coordinator_mappings.py:731-741). Align cloud extractor to LOCAL sensor set; add parity test." >/dev/null
mk "$E1" P1 live-bug,integration "Fix AC-couple PV adjustment missing in HYBRID/HTTP (M3)" \
  "LOCAL adds AC-couple smart-port power into pv_total_power post-overlay (coordinator_local.py:1739-1769); HTTP has no equivalent (coordinator_http.py:626-636). HYBRID AC-coupled users show low pv_total_power. Mirror the adjustment; add test." >/dev/null

mk "$E1" P3 feature,pylxpweb "Follow-up: PV4-6 per-string energy register coverage (>3-string only)" \
  "Codex MED (not a blocker): PV4-6 energy registers (223-231) are not in the combined input-register read group (only pv1-3 energy / 217-222). For >3-string inverters, LOCAL energy accounting would miss pv4-6 string energy. No user-facing per-string energy sensor exists today, so this is internal-only. Extend the read group + ENERGY_FIELD mapping if/when per-string energy is needed for >3-string models." >/dev/null

echo "==> E2 tasks (contract harness)"
mk "$E2" P1 contract,pylxpweb "Scale-parity test: register cloud_api_field scale == scaling.py" \
  "For every register with cloud_api_field, assert the cloud and modbus paths yield the SAME PHYSICAL VALUE when fed real sample payloads (NOT just matching scale symbols — maxChgCurr has different raw units per path yet is correct). Fails CI on drift. Catches genuine #172-style mismatches." >/dev/null
mk "$E2" P1 contract,pylxpweb "Field-mapping completeness test" \
  "Assert every dataclass field populated by from_modbus_registers() has a RUNTIME_FIELD/ENERGY_FIELD/BATTERY_FIELD/GRIDBOSS_FIELD mapping. Catches PV4-6 and all future silent-None gaps." >/dev/null
mk "$E2" P2 contract,pylxpweb "ha_sensor_key reachability test" \
  "Assert every register with non-None ha_sensor_key is reachable end-to-end (register -> field mapping -> dataclass -> property)." >/dev/null
mk "$E2" P1 ci "Wire contract harness into CI (both repos)" \
  "Add the parity/completeness/reachability tests to CI for pylxpweb and the integration so drift fails per-commit." >/dev/null

echo "==> E3 tasks (real-object fixtures)"
mk "$E3" P1 tests "Build real pylxpweb object fixtures per path" \
  "Fixtures using real BatteryBankData (LOCAL), BatteryBank (CLOUD), runtime/midbox objects, both for HYBRID. Replace MagicMock device objects." >/dev/null
mk "$E3" P1 tests "Replace MagicMock with real objects / autospec(spec_set=True)" \
  "Swap MagicMock in mapping/coordinator tests for real objects or create_autospec(..., spec_set=True). Surfaces F1/F7 attribute drift in CI." >/dev/null
mk "$E3" P2 tests "Cross-path sensor-set parity assertions" \
  "Assert LOCAL and CLOUD produce the expected (and reconciled) sensor key sets per device type; encode known/intended divergences explicitly." >/dev/null

echo "==> E4 tasks (typed contract)"
mk "$E4" P2 contract,typing,pylxpweb "Export Protocol/DTOs for consumed shapes" \
  "pylxpweb publishes typed Protocols/frozen DTOs for InverterRuntime, BatteryBankData, BatteryModuleData, MidboxData, InverterFeatures — the integration's consumed surface." >/dev/null
mk "$E4" P2 contract,pylxpweb "Public cache-TTL API (stop private-attr poking)" \
  "Add set_cache_ttls(runtime=, energy=, battery=) to pylxpweb so the integration stops writing inverter._runtime_cache_ttl/_energy/_battery (coordinator.py:552-554)." >/dev/null
mk "$E4" P2 typing,integration "Drop Any; annotate mapping helpers; stop reading _transport_*" \
  "Type coordinator_mappings helpers against the new DTOs (remove Any at lines 9/483/668/830); replace inverter._transport_* reads with public accessors." >/dev/null
mk "$E4" P2 ci,typing "Enforce mypy --strict across the seam in CI" \
  "With DTOs in place, mypy --strict must catch renamed/removed properties at build time. Add/verify in CI for both repos." >/dev/null

echo "==> E5 tasks (consolidate paths)"
mk "$E5" P2 refactor,integration "Unify battery-bank extraction" \
  "Merge _build_battery_bank_sensor_mapping (LOCAL) and _extract_battery_bank_from_object (cloud) into one adapter producing a canonical dict for LOCAL/CLOUD/HYBRID. Makes parity visible in one place; resolves M2." >/dev/null
mk "$E5" P2 refactor,integration "Unify parallel-group + GridBOSS overlay workflow" \
  "One _process_parallel_group_data(pg_data, gridboss_data, source) called by both coordinators; fold the LOCAL AC-couple post-step (M3) behind a flag. Removes triple parallel-group impl + divergent overlay call sites (F4)." >/dev/null
mk "$E5" P2 ci,tests "CI parity test across config/config-local/config-hybrid" \
  "Wire the existing capture dirs + scripts into a CI parity check so cloud/local/hybrid entity sets are compared automatically." >/dev/null

echo "==> E6 task (feature detection)"
mk "$E6" P3 refactor,integration "Consume pylxpweb detect_features; drop duplicate" \
  "Integration uses pylxpweb detect_features/InverterFeatures; keep only the user grid-type override layered on top; delete _features_from_family duplicate logic (coordinator_mappings.py:1011-1097). Add a test asserting both agree per known device." >/dev/null

echo "==> E7 tasks (dead code)"
mk "$E7" P3 cleanup,pylxpweb "Delete shadowed registers.py" \
  "src/pylxpweb/registers.py (module, 511 lines) is shadowed/unreachable by the registers/ package. Confirm no external consumers, then delete." >/dev/null
mk "$E7" P3 cleanup,pylxpweb "Resolve dead scheduling.py SCHEDULE_TYPES/SCHEDULE_REGISTERS" \
  "registers/scheduling.py exports an unused 7-day schedule system (regs 500-723) that contradicts the live 3-period system (constants/registers.py, regs 68-84). Remove or wire it up; document which schedule register range is authoritative." >/dev/null

echo "==> Done. Review with: bd list --type epic   and   bd ready"
