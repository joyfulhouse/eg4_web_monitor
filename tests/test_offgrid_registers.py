"""Confirmed EG4_OFFGRID registers and the backup-output split (#197/#222/#335).

Live-validated on a 12000XP (EG4_OFFGRID, device type 54) via Modbus sweep +
cloud cross-reference (see GH issue #197 for the reporter's tables):

  * Input reg 170 — load power (W, SCALE_NONE).  The 6kXP Modbus PDF labels it
    ``Pload``; valid grid-tied (3788 W) AND in EPS mode (1324 W).  The cloud
    zeroes its mirror field for EG4_OFFGRID, so the LOCAL register is the only
    trustworthy source — never the cloud.
  * Input reg 11 — battery discharge power (W, SCALE_NONE).  Already mapped in
    cloud as ``pDisCharge``; the LOCAL register agrees (1415 vs 1401, timing).
  * Input regs 129/130 — per-leg COMBINED backup-path output (W, SCALE_NONE),
    the local mirror of cloud pEpsL1N/pEpsL2N → ``eps_power_l1/l2`` ONLY.

CORRECTED by #335: the former ``eps_load_power_l1/_l2`` sensors (#197) aliased
regs 129/130 and the L1+L2 sum masqueraded as ``eps_load_power`` — but those
values are the COMBINED backup output (smart load + EPS loads), so the
sensors duplicated ``eps_power_l1/l2`` exactly.  The #197 "sum 1327 ≈ cloud
epsLoadPower 1338" validation was a smart-load-idle coincidence (#222
evidence: GEN port active → L1+L2 3371 W = smartLoadPower 2999 +
epsLoadPower 365).  The per-leg keys are RETIRED (no per-leg EPS-loads
source exists) and ``eps_load_power`` now maps the real cloud
``epsLoadPower`` field — CLOUD-ONLY like its #222 siblings
smart_load_power/grid_load_power, pending a pylxpweb ``eps_load_power``
property (absent until then).

These tests pin that contract: sensor keys in SENSOR_TYPES and the static
key sets, both data paths, EG4_OFFGRID entity gating, and the retirement of
the fabricated per-leg keys.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pylxpweb.devices.inverters._features import InverterFamily, InverterFeatures
from pylxpweb.models import InverterRuntime
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
    drop_offgrid_cloud_output_power,
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


# The LOCAL-register-backed keys introduced by issue #197 (regs 170 / 11).
_LOCAL_KEYS = (
    "load_power",
    "battery_discharge_power",
)

# The CLOUD-ONLY backup-output split keys (#222/#335: consumption =
# epsLoadPower + smartLoadPower + gridLoadPower on this family).  These have
# NO validated local register source, so they are deliberately absent from
# the LOCAL static key sets and flow exclusively through the HTTP property
# map.  eps_load_power additionally awaits a pylxpweb ``eps_load_power``
# property — the map entry resolves to None (key absent) until it ships.
_CLOUD_ONLY_KEYS = (
    "smart_load_power",
    "grid_load_power",
    "eps_load_power",
)

# Retired by #335: fabricated aliases of eps_power_l1/l2 (regs 129/130 /
# cloud pEpsL1N/L2N carry the COMBINED backup output — no per-leg source
# for the EPS-loads subset exists on any path).
_RETIRED_KEYS = (
    "eps_load_power_l1",
    "eps_load_power_l2",
)

# The #222 GEN-port subset of _CLOUD_ONLY_KEYS whose pylxpweb properties
# already SHIPPED (eps_load_power's is still pending, #335) — used by the
# TestSmartLoadSensors specifics below.
_SMART_LOAD_KEYS = (
    "smart_load_power",
    "grid_load_power",
)


# =========================================================================
# Sensor definitions and static key sets
# =========================================================================


class TestSensorDefinitions:
    """SENSOR_TYPES and static key-set membership for the offgrid keys."""

    @pytest.mark.parametrize("key", _LOCAL_KEYS + _CLOUD_ONLY_KEYS)
    def test_sensor_types_defined_as_power(self, key: str) -> None:
        """Every surviving offgrid key is a W power measurement sensor."""
        assert key in SENSOR_TYPES, f"{key} missing from SENSOR_TYPES"
        assert SENSOR_TYPES[key]["device_class"] == "power"
        assert SENSOR_TYPES[key]["state_class"] == "measurement"
        assert SENSOR_TYPES[key]["unit"] == "W"

    @pytest.mark.parametrize("key", _LOCAL_KEYS)
    def test_local_keys_in_static_sets(self, key: str) -> None:
        """Register-backed keys are in the static sets (zero-read refresh)."""
        assert key in INVERTER_RUNTIME_KEYS, f"{key} missing from runtime keys"
        assert key in ALL_INVERTER_SENSOR_KEYS, f"{key} missing from static set"

    @pytest.mark.parametrize("key", _CLOUD_ONLY_KEYS + _RETIRED_KEYS)
    def test_cloud_only_and_retired_keys_not_in_static_sets(self, key: str) -> None:
        """Cloud-only + retired keys must NOT be statically created in LOCAL.

        There is no local source for any of them; pre-creating the entities
        would leave them permanently unknown in pure-LOCAL mode (#335).
        """
        assert key not in INVERTER_RUNTIME_KEYS, f"{key} leaked into runtime keys"
        assert key not in ALL_INVERTER_SENSOR_KEYS, f"{key} leaked into static set"

    @pytest.mark.parametrize("key", _RETIRED_KEYS)
    def test_retired_keys_fully_removed(self, key: str) -> None:
        """The fabricated per-leg keys are gone from every creation surface
        and their orphaned registry entries are covered by the setup purge
        (#335)."""
        from custom_components.eg4_web_monitor import (
            _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES,
        )

        assert key not in SENSOR_TYPES
        property_map = EG4DataUpdateCoordinator._get_inverter_property_map()
        assert key not in property_map.values()
        assert f"_{key}" in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES

    def test_offgrid_only_set_matches_issue_scope(self) -> None:
        """OFFGRID_ONLY_SENSORS is exactly the surviving key set (drift guard)."""
        assert OFFGRID_ONLY_SENSORS == frozenset(_LOCAL_KEYS) | frozenset(
            _CLOUD_ONLY_KEYS
        )


# =========================================================================
# EG4_OFFGRID family gating
# =========================================================================


class TestOffgridGating:
    """Offgrid-only sensors are created for EG4_OFFGRID only."""

    @pytest.mark.parametrize("key", _LOCAL_KEYS + _CLOUD_ONLY_KEYS)
    def test_created_for_offgrid(self, key: str) -> None:
        features = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}
        assert _should_create_sensor(key, features) is True

    @pytest.mark.parametrize("key", _LOCAL_KEYS + _CLOUD_ONLY_KEYS)
    @pytest.mark.parametrize(
        "family", [INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP]
    )
    def test_not_created_for_other_families(self, key: str, family: str) -> None:
        features = {"inverter_family": family}
        assert _should_create_sensor(key, features) is False

    @pytest.mark.parametrize("key", _LOCAL_KEYS + _CLOUD_ONLY_KEYS)
    def test_no_features_is_fail_closed(self, key: str) -> None:
        """No detected features → DO NOT create (review: fail-closed).

        Failed feature detection / legacy configs without family metadata
        previously leaked the OFFGRID-only set onto EG4_HYBRID/LXP installs
        via the create-all fallback — especially risky because the hybrid
        transport overlay writes load_power for any transport-backed device.
        """
        assert _should_create_sensor(key, None) is False
        assert _should_create_sensor(key, {}) is False

    def test_gridboss_load_power_unaffected(self) -> None:
        """GridBOSS / parallel-group devices carry no inverter features —
        their existing load_power entity (CT measurement) must keep being
        created via the device_type bypass."""
        assert _should_create_sensor("load_power", None, "gridboss") is True
        assert _should_create_sensor("load_power", {}, "gridboss") is True
        assert _should_create_sensor("load_power", None, "parallel_group") is True

    def test_static_path_gating_offgrid_vs_hybrid(self) -> None:
        """Static-config features gate the offgrid keys per family (review F5)."""
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            _features_from_family,
        )

        offgrid = _features_from_family("EG4_OFFGRID", None)
        hybrid = _features_from_family("EG4_HYBRID", None)
        for key in _LOCAL_KEYS + _CLOUD_ONLY_KEYS:
            assert _should_create_sensor(key, offgrid) is True
            assert _should_create_sensor(key, hybrid) is False


# =========================================================================
# LOCAL mapping (Modbus registers → sensor keys)
# =========================================================================


class TestLocalRuntimeMapping:
    """_build_runtime_sensor_mapping carries the #197 register values."""

    def test_regs_129_130_map_to_eps_power_legs_only(self) -> None:
        """Regs 129/130 → eps_power_l1/_l2 and NOTHING else (#335).

        The registers carry the COMBINED backup-path legs; the former
        eps_load_power_l1/_l2 aliases and the L1+L2 eps_load_power sum
        fabricated duplicates of eps_power_l1/l2 and are retired.  There is
        no LOCAL source for the cloud epsLoadPower (EPS-loads subset) field.
        """
        runtime = InverterRuntimeData(eps_l1_power=1031, eps_l2_power=296)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["eps_power_l1"] == 1031
        assert mapping["eps_power_l2"] == 296
        assert "eps_load_power_l1" not in mapping
        assert "eps_load_power_l2" not in mapping
        assert "eps_load_power" not in mapping

    def test_no_eps_load_keys_even_when_legs_zero_or_absent(self) -> None:
        """The retired keys never materialize, whatever regs 129/130 read."""
        for runtime in (
            InverterRuntimeData(),
            InverterRuntimeData(eps_l1_power=0, eps_l2_power=0),
            InverterRuntimeData(eps_l1_power=1031),
        ):
            mapping = _build_runtime_sensor_mapping(runtime)
            assert "eps_load_power_l1" not in mapping
            assert "eps_load_power_l2" not in mapping
            assert "eps_load_power" not in mapping

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

    def test_eps_load_power_in_property_map(self) -> None:
        """CLOUD maps eps_load_power from the pylxpweb ``eps_load_power``
        property (cloud epsLoadPower — the EPS-loads subset, #335).  The
        property does not exist in pylxpweb yet; until it ships, the map's
        getattr resolves None and the key stays absent (fail-closed)."""
        property_map = EG4DataUpdateCoordinator._get_inverter_property_map()
        assert property_map.get("eps_load_power") == "eps_load_power"

    async def test_cloud_eps_load_power_is_the_subset_not_the_combined_legs(
        self, hass, mock_config_entry
    ) -> None:
        """#335 contract: epsLoadPower=365 / pEpsL1N=1000 / pEpsL2N=300 →
        eps_power legs 1000/300, eps_load_power=365, and NO fabricated
        eps_load_power_l1/_l2 keys (they were duplicates of the legs).

        The eps_load_power property is patched onto the class with
        ``create=True`` because pylxpweb does not expose it yet — this pins
        the integration's mapping contract for when the library ships it.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "eps_power_l1", property(lambda s: 1000)),
            patch.object(cls, "eps_power_l2", property(lambda s: 300)),
            patch.object(cls, "eps_load_power", property(lambda s: 365), create=True),
        ):
            result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["eps_power_l1"] == 1000
        assert sensors["eps_power_l2"] == 300
        assert sensors["eps_load_power"] == 365
        assert "eps_load_power_l1" not in sensors
        assert "eps_load_power_l2" not in sensors

    async def test_cloud_without_eps_load_power_leaves_key_absent(
        self, hass, mock_config_entry
    ) -> None:
        """No epsLoadPower source → no eps_load_power key (and never the
        fabricated legs/sum) even with pEpsL1N/pEpsL2N present.

        This is also the CURRENT pylxpweb behavior: the class has no
        ``eps_load_power`` property, so the sensor stays absent — never
        wrong — until the library exposes the field.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "eps_power_l1", property(lambda s: 1000)),
            patch.object(cls, "eps_power_l2", property(lambda s: 300)),
        ):
            result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["eps_power_l1"] == 1000
        assert sensors["eps_power_l2"] == 300
        assert "eps_load_power" not in sensors
        assert "eps_load_power_l1" not in sensors
        assert "eps_load_power_l2" not in sensors

    async def test_hybrid_overlay_populates_offgrid_sensors(
        self, hass, mock_config_entry
    ) -> None:
        """HYBRID trusts the local registers: reg 170 → load_power via the
        transport overlay, regs 129/130 → eps_power_l1/_l2 via the property
        map, reg 11 → battery_discharge_power via the property map.  The
        transport carries NO EPS-loads-subset value, so eps_load_power and
        the retired per-leg keys stay absent (#335) — in a real HYBRID
        session the key populates only from cloud-supplemental runtime once
        pylxpweb exposes the property."""
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
        assert sensors["eps_power_l1"] == 1031
        assert sensors["eps_power_l2"] == 296
        assert sensors["battery_discharge_power"] == 1415
        assert "eps_load_power" not in sensors
        assert "eps_load_power_l1" not in sensors
        assert "eps_load_power_l2" not in sensors

    async def test_pure_cloud_has_no_load_power(self, hass, mock_config_entry) -> None:
        """No transport → no load_power key (cloud zero is never trusted).

        Uses a HAS-DATA cloud inverter so the property-map path actually
        executes (review F4: the earlier no-data variant short-circuited at
        has_data=False and would pass even if load_power were mapped).
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Pure cloud: NO transport and NO transport runtime — cloud-side
        # property values are patched onto the real class so the property
        # map path actually executes (no has_data short-circuit). The
        # poisoned load_power property is the canary: pylxpweb's load_power
        # is reg-27 grid import (wrong source) and must never be mapped.
        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "battery_discharge_power", property(lambda s: 1415.0)),
            patch.object(cls, "eps_power_l1", property(lambda s: 1031)),
            patch.object(cls, "eps_power_l2", property(lambda s: 296)),
            # NOTE: HybridInverter exposes no ``load_power`` property at all
            # (verified — patching it raises AttributeError), so the cloud
            # path cannot mis-map it; the map-pin tests above guard the
            # integration side.
        ):
            result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]
        assert "load_power" not in sensors
        # The legitimately cloud-mapped sensors still flow with data.
        assert sensors["battery_discharge_power"] == 1415
        assert sensors["eps_power_l1"] == 1031
        # The fabricated #197 aliases are retired (#335).
        assert "eps_load_power_l1" not in sensors
        assert "eps_load_power" not in sensors


# =========================================================================
# output_power cloud-zero gate (eg4-9e4 Codex review round 1, HIGH)
# =========================================================================


class TestOffgridCloudOutputPowerGate:
    """output_power carries reg-170 semantics (eg4-9e4), but the cloud zeroes
    its reg-170 mirror (pLoad170) for EG4_OFFGRID — the cloud-mapped value
    must be dropped there instead of publishing a false 0 W (#197)."""

    def test_helper_drops_for_offgrid_family(self) -> None:
        sensors: dict[str, object] = {"output_power": 0, "ac_power": 2400}
        drop_offgrid_cloud_output_power(
            sensors, INVERTER_FAMILY_EG4_OFFGRID, has_transport_runtime=False
        )
        assert "output_power" not in sensors
        assert sensors["ac_power"] == 2400

    @pytest.mark.parametrize("family", [None, "", "UNKNOWN", "FUTURE_FAMILY"])
    def test_helper_drops_for_unknown_family(self, family: str | None) -> None:
        """Fail-closed like the #197 entity gate: anything outside the
        trusted allowlist must not risk publishing the OFFGRID cloud zero.
        The pylxpweb InverterFamily enum emits the truthy string "UNKNOWN"
        on failed detection — a not-OFFGRID check would let it through
        (codex r2 HIGH)."""
        sensors: dict[str, object] = {"output_power": 0}
        drop_offgrid_cloud_output_power(sensors, family, has_transport_runtime=False)
        assert "output_power" not in sensors

    @pytest.mark.parametrize(
        "family", [INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP]
    )
    def test_helper_keeps_for_trusted_families(self, family: str) -> None:
        """pLoad170 is live-verified on EG4_HYBRID (18kPV/FlexBOSS21) and
        canonically paired with no zeroing evidence on LXP."""
        sensors: dict[str, object] = {"output_power": 2365}
        drop_offgrid_cloud_output_power(sensors, family, has_transport_runtime=False)
        assert sensors["output_power"] == 2365

    def test_helper_keeps_with_transport_runtime(self) -> None:
        """With transport runtime the value IS reg 170 — genuine even on
        EG4_OFFGRID (pylxpweb power_output prefers the transport)."""
        sensors: dict[str, object] = {"output_power": 1324}
        drop_offgrid_cloud_output_power(
            sensors, INVERTER_FAMILY_EG4_OFFGRID, has_transport_runtime=True
        )
        assert sensors["output_power"] == 1324

    @pytest.mark.asyncio
    async def test_pure_cloud_offgrid_drops_output_power(
        self, hass, mock_config_entry
    ) -> None:
        """End-to-end: pure-cloud 12000XP with the cloud's zeroed pLoad170
        mirror publishes NO output_power key (entity stays absent)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "power_output", property(lambda s: 0.0)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert "output_power" not in result["sensors"]

    @pytest.mark.asyncio
    async def test_pure_cloud_unknown_family_drops_output_power(
        self, hass, mock_config_entry
    ) -> None:
        """End-to-end: failed detection yields the truthy "UNKNOWN" family —
        the gate must still drop the untrusted cloud value (codex r2 HIGH)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("3333333333", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "power_output", property(lambda s: 0.0)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": "UNKNOWN"},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert "output_power" not in result["sensors"]

    @pytest.mark.asyncio
    async def test_pure_cloud_hybrid_family_keeps_output_power(
        self, hass, mock_config_entry
    ) -> None:
        """End-to-end: pure-cloud EG4_HYBRID keeps the pLoad170-sourced
        value (live-verified 2365 W on FlexBOSS21)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("2222222222", "FlexBOSS21")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "power_output", property(lambda s: 2365.0)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["output_power"] == 2365.0

    @pytest.mark.asyncio
    async def test_hybrid_offgrid_local_register_wins(
        self, hass, mock_config_entry
    ) -> None:
        """End-to-end: HYBRID 12000XP with transport runtime keeps
        output_power from reg 170 — the local register always wins."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(output_power=1324.0)
        inverter = make_real_inverter("1111111111", "12000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        with patch.object(
            coordinator,
            "_extract_inverter_features",
            return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["output_power"] == 1324.0


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

    def test_eps_load_purge_suffixes_spare_surviving_keys(self) -> None:
        """#335: the retired-leg suffixes never match the surviving
        eps_load_power (total) or eps_power_l1/l2 unique_ids."""
        from custom_components.eg4_web_monitor import (
            _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES,
        )

        assert "_eps_load_power_l1" in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
        assert "_eps_load_power_l2" in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
        for surviving_uid in (
            "1111111111_runtime_eps_load_power",
            "1111111111_runtime_eps_power_l1",
            "1111111111_runtime_eps_power_l2",
            # GridBOSS per-leg load keys share the ..._load_power_l1 shape.
            "4524850115_midbox_runtime_load_power_l1",
        ):
            assert not any(
                surviving_uid.endswith(suffix)
                for suffix in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
            ), surviving_uid

    async def test_retired_eps_load_leg_entities_purged(
        self, hass, mock_config_entry
    ) -> None:
        """#335: orphaned eps_load_power_l1/_l2 registry entries are removed
        by the duplicate-sensor cleanup; the eps_load_power (total) entry —
        which now carries the real cloud epsLoadPower field — survives."""
        from homeassistant.helpers import entity_registry as er

        from custom_components.eg4_web_monitor import (
            _async_cleanup_duplicate_runtime_data_entities,
        )

        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)

        uid_l1 = "1111111111_runtime_eps_load_power_l1"
        uid_l2 = "1111111111_runtime_eps_load_power_l2"
        uid_total = "1111111111_runtime_eps_load_power"
        uid_leg = "1111111111_runtime_eps_power_l1"
        for uid in (uid_l1, uid_l2, uid_total, uid_leg):
            registry.async_get_or_create(
                "sensor", DOMAIN, uid, config_entry=mock_config_entry
            )

        _async_cleanup_duplicate_runtime_data_entities(hass, mock_config_entry)

        get_eid = registry.async_get_entity_id
        assert get_eid("sensor", DOMAIN, uid_l1) is None
        assert get_eid("sensor", DOMAIN, uid_l2) is None
        assert get_eid("sensor", DOMAIN, uid_total) is not None
        assert get_eid("sensor", DOMAIN, uid_leg) is not None

    async def test_conditional_cleanup_by_family(self, hass, mock_config_entry) -> None:
        """The conditional registry cleanup removes stale per-inverter
        _battery_discharge_power entries ONLY for known non-OFFGRID families.

        Pins the actual entity-registry loop in async_setup_entry (review
        round 2 MINOR): OFFGRID keeps its (reintroduced) entity, a known
        non-OFFGRID family is purged, an unknown family is conservatively
        kept for a later refresh to resolve.
        """
        from unittest.mock import MagicMock

        from homeassistant.helpers import entity_registry as er

        from custom_components.eg4_web_monitor import async_setup_entry

        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)

        uid_offgrid = "1000000001_runtime_battery_discharge_power"
        uid_hybrid = "1000000002_runtime_battery_discharge_power"
        uid_unknown = "1000000003_runtime_battery_discharge_power"
        for uid in (uid_offgrid, uid_hybrid, uid_unknown):
            registry.async_get_or_create(
                "sensor", DOMAIN, uid, config_entry=mock_config_entry
            )

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.data = {
            "devices": {
                "1000000001": {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
                },
                "1000000002": {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
                },
                "1000000003": {"type": "inverter", "features": {}},
            }
        }

        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=mock_coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            assert await async_setup_entry(hass, mock_config_entry)

        get_eid = registry.async_get_entity_id
        assert get_eid("sensor", DOMAIN, uid_offgrid) is not None
        assert get_eid("sensor", DOMAIN, uid_hybrid) is None
        assert get_eid("sensor", DOMAIN, uid_unknown) is not None


# =========================================================================
# Smart load (GEN port) split — issue #222 (6000XP)
# =========================================================================


class TestSmartLoadSensors:
    """Cloud-only smart-load split sensors (issue #222).

    On the 6000XP the GEN terminal doubles as a smart-load output and the
    cloud splits the backup-path output: smartLoadPower 2999 W (EV charger)
    + epsLoadPower 365 W vs peps/regs-129+130 carrying the COMBINED 3371 W.
    The split exists ONLY in the cloud runtime — no validated local register
    on the off-grid family — so the keys flow exclusively through the HTTP
    property map (CLOUD + HYBRID supplemental) and must stay out of the
    LOCAL static key sets.

    SENSOR_TYPES shape, static-set exclusion and family gating for these
    keys are covered generically above (they parametrize _CLOUD_ONLY_KEYS,
    which #335 extended with eps_load_power); this class keeps the
    GEN-port-specific contracts.
    """

    def test_gridboss_smart_load_power_unaffected(self) -> None:
        """ "smart_load_power" is a SHARED key (like "load_power"): GridBOSS
        publishes the all-ports smart-load aggregate under it.  Adding it to
        OFFGRID_ONLY_SENSORS must not block GridBOSS / parallel-group
        entities, which pass via the device_type bypass."""
        assert _should_create_sensor("smart_load_power", None, "gridboss") is True
        assert _should_create_sensor("smart_load_power", {}, "gridboss") is True
        assert _should_create_sensor("smart_load_power", None, "parallel_group") is True

    @pytest.mark.parametrize("key", _SMART_LOAD_KEYS)
    def test_in_http_property_map(self, key: str) -> None:
        """CLOUD/HYBRID map the pylxpweb property of the same name."""
        property_map = EG4DataUpdateCoordinator._get_inverter_property_map()
        assert property_map.get(key) == key

    @pytest.mark.asyncio
    async def test_hybrid_cloud_supplemental_end_to_end(
        self, hass, mock_config_entry
    ) -> None:
        """HYBRID: transport regs feed the #197 sensors while the cloud-only
        smart-load split flows through the property map — and the eps_power
        sensors keep their combined-output semantics.

        The smart-load properties land in pylxpweb (cloud-read even when a
        transport is attached); they are patched onto the real class here so
        the integration contract is testable against the released library.
        The fabricated eps_load_* duplicates of the combined legs are gone
        (#335): this very scenario (GEN port active) is where the old L1+L2
        "EPS load" sum diverged from the cloud epsLoadPower subset.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        # Reporter's capture: EV charging on the GEN-port smart load.
        runtime = InverterRuntimeData(
            eps_l1_power=1590,
            eps_l2_power=1740,
            battery_discharge_power=3240.0,
        )
        inverter = make_real_inverter("4233740012", "6000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()
        cls = type(inverter)
        with (
            patch.object(
                cls, "smart_load_power", property(lambda s: 2999), create=True
            ),
            patch.object(cls, "grid_load_power", property(lambda s: 0), create=True),
        ):
            result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        # Cloud-supplemental split (#222)
        assert sensors["smart_load_power"] == 2999
        assert sensors["grid_load_power"] == 0
        # eps_power legs: combined backup output from the per-leg registers
        # (1590 + 1740 = 3330 ≈ web UI 3371 W timing skew).
        assert sensors["eps_power_l1"] == 1590
        assert sensors["eps_power_l2"] == 1740
        # The fabricated aliases/sum no longer exist; eps_load_power would
        # only appear from the cloud epsLoadPower field (property pending).
        assert "eps_load_power_l1" not in sensors
        assert "eps_load_power_l2" not in sensors
        assert "eps_load_power" not in sensors

    @pytest.mark.asyncio
    async def test_smart_port_cleanup_spares_inverter_entity(
        self, hass, mock_config_entry
    ) -> None:
        """The stale GridBOSS smart-port registry cleanup must not delete the
        inverter's smart_load_power entity (shared key — codex review MEDIUM).

        Before the serial gate, the suffix-only match removed ANY sensor
        whose unique_id ends in a smart-port key when that key was not
        active on a GridBOSS — including the new EG4_OFFGRID inverter
        entity, on every reload, for every system without an active
        GridBOSS smart port.  The GridBOSS's own stale entities must keep
        being cleaned.
        """
        from unittest.mock import MagicMock

        from homeassistant.helpers import entity_registry as er

        from custom_components.eg4_web_monitor import async_setup_entry

        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)

        uid_inverter = "1000000001_smart_load_power"  # OFFGRID inverter (#222)
        uid_gb_aggregate = "9000000001_smart_load_power"  # inactive GB aggregate
        uid_gb_port = "9000000001_smart_load1_power"  # stale per-port entity
        # Second GridBOSS with the SAME key active: per-serial tracking must
        # still clean unit A's stale entity (codex r2 LOW: a global active
        # set would let it survive forever) while keeping unit B's.
        uid_gb2_port = "9000000002_smart_load1_power"  # ACTIVE on unit B
        for uid in (uid_inverter, uid_gb_aggregate, uid_gb_port, uid_gb2_port):
            registry.async_get_or_create(
                "sensor", DOMAIN, uid, config_entry=mock_config_entry
            )

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        # Both GridBOSS units carry AUTHORITATIVE port data: the per-cycle
        # validation marker _filter_unused_smart_port_sensors writes on a
        # fresh, complete good status read.  Without it, the cleanup defers
        # to a coordinator listener instead of running at setup — static
        # first-refresh data must never trigger registry removal (#217).
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            SMART_PORT_VALIDATED_KEY,
        )

        _all_unused = {f"smart_port{p}_status": "unused" for p in range(1, 5)}
        _all_unused[SMART_PORT_VALIDATED_KEY] = True
        mock_coordinator.data = {
            "devices": {
                "1000000001": {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
                    "sensors": {"smart_load_power": 2999},
                },
                # GridBOSS A with NO active smart-port keys this cycle
                "9000000001": {"type": "gridboss", "sensors": dict(_all_unused)},
                # GridBOSS B with smart_load1_power ACTIVE
                "9000000002": {
                    "type": "gridboss",
                    "sensors": {
                        **_all_unused,
                        "smart_port1_status": "smart_load",
                        "smart_load1_power": 480,
                    },
                },
            }
        }

        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=mock_coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            assert await async_setup_entry(hass, mock_config_entry)

        get_eid = registry.async_get_entity_id
        # Inverter entity survives (serial gate)
        assert get_eid("sensor", DOMAIN, uid_inverter) is not None
        # GridBOSS A stale entities still cleaned — even though B has the
        # same per-port key active (per-serial active sets)
        assert get_eid("sensor", DOMAIN, uid_gb_aggregate) is None
        assert get_eid("sensor", DOMAIN, uid_gb_port) is None
        # GridBOSS B's active entity is untouched
        assert get_eid("sensor", DOMAIN, uid_gb2_port) is not None

    @pytest.mark.asyncio
    async def test_released_pylxpweb_without_properties_drops_keys(
        self, hass, mock_config_entry
    ) -> None:
        """Against a pylxpweb without the new properties the keys simply
        never materialize — no None-valued ghosts, no broken entities.
        This pins the safe ship-order: integration first, library after.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(eps_l1_power=1590, eps_l2_power=1740)
        inverter = make_real_inverter("4233740012", "6000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()

        if hasattr(type(inverter), "smart_load_power"):
            pytest.skip("installed pylxpweb already ships the properties")

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]
        assert "smart_load_power" not in sensors
        assert "grid_load_power" not in sensors


class TestOffgridLinkDownLoadFallback:
    """#226 residual (eg4-jzwg): Loads during a hybrid link-down window.

    total_load_power was only ever set by the transport overlay, so a
    link-down cloud-fallback window (transport caches cleared) dropped the
    key and the sensor went unknown — the reporter's Loads gauge errored
    while every other sensor fell back to cloud data.  For EG4_OFFGRID the
    cloud split (epsLoadPower + smartLoadPower + gridLoadPower) is the
    authoritative load figure, so the property-path fallback maps it;
    grid-tied families stay transport-only (their per-inverter cloud
    consumptionPower is unreliable).
    """

    @staticmethod
    def _offgrid_features() -> InverterFeatures:
        features = InverterFeatures.from_device_type_code(38)
        assert features.model_family is InverterFamily.EG4_OFFGRID
        return features

    @pytest.mark.asyncio
    async def test_link_down_maps_total_load_from_cloud_split(
        self, hass, mock_config_entry
    ) -> None:
        """No transport runtime + offgrid family → split sum (365+2999+0)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("4233740012", "6000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._features = self._offgrid_features()
        inverter._runtime = InverterRuntime.model_construct(
            epsLoadPower=365,
            smartLoadPower=2999,
            gridLoadPower=0,
            consumptionPower=0,  # the false 0 the cloud serves this family
        )

        result = await coordinator._process_inverter_object(inverter)
        assert result["sensors"]["total_load_power"] == 3364

    @pytest.mark.asyncio
    async def test_grid_tied_link_down_stays_absent(
        self, hass, mock_config_entry
    ) -> None:
        """Grid-tied family + no transport runtime → key stays absent.

        The cloud's per-inverter consumptionPower is unreliable on grid-tied
        units; the honest behavior there remains an unknown sensor during the
        outage window, not a fabricated value.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1234567890", "FlexBOSS21")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._features = InverterFeatures(
            model_family=InverterFamily.EG4_HYBRID,
            split_phase=True,
        )
        inverter._runtime = InverterRuntime.model_construct(consumptionPower=1234)

        result = await coordinator._process_inverter_object(inverter)
        assert "total_load_power" not in result["sensors"]

    @pytest.mark.asyncio
    async def test_transport_present_keeps_local_balance(
        self, hass, mock_config_entry
    ) -> None:
        """Healthy hybrid: the local energy balance wins over the cloud split."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(
            pv_total_power=1000,
            power_from_grid=0,
            power_to_grid=0,
            battery_discharge_power=500,
            battery_charge_power=0,
        )
        inverter = make_real_inverter("4233740012", "6000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._features = self._offgrid_features()
        inverter._runtime = InverterRuntime.model_construct(
            epsLoadPower=365,
            smartLoadPower=2999,
            gridLoadPower=0,
        )

        result = await coordinator._process_inverter_object(inverter)
        # 1000 PV + 500 discharge = 1500 from the local balance, not 3364.
        assert result["sensors"]["total_load_power"] == 1500
