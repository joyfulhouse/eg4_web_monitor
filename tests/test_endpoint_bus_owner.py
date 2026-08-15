"""Endpoint-scoped local bus ownership contracts for Phase A2 (#581)."""

from __future__ import annotations

import ast
import asyncio
from builtins import BaseExceptionGroup, ExceptionGroup
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_protocol_members
from unittest.mock import AsyncMock, patch

import pytest
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.transports import TerminalInverterTransport
from pylxpweb.transports.capabilities import TransportCapabilities
from pylxpweb.transports.config import TransportConfig, TransportType

from custom_components.eg4_web_monitor.bus_eligibility import (
    BusEligibilityReason,
    LocalBusProvenance,
    evaluate_bus_owner_eligibility,
)
from custom_components.eg4_web_monitor import endpoint_bus
from custom_components.eg4_web_monitor._config_flow.discovery import (
    discover_modbus_device,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.endpoint_bus import (
    EndpointBusCapability,
    EndpointBusRegistry,
    EndpointOwnerClosingError,
)


class _WireProbe:
    """Deterministic endpoint-wide concurrency and operation recorder."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.operations: list[tuple[str, tuple[Any, ...]]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.cancelled = 0

    async def run(self, name: str, *args: Any) -> Any:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.operations.append((name, args))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.in_flight -= 1
        if name.startswith("write"):
            return True
        if name == "read_parameters":
            start, count = args
            return {address: 0 for address in range(start, start + count)}
        if name == "read_named_parameters":
            return {}
        if name in {"read_device_type", "read_parallel_config"}:
            return 0
        if name in {"read_firmware_version", "read_serial_number"}:
            return "SYNTHETIC"
        return object()


class _FakeRawTransport:
    """Shape-faithful raw transport visible only to the injected owner factory."""

    def __init__(self, config: TransportConfig, probe: _WireProbe) -> None:
        self.serial = config.serial
        self.host = config.host
        self.port = config.port
        self.transport_type = config.transport_type.value
        self.inverter_family = config.inverter_family
        self.split_phase = False
        self.pv_string_count = 3
        self.is_midbox_device = False
        self.is_connected = False
        self.capabilities = TransportCapabilities()
        self._probe = probe

    async def connect(self) -> None:
        await self._probe.run("connect")
        self.is_connected = True

    async def async_ensure_connected(self) -> None:
        if not self.is_connected:
            await self.connect()

    async def disconnect(self) -> None:
        await self._probe.run("disconnect")
        self.is_connected = False

    async def read_runtime(self) -> Any:
        return await self._probe.run("read_runtime")

    async def read_energy(self) -> Any:
        return await self._probe.run("read_energy")

    async def read_battery(self) -> Any:
        return await self._probe.run("read_battery")

    async def read_parameters(self, start: int, count: int) -> dict[int, int]:
        return await self._probe.run("read_parameters", start, count)

    async def write_parameters(self, parameters: dict[int, int]) -> bool:
        return await self._probe.run("write_parameters", tuple(parameters.items()))

    async def read_named_parameters(self, start: int, count: int) -> dict[str, Any]:
        return await self._probe.run("read_named_parameters", start, count)

    async def write_named_parameters(self, parameters: dict[str, Any]) -> bool:
        return await self._probe.run(
            "write_named_parameters", tuple(parameters.items())
        )

    async def read_device_type(self) -> int:
        return await self._probe.run("read_device_type")

    async def read_firmware_version(self) -> str:
        return await self._probe.run("read_firmware_version")

    async def read_parallel_config(self) -> int:
        return await self._probe.run("read_parallel_config")

    async def read_serial_number(self) -> str:
        return await self._probe.run("read_serial_number")

    async def read_midbox_runtime(self) -> Any:
        return await self._probe.run("read_midbox_runtime")


class _TerminalFakeRawTransport(_FakeRawTransport):
    def __init__(self, config: TransportConfig, probe: _WireProbe) -> None:
        super().__init__(config, probe)
        self.shutdown_calls = 0
        self.shutdown_release = asyncio.Event()
        self.shutdown_release.set()

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1
        await self.shutdown_release.wait()
        self.is_connected = False


class _InstrumentedTerminalFakeRawTransport(_FakeRawTransport):
    async def async_shutdown(self) -> None:
        await self._probe.run("async_shutdown")


def _config(
    serial: str,
    *,
    host: str = "gateway.example.invalid",
    port: int = 1502,
    transport_type: TransportType = TransportType.MODBUS_TCP,
) -> TransportConfig:
    return TransportConfig(
        host=host,
        port=port,
        serial=serial,
        transport_type=transport_type,
        serial_port="loop://synthetic"
        if transport_type is TransportType.MODBUS_SERIAL
        else None,
    )


def _registry(probes: dict[str, _WireProbe]) -> EndpointBusRegistry:
    def factory(config: TransportConfig) -> _FakeRawTransport:
        key = (
            config.host
            if config.transport_type is not TransportType.MODBUS_SERIAL
            else config.serial_port
        )
        return _FakeRawTransport(config, probes[str(key)])

    return EndpointBusRegistry(raw_transport_factory=factory)


def _poll_coordinator(transport: Any) -> tuple[Any, Any]:
    inverter = SimpleNamespace(
        transport_runtime=SimpleNamespace(
            pv_total_power=0,
            battery_soc=0,
            rectifier_power=0,
        )
    )

    async def refresh(*, include_parameters: bool) -> None:
        await transport.read_parameters(0, 2)
        await transport.read_parameters(20, 1)
        await transport.read_parameters(40, 3)

    inverter.refresh = refresh
    coordinator = SimpleNamespace(
        _inverter_cache={},
        _align_inverter_cache_ttls=lambda *args: None,
        _local_parameters_loaded=True,
        _firmware_cache={},
        _build_local_device_data=lambda **kwargs: {},
        _read_modbus_parameters=AsyncMock(return_value=({}, True)),
        _parameter_write_generation=0,
        _reconcile_parameter_read=lambda serial, data, **kwargs: data,
        data={},
        _last_available_state=True,
    )
    return coordinator, inverter


@pytest.mark.asyncio
async def test_serializes_shared_endpoint_and_allows_independent_endpoints() -> None:
    shared = _WireProbe()
    independent = _WireProbe()
    registry = _registry(
        {"gateway.example.invalid": shared, "other.example.invalid": independent}
    )
    first = registry.create_capability(_config("SYNTH00001"))
    second = registry.create_capability(_config("SYNTH00002"))
    other = registry.create_capability(
        _config("SYNTH00003", host="other.example.invalid")
    )

    shared.release.clear()
    independent.release.clear()
    poll = asyncio.create_task(first.read_runtime())
    await shared.started.wait()
    control = asyncio.create_task(second.write_parameters({1: 2}))
    reconnect = asyncio.create_task(second.connect())
    overlap = asyncio.create_task(other.read_energy())
    await independent.started.wait()
    await asyncio.sleep(0)

    assert shared.in_flight == 1
    assert independent.in_flight == 1
    shared.release.set()
    independent.release.set()
    await asyncio.gather(poll, control, reconnect, overlap)
    assert shared.max_in_flight == 1
    assert independent.max_in_flight == 1
    assert registry.owner_count == 2


@pytest.mark.asyncio
async def test_coordinator_poll_control_reconnect_across_entries_and_endpoints() -> (
    None
):
    shared = _WireProbe()
    independent = _WireProbe()
    registry = _registry(
        {"gateway.example.invalid": shared, "other.example.invalid": independent}
    )
    poll_capability = registry.create_capability(_config("SYNTH00001"))
    control_capability = registry.create_capability(_config("SYNTH00002"))
    independent_capability = registry.create_capability(
        _config("SYNTH00003", host="other.example.invalid")
    )
    poll_coordinator, poll_inverter = _poll_coordinator(poll_capability)
    other_coordinator, other_inverter = _poll_coordinator(independent_capability)
    control_coordinator = SimpleNamespace(
        get_local_transport=lambda serial: control_capability
    )

    shared.release.clear()
    independent.release.clear()

    async def write_control() -> bool:
        return await EG4DataUpdateCoordinator._write_with_local_transport(
            control_coordinator,
            serial="SYNTH00002",
            no_transport_message="missing",
            reconnect_message="reconnect %s %s",
            reconnect_args=("SYNTH00002", "control"),
            write=lambda transport: transport.write_parameters({1: 2}),
            success_message="success %s",
            success_args=("control",),
            failure_message="failure %s: %s",
            failure_args=("control",),
            translated_error=str,
        )

    retry_submitted = asyncio.Event()

    async def cancel_then_retry_control() -> bool:
        try:
            return await write_control()
        except asyncio.CancelledError:
            retry_submitted.set()
            return await write_control()

    with patch.object(
        BaseInverter,
        "from_modbus_transport",
        side_effect=[poll_inverter, other_inverter],
    ):
        control = asyncio.create_task(cancel_then_retry_control())
        await shared.started.wait()
        control.cancel()
        await retry_submitted.wait()
        poll = asyncio.create_task(
            EG4DataUpdateCoordinator._async_update_local_transport_data(
                poll_coordinator,
                transport=poll_capability,
                serial="SYNTH00001",
                model="synthetic",
                connection_type="modbus",
            )
        )
        independent_poll = asyncio.create_task(
            EG4DataUpdateCoordinator._async_update_local_transport_data(
                other_coordinator,
                transport=independent_capability,
                serial="SYNTH00003",
                model="synthetic",
                connection_type="modbus",
            )
        )
        await independent.started.wait()
        await asyncio.sleep(0)
        shared_overlap = shared.in_flight
        independent_overlap = independent.in_flight
        shared.release.set()
        independent.release.set()
        await asyncio.gather(poll, control, independent_poll)

    assert shared_overlap == 1
    assert independent_overlap == 1
    assert shared.max_in_flight == 1
    assert independent.max_in_flight == 1


@pytest.mark.asyncio
async def test_task_reentrant_transaction_keeps_schedule_atomic() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    schedule = registry.create_capability(_config("SYNTH00001"))
    poller = registry.create_capability(_config("SYNTH00002"))

    async def write_schedule() -> None:
        async with schedule.transaction():
            await schedule.write_parameters({10: 20})
            await asyncio.sleep(0)
            await schedule.write_parameters({11: 21})

    await asyncio.gather(write_schedule(), poller.read_runtime())
    assert probe.operations[:2] == [
        ("write_parameters", (((10, 20),),)),
        ("write_parameters", (((11, 21),),)),
    ]
    assert probe.max_in_flight == 1


@pytest.mark.asyncio
async def test_pre_wire_cancellation_removes_waiting_operation() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    holder = registry.create_capability(_config("SYNTH00001"))
    waiter = registry.create_capability(_config("SYNTH00002"))
    probe.release.clear()
    active = asyncio.create_task(holder.read_runtime())
    await probe.started.wait()
    queued = asyncio.create_task(waiter.write_parameters({1: 2}))
    await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    probe.release.set()
    await active

    assert [name for name, _ in probe.operations] == ["read_runtime"]


@pytest.mark.asyncio
async def test_post_wire_cancellation_detaches_without_cancel_or_replay() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    probe.release.clear()
    write = asyncio.create_task(capability.write_parameters({1: 2}))
    await probe.started.wait()
    write.cancel()
    with pytest.raises(asyncio.CancelledError):
        await write

    assert probe.in_flight == 1
    assert probe.cancelled == 0
    probe.release.set()
    await registry.async_wait_idle()
    assert probe.operations == [("write_parameters", (((1, 2),),))]
    assert probe.cancelled == 0


@pytest.mark.asyncio
async def test_cancelled_caller_immediate_retry_waits_for_detached_wire() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    retry_submitted = asyncio.Event()

    async def cancel_then_retry() -> Any:
        try:
            await capability.write_parameters({1: 2})
        except asyncio.CancelledError:
            retry_submitted.set()
            return await capability.read_energy()

    probe.release.clear()
    caller = asyncio.create_task(cancel_then_retry())
    await probe.started.wait()
    caller.cancel()
    await retry_submitted.wait()
    await asyncio.sleep(0)

    in_flight_before_release = probe.in_flight
    operations_before_release = [name for name, _ in probe.operations]
    probe.release.set()
    await caller
    assert in_flight_before_release == 1
    assert operations_before_release == ["write_parameters"]
    assert probe.max_in_flight == 1


@pytest.mark.asyncio
async def test_capability_set_enters_closing_before_terminal_shutdown_waits() -> None:
    probe = _WireProbe()
    raw_transports: list[_TerminalFakeRawTransport] = []

    def factory(config: TransportConfig) -> _TerminalFakeRawTransport:
        raw = _TerminalFakeRawTransport(config, probe)
        raw.shutdown_release.clear()
        raw_transports.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    first = registry.create_capability(_config("SYNTH00001"))
    second = registry.create_capability(_config("SYNTH00002"))

    shutdown_capabilities = getattr(registry, "async_shutdown_capabilities", None)
    assert callable(shutdown_capabilities)
    closing = asyncio.create_task(shutdown_capabilities((first, second)))
    await asyncio.sleep(0)

    with pytest.raises(EndpointOwnerClosingError):
        registry.create_capability(_config("SYNTH00003"))
    assert registry.tombstone_count == 1

    for raw in raw_transports:
        raw.shutdown_release.set()
    await closing
    assert registry.owner_count == 0


@pytest.mark.asyncio
async def test_terminal_shutdown_interrupts_nonreturning_wire_operation() -> None:
    probe = _WireProbe()
    raw_transports: list[_TerminalFakeRawTransport] = []

    def factory(config: TransportConfig) -> _TerminalFakeRawTransport:
        raw = _TerminalFakeRawTransport(config, probe)
        raw_transports.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    capability = registry.create_capability(_config("SYNTH00001"))
    probe.release.clear()
    read = asyncio.create_task(capability.read_runtime())
    await probe.started.wait()

    closing = asyncio.create_task(capability.async_shutdown())
    done, _ = await asyncio.wait({closing}, timeout=0.05)
    if not done:
        probe.release.set()
        await closing

    assert done == {closing}
    assert raw_transports[0].shutdown_calls == 1
    with pytest.raises(asyncio.CancelledError):
        await read
    assert registry.owner_count == 0


@pytest.mark.asyncio
async def test_unrelated_terminal_close_waits_for_active_endpoint_wire() -> None:
    probe = _WireProbe()
    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: _InstrumentedTerminalFakeRawTransport(
            config, probe
        )
    )
    active_capability = registry.create_capability(_config("SYNTH00001"))
    closing_capability = registry.create_capability(_config("SYNTH00002"))
    probe.release.clear()
    active = asyncio.create_task(active_capability.read_runtime())
    await probe.started.wait()

    closing = asyncio.create_task(closing_capability.async_shutdown())
    await asyncio.sleep(0)
    operations_before_release = [name for name, _ in probe.operations]
    max_before_release = probe.max_in_flight
    probe.release.set()
    await asyncio.gather(active, closing)
    await active_capability.async_shutdown()

    assert operations_before_release == ["read_runtime"]
    assert max_before_release == 1
    assert probe.max_in_flight == 1


@pytest.mark.asyncio
async def test_batch_terminal_closes_are_endpoint_serialized() -> None:
    probe = _WireProbe()
    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: _InstrumentedTerminalFakeRawTransport(
            config, probe
        )
    )
    first = registry.create_capability(_config("SYNTH00001"))
    second = registry.create_capability(_config("SYNTH00002"))
    probe.release.clear()

    closing = asyncio.create_task(registry.async_shutdown_capabilities((first, second)))
    await probe.started.wait()
    await asyncio.sleep(0)
    operations_before_release = [name for name, _ in probe.operations]
    max_before_release = probe.max_in_flight
    probe.release.set()
    await closing

    assert operations_before_release == ["async_shutdown"]
    assert max_before_release == 1
    assert probe.max_in_flight == 1


@pytest.mark.asyncio
async def test_batch_shutdown_settles_siblings_before_aggregating_failure() -> None:
    probe = _WireProbe()
    delayed_release = asyncio.Event()
    delayed_started = asyncio.Event()
    delayed_finished = False
    failed_attempts = 0

    class OutcomeTransport(_FakeRawTransport):
        async def async_shutdown(self) -> None:
            nonlocal delayed_finished, failed_attempts
            if self.serial == "SYNTH00001" and failed_attempts == 0:
                failed_attempts += 1
                raise RuntimeError("synthetic terminal failure")
            delayed_started.set()
            await delayed_release.wait()
            delayed_finished = True

    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: OutcomeTransport(config, probe)
    )
    failing = registry.create_capability(_config("SYNTH00001"))
    delayed = registry.create_capability(_config("SYNTH00002"))
    closing = asyncio.create_task(
        registry.async_shutdown_capabilities((failing, delayed))
    )
    await delayed_started.wait()
    await asyncio.sleep(0)
    completed_before_release = closing.done()
    delayed_release.set()

    with pytest.raises(ExceptionGroup, match="Endpoint shutdown failures"):
        await closing

    assert completed_before_release is False
    assert delayed_finished is True
    assert registry.owner_count == 1
    assert registry.tombstone_count == 1

    await registry.async_shutdown_capabilities((failing, delayed))

    assert failed_attempts == 1
    assert registry.owner_count == 0
    assert registry.tombstone_count == 0


@pytest.mark.asyncio
async def test_failed_terminal_close_keeps_tombstone_until_retry() -> None:
    probe = _WireProbe()
    attempts = 0

    class FailOnceTransport(_FakeRawTransport):
        async def async_shutdown(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("synthetic terminal failure")

    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: FailOnceTransport(config, probe)
    )
    capability = registry.create_capability(_config("SYNTH00001"))

    with pytest.raises(RuntimeError, match="synthetic terminal failure"):
        await capability.async_shutdown()

    assert registry.owner_count == 1
    assert registry.tombstone_count == 1
    with pytest.raises(EndpointOwnerClosingError):
        registry.create_capability(_config("SYNTH00002"))

    await capability.async_shutdown()

    assert attempts == 2
    assert registry.owner_count == 0
    assert registry.tombstone_count == 0


@pytest.mark.asyncio
async def test_batch_shutdown_preserves_cancellation_and_terminal_failure() -> None:
    probe = _WireProbe()
    terminal_started = asyncio.Event()
    terminal_release = asyncio.Event()

    class DelayedFailureTransport(_FakeRawTransport):
        async def async_shutdown(self) -> None:
            terminal_started.set()
            await terminal_release.wait()
            raise RuntimeError("synthetic terminal failure")

    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: DelayedFailureTransport(config, probe)
    )
    capability = registry.create_capability(_config("SYNTH00001"))
    closing = asyncio.create_task(registry.async_shutdown_capabilities((capability,)))
    await terminal_started.wait()
    closing.cancel()
    terminal_release.set()

    with pytest.raises(BaseExceptionGroup) as raised:
        await closing

    assert [type(error) for error in raised.value.exceptions] == [
        asyncio.CancelledError,
        RuntimeError,
    ]
    assert registry.owner_count == 1
    assert registry.tombstone_count == 1


@pytest.mark.asyncio
async def test_registry_validates_owner_provenance_and_endpoint_identity() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    owned = registry.create_capability(_config("SYNTH00001"))
    wrong_endpoint = registry.create_capability(_config("SYNTH00002"))
    foreign_registry = _registry({"gateway.example.invalid": probe})
    foreign = foreign_registry.create_capability(_config("SYNTH00001"))

    assert registry.validate_capability(owned, serial="SYNTH00001") is owned
    assert registry.validate_capability(wrong_endpoint, serial="SYNTH00001") is None
    assert registry.validate_capability(foreign, serial="SYNTH00001") is None
    owned.provenance = object()
    assert registry.validate_capability(owned, serial="SYNTH00001") is None
    del owned.provenance

    await registry.async_shutdown_capabilities((owned, wrong_endpoint))
    await foreign.async_shutdown()


@pytest.mark.asyncio
async def test_expired_endpoint_waiter_never_reaches_wire_and_slot_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(endpoint_bus, "ENDPOINT_ACQUIRE_TIMEOUT_SECONDS", 0.01)
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    active_capability = registry.create_capability(_config("SYNTH00001"))
    waiting_capability = registry.create_capability(_config("SYNTH00002"))
    probe.release.clear()
    active = asyncio.create_task(active_capability.read_runtime())
    await probe.started.wait()

    with pytest.raises(endpoint_bus.EndpointAdmissionError):
        await asyncio.wait_for(waiting_capability.read_energy(), timeout=0.1)

    probe.release.set()
    await active
    await waiting_capability.read_battery()

    assert [name for name, _ in probe.operations] == [
        "read_runtime",
        "read_battery",
    ]


@pytest.mark.asyncio
async def test_endpoint_admission_fails_fast_after_bounded_waiters() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    probe.release.clear()
    active = asyncio.create_task(capability.read_runtime())
    await probe.started.wait()
    waiters = [
        asyncio.create_task(capability.read_energy())
        for _ in range(endpoint_bus.MAX_ENDPOINT_WAITERS)
    ]
    await asyncio.sleep(0)

    with pytest.raises(endpoint_bus.EndpointAdmissionError):
        await capability.read_battery()

    for waiter in waiters:
        waiter.cancel()
    await asyncio.gather(*waiters, return_exceptions=True)
    probe.release.set()
    await active


def test_discovery_cannot_open_second_capability_on_live_endpoint() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    registry.create_capability(_config("SYNTH00001"))

    with pytest.raises(endpoint_bus.EndpointOwnerInUseError):
        registry.create_discovery_capability(_config("SYNTH00002"))


@pytest.mark.asyncio
async def test_coordinator_unload_marks_all_capabilities_before_immediate_reload() -> (
    None
):
    probe = _WireProbe()
    raw_transports: list[_TerminalFakeRawTransport] = []

    def factory(config: TransportConfig) -> _TerminalFakeRawTransport:
        raw = _TerminalFakeRawTransport(config, probe)
        raw.shutdown_release.clear()
        raw_transports.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    first = registry.create_capability(_config("SYNTH00001"))
    second = registry.create_capability(_config("SYNTH00002"))

    class DetachingDevice:
        async def detach_local_transport(self) -> None:
            await detach_release.wait()

    detach_release = asyncio.Event()
    coordinator = SimpleNamespace(
        _inverter_cache={},
        _mid_device_cache={},
        station=SimpleNamespace(all_inverters=[DetachingDevice()], all_mid_devices=[]),
        _bus_capabilities={first, second},
        _endpoint_bus_registry=registry,
    )

    unloading = asyncio.create_task(
        EG4DataUpdateCoordinator._disconnect_all_transports(coordinator)
    )
    await asyncio.sleep(0)
    replacement = None
    try:
        replacement = registry.create_capability(_config("SYNTH00003"))
    except EndpointOwnerClosingError:
        pass

    for raw in raw_transports:
        raw.shutdown_release.set()
    detach_release.set()
    await unloading
    if replacement is not None:
        await replacement.async_shutdown()

    assert replacement is None
    assert registry.owner_count == 0


@pytest.mark.asyncio
async def test_live_owner_discovery_fails_closed_without_second_connection() -> None:
    probe = _WireProbe()
    raw_transports: list[_FakeRawTransport] = []

    def factory(config: TransportConfig) -> _FakeRawTransport:
        raw = _FakeRawTransport(config, probe)
        raw_transports.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    live = registry.create_capability(_config("SYNTH00001"))
    try:
        with pytest.raises(endpoint_bus.EndpointOwnerInUseError):
            await discover_modbus_device(
                "gateway.example.invalid",
                port=1502,
                endpoint_bus_registry=registry,
            )
    finally:
        await live.async_shutdown()

    assert len(raw_transports) == 1


@pytest.mark.asyncio
async def test_repeated_failed_hybrid_attach_discards_every_attempt() -> None:
    probe = _WireProbe()
    raw_transports: list[_TerminalFakeRawTransport] = []

    def factory(config: TransportConfig) -> _TerminalFakeRawTransport:
        raw = _TerminalFakeRawTransport(config, probe)
        raw_transports.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    capabilities: set[Any] = set()

    def create(config: TransportConfig) -> Any:
        capability = registry.create_capability(config)
        capabilities.add(capability)
        return capability

    async def fail_attach(configs: list[Any], *, transport_factory: Any) -> Any:
        capability = transport_factory(configs[0])
        await capability.async_shutdown()
        return SimpleNamespace(
            matched=0,
            failed=1,
            failed_serials=[configs[0].serial],
            unmatched_serials=[],
        )

    coordinator = SimpleNamespace(
        station=SimpleNamespace(
            all_inverters=[],
            all_mid_devices=[],
            attach_local_transports=fail_attach,
        ),
        _create_bus_capability=create,
        _endpoint_bus_registry=registry,
        _bus_capabilities=capabilities,
    )
    config = _config("SYNTH00001")

    await EG4DataUpdateCoordinator._attach_owned_transports(coordinator, [config])
    await EG4DataUpdateCoordinator._attach_owned_transports(coordinator, [config])

    assert capabilities == set()
    assert registry.owner_count == 0
    assert [raw.shutdown_calls for raw in raw_transports] == [1, 1]

    async def adopt(configs: list[Any], *, transport_factory: Any) -> Any:
        capability = transport_factory(configs[0])
        coordinator.station.all_inverters = [SimpleNamespace(transport=capability)]
        return SimpleNamespace(
            matched=1,
            failed=0,
            failed_serials=[],
            unmatched_serials=[],
        )

    coordinator.station.attach_local_transports = adopt
    await EG4DataUpdateCoordinator._attach_owned_transports(coordinator, [config])

    assert len(capabilities) == 1
    assert registry.owner_count == 1
    await registry.async_shutdown_capabilities(capabilities)


@pytest.mark.asyncio
async def test_failed_hybrid_cleanup_settles_and_discards_tracking() -> None:
    probe = _WireProbe()
    delayed_release = asyncio.Event()
    delayed_started = asyncio.Event()
    failed_attempts = 0

    class OutcomeTransport(_FakeRawTransport):
        async def async_shutdown(self) -> None:
            nonlocal failed_attempts
            if self.serial == "SYNTH00001" and failed_attempts == 0:
                failed_attempts += 1
                raise RuntimeError("synthetic terminal failure")
            delayed_started.set()
            await delayed_release.wait()

    registry = EndpointBusRegistry(
        raw_transport_factory=lambda config: OutcomeTransport(config, probe)
    )
    capabilities: set[EndpointBusCapability] = set()

    def create(config: TransportConfig) -> EndpointBusCapability:
        capability = registry.create_capability(config)
        capabilities.add(capability)
        return capability

    async def attach(configs: list[Any], *, transport_factory: Any) -> Any:
        for config in configs:
            transport_factory(config)
        return SimpleNamespace(
            matched=0,
            failed=2,
            failed_serials=[config.serial for config in configs],
            unmatched_serials=[],
        )

    coordinator = SimpleNamespace(
        station=SimpleNamespace(
            all_inverters=[],
            all_mid_devices=[],
            attach_local_transports=attach,
        ),
        _create_bus_capability=create,
        _endpoint_bus_registry=registry,
        _bus_capabilities=capabilities,
    )
    cleanup = asyncio.create_task(
        EG4DataUpdateCoordinator._attach_owned_transports(
            coordinator,
            [_config("SYNTH00001"), _config("SYNTH00002")],
        )
    )
    await delayed_started.wait()
    await asyncio.sleep(0)
    completed_before_release = cleanup.done()
    delayed_release.set()

    with pytest.raises(ExceptionGroup, match="Endpoint shutdown failures"):
        await cleanup

    assert completed_before_release is False
    assert len(capabilities) == 1
    assert next(iter(capabilities)).serial == "SYNTH00001"
    assert registry.owner_count == 1
    assert registry.tombstone_count == 1

    await registry.async_shutdown_capabilities(capabilities)
    capabilities.difference_update(
        capability
        for capability in tuple(capabilities)
        if not registry.is_retained_capability(capability)
    )

    assert capabilities == set()
    assert registry.owner_count == 0


@pytest.mark.asyncio
async def test_closing_tombstone_blocks_replacement_until_terminal_close() -> None:
    probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    owner_identity = capability.status.owner_identity
    probe.release.clear()
    closing = asyncio.create_task(capability.async_shutdown())
    await probe.started.wait()

    with pytest.raises(EndpointOwnerClosingError):
        registry.create_capability(_config("SYNTH00002"))
    assert registry.tombstone_count == 1

    probe.release.set()
    await closing
    replacement = registry.create_capability(_config("SYNTH00002"))
    assert replacement.status.owner_identity != owner_identity
    await replacement.async_shutdown()
    assert registry.owner_count == 0
    assert registry.tombstone_count == 0
    assert registry.active_task_count == 0


def test_constructor_failure_leaves_no_owner_lease_or_tombstone() -> None:
    def failing_factory(config: TransportConfig) -> _FakeRawTransport:
        raise OSError("synthetic construction failure")

    registry = EndpointBusRegistry(raw_transport_factory=failing_factory)
    with pytest.raises(OSError, match="synthetic construction failure"):
        registry.create_capability(_config("SYNTH00001"))

    assert registry.owner_count == 0
    assert registry.tombstone_count == 0
    assert registry.active_task_count == 0


@pytest.mark.parametrize(
    ("connection_type", "transports", "available", "eligible", "reason"),
    [
        (
            "local",
            [
                {
                    "transport_type": "modbus_tcp",
                    "serial": "SYNTH00001",
                    "host": "gateway.example.invalid",
                    "port": 1502,
                }
            ],
            {"SYNTH00001"},
            True,
            BusEligibilityReason.ELIGIBLE,
        ),
        (
            "hybrid",
            [
                {
                    "transport_type": "modbus_serial",
                    "serial": "SYNTH00001",
                    "serial_port": "loop://synthetic",
                }
            ],
            {"SYNTH00001"},
            True,
            BusEligibilityReason.ELIGIBLE,
        ),
        ("http", [], set(), False, BusEligibilityReason.CLOUD_ONLY),
        ("local", [], set(), False, BusEligibilityReason.EMPTY_LOCAL),
        ("modbus", [], set(), False, BusEligibilityReason.LEGACY_AMBIGUOUS),
        (
            "local",
            [{"transport_type": "modbus_tcp", "serial": "SYNTH00001"}],
            set(),
            False,
            BusEligibilityReason.AMBIGUOUS_ENDPOINT,
        ),
        (
            "hybrid",
            [
                {
                    "transport_type": "modbus_tcp",
                    "serial": "SYNTH00001",
                    "host": "gateway.example.invalid",
                    "port": 1502,
                }
            ],
            set(),
            False,
            BusEligibilityReason.UNCOVERED_BUS,
        ),
        (
            "local",
            [
                {
                    "transport_type": "modbus_tcp",
                    "serial": "SYNTH00001",
                    "host": "gateway.example.invalid",
                    "port": 1502,
                },
                {
                    "transport_type": "wifi_dongle",
                    "serial": "SYNTH00001",
                    "host": "dongle.example.invalid",
                    "port": 18000,
                },
            ],
            {"SYNTH00001"},
            False,
            BusEligibilityReason.OVERLAPPING_WIFI_DONGLE,
        ),
    ],
)
def test_fail_closed_eligibility_and_local_only_provenance(
    connection_type: str,
    transports: list[dict[str, Any]],
    available: set[str],
    eligible: bool,
    reason: BusEligibilityReason,
) -> None:
    result = evaluate_bus_owner_eligibility(
        connection_type=connection_type,
        local_transports=transports,
        available_serials=available,
    )
    assert result.eligible is eligible
    assert result.reason is reason
    assert result.provenance is LocalBusProvenance.LOCAL_BUS
    assert not hasattr(result, "host")


@pytest.mark.asyncio
async def test_foundation_preserves_exact_read_count_order_and_ranges() -> None:
    direct_probe = _WireProbe()
    direct = _FakeRawTransport(_config("SYNTH00001"), direct_probe)
    direct_coordinator, direct_inverter = _poll_coordinator(direct)
    with patch.object(
        BaseInverter,
        "from_modbus_transport",
        return_value=direct_inverter,
    ):
        await EG4DataUpdateCoordinator._async_update_local_transport_data(
            direct_coordinator,
            transport=direct,
            serial="SYNTH00001",
            model="synthetic",
            connection_type="modbus",
        )

    owned_probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": owned_probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    owned_coordinator, owned_inverter = _poll_coordinator(capability)
    with patch.object(
        BaseInverter,
        "from_modbus_transport",
        return_value=owned_inverter,
    ):
        await EG4DataUpdateCoordinator._async_update_local_transport_data(
            owned_coordinator,
            transport=capability,
            serial="SYNTH00001",
            model="synthetic",
            connection_type="modbus",
        )

    assert owned_probe.operations == direct_probe.operations
    assert owned_probe.operations == [
        ("connect", ()),
        ("read_parameters", (0, 2)),
        ("read_parameters", (20, 1)),
        ("read_parameters", (40, 3)),
        ("read_firmware_version", ()),
    ]


_RAW_CONSTRUCTORS = {
    "create_transport",
    "create_transport_from_config",
    "create_modbus_transport",
    "create_dongle_transport",
    "create_serial_transport",
}
_LOCAL_IO_METHODS = {
    "connect",
    "disconnect",
    "read_battery",
    "read_device_type",
    "read_energy",
    "read_firmware_version",
    "read_midbox_runtime",
    "read_named_parameters",
    "read_parallel_config",
    "read_parameters",
    "read_runtime",
    "read_serial_number",
    "write_named_parameters",
    "write_parameters",
}
_RAW_ESCAPE_ATTRIBUTES = {
    "_op_lock",
    "_raw",
    "_raw_transport",
    "_transport",
    "raw_transport",
}


def _audit_supported_source(
    source: str,
    *,
    owner_module: bool,
) -> list[str]:
    """Audit statically supported escape shapes, not dynamic Python execution."""
    tree = ast.parse(source)
    if owner_module:
        return []
    aliases: dict[str, str] = {}
    violations: list[str] = []
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def qualified_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = qualified_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    function_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

    def enclosing_function(node: ast.AST) -> ast.AST | None:
        parent = parents.get(node)
        while parent is not None and not isinstance(parent, function_types):
            parent = parents.get(parent)
        return parent

    capability_names: dict[ast.AST, set[str]] = {}
    raw_names: dict[ast.AST | None, set[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, function_types):
            continue
        names = capability_names.setdefault(node, set())
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if (
                argument.annotation is not None
                and "EndpointBusCapability" in ast.unparse(argument.annotation)
            ):
                names.add(argument.arg)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = qualified_name(node.func)
        called_name = called.rsplit(".", 1)[-1] if called else ""
        scope = enclosing_function(node)
        checked_type = qualified_name(node.args[1]) if len(node.args) >= 2 else None
        if (
            called_name == "isinstance"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and checked_type is not None
            and checked_type.endswith("EndpointBusCapability")
        ):
            capability_names.setdefault(scope, set()).add(node.args[0].id)

    def is_raw_expression(node: ast.expr, scope: ast.AST | None) -> bool:
        if isinstance(node, ast.Name):
            return node.id in raw_names.get(scope, set())
        if isinstance(node, ast.Attribute):
            return node.attr == "transport" or node.attr in _RAW_ESCAPE_ATTRIBUTES
        if not isinstance(node, ast.Call):
            return False
        called = qualified_name(node.func)
        called_name = called.rsplit(".", 1)[-1] if called else ""
        if called_name in _RAW_CONSTRUCTORS:
            return True
        if called_name == "cast" and len(node.args) >= 2:
            return is_raw_expression(node.args[1], scope)
        return (
            called_name == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _RAW_ESCAPE_ATTRIBUTES
        )

    assignments = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            scope = enclosing_function(node)
            value_is_raw = is_raw_expression(value, scope)
            if (
                isinstance(node, ast.AnnAssign)
                and node.annotation is not None
                and "EndpointBusCapability" in ast.unparse(node.annotation)
                and not value_is_raw
            ):
                for target in targets:
                    if isinstance(target, ast.Name):
                        capability_names.setdefault(scope, set()).add(target.id)
            if isinstance(value, ast.Call):
                called = qualified_name(value.func)
                called_name = called.rsplit(".", 1)[-1] if called else ""
                if called_name in {
                    "create_capability",
                    "create_discovery_capability",
                    "get_local_transport",
                    "validate_capability",
                }:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            capability_names.setdefault(scope, set()).add(target.id)
            if value_is_raw:
                names = raw_names.setdefault(scope, set())
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in names:
                        names.add(target.id)
                        changed = True

    def lambda_capability_call(node: ast.Call, receiver: ast.Name) -> bool:
        scope = enclosing_function(node)
        if not isinstance(scope, ast.Lambda):
            return False
        if receiver.id not in {argument.arg for argument in scope.args.args}:
            return False
        keyword = parents.get(scope)
        outer_call = parents.get(keyword) if isinstance(keyword, ast.keyword) else None
        if not isinstance(keyword, ast.keyword) or keyword.arg != "write":
            return False
        outer_name = (
            qualified_name(outer_call.func)
            if isinstance(outer_call, ast.Call)
            else None
        )
        return outer_name is not None and outer_name.endswith(
            "_write_with_local_transport"
        )

    def is_capability_receiver(node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        receiver = node.func.value
        called = qualified_name(receiver)
        if called is not None and ".api." in f"{called}.":
            return True
        if not isinstance(receiver, ast.Name):
            return False
        scope = enclosing_function(node)
        return receiver.id in capability_names.get(
            scope, set()
        ) or lambda_capability_call(node, receiver)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = qualified_name(node.func)
            called_name = called.rsplit(".", 1)[-1] if called else ""
            if called_name in _RAW_CONSTRUCTORS:
                violations.append(f"raw-constructor:{node.lineno}")
            if called_name in _LOCAL_IO_METHODS and not is_capability_receiver(node):
                violations.append(f"direct-local-io:{node.lineno}")
            if (
                called_name == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _RAW_ESCAPE_ATTRIBUTES
            ):
                violations.append(f"dynamic-unwrap:{node.lineno}")
        if isinstance(node, ast.Attribute) and node.attr in _RAW_ESCAPE_ATTRIBUTES:
            violations.append(f"private-state:{node.lineno}")
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, (ast.Attribute, ast.Subscript)) for target in targets
            ):
                scope = enclosing_function(node)
                if is_raw_expression(node.value, scope):
                    violations.append(f"generic-retention:{node.lineno}")
        if isinstance(node, ast.Return) and node.value is not None:
            scope = enclosing_function(node)
            if is_raw_expression(node.value, scope):
                violations.append(f"direct-return:{node.lineno}")
    return violations


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import pylxpweb.transports as pt\npt.create_modbus_transport()",
            "raw-constructor",
        ),
        (
            "from pylxpweb.transports import create_transport as factory\nfactory()",
            "raw-constructor",
        ),
        ("async def leak(raw):\n    await raw.read_runtime()", "direct-local-io"),
        (
            "def leak(holder):\n"
            "    raw = getattr(holder, '_transport')\n"
            "    holder.cache = raw",
            "generic-retention",
        ),
        (
            "def leak(holder):\n"
            "    raw = getattr(holder, '_transport')\n"
            "    return raw",
            "direct-return",
        ),
        (
            "def leak(device):\n    raw = device.transport\n    return raw",
            "direct-return",
        ),
        (
            "from typing import cast\n"
            "async def leak(device):\n"
            "    capability: EndpointBusCapability = cast(\n"
            "        EndpointBusCapability, device.transport\n"
            "    )\n"
            "    await capability.read_runtime()",
            "direct-local-io",
        ),
        ("getattr(holder, '_transport')", "dynamic-unwrap"),
        ("holder._op_lock = lock", "private-state"),
    ],
)
def test_architecture_audit_detects_supported_escape_mutations(
    source: str, expected: str
) -> None:
    violations = _audit_supported_source(
        source,
        owner_module=False,
    )
    assert any(violation.startswith(expected) for violation in violations)


def test_architecture_rejects_raw_transport_escape_and_private_monkeypatch() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "eg4_web_monitor"
    owner_path = root / "endpoint_bus.py"
    violations: list[str] = []

    for path in sorted(root.rglob("*.py")):
        relative = str(path.relative_to(root))
        findings = _audit_supported_source(
            path.read_text(),
            owner_module=path == owner_path,
        )
        violations.extend(f"{relative}:{finding}" for finding in findings)

    assert violations == []

    source = owner_path.read_text()
    assert "__getattr__" not in source
    assert "EndpointOperationLock" not in source
    hybrid_source = (root / "coordinator_local.py").read_text()
    assert "transport_factory=create" in hybrid_source

    probe = _WireProbe()
    capability = _registry({"gateway.example.invalid": probe}).create_capability(
        _config("SYNTH00001")
    )
    assert isinstance(capability, TerminalInverterTransport)
    assert capability.provenance is LocalBusProvenance.LOCAL_BUS
    assert not hasattr(capability, "raw_transport")
    assert not hasattr(capability, "host")


def test_capability_forwards_pinned_terminal_protocol_surface() -> None:
    protocol_members = get_protocol_members(TerminalInverterTransport)
    missing = {
        member
        for member in protocol_members
        if not hasattr(EndpointBusCapability, member)
    }
    assert missing == set()
