"""Released b13 provenance through real library aggregates and HA lifecycle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pylxpweb.devices.inverters.generic import GenericInverter
from pylxpweb.devices.parallel_group import ParallelGroup
from pylxpweb.models import EnergyInfo
from pylxpweb.provenance import EnergyProvenance, derived_provenance
from pylxpweb.transports.data import (
    InverterEnergyData,
    InverterRuntimeData,
    MidboxRuntimeData,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_energy_sensor_mapping,
)
from custom_components.eg4_web_monitor.coordinator_mixins import (
    apply_gridboss_to_parallel_group,
)
from custom_components.eg4_web_monitor.energy_provenance import (
    aggregate_daily_sample_times,
    local_daily_sample_times,
    mapped_daily_sample_times,
)
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor
from tests.conftest import make_real_mid


def local(at, serial="A"):
    return EnergyProvenance(
        source="local", source_id=f"modbus:{serial}", acquired_at=at
    )


def snapshot(value, record, legacy):
    return InverterEnergyData(
        pv_energy_today=value,
        timestamp=legacy,
        provenance={} if record is None else {"pv_energy_today": record},
    )


def group_snapshot(records, legacy):
    group = ParallelGroup(
        client=Mock(), station=Mock(), name="A", first_device_serial="A"
    )
    for index, record in enumerate(records):
        inv = GenericInverter(client=None, serial_number=str(index), model="Test")
        inv._transport_runtime = InverterRuntimeData()
        inv._transport_energy = snapshot(13.5 / len(records), record, legacy)
        group.inverters.append(inv)
    group._energy = group._compute_energy_from_inverters()
    return group


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kolkata"])
@pytest.mark.parametrize(
    "case",
    [
        "local",
        "cached",
        "http",
        "unknown",
        "mixed_source",
        "mixed_day",
        "aggregate",
        "missing",
        "empty",
    ],
)
async def test_released_lineage_through_entity_lifecycle(hass, freezer, zone, case):
    tz = ZoneInfo(zone)
    dt_util.set_default_time_zone(tz)
    before = datetime(2026, 10, 19, 23, 50, tzinfo=tz).astimezone(UTC)
    after = datetime(2026, 10, 20, 0, 10, tzinfo=tz).astimezone(UTC)
    freezer.move_to(before)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.update_interval = None
    coord.get_device_info = MagicMock(return_value=None)

    def publish(data):
        sensors = _build_energy_sensor_mapping(data)
        coord.async_set_updated_data(
            {
                "devices": {
                    "serial": {
                        "sensors": sensors,
                        "energy_sample_times": local_daily_sample_times(sensors, data),
                    }
                }
            }
        )

    publish(snapshot(14.3, local(before), before))
    entity = EG4InverterSensor(coord, "serial", "yield")
    entity.entity_id = "sensor.provenance_daily"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([entity])
    assert hass.states.get(entity.entity_id).state == "14.3"
    freezer.move_to(after)
    entity.async_write_ha_state()
    assert entity.extra_restore_state_data.native_value == 14.3
    coord.last_update_success = False
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == "unavailable"
    http = EnergyProvenance(source="http", source_id="cloud:A", acquired_at=after)
    records = {
        "local": local(after),
        "cached": local(before),
        "http": http,
        "unknown": None,
        "empty": derived_provenance("empty", []),
    }
    if case in records:
        candidate = snapshot(13.5, records[case], after)
    else:
        components = {
            "mixed_source": [local(after), http],
            "mixed_day": [local(before), local(after)],
            "aggregate": [local(after), local(after + timedelta(minutes=1), "B")],
            "missing": [local(after), None],
        }[case]
        group = group_snapshot(components, after)
        candidate = InverterEnergyData.from_http_response(group._energy)
        mapped = mapped_daily_sample_times(
            {"yield": group.today_yielding},
            group.energy_provenance,
            {"today_yielding": "yield"},
        )
        assert mapped == local_daily_sample_times(
            {"yield": candidate.pv_energy_today}, candidate
        )
    publish(candidate)
    entity.async_write_ha_state()
    expected = 13.5 if case in ("local", "aggregate") else 14.3
    assert float(hass.states.get(entity.entity_id).state) == expected
    assert entity.extra_restore_state_data.native_value == expected
    if case == "aggregate":
        assert coord.data["devices"]["serial"]["energy_sample_times"]["yield"] == after
    await coord.async_shutdown()


def test_real_http_conversion_cannot_date_counter():
    at = datetime(2026, 10, 20, tzinfo=UTC)
    cloud = EnergyInfo(
        success=True,
        **{
            f"{period}{field}": 135
            for period in ("today", "total")
            for field in (
                "Yielding",
                "Charging",
                "Discharging",
                "Import",
                "Export",
                "Usage",
            )
        },
        provenance={
            "todayYielding": EnergyProvenance(
                source="http", source_id="cloud", acquired_at=at
            )
        },
    )
    data = InverterEnergyData.from_http_response(cloud)
    assert local_daily_sample_times(_build_energy_sensor_mapping(data), data) == {}


def test_per_field_balance_requires_every_operand():
    at = datetime(2026, 10, 20, tzinfo=UTC)
    data = InverterEnergyData(
        pv_energy_today=14.3,
        charge_energy_today=0,
        discharge_energy_today=0,
        grid_import_today=0,
        grid_export_today=0,
        provenance={
            name: local(at)
            for name in (
                "pv_energy_today",
                "charge_energy_today",
                "discharge_energy_today",
                "grid_import_today",
                "grid_export_today",
            )
        },
    )
    sensors = _build_energy_sensor_mapping(data)
    assert local_daily_sample_times(sensors, data)["consumption"] == at
    data.provenance.pop("charge_energy_today")
    times = local_daily_sample_times(sensors, data)
    assert times["yield"] == at
    assert "consumption" not in times
    assert "charging" not in times
    assert "yield_lifetime" not in times


def test_mid_partial_phase_and_overlay_never_borrow_group_time():
    at = datetime(2026, 10, 20, tzinfo=UTC)
    runtime = MidboxRuntimeData(
        load_energy_today_l1=4,
        load_energy_today_l2=2,
        ups_energy_today_l1=2,
        ups_energy_today_l2=1,
        provenance={
            name: local(at)
            for name in (
                "load_energy_today_l1",
                "load_energy_today_l2",
                "ups_energy_today_l1",
            )
        },
    )
    mid = make_real_mid(runtime=runtime)
    sensors = {"load_today": mid.e_load_today, "ups_today": mid.e_ups_today}
    times = mapped_daily_sample_times(
        sensors,
        mid.energy_provenance,
        {"e_load_today": "load_today", "e_ups_today": "ups_today"},
    )
    assert times == {"load_today": at}
    pg = {"consumption": 99}
    pg_times = {"consumption": at}
    apply_gridboss_to_parallel_group(
        pg,
        sensors,
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_sample_times=pg_times,
        gb_sample_times=times,
    )
    assert pg["consumption"] == 9
    assert "consumption" not in pg_times
    runtime.provenance["ups_energy_today_l2"] = local(at)
    times = mapped_daily_sample_times(
        sensors,
        mid.energy_provenance,
        {"e_load_today": "load_today", "e_ups_today": "ups_today"},
    )
    apply_gridboss_to_parallel_group(
        pg,
        sensors,
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_sample_times=pg_times,
        gb_sample_times=times,
    )
    assert pg_times["consumption"] == at


@pytest.mark.parametrize("other", [None, "same", "yesterday"])
def test_local_group_requires_every_member(other):
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    stamp = at if other == "same" else at - timedelta(days=1)
    members = [
        {"sensors": {"yield": 7}, "energy_sample_times": {"yield": at}},
        {
            "sensors": {"yield": 6.5},
            "energy_sample_times": {} if other is None else {"yield": stamp},
        },
    ]
    assert aggregate_daily_sample_times({"yield": 13.5}, members) == (
        {"yield": at} if other == "same" else {}
    )


async def test_real_parallel_group_coordinator_retains_field_lineage(hass):
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    group = group_snapshot([local(at), local(at + timedelta(minutes=1), "B")], at)
    data = await coord._process_parallel_group_object(group)
    assert data["sensors"]["yield"] == 13.5
    assert data["energy_sample_times"]["yield"] == at
    assert "consumption" not in data["energy_sample_times"]
    group = group_snapshot([local(at), None], at)
    data = await coord._process_parallel_group_object(group)
    assert data["sensors"]["yield"] == 13.5
    assert "yield" not in data["energy_sample_times"]
    await coord.async_shutdown()


async def test_hybrid_public_properties_and_transport_overlay(hass):
    from unittest.mock import AsyncMock
    from pylxpweb.transports.data import InverterRuntimeData
    from tests.conftest import (
        make_real_inverter,
        make_transport_spec,
        stub_cloud_client,
    )

    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.client = stub_cloud_client()
    energy = snapshot(13.5, local(at), at + timedelta(days=1))
    energy.eps_l1_energy_today = 3
    energy.provenance["eps_l1_energy_today"] = local(at - timedelta(minutes=1))
    inv = make_real_inverter(runtime=InverterRuntimeData(), energy=energy)
    inv.refresh = AsyncMock()
    inv.detect_features = AsyncMock()
    inv._transport = make_transport_spec()
    inv._transport.read_parameters = AsyncMock(return_value={})
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["yield"] == 13.5
    assert data["energy_sample_times"]["yield"] == at
    assert data["energy_sample_times"]["eps_energy_today_l1"] == at - timedelta(
        minutes=1
    )
    assert "consumption" not in data["energy_sample_times"]
    energy.provenance.clear()
    data = await coord._process_inverter_object(inv)
    assert data["energy_sample_times"] == {}
    await coord.async_shutdown()


async def test_local_coordinator_group_uses_member_times_and_ct_replacement(hass):
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    ct_at = at + timedelta(minutes=5)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord._register_pg_device = Mock()
    devices = {}
    for serial in ("A", "B"):
        devices[serial] = {
            "type": "inverter",
            "parallel_number": 1,
            "sensors": {"yield": 6.75, "consumption": 5, "grid_import": 1},
            "energy_sample_times": {"yield": at, "consumption": at, "grid_import": at},
        }
    devices["MID"] = {
        "type": "gridboss",
        "sensors": {"ups_today": 4, "load_today": 5, "grid_import_today": 3},
        "energy_sample_times": {"ups_today": ct_at, "load_today": ct_at},
    }
    processed = {"devices": devices}
    await coord._process_local_parallel_groups(processed)
    group = next(
        value for value in devices.values() if value["type"] == "parallel_group"
    )
    assert group["sensors"]["yield"] == 13.5
    assert group["sensors"]["consumption"] == 9
    assert group["energy_sample_times"] == {"yield": at, "consumption": ct_at}
    await coord.async_shutdown()


@pytest.mark.parametrize("phase_source", ["http", "yesterday"])
def test_real_mid_phase_source_selection_and_day_boundary(phase_source):
    from pylxpweb.models import MidboxData, MidboxRuntime

    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    other_at = at if phase_source == "http" else at - timedelta(days=1)
    other = EnergyProvenance(
        source="http" if phase_source == "http" else "local",
        source_id="other-phase",
        acquired_at=other_at,
    )
    runtime = MidboxRuntimeData(
        load_energy_today_l1=4,
        ups_energy_today_l1=2,
        load_energy_today_l2=None if phase_source == "http" else 2,
        ups_energy_today_l2=None if phase_source == "http" else 1,
        provenance={
            "load_energy_today_l1": local(at),
            "ups_energy_today_l1": local(at),
            "load_energy_today_l2": other,
            "ups_energy_today_l2": other,
        },
    )
    mid = make_real_mid(runtime=runtime)
    # Public MID getters fall back per phase; model_construct avoids inventing
    # unrelated mandatory runtime fields in this offline source-selection test.
    mid._runtime = MidboxRuntime.model_construct(
        midboxData=MidboxData.model_construct(
            eLoadTodayL2=2,
            eUpsTodayL2=1,
            provenance={"eLoadTodayL2": other, "eUpsTodayL2": other},
        )
    )
    sensors = {"load_today": mid.e_load_today, "ups_today": mid.e_ups_today}
    assert sensors == {"load_today": 6, "ups_today": 3}
    times = mapped_daily_sample_times(
        sensors,
        mid.energy_provenance,
        {"e_load_today": "load_today", "e_ups_today": "ups_today"},
    )
    assert times == {}
    pg, pg_times = {"consumption": 99}, {"consumption": at}
    apply_gridboss_to_parallel_group(
        pg,
        sensors,
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_sample_times=pg_times,
        gb_sample_times=times,
    )
    assert pg["consumption"] == 9
    assert pg_times == {}


async def test_lost_group_ct_overlay_and_cached_then_fresh_recovery(hass, freezer):
    before = datetime(2026, 10, 19, 23, 50, tzinfo=UTC)
    after = before + timedelta(hours=1)
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    freezer.move_to(before)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.update_interval = None
    coord.get_device_info = MagicMock(return_value=None)
    group = group_snapshot([local(before), local(before, "B")], before)

    def energy(value, at):
        for inv in group.inverters:
            inv._transport_energy = snapshot(
                value / 2, local(at, inv.serial_number), after
            )
        group._energy = group._compute_energy_from_inverters()

    async def publish(ct_value, ct_at):
        data = await coord._process_parallel_group_object(group)
        mid = make_real_mid(
            runtime=MidboxRuntimeData(
                load_energy_today_l1=ct_value,
                load_energy_today_l2=0,
                ups_energy_today_l1=0,
                ups_energy_today_l2=0,
                provenance={
                    field: local(ct_at)
                    for field in (
                        "load_energy_today_l1",
                        "load_energy_today_l2",
                        "ups_energy_today_l1",
                        "ups_energy_today_l2",
                    )
                },
            )
        )
        ct = {"load_today": mid.e_load_today, "ups_today": mid.e_ups_today}
        times = mapped_daily_sample_times(
            ct,
            mid.energy_provenance,
            {"e_load_today": "load_today", "e_ups_today": "ups_today"},
        )
        apply_gridboss_to_parallel_group(
            data["sensors"],
            ct,
            "A",
            include_ac_couple=False,
            recompute_consumption=False,
            pg_sample_times=data["energy_sample_times"],
            gb_sample_times=times,
        )
        coord.async_set_updated_data({"devices": {"group": data}})
        return data

    energy(14.3, before)
    await publish(14.3, before)
    pv = EG4InverterSensor(coord, "group", "yield", "parallel_group")
    ct = EG4InverterSensor(coord, "group", "consumption", "parallel_group")
    pv.entity_id, ct.entity_id = "sensor.group_pv", "sensor.group_ct"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([pv, ct])
    assert pv.native_value == ct.native_value == 14.3
    freezer.move_to(after)
    # Fresh aggregate lineage alone must not advance a nulled lost-member meter.
    energy(13.5, after)
    group.inverters[1]._transport_runtime = None
    lost = await publish(13.5, after)
    assert lost["sensors"]["yield"] is None
    assert lost["energy_sample_times"]["yield"] == after
    pv.async_write_ha_state()
    ct.async_write_ha_state()
    assert hass.states.get(pv.entity_id).state == "unknown"
    assert hass.states.get(ct.entity_id).state == "13.5"
    assert pv.extra_restore_state_data.native_value is None
    # Recovery of an older cached snapshot still sees yesterday's PV baseline.
    group.inverters[1]._transport_runtime = InverterRuntimeData()
    energy(13.5, before)
    await publish(13.4, after)
    assert pv.native_value == 14.3
    assert ct.native_value == 13.5
    energy(13.5, after)
    await publish(13.4, after)
    assert pv.native_value == 13.5
    assert ct.native_value == 13.5
    await coord.async_shutdown()
