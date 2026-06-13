"""Tests for inverter fault_code / warning_code diagnostic sensors (eg4-23a6).

Input regs 60-61 / 62-63 are 32-bit fault/warning bitfields.  pylxpweb merges
the BMS codes (regs 99/100) in as a fallback when the inverter code reads 0
and carries the combined value on ``InverterRuntimeData.fault_code`` /
``warning_code``.  The cloud ``getInverterRuntime`` response has NO
faultCode/warningCode field (canonical table ``cloud_api_field=None``), so
the sensors are LOCAL/HYBRID-only:

* LOCAL — ``_build_runtime_sensor_mapping`` raw passthrough,
* HYBRID — ``_TRANSPORT_OVERLAY`` from the attached local transport,
* pure CLOUD — the keys are correctly absent (no data source exists).

State is the raw numeric code (0 = no fault/warning); pylxpweb's decoded
``fault_messages``/``warning_messages`` are deliberately not surfaced.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    SENSOR_TYPES,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    GRIDBOSS_SENSOR_KEYS,
    INVERTER_RUNTIME_KEYS,
    PARALLEL_GROUP_SENSOR_KEYS,
    _build_gridboss_sensor_mapping,
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.coordinator_mixins import (
    _TRANSPORT_OVERLAY,
    DeviceProcessingMixin,
)
from custom_components.eg4_web_monitor.sensor import (
    EG4InverterSensor,
    _create_inverter_sensors,
)
from pylxpweb.transports.data import InverterRuntimeData, MidboxRuntimeData

from tests.conftest import make_real_inverter, make_real_mid, make_transport_spec

CODE_KEYS = ("fault_code", "warning_code")

# Repository root (tests/ lives one level below it).
_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mock_config_entry():
    """Create a mock cloud config entry."""
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
        entry_id="fault_warning_test",
    )


# ── Sensor type definitions ──────────────────────────────────────────


class TestFaultWarningSensorDefinitions:
    """SENSOR_TYPES entries follow the diagnostic raw-code convention."""

    def test_defined_as_diagnostic(self):
        """Both codes are diagnostic sensors with the alert icon family."""
        for key in CODE_KEYS:
            assert key in SENSOR_TYPES, f"{key} missing from SENSOR_TYPES"
            assert SENSOR_TYPES[key]["entity_category"] == "diagnostic"
        # Icon convention mirrors the battery fault/warning status sensors.
        assert SENSOR_TYPES["fault_code"]["icon"] == "mdi:alert-circle"
        assert SENSOR_TYPES["warning_code"]["icon"] == "mdi:alert"

    def test_raw_code_state_has_no_unit_or_classes(self):
        """Raw bitfield codes: no unit, device_class or state_class.

        A state_class would feed 32-bit bitfields into long-term statistics
        as if they were measurements.
        """
        for key in CODE_KEYS:
            config = SENSOR_TYPES[key]
            assert "unit" not in config
            assert "device_class" not in config
            assert "state_class" not in config

    def test_translations_present(self):
        """strings.json and every locale carry the entity.sensor entries."""
        base = _REPO_ROOT / "custom_components" / "eg4_web_monitor"
        files = [base / "strings.json", *sorted((base / "translations").glob("*.json"))]
        assert len(files) >= 2  # strings.json + at least en.json
        for path in files:
            sensors = json.loads(path.read_text(encoding="utf-8"))["entity"]["sensor"]
            for key in CODE_KEYS:
                assert key in sensors, f"{key} missing from {path.name}"
                assert sensors[key]["name"], f"{key} name empty in {path.name}"


# ── LOCAL path ───────────────────────────────────────────────────────


class TestFaultWarningLocalMapping:
    """LOCAL runtime table feeds the codes verbatim from the dataclass."""

    def test_runtime_mapping_raw_passthrough(self):
        """fault_code/warning_code pass through unscaled from regs 60-63."""
        runtime = InverterRuntimeData(fault_code=0x0004_0001, warning_code=0x0000_0102)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["fault_code"] == 0x0004_0001
        assert mapping["warning_code"] == 0x0000_0102

    def test_zero_codes_are_preserved(self):
        """0 means 'no fault/warning' and must be published, not dropped."""
        mapping = _build_runtime_sensor_mapping(
            InverterRuntimeData(fault_code=0, warning_code=0)
        )
        assert mapping["fault_code"] == 0
        assert mapping["warning_code"] == 0

    def test_keys_in_static_entity_sets(self):
        """Keys are part of the LOCAL static entity creation surface."""
        for key in CODE_KEYS:
            assert key in INVERTER_RUNTIME_KEYS
            assert key in ALL_INVERTER_SENSOR_KEYS

    def test_inverter_scoped_only(self):
        """Codes are inverter sensors — not GridBOSS, not parallel group."""
        for key in CODE_KEYS:
            assert key not in GRIDBOSS_SENSOR_KEYS
            assert key not in PARALLEL_GROUP_SENSOR_KEYS
        gridboss_mapping = _build_gridboss_sensor_mapping(
            make_real_mid(runtime=MidboxRuntimeData())
        )
        for key in CODE_KEYS:
            assert key not in gridboss_mapping


# ── HYBRID / CLOUD paths ─────────────────────────────────────────────


class TestFaultWarningHybridOverlay:
    """HYBRID overlays the local registers; pure CLOUD has no source."""

    def test_transport_overlay_pairs_present(self):
        """_TRANSPORT_OVERLAY carries both (sensor_key, dataclass attr) pairs."""
        assert ("fault_code", "fault_code") in _TRANSPORT_OVERLAY
        assert ("warning_code", "warning_code") in _TRANSPORT_OVERLAY

    def test_cloud_property_map_excludes_codes(self):
        """The cloud property map must NOT feed the codes.

        getInverterRuntime carries no faultCode/warningCode field, so a
        property-map entry would publish None forever in pure CLOUD; the
        keys flow exclusively through the LOCAL table + HYBRID overlay
        (same pattern as bt_temperature / load_power).
        """
        cloud_keys = set(DeviceProcessingMixin._get_inverter_property_map().values())
        for key in CODE_KEYS:
            assert key not in cloud_keys

    async def test_transport_runtime_overlays_codes(self, hass, mock_config_entry):
        """HYBRID: codes from the attached transport overlay into sensors."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(
            fault_code=0x0000_0010,
            warning_code=0x0000_0001,
            pv_total_power=1500,
        )
        inverter = make_real_inverter("1111111111", "FlexBOSS21", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["fault_code"] == 0x0000_0010
        assert sensors["warning_code"] == 0x0000_0001

    async def test_transport_runtime_overlays_zero_codes(self, hass, mock_config_entry):
        """HYBRID: 0 (no fault/warning) is a real state and overlays too."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(fault_code=0, warning_code=0)
        inverter = make_real_inverter("1111111111", "FlexBOSS21", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["fault_code"] == 0
        assert sensors["warning_code"] == 0


# ── Entity creation (test_sensor_entities.py pattern) ────────────────


class TestFaultWarningEntityCreation:
    """Sensor entities are created for the codes with diagnostic category."""

    @staticmethod
    def _mock_coordinator():
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        coordinator.plant_id = "plant_123"
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value=None)
        coordinator.data = {"devices": {}}
        # Off so these fault/warning tests don't pick up the Quick Charge
        # Remaining sensor (gated on cloud/local transport availability).
        coordinator.has_http_api = MagicMock(return_value=False)
        coordinator.has_configured_local_transport = MagicMock(return_value=False)
        return coordinator

    def test_entities_created_for_codes(self):
        """_create_inverter_sensors creates one entity per code key."""
        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"fault_code": 0, "warning_code": 0},
            "batteries": {},
        }
        inverter_entities, battery_entities = _create_inverter_sensors(
            self._mock_coordinator(), "INV001", device_data
        )
        assert len(inverter_entities) == 2
        assert len(battery_entities) == 0
        assert all(isinstance(e, EG4InverterSensor) for e in inverter_entities)

    def test_entities_are_diagnostic(self):
        """Created entities carry EntityCategory.DIAGNOSTIC."""
        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"fault_code": 0x10, "warning_code": 0x1},
            "batteries": {},
        }
        inverter_entities, _ = _create_inverter_sensors(
            self._mock_coordinator(), "INV001", device_data
        )
        assert len(inverter_entities) == 2
        for entity in inverter_entities:
            assert entity.entity_category is EntityCategory.DIAGNOSTIC

    def test_entities_created_without_feature_gating(self):
        """Codes are not phase/family gated — created for any feature set."""
        device_data = {
            "type": "inverter",
            "model": "12000XP",
            "sensors": {"fault_code": 0, "warning_code": 0},
            "features": {
                "supports_split_phase": False,
                "supports_three_phase": False,
            },
            "batteries": {},
        }
        inverter_entities, _ = _create_inverter_sensors(
            self._mock_coordinator(), "INV001", device_data
        )
        assert len(inverter_entities) == 2
