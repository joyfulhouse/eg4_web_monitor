---
canonical-for: evidence-needed-to-resolve-open-hardware-and-firmware-questions
sources:
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md
  - docs/reference/firmware/OFFGRID_EPS_REGISTERS.md
  - docs/reference/firmware/HYBRID_EPS_REGISTERS.md
  - docs/DATA_MAPPING.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Open hardware and firmware questions

This page owns only unanswered questions and the evidence needed to close them. [registers.md](registers.md#must-not-regress-register-claims) owns every refuted or must-not-regress register claim; [the contradictions ledger](../60-history/open-contradictions.md) owns cross-chapter conflicts. Unknowns remain family-scoped, gated, or unexposed.

## Required unresolved list

| Open question | Current boundary and durable basis | Current grade | Evidence that would settle it |
|---|---|---|---|
| What is the exact OTA per-record checksum/key algorithm, and what bytes/variant does the final integrity field cover? | Record position and model dependence are established, but the algorithm is not. [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) and [firmware-re.md](firmware-re.md#checksum-status). | `asserted-unverified` | Parse multiple captures by actual record boundaries. Compare equal-payload blocks across model keys, then exhaustively test explicit coverage, byte order, polynomial, init, xor-out, reflection, and key-derivation hypotheses against every normal and final record. |
| Do concrete 6000XP and 12kPV images validate under the corrected method? | Portal family membership is not a decoded-image result; no reviewed concrete image exists for either target. [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md). | `asserted-unverified` | Retrieve portal `appLocalUpdate` images; retain metadata/hash; validate ARM vector/load base or C28x MSB-first entry, opcode population, and in-image call targets; publish the exact family/version boundary. |
| Is H110 b14 Green/Off-Grid Mode on 12000XP and 6000XP? | The current family-scoped grade is in [the H110 map](registers.md#h110-safe-bit-map); off-grid portability is unresolved. Issue #476 is the durable 18kPV observation. | `lineage-inferred` | On each family and recorded component firmware, perform one authorized named toggle, capture the complete H110 raw before/after word and XOR, verify intended behavior, restore the original word, and pass the production health check. |
| What are the still-unknown H110 bits? | The register page is the sole owner of accepted, unknown, and refuted positions. [H110 map](registers.md#h110-safe-bit-map); [register audit](../../docs/audits/2026-08-02-register-race-performance-audit.md). | `asserted-unverified` | For one named setting at a time, capture family/firmware/action/full-word before/after/behavior/restore. Never assign a name from proximity or an ACK. |
| What are the still-unknown H179 bits? | See the sole current status in the [H179 map](registers.md#h179-safe-bit-map) and the [register audit](../../docs/audits/2026-08-02-register-race-performance-audit.md). | `asserted-unverified` | Capture one named setting’s full H179 delta, behavior, and clean restore on each applicable family; identify the exact portal parameter. |
| What are the still-unknown H233 bits, and which families implement them? | See the [H233 map](registers.md#h233-safe-bit-map); LOCAL rejection and applicability remain family-dependent. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md). | `asserted-unverified` | Capture one named action per bit with the complete proof tuple, explicitly test family rejection, and preserve atomic read-modify-write around the shared word. |
| Where is genuine off-grid generator power? | The known exclusions and family split are in [registers.md](registers.md#must-not-regress-register-claims); I17 and I27 are only candidates. [`OFFGRID_GENERATOR_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md). | `asserted-unverified` | During an authorized generator start/load/stop sequence, capture complete raw FC04 blocks, portal generator/load flows, voltage/frequency, and an independent signed real-power meter; then trace the matching producer to FC04. |
| What do individual off-grid I124-I126 bits mean? | Word structure and known-written positions do not establish user-facing meanings. [`OFFGRID_GENERATOR_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md). | `asserted-unverified` | Correlate one device-state transition at a time with raw words, then trace the controlling condition for each writer in a validated image. Do not name bits from position alone. |
| What unit does I210 use on each supporting firmware? | The present seconds annotation conflicts with other source material. [`register audit`](../../docs/audits/2026-08-02-register-race-performance-audit.md). | `lineage-inferred` | Start a known-duration quick-charge session; sample raw I210 and wall clock at fixed cadence through zero on the same firmware; repeat after idle/reboot. |
| Is I153 signed for reverse AC-couple flow? | The role is traced; reverse-flow signedness is not. [`OFFGRID_GENERATOR_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md) and [register audit](../../docs/audits/2026-08-02-register-race-performance-audit.md). | `asserted-unverified` | Observe safe bidirectional AC-couple flow and compare raw U16/decoded values with an independent signed reference, including the sign boundary if safely reachable. |
| Where does dormant GridBOSS UART4 route externally? | Firmware establishes dormancy, not PCB routing. [gridboss.md](gridboss.md#what-firmware-cannot-answer). | `asserted-unverified` | Trace continuity from MCU pins through any transceiver to connector/test pads, obtain a schematic, or—only with separate authorization—scope purpose-built diagnostic firmware. |

## Secondary questions

| Open question | Current boundary and durable basis | Current grade | Evidence that would settle it |
|---|---|---|---|
| What is the complete GridBOSS ARM load base/section map, and is there a separately addressed DSP partner? | The portal lists POWER_HUB but the full mapping is not validated. [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md). | `asserted-unverified` | Back-solve the base from vectors/self-loop, validate code/RAM-pointer density and literals, then enumerate portal components for a paired DSP image. |
| What are the physical meanings of hybrid I21/I22 and I131? | Decoded structures exist, but physical labels remain unresolved. [`HYBRID_EPS_REGISTERS.md`](../../docs/reference/firmware/HYBRID_EPS_REGISTERS.md). | `asserted-unverified` | Capture simultaneous DSP/raw words, per-leg voltage/current/power, event transitions, and independent meter/GridBOSS peers. |
| Do GB-I50-I51 and GB-I84-I87 accumulate generator energy? | Current decoder labels are unestablished. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md). | `asserted-unverified` | Run a connected generator long enough to increment daily/lifetime energy; compare raw words, portal runtime/export, and an independent meter. |
| Are inherited I60-I63 fault/warning bit names correct? | Word locations are mapped; individual names lack controlled injection. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md). | `lineage-inferred` | Observe naturally occurring safe events or use a factory simulator; never deliberately create hazardous production faults. |
| When does I69-I70 reset? | Seconds are `portal-correlated`; reset semantics are absent from the durable evidence. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md). | `asserted-unverified` | Record the U32 series across separately authorized ARM reboot, inverter reboot, replacement, and power-cycle cases. |

Closing an item requires updating [registers.md](registers.md) with the tested family, component firmware versions, raw evidence, restore result where writable, and the weakest defensible grade. A unit fixture cannot close a hardware question.
