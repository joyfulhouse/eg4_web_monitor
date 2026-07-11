#!/usr/bin/env python3
"""Monitor EG4 entities for data spikes over time.

Polls HA API every 30 seconds, records values for key sensors,
and flags any readings that look like spikes (sudden large jumps).
"""

import os
import sys
import time
from datetime import datetime

import httpx

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

# Load from .env
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
TOKEN = ""
BASE_URL = "http://localhost:8123"

if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("HA_LONG_LIVED_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("HA_BASE_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"')

if not TOKEN:
    print("ERROR: No HA_LONG_LIVED_TOKEN found in .env")
    sys.exit(1)

# Sensors to monitor for spikes
SPIKE_SENSORS = [
    # GridBOSS power/voltage (most spike-prone)
    "sensor.grid_boss_4524850115_grid_power",
    "sensor.grid_boss_4524850115_grid_power_l1",
    "sensor.grid_boss_4524850115_grid_power_l2",
    "sensor.grid_boss_4524850115_grid_voltage_l1",
    "sensor.grid_boss_4524850115_grid_voltage_l2",
    "sensor.grid_boss_4524850115_grid_frequency",
    "sensor.grid_boss_4524850115_load_power",
    "sensor.grid_boss_4524850115_smart_load_power",
    "sensor.grid_boss_4524850115_grid_import_total",
    "sensor.grid_boss_4524850115_grid_export_total",
    "sensor.grid_boss_4524850115_consumption_total",
    # Inverter power sensors
    "sensor.18kpv_4512670118_power_output",
    "sensor.18kpv_4512670118_battery_power",
    "sensor.18kpv_4512670118_grid_voltage_l1",
    "sensor.18kpv_4512670118_grid_frequency",
    "sensor.flexboss21_52842p0581_power_output",
    "sensor.flexboss21_52842p0581_battery_power",
    "sensor.flexboss21_52842p0581_grid_voltage_l1",
    "sensor.flexboss21_52842p0581_grid_frequency",
    # Battery bank aggregate
    "sensor.battery_bank_4512670118_battery_soc",
    "sensor.battery_bank_52842p0581_battery_soc",
    # Charge rate sensors (new)
    "sensor.battery_bank_4512670118_battery_bank_charge_rate",
    "sensor.battery_bank_52842p0581_battery_bank_charge_rate",
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

DURATION_MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 30
POLL_INTERVAL = 30  # seconds

previous_values: dict[str, float] = {}
spike_count = 0
poll_count = 0


def get_threshold(entity_id: str) -> float:
    for key, thresh in SPIKE_THRESHOLDS.items():
        if key in entity_id:
            return thresh
    return 50000  # very permissive default


def fetch_states() -> dict[str, str]:
    resp = httpx.get(
        f"{BASE_URL}/api/states",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=10,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    return {s["entity_id"]: s["state"] for s in data}


def main() -> None:
    global spike_count, poll_count
    end_time = time.monotonic() + DURATION_MINUTES * 60
    print("=== EG4 Spike Monitor ===")
    print(f"Duration: {DURATION_MINUTES} minutes, interval: {POLL_INTERVAL}s")
    print(f"Monitoring {len(SPIKE_SENSORS)} sensors")
    print(f"Started at {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    while time.monotonic() < end_time:
        poll_count += 1
        now = datetime.now().strftime("%H:%M:%S")
        try:
            states = fetch_states()
        except Exception as e:
            print(f"[{now}] FETCH ERROR: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        spikes_this_poll: list[str] = []
        unavail_this_poll: list[str] = []

        for sensor in SPIKE_SENSORS:
            val_str = states.get(sensor, "missing")
            if val_str in ("unavailable", "unknown", "missing"):
                if val_str != "missing":
                    unavail_this_poll.append(f"{sensor.split('.')[-1]}={val_str}")
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
                    short = sensor.split(".")[-1]
                    msg = f"SPIKE #{spike_count}: {short}: {prev} -> {val} (delta={delta:.1f}, threshold={threshold})"
                    spikes_this_poll.append(msg)

            previous_values[sensor] = val

        elapsed = DURATION_MINUTES * 60 - (end_time - time.monotonic())
        remaining = max(0, end_time - time.monotonic())

        if spikes_this_poll:
            print(f"\n[{now}] Poll #{poll_count} ({elapsed / 60:.1f}m elapsed)")
            for sp in spikes_this_poll:
                print(f"  *** {sp}")
        elif poll_count % 10 == 0 or poll_count == 1:
            # Periodic status every ~5 minutes
            key_vals = []
            for s in [
                "sensor.grid_boss_4524850115_grid_power",
                "sensor.grid_boss_4524850115_grid_voltage_l1",
                "sensor.18kpv_4512670118_battery_power",
            ]:
                v = previous_values.get(s, "?")
                key_vals.append(
                    f"{s.split('_')[-1] if isinstance(v, str) else s.split('4524850115_')[-1].split('4512670118_')[-1]}={v}"
                )
            print(
                f"[{now}] Poll #{poll_count} OK | {remaining / 60:.0f}m left | spikes={spike_count} | unavail={len(unavail_this_poll)}"
            )

        if unavail_this_poll and poll_count <= 3:
            print(f"  Unavailable: {', '.join(unavail_this_poll)}")

        time.sleep(POLL_INTERVAL)

    print("\n" + "=" * 60)
    print("=== MONITORING COMPLETE ===")
    print(f"Duration: {DURATION_MINUTES} minutes")
    print(f"Polls: {poll_count}")
    print(f"Total spikes detected: {spike_count}")
    if spike_count == 0:
        print("RESULT: CLEAN — No data spikes detected")
    else:
        print(f"RESULT: {spike_count} SPIKES DETECTED — Review above")
    print("=" * 60)


if __name__ == "__main__":
    main()
