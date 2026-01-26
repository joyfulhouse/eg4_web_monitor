"""Tests for transition builders."""

from __future__ import annotations

import inspect

from custom_components.eg4_web_monitor.config_flow.transitions import (
    HttpToHybridBuilder,
    HybridToHttpBuilder,
    TransitionBuilder,
    TransitionContext,
    TransitionType,
)
from custom_components.eg4_web_monitor.const import (
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
)


class TestTransitionType:
    """Tests for TransitionType enum."""

    def test_http_to_hybrid_value(self):
        """Test HTTP to Hybrid transition type value."""
        assert TransitionType.HTTP_TO_HYBRID.value == "http_to_hybrid"

    def test_hybrid_to_http_value(self):
        """Test Hybrid to HTTP transition type value."""
        assert TransitionType.HYBRID_TO_HTTP.value == "hybrid_to_http"

    def test_modbus_to_dongle_value(self):
        """Test Modbus to Dongle transition type value."""
        assert TransitionType.MODBUS_TO_DONGLE.value == "modbus_to_dongle"

    def test_dongle_to_modbus_value(self):
        """Test Dongle to Modbus transition type value."""
        assert TransitionType.DONGLE_TO_MODBUS.value == "dongle_to_modbus"


class TestTransitionContext:
    """Tests for TransitionContext dataclass."""

    def test_default_values(self):
        """Test TransitionContext default values."""
        context = TransitionContext()

        assert context.validated_credentials == {}
        assert context.local_transport_config is None
        assert context.test_results == {}
        assert context.warnings == []

    def test_with_credentials(self):
        """Test TransitionContext with validated credentials."""
        creds = {"username": "test", "password": "pass"}
        context = TransitionContext(validated_credentials=creds)

        assert context.validated_credentials == creds
        assert context.validated_credentials["username"] == "test"

    def test_with_local_transport(self):
        """Test TransitionContext with local transport config."""
        transport = {
            "serial": "CE12345",
            "transport_type": "modbus_tcp",
            "host": "192.168.1.100",
        }
        context = TransitionContext(local_transport_config=transport)

        assert context.local_transport_config is not None
        assert context.local_transport_config["host"] == "192.168.1.100"

    def test_with_warnings(self):
        """Test TransitionContext with warnings."""
        warnings = ["Warning 1", "Warning 2"]
        context = TransitionContext(warnings=warnings)

        assert len(context.warnings) == 2
        assert "Warning 1" in context.warnings


class TestTransitionBuilder:
    """Tests for TransitionBuilder abstract base class."""

    def test_is_abstract_class(self):
        """Test that TransitionBuilder is an abstract class."""
        assert inspect.isabstract(TransitionBuilder)

    def test_has_validate_method(self):
        """Test that TransitionBuilder has validate method."""
        assert hasattr(TransitionBuilder, "validate")
        assert inspect.iscoroutinefunction(TransitionBuilder.validate)

    def test_has_collect_input_method(self):
        """Test that TransitionBuilder has collect_input method."""
        assert hasattr(TransitionBuilder, "collect_input")
        assert inspect.iscoroutinefunction(TransitionBuilder.collect_input)

    def test_has_execute_method(self):
        """Test that TransitionBuilder has execute method."""
        assert hasattr(TransitionBuilder, "execute")
        assert inspect.iscoroutinefunction(TransitionBuilder.execute)

    def test_has_add_warning_method(self):
        """Test that TransitionBuilder has add_warning method."""
        assert hasattr(TransitionBuilder, "add_warning")


class TestHttpToHybridBuilder:
    """Tests for HttpToHybridBuilder."""

    def test_class_exists(self):
        """Test that HttpToHybridBuilder class exists."""
        assert HttpToHybridBuilder is not None

    def test_inherits_from_transition_builder(self):
        """Test that HttpToHybridBuilder inherits from TransitionBuilder."""
        assert issubclass(HttpToHybridBuilder, TransitionBuilder)

    def test_has_step_constants(self):
        """Test that HttpToHybridBuilder has step constants."""
        assert hasattr(HttpToHybridBuilder, "STEP_SELECT_LOCAL_TYPE")
        assert hasattr(HttpToHybridBuilder, "STEP_MODBUS")
        assert hasattr(HttpToHybridBuilder, "STEP_DONGLE")
        assert hasattr(HttpToHybridBuilder, "STEP_CONFIRM")

    def test_step_constant_values(self):
        """Test step constant values are unique."""
        steps = [
            HttpToHybridBuilder.STEP_SELECT_LOCAL_TYPE,
            HttpToHybridBuilder.STEP_MODBUS,
            HttpToHybridBuilder.STEP_DONGLE,
            HttpToHybridBuilder.STEP_CONFIRM,
        ]
        # All steps should be unique
        assert len(steps) == len(set(steps))

    def test_has_validate_method(self):
        """Test that HttpToHybridBuilder has validate method."""
        assert hasattr(HttpToHybridBuilder, "validate")
        assert inspect.iscoroutinefunction(HttpToHybridBuilder.validate)

    def test_has_collect_input_method(self):
        """Test that HttpToHybridBuilder has collect_input method."""
        assert hasattr(HttpToHybridBuilder, "collect_input")
        assert inspect.iscoroutinefunction(HttpToHybridBuilder.collect_input)

    def test_has_execute_method(self):
        """Test that HttpToHybridBuilder has execute method."""
        assert hasattr(HttpToHybridBuilder, "execute")
        assert inspect.iscoroutinefunction(HttpToHybridBuilder.execute)


class TestHybridToHttpBuilder:
    """Tests for HybridToHttpBuilder."""

    def test_class_exists(self):
        """Test that HybridToHttpBuilder class exists."""
        assert HybridToHttpBuilder is not None

    def test_inherits_from_transition_builder(self):
        """Test that HybridToHttpBuilder inherits from TransitionBuilder."""
        assert issubclass(HybridToHttpBuilder, TransitionBuilder)

    def test_has_step_constants(self):
        """Test that HybridToHttpBuilder has step constants."""
        assert hasattr(HybridToHttpBuilder, "STEP_CONFIRM_REMOVAL")

    def test_has_validate_method(self):
        """Test that HybridToHttpBuilder has validate method."""
        assert hasattr(HybridToHttpBuilder, "validate")
        assert inspect.iscoroutinefunction(HybridToHttpBuilder.validate)

    def test_has_collect_input_method(self):
        """Test that HybridToHttpBuilder has collect_input method."""
        assert hasattr(HybridToHttpBuilder, "collect_input")
        assert inspect.iscoroutinefunction(HybridToHttpBuilder.collect_input)

    def test_has_execute_method(self):
        """Test that HybridToHttpBuilder has execute method."""
        assert hasattr(HybridToHttpBuilder, "execute")
        assert inspect.iscoroutinefunction(HybridToHttpBuilder.execute)


class TestInverterFamilyOptions:
    """Tests for inverter family options in http_to_hybrid module."""

    def test_inverter_family_options_exist(self):
        """Test that inverter family options are defined."""
        from custom_components.eg4_web_monitor.config_flow.transitions.http_to_hybrid import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_local_type_options_exist(self):
        """Test that local type options are defined."""
        from custom_components.eg4_web_monitor.config_flow.transitions.http_to_hybrid import (
            LOCAL_TYPE_OPTIONS,
        )

        assert "modbus" in LOCAL_TYPE_OPTIONS
        assert "dongle" in LOCAL_TYPE_OPTIONS
