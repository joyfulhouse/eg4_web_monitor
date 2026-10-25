"""Keep identifying Repairs details out of HA's diagnostics wrapper."""

from dataclasses import replace
import hmac
import re

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import instance_id, issue_registry as ir
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

IssueSeverity = ir.IssueSeverity
_SALT: HassKey[bytes] = HassKey(f"{DOMAIN}_repair_identity")
_OPAQUE = re.compile(r"eg4_v2_[0-9a-f]{64}\Z")


@callback
def repair_issue_id(hass: HomeAssistant, legacy_id: str) -> str:
    """Return a stable installation-scoped pseudonym, never a raw identifier."""
    if _OPAQUE.fullmatch(legacy_id):
        return legacy_id
    if _SALT not in hass.data:
        raise RuntimeError("EG4 Repairs must be initialized before use")
    digest = hmac.digest(hass.data[_SALT], legacy_id.encode(), "sha256").hex()
    return f"eg4_v2_{digest}"


async def async_initialize(hass: HomeAssistant) -> None:
    """Initialize identity and migrate every domain repair before downloads."""
    if _SALT not in hass.data:
        hass.data[_SALT] = (await instance_id.async_get(hass)).encode()
    registry = ir.async_get(hass)
    removed: list[str] = []
    changed: dict[str, bool] = {}
    for domain, old_id in list(registry.issues):
        if domain != DOMAIN:
            continue
        # A prior legacy row may already have merged into this destination.
        old = registry.issues[(domain, old_id)]
        new_id = repair_issue_id(hass, old_id)
        if new_id == old_id:
            if old.is_persistent:
                registry.issues[(domain, new_id)] = replace(old, is_persistent=False)
                changed[new_id] = False
            continue

        existing = registry.async_get_issue(domain, new_id)
        if existing is None:
            migrated = replace(old, issue_id=new_id, is_persistent=False)
        else:
            # Keep an active warning and any dismissal; never reactivate two
            # inactive records or discard an earlier creation timestamp.
            details = existing if existing.active or not old.active else old
            migrated = replace(
                details,
                issue_id=new_id,
                is_persistent=False,
                active=existing.active or old.active,
                created=min(existing.created, old.created),
                dismissed_version=existing.dismissed_version or old.dismissed_version,
            )
        registry.issues[(domain, new_id)] = migrated
        del registry.issues[(domain, old_id)]
        removed.append(old_id)
        changed[new_id] = existing is None

    if not changed:
        return
    # HA has no rename API. Finish the synchronous rekey before notifying
    # listeners so they see one complete, state-preserving registry snapshot.
    registry.async_schedule_save()
    for old_id in removed:
        hass.bus.async_fire_internal(
            ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED,
            ir.EventIssueRegistryUpdatedData(
                action="remove", domain=DOMAIN, issue_id=old_id
            ),
        )
    for new_id, created in changed.items():
        hass.bus.async_fire_internal(
            ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED,
            ir.EventIssueRegistryUpdatedData(
                action="create" if created else "update", domain=DOMAIN, issue_id=new_id
            ),
        )


@callback
def async_create_issue(
    hass: HomeAssistant,
    domain: str,
    issue_id: str,
    *,
    is_fixable: bool,
    severity: ir.IssueSeverity,
    translation_key: str,
    translation_placeholders: dict[str, str] | None = None,
) -> None:
    """Keep UI context in memory; HA omits it from nonpersistent downloads."""
    if domain != DOMAIN:
        raise ValueError("EG4 Repairs adapter cannot own another domain")
    ir.async_create_issue(
        hass,
        domain,
        repair_issue_id(hass, issue_id),
        is_fixable=is_fixable,
        is_persistent=False,
        severity=severity,
        translation_key=translation_key,
        translation_placeholders=translation_placeholders,
    )


@callback
def async_delete_issue(hass: HomeAssistant, domain: str, issue_id: str) -> None:
    """Recovery clears both the current identity and any unmigrated legacy row."""
    if domain != DOMAIN:
        raise ValueError("EG4 Repairs adapter cannot own another domain")
    current_id = repair_issue_id(hass, issue_id)
    ir.async_delete_issue(hass, domain, current_id)
    if current_id != issue_id:
        ir.async_delete_issue(hass, domain, issue_id)
