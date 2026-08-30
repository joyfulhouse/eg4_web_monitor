"""Characterization tests for SOC integer validation messages."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet
from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.number import (
    ACChargeEndBatterySOCNumber,
    ACChargeSOCLimitNumber,
    ACChargeStartBatterySOCNumber,
    EG4BaseNumberEntity,
    ForcedDischargeSOCLimitNumber,
    OffGridSOCCutoffNumber,
    OnGridSOCCutoffNumber,
)
from tests.test_number_entities import _mock_coordinator, _prep


ENTITY_CASES: "Sequence[ParameterSet]" = (
    pytest.param(
        ACChargeSOCLimitNumber,
        0,
        101,
        "AC charge SOC limit",
        id="ac-charge-soc-limit",
    ),
    pytest.param(
        ACChargeStartBatterySOCNumber,
        # Floor 1 on this family-less (unresolved → fail-closed) scaffold:
        # the CEAA/CCAA firmware writer rejects H160=0 (#570 review round 4).
        1,
        # Write cap is 90 (pylxpweb's reg-160 definition, PR #488 item 3).
        90,
        "AC charge start battery SOC",
        id="ac-charge-start-battery-soc",
    ),
    pytest.param(
        ACChargeEndBatterySOCNumber,
        # Floor 20 on this family-less (unresolved → fail-closed) scaffold:
        # the CEAA/CCAA firmware writer enforces 20..100 (#570 round 6).
        20,
        100,
        "AC charge end battery SOC",
        id="ac-charge-end-battery-soc",
    ),
    pytest.param(
        ForcedDischargeSOCLimitNumber,
        0,
        100,
        "Forced discharge SOC limit",
        id="forced-discharge-soc-limit",
    ),
    pytest.param(
        # 10-90: the canonical H105 range enforced by pylxpweb's definition
        # and set_battery_soc_limits (#570 review round 2).
        OnGridSOCCutoffNumber,
        10,
        90,
        "On-grid SOC cutoff",
        id="on-grid-soc-cutoff",
    ),
    pytest.param(
        OffGridSOCCutoffNumber,
        0,
        100,
        "Off-grid SOC cutoff",
        id="off-grid-soc-cutoff",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity_type", "min_v", "max_v", "label"), ENTITY_CASES)
@pytest.mark.parametrize("bound", ("min", "max"))
async def test_out_of_range_message_is_exact(
    entity_type: type[EG4BaseNumberEntity],
    min_v: int,
    max_v: int,
    label: str,
    bound: str,
) -> None:
    """Out-of-range values preserve the exact validation message."""
    value = min_v - 1 if bound == "min" else max_v + 1
    coordinator = _mock_coordinator(has_local=True)
    entity = entity_type(coordinator, "1234567890")
    _prep(entity)

    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_set_native_value(value)

    assert str(exc_info.value) == (
        f"{label} must be between {min_v}-{max_v}%, got {value}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity_type", "min_v", "max_v", "label"), ENTITY_CASES)
@pytest.mark.parametrize("side", ("low", "high"))
async def test_non_integer_message_is_exact(
    entity_type: type[EG4BaseNumberEntity],
    min_v: int,
    max_v: int,
    label: str,
    side: str,
) -> None:
    """In-range fractional values preserve the exact validation message."""
    value = min_v + 0.5 if side == "low" else max_v - 0.5
    coordinator = _mock_coordinator(has_local=True)
    entity = entity_type(coordinator, "1234567890")
    _prep(entity)

    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_set_native_value(value)

    assert str(exc_info.value) == f"{label} must be an integer value, got {value}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity_type", "min_v", "max_v", "label"), ENTITY_CASES)
@pytest.mark.parametrize("bound", ("min", "max"))
async def test_in_range_integer_succeeds(
    entity_type: type[EG4BaseNumberEntity],
    min_v: int,
    max_v: int,
    label: str,
    bound: str,
) -> None:
    """Exact boundary integers reach the mocked write successfully."""
    value = float(min_v) if bound == "min" else float(max_v)
    coordinator = _mock_coordinator(has_local=True)
    # Positively resolved non-off-grid family: keeps the local write route
    # for the #558 protected registers so the boundary write is observable.
    coordinator.data["devices"]["1234567890"]["features"] = {
        "inverter_family": "EG4_HYBRID"
    }
    entity = entity_type(coordinator, "1234567890")
    _prep(entity)

    await entity.async_set_native_value(value)
