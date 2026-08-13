---
canonical-for:
  - firmware-acquisition-decoding-and-register-re-methodology
  - ESP32-WLAN-dongle-local-listener-behaviour-and-patch-lineage
sources:
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md
  - docs/reference/firmware/OFFGRID_EPS_REGISTERS.md
  - docs/reference/firmware/HYBRID_EPS_REGISTERS.md
  - docs/reference/firmware/re/00_SUMMARY.md
  - issue eg4-x00j
  - issue eg4-gzol
  - issue eg4-vr06
verified-against: ae9f033
last-verified: 2026-08-13
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

| Stage | Required trace | Evidence record produced |
|---:|---|---|
| 1. Producer | Identify every firmware writer or DSP/parser source for the backing value. Require a known-good writer as a positive control before accepting “no writers found.” | Writer/source addresses, call path, and positive-control result. |
| 2. Conversion | Decode signedness, scaling, subtraction/summing, clamping, byte selection, and truncation. | Reproducible conversion derivation tied to concrete instructions and data flow. |
| 3. Publisher | Trace how the converted value enters the ARM register publication structure; account for callee-saved bases and every dispatcher gap/decrement width. | Publisher path, backing offsets, and gap/decrement accounting. |
| 4. FC04 response | Trace the exact dispatcher case and response word(s), including family-specific address reuse. | Dispatcher case, response word positions, and explicit family boundary. |
| 5. Positive controls | The same dispatcher walk must recover known-live I153 and I170, with correct numbering after gaps. | Positive-control recovery record for both anchors. |
| 6. Independent check | Re-run the decode adversarially and cross-check on live hardware. For a writable semantic, preserve the named action, target family, raw integer before/after words, behavior, and restoration; for a read-only semantic, preserve the simultaneous raw-to-peer observation. | Independent decode result and the complete live observation record actually captured. |

The required direction is **producer → conversion → publisher → FC04 response**. Reverse naming from a response slot alone can prove structure but not physical meaning.

This table classifies evidence artifacts only. Which grade those artifacts earn is determined solely by the [evidence-grade legend](../README.md#evidence-grade-legend). Completing a stage does not award a grade, substitute for a legend requirement, or create an exception.

## ESP32 WLAN dongle local listener

Issue `eg4-x00j` is the durable evidence record for the 2026-08-13 physical dump and
decompilation. The complete 8 MiB flash is intentionally not committed: its NVS partition
may contain network credentials. The hashes below identify the analyzed bytes without
publishing that state.

### First attached unit: factory `V1.1`

| Claim | Evidence | Grade |
|---|---|---|
| The attached unit is an ESP32-D0WD-V3 revision 3.1 with 8 MiB flash. | `esptool` ROM identification and flash ID in `eg4-x00j`; full-flash SHA-256 `3a47027dc6fc19eaf9987415e59366caf94b69c30a089db40794d32765346fdc`. | `asserted-unverified` (issue `eg4-x00j`; the raw hardware transcript is summarized there but not committed) |
| The only application is factory `V1.1`, built 2025-07-17; both 2 MiB OTA slots are erased. | Partition table: factory `0x40000`, OTA0 `0x240000`, OTA1 `0x440000`; extracted 922,544-byte app SHA-256 `bf557329002703d3bf73cbe2561a5a33632cfa5c2d9cbeaa922143aa8ae1cc18`. | `firmware-proven` (WLAN factory `V1.1`; issue `eg4-x00j`) |
| `V1.1` contains a valid plaintext local-server config for TCP port 8000, two clients, name `data server`. | DROM `0x3f417258`; server initializer `FUN_400db958` copies the config, calls create `FUN_400dcf24`, and starts it through `FUN_400dcfa8`. | `firmware-proven` (WLAN factory `V1.1`; issue `eg4-x00j`) |
| The local handler can return values and accept reads/writes: it dispatches `C1` heartbeat, `C2` data, `C3` get-parameter, and `C4` set-parameter frames. | `FUN_400db764`; the `C3` branch parses the start/end codes and calls `FUN_400de614`, while `C4` parses and calls `FUN_400de7cc`. | `firmware-proven` (WLAN factory `V1.1`; issue `eg4-x00j`) |
| Ethernet never starts that listener, while Wi-Fi does. | Network selector `FUN_400da978` calls Wi-Fi `FUN_400de0f4` when parameter `0x0f == 1`, otherwise Ethernet `FUN_400da798`. Wi-Fi creates `wifi_task`, calls `FUN_400db958`, then returns. Ethernet creates `eth_task` and returns without a call to `FUN_400db958`. | `firmware-proven` (WLAN factory `V1.1`; issue `eg4-x00j`) |

The important boundary is **implementation versus reachability**: `V1.1` has the complete
plaintext request/response server, but the Ethernet initialization path does not make it
reachable. The absence of a listener on a running Ethernet unit therefore does not show
that local protocol support was removed.

### Downloaded `WL_LINK_V1_2` and the local-listener patch

A second physical unit, recorded in issue `eg4-gzol`, closes the provenance gap between
the downloaded `V1.2` artifact and shipped hardware:

| Claim | Evidence | Grade |
|---|---|---|
| The second unit is an ESP32-D0WD-V3 revision 3.1 with 8 MiB flash. | `esptool` ROM identification and flash ID in `eg4-gzol`; full-flash SHA-256 `c280cbc43e3f6c6c16306f5410a5a9c641312d2cdade745a9eeae74b453a579f`. | `asserted-unverified` (issue `eg4-gzol`; the raw hardware transcript is summarized there but not committed) |
| Its only application is factory `V1.2`, built 2025-10-22; both 2 MiB OTA slots are erased. | Partition table: factory `0x40000`, OTA0 `0x240000`, OTA1 `0x440000`; both OTA regions contain only `0xff`. The extracted 947,680-byte factory app has SHA-256 `325e12b0b9b4a51fc050fb5e17ab79a97d6bd3ff7301628ecd15e9e74d2fec0f`. | `firmware-proven` (WLAN factory `V1.2`; issue `eg4-gzol`) |
| The shipped factory app is byte-identical to the previously downloaded official `WL_LINK_V1_2.bin`. | Full-file `cmp` equality and the same SHA-256 `325e12b0…fec0f`. | `firmware-proven` (WLAN factory/downloaded `V1.2`; issue `eg4-gzol`) |
| As captured from the factory, the physical unit did **not** contain the local-listener patch. | Its original app equalled official `WL_LINK_V1_2.bin` and differed from `WL_LINK_V1_2_eth_local_listen.bin`, SHA-256 `ab67fc3114298606830e79b3b0c6a9acb803aac11498c51b90b999e38a392255`. The later physical write is recorded below. | `firmware-proven` (original WLAN factory `V1.2` capture; issue `eg4-gzol`) |

Because the factory application and downloaded image are identical, the following
decompilation findings apply directly to the second physical unit; this is binary
identity, not a transfer of conclusions between merely similar builds.

| Artifact or claim | Evidence | Grade |
|---|---|---|
| Official `WL_LINK_V1_2.bin`, SHA-256 `325e12b0b9b4a51fc050fb5e17ab79a97d6bd3ff7301628ecd15e9e74d2fec0f`, retains a port-8000 server but moves it to TLS-PSK. | Valid config at DROM `0x3f41a644`; local initializer `FUN_400dbf88`; TLS/server strings and PSK setup in that call path. | `firmware-proven` (WLAN `V1.2`; issue `eg4-x00j`) |
| Official `V1.2` repeats the Ethernet omission. | Selector `FUN_400dae90`; Wi-Fi `FUN_400ded0c` reaches `FUN_400dbf88`, while Ethernet `FUN_400dacb0` creates `eth_task` and returns. | `firmware-proven` (WLAN `V1.2`; issue `eg4-x00j`) |
| `WL_LINK_V1_2_eth_local_listen.bin`, SHA-256 `ab67fc3114298606830e79b3b0c6a9acb803aac11498c51b90b999e38a392255`, changes the jump at `0x400dae74` from the Ethernet return to the existing Wi-Fi epilogue at `0x400df0a7`, which calls `FUN_400dbf88`. Its ESP checksum and appended image hash validate. | Byte-level comparison and Xtensa disassembly recorded in `eg4-x00j`. | `asserted-unverified` (issue `eg4-x00j`; locally produced artifact, not vendor firmware) |
| That patched image was written to the second physical unit's factory partition at `0x40000`, without rewriting NVS, the partition table, or either OTA slot. The independent 947,680-byte readback is byte-identical to the patch. | Pre-write readback matched official `V1.2` SHA-256 `325e12b0…fec0f`; `esptool` verified the write hash; post-write readback matched patched SHA-256 `ab67fc31…922551`; eFuse summary showed secure boot and flash encryption disabled. | `asserted-unverified` (physical write/readback transcript summarized in issue `eg4-vr06`; the grade legend has no flash-storage grade) |
| The patched `V1.2` should start the existing TLS-PSK port-8000 server after `eth_task` starts. | Direct consequence of the changed control-flow edge and the decompiled target epilogue. It has not been booted or probed on hardware. | `inferred` from the preceding firmware control flow; falsify by booting it and capturing the port/listener result |

The adapter's RTS line did not reboot this unit after the verified write, so it remained in
the ROM flasher stub. A physical power cycle without BOOT/IO0 asserted is required before
the runtime claim can be tested. Exact flash readback proves storage only; it does not
prove that the image boots or that TCP port 8000 listens.

Do not substitute `E_V2_12_local_8000.bin` on this hardware. That image targets ESP32-C3;
the attached WLAN unit and both `WL_LINK_V1_2` artifacts target classic ESP32. The similar
filenames conceal incompatible instruction sets. `firmware-proven` (each image header and
chip ID; issue `eg4-x00j`).

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
