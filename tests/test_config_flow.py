"""Test config flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor._config_flow.discovery import detect_grid_type
from custom_components.eg4_web_monitor._config_flow.helpers import timezone_observes_dst
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from pylxpweb.exceptions import (
    LuxpowerAPIError as EG4APIError,
    LuxpowerAuthError as EG4AuthError,
    LuxpowerConnectionError as EG4ConnectionError,
)


# ====================
# DST Detection Tests
# ====================


class TestTimezoneObservesDst:
    """Tests for the timezone_observes_dst helper function."""

    def test_dst_timezone_returns_true(self):
        """Test that timezones with DST return True."""
        assert timezone_observes_dst("America/New_York") is True
        assert timezone_observes_dst("America/Los_Angeles") is True
        assert timezone_observes_dst("America/Chicago") is True
        assert timezone_observes_dst("America/Denver") is True

    def test_european_dst_timezone_returns_true(self):
        """Test that European timezones with DST return True."""
        assert timezone_observes_dst("Europe/London") is True
        assert timezone_observes_dst("Europe/Paris") is True
        assert timezone_observes_dst("Europe/Berlin") is True

    def test_southern_hemisphere_dst_timezone_returns_true(self):
        """Test that Southern Hemisphere timezones with DST return True."""
        assert timezone_observes_dst("Australia/Sydney") is True
        assert timezone_observes_dst("Australia/Melbourne") is True
        assert timezone_observes_dst("Pacific/Auckland") is True
        assert timezone_observes_dst("America/Santiago") is True

    def test_countries_that_abolished_dst_return_false(self):
        """Test that countries that recently abolished DST return False."""
        assert timezone_observes_dst("America/Sao_Paulo") is False
        assert timezone_observes_dst("Europe/Moscow") is False
        assert timezone_observes_dst("Europe/Istanbul") is False

    def test_non_dst_timezone_returns_false(self):
        """Test that timezones without DST return False."""
        assert timezone_observes_dst("UTC") is False
        assert timezone_observes_dst("America/Phoenix") is False
        assert timezone_observes_dst("Asia/Tokyo") is False
        assert timezone_observes_dst("Asia/Shanghai") is False
        assert timezone_observes_dst("Asia/Singapore") is False

    def test_none_timezone_returns_false(self):
        """Test that None timezone returns False."""
        assert timezone_observes_dst(None) is False

    def test_empty_timezone_returns_false(self):
        """Test that empty string timezone returns False."""
        assert timezone_observes_dst("") is False

    def test_invalid_timezone_returns_false(self):
        """Test that invalid timezone names return False."""
        assert timezone_observes_dst("Invalid/Timezone") is False
        assert timezone_observes_dst("Not_A_Timezone") is False


@pytest.fixture
def hass_with_dst_timezone(hass: HomeAssistant):
    """Set up HA with a timezone that observes DST."""
    hass.config.time_zone = "America/New_York"
    return hass


@pytest.fixture
def hass_with_non_dst_timezone(hass: HomeAssistant):
    """Set up HA with a timezone that does NOT observe DST."""
    hass.config.time_zone = "UTC"
    return hass


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock async_setup_entry and platform setups to prevent integration setup.

    Config flow tests trigger entry creation which calls async_setup_entry and creates
    aiohttp ClientSession instances. These spawn background threads that cause cleanup
    errors during test teardown. Mocking prevents thread creation while still allowing
    tests to validate configuration logic.
    """
    with (
        patch(
            "custom_components.eg4_web_monitor.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_setup",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
            return_value=False,
        ),
    ):
        yield


def _mock_luxpower_client(stations=None, side_effect=None):
    """Create patched LuxpowerClient and Station.load_all context manager.

    Args:
        stations: List of mock Station objects to return from load_all.
        side_effect: Exception to raise from Station.load_all.
    """
    load_all_kwargs = (
        {"side_effect": side_effect} if side_effect else {"return_value": stations}
    )
    client_patch = patch(
        "custom_components.eg4_web_monitor._config_flow.LuxpowerClient"
    )
    station_patch = patch(
        "pylxpweb.devices.Station.load_all",
        new=AsyncMock(**load_all_kwargs),
    )

    class _Combined:
        def __enter__(self_inner):
            mock_client_class = client_patch.__enter__()
            station_patch.__enter__()
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_instance
            return mock_client_class

        def __exit__(self_inner, *args):
            station_patch.__exit__(*args)
            client_patch.__exit__(*args)

    return _Combined()


@pytest.fixture
def mock_api():
    """Create a mock for LuxpowerClient with multiple plants."""
    from tests.conftest import create_mock_station

    stations = [
        create_mock_station("123", "Test Plant 1"),
        create_mock_station("456", "Test Plant 2"),
    ]
    with _mock_luxpower_client(stations=stations):
        yield None


@pytest.fixture
def mock_api_single_plant():
    """Create a mock for LuxpowerClient with a single plant."""
    from tests.conftest import create_mock_station

    with _mock_luxpower_client(stations=[create_mock_station("123", "Test Plant")]):
        yield None


async def _init_and_select_cloud(hass: HomeAssistant):
    """Init flow and navigate through the user menu to cloud_credentials."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "user"

    # Select cloud path from menu
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_credentials"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud_credentials"
    return result


async def test_user_flow_success_multiple_plants(hass: HomeAssistant, mock_api):
    """Test successful user flow with multiple plants."""
    result = await _init_and_select_cloud(hass)

    # Submit credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should proceed to station selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud_station"

    # Select plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "123"},
    )

    # After station selection, should show cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "cloud_add_local"

    # Finish without adding local devices
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    # Should create entry
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "EG4 Electronics - Test Plant 1"
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TYPE_HTTP
    assert result["data"][CONF_USERNAME] == "test@example.com"
    assert result["data"][CONF_PLANT_ID] == "123"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant 1"
    assert result["data"][CONF_LOCAL_TRANSPORTS] == []

    await hass.async_block_till_done()


async def test_user_flow_success_single_plant(
    hass: HomeAssistant, mock_api_single_plant
):
    """Test successful user flow with single plant (auto-select)."""
    result = await _init_and_select_cloud(hass)

    # Submit credentials - should auto-select single plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show cloud_add_local menu (single plant auto-selected)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "cloud_add_local"

    # Finish without local devices
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PLANT_ID] == "123"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant"
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TYPE_HTTP


async def _test_cloud_error(hass, exception, expected_error):
    """Test cloud credential flow with a specific error."""
    with _mock_luxpower_client(side_effect=exception):
        result = await _init_and_select_cloud(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "cloud_credentials"
        assert result["errors"] == {"base": expected_error}


async def test_user_flow_invalid_auth(hass: HomeAssistant):
    """Test flow with invalid authentication."""
    await _test_cloud_error(hass, EG4AuthError("Invalid credentials"), "invalid_auth")


async def test_user_flow_cannot_connect(hass: HomeAssistant):
    """Test flow with connection error."""
    await _test_cloud_error(
        hass, EG4ConnectionError("Cannot connect"), "cannot_connect"
    )


async def test_user_flow_api_error(hass: HomeAssistant):
    """Test flow with API error."""
    await _test_cloud_error(hass, EG4APIError("API Error"), "cannot_connect")


async def test_user_flow_unknown_exception(hass: HomeAssistant):
    """Test flow with unexpected exception."""
    await _test_cloud_error(hass, Exception("Unexpected"), "unknown")


async def test_user_flow_error_recovery(hass: HomeAssistant, mock_api_single_plant):
    """Test user can recover from errors and complete flow."""
    # First attempt - invalid auth
    with _mock_luxpower_client(side_effect=EG4AuthError("Invalid credentials")):
        result = await _init_and_select_cloud(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "wrongpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}

    # Second attempt - success (uses mock_api_single_plant fixture)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "correctpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "cloud_add_local"

    # Finish
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(hass: HomeAssistant, mock_api):
    """Test flow aborts if already configured."""
    MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Electronics - Test Plant 1",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "123",
            CONF_PLANT_NAME: "Test Plant 1",
            CONF_LOCAL_TRANSPORTS: [],
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",
    ).add_to_hass(hass)

    result = await _init_and_select_cloud(hass)

    # Submit credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show station selection (multiple plants)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud_station"

    # Select the same plant that's already configured
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "123"},
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    # Should abort due to duplicate unique_id
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_plant_selection_flow(hass: HomeAssistant, mock_api):
    """Test plant selection step."""
    result = await _init_and_select_cloud(hass)

    # Submit credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show station selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud_station"

    # Select second plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "456"},
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PLANT_ID] == "456"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant 2"


async def test_flow_with_custom_base_url(hass: HomeAssistant, mock_api_single_plant):
    """Test flow with custom base URL."""
    result = await _init_and_select_cloud(hass)

    # Submit credentials with custom URL
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: "https://custom.eg4.com",
            CONF_VERIFY_SSL: False,
        },
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == "https://custom.eg4.com"
    assert result["data"][CONF_VERIFY_SSL] is False


# ================================
# DST Sync Default Behavior Tests
# ================================


async def test_dst_sync_default_true_for_dst_timezone(
    hass_with_dst_timezone: HomeAssistant, mock_api_single_plant
):
    """Test DST sync defaults to True when HA timezone observes DST."""
    hass = hass_with_dst_timezone

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_credentials"},
    )

    # Submit credentials without explicitly setting DST sync
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DST_SYNC] is True


async def test_dst_sync_default_false_for_non_dst_timezone(
    hass_with_non_dst_timezone: HomeAssistant, mock_api_single_plant
):
    """Test DST sync defaults to False when HA timezone does NOT observe DST."""
    hass = hass_with_non_dst_timezone

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_credentials"},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DST_SYNC] is False


async def test_user_can_override_dst_sync_default(
    hass_with_non_dst_timezone: HomeAssistant, mock_api_single_plant
):
    """Test user can explicitly set DST sync to True even in non-DST timezone."""
    hass = hass_with_non_dst_timezone

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_credentials"},
    )

    # User explicitly enables DST sync
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    # cloud_add_local menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "cloud_finish"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DST_SYNC] is True


# =====================================================
# LOCAL DEVICE FLOW TESTS
# =====================================================


def _make_discovered_device(
    serial="1234567890",
    model="FlexBOSS21",
    family="EG4_HYBRID",
    device_type_code=10284,
    firmware_version="1.0.0",
    is_gridboss=False,
    pv_power=1500.0,
    battery_soc=65,
    parallel_master_slave=0,
):
    """Create a DiscoveredDevice for use in tests."""
    from custom_components.eg4_web_monitor._config_flow.discovery import (
        DiscoveredDevice,
    )

    return DiscoveredDevice(
        serial=serial,
        model=model,
        family=family,
        device_type_code=device_type_code,
        firmware_version=firmware_version,
        is_gridboss=is_gridboss,
        pv_power=pv_power,
        battery_soc=battery_soc,
        parallel_master_slave=parallel_master_slave,
    )


async def _init_and_select_local(hass: HomeAssistant):
    """Init flow and navigate through the user menu to local_device_type."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "user"

    # Select local path from menu
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "local_device_type"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "local_device_type"
    return result


# =====================================================
# async_step_local_device_type
# =====================================================


class TestLocalDeviceTypeMenu:
    """Tests for the local device type selection menu."""

    async def test_local_device_type_shows_menu(self, hass: HomeAssistant):
        """Test local_device_type shows menu with correct options."""
        result = await _init_and_select_local(hass)
        assert result["type"] == data_entry_flow.FlowResultType.MENU
        assert result["step_id"] == "local_device_type"
        assert "local_modbus" in result["menu_options"]
        assert "local_dongle" in result["menu_options"]
        assert "local_serial" in result["menu_options"]
        assert "network_scan_config" in result["menu_options"]


# =====================================================
# async_step_local_modbus
# =====================================================


class TestLocalModbusFlow:
    """Tests for the Modbus TCP local device configuration flow."""

    async def test_modbus_success(self, hass: HomeAssistant):
        """Test successful Modbus device discovery and entry creation."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            # Select Modbus from local device type menu
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"

            # Submit Modbus config
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Should show grid type form
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Finish without cloud
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_finish"

            # Provide station name
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"station_name": "My Solar Setup"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            assert result["title"] == "EG4 Electronics - My Solar Setup"
            assert result["data"][CONF_CONNECTION_TYPE] == "local"
            assert len(result["data"][CONF_LOCAL_TRANSPORTS]) == 1

            transport = result["data"][CONF_LOCAL_TRANSPORTS][0]
            assert transport["transport_type"] == "modbus_tcp"
            assert transport["serial"] == "1234567890"
            assert transport["host"] == "192.168.1.100"
            assert transport["port"] == 502

    async def test_modbus_timeout_error(self, hass: HomeAssistant):
        """Test Modbus connection timeout shows appropriate error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=TimeoutError("Connection timed out")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"
            assert result["errors"] == {"base": "modbus_timeout"}

    async def test_modbus_connection_refused(self, hass: HomeAssistant):
        """Test Modbus connection refused shows appropriate error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=OSError("Connection refused")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"
            assert result["errors"] == {"base": "modbus_connection_failed"}

    async def test_modbus_unknown_error(self, hass: HomeAssistant):
        """Test Modbus unexpected error shows unknown error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=RuntimeError("Unexpected")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"
            assert result["errors"] == {"base": "unknown"}

    async def test_modbus_duplicate_transport(self, hass: HomeAssistant):
        """Test duplicate host:port is rejected."""
        device1 = _make_discovered_device(serial="1111111111")
        device2 = _make_discovered_device(serial="2222222222")

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=[device1, device2]),
        ):
            result = await _init_and_select_local(hass)

            # Select Modbus, add first device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type to proceed
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Add another device with same host:port
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_device_type"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"
            assert result["errors"] == {"base": "duplicate_transport"}

    async def test_modbus_duplicate_serial(self, hass: HomeAssistant):
        """Test duplicate serial number in same flow is rejected."""
        device = _make_discovered_device(serial="1234567890")

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            # Add first device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type to proceed
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Try add same serial on different host
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_device_type"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.200",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_modbus"
            assert result["errors"] == {"base": "duplicate_serial"}

    async def test_modbus_shows_form_without_input(self, hass: HomeAssistant):
        """Test Modbus step shows form on initial load (no user_input)."""
        result = await _init_and_select_local(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "local_modbus"},
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "local_modbus"
        assert result["errors"] == {}


# =====================================================
# async_step_local_dongle
# =====================================================


class TestLocalDongleFlow:
    """Tests for the WiFi Dongle local device configuration flow."""

    async def test_dongle_success(self, hass: HomeAssistant):
        """Test successful dongle device discovery and entry creation."""
        device = _make_discovered_device(serial="9876543210")

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_dongle"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ12345678",
                    "inverter_serial": "9876543210",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Finish
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"station_name": "Dongle Setup"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            assert result["data"][CONF_CONNECTION_TYPE] == "local"
            transport = result["data"][CONF_LOCAL_TRANSPORTS][0]
            assert transport["transport_type"] == "wifi_dongle"
            assert transport["serial"] == "9876543210"
            assert transport["host"] == "192.168.1.150"
            assert transport["port"] == 8000

    async def test_dongle_timeout_error(self, hass: HomeAssistant):
        """Test dongle connection timeout shows appropriate error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(side_effect=TimeoutError("Timeout")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ12345678",
                    "inverter_serial": "9876543210",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_dongle"
            assert result["errors"] == {"base": "dongle_timeout"}

    async def test_dongle_connection_failed(self, hass: HomeAssistant):
        """Test dongle connection failure shows appropriate error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(side_effect=OSError("Connection failed")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ12345678",
                    "inverter_serial": "9876543210",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_dongle"
            assert result["errors"] == {"base": "dongle_connection_failed"}

    async def test_dongle_unknown_error(self, hass: HomeAssistant):
        """Test dongle unexpected error shows unknown error."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(side_effect=RuntimeError("Unexpected")),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ12345678",
                    "inverter_serial": "9876543210",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_dongle"
            assert result["errors"] == {"base": "unknown"}

    async def test_dongle_duplicate_transport(self, hass: HomeAssistant):
        """Test duplicate dongle host:port is rejected."""
        device1 = _make_discovered_device(serial="1111111111")
        device2 = _make_discovered_device(serial="2222222222")

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(side_effect=[device1, device2]),
        ):
            result = await _init_and_select_local(hass)

            # Add first dongle
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "D111",
                    "inverter_serial": "1111111111",
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type to proceed
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Try same host:port with different dongle serial
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_device_type"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.150",
                    "dongle_port": 8000,
                    "dongle_serial": "D222",
                    "inverter_serial": "2222222222",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_dongle"
            assert result["errors"] == {"base": "duplicate_transport"}

    async def test_dongle_shows_form_without_input(self, hass: HomeAssistant):
        """Test dongle step shows form on initial load (no user_input)."""
        result = await _init_and_select_local(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "local_dongle"},
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "local_dongle"
        assert result["errors"] == {}


# =====================================================
# async_step_local_device_confirmed & local_finish
# =====================================================


class TestLocalDeviceConfirmedAndFinish:
    """Tests for device confirmed menu and local finish."""

    async def test_device_confirmed_shows_grid_type_form(self, hass: HomeAssistant):
        """Test that local_device_confirmed shows grid type form for inverters."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Inverters show grid type form
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_device_confirmed"
            assert result["description_placeholders"]["device_model"] == "FlexBOSS21"

    async def test_device_added_menu_shows_cloud_option_when_no_cloud(
        self, hass: HomeAssistant
    ):
        """Test that local_device_added includes cloud option when no cloud configured."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Submit grid type form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )

            assert result["step_id"] == "local_device_added"
            # Without cloud, should have option to add cloud
            assert "local_add_cloud" in result["menu_options"]
            assert "local_device_type" in result["menu_options"]
            assert "local_finish" in result["menu_options"]

    async def test_grid_type_stored_in_config(self, hass: HomeAssistant):
        """Test that user-selected grid type is stored in transport config."""
        device = _make_discovered_device(family="LXP", device_type_code=44)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Select single_phase (Brazilian user)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "single_phase"},
            )

            # Finish the flow
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"station_name": "Brazil Install"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            transport = result["data"][CONF_LOCAL_TRANSPORTS][0]
            assert transport["grid_type"] == "single_phase"

    async def test_local_finish_default_station_name(self, hass: HomeAssistant):
        """Test local finish uses device info when station name is empty."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Submit grid type form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )

            # Submit empty station name -> auto-generates from device info
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"station_name": ""},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            # Default name from first transport model + serial
            assert "FlexBOSS21" in result["title"]
            assert "1234567890" in result["title"]

    async def test_local_finish_shows_form_without_input(self, hass: HomeAssistant):
        """Test local finish shows name form when no user_input."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # Submit grid type form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_finish"

    async def test_gridboss_device_confirmed_label(self, hass: HomeAssistant):
        """Test GridBOSS skips grid type form and goes to device_added menu."""
        device = _make_discovered_device(
            serial="5555555555",
            model="GridBOSS",
            family="MID_DEVICE",
            device_type_code=50,
            is_gridboss=True,
        )

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            # GridBOSS skips grid type form, goes straight to device_added menu
            assert result["type"] == data_entry_flow.FlowResultType.MENU
            assert result["step_id"] == "local_device_added"
            assert result["description_placeholders"]["device_count"] == "1"


# =====================================================
# Add multiple local devices
# =====================================================


class TestAddMultipleLocalDevices:
    """Tests for adding multiple local devices in a single flow."""

    async def test_add_two_modbus_devices(self, hass: HomeAssistant):
        """Test adding two Modbus devices and creating entry with both."""
        device1 = _make_discovered_device(serial="1111111111", model="FlexBOSS21")
        device2 = _make_discovered_device(serial="2222222222", model="18kPV")

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=[device1, device2]),
        ):
            result = await _init_and_select_local(hass)

            # First device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type for first device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"
            assert result["description_placeholders"]["device_count"] == "1"

            # Add another device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_device_type"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.101",
                    "modbus_port": 502,
                    "modbus_unit_id": 2,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type for second device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"
            assert result["description_placeholders"]["device_count"] == "2"

            # Finish
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"station_name": "Dual Inverter"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            assert len(result["data"][CONF_LOCAL_TRANSPORTS]) == 2
            assert result["data"][CONF_LOCAL_TRANSPORTS][0]["serial"] == "1111111111"
            assert result["data"][CONF_LOCAL_TRANSPORTS][1]["serial"] == "2222222222"


# =====================================================
# Local-first then add cloud (hybrid)
# =====================================================


class TestLocalThenCloudHybrid:
    """Tests for local-first flow that adds cloud credentials (hybrid mode)."""

    async def test_local_then_add_cloud_creates_hybrid(
        self, hass: HomeAssistant, mock_api_single_plant
    ):
        """Test adding cloud from local_device_added creates hybrid entry."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Choose to add cloud
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_add_cloud"},
            )
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "cloud_credentials"

            # Submit cloud credentials
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test@example.com",
                    CONF_PASSWORD: "testpassword",
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_VERIFY_SSL: True,
                },
            )

            # Single plant auto-selected -> cloud_add_local menu
            assert result["type"] == data_entry_flow.FlowResultType.MENU
            assert result["step_id"] == "cloud_add_local"

            # Finish
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "cloud_finish"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            assert result["data"][CONF_CONNECTION_TYPE] == "hybrid"
            assert result["data"][CONF_USERNAME] == "test@example.com"
            assert len(result["data"][CONF_LOCAL_TRANSPORTS]) == 1


# =====================================================
# _discover_serial_device_with_errors
# =====================================================


class TestDiscoverSerialDeviceWithErrors:
    """Tests for the serial device discovery error handling helper."""

    async def test_serial_timeout_error(self, hass: HomeAssistant):
        """Test serial discovery timeout returns correct error."""
        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.discover_serial_device",
                new=AsyncMock(side_effect=TimeoutError("Timeout")),
            ),
            patch(
                "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
                return_value=[],
            ),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "/dev/ttyUSB0",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_serial"
            assert result["errors"] == {"base": "serial_timeout"}

    async def test_serial_permission_denied(self, hass: HomeAssistant):
        """Test serial port permission denied returns correct error."""
        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.discover_serial_device",
                new=AsyncMock(side_effect=PermissionError("Access denied")),
            ),
            patch(
                "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
                return_value=[],
            ),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "/dev/ttyUSB0",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_serial"
            assert result["errors"] == {"base": "serial_permission_denied"}

    async def test_serial_port_in_use(self, hass: HomeAssistant):
        """Test serial port already in use returns correct error."""
        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.discover_serial_device",
                new=AsyncMock(
                    side_effect=OSError("Port /dev/ttyUSB0 is already in use")
                ),
            ),
            patch(
                "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
                return_value=[],
            ),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "/dev/ttyUSB0",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_serial"
            assert result["errors"] == {"base": "serial_port_in_use"}

    async def test_serial_generic_os_error(self, hass: HomeAssistant):
        """Test generic serial OSError returns port_error."""
        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.discover_serial_device",
                new=AsyncMock(side_effect=OSError("No such device")),
            ),
            patch(
                "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
                return_value=[],
            ),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "/dev/ttyUSB0",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_serial"
            assert result["errors"] == {"base": "serial_port_error"}

    async def test_serial_success(self, hass: HomeAssistant):
        """Test successful serial device discovery."""
        device = _make_discovered_device(serial="5555555555")

        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.discover_serial_device",
                new=AsyncMock(return_value=device),
            ),
            patch(
                "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
                return_value=[],
            ),
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "/dev/ttyUSB0",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_device_confirmed"

    async def test_serial_manual_entry_redirect(self, hass: HomeAssistant):
        """Test selecting manual_entry redirects to serial_manual step."""
        with patch(
            "custom_components.eg4_web_monitor._config_flow.serial_ports.list_serial_ports",
            return_value=[],
        ):
            result = await _init_and_select_local(hass)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_serial"},
            )
            assert result["step_id"] == "local_serial"

            # Select manual_entry as the serial port
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "serial_port": "manual_entry",
                    "serial_baudrate": 19200,
                    "serial_parity": "N",
                    "serial_stopbits": 1,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "local_serial_manual"


# =====================================================
# _has_duplicate_transport
# =====================================================


class TestHasDuplicateTransport:
    """Tests for the _has_duplicate_transport helper."""

    def test_no_duplicates_empty(self):
        """Test no duplicates when transport list is empty."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        assert flow._has_duplicate_transport("192.168.1.1", 502) is False

    def test_detects_duplicate(self):
        """Test detects duplicate host:port."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._local_transports = [
            {"host": "192.168.1.1", "port": 502, "serial": "1234"},
        ]
        assert flow._has_duplicate_transport("192.168.1.1", 502) is True

    def test_different_port_not_duplicate(self):
        """Test same host but different port is not duplicate."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._local_transports = [
            {"host": "192.168.1.1", "port": 502, "serial": "1234"},
        ]
        assert flow._has_duplicate_transport("192.168.1.1", 8000) is False

    def test_different_host_not_duplicate(self):
        """Test different host same port is not duplicate."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._local_transports = [
            {"host": "192.168.1.1", "port": 502, "serial": "1234"},
        ]
        assert flow._has_duplicate_transport("192.168.1.2", 502) is False


# =====================================================
# _derive_connection_type
# =====================================================


class TestDeriveConnectionType:
    """Tests for _derive_connection_type helper function."""

    def test_cloud_only(self):
        """Test cloud only returns http."""
        from custom_components.eg4_web_monitor._config_flow import (
            _derive_connection_type,
        )

        assert _derive_connection_type(has_cloud=True, has_local=False) == "http"

    def test_local_only(self):
        """Test local only returns local."""
        from custom_components.eg4_web_monitor._config_flow import (
            _derive_connection_type,
        )

        assert _derive_connection_type(has_cloud=False, has_local=True) == "local"

    def test_both_returns_hybrid(self):
        """Test both cloud and local returns hybrid."""
        from custom_components.eg4_web_monitor._config_flow import (
            _derive_connection_type,
        )

        assert _derive_connection_type(has_cloud=True, has_local=True) == "hybrid"

    def test_neither_returns_local(self):
        """Test neither returns local (edge case)."""
        from custom_components.eg4_web_monitor._config_flow import (
            _derive_connection_type,
        )

        assert _derive_connection_type(has_cloud=False, has_local=False) == "local"


# =====================================================
# Cloud-first then add local device (hybrid)
# =====================================================


class TestCloudThenAddLocal:
    """Tests for cloud-first flow that adds a local device (hybrid mode)."""

    async def test_cloud_then_add_modbus_creates_hybrid(
        self, hass: HomeAssistant, mock_api_single_plant
    ):
        """Test cloud flow adding local Modbus device creates hybrid entry."""
        device = _make_discovered_device()

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_and_select_cloud(hass)

            # Submit credentials
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test@example.com",
                    CONF_PASSWORD: "testpassword",
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_VERIFY_SSL: True,
                },
            )

            # Single plant auto-selected -> cloud_add_local menu
            assert result["type"] == data_entry_flow.FlowResultType.MENU
            assert result["step_id"] == "cloud_add_local"

            # Choose to add local device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_device_type"},
            )
            assert result["step_id"] == "local_device_type"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )
            assert result["step_id"] == "local_device_added"

            # Cloud is already configured, so no local_add_cloud option
            assert "local_add_cloud" not in result["menu_options"]

            # Finish
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "local_finish"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
            assert result["data"][CONF_CONNECTION_TYPE] == "hybrid"
            assert result["data"][CONF_USERNAME] == "test@example.com"
            assert result["data"][CONF_PLANT_ID] == "123"
            assert len(result["data"][CONF_LOCAL_TRANSPORTS]) == 1


# =====================================================
# detect_grid_type auto-detection
# =====================================================


class TestDetectGridType:
    """Tests for the detect_grid_type auto-detection function."""

    def test_eg4_offgrid_returns_split_phase(self):
        """EG4_OFFGRID family always returns split_phase."""
        device = _make_discovered_device(family="EG4_OFFGRID")
        assert detect_grid_type(device) == "split_phase"

    def test_eg4_hybrid_returns_split_phase(self):
        """EG4_HYBRID family always returns split_phase."""
        device = _make_discovered_device(family="EG4_HYBRID")
        assert detect_grid_type(device) == "split_phase"

    def test_three_phase_parallel_config(self):
        """parallel_master_slave=3 returns three_phase regardless of family."""
        device = _make_discovered_device(
            family="LXP", device_type_code=44, parallel_master_slave=3
        )
        assert detect_grid_type(device) == "three_phase"

    def test_lxp_eu_returns_three_phase(self):
        """LXP with device_type_code=12 (EU) returns three_phase."""
        device = _make_discovered_device(family="LXP", device_type_code=12)
        assert detect_grid_type(device) == "three_phase"

    def test_lxp_lb_returns_split_phase(self):
        """LXP with device_type_code=44 (LB/Americas) returns split_phase."""
        device = _make_discovered_device(family="LXP", device_type_code=44)
        assert detect_grid_type(device) == "split_phase"

    def test_unknown_family_returns_split_phase(self):
        """Unknown family defaults to split_phase."""
        device = _make_discovered_device(family="UNKNOWN")
        assert detect_grid_type(device) == "split_phase"
