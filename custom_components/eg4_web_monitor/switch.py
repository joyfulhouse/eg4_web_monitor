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
from .base_entity import EG4BaseSwitch
from .const import FUNCTION_PARAM_MAPPING, SUPPORTED_INVERTER_MODELS, WORKING_MODES
from .coordinator import EG4DataUpdateCoordinator
from .utils import generate_entity_id

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

        # Only create switches for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check
            model = device_data.get("model", "Unknown")
            model_lower = model.lower()

            # Check if device model is known to support switch functions
            if any(supported in model_lower for supported in SUPPORTED_INVERTER_MODELS):
                # Add quick charge switch
                entities.append(EG4QuickChargeSwitch(coordinator, serial))

                # Add battery backup switch (EPS) - XP devices do not support this
                if "xp" not in model_lower:
                    entities.append(EG4BatteryBackupSwitch(coordinator, serial))

                # Add working mode switches
                for mode_key, mode_config in WORKING_MODES.items():
                    entities.append(
                        EG4WorkingModeSwitch(
                            coordinator=coordinator,
                            serial=serial,
                            mode_key=mode_key,
                            mode_config=mode_config,
                        )
                    )

    if entities:
        async_add_entities(entities)


class EG4QuickChargeSwitch(EG4BaseSwitch):
    """Switch to control quick charge functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the quick charge switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="quick_charge",
            name="Quick Charge",
            icon="mdi:battery-charging",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if quick charge is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check if we have quick charge status data from coordinator
        quick_charge_status = self._device_data.get("quick_charge_status")
        if quick_charge_status and isinstance(quick_charge_status, dict):
            # Parse the hasUnclosedQuickChargeTask field from getStatusInfo response
            has_unclosed_task = quick_charge_status.get("hasUnclosedQuickChargeTask")
            if has_unclosed_task is not None:
                return bool(has_unclosed_task)

        # Default to False if we don't have status information
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add quick charge task details if available
        quick_charge_status = self._device_data.get("quick_charge_status")
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on quick charge."""
        await self._execute_switch_action(
            action_name="quick charge",
            enable_method="enable_quick_charge",
            disable_method="disable_quick_charge",
            turn_on=True,
            refresh_params=False,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off quick charge."""
        await self._execute_switch_action(
            action_name="quick charge",
            enable_method="enable_quick_charge",
            disable_method="disable_quick_charge",
            turn_on=False,
            refresh_params=False,
        )


class EG4BatteryBackupSwitch(EG4BaseSwitch):
    """Switch to control battery backup (EPS) functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the battery backup switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="battery_backup",
            name="EPS Battery Backup",
            icon="mdi:battery-charging",
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if battery backup is enabled."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check battery backup status data from coordinator (real-time)
        battery_backup_status = self._device_data.get("battery_backup_status")
        if battery_backup_status and isinstance(battery_backup_status, dict):
            # Use the enabled field from battery backup status
            enabled = battery_backup_status.get("enabled")
            if enabled is not None:
                return bool(enabled)

        # Fallback: Check parameter data from coordinator
        return bool(self._parameter_data.get("FUNC_EPS_EN", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add battery backup status details if available
        battery_backup_status = self._device_data.get("battery_backup_status")
        if battery_backup_status and isinstance(battery_backup_status, dict):
            # Add battery backup status information
            func_eps_en = battery_backup_status.get("FUNC_EPS_EN")
            if func_eps_en is not None:
                attributes["func_eps_en"] = func_eps_en
            # Add any error information
            error = battery_backup_status.get("error")
            if error:
                attributes["status_error"] = error
        elif self._parameter_data:
            # Fallback: Add parameter details if available
            func_eps_en = self._parameter_data.get("FUNC_EPS_EN")
            if func_eps_en is not None:
                attributes["func_eps_en"] = func_eps_en

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable battery backup."""
        await self._execute_switch_action(
            action_name="battery backup",
            enable_method="enable_battery_backup",
            disable_method="disable_battery_backup",
            turn_on=True,
            refresh_params=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable battery backup."""
        await self._execute_switch_action(
            action_name="battery backup",
            enable_method="enable_battery_backup",
            disable_method="disable_battery_backup",
            turn_on=False,
            refresh_params=True,
        )


# Mapping of working mode parameters to inverter method names
_WORKING_MODE_METHODS = {
    "FUNC_AC_CHARGE": ("enable_ac_charge_mode", "disable_ac_charge_mode"),
    "FUNC_FORCED_CHG_EN": ("enable_pv_charge_priority", "disable_pv_charge_priority"),
    "FUNC_FORCED_DISCHG_EN": ("enable_forced_discharge", "disable_forced_discharge"),
    "FUNC_GRID_PEAK_SHAVING": ("enable_peak_shaving_mode", "disable_peak_shaving_mode"),
    "FUNC_BATTERY_BACKUP_CTRL": ("enable_battery_backup", "disable_battery_backup"),
}


class EG4WorkingModeSwitch(EG4BaseSwitch):
    """Switch for controlling EG4 working modes."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        mode_key: str,
        mode_config: dict[str, Any],
    ) -> None:
        """Initialize the working mode switch."""
        self._mode_key = mode_key
        self._mode_config = mode_config

        # Clean parameter name for entity key
        param_clean = mode_config["param"].lower().replace("func_", "")

        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key=mode_config["param"].lower(),
            name=mode_config["name"],
            icon=mode_config.get("icon", "mdi:toggle-switch"),
            entity_category=mode_config.get("entity_category"),
        )

        # Override entity_id with cleaner parameter name
        self._attr_entity_id = generate_entity_id(
            "switch", self._model, serial, param_clean
        )

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
            # Map function parameter to parameter register
            param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
            if param_key:
                param_value = self._parameter_data.get(param_key, False)
                # Handle both bool and int values
                if isinstance(param_value, bool):
                    is_enabled = param_value
                else:
                    is_enabled = param_value == 1

                _LOGGER.debug(
                    "Working mode switch %s (%s) - param_key=%s, raw_value=%s (type=%s), final_state=%s",
                    self._mode_config["param"],
                    self._serial,
                    param_key,
                    param_value,
                    type(param_value).__name__,
                    is_enabled,
                )
                return is_enabled
            else:
                _LOGGER.warning(
                    "Working mode switch %s (%s) - no param_key mapping found",
                    self._mode_config["param"],
                    self._serial,
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
        attributes: dict[str, Any] = {
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        param = self._mode_config["param"]
        methods = _WORKING_MODE_METHODS.get(param)

        if not methods:
            raise HomeAssistantError(f"Unknown working mode parameter: {param}")

        await self._execute_switch_action(
            action_name=f"working mode {param}",
            enable_method=methods[0],
            disable_method=methods[1],
            turn_on=True,
            refresh_params=False,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        param = self._mode_config["param"]
        methods = _WORKING_MODE_METHODS.get(param)

        if not methods:
            raise HomeAssistantError(f"Unknown working mode parameter: {param}")

        await self._execute_switch_action(
            action_name=f"working mode {param}",
            enable_method=methods[0],
            disable_method=methods[1],
            turn_on=False,
            refresh_params=False,
        )


class EG4DSTSwitch(CoordinatorEntity[EG4DataUpdateCoordinator], SwitchEntity):
    """Switch entity for station Daylight Saving Time configuration.

    Note: This switch doesn't inherit from EG4BaseSwitch because it operates
    on station-level data rather than device-level data.
    """

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
    def device_info(self) -> DeviceInfo | None:
        """Return device information."""
        return self.coordinator.get_station_device_info()

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
        """Enable Daylight Saving Time."""
        await self._set_dst(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Daylight Saving Time."""
        await self._set_dst(enabled=False)

    async def _set_dst(self, enabled: bool) -> None:
        """Set Daylight Saving Time state."""
        action = "Enabling" if enabled else "Disabling"
        try:
            _LOGGER.info(
                "%s Daylight Saving Time for station %s",
                action,
                self.coordinator.plant_id,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = enabled
            self.async_write_ha_state()

            # Get station device object
            station = self.coordinator.station
            if not station:
                raise HomeAssistantError(
                    f"Station {self.coordinator.plant_id} not found"
                )

            # Use device object convenience method
            success = await station.set_daylight_saving_time(enabled=enabled)
            if not success:
                raise HomeAssistantError(
                    f"Failed to {'enable' if enabled else 'disable'} Daylight Saving Time"
                )

            _LOGGER.info(
                "Successfully %s Daylight Saving Time for station %s",
                "enabled" if enabled else "disabled",
                self.coordinator.plant_id,
            )

            # Wait 2 seconds for server to apply changes before refreshing
            await asyncio.sleep(2)

            # Request coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()

            # Clear optimistic state after refresh
            self._optimistic_state = None
            self.async_write_ha_state()

        except HomeAssistantError:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        except Exception as e:
            _LOGGER.error(
                "Failed to %s Daylight Saving Time for station %s: %s",
                action.lower(),
                self.coordinator.plant_id,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action.lower()} Daylight Saving Time: {e}"
            ) from e
