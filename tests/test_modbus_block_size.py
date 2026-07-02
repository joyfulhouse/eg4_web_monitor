"""Modbus read block size option wiring (#254).

The options-flow preset (Conservative/Fast) maps to pylxpweb's
``max_input_block_size`` (40/120). The parameter shipped AFTER pylxpweb
0.9.36b19, so every transport-construction site feature-detects it:

- installed pylxpweb supports it -> transports receive the kwarg;
- released pylxpweb (0.9.36b19) -> silently conservative ({} kwargs, one
  warning), never a TypeError.

These tests run against the real installed pylxpweb (0.9.36b19 in CI at the
time of writing), so the "unsupported" cases exercise the genuine release
and the "supported" cases patch in stand-in classes that carry the
parameter/field.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.eg4_web_monitor.const import (
    BLOCK_SIZE_CONSERVATIVE,
    BLOCK_SIZE_FAST,
    BLOCK_SIZE_PRESET_REGISTERS,
    CONF_CONNECTION_TYPE,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_BLOCK_SIZE,
    CONF_MODBUS_HOST,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_MODBUS_BLOCK_SIZE,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_transport_configs,
    _warn_block_size_unsupported,
    input_block_size_kwargs,
    transport_config_block_size_kwargs,
)


class _SupportingTransport:
    """Stand-in ModbusTransport whose constructor accepts the parameter."""

    def __init__(
        self,
        host: str,
        serial: str = "",
        max_input_block_size: int = 40,
        **kwargs: Any,
    ) -> None:
        self.max_input_block_size = max_input_block_size


@dataclasses.dataclass
class _SupportingTransportConfig:
    """Stand-in TransportConfig dataclass that defines the field."""

    host: str = ""
    port: int = 502
    serial: str = ""
    transport_type: Any = None
    inverter_family: Any = None
    unit_id: int = 1
    dongle_serial: str | None = None
    serial_port: str | None = None
    serial_baudrate: int = 19200
    serial_parity: str = "N"
    serial_stopbits: int = 1
    max_input_block_size: int = 40


@pytest.fixture(autouse=True)
def _reset_warn_once() -> None:
    """Re-arm the warn-once latch between tests."""
    _warn_block_size_unsupported.cache_clear()


# ---------------------------------------------------------------------------
# Preset mapping
# ---------------------------------------------------------------------------


class TestPresetMapping:
    def test_presets(self) -> None:
        assert BLOCK_SIZE_PRESET_REGISTERS[BLOCK_SIZE_CONSERVATIVE] == 40
        assert BLOCK_SIZE_PRESET_REGISTERS[BLOCK_SIZE_FAST] == 120
        assert DEFAULT_MODBUS_BLOCK_SIZE == BLOCK_SIZE_CONSERVATIVE


# ---------------------------------------------------------------------------
# input_block_size_kwargs (constructor-signature feature detection)
# ---------------------------------------------------------------------------


class TestInputBlockSizeKwargs:
    def test_conservative_needs_no_kwargs(self) -> None:
        assert input_block_size_kwargs(40) == {}

    def test_fast_on_released_pylxpweb_is_silently_conservative(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """0.9.36b19 lacks the parameter: {} kwargs plus one warning."""
        from pylxpweb.transports import ModbusTransport
        import inspect

        if (
            "max_input_block_size"
            in inspect.signature(ModbusTransport.__init__).parameters
        ):
            pytest.skip("installed pylxpweb already supports max_input_block_size")

        with caplog.at_level(logging.WARNING):
            assert input_block_size_kwargs(120) == {}
            assert input_block_size_kwargs(120) == {}  # second call: no re-warn

        warnings = [r for r in caplog.records if "max_input_block_size" in r.message]
        assert len(warnings) == 1

    def test_fast_on_supporting_pylxpweb_passes_kwarg(self) -> None:
        with patch("pylxpweb.transports.ModbusTransport", _SupportingTransport):
            assert input_block_size_kwargs(120) == {"max_input_block_size": 120}


# ---------------------------------------------------------------------------
# transport_config_block_size_kwargs (dataclass-field feature detection)
# ---------------------------------------------------------------------------


class TestTransportConfigBlockSizeKwargs:
    def test_conservative_needs_no_kwargs(self) -> None:
        assert transport_config_block_size_kwargs(40) == {}

    def test_fast_on_released_pylxpweb_is_silently_conservative(self) -> None:
        from pylxpweb.transports.config import TransportConfig

        if any(
            f.name == "max_input_block_size"
            for f in dataclasses.fields(TransportConfig)
        ):
            pytest.skip("installed pylxpweb already supports max_input_block_size")

        assert transport_config_block_size_kwargs(120) == {}

    def test_fast_on_supporting_pylxpweb_passes_kwarg(self) -> None:
        with patch(
            "pylxpweb.transports.config.TransportConfig", _SupportingTransportConfig
        ):
            assert transport_config_block_size_kwargs(120) == {
                "max_input_block_size": 120
            }


# ---------------------------------------------------------------------------
# _build_transport_configs plumbing (hybrid attach path)
# ---------------------------------------------------------------------------

_TCP_DICT = {
    "serial": "CE12345678",
    "transport_type": "modbus_tcp",
    "host": "192.168.1.100",
    "port": 502,
    "unit_id": 1,
    "inverter_family": "EG4_HYBRID",
}


class TestBuildTransportConfigs:
    def test_fast_on_released_pylxpweb_builds_without_field(self) -> None:
        """No TypeError and no dropped configs on 0.9.36b19."""
        configs = _build_transport_configs([dict(_TCP_DICT)], 120)
        assert len(configs) == 1
        assert configs[0].serial == "CE12345678"

    def test_none_block_size_builds_unchanged(self) -> None:
        configs = _build_transport_configs([dict(_TCP_DICT)])
        assert len(configs) == 1

    def test_fast_on_supporting_pylxpweb_sets_field(self) -> None:
        with patch(
            "pylxpweb.transports.config.TransportConfig", _SupportingTransportConfig
        ):
            configs = _build_transport_configs([dict(_TCP_DICT)], 120)
        assert len(configs) == 1
        assert configs[0].max_input_block_size == 120

    def test_conservative_never_sets_field(self) -> None:
        with patch(
            "pylxpweb.transports.config.TransportConfig", _SupportingTransportConfig
        ):
            configs = _build_transport_configs([dict(_TCP_DICT)], 40)
        assert len(configs) == 1
        assert configs[0].max_input_block_size == 40  # dataclass default, not set


# ---------------------------------------------------------------------------
# Coordinator option mapping + legacy transport construction
# ---------------------------------------------------------------------------


def _mock_hass() -> MagicMock:
    hass = MagicMock()
    hass.config.time_zone = "America/Los_Angeles"
    hass.bus.async_listen_once = MagicMock()
    return hass


def _legacy_modbus_entry(options: dict[str, Any] | None = None) -> MagicMock:
    """Legacy flat-key MODBUS entry (pre-v3.2 format, no local_transports)."""
    entry = MagicMock()
    entry.data = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS,
        CONF_MODBUS_HOST: "192.168.1.100",
        CONF_INVERTER_SERIAL: "CE12345678",
    }
    entry.options = options or {}
    return entry


class TestCoordinatorOptionMapping:
    def test_default_is_conservative(self) -> None:
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport"),
        ):
            coordinator = EG4DataUpdateCoordinator(_mock_hass(), _legacy_modbus_entry())
        assert coordinator._max_input_block_size == 40

    def test_fast_maps_to_120(self) -> None:
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport"),
        ):
            coordinator = EG4DataUpdateCoordinator(
                _mock_hass(),
                _legacy_modbus_entry({CONF_MODBUS_BLOCK_SIZE: BLOCK_SIZE_FAST}),
            )
        assert coordinator._max_input_block_size == 120

    def test_unknown_preset_falls_back_to_conservative(self) -> None:
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport"),
        ):
            coordinator = EG4DataUpdateCoordinator(
                _mock_hass(),
                _legacy_modbus_entry({CONF_MODBUS_BLOCK_SIZE: "warp-speed"}),
            )
        assert coordinator._max_input_block_size == 40


class TestLegacyTransportConstruction:
    """The pre-v3.2 flat-key path forwards the option (feature-detected)."""

    def test_fast_with_supporting_lib_passes_kwarg(self) -> None:
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport") as mock_create,
            patch(
                "custom_components.eg4_web_monitor.coordinator.input_block_size_kwargs",
                return_value={"max_input_block_size": 120},
            ),
        ):
            EG4DataUpdateCoordinator(
                _mock_hass(),
                _legacy_modbus_entry({CONF_MODBUS_BLOCK_SIZE: BLOCK_SIZE_FAST}),
            )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["max_input_block_size"] == 120

    def test_fast_with_released_lib_stays_conservative(self) -> None:
        """Against real 0.9.36b19 detection, the kwarg is simply absent."""
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport") as mock_create,
        ):
            EG4DataUpdateCoordinator(
                _mock_hass(),
                _legacy_modbus_entry({CONF_MODBUS_BLOCK_SIZE: BLOCK_SIZE_FAST}),
            )

        mock_create.assert_called_once()
        assert "max_input_block_size" not in mock_create.call_args.kwargs

    def test_conservative_never_passes_kwarg(self) -> None:
        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport") as mock_create,
        ):
            EG4DataUpdateCoordinator(_mock_hass(), _legacy_modbus_entry())

        mock_create.assert_called_once()
        assert "max_input_block_size" not in mock_create.call_args.kwargs
