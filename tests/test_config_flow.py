"""Test config flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.config_flow.helpers import timezone_observes_dst
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
    client_patch = patch("custom_components.eg4_web_monitor.config_flow.LuxpowerClient")
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
