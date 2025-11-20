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
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
)


class TestNumberPlatformSetup:
    """Test number platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_inverter(self, hass):
        """Test async_setup_entry creates entities for inverter."""
        from custom_components.eg4_web_monitor.number import async_setup_entry

        # Create mock config entry
        config_entry = MagicMock()

        # Create mock coordinator with inverter data
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            },
            "device_info": {
                "1234567890": {
                    "deviceTypeText4APP": "FlexBOSS21",
                }
            },
        }
        mock_coordinator.get_device_info = MagicMock(return_value={})
        config_entry.runtime_data = mock_coordinator

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, config_entry, mock_add_entities)

        # Should create number entities for FlexBOSS21 inverter
        assert len(entities) > 0
        # FlexBOSS21 should get AC Charge Power, PV Charge Power, and SOC entities
        entity_types = [type(e).__name__ for e in entities]
        assert "ACChargePowerNumber" in entity_types

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_gridboss(self, hass):
        """Test async_setup_entry skips GridBOSS devices."""
        from custom_components.eg4_web_monitor.number import async_setup_entry

        config_entry = MagicMock()

        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "gridboss123": {
                    "type": "gridboss",
                    "model": "GridBOSS",
                }
            },
        }
        mock_coordinator.get_device_info = MagicMock(return_value={})
        config_entry.runtime_data = mock_coordinator

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, config_entry, mock_add_entities)

        # Should not create number entities for GridBOSS
        assert len(entities) == 0

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_xp_device(self, hass):
        """Test async_setup_entry creates entities for XP device."""
        from custom_components.eg4_web_monitor.number import async_setup_entry

        config_entry = MagicMock()

        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "xp1234567890": {
                    "type": "inverter",
                    "model": "XP",
                }
            },
            "device_info": {
                "xp1234567890": {
                    "deviceTypeText4APP": "XP",
                }
            },
        }
        mock_coordinator.get_device_info = MagicMock(return_value={})
        config_entry.runtime_data = mock_coordinator

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, config_entry, mock_add_entities)

        # Should create some number entities for XP device
        assert len(entities) > 0


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
            "parameters": {"1234567890": {"HOLD_AC_CHARGE_POWER_CMD": 5.0}},
        }

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.native_value == 5.0

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
            "parameters": {"1234567890": {"_12K_HOLD_GRID_PEAK_SHAVING_POWER": 5.0}},
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
            "parameters": {"1234567890": {"HOLD_AC_CHARGE_SOC_LIMIT": 90.0}},
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
            "parameters": {"1234567890": {"HOLD_DISCHG_CUT_OFF_SOC_EOD": 20.0}},
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
            "parameters": {"1234567890": {"HOLD_SOC_LOW_LIMIT_EPS_DISCHG": 10.0}},
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


class TestNumberEntityAvailability:
    """Test number entity availability."""

    def test_entity_available_when_update_success(self):
        """Test entity is available when coordinator update successful."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.last_update_success = True

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.available is True

    def test_entity_unavailable_when_update_fails(self):
        """Test entity is unavailable when coordinator update fails."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.last_update_success = False

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.available is False


class TestNumberEntityAttributes:
    """Test number entity attributes and properties."""

    def test_device_info(self):
        """Test device_info property."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "device_info": {
                "1234567890": {
                    "deviceTypeText4APP": "FlexBOSS21",
                }
            },
        }
        # Mock get_device_info to return proper DeviceInfo dict
        coordinator.get_device_info = MagicMock(
            return_value={
                "identifiers": {("eg4_web_monitor", "1234567890")},
                "name": "FlexBOSS21",
                "manufacturer": "EG4",
            }
        )

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        device_info = entity.device_info
        assert device_info is not None
        assert "1234567890" in str(device_info.get("identifiers"))

    def test_unique_id(self):
        """Test unique_id is properly generated."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity.unique_id is not None
        assert "1234567890" in entity.unique_id
        assert "ac_charge_power" in entity.unique_id

    def test_entity_name_and_mode(self):
        """Test entity name and mode configuration."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber
        from homeassistant.components.number import NumberMode

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        assert entity._attr_name == "AC Charge Power"
        assert entity._attr_mode == NumberMode.BOX
        assert entity._attr_has_entity_name is True


class TestNumberEntityValueRetrieval:
    """Test number entity value retrieval methods."""

    def test_get_value_from_coordinator(self):
        """Test _get_value_from_coordinator method."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_AC_CHARGE_POWER_CMD": 7.5,
                }
            },
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Test that _get_value_from_coordinator returns the value
        value = entity._get_value_from_coordinator()
        assert value == 7.5

    def test_get_value_from_coordinator_missing(self):
        """Test _get_value_from_coordinator when parameter is missing."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {"1234567890": {}},
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Test that _get_value_from_coordinator returns None when missing
        value = entity._get_value_from_coordinator()
        assert value is None

    def test_native_value_uses_coordinator_value(self):
        """Test that native_value prefers coordinator value over cached."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {
                "1234567890": {
                    "HOLD_AC_CHARGE_POWER_CMD": 10.0,
                }
            },
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Set a different cached value
        entity._current_value = 5.0

        # native_value should return coordinator value (10), not cached (5)
        assert entity.native_value == 10

    def test_native_value_falls_back_to_cached(self):
        """Test that native_value falls back to cached value when coordinator has none."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "parameters": {"1234567890": {}},
        }
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Set a cached value
        entity._current_value = 8.0

        # native_value should return cached value
        assert entity.native_value == 8.0


class TestNumberEntityErrorHandling:
    """Test error handling in number entities."""

    @pytest.mark.asyncio
    async def test_set_value_with_api_error(self):
        """Test handling of API errors when setting value."""
        from homeassistant.exceptions import HomeAssistantError
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(side_effect=Exception("API Error"))
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Should raise HomeAssistantError with API error details
        with pytest.raises(HomeAssistantError, match="API Error"):
            await entity.async_set_native_value(5.0)

    @pytest.mark.asyncio
    async def test_set_value_out_of_range(self):
        """Test setting value outside allowed range."""
        from homeassistant.exceptions import HomeAssistantError
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Value outside range (0.0-15.0 kW) should raise error
        with pytest.raises(HomeAssistantError, match="must be between 0.0-15.0 kW"):
            await entity.async_set_native_value(20.0)

        # API should not be called for out-of-range value
        coordinator.api.write_parameter.assert_not_called()

        # Value within range should work
        await entity.async_set_native_value(5.0)
        coordinator.api.write_parameter.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_decimal(self):
        """Test setting decimal value works correctly."""
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Decimal value (0.5) should work correctly
        await entity.async_set_native_value(0.5)

        # API should be called with the decimal value
        coordinator.api.write_parameter.assert_called_once()
        call_args = coordinator.api.write_parameter.call_args[1]
        assert call_args["value_text"] == "0.5"

    @pytest.mark.asyncio
    async def test_set_value_api_write_failure(self):
        """Test handling of API write returning failure."""
        from homeassistant.exceptions import HomeAssistantError
        from custom_components.eg4_web_monitor.number import ACChargePowerNumber

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(
            return_value={"success": False, "message": "Device offline"}
        )
        coordinator.get_device_info = MagicMock(return_value={})

        entity = ACChargePowerNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Should raise HomeAssistantError with API error message
        with pytest.raises(HomeAssistantError, match="Device offline"):
            await entity.async_set_native_value(5.0)

        # API should have been called
        coordinator.api.write_parameter.assert_called_once()


class TestBatteryChargeCurrentNumber:
    """Test BatteryChargeCurrentNumber entity."""

    @pytest.mark.asyncio
    async def test_battery_charge_current_entity_creation(self):
        """Test battery charge current entity can be created."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Check entity properties
        assert entity._attr_name == "Battery Charge Current"
        assert entity._attr_native_min_value == 0
        assert entity._attr_native_max_value == 250
        assert entity._attr_native_step == 1
        assert entity._attr_native_unit_of_measurement == "A"
        assert entity._attr_icon == "mdi:battery-charging-high"

    @pytest.mark.asyncio
    async def test_battery_charge_current_set_value(self):
        """Test setting battery charge current value."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Set value to 100A
        await entity.async_set_native_value(100)

        # Verify API was called with correct parameters
        coordinator.api.write_parameter.assert_called_once_with(
            inverter_sn="1234567890",
            hold_param="HOLD_LEAD_ACID_CHARGE_RATE",
            value_text="100",
        )

        # Verify state was updated
        assert entity._current_value == 100
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_battery_charge_current_out_of_range(self):
        """Test setting battery charge current outside allowed range."""
        from homeassistant.exceptions import HomeAssistantError

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryChargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Value outside range (0-250 A) should raise error
        with pytest.raises(
            HomeAssistantError, match="must be between 0-250 A"
        ):
            await entity.async_set_native_value(251)

        # API should not be called for out-of-range value
        coordinator.api.write_parameter.assert_not_called()


class TestBatteryDischargeCurrentNumber:
    """Test BatteryDischargeCurrentNumber entity."""

    @pytest.mark.asyncio
    async def test_battery_discharge_current_entity_creation(self):
        """Test battery discharge current entity can be created."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.last_update_success = True
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryDischargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        # Check entity properties
        assert entity._attr_name == "Battery Discharge Current"
        assert entity._attr_native_min_value == 0
        assert entity._attr_native_max_value == 250
        assert entity._attr_native_step == 1
        assert entity._attr_native_unit_of_measurement == "A"
        assert entity._attr_icon == "mdi:battery-minus"

    @pytest.mark.asyncio
    async def test_battery_discharge_current_set_value(self):
        """Test setting battery discharge current value."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryDischargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Set value to 150A
        await entity.async_set_native_value(150)

        # Verify API was called with correct parameters
        coordinator.api.write_parameter.assert_called_once_with(
            inverter_sn="1234567890",
            hold_param="HOLD_LEAD_ACID_DISCHARGE_RATE",
            value_text="150",
        )

        # Verify state was updated
        assert entity._current_value == 150
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_battery_discharge_current_out_of_range(self):
        """Test setting battery discharge current outside allowed range."""
        from homeassistant.exceptions import HomeAssistantError

        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        }
        coordinator.api = MagicMock()
        coordinator.api.write_parameter = AsyncMock(return_value={"success": True})
        coordinator.get_device_info = MagicMock(return_value={})

        entity = BatteryDischargeCurrentNumber(
            coordinator=coordinator,
            serial="1234567890",
        )

        entity.hass = MagicMock()
        entity.hass.async_create_task = MagicMock()
        entity.async_write_ha_state = MagicMock()

        # Value outside range (0-250 A) should raise error
        with pytest.raises(
            HomeAssistantError, match="must be between 0-250 A"
        ):
            await entity.async_set_native_value(251)

        # API should not be called for out-of-range value
        coordinator.api.write_parameter.assert_not_called()
