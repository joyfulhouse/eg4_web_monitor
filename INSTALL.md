# Installing EG4 Web Monitor

## Prerequisites

- Home Assistant 2026.1.0 or newer.
- [HACS](https://hacs.xyz) installed (recommended), or filesystem access to your
  Home Assistant `config` directory (for manual installation).
- At least one EG4 connection method: a cloud account on
  [monitor.eg4electronics.com](https://monitor.eg4electronics.com), a Modbus TCP
  RS485-to-Ethernet adapter, a USB-to-RS485 serial adapter, or a WiFi dongle.

## Method 1 — HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Click the **⋮** menu → **Custom repositories**.
3. Add `https://github.com/joyfulhouse/eg4_web_monitor` with category
   **Integration**.
4. Search for **EG4 Web Monitor** and click **Download**.
5. **Restart Home Assistant.**

Or use this one-click link:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=joyfulhouse&repository=eg4_web_monitor&category=integration)

## Method 2 — Manual installation

1. Download the latest release from the
   [releases page](https://github.com/joyfulhouse/eg4_web_monitor/releases).
2. Copy the `custom_components/eg4_web_monitor` folder into your Home Assistant
   `config/custom_components/` directory. The result should be
   `config/custom_components/eg4_web_monitor/`.

   > The repository contains a `custom_components/eg4_web_monitor/` subdirectory.
   > Copy that inner directory into your `custom_components` folder, not the
   > entire repository.

3. **Restart Home Assistant.**

## Adding the Integration

1. Go to **Settings → Devices & Services**.
2. Click **+ Add Integration**.
3. Search for **EG4 Web Monitor** and select it.
4. Choose a starting point and follow the configuration flow:
   - **Cloud (HTTP):** enter your EG4 Monitor credentials and select a station.
     You can optionally add a local device to create a hybrid connection.
   - **Local Device:** pick Modbus TCP, WiFi Dongle, or Serial (USB/RS485) and
     enter the connection details. The model and serial number are auto-detected.

The connection type is derived automatically: cloud-only → HTTP, local-only →
Local, both → Hybrid. For RS485 wiring, Waveshare adapter settings, serial and
WiFi dongle setup, and options such as refresh intervals, see
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

> **Docker/HAOS and serial:** for a USB-to-RS485 adapter you may need to pass the
> USB device through to your container. For Docker, add
> `--device /dev/ttyUSB0:/dev/ttyUSB0` to your run command. For HAOS, USB devices
> are typically auto-detected.

## Verifying

After setup, the integration's devices and entities appear under
**Settings → Devices & Services → EG4 Web Monitor**.

## Updating

- **HACS:** update from the HACS dashboard when a new version is available, then
  restart Home Assistant.
- **Manual:** replace the `custom_components/eg4_web_monitor` folder with the new
  release and restart.

## Troubleshooting

If the integration does not appear or fails to set up, see the
[Troubleshooting guide](docs/TROUBLESHOOTING.md) and enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.eg4_web_monitor: debug
```
