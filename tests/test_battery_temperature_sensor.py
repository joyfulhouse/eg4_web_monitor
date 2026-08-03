"""Regression coverage for the inverter battery-temperature entity (I67)."""

from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature
from pylxpweb.transports.data import InverterRuntimeData

from custom_components.eg4_web_monitor.const import SENSOR_TYPES
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.sensor import (
    EG4InverterSensor,
    _create_inverter_sensors,
)


def _coordinator(value: float | None) -> MagicMock:
    """Return a minimal healthy coordinator publishing I67's normalized value."""
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
                "sensors": {"battery_temperature": value},
                "batteries": {},
            }
        }
    }
    return coordinator


def test_i67_has_temperature_diagnostic_metadata() -> None:
    """The already-mapped I67 key must have a real HA sensor description."""
    config = SENSOR_TYPES["battery_temperature"]

    assert config == {
        "name": "Battery Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
        "entity_category": "diagnostic",
    }


def test_i67_creates_an_inverter_entity_and_preserves_signed_value() -> None:
    """A valid signed I67 reading reaches an inverter-scoped HA entity."""
    coordinator = _coordinator(-12.0)

    inverter_entities, battery_entities = _create_inverter_sensors(
        coordinator,
        "INV001",
        coordinator.data["devices"]["INV001"],
    )

    assert battery_entities == []
    assert len(inverter_entities) == 1
    entity = inverter_entities[0]
    assert isinstance(entity, EG4InverterSensor)
    assert entity.unique_id == "INV001_battery_temperature"
    assert entity.native_value == -12.0
    assert entity.device_class == SensorDeviceClass.TEMPERATURE
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert entity.native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert entity.entity_category is EntityCategory.DIAGNOSTIC
    assert entity.available is True


def test_i67_no_reading_sentinel_remains_unknown() -> None:
    """pylxpweb's 0x7f normalization must surface as unknown, never 127 °C."""
    runtime = InverterRuntimeData(battery_temperature=127.0)
    assert runtime.battery_temperature is None
    assert _build_runtime_sensor_mapping(runtime)["battery_temperature"] is None

    coordinator = _coordinator(None)
    inverter_entities, _ = _create_inverter_sensors(
        coordinator,
        "INV001",
        coordinator.data["devices"]["INV001"],
    )
    assert inverter_entities[0].native_value is None
