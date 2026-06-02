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
        _BATTERY_BANK_BMS_PERMISSION_FIELDS,
        _BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
        _BATTERY_BANK_FIELDS,
    )

    values: dict[str, object] = {}
    for attr in {
        **_BATTERY_BANK_FIELDS,
        **_BATTERY_BANK_CAN_DIAGNOSTIC_FIELDS,
    }.values():
        values[attr] = 1
    # BMS permission/request flags (issue #232) are both-mode: the cloud
    # BatteryBank delegates them to its parent inverter, so expose them here.
    for _key, perm_attr, _encode in _BATTERY_BANK_BMS_PERMISSION_FIELDS:
        values[perm_attr] = True
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


def test_pv_current_wired_across_modes() -> None:
    """#243: derived PV current surfaces in every mode.

    No EG4 register or cloud field exposes PV current; pylxpweb derives it as
    power / voltage.  The integration must therefore carry pvN_current on the
    LOCAL runtime mapping, the cloud/hybrid property map, the static key set,
    and SENSOR_TYPES so all three connection modes create the sensors.
    """
    from custom_components.eg4_web_monitor.const.sensors.inverter import (
        SENSOR_TYPES,
    )
    from custom_components.eg4_web_monitor.coordinator import (
        EG4DataUpdateCoordinator,
    )

    runtime_keys = set(_build_runtime_sensor_mapping(InverterRuntimeData()))
    property_map = EG4DataUpdateCoordinator._get_inverter_property_map()

    for key in ("pv1_current", "pv2_current", "pv3_current"):
        assert key in runtime_keys, f"{key} missing from LOCAL runtime mapping"
        assert key in property_map, f"{key} missing from cloud/hybrid property map"
        assert key in ALL_INVERTER_SENSOR_KEYS, f"{key} missing from static key set"
        assert key in SENSOR_TYPES, f"{key} missing from SENSOR_TYPES"


def test_power_factor_wired_across_modes() -> None:
    """#243 follow-up: power factor surfaces in every mode.

    Power factor is dual-source — Modbus reg 19 (LOCAL, and HYBRID via the
    inverter property reading transport first) and the cloud ``pf`` field
    (CLOUD).  It must therefore be on the LOCAL runtime mapping, the
    cloud/hybrid property map, the static key set, and SENSOR_TYPES so all
    three connection modes create the sensor.
    """
    from custom_components.eg4_web_monitor.const.sensors.inverter import (
        SENSOR_TYPES,
    )
    from custom_components.eg4_web_monitor.coordinator import (
        EG4DataUpdateCoordinator,
    )

    runtime_keys = set(_build_runtime_sensor_mapping(InverterRuntimeData()))
    property_map = EG4DataUpdateCoordinator._get_inverter_property_map()

    assert "power_factor" in runtime_keys, "missing from LOCAL runtime mapping"
    assert "power_factor" in property_map, "missing from cloud/hybrid property map"
    assert "power_factor" in ALL_INVERTER_SENSOR_KEYS, "missing from static key set"
    assert "power_factor" in SENSOR_TYPES, "missing from SENSOR_TYPES"


def test_granular_energy_disabled_by_default_and_local_only() -> None:
    """#243: granular per-string/per-component energy is added register-backed,
    disabled-by-default (noise control), and LOCAL/HYBRID only.

    These come from Modbus regs 28-37/40+. The cloud energy endpoint returns
    only aggregates, so they must NOT be in the cloud inverter property map; and
    to avoid dashboard noise they ship disabled-by-default.
    """
    from custom_components.eg4_web_monitor.const.sensors.inverter import (
        SENSOR_TYPES,
    )
    from custom_components.eg4_web_monitor.coordinator import (
        EG4DataUpdateCoordinator,
    )
    from custom_components.eg4_web_monitor.sensor import _should_create_sensor

    granular = [
        "pv1_yield",
        "pv2_yield",
        "pv3_yield",
        "pv1_yield_lifetime",
        "pv2_yield_lifetime",
        "pv3_yield_lifetime",
        "inverter_energy",
        "inverter_energy_lifetime",
        "ac_charge_energy",
        "ac_charge_energy_lifetime",
        "eps_energy",
        "eps_energy_lifetime",
        "generator_energy",
        "generator_energy_lifetime",
    ]
    energy_keys = set(_build_energy_sensor_mapping(InverterEnergyData()))
    property_map = EG4DataUpdateCoordinator._get_inverter_property_map()

    for key in granular:
        assert key in SENSOR_TYPES, f"{key} missing from SENSOR_TYPES"
        assert SENSOR_TYPES[key].get("enabled_default") is False, (
            f"{key} must be disabled-by-default"
        )
        assert key in energy_keys, f"{key} missing from LOCAL energy mapping"
        assert key in ALL_INVERTER_SENSOR_KEYS, f"{key} missing from static set"
        assert key not in property_map, (
            f"{key} should be LOCAL/HYBRID only, not in the cloud property map"
        )

    # PV4-6 yield are gated by pv_string_count, like pv4-6 power/current.
    feats3 = {"pv_string_count": 3}
    assert _should_create_sensor("pv3_yield", feats3) is True
    assert _should_create_sensor("pv4_yield", feats3) is False
    assert _should_create_sensor("pv4_yield_lifetime", feats3) is False


def test_battery_bank_keys_match_canonical_static_set() -> None:
    """LOCAL battery-bank output matches the static BATTERY_BANK_KEYS contract."""
    # battery_bank_charge_rate is computed by compute_bank_charge_rate() after
    # the adapter, so it is in the static frozenset but not the raw mapping.
    local = _local_battery_bank_keys()
    assert local == BATTERY_BANK_KEYS - {"battery_bank_charge_rate"}
