"""Extended tests for EG4 Data Update Coordinator - Device Processing."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )


@pytest.fixture(autouse=True)
def mock_parameter_refresh():
    """Mock parameter refresh to prevent background tasks."""
    with patch(
        "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def mock_api_calls():
    """Mock API client calls to prevent network requests."""
    with patch(
        "custom_components.eg4_web_monitor.eg4_inverter_api.client.EG4InverterAPI.get_quick_charge_status",
        new_callable=AsyncMock,
        return_value={"status": False},
    ) as mock_quick_charge, patch(
        "custom_components.eg4_web_monitor.eg4_inverter_api.client.EG4InverterAPI.read_parameters",
        new_callable=AsyncMock,
        return_value={"FUNC_EPS_EN": 1},
    ) as mock_read_params:
        yield mock_quick_charge, mock_read_params


class TestCoordinatorInverterProcessing:
    """Test coordinator inverter data processing."""

    async def test_process_inverter_data_with_runtime(
        self, hass, mock_config_entry
    ):
        """Test processing inverter with runtime data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {
                "acPower": 5000,
                "acVoltage": 2405,
                "fwCode": "1.2.3",
            },
            "energy": {
                "todayEnergy": 456,
            },
            "battery": {
                "batteryArray": [],
            },
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        assert result["type"] == "inverter"
        assert result["serial"] == "1234567890"
        assert result["firmware_version"] == "1.2.3"
        assert "sensors" in result
        assert "batteries" in result

    async def test_process_inverter_data_with_batteries(
        self, hass, mock_config_entry
    ):
        """Test processing inverter with battery data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {},
            "energy": {},
            "battery": {
                "batteryArray": [
                    {
                        "batteryKey": "Battery_ID_01",
                        "totalVoltage": 5120,
                        "current": 100,
                        "soc": 85,
                    }
                ],
            },
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        assert "batteries" in result
        # Battery key is cleaned: "Battery_ID_01" -> "1234567890-01"
        assert "1234567890-01" in result["batteries"]

    async def test_process_inverter_data_without_runtime(
        self, hass, mock_config_entry
    ):
        """Test processing inverter without runtime data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "energy": {},
            "battery": {"batteryArray": []},
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        assert result["firmware_version"] == "1.0.0"  # Default value


class TestCoordinatorGridBossProcessing:
    """Test coordinator GridBOSS data processing."""

    async def test_process_gridboss_data(self, hass, mock_config_entry):
        """Test processing GridBOSS device data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "gridboss",
            "model": "GridBOSS",
            "runtime": {
                "gridPower": 3000,
                "loadPower": 2500,
            },
        }

        result = await coordinator._process_gridboss_data("9876543210", device_data)

        assert result["type"] == "gridboss"
        assert result["serial"] == "9876543210"
        assert "sensors" in result


class TestCoordinatorParallelGroupProcessing:
    """Test coordinator parallel group processing."""

    async def test_process_parallel_group_data(self, hass, mock_config_entry):
        """Test processing parallel group data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        parallel_energy = {
            "success": True,
            "totalPower": 15000,
            "todayEnergy": 1234,
        }

        parallel_groups_info = [
            {"groupId": "1", "name": "Group 1"},
        ]

        result = await coordinator._process_parallel_group_data(
            parallel_energy, parallel_groups_info
        )

        assert result["type"] == "parallel_group"
        assert "sensors" in result


class TestCoordinatorModelExtraction:
    """Test coordinator model extraction."""

    async def test_extract_model_from_overview(self, hass, mock_config_entry):
        """Test extracting model from device overview."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set up temp device info
        coordinator._temp_device_info = {
            "1234567890": {"deviceTypeText4APP": "FlexBOSS21"}
        }

        model = coordinator._extract_model_from_overview("1234567890")
        assert model == "FlexBOSS21"

    async def test_extract_model_fallback(self, hass, mock_config_entry):
        """Test model extraction fallback to Unknown."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        coordinator._temp_device_info = {}

        model = coordinator._extract_model_from_overview("unknown_serial")
        assert model == "Unknown"


class TestCoordinatorSensorMapping:
    """Test coordinator sensor field mapping."""

    async def test_runtime_field_mapping(self, hass, mock_config_entry):
        """Test runtime field mapping creates correct sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {
                "acPower": 5000,
                "batVoltage": 512,
                "sysWorkMode": 1,
            },
            "energy": {},
            "battery": {"batteryArray": []},
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        # Sensors should be mapped from API fields
        assert "sensors" in result
        # The exact sensor keys depend on field mapping logic

    async def test_energy_field_mapping(self, hass, mock_config_entry):
        """Test energy field mapping creates correct sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {},
            "energy": {
                "todayEnergy": 456,
                "totalEnergy": 123456,
            },
            "battery": {"batteryArray": []},
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        assert "sensors" in result


class TestCoordinatorErrorHandling:
    """Test coordinator error handling in device processing."""

    async def test_process_device_with_error_flag(
        self, hass, mock_config_entry
    ):
        """Test processing device with error flag."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "devices": {
                "1234567890": {
                    "error": "Device offline",
                    "type": "inverter",
                }
            }
        }

        result = await coordinator._process_device_data(device_data)

        assert "devices" in result
        assert "1234567890" in result["devices"]
        assert result["devices"]["1234567890"]["type"] == "unknown"
        assert "error" in result["devices"]["1234567890"]

    async def test_process_unknown_device_type(
        self, hass, mock_config_entry
    ):
        """Test processing device with unknown type."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "devices": {
                "1234567890": {
                    "type": "unknown_type",
                    "model": "Unknown",
                }
            }
        }

        result = await coordinator._process_device_data(device_data)

        # Should log warning but not crash
        assert "devices" in result


class TestCoordinatorBatteryProcessing:
    """Test coordinator battery data processing."""

    async def test_extract_battery_sensors(self, hass, mock_config_entry):
        """Test extracting battery sensors from battery array."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        battery_data = {
            "batteryKey": "Battery_ID_01",
            "totalVoltage": 5120,
            "current": 100,
            "soc": 85,
            "soh": 98,
            "cycleCnt": 50,
        }

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {},
            "energy": {},
            "battery": {
                "batteryArray": [battery_data],
            },
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        # Battery key is cleaned: "Battery_ID_01" -> "1234567890-01"
        assert "1234567890-01" in result["batteries"]
        battery_sensors = result["batteries"]["1234567890-01"]
        assert "state_of_charge" in battery_sensors
        assert battery_sensors["state_of_charge"] == 85

    async def test_multiple_batteries(self, hass, mock_config_entry):
        """Test processing multiple batteries."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "runtime": {},
            "energy": {},
            "battery": {
                "batteryArray": [
                    {"batteryKey": "Battery_ID_01", "soc": 85},
                    {"batteryKey": "Battery_ID_02", "soc": 82},
                ]
            },
        }

        result = await coordinator._process_inverter_data("1234567890", device_data)

        # Battery keys are cleaned: "Battery_ID_XX" -> "1234567890-XX"
        assert len(result["batteries"]) == 2
        assert "1234567890-01" in result["batteries"]
        assert "1234567890-02" in result["batteries"]


class TestCoordinatorParameterManagement:
    """Test coordinator parameter management."""

    async def test_preserve_existing_parameters(self, hass, mock_config_entry):
        """Test that existing parameters are preserved during update."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set existing data with parameters
        coordinator.data = {
            "parameters": {
                "1234567890": {"charge_power_limit": 5000}
            }
        }

        device_data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            }
        }

        # Mock API calls
        coordinator.api.get_inverter_runtime = AsyncMock(return_value={})
        coordinator.api.get_inverter_energy = AsyncMock(return_value={})
        coordinator.api.get_battery_info = AsyncMock(
            return_value={"batteryArray": []}
        )

        result = await coordinator._process_device_data(device_data)

        # Parameters should be preserved
        assert "parameters" in result
        assert "1234567890" in result["parameters"]


class TestCoordinatorDataStructure:
    """Test coordinator data structure validation."""

    async def test_processed_data_structure(self, hass, mock_config_entry):
        """Test that processed data has correct structure."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {
            "devices": {},
        }

        result = await coordinator._process_device_data(device_data)

        # Verify required top-level keys
        assert "plant_id" in result
        assert result["plant_id"] == "12345"
        assert "devices" in result
        assert "device_info" in result
        assert "last_update" in result

    async def test_last_update_timestamp(self, hass, mock_config_entry):
        """Test that last_update timestamp is set."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        device_data = {"devices": {}}

        result = await coordinator._process_device_data(device_data)

        assert "last_update" in result
        assert isinstance(result["last_update"], datetime)
