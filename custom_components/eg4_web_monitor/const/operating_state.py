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
stay faithful to the documented meanings. The off-grid determination and the
0x20 / 0x60 readings were corrected against real LXP-LB hardware and the
``lxp_modbus`` integration (@ivanfmartinez, #262) — see notes below.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# Numeric operating-mode code -> stable slug (the stored enum state).
# Hex values mirror Table 9; the localized label for each slug lives in the
# translation files.
OPERATING_STATE_LABELS: dict[int, str] = {
    0x00: "standby",  # Standby
    0x01: "fault",  # Fault
    0x02: "programming",  # Programming (firmware)
    0x04: "pv_to_grid",  # PV exporting to grid
    0x08: "pv_charging",  # PV charging the battery
    0x0C: "pv_charging_to_grid",  # PV charging battery + exporting to grid
    0x10: "battery_to_grid",  # Battery discharging to grid
    # 0x11: observed Standby alias on real hardware (handled by lxp_modbus);
    # not in Table 9. Reuses the "standby" slug (deduped in the options list).
    0x11: "standby",
    0x14: "pv_battery_to_grid",  # PV + battery exporting to grid
    # 0x20: Table 9's name column is "AC charging"; the description "Grid charges
    # the battery" is misleading — on real hardware this also occurs charging
    # from AC-coupled PV with no grid power (@ivanfmartinez). Labeled "AC", not
    # "Grid".
    0x20: "ac_charging",  # AC charging the battery (grid and/or AC-coupled)
    0x28: "pv_ac_charging",  # PV + AC charging the battery
    0x40: "off_grid_battery",  # Off-grid, battery discharging
    # 0x60: Table 9 contradicts itself (name "Off-grid + battery charging" vs
    # description "On-grid ... AC Coupled"). Real-hardware test (main breaker
    # off, AC-couple charging) and the lxp_modbus integration both confirm this
    # is OFF-GRID AC-coupled charging (@ivanfmartinez, #262).
    0x60: "ac_coupled_charging",  # Off-grid AC-coupled charging
    0x80: "pv_off_grid",  # Off-grid, PV only (unstable; inverter inhibited)
    0x88: "pv_charging_off_grid",  # Off-grid, PV output + battery charging
    0xC0: "pv_battery_off_grid",  # Off-grid, PV + battery discharging
}

# Unique, ordered slugs for the enum sensor's ``options``. 0x11 reuses the
# "standby" slug, so de-duplicate while preserving code order.
OPERATING_STATE_OPTIONS: list[str] = list(
    dict.fromkeys(OPERATING_STATE_LABELS.values())
)

# Codes at or above this are off-grid (bit 6 or bit 7 set). Per Table 9's name
# column, real LXP-LB hardware, and the lxp_modbus integration, every documented
# code >= 0x40 is off-grid — including 0x60 (off-grid AC-coupled charging), which
# the Luxpower docs label inconsistently. Using the threshold (rather than only
# the documented set) means an undocumented off-grid combination still trips the
# Off-Grid binary sensor instead of silently reading on-grid.
_OFF_GRID_MIN_CODE = 0x40

# The documented off-grid codes (derived from the threshold + the label table).
OFF_GRID_STATUS_CODES: frozenset[int] = frozenset(
    code for code in OPERATING_STATE_LABELS if code >= _OFF_GRID_MIN_CODE
)


def operating_state_slug(code: int | None) -> str | None:
    """Return the stable enum slug for an operating-mode code.

    Returns ``None`` for an unknown code or missing value (rendered as
    "unknown" by HA); the raw ``status_code`` sensor remains available for
    diagnosing unmapped codes, and a debug log records the unmapped value.
    """
    if code is None:
        return None
    slug = OPERATING_STATE_LABELS.get(code)
    if slug is None:
        _LOGGER.debug(
            "Unrecognized inverter operating-mode code 0x%02X (%d) — reporting "
            "'unknown'; the Status Code sensor retains the raw value",
            code,
            code,
        )
    return slug


def is_off_grid(code: int | None) -> bool | None:
    """Return whether an operating-mode code is an off-grid (islanded) state.

    Off-grid is any code >= 0x40 (bit 6/7), confirmed against real hardware and
    the lxp_modbus integration (#262). Returns ``None`` when the code is missing
    (e.g. an offline inverter), so the binary sensor reads "unknown" rather than
    a misleading "off".
    """
    if code is None:
        return None
    return code >= _OFF_GRID_MIN_CODE
