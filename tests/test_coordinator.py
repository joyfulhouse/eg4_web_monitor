"""Tests for EG4 Data Update Coordinator with pylxpweb 0.3.5 device objects API."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)


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
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )


@pytest.fixture
def mock_inverter():
    """Create a mock inverter object."""
    mock = MagicMock()
    mock.serial = "INV001"
    mock.serial_number = "INV001"
    mock.model = "FlexBOSS18"
    mock.name = "Test Inverter"
    mock.status = "online"
    mock.power = 5000
    mock.firmware_version = "1.0.0"
    mock.batteries = []
    # Battery bank mock
    mock._battery_bank = MagicMock()
    mock._battery_bank.battery_count = 0
    # Add common properties to avoid MagicMock comparison issues
    mock.input_power = 1000
    mock.feedin_power = 1000
    return mock


@pytest.fixture
def mock_battery():
    """Create a mock battery object."""
    mock = MagicMock()
    mock.serial = "BAT001"
    mock.battery_key = "1"
    mock.voltage = 48.5
    mock.current = 10.2
    mock.soc = 85
    return mock


@pytest.fixture
def mock_station_object(mock_inverter):
    """Create a mock Station object from pylxpweb."""
    mock = MagicMock()
    mock.id = "12345"
    mock.name = "Test Station"
    mock.country = "United States of America"
    mock.timezone = "GMT -8"
    mock.address = "123 Test St"
    mock.createDate = "2025-01-01"
    mock.all_inverters = [mock_inverter]
    mock.all_batteries = []
    mock.refresh_all_data = AsyncMock()
    mock.detect_dst_status = MagicMock(return_value=True)
    mock.sync_dst_setting = AsyncMock(return_value=True)
    return mock


class TestCoordinatorInitialization:
    """Test coordinator initialization."""

    async def test_coordinator_init(self, hass, mock_config_entry):
        """Test coordinator initialization with proper client setup."""
        with patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"):
            coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

            assert coordinator.plant_id == "12345"
            assert coordinator.dst_sync_enabled is True
            assert coordinator.station is None
            assert coordinator.devices == {}


class TestCoordinatorDataFetching:
    """Test coordinator data fetching with device objects API."""

    async def test_initial_station_load(
        self, hass, mock_config_entry, mock_station_object
    ):
        """Test initial station load using Station.load()."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock Station.load to return our mock station
        with patch(
            "custom_components.eg4_web_monitor.coordinator.Station.load",
            new=AsyncMock(return_value=mock_station_object),
        ):
            await coordinator._async_update_data()

            # Verify Station.load was called
            assert coordinator.station is not None
            assert coordinator.station.id == "12345"
            # Verify refresh_all_data was called after load
            mock_station_object.refresh_all_data.assert_called()

    async def test_subsequent_station_refresh(
        self, hass, mock_config_entry, mock_station_object
    ):
        """Test subsequent data updates use refresh_all_data()."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.station = mock_station_object

        await coordinator._async_update_data()

        # Verify refresh_all_data was called (not load)
        mock_station_object.refresh_all_data.assert_called()

    async def test_fetch_data_auth_error(self, hass, mock_config_entry):
        """Test auth error raises ConfigEntryAuthFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock Station.load to raise auth error
        with patch(
            "custom_components.eg4_web_monitor.coordinator.Station.load",
            side_effect=LuxpowerAuthError("Invalid credentials"),
        ):
            with pytest.raises(ConfigEntryAuthFailed):
                await coordinator._async_update_data()

            # Verify availability state changed
            assert coordinator._last_available_state is False

    async def test_fetch_data_connection_error(self, hass, mock_config_entry):
        """Test connection error raises UpdateFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock Station.load to raise connection error
        with patch(
            "custom_components.eg4_web_monitor.coordinator.Station.load",
            side_effect=LuxpowerConnectionError("Connection timeout"),
        ):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    async def test_fetch_data_api_error(self, hass, mock_config_entry):
        """Test API error raises UpdateFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock Station.load to raise API error
        with patch(
            "custom_components.eg4_web_monitor.coordinator.Station.load",
            side_effect=LuxpowerAPIError("API error"),
        ):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()


class TestDSTSynchronization:
    """Test DST synchronization feature."""

    async def test_dst_sync_enabled_configuration(self, hass, mock_config_entry):
        """Test DST sync is enabled when configured."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        assert coordinator.dst_sync_enabled is True

    async def test_dst_sync_disabled_configuration(self, hass):
        """Test DST sync is disabled when configured."""
        # Create entry with DST sync disabled
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Web Monitor - Test Plant",
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_pass",
                CONF_BASE_URL: "https://monitor.eg4electronics.com",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_PLANT_ID: "12345",
                CONF_PLANT_NAME: "Test Plant",
            },
            entry_id="test_entry_id",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        assert coordinator.dst_sync_enabled is False

    async def test_dst_sync_should_sync_timing(self, hass, mock_config_entry):
        """Test DST sync timing window detection."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator._last_dst_sync = None

        # Within 1 minute before hour boundary (timezone-aware)
        time_near_hour = dt_util.parse_datetime("2025-01-01T12:59:30+00:00")
        with patch(
            "custom_components.eg4_web_monitor.coordinator.dt_util.utcnow",
            return_value=time_near_hour,
        ):
            assert coordinator._should_sync_dst() is True

        # Far from hour boundary (timezone-aware)
        time_mid_hour = dt_util.parse_datetime("2025-01-01T12:30:00+00:00")
        with patch(
            "custom_components.eg4_web_monitor.coordinator.dt_util.utcnow",
            return_value=time_mid_hour,
        ):
            assert coordinator._should_sync_dst() is False


class TestParameterRefresh:
    """Test hourly parameter refresh."""

    async def test_parameter_refresh_when_due(
        self, hass, mock_config_entry, mock_station_object
    ):
        """Test parameter refresh runs when due."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.station = mock_station_object

        # Set last refresh to more than 1 hour ago
        coordinator._last_parameter_refresh = dt_util.utcnow() - timedelta(hours=2)

        with patch.object(coordinator, "_hourly_parameter_refresh", new=AsyncMock()):
            await coordinator._async_update_data()

            # Verify refresh task was created (can't directly assert on task creation)
            # but we can verify _should_refresh_parameters returned True
            assert coordinator._should_refresh_parameters()

    async def test_parameter_refresh_not_due(
        self, hass, mock_config_entry, mock_station_object
    ):
        """Test parameter refresh doesn't run when not due."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.station = mock_station_object

        # Set last refresh to recent
        coordinator._last_parameter_refresh = dt_util.utcnow()

        # Should not refresh when just refreshed
        assert not coordinator._should_refresh_parameters()


class TestCoordinatorCleanup:
    """Test coordinator cleanup and shutdown."""

    async def test_async_shutdown_exists(self, hass, mock_config_entry):
        """Test async_shutdown method exists and is callable."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Verify shutdown method exists
        assert hasattr(coordinator, "async_shutdown")
        assert callable(coordinator.async_shutdown)

        # Call shutdown - should not raise
        await coordinator.async_shutdown()

    async def test_client_close_on_shutdown(self, hass, mock_config_entry):
        """Test client.close() is available for shutdown."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Verify client has close method
        assert hasattr(coordinator.client, "close")
        assert callable(coordinator.client.close)


class TestDeviceInfo:
    """Test device info generation methods."""

    async def test_parallel_group_device_name_includes_letter(
        self, hass, mock_config_entry
    ):
        """Test parallel group device name includes the group letter."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "parallel_group_INV001": {
                    "type": "parallel_group",
                    "name": "Parallel Group A",
                    "model": "Parallel Group",
                }
            }
        }

        device_info = coordinator.get_device_info("parallel_group_INV001")

        assert device_info is not None
        assert device_info["name"] == "Parallel Group A"
        assert device_info["model"] == "Parallel Group"

    async def test_parallel_group_device_name_fallback(self, hass, mock_config_entry):
        """Test parallel group device name falls back to model when name missing."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "parallel_group_INV001": {
                    "type": "parallel_group",
                    "model": "Parallel Group",
                    # No "name" field
                }
            }
        }

        device_info = coordinator.get_device_info("parallel_group_INV001")

        assert device_info is not None
        assert device_info["name"] == "Parallel Group"
        assert device_info["model"] == "Parallel Group"

    async def test_parallel_group_multiple_groups_distinct_names(
        self, hass, mock_config_entry
    ):
        """Test multiple parallel groups have distinct names."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "parallel_group_INV001": {
                    "type": "parallel_group",
                    "name": "Parallel Group A",
                    "model": "Parallel Group",
                },
                "parallel_group_INV002": {
                    "type": "parallel_group",
                    "name": "Parallel Group B",
                    "model": "Parallel Group",
                },
            }
        }

        device_info_a = coordinator.get_device_info("parallel_group_INV001")
        device_info_b = coordinator.get_device_info("parallel_group_INV002")

        assert device_info_a["name"] == "Parallel Group A"
        assert device_info_b["name"] == "Parallel Group B"
        # Both should have the same model
        assert device_info_a["model"] == "Parallel Group"
        assert device_info_b["model"] == "Parallel Group"

    async def test_inverter_device_name_includes_serial(self, hass, mock_config_entry):
        """Test inverter device name includes model and serial."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "name": "Test Inverter",
                    "model": "FlexBOSS 18K",
                }
            }
        }

        device_info = coordinator.get_device_info("1234567890")

        assert device_info is not None
        assert device_info["name"] == "FlexBOSS 18K 1234567890"
        assert device_info["model"] == "FlexBOSS 18K"
        assert device_info["serial_number"] == "1234567890"

    async def test_gridboss_device_name_includes_serial(self, hass, mock_config_entry):
        """Test GridBOSS device name includes model and serial."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "9876543210": {
                    "type": "gridboss",
                    "name": "GridBOSS",
                    "model": "GridBOSS MID",
                }
            }
        }

        device_info = coordinator.get_device_info("9876543210")

        assert device_info is not None
        assert device_info["name"] == "GridBOSS MID 9876543210"
        assert device_info["model"] == "GridBOSS MID"
        assert device_info["serial_number"] == "9876543210"

    async def test_get_device_info_returns_none_for_missing_device(
        self, hass, mock_config_entry
    ):
        """Test get_device_info returns None for non-existent device."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {"devices": {}}

        device_info = coordinator.get_device_info("nonexistent")

        assert device_info is None

    async def test_get_device_info_returns_none_when_no_data(
        self, hass, mock_config_entry
    ):
        """Test get_device_info returns None when coordinator has no data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = None

        device_info = coordinator.get_device_info("1234567890")

        assert device_info is None


class TestParallelGroupBatteryCount:
    """Test parallel group battery count aggregation."""

    async def test_parallel_group_battery_count_uses_battery_bank_count(
        self, hass, mock_config_entry
    ):
        """Test parallel group sums battery_bank_count from sensors, not batteries dict.

        For LXP-EU devices, the batteries dict may be empty when CAN bus
        communication with battery BMS isn't established, but battery_bank_count
        (from Modbus register 96 or cloud batParallelNum) is correct.
        """
        # Add config entry to hass for device registry access
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Create processed data with two inverters in a parallel group
        # Each has battery_bank_count=3 but empty batteries dict (simulating LXP-EU)
        processed = {
            "devices": {
                "INV001": {
                    "type": "inverter",
                    "parallel_number": 1,  # In parallel group 1
                    "parallel_master_slave": 1,  # Master
                    "sensors": {
                        "battery_bank_count": 3,  # Has 3 batteries
                        "battery_soc": 50,
                        "battery_voltage": 52.0,
                        "battery_charge_power": 500,
                        "battery_discharge_power": 0,
                    },
                    "batteries": {},  # Empty - no CAN bus data
                },
                "INV002": {
                    "type": "inverter",
                    "parallel_number": 1,  # Same parallel group
                    "parallel_master_slave": 2,  # Slave
                    "sensors": {
                        "battery_bank_count": 3,  # Has 3 batteries
                        "battery_soc": 55,
                        "battery_voltage": 52.5,
                        "battery_charge_power": 600,
                        "battery_discharge_power": 0,
                    },
                    "batteries": {},  # Empty - no CAN bus data
                },
            }
        }

        # Process the parallel groups
        await coordinator._process_local_parallel_groups(processed)

        # Check the parallel group device was created with correct battery count
        parallel_group = processed["devices"].get("parallel_group_INV001")
        assert parallel_group is not None
        assert parallel_group["type"] == "parallel_group"

        # Battery count should be 6 (3 + 3), not 0 (empty batteries dicts)
        sensors = parallel_group.get("sensors", {})
        assert sensors.get("parallel_battery_count") == 6

    async def test_parallel_group_battery_count_handles_none_values(
        self, hass, mock_config_entry
    ):
        """Test parallel group handles None battery_bank_count gracefully."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        processed = {
            "devices": {
                "INV001": {
                    "type": "inverter",
                    "parallel_number": 1,
                    "parallel_master_slave": 1,
                    "sensors": {
                        "battery_bank_count": 2,
                        "battery_soc": 50,
                    },
                    "batteries": {},
                },
                "INV002": {
                    "type": "inverter",
                    "parallel_number": 1,
                    "parallel_master_slave": 2,
                    "sensors": {
                        "battery_bank_count": None,  # Unknown
                        "battery_soc": 55,
                    },
                    "batteries": {},
                },
            }
        }

        await coordinator._process_local_parallel_groups(processed)

        parallel_group = processed["devices"].get("parallel_group_INV001")
        assert parallel_group is not None

        # Should only count the valid battery_bank_count (2), not None
        sensors = parallel_group.get("sensors", {})
        assert sensors.get("parallel_battery_count") == 2

    async def test_parallel_group_battery_count_handles_zero_values(
        self, hass, mock_config_entry
    ):
        """Test parallel group skips zero battery_bank_count values."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        processed = {
            "devices": {
                "INV001": {
                    "type": "inverter",
                    "parallel_number": 1,
                    "parallel_master_slave": 1,
                    "sensors": {
                        "battery_bank_count": 3,
                        "battery_soc": 50,
                    },
                    "batteries": {},
                },
                "INV002": {
                    "type": "inverter",
                    "parallel_number": 1,
                    "parallel_master_slave": 2,
                    "sensors": {
                        "battery_bank_count": 0,  # No batteries (or BMS issue)
                        "battery_soc": 55,
                    },
                    "batteries": {},
                },
            }
        }

        await coordinator._process_local_parallel_groups(processed)

        parallel_group = processed["devices"].get("parallel_group_INV001")
        assert parallel_group is not None

        # Should only count non-zero values (3), not 0
        sensors = parallel_group.get("sensors", {})
        assert sensors.get("parallel_battery_count") == 3
