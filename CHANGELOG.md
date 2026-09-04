# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.5.1-beta.16] - 2026-09-04

Requires **[pylxpweb==0.10.0b9](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.10.0b9)**.

### Changed

- **Two devices on one WiFi dongle no longer fight for its single local TCP slot** (pylxpweb [#329](https://github.com/joyfulhouse/pylxpweb/issues/329) / PR [#330](https://github.com/joyfulhouse/pylxpweb/pull/330)): Home Assistant now uses one shared, serialized socket per dongle, so the second device should stop being dropped and replies should stop landing on the wrong device. This affects WiFi-dongle LOCAL and HYBRID setups with two or more devices on one dongle; cloud-only, Modbus TCP, serial RS485, and one-device-per-dongle installs are unchanged. No configuration change is needed. As one watch-for, pointing two different dongle serials at the same host:port now fails at connect with a mismatch error instead of silently colliding.

### Fixed

- **Standalone batteries now produce an actionable Modbus discovery error** ([#574](https://github.com/joyfulhouse/eg4_web_monitor/issues/574)): when the add-device flow reaches an EG4 battery BMS that serves holding registers but not the inverter input-register map, it identifies the battery protocol and points the user to standalone-battery support issue #176 instead of reporting a generic timeout.

## [3.5.1-beta.15] - 2026-09-02

Requires **[pylxpweb==0.10.0b8](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.10.0b8)**.

### Added

- **The rest of the daily Grid Peak Shaving parameter set** ([#592](https://github.com/joyfulhouse/eg4_web_monitor/issues/592), PR [#608](https://github.com/joyfulhouse/eg4_web_monitor/pull/608)): five new number entities on grid-tied inverters — Grid Peak Shaving Power 2 (register 232), SOC 1 / SOC 2 (207 / 218) and Voltage 1 / Voltage 2 (208 / 219) — alongside the existing Power 1 (206), mode switch and four schedule times. They read locally, via the cloud and in hybrid mode, write locally by name on a positively resolved grid-tied family and through the cloud holdParam (with readback) otherwise; units whose family is unidentified / unresolved route these writes cloud-only, while positively identified off-grid units do not create these entities at all (grid-tied branch only). Power 2 shares Power 1's "Peak Shaving mode must be on" pre-check; the SOC / voltage floors follow the discharge battery-control mode (SOC vs Voltage). Local polling now reads registers 206–212 in one frame plus 218–219 and 232 on hybrid families. The pinned library's voltage holding rows now match the integration's 40.0–64.0 V limits. Register evidence for the five remains portal-correlated.

### Fixed

- `docs/DATA_MAPPING.md` no longer claims register 231 holds the peak-shaving power (H231 is unknown; PS1 is H206).

## [3.5.1-beta.14] - 2026-09-02

Requires **[pylxpweb==0.10.0b7](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.10.0b7)**.

### Fixed

- **On-Grid SOC Cut-Off accepts 91–100 % again and no longer reads unknown for portal-set values** ([#603](https://github.com/joyfulhouse/eg4_web_monitor/issues/603)): beta.13 (PR [#600](https://github.com/joyfulhouse/eg4_web_monitor/pull/600) review round 2) matched the entity to pylxpweb's 10–90 bound for register 105, but that 90 was the portal's arrow-button hint, not a firmware limit — the inverter stores a portal-typed 95 and rejects 101 (96–100 are inferred from that pair). The write ceiling is 100 (companion fix in pylxpweb 0.10.0b7), and the read plausibility window is the full 0–100 so a stored value never blanks. Users who keep batteries full ahead of outages can set the cut-off from HA again.
- **System Charge SOC Limit accepts 0–9 %** — the same class of defect: an evidence-free 10 floor against pylxpweb's 0–101 range would have blanked a portal-set value below 10 to unknown and refused to write one.

## [3.5.1-beta.13] - 2026-08-30

Requires **[pylxpweb==0.10.0b5](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.10.0b5)**.

### Fixed

- **Stale firmware-update activity now expires** ([#573](https://github.com/joyfulhouse/eg4_web_monitor/issues/573), PR [#599](https://github.com/joyfulhouse/eg4_web_monitor/pull/599)): a cached `in_progress` firmware row no longer survives persistent refresh failures as a permanent spinner. Per-serial poll freshness (monotonic, `None` never-ran sentinel) expires stale activity after `max(3 × cloud poll interval, 600 s)` — including when the overall coordinator update succeeds while the firmware side-poll fails — and recovery re-publishes fresh state.
- **GridBOSS Modbus discovery no longer misreads the AC-couple energy counter as parallel config** ([#596](https://github.com/joyfulhouse/eg4_web_monitor/issues/596), PR [#597](https://github.com/joyfulhouse/eg4_web_monitor/pull/597)): input registers 112–113 on MID/GridBOSS are `ac_couple3_energy_total_l1`, so once lifetime energy crossed 6553.6 kWh discovery would have fabricated a parallel role. The read is skipped for GridBOSS (companion library-side fix in pylxpweb 0.10.0b5).
- **Dongle sanitizer is fail-closed on protocol shape** ([#588](https://github.com/joyfulhouse/eg4_web_monitor/issues/588), PR [#598](https://github.com/joyfulhouse/eg4_web_monitor/pull/598)): frames with a protocol version other than little-endian 0x0001 or an address byte other than 1 are rejected with a new `PROTOCOL` failure reason, and heartbeat payloads must be exactly one byte. Review caught and fixed an inverted-endianness check inherited from the earlier #579 draft.
- **Unreported battery state of health shows as unknown, not 100%** (pylxpweb [#309](https://github.com/joyfulhouse/pylxpweb/issues/309), based on pylxpweb [#286](https://github.com/joyfulhouse/pylxpweb/pull/286)): a silent BMS was indistinguishable from a perfectly healthy pack. All decode paths (local Modbus, master/slave battery protocols, cloud) now surface unreported SoH as `None`; bank min-SoH/SoH-delta exclude unreported batteries.
- **GridBOSS serial-number discovery falls back to holding registers** (eg4 [#593](https://github.com/joyfulhouse/eg4_web_monitor/issues/593), pylxpweb [#315](https://github.com/joyfulhouse/pylxpweb/pull/315)): units whose input-register serial area serves energy counters now read `HOLD_SERIAL_NUM`, gated by a strict 10-char alphanumeric plausibility check on both paths, with dongle-safe inter-register delay and graceful degradation on restricted register maps.

### Changed

- **Off-grid write-evidence audit — every off-grid-writable control derived and fail-closed** ([#570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570), PR [#600](https://github.com/joyfulhouse/eg4_web_monitor/pull/600)): the #558 protected set is now *derived*, not spot-checked. All writable scalars, the quick-charge switch/status path, schedule time entities, and Grid Peak-Shaving Power route cloud-only on EG4_OFFGRID **and unresolved** families (fail-closed, verified against the pinned pylxpweb wheel); resolved non-off-grid families keep local-first behavior. Entity ranges now respect firmware-proven off-grid limits (H66 ≤ 10 kW, H158 39–57 V, H159 48–59 V, H160 ≥ 1 %, H161 ≥ 20 %, H105 10–90 % — the H105 ceiling was the then-pinned library bound, not firmware-proven; superseded by #603 in the next beta) with family-scoped bounds. Cloud-routed writes converge cleanly via per-key write-seed settle windows with a one-shot settle-expiry recheck. The llmwiki register ledger carries per-register write-evidence grades from the firmware RE + live hardware sweep, including the H161 write anomaly and the H233 CEAA/CCAA split.
- **Immutable raw-register snapshot store (Phase A3)** ([#583](https://github.com/joyfulhouse/eg4_web_monitor/issues/583), PR [#586](https://github.com/joyfulhouse/eg4_web_monitor/pull/586)): eligible LOCAL/HYBRID owners publish exactly one immutable latest-complete raw frame per (endpoint, unit) — atomic publication only when every invoked read contributed and coverage held, O(1) storage, monotonic freshness policy, zero additional Modbus reads, redacted metrics only, and clean teardown (shared-owner-safe forced release on unload).

## [3.5.1-beta.12] - 2026-08-28

Requires **[pylxpweb==0.10.0b4](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.10.0b4)** — the first release on the 0.10.x library line, carrying both halves of the #587 fix.

### Fixed

- **LOCAL/HYBRID poll interval no longer degrades over time** ([#587](https://github.com/joyfulhouse/eg4_web_monitor/issues/587)): the raised pylxpweb pin closes both mechanisms behind the creeping 5s → 10s → 30s effective poll interval. **Aging-session latency** (pylxpweb [#290](https://github.com/joyfulhouse/pylxpweb/pull/290)/[#295](https://github.com/joyfulhouse/pylxpweb/pull/295), in 0.10.0b3): the long-lived local Modbus session is now recycled proactively (~hourly with jitter) instead of only after 3 consecutive hard errors, so gradual gateway latency degradation no longer accumulates until an integration reload. **Dead-endpoint probe cost** (pylxpweb [#310](https://github.com/joyfulhouse/pylxpweb/pull/310), in 0.10.0b4): when a local endpoint goes deaf (TCP accepts but never answers — the wedged-dongle failure mode), each coordinator refresh no longer pays the transport's full read timeout chain (10s dongle / up to ~30s Modbus retries) as its link-down probe. Probes are now a single-attempt `check_link()` with a 2s budget on an exponentially backed-off window (4s → 60s, reset on any success), and the HTTP fallback keeps data flowing meanwhile. Home Assistant schedules `next poll = refresh duration + interval`, which is why both mechanisms presented as a growing poll interval.
- **Bounded TCP reassembly overlap work** ([#585](https://github.com/joyfulhouse/eg4_web_monitor/pull/585)): caps the per-frame overlap scan in dongle stream reassembly so pathological fragment patterns cannot inflate refresh time.
- **AC Charge switch on EG4_OFFGRID replaced with schedule-state controls** ([#563](https://github.com/joyfulhouse/eg4_web_monitor/issues/563), PR [#572](https://github.com/joyfulhouse/eg4_web_monitor/pull/572)): the previous switch was a no-op on the off-grid family; charging from AC is governed by the schedule state there, which the new controls expose honestly.
- **Unverified off-grid writes route cloud-only** ([#558](https://github.com/joyfulhouse/eg4_web_monitor/issues/558), PR [#569](https://github.com/joyfulhouse/eg4_web_monitor/pull/569)): registers without hardware-proven local write evidence on EG4_OFFGRID no longer attempt the local path, and the doomed pure-LOCAL H233 quick-charge write is stopped instead of failing silently.
- **Firmware update progress reports honest indeterminate state** ([#512](https://github.com/joyfulhouse/eg4_web_monitor/issues/512), PR [#567](https://github.com/joyfulhouse/eg4_web_monitor/pull/567)) instead of a fabricated percentage.
- **Bogus `eps_apparent_power_l1/l2` suppressed on the hybrid family** ([#548](https://github.com/joyfulhouse/eg4_web_monitor/issues/548), PR [#568](https://github.com/joyfulhouse/eg4_web_monitor/pull/568)).
- **Duplicate cloud identity Repair dismissed on successful migration** (PR [#584](https://github.com/joyfulhouse/eg4_web_monitor/pull/584)).

### Added

- **Endpoint-scoped local bus owner** (PR [#582](https://github.com/joyfulhouse/eg4_web_monitor/pull/582)): serialises local transport access per physical endpoint so multiple config entries sharing one gateway cannot interleave requests.
- **Offline dongle capture sanitizer** (PR [#577](https://github.com/joyfulhouse/eg4_web_monitor/pull/577)) for scrubbing serials/identifiers from captured dongle traffic before sharing diagnostics.

## [3.5.1-beta.11] - 2026-08-12

Requires **[pylxpweb>=0.9.39b11](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b11)** (pin raised): the library release carries the `FUNC_ON_GRID_ALWAYS_ON` → holding register 179 bit 15 mapping that the Grid Always On fix below writes through on the local path.

### Fixed

- **Grid Always On now available in LOCAL and HYBRID modes** ([#559](https://github.com/joyfulhouse/eg4_web_monitor/issues/559), PR [#562](https://github.com/joyfulhouse/eg4_web_monitor/pull/562)): the Grid Always On working-mode switch, previously cloud-only, is created and writes locally via the named `FUNC_ON_GRID_ALWAYS_ON` parameter (holding register 179 bit 15) when the installed pylxpweb carries the mapping — which the raised pin guarantees. The bit is **hardware-proven** (2026-08-12, FlexBOSS21): a portal toggle flipped the local raw register read 0x1048 → 0x9048, a single-bit change of exactly 0x8000, with a clean restore verified through both cloud and local reads. The per-family register-179 contract test guards the pin against silent regression; the interim version-tolerance machinery for the pre-pin pylxpweb floor has been removed now that the pin has advanced.

- **Constant-zero temperature blanking requires positive radiator warmth** ([#560](https://github.com/joyfulhouse/eg4_web_monitor/issues/560), PR [#561](https://github.com/joyfulhouse/eg4_web_monitor/pull/561)): blank `internal_temperature` / `battery_temperature` / `bt_temperature` at exact 0 only when at least one radiator reads STRICTLY `> 0` °C — and now on the LOCAL/HYBRID transport paths too, not just cloud. Radiators `<= 0` (including negatives) and absent radiators protect the reading. This also **narrows the cloud path vs #490** (previously unconditional `tinner: 0` blanking); known #490/#76 reporter payloads had live radiators and remain fixed. The #560 reporter's diagnostics showed radiators at 58/61 °C with targets stuck at 0. Accepted residual: an all-zero boot/placeholder frame publishes zeros until radiators warm (indistinguishable from genuine cold — no family/freshness heuristic).

## [3.5.1-beta.10] - 2026-08-08

Requires **[pylxpweb>=0.9.39b10](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b10)** (pin raised): the library half of this fix stops the off-grid generator registers from being decoded at all, so `InverterRuntimeData`/`InverterEnergyData` no longer carry the 1 Hz counter or the status bitfields that the LOCAL and HYBRID paths read directly. The integration change below removes the entities; the library change removes the underlying values.

### Removed

- **Generator Power / Generator Energy / Generator Energy Lifetime on the off-grid family** ([#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544), reported by @brendonlobo123 on a 12000XP reading 28,646 W with nothing connected to the GEN port): these three sensors are no longer created on EG4_OFFGRID, because their backing registers are not measurements on that platform. Established by decoding the reporting device's own firmware (`ceaa-0709`, downloaded from EG4's portal — see the new `scripts/download_inverter_firmware.py`): the Modbus FC04 handler for input register 123 at `0x0801E9CA` returns `RAM16[0x2000D70A]`, a word of the ARM comms processor's own RAM that a timer task increments once per second at `0x08018BDA` with no bound check, so it wraps at 65536 — it is seconds-since-boot, not watts. A whole-image writer audit found only that increment and the power-on clear; no DSP measurement path reaches it. The reporter's own two samples confirm it with zero free parameters: `(5610 − 28646) mod 65536 = 42,500 s`, within 33 seconds of the real interval between the captures. Registers 124/125/126 behind the two energy sensors are ARM-local status words rather than accumulators, which is why a "lifetime" of 135,494.5 kWh decodes to the bit pattern `0x0014ACC1` — and why the same `0xACC1` low word appeared on a *different* 12000XP in [#196](https://github.com/joyfulhouse/eg4_web_monitor/issues/196) five months earlier. Already-created entities are purged from the registry for positively-resolved off-grid inverters, and a Repairs notice names the affected device rather than letting dashboards break silently. **Generator Voltage, Generator Voltage L1/L2 and Generator Frequency are kept** — those read the DSP receive-frame block and correctly report 0 with no generator attached. **EG4_HYBRID is unaffected**: there register 123 is measurement-derived from two DSP-fed operands, and on a GridBOSS parallel system the inverters' values sum to the GridBOSS AC-Couple-1 total within 0.13%. No replacement Generator Power sensor is offered on the off-grid family: no dedicated register for it was found (188/189 are unimplemented), and the candidates will not be wired up without a live capture from a running generator. Full derivation with firmware addresses in [`docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md`](docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md); the 6000XP half of the family matches structurally but its increment site was not located, and that inference is documented in §7 of the same file.

### Fixed

- **"Using generator" no longer inferred from generator power** (part of [#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544)): the diagnostics field derived from `generator_power > 0`, which is wrong on both families — on EG4_OFFGRID the 1 Hz counter pinned it True until the 16-bit wrap, and on EG4_HYBRID register 123 carries whatever crosses the multiplexed GEN terminal, including AC-coupled PV. It is now derived from the GEN terminal's own voltage and frequency (genuine DSP-fed measurements that read 0 with nothing attached), and reports unknown rather than falling back to the library when either is missing — that fallback is unreachable on the cloud path and, on LOCAL/HYBRID, would land straight back on the broken comparison during a partial read.

### Added

- **`scripts/download_inverter_firmware.py`** — fetches complete inverter firmware images (ARM comms + C28x DSP) for any device family from EG4's portal, including hardware you do not own. Supersedes capturing an OTA push with `tcpdump`. **`scripts/walk_input_dispatch.py`** walks the Modbus FC04 input-register dispatcher in an ARM image and reports the RAM address behind each register, which is what distinguishes a genuine DSP-fed measurement from an ARM-local value; it self-checks against registers measured on real hardware in #196. Method and pitfalls in [`docs/reference/firmware/FIRMWARE_ACQUISITION.md`](docs/reference/firmware/FIRMWARE_ACQUISITION.md), which also corrects the previously-committed firmware RE artifacts under `docs/reference/firmware/re/` — they were produced from images that still carried OTA transport framing and are not usable.

## [3.5.1-beta.9] - 2026-08-03

### Fixed

- **Bank Capacity Percent stuck at 0 in Cloud mode** ([#514](https://github.com/joyfulhouse/eg4_web_monitor/issues/514), reported by @brendonlobo123 on a 12000XP): some units report no per-battery module array to EG4's cloud (`batteryArray=[]`), which leaves the cloud's array-computed `capacityPercent` — and only that field — frozen at 0 while the BMS-level pair in the same payload stays live and correct (the reporter's log: 260/500 Ah = 52% matching SOC exactly, across every polled cycle). The sensor relayed that fake 0 verbatim. Fixed in [pylxpweb 0.9.39b9](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b9) (pin raised): the raw cloud value stays primary, and only a 0/absent reading with the BMS pair present derives the percentage from `currentBatteryCharge / maxBatteryCharge`. Devices whose cloud accounts populate the field (live-verified 18kPV and FlexBOSS21, where the raw value already equals the pair ratio exactly) are byte-for-byte unchanged, as are GridBOSS (no pair) and genuinely empty banks (whose pair derives ~0 anyway). Local mode was never affected — its register path already derived the ratio.

## [3.5.1-beta.8] - 2026-08-03

This release delivers the two long-open community PRs from @notexpected, merged after their final review rounds, plus same-day hardening follow-ups from those reviews.

### Added

- **Per-device removal from the UI** ([#174](https://github.com/joyfulhouse/eg4_web_monitor/issues/174), requested by @dscowan): devices the integration no longer provides — an inverter removed from the station or the configuration, a battery module no longer reported, a dissolved parallel group, or a legacy-format duplicate left behind by an older version — can now be deleted from their device page (**Settings → Devices & Services → device → three-dot menu → Delete**), without deleting and re-adding the whole integration entry. Absence is proven over an observation window, not a single poll: any one cycle's payload is a subset of the truth (battery slots rotate round-robin, cloud payloads omit modules, discovery hiccups drop the parallel-group row), so the coordinator tracks when each device was last provided and deletion is allowed only after 15 minutes of continuous absence — or, for battery modules and battery banks, the 6-hour eviction window battery tracking already uses — observed within an unbroken run of updates that were **verified complete**. A cycle can report success while its discovery silently failed (the cloud device-list call and each per-device battery fetch are swallowed inside the library and publish an empty-but-"successful" table), so a cycle only counts toward absence once its device list *and* every battery-capable parent's fetch are confirmed; a cached-through-an-outage cycle, a swallowed device-list failure, or a battery-endpoint failure each restart the relevant class's clock rather than aging a still-live device toward deletion. Practically: after an HA restart, wait 15 minutes before deleting a stale inverter/GridBOSS/parallel group/station and 6 hours before deleting a stale battery module (about 12 hours after physically removing a module, since battery tracking keeps it visible for its first 6 hours of absence); a device the running session has never once observed — a ghost already gone before the restart — is held to the conservative 6-hour window regardless of type, since its class cannot be confirmed. Devices still being provided are always refused (their entities would immediately recreate them under fresh registry entries), as is everything while the last update failed or is being served from cache. Each battery module is judged against its own parent inverter's completeness, so a degraded inverter (link down, or not yet reporting batteries) blocks deletion of its own modules only, never a healthy sibling's; a module whose parent has since left the table, and one the running session has never observed, fall back to a conservative whole-subsystem check. A refused deletion is a recoverable annoyance; a wrongly permitted one destroys entity customizations irreversibly, so that fallback stays conservative. (One documented residual: a HYBRID system whose cloud battery supplement fails from a cold restart can still age out a 5th-or-later module never seen this session — bounded by and consistent with the #258 carry-forward, and self-healing when the module reappears.)

### Changed

- **AC Charge Start Battery SOC entity extended to EG4_HYBRID** (follow-up to [#331](https://github.com/joyfulhouse/eg4_web_monitor/issues/331)): the reg-160 AC-charge start-SOC number, previously created only on EG4_OFFGRID, is now also created on positively-identified EG4_HYBRID inverters (fails-closed `is_hybrid_family()` gate — LXP and unidentified hardware are excluded until verified). Hardware evidence from a FlexBOSS21 (fw FAAB-2727, local dongle Modbus, read+write verified): reg 160 initiates AC charging whenever battery SOC is below its value — in or out of the AC-charge time windows and regardless of the reg-120 ACChargeType selector — so with the entity hidden, the factory default of 90 silently pins a ToU-managed battery high around the clock (grid-charging outside every window), while a low value silently prevents the scheduled in-window charge; the portal/app exposes the same field for the family as "Start AC Charge SOC(%)". Local polling reads the register on both families, so pure-LOCAL installs see the value too. Writes cap at 90% (pylxpweb's register definition), and cloud writes are checked by a readback that fails the write only on a *definite, persistent* mismatch — the register still reading a different value across a short settle re-read (so a write that applies a beat after the portal's ACK is not falsely reported as a failure). The readback is deliberately fail-safe toward the write: a readback that cannot testify — one that times out, omits the key, or returns a non-numeric value — trusts the acknowledged write rather than failing it, so it narrows the acknowledged-but-unapplied no-op class without eliminating it. Reg 161 (*End*) stays EG4_OFFGRID-only: the [#332](https://github.com/joyfulhouse/eg4_web_monitor/pull/332) note records it read-only on grid-tied hardware, and pylxpweb models the grid-tied stop threshold as reg 67 (the existing AC Charge SOC Limit entity, which reg-67 writes now also refresh alongside Start). Entity *creation* on EG4_OFFGRID is unchanged (both Start and End remain); the 90% Start write cap and the cloud readback apply on that family too — an off-grid Start value above 90 written through an earlier version still displays, but can only be re-written at 90 or below from now on.

- **pylxpweb pin raised to [0.9.39b8](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b8)**: the post-merge review of the device-removal PR found that pylxpweb's transport-side battery clock (`_battery_cache_time`) was stamped even when a BMS block read failed — which would have let a cold-restart battery-read outage masquerade as a confirmed empty bank on one leg of the new removal guard. The library now stamps it only when a battery fetch actually delivered data, with a separate per-attempt clock preserving the read cadence (a no-BMS secondary is not re-read every cycle).

### Fixed

- **Device-removal guard hardening** ([#539](https://github.com/joyfulhouse/eg4_web_monitor/pull/539), from the same post-merge review): the empty-plant confirmation call runs under the shared per-account cloud request budget from [#533](https://github.com/joyfulhouse/eg4_web_monitor/pull/533) instead of stacking an extra request on a saturated portal; and the battery-fetch confirmation now requires the success clock to be *fresh* (30-minute bound), not merely set — so a battery endpoint that succeeded once and has been silently failing since cannot age a live battery module toward deletion. With this release's pylxpweb pin the freshness gate is fully effective; the guard only ever gets stricter, never looser.

## [3.5.1-beta.7] - 2026-08-03

### Changed

- **pylxpweb pin raised to [0.9.39b7](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b7)** — the library half of the same audit wave 3.5.1-beta.6 shipped, reviewed by the same four-model gate: atomic Quick Charge bitfield updates (a concurrent sibling-bit write can no longer be erased by a Quick Charge start/stop), coalesced cloud session renewal (one login instead of a herd when the session expires — this also activates the per-account request limiter's auth-task handoff from #533), corrected holding-register-120 field modeling (the AC-charge/discharge selectors were decoded and written at wrong bit positions on the local path), strict FC16 write-acknowledgement validation, and dongle TCP frame assembly with a terminal `async_shutdown()` — which activates the fast-teardown seam #529 already feature-detects, so unloading the integration no longer waits behind an in-flight dongle retry loop.

## [3.5.1-beta.6] - 2026-08-03

This is a **hardening release**: alongside the diagnostics platform, it delivers the full remediation wave from a codebase-wide register, race and performance audit ([#524](https://github.com/joyfulhouse/eg4_web_monitor/pull/524) documents the findings) — nineteen reviewed PRs merged as one composed train and gated by a four-model adversarial review. Most fixes target failure windows (concurrent writes, stale polls, partial setup, shared gateways) rather than day-to-day behavior. The release was validated against live hardware in all three connection modes (Cloud/Local/Hybrid docker sweep: 572/592/630 entities, zero unavailable, values cross-checked against the production install and the EG4 portal).

### Added

- **Diagnostics download**: *Settings → Devices & Services → EG4 Web Monitor → ⋮ → Download diagnostics* now produces a JSON dump of the config entry and the coordinator's current data — what the cloud or your local transport actually returned — so a bug report can carry the evidence without a capture round-trip. Credentials, hosts, the plant name and station identity/location fields are redacted outright, and a non-default portal URL is treated as private topology and redacted too; device, dongle and battery serial numbers are replaced with aliases (`SN_1`, `SN_2`, …) everywhere they appear — as dict keys, as values, lowercased inside derived strings, and embedded inside longer strings such as unique IDs — and the plant id becomes `PLANT_1`, so the dump stays correlatable without exposing identifying values. The download also works on an entry whose setup failed (a config-only snapshot), which is exactly when a reporter needs it. The bug-report form now asks for this file (and for debug logs) up front; note that **debug logs, unlike the diagnostics download, contain serials and the plant id as-is** — the form says so.

- **Battery Temperature sensor for inverters** ([#521](https://github.com/joyfulhouse/eg4_web_monitor/pull/521)): pylxpweb has always decoded input register 67 / cloud `tBat` into the coordinator's data — but the sensor description was missing, so the entity was silently never created even though documentation referred to it. It is now a diagnostic temperature sensor on every connection type. The firmware's `0x7F` "no reading" sentinel (a no-BMS secondary, [#348](https://github.com/joyfulhouse/eg4_web_monitor/issues/348)) renders as unknown rather than a plausible-looking 127 °C.

- **Read-only runtime diagnostics on Local and Hybrid** ([#522](https://github.com/joyfulhouse/eg4_web_monitor/pull/522)): four new diagnostic sensors decoded from canonical input registers — **EPS Apparent Power** (I25, phase-aware: split-phase systems get the aggregate, three-phase systems get an explicitly R-phase entity, unresolved topology gets neither), **Inverter Running Time** (I69–70, raw seconds as a measurement — deliberately not `total_increasing`, since reset behavior across reboots is unproven), **AC Input Type** (I77 bit 0: Grid / Generator), and parallel-topology phase/role (I113). All are **disabled by default**, read-only, and only mapped where the decoding is hardware-evidenced; unproven neighboring bits stay unmapped.

### Fixed

- **A control you set no longer flips back to its old value moments later** ([#527](https://github.com/joyfulhouse/eg4_web_monitor/pull/527), [#519](https://github.com/joyfulhouse/eg4_web_monitor/pull/519)): a parameter poll that *started before* your write could land *after* it and overwrite the acknowledged new value with the stale one it had read — the classic "slider snaps back, then recovers a cycle later". Write acknowledgements now carry a generation stamp: a read from an older cycle cannot retire them, confirmed values are held through a grace window against exactly this race, and unconfirmed seeds expire after 30 minutes so a genuinely failed write cannot masquerade as applied forever. Number entities' optimistic state is likewise wired to real post-write updates (#519).

- **Concurrent control writes can no longer interleave halfway** ([#526](https://github.com/joyfulhouse/eg4_web_monitor/pull/526)): logical operations that span multiple register writes (schedule time windows, battery control mode changes) are serialized per device, so two near-simultaneous automations can no longer leave a window that is half of each request. The locks survive an integration reload mid-operation.

- **Two config entries behind one gateway no longer talk over each other** ([#529](https://github.com/joyfulhouse/eg4_web_monitor/pull/529)): Modbus gateways and WiFi dongles are effectively single-connection devices, but two entries sharing the same host and port could interleave frames — including during the initial transport attach, which now also runs under the shared per-endpoint lock. Operations against one physical endpoint are serialized across entries.

- **Mixed Modbus and dongle stations poll on schedule again** ([#523](https://github.com/joyfulhouse/eg4_web_monitor/pull/523)): a station mixing Modbus-TCP and WiFi-dongle transports could starve one transport group behind the other's cadence gate. The poll-due decision is normalized across transports (with an explicit "never polled" state instead of a zero timestamp that misreads as "just polled" on a freshly booted host).

- **A Local read cycle that fails processing is now marked stale instead of silently serving old data** ([#525](https://github.com/joyfulhouse/eg4_web_monitor/pull/525)): when mapping a device's local payload raises, the device — and the station/group aggregates built from it — are flagged stale rather than continuing to present the last good values as fresh. Only devices that had actually published fresh data are flagged, so a still-warming device is not spuriously marked.

- **A setup failure now unwinds completely** ([#520](https://github.com/joyfulhouse/eg4_web_monitor/pull/520)): when entry setup fails partway through platform forwarding, the platforms already set up are unloaded and the cloud client closed before the error propagates — instead of leaking listeners, sessions and half-registered platforms until the next restart. The original setup exception is always the one reported.

- **Controls whose backing value arrives late are created without a reload** ([#534](https://github.com/joyfulhouse/eg4_web_monitor/pull/534)): a control entity whose parameter only shows up after startup (a slow first cloud parameter read, a briefly offline device) is now created the moment the value appears. Control unique-IDs also migrate to serial-based identities — a model string change can no longer duplicate every control — and control availability again follows its documented contract (a device-level *fetch error* marker no longer blanks controls whose underlying parameter data is still valid).

- **Removing one config entry no longer degrades the others** ([#531](https://github.com/joyfulhouse/eg4_web_monitor/pull/531)): unloading an entry suppressed pylxpweb library logging for every remaining entry, and registry cleanup could act on another entry's devices. Cleanup is now scoped per entry, library logging is reference-counted — and as a hard safety floor, registry pruning refuses to run at all when the coordinator has no live devices, so an empty first refresh can never sweep a working install's device registry.

- **Parallel-group device migration is evidence-based** ([#517](https://github.com/joyfulhouse/eg4_web_monitor/pull/517)): stale parallel-group registry entries (including the legacy GridBOSS-serial-keyed form) are migrated only when member evidence ties the old identity to exactly one current group, with a strict one-to-one fallback for a single stale entry whose legacy serial is a live device. Anything ambiguous is left untouched instead of guessed at.

- **Cloud request volume is bounded and deduplicated** ([#533](https://github.com/joyfulhouse/eg4_web_monitor/pull/533)): concurrent requests against one portal account are capped at three slots shared across all of that account's config entries, duplicate in-flight firmware checks for the same device coalesce into one request, and firmware prefetch fans out at most three at a time. A timeout that occurs while the budget is saturated is treated as *inconclusive* for the [#511](https://github.com/joyfulhouse/eg4_web_monitor/issues/511) connectivity breaker — queue pressure is not evidence the portal is down.

- **Side-fetch breaker coverage is complete** ([#518](https://github.com/joyfulhouse/eg4_web_monitor/pull/518)): the shared connectivity breaker introduced for [#511](https://github.com/joyfulhouse/eg4_web_monitor/issues/511) now also covers firmware-update polls and the call sites the first pass missed, with consistent half-open probing so one probe (not a thundering herd) tests a recovering portal.

- **Cloud login cookies are isolated per config entry** ([#535](https://github.com/joyfulhouse/eg4_web_monitor/pull/535)): entries previously shared Home Assistant's default cookie jar, so two portal accounts (or one account in two entries) could clobber each other's session and force re-authentication loops. Each entry now uses a private cookie session with the same SSL settings, closed on unload.

- **Cloud and Hybrid can no longer configure the same remote plant twice** ([#530](https://github.com/joyfulhouse/eg4_web_monitor/pull/530)): config entries previously used `username_plant` in Cloud mode but `hybrid_username_plant` after adding a local transport, so Home Assistant treated the same portal account and station as two different installations. Both coordinators could then poll the same plant and compete for the same devices and entities. Cloud identity is now the account-plus-plant pair regardless of connection mode, and reconfigure updates that identity when the account or cloud/local makeup changes. Existing entries migrate without deletion or merging: an entry already using the canonical Cloud identity wins; otherwise the oldest matching entry is retained, while every losing duplicate is left byte-for-byte intact and stopped with a migration error for manual recovery. Existing Local-only identities are preserved, and a real Cloud-to-Local transition releases its cloud identity so the plant can be configured elsewhere.

- **An unreachable EG4 portal no longer costs tens of dead seconds every poll cycle** ([#511](https://github.com/joyfulhouse/eg4_web_monitor/issues/511)): every supplemental cloud fetch (quick-charge status, per-string PV energy, the event log, the AC Couple / Smart Load parameter stores, voltage limits) bounds its call with a timeout — which caps each call, but on a portal that is genuinely unreachable (blocked egress, DNS blackhole) every one of them still burned its full timeout every cycle, serially, forever. They now share one connectivity breaker: after three consecutive connectivity-class failures the supplemental fetches are skipped instantly for five minutes, then retried. Only connectivity-class failures count — an HTTP-level answer from the portal (even an error) proves it is reachable and closes the breaker. Entity behavior is unchanged: skipped fetches take the exact same carry-forward path a timed-out fetch always took, just without the wait, and the main runtime polling is not affected. A single warning log line announces the pause.

- **Smart Load switch moved to the Configuration section** (from #499's follow-up question): the switch shipped in 3.5.1-beta.5 without an entity category, so Home Assistant filed it under *Controls* while Grid Always On and the five Smart Load threshold numbers from the same portal panel all sit under *Configuration*. It now declares the configuration category and the panel's seven entities appear together. The #499 reporter also **hardware-confirmed the write path** (a toggle in Home Assistant reflects in the portal), so the switch's unverified-write caveat is retired.

### Changed

- **Coordinator update fan-out is scoped to what changed** ([#532](https://github.com/joyfulhouse/eg4_web_monitor/pull/532)): entity listeners are notified per device instead of every entity re-evaluating on every refresh — a meaningful reduction in per-cycle work on installations with hundreds of entities. Firmware update entities also publish their in-progress state immediately when an install starts and ends, instead of waiting for the next poll.

- **Quality tooling hardened** ([#528](https://github.com/joyfulhouse/eg4_web_monitor/pull/528), [#513](https://github.com/joyfulhouse/eg4_web_monitor/pull/513)): the local lint/type/test runners now fail honestly instead of masking missing tools (mypy pinned, same rationale as the ruff pin), bare `pytest` picks up the canonical configuration, and the test suite hard-refuses live EG4 cloud access — a test can no longer silently depend on the real portal. No shipped code in these.

## [3.5.1-beta.5] - 2026-08-02

### Added

- **The rest of the Smart Load panel** ([#499](https://github.com/joyfulhouse/eg4_web_monitor/issues/499), requested by @brendonlobo123): the portal's *Maintenance → Remote Set → Smart Load Port → Smart Load* tab is now exposed. **Grid Always On** shipped in 3.5.1-beta.4 ([#484](https://github.com/joyfulhouse/eg4_web_monitor/issues/484)); this adds the six controls beside it — a **Smart Load** enable switch, **Smart Load Start SOC** and **End SOC**, **Smart Load Start PV Power** (kW), and **Smart Load Start Voltage** and **End Voltage**. The SOC pair and the voltage pair appear to be alternatives, the reporter's 12000XP showing the voltage pair greyed out while SOC mode is active; which one an inverter acts on has not been tested here, so both are offered rather than one being hidden on an assumption. **All seven are disabled by default** — they only matter once the smart load port is configured, so enable them from the entity settings if you use that port. Not restricted by inverter model or family: all six parameters answered on an 18kPV and a FlexBOSS21 in a read-only cloud check, and the reporter runs them on a 12000XP.
- **Cloud connections only.** These controls are written through the EG4 cloud, on Cloud *and* Hybrid connections alike. None of them has a local Modbus path — no register is pinned for any of the five thresholds, and the enable function lives somewhere in holding register 179 with the bit unconfirmed, the same situation as Grid Always On. So they are not created on Local-only connections, where they could not be read at all.
- **They report unavailable rather than guessing.** An inverter whose cloud data does not include one of these settings would otherwise show a confident 0% or 0 kW. That the cloud really does answer with the enable function present and the five thresholds missing is not a guess — it is exactly what a GridBOSS returns (it has its own per-port smart-load controls instead; these entities are only ever created for inverters, never for a GridBOSS). Each entity stays unavailable until a real value arrives.
- **⚠️ Reading is verified; writing is not.** The values shown come from the same cloud parameter read the portal uses, checked against real hardware. **The write side has only ever been reasoned about, never observed:** no inverter has been seen acting on any of these seven controls, because the evidence behind this feature is a *read-only* probe — nothing was written to a device. Changing one sends the corresponding named cloud call, and that is as much as can honestly be claimed today. **Please report back on [#499](https://github.com/joyfulhouse/eg4_web_monitor/issues/499)** whether a change you make actually takes effect on the inverter — that is the missing half, and the same confirmation that closed out Grid Always On.
- Requires **pylxpweb 0.9.39b6** or newer, which the release carrying this feature pins. Installing this integration release alone is **not** enough if your pylxpweb is older — the version constraint is what upgrades it. On an older version the seven entities stay unavailable and a write reports which version is needed, rather than failing obscurely.

- **The AC Couple switch now works on Local and Hybrid connections** ([#472](https://github.com/joyfulhouse/eg4_web_monitor/issues/472)): the switch introduced in 3.5.1-beta.2 ([#471](https://github.com/joyfulhouse/eg4_web_monitor/issues/471)) was cloud-only — pure-Local installs had no switch at all, and Hybrid installs routed every read and write through the portal. pylxpweb now maps the function to **holding register 179 bit 11**, so Local installs get the switch reading and writing over Modbus with no cloud involved, and Hybrid installs go local-first with the existing cloud fallback when the local write fails or the link is down. Cloud connections are unchanged. Two honest caveats: the bit ships on **lineage inference** rather than a hardware toggle capture — the Luxpower Modbus documentation and the ant0nkr/luxpower-ha-integration map both place it at 179 bit 11, the same 16-bit layout whose bits 3/7/9/10 are hardware-proven on EG4 hardware, and #471's reporter has driven the control through this mapping with agreeing named reads; a toggle capture on EG4 hardware would still upgrade it (see [#472](https://github.com/joyfulhouse/eg4_web_monitor/issues/472)). And on **pure-Local** connections there is no capability signal to gate on — register 179 decodes to a bool on any inverter that answers it — so the switch appears on every control-capable inverter, reading Off where there is no AC-coupled input, whereas Cloud and Hybrid can still tell "device doesn't report the function" and show unavailable instead. Requires pylxpweb 0.9.39b6 for the local half; older installs keep the cloud-only behaviour.

### Changed

- **A battery that loses its cell block now stays listed instead of disappearing** ([#506](https://github.com/joyfulhouse/eg4_web_monitor/issues/506)): the integration decided whether an individual battery slot was real by checking for zero voltage *and* zero state of charge. That is how an empty register slot reads, but it is also how a battery reads when it loses its cell block while its BMS keeps reporting live current, temperature and cycle count — a present-but-degraded battery, not an absent one. Such a battery vanished from Home Assistant entirely, taking its still-valid readings with it, exactly when a user most needs to see that something is wrong with it. The integration now defers to pylxpweb's canonical definition, which additionally requires current, temperature, cycle count, cell count and both cell lists to be empty before calling a slot absent. A degraded battery stays listed, with unknown voltage and power (zero volts is the protocol's honest "absent" encoding, so power is reported as unknown rather than a plausible-looking 0 W) and its live values intact. Genuinely empty slots are still skipped, so no phantom batteries appear.
- This also removes three separate inline copies of the old rule — the local round-robin accumulator, the Hybrid cloud overlay, and the freshness probe that decides whether local battery data should keep a cloud-lost inverter's sensors alive ([#479](https://github.com/joyfulhouse/eg4_web_monitor/issues/479)). The third had drifted out of the issue's scope but described itself as mirroring the first, so leaving it would have reintroduced the same inconsistency. All three now share one implementation.
- **The new definition takes effect with pylxpweb 0.9.39b6.** Against an older library the integration keeps its previous voltage/SOC-only behaviour rather than failing, so the change lands exactly when the dependency pin moves.

- **Charge Last and Share Battery report unavailable instead of a false Off when their state is unknown** ([#497](https://github.com/joyfulhouse/eg4_web_monitor/issues/497)): both switches read their state from a single function parameter, and when that parameter was missing entirely they displayed a confident, toggleable **Off** — indistinguishable from the inverter actually reporting the function disabled. They now show as unavailable until a real value arrives, the same guarantee AC Couple ([#471](https://github.com/joyfulhouse/eg4_web_monitor/issues/471)) and Grid Always On ([#484](https://github.com/joyfulhouse/eg4_web_monitor/issues/484)) already give. Neither switch is restricted by inverter model or family, so "this device does not report the function" is a real possibility rather than a contradiction, which is what made the false Off reachable. **Known behavior change:** on every connection type these two switches read unavailable rather than Off **until a real value for the function arrives**. Normally that is a brief window at startup, but it is not time-bounded, and on Cloud connections it is not simply "the first read": the portal's generic parameter read can succeed while omitting this particular function, and the switch stays unavailable until the function itself is reported. That is the point of the change rather than a side effect of it. On Local and Hybrid connections both values are decoded from holding register 110 (bits 4 and 3) on every inverter family, so they populate as soon as the first register read lands and stay populated — a later partial read cannot blank them, because previously-read values are carried forward. **If you automate these switches:** `switch.turn_on` / `switch.turn_off` targeting an unavailable entity are **skipped** — Home Assistant filters unavailable entities out of the call, so nothing happens and no error is raised, where previously the call would act on the fake Off. Charge Last is enabled by default, so an automation that toggles it at Home Assistant startup is the realistic case — trigger it on the entity becoming available, rather than firing at a fixed moment after start.

### Fixed

- **Per-string PV energy sensors now populate on Cloud connections** ([#495](https://github.com/joyfulhouse/eg4_web_monitor/issues/495), reported by a 6000XP owner): the **PV1/PV2/PV3 Yield** (daily) and **Yield Lifetime** sensors have existed for a long time but were only ever fed by local Modbus registers — Cloud-only installs got the entities and never a value. They are now filled from EG4's chart endpoints (the same figures the portal's energy charts show), with the scaling live-verified: the three per-string lifetimes on a dev inverter sum exactly to the portal's total lifetime yield. The sensors remain **disabled by default** — enable them from the entity settings. Practical notes: the cloud exposes strings 1–3 only, so PV4–6 still need a local connection; daily values refresh about every 5 minutes and lifetime hourly (at most 15 requests/hour per inverter, and zero extra requests on Hybrid when local registers already supply the values); chart days follow the **station's** timezone, not Home Assistant's, so month boundaries land at the plant's midnight; and lifetime totals are guarded against partial cloud responses — a response missing a year of history is rejected rather than being allowed to look like a meter reset and permanently corrupt long-term statistics. That guard persists a small state file per config entry (removed with the entry) so a Home Assistant restart cannot re-open the window it closes.

- **Firmware update chains no longer abort on a partially upgraded device** ([#353](https://github.com/joyfulhouse/eg4_web_monitor/issues/353), delivered by the pylxpweb 0.9.39b6 pin): EG4's `standardUpdate/run` takes no component selector — the server picks which component a run installs, and on a partially upgraded device it can pick one that is **already at the target version**. That run downloads and flashes normally but cannot move the version string, and the orchestrator read the first unchanged version as a dead chain and aborted — so the component that actually needed upgrading never ran. A 6000XP stuck at `ccaa-1E1415` reproduced the same 0% → 100% → "No firmware version progress" loop on every retry. The orchestrator now tolerates a bounded number of completed-but-unchanged steps (with positive evidence the step ran and did not report FAILED) and keeps going until the chain genuinely converges. Busy handling also split: **before** anything has started, a busy device fails fast instead of holding the update for the whole retry budget (the reporter watched "Installing" for five minutes before being told the device was busy the entire time), while mid-chain settling keeps its own wider budget because a component reboot can outlast the post-start grace. A mid-chain "already the latest version" refusal after a successful step is reported as convergence, not surfaced as a raw API error.

- **The test suite no longer burns 25 minutes of wall clock** ([#510](https://github.com/joyfulhouse/eg4_web_monitor/pull/510)): no shipped code changed — tests reaching pylxpweb's cloud request layer were spending exponential-backoff sleeps waiting on requests that could never succeed. A conftest guard now refuses the real request path (and the direct-session path that bypasses it) instantly; the full suite went from 25:21 to under two minutes. Strict enforcement and a shipped-side unreachable-portal cost bound are tracked in [#511](https://github.com/joyfulhouse/eg4_web_monitor/issues/511).

## [3.5.1-beta.4] - 2026-07-27

### Added

- **Grid Always On switch for the smart load port** ([#484](https://github.com/joyfulhouse/eg4_web_monitor/issues/484), requested by @brendonlobo123): the portal's *Maintenance → Remote Set → Smart Load Port → Smart Load* tab carries a **Grid Always On** enable/disable that keeps the smart load port energized from the grid instead of dropping it when the Smart Load SOC window closes. It is now exposed as a switch. **Disabled by default** — it only matters once the smart load port is configured, so enable it from the entity settings if you use that port. Not restricted by inverter model or family: the function comes back in the cloud parameter read on every device checked (18kPV, FlexBOSS21, GridBOSS) and the reporter's screenshot shows it live on a 12000XP, so it is offered wherever it can be read.
- **Cloud connections only.** This control writes through the EG4 cloud, exactly as the portal does. Unlike most switches it has no local Modbus path, and it is **not created wherever its state would have to come from local registers** — Local-only connections, and Hybrid connections with a local transport attached — because there it could not be read at all. (Older "flat" Hybrid entries, whose parameters still come from the cloud, do get it.) The reason is deliberate: the function lives somewhere in holding register 179, but *which bit* has never been confirmed on hardware. Writing a guessed bit is not a safe failure — the firmware acknowledges the write either way, so the cloud fallback would never trigger and a read-back check could not detect the mistake. If someone captures a raw register 179 toggle from the portal, the bit can be pinned and the local path added; until then the cloud is the only route that is known to hit the right thing.
- **It reports unavailable rather than guessing.** Because the switch is offered on every control-capable inverter rather than a fixed model list, a device whose cloud data simply does not include this function would otherwise show a confident, toggleable **Off**. Instead the switch shows as unavailable until a real value arrives.
- **The write path itself has not yet been confirmed on hardware.** The read side is verified — the value the switch displays comes from the same cloud parameter read the portal uses. Toggling it sends the same `FUNC_ON_GRID_ALWAYS_ON` function-control call the portal sends, but no one has yet observed an inverter act on it. Please report back on [#484](https://github.com/joyfulhouse/eg4_web_monitor/issues/484) if it does or does not take effect.

### Fixed

- **Internal Temperature no longer shows a false 0 °C / 32 °F on cloud connections** ([#490](https://github.com/joyfulhouse/eg4_web_monitor/issues/490), reported by @brendonlobo123): the EG4 cloud relays a constant `tinner: 0` for some inverters while the radiator temperatures read live values, so the sensor displayed a permanently wrong 0. A cloud-sourced Internal Temperature of exactly 0 is now reported as **unknown** instead. The sensor is still created for every inverter, and local (Modbus/dongle) connections are unaffected — they read the temperature register directly, and there is no evidence against that path. **This is deliberately not a per-model rule.** The defect splits *within* one device type code (54): a 12000XP reports the constant 0, but a 6000XP reports live values of 31-32 °C alongside radiators at 58-65 °C, and nothing in the cloud data distinguishes the two models — so suppressing the sensor by model family would have hidden a reading that demonstrably works. **Trade-off:** 0 °C is a legitimate temperature, so an inverter genuinely sitting at 0 on a cloud connection will now read unknown rather than 0. That is a small, bounded loss against a permanently wrong value, and no other reading is affected.
- **An unidentified inverter could permanently lose its Battery Discharge Power sensor**: the startup cleanup that removes this sensor from non-off-grid models treated the placeholder family `UNKNOWN` as a positive identification, so an inverter whose family had not been resolved was misclassified as non-off-grid and had the entity removed, irreversibly. This needed two things to go wrong at once — a failed parameter read leaving the family unresolved, *and* a model name the integration does not recognise, since recognised names (6000XP, 12000XP, FlexBOSS21/18, 18kPV, 12kPV) already recover the family from the model. Narrow, but unrecoverable when it hit. Unresolved inverters now keep their entities until the family is actually known.
- **The same cleanup could reach into per-battery and battery-bank entities.** It matched any entity whose ID merely *ended* with the sensor name, which would have included per-battery and bank entities had a shared sensor name ever been added to it. It now matches only the inverter's own entities, and errs toward leaving anything unrecognised alone.
- **A single failed parameter read could permanently delete the Battery Discharge Power sensor on off-grid inverters**: the startup cleanup that removes this sensor from non-off-grid models treated the placeholder family `UNKNOWN` as a positive identification, so an inverter whose family had not been resolved yet — which is what one transient parameter-read failure produces — was misclassified and had the entity removed, irreversibly. Unresolved inverters now keep their entities until the family is actually known. The same cleanup could also reach into per-battery and battery-bank entities that share a sensor name; it is now scoped to the inverter's own entities.
- **`EventRow.eventType` is no longer declared a closed enum in the API spec**: `docs/api/openapi.yaml` both listed `enum: [FAULT, WARNING, INFO, MIDBOX_WARNING]` and told consumers to treat unknown values as passthrough — contradictory, since the enum rejects exactly what the description promises to accept. The four values are documented as *observed* instead. Spec-only; `normalize_event_row` already passed unknown categories through, so no behavior changes. Matches the corresponding correction in pylxpweb ([#236](https://github.com/joyfulhouse/pylxpweb/issues/236)), keeping the two copies of this schema in agreement.
- **Select and number controls no longer snap back to the old value when the post-write refresh fails** ([#379](https://github.com/joyfulhouse/eg4_web_monitor/issues/379), [#362](https://github.com/joyfulhouse/eg4_web_monitor/issues/362) follow-up): Operating Mode, PV Input Mode, Smart Port Mode, Battery Charge/Discharge Control and every number control cleared their optimistic value the moment the write returned — before, or regardless of, the parameter re-read that was supposed to confirm it. When that re-read failed (a single register range timing out is routine), the entity republished the stale pre-write value, so a write the inverter had accepted looked like it had been rejected. They now keep the acknowledged value until real device data arrives. Smart Port Mode was the worst case: its refresh is debounced and returns before any new data exists, so it reverted every single time.
- **A retained value can no longer stick forever** ([#379](https://github.com/joyfulhouse/eg4_web_monitor/issues/379)): schedule time entities have retained acknowledged writes since 3.4.0-beta.18 with no upper bound. If the firmware silently ignored a write (as it does for some registers on some models) and the follow-up read failed in the same moment, the entity would show a time the inverter never took, indefinitely and with no warning. Retention on every control platform now expires after 5 minutes without device confirmation, logging a warning and reverting to the reported state — the same bound switches got in 3.5.1-beta.2. All four platforms (switch, select, number, time) now share one implementation of these semantics.
- **Switch toggles no longer wait out a doomed Modbus timeout when the local link is already known down** ([#485](https://github.com/joyfulhouse/eg4_web_monitor/issues/485), found by review on PR #477): on a Hybrid connection, number/select/time controls already wrote straight through the cloud when pylxpweb had flagged the local transport link down, but switches still attempted the local read-modify-write first. Switches now use the same shared routing helper, so the platforms cannot drift apart again. Post-review hardening also closes both ways the acknowledged cloud value could still be lost or delayed: a known-down switch write schedules no post-write local runtime/parameter recovery probe (the optimistic value is retained until a parameter refresh — not the 20-30 second data poll — reads the device back, or until the 5-minute retention bound expires. That read is not necessarily an hour away: an incomplete or failed read deliberately does not arm the hourly throttle, so it retries from the #282 2-minute floor until it succeeds), and a soft-failed cloud parameter range with `parameters_complete=False` now reports an incomplete refresh instead of clearing optimistic state onto pylxpweb's retained stale values (the [#362](https://github.com/joyfulhouse/eg4_web_monitor/issues/362) failure shape). Local-only connections are unchanged — without a cloud route, the local write is still attempted and its error reported as before.
- **Log noise: a routine incomplete parameter read no longer logs two warnings** ([#485](https://github.com/joyfulhouse/eg4_web_monitor/issues/485), found by review): a partial parameter read is ordinary — one misrouted dongle frame routinely fails a single register range, which is why the integration already carries values forward and retries. It nevertheless logged a warning from the refresh itself *and* a second one from the control that requested it, and every switch toggle during a local-link outage logged the deliberate cloud-only path as a failed refresh. The refresh-side message is now debug, the deliberate skip is no longer described as a failure, and a genuine post-write refresh failure still warns exactly once.

## [3.5.1-beta.3] - 2026-07-25

Two live-reported control and data-integrity fixes: sensors no longer freeze
at stale values when the portal loses an inverter, and the Off-Grid Mode
switch works on Local and Hybrid connections. Requires
[pylxpweb 0.9.39b4](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b4)
(installed automatically).

### Fixed

- **Cloud-lost inverters no longer freeze at their last values** ([#479](https://github.com/joyfulhouse/eg4_web_monitor/issues/479), reported by @ivanfmartinez): when an inverter's dongle loses its internet link, the EG4 portal keeps answering with the last register mirror it received (flagged only by `lost: true`), so on Cloud connections every runtime/energy sensor silently froze at its pre-outage value for the whole outage. Measurement sensors — including individual battery values, parallel-group aggregates, and the Hybrid cloud-supplemental load-split sensors — now read **unknown** while the portal reports the inverter lost; the device stays present with `Cloud Status` reading *offline*, the `Connection Lost` sensor on, and static ratings/diagnostics intact. The repeating `battery_bank_power: cannot calculate` warning during such outages is demoted to debug (and names the bank's serial where the source provides one). The companion pylxpweb 0.9.39b4 fix also accepts the legitimate post-reconnect energy catch-up delta immediately instead of rejecting it as a spike for five polls.
- **Off-Grid Mode switch now works on Local and Hybrid connections** ([#476](https://github.com/joyfulhouse/eg4_web_monitor/issues/476), reported by @scottjvincent; also the unexplained tail of [#194](https://github.com/joyfulhouse/eg4_web_monitor/issues/194)): the local register map placed green/off-grid mode at register 110 bit 8, but a live toggle test on an 18kPV (2026-07-21) pinned the real bit at 14 — so local toggles wrote the wrong bit, reported success, and never fell back to the cloud, while the switch state read the same wrong bit. pylxpweb 0.9.39b4 moves green mode to the hardware-verified bit 14 for every inverter family (the register-110 upper-bit layout is now unified lineage-wide: buzzer bit 7, green 14, battery ECO 15, unverified slots explicitly unmapped). If you toggled Off-Grid Mode from HA on a Local/Hybrid connection before this fix, it is worth a look over your inverter's settings in the EG4 portal. What is established is that those toggles sent a write at register 110 bit 8 and the firmware accepted it; what that bit does, and whether the value persisted or had any effect on the device, is not established. An external register map (ant0nkr/lxp_modbus) puts PV CT sampling in that area, but this project has never verified it, and pylxpweb now marks bits 8–9 explicitly unknown rather than repeat an unproven name.
- **Off-Grid Mode (Green Mode) local control enabled for the EG4 off-grid family** (12000XP/6000XP/SNA): previously this family routed green-mode writes through the cloud because the bit position had never been confirmed on it. The register-110 layout is now shared across families, so the switch writes locally with cloud fallback like every other family. Worth knowing if you run one of these on a Local or Hybrid connection: bit 14 was toggle-proven on an 18kPV, not on off-grid hardware — it is carried across on lineage (the same external register map agrees with every position this project *has* toggle-tested, on both lineages). If your Off-Grid Mode switch does not visibly take effect after this update, please report it on [#476](https://github.com/joyfulhouse/eg4_web_monitor/issues/476); a raw register toggle capture from a 12000XP or 6000XP would settle it for good.

## [3.5.1-beta.2] - 2026-07-17

Cloud AC couple controls (a switch plus the Start/End SOC window) and a
portal event-log sensor, on top of the 3.5.1-beta.1 firmware-update fixes.
Requires
[pylxpweb 0.9.39b3](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b3)
(installed automatically).

### Added

- **AC Couple Start/End SOC number entities** ([#352](https://github.com/joyfulhouse/eg4_web_monitor/issues/352), requested by @mjstrand): the SOC window governing the AC-coupled source on the inverter's smart port — enabled when battery SOC drops below *Start*, disabled above *End* — scriptable for safe grid/smart-port source transfers. Cloud-only (no local Modbus register): created on Cloud and Hybrid connections for all supported inverters, refreshed from the cloud on a 5-minute cadence (which also picks up portal-side edits), unavailable on devices that do not carry the parameters. A factory-disabled End threshold (`255`, "never stop") shows as unknown with a `disabled_sentinel: true` attribute. Requires pylxpweb ≥ 0.9.39b2.
- **AC Couple switch** ([#471](https://github.com/joyfulhouse/eg4_web_monitor/issues/471), follow-up to #352 suggested by @mjstrand and @ivanfmartinez): enables/disables the inverter's AC couple function (`FUNC_AC_COUPLING_FUNCTION`) outright — de-energizing the AC-coupled source on the smart port at any battery level, without driving the Start/End SOC window. Same cloud-only architecture as the SOC pair (state from the 5-minute cloud read, writes cloud-routed in every mode, unavailable on devices that lack the function param). Requires pylxpweb ≥ 0.9.39b3.
- **Cloud event-log "Last Event" sensor and `fetch_events` service** ([#327](https://github.com/joyfulhouse/eg4_web_monitor/issues/327), requested by @mjstrand): surfaces the portal's own event log — alerts and status messages (e.g. a tripped battery breaker) that never appear in the register data — as a `Last Event` sensor per station, plus a `fetch_events` service that returns recent events for automations (each carries a `record_id` for dedupe). Cloud connections only.

### Fixed

- **Control state no longer briefly reverts after a successful write whose refresh fails** ([#362](https://github.com/joyfulhouse/eg4_web_monitor/issues/362)): a swallowed post-write refresh failure let schedule-time entities and pure-cloud function switches clear their optimistic state and publish the stale pre-write value until the next poll — the service reported success while the entity visibly flipped back. The acknowledged write's optimistic state is now retained until genuinely fresh device data arrives (bounded, with a firmware-NAK escape).

## [3.5.1-beta.1] - 2026-07-15

Firmware-update robustness follow-up to the 3.5.0 line, from a live 6000XP report.

> Requires [pylxpweb 0.9.39b1](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.39b1)
> (installed automatically).

### Fixed

- **Firmware update no longer crashes on the 6000XP's `WAITING` status** ([#353](https://github.com/joyfulhouse/eg4_web_monitor/issues/353), reported by @eode): during a multi-component update the 6000XP reports an `updateStatus` of `WAITING` that the client did not recognize, which raised a validation error and — because the coordinator swallowed it — made the update entity fall back to idle mid-update. The client now recognizes `WAITING` (and coerces any future unrecognized status to a neutral value instead of crashing), and treats it as "still updating".
- **The update entity stays in-progress across the whole multi-component update**: while an HA-initiated firmware install is running the entity now reports in-progress for the entire chain, even when the cloud briefly reports the device idle between components, and a transient poll error no longer blanks the status. The multi-step orchestrator also tolerates a transient "device busy" response on either the eligibility check or the start call (bounded retry) rather than aborting, so a device that is momentarily busy settling one component does not stop the chain.

### Added

- **Reverse-engineered OpenAPI 3.1 reference for the EG4 monitor cloud API** under `docs/api/` (44 endpoints, 55 schemas), for contributors.

## [3.5.0] - 2026-07-13

Stable release: Quick Charge local control on all three connection paths,
multi-step firmware updates, and large battery-bank stability — consolidating the
3.5.0 beta line (beta.1–beta.3). Requires
[pylxpweb 0.9.38](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.38)
(installed automatically).

Highlights across the 3.5.0 line:

- **Quick Charge works on all three connection paths** (beta.3, [#366](https://github.com/joyfulhouse/eg4_web_monitor/pull/366)):
  LOCAL/HYBRID starts write the paired register-233/234 frame; the idle Duration
  stores a restart-safe start preference.
- **Firmware updates run multi-step chains to completion and surface failures**
  (beta.1, [#353](https://github.com/joyfulhouse/eg4_web_monitor/issues/353)):
  multi-component devices (6000XP) converge instead of stopping on a partial
  version.
- **Large battery banks stay live at peak** (beta.3, [#367](https://github.com/joyfulhouse/eg4_web_monitor/issues/367)):
  the bank-current corruption canary scales with battery count.
- Additional beta-line fixes: no-BMS secondary all-unknown ([#348](https://github.com/joyfulhouse/eg4_web_monitor/issues/348)),
  daily-energy float-boundary tick rejection ([#346](https://github.com/joyfulhouse/eg4_web_monitor/issues/346)),
  PV Start Voltage cloud read ([#359](https://github.com/joyfulhouse/eg4_web_monitor/pull/359)),
  AC-charge cloud enable read, and a firmware-orchestrator stale-cache replay.

Post-beta.3 fixes from a Codex re-review of the full 3.4.0 → 3.5.0 change set,
targeted at the #342 DRY/simplifier consolidation:

### Fixed

- **History-import recovery snapshot could drop a run's new days on a
  narrower-range retry** ([#357](https://github.com/joyfulhouse/eg4_web_monitor/pull/357) follow-up):
  the timezone-migration recovery snapshot captured only pre-existing rows, so a
  failed write after a successful clear followed by a retry over a narrower date
  range could discard the days being imported that run (cleared from the DB and
  absent from the snapshot). The snapshot now captures the complete intended
  picture (existing + new), matching what is written and the recovery merge on
  load.
- **Quick Charge Duration briefly showed the stored preference after a live
  write when a prior status read had failed**: the throttled quick-charge status
  cache is now seeded unconditionally after an accepted register-234 write, so
  the entity reflects the written value immediately instead of publishing the
  untouched start preference until the next successful poll.

## [3.5.0-beta.3] - 2026-07-12

Quick Charge local control + a large-bank canary fix.

> Requires [pylxpweb 0.9.38b4](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.38b4)
> (installed automatically).

### Added

- **Quick Charge duration now works on all three connection paths** ([#366](https://github.com/joyfulhouse/eg4_web_monitor/pull/366)): a LOCAL/HYBRID start writes the register 233 activation together with the register 234 duration in one contiguous Modbus frame — the portal-equivalent sequence, live-validated on FlexBOSS21 hardware — so a locally-started charge runs for the requested minutes instead of the firmware default (a lone idle reg-234 write is firmware-rejected, [#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)). If the paired frame is rejected, the start falls back to the proven activation-bit-only write with a best-effort live duration write (on that path the firmware-default length runs if the duration write is refused); the cloud start endpoint is used only when the local activation itself fails (HYBRID). Notes: a locally-started session is per-inverter, while portal starts remain parallel-group-wide; the EG4_OFFGRID (XP) family is unchanged — quick charge control there goes through the cloud endpoints (register 233 is firmware-rejected, [#296](https://github.com/joyfulhouse/eg4_web_monitor/issues/296)), so it requires cloud credentials and remains unavailable on pure-LOCAL XP installs.
- **Quick Charge Duration number**: setting it while idle now stores the per-serial start preference (previously rejected with an error); while a charge runs it still adjusts the live countdown. The preference persists across restarts via a `start_preference` state attribute, immune to mid-charge restart countdown readings.

### Changed

- **Quick Charge Duration idle display** (LOCAL/HYBRID): while no charge is running the entity now shows the stored start preference (default 60) instead of mirroring holding register 234, which the firmware zeroes at session end — the idle mirror was a constant 0. If an automation used `Duration == 0` to detect "charge ended", key it on the Quick Charge switch state instead.

### Fixed

- **Bank sensors went stale at solar noon on large battery banks** ([#367](https://github.com/joyfulhouse/eg4_web_monitor/issues/367), reported by @Caymanwent): the bank-current corruption canary's flat 500 A cap rejected a 9-battery bank's genuine ~750 A charging current (508–514 A observed in the report; the math now passes both by construction). The bound scales with the effective battery count — the larger of the reported count (register 96) and the batteries actually present in the read — at 150 A per battery, with a 500 A floor and a 2000 A physical ceiling (pylxpweb 0.9.38b4). Reporter confirmation at the next solar peak is welcome on [#367](https://github.com/joyfulhouse/eg4_web_monitor/issues/367).
- Write logs no longer claim "via CLOUD API" for transport-routed control methods.

## [3.5.0-beta.2] - 2026-07-11

Fast-follow beta: fixes from a dual (Codex + Claude) bug scan of beta.1.

> Requires [pylxpweb 0.9.38b2](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.38b2)
> (installed automatically). **beta.1 users should upgrade before testing
> firmware updates** — its orchestrator falsely abandoned running update
> steps after ~7 minutes (fail-safe, but the update looked failed).

### Fixed

- **Firmware update orchestrator falsely abandoned running steps** (both scanners, independently): a status-cache interaction replayed a stale idle snapshot for the whole start-grace window, so every realistic multi-step update was reported "no firmware version progress" while the inverter was mid-flash. Every progress poll now bypasses the cache (pylxpweb 0.9.38b2).
- **AC-charge settings read `enabled=false` in cloud mode** (pre-existing): the enable bit was read via a local-transport-only key shape; now routed through the transport/cloud-aware helper (pylxpweb 0.9.38b2).
- **Concurrent firmware installs could double-fire**: HA skips its busy flag for native-progress entities and this entity's `in_progress` lags a poll cycle, so two same-window `update.install` calls could both reach the update API. Installs now serialize on a per-serial lock that survives config-entry reloads.
- **Timezone-migration retry could bake in a duplicate day**: retrying an interrupted tz migration merged stale old-timezone rows left by the failed clear and verification then accepted them permanently (one calendar day double-counted). The retry now drops rows not aligned to the migration's target timezone and re-issues the clear. Alignment also now tolerates zones where DST begins at midnight (Havana/Santiago class), which previously mis-classified valid transition-day rows.

## [3.5.0-beta.1] - 2026-07-11

First beta of the 3.5.0 line.

> Requires [pylxpweb 0.9.38b1](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.38b1)
> (installed automatically).

### Fixed

- **Firmware updates run multi-step chains to completion and surface failures** ([#353](https://github.com/joyfulhouse/eg4_web_monitor/issues/353), reported by @eode): on devices whose firmware carries three version components (6000XP), a single update run advanced only one component (`ccaa-1E1415` instead of `ccaa-1E1515`) — the portal and phone app chain multiple runs, and the integration now does too (check → eligibility → start → poll → re-check until the device converges, with a step budget, per-step timeout, FAILED-step abort, and no-progress guard). The update entity also displayed the wrong target version (`ccaa-1515`, missing the leading byte) — the version construction now preserves the full prefix. A refused or failed update start now raises a visible Home Assistant error with the reason instead of logging "initiated" and silently stopping. **Multi-step hardware validation on a real 6000XP is pending — beta testers with multi-component devices, feedback welcome on #353.**
- **One inverter's sensors all unknown after 3.4.0** ([#348](https://github.com/joyfulhouse/eg4_web_monitor/issues/348)): a no-BMS secondary inverter reports battery temperature `127` (0x7F placeholder), which tripped pylxpweb's data-corruption canary and rejected the whole payload every poll. The sentinel is now normalized to unknown for just that field (pylxpweb 0.9.38b1).
- **Valid 0.1 kWh daily-energy ticks rejected** ([#346](https://github.com/joyfulhouse/eg4_web_monitor/issues/346), reported by @ivanfmartinez): the spike filter compared quantized floats without tolerance, so the smallest real increment (`4.4 - 4.3`) could overshoot its own bound by a float ulp and be logged + dropped (pylxpweb 0.9.38b1).
- **PV Start Voltage unknown in cloud-only mode** ([#359](https://github.com/joyfulhouse/eg4_web_monitor/pull/359)): the read path divided the cloud's already-scaled volts by 10, pushing the value out of range; the entity now reads correctly in all modes (and its write keeps the verified named-parameter cloud route).

### Changed

- **Quieter logs at INFO level** ([#345](https://github.com/joyfulhouse/eg4_web_monitor/issues/345), requested by @ivanfmartinez): routine per-cycle parameter-refresh messages and degraded-state retry notices demoted to DEBUG.
- **Internal consolidation** ([#342](https://github.com/joyfulhouse/eg4_web_monitor/issues/342)): coordinator write-helper unit tests, shared validation/write helpers across number entities (`VoltageNumberSpec` table), table-driven Charge Last switch, per-device schedule refresh, and a timezone-change-safe history-import migration (statistics re-keyed with snapshot + verify before any destructive step). No entity IDs or behavior contracts changed; 2086 tests (from 1952).

### Developer

- CI strict-typing job now reads the pylxpweb pin from `tests/requirements-test.txt` (a hardcoded specifier had let mypy check against a stale stable release).
- Firmware reverse-engineering tooling and analysis notes added under `scripts/`/`docs/` (dongle firmware download/extraction helpers; no integration code changes).
- Dev-tooling scripts hardened per Bandit (httpx with TLS verification by default, `--insecure` opt-in; MD5 marked non-security; temp paths via `tempfile`).

## [3.4.0] - 2026-07-07

Stable release consolidating the `3.4.0-beta.1`–`3.4.0-beta.27` and `3.4.0-rc.1`
cycle. Detailed beta notes are retained below.

> Requires [pylxpweb 0.9.37](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.37)
> (installed automatically). 0.9.37 fixes the cloud raw-register write path —
> without it the five new voltage-limit numbers cannot write in pure-cloud
> mode (the final-release review found the cloud endpoint had been silently
> dropping raw register values since before this release train).

### Added

**New controls & configuration**

- **Battery Control Mode — SOC vs Voltage** ([#48](https://github.com/joyfulhouse/eg4_web_monitor/issues/48)): two new **select** entities per inverter — **Battery Charge Control** and **Battery Discharge Control** (`SOC` / `Voltage`) — mirroring the inverter's register-179 regime bits, plus five open-loop **voltage-limit numbers**: **System Charge Voltage Limit** (reg 228), **On-Grid Cut-Off Voltage** (reg 169), **Off-Grid Cut-Off Voltage** (reg 100), **AC Charge Start Voltage** (reg 158), **AC Charge End Voltage** (reg 159). A **Configure → Battery Charge/Discharge Control Mode** option pre-fills from the live regime and gates which limit entities are enabled by default. Works in all modes; in a parallel group the regime is written to and refreshed across all inverters together.
- **Charge Last switch** ([#177](https://github.com/joyfulhouse/eg4_web_monitor/issues/177)): toggle the battery *Charge Last* function (register 110 bit 4) in cloud, local, and hybrid modes.
- **Forced Discharge Power and Forced Discharge SOC Limit numbers** ([#207](https://github.com/joyfulhouse/eg4_web_monitor/issues/207), with [@DevTodd](https://github.com/DevTodd)): holding registers 82/83; the power command is kW (0–25.5), the SOC limit percent. Grid-tied families only (suppressed on the off-grid family, whose topology doesn't blend grid export/import).
- **Stop Discharge Voltage number** (register 202, decivolts): the voltage-regime counterpart of the Forced Discharge SOC Limit, in all modes.
- **Grid Sell Back switch, Export PV Only switch, and Grid Sell Back Power number** ([#135](https://github.com/joyfulhouse/eg4_web_monitor/issues/135)): the web UI's grid-sell controls, gated to grid-tied families (EG4_HYBRID / LXP). **Grid Sell Back** (register 21 bit 15) and **Export PV Only** (register 179 bit 3) work in all modes; **Grid Sell Back Power** is a kW cap (register 103, 100 W raw units; 0–25.5 kW).
- **Fast Zero Export switch** ([#274](https://github.com/joyfulhouse/eg4_web_monitor/issues/274)): the Grid Sell tab's fast zero-export toggle (register 110 bit 1), grid-tied families, all modes.
- **Share Battery switch** ([#306](https://github.com/joyfulhouse/eg4_web_monitor/pull/306), closes [#288](https://github.com/joyfulhouse/eg4_web_monitor/issues/288)): the per-inverter shared-bank toggle (register 110 bit 3) for multi-inverter systems; disabled by default (niche).
- **Start Discharge / Start Charge Power Threshold numbers** ([#272](https://github.com/joyfulhouse/eg4_web_monitor/issues/272)): CT-equipped grid-tied inverters get **Start Discharge Power Threshold** (register 116, whole watts, all modes) and its companion **Start Charge Power Threshold** (register 117, signed watts, LOCAL/HYBRID-only, disabled by default — the cloud has no parameter name for it).
- **AC Charge Start/End Battery SOC numbers — off-grid family** ([#332](https://github.com/joyfulhouse/eg4_web_monitor/pull/332), closes [#331](https://github.com/joyfulhouse/eg4_web_monitor/issues/331)): the off-grid family's real AC-charge window controls (registers 160/161), enabled by default. (The grid-tied *AC Charge SOC Limit*, register 67, is correctly removed on this family — see Fixed.)

**Quick Charge in LOCAL/HYBRID** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251))

- The **Quick Charge** switch and **Quick Charge Duration** number now work over a local transport, not just the cloud API. Duration faithfully mirrors holding register 234 live (idle and while charging): raising it while a charge runs extends the charge; setting it while idle returns a clear error rather than silently storing a rejected value (cloud-only installs keep it as a start-minute preference). A new **Quick Charge Remaining** sensor reports the live countdown in **seconds** (input register 210, holding-234 fallback; cloud reads the API).
- **AC Charge SOC Limit accepts 101%** ([#158](https://github.com/joyfulhouse/eg4_web_monitor/issues/158)): the "never stop AC charging" cell-balancing setting no longer reads back unavailable or rejects a 101 write.

**Schedule time entities**

- Native Home Assistant **time** entities for the portal's working-mode schedule windows: **AC Charge** (registers 68-73, [#277](https://github.com/joyfulhouse/eg4_web_monitor/issues/277)), **AC First** (152-157, off-grid family only), **Forced Charge** (76-81), **Forced Discharge** (84-89, grid-tied families), **Peak Shaving** (209-212), **Generator Charge** (256-259), and **Off-Grid** (269-274) ([#295](https://github.com/joyfulhouse/eg4_web_monitor/issues/295), [#312](https://github.com/joyfulhouse/eg4_web_monitor/pull/312)). Each schedule exposes up to three windows; values follow parameter polling so portal-made changes appear in HA, and LOCAL/HYBRID write the packed register directly while CLOUD uses the portal's named parameters. **All schedule time entities are created disabled by default** — enable the windows you automate from the entity registry.

**New sensors & diagnostics**

- **Operating State sensor and Off-Grid binary sensor** ([#262](https://github.com/joyfulhouse/eg4_web_monitor/issues/262)): the operating-mode code, previously only a raw numeric Status Code, is now decoded into a friendly enum (e.g. `Battery → Grid`, `Off-Grid (Battery)`) in all modes, plus a boolean **Off-Grid** sensor. The cloud connection/health string is renamed **Cloud Status** (entity ID unchanged).
- **Fault Code and Warning Code diagnostic sensors** (input registers 60-63): surfaced per inverter in LOCAL and HYBRID modes (the cloud API doesn't carry these fields).
- **Smart Load Power and Grid Load Power sensors — off-grid family** ([#222](https://github.com/joyfulhouse/eg4_web_monitor/issues/222)): on 6000XP/12000XP the GEN terminal doubles as a smart-load output; the cloud's `smartLoadPower`/`gridLoadPower` split is surfaced in CLOUD and HYBRID modes.
- **Off-grid family register set** ([#197](https://github.com/joyfulhouse/eg4_web_monitor/issues/197)): live-validated **Load Power** (input register 170) and a per-inverter **Battery Discharge Power** sensor for the EG4_OFFGRID family (12000XP/6000XP).

**Other**

- **New service `eg4_web_monitor.import_historical_data`** ([#73](https://github.com/joyfulhouse/eg4_web_monitor/issues/73)): opt-in, idempotent import of plant-level daily energy history (PV yield, consumption, grid import/export, battery charge/discharge) into external long-term statistics selectable in the Energy dashboard. Bounded to 2 years per call, with `dry_run` preview and DST-correct day alignment.
- **Configurable Modbus read block size** ([#254](https://github.com/joyfulhouse/eg4_web_monitor/issues/254)): a new option (shown when a local transport is configured) with **Conservative** (default, unchanged behavior) and **Fast** (up to 120 registers per request, ~4 fewer round-trips per poll) presets. Older dongle firmware that only supports ~40-register reads automatically latches back to conservative reads without interrupting polling.

### Changed / Behavior notes

- **`Output Power` now means load output in every connection mode**: previously an exact duplicate of `AC Power` in cloud/hybrid (both `pinv`) while LOCAL read the load register. It now carries register-170 load-output semantics everywhere. Pure-cloud values change from inverter AC output to load output; the entity is no longer split-phase-gated; and pure-cloud off-grid systems get no `output_power` entity (the cloud zeroes its mirror there) rather than a false 0.
- **`EPS Load Power` (off-grid family) reflects the real always-connected-loads subset** ([#336](https://github.com/joyfulhouse/eg4_web_monitor/pull/336), closes [#335](https://github.com/joyfulhouse/eg4_web_monitor/issues/335)): on the off-grid family this sensor now reads the cloud's `epsLoadPower` field — the load subset of the backup output — diverging from *EPS Power* when the smart load runs (matching the EG4 portal). On pure-LOCAL installs it reads unknown (no local register carries the subset; cloud and hybrid populate it). No per-leg EPS load values exist — use **EPS Power L1/L2** for per-leg readings.

### Fixed

**Battery reporting**

- **Systems with more than 4 batteries now report every battery reliably in all modes** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258), [#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): inverters rotate >4 batteries through 4 fixed Modbus slots and the inverter's reported battery count (register 96) is unreliable on parallel systems. Battery data now accumulates by serial number and ignores register 96, so every battery appears and stays. Several related root causes were also fixed: cloud login no longer fails on parallel-group systems (the login model treated informational last-visit fields as required), the HYBRID merge carries batteries forward across transient cloud omissions and keeps the fresher of the local/cloud reading per battery (with a 6-hour staleness bound so a physically removed pack still disappears without a restart), and transient duplicate-serial register reads can no longer mint a lasting phantom battery.
- **One battery identity across Cloud/Local/Hybrid** ([#252](https://github.com/joyfulhouse/eg4_web_monitor/issues/252)): all modes now derive the same serial-first device key, so switching connection mode no longer duplicates battery devices. Existing installs are migrated in place (automations, dashboards, area, name and history preserved).
- **Battery Bank aggregates no longer flicker unavailable** ([#261](https://github.com/joyfulhouse/eg4_web_monitor/issues/261)): the bank sensors dropped out whenever the local battery count momentarily read 0; they now fall back to the cloud reading, and the local decode preserves the last-good value when only the BMS register block drops.
- **Battery cell-number sensors uncrossed in LOCAL/HYBRID**: the Max/Min Cell Temperature/Voltage Number sensors were swapped on the local path; they now match cloud.
- **Battery bank Full/Remaining Capacity no longer double-counted in cloud mode**, and **battery firmware version no longer flaps between "1.3" and "1.03" in HYBRID** ([#287](https://github.com/joyfulhouse/eg4_web_monitor/issues/287)).

**Device & control detection**

- **12000XP and other SNA-platform units get their full control set in Cloud mode** ([#259](https://github.com/joyfulhouse/eg4_web_monitor/issues/259)): the control gate matched the cloud model string against known substrings, so a unit reporting `SNA-US 15K` was created with no Controls or Configuration at all. The gate now also accepts any device whose detected inverter family is one the integration drives, available in every mode.
- **Family-UNKNOWN devices regain their real sensor profile** ([#219](https://github.com/joyfulhouse/eg4_web_monitor/issues/219)) and **6000XP units reporting device-type code 38 are positively identified as off-grid** ([#222](https://github.com/joyfulhouse/eg4_web_monitor/issues/222)).
- **An offline inverter no longer blacks out all of its entities** ([#256](https://github.com/joyfulhouse/eg4_web_monitor/issues/256)): the cloud's partial "offline" payload failed validation and made every entity unavailable, even on the online sibling in the same station. It now reports `Status = offline` with live metrics unknown.
- **Multi-station cloud accounts can be added again** ([#275](https://github.com/joyfulhouse/eg4_web_monitor/issues/275)): the station-selection dropdown rejected every choice on accounts with more than one station (int-keyed ids vs the frontend's string submission).
- **Duplicate "Has Runtime Data" sensor removed** ([#253](https://github.com/joyfulhouse/eg4_web_monitor/issues/253)).

**Local transport reliability** ([#226](https://github.com/joyfulhouse/eg4_web_monitor/issues/226))

- A local transport that dies mid-run, drops silently (VPN/NAT timeout with no TCP reset), or fails to attach at startup no longer freezes entities on stale data or parks a HYBRID device on cloud data forever. After 3 failed reads the link is declared down (one warning plus a self-clearing Repairs issue); HYBRID falls back to cloud at the normal cadence, LOCAL goes honestly unavailable, and everything self-restores on reconnection. Loads on the off-grid family also rides out an outage now (falls back to the cloud EPS/smart/grid split).
- **Parameter-backed controls no longer go unknown for an hour after one bad read** ([#282](https://github.com/joyfulhouse/eg4_web_monitor/issues/282)): a failed holding-register range read replaced the full parameter set and armed the hourly throttle; partial reads now carry forward last-known values and retry early.
- **Targeted Modbus parameter reads are link-down-gated** and **RS485 serial devices in HYBRID are refreshed sequentially** ([#233](https://github.com/joyfulhouse/eg4_web_monitor/issues/233)) so a shared bus isn't corrupted by concurrent reads.

**GridBOSS & registers**

- **GridBOSS smart-load automations no longer break on every restart in LOCAL mode** ([#217](https://github.com/joyfulhouse/eg4_web_monitor/issues/217)): the boot-time cleanup deleted and re-created smart-port entities under new registry IDs; it's now deferred until real port data lands.
- **Smart Port Status no longer errors when all four ports are Unused** ([#248](https://github.com/joyfulhouse/eg4_web_monitor/issues/248)).
- **Cloud/HYBRID GridBOSS now surfaces Consumption Power and Generator Frequency**, and **LOCAL `Grid Power` computes net grid flow** instead of reading the rectifier-power register.
- **Grid Peak Shaving Power reads and writes correctly in all modes** ([#328](https://github.com/joyfulhouse/eg4_web_monitor/issues/328), [#329](https://github.com/joyfulhouse/eg4_web_monitor/pull/329), [#334](https://github.com/joyfulhouse/eg4_web_monitor/pull/334)): the setpoint lives at register 206 (0.1 kW units, hardware-confirmed), not the earlier-mapped register 231 that silently discarded writes. Writing the setpoint with Peak Shaving mode disabled now gives a clear error instead of a cryptic timeout.

**Config flow**

- **Dongle/Modbus discovery failures now show a clear connection error** instead of "Unexpected error" ([#250](https://github.com/joyfulhouse/eg4_web_monitor/issues/250)).

## [3.4.0-rc.1] - 2026-07-05

> Requires [pylxpweb 0.9.36](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36) (stable, unchanged from beta.27).

**Release candidate for 3.4.0** — identical source to 3.4.0-beta.27; version promotion only. The full
3.4.0 changelog will consolidate the beta.18–beta.27 train. Validation state at this cut: three-mode
entity-parity sweep passed (cloud/local/hybrid, registry-level), 1949 tests, docker hybrid live-validated,
production soaking on the beta line since beta.18.

## [3.4.0-beta.27] - 2026-07-05

> Requires [pylxpweb 0.9.36](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36)
> — the first **stable** release of the 0.9.36 line (installed automatically).

### Fixed

- **EPS Load Power was a duplicate of EPS Power** ([#336](https://github.com/joyfulhouse/eg4_web_monitor/pull/336), closes [#335](https://github.com/joyfulhouse/eg4_web_monitor/issues/335)): on the off-grid family the *EPS Load* sensors were aliases of the combined EPS output — the original off-grid enablement validated the alias at a moment when the smart load was idle, the one state where the two quantities match. **EPS Load Power** now reads the cloud's real `epsLoadPower` field: the always-connected-loads **subset** of the backup output, diverging from *EPS Power* exactly when the smart load runs (matching the EG4 portal).
- **Grid Peak Shaving Power read `unknown` in LOCAL mode** ([#334](https://github.com/joyfulhouse/eg4_web_monitor/pull/334), found by the 3.4.0 three-mode validation sweep): the beta.25 fix reached cloud and hybrid but the LOCAL-mode targeted register poll still skipped register 206 from before its encoding was verified. LOCAL now reads it like the other modes.

### Breaking / Behavior Changes

- **`EPS Load Power L1` / `EPS Load Power L2` sensors are retired** (off-grid family): EG4 provides no per-leg load values — these two were never real measurements, only copies of *EPS Power L1/L2*. Registry entries are cleaned up automatically; update any dashboards or automations to use **EPS Power L1/L2** (the identical values those sensors always showed).
- **`EPS Load Power` (total) changes meaning**: previously the fabricated combined sum (identical to EPS Power), now the true EPS-loads subset. The entity and its unique ID are unchanged, so long-term statistics carry over — but expect a level shift in the history if your smart load runs regularly. On pure-LOCAL installs this sensor now reads unknown (EG4 exposes the subset only via the cloud; no local register is known — cloud and hybrid populate it).

## [3.4.0-beta.26] - 2026-07-05

> Requires [pylxpweb 0.9.36b28](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b28)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **AC Charge SOC on the off-grid family (12000XP/SNA/6000XP)** ([#332](https://github.com/joyfulhouse/eg4_web_monitor/pull/332), closes [#331](https://github.com/joyfulhouse/eg4_web_monitor/issues/331)): setting the *AC Charge SOC Limit* failed every time with `REMOTE_SET_ERROR` — that entity writes register 67, which is the grid-tied family's control; the off-grid firmware rejects it (and the off-grid portal doesn't offer it). The off-grid family's real AC-charge window controls are registers 160/161, portal-verified: two new numbers — **AC Charge Start Battery SOC** and **AC Charge End Battery SOC** — are created on off-grid devices (enabled by default), and the inapplicable *AC Charge SOC Limit* entity is removed there with a one-shot Repairs notice. Grid-tied and LXP devices are unchanged. Automations just need to target the new End SOC entity. (pylxpweb [#216](https://github.com/joyfulhouse/pylxpweb/pull/216) maps register 161 for local access; the canonical note is now family-scoped.)
- **Repairs notices for family-gated entities can no longer false-positive across inverters whose serial is a suffix of another's** (hardening from the #332 review, applies to all gated-entity cleanup paths).

### Improved

- **Multi-device log analysis** (pylxpweb [#215](https://github.com/joyfulhouse/pylxpweb/pull/215), closes pylxpweb [#213](https://github.com/joyfulhouse/pylxpweb/issues/213), thanks @ivanfmartinez): every dongle validation-failure and retry log line now carries the `[serial]` prefix and a uniform `expected [...], received [...]` frame-context block.

## [3.4.0-beta.25] - 2026-07-04

> Requires [pylxpweb 0.9.36b27](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b27)
> (installed automatically; the manifest requirement is bumped — also delivers the b26
> proven-capable Fast-mode improvement below).

### Fixed

- **Grid Peak Shaving Power fully working across all modes** ([#329](https://github.com/joyfulhouse/eg4_web_monitor/pull/329) + pylxpweb [#214](https://github.com/joyfulhouse/pylxpweb/pull/214), closes [#328](https://github.com/joyfulhouse/eg4_web_monitor/issues/328)): the number entity blanked to *unknown* in LOCAL/HYBRID because the local register map deliberately excluded the register while its raw encoding was unverified. @DoubleDoc's hardware write test (pylxpweb [#158](https://github.com/joyfulhouse/pylxpweb/issues/158)) plus a live cloud write/readback correlation settled it: **register 206 is 0.1 kW units**. The whole Peak Shaving family (PS1/PS2 power, both SOC and voltage setpoints) is now mapped for local reads with cloud-identical values, and the power setpoint writes directly over Modbus/dongle when a local transport is attached.
- **Writing the setpoint with Peak Shaving mode disabled now gives a clear error** instead of a cryptic timeout: live testing confirmed the firmware rejects the write (and zeroes the setpoint) while `FUNC_GRID_PEAK_SHAVING` is off. The entity pre-checks the mode — with a live single-register confirmation read when the cached state says *off*, so enabling the mode on the EG4 portal is honored immediately rather than after the hourly parameter cycle.

### Improved

- **Fast block-size mode: proven-capable transports never permanently degrade** (pylxpweb [#212](https://github.com/joyfulhouse/pylxpweb/pull/212) / 0.9.36b26, from @ivanfmartinez's suggestion on [#320](https://github.com/joyfulhouse/eg4_web_monitor/issues/320)): once a transport has completed a >40-register coalesced read, any later failure — misroute, CRC, timeout, short frame — is treated as transient with the ~5-minute cooldown re-probe; the permanent latch is reserved for transports that never proved large-read support. Two new DEBUG lines make the Fast-mode lifecycle explicit (first-success confirmation + cooldown-expiry re-probe).

## [3.4.0-beta.24] - 2026-07-04

> Requires [pylxpweb 0.9.36b25](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b25)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **Daylight Saving Time switch always showed OFF** ([#324](https://github.com/joyfulhouse/eg4_web_monitor/pull/324), closes [#323](https://github.com/joyfulhouse/eg4_web_monitor/issues/323)): the station DST switch read a key the coordinator never populated, so it was pinned OFF regardless of the portal state — since the feature was introduced. Two further bugs fixed in the same pass: the hourly DST auto-sync misread the detected-DST semantics and never corrected a stale cloud flag during summer (exactly the reported season), and the sync compared against a cached flag that nothing ever re-read — portal-side DST changes were invisible forever. The switch now mirrors the cloud flag, and the hourly sync re-reads it from the cloud before comparing, so portal-side changes converge within an hour.
- **Refresh Data button now forces a genuinely full refresh** ([#325](https://github.com/joyfulhouse/eg4_web_monitor/pull/325), closes [#322](https://github.com/joyfulhouse/eg4_web_monitor/issues/322)): the button previously issued a cache-respecting refresh (a no-op within ~30 s of a poll) and never touched holding-register parameters, so a control value changed on the EG4 portal (e.g. Share Battery) could take until the hourly parameter cycle — minutes to an hour — to appear in HA. A press now forces runtime + energy + battery + **parameters**, bypassing all caches. Two review-round hardenings: the coordinator's obsolete link-down skip was removed so a HYBRID system with a dead local link now refreshes parameters via the cloud fallback (pylxpweb's own guard handles routing safely, no hang risk), and a press that reads nothing (device unreachable) now raises a visible error instead of silently reporting success. The per-battery Refresh Data button also forces its read now.
- **Fast block-size mode no longer permanently reverts on a misrouted dongle frame** ([#320](https://github.com/joyfulhouse/eg4_web_monitor/issues/320), pylxpweb [#211](https://github.com/joyfulhouse/pylxpweb/pull/211)): with the Modbus Read Block Size option on Fast, a single misrouted WiFi-dongle response (a frame meant for the EG4 cloud, or an unsolicited heartbeat) tripped the "old firmware" probe latch and silently reverted the connection to conservative grouped reads until reload. Misrouted/unsolicited frames — now including heartbeat and proxied parameter frames, which previously slipped past validation — are classified as transient: the cycle falls back to grouped reads and Fast mode re-probes after a ~5-minute cooldown. Genuine firmware refusals (Modbus exceptions, timeouts, short responses) still latch permanently as designed.

### Review

Every PR passed a dual review gate (Opus code review + adversarial second review). The adversarial pass found three confirmed P1s after Opus passed both integration PRs clean — all fixed in review rounds before merge. Codex quota was exhausted this cycle; Antigravity served as the adversarial reviewer.

## [3.4.0-beta.23] - 2026-07-03

> Requires [pylxpweb 0.9.36b24](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b24)
> (unchanged from beta.22). This is the 3.4.0 release candidate.

### Fixed

- **Forced Charge schedule times removed from the off-grid family** ([#316](https://github.com/joyfulhouse/eg4_web_monitor/pull/316), from @mjstrand's beta.21 report on [#295](https://github.com/joyfulhouse/eg4_web_monitor/issues/295)): setting a Forced Charge start/end time on a 12000XP failed with `REMOTE_SET_ERROR` — the EG4 cloud rejects the parameter, and the off-grid working-mode portal page carries no Forced Charge schedule at all (the beta.20 gate over-generalized from the hybrid page). The six time entities are no longer created on EG4_OFFGRID; anyone who had one registered gets a one-shot Repairs notice. Interesting inverse discovered in the same investigation: the off-grid portal page *does* carry a full Forced Discharge schedule widget, which we currently suppress — tracked as [#317](https://github.com/joyfulhouse/eg4_web_monitor/issues/317), pending hardware write evidence.

## [3.4.0-beta.22] - 2026-07-03

> Requires [pylxpweb 0.9.36b24](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b24)
> (installed automatically; the manifest requirement is bumped).
>
> This is the 3.4.0 issue-zeroing release: every open bug and feature request
> against the integration is resolved here (the sole remaining open issue,
> #176 RS485 battery transport, is milestoned 3.5.0). Every PR passed the
> dual Opus + Codex adversarial review gate, several through multiple rounds.

### Added

- **Generator, Off-Grid and Peak Shaving schedule time entities — full portal parity** ([#312](https://github.com/joyfulhouse/eg4_web_monitor/pull/312)): the remaining schedule windows from the portal's working-mode pages join the seven schedule families as native **time** entities, with registers live-verified on real hardware (cloud-write ↔ local-register correlation): **Peak Shaving** (registers 209-212, 2 windows; the cloud reads these via the portal's `LSP_HOLD_DIS_CHG_POWER_TIME_37..44` interleaved params), **Generator Charge** (256-259, 2 windows; created on EG4_HYBRID and — per the SNA register probe — EG4_OFFGRID), and **Off-Grid** (269-274, 3 windows, EG4_HYBRID). Cloud writes use the portal's own **atomic writeTime endpoint** (one call per boundary — no partial hour/minute failure mode; pylxpweb #209). Smart Load schedules are deliberately excluded: cloud writes returned DATAFRAME_TIMEOUT on both test units and the registers could not be pinned.
- **Share Battery switch** ([#306](https://github.com/joyfulhouse/eg4_web_monitor/pull/306), closes [#288](https://github.com/joyfulhouse/eg4_web_monitor/issues/288)): the portal's per-inverter Share Battery toggle (HOLD 110 bit 3) for multi-inverter shared-bank systems, using the reporter-verified `FUNC_BAT_SHARED` cloud function; disabled by default (niche feature). pylxpweb's battery-count debug line now notes when reg96=0 is expected on a sharing secondary (pylxpweb #207).

### Changed

- **ALL schedule time entities are now disabled by default** — including the existing AC Charge/Forced Charge/Forced Discharge/AC First window-1 entities that beta.18-.20 created enabled. They serve a limited automation use case and add entity noise for most installs. Entities you have already enabled stay enabled (the default only affects new registrations); enable any window from the entity registry.

### Fixed

- **Quick Charge switch no longer lies on the XP family** ([#308](https://github.com/joyfulhouse/eg4_web_monitor/pull/308), closes [#296](https://github.com/joyfulhouse/eg4_web_monitor/issues/296)): on 6000XP/12000XP the switch state read holding register 233 — the exact register that family's firmware rejects (`ILLEGAL DATA ADDRESS`), so the switch showed *off* seconds after starting a charge that was actually running (reporter's log). Quick-charge status and control on the off-grid family now route through the cloud API (the same source the EG4 app reflects) when cloud credentials exist; the commanded state is retained until a **fresh** status read confirms it (never overridden by known-pre-write data — the exact 502-storm flap in the report); the Duration number reads live register 234 so its display and its write agree; and all new cloud/local reads are link-down-gated and time-bounded. Three review rounds.
- **XP-v2: Battery Backup Mode switch removed where firmware rejects it** ([#307](https://github.com/joyfulhouse/eg4_web_monitor/pull/307), closes [#289](https://github.com/joyfulhouse/eg4_web_monitor/issues/289)): the reporter's 12000XP v2 rejects the working-mode write ("failed to enable working mode") and EG4's own Remote Set portal doesn't offer the control for that platform — the switch is no longer created on the off-grid family, with a one-shot Repairs notice for anyone who had it registered. **EPS Battery Backup stays** — the SNA register dump proves it live and enabled on that family (the review gate caught and reverted an over-broad first draft). New XP-family control notes in TROUBLESHOOTING (AC Charge controls charging, not grid passthrough; Off Grid Mode self-reverts on XP-v2 firmware).
- **Positional battery retirement across slot shifts** ([#309](https://github.com/joyfulhouse/eg4_web_monitor/pull/309), closes [#302](https://github.com/joyfulhouse/eg4_web_monitor/issues/302)): when a battery's serial becomes readable after a serial-less cold-start window, the exposed positional entity now retires immediately and exactly (previously the shifted slot index made retirement miss it until the 6-hour bound), with a discoverable INFO log naming the stale entity.
- **Switches converge after cloud-fallback writes instead of reverting** ([#311](https://github.com/joyfulhouse/eg4_web_monitor/pull/311), closes [#310](https://github.com/joyfulhouse/eg4_web_monitor/issues/310)): the #301 parameter-cache seeding now covers the switch family too — a switch flipped while the local link is down converges on the acknowledged cloud value with zero intermediate stale state publishes (the review's state-sequence test found and killed a second stale-publish window). Off-grid Green Mode state is now honest: pylxpweb no longer decodes the unverified SNA bit as truth, and an absent reading shows *unknown* instead of *off* (pylxpweb #210).
- **Targeted Modbus parameter reads are link-down-gated** ([#313](https://github.com/joyfulhouse/eg4_web_monitor/pull/313)): the integration's own per-cycle 8-range parameter read bypassed pylxpweb's refresh guard and could stall a poll cycle for minutes against a dead RS485 link; it now skips with correct sticky/retry accounting and resumes on the recovery cycle. Library-side defense-in-depth shipped in pylxpweb #208.

## [3.4.0-beta.21] - 2026-07-03

> Requires [pylxpweb 0.9.36b23](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b23)
> (installed automatically; the manifest requirement is bumped).
>
> This release is the outcome of a four-scanner adversarial bug sweep
> (two independent Claude passes, Codex, and Antigravity) over the integration
> and the pylxpweb library, followed by a dead-code cleanup of both. Every fix
> below was independently verified before implementation and every PR passed a
> dual Opus + Codex review gate.

### Fixed

- **LOCAL: a physically removed battery now disappears within the staleness bound instead of surviving until a Home Assistant restart** ([#300](https://github.com/joyfulhouse/eg4_web_monitor/pull/300)): the 6-hour eviction added in beta.19 sat in a branch that only ran when a poll returned *zero* batteries — but the round-robin merge always returns the full accumulated cache, so on any normal poll the eviction was unreachable and a removed pack's entities stayed populated with frozen values indefinitely. The eviction now runs unconditionally on every merge (matching the HYBRID/CLOUD behavior shipped in beta.19), and the same bound now also covers the HYBRID coordinator's local-only branch, which was previously unbounded.
- **HYBRID: schedule time, number and select controls now fall back to the cloud when the local write fails or the local link is down** ([#301](https://github.com/joyfulhouse/eg4_web_monitor/pull/301)): switches have always retried a failed local write through the cloud API, but every other control type chose the local path purely because a transport was *attached* — and pylxpweb keeps the transport attached during a link outage — so changing a charge schedule, SOC limit, PV input mode or battery control mode failed until the link recovered even with a healthy cloud connection. All control writes now share the switches' local-attempt-then-cloud semantics, prefer the cloud *immediately* when the library reports the link down (no timeout wait), and the post-write parameter refreshes are link-down-aware so the service call can't stall against a dead transport. After a successful cloud fallback the acknowledged values are seeded into the parameter cache, so the entity converges on what was written instead of reverting to the stale pre-write value until link recovery. Excluded by design: Quick Charge Duration and the Start Charge threshold (no equivalent cloud write exists).
- **Switches and selects now report unavailable during a sustained coordinator outage, like every other entity type** ([#303](https://github.com/joyfulhouse/eg4_web_monitor/pull/303)): sensors, numbers and time entities already gated availability on coordinator health; switches and selects were missed in 2025-12 and stayed clickable against stale data through a full outage (the write then failed loudly). The gate only engages after three consecutive failed update cycles (the existing stale-tolerance circuit breaker) and single-device or transient failures never trip it, so day-to-day behavior is unchanged.
- **Library (pylxpweb 0.9.36b23)**: a truncated-but-well-formed holding-register response from the dongle or Modbus TCP could silently produce a partial parameter read that blanked parameter-backed entities for up to an hour ([pylxpweb#203](https://github.com/joyfulhouse/pylxpweb/pull/203) — the input-register path was guarded in beta.14, the parameter path never was); a battery whose electrical data arrived before its serial number on a cold start could mint a permanent duplicate battery with frozen values ([pylxpweb#204](https://github.com/joyfulhouse/pylxpweb/pull/204)); public cloud-mode schedule getters always returned 00:00 ([pylxpweb#205](https://github.com/joyfulhouse/pylxpweb/pull/205), no integration impact — it reads the named parameters directly); and the link-down probe no longer runs the full six-group input read on every degraded poll, cutting dead-link poll pressure roughly 6× ([pylxpweb#205](https://github.com/joyfulhouse/pylxpweb/pull/205)).

### Changed

- **Dead-code cleanup, both repositories** ([#299](https://github.com/joyfulhouse/eg4_web_monitor/pull/299), [pylxpweb#202](https://github.com/joyfulhouse/pylxpweb/pull/202)): −106 integration lines and −26 library lines of verified-unreferenced code (orphaned helpers, unused mappings, dead stores). Zero functional change — entity IDs, unique IDs and translation keys are byte-identical, verified by both review gates.

## [3.4.0-beta.20] - 2026-07-02

> Requires [pylxpweb 0.9.36b22](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b22)
> (installed automatically; the manifest requirement is bumped).

### Added

- **AC First, Forced Charge and Forced Discharge schedule time entities** ([#295](https://github.com/joyfulhouse/eg4_web_monitor/issues/295)): the remaining portal schedule windows join the #277 AC Charge times as native Home Assistant **time** entities — per schedule, three windows × (start, end), window 1 enabled by default and windows 2/3 created registry-disabled. **AC First** (holding registers 152-157) is the off-grid working mode's schedule and is created only on positively-identified EG4_OFFGRID (SNA-platform) inverters — the portal exposes the AC First section only on the SNA working-mode page, whose `holdParam` attributes plus the live SNA12K-US register probe (pylxpweb `docs/inverters/SNA12KUS_52XXXXXX68.json`, blocks 106-111) pin the cloud names (`HOLD_AC_FIRST_{START|END}_{HOUR|MINUTE}` with `""`/`_1`/`_2` window suffixes) and registers. **Forced Charge** (76-81) is created for all control-capable families; **Forced Discharge** (84-89) for control-capable grid-tied families (suppressed on EG4_OFFGRID, matching the forced discharge power/SOC numbers, #197/#220). All write paths, validation and failure-convergence behavior are identical to the reviewed #277/#283 implementation: LOCAL/HYBRID write one packed register (FC06), CLOUD writes the portal's named hour + minute params with best-effort re-read on partial failure, and overnight windows are accepted. Internally the four schedules now come from one declarative table (`SCHEDULE_TIME_TYPES`) consumed by a single entity class — the #277 code generalized rather than copied — with a drift-guard test against pylxpweb's `SCHEDULE_CONFIGS`. The LOCAL parameter poll covers the new registers (64-89 widened; the 152-157 read is added only on EG4_OFFGRID devices, so non-SNA firmware that rejects the range never degrades the parameter cycle). AC Charge entities are byte-for-byte unchanged (same unique IDs and names). pylxpweb ships `ScheduleType.AC_FIRST` and canonical register names for 84-89/152-157; on pylxpweb 0.9.36b21 the integration falls back to raw register keys, so no version bump is required.

## [3.4.0-beta.19] - 2026-07-02

> Requires [pylxpweb 0.9.36b21](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b21)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **HYBRID/CLOUD: battery entities no longer flip unavailable in subsets when the cloud momentarily omits packs** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258)): on rotating >4-battery banks, a fresh `getBatteryInfo` response occasionally omits or re-keys part of the bank for a cycle. The hybrid merge rebuilt the battery dict from that cloud payload as its baseline — and battery-entity availability is key-presence — so the omitted packs' entities went *unavailable* within seconds of the cloud poll (the reporter's beta.18 drops each followed a fresh cloud POST by ~4 s) even while the local register accumulator held valid data for every pack the whole time. The merge now **carries forward once-published batteries** across transient omissions in every mode branch: carried packs keep their original `battery_last_seen` (staleness stays visible as data, never as availability flapping), legacy pre-migration keys and serial-superseded keys are excluded so the #252 registry migration is unaffected, and a **6-hour staleness bound** evicts a carried pack that has genuinely stopped reporting everywhere (physical removal converges without an HA restart; the bound is far above the seconds-scale cloud gaps and does not govern firmware page-pinning, which the accumulator serves as fresh data). The LOCAL round-robin cache gets the same bound, and cache retirement is now authoritative across both sticky layers. Reported by @ivanfmartinez with the decisive debug log.
- **A transient duplicate-serial register read can no longer mint a lasting phantom battery** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258), [pylxpweb#200](https://github.com/joyfulhouse/pylxpweb/pull/200)): corrupt serial bytes captured during a dongle misroute could make two battery slots report the same serial; the accumulator now disambiguates the collision (one latched WARNING) and **re-verifies** it — the next clean read of that bank position evicts the suspect entry, while a genuine duplicate-serial pack pair keeps re-minting its entry and stays protected at the library layer (Home Assistant identity is the serial, so only one entity can represent a genuine duplicate pair — inherent). Also fixes the battery debug dump printing 14 of 15 serial characters, which manufactured phantom "duplicate serials" in debug logs.
- **Developer: the Fast block-size regression test is now version-independent** — it simulated "released library without the feature" by asserting against the installed pylxpweb and broke once 0.9.36b20 shipped the feature; it now patches the feature-detection instead.

## [3.4.0-beta.18] - 2026-07-02

> Requires [pylxpweb 0.9.36b20](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b20)
> (installed automatically; the manifest requirement is bumped). The #282 HYBRID
> early-retry gating and the #254 Fast block-size mode are inert on older
> pylxpweb versions.

### Added

- **AC Charge schedule time entities** ([#277](https://github.com/joyfulhouse/eg4_web_monitor/issues/277)): the AC charge start/end times from the portal's Maintenance page are now native Home Assistant **time** entities, so automations can reshape charging windows (e.g. flip a dual-rate weekday peak/off-peak window to 00:00-23:59 for the weekend and back) instead of editing them by hand in the EG4 web portal. All three schedule windows are exposed — **AC Charge Start/End Time 1** enabled by default, windows **2** and **3** created disabled (enable them from the entity registry if used). Backed by holding registers 68-73, each packing hour (low byte) and minute (high byte): LOCAL/HYBRID write the packed register directly over Modbus/dongle, CLOUD writes the portal's own `HOLD_AC_CHARGE_{START|END}_{HOUR|MINUTE}` parameters, and in every mode the values follow parameter polling, so portal-made changes appear in Home Assistant. Created for all control-capable families — EG4_OFFGRID (6000/12000XP and SNA-platform units, the reporter's case), EG4_HYBRID (FlexBOSS/18kPV/12kPV) and LXP. Overnight windows (end before start, e.g. 20:00 → 08:00) are accepted as the firmware allows; whether the schedule is honored is still governed by the existing AC Charge switch (register 21 bit 7). Requested by @mjstrand for a 12000XP on dual-rate power.
- **Configurable Modbus read block size — opt-in faster local polling** ([#254](https://github.com/joyfulhouse/eg4_web_monitor/issues/254)): a new "Modbus Read Block Size" option (shown when a local Modbus/dongle transport is configured) with two presets. **Conservative** (default) keeps the exact small grouped register reads every dongle and firmware supports — nothing changes for existing installs. **Fast** reads up to 120 registers per Modbus request, consolidating the four adjacent input-register group reads of 0–112 into a single transaction (~4 fewer round-trips per poll per inverter), which is what lets other tooling poll comfortably at 15 s. The trade-off, stated in the option help text: older dongle firmware only supports ~40-register reads — on those units the first large read fails, pylxpweb logs one warning and automatically latches back to the conservative grouped reads (polling continues, just not faster) until the next reload. GridBOSS reads and the atomic battery block are unchanged. Requires a pylxpweb newer than 0.9.36b19 for the fast path ([pylxpweb#197](https://github.com/joyfulhouse/pylxpweb/pull/197)); on older library versions the option is safely ignored with a log notice. Requested by @ivanfmartinez (LXP-LB, DG dongle fw 2.04–2.09 field-tested at 120), follow-up from [#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251).
- **Start Discharge / Start Charge power threshold numbers** ([#272](https://github.com/joyfulhouse/eg4_web_monitor/issues/272)): CT-equipped grid-tied inverters (EG4_HYBRID and LXP families) get the Luxpower web UI's "Start Discharge P_import(W)" as a **Start Discharge Power Threshold** number — the inverter starts discharging the battery once grid import exceeds this many watts (on-grid, with SOC above the On-Grid SOC Cut-Off). It maps HOLD register 116 (`PtoUserStartdischg`): the raw register is **whole watts** (protocol scale 1 W, default 50 W, range 50-10000 W — not the 100 W encoding of the other power registers), read/written locally through pylxpweb's register name map and, on the cloud path, via the `HOLD_P_TO_USER_START_DISCHG` named parameter — the website's own call, verified in the reporter's browser console. Values set on the Luxpower/EG4 website show up in HA through parameter polling in every connection mode. The companion **Start Charge Power Threshold** (HOLD 117, `PtoUserStartchg`, signed watts, protocol default -50 W = start charging once exporting more than 50 W) is documentation-only hardware the reporter asked to expose for field testing: the cloud API has no parameter name for register 117 (named reads return `<EMPTY>` on every scanned model), so that entity is **LOCAL/HYBRID-only and disabled by default**, reading/writing the raw register (two's-complement for negative thresholds). Requested by @ivanfmartinez for an LXP-LB with CT.
- **Fast Zero Export switch** ([#274](https://github.com/joyfulhouse/eg4_web_monitor/issues/274)): the Grid Sell tab's "Fast Zero Export" toggle from the EG4/Luxpower web UIs is now a switch on grid-tied inverters (EG4_HYBRID and LXP families; off-grid XP units have no export to suppress). It speeds up the inverter's zero-export control loop (import control slows down) and the vendors advise selecting it as the opposite of Grid Sell Back. The bit is HOLD register 110 bit 1 (`FunctionEn1.ubFastZeroExport` in the LXP protocol PDF); the cloud path writes the same `FUNC_RUN_WITHOUT_GRID` function-control parameter the websites use, and the local path read-modify-writes the register bit — state follows parameter polling in all connection modes. Requested by @ivanfmartinez for an LXP-LB; EG4 hybrids expose the same web toggle (first pictured in [#135](https://github.com/joyfulhouse/eg4_web_monitor/issues/135)).

### Fixed

- **Multi-station cloud accounts can be added again** ([#275](https://github.com/joyfulhouse/eg4_web_monitor/issues/275)): the EG4 cloud returns station ids as **integers**, the station-selection dropdown was keyed by those ints, and the Home Assistant frontend submits the selection as a **string** — so validation rejected every choice with "value must be one of [ids]" on any account with more than one station (single-station accounts skip the form, which is why they worked). The selector is now string-keyed with tolerant coercion, the auto-select and reconfigure paths store string ids too, and entries created before the fix are normalized on load — entity and unique IDs are unchanged. Reported by @SimmerV, incorporating their #276.

- **Battery firmware version no longer flaps between "1.3" and "1.03" in HYBRID** ([#287](https://github.com/joyfulhouse/eg4_web_monitor/issues/287)): the local register decode dropped the zero-padding the cloud's `fwVersionText` uses, so the entity alternated between two spellings of the same version depending on which source last supplied it. Fixed in the required pylxpweb ([pylxpweb#199](https://github.com/joyfulhouse/pylxpweb/pull/199)) — the local decode now renders `1.03`. Reported by @ivanfmartinez.

- **Parameter-backed controls no longer go *unknown* for an hour after one bad read** ([#282](https://github.com/joyfulhouse/eg4_web_monitor/issues/282)): a WiFi-dongle misroute storm can fail one of the holding-register range reads behind the hourly parameter refresh (`Failed to read registers 125-250`). The partial result then **replaced** the full parameter set — every control backed by the failed range (e.g. **System Charge SOC Limit**, register 227) flipped to *unknown* within seconds — and the 60-minute refresh throttle was armed anyway, so the blank state persisted until the next hourly pass. This is long-standing behavior (identical in beta.16 and earlier), not a beta.17 regression — dongle misroute storms just make it frequent. Now, following the #261 sticky precedent: a partial read **carries forward last-known values** for the failed range(s) (only successfully re-read ranges change; a fully successful read remains authoritative and prunes stale keys), the throttle is **not** armed by a failed/partial read — the refresh retries early (rate-floored at ~2 minutes) until a clean read, then the hourly cadence resumes — and one INFO line summarizes the failed range(s) instead of silent blanking. Applies to LOCAL and HYBRID local reads and the cloud parameter path alike; the pylxpweb side ships the same carry-forward in its parameter fetch plus a `parameters_complete` flag the throttle now consults ([pylxpweb#198](https://github.com/joyfulhouse/pylxpweb/pull/198)). Reported by @ivanfmartinez.

- **HYBRID: local battery-read outage cycles stay in the hybrid merge (defense-in-depth)** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258)): in the 2026-06-28 follow-up report (LXP-LB, 8 batteries, WiFi dongles), a single failed battery block read (`Failed to read battery registers 5002-5121`) flipped every individual battery entity **unavailable at that exact second** — the momentarily empty transport battery list made the cycle fall through to the cloud-only battery path, which (pre-#252) derived different battery keys on LuxPower-portal systems. The blackout itself is **root-fixed by #252's key unification** (both paths now derive the same canonical keys, and the registry is migrated accordingly). This change is the remaining consistency guard: with a local transport attached and cloud batteries known, the hybrid merge now also runs when the transport list is momentarily empty (a dropped 5002+ block read on pylxpweb ≤ 0.9.36b18) or cleared by a link-down — so outage cycles keep the same sensor mapping and stale-local-vs-fresh-cloud overlay semantics instead of swapping to the cloud-only extraction (different sensor set, re-stamped `battery_last_seen`) for a cycle. The 9-hour freeze mechanism from the same report is fixed at the root in pylxpweb ([pylxpweb#195](https://github.com/joyfulhouse/pylxpweb/pull/195)): failed block reads serve the last-known accumulated batteries, rotation stalls emit a latched warning, and the supplemental cloud refresh stays alive when the whole local feed freezes. Reported by @ivanfmartinez.

- **Grid Sell Back Power is a kW control, not a percent** ([#274](https://github.com/joyfulhouse/eg4_web_monitor/issues/274)): the reg-103 export cap shipped as a 0-100 % number, trusting the protocol PDF and the cloud key name (`HOLD_FEED_IN_GRID_POWER_PERCENT`). It is actually **kilowatts with 100 W raw units** — the same encoding as the AC/PV/forced-charge power registers: the 2026-04-13 live register probe read raw **160** on the very 18kPV whose cloud named read returns **"16"**, and both vendor web UIs label the field "Grid Sell Back Power(**kW**)". On @ivanfmartinez's LXP-LB the website value 12.1 kW (raw 121) failed the old 0-100 integer check, so the entity sat on *unknown* and never reflected website changes; on EG4 hybrids the number silently showed kW labeled as %, and a cloud write of "50 %" actually set a 50 kW cap. The entity now displays kW (0-25.5 in 0.1 steps), scales the raw register ×10/÷10 on the local path, sends kW floats on the cloud path, and keeps the same entity/unique ID. Review automations that set this number: values are now interpreted as kW.
- **One battery identity across Cloud/Local/Hybrid — mode changes no longer duplicate battery devices** ([#252](https://github.com/joyfulhouse/eg4_web_monitor/issues/252)): Cloud mode keyed battery devices by battery **serial** while Local/Hybrid keyed them by **position** (`-01…-NN`), so migrating a cloud entry to hybrid re-keyed every battery that reports a real BMS serial — creating a second set of battery devices and leaving the originals stale. All modes now derive the same serial-first key (packs without BMS serials keep their positional `-NN` keys, which is why most EG4 packs never saw the bug). Existing installs are migrated automatically once serials are known: positional devices are **re-identified in place** (same device — automations, dashboard cards, area, name and labels survive) and entity unique_ids are renamed in place (entity IDs and recorded history preserved). On installs that briefly ran both identities (the reporter's cloud→hybrid case), the positional *duplicates* are removed — the surviving cloud-era entities keep their history, but the short-lived duplicates' own history is deleted, not merged. Two deliberately conservative carve-outs skip the automatic rename and leave the old positional entities as removable orphans: packs that rotate more batteries than the 4 register slots (their positional history cannot be attributed to the right battery), and payloads reporting duplicate battery serials. Note: downgrading to an older beta re-creates the positional duplicates. Reported by @ivanfmartinez.

## [3.4.0-beta.17] - 2026-06-23

> Requires [pylxpweb 0.9.36b18](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b18)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **HYBRID `>4`-battery systems: the 5th battery no longer slows to hourly updates** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258)): beta.16 restored cloud login and added a freshness overlay so a stale *local* battery yields to the fresher *cloud* value. But on the reporter's non-rotating 18kPV firmware, the moment the firmware placed the 5th battery into a Modbus slot even once, pylxpweb's never-evict accumulator cached that block and re-presented it forever — making the library believe the local side already surfaced all five batteries. That switched off the supplemental cloud refresh that had been keeping the 5th battery current, so it dropped from ~5-minute to roughly hourly updates and looked "stuck"/"dropped" on the dashboard. The supplemental-refresh gate now ignores any battery whose local reading has fallen behind its freshest sibling, so the cloud refresh keeps running and every battery stays current. Requires [pylxpweb 0.9.36b18](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b18), which also adds raw round-robin slot logging to help pin down why this firmware barely rotates. Reported by @firestormo.

- **12000XP (and other SNA-platform units) missing all controls in Cloud mode** ([#259](https://github.com/joyfulhouse/eg4_web_monitor/issues/259)): a 15 kW 12000XP reported its model over the cloud as `SNA-US 15K`, and the integration decided which inverters get writable entities (switches, numbers, selects) purely by matching that model string against a list of known substrings (`xp`, `12k`, `18k`, …). `SNA-US 15K` contains none of them — `"15k"` was not in the list and there is no `xp`/`sna` token — so the device was created with **no Controls and no Configuration blocks at all**: no Quick Charge, no charge/discharge limits, no operating-mode selects. (A 12 kW unit reporting `SNA-US 12K` slipped through by accidentally matching `"12k"`, which is why other 12000XP owners did have controls.) The control gate now also accepts any device whose detected inverter family is one the integration drives (`EG4_OFFGRID`, `EG4_HYBRID`, `LXP`) — a signal that is available in every connection mode (cloud included) — so these units get their full control set regardless of how the cloud spells the model name. Off-grid units still correctly omit the grid-tied-only controls (Peak Shaving / Forced Discharge). Reported by @brendonlobo123 and @ivanfmartinez.

## [3.4.0-beta.16] - 2026-06-22

> Requires [pylxpweb 0.9.36b17](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b17)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **Cloud login no longer fails on parallel-group systems — restoring data on systems with more than 4 batteries** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258)): on a parallel system the EG4 cloud can report the *parallel group* (e.g. `Parallel_A`) as the account's "last visited device", and that record omits the per-device fields (phase, device type, battery type, …) that pylxpweb's login model required — so **every cloud login failed validation**. The integration repeatedly hit `ConfigEntryNotReady` on restart, and in HYBRID mode the cloud half went silent (flooding the log with validation errors). With cloud polling dead, any battery the inverter wasn't currently exposing over local Modbus went stale — exactly the ">4 batteries don't pull reliably" symptom on the affected 18kPV. The login model now treats those last-visit fields as optional (they are informational only and used nowhere), so login succeeds and cloud data flows again. Fixed in [pylxpweb 0.9.36b17](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b17); the manifest now requires it. Reported by @firestormo.
- **HYBRID: batteries the firmware only surfaces part of the day no longer freeze** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258), [#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): some 18kPV firmware exposes only a subset of its batteries through the local Modbus register page for long stretches (e.g. one battery during the day, all of them at night) while the EG4 cloud reports all of them. The integration accumulates local battery data and never drops a battery once seen (so genuinely round-robin systems keep every battery), but in HYBRID mode that meant a battery's last *local* reading was overlaid on top of the *fresher cloud* reading — freezing it until the firmware surfaced it locally again hours later. HYBRID now keeps the fresh cloud value whenever the local reading for a battery is older than the cloud refresh interval, so every battery keeps updating; LOCAL-only installs are unchanged (they have no cloud to fall back to). A companion pylxpweb 0.9.36b17 change stamps each battery's "last seen" time in UTC so this freshness check is correct even when the container's timezone differs from Home Assistant's.
- **Duplicate "Has Runtime Data" sensor removed** ([#253](https://github.com/joyfulhouse/eg4_web_monitor/issues/253)): every inverter exposed this diagnostic flag twice — two `..._has_runtime_data` sensors holding the identical value (e.g. `sensor.lxp_us_8_10k_XXXX_has_runtime_data` and `sensor.lxp_lb_us_10k_XXXX_has_runtime_data`), differing only by the model name in the entity ID because each was first registered under a different model string. They came from two internal keys (`has_data` and a redundant `inverter_has_runtime_data`) that resolve to the same underlying state ("runtime or transport data is present"). The redundant sensor has been removed, and its now-orphaned registry entry is purged automatically on restart, leaving a single "Has Runtime Data" sensor per inverter. Affects Cloud and Hybrid installs. Thanks @ivanfmartinez for the report.

## [3.4.0-beta.15] - 2026-06-22

> Requires [pylxpweb 0.9.36b16](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b16)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **`Fault Code` / `Warning Code` no longer flicker to "unknown" on a dropped `bms_data` read** ([#261](https://github.com/joyfulhouse/eg4_web_monitor/issues/261)): beta.14 fixed the *full link-down* case (the codes hold their last value when the local Modbus link drops entirely), but they still went **unknown** in the far more common case where only the BMS register block (`bms_data`, regs 80-112) dropped while the rest of the read succeeded — the frequent WiFi-dongle mismatch storms [@ivanfmartinez](https://github.com/ivanfmartinez) reported, which (as he noted) did *not* correlate with full link-downs. The inverter's own fault/warning registers (60-63) read a healthy `0`, but pylxpweb merged that `0` with the now-missing BMS fallback code as `0 if 0 else None` → `None`, and a `None` code is dropped from the sensor payload (so the sensor reads *unknown*) in **both** HYBRID and LOCAL mode. Fixed in [pylxpweb 0.9.36b16](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b16): a known-healthy `0` is preserved when only the BMS read drops, and the codes go `None` only when neither register was read at all. An active fault from either source is still reported. The manifest now requires `pylxpweb>=0.9.36b16`.

## [3.4.0-beta.14] - 2026-06-21

> Requires [pylxpweb 0.9.36b15](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b15)
> (installed automatically; the manifest requirement is bumped).

### Added

- **New "Operating State" sensor and "Off-Grid" binary sensor** ([#262](https://github.com/joyfulhouse/eg4_web_monitor/issues/262)): the inverter's operating-mode code — previously surfaced only as the raw numeric **Status Code** — is now also decoded into a friendly **Operating State** enum sensor (e.g. `Battery → Grid`, `AC → Battery`, `PV → Battery`, `Off-Grid (Battery)`), following EG4's "Table 9" operational-mode definitions. It is available in **all** connection modes (cloud, local and hybrid) — previously only the bare number changed while the text "Status" stayed at "normal". A companion **Off-Grid** binary sensor turns on whenever the inverter is islanded (any operating mode ≥ 0x40, including off-grid AC-coupled charging), giving automations a single boolean to detect off-grid operation. The numeric **Status Code** is unchanged. The cloud connection/health string previously labelled **Status** is renamed **Cloud Status** to distinguish it from the operating mode (its entity ID is unchanged, so existing automations and dashboards keep working). All operating-state labels are translated across every supported language. Mode decode (off-grid threshold, AC-vs-grid charging, the off-grid AC-couple state) verified against real hardware by @ivanfmartinez.

### Fixed

- **Some HYBRID sensors no longer flicker to unknown/unavailable** ([#261](https://github.com/joyfulhouse/eg4_web_monitor/issues/261)): in HYBRID mode (local + cloud) a few sensors briefly dropped out on a transient local-transport hiccup while cloud-only sensors (e.g. `Status Code`, `Grid Type`) stayed put. Two independent causes:
  - **`Battery Bank SOC`** (and the other `Battery Bank` aggregates) went **unavailable** whenever the inverter's reported battery count (Modbus register 96) momentarily read 0 — which it does on parallel/multi-battery systems (see [#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258)/[#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)). The bank's aggregate readings are still valid in that moment, but the whole bank was dropped instead of falling back to the cloud. The integration now **falls back to the cloud battery reading** when the local count is unreliable, and a complementary pylxpweb fix (0.9.36b15) **preserves the last-good battery reading when the local `bms_data` read drops entirely** (the common WiFi-dongle case — and the only fix that also covers LOCAL mode, which has no cloud to fall back to). A genuine battery-less secondary inverter (which reports 0 on *both* sources) still correctly has no battery bank ([#169](https://github.com/joyfulhouse/eg4_web_monitor/issues/169) preserved).
  - The transport-only **`Fault Code`** / **`Warning Code`** sensors went **unknown** during a transient local Modbus link-down (the cloud API has no fault field, so these have no cloud fallback). They now **hold their last-known value through a brief local outage** instead of blanking. Live measurements are deliberately *not* held this way — they must read honestly during an outage.
- **All batteries now reported on systems with more than 4 batteries** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258), [#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): inverters expose individual battery data through 4 fixed Modbus register slots and rotate systems with more than 4 batteries through those slots over time. The integration relied on the inverter's reported battery count (Modbus register 96), which is unreliable on parallel systems — it reports 12 for a 6-battery bank and intermittently 4 for a 5-battery bank — so the extra battery was repeatedly dropped (it would appear briefly after a restart, then vanish). Battery data now accumulates by battery serial number and ignores register 96 entirely, so every battery appears and stays once it has been seen (a battery rotated out of view keeps its last reading until it cycles back). Fixed in pylxpweb 0.9.36b15; the manifest now requires it.

- **An offline inverter no longer blacks out all of its entities** ([#256](https://github.com/joyfulhouse/eg4_web_monitor/issues/256)): when an inverter goes offline (cloud `lost: true`) the EG4 cloud returns a *partial* runtime/battery payload that omits the live measurement fields. pylxpweb's `InverterRuntime`/`BatteryInfo` models declared those fields required, so the whole response failed validation, the device reported `has_data=False`, and **every** Home Assistant entity for that inverter — including `Status` — went `unavailable`, while a second, online inverter in the same station (e.g. a FlexBOSS21 next to an 18kPV) was unaffected. The offline device now reports `Status = offline` with its live metrics as *unknown*, instead of disappearing. Fixed in pylxpweb 0.9.36b13 (cloud-omittable fields made optional; battery-bank aggregates made `None`-safe); the manifest now requires `pylxpweb>=0.9.36b13`.
- **Quick Charge Duration no longer leaks a restored countdown into the cloud start** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): on LOCAL/HYBRID the number mirrors the live holding register 234, so a value restored across a restart (e.g. "3" captured mid-charge) is a stale countdown reading, not a preference. It was being stored as the cloud start `minute` and could make a HYBRID cloud-fallback start a 3-minute charge. The restored value is now kept as a preference only on cloud-only installs (no configured local transport). Found by adversarial review while finalizing #251.

## [3.4.0-beta.13] - 2026-06-15

> Requires [pylxpweb 0.9.36b12](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b12)
> (installed automatically; the manifest requirement is bumped).

### Changed

- **`Quick Charge Duration` faithfully mirrors the live register** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): in LOCAL/HYBRID the number now shows exactly what holding register 234 holds — idle *and* while charging — instead of a retained UI preference, so it always agrees with what the inverter reports (the firmware governs that value: it starts a charge at its own default, counts down, and rejects changes while quick charge is off). Setting it **while a charge is running** writes register 234 to extend/reduce the charge; setting it **while idle** now returns a clear "Quick Charge must be running to set its duration" message instead of silently storing a value the inverter would reject. The per-serial preference is now used only on the CLOUD path (which has no such register), as the start `minute`. Thanks @ivanfmartinez (LXP-LB) for the hands-on testing.
- **`Quick Charge Remaining` sensor now reports seconds** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): in LOCAL/HYBRID the remaining time prefers **input register 210** (the dedicated seconds-resolution countdown on newer firmware) and falls back to holding register 234 (minutes) when it isn't available; CLOUD reads it from the API. The sensor's unit changed from minutes to seconds to surface that resolution (the `duration` device class renders it human-readably).

> Note: the `Quick Charge Duration` number (holding register 234, writable minutes) and the `Quick Charge Remaining` sensor (input register 210, read-only seconds) are intentionally kept as two separate entities — one per hardware register.

## [3.4.0-beta.12] - 2026-06-15

> Requires [pylxpweb 0.9.36b11](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b11)
> (installed automatically; the manifest requirement is bumped).

### Changed

- **Quick Charge remaining time uses the dedicated countdown register** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): in LOCAL/HYBRID the remaining time now prefers **input register 210** (the seconds-resolution countdown on newer firmware, ≈v25+) and falls back to the minute-resolution holding register 234 when it isn't available; CLOUD continues to read the remaining time from the API. The **`Quick Charge Duration`** number now reflects the **live remaining time while a charge is running** (instead of a stored preset), so it agrees with the **`Quick Charge Remaining`** sensor rather than disagreeing until a refresh; when idle it shows the stored preference (default 60) applied on the next start. The **`Quick Charge Duration` number (holding register 234, writable minutes) and the `Quick Charge Remaining` sensor (input register 210, read-only seconds) are intentionally kept as two separate entities** — one per hardware register — rather than collapsed into one. Per LXP-LB hardware reports (@ivanfmartinez). Requires pylxpweb 0.9.36b11.

## [3.4.0-beta.11] - 2026-06-13

> Requires [pylxpweb 0.9.36b10](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b10)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **Quick Charge in LOCAL/HYBRID now matches the real hardware behaviour** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): on real LXP-LB hardware (thanks @ivanfmartinez) the inverter firmware **rejects writes to the duration register (234) while Quick Charge is off**, which made beta.10 fail two ways — the switch's start duration was silently ignored, and setting `Quick Charge Duration` while idle raised a write error. Now the **`Quick Charge` switch** just starts the charge at the firmware default length, and **`Quick Charge Duration`** writes register 234 *live* only while a charge is actually running (raising it extends the running charge — the cell-balancing / keep-charging use case). While Quick Charge is off the number simply stores the preference (no inverter write, no error). The live state is confirmed with a fresh register read at write time (not a cached value), so a duration change is never silently dropped right after the switch turns on nor rejected right after a charge auto-expires; if the inverter state can't be read the change is surfaced as an error rather than reported as a false success. The cloud path (minute-based Quick Charge from beta.9) is unchanged. Requires pylxpweb 0.9.36b10.

## [3.4.0-beta.10] - 2026-06-13

> Requires [pylxpweb 0.9.36b9](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b9)
> (installed automatically; the manifest requirement is bumped).

### Added

- **Quick Charge in LOCAL/HYBRID mode** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): the `Quick Charge` switch and `Quick Charge Duration` number now work over a local transport, not just the cloud API. With a local connection they drive holding registers directly — register 233 bit 0 (enable) and register 234 (duration minutes) — so a fixed-length charge can be started without the cloud. In HYBRID mode local registers are preferred (faster, no cloud dependency), falling back to the cloud API if a local write fails. The `Quick Charge Duration` is also a live setpoint in LOCAL/HYBRID: raising it while a charge runs extends it (e.g. to keep cells balancing). A new **`Quick Charge Remaining`** sensor (minutes) shows the live countdown in every mode. The entities are gated to supported inverter models with a cloud or local transport. Confirmed against an 18kPV and reported working on an LXP-LB. Requires pylxpweb 0.9.36b9.

## [3.4.0-beta.9] - 2026-06-13

> Requires [pylxpweb 0.9.36b8](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b8)
> (installed automatically; the manifest requirement is bumped).

### Added

- **`Quick Charge Duration` control + remaining-time attribute** ([#251](https://github.com/joyfulhouse/eg4_web_monitor/issues/251)): the newer EG4 firmware added a fixed-duration mode to Quick Charge, so a charge can run for a set number of minutes and then stop on its own. A new **`Quick Charge Duration`** number entity (1–1440 minutes, default 60) sets how long the next Quick Charge runs; turning on the **`Quick Charge`** switch now sends that duration to the cloud. The duration is a per-inverter UI preference — it is not written to the inverter until Quick Charge is turned on. When a timed Quick Charge is running, the `Quick Charge` switch now also exposes a **`minutes_remaining`** attribute (alongside the existing `task_id` / `task_status`). Both are HTTP-only and only appear on supported inverter models, mirroring the existing Quick Charge switch gating. Reverse-engineered live on an 18kPV via the cloud API (2026-06-13).

## [3.4.0-beta.8] - 2026-06-13

> Requires [pylxpweb 0.9.36b7](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b7)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **AC Charge SOC Limit now allows 101%** ([#158](https://github.com/joyfulhouse/eg4_web_monitor/issues/158)): the inverter accepts **101%** as a "never stop AC charging" setting (the stop threshold is unreachable since SOC can't exceed 100), used for battery cell balancing — but the entity capped at 100, so a live-101 value read back as **unavailable** and setting 101 was rejected. The number now spans **0–101%** (its own bound, separate from the on-grid/off-grid discharge cutoffs, which stay 0–100), reads a live 101 correctly, and accepts a 101 write in cloud, local, and hybrid modes. Matches the 101 cap already used by the System Charge SOC Limit. Reported by @DoubleDoc on an 18kPV.

## [3.4.0-beta.7] - 2026-06-12

> Requires [pylxpweb 0.9.36b6](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b6)
> (installed automatically; the manifest requirement is bumped).

### Added

- **`Grid Sell Back` switch, `Export PV Only` switch, and `Grid Sell Back Power` number** ([#135](https://github.com/joyfulhouse/eg4_web_monitor/issues/135)): the EG4 web UI's grid-sell controls, used to stop selling to the grid when wholesale prices go negative. All three are gated to grid-tied families (EG4_HYBRID / LXP) — the off-grid XP series has no sell-back. Backed by a read-only register discovery session on production 18kPV + FlexBOSS21 hardware (2026-06-12):
  - `Grid Sell Back` (cloud `FUNC_FEED_IN_GRID_EN`, holding register 21 bit 15, live-verified): master enable for exporting surplus to the grid. Works in cloud, local, and hybrid modes.
  - `Grid Sell Back Power` (cloud `HOLD_FEED_IN_GRID_POWER_PERCENT`): maximum sell-back power as 0–100 % of rated output. The discovery session pinned this parameter to holding register 103 via single-register named reads on both inverters — notably the cloud never uses the protocol spec's `HOLD_MAX_BACKFLOW_POWER_PERCENT` name for it. Whole percent on every transport (raw register and cloud value are the same number), so it works in cloud, local, and hybrid modes with no scaling hazards.
  - `Export PV Only` (cloud `FUNC_PV_SELL_TO_GRID_EN`, holding register 179 bit 3): sell PV surplus only, never battery. Entered this cycle cloud-only (bit position unpinned, with a register-contract honesty test demanding the local wiring the moment the bit got pinned) — and the bit WAS pinned later the same day, unlocking local/hybrid support before release: see the Changed entry below.

- **`Stop Discharge Voltage` control** (bead eg4-aa3t): the voltage-regime counterpart of the Forced Discharge SOC Limit — the cloud maintain page's *"Stop Discharge Volt 1(V)"*, gated by `disChgVoltEnable`. One number entity per inverter (40.0–56.0 V, 0.1 steps), working in cloud, local, and hybrid modes. Holding register 202 was located by single-register cloud window bisection and its raw encoding live-verified as decivolts (raw 400 ↔ cloud 40 V on an 18kPV, 2026-06-11); the cloud accepts fractional volts (round-trip 40 → 41.5 → 40 V on an 18kPV and a FlexBOSS21). Participates in the charge/discharge regime gating like the other voltage cutoffs (disabled by default while the discharge control mode is SOC), rides the existing local parameter poll (one extra holding read per hourly refresh), and is pinned in the register-contract harness like regs 82/83.

### Fixed

- **GridBOSS smart-load automations no longer break on every Home Assistant restart in LOCAL mode** ([#217](https://github.com/joyfulhouse/eg4_web_monitor/issues/217)): the setup-time cleanup that prunes stale smart-port entities ran against the LOCAL first refresh's static placeholder data — which never contains smart-port keys because port statuses are unknown before the first register read. It therefore deleted **every** smart-port registry entry (`Smart Load N Power`, `Smart Load Power`, AC-couple ports, energy sensors) on each reboot, and the late-registration listener re-created them moments later under brand-new registry entry IDs. Automations pin entities by registry entry ID, so each reboot orphaned the reference and the automation failed with `Unknown entity '<32-char id>'` — re-selecting the entity only held until the next restart. The cleanup is now gated on authoritative port data (the `smart_port*_status` values a real poll always carries) and is deferred via a one-shot coordinator listener until the first real GridBOSS read lands, so registry entries — and the automations pinned to them — survive restarts. The same gate protects CLOUD/HYBRID setups whose midbox runtime endpoint returns no data during boot. Genuinely stale entities (ports reconfigured to unused) are still cleaned once real data confirms it.

- **Grid Peak Shaving Power: local-mode writes were landing in the wrong register** (bead eg4-gfu5): pylxpweb's register map placed `_12K_HOLD_GRID_PEAK_SHAVING_POWER` at holding register 231, but a dual-device cloud register sweep (18kPV + FlexBOSS21, 2026-06-12) proves PS1 actually lives at **register 206** (with SOC/voltage members at 207/208 and the period-2 set at 218/219/232) — register 231 is an unnamed, unknown field that silently quantizes writes to even values. In LOCAL and HYBRID modes, setting Grid Peak Shaving Power wrote that unknown register and **never changed the real setpoint** (cloud mode always wrote correctly via the server-side name). The control now writes through the cloud parameter API in cloud and hybrid modes; in pure-LOCAL mode it raises a clear error and registers disabled-by-default, because the true register's raw encoding is still unverified — local writes return once a write window proves it. The wrong read range (231-232) was dropped from the local parameter poll, and the corrected register locations are pinned in the register-contract harness.

- **Dongle/Modbus discovery failures now show a clear connection error instead of "Unexpected error"** ([#250](https://github.com/joyfulhouse/eg4_web_monitor/issues/250)): when the dongle resets the TCP connection during device discovery (typically because another client holds the dongle's single local-client slot, or dongle firmware blocks local access), pylxpweb raises its transport exceptions — which are not `OSError` subclasses, so the config flow's handlers missed them and the UI showed the generic "unknown" error with a full traceback in the log. All four discovery paths (add + reconfigure, dongle + Modbus TCP) now map `TransportError` to the proper "connection failed" message and `TransportTimeoutError` to the timeout message, and log the underlying cause (which carries pylxpweb's diagnostic hints) as a one-line warning instead of a scary stack trace.

- **pylxpweb (next release): Battery ECO Mode register-110 mapping corrected for EG4_OFFGRID** (claim 1 of PR #220, hardware-verified by @jesserobbins on a 12000XP): the library mapped `FUNC_BATTERY_ECO_EN` to register 110 bit 9 — the 18kPV-derived position — but the SNA platform keeps ECO at **bit 15** (live bidirectional toggle evidence; raw `0x0080`↔`0x8080`; cross-confirmed by the stock SNA cloud decode placing the buzzer at bit 7 and by the ant0nkr lxp_modbus reference). Local transports now use an SNA-specific register-110 layout (`OFFGRID_REGISTER_110_PARAM_KEYS`: ECO=15, buzzer=7, displaced/unverified slots as placeholders). No integration entity reads or writes ECO, so nothing user-visible changes yet — the correction unblocks a future Battery ECO Mode switch once an owner validates it end-to-end. The AC-couple-energy scale claim from the same PR (regs 124-126 as raw Wh) was **rejected** for now: the reporter's own earlier sweep decoded input 124 as a holding-179 status mirror, the successive captures moved by exact powers of two (bit-field churn, not energy), and the claimed today-vs-lifetime figures are mutually inconsistent — the registers stay unmapped to sensors pending a fresh capture.

### Changed

- **Peak Shaving and Forced Discharge controls are no longer created for the EG4 Off-Grid family** (adjudication of [@jesserobbins](https://github.com/jesserobbins)' withdrawn [PR #220](https://github.com/joyfulhouse/eg4_web_monitor/pull/220) findings, [#197](https://github.com/joyfulhouse/eg4_web_monitor/issues/197) follow-up): the Grid Peak Shaving Mode and Forced Discharge Mode switches plus the Grid Peak Shaving Power, Forced Discharge Power, and Forced Discharge SOC Limit numbers are suppressed on positively-identified 12000XP/6000XP devices. These functions act on grid-parallel export/import blending, which the SNA platform does not do (no sellback; bypass-or-invert topology) — the registers exist on the shared Luxpower layout but the functions are inert (stock SNA cloud data and the #222 6000XP capture both read them permanently disabled, and the SNA parameter set does not expose the peak-shaving power register at all; the platform's real knobs are `FUNC_GEN_PEAK_SHAVING` and the `LSP_*` discharge controls). Devices without a positively detected family keep all controls (fail-open). Users who already had the entities get a **Repairs issue** explaining the removal, in all 13 languages (#219 precedent).

- **Off Grid Mode (Green Mode) writes on the EG4 Off-Grid family now go through the cloud only** (same adjudication, hardened in adversarial review): the local write targets register 110 bit 8 per the 18kPV-derived map, but the SNA platform's register-110 upper-bit layout is hardware-proven to differ (buzzer at 7, ECO at 15 — PR #220) and green's true position there is unverified (the lxp_modbus reference puts it at bit 14). A local bit-8 write on a 12000XP/6000XP would likely flip a CT-sampling config bit while reporting success. HYBRID/CLOUD setups are unaffected (the cloud maps the bit server-side, as before); pure-LOCAL off-grid setups now get an honest error instead of a silent wrong-bit write. A community toggle capture (read holding 110, toggle Green Mode in the EG4 web UI, read again) will pin the bit and restore local writes.

- **`Export PV Only` now works in LOCAL and HYBRID modes — register 179 bit 3 pinned** ([#135](https://github.com/joyfulhouse/eg4_web_monitor/issues/135)): authorized live cloud functionControl toggles (2026-06-12, ~16:05–16:07 PT), raw-verified via `remoteRead` (179, 1) valueFrame (base64 LE uint16) on BOTH 12K-hybrid models — FlexBOSS21 SYNTH00003 and 18kPV SYNTH00004 each toggled the reg-179 raw frame `0x104c` ↔ `0x1044` (XOR `0x0008` = single bit 3) in lockstep with the named parameter, restores verified by re-read. Direct proof on both family models — no extrapolation. With pylxpweb ≥ 0.9.36b6 the switch is now created in local-raw setups (LOCAL mode, HYBRID with an attached transport) and writes go through the transport named-parameter read-modify-write; state reads come from the locally decoded bit. Against released pylxpweb 0.9.36b5 a register-map probe (`_local_params_can_carry`, the generalized successor of the per-mode `requires_cloud_params` flag) keeps the previous cloud-only behavior at BOTH setup time (no lying entity in local-raw setups) and write time (legacy flat-HYBRID toggles go straight to the cloud method instead of attempting a doomed local write — hardened in adversarial review). The register-contract harness moved `FUNC_PV_SELL_TO_GRID_EN` from the cloud-only allowlist into the pinned contract at (179, 3) — exactly the promotion its honesty tripwire was designed to force (that contract row is deliberately RED against pylxpweb < 0.9.36b6 as the release cut-blocker). The off-grid / no-sellback model gating is unchanged.

## [3.4.0-beta.6] - 2026-06-12

> Requires [pylxpweb 0.9.36b5](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b5)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **Loads no longer goes unknown during a hybrid local-link outage on the EG4 Off-Grid family** ([#226](https://github.com/joyfulhouse/eg4_web_monitor/issues/226) residual, found during the beta.5 reconnect verification): while every other sensor fell back to cloud data, `total_load_power` vanished — it was only ever fed by the local transport overlay, because the cloud's generic `consumptionPower` field reads a false 0 on these units. The off-grid family now falls back to the authoritative cloud split (`epsLoadPower + smartLoadPower + gridLoadPower`, via pylxpweb 0.9.36b5), so Loads rides out an outage like everything else. Bonus: pure-CLOUD off-grid setups gain the Loads sensor for the first time. Grid-tied models are intentionally unchanged (their per-inverter cloud consumption field is unreliable, so honest-unknown remains correct there).

## [3.4.0-beta.5] - 2026-06-12

> Requires [pylxpweb 0.9.36b4](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b4)
> (installed automatically; the manifest requirement is bumped).

### Added

- **`Smart Load Power` and `Grid Load Power` sensors for the EG4 Off-Grid family** ([#222](https://github.com/joyfulhouse/eg4_web_monitor/issues/222)): on the 6000XP (and 12000XP) the GEN terminal doubles as a smart-load output, and the existing `EPS Load Power` / `EPS Power` sensors carry the COMBINED backup-path output — a ~3 kW EV charger on the GEN port was invisible as its own reading (live evidence: EPS L1+L2 = 3371 W = smart load 2999 W + EPS loads 365 W). The cloud's `smartLoadPower`/`gridLoadPower` split is now surfaced as two W sensors in CLOUD and HYBRID modes (cloud-supplemental; entities gated to EG4_OFFGRID; requires pylxpweb 0.9.36b4, which also keeps the values fresh in HYBRID by refreshing the cloud runtime for off-grid devices on the normal runtime cadence). Pure-LOCAL mode does not get them — no validated Modbus register carries the split on this family (the 18kPV firmware RE names input reg 232 `smart_load_power`, but it is unvalidated on off-grid hardware and never observed non-zero). The EPS-only figure is `EPS Load Power` − `Smart Load Power`; existing eps sensors are intentionally unchanged for entity stability.

- **`Forced Discharge Power` and `Forced Discharge SOC Limit` controls** ([#207](https://github.com/joyfulhouse/eg4_web_monitor/issues/207), co-authored with [@DevTodd](https://github.com/DevTodd) from [PR #249](https://github.com/joyfulhouse/eg4_web_monitor/pull/249)): two number entities per inverter backed by holding registers 82/83, working in cloud, local, and hybrid modes. The power command is kW (0–25.5, 0.1 steps — register 82 stores 100W units, hardware-verified by @DevTodd: panel entry 2.5 kW reads back raw 25); the SOC limit is percent. Both ride the existing Modbus parameter read through the parameter-cache architecture — no extra bus traffic, dongle-safe. The SOC limit participates in the charge/discharge regime gating like the other SOC cutoffs (mirroring the cloud UI, which gates the same field); the power command applies in both regimes. Use case from the report: closed-loop regulation of forced-discharge output against an external CT.

### Fixed
- **6000XP units reporting device type code 38 are now positively identified as EG4_OFFGRID** ([#222](https://github.com/joyfulhouse/eg4_web_monitor/issues/222), via pylxpweb 0.9.36b4): the reporter's 6000XP returns 38 from HOLD_DEVICE_TYPE_CODE (register 19) instead of the documented 54, which left family detection at UNKNOWN before the beta.4 model-name fallback and still mislabels the local model name. Code 38 now maps to the EG4 Off-Grid family everywhere the type code is consulted (feature detection, transport discovery, model naming), so family-gated entities (EPS load power set, smart load split, discharge recovery controls) engage from the type code itself rather than the fallback.
- **Non-English locales caught up — 29 missing keys translated in all 13 languages**: the beta.3 connection-retry and Repairs work plus the historical-import service and battery-control-mode options shipped their `exceptions.*`, `issues.*`, `options.*`, and `services.*` strings in English only, so German/Spanish/French/Italian/Japanese/Korean/Dutch/Polish/Portuguese/Russian/Chinese users saw untranslated fallbacks. All locales are complete again, and a new locale-parity test now fails CI if any future string lands without its translations (placeholder integrity included).
- **AC/PV Charge Power displayed 10x for small values in HYBRID mode** ([#207](https://github.com/joyfulhouse/eg4_web_monitor/issues/207), reported by @icepop456): with a local transport attached, `inverter.parameters` is populated with raw 100W register values, and settings at or below 1.5 kW passed the kW bound and displayed 10x high (0.7 kW showed 7 kW — display only, the actual setpoint was correct). Both entities now read the scaled parameter cache exclusively when a local transport is attached, the same guard the new Forced Discharge Power control shipped with.

- **Historical import: plant-level `grid_import` series no longer empty** (via pylxpweb 0.9.36b4, live-found during beta.4 verification): the cloud's parallel-group month endpoint names grid import `eImportDay` while the single-inverter endpoint uses `eToUserDay` — the parser only knew the latter, so `import_historical_data` reported `no_data` for grid import on multi-inverter plants while the other five series worked. Re-running the service after updating backfills the series (idempotent). The generator-port daily series (`eGenDay` — AC-coupled PV on gen-port sites) is now parsed too.

- **WiFi dongle recovers from silent connection loss without a reload** ([#226](https://github.com/joyfulhouse/eg4_web_monitor/issues/226), via pylxpweb 0.9.36b4): when the network path to the dongle dropped *silently* — a VPN tunnel break or NAT timeout that delivers no TCP reset — the transport kept polling the same dead connection forever and only an integration reload recovered (a reporter's gateway packet capture showed zero reconnection attempts; the beta.4 reconnect work covered the Modbus TCP transport but not the dongle's raw-TCP path). Every response timeout now tears the connection down, so the next poll — or the link-down probe that beta.4 added — dials a fresh TCP connection and polling self-restores within a cycle or two of the path returning. Also hardened: connection state can no longer be corrupted by partially-failed connects, concurrent connection attempts to the dongle's single TCP slot are serialized, and a write is never blindly retransmitted after a lost ACK (the retry re-reads the register first, so a concurrent change can't be overwritten with stale bit-fields).

## [3.4.0-beta.4] - 2026-06-11

### Changed

- **`Output Power` now means load output on every connection mode** (eg4-9e4): in cloud/hybrid this sensor was an exact duplicate of `AC Power` (both read `pinv` — live-confirmed identical on production), while LOCAL read register 170 (Pload). It now carries register-170 load-output semantics everywhere, sourced from the cloud's `pLoad170` mirror in pure-cloud mode — a genuinely distinct reading that pure-cloud systems previously had no way to get. Consequences: pure-cloud values change from inverter AC output to load output; the entity is no longer split-phase-gated (it exists on all families); and pure-cloud EG4_OFFGRID systems (12000XP/6000XP) get **no** `output_power` entity rather than a false 0 — the cloud zeroes its reg-170 mirror for those models (#197), so only positively-trusted families (EG4_HYBRID live-verified, LXP) publish the cloud value.

### Added

- **New service `eg4_web_monitor.import_historical_data`** ([#73](https://github.com/joyfulhouse/eg4_web_monitor/issues/73)): opt-in, idempotent import of plant-level daily energy history (PV yield, consumption, grid import/export, battery charge/discharge) from the EG4 cloud into separate external long-term statistics (`eg4_web_monitor:plant_…`), selectable in the Energy dashboard. Bounded to 2 years per call, with `dry_run` preview, a per-series response summary, per-plant serialization, and DST-correct day alignment (prefers Home Assistant's IANA timezone over the cloud's fixed-offset station strings). Re-running a range is safe — sums are recomputed from all committed rows. Requires pylxpweb ≥ 0.9.36b3; on older versions the service reports a clean "library too old" error.
- **Register-derived contract harness** (eg4-1z8): a 20-test suite that derives the expected sensor mappings from pylxpweb's canonical register tables and asserts the LOCAL register path and the CLOUD/HYBRID property path feed every sensor key from the same canonical source — the structural cure for the recurring "fixed on one connection mode, still broken on the other" bug class. Exact coverage accounting (silent drops fail loudly), stale-allowlist detection, and a routed inventory of 8 real divergences discovered on day one (tracked: eg4-7uz, eg4-9e4, eg4-9wf, eg4-bc0, eg4-23a6, eg4-6ag2).
- **Inverter `Fault Code` and `Warning Code` diagnostic sensors** (eg4-23a6): the raw 32-bit fault/warning registers (input regs 60–63, with the BMS regs 99/100 fallback merge pylxpweb already performs) are now surfaced per inverter in LOCAL and HYBRID modes — `0` means healthy, any other value is the raw code for support/automations. Cloud-only systems don't get these entities because the EG4 cloud runtime API genuinely doesn't carry the fields (verified against the live API); in hybrid they ride the local transport like the other Modbus-only sensors and go unavailable honestly when the link is down. Translated in all 14 locales.

### Fixed

- **A local transport that dies mid-run no longer freezes entities on stale data** ([#226](https://github.com/joyfulhouse/eg4_web_monitor/issues/226) second half, eg4-57g): after 3 consecutive failed local reads the link is declared down — one log warning plus a Repairs issue that clears on recovery. In HYBRID the device falls back to cloud refreshes at the normal cadence and the Connection Transport sensor reads "link down"; in LOCAL its measurement entities (device, battery bank, and parallel-group aggregates — including during the brief cached-data window of a full outage) go honestly unavailable instead of replaying the last values. The dead link keeps being probed every cycle (with same-tick duplicate probes collapsed) and everything self-restores on reconnection. Also fixes the underlying recovery bug via pylxpweb 0.9.36b3: a dropped TCP session raised pymodbus `ConnectionException`, which the reconnect gate's error counter never saw — so the transport stayed wedged on a dead socket until a manual reload. That mechanism matches the #226 report exactly.
- **Battery cell-number sensors uncrossed in LOCAL/HYBRID** (via pylxpweb 0.9.36b3): the per-battery "Max/Min Cell Temperature Number" and "Max/Min Cell Voltage Number" sensors were swapped on the local Modbus path — register offset 14 carries the temperature cell numbers and offset 15 the voltage cell numbers, the reverse of the legacy map. Cloud mode was always correct; local and hybrid now match it (proven against same-minute cloud/local snapshots of the same batteries, including the unambiguous 0/0 marker case).
- **HYBRID: battery-bank register sensors could be missing after a restart** (live-found on production validating beta.3): sensor entities are created from the keys present during platform setup, but in hybrid mode the first refresh is cloud-only by design — the LOCAL-register battery-bank sensors (BMS charge/discharge current limits, charge voltage reference, discharge cut-off voltage, battery type, cycle count, inverter-sampled battery voltage) only appear once the second coordinator cycle has read the local transport, ~5 seconds later. Losing that race at boot left 14 bank sensors unavailable until a manual reload. Battery-bank sensors now late-register when their keys appear, the same way transport-only inverter sensors already did. (Latent since the hybrid bank overlay was introduced; not a beta.3 regression.)
- **Same-class gaps closed by review of the fix above**: parallel-group aggregate sensors derived from member bank data (`parallel_battery_current`, `parallel_battery_charge_rate`) now late-register too — previously the late-registration listener skipped parallel-group devices, stranding those keys when the first cycle had no bank data. And the button platform gained late registration for **per-battery refresh buttons**, which were silently missing on LOCAL-mode boots (the zero-read static first refresh has no batteries yet) and on hybrid boots whose first cloud battery fetch failed.
- **Cloud/HYBRID GridBOSS now surfaces `Consumption Power` and `Generator Frequency`** (eg4-7uz, first divergence retired from the contract-harness inventory): the cloud MID property map omitted both keys, so GridBOSS systems connected via the cloud silently lacked two sensors the LOCAL path has always provided. Consumption power keeps its documented semantics — the GridBOSS load CT measurement (`consumption_power` = `load_power`), expressed as an explicit alias table that the contract harness now checks alongside the main map, so the two paths can no longer drift apart on these keys.
- **LOCAL `Grid Power` was rectifier power, not grid power** (eg4-9wf): in LOCAL mode the sensor read register 17 (`Prec`, the AC→DC rectifier/charging power — a different physical quantity that already has its own `Rectifier Power` sensors), while cloud/hybrid computed the net grid flow. LOCAL now computes the same net value from the canonical to-user/to-grid registers (27/26): positive = importing, negative = exporting, `unknown` on a partial read instead of fabricating flow from one side. The misnamed pylxpweb field was renamed (`rectifier_power`, deprecated read-alias kept), and `docs/DATA_MAPPING.md` no longer contradicts itself about register 17.
- **Yield canonical pairing corrected in pylxpweb** (eg4-bc0): the cloud's `todayYielding` is PV yield — proven from the portal's own pie-chart fields, whose permille slices distribute `todayYielding` and whose export slice equals `todayExport` exactly — so the integration's existing mapping (LOCAL PV-string sum, cloud `todayYielding`) was right all along. The library's canonical table wrongly paired `yield` with register 31 (`Einv_day`, inverter output energy); registers 31/46 are now labeled as the inverter-output energy they actually are, and the contract harness enforces the corrected triangle. Register-table hygiene from the same review (eg4-6ag2): PV4–6 daily/lifetime energy labels aligned to the integration's `pv4_yield…` keys, and `FUNC_BATTERY_BACKUP_CTRL` (register 233 bit 1) added to the canonical holding table. **All 8 divergences found by the contract harness on day one are now fixed and retired from its inventory.**

## [3.4.0-beta.3] - 2026-06-10

### Fixed

- **HYBRID: a failed local-transport attach at startup is now retried** (live-found on production validating beta.2): right after a Home Assistant restart, the WiFi dongle's single TCP slot can still be held by the previous session, so the attach times out — previously that one transient failure parked the device on cloud data **forever** (until a manual reload). Failed attaches are now retried about once a minute and recover automatically; a **Repairs issue** explains the degraded state and clears itself on reconnection.
- **HYBRID: devices running degraded (failed attach) no longer freeze**: while a locally-configured device falls back to cloud data, its cloud API caches — tuned for the slow supplemental role — could pin its sensors at stale values for the whole cache window. Degraded devices now bypass those caches and keep updating at the normal coordinator cadence, a degraded GridBOSS is no longer throttled by the dongle polling interval (it isn't using the dongle), and cloud-fallback failures are logged instead of being silently swallowed.

## [3.4.0-beta.2] - 2026-06-10

### Added

- **Charge Last switch** ([#177](https://github.com/joyfulhouse/eg4_web_monitor/issues/177)): toggle the battery *Charge Last* function (`FUNC_CHARGE_LAST`, register 110 bit 4) from Home Assistant. Off (default, "charge first"): PV charges the battery before exporting surplus. On: PV serves house loads and grid export first and charges the battery last — automate it to reserve battery headroom during peak production (e.g. charge to ~90% in the morning, enable Charge Last through midday, disable in the afternoon to top off). Works in cloud, local, and hybrid modes; hybrid prefers the local Modbus write and falls back to the cloud function-control API.
- **Confirmed EG4_OFFGRID registers** ([#197](https://github.com/joyfulhouse/eg4_web_monitor/issues/197)): surfaced three register groups live-validated on 12000XP hardware (Modbus sweep + cloud cross-reference). All new entities are created for the EG4_OFFGRID family only (12000XP/6000XP).
  - **Per-phase EPS load power** — new `EPS Load Power L1` / `EPS Load Power L2` sensors (input regs 129/130, W) plus a combined `EPS Load Power` (L1+L2 sum, matches the cloud `epsLoadPower` field within polling skew). Useful for diagnosing breaker-panel load imbalance.
  - **Load Power** (input reg 170, `Pload`) — enabled for EG4_OFFGRID. The cloud zeroes its reg-170 mirror for these models, so the value is taken from the local register in LOCAL and HYBRID modes (never the cloud zero); valid both grid-tied and in EPS mode.
  - **Battery Discharge Power** (input reg 11 / cloud `pDisCharge`) — reintroduced as a per-inverter sensor in all connection modes for EG4_OFFGRID. The signed net `Battery Power` sensor is unchanged; the one-time registry cleanup from the charge/discharge consolidation no longer removes this key.

### Fixed

- **Smart Port Status ValueError when all four ports are Unused** ([#248](https://github.com/joyfulhouse/eg4_web_monitor/issues/248), regression of [#195](https://github.com/joyfulhouse/eg4_web_monitor/issues/195)): re-lands the PR [#198](https://github.com/joyfulhouse/eg4_web_monitor/pull/198) fix that was lost in a history rewrite — on GridBOSS units with **all four smart ports Unused**, the all-zeros status read was treated as corrupt, leaking raw integer `0` to HA's enum validation (`ValueError: state value '0' not in options`) on every refresh and leaving the four Smart Port Status sensors permanently unavailable. All-zeros is again recognized as a valid state, and on corrupt no-cache reads status values are normalized to valid labels (out-of-range → `unused`) so raw integers can never reach HA. The lost regression tests are re-landed alongside.
- **Family-UNKNOWN devices regain their real sensor profile** ([#219](https://github.com/joyfulhouse/eg4_web_monitor/issues/219)): when firmware reports an unmapped device type code (e.g. 6000XP on `ccaa-140A0A`), the integration now derives the family profile from the model name, restoring split-phase sensors (`eps_power_l1/l2`) in all connection modes. The user-selected **Grid Type** override now also survives every LOCAL poll (previously only the first static refresh). The diagnostic `inverter_family` sensor reports the effective family, with `family_source`/`detected_inverter_family` breadcrumbs preserved in coordinator data.
- **Behavior change for legacy UNKNOWN-family LOCAL entries**: the static path no longer creates the full create-all sensor set for them — phase sensors the hardware never had (dead three-phase R/S/T entities on split-phase models) are no longer provided. A **Repairs issue** is raised on each affected device explaining the pruning; if your device truly is three-phase, set **Grid Type** in the integration options.
- **Modbus serial (USB/RS485) devices in HYBRID mode** ([#233](https://github.com/joyfulhouse/eg4_web_monitor/issues/233)): devices sharing one RS485 serial bus are now refreshed **sequentially** — concurrent reads on a shared bus corrupted responses. Serial-attached devices reachable only via the station (e.g. a GridBOSS the inverter cache never holds) are now disconnected on unload/reload, closing a leaked-open-serial-port bug. Malformed local-device configs (serial/port type drift) no longer crash setup, and a **Repairs issue** is raised when a serial port cannot be opened (the device temporarily falls back to cloud data).
- **Battery bank Full/Remaining Capacity double-counted in cloud mode** (via pylxpweb 0.9.36b2): on banks whose master battery mirrors pack-level totals into its own module fields, the cloud's module-array sums over-reported the bank (e.g. 1400 Ah "full" on an 840 Ah bank). The bank sensors now use the BMS-reported bank pair, matching the local register path exactly; open-loop (lead-acid / no BMS comms) systems keep the legacy fields.

### Changed

- Minimum `pylxpweb` raised to **0.9.36b2**: WiFi dongle parameter writes now survive mid-sequence TCP connection drops without write wars ([#201](https://github.com/joyfulhouse/eg4_web_monitor/issues/201)) — the full read-modify-write sequence retries with a fresh register read, never resending stale values; write ACKs are echo-validated against misrouted dongle responses; all multi-request reads are serialized on the dongle's single TCP link; and the cloud battery-bank capacity fix above.

### Documentation

- **Example dashboards re-audited against current entity IDs** ([#209](https://github.com/joyfulhouse/eg4_web_monitor/issues/209)): refreshed `examples/dashboards/` (`battery_details.yaml`, `energy_overview.yaml`, `eg4_solar_monitor.yaml`) toward the entity IDs the integration generates today. This re-applies the v3.2.0 renames from #212 (which were lost when `main` was superseded by the 3.3.0 release branch) and catches 3.3.0/3.4.0 drift: dropped the phantom `eg4_` entity-ID prefix (sensors are `sensor.<model>_<serial>_*`), `battery_soc` → `state_of_charge`, `pv_power` → `pv_total_power`, `daily_*` → `yield`/`consumption`/`grid_import`, inverter `load_power` → `consumption_power`, per-battery `state_of_charge` → `relative_soc` and `cell_voltage_max/min` → `max/min_cell_voltage`, per-battery sensors on the `<model>_battery_<serial>_<nn>` device (`real_power`, `state_of_health`, `cell_temperature_delta`, `max/min_voltage_cell_number`), `eg4_gridboss_*` → `grid_boss_*`, switches `battery_backup` → `eps_battery_backup` and `peak_shaving_mode` → `grid_peak_shaving_mode`, and `battery_high/low_soc_limit` → `system_charge_soc_limit`/`on_grid_soc_cut_off`. Rows for controls that never shipped were replaced honestly: `grid_charge` → **AC Charge** (`ac_charge_mode`); `feed_in_grid` ("Grid Export") has no real counterpart — the row is now plain **Forced Discharge** (a true export toggle would need `FUNC_FEED_IN_GRID_EN`, reg 21 bit 15, not yet exposed); `battery_equalization` likewise — use **System Charge SOC Limit** (accepts 101 for top-balancing), with the v3.4.0 **Battery Charge/Discharge Control** selects shown as regime pickers only. Note: Home Assistant preserves existing registry entries, so long-standing installs may retain older object IDs — verify exact IDs under Settings → Devices & Services → Entities.
- **Battery control mode — EG4 UI label cross-reference**: documented the mapping from EG4 web-monitor parameter labels to Home Assistant entities for the SOC/Voltage battery limits — e.g. EG4's *"Back Up Volt(V)"* is the **AC Charge End Voltage** entity (reg 159, the voltage twin of the AC-charge SOC limit, active in battery-backup/voltage mode) and *"System Charge Volt Limit(V)"* is reg 228. Added a label table to [CONFIGURATION.md](docs/CONFIGURATION.md#battery-control-mode-soc-vs-voltage), the canonical register/param table plus confirmed register-179 bits 9/10 to [DATA_MAPPING.md](docs/DATA_MAPPING.md), and a discovery pointer in the README.

## [3.4.0-beta.1] - 2026-06-08

### Added

- **Battery control mode — SOC vs Voltage** ([#48](https://github.com/joyfulhouse/eg4_web_monitor/issues/48)): choose whether the inverter governs battery charge/discharge limits by **State-of-Charge (closed-loop / BMS lithium)** or **Voltage (open-loop / lead-acid / no BMS comms)**, mirroring the inverter's own register-179 regime bits (bit 9 charge, bit 10 discharge). Works in cloud, local, and hybrid modes.
  - Two new **select** entities per inverter — **Battery Charge Control** and **Battery Discharge Control** (`SOC` / `Voltage`) — read and write the live regime and are fully automatable.
  - Five new **voltage-limit number** entities (the open-loop counterparts of the existing SOC limits): **System Charge Voltage Limit** (reg 228), **On-Grid Cut-Off Voltage** (reg 169), **Off-Grid Cut-Off Voltage** (reg 100), **AC Charge Start Voltage** (reg 158), **AC Charge End Voltage** (reg 159).
  - **Configure → Battery Charge/Discharge Control Mode** options: pre-filled from the inverter's live regime; changing them reconfigures the inverter and gates which limit entities are enabled by default to reduce clutter.
- **Entity decluttering by regime**: limit controls for the non-selected regime are created but **disabled by default** (SOC is the default, preserving existing behavior). The active controls expose an `is_effective` attribute and log a non-blocking warning if you set a limit that the current regime ignores.

### Fixed

- **Voltage limits read 10× low in cloud/hybrid mode**: the cloud API returns battery voltages already scaled (e.g. `59.5 V`) while local Modbus returns raw decivolts (`595`); a blind ÷10 produced `5.95 V`. Reads are now magnitude-normalized so both transports agree. (Pre-existing latent issue surfaced while adding the voltage entities.)
- **On-Grid Cut-Off Voltage showed "unknown" in cloud**: the cloud exposes register 169 as `HOLD_ON_GRID_EOD_VOLTAGE`; the mapping used a non-canonical spelling. Confirmed against a live cloud register read.

### Changed

- Minimum `pylxpweb` raised to **0.9.36b1** (dual cloud/transport battery-control methods, `BatteryControlMode`, register 228 definition, and the register-169 cloud name fix).

### Notes

- In a **parallel group**, the inverter firmware syncs the battery control regime across all inverters; setting it on one propagates to the group. The integration writes all inverters and refreshes them together so the per-inverter entities stay consistent.

## [3.3.0] - 2026-06-05

Stable release consolidating the `3.3.0-beta.1`–`3.3.0-beta.8` cycle. Detailed beta notes are retained below.

### Added

- **Per-inverter Load Energy sensors** (`Eload` regs 171/172) — the inverter-served load, a separate meter from whole-home Consumption (see beta.6).
- **BMS permission/request sensors** ([#232](https://github.com/joyfulhouse/eg4_web_monitor/issues/232)) — BMS charge/discharge/force-charge state in all modes (see beta.1).
- **Power factor, GridBOSS smart-load current, granular energy** ([#243](https://github.com/joyfulhouse/eg4_web_monitor/issues/243)).

### Fixed

- **PV Charge Power did not stick on Modbus/hybrid inverters** ("set 1 kW → reads 0" bounce): the local path wrote register 64 (a 0-100% limit) with a lossy `kW↔%` conversion. It now targets register **74** (`HOLD_FORCED_CHG_POWER_CMD`, 100W units) in kW like AC charge power; the cloud path was already correct. Hardware-verified: FlexBOSS reg74=20→2.0 kW, 18kPV reg74=120→12.0 kW.
- **Daily consumption never reset in LOCAL mode** ([#227](https://github.com/joyfulhouse/eg4_web_monitor/issues/227)) and **`total_increasing` dip warnings** ([#218](https://github.com/joyfulhouse/eg4_web_monitor/issues/218)) (see beta.5).
- **EPS/grid aggregate voltage, PV input current, hybrid L1/L2** ([#243](https://github.com/joyfulhouse/eg4_web_monitor/issues/243)).

### Changed

- Minimum `pylxpweb` raised to **0.9.35** (adds register 74 to the local register map).

## [3.3.0-beta.6] - 2026-06-02

### Added

- **Per-inverter Load Energy sensors** (`Load Energy` / `Load Energy (Lifetime)`): the inverter-served load read straight from the `Eload` registers (171/172), matching the EG4 cloud's per-inverter `todayUsage`/`totalUsage` exactly in every mode (validated to the decimal on live hardware). This is a **separate meter** from whole-home **Consumption**: in a parallel group a master inverter can read `0` Load Energy while the home still draws power — grid-direct loads bypass the inverter — and the per-inverter Eload sum sits far below whole-home consumption (the cloud reports them as two distinct numbers, on two different screens). Non-breaking: existing `consumption`/`consumption_lifetime` entities are unchanged and `consumption` remains the whole-home figure (energy balance / GridBOSS CT overlay / cloud group). No new dependency. See [DATA_MAPPING.md → "Consumption vs Load Energy"](docs/DATA_MAPPING.md).

## [3.3.0-beta.5] - 2026-06-02

### Fixed

- **Daily consumption never reset to zero in LOCAL mode** ([#227](https://github.com/joyfulhouse/eg4_web_monitor/issues/227)): In local/dongle/Modbus modes the computed `consumption`/`consumption_lifetime` sensors were pinned at their daily peak by an unbounded monotonic clamp in the coordinator — they only rose when surpassing the previous peak and never reset at midnight. Cloud and hybrid were unaffected. Removed the clamp and rely on Home Assistant's `total_increasing` state class, which detects meter resets natively.
- **`total_increasing` sensors triggering recorder warning on small dips** ([#218](https://github.com/joyfulhouse/eg4_web_monitor/issues/218)): Energy-balance rounding noise caused `consumption` and `consumption_lifetime` to step down by 0.1 kWh between polls (e.g. 2917.1 → 2917.0), tripping HA's "state is not strictly increasing" warning. Added a sensor-level guard that pins downward dips ≤10% to the previous high-water mark — matching HA recorder's reset-detection threshold so daily resets, lifetime counter wraps, and inverter replacements (drops >10%) still pass through unchanged. Paired with the #227 fix, midnight resets pass through while rounding jitter is suppressed.

## [3.3.0-beta.1] - 2026-05-31

### Added

- **BMS permission/request sensors** ([#232](https://github.com/joyfulhouse/eg4_web_monitor/issues/232)): three battery-bank diagnostic sensors surfacing the BMS's charge/discharge/force-charge state, available in cloud, local, and hybrid modes:
  - **BMS Charge Allowed** and **BMS Discharge Allowed** (Allowed / Blocked) — cleared when the bank is full / empty respectively
  - **BMS Force Charge Request** (Requested / Idle) — the BMS requesting a full calibration charge; read-only, distinct from the writable Forced Charge control

  Decoded from input register 95 (bitmap `0x01`/`0x02`/`0x20`) in local/hybrid and from the cloud `bmsCharge`/`bmsDischarge`/`bmsForceCharge` fields — the local decode was validated against the cloud values on live hardware. Requires `pylxpweb>=0.9.32`.

## [3.2.0] - 2026-03-09

The biggest release in the integration's history: 279 commits, 43 beta/RC releases, and contributions from the community. Local polling is no longer experimental — it's production-ready across all four connection modes with full entity parity validated in Docker.

### Changed

- **WiFi dongle minimum polling interval** ([#185](https://github.com/joyfulhouse/eg4_web_monitor/issues/185)): Lowered from 15s to 5s, allowing users who need faster reaction times to opt in via the options flow. Default remains 30s.

### Breaking Changes

- **Config Flow Architecture**: Replaced the 23-file, 12-mixin config flow with a single unified `EG4ConfigFlow` class using menu-based navigation. Existing config entries migrate automatically.
- **Inverter Family Constants Renamed**: `INVERTER_FAMILY_SNA` → `EG4_OFFGRID`, `PV_SERIES` → `EG4_HYBRID`, `LXP_EU`/`LXP_LV` → `LXP`. Old names emit `DeprecationWarning` but continue to work.
- **Config Entry Version**: Bumped from v1 to v2. Legacy modbus/dongle entries auto-migrate on startup via `async_migrate_entry()`.

### Added

#### New Sensors
- **Split-phase per-leg power sensors** ([#178](https://github.com/joyfulhouse/eg4_web_monitor/issues/178)): Separate L1/L2 sensors for EPS and grid power on split-phase inverters
- **BMS bank-level diagnostic sensors**: Min cell voltage/temperature, BMS charge/discharge current limits, charge voltage reference, discharge cutoff, battery type, voltage inverter sample — always available from BMS registers, no CAN bus needed
- **Battery bank cycle count**: From BMS register 106 (always available)
- **Battery bank current**: Mapped from `battery_data.current` in both LOCAL and HTTP paths
- **Battery last seen** ([#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): Per-battery diagnostic timestamp showing last physical read — useful for >4 battery round-robin systems
- **Common voltage aliases** ([#159](https://github.com/joyfulhouse/eg4_web_monitor/issues/159)): `grid_voltage` and `eps_voltage` for single/split-phase inverters
- **Signed net sensors**: Consolidated charge/discharge pairs into single signed sensors
- **Charge rate sensors**: New sensors for monitoring charge rates
- **Parallel battery current**: Aggregates battery current across parallel group members
- **Hybrid transport-exclusive sensors** ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149)): `bt_temperature`, `grid_current_l1/l2/l3`, `battery_current`, `total_load_power` overlaid from local transport in hybrid mode
- **PV Start Voltage number** and **PV Input Mode select** entities
- **Connection transport** and **transport IP** diagnostic sensors
- **API monitoring sensors**: Peak rate, hourly, and daily cloud API request counters

#### New Controls
- **GridBOSS smart port mode select entities**: Configure each smart port (1–4) between Off, Smart Load, and AC Couple modes via holding register 20 bit fields
- **Battery Backup and Grid Peak Shaving switches** in LOCAL mode ([#153](https://github.com/joyfulhouse/eg4_web_monitor/issues/153))

#### Config Flow
- **Menu-based setup**: Cloud (HTTP) or Local Device entry points with auto-derived connection type
- **Unified reconfigure flow**: Update credentials, add/remove local devices, or detach cloud
- **Auto-detection for local devices**: Serial number, model, family, firmware, and parallel group configuration detected automatically
- **Network scan**: Auto-discover Modbus/dongle devices on local network
- **Serial transport**: Modbus RTU via USB-to-RS485 adapter support
- **Automatic config migration**: `async_migrate_entry()` migrates v1 entries on startup ([#83](https://github.com/joyfulhouse/eg4_web_monitor/issues/83))
- **LXP-LB-BR 10kW support**: Brazil model device type for local discovery

#### Data Integrity
- **WiFi dongle cross-request validation** ([#158](https://github.com/joyfulhouse/eg4_web_monitor/issues/158)): Response serial, function code, and register validated against request — catches misrouted cloud responses causing garbage readings
- **Data validation toggle**: Options flow setting to enable/disable canary checks on Modbus reads
- **Energy monotonicity validation**: Lifetime energy counters validated to never decrease
- **Battery canary checks**: Reject readings with `battery_count > 20` or `abs(current) > 500A`

#### Architecture
- **Shared battery bank mirroring** ([#169](https://github.com/joyfulhouse/eg4_web_monitor/issues/169)): In parallel systems with shared batteries, LOCAL path mirrors primary's battery_bank_* values to secondary inverters
- **Static entity creation**: First LOCAL refresh produces zero Modbus reads — entities created from config metadata, real data fills in on second refresh
- **Round-robin battery cache** ([#165](https://github.com/joyfulhouse/eg4_web_monitor/issues/165)): Serial-based battery tracking across round-robin rotation for >4 battery systems
- **Per-transport refresh intervals**: Independent poll intervals for Modbus TCP, WiFi dongle, and serial, configurable via options flow
- **Complete i18n**: 12 language translations (Chinese Simplified, Chinese Traditional, Dutch, French, German, Italian, Japanese, Korean, Polish, Portuguese, Russian, Spanish)

#### Testing & Quality
- **779 tests** (up from ~350 in v3.1.8): Comprehensive suites for all entity types, coordinator paths, config flow, reconfigure flow, and tier validation
- **DATA_MAPPING.md**: Canonical reference for all register-to-sensor and API-to-sensor mappings
- **CI**: Automated issue triage with Claude, translation validation, quality tier scripts

### Fixed

- **HYBRID mode setup hang on HA restart** ([#180](https://github.com/joyfulhouse/eg4_web_monitor/issues/180)): Removed forced Modbus read from transport attachment — Waveshare RS485 gateway stale buffers caused 3–5 minute blocks on `async_config_entry_first_refresh()`
- **HYBRID late sensor registration**: Transport-only sensor keys missing from first update are now discovered and registered via coordinator listener
- **Individual battery entities permanently unavailable** ([#180](https://github.com/joyfulhouse/eg4_web_monitor/issues/180)): pylxpweb no longer permanently disables battery reads after transient WiFi dongle failures; coordinator falls back to round-robin cache
- **Smart port status register** ([#142](https://github.com/joyfulhouse/eg4_web_monitor/issues/142), [#139](https://github.com/joyfulhouse/eg4_web_monitor/issues/139)): Now reads from correct holding register 20 (bit-packed) instead of input registers 105-108
- **Smart port wrong-type sensors**: Removed instead of set to `None`, preventing "Unknown" entities
- **Smart port status display**: Uses `device_class: enum` with translated labels
- **Smart load energy register addresses** ([#146](https://github.com/joyfulhouse/eg4_web_monitor/issues/146)): Corrected off-by-one in daily and lifetime energy registers
- **Parallel group consumption** ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149)): Energy-balance formula using MID device grid power overlay; fixes 0W consumption and energy divergence between LOCAL/CLOUD
- **Parallel group grid voltage**: Overlaid from MID device CT reading; fixes 0V on inverters where firmware doesn't populate regs 193-194
- **Per-transport interval gate bug**: `_should_poll_transport()` now stamps per-type instead of per-device, fixing multi-device LOCAL setups where only first device was polled
- **Double MID device refresh** ([#148](https://github.com/joyfulhouse/eg4_web_monitor/issues/148)): Eliminated redundant refresh that doubled dongle reads per cycle (14→7)
- **Three-phase entity registration order** ([#154](https://github.com/joyfulhouse/eg4_web_monitor/issues/154)): Parallel group devices registered before referencing entities, preventing `via_device` warnings on HA 2025.12.0+
- **GridBOSS firmware shows "unknown"** ([#156](https://github.com/joyfulhouse/eg4_web_monitor/issues/156)): Read from transport + firmware cache instead of always-None property
- **Battery bank diagnostic sensors permanently Unavailable**: Split into CORE (BMS, always available) and CAN (intermittent) key sets
- **Battery bank min_soh**: Falls back to bank-level SOH from input register 5 high byte
- **Secondary inverter battery bank suppression** ([#169](https://github.com/joyfulhouse/eg4_web_monitor/issues/169)): Deferred to runtime to avoid false positives on LXP-EU dual-battery systems
- **Cloud API fallback for HYBRID switch writes**: Falls back to HTTP when local transport write fails
- **LOCAL mode cache TTL adherence**: Removed `force=True` that bypassed pylxpweb cache TTLs
- **Transport disconnect on shutdown**: Prevents unload timeout from dangling connections
- **Truncated battery serial handling** ([#165](https://github.com/joyfulhouse/eg4_web_monitor/issues/165)): Skip in round-robin cache instead of crashing
- **FlexBOSS model detection** ([#152](https://github.com/joyfulhouse/eg4_web_monitor/issues/152)): Corrected during local discovery
- **Network scan dongle prefill crash** ([#172](https://github.com/joyfulhouse/eg4_web_monitor/issues/172)): Handle partial user_input during discovery

### Changed

- **Major coordinator restructuring**: Split monolithic `coordinator.py` (~3000 lines) into focused modules: `coordinator_http.py`, `coordinator_local.py`, `coordinator_mappings.py`, `coordinator_mixins.py`
- **Number entity deduplication**: Consolidated 9 classes into shared `_read_param`/`_write_param` helpers (-500 lines)
- **Hybrid mode simplification**: Replaced ~430-line manual merge pipeline with pylxpweb library transport routing
- **Config flow**: Simplified from 23 files to 5 files
- **last_polled sensors disabled by default**: Reduces database noise
- **GridBOSS CT overlay**: Shared between HTTP and LOCAL paths for consistent energy data
- **HYBRID coordinator interval**: Uses fastest configured transport interval

### Removed

- Legacy config flow (23 files, ~1969 lines)
- `CircuitBreaker` class, `utils.py` helpers, dead constant modules
- Cloud refresh interval option (replaced by library-level cache TTLs)
- Grid type mismatch detection (config is authoritative)
- 5 obsolete test files

### Dependencies

- Requires `pylxpweb>=0.9.26`
- Requires `pymodbus>=3.6.0`
- Requires `pyserial>=3.5`

## [3.1.1] - 2026-01-11

### Added

- **Parallel Group Aggregate Battery Sensors**: New sensors for parallel groups that aggregate battery data across all inverters:
  - Battery Charge Power (W)
  - Battery Discharge Power (W)
  - Battery Power (net W)
  - Battery State of Charge (weighted average %)
  - Battery Max Capacity (Ah)
  - Battery Current Capacity (Ah)
  - Battery Voltage (average V)
  - Battery Count (total modules)

  > **Note**: SOC is calculated as a capacity-weighted average: `(total_current_capacity / total_max_capacity) * 100`. This is more accurate than a simple average when batteries have different capacities.

### Dependencies

- Requires `pylxpweb>=0.5.7` (adds aggregate battery properties to ParallelGroup)

## [3.1.0] - 2026-01-11

### Added

- **Local Modbus/RS485 Connection (Experimental)**: Three connection modes leveraging pylxpweb 0.5.0 transport abstraction:
  - **HTTP (Cloud-only)**: Original behavior using EG4 cloud API (30s polling)
  - **Modbus (Local-only)**: Direct Modbus TCP connection to dongle (5s polling)
  - **Hybrid (Local + Cloud)**: Modbus for fast runtime data + HTTP for cloud-only features

  > **Note**: Local RS485/Modbus connection is experimental and has open issues reported by users. Use with caution and report any issues on GitHub.

- **GridBOSS Smart Load and AC Couple Power Sensors** (#78): New power sensors for GridBOSS devices with Smart Port functionality
- **Reconfigure Flow for Modbus/Hybrid**: Support for changing connection type after initial setup

### Fixed

- **Quick Charge Switch Bounce**: Fixed issue where Quick Charge switch would briefly show OFF after turning ON, then bounce back to ON after coordinator refresh. The optimistic state is now properly maintained until the coordinator refresh completes.
- **Battery Bank Entity Registration** (#81): Fixed device registry error by registering battery bank devices before individual batteries
- **Battery Bank Aggregate Stats** (#76): Battery Bank entity now created with aggregate stats even when `totalNumber=0` in API response
- **Battery Discovery for Short-Format Keys** (#76): Fixed battery discovery when API returns short-format `batteryKey` values
- **Missing batteryArray Handling** (#76): Gracefully handle API responses missing the `batteryArray` field
- **Reconfigure Flow Abort Message**: Added missing `brand_name` placeholder to `reconfigure_successful` abort message

### Changed

- **Modbus Transport Serialization**: Serialize transport reads and add diagnostic logging for debugging connection issues
- **GridBOSS Energy Sensors**: Refactored to use aggregate L1+L2 combined sensors instead of separate per-phase sensors
- **Smart Port Sensor Filtering**: Sensors now filtered based on Smart Port mode (AC Couple vs Smart Load)

### Dependencies

- Requires `pylxpweb>=0.5.6`
- Requires `pymodbus>=3.6.0` (for local Modbus connection)

## [3.0.0] - 2026-01-07

### Breaking Changes

- **Entity ID Changes**: Entity naming convention updated for consistency. Existing automations, scripts, and dashboards may need to be updated.
  - Sensor keys are now more explicit (e.g., `power` → `ac_power`, `soc` → `state_of_charge`)
  - Battery sensors use `battery_{battery_key}` format consistently
  - GridBOSS sensors use `eg4_gridboss_{serial}` prefix
- **Sensor Availability**: Some sensors that were previously always available may now show as "unavailable" if the device doesn't support them (feature detection)

### Added

- **Multi-Brand Support Architecture**: Support for EG4 Electronics, LuxpowerTek, and Fortress Power
- **Binary Sensor: Dongle Connectivity**: Shows whether the inverter's communication dongle is online
- **Switch: Off Grid Mode**: Control Off-Grid/Green Mode on inverters
- **Battery Status Sensor**: Restored battery status sensor lost in refactoring
- **EPS Power Sensors**: EPS Power L1, L2 for 12000XP and compatible devices
- **Inverter Feature Detection**: Only creates sensors that the device actually supports
- **Optimistic Value Context**: Immediate UI feedback for number entity changes

### Fixed

- Quick Charge Switch always showing OFF (#66)
- Working Mode Switches not refreshing parameters after actions (#67)
- Battery Backup Switch conflicts with reauth flow (#50, #55)
- Number Entity value bouncing after parameter changes (#46)
- Reauthentication Flow session expiration handling (#70)
- GridBOSS Auto-Detection when parallel group data not pre-configured (#72)
- 12000XP full sensor support (#49, #63)
- mypy strict typing compliance

### Architecture

- **Base Entity Classes**: `EG4DeviceEntity`, `EG4BatteryEntity`, `EG4BaseSensor`, `EG4BaseSwitch`
- **Coordinator Mixins**: Modular coordinator with focused mixins
- **Platinum Quality Scale**: Meeting all 36 Home Assistant quality scale requirements

### Dependencies

- Requires `pylxpweb>=0.4.4`

[Unreleased]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.5.0-beta.3...HEAD
[3.5.0-beta.3]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.5.0-beta.2...v3.5.0-beta.3
[3.5.0-beta.2]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.5.0-beta.1...v3.5.0-beta.2
[3.5.0-beta.1]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.4.0...v3.5.0-beta.1
[3.4.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0...v3.4.0
[3.3.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0
[3.3.0-beta.6]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.5...v3.3.0-beta.6
[3.3.0-beta.5]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.1...v3.3.0-beta.5
[3.3.0-beta.1]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0-beta.1
[3.2.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.1.8...v3.2.0
[3.1.1]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.1
[3.1.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.0
[3.0.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0
