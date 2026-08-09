---
canonical-for: inverter-and-gridboss-register-ground-truth
sources:
  - /tmp/llmwiki-research/firmware-re-and-registers.md
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - docs/DATA_MAPPING.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Register ground truth

> **Only 45 of 335 current register-semantic claims are actually proven: 27 are `firmware-proven` and 18 are `hardware-toggle-proven`. The other 290 are not proven: 155 are `portal-correlated` and 135 are `lineage-inferred`.**

“Canonical,” a plausible value, a passing test, a Modbus ACK, or a confident source comment is not proof. Grades apply to the stated semantic on the stated device-family scope; the same address can have a different meaning and grade on another family.

## Evidence grades and accounting

| Evidence grade | Meaning | Current claim count |
|---|---|---:|
| `firmware-proven` | Correctly reconstructed and validated firmware directly establishes the producer, conversion, publication, or response behavior. | 27 |
| `hardware-toggle-proven` | A controlled named toggle or hardware observation produced the raw delta, with readback and restoration where applicable. | 18 |
| `portal-correlated` | A register value or delta correlates with a portal/API field, without controlled toggle proof or trustworthy firmware proof. | 155 |
| `lineage-inferred` | The mapping comes from a protocol table, upstream/adjacent family, implementation metadata, or an internally consistent map without direct proof on the stated family. | 135 |
| **Current total** | Counting unit: one semantic claim keyed by family scope, FC/type, base register, and optional bit. A U32 pair counts once at its base; indexed fields count individually. | **335** |
| `refuted` | Historical claims contradicted by stronger evidence. These are represented separately and excluded from the current total. | 14 |
| `asserted-unverified` | Candidate, opaque, reserved, or unresolved semantics retained to prevent accidental promotion. They are excluded from the current total and no exhaustive count is claimed. | — |

The ledger groups adjacent registers for readability; the counts expand indexed fields, family-specific meanings, and mixed-evidence bits according to the counting rule above. The 45 proven claims are only 13.4% of the 335 current claims.

## Notation and safety boundary

| Prefix | Function | Access | Evidence grade |
|---|---|---|---|
| `I` | Inverter input register, FC04 | Read-only | `firmware-proven` for access class; each semantic is graded below |
| `H` | Inverter holding register, FC03 to read | Potentially writable by FC06/FC16 or portal controls | `firmware-proven` for access class; each semantic is graded below |
| `GB-I` | GridBOSS input register, FC04/device type 50 | Read-only | `firmware-proven` for access class; each semantic is graded below |
| `GB-H` | GridBOSS holding register | Potentially writable | `firmware-proven` for access class; each semantic is graded below |

Unless a row explicitly says signed, the current canonical decoder treats it as unsigned. U32 values use the lower-address word as low word: `(high << 16) | low`.

## Corrections that must not regress

| Current mapping or correction | Family scope | Evidence grade | Qualification |
|---|---|---|---|
| H110 bit 14 is Green/Off-Grid Mode. | 18kPV / `EG4_HYBRID` | `hardware-toggle-proven` | Raw 1056 ↔ 17440, XOR `0x4000`, named cloud toggle in lockstep, restored. Off-grid-family applicability remains `lineage-inferred`. |
| Historic H110 bit 8 = Green Mode is false. | Historic hybrid table | `refuted` | A wrong-but-writable b8 write was ACKed and affected the PVCT-sample region; it did not prove Green Mode. |
| H110 bit 10 is Take Load Together. | Tested hardware | `hardware-toggle-proven` | Raw 1056 ↔ 32 while b5 remained unchanged. |
| Historic H110 bit 5 = Take Load Together is false. | Historic table | `refuted` | The later raw toggle pins b10. |
| H206 is peak-shaving period-1 power in **0.1 kW** units. | `EG4_HYBRID` | `hardware-toggle-proven` | Raw 41 = 4.1 kW and raw 120 = 12 kW. |
| H160/H161 are AC-charge start/end SOC, respectively. | Off-grid plus hybrid read scope | `portal-correlated` | H160 is 0–90%; H161 is writable only on the off-grid path and read-only/inert on tested grid-tied firmware. An off-grid local H161 write remains unverified. |
| H67 is the AC-charge stop-SOC control only on grid-tied families. | Grid-tied | `portal-correlated` | Off-grid firmware rejects it; H160/H161 are the off-grid-family SOC controls. Value 101 is used as “never stop/top-balance” where supported. |
| I67 raw `0x007f` means no battery-temperature reading. | All canonical families | `portal-correlated` | This is sentinel value 127 **in I67**, not input register I127 and not 127 °C. |
| I60-I61 are the inverter fault word and I62-I63 are the warning word. | All; surfaced in LOCAL/HYBRID | `lineage-inferred` | Each is a little-word-order U32 bitmap. The per-bit catalogue is inherited, not fault-injection-proven. |
| I171 is inverter-served `Eload_day`; I172-I173 are inverter-served `Eload_all`. | All | `portal-correlated` | They match per-inverter portal usage and are not whole-home consumption. |
| I123 is a nominal ~1 Hz 16-bit boot/ARM-initialization counter, not generator power. | 12000XP / off-grid | `firmware-proven` | It wraps modulo 65,536. “Exactly 1.000 Hz” and “the increment is the only writer” are overclaims because initialization also writes it. |
| I123 is genuine multiplexed GEN-port power. | 18kPV/FlexBOSS hybrid | `firmware-proven` | `low16(int16[DSP_A] - int16[DSP_B])`; two inverters summed within 0.13% of GridBOSS AC-Couple-1. Never suppress this hybrid meaning. |
| I124 is status/metadata and I125-I126 are one U32 status word. | 12000XP / off-grid | `firmware-proven` | They are not generator energy. Individual bit meanings remain unknown. |
| GB-H20 packs four smart-port modes in 2-bit fields. | GridBOSS | `portal-correlated` | Bits 0–1/2–3/4–5/6–7 select ports 1–4; 0 unused, 1 smart load, 2 AC couple. |
| GB-I105-I108 are not the smart-port status source. | GridBOSS | `refuted` | They are words within the GB-I104-I119 AC-couple lifetime-energy block. GB-H20 is the mode source. |
| Peak shaving uses H179 b7 plus H206/H207/H208, H218/H219, and H232. | `EG4_HYBRID` | `portal-correlated` | H179 b7 and H206 are individually `hardware-toggle-proven`; the compound row takes the weaker grade of its SOC/voltage/set-2 fields. |
| Historic peak-shaving enable/power mappings at H21/H231 are wrong. | Tested EG4 hybrid | `refuted` | Enable is H179 b7. H231 is an unknown field with odd→even quantization, not a high word; H206 and H232 are the period-1/period-2 power registers. |

## Inverter input-register ledger

| Register(s) | Established or bounded semantic | Units / scale | Signedness | Family scope | Evidence grade | Qualification |
|---|---|---|---|---|---|---|
| I0 | Device status / operating-state code | raw enum | unsigned | all | `lineage-inferred` | Vendor Table 9 lineage; live anomalies are listed below. |
| I1/I2/I3 | PV1/PV2/PV3 voltage | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I4 | Battery voltage | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I5 | SOC low byte / SOH high byte | 1% per byte | packed unsigned bytes | all | `lineage-inferred` | Low/high-byte layout is inherited and implemented. |
| I7/I8/I9 | PV1/PV2/PV3 power | W | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I10/I11 | Battery charge/discharge power | W | unsigned | all; I11 entity off-grid-gated | `lineage-inferred` | Canonical implementation map only. |
| I12/I13/I14 | Grid R/S/T voltage | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I15 | Grid frequency | 0.01 Hz | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I16 | Inverter power | W | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I17 | Rectifier power, not grid power | W | unsigned | all | `portal-correlated` | On off-grid firmware the value resolves to the DSP power block. I17 plus I27 is only a candidate for off-grid generator power. |
| I18 | Inverter RMS current R/L1 | 0.01 A | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I19 | Power factor with special encoded-negative representation | 0.001 | unsigned encoded | all | `lineage-inferred` | Not a conventional S16 or percentage. |
| I20 | EPS R/aggregate voltage | 0.1 V | unsigned | off-grid and hybrid | `firmware-proven` | Decoded DSP field; hybrid live L1+L2 is consistent. |
| I21/I22 | Historic EPS S/T voltage labels | nominal 0.1 V | unsigned | observed US split-phase | `refuted` | Off-grid values are unrelated composites; hybrid values are coherent but physically unknown and absurd under the old scale. |
| I23 | EPS frequency | 0.01 Hz | unsigned | hybrid | `firmware-proven` | Producer and output path decoded. |
| I23 | EPS frequency | 0.01 Hz | unsigned | non-hybrid | `lineage-inferred` | Broader canonical definition is not independently proven. |
| I24 | EPS active power | wire W; internal deciwatts ÷10 | unsigned off-grid; signed hybrid source | off-grid and hybrid | `firmware-proven` | Producer, conversion, and emission decoded. |
| I25 | EPS apparent power | whole VA off-grid; computed and clamped on hybrid | unsigned output | off-grid and hybrid | `firmware-proven` | Hybrid formula is decoded; live accuracy is not yet independently validated. |
| I26/I27 | Export/import power | W | unsigned | all | `lineage-inferred` | I27 remains only a candidate in the off-grid generator-power search. |
| I28/I29/I30 | PV1/PV2/PV3 energy today | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I31 | Inverter output energy today, not PV yield | 0.1 kWh | unsigned | all | `portal-correlated` | Separate from portal PV yield. |
| I32 | AC/grid charge energy today, `Erec_day` | 0.1 kWh | unsigned | all | `lineage-inferred` | Historic load-energy alias is refuted. |
| I33/I34 | Battery charge/discharge energy today | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I35 | EPS energy today | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I36/I37 | Grid export/import energy today | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I38/I39 | Bus voltage 1/2 | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I40-I45 | PV1/PV2/PV3 lifetime energy, three U32 pairs | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I46-I47 | Inverter output energy lifetime | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Not lifetime PV yield. |
| I48-I49 | AC/grid charge energy lifetime, `Erec_all` | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Historic load-energy alias is refuted. |
| I50-I51 | Charge energy lifetime | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I52-I53 | Discharge energy lifetime | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I54-I55 | EPS lifetime energy | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I56-I57 | Grid export energy lifetime | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I58-I59 | Grid import energy lifetime | U32, 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I60-I61 | Inverter fault bitmap | U32 bits | unsigned | all; LOCAL/HYBRID sensor | `lineage-inferred` | Raw word location is canonical; individual names have no live fault injection. |
| I62-I63 | Inverter warning bitmap | U32 bits | unsigned | all; LOCAL/HYBRID sensor | `lineage-inferred` | Same evidence limit as the fault word. |
| I64 | Internal temperature | °C | signed two’s-complement | all | `lineage-inferred` | Cloud zero on some units is a source defect, not evidence against local I64. |
| I65/I66 | Radiator temperature 1/2 | °C | unsigned canonical | all | `lineage-inferred` | Canonical implementation map only. |
| I67 | Battery temperature; `0x007f` is no-reading sentinel | °C or sentinel | unsigned | all | `portal-correlated` | Do not expose raw 127 as a temperature. |
| I68 | Battery-control temperature | 0.1 °C | unsigned representation | all | `lineage-inferred` | Canonical implementation map only. |
| I69-I70 | Running time | U32 seconds | unsigned | all | `portal-correlated` | Unit is corroborated; reset behavior is unproven. |
| I72/I73/I74 | Direct PV1/PV2/PV3 current candidate | 0.01 A | unsigned | all | `asserted-unverified` | Live EG4 probes often return zero/garbage; the integration derives current from P/V. Excluded from the 335 count. |
| I75 | Inverter-measured battery current | 0.01 A | unsigned/raw direction encoding | all | `lineage-inferred` | Canonical implementation map only. |
| I77 bit 0 | AC source: 0 grid, 1 generator | bit | unsigned | all | `portal-correlated` | Bits 1–2 remain unexposed. |
| I80 | BMS communication/battery type, asserted 0 CAN / 1 RS485 | enum | unsigned | all | `lineage-inferred` | No direct family capture. |
| I81/I82 | BMS charge/discharge current limit | 0.1 A | unsigned | all | `lineage-inferred` | I81 scaling is described as empirical, not independently proven here. |
| I83/I84 | BMS charge-voltage reference / discharge cutoff | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I85-I94 | Opaque BMS status words | raw | unsigned | all | `asserted-unverified` | No per-word semantics. Excluded from the 335 count. |
| I95 | BMS permission/request: b0 charge, b1 discharge, b5 force charge | bits | unsigned | all | `portal-correlated` | Correlated to cloud booleans. |
| I96 | Battery parallel count | count | unsigned | all | `lineage-inferred` | Known unreliable with rotation/more than four batteries. |
| I97 | BMS-reported capacity | Ah | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I98 | BMS battery current | 0.1 A | signed | all | `lineage-inferred` | Canonical implementation map only. |
| I99/I100 | BMS fault/warning fallback when inverter I60-I63 is zero | enum | unsigned | all | `lineage-inferred` | Descriptions are explicitly provisional. |
| I101/I102 | Maximum/minimum cell voltage | 0.001 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I103/I104 | Maximum/minimum cell temperature | 0.1 °C | signed | all | `lineage-inferred` | Canonical implementation map only. |
| I105 | BMS update/status word; low-state bits and b4 dry contact asserted | bitfield | unsigned | all | `lineage-inferred` | Not GridBOSS smart-port status; this row is inverter scope. |
| I106 | BMS cycle count | cycles | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I107 | Inverter-sampled battery voltage | 0.1 V | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I108 | T1/BT board temperature | 0.1 °C | unsigned | all | `lineage-inferred` | Modbus-only in the current integration. |
| I109-I112 | Reserved T2–T5 temperature slots | nominal 0.1 °C | unsigned | all | `asserted-unverified` | No proven sensor assignments. Excluded from the 335 count. |
| I113 | Parallel config: b0-1 role, b2-3 phase, b8-15 unit | bitfield | unsigned | all | `lineage-inferred` | Phase-source comparison conflicts; decoder follows the current canonical table. |
| I121/I122 | Generator voltage/frequency | 0.1 V / 0.01 Hz | unsigned | 12000XP/off-grid | `firmware-proven` | Handler, DSP source, and parser decoded. |
| I121/I122 | Generator voltage/frequency | 0.1 V / 0.01 Hz | unsigned | other families | `lineage-inferred` | Only 12000XP is firmware-proven. |
| I123 | ARM initialization counter modulo 65,536 | nominal seconds/count | unsigned U16 | 12000XP/off-grid | `firmware-proven` | Not generator power. |
| I123 | Timer-structure field; exact writer/meaning unknown | counter-like | unsigned U16 | 6000XP/off-grid | `lineage-inferred` | Structural placement only; do not call it proven. |
| I123 | Multiplexed GEN-port power | W | signed operands, low-16 output | 18kPV/FlexBOSS hybrid | `firmware-proven` | Genuine family-specific generator-port power. |
| I124 | High DSP metadata byte plus low ARM status byte | raw status | unsigned U16 | 12000XP/off-grid | `firmware-proven` | Historic energy label refuted. |
| I125-I126 | One ARM-maintained U32 status word | raw status bits | unsigned | 12000XP/off-grid | `firmware-proven` | Written bit positions are known; meanings are not. |
| I124 | Generator daily energy | 0.1 kWh | unsigned | hybrid/LXP | `lineage-inferred` | Family-gated canonical definition. |
| I125-I126 | Generator lifetime energy | U32, 0.1 kWh | unsigned | hybrid/LXP | `lineage-inferred` | Family-gated canonical definition. |
| I127/I128 | EPS L1/L2 voltage | 0.1 V | unsigned | hybrid and off-grid | `portal-correlated` | Hybrid live values are coherent. |
| I129/I130 | EPS L1/L2 active power, combined backup-path legs | W | unsigned | off-grid | `firmware-proven` | Decoded U32 deciwatts ÷10; not only the EPS-load subset. |
| I129/I130 | EPS L1/L2 active power | W | unsigned | hybrid | `firmware-proven` | Hybrid producer path decoded. |
| I131/I132 | EPS L1/L2 apparent power | VA | unsigned U16 | off-grid | `firmware-proven` | Producer and response path decoded. |
| I131 | Sign-split directional DSP quantity; old apparent-power label invalid | 0.1 power quantity | signed source, magnitude output | hybrid | `refuted` | Structure is decoded; exact physical semantic remains unknown. |
| I132 | Thresholded persistent event counter; old apparent-power label invalid | count | unsigned U16 | hybrid | `refuted` | Firmware counter path decoded. |
| I133/I134 | EPS L1/L2 energy today | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I135-I138 | EPS L1/L2 lifetime energy, two U32 pairs | 0.1 kWh | unsigned | all | `lineage-inferred` | Canonical implementation map only. |
| I153 | AC-couple power | W | canonical unsigned; reverse-flow signedness unknown | all; trace on off-grid | `firmware-proven` | Producer is known. Signedness remains an open question. |
| I170 | Total output/load power | W | signed | all; entity off-grid-gated | `firmware-proven` | Known-live dispatcher anchor and portal/live correlation. |
| I171 | Inverter-served load energy today, `Eload_day` | 0.1 kWh | unsigned | all | `portal-correlated` | Not whole-home consumption. |
| I172-I173 | Inverter-served load energy lifetime, `Eload_all` | U32, 0.1 kWh | unsigned | all | `portal-correlated` | Not whole-home consumption. |
| I188/I189 | Unimplemented/reserved | — | — | 12000XP/off-grid | `firmware-proven` | Firmware proves absence from the dispatcher; not generator-power candidates. |
| I190/I191 | Inverter RMS current S/T | 0.01 A | unsigned | LXP three-phase | `lineage-inferred` | Three-phase canonical map. |
| I193/I194 | Inverter grid L1/L2 voltage; zero on tested US split-phase hybrid | 0.1 V | unsigned | nominal all; tested 18kPV/FlexBOSS zero | `portal-correlated` | Portability beyond tested units is unproven. |
| I195/I196 | Generator L1/L2 voltage | 0.1 V | unsigned | 12000XP/off-grid | `firmware-proven` | DSP source and handler decoded. |
| I195/I196 | Generator L1/L2 voltage | 0.1 V | unsigned | other families | `lineage-inferred` | Only 12000XP is firmware-proven. |
| I197-I204 | Per-leg inverter/rectifier/grid power block | W | unsigned canonical | 12000XP source block; broader names inherited | `firmware-proven` | Block provenance is proven; portable per-field names are weaker. Tested US hybrid block is zero. |
| I210 | Quick-charge remaining | asserted seconds | unsigned | supporting inverters | `lineage-inferred` | The current unit conflicts with other comments; requires wall-clock capture. |
| I217-I222 | PV4/PV5/PV6 voltage and power | 0.1 V / W | unsigned | models with detected strings | `lineage-inferred` | Indexed definitions are feature-gated, not hardware-proven. |
| I223-I231 | PV4/PV5/PV6 daily/lifetime yield blocks | 0.1 kWh; lifetime U32 | unsigned | models with detected strings | `lineage-inferred` | No cloud PV4–6 energy peers. |
| I232 | Smart-load power candidate | W | unsigned | nominal all | `asserted-unverified` | Never validated on off-grid hardware; do not ship as established. Excluded from the 335 count. |

### I0 operating-state decode

| Code(s) | Bounded meaning | Off-grid rule | Evidence grade | Qualification |
|---|---|---|---|---|
| `0x00`, `0x01`, `0x02` | Standby, Fault, Programming | no | `lineage-inferred` | Vendor Table 9. |
| `0x04`, `0x08`, `0x0c`, `0x10`, `0x14`, `0x28` | Documented grid/PV/battery flows | no | `lineage-inferred` | Vendor lineage; labels remain descriptive, not firmware proof. |
| `0x11` | Standby alias | no | `portal-correlated` | Live anomaly absent from Table 9. |
| `0x20` | AC → Battery, not necessarily utility-grid charging | no by threshold | `portal-correlated` | Live-correlated with AC-coupled PV and no utility grid. |
| `0x40`, `0x80`, `0x88`, `0xc0` | Documented off-grid states | yes | `lineage-inferred` | The actual implementation rule is `code >= 0x40`. |
| `0x60` | Off-grid AC-coupled charging | yes | `portal-correlated` | Live-correlated with main breaker off. |

## Inverter holding-register ledger

Every row is readable via FC03 but exists in a potentially writable configuration space.

| Register(s) | Established or bounded semantic | Units / scale | Family scope | Evidence grade | Qualification |
|---|---|---|---|---|---|
| H0-H1 | 32-bit model bitfield; rating in H0 low-byte b5-7 and FlexBOSS offset at H1 b8 | bitfield | inverters | `lineage-inferred` | Used with H19 for discovery. |
| H19 | Device-type code | raw code | inverter/MID/GridBOSS discovery | `portal-correlated` | Identity field correlated to model/device tables. |
| H21 | Function-enable bitmap | bits | lineage-wide; features gated | `lineage-inferred` | Not the peak-shaving enable source. Full asserted map remains inherited. |
| H64 | Legacy charge-power-percent command | % | all | `refuted` | Not the PV-charge power entity target; H74 is. |
| H65 | Discharge power limit | 0–100% | all | `lineage-inferred` | Canonical implementation map only. |
| H66 | AC charge power | raw ×100 W; UI kW | all | `portal-correlated` | Not percentage. |
| H67 | AC-charge stop SOC | %; 101 special where supported | grid-tied only | `portal-correlated` | Off-grid rejects it. |
| H68-H73 | AC-charge windows 1–3 start/end | packed time | control-capable | `portal-correlated` | Hour low byte, minute high byte. |
| H74 | Forced/PV-charge-priority power | raw ×100 W; UI kW | supported | `hardware-toggle-proven` | Not H64. |
| H75 | Forced-charge stop SOC | % | grid-tied controls | `lineage-inferred` | Canonical implementation map only. |
| H76-H81 | Forced-charge windows 1–3 | packed time | grid-tied | `portal-correlated` | Off-grid rejects/portal omits this control. |
| H82 | Forced-discharge power | raw ×100 W; UI kW | grid-tied | `hardware-toggle-proven` | Raw 25 = 2.5 kW. |
| H83 | Forced-discharge SOC stop | % | grid-tied | `hardware-toggle-proven` | Controlled live mapping. |
| H84-H89 | Forced-discharge windows 1–3 | packed time | grid-tied | `portal-correlated` | Off-grid applicability is unresolved/conflicted and remains gated. |
| H100 | EPS/off-grid voltage cutoff | 0.1 V | voltage-control devices | `lineage-inferred` | Canonical implementation map only. |
| H101/H102 | Charge/discharge current limits | A | all | `lineage-inferred` | “Confirmed” source wording lacks a reviewed capture. |
| H103 | Maximum grid sell-back power | raw ×100 W; cloud/UI kW | grid-tied | `portal-correlated` | Historic percentage interpretation is refuted. |
| H105 | On-grid discharge SOC cutoff | % | grid-tied | `lineage-inferred` | Canonical implementation map only. |
| H110 | System-function bitmap | bits | lineage-wide | `hardware-toggle-proven` | This word-level row reflects only proven b10/b14/b15 behavior; use the per-bit grades below for every other position. |
| H116 | Import threshold to start discharge | W | grid-tied; CT required | `portal-correlated` | Whole watts, not ×100 W. |
| H117 | Threshold to start charge | signed W | LOCAL/HYBRID | `asserted-unverified` | No cloud name or validated behavior; excluded from the 335 count. |
| H120 | Compound charge/discharge mode control | bitfields | supporting inverters | `lineage-inferred` | b0 half-hour; b1-3 AC-charge type; b4-5 discharge type; b6 on-grid EOD; b7 generator-charge. |
| H125 | EPS/off-grid discharge SOC cutoff | % | relevant devices | `lineage-inferred` | Canonical implementation map only. |
| H152-H157 | AC-first windows 1–3 | packed time | `EG4_OFFGRID`/SNA portal page | `portal-correlated` | Portal page provides the family bound. |
| H158/H159 | AC-charge start/end voltage | 0.1 V | supported | `hardware-toggle-proven` | Named write round trips establish the addresses. |
| H160 | AC-charge start SOC | %, 0–90 | off-grid plus hybrid read scope | `portal-correlated` | Family applicability comes from portal/control behavior. |
| H161 | AC-charge end SOC | %, dependency 20–100 | writable off-grid; read-only grid-tied | `portal-correlated` | Inert on tested grid-tied firmware; off-grid LOCAL write still unverified. |
| H169 | On-grid end-of-discharge voltage | 0.1 V | grid-tied voltage regime | `lineage-inferred` | Canonical implementation map only. |
| H179 | Extended-function bitmap | bits | lineage-wide with feature gates | `hardware-toggle-proven` | This word-level row reflects only proven b3/b7/b9/b10 behavior; use the per-bit grades below for every other position. |
| H202 | Stop-discharge voltage | 0.1 V | grid-tied forced-discharge voltage mode | `hardware-toggle-proven` | Raw 400 = 40 V; 40→41.5→40 V restored. |
| H206 | Peak-shaving period-1 power | **0.1 kW** | `EG4_HYBRID` | `hardware-toggle-proven` | Raw 41 = 4.1 kW; raw 120 = 12 kW. |
| H207 | Peak-shaving period-1 SOC | % | `EG4_HYBRID` | `portal-correlated` | Raw 80 ↔ portal 80. |
| H208 | Peak-shaving period-1 voltage | 0.1 V | `EG4_HYBRID` | `portal-correlated` | Raw 520 ↔ portal 52 V. |
| H209-H212 | Peak-shaving windows 1–2 | packed time | `EG4_HYBRID` | `portal-correlated` | Live cloud write/register match. |
| H218 | Peak-shaving period-2 SOC | % | `EG4_HYBRID` | `portal-correlated` | Raw 50 ↔ portal 50. |
| H219 | Peak-shaving period-2 voltage | 0.1 V | `EG4_HYBRID` | `portal-correlated` | Raw 520 ↔ portal 52 V. |
| H227 | System charge SOC limit | %, 0–101 | supported | `hardware-toggle-proven` | Raw 80→101→restore. |
| H228 | System charge voltage limit | 0.1 V | voltage-control mode | `hardware-toggle-proven` | Controlled named/raw mapping. |
| H231 | Historic peak-shaving power/high-word claim | unknown | tested hybrid | `refuted` | Odd→even quantization and single-register behavior contradict the old claim. |
| H232 | Peak-shaving period-2 power | 0.1 kW | `EG4_HYBRID` | `portal-correlated` | Period-2 peer of H206; not H231’s high word. |
| H233 | Quick-charge/extended-functions bitmap | bits | hybrid/LXP local; off-grid local access rejected | `hardware-toggle-proven` | This word-level row reflects only proven b0/b1/b12 behavior; use the per-bit grades below for every other position. |
| H234 | Quick-charge duration/setpoint and active remaining time | minutes, 0–1440 | supporting | `hardware-toggle-proven` | Start requires a contiguous paired H233+H234 frame; H234 alone is rejected while idle. |
| H256-H259 | Generator-charge windows 1–2 | packed time | hybrid plus off-grid | `portal-correlated` | Portal names/captures establish the block. |
| H269-H274 | Off-grid schedule windows 1–3 | packed time | `EG4_HYBRID` | `portal-correlated` | Portal names/captures establish the block. |

Schedule blocks use `base+0/+1` for window 1 start/end, `+2/+3` for window 2, and `+4/+5` for window 3 where present. A packed time is `hour | (minute << 8)`. Local schedule writes require FC06; firmware rejects FC16 for these registers.

### H110 safe bit map

| Bit(s) | Safe semantic | Evidence grade | Qualification |
|---:|---|---|---|
| 0 | PV grid-off enable | `lineage-inferred` | No reviewed raw toggle. |
| 1 | Fast Zero Export | `portal-correlated` | Vendor key `FUNC_RUN_WITHOUT_GRID` is misleading. |
| 2 | Micro-grid enable | `lineage-inferred` | No reviewed raw toggle. |
| 3 | Shared battery | `lineage-inferred` | Portal name exists; no controlled toggle. |
| 4 | Charge last | `lineage-inferred` | No reviewed raw toggle. |
| 5 | Unknown; historic Take Load Together mapping false | `refuted` | Take Load Together is b10. |
| 6 | Unknown; historic buzzer mapping false | `refuted` | Current buzzer candidate is b7. |
| 7 | Buzzer enable | `portal-correlated` | Name/raw correlation only. |
| 8 | Unknown; historic Green Mode mapping false | `refuted` | Writing it affected the PVCT-sample region. |
| 9 | Unknown; historic ECO mapping false | `refuted` | ECO is b15. |
| 10 | Take Load Together | `hardware-toggle-proven` | Controlled raw delta. |
| 11–13 | Unknown | `lineage-inferred` | Preserve placeholders; do not infer adjacent names. |
| 14 | Green/Off-Grid Mode | `hardware-toggle-proven` | Proven on 18kPV hybrid; off-grid family remains `lineage-inferred`. |
| 15 | Battery ECO | `hardware-toggle-proven` | Raw `0x0080` ↔ `0x8080`. |

### H179 safe bit map

| Bit(s) | Safe semantic | Evidence grade | Qualification |
|---:|---|---|---|
| 0–2 | Unknown | `lineage-inferred` | Asserted AC-CT direction, PV-CT direction, and AFCI-clear names are uncorroborated. |
| 3 | Export PV Only / `FUNC_PV_SELL_TO_GRID_EN` | `hardware-toggle-proven` | FlexBOSS21 and 18kPV raw `0x104c` ↔ `0x1044`, restored. |
| 4–6 | Unknown | `lineage-inferred` | Safe map rejects confident names without captures. |
| 7 | Grid peak-shaving enable | `hardware-toggle-proven` | Correct enable location; not H21. |
| 8 | Unknown | `lineage-inferred` | Generator peak-shaving name is uncorroborated. |
| 9 | Battery charge control: 0 SOC, 1 voltage | `hardware-toggle-proven` | Controlled 2026-02-18 toggle. |
| 10 | Battery discharge control: 0 SOC, 1 voltage | `hardware-toggle-proven` | Controlled 2026-02-18 toggle. |
| 11 | AC coupling function | `lineage-inferred` | Requires a named/raw lockstep toggle. |
| 12–15 | Unknown | `lineage-inferred` | Preserve placeholders. |

### H233 safe bit map

| Bit(s) | Safe semantic | Evidence grade | Qualification |
|---:|---|---|---|
| 0 | Quick-charge start enable | `hardware-toggle-proven` | Paired H233+H234 local frame validated. |
| 1 | Battery-backup control, distinct from H21 b0 EPS | `hardware-toggle-proven` | Controlled live mapping. |
| 2–11 | Unknown | `lineage-inferred` | Maintenance, weekly schedule, and over-frequency names are not accepted without captures. |
| 12 | Sporadic charge | `hardware-toggle-proven` | Web UI plus raw 0 ↔ 4096. It is not Quick Charge. |
| 13–15 | Unknown | `lineage-inferred` | Preserve placeholders. |

## GridBOSS register ledger

| Register(s) | Established or bounded semantic | Units / scale | Signedness | Evidence grade | Qualification |
|---|---|---|---|---|---|
| GB-I1-I9 | Aggregate and L1/L2 grid, UPS, and generator voltages | 0.1 V | unsigned | `portal-correlated` | Cross-referenced to `getMidboxRuntime`. |
| GB-I10-I17 | Grid/load/generator/UPS L1/L2 currents | 0.1 A | unsigned | `portal-correlated` | Cross-referenced to portal fields. |
| GB-I18-I25 | Smart-port 1–4 L1/L2 currents | 0.1 A | unsigned | `lineage-inferred` | Modbus-only fields. |
| GB-I26-I33 | Grid/load/generator/UPS L1/L2 active power | W | signed | `portal-correlated` | Sequential L1/L2 pairs. |
| GB-I34-I41 | Smart-port 1–4 L1/L2 active power | W | signed | `portal-correlated` | Interpret as smart-load or AC-couple according to GB-H20. |
| GB-I42-I49 | Daily load/UPS/export/import L1/L2 energy | 0.1 kWh | unsigned | `portal-correlated` | Sequential values. |
| GB-I50-I51 | Generator daily-energy candidate | 0.1 kWh | unsigned | `asserted-unverified` | Current decoder calls these unused/unknown; requires a generator run. Excluded from 335. |
| GB-I52-I59 | Smart-load ports 1–4 L1/L2 daily energy | 0.1 kWh | unsigned | `portal-correlated` | Sequential values. |
| GB-I60-I67 | AC-couple ports 1–4 L1/L2 daily energy | 0.1 kWh | unsigned | `portal-correlated` | Sequential values. |
| GB-I68-I83 | Load/UPS/export/import L1/L2 lifetime-energy U32 pairs | 0.1 kWh | unsigned | `portal-correlated` | Low word first. |
| GB-I84-I87 | Generator L1/L2 lifetime-energy candidates | U32, 0.1 kWh | unsigned | `asserted-unverified` | Current decoder calls these unused/unknown; requires a generator run. Excluded from 335. |
| GB-I88-I103 | Smart-load ports 1–4 L1/L2 lifetime-energy U32 pairs | 0.1 kWh | unsigned | `portal-correlated` | Low word first. |
| GB-I104-I119 | AC-couple ports 1–4 L1/L2 lifetime-energy U32 pairs | 0.1 kWh | unsigned | `portal-correlated` | Includes I119; I105-I108 are not status. |
| GB-I128/I129/I130 | Phase-lock/grid/generator frequency | 0.01 Hz | unsigned | `portal-correlated` | Cross-referenced to portal fields. |
| GB-I134-I253 | Exact mirror of GB-H134-H253 | raw mirror | raw/unsigned | `lineage-inferred` | Firmware quirk, not independent runtime data. |
| GB-H20 | Four 2-bit smart-port modes | packed bits | unsigned | `portal-correlated` | P1 b0-1, P2 b2-3, P3 b4-5, P4 b6-7; values 0 unused, 1 smart load, 2 AC couple. |

## Individual-battery extended input ledger

For battery index `n`, the documented base is `B = 5002 + 30n`. The dongle Modbus window has a practical four-slot ceiling; wider bank support depends on firmware rotation or another transport.

| Address | Semantic | Units / scale | Signedness | Evidence grade | Qualification |
|---|---|---|---|---|---|
| B+1 | Full capacity | Ah | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+2 | Charge-voltage reference | 0.1 V | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+3 | Charge-current limit | 0.1 A | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+6 | Battery voltage | 0.01 V | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+7 | Battery current | 0.1 A | signed | `lineage-inferred` | CAN-derived canonical map. |
| B+8 low/high | SOC/SOH | 1% bytes | unsigned | `lineage-inferred` | Packed bytes. |
| B+9 | Cycle count | count | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+12/B+13 | Maximum/minimum cell voltage | 0.001 V | unsigned | `lineage-inferred` | CAN-derived canonical map. |
| B+14 low/high | Maximum/minimum-temperature cell numbers | index bytes | unsigned | `portal-correlated` | Live local/cloud capture refuted the old swap. |
| B+15 low/high | Maximum/minimum-voltage cell numbers | index bytes | unsigned | `portal-correlated` | Live local/cloud capture refuted the old swap. |

## Fault and warning word boundary

| Word | Current interpretation | Evidence grade | Safety qualification |
|---|---|---|---|
| I60-I61 | 32-bit inverter fault bitmap | `lineage-inferred` | The bit-name catalogue is inherited. Do not create faults on production hardware to prove names. |
| I62-I63 | 32-bit inverter warning bitmap | `lineage-inferred` | Safe proof requires a real observed fault/warning or controlled factory/simulator injection. |
| I99/I100 | BMS fault/warning fallback enums | `lineage-inferred` | Used only when the corresponding inverter word is zero; descriptions remain provisional. |

## Source hierarchy

| Source | What it can establish | Maximum safe grade without more evidence |
|---|---|---|
| Correctly reconstructed firmware with validated ARM/C28x decode and full producer-to-FC04 trace | Structure, writers, conversion, publication, response | `firmware-proven` |
| Controlled live named toggle/raw delta/readback/restore on the target family | Writable address/bit semantic on that family | `hardware-toggle-proven` |
| Portal field plus simultaneous raw register movement | Correlation | `portal-correlated` |
| `docs/DATA_MAPPING.md`, canonical metadata, protocol manuals, upstream or adjacent-family tables | Implementation intent or hypothesis | `lineage-inferred` |
| Passing unit/contract tests using the same mapping tables | Internal software consistency only | `asserted-unverified` for real-world semantics |

Detailed derivations live in [DATA_MAPPING.md](../../docs/DATA_MAPPING.md), [OFFGRID_GENERATOR_REGISTERS.md](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md), [OFFGRID_EPS_REGISTERS.md](../../docs/reference/firmware/OFFGRID_EPS_REGISTERS.md), and [HYBRID_EPS_REGISTERS.md](../../docs/reference/firmware/HYBRID_EPS_REGISTERS.md). Those sources remain subject to the grades and corrections on this page.
