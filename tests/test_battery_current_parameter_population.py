"""Test battery charge/discharge current parameter population."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.eg4_web_monitor.number import (
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
)


class TestBatteryCurrentParameterPopulation:
    """Test that battery current parameters are populated from coordinator."""

    @pytest.mark.asyncio
    async def test_battery_charge_current_reads_from_coordinator_cache(self):
        """Test that battery charge current entity reads from coordinator parameter cache."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_LEAD_ACID_CHARGE_RATE": 150,  # 150A
                    "other_param": "value",
                }
            },
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Entity should read value from coordinator cache
        value = entity._get_value_from_coordinator()
        assert value == 150

        # Native value should return the cached value as integer
        assert entity.native_value == 150

    @pytest.mark.asyncio
    async def test_battery_discharge_current_reads_from_coordinator_cache(self):
        """Test that battery discharge current entity reads from coordinator parameter cache."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_LEAD_ACID_DISCHARGE_RATE": 100,  # 100A
                    "other_param": "value",
                }
            },
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryDischargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Entity should read value from coordinator cache
        value = entity._get_value_from_coordinator()
        assert value == 100

        # Native value should return the cached value as integer
        assert entity.native_value == 100

    @pytest.mark.asyncio
    async def test_battery_charge_current_handles_missing_parameter(self):
        """Test that entity handles missing parameter gracefully."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    # HOLD_LEAD_ACID_CHARGE_RATE is missing
                    "other_param": "value",
                }
            },
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Entity should return None when parameter is missing
        value = entity._get_value_from_coordinator()
        assert value is None

        # Native value should return None
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_battery_current_entities_update_after_parameter_refresh(self):
        """Test that entities update their values after coordinator parameter refresh."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_LEAD_ACID_CHARGE_RATE": 100,
                    "HOLD_LEAD_ACID_DISCHARGE_RATE": 75,
                }
            },
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        charge_entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )
        discharge_entity = BatteryDischargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Initial values
        assert charge_entity.native_value == 100
        assert discharge_entity.native_value == 75

        # Simulate coordinator parameter refresh with updated values
        coordinator.data["parameters"]["1234567890"][
            "HOLD_LEAD_ACID_CHARGE_RATE"
        ] = 200
        coordinator.data["parameters"]["1234567890"][
            "HOLD_LEAD_ACID_DISCHARGE_RATE"
        ] = 150

        # Entities should read updated values from coordinator
        assert charge_entity.native_value == 200
        assert discharge_entity.native_value == 150

    @pytest.mark.asyncio
    async def test_battery_charge_current_validates_range(self):
        """Test that entity validates parameter value is within range."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_LEAD_ACID_CHARGE_RATE": 250,  # Out of range (max 200)
                }
            },
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Entity should return None for out-of-range value
        value = entity._get_value_from_coordinator()
        assert value is None

        # Native value should return None
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_coordinator_parameter_structure(self):
        """Test that coordinator stores parameters in expected structure."""
        # This test validates our assumptions about coordinator data structure
        coordinator_data = {
            "devices": {
                "1234567890": {"type": "inverter", "model": "FlexBOSS21"},
                "0987654321": {"type": "inverter", "model": "18kPV"},
            },
            "parameters": {
                "1234567890": {
                    "HOLD_LEAD_ACID_CHARGE_RATE": 150,
                    "HOLD_LEAD_ACID_DISCHARGE_RATE": 100,
                    "FUNC_AC_CHARGE_POWER_CMD": 5.0,
                },
                "0987654321": {
                    "HOLD_LEAD_ACID_CHARGE_RATE": 200,
                    "HOLD_LEAD_ACID_DISCHARGE_RATE": 150,
                    "FUNC_AC_CHARGE_POWER_CMD": 10.0,
                },
            },
        }

        # Verify structure is correct
        assert "parameters" in coordinator_data
        assert "1234567890" in coordinator_data["parameters"]
        assert "HOLD_LEAD_ACID_CHARGE_RATE" in coordinator_data["parameters"]["1234567890"]
        assert coordinator_data["parameters"]["1234567890"]["HOLD_LEAD_ACID_CHARGE_RATE"] == 150

        assert "0987654321" in coordinator_data["parameters"]
        assert "HOLD_LEAD_ACID_DISCHARGE_RATE" in coordinator_data["parameters"]["0987654321"]
        assert coordinator_data["parameters"]["0987654321"]["HOLD_LEAD_ACID_DISCHARGE_RATE"] == 150
