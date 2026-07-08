// Ghidra headless post-analysis script (Java) to extract decompiled functions and string xrefs.
//
// Run via:
//   analyzeHeadless /tmp/ghidra_esp32_project esp32_dongle \
//     -process app_code_IROM.bin -noanalysis \
//     -scriptPath /path/to/scripts \
//     -postScript GhidraExtract.java /path/to/output_dir
//
//@category Analysis

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;

import java.io.*;
import java.util.*;
import java.util.stream.*;

public class GhidraExtract extends GhidraScript {

    private static final String[] PROTOCOL_KEYWORDS = {
        "FUNC_CODE", "DATA_TRANSMISSION", "GET_PARAM", "SET_PARAM",
        "HEARBEAT", "HEARTBEAT", "rs485", "RS485",
        "tcp_client", "tcp_server", "modbus", "register",
        "inverter", "battery", "soc", "hido-iot",
        "solarcloudsystem", "luxpower", "wifi_config", "ble_",
        "uart", "serial_port", "crc", "encrypt", "decrypt",
        "firmware", "ota_", "update", "dongle",
        "charge", "discharge", "grid", "pv_", "solar",
        "mqtt", "http", "json", "parse",
        "cmd", "command", "packet", "frame", "protocol",
    };

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outputDir = args.length > 0 ? args[0] : "/tmp/ghidra_esp32_output";
        new File(outputDir).mkdirs();

        Program program = currentProgram;
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.openProgram(program);

        println("\n=== Ghidra ESP32-C3 Firmware Analysis ===\n");

        // 1. Export all functions sorted by size
        exportAllFunctions(program, outputDir);

        // 2. Find protocol strings and decompile referencing functions
        exportStringXrefs(program, decomp, outputDir);

        // 3. Decompile the 50 largest functions
        exportLargeFunctions(program, decomp, outputDir, 50);

        println("\n=== Analysis complete. Output in: " + outputDir + " ===");
        decomp.dispose();
    }

    private void exportAllFunctions(Program program, String outputDir) throws Exception {
        FunctionManager funcMgr = program.getFunctionManager();
        List<Function> funcs = new ArrayList<>();
        FunctionIterator iter = funcMgr.getFunctions(true);
        while (iter.hasNext()) {
            funcs.add(iter.next());
        }
        // Sort by size descending
        funcs.sort((a, b) -> Long.compare(b.getBody().getNumAddresses(), a.getBody().getNumAddresses()));

        String path = outputDir + "/function_list.txt";
        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("# All functions sorted by size (largest first)");
            pw.println("# Address      |    Size | Name");
            pw.println("-".repeat(70));
            for (Function f : funcs) {
                pw.printf("0x%-12s %8d  %s%n",
                    f.getEntryPoint().toString(),
                    f.getBody().getNumAddresses(),
                    f.getName());
            }
            pw.println("\nTotal functions: " + funcs.size());
        }
        println("Exported " + funcs.size() + " functions to " + path);
    }

    private void exportStringXrefs(Program program, DecompInterface decomp, String outputDir) throws Exception {
        Listing listing = program.getListing();
        ReferenceManager refMgr = program.getReferenceManager();
        FunctionManager funcMgr = program.getFunctionManager();

        // Find all defined strings matching keywords
        Map<Address, String> matchingStrings = new LinkedHashMap<>();
        DataIterator dataIter = listing.getDefinedData(true);
        while (dataIter.hasNext()) {
            Data d = dataIter.next();
            String dtName = d.getDataType().getName().toLowerCase();
            if (dtName.contains("string") || dtName.contains("char")) {
                Object val = d.getValue();
                if (val != null) {
                    String s = val.toString();
                    for (String kw : PROTOCOL_KEYWORDS) {
                        if (s.toLowerCase().contains(kw.toLowerCase())) {
                            matchingStrings.put(d.getAddress(), s);
                            break;
                        }
                    }
                }
            }
        }
        println("Found " + matchingStrings.size() + " matching strings");

        String xrefPath = outputDir + "/string_xrefs.txt";
        String decompPath = outputDir + "/decompiled_protocol.c";

        Set<String> seenFuncs = new HashSet<>();
        List<String> decompiled = new ArrayList<>();

        try (PrintWriter xrefPw = new PrintWriter(new FileWriter(xrefPath))) {
            xrefPw.println("# String cross-references for protocol analysis");
            xrefPw.println("# Keywords: " + String.join(", ", PROTOCOL_KEYWORDS));
            xrefPw.println();

            for (Map.Entry<Address, String> entry : matchingStrings.entrySet()) {
                Address addr = entry.getKey();
                String s = entry.getValue();
                String truncated = s.length() > 200 ? s.substring(0, 200) + "..." : s;
                xrefPw.println("\n--- String at " + addr + ": \"" + truncated + "\"");

                List<Reference> refs = new ArrayList<>();
                ReferenceIterator refIter = refMgr.getReferencesTo(addr);
                while (refIter.hasNext()) {
                    refs.add(refIter.next());
                }
                if (refs.isEmpty()) {
                    xrefPw.println("  (no references found)");
                    continue;
                }

                for (Reference ref : refs) {
                    Address fromAddr = ref.getFromAddress();
                    Function func = funcMgr.getFunctionContaining(fromAddr);
                    if (func != null) {
                        String funcName = func.getName();
                        String funcAddr = func.getEntryPoint().toString();
                        xrefPw.println("  Referenced by: " + funcName + " @ " + funcAddr);

                        if (!seenFuncs.contains(funcAddr)) {
                            seenFuncs.add(funcAddr);
                            DecompileResults result = decomp.decompileFunction(func, 30, monitor);
                            if (result != null && result.getDecompiledFunction() != null) {
                                String code = result.getDecompiledFunction().getC();
                                if (code != null) {
                                    String label = s.length() > 100 ? s.substring(0, 100) + "..." : s;
                                    decompiled.add(
                                        "// === " + funcName + " @ " + funcAddr + " ===\n" +
                                        "// Referenced string: \"" + label + "\"\n\n" +
                                        code + "\n"
                                    );
                                }
                            }
                        }
                    } else {
                        xrefPw.println("  Referenced from: " + fromAddr + " (not in a function)");
                    }
                }
            }
        }

        try (PrintWriter pw = new PrintWriter(new FileWriter(decompPath))) {
            pw.println("// Decompiled protocol-related functions from ESP32-C3 dongle firmware");
            pw.println("// Generated by Ghidra headless analysis");
            pw.println("// Total protocol functions: " + decompiled.size());
            pw.println();
            for (String code : decompiled) {
                pw.println(code);
                pw.println("=".repeat(80));
                pw.println();
            }
        }
        println("Exported " + decompiled.size() + " decompiled protocol functions to " + decompPath);
    }

    private void exportLargeFunctions(Program program, DecompInterface decomp, String outputDir, int topN) throws Exception {
        FunctionManager funcMgr = program.getFunctionManager();
        List<Function> funcs = new ArrayList<>();
        FunctionIterator iter = funcMgr.getFunctions(true);
        while (iter.hasNext()) {
            funcs.add(iter.next());
        }
        funcs.sort((a, b) -> Long.compare(b.getBody().getNumAddresses(), a.getBody().getNumAddresses()));

        String path = outputDir + "/decompiled_large.c";
        int count = 0;
        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("// Top " + topN + " largest functions decompiled from ESP32-C3 dongle firmware");
            pw.println();
            for (int i = 0; i < Math.min(topN, funcs.size()); i++) {
                Function f = funcs.get(i);
                DecompileResults result = decomp.decompileFunction(f, 30, monitor);
                if (result != null && result.getDecompiledFunction() != null) {
                    String code = result.getDecompiledFunction().getC();
                    if (code != null) {
                        pw.printf("// === %s @ %s (%d bytes) ===%n%n%s%n",
                            f.getName(), f.getEntryPoint(),
                            f.getBody().getNumAddresses(), code);
                        pw.println("=".repeat(80));
                        pw.println();
                        count++;
                    }
                }
            }
        }
        println("Exported " + count + " large functions to " + path);
    }
}
