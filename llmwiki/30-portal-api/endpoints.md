---
canonical-for:
  - EG4 portal endpoint inventory
  - EG4 portal object and identifier model
  - OpenAPI coverage boundaries
sources:
  - docs/api/openapi.yaml
  - docs/api/README.md
  - docs/api/PORTAL_ENDPOINTS.md
  - docs/reference/firmware/FIRMWARE_ACQUISITION.md
  - scripts/download_inverter_firmware.py
  - joyfulhouse/pylxpweb/src/pylxpweb/endpoints/
  - joyfulhouse/pylxpweb/src/pylxpweb/models.py
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-08
---

# Portal endpoint reference

## Coverage boundary

| Inventory | Count | Meaning | Evidence |
|---|---:|---|---|
| `docs/api/openapi.yaml` paths | **44** | Deliberate pylxpweb-called subset, not the complete portal. | `verified-against-code` `docs/api/openapi.yaml:7-13`; machine count of `paths` |
| OpenAPI component schemas | **64** | Reusable request/response definitions in the current spec. | `verified-against-code` `docs/api/openapi.yaml` `components.schemas`; machine count |
| Spec paths with live pylxpweb call sites | **44** | Every specified path is used; there are **zero unused spec paths**. | `verified-against-code` exhaustive comparison of OpenAPI `paths` with `pylxpweb/src/pylxpweb/endpoints/*.py` |
| Routes referenced elsewhere but absent from the spec | **7** | Two script-used API routes, two documented but uncalled API routes, two HTML pages, and one API route on another host. | `verified-against-code` repository string inventory summarized below |
| `PORTAL_ENDPOINTS.md` catalog | **251** | Broader authenticated-frontend discovery map; the OpenAPI subset is intentionally much smaller. | `asserted-unverified` `docs/api/PORTAL_ENDPOINTS.md:9-12,429`; deliberate OpenAPI scope `verified-against-code` `docs/api/openapi.yaml:7-13` |

Unless a row says otherwise, paths are relative to `https://monitor.eg4electronics.com`, use form-encoded POST, and return JSON. `verified-against-code` `docs/api/openapi.yaml:23-30,48-50`; `pylxpweb/src/pylxpweb/client.py:603-624`

## The 44 specified paths

### Authentication and plants

| # | Path | Request → result | pylxpweb call site | Evidence |
|---:|---|---|---|---|
| 1 | `POST /WManage/api/login` | `account`, `password`, `language=ENGLISH` → session cookie plus `LoginResponse` with `userId`, `role`, and eager topology | `LuxpowerClient.login()` | `verified-against-code` OpenAPI path; `client.py:818-839` |
| 2 | `POST /WManage/web/config/plant/list/viewer` | paging/search, optionally `targetPlantId` → viewer/admin plant rows | `PlantsEndpoints.get_plants()`, `get_plant_details()` | `verified-against-code` OpenAPI path; `endpoints/plants.py:30,90,133` |
| 3 | `POST /WManage/web/config/plant/list` | same shape → installer/I-assistant plant rows | role-selected variants of the same methods | `verified-against-code` OpenAPI path; `endpoints/plants.py:29,50-52` |
| 4 | `POST /WManage/web/config/plant/edit` | full plant record including `plantId`, timezone/country enums and `daylightSavingTime` → success envelope | `update_plant_config()`, `set_daylight_saving_time()` | `verified-against-code` OpenAPI path; `endpoints/plants.py:310-396` |
| 5 | `POST /WManage/locale/region` | `continent` enum → `[{value,text}]` regions | `_fetch_country_location_from_api()` | `verified-against-code` OpenAPI path; `endpoints/plants.py:181` |
| 6 | `POST /WManage/locale/country` | `region` enum → `[{value,text}]` countries | `_fetch_country_location_from_api()` | `verified-against-code` OpenAPI path; `endpoints/plants.py:195` |
| 7 | `POST /WManage/api/plantOverview/list/viewer` | `searchText` → aggregate plant metrics and nested inverters | `get_plant_overview()` | `verified-against-code` OpenAPI path; `endpoints/plants.py:423` |

The locale calls are real call sites but bypass the normal request helper: they have no shared caching, backoff, reauthentication, or `success:false` handling, and they silently continue on non-200. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/plants.py:150-221`

### Discovery, hierarchy, runtime, energy and batteries

| # | Path | Request → result | pylxpweb call site | Evidence |
|---:|---|---|---|---|
| 8 | `POST /WManage/api/inverterOverview/list` | `plantId`, paging/search/status → devices in the plant | `devices.get_devices()`; `plants.get_inverter_overview()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:145`; `endpoints/plants.py:476` |
| 9 | `POST /WManage/api/inverterOverview/getParallelGroupDetails` | device `serialNum` → group devices and roles | `get_parallel_group_details()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:47-69` |
| 10 | `POST /WManage/api/inverter/autoParallel` | `plantId` → request group re-detection | `sync_parallel_groups()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:110` |
| 11 | `POST /WManage/api/inverter/getInverterInfo` | inverter `serialNum` → static config, firmware, datalog SN and ratings | `devices.get_inverter_info()`; `analytics.get_inverter_info()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:178`; `endpoints/analytics.py:561` |
| 12 | `POST /WManage/api/inverter/getInverterRuntime` | inverter `serialNum` → raw realtime inverter metrics | `get_inverter_runtime()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:213` |
| 13 | `POST /WManage/api/inverter/getInverterEnergyInfo` | inverter `serialNum` → raw daily/lifetime energy totals | `get_inverter_energy()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:243` |
| 14 | `POST /WManage/api/inverter/getInverterEnergyInfoParallel` | any group member `serialNum` → group-aggregate energy | `get_parallel_energy()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:270` |
| 15 | `POST /WManage/api/battery/getBatteryInfo` | inverter `serialNum` → bank aggregate and `batteryArray[]` module data | `get_battery_info()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:302` |
| 16 | `POST /WManage/api/battery/getBatteryInfoForSet` | inverter `serialNum` → lightweight battery identities/status | `devices.get_battery_list()`; `analytics.get_battery_list()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:335`; `endpoints/analytics.py:514` |
| 17 | `POST /WManage/api/midbox/getMidboxRuntime` | GridBOSS/MID `serialNum` → `MidboxRuntime` with `midboxData` and primary `deviceData` | `get_midbox_runtime()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:366`; `models.py:1023-1035` |
| 18 | `POST /WManage/api/system/cluster/search/findOnlineDatalog` | **datalog** `serialNum` → derived online state | `get_dongle_status()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:407-411` |
| 19 | `POST /WManage/web/config/datalog/list` | `plantId` (`-1` for all), paging/search → dongles, `lost`, update time | `get_datalog_list()` | `verified-against-code` OpenAPI path; `endpoints/devices.py:431-461` |

Three paths intentionally have duplicate wrappers: inverter overview, inverter info, and battery-list-for-set. The duplication is in Python access paths, not on the wire. `verified-against-code` call sites in rows 8, 11 and 16

### Parameter and immediate controls

| # | Path | Request → result | pylxpweb call site | Evidence |
|---:|---|---|---|---|
| 20 | `POST /WManage/web/maintain/remoteRead/read` | `inverterSn`, `startRegister`, `pointNumber`, `autoRetry` → flat root-level `HOLD_*`/`FUNC_*` values | `read_parameters()` | `verified-against-code` OpenAPI path; `endpoints/control.py:145-157`; `models.py:1041-1057` |
| 21 | `POST /WManage/web/maintain/remoteSet/write` | `inverterSn`, `holdParam`, pre-scaled `valueText`, client/type fields → success envelope | `write_parameter()` | `verified-against-code` OpenAPI path; `endpoints/control.py:200-217` |
| 22 | `POST /WManage/web/maintain/remoteSet/writeTime` | `inverterSn`, `timeParam`, `hour`, `minute`, client/type fields → one atomic boundary write | `write_time_parameter()` | `verified-against-code` OpenAPI path; `endpoints/control.py:230-280` |
| 23 | `POST /WManage/web/maintain/remoteSet/functionControl` | `functionParam`, lower-case `enable` → one boolean function bit | `control_function()` | `verified-against-code` OpenAPI path; `endpoints/control.py:441-502` |
| 24 | `POST /WManage/web/maintain/remoteSet/bitParamControl` | `bitParam`, multi-valued `value` → GridBOSS smart-port mode | `control_bit_param()` | `verified-against-code` OpenAPI path; `endpoints/control.py:504-562` |
| 25 | `POST /WManage/web/config/quickCharge/start` | inverter SN, client type, optional positive `minute` → start | `start_quick_charge()` | `verified-against-code` OpenAPI path; `endpoints/control.py:564-615` |
| 26 | `POST /WManage/web/config/quickCharge/stop` | inverter SN and client type → stop | `stop_quick_charge()` | `verified-against-code` OpenAPI path; `endpoints/control.py:617-648` |
| 27 | `POST /WManage/web/config/quickCharge/getStatusInfo` | inverter SN → task flags/status; `quickChargeMinute` represents raw holding register 234 | `get_quick_charge_status()` | `verified-against-code` OpenAPI path; `endpoints/control.py:650-681`; `models.py:1079-1114` |
| 28 | `POST /WManage/web/config/quickDischarge/start` | inverter SN and client type → start | `start_quick_discharge()` | `verified-against-code` OpenAPI path; `endpoints/control.py:683-709` |
| 29 | `POST /WManage/web/config/quickDischarge/stop` | inverter SN and client type → stop | `stop_quick_discharge()` | `verified-against-code` OpenAPI path; `endpoints/control.py:711-733` |

### Firmware

| # | Path | Request → result | pylxpweb call site | Evidence |
|---:|---|---|---|---|
| 30 | `POST /WManage/web/maintain/standardUpdate/checkUpdates` | `serialNum` → component/version/update-chain details | `check_firmware_updates()` | `verified-against-code` OpenAPI path; `endpoints/firmware.py:91` |
| 31 | `POST /WManage/web/maintain/standardUpdate/check12KParallelStatus` | `userId`, `serialNum` → eligibility | `check_update_eligibility()` | `verified-against-code` OpenAPI path; `endpoints/firmware.py:154-193` |
| 32 | `POST /WManage/web/maintain/standardUpdate/run` | `userId`, `serialNum`, lower-case `tryFastMode` → begin update | `start_firmware_update()` | `verified-against-code` OpenAPI path; `endpoints/firmware.py:252-264` |
| 33 | `POST /WManage/web/maintain/remoteUpdate/info` | account `userId` → status rows for all account devices | `get_firmware_update_status()` | `verified-against-code` OpenAPI path; `endpoints/firmware.py:140-148` |

`check12KParallelStatus` is used for all device families despite its name, and `remoteUpdate/info` is account-scoped rather than serial-scoped. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/firmware.py:140-159`

Firmware start is a destructive, long-running operation; this knowledge-base work did not invoke it. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/firmware.py:202-214`

### Analytics, forecasting and export

| # | Path | Request → result | pylxpweb call site | Evidence |
|---:|---|---|---|---|
| 34 | `POST /WManage/api/analyze/chart/dayLine` | `serialNum`, free-form `attr`, date → raw hourly points | `get_chart_data()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:99` |
| 35 | `POST /WManage/api/analyze/energy/dayColumn` | SN, parallel flag, date, free-form `energyType` → hourly energy series | `get_energy_day_breakdown()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:162` |
| 36 | `POST /WManage/api/analyze/energy/monthColumn` | SN, parallel flag, year/month, energy type → monthly series | `get_energy_month_breakdown()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:214` |
| 37 | `POST /WManage/api/analyze/energy/yearColumn` | SN, parallel flag, year, energy type → yearly series | `get_energy_year_breakdown()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:339` |
| 38 | `POST /WManage/api/analyze/energy/totalColumn` | SN, parallel flag, energy type → lifetime series | `get_energy_total_breakdown()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:383` |
| 39 | `POST /WManage/api/inverterChart/monthColumn` | SN, year, month → typed daily-energy history for one inverter | `get_month_daily_energy(parallel=False)` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:260-262` |
| 40 | `POST /WManage/api/inverterChart/monthColumnParallel` | SN, year, month → typed daily-energy history for its group | `get_month_daily_energy(parallel=True)` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:260-262` |
| 41 | `POST /WManage/api/analyze/event/list` | paging, `plantId=-1` for all, optional SN, `_all` or event code → event rows | `get_event_list()` | `verified-against-code` OpenAPI path; `endpoints/analytics.py:456-475` |
| 42 | `POST /WManage/api/predict/solar/dayPredictColumnParallel` | `serialNum` → solar forecast | `get_solar_forecast()` | `verified-against-code` OpenAPI path; `endpoints/forecasting.py:61` |
| 43 | `POST /WManage/api/weather/forecast` | `serialNum` → weather plus plant latitude/longitude | `get_weather_forecast()` | `verified-against-code` OpenAPI path; `endpoints/forecasting.py:105` |
| 44 | `GET /WManage/web/analyze/data/export/{serialNum}/{startDate}` | optional `endDateText` query → binary `.xls` | `export_data()` | `verified-against-code` OpenAPI path; `endpoints/export.py:183-231` |

The forecasting shapes are intentionally provisional in the schema even though repository records say their bodies were live-validated on 2026-07-15. `portal-correlated` `docs/api/README.md:414-422`; OpenAPI forecasting paths

The export workbook is capped at ten day sheets and has firmware-dependent columns, so pylxpweb parses it by header rather than fixed column number. `portal-correlated` `docs/api/README.md:484-486`; `pylxpweb/src/pylxpweb/endpoints/export.py:186-231`

## Seven referenced routes outside the OpenAPI spec

“Absent” means absent from `docs/api/openapi.yaml`; it does not mean safe, stable, or publicly supported. `verified-against-code` comparison against OpenAPI `paths`

| Path | Category and known contract | Evidence grade |
|---|---|---|
| `POST /WManage/web/maintain/appLocalUpdate/listForAppByType` | Used by a repository firmware-download script. Form field: `firmwareDeviceType`; documented rows include `recordId`, filename/version fields, and `encryptedFirmware`. | Reference/call site `verified-against-code` `scripts/download_inverter_firmware.py:58`; response behavior `portal-correlated` `docs/reference/firmware/FIRMWARE_ACQUISITION.md:40-43` |
| `POST /WManage/web/maintain/appLocalUpdate/getUploadFileAnalyzeInfo` | Used by the same script. Form fields: `recordId`, **1-based** `startIndex`; documented result contains paged base64 chunks and metadata. | Reference/call site `verified-against-code` `scripts/download_inverter_firmware.py:59`; paging behavior `portal-correlated` `docs/reference/firmware/FIRMWARE_ACQUISITION.md:44-66` |
| `POST /WManage/web/maintain/remoteWeeklyOperation/readValues` | Documented future weekly-schedule read for registers 500-723; no pylxpweb call site. | String/reference `verified-against-code` `pylxpweb/src/pylxpweb/registers/scheduling.py:1-29`; portal availability `asserted-unverified` |
| `POST /WManage/web/maintain/remoteWeeklyOperation/setValues` | Documented future weekly-schedule write; no pylxpweb call site. | String/reference `verified-against-code` `pylxpweb/src/pylxpweb/registers/scheduling.py:1-29`; portal availability `asserted-unverified` |
| `/WManage/web/maintain/workingMode/sna` | Portal HTML page, not a JSON API; used as provenance for some `HOLD_AC_FIRST_*` names. | Reference `verified-against-code` `pylxpweb/src/pylxpweb/constants/registers.py:97`; page behavior `asserted-unverified` |
| `/WManage/web/config/plant/edit/{plant_id}` | Portal HTML edit page linked by a Home Assistant Repair for manual DST work; distinct from the form POST path without the ID suffix. | Reference `verified-against-code` `pylxpweb/src/pylxpweb/constants/locations.py:8`; `custom_components/eg4_web_monitor/coordinator_mixins.py:4091`; page behavior `asserted-unverified` |
| `POST https://res.solarcloudsystem.com:8443/resource/findAllTypeInfo` | Different host; documented firmware release-note lookup by `firmwareDeviceType`. | Documentation `asserted-unverified` `docs/reference/firmware/FIRMWARE_ACQUISITION.md:83-85` |

The broader catalog states that it contains 251 paths observed in portal frontend assets; that discovery claim is not re-proven here. `asserted-unverified` (`docs/api/PORTAL_ENDPOINTS.md:9-12,429-441`) Do not promote a catalog entry into client code without request/response evidence. `inferred` from the OpenAPI call-site scope

## Object model

| Parent | Child | Cardinality represented by the API | Identity | Evidence |
|---|---|---:|---|---|
| Plant / station | Parallel group | `0..n` | `plantId` identifies the plant; groups carry a name such as `Parallel_A`. | `verified-against-code` login/OpenAPI schemas; `pylxpweb/src/pylxpweb/models.py:184-195` |
| Parallel group | MID / GridBOSS | `0..1` | `serialNum`; portal `deviceType=9`. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:371-381`; `constants/api.py:20-21` |
| Parallel group | Inverter | `1..n` | `serialNum`; portal `deviceType=6`. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:371-381`; `constants/api.py:20-21` |
| Inverter | Battery module | `0..n` | `batteryKey`, `batIndex`, and usually a positional `batterySn`. | `verified-against-code` OpenAPI schemas `BatteryInfo`, `BatteryModule`; `pylxpweb/src/pylxpweb/models.py:638-755` |

Login eagerly returns `plants[] -> inverters[]`, including `parallelGroups[]` when the device family supplies them, so topology is partially known before explicit discovery. `verified-against-code` OpenAPI schema `LoginResponse`; `pylxpweb/src/pylxpweb/models.py:184-238`

`parallelGroups` may be absent and defaults to an empty list, including on some 12000XP payloads. `portal-correlated` `pylxpweb/src/pylxpweb/models.py:187-195` and captured-login rationale in `docs/api/README.md`

## Identifier rules and traps

| Identifier | Wire type / meaning | Agent rule | Evidence |
|---|---|---|---|
| `plantId` | Integer in cloud JSON. | Home Assistant's selector submits a **string**; normalize at the UI/storage boundary. Do not assume matching Python types. | `verified-against-code` `pylxpweb/src/pylxpweb/models.py:123,190,277,399,1682`; `portal-correlated` `CHANGELOG.md:556` |
| `plantId=-1` | Sentinel meaning “all plants” for datalog and event list queries. | Preserve the sentinel; do not validate it as a real station ID. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/devices.py:431`; `endpoints/analytics.py:470` |
| `serialNum` | String. It may be alphanumeric, not just digits. | Do not apply a numeric-only regex. Synthetic format examples: numeric `1234567890`; alphanumeric `ABCDE12345` and `EXAMPLE001`. Each is exactly 10 characters; none identifies real hardware. | `portal-correlated` captured payload shapes documented in `docs/api/README.md`; `verified-against-code` `pylxpweb/src/pylxpweb/models.py` serial fields and absence of numeric-format validation |
| `getParallelGroupDetails.serialNum` | An inverter/MID device serial. | **Do not pass `plantId`** even though neighboring discovery calls use it. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/devices.py:47-69` |
| `findOnlineDatalog.serialNum` | Datalog/dongle serial, not inverter serial. | Obtain it from `getInverterInfo.datalogSn`. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/devices.py:407-411`; OpenAPI schema `InverterInfo` |
| `batteryKey` | Composite string `{inverterSerial}_{batterySn}`. | Use the returned key as identity; synthetic example: `ABCDE12345_Battery_ID_01`. | `portal-correlated` battery payload shape documented in `docs/api/README.md`; `verified-against-code` schema field at `docs/api/openapi.yaml:2574` |
| `batterySn` | Often a position label such as `Battery_ID_01`. | Do not assume it is a manufacturer-unique hardware serial. | `portal-correlated` `pylxpweb/samples/battery.json` |
| `deviceType` | Portal topology discriminator: 6 inverter, 9 MID/GridBOSS. | Do not confuse it with local Modbus register-19 `deviceTypeCode`; they are separate namespaces. | `verified-against-code` `pylxpweb/src/pylxpweb/constants/api.py:20-21`; `devices/discovery.py:52,87,121` |
| `userId` | Integer from login. | Required by firmware eligibility, start, and account-wide status calls. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/firmware.py:140-142,185-187,252-254` |

`MidboxRuntime` contains both a 108-field `midboxData` structure and `deviceData` for the primary inverter summary. The typed `MidboxDeviceData` model retains only `isOffGrid`; other wire keys in that nested object are discarded unless raw JSON is retained. `verified-against-code` `pylxpweb/src/pylxpweb/models.py:1012-1035`; `portal-correlated` `pylxpweb/samples/midbox_runtime.json`
