"""Regression tests for bounded and deduplicated cloud polling (eg4-06er.5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import current_entry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pylxpweb.models import FirmwareUpdateInfo, FirmwareUpdateStatus

import custom_components.eg4_web_monitor.coordinator as coordinator_module
from custom_components.eg4_web_monitor.cloud_requests import (
    acquire_shared_cloud_request_budget,
    install_cloud_request_limiter,
    release_shared_cloud_request_budget,
)
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from tests.conftest import make_real_inverter


def _http_entry(
    entry_id: str = "cloud_fanout",
    *,
    username: str = "test",
    plant_id: str = "12345",
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Cloud fanout",
        data={
            CONF_USERNAME: username,
            CONF_PASSWORD: "test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_PLANT_ID: plant_id,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
        },
        entry_id=entry_id,
    )


class _ListenerScope:
    """Hashable stand-in for #532's private listener context."""

    def __init__(self, kind: str, serial: str = "") -> None:
        self.kind = kind
        self.serial = serial


def _local_entry(entry_id: str = "parameter_only") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Parameter only",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_LOCAL_TRANSPORTS: [],
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
        },
        entry_id=entry_id,
    )


class _CountingClient:
    """Small client double whose request method exposes real concurrency."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.calls = 0
        self._request_started = asyncio.Event()
        self._release_requests = asyncio.Event()
        self.api = SimpleNamespace(
            firmware=SimpleNamespace(
                get_firmware_update_status=AsyncMock(return_value=object())
            )
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, endpoint, data, cache_key, cache_endpoint, _retry_count
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        self._request_started.set()
        try:
            await self._release_requests.wait()
        finally:
            self.active -= 1
        return {"success": True}


class _AccountRequestCounter:
    """Aggregate request concurrency across multiple pylxpweb clients."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.calls = 0
        self.three_started = asyncio.Event()
        self.release = asyncio.Event()


class _AccountCountingClient:
    """Client double backed by an account-wide concurrency counter."""

    def __init__(self, counter: _AccountRequestCounter) -> None:
        self.counter = counter
        self.api = SimpleNamespace(
            firmware=SimpleNamespace(
                get_firmware_update_status=AsyncMock(return_value=object())
            )
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, endpoint, data, cache_key, cache_endpoint, _retry_count
        counter = self.counter
        counter.calls += 1
        counter.active += 1
        counter.peak = max(counter.peak, counter.active)
        if counter.active >= 3:
            counter.three_started.set()
        try:
            await counter.release.wait()
        finally:
            counter.active -= 1
        return {"success": True}


class _ColdCacheInverter:
    """A cold inverter refresh fans out runtime, energy, and battery calls."""

    def __init__(self, client: _CountingClient, serial: str) -> None:
        self._client = client
        self.serial_number = serial

    async def refresh(self) -> None:
        await asyncio.gather(
            self._client._request("POST", f"/{self.serial_number}/runtime"),
            self._client._request("POST", f"/{self.serial_number}/energy"),
            self._client._request("POST", f"/{self.serial_number}/battery"),
        )


class _RecursiveRetryClient:
    """Client double that retries through its own patched request attribute."""

    def __init__(self) -> None:
        self.calls = 0
        self.api = SimpleNamespace(
            firmware=SimpleNamespace(
                get_firmware_update_status=AsyncMock(return_value=object())
            )
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        self.calls += 1
        await asyncio.sleep(0)
        if _retry_count == 0:
            return await self._request(
                method,
                endpoint,
                data=data,
                cache_key=cache_key,
                cache_endpoint=cache_endpoint,
                _retry_count=1,
            )
        return {"success": True}


class _ReactiveAuthTaskClient:
    """Model pylxpweb #261's child auth task under saturated parent calls."""

    def __init__(self) -> None:
        self.parents_started = 0
        self.all_parents_started = asyncio.Event()
        self.auth_task: asyncio.Task[dict[str, Any]] | None = None
        self._authentication_task: asyncio.Task[dict[str, Any]] | None = None
        self.login_calls = 0
        self.detect_calls = 0

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, data, cache_key, cache_endpoint, _retry_count
        if endpoint.startswith("/parent/"):
            self.parents_started += 1
            if self.parents_started == 3:
                self.all_parents_started.set()
            await self.all_parents_started.wait()
            task = self.auth_task
            if task is None:
                task = asyncio.create_task(self._request("POST", "/WManage/api/login"))
                self.auth_task = task
                self._authentication_task = task
            await asyncio.shield(task)
            return {"success": True}
        if endpoint == "/WManage/api/login":
            self.login_calls += 1
            # login() performs ordinary account-level detection before the
            # client-owned authentication task completes.
            await self._request("POST", "/auth/account-detection")
            return {"success": True}
        if endpoint == "/auth/account-detection":
            self.detect_calls += 1
            return {"success": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class _LingeringReactiveAuthClient:
    """Keep pylxpweb's shielded auth task alive after all parents cancel."""

    def __init__(self, *, detect_after_login: bool = True) -> None:
        self.detect_after_login = detect_after_login
        self.parents_started = 0
        self.all_parents_started = asyncio.Event()
        self.auth_task: asyncio.Task[dict[str, Any]] | None = None
        self._authentication_task: asyncio.Task[dict[str, Any]] | None = None
        self.auth_started = asyncio.Event()
        self.auth_release = asyncio.Event()
        self.ordinary_started = 0
        self.two_ordinary_started = asyncio.Event()
        self.three_ordinary_started = asyncio.Event()
        self.ordinary_release = asyncio.Event()
        self.active_raw = 0
        self.peak_raw = 0

    def _enter_raw(self) -> None:
        self.active_raw += 1
        self.peak_raw = max(self.peak_raw, self.active_raw)

    def _leave_raw(self) -> None:
        self.active_raw -= 1

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, data, cache_key, cache_endpoint, _retry_count
        if endpoint.startswith("/parent/"):
            self.parents_started += 1
            if self.parents_started == 3:
                self.all_parents_started.set()
            await self.all_parents_started.wait()
            task = self.auth_task
            if task is None:
                task = asyncio.create_task(self._request("POST", "/WManage/api/login"))
                self.auth_task = task
                self._authentication_task = task
            await asyncio.shield(task)
            return {"success": True}
        if endpoint == "/WManage/api/login":
            self._enter_raw()
            self.auth_started.set()
            try:
                await self.auth_release.wait()
            finally:
                self._leave_raw()
            # pylxpweb continues in the same authentication task after login.
            if self.detect_after_login:
                await self._request("POST", "/auth/account-detection")
            return {"success": True}
        if endpoint == "/auth/account-detection":
            return {"success": True}
        if endpoint.startswith("/ordinary/"):
            self._enter_raw()
            self.ordinary_started += 1
            if self.ordinary_started == 2:
                self.two_ordinary_started.set()
            if self.ordinary_started == 3:
                self.three_ordinary_started.set()
            try:
                await self.ordinary_release.wait()
            finally:
                self._leave_raw()
            return {"success": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class _DelayedReactiveAuthClient:
    """Delay exact login until its origin parent's admission has retired."""

    def __init__(self) -> None:
        self.parents_started = 0
        self.three_parents_started = asyncio.Event()
        self.four_parents_started = asyncio.Event()
        self.auth_prework_started = asyncio.Event()
        self.allow_login = asyncio.Event()
        self.auth_task: asyncio.Task[dict[str, Any]] | None = None
        self._authentication_task: asyncio.Task[dict[str, Any]] | None = None
        self.login_calls = 0
        self.active_parents = 0
        self.peak_parents = 0

    async def _authenticate(self) -> dict[str, Any]:
        self.auth_prework_started.set()
        await self.allow_login.wait()
        return await self._request("POST", "/WManage/api/login")

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, data, cache_key, cache_endpoint, _retry_count
        if endpoint.startswith("/parent/"):
            self.active_parents += 1
            self.peak_parents = max(self.peak_parents, self.active_parents)
            try:
                self.parents_started += 1
                if endpoint == "/parent/0":
                    self.auth_task = asyncio.create_task(self._authenticate())
                    self._authentication_task = self.auth_task
                    # pylxpweb #261 consumes the shared task's terminal
                    # exception in its own done callback even when the origin
                    # parent canceled its shielded waiter.
                    self.auth_task.add_done_callback(
                        lambda task: None if task.cancelled() else task.exception()
                    )
                if self.parents_started == 3:
                    self.three_parents_started.set()
                if self.parents_started == 4:
                    self.four_parents_started.set()
                await self.three_parents_started.wait()
                while self.auth_task is None:
                    await asyncio.sleep(0)
                await asyncio.shield(self.auth_task)
                return {"success": True}
            finally:
                self.active_parents -= 1
        if endpoint == "/WManage/api/login":
            self.login_calls += 1
            return {"success": True}
        if endpoint == "/ordinary/recovery":
            return {"success": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class _InheritedOrdinaryChildClient:
    """Prove an unrelated descendant does not inherit limiter admission."""

    def __init__(self) -> None:
        self.child_created = asyncio.Event()
        self.child_started = asyncio.Event()
        self.release_parent = asyncio.Event()
        self.child_task: asyncio.Task[dict[str, Any]] | None = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_endpoint: str | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        del method, data, cache_key, cache_endpoint, _retry_count
        if endpoint == "/parent":
            self.child_task = asyncio.create_task(self._request("POST", "/child"))
            self.child_created.set()
            await self.release_parent.wait()
            return {"success": True}
        if endpoint == "/child":
            self.child_started.set()
            return {"success": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


async def test_cold_cache_station_fanout_is_bounded_at_request_boundary(hass):
    """Station-level gather cannot exceed the per-account request budget."""
    client = _CountingClient()
    entry = _http_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        EG4DataUpdateCoordinator(hass, entry)

    inverters = [_ColdCacheInverter(client, f"INV{i}") for i in range(5)]
    refresh = asyncio.gather(*(inverter.refresh() for inverter in inverters))
    await client._request_started.wait()
    await asyncio.sleep(0)

    # Fifteen cold-cache legs are created together, but only three may enter
    # pylxpweb's request chain at once.
    assert client.calls == 3
    assert client.peak == 3

    client._release_requests.set()
    await refresh
    assert client.calls == 15
    assert client.peak == 3


async def test_same_account_entries_share_one_raw_request_budget(hass):
    """Two plant clients on one account have one aggregate three-chain cap."""
    counter = _AccountRequestCounter()
    clients = [_AccountCountingClient(counter), _AccountCountingClient(counter)]
    coordinators: list[EG4DataUpdateCoordinator] = []
    requests: list[asyncio.Task[dict[str, Any]]] = []
    for index, client in enumerate(clients):
        entry = _http_entry(
            f"shared_budget_{index}",
            username="shared-budget-account",
            plant_id=f"plant-{index}",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=client,
        ):
            coordinators.append(EG4DataUpdateCoordinator(hass, entry))

    try:
        requests = [
            asyncio.create_task(client._request("POST", f"/{client_index}/{call}"))
            for client_index, client in enumerate(clients)
            for call in range(4)
        ]
        await asyncio.wait_for(counter.three_started.wait(), timeout=1)
        await asyncio.sleep(0)

        assert counter.calls == 3
        assert counter.peak == 3
    finally:
        counter.release.set()
        await asyncio.gather(*requests, return_exceptions=True)
        for coordinator in coordinators:
            coordinator._release_shared_cloud_request_budget()
        await asyncio.gather(
            *(
                coordinator._release_shared_firmware_status()
                for coordinator in coordinators
            )
        )


async def test_different_accounts_have_independent_raw_request_budgets(hass):
    """Unrelated cloud accounts can each consume their full three-chain cap."""
    counters = [_AccountRequestCounter(), _AccountRequestCounter()]
    clients = [_AccountCountingClient(counter) for counter in counters]
    coordinators: list[EG4DataUpdateCoordinator] = []
    requests: list[asyncio.Task[dict[str, Any]]] = []
    for index, client in enumerate(clients):
        entry = _http_entry(
            f"isolated_budget_{index}",
            username=f"isolated-budget-account-{index}",
            plant_id=f"plant-{index}",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=client,
        ):
            coordinators.append(EG4DataUpdateCoordinator(hass, entry))

    try:
        requests = [
            asyncio.create_task(client._request("POST", f"/{index}/{call}"))
            for index, client in enumerate(clients)
            for call in range(3)
        ]
        await asyncio.wait_for(
            asyncio.gather(*(counter.three_started.wait() for counter in counters)),
            timeout=1,
        )

        assert [counter.calls for counter in counters] == [3, 3]
        assert [counter.peak for counter in counters] == [3, 3]
    finally:
        for counter in counters:
            counter.release.set()
        await asyncio.gather(*requests, return_exceptions=True)
        for coordinator in coordinators:
            coordinator._release_shared_cloud_request_budget()
        await asyncio.gather(
            *(
                coordinator._release_shared_firmware_status()
                for coordinator in coordinators
            )
        )


async def test_request_budget_releases_a_slot_when_a_waiter_is_cancelled(hass):
    """Cancellation cannot leak a request slot or strand queued requests."""
    client = _CountingClient()
    entry = _http_entry("cloud_cancel")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        EG4DataUpdateCoordinator(hass, entry)

    tasks = [
        asyncio.create_task(client._request("POST", f"/{index}")) for index in range(4)
    ]
    await client._request_started.wait()
    await asyncio.sleep(0)
    assert client.calls == 3

    tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[0]
    await asyncio.sleep(0)
    assert client.calls == 4

    client._release_requests.set()
    await asyncio.gather(*tasks[1:])
    assert client.active == 0


async def test_request_budget_is_reentrant_for_dependency_retries(hass):
    """Three occupied slots can all recurse for retry without deadlocking."""
    client = _RecursiveRetryClient()
    entry = _http_entry("cloud_retry")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        EG4DataUpdateCoordinator(hass, entry)

    results = await asyncio.wait_for(
        asyncio.gather(*(client._request("POST", f"/{index}") for index in range(6))),
        timeout=1,
    )
    assert results == [{"success": True}] * 6
    assert client.calls == 12


async def test_replacement_reuses_budget_while_released_client_drains(hass):
    """Reload shares draining leases and drops queued work from the old client."""
    counter = _AccountRequestCounter()
    clients = [_AccountCountingClient(counter), _AccountCountingClient(counter)]
    coordinators: list[EG4DataUpdateCoordinator] = []
    old_requests: list[asyncio.Task[dict[str, Any]]] = []
    replacement_requests: list[asyncio.Task[dict[str, Any]]] = []

    old_entry = _http_entry(
        "shared_budget_old",
        username="reload-budget-account",
        plant_id="old-plant",
    )
    old_entry.add_to_hass(hass)
    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=clients[0],
    ):
        old_coordinator = EG4DataUpdateCoordinator(hass, old_entry)
    coordinators.append(old_coordinator)
    budget = old_coordinator._cloud_request_budget
    assert budget is not None

    try:
        # Three requests enter and a fourth becomes an old-client waiter.
        old_requests = [
            asyncio.create_task(clients[0]._request("POST", f"/old/{index}"))
            for index in range(4)
        ]
        await asyncio.wait_for(counter.three_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert counter.calls == 3

        # Unloading the final owner closes that client but retains the budget
        # because all four active/queued chains still hold lifecycle leases.
        old_coordinator._release_shared_cloud_request_budget()
        assert budget.ref_count == 0
        assert "eg4_web_monitor_cloud_request_budgets" in hass.data

        replacement_entry = _http_entry(
            "shared_budget_replacement",
            username="reload-budget-account",
            plant_id="replacement-plant",
        )
        replacement_entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=clients[1],
        ):
            replacement = EG4DataUpdateCoordinator(hass, replacement_entry)
        coordinators.append(replacement)

        assert replacement._cloud_request_budget is budget
        assert budget.ref_count == 1
        replacement_requests = [
            asyncio.create_task(clients[1]._request("POST", f"/new/{index}"))
            for index in range(3)
        ]
        await asyncio.sleep(0)
        assert counter.calls == 3
        assert counter.peak == 3

        counter.release.set()
        old_results = await asyncio.gather(*old_requests, return_exceptions=True)
        replacement_results = await asyncio.gather(*replacement_requests)

        # The old queued call consumes/relinquishes its accounted lease after
        # admission, but the post-acquire close check prevents detached-client
        # I/O. Only the three active old calls and three replacement calls run.
        assert old_results[:3] == [{"success": True}] * 3
        assert isinstance(old_results[3], RuntimeError)
        assert replacement_results == [{"success": True}] * 3
        assert counter.calls == 6
        assert counter.peak == 3

        replacement._release_shared_cloud_request_budget()
        assert budget.ref_count == 0
        assert "eg4_web_monitor_cloud_request_budgets" not in hass.data
    finally:
        counter.release.set()
        await asyncio.gather(
            *old_requests,
            *replacement_requests,
            return_exceptions=True,
        )
        for coordinator in coordinators:
            coordinator._release_shared_cloud_request_budget()
        await asyncio.gather(
            *(
                coordinator._release_shared_firmware_status()
                for coordinator in coordinators
            )
        )


async def test_constructor_failure_leaves_no_shared_owners_or_unload_callback(hass):
    """Fallible setup completes before account owners and unload retention."""
    client = _CountingClient()
    entry = _http_entry("constructor_rollback", username="constructor-account")
    entry.add_to_hass(hass)
    initial_callbacks = tuple(getattr(entry, "_on_unload", None) or ())
    context_token = current_entry.set(entry)
    try:
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
                return_value=client,
            ),
            patch.object(
                type(hass.bus),
                "async_listen_once",
                side_effect=RuntimeError("listener setup failed"),
            ),
            pytest.raises(RuntimeError, match="listener setup failed"),
        ):
            EG4DataUpdateCoordinator(hass, entry)
    finally:
        current_entry.reset(context_token)

    assert tuple(getattr(entry, "_on_unload", None) or ()) == initial_callbacks
    assert "eg4_web_monitor_cloud_request_budgets" not in hass.data
    assert "eg4_web_monitor_firmware_status_flights" not in hass.data


@pytest.mark.parametrize(
    "shutdown_method", ["async_shutdown", "_async_handle_shutdown"]
)
@pytest.mark.parametrize("cancel_stage", ["disconnect", "background"])
async def test_early_shutdown_cancellation_drains_shared_account_owners(
    hass, shutdown_method: str, cancel_stage: str
):
    """Unload/HA-stop cancellation cannot skip account-registry release."""
    client = _CountingClient()
    entry = _http_entry(
        f"cancel_{shutdown_method}",
        username=f"cancel-account-{shutdown_method}",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, entry)

    assert "eg4_web_monitor_cloud_request_budgets" in hass.data
    assert "eg4_web_monitor_firmware_status_flights" in hass.data

    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    events: list[str] = []
    original_budget_release = coordinator._release_shared_cloud_request_budget
    original_firmware_release = coordinator._release_shared_firmware_status

    async def _blocked_disconnect() -> None:
        events.append("disconnect-start")
        if cancel_stage == "disconnect":
            cleanup_started.set()
            await release_cleanup.wait()
        events.append("disconnect-end")

    async def _background_cleanup() -> None:
        events.append("background-start")
        if cancel_stage == "background":
            cleanup_started.set()
            await release_cleanup.wait()
        events.append("background-end")

    def _release_budget() -> None:
        events.append("budget-release")
        original_budget_release()

    async def _release_firmware() -> None:
        events.append("firmware-release")
        await original_firmware_release()

    shutdown_task: asyncio.Task[None] | None = None
    try:
        with (
            patch.object(
                coordinator,
                "_disconnect_all_transports",
                side_effect=_blocked_disconnect,
            ),
            patch.object(
                coordinator,
                "_cancel_background_tasks",
                side_effect=_background_cleanup,
            ),
            patch.object(
                coordinator,
                "_release_shared_cloud_request_budget",
                side_effect=_release_budget,
            ),
            patch.object(
                coordinator,
                "_release_shared_firmware_status",
                side_effect=_release_firmware,
            ),
        ):
            shutdown = getattr(coordinator, shutdown_method)
            shutdown_task = asyncio.create_task(
                shutdown(None)
                if shutdown_method == "_async_handle_shutdown"
                else shutdown()
            )
            await cleanup_started.wait()

            shutdown_task.cancel()
            await asyncio.sleep(0)
            shutdown_task.cancel()
            release_cleanup.set()

            with pytest.raises(asyncio.CancelledError):
                await shutdown_task

        assert events == [
            "disconnect-start",
            "disconnect-end",
            "background-start",
            "background-end",
            "budget-release",
            "firmware-release",
        ]
        assert "eg4_web_monitor_cloud_request_budgets" not in hass.data
        assert "eg4_web_monitor_firmware_status_flights" not in hass.data
        assert coordinator._cloud_request_budget_released
        assert coordinator._firmware_status_released
    finally:
        release_cleanup.set()
        if shutdown_task is not None and not shutdown_task.done():
            shutdown_task.cancel()
        if shutdown_task is not None:
            await asyncio.gather(shutdown_task, return_exceptions=True)
        original_budget_release()
        await original_firmware_release()


async def test_saturated_budget_admits_shared_reactive_auth_child_chain(hass):
    """Three parents awaiting #261's auth task cannot consume its login slot."""
    client = _ReactiveAuthTaskClient()
    budget = acquire_shared_cloud_request_budget(
        hass,
        username="reactive-auth-account",
        base_url="https://monitor.eg4electronics.com",
        verify_ssl=True,
        limit=3,
    )
    limiter = install_cloud_request_limiter(  # type: ignore[arg-type]
        client,
        budget=budget,
    )

    requests = [
        asyncio.create_task(client._request("POST", f"/parent/{index}"))
        for index in range(3)
    ]
    try:
        results = await asyncio.wait_for(asyncio.gather(*requests), timeout=1)
        assert results == [{"success": True}] * 3
        assert client.login_calls == 1
        assert client.detect_calls == 1
    finally:
        for request in requests:
            if not request.done():
                request.cancel()
        if client.auth_task is not None and not client.auth_task.done():
            client.auth_task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        if client.auth_task is not None:
            await asyncio.gather(client.auth_task, return_exceptions=True)
        limiter.close()
        release_shared_cloud_request_budget(hass, budget)


async def test_lingering_auth_retains_admission_after_parents_cancel(hass):
    """A shielded auth task cannot become a fourth raw account operation."""
    client = _LingeringReactiveAuthClient()
    budget = acquire_shared_cloud_request_budget(
        hass,
        username="lingering-auth-account",
        base_url="https://monitor.eg4electronics.com",
        verify_ssl=True,
        limit=3,
    )
    limiter = install_cloud_request_limiter(  # type: ignore[arg-type]
        client,
        budget=budget,
    )
    parents = [
        asyncio.create_task(client._request("POST", f"/parent/{index}"))
        for index in range(3)
    ]
    ordinary: list[asyncio.Task[dict[str, Any]]] = []
    try:
        await asyncio.wait_for(client.auth_started.wait(), timeout=1)
        for parent in parents:
            parent.cancel()
        parent_results = await asyncio.gather(*parents, return_exceptions=True)
        assert all(
            isinstance(result, asyncio.CancelledError) for result in parent_results
        )
        assert client.auth_task is not None
        assert not client.auth_task.done()

        ordinary = [
            asyncio.create_task(client._request("POST", f"/ordinary/{index}"))
            for index in range(3)
        ]
        await asyncio.wait_for(client.two_ordinary_started.wait(), timeout=1)
        await asyncio.sleep(0)

        # The auth child retains one admitted parent lease until the whole
        # client-owned task finishes, leaving exactly two slots for new work.
        assert client.ordinary_started == 2
        assert not client.three_ordinary_started.is_set()
        assert client.active_raw == 3
        assert client.peak_raw == 3

        client.auth_release.set()
        await asyncio.wait_for(client.three_ordinary_started.wait(), timeout=1)
        assert await client.auth_task == {"success": True}
        assert client.peak_raw == 3

        client.ordinary_release.set()
        assert await asyncio.gather(*ordinary) == [{"success": True}] * 3
        assert client.active_raw == 0
    finally:
        client.auth_release.set()
        client.ordinary_release.set()
        for task in (*parents, *ordinary):
            if not task.done():
                task.cancel()
        await asyncio.gather(*parents, *ordinary, return_exceptions=True)
        if client.auth_task is not None:
            await asyncio.gather(client.auth_task, return_exceptions=True)
        limiter.close()
        release_shared_cloud_request_budget(hass, budget)


async def test_auth_reservation_survives_final_owner_reload(hass):
    """A replacement reuses the budget until a released owner's auth drains."""
    username = "auth-reload-account"
    base_url = "https://monitor.eg4electronics.com"
    old_client = _LingeringReactiveAuthClient(detect_after_login=False)
    budget = acquire_shared_cloud_request_budget(
        hass,
        username=username,
        base_url=base_url,
        verify_ssl=True,
        limit=3,
    )
    old_limiter = install_cloud_request_limiter(  # type: ignore[arg-type]
        old_client,
        budget=budget,
    )
    parents = [
        asyncio.create_task(old_client._request("POST", f"/parent/{index}"))
        for index in range(3)
    ]
    replacement_client = _CountingClient()
    replacement_limiter = None
    replacement_requests: list[asyncio.Task[dict[str, Any]]] = []
    replacement_budget = None
    try:
        await asyncio.wait_for(old_client.auth_started.wait(), timeout=1)
        for parent in parents:
            parent.cancel()
        await asyncio.gather(*parents, return_exceptions=True)
        assert old_client.auth_task is not None
        assert not old_client.auth_task.done()

        old_limiter.close()
        release_shared_cloud_request_budget(hass, budget)
        assert budget.ref_count == 0
        assert "eg4_web_monitor_cloud_request_budgets" in hass.data

        replacement_budget = acquire_shared_cloud_request_budget(
            hass,
            username=username,
            base_url=base_url,
            verify_ssl=True,
            limit=3,
        )
        assert replacement_budget is budget
        replacement_limiter = install_cloud_request_limiter(
            replacement_client,  # type: ignore[arg-type]
            budget=replacement_budget,
        )
        replacement_requests = [
            asyncio.create_task(
                replacement_client._request("POST", f"/replacement/{index}")
            )
            for index in range(3)
        ]
        await replacement_client._request_started.wait()
        await asyncio.sleep(0)

        # The old auth reservation consumes one account slot, so only two
        # replacement requests enter until that task finishes.
        assert replacement_client.calls == 2
        assert replacement_client.peak == 2

        old_client.auth_release.set()
        assert await old_client.auth_task == {"success": True}
        for _ in range(10):
            if replacement_client.calls == 3:
                break
            await asyncio.sleep(0)
        assert replacement_client.calls == 3
        assert replacement_client.peak == 3

        replacement_client._release_requests.set()
        assert await asyncio.gather(*replacement_requests) == [{"success": True}] * 3
        replacement_limiter.close()
        release_shared_cloud_request_budget(hass, replacement_budget)
        assert "eg4_web_monitor_cloud_request_budgets" not in hass.data
    finally:
        old_client.auth_release.set()
        replacement_client._release_requests.set()
        for task in (*parents, *replacement_requests):
            if not task.done():
                task.cancel()
        await asyncio.gather(*parents, *replacement_requests, return_exceptions=True)
        if old_client.auth_task is not None:
            await asyncio.gather(old_client.auth_task, return_exceptions=True)
        old_limiter.close()
        release_shared_cloud_request_budget(hass, budget)
        if replacement_limiter is not None:
            replacement_limiter.close()
        if replacement_budget is not None:
            release_shared_cloud_request_budget(hass, replacement_budget)


async def test_delayed_auth_claims_cancelled_parent_reservation(hass):
    """Delayed login keeps one origin slot and transparently avoids deadlock."""
    client = _DelayedReactiveAuthClient()
    budget = acquire_shared_cloud_request_budget(
        hass,
        username="retired-auth-account",
        base_url="https://monitor.eg4electronics.com",
        verify_ssl=True,
        limit=3,
    )
    limiter = install_cloud_request_limiter(  # type: ignore[arg-type]
        client,
        budget=budget,
    )
    parents = [
        asyncio.create_task(client._request("POST", f"/parent/{index}"))
        for index in range(3)
    ]
    fourth: asyncio.Task[dict[str, Any]] | None = None
    try:
        await asyncio.wait_for(client.auth_prework_started.wait(), timeout=1)
        await asyncio.wait_for(client.three_parents_started.wait(), timeout=1)

        # Parent zero created the auth task. Its cancellation hands one lease
        # reference to that pending task before the parent drops its own; a
        # fourth parent therefore remains queued instead of preempting login.
        parents[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await parents[0]
        fourth = asyncio.create_task(client._request("POST", "/parent/3"))
        await asyncio.sleep(0)
        assert not client.four_parents_started.is_set()

        client.allow_login.set()
        await asyncio.wait_for(client.four_parents_started.wait(), timeout=1)
        remaining = await asyncio.wait_for(
            asyncio.gather(*parents[1:], fourth),
            timeout=1,
        )

        assert remaining == [{"success": True}] * 3
        assert client.auth_task is not None
        assert await client.auth_task == {"success": True}
        assert client.login_calls == 1
        assert client.peak_parents == 3

        # All parent/reservation references have unwound, so a later refresh
        # is admitted rather than inheriting a leaked lifecycle lease.
        assert await asyncio.wait_for(
            client._request("POST", "/ordinary/recovery"), timeout=1
        ) == {"success": True}
    finally:
        client.allow_login.set()
        if fourth is not None and not fourth.done():
            fourth.cancel()
        for parent in parents:
            if not parent.done():
                parent.cancel()
        await asyncio.gather(
            *parents, *([fourth] if fourth else []), return_exceptions=True
        )
        if client.auth_task is not None:
            await asyncio.gather(client.auth_task, return_exceptions=True)
        limiter.close()
        release_shared_cloud_request_budget(hass, budget)
        assert "eg4_web_monitor_cloud_request_budgets" not in hass.data


async def test_inherited_unrelated_child_remains_inside_request_budget():
    """Only the exact auth chain, not arbitrary descendants, bypasses admission."""
    client = _InheritedOrdinaryChildClient()
    install_cloud_request_limiter(client, limit=1)  # type: ignore[arg-type]
    parent = asyncio.create_task(client._request("POST", "/parent"))
    await client.child_created.wait()
    await asyncio.sleep(0)

    assert not client.child_started.is_set()
    client.release_parent.set()
    await parent
    assert client.child_task is not None
    await client.child_task
    assert client.child_started.is_set()


async def test_parameter_verification_fetches_parameters_only(hass):
    """A post-write verification must not force runtime/energy/battery reads."""
    entry = _local_entry()
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)

    inverter = MagicMock()
    inverter.parameters = {"HOLD_AC_CHARGE_POWER_CMD": 50}
    inverter.parameters_complete = True
    inverter._fetch_parameters = AsyncMock()
    inverter.refresh = AsyncMock()
    coordinator._inverter_cache = {"INV1": inverter}
    coordinator.data = {"devices": {"INV1": {"type": "inverter"}}}

    assert await coordinator._refresh_device_parameters("INV1") is True
    inverter._fetch_parameters.assert_awaited_once_with()
    inverter.refresh.assert_not_awaited()


async def test_targeted_parameter_refresh_does_not_poll_sibling_or_schedule_tick(
    hass,
):
    """Post-write verification mutates one serial and publishes once in place."""
    entry = _local_entry("parameter_target")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)

    target = MagicMock()
    target.parameters = {"HOLD_AC_CHARGE_POWER_CMD": 75}
    target.parameters_complete = True
    target._fetch_parameters = AsyncMock()
    sibling = MagicMock()
    sibling.parameters = {"HOLD_AC_CHARGE_POWER_CMD": 20}
    sibling.parameters_complete = True
    sibling._fetch_parameters = AsyncMock()
    coordinator._inverter_cache = {"INV1": target, "INV2": sibling}
    coordinator.data = {
        "devices": {
            "INV1": {"type": "inverter"},
            "INV2": {"type": "inverter"},
        },
        "parameters": {
            "INV1": {"HOLD_AC_CHARGE_POWER_CMD": 50},
            "INV2": {"HOLD_AC_CHARGE_POWER_CMD": 20},
        },
    }
    coordinator.async_update_listeners = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    assert await coordinator.async_refresh_device_parameters("INV1") is True

    target._fetch_parameters.assert_awaited_once_with()
    sibling._fetch_parameters.assert_not_awaited()
    coordinator.async_update_listeners.assert_called_once_with()
    coordinator.async_request_refresh.assert_not_awaited()
    assert coordinator.data["parameters"]["INV2"] == {"HOLD_AC_CHARGE_POWER_CMD": 20}


async def test_parameter_publication_selects_target_and_discovery_contexts(hass):
    """The #532 listener seam scopes and dispatches one serial when available."""
    entry = _local_entry("parameter_publish")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    context_factory = getattr(coordinator_module, "device_listener_context", None)
    if callable(context_factory):
        # Post-#532 merge validation: use the integration's exact private
        # context class so its isinstance-based dispatcher is exercised.
        target = context_factory("INV1")
        sibling = context_factory("INV2")
        discovery = coordinator_module.DISCOVERY_LISTENER_CONTEXT
        station = coordinator_module.STATION_LISTENER_CONTEXT
    else:
        # Standalone #533 validation before #532 lands: pin the context values
        # selected by the feature-detected publication seam.
        target = _ListenerScope("device", "INV1")
        sibling = _ListenerScope("device", "INV2")
        discovery = _ListenerScope("discovery")
        station = _ListenerScope("station")
    coordinator._pending_listener_contexts = set()
    callbacks = {
        name: MagicMock() for name in ("target", "sibling", "discovery", "station")
    }
    coordinator._listeners = {
        "target": (callbacks["target"], target),
        "sibling": (callbacks["sibling"], sibling),
        "discovery": (callbacks["discovery"], discovery),
        "station": (callbacks["station"], station),
    }
    if callable(context_factory):
        coordinator._last_listener_update_success = coordinator.last_update_success
        coordinator._publish_device_parameter_update("INV1")
        callbacks["target"].assert_called_once_with()
        callbacks["discovery"].assert_called_once_with()
        callbacks["sibling"].assert_not_called()
        callbacks["station"].assert_not_called()
    else:
        selected: list[set[Any]] = []
        coordinator.async_update_listeners = MagicMock(
            side_effect=lambda: selected.append(
                set(coordinator._pending_listener_contexts)
            )
        )
        coordinator._publish_device_parameter_update("INV1")
        assert selected == [{target, discovery}]


async def test_group_parameter_refresh_publishes_all_devices_once(hass):
    """A parallel-group refresh dispatches all changed siblings in one batch."""
    entry = _local_entry("group_parameter_publish")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "devices": {
            "INV1": {"type": "inverter"},
            "INV2": {"type": "inverter"},
        }
    }
    coordinator._refresh_device_parameters = AsyncMock(return_value=True)
    context_factory = getattr(coordinator_module, "device_listener_context", None)
    if callable(context_factory):
        first = context_factory("INV1")
        second = context_factory("INV2")
        discovery = coordinator_module.DISCOVERY_LISTENER_CONTEXT
        station = coordinator_module.STATION_LISTENER_CONTEXT
    else:
        first = _ListenerScope("device", "INV1")
        second = _ListenerScope("device", "INV2")
        discovery = _ListenerScope("discovery")
        station = _ListenerScope("station")
    coordinator._pending_listener_contexts = set()
    callbacks = {
        name: MagicMock() for name in ("first", "second", "discovery", "station")
    }
    coordinator._listeners = {
        "first": (callbacks["first"], first),
        "second": (callbacks["second"], second),
        "discovery": (callbacks["discovery"], discovery),
        "station": (callbacks["station"], station),
    }

    if callable(context_factory):
        coordinator._last_listener_update_success = coordinator.last_update_success
        assert await coordinator.refresh_all_device_parameters() is True
        callbacks["first"].assert_called_once_with()
        callbacks["second"].assert_called_once_with()
        callbacks["discovery"].assert_called_once_with()
        callbacks["station"].assert_not_called()
    else:
        selected: list[set[Any]] = []
        coordinator.async_update_listeners = MagicMock(
            side_effect=lambda: selected.append(
                set(coordinator._pending_listener_contexts)
            )
        )
        assert await coordinator.refresh_all_device_parameters() is True
        assert selected == [{first, second, discovery}]


async def test_narrow_parameter_fetch_preserves_generation_reconcile_seam(hass):
    """A stale narrow read cannot overwrite a write acknowledged mid-read."""
    entry = _local_entry("parameter_generation")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    read_started = asyncio.Event()
    release_read = asyncio.Event()

    inverter = MagicMock()
    inverter.parameters = {"HOLD_CHG_POWER_PERCENT_CMD": 60}
    inverter.parameters_complete = True

    async def _stale_fetch() -> None:
        read_started.set()
        await release_read.wait()
        inverter.parameters = {"HOLD_CHG_POWER_PERCENT_CMD": 60}

    inverter._fetch_parameters = AsyncMock(side_effect=_stale_fetch)
    coordinator._inverter_cache = {"INV1": inverter}
    coordinator.data = {
        "devices": {"INV1": {"type": "inverter"}},
        "parameters": {"INV1": {"HOLD_CHG_POWER_PERCENT_CMD": 60}},
    }
    coordinator._parameter_write_generation = 7
    coordinator._parameter_write_seeds = {}
    reconcile = MagicMock(return_value={"HOLD_CHG_POWER_PERCENT_CMD": 90})
    coordinator._reconcile_parameter_read = reconcile

    refresh = asyncio.create_task(coordinator._refresh_device_parameters("INV1"))
    await read_started.wait()
    coordinator._parameter_write_generation = 8
    coordinator.data["parameters"]["INV1"] = {"HOLD_CHG_POWER_PERCENT_CMD": 90}
    release_read.set()

    assert await refresh is True
    assert coordinator.data["parameters"]["INV1"] == {"HOLD_CHG_POWER_PERCENT_CMD": 90}
    reconcile.assert_called_once_with(
        "INV1",
        {"HOLD_CHG_POWER_PERCENT_CMD": 60},
        read_complete=True,
        read_generation=7,
        observed_keys={"HOLD_CHG_POWER_PERCENT_CMD": 60},
    )


async def test_missing_parameter_refresh_job_is_single_flight(hass):
    """Repeated update cycles share one coordinator-owned missing-data job."""
    entry = _local_entry("missing_singleflight")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_refresh(serials: list[str], processed_data: dict[str, Any]) -> None:
        del serials, processed_data
        started.set()
        await release.wait()

    coordinator._refresh_missing_parameters = AsyncMock(side_effect=_slow_refresh)
    first_data: dict[str, Any] = {"parameters": {}}
    second_data: dict[str, Any] = {"parameters": {}}

    first = coordinator._schedule_missing_parameter_refresh(["INV1"], first_data)
    await started.wait()
    second = coordinator._schedule_missing_parameter_refresh(["INV1"], second_data)

    assert second is first
    assert coordinator._refresh_missing_parameters.await_count == 1

    release.set()
    await first
    await asyncio.sleep(0)
    assert first not in coordinator._background_tasks


async def test_cancelled_missing_parameter_job_does_not_resurrect(hass):
    """Unload cancellation clears ownership and never starts queued work."""
    entry = _local_entry("missing_cancel")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    started = asyncio.Event()

    async def _blocked_refresh(
        serials: list[str], processed_data: dict[str, Any]
    ) -> None:
        del serials, processed_data
        started.set()
        await asyncio.Event().wait()

    coordinator._refresh_missing_parameters = AsyncMock(side_effect=_blocked_refresh)
    task = coordinator._schedule_missing_parameter_refresh(["INV1"], {"parameters": {}})
    await started.wait()
    coordinator._schedule_missing_parameter_refresh(
        ["INV1", "INV2"], {"parameters": {}}
    )

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert coordinator._missing_parameter_refresh_task is None
    assert coordinator._missing_parameter_pending_serials == set()
    assert coordinator._refresh_missing_parameters.await_count == 1


async def test_completed_missing_parameter_callback_cannot_reschedule_during_shutdown(
    hass,
):
    """A done callback racing the shutdown snapshot cannot orphan its next batch."""
    entry = _local_entry("missing_shutdown_callback")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def _finish_normally(
        serials: list[str], processed_data: dict[str, Any]
    ) -> None:
        del serials, processed_data
        started.set()
        await finish.wait()

    coordinator._refresh_missing_parameters = AsyncMock(side_effect=_finish_normally)
    first = coordinator._schedule_missing_parameter_refresh(
        ["INV1"], {"parameters": {}}
    )
    assert first is not None
    await started.wait()
    coordinator._schedule_missing_parameter_refresh(
        ["INV1", "INV2"], {"parameters": {}}
    )

    try:
        finish.set()
        # The task finishes in this loop turn. Its done callbacks are queued
        # behind this test's continuation, reproducing shutdown observing a
        # done task whose rescheduling callback has not run yet.
        await asyncio.sleep(0)
        assert first.done()
        assert coordinator._missing_parameter_refresh_task is first

        await coordinator._cancel_background_tasks()
        await asyncio.sleep(0)

        assert coordinator._refresh_missing_parameters.await_count == 1
        assert coordinator._missing_parameter_refresh_task is None
        assert coordinator._missing_parameter_pending_serials == set()
        assert coordinator._missing_parameter_pending_data is None
        assert coordinator._background_tasks == set()
    finally:
        remaining = coordinator._missing_parameter_refresh_task
        if remaining is not None and not remaining.done():
            remaining.cancel()
            await asyncio.gather(remaining, return_exceptions=True)


async def test_new_missing_serial_is_queued_behind_active_singleflight(hass):
    """A newly discovered inverter is delayed, not dropped or overlapped."""
    entry = _local_entry("missing_queue")
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()
    batches: list[list[str]] = []

    async def _refresh(serials: list[str], processed_data: dict[str, Any]) -> None:
        del processed_data
        batches.append(serials)
        if len(batches) == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_finished.set()

    coordinator._refresh_missing_parameters = AsyncMock(side_effect=_refresh)
    first = coordinator._schedule_missing_parameter_refresh(
        ["INV1"], {"parameters": {}}
    )
    await first_started.wait()
    shared = coordinator._schedule_missing_parameter_refresh(
        ["INV1", "INV2"], {"parameters": {}}
    )
    assert shared is first

    release_first.set()
    await first
    await second_finished.wait()
    second = coordinator._missing_parameter_refresh_task
    if second is not None:
        await second
    assert batches == [["INV1"], ["INV2"]]


async def test_firmware_account_status_is_single_flight_and_shielded(hass):
    """All device polls share one status request; one cancelled waiter is isolated."""
    client = _CountingClient()
    status_started = asyncio.Event()
    status_release = asyncio.Event()
    response = object()

    async def _status() -> object:
        status_started.set()
        await status_release.wait()
        return response

    original_status = AsyncMock(side_effect=_status)
    client.api.firmware.get_firmware_update_status = original_status
    entry = _http_entry("firmware_singleflight")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, entry)

    shared_status = client.api.firmware.get_firmware_update_status
    first = asyncio.create_task(shared_status())
    second = asyncio.create_task(shared_status())
    await status_started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    # Cancelling one consumer does not cancel the coordinator-owned request.
    assert original_status.await_count == 1
    assert not second.done()
    status_release.set()
    assert await second is response
    await asyncio.sleep(0)
    assert coordinator._firmware_status_flight is not None
    assert coordinator._firmware_status_flight.task is None
    await coordinator._release_shared_firmware_status()


async def test_firmware_singleflight_cancels_raw_after_final_waiter_leaves(hass):
    """A timed-out/cancelled lone consumer cannot orphan a cloud request slot."""
    client = _CountingClient()
    status_started = asyncio.Event()
    raw_cancelled = asyncio.Event()

    async def _status() -> None:
        status_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raw_cancelled.set()
            raise

    client.api.firmware.get_firmware_update_status = AsyncMock(side_effect=_status)
    entry = _http_entry("firmware_last_waiter")
    entry.add_to_hass(hass)
    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, entry)

    waiter = asyncio.create_task(client.api.firmware.get_firmware_update_status())
    await status_started.wait()
    flight = coordinator._firmware_status_flight
    assert flight is not None
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await raw_cancelled.wait()
    await asyncio.sleep(0)

    assert flight.task is None
    await coordinator._release_shared_firmware_status()


async def test_firmware_prefetch_does_not_start_getters_when_breaker_is_open(hass):
    """A pre-opened supplemental breaker admits no firmware coroutine body."""
    client = _CountingClient()
    original_status = AsyncMock(return_value=object())
    client.api.firmware.get_firmware_update_status = original_status
    entry = _http_entry("firmware_open_breaker")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, entry)

    device = make_real_inverter(serial_number="INV1", client=client)
    check = AsyncMock(wraps=device.check_firmware_updates)
    progress = AsyncMock(wraps=device.get_firmware_update_progress)
    device.check_firmware_updates = check
    device.get_firmware_update_progress = progress
    coordinator._sidefetch_open_until = time.monotonic() + 60

    await coordinator._prefetch_firmware_update_info([device])

    check.assert_not_called()
    progress.assert_not_called()
    original_status.assert_not_awaited()
    await coordinator._release_shared_firmware_status()


async def test_firmware_prefetch_deduplicates_multi_inverter_status_calls(hass):
    """Real pylxpweb devices align on one account-wide progress call."""
    client = _CountingClient()
    response = FirmwareUpdateStatus(
        receiving=False,
        progressing=False,
        fileReady=False,
        deviceInfos=[],
    )
    original_status = AsyncMock(return_value=response)
    client.api.firmware.get_firmware_update_status = original_status
    entry = _http_entry("firmware_prefetch")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
        return_value=client,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, entry)

    devices = []
    for index in range(7):
        device = make_real_inverter(serial_number=f"INV{index}", client=client)
        device._firmware_update_info = FirmwareUpdateInfo(
            installed_version="1.0.0",
            latest_version="1.0.0",
            title="Firmware",
        )
        # Availability stays inside its 24-hour cache, while progress is past
        # its idle five-minute TTL and therefore reaches the account endpoint.
        device._firmware_update_cache_time = datetime.now() - timedelta(minutes=6)
        devices.append(device)

    await coordinator._prefetch_firmware_update_info(devices)

    assert original_status.await_count == 1
    assert all(device.firmware_update_in_progress is False for device in devices)
    await coordinator._release_shared_firmware_status()


async def test_firmware_singleflight_is_shared_by_same_account_entries(hass):
    """Two plants on one account share status while retaining safe ownership."""
    clients = [_CountingClient(), _CountingClient()]
    status_started = asyncio.Event()
    status_release = asyncio.Event()
    originals: list[AsyncMock] = []

    for index, client in enumerate(clients):

        async def _status(index: int = index) -> int:
            status_started.set()
            await status_release.wait()
            return index

        original = AsyncMock(side_effect=_status)
        originals.append(original)
        client.api.firmware.get_firmware_update_status = original

    coordinators: list[EG4DataUpdateCoordinator] = []
    for index, client in enumerate(clients):
        entry = _http_entry(
            f"firmware_owner_{index}",
            username="shared-account",
            plant_id=f"plant-{index}",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=client,
        ):
            coordinators.append(EG4DataUpdateCoordinator(hass, entry))

    waiters = [
        asyncio.create_task(client.api.firmware.get_firmware_update_status())
        for client in clients
    ]
    try:
        await status_started.wait()
        await asyncio.sleep(0)

        assert sum(original.await_count for original in originals) == 1
        flight = coordinators[0]._firmware_status_flight
        assert flight is not None
        assert coordinators[1]._firmware_status_flight is flight
        assert flight.ref_count == 2
        winner = next(
            index
            for index, original in enumerate(originals)
            if original.await_count == 1
        )
        released = 1 - winner

        waiters[released].cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiters[released]
        await coordinators[released]._release_shared_firmware_status()

        assert flight.ref_count == 1
        assert flight.task is not None
        assert not flight.task.cancelled()
        assert not waiters[winner].done()

        status_release.set()
        assert await waiters[winner] == winner
        await coordinators[winner]._release_shared_firmware_status()
        assert flight.ref_count == 0
        assert flight.task is None
    finally:
        status_release.set()
        await asyncio.gather(*waiters, return_exceptions=True)
        for coordinator in coordinators:
            release = getattr(coordinator, "_release_shared_firmware_status", None)
            if release is not None:
                await release()


@pytest.mark.parametrize("transform_retirement", [False, True])
async def test_firmware_singleflight_transfers_when_origin_entry_unloads(
    hass, transform_retirement: bool
):
    """A surviving plant retries instead of inheriting its peer's closing client."""
    clients = [_CountingClient(), _CountingClient()]
    auth_dependency = asyncio.create_task(asyncio.Event().wait())
    origin_started = asyncio.Event()
    origin_cancelled = asyncio.Event()

    async def _close_origin_client() -> None:
        auth_dependency.cancel()
        await asyncio.gather(auth_dependency, return_exceptions=True)

    origin_close = AsyncMock(side_effect=_close_origin_client)
    setattr(clients[0], "close", origin_close)

    async def _origin_status() -> str:
        origin_started.set()
        try:
            # Model pylxpweb #261: the status request is owned by client A and
            # awaits that client's shielded authentication task. client.close
            # cancels the auth task immediately after coordinator shutdown.
            await asyncio.shield(auth_dependency)
        except asyncio.CancelledError:
            origin_cancelled.set()
            if transform_retirement:
                # A future dependency may translate cancellation while
                # unwinding client shutdown. Surviving owners must identify
                # the deliberately retired task, not one exception shape.
                raise RuntimeError("origin client retired") from None
            raise
        return "origin"

    originals = [
        AsyncMock(side_effect=_origin_status),
        AsyncMock(return_value="survivor"),
    ]
    coordinators: list[EG4DataUpdateCoordinator] = []
    waiters: list[asyncio.Task[Any]] = []
    for index, (client, original) in enumerate(zip(clients, originals, strict=True)):
        client.api.firmware.get_firmware_update_status = original
        entry = _http_entry(
            f"firmware_transfer_{index}",
            username="shared-transfer-account",
            plant_id=f"plant-{index}",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=client,
        ):
            coordinators.append(EG4DataUpdateCoordinator(hass, entry))

    try:
        waiters.append(
            asyncio.create_task(clients[0].api.firmware.get_firmware_update_status())
        )
        await origin_started.wait()
        waiters.append(
            asyncio.create_task(
                coordinators[1]._breakered_cloud_call(
                    lambda: clients[1].api.firmware.get_firmware_update_status(),
                    timeout=1,
                )
            )
        )
        await asyncio.sleep(0)
        originals[1].assert_not_awaited()

        # Coordinator shutdown precedes client.close. Releasing client A must
        # retire A's raw flight so B can retry through its own bound getter.
        await coordinators[0]._release_shared_firmware_status()
        await clients[0].close()  # type: ignore[attr-defined]
        await asyncio.wait_for(origin_cancelled.wait(), timeout=1)

        expected_origin_error = (
            RuntimeError if transform_retirement else asyncio.CancelledError
        )
        with pytest.raises(expected_origin_error):
            await waiters[0]
        assert await waiters[1] == "survivor"
        originals[0].assert_awaited_once_with()
        originals[1].assert_awaited_once_with()
        origin_close.assert_awaited_once_with()
        assert coordinators[1]._sidefetch_consecutive_failures == 0
        assert coordinators[1]._sidefetch_open_until is None
    finally:
        auth_dependency.cancel()
        await asyncio.gather(auth_dependency, *waiters, return_exceptions=True)
        await asyncio.gather(
            *(
                coordinator._release_shared_firmware_status()
                for coordinator in coordinators
            )
        )


async def test_firmware_singleflight_does_not_cross_cloud_accounts(hass):
    """Account identity remains an isolation boundary for status requests."""
    clients = [_CountingClient(), _CountingClient()]
    originals = [AsyncMock(return_value=index) for index in range(2)]
    coordinators: list[EG4DataUpdateCoordinator] = []

    for index, (client, original) in enumerate(zip(clients, originals, strict=True)):
        client.api.firmware.get_firmware_update_status = original
        entry = _http_entry(
            f"firmware_account_{index}",
            username=f"account-{index}",
            plant_id=f"plant-{index}",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.LuxpowerClient",
            return_value=client,
        ):
            coordinators.append(EG4DataUpdateCoordinator(hass, entry))

    try:
        results = await asyncio.gather(
            *(client.api.firmware.get_firmware_update_status() for client in clients)
        )

        assert results == [0, 1]
        assert [original.await_count for original in originals] == [1, 1]
        assert (
            coordinators[0]._firmware_status_flight
            is not coordinators[1]._firmware_status_flight
        )
    finally:
        await asyncio.gather(
            *(
                coordinator._release_shared_firmware_status()
                for coordinator in coordinators
            )
        )
