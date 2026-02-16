# Grid Type Fix Design (Issue #159)

## Problem

LXP-family devices on split-phase or single-phase grids get incorrect voltage readings and false grid type mismatch warnings.

**Root causes:**
1. pylxpweb `FAMILY_DEFAULT_FEATURES[LXP]` hardcodes `split_phase=False, three_phase_capable=True` for ALL LXP models
2. `InverterFeatures.from_device_type_code()` doesn't distinguish LXP-EU (dtc=12) from LXP-LB (dtc=44)
3. Registers 127-128 (EPS L1/L2) and 193-194 (Grid L1/L2) have `models=EG4` filter, blocking LXP
4. Single-phase users get NO grid/EPS voltage sensors because `grid_voltage_r` and `eps_voltage_r` are in `THREE_PHASE_ONLY_SENSORS`
5. Grid type mismatch detection overrides user's correct config selection

## Design

### 1. pylxpweb: Fix LXP-LB Feature Detection

**File:** `_features.py` — `InverterFeatures.from_device_type_code()`

After applying LXP family defaults, override for dtc=44 (LXP-LB Americas):
- `split_phase=True`, `three_phase_capable=False`, `grid_type=SPLIT_PHASE`

LXP-EU (dtc=12) keeps existing behavior (three_phase from family defaults).

### 2. pylxpweb: Widen Register Model Filter

**File:** `inverter_input.py`

Change `models=EG4` to `models=ALL` for registers:
- 127-128: EPS L1/L2 voltage (confirmed working on LXP-LB-BR by community)
- 129-132: EPS L1/L2 active and apparent power
- 193-194: Grid L1/L2 voltage (may return 0 on some LXP — harmless)

### 3. eg4_web_monitor: Phase-Aware Common Voltage Sensors

Create `grid_voltage` and `eps_voltage` as common sensor keys for single-phase and split-phase users.

**Coordinator aliasing** (`coordinator_local.py` + `coordinator_http.py`):
For non-three-phase devices, copy R-phase readings to common keys:
- `grid_voltage_r` → `grid_voltage`
- `eps_voltage_r` → `eps_voltage`

**Sensor definitions** (`const/sensors/inverter.py`):
Add `grid_voltage` and `eps_voltage` with clean display names.

**Filtering** (`device_types.py`):
Add `NON_THREE_PHASE_SENSORS` frozenset containing `grid_voltage` and `eps_voltage`.
Update `_should_create_sensor()` to exclude these for three-phase users.

**Static entity keys** (`coordinator_mappings.py`):
Add to `ALL_INVERTER_SENSOR_KEYS`.

**Result by phase type:**

| Phase Type | Grid Voltage Sensors | EPS Voltage Sensors |
|---|---|---|
| Single | `grid_voltage` (reg 12, 230V) | `eps_voltage` (reg 20) |
| Split | `grid_voltage` (reg 12, 240V) + `grid_voltage_l1/l2` (regs 193-194) | `eps_voltage` (reg 20) + `eps_voltage_l1/l2` (regs 127-128) |
| Three | `grid_voltage_r/s/t` (regs 12-14) | `eps_voltage_r/s/t` (regs 20-22) |

### 4. eg4_web_monitor: Remove Mismatch Detection

Remove entirely:
- `_check_grid_type_mismatch()` method and all call sites
- `_check_missing_grid_type()` method and all call sites
- `_grid_type_mismatch_notified` set
- `strings.json` → `issues.grid_type_mismatch` translation key
- All 13 locale translations for `grid_type_mismatch`

Keep unchanged:
- `_features_from_family()` + `_apply_grid_type_override()` (config is authoritative)
- Config flow grid type selection (three options: single, split, three-phase)
- `SPLIT_PHASE_ONLY_SENSORS` / `THREE_PHASE_ONLY_SENSORS` frozensets
- `_should_create_sensor()` (extended with NON_THREE_PHASE_SENSORS check)

### 5. Test Updates

- Remove `TestGridTypeMismatch` (6 tests)
- Add test: `from_device_type_code(44)` → `split_phase=True, three_phase_capable=False`
- Add test: `grid_voltage` / `eps_voltage` present for single-phase, absent for three-phase
- Add test: `grid_voltage` / `eps_voltage` present for split-phase
- Update any tests asserting on `_grid_type_mismatch_notified`
