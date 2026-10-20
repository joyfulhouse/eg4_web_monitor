"""Acquisition metadata for daily counters from accepted LOCAL snapshots."""

from datetime import UTC, datetime
from typing import Any, cast

from .const import SENSOR_TYPES


def local_daily_sample_times(
    sensors: dict[str, Any], snapshot: Any
) -> dict[str, datetime]:
    """Preserve the read timestamp; never stamp cache processing as acquisition.

    pylxpweb's local register decoders create naive host-local timestamps.
    astimezone() interprets that host timezone before normalizing to UTC.
    Call only for accepted transport snapshots, never HTTP conversions.
    """
    acquired = getattr(snapshot, "timestamp", None)
    if not isinstance(acquired, datetime):
        return {}
    acquired = acquired.astimezone(UTC)
    return {
        key: acquired
        for key, value in sensors.items()
        if value is not None
        and cast("dict[str, Any]", SENSOR_TYPES.get(key, {})).get("reset_period")
        == "daily"
    }
