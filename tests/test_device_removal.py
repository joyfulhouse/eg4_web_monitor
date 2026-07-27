"""Tests for per-device removal (async_remove_config_entry_device, #174).

The removal gate judges absence over the observation ledger, and only over
COMPLETE observed time -- see device_removal.py's module docstring for the
design and the PR #489 fix round that added the completeness signal. The
clock fixture drives the module's ``monotonic`` so tests can age identifiers
past their class windows deterministically.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import async_remove_config_entry_device
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.device_removal import (
    BATTERY_ABSENCE_WINDOW,
    DEVICE_ABSENCE_WINDOW,
    _LEDGER_PRUNE_AGE,
    assess_discovery_completeness,
    provided_identifiers,
    record_provided_identifiers,
)

LIVE_INVERTER = "1234567890"
LIVE_GRIDBOSS = "9876543210"
GONE_SERIAL = "1111111111"
T0 = 1_000_000.0


@pytest.fixture
def clock():
    """Patch device_removal's monotonic() to a controllable clock."""
    state = {"now": T0}
    with patch(
        "custom_components.eg4_web_monitor.device_removal.monotonic",
        side_effect=lambda: state["now"],
    ):
        yield state


def _healthy_data() -> dict:
    """A representative healthy device table."""
    return {
        "devices": {
            LIVE_INVERTER: {
                "type": "inverter",
                "sensors": {"battery_bank_count": 2, "battery_bank_voltage": 53.2},
                # Both battery key shapes the coordinator registers: the
                # serial-based key and a positional/no-serial key.
                "batteries": {f"{LIVE_INVERTER}-01": {}, "BAT002": {}},
            },
            LIVE_GRIDBOSS: {"type": "gridboss", "sensors": {}},
            "parallel_group_a": {"type": "parallel_group", "sensors": {}},
        },
        "station": {"name": "Test Station"},
    }


def _coordinator(data: dict | None = None) -> MagicMock:
    """Coordinator mock carrying the removal ledger attributes."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator._consecutive_update_failures = 0
    coordinator.plant_id = "12345"
    coordinator.connection_type = CONNECTION_TYPE_HTTP
    coordinator.data = _healthy_data() if data is None else data
    coordinator._removal_identifier_last_seen = {}
    coordinator._removal_device_observed_since = None
    coordinator._removal_battery_observed_since = None
    coordinator._removal_device_list_ok = False
    coordinator._removal_battery_ok = False
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    # Default: no inverter object per serial -> the battery-fetch confirmation
    # falls through to the error-row / link-down signals. Tests that exercise
    # the _battery_cache_time confirmation override this.
    coordinator.get_inverter_object = MagicMock(return_value=None)
    return coordinator


def _entry(coordinator: MagicMock) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="remove_test_entry")
    entry.runtime_data = coordinator
    return entry


def _device_entry(*identifiers: str) -> MagicMock:
    """Device-registry entry mock carrying DOMAIN identifiers."""
    device = MagicMock()
    device.identifiers = {(DOMAIN, identifier) for identifier in identifiers}
    return device


def _seed_history(
    coordinator: MagicMock,
    data: dict,
    device_list_ok: bool = True,
    battery_ok: bool = True,
) -> None:
    """Record one historical cycle at the current (patched) clock time."""
    record_provided_identifiers(coordinator, data, device_list_ok, battery_ok)


HASS = MagicMock(spec=HomeAssistant)


# ── provided_identifiers / record bookkeeping ────────────────────────


def test_provided_identifiers_shapes_and_classes():
    """Every registered identifier shape appears verbatim with its class."""
    provided = provided_identifiers(_healthy_data(), "12345")
    assert provided == {
        LIVE_INVERTER: "device",
        LIVE_GRIDBOSS: "device",
        "parallel_group_a": "device",
        f"{LIVE_INVERTER}_battery_bank": "battery",
        f"{LIVE_INVERTER}-01": "battery",
        "BAT002": "battery",
        "station_12345": "device",
    }


def test_bank_identifier_requires_registration_gate():
    """The bank identifier mirrors the #169 device-info gate exactly."""
    data = _healthy_data()
    # battery_bank_count == 0 (shared-battery secondary): no bank.
    data["devices"][LIVE_INVERTER]["sensors"]["battery_bank_count"] = 0
    assert f"{LIVE_INVERTER}_battery_bank" not in provided_identifiers(data, "12345")
    # No bank sensors at all (degraded/placeholder cycle): no bank either.
    data["devices"][LIVE_INVERTER]["sensors"] = {}
    assert f"{LIVE_INVERTER}_battery_bank" not in provided_identifiers(data, "12345")


def test_station_identifier_needs_station_data_and_plant_id():
    data = _healthy_data()
    del data["station"]
    assert "station_12345" not in provided_identifiers(data, "12345")
    assert "station_None" not in provided_identifiers(_healthy_data(), None)


def test_record_stamps_ledger_and_both_clocks(clock):
    coordinator = _coordinator()
    record_provided_identifiers(coordinator, coordinator.data, True, True)
    assert coordinator._removal_device_observed_since == T0
    assert coordinator._removal_battery_observed_since == T0
    assert coordinator._removal_identifier_last_seen[LIVE_INVERTER] == (T0, "device")
    assert coordinator._removal_identifier_last_seen["BAT002"] == (T0, "battery")

    clock["now"] = T0 + 300
    record_provided_identifiers(coordinator, coordinator.data, True, True)
    # Contiguous complete successes keep both observation clocks; last-seen
    # advances.
    assert coordinator._removal_device_observed_since == T0
    assert coordinator._removal_battery_observed_since == T0
    assert coordinator._removal_identifier_last_seen["BAT002"] == (T0 + 300, "battery")


def test_clocks_restart_after_failed_cycle(clock):
    """Blind time never counts: recovery from a failed cycle restarts both
    observation clocks at the recovery cycle (record sees the PREVIOUS
    cycle's verdict in last_update_success while the update method runs)."""
    coordinator = _coordinator()
    record_provided_identifiers(coordinator, coordinator.data, True, True)

    clock["now"] = T0 + 7 * 3600
    coordinator.last_update_success = False
    record_provided_identifiers(coordinator, coordinator.data, True, True)
    assert coordinator._removal_device_observed_since == T0 + 7 * 3600
    assert coordinator._removal_battery_observed_since == T0 + 7 * 3600


def test_incomplete_cycle_clears_its_class_clock(clock):
    """An incomplete cycle is no observation: device-list failure clears the
    device clock (and battery, since battery_ok implies device_list_ok); a
    battery-only failure clears only the battery clock."""
    coordinator = _coordinator()
    record_provided_identifiers(coordinator, coordinator.data, True, True)
    assert coordinator._removal_device_observed_since == T0

    clock["now"] = T0 + 300
    # Battery fetch failed, device list fine: only the battery clock clears.
    record_provided_identifiers(coordinator, coordinator.data, True, False)
    assert coordinator._removal_device_observed_since == T0
    assert coordinator._removal_battery_observed_since is None

    clock["now"] = T0 + 600
    # Device list failed: both clear (battery_ok cannot outlive device_list).
    record_provided_identifiers(coordinator, coordinator.data, False, False)
    assert coordinator._removal_device_observed_since is None
    assert coordinator._removal_battery_observed_since is None

    clock["now"] = T0 + 900
    # A complete cycle restarts both from now.
    record_provided_identifiers(coordinator, coordinator.data, True, True)
    assert coordinator._removal_device_observed_since == T0 + 900
    assert coordinator._removal_battery_observed_since == T0 + 900


def test_hook_is_reexported_from_init():
    """HA resolves the hook by name on the component module."""
    from custom_components.eg4_web_monitor import device_removal

    assert (
        async_remove_config_entry_device
        is device_removal.async_remove_config_entry_device
    )


# ── assess_discovery_completeness: the per-cycle verdicts ────────────


async def test_assess_local_mode_always_device_complete():
    """LOCAL/DONGLE/MODBUS enumerate no devices remotely -- the config set is
    always present, so device discovery cannot silently drop a device."""
    coordinator = _coordinator({"devices": {}})
    coordinator.connection_type = CONNECTION_TYPE_LOCAL
    device_list_ok, _battery_ok = await assess_discovery_completeness(
        coordinator, {"devices": {}}
    )
    assert device_list_ok is True


async def test_assess_cloud_nonempty_is_device_complete():
    coordinator = _coordinator()
    device_list_ok, _battery_ok = await assess_discovery_completeness(
        coordinator, coordinator.data
    )
    assert device_list_ok is True


async def test_assess_cloud_empty_confirmed_empty_plant():
    """An empty table whose get_devices SUCCEEDS (zero rows) is a real empty
    plant -- device-complete, so the sole inverter can age out (finding 6)."""
    coordinator = _coordinator({"devices": {}})
    coordinator.client = MagicMock()
    coordinator.client.api.devices.get_devices = AsyncMock(
        return_value=MagicMock(rows=[])
    )
    device_list_ok, _battery_ok = await assess_discovery_completeness(
        coordinator, {"devices": {}}
    )
    assert device_list_ok is True
    coordinator.client.api.devices.get_devices.assert_awaited_once()


async def test_assess_cloud_empty_device_list_failure_is_incomplete():
    """PR #489 finding 1: an empty table from a SWALLOWED device-list failure
    (get_devices raises) is NOT device-complete."""
    coordinator = _coordinator({"devices": {}})
    coordinator.client = MagicMock()
    coordinator.client.api.devices.get_devices = AsyncMock(
        side_effect=RuntimeError("device list down")
    )
    device_list_ok, battery_ok = await assess_discovery_completeness(
        coordinator, {"devices": {}}
    )
    assert device_list_ok is False
    assert battery_ok is False


async def test_assess_cloud_empty_but_rows_exist_forces_reload():
    """An empty station while get_devices returns rows means pylxpweb
    swallowed a partial load -- refuse and force a hierarchy reload."""
    coordinator = _coordinator({"devices": {}})
    coordinator.station = MagicMock()
    coordinator.client = MagicMock()
    coordinator.client.api.devices.get_devices = AsyncMock(
        return_value=MagicMock(rows=[{"serialNum": LIVE_INVERTER}])
    )
    device_list_ok, _battery_ok = await assess_discovery_completeness(
        coordinator, {"devices": {}}
    )
    assert device_list_ok is False
    assert coordinator.station is None


async def test_assess_battery_ok_healthy():
    coordinator = _coordinator()
    _device_list_ok, battery_ok = await assess_discovery_completeness(
        coordinator, coordinator.data
    )
    assert battery_ok is True


async def test_assess_battery_incomplete_on_degraded_row():
    coordinator = _coordinator()
    data = _healthy_data()
    data["devices"][LIVE_INVERTER]["error"] = "Local transport link down"
    _device_list_ok, battery_ok = await assess_discovery_completeness(coordinator, data)
    assert battery_ok is False


async def test_assess_battery_incomplete_on_link_down():
    coordinator = _coordinator()
    coordinator.is_transport_link_down = MagicMock(return_value=True)
    _device_list_ok, battery_ok = await assess_discovery_completeness(
        coordinator, coordinator.data
    )
    assert battery_ok is False


async def test_assess_battery_incomplete_when_fetch_never_confirmed():
    """PR #489 finding 2: an inverter whose _battery_cache_time is still None
    has never confirmed a battery fetch this session -- battery-incomplete."""
    coordinator = _coordinator()
    unconfirmed = MagicMock()
    unconfirmed._battery_cache_time = None
    coordinator.get_inverter_object = MagicMock(
        side_effect=lambda serial: unconfirmed if serial == LIVE_INVERTER else None
    )
    _device_list_ok, battery_ok = await assess_discovery_completeness(
        coordinator, coordinator.data
    )
    assert battery_ok is False


async def test_assess_battery_complete_when_fetch_confirmed():
    """A confirmed _battery_cache_time (even on a battery-less inverter's
    first empty fetch) passes the battery-completeness check."""
    coordinator = _coordinator()
    confirmed = MagicMock()
    confirmed._battery_cache_time = object()  # any non-None stamp
    coordinator.get_inverter_object = MagicMock(return_value=confirmed)
    _device_list_ok, battery_ok = await assess_discovery_completeness(
        coordinator, coordinator.data
    )
    assert battery_ok is True


# ── Currently provided devices are always refused ────────────────────


async def test_live_identifiers_refused(clock):
    """Provided identifiers are refused even when every window is satisfied --
    the seed + aging below rule out the cold-session refusal masking this
    (adversarial NIT: the provided-check must be the operative gate)."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, coordinator.data)
    entry = _entry(coordinator)
    for identifier in (
        LIVE_INVERTER,
        LIVE_GRIDBOSS,
        "parallel_group_a",
        f"{LIVE_INVERTER}_battery_bank",
        f"{LIVE_INVERTER}-01",
        "BAT002",
        "station_12345",
    ):
        assert (
            await async_remove_config_entry_device(
                HASS, entry, _device_entry(identifier)
            )
            is False
        ), identifier


async def test_hyphenated_parent_serial_battery_refused(clock):
    """A live battery under a hyphenated parent serial is provided verbatim --
    no identifier parsing can misroute it to a non-existent parent. Seeded
    and aged so the provided-check is the operative refusal."""
    data = _healthy_data()
    data["devices"]["ABC-123"] = {
        "type": "inverter",
        "sensors": {},
        "batteries": {"ABC-123-01": {}},
    }
    coordinator = _coordinator(data)
    _seed_history(coordinator, data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, data)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("ABC-123-01"))
        is False
    )


# ── The observation windows ──────────────────────────────────────────


async def test_stale_device_removable_after_device_window(clock):
    """A ghost inverter absent for the device window can be deleted."""
    coordinator = _coordinator()
    ghost_cycle = _healthy_data()
    ghost_cycle["devices"][GONE_SERIAL] = {"type": "inverter", "sensors": {}}
    _seed_history(coordinator, ghost_cycle)

    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    _seed_history(coordinator, coordinator.data)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is True
    )


async def test_stale_device_refused_within_device_window(clock):
    """Seen three minutes ago -- the degraded parallel-group class (#489 r3)."""
    coordinator = _coordinator()
    ghost_cycle = _healthy_data()
    ghost_cycle["devices"]["parallel_group_b"] = {"type": "parallel_group"}
    _seed_history(coordinator, ghost_cycle)

    clock["now"] = T0 + 180
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry("parallel_group_b")
        )
        is False
    )


async def test_refused_until_observation_covers_window(clock):
    """A cold session refuses everything its ledger cannot vouch for."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    entry = _entry(coordinator)

    # Device-class identifier never seen: held to the BATTERY window.
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is False
    )
    # Even a full battery window of uptime cannot excuse a missing clock.
    coordinator._removal_device_observed_since = None
    coordinator._removal_battery_observed_since = None
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_outage_recovery_does_not_count_blind_time(clock):
    """The rr-eviction attack (adversarial HIGH-1): after a >window outage,
    absence accumulated while blind must not authorize deletion at the
    moment of recovery -- the observation clock restarted."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    module_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, module_cycle)

    # 7 hours of failed cycles, then recovery whose first payload exposes
    # only a rotation subset (BAT009 absent, evicted from the rr cache).
    clock["now"] = T0 + 7 * 3600
    coordinator.last_update_success = False
    _seed_history(coordinator, coordinator.data)
    coordinator.last_update_success = True
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is False
    )
    # Only after a full OBSERVED battery window is the module deletable.
    clock["now"] = T0 + 7 * 3600 + BATTERY_ABSENCE_WINDOW + 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is True
    )


async def test_hybrid_link_down_blocks_battery_class(clock):
    """HYBRID serves cloud fallback with NO error row -- the coordinator's
    is_transport_link_down verdict must gate battery deletions there."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    module_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, module_cycle)

    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    # A cycle whose link is down is battery-incomplete: the battery clock is
    # cleared, so no battery deletion is authorized.
    coordinator.is_transport_link_down = MagicMock(return_value=True)
    _seed_history(coordinator, coordinator.data, device_list_ok=True, battery_ok=False)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is False
    )
    # Link recovers: a full observed battery window later, deletable.
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + 2 * BATTERY_ABSENCE_WINDOW + 2
    _seed_history(coordinator, coordinator.data)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is True
    )


async def test_never_seen_identifier_removable_after_battery_window(clock):
    """The #174 ghost: never provided all session, session covers 6 h."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, coordinator.data)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is True
    )
    # Its battery bank (never registered, never seen) goes with it.
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(f"{GONE_SERIAL}_battery_bank")
        )
        is True
    )


@pytest.mark.parametrize("battery_key", [f"{LIVE_INVERTER}-05", "BAT009"])
async def test_battery_keys_hold_battery_window(clock, battery_key):
    """Battery identifiers of BOTH shapes wait out the 6-hour window."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    module_cycle["devices"][LIVE_INVERTER]["batteries"][battery_key] = {}
    _seed_history(coordinator, module_cycle)
    entry = _entry(coordinator)

    # Absent from the current payload but seen 90 s ago (#489 review item
    # 1: a partial payload is a subset, not the truth).
    clock["now"] = T0 + 90
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(battery_key))
        is False
    )
    # The device window is NOT enough for battery-class identifiers.
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(battery_key))
        is False
    )
    # Absent for the full eviction window: really gone.
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, coordinator.data)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(battery_key))
        is True
    )


async def test_last_battery_module_removable(clock):
    """#489 review item 4: an empty batteries dict is steady state, not a
    permanent placeholder -- the evicted last module ages out normally."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    _seed_history(coordinator, module_cycle)

    steady_state = _healthy_data()
    steady_state["devices"][LIVE_INVERTER]["batteries"] = {}
    steady_state["devices"][LIVE_INVERTER]["sensors"] = {}
    coordinator.data = steady_state
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, steady_state)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(f"{LIVE_INVERTER}-01")
        )
        is True
    )


async def test_orphan_bank_removable_bank_of_live_parent_refused(clock):
    """#489 review item 5: a bank is pinned by REGISTRATION, not by its
    parent's existence -- an orphan bank on a shared-battery secondary
    (#169) ages out while its parent lives on."""
    coordinator = _coordinator()
    bank_cycle = _healthy_data()
    _seed_history(coordinator, bank_cycle)

    # The parent stays; the bank stops being registered (count now 0).
    secondary = _healthy_data()
    secondary["devices"][LIVE_INVERTER]["sensors"]["battery_bank_count"] = 0
    secondary["devices"][LIVE_INVERTER]["batteries"] = {}
    coordinator.data = secondary
    entry = _entry(coordinator)
    bank = _device_entry(f"{LIVE_INVERTER}_battery_bank")

    clock["now"] = T0 + 90
    assert await async_remove_config_entry_device(HASS, entry, bank) is False
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    _seed_history(coordinator, secondary)
    assert await async_remove_config_entry_device(HASS, entry, bank) is True


async def test_degraded_row_blocks_battery_class_only(clock):
    """A link-down device row (error marker) blocks battery deletions --
    the battery clock is cleared -- but not device-class ones."""
    coordinator = _coordinator()
    ghost_cycle = _healthy_data()
    ghost_cycle["devices"][GONE_SERIAL] = {"type": "inverter", "sensors": {}}
    ghost_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, ghost_cycle)

    degraded = _healthy_data()
    degraded["devices"][LIVE_INVERTER]["error"] = "Local transport link down"
    coordinator.data = degraded
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    # A degraded row makes the cycle battery-incomplete (device list intact).
    _seed_history(coordinator, degraded, device_list_ok=True, battery_ok=False)
    entry = _entry(coordinator)

    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is False
    )
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is True
    )


async def test_sole_inverter_removable_from_empty_table(clock):
    """#489 review item 6: rows=[] is a legitimate final state -- the
    plant's former sole inverter ages out against a CONFIRMED empty table."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)

    coordinator.data = {"devices": {}}
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    # device_list_ok True == the empty table was confirmed a real empty plant.
    _seed_history(coordinator, coordinator.data, device_list_ok=True, battery_ok=True)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(LIVE_INVERTER)
        )
        is True
    )


async def test_cold_start_failed_device_list_refuses_live_inverter(clock):
    """PR #489 finding 1: a swallowed device-list failure publishes an empty
    table; device_list_ok stays False so the still-registered inverter is
    never authorized for deletion no matter how long the outage runs."""
    coordinator = _coordinator({"devices": {}})
    entry = _entry(coordinator)
    # Six hours of empty, unconfirmed cycles.
    for minute in range(0, 6 * 60 + 30, 10):
        clock["now"] = T0 + minute * 60
        _seed_history(
            coordinator, coordinator.data, device_list_ok=False, battery_ok=False
        )
    assert coordinator._removal_device_observed_since is None
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(LIVE_INVERTER)
        )
        is False
    )


async def test_battery_endpoint_outage_refuses_live_module(clock):
    """PR #489 finding 2: a battery-endpoint failure keeps battery_ok False,
    so a never-seen live module cannot age out over the 6-hour window."""
    coordinator = _coordinator()
    entry = _entry(coordinator)
    # First cycle sees the live modules; then the battery endpoint fails for
    # seven hours (device list stays healthy).
    _seed_history(coordinator, coordinator.data)
    for minute in range(10, 7 * 60 + 10, 10):
        clock["now"] = T0 + minute * 60
        _seed_history(
            coordinator, coordinator.data, device_list_ok=True, battery_ok=False
        )
    assert coordinator._removal_battery_observed_since is None
    # A registry module that was never seen this session (cold carry-forward)
    # stays refused despite 7 h of "successful" cycles.
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT099"))
        is False
    )


async def test_serving_cached_data_refuses_deletion(clock):
    """PR #489 finding 3: while a fetch has failed and cached data is served
    (last_update_success still True), the hook must refuse -- the table's
    absences are an outage, not a fresh observation."""
    coordinator = _coordinator()
    ghost_cycle = _healthy_data()
    ghost_cycle["devices"][GONE_SERIAL] = {"type": "inverter", "sensors": {}}
    _seed_history(coordinator, ghost_cycle)
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    _seed_history(coordinator, coordinator.data)
    entry = _entry(coordinator)

    # Fresh cycle: deletable.
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is True
    )
    # Now serving cached data (one suppressed failure): refuse.
    coordinator._consecutive_update_failures = 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_stale_station_removable_after_window(clock):
    """A station device left over after moving to LOCAL ages out."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)

    local_only = _healthy_data()
    del local_only["station"]
    coordinator.data = local_only
    entry = _entry(coordinator)
    station = _device_entry("station_12345")

    clock["now"] = T0 + 60
    assert await async_remove_config_entry_device(HASS, entry, station) is False
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    _seed_history(coordinator, local_only)
    assert await async_remove_config_entry_device(HASS, entry, station) is True


def test_ledger_pruned_beyond_prune_age(clock):
    """The ledger cannot grow unbounded: entries far past any deletion
    decision are dropped on the next stamp."""
    coordinator = _coordinator()
    churned = _healthy_data()
    churned["devices"]["EPHEMERAL@0"] = {"type": "inverter", "sensors": {}}
    _seed_history(coordinator, churned)
    assert "EPHEMERAL@0" in coordinator._removal_identifier_last_seen

    clock["now"] = T0 + _LEDGER_PRUNE_AGE + 1
    _seed_history(coordinator, coordinator.data)
    assert "EPHEMERAL@0" not in coordinator._removal_identifier_last_seen
    # Still-provided identifiers are re-stamped, never pruned.
    assert LIVE_INVERTER in coordinator._removal_identifier_last_seen


# ── Unhealthy coordinator states ─────────────────────────────────────


async def test_refused_when_update_failed(clock):
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    coordinator.last_update_success = False
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_refused_without_runtime_data():
    never_loaded = MockConfigEntry(domain=DOMAIN, entry_id="never_loaded")
    assert (
        await async_remove_config_entry_device(
            HASS, never_loaded, _device_entry(GONE_SERIAL)
        )
        is False
    )


async def test_refused_for_foreign_identifiers(clock):
    """A registry entry with no DOMAIN identifiers is never deletable here."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    entry = _entry(coordinator)
    device = MagicMock()
    device.identifiers = {("other_domain", "whatever")}
    assert await async_remove_config_entry_device(HASS, entry, device) is False


# ── Coordinator wiring ───────────────────────────────────────────────


async def test_update_data_stamps_ledger_and_resets_clocks_on_cached_fallback(hass):
    """The real _async_update_data stamps the ledger on success and, on the
    3-strike cached-fallback path, does NOT re-stamp AND clears both
    observation clocks so absence cannot accumulate across the outage
    (adversarial MEDIUM: the design's load-bearing wiring, plus #489
    finding 3)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="wiring_test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
        },
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    healthy = _healthy_data()

    with patch.object(
        coordinator,
        "_route_update_by_connection_type",
        AsyncMock(return_value=healthy),
    ):
        await coordinator._async_update_data()
    assert coordinator._removal_device_observed_since is not None
    assert coordinator._removal_battery_observed_since is not None
    first_stamp = coordinator._removal_identifier_last_seen[LIVE_INVERTER]

    # A failed fetch with prior data serves the cache -- old evidence must
    # not refresh any last-seen stamp, and both clocks reset.
    coordinator.data = healthy
    with patch.object(
        coordinator,
        "_route_update_by_connection_type",
        AsyncMock(side_effect=UpdateFailed("boom")),
    ):
        served = await coordinator._async_update_data()
    assert served is healthy
    assert coordinator._removal_identifier_last_seen[LIVE_INVERTER] == first_stamp
    assert coordinator._removal_device_observed_since is None
    assert coordinator._removal_battery_observed_since is None
