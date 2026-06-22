"""Regression tests for issue #253 — duplicate "Has Runtime Data" sensors.

Two sensor keys mapped onto the SAME inverter device with the identical
display name "Has Runtime Data":

* ``has_data`` — the canonical diagnostic (in DIAGNOSTIC_DEVICE_SENSOR_KEYS,
  maintained on the offline path, and part of the register contract harness).
* ``inverter_has_runtime_data`` — a redundant duplicate mapping the identical
  pylxpweb value (``_runtime is not None or _transport_runtime is not None``)
  plus the dead cloud ``hasRuntimeData`` field.

Both rendered the same name, slugged to the same ``_has_runtime_data``
entity_id tail, but carried different unique_ids (``_has_data`` vs
``_inverter_has_runtime_data``) — so every inverter accumulated two active
"Has Runtime Data" entities. The fix removes ``inverter_has_runtime_data`` and
purges its orphaned registry entries.
"""

from __future__ import annotations

from collections import Counter

import homeassistant.helpers.entity_registry as er
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.const.sensors.inverter import SENSOR_TYPES
from custom_components.eg4_web_monitor.const.sensors.mappings import (
    INVERTER_ENERGY_FIELD_MAPPING,
    PARALLEL_GROUP_FIELD_MAPPING,
)
from custom_components.eg4_web_monitor.coordinator_mixins import DeviceProcessingMixin


def _inverter_sensor_display_names() -> list[tuple[str, str]]:
    """(display_name, sensor_key) for every inverter-device sensor key.

    Every key produced by the HTTP inverter property map lands on the single
    inverter device, so any two keys sharing a display name collide onto one
    entity_id.
    """
    property_map = DeviceProcessingMixin._get_inverter_property_map()
    pairs: list[tuple[str, str]] = []
    for key in set(property_map.values()):
        definition = SENSOR_TYPES.get(key)
        if isinstance(definition, dict) and definition.get("name"):
            pairs.append((definition["name"], key))
    return pairs


def test_no_duplicate_display_names_on_inverter_device() -> None:
    """No two inverter-device sensor keys may share a display name (#253)."""
    pairs = _inverter_sensor_display_names()
    counts = Counter(name for name, _ in pairs)
    collisions = {
        name: sorted(key for n, key in pairs if n == name)
        for name, count in counts.items()
        if count > 1
    }
    assert not collisions, (
        f"Inverter sensors with colliding display names: {collisions}"
    )


def test_duplicate_runtime_data_key_removed() -> None:
    """The redundant ``inverter_has_runtime_data`` sensor key is gone (#253)."""
    assert "inverter_has_runtime_data" not in SENSOR_TYPES

    property_map = DeviceProcessingMixin._get_inverter_property_map()
    assert "inverter_has_runtime_data" not in property_map.values()

    # The dead cloud field mapping is removed from both field maps.
    assert "hasRuntimeData" not in PARALLEL_GROUP_FIELD_MAPPING
    assert "hasRuntimeData" not in INVERTER_ENERGY_FIELD_MAPPING


def test_canonical_has_data_sensor_retained() -> None:
    """The canonical ``has_data`` sensor survives with its display name (#253)."""
    assert "has_data" in SENSOR_TYPES
    assert SENSOR_TYPES["has_data"]["name"] == "Has Runtime Data"

    property_map = DeviceProcessingMixin._get_inverter_property_map()
    assert property_map.get("has_data") == "has_data"


def test_cleanup_suffix_matches_duplicate_but_not_survivor() -> None:
    """Cleanup suffix targets the duplicate unique_id and spares ``has_data``."""
    from custom_components.eg4_web_monitor import (
        _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES,
    )

    serial = "1234567890"
    duplicate_uid = f"{serial}_inverter_has_runtime_data"
    survivor_uid = f"{serial}_has_data"

    assert any(
        duplicate_uid.endswith(suffix)
        for suffix in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
    )
    assert not any(
        survivor_uid.endswith(suffix)
        for suffix in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
    )


async def test_cleanup_removes_orphaned_duplicate_entity(hass: HomeAssistant) -> None:
    """The setup-time cleanup removes only the orphaned duplicate (#253)."""
    from custom_components.eg4_web_monitor import (
        _async_cleanup_duplicate_runtime_data_entities,
    )

    entry = MockConfigEntry(domain=DOMAIN, entry_id="issue_253_entry")
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    serial = "1234567890"
    duplicate = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_inverter_has_runtime_data",
        config_entry=entry,
    )
    survivor = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_has_data",
        config_entry=entry,
    )

    _async_cleanup_duplicate_runtime_data_entities(hass, entry)

    assert registry.async_get(duplicate.entity_id) is None
    assert registry.async_get(survivor.entity_id) is not None
