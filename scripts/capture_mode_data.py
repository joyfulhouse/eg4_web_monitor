#!/usr/bin/env python3
"""Capture EG4 integration sensor data for cross-mode validation.

Usage: python3 scripts/capture_mode_data.py [mode_name]
Outputs JSON to stdout for piping/comparison.
"""

import json
import os
import sys

import httpx

MODE = sys.argv[1] if len(sys.argv) > 1 else "unknown"
TOKEN = os.environ.get("HA_LONG_LIVED_TOKEN", "")
BASE_URL = os.environ.get("HA_BASE_URL", "http://localhost:8123")

if not TOKEN:
    print("ERROR: Set HA_LONG_LIVED_TOKEN", file=sys.stderr)
    sys.exit(1)

resp = httpx.get(
    f"{BASE_URL}/api/states",
    headers={"Authorization": f"Bearer {TOKEN}"},
    timeout=15,
    follow_redirects=True,
)
resp.raise_for_status()
states = resp.json()

PREFIXES = ["flexboss", "18kpv", "12kpv", "gridboss", "parallel_group", "station_"]
eg4_all = [s for s in states if any(p in s["entity_id"].lower() for p in PREFIXES)]
eg4_sensors = [s for s in eg4_all if s["entity_id"].startswith("sensor.")]

# Categorize
available = [s for s in eg4_all if s["state"] not in ("unavailable", "unknown")]
unavailable = [s for s in eg4_all if s["state"] == "unavailable"]

# Key power sensors (combined + per-leg)
POWER_KEYS = [
    "eps_power",
    "eps_power_l1",
    "eps_power_l2",
    "eps_apparent_power",
    "eps_apparent_power_l1",
    "eps_apparent_power_l2",
    "grid_power",
    "grid_power_l1",
    "grid_power_l2",
    "pv_total_power",
    "pv1_power",
    "pv2_power",
    "inverter_power",
    "inverter_power_l1",
    "inverter_power_l2",
    "battery_power",
    "battery_soc",
    "load_power",
    "load_power_l1",
    "load_power_l2",
    "consumption_power",
    "rectifier_power",
    "rectifier_power_l1",
    "rectifier_power_l2",
    "output_power",
    "total_load_power",
]

power_data = {}
for s in eg4_sensors:
    eid = s["entity_id"]
    for key in POWER_KEYS:
        # Match key at end of entity_id (after last device prefix segment)
        if eid.endswith(f"_{key}"):
            power_data[eid] = {
                "state": s["state"],
                "unit": s["attributes"].get("unit_of_measurement", ""),
            }

result = {
    "mode": MODE,
    "total_entities": len(eg4_all),
    "sensors": len(eg4_sensors),
    "available": len(available),
    "unavailable": len(unavailable),
    "unavailable_entities": sorted(s["entity_id"] for s in unavailable),
    "power_sensors": dict(sorted(power_data.items())),
}

print(json.dumps(result, indent=2))
