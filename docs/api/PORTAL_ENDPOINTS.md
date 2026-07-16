# EG4 Monitor Portal — Full Endpoint Catalog (frontend-discovered)

> **Scope:** this catalogues **every `/WManage/...` endpoint referenced by the EG4 monitor
> portal's authenticated web frontend** — a much larger surface than the client-used subset
> documented in [`openapi.yaml`](openapi.yaml). It answers "how much of the real API do we
> cover?": the OpenAPI spec covers the **44** endpoints the `pylxpweb` client calls; the portal
> frontend references **186**.
>
> **How this was produced:** static, read-only analysis of the portal's HTML pages and ~64
> jQuery JS files (role: VIEWER), 2026-07-15. Endpoints were catalogued **from JS source**, not
> invoked — **no write/control/firmware endpoint was ever called**, and no account or device
> state was changed.
>
> **Validation status:** the **KNOWN** endpoints (the 35 of the 44 that surface in VIEWER JS)
> are fully typed in `openapi.yaml`. The **NEW** endpoints here are **inventory only** — path +
> HTTP method + request-param *names* extracted from the frontend; their request/response
> **schemas are NOT validated** (and the ~55 write/control ones deliberately were not exercised).
> Treat this as a discovery map, not a verified contract. Owner/installer/admin sections are
> absent (VIEWER role), so the true portal surface is larger still.
>
> Legend: `R/W` — READ (get/list/query/overview/check) vs WRITE (set/save/add/remove/update/run/
> start/stop/control/bind). `KNOWN` = in the 44-endpoint `pylxpweb` subset; `NEW` = beyond it.
> `(q)` = query-string param. `?` method = the call site used a wrapper/`$.ajax` where the type
> was not co-located (server-rendered page routes are GET; JSON data calls are POST unless noted).


> Static, read-only discovery from the authenticated jQuery frontend (role: VIEWER).
> Base host `https://monitor.eg4electronics.com`; JS assets on `https://resource.solarcloudsystem.com`.
> All app paths are prefixed with `baseUrl = /WManage` at runtime (shown here without it).
> Serials / plant IDs / user IDs obfuscated. `(q)` = query-string param. `?` method = call site used a
> wrapper/`$.ajax` where type was not co-located (page routes are GET HTML; data calls are POST unless noted).

**Totals:** 186 distinct `/WManage/...` paths — **35 KNOWN** (in the 44-endpoint pylxpweb subset), **151 NEW**. ~55 write/control, ~52 server-rendered page routes, remainder JSON read endpoints.

## api: EV charge point  (2)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/chargePoint/getChargePointRunTime` | READ | NEW | clientType,inverterSn |
| POST | `/api/chargePoint/realTime` | READ | NEW | inverterSn |

## api: analyze/chart  (7)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/api/analyze/chart/analyzeParallelChartData` | READ | NEW | - |
| POST | `/api/analyze/chart/dayLine` | READ | KNOWN | attr,dateText,serialNum |
| POST | `/api/analyze/chart/dayMultiLine` | READ | NEW | - |
| ? | `/api/analyze/event/list` | READ | KNOWN | - |
| POST | `/api/inverterChart/monthColumn` | READ | KNOWN | - |
| POST | `/api/inverterChart/totalColumn` | READ | NEW | - |
| POST | `/api/inverterChart/yearColumn` | READ | NEW | - |

## api: analyze/chart (predict)  (1)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/predict/solar/` | READ | KNOWN | - |

## api: battery  (3)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/battery/getBatteryInfo` | READ | KNOWN | serialNum |
| POST | `/api/battery/getBatteryInfoForSet` | READ | KNOWN | serialNum |
| POST | `/api/battery/removeBatteryRuntime` | WRITE | NEW | batterySn,serialNum |

## api: googleHome  (2)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| GET | `/api/googleHome/getDeviceSetting` | READ | NEW | serialNum |
| POST | `/api/googleHome/saveDeviceSetting` | WRITE | NEW | - |

## api: gridboss / midbox  (4)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/midbox/genQuickStart` | READ | NEW | - |
| GET | `/api/midbox/genStatus` | READ | NEW | serialNum |
| POST | `/api/midbox/genStop` | WRITE | NEW | clientType,serialNum |
| POST | `/api/midbox/getMidboxRuntime` | READ | KNOWN | serialNum |

## api: inverter  (13)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/inverter/autoParallel` | WRITE | KNOWN | plantId |
| POST | `/api/inverter/ctrlBatteryBackup` | WRITE | NEW | clientType,enable,inverterSn |
| POST | `/api/inverter/ctrlGenExercise` | WRITE | NEW | clientType,enable,inverterSn |
| POST | `/api/inverter/ctrlGenResetTime` | WRITE | NEW | clientType,inverterSn |
| POST | `/api/inverter/getGenResetInfo` | READ | NEW | inverterSn |
| ? | `/api/inverter/getInverterBatteryInfoParallel` | READ | NEW | - |
| POST | `/api/inverter/getInverterEnergyInfo` | READ | KNOWN | - |
| POST | `/api/inverter/getInverterRuntime` | READ | KNOWN | serialNum |
| POST | `/api/inverter/getInverterRuntimeParallel` | READ | NEW | serialNum |
| POST | `/api/inverter/queryEpsOverloadRecoveryTime` | READ | NEW | inverterSn |
| POST | `/api/inverter/transferData` | WRITE | NEW | fromClusterId,inverterSn |
| POST | `/api/inverter/updateAdvancedSettings` | WRITE | NEW | allowExport2Grid,inverterSn |
| POST | `/api/inverterOverview/getParallelGroupDetails` | READ | KNOWN | serialNum |

## api: inverter (generator)  (3)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/gen/exercise/clearGenExerciseInfo` | WRITE | NEW | serialNum |
| POST | `/api/gen/exercise/getGenExerciseInfo` | READ | NEW | serialNum |
| POST | `/api/gen/exercise/updateGenExerciseInfo` | WRITE | NEW | dayOfWeekLocal,hourMinuteLocal,serialNum |

## api: overview  (2)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| GET | `/api/plantOverview/export` | READ | NEW | searchText(q) |
| ? | `/api/plantOverview/list/viewer` | READ | KNOWN | - |

## api: phnix (heat pump)  (1)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/phnix/getData` | READ | NEW | - |

## api: plant  (1)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/plant/getPlantInfo` | READ | NEW | plantId |

## api: system / cluster  (5)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/system/cluster/search/` | READ | NEW | - |
| POST | `/api/system/cluster/search/checkWarranty` | READ | NEW | serialNums |
| POST | `/api/system/cluster/search/findOnlineDatalog` | READ | KNOWN | serialNum |
| POST | `/api/system/cluster/search/findOnlineInverter` | READ | NEW | serialNum |
| POST | `/api/system/cluster/search/viewerFindOnlineDevice` | READ | NEW | plantId |

## api: tigo (optimizer)  (3)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/tigo/checkAuth` | READ | NEW | serialNum,tigoPassword,tigoUsername |
| POST | `/api/tigo/getDeviceTigoInfo` | READ | NEW | serialNum |
| POST | `/api/tigo/updateDeviceTigoInfo` | WRITE | NEW | serialNum,systemId,tigoPassword,tigoUsername |

## api: user prefs  (6)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/userChartRecord/saveOrUpdateChartColor` | WRITE | NEW | - |
| POST | `/api/userChartRecord/saveUserChartRecord` | WRITE | NEW | - |
| ? | `/api/userFav/getUserFavPlantRecordList` | READ | NEW | clientType(q) |
| POST | `/api/userFav/removeUserFavPlantRecord` | WRITE | NEW | plantId |
| POST | `/api/userFav/saveUserFavPlantRecord` | WRITE | NEW | plantId,remarks |
| POST | `/api/userVisit/update` | WRITE | NEW | plantId,serialNum |

## api: weather  (4)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/api/weather/forecast` | READ | KNOWN | serialNum |
| POST | `/api/weather/plant/clearLocation` | WRITE | NEW | plantId |
| POST | `/api/weather/plant/forecast/manual` | READ | NEW | country,inputLocation |
| POST | `/api/weather/plant/saveLocation` | WRITE | NEW | - |

## web: analyze  (14)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/analyze/battery/renonData` | READ (page) | NEW | - |
| ? | `/web/analyze/chart` | READ (page) | NEW | - |
| ? | `/web/analyze/chartCompare` | READ (page) | NEW | - |
| ? | `/web/analyze/chartMidBox` | READ (page) | NEW | - |
| ? | `/web/analyze/data` | READ (page) | NEW | - |
| ? | `/web/analyze/data/` | READ (page) | NEW | - |
| ? | `/web/analyze/data/export/` | READ | KNOWN | - |
| ? | `/web/analyze/data/export1/` | READ | NEW | - |
| ? | `/web/analyze/energy` | READ (page) | NEW | - |
| ? | `/web/analyze/energy/exportData` | READ | NEW | serialNum(q) |
| ? | `/web/analyze/event` | READ (page) | NEW | - |
| ? | `/web/analyze/event/export` | READ | NEW | eventText(q),plantId(q) |
| POST | `/web/analyze/event/remove` | WRITE | NEW | recordId |
| ? | `/web/analyze/localData` | READ (page) | NEW | - |

## web: config  (33)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/config/datalog` | READ (page) | NEW | - |
| POST | `/web/config/datalog/add` | WRITE | NEW | plantId,serialNum,verifyCode |
| POST | `/web/config/datalog/checkUpdates` | READ | NEW | - |
| POST | `/web/config/datalog/edit` | WRITE | NEW | plantId,serialNum |
| ? | `/web/config/datalog/export` | READ | NEW | - |
| POST | `/web/config/datalog/getAllFirmwares` | READ | NEW | datalogType |
| POST | `/web/config/datalog/getDongleInfo` | READ | NEW | serialNum |
| ? | `/web/config/datalog/list` | READ | KNOWN | - |
| POST | `/web/config/datalog/readInvInfo` | READ | NEW | serialNum |
| POST | `/web/config/datalog/removeWithPin` | WRITE | NEW | - |
| POST | `/web/config/datalog/updateFirmware` | WRITE | NEW | dongleFirmware,serialNum |
| ? | `/web/config/datalog/upload` | READ (page) | NEW | - |
| ? | `/web/config/inverter` | READ (page) | NEW | - |
| POST | `/web/config/inverter/bindChargePoint` | WRITE | NEW | chargePointSn,productType,serialNum |
| ? | `/web/config/inverter/bmsMinCellVoltExport` | READ | NEW | bmsMinCellVoltMin(q) |
| POST | `/web/config/inverter/clearBindConnection` | WRITE | NEW | serialNum |
| POST | `/web/config/inverter/getChargePointBySn` | READ | NEW | serialNum |
| ? | `/web/config/inverter/list` | READ | NEW | - |
| POST | `/web/config/inverter/remove` | WRITE | NEW | serialNum |
| POST | `/web/config/inverter/updateUsedAtCustomerDate` | WRITE | NEW | password,serialNum,usedAtCustomerDate |
| ? | `/web/config/plant` | READ (page) | NEW | - |
| ? | `/web/config/plant/edit/` | READ (page) | KNOWN | - |
| POST | `/web/config/plant/editNotice` | WRITE | NEW | noticeEmail,noticeEmail2,noticeType,plantId |
| ? | `/web/config/plant/editPlantImage/` | READ (page) | NEW | - |
| ? | `/web/config/plant/export` | READ | NEW | - |
| ? | `/web/config/plant/exportInverterType` | READ | NEW | page(q) |
| ? | `/web/config/plant/list/viewer` | READ | KNOWN | - |
| POST | `/web/config/plant/remove` | WRITE | NEW | plantId |
| POST | `/web/config/quickCharge/getStatusInfo` | READ | KNOWN | inverterSn |
| POST | `/web/config/quickCharge/start` | WRITE | KNOWN | - |
| POST | `/web/config/quickCharge/stop` | WRITE | KNOWN | clientType,inverterSn |
| POST | `/web/config/quickDischarge/start` | WRITE | KNOWN | clientType,inverterSn |
| POST | `/web/config/quickDischarge/stop` | WRITE | KNOWN | clientType,inverterSn |

## web: inverter  (1)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/web/inverter/debugqna/startAnalyse` | WRITE | NEW | - |

## web: login  (3)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/login` | READ (page) | KNOWN | - |
| ? | `/web/login/clusterLoginForward` | READ (page) | NEW | clusterLoginKey(q) |
| ? | `/web/login/viewDemoPlant` | READ (page) | NEW | customCompany(q) |

## web: logout  (1)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/logout` | READ (page) | NEW | - |

## web: maintain  (51)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/maintain/battUpdate` | READ (page) | NEW | - |
| POST | `/web/maintain/notification/showList` | READ | NEW | deviceType,page,rows |
| POST | `/web/maintain/readDatalogParam/read` | READ | NEW | datalogParam,datalogSn |
| POST | `/web/maintain/remoteRead/midDiff` | READ | NEW | inverterSn |
| POST | `/web/maintain/remoteRead/read` | READ | KNOWN | autoRetry,inverterSn,pointNumber,startRegister |
| POST | `/web/maintain/remoteRead/readInput` | READ | NEW | inverterSn |
| POST | `/web/maintain/remoteRead/readMultiBitParam` | READ | NEW | inverterSn |
| ? | `/web/maintain/remoteSet` | READ (page) | NEW | - |
| POST | `/web/maintain/remoteSet/bitModelParamControl` | READ | NEW | clientType,inverterSn,modelBitParam,remoteSetType,value |
| POST | `/web/maintain/remoteSet/bitParamControl` | READ | KNOWN | bitParam,clientType,inverterSn,remoteSetType,value |
| POST | `/web/maintain/remoteSet/functionControl` | READ | KNOWN | clientType,enable,functionParam,inverterSn,remoteSetType |
| POST | `/web/maintain/remoteSet/reset` | WRITE | NEW | clientType,inverterSn,remoteSetType,resetParam |
| POST | `/web/maintain/remoteSet/wattNode/read` | READ | NEW | inverterSn |
| POST | `/web/maintain/remoteSet/wattNode/write` | WRITE | NEW | inverterSn |
| POST | `/web/maintain/remoteSet/write` | WRITE | KNOWN | clientType,holdParam,inverterSn,remoteSetType,valueText |
| POST | `/web/maintain/remoteSet/writeG98ValueForINF01` | WRITE | NEW | clientType,inverterSn,remoteSetType |
| POST | `/web/maintain/remoteSet/writeModel` | WRITE | NEW | batteryType,inverterSn,leadAcidType,measurement,meterBrand,meterType,ruleMask,usVersion,wirelessMeter |
| POST | `/web/maintain/remoteSet/writeModelByDeviceType` | WRITE | NEW | clientType,deviceType,inverterSn,remoteSetType |
| POST | `/web/maintain/remoteSet/writeMultiBitParam` | WRITE | NEW | - |
| POST | `/web/maintain/remoteSet/writeMultiValue` | WRITE | NEW | - |
| POST | `/web/maintain/remoteSet/writePartModel` | WRITE | NEW | - |
| POST | `/web/maintain/remoteSet/writeTime` | WRITE | KNOWN | clientType,hour,inverterSn,minute,remoteSetType,timeParam |
| ? | `/web/maintain/remoteSet12K` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetAllInOne` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetLsp` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetMidbox` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetOffGrid` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetRecord` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteSetWeekly` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteTransfer/export` | READ | NEW | exportType(q),serialNum(q) |
| POST | `/web/maintain/remoteTransfer/refreshInputData` | WRITE | NEW | inverterSn |
| POST | `/web/maintain/remoteTransfer/sendReadInputCommand` | WRITE | NEW | index,inverterSn |
| ? | `/web/maintain/remoteUpdate` | READ (page) | NEW | - |
| ? | `/web/maintain/remoteUpdate/cancel` | WRITE | NEW | serialNum,userId |
| ? | `/web/maintain/remoteUpdate/info` | READ | KNOWN | userId |
| ? | `/web/maintain/remoteUpdate/run` | WRITE | NEW | serialNums,tryFastMode,userId |
| ? | `/web/maintain/remoteUpdate/upload` | WRITE | NEW | - |
| ? | `/web/maintain/setupWizard` | READ (page) | NEW | serialNum(q) |
| ? | `/web/maintain/standardUpdate/check12KParallelStatus` | READ | KNOWN | serialNum,userId |
| POST | `/web/maintain/standardUpdate/checkUpdates` | READ | KNOWN | serialNum |
| ? | `/web/maintain/standardUpdate/list` | READ (page) | NEW | - |
| ? | `/web/maintain/standardUpdate/run` | WRITE | KNOWN | serialNum,tryFastMode,userId |
| POST | `/web/maintain/template/importTemplate` | WRITE | NEW | inverterSn,templateId |
| POST | `/web/maintain/template/list` | READ | NEW | deviceType,dtc,machineType,odm,phase,powerRating,usVersion,voltClass |
| ? | `/web/maintain/weatherSet` | READ (page) | NEW | - |
| ? | `/web/maintain/workingMode/12k` | READ (page) | NEW | - |
| ? | `/web/maintain/workingMode/eqb` | READ (page) | NEW | - |
| ? | `/web/maintain/workingMode/hybrid` | READ (page) | NEW | - |
| ? | `/web/maintain/workingMode/midbox` | READ (page) | NEW | - |
| ? | `/web/maintain/workingMode/sna` | READ (page) | NEW | - |
| POST | `/web/maintain/writeDatalogParam/write` | WRITE | NEW | clientType,datalogParam,datalogSn,remoteSetType,valueText |

## web: monitor  (5)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/monitor/battery/zrgp` | READ (page) | NEW | - |
| ? | `/web/monitor/battery/zrgpAio` | READ (page) | NEW | - |
| ? | `/web/monitor/inverter` | READ (page) | NEW | - |
| ? | `/web/monitor/lsp/inverter` | READ (page) | NEW | serialNum(q) |
| ? | `/web/monitor/micro/inverter` | READ (page) | NEW | - |

## web: overview  (3)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/overview/global` | READ (page) | NEW | - |
| ? | `/web/overview/globalPlant` | READ (page) | NEW | - |
| ? | `/web/overview/plant` | READ (page) | NEW | autoSelectPlant(q) |

## web: register  (6)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| ? | `/web/register` | READ (page) | NEW | - |
| POST | `/web/register/checkDatalogSnValidForRegister` | READ | NEW | datalogSn |
| POST | `/web/register/isAccountExist` | READ | NEW | account |
| POST | `/web/register/isCheckCodeMatch` | READ | NEW | checkCode,datalogSn |
| POST | `/web/register/isCustomerCodeExist` | READ | NEW | customerCode |
| ? | `/web/register/viewer` | READ (page) | NEW | - |

## web: system  (8)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/web/system/cluster/buildClusterKey` | WRITE | NEW | serverClusterId |
| ? | `/web/system/user` | READ (page) | NEW | - |
| ? | `/web/system/user/center` | READ (page) | NEW | - |
| POST | `/web/system/user/getUseNewSettingPageValue` | READ | NEW | userId |
| ? | `/web/system/user/modifyPassword/{userId}` | READ (page) | NEW | - |
| ? | `/web/system/user/preferences/{userId}` | READ (page) | NEW | - |
| POST | `/web/system/user/useNewSettingPage` | WRITE | NEW | useWorkingModePage,userId |
| ? | `/web/system/user/userSet` | READ (page) | NEW | - |

## auth / locale  (4)

| Method | Endpoint (under /WManage) | R/W | Known? | Params |
|---|---|---|---|---|
| POST | `/authCode` | READ | NEW | authCode |
| POST | `/locale` | READ | NEW | language |
| POST | `/locale/country` | READ | KNOWN | region |
| POST | `/locale/region` | READ | KNOWN | continent |

---

## Crawl provenance

**Authenticated pages fetched (HTTP 200 unless noted), `/WManage/web/...`:**
monitor/inverter, overview/global, config/plant, config/inverter, config/datalog,
analyze/chart, analyze/data, analyze/event, maintain/remoteUpdate, system/user/center,
maintain/workingMode/12k (281 KB — the inverter Remote Set page; `maintain/remoteSet` and
`maintain/workingMode/hybrid` both **302→ workingMode/12k**), maintain/workingMode/midbox
(351 KB — the GridBOSS/MID Remote Set page), plus unauthenticated login + register pages.

**404 (route does not exist):** monitor/plantList, config/user, maintain/standardUpdate, manage/user,
workingMode/{acdc,lv,ac,18k,15k,parallel,gridboss}.
**405 (POST-only, not GET-reachable):** maintain/notification/showList, system/user/list.

**JavaScript analysed:** 64 app JS files under `/WManage/web/js/` (every `<script src>` referenced by the
crawled pages), fetched from `resource.solarcloudsystem.com` at `?v=2.7.3.1`. Key files for the control surface:
`maintain/remoteSet12K/workingMode2/remoteCtrlCommon2.js`, `maintain/remoteSetMidbox/workingMode2/remoteCtrlCommonMidbox.js`,
`maintain/remoteSet/remoteModelSet.js`, `maintain/remoteUpdate/remoteUpdate.js`, `monitor/inverter/monitor_ctrls.js`,
`config/device/inverter/modal/inverterConfigModal.js`, `config/device/datalog/modal/datalogConfigModal.js`,
`login/register.js`, `format/headerMenu.js`.

## KNOWN endpoints NOT surfaced by the VIEWER frontend (used by pylxpweb / admin roles only)

These 9 of the 44 documented endpoints never appear in the VIEWER-role JS (the frontend uses different
sibling calls, or they are owner/admin/installer-only, or API-client-only):

- `plant/list` — VIEWER frontend only ever calls `config/plant/list/viewer`.
- `inverterOverview/list` — frontend uses `inverterOverview/getParallelGroupDetails` + `system/cluster/search/viewerFindOnlineDevice`.
- `inverter/getInverterInfo` — not called; frontend uses `getInverterRuntime`/`getInverterEnergyInfo`.
- `inverter/getInverterEnergyInfoParallel` — frontend has `getInverterRuntimeParallel` + `getInverterBatteryInfoParallel` instead.
- `inverterChart/monthColumnParallel` — only non-parallel `monthColumn`/`yearColumn`/`totalColumn` are wired in `tab_chart_*.js`.
- `analyze/energy/dayColumn`, `analyze/energy/monthColumn`, `analyze/energy/yearColumn`, `analyze/energy/totalColumn`
  — this portal build routes energy columns through `/api/inverterChart/*Column` instead; the `analyze/energy/*Column`
  path family is not referenced.

(`/api/login` — pylxpweb's auth path — is not in the JS either; the browser login form POSTs to `/web/login`.
`locale/region` and `locale/country` DO appear, on the register page, as `baseUrl + /locale/region|country`.)

## Role gating (VIEWER)

The logged-in account is **VIEWER**. Owner/installer-only sections return 404/405 or are absent from the menu
(no `manage/*`, no `config/user`, no user-admin list). The Remote Set / Working Mode / Remote Update / firmware pages
ARE reachable and their full write/control JS is present, so the control endpoints below were catalogued from source
**without being invoked**. Endpoints marked WRITE were NOT exercised.

## Dynamic / concatenated endpoints resolved

- `/api/predict/solar/` + `{dayPredictColumn | dayPredictColumnParallel}` (predictionChart.js).
- `/api/system/cluster/search/` + `{findOnlineDatalog | findOnlineInverter | viewerFindOnlineDevice | checkWarranty}` (built dynamically in deviceClusterModal.js).
- `/web/analyze/data/export/` and `/web/analyze/data/export1/` take trailing path segments (export type/format).
- `/web/config/plant/edit/{plantId}`, `/web/config/plant/editPlantImage/{plantId}`, `/web/system/user/modifyPassword/{userId}`, `/web/system/user/preferences/{userId}` are RESTish path-param routes.
