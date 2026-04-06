# Component Reference

## Coordinator Architecture

The coordinator is the data hub. It inherits from 7 mixins:

```python
class EG4DataUpdateCoordinator(
    HTTPUpdateMixin,           # Cloud API fetching
    LocalTransportMixin,       # Modbus/Dongle operations
    DeviceProcessingMixin,     # Device→sensor data mapping
    DeviceInfoMixin,           # HA DeviceInfo generation
    ParameterManagementMixin,  # Register read/write
    DSTSyncMixin,              # Daylight saving time sync
    BackgroundTaskMixin,       # Async task lifecycle
    FirmwareUpdateMixin,       # Firmware version extraction
    DataUpdateCoordinator,     # HA base class
)
```

### Mixin Responsibilities

| Mixin | File | Key Methods |
|-------|------|-------------|
| HTTPUpdateMixin | `coordinator_http.py` | `_async_update_http_data()`, `_async_update_hybrid_data()`, `_refresh_station_devices()` |
| LocalTransportMixin | `coordinator_local.py` | `_async_update_local_data()`, `_build_static_local_data()`, `_merge_round_robin_batteries()` |
| DeviceProcessingMixin | `coordinator_mixins.py` | `_process_inverter_object()`, `_process_mid_device_object()`, `_extract_inverter_features()` |
| DeviceInfoMixin | `coordinator_mixins.py` | `get_device_info()`, `get_battery_device_info()`, `get_station_device_info()` |
| ParameterManagementMixin | `coordinator_mixins.py` | `_should_refresh_parameters()`, `write_named_parameter()` |
| DSTSyncMixin | `coordinator_mixins.py` | `_should_sync_dst()`, `_perform_dst_sync()` |
| BackgroundTaskMixin | `coordinator_mixins.py` | Background task set management, shutdown cleanup |
| FirmwareUpdateMixin | `coordinator_mixins.py` | `_extract_firmware_update_info()` |

### Data Update Routing

```
_async_update_data()
└─ _route_update_by_connection_type()
   ├─ HTTP    → Station.refresh_all_data() → _process_inverter_object() per device
   ├─ LOCAL   → transport.refresh() per device → _build_local_sensor_data()
   ├─ HYBRID  → local runtime + cloud battery/energy → GridBOSS overlay
   ├─ MODBUS  → ModbusTransport.read_runtime/energy/battery()
   └─ DONGLE  → DongleTransport.read_runtime/energy/battery()
```

## Entity Base Classes

All in `base_entity.py` (1,070 lines):

| Class | Inherits | Purpose | Unique ID Format |
|-------|----------|---------|------------------|
| `EG4DeviceEntity` | CoordinatorEntity | Inverter/GridBOSS entities | — |
| `EG4BatteryEntity` | CoordinatorEntity | Individual battery entities | — |
| `EG4StationEntity` | CoordinatorEntity | Station/plant entities | — |
| `EG4BaseSensor` | EG4DeviceEntity + SensorEntity | Device sensors | `{serial}_{sensor_key}` |
| `EG4BaseBatterySensor` | EG4BatteryEntity + SensorEntity | Battery sensors | `{serial}_{battery_key}_{sensor_key}` |
| `EG4BatteryBankEntity` | EG4DeviceEntity + SensorEntity | Bank aggregate sensors | `{serial}_battery_bank_{sensor_key}` |
| `EG4BaseSwitch` | EG4DeviceEntity + SwitchEntity | Control switches | `{serial}_{switch_key}` |
| `EG4BaseNumber` | EG4DeviceEntity + NumberEntity | Parameter controls | `{serial}_{number_key}` |

### Entity Creation Order (sensor.py)

Three phases to satisfy `via_device` references:

1. **Phase 1**: Station + parallel group sensors (root devices)
2. **Phase 2**: Inverter, GridBOSS, battery bank sensors (reference PG via `via_device`)
3. **Phase 3**: Individual battery sensors (reference bank via `via_device`)

## pylxpweb Integration Points

### Client Initialization

```python
# coordinator.py — session injection for HA Platinum tier
self.client = LuxpowerClient(
    username, password,
    session=aiohttp_client.async_get_clientsession(hass),  # HA session
    iana_timezone=iana_timezone,
)
```

### Device Hierarchy

```python
# coordinator_http.py — Station is the root object
self.station = await Station.load(self.client, int(self.plant_id))
await self.station.refresh_all_data()

# Iterate all devices
for inverter in self.station.all_inverters:
    data = self._process_inverter_object(inverter)
for mid in self.station.all_mid_devices:
    data = self._process_mid_device_object(mid)
```

### Transport Creation

```python
# coordinator_local.py — create from config entry
transport = create_transport(
    transport_type,  # "modbus", "dongle", "serial"
    host=config[CONF_MODBUS_HOST],
    port=config[CONF_MODBUS_PORT],
    serial=config[CONF_INVERTER_SERIAL],
)
```

### Property Access Pattern

```python
# CORRECT: use inverter properties (auto-scaled)
voltage = inverter.grid_voltage_r        # 241.8V
soc = inverter.battery_soc               # 85%
power = inverter.pv_total_power          # 1500W

# WRONG: access private data directly
voltage = inverter._runtime.vacr / 10    # Manual scaling — avoid
```

### Parameter Read/Write

```python
# Read: coordinator reads via transport
params = await transport.read_named_parameters(start_reg, count)

# Write: entities call coordinator method
await coordinator.write_named_parameter("ac_charge_soc_limit", 90, serial)
# Coordinator routes to transport → pylxpweb handles register mapping
```

### Feature Detection

```python
features = inverter._features  # dict from detect_features()
is_split_phase = features.get("supports_split_phase", False)
is_three_phase = features.get("supports_three_phase", False)
# Used by coordinator to filter sensor creation
```

## pylxpweb Library Architecture

### Device Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `LuxpowerClient` | `client.py` | HTTP client + auth + caching |
| `Station` | `devices/station.py` | Plant container (inverters, groups, MID) |
| `ParallelGroup` | `devices/parallel_group.py` | Inverter cluster aggregation |
| `BaseInverter` | `devices/inverters/base.py` | Abstract inverter (80+ properties) |
| `GenericInverter` | `devices/inverters/generic.py` | Standard inverter |
| `HybridInverter` | `devices/inverters/hybrid.py` | Hybrid inverter variant |
| `BatteryBank` | `devices/battery_bank.py` | Battery aggregate (SoC, voltage, power) |
| `Battery` | `devices/battery.py` | Individual battery module |
| `MIDDevice` | `devices/mid_device.py` | GridBOSS (50+ properties) |

### Transport Implementations

| Transport | Module | Protocol | Use Case |
|-----------|--------|----------|----------|
| HTTP | `transports/http.py` | HTTPS REST | Cloud API |
| Modbus | `transports/modbus.py` | Modbus TCP (FC 03/04/06/16) | Direct LAN |
| Dongle | `transports/dongle.py` | Proprietary EG4 WiFi | Dongle gateway |
| Serial | `transports/serial.py` | Modbus RTU RS485 | Wired serial |
| Hybrid | `transports/hybrid.py` | Local + cloud fallback | Best of both |

### Data Classes (transports/data.py)

| Class | Fields | Source |
|-------|--------|--------|
| `InverterRuntimeData` | PV, battery, grid, EPS, temps, BMS | Input registers / API runtime |
| `InverterEnergyData` | Daily/total: PV, charge, discharge, grid, load | Input registers / API energy |
| `BatteryBankData` | Status, voltage, SoC, capacity, count | Battery info API / registers 5002+ |
| `BatteryData` | Per-module: voltage, current, SoC, SoH, cells, temp | Battery array / BMS registers |
| `InverterParameterData` | Config registers: modes, limits, schedules | Holding registers 0-250 |

### Scaling Rules

| Data Type | Example | Raw → Scaled | Factor |
|-----------|---------|-------------|--------|
| Inverter voltage | vpv1 | 5100 → 510.0V | ÷10 |
| Battery bank voltage | vBat | 530 → 53.0V | ÷10 |
| Individual battery voltage | totalVoltage | 5305 → 53.05V | ÷100 |
| Cell voltage | maxCellVoltage | 3317 → 3.317V | ÷1000 |
| Frequency | fac | 5998 → 59.98Hz | ÷100 |
| Energy | todayYielding | 184 → 18.4kWh | ÷10 |
| Power | ppv | 1030 → 1030W | None |
| Temperature | tinner | 39 → 39°C | None |
| BMS current | maxChgCurr | 200 → 20.0A | ÷10 |

### Inverter Families

| Family | Models | Register Map | Features |
|--------|--------|-------------|----------|
| `EG4_HYBRID` | FlexBOSS21/18, 18KPV, 12KPV | 18KPV/12KPV | Split-phase, parallel |
| `EG4_OFFGRID` | 12000XP, 6000XP | 12000XP | Off-grid, split-phase |
| `LXP` | LXP-EU 12K | LXP-EU | Three-phase |
| `LUXPOWER_SNA` | SNA12K-US | SNA | Split-phase |

### Exception Hierarchy

```
LuxpowerError
├── LuxpowerAPIError           # API returned error
├── LuxpowerAuthError          # Login failed
├── LuxpowerConnectionError    # Network issue
├── LuxpowerDeviceError        # Device not found
└── LuxpowerDeviceOfflineError # Device offline
```

### Caching Strategy

| Endpoint | TTL | Rationale |
|----------|-----|-----------|
| Device discovery | 15 min | Rarely changes |
| Battery info | 5 min | Slow-changing |
| Parameters | 2 min | Config registers |
| Quick charge | 1 min | User-initiated |
| Runtime/Energy | 20 sec | Real-time data |

### API Call Budget

| Operation | Calls | Frequency |
|-----------|-------|-----------|
| Discovery | 4 | Once per session |
| Runtime refresh (per inverter) | 3-4 | Every poll |
| Parameter refresh (per inverter) | 3 | Hourly |
| Battery info (per inverter) | 1 | Every poll |
| GridBOSS runtime | 1 | Every poll |

## Config Flow Architecture

Unified menu-based flow in `_config_flow/__init__.py`:

```
Entry Menu
├─ Cloud Path: credentials → validate → station picker → (optional local) → finish
├─ Local Path: transport type → configure → auto-discover → (add more) → finish
└─ Connection type auto-derived: cloud-only=HTTP, local-only=LOCAL, both=HYBRID
```

### Reconfigure Flow

Entry point: `reconfigure_menu` (MENU step)
- Update cloud credentials
- Add/remove local devices
- Detach cloud (downgrade to LOCAL)
- Preserves entity IDs and automations

### Options Flow

Runtime configuration (no integration reload required):
- HTTP/Modbus/Dongle polling intervals
- Parameter refresh interval
- Data validation toggle (canary checks)
- Library debug logging
- DST sync enable/disable
