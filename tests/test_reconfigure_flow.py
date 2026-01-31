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
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from pylxpweb.exceptions import LuxpowerAuthError as EG4AuthError

from tests.test_config_flow import _mock_luxpower_client


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
            CONF_LOCAL_TRANSPORTS: [],
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api_single_plant():
    """Create a mock for LuxpowerClient with a single plant."""
    from tests.conftest import create_mock_station

    with _mock_luxpower_client(stations=[create_mock_station("123", "Test Plant")]):
        yield None


@pytest.fixture
def mock_api_multiple_plants():
    """Create a mock for LuxpowerClient with multiple plants."""
    from tests.conftest import create_mock_station

    stations = [
        create_mock_station("123", "Test Plant 1"),
        create_mock_station("456", "Test Plant 2"),
    ]
    with _mock_luxpower_client(stations=stations):
        yield None


async def _init_reconfigure(hass: HomeAssistant, entry: MockConfigEntry):
    """Init reconfigure flow and navigate to the reconfigure menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    # Reconfigure entry point loads state and goes to reconfigure_menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "reconfigure_menu"
    return result


async def test_reconfigure_flow_update_credentials(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration updating cloud credentials."""
    result = await _init_reconfigure(hass, mock_config_entry)

    # Select cloud update from menu
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "reconfigure_cloud_update"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_cloud_update"

    # Submit new credentials
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

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_PASSWORD] == "newpassword"
    assert updated_entry.data[CONF_PLANT_ID] == "123"


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Test reconfiguration with invalid credentials shows error."""
    with _mock_luxpower_client(side_effect=EG4AuthError("Invalid credentials")):
        result = await _init_reconfigure(hass, mock_config_entry)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_cloud_update"},
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
        assert result["step_id"] == "reconfigure_cloud_update"
        assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_update_base_url(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration can update base URL."""
    result = await _init_reconfigure(hass, mock_config_entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "reconfigure_cloud_update"},
    )

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

    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_BASE_URL] == "https://custom.eg4.com"
    assert updated_entry.data[CONF_VERIFY_SSL] is False
    assert updated_entry.data[CONF_DST_SYNC] is False
