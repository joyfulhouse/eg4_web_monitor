#!/usr/bin/env python3
"""Walk the Modbus FC04 input-register dispatcher in an EG4 ARM comms firmware image.

The dispatcher is a decrement-and-test chain: ``CMP R0,#0`` / ``BEQ.W <handler>`` followed by
repeated ``SUBS R0,R0,#imm`` / ``BEQ.W <handler>``.  Unimplemented registers appear as a larger
decrement, so a walker that only understands ``SUBS #1`` silently mis-numbers every register after
the first gap.  Handling every ``SUBS`` form is what makes the resulting map trustworthy.

Each handler is then decoded far enough to report the RAM address it reads, which is what
distinguishes a genuine DSP-fed measurement from an ARM-local value.

**Known limitation:** the walk covers the contiguous chain only.  On the off-grid ``ceaa-07xx``
image the chain continues past ``0x0801E2D8`` with a register-relative step
(``MOVW R1,#0x11D ; SUBS R0,R0,R1``) into a further block of cases (520-598), which this script does
not follow.  It therefore reports 166 cases up to register 235, while full coverage is 245 cases up
to 598.  Do not read its output as the complete register set.

Read-only.  Requires no vendor tooling.  See
``docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md`` for the analysis this supports.

Usage::

    uv run python scripts/walk_input_dispatch.py IMAGE.bin \
        --base 0x08005000 --start 0x0801DEEC [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

# Registers whose implementation status is known from live hardware (issue #196 measured
# I153=1409 W and I170=3788 W on a 12000XP).  A walk that reports these as unimplemented has
# drifted and must not be trusted.
SANITY_REGISTERS = (153, 170)

_WIDE_PREFIXES = (0xE800, 0xF000, 0xF800)


class Image:
    """A flat firmware image with a known load base."""

    def __init__(self, data: bytes, base: int) -> None:
        self.data = data
        self.base = base

    def halfword(self, addr: int) -> int:
        return int(struct.unpack_from("<H", self.data, addr - self.base)[0])

    def word(self, addr: int) -> int:
        return int(struct.unpack_from("<I", self.data, addr - self.base)[0])

    def contains(self, addr: int, size: int = 2) -> bool:
        off = addr - self.base
        return 0 <= off <= len(self.data) - size


def _is_wide(halfword: int) -> bool:
    """True if this halfword starts a 32-bit Thumb-2 instruction."""
    return (halfword & 0xF800) in _WIDE_PREFIXES


def _decode_beq_w(img: Image, addr: int) -> int | None:
    """Decode ``BEQ.W`` (B<cond>.W encoding T3) at ``addr``, returning its target."""
    hw1 = img.halfword(addr)
    hw2 = img.halfword(addr + 2)
    if (hw1 & 0xF800) != 0xF000 or (hw2 & 0xD000) != 0x8000:
        return None
    if ((hw1 >> 6) & 0xF) != 0:  # cond != EQ
        return None
    sign = (hw1 >> 10) & 1
    imm6 = hw1 & 0x3F
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    imm11 = hw2 & 0x7FF
    offset = (sign << 20) | (j2 << 19) | (j1 << 18) | (imm6 << 12) | (imm11 << 1)
    if sign:
        offset -= 1 << 21
    return addr + 4 + offset


def _decrement(halfword: int) -> int | None:
    """Return the amount subtracted from R0, for either SUBS encoding."""
    # SUBS R0,R0,#imm3 (T1) — the form that encodes dispatcher gaps
    if (
        (halfword & 0xFE00) == 0x1E00
        and ((halfword >> 3) & 7) == 0
        and (halfword & 7) == 0
    ):
        return (halfword >> 6) & 7
    # SUBS R0,#imm8 (T2)
    if (halfword & 0xFF00) == 0x3800:
        return halfword & 0xFF
    return None


def walk_dispatch(img: Image, start: int, limit: int = 0x1000) -> dict[int, int]:
    """Return ``{register_number: handler_address}`` for the chain at ``start``."""
    table: dict[int, int] = {}
    addr = start
    register: int | None = None

    while addr < start + limit and img.contains(addr, 4):
        halfword = img.halfword(addr)

        if register is None:
            if halfword == 0x2800:  # CMP R0,#0 — chain begins, this case is register 0
                register = 0
            addr += 2
            continue

        step = _decrement(halfword)
        if step is not None:
            register += step
            addr += 2
            continue

        target = _decode_beq_w(img, addr)
        if target is not None:
            table.setdefault(register, target)
            addr += 4
            continue

        break  # chain ended

    return table


def decode_handler(img: Image, addr: int, max_insns: int = 8) -> str:
    """Decode a small handler far enough to report the RAM address it loads."""
    steps: list[str] = []
    base: int | None = None

    for _ in range(max_insns):
        if not img.contains(addr, 4):
            break
        halfword = img.halfword(addr)

        if (halfword & 0xF800) == 0x4800:  # LDR Rt,[PC,#imm8*4]
            pool = ((addr + 4) & ~3) + (halfword & 0xFF) * 4
            base = img.word(pool)
            steps.append(f"LDR =0x{base:08X}")
            addr += 2
            continue

        if halfword == 0xF8DF:  # LDR.W Rt,[PC,#imm12]
            pool = ((addr + 4) & ~3) + (img.halfword(addr + 2) & 0xFFF)
            base = img.word(pool)
            steps.append(f"LDR.W =0x{base:08X}")
            addr += 4
            continue

        if (halfword & 0xF800) == 0x7800:  # LDRB Rt,[Rn,#imm5]
            off = (halfword >> 6) & 0x1F
            steps.append(f"LDRB +0x{off:X} -> 0x{(base or 0) + off:08X} (8-bit)")
            # byte-assembled registers load two separate bases; keep going until the
            # next literal is consumed, then stop.
            if sum(1 for s in steps if s.startswith("LDRB")) >= 2:
                return " ; ".join(steps)
            addr += 2
            continue

        if (halfword & 0xF800) == 0x8800:  # LDRH Rt,[Rn,#imm5*2]
            off = ((halfword >> 6) & 0x1F) * 2
            steps.append(f"LDRH +0x{off:X} -> 0x{(base or 0) + off:08X} (16-bit)")
            return " ; ".join(steps)

        if (halfword & 0xF800) == 0x6800:  # LDR Rt,[Rn,#imm5*4]
            off = ((halfword >> 6) & 0x1F) * 4
            steps.append(f"LDR +0x{off:X} -> 0x{(base or 0) + off:08X} (32-bit)")
            return " ; ".join(steps)

        if halfword in (0xF8B0, 0xF8D0):  # LDRH.W / LDR.W Rt,[Rn,#imm12]
            off = img.halfword(addr + 2) & 0xFFF
            width = "16-bit" if halfword == 0xF8B0 else "32-bit"
            steps.append(
                f"{'LDRH.W' if halfword == 0xF8B0 else 'LDR.W'} +0x{off:X}"
                f" -> 0x{(base or 0) + off:08X} ({width})"
            )
            return " ; ".join(steps)

        addr += 4 if _is_wide(halfword) else 2

    return " ; ".join(steps) if steps else "(not decoded)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image", type=Path, help="de-framed ARM comms firmware image")
    parser.add_argument("--base", default="0x08005000", help="load base address")
    parser.add_argument(
        "--start", default="0x0801DEEC", help="dispatcher entry address"
    )
    parser.add_argument(
        "--json", type=Path, help="write the register->handler map here"
    )
    parser.add_argument(
        "--registers", help="comma-separated registers to decode (default: all)"
    )
    args = parser.parse_args()

    img = Image(args.image.read_bytes(), int(args.base, 16))
    table = walk_dispatch(img, int(args.start, 16))

    if not table:
        print("No dispatch chain found — check --start and --base.")
        return 1

    print(f"{len(table)} implemented registers, highest = {max(table)}")

    missing = [r for r in SANITY_REGISTERS if r not in table]
    if missing:
        print(
            f"  !! SANITY CHECK FAILED: register(s) {missing} reported unimplemented, but they "
            f"are measured on real hardware (issue #196). The walk has drifted — do not trust "
            f"this map."
        )
    else:
        print(f"  sanity check passed: registers {list(SANITY_REGISTERS)} implemented")

    if args.registers:
        wanted = [int(r, 0) for r in args.registers.split(",")]
    else:
        wanted = sorted(table)

    print()
    for reg in wanted:
        if reg in table:
            print(
                f"  reg {reg:>3} @{table[reg]:#010x}: {decode_handler(img, table[reg])}"
            )
        else:
            print(f"  reg {reg:>3}: NOT IMPLEMENTED")

    if args.json:
        args.json.write_text(
            json.dumps({str(k): v for k, v in sorted(table.items())}, indent=1)
        )
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
