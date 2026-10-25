"""Detached daily-energy lineage for diagnostics, never a guard-policy input."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any, cast

from homeassistant.util import dt as dt_util
from pylxpweb.provenance import EnergyProvenance

from .const import SENSOR_TYPES
from .energy_provenance import BALANCE_KEYS, _INVERTER_FIELDS


def _daily(key: str) -> bool:
    return (
        cast("dict[str, Any]", SENSOR_TYPES.get(key, {})).get("reset_period") == "daily"
    )


def _lineage(record: EnergyProvenance | None) -> dict[str, Any] | None:
    if not isinstance(record, EnergyProvenance):
        return None
    # source_id and field_name can contain serials, URLs or group names. These
    # diagnostics need contributor structure and acquisition time, not identity.
    return {
        "source": record.source,
        "acquired_at": record.acquired_at,
        "components": [_lineage(component) for component in record.components],
    }


def _evidence(value: Any, lineage: dict[str, Any] | None) -> dict[str, Any]:
    reasons: set[str] = set()
    local_times: list[datetime] = []

    def inspect(node: dict[str, Any] | None) -> None:
        if node is None:
            reasons.add("missing")
        elif node["source"] == "derived":
            if not node["components"]:
                reasons.add("empty")
            for component in node["components"]:
                inspect(component)
        elif node["source"] != "local":
            reasons.add("http" if node["source"] == "http" else "unknown")
        elif node["acquired_at"] is None:
            reasons.add("missing_acquisition_time")
        else:
            local_times.append(node["acquired_at"])

    if value is None:
        lineage = None
        reasons.add("no_value")
    else:
        inspect(lineage)
        if len({dt_util.as_local(stamp).date() for stamp in local_times}) > 1:
            reasons.add("mixed_day")
    return {
        "value": value,
        "lineage": lineage,
        "accepted_for_daily_guard": not reasons,
        "rejection_reasons": sorted(reasons),
    }


def mapped_daily_evidence(
    sensors: Mapping[str, Any],
    provenance: Mapping[str, EnergyProvenance] | None,
    property_map: Mapping[str, str],
    *,
    balance: bool = False,
) -> dict[str, Any]:
    """Snapshot exact selected field records; never synthesize acquisition time."""
    provenance = provenance if isinstance(provenance, Mapping) else {}
    records = {
        key: _lineage(provenance.get(prop)) for prop, key in property_map.items()
    }
    if balance:
        records["consumption"] = {
            "source": "derived",
            "acquired_at": None,
            "components": [records.get(key) for key in BALANCE_KEYS],
        }
    return {
        key: _evidence(value, records.get(key))
        for key, value in sensors.items()
        if _daily(key)
    }


def local_daily_evidence(sensors: Mapping[str, Any], snapshot: Any) -> dict[str, Any]:
    """Use the same inverter field mapping as the existing daily guard adapter."""
    return mapped_daily_evidence(
        sensors,
        getattr(snapshot, "provenance", {}),
        {field: key for key, field in _INVERTER_FIELDS.items()},
        balance=True,
    )


def _retained_lineage(
    key: str, sensors: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any] | None:
    record = evidence.get(key)
    value = sensors.get(key)
    if value is None or not isinstance(record, dict) or record.get("value") != value:
        return None
    return cast("dict[str, Any] | None", deepcopy(record.get("lineage")))


def aggregate_daily_evidence(
    sensors: Mapping[str, Any], members: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Keep all numeric contributors, including cached or missing evidence."""
    members = list(members)
    return {
        key: _evidence(
            value,
            {
                "source": "derived",
                "acquired_at": None,
                "components": [
                    _retained_lineage(
                        key,
                        member.get("sensors", {}),
                        member.get("energy_evidence", {}),
                    )
                    for member in members
                ],
            },
        )
        for key, value in sensors.items()
        if _daily(key)
    }


def reconcile_daily_evidence(data: dict[str, Any]) -> None:
    """Discard evidence when later processing blanks or replaces its value."""
    sensors = data.get("sensors", {})
    evidence = data.get("energy_evidence", {})
    data["energy_evidence"] = {
        key: _evidence(value, _retained_lineage(key, sensors, evidence))
        for key, value in sensors.items()
        if _daily(key)
    }


def carry_daily_evidence(
    target: dict[str, Any], previous: Mapping[str, Any], key: str
) -> None:
    """Carry lineage only at the same point its cached numeric value is copied."""
    if _daily(key):
        target.setdefault("energy_evidence", {})[key] = _evidence(
            target["sensors"].get(key),
            _retained_lineage(
                key, previous.get("sensors", {}), previous.get("energy_evidence", {})
            ),
        )


def overlay_gridboss_evidence(
    sensors: Mapping[str, Any],
    gb_sensors: Mapping[str, Any],
    evidence: dict[str, Any],
    gb_evidence: Mapping[str, Any],
    overlay_map: Mapping[str, str],
) -> None:
    """Follow the CT numeric overlay, preserving each selected phase's tree."""
    for gb_key, key in overlay_map.items():
        if _daily(key) and gb_sensors.get(gb_key) is not None:
            evidence[key] = _evidence(
                sensors.get(key), _retained_lineage(gb_key, gb_sensors, gb_evidence)
            )
    evidence["consumption"] = _evidence(
        sensors.get("consumption"),
        {
            "source": "derived",
            "acquired_at": None,
            "components": [
                _retained_lineage(key, gb_sensors, gb_evidence)
                for key in ("ups_today", "load_today")
            ],
        },
    )
