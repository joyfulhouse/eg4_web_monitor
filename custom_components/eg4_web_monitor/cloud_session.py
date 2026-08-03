"""Cancellation-safe cleanup for cookie-bearing cloud sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import inspect
from typing import Any, cast

import aiohttp


async def _async_drain_awaitable(awaitable: Awaitable[Any]) -> None:
    """Wait for one cleanup operation despite repeated caller cancellation.

    ``asyncio.wait`` observes completion without propagating caller cancellation
    into the dependency-owned task. Catching cancellation lets us keep waiting
    for that exact operation; the first cancellation is re-raised only after the
    operation has settled. Retrieving the result also prevents an exceptional
    cleanup task from becoming an unobserved task exception.
    """
    cleanup_future = asyncio.ensure_future(awaitable)
    caller_cancellation: asyncio.CancelledError | None = None

    while not cleanup_future.done():
        try:
            await asyncio.wait({cleanup_future})
        except asyncio.CancelledError as err:
            if caller_cancellation is None:
                caller_cancellation = err

    cleanup_error: BaseException | None = None
    try:
        cleanup_future.result()
    except BaseException as err:  # includes child-task cancellation
        cleanup_error = err

    if caller_cancellation is not None:
        if cleanup_error is not None:
            raise caller_cancellation from cleanup_error
        raise caller_cancellation
    if cleanup_error is not None:
        raise cleanup_error


async def async_close_client_session(
    client: object | None,
    session: aiohttp.ClientSession | None,
) -> None:
    """Drain client-owned work before detaching its injected HA session."""
    try:
        close = getattr(client, "close", None)
        if close is not None:
            close_result: Any = close()
            if inspect.isawaitable(close_result):
                await _async_drain_awaitable(cast(Awaitable[Any], close_result))
    finally:
        # HA owns the connector. Detach releases only this wrapper and its
        # account-private CookieJar after dependency-owned work has stopped.
        if session is not None and not session.closed:
            session.detach()
