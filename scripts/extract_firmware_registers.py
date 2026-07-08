"""Extract Modbus register map from decompiled ARM firmware and cross-reference with known maps.

Reads the decompiled C code, data tables, numeric tables, and live register dumps
from the firmware RE directory, then cross-references with pylxpweb register definitions
to identify known vs newly-discovered registers.

Output: docs/reference/firmware_re/REGISTER_MAP_FROM_FIRMWARE.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Paths
RE_DIR = Path("docs/reference/firmware_re")
PYLXPWEB_REG_DIR = Path(
    "/Users/bryanli/Projects/joyfulhouse/python/pylxpweb/src/pylxpweb/registers"
)
OUTPUT = RE_DIR / "REGISTER_MAP_FROM_FIRMWARE.md"


# ============================================================================
# 1. Parse pylxpweb register definitions to build the "known" map
# ============================================================================
def _extract_field(block: str, field: str) -> str:
    """Extract a named field value from a dataclass constructor block."""
    # Match field="value" or field=None or field=EnumType.VALUE
    m = re.search(rf'{field}="([^"]*)"', block)
    if m:
        return m.group(1)
    m = re.search(rf"{field}=ScaleFactor\.(\w+)", block)
    if m:
        return m.group(1)
    m = re.search(rf"{field}=None", block)
    if m:
        return ""
    m = re.search(rf"{field}=(\d+)", block)
    if m:
        return m.group(1)
    return ""


def parse_pylxpweb_input_registers() -> dict[int, dict[str, str]]:
    """Parse inverter_input.py for known input register definitions."""
    path = PYLXPWEB_REG_DIR / "inverter_input.py"
    text = path.read_text()
    regs: dict[int, dict[str, str]] = {}

    # Split on RegisterDefinition blocks
    blocks = re.split(r"RegisterDefinition\(", text)[1:]

    for block in blocks:
        # Find the closing paren (allow nested parens)
        depth = 1
        end = 0
        for i, ch in enumerate(block):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        block = block[:end]

        addr_m = re.search(r"address=(\d+)", block)
        name_m = re.search(r'canonical_name="([^"]*)"', block)
        if not addr_m or not name_m:
            continue

        addr = int(addr_m.group(1))
        regs[addr] = {
            "canonical_name": name_m.group(1),
            "cloud_api_field": _extract_field(block, "cloud_api_field"),
            "ha_sensor_key": _extract_field(block, "ha_sensor_key"),
            "scale": _extract_field(block, "scale") or "NONE",
            "unit": _extract_field(block, "unit"),
            "description": _extract_field(block, "description"),
        }
    return regs


def parse_pylxpweb_holding_registers() -> dict[int, dict[str, str]]:
    """Parse inverter_holding.py for known holding register definitions."""
    path = PYLXPWEB_REG_DIR / "inverter_holding.py"
    text = path.read_text()
    regs: dict[int, dict[str, str]] = {}

    blocks = re.split(r"HoldingRegisterDefinition\(", text)[1:]

    for block in blocks:
        depth = 1
        end = 0
        for i, ch in enumerate(block):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        block = block[:end]

        addr_m = re.search(r"address=(\d+)", block)
        name_m = re.search(r'canonical_name="([^"]*)"', block)
        key_m = re.search(r'api_param_key="([^"]*)"', block)
        if not addr_m or not name_m:
            continue

        addr = int(addr_m.group(1))
        entry = {
            "canonical_name": name_m.group(1),
            "api_param_key": key_m.group(1) if key_m else "",
            "ha_entity_key": _extract_field(block, "ha_entity_key"),
            "description": _extract_field(block, "description"),
        }
        if addr not in regs:
            regs[addr] = entry
        # For bitfield registers, keep first entry (or append)
    return regs


def parse_battery_registers() -> dict[int, dict[str, str]]:
    """Parse battery.py for known battery register offsets."""
    path = PYLXPWEB_REG_DIR / "battery.py"
    text = path.read_text()
    regs: dict[int, dict[str, str]] = {}

    pattern = re.compile(
        r"(?:BatteryRegisterDefinition|RegisterDefinition)\(\s*"
        r"(?:offset|address)=(\d+).*?"
        r'canonical_name="([^"]*)".*?'
        r'(?:description="([^"]*)")?',
        re.DOTALL,
    )

    for m in pattern.finditer(text):
        offset = int(m.group(1))
        regs[offset] = {
            "canonical_name": m.group(2),
            "description": m.group(3) or "",
        }
    return regs


# ============================================================================
# 2. Parse live register dump
# ============================================================================
def parse_live_dump() -> dict[str, dict[str, dict[str, int]]]:
    """Parse the live register dump JSON."""
    path = RE_DIR / "live_register_dump.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]


# ============================================================================
# 3. Extract firmware data from numeric tables
# ============================================================================
def parse_firmware_register_map() -> list[dict[str, str | int]]:
    """Extract register read map from 04_numeric_tables.txt."""
    path = RE_DIR / "04_numeric_tables.txt"
    text = path.read_text()
    entries: list[dict[str, str | int]] = []

    # Parse "read holding regs N-M (start=S, count=C)"
    pattern = re.compile(
        r"read (\w+) regs\s+(\d+)-\s*(\d+)\s*\(start=(\d+),\s*count=(\d+)\)"
    )
    for m in pattern.finditer(text):
        entries.append(
            {
                "type": m.group(1),
                "start": int(m.group(4)),
                "count": int(m.group(5)),
                "end": int(m.group(3)),
            }
        )

    # Parse register lists
    list_pattern = re.compile(r"Register list \w+ @ [^:]+:\s*\[([^\]]+)\]")
    for m in list_pattern.finditer(text):
        vals = [int(x.strip()) for x in m.group(1).split(",")]
        for v in vals:
            entries.append({"type": "holding_list", "address": v})

    return entries


# ============================================================================
# 4. Search decompiled C for register-related constants
# ============================================================================
def search_decompiled_for_constants(
    files: list[Path],
) -> dict[str, list[dict[str, str | int]]]:
    """Search decompiled C files for numeric constants that could be register addresses."""
    results: dict[str, list[dict[str, str | int]]] = {
        "hex_comparisons": [],
        "decimal_comparisons": [],
        "function_codes": [],
        "array_inits": [],
        "register_offsets": [],
    }

    for fpath in files:
        text = fpath.read_text()
        fname = fpath.name

        # Find Modbus function code checks (FC 3, 4, 6, 16, 22)
        fc_pattern = re.compile(r"(param_\d+\s*\+\s*1\)\s*==\s*'\\x(\w+)')")
        for m in fc_pattern.finditer(text):
            code_hex = m.group(2)
            code_int = int(code_hex, 16)
            if code_int in {3, 4, 6, 0x10, 0x16}:
                results["function_codes"].append(
                    {
                        "file": fname,
                        "code": code_int,
                        "context": m.group(1),
                    }
                )

        # Find hex constants 0x0000-0x01FF (0-511, register range)
        hex_cmp = re.compile(r"(?:==|!=|<|>|<=|>=)\s*0x([0-9a-fA-F]{1,4})\b")
        for m in hex_cmp.finditer(text):
            val = int(m.group(1), 16)
            if 0 <= val <= 500:
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start:line_end].strip()
                results["hex_comparisons"].append(
                    {
                        "file": fname,
                        "value": val,
                        "hex": f"0x{m.group(1)}",
                        "line": line[:120],
                    }
                )

        # Battery register range (5000-5200) as hex 0x1388-0x1450
        batt_pattern = re.compile(r"0x1[3-4][0-9a-fA-F]{2}")
        for m in batt_pattern.finditer(text):
            val = int(m.group(0), 16)
            if 5000 <= val <= 5200:
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start:line_end].strip()
                results["register_offsets"].append(
                    {
                        "file": fname,
                        "value": val,
                        "hex": m.group(0),
                        "line": line[:120],
                    }
                )

        # Find decimal comparisons in useful register ranges
        dec_cmp = re.compile(r"(?:==|!=|<|>|<=|>=)\s*(\d{1,3})\b(?!\s*\))")
        for m in dec_cmp.finditer(text):
            val = int(m.group(1))
            # Only track values that look like register addresses
            if 60 <= val <= 380 or val in {0, 5, 6, 19, 20, 21}:
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start:line_end].strip()
                results["decimal_comparisons"].append(
                    {
                        "file": fname,
                        "value": val,
                        "line": line[:120],
                    }
                )

        # Find offset patterns like param + N where N is 0-400
        offset_pat = re.compile(
            r"(?:param_\d+|uVar\d+|iVar\d+)\s*\+\s*(0x[0-9a-fA-F]+|\d+)"
        )
        for m in offset_pat.finditer(text):
            raw = m.group(1)
            val = int(raw, 16) if raw.startswith("0x") else int(raw)
            if 2 <= val <= 400:
                pass  # Too noisy, skip for now

    return results


# ============================================================================
# 5. Analyze live register dump for non-zero "undocumented" registers
# ============================================================================
def find_undocumented_nonzero(
    live_data: dict[str, dict[str, dict[str, int]]],
    known_input: dict[int, dict[str, str]],
    known_holding: dict[int, dict[str, str]],
) -> dict[str, list[dict[str, int | str]]]:
    """Find non-zero register values in the live dump that are NOT in pylxpweb."""
    results: dict[str, list[dict[str, int | str]]] = {}

    for device, data in live_data.items():
        device_results: list[dict[str, int | str]] = []

        # Check input registers
        for addr_s, value in data.get("input", {}).items():
            addr = int(addr_s)
            if value != 0 and addr not in known_input and addr < 5000:
                device_results.append(
                    {
                        "type": "input",
                        "address": addr,
                        "value": value,
                        "status": "UNDOCUMENTED (non-zero)",
                    }
                )

        # Check holding registers
        for addr_s, value in data.get("holding", {}).items():
            addr = int(addr_s)
            if value != 0 and addr not in known_holding:
                device_results.append(
                    {
                        "type": "holding",
                        "address": addr,
                        "value": value,
                        "status": "UNDOCUMENTED (non-zero)",
                    }
                )

        results[device] = device_results

    return results


# ============================================================================
# 6. Build comprehensive register map
# ============================================================================
def build_register_map(
    known_input: dict[int, dict[str, str]],
    known_holding: dict[int, dict[str, str]],
    live_data: dict[str, dict[str, dict[str, int]]],
    firmware_map: list[dict[str, str | int]],
    undocumented: dict[str, list[dict[str, int | str]]],
) -> str:
    """Build the markdown output document."""
    lines: list[str] = []

    lines.append("# Firmware Register Map Extraction")
    lines.append("")
    lines.append("**Generated from**: EG4 18kPV ARM Cortex-M4 firmware decompilation")
    lines.append("**Firmware file**: `18kpv_FAAB-27xx_20260330_App.bin`")
    lines.append(
        "**Live dump devices**: 18kPV (10.100.14.68), FlexBOSS21 (10.100.10.184)"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 1: Firmware read map from numeric tables
    lines.append("## 1. DSP Firmware Register Read Map")
    lines.append("")
    lines.append(
        "Extracted from the DSP firmware's literal pool at offset 0x1A306-0x1A368."
    )
    lines.append(
        "These define the Modbus register blocks the firmware reads from the ARM controller."
    )
    lines.append("")
    lines.append("### Holding Register Read Blocks")
    lines.append("")
    lines.append("| Block | Start Reg | Count | End Reg | Coverage |")
    lines.append("|-------|-----------|-------|---------|----------|")

    block_num = 0
    covered_holding: set[int] = set()
    for entry in firmware_map:
        if entry.get("type") == "holding":
            block_num += 1
            start = int(entry["start"])  # type: ignore[arg-type]
            count = int(entry["count"])  # type: ignore[arg-type]
            end = int(entry["end"])  # type: ignore[arg-type]
            for r in range(start, start + count):
                covered_holding.add(r)
            lines.append(
                f"| {block_num} | {start} | {count} | {end} | regs {start}-{end} |"
            )

    lines.append("")
    lines.append(
        f"**Total holding registers covered by firmware reads**: {len(covered_holding)}"
    )
    lines.append(
        f"**Range**: {min(covered_holding) if covered_holding else 'N/A'}-{max(covered_holding) if covered_holding else 'N/A'}"
    )
    lines.append("")

    lines.append("### Input Register Read Blocks")
    lines.append("")
    lines.append("| Block | Start Reg | Count | Coverage |")
    lines.append("|-------|-----------|-------|----------|")
    for entry in firmware_map:
        if entry.get("type") == "input":
            start = int(entry["start"])  # type: ignore[arg-type]
            count = int(entry["count"])  # type: ignore[arg-type]
            lines.append(
                f"| - | {start} | {count} | regs {start}-{start + count - 1} |"
            )

    lines.append("")

    lines.append("### Holding Register Address Lists (from DSP literal pool)")
    lines.append("")
    lines.append("Individual holding registers referenced in the DSP firmware:")
    lines.append("")
    list_regs = sorted(
        set(
            int(e["address"])
            for e in firmware_map  # type: ignore[arg-type]
            if e.get("type") == "holding_list"
        )
    )
    for addr in list_regs:
        known = known_holding.get(addr, {})
        name = known.get("canonical_name", "?")
        lines.append(f"- **reg {addr}**: `{name}`")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Section 2: Complete Input Register Map
    lines.append("## 2. Input Registers (FC 0x04) - Complete Map")
    lines.append("")
    lines.append("Cross-reference: pylxpweb definitions + live register dump values.")
    lines.append("")
    lines.append("### Known Registers (in pylxpweb)")
    lines.append("")
    lines.append(
        "| Reg | Canonical Name | Scale | Unit | HA Sensor Key | 18kPV Value | FB21 Value |"
    )
    lines.append(
        "|-----|----------------|-------|------|---------------|-------------|------------|"
    )

    for addr in sorted(known_input.keys()):
        reg = known_input[addr]
        val_18k = ""
        val_fb = ""
        for dev, data in live_data.items():
            raw = data.get("input", {}).get(str(addr))
            if raw is not None:
                if "18kPV" in dev:
                    val_18k = str(raw)
                elif "FlexBOSS" in dev:
                    val_fb = str(raw)
        lines.append(
            f"| {addr} | `{reg['canonical_name']}` | {reg['scale']} | {reg['unit']} | "
            f"`{reg['ha_sensor_key']}` | {val_18k} | {val_fb} |"
        )

    lines.append("")

    # Non-zero undocumented input registers
    lines.append("### Undocumented Input Registers (non-zero in live dump)")
    lines.append("")
    lines.append("These registers have data but no pylxpweb definition.")
    lines.append("")
    lines.append("| Reg | 18kPV Value | FB21 Value | Possible Interpretation |")
    lines.append("|-----|-------------|------------|------------------------|")

    # Collect all undocumented input regs
    undoc_input: dict[int, dict[str, int]] = {}
    for dev, regs_list in undocumented.items():
        for entry in regs_list:
            if entry["type"] == "input":
                addr = int(entry["address"])  # type: ignore[arg-type]
                if addr not in undoc_input:
                    undoc_input[addr] = {}
                undoc_input[addr][dev] = int(entry["value"])  # type: ignore[arg-type]

    for addr in sorted(undoc_input.keys()):
        vals = undoc_input[addr]
        val_18k = str(vals.get("18kPV", ""))
        val_fb = str(vals.get("FlexBOSS21", ""))
        interp = _interpret_register(addr, vals)
        lines.append(f"| {addr} | {val_18k} | {val_fb} | {interp} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 3: Complete Holding Register Map
    lines.append("## 3. Holding Registers (FC 0x03) - Complete Map")
    lines.append("")
    lines.append("### Known Registers (in pylxpweb)")
    lines.append("")
    lines.append(
        "| Reg | Canonical Name | API Param Key | HA Entity Key | 18kPV | FB21 |"
    )
    lines.append(
        "|-----|----------------|---------------|---------------|-------|------|"
    )

    for addr in sorted(known_holding.keys()):
        reg = known_holding[addr]
        val_18k = ""
        val_fb = ""
        for dev, data in live_data.items():
            raw = data.get("holding", {}).get(str(addr))
            if raw is not None:
                if "18kPV" in dev:
                    val_18k = str(raw)
                elif "FlexBOSS" in dev:
                    val_fb = str(raw)
        lines.append(
            f"| {addr} | `{reg['canonical_name']}` | `{reg['api_param_key']}` | "
            f"`{reg.get('ha_entity_key', '')}` | {val_18k} | {val_fb} |"
        )

    lines.append("")

    # Non-zero undocumented holding registers
    lines.append("### Undocumented Holding Registers (non-zero in live dump)")
    lines.append("")
    lines.append("| Reg | 18kPV Value | FB21 Value | Possible Interpretation |")
    lines.append("|-----|-------------|------------|------------------------|")

    undoc_holding: dict[int, dict[str, int]] = {}
    for dev, regs_list in undocumented.items():
        for entry in regs_list:
            if entry["type"] == "holding":
                addr = int(entry["address"])  # type: ignore[arg-type]
                if addr not in undoc_holding:
                    undoc_holding[addr] = {}
                undoc_holding[addr][dev] = int(entry["value"])  # type: ignore[arg-type]

    for addr in sorted(undoc_holding.keys()):
        vals = undoc_holding[addr]
        val_18k = str(vals.get("18kPV", ""))
        val_fb = str(vals.get("FlexBOSS21", ""))
        interp = _interpret_holding_register(addr, vals)
        lines.append(f"| {addr} | {val_18k} | {val_fb} | {interp} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 4: Battery register space
    lines.append("## 4. Battery Register Space (Input Regs 5000-5124)")
    lines.append("")
    lines.append(
        "Base address: 5002, 30 registers per battery, max 5 batteries per inverter."
    )
    lines.append("")
    lines.append("### 18kPV Battery Data (3 batteries)")
    lines.append("")
    lines.append("| Offset | Reg | Name | Battery 1 | Battery 2 | Battery 3 |")
    lines.append("|--------|-----|------|-----------|-----------|-----------|")

    batt_offsets = {
        0: "protocol_id",
        1: "full_capacity",
        2: "charge_voltage_ref",
        3: "charge_current_limit",
        4: "discharge_current_limit",
        5: "reserved_5",
        6: "voltage",
        7: "current",
        8: "soc_soh_packed",
        9: "cycle_count",
        10: "reserved_10",
        11: "reserved_11",
        12: "max_cell_voltage",
        13: "min_cell_voltage",
        14: "max_cell_temp",
        15: "min_cell_temp",
        16: "bms_flags",
        17: "bms_version",
        18: "bms_serial_1",
        19: "bms_serial_2",
        20: "bms_serial_3",
        21: "bms_serial_4",
        22: "bms_serial_5",
        23: "bms_serial_6",
        24: "bms_serial_7",
        25: "bms_serial_8",
        26: "reserved_26",
        27: "reserved_27",
        28: "reserved_28",
        29: "reserved_29",
    }

    input_18k = live_data.get("18kPV", {}).get("input", {})
    for offset in range(30):
        name = batt_offsets.get(offset, f"unknown_{offset}")
        b1_reg = 5002 + offset
        b2_reg = 5032 + offset
        b3_reg = 5062 + offset
        b1_val = input_18k.get(str(b1_reg), "")
        b2_val = input_18k.get(str(b2_reg), "")
        b3_val = input_18k.get(str(b3_reg), "")
        lines.append(
            f"| {offset} | {b1_reg}/{b2_reg}/{b3_reg} | `{name}` | "
            f"{b1_val} | {b2_val} | {b3_val} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 5: Firmware decompilation analysis
    lines.append("## 5. ARM Firmware Decompilation Analysis")
    lines.append("")
    lines.append("### FUN_08041612 (5,818 bytes) - Main Modbus Handler")
    lines.append("")
    lines.append(
        "The largest function in the firmware. Ghidra's decompilation is heavily"
    )
    lines.append("corrupted due to ARM Thumb-2 mixed instruction/data issues.")
    lines.append("")
    lines.append("**What is recoverable from the decompiled output:**")
    lines.append("")
    lines.append(
        "1. **Slave address check**: `(char)local_28 == '\\x01'` -- checks Modbus slave ID = 1"
    )
    lines.append(
        "2. **FC 0x06 handler**: `*(char *)(param_1 + 1) == '\\x06'` -- Write Single Register"
    )
    lines.append(
        "   - Extracts register address from bytes 2-3: `CONCAT11(*(param_1 + 2), *(param_1 + 3))`"
    )
    lines.append("   - Sets count=1, response length=4 (standard FC 06 response)")
    lines.append(
        "3. **FC 0x16 handler**: `*(char *)(param_1 + 1) == '\\x16'` -- Mask Write Register (FC 22)"
    )
    lines.append("   - Extracts register count from offset 0x0E")
    lines.append("   - Response length = 0x11 (17 bytes)")
    lines.append("4. **Calls FUN_080659f2**: Memory clear/init (memset-like)")
    lines.append("5. **Calls FUN_08023ace**: Likely CRC calculation or UART transmit")
    lines.append("6. **Calls FUN_080587e4**: Likely register access/validation")
    lines.append("")
    lines.append("**Why full register extraction failed:**")
    lines.append(
        "- 90+ 'Removing unreachable block' warnings indicate Ghidra couldn't follow branch tables"
    )
    lines.append(
        "- 'Bad instruction data' and 'Truncating control flow' at the core register dispatch code"
    )
    lines.append("- ARM Thumb-2 inline literal pools misidentified as instructions")
    lines.append(
        "- The register dispatch likely uses a computed jump table (switch statement) that"
    )
    lines.append("  Ghidra couldn't reconstruct from the binary")
    lines.append("")

    lines.append("### Other Modbus-Related Functions")
    lines.append("")
    lines.append("| Function | Size | FC Codes | Role |")
    lines.append("|----------|------|----------|------|")
    lines.append("| FUN_08041612 | 5,818B | FC6, FC22 | Main Modbus PDU handler |")
    lines.append(
        "| FUN_08040ce8 | 668B | - | Register value processor (param validation?) |"
    )
    lines.append(
        "| FUN_0803d340 | ~500B | FC16, FC22 | Write-multiple response handler |"
    )
    lines.append("| FUN_08045f34 | 810B | FC3/FC4 | Read response builder |")
    lines.append("| FUN_080376cc | 1,080B | FC3 | UART/Modbus state machine |")
    lines.append("")

    lines.append("### Modbus Function Code Summary")
    lines.append("")
    lines.append("| FC | Hex | Name | Found In |")
    lines.append("|----|-----|------|----------|")
    lines.append("| 3 | 0x03 | Read Holding Registers | FUN_080376cc, FUN_08045f34 |")
    lines.append("| 4 | 0x04 | Read Input Registers | (implied by FC3 handler) |")
    lines.append("| 6 | 0x06 | Write Single Register | FUN_08041612 |")
    lines.append("| 16 | 0x10 | Write Multiple Registers | FUN_0803d340 |")
    lines.append("| 22 | 0x16 | Mask Write Register | FUN_08041612, FUN_0803d340 |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Section 6: DSP code analysis
    lines.append("## 6. DSP Firmware Analysis (TI C28x)")
    lines.append("")
    lines.append(
        "The Para firmware (.bin files) contain TI C28x DSP code that implements"
    )
    lines.append("the actual register handling, validation, and scaling. Key findings:")
    lines.append("")
    lines.append("### Modbus Register Read Map (from DSP literal pool)")
    lines.append("")
    lines.append("The DSP firmware at offset 0x1A306 contains a structured table of")
    lines.append(
        "register block read definitions used for DSP-to-ARM register transfer:"
    )
    lines.append("")
    lines.append("```")
    lines.append("Section A - Single holding register blocks (12 regs each):")
    lines.append("  [0-11] [6-17] [18-29] [24-35] [30-41]    -- config/function regs")
    lines.append(
        "  [70-81] [72-83] [74-85] [76-87] [78-89]   -- PV/battery/schedule regs"
    )
    lines.append(
        "  [86-97] [88-99]                            -- battery/generator regs"
    )
    lines.append("")
    lines.append("Section B - Dual-block reads (input 14-29 + holding blocks):")
    lines.append("  [input 14-29] + [holding 0-11]")
    lines.append("  [input 14-29] + [holding 6-17]")
    lines.append("  [input 14-29] + [holding 18-29]")
    lines.append("  [input 14-29] + [holding 24-35]")
    lines.append("  [input 14-29] + [holding 30-41]")
    lines.append("```")
    lines.append("")
    lines.append("### Calibration Tables")
    lines.append("")
    lines.append("| Table | Offset | Entries | Description |")
    lines.append("|-------|--------|---------|-------------|")
    lines.append(
        "| PV voltage curves | 0x1A000 | 10 x 8 | MPPT voltage range limits (0.1V units) |"
    )
    lines.append(
        "| Power rating table | 0x1A0A0 | 8 x 8 | Model variant power limits |"
    )
    lines.append(
        "| Scaling table | 0x1A4E0 | 8 | Prescaler values [1,5,20,60,100,200,244,256] |"
    )
    lines.append(
        "| CRC-16/Modbus LOW | 0x24D8 | 256 | Standard Modbus CRC lookup (low byte) |"
    )
    lines.append(
        "| CRC-16/Modbus HIGH | 0x26D8 | 256 | Standard Modbus CRC lookup (high byte) |"
    )
    lines.append("")

    lines.append("### Power Rating Table (Model Variants)")
    lines.append("")
    lines.append(
        "| Row | Rated W | Min W | PV Cap | Batt Cap | Grid Cap | Possible Model |"
    )
    lines.append(
        "|-----|---------|-------|--------|----------|----------|---------------|"
    )
    lines.append("| 0 | 2,223 | 110 | 1,200 | 2,880 | 5,650 | Test/debug variant |")
    lines.append("| 1 | 6,200 | 200 | 240 | 2,880 | 5,000 | 12KPV base |")
    lines.append("| 2 | 6,500 | 200 | 1,080 | 2,980 | 5,600 | 12KPV with MPPT3 |")
    lines.append(
        "| 3 | 6,400 | 15 | 1,200 | 2,880 | 5,650 | Variant with strict limits |"
    )
    lines.append("| 4 | 6,200 | 100 | 240 | 2,880 | 5,000 | 12KPV variant (100W min) |")
    lines.append(
        "| 5 | 6,500 | 200 | 440 | 2,596 | 5,690 | Variant with lower batt cap |"
    )
    lines.append(
        "| 6 | 6,310 | 2 | 1,200 | 2,880 | 5,650 | Variant (2W minimum, strict) |"
    )
    lines.append("| 7 | 6,200 | 110 | 0 | 0 | 0 | Base variant, no caps defined |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Section 7: Summary statistics
    lines.append("## 7. Register Space Summary")
    lines.append("")

    # Count known vs total
    total_input_nonzero = set()
    total_holding_nonzero = set()
    for dev, data in live_data.items():
        for addr_s, val in data.get("input", {}).items():
            addr = int(addr_s)
            if val != 0:
                total_input_nonzero.add(addr)
        for addr_s, val in data.get("holding", {}).items():
            addr = int(addr_s)
            if val != 0:
                total_holding_nonzero.add(addr)

    known_input_addrs = set(known_input.keys())
    known_holding_addrs = set(known_holding.keys())

    lines.append("### Input Registers")
    lines.append(
        f"- **Total non-zero in live dump**: {len(total_input_nonzero)} registers"
    )
    lines.append(f"- **Defined in pylxpweb**: {len(known_input_addrs)} registers")
    lines.append(
        f"- **Undocumented non-zero**: {len(total_input_nonzero - known_input_addrs)} registers"
    )
    lines.append(
        f"- **Coverage**: {len(known_input_addrs & total_input_nonzero)}/{len(total_input_nonzero)} non-zero registers documented ({100 * len(known_input_addrs & total_input_nonzero) // max(len(total_input_nonzero), 1)}%)"
    )
    lines.append("")
    lines.append("### Holding Registers")
    lines.append(
        f"- **Total non-zero in live dump**: {len(total_holding_nonzero)} registers"
    )
    lines.append(f"- **Defined in pylxpweb**: {len(known_holding_addrs)} registers")
    lines.append(
        f"- **Undocumented non-zero**: {len(total_holding_nonzero - known_holding_addrs)} registers"
    )
    lines.append(
        f"- **Coverage**: {len(known_holding_addrs & total_holding_nonzero)}/{len(total_holding_nonzero)} non-zero registers documented ({100 * len(known_holding_addrs & total_holding_nonzero) // max(len(total_holding_nonzero), 1)}%)"
    )
    lines.append("")
    lines.append("### Battery Registers (5000-5124)")
    batt_nonzero = {a for a in total_input_nonzero if a >= 5000}
    lines.append(f"- **Non-zero registers**: {len(batt_nonzero)}")
    lines.append("- **Active batteries (18kPV)**: 3 (regs 5002-5091)")
    lines.append("- **Battery slots**: 5 max (5002-5151)")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Section 8: Recommendations
    lines.append("## 8. Recommendations for pylxpweb")
    lines.append("")
    lines.append("### High-Priority Undocumented Registers to Investigate")
    lines.append("")

    # Find the most interesting undocumented registers
    interesting_input = sorted(
        [(addr, undoc_input[addr]) for addr in undoc_input if addr < 5000],
        key=lambda x: x[0],
    )

    if interesting_input:
        lines.append("**Input Registers:**")
        for addr, vals in interesting_input:
            v_list = ", ".join(f"{dev}={v}" for dev, v in sorted(vals.items()))
            lines.append(
                f"- **Reg {addr}**: {v_list} -- {_interpret_register(addr, vals)}"
            )
        lines.append("")

    interesting_holding = sorted(
        [(addr, undoc_holding[addr]) for addr in undoc_holding],
        key=lambda x: x[0],
    )

    if interesting_holding:
        lines.append("**Holding Registers:**")
        for addr, vals in interesting_holding:
            v_list = ", ".join(f"{dev}={v}" for dev, v in sorted(vals.items()))
            lines.append(
                f"- **Reg {addr}**: {v_list} -- {_interpret_holding_register(addr, vals)}"
            )
        lines.append("")

    lines.append("### Register Gaps in Current Map")
    lines.append("")
    lines.append(
        "Input register addresses NOT defined in pylxpweb but within the active range (0-200):"
    )
    lines.append("")
    missing_input = sorted(set(range(200)) - known_input_addrs)
    lines.append(
        f"Missing: {missing_input[:50]}{'...' if len(missing_input) > 50 else ''}"
    )
    lines.append("")

    lines.append("### Firmware Architecture Insights")
    lines.append("")
    lines.append(
        "1. **Dual-CPU architecture**: ARM Cortex-M4 (communication/UI) + TI C28x DSP (power control)"
    )
    lines.append(
        "2. **Register transfer**: DSP reads holding regs in 12-register blocks, transfers to ARM"
    )
    lines.append(
        "3. **CRC-16/Modbus**: Standard polynomial confirmed (0xA001, init 0xFFFF)"
    )
    lines.append(
        "4. **Multi-model support**: Both 18kW and 21kW constants in single firmware image"
    )
    lines.append(
        "5. **Register map is code**: Implemented as C28x instructions, not data tables"
    )
    lines.append(
        "6. **Block checksums**: 771-byte blocks with model-specific XOR key (0xE7A7)"
    )
    lines.append("")

    return "\n".join(lines)


def _interpret_register(addr: int, vals: dict[str, int]) -> str:
    """Heuristic interpretation of an undocumented input register value."""
    avg = sum(vals.values()) / len(vals) if vals else 0

    # Known gaps in the register map
    if addr == 6:
        return "Unknown (between SOC/SOH packed and PV1 power)"
    if addr == 19:
        return "Power factor (DIV_1000, defined but no HA sensor)"
    if addr in {28, 29, 30}:
        return "PV1/PV2/PV3 energy today (defined, no HA sensor)"
    if addr == 32:
        return "AC charge energy today (Erec_day, defined, no HA sensor)"
    if addr == 35:
        return "EPS energy today (Eeps_day, defined, no HA sensor)"
    if addr in {40, 41, 42, 43, 44, 45}:
        return "PV energy lifetime (32-bit pairs, defined)"
    if addr in {48, 49}:
        return "AC charge energy lifetime (Erec_all, defined)"
    if addr in {54, 55}:
        return "EPS energy lifetime (Eeps_all, defined)"
    if 60 <= addr <= 63:
        return "Fault/warning code (32-bit pair, defined)"
    if addr == 68:
        return "Battery control temperature (defined, no HA sensor)"
    if addr in {69, 70}:
        return "Running time (32-bit, defined)"
    if 72 <= addr <= 75:
        return "PV current (DIV_100, defined, no HA sensor)"
    if 76 <= addr <= 99:
        return "BMS/parallel/generator registers (partially defined)"
    if 100 <= addr <= 108:
        return "BMS data (charge/discharge limits, temperature)"
    if 113 <= addr <= 120:
        return "Firmware version / serial number fields"
    if 121 <= addr <= 126:
        return "Extended runtime / energy counters"
    if 127 <= addr <= 128:
        return "EPS L1/L2 voltage (split-phase, defined)"
    if 134 <= addr <= 175:
        return "Holding register mirror (firmware quirk) or extended runtime"
    if 170 <= addr <= 174:
        return "Possible extended status/diagnostic registers"
    if addr >= 190:
        return "Three-phase / extended registers (LXP only?)"

    # Value-based heuristics
    if 100 <= avg <= 2500:
        return f"Possible voltage ({avg / 10:.1f}V) or power ({avg:.0f}W)"
    if 4000 <= avg <= 7000:
        return f"Possible frequency ({avg / 100:.2f}Hz) or large energy counter"
    if avg > 10000:
        return f"Possible energy counter or packed value (raw={avg:.0f})"
    return f"Unknown purpose (avg={avg:.0f})"


def _interpret_holding_register(addr: int, vals: dict[str, int]) -> str:
    """Heuristic interpretation of an undocumented holding register value."""
    avg = sum(vals.values()) / len(vals) if vals else 0

    # Known regions
    if 0 <= addr <= 8:
        return "HOLD_MODEL / serial number fields"
    if 11 <= addr <= 14:
        return "System/comm configuration"
    if 17 <= addr <= 18:
        return "Reserved system registers"
    if 22 <= addr <= 99:
        # Most of these should be defined
        if 22 <= addr <= 55:
            return "Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)"
        if 56 <= addr <= 99:
            return "Scheduling / generator / power parameter"
    if 100 <= addr <= 133:
        return "Battery BMS configuration / current limits"
    if 134 <= addr <= 175:
        return "Extended configuration / firmware-specific"
    if 176 <= addr <= 233:
        return "Extended function enable / peak shaving / advanced params"
    if 234 <= addr <= 255:
        return "Advanced configuration / model-specific"
    if 256 <= addr <= 366:
        return "Extended parameters (scheduling blocks, rare)"
    return f"Unknown (value={avg:.0f})"


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    print("Parsing pylxpweb register definitions...")
    known_input = parse_pylxpweb_input_registers()
    print(f"  Found {len(known_input)} input register definitions")

    known_holding = parse_pylxpweb_holding_registers()
    print(f"  Found {len(known_holding)} holding register definitions")

    print("Parsing live register dump...")
    live_data = parse_live_dump()
    for dev in live_data:
        n_hold = len(live_data[dev].get("holding", {}))
        n_input = len(live_data[dev].get("input", {}))
        print(f"  {dev}: {n_hold} holding, {n_input} input registers")

    print("Parsing firmware register map from numeric tables...")
    firmware_map = parse_firmware_register_map()
    print(f"  Found {len(firmware_map)} entries")

    print("Searching decompiled C files for register constants...")
    decompiled_files = sorted(RE_DIR.glob("07_decompiled_*.c"))
    _search_results = search_decompiled_for_constants(decompiled_files)
    print(f"  Found {sum(len(v) for v in _search_results.values())} pattern matches")

    print("Finding undocumented non-zero registers...")
    undocumented = find_undocumented_nonzero(live_data, known_input, known_holding)
    for dev, entries in undocumented.items():
        print(f"  {dev}: {len(entries)} undocumented non-zero registers")

    print("Building register map document...")
    output = build_register_map(
        known_input, known_holding, live_data, firmware_map, undocumented
    )

    OUTPUT.write_text(output)
    print(f"\nOutput written to: {OUTPUT}")
    print(f"Size: {len(output):,} bytes, {output.count(chr(10)):,} lines")


if __name__ == "__main__":
    main()
