#!/usr/bin/env bash
# Capture ALL traffic to/from a WiFi dongle during a firmware upgrade.
#
# This captures EVERYTHING — no port filter — because firmware OTA may use
# different ports/servers than the normal cloud protocol (port 4346).
#
# Runs tcpdump on the UDM gateway (172.16.0.1) via SSH, since dongles are on
# a separate VLAN and their traffic is only visible from the gateway.
#
# Usage:
#   ./scripts/capture_firmware_upgrade.sh --ip 10.100.5.225              # capture until Ctrl+C
#   ./scripts/capture_firmware_upgrade.sh --ip 10.100.5.225 --verify     # verify then exit
#   ./scripts/capture_firmware_upgrade.sh --ip 10.100.5.225 --duration 600  # auto-stop
#   ./scripts/capture_firmware_upgrade.sh                                # uses GRIDBOSS_DONGLE_IP from env
#
# Workflow:
#   1. Run with --verify first to confirm everything works
#   2. Run without flags to start capture (runs until Ctrl+C)
#   3. Trigger firmware upgrade via EG4 app/portal
#   4. Wait for upgrade to complete
#   5. Press Ctrl+C to stop capture
#   6. Decode with: uv run python scripts/decode_cloud_frames.py <pcap_file>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYLXPWEB_ENV="/Users/bryanli/Projects/joyfulhouse/python/pylxpweb/.env"
UDM_HOST="172.16.0.1"
UDM_USER="root"

# --- Parse arguments ---
VERIFY_ONLY=false
DURATION=""
DONGLE_IP=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify) VERIFY_ONLY=true; shift ;;
        --duration) DURATION="$2"; shift 2 ;;
        --ip) DONGLE_IP="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Resolve dongle IP ---
if [[ -z "$DONGLE_IP" ]]; then
    # Fall back to env file
    if [[ ! -f "$PYLXPWEB_ENV" ]]; then
        echo "ERROR: No --ip given and $PYLXPWEB_ENV not found"
        exit 1
    fi
    DONGLE_IP=$(grep '^GRIDBOSS_DONGLE_IP=' "$PYLXPWEB_ENV" | cut -d= -f2)
    if [[ -z "$DONGLE_IP" ]]; then
        echo "ERROR: No --ip given and GRIDBOSS_DONGLE_IP not set in $PYLXPWEB_ENV"
        exit 1
    fi
fi

# --- Output setup ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="$PROJECT_DIR/scratchpad/firmware"
PCAP_FILE="$OUTPUT_DIR/firmware_upgrade_${TIMESTAMP}.pcap"
LOCAL_PCAP="$PCAP_FILE"
REMOTE_PCAP="/tmp/firmware_upgrade_${TIMESTAMP}.pcap"

mkdir -p "$OUTPUT_DIR"

echo "============================================"
echo "  EG4 Firmware Upgrade Packet Capture"
echo "============================================"
echo ""
echo "  Dongle IP:     $DONGLE_IP"
echo "  UDM Gateway:   ${UDM_USER}@${UDM_HOST}"
echo "  Remote pcap:   $REMOTE_PCAP"
echo "  Local pcap:    $LOCAL_PCAP"
if [[ -n "$DURATION" ]]; then
    echo "  Duration:      ${DURATION}s (auto-stop)"
else
    echo "  Duration:      unlimited (Ctrl+C to stop)"
fi
echo ""

# --- Step 1: Verify SSH connectivity ---
echo "[1/4] Verifying SSH to UDM..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${UDM_USER}@${UDM_HOST}" "echo ok" >/dev/null 2>&1; then
    echo "  FAIL: Cannot SSH to ${UDM_USER}@${UDM_HOST}"
    echo "  Ensure SSH key is configured for the UDM."
    exit 1
fi
echo "  OK"

# --- Step 2: Verify tcpdump is available on UDM ---
echo "[2/4] Verifying tcpdump on UDM..."
TCPDUMP_PATH=$(ssh "${UDM_USER}@${UDM_HOST}" "which tcpdump 2>/dev/null || echo ''")
if [[ -z "$TCPDUMP_PATH" ]]; then
    echo "  FAIL: tcpdump not found on UDM"
    exit 1
fi
echo "  OK ($TCPDUMP_PATH)"

# --- Step 3: Verify dongle is reachable (traffic exists) ---
echo "[3/4] Verifying dongle traffic is visible from UDM..."
echo "  Capturing 5 seconds of traffic from $DONGLE_IP..."

# Capture a small sample to verify we can see the dongle
SAMPLE_COUNT=$(ssh "${UDM_USER}@${UDM_HOST}" \
    "timeout 5 tcpdump -i any host $DONGLE_IP -c 50 2>/dev/null | wc -l || echo 0" 2>/dev/null)

# tcpdump prints a summary line even with 0 packets; check actual count
VERIFY_PACKETS=$(ssh "${UDM_USER}@${UDM_HOST}" \
    "timeout 5 tcpdump -i any host $DONGLE_IP -c 5 -w /dev/null 2>&1 | grep -oE '[0-9]+ packets? captured' | grep -oE '[0-9]+' || echo 0" 2>/dev/null)

if [[ "$VERIFY_PACKETS" -gt 0 ]]; then
    echo "  OK: Captured $VERIFY_PACKETS packets in 5 seconds"
else
    echo "  WARNING: No packets seen from $DONGLE_IP in 5 seconds"
    echo "  The dongle may be idle. This is OK if it wakes up during firmware upgrade."
    echo "  Continuing anyway..."
fi

# --- Step 4: Identify interfaces ---
echo "[4/4] Checking network interfaces on UDM..."
INTERFACES=$(ssh "${UDM_USER}@${UDM_HOST}" "ip link show | grep -E '^[0-9]+:' | awk -F': ' '{print \$2}' | head -20")
echo "  Available interfaces:"
echo "$INTERFACES" | sed 's/^/    /'

if $VERIFY_ONLY; then
    echo ""
    echo "============================================"
    echo "  Verification complete. Ready to capture."
    echo "============================================"
    echo ""
    echo "  To start capture, run:"
    echo "    ./scripts/capture_firmware_upgrade.sh"
    exit 0
fi

echo ""
echo "============================================"
echo "  STARTING CAPTURE"
echo "============================================"
echo ""
echo "  Filter: host $DONGLE_IP (ALL ports, ALL protocols)"
echo "  Snap length: 65535 (full packets)"
echo ""
echo "  >>> Trigger the firmware upgrade now. <<<"
echo "  >>> Press Ctrl+C when upgrade is complete. <<<"
echo ""

# --- Build tcpdump command ---
# -i any         : capture on all interfaces (dongle VLAN may be on any bridge)
# -s 0           : full packet capture (no truncation)
# -w <file>      : write pcap binary
# -U             : packet-buffered output (flush each packet to disk immediately)
# host <IP>      : capture ALL traffic to/from dongle (no port filter!)
# --immediate-mode: reduce kernel buffering latency
TCPDUMP_CMD="tcpdump -i any -s 0 -U --immediate-mode -w $REMOTE_PCAP host $DONGLE_IP"

if [[ -n "$DURATION" ]]; then
    # With timeout: auto-stop after N seconds
    TCPDUMP_CMD="timeout $DURATION $TCPDUMP_CMD"
fi

# --- Trap Ctrl+C to cleanly stop and download ---
cleanup() {
    echo ""
    echo ""
    echo "[*] Stopping capture..."

    # Kill tcpdump on remote (the SSH session may have already closed)
    ssh "${UDM_USER}@${UDM_HOST}" "pkill -f 'tcpdump.*firmware_upgrade' 2>/dev/null || true" 2>/dev/null || true

    # Small delay to let tcpdump flush
    sleep 1

    # Download the pcap
    echo "[*] Downloading pcap from UDM..."
    if scp "${UDM_USER}@${UDM_HOST}:${REMOTE_PCAP}" "$LOCAL_PCAP" 2>/dev/null; then
        LOCAL_SIZE=$(stat -f%z "$LOCAL_PCAP" 2>/dev/null || stat -c%s "$LOCAL_PCAP" 2>/dev/null || echo "unknown")
        echo "  Downloaded: $LOCAL_PCAP ($LOCAL_SIZE bytes)"

        # Get packet count
        PACKET_INFO=$(ssh "${UDM_USER}@${UDM_HOST}" \
            "tcpdump -r $REMOTE_PCAP -q 2>/dev/null | wc -l || echo unknown" 2>/dev/null)
        echo "  Packets: $PACKET_INFO"

        # Cleanup remote file
        ssh "${UDM_USER}@${UDM_HOST}" "rm -f $REMOTE_PCAP" 2>/dev/null || true
        echo "  Remote file cleaned up."
    else
        echo "  FAIL: Could not download pcap."
        echo "  File may still be on UDM at: $REMOTE_PCAP"
        echo "  Manual download: scp ${UDM_USER}@${UDM_HOST}:${REMOTE_PCAP} ."
    fi

    echo ""
    echo "============================================"
    echo "  Capture Complete"
    echo "============================================"
    echo "  File: $LOCAL_PCAP"
    echo ""
    echo "  Decode with:"
    echo "    uv run python scripts/decode_cloud_frames.py $LOCAL_PCAP"
    echo ""
    echo "  Or open in Wireshark:"
    echo "    open $LOCAL_PCAP"
    echo ""

    exit 0
}
trap cleanup INT TERM

# --- Run capture via SSH ---
# The -t flag allocates a TTY so Ctrl+C propagates to the remote tcpdump.
# stderr is shown locally for packet count updates.
echo "[*] tcpdump running on UDM (pid will appear below)..."
echo ""

ssh -t "${UDM_USER}@${UDM_HOST}" "$TCPDUMP_CMD" 2>&1

# If we get here (duration timeout or natural exit), do cleanup
cleanup
