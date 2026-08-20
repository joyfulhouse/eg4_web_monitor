"""Immutable latest-complete raw snapshot contracts for Phase A3 (#583)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import time
from typing import Any
from uuid import UUID

import pytest
from pylxpweb.transports import RegisterSpace

from custom_components.eg4_web_monitor.raw_snapshot import (
    CrcValidationState,
    FreshnessPolicy,
    LatestCompleteRawSnapshotStore,
    RawRegisterBlock,
    RawSnapshotFrame,
    SnapshotValidationState,
)


EPOCH = UUID("00000000-0000-0000-0000-000000000001")


def _frame(*, ended: float = 20.0, generation: int = 1) -> RawSnapshotFrame:
    block = RawRegisterBlock(
        endpoint_key="owner-1",
        unit=1,
        family_scope="synthetic-family",
        firmware_scope="synthetic-firmware",
        register_space=RegisterSpace.INPUT,
        start_address=10,
        count=3,
        words=(101, 102, 103),
        owner_epoch=EPOCH,
        generation=generation,
        poll_cycle=generation,
        acquired_monotonic_start=19.0,
        acquired_monotonic_end=ended,
        validation_state=SnapshotValidationState.VALID,
        crc_state=CrcValidationState.NOT_APPLICABLE,
    )
    return RawSnapshotFrame(
        owner_epoch=EPOCH,
        generation=generation,
        poll_cycle=generation,
        acquired_monotonic_start=19.0,
        acquired_monotonic_end=ended,
        blocks=(block,),
    )


def test_models_are_frozen_slotted_exact_and_redacted() -> None:
    """Removing frozen slots, exact words, or redacted repr breaks the contract."""
    frame = _frame()
    block = frame.blocks[0]

    assert block.words == (101, 102, 103)
    assert block.count == len(block.words)
    assert not hasattr(block, "__dict__")
    assert "101" not in repr(block)
    assert "synthetic-family" not in repr(block)
    with pytest.raises(FrozenInstanceError):
        setattr(block, "count", 4)


@pytest.mark.parametrize(
    ("count", "words"),
    [(0, ()), (2, (1,)), (1, (-1,)), (1, (0x1_0000,))],
)
def test_raw_block_rejects_incomplete_or_non_word_payloads(
    count: int, words: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError):
        RawRegisterBlock(
            endpoint_key="owner-1",
            unit=1,
            family_scope=None,
            firmware_scope=None,
            register_space=RegisterSpace.INPUT,
            start_address=0,
            count=count,
            words=words,
            owner_epoch=EPOCH,
            generation=1,
            poll_cycle=1,
            acquired_monotonic_start=1.0,
            acquired_monotonic_end=2.0,
            validation_state=SnapshotValidationState.VALID,
            crc_state=CrcValidationState.NOT_APPLICABLE,
        )


@pytest.mark.parametrize(
    ("poll_interval", "expected"),
    [(1.0, 15.0), (10.0, 30.0), (30.0, 60.0)],
)
def test_named_freshness_policy_clamps_three_poll_intervals(
    poll_interval: float, expected: float
) -> None:
    policy = FreshnessPolicy.from_poll_interval(poll_interval)
    assert policy.maximum_age_seconds == expected


def test_freshness_uses_monotonic_end_and_never_ran_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = FreshnessPolicy.from_poll_interval(10.0)
    monkeypatch.setattr(time, "time", lambda: -10_000_000.0)

    assert policy.age_seconds(None, monotonic_now=50.0) is None
    assert policy.is_fresh(_frame(ended=20.0), monotonic_now=49.999)
    assert not policy.is_fresh(_frame(ended=20.0), monotonic_now=50.0)


def test_store_retains_only_latest_complete_and_saturates_redacted_health() -> None:
    store = LatestCompleteRawSnapshotStore(
        freshness_policy=FreshnessPolicy.from_poll_interval(5.0),
        suppression_limit=2,
    )
    first = _frame(generation=1)
    second = _frame(generation=2)

    store.publish(first)
    store.suppress_incomplete(observer_error=True)
    store.suppress_incomplete(observer_error=True)
    store.suppress_incomplete(observer_error=True)
    store.publish(second)

    assert store.latest_complete is second
    assert store.health.suppressed_incomplete == 2
    assert store.health.observer_failures == 2
    health_repr = repr(store.health)
    assert "owner-1" not in health_repr
    assert "101" not in health_repr
    assert not hasattr(store, "latest_attempt")
    assert not hasattr(store, "history")

    store.clear()
    assert store.latest_complete is None


def test_raw_block_rejects_mutable_or_non_int_word_containers() -> None:
    """Only an exact tuple of exact ints satisfies the immutable word contract."""
    kwargs: dict[str, Any] = {
        "endpoint_key": "owner-1",
        "unit": 1,
        "family_scope": None,
        "firmware_scope": None,
        "register_space": RegisterSpace.INPUT,
        "start_address": 0,
        "count": 2,
        "owner_epoch": EPOCH,
        "generation": 1,
        "poll_cycle": 1,
        "acquired_monotonic_start": 1.0,
        "acquired_monotonic_end": 2.0,
        "validation_state": SnapshotValidationState.VALID,
        "crc_state": CrcValidationState.NOT_APPLICABLE,
    }
    with pytest.raises(ValueError):
        RawRegisterBlock(**kwargs, words=[1, 2])
    with pytest.raises(ValueError):
        RawRegisterBlock(**(kwargs | {"count": 1, "words": (True,)}))


def test_frame_rejects_mutable_or_foreign_block_containers() -> None:
    """Only an exact tuple of raw blocks satisfies the immutable frame contract."""
    frame = _frame()
    kwargs: dict[str, Any] = {
        "owner_epoch": EPOCH,
        "generation": 1,
        "poll_cycle": 1,
        "acquired_monotonic_start": 19.0,
        "acquired_monotonic_end": 20.0,
    }
    with pytest.raises(ValueError):
        RawSnapshotFrame(**kwargs, blocks=[frame.blocks[0]])
    with pytest.raises(ValueError):
        RawSnapshotFrame(**kwargs, blocks=(object(),))
