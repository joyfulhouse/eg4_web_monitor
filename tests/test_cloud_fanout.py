"""Regression tests for bounded and deduplicated cloud polling (eg4-06er.5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pylxpweb.models import FirmwareUpdateInfo, FirmwareUpdateStatus

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


def _http_entry(entry_id: str = "cloud_fanout") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Cloud fanout",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_PLANT_ID: "12345",
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
        },
        entry_id=entry_id,
    )


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
    assert coordinator._firmware_status_task is None


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


async def test_firmware_singleflight_is_owned_by_one_config_entry(hass):
    """Unloading one entry cannot cancel another entry's status request."""
    clients = [_CountingClient(), _CountingClient()]
    starts = [asyncio.Event(), asyncio.Event()]
    releases = [asyncio.Event(), asyncio.Event()]
    originals: list[AsyncMock] = []

    for index, client in enumerate(clients):

        async def _status(index: int = index) -> int:
            starts[index].set()
            await releases[index].wait()
            return index

        original = AsyncMock(side_effect=_status)
        originals.append(original)
        client.api.firmware.get_firmware_update_status = original

    coordinators: list[EG4DataUpdateCoordinator] = []
    for index, client in enumerate(clients):
        entry = _http_entry(f"firmware_owner_{index}")
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
    await asyncio.gather(*(started.wait() for started in starts))

    await coordinators[0]._cancel_background_tasks()
    result = await asyncio.gather(waiters[0], return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert not waiters[1].done()
    assert originals[0].await_count == 1
    assert originals[1].await_count == 1

    releases[1].set()
    assert await waiters[1] == 1
