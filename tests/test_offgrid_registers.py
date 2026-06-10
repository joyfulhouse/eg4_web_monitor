"""Confirmed EG4_OFFGRID registers (issue #197).

Live-validated on a 12000XP (EG4_OFFGRID, device type 54) via Modbus sweep +
cloud cross-reference (see GH issue #197 for the reporter's tables):

  * Input regs 129/130 — per-phase EPS load power (W, SCALE_NONE).  Zero when
    grid-tied, non-zero in EPS/discharge mode (L1=1031 / L2=296 vs cloud
    epsLoadPower=1338, 11 W timing skew).
  * Input reg 170 — load power (W, SCALE_NONE).  The 6kXP Modbus PDF labels it
    ``Pload``; valid grid-tied (3788 W) AND in EPS mode (1324 W).  The cloud
    zeroes its mirror field for EG4_OFFGRID, so the LOCAL register is the only
    trustworthy source — never the cloud.
  * Input reg 11 — battery discharge power (W, SCALE_NONE).  Already mapped in
    cloud as ``pDisCharge``; the LOCAL register agrees (1415 vs 1401, timing).

These tests pin the issue-#197 contract: sensor keys exist in SENSOR_TYPES and
the static key set, both data paths (LOCAL mapping + cloud/hybrid property map
or transport overlay) populate them, and entity creation is gated to the
EG4_OFFGRID family.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pylxpweb.transports.data import InverterRuntimeData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_LXP,
)
from custom_components.eg4_web_monitor.const.device_types import (
    OFFGRID_ONLY_SENSORS,
)
from custom_components.eg4_web_monitor.const.sensors.inverter import SENSOR_TYPES
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
    INVERTER_RUNTIME_KEYS,
    _build_runtime_sensor_mapping,
    apply_eps_load_power_sensors,
)
from custom_components.eg4_web_monitor.sensor import _should_create_sensor

from .conftest import make_real_inverter, make_transport_spec


@pytest.fixture
def mock_config_entry():
    """Cloud config entry (matches the test_coordinator.py fixture shape)."""
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="offgrid_197_test",
    )


# The five sensor keys introduced/enabled by issue #197.
_NEW_KEYS = (
    "eps_load_power_l1",
    "eps_load_power_l2",
    "eps_load_power",
    "load_power",
    "battery_discharge_power",
)


# =========================================================================
# Sensor definitions and static key sets
# =========================================================================


class TestSensorDefinitions:
    """SENSOR_TYPES and static key-set membership for the #197 keys."""

    @pytest.mark.parametrize("key", _NEW_KEYS)
    def test_sensor_types_defined_as_power(self, key: str) -> None:
        """Every #197 key is a W power measurement sensor."""
        assert key in SENSOR_TYPES, f"{key} missing from SENSOR_TYPES"
        assert SENSOR_TYPES[key]["device_class"] == "power"
        assert SENSOR_TYPES[key]["state_class"] == "measurement"
        assert SENSOR_TYPES[key]["unit"] == "W"

    @pytest.mark.parametrize("key", _NEW_KEYS)
    def test_keys_in_static_sets(self, key: str) -> None:
        """#197 keys are in the static key sets (zero-read first refresh)."""
        assert key in INVERTER_RUNTIME_KEYS, f"{key} missing from runtime keys"
        assert key in ALL_INVERTER_SENSOR_KEYS, f"{key} missing from static set"

    def test_offgrid_only_set_matches_issue_scope(self) -> None:
        """OFFGRID_ONLY_SENSORS is exactly the #197 key set (drift guard)."""
        assert OFFGRID_ONLY_SENSORS == frozenset(_NEW_KEYS)


# =========================================================================
# EG4_OFFGRID family gating
# =========================================================================


class TestOffgridGating:
    """#197 sensors are created for EG4_OFFGRID only."""

    @pytest.mark.parametrize("key", _NEW_KEYS)
    def test_created_for_offgrid(self, key: str) -> None:
        features = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}
        assert _should_create_sensor(key, features) is True

    @pytest.mark.parametrize("key", _NEW_KEYS)
    @pytest.mark.parametrize(
        "family", [INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP]
    )
    def test_not_created_for_other_families(self, key: str, family: str) -> None:
        features = {"inverter_family": family}
        assert _should_create_sensor(key, features) is False

    @pytest.mark.parametrize("key", _NEW_KEYS)
    def test_no_features_is_conservative(self, key: str) -> None:
        """No detected features → create (matches existing fallback policy)."""
        assert _should_create_sensor(key, None) is True
        assert _should_create_sensor(key, {}) is True

    def test_gridboss_load_power_unaffected(self) -> None:
        """GridBOSS devices carry no inverter features — their existing
        load_power entity (CT measurement) must keep being created."""
        assert _should_create_sensor("load_power", None) is True


# =========================================================================
# LOCAL mapping (Modbus registers → sensor keys)
# =========================================================================


class TestLocalRuntimeMapping:
    """_build_runtime_sensor_mapping carries the #197 register values."""

    def test_eps_load_power_per_leg_and_sum(self) -> None:
        """Regs 129/130 → eps_load_power_l1/_l2 + L1+L2 sum.

        Values from the reporter's EPS-discharge sweep: L1=1031, L2=296,
        sum=1327 (cloud epsLoadPower read 1338 — 11 W timing skew).
        """
        runtime = InverterRuntimeData(eps_l1_power=1031, eps_l2_power=296)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["eps_load_power_l1"] == 1031
        assert mapping["eps_load_power_l2"] == 296
        assert mapping["eps_load_power"] == 1327

    def test_eps_load_power_sum_none_semantics(self) -> None:
        """Both legs None → sum None; a single leg carries the sum."""
        empty = _build_runtime_sensor_mapping(InverterRuntimeData())
        assert empty["eps_load_power_l1"] is None
        assert empty["eps_load_power_l2"] is None
        assert empty["eps_load_power"] is None

        l1_only = _build_runtime_sensor_mapping(InverterRuntimeData(eps_l1_power=1031))
        assert l1_only["eps_load_power"] == 1031

    def test_eps_load_power_zero_when_grid_tied(self) -> None:
        """Grid-tied: regs 129/130 read 0 — the sum is 0, not None."""
        runtime = InverterRuntimeData(eps_l1_power=0, eps_l2_power=0)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["eps_load_power"] == 0

    def test_load_power_from_reg_170(self) -> None:
        """Reg 170 (output_power field) feeds load_power — grid-tied 3788 W."""
        runtime = InverterRuntimeData(output_power=3788.0)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["load_power"] == 3788.0
        # output_power keeps its own sensor (split-phase total) unchanged.
        assert mapping["output_power"] == 3788.0

    def test_battery_discharge_power_from_reg_11(self) -> None:
        """Reg 11 feeds battery_discharge_power — EPS discharge 1415 W."""
        runtime = InverterRuntimeData(battery_discharge_power=1415.0)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["battery_discharge_power"] == 1415.0


# =========================================================================
# Cloud / hybrid path
# =========================================================================


class TestCloudHybridPath:
    """Property map, EPS alias helper, and the hybrid transport overlay."""

    def test_battery_discharge_power_in_property_map(self) -> None:
        """CLOUD maps the pylxpweb battery_discharge_power property
        (cloud pDisCharge / transport reg 11)."""
        property_map = EG4DataUpdateCoordinator._get_inverter_property_map()
        assert property_map.get("battery_discharge_power") == (
            "battery_discharge_power"
        )

    def test_load_power_not_in_property_map(self) -> None:
        """load_power must NOT come from cloud properties: the cloud zeroes
        its reg-170 mirror for EG4_OFFGRID, and the pylxpweb ``load_power``
        property is reg 27 (grid import) — both wrong sources."""
        property_map = EG4DataUpdateCoordinator._get_inverter_property_map()
        assert "load_power" not in property_map
        assert "load_power" not in property_map.values()

    def test_apply_eps_load_power_sensors_aliases_and_sums(self) -> None:
        sensors = {"eps_power_l1": 1031, "eps_power_l2": 296}
        apply_eps_load_power_sensors(sensors)
        assert sensors["eps_load_power_l1"] == 1031
        assert sensors["eps_load_power_l2"] == 296
        assert sensors["eps_load_power"] == 1327

    def test_apply_eps_load_power_sensors_none_semantics(self) -> None:
        sensors: dict[str, object] = {}
        apply_eps_load_power_sensors(sensors)
        assert sensors["eps_load_power_l1"] is None
        assert sensors["eps_load_power_l2"] is None
        assert sensors["eps_load_power"] is None

    async def test_hybrid_overlay_populates_offgrid_sensors(
        self, hass, mock_config_entry
    ) -> None:
        """HYBRID trusts the local registers: reg 170 → load_power via the
        transport overlay, regs 129/130 → eps_load_power_* via the property
        map alias, reg 11 → battery_discharge_power via the property map."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(
            output_power=1324.0,
            eps_l1_power=1031,
            eps_l2_power=296,
            battery_discharge_power=1415.0,
        )
        inverter = make_real_inverter("1111111111", "12000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["load_power"] == 1324.0
        assert sensors["eps_load_power_l1"] == 1031
        assert sensors["eps_load_power_l2"] == 296
        assert sensors["eps_load_power"] == 1327
        assert sensors["battery_discharge_power"] == 1415

    async def test_pure_cloud_has_no_load_power(self, hass, mock_config_entry) -> None:
        """No transport → no load_power key (cloud zero is never trusted)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()

        result = await coordinator._process_inverter_object(inverter)
        assert "load_power" not in result["sensors"]


# =========================================================================
# Registry cleanup regression
# =========================================================================


class TestDeprecatedCleanupSuffixes:
    """battery_discharge_power was reintroduced for EG4_OFFGRID (#197) — the
    one-time consolidation cleanup must not delete the new entities."""

    def test_battery_discharge_power_not_in_cleanup(self) -> None:
        from custom_components.eg4_web_monitor import (
            _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES,
        )

        assert "_battery_discharge_power" not in (_DEPRECATED_CHARGE_DISCHARGE_SUFFIXES)

    def test_other_deprecated_suffixes_still_cleaned(self) -> None:
        from custom_components.eg4_web_monitor import (
            _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES,
        )

        # The bank/parallel split sensors stay consolidated (and deleted).
        for suffix in (
            "_battery_charge_power",
            "_battery_bank_charge_power",
            "_battery_bank_discharge_power",
            "_parallel_battery_charge_power",
            "_parallel_battery_discharge_power",
            "_battery_discharge_rate",
        ):
            assert suffix in _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES, suffix

    def test_parallel_suffix_does_not_match_new_unique_ids(self) -> None:
        """A new per-inverter unique_id must not be caught by the remaining
        suffixes (only the parallel/bank variants may match those)."""
        from custom_components.eg4_web_monitor import (
            _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES,
        )

        new_uid = "1111111111_runtime_battery_discharge_power"
        assert not any(
            new_uid.endswith(suffix) for suffix in _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES
        )
