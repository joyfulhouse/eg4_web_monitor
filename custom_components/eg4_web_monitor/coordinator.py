"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )
else:
    from homeassistant.helpers.update_coordinator import (  # type: ignore[assignment]
        DataUpdateCoordinator,
        UpdateFailed,
    )

from .const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    INVERTER_RUNTIME_FIELD_MAPPING,
    INVERTER_ENERGY_FIELD_MAPPING,
    PARALLEL_GROUP_FIELD_MAPPING,
    GRIDBOSS_FIELD_MAPPING,
    DIVIDE_BY_10_SENSORS,
    DIVIDE_BY_100_SENSORS,
    GRIDBOSS_ENERGY_SENSORS,
    VOLTAGE_SENSORS,
    CURRENT_SENSORS,
    FUNCTION_PARAM_MAPPING,
)
from pylxpweb import LuxpowerClient
from pylxpweb.devices import Station, BaseInverter, Battery
from pylxpweb.exceptions import LuxpowerAuthError, LuxpowerAPIError, LuxpowerConnectionError
from .utils import (
    CircuitBreaker,
    extract_individual_battery_sensors,
    clean_battery_display_name,
    read_device_parameters_ranges,
    process_parameter_responses,
    apply_sensor_scaling,
    to_camel_case,
)

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching EG4 Web Monitor data from the API using device objects."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]

        # Initialize Luxpower API client with injected session (Platinum tier requirement)
        # Home Assistant manages the aiohttp ClientSession for efficient resource usage
        self.client = LuxpowerClient(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(
                CONF_BASE_URL, "https://monitor.eg4electronics.com"
            ),
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
            session=aiohttp_client.async_get_clientsession(hass),
        )

        # Station object for device hierarchy
        self.station: Optional[Station] = None

        # Device tracking
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.device_sensors: Dict[str, List[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: Optional[datetime] = None
        self._parameter_refresh_interval = timedelta(
            hours=1
        )  # Hourly parameter refresh

        # Cache invalidation tracking
        self._last_cache_invalidation: Optional[datetime] = None

        # Solution 4: Background session maintenance tracking
        #  Initialize to current time to prevent immediate trigger on first update
        self._last_session_maintenance: Optional[datetime] = dt_util.utcnow()
        self._session_maintenance_interval = timedelta(
            minutes=90
        )  # Session keepalive every 90 minutes (before 2-hour expiry)

        # Background task tracking for proper cleanup
        self._background_tasks: Set[asyncio.Task[Any]] = set()

        # Circuit breaker for API resilience
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)

        # Temporary device info storage for model extraction
        self._temp_device_info: Dict[str, Any] = {}

        # Individual energy processing queue
        self._pending_individual_energy_serials: List[str] = []

        # Track availability state for Silver tier logging requirement
        self._last_available_state: bool = True

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )

        # Register shutdown listener to cancel background tasks on Home Assistant stop
        self._shutdown_listener_remove = hass.bus.async_listen_once(
            "homeassistant_stop", self._async_handle_shutdown
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint using device objects."""
        try:
            _LOGGER.debug("Fetching data for plant %s", self.plant_id)

            # Solution 4: Background session maintenance
            # Perform session keepalive every 90 minutes to prevent expiry
            if self._should_perform_session_maintenance():
                _LOGGER.info(
                    "Session maintenance is due, performing keepalive to prevent expiry"
                )
                # Don't await this to avoid blocking the main data update
                task = self.hass.async_create_task(self._perform_session_maintenance())
                # Track task for cleanup and remove from set when done
                self._background_tasks.add(task)
                task.add_done_callback(lambda t: self._background_tasks.discard(t))
                task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )

            # Check if cache invalidation is needed before top of hour
            if self._should_invalidate_cache():
                _LOGGER.info(
                    "Cache invalidation needed before top of hour, clearing all caches"
                )
                self._invalidate_all_caches()

            # Check if hourly parameter refresh is due
            if self._should_refresh_parameters():
                _LOGGER.info(
                    "Hourly parameter refresh is due, refreshing all device parameters"
                )
                # Don't await this to avoid blocking the main data update
                # Create task and store reference to avoid RuntimeWarning
                task = self.hass.async_create_task(self._hourly_parameter_refresh())
                # Track task for cleanup and remove from set when done
                self._background_tasks.add(task)
                task.add_done_callback(lambda t: self._background_tasks.discard(t))
                task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )

            # Load or refresh station data using device objects
            if self.station is None:
                _LOGGER.info("Loading station data for plant %s", self.plant_id)
                self.station = await Station.load(self.client, self.plant_id)
            else:
                _LOGGER.debug("Refreshing station data for plant %s", self.plant_id)
                await self.station.refresh_all_data()

            # Process and structure the device data
            processed_data = await self._process_station_data()

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
            # Silver tier requirement: Log when service becomes unavailable
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to authentication error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.error("Authentication error: %s", e)
            # Silver tier requirement: Trigger reauthentication flow on auth failure
            raise ConfigEntryAuthFailed(f"Authentication failed: {e}") from e

        except LuxpowerConnectionError as e:
            # Silver tier requirement: Log when service becomes unavailable
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
            # Silver tier requirement: Log when service becomes unavailable
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
            # Silver tier requirement: Log when service becomes unavailable
            if self._last_available_state:
                _LOGGER.warning(
                    "EG4 Web Monitor service unavailable due to unexpected error for plant %s: %s",
                    self.plant_id,
                    e,
                )
                self._last_available_state = False
            _LOGGER.exception("Unexpected error updating data: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _process_station_data(self) -> Dict[str, Any]:
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
            "plant_id": self.station.plant_id,
        }

        # Process all inverters in the station
        for inverter in self.station.all_inverters:
            try:
                processed["devices"][inverter.serial] = await self._process_inverter_object(
                    inverter
                )
            except Exception as e:
                _LOGGER.error("Error processing inverter %s: %s", inverter.serial, e)
                # Keep device in data but mark it as having an error
                processed["devices"][inverter.serial] = {
                    "type": "unknown",
                    "model": "Unknown",
                    "error": str(e),
                    "sensors": {},
                    "batteries": {},
                }

        # Process parallel group data if available
        if hasattr(self.station, 'parallel_groups') and self.station.parallel_groups:
            for group in self.station.parallel_groups:
                try:
                    processed["devices"][
                        f"parallel_group_{group.group_id}"
                    ] = await self._process_parallel_group_object(group)
                except Exception as e:
                    _LOGGER.error("Error processing parallel group: %s", e)

        # Check if we need to refresh parameters for any inverters that don't have them
        if "parameters" not in processed:
            processed["parameters"] = {}

        inverters_needing_params = []
        for serial, device_data in processed["devices"].items():
            if (
                device_data.get("type") == "inverter"
                and serial not in processed["parameters"]
            ):
                inverters_needing_params.append(serial)

        # If there are inverters without parameters, refresh them
        if inverters_needing_params:
            _LOGGER.info(
                "Refreshing parameters for %d new inverters: %s",
                len(inverters_needing_params),
                inverters_needing_params,
            )
            # Don't await this to avoid blocking the data update
            self.hass.async_create_task(
                self._refresh_missing_parameters(inverters_needing_params, processed)
            )

        return processed

    async def _process_inverter_object(
        self, inverter: BaseInverter
    ) -> Dict[str, Any]:
        """Process inverter device data from device object."""
        processed: Dict[str, Any] = {
            "serial": inverter.serial,
            "type": "inverter" if not inverter.is_gridboss else "gridboss",
            "model": inverter.model or "Unknown",
            "firmware_version": inverter.firmware_version or "1.0.0",
            "sensors": {},
            "binary_sensors": {},
            "batteries": {},
        }

        # Process runtime data from Pydantic model
        if hasattr(inverter, 'runtime') and inverter.runtime:
            runtime_data = self._extract_runtime_from_object(inverter.runtime)
            processed["sensors"].update(runtime_data["sensors"])
            processed["binary_sensors"].update(runtime_data["binary_sensors"])

        # Process energy data
        if hasattr(inverter, 'energy') and inverter.energy:
            energy_data = self._extract_energy_from_object(inverter.energy)
            processed["sensors"].update(energy_data)

        # Process battery bank data
        if hasattr(inverter, 'battery_bank') and inverter.battery_bank:
            # Inverter-level battery data
            if hasattr(inverter.battery_bank, 'voltage'):
                processed["sensors"]["battery_voltage"] = inverter.battery_bank.voltage
            if hasattr(inverter.battery_bank, 'current'):
                processed["sensors"]["battery_current"] = inverter.battery_bank.current
            if hasattr(inverter.battery_bank, 'power'):
                processed["sensors"]["battery_power"] = inverter.battery_bank.power
            if hasattr(inverter.battery_bank, 'soc'):
                processed["sensors"]["state_of_charge"] = inverter.battery_bank.soc
            if hasattr(inverter.battery_bank, 'soh'):
                processed["sensors"]["state_of_health"] = inverter.battery_bank.soh

            # Individual batteries
            if hasattr(inverter.battery_bank, 'batteries'):
                for battery in inverter.battery_bank.batteries:
                    battery_key = clean_battery_display_name(
                        getattr(battery, 'battery_key', f"BAT{battery.index:03d}"),
                        inverter.serial
                    )
                    battery_sensors = self._extract_battery_from_object(battery)
                    processed["batteries"][battery_key] = battery_sensors

        # Process GridBOSS midbox data
        if inverter.is_gridboss and hasattr(inverter, 'midbox') and inverter.midbox:
            gridboss_data = self._extract_gridboss_from_object(inverter.midbox)
            processed["sensors"].update(gridboss_data["sensors"])
            processed["binary_sensors"].update(gridboss_data["binary_sensors"])

        return processed

    def _extract_runtime_from_object(self, runtime: Any) -> Dict[str, Any]:
        """Extract sensor data from runtime Pydantic model."""
        sensors: Dict[str, Any] = {}
        binary_sensors: Dict[str, Any] = {}

        # Map Pydantic model fields to sensor types
        field_mapping = INVERTER_RUNTIME_FIELD_MAPPING

        for api_field, sensor_type in field_mapping.items():
            if hasattr(runtime, api_field):
                value = getattr(runtime, api_field)
                if value is not None:
                    # Apply sensor scaling
                    scaled_value = apply_sensor_scaling(sensor_type, value, "inverter")

                    # Apply camel casing for status text
                    if sensor_type == "status_text" and isinstance(scaled_value, str):
                        scaled_value = to_camel_case(scaled_value)

                    sensors[sensor_type] = scaled_value

        # Calculate net grid power for standard inverters
        if hasattr(runtime, 'pToUser') and hasattr(runtime, 'pToGrid'):
            try:
                p_to_user = float(runtime.pToUser)  # Import from grid
                p_to_grid = float(runtime.pToGrid)  # Export to grid
                sensors["grid_power"] = p_to_user - p_to_grid
                _LOGGER.debug(
                    "Calculated grid_power: %s - %s = %s W (positive=importing, negative=exporting)",
                    p_to_user,
                    p_to_grid,
                    sensors["grid_power"],
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Could not calculate grid_power: %s", e
                )

        return {"sensors": sensors, "binary_sensors": binary_sensors}

    def _extract_energy_from_object(self, energy: Any) -> Dict[str, Any]:
        """Extract sensor data from energy Pydantic model."""
        sensors: Dict[str, Any] = {}

        field_mapping = INVERTER_ENERGY_FIELD_MAPPING

        for api_field, sensor_type in field_mapping.items():
            if hasattr(energy, api_field):
                value = getattr(energy, api_field)
                if value is not None:
                    # Apply sensor scaling
                    scaled_value = apply_sensor_scaling(sensor_type, value, "inverter")
                    sensors[sensor_type] = scaled_value

        return sensors

    def _extract_battery_from_object(self, battery: Battery) -> Dict[str, Any]:
        """Extract sensor data from Battery object."""
        sensors: Dict[str, Any] = {}

        # Direct field mappings
        field_map = {
            "voltage": "battery_real_voltage",
            "current": "battery_real_current",
            "power": "battery_real_power",
            "soc": "battery_rsoc",
            "soh": "state_of_health",
            "temperature": "temperature",
            "cell_voltage_max": "battery_cell_voltage_max",
            "cell_voltage_min": "battery_cell_voltage_min",
            "mos_temperature": "battery_mos_temperature",
            "env_temperature": "battery_env_temperature",
            "cycle_count": "cycle_count",
            "remaining_capacity": "battery_remaining_capacity",
            "full_capacity": "battery_full_capacity",
            "firmware_version": "battery_firmware_version",
        }

        for obj_field, sensor_type in field_map.items():
            if hasattr(battery, obj_field):
                value = getattr(battery, obj_field)
                if value is not None:
                    # Apply sensor scaling
                    scaled_value = apply_sensor_scaling(sensor_type, value, "battery")
                    sensors[sensor_type] = scaled_value

        # Calculate cell voltage difference if min/max available
        if "battery_cell_voltage_max" in sensors and "battery_cell_voltage_min" in sensors:
            sensors["battery_cell_voltage_diff"] = (
                sensors["battery_cell_voltage_max"] - sensors["battery_cell_voltage_min"]
            )

        return sensors

    def _extract_gridboss_from_object(self, midbox: Any) -> Dict[str, Any]:
        """Extract sensor data from GridBOSS midbox Pydantic model."""
        sensors: Dict[str, Any] = {}
        binary_sensors: Dict[str, Any] = {}

        field_mapping = GRIDBOSS_FIELD_MAPPING

        for api_field, sensor_type in field_mapping.items():
            if hasattr(midbox, api_field):
                value = getattr(midbox, api_field)
                if value is not None:
                    # Smart Port Status needs text conversion
                    if sensor_type.startswith("smart_port") and sensor_type.endswith("_status"):
                        status_map = {0: "Unused", 1: "Smart Load", 2: "AC Couple"}
                        value = status_map.get(value, f"Unknown ({value})")
                        sensors[sensor_type] = value
                        continue

                    # Apply sensor scaling
                    scaled_value = apply_sensor_scaling(sensor_type, value, "gridboss")
                    sensors[sensor_type] = scaled_value

        # Filter out sensors for unused Smart Ports
        sensors = self._filter_unused_smart_port_sensors_from_object(sensors, midbox)

        # Calculate aggregate sensors from individual L1/L2 values
        self._calculate_gridboss_aggregates(sensors)

        return {"sensors": sensors, "binary_sensors": binary_sensors}

    def _filter_unused_smart_port_sensors_from_object(
        self, sensors: Dict[str, Any], midbox: Any
    ) -> Dict[str, Any]:
        """Filter out sensors for unused Smart Ports from midbox object."""
        smart_port_statuses = {}
        for port in range(1, 5):
            status_field = f"smartPort{port}Status"
            if hasattr(midbox, status_field):
                status_value = getattr(midbox, status_field)
                smart_port_statuses[port] = status_value

        # Identify sensors to remove for unused Smart Ports (status = 0)
        sensors_to_remove = []
        for port, status in smart_port_statuses.items():
            if status == 0:  # Unused Smart Port
                sensors_to_remove.extend(
                    [
                        f"smart_load{port}_power_l1",
                        f"smart_load{port}_power_l2",
                        f"smart_load{port}_l1",
                        f"smart_load{port}_l2",
                        f"smart_load{port}_lifetime_l1",
                        f"smart_load{port}_lifetime_l2",
                    ]
                )

        # Remove the identified sensors
        filtered_sensors = sensors.copy()
        for sensor_key in sensors_to_remove:
            if sensor_key in filtered_sensors:
                del filtered_sensors[sensor_key]

        return filtered_sensors

    async def _process_parallel_group_object(self, group: Any) -> Dict[str, Any]:
        """Process parallel group data from group object."""
        processed: Dict[str, Any] = {
            "serial": f"parallel_group_{group.group_id}",
            "type": "parallel_group",
            "model": f"Parallel Group {group.group_letter}" if hasattr(group, 'group_letter') else "Parallel Group",
            "sensors": {},
            "binary_sensors": {},
        }

        # Extract parallel group energy sensors if available
        if hasattr(group, 'energy') and group.energy:
            sensors = self._extract_parallel_group_sensors_from_object(group.energy)
            processed["sensors"].update(sensors)

        return processed

    def _extract_parallel_group_sensors_from_object(self, energy: Any) -> Dict[str, Any]:
        """Extract sensor data from parallel group energy object."""
        sensors: Dict[str, Any] = {}

        field_mapping = PARALLEL_GROUP_FIELD_MAPPING

        for api_field, sensor_type in field_mapping.items():
            if hasattr(energy, api_field):
                value = getattr(energy, api_field)
                if value is not None:
                    # Apply sensor scaling
                    scaled_value = apply_sensor_scaling(sensor_type, value, "parallel_group")
                    sensors[sensor_type] = scaled_value

        return sensors

    def _calculate_gridboss_aggregates(self, sensors: Dict[str, Any]) -> None:
        """Calculate aggregate sensor values from individual L1/L2 values."""

        def _safe_numeric(value: Any) -> float:
            """Safely convert value to numeric, defaulting to 0."""
            if value is None:
                return 0.0
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        # Calculate Smart Load aggregate power from individual ports
        smart_load_powers = []
        for port in range(1, 5):
            l1_key = f"smart_load{port}_power_l1"
            l2_key = f"smart_load{port}_power_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_power = _safe_numeric(sensors[l1_key])
                l2_power = _safe_numeric(sensors[l2_key])
                port_power = l1_power + l2_power
                sensors[f"smart_load{port}_power"] = port_power
                smart_load_powers.append(port_power)

        # Calculate total smart load power
        if smart_load_powers:
            sensors["smart_load_power"] = sum(smart_load_powers)

        # Calculate total grid power from L1/L2
        if "grid_power_l1" in sensors and "grid_power_l2" in sensors:
            grid_l1 = _safe_numeric(sensors["grid_power_l1"])
            grid_l2 = _safe_numeric(sensors["grid_power_l2"])
            sensors["grid_power"] = grid_l1 + grid_l2

        # Calculate total UPS power from L1/L2
        if "ups_power_l1" in sensors and "ups_power_l2" in sensors:
            ups_l1 = _safe_numeric(sensors["ups_power_l1"])
            ups_l2 = _safe_numeric(sensors["ups_power_l2"])
            sensors["ups_power"] = ups_l1 + ups_l2

        # Calculate total load power from L1/L2
        if "load_power_l1" in sensors and "load_power_l2" in sensors:
            load_l1 = _safe_numeric(sensors["load_power_l1"])
            load_l2 = _safe_numeric(sensors["load_power_l2"])
            sensors["load_power"] = load_l1 + load_l2

        # Calculate total generator power from L1/L2
        if "generator_power_l1" in sensors and "generator_power_l2" in sensors:
            gen_l1 = _safe_numeric(sensors["generator_power_l1"])
            gen_l2 = _safe_numeric(sensors["generator_power_l2"])
            sensors["generator_power"] = gen_l1 + gen_l2

        # Calculate AC Couple aggregate today values for each port
        for port in range(1, 5):
            l1_key = f"ac_couple{port}_today_l1"
            l2_key = f"ac_couple{port}_today_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_val = _safe_numeric(sensors[l1_key])
                l2_val = _safe_numeric(sensors[l2_key])
                sensors[f"ac_couple{port}_today"] = l1_val + l2_val

        # Calculate AC Couple aggregate total values for each port
        for port in range(1, 5):
            l1_key = f"ac_couple{port}_total_l1"
            l2_key = f"ac_couple{port}_total_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_val = _safe_numeric(sensors[l1_key])
                l2_val = _safe_numeric(sensors[l2_key])
                sensors[f"ac_couple{port}_total"] = l1_val + l2_val

    # PRESERVED HELPER METHODS - Keep exact entity ID generation logic

    def get_device_info(self, serial: str) -> Optional[DeviceInfo]:
        """Get device information for a specific serial number."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        # Special handling for parallel group device naming
        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "unknown")

        if device_type == "parallel_group":
            # Use just the model name for parallel groups (e.g., "Parallel Group A")
            device_name = model
        else:
            device_name = f"{model} {serial}"  # Normal devices include serial number

        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": device_name,
            "manufacturer": "EG4 Electronics",
            "model": model,
        }

        # Add firmware version and serial number only for actual devices, not parallel groups
        if device_type != "parallel_group":
            device_info["serial_number"] = serial

            # Get firmware version for GridBOSS and inverter devices
            sw_version = "1.0.0"  # Default fallback
            if device_type in ["gridboss", "inverter"]:
                sw_version = device_data.get("firmware_version", "1.0.0")
            device_info["sw_version"] = sw_version

        # Add via_device for proper device hierarchy
        if device_type in ["inverter", "gridboss"]:
            # Check if this device belongs to a parallel group
            parallel_group_serial = self._get_parallel_group_for_device(serial)
            if parallel_group_serial:
                device_info["via_device"] = (DOMAIN, parallel_group_serial)

        # Return as Dict (compatible with DeviceInfo type)
        return device_info  # type: ignore[return-value]

    def _get_parallel_group_for_device(self, device_serial: str) -> Optional[str]:
        """Get the parallel group serial that contains this device."""
        if not self.data or "devices" not in self.data:
            return None

        # Check if station has parallel group info
        if self.station and hasattr(self.station, 'parallel_groups'):
            for group in self.station.parallel_groups:
                if hasattr(group, 'inverters'):
                    for inverter in group.inverters:
                        if inverter.serial == device_serial:
                            return f"parallel_group_{group.group_id}"

        # Fallback: if a parallel group exists, assume all devices are part of it
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                return str(serial)

        return None

    def get_battery_device_info(
        self, serial: str, battery_key: str
    ) -> Optional[DeviceInfo]:
        """Get device information for a specific battery."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data or battery_key not in device_data.get("batteries", {}):
            return None

        # Get battery-specific data for firmware version
        battery_data = device_data.get("batteries", {}).get(battery_key, {})
        battery_firmware = battery_data.get("battery_firmware_version", "1.0.0")

        # Use cleaned battery name for display
        clean_battery_name = clean_battery_display_name(battery_key, serial)

        return {
            "identifiers": {(DOMAIN, f"{serial}_{battery_key}")},
            "name": f"Battery {clean_battery_name}",
            "manufacturer": "EG4 Electronics",
            "model": "Battery Module",
            "sw_version": battery_firmware,
            "via_device": (DOMAIN, serial),  # Link battery to its parent inverter
        }

    def get_station_device_info(self) -> Optional[DeviceInfo]:
        """Get device information for the station/plant."""
        if not self.data or "station" not in self.data:
            return None

        station_data = self.data["station"]
        station_name = station_data.get("name", f"Station {self.plant_id}")

        return {
            "identifiers": {(DOMAIN, f"station_{self.plant_id}")},
            "name": f"Station {station_name}",
            "manufacturer": "EG4 Electronics",
            "model": "Station",
            "configuration_url": f"{self.client.base_url}/WManage/web/config/plant/edit/{self.plant_id}",
        }

    def get_inverter_object(self, serial: str) -> Optional[BaseInverter]:
        """Get inverter device object by serial number."""
        if not self.station:
            return None

        for inverter in self.station.all_inverters:
            if inverter.serial == serial:
                return inverter

        return None

    def get_battery_object(self, serial: str, battery_index: int) -> Optional[Battery]:
        """Get battery object by inverter serial and battery index."""
        inverter = self.get_inverter_object(serial)
        if not inverter or not hasattr(inverter, 'battery_bank'):
            return None

        if not hasattr(inverter.battery_bank, 'batteries'):
            return None

        for battery in inverter.battery_bank.batteries:
            if battery.index == battery_index:
                return battery

        return None

    # PRESERVED PARAMETER REFRESH METHODS

    async def refresh_all_device_parameters(self) -> None:
        """Refresh parameters for all inverter devices when any parameter changes."""
        try:
            _LOGGER.info(
                "Refreshing parameters for all inverter devices due to parameter change"
            )

            # Get all inverter devices from current data
            if not self.data or "devices" not in self.data:
                _LOGGER.debug(
                    "No device data available for parameter refresh - "
                    "integration may still be initializing"
                )
                return

            inverter_serials = []
            for serial, device_data in self.data["devices"].items():
                device_type = device_data.get("type", "unknown")
                if device_type == "inverter":
                    inverter_serials.append(serial)

            if not inverter_serials:
                _LOGGER.warning("No inverter devices found for parameter refresh")
                return

            # Refresh parameters for all inverters in parallel
            refresh_tasks = []
            for serial in inverter_serials:
                task = self._refresh_device_parameters(serial)
                refresh_tasks.append(task)

            # Execute all parameter refreshes concurrently
            results = await asyncio.gather(*refresh_tasks, return_exceptions=True)

            # Log results
            success_count = 0
            for i, result in enumerate(results):
                serial = inverter_serials[i]
                if isinstance(result, Exception):
                    _LOGGER.error(
                        "Failed to refresh parameters for %s: %s", serial, result
                    )
                else:
                    success_count += 1

            _LOGGER.info(
                "Successfully refreshed parameters for %d/%d inverters",
                success_count,
                len(inverter_serials),
            )

        except Exception as e:
            _LOGGER.error("Error during all-device parameter refresh: %s", e)

    async def async_refresh_device_parameters(self, serial: str) -> None:
        """Public method to refresh parameters for a specific device.

        This method is called by switch entities after parameter changes
        to ensure the state reflects the actual device configuration.

        Args:
            serial: The inverter serial number to refresh parameters for
        """
        try:
            _LOGGER.debug("Refreshing parameters for device %s", serial)
            await self._refresh_device_parameters(serial)

            # Request a coordinator refresh to update all entities
            await self.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)

    async def _refresh_device_parameters(self, serial: str) -> None:
        """Refresh parameters for a specific device."""
        try:
            # Get inverter object for this serial
            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.warning("Cannot find inverter object for serial %s", serial)
                return

            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(inverter)

            # Process responses to update device parameter cache
            parameter_data = {}
            for _, response, _ in process_parameter_responses(
                responses, serial, _LOGGER
            ):
                if response and response.get("success", False):
                    # Merge parameter data from this range
                    for key, value in response.items():
                        if key != "success" and value is not None:
                            parameter_data[key] = value

            # Store parameter data in coordinator data structure
            if hasattr(self, "data") and self.data is not None:
                if "parameters" not in self.data:
                    self.data["parameters"] = {}
                self.data["parameters"][serial] = parameter_data

            _LOGGER.debug(
                "Refreshed %d parameters for device %s", len(parameter_data), serial
            )

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)
            raise

    async def _refresh_missing_parameters(
        self, inverter_serials: List[str], processed_data: Dict[str, Any]
    ) -> None:
        """Refresh parameters for inverters that don't have them yet."""
        try:
            for serial in inverter_serials:
                try:
                    await self._refresh_device_parameters(serial)
                    # Update the processed data with new parameter data
                    if (
                        self.data
                        and "parameters" in self.data
                        and serial in self.data["parameters"]
                    ):
                        processed_data["parameters"][serial] = self.data["parameters"][
                            serial
                        ]
                except Exception as e:
                    _LOGGER.error(
                        "Failed to refresh missing parameters for %s: %s", serial, e
                    )

            # Request a coordinator refresh to update entities with new parameter data
            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error during missing parameter refresh: %s", e)

    async def _hourly_parameter_refresh(self) -> None:
        """Perform hourly parameter refresh for all inverters."""
        try:
            await self.refresh_all_device_parameters()
            # Update last parameter refresh time
            self._last_parameter_refresh = dt_util.utcnow()
        except Exception as e:
            _LOGGER.error("Error during hourly parameter refresh: %s", e)

    def _should_refresh_parameters(self) -> bool:
        """Check if hourly parameter refresh is due."""
        if self._last_parameter_refresh is None:
            return True

        time_since_refresh = dt_util.utcnow() - self._last_parameter_refresh
        return bool(time_since_refresh >= self._parameter_refresh_interval)

    async def set_working_mode(
        self, serial_number: str, function_param: str, enable: bool
    ) -> bool:
        """Set working mode for inverter."""
        try:
            _LOGGER.debug(
                "Setting working mode %s to %s for device %s",
                function_param,
                enable,
                serial_number,
            )

            # Use existing API method
            response = await self.client.control_function_parameter(
                serial_number=serial_number,
                function_param=function_param,
                enable=enable,
            )

            # Refresh standard parameters immediately to get updated working mode state
            await self._refresh_device_parameters(serial_number)

            # Trigger coordinator refresh to update entities
            await self.async_refresh()

            success = response.get("success", False)
            if success:
                _LOGGER.info(
                    "Successfully set working mode %s to %s for device %s",
                    function_param,
                    enable,
                    serial_number,
                )
            else:
                _LOGGER.warning("Working mode control reported failure: %s", response)

            return bool(success)

        except Exception as err:
            _LOGGER.error(
                "Failed to set working mode %s for %s: %s",
                function_param,
                serial_number,
                err,
            )
            return False

    def get_working_mode_state(self, serial_number: str, function_param: str) -> bool:
        """Get current working mode state from cached parameters."""
        try:
            # Get cached parameters from standard parameter cache
            if not self.data or "parameters" not in self.data:
                return False

            parameter_data = self.data["parameters"].get(serial_number, {})
            if not parameter_data:
                return False

            # Map function parameters to parameter register values
            param_key = FUNCTION_PARAM_MAPPING.get(function_param)
            if param_key:
                # Check if parameter exists and is enabled
                param_value = parameter_data.get(param_key, False)
                # Handle both bool and int values
                if isinstance(param_value, bool):
                    is_enabled = param_value
                else:
                    is_enabled = param_value == 1

                return is_enabled

            _LOGGER.warning("Unknown function parameter: %s", function_param)
            return False

        except Exception as err:
            _LOGGER.error(
                "Error getting working mode state for %s: %s", serial_number, err
            )
            return False

    def _should_invalidate_cache(self) -> bool:
        """Check if cache invalidation is needed before top of hour."""
        now = dt_util.utcnow()

        # If we haven't invalidated cache yet today, check if we're close to top of hour
        if self._last_cache_invalidation is None:
            # First run - invalidate if we're within 5 minutes of top of hour
            minutes_to_hour = 60 - now.minute
            return bool(minutes_to_hour <= 5)

        # Check if we've crossed into a new hour since last invalidation
        last_hour = self._last_cache_invalidation.hour
        current_hour = now.hour

        # If hour has changed, we need to invalidate
        if current_hour != last_hour:
            return True

        # If we're in the same hour but within 5 minutes of the next hour
        # and haven't invalidated in the last 10 minutes, invalidate
        minutes_to_hour = 60 - now.minute
        time_since_last = now - self._last_cache_invalidation

        return bool(minutes_to_hour <= 5 and time_since_last >= timedelta(minutes=10))

    def _invalidate_all_caches(self) -> None:
        """Invalidate all caches to ensure fresh data when date changes."""
        try:
            # Clear API response cache
            if hasattr(self.client, "clear_cache"):
                self.client.clear_cache()
                _LOGGER.debug("Cleared API response cache")

            # Update last invalidation time
            self._last_cache_invalidation = dt_util.utcnow()

            _LOGGER.info(
                "Successfully invalidated all caches at %s to prevent date rollover issues",
                self._last_cache_invalidation.strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

        except Exception as e:
            _LOGGER.error("Error invalidating caches: %s", e)

    def _should_perform_session_maintenance(self) -> bool:
        """Check if session maintenance (keepalive) is due."""
        if self._last_session_maintenance is None:
            return True

        time_since_maintenance = dt_util.utcnow() - self._last_session_maintenance
        return bool(time_since_maintenance >= self._session_maintenance_interval)

    async def _perform_session_maintenance(self) -> None:
        """Perform session maintenance to keep session alive."""
        try:
            _LOGGER.debug("Starting session maintenance keepalive")

            # Make a lightweight API call to keep session alive
            if self.station:
                await self.station.refresh_basic_info()

            # Update last maintenance time
            self._last_session_maintenance = dt_util.utcnow()

            _LOGGER.info(
                "Session maintenance keepalive successful at %s (next in %s)",
                self._last_session_maintenance.strftime("%Y-%m-%d %H:%M:%S UTC"),
                self._session_maintenance_interval,
            )

        except Exception as e:
            _LOGGER.warning(
                "Session maintenance keepalive failed (session will be refreshed on next request): %s",
                e,
            )

    async def _async_handle_shutdown(self, event: Any) -> None:
        """Handle Home Assistant stop event to cancel background tasks."""
        _LOGGER.debug("Handling Home Assistant stop event, cancelling background tasks")

        # Cancel any pending refresh operations
        if hasattr(self, "_debounced_refresh") and self._debounced_refresh:
            self._debounced_refresh.async_cancel()
            await asyncio.sleep(0)
            _LOGGER.debug("Cancelled debounced refresh")

        # Cancel all background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete cancellation
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        _LOGGER.debug("All background tasks cancelled and cleaned up")

    async def async_shutdown(self) -> None:
        """Clean up background tasks and event listeners on shutdown."""
        # Remove the shutdown listener if it exists
        if hasattr(self, "_shutdown_listener_remove"):
            self._shutdown_listener_remove()
            _LOGGER.debug("Removed homeassistant_stop event listener")

        # Cancel all background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete cancellation
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        _LOGGER.debug("Coordinator shutdown complete, all background tasks cleaned up")
