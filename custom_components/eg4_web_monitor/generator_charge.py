"""Device-level GridBOSS generator settings for LOCAL and HYBRID links.

Register names are portal-correlated by the cloud range dumps referenced in
const.midbox. Raw diagnostics carry no assumed units or writable counterpart.
Readback verifies storage, not generator behavior or the active SOC/volt regime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .base_entity import EG4BaseNumber, EG4DeviceEntity
from .const import DEVICE_TYPE_GRIDBOSS

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator


@dataclass(frozen=True)
class GeneratorChargeSpec:
    """One setting with portal units and bounds."""

    param: str
    name: str
    unit: str
    minimum: int
    maximum: int


# Start SOC's portal [40, 57] conflicts with dumps reading 10%; use 0-100%.
# End SOC and remote auto turn-off bounds match #705's portal screenshot.
GENERATOR_CHARGE_SPECS = (
    GeneratorChargeSpec(
        "OFF_GRID_HOLD_GEN_CHG_START_SOC",
        "Generator Charge Start SOC",
        PERCENTAGE,
        0,
        100,
    ),
    GeneratorChargeSpec(
        "OFF_GRID_HOLD_GEN_CHG_END_SOC", "Generator Charge End SOC", PERCENTAGE, 0, 100
    ),
    GeneratorChargeSpec(
        "MIDBOX_HOLD_GEN_REMOTE_TURN_OFF_TIME",
        "Generator Remote Auto Turn-Off Time",
        UnitOfTime.MINUTES,
        5,
        20,
    ),
)

_RAW_NAMES = {
    "OFF_GRID_HOLD_GEN_CHG_START_VOLT_RAW": "Generator Charge Start Voltage",
    "OFF_GRID_HOLD_GEN_CHG_END_VOLT_RAW": "Generator Charge End Voltage",
    "OFF_GRID_HOLD_MAX_GEN_CHG_BAT_CURR_RAW": "Generator Battery Charge Current Limit",
    "MIDBOX_HOLD_GEN_VOLT_SOC_ENABLE_RAW": "Generator SOC/Vbat Enable",
    "MIDBOX_HOLD_GEN_REMOTE_CTRL_RAW": "Generator Remote Control",
    "MIDBOX_HOLD_GEN_WARN_UP_TIME_RAW": "Generator Warm-Up Time",
    "MIDBOX_HOLD_GEN_COOL_DOWN_TIME_RAW": "Generator Cool-Down Time",
}


def create_generator_charge_entities(
    coordinator: EG4DataUpdateCoordinator, platform: str
) -> list[Any]:
    """Create settings only for GridBOSS devices with a configured local link."""
    entities: list[Any] = []
    for serial, device in (coordinator.data or {}).get("devices", {}).items():
        if device.get("type") != DEVICE_TYPE_GRIDBOSS:
            continue
        if not coordinator.has_configured_local_transport(serial):
            continue
        if platform == "number":
            entities.extend(
                GeneratorChargeNumber(coordinator, serial, spec)
                for spec in GENERATOR_CHARGE_SPECS
            )
        elif platform == "sensor":
            entities.extend(
                GeneratorChargeRawSensor(coordinator, serial, param, name)
                for param, name in _RAW_NAMES.items()
            )
    return entities


class _GeneratorChargeEntity(CoordinatorEntity):
    """Shared device identity and local-link availability."""

    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:engine"

    _serial: str

    @property
    def _coordinator(self) -> EG4DataUpdateCoordinator:
        return cast("EG4DataUpdateCoordinator", self.coordinator)

    def _init_generator_charge(self, serial: str, param: str, name: str) -> None:
        self._serial = serial
        self._param = param
        self._attr_unique_id = f"{serial}_{param.lower()}"
        self._attr_name = name

    @property
    def native_value(self) -> int | None:
        """Return the decoded parameter, or unknown before the first read."""
        value = (
            (self._coordinator.data or {})
            .get("parameters", {})
            .get(self._serial, {})
            .get(self._param)
        )
        return value if isinstance(value, int) else None

    @property
    def available(self) -> bool:
        """Require a successful update, a local link and a known parameter."""
        device = (self._coordinator.data or {}).get("devices", {}).get(self._serial, {})
        return bool(
            self._coordinator.last_update_success
            and device.get("type") == DEVICE_TYPE_GRIDBOSS
            and self._coordinator.has_configured_local_transport(self._serial)
            and not self._coordinator.is_transport_link_down(self._serial)
            and self.native_value is not None
        )


class GeneratorChargeNumber(_GeneratorChargeEntity, EG4BaseNumber, NumberEntity):
    """A generator setting written through the existing verified local writer."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: GeneratorChargeSpec,
    ) -> None:
        """Initialize one device-level setting."""
        super().__init__(coordinator, serial)
        self._init_generator_charge(serial, spec.param, spec.name)
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_native_min_value = spec.minimum
        self._attr_native_max_value = spec.maximum

    @property
    def available(self) -> bool:
        """Honor number discovery as well as the local parameter source."""
        return (
            self._control_device_available(DEVICE_TYPE_GRIDBOSS) and super().available
        )

    async def async_set_native_value(self, value: float) -> None:
        """Validate a whole-unit value before passing it to the shared writer."""
        if (
            not math.isfinite(value)
            or not self.native_min_value <= value <= self.native_max_value
            or value != int(value)
        ):
            raise ServiceValidationError(
                f"{self.name} requires a whole number between "
                f"{self.native_min_value} and {self.native_max_value}"
            )
        if not self.available:
            raise ServiceValidationError(
                f"{self.name} requires an available local link"
            )
        await self.coordinator.write_midbox_options(
            self._serial, {self._param: int(value)}
        )


class GeneratorChargeRawSensor(_GeneratorChargeEntity, EG4DeviceEntity, SensorEntity):
    """An unscaled holding-register word with no write interface."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: EG4DataUpdateCoordinator, serial: str, param: str, name: str
    ) -> None:
        """Label the uncertainty directly in the entity name."""
        super().__init__(coordinator, serial)
        self._init_generator_charge(serial, param, f"{name} (raw, unverified)")
