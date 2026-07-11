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
    PARAM_HOLD_START_PV_VOLT,
    REG_AC_CHARGE_END_VOLTAGE,
    REG_AC_CHARGE_START_VOLTAGE,
    REG_OFFGRID_EOD_VOLTAGE,
    REG_ONGRID_EOD_VOLTAGE,
    REG_START_PV_VOLT,
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
    coordinator.client.api.control.write_parameter = AsyncMock(return_value=result)
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


def test_pv_start_voltage_characterization() -> None:
    """PV Start Voltage keeps the folded class's identity and presentation.

    No control_key: always enabled, no regime attributes (it is a PV
    control, not a battery charge/discharge limit).
    """
    coordinator = _mock_coordinator(parameters={PARAM_HOLD_START_PV_VOLT: 1400})
    entity = _voltage_number(coordinator, "pv_start_voltage")

    assert entity.unique_id == "flexboss21_abc123_pv_start_voltage"
    assert entity._attr_name == "PV Start Voltage"
    assert entity._attr_native_min_value == 140
    assert entity._attr_native_max_value == 500
    assert entity._attr_native_step == 1
    assert entity._attr_native_precision == 0
    assert entity._attr_icon == "mdi:solar-power-variant"
    assert entity._control_key is None
    assert entity.entity_registry_enabled_default is True
    assert entity.extra_state_attributes is None
    # LOCAL: raw decivolts (1400) normalize to volts, and the state stays an
    # int ("140" not "140.0") like the retired class (read_as_float=False).
    assert entity.native_value == 140
    assert isinstance(entity.native_value, int)


def test_pv_start_voltage_cloud_read_not_divided_again() -> None:
    """CLOUD: already-scaled 140 V must NOT be divided to 14 (the pure-CLOUD
    unknown-value bug this spec entry fixes — the battery decivolt threshold
    of 100 mis-split PV start's 140-500 V legit range)."""
    coordinator = _mock_coordinator(parameters={PARAM_HOLD_START_PV_VOLT: 140.0})
    coordinator.is_local_only.return_value = False
    entity = _voltage_number(coordinator, "pv_start_voltage")

    assert entity.native_value == 140
    assert isinstance(entity.native_value, int)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (900, 90.0),  # min raw decivolts (90 V)
        (1400, 140.0),  # typical raw decivolts
        (5000, 500.0),  # max raw decivolts
        (90, 90.0),  # min already-volts
        (500, 500.0),  # max already-volts stays undivided
    ],
)
def test_pv_start_voltage_threshold_split(raw: float, expected: float) -> None:
    """Values >= 600 are decivolts; smaller values are already volts."""
    coordinator = _mock_coordinator(parameters={})
    entity = _voltage_number(coordinator, "pv_start_voltage")
    assert entity._volts_from_spec_param(raw) == expected


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
        (
            "pv_start_voltage",
            140.5,
            "PV start voltage must be a whole number of volts, got 140.5",
        ),
        (
            "pv_start_voltage",
            139.0,
            "PV start voltage must be between 140-500 V, got 139",
        ),
        (
            "pv_start_voltage",
            501.0,
            "PV start voltage must be between 140-500 V, got 501",
        ),
    ],
)
async def test_voltage_number_validation_messages(
    spec_key: str,
    value: float,
    message: str,
) -> None:
    """Pin validation messages.

    The four battery specs remain byte-for-byte compatible with their
    retired classes. pv_start_voltage intentionally adopts the shared
    whole-volt wording/order ("whole number of volts" checked before range)
    instead of the retired class's "integer value" message — standardizing
    with the other spec-driven entities.
    """
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
        cloud_write=None,
    )


@pytest.mark.asyncio
async def test_pv_start_voltage_write_dispatch_uses_named_cloud_route() -> None:
    """PV start dispatches with a named-volts cloud override (raw register 22
    cloud writes are unproven; portal valueText semantics are the verified
    route)."""
    coordinator = _mock_coordinator(parameters={})
    entity = _voltage_number(coordinator, "pv_start_voltage")
    entity._write_voltage_register = AsyncMock()

    await entity.async_set_native_value(140.0)

    kwargs = entity._write_voltage_register.await_args.kwargs
    assert kwargs["value"] == 140.0
    assert kwargs["param_name"] == PARAM_HOLD_START_PV_VOLT
    assert kwargs["register"] == REG_START_PV_VOLT
    assert kwargs["label"] == "PV Start Voltage"
    assert kwargs["cloud_write"] is not None

    # Exercise the override: named write in human-readable volts.
    write_parameter = AsyncMock(return_value=MagicMock(success=True))
    coordinator.client.api.control.write_parameter = write_parameter
    await kwargs["cloud_write"]()
    write_parameter.assert_awaited_once_with(SERIAL, PARAM_HOLD_START_PV_VOLT, "140")
    coordinator.refresh_inverter_params_if_linked.assert_awaited_once_with(SERIAL)


@pytest.mark.asyncio
async def test_pv_start_voltage_cloud_write_end_to_end_uses_named_route() -> None:
    """Pure-CLOUD end-to-end (no _write_voltage_register mock): the write
    lands on the named volts route and NEVER touches raw register 22
    (unproven on the cloud API)."""
    coordinator = _mock_coordinator(parameters={})
    coordinator.is_local_only.return_value = False
    coordinator.has_local_transport.return_value = False
    entity = _voltage_number(coordinator, "pv_start_voltage")
    entity.hass = MagicMock()
    entity.entity_id = "number.pv_start_voltage"
    platform = MagicMock()
    platform.entities = {}
    entity.platform = platform
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(140.0)

    coordinator.client.api.control.write_parameter.assert_awaited_once_with(
        SERIAL, PARAM_HOLD_START_PV_VOLT, "140"
    )
    coordinator.client.api.control.write_parameters.assert_not_awaited()
    coordinator.write_named_parameter.assert_not_called()


@pytest.mark.asyncio
async def test_pv_start_voltage_named_cloud_write_failure_raises() -> None:
    """A rejected named cloud write raises with the folded class's message."""
    coordinator = _mock_coordinator(parameters={})
    entity = _voltage_number(coordinator, "pv_start_voltage")
    entity._write_voltage_register = AsyncMock()
    await entity.async_set_native_value(150.0)
    cloud_write = entity._write_voltage_register.await_args.kwargs["cloud_write"]

    coordinator.client.api.control.write_parameter = AsyncMock(
        return_value=MagicMock(success=False)
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await cloud_write()
    assert str(exc_info.value) == "Failed to set PV start voltage to 150 V"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_key", "expected_updated"),
    [
        (
            "on_grid_cutoff_voltage",
            {"on_grid_cutoff_voltage", "off_grid_cutoff_voltage"},
        ),
        (
            "off_grid_cutoff_voltage",
            {"on_grid_cutoff_voltage", "off_grid_cutoff_voltage"},
        ),
        (
            "ac_charge_start_voltage",
            {"ac_charge_start_voltage", "ac_charge_end_voltage"},
        ),
        (
            "ac_charge_end_voltage",
            {"ac_charge_start_voltage", "ac_charge_end_voltage"},
        ),
        (
            "pv_start_voltage",
            {"pv_start_voltage"},
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

    if source_key in ("on_grid_cutoff_voltage", "off_grid_cutoff_voltage"):
        value = 48.0
    elif source_key == "pv_start_voltage":
        value = 140.0
    else:
        value = 52.0
    await entities[source_key].async_set_native_value(value)

    for key, entity in entities.items():
        if key in expected_updated:
            entity.async_update.assert_awaited_once()
        else:
            entity.async_update.assert_not_awaited()
