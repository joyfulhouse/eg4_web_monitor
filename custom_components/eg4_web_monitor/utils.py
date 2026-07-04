"""Utility functions for EG4 Inverter integration."""

import logging
import re
from collections.abc import Awaitable, Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator

from .const import (
    BATTERY_KEY_PREFIX,
    BATTERY_KEY_SEPARATOR,
    BATTERY_KEY_SHORT_PREFIX,
    DOMAIN,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_LXP,
    MANUFACTURER,
    MODEL_NAME_FAMILY_FALLBACK,
    SUPPORTED_INVERTER_MODELS,
)

_LOGGER = logging.getLogger(__name__)


# Inverter families whose control/config entities (switches, numbers, selects)
# the integration knows how to drive. The model-name substring gate
# (SUPPORTED_INVERTER_MODELS) backstops this for devices whose family is
# UNKNOWN, but the family is the canonical, string-agnostic signal and is
# populated in every connection mode (cloud, local, hybrid).
CONTROL_CAPABLE_FAMILIES: frozenset[str] = frozenset(
    {
        INVERTER_FAMILY_EG4_OFFGRID,
        INVERTER_FAMILY_EG4_HYBRID,
        INVERTER_FAMILY_LXP,
    }
)


# Per-family control capability map (GH #289): FUNC_ parameters whose
# controls a family's firmware/cloud REJECTS ON WRITE. Entities for these
# are not created — offering a switch the firmware refuses to honor is an
# optimistic lie.
#
# Inclusion bar (Opus review on PR #307): a live rejected-write report.
# Portal absence alone is NOT sufficient — the EG4_OFFGRID bucket (device
# type code 54) spans SNA12K-US, 12000XP v1/v2 AND 6000XP, no
# device_type_code isolates XP v2, and the FUNC_ bits are register-decoded
# from the shared family-54 layout (regs 21/233 present on every unit, all
# modes), so neither a narrower family gate nor a value-presence probe can
# discriminate an XP-v2-only quirk.
#
# EG4_OFFGRID / FUNC_BATTERY_BACKUP_CTRL (reg 233 bit 1): enabling Battery
# Backup Mode on a 12000XP v2 (serial 61062J0147, fw ceaa-000709) is
# rejected by the cloud ("failed to enable working mode"), and the EG4
# maintenance Remote Set page for the unit exposes no working-mode toggle
# (its Working Mode section is an AC Charge / AC First / Self Consumption
# schedule). The SNA12K-US reference dump (pylxpweb
# docs/inverters/SNA12KUS_52XXXXXX68.md) shows the bit present but
# DISABLED, consistent with the function being unused family-wide.
#
# Deliberately NOT listed (fail-open on ambiguity, same adjudication style
# as the Forced Discharge gating in PR #220):
# - FUNC_EPS_EN (EPS Battery Backup): #289's portal-absence evidence came
#   from an XP v2, but the SNA12K-US reference dump shows FUNC_EPS_EN
#   actively ENABLED (True) on live family-54 hardware — a family gate
#   would remove a working EPS switch from SNA-US 12K/15K owners,
#   partially reversing #259. No rejected-write report exists for it.
# - FUNC_GREEN_EN (Off Grid Mode): the write is ACCEPTED and the firmware
#   self-reverts the bit within ~10 s; the switch converges to the true
#   state on the post-write parameter refresh, which is honest behavior.
# - FUNC_CHARGE_LAST: the bit sticks when written; "appears inert" is not
#   rejection evidence.
FAMILY_UNSUPPORTED_CONTROL_PARAMS: dict[str, frozenset[str]] = {
    INVERTER_FAMILY_EG4_OFFGRID: frozenset(
        {
            "FUNC_BATTERY_BACKUP_CTRL",  # Battery Backup Mode (reg 233 bit 1)
        }
    ),
}


def is_family_control_supported(device_data: dict[str, Any], param: str) -> bool:
    """Whether a FUNC_ control parameter is supported on the device's family.

    Consults :data:`FAMILY_UNSUPPORTED_CONTROL_PARAMS`. Fails open: a device
    whose family is missing or unknown keeps every control — suppression only
    applies to positively identified families (mirrors ``is_offgrid_family``).

    Args:
        device_data: Device data dictionary with ``features``.
        param: FUNC_ parameter name backing the control (e.g. ``FUNC_EPS_EN``).

    Returns:
        False only when the detected family explicitly rejects the control.
    """
    features = device_data.get("features") or {}
    family = str(features.get("inverter_family") or "")
    unsupported = FAMILY_UNSUPPORTED_CONTROL_PARAMS.get(family)
    return unsupported is None or param not in unsupported


async def async_write_with_cloud_fallback(
    coordinator: "EG4DataUpdateCoordinator",
    serial: str,
    action_name: str,
    *,
    local_write: Callable[[], Awaitable[Any]],
    cloud_write: Callable[[], Awaitable[Any]] | None = None,
    local_values: dict[str, Any] | None = None,
) -> None:
    """Attempt a local register write, falling back to the cloud API.

    The non-switch counterpart of ``EG4BaseSwitch._execute_local_with_fallback``:
    time/number/select controls used to choose the local write path purely on
    transport ATTACHMENT, but pylxpweb keeps the transport attached while the
    link is down (``transport_link_down`` — reads keep probing every cycle).
    In HYBRID mode with a down local link and a healthy cloud, those writes
    raised without ever trying their cloud branch, while switches fell back.

    Semantics:

    - Local transport attached, link believed up: try ``local_write`` first;
      on ``HomeAssistantError`` retry via ``cloud_write`` when a cloud client
      exists (both paths set absolute state, so a double-write is safe).
      Without a cloud client the local error propagates unchanged, so
      LOCAL-only installs keep their existing error behavior.
    - Local transport attached but pylxpweb reports the link DOWN: go straight
      to the cloud instead of waiting out a doomed Modbus timeout. Reads keep
      probing the link each poll cycle, so recovery re-enables local writes.
    - No local transport: cloud path, or the standard no-transport error.

    Args:
        coordinator: The data update coordinator (transport + cloud access).
        serial: Device serial number the write targets.
        action_name: Human-readable action label for log messages.
        local_write: Coroutine factory performing the local register write.
        cloud_write: Coroutine factory performing the equivalent cloud write,
            or None when the action has no cloud path (raw-register-only
            controls) — local errors then propagate unchanged.
        local_values: The written parameters in the LOCAL-RAW representation
            the attached-transport cache uses. When the write lands via the
            cloud path while a local transport is attached, these are merged
            into the coordinator's parameter cache
            (:meth:`EG4DataUpdateCoordinator.note_parameters_written`) so the
            entity converges on the written value — the follow-up parameter
            refresh cannot read locally on a down link (LOCAL-only: skipped
            by pylxpweb; HYBRID: cloud re-read can lag or fail), and without
            the seed the entity would revert to the stale pre-write cache
            value once its optimistic state clears.

    Raises:
        HomeAssistantError: If all available write paths fail, or none exist.
    """
    local_attached = coordinator.has_local_transport(serial)
    if local_attached:
        cloud_available = cloud_write is not None and coordinator.has_http_api()
        if cloud_available and coordinator.is_transport_link_down(serial):
            _LOGGER.warning(
                "Local transport link is down for device %s; writing %s via "
                "the cloud API",
                serial,
                action_name,
            )
        else:
            try:
                await local_write()
                return
            except HomeAssistantError:
                if not cloud_available:
                    raise
                _LOGGER.warning(
                    "Local transport write failed for %s on device %s, "
                    "falling back to cloud API",
                    action_name,
                    serial,
                )
    if cloud_write is not None and coordinator.has_http_api():
        await cloud_write()
        if local_attached and local_values:
            # Cloud fallback with an attached local transport: seed the
            # (local-raw) parameter cache with the acknowledged write so
            # the entity shows the new value even though the local param
            # re-read is skipped/unreliable while the link is down.
            coordinator.note_parameters_written(serial, local_values)
        return
    raise HomeAssistantError(
        "No local transport or cloud API available for parameter write."
    )


def is_supported_control_model(device_data: dict[str, Any]) -> bool:
    """Whether the integration should create control/config entities for a device.

    Switches, numbers, and selects historically gated solely on a substring
    match of the model name against ``SUPPORTED_INVERTER_MODELS``. That misses
    cloud ``deviceTypeText`` variants such as ``"SNA-US 15K"`` — a 15 kW
    EG4_OFFGRID unit (device type code 54) whose name contains none of the
    known substrings (no ``"xp"``/``"sna"`` token, and ``"15k"`` is not in the
    set) — so the gate produced an inverter with zero writable entities
    (GH #259). The detected ``inverter_family`` is the canonical signal and is
    available in every connection mode, so it backstops the substring check.

    Args:
        device_data: Device data dictionary with ``model`` and ``features``.

    Returns:
        True if control/config entities should be created for the device.
    """
    model = device_data.get("model", "")
    model_lower = model.lower() if isinstance(model, str) else ""
    if any(supported in model_lower for supported in SUPPORTED_INVERTER_MODELS):
        return True
    features = device_data.get("features") or {}
    return features.get("inverter_family") in CONTROL_CAPABLE_FAMILIES


# Off-grid XP series model detector: the series uses "<rating>XP" model
# numbers (6000XP, 12000XP, 18000XP, "12000XP-US V2", "EG4-6000XP", ...) —
# digits immediately before "XP".  Grid-tied LXP models ("LXP-EU 3650")
# have a letter before "XP" and never match (codex HIGH on GH #135).
_OFFGRID_XP_MODEL_RE = re.compile(r"\d+XP\b")


def supports_grid_sellback(device_data: dict[str, Any]) -> bool:
    """Check if the inverter family supports selling power back to the grid.

    EG4_OFFGRID inverters (12000XP / 6000XP) have no grid sell-back, so the
    Grid Sell Back / Export PV Only controls would be dead entities there.
    Grid-tied families (EG4_HYBRID, LXP) support feed-in.

    Family detection mirrors the issue #219 pattern: prefer detected
    features; when the family is missing or UNKNOWN, fall back to the
    model name — first the exact-name table, then the XP-series pattern
    (catches variants like "12000XP-US V2" that the exact table misses);
    default to allowing the controls (grid-tied hybrids dominate the
    fleet, and a missing control on a grid-tied unit is a worse failure
    than an inert one on an off-grid unit).

    Args:
        device_data: Device data dictionary with model and features

    Returns:
        True if the device family supports grid sell-back (GH #135)
    """
    features = device_data.get("features") or {}
    family = features.get("inverter_family")
    if family == INVERTER_FAMILY_EG4_OFFGRID:
        return False
    if family in (INVERTER_FAMILY_EG4_HYBRID, INVERTER_FAMILY_LXP):
        return True
    # Family missing or UNKNOWN — classify by model name instead
    model = str(device_data.get("model", "")).strip().upper()
    if MODEL_NAME_FAMILY_FALLBACK.get(model) == INVERTER_FAMILY_EG4_OFFGRID:
        return False
    return not _OFFGRID_XP_MODEL_RE.search(model)


def is_offgrid_family(device_data: dict[str, Any]) -> bool:
    """Return True when a device is positively identified as EG4_OFFGRID.

    Fails open (False) when features are missing or the family is unknown, so
    family-based suppression never removes entities from devices that were
    not positively identified as 12000XP/6000XP-class hardware.
    """
    features = device_data.get("features") or {}
    return bool(features.get("inverter_family") == INVERTER_FAMILY_EG4_OFFGRID)


def is_hybrid_family(device_data: dict[str, Any]) -> bool:
    """Return True when a device is positively identified as EG4_HYBRID.

    Fails closed (False) when features are missing or the family is unknown —
    the Generator/Off-Grid/Peak Shaving schedules were verified on EG4_HYBRID
    hardware and are only created there (plus EG4_OFFGRID for Generator).
    """
    features = device_data.get("features") or {}
    return bool(features.get("inverter_family") == INVERTER_FAMILY_EG4_HYBRID)


@callback
def flag_offgrid_control_suppression(
    hass: HomeAssistant,
    serial: str,
    model: str,
    platform: str,
    unique_id_suffixes: Iterable[str],
    issue_key: str = "offgrid_grid_controls_removed",
) -> None:
    """Raise a Repairs issue when family-gated controls vanish from a device.

    Peak Shaving and Forced Discharge controls are suppressed for the
    EG4_OFFGRID family (PR #220 / issue #197 adjudication), the Battery
    Backup Mode switch followed per the #289 capability map, and the Forced
    Charge schedule times per the #295 live report. Users who already
    had those entities registered should learn why they disappeared instead
    of finding dead automations — same precedent as the #219 family-profile
    pruning. The issue is one per (issue_key, serial); re-creating it with
    the same issue_id is an idempotent update.

    Matching is suffix-based rather than exact: number unique IDs embed the
    model slug (``{clean_model}_{serial}_{key}``), and devices that were once
    misdetected (e.g. the pre-beta.2 ``unknown`` model era, #219/#222) carry
    legacy prefixes in the registry. All variants end with
    ``{serial}_{control_key}``, which is what the suffixes pin.

    Args:
        hass: Home Assistant instance.
        serial: Inverter serial number.
        model: Inverter model string (for the issue text).
        platform: Entity platform domain the unique IDs belong to
            (``"switch"``, ``"number"`` or ``"time"``).
        unique_id_suffixes: Case-insensitive unique-ID suffixes of the
            suppressed entities (``{serial}_{control_key}``). The issue is
            only raised if at least one matching entity was previously
            registered.
        issue_key: Translation key in ``strings.json`` ``issues`` describing
            WHICH controls were removed and why; also prefixes the per-serial
            issue id.
    """
    registry = er.async_get(hass)
    suffixes = tuple(suffix.lower() for suffix in unique_id_suffixes)

    def _was_registered() -> bool:
        for entry in registry.entities.values():
            if entry.domain != platform or entry.platform != DOMAIN:
                continue
            unique_id = str(entry.unique_id).lower()
            if any(unique_id.endswith(suffix) for suffix in suffixes):
                return True
        return False

    if not _was_registered():
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{issue_key}_{serial}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue_key,
        translation_placeholders={
            "serial": str(serial),
            "model": str(model),
        },
    )


def clean_battery_display_name(battery_key: str, serial: str) -> str:
    """Clean up battery key for display in entity names.

    Args:
        battery_key: Raw battery key from API (e.g., "1234567890_Battery_ID_01")
        serial: Parent device serial number

    Returns:
        Cleaned battery display name for UI

    Examples:
        "1234567890_Battery_ID_01" -> "1234567890-01"
        "Battery_ID_01" -> "SERIAL-01"
        "BAT001" -> "BAT001"
    """
    if not battery_key:
        return "01"

    # Handle keys like "1234567890_Battery_ID_01" -> "1234567890-01"
    if BATTERY_KEY_SEPARATOR in battery_key:
        parts = battery_key.split(BATTERY_KEY_SEPARATOR)
        if len(parts) == 2:
            device_serial = parts[0]
            battery_num = parts[1]
            return f"{device_serial}-{battery_num}"

    # Handle keys like "Battery_ID_01" -> "01"
    if battery_key.startswith(BATTERY_KEY_PREFIX):
        battery_num = battery_key.replace(BATTERY_KEY_PREFIX, "")
        return f"{serial}-{battery_num}"

    # Handle keys like "BAT001" -> "BAT001"
    if battery_key.startswith(BATTERY_KEY_SHORT_PREFIX):
        return battery_key

    # If it already looks clean (like "01", "02"), use it with serial
    if battery_key.isdigit() and len(battery_key) <= 2:
        return f"{serial}-{battery_key.zfill(2)}"

    # Fallback: use the raw key but try to make it cleaner
    return battery_key.replace("_", "-")


def local_battery_key(
    inverter_serial: str, battery_serial: str | None, battery_index: int
) -> str:
    """Derive the canonical battery key from locally-read (CAN bus) identity.

    Produces the same key the CLOUD path derives for the same battery: the
    cloud ``batteryKey`` is ``{inverterSn}_{batterySn}`` and the cloud
    ``batterySn`` equals the CAN-reported serial (the same equality the #258
    hybrid overlay matches on).  Placeholder serials (``Battery_ID_NN``)
    therefore collapse to the historical ``{inv}-NN`` form, and real serials
    yield ``{inv}-{serial}`` — identical across CLOUD/LOCAL/HYBRID (#252).

    Args:
        inverter_serial: Parent inverter serial number.
        battery_serial: Per-battery serial from the BMS/CAN bus, if any.
        battery_index: Zero-based register slot index (positional fallback).

    Returns:
        Canonical battery key.
    """
    if battery_serial:
        return clean_battery_display_name(
            f"{inverter_serial}_{battery_serial}", inverter_serial
        )
    return f"{inverter_serial}-{battery_index + 1:02d}"


# One-shot dedup for the batteryKey/batterySn divergence warning below.
# Module-level because cloud_battery_key() is a pure helper called from
# several coordinator paths every refresh; tests may clear it.
_battery_key_divergence_warned: set[tuple[str, str]] = set()


def cloud_battery_key(inverter_serial: str, battery: Any) -> str:
    """Derive the canonical battery key from a cloud battery object.

    Shared by the CLOUD and HYBRID paths so a mode migration never re-keys a
    battery (#252).  Uses the cloud ``batteryKey`` exactly like the stable
    3.3.0 CLOUD path always has (existing cloud-created entities keep their
    ids), falling back to the battery serial and finally the positional index.

    The LOCAL path derives its key from the battery serial on the assumption
    that ``batteryKey == {inverterSn}_{batterySn}``.  When a cloud battery
    carries a real (non-placeholder) serial whose derived key differs from
    the ``batteryKey``-derived one, that API invariant is broken and LOCAL
    and CLOUD identities would split — a one-shot WARNING per (inverter,
    battery) surfaces it in the field.

    Args:
        inverter_serial: Parent inverter serial number.
        battery: Cloud battery object (pylxpweb ``Battery``) exposing
            ``battery_key``/``battery_sn``/``battery_index``.

    Returns:
        Canonical battery key.
    """
    raw_key = getattr(battery, "battery_key", None)
    battery_sn = getattr(battery, "battery_sn", None)
    index = getattr(battery, "battery_index", 0) or 0
    if isinstance(raw_key, str) and raw_key:
        key = clean_battery_display_name(raw_key, inverter_serial)
        if (
            isinstance(battery_sn, str)
            and battery_sn
            and not battery_sn.startswith(BATTERY_KEY_PREFIX)
        ):
            sn_key = local_battery_key(inverter_serial, battery_sn, index)
            if (
                sn_key != key
                and (dedup := (inverter_serial, battery_sn))
                not in _battery_key_divergence_warned
            ):
                _battery_key_divergence_warned.add(dedup)
                _LOGGER.warning(
                    "Cloud batteryKey %r for inverter %s yields key %s but its "
                    "batterySn %r yields %s — the batteryKey format deviates "
                    "from '{inverterSn}_{batterySn}', so LOCAL-derived battery "
                    "identity would differ from CLOUD for this battery. "
                    "Please report this at "
                    "https://github.com/joyfulhouse/eg4_web_monitor/issues/252",
                    raw_key,
                    inverter_serial,
                    key,
                    battery_sn,
                    sn_key,
                )
        return key
    if isinstance(battery_sn, str) and battery_sn:
        return local_battery_key(inverter_serial, battery_sn, index)
    return f"{inverter_serial}-{index + 1:02d}"


# ========== CONSOLIDATED UTILITY FUNCTIONS ==========
# These functions eliminate code duplication across multiple platform files


def clean_model_name(model: str, use_underscores: bool = False) -> str:
    """Clean model name for consistent entity ID generation.

    Args:
        model: Raw model name from device
        use_underscores: If True, replace spaces/hyphens with underscores instead of removing them

    Returns:
        Cleaned model name suitable for entity IDs
    """
    if not model:
        return "unknown"

    cleaned = model.lower()
    if use_underscores:
        return cleaned.replace(" ", "_").replace("-", "_")
    return cleaned.replace(" ", "").replace("-", "")


def create_device_info(serial: str, model: str) -> DeviceInfo:
    """Create standardized device info dictionary for Home Assistant entities.

    Args:
        serial: Device serial number
        model: Device model name

    Returns:
        Device info dictionary for Home Assistant
    """
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=f"{model} {serial}",
        manufacturer=MANUFACTURER,
        model=model,
        serial_number=serial,
        sw_version="1.0.0",  # Default version, can be updated from API
    )


def generate_entity_id(
    platform: str,
    model: str,
    serial: str,
    entity_type: str,
    suffix: str | None = None,
) -> str:
    """Generate standardized entity IDs across all platforms.

    Args:
        platform: Platform name (sensor, switch, button, number)
        model: Device model name
        serial: Device serial number
        entity_type: Type of entity (e.g., "refresh_data", "ac_charge")
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized entity ID
    """
    clean_model = clean_model_name(model)
    base_id = f"{platform}.{clean_model}_{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id


def generate_unique_id(serial: str, entity_type: str, suffix: str | None = None) -> str:
    """Generate standardized unique IDs for entity registry.

    Args:
        serial: Device serial number
        entity_type: Type of entity
        suffix: Optional suffix for multi-part entities

    Returns:
        Standardized unique ID
    """
    base_id = f"{serial}_{entity_type}"

    if suffix:
        base_id = f"{base_id}_{suffix}"

    return base_id
