"""Config flow for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import aiohttp_client

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.data_entry_flow import AbortFlow
else:
    from homeassistant import config_entries  # type: ignore[assignment]
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.data_entry_flow import AbortFlow

    # At runtime, ConfigFlowResult might not exist, use FlowResult
    try:
        from homeassistant.config_entries import ConfigFlowResult  # type: ignore[attr-defined]
    except ImportError:
        from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult  # type: ignore[misc]

from .const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from .eg4_inverter_api import EG4InverterAPI
from .eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


class EG4WebMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EG4 Web Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api: Optional[EG4InverterAPI] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._base_url: Optional[str] = None
        self._verify_ssl: Optional[bool] = None
        self._plants: Optional[List[Dict[str, Any]]] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """Handle the initial step - user credentials."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Store credentials
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

                # Test authentication and get plants
                await self._test_credentials()

                # If only one plant, auto-select and finish
                if self._plants and len(self._plants) == 1:
                    plant = self._plants[0]
                    return await self._create_entry(
                        plant_id=plant["plantId"], plant_name=plant["name"]
                    )

                # Multiple plants - show selection step
                return await self.async_step_plant()

            except EG4AuthError:
                errors["base"] = "invalid_auth"
            except EG4ConnectionError:
                errors["base"] = "cannot_connect"
            except EG4APIError as e:
                _LOGGER.error("API error during authentication: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error: %s", e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "base_url": DEFAULT_BASE_URL,
            },
        )

    async def async_step_plant(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """Handle plant selection step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                plant_id = user_input[CONF_PLANT_ID]

                # Find the selected plant
                selected_plant = None
                if self._plants:
                    for plant in self._plants:
                        if plant["plantId"] == plant_id:
                            selected_plant = plant
                            break

                if not selected_plant:
                    errors["base"] = "invalid_plant"
                else:
                    return await self._create_entry(
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"],
                    )

            except AbortFlow:
                # Let AbortFlow exceptions pass through (e.g., already_configured)
                raise
            except Exception as e:
                _LOGGER.exception("Error during plant selection: %s", e)
                errors["base"] = "unknown"

        # Build plant selection schema
        plant_options = {
            plant["plantId"]: plant["name"] for plant in self._plants or []
        }

        plant_schema = vol.Schema(
            {
                vol.Required(CONF_PLANT_ID): vol.In(plant_options),
            }
        )

        return self.async_show_form(
            step_id="plant",
            data_schema=plant_schema,
            errors=errors,
            description_placeholders={
                "plant_count": str(len(plant_options)),
            },
        )

    async def _test_credentials(self) -> None:
        """Test if we can authenticate with the given credentials."""
        # Inject Home Assistant's aiohttp session (Platinum tier requirement)
        session = aiohttp_client.async_get_clientsession(self.hass)
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        self._api = EG4InverterAPI(
            username=self._username,
            password=self._password,
            base_url=self._base_url,
            verify_ssl=self._verify_ssl,
            session=session,
        )

        try:
            # Test login
            await self._api.login()
            _LOGGER.debug("Authentication successful")

            # Get plants
            self._plants = await self._api.get_plants()
            _LOGGER.debug("Found %d plants", len(self._plants))

            if not self._plants:
                raise EG4APIError("No plants found for this account")

        finally:
            if self._api:
                await self._api.close()

    async def _create_entry(self, plant_id: str, plant_name: str) -> ConfigFlowResult:
        """Create the config entry."""
        # Create unique entry ID based on username and plant
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None

        unique_id = f"{self._username}_{plant_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create entry title
        title = f"EG4 Web Monitor - {plant_name}"

        # Create entry data
        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
        }

        return self.async_create_entry(
            title=title,
            data=data,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication flow.

        Silver tier requirement: Reauthentication available through UI.
        """
        # Store the existing entry data for later use
        self._base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        self._verify_ssl = entry_data.get(CONF_VERIFY_SSL, True)
        self._username = entry_data.get(CONF_USERNAME)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation.

        Silver tier requirement: Reauthentication available through UI.
        """
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Update password
                password = user_input[CONF_PASSWORD]

                # Test new credentials with injected session (Platinum tier requirement)
                session = aiohttp_client.async_get_clientsession(self.hass)
                assert self._username is not None
                assert self._base_url is not None
                assert self._verify_ssl is not None
                api = EG4InverterAPI(
                    username=self._username,
                    password=password,
                    base_url=self._base_url,
                    verify_ssl=self._verify_ssl,
                    session=session,
                )

                try:
                    await api.login()
                    _LOGGER.debug("Reauthentication successful")
                finally:
                    await api.close()

                # Get the existing config entry
                existing_entry = await self.async_set_unique_id(self._username)
                if existing_entry:
                    # Update the entry with new password
                    self.hass.config_entries.async_update_entry(
                        existing_entry,
                        data={
                            **existing_entry.data,
                            CONF_PASSWORD: password,
                        },
                    )
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

            except EG4AuthError:
                errors["base"] = "invalid_auth"
            except EG4ConnectionError:
                errors["base"] = "cannot_connect"
            except EG4APIError as e:
                _LOGGER.error("API error during reauthentication: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error during reauthentication: %s", e)
                errors["base"] = "unknown"

        # Show reauthentication form
        reauth_schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=reauth_schema,
            errors=errors,
            description_placeholders={
                "username": self._username or "",
            },
        )

    async def async_step_reconfigure(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration flow.

        Gold tier requirement: Reconfiguration available through UI.
        """
        errors: Dict[str, str] = {}

        # Get the current entry being reconfigured
        entry_id = self.context.get("entry_id")
        assert entry_id is not None, "entry_id must be set in context"
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None, "Config entry not found"

        if user_input is not None:
            try:
                # Store new credentials
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

                # Test new credentials and get plants
                await self._test_credentials()

                # Check if we're changing accounts (username changed)
                if self._username != entry.data.get(CONF_USERNAME):
                    # Changing accounts - need to select plant again
                    assert self._plants is not None, "Plants must be loaded"
                    if len(self._plants) == 1:
                        plant = self._plants[0]
                        return await self._update_entry(
                            entry=entry,
                            plant_id=plant["plantId"],
                            plant_name=plant["name"],
                        )
                    else:
                        # Multiple plants - show selection step
                        return await self.async_step_reconfigure_plant()
                else:
                    # Same account - keep existing plant
                    plant_id = entry.data.get(CONF_PLANT_ID)
                    plant_name = entry.data.get(CONF_PLANT_NAME)
                    assert plant_id is not None and plant_name is not None, (
                        "Plant ID and name must be set"
                    )
                    return await self._update_entry(
                        entry=entry,
                        plant_id=plant_id,
                        plant_name=plant_name,
                    )

            except EG4AuthError:
                errors["base"] = "invalid_auth"
            except EG4ConnectionError:
                errors["base"] = "cannot_connect"
            except EG4APIError as e:
                _LOGGER.error("API error during reconfiguration: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error during reconfiguration: %s", e)
                errors["base"] = "unknown"

        # Show reconfiguration form with current values
        reconfigure_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME)): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_BASE_URL,
                    default=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                ): str,
                vol.Optional(
                    CONF_VERIFY_SSL, default=entry.data.get(CONF_VERIFY_SSL, True)
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def async_step_reconfigure_plant(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """Handle plant selection during reconfiguration.

        Gold tier requirement: Reconfiguration available through UI.
        """
        errors: Dict[str, str] = {}

        # Get the current entry being reconfigured
        entry_id = self.context.get("entry_id")
        assert entry_id is not None, "entry_id must be set in context"
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None, "Config entry not found"

        if user_input is not None:
            try:
                plant_id = user_input[CONF_PLANT_ID]

                # Find the selected plant
                selected_plant = None
                assert self._plants is not None, "Plants must be loaded"
                for plant in self._plants:
                    if plant["plantId"] == plant_id:
                        selected_plant = plant
                        break

                if not selected_plant:
                    errors["base"] = "invalid_plant"
                else:
                    return await self._update_entry(
                        entry=entry,
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"],
                    )

            except AbortFlow:
                # Let AbortFlow exceptions pass through (e.g., already_configured)
                raise
            except Exception as e:
                _LOGGER.exception("Error during plant selection: %s", e)
                errors["base"] = "unknown"

        # Build plant selection schema
        plant_options = {
            plant["plantId"]: plant["name"] for plant in self._plants or []
        }

        plant_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PLANT_ID, default=entry.data.get(CONF_PLANT_ID)
                ): vol.In(plant_options),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_plant",
            data_schema=plant_schema,
            errors=errors,
            description_placeholders={
                "plant_count": str(len(plant_options)),
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def _update_entry(
        self, entry: config_entries.ConfigEntry[Any], plant_id: str, plant_name: str
    ) -> ConfigFlowResult:
        """Update the config entry with new data."""
        # Update unique ID if username changed
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None

        unique_id = f"{self._username}_{plant_id}"

        # Defensive check: If the new unique ID matches an existing entry
        # (other than the one being reconfigured), abort to prevent conflicts
        existing_entry = await self.async_set_unique_id(unique_id)
        if existing_entry and existing_entry.entry_id != entry.entry_id:
            _LOGGER.warning(
                "Cannot reconfigure to account %s with plant %s - already configured",
                self._username,
                plant_name,
            )
            return self.async_abort(reason="already_configured")

        # Update entry title
        title = f"EG4 Web Monitor - {plant_name}"

        # Update entry data
        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
        }

        self.hass.config_entries.async_update_entry(
            entry,
            title=title,
            data=data,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)

        return self.async_abort(reason="reconfigure_successful")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
