# EG4 Web Monitor Home Assistant Integration

Monitor your EG4 Solar Inverters, GridBOSS devices, and battery systems directly in Home Assistant.

## 🙏 Credits

This integration was inspired by and built upon the excellent work by [@twistedroutes](https://github.com/twistedroutes) and their [eg4_inverter_ha](https://github.com/twistedroutes/eg4_inverter_ha) project. We extend our sincere gratitude for their pioneering efforts in EG4 device integration for Home Assistant.

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![HACS][hacsbadge]][hacs]
[![Bronze Tier][bronze-badge]][bronze-workflow]
[![Config Flow Tests][tests-badge]][tests-workflow]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Dashboard Screenshot](images/dashboard.png)](dashboards/eg4_solar_monitor.yaml)

## Features

- **Complete Device Support**: FlexBOSS, 18KPV, 12KPV, XP inverters, GridBOSS, and individual batteries
- **Real-time Monitoring**: Power, voltage, current, temperature, frequency, and energy statistics
- **Control & Automation**: Quick charge, battery backup (EPS), operating modes, and SOC limits
- **Multi-Station Support**: Monitor multiple solar installations from one account
- **GridBOSS Integration**: Grid management, smart load ports, AC coupling, and generator monitoring

![Integration Screenshot](images/integration.png)

## Installation

### HACS (Recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add URL: `https://github.com/joyfulhouse/eg4_web_monitor`
3. Category: Integration
4. Search for "EG4 Web Monitor" and install
5. Restart Home Assistant

### Manual Installation

```bash
cd /config/custom_components
git clone https://github.com/joyfulhouse/eg4_web_monitor.git eg4_web_monitor
```

Restart Home Assistant after installation.

## Configuration

1. **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"EG4 Web Monitor"**
3. Enter your EG4 Monitor credentials:
   - Username and password
   - Base URL: `https://monitor.eg4electronics.com`
4. Select your station (if you have multiple)
5. Devices and entities will be discovered automatically

## Available Controls

### Switches
- **Quick Charge**: Start/stop battery quick charging
- **Battery Backup (EPS)**: Enable/disable emergency power supply mode

### Selects
- **Operating Mode**: Switch between Normal and Standby modes

### Numbers
- **System Charge SOC Limit**: Set battery charge limit (%)
- **AC Charge Power**: Configure AC charging power
- **PV Charge Power**: Configure PV charging power

### Buttons
- **Refresh Data**: Force refresh for devices and batteries

## Service Actions

### eg4_web_monitor.refresh_data

Force an immediate refresh of device data from the EG4 API, bypassing the normal polling interval.

**Parameters:**
- **entry_id** (optional, string): The configuration entry ID to refresh. If not provided, all EG4 Web Monitor integrations will be refreshed.

**Example usage:**

Refresh a specific integration:
```yaml
service: eg4_web_monitor.refresh_data
data:
  entry_id: "abc123def456"
```

Refresh all EG4 Web Monitor integrations:
```yaml
service: eg4_web_monitor.refresh_data
```

**Use cases:**
- Force immediate data update after changing inverter settings
- Refresh after physical device changes
- Automation triggers requiring fresh data

## Entity Examples

```yaml
# Inverter sensors
sensor.18kpv_1234567890_ac_power
sensor.18kpv_1234567890_battery_charge_power
sensor.18kpv_1234567890_state_of_charge
sensor.18kpv_1234567890_daily_energy

# Battery sensors
sensor.battery_1234567890_01_state_of_charge
sensor.battery_1234567890_01_cell_voltage_delta
sensor.battery_1234567890_01_temperature

# GridBOSS sensors
sensor.gridboss_5555555555_grid_power_l1
sensor.gridboss_5555555555_load_power
sensor.gridboss_5555555555_smart_port1_status

# Controls
switch.18kpv_1234567890_quick_charge
switch.18kpv_1234567890_battery_backup
select.18kpv_1234567890_operating_mode
number.18kpv_1234567890_system_charge_soc_limit
```

## Supported Devices

- **Inverters**: FlexBOSS21, FlexBOSS18, 18KPV, 12KPV, XP series
- **GridBOSS**: Microgrid interconnection devices
- **Batteries**: All EG4-compatible battery modules with BMS integration

## Troubleshooting

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.eg4_web_monitor: debug
```

### Common Issues

- **Authentication failed**: Verify credentials in EG4 Monitor app
- **No devices found**: Check device status in EG4 Monitor app
- **Missing sensors**: Normal for unused features (e.g., generator when not connected)

### Support

- [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
- [Home Assistant Community](https://community.home-assistant.io)

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Disclaimer

Unofficial integration not affiliated with EG4 Electronics. Use at your own risk.

---

**Enjoy monitoring your EG4 solar system!** ☀️

[releases-shield]: https://img.shields.io/github/v/release/joyfulhouse/eg4_web_monitor?style=for-the-badge
[releases]: https://github.com/joyfulhouse/eg4_web_monitor/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/joyfulhouse/eg4_web_monitor?style=for-the-badge
[commits]: https://github.com/joyfulhouse/eg4_web_monitor/commits/main
[license-shield]: https://img.shields.io/github/license/joyfulhouse/eg4_web_monitor?style=for-the-badge
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[bronze-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/bronze-tier-validation.yml?branch=main&label=Bronze%20Tier&style=for-the-badge
[bronze-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/bronze-tier-validation.yml
[tests-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/bronze-tier-validation.yml?branch=main&label=Tests&style=for-the-badge
[tests-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/bronze-tier-validation.yml
[maintenance-shield]: https://img.shields.io/badge/maintainer-joyfulhouse-blue.svg?style=for-the-badge
[user_profile]: https://github.com/joyfulhouse
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[buymecoffee]: https://www.buymeacoffee.com/btli
