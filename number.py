"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
from typing import Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator
from .utils import read_device_parameters_ranges, process_parameter_responses

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor number entities from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []

    # Create number entities for each inverter device (not GridBOSS or parallel groups)
    for serial, device_data in coordinator.data.get("devices", {}).items():
        device_type = device_data.get("type")
        if device_type == "inverter":
            entities.append(SystemChargeSOCLimitNumber(coordinator, serial))

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
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration - explicit entity_id to override registry caching
        # Clean model name for entity ID - following same pattern as sensors
        clean_model = model.lower().replace(" ", "_").replace("-", "_")

        # Set entity attributes - unique_id is key for proper entity registration
        self._attr_name = f"{clean_model} {serial.lower()} System Charge SOC Limit"
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

        # Device info
        self._attr_device_info = coordinator.get_device_info(serial)

        # Current value - will be loaded from device
        self._current_value = None

        _LOGGER.debug("Created System Charge SOC Limit number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Optional[int]:
        """Return the current SOC limit value as integer."""
        # Return the cached value if available
        if hasattr(self, "_current_value") and self._current_value is not None:
            return int(round(self._current_value))
        # Return None to indicate unknown value - will be loaded asynchronously
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
                    self.serial, total_responses, total_responses
                )
            else:
                _LOGGER.info(
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT parameter not found for %s "
                    "in %d successful parameter responses. "
                    "This may be a device model compatibility issue.",
                    self.serial, successful_responses
                )

        except Exception as e:
            _LOGGER.warning(
                "Failed to read SOC limit for %s due to: %s. "
                "This is typically caused by temporary API issues. Will retry automatically.",
                self.serial, e
            )

        return None

    def _extract_system_charge_soc_limit(
        self, response: dict, start_register: int
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
                # Set a reasonable default if we can't read the current value
                self._current_value = 90
                _LOGGER.warning(
                    "Could not read SOC limit for %s, using default: 90%%", self.serial
                )
        except Exception as e:
            _LOGGER.error("Failed to initialize SOC limit for %s: %s", self.serial, e)
            self._current_value = 90  # Safe default
