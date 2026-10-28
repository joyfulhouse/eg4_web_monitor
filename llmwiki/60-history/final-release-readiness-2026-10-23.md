---
canonical-for:
  - "October 2026 final-release preparation issue classification and acceptance gaps"
sources:
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/702
  - https://github.com/joyfulhouse/pylxpweb/issues/396
  - docs/production/hybrid-energy-fallback-validation-2026-10-28.json
  - docs/production/pylxpweb-b14-publication-2026-10-25.json
  - docs/production/candidate-soak-progress-2026-10-25-late.json
  - custom_components/eg4_web_monitor/manifest.json
  - tests/requirements-test.txt
  - docs/production/acquisition-evidence-validation-2026-10-25.json
  - custom_components/eg4_web_monitor/energy_evidence.py
  - custom_components/eg4_web_monitor/diagnostics.py
  - tests/test_daily_energy_evidence.py
  - tests/test_diagnostics_acquisition_times.py
  - https://github.com/joyfulhouse/pylxpweb/commit/cac7a9f498aa20528577a08ce1541fdb59f77481
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/691
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/692
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/693
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/694
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/666
  - docs/production/final-release-acceptance-plan-2026-10-23.md
  - docs/production/final-release-preparation-2026-10-23.json
  - docs/production/release-preflight-2026-10-25.json
  - docs/production/candidate-deployment-2026-10-25.json
  - docs/production/candidate-soak-progress-2026-10-25.json
  - docs/production/diagnostics-privacy-validation-2026-10-25.json
  - custom_components/eg4_web_monitor/ha_modbus.py
  - tests/test_ha_modbus.py
  - tests/test_sensor_entities.py
  - tests/test_energy_provenance_adoption.py
  - tests/test_energy_guard_restore.py
verified-against:
  # Dependency delivery and acquisition evidence; historical sections retain their pins.
  eg4_web_monitor: c336cb58ef6be127c03bd3a4b7ac369c06280192
  # Candidate-version source only; historical b13 checks retain cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b.
  pylxpweb: cac7a9f498aa20528577a08ce1541fdb59f77481
last-verified: 2026-10-28
see-also:
  - production-beta21-2026-10-23.md
  - maintenance-2026-10-22.md
  - ../10-integration/entities-identity-availability.md
  - ../10-integration/diagnostics-repairs.md
  - ../20-pylxpweb/transports.md
---

# Final-release preparation, 2026-10-23

Recommendation: **hold final publication** until the production acceptance gates
below have evidence or the release scope is explicitly revised. This is a dated
release judgment (`inferred` from the linked issue acceptance criteria), not a
claim that every open feature blocks shipping. No release publication is
authorized by this report.

## October 25 preflight

The [read-only preflight record](../../docs/production/release-preflight-2026-10-25.json)
owns the observations and validation results. At preflight, integration main was
`77e6c8652d46042e2a919c8e461ddd2c10724c3a` after #695; library main remains
`cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b`. No PRs were open when checked.
Unlike the October 23 preparation session below, authenticated API and existing
SSH access worked. Production reported HA 2026.10.3 and released b13. All 81
installed component files matched published beta.21, so neither #690 nor #695 was
deployed at that checkpoint. These are dated observations, `asserted-unverified` under the wiki
legend, not hardware-toggle evidence.

Fresh offline validation covers minimum HA 2026.10.0, latest published HA
2026.10.4, and exact production HA 2026.10.3 with matching test plugins.
All three full suites and strict typing pass; exact counts and the initial
sandbox-only socket-bind failures are in the preflight record. The latest CI
constraints move to the published pair together. This is software compatibility
evidence, not deployed-candidate acceptance.

The entry is loaded. The new registry/state capture has the same aggregate
counts as the prior smoke test, but does not establish identity equality across
the two captures or transport health. Classification distinguishes inactive
countdowns, button states and explicit AC-couple disabled sentinels from missing
measurements. All unavailable states carry HA's `restored` attribute; none is
attributed to the dongle on count evidence alone. Registry entries were not
removed or changed.

The completed 30-minute passive baseline contains 61 state snapshots without a
read error. Active entity IDs and availability counts remain constant, and the
closing entity/device registry records and config-entry listing metadata equal
the initial captures. This does not compare raw stored credentials or establish
identity continuity back to October 23. One dongle warning occurs inside this
window despite stable state availability. The preflight record preserves the
timestamps and the unresolved acquisition/fallback/recovery boundaries.

The diagnostics request reproduced the metadata blocking warnings on installed
beta.21. Historical logs contain dongle connection timeouts and host-unreachable
errors. Recorder history spanning a natural local midnight shows numeric daily
resets. Neither source establishes acquisition freshness or recovery, and the
history lacks per-field contributor lineage. The deployed candidate's diagnostics
replaced acquisition datetimes with placeholders; the [diagnostics owner](../10-integration/diagnostics-repairs.md)
owns that serialization limitation. At preflight, #691, #693, #694 and #666
remained release blockers. The deployment checkpoint below updates #691; a
24-hour candidate soak has not occurred.

#692 is closed upstream by #695: its acceptance explicitly permits mocked
active/inactive behavior, and the merged tests also cover real HA startup and
registry identity. The preflight did not include patched production startup;
the deployment checkpoint below adds that observation. Other issue classifications remain the proposed scope;
no outstanding hardware/reporter acceptance was closed in this continuation.

The exact existing-main runtime candidate and archive digest are recorded in
the preflight artifact. Its runtime delta from beta.21 is limited to the three
files in the [deployment plan](../../docs/production/final-release-acceptance-plan-2026-10-23.md).
The old rollback files remained readable, but preserved beta.20; at that
preflight checkpoint a fresh beta.21 backup and explicit deployment/restart
authorization were still required.
No production mutation or release publication occurred during that preflight.

### Authorized deployment checkpoint

After the preflight, the user authorized the exact candidate replacement, a
fresh private backup, one Core restart and conditional rollback with one further
restart. The [deployment record](../../docs/production/candidate-deployment-2026-10-25.json)
records the subsequent work (`asserted-unverified`, dated execution evidence).
The fresh rollback archive is listable, its component hashes match the installed
baseline. Canonical operational preconditions passed before activation at
14:13:15 UTC. All 81 installed files match the candidate, with original
ownership/permissions preserved. One restart completed; no rollback was needed.

At 14:17 UTC the entry was loaded, raw EG4 config entries and entity registry
records were unchanged, and device records differed only in five `modified_at`
timestamps. No previously known state degraded. The two existing
inactive countdown entities now report zero, with no duplicate-ID startup
warnings. The downloaded diagnostics produced no post-restart metadata blocking
warnings; older log entries were excluded by the activation timestamp.

Full diagnostics acceptance remains open: private checks reproduced pre-existing
nested-host and wrapper repair-ID exposure before and after deployment. New
[#697](https://github.com/joyfulhouse/eg4_web_monitor/issues/697) is a release
blocker until resolved or explicitly scoped by the user. The diagnostics owner
records the boundary; no private values are published. This is not a
candidate-attributable redaction regression. #691's stated acceptance is narrower:
independent review, green CI and authorized runtime verification without metadata
blocking warnings. Those conditions are met; its closure does not discharge the
separate #697 redaction gate. #693/#694/#666 and the required soak remain open.

The initial ten-minute stability capture has 21 successful snapshots with stable
active IDs and no degradation of previously known states. It is not the settling
gate. With the configured 600-second HTTP interval, the plan retains a 50-minute
settling allowance: the conservative 14:17 UTC anchor places its deadline at
15:07 UTC on October 25. A finite private read-only collector started at 14:33 UTC
and is configured through 15:07 UTC on October 26, covering the full subsequent
24 hours and natural local midnight. Its start and initial subscription/downloads
were verified; completion and acceptance are pending. It watches the existing
enabled entity set, so later registry additions need separate reconciliation.
Neither the collector nor elapsed time resolves acquisition/provenance gaps or
automatically closes an issue.

## Evidence available in the October 23 session

Fetched upstream before work: integration `bf8bfe6ef02570288cae809445773e1e29fb074a`
and library `cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b`. The October 23 validation
artifact records the subsequently tested source `af613d779035a19412c84a1bcf300b210f2adf32`. There were
16 open integration issues, six open library issues, and no open PRs. Work used
isolated worktrees. The local cgroup limit was 8 GiB; heavy validation was
serialized. These are dated observations (`asserted-unverified`, this report).

Production's HTTP API was reachable but returned 401 without authentication.
Neither the approved token variables nor the earlier root `.env`/SSH credentials
were available in this sandbox. No authenticated live state, history, diagnostics
or logs were obtained. No deployment, restart, induced outage, clock change,
generator operation or test hardware write occurred. The earlier
[production record](production-beta21-2026-10-23.md) remains historical evidence;
elapsed time does not extend its observation window. These session observations
are `asserted-unverified` and do not prove current production health.

The sanitized historical record contains only aggregate unknown/unavailable
counts. It cannot classify each entity or correlate it with a transport. Normal
button unknowns and inactive countdowns must be distinguished using a fresh
private registry/state capture; no blanket regression classification is justified
(`inferred` from the evidence fields in `docs/production/beta21-2026-10-23.json`).

## October 23 reviewed software and validation

The tested source is `af613d779035a19412c84a1bcf300b210f2adf32`.
The [sanitized validation record](../../docs/production/final-release-preparation-2026-10-23.json)
owns the exact environment and results. On Python 3.14.8, both HA 2026.10.0
and 2026.10.2 passed 4,190 tests, with 9 skipped and 93% rounded coverage;
strict mypy passed for both. Lint, formatting and Silver/Gold/Platinum validators
passed. These are dated run observations (`asserted-unverified`, the validation
record), not production acceptance.

Fourteen countdown cases fail on the original implementation, and four
shared-Modbus conflict cases fail on the original factory. Fixed coverage
includes real HA registry identity/state publication and HA shared-owner
preservation/retry, without hardware I/O. The tests define software contracts
(`verified-against-code` at the source pin), with residual live acceptance as
listed below.

Independent gpt-6-astra review found no actionable correctness findings in the
combined source; its operational-plan findings were corrected. Session model and
medium reasoning effort were checked through Omnigent session metadata. Final
PR checks and exact-head review are merge gates, not substitutes for production
acceptance (`asserted-unverified`, the validation record).

## Integration acceptance and release scope

### October 25 partial-soak checkpoint

The [sanitized progress record](../../docs/production/candidate-soak-progress-2026-10-25.json)
records the 16:24 UTC collector heartbeat and readable event prefix through
16:07 UTC. No previously known entity becomes unknown or unavailable in that
prefix, and the collector reports no errors. These are dated observations,
`asserted-unverified` under the evidence legend. They support partial published
availability stability, not local acquisition freshness or transport recovery.
The recorded warnings continue, and the diagnostics captured at this checkpoint
still discard acquisition datetimes. The [diagnostics owner](../10-integration/diagnostics-repairs.md)
owns that limitation. Natural local midnight at October 26 07:00 UTC and the
post-settling 24-hour deadline at 15:07 UTC have not occurred at this checkpoint.
#693, #694 and #666 remain blockers; elapsed time alone cannot satisfy them.

### October 25 acquisition-evidence source progress

Source at `ca2bbf0bbf086f2b0d798d5d84dbb451845f5b21` adds a daily-energy
evidence capture path and preserves aware acquisition timestamps in diagnostics. The
[data-semantics owner](../10-integration/data-semantics.md#423-daily-energy-diagnostic-evidence-666)
and [diagnostics owner](../10-integration/diagnostics-repairs.md#acquisition-timestamps-and-capture-time)
own the code contract, scope and privacy limits. These are
`verified-against-code` source claims, not an observation that production runs
this code. The [validation artifact](../../docs/production/acquisition-evidence-validation-2026-10-25.json)
records passing complete minimum/latest HA suites, strict typing, Ruff, formatting,
tier checks and commit hooks. The tests exercise released b13 and HA lifecycle;
these software results do not establish production acceptance.

The deployed candidate and its existing private collector remain on their
previous source. This change neither recovers discarded timestamps from older
captures nor supplies poll duration, runtime fallback or recovery evidence.
A separately authorized installation/restart and suitable subsequent capture
are still required before making new production acquisition claims. The
existing natural-midnight/soak window remains evidence about its exact deployed
candidate. #693, #694 and #666 remain open; #697 retains its separate private
full-download acceptance gate. No release publication follows from this source
progress.

At this checkpoint, pylxpweb main is
`cac7a9f498aa20528577a08ce1541fdb59f77481`; its merged release candidate declares
`0.10.0b14` (`verified-against-code`, `pyproject.toml` at that commit). Publication
remains pending: required immutable `v*` update/deletion protection is missing,
and the prepared rule awaits authorization. It has no bypass actors or
tag-creation restriction. The integration manifest and this validation use
released b13, and production remains on integration
`77e6c8652d46042e2a919c8e461ddd2c10724c3a` with b13. A merged
library release candidate is not evidence of a published artifact or deployed
integration pin. The dated workflow/authorization state is `asserted-unverified`
in the linked validation artifact, not a permanent statement about later releases.

### October 25 authorized b14 delivery and natural recovery observation

The user authorized version-tag protection and the prepared pylxpweb prerelease.
The [publication record](../../docs/production/pylxpweb-b14-publication-2026-10-25.json)
records active immutable-version-tag protection, successful release workflow
`40216833784`, and independent source/tree/attestation/hash verification of the
same wheel and sdist on TestPyPI and PyPI. A clean offline wheel install passes
inverter/GridBOSS deep-counter recovery with no network attempts. These are dated
execution observations, `asserted-unverified` under the wiki legend; the
[release-process owner](../50-operations/release-process.md) owns the trust contract.

At integration `c336cb58ef6be127c03bd3a4b7ac369c06280192`, both runtime and test
requirements select the verified `pylxpweb==0.10.0b14` artifact
(`verified-against-code`, `manifest.json`, `tests/requirements-test.txt`). Full
minimum/latest HA tests, dependency checks, strict typing and quality gates pass;
the publication record owns exact validation results. Production still runs the
older integration source with b13. This delivery does not authorize an integration
release or another production deployment/restart.

The [later passive checkpoint](../../docs/production/candidate-soak-progress-2026-10-25-late.json)
adds a natural software-reported GridBOSS link-down/restore event. Nine local-only
AC-couple controls became unavailable and recovered within about 56.25 seconds;
no sensor availability loss was observed during that event. The source-linked
availability predicate explains why the link flag gates those controls. The
artifact records exact times, adjacent snapshots and pinned source analysis.
These runtime observations are `asserted-unverified`; code predicates are
`verified-against-code` at the artifact's installed integration/library pins.

Issue #693's original bounded investigation acceptance permits documenting the
remaining evidence gap. Independent review adjudicated that acceptance met by
this software-state recovery plus the explicit gaps: cause, poll/fallback duration,
validated acquisition freshness and unobserved object replacement remain unresolved.
No root cause or warning fix is claimed. **The deployment plan's stricter recovery
check has not passed:** fresh local acquisitions plus recovered baseline states
remain required under #694. #666 retains acquisition-lineage and natural rollover
acceptance. Closing the narrower investigation cannot relax those release gates.

### October 28 source-switch regression

Issue #702 reports repeated HYBRID counter drops during local failures, followed
by inflated HA statistics on recovery (`asserted-unverified`, issue body and
reporter follow-up). The reporter corrected the initial setup-only hypothesis:
the stale HTTP snapshot sometimes advances between events. The
[validation record](../../docs/production/hybrid-energy-fallback-validation-2026-10-28.json)
reproduces the mismatch with released b14 and records the bounded integration
fix at `0b7cbb6b15efb5fce05f598bc89cf1f7304e308a`. The [data-semantics owner](../10-integration/data-semantics.md#424-locally-configured-hybrid-inverter-energy-during-gaps-702)
owns its source contract and limitations. Tests and source review do not establish
reporter or production acceptance; #702 remains open for that follow-up.

The previously approved deployment candidate `75aaba62cd993201569de7d18748e666c4eb86d0`
has not been installed by this work. Operational preconditions remained unmet
when rechecked October 28. A candidate incorporating #702 must be separately
identified before activation; no restart or hardware action occurred during
this investigation. Final publication remains on hold.

### Classification

Each classification is a release judgment (`inferred`) from the linked issue and
its acceptance comments. "Accepted limitation" means retained, explicitly
bounded behavior in this proposed release scope; it does not close the issue or
claim missing hardware acceptance. New evidence can change the classification.

| Issue | Classification | Remaining boundary |
|---|---|---|
| [#702](https://github.com/joyfulhouse/eg4_web_monitor/issues/702) | Release blocker: counter-source regression | Software source-gap protection and real-library/HA regressions are implemented; reporter/deployed acceptance remains. Source withholding is an accepted limitation; historic statistics are not rewritten. |
| [#691](https://github.com/joyfulhouse/eg4_web_monitor/issues/691) | Metadata-I/O acceptance met | Independent review and green CI precede the authorized deployed download without blocking warnings. Identity/configuration are preserved. The separate full-download redaction defect remains under #697. |
| [#697](https://github.com/joyfulhouse/eg4_web_monitor/issues/697) | Release blocker: diagnostics redaction | Source fix at `c006150eeef0486db30e2c986dba9415b7e0e644` covers the actual HA wrapper and state-preserving Repairs migration. Production still uses the earlier candidate; the required authorized private full-download check remains open. See the diagnostics owner for the exact privacy boundary. |
| [#692](https://github.com/joyfulhouse/eg4_web_monitor/issues/692) | Resolved in merged #695 | Software acceptance covers initial/late discovery, stable registry identity and status-based inactive/active countdowns. Authorized October 25 candidate startup preserves the two existing IDs, reports zero while inactive and emits no duplicate-ID startup warnings; no quick charge was initiated. |
| [#693](https://github.com/joyfulhouse/eg4_web_monitor/issues/693) | Bounded investigation acceptance met; accepted limitation | Natural software link/control recovery and remaining evidence gaps are documented. Warnings/root cause are not fixed. The stricter deployment recovery/freshness gate remains open under #694; acquisition lineage remains under #666. |
| [#694](https://github.com/joyfulhouse/eg4_web_monitor/issues/694) | Release blocker: production soak | Natural local midnight, the full soak and fresh-local-acquisition recovery remain unverified. The narrower #693 investigation conclusion does not satisfy this deployment recovery gate. Full reconfiguration and rollback restoration remain untested. |
| [#666](https://github.com/joyfulhouse/eg4_web_monitor/issues/666) | Release blocker for LOCAL production rollover acceptance; accepted limitation for undated sources | Released b13 lineage adoption and the new capture path have software coverage. Natural production source continuity still needs qualified observations from deployed code; cloud/battery/chart counter-day and device reset timezone remain unproven. The data-semantics and diagnostics owners define the bounded capture contract. |
| [#619](https://github.com/joyfulhouse/eg4_web_monitor/issues/619) | Accepted limitation | Partial-group runtime works; incomplete cumulative sums remain unknown. Restart/outage/membership continuity needs a defined contract before emitting partial totals. |
| [#659](https://github.com/joyfulhouse/eg4_web_monitor/issues/659) | Accepted limitation, model/source scoped | Existing 12000XP balance-versus-portal discrepancy remains unresolved. Same-time cloud/local counter evidence is required; recognition is fixed separately. No source substitution or statistics repair is justified. |
| [#658](https://github.com/joyfulhouse/eg4_web_monitor/issues/658) | Future work | Generator-energy feature requires nonzero producer/chart evidence, units and leg semantics; persistence is separate. Zeros do not establish a mapping. |
| [#176](https://github.com/joyfulhouse/eg4_web_monitor/issues/176) | Accepted limitation | Read-only direct bridge shipped; identity/fallback/protocol acceptance remains. Master per-pack SOC/capacity remain withheld pending deliberate complete physical inventory and consumer validation. |
| [#574](https://github.com/joyfulhouse/eg4_web_monitor/issues/574) | Accepted limitation | Cell display precision shipped without native scaling changes. Master topology/serial/balance acceptance remains; bank aggregates must not become per-pack values. Existing passive captures need not be repeated. |
| [#668](https://github.com/joyfulhouse/eg4_web_monitor/issues/668) | Accepted limitation, firmware scoped | Preserve rejection cause/rollback and targeted guidance. No universal start/stop inequality, new LXP H160 write, or register rerouting is established. |
| [#612](https://github.com/joyfulhouse/eg4_web_monitor/issues/612) | Accepted limitation: reporter acceptance | Released code-20/2102 discovery has real-library consumer regressions. Reporter confirmation and model-specific writable semantics remain distinct. |
| [#617](https://github.com/joyfulhouse/eg4_web_monitor/issues/617) | Future work | Exact vendor PV priority/start/low-SOC labels, units and family semantics are required. A stored value of 65 does not justify expanding a cross-family write range. |
| [#626](https://github.com/joyfulhouse/eg4_web_monitor/issues/626) | Future work | Saved vendor write-path evidence, units and range are missing. An AI-suggested H99 mapping cannot justify a new write control. |
| [#623](https://github.com/joyfulhouse/eg4_web_monitor/issues/623) | Future work / reporter confirmation | Existing disabled-by-default Grid Always On may cover the shortcut. Confirm semantics before adding a duplicate control. |
| [#670](https://github.com/joyfulhouse/eg4_web_monitor/issues/670) | Accepted limitation | GridBOSS SOC/voltage threshold effectiveness remains unproven. H179 and ACK/readback do not establish switching semantics; mode-specific live evidence requires separate authorization. |

## Library acceptance and release scope

| Issue | Classification | Remaining boundary |
|---|---|---|
| [#389](https://github.com/joyfulhouse/pylxpweb/issues/389) | Resolved in published b14 and integration source | The authorized b14 artifact is independently verified and both integration pins select it. Production remains on b13 until a separately authorized deployment; no hardware root-cause fix is implied. |
| [#396](https://github.com/joyfulhouse/pylxpweb/issues/396) | Release blocker for the library validation/publication contract | Source-specific history, corruption bounds, delayed responses, midnight and MID behavior need a separate fix. Integration #702 bounds inverter/group publication but does not repair this contract or establish MID source equivalence. |
| [#384](https://github.com/joyfulhouse/pylxpweb/issues/384) | Accepted limitation | Decoder correction is published in b13. Integration master suppression remains until deliberate complete-inventory opt-in and validation; responding configured units do not establish physical completeness. |
| [#363](https://github.com/joyfulhouse/pylxpweb/issues/363) | Future work | Shared battery `unit_factory` awaits a consumer. Owned battery transport remains supported. Borrowed ownership/memoization and link-error-only recycling are required if implemented. |
| [#350](https://github.com/joyfulhouse/pylxpweb/issues/350) | Accepted limitation for independent connections; host-conflict fix tracked separately | Per-connection locks do not coordinate the physical endpoint or other applications. Exclusive gateways need host scheduling/ownership; a shared-link conflict must not silently create an independent link. |
| [#345](https://github.com/joyfulhouse/pylxpweb/issues/345) | Accepted limitation | Retain owned-link close-completion workaround until a released public upstream contract and supported-version tests justify removal. |
| [#344](https://github.com/joyfulhouse/pylxpweb/issues/344) | Future work | Recheck private layout before future tmodbus/backend changes. Version availability alone is not runtime compatibility. |
| [#189](https://github.com/joyfulhouse/pylxpweb/issues/189) | Accepted limitation | Retain aioresponses compatibility shim while released response construction omits `stream_writer`. |

The host conflict fix preserves HA's ownership rejection as a
`TransportConnectionError` chained to the original cause, without calling the
owned fallback. It allows retry after the conflicting owner/settings clear.
These source claims are `verified-against-code` at the front-matter integration
pin (`ha_modbus.py` -> `build_shared_unit_factory`, `tests/test_ha_modbus.py`).
This addresses one concrete host path within #350, not independent-connection
scheduling. No library release or integration dependency change is required for
these fixes. No issue with outstanding stated acceptance is closed by this report.

## Next authorized production step

The [deployment and rollback plan](../../docs/production/final-release-acceptance-plan-2026-10-23.md)
defines a candidate-only overlay, fresh backup, identity/redaction checks and
conditional rollback. The exact candidate is deployed; the one initial restart
is complete. Continue passive acceptance and address #697; the conditional
rollback authorization remains available if needed. The new privacy/evidence/b14
candidate needs its own prepared deployment and explicit restart authorization.
Final integration release publication remains separately unauthorized.
