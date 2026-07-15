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
| `forecasting` | Solar + weather forecasts |
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
(`SN` = `serialNum`. All POST unless noted.)

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
| `/WManage/api/plantOverview/list/viewer` | Plant real-time overview | `searchText` → `PlantOverviewResponse` | 30 s |

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
| `/WManage/web/maintain/remoteRead/read` | Read register range (named params) | `inverterSn,startRegister,pointNumber,autoRetry` → `ParameterReadResponse` | 2 min |
| `/WManage/web/maintain/remoteSet/write` ⚠️WRITE | Write one named param | `inverterSn,holdParam,valueText,clientType,remoteSetType` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/writeTime` ⚠️WRITE | Atomic time boundary | `inverterSn,timeParam,hour,minute,...` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/functionControl` ⚠️WRITE | Toggle function bit | `inverterSn,functionParam,enable,...` → `SuccessResponse` | — |
| `/WManage/web/maintain/remoteSet/bitParamControl` ⚠️WRITE | Set bit enum param | `inverterSn,bitParam,value,...` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/start` ⚠️WRITE | Start quick charge | `inverterSn,clientType,minute?` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/stop` ⚠️WRITE | Stop quick charge | `inverterSn,clientType` → `SuccessResponse` | — |
| `/WManage/web/config/quickCharge/getStatusInfo` | Quick charge/discharge status | `inverterSn` → `QuickChargeStatus` | 1 min |
| `/WManage/web/config/quickDischarge/start` ⚠️WRITE | Start quick discharge | `inverterSn,clientType` → `SuccessResponse` | — |
| `/WManage/web/config/quickDischarge/stop` ⚠️WRITE | Stop quick discharge | `inverterSn,clientType` → `SuccessResponse` | — |

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
| `/WManage/api/analyze/chart/dayLine` | Sensor time-series (~359 pts/day) | `SN,attr,dateText` → `DayLineResponse` | none |
| `/WManage/api/analyze/energy/dayColumn` | Hourly energy breakdown | `SN,parallel,year,month,day,energyType` → `EnergyDayColumnResponse` | none |
| `/WManage/api/analyze/energy/monthColumn` | Daily breakdown (1 series) | `SN,parallel,year,month,energyType` → `EnergyMonthColumnResponse` | none |
| `/WManage/api/analyze/energy/yearColumn` | Monthly breakdown | `SN,parallel,year,energyType` → `EnergyYearColumnResponse` | none |
| `/WManage/api/analyze/energy/totalColumn` | Yearly (lifetime) breakdown | `SN,parallel,energyType` → `EnergyTotalColumnResponse` | none |
| `/WManage/api/inverterChart/monthColumn` | Daily-energy history, all series (single) | `SN,year,month` → `MonthlyEnergyHistoryResponse` | none |
| `/WManage/api/inverterChart/monthColumnParallel` | Daily-energy history (group) | `SN,year,month` → `MonthlyEnergyHistoryResponse` | none |
| `/WManage/api/analyze/event/list` | Fault/warning/event log | `page,rows,plantId,SN,eventText` → `EventListResponse` | none |

### forecasting
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `/WManage/api/predict/solar/dayPredictColumnParallel` | Solar-production forecast | `SN` → `SolarForecastResponse` | none |
| `/WManage/api/weather/forecast` | Weather forecast | `SN` → `WeatherForecastResponse` | none |

### export
| Path | Purpose | Request → Response | TTL |
|---|---|---|---|
| `GET /WManage/web/analyze/data/export/{serialNum}/{startDate}?endDateText=` | Historical runtime `.xls` | path+query → binary `.xls` | none |

## Firmware update lifecycle

A full firmware update is **not a single call**. On multi-component devices (the 6000XP is
the reference case, eg4_web_monitor#353) the portal and mobile app issue `standardUpdate/run`
**once per firmware component**, waiting for each component to flash and the device to settle
before starting the next. A lone `run` call leaves such a device stranded on a *partial*
version — a 6000XP asked to reach `ccaa-1E1515` lands on `ccaa-1E1415` (one trailing byte
short). `pylxpweb` therefore drives an orchestrator, `run_firmware_update_to_completion()`,
that chains **check → eligibility → start → poll → settle → re-check** until the device
converges on the latest version or a guard stops it. This section documents that flow and
the empirical device behaviour it was built against.

### The four firmware endpoints

All are HTTP `POST` with `application/x-www-form-urlencoded` bodies and `success` inside an
HTTP-200 body as the error signal. `userId` (from the login response) is required by all but
`checkUpdates`.

| Endpoint | Role | Request → Response | R/W |
|---|---|---|---|
| `/WManage/web/maintain/standardUpdate/checkUpdates` | **Check** — is a newer firmware available, and what is the target version | `serialNum` → `FirmwareUpdateCheck` | read |
| `/WManage/web/maintain/standardUpdate/check12KParallelStatus` | **Eligibility** — is the device allowed to start an update *right now* | `userId,serialNum` → `UpdateEligibilityStatus` | read |
| `/WManage/web/maintain/standardUpdate/run` ⚠️ | **Start one component** — begins a single update step; chained by the orchestrator | `userId,serialNum,tryFastMode` → `{success}` | **write** |
| `/WManage/web/maintain/remoteUpdate/info` | **Status / progress poll** — per-device update rows for the whole account | `userId` → `FirmwareUpdateStatus` | read |

Notes grounded in the client:

- **`checkUpdates` folds "already up to date" into success.** When no update remains, the API
  answers `success:false` with an "already the latest version" message; the client catches
  that specific message and returns a synthetic `FirmwareUpdateCheck` with empty version
  fields (`create_up_to_date`) rather than raising. `update_available` is then simply
  `installed_version != latest_version`.
- **`check12KParallelStatus` applies to all devices**, despite the "12KParallel" name — it is
  the generic per-device eligibility gate. `is_allowed` is true **only** when
  `msg == allowToUpdate`.
- **`run` returns only a boolean.** The client consumes `bool(response.get("success"))` and
  nothing else; on success it optimistically marks the cached state `in_progress=True,
  update_percentage=0` so progress polling engages immediately.
- **`remoteUpdate/info` is account-wide.** It returns `deviceInfos: list[FirmwareDeviceInfo]`
  for every device with an active or recent update; the caller filters to its own
  `inverterSn`. Progress percentage is regex-parsed from each row's free-text `updateRate`
  (e.g. `"50% - 280 / 561"` → `50`).

### The `updateStatus` state machine

Each `FirmwareDeviceInfo` row in `remoteUpdate/info` carries an `updateStatus` plus the
boolean flags `isSendStartUpdate` / `isSendEndUpdate` and a `stopTime` string. The
`UpdateStatus` enum and its derived predicates:

| `updateStatus` | Meaning | Counts as in-progress? |
|---|---|---|
| `READY` | A component is staged and starting (paired with `isSendStartUpdate`) | yes, when `isSendStartUpdate` |
| `UPLOADING` | A component is actively transferring / flashing | yes, when `isSendStartUpdate` |
| `WAITING` | **Queued / between-component busy phase** — the multi-component gap, before the next component's start flag is set | **yes, unconditionally** |
| `COMPLETE` | Terminal success | no |
| `SUCCESS` | Terminal success | no |
| `FAILED` | Terminal failure | no |
| `UNKNOWN` | **Client-side sentinel** for any value the API emits that is not one of the above — never sent by the server | no |

Derived predicates (`FirmwareDeviceInfo`):

- **`is_in_progress`** = `not isSendEndUpdate` **and** ( ( `updateStatus ∈ {UPLOADING, READY}`
  **and** `isSendStartUpdate` ) **or** `updateStatus == WAITING` ).
  `WAITING` is treated as busy **even before** the start flag appears, so a Home Assistant
  Update entity stays "installing" across the whole multi-component update instead of
  flickering idle in the inter-component gap (#353).
- **`is_complete`** = `updateStatus ∈ {SUCCESS, COMPLETE}` **and** `isSendEndUpdate` **and**
  non-empty `stopTime`.
- **`is_failed`** = `updateStatus == FAILED`.

**Why `_missing_ → UNKNOWN` matters.** Both `UpdateStatus` and `UpdateEligibilityMessage` are
`StrEnum`s with a `_missing_` classmethod that coerces any unrecognized value to `UNKNOWN`.
A live 6000XP update surfaced states not in the original enum (`WAITING` was one; a literal
`deviceBusy` on the eligibility path was another), and a strict enum would have raised a
Pydantic `ValidationError` **mid-update**, crashing the flow over a cosmetic status string.
The tolerance is deliberately *safe by default*: `UNKNOWN` is never equal to `allowToUpdate`,
so `UpdateEligibilityStatus.is_allowed` stays `False` and an unknown state is treated as
"not yet eligible / keep waiting", never as a green light to write. `WAITING` was
subsequently promoted to a first-class in-progress value; `UNKNOWN` remains the catch-all.

> The progress conversion in `get_firmware_update_progress()` collapses **every**
> non-installing state to `in_progress=False` (it only reports a boolean + percentage). That
> is why the orchestrator reads terminal **`FAILED`** from the raw status row via a dedicated
> `_update_step_reported_failed()` check rather than inferring it from the flattened progress
> object.

### The multi-step / multi-component chain

`checkUpdates` advertises a chain through the `needRunStep2..needRunStep5` booleans
(surfaced as `needs_run_steps` on `FirmwareUpdateInfo`). **These are diagnostic only** — their
exact firmware semantics are unverified, so the orchestrator deliberately does **not** use
them to gate re-runs. The re-run decision is driven entirely by observed server state: after
each step, does an update still remain, and did the firmware version actually move?

The loop (`run_firmware_update_to_completion`), for up to `max_steps` iterations:

1. **Check** (`checkUpdates`, forced). If no update is available, return converged/success.
2. **Become eligible + start.** Poll `check12KParallelStatus`; when `allowToUpdate`, call
   `run` to start the next component. A transient busy result on *either* the eligibility
   probe or the start call is tolerated and retried within a bounded budget (see below).
3. **Poll to completion** (`remoteUpdate/info`, forced every poll) in two phases: a
   `start_grace` window for the accepted run to become visibly `in_progress`, then poll until
   the row leaves in-progress or `step_timeout` elapses.
4. **FAILED abort.** Read the raw status row; if it reports `FAILED`, re-check the version
   (to capture any partial advance) and **stop** — issue no further `run`.
5. **Settle + re-check.** Re-run `checkUpdates` across a bounded settle window. If no update
   remains → converged. If the version key advanced → continue the chain. If nothing moved
   across the whole window → stop (do not keep writing against an unresponsive chain).

Guards (all overridable; defaults shown):

| Guard | Default | Purpose |
|---|---|---|
| **Step budget** (`max_steps`) | `5` | Hard ceiling on `run` invocations. The API defines steps 2–5, so 5 covers every known chain; exhausting it returns "update still available … stopping at step budget". |
| **Per-step timeout** (`step_timeout`) | `3600 s` | Max wait for a single component to finish installing before aborting that step. |
| **Start-grace visibility window** (`start_grace`) | `300 s` | The server registers an accepted `run` in `remoteUpdate/info` **asynchronously**. Without a grace window, an early poll seeing idle status would be mistaken for instant completion. The loop keeps polling for `in_progress=True` until it appears (fast steps that genuinely complete between polls are caught by the post-step version re-check). |
| **Forced polling** (`poll_interval`, `force=True`) | `30 s` | `get_firmware_update_progress()` caches a *not-in-progress* snapshot for **5 minutes**; an unforced poll would replay that pre-registration idle snapshot for the entire grace window and abandon a genuinely running step as "no progress". Every poll is therefore forced (~2 `remoteUpdate/info` calls/min while installing). |
| **No-progress guard** (`settle_checks`, `settle_interval`) | `3 × 30 s` | After a step, re-check the firmware version across a settle window before declaring a dead chain — the check endpoint's version data can lag the status endpoint's terminal state (cloud eventual consistency). If the progress key never moves, stop instead of looping writes. |
| **FAILED abort** | — | A step ending in `FAILED` stops the chain immediately; firing another `run` at a device whose last step failed is exactly the blind write this orchestrator exists to prevent. |
| **Bounded busy-retry** | `min(start_grace, step_timeout)` | After a component flashes, the device can still be settling/rebooting, so both the eligibility gate and the start call may briefly report busy. Those are treated as "still working" and retried within budget. On the **first** step only, a genuine *not-eligible* (non-busy) result is a real pre-flight rejection → fail fast, **no write**. Any non-busy API error always propagates. |
| **No-write-past-deadline** | — | Once the busy budget is spent, no *retry* start write is issued (the first genuine attempt is exempt, so a zero/expired grace still gets one shot). The eligibility call can straddle the deadline; the loop re-checks the clock and never fires a retry `run` past it. |

The **progress key** used by the no-progress guard is
`(installed_version, app_version_current, param_version_current)`. The full installed code is
primary because it also captures prefix-byte movement (`ccaa-1D..` → `ccaa-1E..`) that the
trailing app/param version pair alone cannot see; the pair rides along for layouts where the
code string is empty. Because the "already latest" response carries an empty
`fwCodeBeforeUpload`, the orchestrator remembers the last non-empty target
(`last_target`) to report as the converged version.

### Busy-code taxonomy

Mid-chain, both the eligibility probe and the start call can lose a TOCTOU race and come back
"busy" under several different codes. `_is_device_busy_error()` classifies them by matching
two case-folded stems in the error message — `"busy"` or `"updating"`:

| Surface | Code / message | Stem matched | Treatment |
|---|---|---|---|
| Transport / HTTP-200 error body | `deviceBusy`, `device_busy`, `DEVICE_BUSY`, bare `BUSY` | `busy` | transient → bounded retry |
| Eligibility enum (`UpdateEligibilityMessage`) | `deviceUpdating`, `parallelGroupUpdating` | `updating` | transient → bounded retry |
| `standardUpdate/run` prose | `"Device is already updating"`, `"Another device in the parallel group is updating"` | `updating` | transient → bounded retry |
| Any other start error | `"no update available"`, bad serial, permission, etc. | *(neither)* | **propagates** (real error) |

Key points:

- The same busy family can appear on **both** the eligibility probe **and** the start call,
  and both sites catch it — the multi-step chain must not abort in the settle/reboot window
  between components.
- A literal `deviceBusy` observed on the eligibility path (#353) is **not** a documented
  `UpdateEligibilityMessage` member; it validates to the `UNKNOWN` sentinel (keeping
  `is_allowed` False) and, if raised as an API error, is classified busy by the stem match.
- Matching on stems rather than an exact allowlist means a novel busy-ish phrasing is
  tolerated as transient, while a genuinely different error (no update, bad serial) contains
  neither stem and still escapes to the caller.

### Practical notes for consumers

- **Poll cadence.** While a step is installing, the orchestrator issues ~**2 forced
  `remoteUpdate/info` calls per minute** (`poll_interval=30 s`), comparable to the portal's
  own polling — a deliberate ceiling, not real-time streaming.
- **Duration.** Budget **20–40 minutes per component**; a multi-component device multiplies
  that by the number of steps. `try_fast_mode` may cut ~20–30% off a step but is best-effort.
- **This is a write with real hazards.** `run` starts an actual flash: the device goes
  unavailable, must keep power and network, and can be bricked if interrupted. Always
  `checkUpdates` → `check12KParallelStatus` → explicit user confirmation → `run` → poll.
- **Resumption is server-state-derived.** The orchestrator persists no local progress — every
  decision is re-derived from `checkUpdates` / `check12KParallelStatus` / `remoteUpdate/info`.
  An interrupted run (e.g. a Home Assistant restart mid-update) can simply be re-invoked: it
  will wait out an in-progress component (eligibility reports busy → bounded retry) or resume
  the chain if an update still remains, then converge.
- **Version rendering.** The displayed target is built by replacing the trailing app/param
  bytes of `fwCodeBeforeUpload` in place, preserving any prefix bytes — 6000XP-class codes
  carry a third leading byte (`ccaa-1E1415` → prefix `ccaa-1E`, app `0x14`, param `0x15`), so
  a naive split on `-` produced the wrong target (`ccaa-1515`) before #353.
- **Hardware-confirmation caveat.** The full orchestrated chain (guards, busy tolerance,
  version rendering) is unit-covered and was designed against the reporter's live 6000XP
  telemetry, but the end-to-end **`1E1415 → 1E1515` convergence on real hardware is the one
  piece still awaiting a re-confirmation run** — treat the multi-component 6000XP path as
  empirically-informed but not yet hardware-re-validated end to end.


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

**Live-validated response bodies (2026-07-15 — no longer provisional):** the six
analytics/forecast/overview endpoints below were captured live (read-only) and now carry
real field-level typed schemas in the spec:
- `plantOverview/list/viewer` → `PlantOverviewResponse` (`rows[]` = `PlantOverviewRow`,
  with nested `parallelGroups[]` and per-device `PlantOverviewInverter`).
- `analyze/chart/dayLine` → `DayLineResponse` (+ `DayLinePoint`).
- `analyze/energy/{day,month,year,total}Column` → `Energy{Day,Month,Year,Total}ColumnResponse`
  (each differs in period-meta + bucket key).
- `analyze/event/list` → `EventListResponse` (+ `EventRow`).
- `predict/solar/dayPredictColumnParallel` → `SolarForecastResponse`.
- `weather/forecast` → `WeatherForecastResponse` (+ `WeatherDay`, `WeatherAlert`).

**Remaining untyped / provisional response bodies** (no Pydantic model — field
names/shapes from SDK docstrings, unverified against live payloads; still marked
provisional in the spec):
- `locale/region`, `locale/country` — provisional untyped arrays (plant-edit slow path);
  not yet captured live.

**Cross-endpoint quirks (documented facts, live-validated 2026-07-15):**
- **Energy is raw 0.1 kWh everywhere** — plantOverview totals, all energy columns, solar
  predictions, and `ePvPredict` (÷10 → kWh).
- **Power is raw watts** (`ppv`, `pCharge`, `pDisCharge`, `pConsumption`).
- **Month indexing differs by endpoint:** `chart/dayLine` `data[].month` is **0-indexed**
  (Java Calendar; July=6), but `energy/yearColumn` `data[].month` is **1-indexed**.
- **`energyType` and `attr` are permissive free-form strings** — the server returns
  `success` with an empty/zero-filled series for unrecognized values rather than an error
  (so an all-zero series is indistinguishable from an unknown key). `energyType` default
  `eInvDay`; confirmed non-zero family:
  `eInvDay/eChgDay/eDisChgDay/eToGridDay/eToUserDay/eGenDay/eRecDay/eLoadDay`.
- **Latitude/longitude ARE available** via `weather/forecast` (top-level `latitude`/
  `longitude`), correcting the earlier "not exposed by any JSON endpoint" note.

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
- **Latitude/longitude** ARE exposed (read-only) by `POST /WManage/api/weather/forecast`
  as top-level `latitude`/`longitude` (live-validated 2026-07-15), but are **not** settable
  via the `POST /WManage/web/config/plant/edit` write above — only via hidden fields on the
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
- **`analyze/energy/*` `energyType` and `chart/dayLine` `attr`** are permissive free-form
  strings (see cross-endpoint quirks above): the server never rejects an unknown value — it
  returns `success` with an empty/zero-filled series — so the "accepted" set is effectively
  unbounded. The confirmed non-zero `energyType` family (live-validated 2026-07-15) is
  `eInvDay/eChgDay/eDisChgDay/eToGridDay/eToUserDay/eGenDay/eRecDay/eLoadDay`; `attr` tracks
  `InverterRuntime` field names.
- **Energy-scale discrepancy** (resolved): some `devices.py` docstrings say "÷1000 (Wh)"
  while the models and `docs/DATA_MAPPING.md` say **÷10 (0.1 kWh)** — **÷10 is
  authoritative**.
- **Export `.xls`** column headers are firmware-dependent and not enumerated; the parser
  is header-agnostic. Server caps the workbook at **10 day-sheets** anchored at
  `startDate` going forward.
- **`autoParallel`** request/response documented from source only (write endpoint, not
  exercised).
- **Live validation scope:** auth/plants/devices were live-validated 2026-07-14; the
  analytics/forecast/overview schemas (plantOverview, chart/dayLine, energy columns,
  event/list, solar + weather forecasts) were live-validated 2026-07-15; typed
  runtime/energy/battery/midbox schemas are Pydantic-backed (high confidence);
  control/firmware and the `locale/region`/`locale/country` arrays were mapped from source
  only.

## Validation

```bash
uv run --with pyyaml --with openapi-spec-validator python3 -c \
  "import yaml; from openapi_spec_validator import validate; validate(yaml.safe_load(open('docs/api/openapi.yaml')))"
```

The spec passes OpenAPI 3.1.0 validation (44 operations, 64 component schemas).
