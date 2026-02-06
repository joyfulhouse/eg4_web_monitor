"""Tests for network scan config flow steps."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.eg4_web_monitor.const import DOMAIN

# Patch targets: local imports inside config_flow methods
_PATCH_NETWORK = "homeassistant.components.network.async_get_adapters"
_PATCH_SCANNER = "pylxpweb.scanner.NetworkScanner"
_PATCH_DISCOVER_MODBUS = (
    "custom_components.eg4_web_monitor._config_flow.discover_modbus_device"
)

_MOCK_ADAPTERS = [
    {
        "enabled": True,
        "ipv4": [{"address": "192.168.1.100", "network_prefix": 24}],
    }
]


def _make_scan_result(
    ip: str = "192.168.1.50",
    port: int = 502,
    device_type_name: str = "MODBUS_VERIFIED",
    serial: str | None = "4512345678",
    model_family: str | None = "EG4_HYBRID",
    mac_vendor: str | None = None,
):
    """Create a mock ScanResult."""
    from pylxpweb.scanner.types import DeviceType

    mock = MagicMock()
    mock.ip = ip
    mock.port = port
    mock.device_type = DeviceType[device_type_name]
    mock.serial = serial
    mock.model_family = model_family
    mock.mac_vendor = mac_vendor
    mock.display_label = (
        f"{model_family or 'Unknown'} ({serial or 'N/A'}) @ {ip}:{port}"
    )
    mock.is_verified = device_type_name == "MODBUS_VERIFIED"
    mock.is_dongle_candidate = device_type_name == "DONGLE_CANDIDATE"
    return mock


async def _navigate_to_scan_config(hass: HomeAssistant):
    """Init flow and navigate to network_scan_config step."""
    with patch(_PATCH_NETWORK, new_callable=AsyncMock, return_value=_MOCK_ADAPTERS):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "user"

        # Select local path
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "local_device_type"},
        )
        assert result["step_id"] == "local_device_type"

        # Select scan network
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "network_scan_config"},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "network_scan_config"
    return result


async def _submit_scan_and_wait(hass: HomeAssistant, flow_id: str, scanner_mock):
    """Submit scan config, wait for background task, and return the result step."""
    with patch(_PATCH_SCANNER, return_value=scanner_mock):
        # Submit scan config → shows progress spinner
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                "ip_range": "192.168.1.0/24",
                "scan_modbus": True,
                "scan_dongle": False,
                "timeout": 0.5,
            },
        )
        assert result["type"] == data_entry_flow.FlowResultType.SHOW_PROGRESS

        # Wait for background scan task to complete and flow to auto-advance
        await hass.async_block_till_done()

        # HA auto-advances through progress_done → next step
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


class TestNetworkScanConfig:
    """Tests for network_scan_config step."""

    async def test_scan_config_shows_form(self, hass: HomeAssistant):
        """Scan config step shows form with default IP range."""
        result = await _navigate_to_scan_config(hass)
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert "ip_range" in result["data_schema"].schema

    async def test_scan_config_invalid_range(self, hass: HomeAssistant):
        """Invalid IP range shows error."""
        result = await _navigate_to_scan_config(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"ip_range": "not-valid", "scan_modbus": True, "scan_dongle": False},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["errors"]["ip_range"] == "invalid_ip_range"


class TestNetworkScanResults:
    """Tests for network scan results step."""

    async def test_scan_finds_modbus_device(self, hass: HomeAssistant):
        """Scan finds a Modbus device → shows results with selection."""
        mock_result = _make_scan_result()

        mock_scanner_instance = MagicMock()

        async def mock_scan_gen():
            yield mock_result

        mock_scanner_instance.scan = mock_scan_gen

        result = await _navigate_to_scan_config(hass)
        result = await _submit_scan_and_wait(
            hass, result["flow_id"], mock_scanner_instance
        )

        assert result["step_id"] == "network_scan_results"
        assert result["type"] == data_entry_flow.FlowResultType.FORM

    async def test_scan_finds_nothing(self, hass: HomeAssistant):
        """Empty scan results → shows empty menu."""
        mock_scanner_instance = MagicMock()

        async def mock_scan_gen():
            return
            yield  # makes this an async generator

        mock_scanner_instance.scan = mock_scan_gen

        result = await _navigate_to_scan_config(hass)
        result = await _submit_scan_and_wait(
            hass, result["flow_id"], mock_scanner_instance
        )

        assert result["step_id"] == "network_scan_empty"
        assert result["type"] == data_entry_flow.FlowResultType.MENU

    async def test_select_modbus_device_prefills_form(self, hass: HomeAssistant):
        """Selecting a Modbus device pre-fills the modbus form."""
        mock_result = _make_scan_result(ip="192.168.1.50", port=502)

        mock_scanner_instance = MagicMock()

        async def mock_scan_gen():
            yield mock_result

        mock_scanner_instance.scan = mock_scan_gen

        result = await _navigate_to_scan_config(hass)

        mock_device = MagicMock()
        mock_device.serial = "4512345678"

        result = await _submit_scan_and_wait(
            hass, result["flow_id"], mock_scanner_instance
        )
        assert result["step_id"] == "network_scan_results"

        with patch(_PATCH_DISCOVER_MODBUS, return_value=mock_device) as mock_discover:
            # Select the discovered device → pre-fills modbus form → calls discover
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"device": "192.168.1.50"},
            )

        # The modbus step should have been called with pre-filled IP
        assert mock_discover.called
        call_args = mock_discover.call_args
        assert call_args[0][0] == "192.168.1.50"
        assert call_args[0][1] == 502

    async def test_scan_finds_dongle_candidate(self, hass: HomeAssistant):
        """Scan finds a dongle candidate → shows results."""
        mock_result = _make_scan_result(
            ip="192.168.1.100",
            port=8000,
            device_type_name="DONGLE_CANDIDATE",
            serial=None,
            model_family=None,
            mac_vendor="Espressif",
        )

        mock_scanner_instance = MagicMock()

        async def mock_scan_gen():
            yield mock_result

        mock_scanner_instance.scan = mock_scan_gen

        result = await _navigate_to_scan_config(hass)
        result = await _submit_scan_and_wait(
            hass, result["flow_id"], mock_scanner_instance
        )

        assert result["step_id"] == "network_scan_results"
        assert result["type"] == data_entry_flow.FlowResultType.FORM


# =============================================================================
# Discovery Model Info Tests — _read_device_info_from_transport()
# =============================================================================


class TestDiscoveryModelInfo:
    """Test that discovery reads HOLD_MODEL for accurate model names."""

    @staticmethod
    def _make_transport(
        device_type_code: int = 10284,
        power_rating: int | None = None,
        us_version: bool = True,
    ) -> MagicMock:
        """Build a mock transport with optional read_model_info."""
        transport = MagicMock()
        transport.read_device_type = AsyncMock(return_value=device_type_code)
        transport.read_firmware_version = AsyncMock(return_value="FAAB-2525")
        transport.read_parallel_config = AsyncMock(return_value=0)

        runtime = MagicMock()
        runtime.pv_total_power = 100.0
        runtime.battery_soc = 50
        transport.read_runtime = AsyncMock(return_value=runtime)

        if power_rating is not None:
            from pylxpweb.devices.inverters._features import InverterModelInfo

            model_info = InverterModelInfo.from_parameters(
                {
                    "HOLD_MODEL_powerRating": power_rating,
                    "HOLD_MODEL_usVersion": us_version,
                }
            )
            transport.read_model_info = AsyncMock(return_value=model_info)
        else:
            # Ensure hasattr(transport, "read_model_info") is False
            del transport.read_model_info

        return transport

    async def test_flexboss21_model_from_hold_model(self):
        """Discovery resolves FlexBOSS21 via HOLD_MODEL powerRating=8."""
        from custom_components.eg4_web_monitor._config_flow.discovery import (
            _read_device_info_from_transport,
        )

        transport = self._make_transport(device_type_code=10284, power_rating=8)
        device = await _read_device_info_from_transport(transport, "4512345678")

        assert device.model == "FlexBOSS21"

    async def test_flexboss18_model_from_hold_model(self):
        """Discovery resolves FlexBOSS18 via HOLD_MODEL powerRating=9."""
        from custom_components.eg4_web_monitor._config_flow.discovery import (
            _read_device_info_from_transport,
        )

        transport = self._make_transport(device_type_code=10284, power_rating=9)
        device = await _read_device_info_from_transport(transport, "4512345678")

        assert device.model == "FlexBOSS18"

    async def test_18kpv_model_from_hold_model(self):
        """Discovery resolves 18KPV via HOLD_MODEL powerRating=6."""
        from custom_components.eg4_web_monitor._config_flow.discovery import (
            _read_device_info_from_transport,
        )

        transport = self._make_transport(device_type_code=2092, power_rating=6)
        device = await _read_device_info_from_transport(transport, "4512670118")

        assert device.model == "18KPV"

    async def test_fallback_when_no_read_model_info(self):
        """Discovery falls back to default name when transport lacks read_model_info."""
        from custom_components.eg4_web_monitor._config_flow.discovery import (
            _read_device_info_from_transport,
        )

        transport = self._make_transport(device_type_code=10284)
        device = await _read_device_info_from_transport(transport, "4512345678")

        assert device.model == "FlexBOSS21"

    async def test_gridboss_skips_model_info_read(self):
        """Discovery skips HOLD_MODEL read for GridBOSS devices."""
        from custom_components.eg4_web_monitor._config_flow.discovery import (
            _read_device_info_from_transport,
        )

        transport = self._make_transport(device_type_code=50, power_rating=0)
        device = await _read_device_info_from_transport(transport, "5012345678")

        assert device.model == "GridBOSS"
        assert device.is_gridboss is True
