"""Offline-only tests for the dongle capture sanitizer."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import traceback
from collections.abc import Buffer, Callable
from importlib import util
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

import scripts.decode_cloud_frames as decoder_module
from scripts.decode_cloud_frames import (
    CaptureError,
    CapturedSegment,
    FailureReason,
    ParserPolicy,
    StreamFrameDecoder,
    TCPStreamReassembler,
    compute_crc16,
    main,
    process_pcap,
    sanitize_segments,
)


OUTER_IDENTITY = b"CANARYDG01"
INNER_IDENTITY = b"CANARYIV01"
PROTECTED_CANARIES = {
    "serial_identity": OUTER_IDENTITY.decode(),
    "device_identity": INNER_IDENTITY.decode(),
    "payload_register": "REG!",
}


class _DecoderModule(Protocol):
    dpkt: ModuleType | None
    CaptureError: type[Exception]

    def compute_crc16(self, data: Buffer) -> int: ...

    def process_pcap(self, pcap_path: str | Path) -> dict[str, object]: ...

    def main(self, argv: list[str] | None = None) -> int: ...


def _dpkt() -> ModuleType:
    return cast(
        ModuleType,
        pytest.importorskip("dpkt", reason="offline PCAP adapter dependency"),
    )


def _ethernet_packet(
    payload: bytes,
    *,
    sequence: int,
    flags: int,
    cloud_to_dongle: bool = False,
) -> bytes:
    packet_module = _dpkt()
    tcp = packet_module.tcp.TCP(
        sport=4346 if cloud_to_dongle else 32000,
        dport=32000 if cloud_to_dongle else 4346,
        seq=sequence,
        flags=flags,
        data=payload,
    )
    ip = packet_module.ip.IP(
        src=b"\xc6\x33\x64\x63" if cloud_to_dongle else b"\xc0\x00\x02\x63",
        dst=b"\xc0\x00\x02\x63" if cloud_to_dongle else b"\xc6\x33\x64\x63",
        p=packet_module.ip.IP_PROTO_TCP,
        data=tcp,
    )
    ethernet = packet_module.ethernet.Ethernet(
        src=b"\x02\x00\x00\x00\x00\x01",
        dst=b"\x02\x00\x00\x00\x00\x02",
        type=packet_module.ethernet.ETH_TYPE_IP,
        data=ip,
    )
    return bytes(ethernet)


def _write_capture(
    capture_path: Path,
    packets: list[tuple[float, bytes]],
    *,
    link_type: int = 1,
    pcapng: bool = False,
) -> None:
    packet_module = _dpkt()
    with capture_path.open("wb") as capture_file:
        writer_type = (
            packet_module.pcapng.Writer if pcapng else packet_module.pcap.Writer
        )
        writer = writer_type(capture_file, linktype=link_type)
        for timestamp, packet in packets:
            writer.writepkt(packet, ts=timestamp)
        writer.close()


def _cloud_frame(
    function: int,
    payload: bytes,
    *,
    identity: bytes = OUTER_IDENTITY,
) -> bytes:
    body = bytes((1, function)) + identity + payload
    return b"\xa1\x1a\x00\x01" + len(body).to_bytes(2, "little") + body


def _read_request(
    *,
    start: int = 7,
    count: int = 2,
    function: int = 0x03,
    identity: bytes = INNER_IDENTITY,
) -> bytes:
    body = bytes((1, function)) + identity
    body += start.to_bytes(2, "little") + count.to_bytes(2, "little")
    return body + compute_crc16(body).to_bytes(2, "little")


def _read_response(
    *,
    start: int = 7,
    words: tuple[int, ...] = (0x1234, 0x5678),
    function: int = 0x04,
    identity: bytes = INNER_IDENTITY,
) -> bytes:
    register_data = b"".join(word.to_bytes(2, "little") for word in words)
    body = (
        bytes((1, function))
        + identity
        + start.to_bytes(2, "little")
        + bytes((len(register_data),))
        + register_data
    )
    return body + compute_crc16(body).to_bytes(2, "little")


def _c2(modbus_frame: bytes, *, identity: bytes = OUTER_IDENTITY) -> bytes:
    payload = len(modbus_frame).to_bytes(2, "little") + modbus_frame
    return _cloud_frame(0xC2, payload, identity=identity)


def _segments(*payloads: bytes) -> list[CapturedSegment]:
    sequence = 100
    captured_at = 10.0
    result: list[CapturedSegment] = []
    for payload in payloads:
        result.append(
            CapturedSegment(
                direction="dongle_to_cloud",
                sequence=sequence,
                captured_at=captured_at,
                payload=payload,
                starts_stream=not result,
            )
        )
        sequence += len(payload)
        captured_at += 0.01
    return result


@pytest.mark.parametrize(
    "value", [b"123456789", bytearray(b"123456789"), memoryview(b"123456789")]
)
def test_public_crc_seam_normalizes_bytes_like_inputs(value: Buffer) -> None:
    assert compute_crc16(value) == 0x4B37


@pytest.mark.parametrize(
    ("maximum_frame_bytes", "prefix_scan_bytes", "overall_frame_deadline"),
    [(512, 2, 1.0), (4096, 64, 5.0), (65535, 1024, 30.0)],
)
def test_parser_policy_accepts_contract_boundaries(
    maximum_frame_bytes: int,
    prefix_scan_bytes: int,
    overall_frame_deadline: float,
) -> None:
    policy = ParserPolicy(
        maximum_frame_bytes=maximum_frame_bytes,
        prefix_scan_bytes=prefix_scan_bytes,
        overall_frame_deadline=overall_frame_deadline,
    )

    assert policy.maximum_frame_bytes == maximum_frame_bytes
    assert policy.prefix_scan_bytes == prefix_scan_bytes
    assert policy.overall_frame_deadline == overall_frame_deadline


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ParserPolicy(maximum_frame_bytes=511),
        lambda: ParserPolicy(maximum_frame_bytes=65536),
        lambda: ParserPolicy(prefix_scan_bytes=1),
        lambda: ParserPolicy(prefix_scan_bytes=1025),
        lambda: ParserPolicy(overall_frame_deadline=0.9),
        lambda: ParserPolicy(overall_frame_deadline=30.1),
        lambda: ParserPolicy(overall_frame_deadline=float("nan")),
        lambda: ParserPolicy(overall_frame_deadline=float("inf")),
        lambda: ParserPolicy(maximum_capture_bytes=0),
        lambda: ParserPolicy(maximum_packet_bytes=0),
        lambda: ParserPolicy(maximum_packets=0),
        lambda: ParserPolicy(maximum_flows=0),
        lambda: ParserPolicy(maximum_segments_per_flow=0),
        lambda: ParserPolicy(maximum_pending_bytes_per_flow=0),
        lambda: ParserPolicy(maximum_reassembled_bytes_per_flow=0),
        lambda: ParserPolicy(maximum_aggregate_memory_bytes=0),
    ],
)
def test_parser_policy_rejects_values_outside_contract(
    constructor: Callable[[], ParserPolicy],
) -> None:
    with pytest.raises(ValueError, match="outside the internal contract"):
        constructor()


def test_stream_decoder_handles_every_split_and_byte_fragmentation() -> None:
    frame = _c2(_read_request())

    for split in range(1, len(frame)):
        decoder = StreamFrameDecoder()
        assert decoder.feed(frame[:split], captured_at=1.0) == []
        assert decoder.feed(frame[split:], captured_at=1.1) == [frame]
        decoder.close(captured_at=1.1)

    byte_decoder = StreamFrameDecoder()
    decoded: list[bytes] = []
    for index, byte in enumerate(frame):
        decoded.extend(byte_decoder.feed(bytes((byte,)), captured_at=2 + index / 100))
    assert decoded == [frame]


def test_stream_decoder_emits_coalesced_frames() -> None:
    heartbeat = _cloud_frame(0xC1, b"\x01")
    request = _c2(_read_request())

    assert StreamFrameDecoder().feed(heartbeat + request, captured_at=1.0) == [
        heartbeat,
        request,
    ]


def test_tcp_reassembler_deduplicates_and_orders_segments() -> None:
    reassembler = TCPStreamReassembler(ParserPolicy())
    reassembler.start(100)

    assert reassembler.push(100, b"abc", captured_at=1.0) == [(1.0, b"abc")]
    assert reassembler.push(106, b"ghi", captured_at=1.2) == []
    assert reassembler.push(100, b"abc", captured_at=1.3) == []
    assert reassembler.push(102, b"cdef", captured_at=1.4) == [(1.4, b"defghi")]


def test_tcp_reassembler_fails_closed_on_gap_conflict_and_capacity() -> None:
    gap = TCPStreamReassembler()
    gap.start(100)
    gap.push(100, b"a", captured_at=1.0)
    gap.push(102, b"c", captured_at=1.1)
    with pytest.raises(CaptureError) as gap_error:
        gap.close()
    assert gap_error.value.reason is FailureReason.TRUNCATED

    conflict = TCPStreamReassembler()
    conflict.start(100)
    conflict.push(100, b"a", captured_at=1.0)
    conflict.push(102, b"c", captured_at=1.1)
    with pytest.raises(CaptureError) as conflict_error:
        conflict.push(102, b"d", captured_at=1.2)
    assert conflict_error.value.reason is FailureReason.MALFORMED

    capacity = TCPStreamReassembler()
    capacity.start(100)
    capacity.push(100, b"a", captured_at=1.0)
    with pytest.raises(CaptureError) as capacity_error:
        capacity.push(102, b"x" * (16 * 1024 + 1), captured_at=1.1)
    assert capacity_error.value.reason is FailureReason.CAPACITY


def test_reassembly_pending_storage_accepts_exact_limit_and_rejects_one_over() -> None:
    policy = ParserPolicy(
        maximum_pending_bytes_per_flow=4,
        maximum_aggregate_memory_bytes=4,
    )
    exact = TCPStreamReassembler(policy)
    exact.start(100)
    assert exact.push(101, b"bcde", captured_at=1.0) == []
    assert exact.pending_bytes == 4
    assert exact.retained_bytes == 4

    overflow = TCPStreamReassembler(policy)
    overflow.start(100)
    with pytest.raises(CaptureError) as caught:
        overflow.push(101, b"bcdef", captured_at=1.0)
    assert caught.value.reason is FailureReason.CAPACITY
    assert overflow.pending_bytes <= policy.maximum_pending_bytes_per_flow


def test_stream_decoder_rejects_truncation_at_eof() -> None:
    decoder = StreamFrameDecoder()
    decoder.feed(_cloud_frame(0xC1, b"\x01")[:-1], captured_at=1.0)

    with pytest.raises(CaptureError) as caught:
        decoder.close(captured_at=1.1)

    assert caught.value.reason is FailureReason.TRUNCATED


def test_stream_decoder_rejects_oversize_before_body_buffering() -> None:
    policy = ParserPolicy(maximum_frame_bytes=512)
    exact_frame = _cloud_frame(0xC1, b"x" * (policy.maximum_frame_bytes - 18))
    exact = StreamFrameDecoder(policy)
    assert exact.feed(exact_frame, captured_at=1.0) == [exact_frame]
    exact.close(captured_at=1.0)

    decoder = StreamFrameDecoder(policy)
    advertised_body = (507).to_bytes(2, "little")

    with pytest.raises(CaptureError) as caught:
        decoder.feed(b"\xa1\x1a\x00\x01" + advertised_body, captured_at=1.0)

    assert caught.value.reason is FailureReason.OVERSIZE
    assert decoder.buffered_bytes <= 6


def test_stream_decoder_enforces_bounded_prefix_scan() -> None:
    frame = _cloud_frame(0xC1, b"\x01")
    decoder = StreamFrameDecoder(ParserPolicy(prefix_scan_bytes=2))
    assert decoder.feed(b"xy" + frame, captured_at=1.0) == [frame]

    with pytest.raises(CaptureError) as caught:
        StreamFrameDecoder(ParserPolicy(prefix_scan_bytes=2)).feed(
            b"xyz" + frame, captured_at=1.0
        )

    assert caught.value.reason is FailureReason.PREFIX


def test_stream_decoder_uses_one_non_resetting_deadline() -> None:
    decoder = StreamFrameDecoder(ParserPolicy(overall_frame_deadline=1.0))
    frame = _cloud_frame(0xC1, b"\x01")
    decoder.feed(frame[:2], captured_at=1.0)
    decoder.feed(frame[2:3], captured_at=1.9)

    with pytest.raises(CaptureError) as caught:
        decoder.feed(frame[3:4], captured_at=2.01)

    assert caught.value.reason is FailureReason.TIMEOUT


def test_capture_timestamps_must_be_finite_and_monotonic() -> None:
    frame = _cloud_frame(0xC1, b"\x01")
    invalid_captures = (
        [CapturedSegment("dongle_to_cloud", 100, value, frame, 0, True)]
        for value in (float("nan"), float("inf"), float("-inf"))
    )
    decreasing = [
        CapturedSegment("dongle_to_cloud", 100, 2.0, b"", 0, True),
        CapturedSegment("dongle_to_cloud", 100, 1.0, frame, 0),
    ]

    for segments in (*invalid_captures, decreasing):
        with pytest.raises(CaptureError) as caught:
            sanitize_segments(segments)
        assert caught.value.reason is FailureReason.MALFORMED


def test_reassembly_gap_uses_earliest_fragment_deadline() -> None:
    frame = _cloud_frame(0xC1, b"\x01")
    captures = (
        [
            CapturedSegment("dongle_to_cloud", 100, 1.0, b"", 0, True),
            CapturedSegment("dongle_to_cloud", 101, 1.0, frame[1:], 0),
            CapturedSegment("dongle_to_cloud", 100, 2.01, frame[:1], 0),
        ],
        [
            CapturedSegment("dongle_to_cloud", 100, 1.0, b"", 0, True),
            CapturedSegment("dongle_to_cloud", 100, 1.0, frame[:3], 0),
            CapturedSegment("dongle_to_cloud", 104, 1.9, frame[4:], 0),
            CapturedSegment("dongle_to_cloud", 103, 2.01, frame[3:4], 0),
        ],
    )

    for segments in captures:
        with pytest.raises(CaptureError) as caught:
            sanitize_segments(segments, ParserPolicy(overall_frame_deadline=1.0))

        assert caught.value.reason is FailureReason.TIMEOUT


def test_sanitizer_rejects_bad_crc() -> None:
    bad_request = bytearray(_read_request())
    bad_request[-1] ^= 0xFF

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(_c2(bytes(bad_request))))

    assert caught.value.reason is FailureReason.CRC


def test_sanitizer_rejects_mismatched_identity_on_stream() -> None:
    first = _cloud_frame(0xC1, b"\x01")
    second = _cloud_frame(0xC1, b"\x01", identity=b"CANARYDG02")

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(first, second))

    assert caught.value.reason is FailureReason.IDENTITY


def test_sanitizer_rejects_mismatched_inner_address() -> None:
    inner = bytearray(_read_request())
    inner[0] = 2
    inner[-2:] = compute_crc16(inner[:-2]).to_bytes(2, "little")

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(_c2(bytes(inner))))

    assert caught.value.reason is FailureReason.IDENTITY


@pytest.mark.parametrize(
    "frame",
    [
        b"\xa1\x1a\x01\x00" + _cloud_frame(0xC1, b"\x01")[4:],
        _cloud_frame(0xC1, b"\x01")[:6] + b"\x02" + _cloud_frame(0xC1, b"\x01")[7:],
        _cloud_frame(0xC1, b"\x01\x02"),
    ],
)
def test_sanitizer_rejects_unsupported_header_and_heartbeat_shapes(
    frame: bytes,
) -> None:
    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(frame))

    assert caught.value.reason is FailureReason.PROTOCOL


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (_cloud_frame(0xCF, b"\x01"), FailureReason.FUNCTION),
        (_c2(_read_request(function=0x06)), FailureReason.FUNCTION),
        (_c2(_read_request(start=65535, count=2)), FailureReason.RANGE),
    ],
)
def test_sanitizer_fails_closed_on_unknown_functions_and_ranges(
    frame: bytes,
    reason: FailureReason,
) -> None:
    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(frame))

    assert caught.value.reason is reason


def test_sanitizer_emits_only_synthetic_minimal_data() -> None:
    heartbeat = _cloud_frame(0xC1, b"\x01")
    response = _c2(_read_response(words=(0x4552, 0x2147)))

    sanitized = sanitize_segments(_segments(heartbeat, response))
    serialized = json.dumps(sanitized, sort_keys=True)

    for forbidden in PROTECTED_CANARIES.values():
        assert forbidden not in serialized
    assert sanitized["capture"] == {
        "source": "authorized_offline_input",
        "dongle_address": "192.0.2.10",
        "cloud_address": "198.51.100.20",
    }
    assert all(frame["identity"].startswith("SYNTH") for frame in sanitized["frames"])
    response_record = sanitized["frames"][1]
    assert response_record["register_count"] == 2
    assert response_record["register_words"] == ["SYNTHETIC_A55A"]


def test_sanitizer_matches_synthetic_minimum_golden_fixture() -> None:
    heartbeat = _cloud_frame(0xC1, b"\x01")
    response = _c2(_read_response(start=7, words=(0x1234, 0x5678)))

    actual = sanitize_segments(_segments(heartbeat, response))
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "dongle_emulation"
        / "minimal_sanitized.json"
    )

    assert actual == json.loads(fixture_path.read_text(encoding="utf-8"))


def test_sanitizer_fails_closed_at_synthetic_record_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decoder_module, "MAX_SANITIZED_RECORDS", 1)
    first = _c2(_read_response(start=7))
    second = _c2(_read_response(start=42))

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(first, second))

    assert caught.value.reason is FailureReason.CAPACITY


def test_offline_pcap_adapter_and_cli_never_report_source_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heartbeat = _cloud_frame(0xC1, b"\x01")
    response = _c2(_read_response(words=(0x4552, 0x2147)))
    chunks = (heartbeat[:5], heartbeat[5:] + response)
    capture_path = tmp_path / "CANARYDG01-authorized-input.pcap"
    output_path = tmp_path / "sanitized.json"
    packet_module = _dpkt()
    sequence = 100
    packets = [
        (
            0.9,
            _ethernet_packet(
                b"", sequence=sequence - 1, flags=packet_module.tcp.TH_SYN
            ),
        )
    ]
    for index, chunk in enumerate(chunks):
        packets.append(
            (
                1.0 + index / 10,
                _ethernet_packet(
                    chunk, sequence=sequence, flags=packet_module.tcp.TH_ACK
                ),
            )
        )
        sequence += len(chunk)
    _write_capture(capture_path, packets)

    direct = process_pcap(capture_path)
    assert direct["frames"][0]["identity"] == "SYNTHDG001"
    assert (
        main(
            [
                str(capture_path),
                "--output",
                str(output_path),
                "--authorized-offline-input",
            ]
        )
        == 0
    )
    captured_output = capsys.readouterr()
    recursive_return = json.dumps(direct, sort_keys=True)
    created_output = output_path.read_text(encoding="utf-8")
    for canary in PROTECTED_CANARIES.values():
        assert canary not in recursive_return
        assert canary not in captured_output.out
        assert canary not in captured_output.err
        assert canary not in created_output
    assert str(capture_path) not in captured_output.out
    assert str(capture_path) not in captured_output.err
    assert str(output_path) not in captured_output.out
    assert str(output_path) not in captured_output.err
    assert json.loads(output_path.read_text(encoding="utf-8")) == direct


def test_pcap_reconnect_on_same_flow_starts_a_new_stream(tmp_path: Path) -> None:
    capture_path = tmp_path / "synthetic-reconnect.pcap"
    frames = (_c2(_read_response(start=7)), _c2(_read_response(start=42)))

    packet_module = _dpkt()
    _write_capture(
        capture_path,
        [
            (
                timestamp,
                _ethernet_packet(payload, sequence=sequence, flags=flags),
            )
            for timestamp, sequence, flags, payload in (
                (1.0, 100, packet_module.tcp.TH_SYN, b""),
                (1.1, 101, packet_module.tcp.TH_ACK, frames[0]),
                (2.0, 10, packet_module.tcp.TH_SYN, b""),
                (2.1, 11, packet_module.tcp.TH_ACK, frames[1]),
            )
        ],
    )

    sanitized = process_pcap(capture_path)

    assert [frame["start_register"] for frame in sanitized["frames"]] == [7, 42]


def test_pcap_handshake_retransmissions_are_exact_in_both_directions(
    tmp_path: Path,
) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    syn = packet_module.tcp.TH_SYN
    syn_ack = packet_module.tcp.TH_SYN | packet_module.tcp.TH_ACK
    ack = packet_module.tcp.TH_ACK
    captures = {
        "exact-client": [
            (1.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (1.1, _ethernet_packet(frame[:5], sequence=100, flags=ack)),
            (1.2, _ethernet_packet(b"", sequence=99, flags=syn)),
            (1.3, _ethernet_packet(frame[5:], sequence=105, flags=ack)),
        ],
        "exact-server": [
            (2.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (
                2.1,
                _ethernet_packet(
                    b"", sequence=199, flags=syn_ack, cloud_to_dongle=True
                ),
            ),
            (
                2.2,
                _ethernet_packet(
                    frame[:5], sequence=200, flags=ack, cloud_to_dongle=True
                ),
            ),
            (
                2.3,
                _ethernet_packet(
                    b"", sequence=199, flags=syn_ack, cloud_to_dongle=True
                ),
            ),
            (
                2.4,
                _ethernet_packet(
                    frame[5:], sequence=205, flags=ack, cloud_to_dongle=True
                ),
            ),
        ],
    }
    for name, packets in captures.items():
        capture_path = tmp_path / f"{name}.pcap"
        _write_capture(capture_path, packets)
        assert process_pcap(capture_path)["frames"]

    conflicting = {
        "conflicting-client": [
            (3.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (3.1, _ethernet_packet(b"", sequence=199, flags=syn)),
            (3.2, _ethernet_packet(frame, sequence=200, flags=ack)),
        ],
        "conflicting-server": [
            (4.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (
                4.1,
                _ethernet_packet(
                    b"", sequence=199, flags=syn_ack, cloud_to_dongle=True
                ),
            ),
            (
                4.2,
                _ethernet_packet(
                    b"", sequence=299, flags=syn_ack, cloud_to_dongle=True
                ),
            ),
        ],
        "conflicting-client-flags": [
            (5.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (
                5.1,
                _ethernet_packet(
                    b"", sequence=99, flags=syn | packet_module.tcp.TH_FIN
                ),
            ),
            (5.2, _ethernet_packet(frame, sequence=100, flags=ack)),
        ],
        "conflicting-server-flags": [
            (6.0, _ethernet_packet(b"", sequence=99, flags=syn)),
            (
                6.1,
                _ethernet_packet(
                    b"", sequence=199, flags=syn_ack, cloud_to_dongle=True
                ),
            ),
            (
                6.2,
                _ethernet_packet(
                    b"",
                    sequence=199,
                    flags=syn_ack | packet_module.tcp.TH_RST,
                    cloud_to_dongle=True,
                ),
            ),
            (
                6.3,
                _ethernet_packet(frame, sequence=200, flags=ack, cloud_to_dongle=True),
            ),
        ],
    }
    for name, packets in conflicting.items():
        capture_path = tmp_path / f"{name}.pcap"
        _write_capture(capture_path, packets)
        with pytest.raises(CaptureError) as caught:
            process_pcap(capture_path)
        assert caught.value.reason is FailureReason.MALFORMED


def test_pcap_fin_consumes_sequence_and_terminates_direction(tmp_path: Path) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    capture_path = tmp_path / "fin.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(
                    frame,
                    sequence=100,
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
                ),
            ),
        ],
    )

    assert process_pcap(capture_path)["frames"]


def test_pcap_accepts_orderly_four_way_close_final_ack(tmp_path: Path) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    client_terminal = 100 + len(frame) + 1
    capture_path = tmp_path / "orderly-close.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(
                    b"",
                    sequence=199,
                    flags=packet_module.tcp.TH_SYN | packet_module.tcp.TH_ACK,
                    cloud_to_dongle=True,
                ),
            ),
            (
                1.2,
                _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK),
            ),
            (
                1.3,
                _ethernet_packet(
                    b"",
                    sequence=100 + len(frame),
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
                ),
            ),
            (
                1.4,
                _ethernet_packet(
                    b"",
                    sequence=200,
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
                    cloud_to_dongle=True,
                ),
            ),
            (
                1.5,
                _ethernet_packet(
                    b"",
                    sequence=client_terminal,
                    flags=packet_module.tcp.TH_ACK,
                ),
            ),
        ],
    )

    assert process_pcap(capture_path)["frames"]


@pytest.mark.parametrize("terminal", ["fin", "rst"])
def test_pcap_accepts_exact_empty_terminal_duplicate(
    tmp_path: Path, terminal: str
) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    terminal_sequence = 100 + len(frame)
    terminal_flag = (
        packet_module.tcp.TH_FIN if terminal == "fin" else packet_module.tcp.TH_RST
    )
    terminal_packet = _ethernet_packet(
        b"",
        sequence=terminal_sequence,
        flags=packet_module.tcp.TH_ACK | terminal_flag,
    )
    capture_path = tmp_path / f"duplicate-{terminal}.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK),
            ),
            (1.2, terminal_packet),
            (1.3, terminal_packet),
        ],
    )

    assert process_pcap(capture_path)["frames"]


def test_pcap_accepts_duplicate_fin_with_data_and_prior_data_retransmission(
    tmp_path: Path,
) -> None:
    packet_module = _dpkt()
    prior_frame = _cloud_frame(0xC1, b"\x01")
    final_frame = _cloud_frame(0xC1, b"\x01")
    terminal_sequence = 100 + len(prior_frame)
    terminal_packet = _ethernet_packet(
        final_frame,
        sequence=terminal_sequence,
        flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
    )
    capture_path = tmp_path / "duplicate-data-fin.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(
                    prior_frame, sequence=100, flags=packet_module.tcp.TH_ACK
                ),
            ),
            (1.2, terminal_packet),
            (1.3, terminal_packet),
            (
                1.4,
                _ethernet_packet(
                    prior_frame, sequence=100, flags=packet_module.tcp.TH_ACK
                ),
            ),
        ],
    )

    assert process_pcap(capture_path)["frames"]


def test_pcap_accepts_nonadvancing_half_close_ack(tmp_path: Path) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    fin_sequence = 100 + len(frame)
    capture_path = tmp_path / "half-close-ack.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK),
            ),
            (
                1.2,
                _ethernet_packet(
                    b"",
                    sequence=fin_sequence,
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
                ),
            ),
            (
                1.3,
                _ethernet_packet(
                    b"", sequence=fin_sequence, flags=packet_module.tcp.TH_ACK
                ),
            ),
        ],
    )

    assert process_pcap(capture_path)["frames"]


def test_pcap_rejects_advancing_empty_post_terminal_segment(tmp_path: Path) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    fin_sequence = 100 + len(frame)
    capture_path = tmp_path / "advancing-empty.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK),
            ),
            (
                1.2,
                _ethernet_packet(
                    b"",
                    sequence=fin_sequence,
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_FIN,
                ),
            ),
            (
                1.3,
                _ethernet_packet(
                    b"", sequence=fin_sequence + 2, flags=packet_module.tcp.TH_ACK
                ),
            ),
        ],
    )

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.MALFORMED


@pytest.mark.parametrize(
    ("terminal", "cloud_to_dongle"),
    [("fin", False), ("rst", False), ("fin", True), ("rst", True)],
)
def test_pcap_rejects_post_terminal_segments(
    tmp_path: Path, terminal: str, cloud_to_dongle: bool
) -> None:
    packet_module = _dpkt()
    first = _cloud_frame(0xC1, b"\x01")
    second = _c2(_read_response())
    terminal_flag = (
        packet_module.tcp.TH_FIN if terminal == "fin" else packet_module.tcp.TH_RST
    )
    terminal_payload = first if terminal == "fin" else b""
    data_sequence = 200 if cloud_to_dongle else 100
    terminal_sequence = (
        data_sequence if terminal == "fin" else data_sequence + len(first)
    )
    following_sequence = terminal_sequence + len(terminal_payload) + (terminal == "fin")
    packets = [
        (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN))
    ]
    if cloud_to_dongle:
        packets.append(
            (
                1.05,
                _ethernet_packet(
                    b"",
                    sequence=199,
                    flags=packet_module.tcp.TH_SYN | packet_module.tcp.TH_ACK,
                    cloud_to_dongle=True,
                ),
            )
        )
    if terminal == "rst":
        packets.append(
            (
                1.1,
                _ethernet_packet(
                    first,
                    sequence=data_sequence,
                    flags=packet_module.tcp.TH_ACK,
                    cloud_to_dongle=cloud_to_dongle,
                ),
            )
        )
    packets.extend(
        [
            (
                1.2,
                _ethernet_packet(
                    terminal_payload,
                    sequence=terminal_sequence,
                    flags=packet_module.tcp.TH_ACK | terminal_flag,
                    cloud_to_dongle=cloud_to_dongle,
                ),
            ),
            (
                1.3,
                _ethernet_packet(
                    second,
                    sequence=following_sequence,
                    flags=packet_module.tcp.TH_ACK,
                    cloud_to_dongle=cloud_to_dongle,
                ),
            ),
        ]
    )
    direction = "server" if cloud_to_dongle else "client"
    capture_path = tmp_path / f"post-{terminal}-{direction}.pcap"
    _write_capture(capture_path, packets)

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.MALFORMED


def test_pcap_rejects_rst_payload(tmp_path: Path) -> None:
    packet_module = _dpkt()
    capture_path = tmp_path / "rst-payload.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(
                    _cloud_frame(0xC1, b"\x01"),
                    sequence=100,
                    flags=packet_module.tcp.TH_ACK | packet_module.tcp.TH_RST,
                ),
            ),
        ],
    )

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.MALFORMED


def test_tcp_reassembler_requires_explicit_stream_origin() -> None:
    reassembler = TCPStreamReassembler()

    with pytest.raises(CaptureError) as caught:
        reassembler.push(100, b"a", captured_at=1.0)

    assert caught.value.reason is FailureReason.TRUNCATED


def test_tcp_reassembler_handles_sequence_wrap_and_reverse_one_byte_segments() -> None:
    policy = ParserPolicy(maximum_segments_per_flow=257)
    reassembler = TCPStreamReassembler(policy)
    origin = (1 << 32) - 4
    reassembler.start(origin)

    for offset in range(256, 0, -1):
        assert (
            reassembler.push(
                (origin + offset) % (1 << 32),
                bytes((offset % 251,)),
                captured_at=1.0,
            )
            == []
        )
    assert reassembler.pending_bytes == 256
    expected = bytes(offset % 251 for offset in range(257))
    assert reassembler.push(origin, b"\x00", captured_at=1.1) == [(1.1, expected)]
    assert reassembler.segment_count == policy.maximum_segments_per_flow


def test_tcp_reassembler_rejects_one_segment_over_limit() -> None:
    reassembler = TCPStreamReassembler(ParserPolicy(maximum_segments_per_flow=1))
    reassembler.start(10)
    reassembler.push(10, b"a", captured_at=1.0)

    with pytest.raises(CaptureError) as caught:
        reassembler.push(11, b"b", captured_at=1.1)

    assert caught.value.reason is FailureReason.CAPACITY


@pytest.mark.parametrize(
    ("first_sequence", "first", "second_sequence", "second", "expected"),
    [
        (100, b"abcd", 100, b"abcd", b""),
        (100, b"abcd", 102, b"cdef", b"ef"),
        (102, b"cdef", 100, b"abcd", b"abcdef"),
        (103, b"def", 102, b"cde", b"abcdef"),
        (102, b"cde", 103, b"def", b"abcdef"),
    ],
)
def test_tcp_reassembler_accepts_every_matching_overlap_shape(
    first_sequence: int,
    first: bytes,
    second_sequence: int,
    second: bytes,
    expected: bytes,
) -> None:
    reassembler = TCPStreamReassembler()
    reassembler.start(100)
    first_chunks = reassembler.push(first_sequence, first, captured_at=1.0)
    second_chunks = reassembler.push(second_sequence, second, captured_at=1.1)
    if first_sequence > 100 and second_sequence > 100:
        second_chunks += reassembler.push(100, b"ab", captured_at=1.2)

    emitted = b"".join(chunk for _, chunk in first_chunks + second_chunks)
    if first_sequence == 100:
        assert emitted == first + expected
    else:
        assert emitted == expected


@pytest.mark.parametrize(
    ("first_sequence", "first", "second_sequence", "second"),
    [
        (100, b"abcd", 100, b"abXd"),
        (100, b"abcd", 102, b"Xdef"),
        (102, b"cdef", 100, b"abXd"),
        (103, b"def", 102, b"cXe"),
        (102, b"cde", 103, b"dXf"),
    ],
)
def test_tcp_reassembler_rejects_every_conflicting_overlap_shape(
    first_sequence: int,
    first: bytes,
    second_sequence: int,
    second: bytes,
) -> None:
    reassembler = TCPStreamReassembler()
    reassembler.start(100)
    reassembler.push(first_sequence, first, captured_at=1.0)

    with pytest.raises(CaptureError) as caught:
        reassembler.push(second_sequence, second, captured_at=1.1)

    assert caught.value.reason is FailureReason.MALFORMED


def test_reassembly_memory_and_stream_limits_accept_exact_and_reject_one_over() -> None:
    exact_policy = ParserPolicy(
        maximum_packet_bytes=2,
        maximum_reassembled_bytes_per_flow=5,
        maximum_aggregate_memory_bytes=5,
    )
    exact = TCPStreamReassembler(exact_policy)
    exact.start(1)
    assert exact.push(1, b"abcde", captured_at=1.0) == [(1.0, b"abcde")]
    assert exact.retained_bytes == 2

    aggregate_policy = ParserPolicy(
        maximum_packet_bytes=4,
        maximum_reassembled_bytes_per_flow=5,
        maximum_aggregate_memory_bytes=4,
    )
    aggregate = TCPStreamReassembler(aggregate_policy)
    aggregate.start(1)
    with pytest.raises(CaptureError) as aggregate_error:
        aggregate.push(1, b"abcde", captured_at=1.0)
    assert aggregate_error.value.reason is FailureReason.CAPACITY
    assert aggregate.retained_bytes <= aggregate_policy.maximum_aggregate_memory_bytes

    stream_policy = ParserPolicy(
        maximum_reassembled_bytes_per_flow=4,
        maximum_aggregate_memory_bytes=5,
    )
    stream = TCPStreamReassembler(stream_policy)
    stream.start(1)
    with pytest.raises(CaptureError) as stream_error:
        stream.push(1, b"abcde", captured_at=1.0)
    assert stream_error.value.reason is FailureReason.CAPACITY
    assert stream.retained_bytes <= stream_policy.maximum_aggregate_memory_bytes


def test_sanitizer_flow_limit_accepts_exact_and_rejects_one_over() -> None:
    frame = _cloud_frame(0xC1, b"\x01")
    exact = [
        CapturedSegment(
            "dongle_to_cloud", 100, float(stream_id), frame, stream_id, True
        )
        for stream_id in range(2)
    ]
    assert len(sanitize_segments(exact, ParserPolicy(maximum_flows=2))["frames"]) == 1

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(exact, ParserPolicy(maximum_flows=1))

    assert caught.value.reason is FailureReason.CAPACITY


def test_sanitizer_aggregate_memory_limit_accepts_peak_and_rejects_one_under() -> None:
    frame = _cloud_frame(0xC1, b"\x01")
    segments = [
        CapturedSegment(
            "dongle_to_cloud", 100, float(stream_id), frame, stream_id, True
        )
        for stream_id in range(2)
    ]
    peak_retained = len(frame) * 3

    assert sanitize_segments(
        segments,
        ParserPolicy(maximum_aggregate_memory_bytes=peak_retained),
    )["frames"]
    with pytest.raises(CaptureError) as caught:
        sanitize_segments(
            segments,
            ParserPolicy(maximum_aggregate_memory_bytes=peak_retained - 1),
        )

    assert caught.value.reason is FailureReason.CAPACITY


def test_session_binds_outer_identity_across_both_directions() -> None:
    segments = [
        CapturedSegment(
            "dongle_to_cloud", 100, 1.0, _cloud_frame(0xC1, b"\x01"), 0, True
        ),
        CapturedSegment(
            "cloud_to_dongle",
            200,
            1.1,
            _cloud_frame(0xC1, b"\x01", identity=b"CANARYDG02"),
            0,
            True,
        ),
    ]

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(segments)

    assert caught.value.reason is FailureReason.IDENTITY


def test_session_binds_inner_identity_across_both_directions() -> None:
    segments = [
        CapturedSegment("dongle_to_cloud", 100, 1.0, _c2(_read_request()), 0, True),
        CapturedSegment(
            "cloud_to_dongle",
            200,
            1.1,
            _c2(_read_request(identity=b"CANARYIV02")),
            0,
            True,
        ),
    ]

    with pytest.raises(CaptureError) as caught:
        sanitize_segments(segments)

    assert caught.value.reason is FailureReason.IDENTITY


def test_distinct_valid_identities_receive_distinct_synthetic_aliases() -> None:
    segments = [
        CapturedSegment("dongle_to_cloud", 100, 1.0, _c2(_read_request()), 0, True),
        CapturedSegment(
            "dongle_to_cloud",
            200,
            1.1,
            _c2(
                _read_request(identity=b"CANARYIV02"),
                identity=b"CANARYDG02",
            ),
            1,
            True,
        ),
    ]

    frames = sanitize_segments(segments)["frames"]

    assert [frame["identity"] for frame in frames] == ["SYNTHDG001", "SYNTHDG002"]
    assert [frame["inner_identity"] for frame in frames] == [
        "SYNTHIV001",
        "SYNTHIV002",
    ]


def test_recursive_output_schema_rejects_generated_pass_through_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = cast(Callable[..., dict[str, object]], decoder_module._sanitize_frame)
    leak_key = "".join(("raw", "_payload"))
    leak_value = "".join(
        chr(code) for code in (76, 69, 65, 75, 45, 67, 65, 78, 65, 82, 89)
    )

    def leaking_sanitizer(*args: object, **kwargs: object) -> dict[str, object]:
        sanitized = original(*args, **kwargs)
        return sanitized | {leak_key: leak_value}

    monkeypatch.setattr(decoder_module, "_sanitize_frame", leaking_sanitizer)
    with pytest.raises(CaptureError) as caught:
        sanitize_segments(_segments(_cloud_frame(0xC1, b"\x01")))

    assert caught.value.reason is FailureReason.SCHEMA


@pytest.mark.parametrize("kind", ["directory", "fifo", "socket"])
def test_process_pcap_rejects_non_regular_inputs(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = Path("input")
    peer_socket: socket.socket | None = None
    if kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        peer_socket = socket.socket(socket.AF_UNIX)
        peer_socket.bind(str(target))
    try:
        with pytest.raises(CaptureError) as caught:
            process_pcap(target)
    finally:
        if peer_socket is not None:
            peer_socket.close()

    assert caught.value.reason is FailureReason.INPUT_KIND


def test_process_pcap_rejects_symlink_input(tmp_path: Path) -> None:
    packet_module = _dpkt()
    target = tmp_path / "target.pcap"
    symlink = tmp_path / "input.pcap"
    _write_capture(
        target,
        [(1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN))],
    )
    symlink.symlink_to(target)

    with pytest.raises(CaptureError) as caught:
        process_pcap(symlink)

    assert caught.value.reason is FailureReason.INPUT_KIND


def test_process_pcap_rejects_lstat_to_open_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture_path = tmp_path / "input.pcap"
    replacement = tmp_path / "replacement.pcap"
    capture_path.write_bytes(b"synthetic")
    replacement.write_bytes(b"synthetic")
    real_open = os.open

    def swap_then_open(path: Path, flags: int) -> int:
        capture_path.unlink()
        capture_path.symlink_to(replacement)
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", swap_then_open)
    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.INPUT_KIND


def test_capture_read_is_bounded_after_descriptor_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture_path = tmp_path / "capture"
    capture_path.write_bytes(b"x")
    file_stat = capture_path.stat()
    read_sizes: list[int] = []

    monkeypatch.setattr(os, "open", lambda path, flags: 123)
    monkeypatch.setattr(os, "fstat", lambda descriptor: file_stat)
    monkeypatch.setattr(os, "close", lambda descriptor: None)

    def oversized_read(descriptor: int, count: int) -> bytes:
        read_sizes.append(count)
        return b"x" * count

    monkeypatch.setattr(os, "read", oversized_read)
    with pytest.raises(CaptureError) as caught:
        decoder_module._read_capture(
            capture_path, ParserPolicy(maximum_capture_bytes=4)
        )

    assert caught.value.reason is FailureReason.INPUT_SIZE
    assert read_sizes == [5]


def test_capture_size_limit_distinguishes_exact_boundary_and_one_over(
    tmp_path: Path,
) -> None:
    capture_path = tmp_path / "capture"
    capture_path.write_bytes(b"abcd")
    with pytest.raises(CaptureError) as exact:
        process_pcap(capture_path, ParserPolicy(maximum_capture_bytes=4))
    assert exact.value.reason is FailureReason.MALFORMED

    with pytest.raises(CaptureError) as overflow:
        process_pcap(capture_path, ParserPolicy(maximum_capture_bytes=3))
    assert overflow.value.reason is FailureReason.INPUT_SIZE


def test_process_pcap_redacts_read_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture_path = tmp_path / "capture"
    capture_path.write_bytes(b"synthetic")

    def failed_read(descriptor: int, count: int) -> bytes:
        raise OSError("synthetic read failure")

    monkeypatch.setattr(os, "read", failed_read)
    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.INPUT_CHANGED
    assert str(caught.value) == "capture rejected: input_changed"


def test_capture_errors_drop_raw_exception_chains_and_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet_module = _dpkt()
    valid_capture = tmp_path / "valid.pcap"
    _write_capture(
        valid_capture,
        [(1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN))],
    )
    caught_errors: list[tuple[CaptureError, str]] = []

    invalid_identity = b"\xffUNICODE!!"
    with pytest.raises(CaptureError) as unicode_error:
        sanitize_segments(
            [
                CapturedSegment(
                    "dongle_to_cloud",
                    100,
                    1.0,
                    _cloud_frame(0xC1, b"\x01", identity=invalid_identity),
                    0,
                    True,
                )
            ]
        )
    caught_errors.append((unicode_error.value, "UNICODE!!"))

    with monkeypatch.context() as scoped:
        scoped.setattr(
            os,
            "read",
            lambda descriptor, count: (_ for _ in ()).throw(
                OSError("FILESYSTEM-CANARY")
            ),
        )
        with pytest.raises(CaptureError) as filesystem_error:
            process_pcap(valid_capture)
    assert filesystem_error.value.reason is FailureReason.INPUT_CHANGED
    caught_errors.append((filesystem_error.value, "FILESYSTEM-CANARY"))

    with monkeypatch.context() as scoped:
        scoped.setattr(
            decoder_module,
            "_decode_link_packet",
            lambda packet, link_type: (_ for _ in ()).throw(
                ValueError("PACKET-CANARY")
            ),
        )
        with pytest.raises(CaptureError) as packet_error:
            process_pcap(valid_capture)
    caught_errors.append((packet_error.value, "PACKET-CANARY"))

    for error, canary in caught_errors:
        diagnostics = "".join(traceback.format_exception(error))
        diagnostics += repr((error, error.args, error.__dict__))
        assert error.__cause__ is None
        assert error.__context__ is None
        assert canary not in diagnostics


def test_capture_rejects_unsupported_link_and_malformed_supported_packet(
    tmp_path: Path,
) -> None:
    unsupported = tmp_path / "unsupported.pcap"
    malformed = tmp_path / "malformed.pcap"
    _write_capture(unsupported, [(1.0, b"synthetic")], link_type=147)
    _write_capture(malformed, [(1.0, b"\x00")])

    with pytest.raises(CaptureError) as unsupported_error:
        process_pcap(unsupported)
    with pytest.raises(CaptureError) as malformed_error:
        process_pcap(malformed)

    assert unsupported_error.value.reason is FailureReason.UNSUPPORTED_LINK
    assert malformed_error.value.reason is FailureReason.MALFORMED


def test_capture_distinguishes_irrelevant_traffic_from_decode_failure(
    tmp_path: Path,
) -> None:
    packet_module = _dpkt()
    udp = packet_module.udp.UDP(sport=1000, dport=1001, data=b"synthetic")
    ip = packet_module.ip.IP(
        src=b"\xc0\x00\x02\x01",
        dst=b"\xc6\x33\x64\x01",
        p=packet_module.ip.IP_PROTO_UDP,
        data=udp,
    )
    ethernet = packet_module.ethernet.Ethernet(
        src=b"\x02\x00\x00\x00\x00\x01",
        dst=b"\x02\x00\x00\x00\x00\x02",
        type=packet_module.ethernet.ETH_TYPE_IP,
        data=ip,
    )
    capture_path = tmp_path / "irrelevant.pcap"
    _write_capture(capture_path, [(1.0, bytes(ethernet))])

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.EMPTY


def test_capture_rejects_midstream_payload_without_handshake(tmp_path: Path) -> None:
    packet_module = _dpkt()
    capture_path = tmp_path / "midstream.pcap"
    _write_capture(
        capture_path,
        [
            (
                1.0,
                _ethernet_packet(
                    _cloud_frame(0xC1, b"\x01"),
                    sequence=100,
                    flags=packet_module.tcp.TH_ACK,
                ),
            )
        ],
    )

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.TRUNCATED


def test_capture_rejects_reverse_payload_without_syn_ack(tmp_path: Path) -> None:
    packet_module = _dpkt()
    capture_path = tmp_path / "missing-syn-ack.pcap"
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(
                    _cloud_frame(0xC1, b"\x01"),
                    sequence=200,
                    flags=packet_module.tcp.TH_ACK,
                    cloud_to_dongle=True,
                ),
            ),
        ],
    )

    with pytest.raises(CaptureError) as caught:
        process_pcap(capture_path)

    assert caught.value.reason is FailureReason.TRUNCATED


def test_capture_packet_count_and_size_limits_have_exact_boundaries(
    tmp_path: Path,
) -> None:
    packet_module = _dpkt()
    frame = _cloud_frame(0xC1, b"\x01")
    syn = _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)
    data = _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK)
    capture_path = tmp_path / "bounded.pcap"
    _write_capture(capture_path, [(1.0, syn), (1.1, data)])
    exact = ParserPolicy(
        maximum_packets=2, maximum_packet_bytes=max(len(syn), len(data))
    )
    assert process_pcap(capture_path, exact)["frames"]

    with pytest.raises(CaptureError) as packet_count:
        process_pcap(capture_path, ParserPolicy(maximum_packets=1))
    with pytest.raises(CaptureError) as packet_size:
        process_pcap(
            capture_path,
            ParserPolicy(maximum_packet_bytes=max(len(syn), len(data)) - 1),
        )

    assert packet_count.value.reason is FailureReason.CAPACITY
    assert packet_size.value.reason is FailureReason.CAPACITY


def test_cli_exclusive_create_allows_shared_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet_module = _dpkt()
    capture_path = tmp_path / "input.pcap"
    output_path = tmp_path / "output.json"
    frame = _cloud_frame(0xC1, b"\x01")
    _write_capture(
        capture_path,
        [
            (1.0, _ethernet_packet(b"", sequence=99, flags=packet_module.tcp.TH_SYN)),
            (
                1.1,
                _ethernet_packet(frame, sequence=100, flags=packet_module.tcp.TH_ACK),
            ),
        ],
    )
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    output_path = shared / "output.json"
    arguments = [
        str(capture_path),
        "--output",
        str(output_path),
        "--authorized-offline-input",
    ]
    assert main(arguments) == 0
    first_output = output_path.read_bytes()
    assert main(arguments) == 2
    output = capsys.readouterr()

    assert output_path.read_bytes() == first_output
    assert output.err == "capture rejected: output_exists\n"
    assert list(shared.iterdir()) == [output_path]


@pytest.mark.parametrize("failure_stage", ["partial_write", "flush"])
def test_safe_publish_removes_only_temporary_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    output_path = tmp_path / "output.json"
    real_named_temporary_file = tempfile.NamedTemporaryFile

    class FailingTemporaryFile:
        def __init__(self) -> None:
            self.output = real_named_temporary_file(dir=tmp_path, delete=False)
            self.name = self.output.name

        def __enter__(self) -> FailingTemporaryFile:
            return self

        def write(self, content: bytes) -> int:
            if failure_stage == "partial_write":
                self.output.write(content[:1])
                return 1
            return self.output.write(content)

        def flush(self) -> None:
            if failure_stage == "flush":
                raise OSError("synthetic flush failure")
            self.output.flush()

        def fileno(self) -> int:
            return self.output.fileno()

        def __exit__(
            self,
            exception_type: object,
            exception: object,
            traceback_object: object,
        ) -> None:
            self.output.close()

    monkeypatch.setattr(
        tempfile,
        "NamedTemporaryFile",
        lambda **kwargs: FailingTemporaryFile(),
    )
    with pytest.raises(CaptureError) as caught:
        decoder_module._write_exclusive(output_path, b"synthetic\n")

    assert caught.value.reason is FailureReason.OUTPUT
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_missing_dpkt_fails_closed_in_process_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module_name = "decode_cloud_frames_without_optional_dependency"
    script_path = Path(decoder_module.__file__)
    spec = util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    loaded = util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, loaded)
    monkeypatch.setitem(sys.modules, "dpkt", None)
    spec.loader.exec_module(loaded)
    isolated = cast(_DecoderModule, loaded)
    capture_path = tmp_path / "SYNTHETIC_CANARY_INPUT"
    output_path = tmp_path / "output.json"
    capture_path.write_bytes(b"synthetic-only")

    with pytest.raises(isolated.CaptureError) as caught:
        isolated.process_pcap(capture_path)
    assert str(caught.value) == "capture rejected: dependency"
    assert (
        isolated.main(
            [
                str(capture_path),
                "--output",
                str(output_path),
                "--authorized-offline-input",
            ]
        )
        == 2
    )
    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == "capture rejected: dependency\n"
    assert not output_path.exists()
    assert "SYNTHETIC_CANARY_INPUT" not in output.err
