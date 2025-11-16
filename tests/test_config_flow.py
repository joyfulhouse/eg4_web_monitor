"""Test config flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.eg4_inverter_api.exceptions import (
    EG4APIError,
    EG4AuthError,
    EG4ConnectionError,
)
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


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
    """Create a mock EG4InverterAPI."""
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(return_value=True)
        api_instance.get_plants = AsyncMock(
            return_value=[
                {"plantId": "123", "name": "Test Plant 1"},
                {"plantId": "456", "name": "Test Plant 2"},
            ]
        )
        api_instance.close = AsyncMock()
        yield api_instance


@pytest.fixture
def mock_api_single_plant():
    """Create a mock EG4InverterAPI with single plant."""
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(return_value=True)
        api_instance.get_plants = AsyncMock(
            return_value=[
                {"plantId": "123", "name": "Test Plant"},
            ]
        )
        api_instance.close = AsyncMock()
        yield api_instance


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
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(side_effect=EG4AuthError("Invalid credentials"))
        api_instance.get_plants = AsyncMock(return_value=[])
        api_instance.close = AsyncMock()

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
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(side_effect=EG4ConnectionError("Cannot connect"))
        api_instance.get_plants = AsyncMock(return_value=[])
        api_instance.close = AsyncMock()

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
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(side_effect=EG4APIError("API Error"))
        api_instance.get_plants = AsyncMock(return_value=[])
        api_instance.close = AsyncMock()

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
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api:
        api_instance = mock_api.return_value
        api_instance.login = AsyncMock(side_effect=Exception("Unexpected"))
        api_instance.get_plants = AsyncMock(return_value=[])
        api_instance.close = AsyncMock()

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
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api_error:
        api_instance = mock_api_error.return_value
        api_instance.login = AsyncMock(side_effect=EG4AuthError("Invalid credentials"))
        api_instance.get_plants = AsyncMock(return_value=[])
        api_instance.close = AsyncMock()

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

    # Second attempt - success
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api_success:
        api_instance = mock_api_success.return_value
        api_instance.login = AsyncMock(return_value=True)
        api_instance.get_plants = AsyncMock(
            return_value=[{"plantId": "123", "name": "Test Plant"}]
        )
        api_instance.close = AsyncMock()

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


# Reconfigure Flow Tests (Gold Tier Requirement)


async def test_reconfigure_flow_success(hass: HomeAssistant, mock_api_single_plant):
    """Test successful credential reconfiguration."""
    # Create existing config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "old@example.com",
            CONF_PASSWORD: "oldpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        unique_id="old@example.com_12345",
    )
    entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Submit new credentials
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_client:
        mock_client.return_value.authenticate = AsyncMock(return_value=True)
        mock_client.return_value.get_plants_list = AsyncMock(
            return_value=[
                {
                    "plantId": "12345",
                    "plantName": "Test Plant",
                }
            ]
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "new@example.com",
                CONF_PASSWORD: "newpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_USERNAME] == "new@example.com"
    assert entry.data[CONF_PASSWORD] == "newpassword"


async def test_reconfigure_flow_auth_failure(hass: HomeAssistant):
    """Test reconfigure flow with authentication failure."""
    # Create existing config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "old@example.com",
            CONF_PASSWORD: "oldpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        unique_id="old@example.com_12345",
    )
    entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    # Submit invalid credentials
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_client:
        mock_client.return_value.authenticate = AsyncMock(
            side_effect=EG4AuthError("Invalid credentials")
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "new@example.com",
                CONF_PASSWORD: "wrongpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_plant_flow_success(hass: HomeAssistant):
    """Test successful plant reconfiguration."""
    # Create existing config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Old Plant",
        },
        unique_id="test@example.com_12345",
    )
    entry.add_to_hass(hass)

    # Start reconfigure_plant flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": "reconfigure_plant",
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_plant"

    # Submit new plant selection
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_client:
        mock_client.return_value.authenticate = AsyncMock(return_value=True)
        mock_client.return_value.get_plants_list = AsyncMock(
            return_value=[
                {"plantId": "12345", "plantName": "Old Plant"},
                {"plantId": "67890", "plantName": "New Plant"},
            ]
        )
        mock_client.return_value.get_parallel_group_details = AsyncMock(
            return_value={"success": True, "data": []}
        )
        mock_client.return_value.get_inverter_overview = AsyncMock(
            return_value={"success": True, "data": []}
        )

        # First configure to get plant list
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )

        # Then select new plant
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_PLANT_ID: "67890",
            },
        )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PLANT_ID] == "67890"
    assert entry.data[CONF_PLANT_NAME] == "New Plant"


async def test_reconfigure_plant_flow_connection_error(hass: HomeAssistant):
    """Test reconfigure plant flow with connection error."""
    # Create existing config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        unique_id="test@example.com_12345",
    )
    entry.add_to_hass(hass)

    # Start reconfigure_plant flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": "reconfigure_plant",
            "entry_id": entry.entry_id,
        },
    )

    # Simulate connection error
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_client:
        mock_client.return_value.authenticate = AsyncMock(
            side_effect=EG4ConnectionError("Connection failed")
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
