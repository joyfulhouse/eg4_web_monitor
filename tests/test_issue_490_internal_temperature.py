"""Regression tests for the constant-zero temperature blanking (#490, #560).

Two reports, two sources, same shape — a temperature channel stuck at
exactly 0 while the radiator temperatures read live:

- #490: the cloud ``getInverterRuntime`` payload relays a constant
  ``tinner: 0`` for some hardware (the reporter's 12000XP, and the #76 raw
  payload from a second 12000XP with ``tinner: 0`` next to ``tradiator1:
  46`` / ``tradiator2: 54``).  ``tinner`` is a REQUIRED pydantic field in
  pylxpweb, so the 0 is literally on the wire — there is no sentinel to
  translate — and the sensor rendered a permanent bogus 0 °C / 32 °F.
- #560: a HYBRID-mode 12000XP (EG4_OFFGRID, deviceTypeCode 54) whose LOCAL
  input registers serve the same constant 0 in reg 64 (internal), reg 67
  (battery) and reg 108 (BT), while radiator1/2 read 58/61 °C and the BMS
  cell temps read a healthy 30/32 °C.  Not a sentinel (127 → 0x7F already
  maps to None in pylxpweb), not signed-decode, not scaling — the DSP
  genuinely serves 0.  #560 falsifies the #490 exemption for
  transport-backed values, so the blanking now covers all three registers
  on every path (CLOUD, HYBRID, LOCAL).

THE FIX IS NOT A FAMILY GATE, and these tests exist partly to keep it from
becoming one.  The bad value does not track the inverter family: a 6000XP
owner reports live ``Tinner`` of 31-32 °C alongside radiators at 58-65 °C
in EG4's own data table

    https://forum.eg4electronics.com/community/troubleshooting/3-6000xps-in-parallel-fans-do-not-run-at-low-wattage/

and ``MODEL_NAME_FAMILY_FALLBACK`` classifies the 6000XP as EG4_OFFGRID
exactly like the 12000XP — they share deviceTypeCode 54, which nothing can
split (#259/#307).  So the split is WITHIN the family, and gating by family
would suppress a sensor that demonstrably works on real hardware.  That is
the #307 over-gating failure, confirmed rather than hypothetical.

Instead only the observed VALUE is treated, and only on positive warmth
evidence: an exact 0 in ``internal_temperature`` / ``battery_temperature``
/ ``bt_temperature`` is published as None (HA "unknown") when at least one
radiator reads STRICTLY ``> 0`` °C — a unit whose radiators read 58 °C is
not at 0 °C ambient.  Radiators ``<= 0`` (including negatives) and
absent/``None`` radiators PROTECT the reading (publish the 0): there is no
evidence it is bogus.  That narrows the earlier #490 unconditional
absent-radiator cloud blanking; known #490/#76 reporter payloads had live
radiators, so they remain fixed.  An all-zero boot/placeholder frame is
physically indistinguishable from genuine cold and is an accepted residual
(publishes the zeros until radiators warm) — no family/freshness guess.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.entity_registry as er
import pytest
from homeassistant.core import HomeAssistant
from pylxpweb.transports.data import InverterRuntimeData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import (
    _async_cleanup_deprecated_battery_discharge_power_entities,
)
from custom_components.eg4_web_monitor.const import (
    DOMAIN,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_UNKNOWN,
    SENSOR_TYPES,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_runtime_sensor_mapping,
    blank_constant_zero_temperatures,
)
from custom_components.eg4_web_monitor.sensor import _should_create_sensor

from .conftest import make_real_inverter, stub_cloud_client

_OFFGRID = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}


@pytest.fixture
def cloud_config_entry() -> MockConfigEntry:
    """Cloud config entry (same shape as the test_offgrid_registers fixture)."""
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    from custom_components.eg4_web_monitor.const import (
        CONF_BASE_URL,
        CONF_DST_SYNC,
        CONF_LIBRARY_DEBUG,
        CONF_PLANT_ID,
        CONF_PLANT_NAME,
        CONF_VERIFY_SSL,
    )

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
        entry_id="issue_490_cloud_entry",
    )


# ── The constant-zero treatment ────────────────────────────────────────


class TestConstantZeroBlanking:
    """An exact 0 becomes None only with warmth evidence; other values pass."""

    def test_zero_becomes_none_with_warm_radiator(self) -> None:
        """FAILS without the fix: the sensor published a bogus 0 °C forever."""
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": 46,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] is None

    def test_zero_key_is_kept_not_popped(self) -> None:
        """The key must survive as None so the entity reads unknown.

        Dropping the key entirely is the other available idiom in this module
        (``drop_offgrid_cloud_output_power`` pops), but a present-but-None
        value is what makes the sensor read "unknown" rather than risking an
        availability flip for keys shared with bank entities (#261).
        """
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": 46,
        }
        blank_constant_zero_temperatures(sensors)
        assert "internal_temperature" in sensors
        assert sensors["internal_temperature"] is None

    def test_battery_and_bt_temperature_covered(self) -> None:
        """FAILS without #560 coverage: regs 67 and 108 serve the same 0."""
        sensors: dict[str, Any] = {
            "battery_temperature": 0,
            "bt_temperature": 0,
            "radiator1_temperature": 58,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["battery_temperature"] is None
        assert sensors["bt_temperature"] is None

    def test_live_values_pass_through(self) -> None:
        """The 6000XP counterexample: a live reading is never touched.

        This is the case that killed the family-gate approach — 31-32 °C
        reported on EG4's own data table by a 6000XP, which is EG4_OFFGRID.
        """
        for key in ("internal_temperature", "battery_temperature", "bt_temperature"):
            for value in (31, 32, 41, 65):
                sensors: dict[str, Any] = {
                    key: value,
                    "radiator1_temperature": 58,
                }
                blank_constant_zero_temperatures(sensors)
                assert sensors[key] == value

    def test_negative_value_passes_through(self) -> None:
        """A cold-climate install reporting below zero must survive.

        Guards the check being ``== 0`` rather than a falsy test or a
        ``<= 0``/``not value`` formulation that would swallow valid readings.
        """
        for value in (-1, -12, -30):
            sensors: dict[str, Any] = {
                "internal_temperature": value,
                "radiator1_temperature": 58,
            }
            blank_constant_zero_temperatures(sensors)
            assert sensors["internal_temperature"] == value

    def test_none_stays_none(self) -> None:
        """An already-absent reading is unchanged (no key invented)."""
        sensors: dict[str, Any] = {
            "internal_temperature": None,
            "radiator1_temperature": 58,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] is None

    def test_missing_key_is_not_added(self) -> None:
        sensors: dict[str, Any] = {"radiator1_temperature": 58}
        blank_constant_zero_temperatures(sensors)
        assert "internal_temperature" not in sensors
        assert "battery_temperature" not in sensors
        assert "bt_temperature" not in sensors


class TestRadiatorCorroboration:
    """Positive warmth corroborates the bogus 0; cold/absent radiators protect.

    Blank only when at least one radiator is STRICTLY ``> 0`` °C.  Mutation
    check: ``> 0`` → ``!= 0`` fails the negative-radiator test; ``> 0`` →
    always-blank (dropped gate) fails the all-zero / absent protect tests.
    """

    def test_live_radiators_corroborate_blank(self) -> None:
        """The #560 shape: regs 64/67/108 at 0, radiators live at 58/61."""
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "battery_temperature": 0,
            "bt_temperature": 0,
            "radiator1_temperature": 58,
            "radiator2_temperature": 61,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] is None
        assert sensors["battery_temperature"] is None
        assert sensors["bt_temperature"] is None

    def test_one_live_radiator_is_enough(self) -> None:
        for radiator_key in ("radiator1_temperature", "radiator2_temperature"):
            sensors: dict[str, Any] = {"internal_temperature": 0, radiator_key: 46}
            blank_constant_zero_temperatures(sensors)
            assert sensors["internal_temperature"] is None

    def test_all_zero_frame_publishes_accepted_residual(self) -> None:
        """All-zero boot/placeholder is indistinguishable from genuine cold.

        Publishes the zeros (accepted residual) until radiators warm — do NOT
        add family gates or freshness heuristics to guess (#490 lesson).
        FAILS if the corroboration gate is dropped (unconditional blank).
        """
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "battery_temperature": 0,
            "bt_temperature": 0,
            "radiator1_temperature": 0,
            "radiator2_temperature": 0,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] == 0
        assert sensors["battery_temperature"] == 0
        assert sensors["bt_temperature"] == 0

    def test_negative_radiators_protect_zero(self) -> None:
        """internal=0 with radiators -2/-1 must PUBLISH the 0.

        Kills the surviving ``!= 0`` → ``> 0`` mutation: after the redesign,
        mutating ``> 0`` back to ``!= 0`` treats negatives as warmth and
        blanks — this test goes red.
        """
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": -2,
            "radiator2_temperature": -1,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] == 0

    def test_absent_radiators_protect_zero(self) -> None:
        """No radiator data at all: no warmth evidence → publish the 0.

        Narrows #490's unconditional absent-radiator blanking.  FAILS if
        absent radiators are treated as corroboration again.
        """
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": None,
            "radiator2_temperature": None,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] == 0

    def test_tri_state_zero_and_none_radiators_publish(self) -> None:
        """One radiator 0 + one None → no warmth evidence → publish.

        Pins the mixed tri-state explicitly; no silent fall-through.
        """
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": 0,
            "radiator2_temperature": None,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] == 0

        sensors = {
            "internal_temperature": 0,
            "radiator1_temperature": None,
            "radiator2_temperature": 0,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["internal_temperature"] == 0

    def test_radiator_values_themselves_untouched(self) -> None:
        """The radiators are the corroborating evidence, never a target."""
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": 0,
            "radiator2_temperature": 54,
        }
        blank_constant_zero_temperatures(sensors)
        assert sensors["radiator1_temperature"] == 0
        assert sensors["radiator2_temperature"] == 54
        assert sensors["internal_temperature"] is None


class TestLocalRegisterPath:
    """#560: the LOCAL register mapping gets the same treatment.

    These drive ``_build_runtime_sensor_mapping`` — the LOCAL path — on a
    real pylxpweb ``InverterRuntimeData``.
    """

    def test_register_zeros_blanked_when_radiators_live(self) -> None:
        """FAILS without the fix: the LOCAL mapping published the bogus 0."""
        runtime = InverterRuntimeData(
            internal_temperature=0,
            battery_temperature=0,
            temperature_t1=0,
            radiator_temperature_1=58,
            radiator_temperature_2=61,
        )
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["internal_temperature"] is None
        assert mapping["battery_temperature"] is None
        assert mapping["bt_temperature"] is None
        assert mapping["radiator1_temperature"] == 58
        assert mapping["radiator2_temperature"] == 61

    def test_live_register_values_pass_through(self) -> None:
        runtime = InverterRuntimeData(
            internal_temperature=31,
            battery_temperature=32,
            temperature_t1=33,
            radiator_temperature_1=58,
            radiator_temperature_2=61,
        )
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["internal_temperature"] == 31
        assert mapping["battery_temperature"] == 32
        assert mapping["bt_temperature"] == 33

    def test_all_zero_frame_publishes_accepted_residual(self) -> None:
        """All-zero boot/placeholder frame publishes zeros (accepted residual).

        Indistinguishable from a genuinely cold unit — no heuristic guess.
        """
        runtime = InverterRuntimeData(
            internal_temperature=0,
            battery_temperature=0,
            temperature_t1=0,
            radiator_temperature_1=0,
            radiator_temperature_2=0,
        )
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["internal_temperature"] == 0
        assert mapping["battery_temperature"] == 0
        assert mapping["bt_temperature"] == 0

    def test_raw_register_decode_path_to_blanking(self) -> None:
        """Drive real ``from_modbus_registers`` decode through to blanking.

        Pins signed decode on reg 64 and ÷10 scaling on reg 108 so a
        pre-decoded dataclass cannot hide sign/scaling regressions.
        Mutation-check: treating reg 64 as unsigned makes ``0xFFFE`` → 65534
        (this test goes red on the ``== -2`` expectation); dropping ÷10 on
        reg 108 makes raw 250 → 250 instead of 25.0.
        """
        warm_zeros = InverterRuntimeData.from_modbus_registers(
            {
                64: 0,
                65: 58,
                66: 61,
                67: 0,
                108: 0,
            },
            model_family="EG4_OFFGRID",
        )
        mapping = _build_runtime_sensor_mapping(warm_zeros)
        assert mapping["internal_temperature"] is None
        assert mapping["battery_temperature"] is None
        assert mapping["bt_temperature"] is None
        assert mapping["radiator1_temperature"] == 58
        assert mapping["radiator2_temperature"] == 61

        signed_and_scaled = InverterRuntimeData.from_modbus_registers(
            {
                64: 0xFFFE,  # signed int16 → -2 °C
                65: 58,
                66: 61,
                67: 30,
                108: 250,  # ÷10 → 25.0 °C
            },
            model_family="EG4_OFFGRID",
        )
        mapping = _build_runtime_sensor_mapping(signed_and_scaled)
        assert mapping["internal_temperature"] == -2
        assert mapping["bt_temperature"] == 25.0
        assert mapping["battery_temperature"] == 30


class TestNoFamilyGate:
    """The sensor is created for EVERY family — no suppression anywhere.

    FAILS against the abandoned first direction, which suppressed
    ``internal_temperature`` on EG4_OFFGRID and so would have hidden the
    6000XP's real 31-32 °C reading.
    """

    def test_internal_temperature_is_a_real_sensor_key(self) -> None:
        assert "internal_temperature" in SENSOR_TYPES

    def test_created_on_offgrid_family(self) -> None:
        assert _should_create_sensor("internal_temperature", _OFFGRID) is True

    def test_created_on_every_family_and_when_unresolved(self) -> None:
        for features in (
            {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
            {"inverter_family": INVERTER_FAMILY_UNKNOWN},
            {},
            None,
        ):
            assert _should_create_sensor("internal_temperature", features) is True

    def test_created_on_non_inverter_device_types(self) -> None:
        for device_type in ("gridboss", "parallel_group"):
            assert (
                _should_create_sensor("internal_temperature", _OFFGRID, device_type)
                is True
            )


class TestEndToEndWiring:
    """The treatment is actually WIRED into the cloud processing path.

    The isolated function tests above all pass with the call site deleted, so
    without these the suite would green-light a fix that never runs.  These
    drive the real ``_process_inverter_object`` on a real pylxpweb inverter.
    """

    @pytest.mark.asyncio
    async def test_pure_cloud_zero_tinner_publishes_unknown(
        self, hass, cloud_config_entry
    ) -> None:
        """End-to-end: a pure-cloud 12000XP reporting tinner=0 publishes None.

        FAILS with the call site removed — this is the #490 bug itself.
        """
        cloud_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, cloud_config_entry)
        coordinator.client = stub_cloud_client()

        inverter = make_real_inverter("1111111111", "12000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "inverter_temperature", property(lambda s: 0)),
            patch.object(cls, "radiator1_temperature", property(lambda s: 46)),
            patch.object(cls, "radiator2_temperature", property(lambda s: 54)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["internal_temperature"] is None
        # The radiators are the live proof the device is reporting at all.
        assert result["sensors"]["radiator1_temperature"] == 46
        assert result["sensors"]["radiator2_temperature"] == 54

    @pytest.mark.asyncio
    async def test_pure_cloud_6000xp_live_value_survives(
        self, hass, cloud_config_entry
    ) -> None:
        """The 6000XP counterexample survives end-to-end.

        FAILS under any family-gated implementation: the 6000XP is
        EG4_OFFGRID, yet it reports a real 32 °C that must reach the sensor.
        """
        cloud_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, cloud_config_entry)
        coordinator.client = stub_cloud_client()

        inverter = make_real_inverter("2222222222", "6000XP")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(cls, "inverter_temperature", property(lambda s: 32)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["internal_temperature"] == 32

    @pytest.mark.asyncio
    async def test_hybrid_register_zeros_blank_end_to_end(
        self, hass, cloud_config_entry
    ) -> None:
        """#560 end-to-end: HYBRID regs 64/67/108 at constant 0 publish unknown.

        FAILS without the fix — the #560 bug itself: transport runtime
        present exempted the value from the #490 blanking, and regs 67/108
        were never covered, so all three sensors rendered a bogus 0 °C
        (32 °F) on a unit running at 58/61 °C radiator temperature.  The
        bt_temperature row also pins the call ORDER: the transport overlay
        writes reg 108 after the property map, so the blanking must run
        after the overlay to treat it.
        """
        cloud_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, cloud_config_entry)
        coordinator.client = stub_cloud_client()

        runtime = InverterRuntimeData(
            internal_temperature=0,
            battery_temperature=0,
            temperature_t1=0,
            radiator_temperature_1=58,
            radiator_temperature_2=61,
        )
        inverter = make_real_inverter("3333333333", "12000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["internal_temperature"] is None
        assert result["sensors"]["battery_temperature"] is None
        assert result["sensors"]["bt_temperature"] is None
        # The radiators are the live corroboration that the unit is warm.
        assert result["sensors"]["radiator1_temperature"] == 58
        assert result["sensors"]["radiator2_temperature"] == 61

    @pytest.mark.asyncio
    async def test_hybrid_live_temperatures_survive_end_to_end(
        self, hass, cloud_config_entry
    ) -> None:
        """A HYBRID unit reporting real temperatures is never treated."""
        cloud_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, cloud_config_entry)
        coordinator.client = stub_cloud_client()

        runtime = InverterRuntimeData(
            internal_temperature=31,
            battery_temperature=32,
            temperature_t1=33,
            radiator_temperature_1=58,
            radiator_temperature_2=61,
        )
        inverter = make_real_inverter("1212121212", "12000XP", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        cls = type(inverter)
        with (
            patch.object(cls, "has_data", property(lambda s: True)),
            patch.object(
                coordinator,
                "_extract_inverter_features",
                return_value={"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
            ),
        ):
            result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"]["internal_temperature"] == 31
        assert result["sensors"]["battery_temperature"] == 32
        assert result["sensors"]["bt_temperature"] == 33


# ── The independent #197 purge corrections ───────────────────────────


def _coordinator_with_devices(devices: dict[str, dict[str, Any]]) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {"devices": devices}
    return coordinator


async def test_cleanup_retains_battery_discharge_power_behavior(
    hass: HomeAssistant,
) -> None:
    """The #197 purge survives the extraction unchanged.

    Non-offgrid RESOLVED-family inverters lose the stale
    ``_battery_discharge_power`` entry; offgrid and unresolved inverters keep
    theirs.
    """
    entry = MockConfigEntry(domain=DOMAIN, entry_id="issue_490_197_entry")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    offgrid_serial = "4444444444"
    hybrid_serial = "5555555555"
    featureless_serial = "6666666666"
    coordinator = _coordinator_with_devices(
        {
            offgrid_serial: {"type": "inverter", "features": dict(_OFFGRID)},
            hybrid_serial: {
                "type": "inverter",
                "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
            },
            featureless_serial: {"type": "inverter", "features": {}},
        }
    )

    entities = {
        serial: registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{serial}_battery_discharge_power",
            config_entry=entry,
        )
        for serial in (offgrid_serial, hybrid_serial, featureless_serial)
    }

    _async_cleanup_deprecated_battery_discharge_power_entities(hass, entry, coordinator)

    assert registry.async_get(entities[offgrid_serial].entity_id) is not None
    assert registry.async_get(entities[hybrid_serial].entity_id) is None
    assert registry.async_get(entities[featureless_serial].entity_id) is not None


async def test_unknown_family_string_is_not_treated_as_resolved(
    hass: HomeAssistant,
) -> None:
    """``inverter_family="UNKNOWN"`` must NOT count as a known family.

    FAILS without the fix (bare ``if family:``): the string "UNKNOWN" is
    truthy AND is the value the pipeline actually emits for an unresolved
    device — pylxpweb's ``InverterFeatures.model_family`` defaults to
    ``InverterFamily.UNKNOWN`` and ``detect_features()`` returns that default
    without raising when the parameter fetch leaves parameters unavailable.
    So one transient parameter-read failure on a genuine off-grid unit made it
    look like "family known, not off-grid" and irreversibly deleted the very
    sensor #197 reintroduced for that family.
    """
    entry = MockConfigEntry(domain=DOMAIN, entry_id="issue_490_unknown_family")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    unresolved_serial = "7777777777"
    coordinator = _coordinator_with_devices(
        {
            unresolved_serial: {
                "type": "inverter",
                "features": {"inverter_family": INVERTER_FAMILY_UNKNOWN},
            },
        }
    )

    entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{unresolved_serial}_battery_discharge_power",
        config_entry=entry,
    )

    _async_cleanup_deprecated_battery_discharge_power_entities(hass, entry, coordinator)

    assert registry.async_get(entity.entity_id) is not None


async def test_purge_matches_the_device_namespace_only(
    hass: HomeAssistant,
) -> None:
    """Matching is namespace-scoped, not a bare ``endswith``.

    FAILS without the fix: one shared SENSOR_TYPES table backs several
    unique-ID namespaces that all begin with the parent inverter serial —
    device ``{serial}_{data_type}_{key}``, battery
    ``{serial}_{battery_key}_{key}`` and bank ``{serial}_battery_bank_{key}``.
    A suffix matcher deletes the battery and bank siblings too.

    Two device forms are purged: the bare ``{serial}_{key}`` — the ONLY shape
    this code is known to have ever emitted — and ``{serial}_runtime_{key}``.
    The latter is a DOCUMENTATION ARTIFACT, not an observed shape: it appears
    in CLAUDE.md and in ``test_conditional_cleanup_by_family``'s fixture, but
    no Python in this repo's history produces it.  It is covered defensively
    so a future data-type scheme cannot silently bypass the guard.

    The battery shapes below are the ones the code ACTUALLY emits.
    ``base_entity`` builds ``{serial}_{battery_key}_{key}`` from the key that
    ``clean_battery_display_name`` produced, so the raw
    ``{serial}_Battery_ID_nn`` form never reaches a unique ID — it becomes
    ``{serial}-nn``.  Critically, a ``BAT``-prefixed key passes through
    VERBATIM and does NOT restate the parent serial, and this integration
    generated exactly those (``BAT{index:03d}``, commit d3dba21 / #76).  That
    row is why the matcher allowlists device shapes instead of blocklisting
    "middle starts with the serial", which would have purged it.
    """
    entry = MockConfigEntry(domain=DOMAIN, entry_id="issue_490_exact_match")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    serial = "8888888888"
    coordinator = _coordinator_with_devices(
        {
            serial: {
                "type": "inverter",
                "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
            },
        }
    )

    device_entity = registry.async_get_or_create(
        "sensor", DOMAIN, f"{serial}_battery_discharge_power", config_entry=entry
    )
    legacy_device_entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_runtime_battery_discharge_power",
        config_entry=entry,
    )
    # Serial-restating battery key: clean_battery_display_name turns the cloud
    # "{inverterSn}_{batterySn}" key into "{serial}-nn".
    battery_entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_{serial}-01_battery_discharge_power",
        config_entry=entry,
    )
    # NON-serial-restating battery key — the case a "starts with the serial"
    # blocklist would have wrongly purged.
    bat_prefixed_entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_BAT001_battery_discharge_power",
        config_entry=entry,
    )
    bank_entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{serial}_battery_bank_battery_discharge_power",
        config_entry=entry,
    )

    _async_cleanup_deprecated_battery_discharge_power_entities(hass, entry, coordinator)

    # Both device-namespace forms are purged...
    assert registry.async_get(device_entity.entity_id) is None
    assert registry.async_get(legacy_device_entity.entity_id) is None
    # ...and no sibling-namespace row is touched, whatever the key shape.
    assert registry.async_get(battery_entity.entity_id) is not None
    assert registry.async_get(bat_prefixed_entity.entity_id) is not None
    assert registry.async_get(bank_entity.entity_id) is not None
