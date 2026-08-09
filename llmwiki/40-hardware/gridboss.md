---
canonical-for: gridboss-power-hub-uart-map
sources:
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - docs/CONFIGURATION.md
  - docs/DATA_MAPPING.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
  - memory/gridboss-powerhub-uart-map.md
verified-against: 9f6d6e2
last-verified: 2026-08-09
---

# GridBOSS / POWER_HUB UART map

> **Only USART3 is initialized by the reviewed POWER_HUB application image `IAAB-16xx_20250925_APP_preENC.hex`. UART4 contains dormant second-RS485 plumbing, but no DIP switch, GPIO input, or serial-dispatch path can enable it. Its external connector routing is unknown.** Evidence: `firmware-proven` for the image-scoped behavior at the concrete code sites below; `asserted-unverified` for physical connector routing.

## Firmware-visible serial map

| Function | MCU peripheral and pins | Initialization / protocol | Evidence grade | Image and concrete code sites |
|---|---|---|---|---|
| Live dongle/panel RS485 bus | USART3: PD8 TX, PD9 RX, PD10 DE/RE | Initialized once; 19,200 baud, 8N1, half-duplex; RXNE and TC interrupts | `firmware-proven` | `IAAB-16xx_20250925_APP_preENC.hex`: `USART_Init` at `fcn.08023C1A` has one image-wide caller; logical-port-2 ISR `0x0802D555`; PD10 direction function `fcn.08018FC4`. `memory/gridboss-powerhub-uart-map.md`. |
| Dormant second RS485 plumbing | UART4; PD0 behaves as DE | ISR, buffers, and direction plumbing exist; peripheral clock, UART pin init, baud setup, and consumer are absent | `firmware-proven` | Same image: UART4 ISR `0x0802D893`; PD0 direction function `fcn.08018FE8`; RCC helper enumeration at `fcn.080232FE` / `fcn.0802331E` finds no UART4 clock enable. `memory/gridboss-powerhub-uart-map.md`. |
| PARALLEL RJ45 pair | CAN1: PB8/PB9 | CAN bus | `firmware-proven` | Same image: CAN1 setup/dispatch site `fcn.08018726` with real RX0/RX1 handlers. `memory/gridboss-powerhub-uart-map.md`. |
| USART1 and USART2 | Peripheral handlers exist | Never clocked/initialized by the reviewed application | `firmware-proven` | Same image: USART1 ISR `0x0802D5E3`, USART2 ISR `0x0802D671`, plus the RCC helper enumeration above. Presence of a handler does not imply an initialized connector. `memory/gridboss-powerhub-uart-map.md`. |

## Why a DIP cannot enable UART4

| Check | Firmware result | Evidence grade | Image and concrete code sites | Consequence |
|---|---|---|---|---|
| RCC/peripheral-clock tracing | No input-controlled path reaches UART4 clock enable. | `firmware-proven` | `IAAB-16xx_20250925_APP_preENC.hex`: APB2/APB1 RCC helpers `fcn.080232FE` / `fcn.0802331E`; exhaustive callers enable USART3 but not UART4. | UART4 remains unclocked. |
| GPIO-input tracing | No DIP or other input reaches UART4 pin initialization. | `firmware-proven` | Same image: input consumers `fcn.0801EBD0` and `fcn.080279C0` feed telemetry/mode packing, not RCC, `USART_Init`, or UART dispatch. | No firmware-visible switch selects UART4 pins. |
| Baud/init call graph | No input reaches a UART4 baud/configuration call. | `firmware-proven` | Same image: `USART_Init` at `fcn.08023C1A` has one image-wide call, for USART3. | A switch cannot turn the dormant plumbing into 19,200 8N1. |
| Serial dispatch | No input selects a UART4 consumer; application traffic stays on logical port 2/USART3. | `firmware-proven` | Same image: logical-port-2 ISR `0x0802D555`; dormant UART4 ISR `0x0802D893`; input consumers above do not reach port dispatch. | There is no hidden runtime port-selection path. |
| Red DIP blocks are passive 120 Ω termination | Consistent with observed behavior, but firmware cannot prove the PCB component value/function. | `lineage-inferred` | No firmware code site can prove a passive PCB component’s resistance or routing. | Confirm electrically or from the schematic before treating this physical interpretation as fact. |

The function/ISR addresses above are the analysis labels preserved with the identified image. They scope these claims to that artifact; the complete POWER_HUB load base and section map remain unresolved in [`FIRMWARE_ACQUISITION.md`](../../docs/reference/firmware/FIRMWARE_ACQUISITION.md).

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
