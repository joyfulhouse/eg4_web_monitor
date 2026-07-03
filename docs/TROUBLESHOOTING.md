# Troubleshooting

Common problems with EG4 Web Monitor and how to resolve them.

## Common Issues

### "Cannot connect to EG4 Web Monitor"

**Possible causes:** internet down, EG4 servers temporarily unavailable, or a
firewall blocking `monitor.eg4electronics.com`.

**Fixes:**

1. Check your internet connection.
2. Try opening [monitor.eg4electronics.com](https://monitor.eg4electronics.com)
   in a browser.
3. Confirm your firewall allows HTTPS to EG4's servers.
4. Wait a few minutes — the integration retries automatically.

### "Invalid username or password"

1. Verify your credentials in the EG4 Monitor app or website.
2. Log out and back in to the EG4 Monitor app.
3. Check for extra spaces in your username or password.
4. If you recently changed your password, use **Reconfigure** to update it.

### "No solar stations/plants found"

**Possible causes:** the account has no stations configured yet, or stations have
not finished syncing to the EG4 cloud.

**Fixes:**

1. Confirm the station is visible in the EG4 Monitor app.
2. Make sure your inverter is online and uploading data.
3. Wait 5–10 minutes for new stations to sync.
4. Contact EG4 support if stations never appear in the app.

### "Entities show as unavailable"

**Possible causes:** internet lost, EG4 API session expired, or the inverter is
offline.

**Fixes:**

1. Check Home Assistant's internet connection.
2. Wait 2–5 minutes — the integration reconnects automatically.
3. Confirm the inverter is online in the EG4 Monitor app.
4. Use the **Refresh Data** button to force a reconnection.
5. If the problem persists, reload the integration.

### "Some sensors are missing"

This is usually normal — the integration only creates sensors for features your
equipment supports. For example, GridBOSS sensors appear only with a GridBOSS
device, battery sensors only for connected banks, generator sensors only with a
generator, and smart-port sensors only for configured ports.

To verify, check which sensors appear in the EG4 Monitor app, confirm the
feature physically exists, and enable debug logging to inspect the data the API
returns.

### XP family (6000XP/12000XP) control notes

EG4's off-grid XP family runs different firmware from the hybrid
(FlexBOSS/18kPV/12kPV) line, and several controls behave differently there
(reported and portal-verified on a 12000XP v2, issue #289):

- **AC Charge Mode controls charging from the grid, not grid passthrough.**
  Turning the switch off stops the battery from charging off AC power; the
  inverter can still power your loads from the grid (bypass). There is no
  switch that cuts grid passthrough — that is inherent to the XP topology.
- **Off Grid Mode may self-revert.** XP v2 firmware accepts the write and
  then clears the bit again within about 10 seconds (vendor behavior — the
  EG4 portal does not offer this toggle for XP v2 either). The switch in
  Home Assistant reflects the device's real state after the next refresh,
  so it turning itself off means the firmware rejected the mode, not that
  the write failed.
- **Battery backup switches are hidden on this family.** The **EPS Battery
  Backup** and **Battery Backup Mode** switches are not created for XP
  models: EG4's own portal exposes no battery-backup/working-mode control
  for the family and the firmware rejects the write ("failed to enable
  working mode"). XP units power their backup loads natively, so there is
  nothing for these switches to do. The same applies to the grid-tied-only
  controls (Peak Shaving, Forced Discharge, Grid Sell Back, Export PV Only,
  Fast Zero Export), which act on grid-parallel export the XP hardware
  doesn't perform.
- **Charge Last sticks but may have no visible effect** on XP firmware; it
  flips PV surplus priority, which mostly matters on exporting (grid-tied)
  systems.

### Local mode connectivity

If a Modbus, serial, or WiFi dongle connection fails, double-check wiring and
adapter settings (see [CONFIGURATION.md](CONFIGURATION.md)). Some newer WiFi
dongle firmware blocks port 8000 — fall back to Modbus or Cloud API. For maximum
reliability, use **Local Modbus TCP** with a Waveshare RS485 adapter: fastest
updates (5 seconds) and fully offline.

## Frequently Asked Questions

**How often does data update?** Cloud API: 30s; local Modbus/dongle/serial: 5s;
hybrid: 5s for sensors with cloud API for battery details. Intervals are
configurable in the integration options (5–300s for sensors).

**Can I monitor multiple installations?** Yes — add the integration once per
station and select a different station each time.

**Will it work if my internet goes down?** Cloud API: no. Local Modbus/serial/WiFi
dongle: yes. Hybrid: sensor and battery data work locally, but cloud features
(DST sync, quick charge) need internet.

**Does it control my inverter?** Yes, for supported features: quick charge (Cloud
API only), battery backup (EPS), operating mode, SOC limits, AC/PV charge power,
and charge/discharge currents. Cloud/Hybrid send commands through EG4's cloud
API; local modes write registers directly.

**Is it secure?** Yes — encrypted HTTPS to EG4's servers, credentials stored in
Home Assistant's encrypted storage, communication only with official EG4
endpoints, and SSL certificate verification by default.

**What if my EG4 password changes?** Home Assistant detects the auth failure and
prompts you to re-enter credentials through the UI — no need to delete and re-add
the integration.

## Enabling Debug Logging

Add the following to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.eg4_web_monitor: debug
```

Then check **Settings → System → Logs**.

## Getting Help

If you are still stuck, open an issue at
<https://github.com/joyfulhouse/eg4_web_monitor/issues> with logs and
reproduction steps. Include your Home Assistant version, EG4 equipment model(s),
error messages, and the steps to reproduce.
