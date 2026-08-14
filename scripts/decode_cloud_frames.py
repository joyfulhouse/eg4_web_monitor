#!/usr/bin/env python3
"""Create synthetic protocol fixtures from an authorized offline PCAP.

The tool never opens a socket and never emits captured identities, addresses,
payloads, timestamps, or register values. TCP segments are reassembled before
frames are parsed; only then is a minimal synthetic representation produced.

Usage:
    python scripts/decode_cloud_frames.py INPUT.pcap --output sanitized.json \
        --authorized-offline-input

The output path must not already exist. Optional PCAP support requires ``dpkt``.
Core stream, parser, and sanitizer tests do not require that package.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from pylxpweb.transports.dongle import compute_crc16

try:
    dpkt: ModuleType | None = import_module("dpkt")
except ImportError:  # pragma: no cover - exercised by the CLI environment
    dpkt = None


FRAME_MAGIC: Final = b"\xa1\x1a"
SYNTHETIC_DONGLE_IDENTITY: Final = "SYNTHDG001"
SYNTHETIC_INVERTER_IDENTITY: Final = "SYNTHIV001"
DOCUMENTATION_DONGLE_ADDRESS: Final = "192.0.2.10"
DOCUMENTATION_CLOUD_ADDRESS: Final = "198.51.100.20"
SYNTHETIC_REGISTER_WORD: Final = "SYNTHETIC_A55A"
MAX_SANITIZED_RECORDS: Final = 1024


class FailureReason(StrEnum):
    """Bounded, redacted parser failure classifications."""

    CAPACITY = "capacity"
    CRC = "crc"
    FUNCTION = "function"
    IDENTITY = "identity"
    MALFORMED = "malformed"
    OVERSIZE = "oversize"
    PREFIX = "prefix"
    RANGE = "range"
    TIMEOUT = "timeout"
    TRUNCATED = "truncated"


class CaptureError(RuntimeError):
    """A fail-closed capture error whose message cannot contain capture data."""

    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        super().__init__(f"capture rejected: {reason.value}")


@dataclass(frozen=True, slots=True)
class ParserPolicy:
    """Internal parser bounds from the Phase A contract."""

    maximum_frame_bytes: int = 4096
    prefix_scan_bytes: int = 64
    overall_frame_deadline: float = 5.0

    def __post_init__(self) -> None:
        bounds: tuple[tuple[int | float, int | float, int | float], ...] = (
            (self.maximum_frame_bytes, 512, 65535),
            (self.prefix_scan_bytes, 2, 1024),
            (self.overall_frame_deadline, 1.0, 30.0),
        )
        if any(
            value < minimum or value > maximum for value, minimum, maximum in bounds
        ):
            raise ValueError("parser policy value outside the internal contract")

    @property
    def reassembly_capacity(self) -> int:
        """Bound pending reassembly under the parser memory budget."""
        return 16 * 1024


class StreamFrameDecoder:
    """Bounded incremental decoder for complete cloud protocol frames."""

    def __init__(self, policy: ParserPolicy | None = None) -> None:
        self.policy = policy or ParserPolicy()
        self._buffer = bytearray()
        self._prefix_scanned = 0
        self._started_at: float | None = None

    @property
    def buffered_bytes(self) -> int:
        """Return retained bytes for resource-bound assertions."""
        return len(self._buffer)

    def feed(self, data: bytes, *, captured_at: float) -> list[bytes]:
        """Consume one ordered stream chunk and return every complete frame."""
        self._check_deadline(captured_at)
        if data and self._started_at is None:
            self._started_at = captured_at

        decoded: list[bytes] = []
        remaining = memoryview(data)
        storage_limit = self.policy.maximum_frame_bytes + self.policy.prefix_scan_bytes

        while remaining:
            room = storage_limit - len(self._buffer)
            if room <= 0:
                before = len(self._buffer)
                decoded.extend(self._extract_available(captured_at))
                if len(self._buffer) >= before:
                    raise CaptureError(FailureReason.CAPACITY)
                continue

            take = min(room, len(remaining))
            self._buffer.extend(remaining[:take])
            remaining = remaining[take:]
            decoded.extend(self._extract_available(captured_at))

        decoded.extend(self._extract_available(captured_at))
        return decoded

    def close(self, *, captured_at: float) -> None:
        """Finalize at EOF, rejecting any partial prefix, header, or body."""
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

    def _extract_available(self, captured_at: float) -> list[bytes]:
        frames: list[bytes] = []
        while self._buffer:
            magic_index = self._buffer.find(FRAME_MAGIC)
            if magic_index < 0:
                retained = 1 if self._buffer[-1:] == FRAME_MAGIC[:1] else 0
                discarded = len(self._buffer) - retained
                self._prefix_scanned += discarded
                if self._prefix_scanned > self.policy.prefix_scan_bytes:
                    self._discard()
                    raise CaptureError(FailureReason.PREFIX)
                if discarded:
                    del self._buffer[:discarded]
                break

            if magic_index:
                self._prefix_scanned += magic_index
                if self._prefix_scanned > self.policy.prefix_scan_bytes:
                    self._discard()
                    raise CaptureError(FailureReason.PREFIX)
                del self._buffer[:magic_index]

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
            del self._buffer[:total_size]
            self._prefix_scanned = 0
            self._started_at = captured_at if self._buffer else None

        return frames

    def _discard(self) -> None:
        self._buffer.clear()
        self._prefix_scanned = 0
        self._started_at = None


@dataclass(frozen=True, slots=True)
class _PendingSegment:
    captured_at: float
    payload: bytes


class TCPStreamReassembler:
    """Sequence-aware, duplicate-safe bounded TCP payload reassembler."""

    def __init__(self, policy: ParserPolicy | None = None) -> None:
        self.policy = policy or ParserPolicy()
        self._next_sequence: int | None = None
        self._pending: dict[int, _PendingSegment] = {}
        self._pending_bytes = 0

    def push(
        self, sequence: int, payload: bytes, *, captured_at: float
    ) -> list[tuple[float, bytes]]:
        """Add a TCP segment and return newly contiguous stream chunks."""
        if not payload:
            return []
        if sequence < 0:
            raise CaptureError(FailureReason.MALFORMED)
        if self._next_sequence is None:
            self._next_sequence = sequence

        assert self._next_sequence is not None
        segment_end = sequence + len(payload)
        if segment_end <= self._next_sequence:
            return []
        if sequence < self._next_sequence:
            payload = payload[self._next_sequence - sequence :]
            sequence = self._next_sequence

        if sequence > self._next_sequence:
            existing = self._pending.get(sequence)
            if existing is not None:
                if existing.payload != payload:
                    raise CaptureError(FailureReason.MALFORMED)
                return []
            if self._pending_bytes + len(payload) > self.policy.reassembly_capacity:
                raise CaptureError(FailureReason.CAPACITY)
            self._pending[sequence] = _PendingSegment(captured_at, payload)
            self._pending_bytes += len(payload)
            return []

        chunks = [(captured_at, payload)]
        self._next_sequence += len(payload)
        chunks.extend(self._drain_pending(available_at=captured_at))
        return chunks

    def _drain_pending(self, *, available_at: float) -> list[tuple[float, bytes]]:
        chunks: list[tuple[float, bytes]] = []
        assert self._next_sequence is not None
        while self._pending:
            sequence = min(self._pending)
            segment = self._pending[sequence]
            segment_end = sequence + len(segment.payload)
            if sequence > self._next_sequence:
                break
            del self._pending[sequence]
            self._pending_bytes -= len(segment.payload)
            if segment_end <= self._next_sequence:
                continue
            overlap = self._next_sequence - sequence
            payload = segment.payload[overlap:]
            chunks.append((max(available_at, segment.captured_at), payload))
            self._next_sequence += len(payload)
        return chunks

    def close(self) -> None:
        """Reject a stream ending with an unresolved sequence gap."""
        if self._pending:
            self._pending.clear()
            self._pending_bytes = 0
            raise CaptureError(FailureReason.TRUNCATED)


@dataclass(frozen=True, slots=True)
class CapturedSegment:
    """One offline TCP payload with only in-memory capture metadata."""

    direction: str
    sequence: int
    captured_at: float
    payload: bytes
    stream_id: int = 0


@dataclass(slots=True)
class _DirectionState:
    reassembler: TCPStreamReassembler
    decoder: StreamFrameDecoder
    source_identity: bytes | None = None


def find_frames(data: bytes) -> list[tuple[int, bytes]]:
    """Compatibility helper using the same bounded streaming decoder."""
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
    if len(raw) != 10:
        raise CaptureError(FailureReason.IDENTITY)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise CaptureError(FailureReason.IDENTITY) from error
    if not all(character.isalnum() for character in text):
        raise CaptureError(FailureReason.IDENTITY)
    return raw


def _validate_crc(frame: bytes) -> None:
    if len(frame) < 3:
        raise CaptureError(FailureReason.MALFORMED)
    actual = int.from_bytes(frame[-2:], "little")
    if actual != compute_crc16(frame[:-2]):
        raise CaptureError(FailureReason.CRC)


def _sanitize_frame(
    frame: bytes, direction: str, state: _DirectionState
) -> dict[str, Any]:
    if len(frame) < 19 or 6 + int.from_bytes(frame[4:6], "little") != len(frame):
        raise CaptureError(FailureReason.MALFORMED)

    outer_identity = _validated_identity(frame[8:18])
    if state.source_identity is None:
        state.source_identity = outer_identity
    elif state.source_identity != outer_identity:
        raise CaptureError(FailureReason.IDENTITY)

    function = frame[7]
    payload = frame[18:]
    base: dict[str, Any] = {
        "direction": direction,
        "identity": SYNTHETIC_DONGLE_IDENTITY,
    }
    if function == 0xC1:
        if not payload:
            raise CaptureError(FailureReason.MALFORMED)
        return base | {"function": "heartbeat", "payload": "SYNTHETIC_STATUS"}
    if function != 0xC2:
        raise CaptureError(FailureReason.FUNCTION)
    if len(payload) < 2:
        raise CaptureError(FailureReason.MALFORMED)

    inner_size = int.from_bytes(payload[:2], "little")
    inner = payload[2:]
    if inner_size != len(inner) or len(inner) < 17:
        raise CaptureError(FailureReason.MALFORMED)
    inner_function = inner[1]
    if inner_function not in (0x03, 0x04):
        raise CaptureError(FailureReason.FUNCTION)
    if inner[0] != frame[6]:
        raise CaptureError(FailureReason.IDENTITY)
    _validated_identity(inner[2:12])
    start_register = int.from_bytes(inner[12:14], "little")

    if len(inner) == 18:
        register_count = int.from_bytes(inner[14:16], "little")
        if register_count < 1 or start_register + register_count > 65536:
            raise CaptureError(FailureReason.RANGE)
        _validate_crc(inner)
        return base | {
            "function": "data_read_request",
            "inner_identity": SYNTHETIC_INVERTER_IDENTITY,
            "inner_function": _inner_function_name(inner_function),
            "start_register": start_register,
            "register_count": register_count,
            "register_words": [],
        }

    byte_count = inner[14]
    if byte_count < 2 or byte_count % 2 or len(inner) != 15 + byte_count + 2:
        raise CaptureError(FailureReason.RANGE)
    register_count = byte_count // 2
    if start_register + register_count > 65536:
        raise CaptureError(FailureReason.RANGE)
    _validate_crc(inner)
    return base | {
        "function": "data_read_response",
        "inner_identity": SYNTHETIC_INVERTER_IDENTITY,
        "inner_function": _inner_function_name(inner_function),
        "start_register": start_register,
        "register_count": register_count,
        "register_words": [SYNTHETIC_REGISTER_WORD],
    }


def _inner_function_name(function: int) -> str:
    return "read_holding" if function == 0x03 else "read_input"


def sanitize_segments(
    segments: Iterable[CapturedSegment], policy: ParserPolicy | None = None
) -> dict[str, Any]:
    """Reassemble, parse, and sanitize authorized offline TCP payloads."""
    active_policy = policy or ParserPolicy()
    states: dict[tuple[int, str], _DirectionState] = {}
    records: list[dict[str, Any]] = []
    record_keys: set[str] = set()
    last_timestamp: dict[tuple[int, str], float] = {}

    for segment in segments:
        if segment.direction not in ("dongle_to_cloud", "cloud_to_dongle"):
            raise CaptureError(FailureReason.MALFORMED)
        state_key = (segment.stream_id, segment.direction)
        state = states.setdefault(
            state_key,
            _DirectionState(
                TCPStreamReassembler(active_policy), StreamFrameDecoder(active_policy)
            ),
        )
        last_timestamp[state_key] = segment.captured_at
        for captured_at, chunk in state.reassembler.push(
            segment.sequence, segment.payload, captured_at=segment.captured_at
        ):
            for frame in state.decoder.feed(chunk, captured_at=captured_at):
                record = _sanitize_frame(frame, segment.direction, state)
                record_key = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if record_key in record_keys:
                    continue
                if len(records) >= MAX_SANITIZED_RECORDS:
                    raise CaptureError(FailureReason.CAPACITY)
                record_keys.add(record_key)
                records.append(record)

    for state_key, state in states.items():
        state.reassembler.close()
        state.decoder.close(captured_at=last_timestamp[state_key])

    return {
        "schema_version": 1,
        "capture": {
            "source": "authorized_offline_input",
            "dongle_address": DOCUMENTATION_DONGLE_ADDRESS,
            "cloud_address": DOCUMENTATION_CLOUD_ADDRESS,
        },
        "frames": records,
    }


def _extract_ip_from_buf(buf: bytes, link_type: int) -> Any | None:
    """Extract IPv4 data from supported offline PCAP link layers."""
    if dpkt is None:
        raise RuntimeError("optional PCAP dependency unavailable")
    try:
        if link_type == dpkt.pcap.DLT_EN10MB:
            link_packet = dpkt.ethernet.Ethernet(buf)
        elif link_type == dpkt.pcap.DLT_LINUX_SLL:
            link_packet = dpkt.sll.SLL(buf)
        elif link_type == dpkt.pcap.DLT_LINUX_SLL2:
            link_packet = dpkt.sll2.SLL2(buf)
        else:
            return None
        return link_packet.data if isinstance(link_packet.data, dpkt.ip.IP) else None
    except (dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError):
        return None


def _pcap_segments(pcap_path: Path) -> Iterable[CapturedSegment]:
    if dpkt is None:
        raise RuntimeError("optional PCAP dependency unavailable")
    try:
        with pcap_path.open("rb") as capture_file:
            reader = dpkt.pcap.UniversalReader(capture_file)
            link_type = reader.datalink()
            stream_ids: dict[tuple[bytes, int, bytes, int], int] = {}
            next_stream_id = 0
            for timestamp, packet_buffer in reader:
                ip_packet = _extract_ip_from_buf(packet_buffer, link_type)
                if ip_packet is None or not isinstance(ip_packet.data, dpkt.tcp.TCP):
                    continue
                tcp = ip_packet.data
                if tcp.dport == 4346:
                    direction = "dongle_to_cloud"
                elif tcp.sport == 4346:
                    direction = "cloud_to_dongle"
                else:
                    continue
                flow_key = (ip_packet.src, tcp.sport, ip_packet.dst, tcp.dport)
                if tcp.flags & dpkt.tcp.TH_SYN or flow_key not in stream_ids:
                    stream_ids[flow_key] = next_stream_id
                    next_stream_id += 1
                if not tcp.data:
                    continue
                yield CapturedSegment(
                    direction,
                    tcp.seq,
                    float(timestamp),
                    bytes(tcp.data),
                    stream_ids[flow_key],
                )
    except (OSError, ValueError, dpkt.dpkt.Error) as error:
        raise CaptureError(FailureReason.MALFORMED) from error


def process_pcap(
    pcap_path: str | Path, policy: ParserPolicy | None = None
) -> dict[str, Any]:
    """Sanitize one authorized capture without retaining raw capture data."""
    return sanitize_segments(_pcap_segments(Path(pcap_path)), policy)


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


def main(argv: list[str] | None = None) -> int:
    """Run the offline-only sanitizer with redacted status output."""
    arguments = _parse_args(argv)
    try:
        sanitized = process_pcap(arguments.input)
        with arguments.output.open("x", encoding="utf-8") as output_file:
            json.dump(sanitized, output_file, indent=2)
            output_file.write("\n")
    except FileExistsError:
        print("capture rejected: output_exists", file=sys.stderr)
        return 2
    except (CaptureError, OSError, RuntimeError) as error:
        if isinstance(error, CaptureError):
            message = str(error)
        elif isinstance(error, RuntimeError):
            message = "capture rejected: dependency"
        else:
            message = "capture rejected: input"
        print(message, file=sys.stderr)
        return 2
    print(f"synthetic fixture written: {len(sanitized['frames'])} frame classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
