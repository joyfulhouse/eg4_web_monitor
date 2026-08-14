"""Tests for hybrid EPS apparent-power exclusions (#548)."""

from __future__ import annotations

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
    HYBRID_EXCLUDED_SENSORS,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_LXP,
    INVERTER_FAMILY_UNKNOWN,
)
from custom_components.eg4_web_monitor.const.device_types import (
    OFFGRID_EXCLUDED_SENSORS,
    SPLIT_PHASE_ONLY_SENSORS,
)
from custom_components.eg4_web_monitor.sensor import _should_create_sensor

SUPPRESSED = frozenset({"eps_apparent_power_l1", "eps_apparent_power_l2"})


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a cloud config entry for registry-cleanup coverage."""
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
        entry_id="issue_548_test",
    )


class TestHybridEpsApparentPowerSensorGating:
    """Entity creation is suppressed on EG4_HYBRID only."""

    def test_exclusion_set_is_exported_and_topology_scoped(self) -> None:
        """The semantic exclusion remains layered on split-phase capability."""
        excluded = HYBRID_EXCLUDED_SENSORS
        assert excluded == SUPPRESSED
        assert excluded <= SPLIT_PHASE_ONLY_SENSORS
        assert excluded & OFFGRID_EXCLUDED_SENSORS == frozenset()

    def test_family_and_capability_matrix(self) -> None:
        """Pin fail-closed resolution, split-phase gating, and family scope."""
        hybrid = {
            "inverter_family": INVERTER_FAMILY_EG4_HYBRID,
            "supports_split_phase": True,
        }
        offgrid = {
            "inverter_family": INVERTER_FAMILY_EG4_OFFGRID,
            "supports_split_phase": True,
        }
        non_split_offgrid = {
            "inverter_family": INVERTER_FAMILY_EG4_OFFGRID,
            "supports_split_phase": False,
        }
        unresolved: tuple[dict[str, str] | None, ...] = (
            None,
            {},
            {"inverter_family": INVERTER_FAMILY_UNKNOWN},
        )

        for sensor_key in SUPPRESSED:
            # Split-phase hybrids must not expose the mislabelled registers.
            assert _should_create_sensor(sensor_key, hybrid) is False, sensor_key

            # The registers are genuine on EG4_OFFGRID, but the existing
            # split-phase capability gate remains authoritative.
            assert _should_create_sensor(sensor_key, offgrid) is True, sensor_key
            assert _should_create_sensor(sensor_key, non_split_offgrid) is False, (
                sensor_key
            )

            # Missing family detection and pylxpweb's literal UNKNOWN defer
            # creation.  A later resolved off-grid cycle makes the key eligible.
            for features in unresolved:
                assert _should_create_sensor(sensor_key, features) is False, (
                    sensor_key,
                    features,
                )
            assert _should_create_sensor(sensor_key, offgrid) is True, sensor_key

            # Only inverter entities are family-gated.
            assert _should_create_sensor(sensor_key, hybrid, "gridboss") is True
            assert _should_create_sensor(sensor_key, hybrid, "parallel_group") is True

        # Aggregate register 25 stays, and the exclusion is a positive family
        # check rather than a model-name substring test.
        assert (
            _should_create_sensor(
                "eps_apparent_power",
                {
                    "inverter_family": INVERTER_FAMILY_EG4_HYBRID,
                    "supports_three_phase": False,
                },
            )
            is True
        )
        assert (
            _should_create_sensor(
                "eps_apparent_power_l1",
                {
                    "inverter_family": INVERTER_FAMILY_LXP,
                    "supports_split_phase": True,
                },
            )
            is True
        )


class TestHybridEpsApparentPowerRegistryCleanup:
    """Existing bogus entities are purged only for resolved hybrids."""

    async def test_cleanup_is_family_and_namespace_scoped(
        self, hass, mock_config_entry: MockConfigEntry
    ) -> None:
        """Purge hybrid device sensors and preserve every adjacent namespace."""
        from custom_components.eg4_web_monitor import async_setup_entry

        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)

        hybrid = "1000000001"
        offgrid = "1000000002"
        unknown = "1000000003"
        missing = "1000000004"
        lxp = "1000000005"
        gridboss = "SYNTH00002"

        for serial in (hybrid, offgrid, unknown, missing, lxp):
            for key in SUPPRESSED:
                registry.async_get_or_create(
                    "sensor",
                    DOMAIN,
                    f"{serial}_{key}",
                    config_entry=mock_config_entry,
                )

        # Defensive legacy device namespace: cleanup supports this shape.
        legacy_hybrid_uid = f"{hybrid}_runtime_eps_apparent_power_l1"
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            legacy_hybrid_uid,
            config_entry=mock_config_entry,
        )

        # Same suffix outside the inverter-device namespace must survive.
        battery_uid = f"{hybrid}_BAT001_eps_apparent_power_l1"
        gridboss_uid = f"{gridboss}_eps_apparent_power_l1"
        aggregate_uid = f"{hybrid}_eps_apparent_power"
        real_power_uid = f"{hybrid}_eps_power_l1"
        for uid in (battery_uid, gridboss_uid, aggregate_uid, real_power_uid):
            registry.async_get_or_create(
                "sensor", DOMAIN, uid, config_entry=mock_config_entry
            )

        coordinator = MagicMock()
        coordinator._async_load_pv_string_lifetime_state = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.data = {
            "devices": {
                hybrid: {
                    "type": "inverter",
                    "model": "18kPV",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
                },
                offgrid: {
                    "type": "inverter",
                    "model": "12000XP",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
                },
                unknown: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_UNKNOWN},
                },
                missing: {"type": "inverter", "features": {}},
                lxp: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_LXP},
                },
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
        for key in SUPPRESSED:
            assert get_eid("sensor", DOMAIN, f"{hybrid}_{key}") is None, key
            for serial in (offgrid, unknown, missing, lxp):
                assert get_eid("sensor", DOMAIN, f"{serial}_{key}") is not None, (
                    serial,
                    key,
                )

        assert get_eid("sensor", DOMAIN, legacy_hybrid_uid) is None
        for uid in (battery_uid, gridboss_uid, aggregate_uid, real_power_uid):
            assert get_eid("sensor", DOMAIN, uid) is not None, uid

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN, f"hybrid_eps_apparent_power_sensors_removed_{hybrid}"
            )
            is not None
        )
        for serial in (offgrid, unknown, missing, lxp, gridboss):
            assert (
                issue_registry.async_get_issue(
                    DOMAIN, f"hybrid_eps_apparent_power_sensors_removed_{serial}"
                )
                is None
            )
