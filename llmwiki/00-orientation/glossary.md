---
canonical-for:
  - "Vocabulary used across llmwiki and the codebase"
sources:
  - custom_components/eg4_web_monitor/const/config_keys.py
  - custom_components/eg4_web_monitor/base_entity.py
  - pylxpweb src/pylxpweb/devices/inverters/_features.py
  - pylxpweb src/pylxpweb/transports/data.py
  - llmwiki/README.md
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-08
see-also:
  - what-this-project-is.md
  - repo-map.md
---

# Glossary

Definitions only. Behaviour belongs to the owning page.

> Every pylxpweb symbol cited below was re-checked at `204b95d` — the commit that
> `refs/tags/v0.9.39b10` resolves to in both the local clone and `origin` — not at a
> working copy.

## Topology

| Term | Meaning | Evidence |
|---|---|---|
| **Plant** / **Station** | The vendor's site-level container, keyed by `plantId`. One HA config entry per station; station-scoped entities are keyed by plant id (forms owned by [`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md)). | `verified-against-code` (`sensor.py` → `plant_id` in the station sensor's unique ID) |
| **Parallel group** | A set of inverters wired and configured to operate together, with a designated master. Some values (per-inverter consumption on the master) legitimately read 0; some writes (register 179 regime bits) propagate to every member by firmware sync. | `asserted-unverified` (`memory/battery-control-mode-soc-vs-voltage.md`; `memory/consumption-energy-sources.md`) |
| **MID** / **GridBOSS** | EG4's mid-point interconnection device. Grid/UPS/load/smart-port management, no batteries of its own. Portal endpoints and payloads call it `midbox`; the product name is GridBOSS. | `verified-against-code` (`midbox` appears in `coordinator_mappings.py`, `sensor.py`, `services.py`, `utils.py`) |
| **Smart port** | A GridBOSS load/AC-couple/generator port. Port mode is bit-packed into a holding register. The register, the packing, and its evidence grade are owned by [`40-hardware/gridboss.md`](../40-hardware/gridboss.md). | — (definition only; the register claim is graded by its owner) |
| **Dongle** | The EG4 WiFi dongle. Doubles as the local Modbus-over-TCP endpoint (`CONNECTION_TYPE_DONGLE`) and as the device that pushes data to the EG4 cloud. | `verified-against-code` (`const/config_keys.py` → `CONNECTION_TYPE_DONGLE`, `HYBRID_LOCAL_DONGLE`) |
| **batteryKey** | The portal's identifier for an individual battery within a bank; carried as `battery_key` through the entity layer and used to key battery entities. | `verified-against-code` (`base_entity.py` → `battery_key` ctor arg on `EG4BatteryEntity`) |
| **Battery bank** | The aggregate of a serial's batteries. Has its own entity scope with **different availability semantics** from device sensors — see [`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md). | `verified-against-code` (`base_entity.py` → `EG4BatteryBankEntity`) |

## Connectivity

| Term | Meaning | Evidence |
|---|---|---|
| **LOCAL** | Mode with no cloud credentials — Modbus TCP, RS485, or WiFi dongle only. Constant `CONNECTION_TYPE_LOCAL = "local"`. | `verified-against-code` (`const/config_keys.py` → `CONNECTION_TYPE_LOCAL`) |
| **CLOUD** / **HTTP** | Portal-only mode. The constant is `CONNECTION_TYPE_HTTP = "http"`; prose and issue reports say "cloud". Treat the two words as the same mode. | `verified-against-code` (`const/config_keys.py` → `CONNECTION_TYPE_HTTP`) |
| **HYBRID** | Local transport for runtime data plus cloud for supplemental data. `CONNECTION_TYPE_HYBRID = "hybrid"`. | `verified-against-code` (`const/config_keys.py` → `CONNECTION_TYPE_HYBRID`) |
| **Transport** | A local data path object in pylxpweb (Modbus TCP / serial / dongle) plus its decoded dataclasses. The integration reads these dataclasses directly. | `asserted-unverified` (`docs/claude/MAINTAINABILITY_FINDINGS.md`; corroborated by `_TRANSPORT_OVERLAY` in `coordinator_mixins.py`) |
| **Transport-exclusive** | A value only the local transport can supply, overlaid onto cloud data when a local transport is attached. Fault/warning codes are the canonical example — the cloud has no such field. | `verified-against-code` for the mechanism (`coordinator_mixins.py` → `_TRANSPORT_OVERLAY`); `asserted-unverified` for the member list (`memory/architecture-patterns.md`) |

## Registers and parameters

| Term | Meaning | Evidence |
|---|---|---|
| **Input register** | Read-only measurement register (Modbus FC04). Runtime values. | `asserted-unverified` (`docs/reference/MODBUS_DOCS.md`) |
| **Holding register** | Read/write configuration register (`HOLD_*`). Controls and setpoints. | `asserted-unverified` (`docs/reference/MODBUS_DOCS.md`) |
| **`HOLD_*`** | pylxpweb's canonical name for a holding-register parameter, e.g. `HOLD_AC_CHARGE_POWER_CMD`. The same names are used by the portal's named-write API. | `verified-against-code` (pylxpweb `constants/__init__.py`) |
| **`FUNC_*`** | A named **bit** inside a function bitmap register (registers 21, 110, 179), e.g. `FUNC_EN_BIT_EPS_EN`. | `verified-against-code` (pylxpweb `constants/registers.py`) |
| **Placeholder key** | A synthetic `FUNC_<reg>_BIT<n>` name for an unidentified bit. These were once reachable by named write, meaning a write could read-modify-write an unknown bit; local named writes to them are now refused by name pattern, so they are decode-only. **The guard keys on the name, not on the evidence** — a bit that carries a *real* name but an unpinned position is not covered by it, which is exactly how H179 b11 ships a local write (see **Semantic proof** above). The companion denylist for named-but-disputed parameters, `DISPUTED_WRITE_BLOCKED_PARAMS`, is empty by design: a name belongs there only while a dispute is live. Both guards are LOCAL-only on purpose — the cloud `functionControl` endpoint writes by name and EG4's server resolves the bit, so only the local path, where we compute the position ourselves, can land on the wrong bit. | `verified-against-code` (pylxpweb `constants/registers.py` → the placeholder name-pattern refusal and `DISPUTED_WRITE_BLOCKED_PARAMS`); origin of the hazard: issue #476, `memory/issue-476-green-mode-bit14.md` |
| **Named parameter** | A read or write addressed by `HOLD_*`/`FUNC_*` name rather than raw register number. Cloud named writes take **engineering units**; local writes take raw register units. | `asserted-unverified` (`memory/cloud-raw-register-write-broken.md`; `memory/voltage-param-scaling-cloud-vs-local.md`) |
| **Delta test** | Write → read back → restore, comparing raw before/after values. It proves **storage and transport**: that a named write reaches the register it claims to. **It does not prove semantics.** A wrong-but-writable bit is firmware-ACKed and reads back exactly as written while the function it is labelled with never moves — that is how register 110 bit 8 was marked verified and shipped wrong (issue #476). | `asserted-unverified` (`memory/cloud-raw-register-write-broken.md`) |
| **Semantic proof** (of a bit or register meaning) | The standard that a delta test does *not* meet. All four are required: (1) a named vendor or UI action on the target family, (2) an **independent observation that the intended physical state actually changed** — a second sensor, a breaker test, a portal widget that reflects the real mode — (3) a complete raw before/after delta on the register, and (4) restoration of the original value. Anything less leaves the semantic **unproven**. An unproven bit **must** then be treated as write-inaccessible — no entity, no named-write path, no placeholder key a write helper can reach. **That is the required safety policy. It is not a description of this codebase, and it is not enforced today:** H179 b11 (AC Couple) and H161 (AC Charge End Battery SOC on `EG4_OFFGRID`) both ship production entities whose LOCAL and HYBRID writes go **local-first with cloud fallback**, on mappings nothing has pinned. Those are live, un-discharged risks — issue **#558** and [contradiction C7](../60-history/open-contradictions.md). **Never infer from a weak grade that a write path is closed; check the entity.** Which grade the evidence earns is the legend's call, never this entry's. Full ladder in [README](../README.md#the-register-annotation-ladder); per-bit status in [`40-hardware/registers.md`](../40-hardware/registers.md). | `asserted-unverified` for the standard (issue #476; `memory/issue-476-green-mode-bit14.md`); `verified-against-code` for the two shipped violations (`switch.py`, `number.py` → `ACChargeEndBatterySOCNumber`, both via `utils.py` → `async_write_with_cloud_fallback`) |
| **Device type code** | The numeric model identifier read from the device; the input to family classification. Defects can split *within* one code — do not treat a code as a capability. | `verified-against-code` (pylxpweb `devices/inverters/_features.py` → `InverterFeatures.from_device_type_code`) |
| **Family** | `InverterFamily`: `EG4_OFFGRID` (12000XP, 6000XP), `EG4_HYBRID` (18kPV, 12kPV, FlexBOSS21/18), `LXP` (Luxpower), `UNKNOWN`. Deprecated aliases `SNA`, `PV_SERIES`, `LXP_EU`, `LXP_LV` still resolve. Capability gates key on family, never on model strings. | `verified-against-code` (pylxpweb `devices/inverters/_features.py`) |
| **Fail-closed gate** | A family gate that treats `UNKNOWN` as unresolved rather than as "not X", so entities are created late once the family resolves rather than being wrongly suppressed. | `asserted-unverified` (`memory/issue-544-generator-power-offgrid.md`) |

## Data handling

| Term | Meaning | Evidence |
|---|---|---|
| **Canary** | A validity predicate in pylxpweb that rejects an implausible payload, implemented as `is_corrupt()` on the transport data classes. Rejecting a payload blanks a whole device, so a canary that is too tight is itself an outage (issue #348), and a fixed threshold that does not scale with the installation is itself a bug (issue #367). **Current thresholds are owned by [`10-integration/data-semantics.md`](../10-integration/data-semantics.md)** — do not quote numbers from anywhere else; several published figures are superseded. | `verified-against-code` for the mechanism (pylxpweb `transports/data.py` → `is_corrupt`) |
| **Carry-forward** | Keeping a previously published value or entity in the coordinator's data when the current poll omits it, so that a transient gap does not delete an entity. Implemented for batteries as `_apply_battery_carry_forward`. Staleness is then expressed **as data** (`battery_last_seen`), not as availability. | `verified-against-code` for the symbol (`coordinator_http.py` → `_apply_battery_carry_forward`); `asserted-unverified` for the policy (`memory/issue-258-beta18-carry-forward.md`) |
| **Eviction bound** | The counterpart to carry-forward: a time limit after which a carried entry is dropped, so a physically removed device converges without an HA restart. Every never-evict rule needs one. | `asserted-unverified` (issue #300) |
| **Seed** | Writing a just-written value into the parameter cache so the entity does not display a stale read. Must live outside data that is replaced each cycle, and may only be superseded when a read observes a concrete value for that field. | `asserted-unverified` (`memory/issue-471-ac-couple-switch.md`) |
| **Rotation** | Firmware behaviour where a device exposes different battery packs in the same four Modbus slots across successive reads. Firmware-dependent; some units never rotate. Accumulate by serial, never by slot position. | `asserted-unverified` (`memory/issue-258-battery-rr-reg96-unreliable.md`) |
| **Fake-confident zero** | A structurally valid `0` the cloud returns for a field it cannot compute (internal temperature, capacity percent, known-state flags). Detected by contradiction with a live sibling value, then blanked or derived — never trusted. | `asserted-unverified` (issues #490, #497, #514; `memory/issue-514-capacity-percent-fake-zero.md`) |
| **`lost`** | A portal response flag meaning the device is offline and the payload is the last register mirror. The response still says `success: true`, so freshness must be gated on this flag. | `asserted-unverified` (issue #479; `memory/issue-479-cloud-lost-freeze.md`) |
| **unknown vs unavailable** | Two distinct HA entity states with different causes here: a missing key yields `unknown` on a device sensor and `unavailable` on a battery-bank entity, because the two base classes implement `available` differently. Never gate data by dropping keys. Owned by [`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md). | `asserted-unverified` (`memory/issue-261-hybrid-sensor-flicker.md`) |

## Process

| Term | Meaning | Evidence |
|---|---|---|
| **Repairs** | Home Assistant's user-facing issue mechanism, used here to announce one-shot removals or family-gated changes. | `asserted-unverified` (issues #331, #544) |
| **Mode parity sweep** | Validation that compares entity registries across cloud/local/hybrid. Compare **registries by unique_id**, not states — a states comparison produces dozens of false "missing" entries from slug drift and enablement differences. | `asserted-unverified` (`memory/release-3.4.0-beta.18-status.md`) |
| **Contract harness** | A test derived from the register table asserting that each cloud field and Modbus path yield the same *physical value*. It is not independent evidence: it resolves against the same pylxpweb tables, so it catches internal drift but cannot prove an address is correct on hardware. | `asserted-unverified` (`docs/claude/MAINTAINABILITY_FINDINGS.md`) |
