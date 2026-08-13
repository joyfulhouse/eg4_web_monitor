"""Regression tests for parallel-group registry ID migration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import async_setup_entry
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_HTTP,
    DOMAIN,
)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Parallel migration",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        entry_id="parallel-migration-entry",
    )


def _seed_group(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    identifier: str,
) -> tuple[dr.DeviceEntry, er.RegistryEntry]:
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, identifier)},
        name=identifier,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{identifier}_power",
        config_entry=entry,
        device_id=device.id,
    )
    return device, entity


async def _run_setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    groups: dict[str, list[str]],
) -> None:
    coordinator = MagicMock()
    coordinator._async_load_pv_string_lifetime_state = AsyncMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.data = {
        "devices": {
            group_id: {
                "type": "parallel_group",
                "member_serials": member_serials,
            }
            for group_id, member_serials in groups.items()
        },
        "device_info": {},
        "parameters": {},
    }

    with (
        patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry)


async def test_two_groups_migrate_by_member_not_lexical_order(
    hass: HomeAssistant,
) -> None:
    """Old master serials must select the group that actually contains them."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_100, entity_100 = _seed_group(hass, entry, "parallel_group_100")
    old_200, entity_200 = _seed_group(hass, entry, "parallel_group_200")

    await _run_setup(
        hass,
        entry,
        {
            "parallel_group_a": ["200", "201"],
            "parallel_group_b": ["100", "101"],
        },
    )

    entity_registry = er.async_get(hass)
    migrated_100_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "parallel_group_b_power"
    )
    migrated_200_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "parallel_group_a_power"
    )
    assert migrated_100_id is not None
    assert migrated_200_id is not None
    assert entity_registry.async_get(migrated_100_id).id == entity_100.id
    assert entity_registry.async_get(migrated_200_id).id == entity_200.id
    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_100.id).identifiers == {
        (DOMAIN, "parallel_group_b")
    }
    assert device_registry.async_get(old_200.id).identifiers == {
        (DOMAIN, "parallel_group_a")
    }
    assert device_registry.async_get_device({(DOMAIN, "parallel_group_100")}) is None
    assert device_registry.async_get_device({(DOMAIN, "parallel_group_200")}) is None


async def test_no_authoritative_group_is_non_destructive(
    hass: HomeAssistant,
) -> None:
    """An empty first refresh must preserve the old device and entity."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, old_entity = _seed_group(hass, entry, "parallel_group_100")

    await _run_setup(hass, entry, {})

    assert dr.async_get(hass).async_get(old_device.id) is not None
    assert er.async_get(hass).async_get(old_entity.entity_id).unique_id == (
        "parallel_group_100_power"
    )


async def test_group_without_members_is_non_destructive(
    hass: HomeAssistant,
) -> None:
    """A name alone is not authoritative evidence for a legacy serial."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, old_entity = _seed_group(hass, entry, "parallel_group_100")

    await _run_setup(hass, entry, {"parallel_group_a": []})

    assert dr.async_get(hass).async_get(old_device.id) is not None
    assert er.async_get(hass).async_get(old_entity.entity_id).unique_id == (
        "parallel_group_100_power"
    )


async def test_ambiguous_membership_is_non_destructive(
    hass: HomeAssistant,
) -> None:
    """A serial present in multiple reported groups is not safe to migrate."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, old_entity = _seed_group(hass, entry, "parallel_group_100")

    await _run_setup(
        hass,
        entry,
        {
            "parallel_group_a": ["100"],
            "parallel_group_b": ["100"],
        },
    )

    assert dr.async_get(hass).async_get(old_device.id) is not None
    assert er.async_get(hass).async_get(old_entity.entity_id).unique_id == (
        "parallel_group_100_power"
    )


async def test_two_old_ids_claiming_one_group_are_non_destructive(
    hass: HomeAssistant,
) -> None:
    """A many-to-one membership claim cannot identify the historical group."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_100, entity_100 = _seed_group(hass, entry, "parallel_group_100")
    old_101, entity_101 = _seed_group(hass, entry, "parallel_group_101")

    await _run_setup(hass, entry, {"parallel_group_a": ["100", "101"]})

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_100.id) is not None
    assert device_registry.async_get(old_101.id) is not None
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(entity_100.entity_id).unique_id == (
        "parallel_group_100_power"
    )
    assert entity_registry.async_get(entity_101.entity_id).unique_id == (
        "parallel_group_101_power"
    )


async def test_existing_target_collision_is_idempotent(
    hass: HomeAssistant,
) -> None:
    """A completed target wins without replacing its registry entry."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, old_entity = _seed_group(hass, entry, "parallel_group_100")
    target_device, target_entity = _seed_group(hass, entry, "parallel_group_a")

    groups = {"parallel_group_a": ["100", "101"]}
    await _run_setup(hass, entry, groups)
    await _run_setup(hass, entry, groups)

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_device.id) is None
    assert device_registry.async_get(target_device.id) is not None
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(old_entity.entity_id) is None
    current_target = entity_registry.async_get(target_entity.entity_id)
    assert current_target is not None
    assert current_target.id == target_entity.id
    assert current_target.unique_id == "parallel_group_a_power"


async def _run_setup_with_devices(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    devices: dict,
) -> None:
    coordinator = MagicMock()
    coordinator._async_load_pv_string_lifetime_state = AsyncMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.data = {"devices": devices, "device_info": {}, "parameters": {}}

    with (
        patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry)


async def test_gridboss_legacy_id_migrates_via_one_to_one_fallback(
    hass: HomeAssistant,
) -> None:
    """A GridBOSS-derived legacy ID (never in member_serials) still migrates
    when there is exactly one legacy ID, one current group, and the legacy
    serial is a live device of this plant (#517 review P1)."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, old_entity = _seed_group(hass, entry, "parallel_group_SYNTH00109")

    await _run_setup_with_devices(
        hass,
        entry,
        {
            "parallel_group_a": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00130", "SYNTH00131"],
                "first_device_serial": "SYNTH00130",
            },
            "SYNTH00109": {"type": "mid", "model": "GridBOSS"},
            "SYNTH00130": {"type": "inverter"},
            "SYNTH00131": {"type": "inverter"},
        },
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_device.id).identifiers == {
        (DOMAIN, "parallel_group_a")
    }
    entity_registry = er.async_get(hass)
    migrated = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "parallel_group_a_power"
    )
    assert migrated is not None
    assert entity_registry.async_get(migrated).id == old_entity.id


async def test_gridboss_legacy_id_with_two_groups_is_non_destructive(
    hass: HomeAssistant,
) -> None:
    """The one-to-one fallback never guesses between multiple current groups."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, _ = _seed_group(hass, entry, "parallel_group_SYNTH00109")

    await _run_setup_with_devices(
        hass,
        entry,
        {
            "parallel_group_a": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00130"],
            },
            "parallel_group_b": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00132"],
            },
            "SYNTH00109": {"type": "mid", "model": "GridBOSS"},
        },
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_device.id).identifiers == {
        (DOMAIN, "parallel_group_SYNTH00109")
    }


async def test_foreign_legacy_serial_is_non_destructive(
    hass: HomeAssistant,
) -> None:
    """A legacy serial that is not a live device of this plant never matches."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, _ = _seed_group(hass, entry, "parallel_group_SYNTH00110")

    await _run_setup_with_devices(
        hass,
        entry,
        {
            "parallel_group_a": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00130"],
            },
            "SYNTH00130": {"type": "inverter"},
        },
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_device.id).identifiers == {
        (DOMAIN, "parallel_group_SYNTH00110")
    }


async def test_master_serial_matches_via_first_device_serial(
    hass: HomeAssistant,
) -> None:
    """The modern master serial is membership evidence even when absent from
    member_serials."""
    entry = _entry()
    entry.add_to_hass(hass)
    old_device, _ = _seed_group(hass, entry, "parallel_group_SYNTH00111")
    _seed_group(hass, entry, "parallel_group_SYNTH00112")

    await _run_setup_with_devices(
        hass,
        entry,
        {
            "parallel_group_a": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00126"],
                "first_device_serial": "SYNTH00111",
            },
            "parallel_group_b": {
                "type": "parallel_group",
                "member_serials": ["SYNTH00112"],
            },
        },
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(old_device.id).identifiers == {
        (DOMAIN, "parallel_group_a")
    }
