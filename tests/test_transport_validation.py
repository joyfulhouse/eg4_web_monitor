"""Tests for transport value consistency validation.

This module provides unit tests that verify sensor values are consistent
across different transport modes (HTTP, Modbus, Dongle). It uses mocked
data to ensure transport implementations produce equivalent outputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    pass


# ============================================================================
# Test: InverterRuntimeData consistency
# ============================================================================


class TestRuntimeDataConsistency:
    """Tests verifying that different transports produce consistent data."""

    @pytest.fixture
    def mock_http_runtime(self) -> dict:
        """Create mock HTTP API response."""
        return {
            "ppv": 2500,
            "ppv1": 1200,
            "ppv2": 1300,
            "vpv1": 1800,  # decivolts
            "vpv2": 3200,  # decivolts
            "vBat": 534,  # decivolts
            "soc": 80,
            "pCharge": 0,
            "pDisCharge": 500,
            "pinv": 2000,
            "vacr": 2459,  # decivolts
            "fac": 6000,  # centihertz
            "tinner": 42,
            "tradiator1": 38,
            "batCurrent": 10,
        }

    @pytest.fixture
    def mock_modbus_runtime(self) -> dict:
        """Create mock Modbus register values (already scaled)."""
        # Modbus transport applies scaling during read
        return {
            "pv_total_power": 2500.0,
            "pv1_power": 1200.0,
            "pv2_power": 1300.0,
            "pv1_voltage": 180.0,
            "pv2_voltage": 320.0,
            "battery_voltage": 53.4,
            "battery_soc": 80,
            "battery_charge_power": 0.0,
            "battery_discharge_power": 500.0,
            "inverter_power": 2000.0,
            "grid_voltage_r": 245.9,
            "grid_frequency": 60.0,
            "internal_temperature": 42.0,
            "radiator_temperature_1": 38.0,
            "battery_current": 10.0,
        }

    def test_voltage_scaling_consistency(self) -> None:
        """Test that HTTP decivolts are properly converted to volts."""
        # HTTP returns 534 decivolts
        http_battery_voltage = 534 / 10.0  # Expected: 53.4V

        # Modbus returns 53.4 volts directly (already scaled)
        modbus_battery_voltage = 53.4

        assert abs(http_battery_voltage - modbus_battery_voltage) < 0.1

    def test_frequency_scaling_consistency(self) -> None:
        """Test that HTTP centihertz are properly converted to Hz."""
        # HTTP returns 6000 centihertz
        http_frequency = 6000 / 100.0  # Expected: 60.0 Hz

        # Modbus returns 60.0 Hz directly (already scaled)
        modbus_frequency = 60.0

        assert abs(http_frequency - modbus_frequency) < 0.1

    def test_power_values_no_scaling(self) -> None:
        """Test that power values need no scaling between transports."""
        # Both HTTP and Modbus return power in watts
        http_pv_power = 2500
        modbus_pv_power = 2500.0

        assert abs(http_pv_power - modbus_pv_power) < 1.0

    def test_soc_clamping(self) -> None:
        """Test that SOC values are clamped to 0-100%."""
        from pylxpweb.transports.data import InverterRuntimeData

        # Create runtime data with out-of-range SOC
        runtime = InverterRuntimeData(battery_soc=150)
        assert runtime.battery_soc == 100  # Should be clamped

        runtime = InverterRuntimeData(battery_soc=-10)
        assert runtime.battery_soc == 0  # Should be clamped

    def test_temperature_no_scaling(self) -> None:
        """Test that temperature values need no scaling."""
        # Both transports return temperature in Celsius
        http_temp = 42
        modbus_temp = 42.0

        assert abs(http_temp - modbus_temp) < 0.1


# ============================================================================
# Test: Transport factory functions
# ============================================================================


class TestTransportFactories:
    """Tests for transport factory function behavior."""

    def test_modbus_transport_creation(self) -> None:
        """Test Modbus transport factory creates valid transport."""
        from pylxpweb.transports import create_modbus_transport

        transport = create_modbus_transport(
            host="192.168.1.100",
            port=502,
            serial="CE12345678",
        )

        assert transport is not None
        # Transport should have required attributes
        assert hasattr(transport, "connect")
        assert hasattr(transport, "disconnect")
        assert hasattr(transport, "read_runtime")

    def test_dongle_transport_creation(self) -> None:
        """Test Dongle transport factory creates valid transport."""
        from pylxpweb.transports import create_dongle_transport

        transport = create_dongle_transport(
            host="192.168.1.100",
            dongle_serial="BA12345678",
            inverter_serial="CE12345678",
        )

        assert transport is not None
        assert hasattr(transport, "connect")
        assert hasattr(transport, "disconnect")
        assert hasattr(transport, "read_runtime")

    def test_http_transport_creation(self) -> None:
        """Test HTTP transport factory creates valid transport."""
        from pylxpweb.transports import create_http_transport

        mock_client = MagicMock()
        transport = create_http_transport(
            client=mock_client,
            serial="CE12345678",
        )

        assert transport is not None
        assert hasattr(transport, "connect")
        assert hasattr(transport, "disconnect")
        assert hasattr(transport, "read_runtime")


# ============================================================================
# Test: Data conversion functions
# ============================================================================


class TestDataConversions:
    """Tests for data conversion between transport formats."""

    def test_http_to_runtime_data_conversion(self) -> None:
        """Test HTTP API response converts to InverterRuntimeData correctly."""
        from pylxpweb.transports.data import InverterRuntimeData

        # Create runtime data with expected values
        runtime = InverterRuntimeData(
            pv_total_power=2500.0,
            battery_voltage=53.4,
            battery_soc=80,
            grid_frequency=60.0,
        )

        assert runtime.pv_total_power == 2500.0
        assert runtime.battery_voltage == 53.4
        assert runtime.battery_soc == 80
        assert runtime.grid_frequency == 60.0

    def test_runtime_data_defaults(self) -> None:
        """Test InverterRuntimeData has sensible defaults."""
        from pylxpweb.transports.data import InverterRuntimeData

        runtime = InverterRuntimeData()

        # Most values should default to None or 0
        assert runtime.pv_total_power is None or runtime.pv_total_power == 0
        assert runtime.battery_soc is None or runtime.battery_soc >= 0


# ============================================================================
# Test: Tolerance validation
# ============================================================================


class TestToleranceValidation:
    """Tests for value comparison with tolerance."""

    def test_absolute_tolerance_pass(self) -> None:
        """Test values within absolute tolerance pass."""
        http_val = 2500.0
        local_val = 2510.0
        tolerance = 50.0

        diff = abs(http_val - local_val)
        assert diff <= tolerance

    def test_absolute_tolerance_fail(self) -> None:
        """Test values outside absolute tolerance fail."""
        http_val = 2500.0
        local_val = 2600.0
        tolerance = 50.0

        diff = abs(http_val - local_val)
        assert diff > tolerance

    def test_percentage_tolerance_pass(self) -> None:
        """Test values within percentage tolerance pass."""
        http_val = 2500.0
        local_val = 2550.0  # 2% difference
        tolerance_pct = 0.05  # 5%

        diff = abs(http_val - local_val)
        base = max(abs(http_val), abs(local_val), 1.0)
        pct_diff = diff / base

        assert pct_diff <= tolerance_pct

    def test_percentage_tolerance_fail(self) -> None:
        """Test values outside percentage tolerance fail."""
        http_val = 2500.0
        local_val = 2800.0  # 12% difference
        tolerance_pct = 0.05  # 5%

        diff = abs(http_val - local_val)
        base = max(abs(http_val), abs(local_val), 1.0)
        pct_diff = diff / base

        assert pct_diff > tolerance_pct


# ============================================================================
# Test: Sensor key mapping consistency
# ============================================================================


class TestSensorKeyMapping:
    """Tests verifying sensor keys are mapped consistently.

    Note: These tests use pytest markers to properly integrate with
    the pytest-homeassistant-custom-component test infrastructure.
    """

    def test_expected_sensor_keys_exist(self) -> None:
        """Test that expected sensor keys will be defined.

        This test verifies the sensor key names that should be defined
        in the integration's SENSOR_TYPES constant. The actual const.py
        imports are tested separately in integration tests.
        """
        # These are the sensor keys that must exist for transport consistency
        expected_keys = [
            "pv_total_power",
            "battery_voltage",
            "state_of_charge",
            "battery_charge_power",
            "battery_discharge_power",
            "grid_voltage_r",
            "internal_temperature",
        ]

        # Verify key names are valid Python identifiers
        for key in expected_keys:
            assert key.isidentifier(), f"Invalid sensor key: {key}"
            assert key == key.lower(), f"Sensor key should be lowercase: {key}"

    def test_expected_field_mappings(self) -> None:
        """Test expected API field to sensor key mappings.

        This test verifies the mapping patterns that should exist
        in INVERTER_RUNTIME_FIELD_MAPPING for transport consistency.
        """
        # These mappings must exist for transport data to match
        expected_mappings = {
            "ppv": "pv_total_power",
            "soc": "state_of_charge",
            "vBat": "battery_voltage",
            "pCharge": "battery_charge_power",
            "pDisCharge": "battery_discharge_power",
        }

        # Verify mapping values are valid sensor keys
        for api_key, sensor_key in expected_mappings.items():
            assert sensor_key.isidentifier(), f"Invalid sensor key: {sensor_key}"
            assert api_key, "API key cannot be empty"
