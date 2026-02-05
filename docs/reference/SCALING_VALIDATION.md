# Scaling Validation Guide

This document describes how to validate data scaling between cloud API, Modbus, and end-user display to prevent recurring scaling bugs.

## Architecture Overview

Data flows through multiple scaling layers:

```
Cloud API (raw values) → pylxpweb/constants/scaling.py → Home Assistant entities
Modbus registers → pylxpweb/transports/register_maps.py → Home Assistant entities
```

Both paths should produce **identical values** for the same physical measurement.

## Validation Process

### Step 1: Capture Cloud Reference Values

Use the EG4 web portal as the **authoritative reference**. The portal displays correctly scaled values.

**Key reference points to capture:**
- BMS Limit Charge/Discharge (A)
- Bus Voltages (V)
- Battery Voltage (V)
- Grid/EPS Voltages (V)
- Power values (W)
- Current values (A)
- SOC (%)

### Step 2: Compare with Local (Modbus) Values

Run in LOCAL mode and compare entity values against cloud reference:

```bash
# Switch to local mode
./scripts/eg4-switch-mode.sh local
docker restart homeassistant-dev

# Test Modbus scaling directly
docker exec homeassistant-dev python3 -c "
import asyncio
from pylxpweb.transports import create_transport
from pylxpweb.devices.inverters._features import InverterFamily

async def test():
    transport = create_transport(
        'modbus',
        host='INVERTER_IP',
        serial='SERIAL_NUMBER',
        port=502,
        unit_id=1,
        inverter_family=InverterFamily.EG4_HYBRID
    )
    await transport.connect()
    data = await transport.read_runtime()

    # Print values to compare with cloud
    print(f'bms_charge_current_limit: {data.bms_charge_current_limit} A')
    print(f'bms_discharge_current_limit: {data.bms_discharge_current_limit} A')
    print(f'bus_voltage_1: {data.bus_voltage_1} V')
    print(f'bus_voltage_2: {data.bus_voltage_2} V')
    print(f'battery_voltage: {data.battery_voltage} V')
    print(f'battery_soc: {data.battery_soc} %')

    await transport.disconnect()

asyncio.run(test())
"
```

### Step 3: Identify Scaling Discrepancies

| Symptom | Likely Cause | Fix Location |
|---------|--------------|--------------|
| Local value 10x too high | Using SCALE_1 instead of SCALE_10 | register_maps.py |
| Local value 10x too low | Using SCALE_100 instead of SCALE_10 | register_maps.py |
| Local value 100x too low | Using SCALE_1000 instead of SCALE_10 | register_maps.py |
| Cloud value 10x wrong | Incorrect API field scaling | scaling.py |

## Scaling Constants Reference

From `pylxpweb/constants/scaling.py`:

| ScaleFactor | Divisor | Use Case |
|-------------|---------|----------|
| SCALE_1 | 1 | Raw integers (status codes, counts) |
| SCALE_10 | 10 | Most voltages, currents, frequencies |
| SCALE_100 | 100 | Some high-precision values |
| SCALE_1000 | 1000 | Energy values (kWh) |

## Known Discrepancies vs Documentation

### Modbus Protocol PDF Errors

The official LuxPower/EG4 Modbus documentation contains errors. **Always validate empirically:**

| Register | PDF Says | Actual | Notes |
|----------|----------|--------|-------|
| 81 (MaxChgCurr) | 0.01A (SCALE_100) | 0.1A (SCALE_10) | BMS charge limit |
| 82 (MaxDischgCurr) | 0.01A (SCALE_100) | 0.1A (SCALE_10) | BMS discharge limit |

### Cloud API Scaling

The cloud API returns raw values that need client-side scaling. The EG4 web portal JavaScript applies:
- Voltages: ÷10
- Frequencies: ÷100
- Currents: direct (no scaling) or ÷10 depending on field

## Validation Checklist

Before releasing scaling changes:

- [ ] Cloud value matches EG4 web portal display
- [ ] Local (Modbus) value matches cloud value (±1% tolerance for timing)
- [ ] Hybrid mode shows consistent values
- [ ] All inverter families tested (EG4_HYBRID, EG4_OFFGRID, LXP, GridBOSS)
- [ ] Individual battery sensors match expected per-battery values
- [ ] Parallel group aggregates sum correctly

## Common Pitfalls

1. **Per-battery vs Total**: BMS limits from Modbus may be per-battery or total depending on register
2. **Inactive Systems**: Low bus voltages are normal when no solar/load (don't assume scaling error)
3. **Model Differences**: Different inverter families may use different register layouts
4. **Documentation Trust**: Never trust PDF documentation without empirical validation

## Files to Modify

| Issue Type | File |
|------------|------|
| Cloud API scaling | `pylxpweb/src/pylxpweb/constants/scaling.py` |
| Modbus scaling | `pylxpweb/src/pylxpweb/transports/register_maps.py` |
| Entity mapping | `eg4_web_monitor/custom_components/eg4_web_monitor/sensor.py` |
