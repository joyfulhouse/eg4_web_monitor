"""Regression and benchmark coverage for coordinator listener fan-out."""

import asyncio
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from custom_components.eg4_web_monitor.base_entity import (
    EG4BatteryEntity,
    EG4DeviceEntity,
    EG4StationEntity,
)
from custom_components.eg4_web_monitor.coordinator import (
    DISCOVERY_LISTENER_CONTEXT,
    STATION_LISTENER_CONTEXT,
    EG4DataUpdateCoordinator,
    _listener_contexts_for_data_change,
    device_listener_context,
)
from custom_components.eg4_web_monitor.update import EG4FirmwareUpdateEntity


def _bare_coordinator(data: dict | None = None) -> EG4DataUpdateCoordinator:
    """Create only the listener-facing portion of a coordinator."""
    coordinator = object.__new__(EG4DataUpdateCoordinator)
    coordinator.data = data
    coordinator._listeners = {}
    coordinator._pending_listener_contexts = None
    coordinator._active_listener_contexts = None
    coordinator._last_listener_update_success = True
    coordinator.last_update_success = True
    # The composed production path (#527) overlays retained parameter write
    # seeds immediately before publishing; a bare coordinator needs the state.
    coordinator._parameter_write_seeds = {}
    coordinator._parameter_write_generation = 0
    return coordinator


def test_changed_data_contexts_ignore_tick_metadata_and_carried_device() -> None:
    """Only a materially changed device is selected on a fastest-transport tick."""
    old = {
        "devices": {
            "FAST": {"sensors": {"power": 100, "last_polled": "t1"}},
            "SLOW": {"sensors": {"power": 200, "last_polled": "t0"}},
        },
        "parameters": {"FAST": {"mode": 1}, "SLOW": {"mode": 2}},
        "station": {"name": "Plant"},
        "last_update": "tick-1",
        "connection_type": "local",
    }
    new = deepcopy(old)
    new["last_update"] = "tick-2"
    new["devices"]["FAST"]["sensors"]["power"] = 101

    assert _listener_contexts_for_data_change(old, new) == {
        device_listener_context("FAST"),
        DISCOVERY_LISTENER_CONTEXT,
    }


def test_parameter_station_and_unknown_top_level_changes_are_not_suppressed() -> None:
    """Parameter, station, and unclassified transitions reach their consumers."""
    old = {
        "devices": {"A": {"sensors": {"power": 1}}},
        "parameters": {"A": {"mode": 1}},
        "station": {"name": "Old"},
        "last_update": "tick-1",
        "connection_type": "local",
    }

    parameter_new = deepcopy(old)
    parameter_new["parameters"]["A"]["mode"] = 2
    assert _listener_contexts_for_data_change(old, parameter_new) == {
        device_listener_context("A"),
        DISCOVERY_LISTENER_CONTEXT,
    }

    station_new = deepcopy(old)
    station_new["station"]["name"] = "New"
    assert _listener_contexts_for_data_change(old, station_new) == {
        STATION_LISTENER_CONTEXT
    }

    unknown_new = deepcopy(old)
    unknown_new["connection_type"] = "hybrid"
    assert _listener_contexts_for_data_change(old, unknown_new) is None


def test_listener_fanout_benchmark_skips_unchanged_device_callbacks() -> None:
    """A 300-entity mixed tick calls 150 changed entities, not all 300."""
    coordinator = _bare_coordinator(
        {
            "devices": {
                "FAST": {"sensors": {"power": 101}},
                "SLOW": {"sensors": {"power": 200}},
            }
        }
    )
    fast_callbacks = [MagicMock() for _ in range(150)]
    slow_callbacks = [MagicMock() for _ in range(150)]
    discovery_callback = MagicMock()
    unscoped_callback = MagicMock()
    listener_id = 0
    for callback in fast_callbacks:
        listener_id += 1
        coordinator._listeners[listener_id] = (
            callback,
            device_listener_context("FAST"),
        )
    for callback in slow_callbacks:
        listener_id += 1
        coordinator._listeners[listener_id] = (
            callback,
            device_listener_context("SLOW"),
        )
    coordinator._listeners[301] = (
        discovery_callback,
        DISCOVERY_LISTENER_CONTEXT,
    )
    coordinator._listeners[302] = (unscoped_callback, None)
    coordinator._pending_listener_contexts = {
        device_listener_context("FAST"),
        DISCOVERY_LISTENER_CONTEXT,
    }

    coordinator.async_update_listeners()

    assert sum(callback.call_count for callback in fast_callbacks) == 150
    assert sum(callback.call_count for callback in slow_callbacks) == 0
    discovery_callback.assert_called_once_with()
    unscoped_callback.assert_called_once_with()


def test_unchanged_tick_skips_scoped_discovery_and_entity_work() -> None:
    """A carried-data-only tick retains unknown listeners but skips scoped work."""
    coordinator = _bare_coordinator({"devices": {"SLOW": {"sensors": {}}}})
    entity_callback = MagicMock()
    discovery_callback = MagicMock()
    unscoped_callback = MagicMock()
    coordinator._listeners = {
        1: (entity_callback, device_listener_context("SLOW")),
        2: (discovery_callback, DISCOVERY_LISTENER_CONTEXT),
        3: (unscoped_callback, None),
    }
    coordinator._pending_listener_contexts = set()

    coordinator.async_update_listeners()

    entity_callback.assert_not_called()
    discovery_callback.assert_not_called()
    unscoped_callback.assert_called_once_with()


def test_foreign_listener_context_retains_default_fanout() -> None:
    """Contexts outside this integration's namespace remain safety listeners."""
    coordinator = _bare_coordinator({"devices": {"FAST": {"sensors": {}}}})
    foreign_hashable_callback = MagicMock()
    foreign_unhashable_callback = MagicMock()
    coordinator._listeners = {
        1: (foreign_hashable_callback, ("foreign_consumer", "opaque_scope")),
        2: (foreign_unhashable_callback, {"opaque": "scope"}),
    }
    coordinator._pending_listener_contexts = {
        device_listener_context("FAST"),
        DISCOVERY_LISTENER_CONTEXT,
    }

    coordinator.async_update_listeners()

    foreign_hashable_callback.assert_called_once_with()
    foreign_unhashable_callback.assert_called_once_with()


def test_availability_transition_notifies_every_listener_once() -> None:
    """Failure/recovery transitions bypass value filtering; repeated failure does not."""
    coordinator = _bare_coordinator()
    scoped_callback = MagicMock()
    unscoped_callback = MagicMock()
    coordinator._listeners = {
        1: (scoped_callback, device_listener_context("SLOW")),
        2: (unscoped_callback, None),
    }
    coordinator.last_update_success = False

    coordinator.async_update_listeners()

    scoped_callback.assert_called_once_with()
    unscoped_callback.assert_called_once_with()

    scoped_callback.reset_mock()
    unscoped_callback.reset_mock()
    # Home Assistant suppresses listener dispatch after a repeated failure.
    # Explicitly stage an unchanged result to exercise the defensive branch.
    coordinator._pending_listener_contexts = set()
    coordinator.async_update_listeners()
    scoped_callback.assert_not_called()
    unscoped_callback.assert_called_once_with()


def test_idle_public_listener_dispatch_retains_default_fanout() -> None:
    """A public dispatch outside a classified refresh must notify all listeners."""
    coordinator = _bare_coordinator()
    scoped_callback = MagicMock()
    coordinator._listeners = {
        1: (scoped_callback, device_listener_context("SLOW")),
    }

    coordinator.async_update_listeners()

    scoped_callback.assert_called_once_with()


@pytest.mark.asyncio
async def test_inflight_refresh_does_not_mask_public_listener_dispatch() -> None:
    """Awaiting transport I/O must not expose an empty scope to other dispatches."""
    data = {"devices": {"SLOW": {"sensors": {"power": 200}}}}
    coordinator = _bare_coordinator(data)
    coordinator._consecutive_update_failures = 0
    coordinator.clear_device_info_caches = MagicMock()
    route_started = asyncio.Event()
    release_route = asyncio.Event()

    async def _route_update() -> dict:
        route_started.set()
        await release_route.wait()
        return deepcopy(data)

    coordinator._route_update_by_connection_type = _route_update
    scoped_callback = MagicMock()
    coordinator._listeners = {
        1: (scoped_callback, device_listener_context("SLOW")),
    }

    refresh = asyncio.create_task(coordinator._async_update_data())
    await route_started.wait()
    coordinator.async_update_listeners()
    release_route.set()

    assert await refresh == data
    scoped_callback.assert_called_once_with()


def test_changed_device_iteration_is_limited_during_discovery_dispatch() -> None:
    """Discovery scans receive only serials changed in the active dispatch."""
    coordinator = _bare_coordinator(
        {
            "devices": {
                "FAST": {"sensors": {"power": 101}},
                "SLOW": {"sensors": {"power": 200}},
            }
        }
    )
    seen: list[str] = []

    def discovery_callback() -> None:
        seen.extend(serial for serial, _ in coordinator.iter_listener_changed_devices())

    coordinator._listeners = {1: (discovery_callback, DISCOVERY_LISTENER_CONTEXT)}
    coordinator._pending_listener_contexts = {
        device_listener_context("FAST"),
        DISCOVERY_LISTENER_CONTEXT,
    }

    coordinator.async_update_listeners()

    assert seen == ["FAST"]


def test_entity_bases_register_device_and_station_contexts() -> None:
    """High-cardinality read entities identify their smallest update scope."""
    coordinator = MagicMock(spec=EG4DataUpdateCoordinator)
    coordinator.data = {
        "devices": {
            "INV": {
                "type": "inverter",
                "model": "Test",
                "sensors": {},
                "batteries": {"BAT": {}},
            }
        }
    }
    coordinator.plant_id = "plant"

    assert EG4DeviceEntity(coordinator, "INV").coordinator_context == (
        device_listener_context("INV")
    )
    assert EG4BatteryEntity(coordinator, "INV", "BAT").coordinator_context == (
        device_listener_context("INV")
    )
    assert EG4StationEntity(coordinator).coordinator_context == STATION_LISTENER_CONTEXT
    assert EG4FirmwareUpdateEntity(
        coordinator, "INV"
    ).coordinator_context == device_listener_context("INV")
