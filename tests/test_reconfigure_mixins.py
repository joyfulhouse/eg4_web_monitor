"""Tests for reconfigure mixins."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING


from custom_components.eg4_web_monitor.config_flow.reconfigure import (
    HttpReconfigureMixin,
    HybridReconfigureMixin,
    LocalReconfigureMixin,
    ModbusReconfigureMixin,
    ReauthMixin,
)
from custom_components.eg4_web_monitor.const import (
    INVERTER_FAMILY_LXP_EU,
    INVERTER_FAMILY_PV_SERIES,
    INVERTER_FAMILY_SNA,
)

if TYPE_CHECKING:
    pass


class TestReauthMixin:
    """Tests for ReauthMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert ReauthMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(ReauthMixin, "async_step_reauth")
        assert hasattr(ReauthMixin, "async_step_reauth_confirm")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(ReauthMixin.async_step_reauth)
        assert inspect.iscoroutinefunction(ReauthMixin.async_step_reauth_confirm)


class TestHttpReconfigureMixin:
    """Tests for HttpReconfigureMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert HttpReconfigureMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(HttpReconfigureMixin, "async_step_reconfigure_http")
        assert hasattr(HttpReconfigureMixin, "async_step_reconfigure_plant")
        assert hasattr(HttpReconfigureMixin, "_update_http_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(
            HttpReconfigureMixin.async_step_reconfigure_http
        )
        assert inspect.iscoroutinefunction(
            HttpReconfigureMixin.async_step_reconfigure_plant
        )
        assert inspect.iscoroutinefunction(HttpReconfigureMixin._update_http_entry)


class TestModbusReconfigureMixin:
    """Tests for ModbusReconfigureMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert ModbusReconfigureMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(ModbusReconfigureMixin, "async_step_reconfigure_modbus")
        assert hasattr(ModbusReconfigureMixin, "_update_modbus_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(
            ModbusReconfigureMixin.async_step_reconfigure_modbus
        )
        assert inspect.iscoroutinefunction(ModbusReconfigureMixin._update_modbus_entry)


class TestHybridReconfigureMixin:
    """Tests for HybridReconfigureMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert HybridReconfigureMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(HybridReconfigureMixin, "async_step_reconfigure_hybrid")
        assert hasattr(HybridReconfigureMixin, "async_step_reconfigure_hybrid_plant")
        assert hasattr(HybridReconfigureMixin, "_update_hybrid_entry_from_reconfigure")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(
            HybridReconfigureMixin.async_step_reconfigure_hybrid
        )
        assert inspect.iscoroutinefunction(
            HybridReconfigureMixin.async_step_reconfigure_hybrid_plant
        )
        assert inspect.iscoroutinefunction(
            HybridReconfigureMixin._update_hybrid_entry_from_reconfigure
        )


class TestLocalReconfigureMixin:
    """Tests for LocalReconfigureMixin."""

    def test_mixin_class_exists(self):
        """Test that the mixin class exists and can be imported."""
        assert LocalReconfigureMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that the mixin has the required step methods."""
        assert hasattr(LocalReconfigureMixin, "async_step_reconfigure_local")
        assert hasattr(LocalReconfigureMixin, "async_step_reconfigure_local_modbus")
        assert hasattr(LocalReconfigureMixin, "async_step_reconfigure_local_dongle")
        assert hasattr(LocalReconfigureMixin, "_update_local_entry")

    def test_step_methods_are_async(self):
        """Test that step methods are coroutine functions."""
        assert inspect.iscoroutinefunction(
            LocalReconfigureMixin.async_step_reconfigure_local
        )
        assert inspect.iscoroutinefunction(
            LocalReconfigureMixin.async_step_reconfigure_local_modbus
        )
        assert inspect.iscoroutinefunction(
            LocalReconfigureMixin.async_step_reconfigure_local_dongle
        )
        assert inspect.iscoroutinefunction(LocalReconfigureMixin._update_local_entry)


class TestReconfigureMixinInverterFamilyOptions:
    """Tests for inverter family options constants in reconfigure mixins."""

    def test_modbus_inverter_family_options(self):
        """Test that Modbus reconfigure mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.reconfigure.modbus import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_hybrid_inverter_family_options(self):
        """Test that Hybrid reconfigure mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.reconfigure.hybrid import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS

    def test_local_inverter_family_options(self):
        """Test that Local reconfigure mixin has inverter family options."""
        from custom_components.eg4_web_monitor.config_flow.reconfigure.local import (
            INVERTER_FAMILY_OPTIONS,
        )

        assert INVERTER_FAMILY_PV_SERIES in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_SNA in INVERTER_FAMILY_OPTIONS
        assert INVERTER_FAMILY_LXP_EU in INVERTER_FAMILY_OPTIONS


class TestLocalReconfigureDeviceTypeOptions:
    """Tests for local reconfigure device type options."""

    def test_device_type_options_exist(self):
        """Test that device type options are defined."""
        from custom_components.eg4_web_monitor.config_flow.reconfigure.local import (
            LOCAL_DEVICE_TYPE_OPTIONS,
        )

        assert "modbus" in LOCAL_DEVICE_TYPE_OPTIONS
        assert "dongle" in LOCAL_DEVICE_TYPE_OPTIONS
