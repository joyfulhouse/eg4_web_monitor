"""Contracts for safe read-only diagnostics from canonical input registers."""

from unittest.mock import MagicMock

from homeassistant.const import EntityCategory, UnitOfTime
from pylxpweb.transports.data import InverterRuntimeData

from custom_components.eg4_web_monitor.const import SENSOR_TYPES
from custom_components.eg4_web_monitor.coordinator_mappings import (
    INVERTER_RUNTIME_KEYS,
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.sensor import _create_inverter_sensors


DIAGNOSTIC_KEYS = {
    "eps_apparent_power",
    "inverter_running_time",
    "ac_input_type",
    "parallel_role",
    "parallel_phase",
    "parallel_unit_number",
}


def test_runtime_diagnostics_decode_canonical_fields() -> None:
    """I25/I69-70/I77/I113 become stable, user-facing values."""
    runtime = InverterRuntimeData(
        eps_apparent_power=3456,
        inverter_on_time=86_400,
        ac_input_type=0b111,
        parallel_master_slave=1,
        parallel_phase=1,
        parallel_number=7,
    )

    mapping = _build_runtime_sensor_mapping(runtime)

    assert mapping["eps_apparent_power"] == 3456
    assert mapping["inverter_running_time"] == 86_400
    assert mapping["ac_input_type"] == "Generator"
    assert mapping["parallel_role"] == "Master"
    assert mapping["parallel_phase"] == "S"
    assert mapping["parallel_unit_number"] == 7
    assert DIAGNOSTIC_KEYS <= INVERTER_RUNTIME_KEYS


def test_runtime_diagnostics_keep_absence_and_standalone_semantics_honest() -> None:
    """Missing data stays unknown; standalone units have no phase/unit ID."""
    missing = _build_runtime_sensor_mapping(InverterRuntimeData())
    assert {key: missing[key] for key in DIAGNOSTIC_KEYS} == dict.fromkeys(
        DIAGNOSTIC_KEYS
    )

    standalone = _build_runtime_sensor_mapping(
        InverterRuntimeData(
            ac_input_type=0,
            parallel_master_slave=0,
            parallel_phase=0,
            parallel_number=0,
        )
    )
    assert standalone["ac_input_type"] == "Grid"
    assert standalone["parallel_role"] == "Standalone"
    assert standalone["parallel_phase"] is None
    assert standalone["parallel_unit_number"] is None


def test_runtime_diagnostics_are_disabled_read_only_entities() -> None:
    """The extra register detail is diagnostic and opt-in, never writable."""
    assert SENSOR_TYPES["eps_apparent_power"] == {
        "name": "EPS Apparent Power",
        "unit": "VA",
        "device_class": "apparent_power",
        "state_class": "measurement",
        "icon": "mdi:power-plug-outline",
        "entity_category": "diagnostic",
        "enabled_default": False,
    }
    assert SENSOR_TYPES["inverter_running_time"] == {
        "name": "Inverter Running Time",
        "unit": UnitOfTime.SECONDS,
        "device_class": "duration",
        "state_class": "total_increasing",
        "icon": "mdi:timer-outline",
        "entity_category": "diagnostic",
        "enabled_default": False,
    }
    for key, options in {
        "ac_input_type": ["Grid", "Generator"],
        "parallel_role": ["Standalone", "Master", "Slave", "Three-Phase Master"],
        "parallel_phase": ["R", "S", "T"],
    }.items():
        config = SENSOR_TYPES[key]
        assert config["device_class"] == "enum"
        assert config["options"] == options
        assert config["entity_category"] == "diagnostic"
        assert config["enabled_default"] is False
        assert "state_class" not in config
        assert "unit" not in config

    number_config = SENSOR_TYPES["parallel_unit_number"]
    assert number_config["entity_category"] == "diagnostic"
    assert number_config["enabled_default"] is False
    assert "state_class" not in number_config


def test_runtime_diagnostics_create_inverter_scoped_entities() -> None:
    """Static LOCAL/HYBRID dictionaries instantiate each diagnostic key."""
    sensors = {
        "eps_apparent_power": 3456,
        "inverter_running_time": 86_400,
        "ac_input_type": "Generator",
        "parallel_role": "Master",
        "parallel_phase": "S",
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
                "features": {"inverter_family": "EG4_HYBRID"},
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
        f"INV001_{key}" for key in DIAGNOSTIC_KEYS
    }
    assert {entity.native_value for entity in entities} == set(sensors.values())
    assert all(
        entity.entity_category is EntityCategory.DIAGNOSTIC for entity in entities
    )
    assert all(entity.entity_registry_enabled_default is False for entity in entities)
