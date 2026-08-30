---
canonical-for: inverter-and-gridboss-register-ground-truth
sources:
  - docs/DATA_MAPPING.md
  - docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md
  - docs/reference/firmware/OFFGRID_EPS_REGISTERS.md
  - docs/reference/firmware/HYBRID_EPS_REGISTERS.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
  - custom_components/eg4_web_monitor/base_entity.py
  - custom_components/eg4_web_monitor/const/device_types.py
  - custom_components/eg4_web_monitor/number.py
  - custom_components/eg4_web_monitor/switch.py
  - custom_components/eg4_web_monitor/utils.py
  - memory/issue-476-green-mode-bit14.md
  - memory/live-write-window-findings.md
  - memory/issue-258-battery-rr-reg96-unreliable.md
  - memory/soc-charge-limit-101-top-balance.md
  - memory/cloud-raw-register-write-broken.md
  - memory/voltage-param-scaling-cloud-vs-local.md
  - memory/quick-charge-local-control-registers.md
  - pylxpweb@204b95d:src/pylxpweb/devices/inverters/base.py
  - pylxpweb@204b95d:src/pylxpweb/transports/data.py
  - pylxpweb@204b95d:src/pylxpweb/transports/dongle.py
  - pylxpweb@204b95d:src/pylxpweb/transports/_canonical_reader.py
  - pylxpweb@204b95d:src/pylxpweb/registers/__init__.py
  - pylxpweb@204b95d:src/pylxpweb/constants/registers.py
  - https://github.com/joyfulhouse/pylxpweb/issues/242
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/559
  - https://github.com/joyfulhouse/pylxpweb/pull/270
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/570
  - https://github.com/joyfulhouse/eg4_web_monitor/pull/569
  - https://github.com/joyfulhouse/pylxpweb/issues/271
  - https://github.com/joyfulhouse/pylxpweb/issues/272
  - https://github.com/joyfulhouse/pylxpweb/pull/273
verified-against:
  # The pin is commit-only per _conventions.md (machine tooling passes it to
  # git show) and covers the pre-existing claims, verified at e9853eb
  # (v3.5.1-beta.12 mainline, contains the PR #569 routing). Rows
  # describing the #570 sweep-extended routing (H227/H234 shipped-path notes,
  # the H22 row, the cloud-only scalar set, the H233 boundary and
  # schedule-write routing rows) are licensed PER CLAIM by their inline
  # PR #600 / issue #570 citations (the durable artifact — the PR diff
  # survives branch deletion; embedded SHAs staled twice in review).
  # Re-pinned at the 2026-08-30 release cut: PR #600 merged as d8e2027, so
  # the sweep-extended rows now verify at the mainline pin below (inline
  # PR #600 / issue #570 citations remain as provenance). pylxpweb stays
  # ab87902 (0.9.39b11); the #271/#272 range fixes merged after it and are
  # cited by PR number (pylxpweb #273), not by pin.
  eg4_web_monitor: d8e2027
  pylxpweb: ab87902
last-verified: 2026-08-30
---

# Register ground truth

> **Audited result: 41 of 346 counted current register claims are proven: 33 `firmware-proven` + 8 `hardware-toggle-proven` = 41; 33 + 8 + 170 `portal-correlated` + 135 `lineage-inferred` = 346.** The arithmetic and row contributions are reproducible from the audit command below; this accounting assertion is `asserted-unverified`, not a code-behavior claim. Register semantics retain their own row grades.

This page is canonical for register semantics and evidence status. **When it conflicts with [`docs/DATA_MAPPING.md`](../../docs/DATA_MAPPING.md), this page wins.** `DATA_MAPPING.md` remains a useful implementation/derivation source, but its names and derivations are subordinate to the family scope, evidence grade, and status recorded here.

The grade vocabulary is owned by the [llmwiki evidence-grade legend](../README.md#evidence-grade-legend); this page does not redefine it. The register-annotation ladder in that legend applies here. In particular, `hardware-toggle-proven` requires a named action on the target family, a captured pair of raw integer register words before and after, and successful restoration. Scaled engineering values are not raw captures and must not be back-computed into one. Component firmware is scope metadata: when it was not recorded, the claim is limited to the tested unit. `refuted` is recorded only in the **Status** column; the **Evidence** column grades the evidence that disproves the historic claim.

## Auditable accounting

| Evidence | Count | Proven? |
|---|---:|:---:|
| `firmware-proven` | 33 | yes |
| `hardware-toggle-proven` | 8 | yes |
| `app-write-path-proven` | 0 | no |
| `portal-correlated` | 170 | no |
| `lineage-inferred` | 135 | no |
| `inferred` | 0 | no |
| `verified-against-code` | 0 | no |
| `asserted-unverified` | 0 | no; candidate rows are excluded |
| **Current total** | **346** | **41 proven (11.8%)** |

The `Claim count` column is the machine-checkable contribution. One separately named semantic is one claim; a U32 low/high pair is one; family-specific meanings are separate; a compound packed-word contract is one claim unless its bits are separately exposed as independent semantics. Structural-only, candidate, unknown, and `asserted-unverified` rows contribute zero. Refuted historic labels are outside the counted ledger. The markers around the ledger allow an `awk -F'|'` sum of column 7 to reproduce every subtotal.

From the repository root, this prints the exact grade subtotals and total used above:

```sh
awk -F'|' '/counted-ledger:start/{on=1;next}/counted-ledger:end/{on=0} on && /^\|/ && $7 ~ /^[[:space:]]*[0-9]+[[:space:]]*$/ {g=$5;c=$7;gsub(/[`[:space:]]/,"",g);gsub(/[[:space:]]/,"",c);n[g]+=c;t+=c} END{for(g in n)print g,n[g];print "TOTAL",t}' llmwiki/40-hardware/registers.md | sort
```

## Notation

| Prefix | Register space | Access | Evidence | Status |
|---|---|---|---|---|
| `I` | Inverter input, FC04 | Read-only | `verified-against-code` | current |
| `H` | Inverter holding, FC03 to read | Potentially writable by FC06/FC16 or portal controls | `verified-against-code` | current |
| `GB-I` | GridBOSS input, FC04/device type 50 | Read-only | `verified-against-code` | current |
| `GB-H` | GridBOSS holding | Potentially writable | `verified-against-code` | current |

Pinned code anchors for this notation are the `registers/__init__.py` exports [`INVERTER_INPUT_REGISTERS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/registers/__init__.py#L104-L123), [`INVERTER_HOLDING_REGISTERS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/registers/__init__.py#L77-L100), and [`GRIDBOSS_REGISTERS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/registers/__init__.py#L46-L72); [`dongle.py::MODBUS_READ_HOLDING` / `MODBUS_READ_INPUT`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/transports/dongle.py#L73-L77) pins FC03/FC04. [`constants/registers.py::MIDBOX_REGISTER_TO_PARAM_KEYS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L1072-L1098) pins the GridBOSS holding map, and [`DEVICE_TYPE_CODE_GRIDBOSS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L1825) is 50.

Unless a row says signed, the current canonical decoder treats it as unsigned. U32 values use the lower-address word as low word: `(high << 16) | low`. This decoding convention is `verified-against-code` at [`_canonical_reader.py::read_raw`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/transports/_canonical_reader.py#L34-L82).

<!-- counted-ledger:start -->

## Inverter input-register ledger

| Register(s) | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| I0 | Device status / operating-state code | all | `lineage-inferred` | current | 1 | [`DATA_MAPPING.md` §2](../../docs/DATA_MAPPING.md#2-inverter-input-registers); enum details below. |
| I1/I2/I3 | PV1/PV2/PV3 voltage, 0.1 V | all | `lineage-inferred` | current | 3 | `DATA_MAPPING.md` §2 canonical map. |
| I4 | Battery voltage, 0.1 V | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2 canonical map. |
| I5 low/high | SOC / SOH, 1% bytes | all | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §15.3 packed-byte implementation. |
| I7/I8/I9 | PV1/PV2/PV3 power, W | all | `lineage-inferred` | current | 3 | `DATA_MAPPING.md` §2 canonical map. |
| I10/I11 | Battery charge/discharge power, W | all; I11 entity off-grid-gated | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §2 canonical map. |
| I12/I13/I14 | Grid R/S/T voltage, 0.1 V | all | `lineage-inferred` | current | 3 | `DATA_MAPPING.md` §2 canonical map. |
| I15 | Grid frequency, 0.01 Hz | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2 canonical map. |
| I16 | Inverter power, W | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2 canonical map. |
| I17 | Rectifier power, not grid power, W | all | `portal-correlated` | current | 1 | `DATA_MAPPING.md` §9 plus off-grid DSP-block correlation; I17/I27 remain generator-power candidates only. |
| I18 | Inverter RMS current R/L1, 0.01 A | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2 canonical map. |
| I19 | Power factor, special encoded-negative representation, 0.001 | all | `lineage-inferred` | current | 1 | Canonical decoder plus register audit; not conventional S16 or percent. |
| I20 | EPS R/aggregate voltage, 0.1 V | decoded off-grid and hybrid images | `firmware-proven` | current | 2 | [`OFFGRID_EPS_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_EPS_REGISTERS.md) and [`HYBRID_EPS_REGISTERS.md`](../../docs/reference/firmware/HYBRID_EPS_REGISTERS.md). |
| I21/I22 | Decoded quantities whose physical meanings remain unknown | observed US split-phase images | `firmware-proven` | structural-only | 0 | Firmware disproves the old EPS S/T voltage labels; the replacement semantics remain unresolved. |
| I23 | EPS frequency, 0.01 Hz | decoded hybrid image | `firmware-proven` | current | 1 | `HYBRID_EPS_REGISTERS.md`. |
| I23 | EPS frequency, 0.01 Hz | other families | `lineage-inferred` | current | 1 | Broader canonical definition has no separate reviewed trace. |
| I24 | EPS active power, wire W; internal deciwatts ÷10 | decoded off-grid and hybrid images | `firmware-proven` | current | 2 | Both EPS firmware analyses. |
| I25 | EPS apparent power; whole VA off-grid, computed/clamped hybrid | decoded off-grid and hybrid images | `firmware-proven` | current | 2 | Both EPS firmware analyses; hybrid live accuracy remains unvalidated. |
| I26/I27 | Export/import power, W | all | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §2; I27 is only a generator-power candidate. |
| I28/I29/I30 | PV1/PV2/PV3 energy today, 0.1 kWh | all | `lineage-inferred` | current | 3 | Canonical register definitions. |
| I31 | Inverter output energy today, not PV yield, 0.1 kWh | all | `portal-correlated` | current | 1 | `DATA_MAPPING.md` energy comparison. |
| I32 | AC/grid charge energy today, `Erec_day`, 0.1 kWh | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2; historic load-energy alias is refuted below. |
| I33/I34 | Battery charge/discharge energy today, 0.1 kWh | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I35 | EPS energy today, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I36/I37 | Grid export/import energy today, 0.1 kWh | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I38/I39 | Bus voltage 1/2, 0.1 V | all | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §2. |
| I40-I45 | PV1/PV2/PV3 lifetime-energy U32 pairs, 0.1 kWh | all | `lineage-inferred` | current | 3 | Canonical register definitions. |
| I46-I47 | Inverter output energy lifetime, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Not lifetime PV yield. |
| I48-I49 | AC/grid charge energy lifetime, `Erec_all`, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Historic load-energy alias is refuted below. |
| I50-I51 | Charge energy lifetime, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I52-I53 | Discharge energy lifetime, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I54-I55 | EPS lifetime energy, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I56-I57 | Grid export energy lifetime, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I58-I59 | Grid import energy lifetime, U32, 0.1 kWh | all | `lineage-inferred` | current | 1 | Canonical register definitions. |
| I60-I61 | Inverter fault bitmap, U32 | all; LOCAL/HYBRID sensor | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §2; individual bit names lack controlled fault injection. |
| I62-I63 | Inverter warning bitmap, U32 | all; LOCAL/HYBRID sensor | `lineage-inferred` | current | 1 | Same evidence boundary as the fault word. |
| I64 | Internal temperature, signed two’s-complement °C | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I65/I66 | Radiator temperature 1/2, °C | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I67 | Battery temperature; raw `0x007f` is the no-reading sentinel | all canonical families | `portal-correlated` | current | 1 | [`CHANGELOG.md` #348/#521](../../CHANGELOG.md) and [`register audit` MAP-01](../../docs/audits/2026-08-02-register-race-performance-audit.md#map-01--battery-temperature-is-mapped-but-cannot-become-an-entity). Live reproduction was not a controlled before/after induction, so this is not `hardware-proven`. Full keeper note below. |
| I68 | Battery-control temperature, 0.1 °C | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I69-I70 | Running time, U32 seconds | all | `portal-correlated` | current | 1 | Unit corroborated; reset behavior unproven. |
| I72/I73/I74 | Asserted direct PV1/PV2/PV3 current, 0.01 A | all | `asserted-unverified` | unresolved | 0 | [`register audit` MAP-01 vicinity](../../docs/audits/2026-08-02-register-race-performance-audit.md); live EG4 probes often return zero/garbage and integration derives P/V. |
| I75 | Inverter-measured battery current, 0.01 A | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I77 b0 | AC source: 0 grid, 1 generator | all | `portal-correlated` | current | 1 | `DATA_MAPPING.md` read-only diagnostics. |
| I80 | BMS communication/battery type, asserted 0 CAN / 1 RS485 | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I81/I82 | BMS charge/discharge current limits, 0.1 A | all | `lineage-inferred` | current | 2 | Canonical definitions; I81 scaling described as empirical. |
| I83/I84 | BMS charge-voltage reference / discharge cutoff, 0.1 V | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I85-I94 | Opaque BMS status words | all | `asserted-unverified` | structural-only | 0 | [`DATA_MAPPING.md` input-register map](../../docs/DATA_MAPPING.md#2-inverter-input-registers) names only opaque status words; no word semantics are claimed. |
| I95 | Packed BMS charge/discharge-permission and force-charge-request bitmap | all | `portal-correlated` | current | 1 | `DATA_MAPPING.md` §7 cloud-boolean correlation; the current named bits are b0, b1, and b5. |
| I96 | Battery parallel count | all | `lineage-inferred` | current | 1 | Known unreliable with rotating banks; do not use it as slot capacity. |
| I97 | BMS-reported capacity, Ah | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I98 | BMS battery current, signed 0.1 A | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I99/I100 | BMS fault/warning fallback enums | all | `lineage-inferred` | current | 2 | Used when inverter I60-I63 is zero; descriptions are provisional. |
| I101/I102 | Maximum/minimum cell voltage, 0.001 V | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I103/I104 | Maximum/minimum cell temperature, signed 0.1 °C | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I105 | BMS update-state enum and b4 generator dry-contact indication | inverter scope | `lineage-inferred` | current | 2 | Canonical inverter definition; unrelated to GridBOSS smart-port mode. |
| I106 | BMS cycle count | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I107 | Inverter-sampled battery voltage, 0.1 V | all | `lineage-inferred` | current | 1 | Canonical register definition. |
| I108 | T1/BT board temperature, 0.1 °C | all | `lineage-inferred` | current | 1 | Modbus-only in current integration. |
| I109-I112 | Reserved T2-T5 temperature slots | all | `asserted-unverified` | structural-only | 0 | [`DATA_MAPPING.md` temperature map](../../docs/DATA_MAPPING.md#temperature-registers) and the canonical decoder reserve them; no sensor assignment is asserted. |
| I113 | Packed parallel-configuration word | all | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` read-only diagnostics assign role, phase, and unit-number subfields; phase-source comparison conflicts. |
| I121/I122 | Generator voltage/frequency, 0.1 V / 0.01 Hz | decoded 12000XP/off-grid image | `firmware-proven` | current | 2 | [`OFFGRID_GENERATOR_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md). |
| I121/I122 | Generator voltage/frequency | other families | `lineage-inferred` | current | 2 | No separate reviewed firmware trace. |
| I123 | ARM-initialization counter modulo 65,536, nominal ~1 Hz | decoded 12000XP/off-grid image | `firmware-proven` | current | 1 | `OFFGRID_GENERATOR_REGISTERS.md`; not generator power. |
| I123 | Timer-structure field; exact writer/meaning unknown | 6000XP/off-grid | `asserted-unverified` | structural-only | 0 | `OFFGRID_GENERATOR_REGISTERS.md` comparison section; no concrete validated 6000XP image. |
| I123 | Multiplexed GEN-port power, low16 of signed DSP difference | decoded 18kPV/FlexBOSS hybrid image | `firmware-proven` | current | 1 | `OFFGRID_GENERATOR_REGISTERS.md` hybrid comparison. |
| I124 | High DSP metadata byte plus low ARM status byte | decoded 12000XP/off-grid image | `firmware-proven` | current | 1 | `OFFGRID_GENERATOR_REGISTERS.md`; not energy. |
| I125-I126 | One ARM-maintained U32 status word | decoded 12000XP/off-grid image | `firmware-proven` | current | 1 | Written positions known; individual meanings unknown. |
| I124 | Generator daily energy, 0.1 kWh | hybrid/LXP | `lineage-inferred` | current | 1 | Family-gated canonical definition. |
| I125-I126 | Generator lifetime energy, U32, 0.1 kWh | hybrid/LXP | `lineage-inferred` | current | 1 | Family-gated canonical definition. |
| I127/I128 | EPS L1/L2 voltage, 0.1 V | hybrid and off-grid | `portal-correlated` | current | 2 | `DATA_MAPPING.md` split-phase/live values. |
| I129/I130 | EPS L1/L2 active power, combined backup-path legs, W | decoded off-grid image | `firmware-proven` | current | 2 | `OFFGRID_EPS_REGISTERS.md`; not EPS-only load. |
| I129/I130 | EPS L1/L2 active power, W | decoded hybrid image | `firmware-proven` | current | 2 | `HYBRID_EPS_REGISTERS.md`. |
| I131/I132 | EPS L1/L2 apparent power, VA | decoded off-grid image | `firmware-proven` | current | 2 | `OFFGRID_EPS_REGISTERS.md`. |
| I131 | Sign-split directional DSP quantity, 0.1 power unit | decoded hybrid image | `firmware-proven` | current | 1 | `HYBRID_EPS_REGISTERS.md`; exact physical label remains unresolved, and old apparent-power label is refuted below. |
| I132 | Thresholded persistent event counter | decoded hybrid image | `firmware-proven` | current | 1 | `HYBRID_EPS_REGISTERS.md`; old L2 apparent-power label is refuted below. |
| I133/I134 | EPS L1/L2 energy today, 0.1 kWh | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I135-I138 | EPS L1/L2 lifetime-energy U32 pairs, 0.1 kWh | all | `lineage-inferred` | current | 2 | Canonical register definitions. |
| I153 | AC-couple power, W; signedness unresolved | decoded off-grid image | `firmware-proven` | current | 1 | `OFFGRID_GENERATOR_REGISTERS.md` known-live dispatcher anchor. |
| I153 | AC-couple power, W | other families | `lineage-inferred` | current | 1 | Broader canonical mapping lacks separate reviewed traces. |
| I170 | Total output/load power, signed W | decoded 12000XP/off-grid image | `firmware-proven` | current | 1 | `OFFGRID_GENERATOR_REGISTERS.md` known-live dispatcher anchor. |
| I170 | Total output/load power, signed W | 6000XP, 12kPV, and other unreviewed images | `lineage-inferred` | current | 1 | Explicitly not `firmware-proven` outside the decoded 12000XP trace. |
| I171 | Inverter-served `Eload_day`, 0.1 kWh | all | `portal-correlated` | current | 1 | Exact per-inverter portal match; not whole-home consumption. |
| I172-I173 | Inverter-served `Eload_all`, U32, 0.1 kWh | all | `portal-correlated` | current | 1 | Same evidence and scope as I171. |
| I188/I189 | Unimplemented/reserved dispatcher slots | decoded 12000XP/off-grid image | `firmware-proven` | current | 2 | `OFFGRID_GENERATOR_REGISTERS.md`; not generator-power candidates. |
| I190/I191 | Inverter RMS current S/T, 0.01 A | LXP three-phase | `lineage-inferred` | current | 2 | Canonical three-phase map. |
| I193/I194 | Inverter grid L1/L2 voltage, 0.1 V; zero on tested US hybrids | nominal all; observed 18kPV/FlexBOSS zero | `portal-correlated` | current | 2 | `DATA_MAPPING.md` live block comparison; portability unproven. |
| I195/I196 | Generator L1/L2 voltage, 0.1 V | decoded 12000XP/off-grid image | `firmware-proven` | current | 2 | `OFFGRID_GENERATOR_REGISTERS.md`. |
| I195/I196 | Generator L1/L2 voltage, 0.1 V | other families | `lineage-inferred` | current | 2 | Broader portable definition is inherited. |
| I197-I204 | Firmware-proven DSP source-block provenance; portable per-field semantics remain weaker | decoded 12000XP block | `firmware-proven` | structural-only | 0 | `OFFGRID_GENERATOR_REGISTERS.md`; excluded because this is not an established per-field semantic claim. |
| I210 | Quick-charge remaining; unit asserted as seconds | supporting inverters | `lineage-inferred` | unresolved | 1 | `memory/quick-charge-local-control-registers.md`; same-firmware wall-clock capture is still required. |
| I217-I222 | PV4/PV5/PV6 voltage and power | models with detected strings | `lineage-inferred` | current | 6 | Canonical extended definitions; feature-gated, not `hardware-proven`. |
| I223-I231 | PV4/PV5/PV6 daily and lifetime yield | models with detected strings | `lineage-inferred` | current | 6 | Canonical extended definitions; no cloud PV4-6 energy peers. |
| I232 | Smart-load power candidate, W | nominal all | `asserted-unverified` | unresolved | 0 | [`DATA_MAPPING.md` backup-output note](../../docs/DATA_MAPPING.md); never validated on off-grid hardware. |

## Inverter holding-register ledger

Every row is readable via FC03 but exists in potentially writable configuration space.

| Register(s) | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| H0-H1 | Model rating bits and FlexBOSS offset bit | inverters | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` model detection. |
| H19 | Device-type code | inverter/MID/GridBOSS discovery | `portal-correlated` | current | 1 | Device-type/model table correlation. |
| H21 | Function-enable bitmap | lineage-wide, feature-gated | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §3; peak shaving is not located here. |
| H21 b7 | Stored and readback-visible but **never consumed — inert as the off-grid AC-charge gate**: the ARM→DSP function mapper enumerates bits 1, 4, 6, 9–13, 15, 16, 19, 23, 26, 30, 31 and skips b7; the charge decision combines the H68–H73 schedule evaluator (runtime bit 23) with battery-control mode, never b7 | decoded CEAA/CCAA off-grid images | `firmware-proven` | current | 1 | [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) (2026-08-12). A negative claim proven by disassembly (legend: negative claims). Confirms the #563 suppression of the off-grid AC Charge switch. Scope: these two lineages' decoded builds only. |
| H22 | PV start voltage (MPPT activation floor), raw 0.1 V; cloud name `HOLD_START_PV_VOLT` returns/accepts already-scaled volts | supported inverters (shipped `pv_start_voltage` control) | `portal-correlated` | current | 1 | Canonical pylxpweb definition, [`inverter_holding.py` address 22 at `ab87902`](https://github.com/joyfulhouse/pylxpweb/blob/ab87902/src/pylxpweb/registers/inverter_holding.py#L167-L177) (90–500 V engineering bounds); the cloud named read/write route is the shipped verified route ([PR #359](https://github.com/joyfulhouse/eg4_web_monitor/pull/359), `CHANGELOG.md`: cloud read fixed, "its write keeps the verified named-parameter cloud route"). Two sub-claims stay `asserted-unverified`: the pylxpweb definition's note that "reg 22 also carries LSP function bits" (no per-family capture — a strong extra reason local scalar writes stay gated), and the shipped spec comment that firmware rejects values below 140 V with error code 3 (`number.py` `pv_start_voltage` spec; no preserved exchange). No write tuple (raw before/after/restore) and no off-grid write evidence exist; the #570 audit routes off-grid/unresolved writes through the named-volts cloud route only. Row added by the #570 sweep (review round 2 — the register was shipped but unledgered). |
| H64 | Legacy charge-power-percent command | all | `lineage-inferred` | current | 1 | Canonical holding definition. H64 is not the PV-charge entity target; H74 is `portal-correlated`. |
| H65 | Discharge power limit, 0-100% | all | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H66 | AC charge power: writable raw 0..100 (≥101 → exception 03) and DSP-propagated, but **no charge-power consumer traceable — semantics NOT verifiable from firmware** | decoded CEAA/CCAA off-grid images | `firmware-proven` | current; semantics unresolved | 1 | [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) (2026-08-12): writer accepts 0..100 only; staging word terminates in transport/default paths in the stripped DSP image. This proves writability and range, **never** the charge-power semantic — do not upgrade the semantic row below from it. pylxpweb permitted the equivalent of raw 0..150 — conflict filed as [pylxpweb #272](https://github.com/joyfulhouse/pylxpweb/issues/272), fixed by [pylxpweb PR #273](https://github.com/joyfulhouse/pylxpweb/pull/273) (max 10 kW, merged to pylxpweb main after `ab87902`). |
| H66 | AC charge power, raw ×100 W / UI kW | all | `portal-correlated` | current | 1 | `DATA_MAPPING.md` raw/UI examples; not percent. No write evidence is recorded — the grade rests on read/scaling evidence only (PR #569 evidence-claim alignment). |
| H67 | AC-charge stop SOC, including 101 where supported | grid-tied only | `portal-correlated` | current | 1 | `DATA_MAPPING.md` plus `memory/soc-charge-limit-101-top-balance.md`; off-grid rejects this control. |
| H68-H73 | AC-charge window 1-3 start/end packed times | control-capable | `portal-correlated` | current | 6 | `DATA_MAPPING.md` schedule table/live named probes. |
| H74 | Forced/PV-charge-priority power, raw ×100 W / UI kW | supported | `portal-correlated` | current | 1 | `DATA_MAPPING.md` identifies H74; durable record lacks the complete toggle-proof tuple. |
| H75 | Forced-charge stop SOC | grid-tied controls | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H76-H81 | Forced-charge window 1-3 packed times | grid-tied | `portal-correlated` | current | 6 | `DATA_MAPPING.md` schedule table. |
| H82 | Forced-discharge power, raw ×100 W / UI kW | grid-tied | `portal-correlated` | current | 1 | `DATA_MAPPING.md` and the canonical map record raw/UI examples; the durable record lacks a named-action raw before/after pair and restoration. |
| H83 | Forced-discharge SOC stop | grid-tied | `portal-correlated` | current | 1 | `DATA_MAPPING.md` identifies the field; the durable record lacks a complete named-action raw before/after pair and restoration. |
| H84-H89 | Forced-discharge window 1-3 packed times | grid-tied | `portal-correlated` | current | 6 | `DATA_MAPPING.md` schedule table; off-grid writability remains gated. |
| H100 | EPS/off-grid voltage cutoff, 0.1 V | voltage-control devices | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H101/H102 | Charge/discharge current limits, A | all | `lineage-inferred` | current | 2 | Canonical definitions; reviewed source contains no controlled capture. |
| H103 | Maximum grid sell-back power, raw ×100 W / UI kW | grid-tied | `portal-correlated` | current | 1 | `DATA_MAPPING.md` raw/UI correlation; not percent. |
| H105 | On-grid discharge SOC cutoff | grid-tied | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H110 | Shared system-function word; individual meanings below | all | `verified-against-code` | structural-only | 0 | [`constants/registers.py::REGISTER_110_PARAM_KEYS`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L642-L659) and [`REGISTER_TO_PARAM_KEYS[110]`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L777-L782) define the structure. Never inherit a bit’s grade to the whole word or another family. |
| H116 | Import threshold to start discharge, W | grid-tied; CT required | `portal-correlated` | current | 1 | `DATA_MAPPING.md`; whole watts, not ×100 W. |
| H117 | Start-charge threshold, signed W | LOCAL/HYBRID | `asserted-unverified` | unresolved | 0 | [`DATA_MAPPING.md` H117 note](../../docs/DATA_MAPPING.md#power-control-registers); no cloud name or validated behavior. |
| H120 | Compound charge/discharge-mode control word | supporting inverters | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` compound-field audit assigns half-hour, AC-charge type, discharge type, on-grid EOD type, and generator-charge type subfields; do not decode it as consecutive booleans. |
| H125 | EPS/off-grid discharge SOC cutoff | relevant devices | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H152-H157 | AC-first window 1-3 packed times | `EG4_OFFGRID`/SNA portal page | `portal-correlated` | current | 6 | `DATA_MAPPING.md` schedule table and SNA probe. |
| H158 | AC-charge start voltage, 0.1 V; FC06/FC16 writer enforces raw 384..570 and ≤H159; consumed by the charge state machine | decoded CEAA (12000XP) and CCAA (6000XP) off-grid images | `firmware-proven` | current | 1 | [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) (2026-08-12; image sha256s in the [PR #569 comment](https://github.com/joyfulhouse/eg4_web_monitor/pull/569#issuecomment-5273044416)): ARM writer range checks, charge-state-machine consumers, C28x corroboration. Mapping proof only — no live off-grid write exists; a version-gated local-write upgrade is a recorded candidate on #570, not shipped. |
| H158 | AC-charge start voltage — named cloud write path, storage and restoration | tested FlexBOSS21 and 18kPV units (component firmware unrecorded — scope limited to the tested units) | `hardware-toggle-proven` | current on tested units | 1 | [#570 live sweep, 2026-08-13](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287046586): cloud named `holdParam` write with raw `remoteRead.valueFrame` decode — FlexBOSS21 raw 400→401→400 (15:11 PT), [18kPV raw 400→401→400 (15:21 PT)](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287070960), each restored on attempt 1. Proves the name→register write path and storage, **not** charge-logic semantics. |
| H158 | AC-charge start voltage, 0.1 V | other families | `portal-correlated` | current | 1 | Earlier named action and 40→40.5→40 V restoration were recorded as scaled engineering values only; raw words not preserved; target family unrecorded. `memory/cloud-raw-register-write-broken.md`. |
| H159 | AC-charge end voltage, 0.1 V; FC06/FC16 writer enforces raw 480..590 and ≥H158; consumed by the charge state machine | decoded CEAA/CCAA off-grid images | `firmware-proven` | current | 1 | Same [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) and scope caveat as H158: mapping proof only. |
| H159 | AC-charge end voltage — named cloud write path, storage and restoration | tested FlexBOSS21 and 18kPV units (component firmware unrecorded — scope limited to the tested units) | `hardware-toggle-proven` | current on tested units | 1 | [#570 live sweep, 2026-08-13](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287046586): FlexBOSS21 raw 560→561→560 (15:11 PT); [18kPV raw 590→589→590 (15:21 PT)](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287070960) — delta downward because 590 is the firmware-proven upper bound. Write path and storage only. |
| H159 | AC-charge end voltage, 0.1 V | other families | `portal-correlated` | current | 1 | `DATA_MAPPING.md` identifies the field; no write tuple in the durable record outside the tested units above. |
| H160 | AC-charge start SOC; FC06/FC16 writer rejects 0 and ≥91 (exception 03) — **raw minimum is 1, not 0** | decoded CEAA/CCAA off-grid images | `firmware-proven` | current | 1 | Same [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579). The pylxpweb definition permitted 0 — conflict filed as [pylxpweb #271](https://github.com/joyfulhouse/pylxpweb/issues/271), fixed by [pylxpweb PR #273](https://github.com/joyfulhouse/pylxpweb/pull/273) (min_value 1, merged to pylxpweb main after `ab87902`). |
| H160 | AC-charge start SOC — named cloud write path, storage and restoration | tested FlexBOSS21 and 18kPV units (component firmware unrecorded — scope limited to the tested units) | `hardware-toggle-proven` | current on tested units | 1 | [#570 live sweep, 2026-08-13](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287046586): FlexBOSS21 raw 5→6→5 (15:11 PT); [18kPV raw 5→6→5 (15:21 PT)](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287070960). H160=0 was deliberately not attempted (firmware proves it invalid). Write path and storage only. |
| H160 | AC-charge start SOC | other families | `portal-correlated` | current | 1 | Portal/control mapping. |
| H161 | AC-charge end SOC; FC06/FC16 writer enforces raw 20..100 and ≥H160; consumed by the charge state machine | decoded CEAA/CCAA off-grid images | `firmware-proven` | current | 1 | Same [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) as H158–H160: mapping proof on the off-grid images only. No live off-grid write exists (the maintainer plant has no off-grid hardware); the targeted retest is recorded on [#570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287056672) and deferred until off-grid hardware exists. |
| H161 | AC-charge end SOC mapping; **LOCAL writability unresolved; inert on the tested grid-tied hybrids** | family behavior conflicts across tested grid-tied and off-grid paths | `portal-correlated` | current; write unresolved | 1 | `memory/soc-charge-limit-101-top-balance.md` records inert grid-tied behavior on an 18kPV (cloud write success=True, raw stays 0). The [#570 live sweep, 2026-08-13](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287046586) reproduced the identical signature on a **second** grid-tied unit (FlexBOSS21: requested 20, success returned, raw stayed 0 on `valueFrame` readback, 15:11–15:12 PT) — [resolved as the pre-documented family quirk, not a write-path fault](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287056672): pylxpweb's register commentary records reg 161 unused/read-only on grid-tied hybrids, whose AC-charge stop SOC is reg 67. Sibling reg 160 toggled cleanly in the same regime, so the inertness is register-specific, not regime gating. [Contradictions C6/C7](../60-history/open-contradictions.md) preserve the conflict; C6 stays formally open pending off-grid evidence. Do not treat H161 as a safe local write. |
| H169 | On-grid end-of-discharge voltage, 0.1 V | grid-tied voltage regime | `lineage-inferred` | current | 1 | Canonical holding definition. |
| H179 | Shared extended-function word; individual meanings below | all | `verified-against-code` | structural-only | 0 | [`constants/registers.py::REGISTER_TO_PARAM_KEYS[179]`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L850-L926) defines the structure. Grades are bit- and family-specific. |
| H202 | Stop-discharge voltage, 0.1 V | grid-tied forced-discharge voltage mode | `portal-correlated` | current | 1 | The source preserves raw 400 ↔ cloud 40 V at baseline, but the 40→41.5→40 V action/restoration is recorded only as scaled engineering values; integer register words for the changed and restored states were not preserved; target family unrecorded. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md#battery-chargedischarge-control-mode-soc-vs-voltage). |
| H206 | Peak-shaving period-1 power, **0.1 kW** | `EG4_HYBRID` | `portal-correlated` | current | 1 | `memory/live-write-window-findings.md` records raw 41→4.1 kW and family applicability; the durable record lacks a complete named-action raw before/after/restore tuple. |
| H207 | Peak-shaving period-1 SOC, % | `EG4_HYBRID` | `portal-correlated` | current | 1 | Raw/portal correlation in canonical holding map. |
| H208 | Peak-shaving period-1 voltage, 0.1 V | `EG4_HYBRID` | `portal-correlated` | current | 1 | Raw/portal correlation in canonical holding map. |
| H209-H212 | Peak-shaving window 1-2 packed times | `EG4_HYBRID` | `portal-correlated` | current | 4 | `SCHEDULE_TIME_TYPES` records FlexBOSS21 FAAB-2525 01:05 → H211 raw 1281. |
| H218 | Peak-shaving period-2 SOC, % | `EG4_HYBRID` | `portal-correlated` | current | 1 | Raw/portal correlation in canonical holding map. |
| H219 | Peak-shaving period-2 voltage, 0.1 V | `EG4_HYBRID` | `portal-correlated` | current | 1 | Raw/portal correlation in canonical holding map. |
| H227 | System charge SOC limit, 0-101% | tested 18kPV | `hardware-toggle-proven` | current on tested unit; cross-family write risk unresolved | 1 | Named System Charge SOC Limit action and raw 80→101→80 restoration; component firmware version unrecorded — scope limited to the tested unit. `memory/soc-charge-limit-101-top-balance.md`. Shipped-path fact (`verified-against-code`): `_create_number_entities` adds `SystemChargeSOCLimitNumber` to the always-on block for every supported inverter reaching it, with no family gate. Routing since the [#570 audit](https://github.com/joyfulhouse/eg4_web_monitor/issues/570) (this change set): the write passes `local_write_blocked_reason` from `_offgrid_cloud_only_reason`, so EG4_OFFGRID and unresolved/UNKNOWN families route CLOUD-ONLY and pure-LOCAL raises; a positively resolved non-off-grid family keeps the local-first route (HYBRID may fall back to cloud; LOCAL has no fallback). Code anchors: `number.py::SystemChargeSOCLimitNumber.async_set_native_value`, `number.py::_offgrid_cloud_only_reason`, `utils.py::async_write_with_cloud_fallback`. Residual risk (`inferred`): the local-first route on resolved non-off-grid families still exceeds the tested-unit evidence scope — do not assume a local write is established on FlexBOSS21, 12kPV, or another untested target. History: escalated on [issue #558](https://github.com/joyfulhouse/eg4_web_monitor/issues/558#issuecomment-5232409553); pre-#570 the write was local-first with no family gate at all. |
| H228 | System charge voltage limit, 0.1 V | voltage-control units | `portal-correlated` | current | 1 | The source preserves raw 595 ↔ cloud 59.5 V at baseline, but the 59.5→59.4→59.5 V action/restoration is recorded only as scaled engineering values; integer register words for the changed and restored states were not preserved; target family unrecorded. `memory/voltage-param-scaling-cloud-vs-local.md`; `memory/cloud-raw-register-write-broken.md`. |
| H231 | Unknown field; historic peak-shaving/high-word label false | tested hybrid | `portal-correlated` | unresolved | 0 | Single-register reads and quantization contradict the old label; no current semantic is counted. |
| H232 | Peak-shaving period-2 power, 0.1 kW | `EG4_HYBRID` | `portal-correlated` | current | 1 | `memory/live-write-window-findings.md`; not H231’s high word. |
| H233 | Shared quick-charge/extended word; individual meanings below | hybrid/LXP local; off-grid boundary below | `verified-against-code` | structural-only | 0 | [`constants/registers.py::REGISTER_TO_PARAM_KEYS[233]`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/constants/registers.py#L961-L984) defines the structure; semantic grades remain bit- and family-specific. |
| H234 | Quick-charge duration/setpoint and active remaining time, minutes | supporting inverters | `portal-correlated` | current | 1 | `memory/quick-charge-local-control-registers.md`; paired H233+H234 start observed, but the complete raw before/after and restoration record is absent. **No off-grid write evidence exists** (the H233 boundary below proves nothing about H234). Shipped routing since the [#570 audit adversarial round 1](https://github.com/joyfulhouse/eg4_web_monitor/issues/570) (this change set): the integration's live reg-234 adjust is gated on `is_positively_non_offgrid_family` — off-grid/unresolved families store the start preference (applied as the cloud start's `minute` parameter) instead of writing the register locally. Note the off-grid live-active check is cloud-routed (#296), so no local H233 read ever gated this write. |
| H256-H259 | Generator-charge window 1-2 packed times | hybrid plus off-grid | `portal-correlated` | current | 4 | `DATA_MAPPING.md` schedule table. |
| H269-H274 | Off-grid schedule window 1-3 packed times | `EG4_HYBRID` | `portal-correlated` | current | 6 | `DATA_MAPPING.md` schedule table. |

### H110 safe bit map

| Register bit | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| H110 b0 | PV grid-off enable | lineage-wide | `lineage-inferred` | current | 1 | Canonical safe map; no reviewed raw toggle. |
| H110 b1 | Fast Zero Export | grid-tied | `portal-correlated` | current | 1 | Portal UI/key correlation; vendor key `FUNC_RUN_WITHOUT_GRID` is misleading. |
| H110 b2 | Micro-grid enable | lineage-wide | `lineage-inferred` | current | 1 | Canonical safe map. |
| H110 b3 | Shared battery | lineage-wide | `lineage-inferred` | current | 1 | Portal name exists; no complete toggle tuple. |
| H110 b4 | Charge last | lineage-wide | `lineage-inferred` | current | 1 | Canonical safe map. |
| H110 b5 | Function unknown | tested 18kPV disproof; wider applicability unresolved | `asserted-unverified` | unresolved | 0 | The b10 toggle shows b5 stayed set, refuting the historic Take Load Together label without identifying b5's actual function. [pylxpweb #242 live-capture record](https://github.com/joyfulhouse/pylxpweb/issues/242#issuecomment-5152609179). |
| H110 b6 | Function unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H110 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); historic buzzer position is refuted below. |
| H110 b7 | Buzzer enable | tested portal scope | `portal-correlated` | current | 1 | Named/raw correlation lacks full toggle tuple. |
| H110 b8 | **Function unknown** | all | `asserted-unverified` | unresolved | 0 | Only the wrong write and firmware ACK were established; it did not control Green Mode. No PVCT/CT semantic is claimed. See [contradiction C5](../60-history/open-contradictions.md) and `memory/issue-476-green-mode-bit14.md`. |
| H110 b9 | Function unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H110 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); historic ECO position is refuted below. |
| H110 b10 | Take Load Together | tested 18kPV (`SYNTH10003`) | `hardware-toggle-proven` | current | 1 | Driving EG4 cloud `functionControl` by name from True to False and back moved raw H110 `1056 → 32 → 1056`: a single b10 delta with byte-perfect restoration while b5 stayed set. Component firmware version unrecorded — scope limited to the tested unit. [pylxpweb #242 live-capture record](https://github.com/joyfulhouse/pylxpweb/issues/242#issuecomment-5152609179). Issue #242 also records that `inverter_holding.py:969-976` had tagged the wrong b5 mapping as `# verified`; code annotations may repeat a finding but are not evidence for a hardware grade. |
| H110 b11-b13 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H110 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); no accepted semantics. |
| H110 b14 | Green/Off-Grid Mode | tested 18kPV hybrid | `hardware-toggle-proven` | current | 1 | Named Green/Off-Grid Mode action and raw 1056→17440→1056 restoration; component firmware version unrecorded — scope limited to the tested unit. `memory/issue-476-green-mode-bit14.md`. |
| H110 b14 | Green/Off-Grid Mode candidate | 12000XP/6000XP | `lineage-inferred` | unresolved | 1 | Unified layout inference only; requires a family-specific controlled behavior-and-restore capture. Shipped-path fact (`verified-against-code`): `EG4OffGridModeSwitch` is appended unconditionally before the later `is_offgrid_family` check, which governs only the working-mode switches below; its on/off methods route `PARAM_FUNC_GREEN_EN` through `_execute_local_with_fallback`, so LOCAL/HYBRID can write this unresolved family mapping local-first. Code anchors: [`switch.py::_create_switch_entities`](../../custom_components/eg4_web_monitor/switch.py#L282) and [`EG4OffGridModeSwitch.async_turn_on` / `async_turn_off`](../../custom_components/eg4_web_monitor/switch.py#L1197). Safety conclusion (`inferred`): **do not treat this as a safe local write**; it is a live, un-discharged risk tracked by [issue #558](https://github.com/joyfulhouse/eg4_web_monitor/issues/558#issuecomment-5232105216) and [contradiction C7](../60-history/open-contradictions.md#c7--register-161-writability-read-only-on-flexboss-versus-a-shipped-off-grid-write-entity). |
| H110 b15 | Battery ECO | tested portal scope | `portal-correlated` | current | 1 | [`register audit` H110 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); the durable record lacks a complete named-action, family, and restoration tuple. |

### H179 safe bit map

| Register bit | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| H179 b0-b2 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H179 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); adjacent names are not accepted. |
| H179 b3 | Export PV Only / `FUNC_PV_SELL_TO_GRID_EN` | tested 18kPV and FlexBOSS21 units | `hardware-toggle-proven` | current | 1 | Named Export PV Only action and raw `0x104c→0x1044→0x104c` restoration; component firmware version unrecorded — scope limited to the tested unit. `memory/live-write-window-findings.md`. |
| H179 b4-b6 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H179 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); no accepted semantics. |
| H179 b7 | Grid peak-shaving enable | tested EG4 hybrid scope | `portal-correlated` | current | 1 | [`DATA_MAPPING.md` H179 map](../../docs/DATA_MAPPING.md); the durable record lacks a complete raw before/after pair and restoration. |
| H179 b8 | Function unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H179 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); the generator peak-shaving name is uncorroborated. |
| H179 b9 | Battery charge control: 0 SOC, 1 voltage | tested scope | `portal-correlated` | current | 1 | [`register audit` H179 map](../../docs/audits/2026-08-02-register-race-performance-audit.md) describes the 2026-02-18 toggle, but the durable raw before/after and restoration record is incomplete. |
| H179 b10 | Battery discharge control: 0 SOC, 1 voltage | tested scope | `portal-correlated` | current | 1 | Same durable audit and evidence boundary as b9. |
| H179 b11 | AC coupling function; **LOCAL writability unresolved** | lineage-wide | `lineage-inferred` | current; live write risk unresolved | 1 | Requires a named/raw lockstep toggle. Shipped-path fact (`verified-against-code`): `EG4ACCoupleSwitch._async_set_enabled` routes LOCAL/HYBRID through `_execute_local_with_fallback`; its class contract says a wrong-target write “would still ACK, which no readback can catch.” Code anchors: [`EG4ACCoupleSwitch` wrong-bit ACK contract](../../custom_components/eg4_web_monitor/switch.py#L799) and [`_async_set_enabled`](../../custom_components/eg4_web_monitor/switch.py#L959). Safety conclusion (`inferred`): **do not treat this as a safe local write**; it is a live, un-discharged risk tracked by [issue #558](https://github.com/joyfulhouse/eg4_web_monitor/issues/558) and [contradiction C7](../60-history/open-contradictions.md#c7--register-161-writability-read-only-on-flexboss-versus-a-shipped-off-grid-write-entity). |
| H179 b12-b14 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H179 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); no accepted semantics. Bit 13 is where `FUNC_SMART_LOAD_ENABLE` is *suspected* but unpinned — Smart Load stays cloud-only. |
| H179 b15 | Grid Always On / `FUNC_ON_GRID_ALWAYS_ON` | toggle-proven FlexBOSS21; family-wide extension rests on the app resolver (no per-model branch; SNA-US 12K / deviceTypeCode 54 membership corroborated by pylxpweb `docs/inverters/SNA12KUS_52XXXXXX68.json` register_blocks) | `hardware-toggle-proven` | current on tested unit; family-wide extension `app-write-path-proven` | 1 | **Toggle-proven 2026-08-12** on FlexBOSS21 SYNTH00003: portal named toggle flipped the local raw reg-179 read 0x1048 → 0x9048 — a single-bit XOR of exactly 0x8000 (bit 15) — and the restore returned 0x1048, verified via both cloud and local reads. That is the ladder's named-action + raw before/after pair + restoration minimum; component firmware version unrecorded, so the proof is scoped to the tested unit. History: originally graded `app-write-path-proven` — the EG4 mobile app `Local12KSetFragment.getBitByFunction` name→bit resolver places `FUNC_ON_GRID_ALWAYS_ON` at H179 b15 (`_179Functions` membership; investigation recorded on [#559](https://github.com/joyfulhouse/eg4_web_monitor/issues/559) / [pylxpweb PR #270](https://github.com/joyfulhouse/pylxpweb/pull/270)), decode validated 4-for-4 against independently confirmed anchors b3 (#135), b7, b9/b10 (#48). That lineage now carries the family-wide extension beyond the tested FlexBOSS21. Mapping shipped in pylxpweb ≥0.9.39b11 ([`constants/registers.py` at `ab87902`](https://github.com/joyfulhouse/pylxpweb/blob/ab87902/src/pylxpweb/constants/registers.py#L935)); the family-wide register-179 contract test guards the pin. |

### H233 safe bit map

| Register bit | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| H233 b0 | Quick-charge start enable | FlexBOSS21 local | `portal-correlated` | current | 1 | `memory/quick-charge-local-control-registers.md`; paired start/stop observed, but a complete raw before/after and restoration record is absent. |
| H233 b1 | Battery-backup control, distinct from H21 b0 EPS | tested hybrid scope | `portal-correlated` | current | 1 | [`register audit` H233 map](../../docs/audits/2026-08-02-register-race-performance-audit.md) describes the mapping without a complete durable raw before/after and restoration record. |
| H233 b2-b11 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H233 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); maintenance/weekly/over-frequency names are not accepted. |
| H233 b12 | Sporadic charge | tested portal scope | `portal-correlated` | current | 1 | [`register audit` H233 map](../../docs/audits/2026-08-02-register-race-performance-audit.md) records Web UI plus raw 0↔4096, but family and restoration fields are incomplete. It is not Quick Charge. |
| H233 b13-b15 | Functions unknown | all | `asserted-unverified` | unresolved | 0 | [`register audit` H233 map](../../docs/audits/2026-08-02-register-race-performance-audit.md); no accepted semantics. |

#### H233 off-grid access boundary

| Claim | Scope | Evidence | Status | Durable basis and qualification |
|---|---|---|---|---|
| The CEAA (12000XP lineage) holding reader/writer jumps H229→H234; an unmatched H233 access returns ILLEGAL DATA ADDRESS. | decoded CEAA image | `firmware-proven` | current | [`fw-verify-offgrid-writes` verdicts on #570](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5273044579) (2026-08-12; image sha256s in the [PR #569 comment](https://github.com/joyfulhouse/eg4_web_monitor/pull/569#issuecomment-5273044416)). Proves the #296 live rejection reports on that lineage. A negative claim proven by disassembly; scoped to the decoded CEAA build. |
| CCAA (6000XP lineage) **implements** the H233 address (reader `0x08030A2E`; writer stores the low 16 bits), but only bits 1–2 are packed toward the DSP and **no bit-0 quick-charge consumer was found** — no proven local quick-charge route exists on CCAA either. | decoded CCAA image | `firmware-proven` | current; b0 semantics unresolved | Same #570 firmware verdicts. The earlier family-wide "off-grid rejects H233" claim was too broad — it is now lineage-scoped to CEAA. |
| Live LOCAL FC03/FC06 access to H233 returned ILLEGAL DATA ADDRESS. | tested `EG4_OFFGRID` units (#296/#308 reports) | `asserted-unverified` | current | [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md#extended-function-enable-2-register-233) and [bug postmortems #296/#308](../60-history/bug-postmortems.md) record the rejection; no preserved raw request/exception-response capture exists, so the live reports stay at this grade (the firmware proof above stands on the disassembly, not on them). |
| Shipped routing: the Quick Charge switch **fails closed in every configuration** — only a positively resolved non-off-grid family keeps the local H233 route. Cloud-less off-grid/unresolved units get an unavailable switch and a forced service call raises before pylxpweb is reached (PR #569, 2026-08-13); with a cloud client, off-grid AND unresolved families go cloud-direct (#570 audit review round 4 — an unresolved unit might be a CCAA 6000XP, where the local H233 write is silently ACCEPTED with unproven bit-0 semantics, so a cloud fallback is no safety net). | current integration | `verified-against-code` | current | [PR #569](https://github.com/joyfulhouse/eg4_web_monitor/pull/569) (merged; `switch.py` → `_offgrid_without_cloud` availability gate) for the cloud-less half; the cloud-present unresolved half is part of the [#570 audit](https://github.com/joyfulhouse/eg4_web_monitor/issues/570) change set (`switch.py` → `_prefers_cloud_control`, now `not is_positively_non_offgrid_family(...) and has_http_api()`). This superseded the earlier shipped-path exposure this section recorded — pure-LOCAL off-grid toggles no longer attempt the rejected write, and unresolved-family cloud entries no longer attempt the CCAA-silent one. |

## GridBOSS register ledger

| Register(s) | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| GB-I1-I9 | Aggregate/L1/L2 grid, UPS, and generator voltages | GridBOSS | `portal-correlated` | current | 9 | `DATA_MAPPING.md` §4 versus `getMidboxRuntime`. |
| GB-I10-I17 | Grid/load/generator/UPS L1/L2 currents | GridBOSS | `portal-correlated` | current | 8 | `DATA_MAPPING.md` §4. |
| GB-I18-I25 | Smart-port 1-4 L1/L2 currents | GridBOSS | `lineage-inferred` | current | 8 | Modbus-only canonical fields. |
| GB-I26-I33 | Grid/load/generator/UPS L1/L2 active power | GridBOSS | `portal-correlated` | current | 8 | Signed W portal correlation. |
| GB-I34-I41 | Smart-port 1-4 L1/L2 active power | GridBOSS | `portal-correlated` | current | 8 | Interpret according to GB-H20 mode. |
| GB-I42-I49 | Daily load/UPS/export/import L1/L2 energy | GridBOSS | `portal-correlated` | current | 8 | 0.1 kWh values. |
| GB-I50-I51 | Asserted generator daily-energy L1/L2 | GridBOSS | `asserted-unverified` | unresolved | 0 | [`DATA_MAPPING.md` generator-energy note](../../docs/DATA_MAPPING.md#daily-energy-registers-10--kwh); current decoder calls them unused/unknown. |
| GB-I52-I59 | Smart-load ports 1-4 L1/L2 daily energy | GridBOSS | `portal-correlated` | current | 8 | `DATA_MAPPING.md` §4. |
| GB-I60-I67 | AC-couple ports 1-4 L1/L2 daily energy | GridBOSS | `portal-correlated` | current | 8 | `DATA_MAPPING.md` §4. |
| GB-I68-I83 | Load/UPS/export/import L1/L2 lifetime-energy U32 pairs | GridBOSS | `portal-correlated` | current | 8 | Low word first. |
| GB-I84-I87 | Asserted generator L1/L2 lifetime-energy U32 pairs | GridBOSS | `asserted-unverified` | unresolved | 0 | [`DATA_MAPPING.md` generator-energy note](../../docs/DATA_MAPPING.md#lifetime-energy-registers-32-bit-pairs-10--kwh); current decoder calls them unused/unknown. |
| GB-I88-I103 | Smart-load ports 1-4 L1/L2 lifetime-energy U32 pairs | GridBOSS | `portal-correlated` | current | 8 | `DATA_MAPPING.md` §4. |
| GB-I104-I119 | AC-couple ports 1-4 L1/L2 lifetime-energy U32 pairs | GridBOSS | `portal-correlated` | current | 8 | Includes I119; I105-I108 are not status. |
| GB-I128/I129/I130 | Phase-lock/grid/generator frequency | GridBOSS | `portal-correlated` | current | 3 | `DATA_MAPPING.md` §4. |
| GB-I134-I253 | Exact mirror of GB-H134-H253 | GridBOSS | `lineage-inferred` | current | 1 | Firmware quirk in canonical map; not independent runtime data. |
| GB-H20 | Four-port 2-bit smart-port-mode packing contract | GridBOSS | `portal-correlated` | current | 1 | Full owner explanation and grade: [GridBOSS register boundary](gridboss.md#smart-port-mode-register-owner). |

## Individual-battery extended input ledger

For battery index `n`, the documented base is `B = 5002 + 30n`.

| Address | Current semantic | Scope | Evidence | Status | Claim count | Durable basis and qualification |
|---|---|---|---|---|---:|---|
| B+1 | Full capacity, Ah | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+2 | Charge-voltage reference, 0.1 V | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+3 | Charge-current limit, 0.1 A | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+6 | Battery voltage, 0.01 V | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+7 | Battery current, signed 0.1 A | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+8 low/high | SOC / SOH, 1% bytes | individual battery | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §7. |
| B+9 | Cycle count | individual battery | `lineage-inferred` | current | 1 | `DATA_MAPPING.md` §7. |
| B+12/B+13 | Maximum/minimum cell voltage, 0.001 V | individual battery | `lineage-inferred` | current | 2 | `DATA_MAPPING.md` §7. |
| B+14 low/high | Maximum/minimum-temperature cell numbers | individual battery | `portal-correlated` | current | 2 | Live local/cloud capture corrected the old swap. |
| B+15 low/high | Maximum/minimum-voltage cell numbers | individual battery | `portal-correlated` | current | 2 | Same capture as B+14. |
| B5002-B5121 | Four-slot local Modbus ceiling on the captured inverter/dongle path | tested rotating-bank reports | `asserted-unverified` | current; family portability unresolved | 0 | `memory/issue-258-battery-rr-reg96-unreliable.md`: 120 registers = 4×30, explicit 5/6-slot reads returned EMPTY, wrong fifth-slot commit `962af29` reverted by `5e1e20a`. Current code’s four-block read is only `verified-against-code`, not additional hardware proof. More than four packs require rotation accumulation, cloud backfill, or direct BMS transport. |

<!-- counted-ledger:end -->

## Schedule write evidence boundary

These claims elaborate the counted schedule rows; they do not add to the ratio.

| Claim | Family scope | Evidence | Status | Durable basis |
|---|---|---|---|---|
| Each schedule block is consecutive start/end pairs: base/+1 window 1, +2/+3 window 2, and +4/+5 window 3 where configured. | Per-family `SCHEDULE_TIME_TYPES` gates | `portal-correlated` | current | [`DATA_MAPPING.md` schedule table](../../docs/DATA_MAPPING.md#schedule-time-window-registers-277--295--312) and live named-register probes. |
| Packed time is `hour \| (minute << 8)`; hour low byte, minute high byte. | Schedule families represented by the captured probes | `portal-correlated` | current | FlexBOSS21/SNA probes plus `time.py::_decode_from_cache`; example 01:05 → H211 raw 1281. |
| Current LOCAL/HYBRID schedule writes issue one packed-register call documented as Modbus FC06 through `EG4ScheduleTimeEntity._async_set_value_locked()` and `EG4DataUpdateCoordinator.write_register()` — since the #570 audit review round 5 (part of the PR #600 change set) only on a positively resolved non-off-grid family; off-grid/unresolved families route through that schedule's own cloud write path — writeTime families (Generator/Off-Grid/Peak Shaving, including an off-grid inverter's Generator Charge schedule) use the atomic `write_time_parameter` portal call, classic families (AC Charge/First, Forced Charge/Discharge) use the per-field hour/minute writes (routing corrected in review round 10; an earlier revision said "classic cloud field writes" for all of them) — and a pure-LOCAL install raises. | Current integration path | `verified-against-code` | current | [`time.py`](../../custom_components/eg4_web_monitor/time.py) and [`coordinator.py`](../../custom_components/eg4_web_monitor/coordinator.py); no transport wire capture is claimed. The schedule rows above are `portal-correlated` from CLOUD probes — no local off-grid schedule write evidence exists, which is what the fail-closed routing encodes (#563's clear-schedule button recorded the same posture first). |

No raw wire evidence establishes a firmware-level FC16 rejection. The current integration’s single-register FC06 path is `verified-against-code`; the rejection comment remains `asserted-unverified` and is not a hardware claim.

## Keeper notes

### I67 `0x7F` sentinel

| Fact | Evidence | Status | Boundary |
|---|---|---|---|
| I67 is the battery-temperature word. | `portal-correlated` | current | Local I67 and cloud `tBat` feed the same field in current mappings. |
| Raw `0x007f`/127 represents no battery-temperature reading on a no-BMS secondary. | `portal-correlated` | current | Normalize only this field to unknown; do not publish 127 °C or confuse it with register I127. |
| No qualifying induced before/after raw capture is present in the cited durable record. | `asserted-unverified` | unresolved | This is an evidence-inventory absence claim, not code behavior; a code citation cannot prove that no capture exists. |
| pylxpweb normalizes the exact battery-temperature value 127 to `None` on every construction path. | `verified-against-code` | current | [`data.py` at `204b95d`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/transports/data.py#L62-L70) defines the sentinel; [`__post_init__`](https://github.com/joyfulhouse/pylxpweb/blob/204b95d/src/pylxpweb/transports/data.py#L312-L321) performs the normalization. This code fact does not upgrade the hardware observation. |

### Four-slot individual-battery ceiling

| Fact | Evidence | Status | Boundary |
|---|---|---|---|
| The captured inverter/dongle Modbus path exposes at most four 30-register battery slots, B5002-B5121. | `asserted-unverified` | current; portability unresolved | Durable narrative: `memory/issue-258-battery-rr-reg96-unreliable.md`; the raw capture files are not in this repository. |
| Explicit fifth/sixth-slot probe reads returned EMPTY; the attempted fifth-slot implementation was reverted. | `asserted-unverified` | current | `memory/issue-258-battery-rr-reg96-unreliable.md`; do not restate `DATA_MAPPING.md`’s “max 5” as established hardware fact. |
| Systems with >4 packs may surface more identities through reported firmware rotation. | `asserted-unverified` | unresolved | No endpoint, field, widget, or preserved portal agreement is cited. Rotation is firmware-dependent and its trigger remains unknown; accumulate observed identities by serial, but do not treat slot count as physical pack count. |

## Must-not-regress register claims

These historic claims are excluded from the 346-current-claim denominator. `refuted` is a status; **Evidence** grades the disproof.

| Historic claim | Evidence | Status | Current bounded result | Durable basis |
|---|---|---|---|---|
| H110 b8 is Green/Off-Grid Mode. | `portal-correlated` | refuted | H110 b8 is **UNKNOWN**. The wrong b8 write was ACKed and did not control Green Mode; no PVCT/CT function is claimed. H110 b14 is `hardware-toggle-proven` on the tested 18kPV unit. | [Contradiction C5](../60-history/open-contradictions.md); `memory/issue-476-green-mode-bit14.md`. |
| H110 b5 is Take Load Together. | `hardware-toggle-proven` | refuted | The named Take Load Together control toggled b10 while b5 stayed set throughout; b10 was restored byte-perfectly. | [pylxpweb #242 live-capture record](https://github.com/joyfulhouse/pylxpweb/issues/242#issuecomment-5152609179). |
| H110 b6 is Buzzer. | `portal-correlated` | refuted | Current candidate is b7; b6 is unknown. | Safe register map and portal correlation. |
| H110 b9 is Battery ECO. | `portal-correlated` | refuted | Current candidate is b15; b9 is unknown. | Safe register map and raw correlation. |
| 12000XP/off-grid I123 is generator power. | `firmware-proven` | refuted | It is an ARM-initialization counter modulo 65,536 with nominal ~1 Hz increment. | `OFFGRID_GENERATOR_REGISTERS.md`. |
| Off-grid I124-I126 are generator energy. | `firmware-proven` | refuted | I124 is status/metadata; I125-I126 are one U32 status word. | `OFFGRID_GENERATOR_REGISTERS.md`. |
| Hybrid I131/I132 are L1/L2 apparent power. | `firmware-proven` | refuted | I131 is a sign-split DSP quantity; I132 is an event counter. Exact I131 physical label remains unresolved. | `HYBRID_EPS_REGISTERS.md`. |
| I21/I22 are usable EPS S/T voltage on observed US split-phase hardware. | `firmware-proven` | refuted | Decoded values are not those voltages; exact replacement semantics remain unresolved. | Both EPS firmware analyses. |
| I129/I130 represent only the EPS-load subset. | `firmware-proven` | refuted | They are combined backup-path L1/L2 active power on off-grid firmware. | `OFFGRID_EPS_REGISTERS.md` plus `DATA_MAPPING.md` backup-output comparison. |
| I171/I172-I173 are whole-home consumption. | `portal-correlated` | refuted | They are inverter-served `Eload_day` / `Eload_all`. | `DATA_MAPPING.md` consumption-vs-load-energy section. |
| I32/I48-I49 `Erec` is load energy. | `portal-correlated` | refuted | It is AC/grid charge energy. | `DATA_MAPPING.md` `Erec` correction. |
| GridBOSS I105-I108 carry smart-port status. | `portal-correlated` | refuted | GB-H20 carries mode; GB-I104-I119 are energy words. | [GridBOSS owner note](gridboss.md#smart-port-mode-register-owner). |
| H21 contains grid peak-shaving enable. | `portal-correlated` | refuted | Current correlated enable is H179 b7. | `DATA_MAPPING.md` H179 section. |
| H231 is peak-shaving power or a high word. | `portal-correlated` | refuted | H206/H232 are period-1/period-2 power; H231 meaning is unknown. | `memory/live-write-window-findings.md` and canonical holding map. |
| H103 is a percentage. | `portal-correlated` | refuted | Raw units are 100 W and portal/UI displays kW. | `DATA_MAPPING.md` H103 raw/UI examples. |
| H66 is a percentage. | `portal-correlated` | refuted | Raw units are 100 W and portal/UI displays kW. | `DATA_MAPPING.md` power-control section. |
| I67 raw 127 is 127 °C or means register I127. | `portal-correlated` | refuted | It is the no-temperature sentinel value inside I67. | I67 keeper note above. |
| B+14/B+15 use the old swapped cell-index map. | `portal-correlated` | refuted | B+14 is temperature cell numbers; B+15 is voltage cell numbers. | `DATA_MAPPING.md` live local/cloud capture. |
| H64 is the PV-charge power entity target. | `portal-correlated` | refuted | H64 remains a legacy percent command; current PV-charge power target is H74. | `DATA_MAPPING.md` H64/H74 correction. |

## Peak-shaving current map

| Function | Register | Evidence | Status | Qualification |
|---|---|---|---|---|
| Enable | H179 b7 | `portal-correlated` | current | Complete raw before/after and restoration record is absent. |
| Period-1 power / SOC / voltage | H206 / H207 / H208 | `portal-correlated` | current | H206 is 0.1 kW. |
| Period-2 SOC / voltage / power | H218 / H219 / H232 | `portal-correlated` | current | H231 is not a high word. |
| Two schedule windows | H209-H212 | `portal-correlated` | current | Packed time; family-gated to `EG4_HYBRID`. |

## Source hierarchy

The canonical vocabulary and ladder live in the [llmwiki README](../README.md#evidence-grade-legend). For this ledger, implementation tables and `DATA_MAPPING.md` cannot by themselves establish a hardware semantic. Passing tests establish software consistency only; they never promote a register mapping to `hardware-toggle-proven`.

Detailed derivations remain in [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md), [`OFFGRID_GENERATOR_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md), [`OFFGRID_EPS_REGISTERS.md`](../../docs/reference/firmware/OFFGRID_EPS_REGISTERS.md), and [`HYBRID_EPS_REGISTERS.md`](../../docs/reference/firmware/HYBRID_EPS_REGISTERS.md), subject to this page’s precedence and grades.
