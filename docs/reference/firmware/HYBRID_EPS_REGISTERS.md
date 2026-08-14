# Does EG4_HYBRID Carry the Same EPS Registers? — Firmware + Live Evidence

**Question.** [`OFFGRID_EPS_REGISTERS.md`](OFFGRID_EPS_REGISTERS.md) showed that on the off-grid
12000XP the EPS apparent-power registers are genuine DSP measurements while the legacy EPS **S/T
voltage** registers are not voltages at all. Does the hybrid family (18kPV / FlexBOSS21,
`FAAB-2727`) behave the same way?

**Answer: no — the registers exist but mean different things, and two of them are not measurements.**

| Reg | Sensor | EG4_OFFGRID | EG4_HYBRID |
|---:|---|---|---|
| 20 | `eps_voltage_r` | genuine | **genuine** (DSP word, used in real voltage arithmetic) |
| 21/22 | `eps_voltage_s` / `eps_voltage_t` | byte/bitfield composites — not voltages | independent DSP words, but **voltage semantics unproven**; live values implausible |
| 24 | `eps_power` | DSP word, 32-bit, ÷10 | DSP-fed via ARM mirror, 32-bit, ÷10 |
| 25 | `eps_apparent_power` | **direct DSP measurement**, 16-bit whole VA | **ARM-computed estimate** `V × I ÷ 100`, clamped so S ≥ P |
| 129/130 | EPS L1/L2 active power | DSP, 32-bit, ÷10 | DSP-fed, 16-bit, whole W |
| 131 | `eps_l1_apparent_power` | **genuine apparent power** | DSP power quantity, **sign-split by direction — not apparent power** |
| 132 | `eps_l2_apparent_power` | **genuine apparent power** | **an incrementing counter — not a measurement** |

Register 132 on hybrid is the same class of defect as the register-123 generator-power bug in
[#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544): a counter surfaced as an
instantaneous power sensor. Unlike the S/T voltages, **it is exposed to users today** (§5).

---

## 1. Two method corrections that come first

Both of these produce confident nonsense rather than loud failure. Both cost time in this session.

### The hybrid image in `extracted/` is raw-framed, and the obvious de-frame is wrong

`scripts/extract_firmware_from_pcap.py` reassembles the OTA transfer but **its output still carries
the transport framing** — 353,026 bytes whose "vector table" reads `SP=0x00059808`, the classic
one-byte shift. De-framing is a separate step, and the fixed-period rule warned about in
[`FIRMWARE_ACQUISITION.md`](FIRMWARE_ACQUISITION.md) §2 corrupts everything past roughly `0xF100`
while leaving the image start looking perfect.

The working recipe strips framing **per actual chunk**:

```python
fp = extract_firmware_passes(pcap)[0]          # pass 0 = ARM App
out = bytearray()
for s in sorted(fp.chunks):
    p = fp.chunks[s].raw_payload[CHUNK_HEADER_SIZE:]
    assert p[0] == 0x08                        # OTA block prefix
    out += p[1:-2]                             # drop prefix + block checksum
del out[-4:]                                   # final chunk carried only the 4-byte fw-id
```

Chunk lengths are **not** uniform — `455×771, 4×259, 1×481, 1×703, 1×7` — which is exactly why a
fixed period fails. The arithmetic predicts the target exactly:
`455·768 + 4·256 + 478 + 700 = 351,642`.

Verify all four:

| Check | Value |
|---|---|
| Size | **351,642 bytes** |
| SHA-256 | **`63d0efba3495a8c601b44c020ecd04aa1329abcbbb64148f5b43ab477149f4a2`** |
| Vector table | SP `0x20000598`, Reset `0x0802B24D`, NMI `0x080132F1`, HardFault `0x080132F3` |
| Cross-model | 18kPV and FlexBOSS21 captures reconstruct **byte-identically** |

The cross-model check is the strongest available: two dongles, two pcaps, one identical binary.

### The hybrid ARM load base is `0x08010000`, not `0x08005000`

Carrying the off-grid base over shifts every instruction boundary and literal resolution, and
disassembles into plausible garbage. Back-solve from a vector-table entry instead:

```
NMI vector 0x080132F1 -> handler 0x080132F0
self-loop pair found at file offset 0x032F0
base = 0x080132F0 - 0x032F0 = 0x08010000
```

Confirmations at `0x08010000` (none hold at `0x08005000`): `0x080132F0` = `70 47` (`BX LR`) with
`fe e7` (`b .`) self-loops after it for HardFault; literal-pool words resolving into RAM jump to
**4,263**; and the independently documented generator derivation at `0x080319DC` resolves its two
literals to exactly `0x2000EAE4` / `0x2000EAE6`, matching
[`OFFGRID_GENERATOR_REGISTERS.md`](OFFGRID_GENERATOR_REGISTERS.md) §8 derived in an earlier session
from a different reconstruction.

| Image | Family | Load base |
|---|---|---|
| `ceaa-07xx…` | EG4_OFFGRID (12000XP) | `0x08005000` |
| `FAAB-27xx…App` | EG4_HYBRID (18kPV / FlexBOSS21) | `0x08010000` |

---

## 2. The FC04 path — and the decoy that nearly derailed this

**FC04 input registers are served from a linear register image at `0x20009DBC`,** built by
`0x080594D8` and emitted big-endian by the response loop at `0x0803FD7E`–`0x0803FDA0`, two bytes per
register. Dispatch reaches it via `0x0803F050` → `0x0803FCCC` → `0x0803FD64`. There are no separate
per-register handler functions as on off-grid; each register has an *emission site* inside the
builder.

> **The decoy.** This image also contains a second, unrelated serialiser that writes a byte-swapped
> report frame into a buffer at `0x2000B6D4` (~187 two-byte slots, nine distinct literal-pool
> entries hold its base). It looks exactly like a register image, and the generator trio appears to
> land at slots `0xF0`/`0xF2`/`0xF4`/`0xF6` = registers 120–123 — which is very persuasive and
> **wrong**. That buffer is the outbound cloud/dongle report with its own field order; `offset/2` is
> *not* the Modbus register index.
>
> The tell was a contradiction that would not resolve: the slot at `0x28` (apparently register 20)
> received only a single low byte and its high byte was never written, yet live `eps_voltage_r`
> reads a full 2468. Chasing that down is what exposed the decoy. **When a mapping produces one
> fact you cannot explain, stop and doubt the mapping — do not explain the fact away.**
>
> Everything derived from that buffer — including a five-branch "mode constant" story for the
> reg-21 slot — describes the *report frame*, not the FC04 registers, and is not evidence about
> register semantics.

---

## 3. Register sources on hybrid

All addresses verified byte-for-byte against the image (SHA `63d0efba…`, base `0x08010000`).

| Reg | Emission site | Literal pool → base | Width | Scaling |
|---:|---|---|---|---|
| 20 | `0x080596FC` `df f8 30 0d` | `0x0805A430` → `0x2000EAF8` | 16-bit | none (wire ×0.1 V) |
| 21 | `0x08059712` `df f8 20 0d` | `0x0805A434` → `0x2000EB2C` | 16-bit | none (wire ×0.1 V) |
| 22 | `0x08059728` `df f8 0c 0d` | `0x0805A438` → `0x2000EB2E` | 16-bit | none (wire ×0.1 V) |
| 23 | `0x0805973E` `df f8 fc 0c` | `0x0805A43C` → `0x2000EB04` | 16-bit | none (wire ×0.01 Hz) |
| 24 | `0x08059754` `df f8 e8 0c` | `0x0805A440` → `0x2000E92C` | 32-bit | signed ÷10 |
| 25 | `0x08059770` `df f8 d0 0c` | `0x0805A444` → `0x2000E940` | 32-bit | signed ÷10 |
| 129 | `0x0805A794` / `0x0805A8E8` | `0x2000EAEA` / `0x2000EAEC` | 16-bit | none, whole W |
| 130 | `0x0805A7AA` / `0x0805A8FE` | `0x2000EAFE` / `0x2000EB00` | 16-bit | none, whole W |
| 131 | `0x0805A7C0` / `0x0805A914` | `0x2000E8C0` / `0x2000E898` | 32-bit | ÷10 |
| 132 | `0x0805A7EC` / `0x0805A930` | `0x0805B53C` → `0x2000D088` `+0` / `+2` | 16-bit | none |

Registers 129–132 have **two source sets (A/B)** selected by a mode test at `0x0805A770`–`0x0805A790`
(a flag byte at `0x2000E984` bit 0, and `0x2000D488+0xB2` bit 2). No register above is unimplemented.

### Register 25 is computed, not measured

```
0x0804CE10  86 48 00 88     LDRH R0,[voltage]
            80 49 09 88     LDRH R1,[current]
            48 43           MULS R0,R1,R0        ; V × I
            64 21           MOVS R1,#100
            b0 fb f1 f0     UDIV R0,R0,R1        ; ÷ 100
            75 49 08 60     STR  R0,[0x2000E88C]
```

Published to `0x2000E940` at `0x08019B4E`–`0x08019B58`, with fallback/clamp branches at
`0x08019ED8`–`0x08019F00` that force **S ≥ P**. So hybrid's aggregate apparent power is a genuine
physical estimate built from DSP voltage and current — but it is ARM arithmetic, not a DSP-measured
S word as on off-grid. The `S ≥ P` relation on hybrid is *enforced by the firmware*, so unlike
off-grid it is **not** independent evidence that the value is real.

### Register 132 is a counter

```
0x080154F2  df f8 50 0b     LDR.W R0,[→ 0x2000D088]
            00 88           LDRH  R0,[R0]
            40 1c           ADDS  R0,R0,#1        ; increment
            df f8 48 1b     LDR.W R1,[→ 0x2000D088]
            08 80           STRH  R0,[R1]
```

`[0x2000D088+0]` increments only after an accumulator at `[+0xA0]` crosses `0x006DDD01`; the `+2`
half does the same from `[+0xA8]` at `0x08015698`–`0x080156A4`. It is a persistent, thresholded
event counter — the same shape as off-grid register 123. All nine literal-pool instances of
`0x2000D088` were audited; every other write is initialisation, reset, or persistence restore
(including one through a callee-saved `R8` held across a restore loop at `0x08057624` — the exact
blind spot that produced a wrong "no writers" conclusion on the off-grid image).

### Scaling asymmetry: absent on hybrid

Off-grid stores P in deciwatts and S in whole VA, and normalises S by ×10 when building its report.
Hybrid stores **both** P and S as 32-bit deci-units, divided by 10 at both the FC04 emission sites
(`0x08059754` / `0x08059770`) and the outbound builder (`0x08031652` / `0x0803174A`). There is no
×10 S normalisation anywhere. The two families genuinely differ here.

---

## 4. Live hardware

From the maintainer's plant (HYBRID mode, `supports_three_phase = False`, `supports_split_phase = True`):

| Sensor | 18kPV (`SN_11`) | FlexBOSS21 (`SN_13`) | Reading |
|---|---:|---:|---|
| `eps_voltage_l1` / `l2` | 122.6 / 123.5 V | 123.6 / 123.2 V | genuine |
| `eps_voltage_r` | **246.8 V** | **247.6 V** | genuine — matches L1+L2 (246.1 / 246.8) |
| `eps_voltage_s` | **256.0 V** | **4832.0 V** | implausible |
| `eps_voltage_t` | **2054.4 V** | **2362.6 V** | implausible |
| `eps_frequency` | 59.99 Hz | 59.99 Hz | genuine |
| `eps_power`, `eps_apparent_power`, `_l1`, `_l2` | 0 | 0 | EPS idle — uninformative |

Two units of the same family disagree by nearly 20× on `eps_voltage_s`, and no quantity on a
120/240 V split-phase system reads 4832 V. Whatever registers 21/22 carry here, it is not
S/T voltage on this hardware.

The apparent-power sensors all read `0` because EPS output was idle — which is also exactly what a
threshold-gated counter reads before its threshold is crossed. **The live data cannot distinguish
the counter hypothesis from a working sensor; only the firmware does.**

---

## 5. Integration impact

### Exposed today — `eps_apparent_power_l2` (register 132)

```
sensor.18kpv_synth00004_eps_apparent_power_l2         0 VA
sensor.flexboss21_synth00003_eps_apparent_power_l2    0 VA
```

Four such entities exist on the maintainer's system. They are backed by a counter. Once the
firmware's accumulator threshold is crossed they will climb monotonically and never return to a
plausible VA reading — presented with `VA` units and `measurement` state class, polluting long-term
statistics. This is the [#544](https://github.com/joyfulhouse/eg4_web_monitor/issues/544) pattern
on a different family.

`eps_apparent_power_l1` (register 131) is a genuine DSP power quantity but is **sign-split into
positive- and negative-direction fields**, which is incompatible with a non-negative apparent power;
its B source zeroes the positive field when the value is negative (`0x0804D846`, `0x0804D850`). It
should not be trusted as VA either, though it is less clearly wrong than 132.

Suggested handling — mirroring the #544 fix rather than inventing a new mechanism: add registers
131/132 to a hybrid-scoped exclusion so the two per-leg VA sensors are not created on EG4_HYBRID,
fail-closed on unresolved family, exactly as `OFFGRID_EXCLUDED_SENSORS` does today. The aggregate
`eps_apparent_power` (register 25) should **stay** — it is a real, if firmware-computed, estimate.

### Latent, not exposed — `eps_voltage_s` / `eps_voltage_t`

Both are in `THREE_PHASE_ONLY_SENSORS` and gated on `features["supports_three_phase"]`. Every unit
observed reports `False`, so no entity is created and the implausible values stop at the
coordinator's internal dict.

The risk is nonetheless real and **greater than on off-grid**: EG4_HYBRID is precisely the
three-phase-capable family, so on a genuinely three-phase hybrid the gate **opens**.

Recommended posture:

1. Do **not** relax `THREE_PHASE_ONLY_SENSORS` or the `supports_three_phase` gate for these keys.
2. Treat three-phase hybrid as an **untested configuration** for EPS S/T voltage specifically.
3. If a three-phase hybrid ever reports absurd `eps_voltage_s`/`_t`, this document is the
   explanation, and the fix is to drop the sensors, not rescale them.

Deliberately **not** done: removing 21/22 outright. On genuinely three-phase firmware these slots
may well carry real R/S/T voltages — that is what the registers are for — and no three-phase
hardware has been observed either way. Removing them would trade a latent bug for a certain
regression on a configuration nobody has tested.

---

## 6. What is NOT established

- **Registers 21/22 physical semantics — UNPROVEN.** The ARM image only copies them to FC04 and the
  report frame; they are never used in voltage arithmetic (unlike register 20, which is multiplied
  by current at `0x0804CE10`). They are assembled from adjacent bytes on one DSP receive page, so
  they are coherent 16-bit DSP words, **not** off-grid-style composites. What the DSP puts there in
  three-phase mode is unknown without the C28x image or readings from a live three-phase install.
- **Register 131 — not proven to be apparent power, and not proven to be anything else.** The
  sign-split writer argues against S; nothing identifies what it *is*.
- **Register 25's accuracy is unvalidated.** `V × I ÷ 100` is dimensionally an apparent power, but
  no live measurement with an actual EPS load has been taken on hybrid to check it against
  `eps_power`. The firmware's own `S ≥ P` clamp means that relation cannot serve as a check.
- **The `0x2000B6D4` report-frame field order is unmapped.** It is a real structure carrying real
  values; nothing here establishes which field is which.

---

## 7. Corroboration

The FC04 builder, the register table in §3, and the counter/estimate findings came from an
independent adversarial pass (Codex `gpt-5.6-sol`, xhigh) working from the image alone; every
instruction and literal-pool value cited was then re-verified byte-for-byte before being recorded
here. That pass **refuted** an earlier conclusion of mine — a five-branch "mode constant" mechanism
for register 21 — by showing I had traced the wrong buffer. The live-hardware evidence in §4 was
gathered independently of both and depends on no firmware decode at all.

Corrected in place rather than left standing: an earlier draft of this document asserted that
hybrid registers 21/22 were byte composites "the same class of junk as off-grid". They are not.
The *conclusion* that they are not usable S/T voltages survives — on live-data grounds — but the
mechanism was wrong, and a wrong mechanism recorded as fact is how the `re/` artifacts became
unusable in the first place.

---

## 8. Reproducing this

```bash
# 1. rebuild the hybrid ARM App correctly (per-chunk de-frame, §1)
#    inputs: docs/reference/firmware/captures/{18kpv,flexboss21}_firmware_upgrade_complete.pcap
#    verify: 351,642 bytes / sha256 63d0efba... / both captures byte-identical

# 2. disassemble at the CORRECT base
r2 -q -a arm -b 16 -m 0x08010000 -c "e asm.bits=16; s 0x08010000; pD 351642" hybrid_app.bin

# 3. live cross-check (read-only HTTP, no Modbus contention)
curl -s -H "Authorization: Bearer $HA_PROD_LONG_LIVED_TOKEN" \
     "$HA_PROD_BASE_URL/api/diagnostics/config_entry/<entry_id>"
```

Stop the `homeassistant-dev` container before any local Modbus probing — production runs HYBRID and
the gateway allows one connection.
