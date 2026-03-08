#!/usr/bin/env python3
"""Verify cloud protocol register data against known register maps.

Extracts register values from decoded pcap frames and cross-references
against known inverter and GridBOSS register maps to validate our
protocol understanding.

Usage:
    python scripts/verify_cloud_registers.py /tmp/pcap_extract/all_dongles_300s.pcap

Requires: dpkt (uv pip install dpkt)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import dpkt
except ImportError:
    print("ERROR: dpkt is required. Install with: uv pip install dpkt")
    sys.exit(1)

# Import the frame parsing from our decoder
sys.path.insert(0, str(Path(__file__).parent))
from decode_cloud_frames import (
    _extract_ip_from_buf,
    find_frames,
)


# ============================================================================
# Register Maps for Verification
# ============================================================================

# GridBOSS input registers (from GRIDBOSS_REGISTER_MAP.md probe)
# Format: (addr, name, scale_factor, unit, expected_range_min, expected_range_max)
GRIDBOSS_REGS: list[tuple[int, str, float, str, float, float]] = [
    (1, "grid_voltage", 0.1, "V", 200.0, 280.0),
    (2, "ups_voltage", 0.1, "V", 0.0, 280.0),
    (3, "gen_voltage", 0.1, "V", 0.0, 280.0),
    (4, "grid_l1_voltage", 0.1, "V", 100.0, 145.0),
    (5, "grid_l2_voltage", 0.1, "V", 100.0, 145.0),
    (6, "ups_l1_voltage", 0.1, "V", 0.0, 145.0),
    (7, "ups_l2_voltage", 0.1, "V", 0.0, 145.0),
    (8, "gen_l1_voltage", 0.1, "V", 0.0, 145.0),
    (9, "gen_l2_voltage", 0.1, "V", 0.0, 145.0),
    (10, "grid_l1_current", 0.1, "A", 0.0, 200.0),
    (11, "grid_l2_current", 0.1, "A", 0.0, 200.0),
    (16, "ups_l1_current", 0.1, "A", 0.0, 200.0),
    (17, "ups_l2_current", 0.1, "A", 0.0, 200.0),
    # Power registers (signed 32-bit split across two regs)
    (128, "phase_lock_freq", 0.01, "Hz", 55.0, 65.0),
    (129, "grid_freq", 0.01, "Hz", 55.0, 65.0),
]

# Inverter input registers (from pylxpweb registers.py)
# Only the first 128 registers (group 0, frame 0)
INVERTER_REGS: list[tuple[int, str, float, str, float, float]] = [
    (0, "status", 1.0, "", 0.0, 20.0),
    (1, "v_pv1", 0.1, "V", 0.0, 600.0),
    (2, "v_pv2", 0.1, "V", 0.0, 600.0),
    (3, "v_pv3", 0.1, "V", 0.0, 600.0),
    (4, "v_bat", 0.01, "V", 40.0, 60.0),
    # reg 5: packed SOC(low byte)/SOH(high byte)
    (16, "v_ac_r", 0.1, "V", 100.0, 280.0),
    (17, "v_ac_s", 0.1, "V", 0.0, 280.0),
    (18, "v_ac_t", 0.1, "V", 0.0, 280.0),
    (19, "f_ac", 0.01, "Hz", 55.0, 65.0),
    (26, "v_eps_r", 0.1, "V", 0.0, 280.0),
    (27, "v_eps_s", 0.1, "V", 0.0, 280.0),
    (29, "f_eps", 0.01, "Hz", 0.0, 65.0),
    (43, "v_bus1", 0.1, "V", 0.0, 500.0),
    (44, "v_bus2", 0.1, "V", 0.0, 500.0),
    (64, "t_inner", 1.0, "C", -20.0, 80.0),
    (65, "t_radiator1", 1.0, "C", -20.0, 80.0),
    (66, "t_radiator2", 1.0, "C", -20.0, 80.0),
    (67, "t_bat", 1.0, "C", -20.0, 80.0),
]


@dataclass
class RegisterDump:
    """Register values extracted from a single 0xC2 frame."""

    dongle_serial: str
    inv_serial: str
    group: int
    start_reg: int
    values: list[int]  # uint16 values in register order


def extract_register_dumps(pcap_path: str) -> list[RegisterDump]:
    """Extract register dumps from pcap file."""
    dumps: list[RegisterDump] = []
    seen: set[tuple[str, int, int]] = set()

    f = open(pcap_path, "rb")
    try:
        try:
            pcap = dpkt.pcap.Reader(f)
        except ValueError:
            f.seek(0)
            pcap = dpkt.pcapng.Reader(f)

        link_type = pcap.datalink()
        cloud_port = 4346
        seg_seen: set[tuple[str, int, int]] = set()

        for _timestamp, buf in pcap:
            ip = _extract_ip_from_buf(buf, link_type)
            if ip is None:
                continue
            if not isinstance(ip.data, dpkt.tcp.TCP):
                continue
            tcp = ip.data
            if not tcp.data:
                continue
            if tcp.dport != cloud_port:
                continue  # Only dongle->cloud

            seg_key = ("d", tcp.seq, len(tcp.data))
            if seg_key in seg_seen:
                continue
            seg_seen.add(seg_key)

            for _offset, frame_bytes in find_frames(tcp.data):
                if len(frame_bytes) < 19:
                    continue
                func = frame_bytes[7]
                if func != 0xC2:
                    continue

                dongle_serial = (
                    frame_bytes[8:18].decode("ascii", errors="replace").rstrip("\x00")
                )
                payload = frame_bytes[18:]

                if len(payload) < 17:
                    continue

                group = payload[2]
                inv_serial = (
                    payload[4:14].decode("ascii", errors="replace").rstrip("\x00")
                )
                start_reg = int.from_bytes(payload[14:16], "little")
                data = payload[17:]  # Register data starts at offset 17

                # Parse register values as uint16 little-endian
                values: list[int] = []
                for i in range(0, len(data) - 1, 2):
                    val = int.from_bytes(data[i : i + 2], "little")
                    values.append(val)

                # Dedup: only take first instance per (serial, group, start_reg)
                key = (dongle_serial, group, start_reg)
                if key in seen:
                    continue
                seen.add(key)

                dumps.append(
                    RegisterDump(
                        dongle_serial=dongle_serial,
                        inv_serial=inv_serial,
                        group=group,
                        start_reg=start_reg,
                        values=values,
                    )
                )
    finally:
        f.close()

    return dumps


def get_reg_value(dump: RegisterDump, addr: int) -> int | None:
    """Get a register value by address from a dump."""
    idx = addr - dump.start_reg
    if 0 <= idx < len(dump.values):
        return dump.values[idx]
    return None


def verify_gridboss(dumps: list[RegisterDump]) -> None:
    """Verify GridBOSS register values against expected ranges."""
    gb_dumps = [d for d in dumps if d.group == 1]
    if not gb_dumps:
        print("\nNo GridBOSS (group=1) frames found.")
        return

    print(f"\n{'=' * 80}")
    print("GridBOSS Register Verification (group=1)")
    print(f"{'=' * 80}")

    for dump in gb_dumps:
        print(f"\n  Dongle: {dump.dongle_serial}  Inverter: {dump.inv_serial}")
        print(
            f"  Register range: {dump.start_reg}-{dump.start_reg + len(dump.values) - 1}"
        )
        print(
            f"  {'Addr':>5} {'Name':<25} {'Raw':>6} {'Scaled':>10} {'Unit':>5}  {'Status'}"
        )
        print(f"  {'─' * 70}")

        for addr, name, scale, unit, lo, hi in GRIDBOSS_REGS:
            raw = get_reg_value(dump, addr)
            if raw is None:
                continue

            # Handle signed values (for power registers)
            if raw > 32767:
                raw_signed = raw - 65536
            else:
                raw_signed = raw

            scaled = raw_signed * scale
            in_range = lo <= abs(scaled) <= hi or (lo == 0.0 and scaled == 0.0)
            status = "OK" if in_range else f"SUSPECT (expected {lo}-{hi})"

            print(
                f"  {addr:>5} {name:<25} {raw:>6} {scaled:>10.2f} {unit:>5}  {status}"
            )

        # Show raw hex for first 40 regs for manual inspection
        if dump.start_reg == 0 and len(dump.values) >= 40:
            print("\n  First 40 register values (raw uint16 LE):")
            for row_start in range(0, 40, 10):
                vals = dump.values[row_start : row_start + 10]
                line = " ".join(f"{v:5d}" for v in vals)
                print(f"  [{row_start:3d}-{row_start + len(vals) - 1:3d}] {line}")


def verify_inverter(dumps: list[RegisterDump]) -> None:
    """Verify inverter register values against expected ranges.

    Try both little-endian and big-endian interpretations to determine
    the correct byte order for register data in cloud frames.
    """
    inv_dumps = [d for d in dumps if d.group == 0 and d.start_reg == 0]
    if not inv_dumps:
        print("\nNo inverter (group=0, start=0) frames found.")
        return

    print(f"\n{'=' * 80}")
    print("Inverter Register Verification (group=0, regs 0-127)")
    print(f"{'=' * 80}")

    for dump in inv_dumps:
        print(f"\n  Dongle: {dump.dongle_serial}  Inverter: {dump.inv_serial}")
        print(f"  Register count: {len(dump.values)}")

        # Try LE interpretation (what we're currently doing)
        print("\n  --- Little-Endian Interpretation ---")
        print(
            f"  {'Addr':>5} {'Name':<20} {'Raw':>6} {'Scaled':>10} {'Unit':>5}  {'Status'}"
        )
        print(f"  {'─' * 65}")

        ok_count_le = 0
        total_count = 0
        for addr, name, scale, unit, lo, hi in INVERTER_REGS:
            raw = get_reg_value(dump, addr)
            if raw is None:
                continue
            total_count += 1
            if raw > 32767:
                raw_signed = raw - 65536
            else:
                raw_signed = raw
            scaled = raw_signed * scale
            in_range = lo <= abs(scaled) <= hi or (lo == 0.0 and scaled == 0.0)
            if in_range:
                ok_count_le += 1
            status = "OK" if in_range else f"SUSPECT ({lo}-{hi})"
            print(
                f"  {addr:>5} {name:<20} {raw:>6} {scaled:>10.2f} {unit:>5}  {status}"
            )

        # Try BE interpretation
        print("\n  --- Big-Endian Interpretation ---")
        print(
            f"  {'Addr':>5} {'Name':<20} {'Raw':>6} {'Scaled':>10} {'Unit':>5}  {'Status'}"
        )
        print(f"  {'─' * 65}")

        ok_count_be = 0
        for addr, name, scale, unit, lo, hi in INVERTER_REGS:
            idx = addr - dump.start_reg
            if 0 <= idx < len(dump.values):
                # Re-interpret the uint16 as big-endian by byte-swapping
                le_val = dump.values[idx]
                be_val = ((le_val & 0xFF) << 8) | ((le_val >> 8) & 0xFF)
                if be_val > 32767:
                    raw_signed = be_val - 65536
                else:
                    raw_signed = be_val
                scaled = raw_signed * scale
                in_range = lo <= abs(scaled) <= hi or (lo == 0.0 and scaled == 0.0)
                if in_range:
                    ok_count_be += 1
                status = "OK" if in_range else f"SUSPECT ({lo}-{hi})"
                print(
                    f"  {addr:>5} {name:<20} {be_val:>6} {scaled:>10.2f} {unit:>5}  {status}"
                )

        print(
            f"\n  Summary: LE={ok_count_le}/{total_count} OK, BE={ok_count_be}/{total_count} OK"
        )
        winner = "LE" if ok_count_le >= ok_count_be else "BE"
        print(f"  Best fit: {winner}")

        # SOC/SOH special decode (reg 5 is packed: SOC=low byte, SOH=high byte)
        reg5 = get_reg_value(dump, 5)
        if reg5 is not None:
            soc_le = reg5 & 0xFF
            soh_le = (reg5 >> 8) & 0xFF
            reg5_be = ((reg5 & 0xFF) << 8) | ((reg5 >> 8) & 0xFF)
            soc_be = reg5_be & 0xFF
            soh_be = (reg5_be >> 8) & 0xFF
            print(f"\n  SOC/SOH (reg 5 = 0x{reg5:04X}):")
            print(f"    LE: SOC={soc_le}%, SOH={soh_le}%")
            print(f"    BE: SOC={soc_be}%, SOH={soh_be}%")

        # Raw register dump for first 32 regs
        print("\n  First 32 registers (raw uint16 LE):")
        for row_start in range(0, min(32, len(dump.values)), 8):
            end = min(row_start + 8, len(dump.values))
            vals = dump.values[row_start:end]
            hex_vals = " ".join(f"0x{v:04X}" for v in vals)
            dec_vals = " ".join(f"{v:>6}" for v in vals)
            print(f"  [{row_start:3d}-{end - 1:3d}] {hex_vals}")
            print(f"          {dec_vals}")


def verify_frame5000(dumps: list[RegisterDump]) -> None:
    """Analyze the mystery register block starting at 5000."""
    r5000_dumps = [d for d in dumps if d.start_reg == 5000]
    if not r5000_dumps:
        print("\nNo reg-5000 frames found.")
        return

    print(f"\n{'=' * 80}")
    print("Mystery Register Block 5000-5127 Analysis")
    print(f"{'=' * 80}")

    for dump in r5000_dumps:
        print(f"\n  Dongle: {dump.dongle_serial}  Inverter: {dump.inv_serial}")
        print(f"  Register count: {len(dump.values)}")

        # Count non-zero values
        non_zero = [(i, v) for i, v in enumerate(dump.values) if v != 0]
        zero_count = len(dump.values) - len(non_zero)
        print(f"  Non-zero: {len(non_zero)}, Zero: {zero_count}")

        if non_zero:
            print("\n  Non-zero registers:")
            print(f"  {'Addr':>6} {'Raw':>6} {'Hex':>8} {'Signed':>8}")
            print(f"  {'─' * 35}")
            for idx, val in non_zero[:50]:  # Limit to first 50
                addr = 5000 + idx
                signed = val - 65536 if val > 32767 else val
                print(f"  {addr:>6} {val:>6} 0x{val:04X} {signed:>8}")

        # Show first 32 raw values
        print("\n  First 32 registers (raw):")
        for row_start in range(0, min(32, len(dump.values)), 8):
            end = min(row_start + 8, len(dump.values))
            vals = dump.values[row_start:end]
            hex_vals = " ".join(f"0x{v:04X}" for v in vals)
            print(f"  [{5000 + row_start:5d}-{5000 + end - 1:5d}] {hex_vals}")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <pcap_file>")
        sys.exit(1)

    pcap_path = sys.argv[1]
    if not Path(pcap_path).exists():
        print(f"ERROR: File not found: {pcap_path}")
        sys.exit(1)

    print(f"Extracting register data from: {pcap_path}")
    dumps = extract_register_dumps(pcap_path)
    print(f"Found {len(dumps)} unique register dumps")

    # Summarize what we found
    by_serial: dict[str, list[RegisterDump]] = {}
    for d in dumps:
        by_serial.setdefault(d.dongle_serial, []).append(d)

    for serial, serial_dumps in sorted(by_serial.items()):
        inv = serial_dumps[0].inv_serial
        grp = serial_dumps[0].group
        ranges = [(d.start_reg, d.start_reg + len(d.values) - 1) for d in serial_dumps]
        ranges_str = ", ".join(f"{s}-{e}" for s, e in sorted(ranges))
        print(f"  {serial} (inv={inv}, grp={grp}): {ranges_str}")

    verify_gridboss(dumps)
    verify_inverter(dumps)
    verify_frame5000(dumps)


if __name__ == "__main__":
    main()
