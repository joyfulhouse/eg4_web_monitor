---
canonical-for:
  - EG4 portal response shapes
  - EG4 cloud value scaling
  - EG4 parameter read and write representation
  - spec, documentation, sample, and pylxpweb schema divergences
sources:
  - CLAUDE.md
  - CHANGELOG.md
  - docs/api/openapi.yaml
  - docs/api/PORTAL_ENDPOINTS.md
  - docs/api/README.md
  - joyfulhouse/pylxpweb/samples/battery.json
  - joyfulhouse/pylxpweb/samples/energy.json
  - joyfulhouse/pylxpweb/samples/midbox_runtime.json
  - joyfulhouse/pylxpweb/src/pylxpweb/client.py
  - joyfulhouse/pylxpweb/src/pylxpweb/constants/registers.py
  - joyfulhouse/pylxpweb/src/pylxpweb/models.py
  - joyfulhouse/pylxpweb/src/pylxpweb/constants/scaling.py
  - joyfulhouse/pylxpweb/src/pylxpweb/endpoints/control.py
  - joyfulhouse/pylxpweb/src/pylxpweb/endpoints/devices.py
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-08
---

# Schemas and scaling

## Governing asymmetry

> **Cloud reads deliver raw integers that still need scaling. Named cloud writes accept pre-scaled engineering units.** `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py:49-192`; `pylxpweb/src/pylxpweb/endpoints/control.py:420-439`

The read and write paths are intentionally asymmetric. Applying a read divisor again before `remoteSet/write` corrupts a setpoint; sending a local raw register integer as `valueText` can be wrong by the same factor in the opposite direction. `inferred` from the verified read/write contracts above

| Direction | Wire representation | Required client behavior | Evidence |
|---|---|---|---|
| Runtime, energy, battery, MID and parameter **read** | Raw integer fields | Apply the field's divisor while constructing engineering-unit values. Preserve `None` and documented sentinels. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:448-755,827-1035`; `constants/scaling.py:49-192` |
| Named parameter **write** via `remoteSet/write` | Engineering value in string field `valueText` | Convert the local/canonical raw value to its engineering value first; for example raw 595 with divisor 10 becomes `"59.5"`. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:200-217,420-439` |
| Boolean function write | Named `functionParam` plus lower-case `enable` | Use `functionControl`; do not write the containing register as a scalar. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:441-502` |
| Multi-valued bit field | Named `bitParam` plus `value` | Use `bitParamControl`; do not coerce it to boolean. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:504-562` |

## Authoritative scaling table

| Field family | Raw → engineering conversion | Evidence |
|---|---:|---|
| `vpv1..6`, `vacr/s/t`, `vepsr/s/t`, bank `vBat`, `genVolt`, GridBOSS grid/UPS/gen RMS voltages | divide by **10** | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py:49-59`; OpenAPI `x-scaling`; `portal-correlated` battery capture `vBat=531` and `totalVoltageText="53.1"` |
| `vBus1`, `vBus2` | divide by 100 | `verified-against-code` OpenAPI schema `InverterRuntime` `vBus1`/`vBus2` scaling |
| `fac`, `feps`, `genFreq`, `gridFreq`, `phaseLockFreq` | divide by 100 | `verified-against-code` OpenAPI `x-scaling` and `pylxpweb/src/pylxpweb/constants/scaling.py` |
| `maxChgCurr`, `maxDischgCurr` | divide by 100 | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py` → `INVERTER_RUNTIME_SCALING` |
| GridBOSS/MID grid, UPS and generator RMS currents | divide by 100 | `verified-against-code` OpenAPI schema `MidboxData` |
| GridBOSS/MID **smart-load** RMS currents | divide by **10** | `verified-against-code` OpenAPI schema `MidboxData` |
| Battery-module `totalVoltage` | divide by 100 | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:638-704`; `portal-correlated` capture `5324 -> 53.24 V` |
| Battery-module `current` | divide by **10**, not 100 | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py:190-192`; `models.py:645` |
| Battery-module `batMaxCellVoltage`, `batMinCellVoltage` | divide by 1000 | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:638-704`; `portal-correlated` capture `3332 -> 3.332 V` |
| Battery-module `batMaxCellTemp`, `batMinCellTemp` | divide by 10 | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:638-704`; `portal-correlated` capture `250 -> 25.0 C` |
| Active-power fields beginning with `p` | multiply by 1; values are watts | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py:100-114` |
| `tinner`, `tradiator*`, valid `tBat` | multiply by 1; values are degrees Celsius | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py` → `INVERTER_RUNTIME_SCALING` |
| `soc`, `seps`, `capacityPercent` | multiply by 1; values are percentage points | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py` → runtime/battery scaling maps; Pydantic model types |
| **All energy totals** in `EnergyInfo`, `MidboxData`, and history | divide by **10**; raw unit is 0.1 kWh | `verified-against-code` `pylxpweb/src/pylxpweb/constants/scaling.py:121-166`; OpenAPI energy schemas |

### Captured proof for energy

`pylxpweb/samples/energy.json` contains `todayYielding=5` beside a rendered value of `"0.5"`, and `totalYielding=13597` beside `"1359.7"`. This establishes 0.1 kWh wire units and a divisor of 10; it contradicts the stale “Wh, divide by 1000” endpoint docstring. `portal-correlated` `pylxpweb/samples/energy.json`; `verified-against-code` `pylxpweb/src/pylxpweb/models.py:609-627`; `constants/scaling.py:121-166`

Many payloads provide raw values together with `*Text`, `*TextUnitLess`, or `*Data`/`*Unit` siblings. Use these captured display fields to test a suspected divisor, but use canonical scaling metadata in implementation. `portal-correlated` `pylxpweb/samples/energy.json`, `pylxpweb/samples/battery.json`; `inferred` implementation rule

## `remoteRead/read` is flat and name-keyed

The response from `POST /WManage/web/maintain/remoteRead/read` places parameters directly at the JSON root under descriptive names such as `HOLD_*` and `FUNC_*`. It is **not** nested under `parameters`, and it is **not** keyed by numeric register address. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:92-95,145-157`; `pylxpweb/src/pylxpweb/models.py:1041-1057`

```json
{
  "success": true,
  "inverterSn": "...",
  "deviceType": 6,
  "startRegister": 0,
  "pointNumber": 127,
  "HOLD_DEVICE_TYPE_CODE": 54,
  "FUNC_EPS_EN": true
}
```

The example shows the documented OpenAPI shape only; its illustrative values are not a captured response. `asserted-unverified` (`docs/api/openapi.yaml` path `/WManage/web/maintain/remoteRead/read`)

`ReadParametersResponse` therefore allows extra fields and exposes a computed `.parameters` view over those extras while typing the fixed envelope fields. `verified-against-code` `pylxpweb/src/pylxpweb/models.py:1048-1057`

| Prefix | Meaning | Correct write endpoint | Evidence |
|---|---|---|---|
| `HOLD_*` | Scalar holding value | `remoteSet/write` with `holdParam` and pre-scaled `valueText` | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:164-217`; `constants/registers.py:661-693` |
| `FUNC_*` | One named boolean bit from a bit-field register | `remoteSet/functionControl` with `functionParam` and `enable` | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:441-502` |
| `BIT_*` | Named multi-valued bit field | `remoteSet/bitParamControl` with `bitParam` and `value` | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:504-562` |
| `_12K_HOLD_*` | Off-grid-family named scalar variant | Same scalar endpoint; family-specific name | `verified-against-code` `pylxpweb/src/pylxpweb/constants/registers.py:1138-1152` |
| `LSP_HOLD_*` | Server-side read interpretation used by peak-shaving schedules | Read-only mapping; do not derive a write name from it | `verified-against-code` `pylxpweb/src/pylxpweb/constants/registers.py:121-126`; `endpoints/control.py:1689-1768` |

The server synthesizes `FUNC_LSP_*` interpretations for register 22; they are not proven local Modbus bit fields. Register 22 is locally a scalar PV-start-voltage register, so never port those cloud names into local bit writes. `verified-against-code` `pylxpweb/src/pylxpweb/constants/registers.py:688-693`

## Named-write conversion and rejection rules

The historical cloud raw-write implementation placed a dictionary inside one form field. aiohttp serialized it as an opaque representation, the intended inner values did not reach the portal as parameters, and success-shaped responses could accompany a no-op. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:292-305`

Current `write_parameters()` resolves an address/value mapping into sequential, flat, named writes. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:292-351`

| Stage | Contract | Evidence |
|---|---|---|
| Preflight | Resolve every requested address before the first write so an unsupported member cannot cause an avoidable partial update. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:337-342` |
| Reject | Reject packed-time registers, unmapped addresses, bit-field/multi-name registers, and signed values whose negative portal representation is unverified. Never guess. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:377-418` |
| Scale | Prefer canonical `ScaleFactor`; then explicit name/address divide-by-ten fallbacks; otherwise divisor 1. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:420-439`; `constants/registers.py:1138-1152` |
| Send | Issue one `remoteSet/write` per resolved name, sequentially. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:344-351` |
| Failure | Stop at the first failed write. Earlier successful writes remain applied. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:344-351` |
| Success | Invalidate cached values for that device. Cache invalidation is not hardware readback proof. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:210-219` |

Cloud multi-write is therefore not atomic. `inferred` from the verified sequential stop-on-first-failure behavior

## Partial, unreliable and sentinel-valued fields

Absence and `None` are domain states, not schema noise. A model that requires every online field will reject valid offline payloads and can blank the entire device in Home Assistant. `portal-correlated` issues #256/#479 recorded in `CHANGELOG.md`; `verified-against-code` optional fields in `pylxpweb/src/pylxpweb/models.py`

| Payload / field | Observed behavior | Required handling | Evidence |
|---|---|---|---|
| Offline `getInverterRuntime`: `status`, `ppv`, `soc`, `vBat`, `pCharge`, `pDisCharge`, `batPower`, `batteryColor`, `pinv`, `prec`, `peps` | Fields can be omitted while identity, `statusText="offline"`, some PV/voltage/temperature fields remain. | Make live metrics optional and preserve the partial object; do not reject the whole payload. | `portal-correlated` issue #256; `verified-against-code` `pylxpweb/src/pylxpweb/models.py:458-465` |
| Offline `getBatteryInfo`: `batStatus`, `soc`, `vBat`, `pCharge`, `pDisCharge` | Fields can be omitted. | Keep the response/bank identity and treat metrics as unavailable. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:706-755` |
| Inverter runtime `tBat` sentinel | Apply the canonical value and handling from [the inverter input-register ledger](../40-hardware/registers.md#inverter-input-register-ledger); this page does not duplicate that hardware fact. | Normalize the sentinel to null/unavailable before plausibility checks. | `verified-against-code` `pylxpweb/src/pylxpweb/devices/inverters/_runtime_properties.py` → `battery_temperature`; hardware evidence remains with the linked keeper |
| Battery `capacityPercent=0` | Can be a fake value on 12000XP payloads with no cloud module array while the BMS charge/capacity pair remains live. | Keep raw value primary; only use the proven BMS-pair fallback under the library's guarded condition. | `portal-correlated` issue #514; `CHANGELOG.md:30` |
| MID `lost` | When true, the dongle is offline and cloud data can be a frozen last-register mirror. | Retain and surface the offline signal; do not present frozen metrics as current. | `portal-correlated` issue #479; `verified-against-code` `pylxpweb/src/pylxpweb/models.py:1029-1033` |
| Battery strings `ambientTemp`, `mosTemp`, `chgCapacity`, `disChgCapacity`, `noticeInfo` | Captures use empty string `""` as well as null-like absence. | Model as optional strings; do not parse blindly as numbers. | `portal-correlated` `pylxpweb/samples/battery.json`; `verified-against-code` `models.py:698-703` |
| `batteryArray` | May be absent when no batteries are reported. | Default to an empty list. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:753-754` |
| Parallel energy `serialNum`, `soc` | May be absent from group responses. | Keep optional. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:613,617-618` |
| Viewer `endUser`, `deviceTypeText4APP` | May be absent. | Do not make account/device discovery depend on presence. | `portal-correlated` `docs/api/README.md:468-470` |
| Analytics `attr` and `energyType` | Unknown strings can return success with empty or zero-filled series. | Validate against a proven vocabulary; zero data alone cannot prove the selector was valid. | `portal-correlated` `docs/api/README.md:430-434,475-480`; `inferred` validation rule |
| `chart/dayLine.data[].month` versus `energy/yearColumn.data[].month` | Day-line month is zero-indexed; year-column month is one-indexed. | Normalize per endpoint, never globally. | `portal-correlated` `docs/api/README.md:428-429` |

The failure mode is whole-object amplification: one required-but-omitted live field causes Pydantic validation failure, and downstream consumers lose every otherwise-valid entity from that response. This previously happened for offline inverters until the affected runtime fields became optional. `portal-correlated` issue #256; `inferred` failure-chain description from `models.py:458-465`

## `MidboxData` completeness

The OpenAPI `MidboxData` schema enumerates **108 fields**, and the pylxpweb Pydantic `MidboxData` model has exactly the same 108-field set. `verified-against-code` `docs/api/openapi.yaml:2699-3078`; `pylxpweb/src/pylxpweb/models.py:827-1010`; machine field-set comparison

A captured `midbox_runtime.json` contains **101** of those fields. The schema/model are a superset because inactive or unsupported smart-load, AC-couple, current, and energy families can be omitted. `portal-correlated` `pylxpweb/samples/midbox_runtime.json`; `verified-against-code` OpenAPI `MidboxData` optional properties

All `MidboxData` numeric properties are nullable. For optional port families, zero or null can mean inactive/unavailable rather than a measured physical zero; `null` specifically documents a register-read failure. `verified-against-code` `docs/api/openapi.yaml:2702-2708`; `inferred` do-not-conflate rule

## Verified divergence ledger

This table records source conflicts so an agent does not trust whichever prose it happens to find first. `verified-against-code` each row cites its adjudicating source

| Severity | Conflicting source | Incorrect claim | Adjudicated truth | Evidence |
|---|---|---|---|---|
| **HIGH** | `pylxpweb/endpoints/devices.py:222,233-234` | Energy is Wh divided by 1000; examples use `eInvDay`/`eInvAll`. | Raw energy is **0.1 kWh divided by 10**; actual fields are `todayYielding` and `totalYielding`. | `verified-against-code` `models.py:609-627`; `constants/scaling.py:121-166`; `portal-correlated` `samples/energy.json` |
| **HIGH** | `pylxpweb/endpoints/devices.py:188-192,204` | Runtime voltage is divided by 100; example uses `vacr / 100`. | Runtime PV/AC voltage is divided by **10**; the stale docstring is a 10x error. | `verified-against-code` `constants/scaling.py:49-59`; `models.py:449-450`; OpenAPI runtime `x-scaling` |
| MEDIUM | `CLAUDE.md` API architecture (`asserted-unverified` source claim) | Serial numbers are 10-digit numeric strings. | Values are 10-character strings and may be alphanumeric; code does not validate numeric form. The sanitized format examples are owned by [Identifier rules and traps](./endpoints.md#identifier-rules-and-traps). | `portal-correlated` captured payload shapes documented in `docs/api/README.md`; `verified-against-code` `models.py` serial fields |
| MEDIUM | `CLAUDE.md:155` (`asserted-unverified` source claim) | Battery-info cache is five minutes. | `client.py` uses 60 seconds. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:136` |
| MEDIUM | `PORTAL_ENDPOINTS.md:11` (`asserted-unverified` source claim) | 41 catalog routes map to the validated spec. | The spec has 44 paths; the difference is login, installer-only plant list, and an export placeholder-name mismatch. | `verified-against-code` machine comparison of `docs/api/openapi.yaml` paths with pylxpweb endpoint call sites |
| INFO | `PORTAL_ENDPOINTS.md` versus OpenAPI | Catalog claims 251 discovered portal routes; the spec deliberately covers only the 44 pylxpweb-called paths. | Treat the catalog as a discovery map and the OpenAPI as the call-site contract. | Catalog count `asserted-unverified` `docs/api/PORTAL_ENDPOINTS.md:9-12`; spec scope `verified-against-code` `docs/api/openapi.yaml:7-13` |
| LOW | Sample versus schema/model | `MidboxData` “has 108 fields” could imply every response has all 108. | Spec and model match at 108, but one capture has 101 because optional families can be absent. | `verified-against-code` OpenAPI/model field comparison; `portal-correlated` `samples/midbox_runtime.json` |
| LOW | `pylxpweb/endpoints/devices.py:345,355-357` | MID voltage/current/frequency uniformly divide by 100; examples use `gridPower`, `loadPower`, `genPower`. | Voltage divides by 10, most current/frequency by 100, and real names are per-leg fields such as `gridL1ActivePower`. | `verified-against-code` OpenAPI schema `MidboxData` |
| LOW | `pylxpweb/endpoints/devices.py:280,293` | Battery example uses `module.vBat / 100`. | `BatteryModule` has `totalVoltage / 100`; it has no `vBat` field. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:638-704` |
| LOW | Client state declaration | `_session_id` appears to hold session identity. | It is never assigned; authentication lives in the aiohttp cookie jar. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:107-119,818-835` |
| LOW | OpenAPI-only view | Every relevant repository route appears in the 44 paths. | Four routes are referenced but never called (two weekly APIs, two HTML pages), two script-used firmware-download APIs are omitted, and one documented route uses another host. | `verified-against-code` repository string inventory; operational availability `asserted-unverified` with durable sources in [Seven referenced routes outside the OpenAPI spec](./endpoints.md#seven-referenced-routes-outside-the-openapi-spec) |
| LOW | `locale/region` and `locale/country` placement | Presence in endpoint modules suggests normal client behavior. | They bypass `_request()`, hence lack its cache, backoff, reauth and application-error behavior. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/plants.py:150-221` |
| LOW | Quick charge/discharge symmetry | Start/stop cache behavior appears parallel. | Quick-charge start/stop invalidates its cache; quick-discharge start/stop does not. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:612-648,702-733` |
| LOW | `CLAUDE.md` cache-boundary wording (`asserted-unverified` source claim) | Cache is cleared before the hour boundary. | The first request **after** the local hour changes clears it. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:580-591` |

When scaling sources disagree, prefer canonical constants, Pydantic field names, OpenAPI `x-scaling`, locked tests, and captured raw/display pairs over endpoint docstrings. `inferred` priority derived from the HIGH divergences and their adjudicating evidence
