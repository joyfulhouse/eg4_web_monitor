"""Restart regressions through HA's native sensor restore and entity lifecycle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.core import State
from homeassistant.helpers.restore_state import async_get as async_get_restore_data
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
    mock_restore_cache_with_extra_data,
)

from custom_components.eg4_web_monitor.const import DOMAIN, SENSOR_TYPES
from custom_components.eg4_web_monitor.sensor import (
    EG4BatteryBankSensor,
    EG4BatterySensor,
    EG4InverterSensor,
)


@pytest.fixture(params=[EG4InverterSensor, EG4BatterySensor, EG4BatteryBankSensor])
def sensor_factory(request, hass):
    """Use real sensor classes sharing each of the three guarded bases."""
    coord = MagicMock()
    coord.hass = hass
    coord.last_update_success = True
    values = {}
    coord.data = {
        "devices": {"serial": {"sensors": values, "batteries": {"b1": values}}}
    }
    coord.get_device_info.return_value = None
    coord.get_battery_device_info.return_value = None
    coord.get_battery_bank_device_info.return_value = None

    def create(key="consumption_lifetime", raw=14.2):
        values[key] = raw
        args = (
            (coord, "serial", "b1", key)
            if request.param is EG4BatterySensor
            else (coord, "serial", key)
        )
        sensor = request.param(*args)
        sensor._attr_entity_registry_enabled_default = True
        sensor.entity_id = "sensor.restored_energy"
        return sensor, values

    return create


async def add_sensor(hass, sensor, native=14.3, unit="kWh", stamp=None, extra=True):
    """Seed HA's restore cache and add via the real entity platform."""
    stamp = stamp or dt_util.utcnow()
    state = State(
        sensor.entity_id, "14300", {"unit_of_measurement": "Wh"}, last_updated=stamp
    )
    payload = SensorExtraStoredData(native, unit).as_dict() if extra else {}
    mock_restore_cache_with_extra_data(hass, [(state, payload)])
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([sensor])
    assert hass.states.get(sensor.entity_id) is not None
    assert async_get_restore_data(hass).entities[sensor.entity_id] is sensor
    return platform


async def test_first_published_reading_is_guarded(hass, sensor_factory):
    sensor, values = sensor_factory()
    await add_sensor(hass, sensor)
    assert hass.states.get(sensor.entity_id).state == "14.3"
    assert sensor.native_value == 14.3
    values["consumption_lifetime"] = 14.4
    assert sensor.native_value == 14.4
    values["consumption_lifetime"] = 0
    assert sensor.native_value == 0  # A genuine reset still passes through.


@pytest.mark.parametrize(
    "native,unit,extra",
    [
        (14.3, "Wh", True),
        (None, "kWh", True),
        ("unknown", "kWh", True),
        (float("nan"), "kWh", True),
        (float("inf"), "kWh", True),
        (float("-inf"), "kWh", True),
        (True, "kWh", True),
        (14.3, "kWh", False),
    ],
)
async def test_invalid_restore_is_ignored(hass, sensor_factory, native, unit, extra):
    sensor, _ = sensor_factory()
    await add_sensor(hass, sensor, native=native, unit=unit, extra=extra)
    assert sensor.native_value == 14.2


@pytest.mark.parametrize(
    "key",
    [
        "consumption",
        "eps_energy_today_l1",
        "pv6_yield",
        "smart_load4_today",
        "battery_charge",
    ],
)
@pytest.mark.parametrize("days_ago,expected", [(0, 14.3), (1, 14.2)])
async def test_daily_restore_requires_same_local_day(
    hass, sensor_factory, freezer, key, days_ago, expected
):
    freezer.move_to("2026-10-13T12:00:00+00:00")
    sensor, _ = sensor_factory(key)
    await add_sensor(hass, sensor, stamp=dt_util.utcnow() - timedelta(days=days_ago))
    assert sensor.native_value == expected


async def test_local_day_used_instead_of_utc_day(hass, sensor_factory, freezer):
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))
    freezer.move_to("2026-10-14T00:30:00+00:00")  # Still October 13 locally.
    sensor, _ = sensor_factory("consumption")
    await add_sensor(hass, sensor, stamp=datetime(2026, 10, 13, 23, 30, tzinfo=UTC))
    assert sensor.native_value == 14.3


async def test_same_utc_day_but_prior_local_day_is_ignored(
    hass, sensor_factory, freezer
):
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))
    freezer.move_to("2026-10-14T07:30:00+00:00")
    sensor, _ = sensor_factory("consumption")
    await add_sensor(hass, sensor, stamp=datetime(2026, 10, 14, 6, 30, tzinfo=UTC))
    assert sensor.native_value == 14.2


async def test_old_lifetime_restore_is_retained(hass, sensor_factory):
    sensor, _ = sensor_factory()
    await add_sensor(hass, sensor, stamp=dt_util.utcnow() - timedelta(days=5))
    assert sensor.native_value == 14.3


async def test_restore_does_not_publish_stale_data_when_live_value_missing(
    hass, sensor_factory
):
    sensor, values = sensor_factory(raw=None)
    await add_sensor(hass, sensor)
    assert hass.states.get(sensor.entity_id).state == "unknown"
    values["consumption_lifetime"] = 14.2
    assert sensor.native_value == 14.3


async def test_measurement_is_not_guarded(hass, sensor_factory):
    sensor, _ = sensor_factory("battery_voltage", 14.2)
    await add_sensor(hass, sensor, unit="V")
    assert sensor.native_value == 14.2


async def test_unitless_total_increasing_sensor_is_restored(hass, sensor_factory):
    sensor, _ = sensor_factory("cycle_count", 99)
    await add_sensor(hass, sensor, native=100, unit=None)
    assert sensor.native_value == 100


async def test_first_install_has_no_restored_baseline(hass, sensor_factory):
    sensor, _ = sensor_factory()
    mock_restore_cache_with_extra_data(hass, [])
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    await platform.async_add_entities([sensor])
    assert sensor.native_value == 14.2


async def test_removed_sensor_stores_native_guarded_value(hass, sensor_factory):
    sensor, _ = sensor_factory()
    platform = await add_sensor(hass, sensor)
    await platform.async_remove_entity(sensor.entity_id)
    replacement, _ = sensor_factory()
    await platform.async_add_entities([replacement])
    assert replacement.native_value == 14.3
    assert hass.states.get(replacement.entity_id).state == "14.3"


def test_daily_metadata_covers_today_and_legacy_energy_keys():
    """Check known naming families; require a decision for new counter names."""
    for key, config in SENSOR_TYPES.items():
        if config.get("state_class") != "total_increasing":
            continue
        assert config.get("reset_period") in (None, "daily"), key
        if (
            "today" in key.split("_")
            or f"{key}_lifetime" in SENSOR_TYPES
            or key == "daily_energy"
        ):
            assert config.get("reset_period") == "daily", key
        elif key.endswith(("_lifetime", "_total")) or "total" in key.split("_"):
            assert config.get("reset_period") is None, key
        elif key in {"cycle_count", "battery_bank_cycle_count"}:
            assert config.get("reset_period") is None, key
        elif key in {"monthly_energy", "yearly_energy"}:
            # Dormant configuration: no coordinator mapping populates these keys.
            assert config.get("reset_period") is None, key
        else:
            pytest.fail(f"Classify the reset period of the new counter {key}")
