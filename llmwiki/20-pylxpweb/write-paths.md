---
canonical-for: pylxpweb cloud, local, hybrid, and schedule write routing and verification
sources:
  - pylxpweb@204b95d:src/pylxpweb/endpoints/control.py
  - pylxpweb@204b95d:src/pylxpweb/transports/
  - pylxpweb@e53b16b:tests/unit/endpoints/test_control_helpers.py
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Write paths

Evidence grades follow the [canonical llmwiki legend](../README.md). Assume partial application unless a cited row proves one contiguous local frame.

## Routing matrix

| Caller/path | Route | Atomicity / verification | Evidence |
|---|---|---|---|
| `client.api.control.write_parameter(...)` | Cloud named `holdParam` / `valueText` form | One portal request; success invalidates cache but does not read back | `verified-against-code` — `src/pylxpweb/endpoints/control.py:164-219` |
| `client.api.control.write_time_parameter(...)` | Cloud named schedule boundary with hour/minute in one `writeTime` request | Atomic for one boundary, not for the whole start/end window | `verified-against-code` — `src/pylxpweb/endpoints/control.py:221-280`, `src/pylxpweb/endpoints/control.py:1635-1654` |
| `client.api.control.write_parameters(dict[int, int])` | Resolve raw addresses to flat named cloud writes, then send sequentially | Resolve-all-before-write prevents an unsafe mapping from causing initial side effects; later network/portal failure can leave earlier values applied | `verified-against-code` — `src/pylxpweb/endpoints/control.py:282-351` |
| `HTTPTransport.write_named_parameters(dict[str, Any])` | Booleans use `control_function`; other values use `write_parameter(str(value))`, one name per request | Multi-key call is non-atomic and can partially apply | `verified-against-code` — `src/pylxpweb/transports/http.py:423-494` |
| Local `write_named_parameters` | Resolve family names, then lock-held read-modify-write for shared bitfield registers | Same-register bit changes combine into one raw register write | `verified-against-code` — `src/pylxpweb/transports/protocol.py:551-630` |
| Local `write_parameters(dict[int, int])` | Sort addresses; FC06 for one register, FC16 for a contiguous run | Each contiguous run is one frame; separate noncontiguous runs can partially apply | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:1572-1618`, `src/pylxpweb/transports/_modbus_base.py:339-352` |
| `HybridTransport` writes | Try local while its local-failure latch permits; on typed local failure, fall back to HTTP | A failed local multi-run operation may already have applied an earlier run before cloud fallback | `inferred` — `src/pylxpweb/transports/hybrid.py:102-173`, `src/pylxpweb/transports/hybrid.py:315-380`, `src/pylxpweb/transports/_register_data.py:1610-1618` |

## Historical cloud raw-register defect

Before the named-write rewrite, `write_parameters` put `{register: value}` under a form field named `data`. `verified-against-code` — `pylxpweb@e53b16b^:src/pylxpweb/endpoints/control.py:259-269`.

The fix commit records that `aiohttp` serialized the nested mapping as repeated `data=<register>` fields with values dropped, that the portal silently no-op'd, and that cloud raw-register writes had never worked; the durable artifact does not include the captured HTTP body or portal response. `asserted-unverified` — `pylxpweb commit e53b16be26f86c5c614f8ed4370ff5cc38cc9187`.

Do not resurrect a supposed portal “batch raw register” endpoint. The current code sends flat named `holdParam` / `valueText` fields. `verified-against-code` — `src/pylxpweb/endpoints/control.py:164-219`, `src/pylxpweb/endpoints/control.py:282-351`.

## Current cloud raw-address compatibility adapter

`write_parameters(inverter_sn, parameters)` is a compatibility adapter, not a raw batch write. `verified-against-code` — `src/pylxpweb/endpoints/control.py:282-351`.

| Stage | Required behavior | Failure behavior | Evidence |
|---|---|---|---|
| 1. Resolve | Resolve every address into exactly one `(holdParam, valueText)` before the first request. | Any unsafe address raises before any write. | `verified-against-code` — `src/pylxpweb/endpoints/control.py:334-342` |
| 2. Reject ambiguity | Reject packed schedule addresses, unmapped addresses, multi-name/bitfield registers, canonical bit rows, and signed registers whose negative portal encoding is not proven. | Reject rather than guess. | `verified-against-code` — `src/pylxpweb/endpoints/control.py:353-418` |
| 3. Scale | Prefer canonical holding scale; otherwise use only the explicit divide-by-ten fallback sets. | Do not apply a universal scale. | `verified-against-code` — `src/pylxpweb/endpoints/control.py:420-439` |
| 4. Write | Call the singular named `write_parameter` in input iteration order. | Stop on first `success=False`; earlier successes remain applied. | `verified-against-code` — `src/pylxpweb/endpoints/control.py:344-351` |

Examples: raw `595` for a divisor-10 register becomes portal string `"59.5"`; a signed negative raw register is refused because the portal may want either `"-1"` or `"65535"` and that encoding is unverified. `verified-against-code` — `src/pylxpweb/endpoints/control.py:409-438`.

## Local named and raw writes

| Concern | Behavior | Evidence |
|---|---|---|
| Unknown name | Raise `ValueError`. | `verified-against-code` — `src/pylxpweb/transports/protocol.py:558-560` |
| Placeholder `FUNC_<reg>_BIT<n>` | Decode-only; refuse writes because the function is not hardware-verified. | `verified-against-code` — `src/pylxpweb/transports/protocol.py:562-567` |
| Disputed mapping | Refuse the write rather than risk changing a different setting that firmware would still ACK. | `verified-against-code` — `src/pylxpweb/transports/protocol.py:569-575` |
| Ordinary/compound bitfield | Read current value, mask/update only requested bits, validate multi-bit width, then write one combined register value. | `verified-against-code` — `src/pylxpweb/transports/protocol.py:591-629` |
| Raw address runs | Sort and group only consecutive addresses. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:1589-1612` |
| Modbus response | Validate response object; do not perform independent readback. | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:341-367` |
| Dongle ACK | Validate serial/function/start address and exact echoed FC06 value or FC16 register count. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1420-1461` |

## Dongle retry and diagnostic readback

| Rule | Consequence | Evidence |
|---|---|---|
| Never replay the same raw write packet merely because its ACK was lost. | The inverter may already have applied it; stale replay could overwrite a concurrent bitfield change. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1401-1418` |
| Named-write retries reconnect and rerun the whole sequence, including a fresh register read before recomputing the RMW. | Retry does not reuse stale bitfield state. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1565-1638` |
| Optional readback is skipped when more than three distinct registers would be read. | Absence of readback does not change the ACK result. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1682-1714` |
| Readback failure or mismatch is diagnostic only. | Accept the ACKed write; do not rewrite to fight firmware clamping/rounding or a concurrent portal/group writer. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1640-1675` |

Dongle readback is **diagnostic, not corrective**. A mismatch is not authorization to write repeatedly until the observed value matches. `verified-against-code` — `src/pylxpweb/transports/dongle.py:1662-1675`.

## Partial-application matrix

| Operation | Can partially apply? | Boundary | Evidence |
|---|---:|---|---|
| Cloud multi-parameter write | Yes | One named portal request per value; earlier success survives later failure | `verified-against-code` — `src/pylxpweb/endpoints/control.py:344-351` |
| HTTP named multi-write | Yes | One function/value request per dictionary entry | `verified-against-code` — `src/pylxpweb/transports/http.py:423-494` |
| Noncontiguous local raw write | Yes | One FC06/FC16 operation per contiguous run | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:1591-1618` |
| Contiguous local raw write | No partiality within pylxpweb's requested run | One FC16 frame, except a one-register run uses FC06 | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:1591-1612`, `src/pylxpweb/transports/_modbus_base.py:339-352` |
| Cloud classic schedule window | Yes | Four named writes: start hour/minute, end hour/minute | `verified-against-code` — `src/pylxpweb/endpoints/control.py:1656-1687` |
| Cloud `writeTime` schedule window | Yes | Each boundary is atomic, but start and end are two requests | `verified-against-code` — `src/pylxpweb/endpoints/control.py:1635-1654` |
| Local schedule window | Yes | Code sends start and end as separate FC06 requests and documents firmware rejection of FC16 for these registers | `verified-against-code` — `src/pylxpweb/devices/inverters/hybrid.py:352-363` |

Cache invalidation is not verification. Cloud writes trust `SuccessResponse`; Modbus trusts its response; only the dongle adds strict ACK echo validation plus optional non-fatal diagnostic readback. `verified-against-code` — `src/pylxpweb/endpoints/control.py:210-219`, `src/pylxpweb/transports/_modbus_base.py:341-367`, `src/pylxpweb/transports/dongle.py:1420-1461`, `src/pylxpweb/transports/dongle.py:1640-1675`.
