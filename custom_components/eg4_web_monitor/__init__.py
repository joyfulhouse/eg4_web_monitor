"""EG4 Web Monitor integration for Home Assistant."""

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any, TypeAlias

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
import homeassistant.helpers.issue_registry as ir
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store

from ._config_flow.helpers import (
    cloud_unique_id_from_data,
    find_config_entry_identity_conflicts,
    migrate_legacy_entry,
)
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DOMAIN,
    HYBRID_EXCLUDED_SENSORS,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_UNKNOWN,
    MANUFACTURER,
    MIN_HTTP_POLLING_INTERVAL,
    OFFGRID_EXCLUDED_SENSORS,
)
from .coordinator import (
    PV_STRING_LIFETIME_STORAGE_KEY,
    PV_STRING_LIFETIME_STORAGE_VERSION,
    EG4DataUpdateCoordinator,
)
from .coordinator_mappings import (
    GRIDBOSS_SMART_PORT_DYNAMIC_KEYS,
    SMART_PORT_VALIDATED_KEY,
)

# Home Assistant resolves the per-device Delete hook by name on the
# component module; the redundant alias marks the re-export (#174).
from .device_removal import (
    async_remove_config_entry_device as async_remove_config_entry_device,
)
from .history_import import (
    IMPORT_HISTORICAL_DATA_SCHEMA,
    SERVICE_IMPORT_HISTORICAL_DATA,
    async_import_historical_data,
)
from .services import (
    FETCH_EVENTS_SCHEMA,
    async_fetch_events,
    async_reconcile_history,
)

_LOGGER = logging.getLogger(__name__)

# Type alias for typed ConfigEntry (Python 3.11 compatible)
EG4ConfigEntry: TypeAlias = ConfigEntry[EG4DataUpdateCoordinator]

# Sensor platform must be set up first to create parent devices (parallel groups,
# battery banks) before other platforms register entities that reference them
# via via_device.  The remaining platforms can load concurrently.
SENSOR_PLATFORM: list[Platform] = [Platform.SENSOR]
OTHER_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
    Platform.UPDATE,
]
PLATFORMS: list[Platform] = SENSOR_PLATFORM + OTHER_PLATFORMS

# Sensor keys removed in the charge/discharge consolidation refactor.
# Existing installations may have entity registry entries for these;
# they are cleaned up once during async_setup_entry().
#
# NOTE: "_battery_discharge_power" is intentionally ABSENT — the per-inverter
# battery_discharge_power sensor was reintroduced for EG4_OFFGRID (reg 11 /
# cloud pDisCharge, issue #197).  Keeping the suffix here would delete the new
# entity's registry entry on every setup.  "_parallel_battery_discharge_power"
# below does NOT match the per-inverter unique_id (suffix matching requires
# the literal "parallel" segment).
_DEPRECATED_CHARGE_DISCHARGE_SUFFIXES: frozenset[str] = frozenset(
    {
        "_battery_charge_power",
        "_battery_bank_charge_power",
        "_battery_bank_discharge_power",
        "_parallel_battery_charge_power",
        "_parallel_battery_discharge_power",
        "_battery_discharge_rate",
        "_battery_bank_discharge_rate",
        "_parallel_battery_discharge_rate",
    }
)

# Sensor keys removed because they duplicated another sensor's value; the
# suffixes purge their orphaned registry entries at setup.  Matching uses the
# literal ``_{sensor_key}`` unique_id tail so surviving keys are never touched.
#
# Issue #253: the per-inverter "Has Runtime Data" sensor was created twice —
# from the inverter ``has_data`` property (key ``has_data``) and from the
# redundant ``has_runtime_data``/cloud ``hasRuntimeData`` field (key
# ``inverter_has_runtime_data``).  Both rendered the identical name and
# collided onto one entity_id slug, so installs accumulated two active
# entities per inverter.  The ``_inverter_has_runtime_data`` tail never
# matches the surviving ``_has_data`` entity (or any ``_runtime_..._has_data``
# variant).
#
# Issue #335: the EG4_OFFGRID "EPS Load Power L1/L2" sensors (#197) aliased
# the eps_power_l1/l2 values (regs 129/130 / cloud pEpsL1N/L2N — the COMBINED
# backup-path legs), so they were exact duplicates of "EPS Power L1/L2".  The
# keys are retired: no per-leg source for the EPS-loads subset exists.  The
# ``..._l1``/``..._l2`` tails never match the surviving ``_eps_load_power``
# (total) entity, which now carries the real cloud ``epsLoadPower`` field.
_DEPRECATED_DUPLICATE_SENSOR_SUFFIXES: frozenset[str] = frozenset(
    {
        "_inverter_has_runtime_data",
        "_eps_load_power_l1",
        "_eps_load_power_l2",
    }
)

SERVICE_REFRESH_DATA = "refresh_data"
SERVICE_RECONCILE_HISTORY = "reconcile_history"
SERVICE_FETCH_EVENTS = "fetch_events"

REFRESH_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)

RECONCILE_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("lookback_hours", default=48): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=8760)
        ),
        vol.Optional("start_date"): cv.string,
        vol.Optional("end_date"): cv.string,
        vol.Optional("entry_id"): cv.string,
    }
)

# Config entry only - no YAML configuration supported
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LIBRARY_LOGGING_DATA_KEY = f"{DOMAIN}_library_logging"


@dataclass(slots=True)
class _LibraryLoggingState:
    """Home Assistant-scoped ownership of the process-global library logger."""

    original_level: int
    entry_preferences: dict[str, bool] = field(default_factory=dict)


@callback
def _async_register_library_logging(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Register one loaded entry's preference and reconcile the shared logger."""
    pylxpweb_logger = logging.getLogger("pylxpweb")
    state = hass.data.get(_LIBRARY_LOGGING_DATA_KEY)
    if not isinstance(state, _LibraryLoggingState):
        state = _LibraryLoggingState(original_level=pylxpweb_logger.level)
        hass.data[_LIBRARY_LOGGING_DATA_KEY] = state

    state.entry_preferences[entry.entry_id] = bool(
        entry.options.get(
            CONF_LIBRARY_DEBUG,
            entry.data.get(CONF_LIBRARY_DEBUG, False),
        )
    )
    debug_enabled = any(state.entry_preferences.values())
    pylxpweb_logger.setLevel(logging.DEBUG if debug_enabled else logging.WARNING)
    _LOGGER.debug(
        "Reconciled pylxpweb logging for %d loaded entries: %s",
        len(state.entry_preferences),
        "DEBUG" if debug_enabled else "WARNING",
    )


@callback
def _async_unregister_library_logging(
    hass: HomeAssistant, entry: EG4ConfigEntry
) -> None:
    """Drop one entry's preference and restore the remaining/baseline level."""
    state = hass.data.get(_LIBRARY_LOGGING_DATA_KEY)
    if not isinstance(state, _LibraryLoggingState):
        return

    state.entry_preferences.pop(entry.entry_id, None)
    pylxpweb_logger = logging.getLogger("pylxpweb")
    if state.entry_preferences:
        debug_enabled = any(state.entry_preferences.values())
        pylxpweb_logger.setLevel(logging.DEBUG if debug_enabled else logging.WARNING)
        return

    pylxpweb_logger.setLevel(state.original_level)
    hass.data.pop(_LIBRARY_LOGGING_DATA_KEY, None)


def _domain_device_identifiers(device: dr.DeviceEntry) -> set[str]:
    """Return this integration's identifiers from one registry device."""
    return {identifier for domain, identifier in device.identifiers if domain == DOMAIN}


@callback
def _async_remove_registry_ownership(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    *,
    device_ids: set[str] | None = None,
) -> tuple[int, int]:
    """Remove this entry's entities/devices without deleting shared identities.

    If ``device_ids`` is provided, only that device subtree is detached (the
    reconfigure path).  Otherwise all records owned by the entry are removed
    (the config-entry deletion path).  A device linked to another config entry
    is retained and only this entry's ownership is removed.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entry_devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    if device_ids is not None:
        entry_devices = [device for device in entry_devices if device.id in device_ids]

    removed_entities = 0
    for entity in list(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    ):
        if device_ids is not None and entity.device_id not in device_ids:
            continue
        entity_registry.async_remove(entity.entity_id)
        removed_entities += 1

    removed_devices = 0
    for device in entry_devices:
        # The registry itself deletes a device when its final config-entry link
        # is removed.  Keep shared devices by detaching only this entry; remove
        # exclusively-owned devices explicitly after their entities are gone.
        other_config_entries = device.config_entries - {entry.entry_id}
        if other_config_entries:
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
            continue
        device_registry.async_remove_device(device.id)
        removed_devices += 1

    return removed_entities, removed_devices


@callback
def _async_cleanup_removed_registry_devices(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> None:
    """Prune serial/plant device trees absent after a successful first refresh.

    Only authoritative root identities are considered: station identifiers and
    physical devices carrying a serial number.  Battery banks and individual
    batteries are never inferred absent from the LOCAL static first refresh;
    they are removed only as descendants of a definitively absent parent.
    """
    data = coordinator.data or {}
    live_root_identifiers = {str(serial) for serial in data.get("devices", {})}
    live_root_identifiers.update(
        str(transport["serial"])
        for transport in entry.data.get(CONF_LOCAL_TRANSPORTS, [])
        if transport.get("serial")
    )
    if coordinator.station is not None:
        for collection_name in ("all_inverters", "all_mid_devices"):
            for device in getattr(coordinator.station, collection_name, ()) or ():
                if serial := getattr(device, "serial_number", None):
                    live_root_identifiers.add(str(serial))
    if not live_root_identifiers:
        # Liveness floor: a refresh can succeed while the portal answers with
        # an empty device list (#256/#479 class). Zero physical roots is not
        # evidence that every configured device was removed — it is evidence
        # that this snapshot is not authoritative. Never prune from it.
        _LOGGER.debug(
            "Skipping registry cleanup for %s: refresh produced no physical "
            "device roots, so absence cannot be proven",
            entry.entry_id,
        )
        return
    if "station" in data and coordinator.plant_id is not None:
        live_root_identifiers.add(f"station_{coordinator.plant_id}")

    device_registry = dr.async_get(hass)
    entry_devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    stale_device_ids: set[str] = set()
    for device in entry_devices:
        identifiers = _domain_device_identifiers(device)
        if not identifiers:
            continue
        is_station = any(
            identifier.startswith("station_") for identifier in identifiers
        )
        is_physical_device = device.serial_number is not None
        if (is_station or is_physical_device) and identifiers.isdisjoint(
            live_root_identifiers
        ):
            stale_device_ids.add(device.id)

    # Remove every descendant of a stale root, but do not inspect battery
    # membership independently: it is intentionally incomplete at LOCAL setup.
    while True:
        descendants = {
            device.id
            for device in entry_devices
            if device.via_device_id in stale_device_ids
        }
        expanded = stale_device_ids | descendants
        if expanded == stale_device_ids:
            break
        stale_device_ids = expanded

    if not stale_device_ids:
        return

    entity_count, device_count = _async_remove_registry_ownership(
        hass, entry, device_ids=stale_device_ids
    )
    _LOGGER.info(
        "Removed %d stale entities and %d stale devices no longer present for %s",
        entity_count,
        device_count,
        entry.entry_id,
    )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the EG4 Web Monitor component."""

    async def handle_refresh_data(call: ServiceCall) -> None:
        """Handle refresh data service call with validation."""
        entry_id = call.data.get("entry_id")
        coordinators_to_refresh = []

        if entry_id:
            # Validate entry exists
            entry = hass.config_entries.async_get_entry(entry_id)
            if not entry:
                raise ServiceValidationError(
                    f"Config entry {entry_id} not found",
                    translation_domain=DOMAIN,
                    translation_key="entry_not_found",
                )

            # Validate entry is loaded
            if entry.state != ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    f"Config entry {entry_id} is not loaded",
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                )

            # Get coordinator from runtime_data
            coordinator = entry.runtime_data
            coordinators_to_refresh.append(coordinator)
        else:
            # Refresh all loaded coordinators
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                if config_entry.state == ConfigEntryState.LOADED:
                    coordinators_to_refresh.append(config_entry.runtime_data)

        if not coordinators_to_refresh:
            raise ServiceValidationError(
                "No EG4 coordinators found to refresh",
                translation_domain=DOMAIN,
                translation_key="no_coordinators",
            )

        # Refresh all coordinators
        for coordinator in coordinators_to_refresh:
            _LOGGER.info(
                "Refreshing EG4 data for coordinator %s", coordinator.entry.entry_id
            )
            await coordinator.async_request_refresh()

        _LOGGER.info(
            "Refresh completed for %d coordinator(s)", len(coordinators_to_refresh)
        )

    # Register service in async_setup to remain available for validation
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DATA,
        handle_refresh_data,
        schema=REFRESH_DATA_SCHEMA,
    )

    # Register reconcile_history service
    async def handle_reconcile_history(call: ServiceCall) -> None:
        """Handle reconcile_history service call."""
        await async_reconcile_history(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECONCILE_HISTORY,
        handle_reconcile_history,
        schema=RECONCILE_HISTORY_SCHEMA,
    )

    # Register import_historical_data service (issue #73)
    async def handle_import_historical_data(call: ServiceCall) -> ServiceResponse:
        """Handle import_historical_data service call."""
        return await async_import_historical_data(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORICAL_DATA,
        handle_import_historical_data,
        schema=IMPORT_HISTORICAL_DATA_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Register fetch_events service (issue #327) — returns the recent portal
    # event log on demand (response-only; requires cloud/hybrid mode).
    async def handle_fetch_events(call: ServiceCall) -> ServiceResponse:
        """Handle fetch_events service call."""
        return await async_fetch_events(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_EVENTS,
        handle_fetch_events,
        schema=FETCH_EVENTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    return True


def _select_cloud_migration_owner(
    entries: list[ConfigEntry], canonical_unique_id: str
) -> ConfigEntry | None:
    """Select the stable owner of a canonical cloud identity.

    An entry already using the canonical ID wins so migration cannot displace an
    established HTTP identity. If all IDs are legacy/non-canonical, retain the
    oldest entry, with entry ID as a deterministic tie-breaker.
    """
    canonical_owners = [
        entry for entry in entries if entry.unique_id == canonical_unique_id
    ]
    if len(canonical_owners) > 1:
        return None
    if canonical_owners:
        return canonical_owners[0]
    return min(entries, key=lambda entry: (entry.created_at, entry.entry_id))


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries to unified transports and canonical cloud identity.

    Version 1 -> 2 introduced the unified local transport array. Version 2 -> 3
    makes cloud identity independent of HTTP/HYBRID mode. Both transformations
    are staged and committed together so an identity conflict leaves the entry
    entirely untouched.
    """
    if config_entry.version > 3:
        # Can't downgrade from future version
        _LOGGER.error(
            "Cannot migrate config entry %s from version %s (future version)",
            config_entry.entry_id,
            config_entry.version,
        )
        return False

    if config_entry.version == 3:
        return True

    _LOGGER.info(
        "Migrating config entry %s from version %s to 3",
        config_entry.entry_id,
        config_entry.version,
    )

    # Stage all data changes. Keep the ownership decision and registry mutation
    # free of await points so concurrent migrations cannot interleave mid-election.
    # Do not mutate the entry until cloud identity ownership has been resolved.
    new_data = dict(config_entry.data)
    if config_entry.version == 1:
        new_data = migrate_legacy_entry(new_data)

    # Cloud identity applies only to entries that actually operate a cloud
    # connection. A legacy local entry that retained username/plant keys in
    # its data must never be re-keyed to (or win) a cloud identity.
    migrated_connection_type = new_data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)
    canonical_unique_id = (
        cloud_unique_id_from_data(new_data)
        if migrated_connection_type in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID)
        else None
    )
    new_unique_id = config_entry.unique_id
    if canonical_unique_id is not None:
        conflicts = find_config_entry_identity_conflicts(
            hass,
            canonical_unique_id,
            cloud_unique_id=canonical_unique_id,
            exclude_entry_id=config_entry.entry_id,
        )
        owner = _select_cloud_migration_owner(
            [config_entry, *conflicts], canonical_unique_id
        )
        if owner is None or owner.entry_id != config_entry.entry_id:
            owner_id = owner.entry_id if owner is not None else "ambiguous"
            _LOGGER.error(
                "Cannot migrate config entry %s: canonical cloud identity is "
                "owned by %s; leaving the entry unchanged",
                config_entry.entry_id,
                owner_id,
            )
            owner_title = owner.title if owner is not None else "another entry"
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"duplicate_cloud_entry_{config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="duplicate_cloud_entry",
                translation_placeholders={
                    "entry_title": config_entry.title,
                    "owner_title": owner_title,
                    "unique_id": canonical_unique_id,
                },
            )
            return False

        new_data[CONF_PLANT_ID] = str(new_data[CONF_PLANT_ID])
        new_unique_id = canonical_unique_id

    hass.config_entries.async_update_entry(
        config_entry,
        data=new_data,
        unique_id=new_unique_id,
        version=3,
    )
    _LOGGER.info("Migration complete for config entry %s", config_entry.entry_id)

    return True


async def _async_update_device_registry(
    hass: HomeAssistant, coordinator: EG4DataUpdateCoordinator
) -> None:
    """Update device registry with current firmware versions.

    This function ensures device sw_version field is updated with current firmware.
    Home Assistant's device registry doesn't auto-update from entity device_info,
    so we must explicitly update devices after data refresh.
    """
    if not coordinator.data or "devices" not in coordinator.data:
        return

    device_registry = dr.async_get(hass)

    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type")

        # Only update firmware for inverter and GridBOSS devices
        if device_type not in ["inverter", "gridboss"]:
            continue

        # Get firmware version from device data
        firmware_version = device_data.get("firmware_version")
        if not firmware_version:
            continue

        # Get device info for this device
        device_info_dict = coordinator.get_device_info(serial)
        if not device_info_dict:
            continue

        # Use async_get_or_create to ensure sw_version is set correctly
        # This handles cases where device registry wasn't updated properly
        model = device_data.get("model", "Unknown")
        device_name = f"{model} {serial}"

        device_registry.async_get_or_create(
            config_entry_id=coordinator.entry.entry_id,
            identifiers={(DOMAIN, serial)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=model,
            serial_number=serial,
            sw_version=firmware_version,
        )


def _async_cleanup_duplicate_runtime_data_entities(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
) -> None:
    """Remove orphaned entities of retired duplicate sensor keys (#253, #335).

    Earlier versions exposed the same underlying value under two sensor keys
    (see ``_DEPRECATED_DUPLICATE_SENSOR_SUFFIXES``): the redundant
    ``inverter_has_runtime_data`` twin of ``has_data`` (#253) and the
    ``eps_load_power_l1``/``_l2`` aliases of ``eps_power_l1``/``_l2`` (#335).
    The duplicate keys have been removed; purge their stale registry entries
    so the dead entities disappear without manual deletion.
    """
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        if any(
            entity.unique_id.endswith(suffix)
            for suffix in _DEPRECATED_DUPLICATE_SENSOR_SUFFIXES
        ):
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed retired duplicate sensor (#253/#335): %s",
                entity.entity_id,
            )


def _parallel_group_migration_matches(
    existing_pg_ids: set[str],
    devices: dict[str, Any],
) -> dict[str, str]:
    """Return legacy-to-current parallel-group IDs with unique member proof.

    A legacy ID embeds the serial of the group master.  A current group is a
    safe migration target only when its authoritative ``member_serials`` list
    contains that serial and both sides of the match are one-to-one.  Empty,
    contradictory, or many-to-one first-refresh data is deliberately ignored.
    """
    current_members: dict[str, set[str]] = {}
    for group_id, device_data in devices.items():
        if (
            not group_id.startswith("parallel_group_")
            or device_data.get("type") != "parallel_group"
        ):
            continue
        members = device_data.get("member_serials")
        if not isinstance(members, (list, tuple, set, frozenset)) or not members:
            continue
        evidence = {str(member) for member in members if member}
        # The legacy ID was derived from the pre-pylxpweb-0.6.9 first device
        # row, which is not always a member inverter; the modern master
        # serial is equally valid proof of membership.
        if first := device_data.get("first_device_serial"):
            evidence.add(str(first))
        current_members[group_id] = evidence

    stale_ids = existing_pg_ids - current_members.keys()
    candidates_by_old: dict[str, set[str]] = {}
    claimants_by_new: dict[str, set[str]] = {
        group_id: set() for group_id in current_members
    }
    for stale_id in stale_ids:
        legacy_serial = stale_id.removeprefix("parallel_group_")
        candidates = {
            group_id
            for group_id, members in current_members.items()
            if legacy_serial in members
        }
        candidates_by_old[stale_id] = candidates
        for group_id in candidates:
            claimants_by_new[group_id].add(stale_id)

    matches: dict[str, str] = {}
    for stale_id, candidates in candidates_by_old.items():
        if len(candidates) != 1:
            continue
        candidate = next(iter(candidates))
        if len(claimants_by_new[candidate]) == 1:
            matches[stale_id] = candidate

    if not matches and len(stale_ids) == 1 and len(current_members) == 1:
        # GridBOSS-derived legacy IDs (pre-0.6.9 ``devices[0]`` included MID
        # rows) never appear in ``member_serials`` or the modern master
        # serial. With exactly one legacy ID and exactly one current group,
        # the pairing is unambiguous — but only when the legacy serial is a
        # live device of THIS plant, so a foreign or mistyped ID stays put.
        stale_id = next(iter(stale_ids))
        legacy_serial = stale_id.removeprefix("parallel_group_")
        if legacy_serial in devices:
            matches[stale_id] = next(iter(current_members))
    return matches


def _migrate_parallel_group_registry_entries(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    existing_pg_ids: set[str],
    devices: dict[str, Any],
) -> None:
    """Migrate parallel-group registry IDs without guessing or losing entries."""
    matches = _parallel_group_migration_matches(existing_pg_ids, devices)
    if not matches:
        return

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for old_id, new_id in sorted(matches.items()):
        old_device = device_registry.async_get_device({(DOMAIN, old_id)})
        if old_device is None:
            continue

        target_device = device_registry.async_get_device({(DOMAIN, new_id)})
        entries = list(
            er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        )
        for entity in entries:
            belongs_to_old_device = entity.device_id == old_device.id
            has_old_unique_id = entity.unique_id.startswith(f"{old_id}_")
            if not belongs_to_old_device and not has_old_unique_id:
                continue

            new_unique_id = (
                entity.unique_id.replace(old_id, new_id, 1)
                if has_old_unique_id
                else entity.unique_id
            )
            existing_entity_id = entity_registry.async_get_entity_id(
                entity.domain, DOMAIN, new_unique_id
            )
            if existing_entity_id and existing_entity_id != entity.entity_id:
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.info(
                    "Removed duplicate legacy PG entity %s; target %s exists",
                    entity.entity_id,
                    existing_entity_id,
                )
                continue

            update_args: dict[str, Any] = {}
            if new_unique_id != entity.unique_id:
                update_args["new_unique_id"] = new_unique_id
            if target_device is not None and belongs_to_old_device:
                update_args["device_id"] = target_device.id
            if update_args:
                entity_registry.async_update_entity(entity.entity_id, **update_args)
                _LOGGER.info(
                    "Migrated PG entity %s: %s -> %s",
                    entity.entity_id,
                    old_id,
                    new_id,
                )

        if target_device is not None and target_device.id != old_device.id:
            device_registry.async_remove_device(old_device.id)
            _LOGGER.info(
                "Merged legacy parallel group device %s into %s", old_id, new_id
            )
            continue

        new_identifiers = {
            identifier
            for identifier in old_device.identifiers
            if identifier != (DOMAIN, old_id)
        }
        new_identifiers.add((DOMAIN, new_id))
        device_registry.async_update_device(
            old_device.id,
            new_identifiers=new_identifiers,
            name=devices[new_id].get("name") or old_device.name,
        )
        _LOGGER.info("Renamed parallel group device in place: %s -> %s", old_id, new_id)


# Segments that may sit between the serial and the sensor key in a DEVICE
# unique ID.
#
# ``""`` is the ONLY segment this code is known to have ever emitted.
# ``base_entity`` builds a bare ``{serial}_{sensor_key}`` today and did at
# v3.2.0 as well, and ``generate_unique_id`` is never called with a data-type
# argument.  The remaining entries are DEFENSIVE, NOT OBSERVED: a
# ``{serial}_{data_type}_{sensor_key}`` shape is described in CLAUDE.md and
# seeded by ``test_conditional_cleanup_by_family``, but no Python in this
# repository's history has ever produced it — ``git log --all -S`` finds that
# shape only in markdown and in that test's fixture.  They are kept so that
# introducing a data-type scheme later cannot silently turn this guard into a
# no-op, and they cost nothing while unused.  This is an ALLOWLIST on purpose
# — see ``_is_device_namespace_uid``.
_DEVICE_UID_DATA_TYPE_SEGMENTS: frozenset[str] = frozenset(
    {
        "",  # current form: {serial}_{sensor_key}
        "runtime",
        "energy",
        "parameters",
        "midbox_runtime",
    }
)


def _is_device_namespace_uid(unique_id: str, serial: str, sensor_key: str) -> bool:
    """Whether ``unique_id`` is *this device's own* entity for ``sensor_key``.

    One shared ``SENSOR_TYPES`` table backs several unique-ID namespaces that
    ALL begin with the parent inverter serial::

        device   {serial}_{data_type}_{key}   <- the only purge target
        battery  {serial}_{battery_key}_{key}
        bank     {serial}_battery_bank_{key}

    A bare ``endswith(f"_{key}")`` therefore reaches into the battery and bank
    namespaces.  That is harmless for ``battery_discharge_power`` today, but
    generic keys DO live in those namespaces — ``cycle_count`` is both a
    per-battery key (``coordinator_mixins`` battery map) and a bank key
    (``coordinator_mappings`` maps ``battery_bank_cycle_count`` onto it), and
    ``state_of_health``/``battery_type``/``battery_serial_number`` are
    per-battery.  Adding one of those here later would be a one-line change
    that silently deleted every per-battery and bank entity for that key while
    passing every existing test.

    An exact ``unique_id == f"{serial}_{sensor_key}"`` match WOULD in fact
    match every row this code has ever emitted — the "legacy data-type" shape
    is a documentation artifact, not an observed one (see the note on
    ``_DEVICE_UID_DATA_TYPE_SEGMENTS``).  The allowlist is kept anyway because
    ``test_conditional_cleanup_by_family`` seeds ``{serial}_runtime_{key}``
    and asserts it purged, and because it stays correct if a data-type scheme
    is ever introduced.  It costs nothing and fails in the safe direction.

    So the device namespace is identified by ALLOWLISTING its own shapes
    rather than by blocklisting the siblings.  That direction matters: a
    ``battery_key`` does NOT reliably restate the parent serial, so a
    "``middle`` starts with the serial" test does not identify batteries.
    ``clean_battery_display_name`` returns ``{serial}-nn`` for the common
    ``{inverterSn}_{batterySn}`` key, but passes a ``BAT``-prefixed key
    through verbatim (``BAT001``).  That branch is live today, so any cloud
    ``batteryKey`` beginning ``BAT`` produces a ``{serial}_BAT001_{key}`` row;
    the integration also carried a code PATH defaulting the key to
    ``BAT{index:03d}`` when a battery object had no ``battery_key`` at all
    (commit d3dba21, #76) — whether any install actually hit that default is
    not demonstrable from the history, but it does not need to be.  Its final
    branch also passes arbitrary cleaned keys through, and ``cloud_battery_key``
    exists specifically to warn that the ``batteryKey`` format deviates in the
    field (#252).  An allowlist leaves every one of those alone, because an
    unrecognised shape is not on the list.  It is not absolute — a battery
    whose cleaned key were literally ``runtime`` would still be matched — but
    that requires the cloud to return a batteryKey colliding with a listed
    data-type name, which is implausible rather than impossible.

    Deriving the battery keys from ``coordinator.data[...]["batteries"]``
    instead was considered and rejected: that dict is initialised empty and is
    only populated once real battery data has been read, so on a LOCAL first
    refresh it is ``{}`` at the moment this purge runs — which would make every
    battery row look unknown and fail OPEN, the #217 failure mode.
    """
    suffix = f"_{sensor_key}"
    prefix = f"{serial}_"
    if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return False
    middle = unique_id[len(prefix) : -len(suffix)]
    return middle in _DEVICE_UID_DATA_TYPE_SEGMENTS


def _async_cleanup_offgrid_generator_entities(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> None:
    """Purge the bogus EG4_OFFGRID generator sensors (#544).

    ``generator_power`` / ``generator_energy`` / ``generator_energy_lifetime``
    are no longer created on EG4_OFFGRID because their backing registers are
    not measurements on that family (see ``OFFGRID_EXCLUDED_SENSORS``).  Without
    this purge the existing entities would linger in the registry forever as
    "unavailable", still showing their last bogus value in history.

    The mirror image of ``_async_cleanup_deprecated_battery_discharge_power_entities``
    and gated the same way: remove ONLY when the device's family is positively
    RESOLVED as EG4_OFFGRID.  ``UNKNOWN`` is excluded — pylxpweb emits it when a
    parameter fetch fails, and treating it as "family known" would let one
    transient read failure delete a hybrid user's genuine Generator Power
    entity irreversibly.  Unresolved devices keep their entities; the family
    resolves on a later refresh.

    Matching is per-serial and exact via ``_is_device_namespace_uid``, so the
    GridBOSS's own real ``generator_power`` (a different device namespace, fed
    by dedicated CT registers) is never touched.
    """
    offgrid_models: dict[str, str] = {}
    if coordinator.data and "devices" in coordinator.data:
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            family = (device_data.get("features") or {}).get("inverter_family")
            if family == INVERTER_FAMILY_EG4_OFFGRID:
                offgrid_models[serial] = str(device_data.get("model") or "Unknown")
    if not offgrid_models:
        return

    entity_registry = er.async_get(hass)
    removed_serials: set[str] = set()
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        serial = entity.unique_id.partition("_")[0]
        if serial not in offgrid_models:
            continue
        if any(
            _is_device_namespace_uid(entity.unique_id, serial, key)
            for key in OFFGRID_EXCLUDED_SENSORS
        ):
            entity_registry.async_remove(entity.entity_id)
            removed_serials.add(serial)
            _LOGGER.info(
                "Removed EG4_OFFGRID generator sensor with no real backing "
                "register (#544): %s",
                entity.entity_id,
            )

    # Generator Power is enabled-by-default with state_class measurement, so a
    # silent removal would break dashboards and automations with no explanation.
    # This repo's convention for a family-driven prune is to surface it in
    # Repairs (the unknown_family_fallback precedent in coordinator_local).
    for serial in removed_serials:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"offgrid_generator_sensors_removed_{serial}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="offgrid_generator_sensors_removed",
            translation_placeholders={
                "serial": serial,
                "model": offgrid_models[serial],
            },
        )


def _async_cleanup_hybrid_eps_apparent_power_entities(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> None:
    """Purge the bogus EG4_HYBRID per-leg EPS apparent-power sensors (#548).

    ``eps_apparent_power_l1`` / ``eps_apparent_power_l2`` are no longer created
    on EG4_HYBRID because their backing registers are a sign-split directional
    power field and a persistent threshold-gated event counter, respectively
    (see ``HYBRID_EXCLUDED_SENSORS``).  Existing registry entries would
    otherwise linger as unavailable and retain their last bogus values in
    history.

    Remove entities only when the inverter family is positively resolved as
    EG4_HYBRID.  Missing features and the literal ``UNKNOWN`` family emitted by
    pylxpweb after a failed parameter fetch are preserved, preventing a
    transient read failure from irreversibly deleting genuine EG4_OFFGRID
    sensors.  Matching is exact and per-serial via
    ``_is_device_namespace_uid`` so adjacent device namespaces are untouched.
    """
    hybrid_models: dict[str, str] = {}
    if coordinator.data and "devices" in coordinator.data:
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            family = (device_data.get("features") or {}).get("inverter_family")
            if family == INVERTER_FAMILY_EG4_HYBRID:
                hybrid_models[serial] = str(device_data.get("model") or "Unknown")
    if not hybrid_models:
        return

    entity_registry = er.async_get(hass)
    removed_serials: set[str] = set()
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        serial = entity.unique_id.partition("_")[0]
        if serial not in hybrid_models:
            continue
        if any(
            _is_device_namespace_uid(entity.unique_id, serial, key)
            for key in HYBRID_EXCLUDED_SENSORS
        ):
            entity_registry.async_remove(entity.entity_id)
            removed_serials.add(serial)
            _LOGGER.info(
                "Removed mislabelled EG4_HYBRID EPS apparent-power sensor (#548): %s",
                entity.entity_id,
            )

    for serial in removed_serials:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"hybrid_eps_apparent_power_sensors_removed_{serial}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="hybrid_eps_apparent_power_sensors_removed",
            translation_placeholders={
                "serial": serial,
                "model": hybrid_models[serial],
            },
        )


def _async_cleanup_deprecated_battery_discharge_power_entities(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> None:
    """Purge the stale per-inverter ``_battery_discharge_power`` sensor (#197).

    The key was deprecated in 3.2.x but REINTRODUCED for EG4_OFFGRID (#197),
    so it cannot be purged unconditionally: installs that skipped the purging
    versions still carry the stale entry on non-offgrid hardware.  Remove it
    ONLY when the device's family is positively RESOLVED and is not
    EG4_OFFGRID.

    "Resolved" EXCLUDES the ``UNKNOWN`` family string.  pylxpweb's
    ``InverterFeatures.model_family`` defaults to ``InverterFamily.UNKNOWN``
    and ``detect_features()`` returns that default WITHOUT raising when the
    parameter fetch leaves parameters unavailable, so ``"UNKNOWN"`` is the
    value the pipeline emits for an unresolved device — and it is truthy.
    Treating it as "family known" would let a single transient parameter-read
    failure on a genuine off-grid unit delete the very sensor #197
    reintroduced for that family, irreversibly.  Unresolved devices keep
    their entities; the family resolves on a later refresh.
    """
    entity_registry = er.async_get(hass)
    offgrid_serials: set[str] = set()
    family_known_serials: set[str] = set()
    if coordinator.data and "devices" in coordinator.data:
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            family = (device_data.get("features") or {}).get("inverter_family")
            if family and family != INVERTER_FAMILY_UNKNOWN:
                family_known_serials.add(serial)
                if family == INVERTER_FAMILY_EG4_OFFGRID:
                    offgrid_serials.add(serial)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        serial = entity.unique_id.partition("_")[0]
        if not _is_device_namespace_uid(
            entity.unique_id, serial, "battery_discharge_power"
        ):
            continue
        if serial in family_known_serials and serial not in offgrid_serials:
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed deprecated sensor for non-offgrid device: %s",
                entity.entity_id,
            )


def _async_cleanup_stale_smart_port_entities(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> set[str]:
    """Remove stale GridBOSS smart-port sensor entities from the registry.

    Previous versions created entities for all 4 smart ports; now only active
    ports get entities (determined dynamically by
    _filter_unused_smart_port_sensors), so registry entries for inactive port
    keys are removed during setup.

    Removal only happens for GridBOSS serials whose coordinator data is
    AUTHORITATIVE: the sensors dict carries the SMART_PORT_VALIDATED_KEY
    marker, which _filter_unused_smart_port_sensors() writes ONLY on a
    fresh, complete good status read (all 4 ports present and in range this
    cycle).  Static placeholder data, suspect-skip cycles, cached-fallback
    cycles, and partial reads never carry it.  The LOCAL-mode first refresh
    returns static placeholder data without smart-port keys (port statuses
    are unknown before the first register read); treating that as
    authoritative deleted every smart-port registry entry on each reboot and
    re-created them moments later under NEW registry entry IDs, permanently
    breaking automations pinned to the old entry ID (#217).  The same applies
    to a CLOUD/HYBRID first refresh where the midbox runtime endpoint
    returned no data.

    Returns:
        Serials of GridBOSS devices whose port data is not authoritative yet;
        their cleanup must be retried when real data arrives.
    """
    entity_registry = er.async_get(hass)

    # Active keys are tracked PER GridBOSS serial: with two GridBOSS units a
    # global set would let a stale entity on unit A survive forever whenever
    # unit B has the same key active (codex r2 LOW).
    active_smart_port_keys_by_serial: dict[str, set[str]] = {}
    pending_serials: set[str] = set()
    devices = (coordinator.data or {}).get("devices", {})
    for serial, device_data in devices.items():
        if device_data.get("type") != "gridboss":
            continue
        sensors = device_data.get("sensors", {})
        # Authority requires the per-cycle validation marker, written by
        # _filter_unused_smart_port_sensors ONLY on a fresh, complete good
        # status read (all 4 ports in range this cycle).  Static placeholder
        # data, suspect-skip cycles, cached-fallback cycles, and partial
        # reads never carry it — none of those prove the dynamic keys
        # reflect the real port configuration (codex r1 HIGH, r2
        # HIGH/MEDIUM), so cleanup waits for a definitive cycle instead.
        if not sensors.get(SMART_PORT_VALIDATED_KEY):
            pending_serials.add(serial)
            continue
        active_smart_port_keys_by_serial[serial] = {
            k for k in sensors if k in GRIDBOSS_SMART_PORT_DYNAMIC_KEYS
        }

    if not active_smart_port_keys_by_serial:
        return pending_serials

    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        # Only GridBOSS entities are smart-port cleanup candidates.  The
        # aggregate "smart_load_power" key is SHARED with EG4_OFFGRID
        # inverters (cloud GEN-port smart load, #222) — a suffix-only match
        # would delete the inverter entity from the registry on every setup
        # whenever no GridBOSS port is active (codex review MEDIUM).
        # Unique IDs are "{serial}_{sensor_key}", so gate on the serial.
        entity_serial = entity.unique_id.split("_", 1)[0]
        if entity_serial not in active_smart_port_keys_by_serial:
            continue
        active_keys = active_smart_port_keys_by_serial[entity_serial]
        # Smart port unique IDs contain sensor keys like "smart_load1_power_l1"
        # Match by checking if any smart port key appears in the unique_id suffix
        for sp_key in GRIDBOSS_SMART_PORT_DYNAMIC_KEYS:
            if entity.unique_id.endswith(f"_{sp_key}") and sp_key not in active_keys:
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.info(
                    "Removed stale smart port entity: %s (key %s not active)",
                    entity.entity_id,
                    sp_key,
                )
                break

    return pending_serials


async def _async_cleanup_failed_entry_setup(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    coordinator: EG4DataUpdateCoordinator,
) -> None:
    """Roll back resources acquired by an entry that did not finish setup."""
    try:
        if not coordinator._platform_setup_started:
            return
        # Unload only what was actually attempted, one platform at a time:
        # a group can fail mid-forward, and unloading a never-forwarded
        # platform raises ValueError inside HA with an ERROR traceback that
        # would bury the real setup failure in the user's log.
        attempted = getattr(coordinator, "_forwarded_platforms", None) or PLATFORMS
        results = await asyncio.gather(
            *(
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in attempted
            ),
            return_exceptions=True,
        )
        for platform, result in zip(attempted, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.debug(
                    "Rollback unload of never-loaded platform %s for %s: %s",
                    platform,
                    entry.title,
                    result,
                )
    finally:
        try:
            try:
                await coordinator.async_shutdown()
            except Exception:
                _LOGGER.warning(
                    "Error shutting down coordinator after failed setup for %s",
                    entry.title,
                    exc_info=True,
                )
        finally:
            try:
                if coordinator.client is not None:
                    try:
                        await coordinator.client.close()
                    except Exception:
                        _LOGGER.warning(
                            "Error closing HTTP client after failed setup for %s",
                            entry.title,
                            exc_info=True,
                        )
            finally:
                entry.runtime_data = None  # type: ignore[assignment]


async def async_setup_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Set up an entry and unwind every acquired resource on failure."""
    try:
        return await _async_setup_entry_logged(hass, entry)
    except (Exception, asyncio.CancelledError):
        coordinator = entry.runtime_data
        if coordinator is not None:
            try:
                await _async_cleanup_failed_entry_setup(hass, entry, coordinator)
            except BaseException:
                # The original setup failure must reach Home Assistant so a
                # ConfigEntryNotReady still schedules SETUP_RETRY; a cleanup
                # error (including cancellation of the cleanup itself) must
                # never replace it.
                _LOGGER.warning(
                    "Cleanup after failed setup itself failed for %s",
                    entry.title,
                    exc_info=True,
                )
        raise


async def _async_setup_entry_logged(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Set up EG4 Web Monitor from a config entry."""
    _async_register_library_logging(hass, entry)
    try:
        setup_ok = await _async_setup_entry(hass, entry)
    except BaseException:
        # Setup failures and cancellation must not leave a process-global
        # logger preference owned by an entry that never became loaded.
        _async_unregister_library_logging(hass, entry)
        raise
    if not setup_ok:
        _async_unregister_library_logging(hass, entry)
    return setup_ok


async def _async_setup_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Set up an entry after its shared logging ownership is registered."""
    _LOGGER.debug("Setting up EG4 Web Monitor entry: %s", entry.entry_id)

    # A failed constructor must not accidentally clean up stale runtime data
    # retained by a test harness or an interrupted previous setup attempt.
    entry.runtime_data = None  # type: ignore[assignment]

    # Force-migrate: add HTTP polling interval for existing entries
    # and bump HTTP-only users below 60s minimum to 90s default
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)
    needs_migration = False
    new_options = dict(entry.options)

    if CONF_HTTP_POLLING_INTERVAL not in new_options:
        new_options[CONF_HTTP_POLLING_INTERVAL] = DEFAULT_HTTP_POLLING_INTERVAL
        needs_migration = True

    if connection_type == CONNECTION_TYPE_HTTP:
        current_sensor = new_options.get(CONF_SENSOR_UPDATE_INTERVAL, 0)
        if 0 < current_sensor < MIN_HTTP_POLLING_INTERVAL:
            _LOGGER.warning(
                "Migrated HTTP polling interval from %ds to %ds (rate limit protection)",
                current_sensor,
                DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
            )
            new_options[CONF_SENSOR_UPDATE_INTERVAL] = (
                DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP
            )
            needs_migration = True

    if needs_migration:
        hass.config_entries.async_update_entry(entry, options=new_options)

    # Snapshot existing parallel group device identifiers BEFORE first refresh.
    # This lets us preserve the established serial even if the coordinator now
    # derives a different one (e.g., after the roleText master-detection fix).
    device_registry = dr.async_get(hass)
    existing_pg_ids: set[str] = set()
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier.startswith("parallel_group_"):
                existing_pg_ids.add(identifier)

    # Initialize the coordinator
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    coordinator._platform_setup_started = False
    coordinator._forwarded_platforms = []
    entry.runtime_data = coordinator
    await coordinator._async_load_pv_string_lifetime_state()

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Reconfigure reloads retain Home Assistant registry records by default.
    # Remove only physical serial/station trees proven absent by this fresh
    # first refresh, preserving shared devices and incomplete battery data.
    _async_cleanup_removed_registry_devices(hass, entry, coordinator)

    # One-time migration: remove stale local-format battery entities
    # Old local keys used numeric-only battery indices (e.g., "0", "1")
    # New format uses "{serial}-{nn}" to match HTTP key format
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    for entity in entities:
        if entity.domain != "sensor":
            continue
        parts = entity.unique_id.split("_")
        # Match pattern: {serial}_{short_numeric_index}_{sensor_key}
        # where serial is a long numeric string (10+ digits) and index is 1-2 digits
        if (
            len(parts) >= 3
            and parts[0].isdigit()
            and len(parts[0]) >= 10
            and parts[1].isdigit()
            and len(parts[1]) <= 2
        ):
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed stale local-format battery entity: %s", entity.entity_id
            )

    # One-time migration: rename power_output to output_power for consistency
    # HTTP mode used "power_output", local mode used "output_power"
    # Now standardized on "output_power" across all modes
    for entity in entities:
        if entity.domain != "sensor":
            continue
        if "_power_output" in entity.unique_id:
            new_unique_id = entity.unique_id.replace("_power_output", "_output_power")
            existing = entity_registry.async_get_entity_id(
                "sensor", DOMAIN, new_unique_id
            )
            if existing:
                # Target unique_id already exists — remove the stale power_output entity
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.info(
                    "Removed stale power_output entity %s (target %s already exists)",
                    entity.entity_id,
                    existing,
                )
            else:
                entity_registry.async_update_entity(
                    entity.entity_id, new_unique_id=new_unique_id
                )
                _LOGGER.info(
                    "Migrated entity %s: power_output -> output_power",
                    entity.entity_id,
                )

    # One-time migration: serial-based parallel group IDs → name-based IDs.
    # Migration is allowed only when the legacy serial occurs in exactly one
    # current group's authoritative member list and no second legacy ID claims
    # that same group. Registry devices are renamed in place where possible so
    # entity/device IDs, user customizations, and history survive the migration.
    if coordinator.data and "devices" in coordinator.data:
        devices = coordinator.data["devices"]
        _migrate_parallel_group_registry_entries(hass, entry, existing_pg_ids, devices)

    # One-time cleanup: remove deprecated charge/discharge split sensors
    # Consolidated into signed net sensors (battery_power, battery_bank_power, etc.)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        if any(
            entity.unique_id.endswith(suffix)
            for suffix in _DEPRECATED_CHARGE_DISCHARGE_SUFFIXES
        ):
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info("Removed deprecated sensor: %s", entity.entity_id)

    # One-time cleanup: purge retired duplicate sensor keys — the "Has
    # Runtime Data" twin (#253) and the fabricated EPS Load Power L1/L2
    # aliases of EPS Power L1/L2 (#335).
    _async_cleanup_duplicate_runtime_data_entities(hass, entry)

    # Conditional cleanup: the reintroduced-for-offgrid
    # "_battery_discharge_power" (#197) on resolved non-offgrid hardware.
    _async_cleanup_deprecated_battery_discharge_power_entities(hass, entry, coordinator)

    # Conditional cleanup: the EG4_OFFGRID generator sensors whose registers are
    # a 1 Hz counter / status bitfields rather than measurements (#544).
    _async_cleanup_offgrid_generator_entities(hass, entry, coordinator)

    # Conditional cleanup: the EG4_HYBRID per-leg EPS apparent-power sensors
    # whose registers are not apparent-power measurements (#548).
    _async_cleanup_hybrid_eps_apparent_power_entities(hass, entry, coordinator)

    # One-time cleanup: remove stale smart port entities from previous versions
    # that created entities for all 4 ports. Now only active ports get entities
    # (determined dynamically by _filter_unused_smart_port_sensors).
    #
    # The cleanup is gated on AUTHORITATIVE port data: the LOCAL-mode first
    # refresh returns static placeholder data without smart-port keys, and
    # running the cleanup against it deleted every smart-port registry entry
    # on each reboot — breaking automations pinned to the registry entry ID
    # (#217).  GridBOSS serials without real port data yet are retried via a
    # one-shot coordinator listener once the first real poll lands.
    pending_smart_port_serials = _async_cleanup_stale_smart_port_entities(
        hass, entry, coordinator
    )
    if pending_smart_port_serials:
        unsub_smart_port_cleanup: CALLBACK_TYPE | None = None

        @callback
        def _async_deferred_smart_port_cleanup() -> None:
            """Retry the smart-port cleanup once real port data arrives."""
            nonlocal unsub_smart_port_cleanup
            if _async_cleanup_stale_smart_port_entities(hass, entry, coordinator):
                return  # some GridBOSS still lacks authoritative port data
            if unsub_smart_port_cleanup is not None:
                unsub_smart_port_cleanup()
                unsub_smart_port_cleanup = None

        @callback
        def _async_cancel_smart_port_cleanup() -> None:
            """Drop the deferred-cleanup listener on entry unload."""
            nonlocal unsub_smart_port_cleanup
            if unsub_smart_port_cleanup is not None:
                unsub_smart_port_cleanup()
                unsub_smart_port_cleanup = None

        unsub_smart_port_cleanup = coordinator.async_add_listener(
            _async_deferred_smart_port_cleanup
        )
        entry.async_on_unload(_async_cancel_smart_port_cleanup)

    # Forward entry setup to platforms (creates devices and entities)
    # Sensor platform first to create parent devices before other platforms
    # reference them via via_device.
    coordinator._platform_setup_started = True
    try:
        # Mark each group attempted BEFORE forwarding so a mid-group failure
        # still rolls back the members that did load.
        coordinator._forwarded_platforms = list(SENSOR_PLATFORM)
        await hass.config_entries.async_forward_entry_setups(entry, SENSOR_PLATFORM)
        coordinator._forwarded_platforms = list(PLATFORMS)
        await hass.config_entries.async_forward_entry_setups(entry, OTHER_PLATFORMS)
    except asyncio.CancelledError:
        _LOGGER.warning(
            "Platform setup for %s was cancelled; will retry on next reload",
            entry.title,
        )
        raise

    # Update device registry with current firmware versions AFTER devices are created
    await _async_update_device_registry(hass, coordinator)

    # Register options update listener - reload when options change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Handle options update - reload the integration to apply new settings."""
    _LOGGER.info("Options updated for %s, reloading integration", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading EG4 Web Monitor entry: %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = entry.runtime_data

        # Shutdown disconnects all transports (unblocking in-flight I/O),
        # cancels background tasks, and notifies the base class.
        await coordinator.async_shutdown()

        # Clean up HTTP client if present (not a transport, separate lifecycle)
        if coordinator.client is not None:
            await coordinator.client.close()

        _async_unregister_library_logging(hass, entry)

    return bool(unload_ok)


async def async_remove_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Handle removal of an entry.

    This is called when the user deletes the integration from the UI.
    It purges all statistics for this integration's entities, allowing
    TOTAL_INCREASING sensors to reset when the integration is re-added.

    Entity/device registry records owned only by this entry are deleted. Shared
    devices survive with their remaining config-entry ownership intact.
    """
    _LOGGER.info("Removing EG4 Web Monitor entry: %s", entry.entry_id)

    # Get entity registry
    entity_registry = er.async_get(hass)

    # Get all entities for this config entry
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    # Purge statistics for each entity
    entity_ids = [entity.entity_id for entity in entities]

    if entity_ids:
        _LOGGER.info(
            "Purging statistics for %d entities to allow fresh sensor history",
            len(entity_ids),
        )

        # Call recorder service to purge statistics
        # This removes all historical data but preserves Entity Registry entries
        try:
            if hass.services.has_service("recorder", "purge_entities"):
                await hass.services.async_call(
                    "recorder",
                    "purge_entities",
                    {
                        "entity_id": entity_ids,
                        "keep_days": 0,  # Delete all history
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "Statistics purge complete for %d entities", len(entity_ids)
                )
            else:
                _LOGGER.debug(
                    "Recorder service not available, skipping statistics purge"
                )
        except Exception as e:
            _LOGGER.warning("Failed to purge entity statistics: %s", e)
    else:
        _LOGGER.debug("No entities found to purge statistics for")

    removed_entities, removed_devices = _async_remove_registry_ownership(hass, entry)
    _LOGGER.info(
        "Removed %d entity registry entries and %d exclusively-owned devices",
        removed_entities,
        removed_devices,
    )

    await Store(
        hass,
        PV_STRING_LIFETIME_STORAGE_VERSION,
        f"{PV_STRING_LIFETIME_STORAGE_KEY}_{entry.entry_id}",
    ).async_remove()
