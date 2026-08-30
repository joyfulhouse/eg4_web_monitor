"""Immutable latest-complete raw-register snapshots for direct local buses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import time
from uuid import UUID

from pylxpweb.transports import RegisterSpace


class SnapshotValidationState(StrEnum):
    """Closed whole-frame validation result exposed by a complete snapshot."""

    VALID = "valid"


class CrcValidationState(StrEnum):
    """Honest CRC evidence available from the public transport contract."""

    NOT_APPLICABLE = "not_applicable"
    VALID = "valid"


@dataclass(frozen=True, slots=True, repr=False)
class RawRegisterBlock:
    """One exact terminal-winning raw register segment."""

    endpoint_key: str
    unit: int
    family_scope: str | None
    firmware_scope: str | None
    register_space: RegisterSpace
    start_address: int
    count: int
    words: tuple[int, ...]
    owner_epoch: UUID
    generation: int
    poll_cycle: int
    acquired_monotonic_start: float
    acquired_monotonic_end: float
    validation_state: SnapshotValidationState
    crc_state: CrcValidationState

    def __post_init__(self) -> None:
        if type(self.words) is not tuple or any(
            type(word) is not int for word in self.words
        ):
            raise ValueError("Raw block words must be an exact tuple of ints")
        if self.count <= 0 or self.count != len(self.words):
            raise ValueError("Raw block count must match its non-empty word tuple")
        if self.start_address < 0 or self.unit < 0:
            raise ValueError("Raw block address and unit must be non-negative")
        if any(word < 0 or word > 0xFFFF for word in self.words):
            raise ValueError("Raw register words must be unsigned 16-bit values")
        if self.acquired_monotonic_end < self.acquired_monotonic_start:
            raise ValueError("Acquisition end must not precede its start")

    def __repr__(self) -> str:
        """Expose bounded structure without identity or raw register values."""
        return (
            f"{type(self).__name__}(register_space={self.register_space!r}, "
            f"start_address={self.start_address!r}, count={self.count!r}, "
            "identity=<redacted>, words=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class RawSnapshotFrame:
    """One atomically published complete owner refresh."""

    owner_epoch: UUID
    generation: int
    poll_cycle: int
    acquired_monotonic_start: float
    acquired_monotonic_end: float
    blocks: tuple[RawRegisterBlock, ...]

    def __post_init__(self) -> None:
        if type(self.blocks) is not tuple or any(
            type(block) is not RawRegisterBlock for block in self.blocks
        ):
            raise ValueError("Frame blocks must be an exact tuple of raw blocks")
        if self.generation <= 0 or self.poll_cycle <= 0 or not self.blocks:
            raise ValueError("A complete frame needs positive identity and blocks")
        if self.acquired_monotonic_end < self.acquired_monotonic_start:
            raise ValueError("Acquisition end must not precede its start")
        identity = (self.owner_epoch, self.generation, self.poll_cycle)
        if any(
            (block.owner_epoch, block.generation, block.poll_cycle) != identity
            or block.acquired_monotonic_start != self.acquired_monotonic_start
            or block.acquired_monotonic_end != self.acquired_monotonic_end
            for block in self.blocks
        ):
            raise ValueError("Every block must belong to exactly this refresh")


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Named monotonic freshness policy for latest-complete frames."""

    maximum_age_seconds: float

    @classmethod
    def from_poll_interval(cls, poll_interval_seconds: float) -> FreshnessPolicy:
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be finite and positive")
        return cls(min(60.0, max(15.0, 3.0 * poll_interval_seconds)))

    def age_seconds(
        self,
        frame: RawSnapshotFrame | None,
        *,
        monotonic_now: float | None = None,
    ) -> float | None:
        """Return monotonic age, preserving ``None`` for never published."""
        if frame is None:
            return None
        now = time.monotonic() if monotonic_now is None else monotonic_now
        return max(0.0, now - frame.acquired_monotonic_end)

    def is_fresh(
        self,
        frame: RawSnapshotFrame | None,
        *,
        monotonic_now: float | None = None,
    ) -> bool:
        age = self.age_seconds(frame, monotonic_now=monotonic_now)
        return age is not None and age < self.maximum_age_seconds


@dataclass(frozen=True, slots=True)
class SnapshotHealth:
    """Bounded identity-free health counters."""

    suppressed_incomplete: int
    observer_failures: int


@dataclass(frozen=True, slots=True)
class SnapshotMetrics:
    """Identity-free current freshness and bounded health metrics."""

    age_seconds: float | None
    fresh: bool
    suppressed_incomplete: int
    observer_failures: int


class LatestCompleteRawSnapshotStore:
    """O(1) externally readable latest-complete snapshot state."""

    __slots__ = (
        "_freshness_policy",
        "_latest_complete",
        "_observer_failures",
        "_suppressed_incomplete",
        "_suppression_limit",
    )

    def __init__(
        self,
        *,
        freshness_policy: FreshnessPolicy,
        suppression_limit: int = (2**31) - 1,
    ) -> None:
        if suppression_limit <= 0:
            raise ValueError("Suppression limit must be positive")
        self._freshness_policy = freshness_policy
        self._suppression_limit = suppression_limit
        self._latest_complete: RawSnapshotFrame | None = None
        self._suppressed_incomplete = 0
        self._observer_failures = 0

    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return self._freshness_policy

    @property
    def latest_complete(self) -> RawSnapshotFrame | None:
        return self._latest_complete

    @property
    def health(self) -> SnapshotHealth:
        return SnapshotHealth(self._suppressed_incomplete, self._observer_failures)

    def publish(self, frame: RawSnapshotFrame) -> None:
        self._latest_complete = frame

    def latest_fresh(
        self, *, monotonic_now: float | None = None
    ) -> RawSnapshotFrame | None:
        if self._freshness_policy.is_fresh(
            self._latest_complete, monotonic_now=monotonic_now
        ):
            return self._latest_complete
        return None

    def metrics(self, *, monotonic_now: float | None = None) -> SnapshotMetrics:
        age = self._freshness_policy.age_seconds(
            self._latest_complete, monotonic_now=monotonic_now
        )
        return SnapshotMetrics(
            age_seconds=age,
            fresh=age is not None and age < self._freshness_policy.maximum_age_seconds,
            suppressed_incomplete=self._suppressed_incomplete,
            observer_failures=self._observer_failures,
        )

    def suppress_incomplete(self, *, observer_error: bool = False) -> None:
        self._suppressed_incomplete = min(
            self._suppression_limit, self._suppressed_incomplete + 1
        )
        if observer_error:
            self._observer_failures = min(
                self._suppression_limit, self._observer_failures + 1
            )

    def clear(self) -> None:
        self._latest_complete = None
