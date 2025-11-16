"""Unit tests for number entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.eg4_web_monitor.number import (
    ACChargePowerNumber,
    PVChargePowerNumber,
    GridPeakShavingPowerNumber,
    ACChargeSOCLimitNumber,
    OnGridSOCCutoffNumber,
    OffGridSOCCutoffNumber,
)


class TestACChargePowerNumber:
    """Test ACChargePowerNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                }
            }
        }

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.serial == "1234567890"
        assert "AC Charge Power" in entity._attr_name

    def test_native_value_from_coordinator(self):
        """Test getting current value from coordinator."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "model": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {"HOLD_AC_CHARGE_POWER_CMD": 5.0}
            }
        }

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 5

    def test_native_value_missing_data(self):
        """Test getting value when data is missing."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting new value."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.async_request_refresh = AsyncMock()

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock hass and async_write_ha_state to avoid HA instance requirement
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(6.0)

        # Just verify it was called, don't assert exact parameters
        coordinator.api.write_parameter.assert_called_once()
        # Note: async_request_refresh is not called directly by this method


class TestPVChargePowerNumber:
    """Test PVChargePowerNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = PVChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert "PV Charge Power" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting PV charge power value."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.async_request_refresh = AsyncMock()

        entity = PVChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock hass and async_write_ha_state to avoid HA instance requirement
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # PV charge power range is 0-15 kW
        await entity.async_set_native_value(10.0)

        coordinator.api.write_parameter.assert_called_once()


class TestGridPeakShavingPowerNumber:
    """Test GridPeakShavingPowerNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = GridPeakShavingPowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert "Peak Shaving" in entity._attr_name or "Grid Peak" in entity._attr_name

    def test_native_value(self):
        """Test getting peak shaving power value."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "model": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {"_12K_HOLD_GRID_PEAK_SHAVING_POWER": 5.0}
            }
        }

        entity = GridPeakShavingPowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 5.0

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting peak shaving power."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.async_request_refresh = AsyncMock()

        entity = GridPeakShavingPowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock hass and async_write_ha_state to avoid HA instance requirement
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(8.0)

        coordinator.api.write_parameter.assert_called_once()


class TestACChargeSOCLimitNumber:
    """Test ACChargeSOCLimitNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = ACChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert "SOC" in entity._attr_name

    def test_native_value(self):
        """Test getting AC charge SOC limit."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "model": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {"HOLD_AC_CHARGE_SOC_LIMIT": 90.0}
            }
        }

        entity = ACChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 90

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting SOC limit for this inverter."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {"type": "inverter", "model": "FlexBOSS21"},
                "0987654321": {"type": "inverter", "model": "FlexBOSS21"},
                "gridboss123": {"type": "gridboss", "model": "GridBOSS"},
            }
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.async_request_refresh = AsyncMock()

        entity = ACChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock hass and async_write_ha_state to avoid HA instance requirement
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(85)

        # Should write parameter to this inverter only
        assert coordinator.api.write_parameter.call_count == 1
        call_args = coordinator.api.write_parameter.call_args[1]
        assert call_args["inverter_sn"] == "1234567890"
        assert call_args["hold_param"] == "HOLD_AC_CHARGE_SOC_LIMIT"
        assert call_args["value_text"] == "85"


class TestOnGridSOCCutoffNumber:
    """Test OnGridSOCCutoffNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = OnGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert "Grid" in entity._attr_name

    def test_native_value(self):
        """Test getting on-grid SOC cutoff."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "model": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {"HOLD_DISCHG_CUT_OFF_SOC_EOD": 20.0}
            }
        }

        entity = OnGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 20


class TestOffGridSOCCutoffNumber:
    """Test OffGridSOCCutoffNumber entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}

        entity = OffGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert "Grid" in entity._attr_name

    def test_native_value(self):
        """Test getting off-grid SOC cutoff."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "model": "FlexBOSS21",
                }
            },
            "parameters": {
                "1234567890": {"HOLD_SOC_LOW_LIMIT_EPS_DISCHG": 10.0}
            }
        }

        entity = OffGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 10

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting off-grid SOC cutoff."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.async_request_refresh = AsyncMock()

        entity = OffGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Mock hass and async_write_ha_state to avoid HA instance requirement
        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(15)

        coordinator.api.write_parameter.assert_called_once()
