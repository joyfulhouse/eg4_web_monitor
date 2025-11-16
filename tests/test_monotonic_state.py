"""Test monotonic state tracking for total_increasing sensors."""

import pytest
from unittest.mock import MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.eg4_web_monitor.sensor import (
    EG4InverterSensor,
    EG4BatterySensor,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with test data."""
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = {
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "18kPV",
                "sensors": {
                    "consumption": 100.0,
                    "consumption_lifetime": 5000.0,
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
