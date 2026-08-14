"""Offline-only tests for the dongle capture sanitizer."""

from __future__ import annotations

import json
from pathlib import Path

import dpkt
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
            )
        )
        sequence += len(payload)
        captured_at += 0.01
    return result


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
    "overrides",
    [
        {"maximum_frame_bytes": 511},
        {"maximum_frame_bytes": 65536},
        {"prefix_scan_bytes": 1},
        {"prefix_scan_bytes": 1025},
        {"overall_frame_deadline": 0.9},
        {"overall_frame_deadline": 30.1},
    ],
)
def test_parser_policy_rejects_values_outside_contract(
    overrides: dict[str, int | float],
) -> None:
    with pytest.raises(ValueError, match="outside the internal contract"):
        ParserPolicy(**overrides)  # type: ignore[arg-type]


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

    assert reassembler.push(100, b"abc", captured_at=1.0) == [(1.0, b"abc")]
    assert reassembler.push(106, b"ghi", captured_at=1.2) == []
    assert reassembler.push(100, b"abc", captured_at=1.3) == []
    assert reassembler.push(102, b"cdef", captured_at=1.4) == [
        (1.4, b"def"),
        (1.4, b"ghi"),
    ]


def test_tcp_reassembler_fails_closed_on_gap_conflict_and_capacity() -> None:
    gap = TCPStreamReassembler()
    gap.push(100, b"a", captured_at=1.0)
    gap.push(102, b"c", captured_at=1.1)
    with pytest.raises(CaptureError) as gap_error:
        gap.close()
    assert gap_error.value.reason is FailureReason.TRUNCATED

    conflict = TCPStreamReassembler()
    conflict.push(100, b"a", captured_at=1.0)
    conflict.push(102, b"c", captured_at=1.1)
    with pytest.raises(CaptureError) as conflict_error:
        conflict.push(102, b"d", captured_at=1.2)
    assert conflict_error.value.reason is FailureReason.MALFORMED

    capacity = TCPStreamReassembler()
    capacity.push(100, b"a", captured_at=1.0)
    with pytest.raises(CaptureError) as capacity_error:
        capacity.push(102, b"x" * (16 * 1024 + 1), captured_at=1.1)
    assert capacity_error.value.reason is FailureReason.CAPACITY


def test_combined_stream_storage_matches_contract_budget() -> None:
    policy = ParserPolicy()
    decoder_storage = policy.maximum_frame_bytes + policy.prefix_scan_bytes

    assert decoder_storage + policy.reassembly_capacity == (
        policy.maximum_frame_bytes + policy.prefix_scan_bytes + 16 * 1024
    )


def test_stream_decoder_rejects_truncation_at_eof() -> None:
    decoder = StreamFrameDecoder()
    decoder.feed(_cloud_frame(0xC1, b"\x01")[:-1], captured_at=1.0)

    with pytest.raises(CaptureError) as caught:
        decoder.close(captured_at=1.1)

    assert caught.value.reason is FailureReason.TRUNCATED


def test_stream_decoder_rejects_oversize_before_body_buffering() -> None:
    decoder = StreamFrameDecoder(ParserPolicy(maximum_frame_bytes=512))
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
    protected_canaries = (
        b"PIN=7391;PSK=private-canary;cookie=private-cookie;"
        b"token=private-token;192.0.2.99;02:00:5e:10:00:00"
    )
    heartbeat = _cloud_frame(0xC1, b"\x01" + protected_canaries)
    response = _c2(_read_response())

    sanitized = sanitize_segments(_segments(heartbeat, response))
    serialized = json.dumps(sanitized, sort_keys=True)

    for forbidden in (
        OUTER_IDENTITY.decode(),
        INNER_IDENTITY.decode(),
        protected_canaries.decode(),
        "192.0.2.99",
        "02:00:5e:10:00:00",
        "1234",
        "5678",
    ):
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
    response = _c2(_read_response())
    chunks = (heartbeat[:5], heartbeat[5:] + response)
    capture_path = tmp_path / "CANARYDG01-authorized-input.pcap"
    output_path = tmp_path / "sanitized.json"

    with capture_path.open("wb") as capture_file:
        writer = dpkt.pcap.Writer(capture_file)
        sequence = 100
        for index, chunk in enumerate(chunks):
            tcp = dpkt.tcp.TCP(
                sport=32000,
                dport=4346,
                seq=sequence,
                flags=dpkt.tcp.TH_ACK,
                data=chunk,
            )
            ip = dpkt.ip.IP(
                src=b"\xc0\x00\x02\x63",
                dst=b"\xc6\x33\x64\x63",
                p=dpkt.ip.IP_PROTO_TCP,
                data=tcp,
            )
            ethernet = dpkt.ethernet.Ethernet(
                src=b"\x02\x00\x00\x00\x00\x01",
                dst=b"\x02\x00\x00\x00\x00\x02",
                type=dpkt.ethernet.ETH_TYPE_IP,
                data=ip,
            )
            writer.writepkt(ethernet, ts=1.0 + index / 10)
            sequence += len(chunk)
        writer.close()

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
    assert "CANARYDG01" not in captured_output.out
    assert "CANARYDG01" not in captured_output.err
    assert str(capture_path) not in captured_output.out
    assert str(capture_path) not in captured_output.err
    assert str(output_path) not in captured_output.out
    assert str(output_path) not in captured_output.err
    assert json.loads(output_path.read_text(encoding="utf-8")) == direct


def test_pcap_reconnect_on_same_flow_starts_a_new_stream(tmp_path: Path) -> None:
    capture_path = tmp_path / "synthetic-reconnect.pcap"
    frames = (_c2(_read_response(start=7)), _c2(_read_response(start=42)))

    with capture_path.open("wb") as capture_file:
        writer = dpkt.pcap.Writer(capture_file)
        for timestamp, sequence, flags, payload in (
            (1.0, 100, dpkt.tcp.TH_SYN, b""),
            (1.1, 101, dpkt.tcp.TH_ACK, frames[0]),
            (2.0, 10, dpkt.tcp.TH_SYN, b""),
            (2.1, 11, dpkt.tcp.TH_ACK, frames[1]),
        ):
            tcp = dpkt.tcp.TCP(
                sport=32000,
                dport=4346,
                seq=sequence,
                flags=flags,
                data=payload,
            )
            ip = dpkt.ip.IP(
                src=b"\xc0\x00\x02\x63",
                dst=b"\xc6\x33\x64\x63",
                p=dpkt.ip.IP_PROTO_TCP,
                data=tcp,
            )
            ethernet = dpkt.ethernet.Ethernet(
                src=b"\x02\x00\x00\x00\x00\x01",
                dst=b"\x02\x00\x00\x00\x00\x02",
                type=dpkt.ethernet.ETH_TYPE_IP,
                data=ip,
            )
            writer.writepkt(ethernet, ts=timestamp)
        writer.close()

    sanitized = process_pcap(capture_path)

    assert [frame["start_register"] for frame in sanitized["frames"]] == [7, 42]
