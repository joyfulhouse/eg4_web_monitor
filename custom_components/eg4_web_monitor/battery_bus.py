"""Read-only devices on a dedicated EG4 battery Modbus TCP bridge."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any, TYPE_CHECKING, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from pylxpweb.transports import BatteryModbusTransport
from pylxpweb.transports.config import TransportConfig, TransportType
from pylxpweb.transports.data import BatteryData

from .const import CONF_MODBUS_HOST, CONF_MODBUS_PORT, DOMAIN
from .endpoint_bus import get_endpoint_bus_registry

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_LOGGER = logging.getLogger(__name__)
CONNECTION_TYPE_BATTERY = "battery_bus"
CONF_BATTERY_UNITS = "battery_unit_ids"
CONF_BATTERY_INTERVAL = "battery_poll_interval"
DEFAULT_BATTERY_INTERVAL = 30


async def close_battery_bus(
    bus: BatteryModbusTransport, release: Callable[[], None]
) -> None:
    """Release ownership only after disconnect completes, including cancellation."""
    close = asyncio.create_task(bus.disconnect())
    try:
        await asyncio.shield(close)
    except asyncio.CancelledError:
        await close
        release()
        raise
    release()


def battery_endpoint(data: Mapping[str, Any]) -> TransportConfig:
    """Build an endpoint identity without issuing an inverter-protocol probe."""
    return TransportConfig(
        transport_type=TransportType.MODBUS_TCP,
        host=data[CONF_MODBUS_HOST],
        port=data.get(CONF_MODBUS_PORT, 502),
        serial="battery_bus",
        unit_id=1,
    )


def project_battery(
    data: BatteryData, protocol: str, *, complete: bool
) -> dict[str, Any]:
    """Keep aggregate master measurements out of per-pack sensors."""
    master = protocol == "eg4_master"
    master_reconstructed = complete and data.current_capacity is not None
    known = protocol in {"eg4_master", "eg4_slave"}
    result: dict[str, Any] = {"protocol": protocol, "firmware": data.firmware_version}
    if not known:
        return result
    result.update(
        voltage=data.voltage if data.voltage > 0 else None,
        current=None if master else data.current,
        soc=data.soc if not master or master_reconstructed else None,
        soh=data.soh,
        temperature=None if master else data.temperature,
        capacity=data.max_capacity if data.max_capacity > 0 else None,
        remaining_capacity=(
            data.current_capacity if not master or master_reconstructed else None
        ),
        cycle_count=None if master else data.cycle_count,
        min_cell_voltage=data.min_cell_voltage if data.min_cell_voltage > 0 else None,
        max_cell_voltage=data.max_cell_voltage if data.max_cell_voltage > 0 else None,
    )
    for index, value in enumerate(data.cell_voltages[:16], 1):
        result[f"cell_{index}_voltage"] = value if value > 0 else None
    for index, value in enumerate(data.cell_temperatures[:6], 1):
        result[f"temperature_{index}"] = value
    return result


class BatteryBusCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Own one dedicated bridge and publish each responding unit independently."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.unit_ids: list[int] = list(entry.data[CONF_BATTERY_UNITS])
        self.bus = BatteryModbusTransport(
            host=entry.data[CONF_MODBUS_HOST],
            port=entry.data.get(CONF_MODBUS_PORT, 502),
            unit_ids=self.unit_ids,
        )
        self._release_endpoint = get_endpoint_bus_registry(
            hass
        ).reserve_external_endpoint(battery_endpoint(entry.data))
        super().__init__(
            hass,
            _LOGGER,
            name="EG4 battery bus",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_BATTERY_INTERVAL,
                    entry.data.get(CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL),
                )
            ),
        )

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            if not self.bus.is_connected:
                await self.bus.connect()
            batteries = await self.bus.read_all()
        except Exception as err:
            raise UpdateFailed(f"Battery bridge read failed: {err}") from err
        if not batteries:
            raise UpdateFailed("No configured battery units responded")
        responding = {battery.battery_index + 1 for battery in batteries}
        complete = set(self.unit_ids).issubset(responding)
        # The pinned library exposes detected protocol objects only in this
        # cache. Fail closed if that seam changes; unit ID alone is not a map.
        protocols = getattr(self.bus, "_detected_protocols", {})
        return {
            battery.battery_index + 1: project_battery(
                battery,
                str(
                    getattr(protocols.get(battery.battery_index + 1), "name", "unknown")
                ),
                complete=complete,
            )
            for battery in batteries
            if battery.battery_index + 1 in self.unit_ids
        }

    async def async_shutdown(self) -> None:
        try:
            await super().async_shutdown()
        finally:
            await close_battery_bus(self.bus, self._release_endpoint)


async def async_setup_battery_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BatteryBusCoordinator(hass, entry)
    entry.runtime_data = coordinator
    started = False
    try:
        await coordinator.async_config_entry_first_refresh()
        started = True
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except BaseException:
        try:
            if started:
                await hass.config_entries.async_unload_platforms(
                    entry, [Platform.SENSOR]
                )
        finally:
            await coordinator.async_shutdown()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_battery))
    return True


async def _async_reload_battery(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_battery_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return False
    await cast(BatteryBusCoordinator, entry.runtime_data).async_shutdown()
    return True


def _descriptions() -> list[SensorEntityDescription]:
    fields: list[tuple[str, str, str | None, SensorDeviceClass | None]] = [
        ("voltage", "Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
        ("current", "Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
        ("soc", "State of charge", "%", SensorDeviceClass.BATTERY),
        ("soh", "State of health", "%", None),
        (
            "temperature",
            "Temperature",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
        ),
        ("capacity", "Capacity", "Ah", None),
        ("remaining_capacity", "Remaining capacity", "Ah", None),
        ("cycle_count", "Cycle count", None, None),
        (
            "min_cell_voltage",
            "Minimum cell voltage",
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
        ),
        (
            "max_cell_voltage",
            "Maximum cell voltage",
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
        ),
    ]
    fields.extend(
        (
            f"cell_{i}_voltage",
            f"Cell {i} voltage",
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
        )
        for i in range(1, 17)
    )
    fields.extend(
        (
            f"temperature_{i}",
            f"Temperature {i}",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
        )
        for i in range(1, 7)
    )
    return [
        SensorEntityDescription(
            key=key,
            name=name,
            native_unit_of_measurement=unit,
            device_class=device_class,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=not key.startswith(
                ("cell_", "temperature_")
            ),
        )
        for key, name, unit, device_class in fields
    ]


class BatteryBusSensor(CoordinatorEntity[BatteryBusCoordinator], SensorEntity):
    """A stable bus/unit entity, independent of unavailable BMS serial strings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BatteryBusCoordinator,
        unit: int,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.unit = unit
        self.entity_description = description
        identity = f"battery_bus_{coordinator.entry.entry_id}_unit_{unit}"
        self._attr_unique_id = f"{identity}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identity)},
            name=f"Battery unit {unit}",
            manufacturer="EG4",
            model="Direct RS485 battery",
        )
        self._attr_extra_state_attributes = {"modbus_unit_id": unit}

    @property
    def available(self) -> bool:
        return super().available and self.unit in (self.coordinator.data or {})

    @property
    def native_value(self) -> float | int | None:
        value = (
            (self.coordinator.data or {})
            .get(self.unit, {})
            .get(self.entity_description.key)
        )
        return value if isinstance(value, (int, float)) else None


def async_setup_battery_sensors(
    entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = cast(BatteryBusCoordinator, entry.runtime_data)
    async_add_entities(
        [
            BatteryBusSensor(coordinator, unit, description)
            for unit in coordinator.unit_ids
            for description in _descriptions()
        ]
    )
