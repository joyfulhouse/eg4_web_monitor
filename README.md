# EG4 Inverter Home Assistant Integration

A comprehensive Home Assistant custom component for monitoring EG4 Solar Inverters and GridBOSS devices through the EG4 Monitor web API.

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![HACS][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

## Features

### 🔋 **Complete Device Support**
- **Standard Inverters**: FlexBOSS21, FlexBOSS18, 18KPV, 12KPV, XP series
- **GridBOSS Devices**: Comprehensive microgrid interconnection monitoring
- **Individual Batteries**: Per-battery monitoring with detailed metrics

### 📊 **Comprehensive Monitoring**
- **Real-time Data**: Power, voltage, current, temperature, frequency
- **Energy Statistics**: Daily, monthly, yearly generation and consumption
- **Battery Management**: State of charge, health, voltage, temperature per battery
- **Grid Integration**: Import/export tracking, grid status monitoring
- **Smart Load Management**: GridBOSS smart port monitoring and control

### 🏠 **Multi-Station Architecture**
- Support for multiple solar installations per account
- Hierarchical device organization: Station → Parallel Groups → Inverters → Batteries
- Intelligent device discovery and configuration

### ⚡ **Advanced GridBOSS Features**
- Grid interconnection monitoring (L1/L2 phases)
- UPS and backup load management
- Smart load port configuration (4 configurable ports)
- AC coupling and solar integration
- Generator monitoring and control
- Phase lock frequency tracking

## Installation

### HACS (Recommended)

1. **Add Custom Repository**:
   - In HACS, go to "Integrations" 
   - Click the three dots menu → "Custom repositories"
   - Add URL: `https://github.com/joyfulhouse/eg4_inverter`
   - Category: "Integration"
   - Click "Add"

2. **Install Integration**:
   - Search for "EG4 Inverter" in HACS
   - Click "Download"
   - Restart Home Assistant

### Manual Installation

1. **Download Integration**:
   ```bash
   cd /config/custom_components
   git clone https://github.com/joyfulhouse/eg4_inverter.git eg4_inverter
   ```

2. **Restart Home Assistant**:
   - Settings → System → Restart

## Configuration

### Step 1: Add Integration

1. Go to **Settings** → **Devices & Services**
2. Click **"Add Integration"** (+ button)
3. Search for **"EG4 Inverter"**
4. Click **"EG4 Inverter"** from the list

### Step 2: Enter Credentials

- **Username**: Your EG4 Monitor account username
- **Password**: Your EG4 Monitor account password  
- **Base URL**: `https://monitor.eg4electronics.com` (default)
- **SSL Verification**: ✓ Enabled (recommended)

### Step 3: Select Station (if multiple)

If you have multiple solar installations, select which station to monitor. Each station requires a separate integration instance.

### Step 4: Automatic Device Discovery

The integration will automatically discover and configure:
- ✅ All inverters in the selected station
- ✅ GridBOSS devices (if present) 
- ✅ Individual battery modules
- ✅ Parallel group configurations

## Device Types & Sensors

### Standard Inverter Sensors

#### Power & Energy
- **AC/DC Power**: Real-time power generation and consumption
- **PV Total Power**: Combined solar panel output
- **Battery Power**: Charging/discharging power
- **Yield / Yield (Lifetime)**: Daily and lifetime energy generation ⭐ *Recently simplified from "Today Yield" / "Total Yield"*
- **Energy Consumption**: Load consumption tracking

#### Electrical Measurements  
- **Voltages**: AC, DC, Battery voltages with precision scaling
- **Currents**: AC, DC, Battery currents
- **Frequency**: Grid frequency monitoring

#### Environmental & Status
- **Temperatures**: Internal, Radiator 1, Radiator 2 temperatures
- **Status**: System status with intelligent text conversion
- **Firmware Version**: Extracted from device runtime ⭐ *Recently improved*

### Individual Battery Sensors (Per Battery)

#### Core Measurements
- **Real Voltage/Current**: Actual battery electrical values
- **State of Charge (SoC)**: Battery charge percentage  
- **State of Health (SoH)**: Battery condition indicator
- **Real Power**: Individual battery power contribution

#### Cell Management
- **Cell Voltage**: Max/min cell voltages with scaling
- **Cell Temperature**: Max/min temperatures
- **Cell Numbers**: Identification of extreme cells

#### Lifecycle Tracking
- **Cycle Count**: Battery charge/discharge cycles
- **Capacities**: Remaining, full, design capacities
- **Firmware Version**: Battery module firmware

### GridBOSS MidBox Sensors

#### Grid Interconnection (Per Phase)
- **Grid Voltage/Current/Power**: L1/L2 phase monitoring
- **Grid Frequency**: Precise frequency measurement (÷100 scaling)
- **Phase Lock Frequency**: Grid synchronization monitoring
- **Import/Export Energy**: Bidirectional energy tracking

#### Load Management
- **Load Power**: Per-phase load consumption
- **UPS Power/Energy**: Backup power systems
- **Smart Load Ports**: 4 configurable smart ports ⭐ *Now created regardless of status*
  - Port Status: "Unused", "Smart Load", "AC Couple"
  - Individual port power monitoring

#### Solar Integration
- **AC Couple Ports**: 4 AC coupling connections
- **Energy Backfeed**: AC couple energy generation
- **Daily/Total Statistics**: Per-port energy accumulation

#### Generator Integration
- **Generator Power/Voltage/Current**: L1/L2 monitoring
- **Generator Frequency**: Generator operation tracking
- **Dry Contact Status**: Generator control integration

## Recent Updates ⭐

### Version 2025.09 - Production Release

#### ✅ **Sensor Naming Simplification**
- **Simplified Energy Sensors**: Cleaner, more intuitive naming
  - `today_yield` → `yield` (daily energy generation)
  - `total_yield` → `yield_lifetime` (lifetime energy generation)
  - Applied to all energy types: charging, discharging, load, grid feed, etc.
- **Entity IDs Simplified**: Consistent naming throughout the integration

#### ✅ **GridBOSS Enhancements** 
- **Zero-Value Filtering Removed**: All GridBOSS sensors now created regardless of value
- **Better Monitoring**: Essential sensors like grid power always visible (0W is meaningful)
- **Improved Scaling**: Accurate frequency readings (÷100 for Hz values)

#### ✅ **Firmware Version Extraction**
- **Inverter Firmware**: Now extracted from `fwCode` field (e.g., "FAAB-2122")
- **GridBOSS Firmware**: Proper version display (e.g., "IAAB-1300")
- **Automatic Detection**: Firmware versions automatically updated

#### ✅ **Production Readiness**
- **Comprehensive Testing**: Full unit test suite with 95%+ coverage
- **Error Handling**: Robust error handling and recovery
- **Performance Optimized**: Concurrent API calls and smart caching

## Supported Devices

### ✅ Tested Inverters
- **FlexBOSS21**: 21kW hybrid inverter
- **FlexBOSS18**: 18kW hybrid inverter  
- **18KPV**: 18kW PV inverter
- **12KPV**: 12kW PV inverter
- **XP Series**: Various XP models

### ✅ Tested GridBOSS
- **GridBOSS**: Microgrid interconnection device
- **MidBox Runtime**: Complete grid management functionality

### ✅ Battery Systems
- **EG4 Batteries**: All EG4-compatible battery modules
- **Individual Monitoring**: Per-battery sensors and diagnostics
- **BMS Integration**: Complete battery management system data

## API Endpoints Used

The integration uses the following EG4 Monitor API endpoints:

### Authentication & Discovery
- `POST /WManage/api/login` - User authentication
- `POST /WManage/web/config/plant/list/viewer` - Station discovery

### Device Discovery  
- `POST /WManage/api/inverterOverview/list` - Primary device discovery
- `POST /WManage/api/inverterOverview/getParallelGroupDetails` - Parallel group discovery

### Runtime Data
- `POST /WManage/api/inverter/getInverterRuntime` - Real-time inverter data
- `POST /WManage/api/inverter/getInverterEnergyInfo` - Energy statistics
- `POST /WManage/api/battery/getBatteryInfo` - Battery array data
- `POST /WManage/api/midbox/getMidboxRuntime` - GridBOSS data

## Configuration Examples

### Single Station Setup
```yaml
# Automatically configured through UI
# Creates: "EG4 Inverter Home Solar System"
```

### Multiple Station Setup  
```yaml
# Create separate integration instances:
# 1. "EG4 Inverter Home Solar System" 
# 2. "EG4 Inverter Cabin Solar System"
# Each monitors different plantId
```

### Entity Naming Convention
```yaml
# Inverter Sensors
sensor.eg4_flexboss21_44300e0585_ac_power
sensor.eg4_flexboss21_44300e0585_yield                    # Daily generation
sensor.eg4_flexboss21_44300e0585_yield_lifetime           # Lifetime generation

# Battery Sensors  
sensor.eg4_flexboss21_44300e0585_battery_44300e0585_01_state_of_charge
sensor.eg4_flexboss21_44300e0585_battery_44300e0585_01_voltage

# GridBOSS Sensors
sensor.eg4_gridboss_4524850115_grid_power_l1
sensor.eg4_gridboss_4524850115_smart_port1_status
```

## Troubleshooting

### Common Issues

#### Authentication Errors
```
Error: Authentication failed
```
**Solution**: Verify EG4 Monitor credentials and account access

#### No Devices Found
```
Warning: No devices found in plant
```
**Solution**: Check device online status in EG4 Monitor app

#### Missing Sensors  
```
Info: Some sensors not created
```
**Solution**: Normal for unused features (e.g., generator when not present)

#### Firmware Version Shows 1.0.0
**Solution**: Updated in latest version - restart integration

### Debug Logging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.eg4_inverter: debug
```

### Network Issues

Verify connectivity to EG4 servers:
```bash
curl -I https://monitor.eg4electronics.com
```

## Development & Testing

### Run Tests
```bash
# Install test dependencies
python run_tests.py --install

# Run all tests with coverage
python run_tests.py --all

# Run specific tests
python run_tests.py --filter "test_sensor"
```

### Test Coverage
The integration includes comprehensive tests covering:
- ✅ **API Integration**: All endpoint interactions
- ✅ **Device Discovery**: Multi-station, multi-device scenarios  
- ✅ **Sensor Creation**: All device types and sensor categories
- ✅ **Data Processing**: Scaling, filtering, validation
- ✅ **Error Handling**: Network, authentication, API errors
- ✅ **Configuration Flow**: Multi-step setup process

## Performance

### Update Intervals
- **Default**: 30 seconds (configurable)
- **Concurrent Requests**: Parallel API calls for multiple devices
- **Session Management**: 2-hour session persistence
- **Smart Caching**: Reduced API load with intelligent caching

### Resource Usage
- **Memory**: ~10MB per integration instance
- **Network**: ~1KB/device per update cycle  
- **CPU**: Minimal impact with async processing

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup
1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Run tests: `python run_tests.py --all`
4. Commit changes: `git commit -m 'Add amazing feature'`
5. Push branch: `git push origin feature/amazing-feature`
6. Open Pull Request

## Support

### Documentation
- [Installation Guide](docs/installation.md)
- [Configuration Guide](docs/configuration.md)
- [API Reference](docs/api.md)
- [Troubleshooting Guide](docs/troubleshooting.md)

### Community
- [GitHub Issues](https://github.com/joyfulhouse/eg4_inverter/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io)
- [EG4 Electronics Support](https://eg4electronics.com/support)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration not affiliated with EG4 Electronics. Use at your own risk. The integration uses publicly available API endpoints and does not modify device settings.

---

**Enjoy monitoring your EG4 solar system with Home Assistant!** ☀️🏠⚡

[releases-shield]: https://img.shields.io/github/v/release/joyfulhouse/eg4_inverter?style=for-the-badge
[releases]: https://github.com/joyfulhouse/eg4_inverter/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/joyfulhouse/eg4_inverter?style=for-the-badge
[commits]: https://github.com/joyfulhouse/eg4_inverter/commits/main
[license-shield]: https://img.shields.io/github/license/joyfulhouse/eg4_inverter?style=for-the-badge
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge