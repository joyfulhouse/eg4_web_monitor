"""Characterization tests for voltage-register number entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    CONTROL_MODE_VOLTAGE,
    PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
    PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
    PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
    PARAM_HOLD_ONGRID_EOD_VOLTAGE,
    REG_AC_CHARGE_END_VOLTAGE,
    REG_AC_CHARGE_START_VOLTAGE,
    REG_OFFGRID_EOD_VOLTAGE,
    REG_ONGRID_EOD_VOLTAGE,
)
from custom_components.eg4_web_monitor.number import (
    EG4VoltageNumber,
    VOLTAGE_NUMBER_SPECS,
)

SERIAL = "ABC123"


def _mock_coordinator(*, parameters: dict[str, Any]) -> MagicMock:
    """Build a coordinator exposing voltage-mode configuration and readings."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": {SERIAL: {"type": "inverter", "model": "FlexBOSS21"}},
        "device_info": {SERIAL: {"deviceTypeText4APP": "FlexBOSS21"}},
        "parameters": {SERIAL: parameters},
    }
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.get_configured_control_modes = MagicMock(
        return_value=(CONTROL_MODE_VOLTAGE, CONTROL_MODE_VOLTAGE)
    )

    def _live_mode(_serial: str, *, discharge: bool = False) -> str:
        return CONTROL_MODE_VOLTAGE

    coordinator.get_live_control_mode = MagicMock(side_effect=_live_mode)
    coordinator.is_local_only = MagicMock(return_value=True)
    coordinator.has_local_transport = MagicMock(return_value=False)
    coordinator.has_http_api = MagicMock(return_value=True)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.refresh_inverter_params_if_linked = AsyncMock()
    result = MagicMock(success=True)
    coordinator.client.api.control.write_parameters = AsyncMock(return_value=result)
    coordinator.require_client = MagicMock(return_value=coordinator.client)
    return coordinator


SPECS_BY_KEY = {spec.key: spec for spec in VOLTAGE_NUMBER_SPECS}


def _voltage_number(coordinator: MagicMock, key: str) -> EG4VoltageNumber:
    """Construct a voltage entity by stable spec key."""
    return EG4VoltageNumber(coordinator, SERIAL, SPECS_BY_KEY[key])


@pytest.mark.parametrize(
    (
        "spec_key",
        "param_key",
        "param_value",
        "expected_native_value",
        "expected",
    ),
    [
        (
            "on_grid_cutoff_voltage",
            PARAM_HOLD_ONGRID_EOD_VOLTAGE,
            475,
            47.5,
            {
                "unique_id": "flexboss21_abc123_on_grid_cutoff_voltage",
                "name": "On-Grid Cut-Off Voltage",
                "min": 40.0,
                "max": 58.0,
                "step": 0.1,
                "precision": 1,
                "icon": "mdi:battery-alert",
                "control_key": "on_grid_cutoff_voltage",
            },
        ),
        (
            "off_grid_cutoff_voltage",
            PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
            480,
            48.0,
            {
                "unique_id": "flexboss21_abc123_off_grid_cutoff_voltage",
                "name": "Off-Grid Cut-Off Voltage",
                "min": 40.0,
                "max": 58.0,
                "step": 0.1,
                "precision": 1,
                "icon": "mdi:battery-outline",
                "control_key": "off_grid_cutoff_voltage",
            },
        ),
        (
            "ac_charge_start_voltage",
            PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
            520,
            52.0,
            {
                "unique_id": "flexboss21_abc123_ac_charge_start_voltage",
                "name": "AC Charge Start Voltage",
                "min": 38,
                "max": 60,
                "step": 1,
                "precision": 0,
                "icon": "mdi:battery-charging-low",
                "control_key": "ac_charge_start_voltage",
            },
        ),
        (
            "ac_charge_end_voltage",
            PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
            580,
            58.0,
            {
                "unique_id": "flexboss21_abc123_ac_charge_end_voltage",
                "name": "AC Charge End Voltage",
                "min": 38,
                "max": 60,
                "step": 1,
                "precision": 0,
                "icon": "mdi:battery-charging-high",
                "control_key": "ac_charge_end_voltage",
            },
        ),
    ],
)
def test_voltage_number_characterization(
    spec_key: str,
    param_key: str,
    param_value: float,
    expected_native_value: float,
    expected: dict[str, Any],
) -> None:
    """Snapshot identity, presentation, gating, attributes, and read behavior."""
    coordinator = _mock_coordinator(parameters={param_key: param_value})
    entity = _voltage_number(coordinator, spec_key)

    assert {
        "unique_id": entity.unique_id,
        "name": entity._attr_name,
        "min": entity._attr_native_min_value,
        "max": entity._attr_native_max_value,
        "step": entity._attr_native_step,
        "precision": entity._attr_native_precision,
        "icon": entity._attr_icon,
        "control_key": entity._control_key,
    } == expected
    assert entity.entity_registry_enabled_default is True
    assert entity.extra_state_attributes == {
        "control_regime": "voltage",
        "active_control_mode": "voltage",
        "is_effective": True,
    }
    assert entity.native_value == expected_native_value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spec_key", "value", "message"),
    [
        (
            "on_grid_cutoff_voltage",
            39.9,
            "On-grid cutoff voltage must be between 40.0-58.0 V, got 39.9",
        ),
        (
            "on_grid_cutoff_voltage",
            58.1,
            "On-grid cutoff voltage must be between 40.0-58.0 V, got 58.1",
        ),
        (
            "off_grid_cutoff_voltage",
            39.9,
            "Off-grid cutoff voltage must be between 40.0-58.0 V, got 39.9",
        ),
        (
            "off_grid_cutoff_voltage",
            58.1,
            "Off-grid cutoff voltage must be between 40.0-58.0 V, got 58.1",
        ),
        (
            "ac_charge_start_voltage",
            52.5,
            "AC charge start voltage must be a whole number of volts, got 52.5",
        ),
        (
            "ac_charge_start_voltage",
            37.0,
            "AC charge start voltage must be between 38-60 V, got 37",
        ),
        (
            "ac_charge_start_voltage",
            61.0,
            "AC charge start voltage must be between 38-60 V, got 61",
        ),
        (
            "ac_charge_end_voltage",
            52.5,
            "AC charge end voltage must be a whole number of volts, got 52.5",
        ),
        (
            "ac_charge_end_voltage",
            37.0,
            "AC charge end voltage must be between 38-60 V, got 37",
        ),
        (
            "ac_charge_end_voltage",
            61.0,
            "AC charge end voltage must be between 38-60 V, got 61",
        ),
    ],
)
async def test_voltage_number_validation_messages(
    spec_key: str,
    value: float,
    message: str,
) -> None:
    """Validation messages remain byte-for-byte compatible."""
    entity = _voltage_number(_mock_coordinator(parameters={}), spec_key)

    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_set_native_value(value)

    assert str(exc_info.value) == message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spec_key", "value", "param_key", "register", "name"),
    [
        (
            "on_grid_cutoff_voltage",
            47.5,
            PARAM_HOLD_ONGRID_EOD_VOLTAGE,
            REG_ONGRID_EOD_VOLTAGE,
            "On-Grid Cut-Off Voltage",
        ),
        (
            "off_grid_cutoff_voltage",
            48.5,
            PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
            REG_OFFGRID_EOD_VOLTAGE,
            "Off-Grid Cut-Off Voltage",
        ),
        (
            "ac_charge_start_voltage",
            52.0,
            PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
            REG_AC_CHARGE_START_VOLTAGE,
            "AC Charge Start Voltage",
        ),
        (
            "ac_charge_end_voltage",
            58.0,
            PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
            REG_AC_CHARGE_END_VOLTAGE,
            "AC Charge End Voltage",
        ),
    ],
)
async def test_voltage_number_write_dispatch(
    spec_key: str,
    value: float,
    param_key: str,
    register: int,
    name: str,
) -> None:
    """Writes preserve value normalization, register, parameter, and display label."""
    entity = _voltage_number(_mock_coordinator(parameters={}), spec_key)
    entity._write_voltage_register = AsyncMock()

    await entity.async_set_native_value(value)

    entity._write_voltage_register.assert_awaited_once_with(
        value=value,
        param_name=param_key,
        register=register,
        label=name,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_key", "expected_updated"),
    [
        (
            "on_grid_cutoff_voltage",
            {"on_grid_cutoff_voltage", "off_grid_cutoff_voltage"},
        ),
        (
            "ac_charge_start_voltage",
            {"ac_charge_start_voltage", "ac_charge_end_voltage"},
        ),
    ],
)
async def test_voltage_number_refresh_fanout_is_pair_scoped(
    source_key: str, expected_updated: set[str]
) -> None:
    """A write refreshes its voltage pair without crossing pair boundaries."""
    coordinator = _mock_coordinator(parameters={})
    coordinator.is_local_only.return_value = False
    entities = {
        spec.key: EG4VoltageNumber(coordinator, SERIAL, spec)
        for spec in VOLTAGE_NUMBER_SPECS
    }
    platform = MagicMock()
    platform.entities = {key: entity for key, entity in entities.items()}
    for entity in entities.values():
        entity.hass = MagicMock()
        entity.entity_id = f"number.{entity._spec.key}"
        entity.platform = platform
        entity.async_write_ha_state = MagicMock()
        entity.async_update = AsyncMock()

    value = 48.0 if source_key == "on_grid_cutoff_voltage" else 52.0
    await entities[source_key].async_set_native_value(value)

    for key, entity in entities.items():
        if key in expected_updated:
            entity.async_update.assert_awaited_once()
        else:
            entity.async_update.assert_not_awaited()
