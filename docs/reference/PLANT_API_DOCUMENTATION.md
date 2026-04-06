# Plant/Station Configuration API Documentation

## Overview
This document describes the EG4 Web Monitor API endpoints for managing plant/station configuration, including the critical Daylight Saving Time (DST) setting that requires manual adjustment.

## Business Requirement
**Problem**: EG4 does not automatically apply Daylight Saving Time enable/disable based on time of year, requiring manual configuration changes.

**Solution**: Create a Station device in Home Assistant with entities to view and modify plant settings, enabling automation of DST changes.

## API Endpoints

### 1. Get Plant List (Detailed View)
**Endpoint**: `/WManage/web/config/plant/list/viewer`
**Method**: POST
**Authentication**: Required (JSESSIONID cookie)

**Request Parameters**:
```
page=1
rows=20
searchText=
targetPlantId=19147
sort=createDate
order=desc
```

**Response Structure**:
```json
{
    "total": 1,
    "rows": [
        {
            "id": 19147,
            "plantId": 19147,
            "name": "6245 N WILLARD",
            "nominalPower": 19000,
            "country": "United States of America",
            "currentTimezoneWithMinute": -800,
            "timezone": "GMT -8",
            "daylightSavingTime": false,
            "createDate": "2025-05-05",
            "noticeFault": false,
            "noticeWarn": false,
            "noticeEmail": "",
            "noticeEmail2": "",
            "contactPerson": "",
            "contactPhone": "",
            "address": "6245 North Willard Avenue"
        }
    ]
}
```

**Key Fields**:
- `plantId`: Unique plant identifier (used in API calls)
- `name`: Station name (editable)
- `nominalPower`: Solar PV power rating in Watts (editable)
- `timezone`: Timezone string (editable, see timezone options below)
- `daylightSavingTime`: Boolean - DST enabled/disabled (editable) **← TARGET FIELD**
- `currentTimezoneWithMinute`: Current timezone offset in minutes
- `country`: Country name (display only from editable enum)
- `createDate`: Plant creation date
- `address`: Physical address

### 2. Get Plant Edit Page (HTML Form)
**Endpoint**: `/WManage/web/config/plant/edit/{plantId}`
**Method**: GET
**Authentication**: Required (JSESSIONID cookie)

**Purpose**: Returns HTML form showing all editable fields and their current values.

**Editable Fields Identified**:

1. **name** (text input, maxLength=50)
   - Current: "6245 N WILLARD"
   - Home Assistant Entity: `sensor.{station}_name`

2. **nominalPower** (text input, maxLength=10)
   - Current: 19000
   - Unit: Watts
   - Validation: Positive integer
   - Home Assistant Entity: `number.{station}_solar_pv_power`

3. **continent** (select dropdown)
   - Current: "NORTH_AMERICA"
   - Options: ASIA, EUROPE, AFRICA, OCEANIA, NORTH_AMERICA, SOUTH_AMERICA
   - Home Assistant Entity: `select.{station}_continent`

4. **region** (select dropdown)
   - Current: "NORTH_AMERICA"
   - Options depend on continent selection
   - North America regions: NORTH_AMERICA, CENTRAL_AMERICA, CARIBBEAN
   - Home Assistant Entity: `select.{station}_region`

5. **country** (select dropdown)
   - Current: "UNITED_STATES_OF_AMERICA"
   - Options depend on region selection
   - North America countries: CANADA, UNITED_STATES_OF_AMERICA, MEXICO, GREENLAND
   - Home Assistant Entity: `select.{station}_country`

6. **timezone** (select dropdown)
   - Current: "WEST8" (GMT -8)
   - Options: WEST12 through EAST12, including half-hour zones
   - Full list: WEST12, WEST11, WEST10, WEST9, WEST8, WEST7, WEST6, WEST5, WEST4, WEST3, WEST2, WEST1, ZERO, EAST1, EAST2, EAST3, EAST3_30, EAST4, EAST5, EAST5_30, EAST6, EAST6_30, EAST7, EAST8, EAST9, EAST10, EAST11, EAST12
   - Display format: "GMT {offset}"
   - Home Assistant Entity: `select.{station}_timezone`

7. **daylightSavingTime** (radio buttons: "true" or "false")
   - Current: false
   - **PRIMARY AUTOMATION TARGET**
   - Home Assistant Entity: `switch.{station}_daylight_saving_time` or `binary_sensor.{station}_dst_status`

**Read-Only Fields**:
- `plantId` (hidden input) - Used in update request
- `longitude` (hidden input) - Geographic coordinate
- `latitude` (hidden input) - Geographic coordinate
- `createDate` (readonly text input) - Plant creation date

### 3. Update Plant Configuration
**Endpoint**: `/WManage/web/config/plant/edit`
**Method**: POST
**Authentication**: Required (JSESSIONID cookie)
**Content-Type**: `application/x-www-form-urlencoded; charset=UTF-8`

**Request Parameters** (from user's curl example):
```
plantId=19147
name=6245+N+WILLARD
longitude=-118.10842
latitude=34.09724
createDate=2025-05-05
nominalPower=19000
continent=NORTH_AMERICA
region=NORTH_AMERICA
country=UNITED_STATES_OF_AMERICA
timezone=WEST8
daylightSavingTime=false
```

**Expected Response**:
```json
{
    "success": true,
    "message": "Plant updated successfully"
}
```

## Implementation Plan

### Phase 1: API Client Extension
Add methods to `eg4_inverter_api/client.py`:

```python
async def get_plant_details(self, plant_id: str) -> Dict[str, Any]:
    """Get detailed plant/station information."""
    data = {
        "page": 1,
        "rows": 20,
        "searchText": "",
        "targetPlantId": plant_id,
        "sort": "createDate",
        "order": "desc",
    }
    result = await self._make_request(
        "POST",
        "/WManage/web/config/plant/list/viewer",
        data=data
    )
    if result.get("rows"):
        return result["rows"][0]
    raise EG4APIError("Plant not found")

async def update_plant_config(
    self,
    plant_id: str,
    **kwargs: Any
) -> Dict[str, Any]:
    """Update plant/station configuration.

    Args:
        plant_id: Plant ID
        **kwargs: Configuration parameters (name, nominalPower, timezone,
                  daylightSavingTime, continent, region, country, etc.)
    """
    # Get current configuration to ensure all required fields are present
    current = await self.get_plant_details(plant_id)

    # Merge current config with updates
    data = {
        "plantId": plant_id,
        "name": kwargs.get("name", current.get("name")),
        "longitude": current.get("longitude"),
        "latitude": current.get("latitude"),
        "createDate": current.get("createDate"),
        "nominalPower": kwargs.get("nominalPower", current.get("nominalPower")),
        "continent": kwargs.get("continent", current.get("continent")),
        "region": kwargs.get("region", current.get("region")),
        "country": kwargs.get("country", current.get("country")),
        "timezone": kwargs.get("timezone", current.get("timezone")),
        "daylightSavingTime": kwargs.get("daylightSavingTime", current.get("daylightSavingTime")),
    }

    return await self._make_request(
        "POST",
        "/WManage/web/config/plant/edit",
        data=data
    )

async def set_daylight_saving_time(
    self,
    plant_id: str,
    enabled: bool
) -> Dict[str, Any]:
    """Set Daylight Saving Time for a plant/station.

    Args:
        plant_id: Plant ID
        enabled: True to enable DST, False to disable
    """
    return await self.update_plant_config(
        plant_id,
        daylightSavingTime=enabled
    )
```

### Phase 2: Station Device Creation
Modify `coordinator.py` to create a Station device during discovery:

```python
# In async_config_entry_first_refresh or device discovery
plant_details = await self.api.get_plant_details(self.plant_id)

# Create station device
station_device = {
    "identifiers": {(DOMAIN, f"station_{self.plant_id}")},
    "name": f"Station: {plant_details.get('name')}",
    "manufacturer": "EG4 Electronics",
    "model": "Station",
    "sw_version": None,
    "configuration_url": f"{self.api.base_url}/WManage/web/config/plant/edit/{self.plant_id}",
}

# Store in coordinator data
self.data["station"] = {
    "device_info": station_device,
    "config": plant_details,
}
```

### Phase 3: Entity Creation

#### Sensor Entities (Read-Only)
- `sensor.eg4_station_{name}_name` - Station name
- `sensor.eg4_station_{name}_country` - Country (formatted text)
- `sensor.eg4_station_{name}_timezone` - Timezone (formatted text)
- `sensor.eg4_station_{name}_create_date` - Creation date
- `sensor.eg4_station_{name}_address` - Physical address

#### Number Entity (Editable)
- `number.eg4_station_{name}_solar_pv_power` - Solar PV Power (W)
  - Min: 1
  - Max: 999999
  - Step: 100
  - Unit: W
  - Device class: power
  - Entity category: config

#### Select Entities (Editable)
- `select.eg4_station_{name}_continent` - Continent selection
- `select.eg4_station_{name}_region` - Region selection (options filtered by continent)
- `select.eg4_station_{name}_country` - Country selection (options filtered by region)
- `select.eg4_station_{name}_timezone` - Timezone selection

#### Switch/Binary Sensor for DST
**Option 1: Switch Entity** (Recommended for automation)
- `switch.eg4_station_{name}_daylight_saving_time`
  - Device class: switch
  - Entity category: config
  - Icon: mdi:clock-time-four

**Option 2: Binary Sensor + Service Call**
- `binary_sensor.eg4_station_{name}_dst_status` (read-only status)
- Service: `eg4_web_monitor.set_dst` (for updates)

### Phase 4: Home Assistant Automation Example

```yaml
automation:
  - alias: "Enable DST for EG4 Station (Spring Forward)"
    trigger:
      - platform: time
        at: "02:00:00"  # 2 AM on DST start date
    condition:
      - condition: template
        value_template: >
          {# Second Sunday in March #}
          {{ now().month == 3 and
             now().day >= 8 and
             now().day <= 14 and
             now().weekday() == 6 }}
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.eg4_station_6245_n_willard_daylight_saving_time

  - alias: "Disable DST for EG4 Station (Fall Back)"
    trigger:
      - platform: time
        at: "02:00:00"  # 2 AM on DST end date
    condition:
      - condition: template
        value_template: >
          {# First Sunday in November #}
          {{ now().month == 11 and
             now().day >= 1 and
             now().day <= 7 and
             now().weekday() == 6 }}
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.eg4_station_6245_n_willard_daylight_saving_time
```

## Timezone Options Reference

| Value | Display | Offset |
|-------|---------|--------|
| WEST12 | GMT -12 | -12:00 |
| WEST11 | GMT -11 | -11:00 |
| WEST10 | GMT -10 | -10:00 |
| WEST9 | GMT -9 | -9:00 |
| WEST8 | GMT -8 | -8:00 |
| WEST7 | GMT -7 | -7:00 |
| WEST6 | GMT -6 | -6:00 |
| WEST5 | GMT -5 | -5:00 |
| WEST4 | GMT -4 | -4:00 |
| WEST3 | GMT -3 | -3:00 |
| WEST2 | GMT -2 | -2:00 |
| WEST1 | GMT -1 | -1:00 |
| ZERO | GMT 0 | 0:00 |
| EAST1 | GMT +1 | +1:00 |
| EAST2 | GMT +2 | +2:00 |
| EAST3 | GMT +3 | +3:00 |
| EAST3_30 | GMT +3:30 | +3:30 |
| EAST4 | GMT +4 | +4:00 |
| EAST5 | GMT +5 | +5:00 |
| EAST5_30 | GMT +5:30 | +5:30 |
| EAST6 | GMT +6 | +6:00 |
| EAST6_30 | GMT +6:30 | +6:30 |
| EAST7 | GMT +7 | +7:00 |
| EAST8 | GMT +8 | +8:00 |
| EAST9 | GMT +9 | +9:00 |
| EAST10 | GMT +10 | +10:00 |
| EAST11 | GMT +11 | +11:00 |
| EAST12 | GMT +12 | +12:00 |

## Testing Checklist
- [ ] Test get_plant_details() retrieves all fields correctly
- [ ] Test update_plant_config() with single field change
- [ ] Test set_daylight_saving_time() toggle
- [ ] Verify Station device appears in Home Assistant
- [ ] Verify all sensor entities show correct values
- [ ] Verify switch entity can toggle DST
- [ ] Test automation triggers at correct times
- [ ] Validate API response handling for errors
- [ ] Test with multiple stations (if applicable)

## Notes
- The `longitude` and `latitude` fields are read-only and must be included in update requests with their current values
- The `createDate` field is also read-only but required in update payload
- All editable select fields use enum values (e.g., "NORTH_AMERICA") not display text
- DST field is boolean type in API but radio buttons in UI (true/false strings)
- Continent/Region/Country selections are hierarchical - changing continent affects region options
