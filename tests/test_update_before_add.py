"""Coordinator entity setup uses initial data without requesting a refresh."""

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor import sensor, switch
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


class _Entry:
    def __init__(self, runtime_data):
        self.runtime_data = runtime_data
        self.entry_id = "test-entry"

    def async_on_unload(self, _unload):
        pass


@pytest.mark.parametrize(
    ("platform", "data"),
    [
        (sensor, {"station": {"plant_name": "Plant"}, "devices": {}}),
        (switch, {"station": {"plant_name": "Plant"}}),
    ],
)
async def test_platform_setup_does_not_request_entity_refresh(
    hass, monkeypatch, platform, data
):
    coordinator = type("Coordinator", (), {})()
    coordinator.data = data
    coordinator.plant_id = "plant_123"
    coordinator.async_request_refresh = MagicMock()
    coordinator.async_add_listener = lambda *_args, **_kwargs: lambda: None
    coordinator.has_http_api = lambda *_args: False
    coordinator.has_configured_local_transport = lambda *_args: False
    coordinator.has_local_transport = lambda *_args: False
    coordinator.is_transport_link_down = lambda *_args: False
    coordinator.is_local_only = lambda *_args: False
    coordinator.is_hybrid = False
    coordinator.last_update_success = True
    coordinator.get_device_info = lambda *_args: None

    if platform is switch:
        monkeypatch.setattr(
            switch, "setup_control_entity_discovery", lambda *_args, **_kwargs: None
        )

    add_calls = []

    def add_entities(entities, update_before_add=False):
        add_calls.append((entities, update_before_add))
        if update_before_add:
            coordinator.async_request_refresh()

    await platform.async_setup_entry(hass, _Entry(coordinator), add_entities)

    assert add_calls
    assert all(not update_before_add for _, update_before_add in add_calls)
    coordinator.async_request_refresh.assert_not_called()


@pytest.mark.parametrize("filename", ["sensor.py", "switch.py"])
def test_platform_add_calls_do_not_request_update_before_add(filename):
    source = Path("custom_components/eg4_web_monitor", filename).read_text()
    tree = ast.parse(source)
    add_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "async_add_entities"
    ]

    assert add_calls
    for call in add_calls:
        assert len(call.args) <= 2
        if len(call.args) == 2:
            assert isinstance(call.args[1], ast.Constant)
            assert call.args[1].value is False
        for keyword in call.keywords:
            if keyword.arg == "update_before_add":
                assert isinstance(keyword.value, ast.Constant)
                assert keyword.value.value is False


@pytest.mark.parametrize("hybrid", [False, True])
async def test_sensor_setup_preserves_first_reading_without_entity_refresh(
    hass: HomeAssistant, hybrid: bool
):
    """Real HA entity setup publishes inverter and bank readings on first add."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Local inverter",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "1234567890",
                    "host": "127.0.0.1",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    entry.runtime_data = coordinator
    initial = {
        "plant_id": None,
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "FlexBOSS21",
                "features": {"supports_split_phase": True},
                "sensors": {"pv1_voltage": None, "battery_bank_soc": None},
                "batteries": {},
            }
        },
        "parameters": {},
        "connection_type": CONNECTION_TYPE_LOCAL,
    }
    measured = {
        **initial,
        "devices": {
            "1234567890": {
                **initial["devices"]["1234567890"],
                "sensors": {"pv1_voltage": 321.0, "battery_bank_soc": 74.0},
            }
        },
    }
    if hybrid:
        coordinator.connection_type = CONNECTION_TYPE_HYBRID
        initial = measured
    coordinator.data = initial
    coordinator._local_static_phase_done = True
    coordinator.async_request_refresh = AsyncMock()
    release_read = asyncio.Event()

    async def first_local_read() -> None:
        await release_read.wait()
        coordinator.async_set_updated_data(measured)

    coordinator._local_initial_read_task = hass.async_create_task(first_local_read())

    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    first_states: dict[str, str] = {}

    def record_first_state(event) -> None:
        state = event.data.get("new_state")
        if state is not None:
            first_states.setdefault(state.entity_id, state.state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record_first_state)

    def add_entities(entities, **kwargs) -> None:
        hass.async_create_task(platform.async_add_entities(entities, **kwargs))

    setup = hass.async_create_task(sensor.async_setup_entry(hass, entry, add_entities))
    await asyncio.sleep(0)
    release_read.set()
    await setup
    await hass.async_block_till_done()

    registry = platform.entities
    inverter = next(
        entity
        for entity in registry.values()
        if entity.unique_id == "1234567890_pv1_voltage"
    )
    bank = next(
        entity
        for entity in registry.values()
        if entity.unique_id == "1234567890_battery_bank_battery_bank_soc"
    )
    assert first_states[inverter.entity_id] == "321.0"
    assert first_states[bank.entity_id] == "74.0"
    registered_identifiers = {
        identifier
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        for domain, identifier in device.identifiers
        if domain == DOMAIN
    }
    assert "1234567890" in registered_identifiers
    assert "1234567890_battery_bank" in registered_identifiers
    coordinator.async_request_refresh.assert_not_awaited()
