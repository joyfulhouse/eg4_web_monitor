# EG4 Monitor Cloud API — Reference

> **Unofficial / reverse-engineered.** This reference and the accompanying
> [`openapi.yaml`](./openapi.yaml) (OpenAPI 3.1.0) are derived entirely from the
> [`pylxpweb`](https://github.com/joyfulhouse/pylxpweb) client — its endpoint modules,
> Pydantic response models, and live read-only validation. It is **not** published or
> endorsed by EG4 Electronics and may drift from the real service. Base URL:
> `https://monitor.eg4electronics.com`.

## Overview

The EG4 monitor portal exposes a `/WManage/...` HTTP surface used by the web portal and
mobile app. `pylxpweb` wraps it; this integration (`eg4_web_monitor`) consumes
`pylxpweb`. Endpoints fall into these groups:

| Tag | What it covers |
|---|---|
| `auth` | Login / session establishment |
| `plants` | Plant/station discovery + config metadata |
| `devices` | Inverter discovery, parallel groups, static info, dongles |
| `runtime` | Real-time inverter metrics + energy totals |
| `battery` | Battery bank aggregate + per-module data |
| `gridboss` | GridBOSS / MID device runtime |
| `control` | Parameter read/write, function bits, quick charge/discharge, schedules |
| `firmware` | Multi-step firmware update flow |
| `analytics` | Charts, energy breakdowns, daily-energy history, event log |
| `forecasting` | Solar + weather forecasts (provisional) |
| `export` | Historical runtime `.xls` export |

## Auth & session model

1. `POST /WManage/api/login` with form fields `account`, `password`, `language=ENGLISH`.
2. On success the server sets a **`JSESSIONID` cookie**; every subsequent request reuses
   it (cookie jar). There is **no bearer token or API key**.
3. Sessions are treated as ~**2 hours** client-side. `pylxpweb` re-logs-in transparently
   when expired, and also recovers when a request returns HTTP 401 or an HTML login page
   instead of JSON (one re-auth + retry).
4. The login response's numeric **`userId`** is required by the firmware endpoints.
5. The login `role` (`VIEWER`/`INSTALLER`/`I_ASSISTANT`/`ADMIN`) **selects the plant-list
   endpoint**: installer-class roles use `/WManage/web/config/plant/list`, everyone else
   uses `/WManage/web/config/plant/list/viewer`.

## Request encoding & error convention

- **All request bodies are `application/x-www-form-urlencoded`** — never JSON — even for
  single-parameter calls. Most booleans are explicitly stringified to lower-case
  `"true"` / `"false"` (e.g. `enable`, `tryFastMode`, `parallel`), but a few are passed as
  raw Python bools that aiohttp encodes **capitalized** (`True` / `False`) — notably
  `autoRetry` (`remoteRead/read`) and `daylightSavingTime` (`plant/edit`).
- **All endpoints are HTTP POST returning JSON**, except the history **export which is a
  GET returning binary `.xls`**.
- **`success: false` inside an HTTP 200 body is the error signal** (not the HTTP status).
  The human reason is under `message` or `msg`.
- **Transient errors** whose message contains `DATAFRAME_TIMEOUT`, `TIMEOUT`, `BUSY`,
  `COMMUNICATION_ERROR`, or `DEVICE_BUSY` are retried (up to 3×) with exponential backoff
  (base 1s, factor 2, max 60s, +jitter). Non-transient errors fail immediately.
- **`deviceBusy` / `DEVICE_BUSY`** is the canonical "try again later" code. It can also
  appear as an HTTP-200 error-body signal on the firmware/eligibility path (see Gaps).
- **Hour-boundary cache invalidation:** the client clears its whole response cache on the
  first request after the wall-clock hour changes (protects daily-energy midnight
  rollover).

## Endpoint reference

Method / path / purpose / request → response model / client cache TTL.
(`SN` = `serialNum`; `iSN` = `inverterSn`. All POST unless noted.)

### auth
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/login` | Authenticate, set session cookie | `account,password,language` → `LoginResponse` | — |

### plants
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/web/config/plant/list/viewer` | List plants (viewer/admin); `targetPlantId`=detail | `PlantListRequest` → `PlantListResponse` | 30 s |
| `/WManage/web/config/plant/list` | List plants (installer roles) | `PlantListRequest` → `PlantListResponse` | 30 s |
| `/WManage/web/config/plant/edit` | **Write** plant config (name/DST/power); drives DST sync | `PlantEditRequest` → `SuccessResponse` | — |
| `/WManage/locale/region` | Locale lookup: regions for a continent (plant-edit slow path) | `continent` → provisional array | — |
| `/WManage/locale/country` | Locale lookup: countries for a region (plant-edit slow path) | `region` → provisional array | — |
| `/WManage/api/plantOverview/list/viewer` | Plant real-time overview | `searchText` → provisional dict | 30 s |

### devices
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/inverterOverview/list` | Device discovery / inverter overview | `page,rows,plantId,searchText,statusText` → `InverterOverviewResponse` | 15 min* |
| `/WManage/api/inverterOverview/getParallelGroupDetails` | Parallel-group hierarchy | `SN` → `ParallelGroupDetailsResponse` | 15 min |
| `/WManage/api/inverter/autoParallel` ⚠️WRITE | Sync parallel groups | `plantId` → `SuccessResponse` | — |
| `/WManage/api/inverter/getInverterInfo` | Static config + `datalogSn` | `SN` → `InverterInfo` | 15 min |
| `/WManage/api/system/cluster/search/findOnlineDatalog` | Single dongle online status | `SN`=datalog serial → `DongleStatus` | none |
| `/WManage/web/config/datalog/list` | All dongles + status | `page,rows,plantId,searchType,searchText` → `DatalogListResponse` | none |

\* `inverterOverview/list` is cached 15 min only when called as device discovery; the
general inverter-overview call is uncached.

### runtime
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/inverter/getInverterRuntime` | Real-time inverter metrics | `SN` → `InverterRuntime` | 20 s |
| `/WManage/api/inverter/getInverterEnergyInfo` | Single-inverter energy | `SN` → `EnergyInfo` | 20 s |
| `/WManage/api/inverter/getInverterEnergyInfoParallel` | Group aggregate energy | `SN` (any member) → `EnergyInfo` | 20 s |

### battery
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/battery/getBatteryInfo` | Aggregate + per-module array | `SN` → `BatteryInfo` (+`BatteryModule[]`) | 60 s |
| `/WManage/api/battery/getBatteryInfoForSet` | Battery identity list only | `SN` → `BatteryListResponse` | 60 s |

### gridboss
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/midbox/getMidboxRuntime` | GridBOSS/MID runtime | `SN` → `MidboxRuntime` (+`MidboxData`) | 20 s |

### control
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/web/maintain/remoteRead/read` | Read register range (named params) | `iSN,startRegister,pointNumber,autoRetry` → `ParameterReadResponse` | 2 min |
| `/WManage/web/maintain/remoteSet/write` ⚠️WRITE | Write one named param | `iSN,holdParam,valueText,clientType,remoteSetType` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/writeTime` ⚠️WRITE | Atomic time boundary | `iSN,timeParam,hour,minute,...` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/functionControl` ⚠️WRITE | Toggle function bit | `iSN,functionParam,enable,...` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/bitParamControl` ⚠️WRITE | Set bit enum param | `iSN,bitParam,value,...` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/start` ⚠️WRITE | Start quick charge | `iSN,clientType,minute?` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/stop` ⚠️WRITE | Stop quick charge | `iSN,clientType` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/getStatusInfo` | Quick charge/discharge status | `iSN` → `QuickChargeStatus` | 1 min |
| `/WManage/web/config/quickDischarge/start` ⚠️WRITE | Start quick discharge | `iSN,clientType` → `SuccessResponse` | — |
| `/WManage/web/config/quickDischarge/stop` ⚠️WRITE | Stop quick discharge | `iSN,clientType` → `SuccessResponse` | — |

**Composed helpers (no new endpoints):** raw multi-register `write_parameters` resolves
each `{register: value}` pair to a **named** `remoteSet/write` (a bad register aborts the
whole batch before any write). Schedule families compose `write`/`writeTime`/`read`:

| Family | ScheduleType | Periods | Write convention |
|---|---|---|---|
| AC Charge | `AC_CHARGE` | 3 | classic (4× `_HOUR`/`_MINUTE` writes) |
| Forced Charge | `FORCED_CHARGE` | 3 | classic |
| Forced Discharge | `FORCED_DISCHARGE` | 3 | classic |
| AC First (off-grid/SNA) | `AC_FIRST` | 3 | classic |
| Generator | `GEN_CHARGE` | 2 | `writeTime` |
| Off-Grid | `OFF_GRID` | 3 | `writeTime` |
| Peak Shaving | `PEAK_SHAVING` | 2 | `writeTime` (read via `LSP_HOLD_DIS_CHG_POWER_TIME_*`) |

### firmware
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/web/maintain/standardUpdate/checkUpdates` | Check for updates | `SN` → `FirmwareUpdateCheck` | 24 h |
| `/WManage/web/maintain/standardUpdate/check12KParallelStatus` | Eligibility (all devices) | `userId,SN` → `UpdateEligibilityStatus` | — |
| `/WManage/web/maintain/standardUpdate/run` ⚠️WRITE | Start one update step | `userId,SN,tryFastMode` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteUpdate/info` | Update status/progress (account-wide) | `userId` → `FirmwareUpdateStatus` | 10 s in-progress / 5 min idle |

### analytics
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/analyze/chart/dayLine` | Hourly sensor time-series | `SN,attr,dateText` → provisional | none |
| `/WManage/api/analyze/energy/dayColumn` | Hourly energy breakdown | `SN,parallel,year,month,day,energyType` → provisional | none |
| `/WManage/api/analyze/energy/monthColumn` | Daily breakdown (1 series) | `SN,parallel,year,month,energyType` → provisional | none |
| `/WManage/api/analyze/energy/yearColumn` | Monthly breakdown | `SN,parallel,year,energyType` → provisional | none |
| `/WManage/api/analyze/energy/totalColumn` | Yearly (lifetime) breakdown | `SN,parallel,energyType` → provisional | none |
| `/WManage/api/inverterChart/monthColumn` | Daily-energy history, all series (single) | `SN,year,month` → `MonthlyEnergyHistoryResponse` | none |
| `/WManage/api/inverterChart/monthColumnParallel` | Daily-energy history (group) | `SN,year,month` → `MonthlyEnergyHistoryResponse` | none |
| `/WManage/api/analyze/event/list` | Fault/warning/event log | `page,rows,plantId,SN,eventText` → provisional | none |

### forecasting
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/predict/solar/dayPredictColumnParallel` | Solar-production forecast | `SN` → provisional | none |
| `/WManage/api/weather/forecast` | Weather forecast | `SN` → provisional | none |

### export
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `GET /WManage/web/analyze/data/export/{serialNum}/{startDate}?endDateText=` | Historical runtime `.xls` | path+query → binary `.xls` | none |

## Firmware multi-step update flow

Some devices (e.g. 6000XP) update one firmware component at a time, so a full update is a
**chain of `run` calls**. The `pylxpweb` orchestrator drives it as:

1. **`checkUpdates`** (forced) → `FirmwareUpdateCheck`. If already up to date, the API
   returns `success:false` with an "already the latest version" message which the client
   converts into a synthetic up-to-date result. `needRunStep2..5` advertise a chain but
   their exact semantics are **unverified and deliberately not used to gate re-runs**.
2. **`check12KParallelStatus`** → eligibility. Proceed only when `msg == allowToUpdate`.
3. **`run`** (`tryFastMode`) → starts one component/step. The response's `success` is the
   only field consumed; the client optimistically marks `in_progress=True, percentage=0`.
4. **Poll `remoteUpdate/info`** (always forced — an unforced poll would replay the 5-min
   idle snapshot and abandon a genuinely running step). Two phases: a ~300s `start_grace`
   window for the accepted run to become in-progress, then poll to terminal within
   `step_timeout` (3600s). Progress % is regex-parsed from each row's `updateRate`
   string (`"50% - 280 / 561"`).
5. If a device row reports **`FAILED`**, STOP. Otherwise run a bounded settle window
   (3 checks × 30s) looking for version movement, then **re-check** — if an update still
   remains, run the next step. Bounded by `max_steps=5`.

**`updateStatus` state machine** (per `FirmwareDeviceInfo`):
- `is_in_progress` = `!isSendEndUpdate` ∧ ( (status ∈ {`UPLOADING`, `READY`} ∧ `isSendStartUpdate`)
  ∨ status == `WAITING` ) — `WAITING` (queued/inter-component busy) counts as in-progress so the
  HA entity stays "installing" across the whole multi-component update (issue #353)
- `is_complete` = status ∈ {`SUCCESS`, `COMPLETE`} ∧ `isSendEndUpdate` ∧ non-empty `stopTime`
- `is_failed` = status == `FAILED`

## Scaling / units

Raw integer → engineering unit. Apply at the consumer.

| Quantity | Scale | Notes |
|---|---|---|
| Voltages: `vpv*`, `vac*`, `veps*`, `vBat`, `genVolt`, grid/ups/gen RMS | ÷10 | decivolts → V |
| Bus voltages `vBus1`,`vBus2` | ÷100 | |
| Frequency `fac`,`feps`,`genFreq`,`gridFreq`,`phaseLockFreq` | ÷100 | centihertz → Hz |
| Inverter `maxChgCurr`/`maxDischgCurr` | ÷100 | |
| MidBox RMS currents (`gridL1RmsCurr` etc.) | ÷100 | centiamps → A |
| MidBox smart-load RMS current (`smartLoad*RmsCurr`) | ÷10 | exception to ÷100 |
| Battery module `totalVoltage` | ÷100 | |
| Battery module `current` | **÷10** | **critical: not ÷100** |
| Battery cell voltage (`batMaxCellVoltage`/`Min`) | ÷1000 | mV → V |
| Battery cell temp (`batMaxCellTemp`/`Min`) | ÷10 | |
| Power (all `p*` active power) | ×1 | direct watts |
| Temperatures (`tinner`,`tradiator*`,`tBat`) | ×1 | direct °C (`tBat`=127/0x7F is a no-BMS sentinel → null) |
| **Energy totals** (`EnergyInfo.*`, `MidboxData.e*`, `*Day` history) | **÷10** | raw is **0.1 kWh** units |
| Overview `vBat` (`InverterOverviewItem`) | ÷10 | |
| Overview `total*` energy | ÷10 | |
| `PlantInfo.nominalPower` | ×1 | Watts |
| Named-param writes (`remoteSet/write` `valueText`) | pre-scaled | already in engineering units (volts, %, whole amps); e.g. AC-charge voltage limits are **volts, not decivolts** |

## Gaps & unverified schemas

Carried forward from the three domain maps:

**Untyped / provisional response bodies** (no Pydantic model — field names/shapes from
SDK docstrings, unverified against live payloads; marked provisional in the spec):
- `plantOverview/list/viewer` — `rows[]` fields not enumerated.
- `analyze/chart/dayLine`, `analyze/energy/{day,month,year,total}Column`,
  `analyze/event/list` — `dataPoints`/`rows` shapes are docstring-confidence; casing and
  nesting may differ.
- `predict/solar/dayPredictColumnParallel`, `weather/forecast` — entirely
  docstring-derived; confirm against a live payload before relying on them.

**Firmware enum tolerance (post-#353 — resolved):**
- **`WAITING`** is a real device-reported `updateStatus` (issue #353, queued/waiting phase
  of a multi-step update on e.g. the 6000XP). It was originally **missing from the
  `pylxpweb` `UpdateStatus` enum** — a server row with `updateStatus:"WAITING"` **failed
  Pydantic validation** and crashed the update flow. The #353 fix adds `WAITING` and treats
  it as in-progress. It is in this spec's `UpdateStatus`.
- **`deviceBusy`** can be observed on the firmware/eligibility path and is **not** one of the
  `UpdateEligibilityMessage` members (`allowToUpdate`/`deviceUpdating`/`parallelGroupUpdating`/
  `notAllowedInParallel`/`warnParallel`). Post-#353 this is no longer a crash: BOTH
  `UpdateStatus` and `UpdateEligibilityMessage` carry a `_missing_` hook that coerces any
  unrecognized value to a client-side `UNKNOWN` sentinel (neutral; `is_allowed` stays False),
  so a novel status/eligibility string validates gracefully instead of raising a
  `ValidationError`. `UNKNOWN` is a client sentinel, not an API-emitted value.

**Plant configuration writes:** `POST /WManage/web/config/plant/edit` is the JSON
form-urlencoded **write** path (`plants.update_plant_config` / `set_daylight_saving_time`,
the latter driving DST sync). The client reads the current record, then re-POSTs the full
config with the changed field(s); `timezone`/`country`/`continent`/`region` are EG4 enum
tokens. The `continent`/`region` tokens are resolved via the `POST /WManage/locale/region`
and `POST /WManage/locale/country` lookups when the static map misses. All three are now in
the spec (documented from source; not exercised live).

**Other known gaps:**
- **Latitude/longitude** are not exposed by any JSON endpoint, and are **not** settable via
  the `POST /WManage/web/config/plant/edit` write above — only via hidden fields on the
  separate HTML plant-edit form (`GET /WManage/web/config/plant/edit/{plantId}`).
- **Login wire extras** dropped by Pydantic: top-level `clusterGroup`,
  `quickChargeDefaultDuration`; per-inverter `datalogSn`/`lastUpdateTime`/`model`/
  `modelText`/`odmValue`; `userVisitRecord` `odm`/`odmValue`/`subDeviceType`.
- **`endUser` / `deviceTypeText4APP`** may be entirely absent from
  `inverterOverview/list` rows on some (e.g. VIEWER) accounts; account-level detection
  then defaults to `owner`.
- **Error-code catalog is partial:** the transient set is confirmed
  (`DATAFRAME_TIMEOUT`, `TIMEOUT`, `BUSY`, `COMMUNICATION_ERROR`, `DEVICE_BUSY`); other
  non-transient permission/parameter codes are surfaced verbatim in `message`/`msg` but
  not enumerated.
- **`analyze/energy/*` `energyType` enum** is only partially documented
  (`eInvDay`,`eToUserDay`,`eToGridDay`,`eAcChargeDay`,`eBatChargeDay`,`eBatDischargeDay`);
  the full server-accepted set is unknown. Likewise `chart/dayLine` `attr` tracks
  `InverterRuntime` field names but is not exhaustively enumerated.
- **Energy-scale discrepancy** (resolved): some `devices.py` docstrings say "÷1000 (Wh)"
  while the models and `docs/DATA_MAPPING.md` say **÷10 (0.1 kWh)** — **÷10 is
  authoritative**.
- **Export `.xls`** column headers are firmware-dependent and not enumerated; the parser
  is header-agnostic. Server caps the workbook at **10 day-sheets** anchored at
  `startDate` going forward.
- **`autoParallel`** request/response documented from source only (write endpoint, not
  exercised).
- **Live validation scope:** auth/plants/devices were live-validated 2026-07-14; typed
  runtime/energy/battery/midbox schemas are Pydantic-backed (high confidence);
  control/firmware and all analytics/forecast dict schemas were mapped from source only.

## Validation

```bash
uv run --with pyyaml --with openapi-spec-validator python3 -c \
  "import yaml; from openapi_spec_validator import validate; validate(yaml.safe_load(open('docs/api/openapi.yaml')))"
```

The spec passes OpenAPI 3.1.0 validation (44 operations, 55 component schemas).
