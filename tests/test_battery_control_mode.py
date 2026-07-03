"""Tests for the battery control mode (SOC vs Voltage) feature.

Covers regime-gated number entities (enabled-default + effectiveness + warning),
the new voltage limit number entities, the battery charge/discharge control
select entities, and the options-flow pre-read/write behavior.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eg4_web_monitor.const import (
    CONTROL_MODE_SOC,
    CONTROL_MODE_VOLTAGE,
    control_side_and_mode,
    is_control_active,
)
from custom_components.eg4_web_monitor.number import (
    ACChargeEndVoltageNumber,
    ACChargeStartVoltageNumber,
    OffGridCutoffVoltageNumber,
    OnGridCutoffVoltageNumber,
    StopDischargeVoltageNumber,
    SystemChargeSOCLimitNumber,
    SystemChargeVoltLimitNumber,
)
from custom_components.eg4_web_monitor.select import (
    EG4BatteryChargeControlSelect,
    EG4BatteryDischargeControlSelect,
)


def _mock_coordinator(
    *,
    serial: str = "1234567890",
    model: str = "FlexBOSS21",
    has_local: bool = False,
    configured: tuple[str, str] = (CONTROL_MODE_SOC, CONTROL_MODE_SOC),
    live: tuple[str, str] = (CONTROL_MODE_SOC, CONTROL_MODE_SOC),
    parameters: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock coordinator with battery-control-mode helpers."""
    coordinator = MagicMock()
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.has_http_api = MagicMock(return_value=not has_local)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.is_local_only = MagicMock(return_value=has_local)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.write_named_parameter = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock()
    coordinator.get_configured_control_modes = MagicMock(return_value=configured)

    def _live(_serial: str, *, discharge: bool = False) -> str:
        return live[1] if discharge else live[0]

    coordinator.get_live_control_mode = MagicMock(side_effect=_live)

    coordinator.data = {
        "devices": {serial: {"type": "inverter", "model": model}},
        "device_info": {serial: {"deviceTypeText4APP": model}},
        "parameters": {serial: parameters or {}},
    }
    coordinator.get_device_info = MagicMock(return_value=None)

    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)
    coordinator.client = MagicMock()
    return coordinator


def _prep(entity: object) -> None:
    """Prepare entity for async action tests."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "number.test_entity"  # type: ignore[attr-defined]
    entity.platform = None  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


# ── Pure classification helpers ──────────────────────────────────────────────


class TestControlClassification:
    """The gating helpers in const.device_types."""

    def test_charge_voltage_active_only_in_voltage_charge_mode(self) -> None:
        assert is_control_active("system_charge_volt_limit", "voltage", "soc") is True
        assert is_control_active("system_charge_volt_limit", "soc", "voltage") is False

    def test_discharge_voltage_active_only_in_voltage_discharge_mode(self) -> None:
        assert is_control_active("on_grid_cutoff_voltage", "soc", "voltage") is True
        assert is_control_active("on_grid_cutoff_voltage", "voltage", "soc") is False
        # Stop discharge voltage (reg 202) is the same discharge/Voltage set
        assert is_control_active("stop_discharge_voltage", "soc", "voltage") is True
        assert is_control_active("stop_discharge_voltage", "voltage", "soc") is False

    def test_soc_controls_active_in_soc_mode(self) -> None:
        assert is_control_active("system_charge_soc_limit", "soc", "soc") is True
        assert is_control_active("on_grid_soc_cutoff", "soc", "soc") is True

    def test_non_gated_control_always_active(self) -> None:
        assert is_control_active("ac_charge_power", "voltage", "voltage") is True
        assert control_side_and_mode("ac_charge_power") is None

    def test_classification_sides(self) -> None:
        assert control_side_and_mode("system_charge_volt_limit") == (
            "charge",
            "voltage",
        )
        assert control_side_and_mode("on_grid_cutoff_voltage") == (
            "discharge",
            "voltage",
        )


# ── Enabled-default gating ───────────────────────────────────────────────────


class TestGatedEnabledDefault:
    """Regime-gated controls start enabled/disabled per the configured mode."""

    def test_soc_mode_enables_soc_disables_voltage(self) -> None:
        coordinator = _mock_coordinator(configured=(CONTROL_MODE_SOC, CONTROL_MODE_SOC))
        soc = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert soc.entity_registry_enabled_default is True
        assert volt.entity_registry_enabled_default is False

    def test_voltage_charge_mode_enables_voltage_disables_soc(self) -> None:
        coordinator = _mock_coordinator(
            configured=(CONTROL_MODE_VOLTAGE, CONTROL_MODE_SOC)
        )
        soc = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert soc.entity_registry_enabled_default is False
        assert volt.entity_registry_enabled_default is True

    def test_discharge_mode_gates_cutoffs_independently(self) -> None:
        coordinator = _mock_coordinator(
            configured=(CONTROL_MODE_SOC, CONTROL_MODE_VOLTAGE)
        )
        volt_cutoff = OnGridCutoffVoltageNumber(coordinator, "1234567890")
        # Charge-side voltage entity stays disabled (charge mode is SOC)
        charge_volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert volt_cutoff.entity_registry_enabled_default is True
        assert charge_volt.entity_registry_enabled_default is False

    def test_stop_discharge_voltage_gated_with_discharge_voltage_set(self) -> None:
        """Reg-202 stop voltage follows the discharge regime: disabled by
        default in SOC mode, enabled in Voltage mode (bead eg4-aa3t)."""
        soc_coordinator = _mock_coordinator(
            configured=(CONTROL_MODE_SOC, CONTROL_MODE_SOC)
        )
        volt_coordinator = _mock_coordinator(
            configured=(CONTROL_MODE_SOC, CONTROL_MODE_VOLTAGE)
        )
        in_soc = StopDischargeVoltageNumber(soc_coordinator, "1234567890")
        in_volt = StopDischargeVoltageNumber(volt_coordinator, "1234567890")
        assert in_soc.entity_registry_enabled_default is False
        assert in_volt.entity_registry_enabled_default is True


# ── Effectiveness attribute + warning ────────────────────────────────────────


class TestEffectiveness:
    """Live regime drives the is_effective attribute and the warning."""

    def test_effective_when_live_matches(self) -> None:
        coordinator = _mock_coordinator(live=(CONTROL_MODE_VOLTAGE, CONTROL_MODE_SOC))
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert volt.is_control_effective is True
        attrs = volt.extra_state_attributes
        assert attrs is not None
        assert attrs["is_effective"] is True
        assert attrs["control_regime"] == "voltage"
        assert attrs["active_control_mode"] == "voltage"

    def test_ineffective_when_live_differs(self) -> None:
        coordinator = _mock_coordinator(live=(CONTROL_MODE_SOC, CONTROL_MODE_SOC))
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert volt.is_control_effective is False
        attrs = volt.extra_state_attributes
        assert attrs is not None
        assert attrs["is_effective"] is False

    @pytest.mark.asyncio
    async def test_warns_on_ineffective_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Live charge mode is SOC; writing a Voltage-mode control warns.
        coordinator = _mock_coordinator(
            has_local=True, live=(CONTROL_MODE_SOC, CONTROL_MODE_SOC)
        )
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        _prep(volt)

        with caplog.at_level(logging.WARNING):
            await volt.async_set_native_value(58.0)

        assert "has no" in caplog.text and "effect" in caplog.text
        # The write still went through (persists for when the regime is switched)
        coordinator.write_named_parameter.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_warning_when_effective(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        coordinator = _mock_coordinator(
            has_local=True, live=(CONTROL_MODE_VOLTAGE, CONTROL_MODE_SOC)
        )
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        _prep(volt)

        with caplog.at_level(logging.WARNING):
            await volt.async_set_native_value(58.0)

        assert "no effect" not in caplog.text


# ── Voltage number entities (read + write) ───────────────────────────────────


class TestVoltageNumberEntities:
    """Voltage limit entities read decivolts and write local/cloud correctly."""

    def test_native_value_scales_decivolts_local(self) -> None:
        # Local transport surfaces the raw register value (decivolts).
        coordinator = _mock_coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_VOLT_LIMIT": 580}
        )
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert volt.native_value == 58.0

    def test_native_value_cloud_already_volts(self) -> None:
        # Cloud API returns the already-scaled value in volts (e.g. "59.5").
        coordinator = _mock_coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_VOLT_LIMIT": 59.5}
        )
        volt = SystemChargeVoltLimitNumber(coordinator, "1234567890")
        assert volt.native_value == 59.5

    def test_native_value_cloud_whole_volts(self) -> None:
        # Cloud whole-volt value (e.g. "40") must not be divided again.
        coordinator = _mock_coordinator(
            parameters={"HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT": 40}
        )
        volt = OffGridCutoffVoltageNumber(coordinator, "1234567890")
        assert volt.native_value == 40.0

    @pytest.mark.asyncio
    async def test_write_local_uses_named_parameter(self) -> None:
        coordinator = _mock_coordinator(has_local=True)
        volt = OnGridCutoffVoltageNumber(coordinator, "1234567890")
        _prep(volt)

        await volt.async_set_native_value(48.0)

        coordinator.write_named_parameter.assert_awaited_once()
        args = coordinator.write_named_parameter.call_args
        assert args[0][0] == "HOLD_ON_GRID_EOD_VOLTAGE"
        assert args[0][1] == 480  # decivolts

    @pytest.mark.asyncio
    async def test_write_cloud_uses_raw_register(self) -> None:
        coordinator = _mock_coordinator(has_local=False)
        result = MagicMock()
        result.success = True
        coordinator.client.api.control.write_parameters = AsyncMock(return_value=result)
        volt = OffGridCutoffVoltageNumber(coordinator, "1234567890")
        _prep(volt)

        await volt.async_set_native_value(42.0)

        coordinator.client.api.control.write_parameters.assert_awaited_once_with(
            "1234567890", {100: 420}
        )

    @pytest.mark.asyncio
    async def test_ac_charge_voltage_rejects_fractional(self) -> None:
        coordinator = _mock_coordinator(has_local=True)
        start = ACChargeStartVoltageNumber(coordinator, "1234567890")
        _prep(start)

        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="whole number"):
            await start.async_set_native_value(52.5)

    @pytest.mark.asyncio
    async def test_ac_charge_end_voltage_whole_volt_writes_decivolts(self) -> None:
        coordinator = _mock_coordinator(has_local=True)
        end = ACChargeEndVoltageNumber(coordinator, "1234567890")
        _prep(end)

        await end.async_set_native_value(58.0)

        args = coordinator.write_named_parameter.call_args
        assert args[0][1] == 580


# ── Battery control mode select entities ─────────────────────────────────────


class TestBatteryControlSelects:
    """The SOC/Voltage regime select entities."""

    def test_current_option_reads_param(self) -> None:
        coordinator = _mock_coordinator(parameters={"FUNC_BAT_CHARGE_CONTROL": True})
        select = EG4BatteryChargeControlSelect(
            coordinator, "1234567890", {"type": "inverter", "model": "FlexBOSS21"}
        )
        assert select.current_option == "Voltage"

    def test_current_option_unknown_when_unpolled(self) -> None:
        # Until reg 179 is polled, the regime is unknown (None), not a default.
        coordinator = _mock_coordinator(parameters={})
        select = EG4BatteryDischargeControlSelect(
            coordinator, "1234567890", {"type": "inverter", "model": "FlexBOSS21"}
        )
        assert select.current_option is None

    @pytest.mark.asyncio
    async def test_select_local_writes_named_bit(self) -> None:
        coordinator = _mock_coordinator(has_local=True)
        select = EG4BatteryChargeControlSelect(
            coordinator, "1234567890", {"type": "inverter", "model": "FlexBOSS21"}
        )
        select.hass = MagicMock()  # type: ignore[attr-defined]
        select.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]

        await select.async_select_option("Voltage")

        coordinator.write_named_parameter.assert_awaited_once_with(
            "FUNC_BAT_CHARGE_CONTROL", True, serial="1234567890"
        )
        # Parallel-group propagation: refresh ALL inverters, not just this one,
        # so sibling selects + effectiveness indicators update promptly.
        coordinator.refresh_all_device_parameters.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_select_cloud_uses_function_control(self) -> None:
        coordinator = _mock_coordinator(has_local=False)
        result = MagicMock()
        result.success = True
        coordinator.client.api.control.control_function = AsyncMock(return_value=result)
        select = EG4BatteryDischargeControlSelect(
            coordinator, "1234567890", {"type": "inverter", "model": "FlexBOSS21"}
        )
        select.hass = MagicMock()  # type: ignore[attr-defined]
        select.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]

        await select.async_select_option("SOC")

        coordinator.client.api.control.control_function.assert_awaited_once_with(
            "1234567890", "FUNC_BAT_DISCHARGE_CONTROL", False
        )
