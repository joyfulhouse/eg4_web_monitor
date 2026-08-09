# Off-Grid Generator Registers — Firmware Proof (input 121–126)

**Question answered:** why does `generator_power` read tens of thousands of watts on an
EG4_OFFGRID inverter with nothing connected to the GEN port?

**Answer:** on the EG4_OFFGRID build, Modbus **input register 123 is not a measurement at all**.
It returns an ARM-local 16-bit counter that increments once per second and wraps at 65536. The
C28x power-conversion DSP never supplies it. Registers 124/125/126 ("generator energy") are
likewise ARM-local status words, not accumulators.

This is proven from the actual firmware the reporting device runs, not inferred from behaviour.
Filed as [#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544); the earlier
[#196](https://github.com/joyfulhouse/eg4_web_monitor/issues/196) sweep measured the 1 Hz rate on
different hardware without identifying the cause.

> **Scope.** Everything below is the **EG4_OFFGRID** family (`SNA_US_12K`, firmware `ceaa-0709`).
> On **EG4_HYBRID** register 123 is genuine — see [Family differential](#8-family-differential).
> Do not generalise either finding to the other family.
>
> **A bogus register here does not make its neighbours bogus.** The follow-up trace in
> [`OFFGRID_EPS_REGISTERS.md`](OFFGRID_EPS_REGISTERS.md) proves that EPS apparent power
> (inputs 25/131/132) on the *same* image is a genuine DSP-sourced measurement — and that the
> legacy EPS S/T voltages (inputs 21/22) are not. Each register needs its own decode.

---

## 1. Firmware analysed

Obtained with the portal download path in
[`FIRMWARE_ACQUISITION.md`](FIRMWARE_ACQUISITION.md) (`firmwareDeviceType=SNA_US_12K`):

| Role | File | recordId | Load base | Addressing | Size |
|------|------|---------:|-----------|-----------|-----:|
| ARM comms | `ceaa-07xx_vE_260214_Br7k5_2.hex` | 224 | `0x08005000` | byte | 238,856 B |
| Inverter DSP (C28x) | `CEAA-xx09_vE_260113.hex` | 225 | `0x80000` | **word** (2 B/addr) | 139,768 B |

Together these are firmware **`ceaa-0709`** (`v1=07` ARM + `v2=09` DSP) — the exact build reported
in #544 on a 12000XP / "SNA-US 15K".

Validation that each image is real code:

- **ARM** — Cortex-M vector table at offset 0: SP `0x2000DFD8`, Reset `0x08030001`,
  NMI `0x0802F39D`, HardFault `0x0802F39F` (all Thumb-odd, in-flash); 229 aligned code pointers,
  2,320 RAM pointers.
- **DSP** — entry words `0048 1098` = `LB 0x081098` (C28x `LB 22bit`); big-endian word counts
  65 `LRETR`, 688 `LRET`, 5,189 `MOVW DP`, against 0 / 40 / 0 for a known-ARM control image.

All addresses below are **ARM byte addresses**; file offset = address − `0x08005000`.

---

## 2. The input-register dispatcher

Modbus function-code 04 resolves a register number through a decrement-and-test chain beginning at
**`0x0801DEEC`**:

```
0x0801DEEC  b538        PUSH  {R3,R4,R5,LR}
0x0801DEEE  0004        MOVS  R4,R0
0x0801DEF0  0020        MOVS  R0,R4
0x0801DEF2  b280        UXTH  R0,R0
0x0801DEF4  2800        CMP   R0,#0
0x0801DEF6  f000 82e0   BEQ.W 0x0801E4BA        ; -> register 0
0x0801DEFA  1e40        SUBS  R0,R0,#1
0x0801DEFC  f000 82e3   BEQ.W 0x0801E4C6        ; -> register 1
             ...
```

Gaps (unimplemented registers) are encoded as a larger decrement — `SUBS R0,R0,#imm3`
(`0x1E80`=2, `0x1EC0`=3, `0x1F00`=4, `0x1F40`=5, `0x1F80`=6) or `SUBS R0,#imm8`
(`0x3811`=17, `0x3813`=19). **Walking the chain while only handling `SUBS #1` silently
mis-numbers every register after the first gap** — see [Pitfalls](#9-pitfalls).

Walked correctly, the contiguous chain yields **166 implemented registers up to 235**, ending at
`0x0801E2D8`.

> **The chain does not end there.** At `0x0801E2D8` it continues with
> `MOVW R1,#0x11D ; SUBS R0,R0,R1`, jumping to a further block of cases (520–598). Full independent
> coverage is **245 cases, highest 598**:
> `0–29, 31–43, 46–77, 79–108, 113, 115–138, 140–153, 170, 174, 193–204, 210–213, 232–235, 520–598`.
> `scripts/walk_input_dispatch.py` stops at the register-relative step and therefore reports only
> the first block — sufficient for everything analysed here (all ≤ 235), but do not read its output
> as the complete register set.

**Independent validation of the walk** (this is what makes the mapping trustworthy): the walk must
mark registers **153** and **170** implemented, because #196 measured both on real off-grid
hardware — `I153 = 1409 W` tracking cloud `acCouplePower`, and `I170 = 3788 W`. Two earlier
buggy walks marked them unimplemented and were discarded. The final walk marks both implemented and
reproduces the handler addresses independently derived by a second reviewer.

Reproduce with `scripts/walk_input_dispatch.py` (see [§11](#11-reproducing-this)).

---

## 3. Where each register actually reads from

Three distinct base pointers, and that separation is the whole finding:

| Base | Nature | Registers |
|------|--------|-----------|
| `0x2000CE5C` | DSP receive-frame block, 16-bit fields | 121, 122, 195, 196 |
| `0x2000D0E4` | DSP power block, 32-bit fields | 17, 27, 153, 170, 197–204 |
| `0x2000D6F0` | **ARM-local block** | **123 only** |

| Reg | Handler | Decoded source | pylxpweb name |
|----:|---------|----------------|---------------|
| 121 | `0x0801E9B8` | `RAM16[0x2000CE5C + 0x28]` = `0x2000CE84` | `generator_voltage` |
| 122 | `0x0801E9C0` | `RAM16[0x2000CE5C + 0x62]` = `0x2000CEBE` | `generator_frequency` |
| **123** | **`0x0801E9CA`** | **`RAM16[0x2000D6F0 + 0x1A]` = `0x2000D70A`** | `generator_power` |
| 124 | `0x0801E9D2` | `(RAM8[0x2000DB49] << 8) \| RAM8[0x2000DB51]` | `generator_energy_today` |
| 125 | `0x0801E9E4` | `low16(RAM32[0x2000D890])` | `generator_energy_total` (low) |
| 126 | `0x0801E9EC` | `high16(RAM32[0x2000D890])` | `generator_energy_total` (high) |
| 153 | `0x0801EADA` | `RAM32[0x2000D0E4 + 0x7C]` = `0x2000D160` | `ac_couple_power` |
| 170 | `0x0801EAE8` | `RAM32[0x2000D0E4 + 0x84]` = `0x2000D168` | `output_power` |
| 195 | `0x0801EB10` | `RAM16[0x2000CE5C + 0x44]` = `0x2000CEA0` | `generator_l1_voltage` |
| 196 | `0x0801EB1A` | `RAM16[0x2000CE5C + 0x46]` = `0x2000CEA2` | `generator_l2_voltage` |
| 197–204 | `0x0801EB24`–`0x0801EB86` | `RAM32[0x2000D0E4 + 0x40…0x5C]` | per-leg inverter/rectifier/grid power |

Register 123 is the **only** member of the generator group that does not read a DSP region.

### Register 123's handler, decoded

```
0x0801E9CA  f8df 0a10   LDR.W R0,=0x2000D6F0     ; literal pool @0x0801F3DC
0x0801E9CE  8b40        LDRH  R0,[R0,#0x1A]      ; -> RAM16[0x2000D70A]
0x0801E9D0  e2bb        B     <common epilogue>
```

`LDR.W` (literal, T2): `Align(PC,4) + imm12` = `0x0801E9CC + 0xA10` = `0x0801F3DC`, which holds
`0x2000D6F0`. `LDRH` T1 `imm5 = 13` → byte offset `26` = `0x1A`. Sum: `0x2000D70A`.

---

## 4. The 1 Hz counter

The identical word is incremented here — same literal, same `#0x1A` offset:

```
0x08018BDA  4857        LDR   R0,=0x2000D6F0     ; literal pool @0x08018D38
0x08018BDC  8b41        LDRH  R1,[R0,#0x1A]
0x08018BDE  1c49        ADDS  R1,R1,#1           ; unconditional — no bound/saturation check
0x08018BE0  8341        STRH  R1,[R0,#0x1A]      ; 16-bit store  -> wraps at 65536
```

`LDRH` zero-extends and `STRH` retains only the low 16 bits, so the `ADDS` result `0x10000` is
truncated to 0 with no comparison or saturation anywhere in the path.

Gated to every second call by a byte counter whose low bit is tested:

```
0x08018BC2  485b        LDR   R0,=<byte counter>
0x08018BC4  7801        LDRB  R1,[R0]
0x08018BC6  1c49        ADDS  R1,R1,#1
0x08018BC8  7001        STRB  R1,[R0]
0x08018BCA  7800        LDRB  R0,[R0]
0x08018BCC  07c0        LSLS  R0,R0,#31          ; isolate bit 0
0x08018BCE  d504        BPL   +8                 ; skip on odd calls
```

Timing chain — **nominally** 1 ms SysTick → scheduler task period 20 → 25 iterations (500 ms) →
every second call, i.e. `1 ms × 20 × 25 × 2 = 1000 ms`. SysTick vector offset `0x3C` → handler
`0x0802F545`; reload programmed from `SystemCoreClock / 1000` (`RVR = quotient − 1`, `CVR = 0`,
`CTRL = 7`) at `0x080326AA`; task descriptor `0x2000D234` receives period `0x14` at `0x0802E30C`;
the task's `0x19`-iteration counter at `0x2000DAC6` calls `0x08018BC0`.

> The nominal period is 1000 ms, but the firmware does not guarantee *exactly* 1.000 Hz — SysTick
> uses integer division of the runtime clock and task dispatch can be delayed. Treat it as a
> nominal 1 Hz tick. Issue #196 measured the realised rate at 0.9996/sec over 460 minutes.

**Writers of `0x2000D70A` — a whole-image audit found exactly two:**

1. the gated increment above, and
2. the initialisation `memset` at `0x08014826`–`0x08014836`, which zeros
   `[0x2000D6F0, 0x2000D70C)` via the routine at `0x08014CAC`.

No DSP receive parser writes it. The nearest aliasing receive path uses base `0x2000D6D0` and is
bounded to a maximum destination of `0x2000D6F1` — below `0x2000D70A`.

**Register 123 on EG4_OFFGRID therefore reports seconds since ARM boot, modulo 65536.**

### Live confirmation from the reported device

The wrap arithmetic fits the reporter's two samples with **zero free parameters**:

```
(5610 − 28646) mod 65536 = 42500 s = 11h 48m 20s
screenshot posted        2026-08-08 08:19:19 EDT
⇒ implied capture time   2026-08-07 20:30:59 EDT
   actual diagnostics log last entry  20:31:32 EDT   →  33 s
```

---

## 5. Registers 124/125/126 are not energy

- **124** — high byte `0x2000DB49` comes from DSP receive-frame page 5; low byte `0x2000DB51` is a
  locally-maintained status bitmask whose bits are set/cleared by ordinary firmware logic
  (e.g. bit 0 at `0x0801CE64`, bit 1 at `0x0801CEAE`, bit 3 at `0x0801CEEC`).
  Reported 179.2 kWh = raw `1792` = `0x0700` → high `0x07`, low `0x00`. The `0x07` equals this
  firmware's own `v1=07`.
- **125/126** — the two halves of status word `RAM32[0x2000D890]`, cleared at init
  (`0x0802E4DE`) and bit-manipulated throughout (bit 0 `0x0801479A`, bit 6 `0x0802E47A`,
  bit 7 `0x080169F2`, bit 14 `0x08018574`, bit 16 `0x0801862A`, bit 29 `0x0801B358`).
  Reported 135,494.5 kWh = `0x0014ACC1`. The low word `0xACC1` was recorded on a **different**
  12000XP in #196 five months earlier — stable status bits, never an accumulator.

---

## 6. "But off-grid inverters have generator legs"

They do, and the firmware **does** instrument them — the generator sensing is real; only the
*power* slot is not:

| Quantity | Register | Source | Reporter's reading (no generator) |
|----------|---------:|--------|-----------------------------------|
| Generator voltage | 121 | DSP frame | 0.0 V ✓ |
| Generator L1 / L2 voltage | 195 / 196 | DSP frame | 0.0 V ✓ |
| Generator frequency | 122 | DSP frame | 0.0 Hz ✓ |
| AC couple power | 153 | DSP power block | 0 W ✓ |
| Output power | 170 | DSP power block | 1106 W ✓ |
| **Generator power** | **123** | **ARM-local counter** | **28,646 W ✗** |
| **Generator energy / lifetime** | **124/125/126** | **ARM-local status** | **179.2 / 135,494.5 kWh ✗** |

Every generator quantity sourced from the DSP reads zero — correct, because no generator is
connected. The **only** non-zero "generator" values are exactly the three that read ARM-local
memory. The firmware's partition and the reported data agree completely.

**Registers 188/189 are confirmed unimplemented** — the dispatcher steps `170 → 174 → 193`
(`SUBS #17` at `0x0801E254`, `SUBS #4` at `0x0801E25A`, `SUBS #19` at `0x0801E260`), so 175–192 are
absent entirely.

The stronger statement — *no* generator-power register anywhere in the off-grid map — is **not
proven**. Establishing it would require identifying the semantics of all 245 handlers and their DSP
producers, which has not been done. What is established is that nothing in the generator group
(121–126, 195/196) carries generator power, and that 123 specifically carries a counter.

The closest engineering candidates for a real substitute are input 17 (`rectifier_power`,
`RAM32[0x2000D120]`) plus input 27 (`power_to_user`, `RAM32[0x2000D118]`) when the AC input is
configured for a generator — but **the physical mux semantics are NOT firmware-proven** and must be
validated against a live generator run before anything is wired up. Do not ship a substitute on
inference.

---

## 7. The 6000XP — matching structure, increment site NOT located

`INVERTER_FAMILY_EG4_OFFGRID` covers the 6000XP as well as the 12000XP, so the gate's scope was
checked against the 6000XP ARM image (`SNA_US_6000`, `ccaa-xx15xx_260519`, base `0x08005000`; its
dispatcher entry is `0x08030B78`, not the 12000XP's address). Every claim below is from that image.

**The same three-base structure holds**, which is the load-bearing observation:

| Reg | 6000XP source | Nature of the base |
|----:|---------------|--------------------|
| 121 | `RAM16[0x20009FC4 + 0x28]` = `0x20009FEC` | DSP receive-frame block |
| 122 | `RAM16[0x20009FC4 + 0x50]` = `0x2000A014` | same DSP frame block |
| **123** | **`RAM16[0x2000A708 + 0x0E]` = `0x2000A716`** | **separate, non-DSP base** |
| 124 | `(RAM8[0x2000AAC1] << 8) \| RAM8[0x2000AAF3]` | byte-assembled, as on the 12000XP |
| 125/126 | halves of `RAM32[0x2000A7F8]` | one 32-bit word, as on the 12000XP |
| 153 | `RAM32[0x2000A084 + 0x78]` | DSP power block |
| 170 | `RAM32[0x2000A084 + 0x80]` | DSP power block |

**And the base register 123 reads is demonstrably a timer struct.** Two counters were decoded in
it at neighbouring offsets:

```
0x080146CA  LDR   R3,=0x2000A708
            LDRH  R0,[R3,#0x0C]
            CMP.W R0,#0xE10        ; 3600 — seconds in an hour
            BGE   +4
            LDRH  R0,[R3,#0x0C]
            ADDS  R0,R0,#1
            STRH  R0,[R3,#0x0C]

0x08011DEA  LDR   R0,=0x2000A708
            LDRH  R1,[R0,#0x10]
            MOVW  R2,#0xFFFF       ; saturating counter
            CMP   R1,R2
            ...    ADDS R1,R1,#1
```

**What is NOT established:** no writer for `+0x0E` itself was found. The pattern search covered
`LDR literal → LDRH/ADDS/STRH` at that offset and every one of the 8 literal pools holding
`0x2000A708`; the increment may use a different base register or a path not matched. So the 6000XP
is **structurally consistent with the 12000XP defect but not independently proven**.

The gate is applied family-wide anyway, on this reasoning: register 123 does not read either DSP
block on the 6000XP, and the base it does read holds nothing but time counters — so it is very
unlikely to be generator power, while leaving a bogus watt reading in place is the harm actually
being reported. **If a 6000XP owner reports a plausible Generator Power reading, treat that as
falsifying evidence and narrow the gate to the 12000XP.** The repo's own #490 lesson is that
behaviour can split *within* a family; this is the one inference in this document.

Reproduce:

```bash
uv run python scripts/download_inverter_firmware.py --device-type SNA_US_6000 --out-dir /tmp/fw6000
uv run python scripts/walk_input_dispatch.py /tmp/fw6000/ccaa-xx15xx_260519.bin \
    --base 0x8005000 --start 0x08030B78 --registers 121,122,123,124,125,126,153,170
```

## 8. Family differential

| | EG4_OFFGRID (`ceaa-0709`) | EG4_HYBRID (`FAAB-2727`) |
|---|---|---|
| Register 123 | `RAM16[0x2000D70A]` — ARM-local 1 Hz counter | `low16(int16[0x2000EAE4] − int16[0x2000EAE6])` — both DSP-fed |
| Verdict | not a measurement | genuine power |

On the maintainer's own FlexBOSS21 + 18kPV, register 123 tracks real power and the two inverters'
values sum to the GridBOSS AC-Couple-1 total within 0.13%. **Any fix must be family-gated**;
suppressing register 123 globally would break working hybrid installs.

---

## 9. Pitfalls

1. **Dispatcher gaps.** Handle every `SUBS R0,R0,#imm3` / `SUBS R0,#imm8`, not just `#1`, or the
   register numbering drifts silently. Validate any walk by requiring registers 153 and 170 to
   come out implemented.
2. **Don't trust a single decode.** Two independent walks here disagreed with each other before the
   bug was found; both were wrong. The mapping was only accepted once a corrected walk and a second
   reviewer produced identical handler addresses *and* the walk passed the #196 hardware check.
3. **radare2's `tms320` plugin is c54x/c55x/c64x** and mis-decodes C28x. Ghidra has no stock C28x
   module. See [`FIRMWARE_ACQUISITION.md`](FIRMWARE_ACQUISITION.md).
4. **The committed `re/` artifacts are invalid** — see the correction banner in
   [`FIRMWARE_BINARY_ANALYSIS.md`](FIRMWARE_BINARY_ANALYSIS.md).

---

## 10. Corroboration

Every claim here was decoded twice — once by hand from the bytes, once by an independent reviewer
instructed to *refute* rather than confirm. Verdicts:

| Claim | Verdict |
|-------|---------|
| Reg 123 handler `0x0801E9CA` → `RAM16[0x2000D70A]`, **and** the dispatch genuinely reaches it for register 123 | **CONFIRMED** (independent cumulative decode: `SUBS` at `0x0801E1A0` brings the case number to 123; the following `BEQ.W` offset `0x824` from PC `0x0801E1A6` lands on `0x0801E9CA`) |
| `RAM16[0x2000D70A]` incremented, 16-bit, wraps at 65536 | **CONFIRMED** — but the write-up's instruction addresses were **2 bytes too high** and have been corrected |
| "Exactly 1.000 Hz" and "the increment is the only writer" | **REFUTED** — nominal 1000 ms, not exact; the init `memset` is a second writer. Both corrected above |
| No DSP path writes `0x2000D70A` | **CONFIRMED** (whole-image writer audit; nearest aliasing receive path is bounded to `0x2000D6F1`) |
| Regs 121/122 are genuine DSP-frame fields | **CONFIRMED** (parser stores `STRH R0,[R6,#0x28]` at `0x08025CFE` and `STRH.W R0,[R6,#0x62]` at `0x08025D0E`, with `R6 = 0x2000CE5C`) |
| Reg 124 = byte-assembled status, not energy | **CONFIRMED** (`ORRS.W R0,R0,R1,LSL #8`; low byte bit-manipulated at `0x0801CE6A`, `0x0801CEAE`, `0x0801CEEC`, …) |
| Regs 125/126 = halves of status word `0x2000D890` | **CONFIRMED** (bit writers at `0x0801479E`, `0x08018578`, `0x0801862E`, `0x0803463A`, …) |
| Reg 188/189 unimplemented | **CONFIRMED** |
| "No generator-power register anywhere" | **UNPROVEN** — narrowed accordingly in §6 |
| Hybrid 123 = `int16[0x2000EAE4] − int16[0x2000EAE6]`, both DSP-fed | **CONFIRMED** (`0x080319DC`–`0x08031A0E` in a correctly reconstructed hybrid image; operands stored from the UART receive buffer at `0x0804D2FE` and `0x0804D51A`) |

Three earlier attempts at the dispatch walk were wrong and were discarded — two of mine (which
mis-numbered registers by mishandling `SUBS #imm3` gaps, and failed the #196 sanity check) and one
address error propagated into an early draft. **Nothing in this document should be extended without
re-running both a hand decode and an adversarial second pass.**

## 11. Reproducing this

```bash
# 1. download the off-grid pair (see FIRMWARE_ACQUISITION.md)
uv run python scripts/download_inverter_firmware.py --device-type SNA_US_12K --out-dir /tmp/fw

# 2. walk the FC04 dispatcher and dump the register -> handler -> RAM map
uv run python scripts/walk_input_dispatch.py \
    /tmp/fw/ceaa-07xx_vE_260214_Br7k5_2.bin --base 0x08005000 --start 0x0801DEEC
```

Both scripts are read-only and require no vendor tooling.
