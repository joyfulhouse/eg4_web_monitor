"""Direct battery bus ownership, identity and missing-data regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from pylxpweb.transports.data import BatteryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.battery_bus import (
    BatteryBusCoordinator,
    BatteryBusSensor,
    CONF_BATTERY_INTERVAL,
    CONF_BATTERY_UNITS,
    _descriptions,
    async_setup_battery_entry,
    async_unload_battery_entry,
    battery_endpoint,
    close_battery_bus,
    project_battery,
)
from custom_components.eg4_web_monitor._config_flow.battery import parse_unit_ids
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.endpoint_bus import (
    EndpointBusRegistry,
    EndpointOwnerInUseError,
    get_endpoint_bus_registry,
)


DATA = {
    "connection_type": "battery_bus",
    "modbus_host": "192.0.2.3",
    "modbus_port": 502,
    CONF_BATTERY_UNITS: [1, 2, 3],
    CONF_BATTERY_INTERVAL: 30,
}


def battery(unit, **kwargs):
    return BatteryData(battery_index=unit - 1, voltage=52.56, soc=57, **kwargs)


def mock_bus():
    bus = MagicMock()
    bus.is_connected = False
    bus.connect = AsyncMock()
    bus.disconnect = AsyncMock()
    bus.read_all = AsyncMock(
        return_value=[battery(1, current_capacity=160), battery(2), battery(3)]
    )
    bus._detected_protocols = {
        1: SimpleNamespace(name="eg4_master"),
        2: SimpleNamespace(name="eg4_slave"),
        3: SimpleNamespace(name="eg4_slave"),
    }
    return bus


def entry(hass):
    result = MockConfigEntry(
        domain=DOMAIN, data=DATA, unique_id="battery_bus_192.0.2.3_502", version=3
    )
    result.add_to_hass(hass)
    return result


@pytest.mark.parametrize("text", ["", "0", "248", "1,1", "1,no", ",1"])
def test_invalid_units(text):
    with pytest.raises(ValueError):
        parse_unit_ids(text)


def test_explicit_units_preserve_address_identity():
    assert parse_unit_ids("16, 3, 2") == [16, 3, 2]


def test_master_aggregate_fields_are_never_per_pack():
    data = battery(1, current=-30, temperature=35, current_capacity=167, cycle_count=99)
    complete = project_battery(data, "eg4_master", complete=True)
    assert complete["soc"] == 57
    assert complete["remaining_capacity"] == 167
    assert complete["current"] is None
    assert complete["temperature"] is None
    assert complete["cycle_count"] is None
    partial = project_battery(data, "eg4_master", complete=False)
    assert partial["soc"] is None
    assert partial["remaining_capacity"] is None
    assert partial["voltage"] == 52.56
    assert "soc" not in project_battery(data, "unknown", complete=True)


def test_slave_zero_current_and_missing_cells_are_distinct():
    data = battery(
        2,
        current=0,
        current_capacity=None,
        cell_voltages=[3.28, 0],
        cell_temperatures=[0, 25],
    )
    result = project_battery(data, "eg4_slave", complete=False)
    assert result["current"] == 0
    assert result["soc"] == 57
    assert result["remaining_capacity"] is None
    assert result["cell_1_voltage"] == 3.28
    assert result["cell_2_voltage"] is None
    assert result["temperature_1"] == 0


def test_complete_bus_does_not_publish_unreconstructed_master_bank_soc():
    from pylxpweb.battery_protocols.eg4_master import EG4MasterProtocol

    data = EG4MasterProtocol().decode_with_slaves({21: 59, 33: 5600}, [])
    assert data.soc == 59
    assert data.current_capacity is None
    result = project_battery(data, "eg4_master", complete=True)
    assert result["soc"] is None
    assert result["remaining_capacity"] is None


def test_external_endpoint_reservation_excludes_all_protocol_owners():
    registry = EndpointBusRegistry(raw_transport_factory=MagicMock())
    config = battery_endpoint(DATA)
    release = registry.reserve_external_endpoint(config)
    with pytest.raises(EndpointOwnerInUseError):
        registry.reserve_external_endpoint(config)
    with pytest.raises(EndpointOwnerInUseError):
        registry.create_capability(config)
    with pytest.raises(EndpointOwnerInUseError):
        registry.create_discovery_capability(config)
    registry.raw_transport_factory.assert_not_called()
    release()
    replacement = registry.reserve_external_endpoint(config)
    release()  # A stale release must not release a newer owner's reservation.
    with pytest.raises(EndpointOwnerInUseError):
        registry.reserve_external_endpoint(config)
    replacement()


async def test_partial_bus_keeps_slave_and_withholds_master_soc(hass):
    config_entry = entry(hass)
    bus = mock_bus()
    with patch(
        "custom_components.eg4_web_monitor.battery_bus.BatteryModbusTransport",
        return_value=bus,
    ):
        coordinator = BatteryBusCoordinator(hass, config_entry)
    try:
        await coordinator.async_refresh()
        assert coordinator.data[1]["soc"] == 57
        bus.read_all.return_value = [battery(1), battery(2)]
        await coordinator.async_refresh()
        assert 3 not in coordinator.data
        assert coordinator.data[1]["soc"] is None
        assert coordinator.data[2]["soc"] == 57
        bus.read_all.return_value = []
        with pytest.raises(UpdateFailed, match="No configured"):
            await coordinator._async_update_data()
    finally:
        await coordinator.async_shutdown()
    bus.disconnect.assert_awaited_once()
    release = get_endpoint_bus_registry(hass).reserve_external_endpoint(
        battery_endpoint(DATA)
    )
    release()


async def test_sensor_identity_survives_missing_serial_and_unit_outage(hass):
    config_entry = entry(hass)
    bus = mock_bus()
    with patch(
        "custom_components.eg4_web_monitor.battery_bus.BatteryModbusTransport",
        return_value=bus,
    ):
        coordinator = BatteryBusCoordinator(hass, config_entry)
    try:
        await coordinator.async_refresh()
        description = next(d for d in _descriptions() if d.key == "soc")
        sensor = BatteryBusSensor(coordinator, 2, description)
        assert sensor.unique_id == f"battery_bus_{config_entry.entry_id}_unit_2_soc"
        assert sensor.native_value == 57
        assert sensor.available
        bus.read_all.return_value = [battery(1)]
        await coordinator.async_refresh()
        assert not sensor.available
        assert sensor.native_value is None
        assert all(
            not d.entity_registry_enabled_default
            for d in _descriptions()
            if d.key.startswith("cell_")
        )
    finally:
        await coordinator.async_shutdown()


async def test_onboarding_uses_battery_protocol_and_closes_probe(hass):
    bus = mock_bus()
    with (
        patch(
            "custom_components.eg4_web_monitor._config_flow.battery.BatteryModbusTransport",
            return_value=bus,
        ),
        patch("custom_components.eg4_web_monitor.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "battery_bridge"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "modbus_host": "192.0.2.3",
                "modbus_port": 502,
                CONF_BATTERY_UNITS: "1,2,3",
                CONF_BATTERY_INTERVAL: 30,
                "dedicated_bus": True,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BATTERY_UNITS] == [1, 2, 3]
    bus.connect.assert_awaited_once()
    bus.disconnect.assert_awaited_once()


async def test_failed_onboarding_releases_probe(hass):
    bus = mock_bus()
    bus.read_all.side_effect = OSError("offline")
    with patch(
        "custom_components.eg4_web_monitor._config_flow.battery.BatteryModbusTransport",
        return_value=bus,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "battery_bridge"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "modbus_host": "192.0.2.3",
                "modbus_port": 502,
                CONF_BATTERY_UNITS: "1,2,3",
                CONF_BATTERY_INTERVAL: 30,
                "dedicated_bus": True,
            },
        )
    assert result["errors"] == {"base": "cannot_connect"}
    bus.disconnect.assert_awaited_once()
    release = get_endpoint_bus_registry(hass).reserve_external_endpoint(
        battery_endpoint(DATA)
    )
    release()


async def test_cancelled_disconnect_retains_ownership_until_socket_closes(hass):
    registry = get_endpoint_bus_registry(hass)
    config = battery_endpoint(DATA)
    release = registry.reserve_external_endpoint(config)
    closing = asyncio.Event()
    closed = asyncio.Event()

    async def disconnect():
        closing.set()
        await closed.wait()

    bus = mock_bus()
    bus.disconnect.side_effect = disconnect
    task = asyncio.create_task(close_battery_bus(bus, release))
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    with pytest.raises(EndpointOwnerInUseError):
        registry.reserve_external_endpoint(config)
    closed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    registry.reserve_external_endpoint(config)()


async def test_failed_disconnect_does_not_allow_second_master(hass):
    registry = get_endpoint_bus_registry(hass)
    config = battery_endpoint(DATA)
    release = registry.reserve_external_endpoint(config)
    bus = mock_bus()
    bus.disconnect.side_effect = OSError("socket close failed")
    with pytest.raises(OSError):
        await close_battery_bus(bus, release)
    with pytest.raises(EndpointOwnerInUseError):
        registry.reserve_external_endpoint(config)
    release()


async def test_setup_failure_cleans_transport_and_reservation(hass):
    config_entry = entry(hass)
    config_entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    bus = mock_bus()
    bus.read_all.return_value = []
    with patch(
        "custom_components.eg4_web_monitor.battery_bus.BatteryModbusTransport",
        return_value=bus,
    ):
        with pytest.raises(ConfigEntryNotReady, match="No configured"):
            await async_setup_battery_entry(hass, config_entry)
    bus.disconnect.assert_awaited_once()
    get_endpoint_bus_registry(hass).reserve_external_endpoint(battery_endpoint(DATA))()


async def test_failed_platform_unload_preserves_active_owner(hass):
    config_entry = entry(hass)
    bus = mock_bus()
    with patch(
        "custom_components.eg4_web_monitor.battery_bus.BatteryModbusTransport",
        return_value=bus,
    ):
        coordinator = BatteryBusCoordinator(hass, config_entry)
    config_entry.runtime_data = coordinator
    try:
        with patch.object(
            hass.config_entries, "async_unload_platforms", return_value=False
        ):
            assert not await async_unload_battery_entry(hass, config_entry)
        bus.disconnect.assert_not_awaited()
        with pytest.raises(EndpointOwnerInUseError):
            get_endpoint_bus_registry(hass).reserve_external_endpoint(
                battery_endpoint(DATA)
            )
    finally:
        await coordinator.async_shutdown()


async def test_diagnostics_redacts_host_and_preserves_unit_measurements(hass):
    from custom_components.eg4_web_monitor.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    config_entry = entry(hass)
    with patch(
        "custom_components.eg4_web_monitor.battery_bus.BatteryModbusTransport",
        return_value=mock_bus(),
    ):
        coordinator = BatteryBusCoordinator(hass, config_entry)
    config_entry.runtime_data = coordinator
    try:
        await coordinator.async_refresh()
        result = await async_get_config_entry_diagnostics(hass, config_entry)
        assert result["entry"]["data"]["modbus_host"] == "**REDACTED**"
        assert result["coordinator"]["data"]["2"]["soc"] == 57
    finally:
        await coordinator.async_shutdown()
