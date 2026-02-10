"""Tests for the HTTP/cloud update mixin (coordinator_http.py)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
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
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import (
    EG4DataUpdateCoordinator,
)
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def http_config_entry():
    """Create a mock HTTP config entry."""
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
            CONF_PLANT_NAME: "Test Plant",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        },
        options={},
        entry_id="http_test_entry",
    )


@pytest.fixture
def hybrid_config_entry():
    """Create a mock hybrid config entry."""
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
            CONF_PLANT_NAME: "Test Plant",
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
        entry_id="hybrid_test_entry",
    )


def _mock_inverter(
    *,
    serial: str = "INV001",
    model: str = "FlexBOSS21",
    has_data: bool = True,
    battery_count: int = 0,
) -> MagicMock:
    """Create a mock inverter object."""
    inv = MagicMock()
    inv.serial_number = serial
    inv.model = model
    inv.has_data = has_data
    inv._runtime = MagicMock() if has_data else None
    inv._energy = MagicMock() if has_data else None
    inv._battery_bank = MagicMock()
    inv._battery_bank.battery_count = battery_count
    inv._battery_bank.batteries = []
    inv._transport = None
    inv._transport_runtime = None
    inv._transport_energy = None
    inv._transport_battery = None
    return inv


def _mock_station(
    inverters: list[MagicMock] | None = None,
) -> MagicMock:
    """Create a mock Station object."""
    station = MagicMock()
    station.id = "12345"
    station.name = "Test Station"
    station.timezone = "GMT -8"
    station.all_inverters = inverters or []
    station.all_mid_devices = []
    station.refresh_all_data = AsyncMock()
    station.detect_dst_status = MagicMock(return_value=True)
    station.sync_dst_setting = AsyncMock(return_value=True)
    station.parallel_groups = []
    return station


# ── HTTPUpdateMixin._async_update_http_data ──────────────────────────


class TestAsyncUpdateHttpData:
    """Test the main HTTP data update flow."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_client_raises(self, mock_aiohttp, mock_client_cls, hass):
        """Raises UpdateFailed when HTTP client is None."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Test",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            entry_id="no_client_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        assert coordinator.client is None

        with pytest.raises(UpdateFailed, match="HTTP client not initialized"):
            await coordinator._async_update_http_data()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_initial_station_load(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """First call loads station via Station.load()."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator.station is None

        mock_station = _mock_station([_mock_inverter()])

        with patch(
            "custom_components.eg4_web_monitor.coordinator_http.Station.load",
            new=AsyncMock(return_value=mock_station),
        ) as mock_load:
            with patch.object(
                coordinator,
                "_process_inverter_object",
                new=AsyncMock(
                    return_value={
                        "type": "inverter",
                        "model": "FlexBOSS21",
                        "sensors": {},
                        "batteries": {},
                    }
                ),
            ):
                result = await coordinator._async_update_http_data()

            mock_load.assert_called_once()
            assert coordinator.station is mock_station
            mock_station.refresh_all_data.assert_called()
            assert "devices" in result

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_subsequent_refresh(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Second+ call uses station.refresh_all_data()."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        mock_station = _mock_station([_mock_inverter()])
        coordinator.station = mock_station

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            await coordinator._async_update_http_data()

        mock_station.refresh_all_data.assert_called()


# ── HTTP error handling ──────────────────────────────────────────────


class TestHttpErrorHandling:
    """Test error handling in _async_update_http_data."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_auth_error_raises_config_entry_auth_failed(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """LuxpowerAuthError → ConfigEntryAuthFailed."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_http.Station.load",
                side_effect=LuxpowerAuthError("Invalid credentials"),
            ),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await coordinator._async_update_http_data()
        assert coordinator._last_available_state is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_connection_error_raises_update_failed(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """LuxpowerConnectionError → UpdateFailed."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_http.Station.load",
                side_effect=LuxpowerConnectionError("timeout"),
            ),
            pytest.raises(UpdateFailed, match="Connection failed"),
        ):
            await coordinator._async_update_http_data()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_api_error_raises_update_failed(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """LuxpowerAPIError → UpdateFailed."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_http.Station.load",
                side_effect=LuxpowerAPIError("server error"),
            ),
            pytest.raises(UpdateFailed, match="API error"),
        ):
            await coordinator._async_update_http_data()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_unexpected_error_raises_update_failed(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Generic exception → UpdateFailed."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_http.Station.load",
                side_effect=RuntimeError("something broke"),
            ),
            pytest.raises(UpdateFailed, match="Unexpected error"),
        ):
            await coordinator._async_update_http_data()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_availability_restored_after_success(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Availability flag restored to True after successful update."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        coordinator._last_available_state = False
        coordinator.station = _mock_station([_mock_inverter()])

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            await coordinator._async_update_http_data()

        assert coordinator._last_available_state is True


# ── _process_station_data ────────────────────────────────────────────


class TestProcessStationData:
    """Test station data processing."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_station_metadata(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Station data includes name and plant_id."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        coordinator.station = _mock_station()

        result = await coordinator._process_station_data()

        assert result["station"]["name"] == "Test Station"
        assert result["station"]["plant_id"] == "12345"
        assert "station_last_polled" in result["station"]

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_station_raises(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """No station loaded → UpdateFailed."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        coordinator.station = None

        with pytest.raises(UpdateFailed, match="Station not loaded"):
            await coordinator._process_station_data()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_preserves_parameters(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Existing parameters from previous updates are preserved."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        coordinator.station = _mock_station()
        coordinator.data = {
            "parameters": {"INV001": {"FUNC_EPS_EN": True}},
        }

        result = await coordinator._process_station_data()

        assert result["parameters"]["INV001"]["FUNC_EPS_EN"] is True

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_api_metrics_when_client_exists(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """API metrics are included when HTTP client exists."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        coordinator.station = _mock_station()
        coordinator.client.api_requests_last_hour = 42
        coordinator.client.api_peak_rate_per_hour = 60
        coordinator.client.api_requests_today = 500

        result = await coordinator._process_station_data()

        assert result["station"]["api_request_rate"] == 42
        assert result["station"]["api_peak_request_rate"] == 60
        assert result["station"]["api_requests_today"] == 500

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_inverter_processing_error_isolated(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """One inverter failing doesn't break others."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        good_inv = _mock_inverter(serial="GOOD001")
        bad_inv = _mock_inverter(serial="BAD001")
        coordinator.station = _mock_station([good_inv, bad_inv])

        call_count = 0

        async def process_inverter(inv: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if inv.serial_number == "BAD001":
                raise RuntimeError("inverter error")
            return {
                "type": "inverter",
                "model": "FlexBOSS21",
                "sensors": {},
                "batteries": {},
            }

        with patch.object(
            coordinator,
            "_process_inverter_object",
            side_effect=process_inverter,
        ):
            result = await coordinator._process_station_data()

        # Both were processed
        assert call_count == 2
        # Good inverter has normal data
        assert result["devices"]["GOOD001"]["type"] == "inverter"
        # Bad inverter has error data
        assert "error" in result["devices"]["BAD001"]


# ── Hybrid mode ──────────────────────────────────────────────────────


class TestHybridMode:
    """Test hybrid mode data update."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_sets_connection_type(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Hybrid mode sets connection_type to 'hybrid'."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = _mock_station([_mock_inverter()])

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            result = await coordinator._async_update_hybrid_data()

        assert result["connection_type"] == CONNECTION_TYPE_HYBRID

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_transport_label_with_local(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Hybrid mode sets transport label when device has local transport."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        inv = _mock_inverter(serial="INV001")
        mock_transport = MagicMock()
        mock_transport.transport_type = "modbus"
        mock_transport.host = "192.168.1.100"
        inv._transport = mock_transport

        coordinator.station = _mock_station([inv])

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            result = await coordinator._async_update_hybrid_data()

        device_sensors = result["devices"]["INV001"]["sensors"]
        assert "Hybrid" in device_sensors["connection_transport"]
        assert device_sensors["transport_host"] == "192.168.1.100"

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_cloud_fallback_label(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Hybrid mode uses 'Cloud' label when no local transport."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv._transport = None
        coordinator.station = _mock_station([inv])
        # Clear local caches to ensure no fallback
        coordinator._inverter_cache = {}
        coordinator._mid_device_cache = {}

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            result = await coordinator._async_update_hybrid_data()

        device_sensors = result["devices"]["INV001"]["sensors"]
        assert device_sensors["connection_transport"] == "Cloud"


# ── Battery extraction paths ─────────────────────────────────────────


class TestBatteryExtraction:
    """Test battery data extraction in _process_station_data."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_cloud_batteries(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Cloud-only path extracts batteries from battery_bank."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        inv = _mock_inverter(serial="INV001", battery_count=2)
        mock_batt1 = MagicMock()
        mock_batt1.battery_index = 0
        mock_batt1.battery_key = "Battery_ID_01"
        mock_batt1.battery_sn = "BAT001"
        mock_batt1.voltage = 52.0
        mock_batt1.current = 10.0
        mock_batt1.soc = 85

        mock_batt2 = MagicMock()
        mock_batt2.battery_index = 1
        mock_batt2.battery_key = "Battery_ID_02"
        mock_batt2.battery_sn = "BAT002"
        mock_batt2.voltage = 51.5
        mock_batt2.current = 9.5
        mock_batt2.soc = 82

        inv._battery_bank.batteries = [mock_batt1, mock_batt2]
        coordinator.station = _mock_station([inv])
        # Populate inverter cache so get_inverter_object() finds the inverter
        # (normally done by _rebuild_inverter_cache in _async_update_http_data)
        coordinator._inverter_cache = {"INV001": inv}

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            result = await coordinator._process_station_data()

        batteries = result["devices"]["INV001"]["batteries"]
        assert len(batteries) == 2

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_battery_bank_skipped(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Device with no battery_bank is skipped."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv._battery_bank = None
        coordinator.station = _mock_station([inv])
        coordinator._inverter_cache = {"INV001": inv}

        with patch.object(
            coordinator,
            "_process_inverter_object",
            new=AsyncMock(
                return_value={
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": {},
                }
            ),
        ):
            result = await coordinator._process_station_data()

        assert result["devices"]["INV001"]["batteries"] == {}

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_transport_batteries_local_only(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """Transport batteries without cloud data uses local-only path."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv._battery_bank = None  # No cloud batteries

        # Transport batteries
        mock_transport_battery = MagicMock()
        mock_batt = MagicMock()
        mock_batt.battery_index = 0
        mock_batt.voltage = 52.0
        mock_batt.current = 10.0
        mock_batt.soc = 85
        mock_transport_battery.batteries = [mock_batt]
        inv._transport_battery = mock_transport_battery

        coordinator.station = _mock_station([inv])
        coordinator._inverter_cache = {"INV001": inv}

        with (
            patch.object(
                coordinator,
                "_process_inverter_object",
                new=AsyncMock(
                    return_value={
                        "type": "inverter",
                        "model": "FlexBOSS21",
                        "sensors": {},
                        "batteries": {},
                    }
                ),
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_http._build_individual_battery_mapping",
                return_value={"battery_voltage": 52.0, "battery_soc": 85},
            ),
        ):
            result = await coordinator._process_station_data()

        batteries = result["devices"]["INV001"]["batteries"]
        assert len(batteries) == 1
        assert "INV001-01" in batteries
