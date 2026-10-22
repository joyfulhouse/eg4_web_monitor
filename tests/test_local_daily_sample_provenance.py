"""LOCAL daily guards follow accepted snapshots, not HA publication time (#666)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pylxpweb.provenance import EnergyProvenance
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.energy_provenance import local_daily_sample_times
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor


def provenance(at, *fields):
    return {
        field: EnergyProvenance(source="local", source_id="test:local", acquired_at=at)
        for field in fields
    }


def balance_snapshot(at):
    return SimpleNamespace(
        timestamp=at,
        provenance=provenance(
            at,
            "pv_energy_today",
            "discharge_energy_today",
            "grid_import_today",
            "charge_energy_today",
            "grid_export_today",
        ),
    )


@pytest.mark.parametrize("device_type", ["inverter", "gridboss"])
@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kolkata"])
async def test_daily_expiration_requires_a_new_local_day_sample(
    hass, freezer, device_type, zone
):
    tz = ZoneInfo(zone)
    dt_util.set_default_time_zone(tz)
    first = datetime(2026, 10, 13, 23, 50, tzinfo=tz)
    freezer.move_to(first)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.update_interval = None
    coordinator.get_device_info = MagicMock(return_value=None)
    values = {"consumption": 14.3, "consumption_lifetime": 14.3}
    device = {"type": device_type, "sensors": values}

    def sample(at, daily, lifetime=14.2):
        values.update(consumption=daily, consumption_lifetime=lifetime)
        device["energy_sample_times"] = local_daily_sample_times(
            values, balance_snapshot(at)
        )
        coordinator.async_set_updated_data({"devices": {"serial": device}})

    sample(first, 14.3, 14.3)
    daily = EG4InverterSensor(coordinator, "serial", "consumption", device_type)
    lifetime = EG4InverterSensor(
        coordinator, "serial", "consumption_lifetime", device_type
    )
    daily.entity_id = "sensor.local_daily"
    lifetime.entity_id = "sensor.local_lifetime"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([daily, lifetime])
    assert hass.states.get(daily.entity_id).state == "14.3"

    sample(first + timedelta(minutes=5), 14.2)
    daily.async_write_ha_state()
    assert daily.native_value == 14.3
    tomorrow = datetime(2026, 10, 14, 12, 0, tzinfo=tz)
    freezer.move_to(tomorrow)
    # Re-publication and restore serialization still see yesterday's snapshot.
    daily.async_write_ha_state()
    assert daily.extra_restore_state_data.native_value == 14.3
    assert daily.native_value == 14.3

    coordinator.last_update_success = False
    daily.async_write_ha_state()
    assert hass.states.get(daily.entity_id).state == "unavailable"
    assert daily.extra_restore_state_data.native_value == 14.3
    values["consumption"] = None
    assert daily.native_value is None

    sample(tomorrow, 13.5)
    daily.async_write_ha_state()
    assert hass.states.get(daily.entity_id).state == "13.5"
    assert lifetime.native_value == 14.3
    sample(tomorrow + timedelta(minutes=1), 13.4)
    assert daily.native_value == 13.5
    sample(tomorrow + timedelta(minutes=2), 0.0)
    assert daily.native_value == 0.0
    await coordinator.async_shutdown()


@pytest.mark.parametrize("stamp", [None, "2026-10-14", datetime(2026, 10, 14)])
async def test_missing_or_untrusted_entity_timestamp_never_expires(
    hass, freezer, stamp
):
    freezer.move_to("2026-10-13T23:50:00+00:00")
    coordinator = MagicMock()
    coordinator.data = {
        "devices": {
            "serial": {
                "sensors": {"consumption": 14.3},
                "energy_sample_times": {"consumption": stamp},
            }
        }
    }
    sensor = EG4InverterSensor(coordinator, "serial", "consumption")
    assert sensor.native_value == 14.3
    freezer.move_to("2026-10-14T12:00:00+00:00")
    coordinator.data["devices"]["serial"]["sensors"]["consumption"] = 13.5
    assert sensor.native_value == 14.3


def test_snapshot_timestamp_survives_reprocessing(freezer):
    snapshot = balance_snapshot(datetime(2026, 10, 13, 23, tzinfo=UTC))
    values = {
        "consumption": 14.3,
        "consumption_lifetime": 100.0,
        "pv_total_power": 1000.0,
    }
    freezer.move_to("2026-10-14T12:00:00+00:00")
    assert local_daily_sample_times(values, snapshot) == {
        "consumption": snapshot.timestamp
    }
    assert local_daily_sample_times(values, SimpleNamespace()) == {}


def test_legacy_transport_stamp_is_not_provenance():
    assert (
        local_daily_sample_times(
            {"consumption": 1.0},
            SimpleNamespace(timestamp=datetime(2026, 10, 14, 0, 30)),
        )
        == {}
    )


async def test_local_mapper_keeps_cached_snapshot_acquisition(hass, freezer):
    """Building data tomorrow cannot redate a snapshot kept after a failed read."""
    from unittest.mock import AsyncMock

    from pylxpweb.transports.data import InverterEnergyData, InverterRuntimeData
    from tests.conftest import make_real_inverter, make_transport_spec

    acquired = datetime(2026, 10, 13, 23, 50, tzinfo=UTC)
    energy = InverterEnergyData(
        timestamp=acquired,
        pv_energy_today=14.3,
        provenance=provenance(acquired, "pv_energy_today"),
    )
    inverter = make_real_inverter(runtime=InverterRuntimeData(), energy=energy)
    inverter._transport = make_transport_spec()
    inverter._transport.read_energy = AsyncMock(side_effect=RuntimeError("read failed"))
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    freezer.move_to("2026-10-14T12:00:00+00:00")
    await inverter._fetch_energy()
    result = coordinator._build_local_device_data(
        inverter, inverter.serial_number, "FlexBOSS21", "test", "modbus"
    )
    assert result["sensors"]["yield"] == 14.3
    assert result["energy_sample_times"]["yield"] == acquired
    assert result["sensors"]["last_polled"].date() == datetime(2026, 10, 14).date()
    assert "yield_lifetime" not in result["energy_sample_times"]
    await coordinator.async_shutdown()


async def test_local_read_does_not_inherit_undated_restored_daily_baseline(hass):
    from homeassistant.components.sensor import SensorExtraStoredData
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import (
        mock_restore_cache_with_extra_data,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.update_interval = None
    coordinator.get_device_info = MagicMock(return_value=None)
    now = datetime.now(UTC)
    coordinator.async_set_updated_data(
        {
            "devices": {
                "INV": {
                    "type": "inverter",
                    "sensors": {"consumption": 13.5},
                    "energy_sample_times": {"consumption": now},
                }
            }
        }
    )
    sensor = EG4InverterSensor(coordinator, "INV", "consumption")
    sensor.entity_id = "sensor.local_daily_restored"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(
                    sensor.entity_id,
                    "14.3",
                    {"unit_of_measurement": "kWh"},
                    last_updated=now,
                ),
                SensorExtraStoredData(14.3, "kWh").as_dict(),
            )
        ],
    )
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([sensor])
    assert hass.states.get(sensor.entity_id).state == "13.5"
    await coordinator.async_shutdown()


async def test_active_gridboss_path_preserves_snapshot_stamp(hass, freezer):
    from unittest.mock import AsyncMock, patch

    from pylxpweb.transports.data import MidboxRuntimeData
    from tests.conftest import make_real_mid, make_transport_spec

    acquired = datetime(2026, 10, 13, 23, 50, tzinfo=UTC)
    runtime = MidboxRuntimeData(
        timestamp=acquired,
        load_energy_today_l1=10.0,
        load_energy_today_l2=4.3,
        provenance=provenance(acquired, "load_energy_today_l1", "load_energy_today_l2"),
    )
    mid = make_real_mid(serial_number="GB001", runtime=runtime)
    mid._transport = make_transport_spec(is_connected=True)
    # The active path also reads smart-port parameters; complete that unrelated
    # read so frozen time does not strand its incomplete-response retry delay.
    mid._transport.read_parameters = AsyncMock(
        side_effect=lambda start, count: dict.fromkeys(range(start, start + count), 0)
    )
    mid.refresh = AsyncMock()  # A skipped/failed refresh leaves the accepted snapshot.
    config = {
        "serial": "GB001",
        "host": "192.0.2.1",
        "port": 502,
        "transport_type": "wifi_dongle",
        "inverter_family": "MID_DEVICE",
        "model": "GridBOSS",
        "is_gridboss": True,
        "dongle_serial": "D001",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "local",
            "local_transports": [config],
        },
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator._local_static_phase_done = True
    coordinator._mid_device_cache["GB001"] = mid
    coordinator._firmware_cache["GB001"] = "test"
    processed = {"devices": {}, "parameters": {}, "parallel_groups": {}}
    freezer.move_to("2026-10-14T12:00:00+00:00")
    with patch.object(coordinator, "_filter_unused_smart_port_sensors"):
        await coordinator._process_single_local_device(config, processed, {})
    device = processed["devices"]["GB001"]
    assert device["sensors"]["load_today"] == 14.3
    assert device["energy_sample_times"]["load_today"] == acquired
    await coordinator.async_shutdown()
