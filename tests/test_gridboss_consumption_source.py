"""Keep GridBOSS consumption on its CT source through incomplete reads (#661)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_LOCAL_TRANSPORTS,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor


def _entry_device(registry, entry_id, identifier):
    """Find our record using an API shared by both registry ownership models."""
    return next(
        device
        for device in dr.async_entries_for_config_entry(registry, entry_id)
        if (DOMAIN, identifier) in device.identifiers
    )


@pytest.mark.parametrize("mode", ["http", "hybrid", "local"])
@pytest.mark.parametrize(
    "missing",
    ["ups_today", "load_today", "ups_total", "load_total", "all", "error", "absent"],
)
async def test_ct_gap_and_recovery_preserve_consumption_source(hass, mode, missing):
    """Real coordinator processing cannot publish a partial CT or inverter total."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: mode,
            CONF_LOCAL_TRANSPORTS: [],
            "username": "test",
            "password": "test",
            "base_url": "https://test.example.com",
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    inverter = {
        "type": "inverter",
        "serial": "INV001",
        "parallel_number": 1,
        "parallel_master_slave": 1,
        "sensors": {"consumption": 19.0, "consumption_lifetime": 1900.0},
    }
    ct = {
        "ups_today": 8.0,
        "load_today": 12.0,
        "ups_total": 800.0,
        "load_total": 1200.0,
    }
    group = MagicMock()
    group.name = "A"
    group.today_yielding = 0.0
    group.inverters = []
    group.mid_device.serial_number = "GB001"
    group._has_local_energy.return_value = True
    station = MagicMock()
    station.all_inverters = []
    station.all_mid_devices = []
    station.standalone_mid_devices = []
    station.parallel_groups = [group]
    coordinator.station = station

    async def process(sensors, *, error=False, absent=False):
        mid = {"type": "gridboss", "serial": "GB001", "sensors": sensors}
        if mode == "local":
            if error:
                mid["error"] = "Local transport link down"
            result = {"devices": {"INV001": inverter, "GB001": mid}}
            if absent:
                del result["devices"]["GB001"]
            await coordinator._process_local_parallel_groups(result)
        else:
            group.mid_device = None if absent else MagicMock(serial_number="GB001")
            with (
                patch.object(
                    coordinator,
                    "_process_parallel_group_object",
                    new=AsyncMock(
                        side_effect=lambda _: {
                            "type": "parallel_group",
                            "sensors": dict(inverter["sensors"]),
                        }
                    ),
                ),
                patch.object(
                    coordinator,
                    "_process_mid_device_object",
                    new=AsyncMock(
                        side_effect=RuntimeError("MID processing failed")
                        if error
                        else None,
                        return_value=mid,
                    ),
                ),
                patch.object(coordinator, "_rebuild_inverter_cache"),
            ):
                result = await coordinator._process_station_data()
        coordinator.async_set_updated_data(result)
        return result["devices"]["parallel_group_a"]["sensors"]

    daily = EG4InverterSensor(
        coordinator, "parallel_group_a", "consumption", "parallel_group"
    )
    lifetime = EG4InverterSensor(
        coordinator, "parallel_group_a", "consumption_lifetime", "parallel_group"
    )
    await process(ct)
    assert daily.native_value == 20.0
    assert lifetime.native_value == 2000.0

    incomplete = dict(ct)
    if missing in {"all", "error", "absent"}:
        incomplete.clear()
    else:
        incomplete.pop(missing)
    values = await process(
        incomplete, error=missing == "error", absent=missing == "absent"
    )
    for key, period, entity in [
        ("consumption", "today", daily),
        ("consumption_lifetime", "total", lifetime),
    ]:
        if missing in {"all", "error", "absent"} or missing.endswith(period):
            assert values[key] is None
            assert entity.native_value is None
        else:
            assert entity.native_value == (20.0 if period == "today" else 2000.0)
    if mode == "local" and missing == "error":
        assert not daily.available

    recovered = {key: value + 1 for key, value in ct.items()}
    await process(recovered)
    assert daily.available
    assert daily.native_value == 22.0
    assert lifetime.native_value == 2002.0


@pytest.mark.parametrize("mode", ["http", "hybrid", "local"])
@pytest.mark.parametrize(
    "history",
    [
        "ct",
        "ct_first_gap",
        "ct_first_error",
        "legacy",
        "legacy_mixed",
        "legacy_partial",
        "inverter",
        "mixed_inverter",
        "removed",
    ],
)
async def test_restart_preserves_group_source(hass, mode, history):
    """A new coordinator keeps registry source evidence before MID rediscovery."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.eg4_web_monitor import (
        _async_cleanup_removed_registry_devices,
        async_remove_config_entry_device,
    )
    from custom_components.eg4_web_monitor.device_removal import DEVICE_ABSENCE_WINDOW
    from custom_components.eg4_web_monitor.gridboss_topology import (
        GRIDBOSS_GROUP_MODEL_ID,
        INVERTER_GROUP_MODEL_ID,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: mode,
            CONF_LOCAL_TRANSPORTS: [],
            "username": "test",
            "password": "test",
        },
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    group_id = "parallel_group_a"
    ct = {
        "ups_today": 8.0,
        "load_today": 12.0,
        "ups_total": 800.0,
        "load_total": 1200.0,
    }

    def new_coordinator():
        with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
            result = EG4DataUpdateCoordinator(hass, entry)
        entry.runtime_data = result
        return result

    async def process(
        coordinator,
        *,
        mid_present,
        readings=None,
        associate_elsewhere=False,
        error=False,
    ):
        inverter = {
            "type": "inverter",
            "serial": "INV001",
            "parallel_number": 1,
            "parallel_master_slave": 1,
            "sensors": {"consumption": 19.0, "consumption_lifetime": 1900.0},
        }
        mid = {
            "type": "gridboss",
            "serial": "GB001",
            "sensors": ct if readings is None else readings,
        }
        if error:
            mid["error"] = "MID data read failed"
            mid["sensors"] = {}
        if mode == "local":
            result = {"devices": {"INV001": inverter}}
            if mid_present:
                result["devices"]["GB001"] = mid
            await coordinator._process_local_parallel_groups(result)
        else:
            group = MagicMock()
            group.name = "A"
            group.inverters = []
            group.mid_device = MagicMock(serial_number="GB001") if mid_present else None
            station = MagicMock()
            station.all_inverters = []
            station.all_mid_devices = []
            station.standalone_mid_devices = []
            station.parallel_groups = [group]
            if associate_elsewhere:
                other_group = MagicMock()
                other_group.name = "B"
                other_group.inverters = []
                other_group.mid_device = MagicMock(serial_number="GB001")
                station.parallel_groups.append(other_group)
            coordinator.station = station
            with (
                patch.object(
                    coordinator,
                    "_process_parallel_group_object",
                    new=AsyncMock(
                        side_effect=lambda _: {
                            "type": "parallel_group",
                            "sensors": dict(inverter["sensors"]),
                        }
                    ),
                ),
                patch.object(
                    coordinator,
                    "_process_mid_device_object",
                    new=AsyncMock(
                        return_value=mid,
                        side_effect=RuntimeError("MID data read failed")
                        if error
                        else None,
                    ),
                ),
                patch.object(coordinator, "_rebuild_inverter_cache"),
            ):
                result = await coordinator._process_station_data()
        coordinator.async_set_updated_data(result)
        return result["devices"][group_id]

    first = new_coordinator()
    if history in {"legacy", "legacy_mixed", "legacy_partial"}:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, group_id)},
            model="Parallel Group",
        )
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "GB001")},
            model="GridBOSS",
        )
    else:
        initial_ct = history not in {"inverter", "mixed_inverter"}
        await process(
            first,
            mid_present=initial_ct,
            readings={} if history == "ct_first_gap" else None,
            error=history == "ct_first_error",
        )
        expected_marker = (
            GRIDBOSS_GROUP_MODEL_ID if initial_ct else INVERTER_GROUP_MODEL_ID
        )
        # Processing persists the choice even before consumption entities exist.
        assert (
            _entry_device(registry, entry.entry_id, group_id).model_id
            == expected_marker
        )
        assert first.get_device_info(group_id)["model_id"] == expected_marker
        if initial_ct and history != "ct_first_error":
            registry.async_get_or_create(
                config_entry_id=entry.entry_id, **first.get_device_info("GB001")
            )
        elif history == "ct_first_error":
            # No GridBOSS entity was registered: the positive association alone
            # must survive the failure and the following restart.
            assert (
                _entry_device(registry, entry.entry_id, "GB001").model_id
                == "eg4_web_monitor:gridboss"
            )
        elif history == "mixed_inverter":
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, "GB001")},
                model="GridBOSS",
            )

    if history == "legacy_partial":
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "GB002")},
            model="GridBOSS",
        )

    if history == "removed":
        device = _entry_device(registry, entry.entry_id, "GB001")
        first._removal_identifier_last_seen["GB001"] = (0.0, "device", None)
        first._removal_device_observed_since = 0.0
        first.data = {"devices": {}}
        first.station = None
        # Exercise the observation window independently of the runner's uptime.
        with patch(
            "custom_components.eg4_web_monitor.device_removal.monotonic",
            return_value=DEVICE_ABSENCE_WINDOW - 1,
        ):
            assert not await async_remove_config_entry_device(hass, entry, device)
        with patch(
            "custom_components.eg4_web_monitor.device_removal.monotonic",
            return_value=DEVICE_ABSENCE_WINDOW + 1,
        ):
            assert await async_remove_config_entry_device(hass, entry, device)
        registry.async_remove_device(device.id)
    await first.async_shutdown()

    restarted = new_coordinator()
    data = await process(restarted, mid_present=False)
    # Cloud setup cleanup must not erase evidence after partial discovery.
    if mode != "local":
        _async_cleanup_removed_registry_devices(hass, entry, restarted)
    expected_ct = history in {
        "ct",
        "ct_first_gap",
        "ct_first_error",
        "legacy",
        "legacy_mixed",
        "legacy_partial",
    }
    assert data["sensors"]["consumption"] == (None if expected_ct else 19.0)
    assert data["sensors"]["consumption_lifetime"] == (None if expected_ct else 1900.0)
    daily = EG4InverterSensor(restarted, group_id, "consumption", "parallel_group")
    lifetime = EG4InverterSensor(
        restarted, group_id, "consumption_lifetime", "parallel_group"
    )
    assert daily.native_value == (None if expected_ct else 19.0)
    assert lifetime.native_value == (None if expected_ct else 1900.0)

    if history in {"legacy_mixed", "legacy_partial"} and mode != "local":
        data = await process(restarted, mid_present=False, associate_elsewhere=True)
        # An unrelated GB association is positive evidence; one still-unresolved
        # known GB prevents classifying the group from an incomplete snapshot.
        expected_ct = history == "legacy_partial"
        assert data["sensors"]["consumption"] == (None if expected_ct else 19.0)
        if not expected_ct:
            assert (
                _entry_device(registry, entry.entry_id, group_id).model_id
                == INVERTER_GROUP_MODEL_ID
            )

    # Repeating the absent discovery after another reload remains safe.
    await restarted.async_shutdown()
    restarted = new_coordinator()
    data = await process(restarted, mid_present=False)
    assert data["sensors"]["consumption"] == (None if expected_ct else 19.0)
    if expected_ct:
        data = await process(restarted, mid_present=True)
        assert data["sensors"]["consumption"] == 20.0
        assert data["sensors"]["consumption_lifetime"] == 2000.0
        assert (
            _entry_device(registry, entry.entry_id, group_id).model_id
            == GRIDBOSS_GROUP_MODEL_ID
        )
    await restarted.async_shutdown()


@pytest.mark.parametrize("has_mid", [False, True])
@pytest.mark.parametrize("shared", [False, True])
async def test_group_source_never_borrows_or_overwrites_foreign_role(
    hass, has_mid, shared
):
    """A colliding group identifier cannot mutate another entry's source marker."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.eg4_web_monitor.gridboss_topology import (
        GRIDBOSS_GROUP_MODEL_ID,
        group_consumption_source,
    )

    owner = MockConfigEntry(domain=DOMAIN, data={CONF_CONNECTION_TYPE: "local"})
    owner.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_CONNECTION_TYPE: "local"})
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    foreign_device = registry.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(DOMAIN, "parallel_group_a")},
        model_id=GRIDBOSS_GROUP_MODEL_ID,
    )
    if shared:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers=foreign_device.identifiers
        )
    ownership = registry.async_get(foreign_device.id).config_entries
    with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    source = group_consumption_source(
        coordinator, "parallel_group_a", has_mid=has_mid, previous_source=None
    )
    assert source == ("gridboss" if has_mid else "inverter")
    current = registry.async_get(foreign_device.id)
    assert current.config_entries == ownership
    assert current.model_id == GRIDBOSS_GROUP_MODEL_ID
    coordinator.data = {
        "devices": {
            "parallel_group_a": {"type": "parallel_group", "consumption_source": source}
        }
    }
    info = coordinator.get_device_info("parallel_group_a")
    if hasattr(registry, "async_get_device_by_identifier"):
        own_device = _entry_device(registry, entry.entry_id, "parallel_group_a")
        assert own_device.id != foreign_device.id
        assert own_device.config_entries == {entry.entry_id}
        expected_marker = f"eg4_web_monitor:{source}_group"
        assert own_device.model_id == expected_marker
        assert info["model_id"] == expected_marker
    else:
        assert "model_id" not in info
    await coordinator.async_shutdown()


async def test_cached_group_role_is_not_republished_after_ownership_changes(hass):
    """Previously cached metadata must respect a later shared registry record."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.eg4_web_monitor.gridboss_topology import (
        INVERTER_GROUP_MODEL_ID,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_CONNECTION_TYPE: "local"})
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, data={CONF_CONNECTION_TYPE: "local"})
    other.add_to_hass(hass)
    registry = dr.async_get(hass)
    own_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "parallel_group_a")}
    )
    with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "devices": {
            "parallel_group_a": {
                "type": "parallel_group",
                "consumption_source": "inverter",
            }
        }
    }
    assert (
        coordinator.get_device_info("parallel_group_a")["model_id"]
        == INVERTER_GROUP_MODEL_ID
    )
    other_device = registry.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={(DOMAIN, "parallel_group_a")}
    )
    info = coordinator.get_device_info("parallel_group_a")
    if other_device.id == own_device.id:
        assert "model_id" not in info
    else:
        assert info["model_id"] == INVERTER_GROUP_MODEL_ID
        assert registry.async_get(other_device.id).model_id is None
        assert registry.async_get(own_device.id).config_entries == {entry.entry_id}
    await coordinator.async_shutdown()
