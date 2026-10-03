"""Setup with ``modbus_connection``, ``tmodbus`` and ``serialx`` unimportable.

The manifest pins plain ``pylxpweb``: Home Assistant ships the
``modbus_connection`` stack only from 2026.9, through its ``modbus``
integration. On older cores these tests pin that:

- the integration imports and a Modbus TCP entry sets up on pymodbus;
- an ``esphome://`` device is created without crashing and fails at connect
  with pylxpweb's ``TransportConnectionError`` naming the missing package.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

from pylxpweb.transports import ModbusSerialTransport, ModbusTransport
from pylxpweb.transports.exceptions import TransportConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import ha_modbus
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_transport_configs,
)

_BLOCKED = ("modbus_connection", "tmodbus", "serialx")

_TCP = {
    "serial": "SYNTH20001",
    "transport_type": "modbus_tcp",
    "host": "192.0.2.20",
    "port": 502,
    "unit_id": 1,
    "inverter_family": "EG4_HYBRID",
    "model": "FlexBOSS21",
}
_ESPHOME = {
    "serial": "SYNTH20002",
    "transport_type": "modbus_serial",
    "serial_port": "esphome://esp-rs485.local:6053",
    "unit_id": 1,
}


@pytest.fixture
def without_modbus_connection() -> Iterator[None]:
    """Make the stack unimportable and re-run ``ha_modbus`` feature detection."""
    blocked = {name: None for name in sys.modules if name.split(".")[0] in _BLOCKED}
    blocked.update(dict.fromkeys(_BLOCKED))
    with patch.dict(sys.modules, blocked):
        with pytest.raises(ImportError):
            importlib.import_module("modbus_connection")
        with patch.object(
            ha_modbus, "_ASYNC_GET_UNIT", ha_modbus._detect_async_get_unit()
        ):
            yield


def _raw(capability: Any) -> Any:
    return capability._owner._records[capability._token].raw


def test_detection_reports_no_shared_unit(without_modbus_connection: None) -> None:
    assert ha_modbus._load_async_get_unit() is None


async def test_tcp_entry_sets_up_on_pymodbus(
    hass: Any, without_modbus_connection: None
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_LOCAL_TRANSPORTS: [dict(_TCP)],
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.eg4_web_monitor.coordinator."
            "EG4DataUpdateCoordinator._async_update_data",
            new=AsyncMock(return_value={"devices": {}, "parameters": {}}),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    # Owned factory: no shared-unit wrapper when the stack is absent.
    assert (
        coordinator._raw_transport_factory
        is coordinator._endpoint_bus_registry.raw_transport_factory
    )
    capability = coordinator._create_bus_capability(
        _build_transport_configs([dict(_TCP)])[0]
    )
    try:
        raw = _raw(capability)
        assert isinstance(raw, ModbusTransport)
        assert raw._backend == "pymodbus"
        assert raw._external_unit is None
    finally:
        await coordinator._endpoint_bus_registry.async_shutdown_capabilities(
            [capability]
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_esphome_port_fails_at_connect_with_install_hint(
    hass: Any, without_modbus_connection: None
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
    )
    entry.add_to_hass(hass)
    from custom_components.eg4_web_monitor.coordinator import (
        EG4DataUpdateCoordinator,
    )

    coordinator = EG4DataUpdateCoordinator(hass, entry)
    capability = coordinator._create_bus_capability(
        _build_transport_configs([dict(_ESPHOME)])[0]
    )
    try:
        raw = _raw(capability)
        assert isinstance(raw, ModbusSerialTransport)
        assert raw._external_unit is None
        with pytest.raises(TransportConnectionError, match="modbus-connection"):
            await raw.connect()
    finally:
        await coordinator._endpoint_bus_registry.async_shutdown_capabilities(
            [capability]
        )
        await coordinator.async_shutdown()
