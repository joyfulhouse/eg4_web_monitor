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
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONF_STATION_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_LOCAL_STATION_NAME,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
    MAX_PARAMETER_REFRESH_INTERVAL,
    MAX_SENSOR_UPDATE_INTERVAL,
    MIN_PARAMETER_REFRESH_INTERVAL,
    MIN_SENSOR_UPDATE_INTERVAL,
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


class EG4WebMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
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
        self._inverter_family: str | None = None

        # WiFi Dongle (local) connection fields
        self._dongle_host: str | None = None
        self._dongle_port: int | None = None
        self._dongle_serial: str | None = None

        # Hybrid mode local transport type selection
        self._hybrid_local_type: str | None = None

        # Local-only multi-device mode fields
        self._local_devices: list[dict[str, Any]] = []
        self._station_name: str | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EG4OptionsFlow()

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
            if connection_type == CONNECTION_TYPE_DONGLE:
                return await self.async_step_dongle()
            if connection_type == CONNECTION_TYPE_LOCAL:
                return await self.async_step_local_setup()
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
                        CONNECTION_TYPE_MODBUS: "Local Modbus TCP (single inverter)",
                        CONNECTION_TYPE_DONGLE: "Local WiFi Dongle (single inverter)",
                        CONNECTION_TYPE_LOCAL: "Local Multi-Device (no cloud required)",
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
            # Serial is now optional - will be auto-detected if not provided
            self._inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection and auto-detect serial if not provided
            try:
                detected_serial = await self._test_modbus_connection()
                # Use detected serial if user didn't provide one
                if not self._inverter_serial and detected_serial:
                    self._inverter_serial = detected_serial
                    _LOGGER.info(
                        "Auto-detected inverter serial from Modbus: %s",
                        detected_serial,
                    )
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
        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        # Serial is optional - auto-detected from Modbus registers if not provided
        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(CONF_INVERTER_MODEL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
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

    async def _test_modbus_connection(self) -> str:
        """Test Modbus TCP connection and read serial number.

        Returns:
            The inverter serial number read from Modbus registers.
        """
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_modbus_transport
        from pylxpweb.transports.exceptions import TransportConnectionError

        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None

        # Convert string family to InverterFamily enum
        inverter_family = None
        if self._inverter_family:
            try:
                inverter_family = InverterFamily(self._inverter_family)
            except ValueError:
                _LOGGER.warning(
                    "Unknown inverter family '%s', using default", self._inverter_family
                )

        transport = create_modbus_transport(
            host=self._modbus_host,
            port=self._modbus_port,
            unit_id=self._modbus_unit_id,
            serial=self._inverter_serial or "",
            timeout=DEFAULT_MODBUS_TIMEOUT,
            inverter_family=inverter_family,
        )

        detected_serial = ""
        try:
            await transport.connect()

            # Read serial number from Modbus registers
            detected_serial = str(await transport.read_serial_number())
            _LOGGER.debug(
                "Read serial number from Modbus registers: %s", detected_serial
            )

            # Try to read runtime data to verify connection
            runtime = await transport.read_runtime()
            _LOGGER.info(
                "Modbus connection successful - Serial: %s, PV power: %sW, Battery SOC: %s%%",
                detected_serial,
                runtime.pv_total_power,
                runtime.battery_soc,
            )
        except TransportConnectionError:
            raise
        finally:
            await transport.disconnect()

        return detected_serial

    async def _create_modbus_entry(self) -> ConfigFlowResult:
        """Create config entry for Modbus connection."""
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        # Serial should have been auto-detected if not provided by user
        assert self._inverter_serial, "Serial number must be provided or auto-detected"

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
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

        return self.async_create_entry(title=title, data=data)

    async def async_step_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle TCP connection configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._dongle_host = user_input[CONF_DONGLE_HOST]
            self._dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            self._dongle_serial = user_input[CONF_DONGLE_SERIAL]
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test dongle connection
            try:
                await self._test_dongle_connection()
                return await self._create_dongle_entry()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        # Build dongle configuration schema
        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        dongle_schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(CONF_INVERTER_MODEL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="dongle",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def _test_dongle_connection(self) -> None:
        """Test WiFi dongle TCP connection to the inverter."""
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_dongle_transport
        from pylxpweb.transports.exceptions import TransportConnectionError

        assert self._dongle_host is not None
        assert self._dongle_port is not None
        assert self._dongle_serial is not None
        assert self._inverter_serial is not None

        # Convert string family to InverterFamily enum
        inverter_family = None
        if self._inverter_family:
            try:
                inverter_family = InverterFamily(self._inverter_family)
            except ValueError:
                _LOGGER.warning(
                    "Unknown inverter family '%s', using default", self._inverter_family
                )

        transport = create_dongle_transport(
            host=self._dongle_host,
            dongle_serial=self._dongle_serial,
            inverter_serial=self._inverter_serial,
            port=self._dongle_port,
            timeout=DEFAULT_DONGLE_TIMEOUT,
            inverter_family=inverter_family,
        )

        try:
            await transport.connect()

            # Try to read runtime data to verify connection
            runtime = await transport.read_runtime()
            _LOGGER.info(
                "Dongle connection successful - PV power: %sW, Battery SOC: %s%%",
                runtime.pv_total_power,
                runtime.battery_soc,
            )
        except TransportConnectionError:
            raise
        finally:
            await transport.disconnect()

    async def _create_dongle_entry(self) -> ConfigFlowResult:
        """Create config entry for WiFi dongle connection."""
        assert self._dongle_host is not None
        assert self._dongle_port is not None
        assert self._dongle_serial is not None
        assert self._inverter_serial is not None

        # Use inverter serial as unique ID
        unique_id = f"dongle_{self._inverter_serial}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create title
        model_suffix = f" ({self._inverter_model})" if self._inverter_model else ""
        title = f"{BRAND_NAME} Dongle - {self._inverter_serial}{model_suffix}"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_DONGLE,
            CONF_DONGLE_HOST: self._dongle_host,
            CONF_DONGLE_PORT: self._dongle_port,
            CONF_DONGLE_SERIAL: self._dongle_serial,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
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
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle local transport type selection for hybrid mode.

        Allows user to choose between Modbus (RS485 adapter) or WiFi Dongle
        for local real-time data. Priority: Modbus > Dongle > Cloud-only.
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
        local_type_options = {
            HYBRID_LOCAL_MODBUS: "Modbus TCP (RS485 adapter - fastest)",
            HYBRID_LOCAL_DONGLE: "WiFi Dongle (no extra hardware)",
        }

        local_type_schema = vol.Schema(
            {
                vol.Required(
                    CONF_HYBRID_LOCAL_TYPE, default=HYBRID_LOCAL_MODBUS
                ): vol.In(local_type_options),
            }
        )

        return self.async_show_form(
            step_id="hybrid_local_type",
            data_schema=local_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_hybrid_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle configuration for hybrid mode."""
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
        inverter_serials: list[str] = []
        if self._plants and self._plant_id:
            for plant in self._plants:
                if plant["plantId"] == self._plant_id:
                    inverters = plant.get("inverters", [])
                    inverter_serials = [
                        inv.get("serialNum", "")
                        for inv in inverters
                        if inv.get("serialNum")
                    ]
                    break

        # Pre-fill first inverter serial if available
        default_serial = inverter_serials[0] if inverter_serials else ""

        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        dongle_schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL, default=default_serial): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
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

    async def async_step_hybrid_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus configuration for hybrid mode."""
        errors: dict[str, str] = {}

        # Ensure hybrid local type is set (should be set by async_step_hybrid_local_type)
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

        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Required(CONF_INVERTER_SERIAL, default=default_serial): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
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
        """Create config entry for hybrid (HTTP + local transport) connection.

        Supports both Modbus and WiFi Dongle as local transport options.
        """
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

        # Unique ID includes both account and plant
        unique_id = f"hybrid_{self._username}_{self._plant_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        title = f"{BRAND_NAME} Hybrid - {plant_name}"

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
            # Uses TransportType enum string values for direct TransportConfig creation
            local_transports.append(
                {
                    "serial": self._inverter_serial,
                    "transport_type": "modbus_tcp",  # TransportType.MODBUS_TCP.value
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
            # Uses TransportType enum string values for direct TransportConfig creation
            local_transports.append(
                {
                    "serial": self._inverter_serial,
                    "transport_type": "wifi_dongle",  # TransportType.WIFI_DONGLE.value
                    "host": self._dongle_host,
                    "port": self._dongle_port,
                    "dongle_serial": self._dongle_serial,
                    "inverter_family": self._inverter_family or DEFAULT_INVERTER_FAMILY,
                }
            )

        # Store the new format for coordinator to use with Station.attach_local_transports()
        if local_transports:
            data[CONF_LOCAL_TRANSPORTS] = local_transports

        return self.async_create_entry(title=title, data=data)

    # ==========================================================================
    # Local-only multi-device mode steps
    # ==========================================================================

    async def async_step_local_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial setup for local-only multi-device mode.

        This step collects the station name and prepares for device entry.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._station_name = user_input.get(
                CONF_STATION_NAME, DEFAULT_LOCAL_STATION_NAME
            )
            self._local_devices = []  # Reset device list

            # Proceed to add first device
            return await self.async_step_local_add_device()

        # Show station name input
        local_setup_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STATION_NAME, default=DEFAULT_LOCAL_STATION_NAME
                ): str,
            }
        )

        return self.async_show_form(
            step_id="local_setup",
            data_schema=local_setup_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_local_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a device in local-only multi-device mode.

        Users can add multiple devices (Modbus or Dongle) one at a time.
        After each device, they can add more or finish setup.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            device_type = user_input.get("device_type", "modbus")

            if device_type == "modbus":
                return await self.async_step_local_modbus_device()
            return await self.async_step_local_dongle_device()

        # Show device type selection
        device_type_schema = vol.Schema(
            {
                vol.Required("device_type", default="modbus"): vol.In(
                    {
                        "modbus": "Modbus TCP (RS485 adapter)",
                        "dongle": "WiFi Dongle (port 8000)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="local_add_device",
            data_schema=device_type_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(len(self._local_devices)),
            },
        )

    async def async_step_local_modbus_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a Modbus device in local-only mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            modbus_host = user_input[CONF_MODBUS_HOST]
            modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            modbus_unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)
            inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection and auto-detect serial if not provided
            try:
                detected_serial = await self._test_local_modbus_connection(
                    modbus_host, modbus_port, modbus_unit_id, inverter_family
                )
                final_serial = inverter_serial or detected_serial

                if not final_serial:
                    errors["base"] = "serial_not_detected"
                else:
                    # Check for duplicate serial
                    existing_serials = [d["serial"] for d in self._local_devices]
                    if final_serial in existing_serials:
                        errors["base"] = "duplicate_serial"
                    else:
                        # Add device to list
                        self._local_devices.append(
                            {
                                "serial": final_serial,
                                "transport_type": "modbus_tcp",
                                "host": modbus_host,
                                "port": modbus_port,
                                "unit_id": modbus_unit_id,
                                "inverter_family": inverter_family,
                            }
                        )
                        _LOGGER.info(
                            "Added local Modbus device: %s at %s:%d",
                            final_serial,
                            modbus_host,
                            modbus_port,
                        )
                        return await self.async_step_local_device_added()

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

        # Build Modbus device schema
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="local_modbus_device",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(len(self._local_devices)),
            },
        )

    async def async_step_local_dongle_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a WiFi Dongle device in local-only mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            dongle_host = user_input[CONF_DONGLE_HOST]
            dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input[CONF_DONGLE_SERIAL]
            inverter_serial = user_input[CONF_INVERTER_SERIAL]
            inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test dongle connection
            try:
                await self._test_local_dongle_connection(
                    dongle_host,
                    dongle_port,
                    dongle_serial,
                    inverter_serial,
                    inverter_family,
                )

                # Check for duplicate serial
                existing_serials = [d["serial"] for d in self._local_devices]
                if inverter_serial in existing_serials:
                    errors["base"] = "duplicate_serial"
                else:
                    # Add device to list
                    self._local_devices.append(
                        {
                            "serial": inverter_serial,
                            "transport_type": "wifi_dongle",
                            "host": dongle_host,
                            "port": dongle_port,
                            "dongle_serial": dongle_serial,
                            "inverter_family": inverter_family,
                        }
                    )
                    _LOGGER.info(
                        "Added local Dongle device: %s at %s:%d",
                        inverter_serial,
                        dongle_host,
                        dongle_port,
                    )
                    return await self.async_step_local_device_added()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        # Build dongle device schema
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        dongle_schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="local_dongle_device",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(len(self._local_devices)),
            },
        )

    async def async_step_local_device_added(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle decision after adding a device - add more or finish."""
        if user_input is not None:
            add_another = user_input.get("add_another", False)
            if add_another:
                return await self.async_step_local_add_device()
            # Finish and create entry
            return await self._create_local_entry()

        # Show add another / finish options
        add_another_schema = vol.Schema(
            {
                vol.Required("add_another", default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="local_device_added",
            data_schema=add_another_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(len(self._local_devices)),
                "device_serials": ", ".join([d["serial"] for d in self._local_devices]),
            },
        )

    async def _test_local_modbus_connection(
        self,
        host: str,
        port: int,
        unit_id: int,
        inverter_family: str,
    ) -> str:
        """Test Modbus connection and return detected serial number."""
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_modbus_transport
        from pylxpweb.transports.exceptions import TransportConnectionError

        # Convert string family to InverterFamily enum
        family_enum = None
        if inverter_family:
            try:
                family_enum = InverterFamily(inverter_family)
            except ValueError:
                _LOGGER.warning(
                    "Unknown inverter family '%s', using default", inverter_family
                )

        transport = create_modbus_transport(
            host=host,
            port=port,
            unit_id=unit_id,
            serial="",
            timeout=DEFAULT_MODBUS_TIMEOUT,
            inverter_family=family_enum,
        )

        detected_serial = ""
        try:
            await transport.connect()
            detected_serial = str(await transport.read_serial_number())
            _LOGGER.debug("Detected serial from Modbus: %s", detected_serial)

            # Read runtime to verify connection
            runtime = await transport.read_runtime()
            _LOGGER.info(
                "Local Modbus connection verified - Serial: %s, PV: %sW, SOC: %s%%",
                detected_serial,
                runtime.pv_total_power,
                runtime.battery_soc,
            )
        except TransportConnectionError:
            raise
        finally:
            await transport.disconnect()

        return detected_serial

    async def _test_local_dongle_connection(
        self,
        host: str,
        port: int,
        dongle_serial: str,
        inverter_serial: str,
        inverter_family: str,
    ) -> None:
        """Test WiFi dongle connection."""
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_dongle_transport
        from pylxpweb.transports.exceptions import TransportConnectionError

        # Convert string family to InverterFamily enum
        family_enum = None
        if inverter_family:
            try:
                family_enum = InverterFamily(inverter_family)
            except ValueError:
                _LOGGER.warning(
                    "Unknown inverter family '%s', using default", inverter_family
                )

        transport = create_dongle_transport(
            host=host,
            dongle_serial=dongle_serial,
            inverter_serial=inverter_serial,
            port=port,
            timeout=DEFAULT_DONGLE_TIMEOUT,
            inverter_family=family_enum,
        )

        try:
            await transport.connect()
            runtime = await transport.read_runtime()
            _LOGGER.info(
                "Local Dongle connection verified - PV: %sW, SOC: %s%%",
                runtime.pv_total_power,
                runtime.battery_soc,
            )
        except TransportConnectionError:
            raise
        finally:
            await transport.disconnect()

    async def _create_local_entry(self) -> ConfigFlowResult:
        """Create config entry for local-only multi-device mode."""
        if not self._local_devices:
            return self.async_abort(reason="no_devices_configured")

        station_name = self._station_name or DEFAULT_LOCAL_STATION_NAME

        # Create unique ID from all device serials sorted
        sorted_serials = sorted([d["serial"] for d in self._local_devices])
        unique_id = f"local_{'_'.join(sorted_serials)}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Create entry title
        device_count = len(self._local_devices)
        title = f"{BRAND_NAME} Local - {station_name} ({device_count} device{'s' if device_count > 1 else ''})"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_STATION_NAME: station_name,
            CONF_LOCAL_TRANSPORTS: self._local_devices,
        }

        return self.async_create_entry(title=title, data=data)

    # ==========================================================================
    # End of local-only multi-device mode steps
    # ==========================================================================

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
        """Handle reconfiguration flow - routes based on connection type.

        Gold tier requirement: Reconfiguration available through UI.
        """
        # Get the current entry being reconfigured
        entry_id = self.context.get("entry_id")
        assert entry_id is not None, "entry_id must be set in context"
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None, "Config entry not found"

        # Route to appropriate reconfigure flow based on connection type
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

        if connection_type == CONNECTION_TYPE_MODBUS:
            return await self.async_step_reconfigure_modbus(user_input)
        if connection_type == CONNECTION_TYPE_HYBRID:
            return await self.async_step_reconfigure_hybrid(user_input)
        # Default to HTTP reconfigure
        return await self.async_step_reconfigure_http(user_input)

    async def async_step_reconfigure_http(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP (cloud) reconfiguration flow."""
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

    async def async_step_reconfigure_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus reconfiguration flow."""
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry_id = self.context.get("entry_id")
        assert entry_id is not None, "entry_id must be set in context"
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None, "Config entry not found"

        if user_input is not None:
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection
            try:
                await self._test_modbus_connection()
                return await self._update_modbus_entry(entry)

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

        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        # Build Modbus reconfiguration schema with current values
        modbus_schema = vol.Schema(
            {
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
                vol.Required(
                    CONF_INVERTER_SERIAL,
                    default=entry.data.get(CONF_INVERTER_SERIAL, ""),
                ): str,
                vol.Optional(
                    CONF_INVERTER_MODEL,
                    default=entry.data.get(CONF_INVERTER_MODEL, ""),
                ): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY,
                    default=entry.data.get(
                        CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
                    ),
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_host": entry.data.get(CONF_MODBUS_HOST, "Unknown"),
            },
        )

    async def async_step_reconfigure_hybrid(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Hybrid reconfiguration flow - update both HTTP and Modbus settings."""
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry_id = self.context.get("entry_id")
        assert entry_id is not None, "entry_id must be set in context"
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None, "Config entry not found"

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

        # Inverter family options for register map selection
        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

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
                ): vol.In(inverter_family_options),
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
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection during hybrid reconfiguration."""
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
        self, entry: config_entries.ConfigEntry[Any], plant_id: str, plant_name: str
    ) -> ConfigFlowResult:
        """Update the HTTP config entry with new data."""
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

        # Update entry data - preserve connection type
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)

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

        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def _update_modbus_entry(
        self, entry: config_entries.ConfigEntry[Any]
    ) -> ConfigFlowResult:
        """Update the Modbus config entry with new data."""
        assert self._modbus_host is not None
        assert self._modbus_port is not None
        assert self._modbus_unit_id is not None
        assert self._inverter_serial is not None

        # Use inverter serial as unique ID
        unique_id = f"modbus_{self._inverter_serial}"

        # Check for conflicts
        existing_entry = await self.async_set_unique_id(unique_id)
        if existing_entry and existing_entry.entry_id != entry.entry_id:
            _LOGGER.warning(
                "Cannot reconfigure to serial %s - already configured",
                self._inverter_serial,
            )
            return self.async_abort(reason="already_configured")

        # Update title
        model_suffix = f" ({self._inverter_model})" if self._inverter_model else ""
        title = f"{BRAND_NAME} Modbus - {self._inverter_serial}{model_suffix}"

        data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS,
            CONF_MODBUS_HOST: self._modbus_host,
            CONF_MODBUS_PORT: self._modbus_port,
            CONF_MODBUS_UNIT_ID: self._modbus_unit_id,
            CONF_INVERTER_SERIAL: self._inverter_serial,
            CONF_INVERTER_MODEL: self._inverter_model or "",
            CONF_INVERTER_FAMILY: self._inverter_family or DEFAULT_INVERTER_FAMILY,
        }

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

    async def _update_hybrid_entry_from_reconfigure(
        self, entry: config_entries.ConfigEntry[Any], plant_id: str, plant_name: str
    ) -> ConfigFlowResult:
        """Update the Hybrid config entry with new HTTP and local transport data.

        Preserves existing local transport type or defaults to Modbus for
        backward compatibility with pre-v3.1.8 configurations.
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
        title = f"{BRAND_NAME} Hybrid - {plant_name}"

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

        # Preserve dongle settings if all required fields exist
        if CONF_DONGLE_HOST in entry.data and CONF_DONGLE_SERIAL in entry.data:
            data[CONF_DONGLE_HOST] = entry.data[CONF_DONGLE_HOST]
            data[CONF_DONGLE_PORT] = entry.data.get(
                CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT
            )
            data[CONF_DONGLE_SERIAL] = entry.data[CONF_DONGLE_SERIAL]
            # Add dongle to local_transports if it's the configured type
            # Uses TransportType enum string values for direct TransportConfig creation
            if hybrid_local_type == HYBRID_LOCAL_DONGLE:
                local_transports.append(
                    {
                        "serial": inverter_serial,
                        "transport_type": "wifi_dongle",  # TransportType.WIFI_DONGLE.value
                        "host": entry.data[CONF_DONGLE_HOST],
                        "port": entry.data.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                        "dongle_serial": entry.data[CONF_DONGLE_SERIAL],
                        "inverter_family": inverter_family,
                    }
                )

        # Store the new format for coordinator to use with Station.attach_local_transports()
        if local_transports:
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


class EG4OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for EG4 Web Monitor."""

    def __init__(self) -> None:
        """Initialize options flow."""
        # Track devices for local mode management (initialized in async_step_init)
        self._local_devices: list[dict[str, Any]] = []
        self._devices_modified = False
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure local devices are initialized from config entry."""
        if not self._initialized:
            self._local_devices = list(
                self.config_entry.data.get(CONF_LOCAL_TRANSPORTS, [])
            )
            self._initialized = True

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        # Ensure local devices are loaded from config entry
        self._ensure_initialized()

        connection_type = self.config_entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )

        # For local mode, show device management options
        if connection_type == CONNECTION_TYPE_LOCAL:
            return await self.async_step_local_options()

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Determine default sensor update interval based on connection type
        connection_type = self.config_entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )
        is_local_connection = connection_type in (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        default_sensor_interval = (
            DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
            if is_local_connection
            else DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
        )

        # Get current values from options, falling back to defaults
        current_sensor_interval = self.config_entry.options.get(
            CONF_SENSOR_UPDATE_INTERVAL, default_sensor_interval
        )
        current_param_interval = self.config_entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SENSOR_UPDATE_INTERVAL,
                    default=current_sensor_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SENSOR_UPDATE_INTERVAL,
                        max=MAX_SENSOR_UPDATE_INTERVAL,
                    ),
                ),
                vol.Required(
                    CONF_PARAMETER_REFRESH_INTERVAL,
                    default=current_param_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_PARAMETER_REFRESH_INTERVAL,
                        max=MAX_PARAMETER_REFRESH_INTERVAL,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "min_sensor_interval": str(MIN_SENSOR_UPDATE_INTERVAL),
                "max_sensor_interval": str(MAX_SENSOR_UPDATE_INTERVAL),
                "min_param_interval": str(MIN_PARAMETER_REFRESH_INTERVAL),
                "max_param_interval": str(MAX_PARAMETER_REFRESH_INTERVAL),
            },
        )

    # ==========================================================================
    # Local-only mode options
    # ==========================================================================

    async def async_step_local_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage local-only mode options."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "add_device":
                return await self.async_step_local_add_device_type()
            if action == "remove_device":
                return await self.async_step_local_remove_device()
            if action == "update_intervals":
                return await self.async_step_local_intervals()
            if action == "done":
                return await self._finish_local_options()

        # Show options menu
        device_count = len(self._local_devices)
        device_serials = ", ".join([d["serial"] for d in self._local_devices])

        options_schema = vol.Schema(
            {
                vol.Required("action", default="done"): vol.In(
                    {
                        "add_device": "Add Device",
                        "remove_device": "Remove Device",
                        "update_intervals": "Update Polling Intervals",
                        "done": "Done",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="local_options",
            data_schema=options_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
                "device_serials": device_serials or "None",
            },
        )

    async def async_step_local_add_device_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select device type to add in options flow."""
        if user_input is not None:
            device_type = user_input.get("device_type", "modbus")
            if device_type == "modbus":
                return await self.async_step_local_options_modbus()
            return await self.async_step_local_options_dongle()

        device_type_schema = vol.Schema(
            {
                vol.Required("device_type", default="modbus"): vol.In(
                    {
                        "modbus": "Modbus TCP (RS485 adapter)",
                        "dongle": "WiFi Dongle (port 8000)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="local_add_device_type",
            data_schema=device_type_schema,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_options_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a Modbus device in options flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            modbus_host = user_input[CONF_MODBUS_HOST]
            modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            modbus_unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)
            inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            try:
                # Reuse test method from config flow
                detected_serial = await self._test_modbus_connection(
                    modbus_host, modbus_port, modbus_unit_id, inverter_family
                )
                final_serial = inverter_serial or detected_serial

                if not final_serial:
                    errors["base"] = "serial_not_detected"
                else:
                    # Check for duplicate
                    existing_serials = [d["serial"] for d in self._local_devices]
                    if final_serial in existing_serials:
                        errors["base"] = "duplicate_serial"
                    else:
                        self._local_devices.append(
                            {
                                "serial": final_serial,
                                "transport_type": "modbus_tcp",
                                "host": modbus_host,
                                "port": modbus_port,
                                "unit_id": modbus_unit_id,
                                "inverter_family": inverter_family,
                            }
                        )
                        self._devices_modified = True
                        return await self.async_step_local_options()

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

        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        modbus_schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="local_options_modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_options_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a WiFi Dongle device in options flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            dongle_host = user_input[CONF_DONGLE_HOST]
            dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input[CONF_DONGLE_SERIAL]
            inverter_serial = user_input[CONF_INVERTER_SERIAL]
            inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            try:
                await self._test_dongle_connection(
                    dongle_host,
                    dongle_port,
                    dongle_serial,
                    inverter_serial,
                    inverter_family,
                )

                # Check for duplicate
                existing_serials = [d["serial"] for d in self._local_devices]
                if inverter_serial in existing_serials:
                    errors["base"] = "duplicate_serial"
                else:
                    self._local_devices.append(
                        {
                            "serial": inverter_serial,
                            "transport_type": "wifi_dongle",
                            "host": dongle_host,
                            "port": dongle_port,
                            "dongle_serial": dongle_serial,
                            "inverter_family": inverter_family,
                        }
                    )
                    self._devices_modified = True
                    return await self.async_step_local_options()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        inverter_family_options = {
            INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
            INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
            INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
        }

        dongle_schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(inverter_family_options),
            }
        )

        return self.async_show_form(
            step_id="local_options_dongle",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_remove_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a device from local station."""
        if not self._local_devices:
            return await self.async_step_local_options()

        if user_input is not None:
            serial_to_remove = user_input.get("device_serial")
            if serial_to_remove:
                self._local_devices = [
                    d for d in self._local_devices if d["serial"] != serial_to_remove
                ]
                self._devices_modified = True
            return await self.async_step_local_options()

        # Build device selection
        device_options = {
            d["serial"]: f"{d['serial']} ({d['transport_type']})"
            for d in self._local_devices
        }

        remove_schema = vol.Schema(
            {
                vol.Required("device_serial"): vol.In(device_options),
            }
        )

        return self.async_show_form(
            step_id="local_remove_device",
            data_schema=remove_schema,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update polling intervals for local mode."""
        if user_input is not None:
            # Store intervals and return to menu
            self._sensor_interval = user_input.get(
                CONF_SENSOR_UPDATE_INTERVAL, DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
            )
            self._param_interval = user_input.get(
                CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
            )
            self._devices_modified = True
            return await self.async_step_local_options()

        current_sensor = self.config_entry.options.get(
            CONF_SENSOR_UPDATE_INTERVAL, DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
        )
        current_param = self.config_entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )

        interval_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SENSOR_UPDATE_INTERVAL, default=current_sensor
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SENSOR_UPDATE_INTERVAL, max=MAX_SENSOR_UPDATE_INTERVAL
                    ),
                ),
                vol.Required(
                    CONF_PARAMETER_REFRESH_INTERVAL, default=current_param
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_PARAMETER_REFRESH_INTERVAL,
                        max=MAX_PARAMETER_REFRESH_INTERVAL,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="local_intervals",
            data_schema=interval_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "min_sensor_interval": str(MIN_SENSOR_UPDATE_INTERVAL),
                "max_sensor_interval": str(MAX_SENSOR_UPDATE_INTERVAL),
                "min_param_interval": str(MIN_PARAMETER_REFRESH_INTERVAL),
                "max_param_interval": str(MAX_PARAMETER_REFRESH_INTERVAL),
            },
        )

    async def _finish_local_options(self) -> ConfigFlowResult:
        """Finish local options and update config entry if needed."""
        if self._devices_modified:
            # Update the config entry data with modified device list
            new_data = dict(self.config_entry.data)
            new_data[CONF_LOCAL_TRANSPORTS] = self._local_devices

            # Update unique ID if device list changed
            sorted_serials = sorted([d["serial"] for d in self._local_devices])
            new_unique_id = (
                f"local_{'_'.join(sorted_serials)}" if sorted_serials else None
            )

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                unique_id=new_unique_id,
            )

            # Return options with updated intervals
            options_data = {
                CONF_SENSOR_UPDATE_INTERVAL: getattr(
                    self, "_sensor_interval", DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
                ),
                CONF_PARAMETER_REFRESH_INTERVAL: getattr(
                    self, "_param_interval", DEFAULT_PARAMETER_REFRESH_INTERVAL
                ),
            }
            return self.async_create_entry(title="", data=options_data)

        # No changes - just return current options
        return self.async_create_entry(title="", data=self.config_entry.options)

    async def _test_modbus_connection(
        self,
        host: str,
        port: int,
        unit_id: int,
        inverter_family: str,
    ) -> str:
        """Test Modbus connection and return detected serial."""
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_modbus_transport

        family_enum = None
        if inverter_family:
            try:
                family_enum = InverterFamily(inverter_family)
            except ValueError:
                pass

        transport = create_modbus_transport(
            host=host,
            port=port,
            unit_id=unit_id,
            serial="",
            timeout=DEFAULT_MODBUS_TIMEOUT,
            inverter_family=family_enum,
        )

        detected_serial = ""
        try:
            await transport.connect()
            detected_serial = str(await transport.read_serial_number())
            await transport.read_runtime()  # Verify connection
        finally:
            await transport.disconnect()

        return detected_serial

    async def _test_dongle_connection(
        self,
        host: str,
        port: int,
        dongle_serial: str,
        inverter_serial: str,
        inverter_family: str,
    ) -> None:
        """Test WiFi dongle connection."""
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_dongle_transport

        family_enum = None
        if inverter_family:
            try:
                family_enum = InverterFamily(inverter_family)
            except ValueError:
                pass

        transport = create_dongle_transport(
            host=host,
            dongle_serial=dongle_serial,
            inverter_serial=inverter_serial,
            port=port,
            timeout=DEFAULT_DONGLE_TIMEOUT,
            inverter_family=family_enum,
        )

        try:
            await transport.connect()
            await transport.read_runtime()
        finally:
            await transport.disconnect()


class CannotConnectError(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuthError(HomeAssistantError):
    """Error to indicate there is invalid auth."""
