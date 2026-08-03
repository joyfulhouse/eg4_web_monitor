"""Coordinator-owned concurrency controls for pylxpweb cloud requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, Coroutine, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pylxpweb import LuxpowerClient

CloudRequest = Callable[..., Awaitable[dict[str, Any]]]
FirmwareStatusFetch = Callable[[], Coroutine[Any, Any, Any]]
CloudAccountKey = tuple[str, str, bool]
FirmwareStatusKey = CloudAccountKey

_CLOUD_REQUEST_BUDGETS = "eg4_web_monitor_cloud_request_budgets"
_FIRMWARE_STATUS_FLIGHTS = "eg4_web_monitor_firmware_status_flights"
_PYLXPWEB_LOGIN_ENDPOINT = "/WManage/api/login"
_FIRMWARE_FLIGHT_CLOSE_TIMEOUT = 1.0


class SharedCloudRequestBudget:
    """One HA-local request-chain budget shared by an exact cloud account."""

    def __init__(
        self,
        hass: HomeAssistant | None,
        key: CloudAccountKey | None,
        *,
        limit: int,
    ) -> None:
        if limit < 1:
            raise ValueError("Cloud request limit must be at least one")
        self._hass = hass
        self.key = key
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self.ref_count = 0
        self._leases = 0
        self._accepting = False

    @classmethod
    def local(cls, *, limit: int) -> SharedCloudRequestBudget:
        """Create an unmanaged budget for direct limiter/unit-test use."""
        budget = cls(None, None, limit=limit)
        budget.register()
        return budget

    def register(self) -> None:
        """Register one config-entry/client owner."""
        self.ref_count += 1
        self._accepting = True

    def release_owner(self) -> bool:
        """Release one owner while retaining active/queued lease accounting."""
        if self.ref_count <= 0:
            return False
        self.ref_count -= 1
        if self.ref_count == 0:
            # Existing leases drain normally. New work from a closing client is
            # refused unless a replacement entry registers this same retained
            # budget before the final lease leaves.
            self._accepting = False
        self._remove_if_idle()
        return True

    @property
    def saturated(self) -> bool:
        """Return True while every request-chain slot is in use.

        A supplemental fetch that times out while the budget is saturated
        spent its deadline queued behind other chains, not on the wire — the
        breaker must not read that as portal unreachability.
        """
        return self._semaphore.locked()

    async def async_acquire(self) -> None:
        """Acquire one chain slot while keeping queued work in lifecycle state."""
        if not self._accepting:
            raise RuntimeError("Cloud request budget owner has been released")
        self._leases += 1
        try:
            await self._semaphore.acquire()
        except BaseException:
            self._leases -= 1
            self._remove_if_idle()
            raise

    def release_slot(self) -> None:
        """Return one acquired slot and retire an unowned idle registry entry."""
        self._semaphore.release()
        self._leases -= 1
        self._remove_if_idle()

    def _remove_if_idle(self) -> None:
        """Remove final-owner state only after every active/queued chain drains."""
        if self.ref_count > 0 or self._leases > 0:
            return
        self._accepting = False
        hass = self._hass
        key = self.key
        if hass is None or key is None:
            return
        registry = hass.data.get(_CLOUD_REQUEST_BUDGETS)
        if isinstance(registry, dict) and registry.get(key) is self:
            registry.pop(key, None)
            if not registry:
                hass.data.pop(_CLOUD_REQUEST_BUDGETS, None)


class _CloudRequestLease:
    """Reference-count one admitted semaphore slot across a request chain."""

    def __init__(self, budget: SharedCloudRequestBudget) -> None:
        self._budget = budget
        self._references = 1

    def retain(self) -> bool:
        """Keep an active slot admitted for a child request task."""
        if self._references == 0:
            return False
        self._references += 1
        return True

    def release(self) -> None:
        """Return the budget slot after the final chain owner leaves."""
        if self._references <= 0:
            raise RuntimeError("Cloud request lease released more than once")
        self._references -= 1
        if self._references == 0:
            self._budget.release_slot()


class CloudRequestLimiter:
    """Bound one client's request chains without deadlocking recursive retries.

    pylxpweb performs retry and re-authentication by recursively calling the
    client's private ``_request`` method.  A plain semaphore wrapper would
    acquire a slot twice in the same task and can deadlock when every slot is
    occupied by a retrying request.  The context variable makes a request
    *chain* re-entrant while independently-created requests still consume one
    slot each.

    Each client retains its own original request callable and re-entrancy
    contexts, while clients for separate plants on the same account share only
    the semaphore budget. The shared budget owns and cancels no request task.
    """

    def __init__(
        self,
        request: CloudRequest,
        *,
        limit: int | None = None,
        budget: SharedCloudRequestBudget | None = None,
        authentication_task_getter: Callable[[], asyncio.Task[Any] | None]
        | None = None,
    ) -> None:
        if budget is None:
            if limit is None:
                raise ValueError("A cloud request limit or shared budget is required")
            budget = SharedCloudRequestBudget.local(limit=limit)
        elif limit is not None and limit != budget.limit:
            raise ValueError("Cloud request limit does not match shared budget")
        self._request = request
        self._budget = budget
        self._authentication_task_getter = authentication_task_getter
        self._auth_task_leases: dict[asyncio.Task[Any], _CloudRequestLease] = {}
        self._closed = False
        self._request_owner: ContextVar[asyncio.Task[Any] | None] = ContextVar(
            f"eg4_cloud_request_{id(self)}", default=None
        )
        self._request_lease: ContextVar[_CloudRequestLease | None] = ContextVar(
            f"eg4_cloud_request_lease_{id(self)}", default=None
        )
        self._auth_chain_owner: ContextVar[asyncio.Task[Any] | None] = ContextVar(
            f"eg4_cloud_auth_chain_{id(self)}", default=None
        )

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        """Run one pylxpweb request chain inside the account budget."""
        if self._closed:
            raise RuntimeError("Cloud request limiter has been released")
        kwargs = {
            "data": data,
            "cache_key": cache_key,
            "cache_endpoint": cache_endpoint,
            "_retry_count": _retry_count,
        }
        current_task = asyncio.current_task()
        if current_task is not None and self._request_owner.get() is current_task:
            return await self._request(method, endpoint, **kwargs)
        if current_task is not None and self._auth_chain_owner.get() is current_task:
            return await self._request(method, endpoint, **kwargs)

        # pylxpweb's reactive authentication creates a child task after an
        # ordinary request receives an unauthenticated response. ContextVars
        # are copied into that child, but exact-task re-entrancy intentionally
        # rejects the inherited parent owner. When every request slot is held
        # by a parent awaiting the shared authentication task, login would
        # otherwise wait forever for one of those same parents to release.
        # Promote only pylxpweb's exact login boundary; the task also performs
        # account discovery before it completes, so retain admission for the
        # remainder of this short-lived auth task's context.
        inherited_owner = self._request_owner.get()
        inherited_login = (
            current_task is not None
            and inherited_owner is not None
            and inherited_owner is not current_task
            and method.upper() == "POST"
            and endpoint == _PYLXPWEB_LOGIN_ENDPOINT
        )
        inherited_lease = self._request_lease.get()
        if inherited_login and current_task is not None:
            reservation = self._auth_task_leases.get(current_task)
            if reservation is None:
                if inherited_lease is None or not inherited_lease.retain():
                    # A future client implementation may hide or replace its
                    # auth task before a cancelling parent can reserve the
                    # slot. Never queue login behind parents that can all be
                    # waiting on it; fail the attempt so they unwind and retry.
                    raise RuntimeError(
                        "Reactive authentication lost its parent request admission"
                    )
                reservation = inherited_lease
                self._auth_task_leases[current_task] = reservation
                current_task.add_done_callback(self._auth_task_finished)
            # login() is only the first phase of pylxpweb's shielded auth task;
            # account discovery and retry backoff continue after this wrapper
            # returns. Keep the inherited parent admission until that *task*
            # finishes, otherwise canceled parents release all three slots and
            # later work can run alongside the still-live auth request.
            self._auth_chain_owner.set(current_task)
            return await self._request(method, endpoint, **kwargs)

        await self._budget.async_acquire()
        lease = _CloudRequestLease(self._budget)
        try:
            # The owner can unload while this chain is queued. Its lease must
            # remain counted until admission so a replacement entry reuses the
            # draining semaphore, but the detached client must not begin new
            # network I/O after close().
            if self._closed:
                raise RuntimeError("Cloud request limiter has been released")
            owner_token = self._request_owner.set(current_task)
            lease_token = self._request_lease.set(lease)
            try:
                return await self._request(method, endpoint, **kwargs)
            except asyncio.CancelledError:
                self._reserve_lease_for_auth_task(lease, current_task)
                raise
            finally:
                self._request_lease.reset(lease_token)
                self._request_owner.reset(owner_token)
        finally:
            lease.release()

    def _reserve_lease_for_auth_task(
        self,
        lease: _CloudRequestLease,
        current_task: asyncio.Task[Any] | None,
    ) -> None:
        """Hand one cancelling parent's slot to its pending shared auth task."""
        if current_task is None or current_task.cancelling() == 0:
            return
        getter = self._authentication_task_getter
        if getter is None:
            return
        try:
            auth_task = getter()
        except Exception:
            return
        if auth_task is None or auth_task.done() or auth_task in self._auth_task_leases:
            return
        if not lease.retain():
            return
        self._auth_task_leases[auth_task] = lease
        auth_task.add_done_callback(self._auth_task_finished)

    def _auth_task_finished(self, task: asyncio.Task[Any]) -> None:
        """Release the one account slot reserved for a complete auth task."""
        lease = self._auth_task_leases.pop(task, None)
        if lease is not None:
            lease.release()

    def close(self) -> None:
        """Refuse new work from this client without affecting sibling clients."""
        self._closed = True


def install_cloud_request_limiter(
    client: LuxpowerClient,
    *,
    limit: int | None = None,
    budget: SharedCloudRequestBudget | None = None,
) -> CloudRequestLimiter:
    """Install a per-client limiter at pylxpweb's common request boundary."""

    def _authentication_task() -> asyncio.Task[Any] | None:
        task = getattr(client, "_authentication_task", None)
        return task if isinstance(task, asyncio.Task) else None

    limiter = CloudRequestLimiter(
        client._request,
        limit=limit,
        budget=budget,
        authentication_task_getter=_authentication_task,
    )
    # pylxpweb's endpoint objects resolve ``client._request`` dynamically, and
    # its retries recurse through the same attribute.  Binding on the instance
    # therefore covers Station.load cache warming and every standard endpoint
    # without replacing the HA-owned aiohttp session.
    setattr(client, "_request", limiter.request)
    return limiter


def acquire_shared_cloud_request_budget(
    hass: HomeAssistant,
    *,
    username: str,
    base_url: str,
    verify_ssl: bool,
    limit: int,
) -> SharedCloudRequestBudget:
    """Acquire one HA-local raw request budget for an exact cloud account."""
    key = (username, base_url.rstrip("/"), verify_ssl)
    registry: dict[CloudAccountKey, SharedCloudRequestBudget] = hass.data.setdefault(
        _CLOUD_REQUEST_BUDGETS, {}
    )
    budget = registry.get(key)
    if budget is None:
        budget = SharedCloudRequestBudget(hass, key, limit=limit)
        registry[key] = budget
    elif budget.limit != limit:
        raise ValueError("Cloud request limit does not match existing account budget")
    budget.register()
    return budget


def release_shared_cloud_request_budget(
    hass: HomeAssistant, budget: SharedCloudRequestBudget
) -> None:
    """Release one account-budget owner; active and queued chains drain safely."""
    del hass  # Budget retains the exact HA registry it belongs to.
    budget.release_owner()


class SharedFirmwareStatusFlight:
    """Account-scoped ownership for pylxpweb's firmware progress endpoint.

    Firmware progress is account-wide, but pylxpweb exposes the getter through
    each client and device. Config entries for separate plants on the same
    account therefore need one shared request. The state lives in one Home
    Assistant instance and is reference-counted so unloading one plant cannot
    cancel a request still owned by another.
    """

    def __init__(self, hass: HomeAssistant, key: FirmwareStatusKey) -> None:
        self._hass = hass
        self.key = key
        self._owners: dict[object, FirmwareStatusFetch] = {}
        self.task: asyncio.Task[Any] | None = None
        self._task_owner: object | None = None
        self._active_batches = 0
        self._task_waiters: dict[asyncio.Task[Any], int] = {}
        self._retired_tasks: set[asyncio.Task[Any]] = set()

    @property
    def ref_count(self) -> int:
        """Return the number of config entries sharing this account state."""
        return len(self._owners)

    def register(self, fetch: FirmwareStatusFetch) -> object:
        """Register one config entry and its client-bound status getter."""
        owner = object()
        self._owners[owner] = fetch
        return owner

    async def run(self, owner: object) -> Any:
        """Join the current account request, transferring from closing clients."""
        while True:
            fetch = self._owners.get(owner)
            if fetch is None:
                raise RuntimeError("Firmware status owner has been released")

            task = self.task
            if task is None or (task.done() and self._active_batches == 0):
                task = self._hass.async_create_task(fetch())
                self.task = task
                self._task_owner = owner
                task.add_done_callback(self._task_finished)

            # A cancelled device/coordinator waiter must not cancel the raw
            # request while another plant or sibling device still consumes it.
            # Once the final waiter leaves, cancel raw work so a breaker timeout
            # cannot strand one cloud-budget slot in client backoff.
            self._task_waiters[task] = self._task_waiters.get(task, 0) + 1
            retry_with_surviving_owner = False
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                caller = asyncio.current_task()
                caller_was_cancelled = caller is not None and caller.cancelling() > 0
                retry_with_surviving_owner = (
                    not caller_was_cancelled
                    and task in self._retired_tasks
                    and owner in self._owners
                )
                if not retry_with_surviving_owner:
                    raise
            except Exception:
                retry_with_surviving_owner = (
                    task in self._retired_tasks and owner in self._owners
                )
                if not retry_with_surviving_owner:
                    raise
            else:
                if task not in self._retired_tasks:
                    return result
                retry_with_surviving_owner = owner in self._owners
                if not retry_with_surviving_owner:
                    raise asyncio.CancelledError
            finally:
                remaining = self._task_waiters[task] - 1
                if remaining:
                    self._task_waiters[task] = remaining
                else:
                    self._task_waiters.pop(task, None)
                    if task.done():
                        self._retired_tasks.discard(task)
                self._discard_unobserved_task()

            # Releasing the client that created a raw request deliberately
            # retires that task. Its own waiters still observe cancellation,
            # but a waiter belonging to another registered config entry loops
            # here and starts a replacement through its own live client. This
            # transfer is internal to the flight, so it cannot count as a
            # connectivity failure in the caller's supplemental breaker.
            if retry_with_surviving_owner:
                continue

    def begin_batch(self) -> None:
        """Keep a fast completed result joinable for one prefetch batch."""
        self._active_batches += 1

    def end_batch(self) -> None:
        """Release one prefetch batch and its completed single-flight result."""
        if self._active_batches > 0:
            self._active_batches -= 1
        self._discard_unobserved_task()

    def _discard_unobserved_task(self) -> None:
        """Clear a result or cancel raw work after its final consumer leaves."""
        if self._active_batches > 0:
            return
        task = self.task
        if task is None or self._task_waiters.get(task, 0) > 0:
            return
        self.task = None
        self._task_owner = None
        if not task.done():
            task.cancel()

    def _task_finished(self, task: asyncio.Task[Any]) -> None:
        """Consume terminal errors and clear an unbatched task owner."""
        try:
            task.exception()
        except asyncio.CancelledError:
            pass
        if self.task is task and self._active_batches == 0:
            self.task = None
            self._task_owner = None
        if not self._task_waiters.get(task, 0):
            self._retired_tasks.discard(task)

    def release(self, owner: object) -> bool:
        """Release one owner and retire raw work tied to its closing client."""
        if self._owners.pop(owner, None) is None:
            return False

        task = self.task
        if (
            self._owners
            and task is not None
            and not task.done()
            and self._task_owner is owner
        ):
            # async_unload_entry closes this owner's pylxpweb client immediately
            # after coordinator shutdown. Keeping a task bound to that client
            # would let client.close cancel a shared auth dependency underneath
            # another plant. Retire synchronously; surviving waiters recognize
            # this exact cancellation and transparently retry through their own
            # registered getter.
            self.task = None
            self._task_owner = None
            self._retired_tasks.add(task)
            task.cancel()
        elif task is not None and task.done() and self._task_owner is owner:
            # A completed batch result no longer depends on its originating
            # client and remains safe for sibling callers to consume.
            self._task_owner = None
        return True

    async def async_close(self) -> None:
        """Cancel the raw request when the final config-entry owner unloads."""
        tasks = set(self._retired_tasks)
        if self.task is not None:
            tasks.add(self.task)
        self.task = None
        self._task_owner = None
        self._active_batches = 0
        self._owners.clear()
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        # Third-party cancellation should be prompt, but unload must remain
        # bounded even if a future pylxpweb coroutine suppresses cancellation.
        await asyncio.wait(tasks, timeout=_FIRMWARE_FLIGHT_CLOSE_TIMEOUT)


def acquire_shared_firmware_status(
    hass: HomeAssistant,
    *,
    username: str,
    base_url: str,
    verify_ssl: bool,
    fetch: FirmwareStatusFetch,
) -> tuple[SharedFirmwareStatusFlight, object]:
    """Acquire one HA-local firmware flight for an exact cloud account."""
    key = (username, base_url.rstrip("/"), verify_ssl)
    registry: dict[FirmwareStatusKey, SharedFirmwareStatusFlight] = (
        hass.data.setdefault(_FIRMWARE_STATUS_FLIGHTS, {})
    )
    flight = registry.get(key)
    if flight is None:
        flight = SharedFirmwareStatusFlight(hass, key)
        registry[key] = flight
    return flight, flight.register(fetch)


async def release_shared_firmware_status(
    hass: HomeAssistant, flight: SharedFirmwareStatusFlight, owner: object
) -> None:
    """Release one entry owner, cancelling only after the last owner leaves."""
    if not flight.release(owner):
        return
    if flight.ref_count > 0:
        return

    # Remove synchronously before awaiting cancellation. A replacement entry
    # racing an unload acquires a fresh state and cannot inherit a cancelling
    # task from the final owner of the old state.
    registry = hass.data.get(_FIRMWARE_STATUS_FLIGHTS)
    if isinstance(registry, dict) and registry.get(flight.key) is flight:
        registry.pop(flight.key, None)
        if not registry:
            hass.data.pop(_FIRMWARE_STATUS_FLIGHTS, None)
    await flight.async_close()
