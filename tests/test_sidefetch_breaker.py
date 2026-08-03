"""Shared connectivity breaker for supplemental cloud side-fetches (#511).

Each side-fetch bounds its cloud call with a timeout, but on a genuinely
unreachable portal every one of them still burned its full timeout every
poll cycle, serially. The breaker shares one connectivity verdict: after
three consecutive connectivity-class failures the side-fetches skip
instantly for a cooldown, then a half-open probe decides. Only
connectivity-class failures count — an HTTP-level API answer proves the
portal is reachable and closes the breaker like a success does.
"""

import asyncio
import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from pylxpweb.exceptions import LuxpowerAPIError, LuxpowerConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import coordinator_mixins
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mixins import (
    _SIDEFETCH_BREAKER_THRESHOLD,
    _CloudSidefetchSkipped,
)


@pytest.fixture
async def coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u",
            "password": "p",
            "connection_type": "http",
            "plant_id": "1",
        },
    )
    entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, entry)
    coord.client = None
    return coord


async def _ok():
    return "payload"


async def _timeout():
    raise TimeoutError


async def _aiohttp_error():
    raise aiohttp.ClientError("transport down")


async def _pylxpweb_conn_error():
    raise LuxpowerConnectionError("no route to portal")


async def _api_error():
    raise LuxpowerAPIError("API error (HTTP 400): bad request")


async def _trip(coordinator, failing=_timeout):
    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD):
        with pytest.raises(Exception):
            await coordinator._breakered_cloud_call(failing(), timeout=5)


@pytest.mark.parametrize("failing", [_timeout, _aiohttp_error, _pylxpweb_conn_error])
async def test_breaker_opens_after_threshold_connectivity_failures(
    coordinator, failing
):
    """Each connectivity error class trips it; the next call skips instantly."""
    await _trip(coordinator, failing)

    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_ok(), timeout=5)


async def test_success_resets_the_streak(coordinator):
    """N-1 failures then a success -> streak gone; N-1 more do not open it."""
    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD - 1):
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"
    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD - 1):
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=5)

    # Still closed: this call runs (and succeeds) rather than skipping.
    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_api_error_counts_as_reachability(coordinator):
    """An HTTP-level answer proves the portal is up: resets, never opens."""
    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD * 2):
        with pytest.raises(LuxpowerAPIError):
            await coordinator._breakered_cloud_call(_api_error(), timeout=5)

    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_cooldown_expiry_half_opens_and_success_closes(coordinator):
    """After the cooldown the next call really runs; success closes fully."""
    await _trip(coordinator)
    opened_at = coordinator._sidefetch_open_until
    assert opened_at is not None

    with patch.object(coordinator_mixins.time, "monotonic", return_value=opened_at + 1):
        assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"
    assert coordinator._sidefetch_open_until is None

    # Fully closed: a single new failure does not skip the following call.
    with pytest.raises(TimeoutError):
        await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_half_open_single_failure_reopens_immediately(coordinator):
    """ONE connectivity failure at half-open re-opens for a full cooldown.

    A real half-open: the post-cooldown probe gets one strike, not another
    three-strike round — otherwise every cooldown expiry would burn up to
    three full fetch timeouts before pausing again (review P2).
    """
    await _trip(coordinator)
    opened_at = coordinator._sidefetch_open_until
    with patch.object(coordinator_mixins.time, "monotonic", return_value=opened_at + 1):
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=5)
        assert coordinator._sidefetch_open_until is not None
        # And the very next call skips instantly.
        with pytest.raises(_CloudSidefetchSkipped):
            await coordinator._breakered_cloud_call(_ok(), timeout=5)


async def test_gathered_all_connectivity_failures_count(coordinator):
    """gather(return_exceptions=True) hiding connectivity errors still trips.

    Review P1: a fast-failing outage returns the exceptions INSIDE a normal
    gather result, which used to reset the streak — the breaker could never
    open. With the classify hook, three all-connectivity gather results open
    it.
    """
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        _classify_gathered_responses,
    )

    async def _gathered():
        return [LuxpowerConnectionError("down"), TimeoutError()]

    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD):
        await coordinator._breakered_cloud_call(
            _gathered(), timeout=5, classify=_classify_gathered_responses
        )

    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_ok(), timeout=5)


async def test_gathered_mixed_result_proves_reachability(coordinator):
    """One real payload (or HTTP-level error) in the gather resets the streak."""
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        _classify_gathered_responses,
    )

    async def _mixed():
        return [LuxpowerConnectionError("down"), {"real": "payload"}]

    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD * 2):
        await coordinator._breakered_cloud_call(
            _mixed(), timeout=5, classify=_classify_gathered_responses
        )

    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_all_none_store_result_is_neutral(coordinator):
    """A failed store getter's all-None SCHEMA dict must not reset the streak.

    Delta-review P1: pylxpweb's getters swallow internal per-range errors
    and return a NON-EMPTY dict with every value None — truthy, so a
    truthiness classify wrongly counted it as reachability. Only a non-None
    value proves the portal answered.
    """
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        _classify_store_limits,
    )

    async def _failed_getter():
        # The real shape: schema keys present, every value None.
        return {"start_soc": None, "end_soc": None, "enabled": None}

    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD - 1):
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    # The neutral result must NOT reset the streak...
    await coordinator._breakered_cloud_call(
        _failed_getter(), timeout=5, classify=_classify_store_limits
    )
    # ...so one more connectivity failure opens the breaker.
    with pytest.raises(TimeoutError):
        await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_ok(), timeout=5)


async def test_store_result_with_false_value_proves_reachability(coordinator):
    """False and 0 are real portal answers — they close the breaker."""
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        _classify_store_limits,
    )

    async def _real_answer():
        return {"start_soc": None, "enabled": False}

    for _ in range(_SIDEFETCH_BREAKER_THRESHOLD - 1):
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    await coordinator._breakered_cloud_call(
        _real_answer(), timeout=5, classify=_classify_store_limits
    )
    # Streak reset: the next failure is #1, not #3 — no skip follows.
    with pytest.raises(TimeoutError):
        await coordinator._breakered_cloud_call(_timeout(), timeout=5)
    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_concurrent_success_closes_an_open_breaker(coordinator):
    """A success completing AFTER a sibling opened the breaker closes it.

    Delta-review P2: with concurrent device processing, call A can open the
    breaker while already-admitted call B is in flight; B's success is
    fresher evidence and must clear the deadline, not just the streak.
    """
    await _trip(coordinator)  # A: breaker now open
    assert coordinator._sidefetch_open_until is not None

    # B (admitted before the open) completes successfully.
    coordinator._sidefetch_note_reachable()

    assert coordinator._sidefetch_open_until is None
    assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_gathered_cancellations_are_neutral(coordinator):
    """CancelledError members carry no portal evidence in either direction.

    Delta-review P2: the caller stopping to wait says nothing about the
    portal; a cancellation-bearing gather must neither reset a streak nor
    count as a failure — the call site re-raises it afterwards.
    """
    from custom_components.eg4_web_monitor.coordinator_mixins import (
        _classify_gathered_responses,
    )

    assert _classify_gathered_responses([asyncio.CancelledError()]) is None
    assert (
        _classify_gathered_responses(
            [LuxpowerConnectionError("down"), asyncio.CancelledError()]
        )
        is False
    )
    assert (
        _classify_gathered_responses([{"payload": 1}, asyncio.CancelledError()]) is True
    )


async def test_skip_closes_coroutine_without_warning(coordinator):
    """The unawaited coroutine is closed — no 'never awaited' warning."""
    await _trip(coordinator)

    called = False

    async def _would_run():
        nonlocal called
        called = True

    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_would_run(), timeout=5)
    assert called is False


async def test_skip_cancels_gather_future(coordinator):
    """A gather() future (children already scheduled) is cancelled on skip."""
    await _trip(coordinator)

    started = False

    async def _child():
        nonlocal started
        started = True
        await asyncio.sleep(10)

    fut = asyncio.gather(_child(), return_exceptions=True)
    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(fut, timeout=5)
    # Awaiting the cancelled gather drives the cancellation to completion
    # deterministically (a single sleep(0) beat is not always enough). With
    # return_exceptions=True a _GatheringFuture finishes WITH the
    # CancelledError rather than transitioning to the CANCELLED state, so
    # done() + the raise is the correct assertion, not cancelled().
    with pytest.raises(asyncio.CancelledError):
        await fut
    assert fut.done()


async def test_fresh_boot_none_sentinel(coordinator):
    """A closed breaker at tiny monotonic values must not skip (d66cc92)."""
    with patch.object(
        coordinator_mixins.time, "monotonic", side_effect=itertools.count(1.0).__next__
    ):
        assert await coordinator._breakered_cloud_call(_ok(), timeout=5) == "payload"


async def test_neutral_half_open_probe_returns_to_open_state(coordinator):
    """An inconclusive probe must not leave an unbounded half-open state."""
    await _trip(coordinator)
    opened_at = coordinator._sidefetch_open_until
    assert opened_at is not None

    async def _neutral():
        return {"start_soc": None, "enabled": None}

    with patch.object(coordinator_mixins.time, "monotonic", return_value=opened_at + 1):
        await coordinator._breakered_cloud_call(
            _neutral(), timeout=5, classify=lambda _result: None
        )

    assert coordinator._sidefetch_half_open is False
    assert coordinator._sidefetch_open_until is not None
    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_ok(), timeout=5)


async def test_cancelled_half_open_probe_returns_to_open_state(coordinator):
    """Caller cancellation is inconclusive and cannot strand half-open state."""
    await _trip(coordinator)
    opened_at = coordinator._sidefetch_open_until
    assert opened_at is not None

    async def _cancelled():
        raise asyncio.CancelledError

    with patch.object(coordinator_mixins.time, "monotonic", return_value=opened_at + 1):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._breakered_cloud_call(_cancelled(), timeout=5)

    assert coordinator._sidefetch_half_open is False
    assert coordinator._sidefetch_open_until is not None


async def test_lazy_call_factory_runs_only_after_breaker_admission(coordinator):
    """A factory avoids scheduling gather children before the open check."""
    created = 0

    def _factory():
        nonlocal created
        created += 1
        return _ok()

    assert await coordinator._breakered_cloud_call(_factory, timeout=5) == "payload"
    assert created == 1

    await _trip(coordinator)
    with pytest.raises(_CloudSidefetchSkipped):
        await coordinator._breakered_cloud_call(_factory, timeout=5)
    assert created == 1


async def test_firmware_calls_are_bounded_by_shared_breaker(coordinator):
    """An open breaker starts neither firmware endpoint."""
    await _trip(coordinator)
    device = MagicMock()
    device.serial_number = "1234567890"
    device.check_firmware_updates = AsyncMock()
    device.get_firmware_update_progress = AsyncMock()
    device.firmware_update_available = False

    assert await coordinator._poll_firmware_update_info(device) is None
    device.check_firmware_updates.assert_not_awaited()
    device.get_firmware_update_progress.assert_not_awaited()


async def test_cloud_quick_charge_detail_is_bounded_by_shared_breaker(coordinator):
    """Cloud-only quick-charge helpers cannot bypass an open breaker."""
    await _trip(coordinator)
    inverter = MagicMock()
    inverter.serial_number = "1234567890"
    inverter.transport = None
    inverter.get_quick_charge_detail = AsyncMock(
        return_value=SimpleNamespace(
            hasUnclosedQuickChargeTask=False,
            remainTimeBeforeQuickChargeStop=0,
            unclosedQuickChargeTaskId=None,
            unclosedQuickChargeTaskStatus=None,
            quickChargeMinute=0,
        )
    )
    coordinator.client = None

    await coordinator._fetch_quick_charge_status(inverter, {})

    inverter.get_quick_charge_detail.assert_not_awaited()


async def test_battery_backup_call_is_bounded_by_shared_breaker(coordinator):
    """An open breaker starts no battery-backup request."""
    await _trip(coordinator)
    inverter = MagicMock()
    inverter.serial_number = "1234567890"
    inverter.transport = None
    inverter.get_battery_backup_status = AsyncMock(return_value=True)
    processed: dict = {}

    await coordinator._fetch_battery_backup_status(inverter, processed, now=1.0)

    inverter.get_battery_backup_status.assert_not_awaited()
    assert "battery_backup_status" not in processed


async def test_battery_backup_first_fetch_runs_at_low_host_uptime(coordinator):
    """A missing stamp is due even when monotonic uptime is below 30 seconds."""
    inverter = MagicMock()
    inverter.serial_number = "1234567890"
    inverter.transport = None
    inverter.get_battery_backup_status = AsyncMock(return_value=True)
    processed: dict = {}

    await coordinator._fetch_battery_backup_status(inverter, processed, now=1.0)

    inverter.get_battery_backup_status.assert_awaited_once()
    assert processed["battery_backup_status"] == {"enabled": True}


async def test_quick_charge_first_fetch_runs_at_low_host_uptime(coordinator):
    """Quick-charge has the same explicit never-fetched sentinel contract."""
    inverter = MagicMock()
    inverter.serial_number = "1234567890"
    inverter.transport = None
    inverter.get_quick_charge_detail = AsyncMock(
        return_value=SimpleNamespace(
            hasUnclosedQuickChargeTask=False,
            remainTimeBeforeQuickChargeStop=0,
            unclosedQuickChargeTaskId=None,
            unclosedQuickChargeTaskStatus=None,
            quickChargeMinute=0,
        )
    )
    coordinator.client = None

    with patch.object(coordinator_mixins.time, "monotonic", return_value=1.0):
        await coordinator._fetch_quick_charge_status(inverter, {})

    inverter.get_quick_charge_detail.assert_awaited_once()


class TestSaturatedBudgetTimeoutIsInconclusive:
    """A side-fetch timeout spent queued in the saturated account budget is
    not connectivity evidence and must not advance the breaker (#533 review)."""

    async def test_saturated_timeout_does_not_strike(self, coordinator):
        coordinator._cloud_request_budget = MagicMock(saturated=True)
        for _ in range(_SIDEFETCH_BREAKER_THRESHOLD + 1):
            with pytest.raises(TimeoutError):
                await coordinator._breakered_cloud_call(_timeout(), timeout=0.01)
        assert coordinator._sidefetch_open_until is None
        assert coordinator._sidefetch_consecutive_failures == 0

    async def test_unsaturated_timeout_still_strikes(self, coordinator):
        coordinator._cloud_request_budget = MagicMock(saturated=False)
        for _ in range(_SIDEFETCH_BREAKER_THRESHOLD):
            with pytest.raises(TimeoutError):
                await coordinator._breakered_cloud_call(_timeout(), timeout=0.01)
        assert coordinator._sidefetch_open_until is not None

    async def test_saturated_timeout_bounds_half_open_probe(self, coordinator):
        coordinator._cloud_request_budget = MagicMock(saturated=True)
        coordinator._sidefetch_open_until = 0.0  # expired cooldown
        with pytest.raises(TimeoutError):
            await coordinator._breakered_cloud_call(_timeout(), timeout=0.01)
        # The probe supplied no evidence: OPEN for one bounded cooldown,
        # not half-open-forever and not a counted strike.
        assert coordinator._sidefetch_half_open is False
        assert coordinator._sidefetch_open_until is not None
