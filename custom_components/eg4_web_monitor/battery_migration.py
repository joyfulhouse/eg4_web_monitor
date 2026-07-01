"""Registry migration for canonical battery identity (#252).

Before #252 the three connection modes derived different battery keys for the
same physical battery: CLOUD used the cloud ``batteryKey``
(``{inv}-{batterySn}`` once cleaned), while HYBRID and LOCAL used positional
keys (``{inv}-01..NN``).  The battery key is the battery *device* identifier
and is embedded in every battery entity unique_id
(``{inverterSn}_{batteryKey}_{suffix}``), so switching modes re-keyed every
battery that reports a real serial — duplicating devices and orphaning
history.

This module migrates legacy positional registry entries to the canonical
serial-based keys once the coordinator learns the mapping:

- when the canonical device does not exist yet (pure LOCAL/HYBRID beta
  installs), the positional *device is re-identified in place* — its UUID,
  area, user-set name and labels survive, so device automations, triggers and
  dashboard cards keep working — and the entity unique_ids are renamed in
  place (entity_id and recorder history preserved);
- when the canonical device already exists (a cloud→hybrid install where the
  cloud-era entities survived alongside the positional duplicates), the
  positional duplicates are REMOVED — their own accumulated history and
  long-term statistics are deleted, not merged — and the canonical entities
  resume updating.  Customizations set on the positional device (area, name,
  labels) are backfilled onto the canonical device where the canonical's own
  value is unset.

Safety: a registry row whose entity object is currently instantiated is never
renamed or removed — the migration for that battery is deferred to the next
restart/reload, where it runs before entities instantiate.
"""

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@callback
def async_migrate_battery_keys(
    hass: HomeAssistant,
    entry_id: str,
    inverter_serial: str,
    key_migrations: dict[str, str],
) -> list[str]:
    """Migrate legacy positional battery registry entries to canonical keys.

    Args:
        hass: Home Assistant instance.
        entry_id: Config entry id owning the battery entities/devices.
        inverter_serial: Parent inverter serial number.
        key_migrations: Mapping of legacy battery key → canonical battery key.

    Returns:
        The legacy keys whose migration completed (including no-op keys with
        nothing to migrate).  Keys that failed or were deferred are absent so
        the caller can retry them instead of marking them done.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    entries = er.async_entries_for_config_entry(entity_registry, entry_id)
    migrated: list[str] = []

    for old_key, new_key in key_migrations.items():
        try:
            if _migrate_single_key(
                hass,
                entity_registry,
                device_registry,
                entries,
                inverter_serial,
                old_key,
                new_key,
            ):
                migrated.append(old_key)
        except Exception:
            # A registry failure must not kill the refresh; the remaining
            # keys are still processed and this one is retried later.
            _LOGGER.exception(
                "Battery key migration %s -> %s for inverter %s failed",
                old_key,
                new_key,
                inverter_serial,
            )
    return migrated


@callback
def _migrate_single_key(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    entries: list[er.RegistryEntry],
    inverter_serial: str,
    old_key: str,
    new_key: str,
) -> bool:
    """Migrate one legacy battery key.  Returns True when complete/no-op."""
    old_prefix = f"{inverter_serial}_{old_key}_"
    new_prefix = f"{inverter_serial}_{new_key}_"

    matches = [e for e in entries if e.unique_id.startswith(old_prefix)]
    old_device = device_registry.async_get_device(identifiers={(DOMAIN, old_key)})
    if not matches and old_device is None:
        # Nothing to migrate — report success so the caller stops rescanning.
        return True

    # Live-entity safety: renaming or removing a registry row whose entity
    # object is currently instantiated strands a stale object on the
    # entity_id (the platform then refuses the canonical replacement).
    # Defer — after the next restart/reload the migration runs during the
    # first refresh, before any battery entity instantiates.
    live = [e.entity_id for e in matches if hass.states.get(e.entity_id) is not None]
    if live:
        _LOGGER.warning(
            "Deferring battery key migration %s -> %s for inverter %s: "
            "%d positional entities are currently live (e.g. %s). The "
            "migration completes automatically on the next Home Assistant "
            "restart or integration reload",
            old_key,
            new_key,
            inverter_serial,
            len(live),
            live[0],
        )
        return False

    new_device = device_registry.async_get_device(identifiers={(DOMAIN, new_key)})

    if old_device is not None and new_device is None:
        # Canonical device doesn't exist yet: re-identify the positional
        # device in place.  This preserves the device UUID (device-based
        # automations, device triggers, dashboard cards) plus area, user-set
        # name and labels — and the entities keep their device link.
        device_registry.async_update_device(
            old_device.id, new_identifiers={(DOMAIN, new_key)}
        )
        _LOGGER.info(
            "Re-identified battery device %s as %s in place (device id %s)",
            old_key,
            new_key,
            old_device.id,
        )
        _migrate_entities(entity_registry, matches, old_prefix, new_prefix, None)
        return True

    if old_device is not None and new_device is not None:
        # Duplicate path: the canonical device already exists (cloud-era
        # identity with the user's history).  Backfill customizations from
        # the positional device where the canonical's own value is unset —
        # canonical customizations win, positional ones aren't silently lost.
        _backfill_device_customizations(device_registry, old_device, new_device)

    target_device_id = new_device.id if new_device is not None else None
    _migrate_entities(
        entity_registry, matches, old_prefix, new_prefix, target_device_id
    )

    if old_device is not None:
        device_registry.async_remove_device(old_device.id)
        _LOGGER.info(
            "Removed legacy positional battery device %s (migrated to %s)",
            old_key,
            new_key,
        )
    return True


@callback
def _migrate_entities(
    entity_registry: er.EntityRegistry,
    matches: list[er.RegistryEntry],
    old_prefix: str,
    new_prefix: str,
    target_device_id: str | None,
) -> None:
    """Rename matched entities to the canonical prefix, removing duplicates.

    A positional entity whose canonical unique_id already exists is a
    duplicate of a surviving cloud-era entity: the positional row is removed
    and its own accumulated history/long-term statistics are deleted (not
    merged) — the canonical entity's history is what survives.
    """
    for entity in matches:
        new_unique_id = new_prefix + entity.unique_id[len(old_prefix) :]
        if entity_registry.async_get_entity_id(entity.domain, DOMAIN, new_unique_id):
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed duplicate positional battery entity %s "
                "(canonical unique_id %s already registered; the positional "
                "entity's own history is deleted, not merged)",
                entity.entity_id,
                new_unique_id,
            )
            continue
        if target_device_id is not None:
            entity_registry.async_update_entity(
                entity.entity_id,
                new_unique_id=new_unique_id,
                device_id=target_device_id,
            )
        else:
            entity_registry.async_update_entity(
                entity.entity_id, new_unique_id=new_unique_id
            )
        _LOGGER.info(
            "Migrated battery entity %s unique_id: %s -> %s",
            entity.entity_id,
            entity.unique_id,
            new_unique_id,
        )


@callback
def _backfill_device_customizations(
    device_registry: dr.DeviceRegistry,
    old_device: dr.DeviceEntry,
    new_device: dr.DeviceEntry,
) -> None:
    """Copy area/name/labels from the positional device where unset."""
    area_id = new_device.area_id or old_device.area_id
    name_by_user = new_device.name_by_user or old_device.name_by_user
    labels = new_device.labels or old_device.labels
    if (area_id, name_by_user, labels) != (
        new_device.area_id,
        new_device.name_by_user,
        new_device.labels,
    ):
        device_registry.async_update_device(
            new_device.id,
            area_id=area_id,
            name_by_user=name_by_user,
            labels=labels,
        )
        _LOGGER.info(
            "Backfilled area/name/label customizations from the positional "
            "battery device onto %s",
            new_device.id,
        )
