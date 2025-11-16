"""Unit tests for switch entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.eg4_web_monitor.switch import (
    EG4QuickChargeSwitch,
    EG4BatteryBackupSwitch,
    EG4WorkingModeSwitch,
)


class TestEG4QuickChargeSwitch:
    """Test EG4QuickChargeSwitch entity logic."""

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
        coordinator.get_device_info.return_value = {
            "identifiers": {("eg4_web_monitor", "1234567890")},
            "name": "FlexBOSS21 1234567890",
        }

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity._serial == "1234567890"
        assert entity._attr_name == "Quick Charge"

    def test_is_on_when_enabled(self):
        """Test switch is on when quick charge is enabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "quick_charge_status": {"status": True}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.is_on is True

    def test_is_on_when_disabled(self):
        """Test switch is off when quick charge is disabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "quick_charge_status": {"status": False}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.is_on is False

    def test_is_on_missing_data(self):
        """Test switch state when data is missing."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {}}
        coordinator.get_device_info.return_value = {}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test turning on quick charge."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.enable_quick_charge = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_turn_on()

        coordinator.api.enable_quick_charge.assert_called_once_with("1234567890")
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test turning off quick charge."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.disable_quick_charge = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_turn_off()

        coordinator.api.disable_quick_charge.assert_called_once_with("1234567890")
        coordinator.async_request_refresh.assert_called_once()


class TestEG4BatteryBackupSwitch:
    """Test EG4BatteryBackupSwitch entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity._serial == "1234567890"
        assert entity._attr_name == "Battery Backup"

    def test_is_on_when_enabled(self):
        """Test switch is on when battery backup is enabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "battery_backup_status": {"enabled": True}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.is_on is True

    def test_is_on_when_disabled(self):
        """Test switch is off when battery backup is disabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "battery_backup_status": {"enabled": False}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test turning on battery backup."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_turn_on()

        coordinator.api.write_parameters.assert_called_once_with(
            "1234567890", {"FUNC_EPS_EN": 1}
        )
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test turning off battery backup."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
        )

        await entity.async_turn_off()

        coordinator.api.write_parameters.assert_called_once_with(
            "1234567890", {"FUNC_EPS_EN": 0}
        )


class TestEG4WorkingModeSwitch:
    """Test EG4WorkingModeSwitch entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_name="Self Use",
            mode_value=0,
        )

        assert entity._serial == "1234567890"
        assert entity._mode_name == "Self Use"
        assert entity._mode_value == 0

    def test_is_on_when_mode_active(self):
        """Test switch is on when this mode is active."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "parameters": {"WORK_MODE": 0}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_name="Self Use",
            mode_value=0,
        )

        assert entity.is_on is True

    def test_is_on_when_different_mode_active(self):
        """Test switch is off when different mode is active."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "parameters": {"WORK_MODE": 1}
                }
            }
        }
        coordinator.get_device_info.return_value = {}

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_name="Self Use",
            mode_value=0,
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test switching to this mode."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"parameters": {}}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_name="Selling First",
            mode_value=1,
        )

        await entity.async_turn_on()

        coordinator.api.write_parameters.assert_called_once_with(
            "1234567890", {"WORK_MODE": 1}
        )
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off_does_nothing(self):
        """Test turning off does nothing (can't unset a mode)."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        coordinator.get_device_info.return_value = {}
        coordinator.api = MagicMock()
        coordinator.api.write_parameters = AsyncMock()

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            mode_name="Self Use",
            mode_value=0,
        )

        await entity.async_turn_off()

        # Should not call write_parameters
        coordinator.api.write_parameters.assert_not_called()
