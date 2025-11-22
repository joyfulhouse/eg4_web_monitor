"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.number import NumberEntity, NumberMode
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.number import NumberEntity, NumberMode
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import EG4ConfigEntry
from .const import (
    AC_CHARGE_POWER_MAX,
    AC_CHARGE_POWER_MIN,
    AC_CHARGE_POWER_STEP,
    BATTERY_CURRENT_MAX,
    BATTERY_CURRENT_MIN,
    BATTERY_CURRENT_STEP,
    GRID_PEAK_SHAVING_POWER_MAX,
    GRID_PEAK_SHAVING_POWER_MIN,
    GRID_PEAK_SHAVING_POWER_STEP,
    PV_CHARGE_POWER_MAX,
    PV_CHARGE_POWER_MIN,
    PV_CHARGE_POWER_STEP,
    SOC_LIMIT_MAX,
    SOC_LIMIT_MIN,
    SOC_LIMIT_STEP,
    SYSTEM_CHARGE_SOC_LIMIT_MAX,
    SYSTEM_CHARGE_SOC_LIMIT_MIN,
    SYSTEM_CHARGE_SOC_LIMIT_STEP,
)
from .coordinator import EG4DataUpdateCoordinator
from .utils import clean_model_name

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

    entities: list[NumberEntity] = []

    # Create number entities for each inverter device (not GridBOSS or parallel groups)
    for serial, device_data in coordinator.data.get("devices", {}).items():
        device_type = device_data.get("type")
        if device_type == "inverter":
            # Get device model for compatibility check
            model = device_data.get("model", "Unknown")
            model_lower = model.lower()

            _LOGGER.debug(
                "Evaluating number entity compatibility: device=%s, model=%s",
                serial,
                model,
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
                _LOGGER.debug(
                    "Created 9 number entities for device %s (%s)",
                    serial,
                    model,
                )
            else:
                _LOGGER.debug(
                    "Skipping number entities for device %s (%s) - unsupported model",
                    serial,
                    model,
                )

    if entities:
        _LOGGER.info("Setup complete: %d number entities created", len(entities))
        async_add_entities(entities, update_before_add=False)
    else:
        _LOGGER.debug("No number entities created - no compatible devices found")


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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "System Charge SOC Limit"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_system_charge_soc_limit"

        # Number configuration for SOC limit (10-101%) - integer only
        self._attr_native_min_value = SYSTEM_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging"

        # Set precision to 0 decimal places (integers only)
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value - will be loaded from device
        self._current_value: float | None = None

        _LOGGER.debug("Created System Charge SOC Limit number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current SOC limit value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            if hasattr(inverter, "battery_soc_limits") and inverter.battery_soc_limits:
                soc_limit = inverter.battery_soc_limits.get("on_grid_limit")
                if soc_limit is not None and 10 <= soc_limit <= 101:
                    return int(soc_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting SOC limit for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the SOC limit value."""
        try:
            # Convert to integer and validate range - must be integer between 10-101
            int_value = int(value)
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

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use inverter device object's convenience method
            success = await inverter.set_battery_soc_limits(on_grid_limit=int_value)

            if not success:
                raise HomeAssistantError(f"Failed to set SOC limit to {int_value}%")

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "AC Charge Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_ac_charge_power"

        # Number configuration for AC Charge Power (0-15 kW)
        # Supports decimal values (0.1 kW step) to match EG4 web interface
        self._attr_native_min_value = AC_CHARGE_POWER_MIN
        self._attr_native_max_value = AC_CHARGE_POWER_MAX
        self._attr_native_step = AC_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created AC Charge Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge power value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            power_limit = inverter.ac_charge_power_limit
            if power_limit is not None and 0 <= power_limit <= 15:
                return round(power_limit, 1)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting AC charge power for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge power value using device object method."""
        try:
            # Validate range (0.0-15.0 kW)
            if value < 0.0 or value > 15.0:
                raise ValueError(
                    f"AC charge power must be between 0.0-15.0 kW, got {value}"
                )

            _LOGGER.info(
                "Setting AC Charge Power for %s to %.1f kW", self.serial, value
            )

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_ac_charge_power(power_kw=value)
            if not success:
                raise HomeAssistantError("Failed to set AC charge power")

            _LOGGER.info(
                "Successfully set AC Charge Power for %s to %.1f kW",
                self.serial,
                value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "AC Charge Power changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error("Invalid AC Charge Power value for %s: %s", self.serial, e)
            raise HomeAssistantError(str(e)) from e
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "PV Charge Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_pv_charge_power"

        # Number configuration for PV Charge Power (0-15 kW)
        self._attr_native_min_value = PV_CHARGE_POWER_MIN
        self._attr_native_max_value = PV_CHARGE_POWER_MAX
        self._attr_native_step = PV_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created PV Charge Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current PV charge power value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            power_limit = inverter.pv_charge_power_limit
            if power_limit is not None and 0 <= power_limit <= 15:
                return int(power_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting PV charge power for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV charge power value using device object method."""
        try:
            # Convert to integer and validate range
            int_value = int(value)
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

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_pv_charge_power(power_kw=int_value)
            if not success:
                raise HomeAssistantError("Failed to set PV charge power")

            _LOGGER.info(
                "Successfully set PV Charge Power for %s to %d kW",
                self.serial,
                int_value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "PV Charge Power changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error("Invalid PV Charge Power value for %s: %s", self.serial, e)
            raise HomeAssistantError(str(e)) from e
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Grid Peak Shaving Power"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_grid_peak_shaving_power"

        # Number configuration for Grid Peak Shaving Power (0.0-25.5 kW)
        # Based on curl example with valueText range
        self._attr_native_min_value = GRID_PEAK_SHAVING_POWER_MIN
        self._attr_native_max_value = GRID_PEAK_SHAVING_POWER_MAX
        self._attr_native_step = GRID_PEAK_SHAVING_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_native_precision = 1
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created Grid Peak Shaving Power number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> float | None:
        """Return the current grid peak shaving power value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            power_limit = inverter.grid_peak_shaving_power_limit
            if power_limit is not None and 0 <= power_limit <= 25.5:
                return round(power_limit, 1)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting grid peak shaving power for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid peak shaving power value using device object method."""
        try:
            # Validate range (0.0-25.5 kW)
            if value < 0.0 or value > 25.5:
                raise ValueError(
                    f"Grid peak shaving power must be between 0.0-25.5 kW, got {value}"
                )

            _LOGGER.info(
                "Setting Grid Peak Shaving Power for %s to %.1f kW", self.serial, value
            )

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_grid_peak_shaving_power(power_kw=value)
            if not success:
                raise HomeAssistantError("Failed to set grid peak shaving power")

            _LOGGER.info(
                "Successfully set Grid Peak Shaving Power for %s to %.1f kW",
                self.serial,
                value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "Grid Peak Shaving Power changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error(
                "Invalid Grid Peak Shaving Power value for %s: %s", self.serial, e
            )
            raise HomeAssistantError(str(e)) from e
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "AC Charge SOC Limit"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_ac_charge_soc_limit"

        # Number configuration for AC Charge SOC Limit (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created AC Charge SOC Limit number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current AC charge SOC limit value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            soc_limit = inverter.ac_charge_soc_limit
            if soc_limit is not None and 0 <= soc_limit <= 100:
                return int(soc_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting AC charge SOC limit for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge SOC limit value using device object method."""
        try:
            int_value = int(value)
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

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_ac_charge_soc_limit(soc_percent=int_value)
            if not success:
                raise HomeAssistantError("Failed to set AC charge SOC limit")

            _LOGGER.info(
                "Successfully set AC Charge SOC Limit for %s to %d%%",
                self.serial,
                int_value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "AC Charge SOC Limit changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error(
                "Invalid AC Charge SOC Limit value for %s: %s", self.serial, e
            )
            raise HomeAssistantError(str(e)) from e
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "On-Grid SOC Cut-Off"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_on_grid_soc_cutoff"

        # Number configuration for On-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created On-Grid SOC Cut-Off number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current on-grid SOC cutoff value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            if hasattr(inverter, "battery_soc_limits") and inverter.battery_soc_limits:
                soc_cutoff = inverter.battery_soc_limits.get("on_grid_limit")
                if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                    return int(soc_cutoff)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting on-grid SOC cutoff for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid SOC cutoff value."""
        try:
            int_value = int(value)
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

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use inverter device object's convenience method
            success = await inverter.set_battery_soc_limits(on_grid_limit=int_value)

            if not success:
                raise HomeAssistantError(
                    f"Failed to set on-grid SOC cutoff to {int_value}%"
                )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters when any parameter changes
            _LOGGER.info(
                "On-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            # Create background task to refresh all device parameters and then update
            # all SOC entities
            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

            _LOGGER.info(
                "Successfully set On-Grid SOC Cut-Off for %s to %d%%",
                self.serial,
                int_value,
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
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
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Off-Grid SOC Cut-Off"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_off_grid_soc_cutoff"

        # Number configuration for Off-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created Off-Grid SOC Cut-Off number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current off-grid SOC cutoff value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            if hasattr(inverter, "battery_soc_limits") and inverter.battery_soc_limits:
                soc_cutoff = inverter.battery_soc_limits.get("off_grid_limit")
                if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                    return int(soc_cutoff)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting off-grid SOC cutoff for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid SOC cutoff value."""
        try:
            int_value = int(value)
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

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use inverter device object's convenience method
            success = await inverter.set_battery_soc_limits(off_grid_limit=int_value)

            if not success:
                raise HomeAssistantError(
                    f"Failed to set off-grid SOC cutoff to {int_value}%"
                )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters when any parameter changes
            _LOGGER.info(
                "Off-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            # Create background task to refresh all device parameters and then update
            # all SOC entities
            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

            _LOGGER.info(
                "Successfully set Off-Grid SOC Cut-Off for %s to %d%%",
                self.serial,
                int_value,
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class BatteryChargeCurrentNumber(CoordinatorEntity, NumberEntity):
    """Number entity for Battery Charge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Battery Charge Current"
        self._attr_unique_id = f"{clean_model}_{serial.lower()}_battery_charge_current"

        # Number configuration for Battery Charge Current (0-250 A)
        # Based on typical battery charge current ranges for EG4 inverters
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-plus"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created Battery Charge Current number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current battery charge current value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            current_limit = inverter.battery_charge_current_limit
            if current_limit is not None and 0 <= current_limit <= 250:
                return int(current_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting battery charge current for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery charge current value using device object method."""
        try:
            int_value = int(value)
            if int_value < 0 or int_value > 250:
                raise ValueError(
                    f"Battery charge current must be between 0-250 A, got {int_value}"
                )

            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"Battery charge current must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting Battery Charge Current for %s to %d A", self.serial, int_value
            )

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_battery_charge_current(current_amps=int_value)
            if not success:
                raise HomeAssistantError("Failed to set battery charge current")

            _LOGGER.info(
                "Successfully set Battery Charge Current for %s to %d A",
                self.serial,
                int_value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "Battery Charge Current changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error(
                "Invalid Battery Charge Current value for %s: %s", self.serial, e
            )
            raise HomeAssistantError(str(e)) from e
        except Exception as e:
            _LOGGER.error(
                "Failed to set Battery Charge Current for %s: %s", self.serial, e
            )
            raise HomeAssistantError(
                f"Failed to set battery charge current: {e}"
            ) from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all current limit entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()

            platform = self.platform
            if platform is not None:
                current_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(
                        entity,
                        (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber),
                    )
                ]

                _LOGGER.info(
                    "Updating %d current limit entities after parameter refresh",
                    len(current_entities),
                )

                update_tasks = []
                for entity in current_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class BatteryDischargeCurrentNumber(CoordinatorEntity, NumberEntity):
    """Number entity for Battery Discharge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: EG4DataUpdateCoordinator = coordinator
        self.serial = serial

        # Get device info
        device_data = coordinator.data.get("devices", {}).get(serial, {})
        model = device_data.get("model", "Unknown")

        # Entity configuration
        clean_model = clean_model_name(model, use_underscores=True)

        # Modern entity naming - let Home Assistant combine device name + entity name
        self._attr_has_entity_name = True
        self._attr_name = "Battery Discharge Current"
        self._attr_unique_id = (
            f"{clean_model}_{serial.lower()}_battery_discharge_current"
        )

        # Number configuration for Battery Discharge Current (0-250 A)
        # Based on typical battery discharge current ranges for EG4 inverters
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:battery-minus"
        self._attr_native_precision = 0
        self._attr_entity_category = EntityCategory.CONFIG

        # Device info
        self._attr_device_info = cast("DeviceInfo", coordinator.get_device_info(serial))

        # Current value
        self._current_value: float | None = None

        _LOGGER.debug("Created Battery Discharge Current number entity for %s", serial)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        """Return the current battery discharge current value from device object."""
        try:
            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                return None

            # Use device object property (cached by library)
            current_limit = inverter.battery_discharge_current_limit
            if current_limit is not None and 0 <= current_limit <= 250:
                return int(current_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting battery discharge current for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery discharge current value using device object method."""
        try:
            int_value = int(value)
            if int_value < 0 or int_value > 250:
                raise ValueError(
                    f"Battery discharge current must be between 0-250 A, got {int_value}"
                )

            if abs(value - int_value) > 0.01:
                raise ValueError(
                    f"Battery discharge current must be an integer value, got {value}"
                )

            _LOGGER.info(
                "Setting Battery Discharge Current for %s to %d A",
                self.serial,
                int_value,
            )

            # Get inverter device object
            inverter = self.coordinator.get_inverter_object(self.serial)
            if not inverter:
                raise HomeAssistantError(f"Inverter {self.serial} not found")

            # Use device object convenience method
            success = await inverter.set_battery_discharge_current(
                current_amps=int_value
            )
            if not success:
                raise HomeAssistantError("Failed to set battery discharge current")

            _LOGGER.info(
                "Successfully set Battery Discharge Current for %s to %d A",
                self.serial,
                int_value,
            )

            # Update the stored value
            self._current_value = value
            self.async_write_ha_state()

            # Refresh inverter data
            await inverter.refresh()

            # Trigger parameter refresh for all inverters
            _LOGGER.info(
                "Battery Discharge Current changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            self.hass.async_create_task(self._refresh_all_parameters_and_entities())

        except ValueError as e:
            _LOGGER.error(
                "Invalid Battery Discharge Current value for %s: %s", self.serial, e
            )
            raise HomeAssistantError(str(e)) from e
        except Exception as e:
            _LOGGER.error(
                "Failed to set Battery Discharge Current for %s: %s", self.serial, e
            )
            raise HomeAssistantError(
                f"Failed to set battery discharge current: {e}"
            ) from e

    async def _refresh_all_parameters_and_entities(self) -> None:
        """Refresh parameters for all inverters and update all current limit entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()

            platform = self.platform
            if platform is not None:
                current_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(
                        entity,
                        (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber),
                    )
                ]

                _LOGGER.info(
                    "Updating %d current limit entities after parameter refresh",
                    len(current_entities),
                )

                update_tasks = []
                for entity in current_entities:
                    task = entity.async_update()
                    update_tasks.append(task)

                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
