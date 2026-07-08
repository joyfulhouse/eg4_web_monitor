#!/usr/bin/env python3
"""Ghidra headless post-analysis script to extract decompiled functions and string xrefs.

Run via Ghidra headless:
  analyzeHeadless /tmp/ghidra_esp32_project esp32_dongle \
    -process app_code_IROM.bin \
    -noanalysis \
    -scriptPath /path/to/this/dir \
    -postScript ghidra_extract.py /path/to/output_dir
"""

# This script runs inside Ghidra's Jython environment
# pylint: disable=undefined-variable
import os

from ghidra.app.decompiler import DecompInterface, DecompileOptions
from ghidra.util.task import ConsoleTaskMonitor


def get_output_dir():
    """Get output directory from script args or default."""
    args = getScriptArgs()  # noqa: F821
    if args:
        return args[0]
    return "/tmp/ghidra_esp32_output"


def setup_decompiler(program):
    """Initialize decompiler interface."""
    decomp = DecompInterface()
    opts = DecompileOptions()
    decomp.setOptions(opts)
    decomp.openProgram(program)
    return decomp


def find_strings_containing(program, keywords):
    """Find defined strings containing any keyword, return {addr: string_value}."""
    listing = program.getListing()
    program.getMemory()
    strings = {}

    # Walk all defined data looking for strings
    data_iter = listing.getDefinedData(True)
    while data_iter.hasNext():
        d = data_iter.next()
        dt = d.getDataType()
        if "string" in dt.getName().lower():
            try:
                val = d.getValue()
                if val is not None:
                    s = str(val)
                    for kw in keywords:
                        if kw.lower() in s.lower():
                            strings[d.getAddress()] = s
                            break
            except Exception:
                pass

    return strings


def get_xrefs_to(program, addr):
    """Get all references to an address."""
    ref_mgr = program.getReferenceManager()
    return list(ref_mgr.getReferencesTo(addr))


def decompile_function_at(decomp, program, addr, monitor):
    """Decompile the function containing the given address."""
    func_mgr = program.getFunctionManager()
    func = func_mgr.getFunctionContaining(addr)
    if func is None:
        return None, None

    result = decomp.decompileFunction(func, 30, monitor)
    if result and result.depiledFunction():
        return func, result.getDecompiledFunction().getC()
    return func, None


def export_all_functions(program, decomp, monitor, output_dir):
    """Export summary of all functions."""
    func_mgr = program.getFunctionManager()
    funcs = []

    func_iter = func_mgr.getFunctions(True)
    while func_iter.hasNext():
        f = func_iter.next()
        funcs.append(
            {
                "name": f.getName(),
                "addr": str(f.getEntryPoint()),
                "size": f.getBody().getNumAddresses(),
            }
        )

    # Sort by size descending
    funcs.sort(key=lambda x: -x["size"])

    path = os.path.join(output_dir, "function_list.txt")
    with open(path, "w") as fh:
        fh.write("# All functions sorted by size (largest first)\n")
        fh.write("# Address | Size | Name\n")
        fh.write("-" * 60 + "\n")
        for f in funcs:
            fh.write("0x{:<12s} {:>8d}  {}\n".format(f["addr"], f["size"], f["name"]))
        fh.write("\nTotal functions: {}\n".format(len(funcs)))

    print("Exported {} functions to {}".format(len(funcs), path))
    return funcs


def export_string_xrefs(program, decomp, monitor, output_dir, keywords):
    """Find strings matching keywords and decompile referencing functions."""
    strings = find_strings_containing(program, keywords)
    print("Found {} matching strings".format(len(strings)))

    path = os.path.join(output_dir, "string_xrefs.txt")
    decompiled_path = os.path.join(output_dir, "decompiled_protocol.c")

    seen_funcs = set()
    decompiled_code = []

    with open(path, "w") as fh:
        fh.write("# String cross-references for protocol analysis\n")
        fh.write("# Keywords: {}\n\n".format(", ".join(keywords)))

        for addr, s in sorted(strings.items(), key=lambda x: str(x[1])):
            fh.write('\n--- String at {}: "{}"\n'.format(addr, s[:200]))
            xrefs = get_xrefs_to(program, addr)
            if not xrefs:
                fh.write("  (no references found)\n")
                continue

            for ref in xrefs:
                from_addr = ref.getFromAddress()
                func_mgr = program.getFunctionManager()
                func = func_mgr.getFunctionContaining(from_addr)
                if func:
                    func_name = func.getName()
                    func_addr = str(func.getEntryPoint())
                    fh.write("  Referenced by: {} @ {}\n".format(func_name, func_addr))

                    # Decompile if we haven't already
                    if func_addr not in seen_funcs:
                        seen_funcs.add(func_addr)
                        result = decomp.decompileFunction(func, 30, monitor)
                        if result and result.getDecompiledFunction():
                            c_code = result.getDecompiledFunction().getC()
                            if c_code:
                                decompiled_code.append(
                                    '// === {} @ {} ===\n// Referenced string: "{}"\n\n{}\n'.format(
                                        func_name, func_addr, s[:100], c_code
                                    )
                                )
                else:
                    fh.write(
                        "  Referenced from: {} (not in a function)\n".format(from_addr)
                    )

    # Write all decompiled protocol functions
    with open(decompiled_path, "w") as fh:
        fh.write(
            "// Decompiled protocol-related functions from ESP32-C3 dongle firmware\n"
        )
        fh.write(
            "// Generated by Ghidra {} headless analysis\n\n".format(
                getGhidraVersion() if "getGhidraVersion" in dir() else "12.0.3"  # noqa: F821
            )
        )
        for code in decompiled_code:
            fh.write(code)
            fh.write("\n" + "=" * 80 + "\n\n")

    print(
        "Exported {} decompiled functions to {}".format(
            len(decompiled_code), decompiled_path
        )
    )
    return seen_funcs


def export_large_functions(program, decomp, monitor, output_dir, top_n=50):
    """Decompile the N largest functions."""
    func_mgr = program.getFunctionManager()
    funcs = []

    func_iter = func_mgr.getFunctions(True)
    while func_iter.hasNext():
        f = func_iter.next()
        funcs.append(f)

    # Sort by size descending
    funcs.sort(key=lambda f: -f.getBody().getNumAddresses())

    path = os.path.join(output_dir, "decompiled_large.c")
    with open(path, "w") as fh:
        fh.write("// Top {} largest functions decompiled\n\n".format(top_n))
        for f in funcs[:top_n]:
            result = decomp.decompileFunction(f, 30, monitor)
            if result and result.getDecompiledFunction():
                c_code = result.getDecompiledFunction().getC()
                if c_code:
                    fh.write(
                        "// === {} @ {} ({} bytes) ===\n\n{}\n".format(
                            f.getName(),
                            f.getEntryPoint(),
                            f.getBody().getNumAddresses(),
                            c_code,
                        )
                    )
                    fh.write("\n" + "=" * 80 + "\n\n")

    print("Exported top {} functions to {}".format(top_n, path))


def run():
    output_dir = get_output_dir()
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    program = getCurrentProgram()  # noqa: F821
    monitor = ConsoleTaskMonitor()
    decomp = setup_decompiler(program)

    print("\n=== Ghidra ESP32-C3 Firmware Analysis ===\n")

    # 1. Export all functions
    export_all_functions(program, decomp, monitor, output_dir)

    # 2. Find protocol-related strings and decompile referencing functions
    protocol_keywords = [
        "FUNC_CODE",
        "DATA_TRANSMISSION",
        "GET_PARAM",
        "SET_PARAM",
        "HEARBEAT",
        "HEARTBEAT",
        "rs485",
        "RS485",
        "tcp_client",
        "tcp_server",
        "modbus",
        "register",
        "inverter",
        "battery",
        "soc",
        "hido-iot",
        "solarcloudsystem",
        "luxpower",
        "wifi_config",
        "ble_",
        "uart",
        "serial_port",
        "crc",
        "encrypt",
        "decrypt",
        "firmware",
        "ota_",
        "update",
    ]
    export_string_xrefs(program, decomp, monitor, output_dir, protocol_keywords)

    # 3. Decompile the 50 largest functions
    export_large_functions(program, decomp, monitor, output_dir, top_n=50)

    print("\n=== Analysis complete. Output in: {} ===".format(output_dir))


run()
