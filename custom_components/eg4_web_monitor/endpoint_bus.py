"""Exclusive ownership and capabilities for physical local-bus endpoints."""

from __future__ import annotations

import asyncio
from builtins import BaseExceptionGroup
from collections.abc import AsyncIterator, Callable, Collection, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
import inspect
import time
from typing import Any, Protocol, cast
from uuid import uuid4

from pylxpweb.transports import (
    RegisterObservation,
    RegisterObserver,
    create_transport_from_config,
)
from pylxpweb.transports.capabilities import TransportCapabilities
from pylxpweb.transports.config import TransportConfig, TransportType

from .bus_eligibility import LocalBusProvenance
from .raw_snapshot import (
    CrcValidationState,
    FreshnessPolicy,
    LatestCompleteRawSnapshotStore,
    RawRegisterBlock,
    RawSnapshotFrame,
    SnapshotHealth,
    SnapshotMetrics,
    SnapshotValidationState,
)


class EndpointOwnerClosingError(RuntimeError):
    """Raised while a terminal owner tombstone blocks replacement."""


class EndpointCapabilityClosedError(RuntimeError):
    """Raised when work is submitted through a terminal capability."""


class EndpointAdmissionError(RuntimeError):
    """Raised when an endpoint already has its bounded number of waiters."""


class EndpointOwnerInUseError(RuntimeError):
    """Raised when discovery would perturb an endpoint that is already owned."""


class _OwnerState(StrEnum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class _PhysicalEndpointKey:
    """Normalized adapter connection and bus identity; never diagnostic."""

    kind: str
    connection: str
    bus: int


@dataclass(frozen=True, slots=True)
class EndpointBusStatus:
    """Redacted owner status exposed through a capability."""

    owner_identity: int
    state: str
    capability_count: int
    in_flight: int


class _RawLocalTransport(Protocol):
    """Complete raw surface consumed only inside this ownership module."""

    serial: str
    is_connected: bool
    capabilities: TransportCapabilities
    transport_type: str
    inverter_family: Any
    split_phase: bool
    pv_string_count: int
    is_midbox_device: bool
    register_observation_error_count: int

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_runtime(self) -> Any: ...

    async def read_energy(self) -> Any: ...

    async def read_battery(self) -> Any: ...

    async def read_parameters(self, start: int, count: int) -> dict[int, int]: ...

    async def write_parameters(self, parameters: dict[int, int]) -> bool: ...

    async def read_named_parameters(self, start: int, count: int) -> dict[str, Any]: ...

    async def write_named_parameters(self, parameters: dict[str, Any]) -> bool: ...

    async def read_device_type(self) -> int: ...

    async def read_firmware_version(self) -> str: ...

    async def read_parallel_config(self) -> int: ...

    async def read_serial_number(self) -> str: ...

    async def read_midbox_runtime(self) -> Any: ...


RawTransportFactory = Callable[..., _RawLocalTransport]
ENDPOINT_BUS_REGISTRY_DATA = "eg4_web_monitor_endpoint_bus_registry"
MAX_ENDPOINT_WAITERS = 64
ENDPOINT_ACQUIRE_TIMEOUT_SECONDS = 10.0
MAX_SNAPSHOT_STAGED_INVOCATIONS = 256
MAX_SNAPSHOT_STAGED_BLOCKS = 256
MAX_SNAPSHOT_STAGED_WORDS = 16_384


async def _await_settled(
    future: asyncio.Future[Any],
) -> asyncio.CancelledError | None:
    """Wait for terminal settlement without discarding caller cancellation."""
    cancellation: asyncio.CancelledError | None = None
    while not future.done():
        try:
            await asyncio.wait({future})
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
    return cancellation


def _default_raw_transport_factory(
    config: TransportConfig,
    *,
    register_observer: RegisterObserver | None = None,
) -> _RawLocalTransport:
    """Construct a raw transport at the single repository construction site."""
    return cast(
        _RawLocalTransport,
        create_transport_from_config(config, register_observer=register_observer),
    )


def _construct_raw_transport(
    factory: RawTransportFactory,
    config: TransportConfig,
    observer: RegisterObserver | None,
) -> _RawLocalTransport:
    """Call observer-aware factories while retaining existing injected fakes."""
    parameters = inspect.signature(factory).parameters.values()
    accepts_observer = any(
        parameter.name == "register_observer"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_observer:
        return factory(config, register_observer=observer)
    return factory(config)


def _endpoint_key(config: TransportConfig) -> _PhysicalEndpointKey:
    """Normalize one public pylxpweb transport configuration."""
    if config.transport_type is TransportType.MODBUS_SERIAL:
        connection = str(config.serial_port or "").strip()
        if not connection:
            raise ValueError("Serial endpoint is ambiguous")
        return _PhysicalEndpointKey("serial", connection, 0)

    connection = str(config.host or "").strip().casefold()
    if not connection:
        raise ValueError("Network endpoint is ambiguous")
    return _PhysicalEndpointKey("network", connection, int(config.port))


class _TaskReentrantGate:
    """Task-reentrant endpoint gate that can outlive a cancelled waiter."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0
        self._wire_holds = 0
        self._waiters = 0

    async def acquire(self, *, deadline: bool = True) -> None:
        """Acquire or re-enter from the current task."""
        task = asyncio.current_task()
        if task is not None and task is self._owner and self._depth > 0:
            self._depth += 1
            return
        if self._lock.locked():
            if deadline and self._waiters >= MAX_ENDPOINT_WAITERS:
                raise EndpointAdmissionError("Endpoint admission limit reached")
            self._waiters += 1
            try:
                if deadline:
                    try:
                        async with asyncio.timeout(ENDPOINT_ACQUIRE_TIMEOUT_SECONDS):
                            await self._lock.acquire()
                    except TimeoutError as err:
                        raise EndpointAdmissionError(
                            "Endpoint admission deadline exceeded"
                        ) from err
                else:
                    await self._lock.acquire()
            finally:
                self._waiters -= 1
        else:
            await self._lock.acquire()
        self._owner = task
        self._depth = 1

    def release(self) -> None:
        """Release one task nesting level."""
        self._depth -= 1
        self._release_if_idle()

    def hold_for_wire_task(self, task: asyncio.Task[Any]) -> None:
        """Keep the endpoint closed to successors until wire work terminates."""
        self._wire_holds += 1
        task.add_done_callback(self._wire_task_done)

    def hold_if_locked(self) -> bool:
        """Keep an active gate held across its token's terminal interrupt."""
        if not self._lock.locked():
            return False
        self._wire_holds += 1
        return True

    def release_hold(self) -> None:
        """Release a non-task hold reserved for terminal interruption."""
        self._wire_holds -= 1
        self._release_if_idle()

    def _wire_task_done(self, task: asyncio.Task[Any]) -> None:
        self._wire_holds -= 1
        if not task.cancelled():
            task.exception()
        self._release_if_idle()

    def _release_if_idle(self) -> None:
        if self._depth == 0 and self._wire_holds == 0 and self._lock.locked():
            self._owner = None
            self._lock.release()


@dataclass(slots=True)
class _CapabilityRecord:
    raw: _RawLocalTransport
    closing: bool = False
    snapshot_state: _UnitSnapshotState | None = None
    snapshot_observer_capable: bool = False
    snapshot_enabled: bool = False
    unit: int = 0
    firmware_scope: str | None = None
    active_attempt: _SnapshotAttempt | None = None


@dataclass(slots=True)
class _UnitSnapshotState:
    """The one retained latest-complete store for an endpoint/unit."""

    store: LatestCompleteRawSnapshotStore
    generation: int = 0
    poll_cycle: int = 0


@dataclass(slots=True)
class _SnapshotAttempt:
    """Bounded mutable state visible only during one owner refresh."""

    identity: int
    started: float
    observer_errors_before: int
    expected_invocations: set[int]
    observed: dict[int, list[RegisterObservation]]
    aborted: bool = False
    overflow: bool = False
    staged_blocks: int = 0
    staged_words: int = 0


_SNAPSHOT_REFRESH_CONTEXT: ContextVar[tuple[int, int, int] | None] = ContextVar(
    "eg4_snapshot_refresh", default=None
)
_SNAPSHOT_READ_CONTEXT: ContextVar[int | None] = ContextVar(
    "eg4_snapshot_read", default=None
)


class _EndpointBusOwner:
    """Own every raw transport and operation for one physical endpoint."""

    def __init__(
        self,
        *,
        identity: int,
        terminal_callback: Callable[[], None],
    ) -> None:
        self._identity = identity
        self._terminal_callback = terminal_callback
        self._state = _OwnerState.OPEN
        self._gate = _TaskReentrantGate()
        self._records: dict[int, _CapabilityRecord] = {}
        self._next_token = 0
        self._wire_tasks: dict[asyncio.Task[Any], int] = {}
        self._epoch = uuid4()
        self._snapshot_states: dict[int, _UnitSnapshotState] = {}

    def add(
        self,
        raw: _RawLocalTransport,
        *,
        snapshot_enabled: bool,
        poll_interval_seconds: float,
        unit: int,
    ) -> EndpointBusCapability:
        """Retain a raw transport and issue its only public capability."""
        if self._state is not _OwnerState.OPEN:
            raise EndpointOwnerClosingError("Endpoint owner is closing")
        self._next_token += 1
        token = self._next_token
        snapshot_state = None
        if snapshot_enabled:
            snapshot_state = self._snapshot_states.get(unit)
            if snapshot_state is None:
                snapshot_state = _UnitSnapshotState(
                    LatestCompleteRawSnapshotStore(
                        freshness_policy=FreshnessPolicy.from_poll_interval(
                            poll_interval_seconds
                        )
                    )
                )
                self._snapshot_states[unit] = snapshot_state
        self._records[token] = _CapabilityRecord(
            raw,
            snapshot_state=snapshot_state,
            snapshot_observer_capable=snapshot_enabled,
            snapshot_enabled=snapshot_enabled,
            unit=unit,
        )
        return EndpointBusCapability(self, token, raw.serial)

    def observe(
        self, token: int, observations: tuple[RegisterObservation, ...]
    ) -> None:
        """Stage one released observer callback for its exact public read."""
        record = self._records.get(token)
        context = _SNAPSHOT_REFRESH_CONTEXT.get()
        invocation = _SNAPSHOT_READ_CONTEXT.get()
        if (
            record is None
            or record.active_attempt is None
            or context != (id(self), token, record.active_attempt.identity)
            or invocation is None
            or invocation not in record.active_attempt.expected_invocations
        ):
            return
        block_count = sum(len(observation.segments) for observation in observations)
        word_count = sum(
            len(segment.words)
            for observation in observations
            for segment in observation.segments
        )
        if (
            record.active_attempt.staged_blocks + block_count
            > MAX_SNAPSHOT_STAGED_BLOCKS
            or record.active_attempt.staged_words + word_count
            > MAX_SNAPSHOT_STAGED_WORDS
        ):
            record.active_attempt.overflow = True
            record.active_attempt.observed.clear()
            record.active_attempt.staged_blocks = 0
            record.active_attempt.staged_words = 0
            return
        record.active_attempt.staged_blocks += block_count
        record.active_attempt.staged_words += word_count
        record.active_attempt.observed.setdefault(invocation, []).extend(observations)

    @asynccontextmanager
    async def snapshot_refresh(self, token: int) -> AsyncIterator[None]:
        """Bracket one coordinator refresh and publish only its complete reads."""
        record = self._open_record(token)
        if not record.snapshot_enabled or record.snapshot_state is None:
            yield
            return
        if record.active_attempt is not None:
            raise RuntimeError("A snapshot refresh is already active")
        record.snapshot_state.poll_cycle += 1
        attempt = _SnapshotAttempt(
            identity=record.snapshot_state.poll_cycle,
            started=time.monotonic(),
            observer_errors_before=int(
                getattr(record.raw, "register_observation_error_count", 0)
            ),
            expected_invocations=set(),
            observed={},
        )
        record.active_attempt = attempt
        context_token = _SNAPSHOT_REFRESH_CONTEXT.set(
            (id(self), token, attempt.identity)
        )
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            _SNAPSHOT_REFRESH_CONTEXT.reset(context_token)
            self._finish_snapshot_refresh(record, attempt, succeeded=succeeded)

    def _finish_snapshot_refresh(
        self,
        record: _CapabilityRecord,
        attempt: _SnapshotAttempt,
        *,
        succeeded: bool,
    ) -> None:
        if record.active_attempt is not attempt:
            return
        record.active_attempt = None
        state = record.snapshot_state
        if state is None or not record.snapshot_enabled:
            return
        store = state.store
        observer_errors_after = int(
            getattr(record.raw, "register_observation_error_count", 0)
        )
        observer_error = observer_errors_after != attempt.observer_errors_before
        complete = (
            succeeded
            and bool(attempt.expected_invocations)
            and set(attempt.observed) == attempt.expected_invocations
            and all(attempt.observed.values())
            and not observer_error
            and not attempt.aborted
            and not attempt.overflow
        )
        if not complete:
            store.suppress_incomplete(observer_error=observer_error)
            return

        ended = time.monotonic()
        state.generation += 1
        family = getattr(record.raw, "inverter_family", None)
        family_scope = getattr(family, "value", family)
        crc_state = (
            CrcValidationState.VALID
            if record.raw.transport_type == TransportType.MODBUS_SERIAL.value
            else CrcValidationState.NOT_APPLICABLE
        )
        blocks = tuple(
            RawRegisterBlock(
                endpoint_key=f"owner-{self._identity}",
                unit=record.unit,
                family_scope=str(family_scope) if family_scope is not None else None,
                firmware_scope=record.firmware_scope,
                register_space=observation.register_space,
                start_address=segment.start_address,
                count=len(segment.words),
                words=segment.words,
                owner_epoch=self._epoch,
                generation=state.generation,
                poll_cycle=state.poll_cycle,
                acquired_monotonic_start=attempt.started,
                acquired_monotonic_end=ended,
                validation_state=SnapshotValidationState.VALID,
                crc_state=crc_state,
            )
            for invocation in sorted(attempt.expected_invocations)
            for observation in attempt.observed[invocation]
            for segment in observation.segments
        )
        if not blocks:
            store.suppress_incomplete()
            return
        store.publish(
            RawSnapshotFrame(
                owner_epoch=self._epoch,
                generation=state.generation,
                poll_cycle=state.poll_cycle,
                acquired_monotonic_start=attempt.started,
                acquired_monotonic_end=ended,
                blocks=blocks,
            )
        )

    def latest_complete(self, token: int) -> RawSnapshotFrame | None:
        record = self._open_record(token)
        if not record.snapshot_enabled or record.snapshot_state is None:
            return None
        return record.snapshot_state.store.latest_complete

    def snapshot_health(self, token: int) -> SnapshotHealth:
        record = self._open_record(token)
        if record.snapshot_state is None:
            return SnapshotHealth(0, 0)
        return record.snapshot_state.store.health

    def snapshot_freshness_policy(self, token: int) -> FreshnessPolicy:
        record = self._open_record(token)
        if record.snapshot_state is None:
            return FreshnessPolicy.from_poll_interval(5.0)
        return record.snapshot_state.store.freshness_policy

    def latest_fresh(
        self, token: int, *, monotonic_now: float | None = None
    ) -> RawSnapshotFrame | None:
        record = self._open_record(token)
        if not record.snapshot_enabled or record.snapshot_state is None:
            return None
        return record.snapshot_state.store.latest_fresh(monotonic_now=monotonic_now)

    def snapshot_metrics(
        self, token: int, *, monotonic_now: float | None = None
    ) -> SnapshotMetrics:
        record = self._open_record(token)
        if record.snapshot_state is None:
            return SnapshotMetrics(None, False, 0, 0)
        return record.snapshot_state.store.metrics(monotonic_now=monotonic_now)

    def abort_snapshot_refresh(self, token: int) -> None:
        record = self._records.get(token)
        if record is not None and record.active_attempt is not None:
            record.active_attempt.aborted = True

    def set_snapshot_coverage(self, token: int, *, enabled: bool) -> None:
        record = self._records.get(token)
        if record is None or record.closing:
            return
        record.snapshot_enabled = enabled and record.snapshot_observer_capable
        if not record.snapshot_enabled and record.snapshot_state is not None:
            if record.active_attempt is not None:
                record.snapshot_state.store.suppress_incomplete()
                record.active_attempt = None
            record.snapshot_state.store.clear()

    def status(self) -> EndpointBusStatus:
        """Return bounded status without endpoint or identity material."""
        return EndpointBusStatus(
            owner_identity=self._identity,
            state=self._state.value,
            capability_count=len(self._records),
            in_flight=len(self._wire_tasks),
        )

    def get_property(self, token: int, name: str) -> Any:
        """Read an explicitly admitted raw property within the owner."""
        return getattr(self._open_record(token).raw, name)

    def set_property(self, token: int, name: str, value: Any) -> None:
        """Set an explicitly admitted raw configuration property."""
        setattr(self._open_record(token).raw, name, value)

    def _open_record(self, token: int) -> _CapabilityRecord:
        record = self._records.get(token)
        if record is None or record.closing:
            raise EndpointCapabilityClosedError("Endpoint capability is closed")
        if self._state is not _OwnerState.OPEN:
            raise EndpointOwnerClosingError("Endpoint owner is closing")
        return record

    async def invoke(
        self,
        token: int,
        method: str,
        *args: Any,
    ) -> Any:
        """Serialize one operation and detach post-wire cancellation."""
        self._open_record(token)
        await self._gate.acquire()
        try:
            record = self._open_record(token)
            operation = cast(
                Callable[..., Coroutine[Any, Any, Any]], getattr(record.raw, method)
            )
            read_context_token: Token[int | None] | None = None
            refresh_context = _SNAPSHOT_REFRESH_CONTEXT.get()
            attempt = record.active_attempt
            if (
                method.startswith("read_")
                and attempt is not None
                and refresh_context == (id(self), token, attempt.identity)
            ):
                if len(attempt.expected_invocations) >= MAX_SNAPSHOT_STAGED_INVOCATIONS:
                    attempt.overflow = True
                else:
                    invocation = len(attempt.expected_invocations) + 1
                    attempt.expected_invocations.add(invocation)
                    read_context_token = _SNAPSHOT_READ_CONTEXT.set(invocation)
            try:
                wire_task = asyncio.create_task(operation(*args))
            finally:
                if read_context_token is not None:
                    _SNAPSHOT_READ_CONTEXT.reset(read_context_token)
            self._wire_tasks[wire_task] = token
            wire_task.add_done_callback(self._wire_tasks.pop)
            self._gate.hold_for_wire_task(wire_task)
            result = await asyncio.shield(wire_task)
            if method == "read_firmware_version":
                record.firmware_scope = str(result) if result else None
            return result
        finally:
            self._gate.release()

    @asynccontextmanager
    async def transaction(self, token: int) -> AsyncIterator[None]:
        """Keep nested capability operations in one indivisible transaction."""
        self._open_record(token)
        await self._gate.acquire()
        try:
            self._open_record(token)
            yield
        finally:
            self._gate.release()

    def begin_shutdown(self, token: int) -> None:
        """Synchronously close admission for one capability."""
        record = self._records.get(token)
        if record is None:
            return
        if not record.closing:
            record.closing = True
            if all(candidate.closing for candidate in self._records.values()):
                self._state = _OwnerState.CLOSING

    async def shutdown(self, token: int) -> None:
        """Interrupt and terminally close one capability."""
        self.begin_shutdown(token)
        record = self._records.get(token)
        if record is None:
            return
        wire_tasks = tuple(
            task for task, task_token in self._wire_tasks.items() if task_token == token
        )
        interrupting = bool(wire_tasks) and self._gate.hold_if_locked()
        acquired = False
        terminal_succeeded = False
        try:
            if not interrupting:
                await self._gate.acquire(deadline=False)
                acquired = True
            terminal_shutdown = getattr(type(record.raw), "async_shutdown", None)
            if callable(terminal_shutdown):
                await terminal_shutdown(record.raw)
            else:
                await record.raw.disconnect()
            terminal_succeeded = True
        finally:
            for task in wire_tasks:
                task.cancel()
            if wire_tasks:
                await asyncio.gather(*wire_tasks, return_exceptions=True)
            if acquired:
                self._gate.release()
            if interrupting:
                self._gate.release_hold()
            if terminal_succeeded:
                state = record.snapshot_state
                record.active_attempt = None
                self._records.pop(token, None)
                if state is not None and not any(
                    candidate.snapshot_state is state
                    for candidate in self._records.values()
                ):
                    state.store.clear()
                    self._snapshot_states.pop(record.unit, None)
                if not self._records:
                    self._state = _OwnerState.CLOSED
                    self._terminal_callback()
                else:
                    self._state = (
                        _OwnerState.CLOSING
                        if any(
                            candidate.closing for candidate in self._records.values()
                        )
                        else _OwnerState.OPEN
                    )
            else:
                self._state = _OwnerState.CLOSING

    async def wait_idle(self) -> None:
        """Wait for detached wire tasks without cancelling them."""
        while self._wire_tasks:
            tasks = tuple(self._wire_tasks)
            await asyncio.gather(
                *(asyncio.shield(task) for task in tasks),
                return_exceptions=True,
            )
            await asyncio.sleep(0)

    @property
    def active_task_count(self) -> int:
        return len(self._wire_tasks)


class EndpointBusCapability:
    """Explicit local-only capability implementing pylxpweb's terminal protocol."""

    provenance = LocalBusProvenance.LOCAL_BUS

    def __init__(
        self,
        owner: _EndpointBusOwner,
        token: int,
        serial: str,
    ) -> None:
        self._owner = owner
        self._token = token
        self._serial = serial
        self._shutdown_task: asyncio.Task[None] | None = None

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def status(self) -> EndpointBusStatus:
        return self._owner.status()

    @property
    def latest_complete_snapshot(self) -> RawSnapshotFrame | None:
        """Return only the externally readable latest-complete frame."""
        return self._owner.latest_complete(self._token)

    @property
    def snapshot_health(self) -> SnapshotHealth:
        """Return bounded redacted snapshot health."""
        return self._owner.snapshot_health(self._token)

    @property
    def snapshot_freshness_policy(self) -> FreshnessPolicy:
        """Return the named freshness policy without endpoint identity."""
        return self._owner.snapshot_freshness_policy(self._token)

    def latest_fresh_snapshot(
        self, *, monotonic_now: float | None = None
    ) -> RawSnapshotFrame | None:
        """Return the complete frame only while the named policy is fresh."""
        return self._owner.latest_fresh(self._token, monotonic_now=monotonic_now)

    def snapshot_metrics(
        self, *, monotonic_now: float | None = None
    ) -> SnapshotMetrics:
        """Return identity-free freshness and bounded health metrics."""
        return self._owner.snapshot_metrics(self._token, monotonic_now=monotonic_now)

    def complete_snapshot_refresh(self) -> Any:
        """Return the owner lifecycle context for one complete refresh."""
        return self._owner.snapshot_refresh(self._token)

    def abort_snapshot_refresh(self) -> None:
        """Mark the active coordinator lifecycle unsuccessful."""
        self._owner.abort_snapshot_refresh(self._token)

    @property
    def is_connected(self) -> bool:
        return bool(self._owner.get_property(self._token, "is_connected"))

    @property
    def capabilities(self) -> TransportCapabilities:
        return cast(
            TransportCapabilities,
            self._owner.get_property(self._token, "capabilities"),
        )

    @property
    def transport_type(self) -> str:
        return str(self._owner.get_property(self._token, "transport_type"))

    @property
    def inverter_family(self) -> Any:
        return self._owner.get_property(self._token, "inverter_family")

    @property
    def split_phase(self) -> bool:
        return bool(self._owner.get_property(self._token, "split_phase"))

    @split_phase.setter
    def split_phase(self, value: bool) -> None:
        self._owner.set_property(self._token, "split_phase", value)

    @property
    def pv_string_count(self) -> int:
        return int(self._owner.get_property(self._token, "pv_string_count"))

    @property
    def is_midbox_device(self) -> bool:
        return bool(self._owner.get_property(self._token, "is_midbox_device"))

    def transaction(self) -> Any:
        """Return an async context for an indivisible nested operation."""
        return self._owner.transaction(self._token)

    async def connect(self) -> None:
        await self._owner.invoke(self._token, "connect")

    async def async_ensure_connected(self) -> None:
        """Schedule a reconnect only when the owned transport needs it."""
        if not self.is_connected:
            await self.connect()

    async def disconnect(self) -> None:
        await self._owner.invoke(self._token, "disconnect")

    async def async_shutdown(self) -> None:
        if self._shutdown_task is None:
            self._owner.begin_shutdown(self._token)
            self._shutdown_task = asyncio.create_task(self._owner.shutdown(self._token))
        cancellation = await _await_settled(self._shutdown_task)
        failure: BaseException | None = None
        try:
            self._shutdown_task.result()
        except BaseException as error:
            failure = error
            self._shutdown_task = None
        if cancellation is not None and failure is not None:
            raise BaseExceptionGroup(
                "Endpoint shutdown failed after caller cancellation",
                [cancellation, failure],
            )
        if failure is not None:
            raise failure
        if cancellation is not None:
            raise cancellation

    async def read_runtime(self) -> Any:
        return await self._owner.invoke(self._token, "read_runtime")

    async def read_energy(self) -> Any:
        return await self._owner.invoke(self._token, "read_energy")

    async def read_battery(self) -> Any:
        return await self._owner.invoke(self._token, "read_battery")

    async def read_parameters(self, start: int, count: int) -> dict[int, int]:
        return cast(
            dict[int, int],
            await self._owner.invoke(self._token, "read_parameters", start, count),
        )

    async def write_parameters(self, parameters: dict[int, int]) -> bool:
        return bool(
            await self._owner.invoke(self._token, "write_parameters", parameters)
        )

    async def read_named_parameters(self, start: int, count: int) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._owner.invoke(
                self._token, "read_named_parameters", start, count
            ),
        )

    async def write_named_parameters(self, parameters: dict[str, Any]) -> bool:
        return bool(
            await self._owner.invoke(self._token, "write_named_parameters", parameters)
        )

    async def read_device_type(self) -> int:
        return int(await self._owner.invoke(self._token, "read_device_type"))

    async def read_firmware_version(self) -> str:
        return str(await self._owner.invoke(self._token, "read_firmware_version"))

    async def read_parallel_config(self) -> int:
        return int(await self._owner.invoke(self._token, "read_parallel_config"))

    async def read_serial_number(self) -> str:
        return str(await self._owner.invoke(self._token, "read_serial_number"))

    async def read_midbox_runtime(self) -> Any:
        return await self._owner.invoke(self._token, "read_midbox_runtime")


class EndpointBusRegistry:
    """HA-scoped registry enforcing one owner per normalized endpoint."""

    def __init__(
        self,
        *,
        raw_transport_factory: RawTransportFactory = _default_raw_transport_factory,
    ) -> None:
        self._raw_transport_factory = raw_transport_factory
        self._owners: dict[_PhysicalEndpointKey, _EndpointBusOwner] = {}
        self._failed_shutdown_capabilities: set[EndpointBusCapability] = set()
        self._next_identity = 0

    def create_capability(
        self,
        config: TransportConfig,
        *,
        snapshot_enabled: bool = False,
        poll_interval_seconds: float = 5.0,
    ) -> EndpointBusCapability:
        """Create and retain raw transport behind the endpoint capability."""
        key = _endpoint_key(config)
        owner = self._owners.get(key)
        created_owner = owner is None
        if owner is not None and owner.status().state != _OwnerState.OPEN.value:
            raise EndpointOwnerClosingError("Endpoint owner is closing")
        if owner is None:
            self._next_identity += 1

            def terminal_callback() -> None:
                current = self._owners.get(key)
                if current is owner:
                    self._owners.pop(key, None)

            owner = _EndpointBusOwner(
                identity=self._next_identity,
                terminal_callback=terminal_callback,
            )
            self._owners[key] = owner
        snapshot_enabled = snapshot_enabled and config.transport_type in {
            TransportType.MODBUS_TCP,
            TransportType.MODBUS_SERIAL,
        }
        token_ref = [0]

        def observer(observations: tuple[RegisterObservation, ...]) -> None:
            owner.observe(token_ref[0], observations)

        try:
            raw = _construct_raw_transport(
                self._raw_transport_factory,
                config,
                observer if snapshot_enabled else None,
            )
        except Exception:
            if created_owner and self._owners.get(key) is owner:
                self._owners.pop(key, None)
            raise
        capability = owner.add(
            raw,
            snapshot_enabled=snapshot_enabled,
            poll_interval_seconds=poll_interval_seconds,
            unit=config.unit_id,
        )
        token_ref[0] = capability._token
        return capability

    def create_discovery_capability(
        self, config: TransportConfig
    ) -> EndpointBusCapability:
        """Create an exclusive short-lived capability for config-flow discovery."""
        if _endpoint_key(config) in self._owners:
            raise EndpointOwnerInUseError("Endpoint is already owned")
        return self.create_capability(config)

    def validate_capability(
        self,
        candidate: object,
        *,
        serial: str | None = None,
        expected_config: TransportConfig | None = None,
    ) -> EndpointBusCapability | None:
        """Return a live local-bus capability owned by this registry."""
        if (
            not isinstance(candidate, EndpointBusCapability)
            or candidate.provenance is not LocalBusProvenance.LOCAL_BUS
            or (serial is not None and candidate.serial != serial)
            or expected_config is None
        ):
            return None
        if self._owners.get(_endpoint_key(expected_config)) is not candidate._owner:
            return None
        try:
            candidate._owner._open_record(candidate._token)
        except (EndpointCapabilityClosedError, EndpointOwnerClosingError):
            return None
        return candidate

    def is_retained_capability(self, candidate: object) -> bool:
        """Return whether this registry still retains the capability record."""
        return (
            isinstance(candidate, EndpointBusCapability)
            and candidate._owner in self._owners.values()
            and candidate._token in candidate._owner._records
        )

    async def async_shutdown_capabilities(
        self, capabilities: Collection[EndpointBusCapability]
    ) -> None:
        """Mark a capability set closing before awaiting terminal shutdown."""
        closing = tuple(capabilities)
        self.begin_shutdown_capabilities(closing)
        batch = asyncio.gather(
            *(capability.async_shutdown() for capability in closing),
            return_exceptions=True,
        )
        cancellation = await _await_settled(batch)
        failures: list[BaseException] = []
        for capability, result in zip(closing, batch.result(), strict=True):
            if isinstance(result, BaseException):
                self._failed_shutdown_capabilities.add(capability)
                failures.append(result)
            else:
                self._failed_shutdown_capabilities.discard(capability)
        if cancellation is not None:
            failures.insert(0, cancellation)
        if failures:
            raise BaseExceptionGroup("Endpoint shutdown failures", failures)

    async def async_retry_failed_shutdowns(
        self, configs: Collection[TransportConfig]
    ) -> None:
        """Retry retained terminal closures for the requested endpoints."""
        owners = {
            owner
            for config in configs
            if (owner := self._owners.get(_endpoint_key(config))) is not None
        }
        await self.async_shutdown_capabilities(
            tuple(
                capability
                for capability in self._failed_shutdown_capabilities
                if capability._owner in owners
            )
        )

    def begin_shutdown_capabilities(
        self, capabilities: Collection[EndpointBusCapability]
    ) -> None:
        """Close admission for a capability set without yielding."""
        for capability in capabilities:
            capability._owner.begin_shutdown(capability._token)

    def set_snapshot_coverage(
        self,
        capabilities: Collection[EndpointBusCapability],
        *,
        enabled: bool,
    ) -> None:
        """Atomically remove lookup/data before direct coverage is lost."""
        for capability in capabilities:
            capability._owner.set_snapshot_coverage(capability._token, enabled=enabled)

    async def async_wait_idle(self) -> None:
        await asyncio.gather(*(owner.wait_idle() for owner in self._owners.values()))

    @property
    def owner_count(self) -> int:
        return len(self._owners)

    @property
    def tombstone_count(self) -> int:
        return sum(
            owner.status().state == _OwnerState.CLOSING.value
            for owner in self._owners.values()
        )

    @property
    def active_task_count(self) -> int:
        return sum(owner.active_task_count for owner in self._owners.values())

    @property
    def snapshot_store_count(self) -> int:
        """Return a redacted retained-resource count for teardown health."""
        return sum(len(owner._snapshot_states) for owner in self._owners.values())


def get_endpoint_bus_registry(hass: Any) -> EndpointBusRegistry:
    """Return the single Home Assistant-scoped endpoint owner registry."""
    registry = hass.data.get(ENDPOINT_BUS_REGISTRY_DATA)
    if registry is None:
        registry = EndpointBusRegistry()
        hass.data[ENDPOINT_BUS_REGISTRY_DATA] = registry
    if not isinstance(registry, EndpointBusRegistry):
        raise RuntimeError("Endpoint bus registry has an unexpected type")
    return registry
