"""Golden ordering/error tests for optimistic write envelope semantics (#362).

Pinned contract for every ``EG4BaseSwitch`` write surface — switch actions,
pure-CLOUD function switches (both via ``_optimistic_write_envelope``), and
the LOCAL named-parameter path (``_execute_named_parameter_action``, the
dispatcher behind ``_execute_local_with_fallback``):

- write FAILS -> raise HomeAssistantError, clear optimistic state once,
  never seed the parameter cache. Exception (#301): the HYBRID fallback
  passes ``clear_optimistic_on_error=False`` so the optimistic state
  survives between the local failure and the cloud retry.
- write OK + refresh OK -> publish the fresh coordinator data (optimistic
  state cleared after the refresh completes). "Refresh OK" for a full
  coordinator refresh requires BOTH ``last_update_success`` AND a new data
  object identity — during the coordinator's 3-strike tolerance window the
  flag stays True while the refresh served the OLD data object unchanged.
- write OK + refresh FAILS (reported failure, raised exception, or a
  tolerated-stale refresh) -> the service call SUCCEEDS (never converted
  into a user-facing write failure), the optimistic state is RETAINED until
  fresh device data arrives (:meth:`EG4BaseSwitch._handle_coordinator_update`)
  or the retention TTL expires (firmware-NAK escape: #251/#331 precedent),
  matching the schedule time entities' retained-optimistic semantics.
"""

import logging
import time as time_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.eg4_web_monitor.base_entity as base_entity_module
from custom_components.eg4_web_monitor.base_entity import (
    RETAINED_OPTIMISTIC_TTL,
    EG4BaseSwitch,
)
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


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

    # A genuinely-successful coordinator refresh produces a NEW data object
    # (the real _async_update_data builds a fresh dict each cycle; only the
    # 3-strike tolerance window returns the old object unchanged).
    def _fresh_refresh() -> None:
        events.append("coordinator-refresh")
        coordinator.data = dict(coordinator.data)

    coordinator.async_refresh = AsyncMock(side_effect=_fresh_refresh)
    # The coordinator refresh helper reports success/failure (#362); the
    # default harness refresh succeeds.
    coordinator.async_refresh_device_parameters = AsyncMock(
        side_effect=lambda _serial: events.append("parameter-refresh") or True
    )
    coordinator.write_named_parameter = AsyncMock(
        side_effect=lambda *_args, **_kwargs: events.append("write") or None
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


# ── Retention TTL bound (#362 review round) ──────────────────────────


@pytest.mark.asyncio
async def test_arming_retention_sets_bounded_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retention is bounded: arming sets a monotonic TTL deadline."""
    before = time_module.monotonic()
    entity = await _make_retained_entity(monkeypatch)

    assert entity._retention_expires > before
    assert entity._retention_expires <= time_module.monotonic() + (
        RETAINED_OPTIMISTIC_TTL + 1.0
    )


@pytest.mark.asyncio
async def test_retained_state_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A firmware-silently-NAKed write (#251/#331 precedent) + one failed
    refresh must not wedge the entity forever: when every poll keeps
    returning the pre-write value (indistinguishable from a stale tick),
    the retention expires after the TTL, logs at WARNING, and the entity
    reverts to the reported state."""
    entity = await _make_retained_entity(monkeypatch, pre_write=False)
    entity._cache_value = False  # device still reports the pre-write value

    # Within the TTL: stale ticks keep the retained state.
    with caplog.at_level(logging.WARNING):
        entity._handle_coordinator_update()
        assert entity._optimistic_retained is True

        # Past the deadline: the retention expires with observability.
        entity._retention_expires = time_module.monotonic() - 1.0
        entity._handle_coordinator_update()

    assert entity._optimistic_retained is False
    assert entity._optimistic_state is None
    assert entity.is_on is False  # reverted to the reported state
    assert "expired without device confirmation" in caplog.text


# ── Tolerated-stale coordinator refresh (#362 review round) ──────────


@pytest.mark.asyncio
async def test_switch_write_ok_tolerated_stale_refresh_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """last_update_success LIES during the coordinator's 3-strike tolerance
    window (old data object served unchanged, flag still True): the envelope
    must detect the unchanged data identity and retain the optimistic state
    instead of publishing the stale data as if it were fresh."""
    events: list[str] = []
    entity, coordinator, inverter = _make_entity(events)
    entity._cache_value = False
    inverter.enable_test = AsyncMock(side_effect=lambda: events.append("write") or True)
    # Tolerance-window shape: refresh completes, flag stays True, data
    # object identity unchanged.
    coordinator.async_refresh = AsyncMock(
        side_effect=lambda: events.append("coordinator-refresh")
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", True
    )

    assert coordinator.last_update_success is True
    assert events == [
        "optimistic-set",
        "write",
        "inverter-refresh",
        "sleep",
        "coordinator-refresh",
    ]
    _assert_retained(entity, value=True)


@pytest.mark.asyncio
async def test_real_tolerance_window_refresh_retains(
    hass,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression against the REAL coordinator tolerance window (not a
    mocked last_update_success): the first UpdateFailed within the 3-strike
    tolerance returns the OLD self.data unchanged and keeps
    last_update_success True — the post-write refresh must still report
    failure so the optimistic state is retained."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Envelope Tolerance Test",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": SERIAL,
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        options={},
        entry_id="envelope_tolerance_test",
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "devices": {SERIAL: {"type": "inverter", "model": "FlexBOSS21"}},
        "parameters": {SERIAL: {}},
    }
    inverter = SimpleNamespace(
        refresh=AsyncMock(),
        enable_test=AsyncMock(return_value=True),
        transport=None,  # inspected by coordinator shutdown at teardown
    )
    coordinator._inverter_cache = {SERIAL: inverter}
    monkeypatch.setattr(
        coordinator,
        "_route_update_by_connection_type",
        AsyncMock(side_effect=UpdateFailed("transient transport error")),
    )

    events: list[str] = []
    entity = EnvelopeTestSwitch(coordinator, events)
    entity.async_write_ha_state = MagicMock()
    monkeypatch.setattr(base_entity_module.asyncio, "sleep", AsyncMock())

    await entity._execute_switch_action(
        "test action", "enable_test", "disable_test", True
    )

    # The tolerance window served the OLD data and kept the flag True...
    assert coordinator.last_update_success is True
    assert coordinator._consecutive_update_failures == 1
    # ...and the envelope still detected the stale refresh and retained.
    assert entity._optimistic_state is True
    assert entity._optimistic_retained is True


# ── LOCAL named-parameter path (#362 review round) ───────────────────


@pytest.mark.asyncio
async def test_named_parameter_success_clears_after_fresh_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL write ok + fresh coordinator refresh: publish fresh data (the
    optimistic state clears after the refresh), and the acknowledged value
    is seeded in place so concurrent cycles converge immediately."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    _patch_sleep(monkeypatch, events)

    await entity._execute_named_parameter_action("test action", "FUNC_TEST", True)

    assert events == [
        "optimistic-set",
        "write",
        "sleep",
        "coordinator-refresh",
        "clear",
    ]
    assert entity._optimistic_state is None
    assert entity._optimistic_retained is False
    assert coordinator.data["parameters"][SERIAL]["FUNC_TEST"] is True


@pytest.mark.asyncio
async def test_named_parameter_write_ok_stale_refresh_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The #362 revert on the highest-traffic path: LOCAL write ok + failed
    or tolerated-stale refresh must retain the optimistic state (a full
    rebuild replaces the parameters dict wholesale, wiping the in-place
    seed) instead of unconditionally clearing onto stale data."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    entity._cache_value = False
    # Tolerated-stale refresh: identity unchanged, flag still True.
    coordinator.async_refresh = AsyncMock(
        side_effect=lambda: events.append("coordinator-refresh")
    )
    _patch_sleep(monkeypatch, events)

    await entity._execute_named_parameter_action("test action", "FUNC_TEST", True)

    assert events == ["optimistic-set", "write", "sleep", "coordinator-refresh"]
    _assert_retained(entity, value=True)
    assert entity._pre_write_state is False
    # The in-place seed still happened (write acknowledged).
    assert coordinator.data["parameters"][SERIAL]["FUNC_TEST"] is True


@pytest.mark.asyncio
async def test_named_parameter_write_ok_refresh_raises_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising post-write refresh after an acknowledged LOCAL write is not
    a write failure: no raise, optimistic state retained."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.async_refresh = AsyncMock(side_effect=RuntimeError("refresh died"))
    _patch_sleep(monkeypatch, events)

    await entity._execute_named_parameter_action("test action", "FUNC_TEST", False)

    assert events == ["optimistic-set", "write", "sleep"]
    _assert_retained(entity, value=False)


@pytest.mark.asyncio
async def test_named_parameter_write_failure_clears_and_raises() -> None:
    """A failed LOCAL write raises, clears optimistic state once, and never
    arms retention (default clear_optimistic_on_error=True)."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.write_named_parameter = AsyncMock(
        side_effect=HomeAssistantError("Modbus timeout")
    )

    with pytest.raises(HomeAssistantError, match="Modbus timeout"):
        await entity._execute_named_parameter_action("test action", "FUNC_TEST", True)

    assert events == ["optimistic-set", "clear"]
    assert entity._optimistic_state is None
    assert entity._optimistic_retained is False


@pytest.mark.asyncio
async def test_named_parameter_write_failure_keeps_optimistic_for_cloud_retry() -> None:
    """#301 byte-for-byte: with clear_optimistic_on_error=False (a cloud
    retry follows), the local write failure re-raises WITHOUT clearing the
    optimistic state — no stale pre-write publish between the local failure
    and the cloud attempt."""
    events: list[str] = []
    entity, coordinator, _inverter = _make_entity(events)
    coordinator.write_named_parameter = AsyncMock(
        side_effect=HomeAssistantError("Modbus timeout")
    )

    with pytest.raises(HomeAssistantError, match="Modbus timeout"):
        await entity._execute_named_parameter_action(
            "test action", "FUNC_TEST", True, clear_optimistic_on_error=False
        )

    assert events == ["optimistic-set"]  # no clear published
    assert entity._optimistic_state is True
