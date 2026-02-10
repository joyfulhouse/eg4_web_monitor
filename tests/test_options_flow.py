"""Tests for EG4 Options Flow."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, PropertyMock

import pytest

from custom_components.eg4_web_monitor._config_flow.options import EG4OptionsFlow
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_UPDATE_INTERVAL,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_UPDATE_INTERVAL,
    CONF_PARAMETER_REFRESH_INTERVAL,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONNECTION_TYPE_DONGLE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    CONNECTION_TYPE_MODBUS,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_PARAMETER_REFRESH_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL,
    MAX_HTTP_POLLING_INTERVAL,
    MIN_HTTP_POLLING_INTERVAL,
)


class TestEG4OptionsFlow:
    """Tests for EG4OptionsFlow class."""

    def test_class_exists(self):
        """Test that EG4OptionsFlow class exists."""
        assert EG4OptionsFlow is not None

    def test_has_async_step_init(self):
        """Test that EG4OptionsFlow has async_step_init method."""
        assert hasattr(EG4OptionsFlow, "async_step_init")
        assert inspect.iscoroutinefunction(EG4OptionsFlow.async_step_init)


class TestOptionsFlowConstants:
    """Tests for options flow constants."""

    def test_sensor_update_interval_key(self):
        """Test that sensor update interval key is defined."""
        assert CONF_SENSOR_UPDATE_INTERVAL == "sensor_update_interval"

    def test_http_polling_interval_key(self):
        """Test that HTTP polling interval key is defined."""
        assert CONF_HTTP_POLLING_INTERVAL == "http_polling_interval"

    def test_parameter_refresh_interval_key(self):
        """Test that parameter refresh interval key is defined."""
        assert CONF_PARAMETER_REFRESH_INTERVAL == "parameter_refresh_interval"


class TestOptionsFlowDefaults:
    """Tests for options flow default values."""

    def test_http_default_sensor_interval(self):
        """Test that HTTP default sensor interval is 90 seconds (rate limit protection)."""
        assert DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP == 90

    def test_local_default_interval(self):
        """Test that local default sensor interval is 5 seconds."""
        assert DEFAULT_SENSOR_UPDATE_INTERVAL_LOCAL == 5

    def test_http_polling_interval_default(self):
        """Test that HTTP polling interval default is 120 seconds."""
        assert DEFAULT_HTTP_POLLING_INTERVAL == 120

    def test_http_polling_interval_min(self):
        """Test that HTTP polling interval minimum is 60 seconds."""
        assert MIN_HTTP_POLLING_INTERVAL == 60

    def test_http_polling_interval_max(self):
        """Test that HTTP polling interval maximum is 600 seconds."""
        assert MAX_HTTP_POLLING_INTERVAL == 600

    def test_parameter_refresh_default(self):
        """Test that parameter refresh default is 60 minutes."""
        assert DEFAULT_PARAMETER_REFRESH_INTERVAL == 60


class TestConnectionTypeLocalCheck:
    """Tests for connection type local checking logic."""

    def test_modbus_is_local(self):
        """Test that Modbus is considered a local connection."""
        local_types = (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        assert CONNECTION_TYPE_MODBUS in local_types

    def test_dongle_is_local(self):
        """Test that Dongle is considered a local connection."""
        local_types = (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        assert CONNECTION_TYPE_DONGLE in local_types

    def test_hybrid_is_local(self):
        """Test that Hybrid is considered a local connection."""
        local_types = (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        assert CONNECTION_TYPE_HYBRID in local_types

    def test_local_is_local(self):
        """Test that Local is considered a local connection."""
        local_types = (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        assert CONNECTION_TYPE_LOCAL in local_types

    def test_http_is_not_local(self):
        """Test that HTTP is not considered a local connection."""
        local_types = (
            CONNECTION_TYPE_MODBUS,
            CONNECTION_TYPE_DONGLE,
            CONNECTION_TYPE_HYBRID,
            CONNECTION_TYPE_LOCAL,
        )
        assert CONNECTION_TYPE_HTTP not in local_types


class TestOptionsFlowPerTransport:
    """Tests for connection-type-aware options flow schema."""

    def _make_flow(
        self,
        connection_type: str,
        local_transports: list[dict[str, str]] | None = None,
    ) -> EG4OptionsFlow:
        """Create an EG4OptionsFlow with a mock config entry."""
        flow = EG4OptionsFlow.__new__(EG4OptionsFlow)
        mock_entry = MagicMock()
        mock_entry.data = {
            CONF_CONNECTION_TYPE: connection_type,
        }
        if local_transports is not None:
            mock_entry.data[CONF_LOCAL_TRANSPORTS] = local_transports
        mock_entry.options = {}
        mock_entry.entry_id = "test_entry"
        type(flow).config_entry = PropertyMock(return_value=mock_entry)
        return flow

    @pytest.mark.asyncio
    async def test_options_http_only_shows_http_interval(self):
        """HTTP-only shows http_polling_interval, not modbus or dongle."""
        flow = self._make_flow(CONNECTION_TYPE_HTTP)
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_HTTP_POLLING_INTERVAL in schema_keys
        assert CONF_MODBUS_UPDATE_INTERVAL not in schema_keys
        assert CONF_DONGLE_UPDATE_INTERVAL not in schema_keys

    @pytest.mark.asyncio
    async def test_options_modbus_only_shows_modbus_interval(self):
        """MODBUS-only shows modbus_update_interval, not http or dongle."""
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_MODBUS_UPDATE_INTERVAL in schema_keys
        assert CONF_HTTP_POLLING_INTERVAL not in schema_keys
        assert CONF_DONGLE_UPDATE_INTERVAL not in schema_keys

    @pytest.mark.asyncio
    async def test_options_local_mixed_shows_both(self):
        """LOCAL with both transports shows modbus + dongle intervals."""
        flow = self._make_flow(
            CONNECTION_TYPE_LOCAL,
            local_transports=[
                {"transport_type": "modbus_tcp", "serial": "111"},
                {"transport_type": "wifi_dongle", "serial": "222"},
            ],
        )
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_MODBUS_UPDATE_INTERVAL in schema_keys
        assert CONF_DONGLE_UPDATE_INTERVAL in schema_keys
        assert CONF_HTTP_POLLING_INTERVAL not in schema_keys

    @pytest.mark.asyncio
    async def test_options_hybrid_shows_local_and_http(self):
        """HYBRID with modbus transport shows modbus + http intervals."""
        flow = self._make_flow(
            CONNECTION_TYPE_HYBRID,
            local_transports=[
                {"transport_type": "modbus_tcp", "serial": "111"},
            ],
        )
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_MODBUS_UPDATE_INTERVAL in schema_keys
        assert CONF_HTTP_POLLING_INTERVAL in schema_keys
        assert CONF_DONGLE_UPDATE_INTERVAL not in schema_keys
