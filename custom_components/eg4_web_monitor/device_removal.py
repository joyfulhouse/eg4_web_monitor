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

Each battery-capable parent keeps its OWN battery observation clock (PR #489
finding 4): a module ages toward deletion only while ITS parent has been
battery-attestable -- an ``"error"`` row, a down local transport link, or an
inverter that has not yet confirmed a single battery fetch resets that
parent's clock alone.  So one permanently-degraded inverter no longer blocks
battery cleanup under a healthy sibling.  Two cases have no parent to
attribute and fall back to a GLOBAL battery clock (every enumerated parent
attestable): a module whose recorded parent has since left the device table,
and a module never once seen this session (its parent, and even its class,
unknowable).  The global clock is the conservative floor under the review's
stated asymmetry (a refused deletion is an annoyance; a wrongly permitted one
is irreversible); the per-parent clocks only ever relax it for a battery whose
own parent is demonstrably healthy.

One residual is documented rather than papered over: a HYBRID system whose
LOCAL battery read succeeds (stamping the parent attestable) while its CLOUD
supplement for a 5th..Nth module fails from a COLD restart can still age that
never-seen module out.  It is bounded by and consistent with the #258
carry-forward: a module seen even once is re-presented (carried forward) until
#258's own staleness gate evicts it, so removal's window starts only after
#258 has concluded the module is gone; the cold-restart sub-case has no
library success signal to gate on (pylxpweb stamps the supplemental timestamp
even on a failed supplement) and self-heals the instant the module reappears.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
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


def _iter_provided(
    data: dict[str, Any], plant_id: str | None
) -> Iterator[tuple[str, str, str | None]]:
    """Yield ``(identifier, class, parent_serial)`` for everything provided.

    The single source of truth for what the integration registers: the
    device-table keys (inverters, GridBOSS, parallel groups), each device's
    battery keys VERBATIM, the battery-bank identifier only under the #169
    device-info gate, and ``station_{plant_id}`` while station data is present.
    Device-class identifiers have no parent (``None``); every battery-class
    identifier carries the serial of the device that provides it, so a battery
    deletion can be judged against ITS parent's clock (PR #489 finding 4).
    """
    for serial, device_data in (data.get("devices") or {}).items():
        parent = str(serial)
        yield parent, _CLASS_DEVICE, None
        if not isinstance(device_data, dict):
            continue
        sensors = device_data.get("sensors") or {}
        # Bank gate -- must stay in lockstep with
        # DeviceInfoMixin.get_battery_bank_device_info (#169): bank sensors
        # present AND a non-zero battery count.
        if any(str(key).startswith("battery_bank_") for key in sensors) and (
            sensors.get("battery_bank_count") or 0
        ):
            yield f"{serial}_battery_bank", _CLASS_BATTERY, parent
        for battery_key in device_data.get("batteries") or {}:
            yield str(battery_key), _CLASS_BATTERY, parent
    if "station" in data and plant_id is not None:
        yield f"station_{plant_id}", _CLASS_DEVICE, None


def provided_identifiers(data: dict[str, Any], plant_id: str | None) -> dict[str, str]:
    """Map every identifier the data currently provides to its class."""
    return {
        identifier: klass
        for identifier, klass, _parent in _iter_provided(data, plant_id)
    }


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
        # Under the shared per-account cloud request budget (#533): this
        # confirmation call competes with the coordinator's own fan-out and
        # must not stack an unbounded extra request on a saturated portal.
        async with coordinator._api_semaphore:
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


# How recently a parent's battery fetch must have succeeded for its battery
# set to count as confirmed.  Every healthy path re-stamps well inside this
# (transport/combined reads at the poll cadence, cloud battery info at its
# 5-minute TTL), so tripping it means a sustained battery-only outage --
# the silent partial failure where the parent's runtime row stays healthy
# while its module dict is served from an ever-older cache.
_BATTERY_CONFIRMATION_MAX_AGE = timedelta(minutes=30)


def _battery_confirmed(inverter: Any) -> bool:
    """Whether this inverter's battery fetch succeeded recently.

    pylxpweb's ``_battery_cache_time`` is a success signal: as of 0.9.39b8
    every leg (transport, combined, HTTP) stamps it only when a battery fetch
    actually delivered data (on 0.9.39b7 the individual transport leg still
    stamps per attempt -- the freshness gate is simply never stale there, so
    this degrades to the None-check until the pin moves).  ``None`` means the
    session has never once confirmed the battery set -- the cold-restart
    outage of PR #489 finding 2.  A *stale* stamp means it succeeded once but
    has been failing since -- the review's residual: after
    ``BATTERY_CARRY_FORWARD_MAX_AGE`` of such silent failure the evicted
    module dict would read as genuine absence.  Both refuse.
    """
    stamp = getattr(inverter, "_battery_cache_time", None)
    if stamp is None:
        return False
    if not isinstance(stamp, datetime):
        return False
    return datetime.now() - stamp <= _BATTERY_CONFIRMATION_MAX_AGE


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
    - a parent whose battery fetch is unconfirmed or stale per
      :func:`_battery_confirmed` -- the cold-restart battery-endpoint outage
      of finding 2 and its silent-partial-failure tail, where a live module
      absent from a failing fetch would otherwise age out.

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
        if not _battery_confirmed(inverter):
            return False
    return True


def _parent_battery_ok(
    coordinator: "EG4DataUpdateCoordinator", data: dict[str, Any]
) -> dict[str, bool]:
    """Per battery-capable parent: whether its battery fetch is confirmed.

    The per-parent counterpart of :func:`_battery_fetch_ok` (PR #489 finding
    4): each inverter's battery attestation is judged on ITS OWN signals so a
    degraded parent cannot freeze battery cleanup under a healthy sibling.
    Same three signals as the global verdict, but scoped to one parent -- an
    ``"error"`` row or a down local transport link on that device, or an
    inverter whose battery fetch is unconfirmed or stale per
    :func:`_battery_confirmed`.  Only inverter-bearing devices carry a
    battery bank; MID/GridBOSS rows (no inverter object) are skipped, so a
    GridBOSS error never resets an inverter's clock.
    """
    result: dict[str, bool] = {}
    for serial, device_data in (data.get("devices") or {}).items():
        if not isinstance(device_data, dict):
            continue
        inverter = coordinator.get_inverter_object(serial)
        if inverter is None:
            continue
        if "error" in device_data or coordinator.is_transport_link_down(serial):
            result[str(serial)] = False
        else:
            result[str(serial)] = _battery_confirmed(inverter)
    return result


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
    not met) and the next qualifying cycle restarts it.  The battery class is
    further split into one clock PER battery-capable parent plus the global
    clock the never-seen / departed-parent cases fall back to (finding 4).
    See the module docstring for why blind and incomplete time must never
    count.
    """
    now = monotonic()
    recovered = not coordinator.last_update_success

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

    # Per-parent battery clocks (finding 4). A failed device list makes every
    # parent unattestable, so drop them all; otherwise advance/reset each on
    # its own verdict and prune any parent no longer enumerated (its batteries,
    # if any linger in the registry, fall back to the global clock above).
    parent_clocks = coordinator._removal_battery_parent_since
    if not device_list_ok:
        parent_clocks.clear()
    else:
        parent_ok = _parent_battery_ok(coordinator, data)
        for parent_serial, ok in parent_ok.items():
            if not ok:
                parent_clocks[parent_serial] = None
            elif recovered or parent_clocks.get(parent_serial) is None:
                parent_clocks[parent_serial] = now
        for gone in [p for p in parent_clocks if p not in parent_ok]:
            del parent_clocks[gone]

    ledger = coordinator._removal_identifier_last_seen
    for identifier, klass, parent in _iter_provided(data, coordinator.plant_id):
        ledger[identifier] = (now, klass, parent)

    stale = [
        identifier
        for identifier, (seen_at, _klass, _parent) in ledger.items()
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
    it was seen within the window).  A battery module is judged against ITS
    parent's clock while that parent is still enumerated, and the global
    battery clock otherwise (finding 4).  An identifier never seen this session
    is held to the conservative battery-class window -- its class is unknowable.
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
    parent_clocks = coordinator._removal_battery_parent_since
    now = monotonic()
    for identifier in identifiers:
        record = ledger.get(identifier)
        if record is None:
            seen_at: float | None = None
            klass = _CLASS_BATTERY
            parent: str | None = None
        else:
            seen_at, klass, parent = record
        window = _WINDOWS[klass]
        if klass == _CLASS_DEVICE:
            observed_since = coordinator._removal_device_observed_since
        elif parent is not None and parent in provided and parent in parent_clocks:
            # The module's parent is still enumerated and battery-attestable on
            # its own clock: judge this module against ITS parent (finding 4),
            # not the whole subsystem.  A degraded SIBLING never resets it.
            observed_since = parent_clocks[parent]
        else:
            # Parent departed, never-seen (unknown parent), or not yet
            # battery-attestable: fall back to the conservative global clock.
            observed_since = coordinator._removal_battery_observed_since
        if observed_since is None or now - observed_since < window:
            # The current run of complete observations does not yet cover the
            # window -- blind, cached, and incomplete time never count.
            return False
        if seen_at is not None and now - seen_at < window:
            return False

    return True
