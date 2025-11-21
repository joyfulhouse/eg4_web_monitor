"""Tests for EG4 Web Monitor reconfiguration flow."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock async_setup_entry to prevent actual integration setup during reconfiguration.

    Reconfigure tests trigger async_reload() which causes integration setup and creates
    aiohttp ClientSession instances. These spawn background threads that cause cleanup
    errors during test teardown. Mocking prevents thread creation while still allowing
    tests to validate reconfiguration logic.
    """
    with patch(
        "custom_components.eg4_web_monitor.async_setup_entry", return_value=True
    ):
        yield


@pytest.fixture
def mock_api():
    """Mock EG4InverterAPI."""
    with patch(
        "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
    ) as mock_api_class:
        mock_instance = AsyncMock()
        mock_instance.login = AsyncMock()
        mock_instance.get_plants = AsyncMock(
            return_value=[
                {"plantId": "plant1", "name": "Station 1"},
                {"plantId": "plant2", "name": "Station 2"},
            ]
        )
        mock_instance.close = AsyncMock()
        mock_api_class.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Web Monitor - Station 1",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "plant1",
            CONF_PLANT_NAME: "Station 1",
        },
        source="user",
        entry_id="test_entry_id",
        unique_id="test_user_plant1",
    )


async def test_reconfigure_flow_init(hass, mock_api, mock_config_entry):
    """Test reconfigure flow initialization."""
    # Add the config entry to hass
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert CONF_USERNAME in result["data_schema"].schema
    assert CONF_PASSWORD in result["data_schema"].schema


async def test_reconfigure_same_account(hass, mock_api, mock_config_entry):
    """Test reconfiguring with same account (password change only)."""
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Submit with same username, new password
    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload") as mock_reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: "test_user",  # Same username
                CONF_PASSWORD: "new_password",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_update.called
    assert mock_reload.called


async def test_reconfigure_different_account(hass, mock_api, mock_config_entry):
    """Test reconfiguring with different account (requires plant selection)."""
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with different username
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "different_user",  # Different username
            CONF_PASSWORD: "new_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show plant selection since account changed
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_plant"
    assert CONF_PLANT_ID in result["data_schema"].schema


async def test_reconfigure_plant_selection(hass, mock_api, mock_config_entry):
    """Test plant selection during reconfiguration."""
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with different username to trigger plant selection
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "different_user",
            CONF_PASSWORD: "new_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Now select a plant
    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload") as mock_reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_PLANT_ID: "plant2",  # Select different plant
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_update.called
    assert mock_reload.called


async def test_reconfigure_single_plant_account(hass, mock_api, mock_config_entry):
    """Test reconfiguring to account with only one plant (auto-select)."""
    # Mock API to return only one plant
    mock_api.get_plants = AsyncMock(
        return_value=[{"plantId": "single_plant", "name": "Only Station"}]
    )

    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with different username
    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload") as mock_reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: "different_user",
                CONF_PASSWORD: "new_password",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
            },
        )

    # Should auto-select single plant and complete
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_update.called
    assert mock_reload.called


async def test_reconfigure_invalid_auth(hass, mock_api, mock_config_entry):
    """Test reconfigure with invalid credentials."""
    from pylxpweb.exceptions import (
        LuxpowerAuthError as EG4AuthError,
    )

    mock_api.login.side_effect = EG4AuthError("Invalid credentials")
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with invalid credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "wrong_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_reconfigure_connection_error(hass, mock_api, mock_config_entry):
    """Test reconfigure with connection error."""
    from pylxpweb.exceptions import (
        LuxpowerConnectionError as EG4ConnectionError,
    )

    mock_api.login.side_effect = EG4ConnectionError("Cannot connect")
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


# Removed test_reconfigure_invalid_plant - voluptuous schema validation with vol.In
# prevents invalid plant_id from being submitted, so this edge case is not testable
# and the validation code is effectively dead code (vol.In catches it first)


async def test_reconfigure_to_already_configured_account(hass, mock_api):
    """Test reconfiguring to an account/plant combination that's already configured."""
    # Create two config entries - BOTH with same username to test conflict
    entry1 = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Web Monitor - Station 1",
        data={
            CONF_USERNAME: "shared_user",  # Same username
            CONF_PASSWORD: "pass1",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "plant1",
            CONF_PLANT_NAME: "Station 1",
        },
        source="user",
        entry_id="entry1",
        unique_id="shared_user_plant1",
    )
    entry1.add_to_hass(hass)

    entry2 = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Web Monitor - Station 2",
        data={
            CONF_USERNAME: "different_user",  # Different username initially
            CONF_PASSWORD: "pass2",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "plant2",
            CONF_PLANT_NAME: "Station 2",
        },
        source="user",
        entry_id="entry2",
        unique_id="different_user_plant2",
    )
    entry2.add_to_hass(hass)

    # Mock API to return plant1 when reconfiguring
    mock_api.get_plants = AsyncMock(
        return_value=[
            {"plantId": "plant1", "name": "Station 1"},
            {"plantId": "plant2", "name": "Station 2"},
        ]
    )

    # Try to reconfigure entry2 to use shared_user + plant1
    # This should conflict with entry1 (shared_user_plant1)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry2.entry_id,
        },
    )

    # Submit with same username but select plant1 (which is already configured)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "shared_user",
            CONF_PASSWORD: "new_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show plant selection
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_plant"

    # Now select plant1 (which conflicts with entry1)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_PLANT_ID: "plant1",
        },
    )

    # Should abort with already_configured
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_current_plant_no_longer_exists(
    hass, mock_api, mock_config_entry
):
    """Test reconfiguring when current plant no longer exists in the account."""
    mock_config_entry.add_to_hass(hass)

    # Mock API to return plants that don't include the current plant
    mock_api.get_plants = AsyncMock(
        return_value=[
            {"plantId": "plant3", "name": "New Station 3"},
            {"plantId": "plant4", "name": "New Station 4"},
        ]
    )

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with same username (password change)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "test_user",  # Same username
            CONF_PASSWORD: "new_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should still complete successfully, keeping the old plant_id
    # The system should handle the case where the plant might not exist anymore
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_timeout_handling(hass, mock_api, mock_config_entry):
    """Test reconfigure with timeout error."""
    mock_api.login.side_effect = asyncio.TimeoutError("Connection timed out")
    mock_config_entry.add_to_hass(hass)

    # Start reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )

    # Submit with credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
        },
    )

    # Should show form with error
    assert result["type"] == FlowResultType.FORM
    # The error will be "unknown" since we handle generic exceptions
    assert "base" in result["errors"]
