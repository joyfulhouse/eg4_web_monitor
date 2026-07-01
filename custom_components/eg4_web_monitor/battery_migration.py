"""Registry migration for canonical battery identity (#252).

Before #252 the three connection modes derived different battery keys for the
same physical battery: CLOUD used the cloud ``batteryKey``
(``{inv}-{batterySn}`` once cleaned), while HYBRID and LOCAL used positional
keys (``{inv}-01..NN``).  The battery key is the battery *device* identifier
and is embedded in every battery entity unique_id
(``{inverterSn}_{batteryKey}_{suffix}``), so switching modes re-keyed every
battery that reports a real serial — duplicating devices and orphaning
history.

This module renames legacy positional registry entries to the canonical
serial-based keys once the coordinator learns the mapping:

- entity unique_ids are renamed in place (entity_id and history preserved);
- when the canonical unique_id already exists (a cloud→hybrid install where
  the cloud-era entities survived alongside the positional duplicates), the
  positional duplicate is removed and the canonical entity resumes updating;
- the canonical device inherits area/name/label customizations from the
  positional device, which is then removed.
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
) -> None:
    """Migrate legacy positional battery registry entries to canonical keys.

    Args:
        hass: Home Assistant instance.
        entry_id: Config entry id owning the battery entities/devices.
        inverter_serial: Parent inverter serial number.
        key_migrations: Mapping of legacy battery key → canonical battery key.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    entries = er.async_entries_for_config_entry(entity_registry, entry_id)

    for old_key, new_key in key_migrations.items():
        old_prefix = f"{inverter_serial}_{old_key}_"
        new_prefix = f"{inverter_serial}_{new_key}_"

        matches = [e for e in entries if e.unique_id.startswith(old_prefix)]
        old_device = device_registry.async_get_device(identifiers={(DOMAIN, old_key)})
        if not matches and old_device is None:
            continue

        # Resolve (or pre-create) the canonical device so renamed entities can
        # be re-pointed before the positional device is removed.  A bare
        # pre-created device is completed by the entity platform when the
        # battery entity registers with full device_info.
        new_device = device_registry.async_get_device(identifiers={(DOMAIN, new_key)})
        if new_device is None:
            new_device = device_registry.async_get_or_create(
                config_entry_id=entry_id,
                identifiers={(DOMAIN, new_key)},
            )
            if old_device is not None and (
                old_device.area_id or old_device.name_by_user or old_device.labels
            ):
                # Carry user customizations from the positional device.
                device_registry.async_update_device(
                    new_device.id,
                    area_id=old_device.area_id,
                    name_by_user=old_device.name_by_user,
                    labels=old_device.labels,
                )
        new_device_id = new_device.id

        for entity in matches:
            new_unique_id = new_prefix + entity.unique_id[len(old_prefix) :]
            if entity_registry.async_get_entity_id(
                entity.domain, DOMAIN, new_unique_id
            ):
                # The canonical entity already exists (cloud-era identity with
                # the user's history) — the positional entry is a duplicate.
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.info(
                    "Removed duplicate positional battery entity %s "
                    "(canonical unique_id %s already registered)",
                    entity.entity_id,
                    new_unique_id,
                )
            else:
                entity_registry.async_update_entity(
                    entity.entity_id,
                    new_unique_id=new_unique_id,
                    device_id=new_device_id,
                )
                _LOGGER.info(
                    "Migrated battery entity %s unique_id: %s -> %s",
                    entity.entity_id,
                    entity.unique_id,
                    new_unique_id,
                )

        if old_device is not None:
            device_registry.async_remove_device(old_device.id)
            _LOGGER.info(
                "Removed legacy positional battery device %s (migrated to %s)",
                old_key,
                new_key,
            )
