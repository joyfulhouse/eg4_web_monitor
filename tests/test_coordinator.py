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
    INVERTER_ENERGY_KEYS,
    INVERTER_RUNTIME_KEYS,
    _build_battery_bank_sensor_mapping,
    _build_energy_sensor_mapping,
    _build_gridboss_sensor_mapping,
    _build_runtime_sensor_mapping,
    _features_from_family,
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

        # Every key from GRIDBOSS_SENSOR_KEYS should be present
        for key in GRIDBOSS_SENSOR_KEYS:
            assert key in sensors, f"Missing GridBOSS sensor key: {key}"

        # GridBOSS device should have binary_sensors dict
        assert "binary_sensors" in result["devices"]["GB001"]

    async def test_second_refresh_reads_registers(self, hass, local_config_entry):
        """Second refresh goes through normal register read path."""
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # First refresh: static data
        await coordinator._async_update_local_data()
        assert coordinator._local_static_phase_done is True

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

        assert len(result["devices"]) == 3
        assert result["devices"]["GB001"]["type"] == "gridboss"
        assert result["devices"]["INV001"]["type"] == "inverter"
        assert result["devices"]["INV002"]["type"] == "inverter"

        # GridBOSS should use GRIDBOSS_SENSOR_KEYS
        gb_keys = set(result["devices"]["GB001"]["sensors"].keys())
        assert GRIDBOSS_SENSOR_KEYS.issubset(gb_keys)

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


class TestForceMigration:
    """Tests for force-migration of polling intervals in __init__.py."""

    def test_http_polling_interval_constant_defaults(self):
        """Test that HTTP polling interval constants have expected values."""
        assert DEFAULT_HTTP_POLLING_INTERVAL == 120
        assert DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP == 90
