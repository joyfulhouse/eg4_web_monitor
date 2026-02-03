"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
from abc import abstractmethod
from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.number import NumberEntity, NumberMode
else:
    from homeassistant.components.number import NumberEntity, NumberMode

from . import EG4ConfigEntry
from .base_entity import EG4BaseNumber, optimistic_value_context
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
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
    PARAM_HOLD_CHARGE_CURRENT,
    PARAM_HOLD_CHG_POWER_PERCENT,
    PARAM_HOLD_DISCHARGE_CURRENT,
    PARAM_HOLD_OFFGRID_DISCHG_SOC,
    PARAM_HOLD_ONGRID_DISCHG_SOC,
    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT,
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

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


class EG4BaseNumberEntity(EG4BaseNumber, NumberEntity):
    """Base class for EG4 number entities with common functionality.

    This base class extends EG4BaseNumber with NumberEntity functionality:
    - NumberEntity integration
    - Common entity attributes
    - Parameter refresh logic with related entity updates

    Uses optimistic_value_context for proper cleanup of optimistic values.
    """

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base number entity."""
        super().__init__(coordinator, serial)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @abstractmethod
    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return tuple of related entity types for parameter refresh.

        Override in subclass to specify which entity types should be
        updated when this entity's value changes.
        """

    async def _refresh_related_entities(self) -> None:
        """Refresh parameters for all inverters and update related entities."""
        try:
            # First refresh all device parameters
            await self.coordinator.refresh_all_device_parameters()

            # Get related entities from the platform
            platform = self.platform
            if platform is not None:
                related_types = self._get_related_entity_types()
                related_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, related_types)
                ]

                _LOGGER.info(
                    "Updating %d related entities after parameter refresh",
                    len(related_entities),
                )

                # Update all related entities
                update_tasks = [
                    entity.async_update()  # type: ignore[attr-defined]
                    for entity in related_entities
                ]

                # Execute all entity updates concurrently
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # Trigger coordinator refresh for general data
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)


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
                # Entities with Modbus register support (work in all modes)
                entities.append(SystemChargeSOCLimitNumber(coordinator, serial))
                entities.append(ACChargePowerNumber(coordinator, serial))
                entities.append(PVChargePowerNumber(coordinator, serial))
                entities.append(ACChargeSOCLimitNumber(coordinator, serial))
                entities.append(OnGridSOCCutoffNumber(coordinator, serial))
                entities.append(OffGridSOCCutoffNumber(coordinator, serial))
                entities.append(BatteryChargeCurrentNumber(coordinator, serial))
                entities.append(BatteryDischargeCurrentNumber(coordinator, serial))

                # Grid peak shaving power (available in all modes)
                entities.append(GridPeakShavingPowerNumber(coordinator, serial))

                entity_count = 9
                _LOGGER.debug(
                    "Created %d number entities for device %s (%s)",
                    entity_count,
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


class SystemChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for System Charge SOC Limit control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "System Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_system_charge_soc_limit"
        )

        # Number configuration for SOC limit (10-101%) - integer only
        self._attr_native_min_value = SYSTEM_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 0

        _LOGGER.debug("Created System Charge SOC Limit number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for SOC limit updates."""
        return (SystemChargeSOCLimitNumber,)

    @property
    def native_value(self) -> int | None:
        """Return the current System Charge SOC limit from cached parameters.

        This reads HOLD_SYSTEM_CHARGE_SOC_LIMIT (register 227) which controls
        when the battery stops charging:
        - 0-100%: Stop charging when battery reaches this SOC
        - 101%: Enable top balancing (full charge with cell balancing)
        """
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    soc_limit = params.get("HOLD_SYSTEM_CHARGE_SOC_LIMIT")
                    if soc_limit is not None:
                        soc_limit = int(soc_limit)  # May be string from transport
                        if 10 <= soc_limit <= 101:
                            return soc_limit
                return None

            # HTTP/Hybrid mode: try local parameters first (fresh every cycle)
            params = self._parameter_data
            if params:
                soc_limit = params.get("HOLD_SYSTEM_CHARGE_SOC_LIMIT")
                if soc_limit is not None:
                    soc_limit = int(soc_limit)  # API may return string
                    if 10 <= soc_limit <= 101:
                        return soc_limit

            # Fall back to inverter object (HTTP API)
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                soc_limit = inverter.system_charge_soc_limit
                if soc_limit is not None:
                    soc_limit = int(soc_limit)  # API may return string
                    if 10 <= soc_limit <= 101:
                        return soc_limit

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting System Charge SOC limit for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the System Charge SOC limit.

        Supports both HTTP API and local Modbus (register 227).

        Args:
            value: Target SOC limit (10-101%)
                - 10-100: Stop charging when battery reaches this SOC
                - 101: Enable top balancing (full charge with cell balancing)
        """
        int_value = int(value)
        if int_value < 10 or int_value > 101:
            raise HomeAssistantError(
                f"SOC limit must be an integer between 10-101%, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(f"SOC limit must be an integer value, got {value}")

        _LOGGER.info(
            "Setting System Charge SOC Limit for %s to %d%%", self.serial, int_value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available (works for local, hybrid, or any mode)
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing System Charge SOC Limit via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT, int_value, serial=self.serial
                )
            elif self.coordinator.client is not None:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing System Charge SOC Limit via CLOUD API for %s",
                    self.serial,
                )
                result = await self.coordinator.client.api.control.set_system_charge_soc_limit(
                    self.serial, int_value
                )

                if not result.success:
                    raise HomeAssistantError(f"Failed to set SOC limit to {int_value}%")

                # Refresh inverter parameters to update cached value
                inverter = self.coordinator.get_inverter_object(self.serial)
                if inverter:
                    await inverter.refresh(force=True, include_parameters=True)
            else:
                raise HomeAssistantError(
                    "No local transport or cloud API available for parameter write."
                )

            _LOGGER.info(
                "Parameter changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            # Refresh related entities (runs inside context for immediate feedback)
            await self._refresh_related_entities()

            _LOGGER.info(
                "Successfully set System Charge SOC Limit for %s to %d%%",
                self.serial,
                int_value,
            )


class ACChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge Power control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "AC Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_ac_charge_power"

        # Number configuration for AC Charge Power (0-15 kW)
        # Supports decimal values (0.1 kW step) to match EG4 web interface
        self._attr_native_min_value = AC_CHARGE_POWER_MIN
        self._attr_native_max_value = AC_CHARGE_POWER_MAX
        self._attr_native_step = AC_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1

        _LOGGER.debug("Created AC Charge Power number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for charge power updates."""
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge power value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return float(round(self._optimistic_value, 1))

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    raw_value = params.get(PARAM_HOLD_AC_CHARGE_POWER)
                    if raw_value is not None:
                        # Convert 100W units to kW (120 → 12.0 kW)
                        power_kw = float(raw_value) / 10.0
                        if 0 <= power_kw <= 15:
                            return float(round(power_kw, 1))
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                power_limit = inverter.ac_charge_power_limit
                if power_limit is not None and 0 <= power_limit <= 15:
                    return float(round(power_limit, 1))

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                raw_value = params.get(PARAM_HOLD_AC_CHARGE_POWER)
                if raw_value is not None:
                    power_kw = float(raw_value) / 10.0
                    if 0 <= power_kw <= 15:
                        return float(round(power_kw, 1))

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting AC charge power for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge power value using device object method or Modbus."""
        if value < 0.0 or value > 15.0:
            raise HomeAssistantError(
                f"AC charge power must be between 0.0-15.0 kW, got {value}"
            )

        _LOGGER.info("Setting AC Charge Power for %s to %.1f kW", self.serial, value)

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing AC Charge Power via LOCAL transport for %s", self.serial
                )
                register_value = int(value * 10)
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_AC_CHARGE_POWER, register_value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set AC Charge Power for %s to %.1f kW (%s = %d)",
                    self.serial,
                    value,
                    PARAM_HOLD_AC_CHARGE_POWER,
                    register_value,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing AC Charge Power via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_ac_charge_power(power_kw=value)
                if not success:
                    raise HomeAssistantError("Failed to set AC charge power")

                _LOGGER.info(
                    "Successfully set AC Charge Power for %s to %.1f kW",
                    self.serial,
                    value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "AC Charge Power changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            await self._refresh_related_entities()


class PVChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for PV Charge Power control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "PV Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_pv_charge_power"

        # Number configuration for PV Charge Power (0-15 kW)
        self._attr_native_min_value = PV_CHARGE_POWER_MIN
        self._attr_native_max_value = PV_CHARGE_POWER_MAX
        self._attr_native_step = PV_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0

        _LOGGER.debug("Created PV Charge Power number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for charge power updates."""
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current PV charge power value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    pct_value = params.get(PARAM_HOLD_CHG_POWER_PERCENT)
                    if pct_value is not None:
                        # Convert percentage to kW (100% = 15 kW)
                        power_kw = int(float(pct_value) / 100.0 * 15)
                        if 0 <= power_kw <= 15:
                            return power_kw
                return None

            # HTTP/Hybrid mode: try local parameters first (fresh every cycle)
            params = self._parameter_data
            if params:
                pct_value = params.get(PARAM_HOLD_CHG_POWER_PERCENT)
                if pct_value is not None:
                    power_kw = int(float(pct_value) / 100.0 * 15)
                    if 0 <= power_kw <= 15:
                        return power_kw

            # Fall back to inverter object (HTTP API)
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                power_limit = inverter.pv_charge_power_limit
                if power_limit is not None and 0 < power_limit <= 15:
                    return int(power_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting PV charge power for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV charge power value using device object method or Modbus."""
        int_value = int(value)
        if int_value < 0 or int_value > 15:
            raise HomeAssistantError(
                f"PV charge power must be between 0-15 kW, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"PV charge power must be an integer value, got {value}"
            )

        _LOGGER.info("Setting PV Charge Power for %s to %d kW", self.serial, int_value)

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing PV Charge Power via LOCAL transport for %s", self.serial
                )
                # Parameter expects percentage (0-100%) where 100% = 15kW
                register_value = int(int_value / 15.0 * 100)
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_CHG_POWER_PERCENT, register_value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set PV Charge Power for %s to %d kW (%s = %d%%)",
                    self.serial,
                    int_value,
                    PARAM_HOLD_CHG_POWER_PERCENT,
                    register_value,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing PV Charge Power via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_pv_charge_power(power_kw=int_value)
                if not success:
                    raise HomeAssistantError("Failed to set PV charge power")

                _LOGGER.info(
                    "Successfully set PV Charge Power for %s to %d kW",
                    self.serial,
                    int_value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "PV Charge Power changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            await self._refresh_related_entities()


class GridPeakShavingPowerNumber(EG4BaseNumberEntity):
    """Number entity for Grid Peak Shaving Power control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "Grid Peak Shaving Power"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_grid_peak_shaving_power"
        )

        # Number configuration for Grid Peak Shaving Power (0.0-25.5 kW)
        self._attr_native_min_value = GRID_PEAK_SHAVING_POWER_MIN
        self._attr_native_max_value = GRID_PEAK_SHAVING_POWER_MAX
        self._attr_native_step = GRID_PEAK_SHAVING_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_native_precision = 1

        _LOGGER.debug("Created Grid Peak Shaving Power number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for peak shaving power updates."""
        return (GridPeakShavingPowerNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current grid peak shaving power value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return float(round(self._optimistic_value, 1))

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    power_limit = params.get("_12K_HOLD_GRID_PEAK_SHAVING_POWER")
                    if power_limit is not None:
                        power_kw = float(power_limit)
                        if 0 <= power_kw <= 25.5:
                            return float(round(power_kw, 1))
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                power_limit = inverter.grid_peak_shaving_power_limit
                if power_limit is not None and 0 <= power_limit <= 25.5:
                    return float(round(power_limit, 1))

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                power_limit = params.get("_12K_HOLD_GRID_PEAK_SHAVING_POWER")
                if power_limit is not None:
                    power_kw = float(power_limit)
                    if 0 <= power_kw <= 25.5:
                        return float(round(power_kw, 1))

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting grid peak shaving power for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid peak shaving power value using device object method or register."""
        if value < 0.0 or value > 25.5:
            raise HomeAssistantError(
                f"Grid peak shaving power must be between 0.0-25.5 kW, got {value}"
            )

        _LOGGER.info(
            "Setting Grid Peak Shaving Power for %s to %.1f kW", self.serial, value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing Grid Peak Shaving Power via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    "_12K_HOLD_GRID_PEAK_SHAVING_POWER", value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set Grid Peak Shaving Power for %s to %.1f kW (local)",
                    self.serial,
                    value,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing Grid Peak Shaving Power via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_grid_peak_shaving_power(power_kw=value)
                if not success:
                    raise HomeAssistantError("Failed to set grid peak shaving power")

                _LOGGER.info(
                    "Successfully set Grid Peak Shaving Power for %s to %.1f kW (HTTP)",
                    self.serial,
                    value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "Grid Peak Shaving Power changed for %s, refreshing parameters",
                self.serial,
            )

            await self._refresh_related_entities()


class ACChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge SOC Limit control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "AC Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_soc_limit"
        )

        # Number configuration for AC Charge SOC Limit (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0

        _LOGGER.debug("Created AC Charge SOC Limit number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for SOC limit updates."""
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current AC charge SOC limit value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    soc_limit = params.get("HOLD_AC_CHARGE_SOC_LIMIT")
                    if soc_limit is not None and 0 <= soc_limit <= 100:
                        return int(soc_limit)
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                soc_limit = inverter.ac_charge_soc_limit
                if soc_limit is not None and 0 <= soc_limit <= 100:
                    return int(soc_limit)

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                soc_limit = params.get("HOLD_AC_CHARGE_SOC_LIMIT")
                if soc_limit is not None and 0 <= soc_limit <= 100:
                    return int(soc_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting AC charge SOC limit for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge SOC limit value using device object method or Modbus."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"AC charge SOC limit must be between 0-100%, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge SOC limit must be an integer value, got {value}"
            )

        _LOGGER.info(
            "Setting AC Charge SOC Limit for %s to %d%%", self.serial, int_value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing AC Charge SOC Limit via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_AC_CHARGE_SOC_LIMIT, int_value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set AC Charge SOC Limit for %s to %d%% (%s)",
                    self.serial,
                    int_value,
                    PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing AC Charge SOC Limit via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_ac_charge_soc_limit(soc_percent=int_value)
                if not success:
                    raise HomeAssistantError("Failed to set AC charge SOC limit")

                _LOGGER.info(
                    "Successfully set AC Charge SOC Limit for %s to %d%%",
                    self.serial,
                    int_value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "AC Charge SOC Limit changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            await self._refresh_related_entities()


class OnGridSOCCutoffNumber(EG4BaseNumberEntity):
    """Number entity for On-Grid SOC Cut-Off control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "On-Grid SOC Cut-Off"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_on_grid_soc_cutoff"
        )

        # Number configuration for On-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0

        _LOGGER.debug("Created On-Grid SOC Cut-Off number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for SOC cutoff updates."""
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current on-grid SOC cutoff value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    soc_cutoff = params.get("HOLD_DISCHG_CUT_OFF_SOC_EOD")
                    if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                        return int(soc_cutoff)
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                if (
                    hasattr(inverter, "battery_soc_limits")
                    and inverter.battery_soc_limits
                ):
                    soc_cutoff = inverter.battery_soc_limits.get("on_grid_limit")
                    if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                        return int(soc_cutoff)

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                soc_cutoff = params.get("HOLD_DISCHG_CUT_OFF_SOC_EOD")
                if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                    return int(soc_cutoff)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Error getting on-grid SOC cutoff for %s: %s", self.serial, e)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid SOC cutoff value using device object method or Modbus."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be between 0-100%, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be an integer value, got {value}"
            )

        _LOGGER.info(
            "Setting On-Grid SOC Cut-Off for %s to %d%%", self.serial, int_value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing On-Grid SOC Cut-Off via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_ONGRID_DISCHG_SOC, int_value, serial=self.serial
                )
                _LOGGER.info(
                    "Wrote On-Grid SOC Cut-Off via %s = %d%%",
                    PARAM_HOLD_ONGRID_DISCHG_SOC,
                    int_value,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing On-Grid SOC Cut-Off via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_battery_soc_limits(on_grid_limit=int_value)

                if not success:
                    raise HomeAssistantError(
                        f"Failed to set on-grid SOC cutoff to {int_value}%"
                    )

                await inverter.refresh()

            _LOGGER.info(
                "On-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            await self._refresh_related_entities()

            _LOGGER.info(
                "Successfully set On-Grid SOC Cut-Off for %s to %d%%",
                self.serial,
                int_value,
            )


class OffGridSOCCutoffNumber(EG4BaseNumberEntity):
    """Number entity for Off-Grid SOC Cut-Off control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "Off-Grid SOC Cut-Off"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_off_grid_soc_cutoff"
        )

        # Number configuration for Off-Grid SOC Cut-Off (0-100%)
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0

        _LOGGER.debug("Created Off-Grid SOC Cut-Off number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for SOC cutoff updates."""
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current off-grid SOC cutoff value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    soc_cutoff = params.get("HOLD_SOC_LOW_LIMIT_EPS_DISCHG")
                    if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                        return int(soc_cutoff)
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                if (
                    hasattr(inverter, "battery_soc_limits")
                    and inverter.battery_soc_limits
                ):
                    soc_cutoff = inverter.battery_soc_limits.get("off_grid_limit")
                    if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                        return int(soc_cutoff)

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                soc_cutoff = params.get("HOLD_SOC_LOW_LIMIT_EPS_DISCHG")
                if soc_cutoff is not None and 0 <= soc_cutoff <= 100:
                    return int(soc_cutoff)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting off-grid SOC cutoff for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid SOC cutoff value using device object method or Modbus."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be between 0-100%, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be an integer value, got {value}"
            )

        _LOGGER.info(
            "Setting Off-Grid SOC Cut-Off for %s to %d%%", self.serial, int_value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing Off-Grid SOC Cut-Off via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_OFFGRID_DISCHG_SOC, int_value, serial=self.serial
                )
                _LOGGER.info(
                    "Wrote Off-Grid SOC Cut-Off via %s = %d%%",
                    PARAM_HOLD_OFFGRID_DISCHG_SOC,
                    int_value,
                )

                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing Off-Grid SOC Cut-Off via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_battery_soc_limits(
                    off_grid_limit=int_value
                )

                if not success:
                    raise HomeAssistantError(
                        f"Failed to set off-grid SOC cutoff to {int_value}%"
                    )

                await inverter.refresh()

            _LOGGER.info(
                "Off-Grid SOC Cut-Off changed for %s, refreshing parameters for all inverters",
                self.serial,
            )

            await self._refresh_related_entities()

            _LOGGER.info(
                "Successfully set Off-Grid SOC Cut-Off for %s to %d%%",
                self.serial,
                int_value,
            )


class BatteryChargeCurrentNumber(EG4BaseNumberEntity):
    """Number entity for Battery Charge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "Battery Charge Current"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_battery_charge_current"
        )

        # Number configuration for Battery Charge Current (0-250 A)
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-plus"
        self._attr_native_precision = 0

        _LOGGER.debug("Created Battery Charge Current number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for current limit updates."""
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current battery charge current value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    current_limit = params.get("HOLD_LEAD_ACID_CHARGE_RATE")
                    if current_limit is not None and 0 <= current_limit <= 250:
                        return int(current_limit)
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                current_limit = inverter.battery_charge_current_limit
                if current_limit is not None and 0 <= current_limit <= 250:
                    return int(current_limit)

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                current_limit = params.get("HOLD_LEAD_ACID_CHARGE_RATE")
                if current_limit is not None and 0 <= current_limit <= 250:
                    return int(current_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting battery charge current for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery charge current value using device object method or register."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery charge current must be between 0-250 A, got {int_value}"
            )

        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Battery charge current must be an integer value, got {value}"
            )

        _LOGGER.info(
            "Setting Battery Charge Current for %s to %d A", self.serial, int_value
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing Battery Charge Current via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_CHARGE_CURRENT, int_value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set Battery Charge Current for %s to %d A (%s)",
                    self.serial,
                    int_value,
                    PARAM_HOLD_CHARGE_CURRENT,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing Battery Charge Current via CLOUD API for %s", self.serial
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_battery_charge_current(
                    current_amps=int_value
                )
                if not success:
                    raise HomeAssistantError("Failed to set battery charge current")

                _LOGGER.info(
                    "Successfully set Battery Charge Current for %s to %d A (HTTP)",
                    self.serial,
                    int_value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "Battery Charge Current changed for %s, refreshing parameters",
                self.serial,
            )

            await self._refresh_related_entities()


class BatteryDischargeCurrentNumber(EG4BaseNumberEntity):
    """Number entity for Battery Discharge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)

        self._attr_name = "Battery Discharge Current"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_battery_discharge_current"
        )

        # Number configuration for Battery Discharge Current (0-250 A)
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-minus"
        self._attr_native_precision = 0

        _LOGGER.debug("Created Battery Discharge Current number entity for %s", serial)

    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return related entity types for current limit updates."""
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> int | None:
        """Return the current battery discharge current value from device object or parameters."""
        # Optimistic value takes precedence (set by context manager)
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:
            # Local-only mode: read from parameters only (no HTTP)
            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    current_limit = params.get("HOLD_LEAD_ACID_DISCHARGE_RATE")
                    if current_limit is not None and 0 <= current_limit <= 250:
                        return int(current_limit)
                return None

            # HTTP/Hybrid mode: try inverter object first
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                current_limit = inverter.battery_discharge_current_limit
                if current_limit is not None and 0 <= current_limit <= 250:
                    return int(current_limit)

            # Fallback to parameters for Hybrid mode
            params = self._parameter_data
            if params:
                current_limit = params.get("HOLD_LEAD_ACID_DISCHARGE_RATE")
                if current_limit is not None and 0 <= current_limit <= 250:
                    return int(current_limit)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug(
                "Error getting battery discharge current for %s: %s", self.serial, e
            )

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery discharge current value using device object method or register."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery discharge current must be between 0-250 A, got {int_value}"
            )

        _LOGGER.info(
            "Setting Battery Discharge Current for %s to %d A",
            self.serial,
            int_value,
        )

        with optimistic_value_context(self, value):
            # Prefer local transport if available
            if self.coordinator.has_local_transport(self.serial):
                _LOGGER.debug(
                    "Writing Battery Discharge Current via LOCAL transport for %s",
                    self.serial,
                )
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_DISCHARGE_CURRENT, int_value, serial=self.serial
                )
                _LOGGER.info(
                    "Successfully set Battery Discharge Current for %s to %d A (%s)",
                    self.serial,
                    int_value,
                    PARAM_HOLD_DISCHARGE_CURRENT,
                )
                await asyncio.sleep(0.5)
            else:
                # Fall back to cloud API
                _LOGGER.debug(
                    "Writing Battery Discharge Current via CLOUD API for %s",
                    self.serial,
                )
                inverter = self._get_inverter_or_raise()

                success = await inverter.set_battery_discharge_current(
                    current_amps=int_value
                )
                if not success:
                    raise HomeAssistantError("Failed to set battery discharge current")

                _LOGGER.info(
                    "Successfully set Battery Discharge Current for %s to %d A (HTTP)",
                    self.serial,
                    int_value,
                )

                await inverter.refresh()

            _LOGGER.info(
                "Battery Discharge Current changed for %s, refreshing parameters",
                self.serial,
            )

            await self._refresh_related_entities()
