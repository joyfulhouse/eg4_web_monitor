"""Tests for __init__.py (setup and teardown) in EG4 Web Monitor integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ServiceValidationError
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.entry_id = "test_entry_id"
    coordinator.async_request_refresh = AsyncMock()
    coordinator.api = MagicMock()
    coordinator.api.close = AsyncMock()
    return coordinator


@pytest.fixture
def mock_config_entry(mock_coordinator):
    """Create a mock config entry."""
    entry = MockConfigEntry(
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
    entry.runtime_data = mock_coordinator
    return entry


class TestAsyncSetup:
    """Test async_setup function."""

    async def test_setup_registers_service(self, hass: HomeAssistant):
        """Test that setup registers the refresh_data service."""
        result = await async_setup(hass, {})

        assert result is True
        assert hass.services.has_service(DOMAIN, "refresh_data")

    async def test_refresh_service_with_valid_entry_id(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test refresh service with valid entry_id."""
        # Setup integration
        await async_setup(hass, {})

        # Add config entry and set it up properly
        mock_config_entry.add_to_hass(hass)

        # Actually load the entry using async_setup_entry
        with patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=mock_coordinator,
        ):
            await async_setup_entry(hass, mock_config_entry)

        # Call service
        await hass.services.async_call(
            DOMAIN,
            "refresh_data",
            {"entry_id": "test_entry_id"},
            blocking=True,
        )

        # Verify coordinator was refreshed
        mock_coordinator.async_request_refresh.assert_called_once()

    async def test_refresh_service_with_invalid_entry_id(self, hass: HomeAssistant):
        """Test refresh service raises error for invalid entry_id."""
        await async_setup(hass, {})

        with pytest.raises(ServiceValidationError, match="not found"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": "non_existent_id"},
                blocking=True,
            )

    async def test_refresh_service_with_unloaded_entry(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test refresh service raises error for unloaded entry."""
        await async_setup(hass, {})

        # Add config entry but don't load it
        mock_config_entry.add_to_hass(hass)
        # State defaults to NOT_LOADED, no need to set it

        with pytest.raises(ServiceValidationError, match="not loaded"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": "test_entry_id"},
                blocking=True,
            )

    async def test_refresh_service_without_entry_id_refreshes_all(
        self, hass: HomeAssistant
    ):
        """Test refresh service without entry_id refreshes all coordinators."""
        await async_setup(hass, {})

        # Create multiple mock coordinators
        mock_coord1 = MagicMock()
        mock_coord1.entry = MagicMock()
        mock_coord1.entry.entry_id = "entry_1"
        mock_coord1.async_request_refresh = AsyncMock()

        mock_coord2 = MagicMock()
        mock_coord2.entry = MagicMock()
        mock_coord2.entry.entry_id = "entry_2"
        mock_coord2.async_request_refresh = AsyncMock()

        # Create config entries
        entry1 = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "user1", CONF_PASSWORD: "pass1", CONF_PLANT_ID: "1"},
            entry_id="entry_1",
        )
        entry1.add_to_hass(hass)

        entry2 = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "user2", CONF_PASSWORD: "pass2", CONF_PLANT_ID: "2"},
            entry_id="entry_2",
        )
        entry2.add_to_hass(hass)

        # Actually load both entries using async_setup_entry
        with patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            side_effect=[mock_coord1, mock_coord2],
        ):
            await async_setup_entry(hass, entry1)
            await async_setup_entry(hass, entry2)

        # Call service without entry_id
        await hass.services.async_call(
            DOMAIN,
            "refresh_data",
            {},
            blocking=True,
        )

        # Verify both coordinators were refreshed
        mock_coord1.async_request_refresh.assert_called_once()
        mock_coord2.async_request_refresh.assert_called_once()

    async def test_refresh_service_with_no_coordinators(self, hass: HomeAssistant):
        """Test refresh service raises error when no coordinators exist."""
        await async_setup(hass, {})

        with pytest.raises(ServiceValidationError, match="No EG4 coordinators"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {},
                blocking=True,
            )


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_success(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test successful setup of config entry."""
        # Mock coordinator
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        # Mock platform setup
        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward:
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            mock_coordinator.async_config_entry_first_refresh.assert_called_once()
            assert mock_config_entry.runtime_data == mock_coordinator
            mock_forward.assert_called_once()

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_creates_coordinator_with_correct_params(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test that coordinator is created with correct parameters."""
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ):
            await async_setup_entry(hass, mock_config_entry)

            # Verify coordinator was created with correct params
            mock_coordinator_class.assert_called_once_with(hass, mock_config_entry)

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_forwards_to_all_platforms(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test that entry setup is forwarded to all platforms."""
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward:
            await async_setup_entry(hass, mock_config_entry)

            # Verify all platforms were forwarded
            call_args = mock_forward.call_args
            platforms = call_args[0][1]
            assert "sensor" in [p.value for p in platforms]
            assert "number" in [p.value for p in platforms]
            assert "switch" in [p.value for p in platforms]
            assert "button" in [p.value for p in platforms]
            assert "select" in [p.value for p in platforms]


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    async def test_unload_entry_success(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test successful unload of config entry."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ) as mock_unload:
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is True
            mock_unload.assert_called_once()
            mock_coordinator.api.close.assert_called_once()

    async def test_unload_entry_failure(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test failed unload of config entry."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=False),
        ) as mock_unload:
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is False
            mock_unload.assert_called_once()
            # API should not be closed if unload failed
            mock_coordinator.api.close.assert_not_called()

    async def test_unload_entry_cleans_up_api(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test that API connection is closed on unload."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            await async_unload_entry(hass, mock_config_entry)

            # Verify API close was called
            mock_coordinator.api.close.assert_called_once()

    async def test_unload_entry_unloads_all_platforms(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test that all platforms are unloaded."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ) as mock_unload:
            await async_unload_entry(hass, mock_config_entry)

            # Verify all platforms were unloaded
            call_args = mock_unload.call_args
            platforms = call_args[0][1]
            assert "sensor" in [p.value for p in platforms]
            assert "number" in [p.value for p in platforms]
            assert "switch" in [p.value for p in platforms]
            assert "button" in [p.value for p in platforms]
            assert "select" in [p.value for p in platforms]
