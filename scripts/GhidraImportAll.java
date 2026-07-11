// Import additional memory segments (DROM, DRAM, IRAM) into existing project.
//
// Run via:
//   analyzeHeadless /tmp/ghidra_esp32_project esp32_dongle \
//     -process app_code_IROM.bin -noanalysis \
//     -scriptPath /path/to/scripts \
//     -postScript GhidraImportAll.java /path/to/segments_dir
//
//@category Analysis

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;

import java.io.*;

public class GhidraImportAll extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String segDir = args.length > 0 ? args[0] :
            "/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor/scratchpad/firmware/segments";

        Memory memory = currentProgram.getMemory();
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();

        // Segments to add (name, file, base address)
        String[][] segments = {
            {"DROM",  "seg0_DROM_0x3C0E0020.bin", "3c0e0020"},
            {"DRAM",  "seg1_DRAM_0x3FC92600.bin",  "3fc92600"},
            {"IRAM0", "seg2_IRAM_0x40380000.bin",  "40380000"},
            {"IRAM1", "seg4_IRAM_0x403822FC.bin",  "403822fc"},
        };

        for (String[] seg : segments) {
            String name = seg[0];
            File file = new File(segDir, seg[1]);
            long baseAddr = Long.parseUnsignedLong(seg[2], 16);

            if (!file.exists()) {
                println("WARNING: Segment file not found: " + file);
                continue;
            }

            byte[] data = readFileBytes(file);
            Address addr = space.getAddress(baseAddr);

            // Check if block already exists
            MemoryBlock existing = memory.getBlock(addr);
            if (existing != null) {
                println("Block already exists at " + addr + ": " + existing.getName() + " (skipping)");
                continue;
            }

            try {
                MemoryBlock block = memory.createInitializedBlock(
                    name, addr, data.length, (byte) 0, monitor, false);
                block.putBytes(addr, data);

                // Set permissions based on type
                if (name.startsWith("IRAM")) {
                    block.setRead(true);
                    block.setWrite(true);
                    block.setExecute(true);
                } else if (name.equals("DROM")) {
                    block.setRead(true);
                    block.setWrite(false);
                    block.setExecute(false);
                } else { // DRAM
                    block.setRead(true);
                    block.setWrite(true);
                    block.setExecute(false);
                }

                println("Added " + name + " at 0x" + seg[2] + " (" + data.length + " bytes)");
            } catch (Exception e) {
                println("ERROR adding " + name + ": " + e.getMessage());
            }
        }

        println("\nMemory map after import:");
        for (MemoryBlock block : memory.getBlocks()) {
            println("  " + block.getName() + " @ " + block.getStart() +
                    " - " + block.getEnd() + " (" + block.getSize() + " bytes)" +
                    (block.isExecute() ? " [X]" : "") +
                    (block.isWrite() ? " [W]" : "") +
                    (block.isRead() ? " [R]" : ""));
        }
    }

    private byte[] readFileBytes(File file) throws IOException {
        try (FileInputStream fis = new FileInputStream(file)) {
            return fis.readAllBytes();
        }
    }
}
