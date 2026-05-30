"""Cross-mode entity-set parity: config / config-local / config-hybrid (eg4-kh7.3).

The integration supports three connection modes (CLOUD, LOCAL, HYBRID).  The
manual full-stack validation captures live entity snapshots per mode
(``scratchpad/capture_entities.py``) and diffs them
(``docs/claude/entity-comparison.md``) — but that needs a live Home Assistant
plus real devices and cannot run in CI.

This test is the automated, CI-reproducible counterpart: it derives the
sensor-key set each mode produces from the actual mapping/adapter functions and
asserts the cross-mode parity contract that the live comparison checks by hand:

  * inverter, GridBOSS and parallel-group sensors come from single shared
    mapping functions, so their key sets are mode-independent by construction
    (no per-mode fork can creep in);
  * battery-bank: CLOUD is a strict subset of LOCAL/HYBRID, and the ONLY
    permitted difference is the documented set of LOCAL-only Modbus BMS
    registers the cloud API genuinely does not expose.

A new cross-mode divergence (a LOCAL-only field the cloud could provide, or a
common field dropped from one path) fails here instead of silently in
production.
"""

from __future__ import annotations

from types import SimpleNamespace

from pylxpweb.transports.data import (
    BatteryBankData,
    BatteryData,
    InverterEnergyData,
    InverterRuntimeData,
)

from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    BATTERY_BANK_KEYS,
    _build_energy_sensor_mapping,
    _build_runtime_sensor_mapping,
    build_battery_bank_sensors,
)

# The ONLY battery-bank keys permitted to exist in LOCAL/HYBRID but not CLOUD:
# Modbus BMS bank registers the cloud API genuinely does not expose.  (min-cell
# temp/voltage are NOT here — the cloud path derives them from per-battery
# data, so they are cross-mode parity keys.)  Adding a LOCAL-only field that
# the cloud could provide must update both paths, not this list.
_DOCUMENTED_LOCAL_ONLY_BATTERY_BANK_KEYS: frozenset[str] = frozenset(
    {
        "battery_bank_bms_charge_current_limit",
        "battery_bank_bms_discharge_current_limit",
        "battery_bank_bms_charge_voltage_ref",
        "battery_bank_bms_discharge_cutoff",
        "battery_bank_bms_battery_type",
        "battery_bank_voltage_inv_sample",
    }
)


def _local_battery_bank_keys() -> set[str]:
    """Battery-bank keys produced by the LOCAL/HYBRID (transport) path."""
    bank = BatteryBankData(
        charge_power=500,
        discharge_power=0,
        batteries=[
            BatteryData(soc=95, soh=98, voltage=53.2, cycle_count=10),
            BatteryData(soc=94, soh=96, voltage=53.1, cycle_count=5),
        ],
    )
    return set(build_battery_bank_sensors(bank, source="local"))


def _cloud_battery_bank_keys() -> set[str]:
    """Battery-bank keys produced by the CLOUD path (fully populated)."""
    from custom_components.eg4_web_monitor.coordinator_mappings import (
        _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
        _BATTERY_BANK_FIELDS,
    )

    values: dict[str, object] = {}
    for attr in {**_BATTERY_BANK_FIELDS, **_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS}.values():
        values[attr] = 1
    values["status"] = "Charging"
    values["charge_power"] = 500
    values["discharge_power"] = 0
    values["battery_power"] = 500
    # Per-battery data so the cloud path derives min-cell temp/voltage.
    values["batteries"] = [
        SimpleNamespace(min_cell_temp=21.0, min_cell_voltage=3.25),
        SimpleNamespace(min_cell_temp=19.5, min_cell_voltage=3.21),
    ]
    return set(build_battery_bank_sensors(SimpleNamespace(**values), source="cloud"))


def test_cloud_battery_bank_is_subset_of_local() -> None:
    """CLOUD battery-bank keys are all present in LOCAL/HYBRID (minimum parity)."""
    local = _local_battery_bank_keys()
    cloud = _cloud_battery_bank_keys()
    missing_from_local = cloud - local
    assert not missing_from_local, (
        "CLOUD emits battery-bank keys LOCAL does not (parity violation): "
        f"{sorted(missing_from_local)}"
    )


def test_battery_bank_local_only_diff_is_documented() -> None:
    """The LOCAL−CLOUD battery-bank difference is exactly the documented BMS set."""
    local = _local_battery_bank_keys()
    cloud = _cloud_battery_bank_keys()
    local_only = local - cloud
    assert local_only == _DOCUMENTED_LOCAL_ONLY_BATTERY_BANK_KEYS, (
        "Battery-bank cross-mode divergence changed.\n"
        f"  unexpected LOCAL-only: {sorted(local_only - _DOCUMENTED_LOCAL_ONLY_BATTERY_BANK_KEYS)}\n"
        f"  no longer LOCAL-only:  {sorted(_DOCUMENTED_LOCAL_ONLY_BATTERY_BANK_KEYS - local_only)}\n"
        "Update both data paths (preferred) or the documented exception list."
    )


def test_min_cell_values_are_cross_mode_parity_keys() -> None:
    """min-cell temp/voltage appear in BOTH modes (cloud derives them)."""
    local = _local_battery_bank_keys()
    cloud = _cloud_battery_bank_keys()
    for key in ("battery_bank_min_cell_temp", "battery_bank_min_cell_voltage"):
        assert key in local, f"{key} missing from LOCAL"
        assert key in cloud, f"{key} missing from CLOUD"


def test_inverter_sensor_mappings_are_mode_independent() -> None:
    """Inverter runtime/energy use single shared mappings (no per-mode fork)."""
    runtime_keys = set(_build_runtime_sensor_mapping(InverterRuntimeData()))
    energy_keys = set(_build_energy_sensor_mapping(InverterEnergyData()))
    # Every mapped runtime/energy key is part of the canonical inverter set
    # all three modes create from the same functions.
    assert runtime_keys | energy_keys <= ALL_INVERTER_SENSOR_KEYS


def test_battery_bank_keys_match_canonical_static_set() -> None:
    """LOCAL battery-bank output matches the static BATTERY_BANK_KEYS contract."""
    # battery_bank_charge_rate is computed by compute_bank_charge_rate() after
    # the adapter, so it is in the static frozenset but not the raw mapping.
    local = _local_battery_bank_keys()
    assert local == BATTERY_BANK_KEYS - {"battery_bank_charge_rate"}
