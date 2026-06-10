"""Tests for the local transport coordinator mixin (coordinator_local.py).

Covers methods not already tested in test_coordinator.py:
- _read_modbus_parameters
- _build_local_device_data
- get_local_transport / has_local_transport / is_local_only
- _attach_local_transports_to_station
- _log_transport_error
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.update_coordinator import UpdateFailed
from pylxpweb.devices import HybridInverter
from pylxpweb.transports import ModbusSerialTransport
from pylxpweb.transports.config import AttachResult, TransportType
from pylxpweb.transports.data import (
    BatteryBankData,
    BatteryData,
    InverterEnergyData,
    InverterRuntimeData,
    MidboxRuntimeData,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import make_real_inverter, make_real_mid, make_transport_spec

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
        """All 12 register ranges are read."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {"PARAM_A": True}

        result = await coordinator._read_modbus_parameters(mock_transport)

        # 12 register ranges: 20-22, 64-79, 100-102, 105-106, 110, 125, 158-159,
        # 169, 179, 227-228, 231-232, 233
        assert mock_transport.read_named_parameters.call_count == 12
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

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = mock_read

        result = await coordinator._read_modbus_parameters(mock_transport)

        # All 12 ranges attempted despite first failure
        assert call_count == 12
        # Successful ranges contributed their params
        assert len(result) == 11  # 12 total - 1 failed

    async def test_total_failure_returns_empty(self, hass, local_config_entry):
        """All register ranges failing returns empty dict."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = RuntimeError("all fail")

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

        # REAL inverter with an empty runtime — computed power properties run for
        # real (all derive to 0 from the empty transport data).
        inverter = make_real_inverter(
            "INV001", "FlexBOSS21", runtime=InverterRuntimeData()
        )
        inverter._transport_battery = None
        # _transport is the network CONNECTION object (Modbus/Dongle socket), not
        # a pylxpweb data model — a real one needs a live socket.  It is an infra
        # mock by design; transport_host is connection metadata, not device data.
        inverter._transport = make_transport_spec(host="192.168.1.100")

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"pv_total_power": 5000},
        ):
            result = coordinator._build_local_device_data(
                inverter=inverter,
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

        # REAL inverter with empty runtime + energy transport data.
        inverter = make_real_inverter(
            "INV001",
            "FlexBOSS21",
            runtime=InverterRuntimeData(),
            energy=InverterEnergyData(),
        )
        inverter._transport_battery = None
        inverter._transport = None

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
                inverter=inverter,
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

        # REAL inverter: the computed power properties are exercised for real
        # from injected transport data, instead of a MagicMock fabricating them.
        # Physically coherent fixture — grid import is one quantity, so
        # power_from_grid (consumption energy-balance) == load_power (Ptouser,
        # the grid_import_power sensor source), both 500, mirroring real modbus
        # where both derive from the same Ptouser register.
        #   consumption = pv + (discharge - charge) + import - export
        #               = 3000 + (0 - 1500) + 500 - 0 = 2000
        runtime = InverterRuntimeData(
            pv_total_power=3000,
            battery_charge_power=1500,
            battery_discharge_power=0,
            power_from_grid=500,
            power_to_grid=0,
            grid_power=200,  # rectifier_power (Prec) source
            load_power=500,  # power_to_user (Ptouser) -> grid_import_power sensor
        )
        inverter = make_real_inverter("INV001", "FlexBOSS21", runtime=runtime)

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={},
        ):
            result = coordinator._build_local_device_data(
                inverter=inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["sensors"]["consumption_power"] == 2000
        # total_load_power is a documented ALIAS of consumption_power (a real
        # pylxpweb semantic the old MagicMock hid by asserting a distinct 4000).
        assert result["sensors"]["total_load_power"] == 2000
        assert (
            result["sensors"]["total_load_power"]
            == result["sensors"]["consumption_power"]
        )
        assert result["sensors"]["battery_power"] == 1500
        assert result["sensors"]["rectifier_power"] == 200
        # grid_import_power sensor is sourced from inverter.power_to_user (load_power)
        assert result["sensors"]["grid_import_power"] == 500


# ── get_local_transport / has_local_transport / is_local_only ────────


class TestTransportAccessors:
    """Test transport accessor methods."""

    def test_get_local_transport_from_inverter_cache(self, hass, local_config_entry):
        """LOCAL mode: get_local_transport returns transport from inverter cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        inv = make_real_inverter(serial_number="INV001")
        inv._transport = mock_transport
        coordinator._inverter_cache["INV001"] = inv

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

        mock_transport = make_transport_spec()
        mock_inverter = make_real_inverter(serial_number="INV001")
        mock_inverter._transport = mock_transport

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
        mock_inverter._transport = make_transport_spec()
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

        mock_transport = make_transport_spec()
        mid = make_real_mid(serial_number="GRIDBOSS001")
        mid._transport = mock_transport
        coordinator._mid_device_cache["GRIDBOSS001"] = mid

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is mock_transport

    def test_has_local_transport_true_for_mid_device(self, hass, local_config_entry):
        """has_local_transport returns True for GridBOSS serial in MID cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_mid = MagicMock()
        mock_mid._transport = make_transport_spec()
        coordinator._mid_device_cache["GRIDBOSS001"] = mock_mid

        assert coordinator.has_local_transport("GRIDBOSS001") is True

    def test_get_local_transport_mid_device_no_transport(
        self, hass, local_config_entry
    ):
        """MID device without an attached transport returns None."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # No transport assigned → real .transport property returns None
        mid = make_real_mid(serial_number="GRIDBOSS001")
        coordinator._mid_device_cache["GRIDBOSS001"] = mid

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


# ── Hybrid + USB serial transport attach (#233) ──────────────────────


_SERIAL_TRANSPORT_DICT: dict[str, Any] = {
    "serial": "INV001",
    "transport_type": "modbus_serial",
    "serial_port": "/dev/ttyUSB0",
    "serial_baudrate": 19200,
    "serial_parity": "N",
    "serial_stopbits": 1,
    "unit_id": 1,
    "inverter_family": "EG4_HYBRID",
    "model": "FlexBOSS21",
}


def _make_hybrid_entry(
    transports: list[dict[str, Any]], entry_id: str
) -> MockConfigEntry:
    """Build a HYBRID-mode config entry with the given local transports."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Serial Test",
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
            CONF_LOCAL_TRANSPORTS: transports,
        },
        options={},
        entry_id=entry_id,
    )


def _make_serial_transport_spec(**attrs: Any) -> Any:
    """Autospec stand-in for a ModbusSerialTransport (USB/RS485 adapter)."""
    spec = create_autospec(ModbusSerialTransport, spec_set=True, instance=True)
    defaults: dict[str, Any] = {
        "transport_type": "modbus_serial",
        "is_connected": False,
    }
    defaults.update(attrs)
    spec.configure_mock(**defaults)
    return spec


@patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
@patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
class TestAttachSerialTransports:
    """Hybrid mode attaches USB serial transports integration-side (#233).

    pylxpweb's Station.attach_local_transports() only dispatches modbus_tcp
    and wifi_dongle configs and logs "Unknown transport type: modbus_serial"
    for serial ones, so the coordinator must create and attach serial
    transports itself, mirroring the LOCAL-only dispatch path.
    """

    async def test_serial_transport_attached_integration_side(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial config attaches without the pylxpweb dispatch (#233)."""
        entry = _make_hybrid_entry([dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ) as mock_create:
            await coordinator._attach_local_transports_to_station()

        # The pylxpweb dispatch (which would log "Unknown transport type:
        # modbus_serial" and fail the attach) must not see serial configs.
        mock_station.attach_local_transports.assert_not_called()

        mock_create.assert_called_once()
        assert mock_create.call_args.args == ("serial",)
        kwargs = mock_create.call_args.kwargs
        assert kwargs["port"] == "/dev/ttyUSB0"
        assert kwargs["serial"] == "INV001"
        assert kwargs["baudrate"] == 19200
        assert kwargs["parity"] == "N"
        assert kwargs["stopbits"] == 1
        assert kwargs["unit_id"] == 1

        serial_transport.connect.assert_awaited_once()
        assert inverter._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_mixed_tcp_and_serial_partitioned(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """TCP configs go to pylxpweb; serial configs attach locally."""
        tcp_dict = {
            "serial": "INV002",
            "transport_type": "modbus_tcp",
            "host": "192.168.1.100",
            "port": 502,
            "unit_id": 1,
            "inverter_family": "EG4_HYBRID",
            "model": "FlexBOSS21",
        }
        entry = _make_hybrid_entry(
            [tcp_dict, dict(_SERIAL_TRANSPORT_DICT)], "hybrid_mixed"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inv_serial = make_real_inverter("INV001", "FlexBOSS21")
        inv_tcp = make_real_inverter("INV002", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(
            return_value=AttachResult(matched=1)
        )
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [inv_serial, inv_tcp]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_station.attach_local_transports.assert_awaited_once()
        (network_configs,) = mock_station.attach_local_transports.call_args.args
        assert [c.transport_type for c in network_configs] == [TransportType.MODBUS_TCP]

        assert inv_serial._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_serial_attaches_to_mid_device(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial transports attach to GridBOSS/MID devices too."""
        serial_dict = dict(_SERIAL_TRANSPORT_DICT)
        serial_dict["serial"] = "GB00000001"
        serial_dict["model"] = "GridBOSS"
        entry = _make_hybrid_entry([serial_dict], "hybrid_serial_mid")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        mid = make_real_mid("GB00000001")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = []
        mock_station.all_mid_devices = [mid]
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_station.attach_local_transports.assert_not_called()
        assert mid._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_serial_unmatched_device(self, mock_aiohttp, mock_client_cls, hass):
        """No station device matching the serial → unmatched, no crash."""
        entry = _make_hybrid_entry(
            [dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_unmatched"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = []
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        with patch("pylxpweb.transports.create_transport") as mock_create:
            await coordinator._attach_local_transports_to_station()

        mock_create.assert_not_called()
        assert coordinator._local_transports_attached is True

    async def test_serial_connect_failure_recorded(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """A failing serial connect is recorded per-device, not fatal."""
        entry = _make_hybrid_entry([dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_fail")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        serial_transport.connect.side_effect = OSError("port busy")
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        # Transport never attached, but per-device failures match the
        # pylxpweb semantics: attach completes and is not retried.
        assert inverter._transport is None
        assert coordinator._local_transports_attached is True

    async def test_serial_connect_failure_creates_repair_issue(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial attach failure surfaces a Repairs issue — no silent cloud-only fallback (#233)."""
        entry = _make_hybrid_entry(
            [dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_repair"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        serial_transport.connect.side_effect = OSError("port busy")
        with (
            patch(
                "pylxpweb.transports.create_transport",
                return_value=serial_transport,
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local.ir.async_create_issue"
            ) as mock_issue,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_issue.assert_called_once()
        args, kwargs = mock_issue.call_args
        assert args[2] == "serial_attach_failed_INV001"
        assert kwargs["translation_key"] == "serial_attach_failed"
        assert kwargs["translation_placeholders"]["serial"] == "INV001"
        assert kwargs["severity"].value == "warning"


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
        mock_inverter._transport = make_transport_spec()
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

        # Build a real MIDDevice with a transport that returns firmware.
        # read_firmware_version is async on the real transport, so the autospec
        # returns a coroutine — set its awaited result, not a plain return value.
        mock_transport = make_transport_spec(is_connected=True)
        mock_transport.read_firmware_version.return_value = "IAAB-1600"

        # Inject real runtime so has_data is True (the MIDDevice property reads
        # _transport_runtime). The MIDDevice.firmware_version property would
        # return "" here (the bug scenario) — firmware must come from transport.
        mock_mid = make_real_mid(serial_number="GB001", runtime=MidboxRuntimeData())
        mock_mid._transport = mock_transport
        mock_mid.refresh = AsyncMock()

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

        mock_transport = make_transport_spec(is_connected=True)
        mock_transport.read_firmware_version.return_value = "SHOULD-NOT-BE-CALLED"

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

    async def test_static_fallback_creates_repair_issue(self, hass, local_config_entry):
        """Legacy UNKNOWN-family entry pruned by model fallback raises Repairs.

        The static path used to create ALL sensors for UNKNOWN-family configs;
        the model fallback now prunes to the real profile, which removes
        previously-visible (dead) three-phase entities — that must be loud,
        not silent (#219 review finding 2).
        """
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._local_transport_configs = [
            {
                "serial": "6000123456",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.50",
                "port": 502,
                "model": "6000XP",
                "inverter_family": "UNKNOWN",
            },
            {
                "serial": "5284200001",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.51",
                "port": 502,
                "model": "FlexBOSS21",
                "inverter_family": "EG4_HYBRID",
            },
        ]

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local.ir.async_create_issue"
        ) as mock_issue:
            coordinator._build_static_local_data()

        # Exactly one issue — for the fallback device, not the clean one.
        mock_issue.assert_called_once()
        args, kwargs = mock_issue.call_args
        assert args[2] == "unknown_family_fallback_6000123456"
        assert kwargs["translation_key"] == "unknown_family_fallback"
        assert kwargs["translation_placeholders"]["model"] == "6000XP"
        assert kwargs["translation_placeholders"]["family"] == "EG4_OFFGRID"

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

        # Secondary inverter: role=2, battery_count=0 (shared battery)
        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=2,
            parallel_phase=0,
            pv_total_power=5000,
            battery_soc=93,
            grid_power=0,
            battery_current=15.0,
            battery_voltage=53.7,
        )

        mock_battery_data = BatteryBankData(
            battery_count=None,  # CAN bus not connected
            batteries=[],
        )

        inverter = make_real_inverter("SECONDARY01", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.101"
        )

        # Pre-populate caches
        coordinator._inverter_cache["SECONDARY01"] = inverter
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

        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=1,
            parallel_phase=0,
            pv_total_power=8000,
            battery_soc=93,
            grid_power=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=4,  # CAN bus connected
            voltage=53.7,
            current=30.0,
            soc=93,
            charge_power=825.0,
            discharge_power=0,
            max_capacity=280.0,
            current_capacity=260.0,
            status="Charging",
            batteries=[
                BatteryData(battery_index=0, serial_number="BAT0"),
                BatteryData(battery_index=1, serial_number="BAT1"),
            ],
        )

        inverter = make_real_inverter("PRIMARY001", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )

        coordinator._inverter_cache["PRIMARY001"] = inverter
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

        mock_runtime = InverterRuntimeData(
            parallel_number=0,  # No parallel group
            parallel_master_slave=0,  # Not a secondary
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=None,  # Temporarily 0
            voltage=53.7,
            current=0.0,
            soc=50,
            charge_power=0,
            discharge_power=0,
            max_capacity=None,
            current_capacity=None,
            status="Idle",
            batteries=[],
        )

        inverter = make_real_inverter("STANDALONE1", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )

        coordinator._inverter_cache["STANDALONE1"] = inverter
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
    def _make_mock_inverter(*, battery_count: int | None = None) -> HybridInverter:
        """Build a REAL inverter with shared-battery secondary defaults."""
        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=2,
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=battery_count,
            batteries=[],
        )

        inverter = make_real_inverter("SECONDARY01", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )
        return inverter

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
    def _make_mock_inverter(
        *, battery_count: int, batteries: list[Any]
    ) -> HybridInverter:
        mock_runtime = InverterRuntimeData(
            parallel_number=0,
            parallel_master_slave=0,
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=battery_count,
            batteries=batteries,
        )

        inverter = make_real_inverter("DONGLE001", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )
        return inverter

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


class TestBatteryControlModeMethods:
    """Coordinator helpers for the battery control regime (SOC vs Voltage)."""

    async def test_get_configured_control_modes_default_soc(
        self, hass, local_config_entry
    ):
        """No stored options → SOC for both (migration-safe)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator.get_configured_control_modes() == ("soc", "soc")

    async def test_get_configured_control_modes_from_options(self, hass):
        """Stored options are returned verbatim."""
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="t",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
            },
            options={
                CONF_CHARGE_CONTROL_MODE: "voltage",
                CONF_DISCHARGE_CONTROL_MODE: "soc",
            },
            entry_id="ctrl_modes",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        assert coordinator.get_configured_control_modes() == ("voltage", "soc")

    async def test_get_live_control_mode(self, hass, local_config_entry):
        """Live regime is read from reg-179 bits in params; missing → SOC."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.data = {
            "parameters": {
                "INV001": {
                    "FUNC_BAT_CHARGE_CONTROL": True,
                    "FUNC_BAT_DISCHARGE_CONTROL": False,
                }
            }
        }
        assert coordinator.get_live_control_mode("INV001") == "voltage"
        assert coordinator.get_live_control_mode("INV001", discharge=True) == "soc"
        assert coordinator.get_live_control_mode("UNKNOWN") == "soc"

    async def test_async_write_battery_control_mode_local(
        self, hass, local_config_entry
    ):
        """Local write sets both reg-179 bits via named parameters."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=True)
        coordinator.write_named_parameter = AsyncMock()

        await coordinator.async_write_battery_control_mode("INV001", "voltage", "soc")

        calls = coordinator.write_named_parameter.call_args_list
        assert calls[0][0][0] == "FUNC_BAT_CHARGE_CONTROL"
        assert calls[0][0][1] is True
        assert calls[1][0][0] == "FUNC_BAT_DISCHARGE_CONTROL"
        assert calls[1][0][1] is False

    async def test_async_write_battery_control_mode_cloud(
        self, hass, local_config_entry
    ):
        """Cloud write uses the atomic function-control API for each bit."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=False)
        result = MagicMock()
        result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(return_value=result)

        await coordinator.async_write_battery_control_mode("INV001", "soc", "voltage")

        calls = coordinator.client.api.control.control_function.call_args_list
        assert calls[0][0] == ("INV001", "FUNC_BAT_CHARGE_CONTROL", False)
        assert calls[1][0] == ("INV001", "FUNC_BAT_DISCHARGE_CONTROL", True)


# ── Transport link-down flow (eg4-57g / #226 attached-but-dead) ──────


class TestLocalLinkDownFlow:
    """LOCAL mode end-to-end: a link-down device must surface an error key
    (entities unavailable) and a Repairs issue — not frozen-fresh values."""

    async def test_link_down_marks_error_and_raises_repairs_issue(self, hass):
        """A device whose transport link died gets its cached device data
        error-marked and a transport_link_down Repairs issue, even when the
        whole cycle ends in UpdateFailed (single-device outage)."""
        from homeassistant.helpers import issue_registry as ir

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Link Down",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="link_down_flow_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        coordinator._local_parameters_loaded = False

        # Previous good cycle's data (this is what would freeze pre-fix).
        coordinator.data = {
            "devices": {
                "CE11111111": {
                    "type": "inverter",
                    "sensors": {"battery_voltage": 53.2},
                }
            },
            "parameters": {},
        }

        # Link-down inverter as pylxpweb now presents it: refresh() swallows
        # the failed probe, transport data caches cleared on the transition.
        transport = MagicMock(spec=["is_connected", "host", "port", "transport_type"])
        transport.is_connected = True
        transport.host = "192.168.1.60"
        transport.port = 502
        transport.transport_type = "modbus_tcp"
        inverter = MagicMock(
            spec=[
                "transport",
                "transport_link_down",
                "transport_runtime",
                "refresh",
                "serial_number",
            ]
        )
        inverter.serial_number = "CE11111111"
        inverter.transport = transport
        inverter.transport_link_down = True
        inverter.transport_runtime = None  # cleared at the down transition
        inverter.refresh = AsyncMock()
        coordinator._inverter_cache["CE11111111"] = inverter

        with pytest.raises(UpdateFailed, match="All 1 local transports failed"):
            await coordinator._async_update_local_data()

        # Probe still attempted this cycle (recovery path stays alive).
        inverter.refresh.assert_awaited_once()

        # The carried-forward device data is error-marked, which flips the
        # base_entity availability contract to unavailable.
        assert (
            coordinator.data["devices"]["CE11111111"]["error"]
            == "Local transport link down"
        )

        # One-shot Repairs issue exists with the right placeholders.
        registry = ir.async_get(hass)
        issue = registry.async_get_issue(DOMAIN, "transport_link_down_CE11111111")
        assert issue is not None
        assert issue.translation_key == "transport_link_down"
        assert issue.translation_placeholders == {
            "serial": "CE11111111",
            "host": "192.168.1.60",
        }
        assert coordinator._link_down_notified == {"CE11111111"}

    async def test_recovery_clears_repairs_issue(self, hass):
        """When the link comes back, the Repairs issue is deleted."""
        from homeassistant.helpers import issue_registry as ir

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Link Recovered",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="link_recovered_flow_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        # Simulate the outage having raised the issue earlier.
        ir.async_create_issue(
            hass,
            DOMAIN,
            "transport_link_down_CE11111111",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="transport_link_down",
            translation_placeholders={"serial": "CE11111111", "host": "x"},
        )
        coordinator._link_down_notified = {"CE11111111"}

        transport = MagicMock(spec=["is_connected", "host", "port"])
        inverter = MagicMock(spec=["transport", "transport_link_down", "serial_number"])
        inverter.serial_number = "CE11111111"
        inverter.transport = transport
        inverter.transport_link_down = False  # recovered
        coordinator._inverter_cache["CE11111111"] = inverter

        processed: dict[str, Any] = {"devices": {}}
        coordinator._sync_transport_link_state(processed)

        registry = ir.async_get(hass)
        assert (
            registry.async_get_issue(DOMAIN, "transport_link_down_CE11111111") is None
        )
        assert coordinator._link_down_notified == set()
