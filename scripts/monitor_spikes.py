#!/usr/bin/env python3
"""Monitor EG4 entities for data spikes over time.

Polls HA API every 30 seconds, records values for key sensors,
and flags any readings that look like spikes (sudden large jumps).
"""

import argparse
import os
import sys
import time
from datetime import datetime

import httpx

# Force unbuffered output when the stream supports reconfiguration.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Load from .env
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")

# Sensors to monitor for spikes
SPIKE_SENSOR_TEMPLATES = [
    # GridBOSS power/voltage (most spike-prone)
    "sensor.grid_boss_{gridboss_serial}_grid_power",
    "sensor.grid_boss_{gridboss_serial}_grid_power_l1",
    "sensor.grid_boss_{gridboss_serial}_grid_power_l2",
    "sensor.grid_boss_{gridboss_serial}_grid_voltage_l1",
    "sensor.grid_boss_{gridboss_serial}_grid_voltage_l2",
    "sensor.grid_boss_{gridboss_serial}_grid_frequency",
    "sensor.grid_boss_{gridboss_serial}_load_power",
    "sensor.grid_boss_{gridboss_serial}_smart_load_power",
    "sensor.grid_boss_{gridboss_serial}_grid_import_total",
    "sensor.grid_boss_{gridboss_serial}_grid_export_total",
    "sensor.grid_boss_{gridboss_serial}_consumption_total",
    # Inverter power sensors
    "sensor.18kpv_{primary_serial}_power_output",
    "sensor.18kpv_{primary_serial}_battery_power",
    "sensor.18kpv_{primary_serial}_grid_voltage_l1",
    "sensor.18kpv_{primary_serial}_grid_frequency",
    "sensor.flexboss21_{secondary_serial}_power_output",
    "sensor.flexboss21_{secondary_serial}_battery_power",
    "sensor.flexboss21_{secondary_serial}_grid_voltage_l1",
    "sensor.flexboss21_{secondary_serial}_grid_frequency",
    # Battery bank aggregate
    "sensor.battery_bank_{primary_serial}_battery_soc",
    "sensor.battery_bank_{secondary_serial}_battery_soc",
    # Charge rate sensors (new)
    "sensor.battery_bank_{primary_serial}_battery_bank_charge_rate",
    "sensor.battery_bank_{secondary_serial}_battery_bank_charge_rate",
    "sensor.parallel_group_a_battery_charge_rate",
    # Parallel group
    "sensor.parallel_group_a_grid_power",
    "sensor.parallel_group_a_consumption_power",
]

# Spike thresholds — max allowed jump between consecutive readings
SPIKE_THRESHOLDS = {
    "grid_power": 10000,  # W
    "grid_voltage": 20,  # V
    "grid_frequency": 5,  # Hz
    "load_power": 10000,  # W
    "smart_load_power": 10000,  # W
    "power_output": 10000,  # W
    "battery_power": 10000,  # W
    "battery_soc": 20,  # %
    "grid_import_total": 100,  # kWh (monotonic)
    "grid_export_total": 100,  # kWh (monotonic)
    "consumption_total": 100,  # kWh (monotonic)
    "charge_rate": 50,  # % (should be 0-100)
    "consumption_power": 10000,  # W
}

POLL_INTERVAL = 30  # seconds

previous_values: dict[str, float] = {}
spike_count = 0
poll_count = 0


def get_threshold(entity_id: str) -> float:
    for key, thresh in SPIKE_THRESHOLDS.items():
        if key in entity_id:
            return thresh
    return 50000  # very permissive default


def load_connection_config() -> tuple[str, str]:
    """Load HA connection settings from the established environment config."""
    token = os.environ.get("HA_LONG_LIVED_TOKEN", "")
    base_url = os.environ.get("HA_BASE_URL", "http://localhost:8123")
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as env_file:
            for line in env_file:
                line = line.strip()
                if not token and line.startswith("HA_LONG_LIVED_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                elif (
                    line.startswith("HA_BASE_URL=") and "HA_BASE_URL" not in os.environ
                ):
                    base_url = line.split("=", 1)[1].strip().strip('"')
    return token, base_url


def fetch_states(token: str, base_url: str) -> dict[str, str]:
    resp = httpx.get(
        f"{base_url}/api/states",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    return {s["entity_id"]: s["state"] for s in data}


def _sensor_label(sensor: str) -> str:
    """Return the operator-facing entity label for diagnostics."""
    return sensor.split(".")[-1]


def main(
    duration_minutes: int,
    serials: tuple[str, ...],
    token: str,
    base_url: str,
) -> None:
    global spike_count, poll_count
    replacements = {
        "{gridboss_serial}": serials[0],
        "{primary_serial}": serials[1],
        "{secondary_serial}": serials[2],
    }
    spike_sensors = SPIKE_SENSOR_TEMPLATES
    for marker, serial in replacements.items():
        spike_sensors = [sensor.replace(marker, serial) for sensor in spike_sensors]

    end_time = time.monotonic() + duration_minutes * 60
    print("=== EG4 Spike Monitor ===")
    print(f"Duration: {duration_minutes} minutes, interval: {POLL_INTERVAL}s")
    print(f"Monitoring {len(spike_sensors)} sensors")
    print(f"Started at {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    while time.monotonic() < end_time:
        poll_count += 1
        now = datetime.now().strftime("%H:%M:%S")
        try:
            states = fetch_states(token, base_url)
        except Exception as err:
            print(f"[{now}] FETCH ERROR: {err}")
            time.sleep(POLL_INTERVAL)
            continue

        spikes_this_poll: list[str] = []
        unavail_this_poll: list[str] = []

        for sensor in spike_sensors:
            val_str = states.get(sensor, "missing")
            if val_str in ("unavailable", "unknown", "missing"):
                if val_str != "missing":
                    unavail_this_poll.append(f"{_sensor_label(sensor)}={val_str}")
                continue

            try:
                val = float(val_str)
            except ValueError:
                continue

            if sensor in previous_values:
                prev = previous_values[sensor]
                delta = abs(val - prev)
                threshold = get_threshold(sensor)
                if delta > threshold:
                    spike_count += 1
                    short = _sensor_label(sensor)
                    msg = f"SPIKE #{spike_count}: {short}: {prev} -> {val} (delta={delta:.1f}, threshold={threshold})"
                    spikes_this_poll.append(msg)

            previous_values[sensor] = val

        elapsed = duration_minutes * 60 - (end_time - time.monotonic())
        remaining = max(0, end_time - time.monotonic())

        if spikes_this_poll:
            print(f"\n[{now}] Poll #{poll_count} ({elapsed / 60:.1f}m elapsed)")
            for sp in spikes_this_poll:
                print(f"  *** {sp}")
        elif poll_count % 10 == 0 or poll_count == 1:
            # Periodic status every ~5 minutes
            key_sensors = (
                ("grid_power", f"sensor.grid_boss_{serials[0]}_grid_power"),
                (
                    "grid_voltage_l1",
                    f"sensor.grid_boss_{serials[0]}_grid_voltage_l1",
                ),
                (
                    "battery_power",
                    f"sensor.18kpv_{serials[1]}_battery_power",
                ),
            )
            key_values = " | ".join(
                f"{label}={previous_values.get(entity_id, '?')}"
                for label, entity_id in key_sensors
            )
            print(
                f"[{now}] Poll #{poll_count} OK | {remaining / 60:.0f}m left | "
                f"spikes={spike_count} | unavail={len(unavail_this_poll)} | "
                f"{key_values}"
            )

        if unavail_this_poll and poll_count <= 3:
            print(f"  Unavailable: {', '.join(unavail_this_poll)}")

        time.sleep(POLL_INTERVAL)

    print("\n" + "=" * 60)
    print("=== MONITORING COMPLETE ===")
    print(f"Duration: {duration_minutes} minutes")
    print(f"Polls: {poll_count}")
    print(f"Total spikes detected: {spike_count}")
    if spike_count == 0:
        print("RESULT: CLEAN — No data spikes detected")
    else:
        print(f"RESULT: {spike_count} SPIKES DETECTED — Review above")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    """Parse explicit runtime device identities."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gridboss-serial", required=True)
    parser.add_argument("--primary-inverter-serial", required=True)
    parser.add_argument("--secondary-inverter-serial", required=True)
    parser.add_argument("--duration-minutes", type=int, default=30)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    runtime_token, runtime_base_url = load_connection_config()
    if not runtime_token:
        print("ERROR: Home Assistant API credentials are not configured")
        sys.exit(1)
    runtime_serials = (
        args.gridboss_serial.lower(),
        args.primary_inverter_serial.lower(),
        args.secondary_inverter_serial.lower(),
    )
    main(
        args.duration_minutes,
        runtime_serials,
        runtime_token,
        runtime_base_url,
    )
