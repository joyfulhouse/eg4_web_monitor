"""Unit tests for number entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.eg4_web_monitor.number import (
    SystemChargeSOCLimitNumber,
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
                    "parameters": {"GRID_MAX_CHARGE_POWER": 5000}
                }
            }
        }

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 5000

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
        coordinator.data = {"devices": {"1234567890": {"parameters": {}, "model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_set_native_value(6000)

        coordinator.api.write_parameters.assert_called_once_with(
            "1234567890", {"GRID_MAX_CHARGE_POWER": 6000}
        )
        coordinator.async_request_refresh.assert_called_once()


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
        coordinator.data = {"devices": {"1234567890": {"parameters": {}, "model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = PVChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_set_native_value(7000)

        coordinator.api.write_parameters.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()


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
                    "parameters": {"GRID_PEAK_SHAVING_POWER": 5000}
                }
            }
        }

        entity = GridPeakShavingPowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 5000

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting peak shaving power."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"parameters": {}, "model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = GridPeakShavingPowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_set_native_value(8000)

        coordinator.api.write_parameters.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()


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
                    "parameters": {"AC_CHARGE_SOC_LIMIT": 90}
                }
            }
        }

        entity = ACChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 90

    @pytest.mark.asyncio
    async def test_async_set_native_value_updates_all_inverters(self):
        """Test setting SOC limit updates all inverters in station."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {"parameters": {}, "type": "inverter", "model": "FlexBOSS21"},
                "0987654321": {"parameters": {}, "type": "inverter", "model": "FlexBOSS21"},
                "gridboss123": {"parameters": {}, "type": "gridboss", "model": "GridBOSS"},
            }
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = ACChargeSOCLimitNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_set_native_value(85)

        # Should update both inverters, not the gridboss
        assert coordinator.api.write_parameters.call_count == 2
        calls = coordinator.api.write_parameters.call_args_list
        serials = [call[0][0] for call in calls]
        assert "1234567890" in serials
        assert "0987654321" in serials
        assert "gridboss123" not in serials


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
                    "parameters": {"ON_GRID_EOD_SOC": 20}
                }
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
                    "parameters": {"OFF_GRID_EOD_SOC": 10}
                }
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
        coordinator.data = {"devices": {"1234567890": {"parameters": {}, "model": "FlexBOSS21"}}}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = OffGridSOCCutoffNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_set_native_value(15)

        coordinator.api.write_parameters.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()
