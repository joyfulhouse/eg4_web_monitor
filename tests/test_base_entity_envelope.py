"""Golden ordering/error tests for optimistic write envelope semantics (#362).

Pinned contract for every write flowing through
``EG4BaseSwitch._optimistic_write_envelope`` (switch actions and pure-CLOUD
function switches):

- write FAILS -> raise HomeAssistantError, clear optimistic state once,
  never seed the parameter cache.
- write OK + refresh OK -> publish the fresh coordinator data (optimistic
  state cleared after the refresh completes).
- write OK + refresh FAILS (reported failure or raised exception) -> the
  service call SUCCEEDS (never converted into a user-facing write failure),
  the optimistic state is RETAINED until fresh device data arrives
  (:meth:`EG4BaseSwitch._handle_coordinator_update`), matching the schedule
  time entities' retained-optimistic semantics.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

import custom_components.eg4_web_monitor.base_entity as base_entity_module
from custom_components.eg4_web_monitor.base_entity import EG4BaseSwitch


SERIAL = "1234567890"


class EnvelopeTestSwitch(EG4BaseSwitch):
    """Concrete base switch that records optimistic-state assignments."""

    # Canned cache-decoded state; overriding _cache_state keeps the
    # production peek helper (which toggles _optimistic_state) from
    # polluting the recorded event stream.
    _cache_value: bool | None = None

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

    def _cache_state(self) -> bool | None:
        """Return the canned cache-decoded state."""
        return self._cache_value

    @property
    def is_on(self) -> bool:
        """Return the current test state."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        return bool(self._cache_value)


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
    # The coordinator refresh helper reports success/failure (#362); the
    # default harness refresh succeeds.
    coordinator.async_refresh_device_parameters = AsyncMock(
        side_effect=lambda _serial: events.append("parameter-refresh") or True
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
async def test_switch_write_failure_never_seeds() -> None:
    """A failed write must not seed the parameter cache (#310 seed is
    an acknowledgement of a SUCCESSFUL write; seeding on failure would
    publish a state the device never confirmed)."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(
        side_effect=lambda: events.append("write") or False
    )

    with pytest.raises(HomeAssistantError):
        await entity._execute_switch_action(
            "test action",
            "enable_test",
            "disable_test",
            True,
            seed_param_key="FUNC_TEST",
        )

    entity._seed_cloud_written_parameter.assert_not_called()
    assert events == ["optimistic-set", "write", "clear"]


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
async def test_cloud_function_write_failure_never_seeds() -> None:
    """A failed cloud function write must not seed the parameter cache."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.client.api.control.control_function.side_effect = (
        lambda _serial, _parameter, _value: (
            events.append("write") or SimpleNamespace(success=False)
        )
    )

    with pytest.raises(HomeAssistantError):
        await entity._execute_cloud_function_action(
            "test action", "FUNC_TEST", False, seed_param_key="FUNC_TEST"
        )

    entity._seed_cloud_written_parameter.assert_not_called()
    assert events == ["optimistic-set", "write", "clear"]


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


# ── Write-ok + refresh-fail retention (#362) ─────────────────────────


def _assert_retained(entity: EnvelopeTestSwitch, *, value: bool) -> None:
    """Assert the acknowledged write's optimistic state was retained."""
    assert entity._optimistic_state is value
    assert entity._optimistic_retained is True
    assert entity.is_on is value


@pytest.mark.asyncio
async def test_switch_write_ok_refresh_reports_failure_retains_optimistic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reported parameter-refresh failure after an acknowledged write must
    NOT raise and must retain the optimistic state (#362): the hardware holds
    the new value; publishing the stale pre-write cache would be a silent
    revert while the service reported success."""
    events: list[str] = []
    entity, coordinator, inverter = _make_entity(events)
    entity._cache_value = False  # stale pre-write cache value
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)
    coordinator.async_refresh_device_parameters = AsyncMock(
        side_effect=lambda _serial: events.append("parameter-refresh") or False
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action",
        "enable_test",
        "disable_test",
        True,
        refresh_params=True,
        seed_param_key="FUNC_TEST",
    )

    # No "clear" event: optimistic state survives the failed refresh. The
    # seed still fires — it acknowledges the WRITE, not the refresh.
    assert events == [
        "optimistic-set",
        "write",
        "seed",
        "inverter-refresh",
        "sleep",
        "parameter-refresh",
    ]
    _assert_retained(entity, value=True)
    assert entity._pre_write_state is False
    assert entity._published_states == [True, True]


@pytest.mark.asyncio
async def test_switch_write_ok_coordinator_refresh_unsuccessful_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A data refresh that leaves the coordinator unsuccessful retains the
    optimistic state instead of publishing stale data."""
    events: list[str] = []
    entity, coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)

    async def _failing_refresh() -> None:
        events.append("coordinator-refresh")
        coordinator.last_update_success = False

    coordinator.async_refresh = AsyncMock(side_effect=_failing_refresh)
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
    ]
    _assert_retained(entity, value=True)


@pytest.mark.asyncio
async def test_switch_write_ok_pre_delay_refresh_raises_is_not_a_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #362 point 2: a transient inverter.refresh() error after a
    successful write must not raise 'Failed to enable X' nor clear the
    optimistic state — the hardware accepted the command."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)

    async def _exploding_refresh() -> None:
        events.append("inverter-refresh")
        raise ConnectionError("transient refresh error")

    inverter.refresh = AsyncMock(side_effect=_exploding_refresh)
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", True
    )

    assert events == ["optimistic-set", "write", "inverter-refresh"]
    _assert_retained(entity, value=True)


@pytest.mark.asyncio
async def test_switch_write_ok_refresh_raises_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising final refresh is treated exactly like a reported failure."""
    events: list[str] = []
    entity, coordinator, inverter = _make_entity(events)
    inverter.disable_test = AsyncMock(
        side_effect=lambda: events.append("write") or True
    )
    coordinator.async_refresh = AsyncMock(side_effect=RuntimeError("refresh died"))
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", False
    )

    assert events == ["optimistic-set", "write", "inverter-refresh", "sleep"]
    _assert_retained(entity, value=False)


@pytest.mark.asyncio
async def test_cloud_function_write_ok_refresh_fail_retains_optimistic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure-CLOUD function switches (not cache-seeded by design) retain the
    optimistic state on write-ok + refresh-fail instead of reverting to the
    stale pre-write parameter value (#362 point 1)."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    entity._cache_value = False
    coordinator.client.api.control.control_function.side_effect = (
        lambda _serial, _parameter, _value: (
            events.append("write") or SimpleNamespace(success=True)
        )
    )
    coordinator.async_refresh_device_parameters = AsyncMock(
        side_effect=lambda _serial: events.append("parameter-refresh") or False
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_cloud_function_action("test action", "FUNC_TEST", True)

    assert events == ["optimistic-set", "write", "sleep", "parameter-refresh"]
    _assert_retained(entity, value=True)
    assert entity._pre_write_state is False


@pytest.mark.asyncio
async def test_write_failure_resets_retention_flags() -> None:
    """A failed write clears optimistic state and never arms retention."""
    events: list[str] = []
    entity, _coordinator, inverter = _make_entity(events)
    inverter.enable_test = AsyncMock(
        side_effect=lambda: events.append("write") or False
    )

    with pytest.raises(HomeAssistantError):
        await entity._execute_switch_action(
            "test action", "enable_test", "disable_test", True
        )

    assert entity._optimistic_state is None
    assert entity._optimistic_retained is False
    assert entity._pre_write_state is None


# ── Retained-state clearing on coordinator updates (#362) ────────────


async def _make_retained_entity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pre_write: bool | None = False,
) -> EnvelopeTestSwitch:
    """Build an entity holding a retained optimistic ON state."""
    events: list[str] = []
    entity, coordinator, inverter = _make_entity(events)
    entity._cache_value = pre_write
    inverter.enable_test = AsyncMock(return_value=True)
    coordinator.async_refresh_device_parameters = AsyncMock(return_value=False)
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", True, refresh_params=True
    )
    assert entity._optimistic_retained is True
    return entity


@pytest.mark.asyncio
async def test_retained_state_clears_when_cache_converges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh data carrying the written value ends the retention."""
    entity = await _make_retained_entity(monkeypatch)

    entity._cache_value = True  # fresh data: the write came back
    entity._handle_coordinator_update()

    assert entity._optimistic_state is None
    assert entity._optimistic_retained is False
    assert entity._pre_write_state is None
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_retained_state_clears_on_other_fresh_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any value that no longer decodes to the pre-write state is fresh
    data (e.g. the cache key disappearing) and ends the retention."""
    entity = await _make_retained_entity(monkeypatch, pre_write=False)

    entity._cache_value = None  # no longer the pre-write value
    entity._handle_coordinator_update()

    assert entity._optimistic_state is None
    assert entity._optimistic_retained is False


@pytest.mark.asyncio
async def test_retained_state_survives_stale_coordinator_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinator ticks still carrying the stale pre-write value must NOT
    clear the retained state — that would be the #362 revert, delayed one
    poll tick."""
    entity = await _make_retained_entity(monkeypatch, pre_write=False)

    entity._cache_value = False  # stale: still the pre-write value
    entity._handle_coordinator_update()

    assert entity._optimistic_state is True
    assert entity._optimistic_retained is True
    assert entity.is_on is True


def test_cache_state_peeks_past_optimistic_state() -> None:
    """The default _cache_state() decodes is_on with the optimistic state
    masked off, and restores it afterwards."""

    class PeekSwitch(EG4BaseSwitch):
        @property
        def is_on(self) -> bool | None:
            if self._optimistic_state is not None:
                return self._optimistic_state
            value = self._parameter_data.get("FUNC_TEST")
            return None if value is None else bool(value)

    coordinator = MagicMock()
    coordinator.data = {
        "devices": {SERIAL: {"type": "inverter", "model": "FlexBOSS21"}},
        "parameters": {SERIAL: {"FUNC_TEST": False}},
    }
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entity = PeekSwitch(coordinator, SERIAL, "peek", "Peek")

    entity._optimistic_state = True
    assert entity.is_on is True
    assert entity._cache_state() is False
    assert entity._optimistic_state is True  # restored after the peek
