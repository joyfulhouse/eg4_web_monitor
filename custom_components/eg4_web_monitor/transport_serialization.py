"""Serialize local transport operations by physical endpoint."""

from __future__ import annotations

import asyncio
from typing import Any


def physical_endpoint_key(transport: Any) -> str | None:
    """Return the physical connection key for a local transport.

    Network transports share a host/port endpoint. Serial transports expose
    their tty path as ``port`` without a host. Transports without either
    public shape cannot be proven to share hardware and remain unchanged.
    """
    host = getattr(transport, "host", None)
    port = getattr(transport, "port", None)
    if host is not None and port is not None:
        return f"network:{str(host).strip().casefold()}:{port}"
    if isinstance(port, str) and port:
        return f"serial:{port}"
    return None


class EndpointOperationLock:
    """Task-reentrant lock shared by transports on one physical endpoint.

    pylxpweb transport operations can re-enter their operation lock: a named
    parameter write holds it across the whole read-modify-write sequence and
    calls raw read/write methods that acquire it again. A plain asyncio lock
    would deadlock that valid nesting, so the integration-owned endpoint lock
    mirrors that task-reentrant contract while expanding its ownership from
    one transport object to every logical device on the same adapter.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> EndpointOperationLock:
        """Acquire the endpoint, or re-enter it from the owning task."""
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            self._depth += 1
            return self
        await self._lock.acquire()
        self._owner = task
        self._depth = 1
        return self

    async def __aexit__(self, *_: object) -> None:
        """Release one nesting level and wake the next endpoint operation."""
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()
