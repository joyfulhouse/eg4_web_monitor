"""Persistent GridBOSS topology shared by statistics source decisions."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_LOCAL_TRANSPORTS, DOMAIN

GRIDBOSS_MODEL_ID = "eg4_web_monitor:gridboss"
GRIDBOSS_GROUP_MODEL_ID = "eg4_web_monitor:gridboss_group"
INVERTER_GROUP_MODEL_ID = "eg4_web_monitor:inverter_group"


def get_topology_device(
    registry: dr.DeviceRegistry, config_entry_id: str, identifier: str
) -> dr.DeviceEntry | None:
    """Use the supported HA registry's entry-scoped device identity."""
    return registry.async_get_device_by_identifier(
        (DOMAIN, identifier), config_entry_id
    )


def is_registered_gridboss(device: dr.DeviceEntry) -> bool:
    """Recognize our role marker and historical library-default registry model."""
    return (device.model_id == GRIDBOSS_MODEL_ID or device.model == "GridBOSS") and any(
        domain == DOMAIN for domain, _ in device.identifiers
    )


def entry_has_known_gridboss(hass: HomeAssistant, entry: Any) -> bool:
    """Retain known topology until explicit config/registry removal."""
    return any(
        config.get("is_gridboss")
        for config in entry.data.get(CONF_LOCAL_TRANSPORTS, [])
    ) or any(
        is_registered_gridboss(device)
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    )


def group_consumption_source(
    coordinator: Any,
    group_id: str,
    *,
    has_mid: bool,
    previous_source: str | None,
    mid_serial: str | None = None,
) -> str:
    """Keep a group's meter source through reload and incomplete discovery.

    An unclassified legacy group in a known GridBOSS entry cannot safely claim
    inverter consumption before its topology returns. Explicit GridBOSS removal
    resets the registry decision on reload; the runtime CT latch lasts the run.
    """
    registry = dr.async_get(coordinator.hass)
    if has_mid and mid_serial:
        mid = get_topology_device(registry, coordinator.entry.entry_id, mid_serial)
        if mid is None or mid.config_entry_id == coordinator.entry.entry_id:
            # Association is topology evidence even when the first data read
            # fails before any GridBOSS entity can register its device.
            registry.async_get_or_create(
                config_entry_id=coordinator.entry.entry_id,
                identifiers={(DOMAIN, mid_serial)},
                serial_number=mid_serial,
                model_id=GRIDBOSS_MODEL_ID,
            )
    device = get_topology_device(registry, coordinator.entry.entry_id, group_id)
    may_persist = device is None or device.config_entry_id == coordinator.entry.entry_id
    if not may_persist:
        # Group identifiers predate entry scoping; never borrow or overwrite a
        # foreign/shared record's source classification.
        device = None
    known_gridboss = entry_has_known_gridboss(coordinator.hass, coordinator.entry)
    if has_mid or previous_source == "gridboss":
        source = "gridboss"
    elif known_gridboss:
        if device is not None and device.model_id == INVERTER_GROUP_MODEL_ID:
            source = "inverter"
        elif device is not None and device.model_id == GRIDBOSS_GROUP_MODEL_ID:
            source = "gridboss"
        elif _known_gridbosses_associated_elsewhere(coordinator, group_id):
            source = "inverter"
        else:
            source = "gridboss_pending"
    else:
        source = "inverter"

    model_id = {
        "gridboss": GRIDBOSS_GROUP_MODEL_ID,
        "inverter": INVERTER_GROUP_MODEL_ID,
    }.get(source)
    if (
        may_persist
        and model_id is not None
        and (device is None or device.model_id != model_id)
    ):
        # Persist even when missing CT readings prevent consumption entity setup.
        registry.async_get_or_create(
            config_entry_id=coordinator.entry.entry_id,
            identifiers={(DOMAIN, group_id)},
            model_id=model_id,
        )
        # A prior device-info cache must not overwrite the newly observed role.
        cache = getattr(coordinator, "_device_info_cache", None)
        if isinstance(cache, dict):
            cache.pop(group_id, None)
    return source


def _known_gridbosses_associated_elsewhere(coordinator: Any, group_id: str) -> bool:
    """Use positive cloud associations to resolve a legacy mixed-entry group."""
    if coordinator.connection_type == "local" or coordinator.station is None:
        return False
    known = {
        str(config["serial"])
        for config in coordinator.entry.data.get(CONF_LOCAL_TRANSPORTS, [])
        if config.get("is_gridboss") and config.get("serial")
    }
    for device in dr.async_entries_for_config_entry(
        dr.async_get(coordinator.hass), coordinator.entry.entry_id
    ):
        if is_registered_gridboss(device):
            known.update(
                identifier
                for domain, identifier in device.identifiers
                if domain == DOMAIN
            )
    associated_elsewhere = {
        str(mid.serial_number)
        for group in coordinator.station.parallel_groups
        if (mid := getattr(group, "mid_device", None)) is not None
        and f"parallel_group_{group.name.lower()}" != group_id
    }
    associated_elsewhere.update(
        str(mid.serial_number)
        for mid in getattr(coordinator.station, "standalone_mid_devices", [])
    )
    return bool(known) and known <= associated_elsewhere
