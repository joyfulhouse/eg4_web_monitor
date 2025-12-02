"""Unit tests for number entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock


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
