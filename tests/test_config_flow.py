"""Tests for EG4 Inverter config flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.eg4_inverter.config_flow import EG4InverterConfigFlow
from custom_components.eg4_inverter.const import DOMAIN, CONF_BASE_URL, CONF_VERIFY_SSL, CONF_PLANT_ID, CONF_PLANT_NAME
from custom_components.eg4_inverter.eg4_inverter_api.exceptions import EG4AuthError, EG4ConnectionError


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def sample_login_response():
    """Sample login response with plants."""
    return {
        "success": True,
        "plants": [
            {
                "plantId": "12345",
                "name": "Home Solar System",
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
            },
            {
                "plantId": "67890",
                "name": "Cabin Solar System",
                "inverters": [
                    {
                        "serialNum": "4512670118",
                        "deviceTypeText4APP": "18KPV",
                        "lost": False
                    }
                ]
            }
        ]
    }


class TestEG4InverterConfigFlow:
    """Test EG4InverterConfigFlow class."""

    def test_config_flow_init(self):
        """Test config flow initialization."""
        flow = EG4InverterConfigFlow()
        assert flow.VERSION == 1
        assert flow.DOMAIN == DOMAIN

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_success_single_plant(self, mock_api_class, sample_login_response):
        """Test user step with successful login and single plant auto-selection.""" 
        # Mock API with single plant
        single_plant_response = {
            "success": True,
            "plants": [sample_login_response["plants"][0]]  # Only first plant
        }
        
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.return_value = single_plant_response
        
        flow = EG4InverterConfigFlow()
        
        # Test initial form
        result = await flow.async_step_user()
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}
        
        # Test form submission with credentials
        result = await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        # Should auto-select single plant and create entry
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "EG4 Inverter Home Solar System"
        assert result["data"]["username"] == "test@example.com"
        assert result["data"]["password"] == "testpass"
        assert result["data"][CONF_PLANT_ID] == "12345"
        assert result["data"][CONF_PLANT_NAME] == "Home Solar System"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_success_multiple_plants(self, mock_api_class, sample_login_response):
        """Test user step with successful login and multiple plants."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.return_value = sample_login_response
        
        flow = EG4InverterConfigFlow()
        
        # Test form submission with credentials
        result = await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        # Should show plant selection form
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "plant_selection"
        assert result["errors"] == {}
        
        # Check plant options
        plant_options = {opt["value"]: opt["label"] for opt in result["data_schema"].schema["plant"].options}
        assert "12345" in plant_options
        assert "67890" in plant_options
        assert plant_options["12345"] == "Home Solar System"
        assert plant_options["67890"] == "Cabin Solar System"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_plant_selection_step(self, mock_api_class, sample_login_response):
        """Test plant selection step."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.return_value = sample_login_response
        
        flow = EG4InverterConfigFlow()
        
        # First authenticate to set up context
        await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        # Select a plant
        result = await flow.async_step_plant_selection({
            "plant": "67890"  # Select second plant
        })
        
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "EG4 Inverter Cabin Solar System"
        assert result["data"][CONF_PLANT_ID] == "67890"
        assert result["data"][CONF_PLANT_NAME] == "Cabin Solar System"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_auth_error(self, mock_api_class):
        """Test user step with authentication error."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.side_effect = EG4AuthError("Invalid credentials")
        
        flow = EG4InverterConfigFlow()
        
        result = await flow.async_step_user({
            "username": "bad@example.com",
            "password": "badpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "invalid_auth"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_connection_error(self, mock_api_class):
        """Test user step with connection error."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.side_effect = EG4ConnectionError("Connection timeout")
        
        flow = EG4InverterConfigFlow()
        
        result = await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "cannot_connect"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_unknown_error(self, mock_api_class):
        """Test user step with unknown error."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.side_effect = Exception("Unexpected error")
        
        flow = EG4InverterConfigFlow()
        
        result = await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "unknown"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_user_step_no_plants(self, mock_api_class):
        """Test user step with no plants found."""
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.return_value = {"success": True, "plants": []}
        
        flow = EG4InverterConfigFlow()
        
        result = await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_plants"

    @patch('custom_components.eg4_inverter.config_flow.EG4InverterAPI')
    async def test_duplicate_plant_prevention(self, mock_api_class, sample_login_response, mock_hass):
        """Test prevention of duplicate plant configurations."""
        # Mock existing entry
        existing_entry = MagicMock()
        existing_entry.data = {
            "username": "test@example.com",
            CONF_PLANT_ID: "12345"
        }
        mock_hass.config_entries.async_entries.return_value = [existing_entry]
        
        mock_api = AsyncMock()
        mock_api_class.return_value = mock_api
        mock_api.login.return_value = sample_login_response
        
        flow = EG4InverterConfigFlow()
        flow.hass = mock_hass
        
        # Try to add the same plant again
        await flow.async_step_user({
            "username": "test@example.com",
            "password": "testpass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True
        })
        
        # Select the same plant that already exists
        result = await flow.async_step_plant_selection({
            "plant": "12345"
        })
        
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    def test_form_schema_validation(self):
        """Test form schema validation."""
        flow = EG4InverterConfigFlow()
        
        # Test user form schema
        user_schema = flow._get_user_schema()
        assert "username" in user_schema.schema
        assert "password" in user_schema.schema
        assert CONF_BASE_URL in user_schema.schema
        assert CONF_VERIFY_SSL in user_schema.schema
        
        # Test default values
        assert user_schema.schema[CONF_BASE_URL].default() == "https://monitor.eg4electronics.com"
        assert user_schema.schema[CONF_VERIFY_SSL].default() is True

    def test_plant_options_creation(self):
        """Test plant options creation for selection form."""
        flow = EG4InverterConfigFlow()
        
        plants = [
            {"plantId": "123", "name": "Plant A"},
            {"plantId": "456", "name": "Plant B"}
        ]
        
        options = flow._create_plant_options(plants)
        
        assert len(options) == 2
        assert options[0]["value"] == "123"
        assert options[0]["label"] == "Plant A"
        assert options[1]["value"] == "456"
        assert options[1]["label"] == "Plant B"

    async def test_async_get_options_flow(self):
        """Test options flow creation."""
        mock_entry = MagicMock()
        
        flow = EG4InverterConfigFlow()
        result = await flow.async_get_options_flow(mock_entry)
        
        # Should return None since no options flow is implemented yet
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__])