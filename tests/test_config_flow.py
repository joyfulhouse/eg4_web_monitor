"""Test config flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.config_flow import _timezone_observes_dst
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
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
    """Tests for the _timezone_observes_dst helper function."""

    def test_dst_timezone_returns_true(self):
        """Test that timezones with DST return True."""
        # US timezones that observe DST
        assert _timezone_observes_dst("America/New_York") is True
        assert _timezone_observes_dst("America/Los_Angeles") is True
        assert _timezone_observes_dst("America/Chicago") is True
        assert _timezone_observes_dst("America/Denver") is True

    def test_european_dst_timezone_returns_true(self):
        """Test that European timezones with DST return True."""
        assert _timezone_observes_dst("Europe/London") is True
        assert _timezone_observes_dst("Europe/Paris") is True
        assert _timezone_observes_dst("Europe/Berlin") is True

    def test_southern_hemisphere_dst_timezone_returns_true(self):
        """Test that Southern Hemisphere timezones with DST return True."""
        # Australia (most states observe DST)
        assert _timezone_observes_dst("Australia/Sydney") is True
        assert _timezone_observes_dst("Australia/Melbourne") is True
        # New Zealand
        assert _timezone_observes_dst("Pacific/Auckland") is True
        # South America
        assert _timezone_observes_dst("America/Santiago") is True  # Chile
        # Note: Brazil (America/Sao_Paulo) abolished DST in 2019

    def test_countries_that_abolished_dst_return_false(self):
        """Test that countries that recently abolished DST return False."""
        # Brazil abolished DST in 2019
        assert _timezone_observes_dst("America/Sao_Paulo") is False
        # Russia abolished DST in 2011
        assert _timezone_observes_dst("Europe/Moscow") is False
        # Turkey abolished DST in 2016
        assert _timezone_observes_dst("Europe/Istanbul") is False

    def test_non_dst_timezone_returns_false(self):
        """Test that timezones without DST return False."""
        # UTC never observes DST
        assert _timezone_observes_dst("UTC") is False
        # Arizona doesn't observe DST (except Navajo Nation)
        assert _timezone_observes_dst("America/Phoenix") is False
        # Most Asian timezones don't observe DST
        assert _timezone_observes_dst("Asia/Tokyo") is False
        assert _timezone_observes_dst("Asia/Shanghai") is False
        assert _timezone_observes_dst("Asia/Singapore") is False

    def test_none_timezone_returns_false(self):
        """Test that None timezone returns False."""
        assert _timezone_observes_dst(None) is False

    def test_empty_timezone_returns_false(self):
        """Test that empty string timezone returns False."""
        assert _timezone_observes_dst("") is False

    def test_invalid_timezone_returns_false(self):
        """Test that invalid timezone names return False."""
        assert _timezone_observes_dst("Invalid/Timezone") is False
        assert _timezone_observes_dst("Not_A_Timezone") is False


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


@pytest.fixture
def mock_api():
    """Create a mock for LuxpowerClient and Station.load_all."""
    from tests.conftest import create_mock_station

    # Create mock Station objects with all required fields
    mock_station1 = create_mock_station("123", "Test Plant 1")
    mock_station2 = create_mock_station("456", "Test Plant 2")

    # Mock the LuxpowerClient class itself to prevent actual connections
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station1, mock_station2]),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        yield None


@pytest.fixture
def mock_api_single_plant():
    """Create a mock for LuxpowerClient and Station.load_all with single plant."""
    from tests.conftest import create_mock_station

    # Create mock Station object with all required fields
    mock_station = create_mock_station("123", "Test Plant")

    # Mock the LuxpowerClient class itself to prevent actual connections
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station]),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        yield None


async def test_user_flow_success_multiple_plants(hass: HomeAssistant, mock_api):
    """Test successful user flow with multiple plants."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select HTTP connection type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: HTTP credentials
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "http_credentials"
    assert result["errors"] == {}

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

    # Should proceed to plant selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "plant"

    # Select plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "123"},
    )

    # Should create entry
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "EG4 Electronics Web Monitor - Test Plant 1"
    assert result["data"] == {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "testpassword",
        CONF_BASE_URL: DEFAULT_BASE_URL,
        CONF_VERIFY_SSL: True,
        CONF_DST_SYNC: True,
        CONF_LIBRARY_DEBUG: False,
        CONF_PLANT_ID: "123",
        CONF_PLANT_NAME: "Test Plant 1",
    }

    # Ensure proper cleanup before teardown
    await hass.async_block_till_done()


async def test_user_flow_success_single_plant(
    hass: HomeAssistant, mock_api_single_plant
):
    """Test successful user flow with single plant (auto-select)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: HTTP credentials
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "http_credentials"

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

    # Should create entry immediately (skip plant selection)
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "EG4 Electronics Web Monitor - Test Plant"
    assert result["data"][CONF_PLANT_ID] == "123"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant"
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TYPE_HTTP


async def test_user_flow_invalid_auth(hass: HomeAssistant):
    """Test flow with invalid authentication."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4AuthError("Invalid credentials")),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Step 1: Connection type selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        )

        # Step 2: Submit invalid credentials
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
        assert result["step_id"] == "http_credentials"
        assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant):
    """Test flow with connection error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4ConnectionError("Cannot connect")),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Step 1: Connection type selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        )

        # Step 2: Submit credentials
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
        assert result["step_id"] == "http_credentials"
        assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_api_error(hass: HomeAssistant):
    """Test flow with API error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4APIError("API Error")),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Step 1: Connection type selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        )

        # Step 2: Submit credentials
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
        assert result["step_id"] == "http_credentials"
        assert result["errors"] == {"base": "unknown"}


async def test_user_flow_unknown_exception(hass: HomeAssistant):
    """Test flow with unexpected exception."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=Exception("Unexpected")),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Step 1: Connection type selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        )

        # Step 2: Submit credentials
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
        assert result["step_id"] == "http_credentials"
        assert result["errors"] == {"base": "unknown"}


async def test_user_flow_error_recovery(hass: HomeAssistant, mock_api_single_plant):
    """Test user can recover from errors and complete flow."""
    # First attempt - invalid auth
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4AuthError("Invalid credentials")),
        ),
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Step 1: Connection type selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        )

        # Step 2: Submit invalid credentials
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

    # Should create entry after recovery
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "EG4 Electronics Web Monitor - Test Plant"


async def test_user_flow_already_configured(hass: HomeAssistant, mock_api):
    """Test flow aborts if already configured."""
    # Create existing entry - unique_id format is {username}_{plant_id}
    MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Electronics Web Monitor - Test Plant 1",
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
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",  # Format: {username}_{plant_id}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: Try to configure with same username - should proceed to plant selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show plant selection (username check on line 67 only sets unique_id temporarily)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "plant"

    # Select the same plant that's already configured
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "123"},
    )

    # Now should abort due to duplicate {username}_{plant_id}
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_plant_selection_flow(hass: HomeAssistant, mock_api):
    """Test plant selection step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: Submit credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show plant selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "plant"

    # Verify plant options are available
    schema = result["data_schema"]
    assert CONF_PLANT_ID in schema.schema

    # Select second plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "456"},
    )

    # Should create entry with selected plant
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "EG4 Electronics Web Monitor - Test Plant 2"
    assert result["data"][CONF_PLANT_ID] == "456"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant 2"


async def test_flow_with_custom_base_url(hass: HomeAssistant, mock_api_single_plant):
    """Test flow with custom base URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: Submit credentials with custom URL
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: "https://custom.eg4.com",
            CONF_VERIFY_SSL: False,
        },
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

    # Initialize flow - should show connection type selection
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: Submit credentials without explicitly setting DST sync
    # (it will use the default from the schema)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            # DST_SYNC not explicitly provided - will use schema default
        },
    )

    # Entry should be created with DST sync = True (default for DST timezone)
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DST_SYNC] is True


async def test_dst_sync_default_false_for_non_dst_timezone(
    hass_with_non_dst_timezone: HomeAssistant, mock_api_single_plant
):
    """Test DST sync defaults to False when HA timezone does NOT observe DST."""
    hass = hass_with_non_dst_timezone

    # Initialize flow - should show connection type selection
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: Submit credentials without explicitly setting DST sync
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            # DST_SYNC not explicitly provided - will use schema default
        },
    )

    # Entry should be created with DST sync = False (default for non-DST timezone)
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

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
    )

    # Step 2: User explicitly enables DST sync despite timezone not observing DST
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,  # Explicitly enabled
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DST_SYNC] is True


# ====================
# Local-Only Multi-Device Mode Tests
# ====================


async def test_local_setup_step_shows_form(hass: HomeAssistant):
    """Test that local setup step shows the station name form."""
    from custom_components.eg4_web_monitor.const import CONNECTION_TYPE_LOCAL

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select local multi-device connection type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
    )

    # Should show local_setup form
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "local_setup"


async def test_local_add_device_step(hass: HomeAssistant):
    """Test that local_add_device step shows device type selection."""
    from custom_components.eg4_web_monitor.const import (
        CONF_STATION_NAME,
        CONNECTION_TYPE_LOCAL,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
    )

    # Step 2: Station name
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STATION_NAME: "Test Local Station"},
    )

    # Should show add device form
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "local_add_device"


async def test_local_modbus_device_connection(hass: HomeAssistant):
    """Test adding a Modbus device in local-only mode."""
    from custom_components.eg4_web_monitor.const import (
        CONF_INVERTER_FAMILY,
        CONF_INVERTER_SERIAL,
        CONF_MODBUS_HOST,
        CONF_MODBUS_PORT,
        CONF_MODBUS_UNIT_ID,
        CONF_STATION_NAME,
        CONNECTION_TYPE_LOCAL,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
    )

    # Step 2: Station name
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STATION_NAME: "Test Local Station"},
    )

    # Step 3: Select device type (modbus)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_type": "modbus"},
    )

    # Should show modbus device form
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "local_modbus_device"

    # Mock Modbus transport and submit device
    mock_runtime = AsyncMock()
    mock_runtime.pv_total_power = 5000
    mock_runtime.battery_soc = 80

    with patch("pylxpweb.transports.create_modbus_transport") as mock_transport_factory:
        mock_transport = AsyncMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.read_serial_number = AsyncMock(return_value="CE12345678")
        mock_transport.read_runtime = AsyncMock(return_value=mock_runtime)
        mock_transport_factory.return_value = mock_transport

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MODBUS_HOST: "192.168.1.100",
                CONF_MODBUS_PORT: 502,
                CONF_MODBUS_UNIT_ID: 1,
                CONF_INVERTER_SERIAL: "",  # Auto-detect
                CONF_INVERTER_FAMILY: "PV_SERIES",
            },
        )

        # Should show device added form
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "local_device_added"


async def test_local_complete_flow_single_device(hass: HomeAssistant):
    """Test complete local-only flow with single device."""
    from custom_components.eg4_web_monitor.const import (
        CONF_INVERTER_FAMILY,
        CONF_INVERTER_SERIAL,
        CONF_LOCAL_TRANSPORTS,
        CONF_MODBUS_HOST,
        CONF_MODBUS_PORT,
        CONF_MODBUS_UNIT_ID,
        CONF_STATION_NAME,
        CONNECTION_TYPE_LOCAL,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Step 1: Connection type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
    )

    # Step 2: Station name
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STATION_NAME: "Home Solar"},
    )

    # Step 3: Device type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_type": "modbus"},
    )

    # Step 4: Modbus device config
    mock_runtime = AsyncMock()
    mock_runtime.pv_total_power = 5000
    mock_runtime.battery_soc = 80

    with patch("pylxpweb.transports.create_modbus_transport") as mock_transport_factory:
        mock_transport = AsyncMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.read_serial_number = AsyncMock(return_value="CE12345678")
        mock_transport.read_runtime = AsyncMock(return_value=mock_runtime)
        mock_transport_factory.return_value = mock_transport

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MODBUS_HOST: "192.168.1.100",
                CONF_MODBUS_PORT: 502,
                CONF_MODBUS_UNIT_ID: 1,
                CONF_INVERTER_SERIAL: "",
                CONF_INVERTER_FAMILY: "PV_SERIES",
            },
        )

    # Step 5: Don't add another device (finish)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"add_another": False},
    )

    # Should create entry
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert "Home Solar" in result["title"]
    assert "1 device" in result["title"]
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TYPE_LOCAL
    assert result["data"][CONF_STATION_NAME] == "Home Solar"
    assert len(result["data"][CONF_LOCAL_TRANSPORTS]) == 1
    assert result["data"][CONF_LOCAL_TRANSPORTS][0]["serial"] == "CE12345678"
    assert result["data"][CONF_LOCAL_TRANSPORTS][0]["transport_type"] == "modbus_tcp"


async def test_local_duplicate_serial_error(hass: HomeAssistant):
    """Test that duplicate serials show an error."""
    from custom_components.eg4_web_monitor.const import (
        CONF_INVERTER_FAMILY,
        CONF_INVERTER_SERIAL,
        CONF_MODBUS_HOST,
        CONF_MODBUS_PORT,
        CONF_MODBUS_UNIT_ID,
        CONF_STATION_NAME,
        CONNECTION_TYPE_LOCAL,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Setup through to first device
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_STATION_NAME: "Test Station"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_type": "modbus"},
    )

    # Add first device
    mock_runtime = AsyncMock()
    mock_runtime.pv_total_power = 5000
    mock_runtime.battery_soc = 80

    with patch("pylxpweb.transports.create_modbus_transport") as mock_transport_factory:
        mock_transport = AsyncMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.read_serial_number = AsyncMock(return_value="CE12345678")
        mock_transport.read_runtime = AsyncMock(return_value=mock_runtime)
        mock_transport_factory.return_value = mock_transport

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MODBUS_HOST: "192.168.1.100",
                CONF_MODBUS_PORT: 502,
                CONF_MODBUS_UNIT_ID: 1,
                CONF_INVERTER_SERIAL: "",
                CONF_INVERTER_FAMILY: "PV_SERIES",
            },
        )

    # Choose to add another device
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"add_another": True},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device_type": "modbus"},
    )

    # Try to add device with same serial
    with patch("pylxpweb.transports.create_modbus_transport") as mock_transport_factory:
        mock_transport = AsyncMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.read_serial_number = AsyncMock(
            return_value="CE12345678"
        )  # Same serial
        mock_transport.read_runtime = AsyncMock(return_value=mock_runtime)
        mock_transport_factory.return_value = mock_transport

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MODBUS_HOST: "192.168.1.101",  # Different host
                CONF_MODBUS_PORT: 502,
                CONF_MODBUS_UNIT_ID: 1,
                CONF_INVERTER_SERIAL: "",
                CONF_INVERTER_FAMILY: "PV_SERIES",
            },
        )

    # Should show error for duplicate serial
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "local_modbus_device"
    assert result["errors"]["base"] == "duplicate_serial"


# ====================
# Options Flow Tests for Local Mode
# ====================


async def test_options_flow_local_mode_shows_local_options(hass: HomeAssistant):
    """Test that local mode shows local options menu."""
    from custom_components.eg4_web_monitor.const import (
        CONF_LOCAL_TRANSPORTS,
        CONF_STATION_NAME,
        CONNECTION_TYPE_LOCAL,
    )

    # Create a local mode config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_STATION_NAME: "Test Local Station",
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "CE12345678",
                    "transport_type": "modbus_tcp",
                    "host": "192.168.1.100",
                    "port": 502,
                    "unit_id": 1,
                    "inverter_family": "PV_SERIES",
                }
            ],
        },
        unique_id="local_CE12345678",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Should show local options menu
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "local_options"


async def test_options_flow_http_mode_shows_init(hass: HomeAssistant):
    """Test that HTTP mode shows standard init options."""
    # Create an HTTP mode config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_PLANT_ID: "123",
            CONF_PLANT_NAME: "Test Plant",
        },
        unique_id="test@example.com_123",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Should show standard init form for HTTP mode
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
