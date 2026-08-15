"""Endpoint-scoped local bus ownership contracts for Phase A2 (#581)."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pylxpweb.transports import TerminalInverterTransport
from pylxpweb.transports.capabilities import TransportCapabilities
from pylxpweb.transports.config import TransportConfig, TransportType

from custom_components.eg4_web_monitor.bus_eligibility import (
    BusEligibilityReason,
    LocalBusProvenance,
    evaluate_bus_owner_eligibility,
)
from custom_components.eg4_web_monitor.endpoint_bus import (
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
    ranges = [(0, 2), (20, 1), (40, 3)]

    async def poll(read: Callable[[int, int], Awaitable[dict[int, int]]]) -> None:
        for start, count in ranges:
            await read(start, count)

    direct_probe = _WireProbe()
    direct = _FakeRawTransport(_config("SYNTH00001"), direct_probe)
    await poll(direct.read_parameters)

    owned_probe = _WireProbe()
    registry = _registry({"gateway.example.invalid": owned_probe})
    capability = registry.create_capability(_config("SYNTH00001"))
    await poll(capability.read_parameters)

    assert owned_probe.operations == direct_probe.operations
    assert owned_probe.operations == [
        ("read_parameters", (0, 2)),
        ("read_parameters", (20, 1)),
        ("read_parameters", (40, 3)),
    ]


def test_architecture_rejects_raw_transport_escape_and_private_monkeypatch() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "eg4_web_monitor"
    owner_path = root / "endpoint_bus.py"
    forbidden_imports: list[str] = []
    forbidden_calls: list[str] = []
    forbidden_private_writes: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and path != owner_path:
                names = [alias.name for alias in node.names]
                if any(
                    name
                    in {
                        "create_transport",
                        "create_transport_from_config",
                        "create_modbus_transport",
                        "create_dongle_transport",
                        "create_serial_transport",
                    }
                    for name in names
                ):
                    forbidden_imports.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"connect", "disconnect"} and path != owner_path:
                    forbidden_calls.append(f"{relative}:{node.lineno}")
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(
                    isinstance(target, ast.Attribute)
                    and target.attr in {"_op_lock", "_transport"}
                    for target in targets
                ):
                    forbidden_private_writes.append(f"{relative}:{node.lineno}")

    assert forbidden_imports == []
    assert forbidden_calls == []
    assert forbidden_private_writes == []

    source = owner_path.read_text()
    assert "__getattr__" not in source
    assert "EndpointOperationLock" not in source
    hybrid_source = (root / "coordinator_local.py").read_text()
    assert "transport_factory=self._create_bus_capability" in hybrid_source

    probe = _WireProbe()
    capability = _registry({"gateway.example.invalid": probe}).create_capability(
        _config("SYNTH00001")
    )
    assert isinstance(capability, TerminalInverterTransport)
    assert capability.provenance is LocalBusProvenance.LOCAL_BUS
    assert not hasattr(capability, "raw_transport")
    assert not hasattr(capability, "host")
