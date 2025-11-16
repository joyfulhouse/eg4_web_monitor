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
                }
            }
        }
        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
        }

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity._serial == "1234567890"

    def test_is_on_when_enabled(self):
        """Test switch is on when quick charge is enabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "quick_charge_status": {"hasUnclosedQuickChargeTask": True},
                }
            },
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity.is_on is True

    def test_is_on_when_disabled(self):
        """Test switch is off when quick charge is disabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "quick_charge_status": {"hasUnclosedQuickChargeTask": False},
                }
            },
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity.is_on is False

    def test_is_on_missing_data(self):
        """Test switch state when data is missing."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {}, "device_info": {}}
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test turning on quick charge."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        coordinator.api = MagicMock()
        coordinator.api.start_quick_charge = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        coordinator.api.start_quick_charge.assert_called_once_with("1234567890")
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test turning off quick charge."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        coordinator.api = MagicMock()
        coordinator.api.stop_quick_charge = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4QuickChargeSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        coordinator.api.stop_quick_charge.assert_called_once_with("1234567890")
        coordinator.async_request_refresh.assert_called_once()


class TestEG4BatteryBackupSwitch:
    """Test EG4BatteryBackupSwitch entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity._serial == "1234567890"

    def test_is_on_when_enabled(self):
        """Test switch is on when battery backup is enabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "battery_backup_status": {"enabled": True},
                }
            },
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity.is_on is True

    def test_is_on_when_disabled(self):
        """Test switch is off when battery backup is disabled."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "battery_backup_status": {"enabled": False},
                }
            },
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test turning on battery backup."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        coordinator.api = MagicMock()
        coordinator.api.enable_battery_backup = AsyncMock(return_value=True)
        coordinator.async_refresh_device_parameters = AsyncMock()
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        coordinator.api.enable_battery_backup.assert_called_once()
        coordinator.async_refresh_device_parameters.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test turning off battery backup."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
        }
        coordinator.api = MagicMock()
        coordinator.api.disable_battery_backup = AsyncMock(return_value=True)
        coordinator.async_refresh_device_parameters = AsyncMock()
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4BatteryBackupSwitch(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        coordinator.api.disable_battery_backup.assert_called_once()
        coordinator.async_refresh_device_parameters.assert_called_once()


class TestEG4WorkingModeSwitch:
    """Test EG4WorkingModeSwitch entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
            "parameters": {"1234567890": {}},
        }
        device_info = {"deviceTypeText4APP": "FlexBOSS21"}
        mode_config = {
            "name": "Self Use",
            "param": "FUNC_WORK_MODE",
            "value": 0,
            "entity_category": None,
        }

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            device_info=device_info,
            serial_number="1234567890",
            mode_config=mode_config,
        )

        assert entity._serial_number == "1234567890"
        assert entity._mode_config["name"] == "Self Use"
        assert entity._mode_config["value"] == 0

    def test_is_on_when_mode_active(self):
        """Test switch is on when this mode is active."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
            "parameters": {"1234567890": {"FUNC_WORK_MODE": 0}},
        }
        coordinator.get_working_mode_state = MagicMock(return_value=True)
        device_info = {"deviceTypeText4APP": "FlexBOSS21"}
        mode_config = {
            "name": "Self Use",
            "param": "FUNC_WORK_MODE",
            "value": 0,
            "entity_category": None,
        }

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            device_info=device_info,
            serial_number="1234567890",
            mode_config=mode_config,
        )

        assert entity.is_on is True

    def test_is_on_when_different_mode_active(self):
        """Test switch is off when different mode is active."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
            "parameters": {"1234567890": {"FUNC_WORK_MODE": 1}},
        }
        coordinator.get_working_mode_state = MagicMock(return_value=False)
        device_info = {"deviceTypeText4APP": "FlexBOSS21"}
        mode_config = {
            "name": "Self Use",
            "param": "FUNC_WORK_MODE",
            "value": 0,
            "entity_category": None,
        }

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            device_info=device_info,
            serial_number="1234567890",
            mode_config=mode_config,
        )

        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test switching to this mode."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
            "parameters": {"1234567890": {}},
        }
        coordinator.set_working_mode = AsyncMock(return_value=True)
        device_info = {"deviceTypeText4APP": "FlexBOSS21"}
        mode_config = {
            "name": "Selling First",
            "param": "FUNC_WORK_MODE",
            "value": 1,
            "entity_category": None,
        }

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            device_info=device_info,
            serial_number="1234567890",
            mode_config=mode_config,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        coordinator.set_working_mode.assert_called_once()


    @pytest.mark.asyncio
    async def test_async_turn_off_does_nothing(self):
        """Test turning off does nothing (can't unset a mode)."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter"}},
            "device_info": {"1234567890": {"deviceTypeText4APP": "FlexBOSS21"}},
            "parameters": {"1234567890": {}},
        }
        coordinator.set_working_mode = AsyncMock()
        device_info = {"deviceTypeText4APP": "FlexBOSS21"}
        mode_config = {
            "name": "Self Use",
            "param": "FUNC_WORK_MODE",
            "value": 0,
            "entity_category": None,
        }

        entity = EG4WorkingModeSwitch(
            coordinator=coordinator,
            device_info=device_info,
            serial_number="1234567890",
            mode_config=mode_config,
        )

        # Mock async_write_ha_state to avoid needing Home Assistant instance
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        # Should call set_working_mode with False
        coordinator.set_working_mode.assert_called_once()
