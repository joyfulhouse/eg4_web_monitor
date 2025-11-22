"""Switch platform for EG4 Web Monitor integration."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.switch import SwitchEntity  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from . import EG4ConfigEntry
from .const import FUNCTION_PARAM_MAPPING, WORKING_MODES
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    create_device_info,
    generate_entity_id,
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor switch entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[SwitchEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for switch setup")
        return

    # Create station DST switch if station data is available
    if "station" in coordinator.data:
        entities.append(EG4DSTSwitch(coordinator))
        _LOGGER.debug("Added DST switch for station")

    # Skip device switches if no devices data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data for switch setup, creating station switches only"
        )
        if entities:
            async_add_entities(entities, True)
        return

    # Create switch entities for compatible devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type: %s", serial, device_type)

        # Only create switches for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check
            model = device_data.get("model", "Unknown")
            model_lower = model.lower()

            _LOGGER.info(
                "Evaluating switch compatibility for device %s: "
                "model='%s' (original), model_lower='%s'",
                serial,
                model,
                model_lower,
            )

            # Check if device model is known to support switch functions
            # Based on the feature request, this appears to be for standard inverters
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                # Add quick charge switch
                entities.append(EG4QuickChargeSwitch(coordinator, serial, device_data))
                _LOGGER.info(
                    "✅ Added quick charge switch for compatible device %s (%s)",
                    serial,
                    model,
                )

                # Add battery backup switch (EPS) - XP devices do not support this
                if not any(xp_model in model_lower for xp_model in ["xp"]):
                    entities.append(
                        EG4BatteryBackupSwitch(coordinator, serial, device_data)
                    )
                    _LOGGER.info(
                        "✅ Added battery backup switch for compatible device %s (%s)",
                        serial,
                        model,
                    )
                else:
                    _LOGGER.info(
                        "⚠️ Skipping battery backup switch for XP device %s (%s) - "
                        "XP devices do not support EPS functionality",
                        serial,
                        model,
                    )
                # Add working mode switches
                for mode_config in WORKING_MODES.values():
                    entities.append(
                        EG4WorkingModeSwitch(
                            coordinator=coordinator,
                            device_data=device_data,
                            serial_number=serial,
                            mode_config=mode_config,
                        )
                    )
                    _LOGGER.info(
                        "✅ Added working mode switch '%s' for device %s (%s)",
                        mode_config["name"],
                        serial,
                        model,
                    )
            else:
                _LOGGER.warning(
                    "❌ Skipping switches for device %s (%s) - "
                    "model not in supported list %s",
                    serial,
                    model,
                    supported_models,
                )
        else:
            _LOGGER.debug(
                "Skipping device %s - not an inverter (type: %s)", serial, device_type
            )

    if entities:
        _LOGGER.info(
            "Adding %d switch entities (quick charge and battery backup)", len(entities)
        )
        async_add_entities(entities)
    else:
        _LOGGER.debug("No switch entities created - no compatible devices found")


class EG4QuickChargeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control quick charge functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the quick charge switch."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

        # Get device info from coordinator data
        self._model = (
            coordinator.data.get("devices", {}).get(serial, {}).get("model", "Unknown")
            if coordinator.data
            else "Unknown"
        )

        # Create unique identifiers using consolidated utilities
        self._attr_unique_id = generate_unique_id(serial, "quick_charge")
        self._attr_entity_id = generate_entity_id(
            "switch", self._model, serial, "quick_charge"
        )

        # Set device attributes
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Quick Charge"
        self._attr_icon = "mdi:battery-charging"

        # Device info for grouping using consolidated utility
        self._attr_device_info = create_device_info(serial, self._model)

    @property
    def is_on(self) -> bool | None:
        """Return True if quick charge is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check if we have quick charge status data from coordinator
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            quick_charge_status = device_data.get("quick_charge_status")

            if quick_charge_status and isinstance(quick_charge_status, dict):
                # Parse the hasUnclosedQuickChargeTask field from getStatusInfo response
                has_unclosed_task = quick_charge_status.get(
                    "hasUnclosedQuickChargeTask"
                )
                if has_unclosed_task is not None:
                    return bool(has_unclosed_task)

        # Default to False if we don't have status information
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add quick charge task details if available
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            quick_charge_status = device_data.get("quick_charge_status")

            if quick_charge_status and isinstance(quick_charge_status, dict):
                # Add useful status information as attributes
                task_id = quick_charge_status.get("unclosedQuickChargeTaskId")
                task_status = quick_charge_status.get("unclosedQuickChargeTaskStatus")

                if task_id:
                    attributes["task_id"] = task_id
                if task_status:
                    attributes["task_status"] = task_status

                # Add optimistic state indicator for debugging
                if self._optimistic_state is not None:
                    attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if the device supports quick charge
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            # Only available for inverter devices (not GridBOSS)
            return bool(device_data.get("type") == "inverter")
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn on quick charge using device object method."""
        try:
            _LOGGER.debug("Starting quick charge for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self._serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial} not found")

            # Use device object convenience method
            success = await inverter.enable_quick_charge()
            if not success:
                raise HomeAssistantError("Failed to enable quick charge")

            _LOGGER.info(
                "Successfully started quick charge for device %s", self._serial
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and request coordinator update for real status
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error(
                "Failed to start quick charge for device %s: %s", self._serial, e
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn off quick charge using device object method."""
        try:
            _LOGGER.debug("Stopping quick charge for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self._serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial} not found")

            # Use device object convenience method
            success = await inverter.disable_quick_charge()
            if not success:
                raise HomeAssistantError("Failed to disable quick charge")

            _LOGGER.info(
                "Successfully stopped quick charge for device %s", self._serial
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and request coordinator update for real status
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error(
                "Failed to stop quick charge for device %s: %s", self._serial, e
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise


class EG4BatteryBackupSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control battery backup (EPS) functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the battery backup switch."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

        # Get device info from coordinator data
        self._model = (
            coordinator.data.get("devices", {}).get(serial, {}).get("model", "Unknown")
            if coordinator.data
            else "Unknown"
        )

        # Create unique identifiers using consolidated utilities
        self._attr_unique_id = generate_unique_id(serial, "battery_backup")
        self._attr_entity_id = generate_entity_id(
            "switch", self._model, serial, "battery_backup"
        )

        # Set device attributes
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "EPS Battery Backup"
        self._attr_icon = "mdi:battery-charging"
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info for grouping using consolidated utility
        self._attr_device_info = create_device_info(serial, self._model)

    @property
    def is_on(self) -> bool | None:
        """Return True if battery backup is enabled."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check battery backup status data from coordinator (real-time)
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            battery_backup_status = device_data.get("battery_backup_status")

            if battery_backup_status and isinstance(battery_backup_status, dict):
                # Use the enabled field from battery backup status
                enabled = battery_backup_status.get("enabled")
                if enabled is not None:
                    return bool(enabled)

        # Fallback: Check parameter data from coordinator
        if self.coordinator.data and "parameters" in self.coordinator.data:
            device_params = self.coordinator.data["parameters"].get(self._serial, {})
            return bool(device_params.get("FUNC_EPS_EN", False))

        # Default to False if we don't have any information
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add battery backup status details if available
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            battery_backup_status = device_data.get("battery_backup_status")

            if battery_backup_status and isinstance(battery_backup_status, dict):
                # Add battery backup status information
                func_eps_en = battery_backup_status.get("FUNC_EPS_EN")
                if func_eps_en is not None:
                    attributes["func_eps_en"] = func_eps_en
                # Add any error information
                error = battery_backup_status.get("error")
                if error:
                    attributes["status_error"] = error

        # Fallback: Add parameter details if available
        if (
            not attributes
            and self.coordinator.data
            and "parameters" in self.coordinator.data
        ):
            device_params = self.coordinator.data["parameters"].get(self._serial, {})
            func_eps_en = device_params.get("FUNC_EPS_EN")

            if func_eps_en is not None:
                attributes["func_eps_en"] = func_eps_en

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if the device supports battery backup
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            # Only available for inverter devices (not GridBOSS)
            return bool(device_data.get("type") == "inverter")
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Enable battery backup using device object method."""
        try:
            _LOGGER.debug("Enabling battery backup for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self._serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial} not found")

            # Use device object convenience method
            success = await inverter.enable_battery_backup()
            if not success:
                raise HomeAssistantError("Failed to enable battery backup")

            _LOGGER.info(
                "Successfully enabled battery backup for device %s", self._serial
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error(
                "Failed to enable battery backup for device %s: %s", self._serial, e
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Disable battery backup using device object method."""
        try:
            _LOGGER.debug("Disabling battery backup for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self._serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial} not found")

            # Use device object convenience method
            success = await inverter.disable_battery_backup()
            if not success:
                raise HomeAssistantError("Failed to disable battery backup")

            _LOGGER.info(
                "Successfully disabled battery backup for device %s", self._serial
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error(
                "Failed to disable battery backup for device %s: %s", self._serial, e
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise


class EG4WorkingModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for controlling EG4 working modes."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        device_data: dict[str, Any],
        serial_number: str,
        mode_config: dict[str, Any],
    ) -> None:
        """Initialize the working mode switch."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self._coordinator = coordinator
        self._device_data = device_data
        self._serial_number = serial_number
        self._mode_config = mode_config

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

        # Get device model
        self._model = device_data.get("model", "Unknown")

        # Set entity attributes using consolidated utilities
        param_clean = self._mode_config["param"].lower().replace("func_", "")
        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = self._mode_config["name"]
        self._attr_unique_id = generate_unique_id(
            serial_number, self._mode_config["param"].lower()
        )
        self._attr_entity_id = generate_entity_id(
            "switch", self._model, serial_number, param_clean
        )
        self._attr_entity_category = self._mode_config["entity_category"]
        self._attr_icon = self._mode_config.get("icon", "mdi:toggle-switch")

        # Device info for grouping using consolidated utility
        self._attr_device_info = create_device_info(serial_number, self._model)

    @property
    def is_on(self) -> bool:
        """Return if the switch is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            _LOGGER.debug(
                "Working mode switch %s using optimistic state: %s",
                self._mode_config["param"],
                self._optimistic_state,
            )
            return self._optimistic_state

        # Read state from coordinator parameters
        try:
            if self._coordinator.data and "parameters" in self._coordinator.data:
                parameter_data = self._coordinator.data["parameters"].get(
                    self._serial_number, {}
                )

                # Map function parameter to parameter register
                param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
                if param_key:
                    param_value = parameter_data.get(param_key, False)
                    # Handle both bool and int values
                    if isinstance(param_value, bool):
                        is_enabled = param_value
                    else:
                        is_enabled = param_value == 1

                    _LOGGER.debug(
                        "Working mode switch %s (%s) - param_key=%s, raw_value=%s (type=%s), final_state=%s",
                        self._mode_config["param"],
                        self._serial_number,
                        param_key,
                        param_value,
                        type(param_value).__name__,
                        is_enabled,
                    )
                    return is_enabled
                else:
                    _LOGGER.warning(
                        "Working mode switch %s (%s) - no param_key mapping found in FUNCTION_PARAM_MAPPING",
                        self._mode_config["param"],
                        self._serial_number,
                    )
        except Exception as err:
            _LOGGER.error(
                "Error reading working mode state for %s: %s",
                self._mode_config["param"],
                err,
            )

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {
            "description": self._mode_config["description"],
            "function_parameter": self._mode_config["param"],
        }

        # Add parameter register information
        param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
        if param_key:
            attributes["parameter_register"] = param_key

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if the device supports working modes
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial_number, {})
            # Only available for inverter devices (not GridBOSS)
            return bool(device_data.get("type") == "inverter")
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the switch on using device object method."""
        try:
            param = self._mode_config["param"]
            _LOGGER.debug(
                "Enabling working mode %s for device %s",
                param,
                self._serial_number,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self._coordinator.get_inverter_object(self._serial_number)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial_number} not found")

            # Map parameter to device object method
            success = False
            if param == "FUNC_AC_CHARGE":
                success = await inverter.enable_ac_charge_mode()
            elif param == "FUNC_FORCED_CHG_EN":
                success = await inverter.enable_pv_charge_priority()
            elif param == "FUNC_FORCED_DISCHG_EN":
                success = await inverter.enable_forced_discharge()
            elif param == "FUNC_GRID_PEAK_SHAVING":
                success = await inverter.enable_peak_shaving_mode()
            elif param == "FUNC_BATTERY_BACKUP_CTRL":
                success = await inverter.enable_battery_backup()
            else:
                raise HomeAssistantError(f"Unknown working mode parameter: {param}")

            if not success:
                raise HomeAssistantError(f"Failed to enable {param}")

            _LOGGER.info(
                "Successfully enabled working mode %s for device %s",
                param,
                self._serial_number,
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and force entity update
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(
                "Failed to enable working mode %s for device %s: %s",
                self._mode_config["param"],
                self._serial_number,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the switch off using device object method."""
        try:
            param = self._mode_config["param"]
            _LOGGER.debug(
                "Disabling working mode %s for device %s",
                param,
                self._serial_number,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Get inverter device object
            inverter = self._coordinator.get_inverter_object(self._serial_number)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self._serial_number} not found")

            # Map parameter to device object method
            success = False
            if param == "FUNC_AC_CHARGE":
                success = await inverter.disable_ac_charge_mode()
            elif param == "FUNC_FORCED_CHG_EN":
                success = await inverter.disable_pv_charge_priority()
            elif param == "FUNC_FORCED_DISCHG_EN":
                success = await inverter.disable_forced_discharge()
            elif param == "FUNC_GRID_PEAK_SHAVING":
                success = await inverter.disable_peak_shaving_mode()
            elif param == "FUNC_BATTERY_BACKUP_CTRL":
                success = await inverter.disable_battery_backup()
            else:
                raise HomeAssistantError(f"Unknown working mode parameter: {param}")

            if not success:
                raise HomeAssistantError(f"Failed to disable {param}")

            _LOGGER.info(
                "Successfully disabled working mode %s for device %s",
                param,
                self._serial_number,
            )

            # Refresh inverter data
            await inverter.refresh()

            # Clear optimistic state and force entity update
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(
                "Failed to disable working mode %s for device %s: %s",
                self._mode_config["param"],
                self._serial_number,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise


class EG4DSTSwitch(CoordinatorEntity[EG4DataUpdateCoordinator], SwitchEntity):
    """Switch entity for station Daylight Saving Time configuration."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
    ) -> None:
        """Initialize the DST switch."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_name = "Daylight Saving Time"
        self._attr_icon = "mdi:clock-time-four"
        self._attr_entity_category = EntityCategory.CONFIG

        # Build unique ID
        self._attr_unique_id = f"station_{coordinator.plant_id}_dst"

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_info = self.coordinator.get_station_device_info()
        return device_info if device_info else {}

    @property
    def is_on(self) -> bool:
        """Return true if DST is enabled."""
        # Use optimistic state if available (during turn_on/turn_off)
        if self._optimistic_state is not None:
            return self._optimistic_state

        if not self.coordinator.data or "station" not in self.coordinator.data:
            return False

        station_data = self.coordinator.data["station"]
        dst_value = station_data.get("daylightSavingTime", False)
        _LOGGER.debug(
            "DST switch state for plant %s: daylightSavingTime=%s (type: %s)",
            self.coordinator.plant_id,
            dst_value,
            type(dst_value).__name__,
        )
        return bool(dst_value)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "station" in self.coordinator.data
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Daylight Saving Time using device object method."""
        try:
            _LOGGER.info(
                "Enabling Daylight Saving Time for station %s",
                self.coordinator.plant_id,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Get station device object
            station = self.coordinator.station
            if not station:
                raise HomeAssistantError(
                    f"Station {self.coordinator.plant_id} not found"
                )

            # Use device object convenience method
            success = await station.set_daylight_saving_time(enabled=True)
            if not success:
                raise HomeAssistantError("Failed to enable Daylight Saving Time")

            _LOGGER.info(
                "Successfully enabled Daylight Saving Time for station %s",
                self.coordinator.plant_id,
            )

            # Wait 2 seconds for server to apply changes before refreshing
            await asyncio.sleep(2)

            # Request coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()

            # Clear optimistic state after refresh
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(
                "Failed to enable Daylight Saving Time for station %s: %s",
                self.coordinator.plant_id,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Daylight Saving Time using device object method."""
        try:
            _LOGGER.info(
                "Disabling Daylight Saving Time for station %s",
                self.coordinator.plant_id,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Get station device object
            station = self.coordinator.station
            if not station:
                raise HomeAssistantError(
                    f"Station {self.coordinator.plant_id} not found"
                )

            # Use device object convenience method
            success = await station.set_daylight_saving_time(enabled=False)
            if not success:
                raise HomeAssistantError("Failed to disable Daylight Saving Time")

            _LOGGER.info(
                "Successfully disabled Daylight Saving Time for station %s",
                self.coordinator.plant_id,
            )

            # Wait 2 seconds for server to apply changes before refreshing
            await asyncio.sleep(2)

            # Request coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()

            # Clear optimistic state after refresh
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(
                "Failed to disable Daylight Saving Time for station %s: %s",
                self.coordinator.plant_id,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
