"""Tests for GridBOSS smart port devices."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import homeassistant.helpers.entity_registry as er
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import EntityPlatform
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import (
    _async_cleanup_stale_smart_port_entities,
    coordinator_mixins,
)
from custom_components.eg4_web_monitor import sensor as sensor_platform
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.coordinator_mappings import (
    GRIDBOSS_SMART_PORT_AGGREGATE_KEYS,
    GRIDBOSS_SMART_PORT_DYNAMIC_KEYS,
    GRIDBOSS_SMART_PORT_KEY_TO_PORT,
    SMART_PORT_VALIDATED_KEY,
)
from custom_components.eg4_web_monitor.coordinator_mixins import DeviceInfoMixin
from custom_components.eg4_web_monitor.select import EG4SmartPortModeSelect
from custom_components.eg4_web_monitor.sensor import (
    EG4SmartPortSensor,
    _create_simple_device_sensors,
    _create_smart_port_sensors,
)
from custom_components.eg4_web_monitor.smart_port_devices import (
    PORT_SENSOR_SPECS,
    PORT_UNUSED,
    PortSensorEnablement,
    async_migrate_to_port_sensors,
    resolve_port_mode,
)

GB = "9876543210"
GB2 = "1234A56789"
INTEGRATION = er.RegistryEntryDisabler.INTEGRATION
SPEC = {spec.id_suffix: spec for spec in PORT_SENSOR_SPECS}


def _statuses(*modes: str, validated: bool = True) -> dict[str, Any]:
    """Port statuses for ports 1..len(modes), as a filtered cycle leaves them."""
    sensors: dict[str, Any] = {
        f"smart_port{port}_status": mode for port, mode in enumerate(modes, 1)
    }
    if validated:
        sensors[SMART_PORT_VALIDATED_KEY] = True
    return sensors


def _gridboss(sensors: dict) -> dict:
    return {"type": "gridboss", "model": "Grid Boss", "sensors": sensors}


class _Coordinator(DeviceInfoMixin):
    """Coordinator double with the REAL device-info code."""

    def __init__(
        self, hass: HomeAssistant | None, devices: dict, *, local: bool = False
    ) -> None:
        self.hass = hass
        self.entry = MagicMock(entry_id="entry1")
        self.data: dict[str, Any] = {"devices": devices}
        self.last_update_success = True
        self.listeners: list[Any] = []
        self._local = local

    def _get_parallel_group_for_device(self, device_serial: str) -> str | None:
        return None

    def has_configured_local_transport(self, serial: str) -> bool:
        return self._local

    def async_add_listener(self, update_callback: Any, context: Any = None) -> Any:
        self.listeners.append(update_callback)
        return lambda: None

    def is_transport_link_down(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def fire(self, times: int = 1) -> None:
        for _ in range(times):
            for listener in list(self.listeners):
                listener()


def _platform(hass: HomeAssistant, entry: MockConfigEntry, domain: str):
    platform = EntityPlatform(
        hass=hass,
        logger=MagicMock(),
        domain=domain,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    return platform


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return entry


def _seed(
    hass: HomeAssistant, entry: MockConfigEntry, unique_id: str, entity_id: str, **kw
) -> er.RegistryEntry:
    domain, object_id = entity_id.split(".")
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        unique_id,
        config_entry=entry,
        suggested_object_id=object_id,
        **kw,
    )


def _entity_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)


def _sensor(sensors: dict, id_suffix: str) -> EG4SmartPortSensor:
    coordinator = _Coordinator(None, {GB: _gridboss(sensors)})
    return EG4SmartPortSensor(coordinator, GB, 1, SPEC[id_suffix])  # type: ignore[arg-type]


class TestKeys:
    def test_every_per_port_key_is_mapped(self):
        """All 7 keys x 2 modes x 4 ports map to their port."""
        assert len(GRIDBOSS_SMART_PORT_KEY_TO_PORT) == 56
        assert GRIDBOSS_SMART_PORT_KEY_TO_PORT["ac_couple4_total"] == 4
        assert set(GRIDBOSS_SMART_PORT_KEY_TO_PORT) <= GRIDBOSS_SMART_PORT_DYNAMIC_KEYS
        assert GRIDBOSS_SMART_PORT_AGGREGATE_KEYS == {
            "smart_load_power",
            "ac_couple_power",
        }

    def test_specs(self):
        """Power/current are mode-neutral; energy is one entity per mode."""
        assert {s.id_suffix for s in PORT_SENSOR_SPECS if s.mode is None} == {
            "power",
            "power_l1",
            "power_l2",
            "current_l1",
            "current_l2",
        }
        assert SPEC["smart_load_total"].mode == "smart_load"
        assert SPEC["ac_couple_today"].name == "AC Couple Energy Today"
        assert SPEC["ac_couple_today"].key_suffix == "today"


class TestResolvePortMode:
    def test_active_status(self):
        assert resolve_port_mode(_statuses("ac_couple"), 1) == "ac_couple"

    def test_filtered_unused_port(self):
        """A filtered cycle removes an unused port's keys: authoritatively unused."""
        assert resolve_port_mode(_statuses("unused"), 1) == PORT_UNUSED

    def test_unfiltered_invalid_status_falls_back_to_keys(self):
        """#195/#248: invalid status registers default the label to "unused"
        without filtering, so the port's keys are still there."""
        sensors = {**_statuses("unused", validated=False), "ac_couple1_power": 5.0}
        assert resolve_port_mode(sensors, 1) == "ac_couple"
        sensors["smart_load1_power"] = 1.0
        assert resolve_port_mode(sensors, 1) == "smart_load"

    def test_placeholder_is_unknown(self):
        assert resolve_port_mode({}, 1) is None


class TestPortSensor:
    def test_identity(self, monkeypatch):
        # Legacy parent-link form, so no hass is needed for the device lookup.
        monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", None)
        sensor = _sensor(_statuses("smart_load"), "power_l1")
        assert sensor.unique_id == f"{GB}_smart_port1_power_l1"
        assert sensor.name == "Power L1"
        assert sensor.device_info["identifiers"] == {(DOMAIN, f"{GB}_smart_port_1")}

    def test_neutral_sensor_reads_the_active_mode(self):
        sensors = {
            **_statuses("smart_load"),
            "smart_load1_power_l1": 120.0,
            "ac_couple1_power_l1": 999.0,
        }
        sensor = _sensor(sensors, "power_l1")
        assert sensor.native_value == 120.0
        assert sensor.available
        sensors["smart_port1_status"] = "ac_couple"
        assert sensor.native_value == 999.0

    def test_energy_sensor_serves_only_its_mode(self):
        """Energy never switches counters: that would corrupt HA statistics."""
        sensors = {
            **_statuses("smart_load"),
            "smart_load1_total": 1000.0,
            "ac_couple1_total": 950.0,
        }
        smart_load = _sensor(sensors, "smart_load_total")
        ac_couple = _sensor(sensors, "ac_couple_total")
        assert smart_load.native_value == 1000.0 and smart_load.available
        assert ac_couple.native_value is None and not ac_couple.available
        sensors["smart_port1_status"] = "ac_couple"
        assert smart_load.native_value is None and not smart_load.available
        assert ac_couple.native_value == 950.0

    def test_unused_port_is_unavailable(self):
        sensor = _sensor(_statuses("unused"), "power")
        assert sensor.native_value is None
        assert not sensor.available

    def test_unfiltered_invalid_status_still_reports(self):
        """#195/#248 regression guard: an unvalidated "unused" label with the
        port's keys present keeps reporting (the old per-mode sensors did)."""
        sensors = {
            **_statuses("unused", validated=False),
            "smart_load1_power": 42.0,
        }
        sensor = _sensor(sensors, "power")
        assert sensor.available
        assert sensor.native_value == 42.0

    def test_icon_follows_the_mode(self):
        sensors = _statuses("smart_load")
        sensor = _sensor(sensors, "power")
        smart_load_icon = sensor.icon
        sensors["smart_port1_status"] = "ac_couple"
        assert sensor.icon != smart_load_icon

    def test_currents_only_with_local_transport(self):
        cloud = _Coordinator(None, {GB: _gridboss({})})
        local = _Coordinator(None, {GB: _gridboss({})}, local=True)
        assert len(_create_smart_port_sensors(cloud, GB, {})) == 4 * 7  # type: ignore[arg-type]
        assert len(_create_smart_port_sensors(local, GB, {})) == 4 * 9  # type: ignore[arg-type]

    def test_per_mode_keys_excluded_from_gridboss(self):
        sensors = {"smart_load2_power": 10.0, "smart_load_power": 10.0, "grid_power": 5}
        entities = _create_simple_device_sensors(
            MagicMock(),
            GB,
            _gridboss(sensors),
            "gridboss",
            exclude=GRIDBOSS_SMART_PORT_KEY_TO_PORT.keys(),
        )
        assert {e.unique_id for e in entities} == {
            f"{GB}_smart_load_power",
            f"{GB}_grid_power",
        }


class TestDevicesAndIds:
    def test_port_device_hangs_off_gridboss(self, monkeypatch):
        # Legacy link form; the via_device_id form is covered by
        # tests/test_via_device_link*.py.
        monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", None)
        info = _Coordinator(None, {GB: _gridboss({})}).get_smart_port_device_info(GB, 2)
        assert info is not None
        assert info["identifiers"] == {(DOMAIN, f"{GB}_smart_port_2")}
        assert info["via_device"] == (DOMAIN, GB)
        assert info["name"] == f"Smart Port 2 {GB}"

    async def test_generated_ids_two_gridboss(self, hass: HomeAssistant):
        """Each GridBOSS's serial is in the ID; nothing collides or is suffixed."""
        entry = _entry(hass)
        coordinator = _Coordinator(hass, {GB: _gridboss({}), GB2: _gridboss({})})
        sensors = _platform(hass, entry, "sensor")
        selects = _platform(hass, entry, "select")
        for serial in (GB, GB2):
            await sensors.async_add_entities(
                [
                    EG4SmartPortSensor(coordinator, serial, 1, SPEC["power_l1"]),  # type: ignore[arg-type]
                    EG4SmartPortSensor(
                        coordinator, serial, 2, SPEC["smart_load_today"]
                    ),  # type: ignore[arg-type]
                ]
            )
            await selects.async_add_entities(
                [EG4SmartPortModeSelect(coordinator, serial, {}, 1)]  # type: ignore[arg-type]
            )
        ids = {
            e.entity_id
            for e in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
        }
        assert ids == {
            f"sensor.smart_port_1_{GB}_power_l1",
            f"sensor.smart_port_2_{GB}_smart_load_energy_today",
            f"select.smart_port_1_{GB}_mode",
            f"sensor.smart_port_1_{GB2.lower()}_power_l1",
            f"sensor.smart_port_2_{GB2.lower()}_smart_load_energy_today",
            f"select.smart_port_1_{GB2.lower()}_mode",
        }


class TestEnablement:
    @staticmethod
    def _sync(hass, entry, sensors, times=2):
        sync = PortSensorEnablement(hass, entry)
        for _ in range(times):
            sync.async_sync({"devices": {GB: _gridboss(sensors)}})
        return sync

    async def test_needs_two_validated_reads(self, hass: HomeAssistant):
        entry = _entry(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p1")
        self._sync(hass, entry, _statuses("unused"), times=1)
        assert er.async_get(hass).async_get(power.entity_id).disabled_by is None
        self._sync(hass, entry, _statuses("unused"), times=2)
        assert er.async_get(hass).async_get(power.entity_id).disabled_by is INTEGRATION

    async def test_unvalidated_reads_change_nothing(self, hass: HomeAssistant):
        entry = _entry(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p1")
        self._sync(hass, entry, _statuses("unused", validated=False), times=3)
        assert er.async_get(hass).async_get(power.entity_id).disabled_by is None

    async def test_round_trip_and_energy_per_mode(self, hass: HomeAssistant):
        entry = _entry(hass)
        registry = er.async_get(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p")
        sl_total = _seed(hass, entry, f"{GB}_smart_port1_smart_load_total", "sensor.s")
        ac_total = _seed(hass, entry, f"{GB}_smart_port1_ac_couple_total", "sensor.a")
        sync = PortSensorEnablement(hass, entry)

        def run(mode: str) -> None:
            for _ in range(2):
                sync.async_sync({"devices": {GB: _gridboss(_statuses(mode))}})

        run("smart_load")
        assert registry.async_get(power.entity_id).disabled_by is None
        assert registry.async_get(sl_total.entity_id).disabled_by is None
        assert registry.async_get(ac_total.entity_id).disabled_by is INTEGRATION
        run("unused")
        assert registry.async_get(power.entity_id).disabled_by is INTEGRATION
        assert registry.async_get(sl_total.entity_id).disabled_by is INTEGRATION
        run("ac_couple")
        assert registry.async_get(power.entity_id).disabled_by is None
        assert registry.async_get(ac_total.entity_id).disabled_by is None
        assert registry.async_get(sl_total.entity_id).disabled_by is INTEGRATION

    async def test_never_enables_what_it_did_not_disable(self, hass: HomeAssistant):
        """User-disabled and "disable new entities" (INTEGRATION, unmarked)."""
        entry = _entry(hass)
        user = _seed(
            hass,
            entry,
            f"{GB}_smart_port1_power",
            "sensor.u",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        pref = _seed(
            hass,
            entry,
            f"{GB}_smart_port1_power_l1",
            "sensor.n",
            disabled_by=INTEGRATION,
        )
        self._sync(hass, entry, _statuses("smart_load"))
        registry = er.async_get(hass)
        assert registry.async_get(user.entity_id).disabled_by is (
            er.RegistryEntryDisabler.USER
        )
        assert registry.async_get(pref.entity_id).disabled_by is INTEGRATION

    async def test_user_reenable_while_unused_is_kept(self, hass: HomeAssistant):
        entry = _entry(hass)
        registry = er.async_get(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p")
        sync = self._sync(hass, entry, _statuses("unused"))
        assert registry.async_get(power.entity_id).disabled_by is INTEGRATION
        registry.async_update_entity(power.entity_id, disabled_by=None)  # the user
        for _ in range(3):
            sync.async_sync({"devices": {GB: _gridboss(_statuses("unused"))}})
        assert registry.async_get(power.entity_id).disabled_by is None

    async def test_setup_listener_follows_mode_changes(self, hass: HomeAssistant):
        """End to end through sensor.async_setup_entry and a real platform."""
        entry = _entry(hass)
        coordinator = _Coordinator(hass, {GB: _gridboss(_statuses(*["unused"] * 4))})
        entry.runtime_data = coordinator  # type: ignore[attr-defined]
        platform = _platform(hass, entry, "sensor")

        def add_entities(entities: Any, update_before_add: bool = False) -> None:
            hass.async_create_task(platform.async_add_entities(list(entities)))

        await sensor_platform.async_setup_entry(hass, entry, add_entities)
        await hass.async_block_till_done()
        coordinator.fire()  # setup ran the first read; this is the second
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        port4_power = _entity_id(hass, f"{GB}_smart_port4_power")
        assert port4_power == f"sensor.smart_port_4_{GB}_power"
        assert registry.async_get(port4_power).disabled_by is INTEGRATION

        coordinator.data = {
            "devices": {
                GB: _gridboss(
                    {
                        **_statuses("unused", "unused", "unused", "ac_couple"),
                        "ac_couple4_power": 50.0,
                    }
                )
            }
        }
        coordinator.fire(times=2)
        await hass.async_block_till_done()
        assert registry.async_get(port4_power).disabled_by is None
        ac_energy = _entity_id(hass, f"{GB}_smart_port4_ac_couple_total")
        sl_energy = _entity_id(hass, f"{GB}_smart_port4_smart_load_total")
        assert registry.async_get(ac_energy).disabled_by is None
        assert registry.async_get(sl_energy).disabled_by is INTEGRATION


class TestMigration:
    async def test_energy_is_adopted_per_mode(self, hass: HomeAssistant):
        entry = _entry(hass)
        sl = _seed(hass, entry, f"{GB}_smart_load1_total", "sensor.sl_total")
        ac = _seed(hass, entry, f"{GB}_ac_couple1_total", "sensor.ac_total")
        async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss(_statuses("ac_couple"))}}
        )
        registry = er.async_get(hass)
        assert registry.async_get(sl.entity_id).unique_id == (
            f"{GB}_smart_port1_smart_load_total"
        )
        assert registry.async_get(ac.entity_id).unique_id == (
            f"{GB}_smart_port1_ac_couple_total"
        )

    async def test_validated_mode_wins_and_nothing_is_deleted(
        self, hass: HomeAssistant
    ):
        entry = _entry(hass)
        live = _seed(hass, entry, f"{GB}_ac_couple1_power_l2", "sensor.live")
        old = _seed(hass, entry, f"{GB}_smart_load1_power_l2", "sensor.old")
        inverter = _seed(hass, entry, "1111111111_smart_load_power", "sensor.inv")
        async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss(_statuses("ac_couple"))}}
        )
        registry = er.async_get(hass)
        assert registry.async_get(live.entity_id).unique_id == (
            f"{GB}_smart_port1_power_l2"
        )
        kept = registry.async_get(old.entity_id)
        assert kept is not None, "superseded entry must not be deleted"
        assert kept.unique_id == old.unique_id
        assert kept.disabled_by is INTEGRATION
        assert registry.async_get(inverter.entity_id).unique_id == inverter.unique_id

    async def test_contested_waits_for_a_validated_read(
        self, hass: HomeAssistant, freezer
    ):
        """LOCAL first load (placeholder data) cannot tell which mode's entry
        is the port's; created_at is no guide (HA restores it on re-created
        entries, and migrated registries hold epoch 0).  Defer, then adopt."""
        entry = _entry(hass)
        smart_load = _seed(hass, entry, f"{GB}_smart_load1_power_l1", "sensor.sl")
        freezer.tick(timedelta(minutes=5))
        ac_couple = _seed(hass, entry, f"{GB}_ac_couple1_power_l1", "sensor.ac")
        energy = _seed(hass, entry, f"{GB}_smart_load1_total", "sensor.sl_total")

        deferred = async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss({})}}
        )
        registry = er.async_get(hass)
        assert deferred == {(GB, 1, "power_l1")}
        assert registry.async_get(smart_load.entity_id).unique_id == (
            smart_load.unique_id
        )
        assert registry.async_get(ac_couple.entity_id).unique_id == ac_couple.unique_id
        # Energy is never contested: adopted right away.
        assert registry.async_get(energy.entity_id).unique_id == (
            f"{GB}_smart_port1_smart_load_total"
        )

        # A validated read says Smart Load: the OLDER entry is the port's.
        deferred = async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss(_statuses("smart_load"))}}
        )
        assert deferred == set()
        assert registry.async_get(smart_load.entity_id).unique_id == (
            f"{GB}_smart_port1_power_l1"
        )
        assert registry.async_get(ac_couple.entity_id).disabled_by is INTEGRATION

    async def test_contested_waits_while_port_unused(self, hass: HomeAssistant):
        entry = _entry(hass)
        _seed(hass, entry, f"{GB}_smart_load1_power", "sensor.sl")
        _seed(hass, entry, f"{GB}_ac_couple1_power", "sensor.ac")
        deferred = async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss(_statuses("unused"))}}
        )
        assert deferred == {(GB, 1, "power")}

    async def test_superseded_entry_is_marked_once_and_left_alone(
        self, hass: HomeAssistant
    ):
        entry = _entry(hass)
        _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.port_power")
        straggler = _seed(hass, entry, f"{GB}_smart_load1_power", "sensor.old")
        data = {"devices": {GB: _gridboss(_statuses("smart_load"))}}
        async_migrate_to_port_sensors(hass, entry, data)
        registry = er.async_get(hass)
        assert registry.async_get(straggler.entity_id).disabled_by is INTEGRATION
        registry.async_update_entity(straggler.entity_id, disabled_by=None)  # the user
        async_migrate_to_port_sensors(hass, entry, data)  # next setup
        assert registry.async_get(straggler.entity_id).disabled_by is None

    async def test_currents_not_adopted_without_local_transport(
        self, hass: HomeAssistant
    ):
        entry = _entry(hass)
        current = _seed(hass, entry, f"{GB}_smart_load1_current_l1", "sensor.cur")
        async_migrate_to_port_sensors(
            hass,
            entry,
            {"devices": {GB: _gridboss(_statuses("smart_load"))}},
            lambda serial: False,
        )
        assert er.async_get(hass).async_get(current.entity_id).unique_id == (
            current.unique_id
        )

    async def test_existing_target_keeps_stragglers(self, hass: HomeAssistant):
        entry = _entry(hass)
        _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.port_power")
        straggler = _seed(hass, entry, f"{GB}_smart_load1_power", "sensor.old")
        async_migrate_to_port_sensors(
            hass, entry, {"devices": {GB: _gridboss(_statuses("smart_load"))}}
        )
        kept = er.async_get(hass).async_get(straggler.entity_id)
        assert kept is not None and kept.disabled_by is INTEGRATION

    async def test_gridboss_absent_is_left_for_later(self, hass: HomeAssistant):
        entry = _entry(hass)
        pending = _seed(hass, entry, f"{GB}_smart_load1_power", "sensor.pending")
        async_migrate_to_port_sensors(hass, entry, {"devices": {}})
        assert er.async_get(hass).async_get(pending.entity_id).unique_id == (
            pending.unique_id
        )

    async def test_adoption_then_stale_cleanup_keeps_port_entries(
        self, hass: HomeAssistant
    ):
        """Setup order: adoption first, then the #217 cleanup, which now only
        prunes the cross-port totals.  A per-port key missing from the first
        validated read (e.g. a Modbus-only current before the dongle attached)
        no longer costs the entry."""
        entry = _entry(hass)
        current = _seed(hass, entry, f"{GB}_smart_load1_current_l1", "sensor.cur")
        stale_total = _seed(hass, entry, f"{GB}_ac_couple_power", "sensor.ac_total")
        data = {"devices": {GB: _gridboss(_statuses("smart_load"))}}
        coordinator = MagicMock(data=data)
        async_migrate_to_port_sensors(hass, entry, data)
        _async_cleanup_stale_smart_port_entities(hass, entry, coordinator)
        registry = er.async_get(hass)
        assert registry.async_get(current.entity_id).unique_id == (
            f"{GB}_smart_port1_current_l1"
        )
        assert registry.async_get(stale_total.entity_id) is None


class TestReadCounting:
    """The sync counts GridBOSS reads, not coordinator updates."""

    async def test_same_read_twice_is_one_read(self, hass: HomeAssistant):
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            SMART_PORT_READ_KEY,
        )

        entry = _entry(hass)
        registry = er.async_get(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p")
        sync = PortSensorEnablement(hass, entry)
        read = {**_statuses("unused"), SMART_PORT_READ_KEY: 100.0}
        sync.async_sync({"devices": {GB: _gridboss(read)}})
        sync.async_sync({"devices": {GB: _gridboss(dict(read))}})  # carried forward
        assert registry.async_get(power.entity_id).disabled_by is None
        read[SMART_PORT_READ_KEY] = 190.0  # a new read
        sync.async_sync({"devices": {GB: _gridboss(read)}})
        assert registry.async_get(power.entity_id).disabled_by is INTEGRATION


class TestUntrustedStatus:
    """#195/#248 skip path: invalid status registers, keys left unfiltered."""

    def test_both_energy_counters_report(self):
        sensors = {
            **_statuses("unused", validated=False),
            "smart_load1_power": 5.0,
            "smart_load1_total": 10.0,
            "ac_couple1_total": 20.0,
        }
        assert _sensor(sensors, "smart_load_total").native_value == 10.0
        ac_couple = _sensor(sensors, "ac_couple_total")
        assert ac_couple.available
        assert ac_couple.native_value == 20.0
        assert not _sensor(sensors, "ac_couple_today").available


class TestPromptConfirmation:
    """A mode written through the Mode select is confirmed quickly."""

    def test_expectation_cleared_by_confirming_data_or_ttl(self, monkeypatch):
        from custom_components.eg4_web_monitor import smart_port_devices as spd

        coordinator = _Coordinator(None, {GB: _gridboss(_statuses("unused"))})
        clock = [1000.0]
        monkeypatch.setattr(spd.time, "monotonic", lambda: clock[0])
        spd.note_port_mode_written(coordinator, GB, 1, "smart_load")
        assert spd.serials_awaiting_port_mode(coordinator) == {GB}
        assert spd.expected_port_mode(coordinator, GB, 1) == "smart_load"

        coordinator.data = {"devices": {GB: _gridboss(_statuses("smart_load"))}}
        assert spd.serials_awaiting_port_mode(coordinator) == set()

        spd.note_port_mode_written(coordinator, GB, 2, "ac_couple")
        clock[0] += spd.EXPECTED_MODE_TTL + 1
        assert spd.expected_port_mode(coordinator, GB, 2) is None
        assert spd.serials_awaiting_port_mode(coordinator) == set()

    @pytest.mark.asyncio
    async def test_hybrid_reads_gridboss_while_awaiting(self):
        from unittest.mock import AsyncMock

        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )
        from custom_components.eg4_web_monitor.smart_port_devices import (
            note_port_mode_written,
        )

        mock_self = MagicMock()
        mock_self._should_poll_hybrid_local = MagicMock(return_value=False)
        mock_self._failed_attach_serials = set()
        mock_self.station = MagicMock(all_mid_devices=[], all_inverters=[])
        mock_self.data = {"devices": {GB: _gridboss(_statuses("unused"))}}
        mock_self._async_update_http_data = AsyncMock(return_value={"devices": {}})

        note_port_mode_written(mock_self, GB, 1, "smart_load")
        await EG4DataUpdateCoordinator._async_update_hybrid_data(mock_self)
        mock_self._async_update_http_data.assert_awaited_once_with(
            include_mid_refresh=True
        )

    async def test_sync_acts_on_first_confirming_read(self, hass: HomeAssistant):
        from custom_components.eg4_web_monitor.smart_port_devices import (
            note_port_mode_written,
        )

        entry = _entry(hass)
        registry = er.async_get(hass)
        power = _seed(hass, entry, f"{GB}_smart_port1_power", "sensor.p")
        coordinator = _Coordinator(hass, {})
        data = {"devices": {GB: _gridboss(_statuses("unused"))}}

        # Without a write, one read is not enough.
        PortSensorEnablement(hass, entry, coordinator).async_sync(data)
        assert registry.async_get(power.entity_id).disabled_by is None

        # A read confirming the mode just written acts at once.
        note_port_mode_written(coordinator, GB, 1, "unused")
        PortSensorEnablement(hass, entry, coordinator).async_sync(data)
        assert registry.async_get(power.entity_id).disabled_by is INTEGRATION

        # A read contradicting the written mode still needs two reads.
        note_port_mode_written(coordinator, GB, 1, "ac_couple")
        other = PortSensorEnablement(hass, entry, coordinator)
        other.async_sync({"devices": {GB: _gridboss(_statuses("smart_load"))}})
        assert registry.async_get(power.entity_id).disabled_by is INTEGRATION

    @pytest.mark.asyncio
    async def test_select_records_the_written_mode(self, monkeypatch):
        from unittest.mock import AsyncMock, patch

        # Legacy parent-link form, so no hass is needed for the device lookup.
        monkeypatch.setattr(coordinator_mixins, "_get_device_id_by_identifier", None)

        from custom_components.eg4_web_monitor.smart_port_devices import (
            expected_port_mode,
        )

        coordinator = _Coordinator(None, {GB: _gridboss(_statuses("unused"))})
        coordinator.async_request_refresh = AsyncMock()  # type: ignore[attr-defined]
        select = EG4SmartPortModeSelect(coordinator, GB, {}, 3)  # type: ignore[arg-type]
        select.hass = MagicMock()
        select.async_write_ha_state = MagicMock()
        with patch(
            "custom_components.eg4_web_monitor.select.async_write_with_cloud_fallback",
            AsyncMock(),
        ):
            await select.async_select_option("AC Couple")
        assert expected_port_mode(coordinator, GB, 3) == "ac_couple"


class TestDeferredAdoptionEndToEnd:
    async def test_contested_sensor_is_created_after_validated_read(
        self, hass: HomeAssistant
    ):
        """Setup order as in __init__: migrate -> record deferred -> platform.
        The contested sensor appears only after a validated read, under the
        port mode's own entry (entity ID and history kept)."""
        from custom_components.eg4_web_monitor.smart_port_devices import (
            set_deferred_port_sensors,
        )

        entry = _entry(hass)
        registry = er.async_get(hass)
        live = _seed(
            hass, entry, f"{GB}_smart_load1_power", "sensor.smart_load_1_power"
        )
        other = _seed(hass, entry, f"{GB}_ac_couple1_power", "sensor.ac_couple_1_power")
        coordinator = _Coordinator(hass, {GB: _gridboss({})})  # LOCAL placeholder
        entry.runtime_data = coordinator  # type: ignore[attr-defined]
        set_deferred_port_sensors(
            coordinator, async_migrate_to_port_sensors(hass, entry, coordinator.data)
        )
        platform = _platform(hass, entry, "sensor")

        def add_entities(entities: Any, update_before_add: bool = False) -> None:
            hass.async_create_task(platform.async_add_entities(list(entities)))

        await sensor_platform.async_setup_entry(hass, entry, add_entities)
        await hass.async_block_till_done()
        assert _entity_id(hass, f"{GB}_smart_port1_power") is None
        assert _entity_id(hass, f"{GB}_smart_port1_power_l1") is not None

        coordinator.data = {
            "devices": {
                GB: _gridboss({**_statuses("smart_load"), "smart_load1_power": 7.0})
            }
        }
        coordinator.fire()
        await hass.async_block_till_done()
        assert _entity_id(hass, f"{GB}_smart_port1_power") == live.entity_id
        assert hass.states.get(live.entity_id).state == "7.0"
        assert registry.async_get(other.entity_id).disabled_by is INTEGRATION
