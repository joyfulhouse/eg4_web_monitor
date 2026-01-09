"""Test reconfigure flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    LuxpowerAuthError as EG4AuthError,
    LuxpowerConnectionError as EG4ConnectionError,
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock async_setup_entry and platform setups to prevent integration setup."""
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
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry for reconfiguration tests."""
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Electronics Web Monitor - Test Plant",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "123",
            CONF_PLANT_NAME: "Test Plant",
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api_single_plant():
    """Create a mock for LuxpowerClient and Station.load_all with single plant."""
    from tests.conftest import create_mock_station

    mock_station = create_mock_station("123", "Test Plant")

    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station]),
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        yield None


@pytest.fixture
def mock_api_multiple_plants():
    """Create a mock for LuxpowerClient with multiple plants."""
    from tests.conftest import create_mock_station

    mock_station1 = create_mock_station("123", "Test Plant 1")
    mock_station2 = create_mock_station("456", "Test Plant 2")

    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[mock_station1, mock_station2]),
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        yield None


async def test_reconfigure_flow_same_account(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration with same account keeps existing plant."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_http"

    # Reconfigure with same username but new password
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "newpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    # Should complete and reload entry
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify entry was updated
    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_PASSWORD] == "newpassword"
    assert updated_entry.data[CONF_PLANT_ID] == "123"  # Same plant


async def test_reconfigure_flow_different_account_single_plant(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration with different account and single plant."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Change to new account
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "newuser@example.com",
            CONF_PASSWORD: "newpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    # Should auto-select single plant and complete
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify entry was updated with new account
    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_USERNAME] == "newuser@example.com"


async def test_reconfigure_flow_different_account_multiple_plants(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_multiple_plants
):
    """Test reconfiguration with different account shows plant selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Change to new account with multiple plants
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "newuser@example.com",
            CONF_PASSWORD: "newpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    # Should show plant selection
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_plant"

    # Select a plant
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PLANT_ID: "456"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify entry was updated with new plant
    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_PLANT_ID] == "456"
    assert updated_entry.data[CONF_PLANT_NAME] == "Test Plant 2"


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Test reconfiguration with invalid credentials shows error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4AuthError("Invalid credentials")),
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "wrongpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure_http"
        assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Test reconfiguration with connection error shows error."""
    with (
        patch(
            "custom_components.eg4_web_monitor.config_flow.LuxpowerClient"
        ) as mock_client_class,
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=EG4ConnectionError("Cannot connect")),
        ),
    ):
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": mock_config_entry.entry_id,
            },
        )

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

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure_http"
        assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_update_base_url(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration can update base URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Update base URL
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: "https://custom.eg4.com",
            CONF_VERIFY_SSL: False,
            CONF_DST_SYNC: False,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify entry was updated
    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_BASE_URL] == "https://custom.eg4.com"
    assert updated_entry.data[CONF_VERIFY_SSL] is False
    assert updated_entry.data[CONF_DST_SYNC] is False


async def test_reconfigure_plant_selection_shows_current_plant(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_multiple_plants
):
    """Test plant selection during reconfigure shows current plant as default."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Change account to trigger plant selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "newuser@example.com",
            CONF_PASSWORD: "newpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    # Should show plant selection form
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_plant"

    # Verify schema includes plant selection
    schema = result["data_schema"]
    assert CONF_PLANT_ID in schema.schema
