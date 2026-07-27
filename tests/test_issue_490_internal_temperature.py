"""Regression tests for issue #490 — cloud Internal Temperature is a constant 0.

The cloud ``getInverterRuntime`` payload relays a constant ``tinner: 0`` for
some hardware while the radiator temperatures read live values (the #490
reporter's 12000XP, and the #76 raw payload from a second 12000XP with
``tinner: 0`` next to ``tradiator1: 46`` / ``tradiator2: 54``).  ``tinner`` is
a REQUIRED pydantic field in pylxpweb, so the 0 is literally on the wire —
there is no sentinel to translate — and the sensor rendered a permanent bogus
0 °C / 32 °F.

THE FIX IS NOT A FAMILY GATE, and these tests exist partly to keep it from
becoming one.  The bad value does not track the inverter family: a 6000XP
owner reports live ``Tinner`` of 31-32 °C alongside radiators at 58-65 °C in
EG4's own data table

    https://forum.eg4electronics.com/community/troubleshooting/3-6000xps-in-parallel-fans-do-not-run-at-low-wattage/

and ``MODEL_NAME_FAMILY_FALLBACK`` classifies the 6000XP as EG4_OFFGRID
exactly like the 12000XP — they share deviceTypeCode 54, which nothing can
split (#259/#307).  So the split is WITHIN the family, and gating by family
would suppress a sensor that demonstrably works on real hardware.  That is
the #307 over-gating failure, confirmed rather than hypothetical.

Instead only the observed VALUE is treated, and only on the source it was
observed on: a CLOUD-sourced ``internal_temperature`` of exactly 0 is
published as None (HA "unknown").  LOCAL/HYBRID read input register 64
directly and there is no evidence against that path.

ACCEPTED TRADE-OFF, pinned below: 0 °C is a physically legitimate reading, so
a unit genuinely sitting at 0 on a cloud connection now reads unknown instead
of 0 — the same caveat #348 raised for ``tBat``.  Small and bounded against a
permanently-wrong constant, and reversible in a way deleting the entity would
not be.
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
    blank_cloud_zero_internal_temperature,
)
from custom_components.eg4_web_monitor.sensor import _should_create_sensor

from .conftest import make_real_inverter

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


# ── The cloud-zero treatment ─────────────────────────────────────────


class TestCloudZeroBlanking:
    """A cloud ``tinner`` of exactly 0 becomes None; everything else passes."""

    def test_cloud_zero_becomes_none(self) -> None:
        """FAILS without the fix: the sensor published a bogus 0 °C forever."""
        sensors: dict[str, Any] = {"internal_temperature": 0}
        blank_cloud_zero_internal_temperature(sensors, False)
        assert sensors["internal_temperature"] is None

    def test_cloud_zero_key_is_kept_not_popped(self) -> None:
        """The key must survive as None so the entity reads unknown.

        Dropping the key entirely is the other available idiom in this module
        (``drop_offgrid_cloud_output_power`` pops), but a present-but-None
        value is what makes the sensor read "unknown" rather than risking an
        availability flip for keys shared with bank entities (#261).
        """
        sensors: dict[str, Any] = {"internal_temperature": 0}
        blank_cloud_zero_internal_temperature(sensors, False)
        assert "internal_temperature" in sensors

    def test_cloud_live_value_passes_through(self) -> None:
        """The 6000XP counterexample: a live cloud reading is never touched.

        This is the case that killed the family-gate approach — 31-32 °C
        reported on EG4's own data table by a 6000XP, which is EG4_OFFGRID.
        """
        for value in (31, 32, 41, 65):
            sensors: dict[str, Any] = {"internal_temperature": value}
            blank_cloud_zero_internal_temperature(sensors, False)
            assert sensors["internal_temperature"] == value

    def test_cloud_negative_value_passes_through(self) -> None:
        """A cold-climate install reporting below zero must survive.

        Guards the check being ``== 0`` rather than a falsy test or a
        ``<= 0``/``not value`` formulation that would swallow valid readings.
        """
        for value in (-1, -12, -30):
            sensors: dict[str, Any] = {"internal_temperature": value}
            blank_cloud_zero_internal_temperature(sensors, False)
            assert sensors["internal_temperature"] == value

    def test_cloud_none_stays_none(self) -> None:
        """An already-absent reading is unchanged (no key invented)."""
        sensors: dict[str, Any] = {"internal_temperature": None}
        blank_cloud_zero_internal_temperature(sensors, False)
        assert sensors["internal_temperature"] is None

    def test_missing_key_is_not_added(self) -> None:
        sensors: dict[str, Any] = {}
        blank_cloud_zero_internal_temperature(sensors, False)
        assert "internal_temperature" not in sensors

    def test_transport_backed_zero_survives(self) -> None:
        """FAILS without the source scoping: register 64 is never treated.

        pylxpweb's ``inverter_temperature`` is
        ``_raw_int("internal_temperature", "tinner")`` — it returns the
        transport register whenever transport runtime exists and only falls
        back to cloud ``tinner`` when it does not.  So a transport-backed 0
        is a genuine register-64 reading and must be published as 0.  There is
        no evidence against reg 64 on any family.
        """
        sensors: dict[str, Any] = {"internal_temperature": 0}
        blank_cloud_zero_internal_temperature(sensors, True)
        assert sensors["internal_temperature"] == 0

    def test_transport_backed_values_untouched(self) -> None:
        for value in (0, -5, 41, None):
            sensors: dict[str, Any] = {"internal_temperature": value}
            blank_cloud_zero_internal_temperature(sensors, True)
            assert sensors["internal_temperature"] == value

    def test_other_temperature_keys_untouched(self) -> None:
        """Only ``internal_temperature`` is treated; radiators read live."""
        sensors: dict[str, Any] = {
            "internal_temperature": 0,
            "radiator1_temperature": 0,
            "radiator2_temperature": 0,
            "battery_temperature": 0,
            "bt_temperature": 0,
        }
        blank_cloud_zero_internal_temperature(sensors, False)
        assert sensors["internal_temperature"] is None
        assert sensors["radiator1_temperature"] == 0
        assert sensors["radiator2_temperature"] == 0
        assert sensors["battery_temperature"] == 0
        assert sensors["bt_temperature"] == 0


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
    async def test_transport_backed_zero_survives_end_to_end(
        self, hass, cloud_config_entry
    ) -> None:
        """A LOCAL/HYBRID register-64 reading of 0 is published as 0.

        Transport runtime present means the value came from register 64, not
        cloud ``tinner`` — genuine, and never treated.
        """
        cloud_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, cloud_config_entry)

        runtime = InverterRuntimeData(internal_temperature=0)
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

        assert result["sensors"]["internal_temperature"] == 0


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

    Both real device forms must still be purged: the bare ``{serial}_{key}``
    and the legacy ``{serial}_runtime_{key}`` that the 3.2.x rows this purge
    exists to remove actually carry.  That legacy form is why an exact
    ``uid == f"{serial}_{key}"`` match is NOT usable here.

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
