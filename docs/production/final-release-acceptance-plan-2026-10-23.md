# Final-release production acceptance plan, 2026-10-23

Status: **not executed**. Deployment, restart and rollback restart require fresh
explicit authorization. Publishing any release requires separate authorization.

October 25 preflight: the locally prepared source candidate is
`77e6c8652d46042e2a919c8e461ddd2c10724c3a`, with 81 files in a `git archive`
tar and SHA-256
`a1a88813c0fac664ba23644aaf85d9eb7acdfe8f9c231007383c58d04d5536c8`.
Every archive file was checked against that commit. The installed component
still matches published beta.21, while HA now reports 2026.10.3. The
[preflight record](release-preflight-2026-10-25.json) owns the dated observations.
This identifies a reviewable candidate; it does not authorize installation.

The existing diagnostics serializer replaces acquisition datetimes with
`<datetime>`. Recorder history also lacks full contributor lineage. These
capture paths cannot satisfy the acquisition-freshness and provenance gates
below, even if numeric values change or reset. A suitable evidence path remains
required; do not silently relax the gates or treat a restart as resolving them.

## Candidate and scope

Use the exact reviewed integration main commit supplied with the deployment
authorization request; the readiness report records the tested source and PR.
Prepare a private archive of `custom_components/eg4_web_monitor/` from that exact
commit, record its SHA-256 and file manifest, and compare it with the beta.21 tag
`ca2f63580091bc5a771253a7dbc5fa09fdb70f2a` before asking for approval.
The intended production changes are `diagnostics.py` (#691), `sensor.py`
(#692), and `ha_modbus.py` (reject a shared-link conflict instead of opening an
independent connection; related to pylxpweb #350). Stop and revise this plan if
other runtime files differ.

This is an explicitly identified source candidate overlay, not a published HACS
release. Its embedded version remains beta.21; record the deployed Git commit and
archive digest privately outside the component so that version text cannot be
mistaken for proof of installed source. Keep the existing published pylxpweb pin.

## Read-only preflight

1. Obtain approved authenticated REST/WebSocket and existing administrative SSH
   access. Do not copy credentials into this repository, logs, or public issues.
2. Verify HA/runtime package versions, entry load state, the current installed
   component file hashes, and no concurrent HACS update or other deployment.
3. Check the site's restart operational policy privately immediately before the
   action. Record only whether preconditions passed in a public result.
4. Capture private entity/device registries, config entry/options, active states,
   recent logs and diagnostics. Compare identities and ownership as well as
   counts. Label unknown/unavailable states by entity class and source; unknown
   buttons and inactive countdowns alone are not evidence of regression.
   Collect at least 30 minutes of passive baseline polling and record each
   transport/source's configured acquisition interval, timeout and observed
   successful acquisition times. If acquisition timestamps are unavailable,
   record that gap instead of substituting HA state-publication timestamps.
5. Confirm the existing rollback artifacts and native HA backup are readable.
   The earlier pre-upgrade archive contains beta.20, so it is not the exact
   rollback target for this candidate. A fresh backup is required below.

## Authorization to request after the candidate is fixed

Request approval for the exact commit/digest, a private fresh backup, replacement
of the component, and one HA Core restart, plus restoration of that fresh
component backup and one additional restart **only if rollback is needed**.
Approval must identify whether that conditional rollback restart is included.
If it is not included, request it before performing rollback.

## Authorized deployment

1. Create a new private, timestamped rollback directory under `/config/.eg4-rollback/`.
   Preserve the entire currently installed component, its hashes, the relevant
   config/entity/device storage files, and current package-version evidence.
   Verify the archive can be listed and the saved component matches the baseline.
   Keep existing backups. Registry snapshots are comparison/recovery evidence;
   ordinary component rollback must not overwrite live HA storage.
2. Stage the candidate separately on HA and verify every file against the local
   archive manifest. Replace the component only after that check; retain the
   exact prior directory for rollback. Preserve ownership and permissions.
3. Recheck operational preconditions and perform the one authorized Core restart.
   Wait for HA and the EG4 entry to settle over normal poll cycles.
4. Compare installed file hashes, package versions, registry IDs, entity settings,
   device ownership, config/options and availability against the fresh baseline.
   Investigate changed identities or newly degraded known states before acceptance.

## Read-only acceptance after restart

| Issue | Required observation | Limit |
|---|---|---|
| #691 | Download diagnostics; correlate request timestamps with logs; no new blocking metadata filesystem warnings. Privately verify known sensitive aliases/config values are redacted. Confirm entity/config identity is preserved. | Existing unit regressions establish executor use and redaction ordering; live warning absence requires the deployed candidate. Never publish raw diagnostics. |
| #692 | One remaining-time registry entity per eligible inverter (supported model/family and HTTP or configured per-device local transport), unchanged existing unique/entity ID and enabled/disabled settings, no duplicate-ID startup warnings; status source and inactive/active availability agree with available read-only evidence. | A disabled registry entry need not have an active state. Do not activate quick charge. Mocked active countdown coverage is valid software evidence; live active behavior remains unobserved unless it occurs normally. |
| Shared Modbus ownership | Existing configured transports load normally; if an existing shared-link conflict appears, preserve its error and investigate configuration. | Do not introduce a conflict on hardware. Offline HA regressions verify rejection, retry and ownership. No endpoint-wide scheduling claim is made. |
| #693 | Timestamp passive poll durations, last successful acquisition/freshness, local/cloud selection, warnings and natural recovery; correlate unavailable entities with their transport. | Unchanged counts do not prove link health. If no failure/recovery occurs, record the unexercised case. No gateway restart or induced outage. |
| #694 / #666 | Follow a natural HA-local midnight with inverter/group/GridBOSS CT numeric sources and per-field acquisition lineage; observe cached data and any natural member loss/recovery. | Recorder history can show values but may not retain contributor lineage; without it, do not claim provenance acceptance. No clock changes. |
| #659 | If available, capture same-time cloud `totalUsage`/`todayUsage` and local component counters, with units and timestamps. | No formula changes or statistics repair from an unproven source assumption. |

For the midnight check, only a nonempty set of entirely LOCAL contributors from
one HA-local calendar day qualifies a baseline timestamp; retain the earliest
acquisition. HTTP, missing, unknown, empty and mixed-day lineage must not expire
a baseline. Acquisition day does not establish inverter reset timezone. Lifetime
formulas and behavior are outside this change.

The existing [beta.21 record](beta21-2026-10-23.json) is historical evidence, not
the baseline for a later deployment. New observations must be timestamped and
sanitized before publication. Keep unobserved scenarios explicit, including full
reconfiguration, rollback restoration, direct batteries, generator use and
firmware-specific write rejection. Do not automatically enable master battery
reconstruction.

## Observation windows and decisions

These are proposed operational acceptance thresholds for this deployment, not
measured hardware guarantees. Record the interval inputs in the private preflight
and include these thresholds in the authorization scope:

- Let `T` be the configured acquisition interval for the particular transport or
  source, including any deliberate cloud/parameter throttling. Let `Tmax` be the
  longest interval among the runtime sources being accepted. Compare each field
  with its own interval; a slow parameter schedule must not excuse stale runtime
  telemetry, and cloud fallback must not be counted as a successful local read.
- Allow initial settling for `max(10 minutes, 5 * Tmax)` after the HA API returns.
  At that deadline the entry must be loaded, identity/config preserved, and known
  states restored to their baseline availability. Diagnose or roll back a new
  candidate-attributable failure; do not extend the deadline silently.
- Flag runtime acquisitions older than `max(3 * T, 180 seconds)` as stale. Record
  start/end, numeric source, fallback and affected entities. A new degradation
  persisting for `max(5 * T, 10 minutes)` triggers rollback assessment. A baseline
  failure that continues unchanged remains an acceptance gap rather than proof
  that the candidate caused it.
- After settling, observe at least 24 hours, including at least 60 minutes before
  and after one natural HA-local midnight. Review at that deadline. Require no
  unexplained new identity/config/availability regressions, qualified provenance
  for the rollover claims, and documented reconnect/fallback outcomes. Repeated
  warnings without freshness/recovery evidence leave #693 unresolved.
- A naturally occurring failure passes the recovery check only when the affected
  local source resumes fresh acquisitions within the degradation threshold and
  its baseline states recover. If no failure occurs, explicitly mark recovery
  unobserved; do not induce one. If lineage/history is insufficient or any gate
  is inconclusive, keep the corresponding release blocker open and state the
  additional evidence needed. Elapsed time alone never passes the gate.

## Rollback criteria and procedure

Rollback for setup failure attributable to the candidate, changed entity/config
identity, a redaction regression, sustained new availability degradation, or an
unexpected candidate-induced polling failure. Preserve private failure evidence.
Restore the freshly saved component directory, verify its hashes, and perform the
conditional restart only if authorized. Recheck entry load and baseline identity,
settings and settled states. Do not restore registry/config storage automatically;
that is a separate recovery action requiring a concrete diagnosis and approval.

If runtime/library versions changed unexpectedly, stop: component-only rollback
is insufficient and this plan must be revised. No dependency installation or
hardware command is included in this plan.
