"""Read-only raw GridBOSS generator diagnostics for LOCAL and HYBRID links.

Cloud range dumps identify addresses, not local scaling. All values remain
unscaled until controlled portal changes are paired with local raw reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .base_entity import EG4DeviceEntity
from .const import DEVICE_TYPE_GRIDBOSS

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator

_RAW_NAMES = {
    "OFF_GRID_HOLD_GEN_CHG_START_VOLT_RAW": "Generator Charge Start Voltage",
    "OFF_GRID_HOLD_GEN_CHG_END_VOLT_RAW": "Generator Charge End Voltage",
    "OFF_GRID_HOLD_GEN_CHG_START_SOC_RAW": "Generator Charge Start SOC",
    "OFF_GRID_HOLD_GEN_CHG_END_SOC_RAW": "Generator Charge End SOC",
    "OFF_GRID_HOLD_MAX_GEN_CHG_BAT_CURR_RAW": "Generator Battery Charge Current Limit",
    "MIDBOX_HOLD_GEN_VOLT_SOC_ENABLE_RAW": "Generator SOC/Vbat Enable",
    "MIDBOX_HOLD_GEN_REMOTE_CTRL_RAW": "Generator Remote Control",
    "MIDBOX_HOLD_GEN_WARN_UP_TIME_RAW": "Generator Warm-Up Time",
    "MIDBOX_HOLD_GEN_COOL_DOWN_TIME_RAW": "Generator Cool-Down Time",
    "MIDBOX_HOLD_GEN_REMOTE_TURN_OFF_TIME_RAW": "Generator Remote Auto Turn-Off Time",
}


def create_generator_charge_entities(
    coordinator: EG4DataUpdateCoordinator,
) -> list[GeneratorChargeRawSensor]:
    """Create raw diagnostics for GridBOSS devices with a configured local link."""
    return [
        GeneratorChargeRawSensor(coordinator, serial, param, name)
        for serial, device in (coordinator.data or {}).get("devices", {}).items()
        if device.get("type") == DEVICE_TYPE_GRIDBOSS
        and coordinator.has_configured_local_transport(serial)
        for param, name in _RAW_NAMES.items()
    ]


class GeneratorChargeRawSensor(EG4DeviceEntity, SensorEntity):
    """An unscaled holding-register word with local-link availability."""

    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:engine"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: EG4DataUpdateCoordinator, serial: str, param: str, name: str
    ) -> None:
        """Label uncertainty directly in the device-level entity name."""
        super().__init__(coordinator, serial)
        self._param = param
        self._attr_unique_id = f"{serial}_{param.lower()}"
        self._attr_name = f"{name} (raw, unverified)"

    @property
    def native_value(self) -> int | None:
        """Return the raw word, or unknown before the first successful read."""
        value = (
            (self.coordinator.data or {})
            .get("parameters", {})
            .get(self._serial, {})
            .get(self._param)
        )
        return value if isinstance(value, int) else None

    @property
    def available(self) -> bool:
        """Require a successful update, configured local link and known word."""
        device = (self.coordinator.data or {}).get("devices", {}).get(self._serial, {})
        return bool(
            self.coordinator.last_update_success
            and device.get("type") == DEVICE_TYPE_GRIDBOSS
            and self.coordinator.has_configured_local_transport(self._serial)
            and not self.coordinator.is_transport_link_down(self._serial)
            and self.native_value is not None
        )
