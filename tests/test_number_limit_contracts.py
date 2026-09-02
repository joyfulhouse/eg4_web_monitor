"""Entity write bounds must match the pinned pylxpweb writers (#603).

The number entities validate a value BEFORE handing it to a pylxpweb writer,
and their advertised range is what Home Assistant shows the user. If the
entity bound and the library bound drift apart, one of two defects appears:
a value HA accepts crashes the service call with the library's raw
``ValueError`` (the beta.13 symptom on off-grid routes), or a value the
library accepts is refused by HA (#603: the entity capped at 90 while the
inverter stores 95). Both are caught here against the INSTALLED wheel — CI
installs ``tests/requirements-test.txt`` — and a separate check keeps that file
and ``manifest.json`` on the same pin so the wheel under test is the one HA
will install.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pylxpweb import LuxpowerClient
from pylxpweb.constants import (
    ONGRID_DISCHARGE_CUTOFF_SOC_MAX,
    ONGRID_DISCHARGE_CUTOFF_SOC_MIN,
)
from pylxpweb.devices.inverters.hybrid import HybridInverter
from pylxpweb.endpoints.control import ControlEndpoints
from pylxpweb.registers.inverter_holding import BY_NAME as HOLDING_BY_NAME
from pylxpweb.transports.protocol import BaseTransport

from custom_components.eg4_web_monitor.const.modbus import (
    PARAM_HOLD_ONGRID_DISCHG_SOC,
    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT,
)
from custom_components.eg4_web_monitor.const.limits import (
    GRID_PEAK_SHAVING_POWER_MAX,
    GRID_PEAK_SHAVING_POWER_MIN,
    GRID_PEAK_SHAVING_SOC_MAX,
    GRID_PEAK_SHAVING_SOC_MIN,
    GRID_PEAK_SHAVING_VOLT_MAX,
    GRID_PEAK_SHAVING_VOLT_MIN,
    GRID_PEAK_SHAVING_VOLT_READ_MAX,
    GRID_PEAK_SHAVING_VOLT_READ_MIN,
    ONGRID_SOC_CUTOFF_MAX,
    ONGRID_SOC_CUTOFF_MIN,
    SOC_LIMIT_MAX,
    SOC_LIMIT_MIN,
    SYSTEM_CHARGE_SOC_LIMIT_MAX,
    SYSTEM_CHARGE_SOC_LIMIT_MIN,
)


def test_ongrid_soc_cutoff_write_bounds_match_pinned_h105_definition() -> None:
    """#603: the entity write bounds equal the library's shared H105 constants.

    ``ONGRID_DISCHARGE_CUTOFF_SOC_MIN/MAX`` are the ONE source pylxpweb's cloud
    writer (``set_battery_soc_limits``), its Modbus writer
    (``set_on_grid_cutoff_soc``) and the canonical H105 definition all read
    (pylxpweb #322), so matching them here means neither the cloud nor the
    local path can refuse a value the entity accepts, or vice versa.
    """
    assert (ONGRID_SOC_CUTOFF_MIN, ONGRID_SOC_CUTOFF_MAX) == (
        ONGRID_DISCHARGE_CUTOFF_SOC_MIN,
        ONGRID_DISCHARGE_CUTOFF_SOC_MAX,
    )
    definition = HOLDING_BY_NAME["ongrid_discharge_cutoff_soc"]
    assert definition.address == 105
    assert (definition.min_value, definition.max_value) == (
        ONGRID_SOC_CUTOFF_MIN,
        ONGRID_SOC_CUTOFF_MAX,
    )
    assert ONGRID_SOC_CUTOFF_MAX == 100


def test_ongrid_soc_cutoff_read_window_is_not_tighter_than_any_writer() -> None:
    """The read plausibility window (0-100) must contain the write bounds:
    the portal can store anything the firmware accepts, and a stored value
    must display rather than blank to unknown (#603)."""
    assert SOC_LIMIT_MIN <= ONGRID_SOC_CUTOFF_MIN
    assert ONGRID_SOC_CUTOFF_MAX <= SOC_LIMIT_MAX


def test_offgrid_soc_cutoff_bounds_match_pinned_h125_definition() -> None:
    definition = HOLDING_BY_NAME["offgrid_discharge_cutoff_soc"]

    assert definition.address == 125
    assert (definition.min_value, definition.max_value) == (
        SOC_LIMIT_MIN,
        SOC_LIMIT_MAX,
    )


def test_system_charge_soc_limit_bounds_match_pinned_h227_definition() -> None:
    """Reg 227 is 0-101 in the pinned library (a library contract, not a
    hardware claim: the keeper's capture is 80->101->80, which does not
    exercise the 0 floor); the former entity floor of 10 would have blanked
    and refused a portal-set 0-9 (same class as #603)."""
    definition = HOLDING_BY_NAME["system_charge_soc_limit"]

    assert definition.address == 227
    assert (definition.min_value, definition.max_value) == (
        SYSTEM_CHARGE_SOC_LIMIT_MIN,
        SYSTEM_CHARGE_SOC_LIMIT_MAX,
    )


_REPO = Path(__file__).resolve().parent.parent


def test_manifest_and_test_requirements_pin_the_same_pylxpweb() -> None:
    """The wheel CI tests against must be the wheel HA installs."""
    manifest = json.loads(
        (_REPO / "custom_components/eg4_web_monitor/manifest.json").read_text()
    )
    manifest_pin = next(
        r for r in manifest["requirements"] if r.startswith("pylxpweb==")
    )
    requirements = (_REPO / "tests/requirements-test.txt").read_text()
    match = re.search(r"^pylxpweb==([^\s#]+)", requirements, re.M)
    assert match is not None
    assert manifest_pin == f"pylxpweb=={match.group(1)}"


def _hybrid_inverter() -> tuple[HybridInverter, Mock]:
    client = Mock(spec=LuxpowerClient)
    client.api = Mock()
    ok = Mock()
    ok.success = True
    client.api.control.write_parameter = AsyncMock(return_value=ok)
    inverter = HybridInverter(
        client=client, serial_number="1234567890", model="18KPV", transport=Mock()
    )
    return inverter, client


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [ONGRID_SOC_CUTOFF_MIN, ONGRID_SOC_CUTOFF_MAX])
async def test_pinned_h105_writers_accept_entity_bounds(value: int) -> None:
    """Exercise the REAL pinned cloud and Modbus writers with only their I/O
    seams mocked: both entity bounds pass their validation and reach the
    write with the exact value."""
    inverter, client = _hybrid_inverter()
    assert await inverter.set_battery_soc_limits(on_grid_limit=value)
    client.api.control.write_parameter.assert_awaited_once_with(
        "1234567890", "HOLD_DISCHG_CUT_OFF_SOC_EOD", str(value)
    )

    inverter, _ = _hybrid_inverter()
    with patch.object(
        inverter, "write_transport_register", AsyncMock(return_value=True)
    ) as write:
        assert await inverter.set_on_grid_cutoff_soc(value)
        write.assert_awaited_once_with(105, value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [ONGRID_SOC_CUTOFF_MIN - 1, ONGRID_SOC_CUTOFF_MAX + 1]
)
async def test_pinned_h105_writers_reject_one_step_outside_without_io(
    value: int,
) -> None:
    inverter, client = _hybrid_inverter()
    with pytest.raises(ValueError):
        await inverter.set_battery_soc_limits(on_grid_limit=value)
    client.api.control.write_parameter.assert_not_awaited()

    inverter, _ = _hybrid_inverter()
    with (
        patch.object(
            inverter, "write_transport_register", AsyncMock(return_value=True)
        ) as write,
        pytest.raises(ValueError),
    ):
        await inverter.set_on_grid_cutoff_soc(value)
    write.assert_not_awaited()


class _NameMapTransport(BaseTransport):
    """Minimal concrete transport: only the physical write is stubbed, so the
    name -> register resolution and serialization are the library's own."""

    def __init__(self, family: str) -> None:
        super().__init__("1234567890")
        self._inverter_family = family
        self._connected = True
        self.written: list[dict[int, int]] = []

    def _get_inverter_family(self) -> str | None:
        return self._inverter_family

    async def write_parameters(self, parameters: dict[int, int]) -> bool:
        self.written.append(dict(parameters))
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["EG4_HYBRID", "EG4_OFFGRID"])
async def test_named_local_writes_land_on_registers_105_and_227(family: str) -> None:
    """The entities' LOCAL route is coordinator.write_named_parameter ->
    transport.write_named_parameters; with only the physical write stubbed,
    the pinned library must serialize the entity's parameter names to raw
    {105: value} / {227: value} whole-percent writes."""
    transport = _NameMapTransport(family)

    assert await transport.write_named_parameters(
        {PARAM_HOLD_ONGRID_DISCHG_SOC: ONGRID_SOC_CUTOFF_MAX}
    )
    assert await transport.write_named_parameters(
        {PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT: SYSTEM_CHARGE_SOC_LIMIT_MIN}
    )

    assert transport.written == [
        {105: ONGRID_SOC_CUTOFF_MAX},
        {227: SYSTEM_CHARGE_SOC_LIMIT_MIN},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [SYSTEM_CHARGE_SOC_LIMIT_MIN, SYSTEM_CHARGE_SOC_LIMIT_MAX]
)
async def test_pinned_reg227_writers_accept_entity_bounds(value: int) -> None:
    """Both REAL pinned reg-227 writers (cloud endpoint + Modbus) accept the
    entity's floor and ceiling and reject one step outside, with only their
    I/O seams mocked — the entity's former 10 floor would have refused 0."""
    control = ControlEndpoints(Mock(spec=LuxpowerClient))
    with patch.object(
        control, "write_parameter", AsyncMock(return_value=Mock())
    ) as write:
        await control.set_system_charge_soc_limit("1234567890", value)
        write.assert_awaited_once_with(
            "1234567890", "HOLD_SYSTEM_CHARGE_SOC_LIMIT", str(value)
        )

    inverter, _ = _hybrid_inverter()
    with patch.object(
        inverter, "write_transport_register", AsyncMock(return_value=True)
    ) as write:
        assert await inverter.set_system_charge_soc_limit(value)
        write.assert_awaited_once_with(227, value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [SYSTEM_CHARGE_SOC_LIMIT_MIN - 1, SYSTEM_CHARGE_SOC_LIMIT_MAX + 1]
)
async def test_pinned_reg227_writers_reject_one_step_outside(value: int) -> None:
    control = ControlEndpoints(Mock(spec=LuxpowerClient))
    with pytest.raises(ValueError):
        await control.set_system_charge_soc_limit("1234567890", value)

    inverter, _ = _hybrid_inverter()
    with pytest.raises(ValueError):
        await inverter.set_system_charge_soc_limit(value)


# ── #592: the daily Grid Peak Shaving set ─────────────────────────────────


def test_grid_peak_shaving_power_2_bounds_match_pinned_h232_definition() -> None:
    """PS2 power (reg 232) advertises exactly the library row's 0-25.5 kW."""
    definition = HOLDING_BY_NAME["grid_peak_shaving_power_2"]
    assert definition.address == 232
    assert (definition.min_value, definition.max_value) == (
        GRID_PEAK_SHAVING_POWER_MIN,
        GRID_PEAK_SHAVING_POWER_MAX,
    )


@pytest.mark.parametrize(
    ("canonical_name", "address"),
    [("grid_peak_shaving_soc", 207), ("grid_peak_shaving_soc_2", 218)],
)
def test_grid_peak_shaving_soc_bounds_match_pinned_definitions(
    canonical_name: str, address: int
) -> None:
    definition = HOLDING_BY_NAME[canonical_name]
    assert definition.address == address
    assert (definition.min_value, definition.max_value) == (
        GRID_PEAK_SHAVING_SOC_MIN,
        GRID_PEAK_SHAVING_SOC_MAX,
    )


@pytest.mark.parametrize(
    ("canonical_name", "address"),
    [("grid_peak_shaving_volt", 208), ("grid_peak_shaving_volt_2", 219)],
)
def test_grid_peak_shaving_volt_bounds_are_a_maintainer_decision(
    canonical_name: str, address: int
) -> None:
    """The pinned VOLT rows carry NO min/max, so the 40.0-64.0 V write window
    is the maintainer's choice (the SYSTEM_CHARGE_VOLT_LIMIT shape). If the
    library ever gains bounds this test must be revisited against them."""
    definition = HOLDING_BY_NAME[canonical_name]
    assert definition.address == address
    assert definition.min_value is None
    assert definition.max_value is None
    assert (GRID_PEAK_SHAVING_VOLT_MIN, GRID_PEAK_SHAVING_VOLT_MAX) == (40.0, 64.0)


def test_grid_peak_shaving_volt_read_window_contains_write_window() -> None:
    """#603: a portal-stored voltage outside the write window must render."""
    assert GRID_PEAK_SHAVING_VOLT_READ_MIN < GRID_PEAK_SHAVING_VOLT_MIN
    assert GRID_PEAK_SHAVING_VOLT_MAX < GRID_PEAK_SHAVING_VOLT_READ_MAX
    assert (GRID_PEAK_SHAVING_VOLT_READ_MIN, GRID_PEAK_SHAVING_VOLT_READ_MAX) == (
        20.0,
        70.0,
    )
