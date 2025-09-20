"""Data update coordinator for EG4 Web Monitor integration."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
from .eg4_inverter_api import EG4InverterAPI
from .utils import (
    extract_individual_battery_sensors,
    clean_battery_display_name,
    read_device_parameters_ranges,
    process_parameter_responses,
    apply_sensor_scaling,
)
from .eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching EG4 Web Monitor data from the API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]

        # Initialize API clien
        self.api = EG4InverterAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(
                CONF_BASE_URL, "https://monitor.eg4electronics.com"
            ),
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
        )

        # Device tracking
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.device_sensors: Dict[str, List[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: Optional[datetime] = None
        self._parameter_refresh_interval = timedelta(
            hours=1
        )  # Hourly parameter refresh

        # Temporary device info storage for model extraction
        self._temp_device_info: Dict[str, Any] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )

    def _to_camel_case(self, text: str) -> str:
        """Convert text to camelCase format."""
        if not text:
            return text

        # Convert spaces and underscores to title case
        words = text.replace("_", " ").split()
        if not words:
            return text

        # First word lowercase, subsequent words title case
        result = words[0].lower()
        for word in words[1:]:
            result += word.capitalize()

        return result

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Fetching data for plant %s", self.plant_id)

            # Check if hourly parameter refresh is due
            if self._should_refresh_parameters():
                _LOGGER.info(
                    "Hourly parameter refresh is due, refreshing all device parameters"
                )
                # Don't await this to avoid blocking the main data update
                self.hass.async_create_task(self._hourly_parameter_refresh())

            # Get comprehensive data for all devices in the plan
            data = await self.api.get_all_device_data(self.plant_id)

            # Process and structure the data
            processed_data = await self._process_device_data(data)

            device_count = len(processed_data.get("devices", {}))
            _LOGGER.debug("Successfully updated data for %d devices", device_count)
            return processed_data

        except EG4AuthError as e:
            _LOGGER.error("Authentication error: %s", e)
            raise UpdateFailed(f"Authentication failed: {e}") from e

        except EG4ConnectionError as e:
            _LOGGER.error("Connection error: %s", e)
            raise UpdateFailed(f"Connection failed: {e}") from e

        except EG4APIError as e:
            _LOGGER.error("API error: %s", e)
            raise UpdateFailed(f"API error: {e}") from e

        except Exception as e:
            _LOGGER.exception("Unexpected error updating data: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e

    async def _process_device_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and structure device data for Home Assistant."""
        processed = {
            "plant_id": self.plant_id,
            "devices": {},
            "device_info": raw_data.get("device_info", {}),
            "last_update": dt_util.utcnow(),
        }

        # Preserve existing parameter data from previous updates
        if self.data and "parameters" in self.data:
            processed["parameters"] = self.data["parameters"]

        # Store device info temporarily for model extraction
        self._temp_device_info = raw_data.get("device_info", {})

        # Process each device
        for serial, device_data in raw_data.get("devices", {}).items():
            if "error" in device_data:
                _LOGGER.error("Error in device %s: %s", serial, device_data["error"])
                # Keep device in data but mark it as having an error
                # This prevents sensors from becoming completely unavailable
                processed["devices"][serial] = {
                    "type": "unknown",
                    "model": "Unknown",
                    "error": device_data["error"],
                    "sensors": {},
                    "batteries": {}
                }
                continue

            device_type = device_data.get("type", "unknown")

            if device_type == "inverter":
                processed["devices"][serial] = await self._process_inverter_data(
                    serial, device_data
                )
            elif device_type == "gridboss":
                processed["devices"][serial] = await self._process_gridboss_data(
                    serial, device_data
                )
            else:
                _LOGGER.warning(
                    "Unknown device type '%s' for device %s", device_type, serial
                )

        # Process parallel group energy data if available
        parallel_energy = raw_data.get("parallel_energy")
        parallel_groups_info = raw_data.get("parallel_groups_info", [])
        _LOGGER.debug(
            "Parallel group data - success: %s, groups: %s",
            parallel_energy.get("success") if parallel_energy else None, parallel_groups_info
        )
        # Only create parallel group if the API indicates parallel groups exis
        if parallel_energy and parallel_energy.get("success"):
            _LOGGER.debug("Processing parallel group energy data")
            processed["devices"][
                "parallel_group"
            ] = await self._process_parallel_group_data(
                parallel_energy, parallel_groups_info
            )

        # Clear temporary device info
        if hasattr(self, "_temp_device_info"):
            delattr(self, "_temp_device_info")

        # Check if we need to refresh parameters for any inverters that don't have them
        if "parameters" not in processed:
            processed["parameters"] = {}

        inverters_needing_params = []
        for serial, device_data in processed["devices"].items():
            if (device_data.get("type") == "inverter" and
                serial not in processed["parameters"]):
                inverters_needing_params.append(serial)

        # If there are inverters without parameters, refresh them
        if inverters_needing_params:
            _LOGGER.info(
                "Refreshing parameters for %d new inverters: %s",
                len(inverters_needing_params),
                inverters_needing_params
            )
            # Don't await this to avoid blocking the data update
            self.hass.async_create_task(
                self._refresh_missing_parameters(inverters_needing_params, processed)
            )
        
        # Refresh working mode parameters for all inverters (lightweight operation)
        inverter_serials = [serial for serial, device_data in processed["devices"].items() 
                           if device_data.get("type") == "inverter"]
        if inverter_serials:
            _LOGGER.debug("Refreshing working mode parameters for %d inverters", len(inverter_serials))
            # Don't await this to avoid blocking the data update
            self.hass.async_create_task(
                self._refresh_working_mode_parameters_for_all(inverter_serials)
            )

        return processed

    async def _process_inverter_data(
        self, serial: str, device_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process inverter device data."""
        runtime = device_data.get("runtime", {})
        energy = device_data.get("energy", {})
        battery = device_data.get("battery", {})

        processed = {
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
            processed["binary_sensors"].update(
                self._extract_runtime_binary_sensors(runtime)
            )

        # Process energy data
        if energy and isinstance(energy, dict):
            processed["sensors"].update(self._extract_energy_sensors(energy))

        # Process battery data
        if battery and isinstance(battery, dict):
            # Non-array battery data (inverter-level)
            processed["sensors"].update(self._extract_battery_sensors(battery))
            processed["binary_sensors"].update(
                self._extract_battery_binary_sensors(battery)
            )

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
                        battery_key = self._clean_battery_key(raw_battery_key, serial)
                        battery_sensors = extract_individual_battery_sensors(bat_data)
                        processed["batteries"][battery_key] = battery_sensors

        # Process quick charge status
        try:
            quick_charge_status = await self.api.get_quick_charge_status(serial)
            processed["quick_charge_status"] = quick_charge_status
            _LOGGER.debug("Retrieved quick charge status for device %s", serial)
        except Exception as e:
            _LOGGER.debug("Failed to get quick charge status for device %s: %s", serial, e)
            # Don't fail the entire update if quick charge status fails
            processed["quick_charge_status"] = {"status": False, "error": str(e)}

        # Process battery backup status by reading FUNC_EPS_EN parameter from base parameters
        try:
            # Read base parameters (0-127) where FUNC_EPS_EN is likely located
            # (cached with 2-minute TTL)
            battery_backup_params = await self.api.read_parameters(serial, 0, 127)
            func_eps_en = None
            if battery_backup_params and battery_backup_params.get("success"):
                func_eps_en = battery_backup_params.get("FUNC_EPS_EN")

            if func_eps_en is not None:
                # Enhanced debugging to understand the actual API response
                _LOGGER.info(
                    "Battery backup parameter for %s: FUNC_EPS_EN = %r (type: %s)",
                    serial, func_eps_en, type(func_eps_en).__name__
                )
                # Convert to boolean with explicit handling of different value types
                if func_eps_en is None:
                    enabled = False
                elif isinstance(func_eps_en, str):
                    # Handle string values like "1", "0", "true", "false"
                    enabled = func_eps_en.lower() not in ("0", "false", "off", "disabled", "")
                elif isinstance(func_eps_en, (int, float)):
                    # Handle numeric values where 0 = disabled, non-zero = enabled
                    enabled = bool(func_eps_en != 0)
                else:
                    # Default boolean conversion
                    enabled = bool(func_eps_en)
                processed["battery_backup_status"] = {
                    "FUNC_EPS_EN": func_eps_en,
                    "enabled": enabled
                }
                _LOGGER.info(
                    "Battery backup status for %s: raw=%r, enabled=%s",
                    serial, func_eps_en, enabled
                )
                # Update the coordinator's parameter cache with this fresh data
                if "parameters" not in processed:
                    processed["parameters"] = {}
                if serial not in processed["parameters"]:
                    processed["parameters"][serial] = {}
                processed["parameters"][serial]["FUNC_EPS_EN"] = func_eps_en
            else:
                processed["battery_backup_status"] = {
                    "enabled": False,
                    "error": "FUNC_EPS_EN parameter not found in base parameters"
                }
                _LOGGER.warning(
                    "FUNC_EPS_EN parameter not found in base parameters for device %s", serial
                )
        except Exception as e:
            _LOGGER.debug("Failed to get battery backup status for device %s: %s", serial, e)
            # Don't fail the entire update if battery backup status fails
            processed["battery_backup_status"] = {"enabled": False, "error": str(e)}

        return processed

    async def _process_gridboss_data(
        self, serial: str, device_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process GridBOSS device data."""
        midbox = device_data.get("midbox", {})

        processed = {
            "serial": serial,
            "type": "gridboss",
            "model": self._extract_model_from_overview(serial),
            "firmware_version": midbox.get(
                "fwCode", "1.0.0"
            ),  # Extract firmware from midbox response
            "sensors": {},
            "binary_sensors": {},
        }

        # Process midbox data
        if midbox and isinstance(midbox, dict):
            _LOGGER.debug(
                "Raw midbox response structure for %s: %s", serial, list(midbox.keys())
            )
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
        parallel_energy: Dict[str, Any] = None,
        parallel_groups_info: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process parallel group energy data."""
        _LOGGER.debug(
            "Processing parallel group data - energy: %s, groups: %s",
            bool(parallel_energy), parallel_groups_info)

        # Extract the group name from parallel groups info
        group_name = "Parallel Group"  # Default fallback
        if parallel_groups_info and len(parallel_groups_info) > 0:
            # Extract group letter from first group
            first_group = parallel_groups_info[0]
            group_letter = first_group.get("parallelGroup", "")
            _LOGGER.debug(
                "Parallel group naming - group_letter: %s", group_letter
            )

            if group_letter:
                # Always include the letter if available, regardless of group coun
                group_name = f"Parallel Group {group_letter}"
                _LOGGER.debug("Set parallel group name to: %s", group_name)
            else:
                _LOGGER.debug("No group letter found, using default name: %s", group_name)

        processed = {
            "serial": "parallel_group",
            "type": "parallel_group",
            "model": group_name,
            "sensors": {},
            "binary_sensors": {},
        }

        # Extract parallel group energy sensors if available
        if parallel_energy:
            processed["sensors"].update(
                self._extract_parallel_group_sensors(parallel_energy)
            )
            processed["binary_sensors"].update(
                self._extract_parallel_group_binary_sensors(parallel_energy)
            )

        return processed

    def _extract_model_from_overview(self, serial: str) -> str:
        """Extract device model from overview data."""
        # Check device_info from login response first (most reliable)
        if hasattr(self, "data") and self.data:
            device_info = self.data.get("device_info", {})
            if serial in device_info:
                model = device_info[serial].get("deviceTypeText4APP")
                if model:
                    return model

            # Note: parallel_groups and inverter_overview discovery endpoints
            # have been disabled as they were problematic and not essential

        # Store device info temporarily during device setup for fallback
        if hasattr(self, "_temp_device_info"):
            device_data = self._temp_device_info.get(serial, {})
            model = device_data.get("deviceTypeText4APP")
            if model:
                return model

        return "Unknown"

    def _extract_runtime_sensors(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from runtime response."""
        _LOGGER.debug("Runtime data fields available: %s", list(runtime.keys()))
        sensors = {}

        # Use shared field mapping from const.py to reduce duplication
        field_mapping = INVERTER_RUNTIME_FIELD_MAPPING

        # Use shared sensor list from const.py to reduce duplication
        divide_by_10_sensors = DIVIDE_BY_10_SENSORS

        # Voltage fields that need division by 10
        divide_voltage_by_10_fields = {"vacr", "vpv1", "vpv2", "vpv3", "vBat"}

        for api_field, sensor_type in field_mapping.items():
            if api_field in runtime:
                value = runtime[api_field]
                if value is not None:
                    # Apply division by 10 for today/daily energy sensors
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

                    # Apply division by 10 for voltage sensors (vacr field)
                    if api_field in divide_voltage_by_10_fields:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert %s value %s to float for voltage division",
                                api_field,
                                value,
                            )
                            continue

                    # Apply camel casing for status tex
                    if sensor_type == "status_text" and isinstance(value, str):
                        value = self._to_camel_case(value)

                    sensors[sensor_type] = value

        return sensors

    def _extract_runtime_binary_sensors(
        self, runtime: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract binary sensor data from runtime response."""
        # Currently no binary sensors are extracted from runtime data
        # This method is reserved for future binary sensor implementations
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
        }

        for api_field, sensor_type in field_mapping.items():
            if api_field in battery:
                value = battery[api_field]
                if value is not None:
                    # Apply scaling for sensors that need i
                    scaled_value = apply_sensor_scaling(sensor_type, value, "inverter")
                    sensors[sensor_type] = scaled_value

        return sensors

    def _extract_battery_binary_sensors(
        self, battery: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract binary sensor data from battery response."""
        # Currently no binary sensors are extracted from battery data
        # This method is reserved for future binary sensor implementations
        _ = battery  # Explicitly mark parameter as unused but preserved for interface
        return {}

    def _clean_battery_key(self, raw_key: str, serial: str) -> str:
        """Clean up battery key to make it more readable."""
        if not raw_key:
            return "BAT01"

        # Handle keys like "4512670118_Battery_ID_01" -> "4512670118-01"
        if "_Battery_ID_" in raw_key:
            parts = raw_key.split("_Battery_ID_")
            if len(parts) == 2:
                device_serial = parts[0]
                battery_num = parts[1]
                return f"{device_serial}-{battery_num}"

        # Handle keys like "Battery_ID_01" -> "01"
        if raw_key.startswith("Battery_ID_"):
            battery_num = raw_key.replace("Battery_ID_", "")
            return f"{serial}-{battery_num}"

        # Handle keys like "BAT001" -> "BAT001"
        if raw_key.startswith("BAT"):
            return raw_key

        # If it already looks clean (like "01", "02"), use it with serial
        if raw_key.isdigit() and len(raw_key) <= 2:
            return f"{serial}-{raw_key.zfill(2)}"

        # Fallback: use the raw key but try to make it cleaner
        return raw_key.replace("_", "-")

    def _extract_gridboss_sensors(self, midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from GridBOSS midbox response."""
        _LOGGER.debug(
            "GridBOSS midbox data fields available: %s", list(midbox_data.keys())
        )
        sensors = {}

        # Use field mapping from const.py to avoid duplication
        field_mapping = {
            # Core Power sensors (not in const.py)
            "hybridPower": "load_power",
            "smartLoadPower": "smart_load_power",
            **GRIDBOSS_FIELD_MAPPING,  # Import all the standardized mappings
        }

        for api_field, sensor_type in field_mapping.items():
            if api_field in midbox_data:
                value = midbox_data[api_field]
                if value is not None:
                    # Smart Port Status needs text conversion BEFORE filtering and scaling
                    if sensor_type.startswith("smart_port") and sensor_type.endswith(
                        "_status"
                    ):
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
                    gridboss_divide_by_10_sensors = (
                        GRIDBOSS_ENERGY_SENSORS | VOLTAGE_SENSORS | CURRENT_SENSORS
                    )

                    # GridBOSS frequency sensors need division by 100
                    # Use frequency sensors from const.py to avoid duplication
                    gridboss_divide_by_100_sensors = DIVIDE_BY_100_SENSORS

                    if sensor_type in gridboss_divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert GridBOSS %s value %s to float for "
                                "division by 10",
                                sensor_type,
                                value,
                            )
                            continue
                    elif sensor_type in gridboss_divide_by_100_sensors:
                        try:
                            value = float(value) / 100.0
                        except (ValueError, TypeError):
                            _LOGGER.warning(
                                "Could not convert GridBOSS %s value %s to float for "
                                "division by 100",
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

        # Calculate total generator power from L1/L2
        if "generator_power_l1" in sensors and "generator_power_l2" in sensors:
            gen_l1 = _safe_numeric(sensors["generator_power_l1"])
            gen_l2 = _safe_numeric(sensors["generator_power_l2"])
            sensors["generator_power"] = gen_l1 + gen_l2

        # Calculate AC Couple aggregate today values for each por
        for port in range(1, 5):
            l1_key = f"ac_couple{port}_today_l1"
            l2_key = f"ac_couple{port}_today_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_val = _safe_numeric(sensors[l1_key])
                l2_val = _safe_numeric(sensors[l2_key])
                sensors[f"ac_couple{port}_today"] = l1_val + l2_val

        # Calculate AC Couple aggregate total values for each por
        for port in range(1, 5):
            l1_key = f"ac_couple{port}_total_l1"
            l2_key = f"ac_couple{port}_total_l2"
            if l1_key in sensors and l2_key in sensors:
                l1_val = _safe_numeric(sensors[l1_key])
                l2_val = _safe_numeric(sensors[l2_key])
                sensors[f"ac_couple{port}_total"] = l1_val + l2_val

    def _filter_unused_smart_port_sensors(
        self, sensors: Dict[str, Any], midbox_data: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                _LOGGER.debug(
                    "Smart Port %d is unused (status=0), removing related sensors", port
                )
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

    def _extract_gridboss_binary_sensors(
        self, _midbox_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract binary sensor data from GridBOSS midbox response."""
        return {}

    def get_device_info(self, serial: str) -> Optional[Dict[str, Any]]:
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

        return device_info

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
                                return serial  # Return the actual parallel group device serial
                        # If no parallel group device found, don't set via_device
                        return None

        # Fallback: if no specific group membership found but a parallel group exists,
        # assume all inverter/gridboss devices are part of i
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                # Found a parallel group - return its serial as the paren
                return serial

        return None

    def get_battery_device_info(
        self, serial: str, battery_key: str
    ) -> Optional[Dict[str, Any]]:
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
            "serial_number": clean_battery_name,
            "sw_version": battery_firmware,
            "via_device": (DOMAIN, serial),  # Link battery to its parent inverter
        }

    def _extract_parallel_group_sensors(
        self, parallel_energy: Dict[str, Any]
    ) -> Dict[str, Any]:
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
        self, parallel_energy: Dict[str, Any]  # pylint: disable=unused-argument
    ) -> Dict[str, Any]:
        """Extract binary sensor data from parallel group energy response."""
        return {}

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
            if hasattr(self, 'data') and self.data is not None:
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
                    if (self.data and "parameters" in self.data and
                        serial in self.data["parameters"]):
                        processed_data["parameters"][serial] = self.data["parameters"][serial]
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
        return time_since_refresh >= self._parameter_refresh_interval

    async def set_working_mode(self, serial_number: str, function_param: str, enable: bool) -> bool:
        """Set working mode for inverter."""
        try:
            _LOGGER.debug("Setting working mode %s to %s for device %s", 
                         function_param, enable, serial_number)
            
            # Use existing API method
            response = await self.api.control_function_parameter(
                serial_number=serial_number,
                function_param=function_param,
                enable=enable
            )
            
            # Refresh working mode parameters immediately to get updated state
            await self.refresh_working_mode_parameters(serial_number)
                
            # Trigger coordinator refresh to update entities
            await self.async_refresh()
            
            success = response.get('success', False)
            if success:
                _LOGGER.info("Successfully set working mode %s to %s for device %s", 
                           function_param, enable, serial_number)
            else:
                _LOGGER.warning("Working mode control reported failure: %s", response)
                
            return success
            
        except Exception as err:
            _LOGGER.error(
                "Failed to set working mode %s for %s: %s",
                function_param, serial_number, err
            )
            return False
    
    async def _read_working_mode_parameters(self, serial_number: str) -> Dict[str, Any]:
        """Read working mode parameters from register 127."""
        try:
            # Read working mode parameters from register 127 (127 registers starting at 127)
            response = await self.api.read_parameters(
                inverter_sn=serial_number,
                start_register=127,
                point_number=127
            )
            
            if response and response.get("success", False):
                _LOGGER.debug("Successfully read working mode parameters for device %s", serial_number)
                return response
            else:
                _LOGGER.warning("Failed to read working mode parameters for device %s: %s", 
                               serial_number, response)
                return {}
                
        except Exception as err:
            _LOGGER.error("Error reading working mode parameters for %s: %s", 
                         serial_number, err)
            return {}
    
    async def refresh_working_mode_parameters(self, serial_number: str) -> None:
        """Refresh working mode parameters and store in coordinator data."""
        try:
            # Read working mode parameters from register 127
            working_mode_data = await self._read_working_mode_parameters(serial_number)
            
            if working_mode_data:
                # Store working mode parameters in coordinator data
                if not hasattr(self, 'data') or self.data is None:
                    self.data = {}
                if "working_mode_parameters" not in self.data:
                    self.data["working_mode_parameters"] = {}
                    
                self.data["working_mode_parameters"][serial_number] = working_mode_data
                _LOGGER.debug("Cached working mode parameters for device %s", serial_number)
            
        except Exception as err:
            _LOGGER.error("Error refreshing working mode parameters for %s: %s", 
                         serial_number, err)
    
    async def _refresh_working_mode_parameters_for_all(self, inverter_serials: List[str]) -> None:
        """Refresh working mode parameters for multiple inverters."""
        try:
            tasks = []
            for serial in inverter_serials:
                tasks.append(self.refresh_working_mode_parameters(serial))
            
            # Execute all working mode parameter reads in parallel
            await asyncio.gather(*tasks, return_exceptions=True)
            _LOGGER.debug("Completed working mode parameter refresh for %d inverters", len(inverter_serials))
            
        except Exception as err:
            _LOGGER.error("Error refreshing working mode parameters for multiple inverters: %s", err)
    
    def get_working_mode_state(self, serial_number: str, function_param: str) -> bool:
        """Get current working mode state from cached parameters."""
        try:
            # Get cached working mode parameters
            if not self.data or "working_mode_parameters" not in self.data:
                _LOGGER.debug("No cached working mode parameters available")
                return False
                
            working_mode_data = self.data["working_mode_parameters"].get(serial_number, {})
            if not working_mode_data:
                _LOGGER.debug("No cached working mode parameters for device %s", serial_number)
                return False
            
            # Map function parameters to parameter register values
            param_key = FUNCTION_PARAM_MAPPING.get(function_param)
            if param_key:
                # Check if parameter exists and is enabled (value == 1)
                param_value = working_mode_data.get(param_key, 0)
                _LOGGER.debug("Working mode %s for device %s: parameter %s = %s", 
                             function_param, serial_number, param_key, param_value)
                return param_value == 1
                
            _LOGGER.warning("Unknown function parameter: %s", function_param)
            return False
            
        except Exception as err:
            _LOGGER.error("Error getting working mode state for %s: %s", 
                         serial_number, err)
            return False
