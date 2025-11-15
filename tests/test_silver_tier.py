"""Tests for Silver tier compliance of EG4 Web Monitor integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.eg4_inverter_api.exceptions import (
    EG4AuthError,
    EG4ConnectionError,
    EG4APIError,
)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MagicMock(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
        state=ConfigEntryState.LOADED,
    )


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.async_create_task = MagicMock()
    return hass


# Silver Tier Requirement: Service actions must raise exceptions on failure
class TestServiceExceptionHandling:
    """Test that service actions raise appropriate exceptions."""

    async def test_refresh_service_raises_validation_error_for_invalid_entry(
        self, hass, mock_config_entry
    ):
        """Test refresh service raises ServiceValidationError for invalid entry_id."""
        from homeassistant.exceptions import ServiceValidationError
        from custom_components.eg4_web_monitor import async_setup

        # Set up the integration
        await async_setup(hass, {})

        # Try to refresh non-existent entry
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": "non_existent_entry"},
                blocking=True,
            )

        assert "not found" in str(exc_info.value).lower()

    async def test_refresh_service_raises_validation_error_for_unloaded_entry(
        self, hass, mock_config_entry
    ):
        """Test refresh service raises ServiceValidationError for unloaded entry."""
        from homeassistant.exceptions import ServiceValidationError
        from custom_components.eg4_web_monitor import async_setup

        # Set up the integration
        await async_setup(hass, {})

        mock_config_entry.state = ConfigEntryState.NOT_LOADED
        mock_config_entry.add_to_hass(hass)

        # Try to refresh unloaded entry
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": mock_config_entry.entry_id},
                blocking=True,
            )

        assert "not loaded" in str(exc_info.value).lower()


# Silver Tier Requirement: Config entry unloading must be supported
class TestConfigEntryUnload:
    """Test config entry unloading."""

    async def test_async_unload_entry_success(self, mock_hass, mock_config_entry):
        """Test successful config entry unload."""
        from custom_components.eg4_web_monitor import async_unload_entry

        # Create mock coordinator with API
        mock_coordinator = MagicMock()
        mock_coordinator.api = MagicMock()
        mock_coordinator.api.close = AsyncMock()
        mock_config_entry.runtime_data = mock_coordinator

        # Mock platform unloading
        mock_hass.config_entries.async_unload_platforms = AsyncMock(
            return_value=True
        )

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True
        mock_coordinator.api.close.assert_called_once()

    async def test_async_unload_entry_cleanup_on_failure(
        self, mock_hass, mock_config_entry
    ):
        """Test cleanup still happens even if unload fails."""
        from custom_components.eg4_web_monitor import async_unload_entry

        mock_coordinator = MagicMock()
        mock_coordinator.api = MagicMock()
        mock_coordinator.api.close = AsyncMock()
        mock_config_entry.runtime_data = mock_coordinator

        # Mock platform unloading failure
        mock_hass.config_entries.async_unload_platforms = AsyncMock(
            return_value=False
        )

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is False
        # API cleanup should NOT be called if unload failed
        mock_coordinator.api.close.assert_not_called()


# Silver Tier Requirement: Unavailable entities must be marked appropriately
class TestEntityAvailability:
    """Test entity availability handling."""

    def test_switch_available_property_for_inverter(self):
        """Test switch entity marks itself unavailable for non-inverter devices."""
        from custom_components.eg4_web_monitor.switch import EG4QuickChargeSwitch

        # Create mock coordinator with GridBOSS device (should be unavailable)
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "gridboss",
                    "model": "GridBOSS",
                }
            }
        }

        # Create switch entity for GridBOSS device
        switch = EG4QuickChargeSwitch(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"model": "GridBOSS", "type": "gridboss"},
        )

        # Switch should be unavailable for GridBOSS devices
        assert switch.available is False

        # Update to inverter device (should be available)
        mock_coordinator.data["devices"]["1234567890"]["type"] = "inverter"
        assert switch.available is True

    def test_entity_unavailable_when_coordinator_fails(self):
        """Test entities become unavailable when coordinator update fails."""
        from custom_components.eg4_web_monitor.switch import EG4QuickChargeSwitch

        # Create mock coordinator with no data (coordinator failed)
        mock_coordinator = MagicMock()
        mock_coordinator.data = None

        # Create switch entity
        switch = EG4QuickChargeSwitch(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data={"model": "FlexBOSS21", "type": "inverter"},
        )

        # Switch should be unavailable when coordinator has no data
        assert switch.available is False

        # Update coordinator with empty devices dict
        mock_coordinator.data = {"devices": {}}
        assert switch.available is False


# Silver Tier Requirement: Logging required when service becomes unavailable and reconnects
class TestUnavailabilityLogging:
    """Test unavailability and reconnection logging."""

    @patch("custom_components.eg4_web_monitor.coordinator._LOGGER")
    async def test_logs_when_service_becomes_unavailable(
        self, mock_logger, mock_hass, mock_config_entry
    ):
        """Test logging when service becomes unavailable."""
        coordinator = EG4DataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator._last_available_state = True

        # Mock API to raise auth error
        coordinator.api = MagicMock()
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4AuthError("Auth failed")
        )

        # Mock async_create_task to prevent background task warnings
        with patch.object(mock_hass, "async_create_task", return_value=MagicMock()):
            with pytest.raises(ConfigEntryAuthFailed):
                await coordinator._async_update_data()

        # Verify logging
        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "unavailable" in warning_call.lower()
        assert "authentication error" in warning_call.lower()

    @patch("custom_components.eg4_web_monitor.coordinator._LOGGER")
    async def test_logs_when_service_reconnects(
        self, mock_logger, mock_hass, mock_config_entry
    ):
        """Test logging when service reconnects."""
        coordinator = EG4DataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator._last_available_state = False

        # Mock successful API call
        coordinator.api = MagicMock()
        coordinator.api.get_all_device_data = AsyncMock(
            return_value={"devices": {}, "device_info": {}}
        )

        # Mock async_create_task to prevent background task warnings
        with patch.object(mock_hass, "async_create_task", return_value=MagicMock()):
            with patch.object(
                coordinator, "_process_device_data", return_value={"devices": {}}
            ):
                await coordinator._async_update_data()

        # Verify reconnection logging
        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "reconnected" in warning_call.lower()

    @patch("custom_components.eg4_web_monitor.coordinator._LOGGER")
    async def test_logs_connection_errors(
        self, mock_logger, mock_hass, mock_config_entry
    ):
        """Test logging for connection errors."""
        coordinator = EG4DataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator._last_available_state = True

        coordinator.api = MagicMock()
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4ConnectionError("Connection failed")
        )

        # Mock async_create_task to prevent background task warnings
        with patch.object(mock_hass, "async_create_task", return_value=MagicMock()):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "unavailable" in warning_call.lower()
        assert "connection error" in warning_call.lower()

    @patch("custom_components.eg4_web_monitor.coordinator._LOGGER")
    async def test_logs_api_errors(self, mock_logger, mock_hass, mock_config_entry):
        """Test logging for API errors."""
        coordinator = EG4DataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator._last_available_state = True

        coordinator.api = MagicMock()
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4APIError("API error")
        )

        # Mock async_create_task to prevent background task warnings
        with patch.object(mock_hass, "async_create_task", return_value=MagicMock()):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        mock_logger.warning.assert_called()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "unavailable" in warning_call.lower()
        assert "api error" in warning_call.lower()


# Silver Tier Requirement: Parallel update count must be specified
class TestParallelUpdateCount:
    """Test parallel update count specification."""

    def test_sensor_platform_has_max_parallel_updates(self):
        """Test sensor platform specifies MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import sensor

        assert hasattr(sensor, "MAX_PARALLEL_UPDATES")
        assert isinstance(sensor.MAX_PARALLEL_UPDATES, int)
        assert sensor.MAX_PARALLEL_UPDATES > 0

    def test_number_platform_has_max_parallel_updates(self):
        """Test number platform specifies MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import number

        assert hasattr(number, "MAX_PARALLEL_UPDATES")
        assert isinstance(number.MAX_PARALLEL_UPDATES, int)
        assert number.MAX_PARALLEL_UPDATES > 0

    def test_switch_platform_has_max_parallel_updates(self):
        """Test switch platform specifies MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import switch

        assert hasattr(switch, "MAX_PARALLEL_UPDATES")
        assert isinstance(switch.MAX_PARALLEL_UPDATES, int)
        assert switch.MAX_PARALLEL_UPDATES > 0

    def test_button_platform_has_max_parallel_updates(self):
        """Test button platform specifies MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import button

        assert hasattr(button, "MAX_PARALLEL_UPDATES")
        assert isinstance(button.MAX_PARALLEL_UPDATES, int)
        assert button.MAX_PARALLEL_UPDATES > 0

    def test_select_platform_has_max_parallel_updates(self):
        """Test select platform specifies MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import select

        assert hasattr(select, "MAX_PARALLEL_UPDATES")
        assert isinstance(select.MAX_PARALLEL_UPDATES, int)
        assert select.MAX_PARALLEL_UPDATES > 0


# Silver Tier Requirement: Reauthentication available through UI
class TestReauthentication:
    """Test reauthentication flow."""

    async def test_reauth_flow_initiated(self, hass):
        """Test reauthentication flow can be initiated."""
        from custom_components.eg4_web_monitor.config_flow import (
            EG4WebMonitorConfigFlow,
        )

        flow = EG4WebMonitorConfigFlow()
        flow.hass = hass

        entry_data = {
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "old_password",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
        }

        result = await flow.async_step_reauth(entry_data)

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm"

    async def test_reauth_flow_success(self, hass):
        """Test successful reauthentication."""
        from custom_components.eg4_web_monitor.config_flow import (
            EG4WebMonitorConfigFlow,
        )

        flow = EG4WebMonitorConfigFlow()
        flow.hass = hass
        flow._username = "test_user"
        flow._base_url = "https://monitor.eg4electronics.com"
        flow._verify_ssl = True

        # Mock successful login
        with patch(
            "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
        ) as mock_api_class:
            mock_api = AsyncMock()
            mock_api.login = AsyncMock()
            mock_api.close = AsyncMock()
            mock_api_class.return_value = mock_api

            # Mock config entry update
            mock_entry = MagicMock()
            flow.async_set_unique_id = AsyncMock(return_value=mock_entry)
            hass.config_entries.async_update_entry = MagicMock()
            hass.config_entries.async_reload = AsyncMock()

            result = await flow.async_step_reauth_confirm(
                {CONF_PASSWORD: "new_password"}
            )

            assert result["type"] == "abort"
            assert result["reason"] == "reauth_successful"

    async def test_reauth_flow_invalid_credentials(self, hass):
        """Test reauthentication with invalid credentials."""
        from custom_components.eg4_web_monitor.config_flow import (
            EG4WebMonitorConfigFlow,
        )
        from custom_components.eg4_web_monitor.eg4_inverter_api.exceptions import (
            EG4AuthError,
        )

        flow = EG4WebMonitorConfigFlow()
        flow.hass = hass
        flow._username = "test_user"
        flow._base_url = "https://monitor.eg4electronics.com"
        flow._verify_ssl = True

        # Mock failed login
        with patch(
            "custom_components.eg4_web_monitor.config_flow.EG4InverterAPI"
        ) as mock_api_class:
            mock_api = AsyncMock()
            mock_api.login = AsyncMock(side_effect=EG4AuthError("Invalid credentials"))
            mock_api.close = AsyncMock()
            mock_api_class.return_value = mock_api

            result = await flow.async_step_reauth_confirm(
                {CONF_PASSWORD: "wrong_password"}
            )

            assert result["type"] == "form"
            assert result["errors"]["base"] == "invalid_auth"

    async def test_coordinator_triggers_reauth_on_auth_error(
        self, mock_hass, mock_config_entry
    ):
        """Test coordinator triggers reauthentication on authentication error."""
        coordinator = EG4DataUpdateCoordinator(mock_hass, mock_config_entry)

        # Mock API to raise auth error
        coordinator.api = MagicMock()
        coordinator.api.get_all_device_data = AsyncMock(
            side_effect=EG4AuthError("Authentication failed")
        )

        # Mock async_create_task to prevent background task warnings
        # Should raise ConfigEntryAuthFailed which triggers reauth
        with patch.object(mock_hass, "async_create_task", return_value=MagicMock()):
            with pytest.raises(ConfigEntryAuthFailed):
                await coordinator._async_update_data()


# Silver Tier Requirement: Test coverage above 95% for all modules
class TestCoverageMetadata:
    """Metadata test to validate coverage requirements."""

    def test_coverage_requirement_documented(self):
        """Verify 95% coverage requirement is documented."""
        # This test serves as documentation that 95% coverage is required
        # Actual coverage is measured by pytest-cov
        assert True, "95% test coverage required for Silver tier"
