"""Registered HYBRID measurements exist before delayed local data (#653)."""

import asyncio
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import Platform, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.sensor import _seed_registered_hybrid_sensor_keys


@pytest.mark.parametrize("complete_read", [True, False])
async def test_registered_hybrid_measurements_have_entities_before_local_read(
    hass, complete_read
):
    """Exercise real first refresh and platform setup with a delayed/hung poll."""
    serial = "1234567890"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "hybrid",
            "username": "test",
            "password": "test",
            "plant_id": "1",
            "dst_sync": False,
            "local_transports": [
                {
                    "serial": serial,
                    "host": "192.0.2.1",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entities = {
        key: registry.async_get_or_create(
            "sensor", DOMAIN, unique_id, config_entry=entry
        )
        for key, unique_id in {
            "inverter_power_l1": f"{serial}_inverter_power_l1",
            "battery_bank_soc": f"{serial}_battery_bank_battery_bank_soc",
        }.items()
    }
    snapshot = {
        "devices": {
            serial: {
                "type": "inverter",
                "model": "FlexBOSS21",
                "serial": serial,
                "sensors": {"pv_total_power": 100},
                "batteries": {},
                "features": {
                    "inverter_family": "EG4_HYBRID",
                    "supports_split_phase": True,
                    "supports_three_phase": False,
                },
            }
        },
        "parameters": {serial: {}},
    }
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    read_started = asyncio.Event()
    release_read = asyncio.Event()
    calls = 0

    async def update():
        nonlocal calls
        calls += 1
        result = deepcopy(snapshot)
        if calls > 1:
            read_started.set()
            await release_read.wait()
            result["devices"][serial]["sensors"].update(
                inverter_power_l1=1200, battery_bank_soc=62
            )
        return result

    with (
        patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.eg4_web_monitor.OTHER_PLATFORMS", []),
        patch("custom_components.eg4_web_monitor.PLATFORMS", [Platform.SENSOR]),
        patch.object(coordinator, "_async_update_data", side_effect=update),
    ):
        try:
            async with asyncio.timeout(30):
                assert await hass.config_entries.async_setup(entry.entry_id)
            for entity in entities.values():
                assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN
            refresh = hass.async_create_task(coordinator.async_refresh())
            async with asyncio.timeout(30):
                await read_started.wait()
            if complete_read:
                release_read.set()
                await refresh
                await hass.async_block_till_done()
                assert (
                    hass.states.get(entities["inverter_power_l1"].entity_id).state
                    == "1200"
                )
                assert (
                    hass.states.get(entities["battery_bank_soc"].entity_id).state
                    == "62"
                )
                assert (
                    len(
                        [
                            e
                            for e in registry.entities.values()
                            if e.unique_id == f"{serial}_inverter_power_l1"
                        ]
                    )
                    == 1
                )
            else:
                for entity in entities.values():
                    assert hass.states.get(entity.entity_id).state == STATE_UNKNOWN
                refresh.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await refresh
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
            await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "case", ["cloud", "local", "other_entry", "excluded_family", "live"]
)
async def test_registry_seed_respects_ownership_capabilities_and_live_data(hass, case):
    """Registry history cannot override current transport, family, or readings."""
    entry = MockConfigEntry(domain=DOMAIN)
    other = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    serial = "1234567890"
    # Per-leg EPS apparent power is excluded for EG4_HYBRID.
    key = "eps_apparent_power_l1" if case == "excluded_family" else "inverter_power_l1"
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_{key}",
        config_entry=other if case == "other_entry" else entry,
    )
    sensors = {key: 456} if case == "live" else {}
    coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
    coordinator.has_http_api.return_value = case != "local"
    coordinator.has_configured_local_transport.return_value = case != "cloud"
    coordinator.data = {
        "devices": {
            serial: {
                "type": "inverter",
                "features": {"inverter_family": "EG4_HYBRID"},
                "sensors": sensors,
            }
        }
    }
    _seed_registered_hybrid_sensor_keys(hass, entry, coordinator)
    assert sensors == ({key: 456} if case == "live" else {})
