---
canonical-for:
  - "Home Assistant-hosted EG4 dongle-emulation product boundary and phased delivery contract"
  - "Single-owner RS485 arbitration and snapshot requirements for dongle replacement"
  - "Dongle-emulation security, rollout, rollback and success criteria"
sources:
  - llmwiki/10-integration/data-flow-by-mode.md
  - llmwiki/10-integration/diagnostics-repairs.md
  - llmwiki/20-pylxpweb/transports.md
  - llmwiki/20-pylxpweb/write-paths.md
  - llmwiki/40-hardware/firmware-re.md
  - llmwiki/40-hardware/registers.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
  - docs/reference/FIRMWARE_OTA_PROTOCOL.md
  - scripts/decode_cloud_frames.py
  - issue eg4-asjv
verified-against:
  eg4_web_monitor: 9798ccc
  pylxpweb: 204b95d
last-verified: 2026-08-13
see-also:
  - firmware-re.md
  - registers.md
  - ../20-pylxpweb/transports.md
  - ../10-integration/data-flow-by-mode.md
---

# Dongle emulation

This page is the implementation contract for replacing a physical EG4/GridBOSS WLAN
dongle with software hosted alongside Home Assistant. It is written for the planning,
implementation and review agents. The physical dongle is removed for the active bus;
the software reuses data acquired by the local RS485 owner and must not become a second
poller.

The supplied deployment identity and check code are deliberately absent. They are
runtime secrets, not specification data, examples, fixtures, logs or diagnostics.

## 1. Evidence boundary

| Claim | Evidence | Grade | Consequence |
|---|---|---|---|
| Current local paths already serialize access for devices sharing a normalized physical endpoint. | `transport_serialization.py` → `physical_endpoint_key`, `EndpointOperationLock`; `coordinator.py` → `_endpoint_operation_lock_for_transport`; `20-pylxpweb/transports.md` owns the transport contract. | `verified-against-code` | Reuse the endpoint-identity seam, but replace shared-lock convention with an owner object that cannot be bypassed. |
| The existing local acquisition path is configured to poll more frequently than the WLAN-dongle path. | `const/config_keys.py` → `DEFAULT_MODBUS_UPDATE_INTERVAL`, `DEFAULT_DONGLE_UPDATE_INTERVAL`; `10-integration/data-flow-by-mode.md` owns the defaults. | `verified-against-code` | Emission consumes completed local snapshots and schedules no duplicate periodic reads. |
| The V1.1 WLAN firmware contains a port-8000 local server and dispatches `C1`–`C4`; V1.2 changes the listener security contract to TLS-PSK. | `40-hardware/firmware-re.md` and its cited shipped application images/functions. | `firmware-proven` | A local listener is a separate compatibility phase. V1.1 plaintext behavior does not authorize guessing the V1.2 PSK contract. |
| Current pylxpweb local-dongle framing validates outer and inner identity, function, range and CRC, assembles fragmented TCP frames, and never blindly replays an ambiguous write. | `src/pylxpweb/transports/dongle.py` → `_build_packet`, `_receive_frame`, `_parse_response`, `_write_holding_registers` at pylxpweb `204b95d`; `20-pylxpweb/transports.md` owns the transport contract. | `verified-against-code` | The emulator parser and scheduler preserve these invariants on both protocol planes. |
| Captures held outside version control show cloud heartbeat, telemetry, cloud reads and write traffic on the vendor ingestion connection. | Local capture analysis named by issue `eg4-asjv`; raw captures are intentionally excluded. | `asserted-unverified` | They justify an offline protocol engine, not live admission or full firmware parity. Sanitized, stream-reassembled fixtures are a blocking evidence gate. |
| The existing capture decoder parses TCP payloads per segment and can expose identity and register content. | `scripts/decode_cloud_frames.py` → `process_pcap`, `find_frames` and output formatting. | `verified-against-code` | It is not a correctness or redaction oracle until stream reassembly and safe output are implemented and tested. |
| Cloud admission, endpoint selection, duplicate-identity behavior, revocation, ban behavior and the complete TLS contract remain unestablished. | Issue `eg4-asjv` records the evidence search and unresolved set. | `asserted-unverified` | Live vendor-cloud identity use remains disabled until every admission gate in §8 passes. |

### Open contradictions

Local-listener client capacity is C12 in
[`60-history/open-contradictions.md`](../60-history/open-contradictions.md). It is not a
product requirement until captured on the target firmware. The implementation must not
resolve the contradiction by choosing the convenient value.

The cloud-emitter evidence and product sequencing also differ: capture evidence is stronger
for the cloud wire format, while the cloud admission and account-risk evidence is weaker.
This specification therefore allows an offline cloud engine early but live cloud use only
after later gates.

## 2. Product boundary

The deliverable is phased. A phase may ship only when its own acceptance criteria pass;
completion of an earlier phase does not authorize a later one.

| Phase | Included | Excluded |
|---|---|---|
| A — single-owner foundation | One bus owner, immutable raw snapshots, offline parsers/builders, sanitized capture replay, observability and cutover runbook | Vendor-cloud connection, local port-8000 server, cloud writes, `C3`/`C4`, OTA |
| B — experimental cloud telemetry | Default-off outbound connection, proven endpoint selection, heartbeat, input telemetry, captured read responses, reconnect and egress restriction | Writes, unobserved commands, OTA, generic user-configurable endpoint |
| C — cloud controls | Exact-family, exact-firmware, evidence-qualified operations through the bus owner; conflict detection and unknown-outcome journal | Derived global write allowlist, automatic retry, semantic success inferred from ACK/readback, OTA |
| D — local dongle listener | Compatibility server for one explicitly captured firmware contract and authenticated network boundary | Guessed TLS-PSK, universal V1.1/V1.2 compatibility, WAN exposure |
| E — firmware servicing | Not planned | OTA proxying, firmware download, firmware transformation and device flashing |

Phase E stays out of scope until a separate specification proves the end-to-end state
machine, artifact authenticity, per-family compatibility, rollback and recovery. The
physical dongle remains the firmware-update fallback.

### Capability definition

“Dongle capabilities” means only behavior observed and admitted by the active phase. It
does not mean byte-for-byte firmware parity. Unknown outer functions, inner functions,
register ranges, dongle-internal parameters, security negotiations and firmware commands
must fail closed and increment a redacted diagnostic counter.

## 3. Required architecture

```text
HA polling ──────────────┐
HA controls ─────────────┤
parameter refresh ───────┤
cloud read requests ─────┼──> endpoint BusController ──> sole worker ──> RS485 gateway
cloud control requests ──┤              │
reconnect/drain work ────┘              └──> immutable snapshot generations
                                          │
                                          └──> optional protocol emitters
```

### 3.1 One owner per physical endpoint

One endpoint registry/factory MUST be the only module allowed to construct and retain a raw
transport. It creates exactly one owner per normalized physical endpoint and returns only an
owner-issued client capability whose API contains scheduled operations, snapshot reads and
status—not raw transport access or arbitrary I/O. Endpoint identity MUST include the
adapter connection and bus identity; uncertain equivalence fails closed. Raw transport
constructors are private to the factory module, the owner stores the transport in a private
field, and no coordinator, entity, protocol emitter or recovery task may accept or expose
the raw transport type.

This boundary is mechanical, not conventional. An architecture test MUST enumerate every
raw-transport construction and I/O call site and fail unless it is inside the registry/owner
module. A runtime test with an instrumented fake transport MUST fail on a second owner,
alternate constructor or operation that bypasses the queue. Stress and cancellation tests
MUST assert the fake transport's maximum concurrent-operation counter is one.

The owner MUST serialize all work that can touch the endpoint:

| Operation class | Scheduling rule |
|---|---|
| Periodic input/holding reads | Coalescible and replaceable before start; bounded starvation |
| Discovery and parameter refresh | Serialized transaction; no overlap with polling |
| HA control | Ordered, higher priority than unstarted polls, never preempts an on-wire operation |
| Read-modify-write and schedules | Indivisible transaction from fresh read through response validation |
| Cloud-requested read | Fresh snapshot when allowed; otherwise one queued read, never a parallel transport call |
| Cloud-requested control | Phase C only; same admission and atomicity rules as HA controls |
| Reconnect, input drain and restoration | Owner-only maintenance operation |

At most one RS485 operation may be in flight. Writes preserve admission order. Cancellation
of a caller must not cancel or replay bytes already placed on the wire.

### 3.2 Snapshot contract

Every successful read publishes an immutable block with:

- normalized endpoint and unit/slave identity;
- known device family and firmware scope;
- register space and exact inclusive range;
- raw words, with no parsed-value reconstruction;
- monotonically increasing generation and poll-cycle identifier;
- monotonic acquisition start/end timestamps;
- validation result covering frame length, identity, function, range and CRC.

Publication occurs only after whole-frame validation. Missing registers are never filled
with zero. An emitted block may not combine ranges from unrelated poll cycles. Wall-clock
changes cannot affect freshness.

The initial default freshness budget is the greater of three configured local poll
intervals or fifteen seconds, capped at sixty seconds. This is a proposal, not firmware
behavior. Planning MUST expose it as one named policy with tests and collect field metrics
before changing it. Proactive telemetry suppresses stale/incomplete blocks. A reactive
read queues one fresh read if its captured deadline permits; otherwise the session uses a
captured error form or closes. It never fabricates data or an unobserved error response.

### 3.3 Parser and connection contract

Every network parser MUST use one named internal `ParserPolicy`. Initial proposed defaults
and allowed test ranges are:

| Policy | Default | Allowed internal range | Boundary behavior |
|---|---:|---:|---|
| Maximum complete frame | 4,096 bytes | 512–65,535 bytes | Advertised size above the limit closes the connection before body allocation. |
| Prefix scan buffer | 64 bytes | 2–1,024 bytes | No prefix within the bound closes the connection and discards the buffer. |
| Overall frame deadline | 5 seconds | 1–30 seconds | One deadline covers prefix, header and body; progress does not reset it. |
| Pending operation capacity | 128 | 16–1,024 | Polls coalesce first; new reads reject next; a new write rejected before transmission returns overload and is never silently dropped. |
| Poll starvation ceiling | two configured intervals, maximum 30 seconds | 1–10 intervals | An overdue poll runs after the current indivisible write transaction. |

Values are product proposals, not captured firmware facts. They are not user-facing tuning
in the first release. Tests cover minimum, default, maximum and one value outside each
allowed range.

Every network parser MUST:

- reassemble split frames and parse multiple coalesced frames;
- impose one bounded frame-size limit, one overall frame deadline and bounded prefix scan;
- reject mismatched outer identity, inner identity, function, start/range and CRC;
- retain incomplete bytes across TCP reads without unbounded memory growth;
- treat EOF, timeout, malformed length and protocol mismatch as connection-fatal;
- emit only redacted metadata and counters.

Reconnect uses a named policy: one-second initial delay, doubling to sixty seconds, ±20%
jitter, and a circuit breaker that opens for five minutes after five consecutive failed
sessions. A successful complete frame resets the failure count. Boundary tests use an
injected clock and deterministic jitter. No pending write is replayed after reconnect. HA
unload/reload and stop must close egress, drain or mark queued work, and leave no background
task or listener.

## 4. Write-safety contract

Phase A and B reject all remote controls. Phase C begins with an empty admitted set. A
control becomes reachable only when the exact family/firmware mapping meets the register
keeper’s write-access ladder and a captured vendor request/response contract exists.
The admitted set is derived from canonical mappings and runtime routing, never copied from
a historical hand-maintained list.

The readback limitation and write-access ladder are owned by
[`README.md`](../README.md#the-register-annotation-ladder); this page applies them and does
not create a second evidence rule.

Packed whole-register controls MUST use a served-generation baseline and one atomic
fresh-read/compare/merge/write transaction. Changed sibling bits, a missing baseline,
multiple possible field interpretations or an unsupported function produce a conflict.

Once any write byte may have reached RS485, a timeout, disconnect, cancellation or malformed
acknowledgement produces `OUTCOME_UNKNOWN`:

1. never replay automatically, including after restart;
2. never report success upstream;
3. reconcile with a fresh read, described only as storage agreement or disagreement;
4. persist a redacted write-ahead record before transmission and a terminal outcome after;
5. block live emission after restart while a nonterminal record exists;
6. require a new explicit command for any later attempt.

## 5. Identity, secrets and trust boundaries

The supplied hardware identity and check code MUST be provisioned out of band at runtime.
Until admission is proven stronger, treat both as credentials. The check code is never sent
to the ingestion endpoint unless a primary capture proves that requirement; it is never
accepted merely because an old design says it is unnecessary.

### MUST

- No **production** serial, check code, PIN, PSK, cookie, token, raw capture, full
  flash/NVS, private address, MAC, configuration register value or unredacted frame enters
  git, fixtures, issues, PRs, logs or diagnostics. Unmistakably synthetic identities,
  RFC 5737 documentation addresses and canary values are required for tests and examples.
- Runtime secret storage uses the platform’s existing secret mechanism. Configuration
  persists an opaque reference or keyed fingerprint, not the literal where possible.
- Diagnostics expose stable aliases, phase/capability state, counters, queue depth,
  latencies, freshness and reconnect reasons only.
- Only Home Assistant administrators may enable, disable or inspect the feature. No generic
  service, event or shared transport capability exposes the emulator to other integrations.
- Cloud emitters in Phases B/C have an allowlisted destination resolved through the proven
  selection mechanism, authenticated encryption with hostname/certificate validation, and
  no inbound listener. Phase D is an independently gated, isolated-interface exception.
- The revocation runbook covers account credentials, vendor-side device association,
  runtime secret deletion and egress blocking. Target time from leak discovery to local
  egress block is five minutes; vendor-side revocation time is measured during HIL.
- Secret scans run on the deliverable diff and repository. Redaction tests use canary
  values that resemble every protected category without containing production values.

### SHOULD

- Run the emulator in the smallest network domain that can reach the RS485 gateway and the
  allowlisted vendor endpoint.
- Deny lateral access from unrelated VLANs and deny all other egress.
- Rate-limit connection attempts and unexpected-command logs to prevent resource and log
  exhaustion.

## 6. Configuration and user experience

Each phase is explicit and default-off beyond Phase A. Enabling a live phase requires an
administrator acknowledgement showing:

- exact supported device family/firmware scope;
- physical dongle must be detached before the emulator uses that identity;
- experimental vendor-cloud status and unresolved warranty/support treatment;
- controls disabled unless Phase C is separately enabled;
- rollback instructions and last successful restoration drill;
- active endpoint alias, freshness state and circuit-breaker status without secrets.

Configuration validation rejects missing secret references, unsupported families,
unproven endpoint selection, duplicate active emitter instances and a bus owner that can be
bypassed. There is no free-form cloud host or port in the user interface.

## 7. Observability and resource limits

The implementation MUST publish redacted metrics for queue wait, transaction duration,
snapshot age, suppressed stale blocks, parser failures by class, reconnects, circuit-breaker
state, rejected commands, conflicts and unknown write outcomes. Labels must not contain
identity, endpoint, register values or unbounded error text.

Acceptance budgets:

| Budget | Threshold |
|---|---|
| Concurrent RS485 transactions per endpoint | exactly 0 or 1; never greater than 1 |
| Additional periodic bus reads caused by emission | 0 |
| Parser memory | peak incremental allocation per active connection no more than `ParserPolicy.maximum_frame_bytes + prefix_scan_bytes + 16 KiB`; after 1,000 malformed connection cycles, retained growth no more than 64 KiB |
| Pending queue | no more than `ParserPolicy.pending_operation_capacity`; overload follows the ordered coalesce/reject behavior in §3.3 |
| Event-loop blocking | 0 blocking socket or file operations in the HA event loop |
| Secret/identity occurrences in diagnostics and normal logs | 0 |

The baseline is a thirty-minute local-only run on the same hardware, configuration and
workload, recording poll completion cadence, transaction p50/p95, error rate, HA process CPU
and resident memory. The candidate passes when poll cadence and transaction p95 are no more
than 20% slower, error rate rises by no more than 0.1 percentage points with zero identity
or CRC mismatches, CPU rises by no more than five percentage points, resident memory rises
by no more than 50 MiB, and a 24-hour soak has no sustained memory slope above 1 MiB/hour.

## 8. Evidence and release gates

### Gate A — offline foundation

- Golden fixtures are generated from authorized captures by an offline sanitizer that
  performs TCP stream reassembly before redaction.
- Fixtures contain synthetic identities/addresses and the minimum register data needed for
  each assertion. A scan proves no production value remains.
- Tests cover byte-at-a-time fragmentation, every split point, coalesced frames, duplicate
  TCP segments, truncation, oversize length, bad CRC, mismatched identities/functions/ranges,
  EOF and timeouts.
- Scheduler/model tests prove the one-in-flight invariant across polls, controls, reconnects,
  cancellation and HA unload/reload.
- Every new or changed test has red-with-fix-reverted and green evidence.

### Gate B — passive and shadow validation

- A minimum thirty-minute passive capture on each exact device/firmware matrix entry confirms
  initial connection, at least ten heartbeats, at least three complete telemetry cycles,
  every observed read range, one controlled network-loss/reconnect and graceful close.
  Raw data remains encrypted and outside the repository, then follows a documented
  retention/deletion period.
- The controlled disconnect records a monotonic start timestamp, then checks the authorized
  portal/API status once per second for at most sixty seconds. Gate B records the first
  observed session-absent timestamp and derives the session-expiry timeout; no disappearance
  within sixty seconds blocks cutover rather than inventing a timeout.
- Shadow means replay or local comparison only. It never opens a second vendor connection
  with the production identity.
- Generated versus captured frames match after replacing nondeterministic identity/time
  fields. Every allowed divergence is named and tested; “looks sane” is not parity.
- Unknown frame/function incidence is zero for that complete capture plan. Controls are a
  separate isolated HIL scenario; passive observation does not qualify a write.

### Gate C — live vendor participation

All items are blocking:

1. device/account ownership confirmed by the administrator;
2. a recorded affirmative authorization decision for protocol emulation and identity use,
   naming the approver, scope, restrictions and re-review triggers; a review that concludes
   the use is prohibited does not pass;
3. dedicated non-production account/device for first use;
4. endpoint selection proven from authenticated API/traffic, not hard-coded;
5. valid, invalid, revoked and duplicate-identity admission behavior captured;
6. TLS and certificate/hostname validation proven;
7. revocation/rotation and physical restoration drills passed;
8. no live parallel run using the same identity;
9. all applicable CI, live-tool checks and review gates green.

### Gate D — local listener

- One passive target-firmware capture proves connection, security negotiation, framing,
  client capacity, close/error behavior and every supported request.
- V1.2 TLS-PSK provisioning and rotation are proven without publishing key material.
- The listener binds only to the intended isolated interface and is unreachable from WAN
  and unrelated VLANs.
- Compatibility is advertised by exact captured contract, never as universal dongle parity.

## 9. Cutover, abort and rollback

There is no same-bus parallel run. Safe shadowing is offline comparison while the physical
dongle remains the only master.

### Cutover

1. Export a redacted configuration/rollback record and verify the restoration checklist.
2. Disable cloud controls and emitter egress.
3. Stop and physically detach the WLAN dongle.
4. Confirm its cloud session is absent for `2 × observed heartbeat timeout + 5 seconds`,
   capped at a sixty-second cutover wait. The observed timeout is recorded by Gate B; if it
   is unavailable or the session remains visible at the cap, abort cutover.
5. Attach/enable the local gateway and prove exactly one bus owner.
6. Run the thirty-minute local-only baseline procedure in §7 and meet every cadence,
   latency, error, CPU and memory threshold before enabling any Phase B egress.
7. Start one allowlisted emitter instance and monitor all abort signals.

### Immediate abort criteria

- any overlapping RS485 transaction or second master;
- any unexpected or unsupported remote command;
- duplicate-identity response or unexplained admission failure;
- wrong, incomplete or stale portal value beyond the captured service window;
- any secret in logs/diagnostics;
- any nonterminal write journal record;
- circuit-breaker flapping, unbounded queue/memory or Home Assistant instability;
- protocol parity or local polling regression outside the accepted baseline.

### Rollback

1. Disable the emulator and block its egress.
2. Verify sockets/listeners are closed and no owner task remains.
3. Spend at most sixty seconds attempting to reconcile `OUTCOME_UNKNOWN`; persist unresolved
   records for deferred investigation rather than delaying service restoration.
4. Detach the local gateway from the active bus if required by the topology.
5. Restore the physical dongle and prior Home Assistant configuration.
6. Verify portal freshness and command behavior, then investigate persisted unknown outcomes.

Every HIL release candidate MUST restore service in under ten minutes in three consecutive
drills. Failure keeps the live phase disabled.

## 10. Success criteria

Phase A succeeds only when:

- one owner is mechanically impossible to bypass in the supported topology;
- stress/fault tests observe no overlapping bus transaction;
- existing local polling and controls retain their baseline behavior;
- the protocol engine passes all sanitized replay, framing and redaction tests;
- telemetry construction adds zero periodic RS485 reads;
- HA start, reload, unload and network loss leave no leaked task/socket;
- documentation contains no production identity or private deployment-network detail.

Phase B succeeds only when Gate C passes and a continuous 24-hour HIL run has:

- no duplicate session, unknown command, stale/incomplete emission or secret disclosure;
- portal values matching complete local snapshots under a committed per-field comparison
  manifest. Each manifest row names the raw source range, canonical scaling owner, display
  resolution and comparison rule: raw words and integer fields are exact; a displayed float
  tolerance is at most half its documented display resolution unless a stricter captured
  rule is proven. A field without a manifest row is excluded rather than compared loosely;
- reconnection after each injected network fault without manual reload;
- physical-dongle rollback completed within the target time;
- local poll cadence and transaction p95 remain within the §7 20% threshold, while the
  exact count of additional periodic RS485 reads attributable to emission remains zero.

Phase C additionally requires one controlled test per admitted operation showing the vendor
request, exact bus transaction, transport/storage reconciliation, independent physical or
portal semantic observation at the grade required by the register keeper, and clean
restoration. ACK/readback alone fails this criterion.

Phase D succeeds only against its named captured firmware contract and must not broaden
Phase B/C support implicitly.

## 11. Required implementation and review routing

Issue `eg4-asjv` records the owner's routing request. For this effort, implementation uses
the Codex worker with `gpt-5.6-sol` at `xhigh` reasoning. Each implementation slice requires
its own PR and the repository delivery gates. `asserted-unverified` (issue `eg4-asjv`).

The requested tribunal matrix for the future implementation is:

| Seat | Requested model | Effort | Role |
|---|---|---|---|
| agent | `grok-5.6` | high | blocking review |
| claude | `claude-fable-5[1m]` | medium | blocking review |
| kimi | `kimi-k3` | high | advisory review |

No implementation may claim this requested tribunal ran until those exact seats return
conforming reports or the owner explicitly approves substitutions. This is a delivery
requirement, not a statement about current harness availability.

## 12. Planning decomposition

The planning agent should create dependent work in this order:

1. safe capture sanitizer and streaming decoder;
2. endpoint-scoped bus owner and bypass audit;
3. immutable snapshot store and freshness policy;
4. offline cloud parser/frame builder and replay suite;
5. lifecycle, redacted diagnostics and fault injection;
6. passive/shadow evidence collection and parity report;
7. legal/admission/security decision gate;
8. experimental read-only cloud HIL;
9. evidence-qualified controls, if separately approved;
10. local-listener capture and compatibility phase, if still needed.

Items 7–10 are not implied by completion of items 1–6. The planner must keep each live
capability behind its own human-visible decision and rollback gate.
