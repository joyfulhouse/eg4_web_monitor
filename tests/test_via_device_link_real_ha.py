"""Parent links against the REAL HA 2026.8+ device registry (skipped on older HA).

tests/test_via_device_link.py covers the branching with a stand-in lookup; this
module exercises HA's own helper, entity platform and websocket rename, which
only exist from HA 2026.8.0b0.  Run it with an HA >= 2026.9 test environment
(Python 3.14) to cover the production code path.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
)

from custom_components.eg4_web_monitor import coordinator_mixins
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator_mixins import DeviceInfoMixin

pytestmark = pytest.mark.skipif(
    not hasattr(dr, "async_get_device_id_by_identifier"),
    reason="needs HA >= 2026.8.0b0 (via_device_id)",
)

SERIAL = "1234567890"


def _mixin(hass: HomeAssistant, entry: MockConfigEntry) -> DeviceInfoMixin:
    mixin = DeviceInfoMixin.__new__(DeviceInfoMixin)
    mixin.hass = hass  # type: ignore[attr-defined]
    mixin.entry = entry  # type: ignore[attr-defined]
    mixin.station = None  # type: ignore[attr-defined]
    mixin.data = {  # type: ignore[attr-defined]
        "devices": {
            SERIAL: {
                "type": "inverter",
                "model": "18kPV",
                "sensors": {"battery_bank_count": 1, "battery_bank_soc": 50},
            }
        }
    }
    return mixin


class _Inverter(Entity):
    _attr_has_entity_name = True
    _attr_name = "status"
    _attr_unique_id = "inverter_u"

    def __init__(self, mixin: DeviceInfoMixin) -> None:
        self._mixin = mixin

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._mixin.get_device_info(SERIAL)


class _Bank(Entity):
    _attr_has_entity_name = True
    _attr_name = "soc"

    def __init__(self, mixin: DeviceInfoMixin, unique_id: str = "bank_u") -> None:
        self._mixin = mixin
        self._attr_unique_id = unique_id

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._mixin.get_battery_bank_device_info(SERIAL)


def _platform(hass: HomeAssistant, entry: MockConfigEntry) -> MockEntityPlatform:
    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    platform.config_entry = entry
    return platform


async def test_legacy_via_device_entity_is_dropped(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pins why the fix exists.

    On HA 2026.9+ the old ``via_device`` link raises when no integration frame
    is on the stack (as for an add that resumes after ``update_before_add``
    suspends) or core is (a UI entity-ID rename).  The entity platform logs
    "Error adding entity" and the entity is silently not added.
    """
    monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", None)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    mixin = _mixin(hass, entry)
    platform = _platform(hass, entry)
    await platform.async_add_entities([_Inverter(mixin)])
    await platform.async_add_entities([_Bank(mixin)])

    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "bank_u") is None
    assert any(
        "deprecated `via_device`" in str(record.exc_info[1])
        for record in caplog.records
        if record.exc_info
    )


async def test_rename_readds_entity(hass: HomeAssistant, hass_ws_client: Any) -> None:
    """A UI/websocket entity-ID rename re-adds the child entity."""
    assert await async_setup_component(hass, "config", {})
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    mixin = _mixin(hass, entry)
    platform = _platform(hass, entry)
    await platform.async_add_entities([_Inverter(mixin)])
    await platform.async_add_entities([_Bank(mixin)])
    await hass.async_block_till_done()

    devices = dr.async_get(hass)
    inverter = devices.async_get_device_by_identifier((DOMAIN, SERIAL), entry.entry_id)
    bank = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_battery_bank"), entry.entry_id
    )
    assert inverter is not None and bank is not None
    assert bank.via_device_id == inverter.id

    entity = next(
        e for e in er.async_get(hass).entities.values() if e.unique_id == "bank_u"
    )
    mixin.clear_device_info_caches()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "config/entity_registry/update",
            "entity_id": entity.entity_id,
            "new_entity_id": "sensor.renamed_bank",
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    assert hass.states.get("sensor.renamed_bank") is not None


async def test_unregistered_parent_warns_once(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    mixin = _mixin(hass, entry)
    platform = _platform(hass, entry)
    with caplog.at_level(logging.WARNING):
        await platform.async_add_entities([_Bank(mixin, "b1"), _Bank(mixin, "b2")])
    warnings = [r for r in caplog.records if "is not registered yet" in r.getMessage()]
    assert len(warnings) == 1
    bank = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_battery_bank"), entry.entry_id
    )
    assert bank is not None and bank.via_device_id is None
