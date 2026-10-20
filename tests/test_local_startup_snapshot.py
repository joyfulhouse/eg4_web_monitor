"""LOCAL startup publishes static entities without waiting for a gateway (#653)."""

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest
from homeassistant.const import Platform, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


@pytest.mark.parametrize("complete_read", [True, False], ids=["snapshot", "hung-read"])
async def test_local_first_refresh_creates_sensors_before_measurements(
    hass, complete_read
):
    """Real HA first refresh/platform forwarding also works if a read never ends."""
    serial = "1234567890"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": serial,
                    "host": "192.0.2.1",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, serial)},
        name="FlexBOSS21",
    )
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    # Isolate measurement startup from the independent deferred parameter loader.
    coordinator._local_parameters_loaded = True
    read_started = asyncio.Event()
    release_read = asyncio.Event()

    async def read_device(config, processed, availability):
        read_started.set()
        await release_read.wait()
        device = deepcopy(coordinator.data["devices"][serial])
        device["sensors"]["pv1_voltage"] = 320.5
        device["sensors"]["battery_bank_soc"] = 62
        processed["devices"][serial] = device
        availability[serial] = True

    with (
        patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.eg4_web_monitor.OTHER_PLATFORMS", []),
        patch("custom_components.eg4_web_monitor.PLATFORMS", [Platform.SENSOR]),
        patch.object(
            coordinator, "_process_single_local_device", side_effect=read_device
        ),
    ):
        try:
            async with asyncio.timeout(30):
                assert await hass.config_entries.async_setup(entry.entry_id)
            registry = er.async_get(hass)
            entities = {
                key: next(
                    e
                    for e in registry.entities.values()
                    if e.config_entry_id == entry.entry_id and e.unique_id.endswith(key)
                )
                for key in ("pv1_voltage", "battery_bank_soc")
            }
            for entity in entities.values():
                assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN

            # Trigger the actual coordinator refresh, with its real debouncer
            # already exercised during async_config_entry_first_refresh().
            refresh = hass.async_create_task(coordinator.async_refresh())
            async with asyncio.timeout(30):
                await read_started.wait()
            for entity in entities.values():
                assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN
            if complete_read:
                release_read.set()
                async with asyncio.timeout(30):
                    await refresh
                assert (
                    hass.states.get(entities["pv1_voltage"].entity_id).state == "320.5"
                )
                assert (
                    hass.states.get(entities["battery_bank_soc"].entity_id).state
                    == "62"
                )
            else:
                refresh.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await refresh
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
            await coordinator.async_shutdown()
