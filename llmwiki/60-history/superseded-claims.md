---
canonical-for:
  - "Claims that were confidently documented, believed, acted upon, and are false"
  - "The mechanism by which each false claim became load-bearing"
sources:
  - memory/queue-cleanup-2026-07-26.md
  - memory/issue-476-green-mode-bit14.md
  - memory/firmware-re-framing-and-word-order.md
  - memory/issue-258-battery-rr-reg96-unreliable.md
  - memory/maintainability-findings-and-live-bugs.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
  - PR #557 (documentation-defect corrections)
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
drift — wrong paths, stale counts, wrong polling defaults — is corrected in the documents
themselves by PR #557 and is not repeated here.

## Index

| # | Claim | Reality | Grade of the reality | Damage done before it was caught |
|---|---|---|---|---|
| S1 | Unique IDs carry a data-type segment | Never implemented; the real forms are owned by [`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md) | `verified-against-code` (see owner) | A test fixture was written to match the doc, then production matcher code was written to satisfy the fixture |
| S2 | Register 110 green/off-grid mode is **bit 8** (annotated `# verified`) | Bit **14** | `hardware-toggle-proven` | Off-Grid switch silently did nothing in LOCAL/HYBRID; the wrong write was firmware-ACKed, so nothing logged (#476, tail of #194) |
| S3 | Register 110 "take load together" is **bit 5** | Bit **10** | `hardware-toggle-proven` | Propagated inside an otherwise-trusted correction note; the upper-bit table around a real fix was stale |
| S4 | The committed firmware reverse-engineering artefacts are usable evidence | Both trees are invalid output; one still lacks its warning | `verified-against-code` | Register names "from firmware" were actually copied from pylxpweb; conclusions about DSP structure were byte-order artefacts |
| S5 | `# verified` in a register table means a toggle was observed | It has meant "the names matched" | `asserted-unverified` | The direct cause of S2 |
| S6 | There is a readable extra battery slot beyond the protocol ceiling | No such slot; the ceiling is a protocol limit (graded by [`40-hardware/registers.md`](../40-hardware/registers.md)) | see owner | A "dedicated 5th slot" commit shipped, was proved wrong, and was reverted |
| S7 | `maxChgCurr` is scaled 10× wrong | Same physical amps, different raw units | `asserted-unverified` | A prior session "fixed" it into a 600 A reading; two independent reviewers then re-raised it |

---

## S1 — The unique-ID format that never existed

**Claimed:** `unique_id = f"{serial}_{data_type}_{sensor_key}"`, and
`…_{batteryKey}` for batteries — in `docs/claude/FINAL_VALIDATION_REPORT.md` and, for a
long time, in the repo `CLAUDE.md`.

**Reality:** the emitted forms contain no data-type segment, and no Python in the repo's
history ever emitted one — `asserted-unverified`
(`memory/queue-cleanup-2026-07-26.md`). The authoritative table of what the code actually
emits is owned by
[`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md)
and is deliberately **not** reproduced here: this is the one fact whose duplication caused
the defect below, so the record of the defect must not become a fourth copy of it.

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

**Reality:** bit **14**. `hardware-toggle-proven` — a cloud `enable_green_mode` toggle on an
18kPV moved register 110 raw `1056 → 17440`, i.e. XOR `0x4000`, and the state was
restored (`memory/issue-476-green-mode-bit14.md`; issue #476). That the integration now
decodes bit 14 is `verified-against-code` (`switch.py` → the off-grid switch's
`is_on` path); the in-tree comment repeating the hardware claim is not itself evidence.

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
- A write attempt plus an ACK establishes *nothing*. Neither does a readback: a delta
  test (write → read back → restore) proves **storage and transport only**. Establishing
  what a bit *means* additionally requires a named vendor/UI action and an independent
  observation that the intended physical state changed — the ladder in
  [README](../README.md#named-refinement-the-register-annotation-ladder).

**Do not extend this to bit 8's semantics.** What bit 8 actually controls is unknown; a
later changelog over-claimed about it a third time. See C5 in
[open-contradictions.md](open-contradictions.md).

---

## S3 — Register 110 "take load together": bit 5 → bit 10

**Claimed:** the upper-bit table circulated alongside the #476 correction placed "take
load together" at register 110 **bit 5**.

**Reality:** bit **10**. `hardware-toggle-proven` — a toggle moved raw `1056 ↔ 32` while bit 5
stayed unchanged (pylxpweb `constants/registers.py`; `memory/issue-476-green-mode-bit14.md`).

**The trap:** the #476 note is trustworthy *for the claim it proved* — the bit-14
toggle — and stale for the surrounding table it also carried. A note that earns
credibility by being right about one hard-won fact will smuggle its unproven neighbours
along with it.

Other register-110 positions the same source records as **refuted** — historical
mappings now known false, with no replacement semantic established (all `asserted-unverified` here;
pylxpweb `constants/registers.py`, and see [`40-hardware/registers.md`](../40-hardware/registers.md)):

| Bit | Historical claim | Present state |
|---|---|---|
| 5 | take load together | `refuted`; no replacement semantic |
| 6 | buzzer | `refuted`; no replacement semantic |
| 8 | Green Mode | `refuted`. The wrong write was firmware-ACKed and did **not** control Green Mode; what it does instead is unestablished (see C5) |
| 9 | ECO | `refuted`; no replacement semantic |

The authoritative current bit table is owned by
[`40-hardware/registers.md`](../40-hardware/registers.md), not this page.

---

## S4 — The firmware reverse-engineering artefacts

**Claimed:** the generated trees under `docs/reference/` document the firmware, and
`REGISTER_MAP_FROM_FIRMWARE.md` establishes register names from decoded firmware.

**Reality:** two blockers invalidated every artefact in both trees —
`asserted-unverified` for the blockers (`memory/firmware-re-framing-and-word-order.md`):

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
`asserted-unverified` (`memory/firmware-re-framing-and-word-order.md`).

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
agreement, not an observed toggle. `asserted-unverified` (issue #476; `memory/issue-476-green-mode-bit14.md`). It is the
direct cause of S2, and the same conflation was re-committed *in the comment documenting
the fix*.

**What replaces it:** the register-annotation ladder, which is defined once in
[README](../README.md#named-refinement-the-register-annotation-ladder) and applied per row
by [`40-hardware/registers.md`](../40-hardware/registers.md). It ranks a live toggle above a
canonical definition plus an independent capture, above a canonical definition alone, above
a vendor table — and makes anything below the top two rungs write-inaccessible.
`asserted-unverified` (`docs/audits/2026-08-02-register-race-performance-audit.md`).

---

## S6 — The fifth battery slot

**Claimed:** a dedicated 5th battery slot is readable; a commit was written to read it.

**Reality:** the protocol exposes a fixed, small number of battery slots and no more; the
commit was proved wrong and reverted. The other community integration
(`ant0nkr/luxpower-ha-integration`) reads batteries against the same ceiling, so the limit
is the protocol, not our code. The register-level fact — how many slots, at which addresses,
and its evidence grade — is owned by
[`40-hardware/registers.md`](../40-hardware/registers.md).
`asserted-unverified` for the history (`memory/issue-258-battery-rr-reg96-unreliable.md`).

**Secondary trap from the same investigation:** "duplicate serials in the accumulator
dump" was a **logging artefact** — the dump decoded only 14 of the 15 serial characters.
Never diagnose serial collisions from that debug line.

---

## S7 — The `maxChgCurr` 10× bug that was not

**Claimed:** the cloud and Modbus scale tables for `maxChgCurr` disagree by 10×, so one
of them is wrong.

**Reality:** cloud `maxChgCurr` raw 6000 is in 0.01 A units (→ 60.0 A); Modbus register
81 raw 600 is in 0.1 A units (→ 60.0 A). **Same physical amps, different raw units.**
`asserted-unverified` (`memory/maintainability-findings-and-live-bugs.md`).

Two independent reviewers called it a 10× bug, and a prior session had already "fixed"
it into a 600 A reading. Only validation against real payloads settled it.

**The rule this produces:** two scale tables disagreeing is necessary but not sufficient
evidence of a bug. **Compare resulting physical values, never scale symbols.**
