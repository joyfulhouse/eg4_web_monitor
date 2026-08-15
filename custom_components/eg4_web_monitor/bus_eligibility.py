"""Pure fail-closed eligibility for the dormant local-bus foundation."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class LocalBusProvenance(StrEnum):
    """Closed provenance vocabulary accepted by endpoint bus owners."""

    LOCAL_BUS = "local_bus"


class BusEligibilityReason(StrEnum):
    """Redacted result codes for setup and runtime coverage checks."""

    ELIGIBLE = "eligible"
    CLOUD_ONLY = "cloud_only"
    EMPTY_LOCAL = "empty_local"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"
    AMBIGUOUS_ENDPOINT = "ambiguous_endpoint"
    UNCOVERED_BUS = "uncovered_bus"
    OVERLAPPING_WIFI_DONGLE = "overlapping_wifi_dongle"


@dataclass(frozen=True, slots=True)
class BusOwnerEligibility:
    """Eligibility without endpoint, identity, or configuration disclosure."""

    eligible: bool
    reason: BusEligibilityReason
    provenance: LocalBusProvenance = LocalBusProvenance.LOCAL_BUS


_ELIGIBLE_CONNECTION_TYPES = frozenset({"local", "hybrid"})
_QUALIFYING_TRANSPORT_TYPES = frozenset({"modbus_tcp", "modbus_serial"})


def _has_unambiguous_endpoint(config: Mapping[str, Any]) -> bool:
    """Return whether one qualifying config names a physical endpoint."""
    serial = config.get("serial")
    if not isinstance(serial, str) or not serial:
        return False
    if config.get("transport_type") == "modbus_serial":
        serial_port = config.get("serial_port")
        return isinstance(serial_port, str) and bool(serial_port)
    host = config.get("host")
    port = config.get("port")
    return isinstance(host, str) and bool(host.strip()) and isinstance(port, int)


def evaluate_bus_owner_eligibility(
    *,
    connection_type: str,
    local_transports: Sequence[Mapping[str, Any]],
    available_serials: Collection[str] | None = None,
) -> BusOwnerEligibility:
    """Evaluate complete direct-local coverage without side effects.

    ``available_serials`` is omitted for the setup/configuration-only check and
    supplied after attachment or link-state transitions. Only redacted reason
    codes leave this function.
    """
    if connection_type == "http":
        return BusOwnerEligibility(False, BusEligibilityReason.CLOUD_ONLY)
    if connection_type not in _ELIGIBLE_CONNECTION_TYPES:
        return BusOwnerEligibility(False, BusEligibilityReason.LEGACY_AMBIGUOUS)
    if not local_transports:
        return BusOwnerEligibility(False, BusEligibilityReason.EMPTY_LOCAL)

    direct = [
        config
        for config in local_transports
        if config.get("transport_type") in _QUALIFYING_TRANSPORT_TYPES
    ]
    if any(not _has_unambiguous_endpoint(config) for config in direct):
        return BusOwnerEligibility(False, BusEligibilityReason.AMBIGUOUS_ENDPOINT)

    direct_serials = {str(config["serial"]) for config in direct}
    wifi_serials = {
        str(config.get("serial"))
        for config in local_transports
        if config.get("transport_type") == "wifi_dongle" and config.get("serial")
    }
    if direct_serials & wifi_serials:
        return BusOwnerEligibility(False, BusEligibilityReason.OVERLAPPING_WIFI_DONGLE)

    configured_serials = {
        str(config.get("serial")) for config in local_transports if config.get("serial")
    }
    if not direct_serials or not configured_serials <= direct_serials:
        return BusOwnerEligibility(False, BusEligibilityReason.UNCOVERED_BUS)
    if available_serials is not None and not direct_serials <= set(available_serials):
        return BusOwnerEligibility(False, BusEligibilityReason.UNCOVERED_BUS)
    return BusOwnerEligibility(True, BusEligibilityReason.ELIGIBLE)
