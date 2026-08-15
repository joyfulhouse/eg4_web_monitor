"""Production-path endpoint-owner raw snapshot lifecycle tests (#583)."""

from __future__ import annotations

import ast
import asyncio
import gc
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import weakref

import pytest
from pylxpweb.transports import (
    RegisterObservation,
    RegisterObserver,
    RegisterSegment,
    RegisterSpace,
)
from pylxpweb.transports.capabilities import TransportCapabilities
from pylxpweb.transports.config import TransportConfig, TransportType

from custom_components.eg4_web_monitor.bus_eligibility import (
    BusEligibilityReason,
    BusOwnerEligibility,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor import endpoint_bus
from custom_components.eg4_web_monitor.endpoint_bus import (
    EndpointBusRegistry,
    EndpointCapabilityClosedError,
)
from custom_components.eg4_web_monitor.raw_snapshot import CrcValidationState


class _ObservedRawTransport:
    """Shape-faithful raw transport with the released observer contract."""

    def __init__(
        self,
        config: TransportConfig,
        observer: RegisterObserver | None,
        operations: list[tuple[str, tuple[Any, ...]]],
    ) -> None:
        self.serial = config.serial
        self.transport_type = config.transport_type.value
        self.inverter_family = config.inverter_family
        self.split_phase = False
        self.pv_string_count = 3
        self.is_midbox_device = False
        self.is_connected = True
        self.capabilities = TransportCapabilities()
        self.register_observation_error_count = 0
        self._observer = observer
        self._operations = operations
        self.emit = True
        self.extra_segment = False
        self.fail = False
        self.block = asyncio.Event()
        self.block.set()

    async def _read(self, name: str, start: int, words: tuple[int, ...]) -> Any:
        self._operations.append((name, (start, len(words))))
        await self.block.wait()
        if self.fail:
            raise RuntimeError("synthetic read failure")
        if self.emit and self._observer is not None:
            segments = [RegisterSegment(start, words)]
            if self.extra_segment:
                segments.append(RegisterSegment(start + len(words), (0x1234,)))
            self._observer(
                (
                    RegisterObservation(
                        RegisterSpace.INPUT,
                        tuple(segments),
                    ),
                )
            )
        return object()

    async def connect(self) -> None:
        self._operations.append(("connect", ()))
        self.is_connected = True

    async def disconnect(self) -> None:
        self._operations.append(("disconnect", ()))
        self.is_connected = False

    async def read_runtime(self) -> Any:
        return await self._read("read_runtime", 0, (11, 12))

    async def read_energy(self) -> Any:
        return await self._read("read_energy", 20, (21,))

    async def read_battery(self) -> Any:
        return await self._read("read_battery", 40, (41, 42, 43))

    async def read_parameters(self, start: int, count: int) -> dict[int, int]:
        await self._read("read_parameters", start, tuple(range(count)))
        return {start + offset: offset for offset in range(count)}

    async def write_parameters(self, parameters: dict[int, int]) -> bool:
        self._operations.append(("write_parameters", tuple(parameters.items())))
        return True

    async def read_named_parameters(self, start: int, count: int) -> dict[str, Any]:
        await self._read("read_named_parameters", start, tuple(range(count)))
        return {}

    async def write_named_parameters(self, parameters: dict[str, Any]) -> bool:
        self._operations.append(("write_named_parameters", tuple(parameters.items())))
        return True

    async def read_device_type(self) -> int:
        await self._read("read_device_type", 0, (0,))
        return 0

    async def read_firmware_version(self) -> str:
        await self._read("read_firmware_version", 7, (7,))
        return "synthetic-firmware"

    async def read_parallel_config(self) -> int:
        await self._read("read_parallel_config", 8, (8,))
        return 0

    async def read_serial_number(self) -> str:
        await self._read("read_serial_number", 9, (9,))
        return "SYNTHETIC"

    async def read_midbox_runtime(self) -> Any:
        return await self._read("read_midbox_runtime", 100, (100,))


def _config(
    *,
    transport_type: TransportType = TransportType.MODBUS_TCP,
    serial: str = "SYNTH00001",
    unit: int = 2,
) -> TransportConfig:
    return TransportConfig(
        host="gateway.example.invalid",
        port=1502,
        serial=serial,
        unit_id=unit,
        transport_type=transport_type,
        serial_port="loop://synthetic"
        if transport_type is TransportType.MODBUS_SERIAL
        else None,
        dongle_serial="SYNTHD0001"
        if transport_type is TransportType.WIFI_DONGLE
        else None,
    )


def _registry() -> tuple[
    EndpointBusRegistry, list[_ObservedRawTransport], list[tuple[str, tuple[Any, ...]]]
]:
    raws: list[_ObservedRawTransport] = []
    operations: list[tuple[str, tuple[Any, ...]]] = []

    def factory(
        config: TransportConfig,
        *,
        register_observer: RegisterObserver | None = None,
    ) -> _ObservedRawTransport:
        raw = _ObservedRawTransport(config, register_observer, operations)
        raws.append(raw)
        return raw

    return EndpointBusRegistry(raw_transport_factory=factory), raws, operations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_type", "crc_state"),
    [
        (TransportType.MODBUS_TCP, CrcValidationState.NOT_APPLICABLE),
        (TransportType.MODBUS_SERIAL, CrcValidationState.VALID),
    ],
)
async def test_complete_refresh_publishes_exact_segments_atomically(
    transport_type: TransportType, crc_state: CrcValidationState
) -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(transport_type=transport_type),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )

    assert capability.latest_complete_snapshot is None
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
        assert capability.latest_complete_snapshot is None
        await capability.read_energy()

    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == 1
    assert frame.poll_cycle == 1
    assert [(block.start_address, block.words) for block in frame.blocks] == [
        (0, (11, 12)),
        (20, (21,)),
    ]
    assert {block.unit for block in frame.blocks} == {2}
    assert {block.crc_state for block in frame.blocks} == {crc_state}


@pytest.mark.asyncio
async def test_failed_incomplete_and_observer_error_attempts_retain_prior_complete() -> (
    None
):
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    prior = capability.latest_complete_snapshot

    with pytest.raises(RuntimeError, match="cycle failed"):
        async with capability.complete_snapshot_refresh():
            await capability.read_energy()
            raise RuntimeError("cycle failed")
    raws[0].emit = False
    async with capability.complete_snapshot_refresh():
        await capability.read_energy()
    raws[0].emit = True
    async with capability.complete_snapshot_refresh():
        await capability.read_energy()
        raws[0].register_observation_error_count += 1

    assert capability.latest_complete_snapshot is prior
    assert capability.snapshot_health.suppressed_incomplete == 3
    assert capability.snapshot_health.observer_failures == 1

    async with capability.complete_snapshot_refresh():
        await capability.read_battery()
    recovered = capability.latest_complete_snapshot
    assert recovered is not None
    assert recovered.generation == 2
    assert recovered.poll_cycle == 5


@pytest.mark.asyncio
async def test_cancelled_refresh_publishes_nothing_partial() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )

    async def refresh() -> None:
        async with capability.complete_snapshot_refresh():
            await capability.read_runtime()
            raws[0].block.clear()
            await capability.read_energy()

    task = asyncio.create_task(refresh())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    raws[0].block.set()
    await registry.async_wait_idle()

    assert capability.latest_complete_snapshot is None
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_store_enabled_and_disabled_have_identical_read_order() -> None:
    enabled_registry, _, enabled_operations = _registry()
    disabled_registry, _, disabled_operations = _registry()
    enabled = enabled_registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    disabled = disabled_registry.create_capability(
        _config(), snapshot_enabled=False, poll_interval_seconds=5.0
    )

    async with enabled.complete_snapshot_refresh():
        await enabled.read_runtime()
        await enabled.read_energy()
        await enabled.read_battery()
    async with disabled.complete_snapshot_refresh():
        await disabled.read_runtime()
        await disabled.read_energy()
        await disabled.read_battery()

    assert enabled_operations == disabled_operations
    assert disabled.latest_complete_snapshot is None


@pytest.mark.asyncio
async def test_fail_closed_transport_coverage_and_unload_drop_lookup_data_callbacks() -> (
    None
):
    registry, raws, _ = _registry()
    direct = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    dongle = registry.create_capability(
        _config(transport_type=TransportType.WIFI_DONGLE, serial="SYNTH00002"),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )
    async with direct.complete_snapshot_refresh():
        await direct.read_runtime()

    registry.set_snapshot_coverage((direct,), enabled=False)
    assert direct.latest_complete_snapshot is None
    assert dongle.latest_complete_snapshot is None
    assert raws[1]._observer is None

    await registry.async_shutdown_capabilities((direct, dongle))
    assert registry.owner_count == 0
    assert registry.active_task_count == 0
    assert registry.snapshot_store_count == 0
    assert not registry.is_retained_capability(direct)


@pytest.mark.asyncio
async def test_reload_creates_inaccessible_old_epoch_and_fresh_generation() -> None:
    registry, _, _ = _registry()
    old = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with old.complete_snapshot_refresh():
        await old.read_runtime()
    old_frame = old.latest_complete_snapshot
    assert old_frame is not None
    await old.async_shutdown()
    with pytest.raises(EndpointCapabilityClosedError):
        _ = old.latest_complete_snapshot

    replacement = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with replacement.complete_snapshot_refresh():
        await replacement.read_runtime()
    replacement_frame = replacement.latest_complete_snapshot
    assert replacement_frame is not None
    assert replacement_frame.owner_epoch != old_frame.owner_epoch
    assert replacement_frame.generation == 1


@pytest.mark.asyncio
async def test_one_latest_complete_store_is_shared_per_endpoint_unit() -> None:
    registry, _, _ = _registry()
    first = registry.create_capability(
        _config(serial="SYNTH00001"),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )
    second = registry.create_capability(
        _config(serial="SYNTH00002"),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )

    async with first.complete_snapshot_refresh():
        await first.read_runtime()
    first_frame = first.latest_complete_snapshot
    assert second.latest_complete_snapshot is first_frame

    async with second.complete_snapshot_refresh():
        await second.read_energy()
    second_frame = second.latest_complete_snapshot
    assert second_frame is not None
    assert second_frame is first.latest_complete_snapshot
    assert second_frame is not first_frame
    assert second_frame.generation == 2
    assert second_frame.poll_cycle == 2

    await registry.async_shutdown_capabilities((first, second))


@pytest.mark.asyncio
async def test_closing_one_unit_drops_only_its_owner_retained_store() -> None:
    registry, _, _ = _registry()
    first = registry.create_capability(
        _config(serial="SYNTH00001", unit=1),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )
    second = registry.create_capability(
        _config(serial="SYNTH00002", unit=2),
        snapshot_enabled=True,
        poll_interval_seconds=5.0,
    )
    assert registry.snapshot_store_count == 2

    await first.async_shutdown()
    assert registry.owner_count == 1
    assert registry.snapshot_store_count == 1

    await second.async_shutdown()
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_unload_releases_raw_transport_observer_owner_reference_cycle() -> None:
    raw_reference: weakref.ReferenceType[_ObservedRawTransport] | None = None

    def factory(
        config: TransportConfig,
        *,
        register_observer: RegisterObserver | None = None,
    ) -> _ObservedRawTransport:
        nonlocal raw_reference
        raw = _ObservedRawTransport(config, register_observer, [])
        raw_reference = weakref.ref(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    await capability.async_shutdown()
    del capability
    gc.collect()

    assert raw_reference is not None
    assert raw_reference() is None
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_private_staging_overflow_is_bounded_and_retains_prior_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    prior = capability.latest_complete_snapshot

    monkeypatch.setattr(endpoint_bus, "MAX_SNAPSHOT_STAGED_BLOCKS", 1)
    raws[0].extra_segment = True
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()

    assert capability.latest_complete_snapshot is prior
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_capability_exposes_fresh_only_lookup_and_redacted_metrics() -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    never = capability.snapshot_metrics(monotonic_now=100.0)
    assert never.age_seconds is None
    assert never.fresh is False

    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    frame = capability.latest_complete_snapshot
    assert frame is not None
    metrics = capability.snapshot_metrics(
        monotonic_now=frame.acquired_monotonic_end + 15.0
    )

    assert metrics.age_seconds == 15.0
    assert metrics.fresh is False
    assert (
        capability.latest_fresh_snapshot(
            monotonic_now=frame.acquired_monotonic_end + 15.0
        )
        is None
    )
    assert "owner-" not in repr(metrics)
    assert "11" not in repr(metrics)


def test_snapshot_modules_have_no_parsed_cloud_entity_or_listener_ingest_route() -> (
    None
):
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "custom_components/eg4_web_monitor/raw_snapshot.py",
        root / "custom_components/eg4_web_monitor/endpoint_bus.py",
    ]
    banned = {"cloud", "coordinator", "entity", "listener", "socket"}
    imported_roots = {
        alias.name.split(".")[0]
        for path in paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported_roots.isdisjoint(banned)


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_type", ["local", "hybrid"])
async def test_coordinator_enables_observer_only_for_a2_eligible_direct_transport(
    connection_type: str,
) -> None:
    registry, raws, _ = _registry()
    coordinator = SimpleNamespace(
        connection_type=connection_type,
        _endpoint_bus_registry=registry,
        _bus_capabilities=set(),
        _bus_capability_configs={},
        _bus_owner_eligibility=BusOwnerEligibility(True, BusEligibilityReason.ELIGIBLE),
        _modbus_interval=7,
        _dongle_interval=30,
    )

    capability = EG4DataUpdateCoordinator._create_bus_capability(coordinator, _config())

    assert raws[0]._observer is not None
    assert capability.snapshot_freshness_policy.maximum_age_seconds == 21.0
    await capability.async_shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eligible,transport_type",
    [
        (False, TransportType.MODBUS_TCP),
        (True, TransportType.WIFI_DONGLE),
    ],
)
async def test_coordinator_observer_construction_fails_closed(
    eligible: bool, transport_type: TransportType
) -> None:
    registry, raws, _ = _registry()
    coordinator = SimpleNamespace(
        connection_type="local",
        _endpoint_bus_registry=registry,
        _bus_capabilities=set(),
        _bus_capability_configs={},
        _bus_owner_eligibility=BusOwnerEligibility(
            eligible,
            BusEligibilityReason.ELIGIBLE
            if eligible
            else BusEligibilityReason.UNCOVERED_BUS,
        ),
        _modbus_interval=5,
        _dongle_interval=30,
    )

    capability = EG4DataUpdateCoordinator._create_bus_capability(
        coordinator, _config(transport_type=transport_type)
    )

    assert raws[0]._observer is None
    assert capability.latest_complete_snapshot is None
    await capability.async_shutdown()


def test_local_owner_refresh_path_brackets_snapshot_lifecycle() -> None:
    """Removing the coordinator bracket disconnects observations from a cycle."""
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/eg4_web_monitor/coordinator_local.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_process_single_local_device"
    )
    calls = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "complete_snapshot_refresh" in calls
