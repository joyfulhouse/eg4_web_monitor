"""Onboard dedicated read-only EG4 battery bridges."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.data_entry_flow import AbortFlow
from pylxpweb.transports import BatteryModbusTransport

from ..battery_bus import (
    CONF_BATTERY_INTERVAL,
    CONF_BATTERY_UNITS,
    CONNECTION_TYPE_BATTERY,
    DEFAULT_BATTERY_INTERVAL,
    battery_endpoint,
    close_battery_bus,
)
from ..const import CONF_CONNECTION_TYPE, CONF_MODBUS_HOST, CONF_MODBUS_PORT, DOMAIN
from ..endpoint_bus import EndpointOwnerInUseError, get_endpoint_bus_registry

if TYPE_CHECKING:
    from . import EG4ConfigFlow


def parse_unit_ids(value: str) -> list[int]:
    """Require explicit, unique Modbus slave addresses, never broadcast zero."""
    units = [int(part.strip()) for part in value.split(",")]
    if not units or len(units) > 32 or len(set(units)) != len(units):
        raise ValueError("Provide 1-32 distinct unit IDs")
    if any(unit < 1 or unit > 247 for unit in units):
        raise ValueError("Unit IDs must be between 1 and 247")
    return units


async def async_battery_bridge_step(
    flow: EG4ConfigFlow, user_input: dict[str, Any] | None
) -> ConfigFlowResult:
    entry = flow.hass.config_entries.async_get_entry(flow.context.get("entry_id", ""))
    defaults = dict(entry.data) if entry is not None else {}
    if entry is not None and CONF_BATTERY_INTERVAL in entry.options:
        defaults[CONF_BATTERY_INTERVAL] = entry.options[CONF_BATTERY_INTERVAL]
    errors: dict[str, str] = {}
    if user_input is not None:
        defaults.update(user_input)
        try:
            units = parse_unit_ids(user_input[CONF_BATTERY_UNITS])
            host = str(user_input[CONF_MODBUS_HOST]).strip().lower().rstrip(".")
            if not host or not user_input.get("dedicated_bus"):
                raise ValueError("A dedicated bridge is required")
            data: dict[str, Any] = {
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_BATTERY,
                CONF_MODBUS_HOST: host,
                CONF_MODBUS_PORT: int(user_input.get(CONF_MODBUS_PORT, 502)),
                CONF_BATTERY_UNITS: units,
                CONF_BATTERY_INTERVAL: int(
                    user_input.get(CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL)
                ),
            }
            identity = f"battery_bus_{host}_{data[CONF_MODBUS_PORT]}"
            if any(
                other.entry_id != (entry.entry_id if entry else None)
                and other.unique_id == identity
                for other in flow.hass.config_entries.async_entries(DOMAIN)
            ):
                return flow.async_abort(reason="already_configured")
            if entry is None:
                await flow.async_set_unique_id(identity)
                flow._abort_if_unique_id_configured()
            # The current endpoint already belongs to this entry. A changed
            # endpoint must pass the same ownership and response checks as setup
            # before unloading the working bus or updating stored settings.
            if entry is None or identity != entry.unique_id:
                bus = BatteryModbusTransport(
                    host=host, port=data[CONF_MODBUS_PORT], unit_ids=units
                )
                release = get_endpoint_bus_registry(
                    flow.hass
                ).reserve_external_endpoint(battery_endpoint(data))
                try:
                    await bus.connect()
                    batteries = await bus.read_all()
                    if not batteries:
                        errors["base"] = "battery_no_response"
                finally:
                    await close_battery_bus(bus, release)
            if not errors:
                if entry is not None:
                    options = dict(entry.options)
                    options[CONF_BATTERY_INTERVAL] = data[CONF_BATTERY_INTERVAL]
                    return flow.async_update_reload_and_abort(
                        entry, unique_id=identity, data_updates=data, options=options
                    )
                return flow.async_create_entry(title="EG4 battery bridge", data=data)
        except AbortFlow:
            raise
        except (ValueError, TypeError):
            errors["base"] = "invalid_battery_units"
        except EndpointOwnerInUseError:
            errors["base"] = "endpoint_in_use"
        except Exception:
            errors["base"] = "cannot_connect"
    unit_default = defaults.get(CONF_BATTERY_UNITS, "1,2,3")
    if isinstance(unit_default, list):
        unit_default = ",".join(str(unit) for unit in unit_default)
    return flow.async_show_form(
        step_id="battery_bridge",
        data_schema=vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST, default=defaults.get(CONF_MODBUS_HOST, "")
                ): str,
                vol.Required(
                    CONF_MODBUS_PORT, default=defaults.get(CONF_MODBUS_PORT, 502)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_BATTERY_UNITS, default=unit_default): str,
                vol.Required(
                    CONF_BATTERY_INTERVAL,
                    default=defaults.get(
                        CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Required("dedicated_bus", default=False): bool,
            }
        ),
        errors=errors,
    )
