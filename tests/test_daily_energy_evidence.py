"""Daily diagnostics retain the lineage selected with each numeric value."""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pylxpweb.provenance import EnergyProvenance, derived_provenance
from pylxpweb.transports.data import InverterRuntimeData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from tests.test_energy_provenance_adoption import group_snapshot, local, snapshot
from tests.conftest import make_real_inverter, make_transport_spec, stub_cloud_client


@pytest.mark.parametrize(
    "case,reason",
    [
        ("local", None),
        ("http", "http"),
        ("unknown", "unknown"),
        ("missing", "unknown"),
        ("empty", "empty"),
        ("mixed_day", "mixed_day"),
    ],
)
async def test_group_evidence_retains_rejected_contributors(hass, case, reason):
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    records = {
        "local": local(at, "PRIVATE_SERIAL"),
        "http": EnergyProvenance(
            source="http", source_id="PRIVATE_SERIAL", acquired_at=at
        ),
        "unknown": EnergyProvenance(source="unknown", source_id="PRIVATE_SERIAL"),
        "missing": None,
        "empty": derived_provenance("PRIVATE_GROUP", []),
        "mixed_day": local(at - timedelta(days=1)),
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    group = group_snapshot([local(at), records[case]], at)
    data = await coord._process_parallel_group_object(group)
    evidence = data.get("energy_evidence", {}).get("yield")
    assert evidence is not None
    assert evidence["value"] == data["sensors"]["yield"] == 13.5
    assert evidence["accepted_for_daily_guard"] is (reason is None)
    assert evidence["rejection_reasons"] == ([] if reason is None else [reason])
    assert "PRIVATE_" not in json.dumps(evidence, default=str)
    assert evidence["lineage"]["source"] == "derived"
    assert len(evidence["lineage"]["components"]) == 2
    await coord.async_shutdown()


async def test_inverter_evidence_is_a_detached_snapshot_before_chart_await(hass):
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.client = stub_cloud_client()
    energy = snapshot(13.5, local(at), at)
    inv = make_real_inverter(runtime=InverterRuntimeData(), energy=energy)
    inv.refresh = AsyncMock()
    inv.detect_features = AsyncMock()
    inv._transport = make_transport_spec()
    inv._transport.read_parameters = AsyncMock(return_value={})

    async def later_snapshot(*args):
        energy.provenance["pv_energy_today"] = local(at + timedelta(days=1))

    coord._fetch_pv_string_energy = later_snapshot
    data = await coord._process_inverter_object(inv)
    evidence = data.get("energy_evidence", {}).get("yield")
    assert evidence is not None
    assert evidence["lineage"]["acquired_at"] == at
    assert evidence["value"] == 13.5
    await coord.async_shutdown()


async def test_lost_group_clears_value_but_ct_keeps_its_own_lineage(hass):
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        apply_gridboss_to_parallel_group,
    )
    from custom_components.eg4_web_monitor.energy_evidence import mapped_daily_evidence

    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    group = group_snapshot([local(at), local(at)], at)
    group.inverters[1]._transport_runtime = None
    data = await coord._process_parallel_group_object(group)
    assert data["sensors"]["yield"] is None
    assert data["energy_evidence"]["yield"]["value"] is None
    assert data["energy_evidence"]["yield"]["rejection_reasons"] == ["no_value"]
    ct_at = at + timedelta(minutes=5)
    ct = {"ups_today": 4, "load_today": 5}
    ct_evidence = mapped_daily_evidence(
        ct,
        {"ups": local(ct_at), "load": local(ct_at)},
        {"ups": "ups_today", "load": "load_today"},
    )
    apply_gridboss_to_parallel_group(
        data["sensors"],
        ct,
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_evidence=data["energy_evidence"],
        gb_evidence=ct_evidence,
    )
    evidence = data["energy_evidence"]["consumption"]
    assert data["sensors"]["consumption"] == evidence["value"] == 9
    assert evidence["accepted_for_daily_guard"] is True
    assert [c["acquired_at"] for c in evidence["lineage"]["components"]] == [
        ct_at,
        ct_at,
    ]
    apply_gridboss_to_parallel_group(
        data["sensors"],
        {"ups_today": 4},
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_evidence=data["energy_evidence"],
        gb_evidence=ct_evidence,
    )
    assert data["sensors"]["consumption"] is None
    assert data["energy_evidence"]["consumption"]["accepted_for_daily_guard"] is False
    await coord.async_shutdown()


async def test_local_group_preserves_cached_member_lineage(hass, freezer):
    from custom_components.eg4_web_monitor.energy_evidence import mapped_daily_evidence

    before = datetime(2026, 10, 19, 23, 50, tzinfo=UTC)
    after = before + timedelta(hours=1)
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord._register_pg_device = Mock()
    devices = {}
    for serial, at in [("A", before), ("B", after)]:
        sensors = {"yield": 6.75}
        devices[serial] = {
            "type": "inverter",
            "parallel_number": 1,
            "sensors": sensors,
            "energy_evidence": mapped_daily_evidence(
                sensors, {"pv": local(at)}, {"pv": "yield"}
            ),
        }
    freezer.move_to(after)
    await coord._process_local_parallel_groups({"devices": devices})
    group = next(v for v in devices.values() if v["type"] == "parallel_group")
    evidence = group["energy_evidence"]["yield"]
    assert evidence["value"] == 13.5
    assert evidence["rejection_reasons"] == ["mixed_day"]
    assert [c["acquired_at"] for c in evidence["lineage"]["components"]] == [
        before,
        after,
    ]
    await coord.async_shutdown()


@pytest.mark.parametrize("other_source", ["http", "yesterday", "missing"])
def test_real_mid_phase_evidence_survives_ct_overlay(other_source):
    from pylxpweb.models import MidboxData, MidboxRuntime
    from pylxpweb.transports.data import MidboxRuntimeData
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        apply_gridboss_to_parallel_group,
    )
    from custom_components.eg4_web_monitor.energy_evidence import mapped_daily_evidence
    from tests.conftest import make_real_mid

    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    other = EnergyProvenance(
        source="http" if other_source == "http" else "local",
        source_id="PRIVATE_PHASE",
        acquired_at=at if other_source == "http" else at - timedelta(days=1),
    )
    runtime = MidboxRuntimeData(
        load_energy_today_l1=4,
        load_energy_today_l2=None if other_source == "http" else 2,
        ups_energy_today_l1=2,
        ups_energy_today_l2=1,
        provenance={
            "load_energy_today_l1": local(at),
            "ups_energy_today_l1": local(at),
            "ups_energy_today_l2": local(at),
            **({} if other_source == "missing" else {"load_energy_today_l2": other}),
        },
    )
    mid = make_real_mid(runtime=runtime)
    mid._runtime = MidboxRuntime.model_construct(
        midboxData=MidboxData.model_construct(
            eLoadTodayL2=2, provenance={"eLoadTodayL2": other}
        )
    )
    sensors = {"load_today": mid.e_load_today, "ups_today": mid.e_ups_today}
    evidence = mapped_daily_evidence(
        sensors,
        mid.energy_provenance,
        {"e_load_today": "load_today", "e_ups_today": "ups_today"},
    )
    pg, pg_evidence = {"consumption": 99}, {}
    apply_gridboss_to_parallel_group(
        pg,
        sensors,
        "PRIVATE_GROUP",
        include_ac_couple=False,
        recompute_consumption=False,
        pg_evidence=pg_evidence,
        gb_evidence=evidence,
    )
    assert pg["consumption"] == 9
    result = pg_evidence["consumption"]
    assert result["accepted_for_daily_guard"] is False
    assert (
        "http"
        if other_source == "http"
        else "mixed_day"
        if other_source == "yesterday"
        else "unknown"
    ) in result["rejection_reasons"]
    assert "PRIVATE_" not in json.dumps(result, default=str)


async def test_local_read_failure_keeps_original_acquisition_evidence(hass, freezer):
    acquired = datetime(2026, 10, 13, 23, 50, tzinfo=UTC)
    energy = snapshot(14.3, local(acquired, "PRIVATE_SERIAL"), acquired)
    inv = make_real_inverter(runtime=InverterRuntimeData(), energy=energy)
    inv._transport = make_transport_spec()
    inv._transport.read_energy = AsyncMock(side_effect=RuntimeError("read failed"))
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    freezer.move_to("2026-10-14T12:00:00+00:00")
    await inv._fetch_energy()
    data = coord._build_local_device_data(
        inv, inv.serial_number, "FlexBOSS21", "test", "modbus"
    )
    evidence = data["energy_evidence"]["yield"]
    assert evidence["value"] == data["sensors"]["yield"] == 14.3
    assert evidence["lineage"]["acquired_at"] == acquired
    assert data["sensors"]["last_polled"].date() != acquired.date()
    assert "yield_lifetime" not in data["energy_evidence"]
    assert "PRIVATE_SERIAL" not in json.dumps(data["energy_evidence"], default=str)
    await coord.async_shutdown()


def test_missing_and_undated_field_evidence_stay_explicit():
    from custom_components.eg4_web_monitor.energy_evidence import (
        mapped_daily_evidence,
        reconcile_daily_evidence,
    )

    sensors = {"yield": 1, "charging": 2, "yield_lifetime": 100}
    result = mapped_daily_evidence(
        sensors,
        {"charge": EnergyProvenance(source="local", source_id="private")},
        {"charge": "charging"},
    )
    assert result["yield"]["rejection_reasons"] == ["missing"]
    assert result["charging"]["rejection_reasons"] == ["missing_acquisition_time"]
    assert "yield_lifetime" not in result
    data = {"sensors": {"yield": 2}, "energy_evidence": result}
    reconcile_daily_evidence(data)
    assert data["energy_evidence"]["yield"]["value"] == 2
    assert data["energy_evidence"]["yield"]["rejection_reasons"] == ["missing"]


async def test_pv_string_carry_keeps_lineage_but_new_chart_value_clears_it(
    hass, freezer
):
    from types import SimpleNamespace
    from custom_components.eg4_web_monitor.energy_evidence import mapped_daily_evidence

    acquired = datetime(2026, 10, 19, 12, tzinfo=UTC)
    freezer.move_to("2026-10-20T12:00:00+00:00")
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    previous = {"sensors": {"pv1_yield": 1}}
    previous["energy_evidence"] = mapped_daily_evidence(
        previous["sensors"], {"pv": local(acquired)}, {"pv": "pv1_yield"}
    )
    coord.data = {"devices": {"A": previous}}
    target = {"sensors": {}, "features": {"pv_string_count": 1}}
    coord._carry_forward_pv_string_energy("A", target)
    assert target["sensors"]["pv1_yield"] == 1
    assert (
        target.get("energy_evidence", {}).get("pv1_yield")
        == previous["energy_evidence"]["pv1_yield"]
    )
    assert (
        target["energy_evidence"]["pv1_yield"]
        is not previous["energy_evidence"]["pv1_yield"]
    )

    coord.client = stub_cloud_client()
    coord.client.analytics.get_month_daily_energy = AsyncMock(
        return_value=SimpleNamespace(days=[SimpleNamespace(day=20, ePv1Day=10)])
    )

    async def call(awaitable, **kwargs):
        return await awaitable

    coord._breakered_cloud_call = call
    await coord._fetch_pv_string_energy("A", target)
    assert target["sensors"]["pv1_yield"] == 1
    assert target["energy_evidence"]["pv1_yield"]["accepted_for_daily_guard"] is False
    assert target["energy_evidence"]["pv1_yield"]["rejection_reasons"] == ["missing"]
    await coord.async_shutdown()


async def test_real_local_update_interval_skip_carries_original_evidence(hass, freezer):
    acquired = datetime(2026, 10, 19, 23, 50, tzinfo=UTC)
    entry = MockConfigEntry(domain=DOMAIN, data={"connection_type": "local"})
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    inv = make_real_inverter(
        runtime=InverterRuntimeData(), energy=snapshot(14.3, local(acquired), acquired)
    )
    previous = coord._build_local_device_data(
        inv, inv.serial_number, "FlexBOSS21", "test", "modbus"
    )
    coord.data = {"devices": {inv.serial_number: previous}}
    coord._local_transport_configs = [
        {
            "serial": inv.serial_number,
            "transport_type": "modbus_tcp",
            "host": "192.0.2.30",
        }
    ]
    coord._local_static_phase_done = True
    coord._should_poll_transport = Mock(return_value=False)
    coord._process_local_transport_group = AsyncMock()
    freezer.move_to("2026-10-20T12:00:00+00:00")
    result = await coord._async_update_local_data()
    retained = result["devices"][inv.serial_number]
    assert retained["sensors"]["yield"] == 14.3
    assert retained["energy_evidence"] == previous["energy_evidence"]
    assert retained["energy_evidence"]["yield"]["lineage"]["acquired_at"] == acquired
    assert result["last_update"].date() != acquired.date()
    coord._process_local_transport_group.assert_not_called()
    await coord.async_shutdown()
