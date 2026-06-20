"""Inverter operating-state decode (INPUT register 0 / cloud ``status``).

The inverter exposes its live operating mode as a bit-packed code in INPUT
register 0 (``device_status``, surfaced as the ``status_code`` sensor). The same
value arrives from the cloud API ``status`` field, so the decode is identical in
LOCAL, CLOUD and HYBRID modes.

This module maps those numeric codes to stable, machine-readable slugs. The slug
is what HA stores as the ``operating_state`` enum sensor's state; the human
readable label lives in ``strings.json``/``translations`` so it is localizable
(see ``entity.sensor.operating_state.state``).

Code meanings follow EG4/Luxpower "Table 9 — Operational mode definitions"
(GitHub issue #262). The codes are a bit field, but the combinations are not
cleanly orthogonal, so a direct lookup table (not a bitwise decode) is used to
stay faithful to the documented meanings.
"""

from __future__ import annotations

# Numeric operating-mode code -> stable slug (the stored enum state).
#
# Hex values mirror Table 9. Off-grid codes are grouped via
# ``OFF_GRID_STATUS_CODES`` below rather than inferred from a single bit, because
# the documented combinations do not map to one consistent bit.
OPERATING_STATE_LABELS: dict[int, str] = {
    0x00: "standby",  # Standby
    0x01: "fault",  # Fault
    0x02: "programming",  # Programming (firmware)
    0x04: "pv_to_grid",  # PV exporting to grid
    0x08: "pv_charging",  # PV charging the battery
    0x0C: "pv_charging_to_grid",  # PV charging battery + exporting to grid
    0x10: "battery_to_grid",  # Battery discharging to grid
    0x14: "pv_battery_to_grid",  # PV + battery exporting to grid
    0x20: "ac_charging",  # Grid charging the battery
    0x28: "pv_ac_charging",  # PV + grid charging the battery
    0x40: "off_grid_battery",  # Off-grid, battery discharging
    # 0x60: Table 9 names this "Off-grid + battery charging" but describes it as
    # "On-grid system charge the battery (AC Coupled)" -- contradictory. The
    # description (grid-tied AC coupling) is treated as authoritative, so this is
    # NOT counted as off-grid (see OFF_GRID_STATUS_CODES).
    0x60: "ac_coupled_charging",  # AC-coupled charging
    0x80: "pv_off_grid",  # Off-grid, PV only (unstable; inverter inhibited)
    0x88: "pv_charging_off_grid",  # Off-grid, PV output + battery charging
    0xC0: "pv_battery_off_grid",  # Off-grid, PV + battery discharging
}

# Stable, ordered list of every possible slug -- used as the enum sensor's
# ``options``. ``dict`` preserves insertion order, so this stays sorted by code.
OPERATING_STATE_OPTIONS: list[str] = list(OPERATING_STATE_LABELS.values())

# Codes that mean the inverter is running off-grid (islanded). Drives the
# dedicated "Off-Grid" binary sensor. 0x60 (AC-coupled charging) is grid-tied
# and deliberately excluded.
OFF_GRID_STATUS_CODES: frozenset[int] = frozenset({0x40, 0x80, 0x88, 0xC0})


def operating_state_slug(code: int | None) -> str | None:
    """Return the stable enum slug for an operating-mode code.

    Returns ``None`` for an unknown code or missing value (rendered as
    "unknown" by HA); the raw ``status_code`` sensor remains available for
    diagnosing unmapped codes.
    """
    if code is None:
        return None
    return OPERATING_STATE_LABELS.get(code)


def is_off_grid(code: int | None) -> bool | None:
    """Return whether an operating-mode code is an off-grid state.

    Returns ``None`` when the code is missing (e.g. an offline inverter), so the
    binary sensor reads "unknown" rather than a misleading "off".
    """
    if code is None:
        return None
    return code in OFF_GRID_STATUS_CODES
