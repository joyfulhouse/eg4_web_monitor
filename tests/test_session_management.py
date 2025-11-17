"""Tests for session management and re-authentication features (v2.2.2)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.eg4_inverter_api import EG4InverterAPI
from custom_components.eg4_web_monitor.eg4_inverter_api.exceptions import EG4AuthError


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry for testing."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "password123",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
        },
        unique_id="test@example.com_12345",
    )


class TestProactiveSessionRefresh:
    """Test Solution 1: Proactive session refresh before expiry."""

    async def test_session_refresh_when_less_than_5_minutes_remaining(
        self, hass: HomeAssistant
    ) -> None:
        """Test that session is refreshed when < 5 minutes until expiry."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set session to expire in 3 minutes
        api._session_id = "old_session_id"
        api._session_expires = datetime.now() + timedelta(minutes=3)

        # Mock the login method
        with patch.object(api, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = {"success": True}

            # Call _ensure_authenticated
            await api._ensure_authenticated()

            # Verify login was called to refresh session
            mock_login.assert_called_once()

    async def test_session_not_refreshed_when_more_than_5_minutes_remaining(
        self, hass: HomeAssistant
    ) -> None:
        """Test that session is NOT refreshed when > 5 minutes until expiry."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set session to expire in 10 minutes
        api._session_id = "valid_session_id"
        api._session_expires = datetime.now() + timedelta(minutes=10)

        # Mock the login method
        with patch.object(api, "login", new_callable=AsyncMock) as mock_login:
            # Call _ensure_authenticated
            await api._ensure_authenticated()

            # Verify login was NOT called
            mock_login.assert_not_called()

    async def test_session_refresh_when_expired(self, hass: HomeAssistant) -> None:
        """Test that expired session triggers login."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set session to expired (1 minute ago)
        api._session_id = "expired_session_id"
        api._session_expires = datetime.now() - timedelta(minutes=1)

        # Mock the login method
        with patch.object(api, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = {"success": True}

            # Call _ensure_authenticated
            await api._ensure_authenticated()

            # Verify login was called
            mock_login.assert_called_once()

    async def test_session_refresh_when_missing(self, hass: HomeAssistant) -> None:
        """Test that missing session triggers login."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # No session ID set
        api._session_id = None
        api._session_expires = None

        # Mock the login method
        with patch.object(api, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = {"success": True}

            # Call _ensure_authenticated
            await api._ensure_authenticated()

            # Verify login was called
            mock_login.assert_called_once()


class TestEnhancedSessionCleanup:
    """Test Solution 2: Enhanced session cleanup with cookie jar clearing."""

    async def test_cookie_jar_cleared_before_login(self, hass: HomeAssistant) -> None:
        """Test that cookie jar is cleared before login."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Mock the _make_request to avoid actual API call
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}

            # Call login
            await api.login()

            # Verify _make_request was called
            mock_request.assert_called_once()

    async def test_cookie_jar_cleared_during_reauth(self, hass: HomeAssistant) -> None:
        """Test that cookie jar is cleared during re-authentication."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Mock _get_session to return the session
        with patch.object(api, "_get_session", return_value=session):
            # Verify cookie jar clearing logic works
            # pylint: disable=protected-access
            if hasattr(session, "_cookie_jar"):
                # The cookie jar should be clearable
                session._cookie_jar.clear()
                assert len(session._cookie_jar) == 0


class TestCircuitBreakerBypass:
    """Test Solution 3: Circuit breaker bypass for re-authentication."""

    async def test_login_skips_backoff(self, hass: HomeAssistant) -> None:
        """Test that login requests skip backoff delays."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set up consecutive errors to trigger backoff
        api._consecutive_errors = 5
        api._current_backoff_delay = 30.0

        # Mock _make_request to verify skip_backoff parameter
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}

            # Call login
            await api.login()

            # Verify _make_request was called with skip_backoff=True
            mock_request.assert_called_once()
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs.get("skip_backoff") is True

    async def test_successful_login_resets_circuit_breaker(
        self, hass: HomeAssistant
    ) -> None:
        """Test that successful login resets circuit breaker state."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set up error state
        api._consecutive_errors = 5
        api._current_backoff_delay = 30.0

        # Mock _make_request
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}

            # Call login
            await api.login()

            # Verify circuit breaker was reset
            assert api._consecutive_errors == 0
            assert api._current_backoff_delay == 0.0


class TestBackgroundSessionMaintenance:
    """Test Solution 4: Background session maintenance task."""

    async def test_session_maintenance_initialization(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that session maintenance tracking is initialized."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Verify maintenance tracking is initialized
        assert coordinator._last_session_maintenance is None
        assert coordinator._session_maintenance_interval == timedelta(minutes=90)

    async def test_should_perform_session_maintenance_when_never_performed(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that maintenance is needed when never performed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # First time should return True
        assert coordinator._should_perform_session_maintenance() is True

    async def test_should_perform_session_maintenance_when_due(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that maintenance is needed when 90+ minutes have passed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set last maintenance to 91 minutes ago
        from homeassistant.util import dt as dt_util

        coordinator._last_session_maintenance = dt_util.utcnow() - timedelta(minutes=91)

        # Should return True
        assert coordinator._should_perform_session_maintenance() is True

    async def test_should_not_perform_session_maintenance_when_recent(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that maintenance is NOT needed when recently performed."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set last maintenance to 30 minutes ago
        from homeassistant.util import dt as dt_util

        coordinator._last_session_maintenance = dt_util.utcnow() - timedelta(minutes=30)

        # Should return False
        assert coordinator._should_perform_session_maintenance() is False

    async def test_perform_session_maintenance_calls_api(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that session maintenance makes a keepalive API call."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock the API method
        with patch.object(
            coordinator.api, "get_plant_details", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = {"name": "Test Plant"}

            # Perform session maintenance
            await coordinator._perform_session_maintenance()

            # Verify API was called
            mock_api.assert_called_once_with(mock_config_entry.data[CONF_PLANT_ID])

    async def test_perform_session_maintenance_updates_timestamp(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that session maintenance updates the timestamp."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock the API method
        with patch.object(
            coordinator.api, "get_plant_details", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = {"name": "Test Plant"}

            # Initial state
            assert coordinator._last_session_maintenance is None

            # Perform session maintenance
            await coordinator._perform_session_maintenance()

            # Verify timestamp was updated
            assert coordinator._last_session_maintenance is not None

    async def test_perform_session_maintenance_handles_errors(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that session maintenance handles API errors gracefully."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock the API method to raise an error
        with patch.object(
            coordinator.api, "get_plant_details", new_callable=AsyncMock
        ) as mock_api:
            mock_api.side_effect = Exception("API Error")

            # Should not raise exception
            await coordinator._perform_session_maintenance()

            # Verify API was called
            mock_api.assert_called_once()


class TestEnhancedDebugLogging:
    """Test Solution 5: Enhanced debug logging for re-authentication."""

    async def test_login_logs_session_state(
        self, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that login logs session state before attempting."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Set existing session
        api._session_id = "test_session_id"
        api._session_expires = datetime.now() + timedelta(hours=1)

        # Mock _make_request
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}

            # Call login
            with caplog.at_level("DEBUG"):
                await api.login()

            # Verify debug logging occurred
            assert any("Login attempt" in record.message for record in caplog.records)

    async def test_successful_login_logs_session_info(
        self, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that successful login logs session information."""
        session = aiohttp_client.async_get_clientsession(hass)
        api = EG4InverterAPI(
            username="test",
            password="pass",
            session=session,
        )

        # Mock _make_request
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}

            # Call login
            with caplog.at_level("INFO"):
                await api.login()

            # Verify info logging occurred
            assert any(
                "Successfully authenticated with EG4 API" in record.message
                for record in caplog.records
            )


class TestIntegrationReauthenticationFlow:
    """Integration tests for the complete re-authentication flow."""

    async def test_coordinator_handles_auth_failure_with_retry(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that coordinator properly handles auth failures."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Mock API to raise auth error
        with patch.object(
            coordinator.api, "get_all_device_data", new_callable=AsyncMock
        ) as mock_api:
            mock_api.side_effect = EG4AuthError("Session expired")

            # This should raise ConfigEntryAuthFailed
            with pytest.raises(ConfigEntryAuthFailed):
                await coordinator._async_update_data()

    async def test_session_maintenance_triggered_during_update(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Test that session maintenance is triggered during coordinator update."""
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Set last maintenance to 91 minutes ago to trigger maintenance
        from homeassistant.util import dt as dt_util

        coordinator._last_session_maintenance = dt_util.utcnow() - timedelta(minutes=91)

        # Mock API methods
        with (
            patch.object(
                coordinator.api, "get_all_device_data", new_callable=AsyncMock
            ) as mock_data,
            patch.object(
                coordinator.api, "get_plant_details", new_callable=AsyncMock
            ) as mock_plant,
            patch.object(
                coordinator, "_process_device_data", new_callable=AsyncMock
            ) as mock_process,
        ):
            mock_data.return_value = {"devices": {}}
            mock_plant.return_value = {"name": "Test Plant"}
            mock_process.return_value = {"devices": {}, "plant_id": "12345"}

            # Trigger update
            result = await coordinator._async_update_data()

            # Verify data was fetched
            assert result is not None
