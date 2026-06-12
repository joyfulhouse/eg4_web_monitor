"""Register-derived contract harness: integration mapping paths vs pylxpweb.

The integration feeds every register-backed sensor through TWO separate code
paths:

* LOCAL — ``coordinator_mappings`` table functions reading pylxpweb transport
  dataclasses (``InverterRuntimeData``/``InverterEnergyData``/``BatteryData``).
* CLOUD/HYBRID — ``coordinator_mixins`` property maps reading pylxpweb device
  objects (``BaseInverter``/``Battery``/``MIDDevice``), whose properties
  internally dispatch transport-vs-cloud.

History shows fixes repeatedly landing on one path and missing the other
(PV charge power reg64-vs-reg74, bank capacity double count, bank BMS
DIV_10-vs-DIV_100).  This harness derives the EXPECTED mapping from pylxpweb's
canonical register tables (``pylxpweb.registers``) and asserts both
integration paths agree with them, so a divergence fails CI with an
actionable message instead of shipping as a silent per-mode regression.

How the actual mappings are derived (no source parsing, no duplicated
tables):

* LOCAL table functions are executed against a recording stub whose attribute
  reads return identity-preserving tokens, yielding the real
  ``{sensor_key: dataclass_attr}`` map.
* Device properties are executed twice on a stub device — once with only
  transport data attached, once with only cloud data — logging which
  dataclass attribute / cloud API field each property actually reads.
* Both sides are then resolved to canonical register names via pylxpweb's own
  ``RUNTIME_FIELD``/``ENERGY_FIELD``/``BATTERY_FIELD`` mappings and
  ``BY_CLOUD_FIELD`` indices, and compared per sensor key.

Where the two paths DELIBERATELY differ, the divergence is encoded in an
explicit allowlist with a citation, so this module doubles as the executable
inventory of known per-mode behaviour differences.  Entries tagged
``TODO(eg4-...)`` are REAL undocumented divergences found by this harness
that need adjudication — do NOT silently delete them; fix the runtime
behaviour (in a dedicated change) or document the difference, then update
the entry.

Companion files:
* ``tests/test_register_contract.py`` — property-map source attrs exist on
  pylxpweb classes (the existence half of the seam).
* ``pylxpweb/tests/unit/test_register_contract.py`` — canonical tables vs
  pylxpweb's own field mappings / scaling (the pylxpweb-internal half).
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

import pytest
from pylxpweb.constants.registers import (
    MULTI_BIT_FIELDS,
    REGISTER_TO_PARAM_KEYS,
)
from pylxpweb.devices import Battery, GenericInverter, MIDDevice
from pylxpweb.registers.battery import BATTERY_REGISTERS
from pylxpweb.registers.battery import BY_CLOUD_FIELD as BATTERY_BY_CLOUD_FIELD
from pylxpweb.registers.gridboss import BY_NAME as GRIDBOSS_BY_NAME
from pylxpweb.registers.gridboss import GRIDBOSS_REGISTERS, GridBossCategory
from pylxpweb.registers.inverter_holding import BY_API_KEY as HOLDING_BY_API_KEY
from pylxpweb.registers.inverter_input import (
    BY_CLOUD_FIELD,
    INVERTER_INPUT_REGISTERS,
)
from pylxpweb.transports._field_mappings import (
    BATTERY_FIELD,
    ENERGY_CATEGORIES,
    ENERGY_FIELD,
    GRIDBOSS_FIELD,
    RUNTIME_CATEGORIES,
    RUNTIME_FIELD,
    RUNTIME_LOAD_POWER_CANONICAL,
)
from pylxpweb.transports.data import (
    BatteryBankData,
    BatteryData,
    InverterEnergyData,
    InverterRuntimeData,
)

from custom_components.eg4_web_monitor.const import FUNCTION_PARAM_MAPPING
from custom_components.eg4_web_monitor.const.modbus import (
    PARAM_FUNC_AC_CHARGE,
    PARAM_FUNC_BAT_CHARGE_CONTROL,
    PARAM_FUNC_BAT_DISCHARGE_CONTROL,
    PARAM_FUNC_BATTERY_BACKUP_CTRL,
    PARAM_FUNC_CHARGE_LAST,
    PARAM_FUNC_EPS_EN,
    PARAM_FUNC_FEED_IN_GRID_EN,
    PARAM_FUNC_FORCED_CHG_EN,
    PARAM_FUNC_FORCED_DISCHG_EN,
    PARAM_FUNC_GREEN_EN,
    PARAM_FUNC_GRID_PEAK_SHAVING,
    PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
    PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
    PARAM_HOLD_CHARGE_CURRENT,
    PARAM_HOLD_CHG_POWER_PERCENT,
    PARAM_HOLD_DISCHARGE_CURRENT,
    PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
    PARAM_HOLD_FORCED_CHG_POWER,
    PARAM_HOLD_FORCED_DISCHG_POWER,
    PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT,
    PARAM_HOLD_OFFGRID_DISCHG_SOC,
    PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
    PARAM_HOLD_ONGRID_DISCHG_SOC,
    PARAM_HOLD_ONGRID_EOD_VOLTAGE,
    PARAM_HOLD_PV_INPUT_MODE,
    PARAM_HOLD_START_PV_VOLT,
    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT,
    PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT,
    REG_AC_CHARGE_END_VOLTAGE,
    REG_AC_CHARGE_START_VOLTAGE,
    REG_OFFGRID_EOD_VOLTAGE,
    REG_ONGRID_EOD_VOLTAGE,
    REG_SYSTEM_CHARGE_VOLT_LIMIT,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _BATTERY_BANK_BMS_PERMISSION_FIELDS,
    _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
    _BATTERY_BANK_FIELDS,
    _BATTERY_BANK_LOCAL_REGISTER_FIELDS,
    _build_energy_sensor_mapping,
    _build_gridboss_sensor_mapping,
    _build_individual_battery_mapping,
    _build_runtime_sensor_mapping,
)
from custom_components.eg4_web_monitor.coordinator_mixins import (
    _ENERGY_OVERLAY,
    _TRANSPORT_OVERLAY,
    DeviceProcessingMixin,
)

# =========================================================================
# Tracing utilities
# =========================================================================


class _SourceToken(int):
    """Identity-preserving int token carrying the attribute name it came from.

    An int subclass survives the arithmetic the mapping functions apply
    (``int()``, ``float()``, ``or``-defaults, comparisons); any operation
    that combines tokens produces a plain int/float, which the tracer reports
    as a DERIVED (multi-source) value.
    """

    attr: str


class _RecordingData:
    """Stub data object: every attribute read returns a fresh _SourceToken."""

    def __init__(self, none_attrs: frozenset[str] = frozenset()) -> None:
        object.__setattr__(self, "_none_attrs", none_attrs)
        object.__setattr__(self, "_count", 0)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self._none_attrs:
            return None
        count = object.__getattribute__(self, "_count")
        object.__setattr__(self, "_count", count + 1)
        # Positive, >0 values so ``or``-fallbacks and >0 guards keep tokens.
        token = _SourceToken(1_000_000 + count)
        token.attr = name
        return token


#: Sentinel attr value for sensor keys whose value is computed from multiple
#: sources (or constants) rather than read from a single dataclass attribute.
DERIVED = "<derived>"


def _trace_sensor_mapping(
    build_fn: Callable[[Any], dict[str, Any]],
    none_attrs: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Run a coordinator mapping function against a recording stub.

    Returns the REAL ``{sensor_key: dataclass_attr}`` map the function
    implements; computed values (timestamps, sums, balances) map to DERIVED.
    """
    result = build_fn(_RecordingData(none_attrs))
    return {
        key: value.attr if isinstance(value, _SourceToken) else DERIVED
        for key, value in result.items()
    }


class _AccessLog:
    """Mutable access log shared by the logging stubs below."""

    def __init__(self) -> None:
        self.reads: list[str] = []


class _LoggingData:
    """Stub data object that records reads AND returns int tokens."""

    def __init__(self, log: _AccessLog) -> None:
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_count", 0)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        self._log.reads.append(name)
        count = object.__getattribute__(self, "_count")
        object.__setattr__(self, "_count", count + 1)
        return _SourceToken(1_000_000 + count)


def _trace_inverter_property(prop: str) -> tuple[frozenset[str], frozenset[str]]:
    """Evaluate a BaseInverter property in transport-only and cloud-only mode.

    Returns ``(transport_reads, cloud_reads)`` — the dataclass attributes /
    cloud API fields the property actually consumed in each mode.  A property
    that raises in a mode (e.g. cloud-only data missing) reports an empty set
    for that mode.
    """
    results: list[frozenset[str]] = []
    for mode in ("transport", "cloud"):
        inverter = object.__new__(GenericInverter)
        log = _AccessLog()
        recorder = _LoggingData(log)
        inverter._transport_runtime = recorder if mode == "transport" else None
        inverter._transport_energy = recorder if mode == "transport" else None
        inverter._transport_battery = None
        inverter._runtime = recorder if mode == "cloud" else None
        inverter._energy = recorder if mode == "cloud" else None
        inverter._battery_bank = None
        inverter._transport = None
        inverter._features = None
        inverter._client = None
        inverter._model = "CONTRACT"
        inverter.serial_number = "CONTRACT"
        try:
            getattr(inverter, prop)
        except Exception:  # noqa: BLE001 - mode without data may legally raise
            results.append(frozenset())
            continue
        results.append(frozenset(log.reads))
    return results[0], results[1]


def _trace_battery_property(prop: str) -> tuple[frozenset[str], frozenset[str]]:
    """Evaluate a cloud Battery property in transport-only / cloud-only mode."""
    results: list[frozenset[str]] = []
    for mode in ("transport", "cloud"):
        battery = object.__new__(Battery)
        log = _AccessLog()
        recorder = _LoggingData(log)
        battery._transport_data = recorder if mode == "transport" else None
        battery._data = recorder if mode == "cloud" else None
        battery._battery_sn = "SN"
        battery._battery_index = 0
        battery.serial_number = "SN"
        battery._client = None
        battery._model = "CONTRACT"
        try:
            getattr(battery, prop)
        except Exception:  # noqa: BLE001 - mode without data may legally raise
            results.append(frozenset())
            continue
        results.append(frozenset(log.reads))
    return results[0], results[1]


# =========================================================================
# Canonical bridges: dataclass attr / cloud field  ->  canonical register
# =========================================================================

# Transport dataclass fields populated by special handling rather than a
# RUNTIME_FIELD entry (see InverterRuntimeData.from_modbus_registers).
_RUNTIME_SPECIAL_ATTR_CANONICAL: dict[str, str] = {
    "battery_soc": "soc_soh_packed",
    "battery_soh": "soc_soh_packed",
    "load_power": RUNTIME_LOAD_POWER_CANONICAL,  # legacy reg-27 alias
    "fault_code": "fault_code",
    "warning_code": "warning_code",
    "bms_allow_charge": "battery_status_inv",
    "bms_allow_discharge": "battery_status_inv",
    "bms_force_charge": "battery_status_inv",
    "parallel_master_slave": "parallel_config",
    "parallel_phase": "parallel_config",
    "parallel_number": "parallel_config",
}

# Transport dataclass fields computed inside from_modbus_registers (sums /
# derivations) — they have no single canonical register.
_RUNTIME_COMPUTED_ATTRS: frozenset[str] = frozenset(
    {
        "pv_total_power",
        "pv1_current",
        "pv2_current",
        "pv3_current",
        "pv4_current",
        "pv5_current",
        "pv6_current",
    }
)
_ENERGY_COMPUTED_ATTRS: frozenset[str] = frozenset(
    {"pv_energy_today", "pv_energy_total"}
)

# Cloud API fields the canonical input table does not pair with a register
# (packed / table gaps) — bridged explicitly so the cloud side still resolves.
_CLOUD_FIELD_SPECIAL_CANONICAL: dict[str, str] = {
    "soc": "soc_soh_packed",  # reg 5 packed; table carries cloud field None
    "pf": "power_factor",  # reg 19; table carries cloud field None
}


def _invert_field_map(field_map: dict[str, str | None]) -> dict[str, str]:
    """Invert canonical->attr, asserting the inversion is unambiguous."""
    inverted: dict[str, str] = {}
    for canonical, attr in field_map.items():
        if attr is None:
            continue
        assert attr not in inverted, (
            f"field mapping is not invertible: attr {attr!r} fed by both "
            f"{inverted[attr]!r} and {canonical!r} — extend the bridge"
        )
        inverted[attr] = canonical
    return inverted


# canonical register -> the single dataclass attr populated by special
# handling in from_modbus_registers (RUNTIME_FIELD maps these canonicals to
# None).  Only 1:1 bridge entries qualify as a Domain-1a expected attr —
# packed multi-attr specials (soc_soh_packed, parallel_config,
# battery_status_inv) are excluded because no single attr IS the register.
_RUNTIME_SPECIAL_CANONICAL_ATTR: dict[str, str] = {
    canonical: attr
    for attr, canonical in _RUNTIME_SPECIAL_ATTR_CANONICAL.items()
    if Counter(_RUNTIME_SPECIAL_ATTR_CANONICAL.values())[canonical] == 1
}


_RUNTIME_ATTR_TO_CANONICAL = {
    **_invert_field_map(RUNTIME_FIELD),
    **_RUNTIME_SPECIAL_ATTR_CANONICAL,
}
_ENERGY_ATTR_TO_CANONICAL = _invert_field_map(ENERGY_FIELD)
_BATTERY_ATTR_TO_CANONICAL = {
    **_invert_field_map(BATTERY_FIELD),
    # Packed / multi-register specials (see BatteryData.from_registers).
    "firmware_version": "battery_firmware_version",
    "serial_number": "battery_serial_number",
}


def _runtime_canonical(attr: str) -> str | None:
    """Resolve a runtime OR energy dataclass attr to its canonical register.

    Computed dataclass fields (pylxpweb derives them from several registers)
    resolve to a stable ``derived:`` pseudo-canonical instead of ``None`` —
    a path reading a derived value while another path reads a real register
    IS a divergence and must surface in the comparison rather than being
    silently skipped.
    """
    if attr in _RUNTIME_COMPUTED_ATTRS or attr in _ENERGY_COMPUTED_ATTRS:
        return f"derived:{attr}"
    return _RUNTIME_ATTR_TO_CANONICAL.get(attr) or _ENERGY_ATTR_TO_CANONICAL.get(attr)


def _cloud_canonical(field: str) -> str | None:
    """Resolve an inverter cloud API field to its canonical register."""
    if field in _CLOUD_FIELD_SPECIAL_CANONICAL:
        return _CLOUD_FIELD_SPECIAL_CANONICAL[field]
    reg = BY_CLOUD_FIELD.get(field)
    return reg.canonical_name if reg is not None else None


def _single(sources: frozenset[str]) -> str | None:
    """Return the sole element of a read-set, or None for 0/derived/multi."""
    return next(iter(sources)) if len(sources) == 1 else None


# Traced integration LOCAL maps (computed once at import; pure functions).
LOCAL_RUNTIME_MAP = _trace_sensor_mapping(_build_runtime_sensor_mapping)
LOCAL_ENERGY_MAP = _trace_sensor_mapping(_build_energy_sensor_mapping)
LOCAL_BATTERY_MAP = _trace_sensor_mapping(
    _build_individual_battery_mapping, none_attrs=frozenset({"last_seen"})
)
LOCAL_GRIDBOSS_MAP = _trace_sensor_mapping(_build_gridboss_sensor_mapping)

CLOUD_INVERTER_MAP = DeviceProcessingMixin._get_inverter_property_map()
CLOUD_BATTERY_MAP = DeviceProcessingMixin._get_battery_property_map()
CLOUD_MID_MAP = DeviceProcessingMixin._get_mid_device_property_map()
# Alias pairs applied after the main map: a dict keyed by property cannot
# express one property feeding two sensor keys (GridBOSS load_power ->
# consumption_power), so the cloud table is the main map PLUS these pairs.
CLOUD_MID_ALIAS_MAP = DeviceProcessingMixin._get_mid_device_property_aliases()

# sensor_key -> property (property maps are injective on values by design;
# verified by the explicit assertion below).
CLOUD_INVERTER_BY_KEY = {key: prop for prop, key in CLOUD_INVERTER_MAP.items()}
CLOUD_BATTERY_BY_KEY = {key: prop for prop, key in CLOUD_BATTERY_MAP.items()}
CLOUD_MID_BY_KEY = {
    key: prop for prop, key in (*CLOUD_MID_MAP.items(), *CLOUD_MID_ALIAS_MAP.items())
}


def test_property_maps_are_injective() -> None:
    """No two properties may feed the same sensor key (silent overwrite)."""
    for label, prop_pairs in (
        ("inverter", tuple(CLOUD_INVERTER_MAP.items())),
        ("battery", tuple(CLOUD_BATTERY_MAP.items())),
        ("mid_device", (*CLOUD_MID_MAP.items(), *CLOUD_MID_ALIAS_MAP.items())),
    ):
        seen: dict[str, str] = {}
        for prop, key in prop_pairs:
            assert key not in seen, (
                f"{label} property map: sensor key {key!r} fed by both "
                f"{seen[key]!r} and {prop!r} — last writer silently wins"
            )
            seen[key] = prop


# =========================================================================
# Domain 1a — inverter input registers: LOCAL mapping fidelity
# =========================================================================
#
# For every canonical inverter-input register that advertises an
# ha_sensor_key, the integration's LOCAL mapping must feed exactly that key
# from exactly the dataclass field pylxpweb assigns to the register.
# Registers that deliberately take another route are allowlisted with the
# route and citation; TODO(eg4-...) entries are real divergences found by
# this harness awaiting adjudication.

_RUNTIME_HA_KEY_EXCEPTIONS: dict[str, str] = {
    # reg 10: per-inverter battery charge power is not an HA sensor; bank
    # charge power flows through the battery-bank adapter tables instead.
    "charge_power": "bank-level only via _BATTERY_BANK_FIELDS adapter",
    # reg 17: surfaced as the rectifier_power sensor via the
    # inverter.rectifier_power device property on BOTH paths
    # (coordinator_local supplement + cloud property map) — see
    # docs/DATA_MAPPING.md "rectifier_power (Inverter)".
    "rectifier_power": "property-fed on both paths (rectifier_power sensor)",
    # reg 27: surfaced as grid_import_power via the inverter.power_to_user
    # device property on BOTH paths (docs/DATA_MAPPING.md "grid_import_power
    # (Inverter)") — not via the runtime table.
    "power_to_user": "property-fed on both paths (grid_import_power sensor)",
    # reg 96: battery_bank_count comes from BatteryBankData.battery_count via
    # the bank adapter (single source for LOCAL and CLOUD), not the runtime
    # table.
    "battery_parallel_count": "bank-level via _BATTERY_BANK_FIELDS adapter",
}

_ENERGY_HA_KEY_EXCEPTIONS: dict[str, str] = {
    # (empty) — regs 31/46 now advertise inverter_energy/inverter_energy_lifetime
    # (eg4-bc0) and regs 223-231 advertise pvN_yield/pvN_yield_lifetime
    # (eg4-6ag2), matching the LOCAL table exactly.
}


def _local_fidelity_offenders(
    categories: set[str],
    field_map: dict[str, str | None],
    local_map: dict[str, str],
    exceptions: dict[str, str],
    special_canonical_attr: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Compare canonical registers against the traced LOCAL mapping.

    ``special_canonical_attr`` supplies the expected attr for registers whose
    ``field_map`` entry is None because ``from_modbus_registers`` populates
    the dataclass field via special handling (e.g. the reg-60/62
    fault/warning merge) rather than the generic field-map loop.

    Returns (offenders, stale_exceptions).
    """
    offenders: list[str] = []
    stale: list[str] = []
    special = special_canonical_attr or {}
    for reg in INVERTER_INPUT_REGISTERS:
        if not reg.ha_sensor_key or reg.category.value not in categories:
            continue
        expected_attr = field_map.get(reg.canonical_name) or special.get(
            reg.canonical_name
        )
        actual_attr = local_map.get(reg.ha_sensor_key)
        matches = expected_attr is not None and actual_attr == expected_attr
        if reg.canonical_name in exceptions:
            if matches:
                stale.append(
                    f"{reg.canonical_name} (reg {reg.address}): LOCAL now maps "
                    f"{expected_attr!r} -> {reg.ha_sensor_key!r}; remove the "
                    f"exception entry"
                )
            continue
        if matches:
            continue
        offenders.append(
            f"{reg.canonical_name} (reg {reg.address}, ha={reg.ha_sensor_key}): "
            f"canonical dataclass field {expected_attr!r} but LOCAL mapping "
            f"feeds the key from {actual_attr!r} "
            f"(None = key absent from the LOCAL table)"
        )
    return offenders, stale


def test_local_runtime_mapping_follows_canonical_registers() -> None:
    """Every runtime register's ha_sensor_key is fed by its canonical field."""
    offenders, stale = _local_fidelity_offenders(
        set(RUNTIME_CATEGORIES),
        RUNTIME_FIELD,
        LOCAL_RUNTIME_MAP,
        _RUNTIME_HA_KEY_EXCEPTIONS,
        special_canonical_attr=_RUNTIME_SPECIAL_CANONICAL_ATTR,
    )
    assert not offenders, (
        "LOCAL runtime mapping diverges from canonical registers:\n  "
        + "\n  ".join(offenders)
    )
    assert not stale, "Stale _RUNTIME_HA_KEY_EXCEPTIONS:\n  " + "\n  ".join(stale)


def test_local_energy_mapping_follows_canonical_registers() -> None:
    """Every energy register's ha_sensor_key is fed by its canonical field."""
    offenders, stale = _local_fidelity_offenders(
        set(ENERGY_CATEGORIES),
        ENERGY_FIELD,
        LOCAL_ENERGY_MAP,
        _ENERGY_HA_KEY_EXCEPTIONS,
    )
    assert not offenders, (
        "LOCAL energy mapping diverges from canonical registers:\n  "
        + "\n  ".join(offenders)
    )
    assert not stale, "Stale _ENERGY_HA_KEY_EXCEPTIONS:\n  " + "\n  ".join(stale)


# =========================================================================
# Domain 1b — inverter sensor keys: LOCAL path vs CLOUD/HYBRID property map
# =========================================================================
#
# For every sensor key fed by BOTH paths, the canonical register behind each
# side must be the same.  Three sources are resolved per key:
#   local    — traced _build_runtime/_energy_sensor_mapping attr
#   hybrid   — the device property's transport-mode read (HYBRID behaviour)
#   cloud    — the device property's cloud-mode read (pure-CLOUD behaviour)

# Sensor keys whose paths intentionally (or knowingly) disagree.
KNOWN_INVERTER_KEY_DIVERGENCES: dict[str, str] = {
    # DELIBERATE: the cloud property reads Eload/todayUsage, and
    # _process_inverter_object OVERRIDES consumption with the energy balance
    # whenever transport data is present; LOCAL computes the energy balance
    # directly.  Eload understates whole-home consumption (grid-direct loads).
    # See docs/DATA_MAPPING.md "Consumption vs Load Energy" + memory
    # consumption-energy-sources.
    "consumption": "deliberate: cloud=Eload, overridden by energy balance",
    "consumption_lifetime": "deliberate: cloud=Eload, overridden by balance",
}

# Properties whose value is legitimately derived from multiple reads (no
# single canonical register on at least one path) — the per-key canonical
# comparison cannot apply.  Derivations are shared pylxpweb code, so the two
# paths cannot drift independently for these.
_DERIVED_INVERTER_PROPERTIES: frozenset[str] = frozenset(
    {
        "battery_power",  # charge−discharge / cloud batPower priority
        "consumption_power",  # energy balance (pylxpweb, both paths)
        "pv1_current",  # derived P/V (issue #243), both paths
        "pv2_current",
        "pv3_current",
        "pv4_current",
        "pv5_current",
        "pv6_current",
        "pv_total_power",  # computed sum on both paths
    }
)

# Properties with no canonical register backing (cloud metadata / flags).
_METADATA_INVERTER_PROPERTIES: frozenset[str] = frozenset(
    {
        "power_rating",
        "power_rating_text",
        "status_text",
        "has_data",
        "is_lost",
        "has_runtime_data",
        "ac_couple_power",  # cloud acCouplePower; transport field is
        # populated only via the canonical ac_couple_power register on LXP
        # Smart-load split (eg4-1d0 / GH #222): cloud smartLoadPower /
        # gridLoadPower only — NO register exists on the off-grid family
        # (18kPV firmware RE names input reg 232 but it is unvalidated on
        # EG4_OFFGRID hardware), so there is no canonical triangle to
        # compare.  The pylxpweb properties read the HTTP runtime even in
        # HYBRID by design (cloud-supplemental data).
        "smart_load_power",
        "grid_load_power",
    }
)


def test_inverter_triangle_exclusion_lists_are_current() -> None:
    """The derived/metadata exclusion lists stay tied to the property map.

    Coverage of the triangle test below is EXACTLY the property map minus
    these two lists, so the lists themselves must be kept honest: every
    excluded name must still be a property-map entry (no rot), the lists
    must not overlap, and growing either list is a conscious decision —
    bump the anchored count in the same change that classifies the new
    property, with a comment saying why it cannot be triangle-compared.
    """
    stale_exclusions = sorted(
        (_DERIVED_INVERTER_PROPERTIES | _METADATA_INVERTER_PROPERTIES)
        - set(CLOUD_INVERTER_MAP)
    )
    assert not stale_exclusions, (
        "Exclusion lists name properties no longer in the inverter property "
        "map — prune them:\n  " + "\n  ".join(stale_exclusions)
    )
    overlap = sorted(_DERIVED_INVERTER_PROPERTIES & _METADATA_INVERTER_PROPERTIES)
    assert not overlap, (
        "Property classified as BOTH derived and metadata: " + ", ".join(overlap)
    )
    # Anchored counts: 9 derived + 9 metadata = 18 excluded entries today.
    # A failure here means triangle coverage changed — verify the new
    # classification is correct, then update the anchor.
    assert len(_DERIVED_INVERTER_PROPERTIES) == 9, (
        f"derived exclusion list changed size "
        f"({len(_DERIVED_INVERTER_PROPERTIES)} != 9) — triangle coverage "
        f"shrinks/grows with it; re-verify and update this anchor"
    )
    assert len(_METADATA_INVERTER_PROPERTIES) == 9, (
        f"metadata exclusion list changed size "
        f"({len(_METADATA_INVERTER_PROPERTIES)} != 9) — triangle coverage "
        f"shrinks/grows with it; re-verify and update this anchor"
    )


def test_inverter_sensor_keys_same_canonical_on_all_paths() -> None:
    """LOCAL, HYBRID (property/transport) and CLOUD agree per sensor key.

    Coverage is exact: every property-map entry outside the two explicit
    exclusion lists MUST produce at least two resolvable paths and be
    compared — an entry silently falling out of comparison (bad trace,
    future multi-read property, bridge gap) fails loudly instead of
    shrinking coverage.
    """
    offenders: list[str] = []
    stale: list[str] = []
    under_resolved: list[str] = []
    compared_keys: set[str] = set()
    local_map = {**LOCAL_RUNTIME_MAP, **LOCAL_ENERGY_MAP}

    excluded_props = _DERIVED_INVERTER_PROPERTIES | _METADATA_INVERTER_PROPERTIES
    expected_keys = {
        key for prop, key in CLOUD_INVERTER_MAP.items() if prop not in excluded_props
    }

    for prop, key in CLOUD_INVERTER_MAP.items():
        if prop in excluded_props:
            continue
        transport_reads, cloud_reads = _trace_inverter_property(prop)

        transport_attr = _single(transport_reads)
        cloud_field = _single(cloud_reads)
        hybrid_canonical = (
            _runtime_canonical(transport_attr) if transport_attr else None
        )
        cloud_canonical = _cloud_canonical(cloud_field) if cloud_field else None

        local_attr = local_map.get(key)
        # DERIVED = the LOCAL table computes the value inline (energy balance,
        # sums).  Resolve it to a pseudo-canonical so a real-register feed on
        # another path is reported as the divergence it is.
        if local_attr == DERIVED:
            local_canonical: str | None = "derived:local-computation"
        elif local_attr:
            local_canonical = _runtime_canonical(local_attr)
        else:
            local_canonical = None

        resolved = {
            label: canonical
            for label, canonical in (
                ("local", local_canonical),
                ("hybrid", hybrid_canonical),
                ("cloud", cloud_canonical),
            )
            if canonical is not None
        }
        if len(resolved) < 2:
            # Coverage loss is a failure, not a skip: a key this harness can
            # no longer compare is a key whose divergence would go unnoticed.
            under_resolved.append(
                f"sensor {key!r} (property {prop!r}): only {len(resolved)} "
                f"resolvable path(s) {resolved or '{}'} — transport reads "
                f"{sorted(transport_reads) or 'none'}, cloud reads "
                f"{sorted(cloud_reads) or 'none'}, local attr {local_attr!r}. "
                f"Classify the property as derived/metadata with a comment, "
                f"or extend the canonical bridges"
            )
            continue
        compared_keys.add(key)

        diverges = len(set(resolved.values())) > 1
        if key in KNOWN_INVERTER_KEY_DIVERGENCES:
            if not diverges:
                stale.append(
                    f"{key}: all paths now agree on {set(resolved.values())}; "
                    f"remove from KNOWN_INVERTER_KEY_DIVERGENCES"
                )
            continue
        if diverges:
            detail = ", ".join(
                f"{label}={canonical}" for label, canonical in resolved.items()
            )
            offenders.append(
                f"sensor {key!r} (property {prop!r}): paths read different "
                f"canonical registers: {detail}"
            )

    assert not under_resolved, (
        "Triangle coverage silently lost for these keys:\n  "
        + "\n  ".join(under_resolved)
    )
    assert compared_keys == expected_keys, (
        "Triangle coverage drifted from the property map:\n  missing: "
        f"{sorted(expected_keys - compared_keys)}\n  unexpected: "
        f"{sorted(compared_keys - expected_keys)}"
    )
    assert not offenders, (
        "Sensor keys fed by DIFFERENT canonical registers per path "
        "(transport-path divergence):\n  " + "\n  ".join(offenders)
    )
    assert not stale, "Stale KNOWN_INVERTER_KEY_DIVERGENCES:\n  " + "\n  ".join(stale)


# Keys the LOCAL path feeds from a register that HAS a cloud API field, yet
# the cloud property map does not feed at all.
_LOCAL_ONLY_KEY_EXCEPTIONS: dict[str, str] = {
    # NOTE: grid_power needs no entry — LOCAL now computes it as
    # power_from_grid − power_to_grid (DERIVED), the same net-flow formula the
    # CLOUD path computes inline in _process_inverter_object (eg4-9wf).
    # DELIBERATE (#197): the cloud zeroes its reg-170 mirror for EG4_OFFGRID,
    # so load_power must come only from the local register (LOCAL table +
    # HYBRID _TRANSPORT_OVERLAY); a cloud property feed would publish zeros.
    "load_power": "deliberate (#197): cloud reg-170 mirror reads 0 on OFFGRID",
    # NOTE: load_energy/_lifetime need no entry here — Eload (regs 171/172)
    # has no cloud_api_field in the canonical table; the cloud feed happens
    # at the call site via getattr(inverter, "energy_today_usage").
    # NOTE: inverter_energy/_lifetime need no entry either — regs 31/46 carry
    # no cloud_api_field anymore (todayYielding/totalYielding are PV yield,
    # not Einv; eg4-bc0), so the keys are cloud-impossible by table.
    # DELIBERATE (#197): the eps_load_power_* aliases are populated by the
    # SHARED apply_eps_load_power_sensors() helper on BOTH paths (called
    # inside the LOCAL runtime table AND in _process_inverter_object), not by
    # the cloud property map — the helper exists precisely so the alias+sum
    # logic cannot drift between modes.
    "eps_load_power_l1": "deliberate (#197): shared helper feeds both paths",
    "eps_load_power_l2": "deliberate (#197): shared helper feeds both paths",
}


def test_local_only_inverter_keys_have_no_cloud_field() -> None:
    """A LOCAL-fed key missing from the cloud map must be cloud-impossible.

    If the canonical register behind a LOCAL-fed sensor key carries a
    cloud_api_field, the cloud path COULD feed the key; not doing so is
    either a documented decision (allowlist) or a forgotten cloud mapping —
    the GridBOSS-consumption_power class of bug.
    """
    offenders: list[str] = []
    stale_candidates = dict(_LOCAL_ONLY_KEY_EXCEPTIONS)
    local_map = {**LOCAL_RUNTIME_MAP, **LOCAL_ENERGY_MAP}

    for key, attr in local_map.items():
        # A key the cloud map now feeds (or a derived value) is no longer
        # "local-only": deliberately do NOT consume its allowlist entry, so
        # a fixed divergence fails below as STALE and the entry is removed.
        if attr == DERIVED or key in CLOUD_INVERTER_BY_KEY:
            continue
        canonical = _runtime_canonical(attr)
        if canonical is None:
            continue
        reg = next(
            (r for r in INVERTER_INPUT_REGISTERS if r.canonical_name == canonical),
            None,
        )
        if reg is None or reg.cloud_api_field is None:
            continue
        stale_candidates.pop(key, None)
        if key in _LOCAL_ONLY_KEY_EXCEPTIONS:
            continue
        offenders.append(
            f"sensor {key!r}: LOCAL feeds it from {canonical!r} (reg "
            f"{reg.address}) which has cloud field {reg.cloud_api_field!r}, "
            f"but the cloud property map never feeds the key — forgotten "
            f"cloud mapping or undocumented local-only decision"
        )

    assert not offenders, (
        "LOCAL-fed keys with an unexplained missing cloud feed:\n  "
        + "\n  ".join(offenders)
    )
    assert not stale_candidates, (
        "Stale _LOCAL_ONLY_KEY_EXCEPTIONS (no longer local-only or no longer "
        "cloud-capable):\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in stale_candidates.items())
    )


def test_transport_overlay_pairs_match_local_mapping() -> None:
    """HYBRID overlay tuples agree with the LOCAL table and the dataclasses.

    Each overlay pair (sensor_key, attr) must read a real dataclass field,
    and when the LOCAL table feeds the same key, it must use the SAME field —
    otherwise HYBRID and LOCAL would publish different registers under one
    sensor key.
    """
    runtime_fields = {f.name for f in dataclasses.fields(InverterRuntimeData)}
    energy_fields = {f.name for f in dataclasses.fields(InverterEnergyData)}
    offenders: list[str] = []

    for overlay, fields, local_map, label in (
        (_TRANSPORT_OVERLAY, runtime_fields, LOCAL_RUNTIME_MAP, "runtime"),
        (_ENERGY_OVERLAY, energy_fields, LOCAL_ENERGY_MAP, "energy"),
    ):
        for sensor_key, attr in overlay:
            if attr not in fields:
                offenders.append(
                    f"{label} overlay {sensor_key!r}: attr {attr!r} is not an "
                    f"Inverter{label.capitalize()}Data field"
                )
                continue
            local_attr = local_map.get(sensor_key)
            if local_attr is not None and local_attr != attr:
                offenders.append(
                    f"{label} overlay {sensor_key!r}: HYBRID overlays {attr!r} "
                    f"but the LOCAL table feeds the key from {local_attr!r}"
                )

    assert not offenders, (
        "HYBRID transport overlay drifted from the LOCAL mapping:\n  "
        + "\n  ".join(offenders)
    )


# =========================================================================
# Domain 2 — battery bank: canonical tables vs pylxpweb bank classes
# =========================================================================
#
# The bank tables in coordinator_mappings are already single-source for
# LOCAL+CLOUD; this guards their attribute names against pylxpweb renames on
# the TRANSPORT dataclass (test_register_contract.py guards the device class).


def test_battery_bank_tables_resolve_on_transport_dataclass() -> None:
    """Every bank table attr exists on BatteryBankData (fields/properties)."""
    bank_fields = {f.name for f in dataclasses.fields(BatteryBankData)}
    offenders = [
        f"{table_name}[{key!r}] -> {attr!r}"
        for table_name, table in (
            ("_BATTERY_BANK_FIELDS", _BATTERY_BANK_FIELDS),
            (
                "_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS",
                _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
            ),
            (
                "_BATTERY_BANK_LOCAL_REGISTER_FIELDS",
                _BATTERY_BANK_LOCAL_REGISTER_FIELDS,
            ),
        )
        for key, attr in table.items()
        if attr not in bank_fields and not hasattr(BatteryBankData, attr)
    ]
    # The power-calculation inputs and the BMS permission attrs are read by
    # the adapter outside the flat tables — same existence contract.
    offenders += [
        f"power-calc -> {attr!r}"
        for attr in ("charge_power", "discharge_power", "battery_power")
        if attr not in bank_fields and not hasattr(BatteryBankData, attr)
    ]
    offenders += [
        f"_BATTERY_BANK_BMS_PERMISSION_FIELDS[{key!r}] -> {attr!r}"
        for key, attr, _encode in _BATTERY_BANK_BMS_PERMISSION_FIELDS
        if attr not in bank_fields and not hasattr(BatteryBankData, attr)
    ]
    assert not offenders, (
        "Battery-bank table attrs missing from BatteryBankData (LOCAL path "
        "would publish None forever):\n  " + "\n  ".join(offenders)
    )


# =========================================================================
# Domain 3 — individual batteries: shared mapping on BOTH source classes
# =========================================================================

# Battery canonical registers handled by packed / multi-register specials
# (BATTERY_FIELD maps them to None but BatteryData still carries the field).
_BATTERY_SPECIAL_CANONICAL_ATTRS: dict[str, str] = {
    "battery_firmware_version": "firmware_version",
    "battery_serial_number": "serial_number",
}


def test_individual_battery_mapping_attrs_exist_on_both_classes() -> None:
    """_build_individual_battery_mapping reads attrs valid for BOTH sources.

    The function receives transport BatteryData (LOCAL + HYBRID overlay) AND
    cloud Battery device objects (HYBRID cloud baseline,
    coordinator_http.py).  An attr existing on only one class crashes or
    silently None-fills the other path.
    """
    battery_fields = {f.name for f in dataclasses.fields(BatteryData)}
    # Instance-level stub: Battery sets serial_number etc. in __init__, so
    # class-level hasattr alone under-reports what instances expose.
    cloud_stub = object.__new__(Battery)
    cloud_stub._transport_data = None
    cloud_stub._data = None
    cloud_stub._battery_sn = "SN"
    cloud_stub._battery_index = 0
    cloud_stub.serial_number = "SN"
    cloud_stub._client = None
    cloud_stub._model = "CONTRACT"

    offenders: list[str] = []
    for key, attr in LOCAL_BATTERY_MAP.items():
        if attr == DERIVED:
            continue
        missing = []
        if attr not in battery_fields and not hasattr(BatteryData, attr):
            missing.append("BatteryData")
        if not hasattr(type(cloud_stub), attr) and not hasattr(cloud_stub, attr):
            missing.append("Battery")
        if missing:
            offenders.append(f"{key!r} <- {attr!r} missing on {', '.join(missing)}")
    assert not offenders, (
        "_build_individual_battery_mapping attrs missing on a source class "
        "(HYBRID feeds it both BatteryData and Battery):\n  " + "\n  ".join(offenders)
    )


def test_local_battery_mapping_follows_canonical_registers() -> None:
    """Every battery register's ha_sensor_key is fed by its canonical field."""
    offenders: list[str] = []
    for reg in BATTERY_REGISTERS:
        if not reg.ha_sensor_key:
            continue
        expected_attr = BATTERY_FIELD.get(reg.canonical_name)
        if expected_attr is None:
            expected_attr = _BATTERY_SPECIAL_CANONICAL_ATTRS.get(reg.canonical_name)
        actual_attr = LOCAL_BATTERY_MAP.get(reg.ha_sensor_key)
        if expected_attr is None:
            offenders.append(
                f"{reg.canonical_name}: no BATTERY_FIELD route and no special "
                f"route — extend _BATTERY_SPECIAL_CANONICAL_ATTRS"
            )
        elif actual_attr != expected_attr:
            offenders.append(
                f"{reg.canonical_name} (ha={reg.ha_sensor_key}): canonical "
                f"field {expected_attr!r} but LOCAL battery mapping feeds the "
                f"key from {actual_attr!r}"
            )
    assert not offenders, (
        "LOCAL battery mapping diverges from canonical registers:\n  "
        + "\n  ".join(offenders)
    )


# Cloud-only battery properties: no transport fallback inside the Battery
# class, so their sensor keys must never appear in the shared LOCAL mapping
# (they would crash/None-fill on BatteryData).
_CLOUD_ONLY_BATTERY_PROPERTIES: frozenset[str] = frozenset(
    {"mos_temp", "ambient_temp", "charge_capacity", "discharge_capacity", "bms_model"}
)

# Battery properties/metadata with no canonical register comparison.
_METADATA_BATTERY_PROPERTIES: frozenset[str] = frozenset(
    {"battery_sn", "battery_index", "model", "battery_type", "battery_type_text"}
)

# NOTE eg4-4yg: the max/min cell-NUMBER fields are being re-adjudicated in
# pylxpweb (crossed register decode on the local path).  At THIS layer the
# name chains are currently consistent (transport max_cell_num_temp ->
# canonical battery_max_cell_num_temp; cloud batMaxCellNumTemp -> same), so
# no allowlist entry is needed today.  If the pylxpweb fix renames or re-pairs
# those fields, this harness fails here — reconcile against the eg4-4yg
# branch outcome rather than papering over the failure.


def test_battery_property_map_same_canonical_on_both_paths() -> None:
    """Each cloud Battery property reads the same canonical register that the
    shared LOCAL mapping feeds into the same sensor key."""
    offenders: list[str] = []
    checked = 0
    for prop, key in CLOUD_BATTERY_MAP.items():
        if prop in _METADATA_BATTERY_PROPERTIES:
            continue
        transport_reads, cloud_reads = _trace_battery_property(prop)
        transport_attr = _single(transport_reads)
        cloud_field = _single(cloud_reads)

        canonicals: dict[str, str] = {}
        if transport_attr and transport_attr in _BATTERY_ATTR_TO_CANONICAL:
            canonicals["property-transport"] = _BATTERY_ATTR_TO_CANONICAL[
                transport_attr
            ]
        if cloud_field and cloud_field in BATTERY_BY_CLOUD_FIELD:
            canonicals["property-cloud"] = BATTERY_BY_CLOUD_FIELD[
                cloud_field
            ].canonical_name
        local_attr = LOCAL_BATTERY_MAP.get(key)
        if (
            local_attr
            and local_attr != DERIVED
            and local_attr in _BATTERY_ATTR_TO_CANONICAL
        ):
            canonicals["local-table"] = _BATTERY_ATTR_TO_CANONICAL[local_attr]

        if prop in _CLOUD_ONLY_BATTERY_PROPERTIES:
            if key in LOCAL_BATTERY_MAP:
                offenders.append(
                    f"{key!r}: cloud-only property {prop!r} but the key is "
                    f"also in the shared LOCAL mapping — would break on "
                    f"BatteryData"
                )
            continue
        if len(canonicals) < 2:
            continue
        checked += 1
        if len(set(canonicals.values())) > 1:
            detail = ", ".join(f"{src}={c}" for src, c in canonicals.items())
            offenders.append(
                f"sensor {key!r} (property {prop!r}): canonical register "
                f"disagreement: {detail}"
            )
    assert checked >= 15, f"vacuous run: only {checked} battery keys compared"
    assert not offenders, (
        "Battery sensor keys fed by different canonical registers per "
        "path:\n  " + "\n  ".join(offenders)
    )


# =========================================================================
# Domain GridBOSS — one MIDDevice, two tables, must be the same table
# =========================================================================
#
# LOCAL (coordinator_local._build_gridboss_sensor_mapping) and CLOUD/HYBRID
# (_get_mid_device_property_map) both read MIDDevice properties.  Any entry
# present in one table and absent from the other makes a sensor exist in one
# mode only.

KNOWN_GRIDBOSS_TABLE_DIVERGENCES: dict[str, str] = {
    # DELIBERATE: timestamp added at the call site on the HTTP path
    # (_process_mid_device_object) and inside the table on the LOCAL path.
    "midbox_last_polled": "deliberate: HTTP path stamps at call site",
}


def test_gridboss_local_and_cloud_tables_agree() -> None:
    """The LOCAL function and the CLOUD property map encode the same table."""
    offenders: list[str] = []
    stale: list[str] = []
    for key in sorted(set(LOCAL_GRIDBOSS_MAP) | set(CLOUD_MID_BY_KEY)):
        local_prop = LOCAL_GRIDBOSS_MAP.get(key)
        cloud_prop = CLOUD_MID_BY_KEY.get(key)
        matches = local_prop == cloud_prop
        if key in KNOWN_GRIDBOSS_TABLE_DIVERGENCES:
            if matches:
                stale.append(
                    f"{key}: both tables now read {local_prop!r}; remove from "
                    f"KNOWN_GRIDBOSS_TABLE_DIVERGENCES"
                )
            continue
        if matches:
            continue
        offenders.append(
            f"sensor {key!r}: LOCAL table reads {local_prop!r}, CLOUD table "
            f"reads {cloud_prop!r} (None = sensor missing on that path)"
        )
    assert not offenders, (
        "GridBOSS LOCAL and CLOUD tables drifted apart:\n  " + "\n  ".join(offenders)
    )
    assert not stale, "Stale KNOWN_GRIDBOSS_TABLE_DIVERGENCES:\n  " + "\n  ".join(stale)


def test_gridboss_properties_exist_on_mid_device() -> None:
    """Every property either table reads must exist on MIDDevice."""
    offenders = sorted(
        {
            prop
            for prop in (
                set(LOCAL_GRIDBOSS_MAP.values())
                | set(CLOUD_MID_MAP.keys())
                | set(CLOUD_MID_ALIAS_MAP.keys())
            )
            if prop != DERIVED and not hasattr(MIDDevice, prop)
        }
    )
    assert not offenders, (
        "GridBOSS tables read properties missing from MIDDevice:\n  "
        + "\n  ".join(offenders)
    )


def _trace_mid_property(prop: str) -> frozenset[str]:
    """Evaluate a MIDDevice property, logging MidboxRuntimeData field reads.

    GridBOSS has a SINGLE data model: ``_transport_runtime``
    (``MidboxRuntimeData``) is populated by both the Modbus transport and the
    HTTP parser, so one trace covers both modes.
    """
    mid = object.__new__(MIDDevice)
    log = _AccessLog()
    mid._transport_runtime = _LoggingData(log)
    mid._runtime = None
    mid._transport = None
    mid._client = None
    mid._model = "CONTRACT"
    mid.serial_number = "CONTRACT"
    try:
        getattr(mid, prop)
    except Exception:  # noqa: BLE001 - HTTP-metadata-only properties may raise
        return frozenset()
    return frozenset(log.reads)


_GRIDBOSS_FIELD_TO_CANONICAL = _invert_field_map(GRIDBOSS_FIELD)

# Canonical GridBOSS registers whose advertised ha_sensor_key the integration
# intentionally surfaces under a DIFFERENT key.
_GRIDBOSS_HA_KEY_EXCEPTIONS: dict[str, str] = {
    # Smart-port current sensors are created as smart_loadN_current_lX by
    # default and dynamically remapped to ac_coupleN_* per port mode by
    # _filter_unused_smart_port_sensors — the canonical port-neutral
    # smart_portN_current_lX key is never published directly (deliberate; see
    # the "Mapped as smart_load by default" comments in both tables).
    **{
        f"smart_port{port}_l{leg}_current": (
            "deliberate: surfaced as smart_loadN/ac_coupleN per port mode"
        )
        for port in range(1, 5)
        for leg in (1, 2)
    },
}


def test_gridboss_tables_match_canonical_ha_keys() -> None:
    """Each traced single-register GridBOSS table entry feeds the canonical
    register's advertised ha_sensor_key (or a documented exception)."""
    offenders: list[str] = []
    stale: list[str] = []
    checked = 0
    for key, prop in sorted(LOCAL_GRIDBOSS_MAP.items()):
        if prop == DERIVED:
            continue
        field = _single(_trace_mid_property(prop))
        canonical = _GRIDBOSS_FIELD_TO_CANONICAL.get(field) if field else None
        if canonical is None:
            continue  # aggregate/HTTP-metadata property — no single register
        reg = GRIDBOSS_BY_NAME[canonical]
        if not reg.ha_sensor_key:
            continue
        checked += 1
        matches = reg.ha_sensor_key == key
        if canonical in _GRIDBOSS_HA_KEY_EXCEPTIONS:
            if matches:
                stale.append(
                    f"{canonical}: integration now surfaces the canonical key "
                    f"{key!r}; remove from _GRIDBOSS_HA_KEY_EXCEPTIONS"
                )
            continue
        if not matches:
            offenders.append(
                f"{canonical} (reg {reg.address}): integration surfaces it as "
                f"{key!r} but the canonical table advertises "
                f"{reg.ha_sensor_key!r}"
            )
    assert checked >= 40, f"vacuous run: only {checked} GridBOSS keys compared"
    assert not offenders, (
        "GridBOSS keys drifted from canonical ha_sensor_keys:\n  "
        + "\n  ".join(offenders)
    )
    assert not stale, "Stale _GRIDBOSS_HA_KEY_EXCEPTIONS:\n  " + "\n  ".join(stale)


def test_gridboss_unsurfaced_canonical_keys_are_documented() -> None:
    """Canonical GridBOSS sensors the integration never feeds are exactly the
    documented aggregate-only / remapped sets — a NEW advertised register
    must be wired up or documented here.
    """
    # A register counts as SURFACED only when it is the single source of a
    # table entry (the sensor key publishes that register).  Registers that
    # aggregate properties merely consume (per-leg energy summed into the
    # aggregate keys) do not publish their advertised per-leg key.
    surfaced_canonicals: set[str] = set()
    for prop in (
        set(LOCAL_GRIDBOSS_MAP.values())
        | set(CLOUD_MID_MAP.keys())
        | set(CLOUD_MID_ALIAS_MAP.keys())
    ):
        if prop == DERIVED:
            continue
        field = _single(_trace_mid_property(prop))
        canonical = _GRIDBOSS_FIELD_TO_CANONICAL.get(field) if field else None
        if canonical is not None:
            surfaced_canonicals.add(canonical)

    # Per-leg energy registers: the integration surfaces aggregate energy
    # only — the L2 energy registers always read 0 on live hardware (see the
    # "aggregate only" comments in both tables), and the aggregate properties
    # consume the per-leg fields internally.
    documented_unsurfaced = {
        reg.canonical_name
        for reg in GRIDBOSS_REGISTERS
        if reg.ha_sensor_key
        and reg.category
        in (GridBossCategory.ENERGY_DAILY, GridBossCategory.ENERGY_LIFETIME)
        and reg.canonical_name.endswith(("_l1", "_l2"))
    }

    unsurfaced = {
        reg.canonical_name
        for reg in GRIDBOSS_REGISTERS
        if reg.ha_sensor_key and reg.canonical_name not in surfaced_canonicals
    }
    undocumented = sorted(unsurfaced - documented_unsurfaced)
    stale_docs = sorted(documented_unsurfaced - unsurfaced)
    assert not undocumented, (
        "Canonical GridBOSS sensors silently unsurfaced (wire them up or "
        "document the decision here):\n  " + "\n  ".join(undocumented)
    )
    assert not stale_docs, (
        "Documented-unsurfaced GridBOSS registers are now surfaced; prune "
        "the documentation set:\n  " + "\n  ".join(stale_docs)
    )


# =========================================================================
# Domain 4 — holding-register controls (number/switch/select entities)
# =========================================================================
#
# The integration addresses every control by pylxpweb parameter NAME; the
# register number lives in pylxpweb's canonical holding table (or, for a few
# cloud-aliased names, in the transport REGISTER_TO_PARAM_KEYS table).  This
# contract pins each control name to the documented (address, bit) so a
# remap on either side — the reg64-vs-reg74 class — fails loudly.

# name -> (holding register address, bit position | None)
# Sources: pylxpweb canonical holding table (verified entries) + the
# integration's own const/modbus.py documentation.  NOTE: the CLAUDE.md
# overview table still says "Off-Grid SOC Cutoff = reg 106"; the canonical,
# live-verified address for HOLD_SOC_LOW_LIMIT_EPS_DISCHG is 125.
_CONTROL_REGISTER_CONTRACT: dict[str, tuple[int, int | None]] = {
    PARAM_FUNC_EPS_EN: (21, 0),
    PARAM_FUNC_AC_CHARGE: (21, 7),
    "FUNC_SET_TO_STANDBY": (21, 9),  # select.py standby control
    PARAM_FUNC_FORCED_DISCHG_EN: (21, 10),
    PARAM_FUNC_FORCED_CHG_EN: (21, 11),
    # Grid Sell Back enable (GH #135): canonical reg 21 bit 15
    # (FUNC_FEED_IN_GRID_EN), live-verified.
    PARAM_FUNC_FEED_IN_GRID_EN: (21, 15),
    PARAM_FUNC_CHARGE_LAST: (110, 4),
    PARAM_FUNC_GREEN_EN: (110, 8),
    PARAM_FUNC_GRID_PEAK_SHAVING: (179, 7),
    PARAM_FUNC_BAT_CHARGE_CONTROL: (179, 9),
    PARAM_FUNC_BAT_DISCHARGE_CONTROL: (179, 10),
    # Reg 233 bit 1 is live-verified; known to BOTH pylxpweb tables (canonical
    # holding entry added in eg4-6ag2), so the inter-table check below covers it.
    PARAM_FUNC_BATTERY_BACKUP_CTRL: (233, 1),
    PARAM_HOLD_PV_INPUT_MODE: (20, None),
    PARAM_HOLD_START_PV_VOLT: (22, None),
    PARAM_HOLD_CHG_POWER_PERCENT: (64, None),
    PARAM_HOLD_AC_CHARGE_POWER: (66, None),
    PARAM_HOLD_AC_CHARGE_SOC_LIMIT: (67, None),
    # The reg64-vs-reg74 guard: PV/forced charge power is reg 74 (100 W
    # units), NOT the reg-64 percent command (see 3.3.0-beta.7 fix).
    PARAM_HOLD_FORCED_CHG_POWER: (74, None),
    # Forced discharge power/SOC (GH #207 / PR #249): reg 82 is 100W units
    # like reg 74 (hardware-verified: panel 2.5 kW -> raw 25), reg 83 is
    # percent; the inter-table check below verifies the pylxpweb
    # REGISTER_TO_PARAM_KEYS pairing added with this.
    PARAM_HOLD_FORCED_DISCHG_POWER: (82, None),
    PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT: (83, None),
    # Grid Sell Back power cap (GH #135): reg 103, whole percent.  Cloud key
    # live-pinned via single-register named reads (18kPV value 16,
    # FlexBOSS21 value 14, 2026-06-12); the cloud never returns the spec's
    # HOLD_MAX_BACKFLOW_POWER_PERCENT name on this hardware.
    PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT: (103, None),
    PARAM_HOLD_OFFGRID_EOD_VOLTAGE: (100, None),
    PARAM_HOLD_CHARGE_CURRENT: (101, None),
    PARAM_HOLD_DISCHARGE_CURRENT: (102, None),
    PARAM_HOLD_ONGRID_DISCHG_SOC: (105, None),
    # Canonical + live-verified: reg 125 (CLAUDE.md's overview table is stale
    # at 106).
    PARAM_HOLD_OFFGRID_DISCHG_SOC: (125, None),
    PARAM_HOLD_AC_CHARGE_START_VOLTAGE: (158, None),
    PARAM_HOLD_AC_CHARGE_END_VOLTAGE: (159, None),
    PARAM_HOLD_ONGRID_EOD_VOLTAGE: (169, None),
    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT: (227, None),
    PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT: (228, None),
}


def _resolve_param_in_pylxpweb(name: str) -> list[tuple[str, int, int | None]]:
    """Resolve a parameter name in BOTH pylxpweb tables.

    Returns a list of (source, address, bit_position) — one entry per table
    that knows the name.  Bitfield bit = list index in REGISTER_TO_PARAM_KEYS
    (1-bit fields; MULTI_BIT_FIELDS are midbox-only 2-bit fields).
    """
    resolutions: list[tuple[str, int, int | None]] = []
    canonical = HOLDING_BY_API_KEY.get(name)
    if canonical is not None:
        resolutions.append(("canonical", canonical.address, canonical.bit_position))
    for address, names in REGISTER_TO_PARAM_KEYS.items():
        if name in names:
            bit: int | None
            if len(names) == 1:
                bit = None  # value register
            elif name in MULTI_BIT_FIELDS:
                bit = MULTI_BIT_FIELDS[name][0]
            else:
                bit = names.index(name)
            resolutions.append(("transport", address, bit))
    return resolutions


def test_control_params_resolve_to_documented_registers() -> None:
    """Every control parameter name maps to its documented (address, bit) in
    pylxpweb, and pylxpweb's own tables agree with each other."""
    offenders: list[str] = []
    for name, (expected_addr, expected_bit) in _CONTROL_REGISTER_CONTRACT.items():
        resolutions = _resolve_param_in_pylxpweb(name)
        if not resolutions:
            offenders.append(
                f"{name}: unknown to BOTH pylxpweb tables (canonical holding "
                f"map and REGISTER_TO_PARAM_KEYS) — writes would fail"
            )
            continue
        for source, address, bit in resolutions:
            if (address, bit) != (expected_addr, expected_bit):
                offenders.append(
                    f"{name}: {source} table says reg {address} bit {bit}, "
                    f"contract says reg {expected_addr} bit {expected_bit} — "
                    f"the reg64-vs-reg74 failure class"
                )
    assert not offenders, (
        "Control parameter register contract violations:\n  " + "\n  ".join(offenders)
    )


# Cloud-only controls: function parameters whose local register/bit is
# UNPINNED — addressable only via the cloud functionControl endpoint, never
# via named-parameter register writes.  Each entry documents why; the honesty
# test below fails as STALE when an entry becomes locally resolvable, at
# which point it moves into _CONTROL_REGISTER_CONTRACT with its (addr, bit).
_CLOUD_ONLY_FUNCTION_PARAMS: dict[str, str] = {
    "FUNC_PV_SELL_TO_GRID_EN": (
        "Export PV Only (GH #135): confirmed IN the register-179 family via "
        "single-register named reads (18kPV + FlexBOSS21, 2026-06-12), but "
        "named responses are alphabetical so the bit position is unpinned"
    ),
}


def test_control_params_cover_all_integration_constants() -> None:
    """Every PARAM_* constant and FUNCTION_PARAM_MAPPING entry is contracted.

    A new control wired by name without a contract entry would silently
    bypass the register pinning above.  Cloud-only controls (register/bit
    unpinned) are carved out via _CLOUD_ONLY_FUNCTION_PARAMS, whose own
    honesty test keeps them honest.
    """
    from custom_components.eg4_web_monitor.const import modbus as modbus_const

    integration_params = {
        getattr(modbus_const, attr)
        for attr in dir(modbus_const)
        if attr.startswith("PARAM_")
    }
    integration_params |= set(FUNCTION_PARAM_MAPPING)
    missing = sorted(
        integration_params
        - set(_CONTROL_REGISTER_CONTRACT)
        - set(_CLOUD_ONLY_FUNCTION_PARAMS)
    )
    assert not missing, (
        "Control parameters without a register contract entry (add them to "
        "_CONTROL_REGISTER_CONTRACT with the documented address):\n  "
        + "\n  ".join(missing)
    )


def test_cloud_only_controls_stay_unpinned_and_unwired() -> None:
    """Cloud-only allowlist entries must stay honest.

    Each entry must (a) remain unknown to BOTH pylxpweb local tables — once
    a register/bit gets pinned the entry is STALE and the control moves into
    _CONTROL_REGISTER_CONTRACT — and (b) never be wired for local writes in
    switch._WORKING_MODE_PARAMETERS, which would write an unproven register.
    """
    from custom_components.eg4_web_monitor.switch import _WORKING_MODE_PARAMETERS

    offenders: list[str] = []
    for name in _CLOUD_ONLY_FUNCTION_PARAMS:
        resolutions = _resolve_param_in_pylxpweb(name)
        if resolutions:
            offenders.append(
                f"{name}: now resolvable in pylxpweb local tables "
                f"({resolutions}) — STALE: move it into "
                f"_CONTROL_REGISTER_CONTRACT with the pinned (addr, bit)"
            )
        if _WORKING_MODE_PARAMETERS.get(name):
            offenders.append(
                f"{name}: wired for local writes in _WORKING_MODE_PARAMETERS "
                f"but its register/bit is unpinned — local writes would hit "
                f"an unproven register"
            )
    assert not offenders, (
        "Cloud-only control allowlist violations:\n  " + "\n  ".join(offenders)
    )


def test_raw_register_constants_match_contract() -> None:
    """REG_* write addresses equal the contracted address of the same control.

    The cloud voltage-write path bypasses parameter names and writes raw
    addresses; if a REG_* constant and its PARAM_* name ever pointed at
    different registers, cloud and local writes would target different
    hardware registers.
    """
    pairs: Iterable[tuple[str, int, str]] = (
        (
            "REG_SYSTEM_CHARGE_VOLT_LIMIT",
            REG_SYSTEM_CHARGE_VOLT_LIMIT,
            PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT,
        ),
        (
            "REG_ONGRID_EOD_VOLTAGE",
            REG_ONGRID_EOD_VOLTAGE,
            PARAM_HOLD_ONGRID_EOD_VOLTAGE,
        ),
        (
            "REG_OFFGRID_EOD_VOLTAGE",
            REG_OFFGRID_EOD_VOLTAGE,
            PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
        ),
        (
            "REG_AC_CHARGE_START_VOLTAGE",
            REG_AC_CHARGE_START_VOLTAGE,
            PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
        ),
        (
            "REG_AC_CHARGE_END_VOLTAGE",
            REG_AC_CHARGE_END_VOLTAGE,
            PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
        ),
    )
    offenders = [
        f"{const_name}={address} but {param!r} is contracted to reg "
        f"{_CONTROL_REGISTER_CONTRACT[param][0]}"
        for const_name, address, param in pairs
        if address != _CONTROL_REGISTER_CONTRACT[param][0]
    ]
    assert not offenders, (
        "Raw register constants disagree with the parameter contract "
        "(cloud and local writes would hit different registers):\n  "
        + "\n  ".join(offenders)
    )


def test_writable_controls_are_writable_in_canonical_table() -> None:
    """Contracted controls known to the canonical table must be writable."""
    offenders = [
        f"{name}: canonical entry at reg {entry.address} is read-only"
        for name in _CONTROL_REGISTER_CONTRACT
        if (entry := HOLDING_BY_API_KEY.get(name)) is not None and not entry.writable
    ]
    assert not offenders, (
        "Controls writing read-only canonical registers:\n  " + "\n  ".join(offenders)
    )


# =========================================================================
# Allowlist honesty — TODO entries must stay real
# =========================================================================


def test_todo_divergences_are_inventoried() -> None:
    """Every TODO(eg4-...) allowlist entry is listed here with its bead ID.

    This is the single place to see all known-but-unadjudicated transport
    path divergences the harness has found, routed to the beads issue that
    owns each adjudication.  When one is fixed, its allowlist entry fails as
    STALE in the owning test; update this inventory in the same change.
    """
    todo_entries = {
        name: reason
        for table in (
            _RUNTIME_HA_KEY_EXCEPTIONS,
            _ENERGY_HA_KEY_EXCEPTIONS,
            KNOWN_INVERTER_KEY_DIVERGENCES,
            _LOCAL_ONLY_KEY_EXCEPTIONS,
            KNOWN_GRIDBOSS_TABLE_DIVERGENCES,
        )
        for name, reason in table.items()
        if reason.startswith("TODO(")
    }
    # entry name -> beads issue adjudicating it.  All 8 divergences found
    # by the harness on day one (eg4-1z8) are now fixed and their entries
    # retired: eg4-7uz, eg4-23a6 (2026-06-10) and eg4-9e4, eg4-9wf,
    # eg4-bc0, eg4-6ag2 (2026-06-11).  New TODO( entries in any allowlist
    # table must be inventoried here with their owning beads issue.
    expected: dict[str, str] = {}
    assert set(todo_entries) == set(expected), (
        "TODO divergence inventory drifted — update this test AND the owning "
        f"beads issue.\n  inventoried: {sorted(todo_entries)}\n  "
        f"expected: {sorted(expected)}"
    )
    misrouted: list[str] = []
    for name, reason in todo_entries.items():
        issue = expected[name]
        if not reason.startswith(f"TODO({issue})"):
            misrouted.append(
                f"{name}: tagged {reason.split(':', 1)[0]!r}, inventory "
                f"routes it to TODO({issue})"
            )
    assert not misrouted, (
        "TODO entries tagged with the wrong beads issue:\n  " + "\n  ".join(misrouted)
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
