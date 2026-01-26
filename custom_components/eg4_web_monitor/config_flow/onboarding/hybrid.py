"""Hybrid (Cloud + Local) onboarding mixin for EG4 Web Monitor config flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
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
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_VERIFY_SSL,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
)
from ..helpers import build_unique_id, format_entry_title, timezone_observes_dst
from ..schemas import HYBRID_LOCAL_TYPE_OPTIONS, INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)

# Backward compatibility alias
LOCAL_TYPE_OPTIONS = HYBRID_LOCAL_TYPE_OPTIONS


def _build_http_credentials_schema(dst_sync_default: bool = True) -> vol.Schema:
    """Build the HTTP credentials schema for hybrid mode.

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


class HybridOnboardingMixin:
    """Mixin providing Hybrid (Cloud + Local) onboarding flow steps.

    This mixin handles the initial setup for hybrid connections that combine
    cloud API access with local transport (Modbus or WiFi Dongle):
    1. Collect HTTP credentials
    2. Test authentication and discover plants
    3. Allow user to select a plant (if multiple)
    4. Select local transport type (Modbus or Dongle)
    5. Configure the selected local transport
    6. Create the config entry with both cloud and local settings

    Requires:
        - ConfigFlowProtocol attributes (all HTTP and local fields)
        - _test_credentials() method from EG4ConfigFlowBase
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - _test_dongle_connection() method from EG4ConfigFlowBase
        - _get_inverter_serials_from_plant() method from EG4ConfigFlowBase
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        # HTTP fields
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _dst_sync: bool | None
        _library_debug: bool | None
        _plant_id: str | None
        _plants: list[dict[str, Any]] | None
        # Modbus fields
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        # Dongle fields
        _dongle_host: str | None
        _dongle_port: int | None
        _dongle_serial: str | None
        # Shared local fields
        _inverter_serial: str | None
        _inverter_family: str | None
        _hybrid_local_type: str | None

        async def _test_credentials(self: ConfigFlowProtocol) -> None: ...
        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def _test_dongle_connection(self: ConfigFlowProtocol) -> None: ...
        def _get_inverter_serials_from_plant(
            self: ConfigFlowProtocol,
        ) -> list[str]: ...
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

    async def async_step_hybrid_http(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP credentials step for hybrid mode.

        This is the main entry point for Hybrid onboarding.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect credentials, or next step.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Store HTTP credentials
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                self._dst_sync = user_input.get(CONF_DST_SYNC, True)
                self._library_debug = user_input.get(CONF_LIBRARY_DEBUG, False)

                # Test authentication and get plants
                await self._test_credentials()

                # If only one plant, auto-select and move to local type selection
                if self._plants and len(self._plants) == 1:
                    plant = self._plants[0]
                    self._plant_id = plant["plantId"]
                    return await self.async_step_hybrid_local_type()

                # Multiple plants - show selection step
                return await self.async_step_hybrid_plant()

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

        # Determine DST sync default
        ha_timezone = self.hass.config.time_zone
        dst_sync_default = timezone_observes_dst(ha_timezone)

        return self.async_show_form(
            step_id="hybrid_http",
            data_schema=_build_http_credentials_schema(dst_sync_default),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "base_url": DEFAULT_BASE_URL,
            },
        )

    async def async_step_hybrid_plant(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection for hybrid mode.

        Args:
            user_input: Form data with selected plant_id, or None.

        Returns:
            Form to select plant, or local type selection step.
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
                    self._plant_id = selected_plant["plantId"]
                    return await self.async_step_hybrid_local_type()

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
                vol.Required(CONF_PLANT_ID): vol.In(plant_options),
            }
        )

        return self.async_show_form(
            step_id="hybrid_plant",
            data_schema=plant_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "plant_count": str(len(plant_options)),
            },
        )

    async def async_step_hybrid_local_type(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle local transport type selection for hybrid mode.

        Allows user to choose between Modbus (RS485 adapter) or WiFi Dongle.

        Args:
            user_input: Form data with selected local type, or None.

        Returns:
            Form to select local type, or appropriate configuration step.
        """
        if user_input is not None:
            local_type = user_input[CONF_HYBRID_LOCAL_TYPE]
            self._hybrid_local_type = local_type

            if local_type == HYBRID_LOCAL_MODBUS:
                return await self.async_step_hybrid_modbus()
            if local_type == HYBRID_LOCAL_DONGLE:
                return await self.async_step_hybrid_dongle()
            # Should not reach here, but default to modbus with warning
            _LOGGER.warning(
                "Unexpected hybrid_local_type value: %s, defaulting to Modbus",
                local_type,
            )
            return await self.async_step_hybrid_modbus()

        # Build local transport type selection schema
        local_type_schema = vol.Schema(
            {
                vol.Required(
                    CONF_HYBRID_LOCAL_TYPE, default=HYBRID_LOCAL_MODBUS
                ): vol.In(LOCAL_TYPE_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="hybrid_local_type",
            data_schema=local_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_hybrid_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus configuration for hybrid mode.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect Modbus settings, or entry creation on success.
        """
        errors: dict[str, str] = {}

        # Ensure hybrid local type is set
        if self._hybrid_local_type is None:
            self._hybrid_local_type = HYBRID_LOCAL_MODBUS

        if user_input is not None:
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            # For hybrid, serial comes from plant discovery, but can be overridden
            self._inverter_serial = user_input.get(
                CONF_INVERTER_SERIAL, self._inverter_serial or ""
            )
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection
            try:
                await self._test_modbus_connection()
                return await self._create_hybrid_entry()

            except ImportError:
                errors["base"] = "modbus_not_installed"
            except TimeoutError:
                errors["base"] = "modbus_timeout"
            except OSError as e:
                _LOGGER.error("Modbus connection error: %s", e)
                errors["base"] = "modbus_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected Modbus error: %s", e)
                errors["base"] = "unknown"

        # Try to get inverter serials from the discovered plant
        inverter_serials = self._get_inverter_serials_from_plant()
        default_serial = inverter_serials[0] if inverter_serials else ""

        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Required(CONF_INVERTER_SERIAL, default=default_serial): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="hybrid_modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_hybrid_dongle(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle configuration for hybrid mode.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect dongle settings, or entry creation on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._dongle_host = user_input[CONF_DONGLE_HOST]
            self._dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            self._dongle_serial = user_input[CONF_DONGLE_SERIAL]
            # For hybrid, inverter serial may come from plant discovery or be specified
            self._inverter_serial = user_input.get(
                CONF_INVERTER_SERIAL, self._inverter_serial or ""
            )
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test dongle connection
            try:
                await self._test_dongle_connection()
                return await self._create_hybrid_entry()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        # Try to get inverter serials from the discovered plant
        inverter_serials = self._get_inverter_serials_from_plant()
        default_serial = inverter_serials[0] if inverter_serials else ""

        dongle_schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL, default=default_serial): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="hybrid_dongle",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _create_hybrid_entry(self: ConfigFlowProtocol) -> ConfigFlowResult:
        """Create config entry for hybrid (HTTP + local transport) connection.

        Supports both Modbus and WiFi Dongle as local transport options.

        Returns:
            Config entry creation result.
        """
        # Validate required state
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None
        assert self._plant_id is not None
        assert self._inverter_serial is not None
        assert self._hybrid_local_type is not None

        # Find plant name
        plant_name = "Unknown"
        if self._plants:
            for plant in self._plants:
                if plant["plantId"] == self._plant_id:
                    plant_name = plant["name"]
                    break

        # Set unique ID and check for duplicates
        unique_id = build_unique_id(
            "hybrid", username=self._username, plant_id=self._plant_id
        )
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        title = format_entry_title("hybrid", plant_name)

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            # HTTP configuration
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_LIBRARY_DEBUG: self._library_debug or False,
            CONF_PLANT_ID: self._plant_id,
            CONF_PLANT_NAME: plant_name,
            # Local transport type (modbus or dongle)
            CONF_HYBRID_LOCAL_TYPE: self._hybrid_local_type,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

        # Add transport-specific configuration (legacy format for backward compatibility)
        # Also build the new CONF_LOCAL_TRANSPORTS list for Station.attach_local_transports()
        local_transports: list[dict[str, Any]] = []

        if self._hybrid_local_type == HYBRID_LOCAL_MODBUS:
            assert self._modbus_host is not None
            assert self._modbus_port is not None
            assert self._modbus_unit_id is not None
            # Legacy format (kept for backward compatibility)
            data[CONF_MODBUS_HOST] = self._modbus_host
            data[CONF_MODBUS_PORT] = self._modbus_port
            data[CONF_MODBUS_UNIT_ID] = self._modbus_unit_id
            # New format for Station.attach_local_transports()
            local_transports.append(
                {
                    "serial": self._inverter_serial,
                    "transport_type": "modbus_tcp",
                    "host": self._modbus_host,
                    "port": self._modbus_port,
                    "unit_id": self._modbus_unit_id,
                    "inverter_family": self._inverter_family or DEFAULT_INVERTER_FAMILY,
                }
            )
        elif self._hybrid_local_type == HYBRID_LOCAL_DONGLE:
            assert self._dongle_host is not None
            assert self._dongle_port is not None
            assert self._dongle_serial is not None
            # Legacy format (kept for backward compatibility)
            data[CONF_DONGLE_HOST] = self._dongle_host
            data[CONF_DONGLE_PORT] = self._dongle_port
            data[CONF_DONGLE_SERIAL] = self._dongle_serial
            # New format for Station.attach_local_transports()
            local_transports.append(
                {
                    "serial": self._inverter_serial,
                    "transport_type": "wifi_dongle",
                    "host": self._dongle_host,
                    "port": self._dongle_port,
                    "dongle_serial": self._dongle_serial,
                    "inverter_family": self._inverter_family or DEFAULT_INVERTER_FAMILY,
                }
            )

        # Store the new format for coordinator
        if local_transports:
            data[CONF_LOCAL_TRANSPORTS] = local_transports

        return self.async_create_entry(title=title, data=data)
