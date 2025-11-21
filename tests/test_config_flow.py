"""Test config flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from pylxpweb.exceptions import (
    LuxpowerAPIError as EG4APIError,
    LuxpowerAuthError as EG4AuthError,
    LuxpowerConnectionError as EG4ConnectionError,
)


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
    from unittest.mock import MagicMock

    # Create mock Station objects
    mock_station1 = MagicMock()
    mock_station1.id = "123"
    mock_station1.name = "Test Plant 1"

    mock_station2 = MagicMock()
    mock_station2.id = "456"
    mock_station2.name = "Test Plant 2"

    # Mock the LuxpowerClient class itself to prevent actual connections
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station1, mock_station2])
        )
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
    from unittest.mock import MagicMock

    # Create mock Station object
    mock_station = MagicMock()
    mock_station.id = "123"
    mock_station.name = "Test Plant"

    # Mock the LuxpowerClient class itself to prevent actual connections
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station])
        )
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

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"
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
    assert result["title"] == "EG4 Web Monitor - Test Plant 1"
    assert result["data"] == {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "testpassword",
        CONF_BASE_URL: DEFAULT_BASE_URL,
        CONF_VERIFY_SSL: True,
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

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

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
    assert result["title"] == "EG4 Web Monitor - Test Plant"
    assert result["data"][CONF_PLANT_ID] == "123"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant"


async def test_user_flow_invalid_auth(hass: HomeAssistant):
    """Test flow with invalid authentication."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4AuthError("Invalid credentials"))
        )
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

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
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant):
    """Test flow with connection error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4ConnectionError("Cannot connect"))
        )
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
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

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_api_error(hass: HomeAssistant):
    """Test flow with API error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4APIError("API Error"))
        )
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
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

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "unknown"}


async def test_user_flow_unknown_exception(hass: HomeAssistant):
    """Test flow with unexpected exception."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=Exception("Unexpected"))
        )
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
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

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
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
            new=AsyncMock(side_effect=EG4AuthError("Invalid credentials"))
        )
    ):
        # Make LuxpowerClient work as a context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

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
    assert result["title"] == "EG4 Web Monitor - Test Plant"


async def test_user_flow_already_configured(hass: HomeAssistant, mock_api):
    """Test flow aborts if already configured."""
    # Create existing entry - unique_id format is {username}_{plant_id}
    MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant 1",
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "123",
            CONF_PLANT_NAME: "Test Plant 1",
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",  # Format: {username}_{plant_id}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Try to configure with same username - should proceed to plant selection
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
    assert result["title"] == "EG4 Web Monitor - Test Plant 2"
    assert result["data"][CONF_PLANT_ID] == "456"
    assert result["data"][CONF_PLANT_NAME] == "Test Plant 2"


async def test_flow_with_custom_base_url(hass: HomeAssistant, mock_api_single_plant):
    """Test flow with custom base URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

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
