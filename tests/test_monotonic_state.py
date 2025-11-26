"""Test monotonic state tracking for lifetime total_increasing sensors.

The EG4 Web Monitor integration only applies monotonic tracking to LIFETIME sensors
(e.g., yield_lifetime, consumption_lifetime, cycle_count) to protect against rare
API glitches that might report temporary decreases.

For daily/periodic sensors (e.g., yield, consumption, daily_energy), we report
exactly what the API returns and let Home Assistant's total_increasing state class
handle resets naturally. This is the recommended approach per HA documentation:
https://developers.home-assistant.io/blog/2021/08/16/state_class_total/
"""

import pytest
from unittest.mock import MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.eg4_web_monitor.sensor import (
    EG4InverterSensor,
    EG4BatterySensor,
)
from custom_components.eg4_web_monitor.const import LIFETIME_SENSOR_KEYS


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
                    # Daily sensors (NOT protected - HA handles resets)
                    "consumption": 100.0,
                    "daily_energy": 10.0,
                    "yield": 25.0,
                    # Lifetime sensors (protected from API glitches)
                    "consumption_lifetime": 5000.0,
                    "yield_lifetime": 8000.0,
                },
                "batteries": {
                    "battery_1": {
                        "cycle_count": 50.0,  # Lifetime sensor
                        "battery_real_voltage": 52.0,
                    }
                },
            }
        },
    }
    coordinator.last_update_success = True
    return coordinator


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


class TestLifetimeSensorsConstant:
    """Test that LIFETIME_SENSOR_KEYS constant is correctly defined."""

    def test_lifetime_sensors_contains_expected_values(self):
        """Test that LIFETIME_SENSOR_KEYS contains all expected lifetime sensors."""
        expected_lifetime = {
            "total_energy",
            "yield_lifetime",
            "discharging_lifetime",
            "charging_lifetime",
            "consumption_lifetime",
            "grid_export_lifetime",
            "grid_import_lifetime",
            "cycle_count",
            "battery_charge_lifetime",
            "battery_discharge_lifetime",
        }
        assert LIFETIME_SENSOR_KEYS == expected_lifetime


class TestLifetimeSensorMonotonicTracking:
    """Test that lifetime sensors are protected from decreases."""

    def test_lifetime_sensor_initial_value_tracking(self, mock_coordinator):
        """Test that initial lifetime value is tracked correctly."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        value = sensor.native_value
        assert value == 5000.0
        assert sensor._last_valid_state == 5000.0

    def test_lifetime_sensor_increasing_value_accepted(self, mock_coordinator):
        """Test that increasing lifetime values are accepted."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # Update to higher value
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 5100.0
        value = sensor.native_value
        assert value == 5100.0
        assert sensor._last_valid_state == 5100.0

    def test_lifetime_sensor_decrease_rejected(self, mock_coordinator):
        """Test that decreasing lifetime values are rejected (API glitch protection)."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # Attempt to decrease (API glitch)
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 4999.9
        value = sensor.native_value
        assert value == 5000.0  # Should maintain previous value
        assert sensor._last_valid_state == 5000.0

    def test_lifetime_sensor_slight_decrease_rejected(self, mock_coordinator):
        """Test that even slight lifetime decreases are rejected."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Set initial value
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

    def test_lifetime_sensor_recovery_after_glitch(self, mock_coordinator):
        """Test that lifetime sensor recovers correctly after temporary decrease."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # Temporary decrease (API glitch)
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 4900.0
        value = sensor.native_value
        assert value == 5000.0  # Should maintain previous value

        # Recovery to higher value
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 5200.0
        value = sensor.native_value
        assert value == 5200.0
        assert sensor._last_valid_state == 5200.0

    def test_lifetime_sensor_multiple_decreases_rejected(self, mock_coordinator):
        """Test multiple consecutive decrease attempts on lifetime sensor."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # Multiple decrease attempts
        for decreasing_value in [4999.5, 4999.0, 4998.5, 4998.0]:
            mock_coordinator.data["devices"]["1234567890"]["sensors"][
                "consumption_lifetime"
            ] = decreasing_value
            value = sensor.native_value
            assert value == 5000.0  # Should always maintain 5000.0


class TestDailySensorNoTracking:
    """Test that daily sensors do NOT have monotonic tracking - HA handles resets."""

    def test_daily_sensor_no_tracking_initialized(self, mock_coordinator):
        """Test that daily sensors don't track state (no _last_valid_state set)."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",  # Daily sensor
            device_type="inverter",
        )

        value = sensor.native_value
        assert value == 100.0
        # Daily sensors should NOT track state
        assert sensor._last_valid_state is None

    def test_daily_sensor_decrease_allowed(self, mock_coordinator):
        """Test that daily sensors allow decreases (API reset is legitimate)."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption",
            device_type="inverter",
        )

        # Initial value
        value = sensor.native_value
        assert value == 100.0

        # Decrease should be allowed for daily sensors (API reset)
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["consumption"] = 50.0
        value = sensor.native_value
        assert value == 50.0  # Should return the actual API value

    def test_daily_sensor_reset_to_zero_allowed(self, mock_coordinator):
        """Test that daily sensors can reset to 0 (midnight reset)."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="yield",
            device_type="inverter",
        )

        # Initial value
        value = sensor.native_value
        assert value == 25.0

        # Reset to 0 (midnight) should be allowed
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["yield"] = 0.0
        value = sensor.native_value
        assert value == 0.0

        # Then accumulation continues
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["yield"] = 5.0
        value = sensor.native_value
        assert value == 5.0

    def test_daily_sensor_reports_api_values_directly(self, mock_coordinator):
        """Test that daily sensors report whatever the API returns."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="daily_energy",
            device_type="inverter",
        )

        # Sequence of API values (simulating normal day operation)
        api_values = [10.0, 15.0, 12.0, 0.0, 3.0, 8.0]  # Note: includes decrease!

        for expected_value in api_values:
            mock_coordinator.data["devices"]["1234567890"]["sensors"][
                "daily_energy"
            ] = expected_value
            value = sensor.native_value
            assert value == expected_value


class TestNonTotalIncreasingSensors:
    """Test that non-total_increasing sensors are not affected."""

    def test_measurement_sensor_not_affected(self, mock_coordinator):
        """Test that measurement sensors are not affected by any tracking."""
        # Add a measurement sensor (not total_increasing)
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["power"] = 1000.0

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="power",
            device_type="inverter",
        )

        # Initial value
        value = sensor.native_value
        assert value == 1000.0
        assert sensor._last_valid_state is None  # Should not track

        # Decrease should be allowed
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["power"] = 500.0
        value = sensor.native_value
        assert value == 500.0


class TestNoneAndInvalidValues:
    """Test handling of None and invalid values."""

    def test_lifetime_sensor_none_value_handling(self, mock_coordinator):
        """Test that None values are handled correctly for lifetime sensors."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial valid value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # None value
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = None
        value = sensor.native_value
        assert value is None
        # Last valid state should remain unchanged
        assert sensor._last_valid_state == 5000.0

    def test_lifetime_sensor_invalid_type_handling(self, mock_coordinator):
        """Test that invalid types are handled gracefully."""
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial valid value
        _ = sensor.native_value
        assert sensor._last_valid_state == 5000.0

        # Invalid string that can't be converted
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = "invalid"
        value = sensor.native_value
        assert value == "invalid"  # Should return raw value
        # Last valid state should remain unchanged
        assert sensor._last_valid_state == 5000.0


class TestSensorRestart:
    """Test behavior when sensor is recreated (e.g., HA restart)."""

    def test_sensor_restart_resets_tracking(self, mock_coordinator):
        """Test that creating a new sensor instance resets tracking."""
        # First sensor instance
        sensor1 = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )
        _ = sensor1.native_value
        assert sensor1._last_valid_state == 5000.0

        # Update coordinator data to lower value
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 4500.0

        # New sensor instance (simulating restart)
        sensor2 = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # New instance should accept the current value (no prior tracking)
        value = sensor2.native_value
        assert value == 4500.0
        assert sensor2._last_valid_state == 4500.0


class TestBatterySensorLifetimeTracking:
    """Test monotonic tracking for battery lifetime sensors (cycle_count)."""

    def test_battery_cycle_count_initial_tracking(self, mock_coordinator):
        """Test that initial battery cycle count is tracked."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",  # Lifetime sensor
        )

        value = sensor.native_value
        assert value == 50.0
        assert sensor._last_valid_state == 50.0

    def test_battery_cycle_count_increase_accepted(self, mock_coordinator):
        """Test that increasing cycle count is accepted."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # Increase
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 55.0
        value = sensor.native_value
        assert value == 55.0
        assert sensor._last_valid_state == 55.0

    def test_battery_cycle_count_decrease_rejected(self, mock_coordinator):
        """Test that decreasing cycle count is rejected (API glitch)."""
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="cycle_count",
        )

        _ = sensor.native_value
        assert sensor._last_valid_state == 50.0

        # Attempt to decrease
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "cycle_count"
        ] = 49.0
        value = sensor.native_value
        assert value == 50.0  # Should maintain previous
        assert sensor._last_valid_state == 50.0

    def test_battery_non_lifetime_sensor_allows_decrease(self, mock_coordinator):
        """Test that non-lifetime battery sensors allow decreases."""
        # battery_real_voltage is not a lifetime sensor
        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="battery_1",
            sensor_key="battery_real_voltage",
        )

        value = sensor.native_value
        assert value == 52.0
        assert sensor._last_valid_state is None  # Not tracked

        # Decrease should be allowed
        mock_coordinator.data["devices"]["1234567890"]["batteries"]["battery_1"][
            "battery_real_voltage"
        ] = 48.0
        value = sensor.native_value
        assert value == 48.0


class TestEdgeCases:
    """Test edge cases for monotonic state tracking."""

    def test_lifetime_sensor_zero_to_positive(self, mock_coordinator):
        """Test transition from zero to positive value for lifetime sensor."""
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 0.0

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="consumption_lifetime",
            device_type="inverter",
        )

        # Initial zero value
        value = sensor.native_value
        assert value == 0.0
        assert sensor._last_valid_state == 0.0

        # Increase from zero
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 10.0
        value = sensor.native_value
        assert value == 10.0
        assert sensor._last_valid_state == 10.0

    def test_lifetime_sensor_large_value_precision(self, mock_coordinator):
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

        # Increase should be accepted
        mock_coordinator.data["devices"]["1234567890"]["sensors"][
            "consumption_lifetime"
        ] = 100000.01
        value = sensor.native_value
        assert value == 100000.01
        assert sensor._last_valid_state == 100000.01
