---
canonical-for:
  - "Vocabulary used across llmwiki and the codebase"
sources:
  - custom_components/eg4_web_monitor/const/config_keys.py
  - custom_components/eg4_web_monitor/base_entity.py
  - /Users/bryanli/Projects/joyfulhouse/python/pylxpweb/src/pylxpweb/devices/inverters/_features.py
  - /Users/bryanli/Projects/joyfulhouse/python/pylxpweb/src/pylxpweb/transports/data.py
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - what-this-project-is.md
  - repo-map.md
---

# Glossary

Definitions only. Behaviour belongs to the owning page.

> pylxpweb citations are against the local checkout of `joyfulhouse/pylxpweb` as of
> 2026-08-08, not a released tag.

## Topology

| Term | Meaning | Evidence |
|---|---|---|
| **Plant** / **Station** | The vendor's site-level container, keyed by `plantId`. One HA config entry per station. Station-scoped entities use unique-ID `station_{plant_id}_{sensor_key}`. | `verified-against-code` (`sensor.py:829`) |
| **Parallel group** | A set of inverters wired and configured to operate together, with a designated master. Some values (per-inverter consumption on the master) legitimately read 0; some writes (register 179 regime bits) propagate to every member by firmware sync. | `asserted-unverified` (corpus §2.1, §2.5; `battery-control-mode-soc-vs-voltage.md`) |
| **MID** / **GridBOSS** | EG4's mid-point interconnection device. Grid/UPS/load/smart-port management, no batteries of its own. Portal endpoints and payloads call it `midbox`; the product name is GridBOSS. | `verified-against-code` (`midbox` appears in `coordinator_mappings.py`, `sensor.py`, `services.py`, `utils.py`) |
| **Smart port** | A GridBOSS load/AC-couple/generator port. Port mode is bit-packed into a holding register, 2 bits per port. | `asserted-unverified` (corpus §1.4 / `GRIDBOSS_REGISTER_MAP.md`; owned by `40-hardware/gridboss.md`) |
| **Dongle** | The EG4 WiFi dongle. Doubles as the local Modbus-over-TCP endpoint (`CONNECTION_TYPE_DONGLE`) and as the device that pushes data to the EG4 cloud. | `verified-against-code` (`const/config_keys.py` → `CONNECTION_TYPE_DONGLE`, `HYBRID_LOCAL_DONGLE`) |
| **batteryKey** | The portal's identifier for an individual battery within a bank; used in the battery unique-ID `{serial}_{battery_key}_{sensor_key}` and carried as `battery_key` through the entity layer. | `verified-against-code` (`base_entity.py:565`; `battery_key` ctor arg on `EG4BatteryEntity`) |
| **Battery bank** | The aggregate of a serial's batteries. Has its own entity scope (`{serial}_battery_bank_{sensor_key}`) with **different availability semantics** from device sensors. | `verified-against-code` (`base_entity.py:660`) |

## Connectivity

| Term | Meaning | Evidence |
|---|---|---|
| **LOCAL** | Mode with no cloud credentials — Modbus TCP, RS485, or WiFi dongle only. Constant `CONNECTION_TYPE_LOCAL = "local"`. | `verified-against-code` (`const/config_keys.py:113`) |
| **CLOUD** / **HTTP** | Portal-only mode. The constant is `CONNECTION_TYPE_HTTP = "http"`; prose and issue reports say "cloud". Treat the two words as the same mode. | `verified-against-code` (`const/config_keys.py:109`) |
| **HYBRID** | Local transport for runtime data plus cloud for supplemental data. `CONNECTION_TYPE_HYBRID = "hybrid"`. | `verified-against-code` (`const/config_keys.py:112`) |
| **Transport** | A local data path object in pylxpweb (Modbus TCP / serial / dongle) plus its decoded dataclasses. The integration reads these dataclasses directly. | `asserted-unverified` (corpus §2.13; corroborated by `_TRANSPORT_OVERLAY` in `coordinator_mixins.py`) |
| **Transport-exclusive** | A value only the local transport can supply, overlaid onto cloud data when a local transport is attached (`_TRANSPORT_OVERLAY`). Fault/warning codes are the canonical example — the cloud has no such field. | `verified-against-code` for the mechanism (`coordinator_mixins.py:446`); `asserted-unverified` for the member list (corpus §2.1) |

## Registers and parameters

| Term | Meaning | Evidence |
|---|---|---|
| **Input register** | Read-only measurement register (Modbus FC04). Runtime values. | `asserted-unverified` (corpus §2.10; standard Modbus) |
| **Holding register** | Read/write configuration register (`HOLD_*`). Controls and setpoints. | `asserted-unverified` (corpus §2.12) |
| **`HOLD_*`** | pylxpweb's canonical name for a holding-register parameter, e.g. `HOLD_AC_CHARGE_POWER_CMD`. The same names are used by the portal's named-write API. | `verified-against-code` (pylxpweb `constants/__init__.py`) |
| **`FUNC_*`** | A named **bit** inside a function bitmap register (registers 21, 110, 179), e.g. `FUNC_EN_BIT_EPS_EN`. | `verified-against-code` (pylxpweb `constants/registers.py`) |
| **Placeholder key** | A synthetic `FUNC_<reg>_BIT<n>` name for an unidentified bit. These were once reachable by named write, meaning a write could read-modify-write an unknown bit; they are decode-only now. | `asserted-unverified` (corpus §2.12) |
| **Named parameter** | A read or write addressed by `HOLD_*`/`FUNC_*` name rather than raw register number. Cloud named writes take **engineering units**; local writes take raw register units. | `asserted-unverified` (corpus §2.5, §2.12) |
| **Delta test** | Write → read back → restore, comparing raw before/after values. The only procedure that proves a name maps to a register or that a bit does what it is labelled. A successful write proves format acceptance, not targeting. | `asserted-unverified` (corpus §2.12) |
| **Device type code** | The numeric model identifier read from the device; the input to family classification. Defects can split *within* one code — do not treat a code as a capability. | `verified-against-code` (pylxpweb `_features.py` docstring: "determined by the `HOLD_DEVICE_TYPE_CODE` register value") |
| **Family** | `InverterFamily`: `EG4_OFFGRID` (12000XP, 6000XP), `EG4_HYBRID` (18kPV, 12kPV, FlexBOSS21/18), `LXP` (Luxpower), `UNKNOWN`. Deprecated aliases `SNA`, `PV_SERIES`, `LXP_EU`, `LXP_LV` still resolve. Capability gates key on family, never on model strings. | `verified-against-code` (pylxpweb `devices/inverters/_features.py`) |
| **Fail-closed gate** | A family gate that treats `UNKNOWN` as unresolved rather than as "not X", so entities are created late once the family resolves rather than being wrongly suppressed. | `asserted-unverified` (corpus §2.6) |

## Data handling

| Term | Meaning | Evidence |
|---|---|---|
| **Canary** | A validity predicate in pylxpweb that rejects an implausible payload — SoC > 100, frequency outside 30–90 Hz, battery count > 20, \|current\| > 500 A. Implemented as `is_corrupt()` on transport data classes. Rejecting a payload blanks a whole device, so a canary that is too tight is itself an outage (issue #348). | `verified-against-code` for the mechanism (pylxpweb `transports/data.py` → `is_corrupt`); `asserted-unverified` for the specific thresholds (corpus §2.4 / `data-validation-architecture.md`) |
| **Carry-forward** | Keeping a previously published value or entity in the coordinator's data when the current poll omits it, so that a transient gap does not delete an entity. Implemented for batteries as `_apply_battery_carry_forward`. Staleness is then expressed **as data** (`battery_last_seen`), not as availability. | `verified-against-code` for the symbol (`coordinator_http.py:598`); `asserted-unverified` for the policy (corpus §2.4) |
| **Eviction bound** | The counterpart to carry-forward: a time limit after which a carried entry is dropped, so a physically removed device converges without an HA restart. Every never-evict rule needs one. | `asserted-unverified` (corpus §2.4, issue #300) |
| **Seed** | Writing a just-written value into the parameter cache so the entity does not display a stale read. Must live outside data that is replaced each cycle, and may only be superseded when a read observes a concrete value for that field. | `asserted-unverified` (corpus §2.7) |
| **Rotation** | Firmware behaviour where a device exposes different battery packs in the same four Modbus slots across successive reads. Firmware-dependent; some units never rotate. Accumulate by serial, never by slot position. | `asserted-unverified` (corpus §2.10) |
| **Fake-confident zero** | A structurally valid `0` the cloud returns for a field it cannot compute (internal temperature, capacity percent, known-state flags). Detected by contradiction with a live sibling value, then blanked or derived — never trusted. | `asserted-unverified` (corpus §2.11) |
| **`lost`** | A portal response flag meaning the device is offline and the payload is the last register mirror. The response still says `success: true`, so freshness must be gated on this flag. | `asserted-unverified` (corpus §2.4, issue #479) |
| **unknown vs unavailable** | Two distinct HA entity states with different causes here: a missing key yields `unknown` on a device sensor and `unavailable` on a battery-bank entity, because the two base classes implement `available` differently. Never gate data by dropping keys. Owned by `10-integration/`. | `asserted-unverified` (corpus §2.3) |

## Process

| Term | Meaning | Evidence |
|---|---|---|
| **Repairs** | Home Assistant's user-facing issue mechanism, used here to announce one-shot removals or family-gated changes. | `asserted-unverified` (corpus §3, issues #331/#544) |
| **Mode parity sweep** | Validation that compares entity registries across cloud/local/hybrid. Compare **registries by unique_id**, not states — a states comparison produces dozens of false "missing" entries from slug drift and enablement differences. | `asserted-unverified` (corpus §2.1) |
| **Contract harness** | A test derived from the register table asserting that each cloud field and Modbus path yield the same *physical value*. It is not independent evidence: it resolves against the same pylxpweb tables, so it catches internal drift but cannot prove an address is correct on hardware. | `asserted-unverified` (corpus §2.12, §2.13) |
