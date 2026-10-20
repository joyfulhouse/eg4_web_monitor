# GridBOSS Unused mode write: issue #629

## Finding and evidence boundary

The reporter reproduced this on integration 3.5.0, Home Assistant 2026.9.2,
and a cloud-connected GridBOSS: selecting Unused, then Smart Load, left the
port's separate Smart Load Enable toggle off. The configured mode and status
both returned to Smart Load while the load consumed no power. Turning the
enable toggle back on in the EG4 portal restored operation.

Source: [issue #629](https://github.com/joyfulhouse/eg4_web_monitor/issues/629).
This is a reporter observation, not a hardware-toggle proof: the issue has
no raw before/after register pair. The exact device-side mechanism, firmware
scope, and local-transport reproduction are not established by this fix.

## Integration root cause

At integration commit `5f42769`, `EG4SmartPortModeSelect.async_select_option`
accepts Unused as mode 0. It routes the write to either:

- `coordinator.write_named_parameter("BIT_MIDBOX_SP_MODE_N", 0)` locally;
- `client.api.control.set_smart_port_mode(serial, port, 0)` over the cloud,
  including hybrid fallback.

The integration then retains optimistic mode state, marks a mode write as
pending, and requests a refresh. `current_option` reads only
`smart_portN_status`. Neither operation reads or restores the independent
Smart Load Enable flag. `switch.py` creates its control switches for
inverters; its inverter-level Smart Load switch is a different control.
There is no GridBOSS per-port enable entity in this implementation.

The pinned `pylxpweb==0.10.0b10` helper also sends only the mode command:
`ControlEndpoints.set_smart_port_mode` calls `control_bit_param` with
`BIT_MIDBOX_SP_MODE_N`. Separate `enable_smart_load` and `disable_smart_load`
helpers call `control_function` with `FUNC_SMART_LOAD_EN_N`. Source:
[`control.py` at library commit 91175b4](https://github.com/joyfulhouse/pylxpweb/blob/91175b4f17a16d278b31824b648fdcf1b9692817/src/pylxpweb/endpoints/control.py),
the public `v0.10.0b10` tag. The published source was compared byte-for-byte
with the installed dependency used for tests.

The integration defect is treating a configuration mode as a reversible
load control while verifying only configuration. A successful mode readback
does not establish enable state or actual power delivery. The integration
source does not itself write the enable flag during a mode change; attributing
the observed clear specifically to portal code or firmware would require
additional evidence.

## Fix and operational behavior

Reject Unused at the select method entry, before optimistic state, writes,
fallback, pending-mode tracking, or refresh. Apply this guard unconditionally
to all four ports and all connection modes: stale, missing, or already-Unused
mode state must not authorize a potentially destructive command.

Keep Unused in the option vocabulary and status mapping so externally
configured ports remain readable. Smart Load and AC Couple retain their
existing write paths. An Unused service call now raises `HomeAssistantError`
with an explanation and portal guidance; an automation must handle that
error and stop using mode changes as load pause/resume.

The fix does not automatically energize a load or restore a saved enable
value. It cannot infer whether a disabled flag was intentional, and two
separate writes would not be atomic. Recovery for an already affected port
is an explicit portal enable action followed by checking actual load power.

Per-port enable entities and other port settings are tracked separately in
[issue #638](https://github.com/joyfulhouse/eg4_web_monitor/issues/638).
That work requires verified state acquisition and write mappings; this fix
adds no guessed enable register and makes no claim that readback proves
hardware semantics.

## Regression coverage

`TestSmartPortModeSelect.test_unused_rejected_before_any_side_effect` covers
every port across cloud, local, and hybrid routing with Smart Load, AC Couple,
Unused, and unknown status. It checks that the rejection preserves the
displayed state and calls neither write path, optimistic-state initialization,
pending-mode tracking, HA state publication, nor refresh. The local mock is
configured to fail if reached, so the test also guards against cloud fallback.

Existing tests exercise readable Unused state, successful Smart Load and
AC Couple writes, cloud rejection, unavailable transport, hybrid fallback,
and optimistic retention. The cloud-rejection test now uses Smart Load so
it continues to exercise a reachable cloud failure rather than the new guard.
`test_index_selection_cannot_bypass_unused_guard` additionally exercises
Home Assistant's inherited first, previous, and cycling-next helpers, which
call the entity method directly rather than the option service wrapper.

These are software regression checks. They do not simulate firmware or
promote the reporter's hardware claim to hardware-proven.

## Validation and adversarial review

Validation on 2026-10-13 used the pinned test requirements and both repository
Home Assistant constraint files:

- Minimum (Python 3.13): full suite 3,692 passed, 14 skipped.
- Latest (Python 3.14): full suite 3,697 passed, 9 skipped.
- Final focused select/retention suites: 117 passed in each environment,
  including the three index-selection regressions added after full-suite
  collection.
- Repository-wide Ruff lint and format checks passed. Strict mypy passed
  with zero errors in both environments (50 source files).

**Kimi K3** (`kimi-code/k3`) reviewed the source paths, dependency, tests,
and documentation and returned no blocking findings. Its low-priority
documentation candidates were addressed by the breaking-change changelog
entry and guidance for ports configured as Unused outside HA. It verified
the local writer's fresh lock-held read-modify-write and found no other
integration mode writer. Unverified firmware scope remains a limitation.

**Grok 4.7** (`grok-4.7`) inspected repository and HA/dependency source paths.
That traversal reached its turn limit before a final verdict. A final
review supplied the complete committed change and relevant HA, integration,
and pinned library source as a fixed evidence bundle, with tools disabled.
It returned no blocking findings: the entry-point guard covers transport
routing and HA index selection. It noted that last/non-cycling helpers
are not separately tested but share the same guarded entity method, and
that hardware/local reproduction and enable-entity work remain outside
this fix. Neither review establishes hardware semantics.
