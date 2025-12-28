# EG4 Web Monitor - Examples

This directory contains example automations and dashboards to help you get the most out of your EG4 Web Monitor integration.

## Directory Structure

```
examples/
├── automations/          # Example Home Assistant automations
│   ├── battery_management.yaml
│   ├── grid_management.yaml
│   ├── solar_optimization.yaml
│   ├── load_management.yaml
│   ├── battery_cell_balancing.yaml
│   ├── grid_export_clipping.yaml
│   └── daylight_saving_time.yaml
├── dashboards/           # Example Lovelace dashboard configurations
│   ├── energy_overview.yaml
│   ├── battery_details.yaml
│   └── eg4_solar_monitor.yaml
└── README.md            # This file
```

## Automations

### Battery Management (`battery_management.yaml`)
- **Battery Low Alert**: Notify when SOC drops below threshold
- **Battery Temperature Alert**: Alert on high battery temperature
- **Battery Cell Imbalance Alert**: Detect cell voltage issues
- **Daily Battery Report**: Morning battery health summary
- **Dynamic AC Charge Control**: Adjust charging based on electricity rates

### Grid Management (`grid_management.yaml`)
- **High Grid Import Alert**: Monitor excessive grid usage
- **Smart Grid Charging**: Time-of-use rate optimization
- **Grid Frequency Alert**: Detect grid instability
- **Smart Grid Export**: Control export based on battery SOC
- **Daily Energy Summary**: Evening energy report

### Solar Optimization (`solar_optimization.yaml`)
- **Solar Production Started**: Morning solar notification
- **Low Solar Production Alert**: Detect panel issues
- **High Solar Self-Consumption**: Run loads during peak solar
- **Solar Production Ended**: Evening production summary
- **Weather-Based Battery Management**: Adjust limits based on forecast
- **PV String Performance Alert**: Detect string imbalances

### Load Management (`load_management.yaml`)
- **High Load Alert**: Monitor excessive consumption
- **Grid Outage Load Shedding**: Automatic load reduction
- **Grid Restored Load Recovery**: Restore loads when grid returns
- **Smart EV Charging**: Charge only with excess solar
- **GridBOSS Smart Load Control**: Control smart load ports by SOC
- **Weekly Load Report**: Sunday consumption summary

### Battery Cell Balancing (`battery_cell_balancing.yaml`)
- Advanced cell voltage monitoring and balancing alerts

### Grid Export Clipping (`grid_export_clipping.yaml`)
- Prevent grid export power clipping and optimize feed-in

### Daylight Saving Time (`daylight_saving_time.yaml`)
- Automatic time adjustment for inverter clocks

## Dashboards

### Energy Overview (`energy_overview.yaml`)
A comprehensive energy monitoring dashboard featuring:
- Real-time power flow visualization
- Solar, grid, battery, and load metrics
- Daily energy statistics
- 24-hour power flow charts
- 7-day battery SOC history
- Grid status and frequency monitoring
- System controls (operating mode, charge settings)

**Required Custom Cards**:
- [Power Flow Card Plus](https://github.com/flixlix/power-flow-card-plus)
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card)

### Battery Details (`battery_details.yaml`)
Detailed battery monitoring dashboard with:
- Battery SOC and SOH gauges
- Individual cell voltage monitoring (all 16 cells)
- Cell voltage imbalance tracking
- Battery temperature history
- Battery power and SOC trends
- Battery configuration controls

**Required Custom Cards**:
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card)

### EG4 Solar Monitor (`eg4_solar_monitor.yaml`)
Advanced solar energy monitoring with comprehensive metrics and visualizations.

## How to Use

### Installing Automations

1. **Copy to your automations file**:
   - Open the automation file you want to use (e.g., `automations/battery_management.yaml`)
   - Copy the automation(s) you want
   - Paste into your `automations.yaml` file or use the Home Assistant UI

2. **Update entity IDs**:
   - Replace `1234567890` with your actual inverter serial number
   - Example: `sensor.eg4_flexboss21_1234567890_battery_soc` → `sensor.eg4_flexboss21_5551234567_battery_soc`

3. **Customize thresholds**:
   - Adjust trigger values to match your needs (e.g., battery SOC thresholds)
   - Modify notification services to match your setup

4. **Test the automation**:
   - Use Developer Tools → Services to manually trigger
   - Monitor logs for any errors

### Installing Dashboards

1. **Install required custom cards**:
   ```bash
   # Via HACS (recommended)
   - Search for "Power Flow Card Plus"
   - Search for "ApexCharts Card"
   - Install both cards
   ```

2. **Create a new dashboard**:
   - Settings → Dashboards → Add Dashboard
   - Choose "Start with an empty dashboard"

3. **Add the dashboard configuration**:
   - Open the dashboard file (e.g., `dashboards/energy_overview.yaml`)
   - Click "Edit Dashboard" → "Raw Configuration Editor"
   - Copy and paste the YAML configuration
   - Update entity IDs to match your devices

4. **Customize the layout**:
   - Adjust card order and groupings
   - Remove cards you don't need
   - Add additional cards as desired

## Entity ID Reference

All entity IDs follow this format:
```
{platform}.{model}_{serial}_{sensor_name}
```

**Examples**:
- `sensor.18kpv_1234567890_state_of_charge`
- `sensor.flexboss21_1234567890_ac_power`
- `switch.18kpv_1234567890_quick_charge`
- `switch.18kpv_1234567890_battery_backup`
- `number.18kpv_1234567890_ac_charge_power`
- `button.18kpv_1234567890_refresh_data`

**GridBOSS entities**:
- `sensor.gridboss_9991234567_grid_power`
- `sensor.gridboss_9991234567_load_power`

**Battery entities**:
- `sensor.battery_1234567890_01_state_of_charge`
- `sensor.battery_1234567890_01_cell_voltage_delta`

## Finding Your Serial Numbers

1. **In Home Assistant**:
   - Settings → Devices & Services → EG4 Web Monitor
   - Click on your integration instance
   - View the device list - serial numbers are shown

2. **In Developer Tools**:
   - Developer Tools → States
   - Filter for `eg4_`
   - Entity IDs contain your serial numbers

## Tips and Best Practices

### Automations
- Start with one or two automations and test thoroughly
- Use trace feature (Developer Tools → Automations) to debug
- Set appropriate delays to avoid rapid on/off cycling
- Consider adding conditions to prevent notifications at night
- Use `for:` duration to avoid triggering on transient spikes

### Dashboards
- Start with the Energy Overview dashboard as your main view
- Add Battery Details as a separate dashboard tab for detailed monitoring
- Use conditional cards to show/hide sections based on device presence
- Consider mobile responsiveness when designing layouts
- Use color coding (severity levels) to quickly identify issues

### Notifications
- Use different notification priorities (high, normal) appropriately
- Group related notifications to avoid spam
- Add actionable notifications where possible
- Include relevant state values in notification messages
- Consider using notification groups for multiple recipients

## Customization Ideas

- **Time-of-Use Optimization**: Integrate with electricity rate sensors
- **Weather Integration**: Use solar forecast to adjust battery limits
- **Load Priority**: Create tiered load shedding based on criticality
- **Seasonal Adjustments**: Different settings for summer/winter
- **Multi-Inverter Support**: Adapt for parallel inverter configurations
- **GridBOSS Integration**: Advanced smart load port automation

## Troubleshooting

### Automation Not Triggering
- Verify entity IDs are correct
- Check automation is enabled
- Review conditions and triggers
- Use automation trace to debug
- Check entity state history

### Dashboard Not Displaying
- Ensure custom cards are installed via HACS
- Clear browser cache
- Check browser console for errors
- Verify entity IDs exist
- Check for YAML syntax errors

### Entity Not Found
- Confirm integration is loaded
- Check device model matches (FlexBOSS, GridBOSS, etc.)
- Verify serial number is correct
- Some sensors may not be available on all models
- Check coordinator update frequency

## Contributing

Have a great automation or dashboard example? Consider contributing:
1. Fork the repository
2. Add your example with clear documentation
3. Submit a pull request

## Support

For issues specific to these examples:
- Check the [main README](../README.md) for integration documentation
- Review [troubleshooting guide](../README.md#troubleshooting)
- Open an issue on GitHub with your configuration (remove sensitive data)

## License

These examples are provided as-is for use with the EG4 Web Monitor integration.
Feel free to modify and adapt to your specific needs.
