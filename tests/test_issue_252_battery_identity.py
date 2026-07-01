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

    async def test_local_no_serial_fallback_unchanged(self, hass, mock_config_entry):
        """Packs without CAN serials keep positional keys (pre-#165 firmware)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        result = coordinator._merge_round_robin_batteries(
            INV, [_transport_battery(0, ""), _transport_battery(1, "")]
        )

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
        """Pure-LOCAL beta install: unique_ids renamed in place, history kept."""
        mock_config_entry.add_to_hass(hass)
        area = ar.async_get(hass).async_create("Casa de Maquinas")
        old_key = f"{INV}-01"
        new_key = f"{INV}-{BAT_SN_1}"
        _, entity_ids = _seed_positional_battery(
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

        # Old positional device is gone; canonical device carries the area.
        device_registry = dr.async_get(hass)
        assert device_registry.async_get_device({(DOMAIN, old_key)}) is None
        new_device = device_registry.async_get_device({(DOMAIN, new_key)})
        assert new_device is not None
        assert new_device.area_id == area.id
        # Migrated entities point at the canonical device.
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

        Mixed pack: slot 0 has no serial (fallback key {inv}-01), slot 1 has a
        real serial whose legacy shadow key is ALSO {inv}-01.  Migrating would
        steal the live battery's entities — it must be skipped.
        """
        mock_config_entry.add_to_hass(hass)
        old_key = f"{INV}-01"
        _, entity_ids = _seed_positional_battery(
            hass, mock_config_entry, old_key, sensor_suffixes=("battery_soc",)
        )

        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        result = coordinator._merge_round_robin_batteries(
            INV,
            [_transport_battery(0, ""), _transport_battery(1, BAT_SN_1)],
        )

        # Fallback key is active for the no-serial battery.
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
