"""GridBOSS (MIDBOX) smart port option registers.

The per-port settings the portal shows under each GridBOSS smart port —
enables, "based on", SOC / voltage thresholds, power shedding and time
windows. pylxpweb's MIDBOX name map does not carry these registers (reg-117
precedent, GH #272), so the integration reads them raw over the local
transport and decodes them here.

Register layout (n = smart port 1-4)::

    229            bits n-1      FUNC_SMART_LOAD_EN_n        Smart Load enable
                   bits n+3      FUNC_SMART_LOAD_GRID_ON_n   Grid Always On
                   bits n+7      FUNC_AC_COUPLE_EN_n         AC Couple enable
                   bits n+11     FUNC_SHEDDING_MODE_EN_n     Use power shedding
    229+n          lo / hi byte  Smart Load start / end SOC (%)
    232+2n, +1     word ÷10      Smart Load start / end voltage (V)
    241+n          lo / hi byte  AC Couple start / end SOC (%)
    244+2n, +1     word ÷10      AC Couple start / end voltage (V)
    253+n          word ÷10      Shedding start PV power (kW)
    257+n          lo / hi byte  Shedding start / end SOC (%)
    260+2n, +1     word ÷10      Shedding start / end voltage (V)
    270+6(n-1)..   6 words       Smart Load windows S1,E1,S2,E2,S3,E3
    294+6(n-1)..   6 words       AC Couple windows, same layout
                                 (window word: lo byte = hour, hi = minute)
    2101           bit n         BIT_SMART_LOAD_BASE_ON_n    1 = SOC/Volt, 0 = Time

Names are the cloud's own parameter names. The cloud range read decodes
every one of these registers by name (pylxpweb
``docs/inverters/GridBoss_43XXXXXX85.md`` and ``GridBoss_52XXXXXX23.md``),
which fixes the register → field assignment; byte order, scale and bit
positions are pinned by controlled changes on a live unit.

Evidence — GridBOSS 5044850330 (fw IAAB-1300), dongle reads of 20,
229-317 and 2099-2104 on 2026-09-29, one read before and one after each
portal or app change. Raw before → after pairs, with every register that
changed in that step listed:

- App, port 4 AC start SOC 8 → 10 and AC window 2 00:00-00:00 →
  02:01-02:02: 245 0x5408 → 0x540a (LOW byte = start SOC), 314 0x0000 →
  0x0102 and 315 0x0000 → 0x0202 (low byte = hour, high byte = minute).
  Nothing else changed.
- App, several fields on ports 1-3 at once (not one change per step):
  232 0x465a → 0x215a (port 3 end SOC 70 → 33, HIGH byte = end SOC);
  254 0x0 → 0x4 and 256 0x0 → 0x3 (shedding start PV power 0.4 / 0.3 kW,
  ×0.1 kW); 258 0x3c5a → 0x2850 (port 1 shedding start 80 / end 40);
  282-287 0 → 0x0504, 0x0405, 0x0607, 0x0706, 0x0908, 0x0809 (port 3
  windows 04:05-05:04, 07:06-06:07, 08:09-09:08); 229 0x0875 → 0x5875;
  2101 0x18 → 0x22. The 229 / 2101 changes of this step are not
  attributed bit by bit (several ports changed together).
- Portal, port 3 based on Time → SOC/Volt: 2101 0x32 → 0x3a (bit 3 only).
- Portal, port 2 Shedding Disable → Enable and based on Time → SOC/Volt:
  229 0x5875 → 0x7875 (bit 13 only), 2101 0x3a → 0x3e (bit 2 only).
  Reverted in the portal: 229 0x7875 → 0x5875, 2101 0x3e → 0x3a — the
  original state restored.
- Portal, Smart Load enable on ports 1 and 2 and based on SOC/Volt on
  ports 1-3: 229 0x3074 → 0x3077 (bits 0, 1), 2101 0x30 → 0x3e (bits 1-3).
- 229 grid-on / AC couple bits: pinned for f2725ee (raw↔named across three
  systems). Shedding bits 12 / 14 (ports 1 / 3) agree with the portal.
- Home Assistant write test, port 4 in Smart Load (2026-09-30, build
  +smartports.11, each write read back over the dongle and reverted; the
  full 20 / 229-317 / 2099-2104 set matched the pre-test read afterwards):
  Smart Load enable 229 0x3077 → 0x307f (bit 3); Grid Always On → 0x30f7
  (bit 7); Power Shedding → 0xb077 (bit 15), shown by the portal as "Smart
  Load 4 Use Shedding Mode: Enable"; SL start / end SOC 85 / 55 → 233
  0x3c55 / 0x3755; based on Time → 2101 0x2e; SL start time 1 01:02 → 288
  0x0201; shedding start PV power 0.5 kW → 257 0x0005; shedding start SOC
  88 → 261 0x3c58.
- Portal, port 4 (switched Unused → Smart Load first: 20 0x15 → 0x55,
  2101 unchanged) based on SOC/Volt → Time: 2101 0x3e → 0x2e (bit 4 only,
  nothing else changed). Reverted in the portal (SOC/Volt, then Unused):
  2101 0x2e → 0x3e, 20 0x55 → 0x15 — the original state restored.
  (Earlier, the mobile app's port 3 "Time+SOC/Volt" choice also set bit 4:
  2101 0x22 → 0x32. That is the app writing port 4's bit, not a separate
  field; the app was not a reliable readback either.)
- Voltage words read 540 / 480 against the cloud's "54" / "48" (÷10). Not
  change-tested: the unit runs SOC control, where the portal greys them.

The cloud also names ``BIT_MID_INSTALL_POSITION`` and
``BIT_SMART_LOAD_BASE_ON_TIME_SOC_VOLT_n`` (the mobile app's "Time+SOC/Volt"
option, which the web portal does not offer) in 2101; their bit positions
are not pinned (bit 5 reads set on the live unit, meaning unknown). They are
not exposed, and every write preserves them (writes mask one field of a
freshly read register).

A readback proves storage and transport, not semantics: what the firmware
does with these values is described by the GridBOSS user manual (v1.1.2
§8.4), not proven here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

SMART_PORT_NUMBERS: tuple[int, ...] = (1, 2, 3, 4)

MIDBOX_REG_SMART_PORT_FUNCTIONS = 229
MIDBOX_REG_SMART_LOAD_BASE_ON = 2101

# Holding-register blocks covering every field below (≤ 40 registers each,
# the dongle's safe block size).
MIDBOX_OPTION_READ_BLOCKS: tuple[tuple[int, int], ...] = (
    (229, 40),
    (269, 40),
    (309, 9),
    (MIDBOX_REG_SMART_LOAD_BASE_ON, 1),
)

# "flag": one bit decoded as bool. "bit": one bit decoded as int 0/1.
# "lo" / "hi": one byte. "word": the whole register, divided by ``divisor``.
MidboxFieldKind = Literal["flag", "bit", "lo", "hi", "word"]


@dataclass(frozen=True)
class MidboxField:
    """Where one named option lives inside a GridBOSS holding register."""

    register: int
    kind: MidboxFieldKind
    bit: int = 0
    divisor: int = 1


# Function-enable prefixes in register 229 → base bit of the per-port group.
MIDBOX_SMART_PORT_FUNCTION_BASE_BITS: dict[str, int] = {
    "FUNC_SMART_LOAD_EN": 0,
    "FUNC_SMART_LOAD_GRID_ON": 4,
    "FUNC_AC_COUPLE_EN": 8,
    "FUNC_SHEDDING_MODE_EN": 12,
}

# Value of BIT_SMART_LOAD_BASE_ON_n.
SMART_LOAD_BASE_ON_TIME = 0
SMART_LOAD_BASE_ON_SOC_VOLT = 1


def _soc_pair(prefix: str, register: int, port: int) -> dict[str, MidboxField]:
    return {
        f"{prefix}_START_SOC_{port}": MidboxField(register, "lo"),
        f"{prefix}_END_SOC_{port}": MidboxField(register, "hi"),
    }


def _volt_pair(prefix: str, register: int, port: int) -> dict[str, MidboxField]:
    return {
        f"{prefix}_START_VOLT_{port}": MidboxField(register, "word", divisor=10),
        f"{prefix}_END_VOLT_{port}": MidboxField(register + 1, "word", divisor=10),
    }


def _windows(prefix: str, register: int) -> dict[str, MidboxField]:
    fields: dict[str, MidboxField] = {}
    for window in (1, 2, 3):
        for offset, edge in ((0, "START"), (1, "END")):
            reg = register + 2 * (window - 1) + offset
            fields[f"{prefix}_{edge}_HOUR_{window}"] = MidboxField(reg, "lo")
            fields[f"{prefix}_{edge}_MINUTE_{window}"] = MidboxField(reg, "hi")
    return fields


def _build_fields() -> dict[str, MidboxField]:
    fields: dict[str, MidboxField] = {}
    for port in SMART_PORT_NUMBERS:
        for prefix, base in MIDBOX_SMART_PORT_FUNCTION_BASE_BITS.items():
            fields[f"{prefix}_{port}"] = MidboxField(
                MIDBOX_REG_SMART_PORT_FUNCTIONS, "flag", bit=base + port - 1
            )
        fields[f"BIT_SMART_LOAD_BASE_ON_{port}"] = MidboxField(
            MIDBOX_REG_SMART_LOAD_BASE_ON, "bit", bit=port
        )
        fields.update(_soc_pair("MIDBOX_HOLD_SL", 229 + port, port))
        fields.update(_volt_pair("MIDBOX_HOLD_SL", 232 + 2 * port, port))
        fields.update(_soc_pair("MIDBOX_HOLD_AC", 241 + port, port))
        fields.update(_volt_pair("MIDBOX_HOLD_AC", 244 + 2 * port, port))
        fields[f"MIDBOX_HOLD_SL_START_PV_P_{port}"] = MidboxField(
            253 + port, "word", divisor=10
        )
        fields.update(_soc_pair("MIDBOX_HOLD_SL_PS", 257 + port, port))
        fields.update(_volt_pair("MIDBOX_HOLD_SL_PS", 260 + 2 * port, port))
        fields.update(_windows(f"HOLD_MIDBOX_SL_{port}", 270 + 6 * (port - 1)))
        fields.update(_windows(f"HOLD_MIDBOX_AC_COUPLE_{port}", 294 + 6 * (port - 1)))
    return fields


MIDBOX_OPTION_FIELDS: dict[str, MidboxField] = _build_fields()


def _fields_by_register() -> dict[int, dict[str, MidboxField]]:
    by_register: dict[int, dict[str, MidboxField]] = {}
    for name, field in MIDBOX_OPTION_FIELDS.items():
        by_register.setdefault(field.register, {})[name] = field
    return by_register


MIDBOX_OPTION_FIELDS_BY_REGISTER: dict[int, dict[str, MidboxField]] = (
    _fields_by_register()
)


def decode_midbox_field(field: MidboxField, raw: int) -> Any:
    """Decode one field from its register's raw value."""
    if field.kind == "flag":
        return bool((raw >> field.bit) & 1)
    if field.kind == "bit":
        return (raw >> field.bit) & 1
    if field.kind == "lo":
        return raw & 0xFF
    if field.kind == "hi":
        return (raw >> 8) & 0xFF
    if field.divisor == 1:
        return raw
    return round(raw / field.divisor, 1)


def decode_midbox_options(raw: Mapping[int, int]) -> dict[str, Any]:
    """Decode every option field whose register is present in ``raw``."""
    values: dict[str, Any] = {}
    for register, value in raw.items():
        for name, field in MIDBOX_OPTION_FIELDS_BY_REGISTER.get(register, {}).items():
            values[name] = decode_midbox_field(field, value)
    return values


def encode_midbox_field(field: MidboxField, raw: int, value: Any) -> int:
    """Return ``raw`` with ``field`` set to ``value``; other bits untouched.

    Raises:
        ValueError: If ``value`` does not fit the field.
    """
    if field.kind in ("flag", "bit"):
        if value not in (0, 1) or not isinstance(value, bool | int):
            raise ValueError(f"bit value must be 0/1 or a bool, got {value!r}")
        mask = 1 << field.bit
        return (raw | mask) if value else (raw & ~mask & 0xFFFF)
    if field.kind in ("lo", "hi"):
        byte = int(value)
        if byte != value or not 0 <= byte <= 0xFF:
            raise ValueError(f"byte value out of range: {value!r}")
        if field.kind == "lo":
            return (raw & 0xFF00) | byte
        return (raw & 0x00FF) | (byte << 8)
    # Half-up, not round()'s half-to-even: 0.05 kW must not become 0.
    word = int(math.floor(value * field.divisor + 0.5))
    if not 0 <= word <= 0xFFFF:
        raise ValueError(f"register value out of range: {value!r}")
    return word


# =============================================================================
# Smart port option entities
# =============================================================================
# One spec per entity on each Smart Port N device. The unique ID is
# ``{serial}_smart_port{n}_{id_suffix}``; ``param`` is the option name with
# ``{port}`` for the port number (for a time window, the name without its
# ``_HOUR_{w}`` / ``_MINUTE_{w}`` tail, ``w`` = ``window``).
#
# ``mode`` is the port mode the entity belongs to: the entity registry sync
# (smart_port_devices.PortSensorEnablement) disables it while the port is in
# another mode. ``gates`` mirror the portal, which greys a field out
# (the entity shows unavailable) unless:
#   - GATE_TIME_BASED: the port's "based on" is Time
#   - GATE_SHEDDING:   power shedding is on for the port
#   - GATE_SOC / GATE_VOLT: SOC / voltage thresholds. Not availability gates:
#     the configured Battery Charge / Discharge Control option decides which
#     set is enabled (option_matches_control_modes, via the registry sync),
#     and the inverters' live regime is reported as entity attributes. Which
#     regime the GridBOSS applies is unproven: the portal greyed a port's
#     voltage fields while the inverter reported voltage control.
PORT_MODE_SMART_LOAD = "smart_load"
PORT_MODE_AC_COUPLE = "ac_couple"

GATE_TIME_BASED = "time_based"
GATE_SHEDDING = "shedding"
GATE_SOC = "soc"
GATE_VOLT = "volt"


@dataclass(frozen=True)
class PortOptionSpec:
    """One smart port option entity."""

    platform: Literal["switch", "select", "number", "time"]
    id_suffix: str
    name: str
    mode: str
    param: str
    gates: tuple[str, ...] = ()
    window: int = 0
    icon: str | None = None

    def param_name(self, port: int) -> str:
        """Option name of this entity's field for ``port``."""
        return self.param.format(port=port)


def _threshold_specs(
    id_prefix: str,
    name_prefix: str,
    mode: str,
    param_prefix: str,
    gates: tuple[str, ...],
) -> tuple[PortOptionSpec, ...]:
    return tuple(
        PortOptionSpec(
            "number",
            f"{id_prefix}_{edge.lower()}_{unit_id}",
            f"{name_prefix} {edge.title()} {unit_name}",
            mode,
            f"{param_prefix}_{edge}_{unit_param}_{{port}}",
            (*gates, gate),
        )
        for unit_id, unit_name, unit_param, gate in (
            ("soc", "SOC", "SOC", GATE_SOC),
            ("voltage", "Voltage", "VOLT", GATE_VOLT),
        )
        for edge in ("START", "END")
    )


def _window_specs(
    id_prefix: str,
    name_prefix: str,
    mode: str,
    param_prefix: str,
    gates: tuple[str, ...],
) -> tuple[PortOptionSpec, ...]:
    return tuple(
        PortOptionSpec(
            "time",
            f"{id_prefix}_{edge.lower()}_time_{window}",
            f"{name_prefix} {edge.title()} Time {window}",
            mode,
            f"{param_prefix}_{{port}}_{edge}",
            gates,
            window=window,
        )
        for window in (1, 2, 3)
        for edge in ("START", "END")
    )


PORT_OPTION_SPECS: tuple[PortOptionSpec, ...] = (
    # Smart Load
    PortOptionSpec(
        "switch",
        "smart_load_enable",
        "Smart Load Enable",
        PORT_MODE_SMART_LOAD,
        "FUNC_SMART_LOAD_EN_{port}",
        icon="mdi:power-plug-outline",
    ),
    PortOptionSpec(
        "switch",
        "grid_always_on",
        "Grid Always On",
        PORT_MODE_SMART_LOAD,
        "FUNC_SMART_LOAD_GRID_ON_{port}",
        icon="mdi:transmission-tower",
    ),
    PortOptionSpec(
        "switch",
        "power_shedding",
        "Power Shedding",
        PORT_MODE_SMART_LOAD,
        "FUNC_SHEDDING_MODE_EN_{port}",
        icon="mdi:transmission-tower-off",
    ),
    PortOptionSpec(
        "select",
        "based_on",
        "Based On",
        PORT_MODE_SMART_LOAD,
        "BIT_SMART_LOAD_BASE_ON_{port}",
        icon="mdi:tune-variant",
    ),
    *_threshold_specs(
        "smart_load", "Smart Load", PORT_MODE_SMART_LOAD, "MIDBOX_HOLD_SL", ()
    ),
    PortOptionSpec(
        "number",
        "shedding_start_pv_power",
        "Shedding Start PV Power",
        PORT_MODE_SMART_LOAD,
        "MIDBOX_HOLD_SL_START_PV_P_{port}",
        (GATE_SHEDDING,),
    ),
    *_threshold_specs(
        "shedding",
        "Shedding",
        PORT_MODE_SMART_LOAD,
        "MIDBOX_HOLD_SL_PS",
        (GATE_SHEDDING,),
    ),
    *_window_specs(
        "smart_load",
        "Smart Load",
        PORT_MODE_SMART_LOAD,
        "HOLD_MIDBOX_SL",
        (GATE_TIME_BASED,),
    ),
    # AC Couple
    PortOptionSpec(
        "switch",
        "ac_couple_enable",
        "AC Couple Enable",
        PORT_MODE_AC_COUPLE,
        "FUNC_AC_COUPLE_EN_{port}",
        icon="mdi:solar-power-variant",
    ),
    *_threshold_specs(
        "ac_couple", "AC Couple", PORT_MODE_AC_COUPLE, "MIDBOX_HOLD_AC", ()
    ),
    *_window_specs(
        "ac_couple", "AC Couple", PORT_MODE_AC_COUPLE, "HOLD_MIDBOX_AC_COUPLE", ()
    ),
)


def regime_side(spec: PortOptionSpec) -> str:
    """Battery control side governing a spec's SOC / voltage gate.

    Smart Load and shedding thresholds act as the battery discharges; AC
    Couple thresholds as it charges (inferred, not proven).
    """
    return "charge" if spec.mode == PORT_MODE_AC_COUPLE else "discharge"


def option_matches_control_modes(
    spec: PortOptionSpec, charge_mode: str, discharge_mode: str
) -> bool:
    """Whether a spec serves the configured battery control modes.

    ``charge_mode`` / ``discharge_mode`` are the integration's Battery Charge
    / Discharge Control options (``"soc"`` or ``"voltage"``). SOC thresholds
    serve SOC control and voltage thresholds voltage control; specs without
    a SOC / voltage gate always serve.
    """
    mode = charge_mode if regime_side(spec) == "charge" else discharge_mode
    if GATE_SOC in spec.gates:
        return mode == "soc"
    if GATE_VOLT in spec.gates:
        return mode == "voltage"
    return True


def port_option_specs(platform: str) -> tuple[PortOptionSpec, ...]:
    """The option specs of one platform."""
    return tuple(spec for spec in PORT_OPTION_SPECS if spec.platform == platform)
