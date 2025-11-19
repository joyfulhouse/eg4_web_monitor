"""Test monotonic state tracking for total_increasing sensors."""

import pytest
from unittest.mock import MagicMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from datetime import datetime, timezone, timedelta

from custom_components.eg4_web_monitor.sensor import (
    EG4InverterSensor,
    EG4BatterySensor,
    LIFETIME_SENSORS,
    _get_current_date,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with test data."""
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = {
        "station": {
            "name": "Test Station",
            "timezone": "GMT -8",
        },
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "18kPV",
                "sensors": {
                    "consumption": 100.0,
                    "consumption_lifetime": 5000.0,
                    "daily_energy": 10.0,
                    "yield": 25.0,
                },
                "batteries": {
                    "battery_1": {
                        "cycle_count": 50.0,
                        "battery_real_voltage": 52.0,
                    }
                },
            }
        }
    }
    coordinator.last_update_success = True
    return coordinator


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


class TestEG4InverterSensorMonotonic:
    """Test monotonic state tracking for EG4InverterSensor."""

    def test_initial_value_tracking(self, mock_coordinator):
        """Test that initial value is tracked correctly."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # First read should set the initial value
        value = sensor.native_value
        assert value == 100.0
        assert sensor._last_valid_state == 100.0

    def test_increasing_value_accepted(self, mock_coordinator):
        """Test that increasing values are accepted."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Update to higher value
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 150.0
        value = sensor.native_value
        assert value == 150.0
        assert sensor._last_valid_state == 150.0

    def test_decreasing_value_rejected(self, mock_coordinator):
        """Test that decreasing values are rejected and previous value maintained."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Attempt to decrease (API glitch)
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 99.9
        value = sensor.native_value
        assert value == 100.0  # Should maintain previous value
        assert sensor._last_valid_state == 100.0

    def test_slight_decrease_rejected(self, mock_coordinator):
        """Test that even slight decreases (like 0.1 kWh) are rejected."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Set initial value to match issue report
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 12258.0
        _ = sensor.native_value
        assert sensor._last_valid_state == 12258.0

        # Attempt slight decrease (like in issue #29)
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 12257.9
        value = sensor.native_value
        assert value == 12258.0  # Should maintain previous value
        assert sensor._last_valid_state == 12258.0

    def test_recovery_after_decrease(self, mock_coordinator):
        """Test that sensor recovers correctly after a temporary decrease."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Temporary decrease (API glitch)
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 99.5
        value = sensor.native_value
        assert value == 100.0

        # Recovery to higher value
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 105.0
        value = sensor.native_value
        assert value == 105.0
        assert sensor._last_valid_state == 105.0

    def test_non_total_increasing_not_affected(self, mock_coordinator):
        """Test that non-total_increasing sensors are not affected by monotonic tracking."""
        # Add a measurement sensor (not total_increasing)
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["power"] = 1000.0

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="power",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state is None  # Should not track

        # Decrease should be allowed for measurement sensors
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["power"] = 500.0
        value = sensor.native_value
        assert value == 500.0
        assert sensor._last_valid_state is None

    def test_none_value_handling(self, mock_coordinator):
        """Test that None values are handled correctly."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial valid value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # None value
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = None
        value = sensor.native_value
        assert value is None
        # Last valid state should remain unchanged
        assert sensor._last_valid_state == 100.0

    def test_invalid_type_handling(self, mock_coordinator):
        """Test that invalid types are handled gracefully."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial valid value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Invalid string that can't be converted
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = (
            "invalid"
        )
        value = sensor.native_value
        assert value == "invalid"  # Should return raw value
        # Last valid state should remain unchanged
        assert sensor._last_valid_state == 100.0


class TestEG4BatterySensorMonotonic:
    """Test monotonic state tracking for EG4BatterySensor."""

    def test_battery_initial_value_tracking(self, mock_coordinator):
        """Test that initial battery value is tracked correctly."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # First read should set the initial value
        value = sensor.native_value
        assert value == 50.0
        assert sensor._last_valid_state == 50.0

    def test_battery_increasing_value_accepted(self, mock_coordinator):
        """Test that increasing battery values are accepted."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # Update to higher value
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 75.0
        value = sensor.native_value
        assert value == 75.0
        assert sensor._last_valid_state == 75.0

    def test_battery_decreasing_value_rejected(self, mock_coordinator):
        """Test that decreasing battery values are rejected."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # Attempt to decrease
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 49.9
        value = sensor.native_value
        assert value == 50.0  # Should maintain previous value
        assert sensor._last_valid_state == 50.0

    def test_battery_slight_decrease_rejected(self, mock_coordinator):
        """Test that even slight battery decreases are rejected."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Set initial value
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 100.0
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Attempt slight decrease
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 99.95
        value = sensor.native_value
        assert value == 100.0  # Should maintain previous value
        assert sensor._last_valid_state == 100.0

    def test_battery_recovery_after_decrease(self, mock_coordinator):
        """Test that battery sensor recovers correctly after temporary decrease."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # Temporary decrease
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 49.0
        value = sensor.native_value
        assert value == 50.0

        # Recovery to higher value
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 60.0
        value = sensor.native_value
        assert value == 60.0
        assert sensor._last_valid_state == 60.0

    def test_battery_none_value_handling(self, mock_coordinator):
        """Test that None battery values are handled correctly."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Initial valid value
        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # None value
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = None
        value = sensor.native_value
        assert value is None
        # Last valid state should remain unchanged
        assert sensor._last_valid_state == 50.0


class TestMonotonicStateEdgeCases:
    """Test edge cases for monotonic state tracking."""

    def test_zero_to_positive(self, mock_coordinator):
        """Test transition from zero to positive value."""
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 0.0

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial zero value
        value = sensor.native_value
        assert value == 0.0
        assert sensor._last_valid_state == 0.0

        # Increase from zero
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 10.0
        value = sensor.native_value
        assert value == 10.0
        assert sensor._last_valid_state == 10.0

    def test_large_value_precision(self, mock_coordinator):
        """Test handling of large values with decimal precision."""
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 99999.99

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial large value
        value = sensor.native_value
        assert value == 99999.99
        assert sensor._last_valid_state == 99999.99

        # Slight decrease should be rejected
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 99999.98
        value = sensor.native_value
        assert value == 99999.99
        assert sensor._last_valid_state == 99999.99

        # Increase should be accepted
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 100000.01
        value = sensor.native_value
        assert value == 100000.01
        assert sensor._last_valid_state == 100000.01

    def test_multiple_consecutive_decreases(self, mock_coordinator):
        """Test multiple consecutive decrease attempts."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 100.0

        # Multiple decrease attempts
        for decreasing_value in [99.5, 99.0, 98.5, 98.0]:
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = (
                decreasing_value
            )
            value = sensor.native_value
            assert value == 100.0  # Should always maintain 100.0
            assert sensor._last_valid_state == 100.0

    def test_sensor_restart_resets_tracking(self, mock_coordinator):
        """Test that creating a new sensor instance resets tracking."""
        # First sensor instance
        sensor1 = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )
        _ = sensor1.native_value
        assert sensor1._last_valid_state == 100.0

        # Update coordinator data to lower value
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 50.0

        # New sensor instance (simulating restart)
        sensor2 = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # New instance should accept the current value without prior tracking
        value = sensor2.native_value
        assert value == 50.0
        assert sensor2._last_valid_state == 50.0


class TestDateBoundaryReset:
    """Test date boundary reset behavior for non-lifetime sensors."""

    def test_get_current_date_with_timezone(self, mock_coordinator):
        """Test _get_current_date function with timezone data."""
        current_date = _get_current_date(mock_coordinator)
        assert current_date is not None
        assert len(current_date) == 10  # YYYY-MM-DD format
        assert current_date.count("-") == 2

    def test_get_current_date_without_timezone(self):
        """Test _get_current_date function without timezone data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = {"devices": {}}

        current_date = _get_current_date(coordinator)
        assert current_date is not None  # Should fallback to UTC

    def test_lifetime_sensors_constant(self):
        """Test that LIFETIME_SENSORS contains expected sensors."""
        expected_lifetime = {
            "total_energy",
            "yield_lifetime",
            "discharging_lifetime",
            "charging_lifetime",
            "consumption_lifetime",
            "grid_export_lifetime",
            "grid_import_lifetime",
            "cycle_count",
        }
        assert LIFETIME_SENSORS == expected_lifetime

    def test_daily_sensor_reset_at_date_boundary(self, mock_coordinator):
        """Test that daily sensors force reset to 0 when date changes."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        # Initial value on day 1
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 10.0
            assert sensor._last_valid_state == 10.0
            assert sensor._last_update_date == "2025-01-19"

            # Value increases during day 1
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 15.0
            value = sensor.native_value
            assert value == 15.0
            assert sensor._last_valid_state == 15.0

            # Date changes to day 2 - forces reset to 0 even if API returns old value
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 15.0  # API stale data
            value = sensor.native_value
            assert value == 0.0  # Should force reset to 0 at date boundary
            assert sensor._last_valid_state == 0.0
            assert sensor._last_update_date == "2025-01-20"

    def test_daily_sensor_forced_reset_then_accumulates(self, mock_coordinator):
        """Test that daily sensors force reset to 0, then accumulate from API values."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="yield",
            device_type="inverter",
        )

        # Initial value on day 1
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 25.0
            assert sensor._last_valid_state == 25.0

            # Value increases during day 1
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["yield"] = 50.0
            value = sensor.native_value
            assert value == 50.0

            # Date changes to day 2, forces reset to 0 (even if API says 50.0)
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["yield"] = 50.0  # API stale
            value = sensor.native_value
            assert value == 0.0  # Should force reset to 0 at date boundary
            assert sensor._last_valid_state == 0.0

            # Next update on day 2, API sends current value
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["yield"] = 2.5
            value = sensor.native_value
            assert value == 2.5  # Should accept new accumulation
            assert sensor._last_valid_state == 2.5

    def test_lifetime_sensor_never_resets_at_date_boundary(self, mock_coordinator):
        """Test that lifetime sensors never reset, even at date boundary."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial value on day 1
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 5000.0
            assert sensor._last_valid_state == 5000.0

            # Value increases during day 1
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption_lifetime"] = 5100.0
            value = sensor.native_value
            assert value == 5100.0

            # Date changes to day 2, but lifetime value tries to decrease
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption_lifetime"] = 5050.0
            value = sensor.native_value
            assert value == 5100.0  # Should NOT allow reset for lifetime sensors
            assert sensor._last_valid_state == 5100.0

    def test_daily_sensor_manual_reset_to_zero(self, mock_coordinator):
        """Test that daily sensors can reset to 0 manually (same day)."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        # Initial value
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 10.0
            assert sensor._last_valid_state == 10.0

            # Manual reset to 0 (same day)
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 0.0
            value = sensor.native_value
            assert value == 0.0  # Should allow reset to 0 for non-lifetime
            assert sensor._last_valid_state == 0.0

    def test_daily_sensor_prevents_non_zero_decrease_same_day(self, mock_coordinator):
        """Test that daily sensors prevent non-zero decreases on same day."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        # Initial value
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 10.0
            assert sensor._last_valid_state == 10.0

            # Attempt non-zero decrease on same day (should be rejected)
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 8.5
            value = sensor.native_value
            assert value == 10.0  # Should maintain previous value
            assert sensor._last_valid_state == 10.0

    def test_battery_cycle_count_never_resets(self, mock_coordinator):
        """Test that battery cycle count (lifetime) never resets."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        # Initial value on day 1
        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            mock_date.return_value = "2025-01-19"
            value = sensor.native_value
            assert value == 50.0
            assert sensor._last_valid_state == 50.0

            # Increase during day 1
            mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"]["cycle_count"] = 55.0
            value = sensor.native_value
            assert value == 55.0

            # Date changes to day 2, cycle count tries to decrease
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"]["cycle_count"] = 52.0
            value = sensor.native_value
            assert value == 55.0  # Should NOT allow reset for cycle count
            assert sensor._last_valid_state == 55.0

    def test_multiple_date_boundaries(self, mock_coordinator):
        """Test sensor behavior across multiple date boundaries."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            # Day 1: Initial value
            mock_date.return_value = "2025-01-19"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 10.0
            assert sensor.native_value == 10.0

            # Day 1: Increases
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 20.0
            assert sensor.native_value == 20.0

            # Day 2: Reset to 0
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 20.0
            assert sensor.native_value == 0.0

            # Day 2: New accumulation
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 5.0
            assert sensor.native_value == 5.0

            # Day 3: Reset to 0 again
            mock_date.return_value = "2025-01-21"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 5.0
            assert sensor.native_value == 0.0

    def test_date_boundary_with_api_already_reset(self, mock_coordinator):
        """Test that if API already reset to 0, we handle it correctly."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            # Day 1
            mock_date.return_value = "2025-01-19"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 10.0
            assert sensor.native_value == 10.0

            # Day 2: API already sent 0
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 0.0
            assert sensor.native_value == 0.0  # Should still work correctly

    def test_first_reading_after_date_boundary(self, mock_coordinator):
        """Test first reading after midnight is 0, subsequent readings accumulate."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            # Day 1: Build up value
            mock_date.return_value = "2025-01-19"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 25.0
            assert sensor.native_value == 25.0

            # Day 2: First reading at 00:01 - forced to 0
            mock_date.return_value = "2025-01-20"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 25.0
            assert sensor.native_value == 0.0

            # Day 2: Reading at 06:00 - API has accumulated 3.0
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 3.0
            assert sensor.native_value == 3.0

            # Day 2: Reading at 12:00 - API has accumulated 12.5
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 12.5
            assert sensor.native_value == 12.5

            # Day 2: Reading at 18:00 - API has accumulated 18.0
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 18.0
            assert sensor.native_value == 18.0

    def test_timezone_changes_dont_trigger_reset(self, mock_coordinator):
        """Test that None timezone values don't cause spurious resets."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        with patch("custom_components.eg4_web_monitor.sensor._get_current_date") as mock_date:
            # Normal operation with timezone
            mock_date.return_value = "2025-01-19"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 10.0
            assert sensor.native_value == 10.0

            # Timezone info temporarily unavailable (returns None)
            mock_date.return_value = None
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 15.0
            assert sensor.native_value == 15.0  # Should still accept increases

            # Timezone info back
            mock_date.return_value = "2025-01-19"
            mock_coordinator.data["devices"]["1234567890"]["sensors"]["daily_energy"] = 20.0
            assert sensor.native_value == 20.0  # Should continue normally
