# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Requires [pylxpweb 0.9.36b14](https://github.com/joyfulhouse/pylxpweb/releases/tag/v0.9.36b14)
> (installed automatically; the manifest requirement is bumped).

### Fixed

- **All batteries now reported on systems with more than 4 batteries** ([#258](https://github.com/joyfulhouse/eg4_web_monitor/issues/258), [#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): inverters expose individual battery data through 4 fixed Modbus register slots and rotate systems with more than 4 batteries through those slots over time. The integration relied on the inverter's reported battery count (Modbus register 96), which is unreliable on parallel systems — it reports 12 for a 6-battery bank and intermittently 4 for a 5-battery bank — so the extra battery was repeatedly dropped (it would appear briefly after a restart, then vanish). Battery data now accumulates by battery serial number and ignores register 96 entirely, so every battery appears and stays once it has been seen (a battery rotated out of view keeps its last reading until it cycles back). Fixed in pylxpweb 0.9.36b14; the manifest now requires it.

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

- **`Export PV Only` now works in LOCAL and HYBRID modes — register 179 bit 3 pinned** ([#135](https://github.com/joyfulhouse/eg4_web_monitor/issues/135)): authorized live cloud functionControl toggles (2026-06-12, ~16:05–16:07 PT), raw-verified via `remoteRead` (179, 1) valueFrame (base64 LE uint16) on BOTH 12K-hybrid models — FlexBOSS21 52842P0581 and 18kPV 4512670118 each toggled the reg-179 raw frame `0x104c` ↔ `0x1044` (XOR `0x0008` = single bit 3) in lockstep with the named parameter, restores verified by re-read. Direct proof on both family models — no extrapolation. With pylxpweb ≥ 0.9.36b6 the switch is now created in local-raw setups (LOCAL mode, HYBRID with an attached transport) and writes go through the transport named-parameter read-modify-write; state reads come from the locally decoded bit. Against released pylxpweb 0.9.36b5 a register-map probe (`_local_params_can_carry`, the generalized successor of the per-mode `requires_cloud_params` flag) keeps the previous cloud-only behavior at BOTH setup time (no lying entity in local-raw setups) and write time (legacy flat-HYBRID toggles go straight to the cloud method instead of attempting a doomed local write — hardened in adversarial review). The register-contract harness moved `FUNC_PV_SELL_TO_GRID_EN` from the cloud-only allowlist into the pinned contract at (179, 3) — exactly the promotion its honesty tripwire was designed to force (that contract row is deliberately RED against pylxpweb < 0.9.36b6 as the release cut-blocker). The off-grid / no-sellback model gating is unchanged.

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

[Unreleased]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0...HEAD
[3.3.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0
[3.3.0-beta.6]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.5...v3.3.0-beta.6
[3.3.0-beta.5]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.1...v3.3.0-beta.5
[3.3.0-beta.1]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0-beta.1
[3.2.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.1.8...v3.2.0
[3.1.1]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.1
[3.1.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.0
[3.0.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0
