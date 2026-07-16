# EG4 Monitor Portal — Full Endpoint Catalog (frontend-discovered)

> **Scope & method.** This catalogues **every `/WManage/...` endpoint referenced by the EG4
> monitor portal's authenticated web frontend** — a far larger surface than the client-used
> subset in [`openapi.yaml`](openapi.yaml). The OpenAPI spec is a *validated contract* for the
> **44** endpoints the `pylxpweb` client calls; this catalog is a *discovery map* of the full
> frontend surface.
>
> **Totals (this exhaustive pass, 2026-07-15):** **251 distinct `/WManage/...` endpoints** —
> **113 READ**, **89 WRITE**, **49 server-rendered page routes**.
> 41 map to the validated `openapi.yaml` set; the rest are beyond it. Of the READ
> endpoints, **23 were live-validated read-only** (2026-07-15) — their captured top-level
> response fields are listed in the "Live-validated" section below.
>
> **How produced.** Read-only static analysis (role: VIEWER): fetched the portal's page HTML +
> **104 jQuery JS files** (auth-free static assets), and extracted endpoints from source — not
> only quoted literals but also `baseUrl + …` concatenations, **ternary/variable path segments**
> (e.g. the `*Parallel` chart variants), backtick template URLs, `fetch()`/`downloadFile()`
> export calls, and HTML form `action=` targets. **No write/control/firmware endpoint was ever
> invoked**; the ~89 WRITE endpoints are inventoried from source only. Serials/plant-ids/
> user-ids obfuscated. Owner/installer/admin sections are only partially reachable as VIEWER, so
> the true portal surface is larger still.
>
> **Validation status.** The **KNOWN** endpoints are fully typed in `openapi.yaml`. The **NEW**
> endpoints here are **inventory** (path + method + param names from source); their request/
> response **schemas are not validated** except the 23 READ endpoints explicitly marked
> ✅ live-validated. Treat this as a discovery map, not a verified contract.
>
> Legend: `R/W` — READ / WRITE / PAGE (server-rendered). `KNOWN` = in the 44-endpoint
> `pylxpweb` subset; `NEW` = beyond it. `✅` = live-validated read (2026-07-15). `{param}` =
> path-parameter segment. `(q)` = query-string param.


## Live-validated READ endpoints (2026-07-15)

Confirmed to return a real typed JSON body via read-only calls; top-level response fields captured (values obfuscated). 21 are **NEW** (beyond `openapi.yaml`) and are candidates for promotion into the validated spec; the rest are already-KNOWN endpoints re-confirmed.

| Endpoint | Top-level response fields (sample) |
|---|---|
| `/WManage/api/battery/renon/getRenonBatteryRuntime` | `dormantCount`, `hasRuntimeData`, `lost`, `offlineCount`, `onlineCount`, `serialNum`, `success` |
| `/WManage/api/battery/renonAio/getRenonAioInfo` | `customVersionText`, `renonInDcdcModuleNumber`, `renonOutDcdcModuleNumber`, `renonSerialNum`, `renonSubBatNum`, `serialNum`, `success` |
| `/WManage/api/battery/renonAio/getRenonAioRuntime` | `renonSubBatArray`, `serialNum`, `success` |
| `/WManage/api/gen/exercise/getGenExerciseInfo` | `success`, `timezoneOffset` |
| `/WManage/api/inverter/getGenResetInfo` | `genWorkTimeText`, `success` |
| `/WManage/api/inverter/getInverterBatteryInfoParallel` | `batParallelNum`, `batShared`, `deviceArray`, `deviceCount`, `hasRuntimeData`, `lost`, `parallelEnabled`, `parallelGroup`, `parallelIndex`, `parallelModel`, `serialNum`, `success` |
| `/WManage/api/inverter/getInverterInfo` | `address`, `allowExport2Grid`, `batteryType`, `datalogSn`, `deviceInfo`, `deviceType`, `deviceTypeText`, `dtc`, `fwVersion`, `hardwareVersion`, `inverterDetail`, `lost` |
| `/WManage/api/inverter/getInverterRuntimeParallel` | `_12KAcCoupleInverterData`, `_12KAcCoupleInverterFlow`, `_12KUsingGenerator`, `_us_type6_phase3`, `batCapacity`, `batParallelNum`, `batPower`, `batShared`, `batteryColor`, `batteryType`, `bmsCharge`, `bmsDischarge` |
| `/WManage/api/inverter/queryEpsOverloadRecoveryTime` | `msg`, `success` |
| `/WManage/api/inverterOverview/list` | `rows`, `success`, `total` |
| `/WManage/api/micro/monitor/getPlantRuntimeInfo` | `powerTotalText`, `rows`, `success`, `totalStationCo2Text`, `totalYieldingStationText` |
| `/WManage/api/plant/getPlantInfo` | `address`, `continent`, `continentText`, `country`, `countryText`, `countrys`, `createDate`, `currencyUnit`, `currencyUnitSymbol`, `currencyUnitText`, `currentCountryIndex`, `currentRegionIndex` |
| `/WManage/api/plantOverview/list` | `rows`, `success`, `total` |
| `/WManage/api/system/cluster/search/findOnlineInverter` | `msg`, `success` |
| `/WManage/api/system/cluster/search/viewerFindOnlineDevice` | `msg`, `success` |
| `/WManage/api/tigo/getDeviceTigoInfo` | `success` |
| `/WManage/web/config/datalog/getDongleInfo` | `datalogType`, `datalogTypeText`, `firmwareVersion`, `success` |
| `/WManage/web/config/datalog/readInvInfo` | `msg`, `success` |
| `/WManage/web/config/inverter/list` | `currentPageSize`, `offlineNum`, `onlineNum`, `rows`, `showAutoParallelButton`, `total` |
| `/WManage/web/maintain/notification/showList` | `rows`, `success`, `total` |
| `/WManage/web/maintain/remoteSetRecord/list` | `rows`, `success`, `total` |
| `/WManage/web/maintain/standardUpdate/list` | `rows`, `success`, `total` |
| `/WManage/web/maintain/template/list` | `rows`, `success`, `total` |

## api: analyze  (16)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/api/analyze/chart/analyzeParallelChartData` | READ | NEW |  | - |
| POST | `/WManage/api/analyze/chart/dayLine` | READ | KNOWN |  | attr,dateText,serialNum |
| POST | `/WManage/api/analyze/chart/dayMultiLine` | READ | NEW |  | - |
| POST | `/WManage/api/analyze/chart/dayMultiLineParallel` | READ | NEW |  | ternary-concat: baseUrl + '/api/analyze/chart/dayMultiLine' + (showParallelData ? 'Parallel' : '') — js/monito |
| GET | `/WManage/api/analyze/energy/columnDataExport` | READ | NEW |  | backtick template literal (not a quoted literal): window.open(`${baseUrl}/api/analyze/energy/columnDataExport? |
| POST | `/WManage/api/analyze/energy/dayColumn` | READ | KNOWN |  |  |
| POST | `/WManage/api/analyze/energy/monthColumn` | READ | KNOWN |  |  |
| POST | `/WManage/api/analyze/energy/totalColumn` | READ | KNOWN |  |  |
| POST | `/WManage/api/analyze/energy/yearColumn` | READ | KNOWN |  |  |
| ? | `/WManage/api/analyze/event/list` | READ | KNOWN |  | - |
| POST | `/WManage/api/inverterChart/monthColumn` | READ | KNOWN |  | - |
| POST | `/WManage/api/inverterChart/monthColumnParallel` | READ | KNOWN |  | ternary-concat: baseUrl + '/api/inverterChart/monthColumn' + (showParallelData ? 'Parallel' : '') — js/monitor |
| POST | `/WManage/api/inverterChart/totalColumn` | READ | NEW |  | - |
| POST | `/WManage/api/inverterChart/totalColumnParallel` | READ | NEW |  | ternary-concat: baseUrl + '/api/inverterChart/totalColumn' + (showParallelData ? 'Parallel' : '') — js/monitor |
| POST | `/WManage/api/inverterChart/yearColumn` | READ | NEW |  | - |
| POST | `/WManage/api/inverterChart/yearColumnParallel` | READ | NEW |  | ternary-concat: baseUrl + '/api/inverterChart/yearColumn' + (showParallelData ? 'Parallel' : '') — js/monitor/ |

## api: battery  (6)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/battery/getBatteryInfo` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/battery/getBatteryInfoForSet` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/battery/removeBatteryRuntime` | WRITE | NEW |  | batterySn,serialNum |
| POST | `/WManage/api/battery/renon/getRenonBatteryRuntime` | READ | NEW | ✅ |  |
| POST | `/WManage/api/battery/renonAio/getRenonAioInfo` | READ | NEW | ✅ |  |
| POST | `/WManage/api/battery/renonAio/getRenonAioRuntime` | READ | NEW | ✅ |  |

## api: cluster/system  (5)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/system/cluster/search` | READ | NEW |  | - |
| POST | `/WManage/api/system/cluster/search/checkWarranty` | READ | NEW | · | serialNums |
| POST | `/WManage/api/system/cluster/search/findOnlineDatalog` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/system/cluster/search/findOnlineInverter` | READ | NEW | ✅ | serialNum |
| POST | `/WManage/api/system/cluster/search/viewerFindOnlineDevice` | READ | NEW | ✅ | plantId |

## api: forecast  (7)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/predict/solar` | READ | NEW |  | - |
| POST | `/WManage/api/predict/solar/dayPredictColumn` | READ | NEW |  | variable path-segment: const url = showParallelData?'dayPredictColumnParallel':'dayPredictColumn'; $.post(base |
| POST | `/WManage/api/predict/solar/dayPredictColumnParallel` | READ | KNOWN |  | variable path-segment (parallel branch of the ternary) — js/monitor/inverter/predictionChart.js:57-58 |
| POST | `/WManage/api/weather/forecast` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/weather/plant/clearLocation` | WRITE | NEW |  | plantId |
| POST | `/WManage/api/weather/plant/forecast/manual` | READ | NEW |  | country,inputLocation |
| POST | `/WManage/api/weather/plant/saveLocation` | WRITE | NEW |  | - |

## api: generator  (3)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/gen/exercise/clearGenExerciseInfo` | WRITE | NEW |  | serialNum |
| POST | `/WManage/api/gen/exercise/getGenExerciseInfo` | READ | NEW | ✅ | serialNum |
| POST | `/WManage/api/gen/exercise/updateGenExerciseInfo` | WRITE | NEW |  | dayOfWeekLocal,hourMinuteLocal,serialNum |

## api: gridboss  (4)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/midbox/genQuickStart` | WRITE | NEW |  | - |
| GET | `/WManage/api/midbox/genStatus` | READ | NEW |  | serialNum |
| POST | `/WManage/api/midbox/genStop` | WRITE | NEW |  | clientType,serialNum |
| POST | `/WManage/api/midbox/getMidboxRuntime` | READ | KNOWN |  | serialNum |

## api: integrations  (8)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/chargePoint/getChargePointRunTime` | READ | NEW | · | clientType,inverterSn |
| POST | `/WManage/api/chargePoint/realTime` | READ | NEW | · | inverterSn |
| GET | `/WManage/api/googleHome/getDeviceSetting` | READ | NEW | · | serialNum |
| POST | `/WManage/api/googleHome/saveDeviceSetting` | WRITE | NEW |  | - |
| POST | `/WManage/api/phnix/getData` | READ | NEW |  | - |
| POST | `/WManage/api/tigo/checkAuth` | READ | NEW |  | serialNum,tigoPassword,tigoUsername |
| POST | `/WManage/api/tigo/getDeviceTigoInfo` | READ | NEW | ✅ | serialNum |
| POST | `/WManage/api/tigo/updateDeviceTigoInfo` | WRITE | NEW |  | serialNum,systemId,tigoPassword,tigoUsername |

## api: inverter/device  (19)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/inverter/autoParallel` | WRITE | KNOWN |  | plantId |
| POST | `/WManage/api/inverter/ctrlBatteryBackup` | WRITE | NEW |  | clientType,enable,inverterSn |
| POST | `/WManage/api/inverter/ctrlGenExercise` | WRITE | NEW |  | clientType,enable,inverterSn |
| POST | `/WManage/api/inverter/ctrlGenResetTime` | WRITE | NEW |  | clientType,inverterSn |
| POST | `/WManage/api/inverter/getGenResetInfo` | READ | NEW | ✅ | inverterSn |
| ? | `/WManage/api/inverter/getInverterBatteryInfoParallel` | READ | NEW | ✅ | - |
| POST | `/WManage/api/inverter/getInverterEnergyInfo` | READ | KNOWN |  | - |
| POST | `/WManage/api/inverter/getInverterEnergyInfoParallel` | READ | KNOWN |  | ternary-concat suffix: baseUrl + '/api/inverter/getInverterEnergyInfo' + (showParallelData ? 'Parallel' : '')  |
| POST | `/WManage/api/inverter/getInverterInfo` | READ | KNOWN | ✅ |  |
| POST | `/WManage/api/inverter/getInverterRuntime` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/inverter/getInverterRuntimeParallel` | READ | NEW | ✅ | serialNum |
| POST | `/WManage/api/inverter/queryEpsOverloadRecoveryTime` | READ | NEW | ✅ | inverterSn |
| POST | `/WManage/api/inverter/transferData` | WRITE | NEW |  | fromClusterId,inverterSn |
| POST | `/WManage/api/inverter/updateAdvancedSettings` | WRITE | NEW |  | allowExport2Grid,inverterSn |
| POST | `/WManage/api/inverterOverview/clearParallel` | WRITE | NEW |  |  |
| POST | `/WManage/api/inverterOverview/editParallel` | WRITE | NEW |  |  |
| POST | `/WManage/api/inverterOverview/export` | READ | NEW |  |  |
| POST | `/WManage/api/inverterOverview/getParallelGroupDetails` | READ | KNOWN |  | serialNum |
| POST | `/WManage/api/inverterOverview/list` | READ | KNOWN | ✅ |  |

## api: microinverter  (2)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/micro/monitor/getInverterEnergyInfo` | READ | NEW |  |  |
| POST | `/WManage/api/micro/monitor/getPlantRuntimeInfo` | READ | NEW | ✅ |  |

## api: plant  (4)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/plant/getPlantInfo` | READ | NEW | ✅ | plantId |
| GET | `/WManage/api/plantOverview/export` | READ | NEW |  | searchText(q) |
| POST | `/WManage/api/plantOverview/list` | READ | NEW | ✅ |  |
| ? | `/WManage/api/plantOverview/list/viewer` | READ | KNOWN |  | - |

## api: user/prefs  (9)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/api/user/getUserAppNoticeInfo` | READ | NEW | · |  |
| POST | `/WManage/api/user/saveUserAppNoticeInfo` | WRITE | NEW |  |  |
| POST | `/WManage/api/user/transferViewerDeviceData2StandAlone` | WRITE | NEW |  |  |
| POST | `/WManage/api/userChartRecord/saveOrUpdateChartColor` | WRITE | NEW |  | - |
| POST | `/WManage/api/userChartRecord/saveUserChartRecord` | WRITE | NEW |  | - |
| ? | `/WManage/api/userFav/getUserFavPlantRecordList` | READ | NEW |  | clientType(q) |
| POST | `/WManage/api/userFav/removeUserFavPlantRecord` | WRITE | NEW |  | plantId |
| POST | `/WManage/api/userFav/saveUserFavPlantRecord` | WRITE | NEW |  | plantId,remarks |
| POST | `/WManage/api/userVisit/update` | WRITE | NEW |  | plantId,serialNum |

## auth/locale  (4)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/authCode` | READ | NEW |  | authCode |
| POST | `/WManage/locale` | WRITE | NEW |  | language |
| POST | `/WManage/locale/country` | READ | KNOWN |  | region |
| POST | `/WManage/locale/region` | READ | KNOWN |  | continent |

## web: analyze  (18)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/analyze/battery/renonData` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/chart` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/chartCompare` | PAGE | NEW |  | - |
| GET | `/WManage/web/analyze/chartCompareMidBox` | PAGE | NEW |  |  |
| ? | `/WManage/web/analyze/chartMidBox` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/data` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/data/export` | READ | NEW |  | - |
| GET | `/WManage/web/analyze/data/export/{serialNum}/{date}` | READ | NEW |  | mid-path variable segments passed to downloadFile()->fetch(): baseUrl + '/web/analyze/data/export/' + combogri |
| ? | `/WManage/web/analyze/data/export1` | READ | NEW |  | - |
| POST | `/WManage/web/analyze/data/{date}` | READ | NEW |  | mid-path variable segment (EasyUI datagrid url, defaults POST): baseUrl + '/web/analyze/data/' + selectDateTex |
| ? | `/WManage/web/analyze/energy` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/energy/exportData` | READ | NEW |  | serialNum(q) |
| ? | `/WManage/web/analyze/event` | PAGE | NEW |  | - |
| ? | `/WManage/web/analyze/event/export` | READ | NEW |  | eventText(q),plantId(q) |
| POST | `/WManage/web/analyze/event/remove` | WRITE | NEW |  | recordId |
| ? | `/WManage/web/analyze/localData` | PAGE | NEW |  | - |
| GET | `/WManage/web/analyze/localData/export` | READ | NEW |  |  |
| GET | `/WManage/web/analyze/localData/list` | READ | NEW |  |  |

## web: config  (35)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/config/datalog` | PAGE | NEW |  | - |
| POST | `/WManage/web/config/datalog/add` | WRITE | NEW |  | plantId,serialNum,verifyCode |
| POST | `/WManage/web/config/datalog/checkUpdates` | READ | NEW |  | - |
| POST | `/WManage/web/config/datalog/edit` | WRITE | NEW |  | plantId,serialNum |
| ? | `/WManage/web/config/datalog/export` | READ | NEW |  | - |
| POST | `/WManage/web/config/datalog/getAllFirmwares` | READ | NEW |  | datalogType |
| POST | `/WManage/web/config/datalog/getDongleInfo` | READ | NEW | ✅ | serialNum |
| ? | `/WManage/web/config/datalog/list` | READ | KNOWN |  | - |
| POST | `/WManage/web/config/datalog/readInvInfo` | READ | NEW | ✅ | serialNum |
| POST | `/WManage/web/config/datalog/removeWithPin` | WRITE | NEW |  | - |
| POST | `/WManage/web/config/datalog/updateFirmware` | WRITE | NEW |  | dongleFirmware,serialNum |
| ? | `/WManage/web/config/datalog/upload` | WRITE | NEW |  | - |
| ? | `/WManage/web/config/inverter` | PAGE | NEW |  | - |
| POST | `/WManage/web/config/inverter/bindChargePoint` | WRITE | NEW |  | chargePointSn,productType,serialNum |
| ? | `/WManage/web/config/inverter/bmsMinCellVoltExport` | READ | NEW |  | bmsMinCellVoltMin(q) |
| POST | `/WManage/web/config/inverter/clearBindConnection` | WRITE | NEW |  | serialNum |
| POST | `/WManage/web/config/inverter/getChargePointBySn` | READ | NEW | · | serialNum |
| ? | `/WManage/web/config/inverter/list` | READ | NEW | ✅ | - |
| POST | `/WManage/web/config/inverter/remove` | WRITE | NEW |  | serialNum |
| POST | `/WManage/web/config/inverter/updateUsedAtCustomerDate` | WRITE | NEW |  | password,serialNum,usedAtCustomerDate |
| ? | `/WManage/web/config/plant` | PAGE | NEW |  | - |
| ? | `/WManage/web/config/plant/edit` | WRITE | KNOWN |  | - |
| GET | `/WManage/web/config/plant/edit/{plantId}` | PAGE | NEW |  | dynamic href/window.open baseUrl+ edit page (web_config_plant.html:241,259, web_maintain_weatherSet.html:259) |
| POST | `/WManage/web/config/plant/editNotice` | WRITE | NEW |  | noticeEmail,noticeEmail2,noticeType,plantId |
| ? | `/WManage/web/config/plant/editPlantImage` | WRITE | NEW |  | - |
| GET | `/WManage/web/config/plant/editPlantImage/{plantId}` | PAGE | NEW |  | dynamic href baseUrl+ picture-edit page (web_config_plant.html:240) |
| ? | `/WManage/web/config/plant/export` | READ | NEW |  | - |
| ? | `/WManage/web/config/plant/exportInverterType` | READ | NEW |  | page(q) |
| ? | `/WManage/web/config/plant/list/viewer` | READ | KNOWN |  | - |
| POST | `/WManage/web/config/plant/remove` | WRITE | NEW |  | plantId |
| POST | `/WManage/web/config/quickCharge/getStatusInfo` | READ | KNOWN |  | inverterSn |
| POST | `/WManage/web/config/quickCharge/start` | WRITE | KNOWN |  | - |
| POST | `/WManage/web/config/quickCharge/stop` | WRITE | KNOWN |  | clientType,inverterSn |
| POST | `/WManage/web/config/quickDischarge/start` | WRITE | KNOWN |  | clientType,inverterSn |
| POST | `/WManage/web/config/quickDischarge/stop` | WRITE | KNOWN |  | clientType,inverterSn |

## web: inverter  (1)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/web/inverter/debugqna/startAnalyse` | WRITE | NEW |  | - |

## web: login  (3)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/login` | PAGE | NEW |  | - |
| ? | `/WManage/web/login/clusterLoginForward` | READ | NEW |  | clusterLoginKey(q) |
| ? | `/WManage/web/login/viewDemoPlant` | PAGE | NEW |  | customCompany(q) |

## web: logout  (1)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/logout` | PAGE | NEW |  | - |

## web: maintain  (72)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| GET | `/WManage/web/maintain` | PAGE | NEW |  |  |
| ? | `/WManage/web/maintain/battUpdate` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/battUpdate/run` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/notification/showList` | READ | NEW | ✅ | deviceType,page,rows |
| POST | `/WManage/web/maintain/readDatalogParam/read` | READ | NEW |  | datalogParam,datalogSn |
| POST | `/WManage/web/maintain/remoteRead/midDiff` | READ | NEW |  | inverterSn |
| POST | `/WManage/web/maintain/remoteRead/read` | READ | KNOWN |  | autoRetry,inverterSn,pointNumber,startRegister |
| POST | `/WManage/web/maintain/remoteRead/readInput` | READ | NEW |  | inverterSn |
| POST | `/WManage/web/maintain/remoteRead/readMultiBitParam` | READ | NEW |  | inverterSn |
| ? | `/WManage/web/maintain/remoteSet` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSet/bitModelParamControl` | WRITE | NEW |  | clientType,inverterSn,modelBitParam,remoteSetType,value |
| POST | `/WManage/web/maintain/remoteSet/bitParamControl` | WRITE | KNOWN |  | bitParam,clientType,inverterSn,remoteSetType,value |
| POST | `/WManage/web/maintain/remoteSet/functionControl` | WRITE | KNOWN |  | clientType,enable,functionParam,inverterSn,remoteSetType |
| POST | `/WManage/web/maintain/remoteSet/reset` | WRITE | NEW |  | clientType,inverterSn,remoteSetType,resetParam |
| POST | `/WManage/web/maintain/remoteSet/wattNode/read` | READ | NEW |  | inverterSn |
| POST | `/WManage/web/maintain/remoteSet/wattNode/write` | WRITE | NEW |  | inverterSn |
| POST | `/WManage/web/maintain/remoteSet/write` | WRITE | KNOWN |  | clientType,holdParam,inverterSn,remoteSetType,valueText |
| POST | `/WManage/web/maintain/remoteSet/writeG98ValueForINF01` | WRITE | NEW |  | clientType,inverterSn,remoteSetType |
| POST | `/WManage/web/maintain/remoteSet/writeModel` | WRITE | NEW |  | batteryType,inverterSn,leadAcidType,measurement,meterBrand,meterType,ruleMask,usVersion,wirelessMeter |
| POST | `/WManage/web/maintain/remoteSet/writeModelByDeviceType` | WRITE | NEW |  | clientType,deviceType,inverterSn,remoteSetType |
| POST | `/WManage/web/maintain/remoteSet/writeMultiBitParam` | WRITE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSet/writeMultiValue` | WRITE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSet/writePartModel` | WRITE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSet/writeTime` | WRITE | KNOWN |  | clientType,hour,inverterSn,minute,remoteSetType,timeParam |
| ? | `/WManage/web/maintain/remoteSet12K` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/remoteSetAllInOne` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSetBatt/multiResetControl` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/remoteSetBatt/writeMultiSocValue` | WRITE | NEW |  |  |
| ? | `/WManage/web/maintain/remoteSetLsp` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSetLsp/bitHoldControl` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/remoteSetLsp/bitHoldControlLspReg26` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/remoteSetLsp/writeMultiHoldValue` | WRITE | NEW |  |  |
| ? | `/WManage/web/maintain/remoteSetMidbox` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/remoteSetOffGrid` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/remoteSetRecord` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteSetRecord/export` | READ | NEW |  |  |
| POST | `/WManage/web/maintain/remoteSetRecord/list` | READ | NEW | ✅ |  |
| ? | `/WManage/web/maintain/remoteSetWeekly` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/remoteTransfer/export` | READ | NEW |  | exportType(q),serialNum(q) |
| POST | `/WManage/web/maintain/remoteTransfer/refreshInputData` | WRITE | NEW |  | inverterSn |
| POST | `/WManage/web/maintain/remoteTransfer/sendReadInputCommand` | WRITE | NEW |  | index,inverterSn |
| ? | `/WManage/web/maintain/remoteUpdate` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/remoteUpdate/cancel` | WRITE | NEW |  | serialNum,userId |
| ? | `/WManage/web/maintain/remoteUpdate/info` | READ | KNOWN |  | userId |
| ? | `/WManage/web/maintain/remoteUpdate/run` | WRITE | NEW |  | serialNums,tryFastMode,userId |
| ? | `/WManage/web/maintain/remoteUpdate/upload` | WRITE | NEW |  | - |
| POST | `/WManage/web/maintain/remoteWeeklyOperation/readValues` | READ | NEW |  | dynamic-concat: var urlSuffix='remoteRead/read'; if(startRegister>=500) urlSuffix='remoteWeeklyOperation/readV |
| POST | `/WManage/web/maintain/remoteWeeklyOperation/setValues` | WRITE | NEW |  |  |
| ? | `/WManage/web/maintain/setupWizard` | PAGE | NEW |  | serialNum(q) |
| ? | `/WManage/web/maintain/standardUpdate/check12KParallelStatus` | READ | KNOWN |  | serialNum,userId |
| POST | `/WManage/web/maintain/standardUpdate/checkUpdates` | READ | KNOWN |  | serialNum |
| ? | `/WManage/web/maintain/standardUpdate/list` | READ | NEW | ✅ | - |
| ? | `/WManage/web/maintain/standardUpdate/run` | WRITE | KNOWN |  | serialNum,tryFastMode,userId |
| POST | `/WManage/web/maintain/template/importTemplate` | WRITE | NEW |  | inverterSn,templateId |
| POST | `/WManage/web/maintain/template/list` | READ | NEW | ✅ | deviceType,dtc,machineType,odm,phase,powerRating,usVersion,voltClass |
| ? | `/WManage/web/maintain/weatherSet` | PAGE | NEW |  | - |
| POST | `/WManage/web/maintain/weatherSet/addDevice` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/weatherSet/disableDevice` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/weatherSet/edit` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/weatherSet/enableDevice` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/weatherSet/inverter/list` | READ | NEW |  | easyui datagrid url= attr (web_maintain_weatherSet.html:641) |
| POST | `/WManage/web/maintain/weatherSet/removeDevice` | WRITE | NEW |  |  |
| POST | `/WManage/web/maintain/weatherSet/setDetail/list` | READ | NEW |  | easyui datagrid url= attr (web_maintain_weatherSet.html:1196) |
| POST | `/WManage/web/maintain/weatherSet/setResult/viewerList` | READ | NEW |  | easyui datagrid url= attr (web_maintain_weatherSet.html:663) |
| GET | `/WManage/web/maintain/workingMode` | PAGE | NEW |  |  |
| ? | `/WManage/web/maintain/workingMode/12k` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/workingMode/eqb` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/workingMode/hybrid` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/workingMode/midbox` | PAGE | NEW |  | - |
| ? | `/WManage/web/maintain/workingMode/sna` | PAGE | NEW |  | - |
| GET | `/WManage/web/maintain/workingMode?serialNum={sn}` | PAGE | NEW |  | window.open baseUrl+ (web_maintain_remoteSet12K.html:519) |
| POST | `/WManage/web/maintain/writeDatalogParam/write` | WRITE | NEW |  | clientType,datalogParam,datalogSn,remoteSetType,valueText |

## web: monitor  (7)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/monitor/battery/zrgp` | PAGE | NEW |  | - |
| ? | `/WManage/web/monitor/battery/zrgpAio` | PAGE | NEW |  | - |
| ? | `/WManage/web/monitor/inverter` | PAGE | NEW |  | - |
| ? | `/WManage/web/monitor/lsp/inverter` | PAGE | NEW |  | serialNum(q) |
| ? | `/WManage/web/monitor/micro/inverter` | PAGE | NEW |  | - |
| POST | `/WManage/web/monitor/micro/inverter/getMicroDeviceLayoutRecordJsonData` | READ | NEW |  |  |
| POST | `/WManage/web/monitor/micro/inverter/save` | WRITE | NEW |  |  |

## web: overview  (3)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/overview/global` | PAGE | NEW |  | - |
| ? | `/WManage/web/overview/globalPlant` | PAGE | NEW |  | - |
| ? | `/WManage/web/overview/plant` | PAGE | NEW |  | autoSelectPlant(q) |

## web: register  (6)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| ? | `/WManage/web/register` | PAGE | NEW |  | - |
| POST | `/WManage/web/register/checkDatalogSnValidForRegister` | READ | NEW |  | datalogSn |
| POST | `/WManage/web/register/isAccountExist` | READ | NEW |  | account |
| POST | `/WManage/web/register/isCheckCodeMatch` | READ | NEW |  | checkCode,datalogSn |
| POST | `/WManage/web/register/isCustomerCodeExist` | READ | NEW |  | customerCode |
| ? | `/WManage/web/register/viewer` | WRITE | NEW |  | - |

## web: system  (18)

| Method | Endpoint | R/W | Known? | Live | Notes / params |
|---|---|---|---|---|---|
| POST | `/WManage/web/system/cluster/buildClusterKey` | WRITE | NEW |  | serverClusterId |
| POST | `/WManage/web/system/installer/pointDetail/list` | READ | NEW |  | easyui datagrid url= attr (web_system_user_userSet.html:1213) |
| POST | `/WManage/web/system/installer/revoke` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/serverEvent/save` | WRITE | NEW |  |  |
| ? | `/WManage/web/system/user` | PAGE | NEW |  | - |
| ? | `/WManage/web/system/user/center` | PAGE | NEW |  | - |
| POST | `/WManage/web/system/user/changeUserCustomerCode` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/user/changeUserTargetCluster` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/user/enable` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/user/getUseNewSettingPageValue` | READ | NEW |  | userId |
| ? | `/WManage/web/system/user/modifyPassword/{userId}` | READ | NEW |  | - |
| ? | `/WManage/web/system/user/preferences/{userId}` | READ | NEW |  | - |
| POST | `/WManage/web/system/user/remove` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/user/useNewSettingPage` | WRITE | NEW |  | useWorkingModePage,userId |
| ? | `/WManage/web/system/user/userSet` | PAGE | NEW |  | - |
| POST | `/WManage/web/system/userMigration/getRecords` | READ | NEW |  | easyui datagrid url= attr (web_system_user_userSet.html:1082) |
| POST | `/WManage/web/system/userMigration/save` | WRITE | NEW |  |  |
| POST | `/WManage/web/system/userQrcode/generate` | WRITE | NEW |  |  |

---

## Provenance & completeness

- Crawl date 2026-07-15, role VIEWER. 251 distinct endpoints from page HTML + 104 JS files.
- Extraction covered literal paths **and** indirect construction (ternary/variable path
  segments, backtick templates, `fetch()`/`downloadFile()` exports, form `action=` targets) —
  a completeness sweep across three independent static-analysis passes surfaced the `*Parallel`
  chart/energy/runtime variants, `predict/solar/dayPredictColumn(Parallel)`,
  `remoteWeeklyOperation/readValues`, `analyze/energy/columnDataExport`, and the export GETs
  that a quoted-literal scan alone missed.
- **Not covered (would need more roles / capture):** endpoints reachable only from
  owner/installer/admin pages a VIEWER account cannot load (some `system/*`, `installer/*`,
  `userMigration/*` write flows are seen in JS but their full param sets are role-gated); the
  mobile app's API (if it differs); and any endpoint invoked only by server-side redirects.
- **No write/control/firmware endpoint was invoked at any point.** The 89 WRITE
  endpoints are inventoried from JS source.
