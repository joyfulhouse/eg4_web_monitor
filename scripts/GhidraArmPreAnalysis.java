// Pre-analysis script for ARM Cortex-M4 inverter firmware.
// Aggressively finds and creates functions by:
// 1. Setting memory as executable
// 2. Finding Thumb function prologues (PUSH {r4-r7, lr} patterns)
// 3. Disassembling at each prologue
// 4. Creating functions
//
//@category Analysis

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.SourceType;

import java.util.*;

public class GhidraArmPreAnalysis extends GhidraScript {

    @Override
    public void run() throws Exception {
        Program program = currentProgram;
        Memory mem = program.getMemory();
        AddressSpace space = program.getAddressFactory().getDefaultAddressSpace();
        FunctionManager funcMgr = program.getFunctionManager();

        println("=== ARM Cortex-M4 Pre-Analysis ===");

        // Step 1: Set all memory blocks as executable (critical for raw binary)
        println("Step 1: Setting memory blocks as executable...");
        for (MemoryBlock block : mem.getBlocks()) {
            block.setExecute(true);
            block.setRead(true);
            println("  " + block.getName() + " @ " + block.getStart()
                + " - " + block.getEnd() + " set RX");
        }

        // Step 2: Scan for Thumb function prologues
        // Common ARM Thumb-2 function prologues:
        // PUSH {r3, lr}       = 0xB508
        // PUSH {r4, lr}       = 0xB510
        // PUSH {r4, r5, lr}   = 0xB530
        // PUSH {r4-r6, lr}    = 0xB570
        // PUSH {r4-r7, lr}    = 0xB5F0
        // PUSH {r3-r7, lr}    = 0xB5F8
        // PUSH.W {r3-r11, lr} = 0xE92D 0x4FF8 (32-bit)
        // PUSH.W {r4-r11, lr} = 0xE92D 0x4FF0 (32-bit)
        // Also: STM/STMDB patterns and MOV r12, sp patterns

        println("Step 2: Scanning for Thumb function prologues...");
        Address start = program.getMinAddress();
        Address end = program.getMaxAddress();
        long size = end.getOffset() - start.getOffset();

        byte[] allBytes = new byte[(int) Math.min(size, 512 * 1024)];
        mem.getBytes(start, allBytes);

        List<Long> prologueAddrs = new ArrayList<>();

        // Scan 16-bit aligned addresses
        for (int i = 0; i < allBytes.length - 1; i += 2) {
            int hw = (allBytes[i] & 0xFF) | ((allBytes[i + 1] & 0xFF) << 8);

            // Match PUSH {reglist, lr} patterns (0xB5xx where bit 8 is LR)
            if ((hw & 0xFF00) == 0xB500) {
                // PUSH with lr — very likely a function entry
                long addr = start.getOffset() + i;
                prologueAddrs.add(addr);
                continue;
            }

            // Match 32-bit PUSH.W {reglist} = 0xE92D xxxx
            if (hw == 0xE92D && i + 3 < allBytes.length) {
                int hw2 = (allBytes[i + 2] & 0xFF) | ((allBytes[i + 3] & 0xFF) << 8);
                // Check if LR is in the register list (bit 14)
                if ((hw2 & 0x4000) != 0) {
                    long addr = start.getOffset() + i;
                    prologueAddrs.add(addr);
                }
                continue;
            }

            // Match MOVS r0, #0 / BX lr (leaf function return, preceding entry)
            // Skip — these are exits not entries

            // Match SUB sp, sp, #imm (0xB0xx where bit 7 is set)
            // These can be function entries in optimized code
        }

        println("  Found " + prologueAddrs.size() + " potential function prologues");

        // Step 3: Also extract addresses from the header table (0x08010000 - 0x0801014F)
        // These look like they might be scrambled addresses. Try different byte orderings.
        println("Step 3: Analyzing header table...");
        List<Long> headerAddrs = new ArrayList<>();

        // The first 0x150 bytes contain a table. Try treating each 4-byte entry
        // as bytes [B0 B1 B2 B3] and check if rearranging gives valid flash addresses.
        for (int i = 0; i < Math.min(0x150, allBytes.length); i += 4) {
            int b0 = allBytes[i] & 0xFF;
            int b1 = allBytes[i + 1] & 0xFF;
            int b2 = allBytes[i + 2] & 0xFF;
            int b3 = allBytes[i + 3] & 0xFF;

            // Standard LE: b0 | b1<<8 | b2<<16 | b3<<24
            long le = b0 | (b1 << 8) | (b2 << 16) | ((long)b3 << 24);
            // Standard BE: b3 | b2<<8 | b1<<16 | b0<<24
            long be = b3 | (b2 << 8) | (b1 << 16) | ((long)b0 << 24);
            // Half-word swapped LE: b2 | b3<<8 | b0<<16 | b1<<24
            long hwsle = b2 | (b3 << 8) | (b0 << 16) | ((long)b1 << 24);
            // Half-word swapped BE: b1 | b0<<8 | b3<<16 | b2<<24
            long hwsbe = b1 | (b0 << 8) | (b3 << 16) | ((long)b2 << 24);

            long baseMin = 0x08010000L;
            long baseMax = 0x08070000L;

            // Check each interpretation
            for (long val : new long[]{le, be, hwsle, hwsbe}) {
                long target = val & ~1L; // Clear Thumb bit
                if (target >= baseMin && target < baseMax) {
                    headerAddrs.add(target | 1L); // Keep as Thumb
                }
            }
        }
        println("  Found " + headerAddrs.size() + " potential addresses from header table");

        // Step 4: Disassemble at all found locations
        println("Step 4: Disassembling at " + prologueAddrs.size() + " prologue locations...");
        int disasmCount = 0;
        int funcCount = 0;

        // Sort and deduplicate
        Set<Long> allEntries = new TreeSet<>();
        allEntries.addAll(prologueAddrs);
        allEntries.addAll(headerAddrs);

        for (long addrVal : allEntries) {
            Address addr = space.getAddress(addrVal);

            // Skip if already disassembled
            Instruction existing = program.getListing().getInstructionAt(addr);
            if (existing != null) continue;

            // Skip if it's in defined data
            Data existingData = program.getListing().getDefinedDataAt(addr);
            if (existingData != null) continue;

            try {
                disassemble(addr);
                disasmCount++;

                // Try to create a function here
                Function existingFunc = funcMgr.getFunctionAt(addr);
                if (existingFunc == null) {
                    Function func = createFunction(addr, null);
                    if (func != null) {
                        funcCount++;
                    }
                }
            } catch (Exception e) {
                // Skip invalid locations silently
            }
        }

        println("  Disassembled at " + disasmCount + " new locations");
        println("  Created " + funcCount + " new functions");

        // Step 5: Let Ghidra's auto-analysis find more through flow analysis
        // The -postScript will run after this -preScript and the re-analysis
        println("Step 5: Auto-analysis will now propagate from discovered code...");

        // Count total functions now
        int total = 0;
        FunctionIterator iter = funcMgr.getFunctions(true);
        while (iter.hasNext()) {
            iter.next();
            total++;
        }
        println("Total functions after pre-analysis: " + total);
        println("=== Pre-Analysis Complete ===");
    }
}
