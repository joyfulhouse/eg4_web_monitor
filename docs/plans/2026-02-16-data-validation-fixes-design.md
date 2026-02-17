# Data Validation Fixes - Issue #158

## Problem

Users experience data spikes (energy yield dipping, battery count = 5421) even with
data validation enabled. Enabling validation breaks GridBOSS updates entirely, creating
a catch-22: validation ON = GridBOSS dead, validation OFF = corrupt data passes through.

## Root Causes

1. **battery_bank_count has no canary**: Register 96 can return garbage (5421) with no
   bounds check in `BatteryBankData.is_corrupt()`.
2. **battery_current has no canary**: Current of 2996A passes through unchecked.
3. **Energy monotonicity gated by validate_data toggle**: The `_is_energy_valid()` method
   short-circuits when `validate_data=False`, allowing lifetime counters to decrease
   (physically impossible).
4. **GridBOSS canary false positive**: Unknown which canary triggers; needs user logs.

## Design

### Fix 1: Battery bank canaries (pylxpweb)

Add to `BatteryBankData.is_corrupt()`:
- `battery_count > BATTERY_MAX_COUNT` (currently 5) → corrupt
- `abs(current) > 500` → corrupt (max physical: ~300A at 5 batteries)

### Fix 2: Always-on energy monotonicity (pylxpweb)

Remove the `validate_data` gate from `_is_energy_valid()` in `BaseDevice`.
Energy monotonicity is physically guaranteed — lifetime kWh counters CANNOT decrease.
This is NOT a heuristic that could false-positive. It should always be active.

The `validate_data` toggle continues to control:
- `InverterRuntimeData.is_corrupt()` (power/frequency/SoC canaries)
- `BatteryBankData.is_corrupt()` (SoC/SoH/count/current canaries)
- `MidboxRuntimeData.is_corrupt()` (voltage/frequency/smart port canaries)

### Fix 3: GridBOSS diagnostic logging

Add per-canary WARNING-level logging to `MidboxRuntimeData.is_corrupt()` so the specific
false-positive trigger is visible in user logs. Current logging is DEBUG level, which
most users don't capture.

## Files Changed

### pylxpweb (library)
- `src/pylxpweb/transports/data.py` — BatteryBankData.is_corrupt() canaries
- `src/pylxpweb/devices/base.py` — Remove validate_data gate from _is_energy_valid()
- `src/pylxpweb/devices/mid_device.py` — Improve is_corrupt rejection logging
- `tests/unit/transports/test_data_corruption.py` — New canary tests

### eg4_web_monitor (HA integration)
- No changes needed (validation logic lives in pylxpweb)
