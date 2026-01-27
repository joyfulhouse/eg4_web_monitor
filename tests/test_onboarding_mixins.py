"""Tests for onboarding mixins."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import voluptuous as vol

from custom_components.eg4_web_monitor.config_flow.onboarding import (
    DongleOnboardingMixin,
    HttpOnboardingMixin,
    HybridOnboardingMixin,
    LocalOnboardingMixin,
    ModbusOnboardingMixin,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_VERIFY_SSL,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

if TYPE_CHECKING:
    pass


class TestHttpOnboardingMixin:
    """Tests for HttpOnboardingMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert HttpOnboardingMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(HttpOnboardingMixin, "async_step_http_credentials")
        assert hasattr(HttpOnboardingMixin, "async_step_plant")
        assert hasattr(HttpOnboardingMixin, "_create_http_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(
            HttpOnboardingMixin.async_step_http_credentials
        )
        assert inspect.iscoroutinefunction(HttpOnboardingMixin.async_step_plant)
        assert inspect.iscoroutinefunction(HttpOnboardingMixin._create_http_entry)


class TestModbusOnboardingMixin:
    """Tests for ModbusOnboardingMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert ModbusOnboardingMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(ModbusOnboardingMixin, "async_step_modbus")
        assert hasattr(ModbusOnboardingMixin, "_create_modbus_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(ModbusOnboardingMixin.async_step_modbus)
        assert inspect.iscoroutinefunction(ModbusOnboardingMixin._create_modbus_entry)


class TestDongleOnboardingMixin:
    """Tests for DongleOnboardingMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert DongleOnboardingMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(DongleOnboardingMixin, "async_step_dongle")
        assert hasattr(DongleOnboardingMixin, "_create_dongle_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(DongleOnboardingMixin.async_step_dongle)
        assert inspect.iscoroutinefunction(DongleOnboardingMixin._create_dongle_entry)


class TestHybridOnboardingMixin:
    """Tests for HybridOnboardingMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert HybridOnboardingMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(HybridOnboardingMixin, "async_step_hybrid_http")
        assert hasattr(HybridOnboardingMixin, "async_step_hybrid_plant")
        assert hasattr(HybridOnboardingMixin, "async_step_hybrid_local_type")
        assert hasattr(HybridOnboardingMixin, "async_step_hybrid_modbus")
        assert hasattr(HybridOnboardingMixin, "async_step_hybrid_dongle")
        assert hasattr(HybridOnboardingMixin, "_create_hybrid_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(HybridOnboardingMixin.async_step_hybrid_http)
        assert inspect.iscoroutinefunction(
            HybridOnboardingMixin.async_step_hybrid_plant
        )
        assert inspect.iscoroutinefunction(
            HybridOnboardingMixin.async_step_hybrid_local_type
        )
        assert inspect.iscoroutinefunction(
            HybridOnboardingMixin.async_step_hybrid_modbus
        )
        assert inspect.iscoroutinefunction(
            HybridOnboardingMixin.async_step_hybrid_dongle
        )
        assert inspect.iscoroutinefunction(HybridOnboardingMixin._create_hybrid_entry)


class TestLocalOnboardingMixin:
    """Tests for LocalOnboardingMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert LocalOnboardingMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(LocalOnboardingMixin, "async_step_local_setup")
        assert hasattr(LocalOnboardingMixin, "async_step_local_add_device")
        assert hasattr(LocalOnboardingMixin, "async_step_local_modbus_connect")
        assert hasattr(LocalOnboardingMixin, "async_step_local_dongle_connect")
        assert hasattr(LocalOnboardingMixin, "async_step_local_device_discovered")
        assert hasattr(LocalOnboardingMixin, "async_step_local_name")
        assert hasattr(LocalOnboardingMixin, "_create_local_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(LocalOnboardingMixin.async_step_local_setup)
        assert inspect.iscoroutinefunction(
            LocalOnboardingMixin.async_step_local_add_device
        )
        assert inspect.iscoroutinefunction(
            LocalOnboardingMixin.async_step_local_modbus_connect
        )
        assert inspect.iscoroutinefunction(
            LocalOnboardingMixin.async_step_local_dongle_connect
        )
        assert inspect.iscoroutinefunction(
            LocalOnboardingMixin.async_step_local_device_discovered
        )
        assert inspect.iscoroutinefunction(LocalOnboardingMixin.async_step_local_name)
        assert inspect.iscoroutinefunction(LocalOnboardingMixin._create_local_entry)


class TestOnboardingMixinSchemas:
    """Tests for schema functions in onboarding mixins."""

    def test_http_credentials_schema_builder(self):
        """Test the HTTP credentials schema builder."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.http import (
            _build_http_credentials_schema,
        )

        schema = _build_http_credentials_schema()
        assert isinstance(schema, vol.Schema)

        # Test validation with valid data
        result = schema(
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "password123",
            }
        )
        assert result[CONF_USERNAME] == "test@example.com"
        assert result[CONF_PASSWORD] == "password123"
        assert result[CONF_BASE_URL] == DEFAULT_BASE_URL
        assert result[CONF_VERIFY_SSL] is True
        assert result[CONF_DST_SYNC] is True
        assert result[CONF_LIBRARY_DEBUG] is False

    def test_http_credentials_schema_dst_default(self):
        """Test DST sync default can be customized."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.http import (
            _build_http_credentials_schema,
        )

        schema_true = _build_http_credentials_schema(dst_sync_default=True)
        schema_false = _build_http_credentials_schema(dst_sync_default=False)

        result_true = schema_true({CONF_USERNAME: "test", CONF_PASSWORD: "pass"})
        result_false = schema_false({CONF_USERNAME: "test", CONF_PASSWORD: "pass"})

        assert result_true[CONF_DST_SYNC] is True
        assert result_false[CONF_DST_SYNC] is False

    def test_modbus_schema_builder(self):
        """Test the Modbus schema builder."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.modbus import (
            _build_modbus_schema,
        )

        schema = _build_modbus_schema()
        assert isinstance(schema, vol.Schema)

        # Test validation with valid data
        result = schema({CONF_MODBUS_HOST: "192.168.1.100"})
        assert result[CONF_MODBUS_HOST] == "192.168.1.100"
        assert result[CONF_MODBUS_PORT] == DEFAULT_MODBUS_PORT
        assert result[CONF_MODBUS_UNIT_ID] == DEFAULT_MODBUS_UNIT_ID

    def test_modbus_schema_builder_with_defaults(self):
        """Test the Modbus schema builder with custom defaults."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.modbus import (
            _build_modbus_schema,
        )

        defaults = {
            CONF_MODBUS_HOST: "192.168.1.200",
            CONF_MODBUS_PORT: 8502,
            CONF_INVERTER_SERIAL: "1234567890",
        }
        schema = _build_modbus_schema(defaults)
        result = schema({CONF_MODBUS_HOST: "192.168.1.200"})
        assert result[CONF_MODBUS_PORT] == 8502

    def test_dongle_schema_builder(self):
        """Test the Dongle schema builder."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.dongle import (
            _build_dongle_schema,
        )

        schema = _build_dongle_schema()
        assert isinstance(schema, vol.Schema)

        # Schema has defaults, so we can validate with minimal input
        result = schema(
            {
                CONF_DONGLE_HOST: "192.168.1.100",
                CONF_DONGLE_SERIAL: "dongle123",
                CONF_INVERTER_SERIAL: "inverter456",
            }
        )
        assert result[CONF_DONGLE_HOST] == "192.168.1.100"
        assert result[CONF_DONGLE_PORT] == DEFAULT_DONGLE_PORT


class TestOnboardingMixinInverterFamilyOptions:
    """Tests for inverter family options constants."""

    def test_modbus_inverter_family_options(self):
        """Test that Modbus mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.modbus import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_dongle_inverter_family_options(self):
        """Test that Dongle mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.dongle import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_hybrid_inverter_family_options(self):
        """Test that Hybrid mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.hybrid import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_local_inverter_family_options(self):
        """Test that inverter family options are defined in schemas.

        Note: The unified local flow auto-detects inverter family from
        the device type code register, so it doesn't use INVERTER_FAMILY_OPTIONS
        directly in the UI. But the options should still exist in schemas.
        """
        from custom_components.eg4_web_monitor.config_flow.schemas import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS


class TestHybridMixinLocalTypeOptions:
    """Tests for hybrid mixin local type options."""

    def test_local_type_options_exist(self):
        """Test that local type options are defined."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.hybrid import (
            LOCAL_TYPE_OPTIONS,
        )

        assert HYBRID_LOCAL_MODBUS in LOCAL_TYPE_OPTIONS
        assert HYBRID_LOCAL_DONGLE in LOCAL_TYPE_OPTIONS

    def test_local_type_options_descriptions(self):
        """Test that local type options have descriptions."""
        from custom_components.eg4_web_monitor.config_flow.onboarding.hybrid import (
            LOCAL_TYPE_OPTIONS,
        )

        assert "Modbus" in LOCAL_TYPE_OPTIONS[HYBRID_LOCAL_MODBUS]
        assert "Dongle" in LOCAL_TYPE_OPTIONS[HYBRID_LOCAL_DONGLE]


class TestLocalMixinDeviceTypeOptions:
    """Tests for local mixin device type options."""

    def test_device_type_options_exist(self):
        """Test that device type options are defined in schemas."""
        from custom_components.eg4_web_monitor.config_flow.schemas import (
            LOCAL_DEVICE_TYPE_OPTIONS,
        )

        assert "modbus" in LOCAL_DEVICE_TYPE_OPTIONS
        assert "dongle" in LOCAL_DEVICE_TYPE_OPTIONS
