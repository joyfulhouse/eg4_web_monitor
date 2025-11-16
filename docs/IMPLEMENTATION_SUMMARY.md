# Station/Plant Device Implementation Summary

## Files Saved
1. `plant_list_viewer.json` - API response from viewer endpoint
2. `plant_list_viewer_formatted.json` - Formatted version
3. `plant_edit_page.html` - HTML form showing all editable fields
4. `PLANT_API_DOCUMENTATION.md` - Complete API documentation

## Key Findings

### Editable Station Fields
| Field | Type | Current Value | HA Entity Type |
|-------|------|---------------|----------------|
| name | text | "My Solar Station" | sensor (read-only) |
| nominalPower | integer | 19000 W | number |
| continent | select | NORTH_AMERICA | select |
| region | select | NORTH_AMERICA | select |
| country | select | UNITED_STATES_OF_AMERICA | select |
| timezone | select | WEST8 (GMT -8) | select |
| **daylightSavingTime** | boolean | false | **switch** |

### API Endpoints Identified
1. **GET** `/WManage/web/config/plant/list/viewer` - Get plant details
2. **GET** `/WManage/web/config/plant/edit/{plantId}` - Get edit form (HTML)
3. **POST** `/WManage/web/config/plant/edit` - Update plant configuration

## Implementation Plan

### 1. API Client Extensions (`eg4_inverter_api/client.py`)
Add three new methods:
- `get_plant_details(plant_id)` - Fetch current configuration
- `update_plant_config(plant_id, **kwargs)` - Update any field(s)
- `set_daylight_saving_time(plant_id, enabled)` - Quick DST toggle

### 2. Constants (`const.py`)
Add new constant dictionaries:
- `TIMEZONE_OPTIONS` - All 26 timezone choices
- `CONTINENT_OPTIONS` - 6 continent choices
- `STATION_SENSOR_TYPES` - Sensor definitions for station data
- `DEVICE_TYPE_STATION` - New device type constant

### 3. Coordinator Updates (`coordinator.py`)
- Fetch plant details during `async_config_entry_first_refresh()`
- Create station device info structure
- Store station data in `self.data["station"]`
- Add refresh method for station data

### 4. Sensor Platform (`sensor.py`)
Add read-only sensors for station:
- Station Name
- Country
- Timezone (formatted)
- Creation Date
- Address

### 5. Number Platform (`number.py`)
Add editable number entity:
- Solar PV Power (W) - range 1-999999, step 100

### 6. Select Platform (`select.py`)
Add editable select entities:
- Continent
- Region (filtered by continent)
- Country (filtered by region)
- Timezone (26 options)

### 7. Switch Platform (`switch.py`)
Add DST switch entity:
- Daylight Saving Time (on/off)
- Icon: mdi:clock-time-four
- Entity category: config

## File Modification Order
1. ✅ `samples/PLANT_API_DOCUMENTATION.md` - Documentation created
2. ⏳ `eg4_inverter_api/client.py` - Add 3 new API methods
3. ⏳ `const.py` - Add station constants
4. ⏳ `coordinator.py` - Add station data fetching
5. ⏳ `sensor.py` - Add station sensors
6. ⏳ `number.py` - Add solar PV power number
7. ⏳ `select.py` - Add station selects
8. ⏳ `switch.py` - Add DST switch
9. ⏳ Test in Docker environment
10. ⏳ Run lint/type checks

## Testing Plan
1. Verify station device appears in HA
2. Test DST switch toggle
3. Test number entity updates
4. Test select entity updates
5. Create automation for automatic DST changes
6. Validate all read-only sensors

## Automation Example
```yaml
automation:
  - alias: "Auto-enable DST (Spring)"
    trigger:
      platform: time
      at: "02:00:00"
    condition:
      - condition: template
        value_template: >
          {{ now().month == 3 and now().day >= 8 and
             now().day <= 14 and now().weekday() == 6 }}
    action:
      service: switch.turn_on
      target:
        entity_id: switch.eg4_station_6245_n_willard_daylight_saving_time
```

## Next Steps
Begin implementation with API client method additions.
