---
canonical-for:
  - "October 22 2026 upstream transport maintenance audit and issue acceptance snapshot"
sources:
  - https://github.com/joyfulhouse/pylxpweb/issues/189
  - https://github.com/joyfulhouse/pylxpweb/issues/344
  - https://github.com/joyfulhouse/pylxpweb/issues/345
  - https://github.com/joyfulhouse/pylxpweb/issues/350
  - https://github.com/joyfulhouse/pylxpweb/issues/363
  - https://pypi.org/pypi/aioresponses/0.7.9/json
  - https://pypi.org/pypi/tmodbus/0.6.2/json
  - https://pypi.org/pypi/modbus-connection/4.12.5/json
  - https://pypi.org/pypi/modbus-connection/4.12.6/json
  - https://github.com/home-assistant-libs/modbus-connection/commit/2d29ba2500f4edd8b7f89ee5d396a2b5ed7d6f25
verified-against:
  pylxpweb: cc503f8f6ac1e0535c26945e7f0062d4cdfaf15b
last-verified: 2026-10-22
see-also:
  - ../20-pylxpweb/transports.md
---

# Transport maintenance audit, 2026-10-22

This is a dated external-source and acceptance snapshot, not a current-release
index. Stable backend and ownership behavior belongs to
[transports](../20-pylxpweb/transports.md#backend-and-ownership-contract-at-cc503f8).

The upstream audit found no released trigger for removing the aioresponses shim
or the owned-link close-completion workaround. PyPI still reports aioresponses
0.7.9 and tmodbus 0.6.2. The former's response builder omits `stream_writer`;
the latter's released close paths initiate underlying close without awaiting
completion. [aioresponses PR #288](https://github.com/pnuckowski/aioresponses/pull/288)
and [tmodbus #153](https://github.com/wlcrs/tmodbus/issues/153) remain open.
Grade: `asserted-unverified` for this dated external-source snapshot; the
existing reproductions remain linked from library #189 and #345. No new runtime
compatibility result is claimed.

modbus-connection 4.12.6 is newly published since the previous audit. Extracted
PyPI wheels for 4.12.5 and 4.12.6 have byte-identical `_client.py`, `_pacing.py`
and `tmodbus/__init__.py`. The upstream change forwards mock-unit timing
requirements ([commit 2d29ba2](https://github.com/home-assistant-libs/modbus-connection/commit/2d29ba2500f4edd8b7f89ee5d396a2b5ed7d6f25)).
Grade: `asserted-unverified` for the dated wheel comparison, not a claim that
4.12.6 passed this project's runtime suite. Keep #344 open for a future tmodbus
0.7 compatibility check, #345 for a released completion contract, #350 for host
coordination across independent connections, and #363 for a shared consumer.

