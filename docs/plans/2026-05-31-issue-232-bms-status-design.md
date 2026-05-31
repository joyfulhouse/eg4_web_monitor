# Issue #232 — BMS Charge/Discharge/Force-Charge Status Entities

**Date:** 2026-05-31
**Issue:** [#232](https://github.com/joyfulhouse/eg4_web_monitor/issues/232) — Add binary_sensors for battery BMS status fields
**Status:** Implemented (pylxpweb 0.9.32 + integration); pending pylxpweb release

## Problem

The BMS reports three permission/request flags that are currently surfaced
nowhere in Home Assistant:

| Concept | Cloud API field | Register 95 bit |
|---|---|---|
| Charge allowed | `bmsCharge` | `0x01` |
| Discharge allowed | `bmsDischarge` | `0x02` |
| Force-charge request (calibration) | `bmsForceCharge` | `0x20` |

The cloud API already returns these as booleans (`RuntimeInfo`,
`pylxpweb/models.py:514-516`). In LOCAL (Modbus) mode they must be decoded
from input register 95, which `pylxpweb` currently models as the **enum**
`battery_status_inv` (`{0:Idle, 1:Unknown(1), 2:StandBy, 3:Active}`).

### Register 95 is a bitmap, not an enum

The existing enum values are exactly the bitmap combinations of
`0x01`(charge) | `0x02`(discharge):

| raw | enum label | bitmap reading |
|---|---|---|
| `0x00` | Idle | neither |
| `0x01` | **"Unknown(1)"** | charge-only (battery low) |
| `0x02` | StandBy | discharge-only (battery full) |
| `0x03` | Active | both |
| `0x20` | (unobserved by EG4) | force-charge request |

`0x01` being labelled "Unknown(1)" is the tell: under the bitmap model it is
plainly "charge allowed, discharge blocked." The enum had no firmware citation
(it predates the canonical-register migration and traces to a legacy
`BATTERY_STATUS_MAP`). The committed firmware decompilation is the ESP32
WiFi-dongle (a transparent Modbus bridge) and does not itself interpret reg 95.

**Source of truth for validation:** the authoritative cloud booleans. The LOCAL
reg-95 decode is confirmed by cross-checking the decoded bits against
`bmsCharge`/`bmsDischarge`/`bmsForceCharge` (available together only in HYBRID).

## Decisions (from issue author + maintainer)

1. **Reg 95 = bitmap** (`0x01`/`0x02`/`0x20`), validated against cloud data.
2. **Reuse the sensor platform** (no new `binary_sensor.py`) — boolean
   diagnostic sensors, following the existing `off_grid`/`has_data` precedent.
3. **Decode in pylxpweb + release** — the register source-of-truth library owns
   the decode; the integration consumes the typed seam. Ships cloud AND local.
4. **Attach to the battery-bank device** — grouped with the existing bank BMS
   sensors (`battery_bank_status`, balance/protection/fault/warning, current
   limits). Routed by the `battery_bank_` key prefix.

## Architecture

Both modes converge through the existing unified bank adapter
`build_battery_bank_sensors(bank, source)` (`coordinator_mappings.py:856`),
which reads source attributes off the bank object in both modes. The cloud
`BatteryBank` holds a parent-inverter reference (`battery_bank.py:85`), so it
can expose the same attributes the local `BatteryBankData` does.

### pylxpweb changes (release 0.9.31 → 0.9.32)

1. **Decode helper** — module-level
   `decode_bms_permissions(raw: int) -> tuple[bool, bool, bool]` returning
   `(allow_charge, allow_discharge, force_charge)` from bits `0x01/0x02/0x20`.
   Single source of the bit layout, unit-tested for every combination.
2. **`InverterRuntimeData`** (local dataclass, `transports/data.py`) — add
   `bms_allow_charge | bms_allow_discharge | bms_force_charge: bool | None`,
   decoded from reg 95 (`battery_status_inv`) in `from_modbus_registers`
   (special-case like `soc_soh_packed`). `None` for cloud-built instances.
3. **`BaseInverter`** dual-source properties (`_runtime_properties.py`,
   mirroring `is_using_generator`): `bms_allow_charge/.../bms_force_charge`
   → transport value first, else cloud `RuntimeInfo.bmsCharge/...`.
4. **`BatteryBankData`** (local bank dataclass) — add
   `allow_charge/allow_discharge/force_charge: bool | None`, decoded from reg 95
   via the shared helper in its `from_modbus_registers`.
5. **`BatteryBank`** (cloud device) — add `allow_charge/allow_discharge/
   force_charge` properties delegating to `self._inverter.bms_allow_charge/...`
   (None-safe when no parent inverter).
6. Keep the existing `battery_status_inv` enum entry as-is (read-but-unsurfaced)
   to avoid behaviour regression; annotate its register description with the
   bitmap meaning.
7. Version bump + CHANGELOG; release via CI/CD (`gh release create v0.9.32`).

### Integration changes

1. **`coordinator_mappings.py`** — add to `_BATTERY_BANK_FIELDS` (both modes):
   - `battery_bank_charge_allowed` → `allow_charge`
   - `battery_bank_discharge_allowed` → `allow_discharge`
   - `battery_bank_force_charge` → `force_charge`

   Add the three keys to `BATTERY_BANK_CORE_KEYS`. The cloud property map
   auto-derives via `get_battery_bank_property_map()`.
2. **`const/sensors/inverter.py`** — three new `SENSOR_TYPES` entries
   (name + icon + `entity_category: diagnostic`, boolean value). Names
   disambiguate the read-only BMS force-charge **request** from the writable
   "Forced Charge" control (holding reg 21 bit 11):
   - `battery_bank_charge_allowed` → "BMS Charge Allowed" (`mdi:battery-arrow-up`)
   - `battery_bank_discharge_allowed` → "BMS Discharge Allowed" (`mdi:battery-arrow-down`)
   - `battery_bank_force_charge` → "BMS Force Charge Request" (`mdi:battery-alert`)
3. **`strings.json` / `translations/*.json`** — intentionally NOT modified.
   The integration sets `_attr_name` directly and uses no `translation_key` for
   sensors, so the enum **values are display-ready English** ("Allowed"/
   "Blocked"/"Requested"/"Idle"), matching the peer `battery_bank_status`
   (which also has no strings.json entry). Verified against HA core: a
   `device_class=enum` sensor with `options` and no `translation_key` emits **no
   warning** and renders the raw option values. Full i18n of the states would
   require adding `translation_key` plumbing (absent integration-wide today) and
   is left as a separate enhancement rather than shipping fake/dormant locale
   entries.
4. **`manifest.json`** + **`tests/requirements-test.txt`** — `pylxpweb>=0.9.32`.
5. **`docs/DATA_MAPPING.md`** — document reg-95 bitmap → sensor mapping.

## Validation ("confirm reading with cloud data")

- **pylxpweb unit test** — `decode_bms_permissions` for all bit combinations
  (`0x00,0x01,0x02,0x03,0x20,0x21,0x22,0x23`).
- **pylxpweb property tests** — cloud path returns `RuntimeInfo` booleans;
  local path returns reg-95-decoded booleans; bank delegation works both ways.
- **HYBRID cross-check** — debug-level log when transport reg-95 decode and
  cloud booleans disagree (operationalises the cloud-as-arbiter confirmation).
- **Live confirmation (DONE 2026-05-31)** — `scratchpad/confirm_reg95_vs_cloud.py`
  read reg 95 over Modbus from both hybrid inverters and compared the decode to
  the cloud booleans: 18kPV `4512670118` and FlexBOSS21 `52842P0581` both read
  `reg95=0x03` → `(charge, discharge, force)=(True, True, False)`, **exactly
  matching** `bmsCharge/bmsDischarge/bmsForceCharge` from the cloud API. ✅
- Integration tests: mapping (cloud+local), static-key contract, sensor
  creation, mode parity.

## Scope / non-goals

- These are **bank-aggregate** signals (inverter's view of the BMS). No
  per-individual-battery allow/force fields exist in the API or registers.
- No new HA platform; no change to the writable Forced Charge control.
