"""Per-device removal from the UI (#174).

Home Assistant offers a Delete action on a device page when the integration
defines ``async_remove_config_entry_device``; ``__init__`` re-exports the
hook from this module.  It lets users delete devices the coordinator no
longer provides -- an inverter dropped from the station or the configuration,
a battery module no longer reported, a dissolved parallel group, or a
legacy-format duplicate left behind by an older version -- without deleting
and re-adding the whole config entry.

Presence is judged over an OBSERVATION LEDGER, not a single coordinator
cycle (PR #489 review): any one cycle's payload is a *subset* of the truth --
battery slots rotate round-robin (#252), cloud payloads omit modules, a
failed ``getParallelGroupDetails`` silently drops the parallel-group row
while its members appear standalone, and the LOCAL first refresh reports
inverters with an empty ``batteries`` dict.  Every successful refresh
therefore records each provided identifier with a monotonic last-seen stamp
(:func:`record_provided_identifiers`, called by the coordinator), and a
device is deletable only when every one of its identifiers has been absent
for its class's full window *within a run that has observed that whole window
COMPLETELY*:

- **device class** (inverter/GridBOSS serials, parallel groups, the
  station): enumerated every healthy cycle, so 15 minutes of continuous
  absence is decisive -- long enough to ride out multi-cycle discovery
  blips like the degraded parallel-group case.
- **battery class** (battery modules and ``{serial}_battery_bank``):
  presence in any one cycle is a subset (slot rotation, module sleep,
  partial cloud payloads), so absence is only trusted after
  ``BATTERY_CARRY_FORWARD_MAX_AGE`` (6 h) -- the same eviction window the
  #258 battery carry-forward uses to decide a module is really gone.

Coverage counts only COMPLETE observed time (PR #489 fix round).  A cycle can
report success while discovery silently failed: pylxpweb's
``Station._load_devices`` swallows a device-list API failure and continues
with an empty device table (finding 1), and a per-device battery fetch is
gathered with ``return_exceptions`` and swallowed inside pylxpweb's own
``inverter.refresh()`` (finding 2) -- both publish a "successful"
snapshot whose emptiness is an outage, not a truth.  Each class therefore has
its own observation clock -- the start of the current contiguous run of
cycles that observed that class COMPLETELY (:func:`assess_discovery_completeness`
supplies the per-cycle verdicts).  A clock is ``None`` whenever the run is
broken: the previous cycle failed (recovery -- the coordinator's
``last_update_success`` still holds the prior verdict while the update method
runs), the 3-strike cached fallback served old data (the coordinator resets
the clocks there; ``last_update_success`` stays True across a <=2-strike blip,
finding 3), or this cycle's completeness for that class was not met.  The
absence windows are thus measured only across an unbroken run of COMPLETE
observations, so neither blind outage time nor a silently-incomplete
discovery can age an identifier toward deletion.  The hook additionally
refuses while ``_consecutive_update_failures`` is non-zero -- the current
table is cached-through-an-outage, not a fresh sighting (finding 3).

A cold start therefore refuses battery-class deletions for the first 6
observed complete hours and device-class for the first 15 observed complete
minutes.  An identifier never seen in a whole COMPLETE observed window is
deletable -- that is precisely the stale-device case the feature exists for
(the #174 ghost inverter parked disabled after a hardware swap).  Its class
is unknowable, so it is held to the conservative battery-class window.
Battery keys are tracked VERBATIM in every shape the coordinator registers
(serial-based ``{parent}-{sn}``, positional ``BAT001``-style,
``@pos``-suffixed) -- no identifier parsing anywhere.

The battery-bank identifier is recorded only when the bank is actually
registered (bank sensors present AND ``battery_bank_count`` > 0 -- the
device-info gate from #169), so an orphan bank on a shared-battery
secondary ages out and becomes deletable instead of being pinned forever
by its parent's existence.

The battery clock is GLOBAL across the device table: any degraded parent --
an ``"error"`` row, a down local transport link, or an inverter that has not
yet confirmed a single battery fetch -- resets it.  That is a deliberate
conservative choice under the review's stated asymmetry (a refused deletion
is an annoyance; a wrongly permitted one is irreversible): while any part of
the battery subsystem is unattestable, no battery deletion is judged safe.
The residual is that one permanently-degraded-but-enumerated inverter blocks
battery cleanup for the whole entry until it recovers or is itself removed.
"""

from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID, DOMAIN
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

# Ledger entries older than this are pruned on each stamp so the map cannot
# grow unbounded from identifier churn over a long session. Chosen well
# beyond both absence windows: a pruned entry becomes a conservative
# "never seen" one, so pruning must only ever touch identifiers already long
# past any deletion decision, never a still-relevant recent sighting.
_LEDGER_PRUNE_AGE = 4 * BATTERY_ABSENCE_WINDOW


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
        # Bank gate -- must stay in lockstep with
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


async def assess_discovery_completeness(
    coordinator: "EG4DataUpdateCoordinator", data: dict[str, Any]
) -> tuple[bool, bool]:
    """Judge whether THIS cycle observed the device set completely.

    Returns ``(device_list_ok, battery_ok)``.  A coordinator cycle can report
    success while discovery silently failed, and a deletion must never be
    authorized off such a cycle (PR #489 fix round -- see the module
    docstring for the two swallow points).  ``battery_ok`` implies
    ``device_list_ok``: a missing device list makes every battery
    unattestable too.
    """
    device_list_ok = await _device_list_ok(coordinator, data)
    battery_ok = device_list_ok and _battery_fetch_ok(coordinator, data)
    return device_list_ok, battery_ok


async def _device_list_ok(
    coordinator: "EG4DataUpdateCoordinator", data: dict[str, Any]
) -> bool:
    """Whether the device enumeration is trustworthy this cycle.

    LOCAL/DONGLE/MODBUS enumerate no devices remotely -- the set is
    config-defined and always present, so discovery cannot silently drop a
    device.  For CLOUD/HYBRID a non-empty table is self-evidently loaded; an
    EMPTY table is ambiguous between a genuinely empty plant (the user
    removed their last inverter -- deletion must stay possible, finding 6
    from the prior round) and pylxpweb's swallowed device-list failure
    (finding 1).  Only a device-list call that actually SUCCEEDS -- even
    returning zero rows -- confirms the plant is really empty.
    """
    if coordinator.connection_type not in (
        CONNECTION_TYPE_HTTP,
        CONNECTION_TYPE_HYBRID,
    ):
        return True
    if data.get("devices"):
        return True
    client = getattr(coordinator, "client", None)
    plant_id = getattr(coordinator, "plant_id", None)
    if client is None or plant_id is None:
        return False
    try:
        response = await client.api.devices.get_devices(int(plant_id))
    except Exception:  # noqa: BLE001 -- any failure means the list is unconfirmed
        return False
    if getattr(response, "rows", None):
        # Devices exist but our station has none: pylxpweb swallowed a
        # partial load. Force a hierarchy reload next cycle and refuse until
        # it succeeds rather than trust the empty table.
        coordinator.station = None
        return False
    return True


def _battery_fetch_ok(
    coordinator: "EG4DataUpdateCoordinator", data: dict[str, Any]
) -> bool:
    """Whether every battery-capable parent confirmed a battery fetch.

    A battery deletion must never be authorized off a cycle where some
    parent's battery fetch failed -- the empty/partial ``batteries`` dict it
    produces is indistinguishable from genuine module absence.  Signals:

    - an ``"error"`` row (LOCAL link-down, cloud per-device failure) or the
      mode-independent :meth:`is_transport_link_down` verdict (HYBRID cloud
      fallback carries no row marker) -- the whole device is degraded;
    - pylxpweb stamps ``_battery_cache_time`` only on a SUCCESSFUL battery
      fetch (both the transport and HTTP legs keep cached data and leave the
      stamp untouched on failure), so a battery-capable inverter whose stamp
      is still ``None`` has never once confirmed its battery set this session
      -- exactly the cold-restart battery-endpoint outage of finding 2, where
      a live module absent from a failing fetch would otherwise age out.

    A MID/GridBOSS row carries no battery bank and no inverter object, so it
    is skipped; a battery-less inverter stamps ``_battery_cache_time`` on its
    first (empty) fetch and passes thereafter.
    """
    devices = data.get("devices") or {}
    for serial, device_data in devices.items():
        if not isinstance(device_data, dict):
            continue
        if "error" in device_data:
            return False
        if coordinator.is_transport_link_down(serial):
            return False
        inverter = coordinator.get_inverter_object(serial)
        if inverter is None:
            continue
        if getattr(inverter, "_battery_cache_time", None) is None:
            return False
    return True


def record_provided_identifiers(
    coordinator: "EG4DataUpdateCoordinator",
    data: dict[str, Any],
    device_list_ok: bool,
    battery_ok: bool,
) -> None:
    """Stamp the ledger and advance the per-class observation clocks.

    Called once per SUCCESSFUL refresh with the freshly built data and the
    completeness verdicts from :func:`assess_discovery_completeness`.  Never
    called on the 3-strike cached-fallback path -- that data is old evidence,
    and the coordinator resets the clocks there instead.

    Each class's clock marks the start of the current contiguous run of
    cycles that observed that class COMPLETELY; it is ``None`` whenever the
    run is broken (recovery from a failed cycle, or this cycle's completeness
    not met) and the next qualifying cycle restarts it.  See the module
    docstring for why blind and incomplete time must never count.
    """
    now = monotonic()
    recovered = not coordinator.last_update_success

    coordinator._removal_device_list_ok = device_list_ok
    coordinator._removal_battery_ok = battery_ok

    # An incomplete cycle is no observation at all -> clear the clock. A
    # complete cycle that either recovers from a broken run (a failed cycle,
    # or a cached fallback that reset the clock to None) or finds no run in
    # progress starts the run at now; an uninterrupted complete run is left
    # to keep accumulating.
    if not device_list_ok:
        coordinator._removal_device_observed_since = None
    elif recovered or coordinator._removal_device_observed_since is None:
        coordinator._removal_device_observed_since = now

    if not battery_ok:
        coordinator._removal_battery_observed_since = None
    elif recovered or coordinator._removal_battery_observed_since is None:
        coordinator._removal_battery_observed_since = now

    ledger = coordinator._removal_identifier_last_seen
    for identifier, klass in provided_identifiers(data, coordinator.plant_id).items():
        ledger[identifier] = (now, klass)

    stale = [
        identifier
        for identifier, (seen_at, _klass) in ledger.items()
        if now - seen_at > _LEDGER_PRUNE_AGE
    ]
    for identifier in stale:
        del ledger[identifier]


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
    failed; the coordinator is currently serving cached data through an
    outage (a fetch failed but the 3-strike tolerance has not yet flipped
    ``last_update_success`` -- the table is stale, its absences an outage,
    not evidence); an identifier is currently provided (a live device's
    entities would recreate it under fresh registry entries, losing
    customizations and breaking registry-pinned automations); or the current
    contiguous run of COMPLETE observations has not yet covered the
    identifier's absence window (its class's clock is unset or too young, or
    it was seen within the window).  An identifier never seen this session is
    held to the conservative battery-class window -- its class is unknowable.
    """
    coordinator = getattr(config_entry, "runtime_data", None)
    if coordinator is None or not coordinator.last_update_success:
        # No healthy data to judge staleness against -- refuse rather than
        # let an outage make every device look removable.
        return False
    if getattr(coordinator, "_consecutive_update_failures", 0) != 0:
        # A fetch failed this cycle and cached data is being served while
        # last_update_success is still True (PR #489 finding 3): the table's
        # absences are an outage, not a fresh observation.
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

    ledger = coordinator._removal_identifier_last_seen
    now = monotonic()
    for identifier in identifiers:
        record = ledger.get(identifier)
        if record is None:
            seen_at: float | None = None
            klass = _CLASS_BATTERY
        else:
            seen_at, klass = record
        window = _WINDOWS[klass]
        if klass == _CLASS_DEVICE:
            observed_since = coordinator._removal_device_observed_since
        else:
            observed_since = coordinator._removal_battery_observed_since
        if observed_since is None or now - observed_since < window:
            # The current run of complete observations does not yet cover the
            # window -- blind, cached, and incomplete time never count.
            return False
        if seen_at is not None and now - seen_at < window:
            return False

    return True
