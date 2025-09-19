# EG4 Web Monitor Home Assistant Integration

A comprehensive Home Assistant custom component for monitoring EG4 Solar Inverters and GridBOSS devices through the EG4 Monitor web API.

## 🙏 Credits

This integration was inspired by and built upon the excellent work by [@twistedroutes](https://github.com/twistedroutes) and their [eg4_inverter_ha](https://github.com/twistedroutes/eg4_inverter_ha) project. We extend our sincere gratitude for their pioneering efforts in EG4 device integration for Home Assistant.

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
- **Quick Charge Control**: Start and stop quick charging directly from Home Assistant with real-time status monitoring
- **Battery Backup Control**: Enable and disable Emergency Power Supply (EPS) mode for battery backup functionality

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
   - Add URL: `https://github.com/joyfulhouse/eg4_web_monitor`
   - Category: "Integration"
   - Click "Add"

2. **Install Integration**:
   - Search for "EG4 Web Monitor" in HACS
   - Click "Download"
   - Restart Home Assistant

### Manual Installation

1. **Download Integration**:
   ```bash
   cd /config/custom_components
   git clone https://github.com/joyfulhouse/eg4_web_monitor.git eg4_web_monitor
   ```

2. **Restart Home Assistant**:
   - Settings → System → Restart

## Configuration

### Step 1: Add Integration

1. Go to **Settings** → **Devices & Services**
2. Click **"Add Integration"** (+ button)
3. Search for **"EG4 Web Monitor"**
4. Click **"EG4 Web Monitor"** from the list

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
- ✅ Quick Charge switches for compatible inverters (FlexBOSS, 18KPV, 12KPV, XP series)
- ✅ Battery Backup switches for Emergency Power Supply (EPS) control
- ✅ Diagnostic refresh buttons for all devices and individual batteries

## Device Types & Sensors

### Standard Inverter Sensors

#### Power & Energy
- **AC/DC Power**: Real-time power generation and consumption
- **PV Total Power**: Combined solar panel output
- **Battery Power**: Charging/discharging power
- **Daily Energy**: Daily energy generation and consumption
- **Lifetime Energy**: Total lifetime energy statistics

#### Electrical Measurements  
- **Voltages**: AC, DC, Battery voltages with precision scaling
- **Currents**: AC, DC, Battery currents
- **Frequency**: Grid frequency monitoring

#### Environmental & Status
- **Temperatures**: Internal, Radiator 1, Radiator 2 temperatures
- **Status**: System status with intelligent text conversion
- **Firmware Version**: Device firmware information

### Switch Controls

#### Quick Charge Control
- **Quick Charge Switch**: Direct battery charging control with real-time status
  - Entity ID: `switch.{model}_{serial}_quick_charge`
  - Icon: Battery charging indicator
  - Optimistic state updates for immediate UI feedback

**Features**:
- **Instant Control**: Start/stop quick charging with immediate UI response
- **Real-time Status**: Automatic status monitoring using `hasUnclosedQuickChargeTask`
- **Task Tracking**: Task ID and status attributes for detailed monitoring
- **Device Compatibility**: Automatic detection for FlexBOSS, 18KPV, 12KPV, XP series
- **Error Handling**: Graceful fallback on API errors with state reversion

#### Battery Backup Control  
- **Battery Backup Switch**: Emergency Power Supply (EPS) mode control
  - Entity ID: `switch.{model}_{serial}_battery_backup`
  - Icon: Battery charging indicator
  - Parameter-based state synchronization

**Features**:
- **EPS Mode Control**: Enable/disable Emergency Power Supply functionality
- **Parameter Sync**: Real-time status sync with `FUNC_EPS_EN` parameter
- **Optimistic Updates**: Immediate UI feedback with state validation
- **Cross-Device Sync**: Parameter changes trigger updates across all inverters
- **Robust Error Handling**: Graceful state reversion on API failures

### Diagnostic Refresh Controls

#### Device Refresh Buttons
- **Device Refresh Button**: Cache invalidation and data refresh for all device types
  - Entity ID: `button.{model}_{serial}_refresh_data`
  - Icon: Refresh indicator
  - Entity Category: Diagnostic

**Features**:
- **Cache Invalidation**: Clears device-specific cache for fresh data retrieval
- **Parameter Refresh**: Automatic parameter refresh for inverter devices
- **Immediate API Calls**: Forces fresh data retrieval bypassing cache
- **Device Compatibility**: Available for all device types (Inverters, GridBOSS, Parallel Groups)
- **Real-time Updates**: Triggers coordinator refresh for immediate entity updates

#### Battery Refresh Buttons
- **Battery Refresh Button**: Individual battery cache invalidation and refresh
  - Entity ID: `button.battery_{serial}_{battery_id}_refresh_data`
  - Name: `Battery {serial}-{id} Refresh Data`
  - Icon: Refresh indicator
  - Entity Category: Diagnostic

**Features**:
- **Targeted Battery Refresh**: Direct battery API calls with cache clearing
- **Device Hierarchy**: Buttons assigned to existing battery devices (no duplicate devices)
- **Comprehensive Cache Clear**: Invalidates both device and battery-specific cache entries
- **Fresh Data Guarantee**: Ensures latest battery data from EG4 API
- **Immediate Updates**: Forces coordinator refresh to update all battery sensors

### Individual Battery Sensors (Per Battery)

#### Core Measurements
- **Real Voltage/Current**: Actual battery electrical values
- **State of Charge (SoC)**: Battery charge percentage  
- **State of Health (SoH)**: Battery condition indicator
- **Power**: Individual battery power contribution

#### Cell Management
- **Cell Voltage**: Max/min cell voltages
- **Cell Temperature**: Max/min temperatures
- **Cell Voltage Delta**: Difference between highest and lowest cell voltages

#### Lifecycle Tracking
- **Cycle Count**: Battery charge/discharge cycles
- **Capacities**: Remaining and full capacities
- **Firmware Version**: Battery module firmware

### GridBOSS MidBox Sensors

#### Grid Interconnection (Per Phase)
- **Grid Voltage/Current/Power**: L1/L2 phase monitoring
- **Grid Frequency**: Precise frequency measurement
- **Phase Lock Frequency**: Grid synchronization monitoring
- **Import/Export Energy**: Bidirectional energy tracking

#### Load Management
- **Load Power**: Per-phase load consumption
- **UPS Power/Energy**: Backup power systems
- **Smart Load Ports**: 4 configurable smart ports
  - Port Status: "Unused", "Smart Load", "AC Couple"
  - Individual port power monitoring

#### Solar Integration
- **AC Couple Ports**: 4 AC coupling connections
- **Energy Backfeed**: AC couple energy generation
- **Daily/Total Statistics**: Per-port energy accumulation

#### Generator Integration
- **Generator Power/Voltage/Current**: L1/L2 monitoring
- **Generator Frequency**: Generator operation tracking
- **Control Integration**: Generator status monitoring

## Supported Devices

### ✅ Tested Inverters
- **FlexBOSS21**: 21kW hybrid inverter
- **FlexBOSS18**: 18kW hybrid inverter  
- **18KPV**: 18kW PV inverter
- **12KPV**: 12kW PV inverter
- **XP Series**: Various XP models

### ✅ Tested GridBOSS
- **GridBOSS**: Microgrid interconnection device
- **Complete Functionality**: All grid management features

### ✅ Battery Systems
- **EG4 Batteries**: All EG4-compatible battery modules
- **Individual Monitoring**: Per-battery sensors and diagnostics
- **BMS Integration**: Complete battery management system data

## Configuration Examples

### Entity Naming Convention
```yaml
# Inverter Sensors
sensor.eg4_flexboss21_44300e0585_ac_power
sensor.eg4_flexboss21_44300e0585_daily_energy_generation
sensor.eg4_flexboss21_44300e0585_total_energy_generation

# Battery Sensors  
sensor.battery_44300e0585_01_state_of_charge
sensor.battery_44300e0585_01_cell_voltage_delta

# Switch Controls
switch.flexboss21_44300e0585_quick_charge
switch.flexboss21_44300e0585_battery_backup
switch.18kpv_4512670118_quick_charge
switch.18kpv_4512670118_battery_backup

# Refresh Buttons
button.flexboss21_44300e0585_refresh_data
button.18kpv_4512670118_refresh_data
button.eg4gridboss_4524850115_refresh_data
button.battery_44300e0585_01_refresh_data
button.battery_4512670118_02_refresh_data

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

### Debug Logging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.eg4_web_monitor: debug
```

### Network Issues

Verify connectivity to EG4 servers:
```bash
curl -I https://monitor.eg4electronics.com
```

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

Contributions are welcome! Please read the contributing guidelines before submitting pull requests.

### Development Setup
1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Run tests to ensure quality
4. Commit changes: `git commit -m 'Add amazing feature'`
5. Push branch: `git push origin feature/amazing-feature`
6. Open Pull Request

## Support

### Community
- [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration not affiliated with EG4 Electronics. Use at your own risk. The integration uses publicly available API endpoints and does not modify device settings.

---

**Enjoy monitoring your EG4 solar system with Home Assistant!** ☀️🏠⚡

[releases-shield]: https://img.shields.io/github/v/release/joyfulhouse/eg4_web_monitor?style=for-the-badge
[releases]: https://github.com/joyfulhouse/eg4_web_monitor/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/joyfulhouse/eg4_web_monitor?style=for-the-badge
[commits]: https://github.com/joyfulhouse/eg4_web_monitor/commits/main
[license-shield]: https://img.shields.io/github/license/joyfulhouse/eg4_web_monitor?style=for-the-badge
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-joyfulhouse-blue.svg?style=for-the-badge
[user_profile]: https://github.com/joyfulhouse
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[buymecoffee]: https://www.buymeacoffee.com/btli