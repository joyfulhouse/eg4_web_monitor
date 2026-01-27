"""Base class and shared logic for config flow.

This module provides the base class and Protocol for type-safe mixins.
The domain=DOMAIN parameter must be on the final assembled class, not here.
"""

import logging
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.helpers import aiohttp_client
from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import LuxpowerAPIError

from ..const import (
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_TIMEOUT,
)

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from .discovery import DiscoveredDevice
    from .transitions.http_to_hybrid import HttpToHybridBuilder
    from .transitions.hybrid_to_http import HybridToHttpBuilder

_LOGGER = logging.getLogger(__name__)


class ConfigFlowProtocol(Protocol):
    """Protocol defining the interface mixins expect from the base class.

    Mixins use this protocol for type hints, ensuring they have access to
    shared state and methods without direct inheritance from ConfigFlow.

    This protocol declares all attributes and methods that may be accessed
    across mixins, enabling proper type checking.
    """

    hass: "HomeAssistant"
    context: dict[str, Any]

    # Connection state (set during flow steps)
    _connection_type: str | None
    _username: str | None
    _password: str | None
    _base_url: str | None
    _verify_ssl: bool | None
    _dst_sync: bool | None
    _library_debug: bool | None
    _plant_id: str | None
    _plants: list[dict[str, Any]] | None

    # Modbus state
    _modbus_host: str | None
    _modbus_port: int | None
    _modbus_unit_id: int | None
    _inverter_serial: str | None
    _inverter_model: str | None
    _inverter_family: str | None

    # Dongle state
    _dongle_host: str | None
    _dongle_port: int | None
    _dongle_serial: str | None

    # Hybrid state
    _hybrid_local_type: str | None

    # Local multi-device state
    _local_station_name: str | None
    _local_devices: list[dict[str, Any]] | None

    # Pending device state (used during local onboarding/reconfigure)
    _pending_device: "DiscoveredDevice | None"
    _pending_transport_type: str | None
    _pending_host: str | None
    _pending_port: int | None
    _pending_unit_id: int | None
    _pending_dongle_serial: str | None

    # Reconfigure state
    _reconfigure_device_index: int | None

    # Transition builder state
    _transition_builder: "HttpToHybridBuilder | HybridToHttpBuilder | None"

    # ==========================================================================
    # Connection testing methods (from EG4ConfigFlowBase)
    # ==========================================================================
    async def _test_credentials(self) -> None: ...
    async def _test_modbus_connection(self) -> str: ...
    async def _test_dongle_connection(self) -> None: ...
    def _get_inverter_serials_from_plant(self) -> list[str]: ...

    # ==========================================================================
    # Discovery methods (from EG4ConfigFlowBase)
    # ==========================================================================
    async def _discover_modbus_device(
        self, host: str, port: int, unit_id: int
    ) -> "DiscoveredDevice": ...
    async def _discover_dongle_device(
        self, host: str, dongle_serial: str, inverter_serial: str, port: int
    ) -> "DiscoveredDevice": ...

    # ==========================================================================
    # ConfigFlow methods (inherited from config_entries.ConfigFlow)
    # ==========================================================================
    def async_show_form(self, **kwargs: Any) -> "ConfigFlowResult": ...
    def async_create_entry(self, **kwargs: Any) -> "ConfigFlowResult": ...
    def async_abort(self, **kwargs: Any) -> "ConfigFlowResult": ...
    async def async_set_unique_id(
        self, unique_id: str
    ) -> "config_entries.ConfigEntry | None": ...
    def _abort_if_unique_id_configured(self) -> None: ...

    # ==========================================================================
    # Entry creation methods (from onboarding mixins)
    # ==========================================================================
    async def _create_http_entry(
        self, plant_id: str, plant_name: str
    ) -> "ConfigFlowResult": ...
    async def _create_modbus_entry(self) -> "ConfigFlowResult": ...
    async def _create_dongle_entry(self) -> "ConfigFlowResult": ...
    async def _create_hybrid_entry(self) -> "ConfigFlowResult": ...
    async def _create_local_entry(self) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Entry update methods (from reconfigure mixins)
    # ==========================================================================
    async def _update_http_entry(
        self,
        entry: "config_entries.ConfigEntry[Any]",
        plant_id: str,
        plant_name: str,
    ) -> "ConfigFlowResult": ...
    async def _update_modbus_entry(
        self, entry: "config_entries.ConfigEntry[Any]"
    ) -> "ConfigFlowResult": ...
    async def _update_local_entry(
        self, entry: "config_entries.ConfigEntry[Any]"
    ) -> "ConfigFlowResult": ...
    async def _update_hybrid_entry_from_reconfigure(
        self,
        entry: "config_entries.ConfigEntry[Any]",
        plant_id: str,
        plant_name: str,
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # HTTP onboarding steps (from HttpOnboardingMixin)
    # ==========================================================================
    async def async_step_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Hybrid onboarding steps (from HybridOnboardingMixin)
    # ==========================================================================
    async def async_step_hybrid_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_hybrid_local_type(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_hybrid_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_hybrid_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Local onboarding steps (from LocalOnboardingMixin)
    # ==========================================================================
    async def async_step_local_modbus_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_local_dongle_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_local_device_discovered(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_local_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_local_name(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # HTTP reconfigure steps (from HttpReconfigureMixin)
    # ==========================================================================
    async def async_step_reconfigure_http(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_reconfigure_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Hybrid reconfigure steps (from HybridReconfigureMixin)
    # ==========================================================================
    async def async_step_reconfigure_hybrid(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_reconfigure_hybrid_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Local reconfigure steps (from LocalReconfigureMixin)
    # ==========================================================================
    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_reconfigure_local_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_reconfigure_local_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_reconfigure_local_discovered(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Reauth steps (from ReauthMixin)
    # ==========================================================================
    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...

    # ==========================================================================
    # Transition steps (from TransitionMixin)
    # ==========================================================================
    async def async_step_transition_http_to_hybrid(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...
    async def async_step_transition_hybrid_to_http(
        self, user_input: dict[str, Any] | None = None
    ) -> "ConfigFlowResult": ...


class EG4ConfigFlowBase:
    """Base config flow mixin with shared state and utilities.

    Note: This is NOT a ConfigFlow subclass. The domain=DOMAIN parameter
    must be on the final assembled class (EG4WebMonitorConfigFlow), not here.
    This class provides shared state and methods that mixins can use.

    All instance variables are declared here so mixins can access them.
    """

    # Type hints for Home Assistant attributes (set by ConfigFlow)
    hass: "HomeAssistant"
    context: dict[str, Any]

    def __init__(self) -> None:
        """Initialize shared state for config flow."""
        super().__init__()

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

        # Local multi-device mode fields
        self._local_station_name: str | None = None
        # Initialize to None so reconfigure can detect if it needs to load from entry
        self._local_devices: list[dict[str, Any]] | None = None

        # Pending device state (used during local onboarding flow)
        # Type is DiscoveredDevice | None but we use Any at runtime
        self._pending_device: Any = None
        self._pending_transport_type: str | None = None
        self._pending_host: str | None = None
        self._pending_port: int | None = None
        self._pending_unit_id: int | None = None
        self._pending_dongle_serial: str | None = None

        # Reconfigure state (used during local reconfigure flow)
        self._reconfigure_device_index: int | None = None

        # Transition builder state (used during connection type transitions)
        self._transition_builder: Any = None

    async def _test_credentials(self) -> None:
        """Test if we can authenticate with the given credentials.

        Stores the list of plants/stations in self._plants on success.

        Raises:
            LuxpowerAuthError: If authentication fails.
            LuxpowerConnectionError: If connection fails.
            LuxpowerAPIError: If no plants found or other API error.
        """
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

    async def _test_modbus_connection(self) -> str:
        """Test Modbus TCP connection and read serial number.

        Returns:
            The inverter serial number read from Modbus registers.

        Raises:
            ImportError: If pymodbus is not installed.
            TimeoutError: If connection times out.
            OSError: If connection fails.
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

    async def _test_dongle_connection(self) -> None:
        """Test WiFi dongle TCP connection to the inverter.

        Raises:
            TimeoutError: If connection times out.
            OSError: If connection fails.
        """
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

    def _get_inverter_serials_from_plant(self) -> list[str]:
        """Get inverter serials from the currently selected plant.

        Returns:
            List of inverter serial numbers, or empty list if none found.
        """
        if not self._plants or not self._plant_id:
            return []

        for plant in self._plants:
            if plant["plantId"] == self._plant_id:
                inverters = plant.get("inverters", [])
                return [
                    inv.get("serialNum", "")
                    for inv in inverters
                    if inv.get("serialNum")
                ]

        return []

    def _get_default_inverter_family(self) -> str:
        """Get the default inverter family.

        Returns:
            Default inverter family constant.
        """
        return DEFAULT_INVERTER_FAMILY

    async def _discover_modbus_device(
        self,
        host: str,
        port: int,
        unit_id: int,
    ) -> "DiscoveredDevice":
        """Connect to Modbus TCP and auto-detect device information.

        Args:
            host: IP address of the Modbus TCP gateway.
            port: TCP port.
            unit_id: Modbus unit/slave ID.

        Returns:
            DiscoveredDevice with all auto-detected information.

        Raises:
            TimeoutError: If connection times out.
            OSError: If connection fails.
            Exception: If device discovery fails.
        """
        from .discovery import discover_modbus_device

        return await discover_modbus_device(
            host=host,
            port=port,
            unit_id=unit_id,
        )

    async def _discover_dongle_device(
        self,
        host: str,
        dongle_serial: str,
        inverter_serial: str,
        port: int,
    ) -> "DiscoveredDevice":
        """Connect to WiFi dongle and auto-detect device information.

        Args:
            host: IP address of the WiFi dongle.
            dongle_serial: Serial number printed on the dongle.
            inverter_serial: Serial number of the inverter (required for auth).
            port: TCP port.

        Returns:
            DiscoveredDevice with all auto-detected information.

        Raises:
            TimeoutError: If connection times out.
            OSError: If connection fails.
            Exception: If device discovery fails.
        """
        from .discovery import discover_dongle_device

        return await discover_dongle_device(
            host=host,
            dongle_serial=dongle_serial,
            inverter_serial=inverter_serial,
            port=port,
        )
