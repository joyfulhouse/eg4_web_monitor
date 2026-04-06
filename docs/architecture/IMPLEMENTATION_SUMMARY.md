# Station/Plant Device Implementation Summary

## Implementation Status: ✅ COMPLETE

This document describes the station-level device implementation for managing EG4 monitoring stations/plants directly from Home Assistant.

## Implemented Features

### Station Device
- Station appears as a device in Home Assistant
- Device info includes station name, plant ID, address, and creation date
- Station entities are grouped under the station device

### Station Entities

| Entity Type | Name | Description | Status |
|-------------|------|-------------|--------|
| Switch | Daylight Saving Time | Toggle DST for station time sync | ✅ Implemented |
| Button | Refresh Data | Force refresh all station data | ✅ Implemented |
| Sensor | Station Name | Read-only station name | ✅ Implemented |
| Sensor | Timezone | Current timezone setting | ✅ Implemented |

### API Endpoints Used
1. **GET** `/WManage/web/config/plant/list/viewer` - Get plant details
2. **POST** `/WManage/web/config/plant/edit` - Update plant configuration (DST)

## Architecture

### Coordinator Integration
Station data is fetched and stored in `coordinator.data["station"]`:
```python
{
    "name": "My Solar Station",
    "plantId": "12345",
    "daylightSavingTime": True,
    "timezone": "WEST8",
    "country": "UNITED_STATES_OF_AMERICA",
    "createDate": "2024-01-15",
    ...
}
```

### Entity Base Classes
Station entities inherit from `EG4StationEntity` in `base_entity.py`:
```python
class EG4StationEntity(CoordinatorEntity):
    """Base class for station-level entities."""

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_station_device_info()
```

### DST Switch Implementation
The DST switch (`EG4DSTSwitch`) in `switch.py`:
- Uses optimistic state for immediate UI feedback
- Calls `station.set_daylight_saving_time(enabled)` on the device object
- Triggers coordinator refresh after state change
- Entity category: CONFIG

## Example Automation

### Automatic DST Changes
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
        entity_id: switch.eg4_station_daylight_saving_time

  - alias: "Auto-disable DST (Fall)"
    trigger:
      platform: time
      at: "02:00:00"
    condition:
      - condition: template
        value_template: >
          {{ now().month == 11 and now().day >= 1 and
             now().day <= 7 and now().weekday() == 6 }}
    action:
      service: switch.turn_off
      target:
        entity_id: switch.eg4_station_daylight_saving_time
```

## File References

| File | Purpose |
|------|---------|
| `coordinator.py` | Station data fetching and caching |
| `coordinator_mixins.py` | `DSTSyncMixin` for DST synchronization |
| `base_entity.py` | `EG4StationEntity` base class |
| `switch.py` | `EG4DSTSwitch` implementation |
| `button.py` | `EG4StationRefreshButton` implementation |

## Related Documentation
- `docs/DST_AUTOMATION_IMPLEMENTATION.md` - Detailed DST automation guide
- `docs/PLANT_API_DOCUMENTATION.md` - Complete plant API reference
