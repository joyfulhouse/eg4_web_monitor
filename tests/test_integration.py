"""Integration tests for EG4 Inverter component."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.setup import async_setup_component

from custom_components.eg4_inverter import async_setup_entry, async_unload_entry
from custom_components.eg4_inverter.const import DOMAIN, SERVICE_REFRESH_DATA
from custom_components.eg4_inverter.coordinator import EG4DataUpdateCoordinator


class TestIntegrationSetup:
    """Test integration setup and teardown."""

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_async_setup_entry_success(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test successful integration setup."""
        # Mock coordinator
        mock_coordinator = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        
        # Mock platform setup
        mock_hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        mock_hass.services.has_service.return_value = False
        mock_hass.services.async_register = MagicMock()
        
        # Test setup
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert result is True
        mock_coordinator_class.assert_called_once_with(mock_hass, mock_config_entry)
        mock_coordinator.async_config_entry_first_refresh.assert_called_once()
        
        # Check data storage
        assert DOMAIN in mock_hass.data
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]
        assert mock_hass.data[DOMAIN][mock_config_entry.entry_id] == mock_coordinator
        
        # Check platform setup
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            mock_config_entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )
        
        # Check service registration
        mock_hass.services.async_register.assert_called_once_with(
            DOMAIN, SERVICE_REFRESH_DATA, mock_hass.services.async_register.call_args[0][2]
        )

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_async_setup_entry_coordinator_failure(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test integration setup with coordinator failure."""
        # Mock coordinator with failure
        mock_coordinator = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_config_entry_first_refresh.side_effect = Exception("Coordinator failed")
        
        # Test setup should fail
        with pytest.raises(Exception, match="Coordinator failed"):
            await async_setup_entry(mock_hass, mock_config_entry)

    async def test_async_unload_entry_success(self, mock_hass, mock_config_entry):
        """Test successful integration unload."""
        # Setup mock data
        mock_coordinator = AsyncMock()
        mock_coordinator.api.close = AsyncMock()
        
        mock_hass.data = {
            DOMAIN: {
                mock_config_entry.entry_id: mock_coordinator
            }
        }
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        
        # Test unload
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is True
        mock_coordinator.api.close.assert_called_once()
        
        # Check data cleanup
        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]

    async def test_async_unload_entry_platform_failure(self, mock_hass, mock_config_entry):
        """Test integration unload with platform failure."""
        # Setup mock data
        mock_coordinator = AsyncMock()
        mock_hass.data = {
            DOMAIN: {
                mock_config_entry.entry_id: mock_coordinator
            }
        }
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        
        # Test unload should fail
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is False
        # Coordinator should not be cleaned up on failure
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]


class TestServiceCalls:
    """Test service call handling."""

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_refresh_data_service_specific_entry(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test refresh data service for specific entry."""
        # Setup coordinator
        mock_coordinator = AsyncMock()
        mock_coordinator.async_request_refresh = AsyncMock()
        mock_coordinator.entry = mock_config_entry
        
        mock_hass.data = {
            DOMAIN: {
                mock_config_entry.entry_id: mock_coordinator
            }
        }
        
        # Import and test service handler
        from custom_components.eg4_inverter import _handle_refresh_data
        
        # Mock service call
        mock_call = MagicMock()
        mock_call.hass = mock_hass
        mock_call.data = {"entry_id": mock_config_entry.entry_id}
        
        # Test service call
        await _handle_refresh_data(mock_call)
        
        mock_coordinator.async_request_refresh.assert_called_once()

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_refresh_data_service_all_entries(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test refresh data service for all entries."""
        # Setup multiple coordinators
        mock_coordinator1 = AsyncMock()
        mock_coordinator1.async_request_refresh = AsyncMock()
        mock_coordinator1.entry.entry_id = "entry1"
        
        mock_coordinator2 = AsyncMock()
        mock_coordinator2.async_request_refresh = AsyncMock()
        mock_coordinator2.entry.entry_id = "entry2"
        
        mock_hass.data = {
            DOMAIN: {
                "entry1": mock_coordinator1,
                "entry2": mock_coordinator2
            }
        }
        
        # Import service handler
        from custom_components.eg4_inverter import _handle_refresh_data
        
        # Mock service call without entry_id
        mock_call = MagicMock()
        mock_call.hass = mock_hass
        mock_call.data = {}
        
        # Test service call
        await _handle_refresh_data(mock_call)
        
        mock_coordinator1.async_request_refresh.assert_called_once()
        mock_coordinator2.async_request_refresh.assert_called_once()

    async def test_refresh_data_service_invalid_entry(self, mock_hass):
        """Test refresh data service with invalid entry ID."""
        mock_hass.data = {DOMAIN: {}}
        
        # Import service handler
        from custom_components.eg4_inverter import _handle_refresh_data
        
        # Mock service call with invalid entry_id
        mock_call = MagicMock()
        mock_call.hass = mock_hass
        mock_call.data = {"entry_id": "invalid_entry"}
        
        # Test service call should handle gracefully
        await _handle_refresh_data(mock_call)
        
        # Should not crash, just log error

    async def test_refresh_data_service_no_coordinators(self, mock_hass):
        """Test refresh data service with no coordinators."""
        mock_hass.data = {}
        
        # Import service handler
        from custom_components.eg4_inverter import _handle_refresh_data
        
        # Mock service call
        mock_call = MagicMock()
        mock_call.hass = mock_hass
        mock_call.data = {}
        
        # Test service call should handle gracefully
        await _handle_refresh_data(mock_call)
        
        # Should not crash, just log warning


class TestPlatformIntegration:
    """Test platform integration."""

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    @patch('custom_components.eg4_inverter.sensor.async_setup_entry')
    @patch('custom_components.eg4_inverter.binary_sensor.async_setup_entry')
    async def test_platform_setup_order(self, mock_binary_setup, mock_sensor_setup, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test that platforms are set up in correct order."""
        # Mock coordinator
        mock_coordinator = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        
        # Mock platform setups
        mock_sensor_setup.return_value = True
        mock_binary_setup.return_value = True
        mock_hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        mock_hass.services.has_service.return_value = False
        mock_hass.services.async_register = MagicMock()
        
        # Test setup
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert result is True
        
        # Verify platforms were set up
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            mock_config_entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )


class TestErrorHandling:
    """Test error handling scenarios."""

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_setup_with_missing_config(self, mock_coordinator_class, mock_hass):
        """Test setup with missing configuration."""
        # Create config entry with missing data
        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.data = {}  # Missing required fields
        
        # Mock coordinator creation failure
        mock_coordinator_class.side_effect = KeyError("Missing required configuration")
        
        # Test setup should handle gracefully
        with pytest.raises(KeyError):
            await async_setup_entry(mock_hass, mock_config_entry)

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_unload_with_missing_data(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test unload with missing hass data."""
        # No data in hass
        mock_hass.data = {}
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        
        # Test unload should handle gracefully
        with pytest.raises(KeyError):
            await async_unload_entry(mock_hass, mock_config_entry)

    @patch('custom_components.eg4_inverter.EG4DataUpdateCoordinator')
    async def test_service_registration_duplicate(self, mock_coordinator_class, mock_hass, mock_config_entry):
        """Test service registration when service already exists."""
        # Mock coordinator
        mock_coordinator = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        
        # Mock platform setup
        mock_hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        mock_hass.services.has_service.return_value = True  # Service already exists
        mock_hass.services.async_register = MagicMock()
        
        # Test setup
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert result is True
        # Service should not be registered again
        mock_hass.services.async_register.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])