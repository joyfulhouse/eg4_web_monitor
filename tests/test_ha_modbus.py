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
import sys
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

    @pytest.mark.parametrize("backend", ["pymodbus", "PyModbus"])
    def test_pymodbus_on_esphome_port_is_ignored(
        self, backend: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """pymodbus cannot open ``esphome://``: a hand-edited value falls back."""
        assert _config({**_ESPHOME, "backend": backend}).backend == "auto"
        assert "pymodbus cannot open esphome://" in caplog.text

    def test_modbus_connection_on_esphome_port_is_kept(self) -> None:
        item = {**_ESPHOME, "backend": "modbus_connection"}
        assert _config(item).backend == "modbus_connection"

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


class _TimeoutRecordingUnit(_FakeUnit):
    def __init__(self) -> None:
        self.required: list[float | None] = []

    def require_timeout(self, seconds: float | None) -> None:
        self.required.append(seconds)


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
            {**_SERIAL, "backend": "pymodbus"},
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

    def test_shared_unit_gets_the_transport_timeout(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        unit = _TimeoutRecordingUnit()
        factory = _factory(MagicMock(return_value=unit), entry, fallback)
        config = dataclasses.replace(_config(_ESPHOME), timeout=25.0)

        factory(config)
        factory(config)

        assert unit.required == [25.0]

    def test_unit_without_require_timeout_still_works(
        self, entry: Any, fallback: MagicMock
    ) -> None:
        """modbus-connection before 4.12.0 (HA 2026.9 pins 4.10.0) lacks it."""
        unit = _FakeUnit()
        assert not hasattr(unit, "require_timeout")
        factory = _factory(MagicMock(return_value=unit), entry, fallback)

        assert factory(_config(_ESPHOME))._external_unit is unit

    def test_link_settings_clash_falls_back_to_owned_link(
        self, entry: Any, fallback: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        get_unit = MagicMock(side_effect=HomeAssistantError("different settings"))
        factory = _factory(get_unit, entry, fallback)

        assert factory(_config(_ESPHOME)) is fallback.return_value
        assert "different link settings" in caplog.text


_RESOLUTION_CASES = [
    (_TCP, False),
    (_SERIAL, False),
    (_ESPHOME, True),
    ({**_ESPHOME, "serial_port": "ESPHOME://ESP.LOCAL:6053"}, True),
    ({**_TCP, "backend": "modbus_connection"}, True),
    ({**_SERIAL, "backend": "pymodbus"}, False),
    ({**_ESPHOME, "backend": "modbus_connection"}, True),
]


@pytest.mark.parametrize(("item", "expected"), _RESOLUTION_CASES)
def test_resolution_without_private_pylxpweb_module(
    item: dict[str, Any], expected: bool
) -> None:
    """A pylxpweb that moves ``_modbus_client`` still resolves the same way."""
    config = _config(item)
    assert ha_modbus._resolves_to_modbus_connection(config) is expected
    with patch.dict(sys.modules, {"pylxpweb.transports._modbus_client": None}):
        assert ha_modbus._resolves_to_modbus_connection(config) is expected


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

    endpoint = ("serial", "esphome://esp-rs485.local:6053")
    config = dataclasses.replace(_config(_ESPHOME), timeout=25.0)
    first = factory(config)
    second = factory(config)

    assert isinstance(first, ModbusSerialTransport)
    assert first._external_unit is second._external_unit
    fallback.assert_not_called()
    shared = hass.data[DATA_MODBUS_CONNECTIONS][endpoint]
    assert shared.consumers == 1
    if hasattr(first._external_unit, "require_timeout"):
        # modbus-connection 4.12.0+: the link honours the transport timeout.
        assert shared.connection._timeout == 25.0

    # The transport only attaches to and detaches from the shared unit: its
    # own connect/disconnect neither dials nor releases the hold.
    await first.connect()
    assert first.is_connected
    assert first.backend_shares_link
    await first.disconnect()
    assert not first.is_connected
    assert shared.consumers == 1
    assert hass.data[DATA_MODBUS_CONNECTIONS][endpoint] is shared
    assert not shared.connection._closed

    # Only the entry unload releases the hold and closes the connection.
    for unload in entry._on_unload or []:
        result = unload()
        if result is not None:
            await result
    assert endpoint not in hass.data[DATA_MODBUS_CONNECTIONS]
    assert shared.consumers == 0
    assert shared.connection._closed


async def test_coordinator_capability_carries_shared_unit(hass: Any) -> None:
    """The coordinator's capabilities use its shared-unit factory.

    An ``esphome://`` port under ``auto`` runs on core's shared unit; a TCP
    gateway under ``auto`` keeps the owned pymodbus link.
    """
    modbus = pytest.importorskip("homeassistant.components.modbus")
    if not hasattr(modbus, "async_get_unit"):
        pytest.skip("Home Assistant core predates async_get_unit (2026.9)")
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.eg4_web_monitor.const import (
        CONF_CONNECTION_TYPE,
        CONNECTION_TYPE_LOCAL,
        DOMAIN,
    )
    from custom_components.eg4_web_monitor.coordinator import (
        EG4DataUpdateCoordinator,
    )

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
    )
    entry.add_to_hass(hass)
    coordinator = EG4DataUpdateCoordinator(hass, entry)

    def raw_of(capability: EndpointBusCapability) -> Any:
        return capability._owner._records[capability._token].raw

    esphome = coordinator._create_bus_capability(_config(_ESPHOME))
    tcp = coordinator._create_bus_capability(_config(_TCP))
    try:
        esphome_raw = raw_of(esphome)
        assert isinstance(esphome_raw, ModbusSerialTransport)
        assert esphome_raw._external_unit is not None

        tcp_raw = raw_of(tcp)
        assert isinstance(tcp_raw, ModbusTransport)
        assert tcp_raw._external_unit is None
        assert tcp_raw._backend == "pymodbus"
    finally:
        await coordinator._endpoint_bus_registry.async_shutdown_capabilities(
            [esphome, tcp]
        )
        await coordinator.async_shutdown()
