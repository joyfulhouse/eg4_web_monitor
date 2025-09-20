"""Switch platform for EG4 Web Monitor integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WORKING_MODES, FUNCTION_PARAM_MAPPING
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor switch entities."""
    coordinator: EG4DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: List[SwitchEntity] = []

    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.warning("No device data available for switch setup")
        return

    # Create switch entities for compatible devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")
        _LOGGER.debug("Processing device %s with type: %s", serial, device_type)

        # Only create switches for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")
            model_lower = model.lower()

            _LOGGER.info(
                "Evaluating switch compatibility for device %s: "
                "model='%s' (original), model_lower='%s'",
                serial, model, model_lower
            )

            # Check if device model is known to support switch functions
            # Based on the feature request, this appears to be for standard inverters
            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]

            if any(supported in model_lower for supported in supported_models):
                # Add quick charge switch
                entities.append(EG4QuickChargeSwitch(coordinator, serial, device_data))
                _LOGGER.info(
                    "✅ Added quick charge switch for compatible device %s (%s)", serial, model
                )# Add battery backup switch
                entities.append(EG4BatteryBackupSwitch(coordinator, serial, device_data))
                _LOGGER.info(
                    "✅ Added battery backup switch for compatible device %s (%s)", serial, model
                )
                # Add working mode switches
                for mode_config in WORKING_MODES.values():
                    entities.append(EG4WorkingModeSwitch(
                        coordinator=coordinator,
                        device_info=device_info,
                        serial_number=serial,
                        mode_config=mode_config
                    ))
                    _LOGGER.info(
                        "✅ Added working mode switch '%s' for compatible device %s (%s)",
                        mode_config['name'], serial, model
                    )
            else:
                _LOGGER.warning(
                    "❌ Skipping switches for device %s (%s) - "
                    "model not in supported list %s",
                    serial, model, supported_models
                )
        else:
            _LOGGER.debug("Skipping device %s - not an inverter (type: %s)", serial, device_type)

    if entities:
        _LOGGER.info("Adding %d switch entities (quick charge and battery backup)", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.info("No switch entities to add")


class EG4QuickChargeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control quick charge functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: Dict[str, Any],
    ) -> None:
        """Initialize the quick charge switch."""
        super().__init__(coordinator)

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: Optional[bool] = None

        # Get device info from coordinator data
        device_info = coordinator.data.get("device_info", {}).get(serial, {})
        self._model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create unique identifiers
        model_clean = self._model.lower().replace(" ", "").replace("-", "")
        self._attr_unique_id = f"{serial}_quick_charge"
        self._attr_entity_id = f"switch.{model_clean}_{serial}_quick_charge"

        # Set device attributes
        self._attr_name = f"{self._model} {serial} Quick Charge"
        self._attr_icon = "mdi:battery-charging"

        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"{self._model} {serial}",
            "manufacturer": "EG4 Electronics",
            "model": self._model,
            "serial_number": serial,
        }

    @property
    def is_on(self) -> Optional[bool]:
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
                has_unclosed_task = quick_charge_status.get("hasUnclosedQuickChargeTask")
                if has_unclosed_task is not None:
                    return bool(has_unclosed_task)

        # Default to False if we don't have status information
        return False

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
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
            return device_data.get("type") == "inverter"
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn on quick charge."""
        try:
            _LOGGER.debug("Starting quick charge for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Call the API
            await self.coordinator.api.start_quick_charge(self._serial)
            _LOGGER.info("Successfully started quick charge for device %s", self._serial)

            # Clear optimistic state and request coordinator update for real status
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to start quick charge for device %s: %s", self._serial, e)
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn off quick charge."""
        try:
            _LOGGER.debug("Stopping quick charge for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Call the API
            await self.coordinator.api.stop_quick_charge(self._serial)
            _LOGGER.info("Successfully stopped quick charge for device %s", self._serial)

            # Clear optimistic state and request coordinator update for real status
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to stop quick charge for device %s: %s", self._serial, e)
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
        device_data: Dict[str, Any],
    ) -> None:
        """Initialize the battery backup switch."""
        super().__init__(coordinator)

        self._serial = serial
        self._device_data = device_data

        # Optimistic state for immediate UI feedback
        self._optimistic_state: Optional[bool] = None

        # Get device info from coordinator data
        device_info = coordinator.data.get("device_info", {}).get(serial, {})
        self._model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create unique identifiers
        model_clean = self._model.lower().replace(" ", "").replace("-", "")
        self._attr_unique_id = f"{serial}_battery_backup"
        self._attr_entity_id = f"switch.{model_clean}_{serial}_battery_backup"

        # Set device attributes
        self._attr_name = f"{self._model} {serial} EPS Battery Backup"
        self._attr_icon = "mdi:battery-charging"

        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"{self._model} {serial}",
            "manufacturer": "EG4 Electronics",
            "model": self._model,
            "serial_number": serial,
        }

    @property
    def is_on(self) -> Optional[bool]:
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
            return device_params.get("FUNC_EPS_EN", False)

        # Default to False if we don't have any information
        return False

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
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
        if not attributes and self.coordinator.data and "parameters" in self.coordinator.data:
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
            return device_data.get("type") == "inverter"
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Enable battery backup."""
        try:
            _LOGGER.debug("Enabling battery backup for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            # Call the API
            await self.coordinator.api.enable_battery_backup(self._serial)
            _LOGGER.info("Successfully enabled battery backup for device %s", self._serial)

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error("Failed to enable battery backup for device %s: %s", self._serial, e)
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Disable battery backup."""
        try:
            _LOGGER.debug("Disabling battery backup for device %s", self._serial)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            # Call the API
            await self.coordinator.api.disable_battery_backup(self._serial)
            _LOGGER.info("Successfully disabled battery backup for device %s", self._serial)

            # Clear optimistic state and request coordinator parameter refresh
            self._optimistic_state = None
            await self.coordinator.async_refresh_device_parameters(self._serial)

        except Exception as e:
            _LOGGER.error("Failed to disable battery backup for device %s: %s", self._serial, e)
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise


class EG4WorkingModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for controlling EG4 working modes."""

    def __init__(self, coordinator, device_info, serial_number, mode_config):
        """Initialize the working mode switch."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._device_info = device_info
        self._serial_number = serial_number
        self._mode_config = mode_config

        # Optimistic state for immediate UI feedback
        self._optimistic_state: Optional[bool] = None

        # Get device model
        self._model = device_info.get("deviceTypeText4APP", "Unknown")
        model_clean = self._model.lower().replace(" ", "").replace("-", "")

        # Set entity attributes
        self._attr_name = f"{self._model} {serial_number} {self._mode_config['name']}"
        self._attr_unique_id = f"{serial_number}_{self._mode_config['param'].lower()}"
        # Generate clean entity ID with proper underscores
        param_clean = self._mode_config['param'].lower().replace('func_', '')
        self._attr_entity_id = f"switch.{model_clean}_{serial_number}_{param_clean}"
        self._attr_entity_category = self._mode_config['entity_category']
        self._attr_icon = self._mode_config.get('icon', 'mdi:toggle-switch')

        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial_number)},
            "name": f"{self._model} {serial_number}",
            "manufacturer": "EG4 Electronics",
            "model": self._model,
            "serial_number": serial_number,
        }
    @property
    def is_on(self) -> bool:
        """Return if the switch is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            _LOGGER.debug("Working mode switch %s using optimistic state: %s",
                         self._mode_config['param'], self._optimistic_state)
            return self._optimistic_state

        state = self._coordinator.get_working_mode_state(
            self._serial_number,
            self._mode_config['param']
        )
        _LOGGER.debug("Working mode switch %s (%s) current state: %s",
                     self._mode_config['param'], self._serial_number, state)
        return state

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return extra state attributes."""
        attributes = {
            "description": self._mode_config['description'],
            "function_parameter": self._mode_config['param']
        }

        # Add parameter register information
        param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config['param'])
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
            return device_data.get("type") == "inverter"
        return False
    async def async_turn_on(self, **kwargs) -> None:  # pylint: disable=unused-argument
        """Turn the switch on."""
        try:
            _LOGGER.debug("Enabling working mode %s for device %s",
                         self._mode_config['param'], self._serial_number)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = True
            self.async_write_ha_state()

            await self._coordinator.set_working_mode(
                self._serial_number,
                self._mode_config['param'],
                True
            )
            _LOGGER.info("Successfully enabled working mode %s for device %s",
                        self._mode_config['param'], self._serial_number)

            # Clear optimistic state and force entity update
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Failed to enable working mode %s for device %s: %s",
                         self._mode_config['param'], self._serial_number, e)
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
    async def async_turn_off(self, **kwargs) -> None:  # pylint: disable=unused-argument
        """Turn the switch off."""
        try:
            _LOGGER.debug("Disabling working mode %s for device %s",
                         self._mode_config['param'], self._serial_number)

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = False
            self.async_write_ha_state()

            await self._coordinator.set_working_mode(
                self._serial_number,
                self._mode_config['param'],
                False
            )
            _LOGGER.info("Successfully disabled working mode %s for device %s",
                        self._mode_config['param'], self._serial_number)

            # Clear optimistic state and force entity update
            self._optimistic_state = None
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Failed to disable working mode %s for device %s: %s",
                         self._mode_config['param'], self._serial_number, e)
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
