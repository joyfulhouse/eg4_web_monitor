# EG4 Web Monitor Home Assistant Integration

Monitor your EG4 Solar Inverters, GridBOSS devices, and battery systems directly in Home Assistant.

## 🙏 Credits

This integration was inspired by and built upon the excellent work by [@twistedroutes](https://github.com/twistedroutes) and their [eg4_inverter_ha](https://github.com/twistedroutes/eg4_inverter_ha) project. We extend our sincere gratitude for their pioneering efforts in EG4 device integration for Home Assistant.

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![HACS][hacsbadge]][hacs]
[![Gold Tier][gold-badge]][gold-workflow]
[![Silver Tier][silver-badge]][silver-workflow]
[![Bronze Tier][bronze-badge]][bronze-workflow]
[![Config Flow Tests][tests-badge]][tests-workflow]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Dashboard Screenshot](images/dashboard.png)](dashboards/eg4_solar_monitor.yaml)

## 🏆 Quality Tier: Gold Certified

This integration meets the **Gold tier** quality standards for Home Assistant integrations, ensuring:
- ✅ Full translation support (multiple languages)
- ✅ Easy reconfiguration through the UI
- ✅ Comprehensive automated testing
- ✅ Extensive user-friendly documentation
- ✅ Professional error handling and logging

## What Does This Integration Do?

This integration connects your EG4 solar equipment to Home Assistant, allowing you to:

- **See Real-Time Data**: View your solar production, battery levels, grid usage, and power consumption
- **Control Your System**: Turn on quick charging, enable battery backup mode, adjust charge limits
- **Create Automations**: Automatically respond to changing energy conditions
- **Track Energy Usage**: Monitor daily, monthly, and lifetime energy statistics
- **Manage Multiple Sites**: Monitor multiple solar installations from one Home Assistant instance

No technical knowledge of solar systems is required - if you can use the EG4 Monitor app, you can use this integration!

## Features

- **Complete Device Support**: FlexBOSS, 18KPV, 12KPV, XP inverters, GridBOSS, and individual batteries
- **Real-time Monitoring**: Power, voltage, current, temperature, frequency, and energy statistics
- **Control & Automation**: Quick charge, battery backup (EPS), operating modes, and SOC limits
- **Multi-Station Support**: Monitor multiple solar installations from one account
- **GridBOSS Integration**: Grid management, smart load ports, AC coupling, and generator monitoring
- **Multi-Language Support**: User interface available in multiple languages

![Integration Screenshot](images/integration.png)

## Prerequisites

Before installing this integration, you need:

1. **EG4 Solar Equipment**: At least one EG4 inverter that's connected to the EG4 Monitor cloud service
2. **EG4 Monitor Account**: An active account on [monitor.eg4electronics.com](https://monitor.eg4electronics.com)
   - Your devices should be visible in the EG4 Monitor mobile app or website
   - Note your username and password - you'll need them during setup
3. **Home Assistant**: Version 2024.1 or newer
4. **HACS** (recommended): For easy installation and automatic updates

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

### Initial Setup

1. Navigate to **Settings** → **Devices & Services** in Home Assistant
2. Click the **Add Integration** button (bottom right)
3. Search for **"EG4 Web Monitor"** and select it
4. Enter your EG4 Monitor credentials:
   - **Username**: Your EG4 Monitor account email or username
   - **Password**: Your EG4 Monitor account password
   - **Base URL**: Leave as default (`https://monitor.eg4electronics.com`) unless instructed otherwise
   - **Verify SSL Certificate**: Leave checked (recommended for security)
5. Click **Submit**

If you have multiple solar installations (stations):
- You'll be asked to select which station to monitor
- Each station requires a separate integration instance
- You can add more instances by repeating the setup process

Once configured:
- Your devices will be discovered automatically
- Sensors will appear within a few seconds
- Data updates every 30 seconds by default

### Reconfiguring the Integration

Need to change your credentials or switch to a different station? No problem!

1. Navigate to **Settings** → **Devices & Services**
2. Find your **EG4 Web Monitor** integration
3. Click the three dots (⋮) menu
4. Select **Reconfigure**
5. Update your settings:
   - Change username, password, or connection settings
   - Switch to a different solar installation/station
   - Update SSL verification settings
6. Click **Submit** - your integration will reload with the new settings

The reconfiguration process won't lose any of your existing automations or dashboards!

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

## Automation Examples

Here are some practical ways to use this integration:

### Automatic Quick Charge During Off-Peak Hours

```yaml
automation:
  - alias: "Charge Batteries During Off-Peak"
    trigger:
      - platform: time
        at: "23:00:00"  # 11 PM - start of off-peak
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.18kpv_1234567890_quick_charge

  - alias: "Stop Quick Charge at Peak Hours"
    trigger:
      - platform: time
        at: "07:00:00"  # 7 AM - end of off-peak
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.18kpv_1234567890_quick_charge
```

### Low Battery Alert

```yaml
automation:
  - alias: "Low Battery Notification"
    trigger:
      - platform: numeric_state
        entity_id: sensor.18kpv_1234567890_state_of_charge
        below: 20
    action:
      - service: notify.mobile_app
        data:
          message: "Battery level is low ({{ states('sensor.18kpv_1234567890_state_of_charge') }}%)"
          title: "Solar Battery Alert"
```

### Enable Battery Backup Mode When Grid Fails

```yaml
automation:
  - alias: "Enable EPS on Grid Failure"
    trigger:
      - platform: numeric_state
        entity_id: sensor.18kpv_1234567890_grid_power
        below: 0.1
        for:
          minutes: 5
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.18kpv_1234567890_battery_backup_eps
```

## Frequently Asked Questions

### How often does the data update?

Data updates every 30 seconds by default. You can force an immediate update using the "Refresh Data" button or the `eg4_web_monitor.refresh_data` service.

### Can I monitor multiple solar installations?

Yes! Each installation (station) requires a separate integration instance. Just add the integration multiple times and select a different station each time.

### Why are some sensors missing or unavailable?

This is normal! The integration only creates sensors for features your equipment actually has. For example:
- Generator sensors only appear if you have a generator connected
- Some GridBOSS ports may not show up if they're unused
- Battery-specific sensors only appear for batteries connected to your inverters

### Will this work if my internet goes down?

No - this integration requires internet access because it communicates with EG4's cloud service. It cannot communicate directly with your inverters. If your internet connection is down, the integration will mark entities as "unavailable" and will automatically reconnect when internet is restored.

### Does this integration control my inverter?

Yes, for supported features like:
- Quick charge on/off
- Battery backup (EPS) mode
- Operating mode (Normal/Standby)
- SOC charge limits
- AC and PV charge power settings

All control commands are sent through the official EG4 API, the same one used by the EG4 Monitor mobile app.

### Is this integration secure?

Yes! The integration:
- Uses encrypted HTTPS connections to EG4's servers
- Stores credentials securely in Home Assistant's encrypted storage
- Only communicates with official EG4 API endpoints
- Verifies SSL certificates by default

### What happens if my EG4 Monitor password changes?

Home Assistant will detect the authentication failure and prompt you to re-enter your credentials through the UI. Just click the notification and enter your new password - no need to delete and re-add the integration!

## Troubleshooting

### Enable Debug Logging

If you're experiencing issues, enable detailed logging to help diagnose the problem:

1. Edit your `configuration.yaml` file
2. Add the following:

```yaml
logger:
  default: warning
  logs:
    custom_components.eg4_web_monitor: debug
```

3. Restart Home Assistant
4. Check **Settings** → **System** → **Logs** for detailed information

### Common Issues

#### "Cannot connect to EG4 Web Monitor"

**Possible causes:**
- Internet connection is down
- EG4 servers are temporarily unavailable
- Firewall is blocking access to monitor.eg4electronics.com

**Solutions:**
1. Check your internet connection
2. Try accessing [monitor.eg4electronics.com](https://monitor.eg4electronics.com) in a web browser
3. Check if your firewall allows HTTPS traffic to EG4's servers
4. Wait a few minutes and try again - the integration will automatically retry

#### "Invalid username or password"

**Solutions:**
1. Verify your credentials in the EG4 Monitor mobile app or website
2. Try logging out and back in to the EG4 Monitor app
3. Check for extra spaces in your username or password
4. If you recently changed your password, use the **Reconfigure** option to update it

#### "No solar stations/plants found"

**Possible causes:**
- Your account doesn't have any stations configured yet
- Stations haven't finished syncing to the EG4 cloud

**Solutions:**
1. Log into the EG4 Monitor app and verify your station is visible there
2. Make sure your inverter is connected to the internet and uploading data
3. Wait 5-10 minutes for new stations to fully sync
4. Contact EG4 support if stations don't appear in the mobile app

#### "Entities show as unavailable"

**Possible causes:**
- Internet connection lost
- EG4 API session expired
- Inverter is offline

**Solutions:**
1. Check Home Assistant's internet connection
2. Wait 2-5 minutes - the integration will automatically reconnect
3. Check if your inverter is online in the EG4 Monitor app
4. Use the "Refresh Data" button to force a reconnection
5. If problem persists, try reloading the integration

#### "Some sensors are missing"

This is usually normal! The integration only creates sensors for features your specific equipment supports. For example:

- **GridBOSS sensors**: Only appear if you have a GridBOSS device
- **Battery sensors**: Only for connected battery banks
- **Generator sensors**: Only if a generator is connected
- **Smart port sensors**: Only for configured ports on GridBOSS

**To verify:**
1. Check what sensors appear in the EG4 Monitor mobile app
2. Make sure the missing feature actually exists on your equipment
3. Enable debug logging to see what data the API is providing

### Getting Help

If you're still experiencing issues:

1. **Check existing issues**: [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
2. **Enable debug logging** and include relevant logs when reporting issues
3. **Provide details**:
   - Your Home Assistant version
   - Your EG4 equipment model(s)
   - Error messages from the logs
   - Steps to reproduce the issue

### Support Channels

- **Bug Reports**: [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
- **Feature Requests**: [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
- **Community Discussion**: [Home Assistant Community](https://community.home-assistant.io)
- **General Help**: [Home Assistant Discord](https://discord.gg/home-assistant)

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
[gold-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/gold-tier-validation.yml?branch=main&label=Gold%20Tier&style=for-the-badge&color=gold
[gold-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/gold-tier-validation.yml
[silver-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/silver-tier-validation.yml?branch=main&label=Silver%20Tier&style=for-the-badge
[silver-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/silver-tier-validation.yml
[bronze-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/bronze-tier-validation.yml?branch=main&label=Bronze%20Tier&style=for-the-badge
[bronze-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/bronze-tier-validation.yml
[tests-badge]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/eg4_web_monitor/bronze-tier-validation.yml?branch=main&label=Tests&style=for-the-badge
[tests-workflow]: https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/bronze-tier-validation.yml
[maintenance-shield]: https://img.shields.io/badge/maintainer-joyfulhouse-blue.svg?style=for-the-badge
[user_profile]: https://github.com/joyfulhouse
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[buymecoffee]: https://www.buymeacoffee.com/btli
