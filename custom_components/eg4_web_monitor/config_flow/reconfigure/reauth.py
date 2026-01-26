"""Reauthentication mixin for EG4 Web Monitor config flow.

This module provides the reauthentication flow for when cloud API credentials
become invalid. This is a Silver tier requirement.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import aiohttp_client
from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from ...const import (
    BRAND_NAME,
    CONF_BASE_URL,
    CONF_PLANT_ID,
    DEFAULT_BASE_URL,
    DEFAULT_VERIFY_SSL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol
else:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

_LOGGER = logging.getLogger(__name__)


class ReauthMixin:
    """Mixin providing reauthentication flow steps.

    This mixin handles reauthentication when cloud API credentials become
    invalid (e.g., password changed, session expired, etc.):

    1. Store existing entry data for reference
    2. Show password entry form
    3. Test new credentials
    4. Update entry and reload integration

    Silver tier requirement: Reauthentication available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _plant_id: str | None

        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> Any: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_abort(
            self: ConfigFlowProtocol,
            *,
            reason: str,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...

    async def async_step_reauth(
        self: ConfigFlowProtocol, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication flow entry point.

        Silver tier requirement: Reauthentication available through UI.

        Args:
            entry_data: Data from the config entry that needs reauthentication.

        Returns:
            Redirect to reauth_confirm step.
        """
        # Store the existing entry data for later use
        self._base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        self._verify_ssl = entry_data.get("verify_ssl", DEFAULT_VERIFY_SSL)
        self._username = entry_data.get(CONF_USERNAME)
        self._plant_id = entry_data.get(CONF_PLANT_ID)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation.

        Silver tier requirement: Reauthentication available through UI.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to enter new password, or abort on success/failure.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Update password
                password = user_input[CONF_PASSWORD]

                # Test new credentials with injected session (Platinum tier requirement)
                session = aiohttp_client.async_get_clientsession(self.hass)
                assert self._username is not None
                assert self._base_url is not None
                assert self._verify_ssl is not None

                # Use context manager for automatic login/logout
                async with LuxpowerClient(
                    username=self._username,
                    password=password,
                    base_url=self._base_url,
                    verify_ssl=self._verify_ssl,
                    session=session,
                ):
                    _LOGGER.debug("Reauthentication successful")

                # Get the existing config entry using correct unique_id format
                unique_id = f"{self._username}_{self._plant_id}"
                existing_entry = await self.async_set_unique_id(unique_id)
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

            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except LuxpowerConnectionError:
                errors["base"] = "cannot_connect"
            except LuxpowerAPIError as e:
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
                "brand_name": BRAND_NAME,
                "username": self._username or "",
            },
        )
