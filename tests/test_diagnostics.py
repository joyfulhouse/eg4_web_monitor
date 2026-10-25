"""Tests for the diagnostics platform (issue-reporting hardening).

The download exists so a bug report can show what the cloud or local
transport returned without a capture round-trip. These tests pin the
promises the bug-report template makes about it: credentials, hosts,
plant/station identity and location fields are redacted; device, dongle
and battery serial numbers are aliased consistently everywhere they
appear — as dict keys, as values (string OR int), lowercased inside
derived strings, and embedded inside longer strings such as unique IDs —
and the dump degrades to a config-only snapshot on a failed-setup entry
instead of raising.
"""

import json
import threading
from unittest.mock import patch

from importlib.metadata import PackageNotFoundError

import pytest
from homeassistant.components import diagnostics as ha_diagnostics
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor import async_setup
from custom_components.eg4_web_monitor import diagnostics as eg4_diagnostics
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.battery_bus import BatteryBusCoordinator
from custom_components.eg4_web_monitor.diagnostics import (
    async_get_config_entry_diagnostics,
)

SERIAL = "1234567890"
DONGLE_SERIAL = "SYNTH10007"
PLANT_ID = "12345"


@pytest.fixture
def entry(hass):
    """Config entry with credentials, a host and local serials to protect."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - 123 Private Street",
        data={
            "username": "real_user",
            "password": "real_pass",
            "base_url": "https://monitor.eg4electronics.com",
            "plant_id": PLANT_ID,
            "plant_name": "My Home Address",
            "connection_type": "http",
            "modbus_host": "10.0.0.42",
            "inverter_serial": SERIAL,
            "dongle_serial": DONGLE_SERIAL,
        },
        options={"sensor_update_interval": 20},
    )
    entry.add_to_hass(hass)
    return entry


def _make_coordinator(hass, entry):
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.client = None  # never used by diagnostics
    coordinator.data = {
        "devices": {
            SERIAL: {
                "sensors": {
                    "soc": 40,
                    "battery_serial_number": "BATSN001",
                    # The plant id embedded in a longer number must NOT be
                    # replaced (digit-boundary guard).
                    "energy_reading": 3123456,
                },
                "unique_id": f"{SERIAL}_state_of_charge",
                # Letter-bearing serials appear lowercased in derived strings.
                "entity_id": f"sensor.eg4_{DONGLE_SERIAL.lower()}_soc",
                "batteries": {
                    "BATSN002": {"sensors": {"battery_sn": "BATSN002", "soc": 41}}
                },
            }
        },
        "station": {
            "plant_id": int(PLANT_ID),  # int-typed, as the cloud returns it
            "name": "123 Private Street",
            "address": "123 Private Street, Springfield",
            "timezone": "GMT -8",
        },
    }
    return coordinator


async def _diagnostics(hass, entry):
    coordinator = _make_coordinator(hass, entry)
    entry.runtime_data = coordinator
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_secrets_redacted_and_serials_aliased(hass, entry):
    """Credentials/hosts/plant identity redacted; no real serial anywhere."""
    result = await _diagnostics(hass, entry)
    dump = json.dumps(result)

    for secret in (
        "real_user",
        "real_pass",
        "My Home Address",
        "10.0.0.42",
        "Private Street",  # entry title is omitted, station name/address redacted
    ):
        assert secret not in dump
    # Device, dongle AND battery serials — battery serials appear both as
    # `batteries` dict keys and as serial-valued sensor fields; the dongle
    # serial also appears lowercased inside an entity ID.
    for serial in (
        SERIAL,
        DONGLE_SERIAL,
        DONGLE_SERIAL.lower(),
        "BATSN001",
        "BATSN002",
    ):
        assert serial not in dump
    assert "**REDACTED**" in dump


async def test_alias_is_consistent_across_keys_and_embedded_strings(hass, entry):
    """The same serial gets the same alias as a dict key and inside a string."""
    result = await _diagnostics(hass, entry)

    devices = result["coordinator"]["data"]["devices"]
    (alias_key,) = devices.keys()
    assert alias_key.startswith("SN_")
    # The unique_id used the serial as a prefix; the alias must replace it
    # there too, with the identical alias.
    assert devices[alias_key]["unique_id"] == f"{alias_key}_state_of_charge"
    # Entry data's inverter_serial gets an alias from the same map.
    assert result["entry"]["data"]["inverter_serial"].startswith("SN_")


async def test_plant_id_aliased_including_int_but_not_embedded_digits(hass, entry):
    """PLANT_1 replaces the plant id as str and int; longer numbers survive."""
    result = await _diagnostics(hass, entry)

    station = result["coordinator"]["data"]["station"]
    assert station["plant_id"] == "PLANT_1"  # was int-typed
    assert result["entry"]["data"]["plant_id"] == "PLANT_1"
    # 3123456 contains "12345" but is a different number — must be untouched.
    devices = result["coordinator"]["data"]["devices"]
    (alias_key,) = devices.keys()
    assert devices[alias_key]["sensors"]["energy_reading"] == 3123456
    # Useful non-identifying station fields survive.
    assert station["timezone"] == "GMT -8"


async def test_failed_setup_entry_returns_config_only_snapshot(hass, entry):
    """No runtime_data (setup failed / unloaded) -> config-only dump, no raise."""
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"] is None
    dump = json.dumps(result)
    for secret in ("real_user", "real_pass", SERIAL, DONGLE_SERIAL):
        assert secret not in dump
    # Entry serials still alias without a coordinator inventory.
    assert result["entry"]["data"]["inverter_serial"].startswith("SN_")


async def test_structure_and_versions(hass, entry):
    """The dump is JSON-serializable and carries the essentials."""
    result = await _diagnostics(hass, entry)

    json.dumps(result)  # must not raise
    assert result["coordinator"]["connection_type"] == "http"
    assert result["coordinator"]["device_count"] == 1
    assert result["versions"]["pylxpweb"] not in ("", None)
    assert result["entry"]["options"] == {"sensor_update_interval": 20}


@pytest.mark.parametrize("missing_package", [False, True])
async def test_package_metadata_lookup_runs_outside_event_loop(
    hass, entry, missing_package
):
    """Metadata disk reads must not block HA, including missing-package lookup."""
    loop_thread = threading.get_ident()

    def lookup(package):
        assert threading.get_ident() != loop_thread
        assert package == "pylxpweb"
        if missing_package:
            raise PackageNotFoundError(package)
        return "0.10.0b13"

    with patch("custom_components.eg4_web_monitor.diagnostics.version", new=lookup):
        result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["versions"]["pylxpweb"] == (
        "unknown" if missing_package else "0.10.0b13"
    )


async def test_unknown_objects_become_type_placeholders(hass, entry):
    """repr() is never emitted — a repr can embed hosts or credentials."""

    class _Secretive:
        def __repr__(self) -> str:  # pragma: no cover - the point is it never runs
            return "ClientConnectorError(host='10.0.0.42', password='real_pass')"

    coordinator = _make_coordinator(hass, entry)
    coordinator.data["devices"][SERIAL]["transport"] = _Secretive()
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)
    dump = json.dumps(result)
    assert "10.0.0.42" not in dump
    assert "real_pass" not in dump
    assert "<_Secretive>" in dump


async def test_inventory_changed_during_metadata_lookup_is_redacted(hass, entry):
    """An inventory refresh during the executor wait cannot leak new serials."""
    coordinator = _make_coordinator(hass, entry)
    entry.runtime_data = coordinator
    new_serial = "NEWDEV1234"
    new_battery = "NEWBAT1234"

    async def refresh_during_lookup(target, *args):
        coordinator.data["devices"] = {
            new_serial: {
                "serial": new_serial,
                "batteries": {new_battery: {"battery_sn": new_battery}},
            }
        }
        return "0.10.0b13"

    with patch.object(hass, "async_add_executor_job", new=refresh_during_lookup):
        result = await async_get_config_entry_diagnostics(hass, entry)

    dump = json.dumps(result)
    assert new_serial not in dump
    assert new_battery not in dump
    assert result["coordinator"]["device_count"] == 1
    device_key = next(iter(result["coordinator"]["data"]["devices"]))
    assert device_key.startswith("SN_")


@pytest.mark.parametrize("loaded", [False, True])
async def test_nested_transport_identity_redacted_without_inventory(
    hass, entry, loaded
):
    """Failed setup must not expose configured hosts or generic serial fields."""
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "local_transports": [
                {"host": "192.0.2.101", "serial": "CONFIG001A", "port": 502},
                {"host": "private.example", "serial": "CONFIG002B", "port": 8000},
            ],
        },
        options={"nested": {"host": "192.0.2.103", "serial": "OPTIONS003"}},
    )
    if loaded:
        entry.runtime_data = _make_coordinator(hass, entry)
        entry.runtime_data.data["devices"][SERIAL]["sensors"]["transport_host"] = (
            "192.0.2.104"
        )
    result = await async_get_config_entry_diagnostics(hass, entry)
    dump = json.dumps(result)
    for private in (
        "192.0.2.101",
        "private.example",
        "192.0.2.103",
        "192.0.2.104",
        "CONFIG001A",
        "CONFIG002B",
        "OPTIONS003",
    ):
        assert private not in dump
    assert result["entry"]["data"]["local_transports"][0]["port"] == 502


async def test_full_download_does_not_expose_legacy_repairs(hass, entry, hass_client):
    """HA snapshots all domain Repairs before invoking our diagnostics handler."""
    registry = ir.async_get(hass)
    ir.async_create_issue(
        hass,
        DOMAIN,
        "transport_link_down_LEGACY0001",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="transport_link_down",
        translation_placeholders={"serial": "LEGACY0001", "host": "192.0.2.151"},
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        "duplicate_cloud_entry_another_entry",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="duplicate_cloud_entry",
        translation_placeholders={
            "entry_title": "Private Example Station",
            "owner_title": "Private Other Station",
            "unique_id": "private@example.test_12345",
        },
    )
    registry.async_ignore(DOMAIN, "transport_link_down_LEGACY0001", True)
    assert await async_setup(hass, {})
    assert await async_setup_component(hass, "diagnostics", {})
    ha_diagnostics._register_diagnostics_platform(hass, DOMAIN, eg4_diagnostics)
    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == 200
    result = await response.json()
    dump = json.dumps(result)
    for private in (
        "LEGACY0001",
        "192.0.2.151",
        "Private Example Station",
        "Private Other Station",
        "private@example.test_12345",
    ):
        assert private not in dump
    assert len(result["issues"]) == 2
    assert result["data"]["versions"]["pylxpweb"] != "unknown"


async def test_battery_coordinator_serials_and_transport_are_private(hass):
    """Integer unit keys and numeric serial values survive the real bus shape."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "battery_bus",
            "modbus_host": "192.0.2.175",
            "battery_unit_ids": [1, 2],
        },
    )
    entry.add_to_hass(hass)
    coordinator = BatteryBusCoordinator(hass, entry)
    entry.runtime_data = coordinator
    coordinator.data = {
        1: {"serial_number": "BATTERY001", "voltage": 52.56},
        2: {"serial_number": 9876543210, "voltage": 52.57},
    }
    try:
        result = await async_get_config_entry_diagnostics(hass, entry)
        dump = json.dumps(result)
        for private in ("192.0.2.175", "BATTERY001", "9876543210"):
            assert private not in dump
        assert result["coordinator"]["connection_type"] == "battery_bus"
        assert result["coordinator"]["data"]["2"]["voltage"] == 52.57
    finally:
        coordinator._release_endpoint()
