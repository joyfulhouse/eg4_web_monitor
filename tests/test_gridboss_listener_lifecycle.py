"""Exercise entry topology dependencies through real HA listener dispatch."""

import logging
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.entity_component import EntityComponent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.coordinator import (
    STATION_LISTENER_CONTEXT,
    EG4DataUpdateCoordinator,
    device_listener_context,
)
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor


@pytest.mark.parametrize("sensor_key", ["consumption", "consumption_lifetime"])
@pytest.mark.parametrize("recognition", ["arrival", "type_change"])
async def test_gridboss_recognition_notifies_unchanged_inverters(
    hass, sensor_key, recognition
):
    """Recognition publishes metadata and latches it before disappearance/drop."""
    entry = MockConfigEntry(
        domain="eg4_web_monitor",
        data={"connection_type": "local", "dst_sync": False},
        options={},
    )
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.update_interval = None
    coordinator._last_listener_update_success = True
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.data = {
        "devices": {
            "INV": {"type": "inverter", "sensors": {sensor_key: 19.0}},
            "OTHER": {"type": "inverter", "sensors": {"yield": 20.0}},
            "GROUP": {"type": "parallel_group", "sensors": {}},
        }
    }
    if recognition == "type_change":
        coordinator.data["devices"]["GB"] = {"type": "unknown", "sensors": {}}
    sensor = EG4InverterSensor(coordinator, "INV", sensor_key)
    other_sensor = EG4InverterSensor(coordinator, "OTHER", "yield")
    component = EntityComponent(logging.getLogger(__name__), "sensor", hass)
    await component.async_add_entities([sensor, other_sensor])
    assert (
        hass.states.get(sensor.entity_id).attributes["state_class"]
        == "total_increasing"
    )

    callbacks = {key: MagicMock() for key in ("INV", "OTHER", "GROUP", "GB", "station")}
    for serial, callback in callbacks.items():
        context = (
            STATION_LISTENER_CONTEXT
            if serial == "station"
            else device_listener_context(serial)
        )
        coordinator.async_add_listener(callback, context)

    try:
        discovered = deepcopy(coordinator.data)
        discovered["devices"]["GB"] = {"type": "gridboss", "sensors": {}}
        coordinator.async_set_updated_data(discovered)
        await hass.async_block_till_done()
        # Inspect published state only: reading the getter would mask missed dispatch.
        state = hass.states.get(sensor.entity_id)
        assert state.state == "19.0"
        assert "state_class" not in state.attributes
        assert sensor._consumption_statistics_disabled
        assert (
            hass.states.get(other_sensor.entity_id).attributes["state_class"]
            == "total_increasing"
        )
        for serial in ("INV", "OTHER", "GB"):
            callbacks[serial].assert_called_once_with()
        callbacks["GROUP"].assert_not_called()
        callbacks["station"].assert_not_called()

        for callback in callbacks.values():
            callback.reset_mock()
        # Ordinary GridBOSS ticks must not fan out to unchanged inverters.
        tick = deepcopy(discovered)
        tick["devices"]["GB"]["sensors"]["power"] = 123
        coordinator.async_set_updated_data(tick)
        await hass.async_block_till_done()
        callbacks["GB"].assert_called_once_with()
        for serial in ("INV", "OTHER", "GROUP", "station"):
            callbacks[serial].assert_not_called()

        removed = deepcopy(tick)
        del removed["devices"]["GB"]
        coordinator.async_set_updated_data(removed)
        await hass.async_block_till_done()
        assert "state_class" not in hass.states.get(sensor.entity_id).attributes

        for callback in callbacks.values():
            callback.reset_mock()
        decreased = deepcopy(removed)
        decreased["devices"]["INV"]["sensors"][sensor_key] = 15.0
        coordinator.async_set_updated_data(decreased)
        await hass.async_block_till_done()
        state = hass.states.get(sensor.entity_id)
        assert state.state == "15.0"
        assert "state_class" not in state.attributes
        callbacks["INV"].assert_called_once_with()
        for serial in ("OTHER", "GROUP", "GB", "station"):
            callbacks[serial].assert_not_called()
    finally:
        await coordinator.async_shutdown()
