"""Hybrid reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for hybrid (cloud + local) connections,
allowing users to update both HTTP credentials and local transport settings.
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
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_BASE_URL,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
)
from ..helpers import find_plant_by_id, format_entry_title, get_reconfigure_entry
from ..schemas import INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol
else:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

_LOGGER = logging.getLogger(__name__)


class HybridReconfigureMixin:
    """Mixin providing Hybrid (cloud + local) reconfiguration flow steps.

    This mixin handles reconfiguration for hybrid connections:

    1. Show combined HTTP + Modbus settings form with current values
    2. Test both connections
    3. If username changed, show plant selection (if multiple plants)
    4. Update config entry and reload

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _test_credentials() method from EG4ConfigFlowBase
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        # HTTP fields
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _dst_sync: bool | None
        _plants: list[dict[str, Any]] | None
        _plant_id: str | None
        # Modbus fields
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        _inverter_serial: str | None
        _inverter_family: str | None

        async def _test_credentials(self: ConfigFlowProtocol) -> None: ...
        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
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

    async def async_step_reconfigure_hybrid(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Hybrid reconfiguration flow - update both HTTP and Modbus settings.

        Gold tier requirement: Reconfiguration available through UI.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to update settings, plant selection, or abort on completion.
        """
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            # Store HTTP credentials
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            self._dst_sync = user_input.get(CONF_DST_SYNC, True)

            # Store Modbus settings
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input.get(
                CONF_INVERTER_SERIAL, entry.data.get(CONF_INVERTER_SERIAL, "")
            )
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            try:
                # Test HTTP credentials
                await self._test_credentials()

                # Test Modbus connection
                await self._test_modbus_connection()

                # Check if we're changing accounts (username changed)
                if self._username != entry.data.get(CONF_USERNAME):
                    # Changing accounts - need to select plant again
                    assert self._plants is not None, "Plants must be loaded"
                    if len(self._plants) == 1:
                        plant = self._plants[0]
                        self._plant_id = plant["plantId"]
                        return await self._update_hybrid_entry_from_reconfigure(
                            entry=entry,
                            plant_id=plant["plantId"],
                            plant_name=plant["name"],
                        )
                    # Multiple plants - show selection step
                    return await self.async_step_reconfigure_hybrid_plant()

                # Same account - keep existing plant
                plant_id = entry.data.get(CONF_PLANT_ID)
                plant_name = entry.data.get(CONF_PLANT_NAME)
                assert plant_id is not None and plant_name is not None, (
                    "Plant ID and name must be set"
                )
                return await self._update_hybrid_entry_from_reconfigure(
                    entry=entry,
                    plant_id=plant_id,
                    plant_name=plant_name,
                )

            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except LuxpowerConnectionError:
                errors["base"] = "cannot_connect"
            except ImportError:
                errors["base"] = "modbus_not_installed"
            except TimeoutError:
                errors["base"] = "modbus_timeout"
            except OSError as e:
                _LOGGER.error("Modbus connection error: %s", e)
                errors["base"] = "modbus_connection_failed"
            except LuxpowerAPIError as e:
                _LOGGER.error("API error during reconfiguration: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error during reconfiguration: %s", e)
                errors["base"] = "unknown"

        # Build hybrid reconfiguration schema with current values
        hybrid_schema = vol.Schema(
            {
                # HTTP settings
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
                # Modbus settings
                vol.Required(
                    CONF_MODBUS_HOST, default=entry.data.get(CONF_MODBUS_HOST, "")
                ): str,
                vol.Optional(
                    CONF_MODBUS_PORT,
                    default=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                ): int,
                vol.Optional(
                    CONF_MODBUS_UNIT_ID,
                    default=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                ): int,
                vol.Optional(
                    CONF_INVERTER_SERIAL,
                    default=entry.data.get(CONF_INVERTER_SERIAL, ""),
                ): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY,
                    default=entry.data.get(
                        CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
                    ),
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid",
            data_schema=hybrid_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
                "current_host": entry.data.get(CONF_MODBUS_HOST, "Unknown"),
            },
        )

    async def async_step_reconfigure_hybrid_plant(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection during hybrid reconfiguration.

        Args:
            user_input: Form data with plant selection, or None for initial display.

        Returns:
            Form to select plant, or abort on completion.
        """
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            try:
                plant_id = user_input[CONF_PLANT_ID]

                # Find the selected plant using helper
                selected_plant = find_plant_by_id(self._plants, plant_id)

                if not selected_plant:
                    errors["base"] = "invalid_plant"
                else:
                    return await self._update_hybrid_entry_from_reconfigure(
                        entry=entry,
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"],
                    )

            except AbortFlow:
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
            step_id="reconfigure_hybrid_plant",
            data_schema=plant_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "plant_count": str(len(plant_options)),
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def _update_hybrid_entry_from_reconfigure(
        self: ConfigFlowProtocol,
        entry: config_entries.ConfigEntry[Any],
        plant_id: str,
        plant_name: str,
    ) -> ConfigFlowResult:
        """Update the Hybrid config entry with new HTTP and local transport data.

        Preserves existing local transport type or defaults to Modbus for
        backward compatibility with pre-v3.1.8 configurations.

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
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None

        unique_id = f"hybrid_{self._username}_{plant_id}"

        # Check for conflicts
        existing_entry = await self.async_set_unique_id(unique_id)
        if existing_entry and existing_entry.entry_id != entry.entry_id:
            _LOGGER.warning(
                "Cannot reconfigure to account %s with plant %s - already configured",
                self._username,
                plant_name,
            )
            return self.async_abort(reason="already_configured")

        # Update title
        title = format_entry_title("hybrid", plant_name)

        # Preserve existing hybrid local type or default to Modbus
        hybrid_local_type = entry.data.get(CONF_HYBRID_LOCAL_TYPE, HYBRID_LOCAL_MODBUS)

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            # HTTP settings
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
            # Local transport type and common settings
            CONF_HYBRID_LOCAL_TYPE: hybrid_local_type,
            CONF_INVERTER_SERIAL: self._inverter_serial or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
            # Modbus settings (current reconfigure flow only supports Modbus)
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
        }

        # Build new CONF_LOCAL_TRANSPORTS list for Station.attach_local_transports()
        local_transports: list[dict[str, Any]] = []
        inverter_serial = self._inverter_serial or ""
        inverter_family = self._inverter_family or DEFAULT_INVERTER_FAMILY

        # Add Modbus transport config if present
        # Uses TransportType enum string values for direct TransportConfig creation
        if hybrid_local_type == HYBRID_LOCAL_MODBUS and self._modbus_host:
            local_transports.append(
                {
                    "serial": inverter_serial,
                    "transport_type": "modbus_tcp",  # TransportType.MODBUS_TCP.value
                    "host": self._modbus_host,
                    "port": self._modbus_port,
                    "unit_id": self._modbus_unit_id,
                    "inverter_family": inverter_family,
                }
            )

        # Preserve dongle settings if using dongle transport
        if hybrid_local_type == HYBRID_LOCAL_DONGLE:
            dongle_host = entry.data.get("dongle_host")
            dongle_port = entry.data.get("dongle_port")
            dongle_serial = entry.data.get("dongle_serial")
            if dongle_host:
                local_transports.append(
                    {
                        "serial": inverter_serial,
                        "transport_type": "wifi_dongle",  # TransportType.WIFI_DONGLE.value
                        "host": dongle_host,
                        "port": dongle_port,
                        "dongle_serial": dongle_serial,
                        "inverter_family": inverter_family,
                    }
                )

        data[CONF_LOCAL_TRANSPORTS] = local_transports

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
