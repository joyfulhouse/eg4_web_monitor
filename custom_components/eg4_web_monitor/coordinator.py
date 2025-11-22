"""Data update coordinator for EG4 Web Monitor integration using pylxpweb device objects."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

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

from pylxpweb import LuxpowerClient
from pylxpweb.devices import Battery, Station
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from .const import (
    BATTERY_KEY_SEPARATOR,
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .utils import (
    CircuitBreaker,
    clean_battery_display_name,
)

_LOGGER = logging.getLogger(__name__)


# ===== Utility Functions for Property Mapping =====


def _map_device_properties(
    device: Any, property_map: dict[str, str], logger_prefix: str = ""
) -> dict[str, Any]:
    """Map device properties to sensor keys using a property mapping dictionary.

    This is a generic utility that extracts properties from any device object
    (inverter, MID device, parallel group, battery) and maps them to sensor keys.

    Args:
        device: The device object to extract properties from
        property_map: Dictionary mapping property_name -> sensor_key
        logger_prefix: Optional prefix for debug logging

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

    if logger_prefix:
        _LOGGER.debug(f"{logger_prefix}: Mapped {len(sensors)} properties from device")

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


class EG4DataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching EG4 Web Monitor data from the API using device objects."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.plant_id = entry.data[CONF_PLANT_ID]

        # Get Home Assistant timezone as IANA timezone string for DST detection
        # This enables pylxpweb DST auto-detection feature
        iana_timezone = str(hass.config.time_zone) if hass.config.time_zone else None

        # Initialize Luxpower API client with injected session (Platinum tier requirement)
        # Home Assistant manages the aiohttp ClientSession for efficient resource usage
        # pylxpweb 0.3.0 provides automatic session management, caching, and re-authentication
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

        # DST sync configuration
        self.dst_sync_enabled = entry.data.get(CONF_DST_SYNC, True)

        # Station object for device hierarchy
        self.station: Station | None = None

        # Device tracking
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_sensors: dict[str, list[str]] = {}

        # Parameter refresh tracking
        self._last_parameter_refresh: datetime | None = None
        self._parameter_refresh_interval = timedelta(
            hours=1
        )  # Hourly parameter refresh

        # DST sync tracking
        self._last_dst_sync: datetime | None = None
        self._dst_sync_interval = timedelta(hours=1)  # Hourly DST check

        # Note: Cache invalidation is automatic in pylxpweb 0.3.3+
        # No manual tracking needed - library clears cache on hour boundaries

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint using device objects.

        This is the main data update method called by Home Assistant's coordinator
        at regular intervals (default: 30 seconds). It orchestrates the entire
        data refresh process including:
        - Automatic cache invalidation (handled by pylxpweb library)
        - Hourly parameter refresh for device settings
        - DST synchronization for accurate time-based operations
        - Device data processing and sensor extraction

        Returns:
            Dictionary containing all device data, sensors, and station information.
            Structure:
            {
                "plant_id": str,
                "devices": {serial: device_data_dict, ...},
                "device_info": {serial: raw_api_info, ...},
                "parameters": {serial: parameters_dict, ...},
                "station": station_data_dict,
                "last_update": datetime
            }

        Raises:
            ConfigEntryAuthFailed: If authentication fails (triggers reauthentication flow).
            UpdateFailed: If connection or API errors occur (marks entities unavailable).

        Note:
            Cache invalidation is automatic in pylxpweb 0.3.3+. The library
            automatically clears cache on the first request after an hour boundary.
        """
        try:
            _LOGGER.debug("Fetching data for plant %s", self.plant_id)

            # Cache invalidation is now automatic in pylxpweb 0.3.3+
            # The library automatically clears cache on first request after hour boundary
            # No manual intervention needed

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
                task.add_done_callback(self._remove_task_from_set)
                task.add_done_callback(self._log_task_exception)

            # Load or refresh station data using device objects
            if self.station is None:
                _LOGGER.info("Loading station data for plant %s", self.plant_id)
                self.station = await Station.load(self.client, self.plant_id)
                # Always refresh after initial load to populate battery data
                _LOGGER.debug(
                    "Refreshing all data after station load to populate battery details"
                )
                await self.station.refresh_all_data()
            else:
                _LOGGER.debug("Refreshing station data for plant %s", self.plant_id)
                await self.station.refresh_all_data()

            # Perform DST sync if enabled and due (pylxpweb 0.2.8 feature)
            # Checks within 1 minute before each hour to catch DST transitions optimally
            if self.dst_sync_enabled and self.station and self._should_sync_dst():
                try:
                    # Check if DST correction is needed
                    dst_status = self.station.detect_dst_status()
                    if dst_status is False:  # DST mismatch detected
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
                        # Update last sync time regardless of success
                        self._last_dst_sync = dt_util.utcnow()
                    elif dst_status is True:
                        _LOGGER.debug(
                            "DST setting is already correct for station %s",
                            self.plant_id,
                        )
                        # Update last sync time since we checked
                        self._last_dst_sync = dt_util.utcnow()
                    else:
                        _LOGGER.debug(
                            "DST status could not be determined for station %s",
                            self.plant_id,
                        )
                        # Update last sync time to avoid repeated failures
                        self._last_dst_sync = dt_util.utcnow()
                except Exception as e:
                    _LOGGER.warning(
                        "Error during DST sync for station %s: %s", self.plant_id, e
                    )
                    # Update last sync time to avoid repeated errors
                    self._last_dst_sync = dt_util.utcnow()

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

        # Add station data - extract all available fields from Station object
        # Station object (pylxpweb 0.3.0) provides plant/station configuration data:
        # - name: Station/plant name
        # - id: Plant ID
        # - location.country: Country name (from Location object)
        # - timezone: Timezone string (e.g., "GMT -8")
        # - location.address: Physical address (from Location object)
        # - created_date: Plant creation date (datetime object)
        processed["station"] = {
            "name": self.station.name,
            "plant_id": self.station.id,
        }

        # Add optional fields using getattr() for cleaner attribute access
        if timezone := getattr(self.station, "timezone", None):
            processed["station"]["timezone"] = timezone

        # Extract location data from Location object
        if location := getattr(self.station, "location", None):
            if country := getattr(location, "country", None):
                processed["station"]["country"] = country
            if address := getattr(location, "address", None):
                processed["station"]["address"] = address

        # Convert datetime to ISO string for JSON serialization
        if created_date := getattr(self.station, "created_date", None):
            processed["station"]["createDate"] = created_date.isoformat()

        # Process all inverters in the station
        for inverter in self.station.all_inverters:
            try:
                processed["devices"][
                    inverter.serial_number
                ] = await self._process_inverter_object(inverter)
            except Exception as e:
                _LOGGER.error(
                    "Error processing inverter %s: %s", inverter.serial_number, e
                )
                # Keep device in data but mark it as having an error
                processed["devices"][inverter.serial_number] = {
                    "type": "unknown",
                    "model": "Unknown",
                    "error": str(e),
                    "sensors": {},
                    "batteries": {},
                }

        # Process parallel group data if available
        if hasattr(self.station, "parallel_groups") and self.station.parallel_groups:
            for group in self.station.parallel_groups:
                try:
                    # Refresh parallel group data to load energy statistics
                    await group.refresh()
                    _LOGGER.debug(
                        f"Refreshed parallel group {getattr(group, 'name', 'unknown')} data"
                    )

                    # Process the parallel group itself
                    processed["devices"][
                        f"parallel_group_{group.first_device_serial}"
                    ] = await self._process_parallel_group_object(group)

                    # Process GridBOSS/MID device if present in this parallel group
                    if hasattr(group, "mid_device") and group.mid_device:
                        try:
                            processed["devices"][
                                group.mid_device.serial_number
                            ] = await self._process_mid_device_object(group.mid_device)
                            _LOGGER.debug(
                                f"Processed GridBOSS/MID device {group.mid_device.serial_number}"
                            )
                        except Exception as e:
                            _LOGGER.error(
                                "Error processing MID device %s: %s",
                                group.mid_device.serial_number,
                                e,
                            )
                except Exception as e:
                    _LOGGER.error("Error processing parallel group: %s", e)

        # Process all batteries from station (pylxpweb 0.3.3+)
        if hasattr(self.station, "all_batteries"):
            _LOGGER.debug(
                f"Station has all_batteries attribute, checking battery count: "
                f"{len(self.station.all_batteries) if self.station.all_batteries else 0}"
            )
            for battery in self.station.all_batteries:
                try:
                    # Find parent inverter serial - try multiple property names
                    parent_serial = (
                        getattr(battery, "parent_serial", None)
                        or getattr(battery, "inverter_serial", None)
                        or getattr(battery, "inverter_sn", None)
                    )

                    # If still None, try to extract from battery_key (format: "serial_Battery_ID_XX")
                    if not parent_serial:
                        battery_key_raw = getattr(battery, "battery_key", "")
                        if battery_key_raw and BATTERY_KEY_SEPARATOR in battery_key_raw:
                            parent_serial = battery_key_raw.split(
                                BATTERY_KEY_SEPARATOR
                            )[0]
                        elif battery_key_raw and "_" in battery_key_raw:
                            # Try alternate format like "serial-XX" or "serial_XX"
                            parts = battery_key_raw.split("_")
                            if len(parts) > 0 and parts[0].isdigit():
                                parent_serial = parts[0]

                    _LOGGER.debug(
                        f"Processing battery {getattr(battery, 'battery_sn', 'unknown')}: "
                        f"parent_serial={parent_serial}, "
                        f"battery_key={getattr(battery, 'battery_key', 'N/A')}, "
                        f"battery_index={getattr(battery, 'battery_index', 'N/A')}"
                    )
                    if parent_serial and parent_serial in processed["devices"]:
                        battery_key = clean_battery_display_name(
                            getattr(
                                battery,
                                "battery_key",
                                f"BAT{battery.battery_index:03d}",
                            ),
                            parent_serial,
                        )
                        battery_sensors = self._extract_battery_from_object(battery)

                        # Add to parent inverter's batteries
                        if "batteries" not in processed["devices"][parent_serial]:
                            processed["devices"][parent_serial]["batteries"] = {}
                        processed["devices"][parent_serial]["batteries"][
                            battery_key
                        ] = battery_sensors

                        _LOGGER.debug(
                            f"Added battery {battery_key} for inverter {parent_serial} "
                            f"with {len(battery_sensors)} sensors"
                        )
                    else:
                        _LOGGER.warning(
                            f"Battery {getattr(battery, 'battery_sn', 'unknown')} parent_serial "
                            f"'{parent_serial}' not found in processed devices: {list(processed['devices'].keys())}"
                        )
                except Exception as e:
                    _LOGGER.error(
                        "Error processing battery %s: %s",
                        getattr(battery, "battery_sn", "unknown"),
                        e,
                    )
        else:
            _LOGGER.warning("Station does not have 'all_batteries' attribute")

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

    async def _process_inverter_object(self, inverter: BaseInverter) -> dict[str, Any]:
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
        # Get model and firmware from properties
        model = getattr(inverter, "model", "Unknown")
        firmware_version = getattr(inverter, "firmware_version", "1.0.0")

        _LOGGER.debug(
            f"Inverter {inverter.serial_number}: model={model}, firmware_version={firmware_version}"
        )

        processed: dict[str, Any] = {
            "serial": inverter.serial_number,
            "type": "inverter",
            "model": model,
            "firmware_version": firmware_version,
            "sensors": {},
            "binary_sensors": {},
            "batteries": {},
        }

        # Only process if inverter has data
        if not inverter.has_data:
            _LOGGER.debug(
                f"Inverter {inverter.serial_number} has no data, skipping sensor extraction"
            )
            return processed

        # Map inverter properties to sensor keys (pylxpweb 0.3.3+)
        # Use utility function to extract properties
        property_map = self._get_inverter_property_map()
        processed["sensors"] = _map_device_properties(
            inverter, property_map, logger_prefix=f"Inverter {inverter.serial_number}"
        )

        # Calculate net grid power (v2.2.7 legacy calculation)
        # grid_power = power_to_user - power_to_grid
        # (positive = importing, negative = exporting)
        if hasattr(inverter, "power_to_user") and hasattr(inverter, "power_to_grid"):
            power_to_user = _safe_numeric(inverter.power_to_user)  # Import
            power_to_grid = _safe_numeric(inverter.power_to_grid)  # Export
            processed["sensors"]["grid_power"] = power_to_user - power_to_grid
            _LOGGER.debug(
                f"Calculated grid_power for {inverter.serial_number}: "
                f"{power_to_user} - {power_to_grid} = {processed['sensors']['grid_power']} W "
                f"(positive=importing, negative=exporting)"
            )

        # Add legacy ac_voltage sensor (EPS output voltage - internal AC from inverter)
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
        # Note: battery_bank is a private attribute (_battery_bank) in pylxpweb
        battery_bank = getattr(inverter, "_battery_bank", None)
        _LOGGER.debug(
            f"Inverter {inverter.serial_number}: _battery_bank={battery_bank}, "
            f"has batteries={battery_bank.battery_count if battery_bank else 0}"
        )
        if battery_bank and battery_bank.battery_count > 0:
            try:
                battery_bank_sensors = self._extract_battery_bank_from_object(
                    battery_bank
                )
                # Add battery bank sensors to inverter sensors with battery_bank_ prefix
                processed["sensors"].update(battery_bank_sensors)
                _LOGGER.debug(
                    f"Added {len(battery_bank_sensors)} battery bank sensors for inverter {inverter.serial_number}"
                )
            except Exception as e:
                _LOGGER.warning(
                    f"Error extracting battery bank data for inverter {inverter.serial_number}: {e}"
                )
        else:
            _LOGGER.debug(
                f"Inverter {inverter.serial_number}: battery_bank not available or empty"
            )

        _LOGGER.debug(
            f"Processed inverter {inverter.serial_number}: {len(processed['sensors'])} sensors, "
            f"{len(processed['binary_sensors'])} binary sensors"
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
            # Note: grid_power is calculated from power_to_user - power_to_grid (see below)
            "consumption_power": "consumption_power",
            "inverter_power": "ac_power",  # AC output power (was "inverter_power", mapped to legacy sensor)
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
            "inverter_temperature": "internal_temperature",  # Map to legacy sensor name
            "radiator1_temperature": "radiator1_temperature",
            "radiator2_temperature": "radiator2_temperature",
            # Battery sensors
            "battery_soc": "state_of_charge",
            # Energy sensors - Generation
            "total_energy_today": "yield",
            "total_energy_lifetime": "yield_lifetime",
            # Energy sensors - Grid Import/Export (pylxpweb 0.3.3+)
            "energy_today_import": "grid_import",
            "energy_today_export": "grid_export",
            "energy_lifetime_import": "grid_import_lifetime",
            "energy_lifetime_export": "grid_export_lifetime",
            # Energy sensors - Consumption (pylxpweb 0.3.3+)
            "energy_today_usage": "consumption",
            "energy_lifetime_usage": "consumption_lifetime",
            # Energy sensors - Battery Charging/Discharging (pylxpweb 0.3.3+)
            "energy_today_charging": "battery_charge",
            "energy_today_discharging": "battery_discharge",
            "energy_lifetime_charging": "battery_charge_lifetime",
            "energy_lifetime_discharging": "battery_discharge_lifetime",
            # Current sensors
            "max_charge_current": "max_charge_current",
            "max_discharge_current": "max_discharge_current",
            # Grid power sensors (instantaneous)
            "power_to_user": "grid_import_power",
            "power_to_grid": "grid_export_power",
            # Other sensors
            "power_rating": "power_rating",
            "power_factor": "power_factor",
            "status_text": "status_text",
            "status": "status_code",
            "has_data": "has_data",  # Runtime data availability indicator
        }

    def _extract_battery_from_object(self, battery: Battery) -> dict[str, Any]:
        """Extract sensor data from Battery object using properties.

        pylxpweb 0.3.3+ provides Battery objects with properly scaled properties.
        All values are ready to use - no additional scaling needed.

        Args:
            battery: Battery object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        # Use utility function to extract properties
        property_map = self._get_battery_property_map()
        sensors = _map_device_properties(
            battery,
            property_map,
            logger_prefix=f"Battery {getattr(battery, 'battery_sn', 'unknown')}",
        )

        # Calculate derived sensors
        self._calculate_battery_derived_sensors(sensors)

        return sensors

    @staticmethod
    def _get_battery_property_map() -> dict[str, str]:
        """Get battery property mapping dictionary.

        Maps all 39 available Battery properties to sensor keys.

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
            "max_battery_charge": "battery_max_discharge_current",
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
        # Calculate cell voltage difference if min/max available
        if (
            "battery_cell_voltage_max" in sensors
            and "battery_cell_voltage_min" in sensors
        ):
            sensors["battery_cell_voltage_diff"] = (
                sensors["battery_cell_voltage_max"]
                - sensors["battery_cell_voltage_min"]
            )

        # Calculate capacity percentage if remaining and full capacity available
        if (
            "battery_remaining_capacity" in sensors
            and "battery_full_capacity" in sensors
            and sensors["battery_full_capacity"] > 0
        ):
            sensors["battery_capacity_percentage"] = (
                sensors["battery_remaining_capacity"]
                / sensors["battery_full_capacity"]
                * 100
            )

    def _extract_battery_bank_from_object(self, battery_bank: Any) -> dict[str, Any]:
        """Extract sensor data from BatteryBank object using properties.

        Args:
            battery_bank: BatteryBank object from pylxpweb

        Returns:
            Dictionary of sensor_key -> value mappings
        """
        # Use utility function to extract properties
        property_map = self._get_battery_bank_property_map()
        sensors = _map_device_properties(
            battery_bank,
            property_map,
            logger_prefix=f"BatteryBank {getattr(battery_bank, 'inverter_serial', 'unknown')}",
        )

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

    @staticmethod
    def _filter_unused_smart_port_sensors(
        sensors: dict[str, Any], mid_device: Any
    ) -> None:
        """Filter out sensors for unused Smart Ports from MID device.

        Modifies the sensors dictionary in place, removing sensors for Smart Ports
        that are not in use (status = 0).

        Args:
            sensors: Dictionary of sensor values to modify
            mid_device: MID device object to read port statuses from
        """
        # Get smart port statuses from MID device properties
        smart_port_statuses = {}
        for port in range(1, 5):
            status_property = f"smart_port{port}_status"
            if hasattr(mid_device, status_property):
                status_value = getattr(mid_device, status_property)
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
        for sensor_key in sensors_to_remove:
            sensors.pop(sensor_key, None)

    async def _process_parallel_group_object(self, group: Any) -> dict[str, Any]:
        """Process parallel group data from group object using properties.

        pylxpweb 0.3.3+ provides ParallelGroup objects with properly scaled properties.
        All energy values are ready to use - no additional scaling needed.

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
            "model": f"Parallel Group {group.name}"
            if hasattr(group, "name") and group.name
            else "Parallel Group",
            "sensors": {},
            "binary_sensors": {},
        }

        # Use utility function to extract properties
        property_map = self._get_parallel_group_property_map()
        processed["sensors"] = _map_device_properties(
            group,
            property_map,
            logger_prefix=f"Parallel Group {getattr(group, 'name', 'unknown')}",
        )

        _LOGGER.debug(
            f"Processed parallel group complete: {len(processed['sensors'])} sensors"
        )

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

        pylxpweb 0.3.3+ provides MIDDevice objects with properly scaled properties.
        All values are ready to use - no additional scaling needed.

        Args:
            mid_device: MIDDevice object from pylxpweb

        Returns:
            Processed device data dictionary with sensors and binary_sensors
        """
        # Extract model and firmware from the MID device properties
        model = getattr(mid_device, "model", "GridBOSS")
        firmware_version = getattr(mid_device, "firmware_version", "1.0.0")

        processed: dict[str, Any] = {
            "serial": mid_device.serial_number,
            "type": "gridboss",
            "model": model,
            "firmware_version": firmware_version,
            "sensors": {},
            "binary_sensors": {},
        }

        _LOGGER.debug(
            f"Processing MID device {mid_device.serial_number}: model={model}, "
            f"has_data={getattr(mid_device, 'has_data', False)}"
        )

        # Extract sensor data from MIDDevice properties (pylxpweb 0.3.3+ API)
        # All properties are properly scaled by the library
        if mid_device.has_data:
            # Use utility function to extract properties
            property_map = self._get_mid_device_property_map()
            processed["sensors"] = _map_device_properties(
                mid_device,
                property_map,
                logger_prefix=f"MID device {mid_device.serial_number}",
            )

            # Filter out sensors for unused Smart Ports
            self._filter_unused_smart_port_sensors(processed["sensors"], mid_device)

            # Calculate aggregate sensors from L1/L2 values
            self._calculate_gridboss_aggregates(processed["sensors"])
        else:
            _LOGGER.warning(f"MID device {mid_device.serial_number} has no data")

        _LOGGER.debug(
            f"Processed MID device {mid_device.serial_number} complete: "
            f"{len(processed['sensors'])} sensors, "
            f"{len(processed['binary_sensors'])} binary sensors"
        )

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
            "smart_port1_status": "smart_port1_status",
            "smart_port2_status": "smart_port2_status",
            "smart_port3_status": "smart_port3_status",
            "smart_port4_status": "smart_port4_status",
        }

    @staticmethod
    def _calculate_gridboss_aggregates(sensors: dict[str, Any]) -> None:
        """Calculate aggregate sensor values from individual L1/L2 values.

        Modifies the sensors dictionary in place to add calculated aggregate values.
        These are true calculated/derived values (sums), not scaling factors.

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

    def get_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for a specific serial number."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        # Special handling for parallel group device naming
        model = device_data.get("model", "Unknown")
        device_type = device_data.get("type", "unknown")

        # Use just the model name for parallel groups, include serial for normal devices
        device_name = model if device_type == "parallel_group" else f"{model} {serial}"

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

        # Return as DeviceInfo TypedDict
        return cast(DeviceInfo, device_info)

    def _get_parallel_group_for_device(self, device_serial: str) -> str | None:
        """Get the parallel group serial that contains this device."""
        if not self.data or "devices" not in self.data:
            return None

        # Check if station has parallel group info
        if self.station and hasattr(self.station, "parallel_groups"):
            for group in self.station.parallel_groups:
                if hasattr(group, "inverters"):
                    for inverter in group.inverters:
                        if inverter.serial_number == device_serial:
                            return f"parallel_group_{group.first_device_serial}"

        # Fallback: if a parallel group exists, assume all devices are part of it
        for serial, device_data in self.data["devices"].items():
            if device_data.get("type") == "parallel_group":
                return str(serial)

        return None

    def get_battery_device_info(
        self, serial: str, battery_key: str
    ) -> DeviceInfo | None:
        """Get device information for a specific battery."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data or battery_key not in device_data.get("batteries", {}):
            return None

        # Get battery-specific data for firmware version and model
        battery_data = device_data.get("batteries", {}).get(battery_key, {})

        # Battery data structure: battery_data is the sensors dict directly (no nested "sensors")
        # because _extract_battery_from_object returns {"sensors": {...}}
        # but we store just the inner dict
        battery_firmware = battery_data.get("battery_firmware_version", "1.0.0")

        # Get BMS model for better device identification
        # Try bms_model first, then battery_model, then fall back to generic name
        bms_model = battery_data.get("battery_bms_model")
        battery_model_name = battery_data.get("battery_model")
        battery_type_text = battery_data.get("battery_type_text")

        # Determine best model name (prefer BMS model as most descriptive)
        model = bms_model or battery_model_name or battery_type_text or "Battery Module"

        _LOGGER.debug(
            f"Battery {battery_key} model selection: bms_model={bms_model}, "
            f"battery_model={battery_model_name}, type_text={battery_type_text}, final_model={model}"
        )

        # Get inverter model for naming
        inverter_model = device_data.get("model", "Unknown")

        # Use cleaned battery name for display
        clean_battery_name = clean_battery_display_name(battery_key, serial)

        return {
            "identifiers": {(DOMAIN, f"{serial}_{battery_key}")},
            "name": f"{inverter_model} Battery {clean_battery_name}",
            "manufacturer": "EG4 Electronics",
            "model": model,
            "sw_version": battery_firmware,
            "via_device": (
                DOMAIN,
                f"{serial}_battery_bank",
            ),  # Link battery to battery bank
        }

    def get_battery_bank_device_info(self, serial: str) -> DeviceInfo | None:
        """Get device information for battery bank (aggregate of all batteries)."""
        if not self.data or "devices" not in self.data:
            return None

        device_data = self.data["devices"].get(serial)
        if not device_data:
            return None

        # Get battery bank data from device sensors
        sensors = device_data.get("sensors", {})
        battery_count = sensors.get("battery_bank_count", 0)

        # Only create battery bank device if there are batteries
        if battery_count == 0:
            return None

        # Get inverter model for naming
        model = device_data.get("model", "Unknown")

        return {
            "identifiers": {(DOMAIN, f"{serial}_battery_bank")},
            "name": f"Battery Bank {serial}",
            "manufacturer": "EG4 Electronics",
            "model": f"{model} Battery Bank",
            "via_device": (DOMAIN, serial),  # Link battery bank to its parent inverter
        }

    def get_station_device_info(self) -> DeviceInfo | None:
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

    def get_inverter_object(self, serial: str) -> BaseInverter | None:
        """Get inverter device object by serial number."""
        if not self.station:
            return None

        for inverter in self.station.all_inverters:
            if inverter.serial_number == serial:
                return inverter

        return None

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

    # PRESERVED PARAMETER REFRESH METHODS

    async def refresh_all_device_parameters(self) -> None:
        """Refresh parameters for all inverter devices when any parameter changes.

        This method is called after a user changes any device parameter (via number,
        select, or switch entities) to ensure all inverters in the system have
        synchronized settings. This is important for multi-inverter parallel systems
        where settings should be consistent.

        The method performs concurrent parameter refreshes for all inverters using
        asyncio.gather() for optimal performance.

        Raises:
            Exception: Logged but does not propagate to avoid disrupting normal operation.

        Note:
            Individual device refresh failures are logged but don't prevent other
            devices from being refreshed. Success count is logged for monitoring.
        """
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
        """Refresh parameters for a specific device using device object.

        This method fetches fresh parameter data from the device and updates
        the coordinator's parameter cache. Parameters include working modes,
        SOC limits, charge/discharge power settings, and other configurable values.

        The method uses the device object's refresh method with the include_parameters
        flag to fetch parameter data. The pylxpweb library caches parameters internally
        to minimize API calls.

        Args:
            serial: The inverter serial number to refresh parameters for.

        Raises:
            Exception: Propagated to caller for error handling.
            AttributeError: If the inverter object doesn't support parameters.
            LuxpowerAPIError: If the API request fails.

        Note:
            This method should only be called when parameter values are expected
            to have changed (e.g., after a user modifies settings via the UI).
            For routine data updates, parameters are cached and reused.
        """
        try:
            # Get inverter object for this serial
            inverter = self.get_inverter_object(serial)
            if not inverter:
                _LOGGER.warning("Cannot find inverter object for serial %s", serial)
                return

            # Use device object's refresh method with parameter fetching
            # The library now caches parameters internally
            await inverter.refresh(include_parameters=True)

            # Extract parameters from inverter object properties (pylxpweb 0.3.3+)
            # Parameters are exposed as properties on the inverter object
            if hasattr(inverter, "parameters") and inverter.parameters:
                # Initialize parameters dict if needed
                if not self.data:
                    return

                if "parameters" not in self.data:
                    self.data["parameters"] = {}

                # Store parameters - inverter.parameters should be a dict
                self.data["parameters"][serial] = inverter.parameters

                # Debug: Log some key working mode parameters
                working_mode_keys = [
                    "FUNC_FORCED_CHG_EN",
                    "FUNC_AC_CHARGE",
                    "FUNC_FORCED_DISCHG_EN",
                    "FUNC_GRID_PEAK_SHAVING",
                    "FUNC_BATTERY_BACKUP_CTRL",
                ]
                working_mode_values = {
                    k: inverter.parameters.get(k, "NOT_FOUND")
                    for k in working_mode_keys
                }
                _LOGGER.debug(
                    f"Refreshed parameters for device {serial}: "
                    f"{len(inverter.parameters)} parameters loaded. "
                    f"Working modes: {working_mode_values}"
                )
            else:
                _LOGGER.warning(
                    f"Inverter {serial} has no parameters attribute or empty parameters"
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

    def _should_sync_dst(self) -> bool:
        """Check if DST sync is due.

        Performs DST sync one minute before the top of each hour to ensure
        time synchronization happens at the optimal moment for DST transitions.
        This allows the system to catch DST changes right before they take effect.
        """
        now = dt_util.utcnow()

        # Check if we're within 1 minute before the top of the hour
        minutes_to_hour = 60 - now.minute
        is_near_hour = minutes_to_hour <= 1

        if not is_near_hour:
            return False

        # If we haven't synced yet, sync now
        if self._last_dst_sync is None:
            return True

        # Check if we've already synced in the last hour
        # This prevents multiple syncs within the same hour's 1-minute window
        time_since_sync = now - self._last_dst_sync
        return bool(time_since_sync >= self._dst_sync_interval)

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

    def _remove_task_from_set(self, task: asyncio.Task[Any]) -> None:
        """Remove completed task from background tasks set.

        This callback is attached to background tasks to automatically clean up
        the task tracking set when tasks complete.

        Args:
            task: The completed asyncio task.
        """
        self._background_tasks.discard(task)

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        """Log exception from completed task if not cancelled.

        This callback is attached to background tasks to log any exceptions
        that occurred during task execution for debugging purposes.

        Args:
            task: The completed asyncio task.
        """
        if not task.cancelled():
            exception = task.exception()
            if exception:
                _LOGGER.error(
                    "Background task failed with exception: %s",
                    exception,
                    exc_info=exception,
                )
