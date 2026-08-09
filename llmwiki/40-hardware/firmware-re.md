---
canonical-for: firmware-acquisition-decoding-and-register-re-methodology
sources:
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md
  - docs/reference/firmware/OFFGRID_EPS_REGISTERS.md
  - docs/reference/firmware/HYBRID_EPS_REGISTERS.md
  - docs/reference/firmware/re/00_SUMMARY.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Firmware reverse engineering

> **The previous reverse-engineering output failed because of two stacked errors: retained OTA record framing and little-endian TI C28x word decoding. Correcting only one still produces garbage.** The invalid method is status `refuted`; the disproof is `firmware-proven` by corrected de-framing plus structural validation. Any conclusion derived from the affected output is invalid unless independently re-established.

## Authority status

| Path or artifact | Status | Evidence | Permitted use |
|---|---|---|---|
| `docs/reference/firmware_re/` | **SUPERSEDED / refuted** stale duplicate | `firmware-proven` disproof | Do not cite its generated disassembly, opcode counts, functions, register maps, section map, or checksum claims. |
| Generated results inside `docs/reference/firmware/re/` | **INVALID GENERATED OUTPUT — SUPERSEDED / refuted; TOMBSTONE ONLY** | `firmware-proven` disproof | Retain only as a record of the failed method. [`00_SUMMARY.md`](../../docs/reference/firmware/re/00_SUMMARY.md) documents the invalidity. |
| Live-probe JSON files inside `docs/reference/firmware/re/` | **VALID as raw hardware observations**, not firmware results | `asserted-unverified` for semantics | The durable JSON files may support later correlation; their labels and interpretations are not automatically proven. |
| `docs/reference/firmware/FIRMWARE_ACQUISITION.md` | Current acquisition/de-framing methodology | `firmware-proven` | Use for image retrieval, record reconstruction, processor classification, and structural validation. |
| `OFFGRID_GENERATOR_REGISTERS.md`, `OFFGRID_EPS_REGISTERS.md`, `HYBRID_EPS_REGISTERS.md` | Current worked analyses | `firmware-proven` only for explicitly traced claims | Preserve each page’s model/family boundary and unresolved qualifications. |

Banner state and duplicate-tree ownership are canonical in [superseded claim S4](../60-history/superseded-claims.md). Both trees remain invalid sources for generated reverse-engineering conclusions.

## Acquire a trustworthy image

Prefer authenticated portal `appLocalUpdate` images because the portal returns already de-framed bytes.

| Step | Procedure | Evidence grade | Failure prevented |
|---:|---|---|---|
| 1 | Call `POST /WManage/web/maintain/appLocalUpdate/listForAppByType` with the exact `firmwareDeviceType`. | `portal-correlated` | Guessing resource filenames or using the wrong family. |
| 2 | Call `POST /WManage/web/maintain/appLocalUpdate/getUploadFileAnalyzeInfo`; treat `startIndex` as one-based. | `portal-correlated` | Missing the first chunk or silently accepting a sparse sequence. |
| 3 | Request through `max(index) + 1`, require a complete index sequence, Base64-decode each chunk, and concatenate in index order. | `portal-correlated` | Truncated or reordered images. |
| 4 | Record image length, address span, portal metadata, and cryptographic hash before analysis. | `firmware-proven` as a validation practice | Mixing versions/models or analyzing a silently changed artifact. |
| 5 | Classify by bytes per address, not `firmwareType=PCS`: 2 bytes/address is normally word-addressed C28x at word base `0x80000`; 1 byte/address is ARM at `0x080xxxxx`. | `firmware-proven` | Misclassifying the DSP image as parameter data or treating ARM bytes as C28x words. |

### Portal family enums

| Portal enum | Intended family | Concrete artifact status | Evidence grade |
|---|---|---|---|
| `LXP_LB_8_12K` | FlexBOSS21, 18kPV, 12kPV / `EG4_HYBRID` | 18kPV/FlexBOSS ARM and C28x pairs validated; no separately validated 12kPV artifact in the reviewed corpus. | `firmware-proven` for reviewed 18kPV/FlexBOSS images; `lineage-inferred` for 12kPV |
| `SNA_US_12K` | 12000XP / SNA-US 15K / `EG4_OFFGRID` | ARM base `0x08005000` and MSB-first C28x image validated. | `firmware-proven` |
| `SNA_US_6000` | 6000XP / `EG4_OFFGRID` | Enum/version convention exists; no reviewed concrete decoded image. | `lineage-inferred` |
| `POWER_HUB` | GridBOSS | Local image has a coherent Cortex-M vector; full load base/section map remains open in [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md). | `firmware-proven` for code structure; `asserted-unverified` for full map |
| `DONGLE_E_WIFI_DONGLE` | Wi-Fi dongle | Separate ESP32/W7500 route and formats. | `lineage-inferred` for inverter semantics; do not use it as inverter register proof |

These acquisition starting points have status `refuted` by `portal-correlated` evidence: ordinary inverter firmware is not reliably obtained from `resource/getAllFirmware`, guessed static resource URLs, or `standardUpdate/checkUpdates` when the device is current.

## OTA captures: parse records, never strip a fixed cadence

An OTA capture is a sequence of transport records, not a flat firmware stream.

| Record component | Established layout | Evidence grade | Qualification |
|---|---|---|---|
| Prefix | One byte, normally `0x08` | `firmware-proven` | Transport framing, not firmware payload. |
| Normal payload | 768 firmware bytes | `firmware-proven` | Extract only after identifying the actual record boundary. |
| Per-record check | Two model-keyed check bytes | `firmware-proven` for position/model dependence | Exact checksum/key algorithm remains `asserted-unverified`; durable boundary: [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md). |
| Final partial record | Variable payload, followed by four-byte firmware ID and a little-endian 16-bit integrity field | `firmware-proven` for structure | Exact coverage and polynomial/variant remain `asserted-unverified`; durable boundary: [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md). |

Real captures contain normal 771-byte records and variable tail records. A fixed 771-byte stride can produce a plausible image start while silently corrupting the tail after the first irregular record. Reassemble by actual packet/record boundaries and sequence numbers; treat the final partial record separately. `scripts/extract_firmware_from_pcap.py` reassembles transfer content but does not by itself make the emitted `.bin` de-framed.

### Checksum status

| Claim | Evidence grade | Current conclusion |
|---|---|---|
| Check-byte position and two-byte width | `firmware-proven` | One prefix + 768 payload + two checks for normal records. |
| The pair is model-keyed | `firmware-proven` | Same-App cross-model captures differ as pairs at the check-byte positions. |
| Exact per-block checksum/key algorithm | `asserted-unverified` | **UNKNOWN.** [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) does not establish an algorithm; do not repeat old XOR keys, custom CRCs, or block-table claims. |
| Final trailer’s exact covered bytes and CRC polynomial/variant | `asserted-unverified` | **UNKNOWN.** [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) bounds the structure; the algorithm is not established. |
| Portal `crc32` metadata | `portal-correlated` | The downloader records it; current tooling does not establish that it verified it. |

## Validate before disassembly

### ARM images

| Validation | Acceptance criterion | Evidence grade |
|---|---|---|
| Vector table | Initial stack pointer lies in plausible RAM; reset/exception vectors are Thumb addresses inside the candidate image mapping. | `firmware-proven` |
| Load base | Derive it anew from vectors/self-loop behavior; corroborate it with RAM-pointer density and known literals. | `firmware-proven` when all controls agree |
| Image identity | Length, address span, and hash match the captured metadata; independent same-App captures match where expected. | `firmware-proven` |
| Instruction alignment | Thumb instructions are 2-byte aligned; the old 4-byte walk has status `refuted`. | `firmware-proven` |

A plausible vector alone is necessary but not sufficient. The GridBOSS image, for example, proves coherent Cortex-M structure but does not yet establish the complete load base and section map.

### TI C28x images

Decode 16-bit instruction words **MSB-FIRST**.

| Validation | Healthy-image signal | Evidence grade |
|---|---|---|
| Entry | First words form a legal in-image long branch, such as `0048 1098` → `LB 0x081098`. | `firmware-proven` |
| Return/opcode population | Coherent `LRET`/`LRETR`, `MOVW DP`, and control-flow populations rather than noise-like statistics. | `firmware-proven` |
| Call targets | A large majority of decoded long-call targets resolve inside the image; corrected reviewed builds are roughly 90%. | `firmware-proven` |
| Related builds | Use an edit-aware diff; corrected hybrid DSP builds are 96.9% similar. | `firmware-proven` |
| Tool support | Implement only required opcodes from TI SPRU430. Treating radare2 `tms320` output as C28x proof has status `refuted`. | `lineage-inferred` from tool/architecture documentation; validate with the structural checks above |

Reading C28x words little-endian produced zero-function “decompilations” and noise-like statistics. `Para*` images are executable C28x power-conversion firmware, not parameter tables.

## Trace a register end to end

Finding a number in an FC04 handler is not enough. The minimum proof chain is:

| Stage | Required evidence | Evidence grade if complete |
|---:|---|---|
| 1. Producer | Identify every firmware writer or DSP/parser source for the backing value. Require a known-good writer as a positive control before accepting “no writers found.” | `firmware-proven` |
| 2. Conversion | Decode signedness, scaling, subtraction/summing, clamping, byte selection, and truncation. | `firmware-proven` |
| 3. Publisher | Trace how the converted value enters the ARM register publication structure; account for callee-saved bases and every dispatcher gap/decrement width. | `firmware-proven` |
| 4. FC04 response | Trace the exact dispatcher case and response word(s), including family-specific address reuse. | `firmware-proven` |
| 5. Positive controls | The same dispatcher walk must recover known-live I153 and I170, with correct numbering after gaps. | `firmware-proven` |
| 6. Independent check | Re-run the decode adversarially and cross-check on live hardware before calling the real-world semantic verified. | `hardware-toggle-proven` when a controlled observation exists |

The required direction is **producer → conversion → publisher → FC04 response**. Reverse naming from a response slot alone can prove structure but not physical meaning.

## Known-good artifact boundaries

| Device/image | Established result | Evidence grade | Boundary |
|---|---|---|---|
| 18kPV/FlexBOSS ARM App | Correct payload is 351,642 bytes; validated vector and independent byte identity. | `firmware-proven` | The committed 353,026-byte extracted App remains framed and is invalid as-is. |
| 18kPV/FlexBOSS `Para375`/`Para075` | C28x code under de-framing plus MSB-first words. | `firmware-proven` | Committed raw extracted files are not directly usable. |
| 12000XP ARM `ceaa-07xx` | 238,856-byte ARM image, base `0x08005000`, coherent vector/pointers. | `firmware-proven` | Applies to the reviewed build, not every off-grid model. |
| 12000XP C28x `CEAA-xx09` | 139,768-byte word-addressed image at `0x80000`, legal entry and coherent code statistics. | `firmware-proven` | Applies to the reviewed build. |
| 6000XP | No concrete decoded artifact reviewed. | `asserted-unverified` | [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) records the family enum, not a validated image. Do not transfer the 12000XP I123 proof. |
| 12kPV hybrid | No separately validated artifact reviewed. | `asserted-unverified` | [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) records portal-family membership, not a decoded-image result. |

## Method claims permanently retired

| Retired claim | Evidence disproving it | Status | Correction |
|---|---|---|---|
| “Strip fixed 771-byte blocks” or “remove only the last two bytes.” | `firmware-proven` | refuted | OTA record sizes vary; parse actual records. |
| “C28x words are little-endian.” | `firmware-proven` | refuted | Decode words MSB-first. |
| “Para files are only parameter data.” | `firmware-proven` | refuted | They contain coherent C28x code. |
| “`0x404–0x2936` is a proven flat register table.” | `firmware-proven` | refuted | It came from invalid generated output. |
| “Old per-region offsets/section maps are authoritative.” | `firmware-proven` | refuted | Re-derive each image’s base and structure. |
| “Related DSP builds are 87% different.” | `firmware-proven` | refuted | Edit-aware comparison finds 96.9% similarity. |
| “A no-writer scan proves absence.” | `firmware-proven` | refuted | It is non-evidence until the scanner first detects a known-good writer. |

See [FIRMWARE_ACQUISITION.md](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) for the underlying acquisition evidence. Treat the old RE directories according to the authority table at the top of this page before following any historical link.
