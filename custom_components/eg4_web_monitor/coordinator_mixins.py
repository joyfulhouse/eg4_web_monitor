"""Coordinator mixins for EG4 Web Monitor integration.

This module provides mixins that separate coordinator responsibilities into
logical units for better maintainability and testability.

Mypy Note: Mixins access attributes defined in the main coordinator class.
The CoordinatorProtocol documents the expected interface, but mypy cannot
verify this at the mixin level. Runtime type safety is guaranteed by the
final coordinator class inheriting all mixins together.
"""

# mypy: disable-error-code="attr-defined,misc,unreachable,assignment"

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from pylxpweb import LuxpowerClient
    from pylxpweb.devices import Battery, Station
    from pylxpweb.devices.inverters.base import BaseInverter

from pylxpweb.devices.inverters._features import InverterFamily

from .const import DOMAIN, MANUFACTURER
from .utils import clean_battery_display_name

_LOGGER = logging.getLogger(__name__)


class CoordinatorProtocol(Protocol):
    """Protocol defining the interface that mixins expect from the coordinator.

    This protocol defines attributes and methods that mixins can safely access
    on the main coordinator class. This enables proper type checking for mixins.
    """

    # Data attributes
    data: dict[str, Any] | None
    plant_id: str
    station: "Station | None"
    client: "LuxpowerClient"
    hass: HomeAssistant
    dst_sync_enabled: bool

    # Private attributes for state tracking
    _last_parameter_refresh: datetime | None  # noqa: F821
    _parameter_refresh_interval: timedelta
    _last_dst_sync: datetime | None  # noqa: F821
    _dst_sync_interval: timedelta
    _background_tasks: set[asyncio.Task[Any]]
    _debounced_refresh: Any

    # Methods that mixins may call on each other
    def get_inverter_object(self, serial: str) -> "BaseInverter | None": ...
    def _extract_firmware_update_info(
        self, device: "BaseInverter"
    ) -> dict[str, Any] | None: ...
    async def async_request_refresh(self) -> None: ...


# ===== Utility Functions =====


def _map_device_properties(device: Any, property_map: dict[str, str]) -> dict[str, Any]:
    """Map device properties to sensor keys using a property mapping dictionary.

    This is a generic utility that extracts properties from any device object
    (inverter, MID device, parallel group, battery) and maps them to sensor keys.

    Args:
        device: The device object to extract properties from
        property_map: Dictionary mapping property_name -> sensor_key

    Returns:
        Dictionary of {sensor_key: value} for all found properties with valid values
    """
    sensors: dict[str, Any] = {}

    for property_name, sensor_key in property_map.items():
        if hasattr(device, property_name):
            value = getattr(device, property_name, None)
            # Skip None values and empty strings (which indicate no data)
            if value is not None and value != "":
                sensors[sensor_key] = value

    return sensors


def _safe_numeric(value: Any) -> float:
    """Safely convert value to numeric, defaulting to 0.

    Args:
        value: Any value to convert to float

    Returns:
        Float value or 0.0 if conversion fails
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class DeviceProcessingMixin:
    """Mixin for device data processing logic.

    Handles processing of inverters, batteries, MID devices, and parallel groups.
    Provides static methods for property mapping.
    """

    async def _process_inverter_object(
        self: "CoordinatorProtocol", inverter: "BaseInverter"
    ) -> dict[str, Any]:
        """Process inverter device data from device object using pylxpweb 0.3.3+ properties.

        pylxpweb 0.3.3+ exposes all data through properties - never access .runtime, .energy,
        or .battery_bank directly. All scaling is handled by the library.

        Note: GridBOSS/MID devices are processed separately via _process_mid_device_object()
        and accessed through parallel_group.mid_device, not as inverters.

        Args:
            inverter: BaseInverter object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        # Refresh inverter to load firmware version
        await inverter.refresh()

        # Detect inverter features for capability-based sensor filtering (pylxpweb 0.4.0+)
        features: dict[str, Any] = {}
        try:
            if hasattr(inverter, "detect_features"):
                await inverter.detect_features()
                features = self._extract_inverter_features(inverter)
                _LOGGER.debug(
                    "Detected features for inverter %s: family=%s, split_phase=%s, "
                    "three_phase=%s, parallel=%s",
                    inverter.serial_number,
                    features.get("inverter_family"),
                    features.get("supports_split_phase"),
                    features.get("supports_three_phase"),
                    features.get("supports_parallel"),
                )
        except Exception as e:
            _LOGGER.debug(
                "Could not detect features for inverter %s: %s",
                inverter.serial_number,
                e,
            )

        # Get model and firmware from properties
        model = getattr(inverter, "model", "Unknown")
        firmware_version = getattr(inverter, "firmware_version", "1.0.0")

        # Check for firmware updates (pylxpweb 0.3.7+)
        firmware_update_info = None
        try:
            if hasattr(inverter, "check_firmware_updates"):
                await inverter.check_firmware_updates()
                if hasattr(inverter, "get_firmware_update_progress"):
                    await inverter.get_firmware_update_progress()
                firmware_update_info = self._extract_firmware_update_info(inverter)
        except Exception as e:
            _LOGGER.debug(
                "Could not check firmware updates for %s: %s",
                inverter.serial_number,
                e,
            )

        processed: dict[str, Any] = {
            "serial": inverter.serial_number,
            "type": "inverter",
            "model": model,
            "firmware_version": firmware_version,
            "firmware_update_info": firmware_update_info,
            "features": features,  # Device capabilities for sensor filtering
            "sensors": {},
            "binary_sensors": {},
            "batteries": {},
        }

        # Check if inverter has runtime data
        if not inverter.has_data:
            # Log detailed diagnostics to help debug missing sensor issues
            runtime_attr = getattr(inverter, "_runtime", "NOT_FOUND")
            energy_attr = getattr(inverter, "_energy", "NOT_FOUND")
            _LOGGER.warning(
                "Inverter %s (%s) has no runtime data available (has_data=False). "
                "Runtime sensors will not be created. "
                "Debug: _runtime=%s, _energy=%s. "
                "This may indicate an API issue or unsupported device model.",
                inverter.serial_number,
                model,
                "None" if runtime_attr is None else "present",
                "None" if energy_attr is None else "present",
            )
            # Still add diagnostic sensors even without runtime data
            processed["sensors"]["firmware_version"] = firmware_version
            processed["sensors"]["has_data"] = False
            if features:
                if "inverter_family" in features:
                    processed["sensors"]["inverter_family"] = features[
                        "inverter_family"
                    ]
                if "device_type_code" in features:
                    processed["sensors"]["device_type_code"] = features[
                        "device_type_code"
                    ]
                if "grid_type" in features:
                    processed["sensors"]["grid_type"] = features["grid_type"]
            return processed

        # Map inverter properties to sensor keys
        property_map = self._get_inverter_property_map()
        processed["sensors"] = _map_device_properties(inverter, property_map)

        # Add firmware_version as diagnostic sensor
        processed["sensors"]["firmware_version"] = firmware_version

        # Add feature detection sensors for diagnostics
        if features:
            if "inverter_family" in features:
                processed["sensors"]["inverter_family"] = features["inverter_family"]
            if "device_type_code" in features:
                processed["sensors"]["device_type_code"] = features["device_type_code"]
            if "grid_type" in features:
                processed["sensors"]["grid_type"] = features["grid_type"]

        # Calculate net grid power
        if hasattr(inverter, "power_to_user") and hasattr(inverter, "power_to_grid"):
            power_to_user = _safe_numeric(inverter.power_to_user)
            power_to_grid = _safe_numeric(inverter.power_to_grid)
            processed["sensors"]["grid_power"] = power_to_user - power_to_grid

        # Calculate total load power (EPS + consumption for better power flow representation)
        eps_power = _safe_numeric(processed["sensors"].get("eps_power", 0))
        consumption_power = _safe_numeric(
            processed["sensors"].get("consumption_power", 0)
        )
        if eps_power > 0 or consumption_power > 0:
            processed["sensors"]["total_load_power"] = eps_power + consumption_power

        # Add legacy ac_voltage sensor
        if hasattr(inverter, "eps_voltage_r"):
            processed["sensors"]["ac_voltage"] = inverter.eps_voltage_r

        # Binary sensors
        if hasattr(inverter, "is_lost"):
            processed["binary_sensors"]["is_lost"] = inverter.is_lost
        if hasattr(inverter, "is_using_generator"):
            processed["binary_sensors"]["is_using_generator"] = (
                inverter.is_using_generator
            )

        # Process battery bank aggregate data if available
        battery_bank = getattr(inverter, "_battery_bank", None)
        if battery_bank and battery_bank.battery_count > 0:
            try:
                battery_bank_sensors = self._extract_battery_bank_from_object(
                    battery_bank
                )
                processed["sensors"].update(battery_bank_sensors)
            except Exception as e:
                _LOGGER.warning(
                    "Error extracting battery bank data for inverter %s: %s",
                    inverter.serial_number,
                    e,
                )

        return processed

    @staticmethod
    def _get_inverter_property_map() -> dict[str, str]:
        """Get inverter property mapping dictionary.

        Returns:
            Dictionary mapping inverter property names to sensor keys
        """
        return {
            # Power sensors
            "power_output": "power_output",
            "pv_total_power": "pv_total_power",
            "pv1_power": "pv1_power",
            "pv2_power": "pv2_power",
            "pv3_power": "pv3_power",
            "battery_power": "battery_power",
            "battery_charge_power": "battery_charge_power",
            "battery_discharge_power": "battery_discharge_power",
            "consumption_power": "consumption_power",
            "inverter_power": "ac_power",
            "rectifier_power": "rectifier_power",
            "ac_couple_power": "ac_couple_power",
            "generator_power": "generator_power",
            "eps_power": "eps_power",
            "eps_power_l1": "eps_power_l1",
            "eps_power_l2": "eps_power_l2",
            # Voltage sensors
            "pv1_voltage": "pv1_voltage",
            "pv2_voltage": "pv2_voltage",
            "pv3_voltage": "pv3_voltage",
            "battery_voltage": "battery_voltage",
            "grid_voltage_r": "grid_voltage_r",
            "grid_voltage_s": "grid_voltage_s",
            "grid_voltage_t": "grid_voltage_t",
            "eps_voltage_r": "eps_voltage_r",
            "eps_voltage_s": "eps_voltage_s",
            "eps_voltage_t": "eps_voltage_t",
            "generator_voltage": "generator_voltage",
            "bus1_voltage": "bus1_voltage",
            "bus2_voltage": "bus2_voltage",
            # Frequency sensors
            "grid_frequency": "grid_frequency",
            "eps_frequency": "eps_frequency",
            "generator_frequency": "generator_frequency",
            # Temperature sensors
            "battery_temperature": "battery_temperature",
            "inverter_temperature": "internal_temperature",
            "radiator1_temperature": "radiator1_temperature",
            "radiator2_temperature": "radiator2_temperature",
            # Battery sensors
            "battery_soc": "state_of_charge",
            # Note: battery_status is extracted from BatteryBank.status in
            # _extract_battery_bank_from_object(), not from the inverter directly
            # Energy sensors - Generation
            "total_energy_today": "yield",
            "total_energy_lifetime": "yield_lifetime",
            # Energy sensors - Grid Import/Export
            "energy_today_import": "grid_import",
            "energy_today_export": "grid_export",
            "energy_lifetime_import": "grid_import_lifetime",
            "energy_lifetime_export": "grid_export_lifetime",
            # Energy sensors - Consumption
            "energy_today_usage": "consumption",
            "energy_lifetime_usage": "consumption_lifetime",
            # Energy sensors - Battery Charging/Discharging
            "energy_today_charging": "charging",
            "energy_today_discharging": "discharging",
            "energy_lifetime_charging": "charging_lifetime",
            "energy_lifetime_discharging": "discharging_lifetime",
            # Current sensors
            "max_charge_current": "max_charge_current",
            "max_discharge_current": "max_discharge_current",
            # Grid power sensors (instantaneous)
            "power_to_user": "grid_import_power",
            "power_to_grid": "grid_export_power",
            # Other sensors
            "power_rating": "power_rating",
            "power_rating_text": "inverter_power_rating",
            "power_factor": "power_factor",
            "status_text": "status_text",
            "status": "status_code",
            "has_data": "has_data",
            # Diagnostic sensors from energy API
            "is_lost": "inverter_lost_status",
            "has_runtime_data": "inverter_has_runtime_data",
        }

    @staticmethod
    def _extract_inverter_features(inverter: "BaseInverter") -> dict[str, Any]:
        """Extract feature capabilities from inverter object.

        This method extracts the detected features from a pylxpweb inverter
        object after detect_features() has been called. The features are used
        for capability-based sensor filtering.

        Args:
            inverter: BaseInverter object with features detected

        Returns:
            Dictionary of feature flags for sensor filtering
        """
        features: dict[str, Any] = {}

        # Get the features object if available
        inverter_features = getattr(inverter, "_features", None)
        if inverter_features is None:
            return features

        # Extract inverter family (SNA, PV_SERIES, LXP_EU, etc.)
        if hasattr(inverter_features, "model_family"):
            family = inverter_features.model_family
            features["inverter_family"] = (
                family.value if isinstance(family, InverterFamily) else str(family)
            )
        else:
            features["inverter_family"] = InverterFamily.UNKNOWN.value

        # Extract grid type
        if hasattr(inverter_features, "grid_type"):
            features["grid_type"] = str(inverter_features.grid_type.value)

        # Extract device type code for debugging
        if hasattr(inverter_features, "device_type_code"):
            features["device_type_code"] = inverter_features.device_type_code

        # Extract boolean capability flags using supports_* properties
        # Maps feature key to InverterFeatures attribute name
        # Some attributes don't follow simple "supports_X" -> "X" pattern
        capability_mapping: dict[str, str] = {
            "supports_split_phase": "split_phase",
            "supports_three_phase": "three_phase_capable",
            "supports_off_grid": "off_grid_capable",
            "supports_parallel": "parallel_support",
            "supports_volt_watt_curve": "volt_watt_curve",
            "supports_grid_peak_shaving": "grid_peak_shaving",
            "supports_drms": "drms_support",
            "supports_discharge_recovery_hysteresis": "discharge_recovery_hysteresis",
        }

        for prop, attr_name in capability_mapping.items():
            if hasattr(inverter, prop):
                features[prop] = getattr(inverter, prop, False)
            elif hasattr(inverter_features, attr_name):
                # Fallback to features object attribute using correct mapping
                features[prop] = getattr(inverter_features, attr_name, False)

        return features

    def _extract_battery_from_object(self, battery: "Battery") -> dict[str, Any]:
        """Extract sensor data from Battery object using properties.

        Args:
            battery: Battery object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        property_map = self._get_battery_property_map()
        sensors = _map_device_properties(battery, property_map)
        self._calculate_battery_derived_sensors(sensors)
        return sensors

    @staticmethod
    def _get_battery_property_map() -> dict[str, str]:
        """Get battery property mapping dictionary.

        Returns:
            Dictionary mapping battery property names to sensor keys
        """
        return {
            # Core battery metrics
            "voltage": "battery_real_voltage",
            "current": "battery_real_current",
            "power": "battery_real_power",
            "soc": "battery_rsoc",
            "soh": "state_of_health",
            # Temperature sensors
            "mos_temp": "battery_mos_temperature",
            "ambient_temp": "battery_ambient_temperature",
            "max_cell_temp": "battery_max_cell_temp",
            "min_cell_temp": "battery_min_cell_temp",
            "max_cell_temp_num": "battery_max_cell_temp_num",
            "min_cell_temp_num": "battery_min_cell_temp_num",
            # Cell voltage sensors
            "max_cell_voltage": "battery_max_cell_voltage",
            "min_cell_voltage": "battery_min_cell_voltage",
            "max_cell_voltage_num": "battery_max_cell_voltage_num",
            "min_cell_voltage_num": "battery_min_cell_voltage_num",
            "cell_voltage_delta": "battery_cell_voltage_delta",
            "cell_temp_delta": "battery_cell_temp_delta",
            # Capacity sensors
            "current_remain_capacity": "battery_remaining_capacity",
            "current_full_capacity": "battery_full_capacity",
            "charge_capacity": "battery_design_capacity",
            "discharge_capacity": "battery_discharge_capacity",
            "capacity_percent": "battery_capacity_percentage",
            # Current limits
            "charge_max_current": "battery_max_charge_current",
            "charge_voltage_ref": "battery_charge_voltage_ref",
            # Lifecycle
            "cycle_count": "cycle_count",
            "firmware_version": "battery_firmware_version",
            # Metadata
            "battery_sn": "battery_serial_number",
            "battery_type": "battery_type",
            "battery_type_text": "battery_type_text",
            "bms_model": "battery_bms_model",
            "model": "battery_model",
            "battery_index": "battery_index",
        }

    @staticmethod
    def _calculate_battery_derived_sensors(sensors: dict[str, Any]) -> None:
        """Calculate derived battery sensors from raw sensor data.

        Modifies the sensors dictionary in place to add calculated values.

        Args:
            sensors: Dictionary of sensor values to modify
        """
        # Calculate cell voltage difference only if not provided by library
        if (
            "battery_cell_voltage_diff" not in sensors
            and "battery_cell_voltage_max" in sensors
            and "battery_cell_voltage_min" in sensors
        ):
            sensors["battery_cell_voltage_diff"] = round(
                sensors["battery_cell_voltage_max"]
                - sensors["battery_cell_voltage_min"],
                3,
            )

        # Calculate capacity percentage only if not provided by library
        if (
            "battery_capacity_percentage" not in sensors
            and "battery_remaining_capacity" in sensors
            and "battery_full_capacity" in sensors
            and sensors["battery_full_capacity"] > 0
        ):
            sensors["battery_capacity_percentage"] = round(
                sensors["battery_remaining_capacity"]
                / sensors["battery_full_capacity"]
                * 100,
                1,
            )

    def _extract_battery_bank_from_object(self, battery_bank: Any) -> dict[str, Any]:
        """Extract sensor data from BatteryBank object using properties.

        Args:
            battery_bank: BatteryBank object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        property_map = self._get_battery_bank_property_map()
        sensors = _map_device_properties(battery_bank, property_map)

        # Add battery_status as alias for battery_bank_status for backwards compatibility
        # In v2.2.x, the batStatus field was mapped to battery_status at the inverter level
        # This maintains the sensor for users upgrading from v2.2.x
        if "battery_bank_status" in sensors:
            sensors["battery_status"] = sensors["battery_bank_status"]

        return sensors

    @staticmethod
    def _get_battery_bank_property_map() -> dict[str, str]:
        """Get battery bank property mapping dictionary.

        Returns:
            Dictionary mapping battery bank property names to sensor keys
        """
        return {
            # Core metrics
            "voltage": "battery_bank_voltage",
            "soc": "battery_bank_soc",
            "charge_power": "battery_bank_charge_power",
            "discharge_power": "battery_bank_discharge_power",
            "battery_power": "battery_bank_power",
            # Capacity metrics
            "max_capacity": "battery_bank_max_capacity",
            "current_capacity": "battery_bank_current_capacity",
            "remain_capacity": "battery_bank_remain_capacity",
            "full_capacity": "battery_bank_full_capacity",
            "capacity_percent": "battery_bank_capacity_percent",
            # Status and metadata
            "battery_count": "battery_bank_count",
            "status": "battery_bank_status",
        }

    async def _process_parallel_group_object(self, group: Any) -> dict[str, Any]:
        """Process parallel group data from group object using properties.

        Args:
            group: ParallelGroup object from pylxpweb

        Returns:
            Processed device data dictionary with sensors
        """
        processed: dict[str, Any] = {
            "name": f"Parallel Group {group.name}"
            if hasattr(group, "name") and group.name
            else "Parallel Group",
            "type": "parallel_group",
            "model": "Parallel Group",
            "sensors": {},
            "binary_sensors": {},
        }

        property_map = self._get_parallel_group_property_map()
        processed["sensors"] = _map_device_properties(group, property_map)

        return processed

    @staticmethod
    def _get_parallel_group_property_map() -> dict[str, str]:
        """Get parallel group property mapping dictionary.

        Returns:
            Dictionary mapping parallel group property names to sensor keys
        """
        return {
            # Today energy values
            "today_yielding": "yield",
            "today_discharging": "discharging",
            "today_charging": "charging",
            "today_export": "grid_export",
            "today_import": "grid_import",
            "today_usage": "consumption",
            # Lifetime energy values
            "total_yielding": "yield_lifetime",
            "total_discharging": "discharging_lifetime",
            "total_charging": "charging_lifetime",
            "total_export": "grid_export_lifetime",
            "total_import": "grid_import_lifetime",
            "total_usage": "consumption_lifetime",
        }

    async def _process_mid_device_object(self, mid_device: Any) -> dict[str, Any]:
        """Process GridBOSS/MID device data from device object using properties.

        Args:
            mid_device: MIDDevice object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        await mid_device.refresh()

        model = getattr(mid_device, "model", "GridBOSS")
        firmware_version = getattr(mid_device, "firmware_version", "1.0.0")

        firmware_update_info = None
        try:
            if hasattr(mid_device, "check_firmware_updates"):
                await mid_device.check_firmware_updates()
                if hasattr(mid_device, "get_firmware_update_progress"):
                    await mid_device.get_firmware_update_progress()
                firmware_update_info = self._extract_firmware_update_info(mid_device)
        except Exception as e:
            _LOGGER.debug(
                "Could not check firmware updates for %s: %s",
                mid_device.serial_number,
                e,
            )

        processed: dict[str, Any] = {
            "serial": mid_device.serial_number,
            "type": "gridboss",
            "model": model,
            "firmware_version": firmware_version,
            "firmware_update_info": firmware_update_info,
            "sensors": {},
            "binary_sensors": {},
        }

        if mid_device.has_data:
            property_map = self._get_mid_device_property_map()
            processed["sensors"] = _map_device_properties(mid_device, property_map)
            processed["sensors"]["firmware_version"] = firmware_version
            self._filter_unused_smart_port_sensors(processed["sensors"], mid_device)
            self._calculate_gridboss_aggregates(processed["sensors"])
        else:
            _LOGGER.warning("MID device %s has no data", mid_device.serial_number)

        return processed

    @staticmethod
    def _get_mid_device_property_map() -> dict[str, str]:
        """Get MID device property mapping dictionary.

        Returns:
            Dictionary mapping MID device property names to sensor keys
        """
        return {
            # Grid sensors
            "grid_power": "grid_power",
            "grid_voltage": "grid_voltage",
            "grid_frequency": "frequency",
            "grid_l1_power": "grid_power_l1",
            "grid_l2_power": "grid_power_l2",
            "grid_l1_voltage": "grid_voltage_l1",
            "grid_l2_voltage": "grid_voltage_l2",
            "grid_l1_current": "grid_current_l1",
            "grid_l2_current": "grid_current_l2",
            # UPS sensors
            "ups_power": "ups_power",
            "ups_voltage": "ups_voltage",
            "ups_l1_power": "ups_power_l1",
            "ups_l2_power": "ups_power_l2",
            "ups_l1_voltage": "load_voltage_l1",
            "ups_l2_voltage": "load_voltage_l2",
            "ups_l1_current": "ups_current_l1",
            "ups_l2_current": "ups_current_l2",
            # Load sensors
            "load_power": "load_power",
            "load_l1_power": "load_power_l1",
            "load_l2_power": "load_power_l2",
            "load_l1_current": "load_current_l1",
            "load_l2_current": "load_current_l2",
            # Generator sensors
            "generator_power": "generator_power",
            "generator_voltage": "generator_voltage",
            "generator_l1_power": "generator_power_l1",
            "generator_l2_power": "generator_power_l2",
            "generator_l1_voltage": "generator_voltage_l1",
            "generator_l2_voltage": "generator_voltage_l2",
            "generator_l1_current": "generator_current_l1",
            "generator_l2_current": "generator_current_l2",
            # Other sensors
            "hybrid_power": "hybrid_power",
            "phase_lock_frequency": "phase_lock_frequency",
            "smart_port1_status": "smart_port1_status",
            "smart_port2_status": "smart_port2_status",
            "smart_port3_status": "smart_port3_status",
            "smart_port4_status": "smart_port4_status",
            # UPS Energy sensors (today)
            "e_ups_today_l1": "ups_l1",
            "e_ups_today_l2": "ups_l2",
            # UPS Energy sensors (lifetime/total)
            "e_ups_total_l1": "ups_lifetime_l1",
            "e_ups_total_l2": "ups_lifetime_l2",
            # Grid Energy sensors (today)
            "e_to_grid_today_l1": "grid_export_l1",
            "e_to_grid_today_l2": "grid_export_l2",
            "e_to_user_today_l1": "grid_import_l1",
            "e_to_user_today_l2": "grid_import_l2",
            # Grid Energy sensors (lifetime/total)
            "e_to_grid_total_l1": "grid_export_lifetime_l1",
            "e_to_grid_total_l2": "grid_export_lifetime_l2",
            "e_to_user_total_l1": "grid_import_lifetime_l1",
            "e_to_user_total_l2": "grid_import_lifetime_l2",
            # Load Energy sensors (today)
            "e_load_today_l1": "load_l1",
            "e_load_today_l2": "load_l2",
            # Load Energy sensors (lifetime/total)
            "e_load_total_l1": "load_lifetime_l1",
            "e_load_total_l2": "load_lifetime_l2",
            # AC Couple Energy sensors (today)
            "e_ac_couple1_today_l1": "ac_couple1_l1",
            "e_ac_couple1_today_l2": "ac_couple1_l2",
            "e_ac_couple2_today_l1": "ac_couple2_l1",
            "e_ac_couple2_today_l2": "ac_couple2_l2",
            "e_ac_couple3_today_l1": "ac_couple3_l1",
            "e_ac_couple3_today_l2": "ac_couple3_l2",
            "e_ac_couple4_today_l1": "ac_couple4_l1",
            "e_ac_couple4_today_l2": "ac_couple4_l2",
            # AC Couple Energy sensors (lifetime/total)
            "e_ac_couple1_total_l1": "ac_couple1_lifetime_l1",
            "e_ac_couple1_total_l2": "ac_couple1_lifetime_l2",
            "e_ac_couple2_total_l1": "ac_couple2_lifetime_l1",
            "e_ac_couple2_total_l2": "ac_couple2_lifetime_l2",
            "e_ac_couple3_total_l1": "ac_couple3_lifetime_l1",
            "e_ac_couple3_total_l2": "ac_couple3_lifetime_l2",
            "e_ac_couple4_total_l1": "ac_couple4_lifetime_l1",
            "e_ac_couple4_total_l2": "ac_couple4_lifetime_l2",
            # Smart Load Power sensors (runtime data)
            "smart_load1_l1_active_power": "smart_load1_power_l1",
            "smart_load1_l2_active_power": "smart_load1_power_l2",
            "smart_load2_l1_active_power": "smart_load2_power_l1",
            "smart_load2_l2_active_power": "smart_load2_power_l2",
            "smart_load3_l1_active_power": "smart_load3_power_l1",
            "smart_load3_l2_active_power": "smart_load3_power_l2",
            "smart_load4_l1_active_power": "smart_load4_power_l1",
            "smart_load4_l2_active_power": "smart_load4_power_l2",
            # Smart Load Energy sensors (today)
            "e_smart_load1_today_l1": "smart_load1_l1",
            "e_smart_load1_today_l2": "smart_load1_l2",
            "e_smart_load2_today_l1": "smart_load2_l1",
            "e_smart_load2_today_l2": "smart_load2_l2",
            "e_smart_load3_today_l1": "smart_load3_l1",
            "e_smart_load3_today_l2": "smart_load3_l2",
            "e_smart_load4_today_l1": "smart_load4_l1",
            "e_smart_load4_today_l2": "smart_load4_l2",
            # Smart Load Energy sensors (lifetime/total)
            "e_smart_load1_total_l1": "smart_load1_lifetime_l1",
            "e_smart_load1_total_l2": "smart_load1_lifetime_l2",
            "e_smart_load2_total_l1": "smart_load2_lifetime_l1",
            "e_smart_load2_total_l2": "smart_load2_lifetime_l2",
            "e_smart_load3_total_l1": "smart_load3_lifetime_l1",
            "e_smart_load3_total_l2": "smart_load3_lifetime_l2",
            "e_smart_load4_total_l1": "smart_load4_lifetime_l1",
            "e_smart_load4_total_l2": "smart_load4_lifetime_l2",
        }

    @staticmethod
    def _filter_unused_smart_port_sensors(
        sensors: dict[str, Any], mid_device: Any
    ) -> None:
        """Filter out sensors for unused Smart Ports from MID device.

        Modifies the sensors dictionary in place.

        Args:
            sensors: Dictionary of sensor values to modify
            mid_device: MID device object to read port statuses from
        """
        smart_port_statuses = {}
        for port in range(1, 5):
            status_property = f"smart_port{port}_status"
            if hasattr(mid_device, status_property):
                status_value = getattr(mid_device, status_property)
                smart_port_statuses[port] = status_value

        sensors_to_remove = []
        for port, status in smart_port_statuses.items():
            if status == 0:
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

        for sensor_key in sensors_to_remove:
            sensors.pop(sensor_key, None)

    @staticmethod
    def _calculate_gridboss_aggregates(sensors: dict[str, Any]) -> None:
        """Calculate aggregate sensor values from individual L1/L2 values.

        Modifies the sensors dictionary in place.

        Args:
            sensors: Dictionary of sensor values to modify
        """
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

        # Calculate UPS consumption aggregates (today)
        if "ups_l1" in sensors and "ups_l2" in sensors:
            ups_l1 = _safe_numeric(sensors["ups_l1"])
            ups_l2 = _safe_numeric(sensors["ups_l2"])
            sensors["ups_consumption"] = ups_l1 + ups_l2

        # Calculate UPS consumption aggregates (lifetime)
        if "ups_lifetime_l1" in sensors and "ups_lifetime_l2" in sensors:
            ups_l1 = _safe_numeric(sensors["ups_lifetime_l1"])
            ups_l2 = _safe_numeric(sensors["ups_lifetime_l2"])
            sensors["ups_consumption_lifetime"] = ups_l1 + ups_l2

        # Calculate Load energy aggregates (today)
        if "load_l1" in sensors and "load_l2" in sensors:
            load_l1 = _safe_numeric(sensors["load_l1"])
            load_l2 = _safe_numeric(sensors["load_l2"])
            sensors["load"] = load_l1 + load_l2

        # Calculate Load energy aggregates (lifetime)
        if "load_lifetime_l1" in sensors and "load_lifetime_l2" in sensors:
            load_l1 = _safe_numeric(sensors["load_lifetime_l1"])
            load_l2 = _safe_numeric(sensors["load_lifetime_l2"])
            sensors["load_lifetime"] = load_l1 + load_l2

        # Calculate Grid Import aggregates (today)
        if "grid_import_l1" in sensors and "grid_import_l2" in sensors:
            import_l1 = _safe_numeric(sensors["grid_import_l1"])
            import_l2 = _safe_numeric(sensors["grid_import_l2"])
            sensors["grid_import"] = import_l1 + import_l2

        # Calculate Grid Import aggregates (lifetime)
        if (
            "grid_import_lifetime_l1" in sensors
            and "grid_import_lifetime_l2" in sensors
        ):
            import_l1 = _safe_numeric(sensors["grid_import_lifetime_l1"])
            import_l2 = _safe_numeric(sensors["grid_import_lifetime_l2"])
            sensors["grid_import_lifetime"] = import_l1 + import_l2

        # Calculate Grid Export aggregates (today)
        if "grid_export_l1" in sensors and "grid_export_l2" in sensors:
            export_l1 = _safe_numeric(sensors["grid_export_l1"])
            export_l2 = _safe_numeric(sensors["grid_export_l2"])
            sensors["grid_export"] = export_l1 + export_l2

        # Calculate Grid Export aggregates (lifetime)
        if (
            "grid_export_lifetime_l1" in sensors
            and "grid_export_lifetime_l2" in sensors
        ):
            export_l1 = _safe_numeric(sensors["grid_export_lifetime_l1"])
            export_l2 = _safe_numeric(sensors["grid_export_lifetime_l2"])
            sensors["grid_export_lifetime"] = export_l1 + export_l2


class DeviceInfoMixin:
    """Mixin for device info retrieval methods."""

    def get_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for a specific serial number."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "unknown")

        if device_type == "parallel_group":
            device_name = device_data.get("name", model)
        else:
            device_name = f"{model} {serial}"

        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": model,
        }

        if device_type != "parallel_group":
            device_info["serial_number"] = serial
            sw_version = "1.0.0"
            if device_type in ["gridboss", "inverter"]:
                sw_version = device_data.get("firmware_version", "1.0.0")
            device_info["sw_version"] = sw_version

        if device_type in ["inverter", "gridboss"]:
            parallel_group_serial = self._get_parallel_group_for_device(serial)
            if parallel_group_serial:
                device_info["via_device"] = (DOMAIN, parallel_group_serial)

        return cast(DeviceInfo, device_info)

    def _get_parallel_group_for_device(self, device_serial: str) -> str | None:
        """Get the parallel group serial that contains this device."""
        if not self.data or "devices" not in self.data:
            return None

        if self.station and hasattr(self.station, "parallel_groups"):
            for group in self.station.parallel_groups:
                if hasattr(group, "inverters"):
                    for inverter in group.inverters:
                        if inverter.serial_number == device_serial:
                            return f"parallel_group_{group.first_device_serial}"

        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                return str(serial)

        return None

    def get_battery_device_info(
        self, serial: str, battery_key: str
    ) -> DeviceInfo | None:
        """Get device information for a specific battery."""
        if not self.data or "devices" not in self.data:
            _LOGGER.debug(
                "get_battery_device_info(%s, %s): No data available",
                serial,
                battery_key,
            )
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data or battery_key not in device_data.get("batteries", {}):
            _LOGGER.debug(
                "get_battery_device_info(%s, %s): Device or battery not found",
                serial,
                battery_key,
            )
            return None

        battery_data = device_data.get("batteries", {}).get(battery_key, {})
        battery_firmware = battery_data.get("battery_firmware_version", "1.0.0")

        bms_model = battery_data.get("battery_bms_model")
        battery_model_name = battery_data.get("battery_model")
        battery_type_text = battery_data.get("battery_type_text")
        model = bms_model or battery_model_name or battery_type_text or "Battery Module"

        _LOGGER.debug(
            "Battery %s model selection: bms_model=%s, battery_model=%s, "
            "type_text=%s, final_model=%s",
            battery_key,
            bms_model,
            battery_model_name,
            battery_type_text,
            model,
        )

        clean_battery_name = clean_battery_display_name(battery_key, serial)
        battery_bank_identifier = f"{serial}_battery_bank"

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, battery_key)},
            "name": f"Battery {clean_battery_name}",
            "manufacturer": MANUFACTURER,
            "model": model,
            "sw_version": battery_firmware,
            "via_device": (DOMAIN, battery_bank_identifier),
        }

        _LOGGER.debug(
            "Created battery device_info for %s: name='%s', model='%s', "
            "identifier='%s', via_device=%s",
            battery_key,
            device_info["name"],
            model,
            battery_key,
            battery_bank_identifier,
        )

        return device_info

    def get_battery_bank_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for battery bank (aggregate of all batteries)."""
        if not self.data or "devices" not in self.data:
            _LOGGER.debug("get_battery_bank_device_info(%s): No data available", serial)
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            _LOGGER.debug("get_battery_bank_device_info(%s): Device not found", serial)
            return None

        sensors = device_data.get("sensors", {})
        battery_count = sensors.get("battery_bank_count", 0)

        if battery_count == 0:
            _LOGGER.debug(
                "get_battery_bank_device_info(%s): No batteries (count=0)", serial
            )
            return None

        model = device_data.get("model", "Unknown")

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, f"{serial}_battery_bank")},
            "name": f"Battery Bank {serial}",
            "manufacturer": MANUFACTURER,
            "model": f"{model} Battery Bank",
            "via_device": (DOMAIN, serial),
        }

        _LOGGER.debug(
            "Created battery_bank device_info for %s: name='%s', model='%s', "
            "battery_count=%d, via_device=%s",
            serial,
            device_info["name"],
            device_info["model"],
            battery_count,
            serial,
        )

        return device_info

    def get_station_device_info(self) -> DeviceInfo | None:
        """Get device information for the station/plant."""
        if not self.data or "station" not in self.data:
            return None

        station_data = self.data["station"]
        station_name = station_data.get("name", f"Station {self.plant_id}")

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, f"station_{self.plant_id}")},
            "name": f"Station {station_name}",
            "manufacturer": MANUFACTURER,
            "model": "Station",
            "configuration_url": f"{self.client.base_url}/WManage/web/config/plant/edit/{self.plant_id}",
        }
        return device_info


class ParameterManagementMixin:
    """Mixin for device parameter refresh operations."""

    async def refresh_all_device_parameters(self) -> None:
        """Refresh parameters for all inverter devices when any parameter changes."""
        try:
            _LOGGER.info(
                "Refreshing parameters for all inverter devices due to parameter change"
            )

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

            refresh_tasks = []
            for serial in inverter_serials:
                task = self._refresh_device_parameters(serial)
                refresh_tasks.append(task)

            results = await asyncio.gather(*refresh_tasks, return_exceptions=True)

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
        """Public method to refresh parameters for a specific device."""
        try:
            _LOGGER.debug("Refreshing parameters for device %s", serial)
            await self._refresh_device_parameters(serial)
            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)

    async def _refresh_device_parameters(self, serial: str) -> None:
        """Refresh parameters for a specific device using device object."""
        try:
            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.warning("Cannot find inverter object for serial %s", serial)
                return

            # Use force=True to bypass cache when refreshing parameters after changes
            await inverter.refresh(force=True, include_parameters=True)

            if hasattr(inverter, "parameters") and inverter.parameters:
                if not self.data:
                    return

                if "parameters" not in self.data:
                    self.data["parameters"] = {}

                self.data["parameters"][serial] = inverter.parameters
            else:
                _LOGGER.warning(
                    "Inverter %s has no parameters attribute or empty parameters",
                    serial,
                )

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for device %s: %s", serial, e)
            raise

    async def _refresh_missing_parameters(
        self, inverter_serials: list[str], processed_data: dict[str, Any]
    ) -> None:
        """Refresh parameters for inverters that don't have them yet."""
        try:
            for serial in inverter_serials:
                try:
                    await self._refresh_device_parameters(serial)
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

            await self.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error during missing parameter refresh: %s", e)

    async def _hourly_parameter_refresh(self) -> None:
        """Perform hourly parameter refresh for all inverters."""
        try:
            await self.refresh_all_device_parameters()
            self._last_parameter_refresh = dt_util.utcnow()
        except Exception as e:
            _LOGGER.error("Error during hourly parameter refresh: %s", e)

    def _should_refresh_parameters(self) -> bool:
        """Check if hourly parameter refresh is due."""
        if self._last_parameter_refresh is None:
            return True

        time_since_refresh = dt_util.utcnow() - self._last_parameter_refresh
        return bool(time_since_refresh >= self._parameter_refresh_interval)


class DSTSyncMixin:
    """Mixin for daylight saving time synchronization operations."""

    def _should_sync_dst(self) -> bool:
        """Check if DST sync is due.

        Performs DST sync one minute before the top of each hour.
        """
        now = dt_util.utcnow()

        minutes_to_hour = 60 - now.minute
        is_near_hour = minutes_to_hour <= 1

        if not is_near_hour:
            return False

        if self._last_dst_sync is None:
            return True

        time_since_sync = now - self._last_dst_sync
        return bool(time_since_sync >= self._dst_sync_interval)

    async def _perform_dst_sync(self) -> None:
        """Perform DST synchronization if needed."""
        if not self.dst_sync_enabled or not self.station:
            return

        try:
            dst_status = self.station.detect_dst_status()
            if dst_status is False:
                _LOGGER.info(
                    "DST mismatch detected for station %s, syncing DST setting",
                    self.plant_id,
                )
                sync_result = await self.station.sync_dst_setting()
                if sync_result:
                    _LOGGER.info(
                        "DST setting synchronized successfully for station %s",
                        self.plant_id,
                    )
                else:
                    _LOGGER.warning(
                        "Failed to synchronize DST setting for station %s",
                        self.plant_id,
                    )
                self._last_dst_sync = dt_util.utcnow()
            elif dst_status is True:
                _LOGGER.debug(
                    "DST setting is already correct for station %s",
                    self.plant_id,
                )
                self._last_dst_sync = dt_util.utcnow()
            else:
                _LOGGER.debug(
                    "DST status could not be determined for station %s",
                    self.plant_id,
                )
                self._last_dst_sync = dt_util.utcnow()
        except Exception as e:
            _LOGGER.warning(
                "Error during DST sync for station %s: %s", self.plant_id, e
            )
            self._last_dst_sync = dt_util.utcnow()


class BackgroundTaskMixin:
    """Mixin for background task management operations."""

    async def _async_handle_shutdown(self, event: Any) -> None:
        """Handle Home Assistant stop event to cancel background tasks."""
        _LOGGER.debug("Handling Home Assistant stop event, cancelling background tasks")

        if hasattr(self, "_debounced_refresh") and self._debounced_refresh:
            self._debounced_refresh.async_cancel()
            await asyncio.sleep(0)
            _LOGGER.debug("Cancelled debounced refresh")

        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        _LOGGER.debug("All background tasks cancelled and cleaned up")

    async def async_shutdown(self) -> None:
        """Clean up background tasks and event listeners on shutdown."""
        if hasattr(self, "_shutdown_listener_remove"):
            self._shutdown_listener_remove()
            _LOGGER.debug("Removed homeassistant_stop event listener")

        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        _LOGGER.debug("Coordinator shutdown complete, all background tasks cleaned up")

    def _remove_task_from_set(self, task: asyncio.Task[Any]) -> None:
        """Remove completed task from background tasks set."""
        self._background_tasks.discard(task)

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        """Log exception from completed task if not cancelled."""
        if not task.cancelled():
            exception = task.exception()
            if exception:
                _LOGGER.error(
                    "Background task failed with exception: %s",
                    exception,
                    exc_info=exception,
                )


class FirmwareUpdateMixin:
    """Mixin for firmware update information extraction."""

    def _extract_firmware_update_info(
        self, device: "BaseInverter"
    ) -> dict[str, Any] | None:
        """Extract firmware update information from device object.

        Args:
            device: Inverter or MID device object with FirmwareUpdateMixin

        Returns:
            Dictionary with firmware update info or None if no update available
        """
        if not hasattr(device, "firmware_update_available"):
            return None

        if not device.firmware_update_available:
            return None

        update_info = {
            "latest_version": device.latest_firmware_version,
            "title": device.firmware_update_title,
            "release_summary": device.firmware_update_summary,
            "release_url": device.firmware_update_url,
            "in_progress": False,
            "update_percentage": None,
        }

        if hasattr(device, "firmware_update_in_progress"):
            update_info["in_progress"] = device.firmware_update_in_progress

        if hasattr(device, "firmware_update_percentage"):
            update_info["update_percentage"] = device.firmware_update_percentage

        return update_info
