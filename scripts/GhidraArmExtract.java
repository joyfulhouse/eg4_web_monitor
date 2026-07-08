// Comprehensive Ghidra headless post-analysis script for ARM Cortex-M4 inverter firmware.
// Extracts: functions, decompiled C, strings, xrefs, call graph, Modbus patterns, data tables.
//
// Run via:
//   analyzeHeadless /tmp/ghidra_arm_project arm_fw \
//     -import firmware.bin -processor "ARM:LE:32:Cortex" \
//     -cspec "default" -loader BinaryLoader -loader-baseAddr 0x08010000 \
//     -scriptPath /path/to/scripts \
//     -postScript GhidraArmExtract.java /path/to/output_dir
//
//@category Analysis

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.*;

public class GhidraArmExtract extends GhidraScript {

    // Known strings to prioritize in cross-reference analysis
    private static final String[] PRIORITY_STRINGS = {
        "DSPBOOTFLASH", "FreedWON", "HINAESS", "eTower", "EG4-LL",
        "Q3500", "512KEAA1", "NOTB", "UARB", "FAABFAABFAAB",
        "FAAB", "LuxPower", "luxpower", "LUXPOWER",
    };

    // Keywords for protocol/communication function identification
    private static final String[] PROTOCOL_KEYWORDS = {
        "modbus", "register", "uart", "serial", "rs485", "rs232",
        "crc", "checksum", "packet", "frame", "protocol", "command",
        "soc", "battery", "inverter", "charge", "discharge", "grid",
        "pv", "solar", "voltage", "current", "power", "energy",
        "temperature", "frequency", "dsp", "adc", "pwm", "timer",
        "flash", "eeprom", "nvs", "config", "param", "setting",
        "cloud", "server", "client", "tcp", "http", "mqtt", "wifi",
        "dongle", "ble", "bluetooth",
        "brand", "model", "serial", "firmware", "version", "ota",
        "error", "fault", "alarm", "warning", "status",
        "can", "spi", "i2c", "dma", "interrupt", "irq",
        "boot", "init", "main", "task", "thread", "rtos",
        "NOTB", "UARB", "FAAB",
        "FreedWON", "HINAESS", "eTower", "EG4",
    };

    private String outputDir;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        outputDir = args.length > 0 ? args[0]
            : "/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor/docs/reference/firmware_re";
        new File(outputDir).mkdirs();

        Program program = currentProgram;
        println("\n========================================================");
        println("  ARM Cortex-M4 Inverter Firmware Analysis");
        println("  Binary: " + program.getName());
        println("  Base: " + program.getMinAddress());
        println("  Size: " + program.getMemory().getSize() + " bytes");
        println("========================================================\n");

        // Initialize decompiler with extended timeout for large functions
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.openProgram(program);

        // 1. Memory map
        exportMemoryMap(program);

        // 2. Vector table analysis
        exportVectorTable(program);

        // 3. Full function list with sizes
        List<Function> allFuncs = getAllFunctions(program);
        exportFunctionList(allFuncs);

        // 4. All strings with addresses
        Map<Address, String> allStrings = findAllStrings(program);
        exportAllStrings(allStrings);

        // 5. String cross-references
        exportStringXrefs(program, decomp, allStrings);

        // 6. Priority string analysis (known firmware strings)
        exportPriorityStringAnalysis(program, decomp, allStrings);

        // 7. Decompile ALL functions (full C output)
        exportAllDecompiled(program, decomp, allFuncs);

        // 8. Call graph (cross-reference map)
        exportCallGraph(program, allFuncs);

        // 9. Data tables and constants
        exportDataTables(program);

        // 10. Modbus-related function identification
        exportModbusAnalysis(program, decomp, allFuncs);

        // 11. Brand/configuration table analysis
        exportBrandAnalysis(program, decomp);

        // 12. UART/Serial communication functions
        exportUartAnalysis(program, decomp, allFuncs);

        // 13. Interrupt handler analysis
        exportInterruptHandlers(program, decomp);

        // 14. Summary statistics
        exportSummary(program, allFuncs, allStrings);

        println("\n========================================================");
        println("  Analysis complete. Output in: " + outputDir);
        println("========================================================\n");

        decomp.dispose();
    }

    // ========================================================================
    // 1. Memory Map
    // ========================================================================
    private void exportMemoryMap(Program program) throws Exception {
        String path = outputDir + "/01_memory_map.txt";
        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Memory Map - ARM Cortex-M4 Inverter Firmware");
            pw.println("# Base address: 0x08010000");
            pw.println();
            pw.printf("%-20s %-12s %-12s %10s  %s%n",
                "Name", "Start", "End", "Size", "Permissions");
            pw.println("-".repeat(80));
            for (MemoryBlock block : program.getMemory().getBlocks()) {
                String perms = (block.isRead() ? "R" : "-")
                    + (block.isWrite() ? "W" : "-")
                    + (block.isExecute() ? "X" : "-");
                pw.printf("%-20s 0x%-10s 0x%-10s %10d  %s%n",
                    block.getName(),
                    block.getStart(),
                    block.getEnd(),
                    block.getSize(),
                    perms);
            }
        }
        println("Exported memory map to " + path);
    }

    // ========================================================================
    // 2. Vector Table
    // ========================================================================
    private void exportVectorTable(Program program) throws Exception {
        String path = outputDir + "/02_vector_table.txt";
        Memory mem = program.getMemory();
        Address base = program.getMinAddress();

        String[] vectorNames = {
            "Initial SP", "Reset", "NMI", "HardFault",
            "MemManage", "BusFault", "UsageFault", "Reserved7",
            "Reserved8", "Reserved9", "Reserved10", "SVCall",
            "DebugMon", "Reserved13", "PendSV", "SysTick",
            // IRQ0-IRQ79 (typical STM32F4)
        };

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# ARM Cortex-M4 Vector Table (at 0x08010000)");
            pw.println("# Format: offset  address  name");
            pw.println();

            // Read up to 256 vectors (1024 bytes)
            int numVectors = Math.min(256, (int)(mem.getSize() / 4));
            for (int i = 0; i < numVectors; i++) {
                Address addr = base.add(i * 4);
                try {
                    int value = mem.getInt(addr);
                    if (value == 0) {
                        // Skip zero entries but still print first few
                        if (i < 16) {
                            String name = i < vectorNames.length ? vectorNames[i] : "Reserved" + i;
                            pw.printf("[%3d] 0x%08x  0x%08x  %s (unused)%n",
                                i, (int)(addr.getOffset()), value, name);
                        }
                        continue;
                    }
                    String name;
                    if (i < vectorNames.length) {
                        name = vectorNames[i];
                    } else {
                        name = "IRQ" + (i - 16);
                    }
                    // Thumb bit
                    int target = value & ~1;
                    pw.printf("[%3d] 0x%08x  0x%08x  %s  → 0x%08x%s%n",
                        i, (int)(addr.getOffset()), value, name, target,
                        (value & 1) != 0 ? " (Thumb)" : "");
                } catch (Exception e) {
                    break;
                }
            }
        }
        println("Exported vector table to " + path);
    }

    // ========================================================================
    // 3. Function List
    // ========================================================================
    private List<Function> getAllFunctions(Program program) {
        FunctionManager funcMgr = program.getFunctionManager();
        List<Function> funcs = new ArrayList<>();
        FunctionIterator iter = funcMgr.getFunctions(true);
        while (iter.hasNext()) {
            funcs.add(iter.next());
        }
        return funcs;
    }

    private void exportFunctionList(List<Function> allFuncs) throws Exception {
        String path = outputDir + "/03_function_list.txt";

        // Sort by address for the main listing
        List<Function> byAddr = new ArrayList<>(allFuncs);
        byAddr.sort((a, b) -> a.getEntryPoint().compareTo(b.getEntryPoint()));

        // Also create size-sorted version
        List<Function> bySize = new ArrayList<>(allFuncs);
        bySize.sort((a, b) -> Long.compare(b.getBody().getNumAddresses(), a.getBody().getNumAddresses()));

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Function List - ARM Cortex-M4 Inverter Firmware");
            pw.println("# Total functions: " + allFuncs.size());
            pw.println();

            // By address
            pw.println("## Functions by Address");
            pw.printf("%-14s %8s  %-40s %s%n", "Address", "Size", "Name", "Calling Convention");
            pw.println("-".repeat(90));
            for (Function f : byAddr) {
                pw.printf("0x%-12s %8d  %-40s %s%n",
                    f.getEntryPoint(),
                    f.getBody().getNumAddresses(),
                    f.getName(),
                    f.getCallingConventionName());
            }

            pw.println("\n\n## Functions by Size (largest first)");
            pw.printf("%-14s %8s  %s%n", "Address", "Size", "Name");
            pw.println("-".repeat(70));
            for (Function f : bySize) {
                pw.printf("0x%-12s %8d  %s%n",
                    f.getEntryPoint(),
                    f.getBody().getNumAddresses(),
                    f.getName());
            }
        }
        println("Exported " + allFuncs.size() + " functions to " + path);
    }

    // ========================================================================
    // 4. All Strings
    // ========================================================================
    private Map<Address, String> findAllStrings(Program program) {
        Map<Address, String> strings = new LinkedHashMap<>();
        Listing listing = program.getListing();

        // Method 1: Defined string data
        DataIterator dataIter = listing.getDefinedData(true);
        while (dataIter.hasNext()) {
            Data d = dataIter.next();
            String dtName = d.getDataType().getName().toLowerCase();
            if (dtName.contains("string") || dtName.contains("char")
                    || dtName.contains("unicode") || dtName.contains("utf")) {
                Object val = d.getValue();
                if (val != null) {
                    String s = val.toString();
                    if (s.length() >= 2) {
                        strings.put(d.getAddress(), s);
                    }
                }
            }
        }

        // Method 2: Scan memory for ASCII strings (min length 4)
        Memory mem = program.getMemory();
        for (MemoryBlock block : mem.getBlocks()) {
            if (!block.isInitialized()) continue;
            try {
                long size = block.getSize();
                Address start = block.getStart();
                byte[] data = new byte[(int) Math.min(size, 1024 * 1024)]; // Max 1MB per block
                mem.getBytes(start, data);

                int runStart = -1;
                for (int i = 0; i < data.length; i++) {
                    byte b = data[i];
                    if (b >= 0x20 && b < 0x7F) {
                        if (runStart < 0) runStart = i;
                    } else if (b == 0x0A || b == 0x0D || b == 0x09) {
                        // Allow newlines/tabs within strings
                        if (runStart < 0) runStart = i;
                    } else {
                        if (runStart >= 0 && (i - runStart) >= 4) {
                            String s = new String(data, runStart, i - runStart, StandardCharsets.US_ASCII).trim();
                            if (s.length() >= 4) {
                                Address addr = start.add(runStart);
                                if (!strings.containsKey(addr)) {
                                    strings.put(addr, s);
                                }
                            }
                        }
                        runStart = -1;
                    }
                }
                // Handle string at end of block
                if (runStart >= 0 && (data.length - runStart) >= 4) {
                    String s = new String(data, runStart, data.length - runStart, StandardCharsets.US_ASCII).trim();
                    if (s.length() >= 4) {
                        Address addr = start.add(runStart);
                        if (!strings.containsKey(addr)) {
                            strings.put(addr, s);
                        }
                    }
                }
            } catch (Exception e) {
                println("WARNING: Error scanning block " + block.getName() + ": " + e.getMessage());
            }
        }

        return strings;
    }

    private void exportAllStrings(Map<Address, String> allStrings) throws Exception {
        String path = outputDir + "/04_all_strings.txt";
        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# All Strings - ARM Cortex-M4 Inverter Firmware");
            pw.println("# Total: " + allStrings.size());
            pw.println();
            pw.printf("%-14s %6s  %s%n", "Address", "Length", "String");
            pw.println("-".repeat(100));
            for (Map.Entry<Address, String> entry : allStrings.entrySet()) {
                String s = entry.getValue();
                String display = s.length() > 200 ? s.substring(0, 200) + "..." : s;
                display = display.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
                pw.printf("0x%-12s %6d  %s%n",
                    entry.getKey(), s.length(), display);
            }
        }
        println("Exported " + allStrings.size() + " strings to " + path);
    }

    // ========================================================================
    // 5. String Cross-References
    // ========================================================================
    private void exportStringXrefs(Program program, DecompInterface decomp,
                                   Map<Address, String> allStrings) throws Exception {
        String path = outputDir + "/05_string_xrefs.txt";
        ReferenceManager refMgr = program.getReferenceManager();
        FunctionManager funcMgr = program.getFunctionManager();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# String Cross-References");
            pw.println("# Strings referenced by code with function context");
            pw.println();

            int stringsWithRefs = 0;
            for (Map.Entry<Address, String> entry : allStrings.entrySet()) {
                Address addr = entry.getKey();
                String s = entry.getValue();

                List<Reference> refs = new ArrayList<>();
                ReferenceIterator refIter = refMgr.getReferencesTo(addr);
                while (refIter.hasNext()) {
                    refs.add(refIter.next());
                }

                if (refs.isEmpty()) continue;
                stringsWithRefs++;

                String display = s.length() > 120 ? s.substring(0, 120) + "..." : s;
                display = display.replace("\n", "\\n").replace("\r", "\\r");
                pw.printf("\nString @ 0x%s: \"%s\"%n", addr, display);

                for (Reference ref : refs) {
                    Address fromAddr = ref.getFromAddress();
                    Function func = funcMgr.getFunctionContaining(fromAddr);
                    if (func != null) {
                        pw.printf("  ← %s @ 0x%s (ref from 0x%s)%n",
                            func.getName(), func.getEntryPoint(), fromAddr);
                    } else {
                        pw.printf("  ← (no function) ref from 0x%s%n", fromAddr);
                    }
                }
            }
            pw.printf("\n\nTotal strings with references: %d / %d%n", stringsWithRefs, allStrings.size());
        }
        println("Exported string cross-references to " + path);
    }

    // ========================================================================
    // 6. Priority String Analysis
    // ========================================================================
    private void exportPriorityStringAnalysis(Program program, DecompInterface decomp,
                                              Map<Address, String> allStrings) throws Exception {
        String path = outputDir + "/06_priority_strings.txt";
        String decompPath = outputDir + "/06_priority_decompiled.c";
        ReferenceManager refMgr = program.getReferenceManager();
        FunctionManager funcMgr = program.getFunctionManager();

        Set<String> decompiled = new LinkedHashSet<>();
        List<String> decompiledCode = new ArrayList<>();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Priority String Analysis - Known Firmware Markers");
            pw.println("# These strings identify key firmware subsystems");
            pw.println();

            for (String keyword : PRIORITY_STRINGS) {
                pw.println("\n" + "=".repeat(70));
                pw.printf("SEARCHING: \"%s\"%n", keyword);
                pw.println("=".repeat(70));

                boolean found = false;
                for (Map.Entry<Address, String> entry : allStrings.entrySet()) {
                    if (entry.getValue().contains(keyword)) {
                        found = true;
                        Address addr = entry.getKey();
                        pw.printf("\n  Found at 0x%s: \"%s\"%n", addr,
                            entry.getValue().length() > 150
                                ? entry.getValue().substring(0, 150) + "..."
                                : entry.getValue());

                        // Get xrefs
                        ReferenceIterator refIter = refMgr.getReferencesTo(addr);
                        while (refIter.hasNext()) {
                            Reference ref = refIter.next();
                            Address fromAddr = ref.getFromAddress();
                            Function func = funcMgr.getFunctionContaining(fromAddr);
                            if (func != null) {
                                String funcKey = func.getEntryPoint().toString();
                                pw.printf("    ← %s @ 0x%s%n", func.getName(), funcKey);

                                if (!decompiled.contains(funcKey)) {
                                    decompiled.add(funcKey);
                                    DecompileResults result = decomp.decompileFunction(func, 60, monitor);
                                    if (result != null && result.getDecompiledFunction() != null) {
                                        String code = result.getDecompiledFunction().getC();
                                        if (code != null) {
                                            decompiledCode.add(
                                                "// === " + func.getName() + " @ 0x" + funcKey + " ===\n"
                                                + "// References priority string: \"" + keyword + "\"\n\n"
                                                + code + "\n"
                                            );
                                        }
                                    }
                                }
                            } else {
                                pw.printf("    ← (data ref) from 0x%s%n", fromAddr);
                            }
                        }
                    }
                }
                if (!found) {
                    pw.println("  NOT FOUND in defined strings");
                    // Try raw memory scan
                    pw.println("  Scanning raw memory...");
                    Memory mem = program.getMemory();
                    for (MemoryBlock block : mem.getBlocks()) {
                        if (!block.isInitialized()) continue;
                        byte[] searchBytes = keyword.getBytes(StandardCharsets.US_ASCII);
                        Address found2 = mem.findBytes(block.getStart(), block.getEnd(),
                            searchBytes, null, true, monitor);
                        if (found2 != null) {
                            pw.printf("  RAW MATCH at 0x%s in block %s%n", found2, block.getName());
                        }
                    }
                }
            }
        }

        // Write decompiled priority functions
        try (PrintWriter pw = new PrintWriter(new FileWriter(decompPath))) {
            pw.println("// Decompiled functions referencing priority firmware strings");
            pw.println("// ARM Cortex-M4 Inverter Firmware");
            pw.println("// Total: " + decompiledCode.size() + " functions\n");
            for (String code : decompiledCode) {
                pw.println(code);
                pw.println("=" .repeat(80));
                pw.println();
            }
        }
        println("Exported priority string analysis to " + path);
        println("Exported " + decompiledCode.size() + " priority decompiled functions to " + decompPath);
    }

    // ========================================================================
    // 7. Decompile ALL Functions
    // ========================================================================
    private void exportAllDecompiled(Program program, DecompInterface decomp,
                                     List<Function> allFuncs) throws Exception {
        // Sort by address
        List<Function> sorted = new ArrayList<>(allFuncs);
        sorted.sort((a, b) -> a.getEntryPoint().compareTo(b.getEntryPoint()));

        // Split into multiple files to avoid huge single files
        int batchSize = 200;
        int fileNum = 0;
        int totalDecompiled = 0;
        int totalFailed = 0;

        // Also create an index file
        String indexPath = outputDir + "/07_decompiled_index.txt";
        try (PrintWriter indexPw = new PrintWriter(new FileWriter(indexPath))) {
            indexPw.println("# Decompiled Function Index");
            indexPw.println("# Maps function address → file containing decompilation");
            indexPw.println();

            for (int start = 0; start < sorted.size(); start += batchSize) {
                fileNum++;
                int end = Math.min(start + batchSize, sorted.size());
                String filePath = outputDir + String.format("/07_decompiled_%03d.c", fileNum);

                try (PrintWriter pw = new PrintWriter(new FileWriter(filePath))) {
                    pw.printf("// Decompiled functions %d-%d of %d%n", start + 1, end, sorted.size());
                    pw.printf("// ARM Cortex-M4 Inverter Firmware%n%n");

                    for (int i = start; i < end; i++) {
                        Function f = sorted.get(i);
                        String funcAddr = f.getEntryPoint().toString();
                        long funcSize = f.getBody().getNumAddresses();

                        indexPw.printf("0x%-12s  %8d  %-40s  → %s%n",
                            funcAddr, funcSize, f.getName(),
                            new File(filePath).getName());

                        DecompileResults result = decomp.decompileFunction(f, 120, monitor);
                        if (result != null && result.getDecompiledFunction() != null) {
                            String code = result.getDecompiledFunction().getC();
                            if (code != null && !code.isEmpty()) {
                                pw.printf("// === %s @ 0x%s (%d bytes) ===%n%n",
                                    f.getName(), funcAddr, funcSize);
                                pw.println(code);
                                pw.println();
                                pw.println("/" + "/".repeat(79));
                                pw.println();
                                totalDecompiled++;
                            } else {
                                pw.printf("// === %s @ 0x%s (%d bytes) === [EMPTY DECOMPILATION]%n%n",
                                    f.getName(), funcAddr, funcSize);
                                totalFailed++;
                            }
                        } else {
                            String err = result != null ? result.getErrorMessage() : "null result";
                            pw.printf("// === %s @ 0x%s (%d bytes) === [DECOMPILE FAILED: %s]%n%n",
                                f.getName(), funcAddr, funcSize, err);
                            totalFailed++;
                        }
                    }
                }
                println("Wrote " + (end - start) + " functions to " + filePath);
            }
        }
        println("Total decompiled: " + totalDecompiled + " / " + allFuncs.size()
            + " (failed: " + totalFailed + ")");
    }

    // ========================================================================
    // 8. Call Graph
    // ========================================================================
    private void exportCallGraph(Program program, List<Function> allFuncs) throws Exception {
        String path = outputDir + "/08_call_graph.txt";
        FunctionManager funcMgr = program.getFunctionManager();
        ReferenceManager refMgr = program.getReferenceManager();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Call Graph - ARM Cortex-M4 Inverter Firmware");
            pw.println("# Format: function → [callees]  ← [callers]");
            pw.println();

            List<Function> sorted = new ArrayList<>(allFuncs);
            sorted.sort((a, b) -> a.getEntryPoint().compareTo(b.getEntryPoint()));

            for (Function f : sorted) {
                pw.printf("\n0x%s  %s (%d bytes)%n",
                    f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());

                // Callees (functions this function calls)
                Set<Function> called = f.getCalledFunctions(monitor);
                if (!called.isEmpty()) {
                    pw.print("  calls: ");
                    List<String> calleeNames = called.stream()
                        .map(c -> c.getName() + "@0x" + c.getEntryPoint())
                        .sorted()
                        .collect(Collectors.toList());
                    pw.println(String.join(", ", calleeNames));
                }

                // Callers (functions that call this function)
                Set<Function> callers = f.getCallingFunctions(monitor);
                if (!callers.isEmpty()) {
                    pw.print("  called by: ");
                    List<String> callerNames = callers.stream()
                        .map(c -> c.getName() + "@0x" + c.getEntryPoint())
                        .sorted()
                        .collect(Collectors.toList());
                    pw.println(String.join(", ", callerNames));
                }

                if (called.isEmpty() && callers.isEmpty()) {
                    pw.println("  (isolated - no calls in or out)");
                }
            }
        }
        println("Exported call graph to " + path);
    }

    // ========================================================================
    // 9. Data Tables
    // ========================================================================
    private void exportDataTables(Program program) throws Exception {
        String path = outputDir + "/09_data_tables.txt";
        Listing listing = program.getListing();
        Memory mem = program.getMemory();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Data Tables and Constants - ARM Cortex-M4 Inverter Firmware");
            pw.println();

            // 1. All defined data items
            pw.println("## Defined Data Items");
            pw.printf("%-14s %-30s %10s  %s%n", "Address", "Type", "Size", "Value");
            pw.println("-".repeat(90));

            int dataCount = 0;
            DataIterator dataIter = listing.getDefinedData(true);
            while (dataIter.hasNext()) {
                Data d = dataIter.next();
                String dtName = d.getDataType().getName();
                Object val = d.getValue();
                String valStr = val != null ? val.toString() : "(null)";
                if (valStr.length() > 100) valStr = valStr.substring(0, 100) + "...";
                valStr = valStr.replace("\n", "\\n").replace("\r", "\\r");
                pw.printf("0x%-12s %-30s %10d  %s%n",
                    d.getAddress(), dtName, d.getLength(), valStr);
                dataCount++;
            }
            pw.println("\nTotal defined data: " + dataCount);

            // 2. Look for potential jump tables (arrays of addresses in 0x08xxxxxx range)
            pw.println("\n\n## Potential Jump/Function Tables");
            pw.println("(Sequences of 4+ consecutive 32-bit values in 0x08010000-0x0806FFFF range)");
            pw.println();

            for (MemoryBlock block : mem.getBlocks()) {
                if (!block.isInitialized() || block.isExecute()) continue;
                try {
                    long size = block.getSize();
                    Address start = block.getStart();
                    int consecutive = 0;
                    Address tableStart = null;

                    for (long offset = 0; offset + 3 < size; offset += 4) {
                        Address addr = start.add(offset);
                        int value = mem.getInt(addr);
                        // Check if it looks like a code address (0x08010000-0x0806FFFF with Thumb bit)
                        if ((value & 0xFFF00000) == 0x08000000 && (value & 1) == 1) {
                            if (consecutive == 0) tableStart = addr;
                            consecutive++;
                        } else {
                            if (consecutive >= 4 && tableStart != null) {
                                pw.printf("  Table at 0x%s (%d entries):%n", tableStart, consecutive);
                                for (int j = 0; j < consecutive; j++) {
                                    Address tAddr = tableStart.add(j * 4);
                                    int tVal = mem.getInt(tAddr);
                                    pw.printf("    [%d] 0x%08x → 0x%08x%n", j, (int)tAddr.getOffset(), tVal);
                                }
                                pw.println();
                            }
                            consecutive = 0;
                            tableStart = null;
                        }
                    }
                } catch (Exception e) {
                    // Skip inaccessible blocks
                }
            }

            // 3. Look for 16-bit value tables (potential register maps)
            pw.println("\n\n## Potential Register Value Tables");
            pw.println("(Sequences of 16-bit values that could be Modbus register addresses)");
            pw.println();

            for (MemoryBlock block : mem.getBlocks()) {
                if (!block.isInitialized()) continue;
                try {
                    long size = block.getSize();
                    Address start = block.getStart();
                    int regSeq = 0;
                    Address regStart = null;

                    for (long offset = 0; offset + 1 < size; offset += 2) {
                        Address addr = start.add(offset);
                        int value = mem.getShort(addr) & 0xFFFF;
                        // Modbus register addresses typically 0-9999
                        if (value > 0 && value < 10000) {
                            if (regSeq == 0) regStart = addr;
                            regSeq++;
                        } else {
                            if (regSeq >= 8 && regStart != null) {
                                pw.printf("  Potential register table at 0x%s (%d entries):%n",
                                    regStart, regSeq);
                                for (int j = 0; j < Math.min(regSeq, 50); j++) {
                                    Address tAddr = regStart.add(j * 2);
                                    int tVal = mem.getShort(tAddr) & 0xFFFF;
                                    pw.printf("    [%d] 0x%s = %d (0x%04x)%n",
                                        j, tAddr, tVal, tVal);
                                }
                                if (regSeq > 50) pw.println("    ... (" + (regSeq - 50) + " more)");
                                pw.println();
                            }
                            regSeq = 0;
                            regStart = null;
                        }
                    }
                } catch (Exception e) {
                    // Skip
                }
            }
        }
        println("Exported data tables to " + path);
    }

    // ========================================================================
    // 10. Modbus Analysis
    // ========================================================================
    private void exportModbusAnalysis(Program program, DecompInterface decomp,
                                      List<Function> allFuncs) throws Exception {
        String path = outputDir + "/10_modbus_analysis.txt";
        String decompPath = outputDir + "/10_modbus_decompiled.c";

        Set<String> modbusDecompiled = new LinkedHashSet<>();
        List<String> modbusCode = new ArrayList<>();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Modbus Protocol Analysis");
            pw.println("# Functions related to register read/write operations");
            pw.println();

            // Find functions that reference Modbus-like constants
            // FC03 (read holding), FC04 (read input), FC06 (write single), FC16 (write multiple)
            FunctionManager funcMgr = program.getFunctionManager();
            Memory mem = program.getMemory();

            // Search for functions by name patterns
            pw.println("## Functions with Modbus-related names");
            for (Function f : allFuncs) {
                String name = f.getName().toLowerCase();
                if (name.contains("modbus") || name.contains("register")
                        || name.contains("holding") || name.contains("input_reg")
                        || name.contains("read_reg") || name.contains("write_reg")
                        || name.contains("rs485") || name.contains("uart")) {
                    pw.printf("  0x%s  %s (%d bytes)%n",
                        f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());
                    addDecompiled(decomp, f, modbusDecompiled, modbusCode,
                        "Modbus-related name: " + f.getName());
                }
            }

            // Search for Modbus function codes in the code
            pw.println("\n## Functions containing Modbus function code constants");
            pw.println("(Looking for 0x03, 0x04, 0x06, 0x10 in comparison contexts)");
            // This is harder to detect without disassembly analysis, but we can look
            // for functions that reference typical Modbus patterns

            // Look for CRC-related functions (Modbus CRC16)
            pw.println("\n## CRC Functions (potential Modbus CRC16)");
            for (Function f : allFuncs) {
                String name = f.getName().toLowerCase();
                if (name.contains("crc")) {
                    pw.printf("  0x%s  %s (%d bytes)%n",
                        f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());
                    addDecompiled(decomp, f, modbusDecompiled, modbusCode,
                        "CRC function: " + f.getName());
                }
            }

            // Look for functions that are large (protocol handlers tend to be big switch statements)
            pw.println("\n## Large Functions (potential protocol handlers, >500 bytes)");
            List<Function> largeFuncs = allFuncs.stream()
                .filter(f -> f.getBody().getNumAddresses() > 500)
                .sorted((a, b) -> Long.compare(b.getBody().getNumAddresses(), a.getBody().getNumAddresses()))
                .collect(Collectors.toList());
            for (Function f : largeFuncs) {
                pw.printf("  0x%s  %8d bytes  %s%n",
                    f.getEntryPoint(), f.getBody().getNumAddresses(), f.getName());
            }
        }

        // Write Modbus-related decompiled functions
        try (PrintWriter pw = new PrintWriter(new FileWriter(decompPath))) {
            pw.println("// Modbus-related decompiled functions");
            pw.println("// ARM Cortex-M4 Inverter Firmware");
            pw.println("// Total: " + modbusCode.size() + " functions\n");
            for (String code : modbusCode) {
                pw.println(code);
                pw.println("=" .repeat(80));
                pw.println();
            }
        }
        println("Exported Modbus analysis to " + path);
    }

    // ========================================================================
    // 11. Brand/Configuration Analysis
    // ========================================================================
    private void exportBrandAnalysis(Program program, DecompInterface decomp) throws Exception {
        String path = outputDir + "/11_brand_analysis.txt";
        String decompPath = outputDir + "/11_brand_decompiled.c";

        Memory mem = program.getMemory();
        FunctionManager funcMgr = program.getFunctionManager();
        ReferenceManager refMgr = program.getReferenceManager();

        String[] brandStrings = {
            "FreedWON", "HINAESS", "eTower", "EG4-LL", "EG4", "LuxPower",
            "Q3500", "18kPV", "12kPV", "6000XP", "12000XP", "FlexBOSS",
            "GridBOSS",
        };

        Set<String> decompiled = new LinkedHashSet<>();
        List<String> decompiledCode = new ArrayList<>();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Brand and Configuration Analysis");
            pw.println("# Looking for brand selection, model identification, and platform config");
            pw.println();

            // Scan specific address range for brand table (~0x1A500 offset = 0x0802A500)
            long[] scanRanges = {
                0x0802A000L, 0x0802B000L,  // Brand table area
                0x0803C000L, 0x0803D000L,  // Platform config area (Q3500 at ~0x2C08C → 0x0803C08C)
                0x08060000L, 0x08065000L,  // Near end of firmware
            };

            pw.println("## Memory Scan for Brand/Platform Strings");
            for (int r = 0; r < scanRanges.length; r += 2) {
                long startAddr = scanRanges[r];
                long endAddr = scanRanges[r + 1];
                Address start = program.getAddressFactory().getDefaultAddressSpace().getAddress(startAddr);
                Address end = program.getAddressFactory().getDefaultAddressSpace().getAddress(endAddr);

                pw.printf("\n### Region 0x%08x - 0x%08x%n", startAddr, endAddr);
                try {
                    int len = (int)(endAddr - startAddr);
                    byte[] data = new byte[len];
                    mem.getBytes(start, data);

                    // Scan for ASCII strings
                    int runStart = -1;
                    for (int i = 0; i < data.length; i++) {
                        byte b = data[i];
                        if (b >= 0x20 && b < 0x7F) {
                            if (runStart < 0) runStart = i;
                        } else {
                            if (runStart >= 0 && (i - runStart) >= 3) {
                                String s = new String(data, runStart, i - runStart, StandardCharsets.US_ASCII);
                                pw.printf("  0x%08x: \"%s\"%n", startAddr + runStart, s);
                            }
                            runStart = -1;
                        }
                    }
                } catch (Exception e) {
                    pw.println("  (region not accessible: " + e.getMessage() + ")");
                }
            }

            // Search for each brand string and decompile referencing functions
            pw.println("\n\n## Brand String References");
            for (String brand : brandStrings) {
                byte[] searchBytes = brand.getBytes(StandardCharsets.US_ASCII);
                for (MemoryBlock block : mem.getBlocks()) {
                    if (!block.isInitialized()) continue;
                    Address found = mem.findBytes(block.getStart(), block.getEnd(),
                        searchBytes, null, true, monitor);
                    while (found != null) {
                        pw.printf("\n  \"%s\" found at 0x%s%n", brand, found);

                        // Get references to this address
                        ReferenceIterator refIter = refMgr.getReferencesTo(found);
                        while (refIter.hasNext()) {
                            Reference ref = refIter.next();
                            Function func = funcMgr.getFunctionContaining(ref.getFromAddress());
                            if (func != null) {
                                pw.printf("    ← %s @ 0x%s%n", func.getName(), func.getEntryPoint());
                                addDecompiled(decomp, func, decompiled, decompiledCode,
                                    "References brand: \"" + brand + "\"");
                            }
                        }

                        // Continue search after this match
                        Address next = found.add(1);
                        if (next.compareTo(block.getEnd()) >= 0) break;
                        found = mem.findBytes(next, block.getEnd(), searchBytes, null, true, monitor);
                    }
                }
            }
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(decompPath))) {
            pw.println("// Brand/configuration decompiled functions");
            pw.println("// ARM Cortex-M4 Inverter Firmware\n");
            for (String code : decompiledCode) {
                pw.println(code);
                pw.println("=" .repeat(80));
                pw.println();
            }
        }
        println("Exported brand analysis to " + path);
    }

    // ========================================================================
    // 12. UART/Serial Analysis
    // ========================================================================
    private void exportUartAnalysis(Program program, DecompInterface decomp,
                                    List<Function> allFuncs) throws Exception {
        String path = outputDir + "/12_uart_analysis.txt";
        String decompPath = outputDir + "/12_uart_decompiled.c";

        Set<String> decompiled = new LinkedHashSet<>();
        List<String> decompiledCode = new ArrayList<>();

        // STM32F4 UART peripheral base addresses
        long[] uartBases = {
            0x40011000L, // USART1
            0x40004400L, // USART2
            0x40004800L, // USART3
            0x40004C00L, // UART4
            0x40005000L, // UART5
            0x40011400L, // USART6
        };

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# UART/Serial Communication Analysis");
            pw.println("# STM32 UART peripherals and communication functions");
            pw.println();

            // Functions with UART/serial in name
            pw.println("## Functions with UART/serial names");
            for (Function f : allFuncs) {
                String name = f.getName().toLowerCase();
                if (name.contains("uart") || name.contains("serial")
                        || name.contains("usart") || name.contains("rs485")
                        || name.contains("rs232") || name.contains("com_")
                        || name.contains("tx_") || name.contains("rx_")
                        || name.contains("send") || name.contains("recv")
                        || name.contains("transmit") || name.contains("receive")) {
                    pw.printf("  0x%s  %s (%d bytes)%n",
                        f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());
                    addDecompiled(decomp, f, decompiled, decompiledCode,
                        "UART-related: " + f.getName());
                }
            }

            // Look for DMA-related functions
            pw.println("\n## DMA Functions");
            for (Function f : allFuncs) {
                String name = f.getName().toLowerCase();
                if (name.contains("dma")) {
                    pw.printf("  0x%s  %s (%d bytes)%n",
                        f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());
                }
            }

            // Look for interrupt handler functions (often named IRQHandler)
            pw.println("\n## Interrupt Handlers");
            for (Function f : allFuncs) {
                String name = f.getName();
                if (name.contains("IRQ") || name.contains("Handler")
                        || name.contains("_ISR") || name.contains("interrupt")) {
                    pw.printf("  0x%s  %s (%d bytes)%n",
                        f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses());
                }
            }
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(decompPath))) {
            pw.println("// UART/Serial decompiled functions");
            pw.println("// ARM Cortex-M4 Inverter Firmware\n");
            for (String code : decompiledCode) {
                pw.println(code);
                pw.println("=" .repeat(80));
                pw.println();
            }
        }
        println("Exported UART analysis to " + path);
    }

    // ========================================================================
    // 13. Interrupt Handler Analysis
    // ========================================================================
    private void exportInterruptHandlers(Program program, DecompInterface decomp) throws Exception {
        String path = outputDir + "/13_interrupt_handlers.txt";
        Memory mem = program.getMemory();
        FunctionManager funcMgr = program.getFunctionManager();
        Address base = program.getMinAddress();

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# Interrupt Handler Analysis");
            pw.println("# Mapping vector table entries to actual handler functions");
            pw.println();

            // Read vector table entries and map to functions
            for (int i = 0; i < 128; i++) {
                Address vAddr = base.add(i * 4);
                try {
                    int value = mem.getInt(vAddr);
                    if (value == 0) continue;

                    int target = value & ~1;
                    Address targetAddr = program.getAddressFactory()
                        .getDefaultAddressSpace().getAddress(target);
                    Function func = funcMgr.getFunctionAt(targetAddr);

                    String funcName = func != null ? func.getName() : "(no function)";
                    long funcSize = func != null ? func.getBody().getNumAddresses() : 0;

                    String vecName;
                    if (i == 0) vecName = "Initial_SP";
                    else if (i == 1) vecName = "Reset_Handler";
                    else if (i == 2) vecName = "NMI_Handler";
                    else if (i == 3) vecName = "HardFault_Handler";
                    else if (i == 4) vecName = "MemManage_Handler";
                    else if (i == 5) vecName = "BusFault_Handler";
                    else if (i == 6) vecName = "UsageFault_Handler";
                    else if (i == 11) vecName = "SVC_Handler";
                    else if (i == 12) vecName = "DebugMon_Handler";
                    else if (i == 14) vecName = "PendSV_Handler";
                    else if (i == 15) vecName = "SysTick_Handler";
                    else if (i >= 16) vecName = "IRQ" + (i - 16);
                    else vecName = "Reserved_" + i;

                    pw.printf("[%3d] %-25s → 0x%08x  %s (%d bytes)%n",
                        i, vecName, target, funcName, funcSize);
                } catch (Exception e) {
                    break;
                }
            }
        }
        println("Exported interrupt handler analysis to " + path);
    }

    // ========================================================================
    // 14. Summary
    // ========================================================================
    private void exportSummary(Program program, List<Function> allFuncs,
                               Map<Address, String> allStrings) throws Exception {
        String path = outputDir + "/00_analysis_summary.txt";
        FunctionManager funcMgr = program.getFunctionManager();

        // Size distribution
        int tiny = 0, small = 0, medium = 0, large = 0, huge = 0;
        for (Function f : allFuncs) {
            long sz = f.getBody().getNumAddresses();
            if (sz < 20) tiny++;
            else if (sz < 100) small++;
            else if (sz < 500) medium++;
            else if (sz < 2000) large++;
            else huge++;
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# ARM Cortex-M4 Inverter Firmware Analysis Summary");
            pw.println("# " + new Date());
            pw.println();
            pw.println("## Binary Info");
            pw.println("  File: " + program.getName());
            pw.println("  Base: " + program.getMinAddress());
            pw.println("  End:  " + program.getMaxAddress());
            pw.println("  Size: " + program.getMemory().getSize() + " bytes");
            pw.println();
            pw.println("## Function Statistics");
            pw.println("  Total functions: " + allFuncs.size());
            pw.println("  Size distribution:");
            pw.printf("    Tiny   (<20 bytes):   %d%n", tiny);
            pw.printf("    Small  (<100 bytes):  %d%n", small);
            pw.printf("    Medium (<500 bytes):  %d%n", medium);
            pw.printf("    Large  (<2000 bytes): %d%n", large);
            pw.printf("    Huge   (>=2000 bytes):%d%n", huge);
            pw.println();
            pw.println("## String Statistics");
            pw.println("  Total strings found: " + allStrings.size());
            pw.println();
            pw.println("## Output Files");
            pw.println("  00_analysis_summary.txt     - This file");
            pw.println("  01_memory_map.txt           - Memory block layout");
            pw.println("  02_vector_table.txt         - Interrupt vector table");
            pw.println("  03_function_list.txt        - All functions by address and size");
            pw.println("  04_all_strings.txt          - All ASCII strings found");
            pw.println("  05_string_xrefs.txt         - String cross-references");
            pw.println("  06_priority_strings.txt     - Known firmware marker analysis");
            pw.println("  06_priority_decompiled.c    - Decompiled priority-referencing functions");
            pw.println("  07_decompiled_NNN.c         - ALL decompiled functions (batched)");
            pw.println("  07_decompiled_index.txt     - Index mapping functions to files");
            pw.println("  08_call_graph.txt           - Function call relationships");
            pw.println("  09_data_tables.txt          - Data tables, constants, register maps");
            pw.println("  10_modbus_analysis.txt      - Modbus protocol function analysis");
            pw.println("  10_modbus_decompiled.c      - Modbus-related decompiled functions");
            pw.println("  11_brand_analysis.txt       - Brand/configuration table analysis");
            pw.println("  11_brand_decompiled.c       - Brand-related decompiled functions");
            pw.println("  12_uart_analysis.txt        - UART/Serial communication analysis");
            pw.println("  12_uart_decompiled.c        - UART-related decompiled functions");
            pw.println("  13_interrupt_handlers.txt   - Vector table to function mapping");
        }
        println("Exported analysis summary to " + path);
    }

    // ========================================================================
    // Helper: add a decompiled function (dedup by address)
    // ========================================================================
    private void addDecompiled(DecompInterface decomp, Function func,
                               Set<String> seen, List<String> output, String reason) {
        String key = func.getEntryPoint().toString();
        if (seen.contains(key)) return;
        seen.add(key);

        try {
            DecompileResults result = decomp.decompileFunction(func, 60, monitor);
            if (result != null && result.getDecompiledFunction() != null) {
                String code = result.getDecompiledFunction().getC();
                if (code != null && !code.isEmpty()) {
                    output.add(
                        "// === " + func.getName() + " @ 0x" + key
                        + " (" + func.getBody().getNumAddresses() + " bytes) ===\n"
                        + "// " + reason + "\n\n"
                        + code + "\n"
                    );
                }
            }
        } catch (Exception e) {
            // Skip failed decompilations
        }
    }
}
