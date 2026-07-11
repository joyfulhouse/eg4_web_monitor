#!/usr/bin/env python3
"""Modbus collision tester.

Performs rapid Modbus reads against inverter/dongle endpoints
to simulate bus contention while the coordinator is polling.
Logs any corrupt or error responses.
"""

import asyncio
import struct
import sys
import time
from datetime import datetime


# Endpoints
INVERTER_1 = ("10.100.14.68", 502)  # 18kPV
INVERTER_2 = ("10.100.10.184", 502)  # FlexBOSS21
DONGLE = ("10.100.12.175", 8000)  # WiFi dongle (GridBOSS)

# Input registers to read (most commonly used)
INPUT_REGS = [
    (0, 40),  # runtime group 1
    (40, 20),  # runtime group 2
    (60, 20),  # energy group
    (80, 20),  # battery group
]

HOLDING_REGS = [
    (20, 1),  # smart port status (GridBOSS)
    (0, 10),  # basic params
]

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
PARALLEL_READS = 3  # concurrent reads per round


def build_modbus_request(
    transaction_id: int,
    unit_id: int,
    function_code: int,
    start_reg: int,
    count: int,
) -> bytes:
    """Build a Modbus TCP request frame."""
    payload = struct.pack(">BHH", function_code, start_reg, count)
    header = struct.pack(">HHHB", transaction_id, 0, len(payload) + 1, unit_id)
    return header + payload


async def read_registers(
    host: str,
    port: int,
    start: int,
    count: int,
    func_code: int = 4,
    label: str = "",
) -> tuple[str, bool, str]:
    """Read Modbus registers and return (label, success, detail)."""
    tid = int(time.monotonic() * 1000) % 65535
    req = build_modbus_request(tid, 1, func_code, start, count)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5.0
        )
        writer.write(req)
        await writer.drain()

        # Read response header (7 bytes MBAP + 1 unit + 1 func + 1 byte count)
        header = await asyncio.wait_for(reader.read(256), timeout=5.0)
        writer.close()
        await writer.wait_closed()

        if len(header) < 9:
            return (label, False, f"short response: {len(header)} bytes")

        resp_tid = struct.unpack(">H", header[0:2])[0]
        resp_func = header[7]

        if resp_func & 0x80:
            error_code = header[8] if len(header) > 8 else 0
            return (
                label,
                False,
                f"Modbus error: func=0x{resp_func:02x} err={error_code}",
            )

        if resp_tid != tid:
            return (label, False, f"TID mismatch: sent={tid} got={resp_tid}")

        byte_count = header[8]
        expected = count * 2
        if byte_count != expected:
            return (
                label,
                False,
                f"byte count mismatch: expected={expected} got={byte_count}",
            )

        # Parse register values
        if len(header) < 9 + byte_count:
            return (
                label,
                False,
                f"truncated data: need {9 + byte_count} got {len(header)}",
            )

        values = struct.unpack(f">{count}H", header[9 : 9 + byte_count])

        # Sanity checks for common fields
        detail_parts = []
        if start == 0 and func_code == 4 and count >= 20:
            # Input reg 0 = status, reg 16 = grid freq (should be 0 or 4500-6500)
            freq_raw = values[16] if count > 16 else 0
            if freq_raw > 0 and (freq_raw < 3000 or freq_raw > 9000):
                detail_parts.append(f"SUSPECT freq={freq_raw / 100:.1f}Hz")
            # reg 15 = grid voltage (should be 0-2800 = 0-280V)
            volt_raw = values[15] if count > 15 else 0
            if volt_raw > 3000:
                detail_parts.append(f"SUSPECT voltage={volt_raw / 10:.1f}V")

        detail = f"OK {count} regs" + (
            f" [{', '.join(detail_parts)}]" if detail_parts else ""
        )
        return (label, True, detail)

    except TimeoutError:
        return (label, False, "timeout")
    except ConnectionRefusedError:
        return (label, False, "connection refused")
    except Exception as e:
        return (label, False, f"error: {e}")


async def run_collision_round(round_num: int) -> list[tuple[str, bool, str]]:
    """Run parallel reads against all endpoints."""
    tasks = []
    for start, count in INPUT_REGS:
        tasks.append(
            read_registers(
                *INVERTER_1,
                start,
                count,
                4,
                f"INV1-IR{start}-{start + count}",
            )
        )
        tasks.append(
            read_registers(
                *INVERTER_2,
                start,
                count,
                4,
                f"INV2-IR{start}-{start + count}",
            )
        )

    # Dongle reads (input registers)
    for start, count in INPUT_REGS[:2]:
        tasks.append(
            read_registers(
                *DONGLE,
                start,
                count,
                4,
                f"DONGLE-IR{start}-{start + count}",
            )
        )

    # Holding register reads
    for start, count in HOLDING_REGS:
        tasks.append(
            read_registers(
                *DONGLE,
                start,
                count,
                3,
                f"DONGLE-HR{start}-{start + count}",
            )
        )

    return await asyncio.gather(*tasks)


async def main() -> None:
    print("=== Modbus Collision Test ===")
    print(f"Targets: INV1={INVERTER_1}, INV2={INVERTER_2}, DONGLE={DONGLE}")
    print(f"Rounds: {ROUNDS}, parallel reads per round: ~{len(INPUT_REGS) * 2 + 4}")
    print("=" * 60)

    total_reads = 0
    total_errors = 0
    total_suspect = 0

    for r in range(1, ROUNDS + 1):
        now = datetime.now().strftime("%H:%M:%S")
        results = await run_collision_round(r)
        errors = [(label, detail) for label, ok, detail in results if not ok]
        suspects = [
            (label, detail)
            for label, ok, detail in results
            if ok and "SUSPECT" in detail
        ]
        total_reads += len(results)
        total_errors += len(errors)
        total_suspect += len(suspects)

        if errors or suspects:
            print(f"\n[{now}] Round {r}/{ROUNDS}:")
            for label, detail in errors:
                print(f"  ERROR: {label}: {detail}")
            for label, detail in suspects:
                print(f"  SUSPECT: {label}: {detail}")
        else:
            if r % 3 == 0 or r == 1:
                print(f"[{now}] Round {r}/{ROUNDS}: {len(results)} reads OK")

        # Small delay between rounds to let coordinator also attempt reads
        await asyncio.sleep(2)

    print("\n" + "=" * 60)
    print("=== COLLISION TEST COMPLETE ===")
    print(f"Total reads: {total_reads}")
    print(f"Errors: {total_errors}")
    print(f"Suspect values: {total_suspect}")
    if total_errors == 0 and total_suspect == 0:
        print("RESULT: CLEAN — All reads returned valid data")
    else:
        print(f"RESULT: {total_errors} errors, {total_suspect} suspect values")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
