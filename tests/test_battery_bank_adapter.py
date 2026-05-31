"""Unified battery-bank adapter: LOCAL/CLOUD parity contract (eg4-kh7.1).

``build_battery_bank_sensors()`` is the single canonical adapter both the
LOCAL (``BatteryBankData`` transport) and CLOUD (``BatteryBank`` device) paths
route through.  These tests lock the invariants that make the consolidation
durable and structurally cure the M2 "fix-one-miss-the-other" duplication:

* the cloud property map is DERIVED from the same canonical field tables, so
  it can never silently drift from the LOCAL sensor set;
* a field added to the common table surfaces in BOTH modes;
* the genuinely per-source behaviour (reversed power-calc priority, LOCAL-only
  BMS registers) is preserved exactly.
"""

from __future__ import annotations

from types import SimpleNamespace

from pylxpweb.transports.data import BatteryBankData, BatteryData

from custom_components.eg4_web_monitor.coordinator_mappings import (
    _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
    _BATTERY_BANK_FIELDS,
    _BATTERY_BANK_LOCAL_REGISTER_FIELDS,
    BATTERY_BANK_CORE_KEYS,
    _compute_bank_power,
    build_battery_bank_sensors,
    get_battery_bank_property_map,
)

_BMS_PERMISSION_KEYS = (
    "battery_bank_charge_allowed",
    "battery_bank_discharge_allowed",
    "battery_bank_force_charge",
)


def _make_local_bank() -> BatteryBankData:
    """LOCAL transport bank with two differing batteries so CAN deltas resolve."""
    return BatteryBankData(
        charge_power=500,
        discharge_power=0,
        batteries=[
            BatteryData(soc=95, soh=98, voltage=53.2, cycle_count=10),
            BatteryData(soc=94, soh=96, voltage=53.1, cycle_count=5),
        ],
    )


def _make_cloud_bank() -> SimpleNamespace:
    """Minimal cloud BatteryBank stand-in exposing the common attribute surface.

    Built programmatically from the canonical tables so that adding a field to
    ``_BATTERY_BANK_FIELDS`` automatically extends the fake — keeping the
    parity test honest as the tables evolve.
    """
    values: dict[str, object] = {}
    for attr in {
        **_BATTERY_BANK_FIELDS,
        **_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
    }.values():
        values[attr] = 1  # non-None sentinel
    values["status"] = "Charging"  # status is a string, not numeric
    values["charge_power"] = 500
    values["discharge_power"] = 0
    values["battery_power"] = 500
    values["batteries"] = []  # no per-battery data -> min_cell_* derivation omitted
    return SimpleNamespace(**values)


def test_cloud_property_map_derived_from_canonical_tables() -> None:
    """The cloud property map is exactly the inverted tables + power intermediates."""
    expected = {
        attr: key
        for key, attr in {
            **_BATTERY_BANK_FIELDS,
            **_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
        }.items()
    }
    expected["charge_power"] = "_battery_bank_charge_power"
    expected["discharge_power"] = "_battery_bank_discharge_power"
    expected["battery_power"] = "battery_bank_power"

    assert get_battery_bank_property_map() == expected


def test_common_fields_surface_in_both_modes() -> None:
    """Every canonical common/CAN/power key appears in BOTH LOCAL and CLOUD output."""
    local = build_battery_bank_sensors(_make_local_bank(), source="local")
    cloud = build_battery_bank_sensors(_make_cloud_bank(), source="cloud")

    common_keys = (
        set(_BATTERY_BANK_FIELDS)
        | set(_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS)
        | {"battery_bank_power", "battery_bank_last_polled", "battery_status"}
    )
    for key in common_keys:
        assert key in local, f"{key} missing from LOCAL output"
        assert key in cloud, f"{key} missing from CLOUD output"


def test_local_register_fields_are_local_only() -> None:
    """BMS register fields appear in LOCAL output but never on CLOUD."""
    local = build_battery_bank_sensors(_make_local_bank(), source="local")
    cloud = build_battery_bank_sensors(_make_cloud_bank(), source="cloud")

    for key in _BATTERY_BANK_LOCAL_REGISTER_FIELDS:
        assert key in local, f"{key} missing from LOCAL output"

    # The cloud BatteryBank object genuinely lacks BMS registers; with no
    # per-battery data the derived min-cell values are omitted too.
    for key in _BATTERY_BANK_LOCAL_REGISTER_FIELDS:
        assert key not in cloud, f"{key} unexpectedly present in CLOUD output"


def test_cloud_skips_none_local_writes_all() -> None:
    """CLOUD omits absent fields; LOCAL writes the key (incl. None) to keep it present."""
    # Cloud bank missing an optional field (min_soh) -> key absent.
    cloud_bank = _make_cloud_bank()
    cloud_bank.min_soh = None
    cloud = build_battery_bank_sensors(cloud_bank, source="cloud")
    assert "battery_bank_min_soh" not in cloud

    # LOCAL always emits the key even when the underlying value is None.
    local_bank = BatteryBankData()  # empty -> most fields None
    local = build_battery_bank_sensors(local_bank, source="local")
    assert "battery_bank_min_soh" in local


def test_cloud_treats_empty_string_as_no_data() -> None:
    """CLOUD treats "" like None (parity with _map_device_properties' != "" skip).

    Regression guard for the original generic mapper which skipped both None
    and empty strings.  Applies to the common loop, the CAN diagnostics, AND
    the battery_bank_power fallback.
    """
    bank = _make_cloud_bank()
    # battery_power == "" must NOT be written as ""; the power calc falls back
    # to charge - discharge instead.
    bank.battery_power = ""
    bank.charge_power = 600
    bank.discharge_power = 100
    # A CAN diagnostic of "" must be omitted (not emitted as "").
    bank.soc_delta = ""
    # A common field of "" must be omitted too.
    bank.min_soh = ""

    cloud = build_battery_bank_sensors(bank, source="cloud")

    assert cloud["battery_bank_power"] == 500  # charge - discharge fallback
    assert cloud["battery_bank_power"] != ""
    assert "battery_bank_soc_delta" not in cloud
    assert "battery_bank_min_soh" not in cloud


def test_power_priority_preserved_per_source() -> None:
    """LOCAL prefers charge−discharge; CLOUD prefers the authoritative API value."""
    # Divergent inputs: charge−discharge = 500 vs api battery_power = 999.
    assert _compute_bank_power(600, 100, 999, prefer_api=True) == 999  # cloud
    assert _compute_bank_power(600, 100, 999, prefer_api=False) == 500  # local

    # Each source falls back to the other source when its preference is missing.
    assert _compute_bank_power(None, None, 999, prefer_api=False) == 999
    assert _compute_bank_power(600, 100, None, prefer_api=True) == 500

    # Nothing computable -> None (LOCAL still writes the key; CLOUD omits it).
    assert _compute_bank_power(None, None, None, prefer_api=True) is None
    assert _compute_bank_power(None, None, None, prefer_api=False) is None


# ---------------------------------------------------------------------------
# BMS permission/request flags (reg 95 bitmap / cloud bmsCharge, issue #232)
# ---------------------------------------------------------------------------


def test_bms_permission_keys_are_core_keys() -> None:
    """The three flags are part of the static bank sensor set (every mode)."""
    for key in _BMS_PERMISSION_KEYS:
        assert key in BATTERY_BANK_CORE_KEYS


def test_bms_permission_local_enum_encoding() -> None:
    """LOCAL decodes BatteryBankData flags into enum states."""
    bank = BatteryBankData(allow_charge=True, allow_discharge=False, force_charge=True)
    local = build_battery_bank_sensors(bank, source="local")
    assert local["battery_bank_charge_allowed"] == "Allowed"
    assert local["battery_bank_discharge_allowed"] == "Blocked"
    assert local["battery_bank_force_charge"] == "Requested"


def test_bms_permission_local_writes_none_when_absent() -> None:
    """LOCAL writes the key (incl. None) so the entity stays present."""
    local = build_battery_bank_sensors(BatteryBankData(), source="local")
    for key in _BMS_PERMISSION_KEYS:
        assert key in local
        assert local[key] is None


def test_bms_permission_cloud_enum_encoding() -> None:
    """CLOUD reads the delegated flags off the BatteryBank object."""
    bank = _make_cloud_bank()
    bank.allow_charge = True
    bank.allow_discharge = True
    bank.force_charge = False
    cloud = build_battery_bank_sensors(bank, source="cloud")
    assert cloud["battery_bank_charge_allowed"] == "Allowed"
    assert cloud["battery_bank_discharge_allowed"] == "Allowed"
    assert cloud["battery_bank_force_charge"] == "Idle"


def test_bms_permission_cloud_skips_none() -> None:
    """CLOUD omits the keys when the parent inverter can't supply the flags."""
    bank = _make_cloud_bank()
    bank.allow_charge = None
    bank.allow_discharge = None
    bank.force_charge = None
    cloud = build_battery_bank_sensors(bank, source="cloud")
    for key in _BMS_PERMISSION_KEYS:
        assert key not in cloud
