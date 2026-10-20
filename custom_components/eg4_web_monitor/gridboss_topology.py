"""Persistent GridBOSS topology shared by statistics source decisions."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_LOCAL_TRANSPORTS, DOMAIN

GRIDBOSS_MODEL_ID = "eg4_web_monitor:gridboss"


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
