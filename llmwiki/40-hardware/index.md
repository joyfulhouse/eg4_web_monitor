# 40-hardware — registers and firmware

## Pages

* [Register ground truth](registers.md) - **The register keeper.** Per-row evidence grades for every inverter and GridBOSS register. Authoritative for any register question. Owns: Inverter and GridBOSS register ground truth.
* [GridBOSS / POWER_HUB UART map](gridboss.md) - GridBOSS specifics, including the smart-port mode register. Owns: GridBOSS POWER_HUB UART map; smart-port mode packing and reported mode-write side effects.
* [Firmware reverse engineering](firmware-re.md) - Firmware acquisition/decoding methodology, invalid-artifact boundaries, and ESP32 WLAN local-listener analysis. Owns: Acquisition, decoding and register-RE methodology; ESP32 WLAN listener behaviour and patch lineage.
* [Dongle emulation](dongle-emulation.md) - Local-transport-only phased contract for replacing a physical WLAN dongle; every eligible mode is single-path and HYBRID adds cloud-echo controls; no port-8000 listener. Owns: Dongle-emulation product boundary; single-owner arbitration and snapshots; mode eligibility and anti-loopback; security, rollout, rollback and success criteria.
* [Register probing playbook](probing-playbook.md) - The safe procedure for dumping and verifying registers on live hardware. **Runbook — read before touching a device.** Owns: Safe register dumping and live verification.
* [Open hardware and firmware questions](open-questions.md) - What evidence would resolve each open hardware question. Owns: Evidence needed to resolve open hardware and firmware questions.
