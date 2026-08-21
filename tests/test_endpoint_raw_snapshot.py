"""Production-path endpoint-owner raw snapshot lifecycle tests (#583)."""

from __future__ import annotations

import ast
import asyncio
from builtins import BaseExceptionGroup
import gc
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
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
from custom_components.eg4_web_monitor import coordinator_local, endpoint_bus
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
        self._observer: RegisterObserver | None = None
        self._operations = operations
        self.emit = True
        self.extra_segment = False
        self.fail = False
        self.battery_result_none = False
        self.observation_override: object | None = None
        self.fail_attach = False
        self.fail_detach = False
        self.block = asyncio.Event()
        self.block.set()

    def set_register_observer(self, observer: RegisterObserver | None) -> None:
        """Attach or detach the observer through the released control seam."""
        if self.fail_attach and observer is not None:
            raise RuntimeError("synthetic attach failure")
        if self.fail_detach and observer is None:
            raise RuntimeError("synthetic detach failure")
        self._observer = observer

    async def _read(self, name: str, start: int, words: tuple[int, ...]) -> Any:
        self._operations.append((name, (start, len(words))))
        await self.block.wait()
        if self.fail:
            raise RuntimeError("synthetic read failure")
        if self.emit and self._observer is not None:
            observations = self.observation_override
            if observations is None:
                segments = [RegisterSegment(start, words)]
                if self.extra_segment:
                    segments.append(RegisterSegment(start + len(words), (0x1234,)))
                observations = (
                    RegisterObservation(RegisterSpace.INPUT, tuple(segments)),
                )
            self._observer(cast(Any, observations))
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
        if self.battery_result_none:
            self._operations.append(("read_battery", (40, 3)))
            await self.block.wait()
            return None
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

    def factory(config: TransportConfig) -> _ObservedRawTransport:
        raw = _ObservedRawTransport(config, operations)
        raws.append(raw)
        return raw

    return EndpointBusRegistry(raw_transport_factory=factory), raws, operations


def _observations(
    start: int = 0, words: tuple[int, ...] = (11, 12)
) -> tuple[RegisterObservation, ...]:
    return (
        RegisterObservation(
            RegisterSpace.INPUT,
            (RegisterSegment(start, words),),
        ),
    )


class _CoordinatorMidDevice:
    def __init__(self, capability: Any, refresh: Any) -> None:
        self.transport = capability
        self.has_data = True
        self.refresh = refresh


def _coordinator_refresh_owner(
    registry: EndpointBusRegistry,
    capability: Any,
    refresh: Any,
) -> SimpleNamespace:
    serial = "SYNTH00001"
    return SimpleNamespace(
        _mid_device_cache={serial: _CoordinatorMidDevice(capability, refresh)},
        _inverter_cache={},
        _firmware_cache={serial: "synthetic-firmware"},
        _endpoint_bus_registry=registry,
        _filter_unused_smart_port_sensors=lambda sensors, device: None,
        _calculate_gridboss_aggregates=lambda sensors: None,
        _prune_bus_capability_tracking=lambda: None,
    )


async def _run_coordinator_refresh(
    owner: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, bool]]:
    monkeypatch.setattr(
        coordinator_local,
        "_build_gridboss_sensor_mapping",
        lambda device: {"synthetic_power": 1},
    )
    processed: dict[str, Any] = {"devices": {}, "parameters": {}}
    availability: dict[str, bool] = {}
    await coordinator_local.LocalTransportMixin._process_single_local_device(
        owner,
        {
            "serial": "SYNTH00001",
            "host": "gateway.example.invalid",
            "transport_type": "modbus_tcp",
            "is_gridboss": True,
        },
        processed,
        availability,
    )
    return processed, availability


def _link_state_coordinator(
    registry: EndpointBusRegistry, *, connection_type: str
) -> SimpleNamespace:
    """Namespace covering both capability creation and link-state sync seams."""
    return SimpleNamespace(
        connection_type=connection_type,
        _endpoint_bus_registry=registry,
        _bus_capabilities=set(),
        _bus_capability_configs={},
        _bus_owner_eligibility=BusOwnerEligibility(
            False, BusEligibilityReason.UNCOVERED_BUS
        ),
        _modbus_interval=5,
        _dongle_interval=30,
        station=None,
        _local_transport_configs=(),
        _inverter_cache={},
        _mid_device_cache={},
        _link_down_notified=set(),
    )


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
async def test_shared_endpoint_unit_rejects_overlapping_refresh_leases() -> None:
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
    release = asyncio.Event()
    staged = asyncio.Event()

    async def first_refresh() -> None:
        async with first.complete_snapshot_refresh():
            await first.read_runtime()
            staged.set()
            await release.wait()

    task = asyncio.create_task(first_refresh())
    await staged.wait()
    with pytest.raises(RuntimeError, match="already active"):
        async with second.complete_snapshot_refresh():
            await second.read_energy()
    assert first.latest_complete_snapshot is None

    release.set()
    await task
    frame = first.latest_complete_snapshot
    assert frame is second.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == frame.poll_cycle == 1
    assert [(block.start_address, block.words) for block in frame.blocks] == [
        (0, (11, 12))
    ]


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
async def test_zero_observation_battery_none_does_not_hide_complete_reads() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    raws[0].battery_result_none = True

    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
        assert await capability.read_battery() is None

    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert [(block.start_address, block.words) for block in frame.blocks] == [
        (0, (11, 12))
    ]

    raws[0].emit = False
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    assert capability.latest_complete_snapshot is frame
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_partial_observation_mid_refresh_is_suppressed() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    prior = capability.latest_complete_snapshot

    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
        raws[0].emit = False
        await capability.read_energy()

    assert capability.latest_complete_snapshot is prior
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_invalid_observations_are_nonthrowing_bounded_and_suppressed() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    prior = capability.latest_complete_snapshot

    invalid_observations = (
        (),
        [SimpleNamespace(register_space=RegisterSpace.INPUT, segments=[])],
        (
            SimpleNamespace(
                register_space="input",
                segments=(SimpleNamespace(start_address=0, words=(1,)),),
            ),
        ),
        (
            SimpleNamespace(
                register_space=RegisterSpace.INPUT,
                segments=(SimpleNamespace(start_address=-1, words=(1,)),),
            ),
        ),
        (
            SimpleNamespace(
                register_space=RegisterSpace.INPUT,
                segments=(SimpleNamespace(start_address=0, words=[1]),),
            ),
        ),
        (
            SimpleNamespace(
                register_space=RegisterSpace.INPUT,
                segments=(SimpleNamespace(start_address=0, words=(True,)),),
            ),
        ),
        (
            SimpleNamespace(
                register_space=RegisterSpace.INPUT,
                segments=(SimpleNamespace(start_address=0xFFFF, words=(1, 2)),),
            ),
        ),
    )
    for observations in invalid_observations:
        raws[0].observation_override = observations
        async with capability.complete_snapshot_refresh():
            await capability.read_runtime()

    assert capability.latest_complete_snapshot is prior
    assert capability.snapshot_health.suppressed_incomplete == len(invalid_observations)
    assert capability.snapshot_health.observer_failures == len(invalid_observations)

    raws[0].observation_override = invalid_observations[-1]
    with pytest.raises(LookupError, match="original refresh failure"):
        async with capability.complete_snapshot_refresh():
            await capability.read_runtime()
            raise LookupError("original refresh failure")


@pytest.mark.asyncio
async def test_terminal_observation_time_controls_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0
    monkeypatch.setattr(endpoint_bus.time, "monotonic", lambda: now)
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )

    async with capability.complete_snapshot_refresh():
        now = 20.0
        await capability.read_runtime()
        now = 100.0

    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.acquired_monotonic_start == 10.0
    assert frame.acquired_monotonic_end == 20.0
    assert capability.latest_fresh_snapshot(monotonic_now=35.0) is None


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
async def test_coverage_loss_detaches_owner_callback_and_removes_store() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    observer = raws[0]._observer
    assert observer is not None
    owner_reference = weakref.ref(capability._owner)

    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    registry.set_snapshot_coverage((capability,), enabled=False)

    assert raws[0]._observer is None
    observer(_observations(20, (21,)))
    await capability.read_energy()
    assert capability.latest_complete_snapshot is None
    assert registry.snapshot_store_count == 0

    del observer
    await capability.async_shutdown()
    del capability
    del registry
    gc.collect()
    assert owner_reference() is None


@pytest.mark.asyncio
async def test_coverage_restore_reattaches_observer_and_republishes() -> None:
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()

    registry.set_snapshot_coverage((capability,), enabled=False)
    assert raws[0]._observer is None
    assert capability.latest_complete_snapshot is None

    registry.set_snapshot_coverage((capability,), enabled=True)
    assert raws[0]._observer is not None
    async with capability.complete_snapshot_refresh():
        await capability.read_energy()

    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == frame.poll_cycle == 2
    assert [(block.start_address, block.words) for block in frame.blocks] == [
        (20, (21,))
    ]


@pytest.mark.asyncio
async def test_coverage_restore_never_reuses_published_frame_identity() -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    first = capability.latest_complete_snapshot
    assert first is not None

    registry.set_snapshot_coverage((capability,), enabled=False)
    assert capability.latest_complete_snapshot is None
    registry.set_snapshot_coverage((capability,), enabled=True)
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()

    second = capability.latest_complete_snapshot
    assert second is not None
    assert second.owner_epoch == first.owner_epoch
    assert second.generation > first.generation
    assert second.poll_cycle > first.poll_cycle
    assert (second.owner_epoch, second.generation) != (
        first.owner_epoch,
        first.generation,
    )


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
    raws: list[_ObservedRawTransport] = []

    def factory(config: TransportConfig) -> _ObservedRawTransport:
        raw = _ObservedRawTransport(config, [])
        raws.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    assert raws[0]._observer is not None
    await capability.async_shutdown()
    assert raws[0]._observer is None

    raw_reference = weakref.ref(raws[0])
    raws.clear()
    del capability
    gc.collect()

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

    assert metrics.age_seconds == pytest.approx(15.0)
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
    imported_parts = {
        part
        for path in paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for imported in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import) or node.module is None
            else [node.module]
        )
        for part in imported.split(".")
    }
    assert not {
        part
        for part in imported_parts
        if any(
            part == name
            or part.startswith(f"{name}_")
            or (name == "entity" and part == "entities")
            for name in banned
        )
    }


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


@pytest.mark.asyncio
async def test_coordinator_refresh_publishes_only_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )

    async def refresh() -> None:
        await capability.read_runtime()
        assert capability.latest_complete_snapshot is None

    owner = _coordinator_refresh_owner(registry, capability, refresh)
    processed, availability = await _run_coordinator_refresh(owner, monkeypatch)

    assert availability == {"SYNTH00001": True}
    assert "SYNTH00001" in processed["devices"]
    assert capability.latest_complete_snapshot is not None


@pytest.mark.asyncio
async def test_coordinator_failed_refresh_retains_prior_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pylxpweb.transports.exceptions import TransportReadError

    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_energy()
    prior = capability.latest_complete_snapshot

    async def refresh() -> None:
        await capability.read_runtime()
        raise TransportReadError("synthetic refresh failure")

    owner = _coordinator_refresh_owner(registry, capability, refresh)
    _, availability = await _run_coordinator_refresh(owner, monkeypatch)

    assert availability == {"SYNTH00001": False}
    assert capability.latest_complete_snapshot is prior
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_coordinator_cancelled_refresh_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    staged = asyncio.Event()
    release = asyncio.Event()

    async def refresh() -> None:
        await capability.read_runtime()
        staged.set()
        await release.wait()

    owner = _coordinator_refresh_owner(registry, capability, refresh)
    task = asyncio.create_task(_run_coordinator_refresh(owner, monkeypatch))
    await staged.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert capability.latest_complete_snapshot is None
    assert capability.snapshot_health.suppressed_incomplete == 1


@pytest.mark.asyncio
async def test_coordinator_coverage_loss_during_refresh_drops_partial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )

    async def refresh() -> None:
        await capability.read_runtime()
        registry.set_snapshot_coverage((capability,), enabled=False)

    owner = _coordinator_refresh_owner(registry, capability, refresh)
    await _run_coordinator_refresh(owner, monkeypatch)

    assert capability.latest_complete_snapshot is None
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_failed_snapshot_context_entry_is_not_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )

    async def refresh() -> None:
        raise AssertionError("refresh must not run after failed context entry")

    owner = _coordinator_refresh_owner(registry, capability, refresh)
    active = capability.complete_snapshot_refresh()
    await active.__aenter__()
    overlapping = capability.complete_snapshot_refresh()

    class TrackingContext:
        exited = False

        async def __aenter__(self) -> None:
            await overlapping.__aenter__()

        async def __aexit__(self, *args: object) -> None:
            self.exited = True
            await overlapping.__aexit__(*args)

    tracking = TrackingContext()
    monkeypatch.setattr(capability, "complete_snapshot_refresh", lambda: tracking)
    await _run_coordinator_refresh(owner, monkeypatch)
    await active.__aexit__(None, None, None)

    assert tracking.exited is False
    assert capability.latest_complete_snapshot is None
    assert capability.snapshot_health.suppressed_incomplete == 1


def test_snapshot_coverage_sync_fails_closed_without_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bool] = []
    owner = SimpleNamespace(
        station=None,
        connection_type="local",
        _local_transport_configs=(),
        _inverter_cache={},
        _mid_device_cache={},
        _link_down_notified=set(),
        _endpoint_bus_registry=SimpleNamespace(
            set_snapshot_coverage=lambda capabilities, *, enabled: observed.append(
                enabled
            )
        ),
        _bus_capabilities=set(),
    )
    monkeypatch.setattr(
        coordinator_local, "evaluate_bus_owner_eligibility", lambda **kwargs: None
    )

    coordinator_local.LocalTransportMixin._sync_transport_link_state(
        owner, {"devices": {}}
    )

    assert observed == [False]


@pytest.mark.asyncio
async def test_initially_ineligible_capability_enables_on_later_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capability created before eligibility must enable on coverage restore."""
    registry, raws, _ = _registry()
    coordinator = _link_state_coordinator(registry, connection_type="local")
    capability = EG4DataUpdateCoordinator._create_bus_capability(coordinator, _config())
    assert raws[0]._observer is None
    assert capability.latest_complete_snapshot is None

    monkeypatch.setattr(
        coordinator_local,
        "evaluate_bus_owner_eligibility",
        lambda **kwargs: BusOwnerEligibility(True, BusEligibilityReason.ELIGIBLE),
    )
    coordinator_local.LocalTransportMixin._sync_transport_link_state(
        coordinator, {"devices": {}}
    )

    assert raws[0]._observer is not None
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == frame.poll_cycle == 1
    await capability.async_shutdown()


@pytest.mark.asyncio
async def test_coverage_restore_observes_only_direct_local_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eligibility restore must not observe an observer-capable WiFi dongle."""
    registry, raws, _ = _registry()
    coordinator = _link_state_coordinator(registry, connection_type="hybrid")
    direct = EG4DataUpdateCoordinator._create_bus_capability(
        coordinator, _config(serial="SYNTH00001")
    )
    dongle = EG4DataUpdateCoordinator._create_bus_capability(
        coordinator,
        _config(transport_type=TransportType.WIFI_DONGLE, serial="SYNTH00002"),
    )
    assert raws[0]._observer is None
    assert raws[1]._observer is None

    monkeypatch.setattr(
        coordinator_local,
        "evaluate_bus_owner_eligibility",
        lambda **kwargs: BusOwnerEligibility(True, BusEligibilityReason.ELIGIBLE),
    )
    coordinator_local.LocalTransportMixin._sync_transport_link_state(
        coordinator, {"devices": {}}
    )

    assert raws[0]._observer is not None
    assert raws[1]._observer is None
    async with dongle.complete_snapshot_refresh():
        await dongle.read_runtime()
    assert dongle.latest_complete_snapshot is None

    await registry.async_shutdown_capabilities((direct, dongle))


@pytest.mark.asyncio
async def test_failed_observer_attach_during_add_retains_no_record_or_state() -> None:
    """A rejected observer attach must not leak an unreachable record or store."""
    raws: list[_ObservedRawTransport] = []

    def factory(config: TransportConfig) -> _ObservedRawTransport:
        raw = _ObservedRawTransport(config, [])
        raw.fail_attach = not raws
        raws.append(raw)
        return raw

    registry = EndpointBusRegistry(raw_transport_factory=factory)
    with pytest.raises(RuntimeError, match="synthetic attach failure"):
        registry.create_capability(
            _config(), snapshot_enabled=True, poll_interval_seconds=5.0
        )

    owner = next(iter(registry._owners.values()))
    assert not owner._records
    assert raws[0]._observer is None
    assert registry.snapshot_store_count == 0

    recovered = registry.create_capability(
        _config(serial="SYNTH00002"), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    assert raws[1]._observer is not None
    async with recovered.complete_snapshot_refresh():
        await recovered.read_runtime()
    assert recovered.latest_complete_snapshot is not None


@pytest.mark.asyncio
async def test_failed_observer_attach_on_restore_stays_disabled_and_retryable() -> None:
    """A rejected restore attach commits nothing and remains retryable."""
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    registry.set_snapshot_coverage((capability,), enabled=False)

    raws[0].fail_attach = True
    with pytest.raises(BaseExceptionGroup, match="snapshot coverage"):
        registry.set_snapshot_coverage((capability,), enabled=True)
    assert raws[0]._observer is None
    assert capability.latest_complete_snapshot is None
    assert registry.snapshot_store_count == 0

    raws[0].fail_attach = False
    registry.set_snapshot_coverage((capability,), enabled=True)
    assert raws[0]._observer is not None
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == frame.poll_cycle == 1


@pytest.mark.asyncio
async def test_failed_detach_on_coverage_loss_clears_state_and_stays_retryable() -> (
    None
):
    """A rejected detach must still quarantine local state and stay retryable."""
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    assert capability.latest_complete_snapshot is not None

    raws[0].fail_detach = True
    with pytest.raises(BaseExceptionGroup, match="snapshot coverage"):
        registry.set_snapshot_coverage((capability,), enabled=False)
    assert capability.latest_complete_snapshot is None
    assert registry.snapshot_store_count == 0

    raws[0].fail_detach = False
    registry.set_snapshot_coverage((capability,), enabled=False)
    assert raws[0]._observer is None

    registry.set_snapshot_coverage((capability,), enabled=True)
    async with capability.complete_snapshot_refresh():
        await capability.read_energy()
    frame = capability.latest_complete_snapshot
    assert frame is not None
    assert frame.generation == frame.poll_cycle == 2


@pytest.mark.asyncio
async def test_failed_detach_still_releases_remaining_capabilities() -> None:
    """One rejected detach must not leave later capabilities observed/stale."""
    registry, raws, _ = _registry()
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
    async with first.complete_snapshot_refresh():
        await first.read_runtime()
    async with second.complete_snapshot_refresh():
        await second.read_runtime()

    raws[0].fail_detach = True
    with pytest.raises(BaseExceptionGroup, match="snapshot coverage"):
        registry.set_snapshot_coverage((first, second), enabled=False)

    assert first.latest_complete_snapshot is None
    assert second.latest_complete_snapshot is None
    assert raws[0]._observer is not None
    assert raws[1]._observer is None
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_failed_detach_during_shutdown_is_best_effort_and_retryable() -> None:
    """A rejected detach must not skip later capabilities or terminal retries."""
    registry, raws, _ = _registry()
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

    raws[0].fail_detach = True
    with pytest.raises(BaseExceptionGroup, match="shutdown"):
        await registry.async_shutdown_capabilities((first, second))

    # Later capabilities were still processed best-effort to terminal close.
    assert raws[1]._observer is None
    assert not registry.is_retained_capability(second)
    # The failed capability stays retained, closing, and still observed.
    assert raws[0]._observer is not None
    assert registry.is_retained_capability(first)
    assert registry.tombstone_count == 1

    raws[0].fail_detach = False
    await registry.async_retry_failed_shutdowns((_config(serial="SYNTH00001"),))
    assert raws[0]._observer is None
    assert not registry.is_retained_capability(first)
    assert registry.owner_count == 0
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_terminal_completion_waits_for_successful_observer_detach() -> None:
    """Terminal shutdown must not complete while the observer stays attached."""
    registry, raws, _ = _registry()
    capability = registry.create_capability(
        _config(), snapshot_enabled=True, poll_interval_seconds=5.0
    )
    async with capability.complete_snapshot_refresh():
        await capability.read_runtime()
    assert capability.latest_complete_snapshot is not None

    raws[0].fail_detach = True
    with pytest.raises(BaseExceptionGroup, match="shutdown"):
        await registry.async_shutdown_capabilities((capability,))
    assert raws[0]._observer is not None
    assert registry.is_retained_capability(capability)
    assert registry.owner_count == 1

    raws[0].fail_detach = False
    await registry.async_retry_failed_shutdowns((_config(),))
    assert raws[0]._observer is None
    assert not registry.is_retained_capability(capability)
    assert registry.owner_count == 0
    assert registry.snapshot_store_count == 0


@pytest.mark.asyncio
async def test_retired_snapshot_identity_stays_bounded_across_units() -> None:
    """Coverage toggles for many units retain one bounded identity high-water mark."""
    registry, _, _ = _registry()
    capabilities = [
        registry.create_capability(
            _config(serial=f"SYNTH0000{unit}", unit=unit),
            snapshot_enabled=True,
            poll_interval_seconds=5.0,
        )
        for unit in (1, 2, 3)
    ]
    frames = []
    for capability in capabilities:
        async with capability.complete_snapshot_refresh():
            await capability.read_runtime()
        frame = capability.latest_complete_snapshot
        assert frame is not None
        frames.append(frame)
        registry.set_snapshot_coverage((capability,), enabled=False)

    # (owner_epoch, generation) identifies a frame and must never repeat
    # within one owner epoch, even across sibling units.
    identities = {(frame.owner_epoch, frame.generation) for frame in frames}
    assert len(identities) == len(frames)

    owner = capabilities[0]._owner
    assert owner._snapshot_poll_cycle_floor == 1
    assert not hasattr(owner, "_snapshot_counters")
    assert registry.snapshot_store_count == 0

    registry.set_snapshot_coverage((capabilities[2],), enabled=True)
    async with capabilities[2].complete_snapshot_refresh():
        await capabilities[2].read_runtime()
    frame = capabilities[2].latest_complete_snapshot
    assert frame is not None
    assert frame.generation == 4
    assert frame.poll_cycle == 2
    assert (frame.owner_epoch, frame.generation) not in identities
