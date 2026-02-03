# Modbus Protocol Documentation References

## EG4 18KPV / FlexBOSS / 12LV Series

**Source**: https://www.dth.net/solar/luxpower/modbus/EG4-18KPV-12LV-Modbus-Protocol.pdf

### Known Documentation Discrepancies

| Register | Documented Scale | Actual Scale | Notes |
|----------|------------------|--------------|-------|
| 81 (MaxChgCurr) | 0.01A | **0.1A** | BMS charge current limit per battery |
| 82 (MaxDischgCurr) | 0.01A | **0.1A** | BMS discharge current limit per battery |

### Verified Scaling (from empirical testing)

- **Registers 81-82**: Use SCALE_10 (÷10), not SCALE_100 as documented
- **Per-battery value**: 200A × 3 batteries = 600A total BMS limit

### Individual Battery Data

Per the user's FlexBOSS21 with 3× WP-16/280-1AWLL batteries:
- Each battery reports ~200A charge/discharge limit
- Total system BMS limit: 600A
- User-configured charge current limit: 250A
