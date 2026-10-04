"""Run local Modbus transports on Home Assistant's shared Modbus connections.

Home Assistant 2026.9 added ``homeassistant.components.modbus.async_get_unit``:
integrations that talk to the same Modbus device share one connection, held
per config entry and closed when the last holding entry unloads. pylxpweb
(0.10.0b10+) accepts such a unit through the transport's ``unit=`` parameter;
it then never dials or closes the link and heals a wedged link through the
unit's own ``disconnect()``.

The unit is injected only when the transport's backend resolves to
``modbus_connection`` (an ``esphome://`` serial port under ``auto``, or an
explicit stored ``backend``). ``auto`` on a TCP gateway or a local serial
device stays on pymodbus exactly as before: the shared unit would silently
swap the wire library under existing installs and drop pylxpweb's gateway
transaction-ID workaround. Older Home Assistant (no ``async_get_unit``), a
pylxpweb without the ``unit=`` seam, or a missing ``modbus_connection``
package all fall back to the default factory, where pylxpweb owns the link.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
import importlib
import inspect
import logging
from typing import Any, Literal, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pylxpweb.transports.config import TransportConfig, TransportType

from .coordinator_mappings import SERIALX_ONLY_SCHEMES
from .endpoint_bus import RawTransportFactory, _RawLocalTransport

_LOGGER = logging.getLogger(__name__)

AsyncGetUnit = Callable[[HomeAssistant, ConfigEntry, Any, int], Any]

_PARITIES: dict[str, Literal["N", "E", "O"]] = {"N": "N", "E": "E", "O": "O"}
_STOPBITS: dict[int, Literal[1, 2]] = {1: 1, 2: 2}


def _detect_async_get_unit() -> AsyncGetUnit | None:
    """Return Home Assistant's ``async_get_unit``, or None where it is absent.

    Feature-detected, not version-compared: the helper exists from Home
    Assistant 2026.9; earlier cores (the hacs.json floor is 2026.1) lack it,
    and importing the modbus component there must not fail setup. It also
    needs the ``modbus_connection`` package, which ``unit_params`` imports.
    Runs at module import, which Home Assistant performs in its import
    executor, so no import happens on the event loop.
    """
    try:
        module = importlib.import_module("homeassistant.components.modbus")
        importlib.import_module("modbus_connection")
    except ImportError:
        return None
    get_unit = getattr(module, "async_get_unit", None)
    return cast(AsyncGetUnit, get_unit) if callable(get_unit) else None


_ASYNC_GET_UNIT = _detect_async_get_unit()


def _load_async_get_unit() -> AsyncGetUnit | None:
    """Return the ``async_get_unit`` detected at import (patched in tests)."""
    return _ASYNC_GET_UNIT


def _transport_accepts_unit() -> bool:
    """Whether the installed pylxpweb Modbus transports take ``unit=``."""
    from pylxpweb.transports import ModbusSerialTransport, ModbusTransport

    return all(
        "unit" in inspect.signature(cls.__init__).parameters
        for cls in (ModbusTransport, ModbusSerialTransport)
    )


def _resolves_to_modbus_connection(config: TransportConfig) -> bool:
    """Whether pylxpweb would run this config on ``modbus_connection``."""
    if config.transport_type not in (
        TransportType.MODBUS_TCP,
        TransportType.MODBUS_SERIAL,
    ):
        return False
    serial_port = (
        config.serial_port
        if config.transport_type is TransportType.MODBUS_SERIAL
        else None
    )
    backend = str(getattr(config, "backend", "auto"))
    try:
        from pylxpweb.transports._modbus_client import resolve_backend
    except ImportError:
        return _owned_resolve_backend(backend, serial_port) == "modbus_connection"
    return resolve_backend(backend, serial_port=serial_port) == "modbus_connection"


def _owned_resolve_backend(backend: str, serial_port: str | None) -> str:
    """Resolve ``auto`` the way pylxpweb 0.10.0b10 does, without its private module.

    ``resolve_backend`` lives in pylxpweb's private ``_modbus_client`` module,
    which a later release may move; this keeps the decision working if so.
    """
    value = backend.strip().lower().replace("-", "_")
    if value != "auto":
        return value
    if serial_port is not None and serial_port.lower().startswith(SERIALX_ONLY_SCHEMES):
        return "modbus_connection"
    return "pymodbus"


def _unit_params(config: TransportConfig) -> Any:
    """Build the ``modbus_connection`` link parameters for one config.

    Mirrors the parameters pylxpweb dials with on its owned
    ``modbus_connection`` path, so a link shared with another integration is
    keyed and configured identically.
    """
    from modbus_connection import ModbusSerialParams, ModbusTcpParams

    if config.transport_type is TransportType.MODBUS_SERIAL:
        parity = _PARITIES.get(config.serial_parity)
        stopbits = _STOPBITS.get(config.serial_stopbits)
        if parity is None or stopbits is None:
            raise ValueError(
                f"Unsupported serial framing {config.serial_parity}/"
                f"{config.serial_stopbits} for modbus_connection"
            )
        return ModbusSerialParams(
            device=str(config.serial_port),
            baudrate=config.serial_baudrate,
            parity=parity,
            stopbits=stopbits,
        )
    return ModbusTcpParams(host=config.host, port=config.port)


def _build_transport(config: TransportConfig, unit: Any) -> _RawLocalTransport:
    """Construct the raw transport around a host-owned unit.

    ``create_transport_from_config`` has no ``unit=`` parameter, so the
    transport is built directly with the same arguments the factory passes.
    """
    from pylxpweb.transports import ModbusSerialTransport, ModbusTransport

    common: dict[str, Any] = {
        "serial": config.serial,
        "unit_id": config.unit_id,
        "timeout": config.timeout,
        "inverter_family": config.inverter_family,
        "retries": config.retries,
        "retry_delay": config.retry_delay,
        "inter_register_delay": config.inter_register_delay,
        "max_input_block_size": config.max_input_block_size,
        "backend": config.backend,
        "unit": unit,
    }
    if config.transport_type is TransportType.MODBUS_SERIAL:
        return cast(
            _RawLocalTransport,
            ModbusSerialTransport(
                port=str(config.serial_port),
                baudrate=config.serial_baudrate,
                parity=config.serial_parity,
                stopbits=config.serial_stopbits,
                **common,
            ),
        )
    return cast(
        _RawLocalTransport,
        ModbusTransport(host=config.host, port=config.port, **common),
    )


def _require_timeout(unit: Any, seconds: float) -> None:
    """Ask a shared link for this transport's configured request timeout.

    Core builds the shared connection without a timeout, so the link uses
    ``modbus_connection``'s 10 s default, and pylxpweb never passes its
    timeout to an injected unit. ``require_timeout`` (modbus-connection
    4.12.0+) sets a per-unit requirement; the link runs at the largest one
    any unit asks for. Earlier releases, including the 4.10.0 Home Assistant
    2026.9 pins, lack it and keep the 10 s default (checked against the
    published 4.10.0, 4.11.0, 4.11.1, 4.12.0 and 4.12.3 wheels).
    """
    require = getattr(unit, "require_timeout", None)
    if callable(require):
        require(seconds)


def build_shared_unit_factory(
    hass: HomeAssistant,
    entry: ConfigEntry,
    fallback: RawTransportFactory,
) -> RawTransportFactory:
    """Return a raw-transport factory that injects Home Assistant's units.

    Returns ``fallback`` itself when Home Assistant, pylxpweb or the
    ``modbus_connection`` package cannot provide a shared unit, so callers
    can pass the result unconditionally.

    Each ``async_get_unit`` call adds one hold on the shared connection that
    is released only when ``entry`` unloads, so units are memoised per link
    and unit ID: recreating a capability after an error reuses the unit
    instead of stacking holds.
    """
    get_unit = _load_async_get_unit()
    if get_unit is None:
        return fallback
    if not _transport_accepts_unit():
        _LOGGER.debug("Installed pylxpweb has no unit= seam; using owned links")
        return fallback

    units: dict[tuple[Hashable, int], Any] = {}

    def factory(config: TransportConfig) -> _RawLocalTransport:
        if not _resolves_to_modbus_connection(config):
            return fallback(config)
        params = _unit_params(config)
        key = (params, config.unit_id)
        unit = units.get(key)
        if unit is None:
            try:
                unit = get_unit(hass, entry, params, config.unit_id)
            except HomeAssistantError as err:
                # Another integration holds this device with different link
                # settings (baud rate, parity...). Both cannot be honoured on
                # one connection; keep this transport working on its own link.
                _LOGGER.warning(
                    "Modbus device %s is shared with different link settings "
                    "(%s); %s keeps its own connection",
                    params.endpoint,
                    err,
                    config.serial,
                )
                return fallback(config)
            units[key] = unit
            _require_timeout(unit, config.timeout)
            _LOGGER.debug(
                "Using Home Assistant's shared Modbus connection %s for %s",
                params.endpoint,
                config.serial,
            )
        return _build_transport(config, unit)

    return factory
