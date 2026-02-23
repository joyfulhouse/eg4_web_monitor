# CloudEmitter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a virtual WiFi dongle (CloudEmitter) in pylxpweb that forwards register data to the EG4 cloud server over TCP, maintaining cloud monitoring when the physical dongle is replaced.

**Architecture:** CloudEmitter is a standalone asyncio background task that reads cached raw register snapshots (stashed during normal HA polling) and sends them to `us2.solarcloudsystem.com:4346` using the same 0xA1/0x1A binary protocol as the physical dongle. Cloud commands (0xC3/0xC4) trigger fresh register reads/writes.

**Tech Stack:** Python 3.12+, asyncio (TCP sockets), pylxpweb transports, CRC-16/Modbus

**Design Doc:** `docs/plans/2026-02-22-cloud-emulator-design.md`

---

## Task 1: Cloud Protocol Module (`protocol.py`)

CRC-16, frame constants, and frame parsing utilities shared by all cloud emitter code.

**Files:**
- Create: `pylxpweb/src/pylxpweb/cloud/__init__.py`
- Create: `pylxpweb/src/pylxpweb/cloud/protocol.py`
- Create: `pylxpweb/tests/unit/test_cloud_protocol.py`

**Context:**
- CRC-16/Modbus already exists in `pylxpweb/src/pylxpweb/transports/dongle.py:69-86` (`compute_crc16`)
- Frame format: `[A1 1A] [ver_lo ver_hi] [frame_len_lo frame_len_hi] [addr] [func] [serial x10] [payload...] [CRC16]`
- `frame_length = total_size - 6` (excludes magic + version + length fields)
- Function codes: 0xC1=heartbeat, 0xC2=data, 0xC3=get_param, 0xC4=set_param

**Step 1: Write failing tests for frame constants and CRC**

```python
# pylxpweb/tests/unit/test_cloud_protocol.py
"""Tests for cloud protocol frame building and parsing."""
from __future__ import annotations

import pytest

from pylxpweb.cloud.protocol import (
    CLOUD_PORT,
    FRAME_MAGIC,
    FUNC_DATA,
    FUNC_GET_PARAM,
    FUNC_HEARTBEAT,
    FUNC_SET_PARAM,
    build_frame,
    compute_crc16,
    parse_frame,
)


class TestConstants:
    def test_frame_magic(self) -> None:
        assert FRAME_MAGIC == bytes([0xA1, 0x1A])

    def test_function_codes(self) -> None:
        assert FUNC_HEARTBEAT == 0xC1
        assert FUNC_DATA == 0xC2
        assert FUNC_GET_PARAM == 0xC3
        assert FUNC_SET_PARAM == 0xC4

    def test_cloud_port(self) -> None:
        assert CLOUD_PORT == 4346


class TestCRC16:
    def test_empty_data(self) -> None:
        assert compute_crc16(b"") == 0xFFFF

    def test_known_value(self) -> None:
        # Standard Modbus CRC-16 test vector: "123456789" -> 0x4B37
        assert compute_crc16(b"123456789") == 0x4B37

    def test_single_byte(self) -> None:
        result = compute_crc16(b"\x01")
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF


class TestBuildFrame:
    def test_heartbeat_frame_length(self) -> None:
        """Heartbeat frame is exactly 19 bytes per firmware spec."""
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        assert len(frame) == 19

    def test_heartbeat_frame_magic(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        assert frame[0:2] == FRAME_MAGIC

    def test_heartbeat_frame_func(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        assert frame[7] == FUNC_HEARTBEAT

    def test_heartbeat_frame_serial(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        assert frame[8:18] == b"1234567890"

    def test_frame_length_field(self) -> None:
        """frame_length = total_size - 6."""
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        frame_len = int.from_bytes(frame[4:6], "little")
        assert frame_len == len(frame) - 6

    def test_frame_version(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        version = int.from_bytes(frame[2:4], "little")
        assert version == 1

    def test_frame_addr(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        assert frame[6] == 0x01

    def test_data_frame_with_payload(self) -> None:
        payload = bytes(range(10))
        frame = build_frame(
            func=FUNC_DATA,
            serial="ABCDEFGHIJ",
            payload=payload,
        )
        # 2(magic) + 2(ver) + 2(len) + 1(addr) + 1(func) + 10(serial) + 10(payload) + 2(crc) = 30
        assert len(frame) == 30
        assert frame[7] == FUNC_DATA

    def test_crc_is_appended(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        # Last 2 bytes are CRC-16 of the inner frame (bytes 6 onward minus CRC)
        inner = frame[6:-2]
        expected_crc = compute_crc16(inner)
        actual_crc = int.from_bytes(frame[-2:], "little")
        assert actual_crc == expected_crc


class TestParseFrame:
    def test_roundtrip_heartbeat(self) -> None:
        frame = build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        )
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_HEARTBEAT
        assert parsed.serial == "1234567890"
        assert parsed.payload == b"\x05"

    def test_roundtrip_data(self) -> None:
        payload = b"\x01\x04\x06\x00\x01\x00\x02\x00\x03"
        frame = build_frame(
            func=FUNC_DATA,
            serial="ABCDEFGHIJ",
            payload=payload,
        )
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_DATA
        assert parsed.serial == "ABCDEFGHIJ"
        assert parsed.payload == payload

    def test_invalid_magic_returns_none(self) -> None:
        assert parse_frame(b"\x00\x00\x00\x00") is None

    def test_truncated_frame_returns_none(self) -> None:
        assert parse_frame(b"\xA1\x1A\x01\x00") is None

    def test_bad_crc_returns_none(self) -> None:
        frame = bytearray(build_frame(
            func=FUNC_HEARTBEAT,
            serial="1234567890",
            payload=b"\x05",
        ))
        frame[-1] ^= 0xFF  # Corrupt CRC
        assert parse_frame(bytes(frame)) is None
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_protocol.py -v
```
Expected: FAIL (ModuleNotFoundError — `pylxpweb.cloud.protocol` does not exist)

**Step 3: Implement protocol module**

```python
# pylxpweb/src/pylxpweb/cloud/__init__.py
"""Cloud emulation for EG4 WiFi dongle replacement."""

from __future__ import annotations

# pylxpweb/src/pylxpweb/cloud/protocol.py
"""Cloud TCP protocol: frame building, parsing, CRC-16, and constants.

The EG4 cloud ingestion server (us2.solarcloudsystem.com:4346) uses a binary
protocol with 0xA1 0x1A magic prefix. All three dongle transports (Cloud TCP,
Local TCP, BLE) share this same frame format.

Frame layout (18-byte preamble + variable payload + 2-byte CRC):
    [A1 1A] [ver_lo ver_hi] [frame_len_lo frame_len_hi] [addr] [func]
    [serial x10] [payload...] [CRC16_lo CRC16_hi]

Where frame_length = total_size - 6 (excludes magic + version + length fields).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# Cloud server defaults
CLOUD_HOST = "us2.solarcloudsystem.com"
CLOUD_PORT = 4346

# Frame constants
FRAME_MAGIC = bytes([0xA1, 0x1A])
FRAME_VERSION = 1
FRAME_ADDR = 0x01
PREAMBLE_SIZE = 18  # magic(2) + ver(2) + len(2) + addr(1) + func(1) + serial(10)
CRC_SIZE = 2

# Function codes
FUNC_HEARTBEAT = 0xC1
FUNC_DATA = 0xC2
FUNC_GET_PARAM = 0xC3
FUNC_SET_PARAM = 0xC4

# Heartbeat status byte (from firmware HeartbeatBuilder)
HEARTBEAT_STATUS = 0x05


def compute_crc16(data: bytes) -> int:
    """Compute CRC-16/Modbus checksum (init=0xFFFF, poly=0xA001).

    This is identical to the implementation in transports/dongle.py and
    the firmware's lookup-table CRC at 0x4200de42.

    Args:
        data: Bytes to compute CRC for.

    Returns:
        16-bit CRC value.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    """A parsed cloud protocol frame."""

    func: int
    serial: str
    payload: bytes


def build_frame(
    *,
    func: int,
    serial: str,
    payload: bytes,
) -> bytes:
    """Build a cloud protocol frame with 0xA1 0x1A prefix.

    Args:
        func: Function code (FUNC_HEARTBEAT, FUNC_DATA, etc.)
        serial: 10-character dongle serial number.
        payload: Variable-length payload bytes.

    Returns:
        Complete frame bytes ready to send over TCP.
    """
    serial_bytes = serial.encode("ascii")[:10].ljust(10, b"\x00")

    # Inner frame: addr + func + serial + payload
    inner = bytes([FRAME_ADDR, func]) + serial_bytes + payload

    # CRC over inner frame
    crc = compute_crc16(inner)
    inner_with_crc = inner + struct.pack("<H", crc)

    # Full frame: magic + version + frame_length + inner_with_crc
    # frame_length = len(inner_with_crc) = total_size - 6
    frame_length = len(inner_with_crc)
    header = FRAME_MAGIC + struct.pack("<HH", FRAME_VERSION, frame_length)

    return header + inner_with_crc


def parse_frame(data: bytes) -> ParsedFrame | None:
    """Parse a cloud protocol frame.

    Args:
        data: Raw bytes received from TCP.

    Returns:
        ParsedFrame if valid, None if invalid magic/CRC/length.
    """
    if len(data) < PREAMBLE_SIZE + CRC_SIZE:
        return None

    if data[0:2] != FRAME_MAGIC:
        return None

    frame_length = int.from_bytes(data[4:6], "little")
    total_expected = 6 + frame_length  # magic(2) + ver(2) + len(2) + frame_length

    if len(data) < total_expected:
        return None

    inner_with_crc = data[6:total_expected]
    inner = inner_with_crc[:-2]
    crc_received = int.from_bytes(inner_with_crc[-2:], "little")
    crc_computed = compute_crc16(inner)

    if crc_received != crc_computed:
        return None

    func = inner[1]
    serial = inner[2:12].decode("ascii", errors="replace").rstrip("\x00")
    payload = inner[12:]

    return ParsedFrame(func=func, serial=serial, payload=payload)
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_protocol.py -v
```
Expected: ALL PASS

**Step 5: Lint and type-check**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run ruff check src/pylxpweb/cloud/ --fix && uv run ruff format src/pylxpweb/cloud/
uv run mypy src/pylxpweb/cloud/
```

**Step 6: Commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git add src/pylxpweb/cloud/ tests/unit/test_cloud_protocol.py
git commit -m "feat(cloud): add protocol module with frame building, parsing, CRC-16"
```

---

## Task 2: Raw Register Snapshot Stashing

Add `_register_snapshot` dict to transports that stashes raw register values during normal reads.

**Files:**
- Modify: `pylxpweb/src/pylxpweb/transports/protocol.py:202-209` (BaseTransport.__init__)
- Modify: `pylxpweb/src/pylxpweb/transports/_modbus_base.py:178-181` (return point in _read_registers)
- Modify: `pylxpweb/src/pylxpweb/transports/dongle.py:742-802` (_read_input/holding_registers)
- Create: `pylxpweb/tests/unit/test_register_snapshot.py`

**Context:**
- `BaseTransport.__init__` at `protocol.py:202` sets `self._serial` and `self._connected`
- `BaseModbusTransport._read_registers` returns `list(result.registers)` at `_modbus_base.py:181`
- `DongleTransport._read_input_registers` returns via `_send_receive` at `dongle.py:767-771`
- `DongleTransport._read_holding_registers` returns via `_send_receive` at `dongle.py:798-802`
- Snapshot dict structure: `{"input": {addr: value, ...}, "holding": {addr: value, ...}}`

**Step 1: Write failing tests**

```python
# pylxpweb/tests/unit/test_register_snapshot.py
"""Tests for raw register snapshot stashing on transports."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylxpweb.transports.protocol import BaseTransport


class TestRegisterSnapshot:
    def test_base_transport_has_snapshot(self) -> None:
        """BaseTransport initializes empty register snapshot."""
        transport = BaseTransport("CE12345678")
        assert hasattr(transport, "_register_snapshot")
        assert transport._register_snapshot == {"input": {}, "holding": {}}

    def test_snapshot_is_mutable_dict(self) -> None:
        transport = BaseTransport("CE12345678")
        transport._register_snapshot["input"][0] = 42
        assert transport._register_snapshot["input"][0] == 42

    def test_snapshot_cleared_on_init(self) -> None:
        transport = BaseTransport("CE12345678")
        transport._register_snapshot["input"][100] = 999
        # New transport should have clean snapshot
        transport2 = BaseTransport("CE12345678")
        assert transport2._register_snapshot["input"] == {}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_register_snapshot.py -v
```
Expected: FAIL (BaseTransport has no `_register_snapshot`)

**Step 3: Add `_register_snapshot` to BaseTransport**

In `pylxpweb/src/pylxpweb/transports/protocol.py`, modify `BaseTransport.__init__`:

```python
# After line 209 (self._connected = False), add:
        self._register_snapshot: dict[str, dict[int, int]] = {
            "input": {},
            "holding": {},
        }
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_register_snapshot.py -v
```
Expected: ALL PASS

**Step 5: Add stashing to BaseModbusTransport._read_registers**

In `pylxpweb/src/pylxpweb/transports/_modbus_base.py`, at line 181 where it returns `list(result.registers)`, change to:

```python
                    self._consecutive_errors = 0
                    values = list(result.registers)
                    # Stash raw register values for CloudEmitter
                    reg_type = "input" if input_registers else "holding"
                    for i, val in enumerate(values):
                        self._register_snapshot[reg_type][address + i] = val
                    return values
```

**Step 6: Add stashing to DongleTransport read methods**

In `pylxpweb/src/pylxpweb/transports/dongle.py`, modify `_read_input_registers` (around line 767):

```python
    async def _read_input_registers(self, address: int, count: int) -> list[int]:
        # ... existing docstring and packet building ...
        packet = self._build_packet(
            tcp_func=TCP_FUNC_TRANSLATED,
            modbus_func=MODBUS_READ_INPUT,
            start_register=address,
            register_count=min(count, 40),
        )
        values = await self._send_receive(
            packet,
            expected_func=MODBUS_READ_INPUT,
            expected_register=address,
        )
        # Stash raw register values for CloudEmitter
        for i, val in enumerate(values):
            self._register_snapshot["input"][address + i] = val
        return values
```

Same pattern for `_read_holding_registers` (around line 798):

```python
        values = await self._send_receive(
            packet,
            expected_func=MODBUS_READ_HOLDING,
            expected_register=address,
        )
        # Stash raw register values for CloudEmitter
        for i, val in enumerate(values):
            self._register_snapshot["holding"][address + i] = val
        return values
```

**Step 7: Run full test suite to verify no regressions**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/ -x --tb=short
```
Expected: ALL PASS

**Step 8: Lint and type-check**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run ruff check src/pylxpweb/transports/protocol.py src/pylxpweb/transports/_modbus_base.py src/pylxpweb/transports/dongle.py --fix
uv run ruff format src/pylxpweb/transports/protocol.py src/pylxpweb/transports/_modbus_base.py src/pylxpweb/transports/dongle.py
uv run mypy src/pylxpweb/transports/protocol.py src/pylxpweb/transports/_modbus_base.py src/pylxpweb/transports/dongle.py
```

**Step 9: Commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git add src/pylxpweb/transports/protocol.py src/pylxpweb/transports/_modbus_base.py src/pylxpweb/transports/dongle.py tests/unit/test_register_snapshot.py
git commit -m "feat(transports): stash raw register values in _register_snapshot for cloud emitter"
```

---

## Task 3: Frame Builder Module (`frames.py`)

Builds Modbus RTU response bytes and wraps them in 0xC2 data frames. Also builds heartbeat frames.

**Files:**
- Create: `pylxpweb/src/pylxpweb/cloud/frames.py`
- Create: `pylxpweb/tests/unit/test_cloud_frames.py`

**Context:**
- 0xC2 payload = Modbus RTU response: `[slave_addr=1] [func_code] [byte_count=N*2] [reg_hi reg_lo ...] [CRC16]`
- Input registers use func_code 0x04, holding use 0x03
- Real dongle sends: holding 0-79 (1 frame), input 0-380 (3 frames, chunks of 127)
- Register snapshot is `dict[int, int]` mapping address → uint16 value
- Uses `build_frame` from `protocol.py`

**Step 1: Write failing tests**

```python
# pylxpweb/tests/unit/test_cloud_frames.py
"""Tests for cloud data frame building."""
from __future__ import annotations

import struct

import pytest

from pylxpweb.cloud.frames import (
    build_data_frames,
    build_heartbeat_frame,
    build_modbus_rtu_response,
)
from pylxpweb.cloud.protocol import FUNC_DATA, FUNC_HEARTBEAT, parse_frame

SERIAL = "1234567890"


class TestModbusRTUResponse:
    def test_empty_registers(self) -> None:
        result = build_modbus_rtu_response(func_code=0x04, start=0, registers={})
        assert result is None

    def test_input_register_response(self) -> None:
        """Build Modbus RTU response for input registers."""
        regs = {0: 100, 1: 200, 2: 300}
        result = build_modbus_rtu_response(func_code=0x04, start=0, registers=regs)
        assert result is not None
        assert result[0] == 0x01  # slave addr
        assert result[1] == 0x04  # func code (input)
        assert result[2] == 6  # byte count (3 regs * 2 bytes)
        # Register values in big-endian (Modbus convention)
        assert struct.unpack(">HHH", result[3:9]) == (100, 200, 300)

    def test_holding_register_response(self) -> None:
        regs = {0: 0xFFFF, 1: 0x0000}
        result = build_modbus_rtu_response(func_code=0x03, start=0, registers=regs)
        assert result is not None
        assert result[1] == 0x03

    def test_crc_appended(self) -> None:
        regs = {0: 42}
        result = build_modbus_rtu_response(func_code=0x04, start=0, registers=regs)
        assert result is not None
        assert len(result) == 1 + 1 + 1 + 2 + 2  # addr+func+count+data+crc

    def test_gap_in_registers_fills_zero(self) -> None:
        """Missing register addresses in snapshot should be zero-filled."""
        regs = {0: 100, 2: 300}  # register 1 missing
        result = build_modbus_rtu_response(
            func_code=0x04, start=0, registers=regs, count=3
        )
        assert result is not None
        values = struct.unpack(">HHH", result[3:9])
        assert values == (100, 0, 300)


class TestHeartbeatFrame:
    def test_heartbeat_is_19_bytes(self) -> None:
        frame = build_heartbeat_frame(SERIAL)
        assert len(frame) == 19

    def test_heartbeat_func_code(self) -> None:
        frame = build_heartbeat_frame(SERIAL)
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_HEARTBEAT

    def test_heartbeat_status_byte(self) -> None:
        frame = build_heartbeat_frame(SERIAL)
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.payload == b"\x05"


class TestBuildDataFrames:
    def test_holding_registers_one_frame(self) -> None:
        """Holding registers 0-79 should produce 1 frame."""
        snapshot = {"input": {}, "holding": {i: i for i in range(80)}}
        frames = build_data_frames(SERIAL, snapshot)
        holding_frames = [
            f for f in frames
            if parse_frame(f) and parse_frame(f).payload[1] == 0x03  # type: ignore[union-attr]
        ]
        assert len(holding_frames) == 1

    def test_input_registers_three_frames(self) -> None:
        """Input registers 0-380 should produce 3 frames (chunks of 127)."""
        snapshot = {"input": {i: i % 0xFFFF for i in range(381)}, "holding": {}}
        frames = build_data_frames(SERIAL, snapshot)
        input_frames = [
            f for f in frames
            if parse_frame(f) and parse_frame(f).payload[1] == 0x04  # type: ignore[union-attr]
        ]
        assert len(input_frames) == 3

    def test_empty_snapshot_returns_empty(self) -> None:
        snapshot = {"input": {}, "holding": {}}
        frames = build_data_frames(SERIAL, snapshot)
        assert frames == []

    def test_all_frames_are_valid(self) -> None:
        snapshot = {
            "input": {i: 1000 + i for i in range(200)},
            "holding": {i: 2000 + i for i in range(80)},
        }
        frames = build_data_frames(SERIAL, snapshot)
        for frame in frames:
            parsed = parse_frame(frame)
            assert parsed is not None, "Frame failed CRC/parse validation"
            assert parsed.func == FUNC_DATA
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_frames.py -v
```
Expected: FAIL (ModuleNotFoundError)

**Step 3: Implement frames module**

```python
# pylxpweb/src/pylxpweb/cloud/frames.py
"""Build cloud data frames wrapping raw Modbus RTU register data.

The real dongle reads registers and sends each Modbus RTU response
as a 0xC2 payload wrapped in the 0xA1/0x1A cloud frame.

Register groups per poll cycle:
- Holding registers 0-79 (1 frame, func=0x03)
- Input registers 0-126 (frame 1, func=0x04)
- Input registers 127-253 (frame 2, func=0x04)
- Input registers 254-380 (frame 3, func=0x04)
"""
from __future__ import annotations

import struct

from .protocol import (
    FUNC_DATA,
    FUNC_HEARTBEAT,
    HEARTBEAT_STATUS,
    build_frame,
    compute_crc16,
)

# Modbus function codes (for RTU response)
_MODBUS_READ_HOLDING = 0x03
_MODBUS_READ_INPUT = 0x04

# Register ranges matching firmware register group table
_HOLDING_START = 0
_HOLDING_END = 79
_INPUT_START = 0
_INPUT_END = 380
_INPUT_CHUNK_SIZE = 127


def build_modbus_rtu_response(
    *,
    func_code: int,
    start: int,
    registers: dict[int, int],
    count: int | None = None,
    slave_addr: int = 0x01,
) -> bytes | None:
    """Build a Modbus RTU response from a register snapshot.

    Args:
        func_code: Modbus function code (0x03 for holding, 0x04 for input).
        start: Starting register address.
        registers: Dict mapping register address to uint16 value.
        count: Number of registers. If None, inferred from max address in registers.
        slave_addr: Modbus slave address (default 1).

    Returns:
        Modbus RTU response bytes including CRC, or None if no registers in range.
    """
    if count is None:
        # Infer count from available registers
        relevant = {a: v for a, v in registers.items() if a >= start}
        if not relevant:
            return None
        count = max(relevant) - start + 1

    # Build register data (big-endian per Modbus convention)
    reg_data = bytearray()
    for addr in range(start, start + count):
        value = registers.get(addr, 0)
        reg_data.extend(struct.pack(">H", value & 0xFFFF))

    byte_count = len(reg_data)
    # Modbus RTU response: slave_addr + func + byte_count + data + CRC
    response = bytes([slave_addr, func_code, byte_count]) + bytes(reg_data)
    crc = compute_crc16(response)
    return response + struct.pack("<H", crc)


def build_heartbeat_frame(serial: str) -> bytes:
    """Build a 19-byte heartbeat frame.

    Args:
        serial: 10-character dongle serial number.

    Returns:
        Complete heartbeat frame ready to send.
    """
    return build_frame(
        func=FUNC_HEARTBEAT,
        serial=serial,
        payload=bytes([HEARTBEAT_STATUS]),
    )


def build_data_frames(
    serial: str,
    snapshot: dict[str, dict[int, int]],
) -> list[bytes]:
    """Build all data frames for one poll cycle.

    Mimics the real dongle's register group reads:
    - Holding registers 0-79 (1 frame)
    - Input registers 0-380 (3 frames in chunks of 127)

    Args:
        serial: 10-character dongle serial number.
        snapshot: Register snapshot dict with "input" and "holding" keys.

    Returns:
        List of complete 0xC2 frames ready to send.
    """
    frames: list[bytes] = []
    holding = snapshot.get("holding", {})
    input_regs = snapshot.get("input", {})

    # Holding registers 0-79
    if holding:
        rtu = build_modbus_rtu_response(
            func_code=_MODBUS_READ_HOLDING,
            start=_HOLDING_START,
            registers=holding,
            count=_HOLDING_END - _HOLDING_START + 1,
        )
        if rtu:
            frames.append(build_frame(func=FUNC_DATA, serial=serial, payload=rtu))

    # Input registers 0-380 in chunks of 127
    if input_regs:
        chunk_start = _INPUT_START
        while chunk_start <= _INPUT_END:
            chunk_end = min(chunk_start + _INPUT_CHUNK_SIZE - 1, _INPUT_END)
            chunk_count = chunk_end - chunk_start + 1
            rtu = build_modbus_rtu_response(
                func_code=_MODBUS_READ_INPUT,
                start=chunk_start,
                registers=input_regs,
                count=chunk_count,
            )
            if rtu:
                frames.append(build_frame(func=FUNC_DATA, serial=serial, payload=rtu))
            chunk_start += _INPUT_CHUNK_SIZE

    return frames
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_frames.py -v
```
Expected: ALL PASS

**Step 5: Lint, type-check, commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run ruff check src/pylxpweb/cloud/ --fix && uv run ruff format src/pylxpweb/cloud/
uv run mypy src/pylxpweb/cloud/
git add src/pylxpweb/cloud/frames.py tests/unit/test_cloud_frames.py
git commit -m "feat(cloud): add frame builder for Modbus RTU → 0xC2 cloud frames"
```

---

## Task 4: CloudEmitter Core Class

The main `CloudEmitter` class with TCP connection, heartbeat, data emission, and command handling.

**Files:**
- Create: `pylxpweb/src/pylxpweb/cloud/emitter.py`
- Create: `pylxpweb/tests/unit/test_cloud_emitter.py`

**Context:**
- Uses `asyncio.open_connection()` for TCP
- Heartbeat every 18s of silence, timeout at 19s → reconnect
- Data push uses `build_data_frames()` with transport `_register_snapshot`
- Commands (0xC3/0xC4) use `transport.read_parameters()` / `transport.write_parameters()`
- Dongle-internal SET_PARAM codes (0,1,3,4,6,9,0x0C,0x0D,0x11,0x12,0x14) are ACK'd without forwarding
- Must be startable/stoppable, report connection status

**Step 1: Write failing tests**

```python
# pylxpweb/tests/unit/test_cloud_emitter.py
"""Tests for CloudEmitter TCP connection and data forwarding."""
from __future__ import annotations

import asyncio
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylxpweb.cloud.emitter import CloudEmitter
from pylxpweb.cloud.protocol import (
    FUNC_DATA,
    FUNC_GET_PARAM,
    FUNC_HEARTBEAT,
    FUNC_SET_PARAM,
    build_frame,
    parse_frame,
)

DONGLE_SERIAL = "BA12345678"
INVERTER_SERIAL = "CE12345678"


@pytest.fixture
def mock_transport() -> MagicMock:
    transport = MagicMock()
    transport.serial = INVERTER_SERIAL
    transport.is_connected = True
    transport._register_snapshot = {
        "input": {i: 1000 + i for i in range(200)},
        "holding": {i: 2000 + i for i in range(80)},
    }
    transport.read_parameters = AsyncMock(return_value={0: 42, 1: 43})
    transport.write_parameters = AsyncMock(return_value=True)
    return transport


@pytest.fixture
def emitter(mock_transport: MagicMock) -> CloudEmitter:
    return CloudEmitter(
        dongle_serial=DONGLE_SERIAL,
        transport=mock_transport,
        host="127.0.0.1",
        port=14346,
    )


class TestCloudEmitterInit:
    def test_default_host(self, mock_transport: MagicMock) -> None:
        emitter = CloudEmitter(
            dongle_serial=DONGLE_SERIAL,
            transport=mock_transport,
        )
        assert emitter._host == "us2.solarcloudsystem.com"
        assert emitter._port == 4346

    def test_custom_host(self, emitter: CloudEmitter) -> None:
        assert emitter._host == "127.0.0.1"
        assert emitter._port == 14346

    def test_not_connected_initially(self, emitter: CloudEmitter) -> None:
        assert not emitter.is_connected

    def test_data_period_default(self, emitter: CloudEmitter) -> None:
        assert emitter._data_period == 100.0


class TestHeartbeatBuilding:
    def test_build_heartbeat(self, emitter: CloudEmitter) -> None:
        frame = emitter._build_heartbeat()
        assert len(frame) == 19
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_HEARTBEAT
        assert parsed.serial == DONGLE_SERIAL


class TestDataEmission:
    def test_build_data_frames(self, emitter: CloudEmitter) -> None:
        """Should build frames from transport snapshot."""
        frames = emitter._build_data()
        assert len(frames) > 0
        for frame in frames:
            parsed = parse_frame(frame)
            assert parsed is not None
            assert parsed.func == FUNC_DATA

    def test_empty_snapshot_no_frames(
        self, emitter: CloudEmitter, mock_transport: MagicMock
    ) -> None:
        mock_transport._register_snapshot = {"input": {}, "holding": {}}
        frames = emitter._build_data()
        assert frames == []


class TestCommandParsing:
    def test_get_param_identified(self, emitter: CloudEmitter) -> None:
        """0xC3 frame should be identified as GET_PARAM."""
        # Build a GET_PARAM frame: start_param=10, end_param=15
        payload = struct.pack("<HH", 10, 15)
        frame = build_frame(
            func=FUNC_GET_PARAM,
            serial=DONGLE_SERIAL,
            payload=payload,
        )
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_GET_PARAM

    def test_set_param_identified(self, emitter: CloudEmitter) -> None:
        """0xC4 frame should be identified as SET_PARAM."""
        # Build a SET_PARAM frame: param_code=100, data_len=2, data=0x1234
        payload = struct.pack("<HH", 100, 2) + struct.pack("<H", 0x1234)
        frame = build_frame(
            func=FUNC_SET_PARAM,
            serial=DONGLE_SERIAL,
            payload=payload,
        )
        parsed = parse_frame(frame)
        assert parsed is not None
        assert parsed.func == FUNC_SET_PARAM


class TestDongleInternalCodes:
    """SET_PARAM codes that configured the physical dongle (not the inverter)."""

    @pytest.mark.parametrize(
        "code",
        [0, 1, 3, 4, 6, 9, 0x0C, 0x0D, 0x11, 0x12, 0x14],
    )
    def test_dongle_internal_codes(self, emitter: CloudEmitter, code: int) -> None:
        assert code in emitter.DONGLE_INTERNAL_CODES


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, emitter: CloudEmitter) -> None:
        with patch.object(emitter, "_run_loop", new_callable=AsyncMock):
            await emitter.start()
            assert emitter._task is not None
            await emitter.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, emitter: CloudEmitter) -> None:
        with patch.object(emitter, "_run_loop", new_callable=AsyncMock):
            await emitter.start()
            await emitter.stop()
            assert emitter._task is None or emitter._task.cancelled()

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self, emitter: CloudEmitter) -> None:
        with patch.object(emitter, "_run_loop", new_callable=AsyncMock):
            await emitter.start()
            await emitter.start()  # Should not error
            await emitter.stop()

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self, emitter: CloudEmitter) -> None:
        await emitter.stop()  # Should not error (never started)
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_emitter.py -v
```
Expected: FAIL

**Step 3: Implement CloudEmitter**

```python
# pylxpweb/src/pylxpweb/cloud/emitter.py
"""CloudEmitter: virtual WiFi dongle that forwards data to EG4 cloud.

Maintains a persistent TCP connection to the EG4 cloud ingestion server,
sending register data in the same binary protocol as the physical dongle.
Receives and proxies cloud commands (GET_PARAM, SET_PARAM) to the inverter.

Usage:
    emitter = CloudEmitter(
        dongle_serial="BA12345678",
        transport=modbus_transport,
    )
    await emitter.start()
    # ... emitter runs in background ...
    await emitter.stop()
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .frames import build_data_frames, build_heartbeat_frame
from .protocol import (
    CLOUD_HOST,
    CLOUD_PORT,
    FUNC_GET_PARAM,
    FUNC_SET_PARAM,
    build_frame,
    parse_frame,
)

if TYPE_CHECKING:
    from pylxpweb.transports.protocol import InverterTransport

_LOGGER = logging.getLogger(__name__)

# Timing constants (from firmware HeartbeatTimer decompilation)
_HEARTBEAT_INTERVAL = 18.0  # seconds of silence before sending heartbeat
_CONNECT_TIMEOUT = 5.0  # seconds (firmware uses 1s, we use 5s for reliability)
_RECONNECT_DELAY = 5.0  # seconds between reconnect attempts
_DEFAULT_DATA_PERIOD = 100.0  # seconds (firmware data_period=1 * 100)
_RECEIVE_TIMEOUT = 1.0  # seconds for non-blocking command check


class CloudEmitter:
    """Virtual WiFi dongle that forwards register data to EG4 cloud.

    Runs as an independent asyncio background task. Reads raw register
    snapshots stashed by the transport during normal HA polling (zero
    additional Modbus reads). Cloud commands trigger fresh reads/writes.
    """

    # SET_PARAM codes that configured the physical dongle, not the inverter.
    # These are ACK'd without forwarding to the inverter.
    DONGLE_INTERNAL_CODES: frozenset[int] = frozenset(
        {0, 1, 3, 4, 6, 9, 0x0C, 0x0D, 0x11, 0x12, 0x14}
    )

    def __init__(
        self,
        dongle_serial: str,
        transport: InverterTransport,
        host: str = CLOUD_HOST,
        port: int = CLOUD_PORT,
        data_period: float = _DEFAULT_DATA_PERIOD,
    ) -> None:
        """Initialize CloudEmitter.

        Args:
            dongle_serial: 10-digit dongle serial from cloud API.
            transport: Local transport for fresh reads on cloud commands.
            host: Cloud TCP server hostname.
            port: Cloud TCP server port.
            data_period: Seconds between data push cycles.
        """
        self._dongle_serial = dongle_serial
        self._transport = transport
        self._host = host
        self._port = port
        self._data_period = data_period

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_send_time: float = 0.0

    @property
    def is_connected(self) -> bool:
        """Whether TCP connection to cloud server is active."""
        return self._connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the cloud emitter background task."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        _LOGGER.info(
            "CloudEmitter started for dongle %s → %s:%d",
            self._dongle_serial,
            self._host,
            self._port,
        )

    async def stop(self) -> None:
        """Stop the cloud emitter and close TCP connection."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._disconnect()
        _LOGGER.info("CloudEmitter stopped for dongle %s", self._dongle_serial)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Establish TCP connection to cloud server."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=_CONNECT_TIMEOUT,
        )
        self._connected = True
        self._last_send_time = time.monotonic()
        _LOGGER.debug(
            "CloudEmitter connected to %s:%d", self._host, self._port
        )

    async def _disconnect(self) -> None:
        """Close TCP connection."""
        self._connected = False
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _send(self, data: bytes) -> None:
        """Send data and update last-send timestamp."""
        if self._writer is None:
            raise ConnectionError("Not connected")
        self._writer.write(data)
        await self._writer.drain()
        self._last_send_time = time.monotonic()

    # ------------------------------------------------------------------
    # Frame building helpers
    # ------------------------------------------------------------------

    def _build_heartbeat(self) -> bytes:
        """Build a 19-byte heartbeat frame."""
        return build_heartbeat_frame(self._dongle_serial)

    def _build_data(self) -> list[bytes]:
        """Build data frames from transport's register snapshot."""
        snapshot = getattr(self._transport, "_register_snapshot", None)
        if snapshot is None:
            return []
        return build_data_frames(self._dongle_serial, snapshot)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main loop: connect, heartbeat, send data, handle commands."""
        while self._running:
            try:
                await self._connect()
                await self._send(self._build_heartbeat())
                await self._data_and_command_loop()
            except (
                ConnectionError,
                OSError,
                asyncio.TimeoutError,
            ) as err:
                _LOGGER.warning(
                    "CloudEmitter connection error: %s. Reconnecting in %ss",
                    err,
                    _RECONNECT_DELAY,
                )
                await self._disconnect()
                await asyncio.sleep(_RECONNECT_DELAY)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("CloudEmitter unexpected error")
                await self._disconnect()
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _data_and_command_loop(self) -> None:
        """Inner loop: periodic data push + heartbeat + command receive."""
        last_data_send = time.monotonic()

        while self._running and self._connected:
            now = time.monotonic()

            # Send data if period elapsed
            if now - last_data_send >= self._data_period:
                await self._emit_data()
                last_data_send = now

            # Send heartbeat if silent too long
            if now - self._last_send_time >= _HEARTBEAT_INTERVAL:
                await self._send(self._build_heartbeat())

            # Check for incoming commands (non-blocking)
            await self._receive_commands()

    async def _emit_data(self) -> None:
        """Build and send all data frames for one poll cycle."""
        frames = self._build_data()
        if not frames:
            _LOGGER.debug("CloudEmitter: no register data to send (HA may not have polled yet)")
            return
        for frame in frames:
            await self._send(frame)
        _LOGGER.debug("CloudEmitter: sent %d data frames", len(frames))

    async def _receive_commands(self) -> None:
        """Non-blocking check for incoming cloud commands."""
        if self._reader is None:
            return
        try:
            data = await asyncio.wait_for(
                self._reader.read(4096),
                timeout=_RECEIVE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return

        if not data:
            # Server closed connection
            self._connected = False
            return

        parsed = parse_frame(data)
        if parsed is None:
            _LOGGER.debug("CloudEmitter: received unparseable frame (%d bytes)", len(data))
            return

        if parsed.func == FUNC_GET_PARAM:
            await self._handle_get_param(parsed.payload)
        elif parsed.func == FUNC_SET_PARAM:
            await self._handle_set_param(parsed.payload)
        else:
            _LOGGER.debug("CloudEmitter: received func 0x%02X (ignored)", parsed.func)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_get_param(self, payload: bytes) -> None:
        """Handle cloud GET_PARAM: fresh register read, send response."""
        if len(payload) < 4:
            return
        import struct

        start_param = struct.unpack_from("<H", payload, 0)[0]
        end_param = struct.unpack_from("<H", payload, 2)[0]
        count = end_param - start_param + 1

        _LOGGER.debug(
            "CloudEmitter: GET_PARAM regs %d-%d", start_param, end_param
        )
        try:
            values = await self._transport.read_parameters(start_param, count)
            # Build response frame
            response_payload = self._build_param_response(
                start_param, values
            )
            response = build_frame(
                func=FUNC_GET_PARAM,
                serial=self._dongle_serial,
                payload=response_payload,
            )
            await self._send(response)
        except Exception:
            _LOGGER.exception("CloudEmitter: GET_PARAM failed for regs %d-%d", start_param, end_param)

    async def _handle_set_param(self, payload: bytes) -> None:
        """Handle cloud SET_PARAM: write register or ACK dongle-internal code."""
        if len(payload) < 4:
            return
        import struct

        param_code = struct.unpack_from("<H", payload, 0)[0]
        data_len = struct.unpack_from("<H", payload, 2)[0]

        if param_code in self.DONGLE_INTERNAL_CODES:
            _LOGGER.debug(
                "CloudEmitter: SET_PARAM code %d is dongle-internal, ACK only",
                param_code,
            )
            return

        if len(payload) < 4 + data_len:
            return

        # Extract register value (first 2 bytes of data)
        if data_len >= 2:
            value = struct.unpack_from("<H", payload, 4)[0]
            _LOGGER.debug(
                "CloudEmitter: SET_PARAM reg %d = %d", param_code, value
            )
            try:
                await self._transport.write_parameters({param_code: value})
            except Exception:
                _LOGGER.exception(
                    "CloudEmitter: SET_PARAM failed for reg %d", param_code
                )

    def _build_param_response(
        self, start: int, values: dict[int, int]
    ) -> bytes:
        """Build GET_PARAM response payload."""
        import struct

        data = bytearray()
        for addr in sorted(values):
            data.extend(struct.pack("<H", values[addr] & 0xFFFF))
        return struct.pack("<H", start) + bytes(data)
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/unit/test_cloud_emitter.py -v
```
Expected: ALL PASS

**Step 5: Lint, type-check, full test suite**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run ruff check src/pylxpweb/cloud/ --fix && uv run ruff format src/pylxpweb/cloud/
uv run mypy src/pylxpweb/cloud/
uv run pytest tests/unit/ -x --tb=short
```
Expected: ALL PASS

**Step 6: Commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git add src/pylxpweb/cloud/emitter.py tests/unit/test_cloud_emitter.py
git commit -m "feat(cloud): add CloudEmitter with TCP connection, heartbeat, data forwarding, command handling"
```

---

## Task 5: Public API and Exports

Export CloudEmitter from pylxpweb's public API.

**Files:**
- Modify: `pylxpweb/src/pylxpweb/cloud/__init__.py`
- Modify: `pylxpweb/src/pylxpweb/__init__.py` (add cloud exports)

**Step 1: Update cloud `__init__.py`**

```python
# pylxpweb/src/pylxpweb/cloud/__init__.py
"""Cloud emulation for EG4 WiFi dongle replacement."""

from .emitter import CloudEmitter
from .protocol import (
    CLOUD_HOST,
    CLOUD_PORT,
    FUNC_DATA,
    FUNC_GET_PARAM,
    FUNC_HEARTBEAT,
    FUNC_SET_PARAM,
)

__all__ = [
    "CloudEmitter",
    "CLOUD_HOST",
    "CLOUD_PORT",
    "FUNC_DATA",
    "FUNC_GET_PARAM",
    "FUNC_HEARTBEAT",
    "FUNC_SET_PARAM",
]
```

**Step 2: Add to main pylxpweb `__init__.py`**

Add to the imports section of `pylxpweb/src/pylxpweb/__init__.py`:

```python
from .cloud import CloudEmitter
```

And add `"CloudEmitter"` to the `__all__` list.

**Step 3: Verify imports work**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run python -c "from pylxpweb import CloudEmitter; print(CloudEmitter)"
```
Expected: `<class 'pylxpweb.cloud.emitter.CloudEmitter'>`

**Step 4: Lint, commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run ruff check src/pylxpweb/ --fix && uv run ruff format src/pylxpweb/
git add src/pylxpweb/cloud/__init__.py src/pylxpweb/__init__.py
git commit -m "feat(cloud): export CloudEmitter from public API"
```

---

## Task 6: HA Integration — Config Flow Changes

Auto-detect dongle serial from cloud API and store in config entry.

**Files:**
- Modify: `eg4_web_monitor/custom_components/eg4_web_monitor/const.py` (add CONF_DONGLE_SERIAL, CONF_CLOUD_REPORTING)
- Modify: `eg4_web_monitor/custom_components/eg4_web_monitor/config_flow/__init__.py` (auto-detect serial)
- Modify: `eg4_web_monitor/custom_components/eg4_web_monitor/config_flow/options.py` (add toggle)
- Test: `eg4_web_monitor/tests/test_config_flow.py` (new test for dongle serial auto-detect)

**Context:**
- `InverterInfo.datalogSn` provides the dongle serial (from cloud API `get_inverter_list`)
- Already fetched during config flow in the plant selection step
- New config keys: `CONF_DONGLE_SERIAL`, `CONF_CLOUD_REPORTING`
- Options flow toggle: "Enable cloud data reporting" (only shown for local/hybrid with dongle serial)

**Note:** This task requires careful reading of the existing config flow before modifying. The exact integration points depend on the current flow structure. Read `config_flow/__init__.py` and `config_flow/options.py` first.

**Step 1: Add constants**

Add to `const.py`:
```python
CONF_DONGLE_SERIAL = "dongle_serial"
CONF_CLOUD_REPORTING = "cloud_reporting"
```

**Step 2: Auto-detect dongle serial in config flow**

In the config flow, after station/plant selection succeeds (where `InverterInfo` is already fetched), extract `datalogSn` from the first inverter's info and store it in the flow data. The exact location depends on reading the current code.

**Step 3: Add options flow toggle**

In `options.py`, add a boolean toggle for cloud reporting. Only show it when `CONF_DONGLE_SERIAL` is present in config entry data.

**Step 4: Write tests for the new config entries**

**Step 5: Run tests, lint, commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor
uv run pytest tests/test_config_flow.py tests/test_options_flow.py -v
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
git add custom_components/ tests/
git commit -m "feat(config): auto-detect dongle serial, add cloud reporting toggle"
```

---

## Task 7: HA Integration — Coordinator CloudEmitter Startup

Start/stop CloudEmitter from the coordinator when cloud reporting is enabled.

**Files:**
- Modify: `eg4_web_monitor/custom_components/eg4_web_monitor/coordinator.py`
- Test: `eg4_web_monitor/tests/test_coordinator.py` (new tests for emitter lifecycle)

**Context:**
- Coordinator reads `CONF_CLOUD_REPORTING` and `CONF_DONGLE_SERIAL` from config entry
- Creates `CloudEmitter` with the local transport
- Starts emitter after first successful data fetch
- Stops emitter on unload
- Emitter runs independently — no changes to polling logic

**Step 1: Add emitter to coordinator init**

```python
from pylxpweb import CloudEmitter

# In coordinator __init__:
self._cloud_emitter: CloudEmitter | None = None
```

**Step 2: Start emitter after first successful poll**

In `_async_update_data` (or `_async_update_local_data`), after first successful data fetch:

```python
if self._cloud_emitter is None and self._dongle_serial and self._cloud_reporting:
    transport = self._get_first_local_transport()
    if transport:
        self._cloud_emitter = CloudEmitter(
            dongle_serial=self._dongle_serial,
            transport=transport,
        )
        await self._cloud_emitter.start()
```

**Step 3: Stop emitter on unload**

In `async_unload` (or wherever background tasks are cleaned up):

```python
if self._cloud_emitter:
    await self._cloud_emitter.stop()
    self._cloud_emitter = None
```

**Step 4: Write tests**

Test that emitter starts when config has both `CONF_DONGLE_SERIAL` and `CONF_CLOUD_REPORTING=True`.
Test that emitter does NOT start when either is missing.
Test that emitter stops on unload.

**Step 5: Run tests, lint, commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor
uv run pytest tests/ -x --tb=short
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
git add custom_components/ tests/
git commit -m "feat(coordinator): start/stop CloudEmitter for cloud data reporting"
```

---

## Task 8: End-to-End Validation

Manual validation with real hardware. Not automated.

**Steps:**
1. Build pylxpweb with cloud module, install in HA docker container
2. Configure EG4 integration in local mode with cloud reporting enabled
3. Check cloud dashboard (`monitor.eg4electronics.com`) for data appearing
4. Verify heartbeat keeps connection alive (watch logs for 18s intervals)
5. Change a parameter via cloud dashboard, verify it propagates to HA
6. Disconnect network briefly, verify reconnection
7. Compare cloud dashboard values with local HA values

**Validation checklist:**
- [ ] Data appears on cloud dashboard within 2 minutes of enabling
- [ ] Heartbeat maintains connection for >10 minutes
- [ ] Cloud-initiated parameter read works (GET_PARAM)
- [ ] Cloud-initiated parameter write works (SET_PARAM)
- [ ] Reconnection after network interruption
- [ ] No additional Modbus reads (check debug logs)
- [ ] HA polling unaffected by CloudEmitter
