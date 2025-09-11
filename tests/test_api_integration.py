"""API integration tests for EG4 Inverter component."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from datetime import datetime

from custom_components.eg4_inverter.eg4_inverter_api.client import EG4InverterAPI
from custom_components.eg4_inverter.eg4_inverter_api.exceptions import (
    EG4APIError, 
    EG4AuthError, 
    EG4ConnectionError
)


class TestEG4InverterAPI:
    """Test EG4InverterAPI client functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.api = EG4InverterAPI(
            username="test_user",
            password="test_pass",
            base_url="https://monitor.eg4electronics.com",
            verify_ssl=True
        )

    @patch('aiohttp.ClientSession.post')
    async def test_login_success(self, mock_post):
        """Test successful login."""
        # Mock successful login response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"success": True, "msg": "Login successful"}
        mock_response.cookies = {"JSESSIONID": "test_session_id"}
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await self.api.login()
        
        assert result["success"] is True
        assert self.api.session_id == "test_session_id"
        assert self.api.last_login_time is not None

    @patch('aiohttp.ClientSession.post')
    async def test_login_invalid_credentials(self, mock_post):
        """Test login with invalid credentials."""
        # Mock failed login response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"success": False, "msg": "Invalid credentials"}
        mock_post.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(EG4AuthError, match="Invalid credentials"):
            await self.api.login()

    @patch('aiohttp.ClientSession.post')
    async def test_login_connection_error(self, mock_post):
        """Test login with connection error."""
        # Mock connection error
        mock_post.side_effect = aiohttp.ClientError("Connection failed")
        
        with pytest.raises(EG4ConnectionError, match="Connection failed"):
            await self.api.login()

    @patch('aiohttp.ClientSession.post')
    async def test_get_plants(self, mock_post):
        """Test get plants functionality."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock plants response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "rows": [
                {"plantId": "12345", "name": "Test Plant 1"},
                {"plantId": "67890", "name": "Test Plant 2"}
            ]
        }
        mock_post.return_value.__aenter__.return_value = mock_response
        
        plants = await self.api.get_plants()
        
        assert len(plants) == 2
        assert plants[0]["plantId"] == "12345"
        assert plants[0]["name"] == "Test Plant 1"
        assert plants[1]["plantId"] == "67890"
        assert plants[1]["name"] == "Test Plant 2"

    @patch('aiohttp.ClientSession.post')
    async def test_get_inverter_overview(self, mock_post):
        """Test get inverter overview functionality."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock overview response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "inverters": [
                    {
                        "serialNum": "44300E0585",
                        "deviceTypeText4APP": "FlexBOSS21",
                        "lost": False
                    },
                    {
                        "serialNum": "4524850115", 
                        "deviceTypeText4APP": "Grid Boss",
                        "lost": False
                    }
                ]
            }
        }
        mock_post.return_value.__aenter__.return_value = mock_response
        
        overview = await self.api.get_inverter_overview("12345")
        
        assert overview["success"] is True
        assert len(overview["data"]["inverters"]) == 2
        assert overview["data"]["inverters"][0]["serialNum"] == "44300E0585"
        assert overview["data"]["inverters"][1]["deviceTypeText4APP"] == "Grid Boss"

    @patch('aiohttp.ClientSession.post')
    async def test_get_runtime_data(self, mock_post):
        """Test get runtime data functionality."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock runtime response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "success": True,
            "serialNum": "44300E0585",
            "fwCode": "FAAB-2122",
            "vpv1": 2554,
            "ppv": 401,
            "vacr": 2417,
            "soc": 69,
            "status": 12
        }
        mock_post.return_value.__aenter__.return_value = mock_response
        
        runtime = await self.api.get_runtime_data("44300E0585")
        
        assert runtime["success"] is True
        assert runtime["serialNum"] == "44300E0585" 
        assert runtime["fwCode"] == "FAAB-2122"
        assert runtime["vpv1"] == 2554
        assert runtime["soc"] == 69

    @patch('aiohttp.ClientSession.post')
    async def test_get_battery_info(self, mock_post):
        """Test get battery info functionality."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock battery response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "success": True,
            "batteryArray": [
                {
                    "batteryKey": "44300E0585-01",
                    "totalVoltage": 5120,
                    "current": -154,
                    "soc": 69,
                    "soh": 100,
                    "cycleCnt": 145
                }
            ],
            "batteryVoltage": 51.2,
            "batteryCurrent": -3.1
        }
        mock_post.return_value.__aenter__.return_value = mock_response
        
        battery = await self.api.get_battery_info("44300E0585")
        
        assert battery["success"] is True
        assert len(battery["batteryArray"]) == 1
        assert battery["batteryArray"][0]["batteryKey"] == "44300E0585-01"
        assert battery["batteryArray"][0]["totalVoltage"] == 5120
        assert battery["batteryVoltage"] == 51.2

    @patch('aiohttp.ClientSession.post')
    async def test_get_midbox_runtime(self, mock_post):
        """Test get midbox runtime functionality."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock midbox response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "success": True,
            "fwCode": "IAAB-1300",
            "midboxData": {
                "gridFreq": 5998,
                "gridL1RmsVolt": 2415,
                "gridL1ActivePower": 0,
                "smartPort1Status": 1
            }
        }
        mock_post.return_value.__aenter__.return_value = mock_response
        
        midbox = await self.api.get_midbox_runtime("4524850115")
        
        assert midbox["success"] is True
        assert midbox["fwCode"] == "IAAB-1300"
        assert midbox["midboxData"]["gridFreq"] == 5998
        assert midbox["midboxData"]["smartPort1Status"] == 1

    @patch('aiohttp.ClientSession.post')
    async def test_session_expiry_and_refresh(self, mock_post):
        """Test session expiry and automatic refresh."""
        # Mock expired session and successful re-login
        responses = [
            # First call - expired session
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": False, "msg": "Session expired"}
            }),
            # Re-login call - success
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "msg": "Login successful"},
                "cookies": {"JSESSIONID": "new_session_id"}
            }),
            # Retry original call - success
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "serialNum": "44300E0585"}
            })
        ]
        
        mock_post.return_value.__aenter__.side_effect = responses
        
        # Set old session
        self.api.session_id = "old_session"
        self.api.last_login_time = datetime.now()
        
        runtime = await self.api.get_runtime_data("44300E0585")
        
        assert runtime["success"] is True
        assert self.api.session_id == "new_session_id"
        # Should have made 3 calls: failed, login, retry
        assert mock_post.call_count == 3

    @patch('aiohttp.ClientSession.post') 
    async def test_api_error_handling(self, mock_post):
        """Test API error handling."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock error response
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text.return_value = "Internal Server Error"
        mock_post.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(EG4APIError, match="API request failed"):
            await self.api.get_runtime_data("44300E0585")

    @patch('aiohttp.ClientSession.post')
    async def test_concurrent_api_calls(self, mock_post):
        """Test concurrent API calls."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock responses for multiple calls
        responses = [
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "type": "runtime", "serialNum": "44300E0585"}
            }),
            AsyncMock(**{
                "status": 200, 
                "json.return_value": {"success": True, "type": "energy", "serialNum": "44300E0585"}
            }),
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "type": "battery", "serialNum": "44300E0585"}
            })
        ]
        
        mock_post.return_value.__aenter__.side_effect = responses
        
        # Make concurrent calls
        import asyncio
        results = await asyncio.gather(
            self.api.get_runtime_data("44300E0585"),
            self.api.get_energy_data("44300E0585"),  
            self.api.get_battery_info("44300E0585")
        )
        
        assert len(results) == 3
        assert results[0]["type"] == "runtime"
        assert results[1]["type"] == "energy" 
        assert results[2]["type"] == "battery"

    async def test_close_session(self):
        """Test session cleanup."""
        # Mock session
        mock_session = AsyncMock()
        self.api._session = mock_session
        
        await self.api.close()
        
        mock_session.close.assert_called_once()
        assert self.api._session is None

    def test_device_type_detection(self):
        """Test device type detection."""
        # Test GridBOSS detection
        assert self.api._is_gridboss_device("Grid Boss") is True
        assert self.api._is_gridboss_device("gridboss") is True
        assert self.api._is_gridboss_device("GRIDBOSS MID") is True
        
        # Test standard inverter detection
        assert self.api._is_gridboss_device("FlexBOSS21") is False
        assert self.api._is_gridboss_device("FlexBOSS18") is False
        assert self.api._is_gridboss_device("18kPV") is False

    @patch('aiohttp.ClientSession.post')
    async def test_get_all_device_data(self, mock_post):
        """Test comprehensive device data retrieval."""
        # Setup session
        self.api.session_id = "test_session"
        
        # Mock multiple API responses
        responses = [
            # Inverter overview
            AsyncMock(**{
                "status": 200,
                "json.return_value": {
                    "success": True,
                    "data": {
                        "inverters": [
                            {"serialNum": "44300E0585", "deviceTypeText4APP": "FlexBOSS21", "lost": False},
                            {"serialNum": "4524850115", "deviceTypeText4APP": "Grid Boss", "lost": False}
                        ]
                    }
                }
            }),
            # Runtime data for FlexBOSS21
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "serialNum": "44300E0585", "vpv1": 2554}
            }),
            # Energy data for FlexBOSS21  
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "todayYielding": 125}
            }),
            # Battery data for FlexBOSS21
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "batteryArray": []}
            }),
            # Midbox data for Grid Boss
            AsyncMock(**{
                "status": 200,
                "json.return_value": {"success": True, "fwCode": "IAAB-1300", "midboxData": {}}
            })
        ]
        
        mock_post.return_value.__aenter__.side_effect = responses
        
        data = await self.api.get_all_device_data("12345")
        
        assert "devices" in data
        assert "44300E0585" in data["devices"]
        assert "4524850115" in data["devices"]
        assert data["devices"]["44300E0585"]["type"] == "inverter"
        assert data["devices"]["4524850115"]["type"] == "gridboss"


if __name__ == "__main__":
    pytest.main([__file__])