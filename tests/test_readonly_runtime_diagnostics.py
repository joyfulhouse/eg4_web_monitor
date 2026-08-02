"""Contracts for safe read-only diagnostics from canonical input registers."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.const import EntityCategory, UnitOfTime
import pytest
from pylxpweb.transports.data import InverterRuntimeData

from custom_components.eg4_web_monitor.const import SENSOR_TYPES
from custom_components.eg4_web_monitor.coordinator_mappings import (
    INVERTER_RUNTIME_KEYS,
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.sensor import (
    _create_inverter_sensors,
    _should_create_sensor,
)


COMMON_DIAGNOSTIC_KEYS = {
    "inverter_running_time",
    "ac_input_type",
    "parallel_role",
    "parallel_phase",
    "parallel_unit_number",
}
EPS_APPARENT_POWER_KEYS = {
    "eps_apparent_power",
    "eps_apparent_power_r",
}
DIAGNOSTIC_KEYS = COMMON_DIAGNOSTIC_KEYS | EPS_APPARENT_POWER_KEYS


def test_runtime_diagnostics_decode_canonical_fields_by_phase_context() -> None:
    """I25 is aggregate outside three-phase and explicitly R-phase within it."""
    runtime = InverterRuntimeData(
        eps_apparent_power=3456,
        inverter_on_time=86_400,
        ac_input_type=0b111,
        parallel_master_slave=1,
        parallel_phase=1,
        parallel_number=7,
    )

    non_three_phase = _build_runtime_sensor_mapping(runtime, supports_three_phase=False)
    three_phase = _build_runtime_sensor_mapping(runtime, supports_three_phase=True)
    unresolved = _build_runtime_sensor_mapping(runtime)

    assert non_three_phase["eps_apparent_power"] == 3456
    assert "eps_apparent_power_r" not in non_three_phase
    assert three_phase["eps_apparent_power_r"] == 3456
    assert "eps_apparent_power" not in three_phase
    assert not EPS_APPARENT_POWER_KEYS & unresolved.keys()

    assert non_three_phase["inverter_running_time"] == 86_400
    assert non_three_phase["ac_input_type"] == "generator"
    assert non_three_phase["parallel_role"] == "master"
    assert non_three_phase["parallel_phase"] == "s"
    assert non_three_phase["parallel_unit_number"] == 7
    assert DIAGNOSTIC_KEYS <= INVERTER_RUNTIME_KEYS


def test_runtime_diagnostics_keep_absence_and_standalone_semantics_honest() -> None:
    """Missing data stays unknown; standalone units have no phase/unit ID."""
    missing = _build_runtime_sensor_mapping(InverterRuntimeData())
    assert {key: missing[key] for key in COMMON_DIAGNOSTIC_KEYS} == dict.fromkeys(
        COMMON_DIAGNOSTIC_KEYS
    )
    assert not EPS_APPARENT_POWER_KEYS & missing.keys()

    standalone = _build_runtime_sensor_mapping(
        InverterRuntimeData(
            ac_input_type=0,
            parallel_master_slave=0,
            parallel_phase=0,
            parallel_number=0,
        ),
        supports_three_phase=False,
    )
    assert standalone["ac_input_type"] == "grid"
    assert standalone["parallel_role"] == "standalone"
    assert standalone["parallel_phase"] is None
    assert standalone["parallel_unit_number"] is None


def test_runtime_diagnostics_are_disabled_read_only_entities() -> None:
    """The extra register detail is diagnostic and opt-in, never writable."""
    for key, name in {
        "eps_apparent_power": "EPS Apparent Power",
        "eps_apparent_power_r": "EPS Apparent Power R",
    }.items():
        assert SENSOR_TYPES[key] == {
            "name": name,
            "unit": "VA",
            "device_class": "apparent_power",
            "state_class": "measurement",
            "icon": "mdi:power-plug-outline",
            "entity_category": "diagnostic",
            "enabled_default": False,
            "translation_key": key,
        }
    assert SENSOR_TYPES["inverter_running_time"] == {
        "name": "Inverter Running Time",
        "unit": UnitOfTime.SECONDS,
        "device_class": "duration",
        "state_class": "measurement",
        "icon": "mdi:timer-outline",
        "entity_category": "diagnostic",
        "enabled_default": False,
        "translation_key": "inverter_running_time",
    }
    for key, options in {
        "ac_input_type": ["grid", "generator"],
        "parallel_role": ["standalone", "master", "slave", "three_phase_master"],
        "parallel_phase": ["r", "s", "t"],
    }.items():
        config = SENSOR_TYPES[key]
        assert config["device_class"] == "enum"
        assert config["options"] == options
        assert config["entity_category"] == "diagnostic"
        assert config["enabled_default"] is False
        assert config["translation_key"] == key
        assert "state_class" not in config
        assert "unit" not in config

    number_config = SENSOR_TYPES["parallel_unit_number"]
    assert number_config["entity_category"] == "diagnostic"
    assert number_config["enabled_default"] is False
    assert number_config["translation_key"] == "parallel_unit_number"
    assert "state_class" not in number_config


@pytest.mark.parametrize(
    ("features", "expected_key"),
    [
        (
            {
                "inverter_family": "EG4_HYBRID",
                "grid_type": "split_phase",
                "supports_three_phase": False,
            },
            "eps_apparent_power",
        ),
        (
            {
                "inverter_family": "LXP",
                "grid_type": "three_phase",
                "supports_three_phase": True,
            },
            "eps_apparent_power_r",
        ),
        (
            {
                "inverter_family": "UNKNOWN",
                "grid_type": "unknown",
                "supports_three_phase": False,
            },
            None,
        ),
        (
            {
                "inverter_family": "UNKNOWN",
                "grid_type": "split_phase",
                "supports_three_phase": False,
            },
            "eps_apparent_power",
        ),
        (
            {
                "inverter_family": "UNKNOWN",
                "grid_type": "three_phase",
                "supports_three_phase": True,
            },
            "eps_apparent_power_r",
        ),
        ({}, None),
        (None, None),
    ],
)
def test_i25_entity_requires_known_phase_context(
    features: dict | None, expected_key: str | None
) -> None:
    """Ambiguous phase context exposes neither the aggregate nor R-phase claim."""
    created = {
        key for key in EPS_APPARENT_POWER_KEYS if _should_create_sensor(key, features)
    }
    assert created == ({expected_key} if expected_key is not None else set())


def test_runtime_diagnostic_translations_cover_every_locale_and_enum_state() -> None:
    """Every opt-in diagnostic has a localizable name and stable enum states."""
    component = Path("custom_components/eg4_web_monitor")
    files = [
        component / "strings.json",
        *sorted((component / "translations").glob("*.json")),
    ]
    expected_states = {
        "ac_input_type": {"grid", "generator"},
        "parallel_role": {
            "standalone",
            "master",
            "slave",
            "three_phase_master",
        },
        "parallel_phase": {"r", "s", "t"},
    }

    for path in files:
        sensor_strings = json.loads(path.read_text())["entity"]["sensor"]
        assert DIAGNOSTIC_KEYS <= sensor_strings.keys(), path
        for key, states in expected_states.items():
            assert sensor_strings[key]["state"].keys() == states, path


def test_runtime_diagnostics_create_inverter_scoped_entities() -> None:
    """Static LOCAL/HYBRID dictionaries instantiate each diagnostic key."""
    sensors = {
        "eps_apparent_power": 3456,
        "inverter_running_time": 86_400,
        "ac_input_type": "generator",
        "parallel_role": "master",
        "parallel_phase": "s",
        "parallel_unit_number": 7,
    }
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.get_device_info.return_value = None
    coordinator.has_http_api.return_value = False
    coordinator.has_configured_local_transport.return_value = False
    coordinator.data = {
        "devices": {
            "INV001": {
                "type": "inverter",
                "model": "FlexBOSS21",
                "features": {
                    "inverter_family": "EG4_HYBRID",
                    "grid_type": "split_phase",
                    "supports_three_phase": False,
                },
                "sensors": sensors,
                "batteries": {},
            }
        }
    }

    entities, battery_entities = _create_inverter_sensors(
        coordinator, "INV001", coordinator.data["devices"]["INV001"]
    )

    assert battery_entities == []
    assert {entity.unique_id for entity in entities} == {
        f"INV001_{key}" for key in COMMON_DIAGNOSTIC_KEYS | {"eps_apparent_power"}
    }
    assert {entity.native_value for entity in entities} == set(sensors.values())
    assert all(
        entity.entity_category is EntityCategory.DIAGNOSTIC for entity in entities
    )
    assert all(entity.entity_registry_enabled_default is False for entity in entities)
