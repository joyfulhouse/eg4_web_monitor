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

Evidence — GridBOSS 5044850330 (fw IAAB-1300), dongle reads 2026-09-29,
each change made in the portal or app and read back with every other
register in 229-317 and 2099-2104 unchanged:

- SOC byte order: AC start SOC p4 8 → 10 moved only the LOW byte of 245
  (0x5408 → 0x540a); SL end SOC p3 70 → 33 moved only the HIGH byte of 232.
  Shedding SOC p1 read lo 80 / hi 40 against portal start 80 / end 40.
- Windows: AC window 2 p4 00:00-00:00 → 02:01-02:02 wrote 314 = 0x0102 and
  315 = 0x0202 (lo = hour, hi = minute); SL windows p3 set to 04:05-05:04,
  07:06-06:07, 08:09-09:08 read back exactly at 282-287.
- Shedding start PV power: portal 0.4 kW (p1) and 0.3 kW (p3) read 4 and 3
  at 254 / 256 (×0.1 kW).
- 229 shedding bits: portal Shedding Disable → Enable on p2 set only bit 13
  and the revert cleared only bit 13; p1 / p3 (bits 12 / 14) match the
  portal. p4 (bit 15) follows the pattern and is not change-tested.
- 229 enable / grid-on / AC couple bits: pinned for f2725ee (raw↔named
  across three systems) and re-confirmed here — enabling Smart Load on p1
  and p2 set exactly bits 0 and 1.
- 2101 based-on: portal Time → SOC/Volt set only bit 3 (p3), only bit 2
  (p2, reverted round-trip) and bit 1 (p1, set together with p2 / p3).
  p4 (bit 4) follows the pattern and is not change-tested.
- Voltage words read 540 / 480 against the cloud's "54" / "48" (÷10). Not
  change-tested: the unit runs SOC control, where the portal greys them.

Bits 5-8 of 2101 are the cloud's ``BIT_SMART_LOAD_BASE_ON_TIME_SOC_VOLT_n``
— the mobile app's "Time+SOC/Volt" option, which the web portal does not
offer. They are not exposed, and every write preserves them (writes mask
one field of a freshly read register).

A readback proves storage and transport, not semantics: what the firmware
does with these values is described by the GridBOSS user manual (v1.1.2
§8.4), not proven here.
"""

from __future__ import annotations

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
        if field.kind == "bit" and value not in (0, 1):
            raise ValueError(f"bit value must be 0 or 1, got {value!r}")
        mask = 1 << field.bit
        return (raw | mask) if value else (raw & ~mask & 0xFFFF)
    if field.kind in ("lo", "hi"):
        byte = int(value)
        if byte != value or not 0 <= byte <= 0xFF:
            raise ValueError(f"byte value out of range: {value!r}")
        if field.kind == "lo":
            return (raw & 0xFF00) | byte
        return (raw & 0x00FF) | (byte << 8)
    word = int(round(value * field.divisor))
    if not 0 <= word <= 0xFFFF:
        raise ValueError(f"register value out of range: {value!r}")
    return word
