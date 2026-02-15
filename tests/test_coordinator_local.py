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
        """All 10 register ranges are read."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock()
        mock_transport.read_named_parameters = AsyncMock(return_value={"PARAM_A": True})

        result = await coordinator._read_modbus_parameters(mock_transport)

        # 10 register ranges: 21, 64-79, 101-102, 105-106, 110, 125, 179, 227, 231-232, 233
        assert mock_transport.read_named_parameters.call_count == 10
        assert "PARAM_A" in result

    async def test_partial_failure_continues(self, hass, local_config_entry):
        """One register range failing doesn't stop the rest."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        call_count = 0

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if start == 21:
                raise RuntimeError("range 21 failed")
            return {f"param_{start}": start}

        mock_transport = MagicMock()
        mock_transport.read_named_parameters = AsyncMock(side_effect=mock_read)

        result = await coordinator._read_modbus_parameters(mock_transport)

        # All 10 ranges attempted despite first failure
        assert call_count == 10
        # Successful ranges contributed their params
        assert len(result) == 9  # 10 total - 1 failed

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
        mock_inverter.total_load_power = None
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
        mock_inverter.total_load_power = None
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
        mock_inverter.total_load_power = 4000
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
        assert result["sensors"]["total_load_power"] == 4000
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
    """Test forced transport read after HYBRID attachment."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_forces_transport_read(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """refresh(force=True) called for attached inverters after attachment."""
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
        mock_inverter.refresh.assert_called_once_with(force=True)

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_force_refresh_failure_nonfatal(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Exception in forced refresh logged but attachment still succeeds."""
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
        mock_inverter.refresh = AsyncMock(side_effect=ConnectionError("timeout"))

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

        # Attachment still succeeds despite force-refresh failure
        assert coordinator._local_transports_attached is True


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
        mock_transport.read_firmware_version = AsyncMock(return_value="SHOULD-NOT-BE-CALLED")

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
