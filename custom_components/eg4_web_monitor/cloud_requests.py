"""Coordinator-owned concurrency controls for pylxpweb cloud requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pylxpweb import LuxpowerClient

CloudRequest = Callable[..., Awaitable[dict[str, Any]]]


class CloudRequestLimiter:
    """Bound one client's request chains without deadlocking recursive retries.

    pylxpweb performs retry and re-authentication by recursively calling the
    client's private ``_request`` method.  A plain semaphore wrapper would
    acquire a slot twice in the same task and can deadlock when every slot is
    occupied by a retrying request.  The context variable makes a request
    *chain* re-entrant while independently-created requests still consume one
    slot each.

    The limiter belongs to one ``LuxpowerClient``.  It is deliberately not
    stored in ``hass.data``: separate config entries keep separate clients and
    unloading one entry cannot own or cancel another entry's requests.
    """

    def __init__(self, request: CloudRequest, *, limit: int) -> None:
        if limit < 1:
            raise ValueError("Cloud request limit must be at least one")
        self._request = request
        self._semaphore = asyncio.Semaphore(limit)
        self._request_owner: ContextVar[asyncio.Task[Any] | None] = ContextVar(
            f"eg4_cloud_request_{id(self)}", default=None
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
        kwargs = {
            "data": data,
            "cache_key": cache_key,
            "cache_endpoint": cache_endpoint,
            "_retry_count": _retry_count,
        }
        current_task = asyncio.current_task()
        if current_task is not None and self._request_owner.get() is current_task:
            return await self._request(method, endpoint, **kwargs)

        async with self._semaphore:
            token = self._request_owner.set(current_task)
            try:
                return await self._request(method, endpoint, **kwargs)
            finally:
                self._request_owner.reset(token)


def install_cloud_request_limiter(
    client: LuxpowerClient, *, limit: int
) -> CloudRequestLimiter:
    """Install a per-client limiter at pylxpweb's common request boundary."""
    limiter = CloudRequestLimiter(client._request, limit=limit)
    # pylxpweb's endpoint objects resolve ``client._request`` dynamically, and
    # its retries recurse through the same attribute.  Binding on the instance
    # therefore covers Station.load cache warming and every standard endpoint
    # without replacing the HA-owned aiohttp session.
    setattr(client, "_request", limiter.request)
    return limiter
