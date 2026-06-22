"""Tests for the HTTP/cloud update mixin (coordinator_http.py)."""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
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
    DEFAULT_DONGLE_UPDATE_INTERVAL,
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
from pylxpweb.transports.data import BatteryBankData, BatteryData, MidboxRuntimeData

from tests.conftest import make_real_inverter, make_real_mid, make_transport_spec


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

        inv = make_real_inverter(serial_number="INV001")
        mock_transport = make_transport_spec(
            transport_type="modbus", host="192.168.1.100"
        )
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

        inv = make_real_inverter(serial_number="INV001")
        # Real inverter has _transport=None by default → .transport returns None.
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


# ── HYBRID per-transport interval gating ─────────────────────────────


@pytest.fixture
def hybrid_dongle_config_entry():
    """Create a hybrid config entry with WiFi dongle transport."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Dongle Test",
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
                    "serial": "MID001",
                    "host": "192.168.1.200",
                    "port": 8000,
                    "transport_type": "wifi_dongle",
                    "inverter_family": "EG4_GRIDBOSS",
                    "model": "GridBOSS",
                },
            ],
        },
        options={},
        entry_id="hybrid_dongle_test_entry",
    )


@pytest.fixture
def hybrid_mixed_config_entry():
    """Create a hybrid config entry with both modbus_tcp and wifi_dongle transports.

    This mirrors the real-world user setup: inverters on modbus, GridBOSS on dongle.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Mixed Test",
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
                    "port": 8000,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "18KPV",
                },
                {
                    "serial": "MID001",
                    "host": "192.168.1.200",
                    "port": 8000,
                    "transport_type": "wifi_dongle",
                    "inverter_family": "EG4_GRIDBOSS",
                    "model": "GridBOSS",
                },
            ],
        },
        options={},
        entry_id="hybrid_mixed_test_entry",
    )


class TestHybridTransportGating:
    """Test HYBRID per-transport interval gating (issue #148)."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_should_poll_hybrid_local_first_call(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """First call returns True (monotonic timestamp starts at 0)."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        # First call should always return True (timestamp=0.0)
        assert coordinator._should_poll_hybrid_local() is True

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_should_poll_hybrid_local_within_interval(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """Returns False when dongle interval has not elapsed."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        # First call stamps the timestamp
        assert coordinator._should_poll_hybrid_local() is True
        # Immediate second call should return False (interval not elapsed)
        assert coordinator._should_poll_hybrid_local() is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_should_poll_hybrid_local_mixed_transports(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_mixed_config_entry
    ):
        """With mixed transports, MID refresh gates on dongle interval only.

        Even when modbus is ready, MID refresh should wait for dongle interval.
        This is the real-world scenario: inverters on modbus, GridBOSS on dongle.
        """
        hybrid_mixed_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_mixed_config_entry)

        # First call: both timestamps at 0 → dongle ready → True
        assert coordinator._should_poll_hybrid_local() is True
        # Second call: dongle timestamp was just stamped → not ready → False
        # (modbus is also stamped, but the result is based on dongle only)
        assert coordinator._should_poll_hybrid_local() is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_should_poll_hybrid_local_mixed_stamps_modbus(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_mixed_config_entry
    ):
        """Mixed transports: modbus timestamp is stamped even when dongle gates False.

        Ensures the pre-compute pattern works — ALL transport timestamps update
        on every call, preventing timestamp drift.
        """
        hybrid_mixed_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_mixed_config_entry)

        # First call stamps both timestamps
        coordinator._should_poll_hybrid_local()
        modbus_stamp_1 = coordinator._last_modbus_poll
        dongle_stamp_1 = coordinator._last_dongle_poll
        assert modbus_stamp_1 > 0
        assert dongle_stamp_1 > 0

        # Second call: returns False (dongle not ready) but still stamps modbus
        coordinator._last_modbus_poll = 0.0  # Reset modbus so it would be ready
        coordinator._should_poll_hybrid_local()
        assert coordinator._last_modbus_poll > 0  # Modbus was re-stamped

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_should_poll_hybrid_local_no_transports(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Returns True when no local transports configured (HTTP-only fallback)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator._local_transport_configs = []

        assert coordinator._should_poll_hybrid_local() is True

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_selective_refresh_skips_mid(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """When dongle interval not elapsed, only inverters refresh (not MID)."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv.refresh = AsyncMock()
        station = _mock_station([inv])
        coordinator.station = station

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
            # First call: interval elapsed → full refresh_all_data
            await coordinator._async_update_hybrid_data()
            station.refresh_all_data.assert_called_once()

            station.refresh_all_data.reset_mock()
            inv.refresh.reset_mock()

            # Second call: interval NOT elapsed → only inv.refresh(), not refresh_all_data
            await coordinator._async_update_hybrid_data()
            station.refresh_all_data.assert_not_called()
            inv.refresh.assert_called_once()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_full_refresh_on_interval(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """When dongle interval elapsed, full refresh_all_data runs."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv.refresh = AsyncMock()
        station = _mock_station([inv])
        coordinator.station = station

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
            # First call: refresh_all_data
            await coordinator._async_update_hybrid_data()
            station.refresh_all_data.assert_called_once()

            # Force timestamp to be old enough for next poll
            coordinator._last_dongle_poll = 0.0
            station.refresh_all_data.reset_mock()

            # Second call with reset timestamp: full refresh again
            await coordinator._async_update_hybrid_data()
            station.refresh_all_data.assert_called_once()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_coordinator_uses_transport_intervals(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """HYBRID coordinator interval uses min(transport intervals)."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        # Dongle-only: interval should be DEFAULT_DONGLE_UPDATE_INTERVAL (30s)
        assert coordinator.update_interval is not None
        assert (
            coordinator.update_interval.total_seconds()
            == DEFAULT_DONGLE_UPDATE_INTERVAL
        )

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_mid_device_not_refreshed_in_process(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """_process_mid_device_object reads existing data without calling refresh()."""
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        mid_device = make_real_mid(
            serial_number="MID001",
            model="GridBOSS",
            runtime=MidboxRuntimeData(
                grid_l1_voltage=122.5,
                grid_l2_voltage=122.4,
                grid_frequency=60.0,
            ),
        )
        # refresh() is the call under test — wrap it so we can assert it is
        # NOT invoked (control-flow mock, not data-producing).
        mid_device.refresh = AsyncMock()

        await coordinator._process_mid_device_object(mid_device)

        # refresh() should NOT have been called — data is already refreshed
        # by station.refresh_all_data() before this method is called
        mid_device.refresh.assert_not_called()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_mid_device_surfaces_consumption_and_generator_frequency(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_dongle_config_entry
    ):
        """eg4-7uz: CLOUD/HYBRID MID path surfaces both formerly LOCAL-only keys.

        ``consumption_power`` must alias the load CT measurement
        (``load_power``) and ``generator_frequency`` must come through the
        dual-source MIDDevice property — matching the LOCAL table.
        """
        hybrid_dongle_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_dongle_config_entry)

        mid_device = make_real_mid(
            serial_number="MID001",
            model="GridBOSS",
            runtime=MidboxRuntimeData(
                load_l1_power=1200.0,
                load_l2_power=300.0,
                gen_frequency=59.9,
            ),
        )

        processed = await coordinator._process_mid_device_object(mid_device)

        sensors = processed["sensors"]
        assert sensors["consumption_power"] == 1500.0
        assert sensors["consumption_power"] == sensors["load_power"]
        assert sensors["generator_frequency"] == 59.9


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

        inv = make_real_inverter(serial_number="INV001")
        # Real inverter has transport_battery=None → cloud-only path is taken.
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

        # Cloud battery metadata lives on the inverter's _battery_bank; the leaf
        # battery objects are metadata stand-ins (the inverter itself is real).
        battery_bank = MagicMock()
        battery_bank.battery_count = 2
        battery_bank.batteries = [mock_batt1, mock_batt2]
        inv._battery_bank = battery_bank
        coordinator.station = _mock_station([inv])
        # Populate inverter cache so get_inverter_object() finds the inverter
        # (normally done by _rebuild_inverter_cache in _async_update_http_data)
        coordinator._inverter_cache = {"INV001": inv}
        # Seed parameters so _process_station_data does not schedule the
        # background parameter refresh (which would call the real inverter's
        # refresh() — unrelated to battery extraction under test).
        coordinator.data = {"parameters": {"INV001": {}}}

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

        inv = make_real_inverter(serial_number="INV001")
        inv._battery_bank = None  # No cloud batteries

        # Transport batteries — real BatteryData/BatteryBankData so the
        # individual-battery read path is exercised against the genuine shape.
        # Set on the real inverter so .transport_battery returns it.
        mock_transport_battery = BatteryBankData(
            batteries=[
                BatteryData(
                    battery_index=0,
                    voltage=52.0,
                    current=10.0,
                    soc=85,
                    serial_number="BAT_SN_001",
                )
            ]
        )
        inv._transport_battery = mock_transport_battery

        coordinator.station = _mock_station([inv])
        coordinator._inverter_cache = {"INV001": inv}
        # Seed parameters so _process_station_data does not schedule the
        # background parameter refresh (which would call the real inverter's
        # refresh() — unrelated to battery extraction under test).
        coordinator.data = {"parameters": {"INV001": {}}}

        mock_mapping = {"battery_voltage": 52.0, "battery_soc": 85}
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
                return_value=mock_mapping,
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_individual_battery_mapping",
                return_value=mock_mapping,
            ),
        ):
            result = await coordinator._process_station_data()

        batteries = result["devices"]["INV001"]["batteries"]
        assert len(batteries) == 1
        assert "INV001-01" in batteries

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_skips_stale_transport_battery(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """HYBRID: a frozen transport battery must not hide fresh cloud data.

        pylxpweb's serial-keyed accumulator never evicts (#170 round-robin), so
        a battery the firmware stops surfacing locally keeps its last register
        block forever. On an 18kPV that exposes only one battery per register
        page for hours (#258), overlaying that frozen block over the refreshed
        cloud baseline froze the other batteries by day. A transport block
        older than HYBRID_TRANSPORT_FRESHNESS is skipped so the fresh cloud
        value stands; a recently-read block still overlays.
        """
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        inv = make_real_inverter(serial_number="INV001")

        # Cloud baseline — both batteries fresh from the cloud (SOC 85 / 82).
        cloud1 = MagicMock(
            battery_sn="BAT001",
            battery_index=0,
            soc=85,
            model=None,
            bms_model=None,
            battery_type_text=None,
        )
        cloud2 = MagicMock(
            battery_sn="BAT002",
            battery_index=1,
            soc=82,
            model=None,
            bms_model=None,
            battery_type_text=None,
        )
        bank = MagicMock()
        bank.batteries = [cloud1, cloud2]
        inv._battery_bank = bank

        # Transport — BAT001 read just now, BAT002 frozen 2h ago at SOC 50.
        # last_seen arrives from pylxpweb as tz-aware UTC (matches production).
        fresh = BatteryData(
            battery_index=0, serial_number="BAT001", voltage=52.0, soc=90
        )
        fresh.last_seen = dt_util.utcnow()
        stale = BatteryData(
            battery_index=1, serial_number="BAT002", voltage=51.0, soc=50
        )
        stale.last_seen = dt_util.utcnow() - timedelta(hours=2)
        inv._transport_battery = BatteryBankData(batteries=[fresh, stale])

        coordinator.station = _mock_station([inv])
        coordinator._inverter_cache = {"INV001": inv}
        # Seed parameters so _process_station_data does not schedule the
        # background parameter refresh.
        coordinator.data = {"parameters": {"INV001": {}}}

        def fake_map(b):
            return {"battery_soc": b.soc}

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
                side_effect=fake_map,
            ),
        ):
            result = await coordinator._process_station_data()

        batteries = result["devices"]["INV001"]["batteries"]
        # Fresh transport overlays the cloud baseline.
        assert batteries["INV001-01"]["battery_soc"] == 90
        # Stale transport is skipped — the fresh cloud value stands (NOT 50).
        assert batteries["INV001-02"]["battery_soc"] == 82

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_hybrid_stale_skip_is_timezone_independent(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """The stale-skip decision must not depend on Home Assistant's timezone.

        last_seen arrives from pylxpweb as tz-aware UTC and the age math is done
        in UTC, so a fresh battery is overlaid and a 2-hour-old one skipped
        regardless of the configured HA timezone (the container TZ commonly
        differs from HA's — the maintainer's own dev env is 3 h apart). Earlier
        the age was computed by treating a naive local stamp as HA-local, which
        skewed the decision by the UTC offset (#258).
        """
        # A non-UTC HA timezone that differs from the (UTC) stamp frame.
        await hass.config.async_set_time_zone("America/Los_Angeles")

        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        inv = make_real_inverter(serial_number="INV001")
        cloud1 = MagicMock(
            battery_sn="BAT001",
            battery_index=0,
            soc=85,
            model=None,
            bms_model=None,
            battery_type_text=None,
        )
        cloud2 = MagicMock(
            battery_sn="BAT002",
            battery_index=1,
            soc=82,
            model=None,
            bms_model=None,
            battery_type_text=None,
        )
        bank = MagicMock()
        bank.batteries = [cloud1, cloud2]
        inv._battery_bank = bank

        fresh = BatteryData(
            battery_index=0, serial_number="BAT001", voltage=52.0, soc=90
        )
        fresh.last_seen = dt_util.utcnow()
        stale = BatteryData(
            battery_index=1, serial_number="BAT002", voltage=51.0, soc=50
        )
        stale.last_seen = dt_util.utcnow() - timedelta(hours=2)
        inv._transport_battery = BatteryBankData(batteries=[fresh, stale])

        coordinator.station = _mock_station([inv])
        coordinator._inverter_cache = {"INV001": inv}
        coordinator.data = {"parameters": {"INV001": {}}}

        def fake_map(b):
            return {"battery_soc": b.soc}

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
                side_effect=fake_map,
            ),
        ):
            result = await coordinator._process_station_data()

        batteries = result["devices"]["INV001"]["batteries"]
        # Fresh battery overlaid, stale battery skipped — same as under UTC.
        assert batteries["INV001-01"]["battery_soc"] == 90
        assert batteries["INV001-02"]["battery_soc"] == 82


# ── _refresh_station_devices (serialized dongle access) ──────────────


class TestRefreshStationDevices:
    """Test serialized device refresh for HYBRID mode dongle protection."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_transports_uses_gather(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Without local transports attached, delegates to station.refresh_all_data()."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = _mock_station([_mock_inverter()])
        coordinator._local_transports_attached = False

        await coordinator._refresh_station_devices(include_mid=True)
        coordinator.station.refresh_all_data.assert_awaited_once()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_shared_dongle_serialized(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Devices sharing same dongle endpoint are refreshed sequentially."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        # Two inverters + GridBOSS, all on same dongle (192.168.1.100:8000)
        inv1 = _mock_inverter(serial="INV001")
        inv1._transport = MagicMock()
        inv1._transport._host = "192.168.1.100"
        inv1._transport._port = 8000
        inv1.refresh = AsyncMock()

        inv2 = _mock_inverter(serial="INV002")
        inv2._transport = MagicMock()
        inv2._transport._host = "192.168.1.100"
        inv2._transport._port = 8000
        inv2.refresh = AsyncMock()

        mid = MagicMock()
        mid.serial_number = "MID001"
        mid._transport = MagicMock()
        mid._transport._host = "192.168.1.100"
        mid._transport._port = 8000
        mid.refresh = AsyncMock()

        station = _mock_station([inv1, inv2])
        station.all_mid_devices = [mid]
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        # All three devices refreshed
        inv1.refresh.assert_awaited_once()
        inv2.refresh.assert_awaited_once()
        mid.refresh.assert_awaited_once()
        # station.refresh_all_data should NOT have been called
        station.refresh_all_data.assert_not_awaited()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_exclude_mid_when_include_mid_false(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """When include_mid=False, MID devices are excluded."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        inv = _mock_inverter(serial="INV001")
        inv._transport = MagicMock()
        inv._transport._host = "192.168.1.100"
        inv._transport._port = 8000
        inv.refresh = AsyncMock()

        mid = MagicMock()
        mid.serial_number = "MID001"
        mid._transport = MagicMock()
        mid._transport._host = "192.168.1.100"
        mid._transport._port = 8000
        mid.refresh = AsyncMock()

        station = _mock_station([inv])
        station.all_mid_devices = [mid]
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=False)

        inv.refresh.assert_awaited_once()
        mid.refresh.assert_not_awaited()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_cloud_only_devices_still_refreshed(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Devices without local transport are refreshed via HTTP (concurrent)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        # One device with transport, one without
        inv1 = _mock_inverter(serial="INV001")
        inv1._transport = MagicMock()
        inv1._transport._host = "192.168.1.100"
        inv1._transport._port = 8000
        inv1.refresh = AsyncMock()

        inv2 = _mock_inverter(serial="INV002")
        inv2._transport = None  # Cloud-only
        inv2.refresh = AsyncMock()

        station = _mock_station([inv1, inv2])
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        inv1.refresh.assert_awaited_once()
        inv2.refresh.assert_awaited_once()


class _FakeSerialTransport:
    """Serial transport stand-in: tty path in ``port``, no ``host`` attribute."""

    def __init__(self, port: str) -> None:
        self.port = port


class _FakeTcpTransport:
    """Network transport stand-in with a real host/port endpoint."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


def _tracking_refresh(counter: dict[str, int]) -> Any:
    """Build a refresh coroutine that records concurrent-entry depth."""

    async def _refresh() -> None:
        counter["active"] += 1
        counter["max"] = max(counter["max"], counter["active"])
        # Yield twice so concurrently-scheduled refreshes can interleave —
        # if two devices on one serial bus run in parallel, max hits 2.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        counter["active"] -= 1

    return _refresh


class TestSerialEndpointGrouping:
    """Devices sharing one RS485 adapter must refresh sequentially (#233)."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_same_serial_port_serialized(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Two devices on /dev/ttyUSB0 never refresh concurrently."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        counter = {"active": 0, "max": 0}
        inv1 = _mock_inverter(serial="INV001")
        inv1.transport = _FakeSerialTransport("/dev/ttyUSB0")
        inv1.refresh = AsyncMock(side_effect=_tracking_refresh(counter))
        inv2 = _mock_inverter(serial="INV002")
        inv2.transport = _FakeSerialTransport("/dev/ttyUSB0")
        inv2.refresh = AsyncMock(side_effect=_tracking_refresh(counter))

        station = _mock_station([inv1, inv2])
        station.all_mid_devices = []
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        inv1.refresh.assert_awaited_once()
        inv2.refresh.assert_awaited_once()
        assert counter["max"] == 1, "shared-bus devices refreshed concurrently"

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_different_serial_ports_parallel(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Devices on distinct adapters still refresh concurrently."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        counter = {"active": 0, "max": 0}
        inv1 = _mock_inverter(serial="INV001")
        inv1.transport = _FakeSerialTransport("/dev/ttyUSB0")
        inv1.refresh = AsyncMock(side_effect=_tracking_refresh(counter))
        inv2 = _mock_inverter(serial="INV002")
        inv2.transport = _FakeSerialTransport("/dev/ttyUSB1")
        inv2.refresh = AsyncMock(side_effect=_tracking_refresh(counter))

        station = _mock_station([inv1, inv2])
        station.all_mid_devices = []
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        inv1.refresh.assert_awaited_once()
        inv2.refresh.assert_awaited_once()
        assert counter["max"] == 2, "independent adapters should parallelize"

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_serial_mid_shares_inverter_bus(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """GridBOSS on the same adapter as an inverter is serialized too."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        counter = {"active": 0, "max": 0}
        inv = _mock_inverter(serial="INV001")
        inv.transport = _FakeSerialTransport("/dev/ttyUSB0")
        inv.refresh = AsyncMock(side_effect=_tracking_refresh(counter))
        mid = MagicMock()
        mid.serial_number = "MID001"
        mid.transport = _FakeSerialTransport("/dev/ttyUSB0")
        mid.refresh = AsyncMock(side_effect=_tracking_refresh(counter))

        station = _mock_station([inv])
        station.all_mid_devices = [mid]
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        inv.refresh.assert_awaited_once()
        mid.refresh.assert_awaited_once()
        assert counter["max"] == 1, "reporter topology must serialize"

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_serial_and_tcp_groups_independent(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """A serial group and a TCP group run concurrently with each other."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        counter = {"active": 0, "max": 0}
        inv1 = _mock_inverter(serial="INV001")
        inv1.transport = _FakeSerialTransport("/dev/ttyUSB0")
        inv1.refresh = AsyncMock(side_effect=_tracking_refresh(counter))
        inv2 = _mock_inverter(serial="INV002")
        inv2.transport = _FakeTcpTransport("192.168.1.50", 502)
        inv2.refresh = AsyncMock(side_effect=_tracking_refresh(counter))

        station = _mock_station([inv1, inv2])
        station.all_mid_devices = []
        coordinator.station = station
        coordinator._local_transports_attached = True

        await coordinator._refresh_station_devices(include_mid=True)

        inv1.refresh.assert_awaited_once()
        inv2.refresh.assert_awaited_once()
        assert counter["max"] == 2


class TestMidboxVoltageCanary:
    """Test voltage canary on MidboxRuntimeData.is_corrupt()."""

    def test_normal_voltage_passes(self):
        """Normal US split-phase voltage passes canary."""
        from pylxpweb.transports.data import MidboxRuntimeData

        data = MidboxRuntimeData(grid_l1_voltage=122.5, grid_l2_voltage=122.4)
        assert data.is_corrupt() is False

    def test_zero_voltage_passes(self):
        """Zero voltage (grid down) passes canary."""
        from pylxpweb.transports.data import MidboxRuntimeData

        data = MidboxRuntimeData(grid_l1_voltage=0.0, grid_l2_voltage=0.0)
        assert data.is_corrupt() is False

    def test_corrupt_l1_voltage_rejected(self):
        """Corrupt L1 voltage (register 0xFFFF/10 = 6553.5V) is rejected."""
        from pylxpweb.transports.data import MidboxRuntimeData

        data = MidboxRuntimeData(grid_l1_voltage=6553.5, grid_l2_voltage=122.4)
        assert data.is_corrupt() is True

    def test_corrupt_l2_voltage_rejected(self):
        """Corrupt L2 voltage detected."""
        from pylxpweb.transports.data import MidboxRuntimeData

        data = MidboxRuntimeData(grid_l1_voltage=122.5, grid_l2_voltage=6553.5)
        assert data.is_corrupt() is True

    def test_none_voltage_passes(self):
        """None voltage (not read) passes canary."""
        from pylxpweb.transports.data import MidboxRuntimeData

        data = MidboxRuntimeData(grid_l1_voltage=None, grid_l2_voltage=None)
        assert data.is_corrupt() is False
