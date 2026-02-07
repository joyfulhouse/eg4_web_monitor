"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
from abc import abstractmethod
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

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
    """Base class for EG4 number entities with shared read/write helpers.

    Provides _read_param_value() for the common multi-tier parameter read
    pattern and _write_parameter() for local/cloud parameter write routing.
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
        """Return tuple of related entity types for parameter refresh."""

    # ── Value read helpers ──────────────────────────────────────────

    def _value_from_params(
        self,
        param_key: str,
        value_min: float,
        value_max: float,
        param_transform: Callable[[Any], float] | None,
    ) -> float | None:
        """Extract numeric value from coordinator parameter data."""
        params = self._parameter_data
        if not params:
            return None
        raw = params.get(param_key)
        if raw is None:
            return None
        val = param_transform(raw) if param_transform else float(raw)
        if value_min <= val <= value_max:
            return val
        return None

    def _value_from_inverter(
        self,
        inverter_attr: str | None,
        dict_attr: str | None,
        dict_key: str | None,
        value_min: float,
        value_max: float,
    ) -> float | None:
        """Extract numeric value from inverter object attribute or dict."""
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            return None
        val: Any
        if dict_attr and dict_key:
            container = getattr(inverter, dict_attr, None)
            if not container:
                return None
            val = container.get(dict_key)
        elif inverter_attr:
            val = getattr(inverter, inverter_attr, None)
        else:
            return None
        if val is None:
            return None
        fval = float(val)
        if value_min <= fval <= value_max:
            return fval
        return None

    def _read_param_value(
        self,
        *,
        param_key: str,
        value_min: float,
        value_max: float,
        inverter_attr: str | None = None,
        inverter_dict_attr: str | None = None,
        inverter_dict_key: str | None = None,
        as_float: bool = False,
        precision: int = 1,
        param_transform: Callable[[Any], float] | None = None,
        params_first: bool = False,
    ) -> float | None:
        """Read parameter with standard multi-tier lookup.

        Standard order: optimistic -> local params -> inverter -> param fallback.
        With params_first: optimistic -> local params -> params -> inverter.
        """
        if self._optimistic_value is not None:
            if as_float:
                return float(round(self._optimistic_value, precision))
            return int(self._optimistic_value)

        def _fmt(raw: float | None) -> float | None:
            if raw is None:
                return None
            if as_float:
                return float(round(raw, precision))
            return int(raw)

        try:
            if self.coordinator.is_local_only():
                return _fmt(
                    self._value_from_params(
                        param_key, value_min, value_max, param_transform
                    )
                )

            if params_first:
                result = _fmt(
                    self._value_from_params(
                        param_key, value_min, value_max, param_transform
                    )
                )
                if result is not None:
                    return result
                return _fmt(
                    self._value_from_inverter(
                        inverter_attr,
                        inverter_dict_attr,
                        inverter_dict_key,
                        value_min,
                        value_max,
                    )
                )

            result = _fmt(
                self._value_from_inverter(
                    inverter_attr,
                    inverter_dict_attr,
                    inverter_dict_key,
                    value_min,
                    value_max,
                )
            )
            if result is not None:
                return result
            return _fmt(
                self._value_from_params(
                    param_key, value_min, value_max, param_transform
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    # ── Value write helpers ─────────────────────────────────────────

    async def _write_parameter(
        self,
        value: float,
        *,
        local_param: str,
        local_value: int | float | None = None,
        cloud_method: str,
        cloud_kwargs: dict[str, Any],
        label: str,
    ) -> None:
        """Write parameter via local transport or cloud API with optimistic context."""
        _LOGGER.info("Setting %s for %s", label, self.serial)
        with optimistic_value_context(self, value):
            if self.coordinator.has_local_transport(self.serial):
                write_val = local_value if local_value is not None else int(value)
                await self.coordinator.write_named_parameter(
                    local_param, write_val, serial=self.serial
                )
                await asyncio.sleep(0.5)
            else:
                inverter = self._get_inverter_or_raise()
                success = await getattr(inverter, cloud_method)(**cloud_kwargs)
                if not success:
                    raise HomeAssistantError(f"Failed to set {label}")
                await inverter.refresh()
            await self._refresh_related_entities()

    async def _refresh_related_entities(self) -> None:
        """Refresh parameters for all inverters and update related entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()
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
                update_tasks = [
                    entity.async_update()  # type: ignore[attr-defined]
                    for entity in related_entities
                ]
                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)


# ── Platform setup ───────────────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor number entities from a config entry."""
    coordinator = config_entry.runtime_data
    entities: list[NumberEntity] = []

    for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
        device_type = device_data.get("type")
        if device_type == "inverter":
            model = device_data.get("model", "Unknown")
            model_lower = model.lower()

            supported_models = ["flexboss", "18kpv", "18k", "12kpv", "12k", "xp"]
            if any(supported in model_lower for supported in supported_models):
                entities.extend(
                    [
                        SystemChargeSOCLimitNumber(coordinator, serial),
                        ACChargePowerNumber(coordinator, serial),
                        PVChargePowerNumber(coordinator, serial),
                        ACChargeSOCLimitNumber(coordinator, serial),
                        OnGridSOCCutoffNumber(coordinator, serial),
                        OffGridSOCCutoffNumber(coordinator, serial),
                        BatteryChargeCurrentNumber(coordinator, serial),
                        BatteryDischargeCurrentNumber(coordinator, serial),
                        GridPeakShavingPowerNumber(coordinator, serial),
                    ]
                )

    if entities:
        _LOGGER.info("Setup complete: %d number entities created", len(entities))
        async_add_entities(entities, update_before_add=False)


# ── Entity classes ───────────────────────────────────────────────────


class SystemChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for System Charge SOC Limit control (register 227).

    Values 10-100%: stop charging at this SOC.  101%: enable top balancing.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "System Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_system_charge_soc_limit"
        )
        self._attr_native_min_value = SYSTEM_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (SystemChargeSOCLimitNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current System Charge SOC limit (reads params first)."""
        return self._read_param_value(
            param_key="HOLD_SYSTEM_CHARGE_SOC_LIMIT",
            value_min=10,
            value_max=101,
            inverter_attr="system_charge_soc_limit",
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the System Charge SOC limit (3-way: local, cloud API, or client)."""
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
            if self.coordinator.has_local_transport(self.serial):
                await self.coordinator.write_named_parameter(
                    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT, int_value, serial=self.serial
                )
            elif self.coordinator.client is not None:
                result = await self.coordinator.client.api.control.set_system_charge_soc_limit(
                    self.serial, int_value
                )
                if not result.success:
                    raise HomeAssistantError(f"Failed to set SOC limit to {int_value}%")
                inverter = self.coordinator.get_inverter_object(self.serial)
                if inverter:
                    await inverter.refresh(force=True, include_parameters=True)
            else:
                raise HomeAssistantError(
                    "No local transport or cloud API available for parameter write."
                )
            await self._refresh_related_entities()


class ACChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge Power control (stored as 100W units)."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_ac_charge_power"
        self._attr_native_min_value = AC_CHARGE_POWER_MIN
        self._attr_native_max_value = AC_CHARGE_POWER_MAX
        self._attr_native_step = AC_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge power (param in 100W units -> kW)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_POWER,
            value_min=0,
            value_max=15,
            inverter_attr="ac_charge_power_limit",
            as_float=True,
            param_transform=lambda v: float(v) / 10.0,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge power (converts kW to 100W units for register)."""
        if value < 0.0 or value > 15.0:
            raise HomeAssistantError(
                f"AC charge power must be between 0.0-15.0 kW, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_POWER,
            local_value=int(value * 10),
            cloud_method="set_ac_charge_power",
            cloud_kwargs={"power_kw": value},
            label=f"AC charge power to {value:.1f} kW",
        )


class PVChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for PV Charge Power control (stored as percentage)."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "PV Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_pv_charge_power"
        self._attr_native_min_value = PV_CHARGE_POWER_MIN
        self._attr_native_max_value = PV_CHARGE_POWER_MAX
        self._attr_native_step = PV_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current PV charge power (percentage -> kW, params-first).

        Reads params first (fresher). Inverter fallback rejects 0 (means unset).
        """
        if self._optimistic_value is not None:
            return int(self._optimistic_value)

        try:

            def _pct_to_kw(pct_value: Any) -> int | None:
                power_kw = int(float(pct_value) / 100.0 * 15)
                return power_kw if 0 <= power_kw <= 15 else None

            if self.coordinator.is_local_only():
                params = self._parameter_data
                if params:
                    pct = params.get(PARAM_HOLD_CHG_POWER_PERCENT)
                    if pct is not None:
                        return _pct_to_kw(pct)
                return None

            # HTTP/Hybrid: params first (fresh every cycle)
            params = self._parameter_data
            if params:
                pct = params.get(PARAM_HOLD_CHG_POWER_PERCENT)
                if pct is not None:
                    result = _pct_to_kw(pct)
                    if result is not None:
                        return result

            # Fall back to inverter (rejects 0 as "no limit set")
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                pl = inverter.pv_charge_power_limit
                if pl is not None and 0 < pl <= 15:
                    return int(pl)
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV charge power (converts kW to percentage for register)."""
        int_value = int(value)
        if int_value < 0 or int_value > 15:
            raise HomeAssistantError(
                f"PV charge power must be between 0-15 kW, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"PV charge power must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_CHG_POWER_PERCENT,
            local_value=int(int_value / 15.0 * 100),
            cloud_method="set_pv_charge_power",
            cloud_kwargs={"power_kw": int_value},
            label=f"PV charge power to {int_value} kW",
        )


class GridPeakShavingPowerNumber(EG4BaseNumberEntity):
    """Number entity for Grid Peak Shaving Power control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Grid Peak Shaving Power"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_grid_peak_shaving_power"
        )
        self._attr_native_min_value = GRID_PEAK_SHAVING_POWER_MIN
        self._attr_native_max_value = GRID_PEAK_SHAVING_POWER_MAX
        self._attr_native_step = GRID_PEAK_SHAVING_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (GridPeakShavingPowerNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current grid peak shaving power."""
        return self._read_param_value(
            param_key="_12K_HOLD_GRID_PEAK_SHAVING_POWER",
            value_min=0,
            value_max=25.5,
            inverter_attr="grid_peak_shaving_power_limit",
            as_float=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid peak shaving power."""
        if value < 0.0 or value > 25.5:
            raise HomeAssistantError(
                f"Grid peak shaving power must be between 0.0-25.5 kW, got {value}"
            )
        await self._write_parameter(
            value,
            local_param="_12K_HOLD_GRID_PEAK_SHAVING_POWER",
            local_value=value,
            cloud_method="set_grid_peak_shaving_power",
            cloud_kwargs={"power_kw": value},
            label=f"grid peak shaving power to {value:.1f} kW",
        )


class ACChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge SOC Limit control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_soc_limit"
        )
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge SOC limit."""
        return self._read_param_value(
            param_key="HOLD_AC_CHARGE_SOC_LIMIT",
            value_min=0,
            value_max=100,
            inverter_attr="ac_charge_soc_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge SOC limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"AC charge SOC limit must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge SOC limit must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
            cloud_method="set_ac_charge_soc_limit",
            cloud_kwargs={"soc_percent": int_value},
            label=f"AC charge SOC limit to {int_value}%",
        )


class OnGridSOCCutoffNumber(EG4BaseNumberEntity):
    """Number entity for On-Grid SOC Cut-Off control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "On-Grid SOC Cut-Off"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_on_grid_soc_cutoff"
        )
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current on-grid SOC cutoff (reads from battery_soc_limits dict)."""
        return self._read_param_value(
            param_key="HOLD_DISCHG_CUT_OFF_SOC_EOD",
            value_min=0,
            value_max=100,
            inverter_dict_attr="battery_soc_limits",
            inverter_dict_key="on_grid_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid SOC cutoff."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_ONGRID_DISCHG_SOC,
            cloud_method="set_battery_soc_limits",
            cloud_kwargs={"on_grid_limit": int_value},
            label=f"on-grid SOC cutoff to {int_value}%",
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
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current off-grid SOC cutoff (reads from battery_soc_limits dict)."""
        return self._read_param_value(
            param_key="HOLD_SOC_LOW_LIMIT_EPS_DISCHG",
            value_min=0,
            value_max=100,
            inverter_dict_attr="battery_soc_limits",
            inverter_dict_key="off_grid_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid SOC cutoff."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_OFFGRID_DISCHG_SOC,
            cloud_method="set_battery_soc_limits",
            cloud_kwargs={"off_grid_limit": int_value},
            label=f"off-grid SOC cutoff to {int_value}%",
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
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-plus"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current battery charge current limit."""
        return self._read_param_value(
            param_key="HOLD_LEAD_ACID_CHARGE_RATE",
            value_min=0,
            value_max=250,
            inverter_attr="battery_charge_current_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery charge current limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery charge current must be between 0-250 A, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Battery charge current must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_CHARGE_CURRENT,
            cloud_method="set_battery_charge_current",
            cloud_kwargs={"current_amps": int_value},
            label=f"battery charge current to {int_value} A",
        )


class BatteryDischargeCurrentNumber(EG4BaseNumberEntity):
    """Number entity for Battery Discharge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Battery Discharge Current"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_battery_discharge_current"
        )
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-minus"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current battery discharge current limit."""
        return self._read_param_value(
            param_key="HOLD_LEAD_ACID_DISCHARGE_RATE",
            value_min=0,
            value_max=250,
            inverter_attr="battery_discharge_current_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery discharge current limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery discharge current must be between 0-250 A, got {int_value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_DISCHARGE_CURRENT,
            cloud_method="set_battery_discharge_current",
            cloud_kwargs={"current_amps": int_value},
            label=f"battery discharge current to {int_value} A",
        )
