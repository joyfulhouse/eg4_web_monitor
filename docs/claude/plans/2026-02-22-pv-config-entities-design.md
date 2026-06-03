# PV Configuration Entities Design

**Date**: 2026-02-22
**Registers**: Holding 20 (PV Input Mode), Holding 22 (PV Start Voltage)
**Status**: Approved

## Context

Two inverter-specific PV configuration parameters need HA entity exposure:

1. **PV Input Mode** (reg 20) — which MPPT channels are active (0-7 enum)
2. **PV Start Voltage** (reg 22) — minimum PV voltage for MPPT engagement (140-500V)

Both registers are already defined in pylxpweb (`inverter_holding.py`) with API param keys
`HOLD_PV_INPUT_MODE` and `HOLD_START_PV_VOLT`. Neither has a dedicated high-level control
method — writes use the generic `write_parameter()` / `write_named_parameter()` path.

Live Modbus validation confirmed:
- Register 20 = 4 ("PV1&2 in") — matches cloud select value
- Register 22 = 1400 (raw) → 140.0V — matches cloud `valueText=140`

## Design

### PV Start Voltage — Number Entity

- **Class**: `PVStartVoltageNumber(EG4BaseNumberEntity)`
- **Range**: 140-500V, step 1V (firmware rejects <140V with error code 3)
- **Scale**: Register stores decivolts (/10). Cloud API takes human-readable volts.
- **Read**: `_read_param_value(param_key="HOLD_START_PV_VOLT", param_transform=lambda v: float(v) / 10.0)`
- **Write local**: `write_named_parameter("HOLD_START_PV_VOLT", int(value * 10))`
- **Write cloud**: `client.api.control.write_parameter(serial, "HOLD_START_PV_VOLT", str(int(value)))`

### PV Input Mode — Select Entity

- **Class**: `EG4PVInputModeSelect(CoordinatorEntity, SelectEntity)`
- **Options**: 8 modes (0="NO PV" through 7="PV1 & PV2 & PV3")
- **Read**: From `coordinator.data["parameters"][serial]["HOLD_PV_INPUT_MODE"]`
- **Write local**: `write_named_parameter("HOLD_PV_INPUT_MODE", int_value)`
- **Write cloud**: `client.api.control.write_parameter(serial, "HOLD_PV_INPUT_MODE", str(int_value))`
- **Dual-path**: Both local and cloud writes supported based on user's connection type

### Files Modified

1. `coordinator_local.py` — Add `(20, 3)` register range to `_read_modbus_parameters()`
2. `const/modbus.py` — Add `PARAM_HOLD_PV_INPUT_MODE`, `PARAM_HOLD_START_PV_VOLT`
3. `const/limits.py` — Add `PV_START_VOLTAGE_MIN/MAX/STEP`
4. `const/__init__.py` — Export new constants
5. `number.py` — Add `PVStartVoltageNumber` class
6. `select.py` — Add `EG4PVInputModeSelect` class with dual local/cloud write
7. `strings.json` — Add number + select translations
8. `translations/en.json` — Mirror strings.json
