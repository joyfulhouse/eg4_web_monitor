"""Tests for EG4 Inverter coordinator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.eg4_inverter.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_inverter.const import DOMAIN, CONF_PLANT_ID, CONF_BASE_URL, CONF_VERIFY_SSL
from custom_components.eg4_inverter.eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MagicMock(spec=ConfigEntry)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def sample_runtime_data():
    """Sample runtime data for testing."""
    return {
        "success": True,
        "serialNum": "44300E0585",
        "fwCode": "FAAB-2122",
        "statusText": "normal",
        "vpv1": 2554,
        "vpv2": 3601,
        "ppv1": 117,
        "ppv2": 284,
        "vacr": 2417,
        "fac": 5998,
        "tinner": 40,
        "tradiator1": 45,
        "tradiator2": 41,
        "ppv": 401,
        "pCharge": 375,
        "soc": 69,
        "status": 12
    }


@pytest.fixture
def sample_energy_data():
    """Sample energy data for testing."""
    return {
        "success": True,
        "todayYielding": 125,
        "todayDischarging": 89,
        "todayCharging": 134,
        "totalYielding": 15634,
        "totalDischarging": 8920,
        "totalCharging": 9455
    }


@pytest.fixture
def sample_battery_data():
    """Sample battery data for testing."""
    return {
        "success": True,
        "batteryArray": [
            {
                "batteryKey": "44300E0585-01",
                "totalVoltage": 5120,
                "current": -154,
                "soc": 69,
                "soh": 100,
                "cycleCnt": 145,
                "fwVersionText": "2.17"
            },
            {
                "batteryKey": "44300E0585-02", 
                "totalVoltage": 5121,
                "current": -155,
                "soc": 70,
                "soh": 99,
                "cycleCnt": 144,
                "fwVersionText": "2.17"
            }
        ],
        "batteryVoltage": 51.2,
        "batteryCurrent": -3.1,
        "batteryPower": 375
    }


@pytest.fixture
def sample_gridboss_data():
    """Sample GridBOSS midbox data for testing."""
    return {
        "success": True,
        "fwCode": "IAAB-1300",
        "midboxData": {
            "gridFreq": 5998,
            "gridL1RmsVolt": 2415,
            "gridL2RmsVolt": 2420,
            "gridL1ActivePower": 0,
            "gridL2ActivePower": 0,
            "smartPort1Status": 1,
            "smartPort2Status": 0,
            "eUpsTodayL1": 125,
            "eUpsTotalL1": 8945
        }
    }


class TestEG4DataUpdateCoordinator:
    """Test EG4DataUpdateCoordinator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_hass = MagicMock(spec=HomeAssistant)
        self.mock_entry = MagicMock(spec=ConfigEntry)
        self.mock_entry.data = {
            "username": "test_user",
            "password": "test_pass", 
            CONF_PLANT_ID: "12345",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        }

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_coordinator_init(self, mock_api_class):
        """Test coordinator initialization."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        assert coordinator.plant_id == "12345"
        assert coordinator.devices == {}
        assert coordinator.device_sensors == {}
        mock_api_class.assert_called_once()

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_update_data_success(self, mock_api_class, sample_runtime_data, sample_energy_data, sample_battery_data):
        """Test successful data update."""
        # Mock API responses
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        
        mock_api.get_all_device_data.return_value = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "runtime": sample_runtime_data,
                    "energy": sample_energy_data,
                    "battery": sample_battery_data
                }
            },
            "parallel_groups": {},
            "inverter_overview": {},
            "device_info": {
                "44300E0585": {"deviceTypeText4APP": "FlexBOSS21"}
            }
        }
        
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        result = await coordinator._async_update_data()
        
        assert result is not None
        assert "devices" in result
        assert "44300E0585" in result["devices"]
        assert result["devices"]["44300E0585"]["type"] == "inverter"
        assert result["devices"]["44300E0585"]["firmware_version"] == "FAAB-2122"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_update_data_auth_error(self, mock_api_class):
        """Test data update with authentication error."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.get_all_device_data.side_effect = EG4AuthError("Authentication failed")
        
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        with pytest.raises(UpdateFailed, match="Authentication failed"):
            await coordinator._async_update_data()

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_update_data_connection_error(self, mock_api_class):
        """Test data update with connection error."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.get_all_device_data.side_effect = EG4ConnectionError("Connection failed")
        
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        with pytest.raises(UpdateFailed, match="Connection failed"):
            await coordinator._async_update_data()

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_extract_runtime_sensors(self, mock_api_class, sample_runtime_data):
        """Test runtime sensor extraction."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        sensors = coordinator._extract_runtime_sensors(sample_runtime_data)
        
        # Check for key sensors
        assert "pv_total_power" in sensors
        assert sensors["pv_total_power"] == 401
        assert "internal_temperature" in sensors
        assert sensors["internal_temperature"] == 40
        assert "ac_voltage" in sensors
        assert sensors["ac_voltage"] == 241.7  # 2417 / 10
        assert "frequency" in sensors
        assert sensors["frequency"] == 59.98  # 5998 / 100

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_extract_energy_sensors(self, mock_api_class, sample_energy_data):
        """Test energy sensor extraction."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        sensors = coordinator._extract_energy_sensors(sample_energy_data)
        
        # Check for yield sensors (renamed from yielding and simplified)
        assert "yield" in sensors
        assert sensors["yield"] == 12.5  # 125 / 10
        assert "yield_lifetime" in sensors
        assert sensors["yield_lifetime"] == 1563.4  # 15634 / 10

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_extract_gridboss_sensors(self, mock_api_class, sample_gridboss_data):
        """Test GridBOSS sensor extraction."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        sensors = coordinator._extract_gridboss_sensors(sample_gridboss_data["midboxData"])
        
        # Check for key GridBOSS sensors
        assert "frequency" in sensors
        assert sensors["frequency"] == 59.98  # 5998 / 100
        assert "grid_voltage_l1" in sensors
        assert sensors["grid_voltage_l1"] == 241.5  # 2415 / 10
        assert "smart_port1_status" in sensors
        assert sensors["smart_port1_status"] == "Smart Load"  # Status 1 mapped
        assert "smart_port2_status" in sensors
        assert sensors["smart_port2_status"] == "Unused"  # Status 0 mapped

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_clean_battery_key(self, mock_api_class):
        """Test battery key cleaning."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        # Test various battery key formats
        assert coordinator._clean_battery_key("4512670118_Battery_ID_01", "4512670118") == "4512670118-01"
        assert coordinator._clean_battery_key("Battery_ID_02", "4512670118") == "4512670118-02"
        assert coordinator._clean_battery_key("BAT001", "4512670118") == "BAT001"
        assert coordinator._clean_battery_key("03", "4512670118") == "4512670118-03"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_to_camel_case(self, mock_api_class):
        """Test camel case conversion."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        assert coordinator._to_camel_case("grid connected") == "gridConnected"
        assert coordinator._to_camel_case("battery_charging") == "batteryCharging"
        assert coordinator._to_camel_case("normal") == "normal"
        assert coordinator._to_camel_case("") == ""

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    async def test_process_inverter_data(self, mock_api_class, sample_runtime_data, sample_energy_data, sample_battery_data):
        """Test inverter data processing."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        device_data = {
            "runtime": sample_runtime_data,
            "energy": sample_energy_data,
            "battery": sample_battery_data
        }
        
        processed = await coordinator._process_inverter_data("44300E0585", device_data)
        
        assert processed["serial"] == "44300E0585"
        assert processed["type"] == "inverter"
        assert processed["firmware_version"] == "FAAB-2122"
        assert len(processed["batteries"]) == 2
        assert "44300E0585-01" in processed["batteries"]
        assert "44300E0585-02" in processed["batteries"]

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI') 
    async def test_process_gridboss_data(self, mock_api_class, sample_gridboss_data):
        """Test GridBOSS data processing."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        
        device_data = {"midbox": sample_gridboss_data}
        
        processed = await coordinator._process_gridboss_data("4524850115", device_data)
        
        assert processed["serial"] == "4524850115"
        assert processed["type"] == "gridboss"
        assert processed["firmware_version"] == "IAAB-1300"
        assert len(processed["sensors"]) > 0

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_get_device_info_inverter(self, mock_api_class):
        """Test device info for inverter."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        coordinator.data = {
            "devices": {
                "44300E0585": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "firmware_version": "FAAB-2122"
                }
            }
        }
        
        device_info = coordinator.get_device_info("44300E0585")
        
        assert device_info["name"] == "FlexBOSS21 44300E0585"
        assert device_info["manufacturer"] == "EG4 Electronics"
        assert device_info["model"] == "FlexBOSS21"
        assert device_info["serial_number"] == "44300E0585"
        assert device_info["sw_version"] == "FAAB-2122"

    @patch('custom_components.eg4_inverter.coordinator.EG4InverterAPI')
    def test_get_device_info_gridboss(self, mock_api_class):
        """Test device info for GridBOSS."""
        coordinator = EG4DataUpdateCoordinator(self.mock_hass, self.mock_entry)
        coordinator.data = {
            "devices": {
                "4524850115": {
                    "type": "gridboss",
                    "model": "Grid Boss",
                    "firmware_version": "IAAB-1300"
                }
            }
        }
        
        device_info = coordinator.get_device_info("4524850115")
        
        assert device_info["name"] == "Grid Boss 4524850115"
        assert device_info["manufacturer"] == "EG4 Electronics"
        assert device_info["model"] == "Grid Boss"
        assert device_info["serial_number"] == "4524850115"
        assert device_info["sw_version"] == "IAAB-1300"


if __name__ == "__main__":
    pytest.main([__file__])