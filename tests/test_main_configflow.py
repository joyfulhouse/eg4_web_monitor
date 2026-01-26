"""Tests for the main EG4WebMonitorConfigFlow class assembly.

This module tests that the ConfigFlow is properly assembled from all mixins
and that routing works correctly.
"""

from __future__ import annotations

import inspect

import pytest

from custom_components.eg4_web_monitor.config_flow import (
    CannotConnectError,
    ConfigFlowProtocol,
    EG4ConfigFlowBase,
    EG4OptionsFlow,
    EG4WebMonitorConfigFlow,
    InvalidAuthError,
    LuxpowerClient,
    _build_user_data_schema,
    _timezone_observes_dst,
)


class TestConfigFlowAssembly:
    """Tests for ConfigFlow class assembly and MRO."""

    def test_configflow_class_exists(self):
        """Test that EG4WebMonitorConfigFlow class exists."""
        assert EG4WebMonitorConfigFlow is not None

    def test_configflow_inherits_all_onboarding_mixins(self):
        """Test that ConfigFlow inherits from all onboarding mixins."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]

        assert "HttpOnboardingMixin" in mro_names
        assert "ModbusOnboardingMixin" in mro_names
        assert "DongleOnboardingMixin" in mro_names
        assert "HybridOnboardingMixin" in mro_names
        assert "LocalOnboardingMixin" in mro_names

    def test_configflow_inherits_all_reconfigure_mixins(self):
        """Test that ConfigFlow inherits from all reconfigure mixins."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]

        assert "HttpReconfigureMixin" in mro_names
        assert "ModbusReconfigureMixin" in mro_names
        assert "HybridReconfigureMixin" in mro_names
        assert "LocalReconfigureMixin" in mro_names
        assert "ReauthMixin" in mro_names

    def test_configflow_inherits_base_class(self):
        """Test that ConfigFlow inherits from EG4ConfigFlowBase."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]

        assert "EG4ConfigFlowBase" in mro_names
        assert "ConfigFlow" in mro_names

    def test_configflow_mro_order(self):
        """Test that MRO has correct order (mixins before base)."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]

        # Base classes should come after all mixins
        base_index = mro_names.index("EG4ConfigFlowBase")
        configflow_index = mro_names.index("ConfigFlow")

        # All onboarding mixins should come before base
        assert mro_names.index("HttpOnboardingMixin") < base_index
        assert mro_names.index("ModbusOnboardingMixin") < base_index
        assert mro_names.index("DongleOnboardingMixin") < base_index

        # All reconfigure mixins should come before base
        assert mro_names.index("HttpReconfigureMixin") < base_index
        assert mro_names.index("ReauthMixin") < base_index

        # EG4ConfigFlowBase should come before ConfigFlow
        assert base_index < configflow_index

    def test_configflow_has_version(self):
        """Test that ConfigFlow has VERSION attribute."""
        assert hasattr(EG4WebMonitorConfigFlow, "VERSION")
        assert EG4WebMonitorConfigFlow.VERSION == 1


class TestConfigFlowRoutingMethods:
    """Tests for ConfigFlow routing methods."""

    def test_has_async_step_user(self):
        """Test that ConfigFlow has async_step_user method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_user")
        assert inspect.iscoroutinefunction(EG4WebMonitorConfigFlow.async_step_user)

    def test_has_async_step_reconfigure(self):
        """Test that ConfigFlow has async_step_reconfigure method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reconfigure")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reconfigure
        )

    def test_has_async_get_options_flow(self):
        """Test that ConfigFlow has async_get_options_flow method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_get_options_flow")


class TestOnboardingStepsFromMixins:
    """Tests for onboarding step methods from mixins."""

    def test_has_http_credentials_step(self):
        """Test that ConfigFlow has async_step_http_credentials from HttpOnboardingMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_http_credentials")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_http_credentials
        )

    def test_has_modbus_step(self):
        """Test that ConfigFlow has async_step_modbus from ModbusOnboardingMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_modbus")
        assert inspect.iscoroutinefunction(EG4WebMonitorConfigFlow.async_step_modbus)

    def test_has_dongle_step(self):
        """Test that ConfigFlow has async_step_dongle from DongleOnboardingMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_dongle")
        assert inspect.iscoroutinefunction(EG4WebMonitorConfigFlow.async_step_dongle)

    def test_has_hybrid_steps(self):
        """Test that ConfigFlow has hybrid steps from HybridOnboardingMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_hybrid_http")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_hybrid_local_type")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_hybrid_modbus")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_hybrid_dongle")

    def test_has_local_steps(self):
        """Test that ConfigFlow has local steps from LocalOnboardingMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_local_setup")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_local_add_device")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_local_modbus_device")
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_local_dongle_device")


class TestReconfigureStepsFromMixins:
    """Tests for reconfigure step methods from mixins."""

    def test_has_reconfigure_http_step(self):
        """Test that ConfigFlow has async_step_reconfigure_http from HttpReconfigureMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reconfigure_http")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reconfigure_http
        )

    def test_has_reconfigure_modbus_step(self):
        """Test that ConfigFlow has async_step_reconfigure_modbus from ModbusReconfigureMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reconfigure_modbus")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reconfigure_modbus
        )

    def test_has_reconfigure_hybrid_step(self):
        """Test that ConfigFlow has async_step_reconfigure_hybrid from HybridReconfigureMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reconfigure_hybrid")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reconfigure_hybrid
        )

    def test_has_reconfigure_local_step(self):
        """Test that ConfigFlow has async_step_reconfigure_local from LocalReconfigureMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reconfigure_local")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reconfigure_local
        )


class TestReauthStepsFromMixin:
    """Tests for reauth step methods from ReauthMixin."""

    def test_has_reauth_step(self):
        """Test that ConfigFlow has async_step_reauth from ReauthMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reauth")
        assert inspect.iscoroutinefunction(EG4WebMonitorConfigFlow.async_step_reauth)

    def test_has_reauth_confirm_step(self):
        """Test that ConfigFlow has async_step_reauth_confirm from ReauthMixin."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_reauth_confirm")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_reauth_confirm
        )


class TestBaseClassMethods:
    """Tests for base class methods from EG4ConfigFlowBase."""

    def test_has_test_credentials_method(self):
        """Test that ConfigFlow has _test_credentials from base class."""
        assert hasattr(EG4WebMonitorConfigFlow, "_test_credentials")
        assert inspect.iscoroutinefunction(EG4WebMonitorConfigFlow._test_credentials)

    def test_has_test_modbus_connection_method(self):
        """Test that ConfigFlow has _test_modbus_connection from base class."""
        assert hasattr(EG4WebMonitorConfigFlow, "_test_modbus_connection")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow._test_modbus_connection
        )

    def test_has_test_dongle_connection_method(self):
        """Test that ConfigFlow has _test_dongle_connection from base class."""
        assert hasattr(EG4WebMonitorConfigFlow, "_test_dongle_connection")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow._test_dongle_connection
        )


class TestBackwardCompatibility:
    """Tests for backward compatibility exports."""

    def test_exceptions_exported(self):
        """Test that exception classes are exported for backward compatibility."""
        assert CannotConnectError is not None
        assert InvalidAuthError is not None

    def test_client_exported(self):
        """Test that LuxpowerClient is exported for backward compatibility."""
        assert LuxpowerClient is not None

    def test_legacy_timezone_function_exported(self):
        """Test that _timezone_observes_dst is exported."""
        assert _timezone_observes_dst is not None

    def test_legacy_timezone_function_works(self):
        """Test that _timezone_observes_dst works with timezone argument."""
        # Should accept a timezone name
        result = _timezone_observes_dst("America/New_York")
        assert isinstance(result, bool)

    def test_legacy_schema_function_raises(self):
        """Test that _build_user_data_schema raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            _build_user_data_schema()

    def test_protocol_exported(self):
        """Test that ConfigFlowProtocol is exported."""
        assert ConfigFlowProtocol is not None

    def test_base_class_exported(self):
        """Test that EG4ConfigFlowBase is exported."""
        assert EG4ConfigFlowBase is not None


class TestOptionsFlow:
    """Tests for EG4OptionsFlow integration."""

    def test_options_flow_class_exists(self):
        """Test that EG4OptionsFlow is exported."""
        assert EG4OptionsFlow is not None

    def test_options_flow_has_async_step_init(self):
        """Test that EG4OptionsFlow has async_step_init method."""
        assert hasattr(EG4OptionsFlow, "async_step_init")
        assert inspect.iscoroutinefunction(EG4OptionsFlow.async_step_init)
