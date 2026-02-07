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
