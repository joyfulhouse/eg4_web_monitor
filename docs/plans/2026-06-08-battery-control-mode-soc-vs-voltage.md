# Battery Control Mode (SOC vs Voltage) — Implementation Plan

**Issue:** eg4-xix (beads) · donation-funded · relates to closed #48
**Date:** 2026-06-08

## Goal
Let users control their battery by **SOC (closed-loop)** or **Voltage (open-loop)**, per
the inverter's own reg-179 regime bits, and declutter entities so only the relevant set is
enabled. Works in cloud, hybrid, and local modes.

## Decisions (locked with user)
1. **Separate charge + discharge** regime. Two `Select` entities (`Battery Charge Control`,
   `Battery Discharge Control`) = SOC/Voltage, backed by reg 179 (`FUNC_EXT_REGISTER`)
   bit 9 (charge) / bit 10 (discharge). `False`=SOC, `True`=Voltage.
2. **New voltage Number entities** (twins of existing SOC numbers):
   - System Charge Voltage Limit — reg 228 `HOLD_SYSTEM_CHARGE_VOLT_LIMIT` ÷10
   - On-Grid Cut-Off Voltage — reg 169 `HOLD_ONGRID_EOD_VOLTAGE` ÷10
   - Off-Grid Cut-Off Voltage — reg 100 `HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT` ÷10
   - AC Charge Start Voltage / AC Charge End Voltage — reg 158/159 ÷10 (whole-volt step)
3. **Config (Options "Configure" + Reconfigure menu):** two pickers "Battery Charge/Discharge
   Control Mode". Pre-read live reg-179 state; on change, write the bits to the inverter with
   an inline warning note. Default **SOC** (migration-safe).
4. **Hiding = disabled-by-default.** All entities always created; off-mode ones use
   `entity_registry_enabled_default=False` (computed from the live regime at registration,
   falling back to stored option, falling back to SOC). Non-destructive.
5. **Warn when an inactive limit is set:** each gated entity exposes
   `extra_state_attributes` (`active_control_mode`, `is_effective`) and logs a non-blocking
   warning on set when its side isn't the current active mode. The write still persists.
6. **pylxpweb broad refactor:** make the transport-only value/bit control methods dual-path
   (cloud via `control_function` for bits + `read_parameters`/`write_parameter` for values;
   transport via `read/write_transport_register` + `write_transport_bit`). Add a friendly
   `BatteryControlMode` enum + mode-aware helpers. Add the missing reg-228 definition.

## pylxpweb changes (do first; integration pins it)
- `models.py`: add `BatteryControlMode(StrEnum)` {SOC, VOLTAGE}; export from package root.
- `registers/inverter_holding.py`: add reg-228 `HoldingRegisterDefinition` (DIV_10);
  add `ha_entity_key` to reg 100/169.
- `devices/inverters/hybrid.py`:
  - Make `_set_register_bit`/`_get_register_bit` dual-path (derive cloud fn-param name from
    `REGISTER_TO_PARAM_KEYS[register][bit]`; cloud uses atomic `control_function`).
  - Add `_read_register_value(register, param_key)` / `_write_register_value(...)` dual-path.
  - Convert to dual-path: `get/set_charge_last`, `battery_charge_control`,
    `battery_discharge_control`, `system_charge_soc_limit`, `system_charge_volt_limit`,
    `on/off_grid_cutoff_soc`, `on/off_grid_cutoff_voltage`, `charge/discharge_current_limit`,
    `start_discharge_power`.
  - Add friendly: `get/set_battery_charge_control_mode`, `get/set_battery_discharge_control_mode`
    (enum), `get_active_charge_limit`, `get_active_discharge_cutoff` (derive from live mode).
- Tests: cloud + transport for reg-179 RMW (bit preservation), value methods, friendly helpers.
- Version → `0.9.36b1`; integration manifest pin `pylxpweb>=0.9.36b1`.

## Integration changes
- `const/config_keys.py`: `CONF_CHARGE_CTRL_MODE`, `CONF_DISCHARGE_CTRL_MODE`,
  `CTRL_MODE_SOC`/`CTRL_MODE_VOLTAGE`, defaults; voltage min/max/step; `PARAM_HOLD_*` keys.
- `const/device_types.py`: side/mode classification + `control_enabled_default()` +
  `control_side_mode()` helpers.
- `coordinator_local.py`: add read ranges (100, 158–159, 169, 228).
- `coordinator.py`: `async_write_battery_ctrl_mode()`; live-mode reader helper.
- `number.py`: 5 voltage Number classes; per-entity `entity_registry_enabled_default`;
  `is_effective`/`active_control_mode` attrs + warn-on-inactive-set (existing SOC numbers too).
- `select.py`: 2 regime Select classes (mirror `EG4PVInputModeSelect`).
- `_config_flow/options.py` + `__init__.py` reconfigure menu: two pickers, pre-read live,
  write-on-change + warning note.
- `strings.json` + `translations/en.json`: labels/descriptions/entity names.
- Tests: options pre-read/write, gating defaults, effective warning, entity counts.

## Verify during/after
- cloud `remoteRead` returns raw register values under named keys (assumed; confirm live).
- AC charge voltage whole-volt step (firmware rejects fractional).
- Entity-count tests in `test_sensor_entities.py` / number/select tests updated.

## Review outcome (4 reviewers: 3 code-reviewer agents + Codex)

Two REAL bugs found and fixed:
1. **Voltage read scaling (Codex BUG 1).** Local transport returns raw decivolts; cloud
   returns already-scaled volts. A blind ÷10 broke cloud reads. Fixed with magnitude-aware
   `EG4BaseNumberEntity._volts_from_param` (≥100 → ÷10, else as-is). See memory
   `voltage-param-scaling-cloud-vs-local`. (Pre-existing `PVStartVoltageNumber` has the same
   latent cloud bug — out of scope; range overlap prevents the magnitude trick.)
2. **Options pre-fill overwrite (Codex BUG 2).** `_current_control_modes` overwrote the stored
   option with a live-default SOC when reg 179 wasn't polled, so saving could silently flip a
   Voltage install to SOC. Fixed: only use live when the FUNC_BAT_*_CONTROL param is actually
   present; `_apply_battery_control_mode` skips the write when the live regime is unknown.

Also: regime `Select.current_option` now returns `None` (unknown) instead of a hardcoded "SOC"
until reg 179 is polled.

Refuted / consistent-with-existing-pattern (no change): options persistence (the SelectSelector
fields ARE in the options schema, so `async_create_entry(data=user_input)` persists them);
AC-charge-voltage param-key aliasing (read key matches in both modes); per-class number entities;
bare-CoordinatorEntity selects; `{clean_model}_{serial}_suffix` unique_id (matches number platform);
`_attr_name`-without-translation_key (matches existing number/select entities).

Status: 917 integration + 2098 pylxpweb tests pass; ruff + mypy clean. Pending: commit (pylxpweb
first, per dev-container note) and live Docker validation across cloud/local/hybrid.
