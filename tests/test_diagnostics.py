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

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.diagnostics import (
    async_get_config_entry_diagnostics,
)

SERIAL = "1234567890"
DONGLE_SERIAL = "BA12345678"
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
