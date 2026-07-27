"""Tests for per-device removal (async_remove_config_entry_device, #174).

The removal gate judges absence over the observation ledger — see
device_removal.py's module docstring for the design. The clock fixture
drives the module's ``monotonic`` so tests can age identifiers past their
class windows deterministically.
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
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.device_removal import (
    BATTERY_ABSENCE_WINDOW,
    DEVICE_ABSENCE_WINDOW,
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
    coordinator.plant_id = "12345"
    coordinator.data = _healthy_data() if data is None else data
    coordinator._removal_identifier_last_seen = {}
    coordinator._removal_observed_since = None
    coordinator.is_transport_link_down = MagicMock(return_value=False)
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


def _seed_history(coordinator: MagicMock, data: dict) -> None:
    """Record one historical cycle at the current (patched) clock time."""
    record_provided_identifiers(coordinator, data)


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


def test_record_stamps_ledger_and_observed_since(clock):
    coordinator = _coordinator()
    record_provided_identifiers(coordinator, coordinator.data)
    assert coordinator._removal_observed_since == T0
    assert coordinator._removal_identifier_last_seen[LIVE_INVERTER] == (
        T0,
        "device",
    )
    assert coordinator._removal_identifier_last_seen["BAT002"] == (T0, "battery")

    clock["now"] = T0 + 300
    record_provided_identifiers(coordinator, coordinator.data)
    # Contiguous successes keep the observation clock; last-seen advances.
    assert coordinator._removal_observed_since == T0
    assert coordinator._removal_identifier_last_seen["BAT002"] == (
        T0 + 300,
        "battery",
    )


def test_observed_since_restarts_after_failed_cycle(clock):
    """Blind time never counts: recovery from a failed cycle resets the
    observation clock (record sees the PREVIOUS cycle's verdict in
    last_update_success while the update method runs)."""
    coordinator = _coordinator()
    record_provided_identifiers(coordinator, coordinator.data)
    assert coordinator._removal_observed_since == T0

    # A 7-hour outage, then the recovery cycle records while the
    # coordinator still carries the failed verdict.
    clock["now"] = T0 + 7 * 3600
    coordinator.last_update_success = False
    record_provided_identifiers(coordinator, coordinator.data)
    assert coordinator._removal_observed_since == T0 + 7 * 3600


def test_hook_is_reexported_from_init():
    """HA resolves the hook by name on the component module."""
    from custom_components.eg4_web_monitor import device_removal

    assert (
        async_remove_config_entry_device
        is device_removal.async_remove_config_entry_device
    )


# ── Currently provided devices are always refused ────────────────────


async def test_live_identifiers_refused(clock):
    """Provided identifiers are refused even when every window is satisfied —
    the seed + aging below rule out the cold-session refusal masking this
    (adversarial NIT: the provided-check must be the operative gate)."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, coordinator.data)
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
    """A live battery under a hyphenated parent serial is provided verbatim —
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
    record_provided_identifiers(coordinator, data)
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
    record_provided_identifiers(coordinator, coordinator.data)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is True
    )


async def test_stale_device_refused_within_device_window(clock):
    """Seen three minutes ago — the degraded parallel-group class (#489 r3)."""
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
    coordinator._removal_observed_since = None
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(GONE_SERIAL))
        is False
    )


async def test_outage_recovery_does_not_count_blind_time(clock):
    """The rr-eviction attack (adversarial HIGH-1): after a >window outage,
    absence accumulated while blind must not authorize deletion at the
    moment of recovery — the observation clock restarted."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    module_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, module_cycle)

    # 7 hours of failed cycles, then recovery whose first payload exposes
    # only a rotation subset (BAT009 absent, evicted from the rr cache).
    clock["now"] = T0 + 7 * 3600
    coordinator.last_update_success = False
    record_provided_identifiers(coordinator, coordinator.data)
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
    """HYBRID serves cloud fallback with NO error row — the coordinator's
    is_transport_link_down verdict must gate battery deletions there."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    module_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, module_cycle)

    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, coordinator.data)
    coordinator.is_transport_link_down = MagicMock(return_value=True)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is False
    )
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry("BAT009"))
        is True
    )


async def test_never_seen_identifier_removable_after_battery_window(clock):
    """The #174 ghost: never provided all session, session covers 6 h."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, coordinator.data)
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
    assert (
        await async_remove_config_entry_device(HASS, entry, _device_entry(battery_key))
        is True
    )


async def test_last_battery_module_removable(clock):
    """#489 review item 4: an empty batteries dict is steady state, not a
    permanent placeholder — the evicted last module ages out normally."""
    coordinator = _coordinator()
    module_cycle = _healthy_data()
    _seed_history(coordinator, module_cycle)

    steady_state = _healthy_data()
    steady_state["devices"][LIVE_INVERTER]["batteries"] = {}
    steady_state["devices"][LIVE_INVERTER]["sensors"] = {}
    coordinator.data = steady_state
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, steady_state)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(f"{LIVE_INVERTER}-01")
        )
        is True
    )


async def test_orphan_bank_removable_bank_of_live_parent_refused(clock):
    """#489 review item 5: a bank is pinned by REGISTRATION, not by its
    parent's existence — an orphan bank on a shared-battery secondary
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
    record_provided_identifiers(coordinator, secondary)
    assert await async_remove_config_entry_device(HASS, entry, bank) is True


async def test_degraded_row_blocks_battery_class_only(clock):
    """A link-down device row (error marker) blocks battery deletions —
    no parent can attest module absence — but not device-class ones."""
    coordinator = _coordinator()
    ghost_cycle = _healthy_data()
    ghost_cycle["devices"][GONE_SERIAL] = {"type": "inverter", "sensors": {}}
    ghost_cycle["devices"][LIVE_INVERTER]["batteries"]["BAT009"] = {}
    _seed_history(coordinator, ghost_cycle)

    degraded = _healthy_data()
    degraded["devices"][LIVE_INVERTER]["error"] = "Local transport link down"
    coordinator.data = degraded
    clock["now"] = T0 + BATTERY_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, degraded)
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
    """#489 review item 6: rows=[] is a legitimate final state — the
    plant's former sole inverter ages out against an empty table."""
    coordinator = _coordinator()
    _seed_history(coordinator, coordinator.data)

    coordinator.data = {"devices": {}}
    clock["now"] = T0 + DEVICE_ABSENCE_WINDOW + 1
    record_provided_identifiers(coordinator, coordinator.data)
    entry = _entry(coordinator)
    assert (
        await async_remove_config_entry_device(
            HASS, entry, _device_entry(LIVE_INVERTER)
        )
        is True
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
    record_provided_identifiers(coordinator, local_only)
    assert await async_remove_config_entry_device(HASS, entry, station) is True


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


async def test_update_data_stamps_ledger_and_skips_cached_fallback(hass):
    """The real _async_update_data stamps the ledger on success and does
    NOT stamp on the 3-strike cached-fallback path (adversarial MEDIUM:
    the design's load-bearing wiring, previously unpinned)."""
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
    assert coordinator._removal_observed_since is not None
    first_stamp = coordinator._removal_identifier_last_seen[LIVE_INVERTER]

    # A failed fetch with prior data serves the cache — old evidence must
    # not refresh any last-seen stamp.
    coordinator.data = healthy
    with patch.object(
        coordinator,
        "_route_update_by_connection_type",
        AsyncMock(side_effect=UpdateFailed("boom")),
    ):
        served = await coordinator._async_update_data()
    assert served is healthy
    assert coordinator._removal_identifier_last_seen[LIVE_INVERTER] == first_stamp
