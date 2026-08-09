---
canonical-for: safe-register-dumping-and-live-verification
sources:
  - docs/DATA_MAPPING.md
  - docs/CONFIGURATION.md
  - scripts/probe_all_registers.py
  - scripts/probe_gridboss_nbu_regs.py
verified-against: 9f6d6e2
last-verified: 2026-08-08
runbook-status: untested-as-written
last-executed: never
---

# Register probing playbook

> **THE VERIFICATION RULE: a register semantic is verified only by a live empirical cross-check on real hardware. Unit tests can prove that software implements its present assumption; they never verify the physical register semantic.** This rule follows the [register-annotation ladder](../README.md#evidence-grade-legend).

> **Execution status: UNTESTED AS WRITTEN; last executed: never.** Do not treat this page as a rehearsed production procedure until an authorized dry run records its date, probe lead, rollback owner, exact commands, and health-check result. `asserted-unverified`; durable operational context: [development environment](../50-operations/dev-environment.md).

For reads, compare raw Modbus values with simultaneous portal/device behavior. For writes, make one named change on the target family, capture the complete raw before/after word and physical/UI behavior, and restore the original word. Record component firmware when available as scope metadata; an unrecorded version limits the claim to the tested unit but does not change the canonical grade criterion.

## Live-household change control

Production Home Assistant runs HYBRID and owns the single gateway. Pausing it for a direct probe degrades telemetry and control for a live household. `asserted-unverified`; operational owner: [development environment](../50-operations/dev-environment.md).

| Control | Mandatory requirement | Evidence/status |
|---|---|---|
| Authorization | The household/system owner must explicitly authorize the outage window. Record the authorizer, probe lead, rollback owner, start time, and affected gateway before touching the gateway owner. | Mandatory; no dated execution record exists yet. See [development environment](../50-operations/dev-environment.md). |
| Outage duration | Keep the gateway-ownership interruption as short as the capture allows and record the actual pause-to-restored-healthy interval. If the capture scope expands or the restore health check stalls, exit and restore rather than extending the probe. | Untested runbook requirement; no numeric maximum is supportable until a timed dry run establishes one. |
| Abort authority | The rollback owner may abort immediately for loss of communication, unexpected plant behavior, an unrelated household event, restore uncertainty, or expiration of the window. | Runbook requirement. |
| Escalation | On restore or health-check failure: stop all probing and writes, notify the authorizer and Home Assistant maintainer, restore the production owner from its normal console, and record an incident before another attempt. | Runbook requirement. |

### Mandatory interruption-safe restore trap

Do not issue the pause/stop command until all of these are true:

1. Define a site-specific `restore_gateway_owner` action that restarts the exact production owner only if this run paused it.
2. Make that action wait for a fresh HYBRID poll, confirm the gateway is connected, and check that agreed key sensors have current timestamps and are not unavailable.
3. Exercise the action without an outage and record success.
4. Register it for `EXIT`, `INT`, `TERM`, and `HUP` **before** pausing the owner.
5. Keep the trap active through restore and health check; clear it only after the rollback owner accepts the fresh production poll.

If the environment cannot provide an idempotent restore action and automated freshness check, this runbook is blocked for that site. `asserted-unverified`; see the production ownership model in [development environment](../50-operations/dev-environment.md).

## Operation risk classes

| Operation | Risk | Maximum evidence from the operation alone | Rule |
|---|---|---|---|
| FC04 input-register read | Read-only | No semantic claim | Preferred for runtime discovery. Retain raw words and split chunks within device limits. |
| FC03 holding-register read | Read-only operation against writable storage | No semantic claim | Inspect the actual call path; a generic “parameter” helper may write. |
| Portal `/remoteRead/read` | Read-only | `portal-correlated` | Dumps the cloud holding/configuration template, not inverter FC04 runtime data. |
| Watch a word while changing one vendor setting | Read script plus intentional configuration change | `portal-correlated`; `hardware-toggle-proven` only with the canonical tuple and restore | Record action, family, raw before/after, behavior, and restored raw word. Record component firmware separately as scope metadata when available. |
| FC06 single-register write | Write-risky | `portal-correlated` until controlled behavior and restoration are captured | Requires separate write authorization and a saved complete original word. |
| FC16 multi-register write | Write-risky; behavior is range/family specific | `asserted-unverified` | Do not use FC16 for discovery. [The schedule evidence boundary](registers.md#schedule-write-evidence-boundary) records that no durable general rejection/support proof exists. |
| Portal write/control API | Write-risky | `portal-correlated` | A success-shaped response does not establish raw targeting or behavior. |

## Tooling

| Tool | Reads | Writes | Safe use | Evidence boundary |
|---|---|---|---|---|
| `pylxpweb/utils/map_registers.py` | Portal `/remoteRead/read` holding-template ranges | None | Reporter-side cloud map; repeat `-r start,length`, prefer JSON | `portal-correlated`; `<EMPTY>` means the cloud template has no mapped parameter, not that the physical address is absent. |
| `scripts/probe_all_registers.py` | Local FC03/FC04 chunks and extended ranges | None in its scan path | Maintainer raw dump with failed-chunk retry | Access path is `verified-against-code`; unit/range guesses remain `asserted-unverified`; outputs must be redirected or moved outside the repository before sharing. |
| `scripts/probe_gridboss_nbu_regs.py` | GridBOSS FC04 | None | Read-only GridBOSS/NBU scan | Access path is `verified-against-code`; the single-client outage controls still apply. |
| Purpose-built host reader | Only explicitly reviewed FC03/FC04 calls | None | Small timestamped raw capture | Not graded until a durable script exists and its no-write call path is reviewed; do not rely on an uncited client-library version detail. |

## Credential handling

Never put probe credentials in the repository, a worktree, a synced folder, a capture directory, or a reusable shell-history argument.

| Stage | Requirement | Evidence/status |
|---|---|---|
| Create | Create a private temporary directory outside the repository, for example with `mktemp -d "${TMPDIR%/}/eg4-probe.XXXXXX"`; set the directory to mode `0700` and its `credentials.env` file to mode `0600`. | Runbook requirement. |
| Scope | Use a disposable or least-privilege account/token that can only perform the required reads. Write-capable credentials require separate write authorization. | Runbook requirement. |
| Load | Source the external file only in the probe shell; never pass a password with `-p`, print the environment, or copy the file into shared artifacts. | Shell/process exposure warning is `inferred`. |
| Destroy | After the restore health check, securely delete the temporary credential file and directory. Rotate/revoke the credential immediately if it was write-capable, reusable, exposed to a process list, or included in any capture. | Runbook requirement. |

Redact plant IDs, hostnames, device identifiers, and all but the final four serial digits before sharing captures.

## Read-only dump procedure

| Step | Action | Required record | Maximum evidence produced |
|---:|---|---|---|
| 1 | Obtain outage authorization and identify the device from a current identity source. Install the tested restore trap. | Authorizer, probe lead, rollback owner, device/family, all component firmware, approved window | No semantic claim until live identity is corroborated. |
| 2 | Establish baseline grid/generator/PV/battery state and relevant portal fields. | Timestamped state snapshot and key-sensor freshness | `portal-correlated` only when a peer exists. |
| 3 | Start the timer, let the trap pause the competing owner, and verify exclusive gateway ownership. | Pause timestamp and owner name | Process integrity only. |
| 4 | Read raw FC04 runtime or FC03 configuration words in small chunks; split and retry failures. | Function code, start, count, raw hex/decimal words, timestamps | No semantic claim. |
| 5 | Exit immediately so the trap restores the production owner. Do not consume the outage window formatting or interpreting output. | Restore timestamp | Process completion only. |
| 6 | Require a fresh HYBRID poll and the pre-agreed sensor health checks. | Fresh timestamps, availability, gateway status, rollback-owner acceptance | Process completion only. |
| 7 | Compare the preserved raw values with simultaneous portal fields or an independent meter, keeping missing, sentinel, zero, and wrap states distinct. | Conversion formula, peer value, error bound, state transition | At most `portal-correlated` without a controlled named action. |

Cloud and local transports may scale the same physical value differently. Compare engineering values after documenting each conversion; do not compare only raw integers.

## Controlled write verification

Writes are not a discovery shortcut. They require their own explicit authorization after a successful read-only rehearsal.

| Step | Required action | Stop condition | Evidence/status |
|---:|---|---|---|
| 1 | Confirm family, every component firmware version, register, mask, accepted range, consequence, outage controls, and restore plan. | Any unresolved target, mask, family scope, or physical consequence | Stop; no promotion. |
| 2 | Read and save the complete original word and peer values. | Inconsistent reads or another writer | Stop and restore ownership. |
| 3 | Change one named setting through the safest supported vendor path while independently watching the raw word. | More than the intended field changes | Do not promote the mapping. |
| 4 | Confirm intended physical/UI behavior—not ACK or readback alone. | No behavior or ambiguous behavior | Maximum `portal-correlated`. |
| 5 | Restore the named setting and exact original word; re-read and health-check production. | Restore mismatch or stale/unavailable production data | Escalate; no further writes. |
| 6 | Repeat once or obtain an independent same-family capture. | Non-reproducible delta | Stop; no promotion. |

## The wrong-but-writable-bit failure mode

| Observation | Evidence | Consequence |
|---|---|---|
| The historic wrong H110 b8 write was accepted, but did not control Green Mode. | `portal-correlated`; issue #476 and [contradiction C5](../60-history/open-contradictions.md) | A firmware ACK does not establish semantics. H110 b8 remains UNKNOWN. |
| The successful low-level write has no exception, fallback, or operator-visible message above DEBUG. | `verified-against-code` against the coordinator write path | Ordinary operation does not surface the semantic error. |
| Readback returns the stored wrong bit. | `inferred` from the accepted-write path | Readback checks transport/storage, not named-feature behavior. |
| Therefore an unproven writable bit must be gated out of named writes. | `inferred` safety conclusion | Gating is the only mitigation available in this path; unknown bits remain decode-only. |

This is why a contract test, mapping-parity test, ACK, or readback can all succeed around the same false table.

## Capture checklist

- Authorization, probe lead, rollback owner, approved outage window, and execution date.
- Model, family, device-type code, and every component firmware version.
- Exact timezone and timestamps for samples, pause, restore, and health check.
- Raw 16-bit words in hex and decimal before scaling; both words and word-order formula for U32.
- Function code, exact start/count, and the complete before/after/restore word for bitfields.
- Exact portal/API action and engineering-unit conversion.
- Intended physical/UI behavior, restore result, and fresh production poll.
- Credential deletion/rotation and capture redaction.
- The weakest grade supported by the completed evidence tuple.

See [registers.md](registers.md) for the current ledger and [open-questions.md](open-questions.md) for the captures that would settle remaining ambiguity.
