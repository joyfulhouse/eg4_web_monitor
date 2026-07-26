"""Tests for per-device removal (async_remove_config_entry_device, #174)."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import async_remove_config_entry_device
from custom_components.eg4_web_monitor.const import DOMAIN

LIVE_INVERTER = "1234567890"
LIVE_GRIDBOSS = "9876543210"
PLACEHOLDER_INVERTER = "5555555555"
GONE_SERIAL = "1111111111"


def _device_entry(*identifiers: str) -> MagicMock:
    """Build a device-registry entry mock carrying DOMAIN identifiers."""
    device = MagicMock()
    device.identifiers = {(DOMAIN, identifier) for identifier in identifiers}
    return device


@pytest.fixture
def coordinator():
    """Coordinator mock with a representative healthy device table."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.plant_id = "12345"
    coordinator.data = {
        "devices": {
            LIVE_INVERTER: {
                "type": "inverter",
                "batteries": {
                    f"{LIVE_INVERTER}-01": {},
                    f"{LIVE_INVERTER}-02": {},
                },
            },
            LIVE_GRIDBOSS: {"type": "gridboss"},
            "parallel_group_a": {"type": "parallel_group"},
            # LOCAL-mode placeholder cycle: device present, no battery
            # data read yet (empty dict, not authoritative — #217).
            PLACEHOLDER_INVERTER: {"type": "inverter", "batteries": {}},
        },
        "station": {"name": "Test Station"},
    }
    return coordinator


@pytest.fixture
def entry(coordinator):
    """Config entry wired to the mock coordinator."""
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id="remove_test_entry")
    config_entry.runtime_data = coordinator
    return config_entry


async def test_stale_inverter_removable(hass: HomeAssistant, entry):
    """A serial absent from coordinator data can be removed."""
    assert (
        await async_remove_config_entry_device(hass, entry, _device_entry(GONE_SERIAL))
        is True
    )


async def test_live_devices_refused(hass: HomeAssistant, entry):
    """Currently-provided devices are refused."""
    for identifier in (
        LIVE_INVERTER,
        LIVE_GRIDBOSS,
        "parallel_group_a",
        PLACEHOLDER_INVERTER,
    ):
        assert (
            await async_remove_config_entry_device(
                hass, entry, _device_entry(identifier)
            )
            is False
        ), identifier


async def test_stale_serial_based_parallel_group_removable(hass: HomeAssistant, entry):
    """Legacy serial-based PG ids not in the device table can be removed."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry("parallel_group_4524850115")
        )
        is True
    )


async def test_live_battery_refused(hass: HomeAssistant, entry):
    """A battery key present in its parent's batteries dict is refused."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{LIVE_INVERTER}-01")
        )
        is False
    )


async def test_stale_battery_removable(hass: HomeAssistant, entry):
    """A battery gone from a parent with authoritative battery data can go."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{LIVE_INVERTER}-03")
        )
        is True
    )


async def test_battery_refused_during_placeholder_cycle(hass: HomeAssistant, entry):
    """Empty parent batteries dict is not authoritative absence (#217)."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{PLACEHOLDER_INVERTER}-01")
        )
        is False
    )


async def test_battery_of_gone_inverter_removable(hass: HomeAssistant, entry):
    """Battery keys of a departed inverter can be removed."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{GONE_SERIAL}-01")
        )
        is True
    )


async def test_battery_bank_follows_parent(hass: HomeAssistant, entry):
    """Bank of a live parent is refused; bank of a gone parent removable."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{LIVE_INVERTER}_battery_bank")
        )
        is False
    )
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry(f"{GONE_SERIAL}_battery_bank")
        )
        is True
    )


async def test_live_station_refused(hass: HomeAssistant, entry):
    """The station device is refused while station data is provided."""
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry("station_12345")
        )
        is False
    )


async def test_stale_station_removable(hass: HomeAssistant, entry, coordinator):
    """A station device with no station data (e.g. after moving to LOCAL)."""
    del coordinator.data["station"]
    assert (
        await async_remove_config_entry_device(
            hass, entry, _device_entry("station_12345")
        )
        is True
    )


async def test_refused_when_update_failed(hass: HomeAssistant, entry, coordinator):
    """A failed update cycle refuses every removal, even stale devices."""
    coordinator.last_update_success = False
    assert (
        await async_remove_config_entry_device(hass, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_refused_when_device_table_empty(hass: HomeAssistant, entry, coordinator):
    """An empty device table is degraded state, not universal staleness."""
    coordinator.data = {"devices": {}}
    assert (
        await async_remove_config_entry_device(hass, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_refused_without_runtime_data(hass: HomeAssistant):
    """An entry that never set up (no runtime_data) refuses removal."""
    never_loaded = MockConfigEntry(domain=DOMAIN, entry_id="never_loaded")
    assert (
        await async_remove_config_entry_device(
            hass, never_loaded, _device_entry(GONE_SERIAL)
        )
        is False
    )
