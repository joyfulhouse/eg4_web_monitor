"""Repairs migration preserves lifecycle state without serializing identifiers."""

from dataclasses import replace
from datetime import timedelta
import json
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import instance_id, issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import flush_store

from custom_components.eg4_web_monitor import repair_registry as repairs
from custom_components.eg4_web_monitor.const import DOMAIN


def _seed(
    registry,
    issue_id,
    *,
    domain=DOMAIN,
    active=True,
    dismissed=None,
    persistent=True,
    translation="connection_failed",
    age=0,
):
    issue = registry.async_get_or_create(
        domain,
        issue_id,
        is_fixable=False,
        is_persistent=persistent,
        severity=ir.IssueSeverity.WARNING,
        translation_key=translation,
        translation_placeholders={"serial": "SYNTH00001", "host": "192.0.2.37"},
        data={"serial": "SYNTH00001"},
        learn_more_url="https://example.invalid/device/SYNTH00001",
    )
    issue = replace(
        issue,
        active=active,
        dismissed_version=dismissed,
        created=dt_util.utcnow() - timedelta(days=age),
    )
    registry.issues[(domain, issue_id)] = issue
    return issue


@pytest.mark.parametrize("active", [False, True])
async def test_migration_preserves_history_and_is_idempotent(hass, active):
    """Migration cannot reactivate an inactive issue or discard its dismissal."""
    registry = ir.async_get(hass)
    legacy_id = "transport_failed_SYNTH00001_192.0.2.37"
    original = _seed(registry, legacy_id, active=active, dismissed="2026.10.0", age=4)
    other = _seed(registry, legacy_id, domain="unrelated_integration")

    await repairs.async_initialize(hass)

    opaque_id = repairs.repair_issue_id(hass, legacy_id)
    issue = registry.async_get_issue(DOMAIN, opaque_id)
    assert issue == replace(original, issue_id=opaque_id, is_persistent=False)
    assert registry.async_get_issue(DOMAIN, legacy_id) is None
    assert registry.async_get_issue("unrelated_integration", legacy_id) is other
    encoded = json.dumps(issue.to_json())
    assert "SYNTH00001" not in encoded
    assert "192.0.2.37" not in encoded
    assert issue.translation_placeholders == original.translation_placeholders

    with patch.object(registry, "async_schedule_save") as save:
        await repairs.async_initialize(hass)
        await repairs.async_initialize(hass)
    save.assert_not_called()
    assert registry.async_get_issue(DOMAIN, opaque_id) is issue
    assert repairs.repair_issue_id(hass, opaque_id) == opaque_id


@pytest.mark.parametrize("opaque_first", [False, True])
@pytest.mark.parametrize("opaque_persistent", [False, True])
@pytest.mark.parametrize(
    "legacy_active,opaque_active",
    [(False, False), (True, False), (False, True), (True, True)],
)
async def test_collision_preserves_history_regardless_of_insertion_order(
    hass, opaque_first, opaque_persistent, legacy_active, opaque_active
):
    """A later persistent opaque snapshot must not overwrite a merged record."""
    await repairs.async_initialize(hass)
    registry = ir.async_get(hass)
    legacy_id = "duplicate_cloud_entry_SYNTHETIC_ENTRY"
    opaque_id = repairs.repair_issue_id(hass, legacy_id)
    definitions = [
        (
            legacy_id,
            {
                "active": legacy_active,
                "dismissed": "2026.9.0",
                "age": 7,
                "translation": "legacy_details",
            },
        ),
        (
            opaque_id,
            {
                "active": opaque_active,
                "translation": "current_details",
                "persistent": opaque_persistent,
            },
        ),
    ]
    if opaque_first:
        definitions.reverse()
    seeded = {key: _seed(registry, key, **kwargs) for key, kwargs in definitions}

    await repairs.async_initialize(hass)

    issue = registry.async_get_issue(DOMAIN, opaque_id)
    assert registry.async_get_issue(DOMAIN, legacy_id) is None
    assert issue.is_persistent is False
    assert issue.active is (legacy_active or opaque_active)
    assert issue.created == seeded[legacy_id].created
    assert issue.dismissed_version == "2026.9.0"
    expected_details = (
        "current_details" if opaque_active or not legacy_active else "legacy_details"
    )
    assert issue.translation_key == expected_details
    before = dict(registry.issues)
    await repairs.async_initialize(hass)
    assert registry.issues == before


async def test_existing_opaque_dismissal_survives_collision(hass):
    """A stale legacy dismissal must not replace the current issue's dismissal."""
    await repairs.async_initialize(hass)
    registry = ir.async_get(hass)
    legacy_id = "parameter_read_SYNTH00001"
    opaque_id = repairs.repair_issue_id(hass, legacy_id)
    _seed(registry, legacy_id, dismissed="2026.9.0")
    _seed(registry, opaque_id, dismissed="2026.10.0")
    await repairs.async_initialize(hass)
    assert registry.async_get_issue(DOMAIN, opaque_id).dismissed_version == "2026.10.0"


async def test_recovery_deletes_both_identities_without_touching_other_domain(hass):
    """Recovery also cleans a legacy row created after initialization."""
    await repairs.async_initialize(hass)
    registry = ir.async_get(hass)
    legacy_id = "transport_failed_SYNTH00001"
    opaque_id = repairs.repair_issue_id(hass, legacy_id)
    repairs.async_create_issue(
        hass,
        DOMAIN,
        legacy_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_failed",
        translation_placeholders={"serial": "SYNTH00001"},
    )
    assert registry.async_get_issue(DOMAIN, opaque_id).is_persistent is False
    _seed(registry, legacy_id)
    other = _seed(registry, legacy_id, domain="other_domain")

    repairs.async_delete_issue(hass, DOMAIN, legacy_id)
    repairs.async_delete_issue(hass, DOMAIN, legacy_id)

    assert registry.async_get_issue(DOMAIN, opaque_id) is None
    assert registry.async_get_issue(DOMAIN, legacy_id) is None
    assert registry.async_get_issue("other_domain", legacy_id) is other


async def test_storage_reload_keeps_identity_and_dismissal_but_requires_recreation(
    hass: HomeAssistant, hass_storage
):
    """Stable instance identity allows nonpersistent repairs to be recreated safely."""
    registry = ir.async_get(hass)
    legacy_id = "duplicate_cloud_entry_SYNTHETIC_ENTRY"
    original = _seed(registry, legacy_id, dismissed="2026.10.0", age=3)
    await repairs.async_initialize(hass)
    opaque_id = repairs.repair_issue_id(hass, legacy_id)
    await flush_store(registry._store)

    serialized = json.dumps(hass_storage[ir.STORAGE_KEY])
    assert "SYNTHETIC_ENTRY" not in serialized
    assert "SYNTH00001" not in serialized
    assert "192.0.2.37" not in serialized
    stored_instance_id = hass_storage[instance_id.DATA_KEY]["data"]["uuid"]

    # Evict both caches to force the installation identity to reload from storage.
    hass.data.pop(repairs._SALT)
    hass.data.pop(instance_id.DATA_KEY)
    await repairs.async_initialize(hass)
    assert await instance_id.async_get(hass) == stored_instance_id
    assert repairs.repair_issue_id(hass, legacy_id) == opaque_id

    reloaded = ir.IssueRegistry(hass)
    await reloaded.async_load()
    issue = reloaded.async_get_issue(DOMAIN, opaque_id)
    assert issue is not None
    assert issue.active is False
    assert issue.dismissed_version == original.dismissed_version
    assert issue.created == original.created
    assert issue.translation_placeholders is None

    with patch.object(ir, "async_get", return_value=reloaded):
        repairs.async_create_issue(
            hass,
            DOMAIN,
            legacy_id,
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="duplicate_cloud_entry",
            translation_placeholders={"entry": "SYNTHETIC_ENTRY"},
        )
    recreated = reloaded.async_get_issue(DOMAIN, opaque_id)
    assert recreated.active is True
    assert recreated.dismissed_version == original.dismissed_version
    assert recreated.created == original.created
    assert recreated.translation_key == "duplicate_cloud_entry"
    assert recreated.translation_placeholders == {"entry": "SYNTHETIC_ENTRY"}
    assert "SYNTHETIC_ENTRY" not in json.dumps(recreated.to_json())
