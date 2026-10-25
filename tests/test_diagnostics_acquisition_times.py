"""Diagnostics distinguish captured time from retained acquisition evidence."""

from datetime import UTC, datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.diagnostics import (
    _jsonable,
    async_get_config_entry_diagnostics,
)


def test_only_aware_datetimes_become_acquisition_strings():
    """A timezone must be known before a timestamp can support local-day claims."""
    acquired = datetime(2026, 10, 25, 23, 59, 58, 123456, timezone(timedelta(hours=-7)))
    assert _jsonable(acquired) == "2026-10-25T23:59:58.123456-07:00"
    assert _jsonable(acquired.replace(tzinfo=None)) == "<datetime>"
    assert _jsonable(object()) == "<object>"


@pytest.mark.parametrize("plant_id", ["12345", "2026", "123456"])
async def test_repeated_downloads_do_not_refresh_cached_acquisition(hass, plant_id):
    """Downloads on opposite sides of midnight keep the original sample age."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "http",
            "plant_id": plant_id,
            "username": "synthetic_user",
            "password": "synthetic_password",
        },
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    entry.runtime_data = coordinator
    acquired = datetime(2026, 10, 26, 6, 59, 0, 123456, tzinfo=UTC)
    coordinator.data = {
        "devices": {
            "SYNTH00101": {
                "sensors": {"yield": 12.3},
                "plant_reference": f"station_{plant_id}",
                "energy_sample_times": {"yield": acquired},
                "energy_evidence": {
                    "yield": {
                        "value": 12.3,
                        "lineage": {"source": "local", "acquired_at": acquired},
                    }
                },
            }
        }
    }
    before = datetime(2026, 10, 26, 6, 59, 30, tzinfo=UTC)
    after = datetime(2026, 10, 26, 7, 1, tzinfo=UTC)
    results = []
    for captured in (before, after):
        with patch("homeassistant.util.dt.utcnow", return_value=captured):
            results.append(await async_get_config_entry_diagnostics(hass, entry))

    assert results[0]["captured_at"] == before.isoformat()
    assert results[1]["captured_at"] == after.isoformat()
    assert results[0]["coordinator"]["data"] == results[1]["coordinator"]["data"]
    device = results[1]["coordinator"]["data"]["devices"]["SN_1"]
    assert device["energy_sample_times"]["yield"] == acquired.isoformat()
    assert (
        device["energy_evidence"]["yield"]["lineage"]["acquired_at"]
        == acquired.isoformat()
    )
    assert device["sensors"]["yield"] == 12.3
    assert device["plant_reference"] == "station_PLANT_1"
    assert "SYNTH00101" not in json.dumps(results)
    assert (
        coordinator.data["devices"]["SYNTH00101"]["energy_sample_times"]["yield"]
        is acquired
    )
