"""Per-device removal from the UI (#174).

Home Assistant offers a Delete action on a device page when the integration
defines ``async_remove_config_entry_device``; ``__init__`` re-exports the
hook from this module.  It lets users delete devices the coordinator no
longer provides — an inverter dropped from the station or the configuration,
a battery module no longer reported, a dissolved parallel group, or a
legacy-format duplicate left behind by an older version — without deleting
and re-adding the whole config entry.

Presence is judged over an OBSERVATION LEDGER, not a single coordinator
cycle (PR #489 review): any one cycle's payload is a *subset* of the truth —
battery slots rotate round-robin (#252), cloud payloads omit modules, a
failed ``getParallelGroupDetails`` silently drops the parallel-group row
while its members appear standalone, and the LOCAL first refresh reports
inverters with an empty ``batteries`` dict.  Every successful refresh
therefore records each provided identifier with a monotonic last-seen stamp
(:func:`record_provided_identifiers`, called by the coordinator), and a
device is deletable only when every one of its identifiers has been absent
for its class's full window *within a session that has observed that whole
window*:

- **device class** (inverter/GridBOSS serials, parallel groups, the
  station): enumerated every healthy cycle, so 15 minutes of continuous
  absence is decisive — long enough to ride out multi-cycle discovery
  blips like the degraded parallel-group case.
- **battery class** (battery modules and ``{serial}_battery_bank``):
  presence in any one cycle is a subset (slot rotation, module sleep,
  partial cloud payloads), so absence is only trusted after
  ``BATTERY_CARRY_FORWARD_MAX_AGE`` (6 h) — the same eviction window the
  #258 battery carry-forward uses to decide a module is really gone.

The coverage requirement counts only OBSERVED time: the clock is
``observed_since`` — the start of the current contiguous run of successful
refreshes — which restarts on the first success after any failed cycle
(:func:`record_provided_identifiers` detects recovery via the coordinator's
own ``last_update_success``, still holding the previous cycle's verdict
while the update method runs).  Blind time can never count as absence: a
cold start refuses battery-class deletions for the first 6 observed hours
and device-class for the first 15 observed minutes, and a long outage —
whose wall-clock span could otherwise both evict the #258 battery
carry-forward AND satisfy the absence window at the moment of recovery —
resets the clock instead.  An identifier never seen in a whole observed
window is deletable — that is precisely the stale-device case the feature
exists for (the #174 ghost inverter parked disabled after a hardware
swap).  Battery keys are tracked VERBATIM in every shape the coordinator
registers (serial-based ``{parent}-{sn}``, positional ``BAT001``-style,
``@pos``-suffixed) — no identifier parsing anywhere.

The battery-bank identifier is recorded only when the bank is actually
registered (bank sensors present AND ``battery_bank_count`` > 0 — the
device-info gate from #169), so an orphan bank on a shared-battery
secondary ages out and becomes deletable instead of being pinned forever
by its parent's existence.  While any device is degraded — an ``"error"``
row (LOCAL link-down, cloud per-device failure) or a mode-independent
``is_transport_link_down`` verdict (HYBRID serves cloud fallback with no
row marker) — battery-class deletions are refused outright: a degraded
parent cannot attest its modules' absence.
"""

from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator_mixins import BATTERY_CARRY_FORWARD_MAX_AGE

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator

# Identifier classes recorded in the ledger.
_CLASS_DEVICE = "device"
_CLASS_BATTERY = "battery"

# Continuous-absence windows per class (seconds). Device-class identifiers
# are re-enumerated every healthy cycle, so a short window suffices;
# battery-class absence is only meaningful past the #258 eviction window.
DEVICE_ABSENCE_WINDOW = 15 * 60.0
BATTERY_ABSENCE_WINDOW = BATTERY_CARRY_FORWARD_MAX_AGE.total_seconds()

_WINDOWS = {
    _CLASS_DEVICE: DEVICE_ABSENCE_WINDOW,
    _CLASS_BATTERY: BATTERY_ABSENCE_WINDOW,
}


def provided_identifiers(data: dict[str, Any], plant_id: str | None) -> dict[str, str]:
    """Map every identifier the data currently provides to its class.

    Mirrors exactly what the integration registers: the device-table keys
    (inverters, GridBOSS, parallel groups), each device's battery keys
    VERBATIM, the battery-bank identifier only under the #169 device-info
    gate, and ``station_{plant_id}`` while station data is present.
    """
    provided: dict[str, str] = {}
    for serial, device_data in (data.get("devices") or {}).items():
        provided[str(serial)] = _CLASS_DEVICE
        if not isinstance(device_data, dict):
            continue
        sensors = device_data.get("sensors") or {}
        # Bank gate — must stay in lockstep with
        # DeviceInfoMixin.get_battery_bank_device_info (#169): bank sensors
        # present AND a non-zero battery count.
        if any(str(key).startswith("battery_bank_") for key in sensors) and (
            sensors.get("battery_bank_count") or 0
        ):
            provided[f"{serial}_battery_bank"] = _CLASS_BATTERY
        for battery_key in device_data.get("batteries") or {}:
            provided[str(battery_key)] = _CLASS_BATTERY
    if "station" in data and plant_id is not None:
        provided[f"station_{plant_id}"] = _CLASS_DEVICE
    return provided


def record_provided_identifiers(
    coordinator: "EG4DataUpdateCoordinator", data: dict[str, Any]
) -> None:
    """Stamp every currently provided identifier in the observation ledger.

    Called by the coordinator once per SUCCESSFUL refresh, with the freshly
    built data — never with the 3-strike cached fallback, whose payload is
    old evidence.

    ``observed_since`` restarts here whenever this success follows a FAILED
    cycle: while the update method runs, the coordinator's
    ``last_update_success`` still holds the previous cycle's verdict, so a
    False reading means observation continuity was just broken and blind
    time must not count toward any absence window.  (A ≤2-cycle
    cached-fallback blip leaves the flag True and slips through — bounded
    at two poll intervals, immaterial against 15-minute/6-hour windows;
    the third strike raises and arms the reset.)
    """
    now = monotonic()
    if (
        coordinator._removal_observed_since is None
        or not coordinator.last_update_success
    ):
        coordinator._removal_observed_since = now
    ledger = coordinator._removal_identifier_last_seen
    for identifier, klass in provided_identifiers(data, coordinator.plant_id).items():
        ledger[identifier] = (now, klass)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    # The string forward reference inside the runtime-generic subscript is
    # deliberate: the EG4ConfigEntry alias lives in __init__ (importing it
    # here would be circular) and evaluates identically at runtime.
    config_entry: ConfigEntry["EG4DataUpdateCoordinator"],
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting a device only when its absence is proven over time.

    Refusal reasons, in order: the entry never set up or its last update
    failed; an identifier is currently provided (a live device's entities
    would recreate it under fresh registry entries, losing customizations
    and breaking registry-pinned automations); the current contiguous run
    of successful refreshes has not yet observed the identifier's full
    absence window; the identifier was seen within its window; or (battery
    class) some device is currently degraded — an ``"error"`` row or a
    down local transport link — so no parent can attest module absence.
    An identifier never seen this session is held to the conservative
    battery-class window — its class is unknowable.
    """
    coordinator = getattr(config_entry, "runtime_data", None)
    if coordinator is None or not coordinator.last_update_success:
        # No healthy data to judge staleness against — refuse rather than
        # let an outage make every device look removable.
        return False

    data = coordinator.data or {}
    identifiers = [
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    ]
    if not identifiers:
        return False

    provided = provided_identifiers(data, coordinator.plant_id)
    if any(identifier in provided for identifier in identifiers):
        return False

    observed_since = coordinator._removal_observed_since
    if observed_since is None:
        # No successful refresh recorded yet this session.
        return False
    ledger = coordinator._removal_identifier_last_seen
    now = monotonic()
    devices = data.get("devices") or {}
    # Degradation is judged mode-independently: LOCAL marks link-down rows
    # with an "error" key and cloud per-device failures do the same, but
    # HYBRID serves cloud-fallback data with NO row marker — there the
    # coordinator's is_transport_link_down() verdict is the signal.
    any_degraded = any(
        isinstance(device_data, dict) and "error" in device_data
        for device_data in devices.values()
    ) or any(coordinator.is_transport_link_down(serial) for serial in devices)

    for identifier in identifiers:
        record = ledger.get(identifier)
        if record is None:
            seen_at: float | None = None
            klass = _CLASS_BATTERY
        else:
            seen_at, klass = record
        window = _WINDOWS[klass]
        if now - observed_since < window:
            # Blind time (failed cycles) never counts as absence: the
            # clock restarts with each recovery, so the window must fit
            # inside the CURRENT unbroken run of successful refreshes.
            return False
        if seen_at is not None and now - seen_at < window:
            return False
        if klass == _CLASS_BATTERY and any_degraded:
            return False

    return True
