"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import aiohttp_client
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )

    from pylxpweb.transports import ModbusTransport
else:
    from homeassistant.helpers.update_coordinator import (  # type: ignore[assignment]
        DataUpdateCoordinator,
        UpdateFailed,
    )

from pylxpweb import LuxpowerClient
from pylxpweb.devices import Battery, Station
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
    LuxpowerDeviceError,
)

from .const import (
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
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_PLANT_ID,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_DONGLE_PORT,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    DOMAIN,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_DEFAULT_MODELS,
)
from .coordinator_mixins import (
    BackgroundTaskMixin,
    DeviceInfoMixin,
    DeviceProcessingMixin,
    DSTSyncMixin,
    FirmwareUpdateMixin,
    ParameterManagementMixin,
)
from .utils import (
    CircuitBreaker,
    clean_battery_display_name,
)

_LOGGER = logging.getLogger(__name__)


def _build_runtime_sensor_mapping(runtime_data: Any) -> dict[str, Any]:
    """Build sensor mapping from runtime data object.

    This helper extracts runtime data from a transport's RuntimeData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Args:
        runtime_data: RuntimeData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # PV/Solar input
        "pv1_voltage": runtime_data.pv1_voltage,
        "pv1_power": runtime_data.pv1_power,
        "pv2_voltage": runtime_data.pv2_voltage,
        "pv2_power": runtime_data.pv2_power,
        "pv3_voltage": runtime_data.pv3_voltage,
        "pv3_power": runtime_data.pv3_power,
        "pv_total_power": runtime_data.pv_total_power,
        # Battery
        "battery_voltage": runtime_data.battery_voltage,
        "battery_current": runtime_data.battery_current,
        "state_of_charge": runtime_data.battery_soc,
        "battery_charge_power": runtime_data.battery_charge_power,
        "battery_discharge_power": runtime_data.battery_discharge_power,
        "battery_temperature": runtime_data.battery_temperature,
        # Grid - all phases
        "grid_voltage_r": runtime_data.grid_voltage_r,
        "grid_voltage_s": runtime_data.grid_voltage_s,
        "grid_voltage_t": runtime_data.grid_voltage_t,
        "grid_current_l1": runtime_data.grid_current_r,
        "grid_current_l2": runtime_data.grid_current_s,
        "grid_current_l3": runtime_data.grid_current_t,
        "grid_frequency": runtime_data.grid_frequency,
        "grid_power": runtime_data.grid_power,
        "grid_export_power": runtime_data.power_to_grid,
        # Inverter output
        "ac_power": runtime_data.inverter_power,
        "load_power": runtime_data.load_power,
        # EPS/Backup
        "eps_voltage_r": runtime_data.eps_voltage_r,
        "eps_voltage_s": runtime_data.eps_voltage_s,
        "eps_voltage_t": runtime_data.eps_voltage_t,
        "eps_frequency": runtime_data.eps_frequency,
        "eps_power": runtime_data.eps_power,
        # Generator
        "generator_voltage": runtime_data.generator_voltage,
        "generator_frequency": runtime_data.generator_frequency,
        "generator_power": runtime_data.generator_power,
        # Bus voltages
        "bus1_voltage": runtime_data.bus_voltage_1,
        "bus2_voltage": runtime_data.bus_voltage_2,
        # Temperatures
        "internal_temperature": runtime_data.internal_temperature,
        "radiator1_temperature": runtime_data.radiator_temperature_1,
        "radiator2_temperature": runtime_data.radiator_temperature_2,
        # Status
        "status_code": runtime_data.device_status,
    }


def _build_energy_sensor_mapping(energy_data: Any) -> dict[str, Any]:
    """Build sensor mapping from energy data object.

    This helper extracts energy data from a transport's EnergyData object
    and maps it to sensor keys matching SENSOR_TYPES definitions in const.py.

    Args:
        energy_data: EnergyData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # Daily energy (kWh)
        "yield": energy_data.pv_energy_today,
        "charging": energy_data.charge_energy_today,
        "discharging": energy_data.discharge_energy_today,
        "grid_import": energy_data.grid_import_today,
        "grid_export": energy_data.grid_export_today,
        "load": energy_data.load_energy_today,
        # Lifetime energy (kWh)
        "yield_lifetime": energy_data.pv_energy_total,
        "charging_lifetime": energy_data.charge_energy_total,
        "discharging_lifetime": energy_data.discharge_energy_total,
        "grid_import_lifetime": energy_data.grid_import_total,
        "grid_export_lifetime": energy_data.grid_export_total,
        "load_lifetime": energy_data.load_energy_total,
    }


def _build_battery_bank_sensor_mapping(battery_data: Any) -> dict[str, Any]:
    """Build sensor mapping from battery bank data object.

    Args:
        battery_data: BatteryData object from pylxpweb transport.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        "battery_bank_soc": battery_data.soc,
        "battery_bank_voltage": battery_data.voltage,
        "battery_bank_charge_power": battery_data.charge_power,
        "battery_bank_discharge_power": battery_data.discharge_power,
    }


def _build_gridboss_sensor_mapping(mid_device: Any) -> dict[str, Any]:
    """Build sensor mapping from MIDDevice object for GridBOSS.

    This helper extracts data from a MIDDevice's runtime properties
    and maps it to sensor keys matching SENSOR_TYPES definitions.

    Args:
        mid_device: MIDDevice object from pylxpweb with runtime data.

    Returns:
        Dictionary mapping sensor keys to values.
    """
    return {
        # Grid sensors
        "grid_power": getattr(mid_device, "grid_power", None),
        "grid_voltage": getattr(mid_device, "grid_voltage", None),
        "frequency": getattr(mid_device, "grid_frequency", None),
        "grid_power_l1": getattr(mid_device, "grid_l1_power", None),
        "grid_power_l2": getattr(mid_device, "grid_l2_power", None),
        "grid_voltage_l1": getattr(mid_device, "grid_l1_voltage", None),
        "grid_voltage_l2": getattr(mid_device, "grid_l2_voltage", None),
        "grid_current_l1": getattr(mid_device, "grid_l1_current", None),
        "grid_current_l2": getattr(mid_device, "grid_l2_current", None),
        # UPS sensors
        "ups_power": getattr(mid_device, "ups_power", None),
        "ups_voltage": getattr(mid_device, "ups_voltage", None),
        "ups_power_l1": getattr(mid_device, "ups_l1_power", None),
        "ups_power_l2": getattr(mid_device, "ups_l2_power", None),
        "load_voltage_l1": getattr(mid_device, "ups_l1_voltage", None),
        "load_voltage_l2": getattr(mid_device, "ups_l2_voltage", None),
        "ups_current_l1": getattr(mid_device, "ups_l1_current", None),
        "ups_current_l2": getattr(mid_device, "ups_l2_current", None),
        # Load sensors
        "load_power": getattr(mid_device, "load_power", None),
        "load_power_l1": getattr(mid_device, "load_l1_power", None),
        "load_power_l2": getattr(mid_device, "load_l2_power", None),
        "load_current_l1": getattr(mid_device, "load_l1_current", None),
        "load_current_l2": getattr(mid_device, "load_l2_current", None),
        # Generator sensors
        "generator_power": getattr(mid_device, "generator_power", None),
        "generator_voltage": getattr(mid_device, "generator_voltage", None),
        "generator_frequency": getattr(mid_device, "generator_frequency", None),
        "generator_power_l1": getattr(mid_device, "generator_l1_power", None),
        "generator_power_l2": getattr(mid_device, "generator_l2_power", None),
        "generator_current_l1": getattr(mid_device, "generator_l1_current", None),
        "generator_current_l2": getattr(mid_device, "generator_l2_current", None),
        # Other sensors
        "hybrid_power": getattr(mid_device, "hybrid_power", None),
        "phase_lock_frequency": getattr(mid_device, "phase_lock_frequency", None),
        "off_grid": getattr(mid_device, "is_off_grid", None),
        # Smart port status
        "smart_port1_status": getattr(mid_device, "smart_port1_status", None),
        "smart_port2_status": getattr(mid_device, "smart_port2_status", None),
        "smart_port3_status": getattr(mid_device, "smart_port3_status", None),
        "smart_port4_status": getattr(mid_device, "smart_port4_status", None),
        # Smart load power (L1/L2)
        "smart_load1_power_l1": getattr(mid_device, "smart_load1_l1_power", None),
        "smart_load1_power_l2": getattr(mid_device, "smart_load1_l2_power", None),
        "smart_load2_power_l1": getattr(mid_device, "smart_load2_l1_power", None),
        "smart_load2_power_l2": getattr(mid_device, "smart_load2_l2_power", None),
        "smart_load3_power_l1": getattr(mid_device, "smart_load3_l1_power", None),
        "smart_load3_power_l2": getattr(mid_device, "smart_load3_l2_power", None),
        "smart_load4_power_l1": getattr(mid_device, "smart_load4_l1_power", None),
        "smart_load4_power_l2": getattr(mid_device, "smart_load4_l2_power", None),
        # AC couple power (L1/L2)
        "ac_couple1_power_l1": getattr(mid_device, "ac_couple1_l1_power", None),
        "ac_couple1_power_l2": getattr(mid_device, "ac_couple1_l2_power", None),
        "ac_couple2_power_l1": getattr(mid_device, "ac_couple2_l1_power", None),
        "ac_couple2_power_l2": getattr(mid_device, "ac_couple2_l2_power", None),
        "ac_couple3_power_l1": getattr(mid_device, "ac_couple3_l1_power", None),
        "ac_couple3_power_l2": getattr(mid_device, "ac_couple3_l2_power", None),
        "ac_couple4_power_l1": getattr(mid_device, "ac_couple4_l1_power", None),
        "ac_couple4_power_l2": getattr(mid_device, "ac_couple4_l2_power", None),
        # Energy sensors - aggregate only (L2 energy registers always read 0)
        "ups_today": getattr(mid_device, "e_ups_today", None),
        "ups_total": getattr(mid_device, "e_ups_total", None),
        "grid_export_today": getattr(mid_device, "e_to_grid_today", None),
        "grid_export_total": getattr(mid_device, "e_to_grid_total", None),
        "grid_import_today": getattr(mid_device, "e_to_user_today", None),
        "grid_import_total": getattr(mid_device, "e_to_user_total", None),
        "load_today": getattr(mid_device, "e_load_today", None),
        "load_total": getattr(mid_device, "e_load_total", None),
    }


def _build_transport_configs(
    config_list: list[dict[str, Any]],
) -> list[Any]:
    """Convert stored config dicts to TransportConfig objects.

    Args:
        config_list: List of transport config dicts from CONF_LOCAL_TRANSPORTS.
            Each dict should have: serial, transport_type, host, port, and
            type-specific fields (unit_id for modbus, dongle_serial for dongle).

    Returns:
        List of TransportConfig objects ready for Station.attach_local_transports().
    """
    from pylxpweb.devices.inverters._features import InverterFamily
    from pylxpweb.transports.config import TransportConfig, TransportType

    configs = []
    for item in config_list:
        try:
            transport_type_str = item.get("transport_type", "modbus_tcp")
            transport_type = TransportType(transport_type_str)

            # Convert inverter family string to enum
            inverter_family = None
            family_str = item.get("inverter_family")
            if family_str:
                try:
                    inverter_family = InverterFamily(family_str)
                except ValueError:
                    _LOGGER.warning(
                        "Unknown inverter family '%s', using default", family_str
                    )

            # Build type-specific kwargs
            extra_kwargs: dict[str, Any] = {}
            if transport_type == TransportType.MODBUS_TCP:
                extra_kwargs["unit_id"] = item.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
            elif transport_type == TransportType.WIFI_DONGLE:
                extra_kwargs["dongle_serial"] = item.get("dongle_serial", "")

            config = TransportConfig(
                host=item["host"],
                port=item["port"],
                serial=item["serial"],
                transport_type=transport_type,
                inverter_family=inverter_family,
                **extra_kwargs,
            )

            configs.append(config)
            _LOGGER.debug(
                "Built TransportConfig for %s: type=%s, host=%s:%d",
                item["serial"],
                transport_type_str,
                item["host"],
                item["port"],
            )

        except (KeyError, ValueError) as err:
            _LOGGER.warning("Failed to build TransportConfig from %s: %s", item, err)
            continue

    return configs


class EG4DataUpdateCoordinator(
    DeviceProcessingMixin,
    DeviceInfoMixin,
    ParameterManagementMixin,
    DSTSyncMixin,
    BackgroundTaskMixin,
    FirmwareUpdateMixin,
    DataUpdateCoordinator[dict[str, Any]],
):
    """Class to manage fetching EG4 Web Monitor data from the API using device objects.

    This coordinator inherits from several mixins to separate concerns:
    - DeviceProcessingMixin: Processing inverters, batteries, MID devices, parallel groups
    - DeviceInfoMixin: Device info retrieval methods
    - ParameterManagementMixin: Parameter refresh operations
    - DSTSyncMixin: Daylight saving time synchronization
    - BackgroundTaskMixin: Background task management
    - FirmwareUpdateMixin: Firmware update information extraction
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry

        # Determine connection type (default to HTTP for backwards compatibility)
        self.connection_type: str = entry.data.get(
            CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP
        )

        # Plant ID (only used for HTTP and Hybrid modes)
        self.plant_id: str | None = entry.data.get(CONF_PLANT_ID)

        # Get Home Assistant timezone as IANA timezone string for DST detection
        iana_timezone = str(hass.config.time_zone) if hass.config.time_zone else None

        # Initialize HTTP client for HTTP and Hybrid modes
        self.client: LuxpowerClient | None = None
        if self.connection_type in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID):
            self.client = LuxpowerClient(
                username=entry.data[CONF_USERNAME],
                password=entry.data[CONF_PASSWORD],
                base_url=entry.data.get(
                    CONF_BASE_URL, "https://monitor.eg4electronics.com"
                ),
                verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
                session=aiohttp_client.async_get_clientsession(hass),
                iana_timezone=iana_timezone,
            )

        # Determine hybrid local transport type (modbus > dongle priority)
        # For hybrid mode, check which local transport is configured
        self._hybrid_local_type: str | None = None
        if self.connection_type == CONNECTION_TYPE_HYBRID:
            self._hybrid_local_type = entry.data.get(
                CONF_HYBRID_LOCAL_TYPE, HYBRID_LOCAL_MODBUS
            )

        # Initialize Modbus transport for Modbus mode or Hybrid with Modbus local
        self._modbus_transport: ModbusTransport | None = None
        should_init_modbus = self.connection_type == CONNECTION_TYPE_MODBUS or (
            self.connection_type == CONNECTION_TYPE_HYBRID
            and self._hybrid_local_type == HYBRID_LOCAL_MODBUS
        )
        if should_init_modbus:
            from pylxpweb.devices.inverters._features import InverterFamily
            from pylxpweb.transports import create_modbus_transport

            # Convert string family to InverterFamily enum
            inverter_family = None
            family_str = entry.data.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY)
            if family_str:
                try:
                    inverter_family = InverterFamily(family_str)
                except ValueError:
                    _LOGGER.warning(
                        "Unknown inverter family '%s', using default", family_str
                    )

            self._modbus_transport = create_modbus_transport(
                host=entry.data[CONF_MODBUS_HOST],
                port=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                unit_id=entry.data.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                timeout=DEFAULT_MODBUS_TIMEOUT,
                inverter_family=inverter_family,
            )
            self._modbus_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
            # Get model from config, or derive from family for entity compatibility
            config_model = entry.data.get(CONF_INVERTER_MODEL, "")
            if config_model:
                self._modbus_model = config_model
            else:
                # Use family to derive default model for SUPPORTED_INVERTER_MODELS check
                self._modbus_model = INVERTER_FAMILY_DEFAULT_MODELS.get(
                    family_str, "18kPV"
                )

        # Initialize Dongle transport for Dongle mode or Hybrid with Dongle local
        self._dongle_transport: Any = None
        should_init_dongle = self.connection_type == CONNECTION_TYPE_DONGLE or (
            self.connection_type == CONNECTION_TYPE_HYBRID
            and self._hybrid_local_type == HYBRID_LOCAL_DONGLE
        )
        if should_init_dongle:
            from pylxpweb.devices.inverters._features import InverterFamily
            from pylxpweb.transports import create_dongle_transport

            # Convert string family to InverterFamily enum
            inverter_family = None
            family_str = entry.data.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY)
            if family_str:
                try:
                    inverter_family = InverterFamily(family_str)
                except ValueError:
                    _LOGGER.warning(
                        "Unknown inverter family '%s', using default", family_str
                    )

            self._dongle_transport = create_dongle_transport(
                host=entry.data[CONF_DONGLE_HOST],
                dongle_serial=entry.data[CONF_DONGLE_SERIAL],
                inverter_serial=entry.data.get(CONF_INVERTER_SERIAL, ""),
                port=entry.data.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                timeout=DEFAULT_DONGLE_TIMEOUT,
                inverter_family=inverter_family,
            )
            self._dongle_serial = entry.data.get(CONF_INVERTER_SERIAL, "")
            # Get model from config, or derive from family for entity compatibility
            config_model = entry.data.get(CONF_INVERTER_MODEL, "")
            if config_model:
                self._dongle_model = config_model
            else:
                # Use family to derive default model for SUPPORTED_INVERTER_MODELS check
                self._dongle_model = INVERTER_FAMILY_DEFAULT_MODELS.get(
                    family_str, "18kPV"
                )

        # DST sync configuration (only for HTTP/Hybrid)
        self.dst_sync_enabled = entry.data.get(CONF_DST_SYNC, True)

        # Station object for device hierarchy (HTTP/Hybrid only)
        self.station: Station | None = None

        # Local transport configs for hybrid mode (new format from CONF_LOCAL_TRANSPORTS)
        # When present, these will be used with Station.attach_local_transports()
        self._local_transport_configs: list[dict[str, Any]] = entry.data.get(
            CONF_LOCAL_TRANSPORTS, []
        )
        self._local_transports_attached = False

        # Device tracking
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_sensors: dict[str, list[str]] = {}

        # Parameter refresh tracking - read from options or use default
        self._last_parameter_refresh: datetime | None = None
        param_refresh_minutes = entry.options.get(
            CONF_PARAMETER_REFRESH_INTERVAL, DEFAULT_PARAMETER_REFRESH_INTERVAL
        )
        self._parameter_refresh_interval = timedelta(minutes=param_refresh_minutes)

        # DST sync tracking
        self._last_dst_sync: datetime | None = None
        self._dst_sync_interval = timedelta(hours=1)

        # Background task tracking for proper cleanup
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Circuit breaker for API resilience
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)

        # Temporary device info storage for model extraction
        self._temp_device_info: dict[str, Any] = {}

        # Individual energy processing queue
        self._pending_individual_energy_serials: list[str] = []

        # Track availability state for Silver tier logging requirement
        self._last_available_state: bool = True

        # Inverter lookup cache for O(1) access (rebuilt when station loads)
        self._inverter_cache: dict[str, BaseInverter] = {}

        # MID device (GridBOSS) cache for LOCAL mode
        self._mid_device_cache: dict[str, Any] = {}

        # Semaphore to limit concurrent API calls and prevent rate limiting
        self._api_semaphore = asyncio.Semaphore(3)

        # Determine update interval - read from options or use connection-type default
        # Modbus, Dongle, Hybrid, and Local can poll faster since they use local network
        is_local_connection = self.connection_type in (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        default_interval = (
            DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL
            if is_local_connection
            else DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
        )
        sensor_interval_seconds = entry.options.get(
            CONF_SENSOR_UPDATE_INTERVAL, default_interval
        )
        update_interval = timedelta(seconds=sensor_interval_seconds)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

        # Register shutdown listener to cancel background tasks on Home Assistant stop
        self._shutdown_listener_remove = hass.bus.async_listen_once(
            "homeassistant_stop", self._async_handle_shutdown
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from appropriate transport based on connection type.

        This is the main data update method called by Home Assistant's coordinator
        at regular intervals.

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If connection or API errors occur.
        """
        if self.connection_type == CONNECTION_TYPE_MODBUS:
            return await self._async_update_modbus_data()
        if self.connection_type == CONNECTION_TYPE_DONGLE:
            return await self._async_update_dongle_data()
        if self.connection_type == CONNECTION_TYPE_HYBRID:
            return await self._async_update_hybrid_data()
        if self.connection_type == CONNECTION_TYPE_LOCAL:
            return await self._async_update_local_data()
        # Default to HTTP
        return await self._async_update_http_data()

    async def _read_modbus_parameters(self, transport: Any) -> dict[str, Any]:
        """Read configuration parameters from Modbus holding registers.

        Reads key holding registers and extracts bit fields to match
        the same parameter format returned by the HTTP API.

        Args:
            transport: ModbusTransport or DongleTransport instance

        Returns:
            Dictionary of parameter keys to values matching HTTP API format
        """
        params: dict[str, Any] = {}

        try:
            # Read function enable register (21) - contains multiple bit fields
            func_regs = await transport.read_parameters(21, 1)
            if 21 in func_regs:
                func_en = func_regs[21]
                # Extract bit fields from register 21
                params["FUNC_EPS_EN"] = bool(func_en & (1 << 0))
                params["FUNC_AC_CHARGE"] = bool(func_en & (1 << 7))
                params["FUNC_SET_TO_STANDBY"] = bool(func_en & (1 << 9))
                params["FUNC_FORCED_DISCHG_EN"] = bool(func_en & (1 << 10))
                params["FUNC_FORCED_CHG_EN"] = bool(func_en & (1 << 11))

            # Read AC charge settings (registers 66-73)
            ac_regs = await transport.read_parameters(66, 8)
            if ac_regs:
                params["HOLD_AC_CHARGE_POWER_CMD"] = ac_regs.get(66, 0)
                params["HOLD_AC_CHARGE_SOC_LIMIT"] = ac_regs.get(67, 0)
                params["HOLD_AC_CHARGE_START_HOUR_1"] = ac_regs.get(68, 0)
                params["HOLD_AC_CHARGE_START_MIN_1"] = ac_regs.get(69, 0)
                params["HOLD_AC_CHARGE_END_HOUR_1"] = ac_regs.get(70, 0)
                params["HOLD_AC_CHARGE_END_MIN_1"] = ac_regs.get(71, 0)
                params["HOLD_AC_CHARGE_ENABLE_1"] = ac_regs.get(72, 0)
                params["HOLD_AC_CHARGE_ENABLE_2"] = ac_regs.get(73, 0)

            # Read discharge settings (registers 74-79)
            dischg_regs = await transport.read_parameters(74, 6)
            if dischg_regs:
                params["HOLD_DISCHG_POWER_CMD"] = dischg_regs.get(74, 0)
                params["HOLD_DISCHG_START_HOUR_1"] = dischg_regs.get(75, 0)
                params["HOLD_DISCHG_START_MIN_1"] = dischg_regs.get(76, 0)
                params["HOLD_DISCHG_END_HOUR_1"] = dischg_regs.get(77, 0)
                params["HOLD_DISCHG_END_MIN_1"] = dischg_regs.get(78, 0)
                params["HOLD_DISCHG_ENABLE_1"] = dischg_regs.get(79, 0)

            # Read SOC limit settings (registers 105-106)
            soc_regs = await transport.read_parameters(105, 2)
            if soc_regs:
                params["HOLD_DISCHG_CUT_OFF_SOC_EOD"] = soc_regs.get(105, 0)
                params["HOLD_SOC_LOW_LIMIT_EPS_DISCHG"] = soc_regs.get(106, 0)

            # Read system function register (110) - additional bit fields
            sys_regs = await transport.read_parameters(110, 1)
            if 110 in sys_regs:
                sys_func = sys_regs[110]
                params["FUNC_PV_GRID_OFF_EN"] = bool(sys_func & (1 << 0))
                params["FUNC_RUN_WITHOUT_GRID"] = bool(sys_func & (1 << 1))
                params["FUNC_MICRO_GRID_EN"] = bool(sys_func & (1 << 2))
                params["FUNC_BAT_SHARED"] = bool(sys_func & (1 << 3))
                params["FUNC_CHARGE_LAST"] = bool(sys_func & (1 << 4))
                params["FUNC_BUZZER_EN"] = bool(sys_func & (1 << 5))
                params["FUNC_GREEN_EN"] = bool(sys_func & (1 << 8))
                params["FUNC_BATTERY_ECO_EN"] = bool(sys_func & (1 << 9))

            _LOGGER.debug("Read %d parameters from Modbus registers", len(params))

        except Exception as err:
            _LOGGER.warning("Failed to read parameters from Modbus: %s", err)

        return params

    async def _async_update_modbus_data(self) -> dict[str, Any]:
        """Fetch data from local Modbus transport using BaseInverter factory.

        This method creates a BaseInverter via from_modbus_transport() factory,
        which enables control operations and provides a consistent data access
        pattern regardless of transport type.

        Returns:
            Dictionary containing device data from Modbus registers.
        """
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        if self._modbus_transport is None:
            raise UpdateFailed("Modbus transport not initialized")

        try:
            serial = self._modbus_serial
            _LOGGER.debug("Fetching Modbus data for inverter %s", serial)

            # Ensure transport is connected
            if not self._modbus_transport.is_connected:
                await self._modbus_transport.connect()

            # Create or reuse BaseInverter via factory
            # This enables control operations and consistent property access
            if serial not in self._inverter_cache:
                _LOGGER.debug(
                    "Creating BaseInverter from Modbus transport for %s", serial
                )
                inverter = await BaseInverter.from_modbus_transport(
                    self._modbus_transport,
                    model=self._modbus_model,
                )
                self._inverter_cache[serial] = inverter
            else:
                inverter = self._inverter_cache[serial]

            # Refresh data from transport (populates _transport_runtime, etc.)
            await inverter.refresh(force=True, include_parameters=True)

            # Read firmware version from holding registers 7-10
            firmware_version = await self._modbus_transport.read_firmware_version()
            if not firmware_version:
                firmware_version = "Unknown"

            # Get data from transport via inverter's internal storage
            runtime_data = inverter._transport_runtime
            energy_data = inverter._transport_energy

            if runtime_data is None:
                raise TransportReadError("Failed to read runtime data from Modbus")

            # Build device data structure from inverter data
            processed = {
                "plant_id": None,  # No plant for Modbus-only
                "devices": {},
                "device_info": {},
                "last_update": dt_util.utcnow(),
                "connection_type": CONNECTION_TYPE_MODBUS,
            }

            # Create device entry with sensor mappings
            device_data: dict[str, Any] = {
                "type": "inverter",
                "model": self._modbus_model,
                "serial": serial,
                "firmware_version": firmware_version,
                "sensors": _build_runtime_sensor_mapping(runtime_data),
                "batteries": {},
            }

            # Add energy sensors if available
            if energy_data:
                device_data["sensors"].update(_build_energy_sensor_mapping(energy_data))

            # Add battery bank data if available
            battery_data = inverter._transport_battery
            if battery_data:
                device_data["sensors"].update(
                    _build_battery_bank_sensor_mapping(battery_data)
                )

            # Add firmware version as diagnostic sensor
            device_data["sensors"]["firmware_version"] = firmware_version

            processed["devices"][serial] = device_data

            # Get parameters from inverter's cached parameters
            param_data = inverter.parameters or {}
            processed["parameters"] = {serial: param_data}

            # Silver tier logging
            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 Modbus connection restored for inverter %s",
                    self._modbus_serial,
                )
                self._last_available_state = True

            _LOGGER.debug(
                "Modbus update complete - FW: %s, PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                firmware_version,
                runtime_data.pv_total_power,
                runtime_data.battery_soc,
                runtime_data.grid_power,
            )

            return processed

        except TransportConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus connection lost for inverter %s: %s",
                    self._modbus_serial,
                    e,
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus connection failed: {e}") from e

        except TransportTimeoutError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus timeout for inverter %s: %s", self._modbus_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus timeout: {e}") from e

        except (TransportReadError, TransportError) as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Modbus read error for inverter %s: %s", self._modbus_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Modbus read error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Unexpected Modbus error for inverter %s: %s",
                    self._modbus_serial,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected Modbus error: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _async_update_dongle_data(self) -> dict[str, Any]:
        """Fetch data from local WiFi dongle transport using BaseInverter factory.

        This method creates a BaseInverter via from_modbus_transport() factory,
        which enables control operations and provides a consistent data access
        pattern regardless of transport type.

        Returns:
            Dictionary containing device data from dongle registers.
        """
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        if self._dongle_transport is None:
            raise UpdateFailed("Dongle transport not initialized")

        try:
            serial = self._dongle_serial
            _LOGGER.debug("Fetching dongle data for inverter %s", serial)

            # Ensure transport is connected
            if not self._dongle_transport.is_connected:
                await self._dongle_transport.connect()

            # Create or reuse BaseInverter via factory
            # This enables control operations and consistent property access
            if serial not in self._inverter_cache:
                _LOGGER.debug(
                    "Creating BaseInverter from dongle transport for %s", serial
                )
                inverter = await BaseInverter.from_modbus_transport(
                    self._dongle_transport,
                    model=self._dongle_model,
                )
                self._inverter_cache[serial] = inverter
            else:
                inverter = self._inverter_cache[serial]

            # Refresh data from transport (populates _transport_runtime, etc.)
            await inverter.refresh(force=True, include_parameters=True)

            # Read firmware version from holding registers 7-10
            firmware_version = await self._dongle_transport.read_firmware_version()
            if not firmware_version:
                firmware_version = "Unknown"

            # Get data from transport via inverter's internal storage
            runtime_data = inverter._transport_runtime
            energy_data = inverter._transport_energy

            if runtime_data is None:
                raise TransportReadError("Failed to read runtime data from dongle")

            # Build device data structure from inverter data
            processed = {
                "plant_id": None,  # No plant for Dongle-only
                "devices": {},
                "device_info": {},
                "last_update": dt_util.utcnow(),
                "connection_type": CONNECTION_TYPE_DONGLE,
            }

            # Create device entry with sensor mappings
            device_data: dict[str, Any] = {
                "type": "inverter",
                "model": self._dongle_model,
                "serial": serial,
                "firmware_version": firmware_version,
                "sensors": _build_runtime_sensor_mapping(runtime_data),
                "batteries": {},
            }

            # Add energy sensors if available
            if energy_data:
                device_data["sensors"].update(_build_energy_sensor_mapping(energy_data))

            # Add battery bank data if available
            battery_data = inverter._transport_battery
            if battery_data:
                device_data["sensors"].update(
                    _build_battery_bank_sensor_mapping(battery_data)
                )

            # Add firmware version as diagnostic sensor
            device_data["sensors"]["firmware_version"] = firmware_version

            processed["devices"][serial] = device_data

            # Get parameters from inverter's cached parameters
            param_data = inverter.parameters or {}
            processed["parameters"] = {serial: param_data}

            # Silver tier logging
            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 Dongle connection restored for inverter %s",
                    self._dongle_serial,
                )
                self._last_available_state = True

            _LOGGER.debug(
                "Dongle update complete - FW: %s, PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                firmware_version,
                runtime_data.pv_total_power,
                runtime_data.battery_soc,
                runtime_data.grid_power,
            )

            return processed

        except TransportConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle connection lost for inverter %s: %s",
                    self._dongle_serial,
                    e,
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle connection failed: {e}") from e

        except TransportTimeoutError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle timeout for inverter %s: %s", self._dongle_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle timeout: {e}") from e

        except (TransportReadError, TransportError) as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Dongle read error for inverter %s: %s", self._dongle_serial, e
                )
                self._last_available_state = False
            raise UpdateFailed(f"Dongle read error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "Unexpected Dongle error for inverter %s: %s",
                    self._dongle_serial,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected Dongle error: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _async_update_local_data(self) -> dict[str, Any]:
        """Fetch data from multiple local transports (Modbus + Dongle mix).

        LOCAL mode allows configuring multiple inverters with different transport
        types in a single config entry, without any cloud credentials.

        Devices are processed sequentially to avoid overwhelming the local network
        with concurrent TCP connections (similar to how single-device Modbus/Dongle
        modes work). Individual device failures are isolated - one device failing
        doesn't break others. Only if ALL devices fail does this method raise
        UpdateFailed.

        Returns:
            Dictionary containing data from all local devices:
            {
                "plant_id": None,
                "devices": {serial1: {...}, serial2: {...}},
                "parameters": {serial1: {...}, serial2: {...}},
                "last_update": datetime,
                "connection_type": "local"
            }

        Raises:
            UpdateFailed: If no transports configured or ALL devices failed.
        """
        from pylxpweb.devices import MIDDevice
        from pylxpweb.devices.inverters._features import InverterFamily
        from pylxpweb.transports import create_dongle_transport, create_modbus_transport
        from pylxpweb.transports.exceptions import (
            TransportConnectionError,
            TransportError,
            TransportReadError,
            TransportTimeoutError,
        )

        if not self._local_transport_configs:
            raise UpdateFailed("No local transports configured")

        # Build processed data structure
        processed: dict[str, Any] = {
            "plant_id": None,  # No plant for LOCAL mode
            "devices": {},
            "device_info": {},
            "parameters": {},
            "last_update": dt_util.utcnow(),
            "connection_type": CONNECTION_TYPE_LOCAL,
        }

        # Track per-device availability for partial failure handling
        device_availability: dict[str, bool] = {}

        # Process each local transport configuration
        for config in self._local_transport_configs:
            serial = config.get("serial", "")
            transport_type = config.get("transport_type", "modbus_tcp")
            host = config.get("host", "")
            port = config.get("port", DEFAULT_MODBUS_PORT)

            if not serial or not host:
                _LOGGER.warning(
                    "LOCAL: Skipping invalid config (missing serial or host): %s",
                    config,
                )
                continue

            try:
                # Convert inverter family string to enum
                inverter_family = None
                family_str = config.get("inverter_family", DEFAULT_INVERTER_FAMILY)
                if family_str:
                    try:
                        inverter_family = InverterFamily(family_str)
                    except ValueError:
                        _LOGGER.warning(
                            "LOCAL: Unknown inverter family '%s' for %s, using default",
                            family_str,
                            serial,
                        )

                # Get model from config, or derive from family
                model = config.get("model", "")
                if not model:
                    model = INVERTER_FAMILY_DEFAULT_MODELS.get(family_str, "18kPV")

                # Create or reuse transport based on type
                # Use plain serial as cache key for get_inverter_object() compatibility
                # Check both inverter and MID device caches
                is_gridboss = serial in self._mid_device_cache
                is_inverter = serial in self._inverter_cache

                if not is_gridboss and not is_inverter:
                    # Create transport (type is Any to support both Modbus and Dongle)
                    transport: Any = None
                    if transport_type == "modbus_tcp":
                        transport = create_modbus_transport(
                            host=host,
                            port=port,
                            unit_id=config.get("unit_id", DEFAULT_MODBUS_UNIT_ID),
                            serial=serial,
                            timeout=DEFAULT_MODBUS_TIMEOUT,
                            inverter_family=inverter_family,
                        )
                    elif transport_type == "wifi_dongle":
                        transport = create_dongle_transport(
                            host=host,
                            dongle_serial=config.get("dongle_serial", ""),
                            inverter_serial=serial,
                            port=port,
                            timeout=DEFAULT_DONGLE_TIMEOUT,
                            inverter_family=inverter_family,
                        )
                    else:
                        _LOGGER.error(
                            "LOCAL: Unknown transport type '%s' for %s",
                            transport_type,
                            serial,
                        )
                        device_availability[serial] = False
                        continue

                    # Connect transport
                    if not transport.is_connected:
                        await transport.connect()

                    # Try to create device - BaseInverter first, MIDDevice if GridBOSS
                    try:
                        _LOGGER.debug(
                            "LOCAL: Creating device from %s transport for %s",
                            transport_type,
                            serial,
                        )
                        inverter = await BaseInverter.from_modbus_transport(
                            transport, model=model
                        )
                        self._inverter_cache[serial] = inverter
                        is_inverter = True
                    except LuxpowerDeviceError as e:
                        # Device is a GridBOSS, not an inverter
                        if "GridBOSS" in str(e) or "MIDbox" in str(e):
                            _LOGGER.info(
                                "LOCAL: Device %s is a GridBOSS, creating MIDDevice",
                                serial,
                            )
                            mid_device = await MIDDevice.from_transport(
                                transport, model="GridBOSS"
                            )
                            self._mid_device_cache[serial] = mid_device
                            is_gridboss = True
                        else:
                            raise

                # Process based on device type
                if is_gridboss:
                    # GridBOSS/MID device processing
                    mid_device = self._mid_device_cache[serial]

                    # Ensure transport is connected
                    transport = mid_device._transport
                    if transport and not transport.is_connected:
                        await transport.connect()

                    # Refresh data from transport
                    await mid_device.refresh()

                    # Read firmware version
                    firmware_version: str = "Unknown"
                    if hasattr(mid_device, "firmware_version"):
                        firmware_version = mid_device.firmware_version or "Unknown"

                    # Check if device has data
                    if not mid_device.has_data:
                        raise TransportReadError(
                            f"Failed to read runtime data for GridBOSS {serial}"
                        )

                    # Build GridBOSS device data with sensor mappings
                    sensors = _build_gridboss_sensor_mapping(mid_device)
                    # Filter out None values
                    sensors = {k: v for k, v in sensors.items() if v is not None}
                    sensors["firmware_version"] = firmware_version

                    device_data: dict[str, Any] = {
                        "type": "gridboss",
                        "model": "GridBOSS",
                        "serial": serial,
                        "firmware_version": firmware_version,
                        "sensors": sensors,
                        "binary_sensors": {},
                    }

                    # Store device data
                    processed["devices"][serial] = device_data
                    device_availability[serial] = True

                    # GridBOSS doesn't have parameters like inverters
                    processed["parameters"][serial] = {}

                    _LOGGER.debug(
                        "LOCAL: Updated GridBOSS %s (%s) - FW: %s, Grid: %sW, Load: %sW",
                        serial,
                        transport_type,
                        firmware_version,
                        sensors.get("grid_power", "N/A"),
                        sensors.get("load_power", "N/A"),
                    )
                else:
                    # Inverter processing
                    inverter = self._inverter_cache[serial]

                    # Ensure transport is connected
                    transport = inverter._transport
                    if transport and not transport.is_connected:
                        await transport.connect()

                    # Refresh data from transport
                    await inverter.refresh(force=True, include_parameters=True)

                    # Read firmware version from transport
                    firmware_version = "Unknown"
                    transport = inverter._transport
                    if transport and hasattr(transport, "read_firmware_version"):
                        read_fw = getattr(transport, "read_firmware_version")
                        firmware_version = await read_fw() or "Unknown"

                    # Get data from transport via inverter's internal storage
                    runtime_data = inverter._transport_runtime
                    energy_data = inverter._transport_energy

                    if runtime_data is None:
                        raise TransportReadError(
                            f"Failed to read runtime data for {serial}"
                        )

                    # Build device data structure with sensor mappings
                    device_data = {
                        "type": "inverter",
                        "model": model,
                        "serial": serial,
                        "firmware_version": firmware_version,
                        "sensors": _build_runtime_sensor_mapping(runtime_data),
                        "batteries": {},
                    }

                    # Add energy sensors if available
                    if energy_data:
                        device_data["sensors"].update(
                            _build_energy_sensor_mapping(energy_data)
                        )

                    # Add battery bank data if available
                    battery_data = inverter._transport_battery
                    if battery_data:
                        device_data["sensors"].update(
                            _build_battery_bank_sensor_mapping(battery_data)
                        )

                    # Add firmware version as diagnostic sensor
                    device_data["sensors"]["firmware_version"] = firmware_version

                    # Store device data
                    processed["devices"][serial] = device_data
                    device_availability[serial] = True

                    # Get parameters from inverter's cached parameters
                    param_data = inverter.parameters or {}
                    processed["parameters"][serial] = param_data

                    _LOGGER.debug(
                        "LOCAL: Updated %s (%s) - FW: %s, PV: %.0fW, SOC: %d%%, Grid: %.0fW",
                        serial,
                        transport_type,
                        firmware_version,
                        runtime_data.pv_total_power,
                        runtime_data.battery_soc,
                        runtime_data.grid_power,
                    )

            except (
                TransportConnectionError,
                TransportTimeoutError,
                TransportReadError,
                TransportError,
            ) as e:
                _LOGGER.warning(
                    "LOCAL: Failed to update %s (%s): %s",
                    serial,
                    transport_type,
                    e,
                )
                device_availability[serial] = False
                # Continue with other devices rather than failing entire update
                continue

            except Exception as e:
                _LOGGER.exception(
                    "LOCAL: Unexpected error updating %s (%s): %s",
                    serial,
                    transport_type,
                    e,
                )
                device_availability[serial] = False
                continue

        # Check if we got any device data
        successful_devices = sum(1 for v in device_availability.values() if v)
        total_devices = len(self._local_transport_configs)

        if successful_devices == 0:
            # Silver tier logging: Log when all devices become unavailable
            if self._last_available_state:
                _LOGGER.warning(
                    "LOCAL: All %d devices unavailable",
                    total_devices,
                )
                self._last_available_state = False
            raise UpdateFailed(f"All {total_devices} local transports failed to update")

        # Silver tier logging: Log when service becomes available again
        if not self._last_available_state:
            _LOGGER.warning(
                "LOCAL: Connection restored - %d/%d devices available",
                successful_devices,
                total_devices,
            )
            self._last_available_state = True

        # Log partial failure if some devices failed
        if successful_devices < total_devices:
            _LOGGER.warning(
                "LOCAL: Partial update - %d/%d devices updated successfully",
                successful_devices,
                total_devices,
            )
        else:
            _LOGGER.debug(
                "LOCAL: Successfully updated all %d devices",
                total_devices,
            )

        return processed

    async def _async_update_hybrid_data(self) -> dict[str, Any]:
        """Fetch data using local transport (Modbus/Dongle) + HTTP (discovery/battery).

        Hybrid mode provides the best of both worlds:
        - Fast 1-5 second runtime updates via local transport (Modbus or Dongle)
        - Device discovery and individual battery data via HTTP cloud API

        Priority: Modbus > Dongle > HTTP-only (based on configured local transport)

        Returns:
            Dictionary containing merged data from both sources.
        """
        from pylxpweb.transports.exceptions import TransportError

        # Try to get local data from configured transport (Modbus or Dongle)
        local_data: dict[str, Any] | None = None
        local_serial: str = ""
        local_transport_name: str = ""

        # Priority 1: Try Modbus if configured
        if self._modbus_transport is not None:
            local_transport_name = "Modbus"
            local_serial = self._modbus_serial
            try:
                if not self._modbus_transport.is_connected:
                    await self._modbus_transport.connect()

                # Read sequentially to avoid transaction ID desync issues
                runtime_data = await self._modbus_transport.read_runtime()
                energy_data = await self._modbus_transport.read_energy()
                local_data = {
                    "runtime": runtime_data,
                    "energy": energy_data,
                }
                _LOGGER.debug(
                    "Hybrid: %s runtime - PV: %.0fW, SOC: %d%%",
                    local_transport_name,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                )
            except TransportError as e:
                _LOGGER.warning(
                    "Hybrid: %s read failed, falling back to HTTP: %s",
                    local_transport_name,
                    e,
                )
                local_data = None

        # Priority 2: Try Dongle if configured and Modbus not available/failed
        if local_data is None and self._dongle_transport is not None:
            local_transport_name = "Dongle"
            local_serial = self._dongle_serial
            try:
                if not self._dongle_transport.is_connected:
                    await self._dongle_transport.connect()

                runtime_data = await self._dongle_transport.read_runtime()
                energy_data = await self._dongle_transport.read_energy()
                local_data = {
                    "runtime": runtime_data,
                    "energy": energy_data,
                }
                _LOGGER.debug(
                    "Hybrid: %s runtime - PV: %.0fW, SOC: %d%%",
                    local_transport_name,
                    runtime_data.pv_total_power,
                    runtime_data.battery_soc,
                )
            except TransportError as e:
                _LOGGER.warning(
                    "Hybrid: %s read failed, falling back to HTTP-only: %s",
                    local_transport_name,
                    e,
                )
                local_data = None

        # Get HTTP data for discovery, batteries, and features not in local transport
        http_data = await self._async_update_http_data()

        # If we have local data, merge it with HTTP data for the matching inverter
        if local_data is not None and local_serial in http_data.get("devices", {}):
            self._merge_local_data_with_http(
                http_data["devices"][local_serial],
                local_data["runtime"],
                local_data["energy"],
                local_serial,
                local_transport_name,
            )

        http_data["connection_type"] = CONNECTION_TYPE_HYBRID
        return http_data

    def _merge_local_data_with_http(
        self,
        device: dict[str, Any],
        runtime: Any,
        energy: Any,
        serial: str,
        transport_name: str,
    ) -> None:
        """Merge local transport data with HTTP device data.

        This method overrides HTTP sensor values with faster local transport values.
        All sensors available from local transport are merged, not just a subset.

        Args:
            device: The device dictionary from HTTP data to update
            runtime: InverterRuntimeData from local transport
            energy: InverterEnergyData from local transport
            serial: Inverter serial number for logging
            transport_name: Name of local transport for logging (Modbus/Dongle)
        """
        # Override runtime sensors with faster local values
        # Uses SENSOR_TYPES keys to match HTTP data structure
        # Include ALL available sensors from local transport for maximum coverage
        device["sensors"].update(
            {
                # PV/Solar input - all strings
                "pv1_voltage": runtime.pv1_voltage,
                "pv1_power": runtime.pv1_power,
                "pv2_voltage": runtime.pv2_voltage,
                "pv2_power": runtime.pv2_power,
                "pv3_voltage": runtime.pv3_voltage,
                "pv3_power": runtime.pv3_power,
                "pv_total_power": runtime.pv_total_power,
                # Battery
                "battery_voltage": runtime.battery_voltage,
                "battery_current": runtime.battery_current,
                "state_of_charge": runtime.battery_soc,
                "battery_charge_power": runtime.battery_charge_power,
                "battery_discharge_power": runtime.battery_discharge_power,
                "battery_temperature": runtime.battery_temperature,
                # Grid - all phases (use _l1/_l2/_l3 to match SENSOR_TYPES)
                "grid_voltage_r": runtime.grid_voltage_r,
                "grid_voltage_s": runtime.grid_voltage_s,
                "grid_voltage_t": runtime.grid_voltage_t,
                "grid_current_l1": runtime.grid_current_r,
                "grid_current_l2": runtime.grid_current_s,
                "grid_current_l3": runtime.grid_current_t,
                "grid_frequency": runtime.grid_frequency,
                "grid_power": runtime.grid_power,
                "grid_export_power": runtime.power_to_grid,
                # Inverter output
                "ac_power": runtime.inverter_power,
                "load_power": runtime.load_power,
                # EPS/Backup - all phases
                "eps_voltage_r": runtime.eps_voltage_r,
                "eps_voltage_s": runtime.eps_voltage_s,
                "eps_voltage_t": runtime.eps_voltage_t,
                "eps_frequency": runtime.eps_frequency,
                "eps_power": runtime.eps_power,
                # Generator (if available from Modbus/Dongle)
                "generator_voltage": runtime.generator_voltage,
                "generator_frequency": runtime.generator_frequency,
                "generator_power": runtime.generator_power,
                # Bus voltages
                "bus1_voltage": runtime.bus_voltage_1,
                "bus2_voltage": runtime.bus_voltage_2,
                # Temperatures
                "internal_temperature": runtime.internal_temperature,
                "radiator1_temperature": runtime.radiator_temperature_1,
                "radiator2_temperature": runtime.radiator_temperature_2,
                # Status
                "status_code": runtime.device_status,
            }
        )

        # Override energy sensors with local values
        device["sensors"].update(
            {
                # Daily energy (kWh)
                "yield": energy.pv_energy_today,
                "charging": energy.charge_energy_today,
                "discharging": energy.discharge_energy_today,
                "grid_import": energy.grid_import_today,
                "grid_export": energy.grid_export_today,
                "load": energy.load_energy_today,
                # Lifetime energy (kWh)
                "yield_lifetime": energy.pv_energy_total,
                "charging_lifetime": energy.charge_energy_total,
                "discharging_lifetime": energy.discharge_energy_total,
                "grid_import_lifetime": energy.grid_import_total,
                "grid_export_lifetime": energy.grid_export_total,
                "load_lifetime": energy.load_energy_total,
            }
        )

        _LOGGER.debug(
            "Hybrid: Merged %s runtime with HTTP data for %s",
            transport_name,
            serial,
        )

    async def _attach_local_transports_to_station(self) -> None:
        """Attach local transports to HTTP-discovered station devices.

        This method enables hybrid mode by connecting local transports
        (Modbus TCP or WiFi Dongle) to devices discovered via HTTP API.
        After attachment, devices will use local transport for data fetching
        with automatic fallback to HTTP on failure.

        Uses the new Station.attach_local_transports() API from pylxpweb.
        """
        if self.station is None or not self._local_transport_configs:
            return

        _LOGGER.info(
            "Attaching %d local transport(s) to station devices",
            len(self._local_transport_configs),
        )

        # Convert stored config dicts to TransportConfig objects
        configs = _build_transport_configs(self._local_transport_configs)
        if not configs:
            _LOGGER.warning("No valid transport configs to attach")
            return

        try:
            result = await self.station.attach_local_transports(configs)

            _LOGGER.info(
                "Local transport attachment complete: %d matched, %d unmatched, %d failed",
                result.matched,
                result.unmatched,
                result.failed,
            )

            if result.unmatched_serials:
                _LOGGER.warning(
                    "No devices found for serials: %s",
                    ", ".join(result.unmatched_serials),
                )

            if result.failed_serials:
                _LOGGER.warning(
                    "Failed to connect transports for serials: %s",
                    ", ".join(result.failed_serials),
                )

            self._local_transports_attached = True

            # Log hybrid mode status
            if self.station.is_hybrid_mode:
                _LOGGER.info(
                    "Station is now in hybrid mode with %d local transport(s) attached",
                    result.matched,
                )

        except Exception as err:
            _LOGGER.error("Failed to attach local transports: %s", err)
            # Don't mark as attached so we can retry on next update
            self._local_transports_attached = False

    async def _async_update_http_data(self) -> dict[str, Any]:
        """Fetch data from HTTP cloud API using device objects.

        This is the original HTTP-based update method using LuxpowerClient
        and Station/Inverter device objects.

        Returns:
            Dictionary containing all device data, sensors, and station information.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If connection or API errors occur.
        """
        if self.client is None:
            raise UpdateFailed("HTTP client not initialized")

        try:
            _LOGGER.debug("Fetching HTTP data for plant %s", self.plant_id)

            # Check if hourly parameter refresh is due
            if self._should_refresh_parameters():
                _LOGGER.info(
                    "Hourly parameter refresh is due, refreshing all device parameters"
                )
                task = self.hass.async_create_task(self._hourly_parameter_refresh())
                self._background_tasks.add(task)
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            # Load or refresh station data using device objects
            if self.station is None:
                _LOGGER.info("Loading station data for plant %s", self.plant_id)
                self.station = await Station.load(self.client, self.plant_id)
                _LOGGER.debug(
                    "Refreshing all data after station load to populate battery details"
                )
                await self.station.refresh_all_data()
                # Build inverter cache for O(1) lookups
                self._rebuild_inverter_cache()

                # For hybrid mode: Attach local transports to devices (new API)
                # This enables devices to use local transport with HTTP fallback
                if (
                    self.connection_type == CONNECTION_TYPE_HYBRID
                    and self._local_transport_configs
                    and not self._local_transports_attached
                ):
                    await self._attach_local_transports_to_station()
            else:
                _LOGGER.debug("Refreshing station data for plant %s", self.plant_id)
                await self.station.refresh_all_data()

            # Log inverter data status after refresh
            for inverter in self.station.all_inverters:
                battery_bank = getattr(inverter, "_battery_bank", None)
                battery_count = 0
                battery_array_len = 0
                if battery_bank:
                    battery_count = getattr(battery_bank, "battery_count", 0)
                    batteries = getattr(battery_bank, "batteries", [])
                    battery_array_len = len(batteries) if batteries else 0
                _LOGGER.debug(
                    "Inverter %s (%s): has_data=%s, _runtime=%s, _energy=%s, "
                    "_battery_bank=%s, battery_count=%s, batteries_len=%s",
                    inverter.serial_number,
                    getattr(inverter, "model", "Unknown"),
                    inverter.has_data,
                    "present"
                    if getattr(inverter, "_runtime", None) is not None
                    else "None",
                    "present"
                    if getattr(inverter, "_energy", None) is not None
                    else "None",
                    "present" if battery_bank else "None",
                    battery_count,
                    battery_array_len,
                )

            # Perform DST sync if enabled and due
            if self.dst_sync_enabled and self.station and self._should_sync_dst():
                await self._perform_dst_sync()

            # Process and structure the device data
            processed_data = await self._process_station_data()
            processed_data["connection_type"] = CONNECTION_TYPE_HTTP

            device_count = len(processed_data.get("devices", {}))
            _LOGGER.debug("Successfully updated data for %d devices", device_count)

            # Silver tier requirement: Log when service becomes available again
            if not self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service reconnected successfully for plant %s",
                    self.plant_id,
                )
                self._last_available_state = True

            return processed_data

        except LuxpowerAuthError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to authentication error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("Authentication error: %s", e)
            raise ConfigEntryAuthFailed(f"Authentication failed: {e}") from e

        except LuxpowerConnectionError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to connection error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("Connection error: %s", e)
            raise UpdateFailed(f"Connection failed: {e}") from e

        except LuxpowerAPIError as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to API error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("API error: %s", e)
            raise UpdateFailed(f"API error: {e}") from e

        except Exception as e:
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to unexpected error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected error updating data: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _process_station_data(self) -> dict[str, Any]:
        """Process station data using device objects."""
        if not self.station:
            raise UpdateFailed("Station not loaded")

        processed = {
            "plant_id": self.plant_id,
            "devices": {},
            "device_info": {},
            "last_update": dt_util.utcnow(),
        }

        # Preserve existing parameter data from previous updates
        if self.data and "parameters" in self.data:
            processed["parameters"] = self.data["parameters"]

        # Add station data
        processed["station"] = {
            "name": self.station.name,
            "plant_id": self.station.id,
        }

        if timezone := getattr(self.station, "timezone", None):
            processed["station"]["timezone"] = timezone

        if location := getattr(self.station, "location", None):
            if country := getattr(location, "country", None):
                processed["station"]["country"] = country
            if address := getattr(location, "address", None):
                processed["station"]["address"] = address

        if created_date := getattr(self.station, "created_date", None):
            processed["station"]["createDate"] = created_date.isoformat()

        # Process all inverters concurrently with semaphore to prevent rate limiting
        async def process_inverter_with_semaphore(
            inv: BaseInverter,
        ) -> tuple[str, dict[str, Any]]:
            """Process a single inverter with semaphore protection."""
            async with self._api_semaphore:
                try:
                    result = await self._process_inverter_object(inv)
                    return (inv.serial_number, result)
                except Exception as e:
                    _LOGGER.error(
                        "Error processing inverter %s: %s", inv.serial_number, e
                    )
                    return (
                        inv.serial_number,
                        {
                            "type": "unknown",
                            "model": "Unknown",
                            "error": str(e),
                            "sensors": {},
                            "batteries": {},
                        },
                    )

        # Process all inverters concurrently (max 3 at a time via semaphore)
        inverter_tasks = [
            process_inverter_with_semaphore(inv) for inv in self.station.all_inverters
        ]
        inverter_results = await asyncio.gather(*inverter_tasks)

        # Populate processed devices from results
        for serial, device_data in inverter_results:
            processed["devices"][serial] = device_data

        # Process parallel group data if available
        if hasattr(self.station, "parallel_groups") and self.station.parallel_groups:
            _LOGGER.debug(
                "Processing %d parallel groups", len(self.station.parallel_groups)
            )
            for group in self.station.parallel_groups:
                try:
                    await group.refresh()
                    _LOGGER.debug(
                        "Parallel group %s refreshed: energy=%s, today_yielding=%.2f kWh",
                        group.name,
                        group._energy is not None,
                        group.today_yielding,
                    )

                    group_data = await self._process_parallel_group_object(group)
                    _LOGGER.debug(
                        "Parallel group %s sensors: %s",
                        group.name,
                        list(group_data.get("sensors", {}).keys()),
                    )
                    processed["devices"][
                        f"parallel_group_{group.first_device_serial}"
                    ] = group_data

                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            processed["devices"][
                                group.mid_device.serial_number
                            ] = await self._process_mid_device_object(group.mid_device)
                        except Exception as e:
                            _LOGGER.error(
                                "Error processing MID device %s: %s",
                                group.mid_device.serial_number,
                                e,
                            )
                except Exception as e:
                    _LOGGER.error("Error processing parallel group: %s", e)

        # Process standalone MID devices (GridBOSS without inverters) - fixes #86
        if hasattr(self.station, "standalone_mid_devices"):
            for mid_device in self.station.standalone_mid_devices:
                try:
                    processed["devices"][
                        mid_device.serial_number
                    ] = await self._process_mid_device_object(mid_device)
                    _LOGGER.debug(
                        "Processed standalone MID device %s",
                        mid_device.serial_number,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing standalone MID device %s: %s",
                        mid_device.serial_number,
                        e,
                    )

        # Process batteries through inverter hierarchy (fixes #76)
        # This approach uses the known parent serial from the inverter object,
        # rather than trying to parse it from batteryKey (which may not contain it)
        for serial, device_data in processed["devices"].items():
            if device_data.get("type") != "inverter":
                continue

            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.debug("No inverter object found for serial %s", serial)
                continue

            # Access battery_bank through the inverter object
            battery_bank = getattr(inverter, "_battery_bank", None)
            if not battery_bank:
                _LOGGER.debug(
                    "No battery_bank for inverter %s (battery_bank=%s)",
                    serial,
                    battery_bank,
                )
                continue

            batteries = getattr(battery_bank, "batteries", None)
            if not batteries:
                _LOGGER.debug(
                    "No batteries in battery_bank for inverter %s (batteries=%s, "
                    "battery_bank.data=%s)",
                    serial,
                    batteries,
                    getattr(battery_bank, "data", None),
                )
                continue

            _LOGGER.debug("Found %d batteries for inverter %s", len(batteries), serial)

            for battery in batteries:
                try:
                    battery_key = clean_battery_display_name(
                        getattr(
                            battery,
                            "battery_key",
                            f"BAT{battery.battery_index:03d}",
                        ),
                        serial,  # Parent serial is known from inverter iteration
                    )
                    battery_sensors = self._extract_battery_from_object(battery)

                    if "batteries" not in device_data:
                        device_data["batteries"] = {}
                    device_data["batteries"][battery_key] = battery_sensors

                    _LOGGER.debug(
                        "Processed battery %s for inverter %s",
                        battery_key,
                        serial,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing battery %s for inverter %s: %s",
                        getattr(battery, "battery_sn", "unknown"),
                        serial,
                        e,
                    )

        # Check if we need to refresh parameters for any inverters
        if "parameters" not in processed:
            processed["parameters"] = {}

        inverters_needing_params = []
        for serial, device_data in processed["devices"].items():
            if (
                device_data.get("type") == "inverter"
                and serial not in processed["parameters"]
            ):
                inverters_needing_params.append(serial)

        if inverters_needing_params:
            _LOGGER.info(
                "Refreshing parameters for %d new inverters: %s",
                len(inverters_needing_params),
                inverters_needing_params,
            )
            task = self.hass.async_create_task(
                self._refresh_missing_parameters(inverters_needing_params, processed)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._remove_task_from_set)
            task.add_done_callback(self._log_task_exception)

        return processed

    def _rebuild_inverter_cache(self) -> None:
        """Rebuild inverter lookup cache after station load."""
        self._inverter_cache = {}
        if self.station:
            for inverter in self.station.all_inverters:
                self._inverter_cache[inverter.serial_number] = inverter
            _LOGGER.debug(
                "Rebuilt inverter cache with %d inverters",
                len(self._inverter_cache),
            )

    def get_inverter_object(self, serial: str) -> BaseInverter | None:
        """Get inverter device object by serial number (O(1) cached lookup)."""
        return self._inverter_cache.get(serial)

    def get_battery_object(self, serial: str, battery_index: int) -> Battery | None:
        """Get battery object by inverter serial and battery index."""
        inverter = self.get_inverter_object(serial)
        battery_bank = getattr(inverter, "_battery_bank", None) if inverter else None
        if not battery_bank:
            return None

        if not hasattr(battery_bank, "batteries"):
            return None

        for battery in battery_bank.batteries:
            if battery.index == battery_index:
                return cast(Battery, battery)

        return None

    def get_local_transport(self) -> Any | None:
        """Get the Modbus or Dongle transport for local register operations.

        Returns:
            ModbusTransport, DongleTransport, or None if using HTTP-only mode.
        """
        if self._modbus_transport:
            return self._modbus_transport
        if self._dongle_transport:
            return self._dongle_transport
        return None

    def has_local_transport(self) -> bool:
        """Check if local Modbus or Dongle transport is available.

        Returns:
            True if Modbus or Dongle transport is configured.
        """
        return self._modbus_transport is not None or self._dongle_transport is not None

    def has_http_api(self) -> bool:
        """Check if HTTP API is available (HTTP or Hybrid mode).

        Used to determine if HTTP-only features like Quick Charge are available.

        Returns:
            True if HTTP client is configured (HTTP or Hybrid mode).
        """
        return self.client is not None

    def is_local_only(self) -> bool:
        """Check if using local-only connection (Modbus or Dongle, no HTTP).

        Returns:
            True if Modbus or Dongle mode without HTTP fallback.
        """
        return self.connection_type in (CONNECTION_TYPE_MODBUS, CONNECTION_TYPE_DONGLE)

    async def write_register_bit(
        self,
        register: int,
        bit: int,
        value: bool,
    ) -> bool:
        """Write a single bit in a holding register.

        Reads the current register value, modifies the specified bit,
        and writes back the updated value.

        Args:
            register: Holding register address (e.g., 21 for FUNC_EN, 110 for SYS_FUNC)
            bit: Bit position (0-15)
            value: True to set bit, False to clear

        Returns:
            True if write succeeded, False otherwise.

        Raises:
            HomeAssistantError: If no local transport or write fails.
        """
        transport = self.get_local_transport()
        if not transport:
            raise HomeAssistantError("No local transport available for register write")

        try:
            # Read current register value
            current_regs = await transport.read_parameters(register, 1)
            if register not in current_regs:
                raise HomeAssistantError(f"Failed to read register {register}")

            current_value = current_regs[register]

            # Modify the bit
            if value:
                new_value = current_value | (1 << bit)
            else:
                new_value = current_value & ~(1 << bit)

            # Write back if changed
            if new_value != current_value:
                await transport.write_parameters({register: new_value})
                _LOGGER.debug(
                    "Wrote register %d bit %d = %s (0x%04X -> 0x%04X)",
                    register,
                    bit,
                    value,
                    current_value,
                    new_value,
                )

            return True

        except Exception as err:
            _LOGGER.error("Failed to write register %d bit %d: %s", register, bit, err)
            raise HomeAssistantError(
                f"Failed to write register {register} bit {bit}: {err}"
            ) from err

    async def write_register_value(
        self,
        register: int,
        value: int,
    ) -> bool:
        """Write a value directly to a holding register.

        Args:
            register: Holding register address
            value: Value to write (0-65535)

        Returns:
            True if write succeeded, False otherwise.

        Raises:
            HomeAssistantError: If no local transport or write fails.
        """
        transport = self.get_local_transport()
        if not transport:
            raise HomeAssistantError("No local transport available for register write")

        try:
            await transport.write_parameters({register: value})
            _LOGGER.debug("Wrote register %d = %d (0x%04X)", register, value, value)
            return True

        except Exception as err:
            _LOGGER.error("Failed to write register %d: %s", register, err)
            raise HomeAssistantError(
                f"Failed to write register {register}: {err}"
            ) from err

    def _get_device_object(self, serial: str) -> BaseInverter | Any | None:
        """Get device object (inverter or MID device) by serial number.

        Used by Update platform to get device objects for firmware updates.
        Returns BaseInverter for inverters, or MIDDevice (typed as Any) for MID devices.
        """
        if not self.station:
            return None

        for inverter in self.station.all_inverters:
            if inverter.serial_number == serial:
                return inverter

        if hasattr(self.station, "parallel_groups"):
            for group in self.station.parallel_groups:
                if hasattr(group, "mid_device") and group.mid_device:
                    if group.mid_device.serial_number == serial:
                        return group.mid_device

        # Check standalone MID devices (GridBOSS without inverters)
        if hasattr(self.station, "standalone_mid_devices"):
            for mid_device in self.station.standalone_mid_devices:
                if mid_device.serial_number == serial:
                    return mid_device

        return None
