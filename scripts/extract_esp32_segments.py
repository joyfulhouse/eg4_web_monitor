#!/usr/bin/env python3
"""Extract ESP32-C3 firmware segments for Ghidra analysis.

Parses the ESP32 image header and extracts individual segments
with proper load addresses for disassembly.
"""

import struct
import sys
from pathlib import Path


def extract_segments(firmware_path: Path, output_dir: Path) -> list[dict]:
    """Extract segments from an ESP32-C3 firmware image."""
    data = firmware_path.read_bytes()

    # ESP32 image header (24 bytes)
    magic = data[0]
    segment_count = data[1]
    data[2]
    data[3]
    entry_point = struct.unpack_from("<I", data, 4)[0]

    print(f"Magic: 0x{magic:02X}")
    print(f"Segments: {segment_count}")
    print(f"Entry point: 0x{entry_point:08X}")

    # Extended header at offset 8 (16 bytes)
    # Segments start at offset 24 (0x18)
    offset = 0x18
    segments = []

    for i in range(segment_count):
        load_addr = struct.unpack_from("<I", data, offset)[0]
        seg_len = struct.unpack_from("<I", data, offset + 4)[0]
        seg_data = data[offset + 8 : offset + 8 + seg_len]

        # Identify memory type
        if 0x3C000000 <= load_addr < 0x3D000000:
            mem_type = "DROM"
        elif 0x3FC00000 <= load_addr < 0x3FD00000:
            mem_type = "DRAM"
        elif 0x40380000 <= load_addr < 0x40400000:
            mem_type = "IRAM"
        elif 0x42000000 <= load_addr < 0x43000000:
            mem_type = "IROM"
        else:
            mem_type = "UNKNOWN"

        seg_info = {
            "index": i,
            "load_addr": load_addr,
            "length": seg_len,
            "file_offset": offset + 8,
            "mem_type": mem_type,
        }
        segments.append(seg_info)

        # Save segment to file
        seg_filename = f"seg{i}_{mem_type}_0x{load_addr:08X}.bin"
        seg_path = output_dir / seg_filename
        seg_path.write_bytes(seg_data)

        print(
            f"  Segment {i}: {mem_type} addr=0x{load_addr:08X} len=0x{seg_len:X} ({seg_len:,} bytes) -> {seg_filename}"
        )

        offset += 8 + seg_len

    # Also create a combined flat binary for Ghidra
    # Map IROM (segment 3) which contains the main application code
    irom_seg = next((s for s in segments if s["mem_type"] == "IROM"), None)
    if irom_seg:
        irom_data = data[
            irom_seg["file_offset"] : irom_seg["file_offset"] + irom_seg["length"]
        ]
        flat_path = output_dir / "app_code_IROM.bin"
        flat_path.write_bytes(irom_data)
        print(f"\n  Main app code: {flat_path} (load at 0x{irom_seg['load_addr']:08X})")

    # IRAM segments (bootloader + interrupt vectors)
    iram_segs = [s for s in segments if s["mem_type"] == "IRAM"]
    if iram_segs:
        # Combine IRAM segments
        min_addr = min(s["load_addr"] for s in iram_segs)
        max_end = max(s["load_addr"] + s["length"] for s in iram_segs)
        iram_combined = bytearray(max_end - min_addr)
        for s in iram_segs:
            seg_data = data[s["file_offset"] : s["file_offset"] + s["length"]]
            start = s["load_addr"] - min_addr
            iram_combined[start : start + s["length"]] = seg_data
        iram_path = output_dir / f"iram_combined_0x{min_addr:08X}.bin"
        iram_path.write_bytes(iram_combined)
        print(
            f"  Combined IRAM: {iram_path} (load at 0x{min_addr:08X}, {len(iram_combined):,} bytes)"
        )

    return segments


def main() -> None:
    fw_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("scratchpad/firmware/E_V2_10.bin")
    )
    output_dir = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else Path("scratchpad/firmware/segments")
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Extracting segments from: {fw_path}")
    print(f"Output directory: {output_dir}\n")

    segments = extract_segments(fw_path, output_dir)

    # Write a Ghidra import script
    ghidra_script = output_dir / "ghidra_import.py"
    ghidra_script.write_text(f"""\
# Ghidra Python script to set up memory map for ESP32-C3 dongle firmware
# Run this after importing the flat binary

from ghidra.program.model.mem import MemoryBlockType

program = getCurrentProgram()
memory = program.getMemory()
listing = program.getListing()

# ESP32-C3 memory map
print("Setting up ESP32-C3 memory map...")

# Segments from firmware:
{
        "".join(
            f'''# Segment {s['index']}: {s['mem_type']} at 0x{s['load_addr']:08X}, length 0x{s['length']:X}
'''
            for s in segments
        )
    }
""")

    print(f"\n  Ghidra import script: {ghidra_script}")
    print("\nTo analyze with Ghidra headless:")
    print("  analyzeHeadless /tmp/ghidra_project esp32_dongle \\")
    print(f"    -import {output_dir / 'app_code_IROM.bin'} \\")
    print("    -processor RISCV:LE:32:RV32IC \\")
    print("    -loader BinaryLoader \\")
    print("    -loader-baseAddr 0x42000020 \\")
    print("    -analysisTimeoutPerFile 600")


if __name__ == "__main__":
    main()
