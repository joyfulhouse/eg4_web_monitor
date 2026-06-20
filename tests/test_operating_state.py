"""Tests for the inverter Operating State sensor + Off-Grid binary sensor (#262).

The operating-mode code (INPUT reg 0 ``device_status`` / cloud ``status``,
surfaced as ``status_code``) is decoded into a friendly ``operating_state`` enum
sensor and an ``off_grid`` binary sensor. The decode is shared so LOCAL, CLOUD
and HYBRID produce identical values. Codes follow EG4 "Table 9".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.binary_sensor import (
    EG4OffGridBinarySensor,
    async_setup_entry,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DIAGNOSTIC_DEVICE_SENSOR_KEYS,
    DOMAIN,
    OFF_GRID_STATUS_CODES,
    OPERATING_STATE_LABELS,
    OPERATING_STATE_OPTIONS,
    SENSOR_TYPES,
    is_off_grid,
    operating_state_slug,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    GRIDBOSS_SENSOR_KEYS,
    INVERTER_RUNTIME_KEYS,
    PARALLEL_GROUP_SENSOR_KEYS,
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor
from pylxpweb.transports.data import InverterRuntimeData

from tests.conftest import make_real_inverter, make_transport_spec

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Code -> expected slug, straight from Table 9 (the documented set, #262).
EXPECTED_DECODE: dict[int, str] = {
    0x00: "standby",
    0x01: "fault",
    0x02: "programming",
    0x04: "pv_to_grid",
    0x08: "pv_charging",
    0x0C: "pv_charging_to_grid",
    0x10: "battery_to_grid",
    0x14: "pv_battery_to_grid",
    0x20: "ac_charging",
    0x28: "pv_ac_charging",
    0x40: "off_grid_battery",
    0x60: "ac_coupled_charging",
    0x80: "pv_off_grid",
    0x88: "pv_charging_off_grid",
    0xC0: "pv_battery_off_grid",
}


# ── Decode helpers (pure) ────────────────────────────────────────────


class TestOperatingStateDecode:
    """operating_state_slug / is_off_grid / module constants."""

    @pytest.mark.parametrize(("code", "slug"), sorted(EXPECTED_DECODE.items()))
    def test_documented_codes_map_to_slug(self, code: int, slug: str):
        """Every Table 9 code decodes to its stable slug."""
        assert operating_state_slug(code) == slug

    def test_module_table_matches_expected(self):
        """The shipped table is exactly the documented Table 9 set."""
        assert OPERATING_STATE_LABELS == EXPECTED_DECODE

    def test_unknown_code_returns_none(self):
        """An unmapped code yields None (rendered 'unknown'), never raises."""
        assert operating_state_slug(0x99) is None
        assert operating_state_slug(255) is None

    def test_none_returns_none(self):
        """A missing value (offline inverter) yields None."""
        assert operating_state_slug(None) is None

    def test_options_are_unique_and_complete(self):
        """Enum options list every slug once, in code order."""
        assert OPERATING_STATE_OPTIONS == list(EXPECTED_DECODE.values())
        assert len(OPERATING_STATE_OPTIONS) == len(set(OPERATING_STATE_OPTIONS))

    def test_off_grid_code_set_is_exact(self):
        """Off-grid set is the islanded codes only (0x60 AC-coupled excluded)."""
        assert OFF_GRID_STATUS_CODES == frozenset({0x40, 0x80, 0x88, 0xC0})

    @pytest.mark.parametrize("code", sorted(OFF_GRID_STATUS_CODES))
    def test_is_off_grid_true(self, code: int):
        """Islanded codes report off-grid."""
        assert is_off_grid(code) is True

    @pytest.mark.parametrize("code", [0x00, 0x04, 0x10, 0x20, 0x28, 0x60])
    def test_is_off_grid_false(self, code: int):
        """On-grid codes (incl. 0x60 AC-coupled) report not off-grid."""
        assert is_off_grid(code) is False

    def test_is_off_grid_none(self):
        """Missing value -> None (binary sensor reads 'unknown', not 'off')."""
        assert is_off_grid(None) is None

    def test_off_grid_codes_are_all_known(self):
        """Every off-grid code is also a decodable operating-state slug."""
        assert OFF_GRID_STATUS_CODES <= set(OPERATING_STATE_LABELS)


# ── Sensor type definition ───────────────────────────────────────────


class TestOperatingStateSensorDefinition:
    """SENSOR_TYPES entry for operating_state + status_text rename."""

    def test_enum_with_translated_options(self):
        """Enum device class, slug options, and a translation key for states."""
        config = SENSOR_TYPES["operating_state"]
        assert config["device_class"] == "enum"
        assert config["options"] == OPERATING_STATE_OPTIONS
        assert config["translation_key"] == "operating_state"

    def test_primary_entity_not_diagnostic(self):
        """Operating State is a primary entity (prominent), not diagnostic."""
        assert "entity_category" not in SENSOR_TYPES["operating_state"]
        assert "operating_state" not in DIAGNOSTIC_DEVICE_SENSOR_KEYS

    def test_enum_has_no_unit_or_state_class(self):
        """Enum sensors must not carry a unit or state_class."""
        config = SENSOR_TYPES["operating_state"]
        assert "unit" not in config
        assert "state_class" not in config

    def test_status_text_renamed_to_cloud_status(self):
        """The cloud health string is renamed to disambiguate (#262)."""
        assert SENSOR_TYPES["status_text"]["name"] == "Cloud Status"


class TestOperatingStateSensorEntity:
    """Entity-level naming: translation_key drives a localizable name."""

    @staticmethod
    def _coordinator(serial: str = "1234567890", model: str = "FlexBOSS21"):
        coordinator = MagicMock()
        coordinator.last_update_success = True
        coordinator.data = {"devices": {serial: {"model": model, "sensors": {}}}}
        return coordinator

    def test_name_resolves_from_translation_not_attr_name(self):
        """operating_state leaves _attr_name unset so the name localizes."""
        entity = EG4InverterSensor(
            self._coordinator(), "1234567890", "operating_state", "inverter"
        )
        assert entity._attr_translation_key == "operating_state"
        assert entity._attr_options == OPERATING_STATE_OPTIONS
        # No hardcoded _attr_name -> HA uses entity.sensor.operating_state.name
        assert getattr(entity, "_attr_name", None) is None

    def test_normal_sensor_still_uses_attr_name(self):
        """A sensor without translation_key keeps its hardcoded _attr_name."""
        entity = EG4InverterSensor(
            self._coordinator(), "1234567890", "status_code", "inverter"
        )
        assert entity._attr_name == "Status Code"
        assert getattr(entity, "_attr_translation_key", None) is None


# ── LOCAL path ───────────────────────────────────────────────────────


class TestOperatingStateLocalMapping:
    """LOCAL runtime table derives operating_state from device_status."""

    def test_runtime_mapping_decodes(self):
        """status_code passes through raw; operating_state is its slug."""
        mapping = _build_runtime_sensor_mapping(InverterRuntimeData(device_status=0x10))
        assert mapping["status_code"] == 0x10
        assert mapping["operating_state"] == "battery_to_grid"

    def test_off_grid_code_decodes(self):
        """An off-grid code decodes to the off-grid slug."""
        mapping = _build_runtime_sensor_mapping(InverterRuntimeData(device_status=0x40))
        assert mapping["operating_state"] == "off_grid_battery"

    def test_unknown_code_yields_none_state(self):
        """Unknown code -> operating_state None, raw status_code preserved."""
        mapping = _build_runtime_sensor_mapping(InverterRuntimeData(device_status=0x99))
        assert mapping["status_code"] == 0x99
        assert mapping["operating_state"] is None

    def test_missing_status_yields_none(self):
        """No device_status (offline) -> operating_state None."""
        mapping = _build_runtime_sensor_mapping(InverterRuntimeData())
        assert mapping["operating_state"] is None

    def test_key_in_static_entity_sets(self):
        """operating_state is part of the LOCAL static entity surface."""
        assert "operating_state" in INVERTER_RUNTIME_KEYS
        assert "operating_state" in ALL_INVERTER_SENSOR_KEYS

    def test_inverter_scoped_only(self):
        """operating_state is an inverter sensor, not GridBOSS / group."""
        assert "operating_state" not in GRIDBOSS_SENSOR_KEYS
        assert "operating_state" not in PARALLEL_GROUP_SENSOR_KEYS


# ── CLOUD / HYBRID path ──────────────────────────────────────────────


@pytest.fixture
def mock_config_entry():
    """Minimal cloud config entry for coordinator construction."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="operating_state_test",
    )


class TestOperatingStateCloudHybrid:
    """The cloud/hybrid object path derives operating_state from status."""

    async def test_process_inverter_object_derives_state(self, hass, mock_config_entry):
        """_process_inverter_object decodes status_code -> operating_state."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(device_status=0x40, pv_total_power=1500)
        inverter = make_real_inverter("1111111111", "FlexBOSS21", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["status_code"] == 0x40
        assert sensors["operating_state"] == "off_grid_battery"

    async def test_no_runtime_data_still_publishes_operating_state_key(
        self, hass, mock_config_entry
    ):
        """has_data=False (no runtime) path must still CREATE operating_state.

        An inverter with no runtime data takes the early-return path in
        _process_inverter_object. The key must be present (value None ->
        "unknown") so the primary Operating State entity is created in
        CLOUD/HYBRID too, not silently dropped (issue #262; #256 philosophy).
        Asserting key membership, not just .get() is None, guards the regression.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # No runtime/energy -> inverter.has_data is False -> early return.
        inverter = make_real_inverter("2222222222", "FlexBOSS21")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()
        assert inverter.has_data is False  # precondition: early-return path

        result = await coordinator._process_inverter_object(inverter)
        assert "operating_state" in result["sensors"]
        assert result["sensors"]["operating_state"] is None


# ── Off-Grid binary sensor ───────────────────────────────────────────


def _coordinator_with_status(serial: str, status_code: object) -> MagicMock:
    """Build a mock coordinator exposing one inverter's status_code."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    sensors = {} if status_code is None else {"status_code": status_code}
    coordinator.data = {
        "devices": {serial: {"sensors": sensors, "model": "FlexBOSS21"}}
    }
    return coordinator


class TestOffGridBinarySensor:
    """EG4OffGridBinarySensor.is_on tracks the off-grid code set."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (0x40, True),
            (0x80, True),
            (0x88, True),
            (0xC0, True),
            (0x00, False),
            (0x10, False),
            (0x20, False),
            (0x60, False),
            (None, None),
        ],
    )
    def test_is_on(self, code, expected):
        """on for islanded codes, off for grid-tied, None when unknown."""
        serial = "1234567890"
        coordinator = _coordinator_with_status(serial, code)
        entity = EG4OffGridBinarySensor(coordinator, serial, {"model": "FlexBOSS21"})
        assert entity.is_on is expected

    def test_unique_id_and_entity_id(self):
        """IDs follow the integration's serial/model conventions."""
        serial = "1234567890"
        coordinator = _coordinator_with_status(serial, 0x00)
        entity = EG4OffGridBinarySensor(coordinator, serial, {"model": "FlexBOSS21"})
        assert entity.unique_id == f"{serial}_off_grid"
        # _attr_entity_id is the integration's set value (HA assigns the real
        # entity_id at platform-add time), matching the convention used by
        # other EG4 platforms' tests.
        assert entity._attr_entity_id == (
            f"binary_sensor.eg4_flexboss21_{serial}_off_grid"
        )
        assert entity.translation_key == "off_grid"

    def test_unavailable_when_device_missing(self):
        """available is False when the device is absent from coordinator data."""
        coordinator = _coordinator_with_status("1234567890", 0x40)
        entity = EG4OffGridBinarySensor(
            coordinator, "9999999999", {"model": "FlexBOSS21"}
        )
        assert entity.available is False

    async def test_setup_creates_for_inverter_only(self):
        """async_setup_entry creates one off-grid sensor per inverter only."""
        coordinator = MagicMock()
        coordinator.last_update_success = True
        coordinator.data = {
            "devices": {
                "1111111111": {"type": "inverter", "model": "FlexBOSS21"},
                "2222222222": {"type": "gridboss", "model": "GridBOSS"},
                "BAT1": {"type": "battery", "model": "EG4-LL"},
            }
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        created: list[EG4OffGridBinarySensor] = []
        await async_setup_entry(
            MagicMock(), entry, lambda entities: created.extend(entities)
        )

        assert len(created) == 1
        assert isinstance(created[0], EG4OffGridBinarySensor)
        assert created[0].unique_id == "1111111111_off_grid"


# ── Translations ─────────────────────────────────────────────────────


class TestOperatingStateTranslations:
    """strings.json and every locale carry the new keys."""

    def _translation_files(self) -> list[Path]:
        base = _REPO_ROOT / "custom_components" / "eg4_web_monitor"
        return [base / "strings.json", *sorted((base / "translations").glob("*.json"))]

    def test_operating_state_states_present_everywhere(self):
        """Every locale defines the operating_state name and all 15 states."""
        for path in self._translation_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = data["entity"]["sensor"]["operating_state"]
            assert entry["name"], f"operating_state name empty in {path.name}"
            states = entry["state"]
            for slug in OPERATING_STATE_OPTIONS:
                assert slug in states, f"{slug} missing from {path.name}"
                assert states[slug], f"{slug} empty in {path.name}"

    def test_off_grid_binary_present_everywhere(self):
        """Every locale defines the off_grid binary sensor name."""
        for path in self._translation_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = data["entity"]["binary_sensor"]["off_grid"]
            assert entry["name"], f"off_grid name empty in {path.name}"
