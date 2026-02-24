#!/usr/bin/env bash
# Capture dongle→cloud TCP traffic for CloudEmitter protocol analysis.
#
# Reads GRIDBOSS_DONGLE_IP from pylxpweb/.env and captures all traffic
# between the dongle and the cloud ingestion server (port 4346).
#
# Usage:
#   sudo ./scripts/capture_cloud_traffic.sh [duration_seconds]
#
# Default duration: 300 seconds (5 minutes — captures ~3 data poll cycles).
# Output: scratchpad/firmware/dongle_capture.pcap
#
# After capture, decode with:
#   uv run python scripts/decode_cloud_frames.py scratchpad/firmware/dongle_capture.pcap

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYLXPWEB_ENV="/Users/bryanli/Projects/joyfulhouse/python/pylxpweb/.env"

# Load dongle IP from pylxpweb .env
if [[ ! -f "$PYLXPWEB_ENV" ]]; then
    echo "ERROR: $PYLXPWEB_ENV not found"
    exit 1
fi

DONGLE_IP=$(grep '^GRIDBOSS_DONGLE_IP=' "$PYLXPWEB_ENV" | cut -d= -f2)
if [[ -z "$DONGLE_IP" ]]; then
    echo "ERROR: GRIDBOSS_DONGLE_IP not set in $PYLXPWEB_ENV"
    exit 1
fi

CLOUD_PORT=4346
DURATION="${1:-300}"
OUTPUT_DIR="$PROJECT_DIR/scratchpad/firmware"
OUTPUT_FILE="$OUTPUT_DIR/dongle_capture.pcap"

mkdir -p "$OUTPUT_DIR"

echo "=== EG4 Cloud Traffic Capture ==="
echo "Dongle IP:    $DONGLE_IP"
echo "Cloud port:   $CLOUD_PORT"
echo "Duration:     ${DURATION}s"
echo "Output:       $OUTPUT_FILE"
echo ""

# Check if running as root (tcpdump needs it for packet capture)
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run with sudo for packet capture"
    echo "Usage: sudo $0 [duration_seconds]"
    exit 1
fi

echo "Starting capture... (Ctrl+C to stop early)"
echo ""

# Capture all TCP traffic between dongle and any host on port 4346.
# This catches both directions: dongle→cloud and cloud→dongle.
tcpdump -i any \
    "host $DONGLE_IP and tcp port $CLOUD_PORT" \
    -w "$OUTPUT_FILE" \
    -v \
    -G "$DURATION" -W 1 \
    2>&1

PCAP_SIZE=$(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE" 2>/dev/null || echo "unknown")
echo ""
echo "=== Capture Complete ==="
echo "File: $OUTPUT_FILE ($PCAP_SIZE bytes)"
echo ""
echo "Decode with:"
echo "  uv run python scripts/decode_cloud_frames.py $OUTPUT_FILE"
