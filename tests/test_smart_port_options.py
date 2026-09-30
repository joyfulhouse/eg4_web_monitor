"""Tests for the GridBOSS smart port option entities (smart_port_options.py)."""

from datetime import time

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import homeassistant.helpers.entity_registry as er
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.const.midbox import (
    GATE_SHEDDING,
    GATE_SOC,
    GATE_TIME_BASED,
    GATE_VOLT,
    PORT_OPTION_SPECS,
    PortOptionSpec,
    decode_midbox_options,
    option_matches_control_modes,
    port_option_specs,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    SMART_PORT_VALIDATED_KEY,
)
from custom_components.eg4_web_monitor.smart_port_devices import PortSensorEnablement
from custom_components.eg4_web_monitor.smart_port_options import (
    BASED_ON_SOC_VOLT,
    BASED_ON_TIME,
    EG4SmartPortBasedOnSelect,
    EG4SmartPortOptionNumber,
    EG4SmartPortOptionSwitch,
    EG4SmartPortWindowTime,
    battery_regime_is_voltage,
    create_port_option_entities,
)

GB = "9876543210"
INV = "1234567890"
INTEGRATION = er.RegistryEntryDisabler.INTEGRATION

# Live read (dump 10): ports 1-3 Smart Load, enabled, grid-on, SOC/Volt;
# shedding on ports 1-2; port 4 unused.
LIVE_PARAMS = decode_midbox_options(
    {
        229: 0x3077,
        2101: 0x3E,
        230: 0x4650,
        232: 0x325A,
        234: 0x21C,
        235: 0x1E0,
        245: 0x540A,
        254: 0,
        256: 3,
        258: 0x2850,
        260: 0x3C5A,
        270: 0,
        271: 0,
    }
)
SPECS = {spec.id_suffix: spec for spec in PORT_OPTION_SPECS}


def _coordinator(
    *,
    modes: tuple[str, ...] = ("smart_load", "smart_load", "smart_load", "unused"),
    params: dict[str, Any] | None = None,
    local: bool = True,
    link_down: bool = False,
    inverter_regimes: tuple[bool, ...] = (),
) -> MagicMock:
    """Coordinator double with one GridBOSS (and optional inverters)."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.has_configured_local_transport = MagicMock(return_value=local)
    coordinator.is_transport_link_down = MagicMock(return_value=link_down)
    coordinator.write_midbox_options = AsyncMock()
    coordinator.get_smart_port_device_info = MagicMock(
        side_effect=lambda serial, port: {"identifiers": {(DOMAIN, f"{serial}_{port}")}}
    )
    sensors = {f"smart_port{port}_status": mode for port, mode in enumerate(modes, 1)}
    devices: dict[str, Any] = {
        GB: {"type": "gridboss", "model": "GridBOSS", "sensors": sensors}
    }
    parameters: dict[str, Any] = {GB: dict(LIVE_PARAMS if params is None else params)}
    for index, voltage in enumerate(inverter_regimes):
        serial = f"{INV[:-1]}{index}"
        devices[serial] = {"type": "inverter", "model": "FlexBOSS21"}
        parameters[serial] = {
            "FUNC_BAT_DISCHARGE_CONTROL": voltage,
            "FUNC_BAT_CHARGE_CONTROL": voltage,
        }
    coordinator.data = {"devices": devices, "parameters": parameters}
    return coordinator


def _switch(coordinator: MagicMock, port: int, id_suffix: str):
    entity = EG4SmartPortOptionSwitch(coordinator, GB, port, SPECS[id_suffix])
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return entity


def _select(coordinator: MagicMock, port: int):
    entity = EG4SmartPortBasedOnSelect(coordinator, GB, port, SPECS["based_on"])
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return entity


# ── Specs ────────────────────────────────────────────────────────────


def test_spec_counts_and_unique_suffixes():
    """19 Smart Load + 11 AC Couple entities per port, suffixes unique."""
    modes = [spec.mode for spec in PORT_OPTION_SPECS]
    assert modes.count("smart_load") == 19
    assert modes.count("ac_couple") == 11
    assert len(SPECS) == len(PORT_OPTION_SPECS)


def test_portal_gating_table():
    """Gates mirror the portal's greying."""
    assert SPECS["smart_load_start_soc"].gates == (GATE_SOC,)
    assert SPECS["smart_load_end_voltage"].gates == (GATE_VOLT,)
    assert SPECS["shedding_start_pv_power"].gates == (GATE_SHEDDING,)
    assert SPECS["shedding_end_soc"].gates == (GATE_SHEDDING, GATE_SOC)
    assert SPECS["smart_load_start_time_2"].gates == (GATE_TIME_BASED,)
    assert SPECS["ac_couple_start_time_1"].gates == ()
    assert SPECS["ac_couple_start_soc"].gates == (GATE_SOC,)
    for suffix in ("smart_load_enable", "grid_always_on", "power_shedding", "based_on"):
        assert SPECS[suffix].gates == ()


# ── Factory ──────────────────────────────────────────────────────────


def test_factory_builds_per_port_entities():
    """Four ports of switches and selects, keyed on the port device."""
    coordinator = _coordinator()
    switches = create_port_option_entities(coordinator, "switch")
    selects = create_port_option_entities(coordinator, "select")
    assert len(switches) == 4 * len(port_option_specs("switch")) == 16
    assert len(selects) == 4
    unique_ids = {entity.unique_id for entity in switches + selects}
    assert f"{GB}_smart_port1_smart_load_enable" in unique_ids
    assert f"{GB}_smart_port4_ac_couple_enable" in unique_ids
    assert f"{GB}_smart_port2_based_on" in unique_ids
    entity = switches[0]
    assert entity.name == "Smart Load Enable"
    assert entity.device_info == {"identifiers": {(DOMAIN, f"{GB}_1")}}


def test_factory_requires_local_transport_and_gridboss():
    """No local transport, or no GridBOSS: no option entities."""
    assert create_port_option_entities(_coordinator(local=False), "switch") == []
    coordinator = _coordinator()
    coordinator.data["devices"][GB]["type"] = "inverter"
    assert create_port_option_entities(coordinator, "switch") == []
    assert create_port_option_entities(_coordinator(), "button") == []


# ── Availability ─────────────────────────────────────────────────────


def test_available_only_in_own_mode():
    """Smart Load controls on Smart Load ports, AC Couple on AC Couple ports."""
    coordinator = _coordinator(modes=("smart_load", "ac_couple", "unused"))
    assert _switch(coordinator, 1, "smart_load_enable").available is True
    assert _switch(coordinator, 1, "ac_couple_enable").available is False
    assert _switch(coordinator, 2, "smart_load_enable").available is False
    assert _switch(coordinator, 2, "ac_couple_enable").available is True
    assert _switch(coordinator, 3, "smart_load_enable").available is False
    assert _switch(coordinator, 4, "smart_load_enable").available is False  # unknown


def test_unavailable_when_never_read_link_down_or_update_failed():
    """No fake OFF: missing values, a down link or a failed update."""
    assert _switch(_coordinator(params={}), 1, "smart_load_enable").available is False
    assert _select(_coordinator(params={}), 1).current_option is None
    assert (
        _switch(_coordinator(link_down=True), 1, "smart_load_enable").available is False
    )
    coordinator = _coordinator()
    coordinator.last_update_success = False
    assert _switch(coordinator, 1, "smart_load_enable").available is False


def _gated(coordinator: MagicMock, port: int, *gates: str) -> bool:
    spec = PortOptionSpec(
        "switch", "probe", "Probe", "smart_load", "FUNC_SMART_LOAD_EN_{port}", gates
    )
    return EG4SmartPortOptionSwitch(coordinator, GB, port, spec).available


def test_time_based_gate_follows_based_on():
    """SL windows are greyed while "based on" is SOC/Volt."""
    assert _gated(_coordinator(), 1, GATE_TIME_BASED) is False  # SOC/Volt
    time_based = decode_midbox_options({229: 0x3077, 2101: 0x30})
    assert _gated(_coordinator(params=time_based), 1, GATE_TIME_BASED) is True


def test_shedding_gate_follows_shedding_switch():
    """Shedding fields are greyed while power shedding is off (port 3)."""
    coordinator = _coordinator()
    assert _gated(coordinator, 1, GATE_SHEDDING) is True
    assert _gated(coordinator, 3, GATE_SHEDDING) is False


def test_regime_gate_follows_inverters():
    """SOC fields need an SOC regime, voltage fields a voltage regime."""
    soc = _coordinator(inverter_regimes=(False,))
    assert _gated(soc, 1, GATE_SOC) is True
    assert _gated(soc, 1, GATE_VOLT) is False
    volt = _coordinator(inverter_regimes=(True, True))
    assert _gated(volt, 1, GATE_SOC) is False
    assert _gated(volt, 1, GATE_VOLT) is True
    # Unknown or disagreeing inverters: nothing is gated.
    for coordinator in (_coordinator(), _coordinator(inverter_regimes=(True, False))):
        assert _gated(coordinator, 1, GATE_SOC) is True
        assert _gated(coordinator, 1, GATE_VOLT) is True


def test_battery_regime_reads_charge_and_discharge_bits():
    """Discharge bit for Smart Load, charge bit for AC Couple."""
    coordinator = _coordinator(inverter_regimes=(False,))
    params = next(
        value
        for serial, value in coordinator.data["parameters"].items()
        if serial != GB
    )
    params["FUNC_BAT_CHARGE_CONTROL"] = True
    assert battery_regime_is_voltage(coordinator, discharge=True) is False
    assert battery_regime_is_voltage(coordinator, discharge=False) is True


# ── State and writes ─────────────────────────────────────────────────


def test_states_decode_from_parameters():
    """Switch and select states come from the parameter store."""
    coordinator = _coordinator()
    assert _switch(coordinator, 1, "power_shedding").is_on is True
    assert _switch(coordinator, 3, "power_shedding").is_on is False
    assert _select(coordinator, 1).current_option == BASED_ON_SOC_VOLT
    time_based = decode_midbox_options({229: 0x3077, 2101: 0x30})
    assert _select(_coordinator(params=time_based), 1).current_option == BASED_ON_TIME


async def test_switch_writes_its_field():
    """Turning a switch on/off writes only its own option."""
    coordinator = _coordinator()
    entity = _switch(coordinator, 3, "power_shedding")
    await entity.async_turn_on()
    coordinator.write_midbox_options.assert_awaited_once_with(
        GB, {"FUNC_SHEDDING_MODE_EN_3": True}
    )
    await entity.async_turn_off()
    coordinator.write_midbox_options.assert_awaited_with(
        GB, {"FUNC_SHEDDING_MODE_EN_3": False}
    )
    assert entity._optimistic_state is None


async def test_failed_write_clears_optimistic_state():
    """A rejected write raises and publishes the stored state again."""
    coordinator = _coordinator()
    coordinator.write_midbox_options = AsyncMock(side_effect=HomeAssistantError("no"))
    entity = _switch(coordinator, 2, "grid_always_on")
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_off()
    assert entity._optimistic_state is None
    assert entity.is_on is True


async def test_select_writes_based_on_bit():
    """SOC/Volt writes 1 and Time writes 0 to the port's based-on bit."""
    coordinator = _coordinator()
    entity = _select(coordinator, 2)
    await entity.async_select_option(BASED_ON_TIME)
    coordinator.write_midbox_options.assert_awaited_once_with(
        GB, {"BIT_SMART_LOAD_BASE_ON_2": 0}
    )
    await entity.async_select_option(BASED_ON_SOC_VOLT)
    coordinator.write_midbox_options.assert_awaited_with(
        GB, {"BIT_SMART_LOAD_BASE_ON_2": 1}
    )
    assert entity.options == [BASED_ON_TIME, BASED_ON_SOC_VOLT]


# ── Registry sync ────────────────────────────────────────────────────


async def test_registry_sync_covers_option_entities(hass: HomeAssistant):
    """Option entities are disabled outside their mode and re-enabled in it."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    sl_switch = registry.async_get_or_create(
        "switch", DOMAIN, f"{GB}_smart_port1_smart_load_enable", config_entry=entry
    )
    ac_switch = registry.async_get_or_create(
        "switch", DOMAIN, f"{GB}_smart_port1_ac_couple_enable", config_entry=entry
    )
    ac_time = registry.async_get_or_create(
        "time", DOMAIN, f"{GB}_smart_port1_ac_couple_start_time_1", config_entry=entry
    )
    sync = PortSensorEnablement(hass, entry)

    def run(mode: str) -> None:
        sensors = {"smart_port1_status": mode, SMART_PORT_VALIDATED_KEY: True}
        for _ in range(2):
            sync.async_sync({"devices": {GB: {"type": "gridboss", "sensors": sensors}}})

    run("smart_load")
    assert registry.async_get(sl_switch.entity_id).disabled_by is None
    assert registry.async_get(ac_switch.entity_id).disabled_by is INTEGRATION
    assert registry.async_get(ac_time.entity_id).disabled_by is INTEGRATION
    run("ac_couple")
    assert registry.async_get(sl_switch.entity_id).disabled_by is INTEGRATION
    assert registry.async_get(ac_switch.entity_id).disabled_by is None
    assert registry.async_get(ac_time.entity_id).disabled_by is None


# ── Numbers ──────────────────────────────────────────────────────────


def _number(coordinator: MagicMock, port: int, id_suffix: str):
    entity = EG4SmartPortOptionNumber(coordinator, GB, port, SPECS[id_suffix])
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return entity


def test_factory_builds_numbers():
    """13 thresholds per port."""
    numbers = create_port_option_entities(_coordinator(), "number")
    assert len(numbers) == 4 * 13
    assert all(isinstance(entity, EG4SmartPortOptionNumber) for entity in numbers)


@pytest.mark.parametrize(
    ("id_suffix", "unit", "step", "value"),
    [
        ("smart_load_start_soc", "%", 1, 80.0),
        ("smart_load_end_soc", "%", 1, 70.0),
        ("smart_load_start_voltage", "V", 0.1, 54.0),
        ("smart_load_end_voltage", "V", 0.1, 48.0),
        ("shedding_start_pv_power", "kW", 0.1, 0.0),
        ("shedding_start_soc", "%", 1, 80.0),
        ("shedding_end_soc", "%", 1, 40.0),
    ],
)
def test_number_format_and_value(id_suffix, unit, step, value):
    """Units, step and decoded values for port 1 of the live read."""
    entity = _number(_coordinator(), 1, id_suffix)
    assert entity.native_unit_of_measurement == unit
    assert entity.native_step == step
    assert entity.native_min_value == 0
    assert entity.native_value == value


def test_number_values_for_other_ports():
    """Port 3 PV power 0.3 kW; port 4 AC start SOC in the low byte."""
    coordinator = _coordinator(modes=("smart_load",) * 3 + ("ac_couple",))
    assert _number(coordinator, 3, "shedding_start_pv_power").native_value == 0.3
    assert _number(coordinator, 3, "smart_load_end_soc").native_value == 50.0
    assert _number(coordinator, 4, "ac_couple_start_soc").native_value == 10.0
    assert _number(coordinator, 4, "ac_couple_start_soc").available is True


def test_number_gating():
    """Shedding thresholds need shedding on; voltage needs a voltage regime."""
    coordinator = _coordinator(inverter_regimes=(False,))
    assert _number(coordinator, 1, "shedding_start_soc").available is True
    assert _number(coordinator, 3, "shedding_start_soc").available is False
    assert _number(coordinator, 1, "smart_load_start_voltage").available is False
    assert _number(coordinator, 1, "smart_load_start_soc").available is True


async def test_number_writes():
    """SOC writes an int, voltage and power round to 0.1."""
    coordinator = _coordinator()
    await _number(coordinator, 3, "smart_load_end_soc").async_set_native_value(60.0)
    coordinator.write_midbox_options.assert_awaited_with(
        GB, {"MIDBOX_HOLD_SL_END_SOC_3": 60}
    )
    await _number(coordinator, 1, "smart_load_start_voltage").async_set_native_value(
        52.46
    )
    coordinator.write_midbox_options.assert_awaited_with(
        GB, {"MIDBOX_HOLD_SL_START_VOLT_1": 52.5}
    )
    entity = _number(coordinator, 1, "shedding_start_pv_power")
    await entity.async_set_native_value(0.4)
    coordinator.write_midbox_options.assert_awaited_with(
        GB, {"MIDBOX_HOLD_SL_START_PV_P_1": 0.4}
    )
    assert entity._optimistic_value is None


async def test_number_rejects_fractional_soc():
    """A fractional SOC is a validation error, not a silent truncation."""
    coordinator = _coordinator()
    with pytest.raises(ServiceValidationError):
        await _number(coordinator, 1, "smart_load_start_soc").async_set_native_value(
            80.5
        )
    coordinator.write_midbox_options.assert_not_awaited()


# ── Time windows ─────────────────────────────────────────────────────

# Time-based Smart Load port 3 with windows 04:05-05:04, 07:06-06:07,
# 08:09-09:08 (the pinning test, registers 282-287), and AC Couple port 4
# window 1 end 01:02 (register 313).
WINDOW_PARAMS = decode_midbox_options(
    {
        229: 0x0875,
        2101: 0x30,
        282: 0x0504,
        283: 0x0405,
        284: 0x0607,
        285: 0x0706,
        286: 0x0908,
        287: 0x0809,
        312: 0,
        313: 0x0201,
        288: 0x3B18,  # hour 24: not a clock time
        289: 0,
    }
)


def _time(coordinator: MagicMock, port: int, id_suffix: str):
    entity = EG4SmartPortWindowTime(coordinator, GB, port, SPECS[id_suffix])
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return entity


def _window_coordinator() -> MagicMock:
    return _coordinator(
        modes=("smart_load", "smart_load", "smart_load", "ac_couple"),
        params=WINDOW_PARAMS,
    )


def test_factory_builds_windows():
    """6 Smart Load + 6 AC Couple window edges per port."""
    times = create_port_option_entities(_coordinator(), "time")
    assert len(times) == 4 * 12
    unique_ids = {entity.unique_id for entity in times}
    assert f"{GB}_smart_port3_smart_load_start_time_1" in unique_ids
    assert f"{GB}_smart_port4_ac_couple_end_time_3" in unique_ids


@pytest.mark.parametrize(
    ("port", "id_suffix", "expected"),
    [
        (3, "smart_load_start_time_1", time(4, 5)),
        (3, "smart_load_end_time_1", time(5, 4)),
        (3, "smart_load_start_time_2", time(7, 6)),
        (3, "smart_load_end_time_3", time(9, 8)),
        (4, "ac_couple_start_time_1", time(0, 0)),
        (4, "ac_couple_end_time_1", time(1, 2)),
    ],
)
def test_window_values(port, id_suffix, expected):
    """Low byte hour, high byte minute."""
    assert _time(_window_coordinator(), port, id_suffix).native_value == expected


def test_window_rejects_non_clock_values():
    """An hour above 23 reads as unknown, not a wrapped time."""
    assert (
        _time(_window_coordinator(), 4, "smart_load_start_time_1").native_value is None
    )


def test_window_gating():
    """SL windows need "based on" = Time; AC windows are always available."""
    time_based = _window_coordinator()
    assert _time(time_based, 3, "smart_load_start_time_1").available is True
    assert _time(time_based, 4, "ac_couple_end_time_1").available is True
    soc_volt = decode_midbox_options({**{282: 0x0504, 283: 0}, 229: 0x3077, 2101: 0x3E})
    assert (
        _time(_coordinator(params=soc_volt), 3, "smart_load_start_time_1").available
        is False
    )


def test_window_unavailable_until_both_bytes_read():
    """A window whose register was never read is unavailable."""
    params = {"BIT_SMART_LOAD_BASE_ON_3": 0, "HOLD_MIDBOX_SL_3_START_HOUR_1": 4}
    entity = _time(_coordinator(params=params), 3, "smart_load_start_time_1")
    assert entity.available is False


async def test_window_writes_hour_and_minute_together():
    """One write carries both bytes of the window register."""
    coordinator = _window_coordinator()
    entity = _time(coordinator, 3, "smart_load_end_time_2")
    await entity.async_set_value(time(22, 30, 15))
    coordinator.write_midbox_options.assert_awaited_once_with(
        GB,
        {"HOLD_MIDBOX_SL_3_END_HOUR_2": 22, "HOLD_MIDBOX_SL_3_END_MINUTE_2": 30},
    )
    assert entity._optimistic_value is None


# ── Configured battery control mode ──────────────────────────────────


@pytest.mark.parametrize(
    ("id_suffix", "charge", "discharge", "expected"),
    [
        ("smart_load_start_soc", "soc", "soc", True),
        ("smart_load_start_voltage", "soc", "soc", False),
        ("smart_load_start_voltage", "soc", "voltage", True),
        ("shedding_end_soc", "voltage", "voltage", False),
        # AC Couple follows the charge side.
        ("ac_couple_start_soc", "soc", "voltage", True),
        ("ac_couple_start_voltage", "soc", "voltage", False),
        ("ac_couple_start_voltage", "voltage", "soc", True),
        # Not SOC / voltage: always.
        ("shedding_start_pv_power", "voltage", "voltage", True),
        ("smart_load_enable", "voltage", "voltage", True),
    ],
)
def test_option_matches_control_modes(id_suffix, charge, discharge, expected):
    """SOC / voltage thresholds follow the configured control mode per side."""
    assert option_matches_control_modes(SPECS[id_suffix], charge, discharge) is expected


async def test_registry_sync_follows_configured_control_mode(hass: HomeAssistant):
    """Voltage thresholds are disabled under SOC control, SOC under voltage."""
    registry = er.async_get(hass)

    def run(entry: MockConfigEntry) -> None:
        sync = PortSensorEnablement(hass, entry)
        sensors = {"smart_port1_status": "smart_load", SMART_PORT_VALIDATED_KEY: True}
        for _ in range(2):
            sync.async_sync({"devices": {GB: {"type": "gridboss", "sensors": sensors}}})

    entry = MockConfigEntry(domain=DOMAIN, options={})  # defaults: SOC / SOC
    entry.add_to_hass(hass)
    soc = registry.async_get_or_create(
        "number", DOMAIN, f"{GB}_smart_port1_smart_load_start_soc", config_entry=entry
    )
    volt = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{GB}_smart_port1_smart_load_start_voltage",
        config_entry=entry,
    )
    pv = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{GB}_smart_port1_shedding_start_pv_power",
        config_entry=entry,
    )
    run(entry)
    assert registry.async_get(soc.entity_id).disabled_by is None
    assert registry.async_get(volt.entity_id).disabled_by is INTEGRATION
    assert registry.async_get(pv.entity_id).disabled_by is None

    hass.config_entries.async_update_entry(
        entry,
        options={"charge_control_mode": "soc", "discharge_control_mode": "voltage"},
    )
    run(entry)
    assert registry.async_get(soc.entity_id).disabled_by is INTEGRATION
    assert registry.async_get(volt.entity_id).disabled_by is None


def test_no_write_while_registry_disabled():
    """A coordinator update doesn't write an entity the sync just disabled."""
    coordinator = _coordinator()
    entity = _switch(coordinator, 1, "ac_couple_enable")
    entity.registry_entry = MagicMock(disabled_by=INTEGRATION)
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()

    entity.registry_entry = MagicMock(disabled_by=None)
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_called_once()
