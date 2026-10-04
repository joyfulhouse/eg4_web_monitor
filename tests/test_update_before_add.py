"""Coordinator entity setup uses initial data without requesting a refresh."""

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.eg4_web_monitor import sensor, switch
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator_local import LocalTransportMixin


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


async def test_local_first_sensor_state_uses_real_ha_startup_path(hass):
    """Observe first LOCAL states through HA's refresh and platform forwarding."""
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
    device_registry = dr.async_get(hass)
    for identifier in ("1234567890", "1234567890_battery_bank"):
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, identifier)},
            name=identifier,
            manufacturer="EG4 Electronics",
            model="FlexBOSS21",
        )
    release_read = hass.loop.create_future()
    read_started = hass.loop.create_future()
    first_states: dict[str, str] = {}
    state_history: dict[str, list[str]] = {}
    first_target_state = hass.loop.create_future()

    def record_first_state(event) -> None:
        state = event.data.get("new_state")
        if state is None:
            return
        if "pv1_voltage" in state.entity_id or "battery_bank_soc" in state.entity_id:
            first_states.setdefault(state.entity_id, state.state)
            state_history.setdefault(state.entity_id, []).append(state.state)
            if not first_target_state.done():
                first_target_state.set_result(None)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record_first_state)

    async def controlled_local_read(coordinator, config, processed, availability):
        if not read_started.done():
            read_started.set_result(None)
        await release_read
        serial = config["serial"]
        processed["devices"][serial]["sensors"].update(
            {
                "pv1_voltage": 321.0,
                "battery_bank_soc": 74.0,
                "battery_bank_count": 4,
            }
        )
        availability[serial] = True

    try:
        with patch.object(
            LocalTransportMixin,
            "_process_single_local_device",
            controlled_local_read,
        ):
            setup = hass.async_create_task(
                hass.config_entries.async_setup(entry.entry_id)
            )
            await asyncio.wait_for(read_started, timeout=10)
            try:
                await asyncio.wait_for(first_target_state, timeout=0.5)
            except TimeoutError:
                pass
            release_read.set_result(None)
            assert await asyncio.wait_for(setup, timeout=30)
            await hass.async_block_till_done()
    finally:
        if not release_read.done():
            release_read.set_result(None)

    inverter_state = next(
        state for entity_id, state in first_states.items() if "pv1_voltage" in entity_id
    )
    bank_state = next(
        state
        for entity_id, state in first_states.items()
        if "battery_bank_soc" in entity_id
    )
    assert inverter_state == "unknown"
    assert bank_state == "unknown"
    for entity_id, expected in (
        (next(key for key in first_states if "pv1_voltage" in key), "321.0"),
        (next(key for key in first_states if "battery_bank_soc" in key), "74.0"),
    ):
        assert expected in state_history[entity_id]
