"""Config flow for EG4 Web Monitor integration."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import aiohttp_client

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.data_entry_flow import AbortFlow
    from homeassistant.exceptions import HomeAssistantError
else:
    from homeassistant import config_entries  # type: ignore[assignment]
    from homeassistant.data_entry_flow import AbortFlow
    from homeassistant.exceptions import HomeAssistantError

    # At runtime, ConfigFlowResult might not exist, use FlowResult
    try:
        from homeassistant.config_entries import (
            ConfigFlowResult,  # type: ignore[attr-defined]
        )
    except ImportError:
        from homeassistant.data_entry_flow import (
            FlowResult as ConfigFlowResult,  # type: ignore[misc]
        )

from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from .const import (
    BRAND_NAME,
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_BASE_URL,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _timezone_observes_dst(timezone_name: str | None) -> bool:
    """Check if a timezone observes Daylight Saving Time.

    Args:
        timezone_name: IANA timezone name (e.g., 'America/New_York', 'UTC')

    Returns:
        True if the timezone observes DST, False otherwise.
    """
    if not timezone_name:
        return False

    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        # Invalid timezone name, default to False
        _LOGGER.debug("Invalid timezone name: %s", timezone_name)
        return False

    # Check UTC offsets at two different times in the year
    # January 15 and July 15 are typically in different DST states for most zones
    current_year = datetime.now().year
    winter = datetime(current_year, 1, 15, 12, 0, 0, tzinfo=tz)
    summer = datetime(current_year, 7, 15, 12, 0, 0, tzinfo=tz)

    # If UTC offsets differ, the timezone observes DST
    return winter.utcoffset() != summer.utcoffset()


def _build_user_data_schema(dst_sync_default: bool = True) -> vol.Schema:
    """Build the user data schema with dynamic DST sync default.

    Args:
        dst_sync_default: Default value for DST sync checkbox.

    Returns:
        Voluptuous schema for user data step.
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


class EG4WebMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EG4 Web Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        # Common fields
        self._connection_type: str | None = None

        # HTTP (cloud) connection fields
        self._username: str | None = None
        self._password: str | None = None
        self._base_url: str | None = None
        self._verify_ssl: bool | None = None
        self._dst_sync: bool | None = None
        self._library_debug: bool | None = None
        self._plant_id: str | None = None
        self._plants: list[dict[str, Any]] | None = None

        # Modbus (local) connection fields
        self._modbus_host: str | None = None
        self._modbus_port: int | None = None
        self._modbus_unit_id: int | None = None
        self._inverter_serial: str | None = None
        self._inverter_model: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - connection type selection."""
        if user_input is not None:
            connection_type = user_input[CONF_CONNECTION_TYPE]
            self._connection_type = connection_type

            if connection_type == CONNECTION_TYPE_HTTP:
                return await self.async_step_http_credentials()
            if connection_type == CONNECTION_TYPE_MODBUS:
                return await self.async_step_modbus()
            # Hybrid mode - start with HTTP credentials
            return await self.async_step_hybrid_http()

        # Show connection type selection
        connection_type_schema = vol.Schema(
            {
                vol.Required(
                    CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_HTTP
                ): vol.In(
                    {
                        CONNECTION_TYPE_HTTP: "Cloud API (HTTP)",
                        CONNECTION_TYPE_MODBUS: "Local Modbus TCP",
                        CONNECTION_TYPE_HYBRID: "Hybrid (Local + Cloud)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=connection_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_http_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP cloud API credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Store credentials
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                self._dst_sync = user_input.get(CONF_DST_SYNC, True)
                self._library_debug = user_input.get(CONF_LIBRARY_DEBUG, False)

                # Test authentication and get plants
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
        dst_sync_default = _timezone_observes_dst(ha_timezone)
        _LOGGER.debug(
            "HA timezone: %s, observes DST: %s", ha_timezone, dst_sync_default
        )

        return self.async_show_form(
            step_id="http_credentials",
            data_schema=_build_user_data_schema(dst_sync_default),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "base_url": DEFAULT_BASE_URL,
            },
        )

    async def async_step_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus TCP connection configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")

            # Test Modbus connection
            try:
                await self._test_modbus_connection()
                return await self._create_modbus_entry()

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

        # Build Modbus configuration schema
        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(CONF_INVERTER_MODEL, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _test_modbus_connection(self) -> None:
        """Test Modbus TCP connection to the inverter."""
        from pylxpweb.transports import create_modbus_transport
        from pylxpweb.transports.exceptions import TransportConnectionError

        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        assert self._inverter_serial is not None

        transport = create_modbus_transport(
            host=self._modbus_host,
            port=self._modbus_port,
            unit_id=self._modbus_unit_id,
            serial=self._inverter_serial,
            timeout=DEFAULT_MODBUS_TIMEOUT,
        )

        try:
            await transport.connect()

            # Try to read runtime data to verify connection
            runtime = await transport.read_runtime()
            _LOGGER.info(
                "Modbus connection successful - PV power: %sW, Battery SOC: %s%%",
                runtime.pv_total_power,
                runtime.battery_soc,
            )
        except TransportConnectionError:
            raise
        finally:
            await transport.disconnect()

    async def _create_modbus_entry(self) -> ConfigFlowResult:
        """Create config entry for Modbus connection."""
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        assert self._inverter_serial is not None

        # Use inverter serial as unique ID
        unique_id = f"modbus_{self._inverter_serial}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create title
        model_suffix = f" ({self._inverter_model})" if self._inverter_model else ""
        title = f"{BRAND_NAME} Modbus - {self._inverter_serial}{model_suffix}"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS,
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
        }

        return self.async_create_entry(title=title, data=data)

    async def async_step_hybrid_http(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP credentials step for hybrid mode."""
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

                # If only one plant, auto-select and move to Modbus config
                if self._plants and len(self._plants) == 1:
                    plant = self._plants[0]
                    self._plant_id = plant["plantId"]
                    return await self.async_step_hybrid_modbus()

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
        dst_sync_default = _timezone_observes_dst(ha_timezone)

        return self.async_show_form(
            step_id="hybrid_http",
            data_schema=_build_user_data_schema(dst_sync_default),
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "base_url": DEFAULT_BASE_URL,
            },
        )

    async def async_step_hybrid_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection for hybrid mode."""
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
                    return await self.async_step_hybrid_modbus()

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

    async def async_step_hybrid_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus configuration for hybrid mode."""
        errors: dict[str, str] = {}

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
        inverter_serials: list[str] = []
        if self._plants and self._plant_id:
            for plant in self._plants:
                if plant["plantId"] == self._plant_id:
                    # Get inverters from plant if available
                    inverters = plant.get("inverters", [])
                    inverter_serials = [
                        inv.get("serialNum", "")
                        for inv in inverters
                        if inv.get("serialNum")
                    ]
                    break

        # Pre-fill first inverter serial if available
        default_serial = inverter_serials[0] if inverter_serials else ""

        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Required(CONF_INVERTER_SERIAL, default=default_serial): str,
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

    async def _create_hybrid_entry(self) -> ConfigFlowResult:
        """Create config entry for hybrid (HTTP + Modbus) connection."""
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None
        assert self._plant_id is not None
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        assert self._inverter_serial is not None

        # Find plant name
        plant_name = "Unknown"
        if self._plants:
            for plant in self._plants:
                if plant["plantId"] == self._plant_id:
                    plant_name = plant["name"]
                    break

        # Unique ID includes both account and plant
        unique_id = f"hybrid_{self._username}_{self._plant_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        title = f"{BRAND_NAME} Hybrid - {plant_name}"

        data = {
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
            # Modbus configuration
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
            CONF_INVERTER_SERIAL: self._inverter_serial,
        }

        return self.async_create_entry(title=title, data=data)

    async def async_step_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection step."""
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
                "brand_name": BRAND_NAME,
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

        # Use context manager for automatic login/logout
        async with LuxpowerClient(
            username=self._username,
            password=self._password,
            base_url=self._base_url,
            verify_ssl=self._verify_ssl,
            session=session,
        ) as client:
            # Import Station here to avoid circular import
            from pylxpweb.devices import Station

            # Load all stations for this user (uses device objects!)
            stations = await Station.load_all(client)
            _LOGGER.debug("Authentication successful")

            # Convert Station objects to dict list
            self._plants = [
                {
                    "plantId": station.id,
                    "name": station.name,
                }
                for station in stations
            ]
            _LOGGER.debug("Found %d plants", len(self._plants))

            if not self._plants:
                raise LuxpowerAPIError("No plants found for this account")

    async def _create_http_entry(
        self, plant_id: str, plant_name: str
    ) -> ConfigFlowResult:
        """Create the config entry for HTTP cloud API connection."""
        # Create unique entry ID based on username and plant
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None
        assert self._library_debug is not None

        unique_id = f"{self._username}_{plant_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create entry title
        title = f"{BRAND_NAME} Web Monitor - {plant_name}"

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
        self._plant_id = entry_data.get(CONF_PLANT_ID)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation.

        Silver tier requirement: Reauthentication available through UI.
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration flow.

        Gold tier requirement: Reconfiguration available through UI.
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
                        return await self._update_entry(
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
                return await self._update_entry(
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
            step_id="reconfigure",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def async_step_reconfigure_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection during reconfiguration.

        Gold tier requirement: Reconfiguration available through UI.
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
                "brand_name": BRAND_NAME,
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
        title = f"{BRAND_NAME} Web Monitor - {plant_name}"

        # Preserve existing connection type and Modbus settings if they exist
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

        # Update entry data
        data = {
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

        return self.async_abort(reason="reconfigure_successful")


class CannotConnectError(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuthError(HomeAssistantError):
    """Error to indicate there is invalid auth."""
