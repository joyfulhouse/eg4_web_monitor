---
canonical-for: safe-register-dumping-and-live-verification
sources:
  - /tmp/llmwiki-research/firmware-re-and-registers.md
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - docs/DATA_MAPPING.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Register probing playbook

> **THE VERIFICATION RULE: a register decode is “verified” only after a live empirical cross-check on real hardware. Unit tests can prove that software implements its current assumption; they can never verify the physical register semantic.** [`hardware-toggle-proven` process rule]

For read mappings, compare raw Modbus and the corresponding portal/device behavior simultaneously. For writable mappings, make one named change at a time, capture the raw before/after delta, verify the intended physical/UI behavior, and restore the original value.

## Operation risk classes

| Operation | Risk | Evidence grade | Rule |
|---|---|---|---|
| FC04 input-register read | Read-only | `firmware-proven` | Preferred for runtime discovery. Chunk within device limits and retain raw words. |
| FC03 holding-register read | Read-only operation against writable storage | `firmware-proven` | Safe only while the tool truly issues FC03; do not assume a “parameter” helper cannot write. |
| Portal `/remoteRead/read` | Read-only | `portal-correlated` | Dumps the cloud holding/configuration template, not inverter FC04 runtime registers. |
| Watch a holding register while toggling a setting through the vendor UI | Read-only script plus an intentional configuration change | `hardware-toggle-proven` only after restoration | Record raw before/during/after, family, firmware, and exact named action. |
| FC06 single-register write | Write-risky | `hardware-toggle-proven` only after controlled delta and behavior | Requires authorization, a saved original value, a one-setting hypothesis, and restore verification. |
| FC16 multi-register write | Write-risky | `asserted-unverified` until family-specific behavior is captured | Schedule registers reject FC16; do not generalize support from another range. |
| Portal `write_parameter`, `functionControl`, `bitParamControl`, schedule, or quick-charge API | Write-risky | `portal-correlated` | This is the maximum without a raw hardware delta; a success-shaped response does not prove targeting or physical meaning. |
| `scratchpad/write_register_bits.py` without `--dry-run` | Hazardous | `refuted` as a safe generic probe | It performs FC06, changes AC charging/battery backup, and does not restore both original values. Do not use it as a discovery tool. |

## Tooling

| Tool | Reads | Writes | Use | Evidence / caveat grade |
|---|---|---|---|---|
| `pylxpweb/utils/map_registers.py` | Portal `/remoteRead/read` holding-template ranges | None | Reporter-safe cloud map; repeat `-r start,length`, prefer JSON output | `portal-correlated`; `<EMPTY>` means read succeeded but the template has no mapped parameter, not that the physical register is absent |
| `scripts/probe_all_registers.py` | Local FC03 and FC04 chunks, including extended/battery ranges | None in scan path | Maintainer raw dump with failed-chunk retry | `firmware-proven` for access class; its numeric unit/range guesses are `asserted-unverified`; it writes JSON/Markdown into the repo when run |
| `scripts/probe_gridboss_nbu_regs.py` | GridBOSS FC04 only | None | Read-only GridBOSS/NBU input scan | `firmware-proven` for access class; the gateway is single-client |
| `scratchpad/probe_register_bits.py` | FC03 holding reads/watch | None | Watch a raw word while a separate authorized UI toggle occurs | `portal-correlated` until a controlled raw delta; its H110 b8 Green Mode comment is `refuted` |
| Purpose-built host-side `pymodbus` reader | Whatever FC03/FC04 range the script explicitly requests | None if no write call exists | Small, auditable capture with raw timestamps | `asserted-unverified` until code review confirms the call path; pymodbus 3.13 uses `device_id=`, not `slave=` |

Prefer `.env` credentials for the cloud reporter. A `-p` password appears in shell history and may be visible in the process list. Redact plant IDs, device identifiers, and all but the last four serial digits before sharing a capture.

## Read-only dump procedure

| Step | Action | Required record | Evidence grade produced |
|---:|---|---|---|
| 1 | Identify the physical device and family from an authoritative live identity source. Do not infer it from a remembered serial. | Device type, full local identity kept private, last four serial digits in shared artifacts, firmware versions | `lineage-inferred` scope until hardware identity is corroborated |
| 2 | Ensure one client owns the gateway. Stop or pause competing Home Assistant/dev clients before a direct Modbus capture. | Which client was paused and outage interval | `hardware-toggle-proven` for bus-observation integrity |
| 3 | Establish a baseline operating state: grid/generator/PV/battery state and relevant portal fields. | Timestamped state snapshot | `portal-correlated` |
| 4 | Read raw words with FC04 for runtime or FC03 for configuration. Start with small chunks and split/retry failures. | Function code, start, length, raw hex/decimal words, timestamps | `asserted-unverified` semantics; a responsive address alone proves no name |
| 5 | Repeat across meaningful states or time. Keep zeros, sentinels, wrap, and missing reads distinct. | Raw time series plus state transitions | `portal-correlated` when a portal peer moves consistently |
| 6 | Compare simultaneously against the cloud field or an independent physical meter. Compare physical units after each transport’s scaling. | Raw value, conversion, peer value, allowed error | `portal-correlated`, or `hardware-toggle-proven` for a controlled named action |
| 7 | Restore all paused clients and confirm normal polling. | Restoration timestamp and fresh values | `asserted-unverified` for semantics; this establishes process completion only |

Cloud and local paths can apply different scaling before returning values. Compare physical values, never only scale symbols or raw integers. A raw local decivolt value such as 595 and a cloud engineering value such as 59.5 can represent the same 59.5 V.

## Controlled write verification

Writes are not a register-discovery shortcut. Use them only with explicit authorization and a bounded hypothesis.

| Step | Required action | Stop condition | Evidence grade |
|---:|---|---|---|
| 1 | Confirm exact family, firmware, register, bit mask, accepted range, and physical consequence. | Any unresolved target, shared-register mask, or safety implication | `asserted-unverified` until completed |
| 2 | Read and record the complete original register word and relevant peer values. | Read is inconsistent or another client may be writing | `asserted-unverified`; baseline only |
| 3 | Change one named vendor setting through the safest supported UI/API while independently watching the raw word. | More than the intended bit/field changes | `asserted-unverified`; the candidate is not isolated |
| 4 | Confirm the intended physical/UI behavior, not merely an ACK or readback. | No behavioral change or ambiguous state | Do not promote above `portal-correlated` |
| 5 | Restore the original named setting/value and re-read the complete word. | Restore fails or unexpected bits remain | `asserted-unverified`; escalate and do not continue probing |
| 6 | Repeat once or obtain an independent capture on the same family. | Delta is not reproducible | `asserted-unverified`; do not promote the mapping |

A no-op write proves only that the request format was accepted. It does not prove the parameter name targets the claimed register.

## The wrong-but-writable-bit failure mode

| Observation | Evidence grade | Consequence |
|---|---|---|
| A wrong-but-writable bit is firmware-ACKed. | `hardware-toggle-proven` | There is no exception and no cloud fallback. |
| The integration emits nothing above DEBUG for that successful low-level write. | `hardware-toggle-proven` | Ordinary logs do not reveal the semantic error. |
| Readback returns the bit that was written. | `hardware-toggle-proven` | Readback verifies storage/transport, not that the bit controls the named feature. |
| Historic H110 b8 Green Mode writes succeeded while Green Mode actually lives at b14. | `refuted` old mapping; b14 is `hardware-toggle-proven` | A passing ACK/readback path preserved a false annotation. |
| Gating is the only mitigation for an unproven writable bit. | `hardware-toggle-proven` safety conclusion | Unknown/placeholder bits must be decode-only and unreachable from named writes. |

This is why a contract test, mapping parity test, or mock response cannot make a writable bit safe. All can agree with the same false table.

## What each form of evidence can say

| Observation | Safe conclusion | Unsafe conclusion | Maximum grade |
|---|---|---|---|
| FC03/FC04 returns a value | Address responds on this device/state | The value has the guessed semantic/unit | `asserted-unverified` |
| Value resembles a plausible voltage/power/time | Candidate scale | Register is identified | `asserted-unverified` |
| Portal field and raw register co-vary | Correlated mapping | Controlled causality or family-wide portability | `portal-correlated` |
| Named single-setting toggle produces one raw delta, intended behavior, and clean restore | Mapping for the tested family/firmware | Mapping for all families | `hardware-toggle-proven` |
| Correct firmware trace finds a handler | Response structure/address | Physical semantic without producer/conversion trace | `firmware-proven` only after the full trace |
| Unit tests pass | Software is internally consistent with fixtures | Hardware mapping is verified | `asserted-unverified` for real-world semantics |

## Capture checklist

- Record model, family, device-type code, and all component firmware versions.
- Record timezone and timestamps around every sample or toggle.
- Preserve raw 16-bit words in hex and decimal before applying scaling.
- Record FC03 versus FC04 and exact start/count; never blur holding and input spaces.
- For U32 values, preserve both words and the word-order formula.
- For bitfields, preserve the complete before/after word and XOR mask.
- Record portal/API names exactly, including whether the portal returned engineering units.
- Restore configuration and verify the raw original word.
- Redact credentials, plant identity, hostnames, and most of each serial before sharing.
- Label the resulting claim with the weakest grade that the evidence actually supports.

See [registers.md](registers.md) for the current ledger and [open-questions.md](open-questions.md) for captures that would resolve remaining ambiguity.
