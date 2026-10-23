---
canonical-for:
  - "October 23 2026 authorized beta.21 production smoke test and its acceptance limits"
sources:
  - docs/production/beta21-2026-10-23.json
  - custom_components/eg4_web_monitor/diagnostics.py
verified-against: ca2f63580091bc5a771253a7dbc5fa09fdb70f2a
last-verified: 2026-10-23
see-also:
  - ../10-integration/entities-identity-availability.md
  - ../10-integration/diagnostics-repairs.md
  - ../50-operations/release-process.md
---

# Authorized beta.21 production smoke test

This dated observation owns this installation's smoke-test result, not a general
hardware acceptance claim. Sanitized measurements and warning excerpts are in
[the evidence record](../../docs/production/beta21-2026-10-23.json).
Observations are `asserted-unverified` under the wiki's proof vocabulary: this
was not a named-control/raw-register before/after/restore experiment.

## Installation and baseline

The user explicitly authorized installation and a Home Assistant restart after
read-only inspection. Access was authenticated REST/WebSocket and the existing
Terminal & SSH add-on. Operational preconditions were checked before proceeding. No test-initiated inverter writes, forced outages,
clock changes, or generator operation occurred; normal automation was left active.

Production ran HA 2026.10.2 in America/Los_Angeles. The starting integration was
beta.20; the installed release is beta.21. Runtime diagnostics confirmed
pylxpweb 0.10.0b13. HYBRID used Modbus TCP for an 18KPV and FlexBOSS21, both
FAAB-2727, and a Wi-Fi dongle for GridBOSS IAAB-1600. Registry topology comprised
one station, one parallel group, two battery banks, six WP-16/280-1AWLL packs
(2.17), and four smart-port devices. The entry configured three inverter/GridBOSS
transports and no direct battery bridge.

The downloaded HACS ZIP SHA-256 matched the handoff. All 81 files matched the
beta.21 tag byte-for-byte, and the installed files matched that ZIP. A private
rollback archive preserved the old integration and config/entity/device storage
on HA and on the observing machine. An October 22 HA backup also existed.
Neither archive restoration nor rollback was exercised.

## Observed results

| Check | Result |
|---|---|
| Config entry startup | Loaded; diagnostics reported last update successful |
| Registry identity | 934 entity records and 17 device records preserved |
| User configuration | EG4 config entry and options unchanged after installation |
| Settled active state population | Same 651 entity IDs as baseline |
| Availability | Same 612 known, 24 unknown, 15 unavailable; no known state degraded |
| Discovery/config menu | Existing integration's initial user menu opened without error; aborted without submission |
| Options form | Initial form rendered without errors; aborted without submission |
| Service registration | refresh_data, reconcile_history, import_historical_data, fetch_events present; not invoked |
| Native battery min/max values | Representative states retained millivolt values such as 3.313 V; no UI precision conclusion |
| Duplicate quick-charge sensors | Existing beta.20 errors recurred for both inverters; not a newly established beta.21 regression |
| Diagnostics download | Completed, but package metadata lookup triggered blocking listdir/read_text/open warnings |

Fifteen previously unavailable entities were temporarily absent during startup,
then returned with the same settled availability. A short smoke test cannot
establish long-duration reconnect behavior or reliable midnight rollover.
At 02:16 UTC the entry remained loaded with unchanged state counts. A dongle
connection warning recurred; connectivity was not established as resolved.

The diagnostics warning points to `async_get_config_entry_diagnostics` calling
`importlib.metadata.version` directly on HA's event loop. The proposed executor
fix is separate from the released production files and is not installed by this
test. No release publication or PR merge is part of the test.

## Acceptance still open

- Natural HA-local midnight rollover, mixed-source/cached provenance, and member
  outage/recovery were not exercised.
- No direct battery bridge was configured, so direct-cell display precision,
  user precision overrides, and master-field behavior were not tested.
- No SOC rejection was provoked, no model control semantics were tested, and no
  generator was started. Code-20/code-2102 recognition was not represented here.
- Consumption discrepancy #659 and generator semantics #658 remain unresolved.
- The initial forms were checked, not all branches or a submitted reconfiguration.
- Rollback readiness is backed by preserved files, not a completed restore drill.
- The existing unknown/unavailable entities and duplicate quick-charge IDs need
  separate diagnosis. Keep issue acceptance distinct from this release smoke test.
