"""Persistent registry topology prevents startup statistics eligibility gaps (#664)."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor import _async_cleanup_removed_registry_devices
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor


async def _add(hass, entry, key="consumption"):
    with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.update_interval = None
    coordinator.last_update_success = True
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.data = {
        "devices": {"INV": {"type": "inverter", "sensors": {key: 19.0}}}
    }
    sensor = EG4InverterSensor(coordinator, "INV", key)
    sensor.entity_id = "sensor.topology_consumption"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([sensor])
    return coordinator, sensor, platform


def _entry(hass, configured=False):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "local",
            "local_transports": [{"serial": "GB", "is_gridboss": True}]
            if configured
            else [],
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize("key", ["consumption", "consumption_lifetime"])
@pytest.mark.parametrize(
    "known",
    ["registered", "legacy_registered", "configured", "unrelated", "inverter_only"],
)
async def test_first_state_uses_known_topology(hass, key, known):
    entry = _entry(hass, configured=known == "configured")
    if known in {"registered", "legacy_registered", "unrelated"}:
        owner = entry
        if known == "unrelated":
            owner = _entry(hass)
        dr.async_get(hass).async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={(DOMAIN, "GB")},
            model="GridBOSS" if known == "legacy_registered" else "Future MID Model",
            model_id="eg4_web_monitor:gridboss"
            if known != "legacy_registered"
            else None,
        )
    coordinator, sensor, _ = await _add(hass, entry, key)
    state = hass.states.get(sensor.entity_id)
    assert ("state_class" not in state.attributes) == (
        known in {"registered", "legacy_registered", "configured"}
    )
    await coordinator.async_shutdown()


async def test_explicit_registry_removal_and_reload_reset_exclusion(hass):
    """A transient absence retains exclusion; deliberate deletion resets on reload."""
    entry = _entry(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "GB")},
        model_id="eg4_web_monitor:gridboss",
    )
    coordinator, sensor, platform = await _add(hass, entry)
    assert "state_class" not in hass.states.get(sensor.entity_id).attributes
    await platform.async_reset()
    await coordinator.async_shutdown()
    coordinator, sensor, platform = await _add(hass, entry)
    assert "state_class" not in hass.states.get(sensor.entity_id).attributes

    # The integration's existing deletion hook independently guards whether a
    # device can be removed; this exercises the accepted registry mutation.
    registry.async_remove_device(device.id)
    assert sensor.state_class is None  # Remains latched until deliberate reload.
    await platform.async_reset()
    await coordinator.async_shutdown()
    coordinator, sensor, _ = await _add(hass, entry)
    assert (
        hass.states.get(sensor.entity_id).attributes["state_class"]
        == "total_increasing"
    )
    await coordinator.async_shutdown()


def test_gridboss_device_info_persists_role(hass):
    entry = _entry(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "devices": {"GB": {"type": "gridboss", "model": "Future MID Model"}}
    }
    assert coordinator.get_device_info("GB")["model_id"] == "eg4_web_monitor:gridboss"


@pytest.mark.parametrize(
    "mode,configured,excluded",
    [
        ("http", False, True),
        ("hybrid", False, True),
        ("local", True, True),
        ("local", False, False),
    ],
)
async def test_setup_cleanup_preserves_unconfirmed_cloud_topology(
    hass, mode, configured, excluded
):
    """Only deliberate LOCAL config removal may prune known CT topology at setup."""
    entry = _entry(hass, configured=configured)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "connection_type": mode,
            "username": "test",
            "password": "test",
        },
    )
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "GB")},
        serial_number="GB",
        model="GridBOSS",
    )
    with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "devices": {"INV": {"type": "inverter", "sensors": {"consumption": 19.0}}}
    }
    _async_cleanup_removed_registry_devices(hass, entry, coordinator)
    assert (registry.async_get(device.id) is not None) == excluded
    coordinator, sensor, _ = await _add(hass, entry)
    assert (
        "state_class" not in hass.states.get(sensor.entity_id).attributes
    ) == excluded
    await coordinator.async_shutdown()
