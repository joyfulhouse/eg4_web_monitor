"""Data update coordinator for EG4 Web Monitor integration."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    CURRENT_SENSORS,
    DEFAULT_UPDATE_INTERVAL,
    DIVIDE_BY_10_SENSORS,
    DIVIDE_BY_100_SENSORS,
    DOMAIN,
    FUNCTION_PARAM_MAPPING,
    GRIDBOSS_ENERGY_SENSORS,
    GRIDBOSS_FIELD_MAPPING,
    INVERTER_ENERGY_FIELD_MAPPING,
    INVERTER_RUNTIME_FIELD_MAPPING,
    PARALLEL_GROUP_FIELD_MAPPING,
    VOLTAGE_SENSORS,
)
from .eg4_inverter_api import EG4InverterAPI
from .eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError
from .utils import (
    CircuitBreaker,
    apply_sensor_scaling,
    clean_battery_display_name,
    extract_individual_battery_sensors,
    process_parameter_responses,
    read_device_parameters_ranges,
    to_camel_case,
)

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching EG4 Web Monitor data from the API.

    Note: type: ignore[misc] - DataUpdateCoordinator base class lacks proper type stubs in some HA versions.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]

        # Initialize API client with injected session (Platinum tier requirement)
        # Home Assistant manages the aiohttp ClientSession for efficient resource usage
        self.api = EG4InverterAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(CONF_BASE_URL, "https://monitor.eg4electronics.com"),
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
            session=aiohttp_client.async_get_clientsession(hass),
        )

        # Device tracking
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.device_sensors: Dict[str, List[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: Optional[datetime] = None
        self._parameter_refresh_interval = timedelta(hours=1)  # Hourly parameter refresh

        # Cache invalidation tracking
        self._last_cache_invalidation: Optional[datetime] = None

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

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            return await self._fetch_and_process_data()
        except EG4AuthError as e:
            self._handle_auth_error(e)
            return {}  # Unreachable but needed for type checker
        except EG4ConnectionError as e:
            self._handle_connection_error(e)
            return {}  # Unreachable but needed for type checker
        except EG4APIError as e:
            self._handle_api_error(e)
            return {}  # Unreachable but needed for type checker
        except Exception as e:
            self._handle_unexpected_error(e)
            return {}  # Unreachable but needed for type checker

    async def _fetch_and_process_data(self) -> Dict[str, Any]:
        """Fetch and process device data."""
        _LOGGER.debug("Fetching data for plant %s", self.plant_id)

        # Check if cache invalidation is needed before top of hour
        if self._should_invalidate_cache():
            _LOGGER.info("Cache invalidation needed before top of hour, clearing all caches")
            self._invalidate_all_caches()

        # Check if hourly parameter refresh is due
        if self._should_refresh_parameters():
            _LOGGER.info("Hourly parameter refresh is due, refreshing all device parameters")
            # Don't await this to avoid blocking the main data update
            task = self.hass.async_create_task(self._hourly_parameter_refresh())
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        # Get comprehensive data for all devices in the plan
        data = await self.api.get_all_device_data(self.plant_id)

        # Process and structure the data
        processed_data = await self._process_device_data(data)

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

    def _handle_auth_error(self, error: EG4AuthError) -> None:
        """Handle authentication errors."""
        if self._last_available_state:
            _LOGGER.warning(
                "EG4 Web Monitor service unavailable due to authentication error for plant %s: %s",
                self.plant_id,
                error,
            )
            self._last_available_state = False
        _LOGGER.error("Authentication error: %s", error)
        raise ConfigEntryAuthFailed(f"Authentication failed: {error}") from error

    def _handle_connection_error(self, error: EG4ConnectionError) -> None:
        """Handle connection errors."""
        if self._last_available_state:
            _LOGGER.warning(
                "EG4 Web Monitor service unavailable due to connection error for plant %s: %s",
                self.plant_id,
                error,
            )
            self._last_available_state = False
        _LOGGER.error("Connection error: %s", error)
        raise UpdateFailed(f"Connection failed: {error}") from error

    def _handle_api_error(self, error: EG4APIError) -> None:
        """Handle API errors."""
        if self._last_available_state:
            _LOGGER.warning(
                "EG4 Web Monitor service unavailable due to API error for plant %s: %s",
                self.plant_id,
                error,
            )
            self._last_available_state = False
        _LOGGER.error("API error: %s", error)
        raise UpdateFailed(f"API error: {error}") from error

    def _handle_unexpected_error(self, error: Exception) -> None:
        """Handle unexpected errors."""
        if self._last_available_state:
            _LOGGER.warning(
                "EG4 Web Monitor service unavailable due to unexpected error for plant %s: %s",
                self.plant_id,
                error,
            )
            self._last_available_state = False
        _LOGGER.exception("Unexpected error updating data: %s", error)
        raise UpdateFailed(f"Unexpected error: {error}") from error

    async def _process_device_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and structure device data for Home Assistant.

        This orchestrates the entire device data processing pipeline:
        1. Initialize processed data structure
        2. Process individual devices by type
        3. Process parallel group data
        4. Handle parameter refresh for new devices

        Args:
            raw_data: Raw device data from API

        Returns:
            Processed data structure ready for Home Assistant
        """
        # Initialize processed data structure
        processed = self._initialize_processed_data(raw_data)

        # Store device info temporarily for model extraction
        self._temp_device_info = raw_data.get("device_info", {})

        # Process individual devices
        await self._process_individual_devices(raw_data, processed)

        # Process parallel group data
        await self._process_parallel_group_if_available(raw_data, processed)

        # Process individual energy batch with rate limiting
        await self._process_energy_batch_if_pending(processed)

        # Clean up temporary device info
        self._cleanup_temp_device_info()

        # Handle parameter refresh for new inverters
        await self._handle_parameter_refresh(processed)

        return processed

    def _initialize_processed_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize the processed data structure.

        Args:
            raw_data: Raw device data from API

        Returns:
            Initialized processed data dictionary
        """
        processed = {
            "plant_id": self.plant_id,
            "devices": {},
            "device_info": raw_data.get("device_info", {}),
            "last_update": dt_util.utcnow(),
        }

        # Preserve existing parameter data from previous updates
        if self.data and "parameters" in self.data:
            processed["parameters"] = self.data["parameters"]

        return processed

    async def _process_individual_devices(self, raw_data: Dict[str, Any], processed: Dict[str, Any]) -> None:
        """Process each individual device by type.

        Args:
            raw_data: Raw device data from API
            processed: Processed data dictionary to populate
        """
        for serial, device_data in raw_data.get("devices", {}).items():
            if "error" in device_data:
                _LOGGER.error("Error in device %s: %s", serial, device_data["error"])
                # Keep device in data but mark it as having an error
                processed["devices"][serial] = {
                    "type": "unknown",
                    "model": "Unknown",
                    "error": device_data["error"],
                    "sensors": {},
                    "batteries": {},
                }
                continue

            device_type = device_data.get("type", "unknown")

            if device_type == "inverter":
                processed["devices"][serial] = await self._process_inverter_data(serial, device_data)
            elif device_type == "gridboss":
                processed["devices"][serial] = await self._process_gridboss_data(serial, device_data)
            else:
                _LOGGER.warning("Unknown device type '%s' for device %s", device_type, serial)

    async def _process_parallel_group_if_available(self, raw_data: Dict[str, Any], processed: Dict[str, Any]) -> None:
        """Process parallel group energy data if available.

        Args:
            raw_data: Raw device data from API
            processed: Processed data dictionary to populate
        """
        parallel_energy = raw_data.get("parallel_energy")
        parallel_groups_info = raw_data.get("parallel_groups_info", [])
        _LOGGER.debug(
            "Parallel group data - success: %s, groups: %s",
            parallel_energy.get("success") if parallel_energy else None,
            parallel_groups_info,
        )

        # Only create parallel group if the API indicates parallel groups exist
        if parallel_energy and parallel_energy.get("success"):
            _LOGGER.debug("Processing parallel group energy data")
            processed["devices"]["parallel_group"] = await self._process_parallel_group_data(
                parallel_energy, parallel_groups_info
            )

    async def _process_energy_batch_if_pending(self, processed: Dict[str, Any]) -> None:
        """Process individual inverter energy data in batches if pending.

        Args:
            processed: Processed data dictionary to populate
        """
        if self._pending_individual_energy_serials:
            await self._process_individual_energy_batch(processed)
            self._pending_individual_energy_serials.clear()

    def _cleanup_temp_device_info(self) -> None:
        """Clean up temporary device info storage."""
        if hasattr(self, "_temp_device_info"):
            delattr(self, "_temp_device_info")

    async def _handle_parameter_refresh(self, processed: Dict[str, Any]) -> None:
        """Handle parameter refresh for inverters that don't have parameters.

        Args:
            processed: Processed data dictionary to check and update
        """
        # Ensure parameters dict exists
        if "parameters" not in processed:
            processed["parameters"] = {}

        # Find inverters needing parameter refresh
        inverters_needing_params = [
            serial
            for serial, device_data in processed["devices"].items()
            if device_data.get("type") == "inverter" and serial not in processed["parameters"]
        ]

        # Refresh parameters for new inverters asynchronously
        if inverters_needing_params:
            _LOGGER.info(
                "Refreshing parameters for %d new inverters: %s",
                len(inverters_needing_params),
                inverters_needing_params,
            )
            # Don't await this to avoid blocking the data update
            self.hass.async_create_task(self._refresh_missing_parameters(inverters_needing_params, processed))

        # Log availability of working mode parameters
        inverter_serials = [
            serial for serial, device_data in processed["devices"].items() if device_data.get("type") == "inverter"
        ]
        if inverter_serials:
            _LOGGER.info(
                "Working mode parameters (AC Charge, PV Charge Priority, Forced Discharge, "
                "Peak Shaving, Battery Backup) available from parameter cache for %d inverters",
                len(inverter_serials),
            )

    async def _process_inverter_data(self, serial: str, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process inverter device data."""
        runtime = device_data.get("runtime", {})
        energy = device_data.get("energy", {})
        battery = device_data.get("battery", {})

        processed: Dict[str, Any] = {
            "serial": serial,
            "type": "inverter",
            "model": self._extract_model_from_overview(serial),
            # Extract firmware from runtime response
            "firmware_version": runtime.get("fwCode", "1.0.0") if runtime else "1.0.0",
            "sensors": {},
            "binary_sensors": {},
            "batteries": {},
        }

        # Process runtime data
        if runtime and isinstance(runtime, dict):
            processed["sensors"].update(self._extract_runtime_sensors(runtime))
            processed["binary_sensors"].update(self._extract_runtime_binary_sensors(runtime))

        # Process energy data
        if energy and isinstance(energy, dict):
            processed["sensors"].update(self._extract_energy_sensors(energy))

        # Store inverter serial for batched individual energy processing
        self._pending_individual_energy_serials.append(serial)
        _LOGGER.debug("Added inverter %s to individual energy processing queue", serial)

        # Process battery data
        if battery and isinstance(battery, dict):
            self._process_battery_data(serial, battery, processed)

        # Process quick charge status
        await self._process_quick_charge_status(serial, processed)

        # Process battery backup status
        await self._process_battery_backup_status(serial, processed)

        return processed

    def _process_battery_data(self, serial: str, battery: Dict[str, Any], processed: Dict[str, Any]) -> None:
        """Process battery data including individual battery array.

        Args:
            serial: Inverter serial number
            battery: Battery data dictionary
            processed: Processed data dictionary to update
        """
        # Non-array battery data (inverter-level)
        processed["sensors"].update(self._extract_battery_sensors(battery))
        processed["binary_sensors"].update(self._extract_battery_binary_sensors(battery))

        # Individual batteries from batteryArray
        battery_array = battery.get("batteryArray", [])
        if isinstance(battery_array, list):
            _LOGGER.debug(
                "Found batteryArray with %d batteries for device %s",
                len(battery_array),
                serial,
            )
            for i, bat_data in enumerate(battery_array):
                if isinstance(bat_data, dict):
                    _LOGGER.debug(
                        "Battery %d data fields available: %s",
                        i + 1,
                        list(bat_data.keys()),
                    )
                    raw_battery_key = bat_data.get("batteryKey", f"BAT{i + 1:03d}")
                    battery_key = clean_battery_display_name(raw_battery_key, serial)
                    battery_sensors = extract_individual_battery_sensors(bat_data)
                    processed["batteries"][battery_key] = battery_sensors

    async def _process_quick_charge_status(self, serial: str, processed: Dict[str, Any]) -> None:
        """Process quick charge status for inverter.

        Args:
            serial: Inverter serial number
            processed: Processed data dictionary to update
        """
        try:
            quick_charge_status = await self.api.get_quick_charge_status(serial)
            processed["quick_charge_status"] = quick_charge_status
            _LOGGER.debug("Retrieved quick charge status for device %s", serial)
        except Exception as e:
            _LOGGER.debug("Failed to get quick charge status for device %s: %s", serial, e)
            # Don't fail the entire update if quick charge status fails
            processed["quick_charge_status"] = {"status": False, "error": str(e)}

    async def _process_battery_backup_status(self, serial: str, processed: Dict[str, Any]) -> None:
        """Process battery backup status by reading FUNC_EPS_EN parameter.

        Args:
            serial: Inverter serial number
            processed: Processed data dictionary to update
        """
        try:
            # Read base parameters (0-127) where FUNC_EPS_EN is likely located
            # (cached with 2-minute TTL)
            battery_backup_params = await self.api.read_parameters(serial, 0, 127)
            func_eps_en = None
            if battery_backup_params and battery_backup_params.get("success"):
                func_eps_en = battery_backup_params.get("FUNC_EPS_EN")

            if func_eps_en is not None:
                self._handle_battery_backup_parameter(serial, func_eps_en, processed)
            else:
                processed["battery_backup_status"] = {
                    "enabled": False,
                    "error": "FUNC_EPS_EN parameter not found in base parameters",
                }
                _LOGGER.warning(
                    "FUNC_EPS_EN parameter not found in base parameters for device %s",
                    serial,
                )
        except Exception as e:
            _LOGGER.debug("Failed to get battery backup status for device %s: %s", serial, e)
            # Don't fail the entire update if battery backup status fails
            processed["battery_backup_status"] = {"enabled": False, "error": str(e)}

    def _handle_battery_backup_parameter(self, serial: str, func_eps_en: Any, processed: Dict[str, Any]) -> None:
        """Handle battery backup parameter conversion and storage.

        Args:
            serial: Inverter serial number
            func_eps_en: Raw FUNC_EPS_EN parameter value
            processed: Processed data dictionary to update
        """
        # Enhanced debugging to understand the actual API response
        _LOGGER.info(
            "Battery backup parameter for %s: FUNC_EPS_EN = %r (type: %s)",
            serial,
            func_eps_en,
            type(func_eps_en).__name__,
        )

        # Convert to boolean with explicit handling of different value types
        enabled = self._convert_func_eps_en_to_bool(func_eps_en)

        processed["battery_backup_status"] = {
            "FUNC_EPS_EN": func_eps_en,
            "enabled": enabled,
        }
        _LOGGER.info(
            "Battery backup status for %s: raw=%r, enabled=%s",
            serial,
            func_eps_en,
            enabled,
        )

        # Update the coordinator's parameter cache with this fresh data
        if "parameters" not in processed:
            processed["parameters"] = {}
        if serial not in processed["parameters"]:
            processed["parameters"][serial] = {}
        processed["parameters"][serial]["FUNC_EPS_EN"] = func_eps_en

    def _convert_func_eps_en_to_bool(self, func_eps_en: Any) -> bool:
        """Convert FUNC_EPS_EN parameter value to boolean.

        Args:
            func_eps_en: Raw parameter value

        Returns:
            Boolean representation of the parameter value
        """
        if func_eps_en is None:
            return False
        if isinstance(func_eps_en, str):
            # Handle string values like "1", "0", "true", "false"
            return func_eps_en.lower() not in (
                "0",
                "false",
                "off",
                "disabled",
                "",
            )
        if isinstance(func_eps_en, (int, float)):
            # Handle numeric values where 0 = disabled, non-zero = enabled
            return bool(func_eps_en != 0)
        # Default boolean conversion
        return bool(func_eps_en)

    async def _process_individual_energy_batch(self, processed: Dict[str, Any]) -> None:
        """Process individual inverter energy data in batches with rate limiting."""
        serials = self._pending_individual_energy_serials
        if not serials:
            return

        _LOGGER.debug(
            "Processing individual energy data for %d inverters with rate limiting",
            len(serials),
        )

        # Process in batches to avoid API overload
        from .const import API_BATCH_DELAY, API_BATCH_SIZE

        batch_size = API_BATCH_SIZE
        delay_between_batches = API_BATCH_DELAY

        for i in range(0, len(serials), batch_size):
            batch = serials[i : i + batch_size]
            _LOGGER.debug("Processing batch %d: %s", i // batch_size + 1, batch)

            # Process batch concurrently but limit batch size
            tasks = []
            for serial in batch:
                tasks.append(self._fetch_individual_energy(serial))

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Apply results to processed data
                for serial, result in zip(batch, results, strict=True):
                    if isinstance(result, Exception):
                        _LOGGER.debug("Failed to get individual energy for %s: %s", serial, result)
                        continue

                    # Note: asyncio.gather with return_exceptions=True returns Union[T, BaseException]
                    # We've already filtered out exceptions above, safe to cast
                    if (
                        result
                        and result.get("success")  # type: ignore[union-attr]
                        and serial in processed["devices"]
                    ):
                        _LOGGER.debug(
                            "Individual energy API response for %s: %s",
                            serial,
                            list(result.keys()),  # type: ignore[union-attr]
                        )
                        energy_sensors = self._extract_energy_sensors(result)  # type: ignore[arg-type]
                        _LOGGER.debug(
                            "Extracted %d energy sensors: %s",
                            len(energy_sensors),
                            list(energy_sensors.keys()),
                        )
                        processed["devices"][serial]["sensors"].update(energy_sensors)
                        _LOGGER.debug(
                            "Added %d individual energy sensors for %s",
                            len(energy_sensors),
                            serial,
                        )
                    else:
                        _LOGGER.warning(
                            "Invalid individual energy response for %s: success=%s, serial_in_devices=%s",
                            serial,
                            result.get("success") if result else "None",  # type: ignore[union-attr]
                            serial in processed["devices"],
                        )

            except Exception as e:
                _LOGGER.warning("Error processing individual energy batch: %s", e)

            # Add delay between batches (except for last batch)
            if i + batch_size < len(serials):
                await asyncio.sleep(delay_between_batches)

    async def _fetch_individual_energy(self, serial: str) -> Optional[Dict[str, Any]]:
        """Fetch individual inverter energy data with error handling."""
        try:
            result = await self.api.get_inverter_energy_info(serial)
            if result and result.get("success"):
                return result
            _LOGGER.debug("No individual energy data for %s", serial)
            return None
        except Exception as e:
            _LOGGER.debug("Failed to fetch individual energy for %s: %s", serial, e)
            return None

    async def _process_gridboss_data(self, serial: str, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process GridBOSS device data."""
        midbox = device_data.get("midbox", {})

        processed = {
            "serial": serial,
            "type": "gridboss",
            "model": self._extract_model_from_overview(serial),
            "firmware_version": midbox.get("fwCode", "1.0.0"),  # Extract firmware from midbox response
            "sensors": {},
            "binary_sensors": {},
        }

        # Process midbox data
        if midbox and isinstance(midbox, dict):
            _LOGGER.debug("Raw midbox response structure for %s: %s", serial, list(midbox.keys()))
            midbox_data = midbox.get("midboxData", {})
            if isinstance(midbox_data, dict):
                _LOGGER.debug(
                    "Processing midboxData for %s with fields: %s",
                    serial,
                    list(midbox_data.keys()),
                )
                processed["sensors"].update(self._extract_gridboss_sensors(midbox_data))
                binary_sensors = self._extract_gridboss_binary_sensors(midbox_data)
                processed["binary_sensors"].update(binary_sensors)
            else:
                _LOGGER.debug(
                    "No midboxData found for %s, using raw midbox data: %s",
                    serial,
                    list(midbox.keys()),
                )
                # Try using the raw midbox data if midboxData is not nested
                processed["sensors"].update(self._extract_gridboss_sensors(midbox))
                gridboss_binary = self._extract_gridboss_binary_sensors(midbox)
                processed["binary_sensors"].update(gridboss_binary)

        return processed

    async def _process_parallel_group_data(
        self,
        parallel_energy: Optional[Dict[str, Any]] = None,
        parallel_groups_info: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Process parallel group energy data."""
        _LOGGER.debug(
            "Processing parallel group data - energy: %s, groups: %s",
            bool(parallel_energy),
            parallel_groups_info,
        )

        # Extract the group name from parallel groups info
        group_name = "Parallel Group"  # Default fallback
        if parallel_groups_info and len(parallel_groups_info) > 0:
            # Extract group letter from first group
            first_group = parallel_groups_info[0]
            group_letter = first_group.get("parallelGroup", "")
            _LOGGER.debug("Parallel group naming - group_letter: %s", group_letter)

            if group_letter:
                # Always include the letter if available, regardless of group coun
                group_name = f"Parallel Group {group_letter}"
                _LOGGER.debug("Set parallel group name to: %s", group_name)
            else:
                _LOGGER.debug("No group letter found, using default name: %s", group_name)

        processed: Dict[str, Any] = {
            "serial": "parallel_group",
            "type": "parallel_group",
            "model": group_name,
            "sensors": {},
            "binary_sensors": {},
        }

        # Extract parallel group energy sensors if available
        if parallel_energy:
            processed["sensors"].update(self._extract_parallel_group_sensors(parallel_energy))
            processed["binary_sensors"].update(self._extract_parallel_group_binary_sensors(parallel_energy))

        return processed

    def _extract_model_from_overview(self, serial: str) -> str:
        """Extract device model from overview data."""
        # Check device_info from login response first (most reliable)
        if hasattr(self, "data") and self.data:
            device_info = self.data.get("device_info", {})
            if serial in device_info:
                model = device_info[serial].get("deviceTypeText4APP")
                if model:
                    return str(model)

            # Note: parallel_groups and inverter_overview discovery endpoints
            # have been disabled as they were problematic and not essential

        # Store device info temporarily during device setup for fallback
        if hasattr(self, "_temp_device_info"):
            device_data = self._temp_device_info.get(serial, {})
            model = device_data.get("deviceTypeText4APP")
            if model:
                return str(model)

        return "Unknown"

    def _extract_runtime_sensors(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from runtime response."""
        _LOGGER.debug("Runtime data fields available: %s", list(runtime.keys()))
        sensors = {}

        # Use shared field mapping from const.py to reduce duplication
        field_mapping = INVERTER_RUNTIME_FIELD_MAPPING

        # Process each field mapping
        for api_field, sensor_type in field_mapping.items():
            if api_field in runtime:
                value = runtime[api_field]
                if value is not None:
                    processed_value = self._process_runtime_field_value(api_field, sensor_type, value)
                    if processed_value is not None:
                        sensors[sensor_type] = processed_value

        # Calculate net grid power for standard inverters
        self._calculate_grid_power(runtime, sensors)

        return sensors

    def _process_runtime_field_value(self, api_field: str, sensor_type: str, value: Any) -> Optional[Any]:
        """Process a single runtime field value with appropriate scaling.

        Args:
            api_field: API field name
            sensor_type: Sensor type identifier
            value: Raw field value

        Returns:
            Processed value or None if processing failed
        """
        # Use shared sensor list from const.py to reduce duplication
        divide_by_10_sensors = DIVIDE_BY_10_SENSORS

        # Voltage fields that need division by 10
        divide_voltage_by_10_fields = {"vacr", "vpv1", "vpv2", "vpv3", "vBat"}

        # Apply division by 10 for today/daily energy sensors
        if sensor_type in divide_by_10_sensors:
            try:
                return float(value) / 10.0
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not convert %s value %s to float for division",
                    sensor_type,
                    value,
                )
                return None

        # Apply division by 10 for voltage sensors (vacr field)
        if api_field in divide_voltage_by_10_fields:
            try:
                return float(value) / 10.0
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not convert %s value %s to float for voltage division",
                    api_field,
                    value,
                )
                return None

        # Apply camel casing for status text
        if sensor_type == "status_text" and isinstance(value, str):
            return to_camel_case(value)

        return value

    def _calculate_grid_power(self, runtime: Dict[str, Any], sensors: Dict[str, Any]) -> None:
        """Calculate net grid power from import and export values.

        Args:
            runtime: Runtime data dictionary
            sensors: Sensors dictionary to update
        """
        # Calculate net grid power for standard inverters
        # pToUser = import from grid (positive when importing)
        # pToGrid = export to grid (positive when exporting)
        # grid_power = pToUser - pToGrid (positive = importing, negative = exporting)
        if "pToUser" in runtime and "pToGrid" in runtime:
            try:
                p_to_user = float(runtime["pToUser"])  # Import from grid
                p_to_grid = float(runtime["pToGrid"])  # Export to grid
                sensors["grid_power"] = p_to_user - p_to_grid
                _LOGGER.debug(
                    "Calculated grid_power: %s - %s = %s W (positive=importing, negative=exporting)",
                    p_to_user,
                    p_to_grid,
                    sensors["grid_power"],
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Could not calculate grid_power from pToUser=%s and pToGrid=%s: %s",
                    runtime.get("pToUser"),
                    runtime.get("pToGrid"),
                    e,
                )

    def _extract_runtime_binary_sensors(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from runtime response.

        FUTURE IMPLEMENTATION: This method is reserved for future binary sensor support.
        Potential binary sensors include:
        - Grid connection status
        - Battery charging/discharging state
        - Fault/warning indicators
        - Operating mode status flags

        Args:
            runtime: Runtime data dictionary from API

        Returns:
            Empty dict (no binary sensors currently implemented)
        """
        _ = runtime  # Explicitly mark parameter as unused but preserved for interface
        return {}

    def _extract_energy_sensors(self, energy: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from energy response."""
        _LOGGER.debug("Energy data fields available: %s", list(energy.keys()))
        sensors = {}

        # Use shared field mapping from const.py to reduce duplication
        field_mapping = INVERTER_ENERGY_FIELD_MAPPING

        # Use shared sensor list from const.py to reduce duplication
        divide_by_10_sensors = DIVIDE_BY_10_SENSORS

        for api_field, sensor_type in field_mapping.items():
            if api_field in energy:
                value = energy[api_field]
                if value is not None:
                    # Apply division by 10 for energy sensors to convert to kWh
                    if sensor_type in divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert %s value %s to float for division",
                                sensor_type,
                                value,
                            )
                            continue
                    sensors[sensor_type] = value

        return sensors

    def _extract_battery_sensors(self, battery: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from battery response (non-array data)."""
        sensors = {}

        field_mapping = {
            "batteryVoltage": "battery_voltage",
            "batteryCurrent": "battery_current",
            "batteryPower": "battery_power",
            "stateOfCharge": "state_of_charge",
            "stateOfHealth": "state_of_health",
            "temperature": "temperature",
            # Battery power flow sensors from getBatteryInfo
            "pCharge": "battery_charge_power",
            "pDisCharge": "battery_discharge_power",
            "batPower": "battery_power",
            "batStatus": "battery_status",
        }

        for api_field, sensor_type in field_mapping.items():
            if api_field in battery:
                value = battery[api_field]
                if value is not None:
                    # Apply scaling for sensors that need i
                    scaled_value = apply_sensor_scaling(sensor_type, value, "inverter")
                    sensors[sensor_type] = scaled_value

        return sensors

    def _extract_battery_binary_sensors(self, battery: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from battery response.

        FUTURE IMPLEMENTATION: This method is reserved for future binary sensor support.
        Potential binary sensors include:
        - Battery charging status
        - Battery health warnings
        - Cell imbalance alerts
        - Temperature warnings
        - Cycle count thresholds

        Args:
            battery: Battery data dictionary from API

        Returns:
            Empty dict (no binary sensors currently implemented)
        """
        _ = battery  # Explicitly mark parameter as unused but preserved for interface
        return {}

    def _extract_gridboss_sensors(self, midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from GridBOSS midbox response.

        GridBOSS (MID device) provides grid management and interconnection data.
        This includes grid power flow, UPS functionality, load management,
        smart load ports, AC coupling, and generator integration.

        Example data extraction:
            >>> midbox_data = {
            ...     "gridPower": 1500.0,
            ...     "hybridPower": 500.0,
            ...     "smartLoadPower": 200.0,
            ...     "gridFrequency": 6000  # 60.00 Hz (÷100)
            ... }
            >>> sensors = coordinator._extract_gridboss_sensors(midbox_data)
            >>> sensors["grid_power"]
            1500.0
            >>> sensors["grid_frequency"]
            60.0

        Args:
            midbox_data: GridBOSS midbox runtime data dictionary from API

        Returns:
            Dictionary mapping sensor types to their values with appropriate scaling
        """
        _LOGGER.debug("GridBOSS midbox data fields available: %s", list(midbox_data.keys()))
        sensors = {}

        # Use field mapping from const.py to avoid duplication
        field_mapping = {
            # Core Power sensors (not in const.py)
            "hybridPower": "hybrid_power",
            "smartLoadPower": "smart_load_power",
            **GRIDBOSS_FIELD_MAPPING,  # Import all the standardized mappings
        }

        for api_field, sensor_type in field_mapping.items():
            if api_field in midbox_data:
                value = midbox_data[api_field]
                if value is not None:
                    # Smart Port Status needs text conversion BEFORE filtering and scaling
                    if sensor_type.startswith("smart_port") and sensor_type.endswith("_status"):
                        _LOGGER.debug(
                            "Converting Smart Port status %s: raw_value=%s, type=%s",
                            sensor_type,
                            value,
                            type(value),
                        )
                        status_map = {0: "Unused", 1: "Smart Load", 2: "AC Couple"}
                        converted_value = status_map.get(value, f"Unknown ({value})")
                        _LOGGER.debug(
                            "Smart Port status %s converted from %s to %s",
                            sensor_type,
                            value,
                            converted_value,
                        )
                        value = converted_value
                        # Smart Port status sensors are always included, skip filtering and scaling
                        sensors[sensor_type] = value
                        continue

                    # Use sensor lists from const.py to avoid duplication
                    gridboss_divide_by_10_sensors = GRIDBOSS_ENERGY_SENSORS | VOLTAGE_SENSORS | CURRENT_SENSORS

                    # GridBOSS frequency sensors need division by 100
                    # Use frequency sensors from const.py to avoid duplication
                    gridboss_divide_by_100_sensors = DIVIDE_BY_100_SENSORS

                    if sensor_type in gridboss_divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert GridBOSS %s value %s to float for division by 10",
                                sensor_type,
                                value,
                            )
                            continue
                    elif sensor_type in gridboss_divide_by_100_sensors:
                        try:
                            value = float(value) / 100.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert GridBOSS %s value %s to float for division by 100",
                                sensor_type,
                                value,
                            )
                            continue

                    # Zero-value filtering for GridBOSS sensors
                    # GridBOSS sensors should be created regardless of value for better monitoring
                    # if should_filter_zero_sensor(sensor_type, value):
                    #     _LOGGER.debug("Skipping zero-value %s sensor: %s", sensor_type, value)
                    #     continue

                    sensors[sensor_type] = value

        # Filter out sensors for unused Smart Ports (status = 0)
        sensors = self._filter_unused_smart_port_sensors(sensors, midbox_data)

        # Calculate aggregate sensors from individual L1/L2 values
        self._calculate_gridboss_aggregates(sensors)

        return sensors

    def _calculate_gridboss_aggregates(self, sensors: Dict[str, Any]) -> None:
        """Calculate aggregate sensor values from individual L1/L2 values."""
        # Calculate Smart Load aggregate power from individual ports
        self._calculate_smart_load_aggregates(sensors)

        # Calculate total power values from L1/L2 components
        self._calculate_dual_leg_power_aggregates(sensors)

        # Calculate AC Couple aggregate values for each port
        self._calculate_ac_couple_aggregates(sensors)

    def _calculate_smart_load_aggregates(self, sensors: Dict[str, Any]) -> None:
        """Calculate Smart Load aggregate power from individual ports.

        Args:
            sensors: Sensors dictionary to update
        """
        smart_load_powers = []
        for port in range(1, 5):
            l1_key = f"smart_load{port}_power_l1"
            l2_key = f"smart_load{port}_power_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_power = self._safe_numeric(sensors[l1_key])
                l2_power = self._safe_numeric(sensors[l2_key])
                port_power = l1_power + l2_power
                sensors[f"smart_load{port}_power"] = port_power
                smart_load_powers.append(port_power)

        # Calculate total smart load power
        if smart_load_powers:
            sensors["smart_load_power"] = sum(smart_load_powers)

    def _calculate_dual_leg_power_aggregates(self, sensors: Dict[str, Any]) -> None:
        """Calculate total power values from L1/L2 components.

        Args:
            sensors: Sensors dictionary to update
        """
        # Define power pairs to aggregate
        power_pairs = [
            ("grid_power_l1", "grid_power_l2", "grid_power"),
            ("ups_power_l1", "ups_power_l2", "ups_power"),
            ("load_power_l1", "load_power_l2", "load_power"),
            ("generator_power_l1", "generator_power_l2", "generator_power"),
        ]

        for l1_key, l2_key, total_key in power_pairs:
            if l1_key in sensors and l2_key in sensors:
                l1_value = self._safe_numeric(sensors[l1_key])
                l2_value = self._safe_numeric(sensors[l2_key])
                sensors[total_key] = l1_value + l2_value

    def _calculate_ac_couple_aggregates(self, sensors: Dict[str, Any]) -> None:
        """Calculate AC Couple aggregate values for each port.

        Args:
            sensors: Sensors dictionary to update
        """
        # Calculate AC Couple aggregate today values for each port
        for port in range(1, 5):
            self._calculate_ac_couple_port_aggregate(sensors, port, "today")

        # Calculate AC Couple aggregate total values for each port
        for port in range(1, 5):
            self._calculate_ac_couple_port_aggregate(sensors, port, "total")

    def _calculate_ac_couple_port_aggregate(self, sensors: Dict[str, Any], port: int, metric_type: str) -> None:
        """Calculate AC Couple aggregate for a specific port and metric type.

        Args:
            sensors: Sensors dictionary to update
            port: Port number (1-4)
            metric_type: Type of metric ("today" or "total")
        """
        l1_key = f"ac_couple{port}_{metric_type}_l1"
        l2_key = f"ac_couple{port}_{metric_type}_l2"
        if l1_key in sensors and l2_key in sensors:
            l1_val = self._safe_numeric(sensors[l1_key])
            l2_val = self._safe_numeric(sensors[l2_key])
            sensors[f"ac_couple{port}_{metric_type}"] = l1_val + l2_val

    @staticmethod
    def _safe_numeric(value: Any) -> float:
        """Safely convert value to numeric, defaulting to 0.

        Args:
            value: Value to convert

        Returns:
            Numeric value or 0.0 if conversion fails
        """
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _filter_unused_smart_port_sensors(self, sensors: Dict[str, Any], midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter out sensors for unused Smart Ports (status = 0)."""
        # Get Smart Port status values from raw midbox data
        smart_port_statuses = {}
        for port in range(1, 5):
            status_api_field = f"smartPort{port}Status"
            if status_api_field in midbox_data:
                status_value = midbox_data[status_api_field]
                smart_port_statuses[port] = status_value
                _LOGGER.debug("Smart Port %d status: %s", port, status_value)

        # Identify sensors to remove for unused Smart Ports (status = 0)
        sensors_to_remove = []
        for port, status in smart_port_statuses.items():
            if status == 0:  # Unused Smart Por
                _LOGGER.debug("Smart Port %d is unused (status=0), removing related sensors", port)
                # Remove Smart Load power sensors
                sensors_to_remove.extend(
                    [
                        f"smart_load{port}_power_l1",
                        f"smart_load{port}_power_l2",
                    ]
                )
                # Remove Smart Load energy sensors (daily)
                sensors_to_remove.extend(
                    [
                        f"smart_load{port}_l1",
                        f"smart_load{port}_l2",
                    ]
                )
                # Remove Smart Load energy sensors (lifetime)
                sensors_to_remove.extend(
                    [
                        f"smart_load{port}_lifetime_l1",
                        f"smart_load{port}_lifetime_l2",
                    ]
                )
                # Note: Keep the status sensor itself for visibility

        # Remove the identified sensors
        filtered_sensors = sensors.copy()
        for sensor_key in sensors_to_remove:
            if sensor_key in filtered_sensors:
                del filtered_sensors[sensor_key]
                _LOGGER.debug("Removed unused Smart Port sensor: %s", sensor_key)

        _LOGGER.debug("Filtered %d unused Smart Port sensors", len(sensors_to_remove))
        return filtered_sensors

    def _extract_gridboss_binary_sensors(self, _midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from GridBOSS midbox response."""
        return {}

    def get_device_info(self, serial: str) -> Optional[DeviceInfo]:
        """Get device information for a specific serial number."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        # Device info debug logging removed for performance

        # Special handling for parallel group device naming
        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "unknown")

        if device_type == "parallel_group":
            # Use just the model name for parallel groups (e.g., "Parallel Group A")
            device_name = model
        else:
            device_name = f"{model} {serial}"  # Normal devices include serial number

        # Build DeviceInfo object with proper typing
        base_info: DeviceInfo = {
            "identifiers": {(DOMAIN, serial)},
            "name": device_name,
            "manufacturer": "EG4 Electronics",
            "model": model,
        }

        # Add firmware version and serial number only for actual devices, not parallel groups
        if device_type != "parallel_group":
            base_info["serial_number"] = serial

            # Get firmware version for GridBOSS and inverter devices
            sw_version = "1.0.0"  # Default fallback
            if device_type in ["gridboss", "inverter"]:
                sw_version = device_data.get("firmware_version", "1.0.0")
            base_info["sw_version"] = sw_version

        # Add via_device for proper device hierarchy
        if device_type in ["inverter", "gridboss"]:
            # Check if this device belongs to a parallel group
            parallel_group_serial = self._get_parallel_group_for_device(serial)
            if parallel_group_serial:
                base_info["via_device"] = (DOMAIN, parallel_group_serial)

        return base_info

    def _get_parallel_group_for_device(self, device_serial: str) -> Optional[str]:
        """Get the parallel group serial that contains this device."""
        if not self.data or "devices" not in self.data:
            return None

        # Check parallel groups info to see which devices belong to which group
        parallel_groups_info = self.data.get("parallel_groups_info", [])
        if parallel_groups_info:
            for group in parallel_groups_info:
                # Check if this device is listed in the group's inverter lis
                inverter_list = group.get("inverterList", [])
                for inverter in inverter_list:
                    if inverter.get("serialNum") == device_serial:
                        # This device belongs to this parallel group
                        # Find the actual parallel group device serial in our devices
                        for serial, device_data in self.data["devices"].items():
                            if device_data.get("type") == "parallel_group":
                                return str(serial)  # Return the actual parallel group device serial
                        # If no parallel group device found, don't set via_device
                        return None

        # Fallback: if no specific group membership found but a parallel group exists,
        # assume all inverter/gridboss devices are part of i
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                # Found a parallel group - return its serial as the paren
                return str(serial)

        return None

    def get_battery_device_info(self, serial: str, battery_key: str) -> Optional[DeviceInfo]:
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

        return DeviceInfo(
            identifiers={(DOMAIN, f"{serial}_{battery_key}")},
            name=f"Battery {clean_battery_name}",
            manufacturer="EG4 Electronics",
            model="Battery Module",
            sw_version=battery_firmware,
            via_device=(DOMAIN, serial),  # Link battery to its parent inverter
        )

    def _extract_parallel_group_sensors(self, parallel_energy: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from parallel group energy response."""
        _LOGGER.debug(
            "Parallel group energy data fields available: %s",
            list(parallel_energy.keys()),
        )
        sensors = {}

        # Use shared field mapping from const.py to reduce duplication
        field_mapping = PARALLEL_GROUP_FIELD_MAPPING

        # Use shared sensor list from const.py to reduce duplication
        divide_by_10_sensors = DIVIDE_BY_10_SENSORS

        for api_field, sensor_type in field_mapping.items():
            if api_field in parallel_energy:
                value = parallel_energy[api_field]
                if value is not None:
                    # Apply division by 10 for energy sensors to convert to kWh
                    if sensor_type in divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert %s value %s to float for division",
                                sensor_type,
                                value,
                            )
                            continue
                    sensors[sensor_type] = value

        return sensors

    def _extract_parallel_group_binary_sensors(
        self,
        parallel_energy: Dict[str, Any],  # pylint: disable=unused-argument
    ) -> Dict[str, Any]:
        """Extract binary sensor data from parallel group energy response."""
        return {}

    async def refresh_all_device_parameters(self) -> None:
        """Refresh parameters for all inverter devices when any parameter changes."""
        try:
            _LOGGER.info("Refreshing parameters for all inverter devices due to parameter change")

            # Get all inverter devices from current data
            if not self.data or "devices" not in self.data:
                _LOGGER.debug("No device data available for parameter refresh - integration may still be initializing")
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
                    _LOGGER.error("Failed to refresh parameters for %s: %s", serial, result)
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
            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(self.api, serial)

            # Process responses to update device parameter cache
            parameter_data = {}
            for _, response, _ in process_parameter_responses(responses, serial, _LOGGER):
                if response and response.get("success", False):
                    # Merge parameter data from this range
                    for key, value in response.items():
                        if key != "success" and value is not None:
                            parameter_data[key] = value

            # Store parameter data in coordinator data structure
            # Note: self.data is managed by the coordinator base class
            if hasattr(self, "data") and self.data is not None:
                if "parameters" not in self.data:
                    self.data["parameters"] = {}
                self.data["parameters"][serial] = parameter_data

            _LOGGER.debug("Refreshed %d parameters for device %s", len(parameter_data), serial)

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)
            raise

    async def _refresh_missing_parameters(self, inverter_serials: List[str], processed_data: Dict[str, Any]) -> None:
        """Refresh parameters for inverters that don't have them yet."""
        try:
            for serial in inverter_serials:
                try:
                    await self._refresh_device_parameters(serial)
                    # Update the processed data with new parameter data
                    if self.data and "parameters" in self.data and serial in self.data["parameters"]:
                        processed_data["parameters"][serial] = self.data["parameters"][serial]
                except Exception as e:
                    _LOGGER.error("Failed to refresh missing parameters for %s: %s", serial, e)

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

    async def set_working_mode(self, serial_number: str, function_param: str, enable: bool) -> bool:
        """Set working mode for inverter."""
        try:
            _LOGGER.debug(
                "Setting working mode %s to %s for device %s",
                function_param,
                enable,
                serial_number,
            )

            # Use existing API method
            response = await self.api.control_function_parameter(
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
            # Get cached parameters from standard parameter cache (includes all 3 register ranges)
            if not self.data or "parameters" not in self.data:
                _LOGGER.debug(
                    "No cached parameters available - data structure: %s",
                    list(self.data.keys()) if self.data else "None",
                )
                return False

            parameter_data = self.data["parameters"].get(serial_number, {})
            if not parameter_data:
                available_devices = list(self.data["parameters"].keys())
                _LOGGER.debug(
                    "No cached parameters for device %s - available: %s",
                    serial_number,
                    available_devices,
                )
                return False

            # Debug: Check if working mode parameters exist in cache
            working_mode_params_in_cache = {
                k: v
                for k, v in parameter_data.items()
                if "FUNC_" in k
                and k
                in [
                    "FUNC_AC_CHARGE",
                    "FUNC_FORCED_CHG_EN",
                    "FUNC_FORCED_DISCHG_EN",
                    "FUNC_GRID_PEAK_SHAVING",
                    "FUNC_BATTERY_BACKUP_CTRL",
                ]
            }
            if working_mode_params_in_cache:
                _LOGGER.debug(
                    "Working mode parameters found in cache for %s: %s",
                    serial_number,
                    working_mode_params_in_cache,
                )

            # Map function parameters to parameter register values
            param_key = FUNCTION_PARAM_MAPPING.get(function_param)
            if param_key:
                # Check if parameter exists and is enabled (value == 1 or True)
                param_value = parameter_data.get(param_key, False)
                # Handle both bool and int values (True or 1 = enabled)
                if isinstance(param_value, bool):
                    is_enabled = param_value
                else:
                    is_enabled = param_value == 1
                _LOGGER.debug(
                    "Working mode %s for device %s: parameter %s = %s (type: %s) -> enabled: %s",
                    function_param,
                    serial_number,
                    param_key,
                    param_value,
                    type(param_value),
                    is_enabled,
                )

                # Log available parameters if the expected one is missing
                if param_key not in parameter_data:
                    available_params = [k for k in parameter_data.keys() if "FUNC_" in k]
                    _LOGGER.debug(
                        "Parameter %s not found for device %s. Available FUNC_ parameters: %s",
                        param_key,
                        serial_number,
                        list(available_params)[:10],
                    )

                return is_enabled

            _LOGGER.warning("Unknown function parameter: %s", function_param)
            return False

        except Exception as err:
            _LOGGER.error("Error getting working mode state for %s: %s", serial_number, err)
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
            if hasattr(self.api, "clear_cache"):
                self.api.clear_cache()
                _LOGGER.debug("Cleared API response cache")

            # Clear device discovery cache
            if hasattr(self.api, "_device_cache"):
                self.api._device_cache.clear()
                self.api._device_cache_expires = None
                _LOGGER.debug("Cleared device discovery cache")

            # Update last invalidation time
            self._last_cache_invalidation = dt_util.utcnow()

            _LOGGER.info(
                "Successfully invalidated all caches at %s to prevent date rollover issues",
                self._last_cache_invalidation.strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

        except Exception as e:
            _LOGGER.error("Error invalidating caches: %s", e)
