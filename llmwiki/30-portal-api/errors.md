---
canonical-for:
  - EG4 portal error envelopes
  - pylxpweb retry and backoff behavior
  - EG4 cloud request throttling and cache policy
sources:
  - docs/api/openapi.yaml
  - docs/api/README.md
  - CHANGELOG.md
  - custom_components/eg4_web_monitor/cloud_requests.py
  - custom_components/eg4_web_monitor/coordinator.py
  - joyfulhouse/pylxpweb/src/pylxpweb/client.py
  - joyfulhouse/pylxpweb/src/pylxpweb/constants/api.py
  - joyfulhouse/pylxpweb/src/pylxpweb/exceptions.py
  - joyfulhouse/pylxpweb/tests/integration/test_control_operations.py
  - joyfulhouse/pylxpweb/tests/integration/test_get_operations.py
  - joyfulhouse/pylxpweb/tests/unit/test_transient_error_retry.py
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-08
---

# Errors, retries, rate control and readback limits

## HTTP 200 can be failure

Portal application errors normally arrive as an HTTP 200 JSON envelope with `success:false`; HTTP status alone does not identify success. `verified-against-code` `docs/api/openapi.yaml:34-39`; `pylxpweb/src/pylxpweb/client.py:626-655`

```json
{"success": false, "message": "REMOTE_SET_ERROR"}
```

The example is a known envelope shape and known firmware-rejection message. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:626-655`; `portal-correlated` `CHANGELOG.md` issues #316/#331

| Parsing rule | Behavior | Evidence |
|---|---|---|
| `success` is explicitly `false` | Treat as application failure even when status is 200. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:626-655` |
| `success` is absent | Default to **true** via `json_data.get("success", True)`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:627` |
| Error text | Select `message`, then `msg`, then a diagnostic containing the full response. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:628-631` |
| Terminal application error | Raise `LuxpowerAPIError("API error (HTTP <status>): <message>")`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:655` |

Do not “tighten” the absent-`success` default without endpoint-by-endpoint evidence: several portal responses are legitimate data structures rather than a uniform success envelope. `inferred` from the verified default and raw-dictionary endpoint behavior in `pylxpweb/src/pylxpweb/endpoints/analytics.py`, `forecasting.py`, and `plants.py`

## Retry classification

Only five portal-message fragments are transient. Matching is substring-based. `verified-against-code` `pylxpweb/src/pylxpweb/constants/api.py:42-48`; `client.py:634-652`

| Transient fragment | Interpretation | Retry behavior | Evidence |
|---|---|---|---|
| `DATAFRAME_TIMEOUT` | Device dataframe communication timed out. | Retry with exponential backoff. | `verified-against-code` `constants/api.py:42-48`; `client.py:634-652` |
| `TIMEOUT` | Generic timeout message. | Retry with exponential backoff. | `verified-against-code` same |
| `BUSY` | Busy message, also matching busy-like prose by substring. | Retry with exponential backoff. | `verified-against-code` same |
| `COMMUNICATION_ERROR` | Portal-to-device communication failure. | Retry with exponential backoff. | `verified-against-code` same |
| `DEVICE_BUSY` | Device is processing another request. | Retry with exponential backoff. | `verified-against-code` same |

The client allows `MAX_TRANSIENT_ERROR_RETRIES = 3`, meaning one initial request plus as many as three retries for a matching portal-message error. `verified-against-code` `pylxpweb/src/pylxpweb/constants/api.py:32-48`; `pylxpweb/tests/unit/test_transient_error_retry.py:103-125`

### `apiBlocked`

`apiBlocked` is a portal application message carried as HTTP 200 JSON with `success:false`; the locked unit-test shape is `{"success":false,"msg":"apiBlocked"}`. pylxpweb classifies it as non-transient, raises `LuxpowerAPIError` immediately, and makes exactly one request. `verified-against-code` `pylxpweb/tests/unit/test_transient_error_retry.py` → `test_is_not_transient_error_api_blocked`, `test_non_transient_error_not_retried`

Live-test handling associates `apiBlocked` with an account that lacks permission for remote parameter reads or writes. The repository does **not** establish that it is an HTTP-rate quota signal, so do not treat it as equivalent to 429. `portal-correlated` `pylxpweb/tests/integration/test_get_operations.py:103-113`; `test_control_operations.py:153-163`

A caller should stop retrying the operation, surface a permission/account-level error, and require the operator to use an account authorized for that parameter action. Reauthentication with the same account is not a demonstrated remedy. `inferred` from the terminal classification and permission-correlated integration handling above

## `REMOTE_SET_ERROR` is terminal firmware rejection

| Wire outcome | Meaning | Client action | Evidence |
|---|---|---|---|
| HTTP 200, `success:false`, `message` or `msg` contains `REMOTE_SET_ERROR` | Firmware rejected or does not support the named write for that device/family. | Raise `LuxpowerAPIError`; **do not retry** because the message is not transient. | `portal-correlated` issues #316/#331 in `CHANGELOG.md`; `verified-against-code` transient set in `constants/api.py:42-48` |
| HTTP 200, `success:false`, one of the five transient fragments | Temporary busy/communication failure. | Retry up to the configured bound. | `verified-against-code` `client.py:634-652` |
| Successful write envelope | Portal accepted the named operation. | Invalidate relevant cache; no automatic cloud hardware readback follows. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:210-219,271-280` |

Repeatedly retrying `REMOTE_SET_ERROR` cannot turn a family-incompatible parameter into a supported one and adds portal load. `inferred` from the verified terminal classification and portal-correlated family rejection evidence

## ACK is not semantic proof

A write aimed at the wrong function bit can still be acknowledged. In the documented off-grid green-mode incident, the server/firmware accepted the write even though the inferred bit identity was wrong; reading through the same interpreted path could not expose that semantic mismatch. `portal-correlated` `CHANGELOG.md:166` and issue #476

Therefore, an ACK or success envelope proves request acceptance, not that the intended physical feature changed. A name-to-register or bit mapping requires an independent delta test against the intended behavior: capture baseline, write, observe the target state through an independent source, and restore. `inferred` from the portal-correlated wrong-bit incident and verified absence of automatic cloud readback

Cloud cache invalidation is likewise not verification. It merely forces a later fetch. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:210-219,271-280`

## Authentication and transport errors are different classes

| Situation | Wire symptom | Result | Retry/repair boundary | Evidence |
|---|---|---|---|---|
| Expired session | HTTP 200 HTML login page causes `aiohttp.ContentTypeError` | Authentication renewal and once-only replay | A second unauthorized result raises `LuxpowerAuthError`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:664-696,746-774` |
| Unauthorized session | HTTP 401 | Same renewal/replay path | Once only. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:698-732,746-774` |
| Forbidden | HTTP 403 | `LuxpowerAPIError("HTTP 403: ...")` | No reauthentication branch and no immediate retry. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:698-744` |
| Too many requests | HTTP 429 | `LuxpowerAPIError("HTTP 429: ...")` | No `Retry-After` handling and no immediate retry. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:698-744` |
| Network failure | `aiohttp.ClientError` | `LuxpowerConnectionError` | Login retries only connection failures; HA should not treat them as bad credentials. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:680-687,843-872` |
| Other non-success HTTP status | `ClientResponseError` | `LuxpowerAPIError` with HTTP status/message | Not an auth replay unless status is 401. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:698-744` |
| Response validates at HTTP/request layer but fails endpoint model validation | Pydantic schema error after `_request()` returns | `pydantic.ValidationError` can escape | Not translated to a portal exception. | `verified-against-code` endpoint `model_validate` calls, for example `endpoints/control.py:210-213` |

The exception hierarchy is `LuxpowerError` with API, authentication, connection, and device branches; `LuxpowerDeviceOfflineError` derives from the device branch. `verified-against-code` `pylxpweb/src/pylxpweb/exceptions.py:6-27`

`LuxpowerAPIError` has no structured `status`, response, or headers attribute. HTTP 403 and 429 therefore have the same public exception type and are **not robustly distinguishable through pylxpweb's structured API**; the numeric status survives only in the exception text and in the chained private `aiohttp.ClientResponseError`. Parsing `str(error)` or inspecting `error.__cause__` is possible but is not a stable typed contract. The request telemetry counts both requests without status-specific counters. `verified-against-code` `pylxpweb/src/pylxpweb/exceptions.py` → `LuxpowerAPIError`; `client.py:342-394,698-744`

## There is no HTTP 429 handling

No HTTP 429 constant, `Retry-After` parser, or rate-limit-specific branch exists in the inspected pylxpweb request path. `verified-against-code` exhaustive `429`/`TOO_MANY` search; `pylxpweb/src/pylxpweb/client.py:698-744`; `constants/api.py:32-48`

No observed server-side 429 behavior is established by the durable repository evidence. Treat any claim about the portal's actual quota or reset window as unverified. `asserted-unverified` (`docs/api/README.md:471-486`; no 429 fixture or branch in `pylxpweb/src/pylxpweb/client.py`)

The implemented rate strategy is client-side self-restraint; `apiBlocked` is a separate terminal application message whose relationship to rate quotas is not established. `inferred` from the absence of 429 logic and the verified mechanisms below

### Client-side controls

| Control | Value / behavior | Evidence |
|---|---|---|
| Cloud poll floor | `min_poll_interval_seconds = 30.0`; local Modbus is 1.0 seconds. | `verified-against-code` `pylxpweb/src/pylxpweb/transports/capabilities.py:74-75,95` |
| Error backoff | Base 1.0 second, factor 2.0, maximum 60.0 seconds, jitter 0.1. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:145-150`; `constants/api.py:27-30` |
| Backoff scope | Applies before the next request after any recorded request error, not only rate-limit-like failures; resets after success. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:396-435,601` |
| Device discovery cache | 15 minutes. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:135` |
| Battery info cache | **60 seconds**; the stale prose conflict is owned by the [divergence ledger](./schemas-and-scaling.md#verified-divergence-ledger). | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:136` |
| Parameter read cache | 2 minutes. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:137` |
| Quick-charge status cache | 1 minute. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:138` |
| Runtime, energy and MID caches | 20 seconds each. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:139-141` |
| Unlisted cache-key default | 30 seconds. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:452` |
| Hour-boundary flush | The first request after the local hour changes clears the whole response cache, protecting date-bucketed energy from stale rollover values. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:580-591`; purpose `inferred` |
| Request telemetry | Tracks per-minute, last-hour, densest 60-second rate and today's calls; it observes but does not enforce a quota. Cache hits are not counted. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:342-394,159-162` |

### Hour-boundary thundering-herd exposure and bound

The hour change clears every response-cache key in each pylxpweb client. The cache has no per-key single-flight and the flush adds no jitter, so concurrent coordinator work immediately after the boundary can turn many formerly cached operations into queued calls against a vendor portal the integration treats as rate-sensitive. Multiple config entries using the same account can synchronize on the same boundary; the actual vendor quota remains unknown. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:440-532,580-598`; herd consequence and rate-risk classification `inferred`

The Home Assistant integration bounds that exposure with a semaphore of **3 request chains**, shared per normalized `(username, base_url, verify_ssl)` key; see [Intervals, throttles and caches](../10-integration/data-flow-by-mode.md#6-intervals-throttles-and-caches). The limiter is re-entrant for pylxpweb's recursive retry/reauthentication calls, so one admitted chain keeps one slot instead of deadlocking on reacquisition. `verified-against-code` `custom_components/eg4_web_monitor/cloud_requests.py` → `SharedCloudRequestBudget`, `CloudRequestLimiter`, `acquire_shared_cloud_request_budget`; `coordinator.py:765-785`

For one Home Assistant process and one exact account key, the instantaneous admitted-chain bound is `C <= 3`. This caps concurrency, **not total post-flush calls**: every distinct cache miss may still queue, each normal login costs three sequential portal requests, and separate Home Assistant processes or direct pylxpweb clients do not share this semaphore. The limiter therefore contains the herd but does not prove compliance with an unknown vendor quota. `verified-against-code` limiter sources above and `pylxpweb/src/pylxpweb/client.py:818-839,935-989`; conclusion `inferred`

The 30-second transport floor and 20-second runtime cache are separate layers: the transport capability prevents the cloud polling cadence from being set below 30 seconds even though an individual cached response has a shorter TTL. `verified-against-code` `pylxpweb/src/pylxpweb/transports/capabilities.py:74-75`; `client.py:139-141`; `inferred` interaction statement

Login amplifies traffic because account-level detection adds plant and device requests; budget three calls per normal login/renewal. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:839,935-989`

## Decision table for callers

| Observed result | Safe classification | Caller behavior | Evidence |
|---|---|---|---|
| `success:false`, `REMOTE_SET_ERROR` | Terminal parameter/firmware rejection | Surface and family-gate; no automatic retry. | `portal-correlated` issues #316/#331; `inferred` caller rule |
| `success:false`, one of five transient fragments | Temporary portal/device communication problem | Let pylxpweb perform its bounded retries; do not add an unbounded outer retry. | `verified-against-code` `client.py:634-652`; `inferred` outer-loop rule |
| `success:false`, `apiBlocked` | Terminal permission-correlated application block | Stop; surface account-level/permission remediation. Do not retry or map it to 429. | `verified-against-code` `test_transient_error_retry.py` → `test_non_transient_error_not_retried`; interpretation `portal-correlated` integration tests cited above |
| HTTP 200 HTML or 401 | Expired/invalid session | Let the single-flight renewal path perform one replay. | `verified-against-code` `client.py:664-732,746-774` |
| HTTP 403 | Forbidden, non-auth-replay HTTP failure | Surface `LuxpowerAPIError`; no automatic retry. It is not structurally distinguishable from 429 by exception type. | `verified-against-code` `client.py:698-744`; `exceptions.py` → `LuxpowerAPIError` |
| HTTP 429 | Too-many-requests, but unsupported as a special case | Surface `LuxpowerAPIError`; no `Retry-After` semantics. It is not structurally distinguishable from 403 by exception type. | `verified-against-code` `client.py:698-744`; `exceptions.py` → `LuxpowerAPIError` |
| Success ACK after control write | Accepted request only | Do not claim the intended feature changed without independent evidence. | `portal-correlated` wrong-bit incident #476; `inferred` caller rule |
| Partial offline JSON | Valid degraded data | Preserve the object and mark missing metrics unavailable; do not turn it into an all-entity failure. | `portal-correlated` issues #256/#479; `verified-against-code` optional fields in `models.py:458-465,706-755,1023-1035` |
