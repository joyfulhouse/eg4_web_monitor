---
canonical-for: pylxpweb portal models, local normalized data, missing values, enums, and scaling
sources:
  - pylxpweb@204b95d:src/pylxpweb/models.py
  - pylxpweb@204b95d:src/pylxpweb/endpoints/devices.py
  - pylxpweb@204b95d:src/pylxpweb/registers/
  - pylxpweb@204b95d:src/pylxpweb/transports/
  - pylxpweb@204b95d:tests/unit/test_models.py
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Models and scaling

Evidence grades follow the [canonical llmwiki legend](../README.md).

## Non-negotiable missing-data rule

> Missing telemetry is `None`, **not zero**. Never manufacture `0` from an absent register, an absent half of a 32-bit value, or an optional offline portal field. `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:54-70`, `src/pylxpweb/transports/_canonical_reader.py:130-148`, `src/pylxpweb/transports/data.py:125-142`.

| Input condition | Correct representation | Evidence |
|---|---|---|
| Register absent | `None` | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:54-70` |
| Either half of a 32-bit pair absent | `None` for the whole value | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:54-70` |
| Scaling receives `None` | Preserve `None`; do not create zero | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:130-148` |
| Temperature raw value exactly `127` / `0x7F` | `None` meaning sensor absent | `verified-against-code` — `src/pylxpweb/transports/data.py:62-70`, `src/pylxpweb/transports/data.py:318-321` |
| Other extreme temperature | Preserve it so corruption validation can inspect it | `verified-against-code` — `src/pylxpweb/transports/data.py:62-70`, `src/pylxpweb/transports/data.py:1417-1428` |
| Present individual battery block | `BatteryData` is a documented exception: several child fields use zero/empty defaults | `verified-against-code` — `src/pylxpweb/transports/data.py:973-1035`, `src/pylxpweb/transports/data.py:1250-1339` |

Do not generalize the `BatteryData` exception to inverter runtime, aggregate energy, battery-bank, or MID/GridBOSS telemetry. `verified-against-code` — `src/pylxpweb/transports/data.py:144-790`, `src/pylxpweb/transports/data.py:1343-1385`, `src/pylxpweb/transports/data.py:1773-1829`.

## Portal Pydantic models and optionality

Portal responses are Pydantic models that preserve portal field spelling. Compatibility is targeted: known partial fields are optional/defaulted, while core identity/schema errors remain strict. `verified-against-code` — `src/pylxpweb/models.py:1-5`, `src/pylxpweb/models.py:1041-1076`.

| Model/family | Optionality contract | Evidence |
|---|---|---|
| `UserVisitRecord` | Only `plantId` and `serialNum` are required; device-specific values may be absent for parallel-group visits. | `verified-against-code` — `src/pylxpweb/models.py:112-139`, `tests/unit/test_models.py:120-161` |
| Parallel overview rows | Normal inverter metrics are optional because GridBOSS rows do not carry them. | `verified-against-code` — `src/pylxpweb/models.py:339-381` |
| `InverterRuntime` | Offline responses may omit status, aggregate PV, SOC, battery voltage/power/color, and inverter/rectifier/EPS power; those fields default to `None`. | `verified-against-code` — `src/pylxpweb/models.py:443-465`, `src/pylxpweb/models.py:501-543`, `tests/samples/runtime_offline.json:1-74` |
| `EnergyInfo` | Daily/lifetime energy and success remain required; `serialNum` and `soc` are optional because parallel-group responses omit them. | `verified-against-code` — `src/pylxpweb/models.py:606-632` |
| `BatteryInfo` | Only success and inverter serial are required; aggregate runtime values are optional/defaulted and `batteryArray` defaults empty. | `verified-against-code` — `src/pylxpweb/models.py:706-755`, `tests/unit/test_models.py:304-322` |
| `MidboxData` | Original core keys may be required-but-null; newer smart-load, AC-couple, current, and energy families default to `None`. | `verified-against-code` — `src/pylxpweb/models.py:827-1009` |
| `MidboxRuntime` | Success, serial, firmware, and `midbox` data are required; `lost` and primary-inverter `deviceData` are optional. | `verified-against-code` — `src/pylxpweb/models.py:1023-1035` |
| Dynamic parameter reads | This is the sole general `extra="allow"` response because parameter names arrive dynamically. | `verified-against-code` — `src/pylxpweb/models.py:1041-1076` |

The portal models deliberately accept partial inverter-runtime, battery, and MID/GridBOSS payloads; omitted telemetry must remain optional rather than being synthesized. `verified-against-code` — `src/pylxpweb/models.py:458-465`, `src/pylxpweb/models.py:706-755`, `src/pylxpweb/models.py:827-1035`.

The offline-tolerance fix commit records that making these fields required caused whole-response validation to fail and blanked every related Home Assistant entity in production; it does not include a production trace. `asserted-unverified` — `pylxpweb commit 36a3e298f0590447a7c58f3b422b953e39f1395d`.

## Enums

| Rule | Evidence |
|---|---|
| `UpdateStatus._missing_` maps unknown values to `UpdateStatus.UNKNOWN`. | `verified-against-code` — `src/pylxpweb/models.py:1167-1182` |
| `UpdateEligibilityMessage._missing_` maps unknown values to `UNKNOWN`, and that value is not allowed. | `verified-against-code` — `src/pylxpweb/models.py:1185-1201` |
| These are the only source enums with `_missing_`; all other enums are strict. Never assume a universal unknown fallback. | `verified-against-code` — `src/pylxpweb/models.py:16-1880` |

## Canonical decoding and scaling

| Rule | Evidence |
|---|---|
| Canonical input scale divisors are 1, 10, 100, and 1000. | `verified-against-code` — `src/pylxpweb/registers/inverter_input.py:77-84` |
| 32-bit inverter values are low-word first: `(high << 16) | low`. | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:34-70` |
| Packed bytes are extracted before signed conversion; signed 16/32-bit values use two's-complement subtraction. | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:34-86` |
| Canonical names are stable register identities and may differ from normalized dataclass field names; explicit mappings bridge them. | `verified-against-code` — `src/pylxpweb/transports/_field_mappings.py:1-8`, `src/pylxpweb/transports/_field_mappings.py:17-340` |
| Raw SOC/SOH is retained before public clamping so corruption checks still see out-of-range hardware values. | `verified-against-code` — `src/pylxpweb/transports/_canonical_reader.py:196-206`, `src/pylxpweb/transports/data.py:339-358` |

## Separate register tables: a real maintenance trap

| Table | Used for | Does **not** update | Evidence |
|---|---|---|---|
| Canonical `INVERTER_HOLDING_REGISTERS` and indexes in `registers/inverter_holding.py` | Stable canonical/API/entity identity, width, scale, signedness, bounds, writability, family, and bit metadata | Operational local named reads/writes | `verified-against-code` — `src/pylxpweb/registers/inverter_holding.py:50-106`, `src/pylxpweb/registers/inverter_holding.py:1818-1881` |
| Operational `REGISTER_TO_PARAM_KEYS`, aliases, compound layouts, and scale sets in `constants/registers.py` | `BaseTransport.read_named_parameters` and `write_named_parameters` resolution/RMW | Canonical register definitions and indexes | `verified-against-code` — `src/pylxpweb/transports/protocol.py:376-420`, `src/pylxpweb/constants/registers.py:661-693` |

Changing one table does **not** change the other. A new canonical holding row alone does not make a name locally readable or writable; an operational mapping alone does not create canonical metadata. Update both deliberately when both seams are intended. `verified-against-code` — `src/pylxpweb/transports/protocol.py:376-420`, `src/pylxpweb/registers/inverter_holding.py:1818-1881`.

Never infer local bit order from portal list order. Ordinary operational bitfields use list index as bit number, while explicit compound layouts override that rule. `verified-against-code` — `src/pylxpweb/constants/registers.py:1049-1119`, `src/pylxpweb/transports/protocol.py:591-626`.

## Schema-divergence ownership

`src/pylxpweb/endpoints/devices.py` is the current device-endpoint module. `verified-against-code` — `src/pylxpweb/endpoints/devices.py:1-532`.

Known endpoint-docstring, model-field, and scaling divergences are canonical in the [portal schema-and-scaling ledger](../30-portal-api/schemas-and-scaling.md); do not duplicate that ledger here.
