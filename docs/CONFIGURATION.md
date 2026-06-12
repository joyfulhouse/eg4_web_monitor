# Configuration

Full configuration reference for EG4 Web Monitor.

## Connection Types

The integration supports five ways to reach your equipment. The connection
*type* is derived automatically from what you configure — you do not choose it
upfront.

| Connection type | Description | Update speed | Internet required |
|---|---|---|---|
| **Cloud API (HTTP)** | Connect via EG4's cloud service | 30 seconds | Yes |
| **Local Modbus TCP** | Direct RS485 connection via adapter | 5 seconds | No |
| **WiFi dongle** | Direct connection via the inverter's WiFi dongle | 5 seconds | No |
| **Serial Modbus (USB/RS485)** | Direct USB-to-RS485 serial connection | 5 seconds | No |
| **Hybrid** | Local polling + cloud for DST sync & quick charge | 5 seconds | Yes (cloud features) |

- **Cloud credentials only →** HTTP mode (30s polling).
- **Local device(s) only →** Local mode (5s polling).
- **Both cloud and local →** Hybrid mode (5s polling plus cloud-only features
  such as DST sync and quick charge).

### Cloud API (HTTP)

The easiest setup. Uses your EG4 Monitor account credentials to communicate with
EG4's cloud servers. No additional hardware is needed and it works anywhere with
internet, at the cost of a 30-second update interval and a dependency on EG4's
servers.

### Local Modbus TCP with a Waveshare RS485 adapter

For faster updates and local-only operation, connect directly to your inverter
using an RS485-to-Ethernet adapter such as the Waveshare RS485 to ETH (B).

#### Hardware

The following is the tested and validated setup. Other RS485 adapters and cables
may work, but this is what we recommend:

- **RS485 to Ethernet adapter** — choose one:
  - **Waveshare 2-CH RS485 to ETH** — 2 channels (~$25)
  - **Waveshare 4-CH RS485 to POE ETH** — 4 channels, PoE (~$45) — best for
    multiple inverters
- **RS485 cable** — 2-wire twisted pair:
  - a spare CAT5/CAT6 pair, or
  - shielded RS485 cable (recommended for long runs)
- **Ferrule crimping tool** — for clean, reliable RS485 terminal connections
- **Ethernet cable** — adapter to network
- **Network switch** — any managed switch works

> The 4-channel PoE version lets you connect multiple inverters or other RS485
> devices (such as energy meters) to a single adapter and powers it over
> Ethernet — no separate power supply needed. For cable runs over 50 feet, use
> shielded cable to reduce interference.

#### Wiring

```
EG4 Inverter RS485 Port          Waveshare RS485 to ETH (B)
┌─────────────────────┐          ┌─────────────────────┐
│  RS485-A (Pin 1) ───┼──────────┼── A+ (Terminal)     │
│  RS485-B (Pin 2) ───┼──────────┼── B- (Terminal)     │
│  GND (Pin 3) ───────┼──────────┼── GND (Terminal)    │
└─────────────────────┘          └─────────────────────┘
                                         │
                                         │ Ethernet
                                         ▼
                                   Your Network
```

> On EG4 18kPV inverters, the RS485 port is labeled "BMS/Meter" and is on the
> bottom of the inverter. Use pins 1 (A), 2 (B), and 3 (GND).

#### Waveshare adapter settings

1. Connect the adapter to your network via Ethernet.
2. Open the web configuration at `http://192.168.1.200` (default IP).
3. Configure:
   - **Network:** static IP (e.g. `192.168.1.100`), subnet `255.255.255.0`,
     gateway = your router IP.
   - **Serial port:** baud `19200`, data bits `8`, stop bits `1`, parity `None`.
   - **Working mode:** `TCP Server`, local port `502` (standard Modbus TCP).
4. Save and restart the adapter.

#### Home Assistant side

During setup, select **Local Modbus TCP (RS485 adapter)**, then enter the
adapter's IP (e.g. `192.168.1.100`), port `502`, unit ID `1` (default for most
inverters), your inverter's serial number, and inverter family.

### Serial Modbus (USB/RS485)

Connect directly to your inverter using a USB-to-RS485 adapter (FTDI, CH340, or
CP2102-based) plugged into the host running Home Assistant — no network adapter
needed. Wire the RS485 cable to the inverter's Modbus port using the same wiring
as the Waveshare setup above.

During setup, select **Local Device → Serial (USB/RS485)**, choose your serial
port from the dropdown (RS485 adapters are prioritized) or enter a path
manually, and the integration auto-discovers the model and serial number.

> **Docker/HAOS:** you may need to pass the USB device through to your container.
> For Docker, add `--device /dev/ttyUSB0:/dev/ttyUSB0` to your run command. For
> HAOS, USB devices are typically auto-detected.

### WiFi dongle

If your inverter has a WiFi dongle on your local network, connect directly to it
on port 8000. You need the dongle's serial number (on its sticker).

> Some newer dongle firmware versions block port 8000 for security. If the
> connection fails, use the Modbus or Cloud API method instead.

### Hybrid

Combines local polling (Modbus, dongle, or serial) for fast sensor updates with
the Cloud API for cloud-only features. Best for users who want fast local
updates and also need DST auto-sync and quick charge control. Battery data is
available via all local connection types — cloud is not required for battery
monitoring.

## Adding the Integration

1. Go to **Settings → Devices & Services** → **Add Integration**.
2. Search for **EG4 Web Monitor** and select it.
3. Choose a starting point:
   - **Cloud (HTTP):** enter your EG4 Monitor credentials (username, password,
     base URL), select your station, and optionally add a local device to create
     a hybrid connection.
   - **Local Device:** choose Modbus TCP, WiFi Dongle, or Serial; enter the
     connection details. The model and serial number are auto-detected.

## Reconfiguration

To change settings, open **Settings → Devices & Services**, find **EG4 Web
Monitor**, click the **⋮** menu → **Reconfigure**, and choose:

- **Update Cloud Credentials** — change username, password, base URL, or station.
- **Add Local Device** — add a Modbus, dongle, or serial connection (upgrades
  HTTP → Hybrid).
- **Remove Local Device** — remove a local transport.
- **Detach Cloud** — switch from Hybrid to Local-only mode.

Existing automations and dashboards are preserved.

> **Changing stations:** if you switch to a different station/plant, entity IDs
> change to reflect the new station's devices. Automations and dashboard cards
> referencing the old IDs need updating, and history from the old station stays
> but is no longer connected to the new entities. Changing only credentials for
> the same station leaves entity IDs unchanged.

## Configuration Options (Refresh Intervals)

After setup, click **Configure** on the integration to customize:

- **Sensor Update Interval** — how often to poll sensor data (5–300 seconds).
  Default: 5 seconds for local connections, 30 seconds for HTTP.
- **Parameter Refresh Interval** — how often to sync configuration settings
  (5–1440 minutes). Default: 60 minutes.

> Lower sensor intervals give faster updates but increase network/API load. For
> local connections, 5 seconds is recommended; for the cloud API, 30 seconds
> balances responsiveness with server load.

If you change settings directly on the EG4 website (not through Home Assistant),
parameter data such as working-mode switches may take up to the parameter
refresh interval to update. Press the refresh-data button to force an immediate
parameter sync.

## Entities and Controls

### Switches

- **Quick Charge** — start/stop battery quick charging (Cloud API / Hybrid only,
  as it is a cloud-scheduled task).
- **Battery Backup (EPS)** — enable/disable emergency power supply mode.
- **Daylight Saving Time** — enable/disable DST for station time sync.
- **Working modes** — AC Charge, PV Charge Priority, Forced Discharge, Peak
  Shaving, Battery Backup Control.
  > **EG4 Off-Grid family (12000XP/6000XP):** the **Forced Discharge** and
  > **Peak Shaving** switches are not created — these grid-parallel functions
  > are inert on the no-sellback SNA platform (PR #220 / #197 adjudication).
  > If you had them from an earlier version, a Repairs issue explains the
  > removal.

### Selects

- **Operating Mode** — Normal or Standby.
- **GridBOSS Smart Port Mode (1–4)** — Off, Smart Load, or AC Couple per port.
- **Battery Charge Control** / **Battery Discharge Control** — regulate the battery
  by **SOC** (closed-loop, default) or **Voltage** (open-loop). See
  [Battery control mode](#battery-control-mode-soc-vs-voltage) below.

### Numbers

- System Charge SOC Limit (%)
- AC Charge SOC Limit (%), On-Grid SOC Cut-Off (%), Off-Grid SOC Cut-Off (%)
- System Charge Voltage Limit (V), AC Charge Start / End Voltage (V),
  On-Grid / Off-Grid Cut-Off Voltage (V) — voltage-mode limits (see below)
- AC Charge Power (0.1 kW increments)
- PV Charge Power
- PV Start Voltage threshold
- Grid Peak Shaving Power (not on the EG4 Off-Grid family — see the working
  modes note above)
- Forced Discharge Power (kW) and Forced Discharge SOC Limit (%) (not on the
  EG4 Off-Grid family)
- Battery Charge Current
- Battery Discharge Current

### Battery control mode (SOC vs Voltage)

Two selects — **Battery Charge Control** and **Battery Discharge Control** — set how
the inverter regulates the battery: by **State of Charge** (closed-loop, the default
and existing behavior) or by **Voltage** (open-loop, for lead-acid or no-BMS packs).
They mirror the inverter's own setting (register 179, bit 9 = charge, bit 10 =
discharge; `0` = SOC, `1` = Voltage), so **changing a select writes to the inverter**
— and the inverter propagates the change to every unit in a parallel group.

To reduce clutter, the limit entities for the **active** mode are enabled by default
and the other mode's limits are created but disabled. (Changing a select only sets
this initial default; Home Assistant keeps any manual enable/disable you make, so
enable any disabled limit yourself if you want it.)

Some EG4 web UI labels differ from the Home Assistant entity names — match them here
(or by the **EG4 param key**, shown on the EG4 cloud *Parameter Read* page):

| EG4 web UI label | Home Assistant entity | Reg | EG4 param key | Enabled by default when |
|---|---|---|---|---|
| — | **Battery Charge Control** (select) | 179·b9 | `FUNC_BAT_CHARGE_CONTROL` | always |
| — | **Battery Discharge Control** (select) | 179·b10 | `FUNC_BAT_DISCHARGE_CONTROL` | always |
| **System Charge Volt Limit(V)** | System Charge Voltage Limit | 228 | `HOLD_SYSTEM_CHARGE_VOLT_LIMIT` | Charge = Voltage |
| **Back Up Volt(V)** | AC Charge End Voltage | 159 | `HOLD_AC_CHARGE_END_BATTERY_VOLTAGE` | Charge = Voltage |
| — | AC Charge Start Voltage | 158 | `HOLD_AC_CHARGE_START_BATTERY_VOLTAGE` | Charge = Voltage |
| — | System Charge SOC Limit | 227 | `HOLD_SYSTEM_CHARGE_SOC_LIMIT` | Charge = SOC |
| — | AC Charge SOC Limit | 67 | `HOLD_AC_CHARGE_SOC_LIMIT` | Charge = SOC |
| — | On-Grid Cut-Off Voltage | 169 | `HOLD_ON_GRID_EOD_VOLTAGE` | Discharge = Voltage |
| — | Off-Grid Cut-Off Voltage | 100 | `HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT` | Discharge = Voltage |
| — | On-Grid SOC Cut-Off | 105 | `HOLD_DISCHG_CUT_OFF_SOC_EOD` | Discharge = SOC |
| — | Off-Grid SOC Cut-Off | 125 | `HOLD_SOC_LOW_LIMIT_EPS_DISCHG` | Discharge = SOC |

> EG4 web UI labels are filled in where confirmed; **—** means the exact EG4 wording
> isn't mapped yet — cross-reference by param key or register. To contribute a
> confirmed label, open an issue or PR.

**Periodic balancing (Voltage mode):** set **Battery Charge Control** to *Voltage*,
then raise **System Charge Voltage Limit** (the absorption/balance target) and
**AC Charge End Voltage** — EG4's *"Back Up Volt(V)"*, the battery voltage at which
grid/AC charging stops. Both are writable and automatable from Home Assistant.

### Buttons

- **Refresh Data** — force a refresh for devices and batteries.

### Service action: `eg4_web_monitor.refresh_data`

Force an immediate refresh of device data, bypassing the normal polling interval.

| Parameter | Type | Description |
|---|---|---|
| `entry_id` | string (optional) | The config entry to refresh. If omitted, all EG4 Web Monitor integrations refresh. |

```yaml
service: eg4_web_monitor.refresh_data
data:
  entry_id: "abc123def456"
```

### Example entity IDs

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
switch.eg4_station_daylight_saving_time
```

> The integration only creates entities for features your equipment actually has,
> so some sensors (generators, unused GridBOSS ports, battery-specific sensors)
> may not appear. This is expected.

For the complete register-to-sensor and API-to-sensor mapping, see
[DATA_MAPPING.md](DATA_MAPPING.md).
