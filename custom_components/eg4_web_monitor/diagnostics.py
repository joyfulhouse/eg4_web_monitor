"""Diagnostics support for the EG4 Web Monitor integration.

Settings -> Devices & Services -> EG4 Web Monitor -> Download diagnostics.

The download exists so a bug report can show exactly what the cloud or the
local transport returned, without a round-trip asking the reporter to capture
it by hand. Credentials, hosts, the plant name/title and station location
fields are redacted outright; device, dongle and battery serial numbers are
replaced with aliases (``SN_1``, ``SN_2``, ...) everywhere they appear — as
dict keys, as values, and embedded inside longer strings such as unique IDs —
and the plant id likewise becomes ``PLANT_1``, so the structure stays
correlatable across the whole dump without exposing identifying values.
Aliases are deterministic for a given inventory but may renumber if devices
are added or removed between downloads.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DONGLE_HOST,
    CONF_MODBUS_HOST,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
)
from .coordinator import EG4DataUpdateCoordinator

TO_REDACT = {
    "username",
    "password",
    CONF_PLANT_NAME,
    CONF_MODBUS_HOST,
    CONF_DONGLE_HOST,
    # Station/location fields (HA treats location and personal data as
    # sensitive diagnostics content); nested occurrences are covered because
    # async_redact_data walks the whole tree.
    "name",
    "address",
    "phone",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "country",
    "city",
}

# The default portal URLs are public knowledge and useful evidence; anything
# else (a proxy, an internal hostname) is the reporter's private topology.
_PUBLIC_BASE_URLS = {
    "https://monitor.eg4electronics.com",
    "https://us.luxpowertek.com",
    "https://eu.luxpowertek.com",
}

# Config-entry keys whose values are device serials and must join the alias
# map before the entry data is dumped.
_SERIAL_ENTRY_KEYS = ("inverter_serial", "dongle_serial")

# A shorter string is more likely to be a coincidental substring than a
# serial; real EG4/dongle/battery serials are 10+ characters.
_MIN_SERIAL_LEN = 4


def _walk_serials(obj: Any, serials: set[str]) -> None:
    """Recursively collect serial-shaped values from the data tree.

    Two sources beyond the top-level device keys: any dict stored under a
    ``batteries`` key is keyed by battery serial (serial-first identity,
    #252), and any value whose key mentions ``serial`` or is ``battery_sn``
    is a serial regardless of where it sits (e.g. the
    ``battery_serial_number`` sensor value).
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                lowered = key.lower()
                if lowered == "batteries" and isinstance(value, dict):
                    serials.update(str(k) for k in value)
                if ("serial" in lowered or lowered == "battery_sn") and isinstance(
                    value, str
                ):
                    serials.add(value)
            _walk_serials(value, serials)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _walk_serials(item, serials)


def _collect_serials(
    coordinator: EG4DataUpdateCoordinator | None, entry: ConfigEntry
) -> list[str]:
    """Collect every device serial the dump could contain, deterministically.

    Device dict keys are the authoritative inventory; the recursive walk adds
    battery serials (both as ``batteries`` dict keys and as serial-valued
    fields anywhere in the tree); entry data can add local device serials
    that predate a successful poll. Sorted so aliasing is deterministic for
    a given inventory.
    """
    serials: set[str] = set()
    if coordinator is not None:
        data = coordinator.data or {}
        serials.update(str(key) for key in data.get("devices", {}))
        _walk_serials(data, serials)

    entry_data = entry.data
    for key in _SERIAL_ENTRY_KEYS:
        value = entry_data.get(key)
        if value:
            serials.add(str(value))
    for transport in entry_data.get("local_transports", []) or []:
        if isinstance(transport, dict):
            for key in _SERIAL_ENTRY_KEYS:
                value = transport.get(key)
                if value:
                    serials.add(str(value))

    # A too-short "serial" (or an empty one) would corrupt the dump through
    # coincidental substring hits; drop them rather than alias them.
    serials = {s for s in serials if len(s) >= _MIN_SERIAL_LEN}

    # Longest first, so a serial that happens to contain another as a
    # substring is replaced before its fragment can be.
    return sorted(serials, key=lambda s: (-len(s), s))


def _build_alias_pattern(aliases: dict[str, str]) -> re.Pattern[str] | None:
    """Compile one case-insensitive pattern over all serials, longest first.

    A purely numeric serial (or the plant id) gets digit-boundary guards so
    it only matches where it is not part of a longer number — otherwise an
    energy reading that happens to contain the plant id as a substring would
    be corrupted by the replacement.
    """
    if not aliases:
        return None
    parts = []
    for serial in aliases:
        escaped = re.escape(serial)
        if serial.isdigit():
            escaped = rf"(?<!\d){escaped}(?!\d)"
        parts.append(escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


def _alias_serials(
    obj: Any, aliases: dict[str, str], pattern: re.Pattern[str] | None
) -> Any:
    """Recursively replace serials in keys, values and embedded strings.

    Matching is case-insensitive (letter-bearing dongle/battery serials can
    appear lowercased in derived strings such as entity IDs); the longest
    serial wins where one embeds another because the pattern lists serials
    longest first.
    """
    if pattern is None:
        return obj
    if isinstance(obj, dict):
        return {
            _alias_serials(key, aliases, pattern): _alias_serials(
                value, aliases, pattern
            )
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_alias_serials(item, aliases, pattern) for item in obj]
    if isinstance(obj, str):
        return pattern.sub(lambda m: aliases[m.group(0).upper()], obj)
    # An int-typed serial or plant id (the cloud returns plantId as a
    # number) would otherwise sail past the string replacement.
    if isinstance(obj, int) and not isinstance(obj, bool) and str(obj) in aliases:
        return aliases[str(obj)]
    return obj


def _jsonable(obj: Any) -> Any:
    """Reduce arbitrary values to JSON-serializable primitives.

    Unknown objects become a bounded ``<TypeName>`` placeholder rather than
    ``repr()`` — a repr can embed credentials, hosts or tokens (e.g. an
    aiohttp exception carrying the connection target), and nothing
    downstream could redact free-form repr text reliably.
    """
    if isinstance(obj, dict):
        return {str(key): _jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return f"<{type(obj).__name__}>"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Works on a failed-setup or unloaded entry too: ``runtime_data`` is only
    assigned after the first successful refresh, and a reporter whose setup
    fails is exactly the reporter who needs to attach evidence — so the dump
    degrades to a config-only snapshot instead of raising.
    """
    coordinator_candidate = getattr(entry, "runtime_data", None)
    coordinator: EG4DataUpdateCoordinator | None = (
        coordinator_candidate
        if isinstance(coordinator_candidate, EG4DataUpdateCoordinator)
        else None
    )

    serials = _collect_serials(coordinator, entry)
    aliases = {
        serial.upper(): f"SN_{index}" for index, serial in enumerate(serials, start=1)
    }
    plant_id = entry.data.get(CONF_PLANT_ID)
    if plant_id:
        aliases[str(plant_id).upper()] = "PLANT_1"
    pattern = _build_alias_pattern(aliases)

    def _clean(obj: Any) -> Any:
        return _alias_serials(
            async_redact_data(_jsonable(obj), TO_REDACT), aliases, pattern
        )

    try:
        pylxpweb_version = version("pylxpweb")
    except PackageNotFoundError:
        pylxpweb_version = "unknown"

    base_url = entry.data.get("base_url")
    entry_data = dict(entry.data)
    if base_url and base_url.rstrip("/") not in _PUBLIC_BASE_URLS:
        entry_data["base_url"] = "**REDACTED**"

    result: dict[str, Any] = {
        "entry": {
            "data": _clean(entry_data),
            "options": _clean(dict(entry.options)),
        },
        "versions": {
            "pylxpweb": pylxpweb_version,
        },
    }

    if coordinator is None:
        result["coordinator"] = None
        return result

    result["coordinator"] = {
        "connection_type": coordinator.connection_type,
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        "device_count": len((coordinator.data or {}).get("devices", {})),
        "serial_aliases": sorted(aliases.values()),
        "bus_owner": {
            "eligible": coordinator._bus_owner_eligibility.eligible,
            "reason": coordinator._bus_owner_eligibility.reason.value,
            "provenance": coordinator._bus_owner_eligibility.provenance.value,
        },
        "data": _clean(coordinator.data or {}),
    }
    return result
