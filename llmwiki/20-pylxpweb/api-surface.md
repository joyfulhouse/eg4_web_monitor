---
canonical-for: pylxpweb public client, device-factory, and transport-factory seams
sources:
  - pylxpweb@204b95d:src/pylxpweb/client.py
  - pylxpweb@204b95d:src/pylxpweb/api_namespace.py
  - pylxpweb@204b95d:src/pylxpweb/devices/
  - pylxpweb@204b95d:src/pylxpweb/transports/
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# API surface

Evidence grades follow the [canonical llmwiki legend](../README.md); this chapter does not redefine them.

## Recommended entry point

| Rule | Evidence |
|---|---|
| Construct `LuxpowerClient`, enter it asynchronously or close it explicitly, then use `client.api.<namespace>`. | `verified-against-code` — `src/pylxpweb/client.py:181-236`, `src/pylxpweb/client.py:238-267` |
| `client.api.plants`, `.devices`, `.control`, `.analytics`, `.forecasting`, `.export`, and `.firmware` are lazy endpoint namespaces. | `verified-against-code` — `src/pylxpweb/api_namespace.py:51-240` |
| New code should use `client.api.*`. Bare `client.plants`, `.devices`, `.control`, `.analytics`, `.forecasting`, `.export`, and `.firmware` remain compatibility aliases; they are labeled deprecated in comments but emit no runtime warning. | `verified-against-code` — `src/pylxpweb/client.py:238-318` |
| Do not infer an endpoint method from namespace examples or prose. Some examples are stale; inspect the endpoint implementation before calling a method not listed here. | `verified-against-code` — `src/pylxpweb/api_namespace.py:133-138`, `src/pylxpweb/api_namespace.py:159-163`, `src/pylxpweb/api_namespace.py:207-211`, `src/pylxpweb/api_namespace.py:231-235` |

## `LuxpowerClient`

Exact constructor signature: `verified-against-code` — `src/pylxpweb/client.py:82-106`.

```python
LuxpowerClient(
    username: str,
    password: str,
    *,
    base_url: str = "https://monitor.eg4electronics.com",
    verify_ssl: bool = True,
    timeout: int = 30,
    session: aiohttp.ClientSession | None = None,
    iana_timezone: str | None = None,
) -> None
```

| Namespace | Endpoint class | Intended seam | Evidence |
|---|---|---|---|
| `client.api.plants` | `PlantEndpoints` | Plant list/detail/configuration, DST, and overviews | `verified-against-code` — `src/pylxpweb/api_namespace.py:68-90`, `src/pylxpweb/endpoints/plants.py:54-436` |
| `client.api.devices` | `DeviceEndpoints` | Device discovery, runtime, energy, batteries, MID/GridBOSS, dongles, and datalogs | `verified-against-code` — `src/pylxpweb/api_namespace.py:92-117`, `src/pylxpweb/endpoints/devices.py:44-532` |
| `client.api.control` | `ControlEndpoints` | Parameter, function, bitfield, schedule, quick-action, inverter, battery, and MID controls | `verified-against-code` — `src/pylxpweb/api_namespace.py:119-144`, `src/pylxpweb/endpoints/control.py:83-3581` |
| `client.api.analytics` | `AnalyticsEndpoints` | Charts, histories, events, and analytical reads | `verified-against-code` — `src/pylxpweb/api_namespace.py:146-169`, `src/pylxpweb/endpoints/analytics.py:54-522` |
| `client.api.forecasting` | `ForecastingEndpoints` | Solar and weather forecasts | `verified-against-code` — `src/pylxpweb/api_namespace.py:171-193`, `src/pylxpweb/endpoints/forecasting.py:29-67` |
| `client.api.export` | `ExportEndpoints` | Binary spreadsheet export and parsing | `verified-against-code` — `src/pylxpweb/api_namespace.py:195-217`, `src/pylxpweb/endpoints/export.py:25-231` |
| `client.api.firmware` | `FirmwareEndpoints` | Firmware check, status, eligibility, and start calls | `verified-against-code` — `src/pylxpweb/api_namespace.py:219-240`, `src/pylxpweb/endpoints/firmware.py:36-268` |

## High-level device factories

The signatures below are the supported construction seam; retain the keyword-only markers and async boundaries. `verified-against-code` — `src/pylxpweb/devices/station.py:553-665`, `src/pylxpweb/devices/station.py:1286-1300`, `src/pylxpweb/devices/inverters/base.py:335-409`, `src/pylxpweb/devices/inverters/base.py:586-620`, `src/pylxpweb/devices/mid_device.py:115-120`.

```python
async Station.load(
    client: LuxpowerClient,
    plant_id: int,
) -> Station

async Station.load_all(
    client: LuxpowerClient,
) -> list[Station]

async Station.from_local_discovery(
    configs: list[TransportConfig],
    *,
    station_name: str = "Local Station",
    plant_id: int = 0,
    timezone_str: str = "UTC",
) -> Station

async station.attach_local_transports(
    configs: list[TransportConfig],
) -> AttachResult

async BaseInverter.from_transport(
    transport_or_type: InverterTransport | str,
    *,
    model: str | None = None,
    **config: Any,
) -> BaseInverter

async BaseInverter.from_modbus_transport(
    transport: InverterTransport,
    model: str | None = None,
) -> BaseInverter

async BaseInverter.from_dongle_transport(
    transport: InverterTransport,
    model: str | None = None,
) -> BaseInverter

async MIDDevice.from_transport(
    transport: InverterTransport,
    model: str = "GridBOSS",
) -> MIDDevice
```

| Factory behavior | Evidence |
|---|---|
| `Station.load` builds the cloud hierarchy; `load_all` loads all returned plants concurrently. | `verified-against-code` — `src/pylxpweb/devices/station.py:553-632` |
| `Station.from_local_discovery` is asynchronous even though some older summaries omit `async`; it accepts transport configs and constructs a clientless local station. | `verified-against-code` — `src/pylxpweb/devices/station.py:634-665` |
| `attach_local_transports` attaches local transports to cloud-discovered devices and returns match/failure counts in `AttachResult`. | `verified-against-code` — `src/pylxpweb/devices/station.py:1286-1300`, `src/pylxpweb/transports/config.py:284-317` |
| `BaseInverter.from_transport` accepts an existing transport or one of the strings `"modbus"`, `"serial"`, `"dongle"`, or `"hybrid"`; it rejects other strings. | `verified-against-code` — `src/pylxpweb/devices/inverters/base.py:335-402` |
| `from_dongle_transport` is a compatibility alias that delegates to `from_modbus_transport`; both accept any `InverterTransport`. | `verified-against-code` — `src/pylxpweb/devices/inverters/base.py:586-620` |
| A transport-created `MIDDevice` has no cloud client. Do not call cloud-only firmware or MID controls on it. | `verified-against-code` — `src/pylxpweb/devices/mid_device.py:115-188`, `src/pylxpweb/devices/mid_device.py:356-490` |

## Transport factories

`ConnectionType` is `Literal["http", "modbus", "serial", "dongle", "hybrid"]`. The unified factory is recommended; the named convenience factories remain public and supported. `verified-against-code` — `src/pylxpweb/transports/factory.py:54-137`, `src/pylxpweb/transports/__init__.py:80-121`.

```python
create_transport(
    connection_type: ConnectionType,
    **config: Any,
) -> InverterTransport

create_http_transport(
    client: LuxpowerClient,
    serial: str,
) -> HTTPTransport

create_modbus_transport(
    host: str,
    serial: str,
    *,
    port: int = 502,
    unit_id: int = 1,
    timeout: float = 10.0,
    inverter_family: InverterFamily | None = None,
    max_input_block_size: int = 40,
) -> ModbusTransport

create_dongle_transport(
    host: str,
    dongle_serial: str,
    inverter_serial: str,
    *,
    port: int = 8000,
    timeout: float = 10.0,
    inverter_family: InverterFamily | None = None,
    max_input_block_size: int = 40,
) -> DongleTransport

create_serial_transport(
    port: str,
    serial: str,
    *,
    baudrate: int = 19200,
    parity: str = "N",
    stopbits: int = 1,
    unit_id: int = 1,
    timeout: float = 10.0,
    inverter_family: InverterFamily | None = None,
    max_input_block_size: int = 40,
) -> ModbusSerialTransport

create_transport_from_config(
    config: TransportConfig,
) -> BaseTransport
```

Exact convenience-factory definitions: `verified-against-code` — `src/pylxpweb/transports/factory.py:329-581`; the default block size is `40`: `verified-against-code` — `src/pylxpweb/transports/_register_data.py:136-145`.

The `create_transport` overloads require these keys. `verified-against-code` — `src/pylxpweb/transports/factory.py:63-137`.

| `connection_type` | Required configuration | Optional configuration | Evidence |
|---|---|---|---|
| `http` | `client`, `serial` | none | `verified-against-code` — `src/pylxpweb/transports/factory.py:63-69` |
| `modbus` | `host`, `serial` | `port`, `unit_id`, `timeout`, `inverter_family`, `max_input_block_size` | `verified-against-code` — `src/pylxpweb/transports/factory.py:72-83` |
| `serial` | `port`, `serial` | `baudrate`, `parity`, `stopbits`, `unit_id`, `timeout`, `inverter_family`, `max_input_block_size` | `verified-against-code` — `src/pylxpweb/transports/factory.py:86-99` |
| `dongle` | `host`, `dongle_serial`, `inverter_serial` | `port`, `timeout`, `inverter_family`, `max_input_block_size` | `verified-against-code` — `src/pylxpweb/transports/factory.py:102-113` |
| `hybrid` | `client`, `serial`, `local_host` | `local_type`, `local_port`, `dongle_serial`, `unit_id`, `timeout`, `inverter_family`, `local_retry_interval`, `max_input_block_size` | `verified-against-code` — `src/pylxpweb/transports/factory.py:116-131` |

## Common transport contract

`InverterTransport` is runtime-checkable. Implementations must provide the following exact protocol surface. `verified-against-code` — `src/pylxpweb/transports/protocol.py:70-238`.

```python
serial: str                       # read-only property
is_connected: bool                # read-only property
capabilities: TransportCapabilities  # read-only property

async connect() -> None
async disconnect() -> None
async read_runtime() -> InverterRuntimeData
async read_energy() -> InverterEnergyData
async read_battery() -> BatteryBankData | None
async read_parameters(
    start_address: int,
    count: int,
) -> dict[int, int]
async write_parameters(
    parameters: dict[int, int],
) -> bool
async read_named_parameters(
    start_address: int,
    count: int,
) -> dict[str, Any]
async write_named_parameters(
    parameters: dict[str, Any],
) -> bool
```

| Contract boundary | Evidence |
|---|---|
| `BaseTransport` adds async context management: `__aenter__()` connects and `__aexit__(...)` disconnects. Context management is a base-class facility, not a declared `InverterTransport` protocol member. | `verified-against-code` — `src/pylxpweb/transports/protocol.py:241-288` |
| Specialist methods such as `read_all_input_data()` and `read_midbox_runtime()` are concrete extensions, not guaranteed by `InverterTransport`. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:1398-1536`, `src/pylxpweb/devices/inverters/base.py:1110-1116` |
| Use normalized return dataclasses and typed transport exceptions; do not depend on leading-underscore framing, reader, or coalescing helpers. | `verified-against-code` — `src/pylxpweb/transports/__init__.py:112-165`, `src/pylxpweb/transports/exceptions.py:1-80` |
