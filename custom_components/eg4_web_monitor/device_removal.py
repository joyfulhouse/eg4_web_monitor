"""Per-device removal from the UI (#174).

Home Assistant offers a Delete action on a device page when the integration
defines ``async_remove_config_entry_device``; ``__init__`` re-exports the
hook from this module.  It lets users delete devices the coordinator no
longer provides — an inverter dropped from the station or the configuration,
a battery module no longer reported, a dissolved parallel group, or a
legacy-format duplicate left behind by an older version — without deleting
and re-adding the whole config entry.

Refusals are deliberately conservative, applying the #217 smart-port-cleanup
lesson that placeholder or degraded cycles must never be read as
authoritative absence: a failed update, an empty device table, or a
LOCAL-mode placeholder cycle (a parent inverter present with an empty
``batteries`` dict, as the first refresh reports before the first real poll)
refuses removal outright.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator


def _provided_device_identifiers(
    coordinator: EG4DataUpdateCoordinator,
) -> set[str]:
    """Collect the identifiers of every device the coordinator currently provides.

    Covers all four identifier shapes the integration registers:
    ``{serial}`` (inverter / GridBOSS / parallel group — the keys of
    ``data["devices"]``), ``{serial}_battery_bank``, the per-module battery
    keys from ``device_data["batteries"]``, and ``station_{plant_id}``.
    """
    data = coordinator.data or {}
    provided: set[str] = set()
    for serial, device_data in data.get("devices", {}).items():
        provided.add(serial)
        # The battery bank derives from its parent inverter: keep it while
        # the parent is provided, even on cycles where the bank sensors are
        # temporarily absent (link-down reads, shared-battery secondary
        # inverters — #169).
        provided.add(f"{serial}_battery_bank")
        provided.update(device_data.get("batteries") or {})
    if "station" in data and coordinator.plant_id is not None:
        provided.add(f"station_{coordinator.plant_id}")
    return provided


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry[EG4DataUpdateCoordinator],
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing devices the coordinator no longer provides (#174).

    Called by Home Assistant when the user confirms the Delete action on a
    device page; returning False refuses the removal.  A device may be
    deleted only when nothing it identifies is present in the current
    coordinator data.  Devices still being provided are refused: their
    entities would recreate them on the next cycle under fresh registry
    entries, losing customizations and breaking registry-pinned
    automations (#217).
    """
    coordinator = getattr(config_entry, "runtime_data", None)
    if coordinator is None or not coordinator.last_update_success:
        # No healthy data to judge staleness against — refuse rather than
        # let an outage make every device look removable.
        return False
    devices = (coordinator.data or {}).get("devices") or {}
    if not devices:
        # An empty device table is a degraded state, not evidence that
        # every device is gone.
        return False

    provided = _provided_device_identifiers(coordinator)
    if any(
        identifier in provided
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    ):
        return False

    # Placeholder guard (same lesson as the #217 smart-port cleanup): the
    # LOCAL-mode first refresh reports each inverter with an EMPTY
    # "batteries" dict before the first real poll.  A live battery-module
    # device must not look stale during that window, so refuse to remove a
    # battery-shaped identifier ({parent_serial}-...) whose parent inverter
    # is provided but carries no battery data yet.
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN or "-" not in identifier:
            continue
        parent_serial = identifier.split("-", 1)[0]
        parent = devices.get(parent_serial)
        if parent is not None and not parent.get("batteries"):
            return False

    return True
