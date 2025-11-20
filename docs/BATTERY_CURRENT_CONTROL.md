# Battery Charge/Discharge Current Control

This guide explains how to use the Battery Charge Current and Battery Discharge Current number entities to optimize your EG4 inverter system performance.

## Overview

Starting in version 2.2.6, the EG4 Web Monitor integration provides direct control over battery charge and discharge current limits through Home Assistant number entities. This enables advanced automation scenarios for optimizing solar production, preventing inverter throttling, and managing battery health.

## Available Entities

### Battery Charge Current
- **Entity ID Pattern**: `number.eg4_{model}_{serial}_battery_charge_current`
- **Parameter**: `HOLD_LEAD_ACID_CHARGE_RATE`
- **Range**: 0-250 Amperes (A)
- **Purpose**: Controls the maximum current allowed to charge the batteries

### Battery Discharge Current
- **Entity ID Pattern**: `number.eg4_{model}_{serial}_battery_discharge_current`
- **Parameter**: `HOLD_LEAD_ACID_DISCHARGE_RATE`
- **Range**: 0-250 Amperes (A)
- **Purpose**: Controls the maximum current allowed to discharge from the batteries

## Use Cases

### 1. Preventing Inverter Throttling (Primary Use Case)

**Problem**: When your PV array can produce more DC power than your inverter can convert to AC, and your batteries are full, the system throttles total output to the inverter's maximum AC capacity.

**Example Scenario**:
- 18kPV inverter with 12kW maximum AC output
- 20kW PV array capacity
- On sunny days: PV produces 18kW DC, but inverter can only output 12kW AC
- When batteries are full: System throttles total PV production to 12kW, wasting 6kW of potential production

**Solution**: Limit battery charge current during high production periods to force excess power to grid export instead of battery charging.

```yaml
# Reduce charge current on sunny days to prevent throttling
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_charge_current
  data:
    value: 80  # ~5kW charge rate at 48V nominal
```

**Result**:
- Batteries charge at 5kW (limited by 80A current)
- Home consumption: 2kW
- Grid export: 11kW (18kW PV - 5kW battery - 2kW consumption)
- **Total production: 18kW** (vs 12kW with throttling)

### 2. Maximizing Battery Charging on Cloudy Days

**Problem**: On days with limited solar production, you want to ensure batteries are fully charged for evening/overnight use.

**Solution**: Increase charge current to maximum to capture all available solar energy into batteries.

```yaml
# Maximize charge rate on cloudy days
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_charge_current
  data:
    value: 200  # Maximum charge rate
```

### 3. Time-of-Use (TOU) Rate Optimization

**Scenario**: Your utility has time-of-use rates where grid export is more valuable during peak hours.

**Strategy**:
- **Peak hours + sunny**: Reduce charge current to maximize high-value grid export
- **Off-peak hours**: Increase charge current to build battery reserves for next peak period

```yaml
# Peak hours: minimize charge, maximize export
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_charge_current
  data:
    value: 50  # Minimal charging, maximum export
```

### 4. Battery Health Management

**Purpose**: Reduce charge/discharge rates to extend battery lifespan and reduce heat generation.

```yaml
# Gentle charging for battery longevity
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_charge_current
  data:
    value: 100  # 0.2C charge rate for 500Ah battery bank

# Conservative discharge for battery preservation
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_discharge_current
  data:
    value: 150  # Moderate discharge rate
```

### 5. Emergency Power Management

**Scenario**: Grid outage with limited solar production - need to preserve battery capacity.

```yaml
# Limit discharge during grid outage
- service: number.set_value
  target:
    entity_id: number.eg4_18kpv_1234567890_battery_discharge_current
  data:
    value: 50  # Minimal discharge to extend battery runtime
```

## Automation Examples

### Weather-Based Charge Rate Control

This automation adjusts charge current based on weather forecasts to optimize for the scenarios above.

**See**: [`examples/automations/battery_charge_control_weather.yaml`](../examples/automations/battery_charge_control_weather.yaml)

The example file includes 5 comprehensive automation scenarios:
1. **Basic Weather-Based Control**: Simple sunny/cloudy logic
2. **Solar Production-Based Control**: Responsive to actual PV output
3. **Time-of-Use + Weather**: Combines TOU rates with weather forecasts
4. **SOC-Based Control**: Prevents throttling when batteries are nearly full
5. **Advanced Multi-Factor**: Combines weather, SOC, production, and time

### Quick Example: Basic Weather Control

```yaml
automation:
  - id: battery_charge_weather_basic
    alias: "EG4: Battery Charge - Weather Based"
    trigger:
      - platform: time_pattern
        hours: "/1"
    condition:
      - condition: sun
        after: sunrise
        before: sunset
    action:
      - choose:
          # Sunny: Reduce charge to prevent throttling
          - conditions:
              - condition: state
                entity_id: weather.home
                state: "sunny"
            sequence:
              - service: number.set_value
                target:
                  entity_id: number.eg4_18kpv_1234567890_battery_charge_current
                data:
                  value: 80  # Limited charge for grid export
        # Cloudy: Maximize charge
        default:
          - service: number.set_value
            target:
              entity_id: number.eg4_18kpv_1234567890_battery_charge_current
            data:
              value: 200  # Maximum charge rate
```

## Understanding the Numbers

### Current vs Power

Battery power is calculated as: **Power (W) = Voltage (V) × Current (A)**

For a 48V nominal battery system:
- 50A = ~2.4kW
- 100A = ~4.8kW
- 150A = ~7.2kW
- 200A = ~9.6kW
- 250A = ~12kW

**Note**: Actual voltage varies with battery SOC (typically 48-58V), so actual power will vary.

### Recommended Starting Values

**High Production Limiting (Prevent Throttling)**:
- Start with: 80-100A (4-5kW)
- Adjust based on typical home consumption
- Goal: Allow enough excess for meaningful grid export

**Maximum Charging (Cloudy Days)**:
- Use: 200A or your battery's maximum rated current
- Respect battery manufacturer specifications
- Consider battery temperature

**Battery Preservation**:
- Use: 0.2C to 0.5C based on your battery capacity
- Example: For 500Ah battery, 0.2C = 100A, 0.5C = 250A
- Lower rates extend battery life but reduce power availability

## Safety Considerations

### Battery Limits

⚠️ **CRITICAL**: Never exceed your battery's maximum charge/discharge current rating.

- Check your battery manufacturer specifications
- Account for multiple battery banks in parallel
- Monitor battery temperature during high current operations
- Some batteries have lower limits in cold weather

### Integration Safeguards

The integration enforces these limits:
- Minimum: 0A (effectively disables charging/discharging)
- Maximum: 250A (API maximum, may exceed your battery's safe limit)
- **You are responsible for setting appropriate values for your battery system**

### Monitoring

Monitor these sensors when using current control:
- `sensor.eg4_{model}_{serial}_battery_temperature`
- `sensor.eg4_{model}_{serial}_battery_voltage`
- `sensor.eg4_{model}_{serial}_battery_current`
- Individual battery sensors (if available)

**Warning Signs**:
- Battery temperature >45°C (113°F)
- Significant voltage drop during discharge
- Large voltage delta between battery cells
- Unusual battery behavior or error states

## Troubleshooting

### Current Limit Not Taking Effect

**Symptoms**: Set charge current limit, but batteries charge at higher rate

**Common Causes**:
1. **Multiple inverters**: Each inverter has independent settings
2. **Inverter caching**: Settings may take 1-2 minutes to apply
3. **Operating mode**: Some modes override current limits
4. **BMS limits**: Battery BMS may impose stricter limits

**Solutions**:
- Verify entity ID matches your inverter
- Check inverter operating mode
- Wait 2-5 minutes and verify via `sensor.eg4_{model}_{serial}_battery_current`
- Check inverter display for actual applied limits

### Automation Not Triggering

**Debug Steps**:
1. Enable debug logging for automation:
   ```yaml
   logger:
     logs:
       homeassistant.components.automation: debug
   ```

2. Check automation state in Developer Tools > States

3. Verify trigger conditions:
   - Weather entity exists and updates
   - Solar sensors have valid data
   - Time/sun conditions are met

4. Test manually:
   - Go to Developer Tools > Services
   - Call `number.set_value` directly
   - Verify value changes in entity state

### Values Reverting

**Symptoms**: Current limit resets to default (200A) after some time

**Causes**:
1. **Inverter parameter refresh**: Integration syncs from inverter hourly
2. **Manual changes**: Changes via inverter display or web interface
3. **Competing automations**: Multiple automations setting different values

**Solutions**:
- Use `logbook` to track when values change and by what
- Add logging to automations to track executions
- Review all automations that modify these entities

## Best Practices

### Start Conservative

1. **Begin with moderate values**: Don't jump to extremes
2. **Test during safe conditions**: Moderate weather, normal battery SOC
3. **Monitor closely**: Watch battery temperature, voltage, current
4. **Adjust gradually**: Increase/decrease in 25A increments
5. **Validate results**: Compare daily production to baseline

### Automation Design

1. **Add logging**: Use `logbook.log` to track automation decisions
2. **Include safeguards**: Check battery temperature, SOC before adjusting
3. **Avoid rapid changes**: Limit automation frequency (5-10 minute minimum)
4. **Test scenarios**: Verify behavior in all weather conditions
5. **Document settings**: Comment your automation with reasoning

### Seasonal Adjustments

- **Summer**: Lower charge rates during peak production
- **Winter**: Higher charge rates to maximize limited sun
- **Spring/Fall**: Moderate rates, adjust based on weather patterns

### Multi-Inverter Systems

For parallel inverter setups:
- Set all inverters to the same charge/discharge limits
- Use parallel group sensors to monitor total system current
- Account for total battery capacity across all inverters

## Advanced Topics

### Dynamic Rate Calculation

Calculate optimal charge rate based on production and consumption:

```yaml
# Template sensor for optimal charge rate
- sensor:
    - name: "Optimal Battery Charge Rate"
      unit_of_measurement: "A"
      state: >
        {% set pv_power = states('sensor.eg4_18kpv_1234567890_pv_power') | float %}
        {% set consumption = states('sensor.eg4_18kpv_1234567890_load_power') | float %}
        {% set max_ac = 12000 %}  # Inverter max AC output
        {% set battery_voltage = states('sensor.eg4_18kpv_1234567890_battery_voltage') | float %}

        {% if pv_power > max_ac %}
          {# High production: limit charge to force export #}
          {% set target_charge_power = (pv_power - max_ac + consumption) | max(2000) %}
          {{ (target_charge_power / battery_voltage) | round(0) }}
        {% else %}
          {# Normal production: maximize charging #}
          200
        {% endif %}
```

### Integration with Energy Management

Coordinate with other home energy systems:
- EV charging schedules
- Smart water heater control
- HVAC pre-cooling/heating
- Grid export limits

### Seasonal Profiles

Create input_select with seasonal profiles:

```yaml
input_select:
  battery_charge_profile:
    options:
      - "Summer - High Export"
      - "Winter - Max Charge"
      - "Spring/Fall - Balanced"
      - "Manual Override"
```

Then use in automations to select appropriate charge rates.

## Related Features

- **Operating Mode Control**: `select.eg4_{model}_{serial}_operating_mode`
- **AC Charge Power**: `number.eg4_{model}_{serial}_ac_charge_power`
- **Battery SOC Limits**: Various battery parameter sensors
- **Grid Export Control**: Via operating mode and power settings

## Support

For issues, questions, or feature requests:
- GitHub Issues: https://github.com/joyfulhouse/eg4_web_monitor/issues
- Example automations: https://github.com/joyfulhouse/eg4_web_monitor/tree/main/examples/automations
- Integration documentation: [README.md](../README.md)

## Version History

- **v2.2.6**: Initial release of battery charge/discharge current control
  - Added number entities for charge and discharge current
  - Comprehensive automation examples
  - Full documentation and use cases
