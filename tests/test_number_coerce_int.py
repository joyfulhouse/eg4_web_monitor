"""Characterization tests for SOC integer validation messages."""

from collections.abc import Sequence

import pytest
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


ENTITY_CASES: Sequence = (
    pytest.param(
        ACChargeSOCLimitNumber,
        0,
        101,
        "AC charge SOC limit",
        id="ac-charge-soc-limit",
    ),
    pytest.param(
        ACChargeStartBatterySOCNumber,
        0,
        100,
        "AC charge start battery SOC",
        id="ac-charge-start-battery-soc",
    ),
    pytest.param(
        ACChargeEndBatterySOCNumber,
        0,
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
        OnGridSOCCutoffNumber,
        0,
        100,
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
async def test_non_integer_message_is_exact(
    entity_type: type[EG4BaseNumberEntity],
    min_v: int,
    max_v: int,
    label: str,
) -> None:
    """In-range fractional values preserve the exact validation message."""
    value = min_v + 0.5
    coordinator = _mock_coordinator(has_local=True)
    entity = entity_type(coordinator, "1234567890")
    _prep(entity)

    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_set_native_value(value)

    assert str(exc_info.value) == f"{label} must be an integer value, got {value}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity_type", "min_v", "max_v", "label"), ENTITY_CASES)
async def test_in_range_integer_succeeds(
    entity_type: type[EG4BaseNumberEntity],
    min_v: int,
    max_v: int,
    label: str,
) -> None:
    """An in-range integer reaches the mocked write successfully."""
    coordinator = _mock_coordinator(has_local=True)
    entity = entity_type(coordinator, "1234567890")
    _prep(entity)

    await entity.async_set_native_value(float(min_v))
