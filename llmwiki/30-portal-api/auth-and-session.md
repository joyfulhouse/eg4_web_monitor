---
canonical-for:
  - EG4 portal authentication
  - JSESSIONID session lifecycle
  - pylxpweb reauthentication and request encoding
sources:
  - docs/api/openapi.yaml
  - docs/api/README.md
  - custom_components/eg4_web_monitor/__init__.py
  - custom_components/eg4_web_monitor/_config_flow/__init__.py
  - custom_components/eg4_web_monitor/cloud_requests.py
  - custom_components/eg4_web_monitor/cloud_session.py
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/coordinator_http.py
  - custom_components/eg4_web_monitor/diagnostics.py
  - joyfulhouse/pylxpweb/.gitignore
  - joyfulhouse/pylxpweb/src/pylxpweb/client.py
  - joyfulhouse/pylxpweb/src/pylxpweb/constants/api.py
  - joyfulhouse/pylxpweb/tests/integration/conftest.py
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Authentication and session lifecycle

## Non-negotiable wire contract

| Rule | Evidence |
|---|---|
| Authentication is an HTTP session cookie named `JSESSIONID`. It is **not** a bearer token, API key, or token returned in the login JSON. | `verified-against-code` `docs/api/openapi.yaml:29-35`; `pylxpweb/src/pylxpweb/client.py:818-835` |
| Login is `POST /WManage/api/login`. | `verified-against-code` OpenAPI path `/WManage/api/login`; `pylxpweb/src/pylxpweb/client.py:825` |
| The login body is `account=<username>&password=<password>&language=ENGLISH`. The password is sent as a normal form value over HTTPS; pylxpweb does not hash it first. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:818-825`; OpenAPI path `/WManage/api/login` |
| `aiohttp.ClientSession` owns the effective cookie jar and attaches the cookie to subsequent calls. `LuxpowerClient._session_id` is declared but never assigned and is not authentication state. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:107-119,818-835` |
| All JSON API operations are form-encoded POSTs. The sole method/response exception in the 44-path spec is the history export: GET returning binary `.xls`. | `verified-against-code` `docs/api/openapi.yaml:23-30`; `pylxpweb/src/pylxpweb/client.py:603-624`; `pylxpweb/src/pylxpweb/endpoints/export.py:183-202` |

Do not invent an `Authorization` header and do not serialize request parameters as JSON. `verified-against-code` `docs/api/openapi.yaml:23-35`; `pylxpweb/src/pylxpweb/client.py:603-624`

## Login costs three HTTP requests

One successful `LuxpowerClient.login()` normally performs the following request sequence. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:818-839,935-989`

| Order | Request | Why | Evidence |
|---:|---|---|---|
| 1 | `POST /WManage/api/login` | Establish `JSESSIONID`; parse `userId`, `role`, and the eager plant/inverter tree. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:818-835`; OpenAPI path `/WManage/api/login` |
| 2 | Role-selected plant list (`/plant/list` or `/plant/list/viewer`) | `_detect_account_level()` obtains plants immediately inside `login()`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:839,935-962`; `pylxpweb/src/pylxpweb/endpoints/plants.py:29-30,50-52` |
| 3 | `POST /WManage/api/inverterOverview/list` for the first plant | `_detect_account_level()` inspects `endUser` plus the login role to infer `guest`, `viewer`, `installer`, or `owner`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:962-979` |

Therefore, request-budget calculations must count a normal login or renewal as three portal requests, not one. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:839,956,962`

`INSTALLER` and `I_ASSISTANT` use `/WManage/web/config/plant/list`; other roles use `/WManage/web/config/plant/list/viewer`. `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/plants.py:29-30,50-52`; `pylxpweb/src/pylxpweb/client.py:933`

The account-level probe is deliberately best-effort: failures are caught and logged rather than invalidating an otherwise successful login. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:951-989`

## The “two-hour session” is not a server fact

| Statement | Grade and source |
|---|---|
| After login, pylxpweb locally sets `_session_expires = now + 2 hours`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:829` |
| No inspected response field communicates a server expiry time, and no repository-visible expiry negotiation exists. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:818-841`; OpenAPI schema `LoginResponse` |
| “Sessions last two hours” is therefore a **client-side guess**, useful only as a proactive refresh threshold. It must not be treated as the portal's authoritative TTL. | `inferred` from the preceding two code facts |
| The operational expiry signal is usually an HTML login page where JSON was expected; HTTP 401 is the other explicit signal. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:664-732` |

An expired-cookie response can still have HTTP 200. JSON parsing then raises `aiohttp.ContentTypeError`, which pylxpweb interprets as authentication expiry and routes through renewal. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:664-696`

## Renewal state machine

| Condition | Client action | Loop bound | Evidence |
|---|---|---:|---|
| Local two-hour timestamp has passed | `_ensure_authenticated()` renews before the request. | One shared login task | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:874-878` |
| Response body is HTML/wrong content type | Treat as expired session, renew, replay. | One renewal and one replay | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:664-696,746-774` |
| HTTP status is 401 | Renew, replay. | One renewal and one replay | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:698-732,746-774` |
| Replayed request is still unauthorized | Raise `LuxpowerAuthError("Session remained unauthorized after re-authentication")`. | No second replay | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:746-759` |

### Why concurrent expiry produces only one login

| Mechanism | Required interpretation | Evidence |
|---|---|---|
| Authentication generation counter | Each failed caller records the generation it observed. If another caller has already completed renewal and incremented the generation, the stale caller does not log in again. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:124,880-906` |
| Shared authentication task | Concurrent renewers await the same in-flight login task. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:880-921` |
| `asyncio.shield` | Cancelling one waiter cannot cancel the shared authentication task needed by other requests. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:880-921` |
| Context-local replay guard | `_reactive_authentication_replay` records that the current request chain already replayed, preventing an authentication loop. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:127-130,746-774` |

This is single-flight renewal: N concurrent expired requests may all observe failure, but they converge on one login generation and each original operation is replayed at most once. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:874-921`; concurrency coverage `pylxpweb/tests/unit/test_client_aioresponses.py:781-900,945-1058`

## Session ownership and isolation

| Client construction | Close behavior | Evidence |
|---|---|---|
| pylxpweb creates the `aiohttp.ClientSession` | `close()` drains/cancels in-flight authentication and closes the owned session, dropping its cookie jar. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:195-236` |
| Caller injects the session | `close()` does not close or clear the caller-owned session or cookie jar. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:211-236` |

Cookie-authenticated accounts on the same portal host must not share a domain-level cookie jar: each cloud-capable Home Assistant config entry creates its own private `ClientSession`/cookie jar, even when several entries reuse one account, and drains it before detach/close. `verified-against-code` `custom_components/eg4_web_monitor/coordinator.py:299-325,1048-1066`; `cloud_session.py` → `async_close_client_session`

There is no implemented portal logout, explicit cookie revocation, or password/token rotation operation in pylxpweb. Closing an owned session is the only repository-visible cookie-discard path. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:211-236,818-914`

## Credential-compromise incident procedure

Trigger this procedure when a portal password, `JSESSIONID`, credential-bearing configuration file, command line, log, screenshot, support bundle, or public commit is exposed or suspected exposed. Record the discovery time and source without copying the secret into another ticket or log, remove public access to the artifact, and assume it was copied before removal. `inferred` from the cookie/password authentication boundary above and the durable storage paths below

| Inventory target | What to inspect without echoing the secret | Evidence |
|---|---|---|
| Home Assistant configuration entries | Identify every HTTP or HYBRID entry whose `entry.data` uses the affected username and base URL. Home Assistant persists config-entry data under `.storage/core.config_entries`; use the UI/API rather than editing that file. | `verified-against-code` `custom_components/eg4_web_monitor/coordinator.py:299-315`; `_config_flow/__init__.py:824-841,1451-1452`; persistence filename `asserted-unverified` from the Home Assistant storage convention, with this repo's config-entry access as the durable artifact |
| pylxpweb development credentials | Inventory the pylxpweb repository root `.env`, `.env.local`, `.env.*.local`, process environment variables `LUXPOWER_USERNAME`/`LUXPOWER_PASSWORD`, and any private copies or backups of those files. Do not read values into logs. | `verified-against-code` `pylxpweb/tests/integration/conftest.py` (`env_path`, `LUXPOWER_USERNAME`, `LUXPOWER_PASSWORD`); `pylxpweb/.gitignore:60-62` |
| Automation and copies | Inventory CI/secret-manager entries, shell history, Home Assistant backups, browser password stores, and exported support artifacts that could contain the same password or cookie. Diagnostics currently redact username/password, but that does not prove every external artifact is clean. | Redaction `verified-against-code` `custom_components/eg4_web_monitor/diagnostics.py:31-45`; broader-copy inventory `inferred` from the two persisted credential locations above |
| Active sessions | Enumerate Home Assistant entries, browser profiles, scripts, and other clients logged into the affected portal account; each can hold a separate cookie. Entries sharing credentials have the same account blast radius even though each coordinator creates a separate private `ClientSession`/cookie jar. | `verified-against-code` `custom_components/eg4_web_monitor/coordinator.py:299-315,765-785`; `cloud_requests.py` → `CloudRequestLimiter` |

| Order | Required action | Verification and evidence |
|---:|---|---|
| 1 | **Contain:** disable or unload every affected Home Assistant config entry and stop affected scripts before rotation so they cannot create fresh sessions with the exposed password. Preserve one controlled pre-rotation browser session only if it is needed for the read-only invalidation check in step 5. | Entry unload closes the client and disposes its private cookie-bearing session. `verified-against-code` `custom_components/eg4_web_monitor/__init__.py` → `async_unload_entry`; `cloud_session.py` → `async_close_client_session` |
| 2 | **Rotate manually:** from a trusted device, sign in directly to the portal, open its account/profile password control, and set a new unique password. The repository does not document the UI route or expose a password-change API; if the control is unavailable, contact the portal account administrator or EG4 support instead of inventing an endpoint. | UI path and support workflow `asserted-unverified` (`docs/api/openapi.yaml` contains no account-password path; `pylxpweb/src/pylxpweb/client.py:818-914` contains no rotation call) |
| 3 | **Dispose local sessions and force reauthentication:** reload or re-enable every affected Home Assistant entry after the password change. After its private old cookie jar is disposed, setup uses the stored old password; a completed rotation makes that login fail and enter the integration's reauthentication flow. Enter the new password there: the flow validates it, updates `entry.data`, and reloads the entry. Close affected browser sessions and restart each script/client so no controlled old cookie jar remains. | `verified-against-code` `custom_components/eg4_web_monitor/coordinator_http.py:540-565`; `_config_flow/__init__.py:807-847`; `cloud_session.py` → `async_close_client_session`; rotation consequence `inferred` |
| 4 | **Verify credential revocation:** in a fresh private browser/client with no cookies, confirm the old password can no longer log in, then confirm the new password can. Do not test with a control write. | This proves password replacement, not cookie revocation. `inferred` from `/WManage/api/login` and the cookie boundary |
| 5 | **Test server-session invalidation separately:** use the one controlled pre-rotation session, if retained, for a read-only page/request after rotation. Whether password rotation invalidates existing server-side `JSESSIONID` sessions is **UNKNOWN until tested**; the two-hour client timestamp is not proof. | `asserted-unverified` (`pylxpweb/src/pylxpweb/client.py:829`; no logout/revocation path in `client.py:211-236,818-914`) |
| 6 | **Escalate if an old cookie still works:** keep affected integrations/scripts unloaded, delete controlled local cookies, and request account-wide session revocation from the portal administrator or EG4 support. Do not claim containment from password rotation alone. | Server-side manual revocation capability and response time `asserted-unverified` (`docs/api/openapi.yaml` has no revocation endpoint; no repository issue records a tested support flow) |

**Manual target:** the incident owner is the operator who controls both the portal account and the Home Assistant host. Begin immediately and target password rotation, controlled-session disposal, and the old-password negative test within **15 minutes** of confirmed disclosure; start vendor/admin escalation immediately if the controlled old-cookie test remains authorized. This is a local response target, not a server guarantee. `asserted-unverified` (operational policy recorded in `llmwiki/30-portal-api/auth-and-session.md`)

## Encoding details agents routinely get wrong

| Detail | Correct behavior | Evidence |
|---|---|---|
| Content type | `application/x-www-form-urlencoded; charset=UTF-8`; `Accept: application/json`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:603-609` |
| aiohttp call | Pass a flat mapping as `data=...`; do not pass `json=...`. | `verified-against-code` `pylxpweb/src/pylxpweb/client.py:622` |
| Most booleans | Explicit lower-case strings, for example `"true"` and `"false"`. | `verified-against-code` `docs/api/openapi.yaml:23-28` and endpoint call sites |
| `autoRetry`, `daylightSavingTime` | Passed as Python booleans, so aiohttp form-encodes `True`/`False`; the documented client behavior relies on the portal accepting that capitalization. | `verified-against-code` `docs/api/openapi.yaml:23-28`; `pylxpweb/src/pylxpweb/endpoints/control.py:145-150`; `pylxpweb/src/pylxpweb/endpoints/plants.py:310-364` |
| Nested mappings | Never put a mapping inside a form value. The historical raw-write body encoded the inner mapping opaquely and silently dropped the intended values. | `verified-against-code` `pylxpweb/src/pylxpweb/endpoints/control.py:292-305` |
| Export | Use `GET /WManage/web/analyze/data/export/{serialNum}/{startDate}` with optional `endDateText` query parameter and parse the binary workbook separately. | `verified-against-code` OpenAPI export path; `pylxpweb/src/pylxpweb/endpoints/export.py:183-231` |

## Login failure boundaries

`login()` retries only `LuxpowerConnectionError`, with exponential delay and `MAX_LOGIN_RETRIES = 3`; authentication rejection and application errors are surfaced immediately. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:843-872`; `pylxpweb/src/pylxpweb/constants/api.py:38`

This separation matters to Home Assistant: a temporary network failure must not be converted into a bad-credentials repair flow. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:686-687,843-872`

For application-error retry rules and the absence of HTTP 429 handling, see `errors.md`. `verified-against-code` `pylxpweb/src/pylxpweb/client.py:626-655,698-744`
