#!/usr/bin/env python3
"""Extract firmware binaries from a pcap capture of an EG4 OTA upgrade.

Parses the cloud protocol frames to reconstruct firmware .hex files from
the two-pass OTA upgrade (App firmware + Parameter table).

Protocol summary:
  - 0x21 (init): announces firmware pass with chunk count + hash
  - 0x22 (data): sequential 768-byte chunks of firmware data
  - Last 0x22 per pass: contains firmware_id(4B) + CRC-16(2B) trailer

Usage:
    uv run python scripts/extract_firmware_from_pcap.py <pcap_file>
"""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import dpkt
except ImportError:
    print("ERROR: dpkt required. Install with: uv add dpkt")
    sys.exit(1)


# ── Protocol constants ──────────────────────────────────────────────────

CHUNK_HEADER_SIZE = 6  # type(1) + subcmd(1) + page_count(2) + page_addr(2)
FW_ID_SIZE = 4
CRC_SIZE = 2
TRAILER_SIZE = FW_ID_SIZE + CRC_SIZE  # 6 bytes at end of final chunk


# ── CRC implementations ────────────────────────────────────────────────


def _build_crc16_table(poly: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC16_MODBUS_TABLE = _build_crc16_table(0xA001)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    table = _CRC16_MODBUS_TABLE
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFF


def _build_ccitt_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        table.append(crc & 0xFFFF)
    return table


_CRC16_CCITT_TABLE = _build_ccitt_table()


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    table = _CRC16_CCITT_TABLE
    for b in data:
        crc = table[((crc >> 8) ^ b) & 0xFF] ^ ((crc << 8) & 0xFFFF)
    return crc & 0xFFFF


def crc16_xmodem(data: bytes) -> int:
    return crc16_ccitt(data, init=0x0000)


def checksum16(data: bytes) -> int:
    """Simple 16-bit sum of all bytes (LE word pairs)."""
    mv = memoryview(data)
    total = sum(mv)  # fast byte sum
    return total & 0xFFFF


def checksum16_words(data: bytes) -> int:
    """16-bit sum of LE 16-bit words."""
    total = 0
    for i in range(0, len(data) - 1, 2):
        total += int.from_bytes(data[i : i + 2], "little")
    if len(data) % 2:
        total += data[-1]
    return total & 0xFFFF


# ── Data classes ────────────────────────────────────────────────────────


@dataclass
class InitFrame:
    """Parsed 0x21 firmware init frame."""

    serial: str
    fw_id_bytes: bytes  # 4-byte firmware identifier
    fw_id: str  # ASCII representation
    chunk_count: int
    hash_bytes: bytes  # 6-byte hash from init

    @classmethod
    def from_modbus(cls, md: bytes) -> InitFrame:
        serial = md[2:12].decode("ascii", errors="replace").rstrip("\x00")
        id_b0 = md[12:14]  # start_reg bytes
        id_b1 = md[14:16]  # first 2 metadata bytes
        fw_id_bytes = id_b0 + id_b1
        fw_id = "".join(
            chr(b) if 0x20 <= b < 0x7F else f"[{b:02X}]" for b in fw_id_bytes
        )
        chunk_count = int.from_bytes(md[16:18], "little")
        hash_bytes = md[18:24]
        return cls(serial, fw_id_bytes, fw_id, chunk_count, hash_bytes)


@dataclass
class DataChunk:
    """Parsed 0x22 firmware data chunk."""

    seq: int
    fw_type: int  # byte [14] — 0x42=App, 0x02=Para
    subcmd: int  # byte [15] — 0x04=data, 0x08=end, etc.
    page_count: int  # bytes [16:18] LE
    page_addr: int  # bytes [18:20] LE
    raw_payload: bytes  # everything after 14-byte modbus header
    modbus_len: int  # total modbus data length


@dataclass
class FirmwarePass:
    """One complete firmware transfer pass."""

    init: InitFrame
    chunks: dict[int, DataChunk] = field(default_factory=dict)
    pass_name: str = ""


# ── Intel HEX writer ───────────────────────────────────────────────────


def write_intel_hex(data: bytes, filepath: str, base_addr: int = 0) -> None:
    """Write binary data as Intel HEX format."""
    lines: list[str] = []
    offset = 0
    current_upper = -1

    while offset < len(data):
        addr = base_addr + offset
        upper = (addr >> 16) & 0xFFFF
        lower = addr & 0xFFFF

        # Emit extended linear address record if upper changed
        if upper != current_upper:
            rec = struct.pack(">BHB", 2, 0, 4) + struct.pack(">H", upper)
            chk = (-sum(rec)) & 0xFF
            lines.append(f":{rec.hex().upper()}{chk:02X}")
            current_upper = upper

        # Data record — 16 bytes per line
        chunk_len = min(16, len(data) - offset)
        rec = (
            struct.pack(">BHB", chunk_len, lower, 0) + data[offset : offset + chunk_len]
        )
        chk = (-sum(rec)) & 0xFF
        lines.append(f":{rec.hex().upper()}{chk:02X}")
        offset += chunk_len

    # EOF record
    lines.append(":00000001FF")

    Path(filepath).write_text("\n".join(lines) + "\n")


# ── Pcap parsing ───────────────────────────────────────────────────────


def parse_pcap_frames(pcap_path: str) -> tuple[list[tuple[str, bytes]], str, str]:
    """Parse pcap and extract cloud protocol frames directly from each packet.

    Returns (frames_list, dongle_ip, cloud_ip) where frames_list is
    [(direction, frame_bytes), ...] with direction = 'c2d' or 'd2c'.

    SLL2 captures duplicate each packet across interfaces. We deduplicate
    by tracking TCP sequence numbers.
    """
    frames: list[tuple[str, bytes]] = []
    dongle_ip = ""
    cloud_ip = ""
    seen: set[tuple] = set()

    with open(pcap_path, "rb") as f:
        try:
            pcap = dpkt.pcap.Reader(f)
        except ValueError:
            f.seek(0)
            pcap = dpkt.pcapng.Reader(f)

        link_type = pcap.datalink()

        for _ts, buf in pcap:
            ip_offset = {276: 20, 113: 16}.get(link_type)
            if ip_offset is not None:
                if len(buf) <= ip_offset + 20:
                    continue
                try:
                    ip_pkt = dpkt.ip.IP(buf[ip_offset:])
                except dpkt.dpkt.UnpackError:
                    continue
            else:
                try:
                    ip_pkt = dpkt.ethernet.Ethernet(buf).data
                except (dpkt.dpkt.UnpackError, AttributeError):
                    continue

            if not isinstance(ip_pkt, dpkt.ip.IP) or ip_pkt.p != dpkt.ip.IP_PROTO_TCP:
                continue
            tcp = ip_pkt.data
            if not isinstance(tcp, dpkt.tcp.TCP) or not tcp.data:
                continue

            # Deduplicate SLL2 interface mirrors
            dedup_key = (ip_pkt.src, ip_pkt.dst, tcp.seq, len(tcp.data))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            src = ".".join(str(b) for b in ip_pkt.src)
            dst = ".".join(str(b) for b in ip_pkt.dst)

            if not dongle_ip:
                if src.startswith("10."):
                    dongle_ip, cloud_ip = src, dst
                elif dst.startswith("10."):
                    dongle_ip, cloud_ip = dst, src

            direction = (
                "c2d" if src == cloud_ip else "d2c" if src == dongle_ip else None
            )
            if direction is None:
                continue

            # Extract frames directly from this packet's TCP payload
            pkt_frames = find_frames(bytes(tcp.data))
            for frame in pkt_frames:
                frames.append((direction, frame))

    return frames, dongle_ip, cloud_ip


def find_frames(data: bytes) -> list[bytes]:
    """Find all 0xA1 0x1A cloud protocol frames in reassembled TCP stream."""
    frames: list[bytes] = []
    i = 0
    while i < len(data) - 6:
        if data[i] == 0xA1 and data[i + 1] == 0x1A:
            frame_len = int.from_bytes(data[i + 4 : i + 6], "little")
            total = 6 + frame_len
            if i + total <= len(data):
                frames.append(data[i : i + total])
                i += total
                continue
        i += 1
    return frames


def extract_modbus_data(frame: bytes) -> tuple[int, bytes] | None:
    """Extract (modbus_func, modbus_data) from a cloud protocol frame."""
    if len(frame) < 19 or frame[7] != 0xC2:
        return None
    payload = frame[18:]
    if len(payload) < 16:
        return None
    md = payload[2:]
    if len(md) < 15:
        return None
    return md[1], md


# ── Main extraction ────────────────────────────────────────────────────


def extract_firmware_passes(pcap_path: str) -> list[FirmwarePass]:
    """Extract all firmware passes from a pcap capture."""
    all_frames, dongle_ip, cloud_ip = parse_pcap_frames(pcap_path)
    print(f"Dongle: {dongle_ip}  Cloud: {cloud_ip}")

    c2d_count = sum(1 for d, _ in all_frames if d == "c2d")
    d2c_count = sum(1 for d, _ in all_frames if d == "d2c")
    print(f"Frames: {c2d_count} cloud→dongle, {d2c_count} dongle→cloud")
    print()

    # Parse all cloud→dongle frames chronologically, splitting on 0x21 init frames
    passes: list[FirmwarePass] = []
    seen_inits: set[bytes] = set()

    for direction, frame in all_frames:
        if direction != "c2d":
            continue

        result = extract_modbus_data(frame)
        if result is None:
            continue
        func, md = result

        if func == 0x21:
            # Deduplicate retransmitted init frames
            if md in seen_inits:
                continue
            seen_inits.add(md)
            init = InitFrame.from_modbus(md)
            passes.append(FirmwarePass(init=init))
            print(
                f"Pass {len(passes)}: init fw_id={init.fw_id} chunks={init.chunk_count} "
                f"hash={init.hash_bytes.hex()}"
            )

        elif func == 0x22 and passes:
            seq = int.from_bytes(md[12:14], "little")
            chunk_payload = md[14:]
            if len(chunk_payload) < CHUNK_HEADER_SIZE:
                continue

            chunk = DataChunk(
                seq=seq,
                fw_type=chunk_payload[0],
                subcmd=chunk_payload[1],
                page_count=int.from_bytes(chunk_payload[2:4], "little"),
                page_addr=int.from_bytes(chunk_payload[4:6], "little"),
                raw_payload=chunk_payload,
                modbus_len=len(md),
            )

            current_pass = passes[-1]
            if seq not in current_pass.chunks:
                current_pass.chunks[seq] = chunk

    print()
    return passes


def reconstruct_pass(fp: FirmwarePass) -> tuple[bytearray, bytes, int]:
    """Reconstruct firmware binary from a single pass.

    Returns (firmware_data, fw_id_from_trailer, crc_from_trailer).
    """
    expected = fp.init.chunk_count
    actual = len(fp.chunks)
    seqs = sorted(fp.chunks.keys())

    print(f"  Chunks: {actual} captured, {expected} expected")

    # Check for gaps
    missing = set(range(1, seqs[-1] + 1)) - set(seqs) if seqs else set()
    if missing:
        print(f"  WARNING: {len(missing)} missing chunks: {sorted(missing)[:10]}")

    # The LAST chunk (seq == chunk_count) contains the finalization trailer:
    #   ... [fw_id 4B] [crc16 2B]
    # All other chunks are pure data after the 6-byte chunk header.
    final_seq = expected
    fw_id_trailer = b""
    crc_trailer = 0

    firmware = bytearray()

    for seq in sorted(fp.chunks.keys()):
        chunk = fp.chunks[seq]
        payload = chunk.raw_payload[CHUNK_HEADER_SIZE:]  # skip 6-byte header

        if seq == final_seq:
            # Final chunk: strip trailer
            if len(payload) >= TRAILER_SIZE:
                fw_id_trailer = payload[-TRAILER_SIZE:-CRC_SIZE]
                crc_trailer = int.from_bytes(payload[-CRC_SIZE:], "little")
                data = payload[:-TRAILER_SIZE]
            else:
                data = payload
        else:
            data = payload

        firmware.extend(data)

    print(f"  Firmware size: {len(firmware):,} bytes ({len(firmware) / 1024:.1f} KB)")

    if fw_id_trailer:
        trailer_str = "".join(
            chr(b) if 0x20 <= b < 0x7F else f"[{b:02X}]" for b in fw_id_trailer
        )
        print(f"  Trailer fw_id: {trailer_str} ({fw_id_trailer.hex()})")
        print(f"  Trailer CRC-16: 0x{crc_trailer:04X}")

    return firmware, fw_id_trailer, crc_trailer


def validate_crc(firmware: bytes, expected_crc: int) -> str | None:
    """Try multiple CRC algorithms to find one matching the expected value."""
    checks = {
        "CRC-16/Modbus": crc16_modbus(firmware),
        "CRC-16/CCITT-FALSE": crc16_ccitt(firmware, 0xFFFF),
        "CRC-16/XMODEM": crc16_xmodem(firmware),
        "Checksum-16 (byte sum)": checksum16(firmware),
        "Checksum-16 (negated)": (~checksum16(firmware)) & 0xFFFF,
        "Checksum-16 (LE words)": checksum16_words(firmware),
        "Checksum-16 (LE words neg)": (~checksum16_words(firmware)) & 0xFFFF,
    }

    for name, computed in checks.items():
        match = "✓ MATCH" if computed == expected_crc else ""
        print(f"    {name}: 0x{computed:04X} {match}")
        if computed == expected_crc:
            return name

    # Also try byte-swapped CRC
    swapped = ((expected_crc >> 8) & 0xFF) | ((expected_crc & 0xFF) << 8)
    for name, computed in checks.items():
        if computed == swapped:
            print(f"    {name} (byte-swapped): 0x{computed:04X} ✓ MATCH")
            return f"{name} (byte-swapped)"

    return None


def analyze_binary(data: bytes) -> None:
    """Print analysis of a firmware binary."""
    nonzero = sum(1 for b in data if b != 0)
    print(f"  Non-zero: {nonzero:,} / {len(data):,} ({100 * nonzero / len(data):.1f}%)")

    byte_counts = [0] * 256
    for b in data:
        byte_counts[b] += 1
    entropy = sum(
        -p / len(data) * math.log2(p / len(data)) for p in byte_counts if p > 0
    )
    print(f"  Entropy: {entropy:.2f} bits/byte")

    print(f"  First 32 bytes: {data[:32].hex()}")

    # Extract strings
    strings: list[str] = []
    cur: list[str] = []
    for b in data:
        if 0x20 <= b < 0x7F:
            cur.append(chr(b))
        else:
            if len(cur) >= 8:
                strings.append("".join(cur))
            cur = []
    if len(cur) >= 8:
        strings.append("".join(cur))

    if strings:
        print(f"  Strings ({len(strings)} total, showing first 15):")
        for s in strings[:15]:
            print(f"    {s}")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <pcap_file>")
        sys.exit(1)

    pcap_path = sys.argv[1]
    output_dir = Path(pcap_path).parent
    passes = extract_firmware_passes(pcap_path)

    # Output filenames per pass
    pass_names = [
        "FAAB-27xx_20260330_App",
        "fAAB-xx27_Para375_20260330",
    ]

    for i, fp in enumerate(passes):
        name = pass_names[i] if i < len(pass_names) else f"pass{i + 1}"
        fp.pass_name = name
        print(f"{'=' * 60}")
        print(f"PASS {i + 1}: {name}")
        print(f"{'=' * 60}")

        firmware, fw_id_trailer, crc_trailer = reconstruct_pass(fp)

        if not firmware:
            print("  No data extracted!")
            continue

        # Validate fw_id trailer matches init frame
        if fw_id_trailer:
            if fw_id_trailer == fp.init.fw_id_bytes:
                print("  Firmware ID: MATCHES init frame ✓")
            else:
                print(
                    f"  Firmware ID: MISMATCH! init={fp.init.fw_id_bytes.hex()} "
                    f"trailer={fw_id_trailer.hex()}"
                )

        # Validate chunk count
        expected = fp.init.chunk_count
        actual = len(fp.chunks)
        if actual == expected:
            print(f"  Chunk count: {actual}/{expected} ✓")
        else:
            print(f"  Chunk count: {actual}/{expected} ✗ MISMATCH")

        # Validate CRC
        print(f"  CRC validation (expected 0x{crc_trailer:04X}):")
        crc_algo = validate_crc(firmware, crc_trailer)
        if crc_algo:
            print(f"  CRC algorithm: {crc_algo} ✓")
        else:
            # Try CRC on firmware + fw_id (maybe CRC covers the ID too)
            print("  Trying CRC over firmware+fw_id:")
            crc_algo = validate_crc(firmware + fw_id_trailer, crc_trailer)
            if crc_algo:
                print(f"  CRC algorithm (with fw_id): {crc_algo} ✓")
            else:
                print("  CRC: no matching algorithm found")

        print()
        analyze_binary(firmware)

        # Write raw binary
        bin_path = output_dir / f"{name}.bin"
        bin_path.write_bytes(firmware)
        print(f"\n  Binary: {bin_path} ({len(firmware):,} bytes)")

        # Write Intel HEX
        hex_path = output_dir / f"{name}.hex"
        # Use page address from first chunk as base address hint
        first_chunk = fp.chunks.get(1)
        base_addr = 0
        if first_chunk:
            base_addr = first_chunk.page_addr * 256
            print(f"  Base address: 0x{base_addr:08X} (page {first_chunk.page_addr})")
        write_intel_hex(firmware, str(hex_path), base_addr)
        print(f"  Intel HEX: {hex_path}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
