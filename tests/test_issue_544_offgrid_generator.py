"""EG4_OFFGRID generator registers are not measurements (issue #544).

Proven from the reporting device's own firmware (12000XP, ``ceaa-0709``); the
full derivation with addresses lives in
``docs/reference/firmware/OFFGRID_GENERATOR_REGISTERS.md``:

  * Input reg 123 (``generator_power``) — the FC04 handler at ``SYNTH00113``
    returns ``RAM16[SYNTH00114]``, a word of the ARM comms processor's own RAM
    that a timer task increments once per second at ``SYNTH00115`` with no
    bound check, so it wraps at 65536.  It is seconds-since-boot, not watts.  A
    whole-image writer audit found only that increment and the power-on memset;
    no DSP measurement path reaches it.  The reporter's two samples fit the
    wrap exactly: ``(5610 - 28646) mod 65536 = 42500 s``, within 33 seconds of
    the real interval between the captures.
  * Input regs 124/125/126 (``generator_energy`` / ``_lifetime``) — ARM-local
    status words.  124 is byte-assembled from a frame byte plus a local
    bitmask; 125/126 are the halves of one 32-bit status bitfield, which is why
    a "lifetime" of 135,494.5 kWh decodes to the bit pattern ``SYNTH00116``.

Genuine on the same family and therefore NOT suppressed: ``generator_voltage``
(reg 121), ``generator_frequency`` (reg 122) and ``generator_voltage_l1/l2``
(regs 195/196) all read the DSP receive-frame block and correctly report 0 when
no generator is attached.

EG4_HYBRID is untouched: there reg 123 is measurement-derived from two DSP-fed
operands, and on a GridBOSS parallel system the inverters' values sum to the
GridBOSS AC-Couple-1 total within 0.13%.  These tests pin that the gate stays
family-scoped in BOTH directions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
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
    INVERTER_FAMILY_UNKNOWN,
)
from custom_components.eg4_web_monitor.const.device_types import (
    OFFGRID_EXCLUDED_SENSORS,
    OFFGRID_ONLY_SENSORS,
)
from custom_components.eg4_web_monitor.coordinator_mixins import (
    _derive_using_generator,
)
from custom_components.eg4_web_monitor.sensor import _should_create_sensor

# The three keys whose registers carry no measurement on EG4_OFFGRID.
SUPPRESSED = ("generator_power", "generator_energy", "generator_energy_lifetime")

# Real DSP-fed generator measurements on the same family — must survive.
KEPT = (
    "generator_voltage",
    "generator_frequency",
    "generator_voltage_l1",
    "generator_voltage_l2",
)


@pytest.fixture
def mock_config_entry():
    """Cloud config entry (matches the test_offgrid_registers.py fixture shape)."""
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
        entry_id="issue_544_test",
    )


class TestOffgridGeneratorSensorGating:
    """Entity creation is suppressed on EG4_OFFGRID only."""

    @pytest.mark.parametrize("sensor_key", SUPPRESSED)
    def test_suppressed_on_offgrid(self, sensor_key: str) -> None:
        """The counter/bitfield-backed sensors are not created on EG4_OFFGRID."""
        features = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}
        assert _should_create_sensor(sensor_key, features) is False

    @pytest.mark.parametrize("sensor_key", SUPPRESSED)
    @pytest.mark.parametrize(
        "family", [INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP]
    )
    def test_kept_on_other_families(self, sensor_key: str, family: str) -> None:
        """EG4_HYBRID/LXP keep them — reg 123 is a real measurement there."""
        assert _should_create_sensor(sensor_key, {"inverter_family": family}) is True

    @pytest.mark.parametrize("sensor_key", SUPPRESSED)
    @pytest.mark.parametrize(
        "features",
        [None, {}, {"inverter_family": INVERTER_FAMILY_UNKNOWN}],
        ids=["no-features", "empty-features", "family-UNKNOWN"],
    )
    def test_gate_fails_closed_while_family_unresolved(
        self, sensor_key: str, features: dict[str, str] | None
    ) -> None:
        """An unresolved family creates nothing — including literal "UNKNOWN".

        pylxpweb emits the truthy string ``UNKNOWN`` whenever the parameter
        fetch fails, so a ``!= EG4_OFFGRID`` test alone would recreate the bogus
        counter-backed sensor on exactly the hardware this gate protects.

        Failing closed costs nothing permanent: the key stays eligible for late
        registration and is re-evaluated with fresh features on the next changed
        cycle (see test_late_registration_creates_once_family_resolves).
        """
        assert _should_create_sensor(sensor_key, features) is False

    @pytest.mark.parametrize("sensor_key", SUPPRESSED)
    def test_late_registration_creates_once_family_resolves(
        self, sensor_key: str
    ) -> None:
        """The same key filtered while UNKNOWN is created once it resolves.

        Pins the self-healing property the fail-closed posture depends on:
        ``_async_discover_device_sensors`` re-runs this predicate with fresh
        features every changed cycle, so a genuine EG4_HYBRID Generator Power
        is not lost by a transient detection failure — it simply appears late.
        """
        unresolved = {"inverter_family": INVERTER_FAMILY_UNKNOWN}
        resolved = {"inverter_family": INVERTER_FAMILY_EG4_HYBRID}
        assert _should_create_sensor(sensor_key, unresolved) is False
        assert _should_create_sensor(sensor_key, resolved) is True

    @pytest.mark.parametrize("sensor_key", KEPT)
    def test_real_generator_measurements_survive_on_offgrid(
        self, sensor_key: str
    ) -> None:
        """Gen voltage/frequency/per-leg voltage are DSP-fed and must remain."""
        features = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}
        assert _should_create_sensor(sensor_key, features) is True

    def test_gridboss_generator_power_unaffected(self) -> None:
        """GridBOSS measures generator power with dedicated CT registers."""
        features = {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}
        assert _should_create_sensor("generator_power", features, "gridboss") is True
        assert (
            _should_create_sensor("generator_power", features, "parallel_group") is True
        )


class TestGateSetsAreDisjoint:
    """The two family gates must never claim the same key."""

    def test_offgrid_only_and_excluded_do_not_overlap(self) -> None:
        """Order-dependence contract.

        ``OFFGRID_ONLY_SENSORS`` is tested first and returns unconditionally, so
        a key in BOTH sets would be created on EG4_OFFGRID and this exclusion
        silently skipped.  They are disjoint today; this pins it so a future
        addition to either set fails loudly instead of quietly re-enabling a
        counter-backed sensor.
        """
        assert OFFGRID_ONLY_SENSORS & OFFGRID_EXCLUDED_SENSORS == frozenset()


class TestUsingGeneratorDerivation:
    """``is_using_generator`` no longer derives from ``generator_power > 0``."""

    def test_counter_value_does_not_imply_generator(self) -> None:
        """The exact #544 reading: a huge reg-123 value with a dead GEN port.

        pylxpweb would return True here (28646 > 0) — that is the bug.  With
        no generator the terminal reads 0 V / 0 Hz, so the answer is False.
        """
        inverter = SimpleNamespace(
            generator_voltage=0.0,
            generator_frequency=0.0,
            generator_power=28646,
            is_using_generator=True,
        )
        assert _derive_using_generator(inverter) is False

    def test_live_generator_detected(self) -> None:
        """An energised GEN terminal reports True regardless of reg 123."""
        inverter = SimpleNamespace(
            generator_voltage=240.1,
            generator_frequency=59.9,
            generator_power=0,
            is_using_generator=False,
        )
        assert _derive_using_generator(inverter) is True

    @pytest.mark.parametrize(
        ("voltage", "frequency"),
        [(240.0, 0.0), (0.0, 60.0)],
    )
    def test_requires_both_voltage_and_frequency(
        self, voltage: float, frequency: float
    ) -> None:
        """One live measurement alone is not a running generator."""
        inverter = SimpleNamespace(
            generator_voltage=voltage,
            generator_frequency=frequency,
            is_using_generator=True,
        )
        assert _derive_using_generator(inverter) is False

    def test_missing_measurement_is_unknown_not_library_fallback(self) -> None:
        """A partial read reports unknown — it must NOT consult the library.

        This is the trap: deferring to ``inverter.is_using_generator`` looks
        like a safe fallback but is exactly the broken ``generator_power > 0``
        predicate on the LOCAL/HYBRID path, where regs 121/122 can decode to
        ``None`` independently of reg 123 (different read blocks).  Falling back
        there would reintroduce #544 on a partial read.

        The cloud path never reaches this branch at all: ``InverterRuntime``
        declares ``genVolt``/``genFreq`` as non-optional ints defaulting to 0,
        so once a runtime exists both operands are always present.
        """
        inverter = SimpleNamespace(
            generator_voltage=None,
            generator_frequency=None,
            generator_power=28646,
            # Would be True via `generator_power > 0` — must not be consulted.
            is_using_generator=True,
        )
        assert _derive_using_generator(inverter) is None

    def test_partial_read_one_measurement_missing(self) -> None:
        """Only one of the pair decoded — still unknown, still no fallback."""
        inverter = SimpleNamespace(
            generator_voltage=0.0,
            generator_frequency=None,
            is_using_generator=True,
        )
        assert _derive_using_generator(inverter) is None


class TestOffgridGeneratorRegistryCleanup:
    """Existing bogus entities are purged, and only for resolved off-grid."""

    async def test_cleanup_is_family_scoped(self, hass, mock_config_entry) -> None:
        """Off-grid purged; hybrid, unresolved and GridBOSS all preserved.

        Without the purge the suppressed entities would linger forever as
        "unavailable" while still showing their last bogus value in history.
        The unresolved case matters most: pylxpweb emits ``UNKNOWN`` when a
        parameter fetch fails, so treating it as "family known" would let one
        transient read delete a hybrid user's real Generator Power entity.
        """
        from custom_components.eg4_web_monitor import async_setup_entry

        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)

        offgrid, hybrid, unknown, gridboss = (
            "SYNTH00117",
            "SYNTH00118",
            "SYNTH00119",
            "SYNTH00109",
        )
        uids = {
            f"{serial}_{key}"
            for serial in (offgrid, hybrid, unknown)
            for key in OFFGRID_EXCLUDED_SENSORS
        }
        # GridBOSS carries the same key name in its own device namespace.
        gridboss_uid = f"{gridboss}_generator_power"
        # A genuine off-grid generator measurement must not be collateral.
        offgrid_voltage_uid = f"{offgrid}_generator_voltage"
        for uid in {*uids, gridboss_uid, offgrid_voltage_uid}:
            registry.async_get_or_create(
                "sensor", DOMAIN, uid, config_entry=mock_config_entry
            )

        coordinator = MagicMock()
        coordinator._async_load_pv_string_lifetime_state = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.data = {
            "devices": {
                offgrid: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
                },
                hybrid: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
                },
                unknown: {"type": "inverter", "features": {}},
                gridboss: {"type": "gridboss", "features": {}},
            }
        }

        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            assert await async_setup_entry(hass, mock_config_entry)

        get_eid = registry.async_get_entity_id
        for key in OFFGRID_EXCLUDED_SENSORS:
            assert get_eid("sensor", DOMAIN, f"{offgrid}_{key}") is None, key
            assert get_eid("sensor", DOMAIN, f"{hybrid}_{key}") is not None, key
            assert get_eid("sensor", DOMAIN, f"{unknown}_{key}") is not None, key
        assert get_eid("sensor", DOMAIN, gridboss_uid) is not None
        assert get_eid("sensor", DOMAIN, offgrid_voltage_uid) is not None

        # Removing an enabled-by-default measurement sensor must be surfaced in
        # Repairs, not just an INFO log — and only for the device it happened to.
        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN, f"offgrid_generator_sensors_removed_{offgrid}"
            )
            is not None
        )
        for serial in (hybrid, unknown, gridboss):
            assert (
                issue_registry.async_get_issue(
                    DOMAIN, f"offgrid_generator_sensors_removed_{serial}"
                )
                is None
            )
