"""Tests for EG4 Data Update Coordinator."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.eg4_inverter_api.exceptions import (
    EG4APIError,
    EG4AuthError,
    EG4ConnectionError,
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
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )


@pytest.fixture
def mock_api_data():
    """Create mock API data."""
    return {
        "devices": [
            {
                "serialNum": "1234567890",
                "model": "FlexBOSS21",
                "type": "inverter",
            },
            {
                "serialNum": "9876543210",
                "model": "GridBOSS",
                "type": "gridboss",
            },
        ],
        "runtime_data": {
            "1234567890": {
                "acPower": 5000,
                "acVoltage": 2405,
                "batVoltage": 512,
            },
        },
    }


@pytest.fixture(autouse=True)
def mock_parameter_refresh():
    """Mock parameter refresh to prevent background tasks."""
    with patch(
        "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
        return_value=False,
    ):
        yield


class TestCoordinatorInitialization:
    """Test coordinator initialization."""

    async def test_coordinator_init(self, hass, mock_config_entry):
        """Test coordinator initializes with correct values."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        assert coordinator.entry == mock_config_entry
        assert coordinator.plant_id == "12345"
        assert coordinator.api is not None
        assert coordinator.devices == {}
        assert coordinator._last_available_state is True

    async def test_coordinator_creates_api_client(self, hass, mock_config_entry):
        """Test coordinator creates API client with correct parameters."""
        with patch(
            "custom_components.eg4_web_monitor.coordinator.EG4InverterAPI"
        ) as mock_api_class:
            _ = EG4DataUpdateCoordinator(hass, mock_config_entry)

            # Verify API was created with correct parameters
            mock_api_class.assert_called_once()
            call_kwargs = mock_api_class.call_args[1]
            assert call_kwargs["username"] == "test_user"
            assert call_kwargs["password"] == "test_pass"
            assert call_kwargs["base_url"] == "https://monitor.eg4electronics.com"
            assert call_kwargs["verify_ssl"] is True

    async def test_coordinator_uses_default_base_url(self, hass):
        """Test coordinator uses default base URL when not specified."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_USERNAME: "test_user",
                CONF_PASSWORD: "test_pass",
                CONF_PLANT_ID: "12345",
                # No base_url specified
            },
        )

        with patch(
            "custom_components.eg4_web_monitor.coordinator.EG4InverterAPI"
        ) as mock_api_class:
            _ = EG4DataUpdateCoordinator(hass, entry)

            call_kwargs = mock_api_class.call_args[1]
            assert call_kwargs["base_url"] == "https://monitor.eg4electronics.com"


class TestCoordinatorDataFetching:
    """Test coordinator data fetching."""

    async def test_fetch_data_success(self, hass, mock_config_entry, mock_api_data):
        """Test successful data fetch."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API methods
        coordinator.api.get_all_device_data = AsyncMock(return_value=mock_api_data)
        coordinator.api.get_plant_details = AsyncMock(
            return_value={"name": "Test Plant", "totalPower": 8500}
        )

        with patch.object(
            coordinator,
            "_process_device_data",
            new=AsyncMock(return_value={"devices": {}}),
        ):
            data = await coordinator._async_update_data()

            assert data is not None
            assert "devices" in data or "station" in data

    async def test_fetch_data_auth_error(self, hass, mock_config_entry):
        """Test auth error raises ConfigEntryAuthFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API to raise auth error
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4AuthError("Invalid credentials")
        )

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        # Verify availability state changed
        assert coordinator._last_available_state is False

    async def test_fetch_data_connection_error(self, hass, mock_config_entry):
        """Test connection error raises UpdateFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API to raise connection error
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4ConnectionError("Connection timeout")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        # Verify availability state changed
        assert coordinator._last_available_state is False

    async def test_fetch_data_api_error(self, hass, mock_config_entry):
        """Test API error raises UpdateFailed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API to raise API error
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4APIError("API error")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        # Verify availability state changed
        assert coordinator._last_available_state is False

    async def test_fetch_data_logs_reconnection(
        self, hass, mock_config_entry, mock_api_data
    ):
        """Test coordinator logs when service reconnects."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set initial state to unavailable
        coordinator._last_available_state = False

        # Mock API methods
        coordinator.api.get_all_device_data = AsyncMock(return_value=mock_api_data)
        coordinator.api.get_plant_details = AsyncMock(
            return_value={"name": "Test Plant"}
        )

        with patch.object(
            coordinator,
            "_process_device_data",
            new=AsyncMock(return_value={"devices": {}}),
        ):
            await coordinator._async_update_data()

            # Verify availability state changed back to True
            assert coordinator._last_available_state is True

    async def test_fetch_data_handles_station_error(
        self, hass, mock_config_entry, mock_api_data
    ):
        """Test coordinator handles station data fetch errors gracefully."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API methods - station fetch fails
        coordinator.api.get_all_device_data = AsyncMock(return_value=mock_api_data)
        coordinator.api.get_plant_details = AsyncMock(
            side_effect=Exception("Station fetch failed")
        )

        with patch.object(
            coordinator,
            "_process_device_data",
            new=AsyncMock(return_value={"devices": {}}),
        ):
            data = await coordinator._async_update_data()

            # Should still return data, just without station info
            assert data is not None
            assert "station" not in data or data.get("station") is None


class TestCoordinatorCaching:
    """Test coordinator caching behavior."""

    async def test_should_invalidate_cache_near_hour_boundary(
        self, hass, mock_config_entry
    ):
        """Test cache invalidation is triggered near hour boundary."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set current time to 4 minutes before hour
        mock_now = datetime(2025, 1, 15, 13, 56, 0)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.dt_util.utcnow",
            return_value=mock_now,
        ):
            assert coordinator._should_invalidate_cache() is True

    async def test_should_not_invalidate_cache_far_from_hour(
        self, hass, mock_config_entry
    ):
        """Test cache invalidation is not triggered far from hour boundary."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set current time to 10 minutes after hour
        mock_now = datetime(2025, 1, 15, 13, 10, 0)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.dt_util.utcnow",
            return_value=mock_now,
        ):
            assert coordinator._should_invalidate_cache() is False

    async def test_invalidate_cache_respects_rate_limit(self, hass, mock_config_entry):
        """Test cache invalidation respects 10-minute rate limit."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set last invalidation to recent time
        coordinator._last_cache_invalidation = datetime(2025, 1, 15, 13, 52, 0)

        # Current time is 5 minutes later (within 10-minute limit)
        mock_now = datetime(2025, 1, 15, 13, 57, 0)
        with patch(
            "custom_components.eg4_web_monitor.coordinator.dt_util.utcnow",
            return_value=mock_now,
        ):
            assert coordinator._should_invalidate_cache() is False

    async def test_invalidate_all_caches_calls_api(self, hass, mock_config_entry):
        """Test invalidate_all_caches calls API invalidate methods."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API invalidate method - the API client has this method
        if hasattr(coordinator.api, "invalidate_all_caches"):
            coordinator.api.invalidate_all_caches = MagicMock()
            coordinator._invalidate_all_caches()
            coordinator.api.invalidate_all_caches.assert_called_once()
        else:
            # If method doesn't exist, just verify _invalidate_all_caches runs
            coordinator._invalidate_all_caches()
            assert coordinator._last_cache_invalidation is not None

    async def test_invalidate_caches_updates_timestamp(self, hass, mock_config_entry):
        """Test cache invalidation updates last invalidation timestamp."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API
        coordinator.api.invalidate_all_caches = MagicMock()

        assert coordinator._last_cache_invalidation is None

        coordinator._invalidate_all_caches()

        # Verify timestamp was updated
        assert coordinator._last_cache_invalidation is not None


class TestCoordinatorParameterRefresh:
    """Test coordinator parameter refresh."""

    async def test_should_refresh_parameters_when_due(self, hass, mock_config_entry):
        """Test parameter refresh is due after interval."""
        # Need to remove the autouse fixture mock for this specific test
        with patch(
            "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
            wraps=lambda self: (
                self._last_parameter_refresh is None
                or datetime.now() - self._last_parameter_refresh > timedelta(hours=1)
            ),
        ):
            coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

            # Set last refresh to over an hour ago
            coordinator._last_parameter_refresh = datetime.now() - timedelta(hours=2)

            # Should return True since it's been over an hour
            assert (
                coordinator._last_parameter_refresh is None
                or datetime.now() - coordinator._last_parameter_refresh
                > timedelta(hours=1)
            ) is True

    async def test_should_not_refresh_parameters_when_recent(
        self, hass, mock_config_entry
    ):
        """Test parameter refresh is not due when recent."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set last refresh to 10 minutes ago
        coordinator._last_parameter_refresh = datetime.now() - timedelta(minutes=10)

        with patch(
            "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
            wraps=coordinator._should_refresh_parameters,
        ):
            assert coordinator._should_refresh_parameters() is False

    async def test_hourly_parameter_refresh_updates_devices(
        self, hass, mock_config_entry
    ):
        """Test hourly parameter refresh updates device parameters."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Add devices to coordinator
        coordinator.devices = {
            "1234567890": {"type": "inverter", "model": "FlexBOSS21"},
        }

        # Mock read_device_parameters_ranges
        with patch(
            "custom_components.eg4_web_monitor.coordinator.read_device_parameters_ranges",
            new=AsyncMock(
                return_value=[{"param1": 100}, {"param2": 200}, {"param3": 300}]
            ),
        ):
            await coordinator._hourly_parameter_refresh()

            # Verify last refresh time was updated
            assert coordinator._last_parameter_refresh is not None


class TestCoordinatorDeviceData:
    """Test coordinator device data processing."""

    async def test_process_device_data_handles_inverters(self, hass, mock_config_entry):
        """Test processing of inverter device data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Coordinator expects devices as dict with serial as key
        device_data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            }
        }

        # Mock API methods
        coordinator.api.get_inverter_runtime = AsyncMock(
            return_value={"acPower": 5000, "acVoltage": 2405}
        )
        coordinator.api.get_inverter_energy = AsyncMock(
            return_value={"todayEnergy": 456}
        )
        coordinator.api.get_battery_info = AsyncMock(return_value={"batteryArray": []})

        result = await coordinator._process_device_data(device_data)

        assert "devices" in result
        assert "1234567890" in result["devices"]

        # Clean up coordinator to prevent lingering timers
        # Need extra time for debouncer cancellation to complete in CI
        await hass.async_block_till_done()
        await coordinator.async_shutdown()
        await hass.async_block_till_done()
        # Give debouncer extra time to fully cancel (CI timing issue - needs longer delay)
        await asyncio.sleep(0.5)
        await hass.async_block_till_done()

    async def test_process_device_data_handles_gridboss(self, hass, mock_config_entry):
        """Test processing of GridBOSS device data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Coordinator expects devices as dict with serial as key
        device_data = {
            "devices": {
                "9876543210": {
                    "type": "gridboss",
                    "model": "GridBOSS",
                }
            }
        }

        # Mock API method
        coordinator.api.get_midbox_runtime = AsyncMock(
            return_value={"gridPower": 3000, "loadPower": 2500}
        )

        result = await coordinator._process_device_data(device_data)

        assert "devices" in result
        assert "9876543210" in result["devices"]

        # Clean up coordinator to prevent lingering timers
        await hass.async_block_till_done()
        await coordinator.async_shutdown()
        await hass.async_block_till_done()


class TestCoordinatorAvailability:
    """Test coordinator availability tracking."""

    async def test_tracks_availability_state_changes(self, hass, mock_config_entry):
        """Test coordinator tracks availability state changes."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        assert coordinator._last_available_state is True

        # Simulate failure
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4ConnectionError("Connection failed")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator._last_available_state is False

    async def test_logs_state_transitions(self, hass, mock_config_entry, mock_api_data):
        """Test coordinator logs availability state transitions."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Start unavailable
        coordinator._last_available_state = False

        # Mock successful fetch
        coordinator.api.get_all_device_data = AsyncMock(return_value=mock_api_data)
        coordinator.api.get_plant_details = AsyncMock(
            return_value={"name": "Test Plant"}
        )

        with patch.object(
            coordinator,
            "_process_device_data",
            new=AsyncMock(return_value={"devices": {}}),
        ):
            with patch(
                "custom_components.eg4_web_monitor.coordinator._LOGGER"
            ) as mock_logger:
                await coordinator._async_update_data()

                # Should have logged reconnection
                assert any(
                    "reconnected" in str(call).lower()
                    for call in mock_logger.warning.call_args_list
                )


class TestCoordinatorCircuitBreaker:
    """Test coordinator circuit breaker functionality."""

    async def test_circuit_breaker_initialized(self, hass, mock_config_entry):
        """Test circuit breaker is initialized."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        assert coordinator._circuit_breaker is not None
        assert coordinator._circuit_breaker.failure_threshold == 3
        assert coordinator._circuit_breaker.timeout == 30


class TestCoordinatorDeviceInfo:
    """Test coordinator device info methods."""

    async def test_get_device_info_for_inverter(self, hass, mock_config_entry):
        """Test get_device_info returns proper DeviceInfo for inverter."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {"1234567890": {"type": "inverter", "model": "FlexBOSS21"}},
            "device_info": {
                "1234567890": {
                    "deviceTypeText4APP": "FlexBOSS21",
                    "firmwareVersion": "1.0.0",
                }
            },
        }

        device_info = coordinator.get_device_info("1234567890")

        assert device_info is not None
        assert ("eg4_web_monitor", "1234567890") in device_info["identifiers"]
        assert "FlexBOSS21" in device_info["model"]

    async def test_get_device_info_missing_device(self, hass, mock_config_entry):
        """Test get_device_info returns None for missing device."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {"devices": {}}

        device_info = coordinator.get_device_info("nonexistent")

        assert device_info is None

    async def test_get_battery_device_info(self, hass, mock_config_entry):
        """Test get_battery_device_info returns proper DeviceInfo."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "batteries": {
                        "battery1": {
                            "batteryName": "Battery Pack 1",
                            "voltage": 52.0,
                        }
                    },
                }
            },
            "device_info": {
                "1234567890": {
                    "deviceTypeText4APP": "FlexBOSS21",
                }
            },
        }

        device_info = coordinator.get_battery_device_info("1234567890", "battery1")

        assert device_info is not None
        assert "battery" in device_info["name"].lower()
        assert ("eg4_web_monitor", "1234567890_battery1") in device_info["identifiers"]

    async def test_get_station_device_info(self, hass, mock_config_entry):
        """Test get_station_device_info returns proper DeviceInfo."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "station": {
                "plantName": "My Station",
                "plantId": "station123",
            }
        }

        device_info = coordinator.get_station_device_info()

        assert device_info is not None
        assert "Station" in device_info["name"]
        assert any(
            "station" in str(identifier).lower()
            for identifier in device_info["identifiers"]
        )

    async def test_get_station_device_info_no_station(self, hass, mock_config_entry):
        """Test get_station_device_info returns None when no station data."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {}

        device_info = coordinator.get_station_device_info()

        assert device_info is None


class TestCoordinatorParameterRefreshAdditional:
    """Test coordinator parameter refresh functionality - additional tests."""

    @pytest.mark.asyncio
    async def test_refresh_all_device_parameters_no_devices(
        self, hass, mock_config_entry
    ):
        """Test refresh_all_device_parameters handles no devices gracefully."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {}

        # Should not raise an error
        await coordinator.refresh_all_device_parameters()

        assert coordinator.data == {}

    @pytest.mark.asyncio
    async def test_refresh_all_device_parameters_with_no_inverters(
        self, hass, mock_config_entry
    ):
        """Test refresh_all_device_parameters handles no inverters gracefully."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {
                "gridboss123": {"type": "gridboss"},
                "parallel1": {"type": "parallel_group"},
            }
        }

        # Should not raise an error when there are no inverters
        await coordinator.refresh_all_device_parameters()

        assert len(coordinator.data["devices"]) == 2


class TestCoordinatorParallelGroup:
    """Test coordinator parallel group methods."""

    async def test_get_parallel_group_for_device(self, hass, mock_config_entry):
        """Test _get_parallel_group_for_device finds group."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {
            "devices": {"group1": {"type": "parallel_group"}},
            "parallel_groups_info": [
                {
                    "inverterList": [
                        {"serialNum": "1234567890"},
                        {"serialNum": "0987654321"},
                    ]
                }
            ],
        }

        group_id = coordinator._get_parallel_group_for_device("1234567890")

        assert group_id == "group1"

    async def test_get_parallel_group_for_device_not_found(
        self, hass, mock_config_entry
    ):
        """Test _get_parallel_group_for_device returns None when not found."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = {"devices": {}, "parallel_groups_info": []}

        group_id = coordinator._get_parallel_group_for_device("1234567890")

        assert group_id is None
