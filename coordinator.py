"""Data update coordinator for EG4 Inverter integration."""

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
    CONF_BASE_URL, CONF_PLANT_ID, CONF_VERIFY_SSL, DEFAULT_UPDATE_INTERVAL, DOMAIN, SENSOR_TYPES,
    INVERTER_RUNTIME_FIELD_MAPPING, INVERTER_ENERGY_FIELD_MAPPING, 
    GRIDBOSS_FIELD_MAPPING, PARALLEL_GROUP_FIELD_MAPPING
)
from .eg4_inverter_api import EG4InverterAPI
from .utils import (
    extract_individual_battery_sensors,
    should_filter_zero_sensor,
    validate_api_response,
    validate_sensor_value,
    safe_division,
    DIVIDE_BY_10_SENSORS,
    DIVIDE_BY_100_SENSORS,
    GRIDBOSS_DIVIDE_BY_10_SENSORS,
    POWER_ENERGY_SENSORS,
    ESSENTIAL_SENSORS
)
from .eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError

_LOGGER = logging.getLogger(__name__)


class EG4DataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching EG4 Inverter data from the API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]
        
        # Initialize API client
        self.api = EG4InverterAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(CONF_BASE_URL, "https://monitor.eg4electronics.com"),
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
        )
        
        # Device tracking
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.device_sensors: Dict[str, List[str]] = {}
        
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
        words = text.replace('_', ' ').split()
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
            
            # Get comprehensive data for all devices in the plant
            data = await self.api.get_all_device_data(self.plant_id)
            
            # Process and structure the data
            processed_data = await self._process_device_data(data)
            
            _LOGGER.debug("Successfully updated data for %d devices", len(processed_data.get("devices", {})))
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
            "parallel_groups": raw_data.get("parallel_groups", {}),
            "inverter_overview": raw_data.get("inverter_overview", {}),
            "device_info": raw_data.get("device_info", {}),
            "last_update": dt_util.utcnow(),
        }
        
        # Store device info temporarily for model extraction
        self._temp_device_info = raw_data.get("device_info", {})
        
        # Process each device
        for serial, device_data in raw_data.get("devices", {}).items():
            if "error" in device_data:
                _LOGGER.warning("Error in device %s: %s", serial, device_data["error"])
                continue
                
            device_type = device_data.get("type", "unknown")
            
            if device_type == "inverter":
                processed["devices"][serial] = await self._process_inverter_data(serial, device_data)
            elif device_type == "gridboss":
                processed["devices"][serial] = await self._process_gridboss_data(serial, device_data)
            else:
                _LOGGER.warning("Unknown device type '%s' for device %s", device_type, serial)
        
        # Process parallel group energy data if available
        parallel_energy = raw_data.get("parallel_energy")
        parallel_groups_info = raw_data.get("parallel_groups_info", [])
        if parallel_energy and parallel_energy.get("success"):
            _LOGGER.debug("Processing parallel group energy data")
            processed["devices"]["parallel_group"] = await self._process_parallel_group_data(parallel_energy, parallel_groups_info)
        
        # Clear temporary device info
        if hasattr(self, "_temp_device_info"):
            delattr(self, "_temp_device_info")
        
        return processed

    async def _process_inverter_data(self, serial: str, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process inverter device data."""
        runtime = device_data.get("runtime", {})
        energy = device_data.get("energy", {})
        battery = device_data.get("battery", {})
        
        processed = {
            "serial": serial,
            "type": "inverter",
            "model": self._extract_model_from_overview(serial),
            "firmware_version": runtime.get("fwCode", "1.0.0") if runtime else "1.0.0",  # Extract firmware from runtime response
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
        
        # Process battery data
        if battery and isinstance(battery, dict):
            # Non-array battery data (inverter-level)
            processed["sensors"].update(self._extract_battery_sensors(battery))
            processed["binary_sensors"].update(self._extract_battery_binary_sensors(battery))
            
            # Individual batteries from batteryArray
            battery_array = battery.get("batteryArray", [])
            if isinstance(battery_array, list):
                _LOGGER.debug("Found batteryArray with %d batteries for device %s", len(battery_array), serial)
                for i, bat_data in enumerate(battery_array):
                    if isinstance(bat_data, dict):
                        _LOGGER.debug("Battery %d data fields available: %s", i+1, list(bat_data.keys()))
                        raw_battery_key = bat_data.get("batteryKey", f"BAT{i+1:03d}")
                        battery_key = self._clean_battery_key(raw_battery_key, serial)
                        processed["batteries"][battery_key] = extract_individual_battery_sensors(bat_data)
        
        return processed

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
                _LOGGER.debug("Processing midboxData for %s with fields: %s", serial, list(midbox_data.keys()))
                processed["sensors"].update(self._extract_gridboss_sensors(midbox_data))
                processed["binary_sensors"].update(self._extract_gridboss_binary_sensors(midbox_data))
            else:
                _LOGGER.debug("No midboxData found for %s, using raw midbox data: %s", serial, list(midbox.keys()))
                # Try using the raw midbox data if midboxData is not nested
                processed["sensors"].update(self._extract_gridboss_sensors(midbox))
                processed["binary_sensors"].update(self._extract_gridboss_binary_sensors(midbox))
        
        return processed

    async def _process_parallel_group_data(self, parallel_energy: Dict[str, Any], parallel_groups_info: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process parallel group energy data."""
        # Extract the group name from parallel groups info
        group_name = "Parallel Group"  # Default fallback
        if parallel_groups_info and len(parallel_groups_info) > 0:
            first_group = parallel_groups_info[0]
            group_letter = first_group.get("parallelGroup", "")
            if group_letter:
                group_name = f"Parallel Group {group_letter}"
        
        processed = {
            "serial": "parallel_group",
            "type": "parallel_group",
            "model": group_name,
            "sensors": {},
            "binary_sensors": {},
        }
        
        # Extract parallel group energy sensors
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
                    return model
            
            # Check parallel groups
            parallel_groups = self.data.get("parallel_groups", {})
            if isinstance(parallel_groups, dict):
                for group in parallel_groups.get("data", []):
                    for device in group.get("inverterList", []):
                        if device.get("serialNum") == serial:
                            model = device.get("deviceTypeText4APP")
                            if model:
                                return model
            
            # Check inverter overview
            inverter_overview = self.data.get("inverter_overview", {})
            if isinstance(inverter_overview, dict):
                for device in inverter_overview.get("data", []):
                    if device.get("serialNum") == serial:
                        model = device.get("deviceTypeText4APP")
                        if model:
                            return model
        
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
        
        # Map common runtime fields to sensor types
        field_mapping = {
            "acPower": "ac_power",
            "dcPower": "dc_power", 
            "acVoltage": "ac_voltage",
            "dcVoltage": "dc_voltage",
            "acCurrent": "ac_current",
            "dcCurrent": "dc_current",
            "frequency": "frequency",
            "temperature": "temperature",
            # New runtime sensors based on actual API data
            "vacr": "ac_voltage",  # AC Voltage (needs division by 10)
            "ppv": "pv_total_power",  # PV Total Power 
            "tinner": "internal_temperature",  # Internal Temperature
            "tradiator1": "radiator1_temperature",  # Radiator 1 Temperature
            "tradiator2": "radiator2_temperature",  # Radiator 2 Temperature
            # PV String mappings
            "vpv1": "pv1_voltage",
            "vpv2": "pv2_voltage", 
            "vpv3": "pv3_voltage",
            "ppv1": "pv1_power",
            "ppv2": "pv2_power",
            "ppv3": "pv3_power",
            # Energy fields that might appear in runtime data
            "todayYielding": "yield",
            "todayDischarging": "discharging",
            "todayCharging": "charging",
            "todayLoad": "load",
            "todayGridFeed": "grid_export", 
            "todayGridConsumption": "grid_import",
            "totalYielding": "yield_lifetime",
            "totalDischarging": "discharging_lifetime",
            "totalCharging": "charging_lifetime",
            "totalLoad": "load_lifetime",
            "totalGridFeed": "grid_export_lifetime",
            "totalGridConsumption": "grid_import_lifetime",
            # Status sensors
            "status": "status_code",
            "statusText": "status_text",        }
        
        # These sensors need values divided by 10 
        divide_by_10_sensors = {
            # Energy sensors (to convert to kWh)
            "yield", "discharging", "charging",
            "load", "grid_export", "grid_import",
            "yield_lifetime", "discharging_lifetime", "charging_lifetime", 
            "load_lifetime", "grid_export_lifetime", "grid_import_lifetime"
        }
        
        # Voltage fields that need division by 10
        divide_voltage_by_10_fields = {"vacr", "vpv1", "vpv2", "vpv3"}
        
        for api_field, sensor_type in field_mapping.items():
            if api_field in runtime:
                value = runtime[api_field]
                if value is not None:
                    # Apply division by 10 for today/daily energy sensors
                    if sensor_type in divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert %s value %s to float for division", sensor_type, value)
                            continue
                    
                    # Apply division by 10 for voltage sensors (vacr field)
                    if api_field in divide_voltage_by_10_fields:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert %s value %s to float for voltage division", api_field, value)
                            continue
                    
                    # Apply camel casing for status text
                    if sensor_type == "status_text" and isinstance(value, str):
                        value = self._to_camel_case(value)
                    
                    sensors[sensor_type] = value
        
        return sensors

    def _extract_runtime_binary_sensors(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from runtime response."""
        return {}

    def _extract_energy_sensors(self, energy: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from energy response."""
        _LOGGER.debug("Energy data fields available: %s", list(energy.keys()))
        sensors = {}
        
        field_mapping = {
            "totalEnergy": "total_energy",
            "dailyEnergy": "daily_energy", 
            "monthlyEnergy": "monthly_energy",
            "yearlyEnergy": "yearly_energy",
            # Today energy sensors (need division by 10)
            "todayYielding": "yield",
            "todayDischarging": "discharging",
            "todayCharging": "charging",
            "todayLoad": "load",
            "todayGridFeed": "grid_export", 
            "todayGridConsumption": "grid_import",
            # Total energy sensors (need division by 10)
            "totalYielding": "yield_lifetime",
            "totalDischarging": "discharging_lifetime",
            "totalCharging": "charging_lifetime",
            "totalLoad": "load_lifetime",
            "totalGridFeed": "grid_export_lifetime",
            "totalGridConsumption": "grid_import_lifetime",
        }
        
        # These sensors need values divided by 10 to convert to kWh
        divide_by_10_sensors = {
            "yield", "discharging", "charging",
            "load", "grid_export", "grid_import",
            "yield_lifetime", "discharging_lifetime", "charging_lifetime", 
            "load_lifetime", "grid_export_lifetime", "grid_import_lifetime"
        }
        
        for api_field, sensor_type in field_mapping.items():
            if api_field in energy:
                value = energy[api_field]
                if value is not None:
                    # Apply division by 10 for energy sensors to convert to kWh
                    if sensor_type in divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert %s value %s to float for division", sensor_type, value)
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
                    sensors[sensor_type] = value
        
        return sensors

    def _extract_battery_binary_sensors(self, battery: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from battery response."""
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

    
    def _is_valid_numeric(self, value) -> bool:
        """Check if a value is valid numeric data."""
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                float(value)
                return True
            except (ValueError, TypeError):
                return False
        return False
    
    def _process_sensor_value(self, api_field: str, value, sensor_type: str):
        """Process and scale sensor values based on API field type."""
        # Validate numeric values for sensors that expect numbers
        sensor_config = SENSOR_TYPES.get(sensor_type, {})
        device_class = sensor_config.get("device_class")
        
        # For numeric sensors, ensure the value is actually numeric
        if device_class in ["temperature", "voltage", "current", "power", "battery"] or sensor_config.get("state_class") == "measurement":
            if not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    _LOGGER.debug("Skipping invalid numeric value for %s.%s: %s", sensor_type, api_field, value)
                    return None
        
        # Apply scaling or conversion based on actual API field scaling
        if api_field in ["totalVoltage", "batMaxCellVoltage", "batMinCellVoltage"] and isinstance(value, (int, float)):
            # Voltage fields are scaled by 100x, need to divide by 100
            value = value / 100.0
        elif api_field in ["current"] and isinstance(value, (int, float)):
            # Current is scaled by 10x, need to divide by 10
            value = value / 10.0
        elif api_field in ["batMaxCellTemp", "batMinCellTemp", "ambientTemp", "mosTemp"] and isinstance(value, (int, float)):
            # Temperature fields are scaled by 10x, need to divide by 10
            value = value / 10.0
        
        return value

    def _extract_gridboss_sensors(self, midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from GridBOSS midbox response."""
        _LOGGER.debug("GridBOSS midbox data fields available: %s", list(midbox_data.keys()))
        sensors = {}
        
        field_mapping = {
            # Core Power sensors  
            "hybridPower": "load_power",
            "smartLoadPower": "smart_load_power",
            # Frequency sensors
            "gridFreq": "frequency",
            "genFreq": "generator_frequency", 
            "phaseLockFreq": "phase_lock_frequency",
            
            # GridBOSS MidBox voltage sensors (actual API field names)
            "gridL1RmsVolt": "grid_voltage_l1",
            "gridL2RmsVolt": "grid_voltage_l2", 
            "upsL1RmsVolt": "load_voltage_l1",
            "upsL2RmsVolt": "load_voltage_l2",
            "upsRmsVolt": "ups_voltage",
            "gridRmsVolt": "grid_voltage",
            "genRmsVolt": "generator_voltage",
            
            # GridBOSS MidBox current sensors (actual API field names)
            "gridL1RmsCurr": "grid_current_l1",
            "gridL2RmsCurr": "grid_current_l2",
            "loadL1RmsCurr": "load_current_l1",
            "loadL2RmsCurr": "load_current_l2",
            "upsL1RmsCurr": "ups_current_l1",
            "upsL2RmsCurr": "ups_current_l2",
            "genL1RmsCurr": "generator_current_l1",
            "genL2RmsCurr": "generator_current_l2",
            
            # GridBOSS MidBox power sensors (actual API field names)
            "gridL1ActivePower": "grid_power_l1",
            "gridL2ActivePower": "grid_power_l2",
            "loadL1ActivePower": "load_power_l1", 
            "loadL2ActivePower": "load_power_l2",
            "upsL1ActivePower": "ups_power_l1",
            "upsL2ActivePower": "ups_power_l2",
            "genL1ActivePower": "generator_power_l1",
            "genL2ActivePower": "generator_power_l2",
            
            # Smart Load Power sensors
            "smartLoad1L1ActivePower": "smart_load1_power_l1",
            "smartLoad1L2ActivePower": "smart_load1_power_l2",
            "smartLoad2L1ActivePower": "smart_load2_power_l1", 
            "smartLoad2L2ActivePower": "smart_load2_power_l2",
            "smartLoad3L1ActivePower": "smart_load3_power_l1",
            "smartLoad3L2ActivePower": "smart_load3_power_l2",
            "smartLoad4L1ActivePower": "smart_load4_power_l1",
            "smartLoad4L2ActivePower": "smart_load4_power_l2",
            
            # Smart Port Status sensors (diagnostic)
            "smartPort1Status": "smart_port1_status",
            "smartPort2Status": "smart_port2_status",
            "smartPort3Status": "smart_port3_status",
            "smartPort4Status": "smart_port4_status",
            
            # Energy sensors - UPS/backup load daily values
            "eUpsTodayL1": "ups_l1",
            "eUpsTodayL2": "ups_l2", 
            # Energy sensors - UPS/backup load lifetime values
            "eUpsTotalL1": "ups_lifetime_l1",
            "eUpsTotalL2": "ups_lifetime_l2",
            
            # Energy sensors - Grid interaction daily values
            "eToGridTodayL1": "grid_export_l1",
            "eToGridTodayL2": "grid_export_l2",
            "eToUserTodayL1": "grid_import_l1", 
            "eToUserTodayL2": "grid_import_l2",
            # Energy sensors - Grid interaction lifetime values
            "eToGridTotalL1": "grid_export_lifetime_l1",
            "eToGridTotalL2": "grid_export_lifetime_l2",
            "eToUserTotalL1": "grid_import_lifetime_l1",
            "eToUserTotalL2": "grid_import_lifetime_l2",
            
            # Energy sensors - Non-backup load daily values
            "eLoadTodayL1": "load_l1",
            "eLoadTodayL2": "load_l2",
            # Energy sensors - Non-backup load lifetime values
            "eLoadTotalL1": "load_lifetime_l1",
            "eLoadTotalL2": "load_lifetime_l2",
            
            # Energy sensors - AC Couple daily values  
            "eACcouple1TodayL1": "ac_couple1_l1",
            "eACcouple1TodayL2": "ac_couple1_l2",
            "eACcouple2TodayL1": "ac_couple2_l1",
            "eACcouple2TodayL2": "ac_couple2_l2",
            "eACcouple3TodayL1": "ac_couple3_l1",
            "eACcouple3TodayL2": "ac_couple3_l2",
            "eACcouple4TodayL1": "ac_couple4_l1",
            "eACcouple4TodayL2": "ac_couple4_l2",
            # Energy sensors - AC Couple lifetime values
            "eACcouple1TotalL1": "ac_couple1_lifetime_l1",
            "eACcouple1TotalL2": "ac_couple1_lifetime_l2",
            "eACcouple2TotalL1": "ac_couple2_lifetime_l1",
            "eACcouple2TotalL2": "ac_couple2_lifetime_l2",
            "eACcouple3TotalL1": "ac_couple3_lifetime_l1",
            "eACcouple3TotalL2": "ac_couple3_lifetime_l2",
            "eACcouple4TotalL1": "ac_couple4_lifetime_l1",
            "eACcouple4TotalL2": "ac_couple4_lifetime_l2",
            
            # Smart Load Energy sensors - daily values
            "eSmartLoad1TodayL1": "smart_load1_l1",
            "eSmartLoad1TodayL2": "smart_load1_l2",
            "eSmartLoad2TodayL1": "smart_load2_l1",
            "eSmartLoad2TodayL2": "smart_load2_l2",
            "eSmartLoad3TodayL1": "smart_load3_l1",
            "eSmartLoad3TodayL2": "smart_load3_l2",
            "eSmartLoad4TodayL1": "smart_load4_l1",
            "eSmartLoad4TodayL2": "smart_load4_l2",
            # Smart Load Energy sensors - lifetime values
            "eSmartLoad1TotalL1": "smart_load1_lifetime_l1",
            "eSmartLoad1TotalL2": "smart_load1_lifetime_l2",
            "eSmartLoad2TotalL1": "smart_load2_lifetime_l1",
            "eSmartLoad2TotalL2": "smart_load2_lifetime_l2",
            "eSmartLoad3TotalL1": "smart_load3_lifetime_l1",
            "eSmartLoad3TotalL2": "smart_load3_lifetime_l2",
            "eSmartLoad4TotalL1": "smart_load4_lifetime_l1",
            "eSmartLoad4TotalL2": "smart_load4_lifetime_l2",
        }
        
        
        for api_field, sensor_type in field_mapping.items():
            if api_field in midbox_data:
                value = midbox_data[api_field]
                if value is not None:
                    # Smart Port Status needs text conversion BEFORE filtering and scaling
                    if sensor_type.startswith("smart_port") and sensor_type.endswith("_status"):
                        _LOGGER.debug("Converting Smart Port status %s: raw_value=%s, type=%s", sensor_type, value, type(value))
                        status_map = {0: "Unused", 1: "Smart Load", 2: "AC Couple"}
                        converted_value = status_map.get(value, f"Unknown ({value})")
                        _LOGGER.debug("Smart Port status %s converted from %s to %s", sensor_type, value, converted_value)
                        value = converted_value
                        # Smart Port status sensors are always included, skip filtering and scaling
                        sensors[sensor_type] = value
                        continue
                    
                    # Apply division by 10 for GridBOSS energy and voltage sensors
                    gridboss_divide_by_10_sensors = {
                        # UPS energy sensors
                        "ups_l1", "ups_l2", "ups_lifetime_l1", "ups_lifetime_l2", 
                        # Grid export/import energy sensors
                        "grid_export_l1", "grid_export_l2", "grid_import_l1", "grid_import_l2",
                        "grid_export_lifetime_l1", "grid_export_lifetime_l2", "grid_import_lifetime_l1", "grid_import_lifetime_l2",
                        # Load energy sensors
                        "load_l1", "load_l2", "load_lifetime_l1", "load_lifetime_l2",
                        # AC Couple energy sensors
                        "ac_couple1_l1", "ac_couple1_l2", "ac_couple1_lifetime_l1", "ac_couple1_lifetime_l2",
                        "ac_couple2_l1", "ac_couple2_l2", "ac_couple2_lifetime_l1", "ac_couple2_lifetime_l2", 
                        "ac_couple3_l1", "ac_couple3_l2", "ac_couple3_lifetime_l1", "ac_couple3_lifetime_l2",
                        "ac_couple4_l1", "ac_couple4_l2", "ac_couple4_lifetime_l1", "ac_couple4_lifetime_l2",
                        # Smart Load energy sensors  
                        "smart_load1_l1", "smart_load1_l2", "smart_load1_lifetime_l1", "smart_load1_lifetime_l2",
                        "smart_load2_l1", "smart_load2_l2", "smart_load2_lifetime_l1", "smart_load2_lifetime_l2",
                        "smart_load3_l1", "smart_load3_l2", "smart_load3_lifetime_l1", "smart_load3_lifetime_l2",
                        "smart_load4_l1", "smart_load4_l2", "smart_load4_lifetime_l1", "smart_load4_lifetime_l2",
                        # Other energy sensors
                        "energy_to_user", "ups_energy",
                        # Voltage sensors (convert from decivolts to volts)
                        "grid_voltage_l1", "grid_voltage_l2", "load_voltage_l1", "load_voltage_l2", 
                        "ups_voltage", "grid_voltage", "generator_voltage",
                        # Current sensors (convert from deciamps to amps)
                        "grid_current_l1", "grid_current_l2", "load_current_l1", "load_current_l2", 
                        "ups_current_l1", "ups_current_l2", "generator_current_l1", "generator_current_l2"
                    }
                    
                    # GridBOSS frequency sensors need division by 100
                    gridboss_divide_by_100_sensors = {
                        "frequency", "generator_frequency", "phase_lock_frequency"
                    }
                    
                    if sensor_type in gridboss_divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert GridBOSS %s value %s to float for division by 10", sensor_type, value)
                            continue
                    elif sensor_type in gridboss_divide_by_100_sensors:
                        try:
                            value = float(value) / 100.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert GridBOSS %s value %s to float for division by 100", sensor_type, value)
                            continue
                    
                    # TODO: Remove zero-value filtering for GridBOSS as per task requirements
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
            if status == 0:  # Unused Smart Port
                _LOGGER.debug("Smart Port %d is unused (status=0), removing related sensors", port)
                # Remove Smart Load power sensors
                sensors_to_remove.extend([
                    f"smart_load{port}_power_l1",
                    f"smart_load{port}_power_l2",
                ])
                # Remove Smart Load energy sensors (daily)
                sensors_to_remove.extend([
                    f"smart_load{port}_l1", 
                    f"smart_load{port}_l2",
                ])
                # Remove Smart Load energy sensors (lifetime)
                sensors_to_remove.extend([
                    f"smart_load{port}_lifetime_l1",
                    f"smart_load{port}_lifetime_l2",
                ])
                # Note: Keep the status sensor itself for visibility
        
        # Remove the identified sensors
        filtered_sensors = sensors.copy()
        for sensor_key in sensors_to_remove:
            if sensor_key in filtered_sensors:
                del filtered_sensors[sensor_key]
                _LOGGER.debug("Removed unused Smart Port sensor: %s", sensor_key)
        
        _LOGGER.debug("Filtered %d unused Smart Port sensors", len(sensors_to_remove))
        return filtered_sensors

    def _extract_gridboss_binary_sensors(self, midbox_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from GridBOSS midbox response."""
        return {}

    def get_device_info(self, serial: str) -> Optional[Dict[str, Any]]:
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
            device_name = model  # Use just the model name for parallel groups (e.g., "Parallel Group A")
        else:
            device_name = f"{model} {serial}"  # Normal devices include serial number
        
        # Get firmware version based on device type
        sw_version = "1.0.0"  # Default fallback
        if device_type in ["gridboss", "inverter"]:
            # For GridBOSS and inverter devices, get firmware from fwCode field
            sw_version = device_data.get("firmware_version", "1.0.0")
        
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": device_name,
            "manufacturer": "EG4 Electronics",
            "model": model,
            "serial_number": serial,
            "sw_version": sw_version,
            # Removed via_device to avoid warnings - creates flat device structure
        }

    def get_battery_device_info(self, serial: str, battery_key: str) -> Optional[Dict[str, Any]]:
        """Get device information for a specific battery."""
        if not self.data or "devices" not in self.data:
            return None
            
        device_data = self.data["devices"].get(serial)
        if not device_data or battery_key not in device_data.get("batteries", {}):
            return None
            
        return {
            "identifiers": {(DOMAIN, f"{serial}_{battery_key}")},
            "name": f"Battery {battery_key}",
            "manufacturer": "EG4 Electronics", 
            "model": "Battery Module",
            "serial_number": f"{serial}_{battery_key}",
            "sw_version": "1.0.0",
            # Removed via_device to avoid timing warnings - devices still show in registry
        }

    def _extract_parallel_group_sensors(self, parallel_energy: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sensor data from parallel group energy response."""
        _LOGGER.debug("Parallel group energy data fields available: %s", list(parallel_energy.keys()))
        sensors = {}
        
        # Map parallel group energy data to sensor types
        field_mapping = {
            # Today energy values (need division by 10)
            "todayYielding": "yield",
            "todayDischarging": "discharging", 
            "todayCharging": "charging",
            "todayExport": "grid_export",
            "todayImport": "grid_import",
            "todayUsage": "consumption",
            # Total energy values (need division by 10)
            "totalYielding": "yield_lifetime",
            "totalDischarging": "discharging_lifetime",
            "totalCharging": "charging_lifetime", 
            "totalExport": "grid_export_lifetime",
            "totalImport": "grid_import_lifetime",
            "totalUsage": "consumption_lifetime",
        }
        
        # These sensors need values divided by 10 to convert to kWh
        divide_by_10_sensors = {
            "yield", "discharging", "charging",
            "grid_export", "grid_import", "consumption",
            "yield_lifetime", "discharging_lifetime", "charging_lifetime",
            "grid_export_lifetime", "grid_import_lifetime", "consumption_lifetime"
        }
        
        for api_field, sensor_type in field_mapping.items():
            if api_field in parallel_energy:
                value = parallel_energy[api_field]
                if value is not None:
                    # Apply division by 10 for energy sensors to convert to kWh
                    if sensor_type in divide_by_10_sensors:
                        try:
                            value = float(value) / 10.0
                        except (ValueError, TypeError):
                            _LOGGER.warning("Could not convert %s value %s to float for division", sensor_type, value)
                            continue
                    sensors[sensor_type] = value
        
        return sensors

    def _extract_parallel_group_binary_sensors(self, parallel_energy: Dict[str, Any]) -> Dict[str, Any]:
        """Extract binary sensor data from parallel group energy response."""
        return {}