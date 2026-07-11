#!/usr/bin/env python3
"""Validate EG4 cloud analytics API response format.

This script tests the actual API response format for the energy analytics
endpoints used by the history reconciliation service.

Usage:
    # With environment variables:
    export EG4_USERNAME="your_username"
    export EG4_PASSWORD="your_password"
    uv run python scripts/validate_analytics_api.py

    # Or with Phase secrets:
    phase run --app claude-code --env development -- uv run python scripts/validate_analytics_api.py

Expected output shows the actual response structure from the EG4 cloud API.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxpweb import LuxpowerClient
except ImportError:
    print("ERROR: pylxpweb not installed. Run: uv add pylxpweb")
    sys.exit(1)


async def main() -> int:
    """Run API validation."""
    username = os.environ.get("EG4_USERNAME")
    password = os.environ.get("EG4_PASSWORD")

    if not username or not password:
        print("ERROR: EG4_USERNAME and EG4_PASSWORD environment variables required")
        print("\nSet them via:")
        print("  export EG4_USERNAME='your_username'")
        print("  export EG4_PASSWORD='your_password'")
        return 1

    print(f"Connecting as: {username}")
    print("=" * 60)

    try:
        async with LuxpowerClient(username, password) as client:
            # Get stations
            stations = await client.plants.get_plant_list()
            print(f"\nFound {len(stations)} station(s)")

            if not stations:
                print("ERROR: No stations found")
                return 1

            station = stations[0]
            print(f"Using station: {station.name} (ID: {station.id})")

            # Load station to get inverters
            await station.load(client)

            if not station.all_inverters:
                print("ERROR: No inverters found")
                return 1

            inverter = station.all_inverters[0]
            serial = inverter.serial
            print(f"Using inverter: {inverter.model} ({serial})")

            # Test dates
            today = datetime.now()
            yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            (today - timedelta(days=30)).strftime("%Y-%m-%d")

            # Test energy types
            energy_types = [
                "eInvDay",  # Solar production
                "eToUserDay",  # Grid import
                "eToGridDay",  # Grid export
            ]

            print("\n" + "=" * 60)
            print("TESTING dayColumn ENDPOINT (hourly energy)")
            print("=" * 60)

            for energy_type in energy_types:
                print(f"\n--- {energy_type} for {yesterday} ---")

                response = await client.analytics.get_energy_day_breakdown(
                    serial,
                    yesterday,
                    energy_type,
                    parallel=False,
                )

                print(f"Response keys: {list(response.keys())}")
                print(f"Success: {response.get('success')}")

                # Check data structure
                data = response.get("data")
                data_points = response.get("dataPoints")

                print(f"'data' key exists: {data is not None}")
                print(f"'dataPoints' key exists: {data_points is not None}")

                points = data or data_points
                if points is None:
                    print("WARNING: No data found in response")
                    continue

                print(f"Data type: {type(points).__name__}")

                if isinstance(points, list):
                    print(f"List length: {len(points)}")
                    if points:
                        sample = points[0]
                        print(f"Sample item type: {type(sample).__name__}")
                        if isinstance(sample, dict):
                            print(f"Sample keys: {list(sample.keys())}")
                            print(f"Sample value: {json.dumps(sample, indent=2)}")

                            # Check for expected fields
                            has_hour = "hour" in sample
                            has_energy = "energy" in sample
                            has_period = "period" in sample
                            has_value = "value" in sample

                            print("\nField analysis:")
                            print(f"  'hour' field: {has_hour}")
                            print(f"  'energy' field: {has_energy}")
                            print(f"  'period' field: {has_period}")
                            print(f"  'value' field: {has_value}")

                            if has_hour and has_energy:
                                print("  => Format 1: {{hour, energy}} ✓")
                            elif has_period and has_value:
                                print("  => Format 2: {{period, value}} ✓")
                            else:
                                print("  => Unknown format!")

                        # Show first 3 data points
                        print("\nFirst 3 data points:")
                        for i, p in enumerate(points[:3]):
                            print(f"  [{i}]: {json.dumps(p)}")

                        # Calculate total
                        total = 0
                        for p in points:
                            if isinstance(p, dict):
                                val = p.get("energy") or p.get("value") or 0
                                total += val
                        print(f"\nTotal for day: {total} Wh ({total / 1000:.2f} kWh)")

                elif isinstance(points, dict):
                    print(f"Dict keys: {list(points.keys())}")
                    print("  => Format 3: {{timestamps, values}}")

                    timestamps = points.get("timestamps", [])
                    values = points.get("values", [])
                    print(f"  timestamps: {len(timestamps)} items")
                    print(f"  values: {len(values)} items")

                    if timestamps and values:
                        print("\nFirst 3 entries:")
                        for i, (ts, val) in enumerate(zip(timestamps[:3], values[:3])):
                            print(f"  [{i}]: {ts} = {val}")

                # Add small delay between API calls
                await asyncio.sleep(0.5)

            print("\n" + "=" * 60)
            print("TESTING monthColumn ENDPOINT (daily energy)")
            print("=" * 60)

            # Get current month data
            response = await client.analytics.get_energy_month_breakdown(
                serial,
                today.year,
                today.month,
                "eInvDay",
                parallel=False,
            )

            print(f"\nResponse keys: {list(response.keys())}")
            data = response.get("data") or response.get("dataPoints")

            if data:
                print(f"Data type: {type(data).__name__}")
                if isinstance(data, list) and data:
                    print(f"List length: {len(data)} days")
                    sample = data[0]
                    if isinstance(sample, dict):
                        print(f"Sample keys: {list(sample.keys())}")
                        print(f"Sample value: {json.dumps(sample, indent=2)}")

            print("\n" + "=" * 60)
            print("VALIDATION COMPLETE")
            print("=" * 60)
            print("\nUse this information to verify the services.py implementation")
            print("handles the correct response format.")

            return 0

    except Exception as err:
        print(f"\nERROR: {err}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
