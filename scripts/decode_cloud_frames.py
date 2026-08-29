#!/usr/bin/env python3
"""Create a synthetic protocol fixture from an authorized offline capture."""

from __future__ import annotations

import argparse
import bisect
import io
import json
import math
import os
import re
import secrets
import stat
import sys
from collections.abc import Buffer, Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import Any, BinaryIO, Final, Never, Protocol, cast


class _CaptureReader(Protocol):
    def __iter__(self) -> Iterator[tuple[float, Buffer]]: ...

    def datalink(self) -> int: ...


class _ReaderFactory(Protocol):
    def __call__(self, capture: BinaryIO) -> _CaptureReader: ...


class _PacketFactory(Protocol):
    def __call__(self, packet: bytes) -> _LinkPacket: ...


class _LinkPacket(Protocol):
    data: object


class _IPPacket(Protocol):
    src: Buffer
    dst: Buffer
    p: int
    data: object


class _TCPPacket(Protocol):
    sport: int
    dport: int
    seq: int
    ack: int
    flags: int
    opts: Buffer
    data: Buffer


class _PcapNamespace(Protocol):
    DLT_EN10MB: int
    DLT_LINUX_SLL: int
    DLT_LINUX_SLL2: int
    UniversalReader: _ReaderFactory


class _PacketNamespace(Protocol):
    Ethernet: _PacketFactory


class _SLLNamespace(Protocol):
    SLL: _PacketFactory


class _SLL2Namespace(Protocol):
    SLL2: _PacketFactory


class _IPNamespace(Protocol):
    IP: type
    IP_PROTO_TCP: int


class _IP6Namespace(Protocol):
    IP6: type


class _TCPNamespace(Protocol):
    TCP: type
    TH_ACK: int
    TH_FIN: int
    TH_RST: int
    TH_SYN: int


class _DPKT(Protocol):
    pcap: _PcapNamespace
    ethernet: _PacketNamespace
    sll: _SLLNamespace
    sll2: _SLL2Namespace
    ip: _IPNamespace
    ip6: _IP6Namespace
    tcp: _TCPNamespace


def _load_dpkt() -> _DPKT | None:
    try:
        module = import_module("dpkt")
    except ImportError:
        return None
    return cast(_DPKT, module)


dpkt = _load_dpkt()

FRAME_MAGIC: Final = b"\xa1\x1a"
SYNTHETIC_DONGLE_IDENTITY: Final = "SYNTHDG001"
SYNTHETIC_INVERTER_IDENTITY: Final = "SYNTHIV001"
DOCUMENTATION_DONGLE_ADDRESS: Final = "192.0.2.10"
DOCUMENTATION_CLOUD_ADDRESS: Final = "198.51.100.20"
SYNTHETIC_REGISTER_WORD: Final = "SYNTHETIC_A55A"
MAX_SANITIZED_RECORDS: Final = 1024
_SEQUENCE_MODULUS: Final = 1 << 32
_SEQUENCE_HALF: Final = 1 << 31
_PENDING_BYTE_MEMORY_CHARGE: Final = max(
    1,
    sys.getsizeof({0: 0}) - sys.getsizeof({}) + sys.getsizeof(0),
)
_ATOMIC_DIR_FD_SUPPORTED: Final = all(
    function in os.supports_dir_fd
    for function in (os.open, os.link, os.stat, os.unlink)
)
_DONGLE_ALIAS = re.compile(r"SYNTHDG[0-9]{3}\Z")
_INVERTER_ALIAS = re.compile(r"SYNTHIV[0-9]{3}\Z")


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def compute_crc16(data: Buffer) -> int:
    """Return the Modbus CRC in the byte order used by captured frames."""
    crc = 0xFFFF
    for byte in bytes(data):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


class FailureReason(StrEnum):
    """Bounded failure categories that never contain captured values."""

    CAPACITY = "capacity"
    CLI = "cli"
    CRC = "crc"
    DEPENDENCY = "dependency"
    EMPTY = "empty"
    FUNCTION = "function"
    IDENTITY = "identity"
    INPUT_CHANGED = "input_changed"
    INPUT_KIND = "input_kind"
    INPUT_SIZE = "input_size"
    IP_VERSION = "ip_version"
    MALFORMED = "malformed"
    OUTPUT = "output"
    OUTPUT_EXISTS = "output_exists"
    OVERSIZE = "oversize"
    PREFIX = "prefix"
    PROTOCOL = "protocol"
    RANGE = "range"
    SCHEMA = "schema"
    TIMEOUT = "timeout"
    TRUNCATED = "truncated"
    UNSUPPORTED_LINK = "unsupported_link"


class CaptureError(RuntimeError):
    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        super().__init__(f"capture rejected: {reason.value}")


@dataclass(frozen=True, slots=True)
class ParserPolicy:
    maximum_frame_bytes: int = 4096
    prefix_scan_bytes: int = 64
    overall_frame_deadline: float = 5.0
    maximum_capture_bytes: int = 16 * 1024 * 1024
    maximum_packet_bytes: int = 1024 * 1024
    maximum_packets: int = 100_000
    maximum_flows: int = 128
    maximum_segments_per_flow: int = 4096
    maximum_pending_bytes_per_flow: int = 16 * 1024
    maximum_reassembled_bytes_per_flow: int = 4 * 1024 * 1024
    maximum_aggregate_memory_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        bounded: tuple[tuple[int | float, int | float, int | float], ...] = (
            (self.maximum_frame_bytes, 512, 65535),
            (self.prefix_scan_bytes, 2, 1024),
            (self.overall_frame_deadline, 1.0, 30.0),
            (self.maximum_capture_bytes, 1, 64 * 1024 * 1024),
            (self.maximum_packet_bytes, 1, 4 * 1024 * 1024),
            (self.maximum_packets, 1, 1_000_000),
            (self.maximum_flows, 1, 4096),
            (self.maximum_segments_per_flow, 1, 100_000),
            (self.maximum_pending_bytes_per_flow, 1, 1024 * 1024),
            (self.maximum_reassembled_bytes_per_flow, 1, 64 * 1024 * 1024),
            (self.maximum_aggregate_memory_bytes, 1, 64 * 1024 * 1024),
        )
        if any(
            not math.isfinite(value) or value < low or value > high
            for value, low, high in bounded
        ):
            raise ValueError("parser policy value outside the internal contract")

    @property
    def reassembly_capacity(self) -> int:
        return self.maximum_pending_bytes_per_flow


@dataclass(slots=True)
class _MemoryBudget:
    limit: int
    retained: int = 0

    def reserve(self, count: int) -> None:
        if count < 0 or self.retained + count > self.limit:
            raise CaptureError(FailureReason.CAPACITY)
        self.retained += count

    def release(self, count: int) -> None:
        self.retained -= count
        if self.retained < 0:
            raise CaptureError(FailureReason.MALFORMED)


class _ChargedRingBuffer:
    """Lazy fixed-capacity ring whose whole allocation is budgeted up front."""

    def __init__(self, capacity: int, budget: _MemoryBudget) -> None:
        self._capacity = capacity
        self._budget = budget
        self._data: bytearray | None = None
        self._head = 0
        self._size = 0

    def __len__(self) -> int:
        return self._size

    @property
    def allocated_bytes(self) -> int:
        return self._capacity if self._data is not None else 0

    def _ensure_allocated(self) -> bytearray:
        if self._data is None:
            self._budget.reserve(self._capacity)
            try:
                self._data = bytearray(self._capacity)
            except MemoryError:
                self._budget.release(self._capacity)
                raise CaptureError(FailureReason.CAPACITY) from None
        return self._data

    def byte_at(self, index: int) -> int:
        if not 0 <= index < self._size or self._data is None:
            raise CaptureError(FailureReason.MALFORMED)
        return self._data[(self._head + index) % self._capacity]

    def append(self, value: Buffer) -> None:
        view = memoryview(value).cast("B")
        if len(view) > self._capacity - self._size:
            raise CaptureError(FailureReason.CAPACITY)
        if not view:
            return
        data = self._ensure_allocated()
        tail = (self._head + self._size) % self._capacity
        first = min(len(view), self._capacity - tail)
        data[tail : tail + first] = view[:first]
        data[: len(view) - first] = view[first:]
        self._size += len(view)

    def find(self, value: bytes) -> int:
        if not value:
            return 0
        limit = self._size - len(value) + 1
        for index in range(max(0, limit)):
            if all(
                self.byte_at(index + offset) == byte
                for offset, byte in enumerate(value)
            ):
                return index
        return -1

    def to_bytes(self, start: int = 0, count: int | None = None) -> bytes:
        length = self._size - start if count is None else count
        if start < 0 or length < 0 or start + length > self._size:
            raise CaptureError(FailureReason.MALFORMED)
        if not length:
            return b""
        if self._data is None:
            raise CaptureError(FailureReason.MALFORMED)
        physical_start = (self._head + start) % self._capacity
        first = min(length, self._capacity - physical_start)
        return bytes(self._data[physical_start : physical_start + first]) + bytes(
            self._data[: length - first]
        )

    def discard(self, count: int) -> None:
        if not 0 <= count <= self._size:
            raise CaptureError(FailureReason.MALFORMED)
        self._head = (self._head + count) % self._capacity
        self._size -= count
        if not self._size:
            self._head = 0

    def release(self) -> None:
        if self._data is not None:
            self._data = None
            self._budget.release(self._capacity)
        self._head = 0
        self._size = 0


class StreamFrameDecoder:
    def __init__(
        self,
        policy: ParserPolicy | None = None,
        budget: _MemoryBudget | None = None,
    ) -> None:
        self.policy = policy or ParserPolicy()
        self._budget = budget or _MemoryBudget(
            self.policy.maximum_aggregate_memory_bytes
        )
        self._buffer = _ChargedRingBuffer(
            self.policy.maximum_frame_bytes + self.policy.prefix_scan_bytes,
            self._budget,
        )
        self._prefix_scanned = 0
        self._started_at: float | None = None
        self._last_captured_at: float | None = None

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(
        self,
        data: Buffer,
        *,
        captured_at: float,
        observed_at: float | None = None,
    ) -> list[bytes]:
        normalized = bytes(data)
        observation = captured_at if observed_at is None else observed_at
        if (
            not _is_finite_number(captured_at)
            or not _is_finite_number(observation)
            or captured_at > observation
        ):
            raise CaptureError(FailureReason.MALFORMED)
        self._validate_timestamp(observation)
        self._check_deadline(observation)
        if normalized and self._started_at is None:
            self._started_at = captured_at
        decoded: list[bytes] = []
        offset = 0
        storage_limit = self.policy.maximum_frame_bytes + self.policy.prefix_scan_bytes
        while offset < len(normalized):
            room = storage_limit - len(self._buffer)
            if room <= 0:
                before = len(self._buffer)
                decoded.extend(self._extract_available(captured_at))
                if len(self._buffer) >= before:
                    raise CaptureError(FailureReason.CAPACITY)
                continue
            take = min(room, len(normalized) - offset)
            self._buffer.append(normalized[offset : offset + take])
            offset += take
            decoded.extend(self._extract_available(captured_at))
        decoded.extend(self._extract_available(captured_at))
        return decoded

    def close(self, *, captured_at: float) -> None:
        self._validate_timestamp(captured_at)
        self._check_deadline(captured_at)
        self._extract_available(captured_at)
        if len(self._buffer) or self._prefix_scanned:
            self._discard()
            raise CaptureError(FailureReason.TRUNCATED)
        self._buffer.release()

    def _check_deadline(self, captured_at: float) -> None:
        if (
            self._started_at is not None
            and captured_at - self._started_at > self.policy.overall_frame_deadline
        ):
            self._discard()
            raise CaptureError(FailureReason.TIMEOUT)

    def _validate_timestamp(self, captured_at: float) -> None:
        if not _is_finite_number(captured_at) or (
            self._last_captured_at is not None and captured_at < self._last_captured_at
        ):
            raise CaptureError(FailureReason.MALFORMED)
        self._last_captured_at = captured_at

    def _remove_prefix(self, count: int) -> None:
        if count:
            self._buffer.discard(count)

    def _extract_available(self, captured_at: float) -> list[bytes]:
        frames: list[bytes] = []
        while len(self._buffer):
            magic_index = self._buffer.find(FRAME_MAGIC)
            if magic_index < 0:
                retained = int(
                    len(self._buffer) > 0
                    and self._buffer.byte_at(len(self._buffer) - 1) == FRAME_MAGIC[0]
                )
                discarded = len(self._buffer) - retained
                self._prefix_scanned += discarded
                if self._prefix_scanned > self.policy.prefix_scan_bytes:
                    self._discard()
                    raise CaptureError(FailureReason.PREFIX)
                self._remove_prefix(discarded)
                break
            if magic_index:
                self._prefix_scanned += magic_index
                if self._prefix_scanned > self.policy.prefix_scan_bytes:
                    self._discard()
                    raise CaptureError(FailureReason.PREFIX)
                self._remove_prefix(magic_index)
            if len(self._buffer) < 6:
                break
            total_size = 6 + int.from_bytes(self._buffer.to_bytes(4, 2), "little")
            if total_size > self.policy.maximum_frame_bytes:
                self._discard()
                raise CaptureError(FailureReason.OVERSIZE)
            if total_size < 19:
                self._discard()
                raise CaptureError(FailureReason.MALFORMED)
            if len(self._buffer) < total_size:
                break
            frames.append(self._buffer.to_bytes(0, total_size))
            self._remove_prefix(total_size)
            self._prefix_scanned = 0
            self._started_at = captured_at if len(self._buffer) else None
        return frames

    def _discard(self) -> None:
        self._buffer.release()
        self._prefix_scanned = 0
        self._started_at = None


class _PendingRun:
    """A coalesced run of pending stream bytes, growable at either edge.

    Bytes live in a single ``bytearray`` with tracked front slack (``_head``) so a
    reverse-adjacent fragment prepends without recopying the whole run on every
    insert, while forward growth uses ``bytearray``'s amortized append. Both edges
    are therefore amortized O(1); transient slack is bounded by the run length, so
    pending memory stays within the charged budget.
    """

    __slots__ = ("start", "_buffer", "_head")

    def __init__(self, start: int, data: Buffer) -> None:
        self.start = start
        self._buffer = bytearray(data)
        self._head = 0

    def __len__(self) -> int:
        return len(self._buffer) - self._head

    @property
    def end(self) -> int:
        return self.start + len(self)

    def to_bytes(self, begin: int = 0, stop: int | None = None) -> bytes:
        length = len(self)
        stop = length if stop is None else stop
        return bytes(self._buffer[self._head + begin : self._head + stop])

    def append(self, data: Buffer) -> None:
        self._buffer += bytes(data)

    def reserve_prepend(self, need: int) -> None:
        if self._head >= need:
            return
        length = len(self)
        reserve = need + length
        grown = bytearray(reserve + length)
        grown[reserve:] = self._buffer[self._head :]
        self._buffer = grown
        self._head = reserve

    def prepend(self, start: int, data: Buffer) -> None:
        chunk = bytes(data)
        need = len(chunk)
        self.reserve_prepend(need)
        self._head -= need
        self._buffer[self._head : self._head + need] = chunk
        self.start = start


def _pending_run_start(run: _PendingRun) -> int:
    return run.start


def _pending_run_end(run: _PendingRun) -> int:
    return run.end


class TCPStreamReassembler:
    """Bounded sequence window with complete byte-overlap validation."""

    def __init__(
        self,
        policy: ParserPolicy | None = None,
        budget: _MemoryBudget | None = None,
    ) -> None:
        self.policy = policy or ParserPolicy()
        self._budget = budget or _MemoryBudget(
            self.policy.maximum_aggregate_memory_bytes
        )
        self._origin: int | None = None
        self._assembled_bytes = 0
        self._history_start = 0
        self._history_limit = min(
            self.policy.maximum_packet_bytes,
            self.policy.maximum_reassembled_bytes_per_flow,
            16 * 1024,
        )
        self._history = _ChargedRingBuffer(self._history_limit, self._budget)
        self._pending: list[_PendingRun] | None = None
        self._pending_bytes = 0
        self._segment_count = 0
        self._started_at: float | None = None
        self._emitted_started_at: float | None = None
        self._last_captured_at: float | None = None

    @property
    def pending_bytes(self) -> int:
        return self._pending_bytes

    @property
    def retained_bytes(self) -> int:
        return self._history.allocated_bytes + self.pending_bytes

    @property
    def segment_count(self) -> int:
        return self._segment_count

    @property
    def emitted_started_at(self) -> float | None:
        return self._emitted_started_at

    def start(self, sequence: int) -> None:
        if self._origin is not None or not 0 <= sequence < _SEQUENCE_MODULUS:
            raise CaptureError(FailureReason.MALFORMED)
        self._origin = sequence

    def _offset(self, sequence: int) -> int:
        if self._origin is None:
            raise CaptureError(FailureReason.TRUNCATED)
        if not 0 <= sequence < _SEQUENCE_MODULUS:
            raise CaptureError(FailureReason.MALFORMED)
        delta = (sequence - self._origin) % _SEQUENCE_MODULUS
        return delta - _SEQUENCE_MODULUS if delta >= _SEQUENCE_HALF else delta

    def push(
        self, sequence: int, payload: Buffer, *, captured_at: float
    ) -> list[tuple[float, bytes]]:
        self._validate_timestamp(captured_at)
        self._emitted_started_at = None
        normalized = bytes(payload)
        if not normalized:
            return []
        if len(normalized) > self._budget.limit - self._budget.retained:
            raise CaptureError(FailureReason.CAPACITY)
        if self._started_at is None:
            self._started_at = captured_at
        elif captured_at - self._started_at > self.policy.overall_frame_deadline:
            self._clear()
            raise CaptureError(FailureReason.TIMEOUT)
        self._segment_count += 1
        if self._segment_count > self.policy.maximum_segments_per_flow:
            raise CaptureError(FailureReason.CAPACITY)
        start = self._offset(sequence)
        end = start + len(normalized)
        if start < self._history_start:
            raise CaptureError(FailureReason.MALFORMED)
        if end > self.policy.maximum_reassembled_bytes_per_flow:
            raise CaptureError(FailureReason.CAPACITY)
        assembled_overlap_end = min(end, self._assembled_bytes)
        if (
            start < assembled_overlap_end
            and self._history.to_bytes(
                start - self._history_start, assembled_overlap_end - start
            )
            != normalized[: assembled_overlap_end - start]
        ):
            raise CaptureError(FailureReason.MALFORMED)

        unassembled_start = max(start, self._assembled_bytes)
        unassembled = normalized[unassembled_start - start :]
        # Runs are sorted and non-overlapping, so both ``start`` and ``end`` rise
        # monotonically; bisect the touched window instead of scanning from zero so
        # sparse out-of-order fragments cost O(log runs), not O(runs), per insert.
        pending = self._pending
        if pending is None:
            first_run = last_run = 0
            touched: list[_PendingRun] = []
        else:
            first_run = bisect.bisect_left(
                pending, unassembled_start, key=_pending_run_end
            )
            last_run = bisect.bisect_right(pending, end, key=_pending_run_start)
            touched = pending[first_run:last_run]
        overlap_bytes = 0
        for run in touched:
            overlap_start = max(unassembled_start, run.start)
            overlap_end = min(end, run.end)
            if overlap_start < overlap_end:
                run_overlap = run.to_bytes(
                    overlap_start - run.start, overlap_end - run.start
                )
                segment_overlap = unassembled[
                    overlap_start - unassembled_start : overlap_end - unassembled_start
                ]
                if run_overlap != segment_overlap:
                    raise CaptureError(FailureReason.MALFORMED)
                overlap_bytes += overlap_end - overlap_start
        new_bytes = len(unassembled) - overlap_bytes
        if start > self._assembled_bytes and (
            start - self._assembled_bytes > self.policy.maximum_pending_bytes_per_flow
            or self.pending_bytes + new_bytes
            > self.policy.maximum_pending_bytes_per_flow
        ):
            raise CaptureError(FailureReason.CAPACITY)
        contiguous = bytearray()
        if start > self._assembled_bytes:
            if new_bytes:
                self._budget.reserve(new_bytes * _PENDING_BYTE_MEMORY_CHARGE)
                if pending is None:
                    pending = []
                run_snapshot: tuple[_PendingRun, bytearray, int, int] | None = None
                try:
                    if first_run == last_run:
                        # Isolated gap fragment: a brand-new run.
                        pending.insert(
                            first_run, _PendingRun(unassembled_start, unassembled)
                        )
                    else:
                        # Retain the leftmost touched run and append only bytes not
                        # already stored there. Preflight front growth before the
                        # append so a failed prepend allocation cannot leave an
                        # uncharged suffix behind.
                        run = pending[first_run]
                        run_start = run.start
                        run_end = run.end
                        run_snapshot = (run, run._buffer, run._head, run_start)
                        prefix = unassembled[: max(0, run_start - unassembled_start)]
                        if last_run - first_run == 1:
                            suffix = unassembled[max(0, run_end - unassembled_start) :]
                        else:
                            tail = bytearray()
                            cursor = run_end
                            for subsequent in pending[first_run + 1 : last_run]:
                                segment_end = min(subsequent.start, end)
                                if cursor < segment_end:
                                    tail += unassembled[
                                        cursor - unassembled_start : segment_end
                                        - unassembled_start
                                    ]
                                    cursor = segment_end
                                if cursor < subsequent.end:
                                    tail += subsequent.to_bytes(
                                        max(0, cursor - subsequent.start)
                                    )
                                    cursor = subsequent.end
                            if cursor < end:
                                tail += unassembled[cursor - unassembled_start :]
                            suffix = bytes(tail)
                        run.reserve_prepend(len(prefix))
                        if suffix:
                            run.append(suffix)
                        if unassembled_start < run_start:
                            run.prepend(unassembled_start, prefix)
                        del pending[first_run + 1 : last_run]
                except MemoryError:
                    if run_snapshot is not None:
                        run, run._buffer, run._head, run.start = run_snapshot
                    self._budget.release(new_bytes * _PENDING_BYTE_MEMORY_CHARGE)
                    raise CaptureError(FailureReason.CAPACITY) from None
                self._pending = pending
                self._pending_bytes += new_bytes
        else:
            contiguous.extend(unassembled)
            contiguous_end = self._assembled_bytes + len(contiguous)
            consumed_runs = 0
            consumed_bytes = 0
            while pending is not None and consumed_runs < len(pending):
                run = pending[consumed_runs]
                if run.start > contiguous_end:
                    break
                suffix_start = min(len(run), max(0, contiguous_end - run.start))
                contiguous.extend(run.to_bytes(suffix_start))
                contiguous_end += len(run) - suffix_start
                consumed_bytes += len(run)
                consumed_runs += 1
            self._assembled_bytes = contiguous_end
            if consumed_runs:
                assert pending is not None
                del pending[:consumed_runs]
                self._pending_bytes -= consumed_bytes
                self._budget.release(consumed_bytes * (_PENDING_BYTE_MEMORY_CHARGE - 1))
                if not pending:
                    self._pending = None
        expired = max(0, len(self._history) + len(contiguous) - self._history_limit)
        contiguous_history_start = 0
        if expired > 0:
            from_history = min(expired, len(self._history))
            self._history.discard(from_history)
            if expired > from_history:
                contiguous_history_start = expired - from_history
            self._history_start += expired
        self._history.append(memoryview(contiguous)[contiguous_history_start:])
        chunks: list[tuple[float, bytes]] = []
        if contiguous:
            assert self._started_at is not None
            self._emitted_started_at = self._started_at
            chunks.append((captured_at, bytes(contiguous)))
        if self._pending is None:
            self._started_at = None
        return chunks

    def close(self) -> None:
        has_gap = self._pending is not None
        self._clear()
        if has_gap:
            raise CaptureError(FailureReason.TRUNCATED)

    def _validate_timestamp(self, captured_at: float) -> None:
        if not _is_finite_number(captured_at) or (
            self._last_captured_at is not None and captured_at < self._last_captured_at
        ):
            raise CaptureError(FailureReason.MALFORMED)
        self._last_captured_at = captured_at

    def _clear(self) -> None:
        retained = self.pending_bytes * _PENDING_BYTE_MEMORY_CHARGE
        self._pending = None
        self._pending_bytes = 0
        self._history.release()
        self._budget.release(retained)
        self._started_at = None


@dataclass(frozen=True, slots=True)
class CapturedSegment:
    direction: str
    sequence: int
    captured_at: float
    payload: bytes
    stream_id: int = 0
    starts_stream: bool = False


@dataclass(slots=True)
class _DirectionState:
    reassembler: TCPStreamReassembler
    decoder: StreamFrameDecoder


@dataclass(slots=True)
class _SessionState:
    directions: dict[str, _DirectionState] = field(default_factory=dict)
    outer_identity: bytes | None = None
    inner_identity: bytes | None = None


def find_frames(data: bytes) -> list[tuple[int, bytes]]:
    decoder = StreamFrameDecoder()
    frames = decoder.feed(data, captured_at=0.0)
    decoder.close(captured_at=0.0)
    result: list[tuple[int, bytes]] = []
    offset = 0
    for frame in frames:
        offset = data.find(frame, offset)
        result.append((offset, frame))
        offset += len(frame)
    return result


def _validated_identity(raw: bytes) -> bytes:
    if len(raw) != 10 or not all(
        48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 for byte in raw
    ):
        raise CaptureError(FailureReason.IDENTITY)
    return raw


def _bind_identity(current: bytes | None, candidate: bytes) -> bytes:
    validated = _validated_identity(candidate)
    if current is not None and current != validated:
        raise CaptureError(FailureReason.IDENTITY)
    return validated


def _validate_crc(frame: bytes) -> None:
    if len(frame) < 3:
        raise CaptureError(FailureReason.MALFORMED)
    if int.from_bytes(frame[-2:], "little") != compute_crc16(frame[:-2]):
        raise CaptureError(FailureReason.CRC)


def _alias(identity: bytes, identities: dict[bytes, str], prefix: str) -> str:
    existing = identities.get(identity)
    if existing is not None:
        return existing
    if len(identities) >= 999:
        raise CaptureError(FailureReason.CAPACITY)
    alias = f"{prefix}{len(identities) + 1:03d}"
    identities[identity] = alias
    return alias


def _inner_function_name(function: int) -> str:
    return "read_holding" if function == 0x03 else "read_input"


def _sanitize_frame(
    frame: bytes,
    direction: str,
    session: _SessionState,
    dongle_identities: dict[bytes, str],
    inverter_identities: dict[bytes, str],
) -> dict[str, Any]:
    if len(frame) < 19 or 6 + int.from_bytes(frame[4:6], "little") != len(frame):
        raise CaptureError(FailureReason.MALFORMED)
    # Phase A1 capture evidence contains only protocol version 0x0001
    # (little-endian on the wire, so bytes 01 00) and address 1. Unknown
    # variants are rejected rather than redacted into a known-looking record.
    if frame[2:4] != b"\x01\x00" or frame[6] != 1:
        raise CaptureError(FailureReason.PROTOCOL)
    session.outer_identity = _bind_identity(session.outer_identity, frame[8:18])
    base: dict[str, Any] = {
        "direction": direction,
        "identity": _alias(session.outer_identity, dongle_identities, "SYNTHDG"),
    }
    function = frame[7]
    payload = frame[18:]
    if function == 0xC1:
        # The captured heartbeat shape is exactly one status byte. Appended
        # fields are not evidenced and must not be silently masked.
        if len(payload) != 1:
            raise CaptureError(FailureReason.PROTOCOL)
        return base | {"function": "heartbeat", "payload": "SYNTHETIC_STATUS"}
    if function != 0xC2 or len(payload) < 2:
        raise CaptureError(
            FailureReason.FUNCTION if function != 0xC2 else FailureReason.MALFORMED
        )
    inner_size = int.from_bytes(payload[:2], "little")
    inner = payload[2:]
    if inner_size != len(inner) or len(inner) < 17:
        raise CaptureError(FailureReason.MALFORMED)
    inner_function = inner[1]
    if inner_function not in (0x03, 0x04):
        raise CaptureError(FailureReason.FUNCTION)
    if inner[0] != frame[6]:
        raise CaptureError(FailureReason.IDENTITY)
    session.inner_identity = _bind_identity(session.inner_identity, inner[2:12])
    inner_alias = _alias(session.inner_identity, inverter_identities, "SYNTHIV")
    start_register = int.from_bytes(inner[12:14], "little")
    if len(inner) == 18:
        register_count = int.from_bytes(inner[14:16], "little")
        if register_count < 1 or start_register + register_count > 65536:
            raise CaptureError(FailureReason.RANGE)
        _validate_crc(inner)
        return base | {
            "function": "data_read_request",
            "inner_identity": inner_alias,
            "inner_function": _inner_function_name(inner_function),
            "start_register": start_register,
            "register_count": register_count,
            "register_words": [],
        }
    byte_count = inner[14]
    if byte_count < 2 or byte_count % 2 or len(inner) != 17 + byte_count:
        raise CaptureError(FailureReason.RANGE)
    register_count = byte_count // 2
    if start_register + register_count > 65536:
        raise CaptureError(FailureReason.RANGE)
    _validate_crc(inner)
    return base | {
        "function": "data_read_response",
        "inner_identity": inner_alias,
        "inner_function": _inner_function_name(inner_function),
        "start_register": start_register,
        "register_count": register_count,
        "register_words": [SYNTHETIC_REGISTER_WORD],
    }


def sanitize_segments(
    segments: Iterable[CapturedSegment], policy: ParserPolicy | None = None
) -> dict[str, Any]:
    active_policy = policy or ParserPolicy()
    budget = _MemoryBudget(active_policy.maximum_aggregate_memory_bytes)
    sessions: dict[int, _SessionState] = {}
    records: list[dict[str, Any]] = []
    record_keys: set[str] = set()
    dongle_identities: dict[bytes, str] = {}
    inverter_identities: dict[bytes, str] = {}
    last_timestamp: dict[tuple[int, str], float] = {}
    capture_timestamp: float | None = None
    for segment in segments:
        if not _is_finite_number(segment.captured_at) or (
            capture_timestamp is not None and segment.captured_at < capture_timestamp
        ):
            raise CaptureError(FailureReason.MALFORMED)
        capture_timestamp = segment.captured_at
        if segment.direction not in ("dongle_to_cloud", "cloud_to_dongle"):
            raise CaptureError(FailureReason.MALFORMED)
        session = sessions.get(segment.stream_id)
        if session is None:
            if len(sessions) >= active_policy.maximum_flows:
                raise CaptureError(FailureReason.CAPACITY)
            session = _SessionState()
            sessions[segment.stream_id] = session
        state = session.directions.get(segment.direction)
        if state is None:
            state = _DirectionState(
                TCPStreamReassembler(active_policy, budget),
                StreamFrameDecoder(active_policy, budget),
            )
            session.directions[segment.direction] = state
        if segment.starts_stream:
            state.reassembler.start(segment.sequence)
        last_timestamp[(segment.stream_id, segment.direction)] = segment.captured_at
        for _captured_at, chunk in state.reassembler.push(
            segment.sequence, segment.payload, captured_at=segment.captured_at
        ):
            decoder_timestamp = state.reassembler.emitted_started_at
            assert decoder_timestamp is not None
            for frame in state.decoder.feed(
                chunk,
                captured_at=decoder_timestamp,
                observed_at=segment.captured_at,
            ):
                record = _sanitize_frame(
                    frame,
                    segment.direction,
                    session,
                    dongle_identities,
                    inverter_identities,
                )
                key = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if key in record_keys:
                    continue
                if len(records) >= MAX_SANITIZED_RECORDS:
                    raise CaptureError(FailureReason.CAPACITY)
                record_keys.add(key)
                records.append(record)
    for stream_id, session in sessions.items():
        for direction, state in session.directions.items():
            state.reassembler.close()
            state.decoder.close(captured_at=last_timestamp[(stream_id, direction)])
    if not records:
        raise CaptureError(FailureReason.EMPTY)
    result: dict[str, Any] = {
        "schema_version": 1,
        "capture": {
            "source": "authorized_offline_input",
            "dongle_address": DOCUMENTATION_DONGLE_ADDRESS,
            "cloud_address": DOCUMENTATION_CLOUD_ADDRESS,
        },
        "frames": records,
    }
    _validate_synthetic_output(result)
    return result


def _exact_keys(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise CaptureError(FailureReason.SCHEMA)
    return cast(dict[str, Any], value)


def _validate_synthetic_output(value: object) -> None:
    root = _exact_keys(value, {"schema_version", "capture", "frames"})
    if root["schema_version"] != 1 or not isinstance(root["frames"], list):
        raise CaptureError(FailureReason.SCHEMA)
    capture = _exact_keys(
        root["capture"], {"source", "dongle_address", "cloud_address"}
    )
    if capture != {
        "source": "authorized_offline_input",
        "dongle_address": DOCUMENTATION_DONGLE_ADDRESS,
        "cloud_address": DOCUMENTATION_CLOUD_ADDRESS,
    }:
        raise CaptureError(FailureReason.SCHEMA)
    for raw_frame in root["frames"]:
        frame = cast(dict[str, Any], raw_frame) if isinstance(raw_frame, dict) else {}
        function = frame.get("function")
        common = {"direction", "identity", "function"}
        expected = common | (
            {"payload"}
            if function == "heartbeat"
            else {
                "inner_identity",
                "inner_function",
                "start_register",
                "register_count",
                "register_words",
            }
        )
        frame = _exact_keys(raw_frame, expected)
        if frame["direction"] not in ("dongle_to_cloud", "cloud_to_dongle"):
            raise CaptureError(FailureReason.SCHEMA)
        identity = frame["identity"]
        if not isinstance(identity, str) or _DONGLE_ALIAS.fullmatch(identity) is None:
            raise CaptureError(FailureReason.SCHEMA)
        if function == "heartbeat":
            if frame["payload"] != "SYNTHETIC_STATUS":
                raise CaptureError(FailureReason.SCHEMA)
            continue
        if function not in ("data_read_request", "data_read_response"):
            raise CaptureError(FailureReason.SCHEMA)
        inner_identity = frame["inner_identity"]
        if (
            not isinstance(inner_identity, str)
            or _INVERTER_ALIAS.fullmatch(inner_identity) is None
            or frame["inner_function"] not in ("read_holding", "read_input")
        ):
            raise CaptureError(FailureReason.SCHEMA)
        start = frame["start_register"]
        count = frame["register_count"]
        words = frame["register_words"]
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or start < 0
            or start + count > 65536
            or not isinstance(words, list)
            or words not in ([], [SYNTHETIC_REGISTER_WORD])
            or (function == "data_read_request" and words)
            or (function == "data_read_response" and not words)
        ):
            raise CaptureError(FailureReason.SCHEMA)


def _stat_signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _read_stable_capture(path: Path, policy: ParserPolicy) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    with suppress(OSError):
        descriptor = os.open(path, flags)
    if descriptor is None:
        raise CaptureError(FailureReason.INPUT_KIND)
    failure: FailureReason | None = None
    capture: bytes | None = None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CaptureError(FailureReason.INPUT_KIND)
        if before.st_size > policy.maximum_capture_bytes:
            raise CaptureError(FailureReason.INPUT_SIZE)
        chunks: list[bytes] = []
        remaining = policy.maximum_capture_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        capture = b"".join(chunks)
        after = os.fstat(descriptor)
        by_name = os.stat(path, follow_symlinks=False)
        if len(capture) > policy.maximum_capture_bytes:
            raise CaptureError(FailureReason.INPUT_SIZE)
        if (
            len(capture) != before.st_size
            or _stat_signature(before) != _stat_signature(after)
            or _stat_signature(after) != _stat_signature(by_name)
        ):
            raise CaptureError(FailureReason.INPUT_CHANGED)
    except CaptureError as error:
        failure = error.reason
    except OSError:
        failure = FailureReason.INPUT_CHANGED
    try:
        os.close(descriptor)
    except OSError:
        if failure is None:
            failure = FailureReason.INPUT_CHANGED
    if failure is not None:
        raise CaptureError(failure)
    assert capture is not None
    return capture


def _decode_link_packet(packet: bytes, link_type: int) -> _IPPacket | None:
    module = dpkt
    if module is None:
        raise CaptureError(FailureReason.DEPENDENCY)
    factories: dict[int, _PacketFactory] = {
        module.pcap.DLT_EN10MB: module.ethernet.Ethernet,
        module.pcap.DLT_LINUX_SLL: module.sll.SLL,
        module.pcap.DLT_LINUX_SLL2: module.sll2.SLL2,
    }
    factory = factories.get(link_type)
    if factory is None:
        raise CaptureError(FailureReason.UNSUPPORTED_LINK)
    link_packet: _LinkPacket | None = None
    with suppress(Exception):
        link_packet = factory(packet)
    if link_packet is None:
        raise CaptureError(FailureReason.MALFORMED)
    data = link_packet.data
    if isinstance(data, module.ip.IP):
        return cast(_IPPacket, data)
    if isinstance(data, module.ip6.IP6):
        ip_packet = cast(_IPPacket, data)
        transport_data = ip_packet.data
        ports: tuple[int, int] | None = None
        if isinstance(transport_data, module.tcp.TCP):
            transport = cast(_TCPPacket, transport_data)
            ports = transport.sport, transport.dport
        elif ip_packet.p == module.ip.IP_PROTO_TCP and isinstance(
            transport_data, Buffer
        ):
            prefix = memoryview(transport_data)
            if len(prefix) >= 4:
                ports = int.from_bytes(prefix[:2]), int.from_bytes(prefix[2:4])
        if ports is not None and 4346 in ports:
            raise CaptureError(FailureReason.IP_VERSION)
    return None


@dataclass(slots=True)
class _ObservedSession:
    stream_id: int
    client_initial_sequence: int
    client_handshake: tuple[int, int, bytes, bytes]
    server_initial_sequence: int | None = None
    server_handshake: tuple[int, int, bytes, bytes] | None = None
    application_started: bool = False
    client_terminal: tuple[int, int, int, bytes, bytes] | None = None
    server_terminal: tuple[int, int, int, bytes, bytes] | None = None
    reset_terminal: tuple[bool, int, int, int, bytes, bytes] | None = None


def _pcap_segments(capture: bytes, policy: ParserPolicy) -> Iterable[CapturedSegment]:
    module = dpkt
    if module is None:
        raise CaptureError(FailureReason.DEPENDENCY)
    reader: _CaptureReader | None = None
    link_type: int | None = None
    try:
        reader = module.pcap.UniversalReader(io.BytesIO(capture))
        link_type = reader.datalink()
    except Exception:
        pass
    if reader is None or link_type is None:
        raise CaptureError(FailureReason.MALFORMED)
    supported = {
        module.pcap.DLT_EN10MB,
        module.pcap.DLT_LINUX_SLL,
        module.pcap.DLT_LINUX_SLL2,
    }
    if link_type not in supported:
        raise CaptureError(FailureReason.UNSUPPORTED_LINK)
    sessions: dict[tuple[bytes, int, bytes, int], _ObservedSession] = {}
    next_stream_id = 0
    packet_count = 0
    last_timestamp: float | None = None
    raw_failure = False
    try:
        for timestamp, raw_packet in reader:
            captured_at = float(timestamp)
            if not math.isfinite(captured_at) or (
                last_timestamp is not None and captured_at < last_timestamp
            ):
                raise CaptureError(FailureReason.MALFORMED)
            last_timestamp = captured_at
            packet_count += 1
            if packet_count > policy.maximum_packets:
                raise CaptureError(FailureReason.CAPACITY)
            packet = bytes(raw_packet)
            if len(packet) > policy.maximum_packet_bytes:
                raise CaptureError(FailureReason.CAPACITY)
            ip_packet = _decode_link_packet(packet, link_type)
            if ip_packet is None:
                continue
            if ip_packet.p != module.ip.IP_PROTO_TCP:
                continue
            if not isinstance(ip_packet.data, module.tcp.TCP):
                raise CaptureError(FailureReason.MALFORMED)
            tcp = cast(_TCPPacket, ip_packet.data)
            if tcp.dport == 4346:
                direction = "dongle_to_cloud"
                key = (bytes(ip_packet.src), tcp.sport, bytes(ip_packet.dst), tcp.dport)
                client_side = True
            elif tcp.sport == 4346:
                direction = "cloud_to_dongle"
                key = (bytes(ip_packet.dst), tcp.dport, bytes(ip_packet.src), tcp.sport)
                client_side = False
            else:
                continue
            syn = bool(tcp.flags & module.tcp.TH_SYN)
            ack = bool(tcp.flags & module.tcp.TH_ACK)
            session = sessions.get(key)
            starts_stream = False
            sequence = tcp.seq
            payload = bytes(tcp.data)
            options = bytes(tcp.opts)
            handshake = (tcp.flags, tcp.ack, options, payload)
            has_terminal_flag = bool(
                tcp.flags & (module.tcp.TH_FIN | module.tcp.TH_RST)
            )
            if client_side and syn and not ack:
                if session is not None and sequence == session.client_initial_sequence:
                    if handshake != session.client_handshake:
                        raise CaptureError(FailureReason.MALFORMED)
                    continue
                if tcp.ack or payload or has_terminal_flag:
                    raise CaptureError(FailureReason.MALFORMED)
                if session is not None and not session.application_started:
                    raise CaptureError(FailureReason.MALFORMED)
                session = _ObservedSession(next_stream_id, sequence, handshake)
                sessions[key] = session
                next_stream_id += 1
                starts_stream = True
                sequence = (sequence + 1) % _SEQUENCE_MODULUS
            elif not client_side and syn and ack and session is not None:
                if session.server_initial_sequence == sequence:
                    if handshake != session.server_handshake:
                        raise CaptureError(FailureReason.MALFORMED)
                    continue
                if (
                    tcp.ack != (session.client_initial_sequence + 1) % _SEQUENCE_MODULUS
                    or payload
                    or has_terminal_flag
                ):
                    raise CaptureError(FailureReason.MALFORMED)
                if session.server_initial_sequence is not None:
                    raise CaptureError(FailureReason.MALFORMED)
                session.server_initial_sequence = sequence
                session.server_handshake = handshake
                starts_stream = True
                sequence = (sequence + 1) % _SEQUENCE_MODULUS
            elif session is None or (
                not client_side and session.server_initial_sequence is None
            ):
                raise CaptureError(FailureReason.TRUNCATED)
            assert session is not None
            if syn and not starts_stream:
                raise CaptureError(FailureReason.MALFORMED)
            terminal = (sequence, tcp.ack, tcp.flags, options, payload)
            reset_terminal = (client_side, *terminal)
            if session.reset_terminal is not None:
                if reset_terminal == session.reset_terminal:
                    continue
                if payload or has_terminal_flag:
                    raise CaptureError(FailureReason.MALFORMED)
                continue
            direction_terminal = (
                session.client_terminal if client_side else session.server_terminal
            )
            if direction_terminal is not None:
                if terminal == direction_terminal:
                    continue
                if payload or has_terminal_flag:
                    raise CaptureError(FailureReason.MALFORMED)
                continue
            if (payload or has_terminal_flag) and not ack:
                raise CaptureError(FailureReason.MALFORMED)
            if tcp.flags & module.tcp.TH_RST:
                session.reset_terminal = reset_terminal
            elif tcp.flags & module.tcp.TH_FIN:
                if client_side:
                    session.client_terminal = terminal
                else:
                    session.server_terminal = terminal
            if payload:
                session.application_started = True
            if starts_stream or payload:
                yield CapturedSegment(
                    direction,
                    sequence,
                    captured_at,
                    payload,
                    session.stream_id,
                    starts_stream,
                )
    except CaptureError:
        raise
    except Exception:
        raw_failure = True
    if raw_failure:
        raise CaptureError(FailureReason.MALFORMED)


def process_pcap(
    pcap_path: str | Path, policy: ParserPolicy | None = None
) -> dict[str, Any]:
    active_policy = policy or ParserPolicy()
    capture = _read_stable_capture(Path(pcap_path), active_policy)
    return sanitize_segments(_pcap_segments(capture, active_policy), active_policy)


class _ArgumentParseFailure(Exception):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _ArgumentParseFailure


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _RedactedArgumentParser(
        description="Create a synthetic fixture from an authorized offline capture."
    )
    parser.add_argument("input", type=Path, help="authorized offline PCAP or PCAPNG")
    parser.add_argument(
        "--output", required=True, type=Path, help="new JSON output path"
    )
    parser.add_argument(
        "--authorized-offline-input",
        action="store_true",
        required=True,
        help="confirm authorization and offline-only handling",
    )
    try:
        return parser.parse_args(argv)
    except _ArgumentParseFailure:
        pass
    raise CaptureError(FailureReason.CLI)


def _serialize_output(value: object) -> bytes:
    _validate_synthetic_output(value)
    return (json.dumps(value, indent=2) + "\n").encode()


def _open_temporary(directory_descriptor: int) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(16):
        name = f".decode-cloud-frames-{secrets.token_hex(16)}.tmp"
        try:
            return os.open(name, flags, 0o600, dir_fd=directory_descriptor), name
        except FileExistsError:
            continue
        except OSError:
            break
    else:
        raise CaptureError(FailureReason.CAPACITY)
    raise CaptureError(FailureReason.OUTPUT)


def _unlink_if_same(
    directory_descriptor: int,
    name: str,
    identity: tuple[int, int],
) -> None:
    with suppress(OSError):
        current = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) == identity:
            os.unlink(name, dir_fd=directory_descriptor)


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    directory_descriptor: int | None = None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    published = False
    failure: FailureReason | None = None
    try:
        if (
            not path.name
            or not _ATOMIC_DIR_FD_SUPPORTED
            or not hasattr(os, "O_DIRECTORY")
        ):
            raise CaptureError(FailureReason.OUTPUT)
        directory_flags = (
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_descriptor = os.open(path.parent, directory_flags)
        directory_stat = os.fstat(directory_descriptor)
        # Cleanup uses inode validation followed by unlink relative to this fd.
        # Exclude directories writable by other principals so that validation
        # and cleanup cannot race an untrusted replacement entry.
        if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_mode & (
            stat.S_IWGRP | stat.S_IWOTH
        ):
            raise CaptureError(FailureReason.OUTPUT)
        descriptor, temporary_name = _open_temporary(directory_descriptor)
        opened = os.fstat(descriptor)
        temporary_identity = (opened.st_dev, opened.st_ino)
        if stat.S_IMODE(opened.st_mode) != 0o600:
            raise CaptureError(FailureReason.OUTPUT)
        written = 0
        while written < len(content):
            count = os.write(descriptor, memoryview(content)[written:])
            if count <= 0:
                raise CaptureError(FailureReason.OUTPUT)
            written += count
        os.fsync(descriptor)
        closing_descriptor = descriptor
        descriptor = None
        os.close(closing_descriptor)
        os.link(
            temporary_name,
            path.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        published = True
        os.unlink(temporary_name, dir_fd=directory_descriptor)
        temporary_name = None
        os.fsync(directory_descriptor)
        closing_directory_descriptor = directory_descriptor
        directory_descriptor = None
        with suppress(OSError):
            os.close(closing_directory_descriptor)
    except FileExistsError:
        failure = FailureReason.OUTPUT_EXISTS
    except CaptureError as error:
        failure = error.reason
    except OSError:
        failure = FailureReason.OUTPUT

    if descriptor is not None:
        closing_descriptor = descriptor
        descriptor = None
        try:
            os.close(closing_descriptor)
        except OSError:
            if failure is None:
                failure = FailureReason.OUTPUT
    if failure is not None:
        if (
            published
            and temporary_identity is not None
            and directory_descriptor is not None
        ):
            _unlink_if_same(directory_descriptor, path.name, temporary_identity)
        if (
            temporary_name is not None
            and temporary_identity is not None
            and directory_descriptor is not None
        ):
            _unlink_if_same(directory_descriptor, temporary_name, temporary_identity)
        if directory_descriptor is not None:
            with suppress(OSError):
                os.fsync(directory_descriptor)
    if directory_descriptor is not None:
        closing_directory_descriptor = directory_descriptor
        directory_descriptor = None
        try:
            os.close(closing_directory_descriptor)
        except OSError:
            if failure is None:
                failure = FailureReason.OUTPUT
    if failure is not None:
        raise CaptureError(failure)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parse_args(argv)
        sanitized = process_pcap(arguments.input)
        serialized = _serialize_output(sanitized)
        _write_exclusive(arguments.output, serialized)
    except CaptureError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"synthetic fixture written: {len(sanitized['frames'])} frame classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
