#!/usr/bin/env python3
"""Download EG4 dongle firmware from the LuxPower resource server.

Probes the firmware list API and downloads available .bin files
for analysis. Targets the E WiFi dongle (ESP32) firmware.

Usage:
    uv run python scripts/download_dongle_firmware.py
    uv run python scripts/download_dongle_firmware.py --output-dir /tmp/fw
    uv run python scripts/download_dongle_firmware.py --list-only
    uv run python scripts/download_dongle_firmware.py --brand LuxPower
"""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import httpx

FIRMWARE_LIST_URL = "https://res.solarcloudsystem.com:8443/resource/getAllFirmware"
FIRMWARE_DOWNLOAD_BASE = "http://47.254.33.206:8083/resource/firmware/"
CHANGELOG_URL = "https://res.solarcloudsystem.com:8443/resource/findAllTypeInfo"

DEFAULT_BRAND = "EG4"
DEFAULT_OUTPUT_DIR = Path("scratchpad/firmware")

# ESP32 firmware magic bytes
ESP32_IMAGE_MAGIC = 0xE9
ESP32_APP_MAGIC = 0xE9

# W7500 (ARM Cortex-M0) vector table: first word is initial SP, second is reset vector
# SP typically points to top of SRAM (0x20004000 for 16KB SRAM)
W7500_SRAM_BASE = 0x20000000
W7500_SRAM_TOP = 0x20004000
W7500_FLASH_BASE = 0x00000000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download EG4 dongle firmware")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for firmware files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--brand",
        default=DEFAULT_BRAND,
        help=f"Brand to query (default: {DEFAULT_BRAND})",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list available firmware, don't download",
    )
    parser.add_argument(
        "--changelog",
        action="store_true",
        help="Also fetch firmware type/changelog info",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (some LuxPower servers have certificate issues)",
    )
    return parser.parse_args()


def fetch_firmware_list(client: httpx.Client, brand: str) -> dict | None:
    """Fetch the list of available firmware from the resource server."""
    print(f"[*] Querying firmware list for brand: {brand}")
    print(f"    URL: {FIRMWARE_LIST_URL}")

    try:
        resp = client.post(
            FIRMWARE_LIST_URL,
            json={"brand": brand},
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"    Status: {resp.status_code}")
        print(
            f"    Response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
        return data
    except httpx.HTTPStatusError as e:
        print(f"    HTTP error: {e.response.status_code} {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def fetch_changelog(client: httpx.Client, brand: str) -> dict | None:
    """Fetch firmware type/changelog info."""
    print(f"\n[*] Querying firmware changelog for brand: {brand}")
    print(f"    URL: {CHANGELOG_URL}")

    try:
        resp = client.post(
            CHANGELOG_URL,
            json={"brand": brand},
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"    Status: {resp.status_code}")
        return data
    except Exception as e:
        print(f"    Error: {e}")
        return None


def extract_firmware_entries(data: dict) -> list[dict]:
    """Extract firmware file entries from the API response."""
    entries = []

    # The response structure varies - try common patterns
    if "firmwares" in data:
        fw_data = data["firmwares"]
        if isinstance(fw_data, str):
            try:
                fw_data = json.loads(fw_data)
            except json.JSONDecodeError:
                pass
        if isinstance(fw_data, list):
            entries = fw_data
        elif isinstance(fw_data, dict):
            entries = [fw_data]

    # Also check for direct list at top level
    if not entries and isinstance(data, list):
        entries = data

    # Check for nested data
    if not entries and "data" in data:
        nested = data["data"]
        if isinstance(nested, list):
            entries = nested
        elif isinstance(nested, dict) and "firmwares" in nested:
            entries = (
                nested["firmwares"]
                if isinstance(nested["firmwares"], list)
                else [nested["firmwares"]]
            )

    return entries


def parse_firmware_filename(filename: str) -> dict:
    """Parse version info from firmware filename."""
    info: dict = {"filename": filename}

    # Pattern: V{major}_{minor}.bin (e.g., V1_05.bin)
    match = re.search(r"V(\d+)_(\d+)\.bin", filename, re.IGNORECASE)
    if match:
        info["version_major"] = int(match.group(1))
        info["version_minor"] = int(match.group(2))
        info["version"] = f"{match.group(1)}.{match.group(2)}"

    # Detect chip type hints
    lower = filename.lower()
    if "esp" in lower or "esp32" in lower:
        info["chip_hint"] = "ESP32"
    elif "w7500" in lower or "wiznet" in lower:
        info["chip_hint"] = "W7500"

    return info


def identify_firmware_type(data: bytes) -> str:
    """Identify firmware type from binary header."""
    if len(data) < 16:
        return "unknown (too small)"

    first_byte = data[0]

    # ESP32 image: starts with 0xE9
    if first_byte == ESP32_IMAGE_MAGIC:
        # ESP32 image header: magic(1) + segment_count(1) + spi_mode(1) + spi_speed_size(1)
        segment_count = data[1]
        if 1 <= segment_count <= 16:
            # Check for ESP-IDF app description at offset 0x20
            if len(data) > 0x40:
                try:
                    app_desc = data[0x20:0x30].decode("ascii", errors="ignore")
                    if any(c.isalpha() for c in app_desc):
                        return f"ESP32 firmware (segments={segment_count}, app_hint='{app_desc.strip()}')"
                except Exception:
                    pass
            return f"ESP32 firmware ({segment_count} segments)"

    # ARM Cortex-M0 (W7500): vector table
    # First word = initial SP (should be in SRAM range)
    # Second word = reset handler (should be in flash range, odd for Thumb)
    if len(data) >= 8:
        sp = struct.unpack_from("<I", data, 0)[0]
        reset = struct.unpack_from("<I", data, 4)[0]

        if (W7500_SRAM_BASE <= sp <= W7500_SRAM_TOP + 0x8000) and (
            W7500_FLASH_BASE < reset < 0x00020000
        ):
            return (
                f"ARM Cortex-M0 (W7500) firmware (SP=0x{sp:08X}, Reset=0x{reset:08X})"
            )

    # Generic ARM check (broader range)
    if len(data) >= 8:
        sp = struct.unpack_from("<I", data, 0)[0]
        reset = struct.unpack_from("<I", data, 4)[0]
        if (0x20000000 <= sp <= 0x20100000) and (reset & 1):  # Thumb bit set
            return f"ARM Cortex-M firmware (SP=0x{sp:08X}, Reset=0x{reset:08X})"

    # Intel HEX check
    if data[:1] == b":":
        return "Intel HEX format"

    # Motorola S-Record
    if data[:2] in (b"S0", b"S1", b"S2", b"S3"):
        return "Motorola S-Record format"

    return f"Unknown (magic=0x{first_byte:02X}, first 16 bytes: {data[:16].hex()})"


def analyze_firmware(filepath: Path) -> None:
    """Analyze a downloaded firmware binary."""
    data = filepath.read_bytes()
    size = len(data)

    if size == 0:
        print(f"\n    --- {filepath.name}: EMPTY (0 bytes) ---")
        return

    print(f"\n    --- Analysis of {filepath.name} ---")
    print(f"    Size: {size:,} bytes ({size / 1024:.1f} KB)")

    # Hashes
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    print(f"    MD5:    {md5}")
    print(f"    SHA256: {sha256}")

    # Type identification
    fw_type = identify_firmware_type(data)
    print(f"    Type:   {fw_type}")

    # Entropy estimate (quick)
    byte_counts = [0] * 256
    for b in data:
        byte_counts[b] += 1
    import math

    entropy = 0.0
    for count in byte_counts:
        if count > 0:
            p = count / size
            entropy -= p * math.log2(p)
    print(
        f"    Entropy: {entropy:.2f} bits/byte (max 8.0, >7.5 suggests encryption/compression)"
    )

    # String extraction (interesting ones)
    strings = extract_strings(data, min_length=8)
    interesting = [
        s
        for s in strings
        if any(
            kw in s.lower()
            for kw in [
                "version",
                "http",
                "wifi",
                "ssid",
                "password",
                "serial",
                "modbus",
                "uart",
                "esp",
                "luxpower",
                "eg4",
                "server",
                "mqtt",
                "tcp",
                "ssl",
                "firmware",
                "update",
                "ota",
                "error",
                "debug",
                ".com",
                ".bin",
                "solarcloudsystem",
            ]
        )
    ]
    if interesting:
        print(f"    Interesting strings ({len(interesting)} found):")
        for s in interesting[:30]:
            print(f"      {s}")
    else:
        print(f"    Strings: {len(strings)} total, none matched keywords")

    # ESP32 partition table check
    if data[0] == ESP32_IMAGE_MAGIC and len(data) > 0x8000:
        check_esp32_partitions(data)


def extract_strings(data: bytes, min_length: int = 6) -> list[str]:
    """Extract printable ASCII strings from binary data."""
    strings = []
    current = []
    for b in data:
        if 0x20 <= b < 0x7F:
            current.append(chr(b))
        else:
            if len(current) >= min_length:
                strings.append("".join(current))
            current = []
    if len(current) >= min_length:
        strings.append("".join(current))
    return strings


def check_esp32_partitions(data: bytes) -> None:
    """Check for ESP32 partition table at 0x8000."""
    PT_OFFSET = 0x8000
    PT_MAGIC = 0xAA50

    if len(data) <= PT_OFFSET + 32:
        return

    magic = struct.unpack_from("<H", data, PT_OFFSET)[0]
    if magic == PT_MAGIC:
        print("    ESP32 Partition Table found at 0x8000:")
        offset = PT_OFFSET
        while offset + 32 <= len(data):
            entry = data[offset : offset + 32]
            entry_magic = struct.unpack_from("<H", entry, 0)[0]
            if entry_magic != PT_MAGIC:
                break
            ptype = entry[2]
            psubtype = entry[3]
            poffset = struct.unpack_from("<I", entry, 4)[0]
            psize = struct.unpack_from("<I", entry, 8)[0]
            pname = entry[12:28].split(b"\x00")[0].decode("ascii", errors="ignore")
            print(
                f"      {pname:16s} type={ptype} subtype=0x{psubtype:02X} offset=0x{poffset:06X} size={psize:,}"
            )
            offset += 32


def download_firmware(
    client: httpx.Client,
    filename: str,
    output_dir: Path,
) -> Path | None:
    """Download a single firmware file."""
    url = FIRMWARE_DOWNLOAD_BASE + filename
    output_path = output_dir / filename

    if output_path.exists():
        print(f"    [skip] Already downloaded: {output_path}")
        analyze_firmware(output_path)
        return output_path

    print(f"    [download] {url}")
    try:
        resp = client.get(url)
        resp.raise_for_status()

        if len(resp.content) == 0:
            print("    [skip] Empty response (0 bytes) - file not found on server")
            return None

        output_path.write_bytes(resp.content)
        print(f"    [saved] {output_path} ({len(resp.content):,} bytes)")
        return output_path
    except httpx.HTTPStatusError as e:
        print(f"    [error] HTTP {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"    [error] {e}")
        return None


def try_common_firmware_names(
    client: httpx.Client,
    output_dir: Path,
) -> list[Path]:
    """Try downloading firmware with common naming patterns."""
    print("\n[*] Probing common firmware filenames...")

    # Common patterns observed in the APK
    candidates = []

    # E WiFi dongle pattern: V{major}_{minor}.bin
    for major in range(1, 4):
        for minor in range(0, 20):
            candidates.append(f"V{major}_{minor:02d}.bin")

    # Also try without zero padding
    for major in range(1, 4):
        for minor in range(0, 20):
            candidates.append(f"V{major}_{minor}.bin")

    # ESP32 patterns
    candidates.extend(
        [
            "esp32_dongle.bin",
            "dongle_firmware.bin",
            "ewifi_firmware.bin",
            "EWiFi.bin",
        ]
    )

    downloaded = []
    for name in candidates:
        url = FIRMWARE_DOWNLOAD_BASE + name
        try:
            resp = client.head(url, follow_redirects=True)
            if resp.status_code == 200:
                content_length = resp.headers.get("content-length", "?")
                print(f"    [found] {name} ({content_length} bytes)")
                path = download_firmware(client, name, output_dir)
                if path:
                    downloaded.append(path)
        except Exception:
            pass

    return downloaded


def main() -> None:
    args = parse_args()

    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Output directory: {args.output_dir.resolve()}")

    with httpx.Client(
        timeout=args.timeout,
        verify=not args.insecure,  # TLS verified by default; opt out with --insecure
        follow_redirects=True,
    ) as client:
        # Step 1: Fetch firmware list
        data = fetch_firmware_list(client, args.brand)

        if data:
            # Save raw response for analysis
            raw_path = args.output_dir / f"firmware_list_{args.brand.lower()}.json"
            raw_path.write_text(json.dumps(data, indent=2, default=str))
            print(f"    Raw response saved to: {raw_path}")

            entries = extract_firmware_entries(data)
            print(f"\n[*] Found {len(entries)} firmware entries")

            if entries:
                for i, entry in enumerate(entries):
                    print(
                        f"\n  [{i + 1}] {json.dumps(entry, indent=4, default=str)[:500]}"
                    )

                    if not args.list_only:
                        # Try to find downloadable filename in entry
                        filename = None
                        if isinstance(entry, dict):
                            # API returns 'sourceName' for the actual filename
                            for key in [
                                "sourceName",
                                "fileName",
                                "filename",
                                "file",
                                "name",
                                "url",
                                "path",
                            ]:
                                if key in entry and isinstance(entry[key], str):
                                    val = entry[key]
                                    if val.endswith(".bin") or val.endswith(".hex"):
                                        filename = val.split("/")[-1]
                                        break
                                    elif "/" in val or val.startswith("http"):
                                        filename = val.split("/")[-1]
                                        break
                        elif isinstance(entry, str):
                            if entry.endswith(".bin") or entry.endswith(".hex"):
                                filename = entry

                        if filename:
                            path = download_firmware(client, filename, args.output_dir)
                            if path:
                                analyze_firmware(path)
            else:
                print("    No firmware entries found in response")
                print(
                    f"    Full response: {json.dumps(data, indent=2, default=str)[:1000]}"
                )
        else:
            print("    Failed to fetch firmware list")

        # Step 2: Try alternate brands
        if not data or not extract_firmware_entries(data):
            for alt_brand in ["LuxPower", "luxpower", "lxp", "EG4", "SNAP", "Snap"]:
                if alt_brand == args.brand:
                    continue
                print(f"\n[*] Trying alternate brand: {alt_brand}")
                alt_data = fetch_firmware_list(client, alt_brand)
                if alt_data:
                    alt_entries = extract_firmware_entries(alt_data)
                    if alt_entries:
                        print(
                            f"    Found {len(alt_entries)} entries for brand '{alt_brand}'"
                        )
                        raw_path = (
                            args.output_dir / f"firmware_list_{alt_brand.lower()}.json"
                        )
                        raw_path.write_text(json.dumps(alt_data, indent=2, default=str))

                        if not args.list_only:
                            for entry in alt_entries:
                                if isinstance(entry, dict):
                                    for key in ["sourceName", "fileName", "filename"]:
                                        if (
                                            key in entry
                                            and isinstance(entry[key], str)
                                            and entry[key].endswith(".bin")
                                        ):
                                            path = download_firmware(
                                                client, entry[key], args.output_dir
                                            )
                                            if path:
                                                analyze_firmware(path)
                                            break
                        break

        # Step 3: Fetch changelog if requested
        if args.changelog or True:  # Always fetch changelog for context
            changelog = fetch_changelog(client, args.brand)
            if changelog:
                cl_path = args.output_dir / f"changelog_{args.brand.lower()}.json"
                cl_path.write_text(json.dumps(changelog, indent=2, default=str))
                print(f"    Changelog saved to: {cl_path}")

    print("\n[*] Done")


if __name__ == "__main__":
    main()
