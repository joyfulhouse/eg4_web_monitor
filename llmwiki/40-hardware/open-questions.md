---
canonical-for: unresolved-hardware-register-and-firmware-questions
sources:
  - /tmp/llmwiki-research/firmware-re-and-registers.md
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - docs/DATA_MAPPING.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Open hardware and firmware questions

Unknown means unknown. These items must remain family-scoped, gated, or unexposed until the listed evidence exists.

| Open question | Current bounded knowledge | Current evidence grade | Evidence that would settle it |
|---|---|---|---|
| What is the exact OTA per-block checksum/key algorithm? What bytes and CRC variant does the final integrity field cover? | Normal records contain one prefix, 768 payload bytes, and two model-keyed check bytes. The variable final record adds a four-byte firmware ID and a little-endian 16-bit field. Old XOR/custom-CRC claims came from invalid framed/byte-swapped analysis. | `asserted-unverified` | Compare correctly parsed same-payload blocks across model keys; test explicit key derivations, coverage boundaries, byte order, polynomials, init/xor/reflection variants against every normal record and multiple final trailers. |
| Do concrete 6000XP and 12kPV images validate under the corrected method? | Portal enums exist. No reviewed concrete 6000XP or separately validated 12kPV image establishes their vector/base/entry/call-target structure. | `asserted-unverified` | Retrieve `appLocalUpdate` images; record hashes, lengths, address spans, and versions; validate ARM vectors/load base or C28x MSB-first entry, opcode population, and in-image call targets. |
| Is H110 bit 14 Green/Off-Grid Mode on 12000XP and 6000XP? | H110 b14 is toggle-proven on 18kPV hybrid. Off-grid-family applicability is inherited from the unified layout, not independently toggled. | `lineage-inferred` | On each off-grid family, perform one named cloud/LCD Green Mode toggle while recording raw H110 before/after, confirm XOR `0x4000` and visible behavior, then restore. |
| What do the remaining unknown H110 bits mean? | b10/b14/b15 are toggle-proven; b7 is portal-correlated. Historic b5/b6/b8/b9 names are refuted. Bits 0/2/3/4/11–13 remain inferred or unknown. | `lineage-inferred` | Toggle one named CT/PVCT/buzzer/ECO/system setting at a time; capture complete raw H110 before/during/after, intended behavior, and restore. Never infer adjacent bit names. |
| What do the remaining unknown H179 bits mean? | b3/b7/b9/b10 are toggle-proven; b11 AC coupling is lineage-inferred; the safe map leaves the rest unknown. | `lineage-inferred` | For each candidate, capture one named setting’s raw H179 delta with behavioral confirmation and restoration. Correlate the exact portal parameter, but do not promote a name without the raw lockstep delta. |
| What do the remaining unknown H233 bits mean and where do they apply? | b0 quick-charge, b1 battery-backup control, and b12 sporadic charge are toggle-proven. Off-grid local H233 access is rejected. Other confident names are not accepted by the safe map. | `lineage-inferred` | Capture one named portal/UI action per bit with full-word raw delta and restore on each applicable family; explicitly test family rejection. Preserve atomic read-modify-write for the shared word. |
| Where is genuine off-grid generator power? | On 12000XP, I123 is a boot/ARM counter; I124-I126 are status, and I188/I189 are unimplemented. I17 and I27 are candidates only. The claim “no such field exists anywhere” is not proven. | `asserted-unverified` | Run a generator and capture full raw FC04 blocks including I17/I27, portal fields, generator voltage/frequency, load flows, and an independent real-power meter over start/load/stop transitions. |
| What do individual off-grid I124-I126 bits mean? | I124’s byte structure and the I125-I126 U32 status-word structure are firmware-proven. Writers touch I124-low b0/b1/b3 and U32 bits 0/6/7/14/16/29, but no user-facing semantic is established. | `asserted-unverified` for bit meanings | Correlate one physical/device-state transition at a time with raw words, then trace each known writer condition in correctly decoded firmware. Do not attach a name from bit position alone. |
| What unit does I210 use on each supporting firmware? | The EG4 stack currently treats it as quick-charge remaining seconds, while conflicting comments/documentation exist. | `lineage-inferred` | Start a known-duration quick-charge session; sample raw I210 and wall clock at a fixed cadence through zero on the same firmware; repeat after reboot/idle. |
| Is I153 signed for reverse AC-couple flow? | The producer/path and AC-couple-power role are firmware-proven; the canonical output is currently unsigned. Reverse-flow interpretation is not established. | `asserted-unverified` for signedness | Create or observe AC-couple power in both directions; capture raw U16 and decoded values against an independent signed power reference, including values across `0x7fff/0x8000` if safely reachable. |
| Where does dormant GridBOSS UART4 route externally? | UART4 plumbing, PD0 direction behavior, absence of clock/init/consumer, and absence of any DIP-enable path are firmware-proven. Connector/transceiver routing is not. | `asserted-unverified` | Trace PCB continuity from MCU UART4 pins through any transceiver to connector/test pads; obtain a schematic or scope the route. Only with explicit authorization, use purpose-built firmware to clock/configure UART4. |

## Secondary firmware questions

| Open question | Current evidence grade | Evidence that would settle it |
|---|---|---|
| What is the complete GridBOSS ARM load base/section map, and is there a separately addressed DSP partner? | `asserted-unverified` | Back-solve the base from vectors/self-loop, validate code/RAM pointer density and literals, then enumerate portal components for a paired DSP image. |
| What are the exact physical meanings of hybrid I21/I22, I131, and I132? | Old voltage/apparent-power labels are `refuted`; decoded structures are `firmware-proven` | Capture simultaneous DSP/raw words, per-leg voltage/current/power, event transitions, and GridBOSS/independent-meter peers. |
| Do GridBOSS GB-I50-I51 and GB-I84-I87 accumulate generator energy? | `asserted-unverified` | Run a connected generator long enough to increment daily/lifetime energy and compare raw words, portal CSV/runtime fields, and an independent meter. |
| Are inherited I60-I63 fault/warning bit names correct? | `lineage-inferred` | Observe naturally occurring safe faults/warnings or use a factory simulator; capture raw words. Never deliberately create hazardous production faults. |
| Does I69-I70 reset on ARM reboot, inverter reboot, replacement, or power cycle? | `portal-correlated` for seconds; reset semantics `asserted-unverified` | Record the U32 time series across each controlled reboot class and normal wrap/continuity. |

## Refuted starting points

| Do not start from this claim | Evidence grade | Start from this instead |
|---|---|---|
| H110 b8 is Green Mode. | `refuted` | b14 is toggle-proven on 18kPV; off-grid applicability remains open. |
| H110 b5 is Take Load Together. | `refuted` | b10 is toggle-proven. |
| H21/H231 are the peak-shaving enable/power mapping. | `refuted` | H179 b7 enables peak shaving; H206 and H232 are the two power setpoints. |
| Off-grid I123/I124-I126 are generator power/energy. | `refuted` | I123 is a counter; I124-I126 are status structures. Search for generator power independently. |
| GB-I105-I108 carry smart-port status. | `refuted` | GB-H20 carries modes; GB-I104-I119 are energy words. |
| The old generated firmware RE output can answer these questions. | `refuted` | Re-acquire/de-frame, decode C28x MSB-first, validate structure, and trace end to end. |

Any future resolution must update [registers.md](registers.md) with the tested family, raw evidence, and the weakest defensible grade. A unit-test fixture alone cannot close an item on this page.
