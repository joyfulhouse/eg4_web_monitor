"""HTTP (cloud) reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for cloud API connections, allowing users
to update credentials, change stations, or modify DST sync settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.data_entry_flow import AbortFlow
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
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_BASE_URL,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    CONF_INVERTER_SERIAL,
)
from ..helpers import format_entry_title

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol
else:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

_LOGGER = logging.getLogger(__name__)


class HttpReconfigureMixin:
    """Mixin providing HTTP (cloud) reconfiguration flow steps.

    This mixin handles reconfiguration for HTTP/cloud connections:

    1. Show credentials form with current values
    2. Test new credentials
    3. If username changed, show plant selection (if multiple plants)
    4. Update config entry and reload

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _test_credentials() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _dst_sync: bool | None
        _plants: list[dict[str, Any]] | None

        async def _test_credentials(self: ConfigFlowProtocol) -> None: ...
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

    async def async_step_reconfigure_http(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP (cloud) reconfiguration flow.

        Gold tier requirement: Reconfiguration available through UI.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to update credentials, plant selection, or abort on completion.
        """
        errors: dict[str, str] = {}

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
                self._dst_sync = user_input.get(CONF_DST_SYNC, True)

                # Test new credentials and get plants
                await self._test_credentials()

                # Check if we're changing accounts (username changed)
                if self._username != entry.data.get(CONF_USERNAME):
                    # Changing accounts - need to select plant again
                    assert self._plants is not None, "Plants must be loaded"
                    if len(self._plants) == 1:
                        plant = self._plants[0]
                        return await self._update_http_entry(
                            entry=entry,
                            plant_id=plant["plantId"],
                            plant_name=plant["name"],
                        )
                    # Multiple plants - show selection step
                    return await self.async_step_reconfigure_plant()
                # Same account - keep existing plant
                plant_id = entry.data.get(CONF_PLANT_ID)
                plant_name = entry.data.get(CONF_PLANT_NAME)
                assert plant_id is not None and plant_name is not None, (
                    "Plant ID and name must be set"
                )
                return await self._update_http_entry(
                    entry=entry,
                    plant_id=plant_id,
                    plant_name=plant_name,
                )

            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except LuxpowerConnectionError:
                errors["base"] = "cannot_connect"
            except LuxpowerAPIError as e:
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
                vol.Optional(
                    CONF_DST_SYNC, default=entry.data.get(CONF_DST_SYNC, True)
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_http",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def async_step_reconfigure_plant(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection during HTTP reconfiguration.

        Gold tier requirement: Reconfiguration available through UI.

        Args:
            user_input: Form data with plant selection, or None for initial display.

        Returns:
            Form to select plant, or abort on completion.
        """
        errors: dict[str, str] = {}

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
                    return await self._update_http_entry(
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
                "brand_name": BRAND_NAME,
                "plant_count": str(len(plant_options)),
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def _update_http_entry(
        self: ConfigFlowProtocol,
        entry: config_entries.ConfigEntry[Any],
        plant_id: str,
        plant_name: str,
    ) -> ConfigFlowResult:
        """Update the HTTP config entry with new data.

        Args:
            entry: The config entry to update.
            plant_id: The plant/station ID.
            plant_name: The plant/station name.

        Returns:
            Abort result indicating success or conflict.
        """
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None

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
        title = format_entry_title("http", plant_name)

        # Update entry data - preserve connection type
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: connection_type,
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
        }

        # Preserve Modbus settings for hybrid mode
        if connection_type == CONNECTION_TYPE_HYBRID:
            data[CONF_MODBUS_HOST] = entry.data.get(CONF_MODBUS_HOST, "")
            data[CONF_MODBUS_PORT] = entry.data.get(
                CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT
            )
            data[CONF_MODBUS_UNIT_ID] = entry.data.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            data[CONF_INVERTER_SERIAL] = entry.data.get(CONF_INVERTER_SERIAL, "")

        self.hass.config_entries.async_update_entry(
            entry,
            title=title,
            data=data,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)

        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )
