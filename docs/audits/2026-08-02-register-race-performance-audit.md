# Register Mapping, Race, Lifecycle, and Performance Audit

Date: 2026-08-02

Status: read-only audit; no implementation changes

Tracking issue: `eg4-vy1b`

## Executive summary

This audit found four classes of work that should be kept separate:

1. **Released integration correctness defects.** The highest-priority items are a
   mixed Modbus TCP/serial poll starvation bug, unsafe parallel-group registry
   migration, number entities whose optimistic retention never receives its
   production convergence/TTL callback, shared-physical-endpoint serialization
   gaps, and concurrent classic schedule writes that can produce a time requested
   by neither caller.
2. **`pylxpweb` dependency defects.** Local Quick Charge performs an unlocked
   read/modify/write of shared register 233, FC16 accepts a malformed multi-value
   read-style ACK as success, authentication renewal is not single-flight, and
   generic register-120 decoding treats compound fields as unrelated single bits.
3. **Pre-merge `#511` breaker defects.** The current in-flight breaker can remain
   half-open after a neutral store result, does not cover battery-backup and
   firmware-status side fetches, and constructs the PV-lifetime `gather()` before
   checking whether the breaker is open. A separate concurrent-success defect was
   reproduced in the staged snapshot and then fixed by an unstaged change while
   this audit was running.
4. **Mapping opportunities and portability traps.** More data and bits can be
   surfaced, but the ant0nkr map must not be copied wholesale. The strongest
   writable candidates are H110 bits 7, 10, and 15 and H233 bit 12, with explicit
   family gates and disabled-by-default UX. The safest immediate mapping work is
   read-only: I67 battery temperature is already in coordinator data but has no
   entity description, while I10, I25, I68, I69-I70, I77, and selected battery
   slot diagnostics already have credible local definitions.

The architectural comparison is not “upstream has more, therefore copy it.” The
upstream integration scans a broad LuxPower-oriented register plane and exposes
many controls without EG4 family gates. This project is more conservative and has
substantially better in-process RMW safety, but its higher feature depth creates
more lifecycle, cache, cloud-fanout, and entity-churn surfaces.

### Immediate decisions

- Do not port H22 bit 15 as Feed-In Grid. EG4 evidence pins Feed-In to H21 bit 15;
  H22 is PV start voltage on supported EG4 hardware.
- Do not treat upstream percentage encodings for H66/H74/H82/H103 as authoritative
  on EG4. Current EG4 evidence uses 100 W/deci-kW encodings.
- Do not expose H120 through generic named-parameter decoding until the compound
  field model is corrected and tested.
- Do not ship H179 or H233 placeholder bits from protocol lineage alone.
- Fix the P1/P2 correctness and pre-merge breaker findings before expanding the
  writable surface.
- Prefer read-only diagnostics when a semantic mapping is credible but write
  safety or family applicability is not proven.

## Reproducibility and source authority

| Source | Revision used | Role |
| --- | --- | --- |
| `eg4_web_monitor` clean baseline | `0934083371456269f8a37f05c07b2562e1a0a64f` | Released integration baseline and isolated documentation branch |
| Main working-tree index | `coordinator_mixins.py` blob `6b59088e851c20273f9bf7b7c8f0e102d6a7a25e`; `test_sidefetch_breaker.py` blob `5850297a94208f8a2b58e592adac36113b2e0660` | In-flight `#511` snapshot initially scanned |
| Main working tree after concurrent review edits | `coordinator_mixins.py` blob `bc30a11e65c1c49978f991ec9cf81fc276c3a886`; `test_sidefetch_breaker.py` blob `c1e616f7562201de0bcc9209d36dd44087cf98c7` | Moving snapshot used to distinguish fixed vs outstanding breaker findings |
| `pylxpweb` | `ee16a6aff99d4366b7026a55e606656f21a932ad`, tag `v0.9.39b6` | Canonical runtime parser/transport dependency; matches manifest floor `pylxpweb>=0.9.39b6` |
| `ant0nkr/luxpower-ha-integration` | `d3d101498bc2796d6d57142b0e8d7351fdd3cab6` | Independent LuxPower-oriented comparison oracle |

The upstream comparison was pinned to
[`d3d1014`](https://github.com/ant0nkr/luxpower-ha-integration/tree/d3d101498bc2796d6d57142b0e8d7351fdd3cab6),
not a moving default branch. The dependency was inspected from the exact local
source tag used by the integration, not from stale environment package metadata.

### Moving-worktree rule

The user's pre-existing dirty tree was never edited by this audit. A separate
worktree and branch were used for this document. While scans were running, another
process added `_sidefetch_open_until = None` to `_sidefetch_note_reachable()` and
added a regression test. Therefore:

- the concurrent-success/open-deadline race is a **confirmed defect in the staged
  `6b59088e` snapshot and fixed in current unstaged `bc30a11e`**;
- neutral-result half-open state, eager lifetime `gather()`, and unwrapped
  supplemental paths remain present in `bc30a11e`;
- released baseline findings are independent of the in-flight `#511` diff.

## Methodology

Twenty-six independent external scan processes were launched, followed by three
in-session validation lanes. One long-running plan process was stopped after its
subchecks had completed; its lifecycle result was retained. No scan was allowed to
edit production files.

| Lanes | Focus |
| --- | --- |
| 1-4 | Transport framing, sensor/input maps, holding/control bits, write/RMW races |
| 5-8 | Lifecycle, shared state, recovery/breaker behavior, performance |
| 9-12 | Entity migration, test quality, numeric edges, architecture diff |
| 13-16 | Dependency mapping, dependency transport, dependency writes, dependency read plan |
| 17-26 | Full-output adversarial repeats of protocol, input map, control bits, write races, lifecycle, breaker, performance, migration, tests, and architecture |
| 27-29 | Mapping reconciliation, race/performance reconciliation, deterministic validation and full quality gates |

Findings were retained only after source tracing, an existing test, a deterministic
probe, or independent agreement between lanes. “Confirmed” means the behavior was
directly reproduced or is an unavoidable result of the shown control flow.
“High-confidence” means the control flow is clear but the full production
interleaving was not executed. “Verification target” means evidence is conflicting
or hardware-dependent.

Severity convention:

- **P1 / High:** can silently write or present materially wrong device state,
  starve a device indefinitely, corrupt registry continuity, or defeat a release
  blocker under realistic concurrency.
- **P2 / Medium:** bounded stale state, partial writes, setup leaks, substantial
  request amplification, or dormant library hazards.
- **P3 / Low:** metadata, documentation, bounded startup latency, or low-frequency
  operational friction.

## Finding index

| ID | Severity | Confidence | Scope | Summary |
| --- | --- | --- | --- | --- |
| INT-01 | P1 | Confirmed/reproduced | Released integration | Mixed Modbus TCP and serial share one poll timestamp; the later type is starved every cycle |
| INT-02 | P1 | Confirmed control flow | Released integration | Parallel-group migration guesses pairings and deletes the old device even without a match |
| INT-03 | P1 | Confirmed/reproduced | Released integration | Number entities register `async_write_ha_state`, bypassing optimistic convergence/TTL handling |
| ARC-01 | P1 | High | Integration + dependency | Shared physical endpoint grouping serializes poll-vs-poll only, not writes/background operations across transport instances |
| INT-04 | P1 | Confirmed/reproduced | Released integration | Two classic schedule writes can interleave into a time requested by neither caller |
| DEP-01 | P1 | Confirmed/reproduced | `pylxpweb` | Quick Charge performs an unlocked RMW of shared H233 and can erase sibling bits |
| DEP-02 | P1/P2 | Confirmed/reproduced | `pylxpweb` | Expired authentication is renewed independently by every concurrent request |
| BRK-01 | P1 pre-merge | Confirmed/reproduced | Dirty `#511` | A neutral half-open probe returns with `_sidefetch_half_open=True` |
| BRK-02 | P1 pre-merge | Confirmed | Dirty `#511` | Battery-backup and firmware status bypass the shared breaker; battery backup has no outer timeout |
| BRK-03 | P2 pre-merge | Confirmed | Dirty `#511` | PV lifetime `gather()` schedules children before an open-breaker check |
| BRK-04 | Fixed during audit | Confirmed/reproduced | Dirty `#511` | In-flight success formerly failed to clear a sibling-opened deadline; current unstaged tree fixes it |
| INT-05 | P2 | High | Released integration | Failed initial refresh/platform setup has no coordinator/client/transport unwind path |
| INT-06 | P2 | High | Released integration | Persistent integration-side processing errors can carry stale device data as available |
| INT-07 | P2 | Confirmed | Released integration | Static-phase follow-up refresh is an untracked task and can race unload |
| INT-08 | P2/P3 | Confirmed/reproduced | Released integration | Five throttle sites use monotonic `0.0` as “never,” suppressing first work on young hosts |
| INT-09 | P2 | High | Released integration | Control platforms have setup-time family/feature gates but no late registration |
| INT-10 | P2 | Confirmed | Released integration | Parallel-group suggested entity IDs omit the group identity |
| INT-11 | P2 | High | Released integration | Main parameter cache seeds can be overwritten by an in-flight raw parameter poll |
| INT-12 | P2 | High | Released integration | Battery-mode and other multi-call logical writes have no per-device transaction lock |
| MAP-01 | P2 | Confirmed | Released integration | I67 battery temperature reaches coordinator data but lacks an entity description |
| DEP-03 | P2 | Confirmed/reproduced | `pylxpweb` | FC16 accepts a wrong multi-value read-style ACK as success |
| DEP-04 | P2 dormant/High if used | Confirmed | `pylxpweb` | H120 compound fields are decoded/written as consecutive one-bit fields |
| DEP-05 | P2 | High | `pylxpweb` | Dongle uses one `read(4096)` rather than length-framed assembly |
| DEP-06 | P2/P3 | Confirmed metadata | `pylxpweb` | Dongle returns `MODBUS_CAPABILITIES`, incorrectly advertising concurrent reads |
| PERF-01 | P2 | Confirmed | Integration | Primary cloud refresh bypasses the integration's semaphore and fans out per inverter |
| PERF-02 | P2 | Confirmed | Integration + dependency | Parameter verification forces runtime, energy, battery, and parameter refreshes |
| PERF-03 | P2 | Confirmed | Integration | Missing-parameter tasks can overlap, and firmware status duplicates an account-wide request per inverter |
| PERF-04 | P2/P3 | Confirmed architecture | Integration | Fastest-transport ticks notify the full entity/discovery graph even when slower transports are carried forward |
| CFG-01 | P2 | High | Released integration | The same plant can be configured in HTTP and HYBRID modes with two coordinators |

## Detailed root-cause analysis

### INT-01 — mixed Modbus TCP/serial poll starvation

**Trigger:** one LOCAL or HYBRID config entry contains at least one
`modbus_tcp` and one `modbus_serial` inverter.

**Root cause:** `_should_poll_transport()` maps both types to
`_last_modbus_poll`. `_async_update_local_data()` correctly computes one gate per
distinct transport type, but the first type updates the shared timestamp before
the second type checks it. Stable config iteration makes the same type win every
cycle.

**Observed:** a deterministic probe at monotonic times 100, 105, and 110 seconds
returned `tcp_due=True, serial_due=False` each time. Skipped devices are populated
from cached/static data and marked available, so the starvation can look healthy.

**Expected:** independent timestamps per independently gated type, or a single
shared “Modbus due” decision applied to both types in the same cycle.

**Evidence:** `coordinator.py::_should_poll_transport()` and
`coordinator_local.py` around the `transport_types_seen`/`pollable_types` loop.
Existing coverage tests multiple devices of one TCP type, not TCP plus serial.

### INT-02 — unsafe and destructive parallel-group migration

**Trigger:** an older installation has one or more serial-derived
`parallel_group_*` registry devices, and the first refresh yields new name-derived
group IDs or temporarily yields none.

**Root cause:** setup snapshots old IDs, then pairs each stale ID to the first
lexicographically unclaimed new ID. It does not correlate members, master serial,
or group name. After the optional match block, it removes the old device
unconditionally.

**Impact:** with two groups, histories can be swapped. With no authoritative new
group, the old registry device is still deleted. This is a migration-time registry
continuity/data-association defect, not merely cosmetic cleanup.

**Evidence:** `custom_components/eg4_web_monitor/__init__.py` lines 639-647 and
710-767 in the audited snapshot. No migration matrix tests were found.

### INT-03 — number optimistic retention has no production cleanup callback

**Trigger:** a number write is acknowledged and its post-write refresh fails or is
intentionally skipped, arming bounded optimistic retention.

**Root cause:** `EG4BaseNumberEntity.async_added_to_hass()` registers
`self.async_write_ha_state` directly and never calls
`super().async_added_to_hass()`. `EG4OptimisticEntity` inherits
`CoordinatorEntity`, whose listener would dispatch
`_handle_coordinator_update()`. That overridden handler is the only path that
clears on convergence or the five-minute TTL.

**Observed:** AST/callback probes show no `super()` call and the registered
callback is the state writer. Existing retention tests manually invoke
`_handle_coordinator_update()`, so they test the algorithm but not production
wiring.

**Impact:** a number can display a device-rejected or superseded optimistic value
indefinitely. This keeps the still-open `#379` follow-up materially relevant.

### ARC-01 — endpoint serialization does not cover all operations

**Trigger:** multiple logical devices share one single-slot dongle or RS485
adapter; one device is polled while another is written or performs background
parameter/drain work.

**Root cause:** coordinator endpoint grouping serializes poll-vs-poll. The
dependency creates a separate transport object and `_op_lock` per device. Direct
writes, deferred parameter loads, and buffer drains do not acquire a coordinator
endpoint lock shared by all devices on the physical endpoint.

**Impact:** a poll for device A can overlap a write/read sequence for device B on
hardware documented as one-request-at-a-time. Per-transport frame attribution and
locks do not protect across instances.

**Confidence note:** the object/lock topology is confirmed; a hardware or fake
single-slot endpoint interleaving test is still needed before choosing the lock
ownership design.

### INT-04 — classic schedule writes can synthesize an unintended time

**Trigger:** two callers update the same classic cloud schedule boundary at nearly
the same time.

**Root cause:** classic schedules write hour and minute in separate cloud calls.
There is no per-serial/boundary logical transaction lock, and platform parallelism
is three.

**Observed interleaving:** A requests 08:15; B requests 20:45. The order A-hour,
B-hour, B-minute, A-minute leaves 20:15. Single-call partial-failure convergence
does not prevent two successful calls from interleaving.

**Scope:** `writeTime` families use one atomic API call and are not affected.

### DEP-01 — Quick Charge loses H233 sibling bits

**Trigger:** local Quick Charge start/stop overlaps another H233 control, such as
battery backup, maintenance, weekly mode, or a future sporadic-charge switch.

**Root cause:** `BaseInverter.write_transport_bit()` and
`_enable_quick_charge_local()` call `read_parameters()` and later
`write_parameters()` as separate high-level operations. The correct named
parameter RMW path holds the transport operation lock across both, but Quick
Charge bypasses it.

**Observed:** starting with H233=`0x1000`, a sibling set bit 1 after the Quick
Charge read. Quick Charge then wrote its stale snapshot plus bit 0. Final H233 was
`0x1001`; the merged expected state was `0x1003`.

**Impact:** silent durable device-state loss. Adding more H233 controls would make
the race more likely unless this is fixed first.

### DEP-02 — authentication renewal thundering herd

**Trigger:** concurrent cloud requests see an expired session.

**Root cause:** `_ensure_authenticated()` checks expiry and calls `login()` with no
shared lock or in-flight task. The integration and dependency both use broad
`gather()` fanout.

**Observed:** ten concurrent non-network probes resulted in ten concurrent login
calls before any completed.

**Impact:** avoidable authentication traffic and concurrent mutation of shared
cookies/session metadata. A single-flight renewal primitive should live in the
client, not at every integration call site.

### BRK-01 — neutral half-open result leaves the state machine armed

**Trigger:** breaker cooldown expires and the probe is a cloud-store getter that
returns its all-`None` schema after swallowed per-range errors, or another
classifier returns `None`.

**Root cause:** `_breakered_cloud_call()` sets `_sidefetch_half_open=True` before
the call. True and False verdicts leave half-open through their bookkeeping;
`None` executes neither path.

**Observed:** the deterministic result was
`half_open_after_neutral=True, open_until=None, failures=0`.

**Impact:** subsequent calls run as though closed, but the next single connectivity
failure is treated as a failed half-open probe and reopens the breaker for five
minutes. The state is neither closed nor meaningfully probing.

### BRK-02 — supplemental paths outside the breaker

Battery-backup status calls `get_battery_backup_status()` directly every 30
seconds in cloud-only mode. It has neither `_breakered_cloud_call()` nor an outer
`wait_for()`, so dependency backoff and HTTP timeout costs remain even while other
supplemental calls are paused. Firmware progress is also polled in per-inverter
processing outside the breaker, and the underlying status request is account-wide.

The `#511` acceptance claim should enumerate actual call sites. “All supplemental
cloud fetches” is not true in the audited snapshot.

### BRK-03 — eager PV-lifetime gather defeats skip-before-start

Python evaluates call arguments before entering `_breakered_cloud_call()`.
Constructing `asyncio.gather(...)` as the argument immediately schedules child
coroutines. The open breaker then cancels the gather, which is necessary cleanup
but not proof that no request/backoff work began.

The daily PV path passes a bare coroutine and can be closed before it starts; the
lifetime path has different semantics. Existing tests assert cancellation but do
not assert that production children never started.

### BRK-04 — concurrent success/open deadline race, fixed during audit

The staged snapshot reset failure count and half-open state on reachability but did
not clear `_sidefetch_open_until`. An already-admitted success completing after a
sibling opened/reopened the breaker left the deadline active for five minutes.
This was reproduced. The current unstaged tree explicitly clears the deadline and
adds a regression test, so it is not an outstanding item in that newer snapshot.

### INT-05 — failed setup lacks unwind

Coordinator construction registers the HA-stop listener before the first refresh.
HYBRID setup can also attach transports or start background state. `runtime_data`
is assigned only after first refresh, and platform setup is not wrapped in a
general cleanup block. `async_unload_entry()` obtains the coordinator only through
`entry.runtime_data`.

A first-refresh exception or platform-setup failure can therefore leave listener,
transport, task, or HTTP-client state without the normal shutdown path. A failure
injection test should define the exact leaked resources and the required idempotent
unwind contract.

### INT-06 — processing failures can preserve stale data as available

LOCAL processing pre-populates the new result with prior device dictionaries.
Per-device exceptions mark a side availability map false, but the partial-success
path logs and returns. Error decoration is tied mainly to dependency link-down
state; a persistent integration-side mapping/processing exception after a
successful transport read need not advance that link-health counter.

The result can be a stale carried device without an error marker, and a parallel
aggregate may consume it. This is high-confidence control-flow analysis; retain a
failure-injection test before choosing whether to mark the device unavailable,
preserve values with explicit staleness, or taint only dependent aggregates.

### INT-07 — untracked static-phase refresh

The first LOCAL static phase calls
`hass.async_create_task(self.async_request_refresh())` without adding the task to
`_background_tasks` or attaching exception callbacks. Other background tasks in
the coordinator are tracked and cancelled during shutdown.

Immediate reload/unload can therefore race this refresh against transport
disconnect. The likely impact is log noise or a reconnect during reload, but the
lifecycle contract is inconsistent and untested.

### INT-08 — monotonic-zero sentinel family

The following paths use `0.0` as both a real monotonic timestamp and “never”:

- `_should_poll_transport()`;
- degraded HTTP cache busting;
- first Quick Charge status fetch;
- first battery-backup status fetch;
- parallel-group cloud-energy retry after a warm-cache failure.

On a host whose uptime is below the interval, first-ever work is classified as
recent. A first Modbus poll at monotonic 1.0 seconds returned False in the
deterministic probe. Adjacent cloud-store code already documents and correctly
uses `None` for this exact bug class.

The aggregate impact is bounded startup delay, except that the same shared-clock
design also participates in INT-01's permanent mixed-type starvation.

### INT-09 — setup-time control gates do not converge when features arrive late

Sensors have late registration for batteries, smart ports, and resolved feature
keys. Switch, number, select, and time platforms perform one-shot setup. LOCAL
feature and parameter discovery can complete after static entity setup.

The result can be missing valid controls or inert family-inapplicable controls
until reload. Existing tests verify the gate outcome for a prepared snapshot, not
unknown-to-known feature transitions.

### INT-10 — parallel-group suggested entity-ID collisions

Parallel-group sensors use unique IDs containing `parallel_group_a`,
`parallel_group_b`, and so on, but their suggested entity ID is only
`sensor.eg4_parallel_group_{sensor_key}`. Two groups therefore collide and depend
on Home Assistant's `_2` suffix assignment. Unique identity remains safe, but
dashboards and human-facing entity IDs are ambiguous and can reshuffle.

### INT-11 — parameter seed vs in-flight poll

`note_parameters_written()` mutates the current coordinator data. A raw LOCAL
parameter poll bypasses the dependency's parameter write-generation guard and can
later publish a snapshot started before the write. Cloud-only AC Couple/Smart Load
stores already use an out-of-band seed registry precisely to survive this class.

This is a cache/UI rollback risk rather than device-level bit loss. Add a
deterministic paused-poll test before selecting a generation counter or persistent
seed overlay.

### INT-12 — higher-level multi-call writes are not transactions

Low-level named bitfield RMW is correctly serialized for one transport instance.
That does not make a logical operation consisting of multiple named writes atomic.
Battery control mode writes charge and discharge regime bits separately. Classic
schedules write hour/minute separately. Concurrent callers or a mid-operation
failure can leave a mixed configuration. Existing code handles several partial
failure cases honestly, but no per-device logical write lock prevents two
successful operations from interleaving.

### MAP-01 — battery temperature is mapped but cannot become an entity

I67 is decoded by `pylxpweb`, normalized for the `0x7f` no-reading sentinel, and
copied to coordinator key `battery_temperature`. No matching entry exists in
`const/sensors/inverter.py`, so normal entity creation drops it. Documentation
already refers to the entity. This is the clearest immediate read-only mapping
bug.

### DEP-03 — FC16 multi-value ACK bypass

For FC16, `_write_holding_registers()` rejects an empty ACK and rejects a wrong
count only when `len(ack) == 1`. A read-style response parsed into two or more
values skips the condition and returns True regardless of contents.

The deterministic probe supplied `[0x9999, 0x8888]` as the parsed ACK for a
two-register H233/H234 write; the method returned True. Real 16-byte count ACKs
are validated correctly. The missing case is the explicitly supported fallback
for firmware that responds in read-frame layout.

### DEP-04 — H120 compound fields are structurally mis-modeled

H120 contains bit 0 plus compound fields at bits 1-3 and 4-5, followed by bits 6
and 7. The generic `REGISTER_TO_PARAM_KEYS[120]` lists seven names as if each
occupied one bit. `MULTI_BIT_FIELDS` contains only MIDBOX port fields, so generic
read/write uses list index as bit index. A dedicated inverter API has the correct
`0x0e` mask for AC charge type, proving the generic map is inconsistent with the
same codebase.

The integration currently exposes no H120 entity, limiting present impact. Any
generic named read or future entity would be wrong; a named write with values
greater than one is unsafe.

### DEP-05/DEP-06 — remaining transport hazards

- Dongle receive uses one `StreamReader.read(4096)`. TCP may return a partial
  prefix; the code treats it as truncated and retries rather than assembling the
  advertised frame length. The upstream implementation has explicit length-based
  recovery, while this dependency has stronger CRC/serial/function/register
  attribution.
- Waveshare compatibility disables Modbus TCP transaction-ID validation and
  substitutes the expected ID. Per-instance locking limits the risk, but stale
  gateway data has weaker attribution than the dongle protocol path.
- Plain non-coalesced input short reads can publish partial dictionaries; holding
  and coalesced paths are stricter. This is partly an intentional firmware
  compatibility tradeoff.
- Public `DongleTransport.disconnect()` is not serialized on the connect lock.
- `DongleTransport.capabilities` returns `MODBUS_CAPABILITIES`, advertising
  `supports_concurrent_reads=True`, despite a dedicated
  `DONGLE_CAPABILITIES=False`. There is no current runtime consumer, so this is a
  dormant metadata/test defect.

## Register-map comparison

### Inventory and architectural shape

The raw counts are not an apples-to-apples measure of correctness:

| Surface | ant0nkr reference | EG4 stack |
| --- | ---: | ---: |
| Ordinary sensor descriptions | 185 | 335 integration sensor descriptions across inverter, GridBOSS, battery, station, and derived surfaces |
| Battery sensor descriptions | 18 | Serial-aware battery/bank model in integration and dependency |
| Number descriptions | 335 | Curated, family-gated control set |
| Switch descriptions | 28 | Curated, family-gated control set |
| Select descriptions | 17 | Curated, family-gated control set |
| Time descriptions | 144 | Daily schedule abstractions; weekly plane not wired |
| Direct holding mappings | 531 | 157 canonical holding definitions plus runtime-safe transport maps |
| Direct input mappings | 150 | 143 canonical input definitions |

Canonical direct input coverage is I0, I1-I5, I7-I39, I40-I63, I64-I75,
I77, I80-I113, I121-I139, I153, I170-I173, I190-I191, I193-I204, I210,
and I217-I232. The reference-only claims are I6, I71, I114, I120, I139,
I174, I176-I189, I192, I205-I209, and I214-I216. Numeric overlap does not
imply semantic agreement; several of those claims are explicitly rejected below.

Canonical holding coverage includes scalar H9, H10, H15, H16, H19, H20,
H22-H25, H27-H28, H59-H62, H64-H91, H99-H103, H105, H112, H116,
H118-H120, H125, H144-H169, H176-H177, H190, H194-H198, H202,
H206-H208, H218-H219, H227-H228, and H232-H234; bitfields H21, H26,
H110, H179, and H233; plus separately configured daily schedules. Broad
reference-only holding ranges are not automatically gaps: many are unverified,
family-specific, compound, protection-related, or weekly-layout-dependent.

The reference is a local, register-centric, single-inverter integration. It polls
large input and holding spans and instantiates entities for a broad LuxPower
protocol family. The EG4 stack supports cloud, local, and hybrid operation;
multiple inverter families; parallel groups; GridBOSS/MID; dynamic battery
identity; dedicated cloud-only stores; and firmware/history features. Its smaller
direct register table is often an intentional refusal to guess.

### Evidence hierarchy

Use the following authority order for any new mapping:

1. Live named-control or UI action correlated to raw before/after values on the
   target EG4 family, including restoration.
2. Current canonical `pylxpweb` definition plus an independent hardware capture or
   firmware/scanner observation.
3. Current canonical definition alone for read-only diagnostics with credible
   units and harmless failure mode.
4. ant0nkr/vendor protocol table as a family-specific hypothesis.

The current contract harness is valuable but not independent: the integration and
the harness ultimately resolve against the same `pylxpweb` tables. It catches
internal drift; it cannot prove that a consistently shared address, scale, or bit
is correct on hardware.

### Strong conflicts and hazards

| Address | ant0nkr/reference meaning | EG4/canonical meaning or evidence | Decision |
| --- | --- | --- | --- |
| H21/H22 b15 | Feed-In at H22 b15 | Live EG4 evidence and contract pin Feed-In to H21 b15; H22 is PV start voltage | Never port H22 b15 to EG4; wrong-register write can alter PV threshold |
| H26 | High grid-connect voltage | Canonical generic table treats lower bits as LSP flags, while scanner output also reports scalar voltage | Do not RMW individual bits until the scalar-vs-server-reinterpretation conflict is resolved |
| H59-H62 | Reactive command type, active %, reactive %, PF command | Canonical table currently describes Q/PV reactive modes and signed settings; dependency scanner agrees with reference naming | Treat canonical rows as suspect/dormant; require raw/UI correlation before exposure |
| H66/H74/H82/H103 | Percentage-oriented power/current limits | EG4 captures and current code use 100 W/deci-kW semantics | Reference entities are unsafe portability templates |
| H120 | Compound AC/discharge control fields | Generic runtime table lists consecutive one-bit names; dedicated API uses correct masks | Fix dependency model before any entity |
| H202 | Raw decivolts | Canonical metadata says volts/no scale while higher layers normalize | Runtime can be right while metadata is misleading; document normalization ownership |
| H206/H231 | Peak-shaving comments vary; reference exposes local setpoint | H206 period-1 deci-kW is live-verified; H232 is period 2; H231 is unknown | Correct local docs; do not revive H231 |
| I19 | Scale 0.001 labeled percent | Canonical handles encoded negative PF and exposes unitless ratio | Keep canonical behavior; reference unit is misleading |
| I64/I103/I104/I170 | Unsigned transform in several reference entities | Canonical marks signed temperature/reverse-flow fields | Do not port reference transforms |
| I72-I74 | Auto-test/current claims vary | EG4 live probes often return zero/garbage; integration derives PV current as P/V | Continue to suppress raw values |
| I114 | On-grid load | EG4 evidence indicates communication/version-related content | Not portable |
| I120 | Half-bus voltage | EG4 probes indicate packed version data | Not portable |
| I139 | Reactive power | EG4 probes look battery-bus-voltage-like | Not portable without family evidence |
| I153 | AC-couple power, upstream constants describe signed range | Both implementations currently decode unsigned | Verification target: capture negative/reverse flow before changing signedness |
| I174 | Switch/DIP state | EG4 probes resemble inverter count | Not portable |
| I176-I189, I192, I205-I209, I214-I216 | Three-phase/V23 diagnostics and flows | No global EG4 corroboration; several collide with other observed meanings | Family-specific research only |
| I210 | Remaining Quick Charge minutes | EG4 stack treats I210 as seconds; H234 is minutes | Keep EG4 behavior pending same-firmware countdown correlation; do not copy unit |
| Battery 5000/5002 | Appears to have a two-register base mismatch | Field offsets align at absolute addresses such as capacity 5003/current 5009/SOC 5010 | Not a bug |

### Read-only additions with the best evidence

These do not require importing an upstream address. They already exist in the
canonical dependency or current coordinator data.

| Register/data | Candidate | Confidence | Required guard or validation |
| --- | --- | --- | --- |
| I67 | Battery temperature entity | High; current mapping bug | Add entity description; preserve `0x7f -> unknown` normalization |
| I10 | Separate battery charge power | High mapping confidence | Decide product semantics vs signed net battery power; correct stale docs either way |
| I25 | Aggregate EPS apparent power | High | Avoid duplicating/confusing per-leg I131/I132; validate all supported phase layouts |
| I68 | Battery control temperature | Medium | Diagnostic, disabled by default; verify non-sentinel population |
| I69-I70 | 32-bit inverter running time | Medium/high | Correlate units/reset behavior to uptime before choosing device/state class |
| I77 | AC input type bits | Medium/high | Expose decoded enum/diagnostic rather than opaque integer |
| I113 | Parallel role/group fields | Medium | Diagnostic only; reuse the parser already used internally |
| Battery-slot current limit and voltage cutoff | Per-battery diagnostics | High mapping, variable population | Disabled by default; keep bank-level equivalents authoritative |

I108-I112 auxiliary temperature channels were zero on sampled EG4 units. They are
low-value until a model with populated readings is captured.

## Can more holding-register bits be mapped?

Yes, but “mapped” must distinguish read-only state, safe writable control, and a
protocol hypothesis.

### Tier A — strongest writable candidates after normal entity design

| Register/bit | Canonical name | Evidence | Guardrails |
| --- | --- | --- | --- |
| H110 b7 (`0x0080`) | `FUNC_BUZZER_EN` | Hardware-verified on 12000XP; reference corroborates | Family/capability matrix; disabled by default |
| H110 b10 (`0x0400`) | `FUNC_TAKE_LOAD_TOGETHER` | Live 18kPV raw toggle pin; reference corroborates | Initially gate to verified hybrid family; do not infer OFFGRID applicability |
| H110 b15 (`0x8000`) | `FUNC_BATTERY_ECO_EN` | Hardware-verified on 12000XP; reference Eco mode | Gate by verified family; disabled by default |
| H233 b12 (`0x1000`) | `FUNC_SPORADIC_CHARGE` | Web UI toggle correlated with raw 0/4096 | H233 is rejected on EG4_OFFGRID; capability/family gate is mandatory |

These are not authorization to implement in this audit. DEP-01 must be fixed before
adding another H233 writer.

### Tier B — useful read-only states, unsafe as casual writable switches

H21 bits 1-6, 8, and 12-14 have credible protocol names (over-frequency
derating, DRMS, LVRT, anti-islanding, neutral detection, soft start, seamless
switching, insulation monitoring, GFCI, and DCI). They are protection/grid-code
settings. If surfaced, prefer disabled-by-default diagnostic binary sensors. A
writable UX needs regulatory/family semantics and explicit warnings, not merely a
bit location.

H110 b0 (PV grid-off) and b2 (microgrid) have name agreement but weaker raw-toggle
provenance than Tier A. Capture each named UI/API control against raw H110 on every
intended family before local writes.

### Tier C — one hardware capture away from a local hypothesis

| Candidate | Suspected location | Why blocked |
| --- | --- | --- |
| On-Grid Always On | H179 b15 in reference | EG4 cloud name exists, but raw bit is intentionally unpinned |
| Smart Load Enable | H179 b13 in reference | Reference semantic may be Generator/Smart-Load selection rather than parent enable |
| Volt-Watt | H179 b4 | Cloud/canonical spelling differs; grid-code control |
| Generator peak shaving | H179 b8 | Family applicability and raw bit unproven |
| PV Arc | H179 b12 | Safety control; spelling and raw correlation unproven |
| AC Couple | H179 b11 | Already lineage-mapped, but a direct EG4 raw lockstep capture remains valuable |
| Battery maintenance | H233 b2 | Reference/canonical lineage only; runtime transport intentionally keeps placeholder |
| Weekly/working-mode enable | H233 b3 | Must be proven together with the actual weekly data plane |
| Over-frequency stop | H233 b10 | Protection semantics and raw bit unproven |

### Tier D — do not map as independent booleans

- H110 bits 5-6, 8-9, and 12-13 may be multi-bit CT/PVCT fields.
- H120 compound fields are currently structurally broken in generic decode.
- H179 CT direction, AFCI clear, RSD disable, and other momentary/safety fields
  need model-specific semantics and confirmation UX.
- H233 bits 4-9 may contain dry-contactor/CT-position compound fields.
- Any `FUNC_<register>_BIT<n>` placeholder is deliberately write-refused and must
  remain so.
- H251 WattNode/V23 direction/update fields are model-specific hypotheses.

### Weekly schedules are a research track, not a quick port

The reference exposes a large H500-H723 weekly schedule plane and a H233 bit-3
enable. The dependency contains schedule definitions that are not wired into the
runtime transport. Reference comments describe transposed/type-grouped reads and
per-day multi-register writes, while its entity implementation assumes a normal
contiguous cache and single writes. EG4 probes show different repeating patterns
around H720-H789 and partial mirrors from H600.

Do not expose the enable bit alone: changing daily/weekly mode without a proven,
round-trippable schedule plane can activate unread or stale device state. This
feature requires per-family captures, complete read/write layout, atomic mode
migration, bounds, time-zone behavior, and recovery tests.

## Source-of-truth drift

The dependency currently has at least three mapping layers:

- canonical `registers/inverter_holding.py` / `inverter_input.py` metadata;
- runtime-safe `constants/registers.py::REGISTER_TO_PARAM_KEYS` with placeholders;
- legacy exported constants and device scanner documentation.

They disagree in material places, including H59-H62, H120, H179 names, H22/LSP
descriptions, H103/H104 labels, BMS current comments, and several older input
constants. Runtime writes usually follow `REGISTER_TO_PARAM_KEYS`, which is the
safer layer, but canonical/public metadata can mislead new code.

The long-term contract should encode provenance per field (vendor document,
firmware scanner, raw UI toggle, live write, family set) and make it impossible for
a canonical “named” row to imply writable safety when the runtime table still has
a placeholder.

## Performance analysis

### Local transaction budgets

| Path | Typical work | Important cost |
| --- | --- | --- |
| ant0nkr default | Six 125-register FC04 blocks plus six FC03 blocks over 0-749, then optional battery | About 12-13 transactions every 60 s (`~0.2 tx/s`) |
| ant0nkr 40-register block | Nineteen input plus nineteen holding blocks | About 38 transactions every 60 s before battery |
| EG4 conservative local input | About eight targeted input groups plus battery/header/PV extras | At 5 s Modbus default, fewer registers but potentially higher steady transaction rate than upstream |
| EG4 coalesced/fast input | Typically four to five merged input reads plus extras | Lower transaction count; must respect firmware block-size compatibility |
| EG4 dongle | Targeted groups with 0.5 s inter-group pacing, 30 s default | Seven gaps across eight groups impose a 3.5 s sleep floor before network/retry cost |
| EG4 parameter refresh | Roughly 14-18 targeted ranges, hourly with retry floors | Multi-second dongle spike; writes queue behind operation lock |

The correct conclusion is nuanced: EG4 reads a much smaller relevant plane and
amortizes holding parameters, but its 5-second Modbus cadence can produce more
transactions per hour than the reference's 60-second full sweep. Transaction
count, wall time, and HA callback cost should be profiled separately.

### PERF-01 — semaphore does not bound primary cloud fanout

The integration's semaphore of three wraps later per-inverter processing. Before
that, pure-cloud refresh delegates to `Station.refresh_all_data()`, which gathers
all inverters. Each inverter refresh can concurrently launch runtime, energy, and
battery fetches. A cold/expired-cache primary burst is therefore approximately
three requests times inverter count, not three total.

The semaphore still usefully bounds mapping/side-fetch processing; documentation
should not describe it as a global API concurrency cap.

### PERF-02 — “parameter refresh” is a broad forced refresh

Post-write verification and all-device parameter refresh call inverter
`refresh(force=True, include_parameters=True)`. In the dependency, `force=True`
expires runtime, energy, and battery caches too; the parameter leg adds three cloud
ranges. One logical parameter verification can therefore fan out to roughly six
operations per inverter.

Number post-write handling also iterates related entities and calls
`async_update()`, then explicitly requests a coordinator refresh. HA debouncing
prevents a completely unbounded poll storm, but this remains O(entity count) task
and callback amplification with possible immediate plus trailing refreshes.

### PERF-03 — duplicated background work

- Missing-parameter refresh creates a task whenever parameters are absent. There
  is no explicit in-flight registry. If a forced refresh exceeds the update
  interval, another task can queue behind dependency locks and repeat the work.
- Firmware progress is called during each inverter's processing. Its five-minute
  cache is per inverter, while the underlying progress endpoint is account-wide;
  all inverters can issue the same request when caches expire.
- Cloud supplemental calls inside one inverter are largely sequential. Before the
  breaker opens, aligned Quick Charge, events, AC Couple, Smart Load, and PV work
  can accumulate 10-30 second timeout budgets. Multiple inverters overlap only up
  to the later processing semaphore.
- Battery-backup remains an unprotected 30-second tier in the `#511` snapshot.

### PERF-04 — callback and discovery churn

Mixed LOCAL/HYBRID entries tick at the fastest transport interval. Slower
transports carry cached data, but every successful coordinator update still
notifies all listeners. Sensor setup registers several whole-data discovery scans,
button setup adds another, and each entity evaluates/writes state.

At 300 entities and a five-second tick, there are about 5.18 million entity
callback/state-write attempts per day, before discovery scans. Home Assistant may
suppress identical recorder events, so this is a callback/decoding budget—not a
claim of 5.18 million database rows.

### CFG-01 — duplicate plant coordinators across modes

Config unique IDs intentionally differ between HTTP (`username_plant`) and HYBRID
(`hybrid_username_plant`). Exact-ID duplicate checks therefore permit the same
cloud plant in both modes. Two coordinators can poll the same station and contend
for the same HA entity/device identities. Updating an entry's mode/data also does
not update the unique ID.

This needs an explicit product decision: prohibit cross-mode duplicates, migrate
the same entry between modes, or define safe namespace/request-sharing behavior.

### Reference performance and race comparison

The reference is gentler on HA by default because it polls every 60 seconds and
has fewer feature surfaces, but it is more aggressive on the wire per cycle and
in recovery mode. It connects/reads/closes under one entry lock and may increase
poll frequency while unhealthy.

Reference controls compose bitfield writes from the coordinator's poll-time raw
cache, then optimistically patch that cache. An external write between poll and
write can be erased. Current `pylxpweb` named writes are safer: they fresh-read and
hold a reentrant operation lock across RMW for one transport instance. DEP-01 and
ARC-01 are the important exceptions/remaining boundaries.

## Entity, registry, and lifecycle follow-ups

Additional high-confidence gaps retained below the main P1 set:

- Number/time availability checks only coordinator success, unlike sensor/switch
  device-presence checks. A removed/missing device can leave actionable controls
  available until reload.
- Number/time unique IDs embed a model slug. A device first created as `unknown`
  and later identified can create a new registry identity, unlike model-stable
  sensor/switch IDs.
- Reconfigure device or cloud removal updates config data but has no general
  entity/device registry purge; old serial/plant entries can remain orphaned.
- Control platforms lack the sensor platform's late-register/prune mechanisms.
- Process-global `logging.getLogger("pylxpweb").setLevel(...)` means the last
  loaded entry wins its `library_debug` preference; unload does not reconcile it.
- Module-global install/import locks retain keys for process lifetime. The memory
  impact is small, and persistence across reload is partly intentional.

## Test and quality-gate assessment

### What is strong

- The register contract harness executes real mapping functions and resolves
  controls against the exact installed dependency. It has no remaining declared
  TODO divergences in the audited snapshot.
- The dependency has strong CRC, serial/function/register mismatch, write-ACK,
  short holding-read, BMS truncation, signed/overflow, retry, and link-health
  tests.
- Same-type device poll gating, shared-endpoint poll serialization, battery
  identity migration happy paths, carry-forward behavior, and low-level named RMW
  have meaningful coverage.
- The in-flight breaker helper tests cover threshold/open, single-probe reopen,
  basic classification, coroutine close, gather cancel, and fresh-boot deadline
  sentinel behavior.

### Highest-value missing tests

1. Mixed `modbus_tcp` plus `modbus_serial` due-cycle isolation over multiple ticks.
2. Parallel-group migration with two old/two new groups, no new groups, ambiguous
   groups, and collision rollback.
3. Production listener registration for every optimistic platform; do not invoke
   `_handle_coordinator_update()` manually.
4. Quick Charge vs H233 sibling writer using a real dependency transport lock.
5. Shared physical endpoint poll vs write/background work across two device
   transport objects.
6. Concurrent classic schedule writes and concurrent battery-mode writes.
7. Half-open breaker times neutral result, cancellation, success/failure races,
   and all real side-fetch call sites.
8. Open breaker must leave each underlying getter unstarted; specifically cover
   the lifetime gather call-site semantics.
9. Battery-backup/firmware-status breaker coverage and deterministic request-count
   budgets.
10. Authentication expiry with concurrent cloud requests; exactly one login.
11. First-refresh and platform-setup failure cleanup, including cancellation.
12. Persistent post-read mapping failure with one healthy sibling; assert device
   and parallel-group availability/staleness.
13. Every monotonic throttle at host uptime below its interval.
14. H120 compound read/write property tests and malformed multi-value FC16 ACKs.
15. Independent register truth fixtures from captured frames—not tables shared by
   production and tests.
16. Primary cloud cold-cache concurrency, forced parameter refresh call counts,
   missing-task deduplication, and multi-inverter firmware status counts.
17. Cross-mode duplicate plant setup and multi-entry library logging preferences.

### Test infrastructure gaps

- `tests/pytest.ini` declares unsupported `rootdir`, producing a warning.
- `tests/run_tests.py --install` searches for a root `requirements-test.txt`, but
  the file is under `tests/`; it reports success without installing.
- That runner uses optional Flake8 while declared/CI linting uses Ruff, and it can
  return success when Flake8 is absent.
- The Platinum validator can return success when mypy fails or is unavailable.
  Direct configured mypy passed in this audit, so the product code is not
  currently hidden by that behavior.
- Development documentation references `uv sync` without a project
  `pyproject.toml`/lock, a missing Bronze validator, and a nonexistent root
  `mypy.ini`.
- Coverage is collected without an enforced threshold despite a documented target.

## Rejected or narrowed scan claims

The following were explicitly not promoted:

- **Generic same-transport RMW is unlocked:** false. Dependency named writes hold
  the reentrant operation lock across fresh-read RMW. The gaps are Quick Charge,
  cross-transport cloud/local writers, and separate objects sharing one endpoint.
- **All malformed-frame handling is absent:** false. The dependency has strong
  parser tests. Retained gaps are length assembly, TID workaround attribution,
  selected short-input behavior, and FC16 multi-value fallback.
- **Multiple devices of the same transport type starve:** false; this is tested and
  fixed. INT-01 is specifically mixed TCP plus serial sharing a timestamp.
- **EG4 always performs more Modbus I/O than the reference:** too broad. It reads
  fewer targeted registers per cycle but polls Modbus much more frequently.
- **Station load immediately duplicates every cloud runtime call:** normally
  false; cache warming/TTLs remove much of the duplicate work. Cold/expired primary
  fanout remains PERF-01.
- **Class-level breaker defaults share state across coordinators:** false; instance
  assignment shadows immutable class defaults.
- **OSError in a cloud side-fetch proves portal outage:** false for current breaker
  classification. Several older tests use `OSError("cloud down")`, which the
  breaker treats as non-connectivity/reachability evidence.
- **Battery base 5000 vs 5002 is an offset bug:** false after absolute-field
  comparison.
- **Raw I72-I74 PV currents should be exposed:** rejected; derived P/V current is
  the evidence-backed path for EG4.
- **I176-I216 reference additions are globally portable:** rejected; they are
  predominantly three-phase/V23 lineage and collide with EG4 observations.
- **Feed-In belongs at H22 b15 because upstream says so:** rejected as dangerous.
- **I210 must be minutes:** not established; EG4 countdown evidence supports the
  current seconds path and H234-minute fallback.
- **All current stale/partial behavior is a bug:** narrowed. Several paths
  intentionally preserve last-known values; the defect is presenting them as
  fresh/healthy or allowing stale state to drive aggregates without an age/error
  contract.

## Prioritized follow-up plan

### P1 — correctness and pre-merge blockers

1. Fix INT-01 and add mixed-type multi-tick coverage.
2. Make INT-02 migration evidence-based and non-destructive on ambiguity/no match;
   add a registry rollback matrix.
3. Repair INT-03 production listener wiring and extend the open `#379` tests to
   inspect registered callbacks.
4. Choose physical-endpoint lock ownership for ARC-01 and test poll/write/background
   interactions across device objects.
5. Serialize classic schedule logical writes per serial/boundary; evaluate the same
   primitive for battery control mode.
6. Fix DEP-01 in `pylxpweb` before adding H233 controls.
7. Make authentication renewal single-flight in the dependency.
8. Before merging `#511`, resolve BRK-01, wrap or explicitly exempt every
   supplemental path, make lifetime work lazy, and retain the concurrent-success
   regression test already added unstaged.

### P2 — lifecycle, state truth, and protocol contracts

1. Add setup failure unwind and track the static follow-up refresh.
2. Define stale/available semantics for per-device processing failures and tainted
   parallel aggregates.
3. Replace every never-fetched monotonic `0.0` sentinel with explicit state.
4. Add persistent parameter seed/generation handling for raw LOCAL polls.
5. Correct DEP-03 and DEP-04 with dependency tests; then correct capability
   metadata and evaluate length-framed dongle receive.
6. Add late registration or an explicit reload trigger for controls after feature
   resolution.
7. Fix MAP-01, then review the read-only Tier A sensor candidates independently
   from writable bit work.
8. Bound primary cloud concurrency, narrow forced parameter refresh, deduplicate
   missing-parameter/firmware tasks, and profile callback fanout.
9. Decide how cross-mode duplicate plants should be represented.

### Hardware-evidence queue

1. Raw H179 before/after cloud toggles for On-Grid Always On, Smart Load, Volt-Watt,
   PV Arc, generator peak shaving, and AC Couple.
2. H120 compound field matrix using the dedicated API and raw register.
3. H59-H62 raw/UI correlations and H26 scalar-vs-bit behavior.
4. Negative/reverse I153 capture.
5. Same-firmware I210 countdown correlation against real seconds/minutes and H234.
6. Family matrix for H110 b7/b10/b15 and H233 b12, including restore proof.
7. Complete weekly schedule read/write captures before considering H233 b3.

### Filed follow-up issues

| Bead | Scope |
| --- | --- |
| `eg4-mkxg` | Mixed TCP/serial poll starvation |
| `eg4-w250` | Parallel-group migration safety |
| `eg4-hpwq` | Shared physical endpoint serialization |
| `eg4-xa9f` | Logical multi-call schedule/battery-mode write serialization |
| `eg4-xvf1` | Dependency Quick Charge H233 atomic RMW |
| `eg4-bl9f` | Dependency authentication single-flight |
| `eg4-scg1` | `#511` breaker state machine and call-site coverage |
| `eg4-vp2r` | Dependency H120/FC16/dongle contracts |
| `eg4-06er` | Lifecycle, staleness, startup sentinel, and performance bundle |
| `eg4-uwa0` | Register provenance, read-only gaps, and hardware captures |

The existing open `eg4-1784213053000-189-c167c51a` (`#379`) was updated with
INT-03, and `eg4-ooox` was updated with the new bit-evidence ranking.

## Verification evidence from this audit

### Deterministic probes

```text
# Mixed TCP/serial gate, one shared timestamp
t=100 tcp_due=True serial_due=False shared_stamp=100
t=105 tcp_due=True serial_due=False shared_stamp=105
t=110 tcp_due=True serial_due=False shared_stamp=110
fresh_boot_modbus_due=False stamp=0.0

# Number production wiring (AST/callback inspection)
calls=['self.async_on_remove', 'self.coordinator.async_add_listener']
calls_super=False
registers_state_writer=True

# Neutral half-open breaker result
half_open_after_neutral=True open_until=None failures=0

# H233 Quick Charge lost update
quick_charge_result=True
final_reg233=0x1001 expected_if_merged=0x1003

# FC16 malformed read-style ACK and capability metadata
fc16_multivalue_wrong_echo_accepted=True
dongle_reports_concurrent_reads=True

# Independent validator probes
mixed_modbus_due True False shared_stamp 100.0
fresh_boot_first_poll False stamp 0.0
fresh_boot_degraded_bust False invalidate_calls 0

# Concurrent auth renewal
10 concurrent _ensure_authenticated calls -> 10 concurrent login calls

# Concurrent classic schedule writes
08:15 plus 20:45 with A-hour/B-hour/B-minute/A-minute -> 20:15
```

### Quality gates run during discovery

Before the final moving-tree breaker delta, the validation lane ran:

```text
pytest: 2537 passed, 3 skipped, 42 warnings in 147.82s
register contract: 7 passed, 5 warnings
ruff check: pass
ruff format --check: 116 files already formatted
mypy strict: success across 41 source files
Silver/Gold/Platinum/translation validators: exit 0
```

After the latest unstaged breaker change landed in the moving worktree, the
complete gates were rerun from scratch against that exact tree:

```text
pytest: 2543 passed, 3 skipped, 42 warnings in 137.91s
ruff check: all checks passed
ruff format --check: 116 files already formatted
mypy strict: success across 41 source files
```

The 42 warnings include the already-assessed unsupported `rootdir` pytest
option, deprecated family aliases, and unawaited `AsyncMock` coroutine warnings
from coordinator carry-forward tests. No production code was changed for this
audit.

These green gates do not refute the findings: most defects are uncovered
interleavings, production listener registration, independent-oracle gaps, or
moving dirty code not represented by the existing tests. Final documentation
branch verification is recorded in the commit/push handoff.

## Final assessment

The EG4 integration should continue to treat the ant0nkr repository as an
independent hypothesis generator, not a universal register map. The current stack
is stronger on device families, cloud/local composition, frame attribution, and
fresh-read named RMW. Its main risks arise where that sophistication crosses
boundaries: shared physical endpoints represented by separate objects, logical
operations made of multiple individually safe calls, asynchronous setup and late
feature discovery, cloud fanout, and shared mapping tables that are not independent
truth.

There is worthwhile additional mapping work. The best near-term value is the
already-decoded read-only data and four hardware-backed bit candidates—not the
hundreds of upstream-only holding entities. Correctness, provenance, family gates,
and an explicit “unknown/unsafe” state should remain the defining advantages of
this integration.
