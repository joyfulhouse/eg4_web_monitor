"""Tests for coordinator hybrid mode with Station.attach_local_transports().

This module tests the new hybrid mode implementation where local transports
are attached to HTTP-discovered Station devices using CONF_LOCAL_TRANSPORTS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    HYBRID_LOCAL_MODBUS,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_transport_configs,
)

if TYPE_CHECKING:
    pass


# ============================================================================
# Test: _build_transport_configs() Helper
# ============================================================================


# Skip tests that require pylxpweb.transports.config (not yet in published package)
try:
    from pylxpweb.transports.config import TransportConfig, TransportType  # noqa: F401

    HAS_TRANSPORT_CONFIG = True
except ImportError:
    HAS_TRANSPORT_CONFIG = False


@pytest.mark.skipif(
    not HAS_TRANSPORT_CONFIG,
    reason="pylxpweb.transports.config not available in published package",
)
class TestBuildTransportConfigs:
    """Tests for _build_transport_configs() helper function."""

    def test_build_modbus_config(self) -> None:
        """Test building TransportConfig from Modbus config dict."""
        config_list = [
            {
                "serial": "CE12345678",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.100",
                "port": 502,
                "unit_id": 1,
                "inverter_family": "EG4_HYBRID",
            }
        ]

        configs = _build_transport_configs(config_list)

        assert len(configs) == 1
        assert configs[0].serial == "CE12345678"
        assert configs[0].host == "192.168.1.100"
        assert configs[0].port == 502

    def test_build_dongle_config(self) -> None:
        """Test building TransportConfig from Dongle config dict."""
        config_list = [
            {
                "serial": "CE87654321",
                "transport_type": "wifi_dongle",
                "host": "192.168.1.101",
                "port": 8000,
                "dongle_serial": "BA12345678",
                "inverter_family": "EG4_HYBRID",
            }
        ]

        configs = _build_transport_configs(config_list)

        assert len(configs) == 1
        assert configs[0].serial == "CE87654321"
        assert configs[0].host == "192.168.1.101"
        assert configs[0].port == 8000
        assert configs[0].dongle_serial == "BA12345678"

    def test_build_multiple_configs(self) -> None:
        """Test building multiple TransportConfig objects."""
        config_list = [
            {
                "serial": "CE11111111",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.100",
                "port": 502,
                "unit_id": 1,
                "inverter_family": "EG4_HYBRID",
            },
            {
                "serial": "CE22222222",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.101",
                "port": 502,
                "unit_id": 2,
                "inverter_family": "EG4_OFFGRID",
            },
        ]

        configs = _build_transport_configs(config_list)

        assert len(configs) == 2
        assert configs[0].serial == "CE11111111"
        assert configs[1].serial == "CE22222222"

    def test_serial_malformed_numeric_skipped_not_fatal(self) -> None:
        """A None baudrate (TypeError in int()) skips the config, not setup (#233)."""
        config_list = [
            {
                "serial": "CE33333333",
                "transport_type": "modbus_serial",
                "serial_port": "/dev/ttyUSB0",
                "serial_baudrate": None,
                "inverter_family": "EG4_HYBRID",
            },
            {
                "serial": "CE44444444",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.100",
                "port": 502,
                "unit_id": 1,
                "inverter_family": "EG4_HYBRID",
            },
        ]

        configs = _build_transport_configs(config_list)

        # Bad serial config skipped; the good TCP config still builds.
        assert len(configs) == 1
        assert configs[0].serial == "CE44444444"

    def test_serial_string_numerics_coerced(self) -> None:
        """String numeric fields from older stored entries coerce cleanly (#233)."""
        config_list = [
            {
                "serial": "CE55555555",
                "transport_type": "modbus_serial",
                "serial_port": "/dev/ttyUSB0",
                "serial_baudrate": "19200",
                "serial_stopbits": "1",
                "unit_id": "1",
                "inverter_family": "EG4_HYBRID",
            }
        ]

        configs = _build_transport_configs(config_list)

        assert len(configs) == 1
        assert configs[0].serial_baudrate == 19200
        assert configs[0].serial_stopbits == 1
        assert configs[0].unit_id == 1

    def test_build_empty_list(self) -> None:
        """Test building with empty config list."""
        configs = _build_transport_configs([])
        assert configs == []

    def test_build_invalid_transport_type(self) -> None:
        """Test building with invalid transport type skips the config."""
        config_list = [
            {
                "serial": "CE12345678",
                "transport_type": "invalid_type",
                "host": "192.168.1.100",
                "port": 502,
            }
        ]

        configs = _build_transport_configs(config_list)
        # Should skip invalid config
        assert len(configs) == 0

    def test_build_missing_required_field(self) -> None:
        """Test building with missing required field skips the config."""
        config_list = [
            {
                "serial": "CE12345678",
                "transport_type": "modbus_tcp",
                # Missing "host" field
                "port": 502,
            }
        ]

        configs = _build_transport_configs(config_list)
        # Should skip config with missing field
        assert len(configs) == 0

    def test_build_serial_config(self) -> None:
        """Serial config dicts build a MODBUS_SERIAL TransportConfig (#233).

        Stored modbus_serial dicts have no host/port keys (the config flow
        only stores serial_port/baudrate/parity/stopbits/unit_id), so the
        builder must not require them.
        """
        config_list = [
            {
                "serial": "CE12345678",
                "transport_type": "modbus_serial",
                "serial_port": "/dev/ttyUSB0",
                "serial_baudrate": 19200,
                "serial_parity": "N",
                "serial_stopbits": 1,
                "unit_id": 1,
                "inverter_family": "EG4_HYBRID",
            }
        ]

        configs = _build_transport_configs(config_list)

        assert len(configs) == 1
        assert configs[0].transport_type == TransportType.MODBUS_SERIAL
        assert configs[0].serial == "CE12345678"
        assert configs[0].serial_port == "/dev/ttyUSB0"
        assert configs[0].serial_baudrate == 19200
        assert configs[0].serial_parity == "N"
        assert configs[0].serial_stopbits == 1
        assert configs[0].unit_id == 1

    def test_build_serial_config_missing_port_skipped(self) -> None:
        """Serial config without serial_port is skipped, not crashed on."""
        config_list = [
            {
                "serial": "CE12345678",
                "transport_type": "modbus_serial",
            }
        ]

        configs = _build_transport_configs(config_list)

        assert configs == []


# ============================================================================
# Test: Coordinator Hybrid Mode Initialization
# ============================================================================


class TestCoordinatorHybridInit:
    """Tests for coordinator initialization with CONF_LOCAL_TRANSPORTS."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.config.time_zone = "America/Los_Angeles"
        hass.bus.async_listen_once = MagicMock()
        return hass

    @pytest.fixture
    def hybrid_entry_with_local_transports(self) -> MagicMock:
        """Create a mock config entry with CONF_LOCAL_TRANSPORTS."""
        entry = MagicMock()
        entry.data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            "username": "test@example.com",
            "password": "test_password",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_PLANT_ID: "12345",
            # Legacy modbus fields (still needed for coordinator __init__)
            CONF_HYBRID_LOCAL_TYPE: HYBRID_LOCAL_MODBUS,
            CONF_MODBUS_HOST: "192.168.1.100",
            # New CONF_LOCAL_TRANSPORTS format for attach_local_transports()
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "CE12345678",
                    "transport_type": "modbus_tcp",
                    "host": "192.168.1.100",
                    "port": DEFAULT_MODBUS_PORT,
                    "unit_id": DEFAULT_MODBUS_UNIT_ID,
                    "inverter_family": "EG4_HYBRID",
                }
            ],
        }
        entry.options = {}
        return entry

    def test_stores_local_transport_configs(
        self, mock_hass: MagicMock, hybrid_entry_with_local_transports: MagicMock
    ) -> None:
        """Test that coordinator stores CONF_LOCAL_TRANSPORTS during init."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport"),
        ):
            coordinator = EG4DataUpdateCoordinator(
                mock_hass, hybrid_entry_with_local_transports
            )

        assert len(coordinator._local_transport_configs) == 1
        assert coordinator._local_transport_configs[0]["serial"] == "CE12345678"
        assert coordinator._local_transports_attached is False

    def test_empty_local_transports_list(self, mock_hass: MagicMock) -> None:
        """Test coordinator handles missing CONF_LOCAL_TRANSPORTS."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        entry = MagicMock()
        entry.data = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            "username": "test@example.com",
            "password": "test_password",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_PLANT_ID: "12345",
            # Legacy modbus fields (still needed for coordinator __init__)
            CONF_HYBRID_LOCAL_TYPE: HYBRID_LOCAL_MODBUS,
            CONF_MODBUS_HOST: "192.168.1.100",
            # No CONF_LOCAL_TRANSPORTS - should default to empty list
        }
        entry.options = {}

        with (
            patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
            patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
            patch("pylxpweb.transports.create_transport"),
        ):
            coordinator = EG4DataUpdateCoordinator(mock_hass, entry)

        assert coordinator._local_transport_configs == []


# ============================================================================
# Test: _attach_local_transports_to_station()
# ============================================================================


class TestAttachLocalTransports:
    """Tests for _attach_local_transports_to_station() method."""

    @pytest.mark.asyncio
    async def test_attach_transports_no_station(self) -> None:
        """Test that attachment is skipped when station is None."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        # Create a mock coordinator with station = None
        mock_self = MagicMock()
        mock_self.station = None
        mock_self._local_transport_configs = [{"serial": "CE12345678"}]
        mock_self._local_transports_attached = False

        # Call the method as a bound method
        await EG4DataUpdateCoordinator._attach_local_transports_to_station(mock_self)

        # Should return early without any changes
        # The method should not raise an error

    @pytest.mark.asyncio
    async def test_attach_transports_no_configs(self) -> None:
        """Test that attachment is skipped when no configs."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self._local_transport_configs = []

        await EG4DataUpdateCoordinator._attach_local_transports_to_station(mock_self)

        # Should return early without calling attach_local_transports
        mock_self.station.attach_local_transports.assert_not_called()

    @pytest.mark.asyncio
    async def test_attach_transports_success(self) -> None:
        """Test successful transport attachment."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        # Mock successful attachment result
        attach_result = MagicMock()
        attach_result.matched = 1
        attach_result.unmatched = 0
        attach_result.failed = 0
        attach_result.unmatched_serials = []
        attach_result.failed_serials = []

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self.station.is_hybrid_mode = True
        mock_self._local_transport_configs = [
            {
                "serial": "CE12345678",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.100",
                "port": 502,
                "unit_id": 1,
                "inverter_family": "EG4_HYBRID",
            }
        ]
        mock_self._local_transports_attached = False

        # Mock the helper function to return valid configs
        mock_config = MagicMock()
        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[mock_config],
        ):
            await EG4DataUpdateCoordinator._attach_local_transports_to_station(
                mock_self
            )

        # Verify attachment was called
        mock_self.station.attach_local_transports.assert_called_once_with([mock_config])


class TestAttachRetryAndDegradedFallback:
    """eg4-05l/eg4-o5m: failed attaches retry; degraded devices stay fresh.

    Live prod incident (2026-06-10, v3.4.0-beta.2): an HA restart left the
    dongle's TCP slot held by the previous session, the GridBOSS attach
    timed out once and was never retried, and its cloud fallback froze on
    HTTP-interval-aligned caches until a manual reload.
    """

    @staticmethod
    def _net_cfg(serial: str, host: str = "10.100.12.175") -> MagicMock:
        from pylxpweb.transports.config import TransportType

        cfg = MagicMock()
        cfg.serial = serial
        cfg.host = host
        cfg.transport_type = TransportType.WIFI_DONGLE
        return cfg

    @pytest.mark.asyncio
    async def test_partial_failure_tracks_serials_and_raises_issue(self) -> None:
        """A failed serial populates the retry set and raises a Repairs issue."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        attach_result = MagicMock()
        attach_result.matched = 0
        attach_result.unmatched = 0
        attach_result.failed = 1
        attach_result.unmatched_serials = []
        attach_result.failed_serials = ["4524850115"]

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self._local_transport_configs = [
            {"serial": "4524850115", "transport_type": "wifi_dongle"}
        ]
        mock_self._local_transports_attached = False

        cfg = self._net_cfg("4524850115")
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
                return_value=[cfg],
            ),
            patch("custom_components.eg4_web_monitor.coordinator_local.ir") as mock_ir,
        ):
            await EG4DataUpdateCoordinator._attach_local_transports_to_station(
                mock_self
            )

        assert mock_self._failed_attach_serials == {"4524850115"}
        assert mock_self._local_transports_attached is True
        issue_ids = [c.args[2] for c in mock_ir.async_create_issue.call_args_list]
        assert "transport_attach_failed_4524850115" in issue_ids

    @pytest.mark.asyncio
    async def test_successful_attach_clears_stale_issue(self) -> None:
        """A serial that attaches cleanly gets any stale Repairs issue deleted."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        attach_result = MagicMock()
        attach_result.matched = 1
        attach_result.unmatched = 0
        attach_result.failed = 0
        attach_result.unmatched_serials = []
        attach_result.failed_serials = []

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self._local_transport_configs = [
            {"serial": "4524850115", "transport_type": "wifi_dongle"}
        ]
        mock_self._local_transports_attached = False

        cfg = self._net_cfg("4524850115")
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
                return_value=[cfg],
            ),
            patch("custom_components.eg4_web_monitor.coordinator_local.ir") as mock_ir,
        ):
            await EG4DataUpdateCoordinator._attach_local_transports_to_station(
                mock_self
            )

        assert mock_self._failed_attach_serials == set()
        deleted = [c.args[2] for c in mock_ir.async_delete_issue.call_args_list]
        assert "transport_attach_failed_4524850115" in deleted

    @pytest.mark.asyncio
    async def test_retry_recovers_and_clears_issue(self) -> None:
        """A retry that succeeds clears the set, the issue, and reconfigures."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        attach_result = MagicMock()
        attach_result.failed_serials = []
        attach_result.unmatched_serials = []

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self._last_attach_retry = 0.0
        mock_self._local_transport_configs = [
            {"serial": "4524850115", "transport_type": "wifi_dongle"}
        ]

        cfg = self._net_cfg("4524850115")
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
                return_value=[cfg],
            ),
            patch("custom_components.eg4_web_monitor.coordinator_local.ir") as mock_ir,
        ):
            await EG4DataUpdateCoordinator._maybe_retry_failed_attaches(mock_self)

        mock_self.station.attach_local_transports.assert_awaited_once_with([cfg])
        assert mock_self._failed_attach_serials == set()
        deleted = [c.args[2] for c in mock_ir.async_delete_issue.call_args_list]
        assert "transport_attach_failed_4524850115" in deleted
        mock_self._configure_attached_devices.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_still_failing_keeps_serial(self) -> None:
        """A retry that fails again keeps the serial for the next attempt."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        attach_result = MagicMock()
        attach_result.failed_serials = ["4524850115"]
        attach_result.unmatched_serials = []

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self._last_attach_retry = 0.0
        mock_self._local_transport_configs = [
            {"serial": "4524850115", "transport_type": "wifi_dongle"}
        ]

        cfg = self._net_cfg("4524850115")
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
                return_value=[cfg],
            ),
            patch("custom_components.eg4_web_monitor.coordinator_local.ir") as mock_ir,
        ):
            await EG4DataUpdateCoordinator._maybe_retry_failed_attaches(mock_self)

        assert mock_self._failed_attach_serials == {"4524850115"}
        mock_ir.async_delete_issue.assert_not_called()
        mock_self._configure_attached_devices.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_respects_backoff(self) -> None:
        """Retries are bounded — a fresh retry timestamp skips the attempt."""
        import time as time_mod

        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock()
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self._last_attach_retry = time_mod.monotonic()

        await EG4DataUpdateCoordinator._maybe_retry_failed_attaches(mock_self)

        mock_self.station.attach_local_transports.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_noop_without_failures(self) -> None:
        """No failed serials -> no retry work at all."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock()
        mock_self._failed_attach_serials = set()

        await EG4DataUpdateCoordinator._maybe_retry_failed_attaches(mock_self)

        mock_self.station.attach_local_transports.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_degraded_device_gets_cache_bust_and_cloud_refresh(self) -> None:
        """A locally-configured device with no transport refreshes via cloud
        with its API cache invalidated (eg4-o5m freeze fix)."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mid = MagicMock()
        mid.serial_number = "4524850115"
        mid.transport = None
        mid.refresh = AsyncMock()

        mock_self = MagicMock()
        mock_self._local_transports_attached = True
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self.station = MagicMock()
        mock_self.station.all_inverters = []
        mock_self.station.all_mid_devices = [mid]
        mock_self.client = MagicMock()
        mock_self._http_polling_interval = 60
        mock_self._last_degraded_cloud_refresh = {}

        await EG4DataUpdateCoordinator._refresh_station_devices(
            mock_self, include_mid=True
        )

        mock_self.client.invalidate_cache_for_device.assert_called_once_with(
            "4524850115"
        )
        mid.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cloud_only_device_keeps_its_caches(self) -> None:
        """A device never configured for local polling is NOT cache-busted."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        inv = MagicMock()
        inv.serial_number = "9999999999"
        inv.transport = None
        inv.refresh = AsyncMock()

        mock_self = MagicMock()
        mock_self._local_transports_attached = True
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self.station = MagicMock()
        mock_self.station.all_inverters = [inv]
        mock_self.station.all_mid_devices = []
        mock_self.client = MagicMock()
        mock_self._http_polling_interval = 60
        mock_self._last_degraded_cloud_refresh = {}

        await EG4DataUpdateCoordinator._refresh_station_devices(
            mock_self, include_mid=True
        )

        mock_self.client.invalidate_cache_for_device.assert_not_called()
        inv.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_degraded_refresh_failure_is_logged_not_swallowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cloud-refresh failures for transportless devices log a warning."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mid = MagicMock()
        mid.serial_number = "4524850115"
        mid.transport = None
        mid.refresh = AsyncMock(side_effect=RuntimeError("cloud down"))

        mock_self = MagicMock()
        mock_self._local_transports_attached = True
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self.station = MagicMock()
        mock_self.station.all_inverters = []
        mock_self.station.all_mid_devices = [mid]
        mock_self.client = MagicMock()
        mock_self._http_polling_interval = 60
        mock_self._last_degraded_cloud_refresh = {}

        await EG4DataUpdateCoordinator._refresh_station_devices(
            mock_self, include_mid=True
        )

        assert "Cloud refresh failed for 4524850115" in caplog.text

    @pytest.mark.asyncio
    async def test_degraded_mid_escalates_include_mid_gate(self) -> None:
        """A degraded MID forces include_mid past the dongle-interval gate."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mid = MagicMock()
        mid.serial_number = "4524850115"

        mock_self = MagicMock()
        mock_self._should_poll_hybrid_local = MagicMock(return_value=False)
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self.station = MagicMock()
        mock_self.station.all_mid_devices = [mid]
        mock_self.station.all_inverters = []
        mock_self._async_update_http_data = AsyncMock(return_value={"devices": {}})

        await EG4DataUpdateCoordinator._async_update_hybrid_data(mock_self)

        mock_self._async_update_http_data.assert_awaited_once_with(
            include_mid_refresh=True
        )

    @pytest.mark.asyncio
    async def test_degraded_inverter_does_not_escalate_mid_gate(self) -> None:
        """A degraded INVERTER must not force off-interval dongle polling."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mid = MagicMock()
        mid.serial_number = "4524850115"

        mock_self = MagicMock()
        mock_self._should_poll_hybrid_local = MagicMock(return_value=False)
        mock_self._failed_attach_serials = {"1111111111"}  # an inverter
        mock_self.station = MagicMock()
        mock_self.station.all_mid_devices = [mid]
        mock_self.station.all_inverters = []
        mock_self._async_update_http_data = AsyncMock(return_value={"devices": {}})

        await EG4DataUpdateCoordinator._async_update_hybrid_data(mock_self)

        mock_self._async_update_http_data.assert_awaited_once_with(
            include_mid_refresh=False
        )

    @pytest.mark.asyncio
    async def test_degraded_refresh_throttled_to_http_interval(self) -> None:
        """Degraded cloud refresh never outpaces the HTTP interval (review HIGH).

        A hybrid coordinator can tick every 5s — the degraded fallback must
        not turn that into a per-tick cloud call.
        """
        import time as time_mod

        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mid = MagicMock()
        mid.serial_number = "4524850115"
        mid.transport = None
        mid.refresh = AsyncMock()

        mock_self = MagicMock()
        mock_self._local_transports_attached = True
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self.station = MagicMock()
        mock_self.station.all_inverters = []
        mock_self.station.all_mid_devices = [mid]
        mock_self.client = MagicMock()
        mock_self._http_polling_interval = 60
        mock_self._last_degraded_cloud_refresh = {
            "4524850115": time_mod.monotonic()  # refreshed moments ago
        }

        await EG4DataUpdateCoordinator._refresh_station_devices(
            mock_self, include_mid=True
        )

        mock_self.client.invalidate_cache_for_device.assert_not_called()
        mid.refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_recovery_drains_recovered_modbus_only(self) -> None:
        """A recovered Modbus transport gets a stale-buffer drain (review MEDIUM)."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        attach_result = MagicMock()
        attach_result.failed_serials = []
        attach_result.unmatched_serials = []

        recovered_inv = MagicMock()
        recovered_inv.serial_number = "1111111111"
        healthy_inv = MagicMock()
        healthy_inv.serial_number = "2222222222"

        mock_self = MagicMock()
        mock_self.station = MagicMock()
        mock_self.station.attach_local_transports = AsyncMock(
            return_value=attach_result
        )
        mock_self._failed_attach_serials = {"1111111111"}
        mock_self._last_attach_retry = 0.0
        mock_self._local_transport_configs = [
            {"serial": "1111111111", "transport_type": "modbus_tcp"}
        ]
        mock_self._configure_attached_devices = MagicMock(
            return_value=[recovered_inv, healthy_inv]
        )
        mock_self._background_tasks = set()

        from pylxpweb.transports.config import TransportType

        cfg = MagicMock()
        cfg.serial = "1111111111"
        cfg.transport_type = TransportType.MODBUS_TCP
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
                return_value=[cfg],
            ),
            patch("custom_components.eg4_web_monitor.coordinator_local.ir"),
        ):
            await EG4DataUpdateCoordinator._maybe_retry_failed_attaches(mock_self)

        # Drain scheduled with ONLY the recovered inverter
        mock_self._drain_modbus_buffers.assert_called_once_with([recovered_inv])
        mock_self.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_local_transports_full_reattach_after_exception(
        self,
    ) -> None:
        """A whole-attach exception (attached=False, empty failed set) re-runs
        the full attach with bounded backoff (review HIGH)."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.connection_type = CONNECTION_TYPE_HYBRID
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self._local_transports_attached = False
        mock_self._failed_attach_serials = set()
        mock_self._last_attach_retry = 0.0
        mock_self._attach_local_transports_to_station = AsyncMock()
        mock_self._maybe_retry_failed_attaches = AsyncMock()

        await EG4DataUpdateCoordinator._ensure_local_transports(mock_self)

        mock_self._attach_local_transports_to_station.assert_awaited_once()
        mock_self._maybe_retry_failed_attaches.assert_not_awaited()
        assert mock_self._last_attach_retry > 0.0

    @pytest.mark.asyncio
    async def test_ensure_local_transports_full_reattach_backoff(self) -> None:
        """The full re-attach respects the bounded retry interval."""
        import time as time_mod

        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.connection_type = CONNECTION_TYPE_HYBRID
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self._local_transports_attached = False
        mock_self._failed_attach_serials = set()
        mock_self._last_attach_retry = time_mod.monotonic()
        mock_self._attach_local_transports_to_station = AsyncMock()

        await EG4DataUpdateCoordinator._ensure_local_transports(mock_self)

        mock_self._attach_local_transports_to_station.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ensure_local_transports_delegates_per_serial_retry(self) -> None:
        """With attach done but serials failed, the per-serial retry runs."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.connection_type = CONNECTION_TYPE_HYBRID
        mock_self._local_transport_configs = [{"serial": "4524850115"}]
        mock_self._local_transports_attached = True
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self._attach_local_transports_to_station = AsyncMock()
        mock_self._maybe_retry_failed_attaches = AsyncMock()

        await EG4DataUpdateCoordinator._ensure_local_transports(mock_self)

        mock_self._maybe_retry_failed_attaches.assert_awaited_once()
        mock_self._attach_local_transports_to_station.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ensure_local_transports_noop_outside_hybrid(self) -> None:
        """Non-hybrid connection types never run attach recovery."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        mock_self = MagicMock()
        mock_self.connection_type = "http"
        mock_self._local_transports_attached = False
        mock_self._failed_attach_serials = {"4524850115"}
        mock_self._attach_local_transports_to_station = AsyncMock()
        mock_self._maybe_retry_failed_attaches = AsyncMock()

        await EG4DataUpdateCoordinator._ensure_local_transports(mock_self)

        mock_self._attach_local_transports_to_station.assert_not_awaited()
        mock_self._maybe_retry_failed_attaches.assert_not_awaited()
