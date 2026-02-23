#!/usr/bin/env python3
"""Decode EG4 cloud protocol frames from a pcap capture.

Reads a pcap file containing TCP traffic between a WiFi dongle and
us2.solarcloudsystem.com:4346, decodes all 0xA1/0x1A frames, and
produces a human-readable analysis.

Usage:
    python scripts/decode_cloud_frames.py scratchpad/firmware/dongle_capture.pcap

Requires: dpkt (pip install dpkt)

The script reconstructs TCP streams and identifies:
- 0xC1 heartbeat frames (timing, format)
- 0xC2 data frames (register groups, values)
- 0xC3 GET_PARAM commands (register ranges)
- 0xC4 SET_PARAM commands (register writes)
- Server→dongle responses (any direction)
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import dpkt
except ImportError:
    print("ERROR: dpkt is required. Install with: uv pip install dpkt")
    sys.exit(1)


# Cloud protocol constants
FRAME_MAGIC = bytes([0xA1, 0x1A])
FUNC_NAMES = {
    0xC1: "HEARTBEAT",
    0xC2: "DATA_TX",
    0xC3: "GET_PARAM",
    0xC4: "SET_PARAM",
}
MODBUS_FUNC_NAMES = {
    0x03: "READ_HOLDING",
    0x04: "READ_INPUT",
    0x06: "WRITE_SINGLE",
    0x10: "WRITE_MULTI",
}


def compute_crc16(data: bytes) -> int:
    """CRC-16/Modbus."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass
class DecodedFrame:
    """A decoded cloud protocol frame."""

    timestamp: float
    direction: str  # "dongle→cloud" or "cloud→dongle"
    func: int
    func_name: str
    serial: str
    payload: bytes
    raw_size: int
    details: str = ""


@dataclass
class StreamState:
    """TCP stream reassembly state."""

    buffer: bytearray = field(default_factory=bytearray)


def find_frames(data: bytes) -> list[tuple[int, bytes]]:
    """Find all 0xA1 0x1A frames in a byte buffer.

    Returns list of (offset, frame_bytes) tuples.
    """
    frames = []
    i = 0
    while i < len(data) - 6:
        if data[i] == 0xA1 and data[i + 1] == 0x1A:
            # Read frame length
            frame_len = int.from_bytes(data[i + 4 : i + 6], "little")
            total = 6 + frame_len
            if i + total <= len(data):
                frames.append((i, data[i : i + total]))
                i += total
                continue
        i += 1
    return frames


def decode_frame(
    frame_bytes: bytes, timestamp: float, direction: str
) -> DecodedFrame | None:
    """Decode a single cloud protocol frame."""
    if len(frame_bytes) < 20:  # Minimum: 18 preamble + 2 CRC
        return None

    func = frame_bytes[7]
    serial = frame_bytes[8:18].decode("ascii", errors="replace").rstrip("\x00")

    # Verify CRC
    inner = frame_bytes[6:-2]
    crc_received = int.from_bytes(frame_bytes[-2:], "little")
    crc_computed = compute_crc16(inner)
    crc_ok = crc_received == crc_computed

    payload = frame_bytes[18:-2]

    details_parts = []
    if not crc_ok:
        details_parts.append(f"BAD CRC (got 0x{crc_received:04X}, expected 0x{crc_computed:04X})")

    func_name = FUNC_NAMES.get(func, f"UNKNOWN(0x{func:02X})")

    # Decode payload based on function
    if func == 0xC1:
        if payload:
            details_parts.append(f"status=0x{payload[0]:02X}")
    elif func == 0xC2 and len(payload) >= 3:
        details_parts.extend(_decode_modbus_rtu(payload))
    elif func == 0xC3 and len(payload) >= 4:
        start = int.from_bytes(payload[0:2], "little")
        end = int.from_bytes(payload[2:4], "little")
        details_parts.append(f"GET regs {start}-{end} ({end - start + 1} regs)")
    elif func == 0xC4 and len(payload) >= 4:
        param_code = int.from_bytes(payload[0:2], "little")
        data_len = int.from_bytes(payload[2:4], "little")
        details_parts.append(f"SET param_code={param_code} data_len={data_len}")
        if len(payload) > 4:
            hex_data = payload[4:].hex()
            details_parts.append(f"data={hex_data}")

    return DecodedFrame(
        timestamp=timestamp,
        direction=direction,
        func=func,
        func_name=func_name,
        serial=serial,
        payload=payload,
        raw_size=len(frame_bytes),
        details=", ".join(details_parts),
    )


def _decode_modbus_rtu(payload: bytes) -> list[str]:
    """Decode Modbus RTU response embedded in 0xC2 payload."""
    parts = []
    if len(payload) < 3:
        return ["(truncated Modbus RTU)"]

    slave_addr = payload[0]
    modbus_func = payload[1]
    func_name = MODBUS_FUNC_NAMES.get(modbus_func, f"0x{modbus_func:02X}")
    parts.append(f"slave={slave_addr} func={func_name}")

    if modbus_func in (0x03, 0x04):
        byte_count = payload[2]
        reg_count = byte_count // 2
        parts.append(f"byte_count={byte_count} ({reg_count} regs)")

        # Decode register values (big-endian per Modbus convention)
        if len(payload) >= 3 + byte_count:
            values = []
            for j in range(0, byte_count, 2):
                val = int.from_bytes(payload[3 + j : 3 + j + 2], "big")
                values.append(val)
            # Show first 5 and last 2 values for brevity
            if len(values) > 7:
                shown = [str(v) for v in values[:5]] + ["..."] + [str(v) for v in values[-2:]]
            else:
                shown = [str(v) for v in values]
            parts.append(f"values=[{', '.join(shown)}]")

        # Verify Modbus CRC
        if len(payload) >= 3 + byte_count + 2:
            modbus_data = payload[: 3 + byte_count]
            modbus_crc = int.from_bytes(
                payload[3 + byte_count : 3 + byte_count + 2], "little"
            )
            expected_crc = compute_crc16(modbus_data)
            if modbus_crc != expected_crc:
                parts.append(f"BAD MODBUS CRC (0x{modbus_crc:04X} vs 0x{expected_crc:04X})")
    else:
        parts.append(f"payload={payload[2:].hex()}")

    return parts


def process_pcap(pcap_path: str) -> list[DecodedFrame]:
    """Process a pcap file and extract all cloud protocol frames."""
    frames: list[DecodedFrame] = []
    streams: dict[tuple, StreamState] = {}

    with open(pcap_path, "rb") as f:
        try:
            pcap = dpkt.pcap.Reader(f)
        except ValueError:
            # Try pcapng format
            f.seek(0)
            pcap = dpkt.pcapng.Reader(f)

    cloud_port = 4346

    for timestamp, buf in pcap:
        try:
            eth = dpkt.ethernet.Ethernet(buf)
        except dpkt.dpkt.NeedData:
            continue

        if not isinstance(eth.data, dpkt.ip.IP):
            continue
        ip = eth.data

        if not isinstance(ip.data, dpkt.tcp.TCP):
            continue
        tcp = ip.data

        if not tcp.data:
            continue

        # Determine direction
        if tcp.dport == cloud_port:
            direction = "dongle->cloud"
        elif tcp.sport == cloud_port:
            direction = "cloud->dongle"
        else:
            continue

        # Find frames in TCP payload
        for _offset, frame_bytes in find_frames(tcp.data):
            decoded = decode_frame(frame_bytes, timestamp, direction)
            if decoded:
                frames.append(decoded)

    return frames


def print_analysis(frames: list[DecodedFrame]) -> None:
    """Print a human-readable analysis of decoded frames."""
    if not frames:
        print("No frames found in capture.")
        return

    print(f"\n{'=' * 80}")
    print(f"EG4 Cloud Protocol Traffic Analysis")
    print(f"{'=' * 80}")
    print(f"Total frames: {len(frames)}")

    # Count by direction and type
    dongle_frames = [f for f in frames if f.direction == "dongle->cloud"]
    cloud_frames = [f for f in frames if f.direction == "cloud->dongle"]
    print(f"Dongle → Cloud: {len(dongle_frames)}")
    print(f"Cloud → Dongle: {len(cloud_frames)}")

    # Count by function
    func_counts: dict[str, int] = {}
    for f in frames:
        func_counts[f.func_name] = func_counts.get(f.func_name, 0) + 1
    print(f"\nFrame types:")
    for name, count in sorted(func_counts.items()):
        print(f"  {name}: {count}")

    # Serials seen
    serials = {f.serial for f in frames}
    print(f"\nDongle serials: {', '.join(sorted(serials))}")

    # Heartbeat timing
    heartbeats = [f for f in frames if f.func == 0xC1 and f.direction == "dongle->cloud"]
    if len(heartbeats) >= 2:
        intervals = []
        for i in range(1, len(heartbeats)):
            intervals.append(heartbeats[i].timestamp - heartbeats[i - 1].timestamp)
        avg_interval = sum(intervals) / len(intervals)
        print(f"\nHeartbeat timing:")
        print(f"  Count: {len(heartbeats)}")
        print(f"  Avg interval: {avg_interval:.1f}s")
        print(f"  Min interval: {min(intervals):.1f}s")
        print(f"  Max interval: {max(intervals):.1f}s")

    # Data frame timing
    data_frames = [f for f in frames if f.func == 0xC2 and f.direction == "dongle->cloud"]
    if len(data_frames) >= 2:
        # Group by poll cycle (frames within 5s of each other = same cycle)
        cycles: list[list[DecodedFrame]] = []
        current_cycle: list[DecodedFrame] = [data_frames[0]]
        for i in range(1, len(data_frames)):
            if data_frames[i].timestamp - data_frames[i - 1].timestamp < 5.0:
                current_cycle.append(data_frames[i])
            else:
                cycles.append(current_cycle)
                current_cycle = [data_frames[i]]
        cycles.append(current_cycle)

        print(f"\nData transmission cycles: {len(cycles)}")
        print(f"  Frames per cycle: {[len(c) for c in cycles]}")
        if len(cycles) >= 2:
            cycle_intervals = []
            for i in range(1, len(cycles)):
                cycle_intervals.append(cycles[i][0].timestamp - cycles[i - 1][0].timestamp)
            avg_cycle = sum(cycle_intervals) / len(cycle_intervals)
            print(f"  Avg cycle interval: {avg_cycle:.1f}s")

    # Detailed frame log
    print(f"\n{'=' * 80}")
    print(f"Detailed Frame Log")
    print(f"{'=' * 80}")

    t0 = frames[0].timestamp if frames else 0
    for f in frames:
        ts = f.timestamp - t0
        dt = datetime.fromtimestamp(f.timestamp, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        print(
            f"[{ts:8.3f}s] [{dt}] {f.direction:15s} "
            f"{f.func_name:12s} serial={f.serial} "
            f"size={f.raw_size:4d}  {f.details}"
        )


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <pcap_file>")
        print(f"\nCapture traffic first:")
        print(f"  sudo tcpdump -i any host us2.solarcloudsystem.com and port 4346 -w capture.pcap")
        sys.exit(1)

    pcap_path = sys.argv[1]
    if not Path(pcap_path).exists():
        print(f"ERROR: File not found: {pcap_path}")
        sys.exit(1)

    print(f"Reading: {pcap_path}")
    frames = process_pcap(pcap_path)
    print_analysis(frames)


if __name__ == "__main__":
    main()
