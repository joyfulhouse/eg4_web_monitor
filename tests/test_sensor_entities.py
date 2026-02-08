"""Tests for EG4 sensor entity creation and setup."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eg4_web_monitor.const import (
    DISCHARGE_RECOVERY_SENSORS,
    SENSOR_TYPES,
    SPLIT_PHASE_ONLY_SENSORS,
    STATION_SENSOR_TYPES,
    THREE_PHASE_ONLY_SENSORS,
    VOLT_WATT_SENSORS,
)
from custom_components.eg4_web_monitor.sensor import (
    EG4BatteryBankSensor,
    EG4BatterySensor,
    EG4InverterSensor,
    EG4StationSensor,
    _create_inverter_sensors,
    _create_simple_device_sensors,
    _create_station_sensors,
    _should_create_sensor,
    async_setup_entry,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    devices: dict[str, dict[str, Any]] | None = None,
    station: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    plant_id: str = "plant_123",
) -> MagicMock:
    """Build a mock EG4DataUpdateCoordinator for sensor tests."""
    coordinator = MagicMock()
    coordinator.plant_id = plant_id
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.get_battery_device_info = MagicMock(return_value=None)
    coordinator.get_battery_bank_device_info = MagicMock(return_value=None)

    data: dict[str, Any] = {}
    if devices is not None:
        data["devices"] = devices
    if station is not None:
        data["station"] = station
    if parameters is not None:
        data["parameters"] = parameters
    coordinator.data = data if data else None
    return coordinator


def _inverter_device(
    *,
    model: str = "FlexBOSS21",
    sensors: dict[str, Any] | None = None,
    batteries: dict[str, dict[str, Any]] | None = None,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal inverter device data dict."""
    result: dict[str, Any] = {
        "type": "inverter",
        "model": model,
        "sensors": sensors or {},
        "batteries": batteries or {},
    }
    if features is not None:
        result["features"] = features
    return result


# ── _should_create_sensor ────────────────────────────────────────────


class TestShouldCreateSensor:
    """Test feature-based sensor filtering."""

    def test_no_features_creates_all(self):
        """No features dict → all sensors created (conservative fallback)."""
        assert _should_create_sensor("pv1_voltage", None) is True
        assert _should_create_sensor("grid_l2_voltage", None) is True
        assert _should_create_sensor("r_phase_voltage", None) is True

    def test_no_features_empty_dict(self):
        """Empty features dict → all sensors created."""
        assert _should_create_sensor("pv1_voltage", {}) is True

    def test_split_phase_sensor_with_support(self):
        """Split-phase sensor created when device supports it."""
        features = {"supports_split_phase": True}
        for key in SPLIT_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is True

    def test_split_phase_sensor_without_support(self):
        """Split-phase sensor skipped when device doesn't support it."""
        features = {"supports_split_phase": False}
        for key in SPLIT_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is False

    def test_three_phase_sensor_with_support(self):
        """Three-phase sensor created when device supports it."""
        features = {"supports_three_phase": True}
        for key in THREE_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is True

    def test_three_phase_sensor_without_support(self):
        """Three-phase sensor skipped when device doesn't support it."""
        features = {"supports_three_phase": False}
        for key in THREE_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is False

    def test_discharge_recovery_with_support(self):
        """Discharge recovery sensor created when device supports it."""
        features = {"supports_discharge_recovery_hysteresis": True}
        for key in DISCHARGE_RECOVERY_SENSORS:
            assert _should_create_sensor(key, features) is True

    def test_discharge_recovery_without_support(self):
        """Discharge recovery sensor skipped when device doesn't support it."""
        features = {"supports_discharge_recovery_hysteresis": False}
        for key in DISCHARGE_RECOVERY_SENSORS:
            assert _should_create_sensor(key, features) is False

    def test_volt_watt_with_support(self):
        """Volt-Watt sensor created when device supports it."""
        features = {"supports_volt_watt_curve": True}
        for key in VOLT_WATT_SENSORS:
            assert _should_create_sensor(key, features) is True

    def test_volt_watt_without_support(self):
        """Volt-Watt sensor skipped when device doesn't support it."""
        features = {"supports_volt_watt_curve": False}
        for key in VOLT_WATT_SENSORS:
            assert _should_create_sensor(key, features) is False

    def test_regular_sensor_always_created(self):
        """Normal sensor created regardless of features."""
        features = {
            "supports_split_phase": False,
            "supports_three_phase": False,
            "supports_discharge_recovery_hysteresis": False,
            "supports_volt_watt_curve": False,
        }
        assert _should_create_sensor("pv1_voltage", features) is True
        assert _should_create_sensor("state_of_charge", features) is True
        assert _should_create_sensor("battery_power", features) is True

    def test_default_true_when_feature_flag_missing(self):
        """If feature flag not in dict, defaults to True (conservative)."""
        # Features dict exists but doesn't have the specific key
        features = {"some_other_feature": True}
        for key in SPLIT_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is True
        for key in THREE_PHASE_ONLY_SENSORS:
            assert _should_create_sensor(key, features) is True


# ── _create_inverter_sensors ─────────────────────────────────────────


class TestCreateInverterSensors:
    """Test inverter sensor entity creation."""

    def test_basic_sensor_creation(self):
        """Creates EG4InverterSensor for known sensor keys."""
        coordinator = _mock_coordinator(devices={})
        device_data = _inverter_device(
            sensors={"pv1_voltage": 350.0, "state_of_charge": 85}
        )
        inverter_entities, battery_entities = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        assert len(inverter_entities) == 2
        assert len(battery_entities) == 0
        assert all(isinstance(e, EG4InverterSensor) for e in inverter_entities)

    def test_unknown_sensor_keys_skipped(self):
        """Sensor keys not in SENSOR_TYPES are skipped."""
        coordinator = _mock_coordinator(devices={})
        device_data = _inverter_device(
            sensors={"pv1_voltage": 350.0, "totally_fake_sensor": 42}
        )
        inverter_entities, _ = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        assert len(inverter_entities) == 1

    def test_battery_bank_sensors_separated(self):
        """Sensors starting with battery_bank_ go to phase 1 as BatteryBankSensor."""
        coordinator = _mock_coordinator(devices={})
        # Find a real battery_bank key from SENSOR_TYPES
        bank_keys = [k for k in SENSOR_TYPES if k.startswith("battery_bank_")]
        if not bank_keys:
            pytest.skip("No battery_bank_ keys in SENSOR_TYPES")

        sensors = {"pv1_voltage": 350.0}
        for key in bank_keys[:2]:
            sensors[key] = 42.0

        device_data = _inverter_device(sensors=sensors)
        inverter_entities, battery_entities = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        bank_entities = [
            e for e in inverter_entities if isinstance(e, EG4BatteryBankSensor)
        ]
        inverter_only = [
            e for e in inverter_entities if isinstance(e, EG4InverterSensor)
        ]

        assert len(bank_entities) == min(2, len(bank_keys))
        assert len(inverter_only) == 1  # pv1_voltage
        assert len(battery_entities) == 0

    def test_individual_battery_sensors_phase2(self):
        """Individual battery sensors go to phase 2."""
        coordinator = _mock_coordinator(devices={})
        # Find a real battery sensor key
        batt_keys = [
            k for k in SENSOR_TYPES if "battery_voltage" in k or k == "battery_soc"
        ]
        if not batt_keys:
            batt_keys = ["battery_voltage"]

        device_data = _inverter_device(
            sensors={"pv1_voltage": 350.0},
            batteries={"INV001-01": {batt_keys[0]: 52.5}},
        )
        inverter_entities, battery_entities = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        assert len(battery_entities) == 1
        assert isinstance(battery_entities[0], EG4BatterySensor)

    def test_feature_filtering_skips_sensors(self):
        """Sensors filtered out by feature flags don't create entities."""
        coordinator = _mock_coordinator(devices={})
        # Pick one split-phase sensor that's in SENSOR_TYPES
        split_keys = [k for k in SPLIT_PHASE_ONLY_SENSORS if k in SENSOR_TYPES]
        if not split_keys:
            pytest.skip("No split-phase keys in SENSOR_TYPES")

        sensors = {"pv1_voltage": 350.0}
        for k in split_keys[:1]:
            sensors[k] = 120.0

        device_data = _inverter_device(
            sensors=sensors,
            features={"supports_split_phase": False},
        )
        inverter_entities, _ = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        # Only pv1_voltage should be created, split-phase filtered out
        assert len(inverter_entities) == 1

    def test_no_features_creates_all_sensors(self):
        """Without features dict, all sensors created (conservative)."""
        coordinator = _mock_coordinator(devices={})
        split_keys = [k for k in SPLIT_PHASE_ONLY_SENSORS if k in SENSOR_TYPES]
        if not split_keys:
            pytest.skip("No split-phase keys in SENSOR_TYPES")

        sensors = {"pv1_voltage": 350.0}
        for k in split_keys[:1]:
            sensors[k] = 120.0

        device_data = _inverter_device(sensors=sensors)  # No features key
        inverter_entities, _ = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        assert len(inverter_entities) == 2  # Both created

    def test_empty_sensors_dict(self):
        """Empty sensors dict creates no entities."""
        coordinator = _mock_coordinator(devices={})
        device_data = _inverter_device(sensors={})
        inverter_entities, battery_entities = _create_inverter_sensors(
            coordinator, "INV001", device_data
        )
        assert len(inverter_entities) == 0
        assert len(battery_entities) == 0


# ── _create_simple_device_sensors ────────────────────────────────────


class TestCreateSimpleDeviceSensors:
    """Test GridBOSS and parallel group sensor creation."""

    def test_gridboss_sensors(self):
        """Creates EG4InverterSensor for GridBOSS device."""
        coordinator = _mock_coordinator(devices={})
        device_data = {
            "type": "gridboss",
            "model": "GridBOSS",
            "sensors": {"grid_power": 5000, "load_power": 3000},
        }
        entities = _create_simple_device_sensors(
            coordinator, "GB001", device_data, "gridboss"
        )
        valid_count = sum(1 for k in device_data["sensors"] if k in SENSOR_TYPES)
        assert len(entities) == valid_count
        assert all(isinstance(e, EG4InverterSensor) for e in entities)

    def test_parallel_group_sensors(self):
        """Creates EG4InverterSensor for parallel group device."""
        coordinator = _mock_coordinator(devices={})
        device_data = {
            "type": "parallel_group",
            "model": "Parallel Group",
            "sensors": {"pv_total_power": 10000, "grid_power": 500},
        }
        entities = _create_simple_device_sensors(
            coordinator, "parallel_group_INV001", device_data, "parallel_group"
        )
        valid_count = sum(1 for k in device_data["sensors"] if k in SENSOR_TYPES)
        assert len(entities) == valid_count

    def test_unknown_keys_skipped(self):
        """Unknown sensor keys in device data are skipped."""
        coordinator = _mock_coordinator(devices={})
        device_data = {
            "type": "gridboss",
            "model": "GridBOSS",
            "sensors": {"fake_sensor": 42},
        }
        entities = _create_simple_device_sensors(
            coordinator, "GB001", device_data, "gridboss"
        )
        assert len(entities) == 0


# ── _create_station_sensors ──────────────────────────────────────────


class TestCreateStationSensors:
    """Test station sensor creation."""

    def test_creates_all_station_sensors(self):
        """Creates one entity per STATION_SENSOR_TYPES key."""
        coordinator = _mock_coordinator(station={"name": "Test"})
        entities = _create_station_sensors(coordinator)
        assert len(entities) == len(STATION_SENSOR_TYPES)
        assert all(isinstance(e, EG4StationSensor) for e in entities)

    def test_station_sensor_unique_ids(self):
        """Each station sensor has a unique ID."""
        coordinator = _mock_coordinator(station={"name": "Test"})
        entities = _create_station_sensors(coordinator)
        unique_ids = {e._attr_unique_id for e in entities}
        assert len(unique_ids) == len(entities)


# ── async_setup_entry ────────────────────────────────────────────────


class TestAsyncSetupEntry:
    """Test the full sensor platform setup."""

    @pytest.fixture
    def mock_entry(self):
        """Create a mock config entry with runtime_data."""
        entry = MagicMock()
        entry.async_on_unload = MagicMock()
        return entry

    async def test_no_data_returns_early(self, hass, mock_entry):
        """No coordinator data → returns without creating entities."""
        coordinator = _mock_coordinator()
        coordinator.data = None
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )
        assert len(added) == 0

    async def test_station_only_data(self, hass, mock_entry):
        """Station data without devices → creates station sensors only."""
        coordinator = _mock_coordinator(station={"name": "Test"})
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )
        station_count = sum(1 for e in added if isinstance(e, EG4StationSensor))
        assert station_count == len(STATION_SENSOR_TYPES)

    async def test_inverter_with_batteries_phases(self, hass, mock_entry):
        """Inverter with batteries → phase 1 and phase 2 entities created."""
        # Find valid sensor keys
        valid_key = next(k for k in SENSOR_TYPES if not k.startswith("battery_bank_"))
        batt_key = next(
            k for k in SENSOR_TYPES if "battery_voltage" in k or k == "battery_soc"
        )

        coordinator = _mock_coordinator(
            devices={
                "INV001": _inverter_device(
                    sensors={valid_key: 42},
                    batteries={"INV001-01": {batt_key: 52.5}},
                ),
            },
        )
        mock_entry.runtime_data = coordinator

        phases: list[list] = []
        call_count = 0

        def mock_add(entities, update_before_add):
            nonlocal call_count
            phases.append(list(entities))
            call_count += 1

        await async_setup_entry(hass, mock_entry, mock_add)

        # Phase 1 (inverter sensors) and phase 2 (battery sensors)
        assert call_count == 2
        assert len(phases[0]) >= 1  # Phase 1: inverter sensors
        assert len(phases[1]) >= 1  # Phase 2: battery sensors

    async def test_gridboss_device_creates_sensors(self, hass, mock_entry):
        """GridBOSS device creates sensors via _create_simple_device_sensors."""
        # Use a sensor key that exists in SENSOR_TYPES
        valid_keys = [k for k in ["grid_power", "load_power"] if k in SENSOR_TYPES]
        if not valid_keys:
            pytest.skip("No gridboss sensor keys in SENSOR_TYPES")

        coordinator = _mock_coordinator(
            devices={
                "GB001": {
                    "type": "gridboss",
                    "model": "GridBOSS",
                    "sensors": {k: 5000 for k in valid_keys},
                },
            },
        )
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )
        assert len(added) == len(valid_keys)

    async def test_late_battery_registration_callback(self, hass, mock_entry):
        """Late battery registration discovers batteries added after setup."""
        batt_key = next(
            k for k in SENSOR_TYPES if "battery_voltage" in k or k == "battery_soc"
        )

        # Start with no batteries
        coordinator = _mock_coordinator(
            devices={
                "INV001": _inverter_device(
                    sensors={"pv1_voltage": 350},
                    batteries={},
                ),
            },
        )
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )

        # Capture the listener callback
        assert mock_entry.async_on_unload.called
        # The coordinator.async_add_listener was called with the callback
        listener_call = coordinator.async_add_listener.call_args
        callback = listener_call[0][0]

        # Now simulate new batteries appearing in coordinator data
        coordinator.data["devices"]["INV001"]["batteries"]["INV001-01"] = {
            batt_key: 52.5,
        }

        # Clear added list and call the callback
        added.clear()
        callback()

        # New battery entities should have been added
        assert len(added) >= 1
        assert any(isinstance(e, EG4BatterySensor) for e in added)

    async def test_late_battery_ignores_known(self, hass, mock_entry):
        """Late battery registration doesn't re-add known batteries."""
        batt_key = next(
            k for k in SENSOR_TYPES if "battery_voltage" in k or k == "battery_soc"
        )

        coordinator = _mock_coordinator(
            devices={
                "INV001": _inverter_device(
                    sensors={"pv1_voltage": 350},
                    batteries={"INV001-01": {batt_key: 52.5}},
                ),
            },
        )
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )

        listener_call = coordinator.async_add_listener.call_args
        callback = listener_call[0][0]

        # Call callback - no new batteries
        added.clear()
        callback()
        assert len(added) == 0

    async def test_unknown_device_type_warning(self, hass, mock_entry):
        """Unknown device type logs warning but doesn't crash."""
        coordinator = _mock_coordinator(
            devices={
                "UNK001": {
                    "type": "unknown_type",
                    "model": "Mystery",
                    "sensors": {"pv1_voltage": 42},
                },
            },
        )
        mock_entry.runtime_data = coordinator

        added: list = []
        await async_setup_entry(
            hass, mock_entry, lambda entities, _: added.extend(entities)
        )
        # No entities created for unknown type
        assert len(added) == 0


# ── EG4StationSensor ─────────────────────────────────────────────────


class TestEG4StationSensor:
    """Test station sensor native_value mapping."""

    def _make_sensor(
        self, sensor_key: str, station_data: dict[str, Any]
    ) -> EG4StationSensor:
        coordinator = _mock_coordinator(station=station_data)
        return EG4StationSensor(coordinator=coordinator, sensor_key=sensor_key)

    def test_station_name(self):
        sensor = self._make_sensor("station_name", {"name": "My Station"})
        assert sensor.native_value == "My Station"

    def test_station_country(self):
        sensor = self._make_sensor("station_country", {"country": "US"})
        assert sensor.native_value == "US"

    def test_station_timezone(self):
        sensor = self._make_sensor("station_timezone", {"timezone": "GMT -8"})
        assert sensor.native_value == "GMT -8"

    def test_station_create_date(self):
        sensor = self._make_sensor("station_create_date", {"createDate": "2025-01-01"})
        assert sensor.native_value == "2025-01-01"

    def test_station_address(self):
        sensor = self._make_sensor("station_address", {"address": "123 Main St"})
        assert sensor.native_value == "123 Main St"

    def test_station_last_polled(self):
        sensor = self._make_sensor(
            "station_last_polled", {"station_last_polled": "2025-01-01T12:00:00"}
        )
        assert sensor.native_value == "2025-01-01T12:00:00"

    def test_api_request_rate(self):
        sensor = self._make_sensor("api_request_rate", {"api_request_rate": 15.0})
        assert sensor.native_value == 15.0

    def test_api_peak_request_rate(self):
        sensor = self._make_sensor(
            "api_peak_request_rate", {"api_peak_request_rate": 42.0}
        )
        assert sensor.native_value == 42.0

    def test_api_requests_today(self):
        sensor = self._make_sensor("api_requests_today", {"api_requests_today": 500})
        assert sensor.native_value == 500

    def test_missing_station_data(self):
        """Returns None when station data is missing."""
        coordinator = _mock_coordinator()
        coordinator.data = None
        sensor = EG4StationSensor(coordinator=coordinator, sensor_key="station_name")
        assert sensor.native_value is None

    def test_unknown_sensor_key_raises(self):
        """Unknown sensor key raises KeyError during init."""
        with pytest.raises(KeyError):
            self._make_sensor("nonexistent_key", {"name": "Test"})
