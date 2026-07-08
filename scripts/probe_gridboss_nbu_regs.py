#!/usr/bin/env python3
"""Probe unknown GridBOSS input registers 50-51 and 84-87.

These registers are currently marked as "unused/unknown" in the GridBOSS
register map. The XLS export from the cloud portal shows `eNBU Day` and
`eNBUAll` columns (Non-Backup load energy) that don't map to any known
registers. Hypothesis: regs 50-51 are NBU daily energy L1/L2, and regs
84-87 are NBU lifetime energy L1/L2 (32-bit).

Also probes for generator energy registers (eGenDay, eGenAll from XLS).

Usage:
    uv run python scripts/probe_gridboss_nbu_regs.py

Requirements:
    - GridBOSS WiFi dongle must be reachable at 10.100.12.175:8000
    - No other client connected to the dongle (single-client limitation)
    - HA container should be stopped or in cloud-only mode
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add pylxpweb to path for development
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "python" / "pylxpweb" / "src")
)

from pylxpweb.transports.dongle import DongleTransport


# GridBOSS connection details (from HA config)
GRIDBOSS_HOST = "10.100.12.175"
GRIDBOSS_PORT = 8000
DONGLE_SERIAL = "DJ43404815"
INVERTER_SERIAL = "4524850115"

# Known register ranges for context
KNOWN_DAILY_ENERGY = {
    42: "load_energy_today_l1",
    43: "load_energy_today_l2",
    44: "ups_energy_today_l1",
    45: "ups_energy_today_l2",
    46: "grid_export_today_l1",
    47: "grid_export_today_l2",
    48: "grid_import_today_l1",
    49: "grid_import_today_l2",
    # 50-51: UNKNOWN (hypothesis: nbu_energy_today_l1/l2)
    52: "smart_load1_energy_today_l1",
    53: "smart_load1_energy_today_l2",
}

KNOWN_LIFETIME_ENERGY = {
    68: "load_energy_total_l1 (low)",
    69: "load_energy_total_l1 (high)",
    70: "load_energy_total_l2 (low)",
    71: "load_energy_total_l2 (high)",
    72: "ups_energy_total_l1 (low)",
    73: "ups_energy_total_l1 (high)",
    74: "ups_energy_total_l2 (low)",
    75: "ups_energy_total_l2 (high)",
    76: "grid_export_total_l1 (low)",
    77: "grid_export_total_l1 (high)",
    78: "grid_export_total_l2 (low)",
    79: "grid_export_total_l2 (high)",
    80: "grid_import_total_l1 (low)",
    81: "grid_import_total_l1 (high)",
    82: "grid_import_total_l2 (low)",
    83: "grid_import_total_l2 (high)",
    # 84-87: UNKNOWN (hypothesis: nbu_energy_total_l1/l2)
    88: "smart_load1_energy_total_l1 (low)",
    89: "smart_load1_energy_total_l1 (high)",
}


def format_energy_16bit(raw: int) -> float:
    """Convert 16-bit raw register to kWh (÷10 scaling)."""
    return raw / 10.0


def format_energy_32bit(low: int, high: int) -> float:
    """Convert 32-bit raw register pair to kWh (÷10 scaling)."""
    return ((high << 16) | low) / 10.0


async def probe() -> None:
    """Read and display unknown GridBOSS registers."""
    transport = DongleTransport(
        host=GRIDBOSS_HOST,
        port=GRIDBOSS_PORT,
        dongle_serial=DONGLE_SERIAL,
        inverter_serial=INVERTER_SERIAL,
        timeout=10.0,
    )

    try:
        await transport.connect()
        print(f"Connected to GridBOSS {INVERTER_SERIAL} via dongle {DONGLE_SERIAL}")
        print()

        # =====================================================================
        # Read daily energy block (regs 42-67) to get context + unknown 50-51
        # =====================================================================
        print("=" * 70)
        print("DAILY ENERGY REGISTERS (42-67)")
        print("=" * 70)

        daily_regs = await transport._read_input_registers(42, 26)
        for i, val in enumerate(daily_regs):
            addr = 42 + i
            energy = format_energy_16bit(val)
            label = KNOWN_DAILY_ENERGY.get(addr, "")
            if addr in (50, 51):
                label = "*** UNKNOWN — hypothesis: nbu_energy_today ***"
            if energy > 0 or addr in (50, 51):
                print(f"  Reg {addr:3d}: raw={val:5d}  → {energy:8.1f} kWh  {label}")

        print()

        # =====================================================================
        # Read lifetime energy block (regs 68-103) to get context + unknown 84-87
        # =====================================================================
        print("=" * 70)
        print("LIFETIME ENERGY REGISTERS (68-103)")
        print("=" * 70)

        lifetime_regs = await transport._read_input_registers(68, 36)
        for i in range(0, len(lifetime_regs), 2):
            addr_low = 68 + i
            addr_high = 68 + i + 1
            if i + 1 < len(lifetime_regs):
                low = lifetime_regs[i]
                high = lifetime_regs[i + 1]
                energy = format_energy_32bit(low, high)
                label = KNOWN_LIFETIME_ENERGY.get(addr_low, "")
                if addr_low in (84, 86):
                    label = "*** UNKNOWN — hypothesis: nbu_energy_total ***"
                if energy > 0 or addr_low in (84, 86):
                    print(
                        f"  Reg {addr_low:3d}-{addr_high:3d}: "
                        f"raw=({low:5d}, {high:5d})  → {energy:10.1f} kWh  {label}"
                    )

        print()

        # =====================================================================
        # Look for generator energy registers in unexplored areas
        # Hypothesis: could be near regs 50-51 or in the 119-127 gap
        # =====================================================================
        print("=" * 70)
        print("SEARCHING FOR GENERATOR ENERGY (regs 119-127, gap before freq)")
        print("=" * 70)

        try:
            gap_regs = await transport._read_input_registers(119, 9)
            for i, val in enumerate(gap_regs):
                addr = 119 + i
                if val != 0:
                    energy_16 = format_energy_16bit(val)
                    print(f"  Reg {addr:3d}: raw={val:5d}  (÷10 → {energy_16:.1f})")
            if all(v == 0 for v in gap_regs):
                print("  All zero — no generator energy here")
        except Exception as e:
            print(f"  Read error: {e}")

        print()

        # =====================================================================
        # Also read regs 18-25 (currently marked as "unused/unknown")
        # =====================================================================
        print("=" * 70)
        print("UNKNOWN REGISTERS 18-25 (between current and power)")
        print("=" * 70)

        try:
            unk_regs = await transport._read_input_registers(18, 8)
            for i, val in enumerate(unk_regs):
                addr = 18 + i
                if val != 0:
                    print(f"  Reg {addr:3d}: raw={val:5d}  (÷10 → {val / 10:.1f})")
            if all(v == 0 for v in unk_regs):
                print("  All zero — no data here")
        except Exception as e:
            print(f"  Read error: {e}")

        print()

        # =====================================================================
        # Summary comparison with XLS export data
        # =====================================================================
        print("=" * 70)
        print("COMPARISON WITH XLS EXPORT (2026-02-28)")
        print("=" * 70)
        print()
        print("XLS export values at 00:03:46:")
        print("  eBU Day    = 0.2 kWh  (ups_today)")
        print("  eNBU Day   = 0.0 kWh  ← WHAT REGISTER?")
        print("  eGenDay    = 0.0 kWh  ← WHAT REGISTER?")
        print("  eBUAll     = 15249.7 kWh  (ups_total)")
        print("  eNBUAll    = 10736.7 kWh  ← WHAT REGISTER?")
        print("  eGenAll    = 0.0 kWh  ← WHAT REGISTER?")
        print()

        # Read the specific unknown registers one more time for clear output
        regs_50_51 = await transport._read_input_registers(50, 2)
        regs_84_87 = await transport._read_input_registers(84, 4)

        print("Probe results for candidate NBU registers:")
        print(
            f"  Reg 50: raw={regs_50_51[0]:5d}  → {format_energy_16bit(regs_50_51[0]):.1f} kWh  (nbu_energy_today_l1?)"
        )
        print(
            f"  Reg 51: raw={regs_50_51[1]:5d}  → {format_energy_16bit(regs_50_51[1]):.1f} kWh  (nbu_energy_today_l2?)"
        )
        nbu_total_l1 = format_energy_32bit(regs_84_87[0], regs_84_87[1])
        nbu_total_l2 = format_energy_32bit(regs_84_87[2], regs_84_87[3])
        print(
            f"  Reg 84-85: raw=({regs_84_87[0]:5d}, {regs_84_87[1]:5d})  → {nbu_total_l1:.1f} kWh  (nbu_energy_total_l1?)"
        )
        print(
            f"  Reg 86-87: raw=({regs_84_87[2]:5d}, {regs_84_87[3]:5d})  → {nbu_total_l2:.1f} kWh  (nbu_energy_total_l2?)"
        )
        nbu_total = nbu_total_l1 + nbu_total_l2
        print(
            f"  Combined L1+L2 total: {nbu_total:.1f} kWh  (XLS eNBUAll = 10736.7 kWh)"
        )
        print()

        if abs(nbu_total - 10736.7) < 200:
            print(
                "  *** MATCH! Regs 84-87 are almost certainly NBU lifetime energy ***"
            )
        elif nbu_total > 0:
            print("  Value is non-zero but doesn't match XLS. Investigate further.")
        else:
            print("  Registers are zero — hypothesis may be wrong.")

    except Exception as e:
        print(f"Error: {e}")
        raise
    finally:
        await transport.disconnect()


if __name__ == "__main__":
    asyncio.run(probe())
