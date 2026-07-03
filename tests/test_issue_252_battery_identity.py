"""Regression tests for issue #252 — unified battery identity across modes.

A cloud→hybrid migration duplicated every battery device: CLOUD keyed battery
devices by the cloud ``batteryKey`` (``{inverterSn}_{batterySn}`` → cleaned to
``{inv}-{batterySn}``), while HYBRID keyed them positionally
(``{inv}-{cloud_index+1:02d}``) and LOCAL keyed them by first-seen order
(``{inv}-{NN}``).  Packs whose BMS reports real serials therefore re-keyed on
every mode change → new unique_ids → new devices, orphaning the old ones.

The fix derives ONE canonical, serial-first key in all three paths:

- CLOUD: unchanged (stable 3.3.0 format — preserves existing entities).
- HYBRID: same cloud ``batteryKey`` derivation as CLOUD (shared helper).
- LOCAL: synthesized from the CAN-reported serial → identical to the cloud key
  for the same battery (cloud ``batterySn`` == CAN serial; the #258 overlay
  already matches on that equality).
- No serial → positional fallback (unchanged).

Plus a coordinator-driven registry migration renaming legacy positional
unique_ids to the canonical ones (entity_id/history preserved), removing
positional duplicates when the canonical entity already exists, and carrying
device customizations (area/name/labels) to the canonical device.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.utils import (
    cloud_battery_key,
    local_battery_key,
)
from pylxpweb.transports.data import BatteryBankData, BatteryData

from tests.conftest import make_real_inverter

INV = "4394012345"
BAT_SN_1 = "029200112233"
BAT_SN_2 = "029200445566"


@pytest.fixture
def mock_config_entry():
    """A cloud config entry (HYBRID is simulated by attaching a transport)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="issue_252_test",
    )


def _cloud_battery(index: int, serial: str) -> SimpleNamespace:
    """A cloud Battery stand-in matching pylxpweb's real attribute surface.

    The real cloud ``batteryKey`` is ``{inverterSn}_{batterySn}`` — verified
    against the recorded getBatteryInfo sample (battery_44300E0585.json).
    """
    return SimpleNamespace(
        battery_key=f"{INV}_{serial}",
        battery_sn=serial,
        battery_index=index,
        voltage=52.0,
        soc=85,
        model=None,
        bms_model=None,
        battery_type_text=None,
    )


def _transport_battery(index: int, serial: str, soc: int = 90) -> BatteryData:
    """A local/transport BatteryData with a CAN-reported serial."""
    return BatteryData(
        battery_index=index,
        serial_number=serial,
        voltage=52.5,
        soc=soc,
    )


def _mock_station(inverters: list) -> MagicMock:
    station = MagicMock()
    station.id = "12345"
    station.name = "Test Station"
    station.timezone = "GMT -8"
    station.all_inverters = inverters
    station.all_mid_devices = []
    station.standalone_mid_devices = []
    station.refresh_all_data = AsyncMock()
    station.parallel_groups = []
    return station


async def _process(coordinator: EG4DataUpdateCoordinator) -> dict:
    """Run _process_station_data with the inverter-processing stub."""
    with (
        patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "LXP-LB-US 10K",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ),
        patch(
            "custom_components.eg4_web_monitor.coordinator_http._build_individual_battery_mapping",
            side_effect=lambda b: {"battery_soc": b.soc},
        ),
        patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_individual_battery_mapping",
            side_effect=lambda b: {"battery_soc": b.soc},
        ),
    ):
        return await coordinator._process_station_data()


def _make_coordinator(hass, entry, *, cloud=None, transport=None):
    """Coordinator wired with a real inverter carrying the given battery data."""
    inv = make_real_inverter(serial_number=INV)
    if cloud is not None:
        bank = MagicMock()
        bank.batteries = cloud
        bank.battery_count = len(cloud)
        inv._battery_bank = bank
    else:
        inv._battery_bank = None
    if transport is not None:
        inv._transport_battery = BatteryBankData(batteries=transport)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator.station = _mock_station([inv])
    coordinator._inverter_cache = {INV: inv}
    # Seed parameters so no background parameter refresh is scheduled.
    coordinator.data = {"parameters": {INV: {}}}
    return coordinator


# ── Canonical key helpers ─────────────────────────────────────────────


class TestCanonicalKeyHelpers:
    """Pure key-derivation helpers shared by all three paths."""

    def test_cloud_key_real_serial(self):
        batt = _cloud_battery(0, BAT_SN_1)
        assert cloud_battery_key(INV, batt) == f"{INV}-{BAT_SN_1}"

    def test_cloud_key_placeholder_serial(self):
        """EG4 packs without BMS serials keep their historical {inv}-NN keys."""
        batt = SimpleNamespace(
            battery_key=f"{INV}_Battery_ID_03",
            battery_sn="Battery_ID_03",
            battery_index=2,
        )
        assert cloud_battery_key(INV, batt) == f"{INV}-03"

    def test_cloud_key_missing_battery_key_uses_serial(self):
        """A cloud object without batteryKey falls back to the serial."""
        batt = SimpleNamespace(battery_sn=BAT_SN_1, battery_index=0)
        assert cloud_battery_key(INV, batt) == f"{INV}-{BAT_SN_1}"

    def test_cloud_key_non_string_battery_key_uses_serial(self):
        """A non-str batteryKey (mock artifacts, garbage) is ignored."""
        batt = SimpleNamespace(
            battery_key=MagicMock(), battery_sn=BAT_SN_1, battery_index=0
        )
        assert cloud_battery_key(INV, batt) == f"{INV}-{BAT_SN_1}"

    def test_cloud_key_no_identity_falls_back_to_index(self):
        batt = SimpleNamespace(battery_key=None, battery_sn=None, battery_index=1)
        assert cloud_battery_key(INV, batt) == f"{INV}-02"

    def test_local_key_real_serial(self):
        assert local_battery_key(INV, BAT_SN_1, 0) == f"{INV}-{BAT_SN_1}"

    def test_local_key_placeholder_serial(self):
        """CAN serials shaped like Battery_ID_NN normalize like the cloud key."""
        assert local_battery_key(INV, "Battery_ID_05", 0) == f"{INV}-05"

    def test_local_key_no_serial_falls_back_to_slot(self):
        assert local_battery_key(INV, None, 2) == f"{INV}-03"
        assert local_battery_key(INV, "", 0) == f"{INV}-01"

    def test_local_key_matches_cloud_key_for_same_battery(self):
        """The cross-mode invariant: same battery → same key in every path."""
        cloud = _cloud_battery(0, BAT_SN_1)
        assert cloud_battery_key(INV, cloud) == local_battery_key(INV, BAT_SN_1, 0)


# ── Cross-mode identity (the #252 regression) ─────────────────────────


class TestCrossModeIdentity:
    """CLOUD, HYBRID, and LOCAL must produce identical battery keys."""

    async def test_hybrid_keys_match_cloud_keys(self, hass, mock_config_entry):
        """Cloud-only then hybrid (transport attached) — identical keys.

        This is the exact #252 migration: the same station processed first
        without transport data (cloud era) and then with it (hybrid era) must
        key every battery identically, so no new devices are created.
        """
        mock_config_entry.add_to_hass(hass)
        cloud = [_cloud_battery(0, BAT_SN_1), _cloud_battery(1, BAT_SN_2)]

        coordinator = _make_coordinator(hass, mock_config_entry, cloud=cloud)
        cloud_result = await _process(coordinator)
        cloud_keys = set(cloud_result["devices"][INV]["batteries"])

        transport = [
            _transport_battery(0, BAT_SN_1),
            _transport_battery(1, BAT_SN_2),
        ]
        coordinator2 = _make_coordinator(
            hass, mock_config_entry, cloud=cloud, transport=transport
        )
        hybrid_result = await _process(coordinator2)
        hybrid_keys = set(hybrid_result["devices"][INV]["batteries"])

        assert cloud_keys == hybrid_keys == {f"{INV}-{BAT_SN_1}", f"{INV}-{BAT_SN_2}"}

    async def test_hybrid_overlay_lands_on_cloud_key(self, hass, mock_config_entry):
        """Transport data must overlay the SAME key the cloud baseline used."""
        mock_config_entry.add_to_hass(hass)
        cloud = [_cloud_battery(0, BAT_SN_1)]
        transport = [_transport_battery(0, BAT_SN_1, soc=91)]
        coordinator = _make_coordinator(
            hass, mock_config_entry, cloud=cloud, transport=transport
        )

        result = await _process(coordinator)
        batteries = result["devices"][INV]["batteries"]
        assert list(batteries) == [f"{INV}-{BAT_SN_1}"]
        # Transport SOC (91) overlaid the cloud baseline (85) on the same key.
        assert batteries[f"{INV}-{BAT_SN_1}"]["battery_soc"] == 91

    async def test_local_keys_match_cloud_keys(self, hass, mock_config_entry):
        """LOCAL round-robin merge keys by serial, matching the cloud key."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        result = coordinator._merge_round_robin_batteries(
            INV,
            [_transport_battery(0, BAT_SN_1), _transport_battery(1, BAT_SN_2)],
        )

        assert set(result) == {f"{INV}-{BAT_SN_1}", f"{INV}-{BAT_SN_2}"}

    async def test_local_placeholder_serials_keep_numeric_keys(
        self, hass, mock_config_entry
    ):
        """Battery_ID_NN packs keep {inv}-NN keys (EG4 backward compat)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        result = coordinator._merge_round_robin_batteries(
            INV,
            [
                _transport_battery(0, "Battery_ID_01"),
                _transport_battery(1, "Battery_ID_02"),
            ],
        )

        assert set(result) == {f"{INV}-01", f"{INV}-02"}

    async def test_local_key_stable_across_rotation_order(
        self, hass, mock_config_entry
    ):
        """Serial keys no longer depend on first-seen order (restart-stable)."""
        mock_config_entry.add_to_hass(hass)
        c1 = EG4DataUpdateCoordinator(hass, mock_config_entry)
        c1._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_2)])
        r1 = c1._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        c2 = EG4DataUpdateCoordinator(hass, mock_config_entry)
        c2._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])
        r2 = c2._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_2)])

        assert set(r1) == set(r2) == {f"{INV}-{BAT_SN_1}", f"{INV}-{BAT_SN_2}"}

    async def test_local_no_serial_fallback_after_debounce(
        self, hass, mock_config_entry
    ):
        """Packs without CAN serials keep positional keys (pre-#165 firmware).

        Positional fallback entries are debounced (_NO_SERIAL_EXPOSE_POLLS) so
        a late-arriving serial can claim the identity first; a genuinely
        serial-less pack surfaces its positional entities after the debounce.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        payload = [_transport_battery(0, ""), _transport_battery(1, "")]
        assert coordinator._merge_round_robin_batteries(INV, payload) == {}
        assert coordinator._merge_round_robin_batteries(INV, payload) == {}
        result = coordinator._merge_round_robin_batteries(INV, payload)

        assert set(result) == {f"{INV}-01", f"{INV}-02"}


# ── Registry migration: positional → canonical ────────────────────────


def _seed_positional_battery(
    hass,
    entry,
    old_key: str,
    *,
    area_id: str | None = None,
    sensor_suffixes: tuple[str, ...] = ("battery_soc", "battery_voltage"),
) -> tuple[str, list[str]]:
    """Seed a positional-era battery device + entities in the registries.

    Returns (device_id, [entity_ids]).
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, old_key)},
        name=f"Battery {old_key}",
        manufacturer="EG4",
    )
    if area_id:
        device_registry.async_update_device(device.id, area_id=area_id)

    entity_ids = []
    for suffix in sensor_suffixes:
        entity = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{INV}_{old_key}_{suffix}",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"eg4_test_{INV}_battery_{old_key.lower()}_{suffix}",
        )
        entity_ids.append(entity.entity_id)
    button = entity_registry.async_get_or_create(
        "button",
        DOMAIN,
        f"{INV}_{old_key}_refresh_data",
        config_entry=entry,
        device_id=device.id,
    )
    entity_ids.append(button.entity_id)
    return device.id, entity_ids


class TestPositionalKeyMigration:
    """Legacy positional unique_ids migrate to the canonical serial keys."""

    async def test_local_merge_renames_positional_entities(
        self, hass, mock_config_entry
    ):
        """Pure-LOCAL beta install: device re-identified in place, history kept.

        The positional device must keep its UUID (device automations, device
        triggers and dashboard cards reference it) and its area/name/labels;
        the entity unique_ids are renamed in place (entity_id preserved).
        """
        mock_config_entry.add_to_hass(hass)
        area = ar.async_get(hass).async_create("Casa de Maquinas")
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        seeded_device_id, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, area_id=area.id
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        entity_registry = er.async_get(hass)
        # Same entity_ids (history preserved), new unique_ids.
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None, f"{entity_id} vanished"
            assert new_key in entry_.unique_id
            assert old_key not in entry_.unique_id

        # The positional identifier no longer resolves; the canonical one
        # resolves to the SAME device row (re-identified in place).
        device_registry = dr.async_get(hass)
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None
        new_device = device_registry.async_get_device({(DOMAIN, new_key)})
        assert new_device is not None
        assert new_device.id == seeded_device_id  # device UUID preserved
        assert new_device.area_id == area.id
        # Entities still point at that device.
        for entity_id in entity_ids:
            assert entity_registry.async_get(entity_id).device_id == new_device.id

    async def test_cloud_hybrid_duplicate_is_removed(self, hass, mock_config_entry):
        """Cloud→hybrid install (#252): positional duplicates are purged.

        The registry holds BOTH the cloud-era serial-keyed entities (with the
        user's history) AND the beta positional duplicates.  The duplicates and
        their devices must be removed; the cloud entities stay untouched.
        """
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"

        # Cloud-era entity + device (the identity that must survive).
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        cloud_device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, new_key)},
            name=f"Battery {new_key}",
        )
        cloud_entity = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{INV}_{new_key}_battery_soc",
            config_entry=mock_config_entry,
            device_id=cloud_device.id,
        )

        # Beta positional duplicates.
        old_device_id, old_entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        # Cloud entity untouched.
        surviving = entity_registry.async_get(cloud_entity.entity_id)
        assert surviving is not None
        assert surviving.unique_id == f"{INV}_{new_key}_battery_soc"
        # Positional sensor duplicate removed (button has no serial twin and
        # is renamed instead).
        assert entity_registry.async_get(old_entity_ids[0]) is None
        button_entry = entity_registry.async_get(old_entity_ids[-1])
        assert button_entry is not None
        assert button_entry.unique_id == f"{INV}_{new_key}_refresh_data"
        # Positional device removed, cloud device still there.
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None
        assert device_registry.async_get_device({(DOMAIN, new_key)}) is not None

    async def test_hybrid_path_migrates_positional_entities(
        self, hass, mock_config_entry
    ):
        """HYBRID processing derives legacy index keys and migrates them."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        cloud = [_cloud_battery(0, BAT_SN_1)]
        transport = [_transport_battery(0, BAT_SN_1)]
        coordinator = _make_coordinator(
            hass, mock_config_entry, cloud=cloud, transport=transport
        )
        await _process(coordinator)

        entity_registry = er.async_get(hass)
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None
            assert new_key in entry_.unique_id

    async def test_cloud_fallback_path_migrates_positional_entities(
        self, hass, mock_config_entry
    ):
        """CLOUD-only processing (hybrid first refresh) also migrates."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = _make_coordinator(
            hass, mock_config_entry, cloud=[_cloud_battery(0, BAT_SN_1)]
        )
        await _process(coordinator)

        entity_registry = er.async_get(hass)
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None
            assert new_key in entry_.unique_id

    async def test_active_positional_key_not_migrated(self, hass, mock_config_entry):
        """A positional key still actively used by a no-serial battery stays.

        Mixed pack: slot 0 has no serial (fallback key {inv}-01, debounced but
        counting as active), slot 1 has a real serial whose legacy shadow key
        is ALSO {inv}-01.  Migrating would steal the live battery's entities —
        it must be skipped, on the very first poll and after the fallback is
        exposed.
        """
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        payload = [_transport_battery(0, ""), _transport_battery(1, BAT_SN_1)]
        result = coordinator._merge_round_robin_batteries(INV, payload)
        # Serial battery exposed immediately; fallback slot still debounced.
        assert f"{INV}-{BAT_SN_1}" in result
        result = coordinator._merge_round_robin_batteries(INV, payload)
        result = coordinator._merge_round_robin_batteries(INV, payload)

        # Fallback key is active for the no-serial battery after debounce.
        assert f"{INV}-01" in result
        # Registry untouched: unique_ids still positional.
        entity_registry = er.async_get(hass)
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None
            assert old_key in entry_.unique_id

    async def test_unrelated_entities_untouched(self, hass, mock_config_entry):
        """Inverter-level entities never match the battery prefix rewrite."""
        mock_config_entry.add_to_hass(hass)
        entity_registry = er.async_get(hass)
        inverter_entity = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{INV}_battery_voltage",
            config_entry=mock_config_entry,
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        entry_ = entity_registry.async_get(inverter_entity.entity_id)
        assert entry_ is not None
        assert entry_.unique_id == f"{INV}_battery_voltage"

    async def test_migration_is_one_shot_per_session(self, hass, mock_config_entry):
        """The registry scan fires once per (inverter, legacy key)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        # Seed a positional entity AFTER the first merge; the second merge
        # must not touch it (migration for this key already ran).
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, f"{INV}-01", sensor_suffixes=("battery_soc",)
        )
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert f"{INV}-01" in entry_.unique_id

    async def test_dup_path_backfills_unset_customizations(
        self, hass, mock_config_entry
    ):
        """Dup removal backfills area from the positional device when unset.

        Cloud→hybrid scenario: the user assigned an area to the fresh
        positional device while the cloud device sat stale.  The positional
        device is removed, but its area must move to the canonical device —
        without overwriting a canonical customization that exists.
        """
        mock_config_entry.add_to_hass(hass)
        area = ar.async_get(hass).async_create("Garagem")
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        # Canonical (cloud-era) device WITHOUT an area, but with a user name.
        cloud_device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, new_key)},
            name=f"Battery {new_key}",
        )
        device_registry.async_update_device(cloud_device.id, name_by_user="Cloud Name")
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{INV}_{new_key}_battery_soc",
            config_entry=mock_config_entry,
            device_id=cloud_device.id,
        )
        # Positional device WITH an area and a user name.
        old_device_id, _ = _seed_positional_battery(
            hass,
            mock_config_entry,
            old_key,
            area_id=area.id,
            sensor_suffixes=("battery_soc",),
        )
        device_registry.async_update_device(old_device_id, name_by_user="Beta Name")

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        surviving = device_registry.async_get_device({(DOMAIN, new_key)})
        assert surviving is not None
        # Area backfilled from the positional device (canonical had none)...
        assert surviving.area_id == area.id
        # ...but the canonical user name wins over the positional one.
        assert surviving.name_by_user == "Cloud Name"
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None


# ── P0: no-serial → serial cold-start sequence (third review) ─────────


class TestNoSerialThenSerialSequence:
    """A battery whose serial arrives late must not fork into two identities."""

    async def test_two_poll_no_serial_then_serial_single_identity(
        self, hass, mock_config_entry
    ):
        """Poll 1 without serial, poll 2 with serial → ONE battery, migrated.

        Regression for the review P0: the poll-1 positional fallback entry
        used to persist in the never-evicting rr-cache, keeping a frozen
        positional twin forever AND blocking the registry migration via the
        active-key guard.
        """
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        # Poll 1: battery reports data but no CAN serial yet.
        result1 = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, "")]
        )
        # Poll 2: same battery, serial now readable.
        result2 = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, BAT_SN_1)]
        )

        # Exactly one identity — no frozen positional twin.
        assert set(result2) == {new_key}
        assert old_key not in result2
        # And it stays gone on subsequent polls.
        result3 = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, BAT_SN_1)]
        )
        assert set(result3) == {new_key}
        _ = result1

        # Migration fired: registry rows renamed to the canonical key.
        entity_registry = er.async_get(hass)
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None
            assert new_key in entry_.unique_id
        device_registry = dr.async_get(hass)
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None
        assert device_registry.async_get_device({(DOMAIN, new_key)}) is not None

    async def test_exposed_fallback_then_serial_still_single_identity(
        self, hass, mock_config_entry
    ):
        """Serial arriving after the debounce window still retires the twin."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        no_serial = [_transport_battery(0, "")]
        for _ in range(3):  # exposed after _NO_SERIAL_EXPOSE_POLLS
            result = coordinator._merge_round_robin_batteries(INV, no_serial)
        assert set(result) == {f"{INV}-01"}

        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, BAT_SN_1)]
        )
        assert set(result) == {f"{INV}-{BAT_SN_1}"}

    async def test_placeholder_serial_claiming_own_fallback_slot(
        self, hass, mock_config_entry
    ):
        """Serial 'Battery_ID_01' at slot 0 owns the {inv}-01 key cleanly.

        The canonical key equals the slot's fallback key here — retiring the
        fallback must not delete the entry the serial just claimed.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        no_serial = [_transport_battery(0, "")]
        for _ in range(3):
            coordinator._merge_round_robin_batteries(INV, no_serial)

        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, "Battery_ID_01")]
        )
        assert set(result) == {f"{INV}-01"}


# ── #302: retirement across pylxpweb#204 virtual-slot shifts ──────────


class TestShiftedSlotRetirement:
    """Exposed positional keys retire even when battery_index shifts (#302).

    Since pylxpweb#204, reconciling a "pos:N" accumulator entry evicts it and
    mints the arriving serial a NEW virtual slot (the old slot stays a
    reservation hole), so the serial's ``battery_index`` no longer matches the
    slot whose positional key the integration exposed.  Retirement must key
    off the exposure record, not the shifted index.
    """

    async def test_shifted_index_retires_exposed_fallback_immediately(
        self, hass, mock_config_entry, caplog
    ):
        """Serial arriving at a SHIFTED index still retires the exposed twin.

        Regression for #302: pre-fix the merge retired {INV}-02 (current
        index) instead of the exposed {INV}-01, leaving a frozen positional
        twin until the 6h age bound and an orphaned debounce counter.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        no_serial = [_transport_battery(0, "")]
        for _ in range(3):  # exposed after _NO_SERIAL_EXPOSE_POLLS
            result = coordinator._merge_round_robin_batteries(INV, no_serial)
        assert set(result) == {f"{INV}-01"}
        # Carry-forward layer also published the positional key earlier.
        coordinator._battery_carry_forward[INV] = {f"{INV}-01": {"battery_soc": 90}}

        # Serial becomes readable: pylxpweb evicts pos:0 and mints the serial
        # virtual slot 1; slot 0 stays a reservation hole (never served again).
        with caplog.at_level(logging.INFO):
            result = coordinator._merge_round_robin_batteries(
                INV, [_transport_battery(1, BAT_SN_1)]
            )

        # The exposed positional twin retired immediately — no 6h wait.
        assert set(result) == {f"{INV}-{BAT_SN_1}"}
        assert coordinator._battery_fallback_keys[INV] == set()
        # The retirement is user-visible at INFO naming the stale key: its
        # registry rows can survive as orphans (the #252 migration renames
        # first-seen-order legacy keys, which need not match the
        # slot-position fallback), so users need a discoverable trace.
        retire_logs = [
            record
            for record in caplog.records
            if record.levelno == logging.INFO
            and "retired stale positional battery fallback" in record.getMessage()
            and f"{INV}-01" in record.getMessage()
        ]
        assert len(retire_logs) == 1
        # The stale slot-0 debounce counter is popped too.
        assert coordinator._battery_noserial_polls[INV] == {}
        # Retirement is authoritative over the carry-forward layer.
        assert f"{INV}-01" not in coordinator._battery_carry_forward[INV]

        # And it stays gone on subsequent polls.
        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(1, BAT_SN_1)]
        )
        assert set(result) == {f"{INV}-{BAT_SN_1}"}

    async def test_shifted_retirement_spares_still_serialless_sibling(
        self, hass, mock_config_entry
    ):
        """Only the reconciled battery's positional key retires.

        A still-serial-less sibling re-claims its positional key on the same
        poll (the transport serves the full accumulator every poll), so the
        absence-based sweep must leave it — and its debounce counter — alone.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        pair = [_transport_battery(0, ""), _transport_battery(1, "")]
        for _ in range(3):
            result = coordinator._merge_round_robin_batteries(INV, pair)
        assert set(result) == {f"{INV}-01", f"{INV}-02"}

        # Slot 0's serial arrives (shifted to fresh virtual slot 2); slot 1's
        # battery is still serial-less and re-served from the accumulator.
        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(2, BAT_SN_1), _transport_battery(1, "")]
        )

        assert set(result) == {f"{INV}-{BAT_SN_1}", f"{INV}-02"}
        assert coordinator._battery_fallback_keys[INV] == {f"{INV}-02"}
        assert set(coordinator._battery_noserial_polls[INV]) == {1}

    async def test_shifted_placeholder_serial_keeps_claimed_key(
        self, hass, mock_config_entry
    ):
        """Placeholder serial claiming the exposed key at a shifted index.

        'Battery_ID_01' canonically collapses to {INV}-01 — the very key the
        integration exposed for the pre-serial reads.  The sweep must clear
        the exposure record without deleting the mapping the serial now owns.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        no_serial = [_transport_battery(0, "")]
        for _ in range(3):
            coordinator._merge_round_robin_batteries(INV, no_serial)

        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(1, "Battery_ID_01")]
        )

        assert set(result) == {f"{INV}-01"}
        assert coordinator._battery_fallback_keys[INV] == set()
        assert coordinator._battery_noserial_polls[INV] == {}

    async def test_shifted_retirement_unblocks_registry_migration(
        self, hass, mock_config_entry
    ):
        """The #252 migration fires despite the shift.

        Pre-fix, the un-retired positional key stayed in the rr-cache and its
        stale counter in active_keys, permanently skipping the one-shot
        legacy→canonical registry rename.
        """
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        no_serial = [_transport_battery(0, "")]
        for _ in range(3):
            coordinator._merge_round_robin_batteries(INV, no_serial)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(1, BAT_SN_1)])

        entity_registry = er.async_get(hass)
        for entity_id in entity_ids:
            entry_ = entity_registry.async_get(entity_id)
            assert entry_ is not None
            assert new_key in entry_.unique_id
        device_registry = dr.async_get(hass)
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None
        assert device_registry.async_get_device({(DOMAIN, new_key)}) is not None

    async def test_shift_retirement_log_is_one_shot_per_key(
        self, hass, mock_config_entry, caplog
    ):
        """A key already announced retires at DEBUG, not INFO (no log spam)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        # Simulate an earlier announcement of this key (flapping serial).
        coordinator._battery_shift_retire_logged.add(f"{INV}-01")

        no_serial = [_transport_battery(0, "")]
        for _ in range(3):
            coordinator._merge_round_robin_batteries(INV, no_serial)
        with caplog.at_level(logging.INFO):
            result = coordinator._merge_round_robin_batteries(
                INV, [_transport_battery(1, BAT_SN_1)]
            )

        # Retirement itself still happens...
        assert set(result) == {f"{INV}-{BAT_SN_1}"}
        # ...but without a second INFO record.
        assert not [
            record
            for record in caplog.records
            if record.levelno == logging.INFO
            and "retired stale positional battery fallback" in record.getMessage()
        ]

    async def test_ghost_read_sibling_keeps_debounce_counter(
        self, hass, mock_config_entry
    ):
        """A ghost-read sibling slot keeps its debounce progress.

        The counter sweep only pops slots the transport did not serve AT ALL
        (upstream reservation holes).  A sibling served as a ghost this poll
        (voltage=0, soc=0 — skipped before the counter increment) must not
        have its pending debounce reset by an unrelated serial arrival.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        pair = [_transport_battery(0, ""), _transport_battery(1, "")]
        for _ in range(2):  # both pending: counters {0: 2, 1: 2}
            coordinator._merge_round_robin_batteries(INV, pair)
        assert coordinator._battery_noserial_polls[INV] == {0: 2, 1: 2}

        # Slot 0's serial arrives (shifted to virtual slot 2, hole at 0);
        # slot 1's battery reads ghost this poll but IS served.
        ghost = BatteryData(battery_index=1, serial_number="", voltage=0.0, soc=0)
        coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(2, BAT_SN_1), ghost]
        )

        # Reconciled hole's stale counter popped; ghost sibling's retained.
        assert coordinator._battery_noserial_polls[INV] == {1: 2}


# ── Rotation trust guard (third review, LOCAL only) ───────────────────


class TestRotationTrustGuard:
    """Rotating packs must not have positional history renamed blindly."""

    async def test_reported_count_over_page_skips_migration(
        self, hass, mock_config_entry
    ):
        """reg-96 count > 4 slots ⇒ LOCAL migration suppressed, rows orphaned."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, BAT_SN_1)], reported_count=8
        )

        # Live data still keyed canonically...
        assert set(result) == {f"{INV}-{BAT_SN_1}"}
        # ...but the positional registry rows are untouched (orphans).
        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert old_key in entry_.unique_id
        assert INV in coordinator._battery_migration_suppressed

    async def test_more_serials_than_slots_skips_migration(
        self, hass, mock_config_entry
    ):
        """>4 accumulated distinct serials ⇒ rotation ⇒ suppression (sticky)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        serials = [f"02920011223{i}" for i in range(4)]
        coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(i, sn) for i, sn in enumerate(serials)]
        )
        assert INV not in coordinator._battery_migration_suppressed

        # 5th serial rotates into slot 0 → rotation detected.
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, f"{INV}-05", sensor_suffixes=("battery_soc",)
        )
        coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, "029200112239")]
        )

        assert INV in coordinator._battery_migration_suppressed
        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert f"{INV}-05" in entry_.unique_id

    async def test_four_or_fewer_batteries_still_migrate(self, hass, mock_config_entry):
        """The common ≤4-battery case keeps migrating (reg-96 agrees)."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, BAT_SN_1)], reported_count=1
        )

        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert new_key in entry_.unique_id


# ── Duplicate battery identity (third review P1) ──────────────────────


class TestDuplicateSerialCollision:
    """Two batteries resolving to one canonical key must not merge silently."""

    async def test_local_duplicate_serial_disambiguated_and_suppressed(
        self, hass, mock_config_entry, caplog
    ):
        """Same serial in two slots: positional disambiguation + no migration."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        result = coordinator._merge_round_robin_batteries(
            INV,
            [_transport_battery(0, BAT_SN_1), _transport_battery(1, BAT_SN_1)],
        )

        # Both batteries visible: canonical + positional disambiguation.
        assert f"{INV}-{BAT_SN_1}" in result
        assert f"{INV}-02" in result
        # Migration suppressed for the inverter; registry untouched.
        assert INV in coordinator._battery_migration_suppressed
        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert old_key in entry_.unique_id
        assert "resolve to battery identity" in caplog.text

    async def test_register_drops_colliding_target_pairs(
        self, hass, mock_config_entry, caplog
    ):
        """Two legacy keys mapping to one canonical target are dropped."""
        mock_config_entry.add_to_hass(hass)
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, f"{INV}-01", sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._register_battery_key_migrations(
            INV,
            {f"{INV}-01": f"{INV}-{BAT_SN_1}", f"{INV}-02": f"{INV}-{BAT_SN_1}"},
            active_keys=set(),
        )

        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert f"{INV}-01" in entry_.unique_id
        assert "resolve to the same canonical key" in caplog.text


# ── Done-guard exception safety (third review P1) ─────────────────────


class TestMigrationGuardExceptionSafety:
    """Keys are marked done only after their registry ops succeed."""

    async def test_failed_key_not_marked_done_and_retries(
        self, hass, mock_config_entry
    ):
        """A registry exception leaves the key retryable; retry succeeds."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        pairs = {old_key: new_key}

        with patch.object(
            er.EntityRegistry,
            "async_update_entity",
            side_effect=RuntimeError("registry exploded"),
        ):
            coordinator._register_battery_key_migrations(INV, pairs, set())

        # Not marked done — the failure is retryable.
        assert (INV, old_key) not in coordinator._battery_key_migrations_done
        entity_registry = er.async_get(hass)
        assert old_key in entity_registry.async_get(entity_ids[0]).unique_id

        # Retry without the fault: migration completes and is marked done.
        coordinator._register_battery_key_migrations(INV, pairs, set())
        assert (INV, old_key) in coordinator._battery_key_migrations_done
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert new_key in entry_.unique_id

    async def test_one_failing_key_does_not_block_others(self, hass, mock_config_entry):
        """Per-key containment: other keys still migrate when one fails."""
        mock_config_entry.add_to_hass(hass)
        _, ids_1 = _seed_positional_battery(
            hass, mock_config_entry, f"{INV}-01", sensor_suffixes=("battery_soc",)
        )
        _, ids_2 = _seed_positional_battery(
            hass, mock_config_entry, f"{INV}-02", sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        entity_registry = er.async_get(hass)
        real_update = er.EntityRegistry.async_update_entity

        def _fail_key_one(self, entity_id, **kwargs):
            if entity_id in ids_1:
                raise RuntimeError("registry exploded")
            return real_update(self, entity_id, **kwargs)

        with patch.object(er.EntityRegistry, "async_update_entity", _fail_key_one):
            coordinator._register_battery_key_migrations(
                INV,
                {
                    f"{INV}-01": f"{INV}-{BAT_SN_1}",
                    f"{INV}-02": f"{INV}-{BAT_SN_2}",
                },
                set(),
            )

        # Key 2 migrated and is done; key 1 failed and is retryable.
        assert (INV, f"{INV}-02") in coordinator._battery_key_migrations_done
        assert (INV, f"{INV}-01") not in coordinator._battery_key_migrations_done
        assert f"{INV}-{BAT_SN_2}" in entity_registry.async_get(ids_2[0]).unique_id
        assert f"{INV}-01" in entity_registry.async_get(ids_1[0]).unique_id

    async def test_live_entity_defers_migration(self, hass, mock_config_entry):
        """A live positional entity defers the key instead of stranding it."""
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )
        # Simulate an instantiated entity: a state exists for the entity_id.
        hass.states.async_set(entity_ids[0], "85")

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._merge_round_robin_batteries(INV, [_transport_battery(0, BAT_SN_1)])

        # Deferred: registry untouched, key NOT marked done (retry later).
        entity_registry = er.async_get(hass)
        entry_ = entity_registry.async_get(entity_ids[0])
        assert entry_ is not None
        assert old_key in entry_.unique_id
        assert (INV, old_key) not in coordinator._battery_key_migrations_done


# ── batteryKey/batterySn divergence warning (third review P1) ─────────


class TestBatteryKeyDivergenceWarning:
    """A batteryKey that deviates from {inv}_{batterySn} must be surfaced."""

    @pytest.fixture(autouse=True)
    def _clear_warned(self):
        from custom_components.eg4_web_monitor import utils

        utils._battery_key_divergence_warned.clear()
        yield
        utils._battery_key_divergence_warned.clear()

    def test_warns_once_on_divergence(self, caplog):
        batt = SimpleNamespace(
            battery_key="SOMETHING_ELSE_ENTIRELY",
            battery_sn=BAT_SN_1,
            battery_index=0,
        )
        key = cloud_battery_key(INV, batt)
        # batteryKey precedence is kept (CLOUD ids stay 3.3.0-identical)...
        assert key == "SOMETHING-ELSE-ENTIRELY"
        # ...but the invariant violation is surfaced.
        assert "deviates" in caplog.text
        caplog.clear()
        cloud_battery_key(INV, batt)
        assert "deviates" not in caplog.text  # one-shot

    def test_no_warning_on_placeholder_pack(self, caplog):
        batt = SimpleNamespace(
            battery_key=f"{INV}_Battery_ID_01",
            battery_sn="Battery_ID_01",
            battery_index=0,
        )
        assert cloud_battery_key(INV, batt) == f"{INV}-01"
        assert "deviates" not in caplog.text

    def test_no_warning_when_consistent(self, caplog):
        batt = _cloud_battery(0, BAT_SN_1)
        assert cloud_battery_key(INV, batt) == f"{INV}-{BAT_SN_1}"
        assert "deviates" not in caplog.text


# ── Full-setup ordering invariant (migration before instantiation) ────


class TestSetupOrderingInvariant:
    """End-to-end: migration fires before battery entities instantiate.

    Pre-seeds positional registry rows, runs REAL config-entry setup
    (async_config_entry_first_refresh → async_forward_entry_setups → the
    sensor.py late-battery listener), then lets batteries appear on a later
    refresh.  The seeded rows must be renamed BEFORE the listener creates the
    battery entity objects, so the objects adopt the renamed rows: zero
    duplicate battery devices/entities, entity_ids preserved.
    """

    async def test_full_setup_migrates_before_battery_entities_instantiate(
        self, hass, mock_config_entry
    ):
        from custom_components.eg4_web_monitor.const import DOMAIN as EG4_DOMAIN

        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        # Suffixes must be sensor keys the real pipeline emits so the late
        # listener instantiates entities that adopt the renamed rows.
        seeded_device_id, entity_ids = _seed_positional_battery(
            hass,
            mock_config_entry,
            old_key,
            sensor_suffixes=("battery_rsoc", "battery_real_voltage"),
        )
        seeded_sensor_id = entity_ids[0]

        inv = make_real_inverter(serial_number=INV, model="LXP-LB-US 10K")
        inv._battery_bank = None  # no batteries at first refresh (cold start)
        station = _mock_station([inv])
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator.LuxpowerClient"
            ) as mock_client_cls,
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch(
                "custom_components.eg4_web_monitor.coordinator_http.Station.load",
                new=AsyncMock(return_value=station),
            ),
            patch.object(
                EG4DataUpdateCoordinator,
                "_process_inverter_object",
                new=AsyncMock(
                    return_value={
                        "type": "inverter",
                        "model": "LXP-LB-US 10K",
                        "serial": INV,
                        "sensors": {},
                        "batteries": {},
                    }
                ),
            ),
            patch.object(
                EG4DataUpdateCoordinator,
                "_refresh_missing_parameters",
                new=AsyncMock(),
            ),
        ):
            mock_client_cls.return_value.close = AsyncMock()

            # Phase A: full real setup, batteries not yet known.
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            entity_registry = er.async_get(hass)
            # Positional rows untouched (no serials known yet), no battery
            # entity objects instantiated.
            assert old_key in entity_registry.async_get(seeded_sensor_id).unique_id
            assert hass.states.get(seeded_sensor_id) is None

            # Phase B: batteries appear on a later refresh (serials known).
            bank = MagicMock()
            bank.batteries = [_cloud_battery(0, BAT_SN_1)]
            bank.battery_count = 1
            inv._battery_bank = bank

            coordinator = mock_config_entry.runtime_data
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            # Rows renamed in place: same entity_ids, canonical unique_ids.
            for entity_id in entity_ids:
                entry_ = entity_registry.async_get(entity_id)
                assert entry_ is not None, f"{entity_id} vanished"
                assert new_key in entry_.unique_id
                assert old_key not in entry_.unique_id

            # The listener-created entity objects ADOPTED the renamed rows —
            # the seeded entity_id is now a live state (ordering invariant).
            assert hass.states.get(seeded_sensor_id) is not None

            # Zero duplicates: exactly one entity owns the canonical soc
            # unique_id and it is the seeded row.
            soc_uid = f"{INV}_{new_key}_battery_rsoc"
            assert (
                entity_registry.async_get_entity_id("sensor", EG4_DOMAIN, soc_uid)
                == seeded_sensor_id
            )
            positional_uid = f"{INV}_{old_key}_battery_rsoc"
            assert (
                entity_registry.async_get_entity_id(
                    "sensor", EG4_DOMAIN, positional_uid
                )
                is None
            )

            # Exactly one battery device: the seeded one, re-identified.
            device_registry = dr.async_get(hass)
            assert device_registry.async_get_device({(EG4_DOMAIN, old_key)}) is None
            new_device = device_registry.async_get_device({(EG4_DOMAIN, new_key)})
            assert new_device is not None
            assert new_device.id == seeded_device_id

            await hass.config_entries.async_unload(mock_config_entry.entry_id)
            await hass.async_block_till_done()
