"""GridBOSS smart port option entities (per-port portal settings).

Each Smart Port N device carries the settings the portal shows for its port
— enables, "based on", thresholds and time windows — as the entities in
``const.midbox.PORT_OPTION_SPECS`` (register layout and evidence in the
same module).

Local transports only: the values come from raw register reads over the
GridBOSS's local transport (LOCAL, or HYBRID with an attached dongle) and
are written back the same way (``write_midbox_options``). A GridBOSS without
a configured local transport gets none of these entities; the cloud has no
settings getter for them.

Availability mirrors the portal:

- **Port mode.** An entity belongs to one mode (Smart Load or AC Couple).
  The entity registry sync disables it while the port is in another mode,
  and it shows unavailable until the sync catches up.
- **Portal greying.** A field the portal greys out shows unavailable: the
  Smart Load time windows unless "based on" is Time, the shedding fields
  unless power shedding is on, and the SOC or voltage thresholds per the
  inverters' battery control regime (``GATE_*`` in const/midbox.py).
- **Local link.** A down local link, or a value never read, shows
  unavailable rather than a stale or fake value.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo

from .base_entity import (
    EG4BaseNumber,
    EG4BaseSelect,
    EG4BaseSwitch,
    EG4OptimisticEntity,
)
from .const import (
    DEVICE_TYPE_GRIDBOSS,
    PARAM_FUNC_BAT_CHARGE_CONTROL,
    PARAM_FUNC_BAT_DISCHARGE_CONTROL,
    SMART_LOAD_PV_POWER_MAX,
    SMART_LOAD_PV_POWER_MIN,
    SMART_LOAD_PV_POWER_STEP,
    SMART_LOAD_SOC_MAX,
    SMART_LOAD_SOC_MIN,
    SMART_LOAD_SOC_STEP,
    SMART_LOAD_VOLT_MAX,
    SMART_LOAD_VOLT_MIN,
    SMART_LOAD_VOLT_STEP,
)
from .const.midbox import (
    GATE_SHEDDING,
    GATE_SOC,
    GATE_TIME_BASED,
    GATE_VOLT,
    PORT_MODE_AC_COUPLE,
    SMART_LOAD_BASE_ON_SOC_VOLT,
    SMART_LOAD_BASE_ON_TIME,
    SMART_PORT_NUMBERS,
    PortOptionSpec,
    port_option_specs,
)
from .smart_port_devices import port_sensor_unique_id, resolve_port_mode

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

BASED_ON_TIME = "Time"
BASED_ON_SOC_VOLT = "SOC/Volt"
_BASED_ON_OPTIONS: dict[int, str] = {
    SMART_LOAD_BASE_ON_TIME: BASED_ON_TIME,
    SMART_LOAD_BASE_ON_SOC_VOLT: BASED_ON_SOC_VOLT,
}
_BASED_ON_VALUES: dict[str, int] = {
    label: value for value, label in _BASED_ON_OPTIONS.items()
}


def battery_regime_is_voltage(
    coordinator: EG4DataUpdateCoordinator, *, discharge: bool
) -> bool | None:
    """Whether the inverters' battery control regime is voltage.

    Reads register 179 (bit 10 discharge / bit 9 charge) from every
    inverter's parameters. None when no inverter has reported it or the
    inverters disagree: the portal's greying can't be mirrored then, so no
    threshold is gated.
    """
    key = (
        PARAM_FUNC_BAT_DISCHARGE_CONTROL if discharge else PARAM_FUNC_BAT_CHARGE_CONTROL
    )
    data = coordinator.data or {}
    parameters = data.get("parameters", {})
    regimes = {
        bool(value)
        for serial, device in data.get("devices", {}).items()
        if device.get("type") == "inverter"
        and (value := parameters.get(serial, {}).get(key)) is not None
    }
    return regimes.pop() if len(regimes) == 1 else None


def create_port_option_entities(
    coordinator: EG4DataUpdateCoordinator, platform: str
) -> list[Any]:
    """Build one platform's option entities for every GridBOSS with a local link."""
    entity_class = _PLATFORM_CLASSES.get(platform)
    if entity_class is None or not coordinator.data:
        return []
    entities: list[Any] = []
    for serial, device_data in coordinator.data.get("devices", {}).items():
        if device_data.get("type") != DEVICE_TYPE_GRIDBOSS:
            continue
        if not coordinator.has_configured_local_transport(serial):
            continue
        entities.extend(
            entity_class(coordinator, serial, port, spec)
            for port in SMART_PORT_NUMBERS
            for spec in port_option_specs(platform)
        )
    return entities


class PortOptionEntity(EG4OptimisticEntity):
    """Shared identity, device and availability for smart port option entities.

    Mixed in ahead of the platform base class, so its ``available`` and
    ``device_info`` win.
    """

    _serial: str
    _port: int
    _spec: PortOptionSpec

    @property
    def _coordinator(self) -> EG4DataUpdateCoordinator:
        return cast("EG4DataUpdateCoordinator", self.coordinator)

    def _init_port_option(self, port: int, spec: PortOptionSpec) -> None:
        self._port = port
        self._spec = spec
        self._attr_unique_id = port_sensor_unique_id(self._serial, port, spec.id_suffix)
        self._attr_has_entity_name = True
        self._attr_name = spec.name
        self._attr_entity_category = EntityCategory.CONFIG
        if spec.icon is not None:
            self._attr_icon = spec.icon

    @property
    def device_info(self) -> DeviceInfo | None:
        """The Smart Port N device."""
        return self._coordinator.get_smart_port_device_info(self._serial, self._port)

    @property
    def _option_params(self) -> dict[str, Any]:
        params: dict[str, Any] = (
            (self.coordinator.data or {}).get("parameters", {}).get(self._serial)
        ) or {}
        return params

    def _option_value(self, name: str) -> Any:
        return self._option_params.get(name)

    def _option_names(self) -> tuple[str, ...]:
        """Option names this entity reads (all must be known to be available)."""
        return (self._spec.param_name(self._port),)

    def _option_available(self) -> bool:
        """Portal-equivalent availability (module docstring)."""
        if not self._control_device_available(DEVICE_TYPE_GRIDBOSS):
            return False
        device = (self.coordinator.data or {})["devices"][self._serial]
        if self._coordinator.is_transport_link_down(self._serial):
            return False
        sensors = device.get("sensors") or {}
        if resolve_port_mode(sensors, self._port) != self._spec.mode:
            return False
        if any(self._option_value(name) is None for name in self._option_names()):
            return False
        return self._gates_open()

    def _gates_open(self) -> bool:
        port = self._port
        for gate in self._spec.gates:
            if gate == GATE_TIME_BASED:
                based_on = self._option_value(f"BIT_SMART_LOAD_BASE_ON_{port}")
                if based_on != SMART_LOAD_BASE_ON_TIME:
                    return False
            elif gate == GATE_SHEDDING:
                if self._option_value(f"FUNC_SHEDDING_MODE_EN_{port}") is not True:
                    return False
            elif gate in (GATE_SOC, GATE_VOLT):
                voltage = battery_regime_is_voltage(
                    self._coordinator,
                    discharge=self._spec.mode != PORT_MODE_AC_COUPLE,
                )
                if voltage is not None and voltage != (gate == GATE_VOLT):
                    return False
        return True

    async def _write_options(self, values: dict[str, Any]) -> None:
        _LOGGER.info(
            "Setting smart port %d %s for %s", self._port, values, self._serial
        )
        await self._coordinator.write_midbox_options(self._serial, values)


class EG4SmartPortOptionSwitch(PortOptionEntity, EG4BaseSwitch):
    """A smart port function enable (register 229)."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        port: int,
        spec: PortOptionSpec,
    ) -> None:
        """Initialize the switch for one port."""
        super().__init__(coordinator, serial, spec.id_suffix, spec.name)
        self._init_port_option(port, spec)

    @property
    def available(self) -> bool:
        """Portal-equivalent availability."""
        return self._option_available()

    @property
    def is_on(self) -> bool | None:
        """Return the function's enable state."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        value = self._option_value(self._spec.param_name(self._port))
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the port function."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the port function."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        # The writer's verify read seeds the parameter store with device
        # truth before the optimistic state clears, so no refresh is needed.
        self._optimistic_state = enabled
        self.async_write_ha_state()
        try:
            await self._write_options({self._spec.param_name(self._port): enabled})
        finally:
            self._optimistic_state = None
            self.async_write_ha_state()


class EG4SmartPortBasedOnSelect(PortOptionEntity, EG4BaseSelect):
    """Smart Load "based on": Time or SOC/Volt (register 2101)."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        port: int,
        spec: PortOptionSpec,
    ) -> None:
        """Initialize the select for one port."""
        super().__init__(coordinator, serial)
        self._init_port_option(port, spec)
        self._attr_options = list(_BASED_ON_VALUES)

    @property
    def available(self) -> bool:
        """Portal-equivalent availability."""
        return self._option_available()

    @property
    def current_option(self) -> str | None:
        """Return the current "based on" option."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        return _BASED_ON_OPTIONS.get(
            self._option_value(self._spec.param_name(self._port))
        )

    async def async_select_option(self, option: str) -> None:
        """Write the new "based on" option."""
        self._optimistic_state = option
        self.async_write_ha_state()
        try:
            await self._write_options(
                {self._spec.param_name(self._port): _BASED_ON_VALUES[option]}
            )
        finally:
            self._optimistic_state = None
            self.async_write_ha_state()


@dataclass(frozen=True)
class _NumberFormat:
    unit: str
    minimum: float
    maximum: float
    step: float
    device_class: NumberDeviceClass | None = None


# Bounds shared with the inverter Smart Load panel (const/limits.py): the
# wire carries SOC as a byte and volts / kW at 0.1 resolution with no
# documented ceiling, and a too-narrow range would render a legal portal
# value as unknown. The manual gives shedding start PV power as "0 – 360W";
# the portal and register use kW at 0.1, so no firmware ceiling is pinned.
_NUMBER_FORMATS: dict[str, _NumberFormat] = {
    "SOC": _NumberFormat(
        PERCENTAGE, SMART_LOAD_SOC_MIN, SMART_LOAD_SOC_MAX, SMART_LOAD_SOC_STEP
    ),
    "VOLT": _NumberFormat(
        UnitOfElectricPotential.VOLT,
        SMART_LOAD_VOLT_MIN,
        SMART_LOAD_VOLT_MAX,
        SMART_LOAD_VOLT_STEP,
        NumberDeviceClass.VOLTAGE,
    ),
    "PV_P": _NumberFormat(
        UnitOfPower.KILO_WATT,
        SMART_LOAD_PV_POWER_MIN,
        SMART_LOAD_PV_POWER_MAX,
        SMART_LOAD_PV_POWER_STEP,
        NumberDeviceClass.POWER,
    ),
}


def _number_format(spec: PortOptionSpec) -> _NumberFormat:
    for field_type, number_format in _NUMBER_FORMATS.items():
        if f"_{field_type}_" in spec.param:
            return number_format
    raise ValueError(f"No number format for {spec.param}")


class EG4SmartPortOptionNumber(PortOptionEntity, EG4BaseNumber, NumberEntity):
    """A smart port threshold: SOC, voltage or shedding start PV power."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        port: int,
        spec: PortOptionSpec,
    ) -> None:
        """Initialize the number for one port."""
        super().__init__(coordinator, serial)
        self._serial = serial
        self._init_port_option(port, spec)
        number_format = _number_format(spec)
        self._integer = number_format.step == 1
        self._attr_native_unit_of_measurement = number_format.unit
        self._attr_native_min_value = number_format.minimum
        self._attr_native_max_value = number_format.maximum
        self._attr_native_step = number_format.step
        self._attr_device_class = number_format.device_class

    @property
    def available(self) -> bool:
        """Portal-equivalent availability."""
        return self._option_available()

    @property
    def native_value(self) -> float | None:
        """Return the threshold."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        value = self._option_value(self._spec.param_name(self._port))
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        """Write the threshold."""
        if self._integer:
            if value != int(value):
                raise ServiceValidationError(
                    f"{self._spec.name} must be a whole number, got {value}"
                )
            written: float = int(value)
        else:
            written = round(value, 1)
        self._optimistic_value = written
        self.async_write_ha_state()
        try:
            await self._write_options({self._spec.param_name(self._port): written})
        finally:
            self._optimistic_value = None
            self.async_write_ha_state()


_PLATFORM_CLASSES: dict[str, type[Any]] = {
    "switch": EG4SmartPortOptionSwitch,
    "select": EG4SmartPortBasedOnSelect,
    "number": EG4SmartPortOptionNumber,
}
