"""Conservative HA-local daily guard policy for released library provenance."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

from homeassistant.util import dt as dt_util
from pylxpweb.provenance import EnergyProvenance, derived_provenance

from .const import SENSOR_TYPES

BALANCE_KEYS = ("yield", "discharging", "grid_import", "charging", "grid_export")

# Mirrors the numeric transport mapper; consumption requires all five operands.
_INVERTER_FIELDS = {
    "yield": "pv_energy_today",
    "charging": "charge_energy_today",
    "discharging": "discharge_energy_today",
    "grid_import": "grid_import_today",
    "grid_export": "grid_export_today",
    "load_energy": "load_energy_today",
    "eps_energy_today_l1": "eps_l1_energy_today",
    "eps_energy_today_l2": "eps_l2_energy_today",
    **{f"pv{i}_yield": f"pv{i}_energy_today" for i in range(1, 7)},
    **{
        f"{name}_energy": f"{name}_energy_today"
        for name in ("inverter", "ac_charge", "eps", "generator")
    },
}


def _local_leaves(record: EnergyProvenance | None) -> list[datetime]:
    if not isinstance(record, EnergyProvenance):
        return []
    if record.source == "derived":
        leaves = [_local_leaves(component) for component in record.components]
        if not leaves or not all(leaves):
            return []
        return [stamp for component in leaves for stamp in component]
    if record.source != "local" or record.acquired_at is None:
        return []
    return [record.acquired_at]


def same_day_sample_time(times: Iterable[datetime | None]) -> datetime | None:
    """Require every contributor on one HA day; preserve the earliest receipt."""
    stamps = list(times)
    if not stamps or any(stamp is None for stamp in stamps):
        return None
    known = [stamp for stamp in stamps if stamp is not None]
    if len({dt_util.as_local(stamp).date() for stamp in known}) != 1:
        return None
    return min(known)


def daily_sample_times(
    sensors: Mapping[str, Any], provenance: Mapping[str, EnergyProvenance]
) -> dict[str, datetime]:
    """Accept only entirely LOCAL field lineage, never HTTP receipt or legacy time.

    This is an acquisition-day policy, not evidence of device reset timezone or
    counter day. Unknown and missing contributors invalidate the whole field.
    """
    result = {}
    for key, value in sensors.items():
        if (
            value is None
            or cast("dict[str, Any]", SENSOR_TYPES.get(key, {})).get("reset_period")
            != "daily"
        ):
            continue
        stamp = same_day_sample_time(_local_leaves(provenance.get(key)))
        if stamp is not None:
            result[key] = stamp
    return result


def mapped_daily_sample_times(
    sensors: Mapping[str, Any],
    provenance: Mapping[str, EnergyProvenance] | None,
    property_map: Mapping[str, str],
    *,
    balance: bool = False,
) -> dict[str, datetime]:
    """Follow the public property mapper, including its consumption override."""
    if not isinstance(provenance, Mapping):
        return {}
    records = {
        key: provenance[prop]
        for prop, key in property_map.items()
        if prop in provenance
    }
    if balance:
        records["consumption"] = derived_provenance(
            "integration:balance", (records.get(key) for key in BALANCE_KEYS)
        )
    return daily_sample_times(sensors, records)


def local_daily_sample_times(
    sensors: dict[str, Any], snapshot: Any
) -> dict[str, datetime]:
    """Map accepted inverter snapshot fields without trusting conversion time."""
    provenance = getattr(snapshot, "provenance", {})
    return mapped_daily_sample_times(
        sensors,
        provenance,
        {field: key for key, field in _INVERTER_FIELDS.items()},
        balance=True,
    )


def aggregate_daily_sample_times(
    sensors: Mapping[str, Any], members: Iterable[Mapping[str, Any]]
) -> dict[str, datetime]:
    """Combine already-qualified field times, retaining every group member."""
    members = list(members)
    result = {}
    for key, value in sensors.items():
        if value is None:
            continue
        stamp = same_day_sample_time(
            member.get("energy_sample_times", {}).get(key)
            if member.get("sensors", {}).get(key) is not None
            else None
            for member in members
        )
        if stamp is not None:
            result[key] = stamp
    return result
