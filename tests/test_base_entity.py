"""Tests for base entity classes."""

from unittest.mock import MagicMock

import pytest

from custom_components.eg4_web_monitor.base_entity import (
    EG4BatteryEntity,
    EG4DeviceEntity,
    EG4StationEntity,
    _guard_total_increasing,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "FlexBOSS 18K",
                "batteries": {
                    "Battery_ID_01": {"soc": 95},
                    "Battery_ID_02": {"soc": 93},
                },
            }
        },
        "station": {
            "name": "Test Station",
            "plantId": "test-plant-123",
        },
    }
    coordinator.plant_id = "test-plant-123"
    coordinator.last_update_success = True
    return coordinator


class TestEG4DeviceEntity:
    """Test EG4DeviceEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test device entity initialization."""
        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.coordinator == mock_coordinator
        assert entity._serial == "1234567890"

    def test_device_info(self, mock_coordinator):
        """Test device_info property."""
        mock_coordinator.get_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "1234567890")},
                "name": "FlexBOSS 18K 1234567890",
                "manufacturer": "EG4 Electronics",
            }
        )

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")
        device_info = entity.device_info

        assert device_info["name"] == "FlexBOSS 18K 1234567890"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_device_info.assert_called_once_with("1234567890")

    def test_device_info_none_fallback(self, mock_coordinator):
        """Test device_info returns None when not available."""
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_device_exists(self, mock_coordinator):
        """Test entity is available when device exists."""
        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is True

    def test_not_available_when_device_missing(self, mock_coordinator):
        """Test entity is not available when device is missing."""
        entity = EG4DeviceEntity(mock_coordinator, "9999999999")

        assert entity.available is False

    def test_not_available_when_no_data(self, mock_coordinator):
        """Test entity is not available when coordinator has no data."""
        mock_coordinator.data = None

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is False

    def test_not_available_when_no_devices_key(self, mock_coordinator):
        """Test entity is not available when coordinator data has no devices key."""
        mock_coordinator.data = {"station": {}}

        entity = EG4DeviceEntity(mock_coordinator, "1234567890")

        assert entity.available is False


class TestEG4BatteryEntity:
    """Test EG4BatteryEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test battery entity initialization."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.coordinator == mock_coordinator
        assert entity._parent_serial == "1234567890"
        assert entity._battery_key == "Battery_ID_01"

    def test_device_info(self, mock_coordinator):
        """Test battery device_info property."""
        mock_coordinator.get_battery_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "1234567890_Battery_ID_01")},
                "name": "Battery Battery_ID_01",
                "manufacturer": "EG4 Electronics",
                "via_device": ("eg4_web_monitor", "1234567890"),
            }
        )

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")
        device_info = entity.device_info

        assert device_info["name"] == "Battery Battery_ID_01"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_battery_device_info.assert_called_once_with(
            "1234567890", "Battery_ID_01"
        )

    def test_device_info_empty_fallback(self, mock_coordinator):
        """Test battery device_info returns None when not available."""
        mock_coordinator.get_battery_device_info = MagicMock(return_value=None)

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_battery_exists(self, mock_coordinator):
        """Test battery entity is available when battery exists."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.available is True

    def test_not_available_when_battery_missing(self, mock_coordinator):
        """Test battery entity is not available when battery is missing."""
        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_99")

        assert entity.available is False

    def test_not_available_when_parent_missing(self, mock_coordinator):
        """Test battery entity is not available when parent device is missing."""
        entity = EG4BatteryEntity(mock_coordinator, "9999999999", "Battery_ID_01")

        assert entity.available is False

    def test_not_available_when_no_batteries_key(self, mock_coordinator):
        """Test battery entity is not available when parent has no batteries."""
        mock_coordinator.data["devices"]["1234567890"].pop("batteries")

        entity = EG4BatteryEntity(mock_coordinator, "1234567890", "Battery_ID_01")

        assert entity.available is False


class TestEG4StationEntity:
    """Test EG4StationEntity base class."""

    def test_initialization(self, mock_coordinator):
        """Test station entity initialization."""
        entity = EG4StationEntity(mock_coordinator)

        assert entity.coordinator == mock_coordinator

    def test_device_info(self, mock_coordinator):
        """Test station device_info property."""
        mock_coordinator.get_station_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "station_test-plant-123")},
                "name": "Test Station",
                "manufacturer": "EG4 Electronics",
            }
        )

        entity = EG4StationEntity(mock_coordinator)
        device_info = entity.device_info

        assert device_info["name"] == "Test Station"
        assert device_info["manufacturer"] == "EG4 Electronics"
        mock_coordinator.get_station_device_info.assert_called_once()

    def test_device_info_none_fallback(self, mock_coordinator):
        """Test station device_info returns None when not available."""
        mock_coordinator.get_station_device_info = MagicMock(return_value=None)

        entity = EG4StationEntity(mock_coordinator)
        device_info = entity.device_info

        assert device_info is None

    def test_available_when_station_exists(self, mock_coordinator):
        """Test station entity is available when station data exists."""
        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is True

    def test_not_available_when_update_failed(self, mock_coordinator):
        """Test station entity is not available when last update failed."""
        mock_coordinator.last_update_success = False

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_not_available_when_no_data(self, mock_coordinator):
        """Test station entity is not available when coordinator has no data."""
        mock_coordinator.data = None

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_not_available_when_no_station_key(self, mock_coordinator):
        """Test station entity is not available when data has no station key."""
        mock_coordinator.data = {"devices": {}}

        entity = EG4StationEntity(mock_coordinator)

        assert entity.available is False

    def test_extra_state_attributes(self, mock_coordinator):
        """Test station extra_state_attributes includes plant_id."""
        entity = EG4StationEntity(mock_coordinator)
        attributes = entity.extra_state_attributes

        assert attributes is not None
        assert attributes["plant_id"] == "test-plant-123"


class TestGuardTotalIncreasing:
    """Tests for the ``_guard_total_increasing`` helper.

    Reproduces the conditions from issue #218 where cloud-API rounding noise
    drops ``consumption_lifetime`` from 2917.1 → 2917.0 and trips HA's
    "state is not strictly increasing" warning.
    """

    def test_increasing_passes_through(self):
        value, cache = _guard_total_increasing("total_increasing", 14.4, 14.3)
        assert value == 14.4
        assert cache == 14.4

    def test_same_value_passes_through(self):
        value, cache = _guard_total_increasing("total_increasing", 14.3, 14.3)
        assert value == 14.3
        assert cache == 14.3

    def test_small_dip_is_pinned_to_previous_high(self):
        # Issue #218 scenario: consumption 14.3 → 14.2 (within 10%).
        value, cache = _guard_total_increasing("total_increasing", 14.2, 14.3)
        assert value == 14.3
        assert cache == 14.3

    def test_lifetime_dip_is_pinned(self):
        # Issue #218 scenario: consumption_lifetime 2917.1 → 2917.0.
        value, cache = _guard_total_increasing("total_increasing", 2917.0, 2917.1)
        assert value == 2917.1
        assert cache == 2917.1

    def test_consecutive_dips_keep_cache_pinned(self):
        # Once pinned, the cache stays at the high — subsequent dips compare
        # against the previously reported value, not the noisy reading.
        value, cache = _guard_total_increasing("total_increasing", 14.2, 14.3)
        assert (value, cache) == (14.3, 14.3)
        value, cache = _guard_total_increasing("total_increasing", 14.1, cache)
        assert (value, cache) == (14.3, 14.3)

    def test_drop_just_below_10pct_is_treated_as_reset(self):
        # 14.3 → 12.86 is a 10.07% drop → above HA's reset threshold,
        # passes through and updates cache.
        value, cache = _guard_total_increasing("total_increasing", 12.86, 14.3)
        assert value == 12.86
        assert cache == 12.86

    def test_drop_exactly_at_10pct_is_suppressed(self):
        # 10.0 → 9.0 is exactly a 10% drop. HA still warns at this boundary
        # (warning condition is ``new < old`` with ``new >= 0.9 * old``).
        value, cache = _guard_total_increasing("total_increasing", 9.0, 10.0)
        assert value == 10.0
        assert cache == 10.0

    def test_daily_reset_to_zero_passes_through(self):
        # Daily ``consumption`` resets to 0 at midnight. 14.4 → 0.0 is a
        # 100% drop, treated as a reset. Cache must update so the next
        # comparison is against 0.0, not the previous day's high.
        value, cache = _guard_total_increasing("total_increasing", 0.0, 14.4)
        assert value == 0.0
        assert cache == 0.0

    def test_inverter_replacement_lifetime_reset(self):
        # Lifetime counter resets after inverter swap (e.g. 2917 → 0).
        value, cache = _guard_total_increasing("total_increasing", 0.0, 2917.1)
        assert value == 0.0
        assert cache == 0.0

    def test_first_value_passes_through(self):
        # No cache yet — pass through and seed cache.
        value, cache = _guard_total_increasing("total_increasing", 14.3, None)
        assert value == 14.3
        assert cache == 14.3

    def test_none_value_returns_none_without_touching_cache(self):
        value, cache = _guard_total_increasing("total_increasing", None, 14.3)
        assert value is None
        assert cache == 14.3

    def test_non_numeric_passes_through_without_touching_cache(self):
        # State class is wrong for strings, but be defensive.
        value, cache = _guard_total_increasing("total_increasing", "n/a", 14.3)
        assert value == "n/a"
        assert cache == 14.3

    def test_non_total_increasing_state_class_is_unaffected(self):
        # ``measurement`` and ``total`` sensors should pass through verbatim.
        # The cache is never consulted nor mutated for these sensors.
        for state_class in ("measurement", "total", None):
            value, cache = _guard_total_increasing(state_class, 5.0, 10.0)
            assert value == 5.0
            assert cache == 10.0  # unchanged — guard doesn't engage

    def test_enum_state_class_is_normalized(self):
        # Mimic ``SensorStateClass.TOTAL_INCREASING`` (StrEnum exposing .value).
        class _FakeEnum:
            value = "total_increasing"

        value, cache = _guard_total_increasing(_FakeEnum(), 14.2, 14.3)
        assert value == 14.3
        assert cache == 14.3

    def test_zero_previous_value_does_not_trigger_guard(self):
        # last_reported == 0 — guard requires positive last to engage. Any
        # value passes through (treating the 0-baseline as a fresh start).
        value, cache = _guard_total_increasing("total_increasing", 0.0, 0.0)
        assert value == 0.0
        assert cache == 0.0

    def test_negative_previous_value_does_not_trigger_guard(self):
        # Defensive: negative cache shouldn't engage suppression.
        value, cache = _guard_total_increasing("total_increasing", -1.0, -2.0)
        assert value == -1.0
        # ``new_val < last_reported`` is False here (-1 > -2), pass-through.
        assert cache == -1.0

    def test_recovery_after_dip_resumes_normal_progression(self):
        # 14.3 → 14.2 (dip suppressed) → 14.4 (real progress).
        value, cache = _guard_total_increasing("total_increasing", 14.2, 14.3)
        assert (value, cache) == (14.3, 14.3)
        value, cache = _guard_total_increasing("total_increasing", 14.4, cache)
        assert (value, cache) == (14.4, 14.4)


class TestGuardIntegrationWithBaseSensor:
    """End-to-end behaviour through ``EG4BaseSensor.native_value``."""

    def test_dip_suppressed_then_recovers(self, mock_coordinator):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor

        # Add a consumption_lifetime sensor reading to coordinator data.
        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption_lifetime": 2917.1,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption_lifetime")
        # Sanity: the sensor was wired up as total_increasing.
        assert sensor._attr_state_class == "total_increasing"

        # Initial reading establishes the high-water mark.
        assert sensor.native_value == 2917.1

        # Cloud noise drops the value by 0.1 — guard should pin to 2917.1.
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 2917.0
        assert sensor.native_value == 2917.1

        # Real progress passes through.
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 2917.2
        assert sensor.native_value == 2917.2

    def test_daily_reset_to_zero_passes_through(self, mock_coordinator):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption": 14.4,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption")
        assert sensor.native_value == 14.4

        # Midnight rollover — this MUST pass through so the daily total
        # actually resets in HA's recorder.
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 0.0
        assert sensor.native_value == 0.0

        # Subsequent reads compare against the post-reset baseline.
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 0.1
        assert sensor.native_value == 0.1
