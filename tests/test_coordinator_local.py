"""Tests for the local transport coordinator mixin (coordinator_local.py).

Covers methods not already tested in test_coordinator.py:
- _read_modbus_parameters
- _build_local_device_data
- get_local_transport / has_local_transport / is_local_only
- _attach_local_transports_to_station
- _log_transport_error
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import (
    EG4DataUpdateCoordinator,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def local_config_entry():
    """Config entry for LOCAL mode with one inverter."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Local Test",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "INV001",
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        options={},
        entry_id="local_test",
    )


@pytest.fixture
def hybrid_config_entry():
    """Config entry for HYBRID mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Test",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "INV001",
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        options={},
        entry_id="hybrid_test",
    )


@pytest.fixture
def http_config_entry():
    """Config entry for HTTP-only mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - HTTP Test",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        },
        options={},
        entry_id="http_test",
    )


# ── _read_modbus_parameters ─────────────────────────────────────────


class TestReadModbusParameters:
    """Test reading configuration parameters from Modbus registers."""

    async def test_reads_all_register_ranges(self, hass, local_config_entry):
        """All 11 register ranges are read."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock()
        mock_transport.read_named_parameters = AsyncMock(return_value={"PARAM_A": True})

        result = await coordinator._read_modbus_parameters(mock_transport)

        # 11 register ranges: 20-22, 64-79, 82-83, 101-102, 105-106, 110, 125, 179, 227, 231-232, 233
        assert mock_transport.read_named_parameters.call_count == 11
        assert "PARAM_A" in result

    async def test_partial_failure_continues(self, hass, local_config_entry):
        """One register range failing doesn't stop the rest."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        call_count = 0

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if start == 20:
                raise RuntimeError("range 20 failed")
            return {f"param_{start}": start}

        mock_transport = MagicMock()
        mock_transport.read_named_parameters = AsyncMock(side_effect=mock_read)

        result = await coordinator._read_modbus_parameters(mock_transport)

        # All 11 ranges attempted despite first failure
        assert call_count == 11
        # Successful ranges contributed their params
        assert len(result) == 10  # 11 total - 1 failed

    async def test_total_failure_returns_empty(self, hass, local_config_entry):
        """All register ranges failing returns empty dict."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock()
        mock_transport.read_named_parameters = AsyncMock(
            side_effect=RuntimeError("all fail")
        )

        result = await coordinator._read_modbus_parameters(mock_transport)

        assert result == {}

    async def test_outer_exception_returns_empty(self, hass, local_config_entry):
        """Exception before the loop returns empty dict."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # Transport without read_named_parameters
        mock_transport = MagicMock(spec=[])

        result = await coordinator._read_modbus_parameters(mock_transport)

        assert result == {}


# ── _build_local_device_data ─────────────────────────────────────────


class TestBuildLocalDeviceData:
    """Test building device data structure from inverter transport data."""

    async def test_basic_structure(self, hass, local_config_entry):
        """Device data has expected keys."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter._transport_runtime = MagicMock()
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = None
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.host = "192.168.1.100"
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"pv_total_power": 5000},
        ):
            result = coordinator._build_local_device_data(
                inverter=mock_inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["type"] == "inverter"
        assert result["model"] == "FlexBOSS21"
        assert result["serial"] == "INV001"
        assert result["firmware_version"] == "ARM-1.0"
        assert result["sensors"]["firmware_version"] == "ARM-1.0"
        assert result["sensors"]["transport_host"] == "192.168.1.100"
        assert result["batteries"] == {}

    async def test_includes_energy_data(self, hass, local_config_entry):
        """Energy data is merged into sensors when available."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter._transport_runtime = MagicMock()
        mock_inverter._transport_energy = MagicMock()
        mock_inverter._transport_battery = None
        mock_inverter._transport = None
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"pv_total_power": 5000},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_energy_sensor_mapping",
                return_value={"yield": 25.0},
            ),
        ):
            result = coordinator._build_local_device_data(
                inverter=mock_inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["sensors"]["yield"] == 25.0

    async def test_includes_computed_sensors(self, hass, local_config_entry):
        """Computed sensors from inverter properties are included."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter._transport_runtime = MagicMock()
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = None
        mock_inverter._transport = None
        mock_inverter.consumption_power = 3000
        mock_inverter.battery_power = 1500
        mock_inverter.rectifier_power = 200
        mock_inverter.power_to_user = 500

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={},
        ):
            result = coordinator._build_local_device_data(
                inverter=mock_inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["sensors"]["consumption_power"] == 3000
        assert result["sensors"]["battery_power"] == 1500
        assert result["sensors"]["rectifier_power"] == 200
        assert result["sensors"]["grid_import_power"] == 500


# ── get_local_transport / has_local_transport / is_local_only ────────


class TestTransportAccessors:
    """Test transport accessor methods."""

    def test_get_local_transport_from_inverter_cache(self, hass, local_config_entry):
        """LOCAL mode: get_local_transport returns transport from inverter cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock()
        mock_inverter = MagicMock()
        mock_inverter._transport = mock_transport
        coordinator._inverter_cache["INV001"] = mock_inverter

        result = coordinator.get_local_transport("INV001")
        assert result is mock_transport

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_from_station(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode: get_local_transport from station inverter."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_transport = MagicMock()
        mock_inverter = MagicMock()
        mock_inverter._transport = mock_transport
        mock_inverter.serial_number = "INV001"

        mock_station = MagicMock()
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        # Patch get_inverter_object to return our mock
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        result = coordinator.get_local_transport("INV001")
        assert result is mock_transport

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_returns_none_http_only(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """HTTP-only mode: get_local_transport returns None."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        result = coordinator.get_local_transport("INV001")
        assert result is None

    def test_has_local_transport_true(self, hass, local_config_entry):
        """has_local_transport returns True when transport exists."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter._transport = MagicMock()
        coordinator._inverter_cache["INV001"] = mock_inverter

        assert coordinator.has_local_transport("INV001") is True

    def test_has_local_transport_false(self, hass, local_config_entry):
        """has_local_transport returns False when no transport."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        assert coordinator.has_local_transport("UNKNOWN") is False

    def test_has_local_transport_no_serial_deprecated(self, hass, local_config_entry):
        """has_local_transport without serial checks deprecated fields."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # No deprecated transports set
        assert coordinator.has_local_transport() is False

    def test_get_local_transport_from_mid_device_cache(self, hass, local_config_entry):
        """LOCAL mode: get_local_transport returns transport from MID device cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock()
        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        coordinator._mid_device_cache["GRIDBOSS001"] = mock_mid

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is mock_transport

    def test_has_local_transport_true_for_mid_device(self, hass, local_config_entry):
        """has_local_transport returns True for GridBOSS serial in MID cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_mid = MagicMock()
        mock_mid._transport = MagicMock()
        coordinator._mid_device_cache["GRIDBOSS001"] = mock_mid

        assert coordinator.has_local_transport("GRIDBOSS001") is True

    def test_get_local_transport_mid_device_no_transport(
        self, hass, local_config_entry
    ):
        """MID device without _transport attribute returns None."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_mid = MagicMock(spec=[])  # No attributes
        coordinator._mid_device_cache["GRIDBOSS001"] = mock_mid

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is None

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_from_station_mid_device(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode: get_local_transport finds MID device via station (#182)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_transport = MagicMock()
        mock_mid = MagicMock()
        mock_mid.serial_number = "GRIDBOSS001"
        mock_mid._transport = mock_transport

        mock_station = MagicMock()
        mock_station.all_inverters = []
        mock_station.all_mid_devices = [mock_mid]
        coordinator.station = mock_station

        # Inverter lookup returns None (GridBOSS is not an inverter)
        coordinator.get_inverter_object = MagicMock(return_value=None)

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is mock_transport

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_station_mid_no_transport(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode: station MID device without transport returns None."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_mid = MagicMock(spec=[])  # No _transport attribute
        mock_mid.serial_number = "GRIDBOSS001"

        mock_station = MagicMock()
        mock_station.all_inverters = []
        mock_station.all_mid_devices = [mock_mid]
        coordinator.station = mock_station
        coordinator.get_inverter_object = MagicMock(return_value=None)

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is None

    def test_is_local_only_local_mode(self, hass, local_config_entry):
        """LOCAL mode → is_local_only returns True."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator.is_local_only() is True

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_is_local_only_http_mode(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """HTTP mode → is_local_only returns False."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator.is_local_only() is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_is_local_only_hybrid_mode(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode → is_local_only returns False."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        assert coordinator.is_local_only() is False


# ── write_smart_port_mode ──────────────────────────────────────────────


class TestWriteSmartPortMode:
    """Tests for coordinator.write_smart_port_mode() (#182)."""

    @pytest.mark.asyncio
    async def test_write_via_local_transport(self, hass, local_config_entry):
        """Local transport path: writes via transport.write_named_parameters."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = AsyncMock()
        mock_transport.is_connected = True
        mock_transport.write_named_parameters = AsyncMock(return_value=True)

        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        coordinator._mid_device_cache["GB001"] = mock_mid

        result = await coordinator.write_smart_port_mode("GB001", 2, 1)

        assert result is True
        mock_transport.write_named_parameters.assert_called_once_with(
            {"BIT_MIDBOX_SP_MODE_2": 1}
        )

    @pytest.mark.asyncio
    async def test_write_reconnects_transport(self, hass, local_config_entry):
        """Reconnects transport if not connected before writing."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = AsyncMock()
        mock_transport.is_connected = False
        mock_transport.connect = AsyncMock()
        mock_transport.write_named_parameters = AsyncMock(return_value=True)

        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        coordinator._mid_device_cache["GB001"] = mock_mid

        await coordinator.write_smart_port_mode("GB001", 1, 2)

        mock_transport.connect.assert_called_once()
        mock_transport.write_named_parameters.assert_called_once()

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_write_via_cloud_api(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Cloud API path: writes via client.api.control.set_smart_port_mode."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        result_mock = MagicMock()
        result_mock.success = True
        coordinator.client.api.control.set_smart_port_mode = AsyncMock(
            return_value=result_mock
        )

        result = await coordinator.write_smart_port_mode("GB001", 3, 0)

        assert result is True
        coordinator.client.api.control.set_smart_port_mode.assert_called_once_with(
            "GB001", 3, 0
        )

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_local_failure_falls_back_to_cloud(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Local transport failure falls back to cloud API."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_transport = AsyncMock()
        mock_transport.is_connected = True
        mock_transport.write_named_parameters = AsyncMock(
            side_effect=Exception("Modbus timeout")
        )
        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        coordinator._mid_device_cache["GB001"] = mock_mid

        result_mock = MagicMock()
        result_mock.success = True
        coordinator.client.api.control.set_smart_port_mode = AsyncMock(
            return_value=result_mock
        )

        result = await coordinator.write_smart_port_mode("GB001", 4, 2)

        assert result is True
        coordinator.client.api.control.set_smart_port_mode.assert_called_once_with(
            "GB001", 4, 2
        )

    @pytest.mark.asyncio
    async def test_no_transport_no_client_raises(self, hass, local_config_entry):
        """No local transport and no cloud API raises HomeAssistantError."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        with pytest.raises(HomeAssistantError, match="No local transport or cloud API"):
            await coordinator.write_smart_port_mode("GB001", 1, 1)

    @pytest.mark.asyncio
    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_cloud_failure_raises(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Cloud API returning failure raises HomeAssistantError."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        result_mock = MagicMock()
        result_mock.success = False
        coordinator.client.api.control.set_smart_port_mode = AsyncMock(
            return_value=result_mock
        )

        with pytest.raises(HomeAssistantError, match="Cloud API failed"):
            await coordinator.write_smart_port_mode("GB001", 2, 1)


# ── get_mid_device_object ──────────────────────────────────────────────


class TestGetMidDeviceObject:
    """Tests for coordinator.get_mid_device_object() (#182)."""

    def test_from_mid_device_cache(self, hass, local_config_entry):
        """Finds MID device in LOCAL mode cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_mid = MagicMock()
        coordinator._mid_device_cache["GB001"] = mock_mid

        result = coordinator.get_mid_device_object("GB001")
        assert result is mock_mid

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_from_station_mid_devices(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Finds MID device via station in HYBRID mode."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_mid = MagicMock()
        mock_mid.serial_number = "GB001"

        mock_station = MagicMock()
        mock_station.all_mid_devices = [mock_mid]
        coordinator.station = mock_station

        result = coordinator.get_mid_device_object("GB001")
        assert result is mock_mid

    def test_not_found_returns_none(self, hass, local_config_entry):
        """Returns None when MID device not found anywhere."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        result = coordinator.get_mid_device_object("UNKNOWN")
        assert result is None

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_cache_takes_precedence_over_station(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """LOCAL cache is checked before station (for performance)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        cached_mid = MagicMock()
        coordinator._mid_device_cache["GB001"] = cached_mid

        station_mid = MagicMock()
        station_mid.serial_number = "GB001"
        mock_station = MagicMock()
        mock_station.all_mid_devices = [station_mid]
        coordinator.station = mock_station

        # Cache should win
        result = coordinator.get_mid_device_object("GB001")
        assert result is cached_mid


# ── _attach_local_transports_to_station ──────────────────────────────


class TestAttachLocalTransports:
    """Test attaching local transports to station devices."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_station_returns_early(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """No station → returns without attaching."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = None

        await coordinator._attach_local_transports_to_station()
        assert coordinator._local_transports_attached is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_successful_attachment(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Successful attachment sets flag to True."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is True
        mock_station.attach_local_transports.assert_called_once()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attachment_failure_keeps_flag_false(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Attachment error keeps flag False for retry."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(
            side_effect=RuntimeError("connection failed")
        )
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_valid_configs_returns_early(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Empty transport configs list → returns without attaching."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = MagicMock()

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[],
        ):
            await coordinator._attach_local_transports_to_station()

        # station.attach_local_transports should NOT be called
        coordinator.station.attach_local_transports.assert_not_called()


class TestAttachForcedTransportRead:
    """Test transport attachment does NOT issue a forced read.

    asyncio.wait_for() with Python 3.11 does not interrupt in-flight pymodbus
    reads — it waits for the inner task to finish before raising TimeoutError.
    On HA restart the Waveshare gateway has stale RS485 responses buffered,
    causing reads to fail for 3–5 minutes. A forced refresh here would block
    async_config_entry_first_refresh() for the entire duration, causing HA's
    setup timeout to fire and cancel entity setup (setup_error). Data is
    populated by the first regular poll instead.
    """

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_does_not_force_transport_read(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """No refresh() call is issued after transport attachment."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        mock_inverter = MagicMock()
        mock_inverter._transport = MagicMock()
        mock_inverter.serial_number = "1234567890"
        mock_inverter.refresh = AsyncMock()

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is True
        # No forced read — data will be populated on the first regular poll
        mock_inverter.refresh.assert_not_called()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_completes_when_inverter_has_no_transport(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Attachment loop handles inverters without a transport gracefully."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        # Inverter with no transport attached (e.g. unmatched serial)
        mock_inverter = MagicMock()
        mock_inverter._transport = None
        mock_inverter.serial_number = "1234567890"
        mock_inverter.refresh = AsyncMock()

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        # Attachment still marks as attached; no refresh for transportless inverter
        assert coordinator._local_transports_attached is True
        mock_inverter.refresh.assert_not_called()


# ── _log_transport_error ─────────────────────────────────────────────


class TestLogTransportError:
    """Test transport error logging."""

    def test_first_error_updates_availability(self, hass, local_config_entry):
        """First error sets availability to False."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator._last_available_state is True

        coordinator._log_transport_error(
            "Modbus error", "INV001", RuntimeError("timeout")
        )

        assert coordinator._last_available_state is False

    def test_subsequent_error_no_warning(self, hass, local_config_entry):
        """Subsequent errors when already unavailable don't log warning again."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._last_available_state = False

        # Should not log warning (already unavailable)
        coordinator._log_transport_error(
            "Modbus error", "INV001", RuntimeError("timeout")
        )

        assert coordinator._last_available_state is False


# ── _async_update_local_data edge cases ──────────────────────────────


class TestAsyncUpdateLocalDataEdgeCases:
    """Edge cases for _async_update_local_data not covered by test_coordinator.py."""

    async def test_no_transports_configured_raises(self, hass):
        """No local transports → UpdateFailed."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Empty",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            entry_id="empty_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        with pytest.raises(UpdateFailed, match="No local transports configured"):
            await coordinator._async_update_local_data()

    async def test_invalid_config_skipped(self, hass):
        """Config with missing serial is skipped."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Invalid",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        # Missing serial
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                    },
                ],
            },
            entry_id="invalid_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        with pytest.raises(UpdateFailed, match="All .* local transports failed"):
            await coordinator._async_update_local_data()


class TestGridBOSSFirmwareCache:
    """GridBOSS firmware version should be read from transport and cached (#156)."""

    async def test_gridboss_firmware_read_from_transport(self, hass):
        """GridBOSS firmware is read via transport.read_firmware_version(), not MIDDevice property."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GridBOSS FW",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.200",
                        "port": 502,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "MID_DEVICE",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                        "dongle_serial": "D001",
                    },
                ],
            },
            entry_id="gb_fw_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        # Build a mock MIDDevice with a transport that returns firmware
        mock_transport = MagicMock()
        mock_transport.is_connected = True
        mock_transport.read_firmware_version = AsyncMock(return_value="IAAB-1600")

        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        mock_mid.has_data = True
        mock_mid.refresh = AsyncMock()
        # MIDDevice.firmware_version property returns None (the bug scenario)
        mock_mid.firmware_version = None

        coordinator._mid_device_cache["GB001"] = mock_mid

        # Mock out the sensor mapping and other helpers
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_gridboss_sensor_mapping",
                return_value={"grid_voltage": 240.0},
            ),
            patch.object(coordinator, "_filter_unused_smart_port_sensors"),
            patch.object(coordinator, "_calculate_gridboss_aggregates"),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        # Firmware should come from transport, not the MIDDevice property
        device_data = processed["devices"]["GB001"]
        assert device_data["firmware_version"] == "IAAB-1600"
        assert device_data["sensors"]["firmware_version"] == "IAAB-1600"
        # Cached for subsequent calls
        assert coordinator._firmware_cache["GB001"] == "IAAB-1600"

    async def test_gridboss_firmware_cached_on_second_call(self, hass):
        """Firmware is read once and cached — transport not called again."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GridBOSS FW Cache",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB002",
                        "host": "192.168.1.200",
                        "port": 502,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "MID_DEVICE",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                        "dongle_serial": "D002",
                    },
                ],
            },
            entry_id="gb_fw_cache_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        # Pre-populate firmware cache (simulates first refresh already done)
        coordinator._firmware_cache["GB002"] = "IAAB-1600"

        mock_transport = MagicMock()
        mock_transport.is_connected = True
        mock_transport.read_firmware_version = AsyncMock(
            return_value="SHOULD-NOT-BE-CALLED"
        )

        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        mock_mid.has_data = True
        mock_mid.refresh = AsyncMock()
        mock_mid.firmware_version = None

        coordinator._mid_device_cache["GB002"] = mock_mid

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_gridboss_sensor_mapping",
                return_value={"grid_voltage": 240.0},
            ),
            patch.object(coordinator, "_filter_unused_smart_port_sensors"),
            patch.object(coordinator, "_calculate_gridboss_aggregates"),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        # Should use cached value, NOT call transport again
        mock_transport.read_firmware_version.assert_not_called()
        assert processed["devices"]["GB002"]["firmware_version"] == "IAAB-1600"


class TestSharedBatterySecondary:
    """Shared battery suppression for parallel secondary inverters (#169).

    In a parallel system with "Share Battery" enabled, the CAN bus connects
    only to the primary inverter.  The secondary (role >= 2) reports
    battery_count=0 at Modbus register 96.  Battery bank device/entities
    should be suppressed on the secondary — per-inverter runtime sensors
    (battery_voltage, battery_current, state_of_charge) remain accurate.
    """

    @pytest.fixture
    def parallel_config_entry(self, hass):
        """Config entry with primary + secondary inverter in parallel."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Parallel",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "PRIMARY001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS18",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SECONDARY01",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id="parallel_test",
        )
        entry.add_to_hass(hass)
        return entry

    async def test_static_phase_includes_battery_bank_keys_for_all_inverters(
        self, hass, parallel_config_entry
    ):
        """Static phase includes core battery_bank keys for all inverters.

        We cannot know at static-phase time whether a secondary truly
        lacks batteries (shared CAN bus) or has its own bank.  Suppression
        happens at runtime when we have actual battery_count data.
        """
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            BATTERY_BANK_CORE_KEYS,
        )

        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        result = coordinator._build_static_local_data()

        primary_sensors = result["devices"]["PRIMARY001"]["sensors"]
        secondary_sensors = result["devices"]["SECONDARY01"]["sensors"]

        # Both primary and secondary should have core battery bank keys
        assert any(k in primary_sensors for k in BATTERY_BANK_CORE_KEYS), (
            "Primary should have battery bank keys in static phase"
        )

        assert any(k in secondary_sensors for k in BATTERY_BANK_CORE_KEYS), (
            "Secondary should have battery bank keys in static phase"
        )

    async def test_static_phase_excludes_can_diagnostic_keys(
        self, hass, parallel_config_entry
    ):
        """Static phase must NOT include CAN-dependent diagnostic keys.

        CAN bus diagnostic sensors (soc_delta, soh_delta, etc.) require
        individual battery data from registers 5002+.  Pre-creating them
        statically would produce permanently Unavailable entities when
        CAN data is not available.
        """
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            BATTERY_BANK_CAN_DIAGNOSTIC_KEYS,
        )

        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        result = coordinator._build_static_local_data()

        for serial in result["devices"]:
            sensors = result["devices"][serial]["sensors"]
            for key in BATTERY_BANK_CAN_DIAGNOSTIC_KEYS:
                assert key not in sensors, (
                    f"{key} should not be in static sensors for {serial}"
                )

    async def test_secondary_skips_battery_bank_when_count_zero(
        self, hass, parallel_config_entry
    ):
        """Secondary (battery_count=0) should not get battery bank sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        coordinator._local_static_phase_done = True

        # Mock secondary inverter: role=2, battery_count=0 (shared battery)
        mock_runtime = MagicMock()
        mock_runtime.parallel_number = 2
        mock_runtime.parallel_master_slave = 2
        mock_runtime.parallel_phase = 0
        mock_runtime.pv_total_power = 5000
        mock_runtime.battery_soc = 93
        mock_runtime.grid_power = 0
        mock_runtime.battery_current = 15.0
        mock_runtime.battery_voltage = 53.7

        mock_battery_data = MagicMock()
        mock_battery_data.battery_count = None  # CAN bus not connected
        mock_battery_data.batteries = []

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport_runtime = mock_runtime
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = mock_battery_data
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport.host = "192.168.1.101"
        mock_inverter._transport.disconnect = AsyncMock()
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None
        mock_inverter.eps_power_l1 = None
        mock_inverter.eps_power_l2 = None

        # Pre-populate caches
        coordinator._inverter_cache["SECONDARY01"] = mock_inverter
        coordinator._firmware_cache["SECONDARY01"] = "fAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={
                "battery_voltage": 53.7,
                "battery_current": 15.0,
                "state_of_charge": 93,
            },
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=parallel_config_entry.data[CONF_LOCAL_TRANSPORTS][1],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["SECONDARY01"]

        # Runtime sensors (from input registers) should be present
        assert device["sensors"]["battery_voltage"] == 53.7
        assert device["sensors"]["battery_current"] == 15.0
        assert device["sensors"]["state_of_charge"] == 93

        # No battery_bank_* sensors should exist
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"

        # No individual batteries
        assert device["batteries"] == {}

    async def test_primary_retains_battery_bank(self, hass, parallel_config_entry):
        """Primary inverter (role=1) should still get battery bank sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        coordinator._local_static_phase_done = True

        mock_runtime = MagicMock()
        mock_runtime.parallel_number = 2
        mock_runtime.parallel_master_slave = 1
        mock_runtime.parallel_phase = 0
        mock_runtime.pv_total_power = 8000
        mock_runtime.battery_soc = 93
        mock_runtime.grid_power = 0

        mock_battery_data = MagicMock()
        mock_battery_data.battery_count = 4  # CAN bus connected
        mock_battery_data.voltage = 53.7
        mock_battery_data.current = 30.0
        mock_battery_data.soc = 93
        mock_battery_data.charge_power = 825.0
        mock_battery_data.discharge_power = 0
        mock_battery_data.battery_power = 1611.0
        mock_battery_data.max_capacity = 280.0
        mock_battery_data.current_capacity = 260.0
        mock_battery_data.remain_capacity = 260.0
        mock_battery_data.full_capacity = 280.0
        mock_battery_data.capacity_percent = 92.9
        mock_battery_data.status = "Charging"
        mock_battery_data.min_soh = None
        mock_battery_data.max_cell_temp = None
        mock_battery_data.temp_delta = None
        mock_battery_data.cell_voltage_delta_max = None
        mock_battery_data.soc_delta = None
        mock_battery_data.soh_delta = None
        mock_battery_data.voltage_delta = None
        mock_battery_data.cycle_count_delta = None
        mock_battery_data.batteries = [MagicMock(), MagicMock()]

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport_runtime = mock_runtime
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = mock_battery_data
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport.host = "192.168.1.100"
        mock_inverter._transport.disconnect = AsyncMock()
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None
        mock_inverter.eps_power_l1 = None
        mock_inverter.eps_power_l2 = None

        coordinator._inverter_cache["PRIMARY001"] = mock_inverter
        coordinator._firmware_cache["PRIMARY001"] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"battery_voltage": 53.7, "state_of_charge": 93},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=parallel_config_entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["PRIMARY001"]

        # Primary should have battery bank sensors
        assert "battery_bank_soc" in device["sensors"]
        assert "battery_bank_voltage" in device["sensors"]
        assert "battery_bank_count" in device["sensors"]
        assert device["sensors"]["battery_bank_count"] == 4

    async def test_shared_battery_logged_once(self, hass, parallel_config_entry):
        """Info log for shared battery skip should fire only once per serial."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)

        # Simulate: serial already logged
        coordinator._shared_battery_logged.add("SECONDARY01")

        # The set prevents re-logging on subsequent invocations
        assert "SECONDARY01" in coordinator._shared_battery_logged

    async def test_non_parallel_inverter_with_zero_battery_count_skips_bank(
        self,
        hass,
    ):
        """Standalone inverter with battery_count=0 also skips battery bank.

        Battery bank creation is gated purely on battery_count, regardless of
        parallel role.  If the count is 0/None, no battery bank device is created.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Standalone",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "STANDALONE1",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            options={},
            entry_id="standalone_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_runtime = MagicMock()
        mock_runtime.parallel_number = 0  # No parallel group
        mock_runtime.parallel_master_slave = 0  # Not a secondary
        mock_runtime.parallel_phase = 0

        mock_battery_data = MagicMock()
        mock_battery_data.battery_count = None  # Temporarily 0
        mock_battery_data.voltage = 53.7
        mock_battery_data.current = 0.0
        mock_battery_data.soc = 50
        mock_battery_data.charge_power = 0
        mock_battery_data.discharge_power = 0
        mock_battery_data.battery_power = 0
        mock_battery_data.max_capacity = None
        mock_battery_data.current_capacity = None
        mock_battery_data.remain_capacity = None
        mock_battery_data.full_capacity = None
        mock_battery_data.capacity_percent = None
        mock_battery_data.status = "Idle"
        mock_battery_data.min_soh = None
        mock_battery_data.max_cell_temp = None
        mock_battery_data.temp_delta = None
        mock_battery_data.cell_voltage_delta_max = None
        mock_battery_data.soc_delta = None
        mock_battery_data.soh_delta = None
        mock_battery_data.voltage_delta = None
        mock_battery_data.cycle_count_delta = None
        mock_battery_data.batteries = []

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport_runtime = mock_runtime
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = mock_battery_data
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport.host = "192.168.1.100"
        mock_inverter._transport.disconnect = AsyncMock()
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None
        mock_inverter.eps_power_l1 = None
        mock_inverter.eps_power_l2 = None

        coordinator._inverter_cache["STANDALONE1"] = mock_inverter
        coordinator._firmware_cache["STANDALONE1"] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["STANDALONE1"]

        # battery_count=0 → no battery bank sensors regardless of parallel status
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"


class TestBatteryBankCountSuppression:
    """Tests for battery bank suppression when battery_count=0 (issue #169)."""

    @staticmethod
    def _make_detection_entry(hass: Any, serial: str, entry_id: str) -> MockConfigEntry:
        """Build a LOCAL config entry with one secondary inverter for detection tests."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Detection Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": serial,
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id=entry_id,
        )
        entry.add_to_hass(hass)
        return entry

    @staticmethod
    def _make_mock_inverter(*, battery_count: int | None = None) -> MagicMock:
        """Build a mock inverter with shared-battery secondary defaults."""
        mock_runtime = MagicMock()
        mock_runtime.parallel_number = 2
        mock_runtime.parallel_master_slave = 2
        mock_runtime.parallel_phase = 0

        mock_battery_data = MagicMock()
        mock_battery_data.battery_count = battery_count
        mock_battery_data.batteries = []

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport_runtime = mock_runtime
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = mock_battery_data
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport.host = "192.168.1.100"
        mock_inverter._transport.disconnect = AsyncMock()
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None
        mock_inverter.eps_power_l1 = None
        mock_inverter.eps_power_l2 = None
        return mock_inverter

    async def test_secondary_no_battery_bank_sensors(self, hass):
        """Secondary with battery_count=0 gets no battery_bank_* sensors."""
        serial = "INVPARAM01"
        entry = self._make_detection_entry(hass, serial, "param_test")
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_inverter = self._make_mock_inverter(battery_count=None)
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {serial: {"FUNC_BAT_SHARED": 1}},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"

    async def test_secondary_with_battery_count_zero_explicit(self, hass):
        """Secondary with battery_count=0 (explicit zero) also skips bank."""
        serial = "INVZERO01"
        entry = self._make_detection_entry(hass, serial, "zero_test")
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_inverter = self._make_mock_inverter(battery_count=0)
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == []

    async def test_parallel_group_counts_only_primary_batteries(self, hass):
        """Parallel group battery count comes from primary only (secondary has 0)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - PG Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "PRIMARY001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS18",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SECONDARY01",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id="pg_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        processed: dict[str, Any] = {
            "devices": {
                "PRIMARY001": {
                    "type": "inverter",
                    "model": "FlexBOSS18",
                    "serial": "PRIMARY001",
                    "sensors": {
                        "battery_bank_count": 4,
                        "battery_bank_current": 30.0,
                        "battery_bank_max_capacity": 280.0,
                        "battery_bank_current_capacity": 260.0,
                        "state_of_charge": 93,
                    },
                    "batteries": {"bat1": {"soc": 93}},
                    "parallel_number": 2,
                    "parallel_master_slave": 1,
                },
                "SECONDARY01": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "serial": "SECONDARY01",
                    "sensors": {
                        "state_of_charge": 93,
                        "battery_voltage": 53.7,
                    },
                    "batteries": {},
                    "parallel_number": 2,
                    "parallel_master_slave": 2,
                },
            },
            "parallel_groups": {},
            "parameters": {},
        }

        await coordinator._process_local_parallel_groups(processed)

        pg = processed["devices"].get("parallel_group_a", {})
        pg_sensors = pg.get("sensors", {})

        # Battery count = 4 (primary only, secondary has none)
        assert pg_sensors.get("parallel_battery_count") == 4
        assert pg_sensors.get("parallel_battery_current") == 30.0


class TestBatteryRRCacheFallback:
    """Regression tests for issue #180: individual batteries become unavailable.

    When the WiFi dongle fails to read individual battery registers (5002+),
    ``_battery_slot_ceiling`` was permanently set to 0, causing all subsequent
    polls to return ``battery_data.batteries = []``.  The coordinator now falls
    back to the round-robin cache so entities stay available during transient
    transport failures.
    """

    @staticmethod
    def _make_config_entry(hass: Any, serial: str) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Cache Fallback Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": serial,
                        "host": "192.168.1.100",
                        "port": 8899,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 0,
                        "parallel_master_slave": 0,
                    },
                ],
            },
            options={},
            entry_id="cache_fallback_test",
        )
        entry.add_to_hass(hass)
        return entry

    @staticmethod
    def _make_mock_inverter(*, battery_count: int, batteries: list[Any]) -> MagicMock:
        mock_runtime = MagicMock()
        mock_runtime.parallel_number = 0
        mock_runtime.parallel_master_slave = 0
        mock_runtime.parallel_phase = 0

        mock_battery_data = MagicMock()
        mock_battery_data.battery_count = battery_count
        mock_battery_data.batteries = batteries

        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        mock_inverter._transport_runtime = mock_runtime
        mock_inverter._transport_energy = None
        mock_inverter._transport_battery = mock_battery_data
        mock_inverter._transport = MagicMock()
        mock_inverter._transport.is_connected = True
        mock_inverter._transport.host = "192.168.1.100"
        mock_inverter._transport.disconnect = AsyncMock()
        mock_inverter.consumption_power = None
        mock_inverter.battery_power = None
        mock_inverter.rectifier_power = None
        mock_inverter.power_to_user = None
        mock_inverter.eps_power_l1 = None
        mock_inverter.eps_power_l2 = None
        return mock_inverter

    async def test_cache_fallback_when_batteries_empty_this_poll(
        self, hass: Any
    ) -> None:
        """When battery_data.batteries is empty but cache has data, use cache.

        Regression test for issue #180: after a transient WiFi dongle read
        failure, individual battery entities must stay available (not go
        unavailable) by falling back to the round-robin cache.
        """
        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        # Pre-populate the round-robin cache with 4 batteries (as if a
        # previous successful poll populated them).
        coordinator._battery_rr_cache[serial] = {
            f"{serial}-01": {"soc": 80, "voltage": 52.8},
            f"{serial}-02": {"soc": 79, "voltage": 52.7},
            f"{serial}-03": {"soc": 81, "voltage": 52.9},
            f"{serial}-04": {"soc": 78, "voltage": 52.6},
        }

        # This poll: battery_data exists (bank sensors work) but batteries=[]
        # (individual register read failed, _battery_slot_ceiling was set to 0)
        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"state_of_charge": 79},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_battery_bank_sensor_mapping",
                return_value={"battery_bank_count": 4, "battery_bank_voltage": 52.7},
            ),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        # Cache fallback: 4 batteries should be available from the cache
        assert len(device["batteries"]) == 4, (
            "Expected 4 batteries from RR cache fallback, "
            f"got {len(device['batteries'])}: {list(device['batteries'].keys())}"
        )
        assert f"{serial}-01" in device["batteries"]
        assert f"{serial}-04" in device["batteries"]

    async def test_no_fallback_when_cache_empty(self, hass: Any) -> None:
        """When both poll batteries and cache are empty, batteries dict is empty."""
        serial = "DONGLE002"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        # No pre-populated cache

        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"state_of_charge": 50},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_battery_bank_sensor_mapping",
                return_value={"battery_bank_count": 4},
            ),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        # No fallback possible — batteries stays empty
        assert device["batteries"] == {}
