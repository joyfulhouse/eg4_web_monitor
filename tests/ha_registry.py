"""Registry fixtures that respect HA's config-entry-scoped device identity."""

from homeassistant.helpers import device_registry as dr


def get_registry_device(registry, identifier, config_entry_id):
    lookup = getattr(registry, "async_get_device_by_identifier", None)
    if lookup is not None:
        return lookup(identifier, config_entry_id)
    device = registry.async_get_device(identifiers={identifier})
    if device is not None and config_entry_id in device.config_entries:
        return device
    return None


def registry_parent_link(registry, identifier, config_entry_id):
    if hasattr(dr, "async_get_device_id_by_identifier"):
        parent = get_registry_device(registry, identifier, config_entry_id)
        assert parent is not None, "register fixture parents before children"
        return {"via_device_id": parent.id}
    return {"via_device": identifier}
