---
canonical-for: pylxpweb local Modbus TCP and WiFi dongle transport behavior
sources:
  - pylxpweb@204b95d:src/pylxpweb/transports/
  - pylxpweb@204b95d:src/pylxpweb/registers/battery.py
  - pylxpweb@204b95d:tests/unit/transports/
verified-against:
  pylxpweb: 204b95d
last-verified: 2026-08-08
---

# Local transports

Evidence grades follow the [canonical llmwiki legend](../README.md). Do not generalize one transport's wire behavior to another.

## Transport comparison

| Property | Modbus TCP | WiFi dongle | Evidence |
|---|---|---|---|
| Wire protocol | Standard Modbus TCP MBAP/PDU through `pymodbus` | Proprietary LuxPower `A1 1A` TCP envelope around an embedded Modbus data frame | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:167-209`, `src/pylxpweb/transports/dongle.py:1-10`, `src/pylxpweb/transports/dongle.py:545-624` |
| Default port | `502` | `8000` | `verified-against-code` — `src/pylxpweb/transports/factory.py:357-366`, `src/pylxpweb/transports/factory.py:436-445` |
| Reads | FC03 holding, FC04 input | Embedded FC03/FC04 | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:167-220`, `src/pylxpweb/transports/dongle.py:56-77`, `src/pylxpweb/transports/dongle.py:1293-1367` |
| Writes | FC06 single, FC16 multiple | Embedded FC06/FC16 | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:316-367`, `src/pylxpweb/transports/dongle.py:56-77`, `src/pylxpweb/transports/dongle.py:1380-1461` |
| Concurrency | Operations are guarded inside this process; external gateway clients are outside those locks | One serialized request/response workflow over the dongle's transaction lock | `verified-against-code` — `src/pylxpweb/transports/modbus.py:46-55`, `src/pylxpweb/transports/dongle.py:247-254`, `src/pylxpweb/transports/dongle.py:1467-1481` |

The upstream README instructs operators to run one active application/client per gateway or dongle, but the cited artifact contains no qualifying raw before/after observation. `asserted-unverified` — `pylxpweb@204b95d:README.md:67-69`.

## Modbus TCP

| Behavior | Agent constraint | Evidence |
|---|---|---|
| `connect()` constructs `AsyncModbusTcpClient(host, port, timeout, retries=pymodbus_retries)`, connects, installs the transaction-ID compatibility hook, and resets error state. | Do not rely on the stale docstring's claimed synchronization read; no synchronization read occurs. | `verified-against-code` — `src/pylxpweb/transports/modbus.py:145-180` |
| FC03/FC04 calls use `device_id=unit_id`. | Preserve the unit ID and distinguish holding from input reads. | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:167-220` |
| FC06 is used for one value; FC16 is used for a contiguous list. | Schedule code sends start and end as separate one-register calls, so local Modbus and dongle transports issue two FC06 writes. | `verified-against-code` — `src/pylxpweb/devices/inverters/hybrid.py:352-363`, `src/pylxpweb/transports/_register_data.py:1589-1611`, `src/pylxpweb/transports/_modbus_base.py:339-352`, `src/pylxpweb/transports/dongle.py:1387-1393` |
| Short holding reads fail inside the retry loop; short input reads pass upward for coalescing/BMS fallback policy. | Do not make both paths uniformly strict or uniformly permissive. | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:222-237` |
| Modbus writes validate the response but do not read the register back. | An accepted response is not independent readback proof. | `verified-against-code` — `src/pylxpweb/transports/_modbus_base.py:341-367` |

The schedule implementation comment attributes those separate writes to firmware rejection of FC16, but no raw rejection capture establishes that hardware behavior. `asserted-unverified` — `pylxpweb@204b95d:src/pylxpweb/devices/inverters/hybrid.py:352-363`. See the [hardware evidence boundary](../40-hardware/registers.md#schedule-write-evidence-boundary).

### Intentional Waveshare transaction-ID workaround

The upstream source states that Waveshare TCP-to-RTU gateways can replace the MBAP transaction ID instead of echoing it, but it does not cite a qualifying raw before/after capture. `asserted-unverified` — `pylxpweb@204b95d:src/pylxpweb/transports/modbus.py:207-254`.

The compatibility code parses with `exp_tid=0`, rewrites the returned PDU transaction ID to the currently expected value, and ignores a response if the current future is already complete. Do not remove that behavior as “lax validation” without replacement evidence. `verified-against-code` — `src/pylxpweb/transports/modbus.py:207-254`.

## WiFi dongle protocol

### A11A envelope

| Field/order | Encoding | Evidence |
|---|---|---|
| Prefix | `A1 1A` | `verified-against-code` — `src/pylxpweb/transports/dongle.py:545-575` |
| Outer metadata | version LE16, frame length LE16, address `01`, outer function, ten-byte dongle serial, data length LE16 | `verified-against-code` — `src/pylxpweb/transports/dongle.py:545-624` |
| Embedded request | action byte `0`, Modbus function, ten-byte inverter serial, register LE16, then count/value fields | `verified-against-code` — `src/pylxpweb/transports/dongle.py:576-604` |
| Integrity | CRC-16/Modbus over the embedded data frame; CRC stored LE16 | `verified-against-code` — `src/pylxpweb/transports/dongle.py:101-118`, `src/pylxpweb/transports/dongle.py:606-624` |
| Outer functions | C1 heartbeat, C2 translated Modbus, C3 read parameter, C4 write parameter | `verified-against-code` — `src/pylxpweb/transports/dongle.py:56-77` |

### Single serialized TCP workflow

| Rule | Why | Evidence |
|---|---|---|
| `_connect_lock` serializes dial/close, the transaction lock serializes request/response, and the reentrant operation lock covers multi-request operations. | pylxpweb serializes its own transactions and multi-step operations within this transport instance. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:247-254`, `src/pylxpweb/transports/dongle.py:1467-1481` |
| Gateway capacity | Source comments describe the dongle as having one TCP slot and processing one request at a time. | `asserted-unverified` — `pylxpweb@204b95d:src/pylxpweb/transports/dongle.py:247-254`, `pylxpweb@204b95d:src/pylxpweb/transports/dongle.py:1467-1481`; no external-client connection capture is cited |
| One timeout bounds the whole prefix/header/body receive. | Fragment arrival does not restart the timeout. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:898-904` |
| A write request is not replayed at request level after missing ACK/EOF/socket error. | The inverter may already have applied it; replay could overwrite a concurrent bitfield change with stale state. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1401-1418` |
| Response identity validation checks outer function before inner parsing, then CRC, serial, Modbus function, and start register. | A heartbeat/proxied frame must become `TransportResponseMismatchError`, not false evidence that fast reads are unsupported. | `verified-against-code` — `src/pylxpweb/transports/dongle.py:1080-1268` |

## Input-read planning

### Coalescing invariants

| Invariant | Required behavior | Evidence |
|---|---|---|
| Merge eligibility | Merge only contiguous or overlapping spans whose union fits `max_input_block_size`. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:203-238` |
| Gaps | Never bridge an unmapped gap, even when the numeric start-to-end span would fit. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:207-217` |
| Oversized logical group | Never split it; preserve the original one-read group. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:216-238` |
| Configuration | Accepted `max_input_block_size` is 40 through 125; the default is 40. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:136-175` |
| Claimed fast setting | A source comment describes 120 as field-proven, but no qualifying raw before/after artifact is cited here. | `asserted-unverified` — `pylxpweb@204b95d:src/pylxpweb/transports/_register_data.py:123-142` |
| GridBOSS/MID | Keep every group at 40 registers or fewer and never coalesce it. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:111-134` |
| GridBOSS hardware rationale | A source comment reports that reads above 40 failed on real GridBOSS hardware, but it supplies no qualifying raw before/after capture. | `asserted-unverified` — `pylxpweb@204b95d:src/pylxpweb/transports/_register_data.py:130-134` |
| Batteries | Always read the four 30-register physical slots as one atomic 120-register FC04 block starting at 5002, independent of the configured normal block size. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:322-374` |
| Battery rationale | One 120-register read places all four physical slots in the same transaction, eliminating inter-read page rotation by construction. | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:322-374` |

At configured size 120, the inverter plan is `(0,113)`, `(113,41)`, `(170,4)`, `(193,12)`; gaps 154–169 and 174–192 remain unread. `verified-against-code` — `tests/unit/transports/test_input_block_coalescing.py:50-59`, `tests/unit/transports/test_input_block_coalescing.py:98-148`.

### Fast-read latch state machine

| Prior evidence / failure | Immediate action | Future mode | Evidence |
|---|---|---|---|
| No successful read above 40; a genuine coalesced request raises or short-reads | Rerun the current cycle using the plain plan | **Permanently latch conservative mode for that transport instance**; recreation/reload re-arms it | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:888-918`, `src/pylxpweb/transports/_register_data.py:1007-1024`, `src/pylxpweb/transports/_register_data.py:1058-1066` |
| Any response mismatch, whether support was proven or not | Rerun the current cycle using the plain plan | Plain reads for 300 monotonic seconds, then probe fast mode again | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:920-939`, `src/pylxpweb/transports/_register_data.py:1000-1006` |
| At least one successful coalesced read above 40; any later exception or short read | Rerun the current cycle using the plain plan | Plain reads for 300 monotonic seconds, then probe fast mode again | `verified-against-code` — `src/pylxpweb/transports/_register_data.py:941-970`, `src/pylxpweb/transports/_register_data.py:1007-1032` |

Do not collapse the last two rows into the permanent latch. A mismatch is evidence of a misrouted frame, and a failure after proven support cannot prove an old-firmware 40-register cap. `verified-against-code` — `src/pylxpweb/transports/_register_data.py:920-1032`.
