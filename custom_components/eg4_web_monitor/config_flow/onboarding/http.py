"""HTTP (Cloud API) onboarding mixin for EG4 Web Monitor config flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from ...const import (
    BRAND_NAME,
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DEFAULT_BASE_URL,
    DEFAULT_VERIFY_SSL,
)
from ..helpers import build_unique_id, format_entry_title, timezone_observes_dst

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


def _build_http_credentials_schema(dst_sync_default: bool = True) -> vol.Schema:
    """Build the HTTP credentials schema with dynamic DST sync default.

    Args:
        dst_sync_default: Default value for DST sync checkbox.

    Returns:
        Voluptuous schema for HTTP credentials step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
            vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            vol.Optional(CONF_DST_SYNC, default=dst_sync_default): bool,
            vol.Optional(CONF_LIBRARY_DEBUG, default=False): bool,
        }
    )


class HttpOnboardingMixin:
    """Mixin providing HTTP (Cloud API) onboarding flow steps.

    This mixin handles the initial setup for cloud-only connections:
    1. Collect HTTP credentials (username, password, base URL)
    2. Test authentication and discover available plants
    3. Allow user to select a plant (if multiple)
    4. Create the config entry

    Requires:
        - ConfigFlowProtocol attributes (_username, _password, etc.)
        - _test_credentials() method from EG4ConfigFlowBase
        - hass attribute from ConfigFlow
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _dst_sync: bool | None
        _library_debug: bool | None
        _plants: list[dict[str, Any]] | None

        async def _test_credentials(self: ConfigFlowProtocol) -> None: ...
        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> None: ...
        def _abort_if_unique_id_configured(self: ConfigFlowProtocol) -> None: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_create_entry(
            self: ConfigFlowProtocol,
            *,
            title: str,
            data: dict[str, Any],
        ) -> ConfigFlowResult: ...

    async def async_step_http_credentials(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP cloud API credentials step.

        This is the main entry point for HTTP-only onboarding.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect credentials, or next step/entry creation.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Store credentials in instance state
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                self._dst_sync = user_input.get(CONF_DST_SYNC, True)
                self._library_debug = user_input.get(CONF_LIBRARY_DEBUG, False)

                # Test authentication and discover plants
                await self._test_credentials()

                # If only one plant, auto-select and finish
                if self._plants and len(self._plants) == 1:
                    plant = self._plants[0]
                    return await self._create_http_entry(
                        plant_id=plant["plantId"], plant_name=plant["name"]
                    )

                # Multiple plants - show selection step
                return await self.async_step_plant()

            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except LuxpowerConnectionError:
                errors["base"] = "cannot_connect"
            except LuxpowerAPIError as e:
                _LOGGER.error("API error during authentication: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error: %s", e)
                errors["base"] = "unknown"

        # Determine DST sync default based on Home Assistant timezone
        ha_timezone = self.hass.config.time_zone
        dst_sync_default = timezone_observes_dst(ha_timezone)
        _LOGGER.debug(
            "HA timezone: %s, observes DST: %s", ha_timezone, dst_sync_default
        )

        return self.async_show_form(
            step_id="http_credentials",
            data_schema=_build_http_credentials_schema(dst_sync_default),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "base_url": DEFAULT_BASE_URL,
            },
        )

    async def async_step_plant(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection step when multiple plants exist.

        Args:
            user_input: Form data with selected plant_id, or None.

        Returns:
            Form to select plant, or entry creation on selection.
        """
        errors: dict[str, str] = {}

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
                    return await self._create_http_entry(
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"],
                    )

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
                "brand_name": BRAND_NAME,
                "plant_count": str(len(plant_options)),
            },
        )

    async def _create_http_entry(
        self: ConfigFlowProtocol, plant_id: str, plant_name: str
    ) -> ConfigFlowResult:
        """Create the config entry for HTTP cloud API connection.

        Args:
            plant_id: The selected plant/station ID.
            plant_name: The plant name for display.

        Returns:
            Config entry creation result.
        """
        # Validate required state
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None
        assert self._library_debug is not None

        # Set unique ID and check for duplicates
        unique_id = build_unique_id("http", username=self._username, plant_id=plant_id)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create entry title
        title = format_entry_title("http", plant_name)

        # Create entry data
        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_LIBRARY_DEBUG: self._library_debug,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
        }

        return self.async_create_entry(title=title, data=data)
