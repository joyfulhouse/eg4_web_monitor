"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.components.number import NumberEntity, NumberMode
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.number import NumberEntity, NumberMode
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import EG4ConfigEntry
from .coordinator import EG4DataUpdateCoordinator
from .utils import read_device_parameters_ranges, process_parameter_responses

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor number entities from a config entry."""
    coordinator = config_entry.runtime_data

    entities: List[NumberEntity] = []

    # Create number entities for each inverter device (not GridBOSS or parallel groups)
    for serial, device_data in coordinator.data.get("devices", {}).items():
        device_type = device_data.get("type")
        if device_type == "inverter":
            # Get device model for compatibility check
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")
            model_lower = model.lower()

            _LOGGER.info(
                "Evaluating number entity compatibility for device %s: "
                "model='%s' (original), model_lower='%s'",
                serial,
                model,
                model_lower,
            )

            # Check if device model is known to support number entities
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                # Add number entities for all supported models
                entities.append(SystemChargeSOCLimitNumber(coordinator, serial))
                entities.append(ACChargePowerNumber(coordinator, serial))
                entities.append(PVChargePowerNumber(coordinator, serial))
                entities.append(GridPeakShavingPowerNumber(coordinator, serial))
                # Add new SOC cutoff limit entities
                entities.append(ACChargeSOCLimitNumber(coordinator, serial))
                entities.append(OnGridSOCCutoffNumber(coordinator, serial))
                entities.append(OffGridSOCCutoffNumber(coordinator, serial))
                # Add battery charge/discharge current control entities
                entities.append(BatteryChargeCurrentNumber(coordinator, serial))
                entities.append(BatteryDischargeCurrentNumber(coordinator, serial))
                _LOGGER.info(
                    "✅ Added number entities for compatible device %s (%s)",
                    serial,
                    model,
                )
            else:
                _LOGGER.warning(
                    "❌ Skipping number entities for device %s (%s) - "
                    "model not in supported list %s",
                    serial,
                    model,
                    supported_models,
                )

    if entities:
        _LOGGER.info("Added %d number entities", len(entities))
        async_add_entities(entities, update_before_add=True)
    else:
        _LOGGER.info("No number entities created")


class SystemChargeSOCLimitNumber(CoordinatorEntity, NumberEntity):
    """Number entity for System Charge SOC Limit control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration - explicit entity_id to override registry caching
        # Clean model name for entity ID - following same pattern as sensors
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "System Charge SOC Limit"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_system_charge_soc_limit"

        _LOGGER.debug(
            "Creating SOC Limit entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for SOC limit (10-101%) - integer only
        self._attr_native_min_value = 10
        self._attr_native_max_value = 101
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging"

        # Set precision to 0 decimal places (integers only)
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value - will be loaded from device
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created System Charge SOC Limit number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[int]:
        """Return the current SOC limit value as integer."""
        # First check if we have fresh data from coordinator's parameter cache
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            # Update our cached value and return it
            self._current_value = coordinator_value
            return int(round(coordinator_value))

        # Fall back to cached value if available
        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))

        # Return None to indicate unknown value - will be loaded asynchronously
        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "HOLD_SYSTEM_CHARGE_SOC_LIMIT" in parameter_data:
                    raw_value = parameter_data["HOLD_SYSTEM_CHARGE_SOC_LIMIT"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 10 <= value <= 101:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the SOC limit value."""
        try:
            # Convert to integer and validate range - must be integer between 10-101
            int_value = int(round(value))
            if int_value < 10 or int_value > 101:
                raise ValueError(
                    f"SOC limit must be an integer between 10-101%, got {int_value}"
                )

            # Validate that the input is actually an integer (no decimals)
            if abs(value - int_value) > 0.01:  # Allow small floating point tolerance
                raise ValueError(f"SOC limit must be an integer value, got {value}")

            _LOGGER.info(
                "Setting System Charge SOC Limit for %s to %d%%", self.serial, int_value
            )

            # Use the API client to write the parameter
            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_SYSTEM_CHARGE_SOC_LIMIT",
                value_text=str(int_value),
            )

            _LOGGER.debug("Parameter write response for %s: %s", self.serial, response)

            # Check if the write was successful
            if response.get("success", False):
                # Update the stored value
                self._current_value = value
                self.async_write_ha_state()

                # Trigger parameter refresh for all inverters when any parameter changes
                _LOGGER.info(
                    "Parameter changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                # Create background task to refresh all device parameters and then update
                # all SOC entities
                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set System Charge SOC Limit for %s to %d%%",
                    self.serial,
                    int_value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(f"Failed to set SOC limit: {error_msg}")

        except Exception as e:
            _LOGGER.error(
                "Failed to set System Charge SOC Limit for %s: %s", self.serial, e
            )
            raise HomeAssistantError(f"Failed to set SOC limit: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all SOC limit entities."""
        try:
            # First refresh all device parameters
            await self.coordinator.refresh_all_device_parameters()

            # Get all SOC limit entities from the platform
            platform = self.platform
            if platform is not None:
                # Find all SOC limit entities and trigger their updates
                soc_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, SystemChargeSOCLimitNumber)
                ]

                _LOGGER.info(
                    "Updating %d SOC limit entities after parameter refresh",
                    len(soc_entities),
                )

                # Update all SOC limit entities
                update_tasks = []
                for entity in soc_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                # Execute all entity updates concurrently
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # Trigger coordinator refresh for general data
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        # Refresh the SOC limit value from the device periodically
        try:
            current_value = await self._read_current_soc_limit()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "SOC limit for %s updated from %s%% to %s%%",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error("Failed to update SOC limit for %s: %s", self.serial, e)

        await self.coordinator.async_request_refresh()

    async def _read_current_soc_limit(self) -> Optional[float]:
        """Read the current SOC limit from the device by reading all register ranges."""
        try:
            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            # Process responses and look for HOLD_SYSTEM_CHARGE_SOC_LIMIT in any range
            successful_responses = 0
            total_responses = 0

            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                total_responses += 1
                if response and response.get("success", False):
                    successful_responses += 1
                    _LOGGER.debug(
                        "Parameter read response for %s (reg %d): success=True",
                        self.serial,
                        start_register,
                    )

                    # Check for HOLD_SYSTEM_CHARGE_SOC_LIMIT in this response
                    soc_limit = self._extract_system_charge_soc_limit(
                        response, start_register
                    )
                    if soc_limit is not None:
                        return soc_limit

            # Provide more specific error messaging based on response status
            if successful_responses == 0:
                _LOGGER.warning(
                    "No successful parameter responses received for %s (%d/%d failed). "
                    "API communication issues detected. HOLD_SYSTEM_CHARGE_SOC_LIMIT is typically "
                    "available in register 127-254 range. Will retry on next update cycle.",
                    self.serial,
                    total_responses,
                    total_responses,
                )
            else:
                _LOGGER.info(
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT parameter not found for %s "
                    "in %d successful parameter responses. "
                    "This may be a device model compatibility issue.",
                    self.serial,
                    successful_responses,
                )

        except Exception as e:
            _LOGGER.warning(
                "Failed to read SOC limit for %s due to: %s. "
                "This is typically caused by temporary API issues. Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_system_charge_soc_limit(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[int]:
        """Extract HOLD_SYSTEM_CHARGE_SOC_LIMIT from parameter response as integer."""
        if (
            "HOLD_SYSTEM_CHARGE_SOC_LIMIT" in response
            and response["HOLD_SYSTEM_CHARGE_SOC_LIMIT"] is not None
        ):
            try:
                raw_value = float(response["HOLD_SYSTEM_CHARGE_SOC_LIMIT"])
                int_value = int(round(raw_value))

                if 10 <= int_value <= 101:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_SYSTEM_CHARGE_SOC_LIMIT for %s (reg %d): %d%%",
                        self.serial,
                        start_register,
                        int_value,
                    )
                    return int_value

                _LOGGER.warning(
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT for %s (reg %d) out of range: %d%%",
                    self.serial,
                    start_register,
                    int_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_SYSTEM_CHARGE_SOC_LIMIT for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Read the current SOC limit from the device
        try:
            current_value = await self._read_current_soc_limit()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded SOC limit for %s: %s%%", self.serial, current_value
                )
            else:
                # Leave current_value as None to show as unavailable
                _LOGGER.debug(
                    "Could not read SOC limit for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error("Failed to initialize SOC limit for %s: %s", self.serial, e)
            # Leave current_value as None to show as unavailable


class ACChargePowerNumber(CoordinatorEntity, NumberEntity):
    """Number entity for AC Charge Power control.

    Note: Several assignments have type: ignore[assignment] due to mypy
    control flow false positives when assigning float to Optional[float].
    Mypy incorrectly narrows the type to None in some branches.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "AC Charge Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_ac_charge_power"

        _LOGGER.debug(
            "Creating AC Charge Power entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for AC Charge Power (0-15 kW)
        # Supports decimal values (0.1 kW step) to match EG4 web interface
        self._attr_native_min_value = 0
        self._attr_native_max_value = 15
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created AC Charge Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[float]:
        """Return the current AC charge power value."""
        # First check if we have fresh data from coordinator's parameter cache
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            # Update our cached value and return it
            self._current_value = coordinator_value
            return round(coordinator_value, 1)

        # Fall back to cached value if available
        if hasattr(self, "_current_value") and self._current_value is not None:
            return round(self._current_value, 1)

        # Return None to indicate unknown value
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge power value."""
        try:
            # Validate range (0.0-15.0 kW)
            if value < 0.0 or value > 15.0:
                raise ValueError(
                    f"AC charge power must be between 0.0-15.0 kW, got {value}"
                )

            _LOGGER.info(
                "Setting AC Charge Power for %s to %.1f kW", self.serial, value
            )

            # Use the API client to write the parameter
            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_AC_CHARGE_POWER_CMD",
                value_text=str(value),
            )

            _LOGGER.debug(
                "AC Charge Power write response for %s: %s", self.serial, response
            )

            # Check if the write was successful
            if response.get("success", False):
                # Update the stored value
                self._current_value = value
                self.async_write_ha_state()

                # Trigger parameter refresh for all inverters
                _LOGGER.info(
                    "AC Charge Power changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set AC Charge Power for %s to %.1f kW",
                    self.serial,
                    value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(f"Failed to set AC charge power: {error_msg}")

        except Exception as e:
            _LOGGER.error("Failed to set AC Charge Power for %s: %s", self.serial, e)
            raise HomeAssistantError(f"Failed to set AC charge power: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all charge power entities."""
        try:
            # First refresh all device parameters
            await self.coordinator.refresh_all_device_parameters()

            # Get all charge power entities from the platform
            platform = self.platform
            if platform is not None:
                # Find all charge power entities and trigger their updates
                charge_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, (ACChargePowerNumber, PVChargePowerNumber))
                ]

                _LOGGER.info(
                    "Updating %d charge power entities after parameter refresh",
                    len(charge_entities),
                )

                # Update all charge power entities
                update_tasks = []
                for entity in charge_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                # Execute all entity updates concurrently
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # Trigger coordinator refresh for general data
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_ac_charge_power()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "AC charge power for %s updated from %s kW to %s kW",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error("Failed to update AC charge power for %s: %s", self.serial, e)

        await self.coordinator.async_request_refresh()

    async def _read_current_ac_charge_power(self) -> Optional[float]:
        """Read the current AC charge power from the device."""
        try:
            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            # Process responses and look for HOLD_AC_CHARGE_POWER_CMD
            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    # Check for HOLD_AC_CHARGE_POWER_CMD in this response
                    ac_charge_power = self._extract_ac_charge_power(
                        response, start_register
                    )
                    if ac_charge_power is not None:
                        return ac_charge_power

        except Exception as e:
            _LOGGER.warning(
                "Failed to read AC charge power for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_ac_charge_power(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[float]:
        """Extract HOLD_AC_CHARGE_POWER_CMD from parameter response."""
        if (
            "HOLD_AC_CHARGE_POWER_CMD" in response
            and response["HOLD_AC_CHARGE_POWER_CMD"] is not None
        ):
            try:
                raw_value = float(response["HOLD_AC_CHARGE_POWER_CMD"])

                if 0.0 <= raw_value <= 15.0:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_AC_CHARGE_POWER_CMD for %s (reg %d): %.1f kW",
                        self.serial,
                        start_register,
                        raw_value,
                    )
                    return raw_value

                _LOGGER.warning(
                    "HOLD_AC_CHARGE_POWER_CMD for %s (reg %d) out of range: %.1f kW",
                    self.serial,
                    start_register,
                    raw_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_AC_CHARGE_POWER_CMD for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "HOLD_AC_CHARGE_POWER_CMD" in parameter_data:
                    raw_value = parameter_data["HOLD_AC_CHARGE_POWER_CMD"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 0.0 <= value <= 15.0:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Read the current AC charge power from the device
        try:
            current_value = await self._read_current_ac_charge_power()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded AC charge power for %s: %s kW", self.serial, current_value
                )
            else:
                # Leave current_value as None to show as unavailable
                _LOGGER.debug(
                    "Could not read AC charge power for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize AC charge power for %s: %s", self.serial, e
            )
            # Leave current_value as None to show as unavailable


class PVChargePowerNumber(CoordinatorEntity, NumberEntity):
    """Number entity for PV Charge Power control.

    Note: Several assignments have type: ignore[assignment] due to mypy
    control flow false positives when assigning float to Optional[float].
    Mypy incorrectly narrows the type to None in some branches.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "PV Charge Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_pv_charge_power"

        _LOGGER.debug(
            "Creating PV Charge Power entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for PV Charge Power (0-15 kW)
        self._attr_native_min_value = 0
        self._attr_native_max_value = 15
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created PV Charge Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[int]:
        """Return the current PV charge power value as integer."""
        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV charge power value."""
        try:
            # Convert to integer and validate range
            int_value = int(round(value))
            if int_value < 0 or int_value > 15:
                raise ValueError(
                    f"PV charge power must be between 0-15 kW, got {int_value}"
                )

            # Validate that the input is actually an integer
            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"PV charge power must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting PV Charge Power for %s to %d kW", self.serial, int_value
            )

            # Use the API client to write the parameter
            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_FORCED_CHG_POWER_CMD",
                value_text=str(int_value),
            )

            _LOGGER.debug(
                "PV Charge Power write response for %s: %s", self.serial, response
            )

            # Check if the write was successful
            if response.get("success", False):
                # Update the stored value
                self._current_value = value
                self.async_write_ha_state()

                # Trigger parameter refresh for all inverters
                _LOGGER.info(
                    "PV Charge Power changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set PV Charge Power for %s to %d kW",
                    self.serial,
                    int_value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(f"Failed to set PV charge power: {error_msg}")

        except Exception as e:
            _LOGGER.error("Failed to set PV Charge Power for %s: %s", self.serial, e)
            raise HomeAssistantError(f"Failed to set PV charge power: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all charge power entities."""
        try:
            # First refresh all device parameters
            await self.coordinator.refresh_all_device_parameters()

            # Get all charge power entities from the platform
            platform = self.platform
            if platform is not None:
                # Find all charge power entities and trigger their updates
                charge_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, (ACChargePowerNumber, PVChargePowerNumber))
                ]

                _LOGGER.info(
                    "Updating %d charge power entities after parameter refresh",
                    len(charge_entities),
                )

                # Update all charge power entities
                update_tasks = []
                for entity in charge_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                # Execute all entity updates concurrently
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # Trigger coordinator refresh for general data
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_pv_charge_power()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "PV charge power for %s updated from %s kW to %s kW",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error("Failed to update PV charge power for %s: %s", self.serial, e)

        await self.coordinator.async_request_refresh()

    async def _read_current_pv_charge_power(self) -> Optional[float]:
        """Read the current PV charge power from the device."""
        try:
            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            # Process responses and look for HOLD_FORCED_CHG_POWER_CMD
            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    # Check for HOLD_FORCED_CHG_POWER_CMD in this response
                    pv_charge_power = self._extract_pv_charge_power(
                        response, start_register
                    )
                    if pv_charge_power is not None:
                        return pv_charge_power

        except Exception as e:
            _LOGGER.warning(
                "Failed to read PV charge power for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_pv_charge_power(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[int]:
        """Extract HOLD_FORCED_CHG_POWER_CMD from parameter response."""
        if (
            "HOLD_FORCED_CHG_POWER_CMD" in response
            and response["HOLD_FORCED_CHG_POWER_CMD"] is not None
        ):
            try:
                raw_value = float(response["HOLD_FORCED_CHG_POWER_CMD"])
                int_value = int(round(raw_value))

                if 0 <= int_value <= 15:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_FORCED_CHG_POWER_CMD for %s (reg %d): %d kW",
                        self.serial,
                        start_register,
                        int_value,
                    )
                    return int_value

                _LOGGER.warning(
                    "HOLD_FORCED_CHG_POWER_CMD for %s (reg %d) out of range: %d kW",
                    self.serial,
                    start_register,
                    int_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_FORCED_CHG_POWER_CMD for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Read the current PV charge power from the device
        try:
            current_value = await self._read_current_pv_charge_power()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded PV charge power for %s: %s kW", self.serial, current_value
                )
            else:
                # Leave current_value as None to show as unavailable
                _LOGGER.debug(
                    "Could not read PV charge power for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize PV charge power for %s: %s", self.serial, e
            )
            # Leave current_value as None to show as unavailable


class GridPeakShavingPowerNumber(CoordinatorEntity, NumberEntity):
    """Number entity for Grid Peak Shaving Power control.

    Note: Several assignments have type: ignore[assignment] due to mypy
    control flow false positives when assigning float to Optional[float].
    Mypy incorrectly narrows the type to None in some branches.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Grid Peak Shaving Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_grid_peak_shaving_power"

        _LOGGER.debug(
            "Creating Grid Peak Shaving Power entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for Grid Peak Shaving Power (0.0-25.5 kW)
        # Based on curl example with valueText range
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 25.5
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_native_precision = 1
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created Grid Peak Shaving Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[float]:
        """Return the current grid peak shaving power value."""
        # First check if we have fresh data from coordinator's parameter cache
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            # Update our cached value and return it
            self._current_value = coordinator_value
            return round(coordinator_value, 1)

        # Fall back to cached value if available
        if hasattr(self, "_current_value") and self._current_value is not None:
            return round(self._current_value, 1)

        # Return None to indicate unknown value
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid peak shaving power value."""
        try:
            # Validate range (0.0-25.5 kW)
            if value < 0.0 or value > 25.5:
                raise ValueError(
                    f"Grid peak shaving power must be between 0.0-25.5 kW, got {value}"
                )

            _LOGGER.info(
                "Setting Grid Peak Shaving Power for %s to %.1f kW", self.serial, value
            )

            # Use the API client to write the parameter
            # The parameter name is model-specific: _12K_HOLD_GRID_PEAK_SHAVING_POWER
            # We'll use a generic name and let the API handle the model-specific mapping
            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="_12K_HOLD_GRID_PEAK_SHAVING_POWER",
                value_text=str(value),
            )

            _LOGGER.debug(
                "Grid Peak Shaving Power write response for %s: %s",
                self.serial,
                response,
            )

            # Check if the write was successful
            if response.get("success", False):
                # Update the stored value
                self._current_value = value
                self.async_write_ha_state()

                # Trigger parameter refresh for all inverters
                _LOGGER.info(
                    "Grid Peak Shaving Power changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set Grid Peak Shaving Power for %s to %.1f kW",
                    self.serial,
                    value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(
                    f"Failed to set grid peak shaving power: {error_msg}"
                )

        except Exception as e:
            _LOGGER.error(
                "Failed to set Grid Peak Shaving Power for %s: %s", self.serial, e
            )
            raise HomeAssistantError(
                f"Failed to set grid peak shaving power: {e}"
            ) from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all peak shaving power entities."""
        try:
            # First refresh all device parameters
            await self.coordinator.refresh_all_device_parameters()

            # Get all peak shaving power entities from the platform
            platform = self.platform
            if platform is not None:
                # Find all peak shaving power entities and trigger their updates
                peak_shaving_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, GridPeakShavingPowerNumber)
                ]

                _LOGGER.info(
                    "Updating %d grid peak shaving power entities after parameter refresh",
                    len(peak_shaving_entities),
                )

                # Update all peak shaving power entities
                update_tasks = []
                for entity in peak_shaving_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                # Execute all entity updates concurrently
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # Trigger coordinator refresh for general data
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_grid_peak_shaving_power()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "Grid peak shaving power for %s updated from %s kW to %s kW",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error(
                "Failed to update grid peak shaving power for %s: %s", self.serial, e
            )

        await self.coordinator.async_request_refresh()

    async def _read_current_grid_peak_shaving_power(self) -> Optional[float]:
        """Read the current grid peak shaving power from the device."""
        try:
            # Use shared utility function to read all parameter ranges
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            # Process responses and look for _12K_HOLD_GRID_PEAK_SHAVING_POWER
            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    # Check for _12K_HOLD_GRID_PEAK_SHAVING_POWER in this response
                    peak_shaving_power = self._extract_grid_peak_shaving_power(
                        response, start_register
                    )
                    if peak_shaving_power is not None:
                        return peak_shaving_power

        except Exception as e:
            _LOGGER.warning(
                "Failed to read grid peak shaving power for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_grid_peak_shaving_power(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[float]:
        """Extract _12K_HOLD_GRID_PEAK_SHAVING_POWER from parameter response."""
        if (
            "_12K_HOLD_GRID_PEAK_SHAVING_POWER" in response
            and response["_12K_HOLD_GRID_PEAK_SHAVING_POWER"] is not None
        ):
            try:
                raw_value = float(response["_12K_HOLD_GRID_PEAK_SHAVING_POWER"])

                if 0.0 <= raw_value <= 25.5:  # Validate range
                    _LOGGER.info(
                        "Found _12K_HOLD_GRID_PEAK_SHAVING_POWER for %s (reg %d): %.1f kW",
                        self.serial,
                        start_register,
                        raw_value,
                    )
                    return raw_value

                _LOGGER.warning(
                    "_12K_HOLD_GRID_PEAK_SHAVING_POWER for %s (reg %d) out of range: %.1f kW",
                    self.serial,
                    start_register,
                    raw_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse _12K_HOLD_GRID_PEAK_SHAVING_POWER for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "_12K_HOLD_GRID_PEAK_SHAVING_POWER" in parameter_data:
                    raw_value = parameter_data["_12K_HOLD_GRID_PEAK_SHAVING_POWER"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 0.0 <= value <= 25.5:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Read the current grid peak shaving power from the device
        try:
            current_value = await self._read_current_grid_peak_shaving_power()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded grid peak shaving power for %s: %.1f kW",
                    self.serial,
                    current_value,
                )
            else:
                # Leave current_value as None to show as unavailable
                _LOGGER.debug(
                    "Could not read grid peak shaving power for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize grid peak shaving power for %s: %s",
                self.serial,
                e,
            )
            # Leave current_value as None to show as unavailable


class ACChargeSOCLimitNumber(CoordinatorEntity, NumberEntity):
    """Number entity for AC Charge SOC Limit control.

    Note: Several assignments have type: ignore[assignment] due to mypy
    control flow false positives when assigning float to Optional[float].
    Mypy incorrectly narrows the type to None in some branches.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "AC Charge SOC Limit"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_ac_charge_soc_limit"

        _LOGGER.debug(
            "Creating AC Charge SOC Limit entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for AC Charge SOC Limit (0-100%)
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created AC Charge SOC Limit number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[int]:
        """Return the current AC charge SOC limit value as integer."""
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            self._current_value = coordinator_value
            return int(round(coordinator_value))

        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))

        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "HOLD_AC_CHARGE_SOC_LIMIT" in parameter_data:
                    raw_value = parameter_data["HOLD_AC_CHARGE_SOC_LIMIT"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 0 <= value <= 100:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge SOC limit value."""
        try:
            int_value = int(round(value))
            if int_value < 0 or int_value > 100:
                raise ValueError(
                    f"AC charge SOC limit must be between 0-100%, got {int_value}"
                )

            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"AC charge SOC limit must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting AC Charge SOC Limit for %s to %d%%", self.serial, int_value
            )

            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_AC_CHARGE_SOC_LIMIT",
                value_text=str(int_value),
            )

            _LOGGER.debug(
                "AC Charge SOC Limit write response for %s: %s", self.serial, response
            )

            if response.get("success", False):
                self._current_value = value
                self.async_write_ha_state()

                _LOGGER.info(
                    "AC Charge SOC Limit changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set AC Charge SOC Limit for %s to %d%%",
                    self.serial,
                    int_value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(
                    f"Failed to set AC charge SOC limit: {error_msg}"
                )

        except Exception as e:
            _LOGGER.error(
                "Failed to set AC Charge SOC Limit for %s: %s", self.serial, e
            )
            raise HomeAssistantError(f"Failed to set AC charge SOC limit: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all SOC limit entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()

            platform = self.platform
            if platform is not None:
                soc_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(
                        entity,
                        (
                            ACChargeSOCLimitNumber,
                            OnGridSOCCutoffNumber,
                            OffGridSOCCutoffNumber,
                        ),
                    )
                ]

                _LOGGER.info(
                    "Updating %d SOC limit entities after parameter refresh",
                    len(soc_entities),
                )

                update_tasks = []
                for entity in soc_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_ac_charge_soc_limit()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "AC charge SOC limit for %s updated from %s%% to %s%%",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error(
                "Failed to update AC charge SOC limit for %s: %s", self.serial, e
            )

        await self.coordinator.async_request_refresh()

    async def _read_current_ac_charge_soc_limit(self) -> Optional[float]:
        """Read the current AC charge SOC limit from the device."""
        try:
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    ac_charge_soc_limit = self._extract_ac_charge_soc_limit(
                        response, start_register
                    )
                    if ac_charge_soc_limit is not None:
                        return ac_charge_soc_limit

        except Exception as e:
            _LOGGER.warning(
                "Failed to read AC charge SOC limit for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_ac_charge_soc_limit(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[int]:
        """Extract HOLD_AC_CHARGE_SOC_LIMIT from parameter response."""
        if (
            "HOLD_AC_CHARGE_SOC_LIMIT" in response
            and response["HOLD_AC_CHARGE_SOC_LIMIT"] is not None
        ):
            try:
                raw_value = float(response["HOLD_AC_CHARGE_SOC_LIMIT"])
                int_value = int(round(raw_value))

                if 0 <= int_value <= 100:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_AC_CHARGE_SOC_LIMIT for %s (reg %d): %d%%",
                        self.serial,
                        start_register,
                        int_value,
                    )
                    return int_value

                _LOGGER.warning(
                    "HOLD_AC_CHARGE_SOC_LIMIT for %s (reg %d) out of range: %d%%",
                    self.serial,
                    start_register,
                    int_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_AC_CHARGE_SOC_LIMIT for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        try:
            current_value = await self._read_current_ac_charge_soc_limit()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded AC charge SOC limit for %s: %s%%",
                    self.serial,
                    current_value,
                )
            else:
                _LOGGER.debug(
                    "Could not read AC charge SOC limit for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize AC charge SOC limit for %s: %s", self.serial, e
            )


class OnGridSOCCutoffNumber(CoordinatorEntity, NumberEntity):
    """Number entity for On-Grid SOC Cut-Off control.

    Note: Several assignments have type: ignore[assignment] due to mypy
    control flow false positives when assigning float to Optional[float].
    Mypy incorrectly narrows the type to None in some branches.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "On-Grid SOC Cut-Off"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_on_grid_soc_cutoff"

        _LOGGER.debug(
            "Creating On-Grid SOC Cut-Off entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for On-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created On-Grid SOC Cut-Off number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[int]:
        """Return the current on-grid SOC cutoff value as integer."""
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            self._current_value = coordinator_value
            return int(round(coordinator_value))

        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))

        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "HOLD_DISCHG_CUT_OFF_SOC_EOD" in parameter_data:
                    raw_value = parameter_data["HOLD_DISCHG_CUT_OFF_SOC_EOD"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 0 <= value <= 100:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid SOC cutoff value."""
        try:
            int_value = int(round(value))
            if int_value < 0 or int_value > 100:
                raise ValueError(
                    f"On-grid SOC cutoff must be between 0-100%, got {int_value}"
                )

            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"On-grid SOC cutoff must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting On-Grid SOC Cut-Off for %s to %d%%", self.serial, int_value
            )

            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_DISCHG_CUT_OFF_SOC_EOD",
                value_text=str(int_value),
            )

            _LOGGER.debug(
                "On-Grid SOC Cut-Off write response for %s: %s", self.serial, response
            )

            if response.get("success", False):
                self._current_value = value
                self.async_write_ha_state()

                _LOGGER.info(
                    "On-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set On-Grid SOC Cut-Off for %s to %d%%",
                    self.serial,
                    int_value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(
                    f"Failed to set on-grid SOC cutoff: {error_msg}"
                )

        except Exception as e:
            _LOGGER.error(
                "Failed to set On-Grid SOC Cut-Off for %s: %s", self.serial, e
            )
            raise HomeAssistantError(f"Failed to set on-grid SOC cutoff: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all SOC limit entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()

            platform = self.platform
            if platform is not None:
                soc_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(
                        entity,
                        (
                            ACChargeSOCLimitNumber,
                            OnGridSOCCutoffNumber,
                            OffGridSOCCutoffNumber,
                        ),
                    )
                ]

                _LOGGER.info(
                    "Updating %d SOC limit entities after parameter refresh",
                    len(soc_entities),
                )

                update_tasks = []
                for entity in soc_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_on_grid_soc_cutoff()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "On-grid SOC cutoff for %s updated from %s%% to %s%%",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error(
                "Failed to update on-grid SOC cutoff for %s: %s", self.serial, e
            )

        await self.coordinator.async_request_refresh()

    async def _read_current_on_grid_soc_cutoff(self) -> Optional[float]:
        """Read the current on-grid SOC cutoff from the device."""
        try:
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    on_grid_soc_cutoff = self._extract_on_grid_soc_cutoff(
                        response, start_register
                    )
                    if on_grid_soc_cutoff is not None:
                        return on_grid_soc_cutoff

        except Exception as e:
            _LOGGER.warning(
                "Failed to read on-grid SOC cutoff for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_on_grid_soc_cutoff(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[int]:
        """Extract HOLD_DISCHG_CUT_OFF_SOC_EOD from parameter response."""
        if (
            "HOLD_DISCHG_CUT_OFF_SOC_EOD" in response
            and response["HOLD_DISCHG_CUT_OFF_SOC_EOD"] is not None
        ):
            try:
                raw_value = float(response["HOLD_DISCHG_CUT_OFF_SOC_EOD"])
                int_value = int(round(raw_value))

                if 0 <= int_value <= 100:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_DISCHG_CUT_OFF_SOC_EOD for %s (reg %d): %d%%",
                        self.serial,
                        start_register,
                        int_value,
                    )
                    return int_value

                _LOGGER.warning(
                    "HOLD_DISCHG_CUT_OFF_SOC_EOD for %s (reg %d) out of range: %d%%",
                    self.serial,
                    start_register,
                    int_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_DISCHG_CUT_OFF_SOC_EOD for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        try:
            current_value = await self._read_current_on_grid_soc_cutoff()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded on-grid SOC cutoff for %s: %s%%", self.serial, current_value
                )
            else:
                _LOGGER.debug(
                    "Could not read on-grid SOC cutoff for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize on-grid SOC cutoff for %s: %s", self.serial, e
            )


class OffGridSOCCutoffNumber(CoordinatorEntity, NumberEntity):
    """Number entity for Off-Grid SOC Cut-Off control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Off-Grid SOC Cut-Off"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_off_grid_soc_cutoff"

        _LOGGER.debug(
            "Creating Off-Grid SOC Cut-Off entity - Model: %s, Clean: %s, Serial: %s, Name: %s, Unique ID: %s",
            model,
            clean_model,
            serial,
            self._attr_name,
            self._attr_unique_id,
        )

        # Number configuration for Off-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast(DeviceInfo, coordinator.get_device_info(serial))

        # Current value
        self._current_value: Optional[float] = None

        _LOGGER.debug("Created Off-Grid SOC Cut-Off number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> Optional[int]:
        """Return the current off-grid SOC cutoff value as integer."""
        coordinator_value = self._get_value_from_coordinator()
        if coordinator_value is not None:
            self._current_value = coordinator_value
            return int(round(coordinator_value))

        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))

        return None

    def _get_value_from_coordinator(self) -> Optional[float]:
        """Get the current value from coordinator's parameter data."""
        try:
            if "parameters" in self.coordinator.data:
                parameter_data = self.coordinator.data["parameters"].get(
                    self.serial, {}
                )
                if "HOLD_SOC_LOW_LIMIT_EPS_DISCHG" in parameter_data:
                    raw_value = parameter_data["HOLD_SOC_LOW_LIMIT_EPS_DISCHG"]
                    if raw_value is not None:
                        value = float(raw_value)
                        if 0 <= value <= 100:  # Validate range
                            return value
        except (ValueError, TypeError, KeyError):
            pass
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid SOC cutoff value."""
        try:
            int_value = int(round(value))
            if int_value < 0 or int_value > 100:
                raise ValueError(
                    f"Off-grid SOC cutoff must be between 0-100%, got {int_value}"
                )

            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"Off-grid SOC cutoff must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting Off-Grid SOC Cut-Off for %s to %d%%", self.serial, int_value
            )

            response = await self.coordinator.api.write_parameter(
                inverter_sn=self.serial,
                hold_param="HOLD_SOC_LOW_LIMIT_EPS_DISCHG",
                value_text=str(int_value),
            )

            _LOGGER.debug(
                "Off-Grid SOC Cut-Off write response for %s: %s", self.serial, response
            )

            if response.get("success", False):
                self._current_value = value
                self.async_write_ha_state()

                _LOGGER.info(
                    "Off-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                    self.serial,
                )

                self.hass.async_create_task(self._refresh_all_parameters_and_entities())

                _LOGGER.info(
                    "Successfully set Off-Grid SOC Cut-Off for %s to %d%%",
                    self.serial,
                    int_value,
                )
            else:
                error_msg = response.get("message", "Unknown error")
                raise HomeAssistantError(
                    f"Failed to set off-grid SOC cutoff: {error_msg}"
                )

        except Exception as e:
            _LOGGER.error(
                "Failed to set Off-Grid SOC Cut-Off for %s: %s", self.serial, e
            )
            raise HomeAssistantError(f"Failed to set off-grid SOC cutoff: {e}") from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all SOC limit entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()

            platform = self.platform
            if platform is not None:
                soc_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(
                        entity,
                        (
                            ACChargeSOCLimitNumber,
                            OnGridSOCCutoffNumber,
                            OffGridSOCCutoffNumber,
                        ),
                    )
                ]

                _LOGGER.info(
                    "Updating %d SOC limit entities after parameter refresh",
                    len(soc_entities),
                )

                update_tasks = []
                for entity in soc_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_update(self) -> None:
        """Update the entity."""
        try:
            current_value = await self._read_current_off_grid_soc_cutoff()
            if current_value is not None and current_value != self._current_value:
                _LOGGER.debug(
                    "Off-grid SOC cutoff for %s updated from %s%% to %s%%",
                    self.serial,
                    self._current_value,
                    current_value,
                )
                self._current_value = current_value
        except Exception as e:
            _LOGGER.error(
                "Failed to update off-grid SOC cutoff for %s: %s", self.serial, e
            )

        await self.coordinator.async_request_refresh()

    async def _read_current_off_grid_soc_cutoff(self) -> Optional[float]:
        """Read the current off-grid SOC cutoff from the device."""
        try:
            responses = await read_device_parameters_ranges(
                self.coordinator.api, self.serial
            )

            for _, response, start_register in process_parameter_responses(
                responses, self.serial, _LOGGER
            ):
                if response and response.get("success", False):
                    off_grid_soc_cutoff = self._extract_off_grid_soc_cutoff(
                        response, start_register
                    )
                    if off_grid_soc_cutoff is not None:
                        return off_grid_soc_cutoff

        except Exception as e:
            _LOGGER.warning(
                "Failed to read off-grid SOC cutoff for %s due to: %s. "
                "Will retry automatically.",
                self.serial,
                e,
            )

        return None

    def _extract_off_grid_soc_cutoff(
        self, response: Dict[str, Any], start_register: int
    ) -> Optional[int]:
        """Extract HOLD_SOC_LOW_LIMIT_EPS_DISCHG from parameter response."""
        if (
            "HOLD_SOC_LOW_LIMIT_EPS_DISCHG" in response
            and response["HOLD_SOC_LOW_LIMIT_EPS_DISCHG"] is not None
        ):
            try:
                raw_value = float(response["HOLD_SOC_LOW_LIMIT_EPS_DISCHG"])
                int_value = int(round(raw_value))

                if 0 <= int_value <= 100:  # Validate range
                    _LOGGER.info(
                        "Found HOLD_SOC_LOW_LIMIT_EPS_DISCHG for %s (reg %d): %d%%",
                        self.serial,
                        start_register,
                        int_value,
                    )
                    return int_value

                _LOGGER.warning(
                    "HOLD_SOC_LOW_LIMIT_EPS_DISCHG for %s (reg %d) out of range: %d%%",
                    self.serial,
                    start_register,
                    int_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to parse HOLD_SOC_LOW_LIMIT_EPS_DISCHG for %s (reg %d): %s",
                    self.serial,
                    start_register,
                    e,
                )

        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        try:
            current_value = await self._read_current_off_grid_soc_cutoff()
            if current_value is not None:
                self._current_value = current_value
                self.async_write_ha_state()
                _LOGGER.info(
                    "Loaded off-grid SOC cutoff for %s: %s%%",
                    self.serial,
                    current_value,
                )
            else:
                _LOGGER.debug(
                    "Could not read off-grid SOC cutoff for %s, will show as unavailable",
                    self.serial,
                )
        except Exception as e:
            _LOGGER.error(
                "Failed to initialize off-grid SOC cutoff for %s: %s", self.serial, e
            )
