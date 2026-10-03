"""Home Assistant shared Modbus units and the stored ``backend`` key.

pylxpweb 0.10.0b10 runs Modbus transports on either pymodbus or
``modbus_connection`` and accepts a host-owned unit through ``unit=``.
These tests pin the eg4 side of that seam:

- a stored ``backend`` reaches ``TransportConfig``; absent/null stays ``auto``;
- only configs resolving to ``modbus_connection`` get Home Assistant's unit,
  so ``auto`` on TCP / local serial keeps the owned pymodbus path;
- one ``async_get_unit`` hold per link and unit ID, however often the
  capability is recreated;
- older Home Assistant (no ``async_get_unit``) and a link-settings clash
  fall back to the owned factory.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from homeassistant.exceptions import HomeAssistantError
from pylxpweb.transports import ModbusSerialTransport, ModbusTransport
from pylxpweb.transports.config import TransportConfig
import pytest

from custom_components.eg4_web_monitor import ha_modbus
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_transport_configs,
    _transport_config_backend_kwargs,
)
from custom_components.eg4_web_monitor.endpoint_bus import (
    EndpointBusCapability,
    EndpointBusRegistry,
)
from tests.test_endpoint_bus_owner import (
    _config as _owner_config,
    _FakeRawTransport,
    _WireProbe,
)

_TCP = {
    "serial": "SYNTH10001",
    "transport_type": "modbus_tcp",
    "host": "192.0.2.10",
    "port": 502,
    "unit_id": 1,
}
_SERIAL = {
    "serial": "SYNTH10002",
    "transport_type": "modbus_serial",
    "serial_port": "/dev/ttyUSB0",
    "unit_id": 1,
}
_ESPHOME = {**_SERIAL, "serial_port": "esphome://esp-rs485.local:6053"}


def _config(item: dict[str, Any]) -> TransportConfig:
    configs = _build_transport_configs([dict(item)])
    assert len(configs) == 1
    return configs[0]


class _FakeUnit:
    connected = True

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        return [0] * count

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        return [0] * count

    async def write_register(self, address: int, value: int) -> None:
        return None

    async def write_registers(self, address: int, values: list[int]) -> None:
        return None

    async def disconnect(self) -> None:
        return None


class TestStoredBackend:
    @pytest.mark.parametrize("item", [_TCP, _SERIAL])
    def test_absent_backend_is_auto(self, item: dict[str, Any]) -> None:
        assert _config(item).backend == "auto"

    def test_null_backend_is_auto(self) -> None:
        assert _config({**_TCP, "backend": None}).backend == "auto"

    @pytest.mark.parametrize("backend", ["pymodbus", "modbus_connection"])
    @pytest.mark.parametrize("item", [_TCP, _SERIAL])
    def test_stored_backend_reaches_config(
        self, item: dict[str, Any], backend: str
    ) -> None:
        assert _config({**item, "backend": backend}).backend == backend

    def test_invalid_backend_skips_only_that_device(self) -> None:
        configs = _build_transport_configs(
            [{**_TCP, "backend": "bogus"}, dict(_SERIAL)]
        )
        assert [c.serial for c in configs] == ["SYNTH10002"]

    def test_dongle_ignores_backend(self) -> None:
        dongle = {
            "serial": "SYNTH10003",
            "transport_type": "wifi_dongle",
            "host": "192.0.2.11",
            "port": 8000,
            "dongle_serial": "SYNTHDONGL",
            "backend": "modbus_connection",
        }
        assert _config(dongle).backend == "auto"

    def test_pylxpweb_without_backend_field_drops_key(self) -> None:
        """Older pylxpweb has no ``backend`` field: omit it, never TypeError."""
        legacy = dataclasses.make_dataclass("TransportConfig", [("host", str, "")])
        with patch("pylxpweb.transports.config.TransportConfig", legacy):
            assert _transport_config_backend_kwargs({"backend": "pymodbus"}) == {}


@pytest.fixture
def entry() -> Any:
    return SimpleNamespace(entry_id="synthetic-entry")


@pytest.fixture
def fallback() -> MagicMock:
    return MagicMock(name="owned_factory", return_value=object())


def _factory(get_unit: Any, entry: Any, fallback: MagicMock) -> Any:
    with patch.object(ha_modbus, "_load_async_get_unit", return_value=get_unit):
        return ha_modbus.build_shared_unit_factory(MagicMock(), entry, fallback)


class TestSharedUnitFactory:
    def test_without_async_get_unit_returns_fallback(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        assert _factory(None, entry, fallback) is fallback

    def test_without_unit_seam_returns_fallback(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        with patch.object(ha_modbus, "_transport_accepts_unit", return_value=False):
            assert _factory(MagicMock(), entry, fallback) is fallback

    @pytest.mark.parametrize(
        "item",
        [
            _TCP,
            _SERIAL,
            {**_TCP, "backend": "pymodbus"},
            {**_ESPHOME, "backend": "pymodbus"},
        ],
    )
    def test_pymodbus_resolution_keeps_owned_path(
        self, item: dict[str, Any], entry: Any, fallback: MagicMock
    ) -> None:
        get_unit = MagicMock()
        factory = _factory(get_unit, entry, fallback)
        config = _config(item)

        assert factory(config) is fallback.return_value
        fallback.assert_called_once_with(config)
        get_unit.assert_not_called()

    def test_esphome_auto_gets_shared_serial_unit(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        unit = _FakeUnit()
        get_unit = MagicMock(return_value=unit)
        factory = _factory(get_unit, entry, fallback)

        transport = factory(_config(_ESPHOME))

        assert isinstance(transport, ModbusSerialTransport)
        assert transport._external_unit is unit
        fallback.assert_not_called()
        hass_arg, entry_arg, params, unit_id = get_unit.call_args.args
        assert entry_arg is entry
        assert unit_id == 1
        assert params.endpoint == ("serial", "esphome://esp-rs485.local:6053")
        assert (params.baudrate, params.parity, params.stopbits) == (19200, "N", 1)

    def test_explicit_tcp_backend_gets_shared_tcp_unit(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        get_unit = MagicMock(return_value=_FakeUnit())
        factory = _factory(get_unit, entry, fallback)

        transport = factory(_config({**_TCP, "backend": "modbus_connection"}))

        assert isinstance(transport, ModbusTransport)
        params = get_unit.call_args.args[2]
        assert (params.host, params.port) == ("192.0.2.10", 502)

    def test_recreating_a_capability_reuses_the_hold(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        unit = _FakeUnit()
        get_unit = MagicMock(return_value=unit)
        factory = _factory(get_unit, entry, fallback)

        first = factory(_config(_ESPHOME))
        second = factory(_config(_ESPHOME))

        assert first is not second
        assert first._external_unit is second._external_unit is unit
        get_unit.assert_called_once()

    def test_distinct_unit_ids_take_distinct_units(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        get_unit = MagicMock(side_effect=lambda *a: _FakeUnit())
        factory = _factory(get_unit, entry, fallback)

        factory(_config(_ESPHOME))
        factory(_config({**_ESPHOME, "serial": "SYNTH10004", "unit_id": 2}))

        assert get_unit.call_count == 2

    def test_link_settings_clash_falls_back_to_owned_link(
        self, entry: Any, fallback: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        get_unit = MagicMock(side_effect=HomeAssistantError("different settings"))
        factory = _factory(get_unit, entry, fallback)

        assert factory(_config(_ESPHOME)) is fallback.return_value
        assert "different link settings" in caplog.text


def test_registry_uses_per_call_factory() -> None:
    """The shared registry keeps its own factory unless a call overrides it."""
    probe = _WireProbe()
    default = MagicMock(name="default_factory")
    override = MagicMock(
        name="entry_factory", side_effect=lambda c: _FakeRawTransport(c, probe)
    )
    registry = EndpointBusRegistry(raw_transport_factory=default)
    assert registry.raw_transport_factory is default

    config = _owner_config("SYNTH10005")
    capability = registry.create_capability(config, raw_transport_factory=override)

    assert isinstance(capability, EndpointBusCapability)
    override.assert_called_once_with(config)
    default.assert_not_called()


def test_load_async_get_unit_matches_installed_core() -> None:
    """Feature detection agrees with what this Home Assistant actually ships."""
    try:
        from homeassistant.components.modbus import async_get_unit
    except ImportError:
        assert ha_modbus._load_async_get_unit() is None
    else:
        assert ha_modbus._load_async_get_unit() is async_get_unit


async def test_real_async_get_unit_holds_until_entry_unloads(hass: Any) -> None:
    """Against core's real helper: one hold per link, released on unload."""
    modbus = pytest.importorskip("homeassistant.components.modbus")
    if not hasattr(modbus, "async_get_unit"):
        pytest.skip("Home Assistant core predates async_get_unit (2026.9)")
    from homeassistant.components.modbus.connection import DATA_MODBUS_CONNECTIONS
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="eg4_web_monitor")
    entry.add_to_hass(hass)
    fallback = MagicMock(name="owned_factory")
    factory = ha_modbus.build_shared_unit_factory(hass, entry, fallback)

    first = factory(_config(_ESPHOME))
    second = factory(_config(_ESPHOME))

    assert isinstance(first, ModbusSerialTransport)
    assert first._external_unit is second._external_unit
    fallback.assert_not_called()
    shared = hass.data[DATA_MODBUS_CONNECTIONS][
        ("serial", "esphome://esp-rs485.local:6053")
    ]
    assert shared.consumers == 1

    for unload in entry._on_unload or []:
        result = unload()
        if result is not None:
            await result
    assert ("serial", "esphome://esp-rs485.local:6053") not in hass.data[
        DATA_MODBUS_CONNECTIONS
    ]
