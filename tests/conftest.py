"""Test configuration and fixtures for EG4 Inverter tests."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
from pathlib import Path

# Add the integration to the Python path
integration_path = Path(__file__).parent.parent
sys.path.insert(0, str(integration_path))

# Mock Home Assistant modules that might not be available
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['homeassistant.helpers.entity'] = MagicMock()
sys.modules['homeassistant.helpers.entity_platform'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.sensor'] = MagicMock()
sys.modules['homeassistant.util'] = MagicMock()
sys.modules['homeassistant.util.dt'] = MagicMock()
sys.modules['homeassistant.data_entry_flow'] = MagicMock()

# Import the real constants and enums we need
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)

from homeassistant.helpers.entity import EntityCategory
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

# Configure logging for tests
import logging
logging.basicConfig(level=logging.DEBUG)

@pytest.fixture
def mock_hass():
    """Provide a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


@pytest.fixture
def mock_config_entry():
    """Provide a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "username": "test_user",
        "password": "test_pass",
        "plant_id": "12345",
        "plant_name": "Test Plant",
        "base_url": "https://monitor.eg4electronics.com",
        "verify_ssl": True
    }
    return entry


@pytest.fixture
def sample_api_responses():
    """Provide sample API responses for testing."""
    return {
        "login": {
            "success": True,
            "plants": [
                {
                    "plantId": "12345",
                    "name": "Test Plant",
                    "inverters": [
                        {
                            "serialNum": "44300E0585",
                            "deviceTypeText4APP": "FlexBOSS21",
                            "lost": False
                        }
                    ]
                }
            ]
        },
        "runtime": {
            "success": True,
            "serialNum": "44300E0585",
            "fwCode": "FAAB-2122",
            "statusText": "normal",
            "vpv1": 2554,
            "ppv": 401,
            "vacr": 2417,
            "fac": 5998,
            "tinner": 40,
            "soc": 69,
            "status": 12
        },
        "energy": {
            "success": True,
            "todayYielding": 125,
            "totalYielding": 15634,
            "todayDischarging": 89,
            "totalDischarging": 8920
        },
        "battery": {
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
                }
            ],
            "batteryVoltage": 51.2,
            "batteryCurrent": -3.1
        },
        "gridboss": {
            "success": True,
            "fwCode": "IAAB-1300",
            "midboxData": {
                "gridFreq": 5998,
                "gridL1RmsVolt": 2415,
                "gridL1ActivePower": 0,
                "smartPort1Status": 1
            }
        }
    }


@pytest.fixture
def mock_api():
    """Provide a mock EG4InverterAPI instance."""
    api = AsyncMock()
    api.login.return_value = {"success": True, "plants": []}
    api.get_all_device_data.return_value = {"devices": {}}
    api.close.return_value = None
    return api


@pytest.fixture(autouse=True)
def mock_dt_util():
    """Mock dt_util.utcnow() for consistent testing."""
    with patch('homeassistant.util.dt.utcnow') as mock_utcnow:
        from datetime import datetime
        mock_utcnow.return_value = datetime(2023, 9, 11, 12, 0, 0)
        yield mock_utcnow