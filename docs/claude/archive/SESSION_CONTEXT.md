# Session Context - Bug Fix Planning

## Dev Environment

**Container**: `homeassistant-dev` on Docker
**Compose**: `/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/docker-compose.yaml`
**Switch modes**: `./scripts/eg4-switch-mode.sh cloud|local|hybrid`
**Check mode**: `grep ":/config" docker-compose.yaml | head -1`

**Volume mappings**:
- `./eg4_web_monitor/custom_components/eg4_web_monitor` → `/config/custom_components/eg4_web_monitor`
- `../python/pylxpweb/src/pylxpweb` → `/usr/local/lib/python3.13/site-packages/pylxpweb`

## Mode Comparison Results

| Mode | Entities | Notes |
|------|----------|-------|
| Cloud | 451 | Baseline reference |
| Local | 415 | Missing 70 cloud entities, has 34 unique local sensors |
| Hybrid | 452 | Full cloud parity + transport_ip_address |

## P1 Bugs to Fix

### eg4-y8m: AC Couple sensors unavailable in Hybrid (GitHub #128)
- **Root cause**: Smart port status registers return 0 via WiFi dongle, correct via cloud
- **Location**: `coordinator_mixins.py` - sensor filtering logic
- **Fix**: Use cloud data for smart_port_status detection in hybrid mode

### eg4-c0p: Battery data missing in Local for LuxPower (GitHub #129)
- **Root cause**: battery_count=0 in local mode, no BMS Modbus sensors
- **Related to #128**: Both involve local transport missing data cloud provides
- **Investigation**: Check 5000+ register range, Modbus 80-107, 108-112

### eg4-f8n: bus_1_voltage scaling (10x too low in cloud)
- Cloud: 1.34V, Local/Hybrid: 13.4V
- Cloud value needs 10x scaling

### eg4-5qb: max_charge_current scaling discrepancy
- Cloud: 200.0A, Local/Hybrid: 20.0A
- One source has incorrect 10x scaling

## P2 Bugs

- `eg4-vi9`: battery_type empty in Local (returns "" instead of "Lithium")
- `eg4-p3a`: remaining_capacity zero in Local (returns 0.0 instead of Ah values)
- `eg4-zkx`: Parallel Group B duplication in Local mode

## Key Files

- **Coordinator**: `custom_components/eg4_web_monitor/coordinator.py`
- **Coordinator Mixins**: `custom_components/eg4_web_monitor/coordinator_mixins.py`
- **Sensor filtering**: Look for `Removing * Smart Port sensors based on status`
- **pylxpweb MID device**: `../python/pylxpweb/src/pylxpweb/devices/mid_device.py`
- **pylxpweb transports**: `../python/pylxpweb/src/pylxpweb/transports/`

## Test Devices

- **18KPV** (4512670118) - 3 batteries
- **FlexBOSS21** (52842P0581) - 3 batteries
- **GridBOSS** (4524850115) - MID device

## Reference Docs

- `docs/claude/MODE_COMPARISON_REPORT.md` - Full entity comparison
- `.env` - Environment documentation
- `CLAUDE.md` - Project documentation
