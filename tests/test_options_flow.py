"""Tests for EG4 Options Flow."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from custom_components.eg4_web_monitor._config_flow.options import EG4OptionsFlow
from custom_components.eg4_web_monitor.const import (
    BLOCK_SIZE_CONSERVATIVE,
    BLOCK_SIZE_FAST,
    CONF_CONNECTION_TYPE,
    CONF_DATA_VALIDATION,
    CONF_DONGLE_UPDATE_INTERVAL,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_BLOCK_SIZE,
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


class TestDataValidationOption:
    """Tests for data_validation checkbox visibility in options flow."""

    def _make_flow(
        self,
        connection_type: str,
        local_transports: list[dict[str, str]] | None = None,
        options: dict | None = None,
    ) -> EG4OptionsFlow:
        """Create an EG4OptionsFlow with a mock config entry."""
        flow = EG4OptionsFlow.__new__(EG4OptionsFlow)
        mock_entry = MagicMock()
        mock_entry.data = {
            CONF_CONNECTION_TYPE: connection_type,
        }
        if local_transports is not None:
            mock_entry.data[CONF_LOCAL_TRANSPORTS] = local_transports
        mock_entry.options = options or {}
        mock_entry.entry_id = "test_entry"
        type(flow).config_entry = PropertyMock(return_value=mock_entry)
        return flow

    @pytest.mark.asyncio
    async def test_data_validation_shown_for_modbus(self):
        """data_validation checkbox shown when MODBUS transport exists."""
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_DATA_VALIDATION in schema_keys

    @pytest.mark.asyncio
    async def test_data_validation_shown_for_dongle(self):
        """data_validation checkbox shown when DONGLE transport exists."""
        flow = self._make_flow(CONNECTION_TYPE_DONGLE)
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_DATA_VALIDATION in schema_keys

    @pytest.mark.asyncio
    async def test_data_validation_shown_for_local_mixed(self):
        """data_validation shown for LOCAL with modbus + dongle."""
        flow = self._make_flow(
            CONNECTION_TYPE_LOCAL,
            local_transports=[
                {"transport_type": "modbus_tcp", "serial": "111"},
                {"transport_type": "wifi_dongle", "serial": "222"},
            ],
        )
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_DATA_VALIDATION in schema_keys

    @pytest.mark.asyncio
    async def test_data_validation_hidden_for_http_only(self):
        """data_validation checkbox NOT shown for HTTP-only mode."""
        flow = self._make_flow(CONNECTION_TYPE_HTTP)
        result = await flow.async_step_init(user_input=None)
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert CONF_DATA_VALIDATION not in schema_keys

    @pytest.mark.asyncio
    async def test_data_validation_defaults_false(self):
        """data_validation defaults to False when not set."""
        flow = self._make_flow(CONNECTION_TYPE_MODBUS, options={})
        result = await flow.async_step_init(user_input=None)
        schema = result["data_schema"].schema
        for key in schema:
            if str(key) == CONF_DATA_VALIDATION:
                assert key.default() is False
                break
        else:
            pytest.fail("CONF_DATA_VALIDATION not found in schema")

    @pytest.mark.asyncio
    async def test_data_validation_reads_existing_option(self):
        """data_validation reads current value from options."""
        flow = self._make_flow(
            CONNECTION_TYPE_MODBUS,
            options={CONF_DATA_VALIDATION: True},
        )
        result = await flow.async_step_init(user_input=None)
        schema = result["data_schema"].schema
        for key in schema:
            if str(key) == CONF_DATA_VALIDATION:
                assert key.default() is True
                break
        else:
            pytest.fail("CONF_DATA_VALIDATION not found in schema")


class TestModbusBlockSizeOption:
    """Modbus read block size preset in the options flow (#254)."""

    def _make_flow(
        self,
        connection_type: str,
        local_transports: list[dict[str, str]] | None = None,
        options: dict | None = None,
    ) -> EG4OptionsFlow:
        """Create an EG4OptionsFlow with a mock config entry."""
        flow = EG4OptionsFlow.__new__(EG4OptionsFlow)
        mock_entry = MagicMock()
        mock_entry.data = {
            CONF_CONNECTION_TYPE: connection_type,
        }
        if local_transports is not None:
            mock_entry.data[CONF_LOCAL_TRANSPORTS] = local_transports
        mock_entry.options = options or {}
        mock_entry.entry_id = "test_entry"
        # No devices -> _apply_battery_control_mode is a no-op on submit
        mock_entry.runtime_data = MagicMock(data={})
        type(flow).config_entry = PropertyMock(return_value=mock_entry)
        return flow

    def _schema_key(self, result, name):
        for key in result["data_schema"].schema:
            if str(key) == name:
                return key
        return None

    @pytest.mark.asyncio
    async def test_shown_for_modbus(self):
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        result = await flow.async_step_init(user_input=None)
        assert self._schema_key(result, CONF_MODBUS_BLOCK_SIZE) is not None

    @pytest.mark.asyncio
    async def test_shown_for_dongle(self):
        flow = self._make_flow(CONNECTION_TYPE_DONGLE)
        result = await flow.async_step_init(user_input=None)
        assert self._schema_key(result, CONF_MODBUS_BLOCK_SIZE) is not None

    @pytest.mark.asyncio
    async def test_hidden_for_http_only(self):
        """No local transport -> no block size to configure."""
        flow = self._make_flow(CONNECTION_TYPE_HTTP)
        result = await flow.async_step_init(user_input=None)
        assert self._schema_key(result, CONF_MODBUS_BLOCK_SIZE) is None

    @pytest.mark.asyncio
    async def test_defaults_to_conservative(self):
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        result = await flow.async_step_init(user_input=None)
        key = self._schema_key(result, CONF_MODBUS_BLOCK_SIZE)
        assert key is not None
        assert key.default() == BLOCK_SIZE_CONSERVATIVE

    @pytest.mark.asyncio
    async def test_reads_existing_option(self):
        flow = self._make_flow(
            CONNECTION_TYPE_MODBUS,
            options={CONF_MODBUS_BLOCK_SIZE: BLOCK_SIZE_FAST},
        )
        result = await flow.async_step_init(user_input=None)
        key = self._schema_key(result, CONF_MODBUS_BLOCK_SIZE)
        assert key is not None
        assert key.default() == BLOCK_SIZE_FAST

    @pytest.mark.asyncio
    async def test_selector_offers_both_presets(self):
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        result = await flow.async_step_init(user_input=None)
        key = self._schema_key(result, CONF_MODBUS_BLOCK_SIZE)
        selector = result["data_schema"].schema[key]
        assert selector.config["options"] == [
            BLOCK_SIZE_CONSERVATIVE,
            BLOCK_SIZE_FAST,
        ]
        assert selector.config["translation_key"] == "modbus_block_size"

    @pytest.mark.asyncio
    async def test_round_trip_saves_fast(self):
        """Submitting Fast stores the preset in the entry options."""
        flow = self._make_flow(CONNECTION_TYPE_MODBUS)
        flow.flow_id = "test_flow"
        flow.handler = "eg4_web_monitor"
        user_input = {
            CONF_MODBUS_UPDATE_INTERVAL: 5,
            CONF_PARAMETER_REFRESH_INTERVAL: 60,
            CONF_MODBUS_BLOCK_SIZE: BLOCK_SIZE_FAST,
        }
        result = await flow.async_step_init(user_input=user_input)
        assert result["type"].value == "create_entry"
        assert result["data"][CONF_MODBUS_BLOCK_SIZE] == BLOCK_SIZE_FAST


class TestOptionsBatteryControlMode:
    """The control-mode pickers pre-fill safely and write only when known."""

    def _make_flow(self, *, options, parameters):
        from unittest.mock import MagicMock, PropertyMock

        from custom_components.eg4_web_monitor._config_flow.options import (
            EG4OptionsFlow,
        )

        flow = EG4OptionsFlow.__new__(EG4OptionsFlow)
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"INV1": {"type": "inverter"}},
            "parameters": {"INV1": parameters},
        }
        coordinator.get_live_control_mode = MagicMock(
            side_effect=lambda s, discharge=False: "voltage"
        )
        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
        mock_entry.options = options
        mock_entry.runtime_data = coordinator
        type(flow).config_entry = PropertyMock(return_value=mock_entry)
        return flow, coordinator

    def test_prefill_uses_live_when_reg179_polled(self):
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        flow, _ = self._make_flow(
            options={
                CONF_CHARGE_CONTROL_MODE: "soc",
                CONF_DISCHARGE_CONTROL_MODE: "soc",
            },
            parameters={
                "FUNC_BAT_CHARGE_CONTROL": True,
                "FUNC_BAT_DISCHARGE_CONTROL": True,
            },
        )
        assert flow._current_control_modes() == ("voltage", "voltage")

    def test_prefill_keeps_stored_when_reg179_unpolled(self):
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        flow, coordinator = self._make_flow(
            options={
                CONF_CHARGE_CONTROL_MODE: "voltage",
                CONF_DISCHARGE_CONTROL_MODE: "voltage",
            },
            parameters={},  # reg 179 not yet polled
        )
        # Must show the stored mode, NOT a misleading live/SOC default.
        assert flow._current_control_modes() == ("voltage", "voltage")
        coordinator.get_live_control_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_skips_write_when_reg179_unpolled(self):
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        flow, coordinator = self._make_flow(
            options={},
            parameters={},  # unknown live regime
        )
        coordinator.async_write_battery_control_mode = AsyncMock()
        await flow._apply_battery_control_mode(
            {
                CONF_CHARGE_CONTROL_MODE: "voltage",
                CONF_DISCHARGE_CONTROL_MODE: "voltage",
            }
        )
        coordinator.async_write_battery_control_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrelated_save_does_not_rewrite_mixed_regimes(self):
        """An options save with UNTOUCHED regime pickers must not write any
        inverter — even one whose live regime differs from the first
        inverter's prefill (codex HIGH, 3.4.0 final review)."""
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        flow, coordinator = self._make_flow(
            options={},
            parameters={
                "FUNC_BAT_CHARGE_CONTROL": True,
                "FUNC_BAT_DISCHARGE_CONTROL": True,
            },
        )
        coordinator.async_write_battery_control_mode = AsyncMock()
        # Show the form: prefill captured from the first inverter (voltage).
        await flow.async_step_init(user_input=None)
        assert flow._control_mode_prefill == ("voltage", "voltage")
        # Submit with the pickers untouched (plus an unrelated change).
        result = await flow.async_step_init(
            user_input={
                CONF_CHARGE_CONTROL_MODE: "voltage",
                CONF_DISCHARGE_CONTROL_MODE: "voltage",
                "sensor_update_interval": 30,
            }
        )
        coordinator.async_write_battery_control_mode.assert_not_called()
        assert str(result["type"]) == "create_entry"

    @pytest.mark.asyncio
    async def test_changed_picker_applies_regime(self):
        """Changing a picker from its prefill DOES write the regime."""
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        flow, coordinator = self._make_flow(
            options={},
            parameters={
                "FUNC_BAT_CHARGE_CONTROL": True,
                "FUNC_BAT_DISCHARGE_CONTROL": True,
            },
        )
        coordinator.async_write_battery_control_mode = AsyncMock()
        await flow.async_step_init(user_input=None)  # prefill = voltage/voltage
        await flow.async_step_init(
            user_input={
                CONF_CHARGE_CONTROL_MODE: "soc",
                CONF_DISCHARGE_CONTROL_MODE: "voltage",
            }
        )
        coordinator.async_write_battery_control_mode.assert_called_once_with(
            "INV1", "soc", "voltage"
        )
