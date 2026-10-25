---
canonical-for:
  - "October 2026 final-release preparation issue classification and acceptance gaps"
sources:
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/691
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/692
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/693
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/694
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/666
  - docs/production/final-release-acceptance-plan-2026-10-23.md
  - docs/production/final-release-preparation-2026-10-23.json
  - docs/production/release-preflight-2026-10-25.json
  - custom_components/eg4_web_monitor/ha_modbus.py
  - tests/test_ha_modbus.py
  - tests/test_sensor_entities.py
  - tests/test_energy_provenance_adoption.py
  - tests/test_energy_guard_restore.py
verified-against:
  eg4_web_monitor: 77e6c8652d46042e2a919c8e461ddd2c10724c3a
  pylxpweb: cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b
last-verified: 2026-10-25
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

## October 25 continuation

The [read-only preflight record](../../docs/production/release-preflight-2026-10-25.json)
owns the fresh observations and validation results. Upstream integration main is
`77e6c8652d46042e2a919c8e461ddd2c10724c3a` after #695; library main remains
`cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b`. No PRs were open when checked.
Unlike the October 23 preparation session below, authenticated API and existing
SSH access worked. Production reports HA 2026.10.3 and released b13. All 81
installed component files match published beta.21, so neither #690 nor #695 is
deployed. These are dated observations, `asserted-unverified` under the wiki
legend, not hardware-toggle evidence.

The entry is loaded. The new registry/state capture has the same aggregate
counts as the prior smoke test, but does not establish identity equality across
the two captures or transport health. Classification distinguishes inactive
countdowns, button states and explicit AC-couple disabled sentinels from missing
measurements. All unavailable states carry HA's `restored` attribute; none is
attributed to the dongle on count evidence alone. Registry entries were not
removed or changed.

The diagnostics request reproduced the metadata blocking warnings on installed
beta.21. Historical logs contain dongle connection timeouts and host-unreachable
errors. Recorder history spanning a natural local midnight shows numeric daily
resets. Neither source establishes acquisition freshness or recovery, and the
history lacks per-field contributor lineage. Diagnostics replaces acquisition
datetimes with placeholders; the [diagnostics owner](../10-integration/diagnostics-repairs.md)
owns that serialization limitation. Thus #691, #693, #694 and #666 remain release
blockers under the scope below. A 24-hour candidate soak has not occurred.

#692 is closed upstream by #695: its acceptance explicitly permits mocked
active/inactive behavior, and the merged tests also cover real HA startup and
registry identity. This does not claim that patched production startup has been
observed. All other issue classifications below remain the proposed scope;
no outstanding hardware/reporter acceptance was closed in this continuation.

The exact existing-main runtime candidate and archive digest are recorded in
the preflight artifact. Its runtime delta from beta.21 is limited to the three
files in the [deployment plan](../../docs/production/final-release-acceptance-plan-2026-10-23.md).
The old rollback files remain readable, but they preserve beta.20; a fresh
beta.21 backup and explicit deployment/restart authorization are still required.
No production mutation or release publication occurred.

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

Each classification is a release judgment (`inferred`) from the linked issue and
its acceptance comments. "Accepted limitation" means retained, explicitly
bounded behavior in this proposed release scope; it does not close the issue or
claim missing hardware acceptance. New evidence can change the classification.

| Issue | Classification | Remaining boundary |
|---|---|---|
| [#691](https://github.com/joyfulhouse/eg4_web_monitor/issues/691) | Release blocker: production acceptance | Executor/redaction fix merged in #690; authorized deployed diagnostics must complete without the metadata blocking warnings and preserve identity/redaction. Source tests alone do not meet this issue's acceptance. |
| [#692](https://github.com/joyfulhouse/eg4_web_monitor/issues/692) | Resolved in merged #695 | Duplicate generic/specialized countdown producers reproduced and removed. Software acceptance covers initial/late discovery, stable registry identity and status-based inactive/active countdowns without activating hardware. Production still runs unpatched beta.21 as of the October 25 preflight. |
| [#693](https://github.com/joyfulhouse/eg4_web_monitor/issues/693) | Release blocker: production characterization | Recurring dongle warnings need timestamps, duration/freshness/fallback correlation and natural recovery if it occurs. Neither a network root cause nor a library regression is established. |
| [#694](https://github.com/joyfulhouse/eg4_web_monitor/issues/694) | Release blocker: production soak | Natural local midnight and longer passive observations remain unverified. Full reconfiguration and rollback restoration remain untested and must stay explicit. |
| [#666](https://github.com/joyfulhouse/eg4_web_monitor/issues/666) | Release blocker for LOCAL production rollover acceptance; accepted limitation for undated sources | Released b13 lineage adoption is covered by software regressions. Natural production source continuity is outstanding; cloud/battery/chart counter-day and device reset timezone remain unproven. |
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
conditional rollback. Its status is unexecuted. Fix the source commit and archive
digest before requesting approval. Deployment/restarts and eventual publication
are separate authorizations.
