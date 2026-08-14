#!/usr/bin/env python3
"""Create a synthetic protocol fixture from an authorized offline capture."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Buffer, Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO, Final, Protocol, cast


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
    tcp: _TCPNamespace


def _load_dpkt() -> _DPKT | None:
    try:
        module = import_module("dpkt")
    except ImportError:
        return None
    return cast(_DPKT, cast(ModuleType, module))


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
_DONGLE_ALIAS = re.compile(r"SYNTHDG[0-9]{3}\Z")
_INVERTER_ALIAS = re.compile(r"SYNTHIV[0-9]{3}\Z")


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _sequence_advances(sequence: int, boundary: int) -> bool:
    delta = (sequence - boundary) % _SEQUENCE_MODULUS
    return 0 < delta < _SEQUENCE_HALF


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
    CRC = "crc"
    DEPENDENCY = "dependency"
    EMPTY = "empty"
    FUNCTION = "function"
    IDENTITY = "identity"
    INPUT_CHANGED = "input_changed"
    INPUT_KIND = "input_kind"
    INPUT_SIZE = "input_size"
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
        self._buffer = b""
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
            self._budget.reserve(take)
            self._buffer += normalized[offset : offset + take]
            offset += take
            decoded.extend(self._extract_available(captured_at))
        decoded.extend(self._extract_available(captured_at))
        return decoded

    def close(self, *, captured_at: float) -> None:
        self._validate_timestamp(captured_at)
        self._check_deadline(captured_at)
        self._extract_available(captured_at)
        if self._buffer or self._prefix_scanned:
            self._discard()
            raise CaptureError(FailureReason.TRUNCATED)

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
            self._buffer = self._buffer[count:]
            self._budget.release(count)

    def _extract_available(self, captured_at: float) -> list[bytes]:
        frames: list[bytes] = []
        while self._buffer:
            magic_index = self._buffer.find(FRAME_MAGIC)
            if magic_index < 0:
                retained = int(self._buffer[-1:] == FRAME_MAGIC[:1])
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
            total_size = 6 + int.from_bytes(self._buffer[4:6], "little")
            if total_size > self.policy.maximum_frame_bytes:
                self._discard()
                raise CaptureError(FailureReason.OVERSIZE)
            if total_size < 19:
                self._discard()
                raise CaptureError(FailureReason.MALFORMED)
            if len(self._buffer) < total_size:
                break
            frames.append(bytes(self._buffer[:total_size]))
            self._remove_prefix(total_size)
            self._prefix_scanned = 0
            self._started_at = captured_at if self._buffer else None
        return frames

    def _discard(self) -> None:
        self._budget.release(len(self._buffer))
        self._buffer = b""
        self._prefix_scanned = 0
        self._started_at = None


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
        self._history = b""
        self._pending: dict[int, int] | None = None
        self._segment_count = 0
        self._started_at: float | None = None
        self._emitted_started_at: float | None = None
        self._last_captured_at: float | None = None

    @property
    def pending_bytes(self) -> int:
        return len(self._pending) if self._pending is not None else 0

    @property
    def retained_bytes(self) -> int:
        return len(self._history) + self.pending_bytes

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
        pending = self._pending
        new_bytes = 0
        for index, byte in enumerate(normalized):
            offset = start + index
            if offset < self._assembled_bytes:
                if self._history[offset - self._history_start] != byte:
                    raise CaptureError(FailureReason.MALFORMED)
                continue
            existing = pending.get(offset) if pending is not None else None
            if existing is not None:
                if existing != byte:
                    raise CaptureError(FailureReason.MALFORMED)
                continue
            new_bytes += 1
        if start > self._assembled_bytes and (
            start - self._assembled_bytes > self.policy.maximum_pending_bytes_per_flow
            or self.pending_bytes + new_bytes
            > self.policy.maximum_pending_bytes_per_flow
        ):
            raise CaptureError(FailureReason.CAPACITY)
        contiguous = bytearray()
        if start > self._assembled_bytes:
            self._budget.reserve(new_bytes)
            if new_bytes:
                if pending is None:
                    pending = {}
                for index, byte in enumerate(normalized):
                    offset = start + index
                    if offset not in pending:
                        pending[offset] = byte
                self._pending = pending
        else:
            self._budget.reserve(new_bytes)
            while self._assembled_bytes < end:
                pending_byte = (
                    pending.pop(self._assembled_bytes)
                    if pending is not None and self._assembled_bytes in pending
                    else None
                )
                if pending_byte is None:
                    byte = normalized[self._assembled_bytes - start]
                else:
                    byte = pending_byte
                contiguous.append(byte)
                self._assembled_bytes += 1
            while pending is not None and self._assembled_bytes in pending:
                byte = pending.pop(self._assembled_bytes)
                contiguous.append(byte)
                self._assembled_bytes += 1
            if pending is not None and not pending:
                self._pending = None
                pending = None
        overlap_limit = min(
            self.policy.maximum_packet_bytes,
            self.policy.maximum_reassembled_bytes_per_flow,
        )
        combined_history = self._history + bytes(contiguous)
        expired = len(combined_history) - overlap_limit
        if expired > 0:
            self._history = combined_history[expired:]
            self._history_start += expired
            self._budget.release(expired)
        else:
            self._history = combined_history
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
        retained = len(self._history) + self.pending_bytes
        self._pending = None
        self._history = b""
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
    # Phase A1 capture evidence contains only protocol version 0x0001 and
    # address 1. Unknown variants are rejected rather than redacted into a
    # known-looking record.
    if frame[2:4] != b"\x00\x01" or frame[6] != 1:
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
    """Recursively enforce the complete key/type allowlist before publication."""
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


def _read_capture(path: Path, policy: ParserPolicy) -> bytes:
    path_stat: os.stat_result | None = None
    try:
        path_stat = path.lstat()
    except OSError:
        pass
    if path_stat is None or stat.S_ISLNK(path_stat.st_mode):
        raise CaptureError(FailureReason.INPUT_KIND)
    descriptor: int | None = None
    flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        pass
    if descriptor is None:
        raise CaptureError(FailureReason.INPUT_KIND)
    failure: FailureReason | None = None
    capture: bytes | None = None
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            failure = FailureReason.INPUT_KIND
        elif file_stat.st_size > policy.maximum_capture_bytes:
            failure = FailureReason.INPUT_SIZE
        else:
            chunks: list[bytes] = []
            remaining = policy.maximum_capture_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            capture = b"".join(chunks)
    except OSError:
        failure = FailureReason.INPUT_CHANGED
    try:
        os.close(descriptor)
    except OSError:
        if failure is None:
            failure = FailureReason.INPUT_CHANGED
    if failure is not None:
        raise CaptureError(failure)
    if capture is None:
        raise CaptureError(FailureReason.INPUT_CHANGED)
    if len(capture) > policy.maximum_capture_bytes:
        raise CaptureError(FailureReason.INPUT_SIZE)
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
    return None


@dataclass(slots=True)
class _ObservedSession:
    stream_id: int
    client_initial_sequence: int
    client_handshake: tuple[int, bytes, bytes]
    server_initial_sequence: int | None = None
    server_handshake: tuple[int, bytes, bytes] | None = None
    client_terminal_sequence: int | None = None
    server_terminal_sequence: int | None = None
    client_terminal_packet: tuple[int, int, bytes] | None = None
    server_terminal_packet: tuple[int, int, bytes] | None = None
    application_started: bool = False


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
            fin = bool(tcp.flags & module.tcp.TH_FIN)
            rst = bool(tcp.flags & module.tcp.TH_RST)
            session = sessions.get(key)
            starts_stream = False
            sequence = tcp.seq
            payload = bytes(tcp.data)
            handshake = (tcp.flags, bytes(tcp.opts), payload)
            has_terminal_flag = fin or rst
            if client_side and syn and not ack:
                if session is not None and sequence == session.client_initial_sequence:
                    if handshake != session.client_handshake:
                        raise CaptureError(FailureReason.MALFORMED)
                    continue
                if has_terminal_flag:
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
                if has_terminal_flag:
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
            packet_signature = (sequence, tcp.flags, payload)
            terminal_sequence = (
                session.client_terminal_sequence
                if client_side
                else session.server_terminal_sequence
            )
            if terminal_sequence is not None:
                terminal_packet = (
                    session.client_terminal_packet
                    if client_side
                    else session.server_terminal_packet
                )
                payload_end = (sequence + len(payload)) % _SEQUENCE_MODULUS
                if packet_signature == terminal_packet:
                    continue
                if (
                    has_terminal_flag
                    or _sequence_advances(sequence, terminal_sequence)
                    or (payload and _sequence_advances(payload_end, terminal_sequence))
                ):
                    raise CaptureError(FailureReason.MALFORMED)
                if not payload:
                    continue
                yield CapturedSegment(
                    direction,
                    sequence,
                    captured_at,
                    payload,
                    session.stream_id,
                )
                continue
            if fin and rst:
                raise CaptureError(FailureReason.MALFORMED)
            if rst:
                if payload:
                    raise CaptureError(FailureReason.MALFORMED)
                if client_side:
                    session.client_terminal_sequence = sequence
                    session.client_terminal_packet = packet_signature
                else:
                    session.server_terminal_sequence = sequence
                    session.server_terminal_packet = packet_signature
                continue
            if payload:
                session.application_started = True
            if fin:
                terminal_sequence = (sequence + len(payload) + 1) % _SEQUENCE_MODULUS
                if client_side:
                    session.client_terminal_sequence = terminal_sequence
                    session.client_terminal_packet = packet_signature
                else:
                    session.server_terminal_sequence = terminal_sequence
                    session.server_terminal_packet = packet_signature
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
    capture = _read_capture(Path(pcap_path), active_policy)
    return sanitize_segments(_pcap_segments(capture, active_policy), active_policy)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
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
    return parser.parse_args(argv)


def _serialize_output(value: object) -> bytes:
    _validate_synthetic_output(value)
    return (json.dumps(value, indent=2) + "\n").encode()


def _write_exclusive(path: Path, content: bytes) -> None:
    failure: FailureReason | None = None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            temporary_path = Path(output.name)
            if output.write(content) != len(content):
                raise CaptureError(FailureReason.OUTPUT)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_path, path)
    except FileExistsError:
        failure = FailureReason.OUTPUT_EXISTS
    except CaptureError as error:
        failure = error.reason
    except OSError:
        failure = FailureReason.OUTPUT
    if temporary_path is not None:
        with suppress(OSError):
            temporary_path.unlink()
    if failure is not None:
        raise CaptureError(failure)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
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
