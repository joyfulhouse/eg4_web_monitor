//@category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class GhidraTransportForward extends GhidraScript {
    private static final String[][] TARGETS = {
        {"4200a8a2", "TransportForward_Cloud"},
        {"4200b6ee", "TransportForward_Local"},
        {"4200935a", "TransportForward_BLE"},
        {"4200a884", "TCPClient_OnConnect"},
        {"4200a506", "TCPClient_HeartbeatTimer"},
    };

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outputPath = args.length > 0 ? args[0] : "/tmp/ghidra_esp32_output/decompiled_transport.c";
        new File(outputPath).getParentFile().mkdirs();
        DecompInterface decomp = new DecompInterface();
        decomp.setOptions(new DecompileOptions());
        decomp.openProgram(currentProgram);
        FunctionManager funcMgr = currentProgram.getFunctionManager();
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        int count = 0;
        try (PrintWriter pw = new PrintWriter(new FileWriter(outputPath))) {
            pw.println("// Transport forward functions decompilation");
            pw.println();
            for (String[] target : TARGETS) {
                Address addr = space.getAddress(Long.parseUnsignedLong(target[0], 16));
                Function func = funcMgr.getFunctionAt(addr);
                if (func == null) { func = funcMgr.getFunctionContaining(addr); }
                if (func == null) {
                    try { disassemble(addr); func = createFunction(addr, target[1]); } catch (Exception e) {}
                }
                if (func == null) { pw.printf("// 0x%s: %s — NOT FOUND%n%n", target[0], target[1]); continue; }
                DecompileResults result = decomp.decompileFunction(func, 60, monitor);
                if (result != null && result.getDecompiledFunction() != null) {
                    String code = result.getDecompiledFunction().getC();
                    if (code != null) {
                        pw.printf("// === 0x%s: %s (%d bytes) ===%n%n", target[0], target[1], func.getBody().getNumAddresses());
                        pw.println(code);
                        pw.println("=" .repeat(80));
                        pw.println();
                        count++;
                    }
                }
            }
            pw.printf("// Total: %d/%d%n", count, TARGETS.length);
        }
        decomp.dispose();
        println("Output: " + outputPath + " (" + count + "/" + TARGETS.length + ")");
    }
}
