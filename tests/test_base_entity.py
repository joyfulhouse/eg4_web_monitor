"""Tests for base entity classes."""

from unittest.mock import AsyncMock, MagicMock

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

    @pytest.mark.parametrize("sensor_kind", ["device", "battery", "bank"])
    @pytest.mark.asyncio
    async def test_restored_high_seeds_dip_guard(self, mock_coordinator, sensor_kind):
        from custom_components.eg4_web_monitor.base_entity import (
            EG4BaseBatterySensor,
            EG4BaseSensor,
            EG4BatteryBankEntity,
        )
        from homeassistant.components.sensor import SensorExtraStoredData

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption_lifetime": 14.8,
        }
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["Battery_ID_01"][
            "consumption_lifetime"
        ] = 14.8
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        mock_coordinator.get_battery_device_info = MagicMock(return_value=None)
        mock_coordinator.get_battery_bank_device_info = MagicMock(return_value=None)
        if sensor_kind == "device":
            sensor = EG4BaseSensor(
                mock_coordinator, "1234567890", "consumption_lifetime"
            )
        elif sensor_kind == "battery":
            sensor = EG4BaseBatterySensor(
                mock_coordinator,
                "1234567890",
                "Battery_ID_01",
                "consumption_lifetime",
            )
        else:
            sensor = EG4BatteryBankEntity(
                mock_coordinator, "1234567890", "consumption_lifetime"
            )

        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(15.3, "kWh")
        )
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()

        assert sensor.native_value == 15.3
        sensor.async_get_last_sensor_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_daily_restore_from_prior_local_day_is_ignored(
        self, mock_coordinator
    ):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData
        from homeassistant.util import dt as dt_util

        old_timezone = dt_util.DEFAULT_TIME_ZONE
        dt_util.set_default_time_zone(ZoneInfo("America/Los_Angeles"))
        from freezegun import freeze_time

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption": 13.5,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption")
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(14.4, "kWh")
        )
        sensor.async_get_last_state = AsyncMock(
            return_value=MagicMock(
                last_updated=datetime(2026, 10, 4, 6, 30, tzinfo=timezone.utc)
            )
        )

        try:
            with freeze_time("2026-10-04T08:00:00Z"):
                await sensor.async_added_to_hass()

                assert sensor._last_reported_value is None
                assert sensor.native_value == 13.5
                assert sensor._last_reported_value == 13.5
        finally:
            dt_util.set_default_time_zone(old_timezone)

    @pytest.mark.asyncio
    async def test_daily_restore_from_same_local_day_seeds_guard(
        self, mock_coordinator
    ):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData
        from homeassistant.util import dt as dt_util
        from freezegun import freeze_time

        old_timezone = dt_util.DEFAULT_TIME_ZONE
        dt_util.set_default_time_zone(ZoneInfo("America/Los_Angeles"))
        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption": 13.5,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption")
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(14.4, "kWh")
        )
        sensor.async_get_last_state = AsyncMock(
            return_value=MagicMock(
                last_updated=datetime(2026, 10, 3, 23, 30, tzinfo=timezone.utc)
            )
        )

        try:
            with freeze_time("2026-10-04T02:00:00Z"):
                await sensor.async_added_to_hass()

                assert sensor.native_value == 14.4
                assert sensor._last_reported_value == 14.4
        finally:
            dt_util.set_default_time_zone(old_timezone)

    @pytest.mark.parametrize(
        "restored", [None, float("inf"), float("nan"), "unknown", True]
    )
    @pytest.mark.asyncio
    async def test_invalid_restored_value_does_not_seed_guard(
        self, mock_coordinator, restored
    ):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData

        current = 0.95 if restored is True else 13.5
        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption_lifetime": current,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor_key = "consumption_lifetime"
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", sensor_key)
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(restored, "kWh")
        )
        sensor.async_get_last_state = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor._last_reported_value is None
        assert sensor.native_value == current
        assert sensor._last_reported_value == current

    @pytest.mark.asyncio
    async def test_restored_guard_still_accepts_genuine_large_reset(
        self, mock_coordinator
    ):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption_lifetime": 10.0,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption_lifetime")
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(15.3, "kWh")
        )
        sensor.async_get_last_state = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor.native_value == 10.0
        sensor.async_get_last_sensor_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restored_value_in_different_native_unit_is_ignored(
        self, mock_coordinator
    ):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "consumption_lifetime": 13.5,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "consumption_lifetime")
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(14.4, "Wh")
        )
        sensor.async_get_last_state = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor._last_reported_value is None
        assert sensor.native_value == 13.5
        assert sensor._last_reported_value == 13.5

    @pytest.mark.asyncio
    async def test_non_total_increasing_restore_does_not_seed_guard(
        self, mock_coordinator
    ):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor
        from homeassistant.components.sensor import SensorExtraStoredData

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "battery_voltage": 13.5,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)
        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "battery_voltage")
        sensor.async_get_last_sensor_data = AsyncMock(
            return_value=SensorExtraStoredData(14.4, "V")
        )
        sensor.async_get_last_state = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor.native_value == 13.5
        assert sensor._last_reported_value is None

    def test_daily_total_keys_derive_from_sensor_types(self):
        from custom_components.eg4_web_monitor.base_entity import (
            _DAILY_TOTAL_SENSOR_KEYS,
            _NON_DAILY_TOTAL_SENSOR_KEY_PARTS,
        )
        from custom_components.eg4_web_monitor.const import SENSOR_TYPES

        expected_existing_daily_keys = {
            "daily_energy",
            "yield",
            "discharging",
            "charging",
            "consumption",
            "load_energy",
            "grid_export",
            "grid_import",
            "inverter_energy",
            "ac_charge_energy",
            "eps_energy",
            "generator_energy",
            "battery_charge",
            "battery_discharge",
            "eps_energy_today_l1",
            "eps_energy_today_l2",
            *(f"pv{index}_yield" for index in range(1, 7)),
        }
        today_keys = {
            sensor_key
            for sensor_key, sensor_config in SENSOR_TYPES.items()
            if sensor_key.endswith("_today")
            and sensor_config.get("state_class") == "total_increasing"
        }
        expected = expected_existing_daily_keys | today_keys
        expected_from_sensor_types = {
            sensor_key
            for sensor_key, sensor_config in SENSOR_TYPES.items()
            if sensor_config.get("state_class") == "total_increasing"
            and not sensor_key.startswith(("total_", "monthly_", "yearly_"))
            and sensor_key != "cycle_count"
            and not any(
                part in sensor_key for part in _NON_DAILY_TOTAL_SENSOR_KEY_PARTS
            )
        }

        assert _DAILY_TOTAL_SENSOR_KEYS == expected_from_sensor_types == expected


class TestErrorKeyAvailabilityContract:
    """Link-down LOCAL contract (eg4-57g): an ``"error"`` key on the device
    data makes sensor entities unavailable instead of frozen-fresh."""

    def test_base_sensor_unavailable_when_device_error(self, mock_coordinator):
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "battery_voltage": 53.2,
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        sensor = EG4BaseSensor(mock_coordinator, "1234567890", "battery_voltage")
        assert sensor.available is True

        # Coordinator marks the device link-down (LOCAL mode, no cloud).
        mock_coordinator.data["devices"]["1234567890"]["error"] = (
            "Local transport link down"
        )
        assert sensor.available is False

        # Recovery rebuilds the device data without the error key.
        del mock_coordinator.data["devices"]["1234567890"]["error"]
        assert sensor.available is True

    def test_battery_sensor_unavailable_when_parent_error(self, mock_coordinator):
        from custom_components.eg4_web_monitor.base_entity import (
            EG4BaseBatterySensor,
        )

        mock_coordinator.get_battery_device_info = MagicMock(return_value=None)

        sensor = EG4BaseBatterySensor(
            mock_coordinator, "1234567890", "Battery_ID_01", "soc"
        )
        assert sensor.available is True

        mock_coordinator.data["devices"]["1234567890"]["error"] = (
            "Local transport link down"
        )
        assert sensor.available is False

    def test_battery_bank_sensor_unavailable_when_device_error(self, mock_coordinator):
        """Battery-bank sensors are measurements: error key -> unavailable
        (eg4-57g review HIGH-1b)."""
        from custom_components.eg4_web_monitor.base_entity import (
            EG4BatteryBankEntity,
        )

        mock_coordinator.data["devices"]["1234567890"]["sensors"] = {
            "battery_bank_current": 12.5,
        }
        mock_coordinator.get_battery_bank_device_info = MagicMock(return_value=None)

        sensor = EG4BatteryBankEntity(
            mock_coordinator, "1234567890", "battery_bank_current"
        )
        assert sensor.available is True

        mock_coordinator.data["devices"]["1234567890"]["error"] = (
            "Local transport link down"
        )
        assert sensor.available is False

        del mock_coordinator.data["devices"]["1234567890"]["error"]
        assert sensor.available is True

    def test_parallel_group_sensor_unavailable_when_error(self, mock_coordinator):
        """PG sensors go unavailable when the group is error-marked
        (link-down member taints the aggregate — eg4-57g review HIGH-1a)."""
        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor

        mock_coordinator.data["devices"]["parallel_group_a"] = {
            "type": "parallel_group",
            "sensors": {"pv_total_power": 5000.0},
        }
        mock_coordinator.get_device_info = MagicMock(return_value=None)

        sensor = EG4BaseSensor(
            mock_coordinator,
            "parallel_group_a",
            "pv_total_power",
            device_type="parallel_group",
        )
        assert sensor.available is True

        mock_coordinator.data["devices"]["parallel_group_a"]["error"] = (
            "Local transport link down for member(s): SYNTH10015"
        )
        assert sensor.available is False
