"""Low-churn runtime discovery for capability-gated control entities.

Control capabilities arrive in stages: the first coordinator snapshot can know
that a device exists before pylxpweb has resolved its inverter family, model, or
local transport.  Requiring a config-entry reload at that boundary is both
surprising and racy.  This module keeps one capability signature per platform,
rebuilds candidates only when that signature changes, and preserves entities
that have already been registered while marking them unsupported.
"""

from collections.abc import Callable, Hashable, Mapping, Sequence
import logging
import re
from typing import Any

from homeassistant.const import ATTR_RESTORED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import EG4OptimisticEntity
from .const import DOMAIN
from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
_UNSET = object()

EntityFactory = Callable[[], Sequence[EG4OptimisticEntity]]
ExtraSignatureFactory = Callable[[], Any]


def _freeze(value: Any) -> Hashable:
    """Convert nested capability metadata into a deterministic hashable value."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(repr(_freeze(item)) for item in value))
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    return repr(value)


def control_capability_signature(
    coordinator: EG4DataUpdateCoordinator,
    extra_signature: ExtraSignatureFactory | None = None,
) -> Hashable:
    """Return only metadata that can change the set of control entities.

    Fast sensor/parameter values are intentionally excluded.  Rebuilding every
    control object on every coordinator poll would turn late discovery into a
    persistent allocation and registry-lookup cost.
    """
    devices = (coordinator.data or {}).get("devices", {})
    device_signature = tuple(
        sorted(
            (
                str(serial),
                _freeze(device_data.get("type")),
                _freeze(device_data.get("model")),
                _freeze(device_data.get("features")),
            )
            for serial, device_data in devices.items()
        )
    )
    extra = _freeze(extra_signature()) if extra_signature is not None else None
    return device_signature, extra


def _migrate_model_prefixed_unique_ids(
    hass: HomeAssistant,
    config_entry: Any,
    platform: str,
    entities: list[EG4OptimisticEntity],
    warned_conflicts: set[str],
) -> set[str]:
    """Migrate ``{model}_{serial}_{key}`` IDs to ``{serial}_{key}`` in place.

    Number and time entities historically embedded the discovered model.  A
    model transition therefore registered a second entity, and a model that
    changed more than once (HYBRID reports differ between the portal and the
    transport) left one legacy entry per model (#656).  Matching the full new
    unique ID as a suffix identifies every legacy entry for the same control
    in this config entry.

    Nothing can recreate a model-prefixed ID, so every match is the same
    control. If no stable entry exists, one legacy entry is kept by rewriting
    its unique ID, preferring enabled, then most recently created where HA
    recorded it. Ties prefer an entity ID without a numeric suffix, then lexical
    entity-ID ordering. An existing stable entry in this config entry is always
    kept untouched; the legacy entries are removed unless they back loaded
    entities. Return conflicted IDs to skip registration when a different config
    entry owns the stable identity.
    """
    entry_id = getattr(config_entry, "entry_id", None)
    if not isinstance(entry_id, str):
        return set()

    registry = er.async_get(hass)
    registry_entries = [
        entry
        for entry in er.async_entries_for_config_entry(registry, entry_id)
        if entry.domain == platform and entry.platform == DOMAIN
    ]
    conflicts: set[str] = set()

    for entity in entities:
        unique_id = entity.unique_id
        if not unique_id:
            continue

        suffix = f"_{unique_id}"
        matches = [
            entry for entry in registry_entries if entry.unique_id.endswith(suffix)
        ]
        stable_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        stable = registry.async_get(stable_id) if stable_id is not None else None
        if stable is not None and stable.config_entry_id != entry_id:
            conflicts.add(unique_id)
            if unique_id not in warned_conflicts:
                warned_conflicts.add(unique_id)
                _LOGGER.warning(
                    "Skipping %s control identity %s: stable entity %s belongs to "
                    "config entry %s, not %s",
                    platform,
                    unique_id,
                    stable.entity_id,
                    stable.config_entry_id,
                    entry_id,
                )
            continue

        if not matches:
            continue

        if stable is None:
            keep = min(
                matches,
                key=lambda entry: (
                    entry.disabled_by is not None,
                    -entry.created_at.timestamp(),
                    re.search(r"_\d+$", entry.entity_id) is not None,
                    entry.entity_id,
                ),
            )
            matches.remove(keep)
            registry_entries.remove(keep)
            registry.async_update_entity(keep.entity_id, new_unique_id=unique_id)
            _LOGGER.info(
                "Migrated %s control identity %s -> %s",
                platform,
                keep.unique_id,
                unique_id,
            )

        for legacy in matches:
            if _backs_loaded_entity(hass, legacy.entity_id):
                continue
            registry.async_remove(legacy.entity_id)
            registry_entries.remove(legacy)
            _LOGGER.warning(
                "Removed superseded %s control %s (legacy identity %s)",
                platform,
                legacy.entity_id,
                legacy.unique_id,
            )
    return conflicts


def _backs_loaded_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether a live entity, not a startup placeholder, owns the ID."""
    state = hass.states.get(entity_id)
    return state is not None and not state.attributes.get(ATTR_RESTORED, False)


def setup_control_entity_discovery(
    hass: HomeAssistant,
    config_entry: Any,
    coordinator: EG4DataUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
    entity_factory: EntityFactory,
    *,
    platform: str,
    extra_signature: ExtraSignatureFactory | None = None,
    migrate_model_prefix: bool = False,
    update_before_add: bool = False,
) -> None:
    """Add current controls and converge their active set on later updates."""
    known_entities: dict[str, EG4OptimisticEntity] = {}
    warned_conflicts: set[str] = set()
    previous_signature: object = _UNSET

    @callback
    def _rediscover_controls() -> None:
        nonlocal previous_signature
        signature = control_capability_signature(coordinator, extra_signature)
        if signature == previous_signature:
            return

        candidates = entity_factory()
        active_ids = {
            unique_id
            for entity in candidates
            if (unique_id := entity.unique_id) is not None
        }
        for unique_id, entity in known_entities.items():
            entity._set_control_discovery_supported(unique_id in active_ids)

        new_by_id: dict[str, EG4OptimisticEntity] = {}
        for entity in candidates:
            unique_id = entity.unique_id
            if (
                unique_id is None
                or unique_id in known_entities
                or unique_id in new_by_id
            ):
                continue
            entity._set_control_discovery_supported(True)
            new_by_id[unique_id] = entity

        if not new_by_id:
            previous_signature = signature
            return
        new_entities = list(new_by_id.values())
        if migrate_model_prefix:
            conflicts = _migrate_model_prefixed_unique_ids(
                hass, config_entry, platform, new_entities, warned_conflicts
            )
            new_by_id = {
                unique_id: entity
                for unique_id, entity in new_by_id.items()
                if unique_id not in conflicts
            }
            new_entities = list(new_by_id.values())
        _LOGGER.info(
            "Discovered %d new %s control entities (%d active, %d retained)",
            len(new_entities),
            platform,
            len(active_ids),
            len(known_entities) + len(new_entities),
        )
        async_add_entities(new_entities, update_before_add=update_before_add)
        known_entities.update(new_by_id)
        previous_signature = signature

    # Register before adding entities so the capability callback runs before
    # their CoordinatorEntity listeners on each update.  Availability therefore
    # converges in the same tick rather than one poll later.
    config_entry.async_on_unload(coordinator.async_add_listener(_rediscover_controls))
    _rediscover_controls()
