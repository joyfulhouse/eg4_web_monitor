---
canonical-for:
  - "The four moving parts of the EG4 system and the boundaries between them"
  - "The two-repo relationship (integration + pylxpweb)"
  - "Device hierarchy vocabulary at system level"
  - "The 'cloud is not a separate data source' principle"
sources:
  - custom_components/eg4_web_monitor/manifest.json
  - custom_components/eg4_web_monitor/const/brand.py
  - pylxpweb src/pylxpweb/client.py
  - memory/feedback_eg4-data-model-and-sensor-noise.md
  - memory/issue-544-generator-power-offgrid.md
  - memory/maintainability-findings-and-live-bugs.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - repo-map.md
  - glossary.md
---

# What this project is

A Home Assistant custom integration for EG4 / Luxpower solar inverters. It is one part
of a four-part system; most non-obvious behaviour comes from the boundaries between
the parts, not from any one of them.

> pylxpweb citations on this page are against the local checkout of
> `joyfulhouse/pylxpweb` as of 2026-08-08, not a released tag. The version this repo
> requires is in `manifest.json` → `requirements`.

## The four parts

| Part | What it is | Where | Owned by |
|---|---|---|---|
| **The integration** | HA custom component, domain `eg4_web_monitor`. Coordinators, entities, config flow, services. | this repo, `custom_components/eg4_web_monitor/` | `10-integration/` |
| **pylxpweb** | Standalone Python library: portal HTTP client, Modbus/dongle transports, register decode, data models, write paths. Separate repo, published to PyPI, pinned in `manifest.json` → `requirements`. | `github.com/joyfulhouse/pylxpweb`; local checkout `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb` | `20-pylxpweb/` |
| **The EG4 portal** | Vendor cloud at `https://monitor.eg4electronics.com`. HTTP JSON API under `/WManage/…`. Also the mobile app's backend. | remote | `30-portal-api/` |
| **The hardware** | Inverters, GridBOSS (MID), battery packs, and the WiFi dongle or RS485 gateway that carries Modbus. | physical | `40-hardware/` |

| Claim | Detail | Grade |
|---|---|---|
| Domain is `eg4_web_monitor`, `integration_type: device`, `iot_class: local_polling`, `quality_scale: platinum` | `manifest.json` | `verified-against-code` |
| Runtime deps are `pylxpweb`, `pymodbus`, `pyserial` | `manifest.json` → `requirements` (exact pins live there, not here) | `verified-against-code` |
| Portal base URL `https://monitor.eg4electronics.com` | `const/brand.py` → `default_base_url`; also `diagnostics.py` | `verified-against-code` |
| Auth is `POST /WManage/api/login` | pylxpweb `client.py` → `_request("POST", "/WManage/api/login", …)` | `verified-against-code` |
| pylxpweb re-authenticates after a **locally assumed** 2-hour threshold | `client.py` → `self._session_expires = datetime.now() + timedelta(hours=2)`. This is a client-side refresh threshold, **not a server TTL** — the portal communicates no expiry, and real expiry is detected by other means. Session semantics are owned by [`30-portal-api/auth-and-session.md`](../30-portal-api/auth-and-session.md). | `verified-against-code` for the client threshold only |

## How a value reaches Home Assistant

Two physical routes, three configured modes.

| Route | Path | Notes |
|---|---|---|
| Local | inverter registers → RS485/Modbus TCP or WiFi dongle → pylxpweb transport → transport dataclasses → coordinator → entity | The integration reads **transport dataclasses**, not pylxpweb's gated convenience properties. A library fix applied only to a property ships nothing for LOCAL/HYBRID. |
| Cloud | inverter registers → dongle → EG4 cloud → portal HTTP JSON → pylxpweb client → device models → coordinator → entity | The portal relays or derives the same register values. |

Modes: `http` (cloud only), `local`, `hybrid` (local + cloud supplement). The constants
are `CONNECTION_TYPE_HTTP` / `CONNECTION_TYPE_LOCAL` / `CONNECTION_TYPE_HYBRID` in
`const/config_keys.py` — `verified-against-code`. Per-mode behaviour is owned by
`10-integration/`.

### The founding principle

**The cloud is not a separate data source.** The EG4 cloud relays the same Modbus
register values the dongle reads, or computes a derivation from them. When a cloud
field looks "missing", trace it to its register before calling it cloud-only; a
`cloud_api_field=None` on a register means the cloud does not carry that field, not
that the data is unavailable. `asserted-unverified`
(`memory/feedback_eg4-data-model-and-sensor-noise.md`).

Consequences that have each cost a debugging session:

| Consequence | Grade |
|---|---|
| A "cloud-only" value may be a derivation computed from registers you already have. PV current is the worked case: registers 72-74 exist as candidates but read 0 or garbage on tested EG4 hardware, so the integration derives current from P/V. Register-level detail is owned by [`40-hardware/registers.md`](../40-hardware/registers.md). | `asserted-unverified` (issue #243; `memory/issue-243-eps-aggregate-and-pv-current.md`) |
| A value may exist only over Modbus because the cloud never carries it — fault/warning codes have no cloud field at all | `asserted-unverified` (`memory/architecture-patterns.md`) |
| The same concept can be genuinely different per mode — per-inverter consumption vs whole-home consumption are two non-summing scopes, not one value with a bug. Owned by [`10-integration/data-semantics.md`](../10-integration/data-semantics.md). | `asserted-unverified` (`memory/consumption-energy-sources.md`) |

## Device hierarchy

```
Plant / Station  (plantId)
└── Parallel group        (0..n)
    ├── MID device / GridBOSS   (0..1)
    └── Inverter               (1..n)
        └── Battery            (0..n, addressed by batteryKey)
```

The integration creates one config entry per station. Terms are defined in
[glossary.md](glossary.md). `asserted-unverified` (`CLAUDE.md` "Device Hierarchy"; the
shapes are corroborated by the entity unique-ID forms owned by
[`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md)).

## The two-repo relationship

| Fact | Detail | Grade |
|---|---|---|
| Register decode, scaling, and transport live in **pylxpweb**, not here | The integration consumes decoded dataclasses and named-parameter reads/writes | `asserted-unverified` (`docs/claude/MAINTAINABILITY_FINDINGS.md`; corroborated by `manifest.json` requirements) |
| A register/scale fix therefore usually starts in pylxpweb, and the integration then bumps its pin | The cross-repo change ordering, its traps, and the pre-release pin rule are owned by [`50-operations/release-process.md`](../50-operations/release-process.md) | `asserted-unverified` (`memory/feedback_release-strategy.md`) |
| The seam between the two repos is maintained by convention, not enforced by types | Historically the integration duck-typed the library and read/wrote private attributes; `mypy --strict` could not see across the seam because consuming functions were typed `Any` | `asserted-unverified` (`docs/claude/MAINTAINABILITY_FINDINGS.md`) |

**Working rule:** when you fix anything that crosses the seam, check which side the
data actually flows through. The integration reads transport dataclasses directly, so
a library change made only on a cloud property, or only on a convenience accessor,
will silently not ship for LOCAL/HYBRID. This is the shape of issue #544
(`60-history/bug-postmortems.md`).
