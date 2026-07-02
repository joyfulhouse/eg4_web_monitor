"""EG4 Web Monitor integration for Home Assistant."""

import asyncio
import logging
from typing import Any, TypeAlias

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
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

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_HTTP_POLLING_INTERVAL,
    CONF_SENSOR_UPDATE_INTERVAL,
    CONNECTION_TYPE_HTTP,
    DEFAULT_HTTP_POLLING_INTERVAL,
    DEFAULT_SENSOR_UPDATE_INTERVAL_HTTP,
    DOMAIN,
    INVERTER_FAMILY_EG4_OFFGRID,
    MANUFACTURER,
    MIN_HTTP_POLLING_INTERVAL,
)
from .coordinator import EG4DataUpdateCoordinator
from .coordinator_mappings import (
    GRIDBOSS_SMART_PORT_DYNAMIC_KEYS,
    SMART_PORT_VALIDATED_KEY,
)
from .history_import import (
    IMPORT_HISTORICAL_DATA_SCHEMA,
    SERVICE_IMPORT_HISTORICAL_DATA,
    async_import_historical_data,
)
from .services import async_reconcile_history
from ._config_flow.helpers import migrate_legacy_entry

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

# Issue #253: the per-inverter "Has Runtime Data" sensor was created twice —
# from the inverter ``has_data`` property (key ``has_data``) and from the
# redundant ``has_runtime_data``/cloud ``hasRuntimeData`` field (key
# ``inverter_has_runtime_data``).  Both rendered the identical name and
# collided onto one entity_id slug, so installs accumulated two active
# entities per inverter.  The duplicate key has been removed; this suffix
# purges its orphaned registry entries.  Matching requires the literal
# ``_inverter_has_runtime_data`` tail so the surviving ``_has_data`` entity
# (and any ``_runtime_..._has_data`` variant) is never touched.
_DEPRECATED_DUPLICATE_SENSOR_SUFFIXES: frozenset[str] = frozenset(
    {
        "_inverter_has_runtime_data",
    }
)

SERVICE_REFRESH_DATA = "refresh_data"
SERVICE_RECONCILE_HISTORY = "reconcile_history"

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

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to current version.

    Version 1 -> 2: Migrate legacy modbus/dongle entries to unified local format.
    Old format stored connection details at root level (modbus_host, dongle_host, etc.)
    New format uses local_transports array with transport configs.
    """
    if config_entry.version > 2:
        # Can't downgrade from future version
        _LOGGER.error(
            "Cannot migrate config entry %s from version %s (future version)",
            config_entry.entry_id,
            config_entry.version,
        )
        return False

    if config_entry.version == 1:
        _LOGGER.info(
            "Migrating config entry %s from version 1 to 2",
            config_entry.entry_id,
        )

        # Use the helper function to migrate legacy modbus/dongle entries
        new_data = migrate_legacy_entry(dict(config_entry.data))

        # Update the entry with migrated data and new version
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=2,
        )

        _LOGGER.info(
            "Migration complete for config entry %s",
            config_entry.entry_id,
        )

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
    """Remove orphaned duplicate "Has Runtime Data" sensor entities (#253).

    Earlier versions exposed the same inverter runtime-data flag as two
    sensors sharing the name "Has Runtime Data": the canonical ``has_data``
    key and the redundant ``inverter_has_runtime_data`` key.  Both mapped the
    identical underlying value and collided onto one entity_id slug, so
    installs accumulated two active entities per inverter.  The
    ``inverter_has_runtime_data`` sensor has been removed; purge its stale
    registry entries so the duplicate disappears without manual deletion.
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
                "Removed duplicate Has Runtime Data sensor (#253): %s",
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


async def async_setup_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> bool:
    """Set up EG4 Web Monitor from a config entry."""
    _LOGGER.debug("Setting up EG4 Web Monitor entry: %s", entry.entry_id)

    # Configure library debug logging based on user preference (options, data fallback)
    library_debug = entry.options.get(
        "library_debug", entry.data.get("library_debug", False)
    )
    pylxpweb_logger = logging.getLogger("pylxpweb")

    if library_debug:
        pylxpweb_logger.setLevel(logging.DEBUG)
        _LOGGER.info("Enabled DEBUG logging for pylxpweb library")
    else:
        # Set to WARNING to suppress INFO logs from library
        pylxpweb_logger.setLevel(logging.WARNING)

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

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime_data
    entry.runtime_data = coordinator

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
    # Old format: parallel_group_{serial} (e.g., parallel_group_4524850115)
    # New format: parallel_group_{letter} (e.g., parallel_group_a)
    # The new format uses the cloud API's parallelGroup name for stability
    # across LOCAL/HYBRID/cloud mode transitions.
    if coordinator.data and "devices" in coordinator.data:
        devices = coordinator.data["devices"]
        new_pg_ids = {k for k in devices if k.startswith("parallel_group_")}

        # Find old serial-based PG IDs that don't match any new name-based ID
        stale_ids = existing_pg_ids - new_pg_ids

        claimed_new_ids: set[str] = set()
        for stale_id in sorted(stale_ids):
            # Find matching new name-based PG not already claimed or existing
            matched_new_id = ""
            for new_id in sorted(new_pg_ids):
                if new_id not in existing_pg_ids and new_id not in claimed_new_ids:
                    matched_new_id = new_id
                    claimed_new_ids.add(new_id)
                    break

            if matched_new_id:
                # Migrate entity unique_ids from old serial-based to new name-based
                old_prefix = stale_id
                new_prefix = matched_new_id
                for entity in er.async_entries_for_config_entry(
                    entity_registry, entry.entry_id
                ):
                    if entity.unique_id.startswith(f"{old_prefix}_"):
                        new_uid = entity.unique_id.replace(old_prefix, new_prefix, 1)
                        existing_entity = entity_registry.async_get_entity_id(
                            entity.domain, DOMAIN, new_uid
                        )
                        if existing_entity:
                            entity_registry.async_remove(entity.entity_id)
                        else:
                            entity_registry.async_update_entity(
                                entity.entity_id, new_unique_id=new_uid
                            )
                        _LOGGER.info(
                            "Migrated PG entity %s: %s -> %s",
                            entity.entity_id,
                            old_prefix,
                            new_prefix,
                        )

            # Remove the old serial-based PG device
            for device in dr.async_entries_for_config_entry(
                device_registry, entry.entry_id
            ):
                for domain, identifier in device.identifiers:
                    if domain == DOMAIN and identifier == stale_id:
                        device_registry.async_remove_device(device.id)
                        _LOGGER.info(
                            "Removed stale parallel group device: %s",
                            stale_id,
                        )

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

    # One-time cleanup: remove the duplicate "Has Runtime Data" sensor (#253).
    _async_cleanup_duplicate_runtime_data_entities(hass, entry)

    # Conditional cleanup: per-inverter "_battery_discharge_power" was
    # deprecated in 3.2.x but REINTRODUCED for EG4_OFFGRID (#197). Installs
    # that skipped the purging versions still carry the stale entry on
    # non-offgrid hardware — remove it ONLY when the device's family is
    # positively known and not EG4_OFFGRID; unresolved devices keep theirs
    # (conservative — pure-cloud family resolves on a later refresh).
    offgrid_serials: set[str] = set()
    family_known_serials: set[str] = set()
    if coordinator.data and "devices" in coordinator.data:
        for serial, device_data in coordinator.data["devices"].items():
            if device_data.get("type") != "inverter":
                continue
            family = (device_data.get("features") or {}).get("inverter_family")
            if family:
                family_known_serials.add(serial)
                if family == INVERTER_FAMILY_EG4_OFFGRID:
                    offgrid_serials.add(serial)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.domain != "sensor":
            continue
        uid = entity.unique_id
        if not uid.endswith("_battery_discharge_power"):
            continue
        serial = uid.split("_", 1)[0]
        if serial in family_known_serials and serial not in offgrid_serials:
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.info(
                "Removed deprecated sensor for non-offgrid device: %s",
                entity.entity_id,
            )

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
    try:
        await hass.config_entries.async_forward_entry_setups(entry, SENSOR_PLATFORM)
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

    return bool(unload_ok)


async def async_remove_entry(hass: HomeAssistant, entry: EG4ConfigEntry) -> None:
    """Handle removal of an entry.

    This is called when the user deletes the integration from the UI.
    It purges all statistics for this integration's entities, allowing
    TOTAL_INCREASING sensors to reset when the integration is re-added.

    Entity Registry entries (names, areas, labels) are NOT deleted,
    so they will be automatically restored when re-adding the integration.
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
