#!/usr/bin/env python3
"""Download EG4 inverter firmware images (ARM comms + C28x DSP) from the EG4 portal.

The EG4 mobile app's *local update* flow exposes two undocumented endpoints that serve complete
firmware images for any device family — not just the family you own.  This is the only known way to
obtain firmware for hardware you do not have (e.g. the off-grid SNA families), and it replaced the
previous approach of capturing an OTA push with tcpdump.

Endpoints (POST, authenticated portal session)::

    /WManage/web/maintain/appLocalUpdate/listForAppByType   firmwareDeviceType=<enum>
    /WManage/web/maintain/appLocalUpdate/getUploadFileAnalyzeInfo   recordId=<id>&startIndex=<n>

``startIndex`` is **1-based** — passing 0 returns an empty body or HTTP 500, which looks exactly
like "no such firmware" and is why this path was initially missed.

Images arrive already de-framed: unlike OTA pcap captures, there is no 771-byte block framing to
strip.  Which processor an image belongs to is determined by the ratio of chunk size to address
stride, since ``firmwareType`` reads ``PCS`` for both:

===================  =====================  ===========================
bytes per address    processor              typical load base
===================  =====================  ===========================
2                    TI C28x inverter DSP   ``0x80000``
1                    ARM Cortex-M comms     ``0x080xxxxx``
===================  =====================  ===========================

Credentials come from ``python/pylxpweb/.env`` (``LUXPOWER_USERNAME`` / ``LUXPOWER_PASSWORD`` /
``LUXPOWER_BASE_URL``).  Read-only: this never writes to a device.

Usage::

    uv run python scripts/download_inverter_firmware.py --list
    uv run python scripts/download_inverter_firmware.py --device-type SNA_US_12K --out-dir /tmp/fw
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
from pathlib import Path, PurePosixPath

# From the decompiled EG4 Android app:
#   smali_classes2/com/nfcx/eg4/global/firmware/FIRMWARE_DEVICE_TYPE.smali
# The API rejects anything not in this list, so these values cannot be guessed.
DEVICE_TYPES = (
    "LXP_LB_8_12K",  # FlexBOSS21 / 18kPV / 12kPV  (EG4_HYBRID)
    "SNA_US_12K",  # 12000XP / SNA-US 15K        (EG4_OFFGRID)
    "SNA_US_6000",  # 6000XP                      (EG4_OFFGRID)
    "POWER_HUB",  # GridBOSS
    "DONGLE_E_WIFI_DONGLE",
)

LIST_PATH = "/WManage/web/maintain/appLocalUpdate/listForAppByType"
FETCH_PATH = "/WManage/web/maintain/appLocalUpdate/getUploadFileAnalyzeInfo"
CHUNK_DELAY_S = 0.12  # be polite to the vendor server


class FirmwareDownloadError(RuntimeError):
    """A firmware transfer did not complete cleanly."""


async def _list_firmware(session, base_url: str, device_type: str) -> list[dict]:
    async with session.post(
        base_url + LIST_PATH, data={"firmwareDeviceType": device_type}
    ) as resp:
        body = await resp.text()
    if not body.strip():
        return []
    return json.loads(body).get("rows", [])


async def _fetch_image(
    session, base_url: str, record_id: int
) -> tuple[dict, dict, dict]:
    """Page one firmware record.  Returns (metadata, {index: b64 data}, {index: address}).

    Raises ``FirmwareDownloadError`` rather than returning a short image: a
    truncated firmware that looks complete is far worse than a failed download,
    because every downstream address would be silently wrong.
    """
    chunks: dict[int, str] = {}
    addrs: dict[int, int] = {}
    meta: dict = {}
    start_index = 1  # 1-based; 0 yields an empty body / HTTP 500

    while True:
        async with session.post(
            base_url + FETCH_PATH,
            data={"recordId": str(record_id), "startIndex": str(start_index)},
        ) as resp:
            status = resp.status
            body = await resp.text()
        if status != 200:
            raise FirmwareDownloadError(
                f"record {record_id}: HTTP {status} at startIndex={start_index}"
            )
        if not body.strip():
            raise FirmwareDownloadError(
                f"record {record_id}: empty response at startIndex={start_index} "
                f"after {len(chunks)} chunks (transfer incomplete)"
            )
        payload = json.loads(body)
        if not payload.get("success"):
            raise FirmwareDownloadError(
                f"record {record_id}: server reported failure at "
                f"startIndex={start_index} after {len(chunks)} chunks"
            )
        if not meta:
            meta = {
                k: v
                for k, v in payload.items()
                if k not in ("firmwareData", "physicalAddrData")
            }
        for entry in payload.get("firmwareData") or []:
            chunks[entry["index"]] = entry["data"]
        for entry in payload.get("physicalAddrData") or []:
            addrs[entry["index"]] = entry["physicalAddr"]
        if not payload.get("hasNext"):
            break
        start_index = max(chunks) + 1
        await asyncio.sleep(CHUNK_DELAY_S)

    # Chunk indices must be the complete run 1..N — a gap means a lost page, and
    # concatenating around it would shift every later byte.
    if chunks:
        expected = set(range(1, max(chunks) + 1))
        missing = sorted(expected - set(chunks))
        if missing:
            raise FirmwareDownloadError(
                f"record {record_id}: missing chunk indices {missing[:10]}"
                f"{'…' if len(missing) > 10 else ''}"
            )
    return meta, chunks, addrs


def _classify(chunks: dict[int, str], addrs: dict[int, int]) -> tuple[str, int | None]:
    """Identify the processor from the address stride vs chunk size."""
    order = sorted(chunks)
    if len(order) < 2:
        return "unknown", (min(addrs.values()) if addrs else None)
    size = len(base64.b64decode(chunks[order[0]]))
    stride = addrs[order[1]] - addrs[order[0]]
    if stride <= 0:
        return "unknown", min(addrs.values())
    per_addr = size / stride
    if abs(per_addr - 2) < 0.01:
        return "C28x inverter DSP", min(addrs.values())
    if abs(per_addr - 1) < 0.01:
        return "ARM comms", min(addrs.values())
    return f"unknown ({per_addr:.2f} B/addr)", min(addrs.values())


async def run(device_types: list[str], out_dir: Path | None, list_only: bool) -> int:
    try:
        from dotenv import load_dotenv
        from pylxpweb import LuxpowerClient
    except ImportError as err:
        print(
            f"missing dependency: {err}.  Run with: uv run --with python-dotenv python ..."
        )
        return 1

    # EG4 portal credentials live in pylxpweb's .env, not this repo's (which holds only
    # Home Assistant tokens).  Search the usual sibling-checkout layouts.
    here = Path(__file__).resolve()
    for candidate in (
        parent / "python" / "pylxpweb" / ".env" for parent in here.parents
    ):
        if candidate.is_file():
            load_dotenv(candidate)
            break

    username, password = (
        os.environ.get("LUXPOWER_USERNAME"),
        os.environ.get("LUXPOWER_PASSWORD"),
    )
    if not username or not password:
        print(
            "LUXPOWER_USERNAME / LUXPOWER_PASSWORD not set — expected in "
            "<checkout-root>/python/pylxpweb/.env"
        )
        return 1
    base_url = os.environ.get("LUXPOWER_BASE_URL", "https://monitor.eg4electronics.com")

    async with LuxpowerClient(
        username=username, password=password, base_url=base_url
    ) as client:
        await client.login()
        session = client._session  # noqa: SLF001 - portal endpoints are not modelled in pylxpweb

        for device_type in device_types:
            rows = await _list_firmware(session, base_url, device_type)
            print(f"\n=== {device_type}: {len(rows)} firmware record(s) ===")
            for row in rows:
                print(
                    f"  recordId={row['recordId']:<5} {row['fileName']:<44}"
                    f" standard={row.get('standard')} v1={row.get('v1')} v2={row.get('v2')}"
                )
            if list_only or out_dir is None:
                continue

            out_dir.mkdir(parents=True, exist_ok=True)
            for row in rows:
                meta, chunks, addrs = await _fetch_image(
                    session, base_url, row["recordId"]
                )
                if not chunks:
                    print(f"    {row['fileName']}: no data returned")
                    continue
                blob = b"".join(base64.b64decode(chunks[i]) for i in sorted(chunks))
                kind, base_addr = _classify(chunks, addrs)
                # fileName is vendor-controlled: reduce to a bare basename and
                # confirm the resolved path stays under --out-dir before writing.
                stem = PurePosixPath(str(row["fileName"])).name.replace(".hex", "")
                stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).lstrip(".") or "firmware"
                dest = (out_dir / f"{stem}.bin").resolve()
                if not dest.is_relative_to(out_dir.resolve()):
                    raise FirmwareDownloadError(
                        f"refusing to write outside {out_dir}: {row['fileName']!r}"
                    )
                dest.write_bytes(blob)
                print(
                    f"    {row['fileName']}: {len(chunks)} chunks, {len(blob):,} B, {kind}, "
                    f"base=0x{base_addr:X} -> {dest}"
                )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--device-type",
        action="append",
        choices=DEVICE_TYPES,
        help="device family to fetch (repeatable; default: all)",
    )
    parser.add_argument("--out-dir", type=Path, help="write .bin images here")
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="list available firmware without downloading",
    )
    args = parser.parse_args()

    device_types = args.device_type or list(DEVICE_TYPES)
    if not args.list_only and args.out_dir is None:
        parser.error("--out-dir is required unless --list is given")
    return asyncio.run(run(device_types, args.out_dir, args.list_only))


if __name__ == "__main__":
    raise SystemExit(main())
