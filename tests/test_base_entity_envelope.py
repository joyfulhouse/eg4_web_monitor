"""Characterization tests for optimistic cloud-write switch actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

import custom_components.eg4_web_monitor.base_entity as base_entity_module
from custom_components.eg4_web_monitor.base_entity import EG4BaseSwitch


SERIAL = "1234567890"


class EnvelopeTestSwitch(EG4BaseSwitch):
    """Concrete base switch that records optimistic-state assignments."""

    def __init__(self, coordinator: MagicMock, events: list[str]) -> None:
        """Initialize the test switch and attach its event recorder."""
        super().__init__(coordinator, SERIAL, "envelope", "Envelope")
        self._events = events

    @property
    def _optimistic_state(self) -> bool | None:
        """Return the recorded optimistic state."""
        return self._recorded_optimistic_state

    @_optimistic_state.setter
    def _optimistic_state(self, value: bool | None) -> None:
        self._recorded_optimistic_state = value
        events = self.__dict__.get("_events")
        if events is not None:
            events.append("optimistic-set" if value is not None else "clear")

    @property
    def is_on(self) -> bool:
        """Return the current test state."""
        return bool(self._optimistic_state)


def _make_entity(
    events: list[str],
) -> tuple[EnvelopeTestSwitch, MagicMock, SimpleNamespace]:
    """Build an entity with event-recording coordinator dependencies."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": {SERIAL: {"type": "inverter", "model": "FlexBOSS21"}},
        "parameters": {SERIAL: {}},
    }
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_refresh = AsyncMock(
        side_effect=lambda: events.append("coordinator-refresh")
    )
    coordinator.async_refresh_device_parameters = AsyncMock(
        side_effect=lambda _serial: events.append("parameter-refresh")
    )

    inverter = SimpleNamespace(
        refresh=AsyncMock(side_effect=lambda: events.append("inverter-refresh"))
    )
    coordinator.get_inverter_object = MagicMock(return_value=inverter)

    response = SimpleNamespace(success=True)
    client = MagicMock()
    client.api.control.control_function = AsyncMock(return_value=response)
    coordinator.client = client

    entity = EnvelopeTestSwitch(coordinator, events)
    published_states: list[bool | None] = []
    entity.async_write_ha_state = MagicMock(
        side_effect=lambda: published_states.append(entity._optimistic_state)
    )
    entity._published_states = published_states
    entity._seed_cloud_written_parameter = MagicMock(
        side_effect=lambda _key, _value: events.append("seed")
    )
    return entity, coordinator, inverter


def _patch_sleep(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    """Replace the API propagation delay with an event-recording mock."""
    monkeypatch.setattr(
        base_entity_module.asyncio,
        "sleep",
        AsyncMock(side_effect=lambda _delay: events.append("sleep")),
    )


def _assert_state_write_counts(
    entity: EnvelopeTestSwitch,
    *,
    optimistic_value: bool,
    clear_count: int,
) -> None:
    """Assert optimistic and cleared Home Assistant state publications."""
    assert entity._published_states == [optimistic_value, *([None] * clear_count)]
    assert entity.async_write_ha_state.call_count == clear_count + 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refresh_params", "final_refresh"),
    [(False, "coordinator-refresh"), (True, "parameter-refresh")],
)
async def test_switch_success_order_and_state_writes(
    monkeypatch: pytest.MonkeyPatch,
    refresh_params: bool,
    final_refresh: str,
) -> None:
    """Switch writes seed and pre-refresh before delay and final refresh."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action",
        "enable_test",
        "disable_test",
        True,
        refresh_params=refresh_params,
        api_delay=0.25,
        seed_param_key="FUNC_TEST",
    )

    assert events == [
        "optimistic-set",
        "write",
        "seed",
        "inverter-refresh",
        "sleep",
        final_refresh,
        "clear",
    ]
    _assert_state_write_counts(entity, optimistic_value=True, clear_count=1)
    entity._seed_cloud_written_parameter.assert_called_once_with("FUNC_TEST", True)
    base_entity_module.asyncio.sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_switch_skips_seed_without_parameter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switch writes do not seed when no parameter-cache key is supplied."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", True
    )

    assert events == [
        "optimistic-set",
        "write",
        "inverter-refresh",
        "sleep",
        "coordinator-refresh",
        "clear",
    ]
    entity._seed_cloud_written_parameter.assert_not_called()


@pytest.mark.asyncio
async def test_switch_method_not_found_clears_once() -> None:
    """Switch method lookup failures clear optimistic state once."""
    events: list[str] = []
    entity, _coordinator, _inverter = _make_entity(events)

    with pytest.raises(
        HomeAssistantError, match="^Method missing_method not found on inverter$"
    ):
        await entity._execute_switch_action(
            "test action", "missing_method", "disable_test", True
        )

    assert events == ["optimistic-set", "clear"]
    _assert_state_write_counts(entity, optimistic_value=True, clear_count=1)


@pytest.mark.asyncio
async def test_switch_false_success_clears_once() -> None:
    """Switch false-success failures clear optimistic state once."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(
        side_effect=lambda: events.append("write") or False
    )

    with pytest.raises(HomeAssistantError, match="^Failed to enabling test action$"):
        await entity._execute_switch_action(
            "test action", "enable_test", "disable_test", True
        )

    assert events == ["optimistic-set", "write", "clear"]
    _assert_state_write_counts(entity, optimistic_value=True, clear_count=1)


@pytest.mark.asyncio
async def test_switch_plain_exception_is_wrapped() -> None:
    """Plain switch write exceptions become HomeAssistantError failures."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)

    async def raise_write_error() -> bool:
        events.append("write")
        raise RuntimeError("write exploded")

    inverter.disable_test = AsyncMock(side_effect=raise_write_error)

    with pytest.raises(
        HomeAssistantError,
        match="^Failed to disabling test action: write exploded$",
    ):
        await entity._execute_switch_action(
            "test action", "enable_test", "disable_test", False
        )

    assert events == ["optimistic-set", "write", "clear"]
    _assert_state_write_counts(entity, optimistic_value=False, clear_count=1)


@pytest.mark.asyncio
async def test_cloud_function_success_order_and_state_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud function writes seed before delay and parameter refresh."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.client.api.control.control_function.side_effect = (
        lambda _serial, _parameter, _value: (
            events.append("write") or SimpleNamespace(success=True)
        )
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_cloud_function_action(
        "test action",
        "FUNC_TEST",
        True,
        api_delay=0.25,
        seed_param_key="FUNC_TEST",
    )

    assert events == [
        "optimistic-set",
        "write",
        "seed",
        "sleep",
        "parameter-refresh",
        "clear",
    ]
    _assert_state_write_counts(entity, optimistic_value=True, clear_count=1)
    entity._seed_cloud_written_parameter.assert_called_once_with("FUNC_TEST", True)
    base_entity_module.asyncio.sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_cloud_function_skips_seed_without_parameter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud function writes skip seeding when no key is supplied."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.client.api.control.control_function.side_effect = (
        lambda _serial, _parameter, _value: (
            events.append("write") or SimpleNamespace(success=True)
        )
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_cloud_function_action("test action", "FUNC_TEST", True)

    assert events == [
        "optimistic-set",
        "write",
        "sleep",
        "parameter-refresh",
        "clear",
    ]
    entity._seed_cloud_written_parameter.assert_not_called()


@pytest.mark.asyncio
async def test_cloud_function_false_success_clears_once() -> None:
    """Cloud false-success failures clear optimistic state once."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.client.api.control.control_function.side_effect = (
        lambda _serial, _parameter, _value: (
            events.append("write") or SimpleNamespace(success=False)
        )
    )

    with pytest.raises(HomeAssistantError, match="^Failed to disabling test action$"):
        await entity._execute_cloud_function_action("test action", "FUNC_TEST", False)

    assert events == ["optimistic-set", "write", "clear"]
    _assert_state_write_counts(entity, optimistic_value=False, clear_count=1)


@pytest.mark.asyncio
async def test_cloud_function_plain_exception_is_wrapped() -> None:
    """Plain cloud function exceptions become HomeAssistantError failures."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)

    async def raise_write_error(
        _serial: str, _parameter: str, _value: bool
    ) -> SimpleNamespace:
        events.append("write")
        raise RuntimeError("write exploded")

    coordinator.client.api.control.control_function.side_effect = raise_write_error

    with pytest.raises(
        HomeAssistantError,
        match="^Failed to enabling test action: write exploded$",
    ):
        await entity._execute_cloud_function_action("test action", "FUNC_TEST", True)

    assert events == ["optimistic-set", "write", "clear"]
    _assert_state_write_counts(entity, optimistic_value=True, clear_count=1)


@pytest.mark.asyncio
async def test_cloud_function_missing_client_fails_before_optimistic_state() -> None:
    """The cloud-client precondition runs before optimistic state is set."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.client = None

    with pytest.raises(
        HomeAssistantError, match="^No cloud API available for test action$"
    ):
        await entity._execute_cloud_function_action("test action", "FUNC_TEST", True)

    assert events == []
    assert entity.async_write_ha_state.call_count == 0
