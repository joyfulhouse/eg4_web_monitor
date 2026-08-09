# Obtaining and Decoding EG4 Inverter Firmware

How to get a firmware image for **any** EG4 inverter family — including hardware you do not own —
and how to turn it into something a disassembler can read.

Two blockers historically defeated this work and produced the unusable artifacts under
[`re/`](re/): the OTA transport framing, and the C28x word serialisation order. Both are documented
below so they are never rediscovered the hard way.

---

## 1. Preferred route — download from the portal

The EG4 mobile app's *local update* flow serves complete firmware images over the normal portal
session. This supersedes the old approach of capturing an OTA push with `tcpdump`, and it works for
families you have no hardware for.

```bash
uv run python scripts/download_inverter_firmware.py --list
uv run python scripts/download_inverter_firmware.py --device-type SNA_US_12K --out-dir /tmp/fw
```

### Device-type enum

`firmwareDeviceType` only accepts these values, taken from the decompiled Android app at
`smali_classes2/com/nfcx/eg4/global/firmware/FIRMWARE_DEVICE_TYPE.smali`. Every other spelling is
rejected with `No enum constant …`, so they cannot be guessed:

| Value | Hardware | Integration family |
|-------|----------|--------------------|
| `LXP_LB_8_12K` | FlexBOSS21, 18kPV, 12kPV | `EG4_HYBRID` |
| `SNA_US_12K` | 12000XP / "SNA-US 15K" | `EG4_OFFGRID` |
| `SNA_US_6000` | 6000XP | `EG4_OFFGRID` |
| `POWER_HUB` | GridBOSS | MID |
| `DONGLE_E_WIFI_DONGLE` | WiFi dongle | — |

### Endpoints

```
POST /WManage/web/maintain/appLocalUpdate/listForAppByType
     firmwareDeviceType=<enum>
  -> rows of {recordId, fileName, standard, v1, v2, v3, encryptedFirmware}

POST /WManage/web/maintain/appLocalUpdate/getUploadFileAnalyzeInfo
     recordId=<id>&startIndex=<n>
  -> {firmwareData:[{index,data(base64)}], physicalAddrData:[{index,physicalAddr}],
      firmwareType, crc32, hasNext, fileName, tailEncoded}
```

> **`startIndex` is 1-based.** Passing `0` returns an empty body or HTTP 500 — indistinguishable
> from "no such firmware", which is exactly why this path looked like a dead end at first.

Page with `startIndex = max(index) + 1` until `hasNext` is false, then concatenate chunks in
ascending `index` order.

### Identifying the processor

`firmwareType` reads `PCS` for both processors and does **not** discriminate. Use the ratio of
chunk size to address stride instead:

| bytes per address | Processor | Typical load base |
|------------------:|-----------|-------------------|
| **2** | TI C28x inverter DSP (the power-conversion firmware) | `0x80000` |
| **1** | ARM Cortex-M comms processor | `0x080xxxxx` |

C28x is word-addressed — one address holds one 16-bit word — which is what produces the 2:1 ratio.

### Version strings map to file pairs

A device reports a combined version; each half is a separate file:

| Reported version | ARM file (`v1`) | DSP file (`v2`) |
|------------------|-----------------|-----------------|
| `ceaa-0709` (12000XP) | `ceaa-07xx_vE_260214_Br7k5_2.hex` | `CEAA-xx09_vE_260113.hex` |
| `FAAB-2727` (18kPV/FlexBOSS21) | `FAAB-27xx_20260330_App.hex` | `fAAB-xx27_Para375_20260330.hex` |

`xx` marks the half a given file does not carry. Some families (6000XP, `ccaa-1E1515`) carry a
third version byte.

Release notes per family:

```
POST https://res.solarcloudsystem.com:8443/resource/findAllTypeInfo
     firmwareDeviceType=<enum>
```

### Dead ends, recorded so they are not retried

- `POST …:8443/resource/getAllFirmware` returns **only** dongle (`ESP_WIFI`) images.
- `http://47.254.33.206:8083/resource/firmware/<name>` serves dongle images only; for anything else
  it answers **HTTP 200 with a zero-length body**, which is its not-found signature — a bogus
  filename returns exactly the same thing.
- `/WManage/web/maintain/standardUpdate/checkUpdates` returns no filename when a unit is already
  current.

---

## 2. Legacy route — OTA packet capture

Images extracted from an OTA pcap (see [`FIRMWARE_OTA_PROTOCOL.md`](FIRMWARE_OTA_PROTOCOL.md) and
`docs/reference/firmware/captures/`) still carry transport framing and **must be de-framed** before
disassembly. Files under [`extracted/`](extracted/) are in this raw state.

```
repeating 771-byte block:
  [1 byte]   block prefix, constant 0x08
  [768 byte] firmware payload
  [2 byte]   model-keyed block checksum
final partial block additionally ends with a 6-byte trailer (4-byte firmware id + CRC16-LE)
```

**Do not de-frame by assuming a uniform block size.** Stripping 1 leading + 2 trailing bytes from
each 771-byte block reproduces the image correctly only for roughly the first `0xF100` bytes; beyond
that the OTA chunk sizes are not uniform and a fixed-period rule silently corrupts everything
downstream. Reconstruct instead from the pcap's own chunk records via
`scripts/extract_firmware_from_pcap.py`, which follows the transfer's sequence numbers.

**How the block structure was established** (repeat if the format ever changes): diff the two model
variants of the *same* App firmware. Differences appear in pairs at offsets 769,770 of each block at
a 771 cadence — the model-keyed checksums, which reveal the period directly.

**How to verify a candidate reconstruction** — do not skip this, an off-by-one silently corrupts
every instruction downstream while leaving the start of the image looking perfect:

- The ARM image must begin with a valid Cortex-M vector table. For `FAAB-27xx…App`: SP
  `0x20000598`, Reset `0x0802b24d`, NMI `0x080132f1`, HardFault `0x080132f3` — all Thumb-odd and
  in-flash. **This check passes even on a badly mis-framed image**, because the corruption starts
  much later; it is necessary, not sufficient.
- The decisive check: the correctly reconstructed `FAAB-27xx_20260330_App` payload is **351,642
  bytes**, SHA-256 `63d0efba3495a8c601b44c020ecd04aa1329abcbbb64148f5b43ab477149f4a2`, and the
  18kPV and FlexBOSS21 reconstructions are then **byte-identical** — the ARM comms firmware is
  genuinely the same binary on both models. If your reconstruction yields residual cross-model
  differences (e.g. ~761 bytes at a 768-byte cadence beginning at `0xF100`), that is *your framing
  error*, not model-specific content.

None of this affects the portal-download route in §1, whose images never carry OTA framing.

Portal-downloaded images (§1) are **already de-framed** — this section does not apply to them.

---

## 3. Reading the C28x DSP image

### Words are serialised MSB-first

The image stores each 16-bit word high byte first. Read little-endian it looks like structureless
data, which is why earlier passes concluded the DSP contained no functions. Read big-endian the
code density is unmistakable:

| Measure (big-endian words) | 18kPV DSP | FlexBOSS21 DSP | ARM image (control) |
|---|---:|---:|---:|
| `LRETR` (`0xFF69`) | 112 | — | 0 |
| `LRET` (`0x0006`) | 516 | 497 | 40 |
| `MOVW DP,#imm` (`0x761F`) | 10,200 | 10,177 | 0 |

Roughly 90% of long-call targets resolve inside the image under this interpretation; the opposite
order destroys that self-consistency.

### Entry point

A valid image begins with a C28x `LB 22bit` long branch: word0 = `0x0040 | (addr >> 16)`,
word1 = `addr & 0xFFFF`.

| Image | First words | Decodes as |
|-------|-------------|------------|
| 18kPV `Para375` | `0048 1459` | `LB 0x081459` |
| FlexBOSS21 `Para075` | `0048 1459`-class | `LB 0x0814xx` |
| 12000XP `CEAA-xx09` | `0048 1098` | `LB 0x081098` |

### Cross-model comparison

Compare Para images with an **edit-aware** diff, not a positional one. The 18kPV and FlexBOSS21
DSP images are **96.9% similar** (edit distance 17,828 bytes) — a naive byte-for-byte positional
diff reports ~87% *different* purely because code is relocated between builds.

---

## 4. Tooling reality

- **Ghidra** is not installed here and has no stock C28x processor module.
- **radare2** is installed and advertises a `tms320` plugin, but it targets c54x/c55x/c64x and
  **mis-decodes C28x** — given the known sequence `0006 761f 03b8 0006` (`LRETR` / `MOVW DP,#0x03B8`
  / `LRETR`) it emits unrelated instructions such as `nop_16`, `abs`, `mpymk`. Do not use it.
- Practical approach: decode the specific opcodes you need per TI **SPRU430**, and never publish
  speculative disassembly. `scripts/walk_input_dispatch.py` is a worked example for the ARM side.

---

## 5. Validate every conclusion against hardware

Firmware decoding is easy to get subtly wrong, and a wrong decode reads exactly like a right one.
Anchor conclusions to measurements:

- The FC04 dispatcher walk must report input registers **153** and **170** as implemented — issue
  [#196](https://github.com/joyfulhouse/eg4_web_monitor/issues/196) measured `I153 = 1409 W` and
  `I170 = 3788 W` on real off-grid hardware. `scripts/walk_input_dispatch.py` asserts this
  automatically; two earlier walks failed it and were discarded.
- Where a register's meaning is at stake, check the decode against a live capture or an issue
  report before publishing it.

Worked analyses following this method:

- [`OFFGRID_GENERATOR_REGISTERS.md`](OFFGRID_GENERATOR_REGISTERS.md) — input 123 is an ARM-local
  1 Hz counter, not generator power (issue #544).
- [`OFFGRID_EPS_REGISTERS.md`](OFFGRID_EPS_REGISTERS.md) — inputs 25/131/132 (EPS apparent power)
  *are* genuine DSP measurements, traced parser → filter → publish → Modbus; inputs 21/22 (EPS S/T
  voltage) are byte/bitfield composites and not voltages.

A scanner that reports "no writers" is the trap to watch for: a base pointer held in a callee-saved
register across a large function defeats naive literal tracking, and the resulting silence reads
exactly like proof of absence. Confirm the scanner can see a known-good writer before trusting it
on an unknown one.
