"""Tests for linking child devices to their parent (via_device vs via_device_id)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.eg4_web_monitor import coordinator_mixins
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator_mixins import DeviceInfoMixin

SERIAL = "1234567890"


def _mixin() -> DeviceInfoMixin:
    mixin = DeviceInfoMixin.__new__(DeviceInfoMixin)
    mixin.hass = MagicMock()  # type: ignore[attr-defined]
    mixin.entry = MagicMock(entry_id="entry1")  # type: ignore[attr-defined]
    mixin.data = {  # type: ignore[attr-defined]
        "devices": {
            SERIAL: {
                "type": "inverter",
                "model": "18kPV",
                "sensors": {"battery_bank_count": 1, "battery_bank_soc": 50},
                "batteries": {f"{SERIAL}-01": {"battery_model": "LL"}},
            }
        }
    }
    return mixin


def test_legacy_ha_keeps_via_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """HA without the lookup helper (< 2026.8) gets the identifier tuple."""
    monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", None)
    assert _mixin().via_device_link("parent") == {"via_device": (DOMAIN, "parent")}


def test_new_ha_uses_via_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def lookup(hass: Any, identifier: Any, *, config_entry_id: str) -> str:
        calls.append((identifier, config_entry_id))
        return "device-id-1"

    monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", lookup)
    assert _mixin().via_device_link("parent") == {"via_device_id": "device-id-1"}
    # Scoped to this config entry, as HA requires.
    assert calls == [((DOMAIN, "parent"), "entry1")]


def test_unregistered_parent_is_unlinked_and_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing parent yields no link, and the next lookup retries."""
    parent_id: str | None = None

    def lookup(hass: Any, identifier: Any, *, config_entry_id: str) -> str:
        if parent_id is None:
            raise ValueError("no such device")
        return parent_id

    monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", lookup)
    mixin = _mixin()

    bank = mixin.get_battery_bank_device_info(SERIAL)
    battery = mixin.get_battery_device_info(SERIAL, f"{SERIAL}-01")
    assert bank is not None and "via_device_id" not in bank
    assert battery is not None and "via_device_id" not in battery

    parent_id = "registered-now"
    bank = mixin.get_battery_bank_device_info(SERIAL)
    battery = mixin.get_battery_device_info(SERIAL, f"{SERIAL}-01")
    assert bank is not None and dict(bank).get("via_device_id") == "registered-now"
    assert battery is not None
    assert dict(battery).get("via_device_id") == "registered-now"
    for info in (bank, battery):
        assert "via_device" not in info


def test_parallel_group_member_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        coordinator_mixins,
        "_get_device_id_by_identifier",
        lambda hass, identifier, *, config_entry_id: f"id-of-{identifier[1]}",
    )
    mixin = _mixin()
    mixin.station = None  # type: ignore[attr-defined]
    mixin.data["devices"]["parallel_group_a"] = {  # type: ignore[attr-defined]
        "type": "parallel_group",
        "member_serials": [SERIAL],
    }
    info = mixin.get_device_info(SERIAL)
    assert info is not None
    assert dict(info).get("via_device_id") == "id-of-parallel_group_a"
    assert "via_device" not in info
