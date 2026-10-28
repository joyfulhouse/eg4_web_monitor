"""Published counters never switch to an older cloud snapshot on local loss (#702)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pylxpweb import LuxpowerClient
from pylxpweb.devices.parallel_group import ParallelGroup
from pylxpweb.models import EnergyInfo
from pylxpweb.provenance import EnergyProvenance
from pylxpweb.transports.data import InverterEnergyData, InverterRuntimeData
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mixins import (
    apply_gridboss_to_parallel_group,
)
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor
from tests.conftest import make_real_inverter, make_transport_spec

SERIAL = "SYNTH00001"
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def cloud(value):
    return EnergyInfo(
        success=True,
        serialNum=SERIAL,
        soc=50,
        todayYielding=round(value * 10),
        todayCharging=14,
        todayDischarging=44,
        todayImport=0,
        todayExport=0,
        todayUsage=56,
        totalYielding=round((2000 + value) * 10),
        totalCharging=10000,
        totalDischarging=10000,
        totalImport=10000,
        totalExport=10000,
        totalUsage=10000,
    )


def local(value, at=AT):
    return InverterEnergyData(
        pv_energy_today=value,
        pv_energy_total=2000 + value,
        charge_energy_today=4,
        discharge_energy_today=6,
        grid_import_today=2,
        grid_export_today=1,
        provenance={
            "pv_energy_today": EnergyProvenance(
                source="local", source_id=SERIAL, acquired_at=at
            )
        },
    )


def coordinator(hass, configured=True):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "hybrid",
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "local_transports": [{"serial": SERIAL}] if configured else [],
        },
    )
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.update_interval = None
    coord.get_device_info = Mock(return_value=None)
    for name in (
        "_poll_firmware_update_info",
        "_fetch_pv_string_energy",
        "_fetch_quick_charge_status",
        "_fetch_last_event",
        "_fetch_ac_couple_soc",
        "_fetch_smart_load",
        "_fetch_battery_backup_status",
    ):
        setattr(coord, name, AsyncMock(return_value=None))
    return coord, entry


async def seeded_inverter(read_path="separate"):
    client = Mock(spec=LuxpowerClient)
    client.api = Mock()
    client.api.devices = Mock()
    client.api.devices.get_inverter_energy = AsyncMock(return_value=cloud(2.6))
    inv = make_real_inverter(
        SERIAL,
        client=client,
        runtime=InverterRuntimeData(pv_total_power=1234, battery_soc=60),
    )
    inv._transport = make_transport_spec()
    inv._rated_power_kw = 21
    inv.validate_data = True
    inv.refresh = AsyncMock()
    inv.detect_features = AsyncMock()
    with patch("pylxpweb.devices.base.time.monotonic", return_value=100):
        await inv._fetch_energy_http()
    inv._energy_validation_calls = 10
    for clock, value in [(15000, 16.5), (15060, 16.6)]:
        inv._transport.read_energy = AsyncMock(return_value=local(value))
        with patch("pylxpweb.devices.base.time.monotonic", return_value=clock):
            if read_path == "combined":
                inv._transport.read_all_input_data = AsyncMock(
                    return_value=(inv.transport_runtime, local(value), None)
                )
                await inv._fetch_combined_input_data()
            else:
                await inv._fetch_energy()
    return inv, client


@pytest.mark.parametrize("fallback", ["rejected", "failed", "lower", "current"])
@pytest.mark.parametrize("read_path", ["separate", "combined"])
async def test_real_library_outage_never_publishes_cloud_energy(
    hass, fallback, caplog, read_path
):
    coord, entry = coordinator(hass)
    inv, client = await seeded_inverter(read_path)
    data = await coord._process_inverter_object(inv)
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    entity = EG4InverterSensor(coord, SERIAL, "yield")
    entity.entity_id = "sensor.fallback_energy"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([entity])
    assert hass.states.get(entity.entity_id).state == "16.6"
    with patch("pylxpweb.devices.base.time.monotonic", return_value=15112):
        for _ in range(3):
            inv._record_transport_read_failure()
        client.api.devices.get_inverter_energy.return_value = cloud(
            {"lower": 2.7, "current": 16.6}.get(fallback, 16.6)
        )
        if fallback == "failed":
            client.api.devices.get_inverter_energy.side_effect = OSError("offline")
        if fallback == "current":
            inv.validate_data = False
        await inv._fetch_energy_http()
    if fallback == "rejected":
        assert "daily energy spike rejected" in caplog.text
        assert inv.total_energy_today == 2.6  # Reproduce released-library defect.
    # Restore runtime only, as happens when probing recovers before energy.
    inv._record_transport_read_success()
    inv._transport_runtime = InverterRuntimeData(pv_total_power=1234, battery_soc=60)
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["pv_total_power"] == 1234
    assert data["sensors"]["state_of_charge"] == 60
    assert data["sensors"]["yield"] is None
    assert data["sensors"]["yield_lifetime"] is None
    assert data["sensors"]["consumption"] is None
    assert "yield" not in data["energy_sample_times"]
    assert data["energy_evidence"]["yield"]["value"] is None
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == "unknown"
    inv._transport_energy = local(16.7)
    data = await coord._process_inverter_object(inv)
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == "16.7"
    await coord.async_shutdown()


@pytest.mark.parametrize("configured", [False, True])
async def test_cloud_only_vs_failed_local_attachment(hass, configured):
    coord, _ = coordinator(hass, configured)
    inv, _ = await seeded_inverter()
    inv._transport = None
    inv._transport_energy = None
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["yield"] == (None if configured else 2.6)
    await coord.async_shutdown()


@pytest.mark.parametrize("other_member", [False, True])
async def test_group_does_not_publish_partial_or_cloud_energy_and_ct_still_wins(
    hass, other_member
):
    coord, _ = coordinator(hass)
    inv, _ = await seeded_inverter()
    group = ParallelGroup(
        client=Mock(), station=Mock(), name="A", first_device_serial=SERIAL
    )
    group.inverters = [inv]
    if other_member:
        group.inverters.append(
            make_real_inverter(
                "SYNTH00002",
                runtime=InverterRuntimeData(pv_total_power=500),
                energy=local(4),
            )
        )
    inv._transport_energy = None
    group._energy = (
        group._compute_energy_from_inverters() if other_member else cloud(2.6)
    )
    data = await coord._process_parallel_group_object(group)
    assert data["sensors"]["yield"] is None
    assert data["sensors"]["yield_lifetime"] is None
    assert data["sensors"]["pv_total_power"] is not None
    apply_gridboss_to_parallel_group(
        data["sensors"],
        {"ups_today": 4, "load_today": 5},
        "A",
        include_ac_couple=False,
        recompute_consumption=False,
    )
    assert data["sensors"]["consumption"] == 9
    assert data["sensors"]["yield"] is None
    await coord.async_shutdown()


async def test_local_midnight_reset_after_gap_keeps_original_acquisition(hass, freezer):
    coord, entry = coordinator(hass)
    inv, _ = await seeded_inverter()
    before = datetime(2026, 10, 28, 23, 59, tzinfo=UTC)
    freezer.move_to(before)
    inv._transport_energy = local(16.6, before)
    data = await coord._process_inverter_object(inv)
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    entity = EG4InverterSensor(coord, SERIAL, "yield")
    entity.entity_id = "sensor.midnight_fallback"
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    await platform.async_add_entities([entity])
    inv._transport_energy = None
    freezer.move_to(before + timedelta(minutes=2))
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["yield"] is None
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    after = before + timedelta(minutes=3)
    inv._transport_energy = local(0.1, after)
    data = await coord._process_inverter_object(inv)
    assert data["energy_sample_times"]["yield"] == after
    coord.async_set_updated_data({"devices": {SERIAL: data}})
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == "0.1"
    await coord.async_shutdown()


@pytest.mark.parametrize("has_runtime", [False, True])
async def test_chart_or_carry_forward_does_not_reintroduce_outage_energy(
    hass, has_runtime
):
    coord, _ = coordinator(hass)
    inv, _ = await seeded_inverter()
    inv._transport_energy = None
    if not has_runtime:
        inv._transport_runtime = None

    async def chart(*args):
        args[1]["sensors"]["pv1_yield"] = 2.6

    coord._fetch_pv_string_energy = chart
    coord._carry_forward_pv_string_energy = lambda serial, data: data["sensors"].update(
        pv1_yield=2.6
    )
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["pv1_yield"] is None
    await coord.async_shutdown()


async def test_recovery_during_supplemental_await_waits_for_next_complete_mapping(hass):
    coord, _ = coordinator(hass)
    inv, _ = await seeded_inverter()
    inv._transport_energy = None

    async def recovered(*args):
        inv._transport_energy = local(16.7)

    coord._fetch_pv_string_energy = recovered
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["yield"] is None
    following = await coord._process_inverter_object(inv)
    assert following["sensors"]["yield"] == 16.7
    await coord.async_shutdown()


async def test_repair_host_uses_config_for_owner_capability(hass):
    from homeassistant.helpers import issue_registry as ir
    from custom_components.eg4_web_monitor import repair_registry

    coord, entry = coordinator(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "local_transports": [
                {
                    "serial": SERIAL,
                    "host": "192.0.2.42",
                    "transport_type": "wifi_dongle",
                }
            ],
        },
    )
    coord._local_transport_configs = list(entry.data["local_transports"])
    inv, _ = await seeded_inverter()
    # Owner-issued transport capabilities expose neither host nor port.
    inv._transport = Mock(spec=[])
    inv._transport_consecutive_failures = 3
    coord._inverter_cache[SERIAL] = inv
    await repair_registry.async_initialize(hass)
    coord._sync_transport_link_state(None)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, repair_registry.repair_issue_id(hass, f"transport_link_down_{SERIAL}")
    )
    assert issue.translation_placeholders["host"] == "192.0.2.42"
    assert "192.0.2.42" not in str(issue.to_json())
    await coord.async_shutdown()


async def test_actual_http_runtime_remains_available_during_energy_gap(hass):
    from pylxpweb.models import BatteryType, InverterRuntime

    coord, _ = coordinator(hass)
    inv, client = await seeded_inverter()
    # A valid cloud model, with unrelated required numeric channels at zero.
    values = {
        name: 0
        for name, field in InverterRuntime.model_fields.items()
        if field.is_required() and field.annotation is int
    }
    runtime = InverterRuntime.model_validate(
        {
            **values,
            "success": True,
            "serialNum": SERIAL,
            "fwCode": "TEST",
            "powerRatingText": "21kW",
            "lost": False,
            "statusText": "normal",
            "batteryType": next(iter(BatteryType)).value,
            "serverTime": "2026-10-28 12:00:00",
            "deviceTime": "2026-10-28 12:00:00",
            "pf": "1",
            "ppv": 2345,
            "soc": 61,
        }
    )
    for _ in range(3):
        inv._record_transport_read_failure()
    client.api.devices.get_inverter_runtime = AsyncMock(return_value=runtime)
    await inv._fetch_runtime_http()
    assert inv.transport_runtime is None
    data = await coord._process_inverter_object(inv)
    assert data["sensors"]["pv_total_power"] == 2345
    assert data["sensors"]["state_of_charge"] == 61
    assert data["sensors"]["yield"] is None
    await coord.async_shutdown()
