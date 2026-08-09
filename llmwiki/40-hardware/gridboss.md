---
canonical-for: gridboss-power-hub-uart-map
sources:
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - docs/CONFIGURATION.md
  - docs/DATA_MAPPING.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# GridBOSS / POWER_HUB UART map

> **Only USART3 is initialized by the reviewed POWER_HUB application firmware. UART4 contains dormant second-RS485 plumbing, but no DIP switch, GPIO input, or serial-dispatch path can enable it. Its external connector routing is unknown.** Evidence: `firmware-proven` for the decoded application behavior; `asserted-unverified` for physical connector routing.

## Firmware-visible serial map

| Function | MCU peripheral and pins | Initialization / protocol | Evidence grade | Qualification |
|---|---|---|---|---|
| Live dongle/panel RS485 bus | USART3: PD8 TX, PD9 RX, PD10 DE/RE | Initialized once; 19,200 baud, 8N1, half-duplex; RXNE and TC interrupts | `firmware-proven` | Every application serial call uses logical port 2, which resolves to USART3. |
| Dormant second RS485 plumbing | UART4; PD0 behaves as DE | ISR, buffers, and direction plumbing exist; peripheral clock, UART pin init, baud setup, and consumer are absent | `firmware-proven` | Dormant code is not a usable second application port. |
| PARALLEL RJ45 pair | CAN1: PB8/PB9 | CAN bus | `firmware-proven` | It is not the dormant UART4 Modbus connection. |
| USART1, USART2, UART5 | Peripheral symbols may exist | Never clocked/initialized by the reviewed application | `firmware-proven` | Do not infer a connector from MCU capability alone. |

## Why a DIP cannot enable UART4

| Check | Firmware result | Evidence grade | Consequence |
|---|---|---|---|
| RCC/peripheral-clock tracing | No input-controlled path reaches UART4 clock enable. | `firmware-proven` | UART4 remains unclocked. |
| GPIO-input tracing | No DIP or other input reaches UART4 pin initialization. | `firmware-proven` | No firmware-visible switch selects UART4 pins. |
| Baud/init call graph | No input reaches a UART4 baud/configuration call. | `firmware-proven` | A switch cannot turn the dormant plumbing into 19,200 8N1. |
| Serial dispatch | No input selects a UART4 consumer; application traffic stays on logical port 2/USART3. | `firmware-proven` | There is no hidden runtime port-selection path. |
| Red DIP blocks are passive 120 Ω termination | Consistent with observed behavior, but firmware cannot prove the PCB component value/function. | `lineage-inferred` | Confirm electrically or from the schematic before treating this physical interpretation as fact. |

“No firmware-visible DIP enable” is stronger and narrower than “the board cannot ever use UART4.” Purpose-built modified firmware could clock and configure the dormant peripheral if the PCB actually routes it, but the stock application does not.

## What firmware cannot answer

| Unknown | Current evidence grade | Evidence required |
|---|---|---|
| Which external connector, test pad, or transceiver—if any—carries UART4 TX/RX/DE | `asserted-unverified` | The reviewed image boundary is recorded in [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md); settlement requires PCB continuity, a schematic, or scoped traffic under separately authorized diagnostic firmware. |
| UART4 electrical polarity, termination, and connector pinout | `asserted-unverified` | [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) cannot establish PCB routing; settlement requires schematic/board tracing and electrical measurement. |
| Exact purpose intended by the dormant UART4 code | `asserted-unverified` | The current POWER_HUB artifact list is in [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md); settlement requires symbols/design documentation or a reachable consumer in another validated build. |
| Exact MCU/package topology beyond the decoded application behavior | `asserted-unverified` | [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md) records only the image family; settlement requires part marking, schematic, and a validated full image/load map. |

Do not use UART4 dormancy to infer an inverter-side UART map. The reviewed finding is specific to GridBOSS/POWER_HUB. The inverter↔dongle external bus is separately documented as 19,200 8N1 half-duplex RS485 in [`CONFIGURATION.md`](../../docs/CONFIGURATION.md), but no reviewed source establishes the inverter ARM MCU’s internal USART pins. Evidence: `lineage-inferred` for the external wiring; `asserted-unverified` for inverter MCU routing.

## Smart-port mode register owner

This section is canonical for the GB-H20 packing and its grade. GridBOSS serial hardware and register semantics remain separate proof questions.

| Port | GB-H20 field | Value `0` | Value `1` | Value `2` | Value `3` | Evidence |
|---:|---|---|---|---|---|---|
| 1 | b0-b1 | Unused | Smart load | AC couple | Reserved/unknown | `portal-correlated` |
| 2 | b2-b3 | Unused | Smart load | AC couple | Reserved/unknown | `portal-correlated` |
| 3 | b4-b5 | Unused | Smart load | AC couple | Reserved/unknown | `portal-correlated` |
| 4 | b6-b7 | Unused | Smart load | AC couple | Reserved/unknown | `portal-correlated` |

The full-word decoding is `mode(port) = (GB-H20 >> (2 × (port - 1))) & 0x3`. It remains `portal-correlated`, not `hardware-toggle-proven`: the durable evidence does not contain the complete named-action, target-family, raw-before/raw-after, and restoration tuple for all four fields. [`DATA_MAPPING.md`](../../docs/DATA_MAPPING.md) owns the implementation derivation; [registers.md](registers.md) owns the register-ledger count.

| Register fact | Evidence grade | Boundary |
|---|---|---|
| GB-H20 packs four 2-bit smart-port modes. | `portal-correlated` | Port 1 uses b0-b1 through port 4 b6-b7; value 3 remains reserved/unknown. |
| GB-I104-I119 are AC-couple lifetime-energy words. | `portal-correlated` | GB-I105-I108 are therefore not the smart-port status source. |
| GB-I18-I25 carry smart-port currents. | `lineage-inferred` | These are Modbus-only in the current map; the UART decode does not independently prove their units/semantics. |

See [registers.md](registers.md) for the family-scoped register ledger and evidence accounting.
