"""Tests for the TransitionMixin class.

This module tests the transition flow steps provided by TransitionMixin,
including HTTP → Hybrid and Hybrid → HTTP transitions.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

from custom_components.eg4_web_monitor.config_flow import EG4WebMonitorConfigFlow
from custom_components.eg4_web_monitor.config_flow.transitions import (
    HttpToHybridBuilder,
    HybridToHttpBuilder,
    TransitionMixin,
)
from custom_components.eg4_web_monitor.config_flow.transitions.mixin import (
    TRANSITION_OPTIONS_HTTP,
    TRANSITION_OPTIONS_HYBRID,
)
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_MODBUS,
)


def _run_async(coro):
    """Helper to run async code in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Test Class Assembly
# =============================================================================


class TestTransitionMixinAssembly:
    """Tests for TransitionMixin class assembly."""

    def test_transition_mixin_exists(self):
        """Test that TransitionMixin class exists."""
        assert TransitionMixin is not None

    def test_configflow_inherits_transition_mixin(self):
        """Test that ConfigFlow inherits from TransitionMixin."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]
        assert "TransitionMixin" in mro_names

    def test_transition_mixin_before_base_in_mro(self):
        """Test that TransitionMixin comes before base classes in MRO."""
        mro = EG4WebMonitorConfigFlow.__mro__
        mro_names = [c.__name__ for c in mro]

        transition_index = mro_names.index("TransitionMixin")
        base_index = mro_names.index("EG4ConfigFlowBase")
        configflow_index = mro_names.index("ConfigFlow")

        assert transition_index < base_index
        assert transition_index < configflow_index


# =============================================================================
# Test Step Methods Availability
# =============================================================================


class TestTransitionStepMethods:
    """Tests for TransitionMixin step methods availability."""

    def test_has_async_step_transition_select(self):
        """Test that ConfigFlow has async_step_transition_select method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_select")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_select
        )

    def test_has_async_step_transition_http_to_hybrid(self):
        """Test that ConfigFlow has async_step_transition_http_to_hybrid method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_http_to_hybrid")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_http_to_hybrid
        )

    def test_has_async_step_transition_hybrid_to_http(self):
        """Test that ConfigFlow has async_step_transition_hybrid_to_http method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_hybrid_to_http")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_hybrid_to_http
        )

    def test_has_async_step_transition_select_local_type(self):
        """Test that ConfigFlow has async_step_transition_select_local_type method."""
        assert hasattr(
            EG4WebMonitorConfigFlow, "async_step_transition_select_local_type"
        )
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_select_local_type
        )

    def test_has_async_step_transition_modbus(self):
        """Test that ConfigFlow has async_step_transition_modbus method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_modbus")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_modbus
        )

    def test_has_async_step_transition_dongle(self):
        """Test that ConfigFlow has async_step_transition_dongle method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_dongle")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_dongle
        )

    def test_has_async_step_transition_confirm(self):
        """Test that ConfigFlow has async_step_transition_confirm method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_confirm")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_confirm
        )

    def test_has_async_step_transition_confirm_removal(self):
        """Test that ConfigFlow has async_step_transition_confirm_removal method."""
        assert hasattr(EG4WebMonitorConfigFlow, "async_step_transition_confirm_removal")
        assert inspect.iscoroutinefunction(
            EG4WebMonitorConfigFlow.async_step_transition_confirm_removal
        )


# =============================================================================
# Test Transition Options
# =============================================================================


class TestTransitionOptions:
    """Tests for transition options constants."""

    def test_http_transition_options_contains_upgrade(self):
        """Test that HTTP options contain upgrade to hybrid."""
        assert "upgrade_to_hybrid" in TRANSITION_OPTIONS_HTTP
        assert "no_change" in TRANSITION_OPTIONS_HTTP

    def test_hybrid_transition_options_contains_downgrade(self):
        """Test that Hybrid options contain downgrade to HTTP."""
        assert "downgrade_to_http" in TRANSITION_OPTIONS_HYBRID
        assert "no_change" in TRANSITION_OPTIONS_HYBRID

    def test_transition_options_have_descriptions(self):
        """Test that transition options have user-friendly descriptions."""
        for key, value in TRANSITION_OPTIONS_HTTP.items():
            assert isinstance(value, str)
            assert len(value) > 0

        for key, value in TRANSITION_OPTIONS_HYBRID.items():
            assert isinstance(value, str)
            assert len(value) > 0


# =============================================================================
# Test Transition Select Step (mocked hass)
# =============================================================================


class TestTransitionSelectStepMocked:
    """Tests for async_step_transition_select behavior using mocks."""

    def test_transition_select_aborts_without_entry_id(self):
        """Test that transition select aborts when entry_id is missing."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {}  # No entry_id
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "entry_not_found"}
        )

        result = _run_async(TransitionMixin.async_step_transition_select(flow, None))

        assert result["type"] == "abort"
        assert result["reason"] == "entry_not_found"

    def test_transition_select_aborts_entry_not_found(self):
        """Test that transition select aborts when entry doesn't exist."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "nonexistent_entry"}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = None
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "entry_not_found"}
        )

        result = _run_async(TransitionMixin.async_step_transition_select(flow, None))

        assert result["type"] == "abort"
        assert result["reason"] == "entry_not_found"


# =============================================================================
# Test HTTP to Hybrid Builder Step (mocked)
# =============================================================================


class TestHttpToHybridStepMocked:
    """Tests for HTTP to Hybrid transition step using mocks."""

    def test_http_to_hybrid_aborts_without_entry(self):
        """Test that HTTP to Hybrid aborts when entry is missing."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {}  # No entry_id
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "entry_not_found"}
        )

        result = _run_async(
            TransitionMixin.async_step_transition_http_to_hybrid(flow, None)
        )

        assert result["type"] == "abort"
        assert result["reason"] == "entry_not_found"


# =============================================================================
# Test Hybrid to HTTP Builder Step (mocked)
# =============================================================================


class TestHybridToHttpStepMocked:
    """Tests for Hybrid to HTTP transition step using mocks."""

    def test_hybrid_to_http_aborts_without_entry(self):
        """Test that Hybrid to HTTP aborts when entry is missing."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {}  # No entry_id
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "entry_not_found"}
        )

        result = _run_async(
            TransitionMixin.async_step_transition_hybrid_to_http(flow, None)
        )

        assert result["type"] == "abort"
        assert result["reason"] == "entry_not_found"


# =============================================================================
# Test Pass-Through Step Methods (mocked)
# =============================================================================


class TestPassThroughStepMethodsMocked:
    """Tests for pass-through step methods that delegate to builders."""

    def test_transition_confirm_without_builder(self):
        """Test that confirm step aborts without builder."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {}
        flow._transition_builder = None
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "transition_not_started"}
        )

        result = _run_async(TransitionMixin.async_step_transition_confirm(flow, None))

        assert result["type"] == "abort"
        assert result["reason"] == "transition_not_started"


# =============================================================================
# Test Builder Delegation (mocked)
# =============================================================================


class TestBuilderDelegationMocked:
    """Tests for step methods delegating to builders using mocks."""

    def test_select_local_type_delegates_to_builder(self):
        """Test that select_local_type delegates to builder's collect_input."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HttpToHybridBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "form", "step_id": "test_step"}
        )
        flow._transition_builder = mock_builder

        _run_async(
            TransitionMixin.async_step_transition_select_local_type(
                flow, {"test_input": "value"}
            )
        )

        mock_builder.collect_input.assert_called_once_with(
            HttpToHybridBuilder.STEP_SELECT_LOCAL_TYPE, {"test_input": "value"}
        )

    def test_modbus_delegates_to_builder(self):
        """Test that modbus step delegates to builder's collect_input."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HttpToHybridBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "form", "step_id": "test_step"}
        )
        flow._transition_builder = mock_builder

        modbus_input = {CONF_MODBUS_HOST: "192.168.1.100", CONF_MODBUS_PORT: 502}

        _run_async(TransitionMixin.async_step_transition_modbus(flow, modbus_input))

        mock_builder.collect_input.assert_called_once_with(
            HttpToHybridBuilder.STEP_MODBUS, modbus_input
        )

    def test_dongle_delegates_to_builder(self):
        """Test that dongle step delegates to builder's collect_input."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HttpToHybridBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "form", "step_id": "test_step"}
        )
        flow._transition_builder = mock_builder

        dongle_input = {
            CONF_DONGLE_HOST: "192.168.1.100",
            CONF_DONGLE_SERIAL: "ABC123",
        }

        _run_async(TransitionMixin.async_step_transition_dongle(flow, dongle_input))

        mock_builder.collect_input.assert_called_once_with(
            HttpToHybridBuilder.STEP_DONGLE, dongle_input
        )

    def test_confirm_delegates_to_http_to_hybrid_builder(self):
        """Test that confirm delegates to HttpToHybridBuilder."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HttpToHybridBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "abort", "reason": "success"}
        )
        flow._transition_builder = mock_builder

        _run_async(TransitionMixin.async_step_transition_confirm(flow, {}))

        mock_builder.collect_input.assert_called_once_with(
            HttpToHybridBuilder.STEP_CONFIRM, {}
        )

    def test_confirm_delegates_to_hybrid_to_http_builder(self):
        """Test that confirm delegates to HybridToHttpBuilder."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HybridToHttpBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "abort", "reason": "success"}
        )
        flow._transition_builder = mock_builder

        _run_async(TransitionMixin.async_step_transition_confirm(flow, {}))

        mock_builder.collect_input.assert_called_once_with(
            HybridToHttpBuilder.STEP_CONFIRM_REMOVAL, {}
        )

    def test_confirm_removal_delegates_to_builder(self):
        """Test that confirm_removal delegates to HybridToHttpBuilder."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_entry"}

        mock_builder = MagicMock(spec=HybridToHttpBuilder)
        mock_builder.collect_input = AsyncMock(
            return_value={"type": "form", "step_id": "test_step"}
        )
        flow._transition_builder = mock_builder

        _run_async(TransitionMixin.async_step_transition_confirm_removal(flow, {}))

        mock_builder.collect_input.assert_called_once_with(
            HybridToHttpBuilder.STEP_CONFIRM_REMOVAL, {}
        )


# =============================================================================
# Test Builder State Management
# =============================================================================


class TestBuilderStateManagement:
    """Tests for builder state management in TransitionMixin."""

    def test_builder_is_none_initially(self):
        """Test that _transition_builder is None initially."""
        flow = EG4WebMonitorConfigFlow()
        assert flow._transition_builder is None

    def test_transition_builder_attribute_on_mixin(self):
        """Test that TransitionMixin has _transition_builder attribute."""
        assert hasattr(TransitionMixin, "_transition_builder")


# =============================================================================
# Test Builder Constants
# =============================================================================


class TestBuilderConstants:
    """Tests for builder step constants."""

    def test_http_to_hybrid_builder_has_step_constants(self):
        """Test that HttpToHybridBuilder has step constants."""
        assert hasattr(HttpToHybridBuilder, "STEP_SELECT_LOCAL_TYPE")
        assert hasattr(HttpToHybridBuilder, "STEP_MODBUS")
        assert hasattr(HttpToHybridBuilder, "STEP_DONGLE")
        assert hasattr(HttpToHybridBuilder, "STEP_CONFIRM")

        assert (
            HttpToHybridBuilder.STEP_SELECT_LOCAL_TYPE == "transition_select_local_type"
        )
        assert HttpToHybridBuilder.STEP_MODBUS == "transition_modbus"
        assert HttpToHybridBuilder.STEP_DONGLE == "transition_dongle"
        assert HttpToHybridBuilder.STEP_CONFIRM == "transition_confirm"

    def test_hybrid_to_http_builder_has_step_constants(self):
        """Test that HybridToHttpBuilder has step constants."""
        assert hasattr(HybridToHttpBuilder, "STEP_CONFIRM_REMOVAL")
        assert HybridToHttpBuilder.STEP_CONFIRM_REMOVAL == "transition_confirm_removal"


# =============================================================================
# Test Transition Type Flow (integration-style with mocks)
# =============================================================================


class TestTransitionTypeSelection:
    """Tests for transition type selection routing."""

    def test_transition_routes_upgrade_to_http_to_hybrid(self):
        """Test that 'upgrade_to_hybrid' routes to http_to_hybrid step."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_http_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry

        flow.async_step_transition_http_to_hybrid = AsyncMock(
            return_value={"type": "form", "step_id": "transition_select_local_type"}
        )

        _run_async(
            TransitionMixin.async_step_transition_select(
                flow, {"transition_type": "upgrade_to_hybrid"}
            )
        )

        flow.async_step_transition_http_to_hybrid.assert_called_once()

    def test_transition_routes_downgrade_to_hybrid_to_http(self):
        """Test that 'downgrade_to_http' routes to hybrid_to_http step."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_hybrid_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry

        flow.async_step_transition_hybrid_to_http = AsyncMock(
            return_value={"type": "form", "step_id": "transition_confirm_removal"}
        )

        _run_async(
            TransitionMixin.async_step_transition_select(
                flow, {"transition_type": "downgrade_to_http"}
            )
        )

        flow.async_step_transition_hybrid_to_http.assert_called_once()

    def test_transition_routes_no_change_to_http_reconfigure(self):
        """Test that 'no_change' routes to reconfigure_http for HTTP entry."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_http_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry

        flow.async_step_reconfigure_http = AsyncMock(
            return_value={"type": "form", "step_id": "reconfigure_http"}
        )

        _run_async(
            TransitionMixin.async_step_transition_select(
                flow, {"transition_type": "no_change"}
            )
        )

        flow.async_step_reconfigure_http.assert_called_once()

    def test_transition_routes_no_change_to_hybrid_reconfigure(self):
        """Test that 'no_change' routes to reconfigure_hybrid for Hybrid entry."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_hybrid_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry

        flow.async_step_reconfigure_hybrid = AsyncMock(
            return_value={"type": "form", "step_id": "reconfigure_hybrid"}
        )

        _run_async(
            TransitionMixin.async_step_transition_select(
                flow, {"transition_type": "no_change"}
            )
        )

        flow.async_step_reconfigure_hybrid.assert_called_once()

    def test_transition_aborts_for_unsupported_type(self):
        """Test that transition aborts for unsupported connection type."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_modbus_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_MODBUS}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry
        flow.async_abort = MagicMock(
            return_value={"type": "abort", "reason": "transition_not_supported"}
        )

        result = _run_async(TransitionMixin.async_step_transition_select(flow, None))

        assert result["type"] == "abort"
        assert result["reason"] == "transition_not_supported"

    def test_transition_shows_form_for_http_entry(self):
        """Test that transition shows form with HTTP options."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_http_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry
        flow.async_show_form = MagicMock(
            return_value={"type": "form", "step_id": "transition_select"}
        )

        _run_async(TransitionMixin.async_step_transition_select(flow, None))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args.kwargs
        assert call_kwargs["step_id"] == "transition_select"
        assert "Cloud API" in call_kwargs["description_placeholders"]["current_type"]

    def test_transition_shows_form_for_hybrid_entry(self):
        """Test that transition shows form with Hybrid options."""
        flow = MagicMock(spec=EG4WebMonitorConfigFlow)
        flow.context = {"entry_id": "test_hybrid_entry"}

        mock_entry = MagicMock()
        mock_entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID}
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = mock_entry
        flow.async_show_form = MagicMock(
            return_value={"type": "form", "step_id": "transition_select"}
        )

        _run_async(TransitionMixin.async_step_transition_select(flow, None))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args.kwargs
        assert call_kwargs["step_id"] == "transition_select"
        assert "Hybrid" in call_kwargs["description_placeholders"]["current_type"]
