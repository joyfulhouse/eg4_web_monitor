"""Config flow for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

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
        self._plants: Optional[list] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
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

                # Check if we already have an entry for this user
                await self.async_set_unique_id(self._username)
                self._abort_if_unique_id_configured()

                # If only one plant, auto-select and finish
                if len(self._plants) == 1:
                    plant = self._plants[0]
                    return await self._create_entry(
                        plant_id=plant["plantId"],
                        plant_name=plant["name"]
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
    ) -> FlowResult:
        """Handle plant selection step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                plant_id = user_input[CONF_PLANT_ID]

                # Find the selected plant
                selected_plant = None
                for plant in self._plants:
                    if plant["plantId"] == plant_id:
                        selected_plant = plant
                        break

                if not selected_plant:
                    errors["base"] = "invalid_plant"
                else:
                    return await self._create_entry(
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"]
                    )

            except Exception as e:
                _LOGGER.exception("Error during plant selection: %s", e)
                errors["base"] = "unknown"

        # Build plant selection schema
        plant_options = {
            plant["plantId"]: plant["name"]
            for plant in self._plants or []
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
        self._api = EG4InverterAPI(
            username=self._username,
            password=self._password,
            base_url=self._base_url,
            verify_ssl=self._verify_ssl,
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

    async def _create_entry(self, plant_id: str, plant_name: str) -> FlowResult:
        """Create the config entry."""
        # Create unique entry ID based on username and plant
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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
