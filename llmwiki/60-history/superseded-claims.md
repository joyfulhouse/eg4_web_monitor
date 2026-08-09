---
canonical-for:
  - "Claims that were confidently documented, believed, acted upon, and are false"
  - "The mechanism by which each false claim became load-bearing"
sources:
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - /tmp/llmwiki-research/firmware-re-and-registers.md
  - /tmp/llmwiki-research/docs-accuracy-audit.md
  - git ls-files / diff at 9f6d6e2
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - open-contradictions.md
  - bug-postmortems.md
---

# Superseded claims

Statements this project once documented with confidence that are **false**. Each is
kept, not deleted, because in every case the false claim did work before it was caught:
it justified code, shaped a review, or invalidated an analysis.

Scope: claims that entered the *knowledge base* and were acted upon. Plain documentation
drift — wrong paths, stale counts, wrong polling defaults — is catalogued as 39 verified
defects in `docs-accuracy-audit.md` and is being corrected in the documents themselves;
it is not repeated here.

## Index

| # | Claim | Reality | Grade of the reality | Damage done before it was caught |
|---|---|---|---|---|
| S1 | Unique IDs are `{serial}_{data_type}_{sensor_key}` | Never implemented; device IDs are `{serial}_{sensor_key}` | `verified-against-code` | A test fixture was written to match the doc, then production matcher code was written to satisfy the fixture |
| S2 | Register 110 green/off-grid mode is **bit 8** (annotated `# verified`) | Bit **14** | `hardware-proven` | Off-Grid switch silently did nothing in LOCAL/HYBRID; the wrong write was firmware-ACKed, so nothing logged (#476, tail of #194) |
| S3 | Register 110 "take load together" is **bit 5** | Bit **10** | `hardware-proven` | Propagated inside an otherwise-trusted correction note; the upper-bit table around a real fix was stale |
| S4 | The committed firmware reverse-engineering artefacts are usable evidence | Both trees are invalid output; one still lacks its warning | `verified-against-code` | Register names "from firmware" were actually copied from pylxpweb; conclusions about DSP structure were byte-order artefacts |
| S5 | `# verified` in a register table means a toggle was observed | It has meant "the names matched" | `asserted-unverified` | The direct cause of S2 |
| S6 | There is a readable 5th battery slot | The protocol ceiling is 4 slots | `asserted-unverified` (5/6-slot probes return empty) | A "dedicated 5th slot" commit shipped, was proved wrong, and was reverted |
| S7 | `maxChgCurr` is scaled 10× wrong | Same physical amps, different raw units | `asserted-unverified` | A prior session "fixed" it into a 600 A reading; two independent reviewers then re-raised it |

---

## S1 — The unique-ID format that never existed

**Claimed:** `unique_id = f"{serial}_{data_type}_{sensor_key}"`, and
`…_{batteryKey}` for batteries — in `docs/claude/FINAL_VALIDATION_REPORT.md` and, for a
long time, in the repo `CLAUDE.md`.

**Reality**, `verified-against-code` at 9f6d6e2:

| Scope | Emitted form | Site |
|---|---|---|
| Device | `{serial}_{sensor_key}` | `base_entity.py:457` |
| Battery | `{serial}_{battery_key}_{sensor_key}` | `base_entity.py:565` |
| Battery bank | `{serial}_battery_bank_{sensor_key}` | `base_entity.py:660` |
| Station | `station_{plant_id}_{sensor_key}` | `sensor.py:829` |

No Python in the repo's history emits a data-type segment — `asserted-unverified`
(corpus §4 C1, from `memory/queue-cleanup-2026-07-26.md`).

**Why it matters more than a wrong string.** The failure chain was:

1. The format was documented but never implemented.
2. A **test fixture was written to match the documentation**.
3. **Production code — a registry-cleanup matcher — was then designed to satisfy that
   fixture**, defending against an ID shape that does not exist.
4. The suite passed at every step. A green test proved only that the code matched the
   fixture, and the fixture encoded the fiction.

**The rule this produces:** a passing test is evidence about the code's contract, never
about the world. When a fixture is the only support for a behaviour, find the
production emission site before writing code that consumes it.

**Current state:** repo `CLAUDE.md` carries the correction; the stale claim survives in
`docs/claude/FINAL_VALIDATION_REPORT.md`, which is why C1 remains open in
[open-contradictions.md](open-contradictions.md). Never lift an ID format from that file.

---

## S2 — Register 110 green mode: bit 8 → bit 14

**Claimed:** pylxpweb's 18kPV / `EG4_HYBRID` table mapped `FUNC_GREEN_EN` to register
110 **bit 8**, annotated `# verified`.

**Reality:** bit **14**. `hardware-proven` — a cloud `enable_green_mode` toggle on an
18kPV moved register 110 raw `1056 → 17440`, i.e. XOR `0x4000`, and the state was
restored (corpus §4 C5 and `firmware-re-and-registers.md` §6.5, both from
`memory/issue-476-green-mode-bit14.md`). The bit-14 decode is documented in-tree at
`switch.py:1167` — `verified-against-code`.

**Why it was invisible.** Writing bit 8 *succeeds*. The firmware ACKs a
wrong-but-writable bit, so:

- no exception is raised,
- no cloud fallback triggers,
- nothing is logged above DEBUG,
- and **readback cannot detect it** — writing bit 14 sets bit 14 and reads back true
  whether or not green mode moved.

The user-visible symptom was an Off-Grid switch that did nothing in HYBRID/LOCAL. It was
also the never-root-caused tail of #194.

**The rules this produces:**

- Gating is the only mitigation for an unproven bit mapping. You cannot test your way
  out of a wrong address on a writable register.
- A write attempt plus an ACK establishes *nothing* about targeting. Only a delta test
  — write, read back the raw register, restore — does.

**Do not extend this to bit 8's semantics.** What bit 8 actually controls is unknown; a
later changelog over-claimed about it a third time. See C5 in
[open-contradictions.md](open-contradictions.md).

---

## S3 — Register 110 "take load together": bit 5 → bit 10

**Claimed:** the upper-bit table circulated alongside the #476 correction placed "take
load together" at register 110 **bit 5**.

**Reality:** bit **10**. `hardware-proven` — a toggle moved raw `1056 ↔ 32` while bit 5
stayed unchanged (source: `firmware-re-and-registers.md` §6.5, citing pylxpweb
`constants/registers.py`).

**The trap:** the #476 note is trustworthy *for the claim it proved* — the bit-14
toggle — and stale for the surrounding table it also carried. A note that earns
credibility by being right about one hard-won fact will smuggle its unproven neighbours
along with it.

Other register-110 positions the same source records as **refuted** — historical
mappings now known false, with no replacement semantic established (all
`asserted-unverified` here; source: `firmware-re-and-registers.md` §6.5):

| Bit | Historical claim | Present state |
|---|---|---|
| 5 | take load together | refuted; unknown |
| 6 | buzzer | refuted; unknown |
| 8 | Green Mode | refuted; unknown. Writing it affected the PVCT-sample region |
| 9 | ECO | refuted; unknown |

The authoritative current bit table is owned by `40-hardware/registers.md`, not this page.

---

## S4 — The firmware reverse-engineering artefacts

**Claimed:** the generated trees under `docs/reference/` document the firmware, and
`REGISTER_MAP_FROM_FIRMWARE.md` establishes register names from decoded firmware.

**Reality:** two blockers invalidated every artefact in both trees —
`asserted-unverified` for the blockers (source: `memory/firmware-re-framing-and-word-order.md`
via `firmware-re-and-registers.md` §2, §3):

1. **OTA framing was never stripped.** The images still carried transport framing — a
   1-byte prefix and 2 check bytes per 771-byte block — so instruction alignment is
   wrong throughout. The uniform block rule additionally holds only to about `0xF100`,
   so a fixed-period strip corrupts the tail while the image start still looks perfect.
2. **The C28x images were read little-endian.** TI C28x serialises each 16-bit
   instruction word **MSB-first**. Read the wrong way it looks like data — which is why
   earlier passes concluded "no functions".

The invalidity is visible in the output itself: zero-function decompilations, empty
Modbus name/function-code/CRC sections, noise-like opcode statistics, and — decisively —
`REGISTER_MAP_FROM_FIRMWARE.md` admitting its input register names were cross-referenced
from pylxpweb and live dumps rather than decoded.

**The duplicate trees**, `verified-against-code` at 9f6d6e2:

| Path | Tracked files | `00_SUMMARY.md` |
|---|---|---|
| `docs/reference/firmware/re/` | 10 | Carries "⛔ These artifacts are INVALID — do not cite them (2026-08-08)" |
| `docs/reference/firmware_re/` | 10, identical filenames | **No banner** |

Filename sets are identical and the only content difference found between the two
summaries is that banner block. The trees entered git together; the original scripts
(`scripts/firmware_re_analysis.py`, `scripts/extract_firmware_registers.py`) target the
**root sibling**, which is the one still missing the warning —
`asserted-unverified` (source: `firmware-re-and-registers.md` §2.1).

**Working rule:** neither tree's generated artefacts are firmware evidence. Treat
`docs/reference/firmware/re/` as the tombstone (it warns) and
`docs/reference/firmware_re/` as a stale duplicate of the same invalid output. The live
probe JSON files referenced from the summary remain usable **as hardware observations
only**. The current worked analyses are `FIRMWARE_ACQUISITION.md`,
`OFFGRID_GENERATOR_REGISTERS.md`, `OFFGRID_EPS_REGISTERS.md`, `HYBRID_EPS_REGISTERS.md`.

---

## S5 — What `# verified` meant

**Claimed:** a `# verified` annotation in a register table means the mapping was proven.

**Reality:** in this project it has meant "the names matched" — a cross-reference
agreement, not an observed toggle. `asserted-unverified` (corpus §2.12). It is the
direct cause of S2, and the same conflation was re-committed *in the comment documenting
the fix*.

**The evidence hierarchy that replaces it**, strongest first (source: the 2026-08-02
audit via corpus §2.12):

1. A live named-control or UI action correlated to raw before/after values on the target
   family, with restoration.
2. A canonical pylxpweb definition **plus** an independent hardware capture.
3. A canonical definition alone — read-only diagnostics only.
4. A vendor or third-party table — a family-specific hypothesis, nothing more.

The contract harness is valuable but **not independent**: it resolves against the same
pylxpweb tables, so it catches internal drift and cannot prove an address is correct on
hardware.

---

## S6 — The fifth battery slot

**Claimed:** a dedicated 5th battery slot is readable; a commit was written to read it.

**Reality:** the inverter dongle Modbus protocol exposes at most **4** battery slots;
5- and 6-slot probe reads return empty. The commit was proved wrong and reverted. The
other community integration (`ant0nkr/luxpower-ha-integration`) reads batteries with
the same hard 4-block ceiling, so the limit is the protocol, not our code.
`asserted-unverified` (corpus §2.10, from `memory/issue-258-battery-rr-reg96-unreliable.md`).

**Secondary trap from the same investigation:** "duplicate serials in the accumulator
dump" was a **logging artefact** — the dump decoded only 14 of the 15 serial characters.
Never diagnose serial collisions from that debug line.

---

## S7 — The `maxChgCurr` 10× bug that was not

**Claimed:** the cloud and Modbus scale tables for `maxChgCurr` disagree by 10×, so one
of them is wrong.

**Reality:** cloud `maxChgCurr` raw 6000 is in 0.01 A units (→ 60.0 A); Modbus register
81 raw 600 is in 0.1 A units (→ 60.0 A). **Same physical amps, different raw units.**
`asserted-unverified` (corpus §2.5, from `memory/maintainability-findings-and-live-bugs.md`).

Two independent reviewers called it a 10× bug, and a prior session had already "fixed"
it into a 600 A reading. Only validation against real payloads settled it.

**The rule this produces:** two scale tables disagreeing is necessary but not sufficient
evidence of a bug. **Compare resulting physical values, never scale symbols.**
