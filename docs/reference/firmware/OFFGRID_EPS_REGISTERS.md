# Off-Grid EPS Registers — What Input 25 / 131 / 132 Actually Are

**Question** (issue [#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544) follow-up):
after input register 123 turned out to be an ARM-local counter rather than generator power, is
**EPS apparent power (VA)** genuine on the same platform, or another repurposed slot?

**Answer: genuine.** Inputs 25, 131 and 132 are measured values that originate on the C28x DSP,
arrive over the inter-processor link, are filtered, and are published into the same struct that
feeds the already-proven active-power registers. They are *not* counters, constants, duplicates or
aliases.

> **Scope: this document is about the off-grid image only.** The identically-numbered registers mean
> different things on EG4_HYBRID — there, 25 is an ARM-computed `V × I ÷ 100` estimate, 131 is a
> sign-split directional power, and **132 is an incrementing counter**. See
> [`HYBRID_EPS_REGISTERS.md`](HYBRID_EPS_REGISTERS.md). Do not carry conclusions across families.

A second, unrelated finding fell out of the same trace: **inputs 21 and 22 — the legacy EPS
*S-phase* and *T-phase* voltages — are not voltages at all** on this build. See §5.

Companion documents: [`OFFGRID_GENERATOR_REGISTERS.md`](OFFGRID_GENERATOR_REGISTERS.md) for the
register-123 proof and the three-base structural argument; [`FIRMWARE_ACQUISITION.md`](FIRMWARE_ACQUISITION.md)
for how to obtain and decode an image, and for the method rules every claim here follows.

---

## 1. Firmware analysed

| | |
|---|---|
| Image | `ceaa-07xx_vE_260214_Br7k5_2` — ARM comms processor, 12000XP / `SNA_US_12K` |
| Reported as | `ceaa-0709` (the `09` half is the separate C28x image) |
| Size | 238,856 bytes |
| SHA-256 | `d46f8b0c051e78c7e85adf2d4683dedae6489016cd563759d5edd2a487818624` |
| Load base | `0x08005000` |
| FC04 dispatcher | `0x0801DEEC` |

---

## 2. The six handlers

All six resolve the **same** literal pool slot `0x0801EF50`, whose bytes are `e4 d0 00 20` =
`0x2000D0E4` — the DSP power block, the same base as the hardware-measured registers 153
(`ac_couple_power`) and 170 (`output_power`), and a different base from register 123's ARM-local
counter.

| Reg | pylxpweb name | Handler | Decoded source | Unit conversion |
|----:|---------------|---------|----------------|-----------------|
| 24 | `eps_power` | `0x0801E624` | `RAM32[0x2000D0E4 + 0x60]` = `0x2000D144` | `UDIV` by 10 |
| **25** | **`eps_apparent_power`** | **`0x0801E634`** | **`RAM16[0x2000D0E4 + 0x88]` = `0x2000D16C`** | **none** |
| 129 | `eps_l1_power` | `0x0801EA06` | `RAM32[0x2000D0E4 + 0x64]` = `0x2000D148` | `UDIV` by 10 |
| 130 | `eps_l2_power` | `0x0801EA14` | `RAM32[0x2000D0E4 + 0x68]` = `0x2000D14C` | `UDIV` by 10 |
| **131** | **`eps_l1_apparent_power`** | **`0x0801EA22`** | **`RAM16[0x2000D0E4 + 0x8A]` = `0x2000D16E`** | **none** |
| **132** | **`eps_l2_apparent_power`** | **`0x0801EA2C`** | **`RAM16[0x2000D0E4 + 0x8C]` = `0x2000D170`** | **none** |

```
; register 25 — EPS apparent power
0801E634  df f8 18 09   LDR.W  R0,[PC,#0x918]   ; Align(0x0801E638,4)+0x918 = 0x0801EF50 -> 0x2000D0E4
0801E638  b0 f8 88 00   LDRH.W R0,[R0,#0x88]    ; -> RAM16[0x2000D16C]
0801E63C  00 f0 85 bc   B.W    0x0801EF4A       ; common epilogue: UXTH R0,R0

; register 24 — EPS active power, for contrast
0801E624  df f8 28 09   LDR.W  R0,[PC,#0x928]   ; same pool slot -> 0x2000D0E4
0801E628  00 6e         LDR    R0,[R0,#0x60]    ; -> RAM32[0x2000D144]
0801E62A  0a 21         MOVS   R1,#10
0801E62C  b0 fb f1 f0   UDIV   R0,R0,R1
```

The three apparent-power fields are **contiguous 16-bit slots** at `+0x88`, `+0x8A`, `+0x8C`
(total, L1, L2) — a deliberate layout, read with plain `LDRH.W`. No byte-gluing, no bitfield
masking, no shared address. Compare register 123's `RAM16[0x2000D6F0 + 0x1A]`, or registers 21/22
in §5, where exactly those tell-tale shapes *do* appear.

### The scaling asymmetry is real, and it is the firmware's own

Active power is held internally in **deciwatts** and divided by 10 at the register boundary.
Apparent power is held in **whole VA** and is not divided. That is not an inference — the firmware
normalises in the opposite direction when it builds its own outbound report frame at `0x0800E3E6`,
multiplying each apparent value by 10 to match the active-power scale:

```
0800E3E6  df f8 3c 23   LDR.W R2,[0x0800E724]      ; = 0x2000D0E4
0800E3EA  13 6e         LDR   R3,[R2,#0x60]        ; P total  (deciwatts)
0800E3EC  0b 64         STR   R3,[R1,#0x40]
0800E3EE  02 f1 88 03   ADD.W R3,R2,#0x88          ; &S total
0800E3F2  1c 88         LDRH  R4,[R3]              ; S total  (VA)
0800E3F4  04 eb 84 05   ADD.W R5,R4,R4,LSL #2      ; R5 = S*5
0800E3F8  6d 00         LSLS  R5,R5,#1             ; R5 = S*10  -> same deci-scale as P
0800E3FA  0d 65         STR   R5,[R1,#0x50]
0800E3FC  54 6e         LDR   R4,[R2,#0x64]        ; P L1
0800E400  5d 88         LDRH  R5,[R3,#2]           ; S L1  -> also *10
0800E40A  91 6e         LDR   R1,[R2,#0x68]        ; P L2
0800E40E  9a 88         LDRH  R2,[R3,#4]           ; S L2  -> also *10
```

Three P/S pairs, total / L1 / L2, interleaved. The firmware itself treats `+0x88`/`+0x8A`/`+0x8C`
as apparent power paired one-to-one with the active powers at `+0x60`/`+0x64`/`+0x68`.
`LDRH` zero-extends, so the values are unsigned — correct for apparent power, and 16 bits caps at
65,535 VA, far above a 12 kW unit's range.

pylxpweb's map (`unit="VA"`, no scale factor) matches this exactly.

---

## 3. Provenance — the full chain from DSP to Modbus

The decisive question is not "what address does the handler read" but "who writes it". For these
six fields the chain is complete:

```
C28x DSP
   │  inter-processor frame (CRC checked at 0x080275AE, dispatched via 0x0802677A)
   ▼
frame parser  0x08025AB8        R6 = 0x2000CE5C (receive block)
   │  page 3  (CMP R0,#3 @ 0x08025D5E)   0x08025D74  STRH.W R0,[R6,#0x9C]   raw S total
   │  page 12 (CMP R0,#12 @ 0x080265C6)  0x080265D6  STRH.W R0,[R6,#0xA0]   raw S L1
   │                                     0x080265E8  STRH.W R0,[R6,#0xA2]   raw S L2
   ▼
filter / convert  0x08018D44     R7 = 0x2000CE5C (loaded @0x08018DAE)
   │                             R6 = 0x2000D0E4 (loaded @0x08018D8C)
   │  0x080191B0  LDRH.W R0,[R7,#0x9C]     ; read raw total
   │  0x08019274  LDRH.W R0,[R7,#0xA0]     ; read raw L1
   │  0x08019330  LDRH.W R0,[R7,#0xA2]     ; read raw L2
   ▼
publish into the power block  (in image order)
      0x0801A2EC  STR    R0,[R6,#0x64]     P L1      ─┐
      0x0801A2F8  STRH.W R0,[R6,#0x8A]     S L1       │ P and S published
      0x0801A306  STR    R0,[R6,#0x68]     P L2       │ by the same routine,
      0x0801A312  STRH.W R0,[R6,#0x8C]     S L2       │ alternating, through
      0x0801A320  STR    R0,[R6,#0x60]     P total    │ the same filters
      0x0801A32C  STRH.W R0,[R6,#0x88]     S total   ─┘
   ▼
FC04 handlers 0x0801E634 / 0x0801EA22 / 0x0801EA2C  (§2)
```

Active and apparent power travel the identical path. Whatever confidence register 24 deserves,
registers 25/131/132 deserve the same.

Two negative controls support the same conclusion:

- **No ARM code computes these fields.** A whole-image scan for stores into `0x2000D0E4` at offsets
  `0x60`, `0x64`, `0x68`, `0x88`, `0x8A`, `0x8C` finds only the six publishes above. Other offsets
  in the same struct *are* ARM-written — `+0x08`/`+0x0A` receive the model's rated power
  (`0x2710`=10000, `0x2EE0`=12000, `0x3138`=12600, `0x36B0`=14000, `0x3A98`=15000 W) at
  `0x08012972`–`0x080129D8`. So the struct mixes ARM-authored limits with DSP-authored
  measurements, and the six registers of interest sit firmly on the measurement side.
- **The values are consumed as power.** `+0x60`/`+0x64`/`+0x68` are integrated into the EPS energy
  accumulators at `0x080360B8`, `0x080360F0`, `0x08036124` — the source of `eps_energy` /
  `eps_energy_lifetime`.

> **Still unproven, and deliberately not claimed:** whether the C28x computes true-RMS apparent
> power (`S = V_rms · I_rms`) or a simplified estimate. That lives in the C28x image, for which no
> usable disassembler exists (see [`FIRMWARE_ACQUISITION.md`](FIRMWARE_ACQUISITION.md) §4). Nothing
> in this document depends on the answer — "genuine measured quantity in VA" is established without
> it.

---

## 4. Live cross-check

From the #544 reporter's diagnostics (12000XP, HYBRID mode, real hardware):

| Channel | P (W) | S (VA) | PF | S ≥ P |
|---------|------:|-------:|----:|:-----:|
| Total | 1104 | 1257 | 0.878 | ✓ |
| L1 | 529 | 588 | 0.900 | ✓ |
| L2 | 580 | 666 | 0.871 | ✓ |

- Leg sums: `529 + 580 = 1109` vs total `1104` (0.45%); `588 + 666 = 1254` vs total `1257` (0.24%).
  Small residuals are expected — the totals are received and filtered independently, not summed by
  the handler.
- Implied reactive power `√(S²−P²) = 601 VAR` — plausible for a residential load.
- Implied leg currents `588/119.6 = 4.92 A` and `666/119.6 = 5.57 A` — plausible.
- `S ≥ P` holds on every channel. A repurposed slot has no reason to respect that constraint;
  register 123 did not (28,646 "W" against a 1.1 kW load).

This is corroboration, not proof — but it is the kind that a wrong decode fails.

---

## 5. Second finding — EPS S/T voltages are not voltages

The same walk shows that of the three legacy R/S/T EPS voltage registers, only **R** is real:

| Reg | pylxpweb name | Decoded source | Verdict |
|----:|---------------|----------------|---------|
| 20 | `eps_voltage_r` | `RAM16[0x2000CE5C + 0x22]` = `0x2000CE7E` | genuine DSP field |
| 21 | `eps_voltage_s` | `RAM8[0x2000CF37] \| (RAM8[0x2000CF34] << 8)` | **byte-pair composite — not a voltage** |
| 22 | `eps_voltage_t` | `(RAM16[0x2000BB6A] & 0xFFF0) \| (RAM8[0x2000BB6C] & 0x0F)` | **bitfield merge — not a voltage** |

```
; register 21 — two unrelated bytes glued together (offsets differ by 3, not 1,
;               so this cannot be a little-endian 16-bit field read)
0801E5E8  df f8 68 09   LDR.W  R0,[PC,#0x968]      ; pool 0x0801EF54 -> 0x2000CE5C
0801E5EC  90 f8 d8 10   LDRB.W R1,[R0,#0xD8]       ; 0x2000CF34
0801E5F0  90 f8 db 00   LDRB.W R0,[R0,#0xDB]       ; 0x2000CF37
0801E5F4  50 ea 01 20   ORRS.W R0,R0,R1,LSL #8

; register 22 — masked 16-bit field OR'd with a nibble, from a fourth base entirely
0801E5FC  df f8 60 29   LDR.W  R2,[PC,#0x960]      ; pool 0x0801EF60 -> 0x2000B910
0801E600  b2 f8 5a 02   LDRH.W R0,[R2,#0x25A]      ; 0x2000BB6A
0801E604  4f f6 f0 71   MOVW   R1,#0xFFF0
0801E608  08 40         ANDS   R0,R0,R1
0801E60A  92 f8 5c 12   LDRB.W R1,[R2,#0x25C]      ; 0x2000BB6C
0801E60E  11 f0 0f 01   ANDS.W R1,R1,#0x0F
0801E612  08 43         ORRS   R0,R0,R1
```

The composed bytes are written by *different pages* of the receive parser, which is what rules out
their being one coherent field:

| Component | Writer |
|-----------|--------|
| Reg 21 high byte (`+0xD8`) | `0x08025C7A  STRB.W R0,[R6,#0xD8]` (page 2) |
| Reg 21 low byte (`+0xDB`) | `0x08025F44  STRB.W R1,[R0,#0xDB]` (page 5) |
| Reg 22 upper 12 bits (`+0x25A`) | `0x08025E5C  STRH.W R0,[R1,#0x25A]` (page 4) |
| Reg 22 low nibble (`+0x25C`) | `0x08025F72  STRB.W R0,[R6,#0x25C]` (page 5) |

The reporter's live readings decode exactly as the handlers predict:

| Sensor | Reading | Raw | Reads as |
|--------|--------:|----:|----------|
| `eps_voltage_r` | 239.0 V | 2390 = `0x0956` | a normal 16-bit word; matches L1+L2 = 119.6+119.6 = 239.2 V |
| `eps_voltage_s` | 1004.8 V | 10048 = `0x2740` | bytes `0x27` and `0x40` |
| `eps_voltage_t` | 417.8 V | 4178 = `0x1052` | `0x1050` plus nibble `0x2` |

**Current exposure — no user-visible bug.** `eps_voltage_s` / `eps_voltage_t` are members of
`THREE_PHASE_ONLY_SENSORS` (`const/device_types.py`) and are gated on
`features["supports_three_phase"]`, which is `False` for this hardware. The bogus values reach the
coordinator's internal sensor dict but no entity is created. Nothing needs fixing today.

**What this is a warning about:** the gate is currently correct for an incidental reason (split
phase), not because anyone knew the registers were junk. Do not relax `THREE_PHASE_ONLY_SENSORS`
for this family, and do not treat a three-phase off-grid variant as automatically safe — verify the
handler first.

What inputs 21/22 actually carry is **UNPROVEN**; naming them needs the C28x transmit-side decode.

> **These two registers are also unusable on EG4_HYBRID**, though for different reasons — there they
> are coherent DSP words rather than composites, but nothing uses them as voltages and live readings
> are implausible (`eps_voltage_s` = 256.0 V and 4832.0 V on two units). That family *can* be
> three-phase, so the gate that permanently suppresses these sensors here is not guaranteed to
> suppress them there. See [`HYBRID_EPS_REGISTERS.md`](HYBRID_EPS_REGISTERS.md).

---

## 6. Corroboration

Every claim was decoded twice — once by hand from the bytes, once by an independent reviewer
(Codex `gpt-5.6-sol`, xhigh) instructed to refute rather than confirm, working from the image alone.

| Claim | Verdict |
|-------|---------|
| Regs 24/25/129/130/131/132 all resolve pool slot `0x0801EF50` = `0x2000D0E4` | **CONFIRMED** (both decodes; pool bytes `e4 d0 00 20`) |
| Reg 25 = `RAM16[0x2000D16C]`, 131 = `RAM16[0x2000D16E]`, 132 = `RAM16[0x2000D170]`, no scaling | **CONFIRMED** |
| Active power divided by 10, apparent power not | **CONFIRMED** — and independently cross-checked by the `×10` normalisation at `0x0800E3F4` |
| 131/132 are individually implemented, not aliases of each other or of 25 | **CONFIRMED** (full 245-case dispatcher walk incl. cases 520–598 found no other reader of those three addresses) |
| The three apparent fields are DSP-sourced, ARM-filtered, not ARM-computed | **CONFIRMED** (parser → filter → publish chain in §3) |
| No ARM code writes `+0x60/0x64/0x68/0x88/0x8A/0x8C` other than the publish sites | **CONFIRMED** (whole-image scan; contrast `+0x08`/`+0x0A` rated-power writes) |
| The C28x computes true-RMS apparent power | **UNPROVEN** — not claimed; needs the DSP image |
| Reg 20 genuine; regs 21/22 are composites, not voltages | **CONFIRMED** (both decodes; writers on different parser pages) |
| What regs 21/22 actually carry | **UNPROVEN** |

An earlier pass of mine reported "zero writers" for the power fields and nearly concluded the struct
was DMA-filled. That was a tooling artefact — the base pointer is loaded once at `0x08018D8C` and
held in `R6` across a ~6 kB function, which a naive literal-tracking scan drops. The reviewer found
the publish sites; they were then verified byte-for-byte before being recorded here. **Absence of
evidence from a scanner is not evidence of absence — confirm the scanner can see what it claims is
missing.**

---

## 7. Reproducing this

```bash
# 1. download the off-grid pair (see FIRMWARE_ACQUISITION.md)
uv run python scripts/download_inverter_firmware.py --device-type SNA_US_12K --out-dir /tmp/fw

# 2. walk the FC04 dispatcher: registers 24/25/129/130/131/132 and 20/21/22
uv run python scripts/walk_input_dispatch.py \
    /tmp/fw/ceaa-07xx_vE_260214_Br7k5_2.bin --base 0x08005000 --start 0x0801DEEC
```

Both scripts are read-only and require no vendor tooling. The walk covers the contiguous chain only
(166 cases, up to register 235); the handlers in this document all fall inside that range.
