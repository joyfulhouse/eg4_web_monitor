"""Integration tests for recent changes."""

import pytest
from unittest.mock import MagicMock, patch

from custom_components.eg4_inverter.const import SENSOR_TYPES
from custom_components.eg4_inverter.coordinator import EG4DataUpdateCoordinator


class TestSensorNamingSimplification:
    """Test that sensors have been simplified: 'yielding'→'yield', 'today_'→'', 'total_'→'_lifetime'."""

    def test_sensor_types_simplified(self):
        """Test that sensor types use simplified naming convention."""
        # Check that the new simplified yield sensors exist
        assert "yield" in SENSOR_TYPES
        assert "yield_lifetime" in SENSOR_TYPES
        
        # Check that the old yielding sensors don't exist
        assert "today_yielding" not in SENSOR_TYPES
        assert "total_yielding" not in SENSOR_TYPES
        assert "today_yield" not in SENSOR_TYPES
        assert "total_yield" not in SENSOR_TYPES
        
        # Verify the names are correct
        assert SENSOR_TYPES["yield"]["name"] == "Yield"
        assert SENSOR_TYPES["yield_lifetime"]["name"] == "Yield (Lifetime)"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_coordinator_field_mapping_updated(self, mock_api_class):
        """Test that coordinator field mappings use yield sensors."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test", 
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        # Test runtime sensor mapping
        runtime_data = {
            "todayYielding": 125,
            "totalYielding": 15634,
            "todayDischarging": 89
        }
        
        sensors = coordinator._extract_runtime_sensors(runtime_data)
        
        # Should map to simplified yield sensors
        assert "yield" in sensors
        assert "yield_lifetime" in sensors
        assert sensors["yield"] == 12.5  # 125 / 10
        assert sensors["yield_lifetime"] == 1563.4  # 15634 / 10
        
        # Should not have old yielding sensors
        assert "today_yielding" not in sensors
        assert "total_yielding" not in sensors
        assert "today_yield" not in sensors
        assert "total_yield" not in sensors

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_energy_sensor_mapping_updated(self, mock_api_class):
        """Test that energy sensor mappings use yield sensors."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345", 
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        energy_data = {
            "todayYielding": 125,
            "totalYielding": 15634
        }
        
        sensors = coordinator._extract_energy_sensors(energy_data)
        
        # Should map to simplified yield sensors
        assert "yield" in sensors
        assert "yield_lifetime" in sensors
        assert sensors["yield"] == 12.5
        assert sensors["yield_lifetime"] == 1563.4

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_parallel_group_mapping_updated(self, mock_api_class):
        """Test that parallel group mappings use yield sensors."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com", 
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        parallel_data = {
            "todayYielding": 250,
            "totalYielding": 31268
        }
        
        sensors = coordinator._extract_parallel_group_sensors(parallel_data)
        
        # Should map to simplified yield sensors
        assert "yield" in sensors
        assert "yield_lifetime" in sensors
        assert sensors["yield"] == 25.0
        assert sensors["yield_lifetime"] == 3126.8


class TestGridBOSSZeroFilteringRemoval:
    """Test that GridBOSS zero value filtering has been removed."""

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_gridboss_zero_sensors_not_filtered(self, mock_api_class):
        """Test that GridBOSS sensors with zero values are not filtered."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        # Test with zero values that previously would have been filtered
        midbox_data = {
            "gridL1ActivePower": 0,
            "gridL2ActivePower": 0,
            "loadL1ActivePower": 0,
            "smartLoad1L1ActivePower": 0,
            "generatorPower": 0,
            "gridFreq": 5998,  # Non-zero value
            "smartPort1Status": 1  # Status sensor (should always be included)
        }
        
        sensors = coordinator._extract_gridboss_sensors(midbox_data)
        
        # Zero power sensors should now be included (filtering removed)
        assert "grid_power_l1" in sensors
        assert "grid_power_l2" in sensors
        assert "load_power_l1" in sensors
        assert "smart_load1_power_l1" in sensors
        
        # Verify values are correct (scaled appropriately)
        assert sensors["grid_power_l1"] == 0
        assert sensors["grid_power_l2"] == 0
        assert sensors["load_power_l1"] == 0
        assert sensors["smart_load1_power_l1"] == 0
        
        # Non-zero and status sensors should still be included
        assert sensors["frequency"] == 59.98  # 5998 / 100
        assert sensors["smart_port1_status"] == "Smart Load"


class TestInverterFirmwareExtraction:
    """Test that inverter firmware is extracted from fwCode field."""

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_inverter_firmware_extracted(self, mock_api_class):
        """Test that inverter firmware version is extracted from runtime fwCode."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        # Test inverter data with firmware code
        device_data = {
            "runtime": {
                "fwCode": "FAAB-2122",
                "statusText": "normal",
                "soc": 69
            },
            "energy": {},
            "battery": {}
        }
        
        processed = await coordinator._process_inverter_data("44300E0585", device_data)
        
        # Should extract firmware version from runtime fwCode
        assert processed["firmware_version"] == "FAAB-2122"
        assert processed["type"] == "inverter"
        assert processed["serial"] == "44300E0585"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_inverter_firmware_fallback(self, mock_api_class):
        """Test inverter firmware fallback when fwCode is missing."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        
        # Test with missing fwCode
        device_data = {
            "runtime": {
                "statusText": "normal",
                "soc": 69
            },
            "energy": {},
            "battery": {}
        }
        
        processed = await coordinator._process_inverter_data("44300E0585", device_data)
        
        # Should fallback to default
        assert processed["firmware_version"] == "1.0.0"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI') 
    def test_device_info_uses_firmware(self, mock_api_class):
        """Test that device info uses extracted firmware version."""
        mock_entry = MagicMock()
        mock_entry.data = {
            "username": "test",
            "password": "test",
            "plant_id": "12345",
            "base_url": "https://monitor.eg4electronics.com",
            "verify_ssl": True
        }
        
        coordinator = EG4DataUpdateCoordinator(MagicMock(), mock_entry)
        coordinator.data = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "firmware_version": "FAAB-2122"
                },
                "4524850115": {
                    "type": "gridboss", 
                    "model": "Grid Boss",
                    "firmware_version": "IAAB-1300"
                }
            }
        }
        
        # Test inverter device info
        inverter_info = coordinator.get_device_info("44300E0585")
        assert inverter_info["sw_version"] == "FAAB-2122"
        
        # Test GridBOSS device info (should still work)
        gridboss_info = coordinator.get_device_info("4524850115")
        assert gridboss_info["sw_version"] == "IAAB-1300"


class TestBackwardsCompatibility:
    """Test that changes maintain backwards compatibility."""

    def test_sensor_units_unchanged(self):
        """Test that sensor units remain unchanged after renaming."""
        # Verify yield sensors have the same units as the old yielding sensors
        assert SENSOR_TYPES["yield"]["unit"].value == "kWh"
        assert SENSOR_TYPES["yield_lifetime"]["unit"].value == "kWh"
        
        # Verify device classes remain the same
        assert SENSOR_TYPES["yield"]["device_class"] == "energy"
        assert SENSOR_TYPES["yield_lifetime"]["device_class"] == "energy"
        
        # Verify state classes remain the same
        assert SENSOR_TYPES["yield"]["state_class"] == "total_increasing"
        assert SENSOR_TYPES["yield_lifetime"]["state_class"] == "total_increasing"

    def test_sensor_icons_unchanged(self):
        """Test that sensor icons remain appropriate after renaming."""
        assert SENSOR_TYPES["yield"]["icon"] == "mdi:solar-power"
        assert SENSOR_TYPES["yield_lifetime"]["icon"] == "mdi:solar-power"


if __name__ == "__main__":
    pytest.main([__file__])