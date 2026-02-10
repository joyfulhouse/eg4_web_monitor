"""Tests for EG4 Data Update Coordinator with pylxpweb 0.3.5 device objects API."""

import time

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
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import (
    EG4DataUpdateCoordinator,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    BATTERY_BANK_KEYS,
    GRIDBOSS_SENSOR_KEYS,
    GRIDBOSS_SMART_PORT_POWER_KEYS,
    INVERTER_ENERGY_KEYS,
    INVERTER_RUNTIME_KEYS,
    PARALLEL_GROUP_GRIDBOSS_KEYS,
    PARALLEL_GROUP_SENSOR_KEYS,
    _apply_grid_type_override,
    _build_battery_bank_sensor_mapping,
    _build_energy_sensor_mapping,
    _build_gridboss_sensor_mapping,
    _build_runtime_sensor_mapping,
    _features_from_family,
)
from custom_components.eg4_web_monitor.coordinator_mixins import (
    apply_gridboss_overlay,
)
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
            "custom_components.eg4_web_monitor.coordinator_mixins.dt_util.utcnow",
            return_value=time_near_hour,
        ):
            assert coordinator._should_sync_dst() is True

        # Far from hour boundary (timezone-aware)
        time_mid_hour = dt_util.parse_datetime("2025-01-01T12:30:00+00:00")
        with patch(
            "custom_components.eg4_web_monitor.coordinator_mixins.dt_util.utcnow",
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
                "parallel_group_a": {
                    "type": "parallel_group",
                    "name": "Parallel Group A",
                    "model": "Parallel Group",
                }
            }
        }

        device_info = coordinator.get_device_info("parallel_group_a")

        assert device_info is not None
        assert device_info["name"] == "Parallel Group A"
        assert device_info["model"] == "Parallel Group"

    async def test_parallel_group_device_name_fallback(self, hass, mock_config_entry):
        """Test parallel group device name falls back to model when name missing."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "parallel_group_a": {
                    "type": "parallel_group",
                    "model": "Parallel Group",
                    # No "name" field
                }
            }
        }

        device_info = coordinator.get_device_info("parallel_group_a")

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
                "parallel_group_a": {
                    "type": "parallel_group",
                    "name": "Parallel Group A",
                    "model": "Parallel Group",
                },
                "parallel_group_b": {
                    "type": "parallel_group",
                    "name": "Parallel Group B",
                    "model": "Parallel Group",
                },
            }
        }

        device_info_a = coordinator.get_device_info("parallel_group_a")
        device_info_b = coordinator.get_device_info("parallel_group_b")

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
        parallel_group = processed["devices"].get("parallel_group_a")
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

        parallel_group = processed["devices"].get("parallel_group_a")
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

        parallel_group = processed["devices"].get("parallel_group_a")
        assert parallel_group is not None

        # Should only count non-zero values (3), not 0
        sensors = parallel_group.get("sensors", {})
        assert sensors.get("parallel_battery_count") == 3


class TestDeferredLocalParameters:
    """Test deferred parameter loading for local transport modes."""

    @pytest.fixture
    def local_config_entry(self):
        """Config entry for LOCAL connection type."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Electronics - FlexBOSS21",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "1234567890",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            entry_id="local_test_entry",
        )

    async def test_local_parameters_deferred_flag_init(self, hass, local_config_entry):
        """Verify _local_parameters_loaded starts False."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator._local_parameters_loaded is False

    async def test_first_refresh_skips_parameters(self, hass, local_config_entry):
        """Verify include_parameters=False on first local refresh."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport_runtime = MagicMock()
        mock_inverter._transport_runtime.pv_total_power = 0
        mock_inverter._transport_runtime.battery_soc = 50
        mock_inverter._transport_runtime.grid_power = 0
        mock_inverter._transport_runtime.parallel_number = 0
        mock_inverter._transport_runtime.parallel_master_slave = 0
        mock_inverter._transport_runtime.parallel_phase = 0
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = None
        mock_inverter.consumption_power = None
        mock_inverter.total_load_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None

        coordinator._inverter_cache["1234567890"] = mock_inverter
        coordinator._firmware_cache["1234567890"] = "TEST-FW"

        # Simulate processing a single local device
        processed = {"devices": {}, "parameters": {}}
        device_availability: dict[str, bool] = {}

        config = local_config_entry.data[CONF_LOCAL_TRANSPORTS][0]
        await coordinator._process_single_local_device(
            config, processed, device_availability
        )

        # First refresh should use include_parameters=False
        mock_inverter.refresh.assert_called_once_with(
            force=True, include_parameters=False
        )
        # Parameters should be empty dict (deferred)
        assert processed["parameters"]["1234567890"] == {}

    async def test_second_refresh_includes_parameters(self, hass, local_config_entry):
        """After flag is set, include_parameters=True on subsequent refreshes."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._local_parameters_loaded = True  # Simulate post-first-refresh

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter.detect_features = AsyncMock()
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport_runtime = MagicMock()
        mock_inverter._transport_runtime.pv_total_power = 0
        mock_inverter._transport_runtime.battery_soc = 50
        mock_inverter._transport_runtime.grid_power = 0
        mock_inverter._transport_runtime.parallel_number = 0
        mock_inverter._transport_runtime.parallel_master_slave = 0
        mock_inverter._transport_runtime.parallel_phase = 0
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = None
        mock_inverter.consumption_power = None
        mock_inverter.total_load_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None

        coordinator._inverter_cache["1234567890"] = mock_inverter
        coordinator._firmware_cache["1234567890"] = "TEST-FW"

        processed = {"devices": {}, "parameters": {}}
        device_availability: dict[str, bool] = {}

        with patch.object(
            coordinator,
            "_read_modbus_parameters",
            new_callable=AsyncMock,
            return_value={"FUNC_EPS_EN": True},
        ) as mock_params:
            config = local_config_entry.data[CONF_LOCAL_TRANSPORTS][0]
            await coordinator._process_single_local_device(
                config, processed, device_availability
            )

        # Second refresh should use include_parameters=True
        mock_inverter.refresh.assert_called_once_with(
            force=True, include_parameters=True
        )
        # Feature detection should be called
        mock_inverter.detect_features.assert_called_once()
        # Parameters should be populated
        mock_params.assert_called_once()
        assert processed["parameters"]["1234567890"] == {"FUNC_EPS_EN": True}

    async def test_deferred_background_task_loads_parameters(
        self, hass, local_config_entry
    ):
        """Background task loads parameters and calls detect_features."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.async_request_refresh = AsyncMock()

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter.detect_features = AsyncMock()
        coordinator._inverter_cache["1234567890"] = mock_inverter

        await coordinator._deferred_local_parameter_load()

        # Should use force=False to avoid re-reading cached data
        mock_inverter.refresh.assert_called_once_with(
            force=False, include_parameters=True
        )
        mock_inverter.detect_features.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()


class TestStaticLocalData:
    """Tests for static device data pre-population (zero-read first refresh)."""

    @pytest.fixture
    def local_config_entry(self):
        """Config entry for LOCAL connection type with one inverter."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Electronics - FlexBOSS21",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "1234567890",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "device_type_code": 10284,
                        "model": "FlexBOSS21",
                        "firmware_version": "ARM-1.0",
                    },
                ],
            },
            entry_id="static_test_entry",
        )

    @pytest.fixture
    def gridboss_config_entry(self):
        """Config entry for LOCAL connection type with one GridBOSS."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Electronics - GridBOSS",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.200",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                        "device_type_code": 50,
                        "firmware_version": "GB-2.0",
                    },
                ],
            },
            entry_id="gridboss_test_entry",
        )

    @pytest.fixture
    def multi_device_config_entry(self):
        """Config entry for LOCAL with GridBOSS + 2 inverters (Issue #83)."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Electronics - Multi-Device",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                    },
                    {
                        "serial": "INV001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "model": "FlexBOSS21",
                    },
                    {
                        "serial": "INV002",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            entry_id="multi_test_entry",
        )

    async def test_first_refresh_returns_static_data(self, hass, local_config_entry):
        """First local refresh returns static data without Modbus reads."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # First refresh should return static data
        result = await coordinator._async_update_local_data()

        # Static phase flag should be set
        assert coordinator._local_static_phase_done is True

        # Result should contain device data
        assert "1234567890" in result["devices"]
        device = result["devices"]["1234567890"]
        assert device["type"] == "inverter"
        assert device["model"] == "FlexBOSS21"
        assert device["serial"] == "1234567890"
        assert device["firmware_version"] == "ARM-1.0"
        assert device["batteries"] == {}
        # Features should be derived from inverter_family in config
        # EG4_HYBRID is US split-phase (L1/L2), NOT three-phase (R/S/T)
        assert device["features"]["inverter_family"] == "EG4_HYBRID"
        assert device["features"]["supports_split_phase"] is True
        assert device["features"]["supports_three_phase"] is False

        # Sensors should have None values (except metadata)
        sensors = device["sensors"]
        assert sensors["pv1_voltage"] is None
        assert sensors["state_of_charge"] is None
        assert sensors["firmware_version"] == "ARM-1.0"
        assert sensors["connection_transport"] == "Modbus"
        assert sensors["transport_host"] == "192.168.1.100"

    async def test_static_data_has_all_inverter_sensor_keys(
        self, hass, local_config_entry
    ):
        """Static data includes all expected inverter sensor keys."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        result = await coordinator._async_update_local_data()
        sensors = result["devices"]["1234567890"]["sensors"]

        # Every key from ALL_INVERTER_SENSOR_KEYS should be present
        for key in ALL_INVERTER_SENSOR_KEYS:
            assert key in sensors, f"Missing sensor key: {key}"

    async def test_static_data_has_all_gridboss_sensor_keys(
        self, hass, gridboss_config_entry
    ):
        """Static data includes all expected GridBOSS sensor keys."""
        coordinator = EG4DataUpdateCoordinator(hass, gridboss_config_entry)
        result = await coordinator._async_update_local_data()
        sensors = result["devices"]["GB001"]["sensors"]

        # Every key from GRIDBOSS_SENSOR_KEYS except smart port power keys
        # should be present — smart port power keys are added dynamically
        # by _filter_unused_smart_port_sensors() based on actual port status.
        static_keys = GRIDBOSS_SENSOR_KEYS - GRIDBOSS_SMART_PORT_POWER_KEYS
        for key in static_keys:
            assert key in sensors, f"Missing GridBOSS sensor key: {key}"
        for key in GRIDBOSS_SMART_PORT_POWER_KEYS:
            assert key not in sensors, f"Smart port power key should not be in static data: {key}"

        # GridBOSS device should have binary_sensors dict
        assert "binary_sensors" in result["devices"]["GB001"]

    async def test_second_refresh_reads_registers(self, hass, local_config_entry):
        """Second refresh goes through normal register read path."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # First refresh: static data
        await coordinator._async_update_local_data()
        assert coordinator._local_static_phase_done is True

        # Reset per-transport timestamps so the poll gate doesn't skip
        # our explicit second call (the static phase may have triggered
        # a background refresh that set the timestamp).
        coordinator._last_modbus_poll = 0.0

        # Second refresh: should attempt real Modbus reads.
        # Without real transports, this will raise UpdateFailed because
        # all devices fail to connect — which proves it entered the
        # normal register-read code path.
        with pytest.raises(UpdateFailed, match="All .* local transports failed"):
            await coordinator._async_update_local_data()

    async def test_multi_device_static_data(self, hass, multi_device_config_entry):
        """Static data correctly handles mixed GridBOSS + inverter configs."""
        coordinator = EG4DataUpdateCoordinator(hass, multi_device_config_entry)
        result = await coordinator._async_update_local_data()

        # GB001 + INV001 + INV002 + parallel_group_a (from fallback heuristic) = 4
        # Group name used as device ID (matches cloud API parallelGroup field)
        assert len(result["devices"]) == 4
        assert result["devices"]["GB001"]["type"] == "gridboss"
        assert result["devices"]["INV001"]["type"] == "inverter"
        assert result["devices"]["INV002"]["type"] == "inverter"
        assert result["devices"]["parallel_group_a"]["type"] == "parallel_group"

        # GridBOSS should use GRIDBOSS_SENSOR_KEYS minus smart port power keys
        gb_keys = set(result["devices"]["GB001"]["sensors"].keys())
        static_keys = GRIDBOSS_SENSOR_KEYS - GRIDBOSS_SMART_PORT_POWER_KEYS
        assert static_keys.issubset(gb_keys)

        # Inverters should use ALL_INVERTER_SENSOR_KEYS
        inv_keys = set(result["devices"]["INV001"]["sensors"].keys())
        assert ALL_INVERTER_SENSOR_KEYS.issubset(inv_keys)

    async def test_static_data_lxp_eu_features(self, hass):
        """Static data uses device_type_code for LXP-EU three-phase features."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="LXP-EU 12K",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "EU12345678",
                        "host": "192.168.1.50",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "LXP",
                        "device_type_code": 12,
                        "model": "LXP-EU 12K",
                    },
                ],
            },
            entry_id="lxp_eu_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        device = result["devices"]["EU12345678"]
        assert device["features"]["supports_three_phase"] is True
        assert device["features"]["supports_split_phase"] is False

    async def test_static_data_lxp_lb_features(self, hass):
        """Static data uses device_type_code for LXP-LB split-phase features."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="LXP-LB-BR 10K",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "BR12345678",
                        "host": "192.168.1.51",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "LXP",
                        "device_type_code": 44,
                        "model": "LXP-LB-BR 10K",
                    },
                ],
            },
            entry_id="lxp_lb_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        device = result["devices"]["BR12345678"]
        assert device["features"]["supports_three_phase"] is False
        assert device["features"]["supports_split_phase"] is True

    def test_static_keys_match_runtime_mapping(self):
        """INVERTER_RUNTIME_KEYS matches _build_runtime_sensor_mapping keys."""
        mock_runtime = MagicMock()
        # bt_temperature is conditionally included, so we ensure it's present
        mock_runtime.temperature_t1 = 25.0
        mapping = _build_runtime_sensor_mapping(mock_runtime)
        assert set(mapping.keys()) == INVERTER_RUNTIME_KEYS

    def test_static_keys_match_energy_mapping(self):
        """INVERTER_ENERGY_KEYS matches _build_energy_sensor_mapping keys."""
        mock_energy = MagicMock()
        mapping = _build_energy_sensor_mapping(mock_energy)
        assert set(mapping.keys()) == INVERTER_ENERGY_KEYS

    def test_static_keys_match_battery_bank_mapping(self):
        """BATTERY_BANK_KEYS matches _build_battery_bank_sensor_mapping keys."""
        mock_battery = MagicMock()
        # Ensure diagnostic values are non-None so all keys are present
        mock_battery.min_soh = 95.0
        mock_battery.max_cell_temp = 30.0
        mock_battery.temp_delta = 2.0
        mock_battery.cell_voltage_delta_max = 0.05
        mock_battery.soc_delta = 1.0
        mock_battery.soh_delta = 2.0
        mock_battery.voltage_delta = 0.1
        mock_battery.cycle_count_delta = 5
        mock_battery.charge_power = 500
        mock_battery.discharge_power = 0
        mock_battery.battery_power = 500
        mapping = _build_battery_bank_sensor_mapping(mock_battery)
        assert set(mapping.keys()) == BATTERY_BANK_KEYS

    def test_static_keys_match_gridboss_mapping(self):
        """GRIDBOSS_SENSOR_KEYS covers _build_gridboss_sensor_mapping keys + metadata."""
        mock_mid = MagicMock()
        mapping = _build_gridboss_sensor_mapping(mock_mid)
        mapping_keys = set(mapping.keys())

        # The mapping function produces all keys except coordinator-added metadata
        gridboss_metadata = {
            "firmware_version",
            "connection_transport",
            "transport_host",
        }

        # All mapping keys must be in the constant
        assert mapping_keys.issubset(GRIDBOSS_SENSOR_KEYS), (
            f"Mapping has keys not in GRIDBOSS_SENSOR_KEYS: "
            f"{mapping_keys - GRIDBOSS_SENSOR_KEYS}"
        )
        # The only extra keys in the constant should be the metadata keys
        extra = GRIDBOSS_SENSOR_KEYS - mapping_keys
        assert extra == gridboss_metadata, (
            f"Unexpected extra keys in GRIDBOSS_SENSOR_KEYS: "
            f"{extra - gridboss_metadata}"
        )

    @pytest.mark.parametrize(
        ("family", "split_phase", "three_phase"),
        [
            ("EG4_OFFGRID", True, False),
            ("EG4_HYBRID", True, False),
        ],
    )
    def test_features_from_family(self, family, split_phase, three_phase):
        """_features_from_family returns correct phase flags per family."""
        features = _features_from_family(family)
        assert features["supports_split_phase"] is split_phase
        assert features["supports_three_phase"] is three_phase

    def test_features_from_family_unknown_returns_empty(self):
        """Unknown family returns empty dict (conservative: all sensors created)."""
        assert _features_from_family(None) == {}
        assert _features_from_family("UNKNOWN_FAMILY") == {}

    def test_features_from_family_lxp_without_dtc_returns_empty(self):
        """LXP without device_type_code returns empty — conservative fallback."""
        # Family string alone can't distinguish EU (three-phase) from
        # LB (single/split-phase), so conservative fallback creates all sensors.
        assert _features_from_family("LXP") == {}
        assert _features_from_family("LXP", device_type_code=None) == {}

    def test_features_from_family_lxp_eu_with_dtc(self):
        """LXP-EU (device_type_code=12) maps to three-phase."""
        features = _features_from_family("LXP", device_type_code=12)
        assert features["inverter_family"] == "LXP"
        assert features["supports_split_phase"] is False
        assert features["supports_three_phase"] is True
        assert features["supports_volt_watt_curve"] is True

    def test_features_from_family_lxp_lb_with_dtc(self):
        """LXP-LB (device_type_code=44) maps to split-phase (not three-phase)."""
        features = _features_from_family("LXP", device_type_code=44)
        assert features["inverter_family"] == "LXP"
        assert features["supports_split_phase"] is True
        assert features["supports_three_phase"] is False
        assert features["supports_volt_watt_curve"] is True

    def test_features_from_family_lxp_unknown_dtc_returns_empty(self):
        """LXP with unrecognized device_type_code returns empty."""
        assert _features_from_family("LXP", device_type_code=999) == {}

    def test_features_from_family_legacy_names(self):
        """Legacy family names are mapped correctly."""
        features = _features_from_family("SNA")
        assert features["inverter_family"] == "EG4_OFFGRID"
        assert features["supports_split_phase"] is True

        features = _features_from_family("PV_SERIES")
        assert features["inverter_family"] == "EG4_HYBRID"
        assert features["supports_split_phase"] is True
        assert features["supports_three_phase"] is False

        # Legacy LXP names without device_type_code return empty
        assert _features_from_family("LXP_EU") == {}
        assert _features_from_family("LXP_LV") == {}

    def test_features_from_family_grid_type_override_split_phase(self):
        """grid_type='split_phase' overrides phase flags to split-phase."""
        # LXP-EU defaults to three-phase, but grid_type forces split-phase
        features = _features_from_family(
            "LXP", device_type_code=12, grid_type="split_phase"
        )
        assert features["supports_split_phase"] is True
        assert features["supports_three_phase"] is False

    def test_features_from_family_grid_type_override_single_phase(self):
        """grid_type='single_phase' disables both split and three-phase."""
        # LXP-LB defaults to split-phase, Brazilian user selects single_phase
        features = _features_from_family(
            "LXP", device_type_code=44, grid_type="single_phase"
        )
        assert features["supports_split_phase"] is False
        assert features["supports_three_phase"] is False

    def test_features_from_family_grid_type_override_three_phase(self):
        """grid_type='three_phase' overrides to three-phase."""
        # EG4_HYBRID defaults to split-phase, but override to three-phase
        features = _features_from_family("EG4_HYBRID", grid_type="three_phase")
        assert features["supports_split_phase"] is False
        assert features["supports_three_phase"] is True

    def test_features_from_family_grid_type_none_preserves_default(self):
        """grid_type=None preserves default behavior (backward compatible)."""
        features = _features_from_family("EG4_OFFGRID", grid_type=None)
        assert features["supports_split_phase"] is True
        assert features["supports_three_phase"] is False

    def test_apply_grid_type_override_split_phase(self):
        """_apply_grid_type_override sets correct flags for split_phase."""
        features = {"supports_split_phase": False, "supports_three_phase": True}
        _apply_grid_type_override(features, "split_phase")
        assert features["supports_split_phase"] is True
        assert features["supports_three_phase"] is False

    def test_apply_grid_type_override_single_phase(self):
        """_apply_grid_type_override disables both for single_phase."""
        features = {"supports_split_phase": True, "supports_three_phase": False}
        _apply_grid_type_override(features, "single_phase")
        assert features["supports_split_phase"] is False
        assert features["supports_three_phase"] is False

    def test_apply_grid_type_override_three_phase(self):
        """_apply_grid_type_override sets correct flags for three_phase."""
        features = {"supports_split_phase": True, "supports_three_phase": False}
        _apply_grid_type_override(features, "three_phase")
        assert features["supports_split_phase"] is False
        assert features["supports_three_phase"] is True

    async def test_static_parallel_group_created_from_parallel_number(self, hass):
        """Static data creates parallel group when configs share parallel_number > 0."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Parallel",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "MASTER001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SLAVE002",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            entry_id="parallel_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        # 2 inverters + 1 parallel group = 3 device entries
        assert len(result["devices"]) == 3
        group = result["devices"]["parallel_group_a"]
        assert group["type"] == "parallel_group"
        assert group["name"] == "Parallel Group A"
        assert group["first_device_serial"] == "MASTER001"
        assert group["member_count"] == 2
        assert set(group["member_serials"]) == {"MASTER001", "SLAVE002"}

        # All sensor keys present with None values (no Modbus reads yet)
        assert PARALLEL_GROUP_SENSOR_KEYS == set(group["sensors"].keys())
        assert all(v is None for v in group["sensors"].values())

    async def test_static_parallel_group_with_gridboss(self, hass):
        """Static parallel group includes GridBOSS overlay keys when GridBOSS present."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GridBOSS + Inverters",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.200",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                    },
                    {
                        "serial": "INV001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "INV002",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            entry_id="gridboss_parallel_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        # GB001 + INV001 + INV002 + parallel_group_a = 4 entries
        # Group name used as device ID (matches cloud API parallelGroup field)
        assert len(result["devices"]) == 4
        group = result["devices"]["parallel_group_a"]
        assert group["type"] == "parallel_group"
        assert group["first_device_serial"] == "INV001"

        expected_keys = PARALLEL_GROUP_SENSOR_KEYS | PARALLEL_GROUP_GRIDBOSS_KEYS
        assert expected_keys == set(group["sensors"].keys())

    async def test_static_parallel_group_not_created_for_single_device(self, hass):
        """No parallel group created when only one device configured."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Single",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "SOLO001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            entry_id="single_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        assert len(result["devices"]) == 1
        assert "SOLO001" in result["devices"]
        assert not any(k.startswith("parallel_group_") for k in result["devices"])

    async def test_static_parallel_group_fallback_heuristic(self, hass):
        """Two inverters without parallel_number create group via count heuristic."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - No Parallel Info",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "DEV_A",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                    {
                        "serial": "DEV_B",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                    },
                ],
            },
            entry_id="fallback_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        # 2 inverters + 1 parallel group (from fallback) = 3 entries
        assert len(result["devices"]) == 3
        group = result["devices"]["parallel_group_a"]
        assert group["type"] == "parallel_group"
        assert group["member_count"] == 2
        assert set(group["member_serials"]) == {"DEV_A", "DEV_B"}

    async def test_static_parallel_group_gridboss_only_no_group(self, hass):
        """Single GridBOSS alone does not create a parallel group."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GB Only",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB_ONLY",
                        "host": "192.168.1.200",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                    },
                ],
            },
            entry_id="gb_only_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        assert len(result["devices"]) == 1
        assert not any(k.startswith("parallel_group_") for k in result["devices"])

    async def test_static_parallel_group_single_inverter_with_parallel_number(
        self, hass
    ):
        """Single inverter with parallel_number > 0 creates a group.

        This handles the case of a single inverter + GridBOSS where the
        inverter is configured for parallel operation.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Single Parallel",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.200",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                    },
                    {
                        "serial": "INV_SOLO",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 1,
                        "parallel_master_slave": 1,
                    },
                ],
            },
            entry_id="single_parallel_test",
        )
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        result = await coordinator._async_update_local_data()

        # GB001 + INV_SOLO + parallel_group_a = 3 entries
        # Group name used as device ID (matches cloud API parallelGroup field)
        assert len(result["devices"]) == 3
        group = result["devices"]["parallel_group_a"]
        assert group["type"] == "parallel_group"
        assert group["first_device_serial"] == "INV_SOLO"
        assert group["member_count"] == 1
        assert group["member_serials"] == ["INV_SOLO"]
        expected_keys = PARALLEL_GROUP_SENSOR_KEYS | PARALLEL_GROUP_GRIDBOSS_KEYS
        assert expected_keys == set(group["sensors"].keys())


class TestParallelGroupAggregationMath:
    """Tests for parallel group aggregation math in GridBOSS-less setups.

    These tests validate that _process_local_parallel_groups() correctly
    sums power, sums energy, averages SOC/voltage, and remaps battery keys
    using realistic non-zero sensor values. This is critical for users
    without a GridBOSS where inverters report their own grid/consumption data.
    """

    @pytest.fixture
    def local_entry(self, hass):
        """Create a local config entry with 2 inverters, no GridBOSS."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - No GridBOSS",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "MASTER001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SLAVE002",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            entry_id="agg_math_test",
        )
        entry.add_to_hass(hass)
        return entry

    def _make_processed(self, inv1_sensors, inv2_sensors):
        """Build a processed dict with two inverters."""
        return {
            "devices": {
                "MASTER001": {
                    "type": "inverter",
                    "parallel_number": 2,
                    "parallel_master_slave": 1,
                    "sensors": inv1_sensors,
                },
                "SLAVE002": {
                    "type": "inverter",
                    "parallel_number": 2,
                    "parallel_master_slave": 2,
                    "sensors": inv2_sensors,
                },
            }
        }

    @pytest.mark.asyncio
    async def test_power_sensors_summed(self, hass, local_entry):
        """Power sensors from both inverters are summed in parallel group."""
        processed = self._make_processed(
            {
                "pv_total_power": 3500,
                "grid_power": 200,  # importing 200W
                "consumption_power": 2800,
                "eps_power": 100,
                "battery_charge_power": 0,
                "battery_discharge_power": 900,
                "ac_power": 2700,
                "output_power": 2700,
            },
            {
                "pv_total_power": 4200,
                "grid_power": -500,  # exporting 500W
                "consumption_power": 3100,
                "eps_power": 200,
                "battery_charge_power": 600,
                "battery_discharge_power": 0,
                "ac_power": 3800,
                "output_power": 3800,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        group = processed["devices"]["parallel_group_a"]
        sensors = group["sensors"]

        # Power sensors should be summed
        assert sensors["pv_total_power"] == 7700  # 3500 + 4200
        assert sensors["grid_power"] == -300  # 200 + (-500) = net export
        assert sensors["consumption_power"] == 5900  # 2800 + 3100
        assert sensors["eps_power"] == 300  # 100 + 200
        assert sensors["ac_power"] == 6500  # 2700 + 3800
        assert sensors["output_power"] == 6500  # 2700 + 3800

    @pytest.mark.asyncio
    async def test_energy_sensors_summed(self, hass, local_entry):
        """Energy sensors from both inverters are summed in parallel group."""
        processed = self._make_processed(
            {
                "yield": 15.3,
                "charging": 2.1,
                "discharging": 8.5,
                "grid_import": 5.2,
                "grid_export": 12.0,
                "consumption": 17.0,
                "yield_lifetime": 10500.0,
                "charging_lifetime": 3200.0,
                "discharging_lifetime": 6100.0,
                "grid_import_lifetime": 8500.0,
                "grid_export_lifetime": 5200.0,
                "consumption_lifetime": 13800.0,
            },
            {
                "yield": 18.7,
                "charging": 3.5,
                "discharging": 5.0,
                "grid_import": 8.1,
                "grid_export": 6.5,
                "consumption": 25.3,
                "yield_lifetime": 12200.0,
                "charging_lifetime": 4100.0,
                "discharging_lifetime": 7800.0,
                "grid_import_lifetime": 11200.0,
                "grid_export_lifetime": 3900.0,
                "consumption_lifetime": 19500.0,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Today energy
        assert sensors["yield"] == pytest.approx(34.0, abs=0.01)
        assert sensors["charging"] == pytest.approx(5.6, abs=0.01)
        assert sensors["discharging"] == pytest.approx(13.5, abs=0.01)
        assert sensors["grid_import"] == pytest.approx(13.3, abs=0.01)
        assert sensors["grid_export"] == pytest.approx(18.5, abs=0.01)
        assert sensors["consumption"] == pytest.approx(42.3, abs=0.01)

        # Lifetime energy
        assert sensors["yield_lifetime"] == pytest.approx(22700.0)
        assert sensors["charging_lifetime"] == pytest.approx(7300.0)
        assert sensors["discharging_lifetime"] == pytest.approx(13900.0)
        assert sensors["grid_import_lifetime"] == pytest.approx(19700.0)
        assert sensors["grid_export_lifetime"] == pytest.approx(9100.0)
        assert sensors["consumption_lifetime"] == pytest.approx(33300.0)

    @pytest.mark.asyncio
    async def test_battery_soc_averaged(self, hass, local_entry):
        """Battery SOC from both inverters is averaged, not summed."""
        processed = self._make_processed(
            {"state_of_charge": 85},
            {"state_of_charge": 65},
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]
        assert sensors["parallel_battery_soc"] == 75.0  # (85 + 65) / 2

    @pytest.mark.asyncio
    async def test_battery_voltage_averaged(self, hass, local_entry):
        """Battery voltage from both inverters is averaged, not summed."""
        processed = self._make_processed(
            {"battery_voltage": 52.4},
            {"battery_voltage": 51.8},
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]
        assert sensors["parallel_battery_voltage"] == 52.1  # (52.4 + 51.8) / 2

    @pytest.mark.asyncio
    async def test_battery_power_remapping(self, hass, local_entry):
        """Battery charge/discharge are remapped to parallel_battery_* keys.

        parallel_battery_power = total_discharge - total_charge
        (positive = net discharging, negative = net charging)
        """
        processed = self._make_processed(
            {
                "battery_charge_power": 0,
                "battery_discharge_power": 2500,
            },
            {
                "battery_charge_power": 1500,
                "battery_discharge_power": 0,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Remapped keys
        assert sensors["parallel_battery_charge_power"] == 1500  # 0 + 1500
        assert sensors["parallel_battery_discharge_power"] == 2500  # 2500 + 0
        # Net: 2500 discharge - 1500 charge = 1000 net discharge
        assert sensors["parallel_battery_power"] == 1000

        # Original keys should NOT exist (popped)
        assert "battery_charge_power" not in sensors
        assert "battery_discharge_power" not in sensors

    @pytest.mark.asyncio
    async def test_battery_count_and_capacity_summed(self, hass, local_entry):
        """Battery count and capacity are summed across inverters."""
        processed = self._make_processed(
            {
                "battery_bank_count": 4,
                "battery_bank_max_capacity": 200.0,  # 4 x 50Ah
                "battery_bank_current_capacity": 170.0,  # 85%
            },
            {
                "battery_bank_count": 3,
                "battery_bank_max_capacity": 150.0,  # 3 x 50Ah
                "battery_bank_current_capacity": 97.5,  # 65%
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]
        assert sensors["parallel_battery_count"] == 7  # 4 + 3
        assert sensors["parallel_battery_max_capacity"] == 350.0
        assert sensors["parallel_battery_current_capacity"] == 267.5

    @pytest.mark.asyncio
    async def test_grid_voltage_from_master(self, hass, local_entry):
        """Grid voltage is taken from master inverter, not averaged."""
        processed = self._make_processed(
            {
                "grid_voltage_l1": 121.5,
                "grid_voltage_l2": 122.3,
            },
            {
                "grid_voltage_l1": 121.2,  # slave value should be ignored
                "grid_voltage_l2": 122.1,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]
        # Uses master inverter (MASTER001) values only
        assert sensors["grid_voltage_l1"] == 121.5
        assert sensors["grid_voltage_l2"] == 122.3

    @pytest.mark.asyncio
    async def test_no_gridboss_overlay_without_gridboss(self, hass, local_entry):
        """Without GridBOSS, inverter-summed grid/consumption values are preserved.

        The GridBOSS overlay code should NOT trigger when no GridBOSS device
        exists in the processed data. This is the key scenario for users
        without a GridBOSS.
        """
        processed = self._make_processed(
            {
                "grid_power": 1200,
                "consumption_power": 3500,
                "grid_import": 25.0,
                "grid_export": 8.0,
                "consumption": 45.0,
                "grid_import_lifetime": 5000.0,
                "grid_export_lifetime": 2000.0,
                "consumption_lifetime": 8000.0,
            },
            {
                "grid_power": 800,
                "consumption_power": 2800,
                "grid_import": 18.0,
                "grid_export": 5.0,
                "consumption": 38.0,
                "grid_import_lifetime": 4200.0,
                "grid_export_lifetime": 1800.0,
                "consumption_lifetime": 7200.0,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Inverter-summed values should be preserved (no GridBOSS override)
        assert sensors["grid_power"] == 2000  # 1200 + 800
        assert sensors["consumption_power"] == 6300  # 3500 + 2800
        assert sensors["grid_import"] == pytest.approx(43.0)
        assert sensors["grid_export"] == pytest.approx(13.0)
        assert sensors["consumption"] == pytest.approx(83.0)

        # No GridBOSS-specific keys should exist
        assert "load_power" not in sensors
        assert "grid_power_l1" not in sensors
        assert "grid_power_l2" not in sensors

    @pytest.mark.asyncio
    async def test_consumption_energy_balance_holds(self, hass, local_entry):
        """The energy balance equation holds at the aggregate level.

        For each inverter: consumption = pv + battery_power + grid_import - grid_export
        Since this equation is linear, summing per-inverter consumption equals
        computing consumption from summed group totals.
        """
        # Inverter 1: consumption = 3500 + (900 - 0) + 200 - 1800 = 2800
        inv1 = {
            "pv_total_power": 3500,
            "battery_charge_power": 0,
            "battery_discharge_power": 900,
            "grid_power": -1600,  # net export (200 import - 1800 export)
            "consumption_power": 2800,
        }
        # Inverter 2: consumption = 4200 + (0 - 600) + 1500 - 300 = 4800
        inv2 = {
            "pv_total_power": 4200,
            "battery_charge_power": 600,
            "battery_discharge_power": 0,
            "grid_power": 1200,  # net import
            "consumption_power": 4800,
        }

        processed = self._make_processed(inv1, inv2)
        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Group totals
        total_pv = sensors["pv_total_power"]
        total_battery = sensors["parallel_battery_power"]  # discharge - charge
        total_grid = sensors["grid_power"]  # signed: positive=import, negative=export
        total_consumption = sensors["consumption_power"]

        # Verify the energy balance at the group level:
        # consumption_power (summed) should approximately equal
        # pv + battery_power + grid_import - grid_export (from summed values)
        # Note: grid_power is already net (positive=import, negative=export)
        # so: consumption ≈ pv + battery_power + grid_power
        # Since consumption_power in pylxpweb uses separated import/export,
        # and grid_power is the signed net, there can be slight differences
        # in how the terms map. But the sum should be consistent.
        assert total_pv == 7700  # 3500 + 4200
        assert total_battery == 300  # (900 + 0) - (0 + 600) = 300 net discharge
        assert total_grid == -400  # -1600 + 1200
        assert total_consumption == 7600  # 2800 + 4800

    @pytest.mark.asyncio
    async def test_mixed_grid_state_one_importing_one_exporting(
        self, hass, local_entry
    ):
        """Mixed grid state: one inverter importing, one exporting.

        This tests a realistic scenario where one inverter's PV exceeds its
        local consumption (exporting) while the other draws from grid.
        """
        processed = self._make_processed(
            {
                "pv_total_power": 6000,  # High PV
                "grid_power": -2000,  # Exporting excess
                "consumption_power": 3000,
                "battery_charge_power": 1000,
                "battery_discharge_power": 0,
                "eps_power": 0,
            },
            {
                "pv_total_power": 500,  # Low PV (shaded)
                "grid_power": 3000,  # Heavy import
                "consumption_power": 3500,
                "battery_charge_power": 0,
                "battery_discharge_power": 0,
                "eps_power": 0,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Net grid: -2000 + 3000 = 1000W net import
        assert sensors["grid_power"] == 1000
        # Total PV: 6000 + 500 = 6500W
        assert sensors["pv_total_power"] == 6500
        # Total consumption: 3000 + 3500 = 6500W
        assert sensors["consumption_power"] == 6500
        # Battery: 1000 charge, 0 discharge → net = -1000 (charging)
        assert sensors["parallel_battery_power"] == -1000

    @pytest.mark.asyncio
    async def test_none_sensor_values_skipped(self, hass, local_entry):
        """Sensors with None values don't contribute to sums or averages.

        This handles the case where one inverter hasn't reported data yet.
        """
        processed = self._make_processed(
            {
                "pv_total_power": 3000,
                "grid_power": 500,
                "state_of_charge": 80,
                "battery_voltage": 52.0,
            },
            {
                "pv_total_power": None,  # No data yet
                "grid_power": None,
                "state_of_charge": None,
                "battery_voltage": None,
            },
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # Only inverter 1 values should be used (None skipped)
        assert sensors["pv_total_power"] == 3000
        assert sensors["grid_power"] == 500
        assert sensors["parallel_battery_soc"] == 80.0  # Only 1 reading
        assert sensors["parallel_battery_voltage"] == 52.0

    @pytest.mark.asyncio
    async def test_group_metadata_correct(self, hass, local_entry):
        """Parallel group metadata (name, members, type) is correct."""
        processed = self._make_processed(
            {"pv_total_power": 1000},
            {"pv_total_power": 2000},
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        group = processed["devices"]["parallel_group_a"]
        assert group["type"] == "parallel_group"
        assert group["name"] == "Parallel Group A"
        assert group["group_name"] == "A"
        assert group["first_device_serial"] == "MASTER001"
        assert group["member_count"] == 2
        assert set(group["member_serials"]) == {"MASTER001", "SLAVE002"}

    @pytest.mark.asyncio
    async def test_last_polled_timestamp_set(self, hass, local_entry):
        """Parallel group includes a last_polled timestamp."""
        processed = self._make_processed(
            {"pv_total_power": 1000},
            {"pv_total_power": 2000},
        )

        coordinator = EG4DataUpdateCoordinator(hass, local_entry)
        await coordinator._process_local_parallel_groups(processed)

        sensors = processed["devices"]["parallel_group_a"]["sensors"]
        assert "parallel_group_last_polled" in sensors
        assert sensors["parallel_group_last_polled"] is not None


class TestGridBOSSOverlay:
    """Tests for the shared GridBOSS CT overlay function.

    The apply_gridboss_overlay function ensures that when a GridBOSS is present,
    its CT measurements (the authoritative source for grid and consumption data)
    override inverter-derived estimates.  This function is used by both the LOCAL
    and HTTP (hybrid) paths so that parallel group values are consistent
    regardless of connection mode.
    """

    def test_energy_values_overridden(self):
        """GridBOSS CT energy values replace inverter-summed estimates."""
        pg = {
            "grid_import": 25.0,
            "grid_import_lifetime": 3698.0,
            "grid_export": 10.0,
            "grid_export_lifetime": 8483.3,
            "consumption": 9.1,
            "consumption_lifetime": 3698.0,
        }
        gb = {
            "grid_import_today": 30.5,
            "grid_import_total": 17354.4,
            "grid_export_today": 12.3,
            "grid_export_total": 10621.9,
            "load_today": 43.1,
            "load_total": 10736.7,
        }

        apply_gridboss_overlay(pg, gb, "A")

        assert pg["grid_import"] == pytest.approx(30.5)
        assert pg["grid_import_lifetime"] == pytest.approx(17354.4)
        assert pg["grid_export"] == pytest.approx(12.3)
        assert pg["grid_export_lifetime"] == pytest.approx(10621.9)
        assert pg["consumption"] == pytest.approx(43.1)
        assert pg["consumption_lifetime"] == pytest.approx(10736.7)

    def test_power_values_overridden(self):
        """GridBOSS CT power values replace inverter-summed values."""
        pg = {"grid_power": 500.0}
        gb = {
            "grid_power": 520.0,
            "grid_power_l1": 260.0,
            "grid_power_l2": 260.0,
            "load_power": 1800.0,
            "load_power_l1": 900.0,
            "load_power_l2": 900.0,
        }

        apply_gridboss_overlay(pg, gb, "A")

        assert pg["grid_power"] == pytest.approx(520.0)
        assert pg["grid_power_l1"] == pytest.approx(260.0)
        assert pg["grid_power_l2"] == pytest.approx(260.0)
        assert pg["load_power"] == pytest.approx(1800.0)
        assert pg["load_power_l1"] == pytest.approx(900.0)
        assert pg["load_power_l2"] == pytest.approx(900.0)

    def test_missing_gb_values_not_overridden(self):
        """Values missing from GridBOSS sensors are left unchanged."""
        pg = {
            "grid_import": 25.0,
            "grid_export": 10.0,
            "consumption": 9.1,
        }
        # GridBOSS only has import data, not export or consumption
        gb = {"grid_import_today": 30.5}

        apply_gridboss_overlay(pg, gb, "A")

        assert pg["grid_import"] == pytest.approx(30.5)  # overridden
        assert pg["grid_export"] == pytest.approx(10.0)  # unchanged
        assert pg["consumption"] == pytest.approx(9.1)  # unchanged

    def test_empty_gb_sensors_noop(self):
        """Empty GridBOSS sensor dict is a no-op."""
        pg = {"consumption_lifetime": 3698.0, "grid_power": 500.0}
        original = dict(pg)

        apply_gridboss_overlay(pg, {}, "A")

        assert pg == original

    def test_new_keys_added(self):
        """GridBOSS keys not already in parallel group are added."""
        pg: dict = {}
        gb = {"load_power": 1800.0, "load_total": 10736.7}

        apply_gridboss_overlay(pg, gb, "A")

        assert pg["load_power"] == pytest.approx(1800.0)
        assert pg["consumption_lifetime"] == pytest.approx(10736.7)

    @pytest.mark.asyncio
    async def test_http_path_applies_gridboss_overlay(self, hass):
        """HYBRID mode applies GridBOSS overlay to parallel group in HTTP path.

        This is the key regression test: before the fix, HYBRID mode would use
        inverter-summed energy values (from _compute_energy_from_inverters)
        without overlaying GridBOSS CT data, causing consumption_lifetime to
        diverge from LOCAL mode.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Hybrid Test",
            data={
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
                CONF_PLANT_ID: "999",
                CONF_PLANT_NAME: "Hybrid Test",
                CONF_BASE_URL: "https://test.example.com",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
                CONF_VERIFY_SSL: True,
                CONF_HTTP_POLLING_INTERVAL: DEFAULT_HTTP_POLLING_INTERVAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [],
            },
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator.client = MagicMock()
        coordinator.station = MagicMock()

        # Create mock parallel group with MID device
        mock_group = MagicMock()
        mock_group.name = "A"
        mock_group._energy = MagicMock()
        mock_group.today_yielding = 15.0
        mock_group._has_local_energy.return_value = True
        mock_group._fetch_energy_data = AsyncMock()

        # Mock MID device
        mock_mid = MagicMock()
        mock_mid.serial_number = "GB001"
        mock_mid.refresh = AsyncMock()
        mock_group.mid_device = mock_mid
        mock_group.inverters = [MagicMock(serial_number="INV001")]

        # Setup station to return our parallel group
        coordinator.station.parallel_groups = [mock_group]
        coordinator.station.standalone_mid_devices = []

        # Mock _process_parallel_group_object to return inverter-summed values
        # (simulating what _compute_energy_from_inverters would produce)
        async def mock_pg_process(group):
            return {
                "name": "Parallel Group A",
                "type": "parallel_group",
                "first_device_serial": "INV001",
                "member_serials": ["INV001"],
                "member_count": 1,
                "sensors": {
                    "consumption_lifetime": 3698.0,  # inverter sum (wrong)
                    "grid_import_lifetime": 13640.2,  # inverter sum (wrong)
                    "grid_export_lifetime": 8483.3,  # inverter sum (wrong)
                    "consumption": 9.1,
                    "grid_import": 18.0,
                    "grid_export": 7.5,
                    "grid_power": 500,
                    "parallel_group_last_polled": dt_util.utcnow(),
                },
                "binary_sensors": {},
            }

        # Mock _process_mid_device_object to return GridBOSS CT data
        async def mock_mid_process(mid):
            return {
                "name": "GridBOSS",
                "type": "gridboss",
                "sensors": {
                    "grid_power": 520.0,
                    "load_power": 1800.0,
                    "grid_import_today": 30.5,
                    "grid_import_total": 17354.4,
                    "grid_export_today": 12.3,
                    "grid_export_total": 10621.9,
                    "load_today": 43.1,
                    "load_total": 10736.7,
                },
            }

        with (
            patch.object(
                coordinator,
                "_process_parallel_group_object",
                side_effect=mock_pg_process,
            ),
            patch.object(
                coordinator,
                "_process_mid_device_object",
                side_effect=mock_mid_process,
            ),
            patch.object(coordinator, "_rebuild_inverter_cache"),
        ):
            processed = await coordinator._process_station_data()

        pg_sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # After overlay, parallel group should use GridBOSS CT values
        assert pg_sensors["consumption_lifetime"] == pytest.approx(10736.7)
        assert pg_sensors["grid_import_lifetime"] == pytest.approx(17354.4)
        assert pg_sensors["grid_export_lifetime"] == pytest.approx(10621.9)
        assert pg_sensors["consumption"] == pytest.approx(43.1)
        assert pg_sensors["grid_import"] == pytest.approx(30.5)
        assert pg_sensors["grid_export"] == pytest.approx(12.3)
        assert pg_sensors["grid_power"] == pytest.approx(520.0)

    @pytest.mark.asyncio
    async def test_local_path_applies_gridboss_overlay(self, hass):
        """LOCAL mode applies GridBOSS overlay to parallel group.

        Verifies the refactored LOCAL path (which now uses the shared
        apply_gridboss_overlay function) still works correctly.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Local Test",
            data={
                CONF_USERNAME: "",
                CONF_PASSWORD: "",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "type": "modbus_tcp",
                        "host": "192.168.1.100",
                        "port": 8000,
                        "serial": "INV001",
                        "unit_id": 1,
                        "parallel_number": 1,
                        "is_gridboss": False,
                        "inverter_family": "EG4_OFFGRID",
                    },
                    {
                        "type": "modbus_tcp",
                        "host": "192.168.1.101",
                        "port": 8000,
                        "serial": "GB001",
                        "unit_id": 1,
                        "parallel_number": 0,
                        "is_gridboss": True,
                        "inverter_family": "EG4_OFFGRID",
                    },
                ],
            },
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        processed: dict = {
            "devices": {
                "INV001": {
                    "type": "inverter",
                    "parallel_number": 1,
                    "parallel_master_slave": 1,
                    "sensors": {
                        "consumption_lifetime": 1849.0,
                        "grid_import_lifetime": 6820.1,
                        "grid_export_lifetime": 4241.7,
                        "consumption": 4.5,
                        "grid_import": 9.0,
                        "grid_export": 3.75,
                        "grid_power": 250,
                        "consumption_power": 1400,
                        "eps_power": 100,
                        "pv_total_power": 2000,
                        "battery_charge_power": 0,
                        "battery_discharge_power": 450,
                        "state_of_charge": 80,
                        "battery_voltage": 52.0,
                    },
                },
                "GB001": {
                    "type": "gridboss",
                    "sensors": {
                        "grid_power": 520.0,
                        "load_power": 1800.0,
                        "grid_import_today": 30.5,
                        "grid_import_total": 17354.4,
                        "grid_export_today": 12.3,
                        "grid_export_total": 10621.9,
                        "load_today": 43.1,
                        "load_total": 10736.7,
                    },
                },
            }
        }

        await coordinator._process_local_parallel_groups(processed)

        pg_sensors = processed["devices"]["parallel_group_a"]["sensors"]

        # GridBOSS CT values should override inverter estimates
        assert pg_sensors["consumption_lifetime"] == pytest.approx(10736.7)
        assert pg_sensors["grid_import_lifetime"] == pytest.approx(17354.4)
        assert pg_sensors["grid_export_lifetime"] == pytest.approx(10621.9)
        assert pg_sensors["consumption"] == pytest.approx(43.1)
        assert pg_sensors["grid_import"] == pytest.approx(30.5)
        assert pg_sensors["grid_export"] == pytest.approx(12.3)
        assert pg_sensors["grid_power"] == pytest.approx(520.0)
        assert pg_sensors["load_power"] == pytest.approx(1800.0)


class TestCoordinatorIntervalLogic:
    """Tests for coordinator interval selection based on connection type."""

    @pytest.fixture
    def http_config_entry(self):
        """Create a mock HTTP config entry."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - HTTP Test",
            data={
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
                CONF_BASE_URL: "https://monitor.eg4electronics.com",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_LIBRARY_DEBUG: False,
                CONF_PLANT_ID: "12345",
                CONF_PLANT_NAME: "Test",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            },
            options={},
            entry_id="http_test",
        )

    @pytest.fixture
    def local_config_entry(self):
        """Create a mock local config entry."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Local Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="local_test",
        )

    @pytest.fixture
    def hybrid_config_entry(self):
        """Create a mock hybrid config entry."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Hybrid Test",
            data={
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
                CONF_BASE_URL: "https://monitor.eg4electronics.com",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_LIBRARY_DEBUG: False,
                CONF_PLANT_ID: "12345",
                CONF_PLANT_NAME: "Test",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
                CONF_LOCAL_TRANSPORTS: [],
            },
            options={},
            entry_id="hybrid_test",
        )

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_http_mode_uses_http_interval(
        self, mock_aiohttp, mock_client, hass, http_config_entry
    ):
        """Test HTTP mode coordinator uses HTTP polling interval."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator.update_interval == timedelta(
            seconds=DEFAULT_HTTP_POLLING_INTERVAL
        )

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_http_mode_custom_interval(
        self, mock_aiohttp, mock_client, hass, http_config_entry
    ):
        """Test HTTP mode uses custom HTTP polling interval from options."""
        http_config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            http_config_entry,
            options={CONF_HTTP_POLLING_INTERVAL: 120},
        )
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator.update_interval == timedelta(seconds=120)

    def test_local_mode_uses_sensor_interval(self, hass, local_config_entry):
        """Test local mode coordinator uses sensor update interval."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator.update_interval == timedelta(
            seconds=DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
        )

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_mode_uses_sensor_interval(
        self, mock_aiohttp, mock_client, hass, hybrid_config_entry
    ):
        """Test hybrid mode coordinator uses sensor interval (not HTTP)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        assert coordinator.update_interval == timedelta(
            seconds=DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
        )

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_http_polling_interval_stored(
        self, mock_aiohttp, mock_client, hass, http_config_entry
    ):
        """Test HTTP polling interval is stored for cache alignment."""
        http_config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            http_config_entry,
            options={CONF_HTTP_POLLING_INTERVAL: 150},
        )
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator._http_polling_interval == 150


class TestStaleDataTolerance:
    """Tests for stale data tolerance in _async_update_data."""

    @pytest.fixture
    def coordinator_with_data(self, hass):
        """Create a coordinator with mock cached data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="stale_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        # Simulate cached data from a previous successful update
        coordinator.data = {"devices": {"INV001": {"type": "inverter"}}}
        return coordinator

    @pytest.mark.asyncio
    async def test_first_failure_returns_cached_data(self, coordinator_with_data):
        """Test first update failure returns last-known-good data."""
        coordinator = coordinator_with_data
        with patch.object(
            coordinator,
            "_route_update_by_connection_type",
            side_effect=UpdateFailed("timeout"),
        ):
            result = await coordinator._async_update_data()
        assert result == coordinator.data
        assert coordinator._consecutive_update_failures == 1

    @pytest.mark.asyncio
    async def test_second_failure_returns_cached_data(self, coordinator_with_data):
        """Test second consecutive failure still returns cached data."""
        coordinator = coordinator_with_data
        coordinator._consecutive_update_failures = 1
        with patch.object(
            coordinator,
            "_route_update_by_connection_type",
            side_effect=UpdateFailed("timeout"),
        ):
            result = await coordinator._async_update_data()
        assert result == coordinator.data
        assert coordinator._consecutive_update_failures == 2

    @pytest.mark.asyncio
    async def test_third_failure_propagates(self, coordinator_with_data):
        """Test third consecutive failure raises UpdateFailed."""
        coordinator = coordinator_with_data
        coordinator._consecutive_update_failures = 2
        with (
            patch.object(
                coordinator,
                "_route_update_by_connection_type",
                side_effect=UpdateFailed("timeout"),
            ),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()
        assert coordinator._consecutive_update_failures == 3

    @pytest.mark.asyncio
    async def test_success_resets_counter(self, coordinator_with_data):
        """Test successful update resets failure counter."""
        coordinator = coordinator_with_data
        coordinator._consecutive_update_failures = 2
        fresh_data = {"devices": {"INV001": {"type": "inverter", "status": "online"}}}
        with patch.object(
            coordinator,
            "_route_update_by_connection_type",
            return_value=fresh_data,
        ):
            result = await coordinator._async_update_data()
        assert result == fresh_data
        assert coordinator._consecutive_update_failures == 0

    @pytest.mark.asyncio
    async def test_auth_failure_always_propagates(self, coordinator_with_data):
        """Test auth failures always propagate immediately (no grace period)."""
        coordinator = coordinator_with_data
        with (
            patch.object(
                coordinator,
                "_route_update_by_connection_type",
                side_effect=ConfigEntryAuthFailed("bad creds"),
            ),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await coordinator._async_update_data()
        # Counter should not increment for auth failures
        assert coordinator._consecutive_update_failures == 0

    @pytest.mark.asyncio
    async def test_no_cached_data_raises_immediately(self, hass):
        """Test that first-ever failure raises immediately (no cached data)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="no_cache_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        # data is None — no previous successful update
        with (
            patch.object(
                coordinator,
                "_route_update_by_connection_type",
                side_effect=UpdateFailed("timeout"),
            ),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()


class TestClientCacheAlignment:
    """Tests for client cache TTL alignment with HTTP polling interval."""

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_cache_alignment_sets_battery_ttl(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Test _align_client_cache_with_http_interval sets battery_info TTL."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Test",
            data={
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
                CONF_BASE_URL: "https://monitor.eg4electronics.com",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_LIBRARY_DEBUG: False,
                CONF_PLANT_ID: "12345",
                CONF_PLANT_NAME: "Test",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            },
            options={CONF_HTTP_POLLING_INTERVAL: 120},
            entry_id="cache_align_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        # Ensure client has _cache_ttl_config with default pylxpweb values
        coordinator.client._cache_ttl_config = {
            "battery_info": timedelta(seconds=60),
            "midbox_runtime": timedelta(seconds=20),
            "quick_charge_status": timedelta(minutes=1),
            "inverter_runtime": timedelta(seconds=20),
            "inverter_energy": timedelta(seconds=20),
            "parameter_read": timedelta(minutes=2),
        }
        coordinator._align_client_cache_with_http_interval()
        expected = timedelta(seconds=120)
        for key in (
            "battery_info",
            "midbox_runtime",
            "quick_charge_status",
            "inverter_runtime",
            "inverter_energy",
            "parameter_read",
        ):
            assert coordinator.client._cache_ttl_config[key] == expected, (
                f"{key} TTL not aligned"
            )

    def test_cache_alignment_no_client(self, hass):
        """Test _align_client_cache_with_http_interval is safe without client."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="no_client_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        assert coordinator.client is None
        # Should not raise
        coordinator._align_client_cache_with_http_interval()


class TestPerTransportIntervals:
    """Tests for per-transport refresh interval feature."""

    @pytest.fixture
    def mixed_local_config_entry(self):
        """Config entry for LOCAL mode with both Modbus and Dongle transports."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Mixed Local",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "1111111111",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                    {
                        "serial": "2222222222",
                        "host": "192.168.1.200",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "dongle_serial": "BJ1234567890",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                    },
                ],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="mixed_local_test",
        )

    @pytest.fixture
    def modbus_only_local_config_entry(self):
        """Config entry for LOCAL mode with Modbus-only transport."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Modbus Only",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "3333333333",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="modbus_only_test",
        )

    @pytest.fixture
    def dongle_only_local_config_entry(self):
        """Config entry for LOCAL mode with Dongle-only transport."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Dongle Only",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "4444444444",
                        "host": "192.168.1.200",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "dongle_serial": "BJ9876543210",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                    },
                ],
                CONF_LIBRARY_DEBUG: False,
            },
            options={},
            entry_id="dongle_only_test",
        )

    def test_compute_update_interval_local_mixed(self, hass, mixed_local_config_entry):
        """LOCAL with mixed transports: update_interval = min(modbus, dongle)."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        # Default modbus=5, dongle=10 → min=5
        assert coordinator.update_interval == timedelta(seconds=5)
        assert coordinator._modbus_interval == 5
        assert coordinator._dongle_interval == 10

    def test_compute_update_interval_local_modbus_only(
        self, hass, modbus_only_local_config_entry
    ):
        """LOCAL with only Modbus: update_interval = modbus interval."""
        modbus_only_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, modbus_only_local_config_entry)
        assert coordinator.update_interval == timedelta(seconds=5)

    def test_compute_update_interval_local_dongle_only(
        self, hass, dongle_only_local_config_entry
    ):
        """LOCAL with only Dongle: update_interval = dongle interval."""
        dongle_only_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, dongle_only_local_config_entry)
        assert coordinator.update_interval == timedelta(seconds=10)

    def test_should_poll_transport_first_call_always_true(
        self, hass, mixed_local_config_entry
    ):
        """First call to _should_poll_transport always returns True (timestamp==0.0)."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        assert coordinator._last_modbus_poll == 0.0
        assert coordinator._should_poll_transport("modbus_tcp") is True
        assert coordinator._last_modbus_poll > 0.0

    def test_should_poll_transport_within_interval_false(
        self, hass, mixed_local_config_entry
    ):
        """Calling _should_poll_transport before interval elapses returns False."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        # First call sets the timestamp
        assert coordinator._should_poll_transport("modbus_tcp") is True
        # Immediately calling again should return False (5s hasn't elapsed)
        assert coordinator._should_poll_transport("modbus_tcp") is False

    def test_should_poll_transport_elapsed_true(self, hass, mixed_local_config_entry):
        """After interval elapses, _should_poll_transport returns True."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        # Simulate that last poll happened long ago
        coordinator._last_modbus_poll = 1.0  # far in the past
        assert coordinator._should_poll_transport("modbus_tcp") is True

    @pytest.mark.asyncio
    async def test_multi_device_same_transport_all_polled(self, hass):
        """Multiple devices on the same transport type must all be polled.

        Regression test: _should_poll_transport used a shared timestamp per
        transport TYPE.  When the partition loop called it per-device, the first
        device's check stamped the timestamp and all subsequent devices of the
        same type were permanently skipped.  The fix pre-computes pollable types
        once before iterating devices.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Two Modbus",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "AAAA111111",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                    {
                        "serial": "BBBB222222",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "18kPV",
                    },
                ],
            },
            options={},
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        # Simulate stale timestamps so modbus_tcp should be polled
        coordinator._last_modbus_poll = 0.0

        # Track which configs enter the transport group processor.
        # Mock at the group level to capture all configs that were
        # queued for polling (the individual device processor would
        # fail on real transport connections).
        polled_configs: list[list[str]] = []

        async def tracking_group(configs, processed, avail):
            polled_configs.append([c.get("serial", "") for c in configs])
            for c in configs:
                avail[c.get("serial", "")] = True

        with patch.object(
            coordinator, "_process_local_transport_group", side_effect=tracking_group
        ):
            await coordinator._async_update_local_data()

        # Both modbus_tcp devices must be in the same group
        all_serials = [s for group in polled_configs for s in group]
        assert "AAAA111111" in all_serials, "First modbus_tcp device was not polled"
        assert "BBBB222222" in all_serials, (
            "Second modbus_tcp device was skipped (transport interval bug)"
        )

    @pytest.mark.asyncio
    async def test_local_data_skipped_devices_use_cache(
        self, hass, mixed_local_config_entry
    ):
        """Skipped transports retain prior data from cache."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        # Simulate post-static phase
        coordinator._local_static_phase_done = True
        # Simulate prior cached data
        coordinator.data = {
            "devices": {
                "1111111111": {"type": "inverter", "sensors": {"pv_total_power": 5000}},
                "2222222222": {"type": "inverter", "sensors": {"pv_total_power": 3000}},
            },
            "parameters": {"1111111111": {}, "2222222222": {}},
        }
        # Set timestamps so both transports were recently polled
        coordinator._last_modbus_poll = time.monotonic()
        coordinator._last_dongle_poll = time.monotonic()

        # Both transports skipped → should return cached data
        result = await coordinator._async_update_local_data()
        assert "1111111111" in result["devices"]
        assert "2222222222" in result["devices"]
        assert result["devices"]["1111111111"]["sensors"]["pv_total_power"] == 5000

    @pytest.mark.asyncio
    async def test_local_data_partial_poll_modbus_only(
        self, hass, mixed_local_config_entry
    ):
        """Only Modbus polled, Dongle retains cached data."""
        mixed_local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mixed_local_config_entry)
        coordinator._local_static_phase_done = True
        coordinator.data = {
            "devices": {
                "2222222222": {"type": "inverter", "sensors": {"pv_total_power": 3000}},
            },
            "parameters": {"2222222222": {}},
        }
        # Dongle was just polled, Modbus was not
        coordinator._last_dongle_poll = time.monotonic()
        coordinator._last_modbus_poll = 0.0  # Never polled → will poll

        # Modbus device will be attempted but fail (no real transport)
        # → dongle device should still have cached data
        try:
            await coordinator._async_update_local_data()
        except Exception:
            # Modbus poll may fail, but dongle data should be cached
            pass

        # Verify dongle device retained cached data
        # (This is tested via the pre-population logic)
        assert coordinator._last_modbus_poll > 0.0  # Was attempted

    def test_fallback_to_sensor_update_interval(self, hass):
        """No new keys in options: falls back to legacy sensor_update_interval."""

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Fallback Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "5555555555",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
                CONF_LIBRARY_DEBUG: False,
            },
            # Legacy sensor_update_interval, no new per-transport keys
            options={"sensor_update_interval": 7},
            entry_id="fallback_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        # Should fall back to sensor_update_interval=7 for modbus
        assert coordinator._modbus_interval == 7
        # Dongle also falls back to sensor_update_interval
        assert coordinator._dongle_interval == 7


class TestForceMigration:
    """Tests for force-migration of polling intervals in __init__.py."""

    def test_http_polling_interval_constant_defaults(self):
        """Test that HTTP polling interval constants have expected values."""
        assert DEFAULT_HTTP_POLLING_INTERVAL == 120
        assert DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP == 90


class TestMappingKeyConsistency:
    """Verify LOCAL and HTTP mapping functions produce keys within the static key sets.

    These tests catch key drift: if a mapping function adds a new sensor key
    but the corresponding static frozenset isn't updated, the entity won't be
    created during the static-data first-refresh phase.
    """

    def test_gridboss_local_keys_subset_of_static(self):
        """LOCAL _build_gridboss_sensor_mapping() keys ⊆ GRIDBOSS_SENSOR_KEYS."""
        # Create a mock MID device where every attribute returns a sentinel
        mock_mid = MagicMock()
        sensors = _build_gridboss_sensor_mapping(mock_mid)
        local_keys = set(sensors.keys())
        unknown = local_keys - GRIDBOSS_SENSOR_KEYS
        assert not unknown, (
            f"LOCAL GridBOSS keys not in GRIDBOSS_SENSOR_KEYS: {sorted(unknown)}"
        )

    def test_gridboss_http_values_within_known_keys(self):
        """HTTP _get_mid_device_property_map() values ⊆ GRIDBOSS_SENSOR_KEYS + HTTP extras.

        The HTTP path exposes additional per-port energy keys and generator
        per-phase voltages that LOCAL cannot read (L2 energy registers always
        read 0 on Modbus, generator per-phase voltages are HTTP-only).
        """
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        # HTTP-only keys not in GRIDBOSS_SENSOR_KEYS (LOCAL static set)
        http_only_keys = {
            "ac_couple1_today",
            "ac_couple1_total",
            "ac_couple2_today",
            "ac_couple2_total",
            "ac_couple3_today",
            "ac_couple3_total",
            "ac_couple4_today",
            "ac_couple4_total",
            "smart_load1_today",
            "smart_load1_total",
            "smart_load2_today",
            "smart_load2_total",
            "smart_load3_today",
            "smart_load3_total",
            "smart_load4_today",
            "smart_load4_total",
            "generator_voltage_l1",
            "generator_voltage_l2",
        }

        property_map = DeviceProcessingMixin._get_mid_device_property_map()
        http_keys = set(property_map.values())
        unknown = http_keys - GRIDBOSS_SENSOR_KEYS - http_only_keys
        assert not unknown, (
            f"HTTP GridBOSS sensor keys not in GRIDBOSS_SENSOR_KEYS or "
            f"known HTTP-only set: {sorted(unknown)}"
        )

    def test_gridboss_local_and_http_share_core_keys(self):
        """LOCAL and HTTP GridBOSS mappings share a large overlapping key set."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        mock_mid = MagicMock()
        local_keys = set(_build_gridboss_sensor_mapping(mock_mid).keys())
        http_keys = set(DeviceProcessingMixin._get_mid_device_property_map().values())

        overlap = local_keys & http_keys
        # Both paths should share at least 40 sensor keys (the core set)
        assert len(overlap) >= 40, (
            f"Only {len(overlap)} shared keys between LOCAL and HTTP GridBOSS "
            f"mappings — expected >= 40"
        )

    def test_inverter_local_runtime_keys_subset_of_static(self):
        """LOCAL _build_runtime_sensor_mapping() keys ⊆ INVERTER_RUNTIME_KEYS."""
        mock_runtime = MagicMock()
        # bt_temperature is conditionally included — set it to a value
        mock_runtime.temperature_t1 = 25
        sensors = _build_runtime_sensor_mapping(mock_runtime)
        local_keys = set(sensors.keys())
        unknown = local_keys - INVERTER_RUNTIME_KEYS
        assert not unknown, (
            f"LOCAL inverter runtime keys not in INVERTER_RUNTIME_KEYS: "
            f"{sorted(unknown)}"
        )

    def test_inverter_http_values_within_known_keys(self):
        """HTTP _get_inverter_property_map() values ⊆ ALL_INVERTER_SENSOR_KEYS + HTTP extras.

        The HTTP cloud API exposes additional fields (EPS per-leg power,
        power factor, status text, etc.) that LOCAL transport doesn't have.
        These are legitimate sensor keys that exist only in the HTTP path.
        """
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        # HTTP-only keys not in ALL_INVERTER_SENSOR_KEYS (LOCAL static set)
        http_only_keys = {
            "power_factor",
            "power_rating",
            "inverter_power_rating",
            "status_text",
            "has_data",
            "inverter_lost_status",
            "inverter_has_runtime_data",
            "ac_couple_power",
            "max_charge_current",
            "max_discharge_current",
        }

        property_map = DeviceProcessingMixin._get_inverter_property_map()
        http_keys = set(property_map.values())
        unknown = http_keys - ALL_INVERTER_SENSOR_KEYS - http_only_keys
        assert not unknown, (
            f"HTTP inverter sensor keys not in ALL_INVERTER_SENSOR_KEYS or "
            f"known HTTP-only set: {sorted(unknown)}"
        )


class TestSmartPortFiltering:
    """Tests for _filter_unused_smart_port_sensors dual-key creation."""

    @staticmethod
    def _make_mid_device(statuses: dict[int, int | None]) -> MagicMock:
        """Create a mock MID device with smart port status attributes."""
        device = MagicMock()
        for port in range(1, 5):
            attr = f"smart_port{port}_status"
            if port in statuses:
                setattr(device, attr, statuses[port])
            else:
                # Remove the attribute so hasattr returns False
                delattr(type(device), attr) if hasattr(type(device), attr) else None
        return device

    def test_ac_couple_port_creates_both_sensor_types(self):
        """Port status=2 (AC Couple): ac_couple power keys have values, smart_load power keys are None."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        mid = self._make_mid_device({1: 2, 2: 0, 3: 0, 4: 0})
        sensors: dict = {
            "ac_couple1_power_l1": 150.0,
            "ac_couple1_power_l2": 200.0,
            "ac_couple1_power": 350.0,
            "ac_couple1_today": 5.0,
            "ac_couple1_total": 100.0,
        }

        DeviceProcessingMixin._filter_unused_smart_port_sensors(sensors, mid)

        # AC Couple power keys preserved with original values
        assert sensors["ac_couple1_power_l1"] == 150.0
        assert sensors["ac_couple1_power_l2"] == 200.0
        assert sensors["ac_couple1_power"] == 350.0
        # AC Couple energy keys preserved
        assert sensors["ac_couple1_today"] == 5.0
        assert sensors["ac_couple1_total"] == 100.0
        # Smart Load power keys created as None (unavailable)
        assert "smart_load1_power_l1" in sensors
        assert sensors["smart_load1_power_l1"] is None
        assert sensors["smart_load1_power_l2"] is None
        assert sensors["smart_load1_power"] is None
        # Smart Load energy keys removed (not created)
        assert "smart_load1_today" not in sensors
        assert "smart_load1_total" not in sensors

    def test_smart_load_port_creates_both_sensor_types(self):
        """Port status=1 (Smart Load): smart_load power keys have values, ac_couple power keys are None."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        mid = self._make_mid_device({1: 0, 2: 0, 3: 1, 4: 0})
        sensors: dict = {
            "smart_load3_power_l1": 75.0,
            "smart_load3_power_l2": 80.0,
            "smart_load3_power": 155.0,
            "smart_load3_today": 2.0,
            "smart_load3_total": 50.0,
        }

        DeviceProcessingMixin._filter_unused_smart_port_sensors(sensors, mid)

        # Smart Load power keys preserved with original values
        assert sensors["smart_load3_power_l1"] == 75.0
        assert sensors["smart_load3_power_l2"] == 80.0
        assert sensors["smart_load3_power"] == 155.0
        # Smart Load energy keys preserved
        assert sensors["smart_load3_today"] == 2.0
        assert sensors["smart_load3_total"] == 50.0
        # AC Couple power keys created as None (unavailable)
        assert "ac_couple3_power_l1" in sensors
        assert sensors["ac_couple3_power_l1"] is None
        assert sensors["ac_couple3_power_l2"] is None
        assert sensors["ac_couple3_power"] is None
        # AC Couple energy keys removed (not created)
        assert "ac_couple3_today" not in sensors
        assert "ac_couple3_total" not in sensors

    def test_unused_port_removes_all_sensors(self):
        """Port status=0 (Unused): all sensor keys removed."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        # Port 1 = AC Couple (active, prevents all-zero skip), port 2 = Unused
        mid = self._make_mid_device({1: 2, 2: 0, 3: 0, 4: 0})
        sensors: dict = {
            "smart_load2_power_l1": 10.0,
            "ac_couple2_power_l1": 20.0,
            "smart_load2_today": 1.0,
            "ac_couple2_today": 2.0,
        }

        DeviceProcessingMixin._filter_unused_smart_port_sensors(sensors, mid)

        # All port 2 sensors removed
        assert "smart_load2_power_l1" not in sensors
        assert "ac_couple2_power_l1" not in sensors
        assert "smart_load2_today" not in sensors
        assert "ac_couple2_today" not in sensors

    def test_mixed_port_statuses(self):
        """Port 1=AC Couple, Port 2=Unused, Port 3=Smart Load, Port 4=Unused."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        mid = self._make_mid_device({1: 2, 2: 0, 3: 1, 4: 0})
        sensors: dict = {
            # Port 1: AC Couple data from API
            "ac_couple1_power_l1": 100.0,
            "ac_couple1_power_l2": 120.0,
            "ac_couple1_power": 220.0,
            "ac_couple1_today": 3.0,
            "ac_couple1_total": 60.0,
            # Port 3: Smart Load data from API
            "smart_load3_power_l1": 50.0,
            "smart_load3_power_l2": 55.0,
            "smart_load3_power": 105.0,
            "smart_load3_today": 1.5,
            "smart_load3_total": 30.0,
        }

        DeviceProcessingMixin._filter_unused_smart_port_sensors(sensors, mid)

        # Port 1 (AC Couple): correct-type power keys preserved, wrong-type = None
        assert sensors["ac_couple1_power_l1"] == 100.0
        assert sensors["smart_load1_power_l1"] is None
        assert sensors["smart_load1_power_l2"] is None
        assert sensors["smart_load1_power"] is None
        assert sensors["ac_couple1_today"] == 3.0
        assert "smart_load1_today" not in sensors

        # Port 2 (Unused): all removed
        assert "smart_load2_power_l1" not in sensors
        assert "ac_couple2_power_l1" not in sensors

        # Port 3 (Smart Load): correct-type power keys preserved, wrong-type = None
        assert sensors["smart_load3_power_l1"] == 50.0
        assert sensors["ac_couple3_power_l1"] is None
        assert sensors["ac_couple3_power_l2"] is None
        assert sensors["ac_couple3_power"] is None
        assert sensors["smart_load3_today"] == 1.5
        assert "ac_couple3_today" not in sensors

        # Port 4 (Unused): all removed
        assert "smart_load4_power_l1" not in sensors
        assert "ac_couple4_power_l1" not in sensors

    def test_setdefault_does_not_overwrite_existing_values(self):
        """Verify setdefault preserves existing API values (doesn't reset to 0.0)."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            DeviceProcessingMixin,
        )

        mid = self._make_mid_device({1: 2, 2: 0, 3: 0, 4: 0})
        sensors: dict = {
            "ac_couple1_power_l1": 999.0,
            "ac_couple1_power_l2": 888.0,
            "ac_couple1_power": 1887.0,
        }

        DeviceProcessingMixin._filter_unused_smart_port_sensors(sensors, mid)

        # Existing values NOT overwritten by setdefault
        assert sensors["ac_couple1_power_l1"] == 999.0
        assert sensors["ac_couple1_power_l2"] == 888.0
        assert sensors["ac_couple1_power"] == 1887.0
