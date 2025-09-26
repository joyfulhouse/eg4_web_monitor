# EG4 Web Monitor Automations

This directory contains example Home Assistant automations that work with the EG4 Web Monitor integration to provide advanced battery management and monitoring capabilities.

## Available Automations

### 🔋 Battery Cell Balancing (`battery_cell_balancing.yaml`)

A single, comprehensive automation that monitors battery cell voltage deltas and automatically manages the complete top balancing cycle.

#### **Functionality**:
- **Monitoring**: Continuously watches all battery cell voltage delta sensors
- **Detection**: Triggers when ANY battery has a delta > 0.05V for more than 24 hours
- **Balancing**: Sets `system_charge_soc_limit` to 101% for top balancing
- **Auto-Recovery**: After SOC limit has been 101% for 48 hours, returns to normal 80% charge limit
- **Self-Contained**: No helper entities required - uses trigger IDs and choose actions

#### **How It Works**:
1. **Trigger 1 - Start Balancing**: Monitors cell voltage deltas, triggers when > 0.05V for 24h
2. **Trigger 2 - End Balancing**: Monitors SOC limit, triggers when 101% for 48h
3. **Smart Actions**: Uses `trigger_id` and `choose` to execute appropriate actions
4. **Automatic Cycle**: Complete hands-off operation from detection to recovery

#### **Benefits**:
- **No Helper Entities**: Self-contained automation without `input_boolean` requirements
- **Simplified Setup**: Single automation handles the entire balancing cycle
- **Smart Logic**: Uses SOC limit state as the balancing indicator
- **Safety Features**: Built-in conditions prevent conflicts and double-triggering

## Installation Instructions

### Step 1: Install the Automation

**Option A: Via Home Assistant UI**
1. Copy the entire automation from the YAML file
2. Go to Settings → Automations & Scenes → Automations
3. Click "Add Automation" → "Start with empty automation" 
4. Switch to YAML mode and paste the automation code
5. Save and enable

**Option B: Via automations.yaml**
1. Copy the automation to your `automations.yaml` file
2. Reload automations: Developer Tools → YAML → Reload Automations

### Step 2: Customize Entity IDs (Required)

Update these entity IDs to match your system:

```yaml
# Battery cell voltage delta sensors (Trigger 1)
entity_id:
  - sensor.battery_1234567890_01_cell_voltage_delta
  - sensor.battery_1234567890_02_cell_voltage_delta
  - sensor.battery_0987654321_01_cell_voltage_delta
  - sensor.battery_0987654321_02_cell_voltage_delta

# SOC limit control (appears in Trigger 2 AND both actions)
entity_id: number.flexboss21_1234567890_system_charge_soc_limit
```

### Step 3: Configure Notifications (Optional)

Uncomment and configure notification services:

```yaml
# For mobile notifications
service: notify.mobile_app_your_phone

# For persistent web notifications  
service: notify.persistent_notification
```

## Finding Your Entity IDs

1. Go to **Developer Tools** → **States**
2. Search for `cell_voltage_delta` to find your battery delta sensors
3. Search for `system_charge_soc_limit` to find your SOC limit control
4. Copy the exact entity IDs into the automation

## Automation Logic Flow

### **Trigger 1: Start Balancing**
```yaml
- id: "start_balancing"
  platform: numeric_state
  entity_id: [battery_delta_sensors]
  above: 0.05
  for: hours: 24
```

**Conditions**:
- Must be triggered by `start_balancing`
- SOC limit must be below 101% (not already balancing)

**Actions**:
- Set SOC limit to 101%
- Log start of balancing cycle
- Send optional notification

### **Trigger 2: End Balancing**
```yaml
- id: "end_balancing" 
  platform: numeric_state
  entity_id: number.*_system_charge_soc_limit
  above: 100
  for: hours: 48
```

**Conditions**:
- Must be triggered by `end_balancing`
- SOC limit must be above 100% (currently balancing)

**Actions**:
- Set SOC limit to 80%
- Log completion of balancing cycle
- Send optional notification

## Customization Options

### Adjust Detection Threshold
```yaml
above: 0.05  # Voltage delta threshold (0.05V = 50mV)
```

### Adjust Timing
```yaml
for:
  hours: 24    # Detection period before starting balancing

for:
  hours: 48    # Balancing duration before returning to normal
```

### Adjust SOC Limits
```yaml
value: 101     # Balancing SOC (101% for top balancing)
value: 80      # Normal SOC (80% for daily use)
```

## Safety Features

### **Built-in Protections**:
- ✅ **Condition Checks**: Won't start if already balancing, won't end if not balancing
- ✅ **Manual Override**: Can manually change SOC limit anytime without breaking automation
- ✅ **State-Based Logic**: Uses actual SOC limit value to determine balancing state
- ✅ **Comprehensive Logging**: All actions logged to Home Assistant logbook
- ✅ **No Helper Dependencies**: Self-contained without additional entities

### **Emergency Stop Procedure**:
1. Go to Settings → Devices & Services → EG4 Web Monitor
2. Find your SOC Limit entity
3. Manually set it to 80% (or your preferred normal value)
4. The automation will detect this and not interfere

## Monitoring & Dashboard

### View Automation Activity
- **History**: Go to History → Logbook, filter by "EG4 Battery Balancing"
- **Automation State**: Check the automation entity in Developer Tools → States
- **SOC Limit**: Monitor the current SOC limit value
- **Cell Deltas**: Watch your battery cell voltage delta sensors

### Dashboard Example
```yaml
# Automation control card
type: entity
entity: automation.eg4_battery_cell_balancing
name: "Battery Balancing Automation"

# SOC Limit monitoring
type: entity  
entity: number.flexboss21_1234567890_system_charge_soc_limit
name: "Current SOC Limit"

# Battery delta monitoring
type: entities
entities:
  - sensor.battery_1234567890_01_cell_voltage_delta
  - sensor.battery_1234567890_02_cell_voltage_delta
title: "Battery Cell Voltage Deltas"
```

## Troubleshooting

### Automation Not Triggering
- ✅ Verify entity IDs are correct (check Developer Tools → States)
- ✅ Ensure cell voltage delta sensors are reporting values > 0.05V
- ✅ Check that 24 hours have passed since threshold was exceeded
- ✅ Verify SOC limit is currently below 101%

### Balancing Not Ending
- ✅ Verify SOC limit entity ID is correct in both trigger and action
- ✅ Check that SOC limit has actually been above 100% for 48+ hours
- ✅ Look at automation history to see if the end trigger has fired

### Manual Intervention Needed
- ✅ You can manually change the SOC limit anytime
- ✅ The automation will adapt to manual changes
- ✅ No need to disable the automation for manual control

### Check Logs
- ✅ Go to History → Logbook and filter by "EG4 Battery Balancing"
- ✅ Enable automation debug logging if needed
- ✅ Check automation trace in Developer Tools

## Advanced Configuration

### Multiple Battery Banks
If you have multiple inverters/battery banks, create separate automations for each:

```yaml
# Copy the automation and update:
- id: eg4_battery_cell_balancing_bank_1
  # Update all entity IDs for first bank

- id: eg4_battery_cell_balancing_bank_2  
  # Update all entity IDs for second bank
```

### Different Balancing Parameters
Customize thresholds per battery type:

```yaml
# For newer batteries (more sensitive)
above: 0.03  # 30mV threshold

# For older batteries (less sensitive)  
above: 0.08  # 80mV threshold
```

## Safety Considerations

### ⚠️ **Critical Safety Notes**:

1. **Battery Compatibility**: Verify your batteries support 101% SOC charging
2. **Monitoring Required**: Watch the first few cycles closely
3. **Emergency Access**: Always have manual override capability
4. **Ventilation**: Ensure adequate ventilation during balancing
5. **Temperature**: Avoid balancing in extreme temperatures
6. **Load Management**: Consider reducing load during balancing cycles

### **Before First Use**:
- ✅ Test with shorter durations initially
- ✅ Verify all entity IDs are correct
- ✅ Confirm SOC limit control is working
- ✅ Set up notifications to monitor progress
- ✅ Read your battery manufacturer's balancing guidelines

## Contributing

Have improvements for this automation? Please contribute:

1. Fork the repository
2. Improve the automation with better logic or safety features
3. Update this documentation
4. Submit a pull request

## Support

For issues with this automation:
- [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io)

---

**⚠️ Disclaimer**: This automation modifies your inverter settings and charging behavior. Use at your own risk and ensure you understand the implications of top balancing your specific battery system.