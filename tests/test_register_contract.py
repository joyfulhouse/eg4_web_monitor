"""Cross-repo seam contract: integration ↔ pylxpweb.

The coordinator reads pylxpweb device/dataclass attributes by NAME through the
``_get_*_property_map()`` tables in ``coordinator_mixins`` (consumed via
``getattr`` in ``_map_device_properties``).  When pylxpweb renames or removes an
attribute, ``getattr`` silently returns ``None`` and the corresponding Home
Assistant sensor goes permanently unavailable — a silent regression that no
existing test catches because the coordinator tests feed ``MagicMock`` objects
that answer to ANY attribute name.

This test asserts every attribute the property maps read actually exists on the
real pylxpweb class it is applied to, so a future pylxpweb bump that drops or
renames a consumed attribute fails CI here instead of in production.

It is the integration half of the register-derived contract harness (the
pylxpweb half lives in ``pylxpweb/tests/unit/test_register_contract.py``).
"""

from __future__ import annotations

import pytest
from pylxpweb.devices import (
    BaseInverter,
    Battery,
    BatteryBank,
    MIDDevice,
    ParallelGroup,
)

from custom_components.eg4_web_monitor.coordinator_mixins import DeviceProcessingMixin

# -------------------------------------------------------------------------
# Pre-existing seam gaps: attributes a property map reads that the pylxpweb
# class does NOT expose, so the sensor is only populated via a different
# (cloud/camelCase) path or not at all.  Each entry is DEBT, not design —
# keep this set SHRINKING.  Tracked in beads (see issue refs).
# -------------------------------------------------------------------------
KNOWN_SEAM_GAPS: dict[tuple[str, str], str] = {
    # Empty: the prior gaps (inverter.power_rating_text / has_runtime_data,
    # battery_bank.cycle_count) were closed in eg4-ohz by exposing honest
    # device properties on pylxpweb, so the device-object path now resolves
    # them for real.  Keep this set SHRINKING — add an entry only with a
    # tracking issue, and `test_known_seam_gaps_are_still_gaps` guards against
    # stale entries pylxpweb has since provided.
}

# (label, property_map, target pylxpweb class the map is applied to)
_PROPERTY_MAP_TARGETS = [
    ("inverter", DeviceProcessingMixin._get_inverter_property_map(), BaseInverter),
    ("battery", DeviceProcessingMixin._get_battery_property_map(), Battery),
    (
        "battery_bank",
        DeviceProcessingMixin._get_battery_bank_property_map(),
        BatteryBank,
    ),
    (
        "parallel_group",
        DeviceProcessingMixin._get_parallel_group_property_map(),
        ParallelGroup,
    ),
    ("mid_device", DeviceProcessingMixin._get_mid_device_property_map(), MIDDevice),
]


@pytest.mark.parametrize(
    ("label", "property_map", "cls"),
    _PROPERTY_MAP_TARGETS,
    ids=[t[0] for t in _PROPERTY_MAP_TARGETS],
)
def test_property_map_sources_exist_on_pylxpweb_class(
    label: str, property_map: dict[str, str], cls: type
) -> None:
    """Every property-map source attribute resolves on its pylxpweb class."""
    offenders = [
        src
        for src in property_map
        if not hasattr(cls, src) and (label, src) not in KNOWN_SEAM_GAPS
    ]
    assert not offenders, (
        f"{label} property map reads attributes missing from "
        f"pylxpweb {cls.__name__} (silent None / seam drift):\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_known_seam_gaps_are_still_gaps() -> None:
    """Keep the debt list honest: a KNOWN_SEAM_GAP that pylxpweb now provides
    must be removed so the real contract takes over."""
    target_by_label = {label: cls for label, _, cls in _PROPERTY_MAP_TARGETS}
    resolved: list[str] = []
    for (label, attr), _reason in KNOWN_SEAM_GAPS.items():
        cls = target_by_label[label]
        if hasattr(cls, attr):
            resolved.append(
                f"{label}.{attr} now exists on {cls.__name__}; drop it from KNOWN_SEAM_GAPS"
            )
    assert not resolved, "Stale KNOWN_SEAM_GAPS entries:\n  " + "\n  ".join(resolved)
