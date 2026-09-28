"""GridBOSS smart-port devices: port sensors, registry sync, and migration.

Each GridBOSS smart port is its own HA device (``{serial}_smart_port_{n}``,
via the GridBOSS) holding the port's mode select and a fixed sensor set:

- **Power and current are mode-neutral** ("Power L1", "Current L2"): one
  entity reads whichever mode the port is in (the port status label IS the
  coordinator key prefix: ``smart_load`` / ``ac_couple``).
- **Energy stays per mode** ("Smart Load Energy Total", "AC Couple Energy
  Total"): each firmware counter keeps its own ``total_increasing`` entity.
  Switching one entity between counters would corrupt HA's long-term
  statistics (a jump reads as consumption, a negative delta, or a meter
  reset).

An entity whose mode is not the port's current one is disabled in the entity
registry and re-enabled when the port returns to that mode.

Earlier versions put per-mode sensors (``smart_load{n}_*`` /
``ac_couple{n}_*``) on the GridBOSS device; setup adopts those registry
entries as the port sensors, keeping their entity IDs and history.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.entity_registry as er
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator_mappings import (
    GRIDBOSS_SMART_PORT_KEY_TO_PORT,
    SMART_PORT_READ_KEY,
    SMART_PORT_VALIDATED_KEY,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Port status labels that mean "a mode is active"; each equals the key prefix.
ACTIVE_PORT_MODES: tuple[str, ...] = ("smart_load", "ac_couple")
PORT_UNUSED = "unused"

_MODE_LABELS = {"smart_load": "Smart Load", "ac_couple": "AC Couple"}
_NEUTRAL_NAMES = {
    "power": "Power",
    "power_l1": "Power L1",
    "power_l2": "Power L2",
    "current_l1": "Current L1",
    "current_l2": "Current L2",
}
_ENERGY_NAMES = {"today": "Energy Today", "total": "Energy Total"}

# Per-port currents come from Modbus registers only; the cloud never has them.
LOCAL_ONLY_KEY_SUFFIXES: frozenset[str] = frozenset({"current_l1", "current_l2"})

PORT_MODE_SELECT_NAME = "Mode"


@dataclass(frozen=True)
class PortSensorSpec:
    """One sensor of a smart port device.

    ``mode`` is None for a mode-neutral sensor, else the only mode it serves.
    ``key_suffix`` is the coordinator key suffix (``{mode}{n}_{key_suffix}``);
    ``id_suffix`` is the unique-ID suffix (``{serial}_smart_port{n}_{id_suffix}``).
    """

    id_suffix: str
    key_suffix: str
    mode: str | None
    name: str


PORT_SENSOR_SPECS: tuple[PortSensorSpec, ...] = (
    *(PortSensorSpec(s, s, None, name) for s, name in _NEUTRAL_NAMES.items()),
    *(
        PortSensorSpec(f"{mode}_{s}", s, mode, f"{_MODE_LABELS[mode]} {name}")
        for mode in ACTIVE_PORT_MODES
        for s, name in _ENERGY_NAMES.items()
    ),
)


PORT_SENSOR_SPECS_BY_ID: dict[str, PortSensorSpec] = {
    spec.id_suffix: spec for spec in PORT_SENSOR_SPECS
}


def port_sensor_unique_id(serial: str, port: int, id_suffix: str) -> str:
    """Return the unique ID of a smart port sensor."""
    return f"{serial}_smart_port{port}_{id_suffix}"


def resolve_port_mode(sensors: dict[str, Any], port: int) -> str | None:
    """Return the port's mode, ``PORT_UNUSED``, or None when unknown.

    Mirrors the coordinator's smart-port filter: on a filtered cycle (fresh
    validated read or cached statuses) an unused port has ALL its per-port
    keys removed.  An "unused" label with per-port keys still present is the
    filter's skip path (invalid status registers, #195/#248), where labels
    default to "unused" but nothing was filtered -- so fall back to the keys
    present, preferring Smart Load as the coordinator's own mapping does.
    Placeholder data (no status, no keys) is unknown.
    """
    status = sensors.get(f"smart_port{port}_status")
    if status in ACTIVE_PORT_MODES:
        return str(status)
    for mode in ACTIVE_PORT_MODES:
        if any(
            key in sensors
            for key, key_port in GRIDBOSS_SMART_PORT_KEY_TO_PORT.items()
            if key_port == port and key.startswith(f"{mode}{port}_")
        ):
            return mode
    return PORT_UNUSED if status == PORT_UNUSED else None


def port_status_authoritative(sensors: dict[str, Any], port: int) -> bool:
    """Whether the port's status label can be trusted as its mode.

    True for an active label, or an "unused" label on a filtered cycle (no
    per-port keys left).  False on the filter's skip path (#195/#248: labels
    defaulted to "unused" with keys unfiltered) and on placeholder data.
    """
    status = sensors.get(f"smart_port{port}_status")
    if status in ACTIVE_PORT_MODES:
        return True
    return status == PORT_UNUSED and resolve_port_mode(sensors, port) == PORT_UNUSED


def spec_is_active(spec: PortSensorSpec, mode: str | None) -> bool:
    """Whether a port sensor serves the port's (resolved) mode."""
    if mode not in ACTIVE_PORT_MODES:
        return False
    return spec.mode is None or spec.mode == mode


def spec_serves(spec: PortSensorSpec, sensors: dict[str, Any], port: int) -> bool:
    """Whether a port sensor has something to report right now.

    With an untrusted status (#195/#248 skip path), an energy sensor serves
    whenever its own mode's counter is present: that firmware never reports
    a valid mode, and both counters are real.
    """
    if spec.mode is not None and not port_status_authoritative(sensors, port):
        return f"{spec.mode}{port}_{spec.key_suffix}" in sensors
    return spec_is_active(spec, resolve_port_mode(sensors, port))


def _split_mode_key_unique_id(unique_id: str) -> tuple[str, str, int, str] | None:
    """Split ``{serial}_{mode}{n}_{suffix}`` into (serial, mode, port, suffix)."""
    for key, port in GRIDBOSS_SMART_PORT_KEY_TO_PORT.items():
        if unique_id.endswith(f"_{key}"):
            mode, suffix = key.split(f"{port}_", 1)
            return unique_id[: -len(key) - 1], mode, port, suffix
    return None


def _gridboss_sensors(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(serial): device_data.get("sensors", {})
        for serial, device_data in (data or {}).get("devices", {}).items()
        if device_data.get("type") == "gridboss"
    }


# A mode just written through the Mode select, awaiting confirmation by a
# GridBOSS read.  While one is pending, the coordinator reads the GridBOSS every
# cycle instead of once per (dongle) transport interval, and the sync accepts
# the first validated read that confirms it.  Bounded so a write the device
# never applies stops forcing reads.
EXPECTED_MODE_TTL = 120.0
_EXPECTED_ATTR = "_smart_port_expected_modes"


def note_port_mode_written(coordinator: Any, serial: str, port: int, mode: str) -> None:
    """Record a mode just written to a port (``smart_load``/``ac_couple``/``unused``)."""
    expected: dict[tuple[str, int], tuple[str, float]] = (
        coordinator.__dict__.setdefault(_EXPECTED_ATTR, {})
    )
    expected[(serial, port)] = (mode, time.monotonic() + EXPECTED_MODE_TTL)


def expected_port_mode(coordinator: Any, serial: str, port: int) -> str | None:
    """Return the unexpired mode just written to a port, if any."""
    expected = coordinator.__dict__.get(_EXPECTED_ATTR) or {}
    mode, deadline = expected.get((serial, port), (None, 0.0))
    return mode if mode is not None and time.monotonic() < deadline else None


def serials_awaiting_port_mode(coordinator: Any) -> set[str]:
    """GridBOSS serials with a written port mode the data does not show yet.

    Called at the start of a coordinator cycle: expectations the previous
    cycle's data already confirms, or that expired, are dropped.
    """
    expected: dict[tuple[str, int], tuple[str, float]] = (
        coordinator.__dict__.get(_EXPECTED_ATTR) or {}
    )
    gridboss = _gridboss_sensors(getattr(coordinator, "data", None))
    now = time.monotonic()
    for key, (mode, deadline) in list(expected.items()):
        serial, port = key
        status = gridboss.get(serial, {}).get(f"smart_port{port}_status")
        if now >= deadline or status == mode:
            del expected[key]
    return {serial for serial, _port in expected}


# Per-entity registry option (under this domain) recording why the sync last
# touched an entity, so it only ever undoes its own changes.
_SYNC_OPTION = "smart_port_sync"
_AUTO_DISABLED = "disabled"  # the sync disabled it for an inactive mode
_USER_ENABLED = "user_enabled"  # the user re-enabled it while inactive
# Per-entity registry option marking a per-mode entry superseded by another
# mode's entry during adoption: set once, then the entry is left alone.
_SUPERSEDED_OPTION = "smart_port_superseded"

# Port sensors whose adoption waits for a validated read (see
# async_migrate_to_port_sensors), as (serial, port, id_suffix).
_DEFERRED_ATTR = "_smart_port_deferred_sensors"


def set_deferred_port_sensors(
    coordinator: Any, deferred: set[tuple[str, int, str]]
) -> None:
    """Record the port sensors whose creation waits for a validated read."""
    coordinator.__dict__[_DEFERRED_ATTR] = set(deferred)


def deferred_port_sensors(coordinator: Any) -> set[tuple[str, int, str]]:
    """Return the port sensors whose creation waits for a validated read."""
    deferred: set[tuple[str, int, str]] = coordinator.__dict__.setdefault(
        _DEFERRED_ATTR, set()
    )
    return deferred


class PortSensorEnablement:
    """Disable port sensors that don't serve the port's mode; re-enable them.

    - Acts only on VALIDATED status reads (the #217 authority marker), and
      only after ``REQUIRED_READS`` consecutive validated READS agree
      (distinct ``SMART_PORT_READ_KEY`` stamps, not coordinator updates), so a
      single bad read cannot flip entities (or trigger reloads) -- except a
      read confirming a mode just written through the Mode select, which
      that write corroborates.
    - Re-enables only entities it disabled itself (marked in the entity's
      registry options): entities disabled by the user, or by HA's
      "disable new entities" preference, stay disabled.
    - If the user re-enables an entity it disabled, that choice is kept until
      the port next serves the entity's mode; after that the entity is
      managed again.

    Re-enabling makes HA reload the entry ~30 s later, which is how HA adds a
    newly enabled entity.
    """

    REQUIRED_READS = 2

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: Any = None
    ) -> None:
        """Initialize the sync for one config entry."""
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._streak: dict[tuple[str, int], tuple[str | None, int]] = {}
        self._last_read: dict[str, Any] = {}

    def async_sync(self, data: dict[str, Any] | None) -> None:
        """Apply the current validated port modes to the registry."""
        registry = er.async_get(self._hass)
        for serial, sensors in _gridboss_sensors(data).items():
            if not sensors.get(SMART_PORT_VALIDATED_KEY):
                continue
            # Count GridBOSS READS, not coordinator updates: a cycle that
            # re-processes cached device data, or carries the previous devices
            # dict forward, keeps the same read stamp.
            read = sensors.get(SMART_PORT_READ_KEY)
            if read is not None:
                if self._last_read.get(serial) == read:
                    continue
                self._last_read[serial] = read
            for port in range(1, 5):
                mode = resolve_port_mode(sensors, port)
                previous, count = self._streak.get((serial, port), (None, 0))
                count = count + 1 if previous == mode else 1
                self._streak[(serial, port)] = (mode, count)
                # A read confirming the mode just written through the Mode
                # select is corroborated by that write: act on it at once.
                confirmed = (
                    self._coordinator is not None
                    and mode is not None
                    and expected_port_mode(self._coordinator, serial, port) == mode
                )
                if mode is None or (count < self.REQUIRED_READS and not confirmed):
                    continue
                for spec in PORT_SENSOR_SPECS:
                    entity_id = registry.async_get_entity_id(
                        "sensor",
                        DOMAIN,
                        port_sensor_unique_id(serial, port, spec.id_suffix),
                    )
                    if entity_id is not None:
                        _apply(registry, entity_id, spec_is_active(spec, mode))


def _apply(registry: er.EntityRegistry, entity_id: str, active: bool) -> None:
    entry = registry.async_get(entity_id)
    if entry is None:
        return
    marker = dict(entry.options.get(DOMAIN) or {}).get(_SYNC_OPTION)
    if not active:
        if entry.disabled_by is not None or marker == _USER_ENABLED:
            return
        if marker == _AUTO_DISABLED:
            # We disabled it and it is enabled again: the user chose that.
            _set_marker(registry, entity_id, _USER_ENABLED)
            return
        _LOGGER.info("Disabling %s (inactive smart port mode)", entity_id)
        registry.async_update_entity(
            entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
        )
        _set_marker(registry, entity_id, _AUTO_DISABLED)
        return
    if (
        marker == _AUTO_DISABLED
        and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    ):
        _LOGGER.info("Enabling %s (smart port mode active)", entity_id)
        registry.async_update_entity(entity_id, disabled_by=None)
    if marker is not None:
        _set_marker(registry, entity_id, None)


def _set_marker(registry: er.EntityRegistry, entity_id: str, value: str | None) -> None:
    entry = registry.async_get(entity_id)
    if entry is None:
        return
    options = {
        key: val
        for key, val in dict(entry.options.get(DOMAIN) or {}).items()
        if key != _SYNC_OPTION
    }
    if value is not None:
        options[_SYNC_OPTION] = value
    registry.async_update_entity_options(entity_id, DOMAIN, options or None)


def async_migrate_to_port_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any] | None,
    has_local_transport: Callable[[str], bool] | None = None,
) -> set[tuple[str, int, str]]:
    """Adopt existing per-mode sensor entries as the port sensors.

    ``{serial}_{mode}{n}_{suffix}`` gets the port sensor's unique ID (energy:
    ``..._smart_port{n}_{mode}_{suffix}``, one per mode, never contested;
    power/current: ``..._smart_port{n}_{suffix}``, shared by both modes), so
    the registry entry keeps its entity ID, customizations and history.

    A power/current sensor with entries for BOTH modes is contested: only a
    VALIDATED read of an active port mode decides it (``created_at`` cannot:
    HA restores it on re-created entries, and migrated registries hold epoch
    0).  Until then it is returned as deferred, and the platform creates that
    sensor only once a later call adopts it.  Nothing is deleted: the losing
    entry keeps its old unique ID (never created again) and is disabled and
    marked once, then left alone.  Current entries are not adopted for a
    GridBOSS without a local transport, which never creates current sensors.
    Must run before the #217 stale cleanup.

    Returns:
        The deferred port sensors, as (serial, port, id_suffix).
    """
    registry = er.async_get(hass)
    gridboss = _gridboss_sensors(data)
    candidates: dict[
        tuple[str, int, str], tuple[str | None, list[tuple[str, er.RegistryEntry]]]
    ] = {}
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.domain != "sensor":
            continue
        if dict(registry_entry.options.get(DOMAIN) or {}).get(_SUPERSEDED_OPTION):
            continue
        split = _split_mode_key_unique_id(registry_entry.unique_id)
        if split is None or split[0] not in gridboss:
            continue
        serial, mode, port, suffix = split
        if (
            suffix in LOCAL_ONLY_KEY_SUFFIXES
            and has_local_transport is not None
            and not has_local_transport(serial)
        ):
            continue
        id_suffix = f"{mode}_{suffix}" if suffix in _ENERGY_NAMES else suffix
        sensors = gridboss[serial]
        current = (
            resolve_port_mode(sensors, port)
            if sensors.get(SMART_PORT_VALIDATED_KEY)
            else None
        )
        candidates.setdefault((serial, port, id_suffix), (current, []))[1].append(
            (mode, registry_entry)
        )

    deferred: set[tuple[str, int, str]] = set()
    for key, (current, entries) in candidates.items():
        serial, port, id_suffix = key
        target = port_sensor_unique_id(serial, port, id_suffix)
        winner: er.RegistryEntry | None = None
        if not registry.async_get_entity_id("sensor", DOMAIN, target):
            if len(entries) == 1:
                winner = entries[0][1]
            else:
                winner = next(
                    (entity for mode, entity in entries if mode == current), None
                )
                if winner is None:
                    deferred.add(key)
                    continue
            _LOGGER.info(
                "Adopting %s as smart port sensor %s", winner.entity_id, target
            )
            registry.async_update_entity(winner.entity_id, new_unique_id=target)
        for _mode, superseded in entries:
            if superseded is not winner:
                _supersede(registry, superseded)
    return deferred


def _supersede(registry: er.EntityRegistry, entry: er.RegistryEntry) -> None:
    """Disable and mark an entry another mode's entry replaced (once)."""
    _LOGGER.info(
        "Keeping superseded smart port entity %s disabled; delete it from its "
        "entity settings if its history is not needed",
        entry.entity_id,
    )
    if entry.disabled_by is None:
        registry.async_update_entity(
            entry.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
        )
    options = dict(entry.options.get(DOMAIN) or {})
    options[_SUPERSEDED_OPTION] = True
    registry.async_update_entity_options(entry.entity_id, DOMAIN, options)
