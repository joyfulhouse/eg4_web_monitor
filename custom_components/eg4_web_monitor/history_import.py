"""Historical energy import service for the EG4 Web Monitor integration.

Implements the ``eg4_web_monitor.import_historical_data`` service: a
user-triggered, opt-in, idempotent backfill of plant-level daily energy
series from the EG4 cloud into Home Assistant long-term statistics.

Design notes:

- Data source: ``LuxpowerClient.analytics.get_month_daily_energy()`` —
  one cloud request per calendar month per inverter/parallel group,
  returning all daily energy series at once.
- Statistics are written as EXTERNAL statistics
  (``eg4_web_monitor:plant_{plant_id}_{series}``) via
  ``async_add_external_statistics``. External statistic IDs use a ``:``
  separator and therefore can never collide with the live sensors'
  entity statistics.
- One statistics row per day, placed at local midnight (station timezone
  when known, otherwise the Home Assistant timezone). The recorder
  requires row starts at the top of an hour; midnight satisfies this.
- Timezone preference: the cloud reports station timezones as fixed
  offsets ("GMT -8") with no DST rules — under DST those would drift
  daily rows to 01:00 local. Because the HA instance lives at the plant
  in essentially all deployments, Home Assistant's configured (IANA,
  DST-aware) timezone is preferred whenever the station timezone is a
  fixed offset or cannot be parsed. Genuine IANA station timezones are
  used as-is.
- Idempotency: the recorder upserts rows on (statistic_id, start), and this
  module recomputes the cumulative ``sum`` across ALL known rows (existing +
  new) from the earliest point, so overlapping re-imports converge instead of
  double counting. A resolved-timezone change clears existing rows only when
  the requested range covers their full known span; a first-ever import with
  no prior marker intentionally never clears because there is nothing to
  compare or protect. Recorder clear/write calls are enqueue-only and log
  failures instead of raising them to this caller, so the persisted marker can
  in principle get ahead of the database. Requiring a full-span rebuild bounds
  that residual window to recoverable marker/database staleness that a future
  re-import will detect and guard again, rather than silently losing history
  outside the requested range.
- Concurrency: imports for the same plant serialize on a per-plant
  asyncio.Lock held across the whole read-recompute-write section —
  without it, two concurrent imports would each snapshot stale history
  and write undercounted sums.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_PLANT_NAME,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DOMAIN,
)
from .services import _get_station_timezone

if TYPE_CHECKING:
    from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_IMPORT_HISTORICAL_DATA = "import_historical_data"

# Hard bound on the requested range (two years, leap-safe).
MAX_RANGE_DAYS = 731

# Delay between cloud requests to stay gentle on the EG4 API.
FETCH_DELAY_SECONDS = 0.5

# Resolved timezone used by the last successful statistics write, keyed by
# statistic ID. A changed timezone shifts local midnight's UTC row start.
HISTORY_IMPORT_TZ_STORAGE_VERSION = 1
HISTORY_IMPORT_TZ_STORAGE_KEY = f"{DOMAIN}_history_import_tz"

# Per-plant import locks: concurrent service calls for the same plant must
# serialize across the whole read-recompute-write section, or each call
# would snapshot stale history and write undercounted sums. Keyed by plant
# slug (the statistic-ID namespace, shared even across duplicate entries).
_IMPORT_LOCKS: dict[str, asyncio.Lock] = {}

# The timezone marker Store is shared by every plant/statistic ID. Hold this
# lock across each complete load-decide-write-save sequence to prevent two
# cross-plant imports from losing one another's marker updates.
_TZ_MARKER_LOCK = asyncio.Lock()

IMPORT_HISTORICAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry"): cv.string,
        vol.Required("start_date"): cv.date,
        vol.Optional("end_date"): cv.date,
        vol.Optional("dry_run", default=False): cv.boolean,
    }
)


@dataclass(frozen=True)
class SeriesSpec:
    """One importable plant-level energy series."""

    key: str
    """Statistic ID suffix and response key."""

    label: str
    """Human-readable name suffix for the statistic."""

    attr: str
    """Primary ``DailyEnergyHistoryEntry`` kWh property."""

    fallback_attr: str | None = None
    """Fallback property used only when the primary has no data at all."""


SERIES_SPECS: tuple[SeriesSpec, ...] = (
    # eInvDay matches the live "yield" sensor (todayYielding). If the cloud
    # rows do not carry eInvDay, fall back to PV string totals.
    SeriesSpec("yield", "PV yield", "inverter_kwh", "pv_kwh"),
    SeriesSpec("consumption", "Consumption", "consumption_kwh"),
    SeriesSpec("grid_import", "Grid import", "import_kwh"),
    SeriesSpec("grid_export", "Grid export", "export_kwh"),
    SeriesSpec("battery_charge", "Battery charge", "charge_kwh"),
    SeriesSpec("battery_discharge", "Battery discharge", "discharge_kwh"),
)

# All entry properties that need accumulating (primary + fallback attrs).
_ACCUMULATED_ATTRS: tuple[str, ...] = tuple(
    dict.fromkeys(
        attr
        for spec in SERIES_SPECS
        for attr in (spec.attr, spec.fallback_attr)
        if attr is not None
    )
)


async def async_import_historical_data(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the import_historical_data service call.

    Fetches plant-level daily energy history from the EG4 cloud and writes
    it as external long-term statistics. Safe to re-run for overlapping
    ranges (idempotent upsert + full sum recompute).
    """
    entry = _resolve_entry(hass, call.data["config_entry"])
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data
    client = _require_cloud_client(coordinator)
    start_date, end_date = _validate_range(
        call.data["start_date"], call.data.get("end_date")
    )
    dry_run = bool(call.data["dry_run"])

    fetch_method = getattr(
        getattr(client, "analytics", None), "get_month_daily_energy", None
    )
    if not callable(fetch_method):
        raise ServiceValidationError(
            "The installed pylxpweb library does not provide the energy "
            "history API required by this service",
            translation_domain=DOMAIN,
            translation_key="history_api_unavailable",
        )

    plant_slug = _plant_slug(coordinator)
    plant_name = entry.data.get(CONF_PLANT_NAME) or entry.title

    # Serialize concurrent imports for the same plant: the sum recompute
    # in _merge_and_write must see every previously submitted row.
    lock = _IMPORT_LOCKS.setdefault(plant_slug, asyncio.Lock())
    async with lock:
        units = _collect_units(coordinator)

        # async_add_external_statistics() only QUEUES an
        # ImportStatisticsTask on the recorder worker and returns before
        # the rows are committed, so holding the lock alone is not enough:
        # a previous import may have released the lock with writes still
        # in flight. Entry drain (the correctness guarantee): wait for the
        # recorder queue so _load_existing_rows() reads committed state.
        # No-op when the queue is idle.
        #
        # Known residual window (accepted): on a retryable DB error
        # (SQLite lock / MySQL deadlock) ImportStatisticsTask requeues
        # itself and can land BEHIND the synchronize barrier, so this
        # drain is not a perfect commit fence in that rare window. The
        # exposure requires two imports racing during a DB retry; the
        # damage is bounded (undercounted sums on the second import's
        # rows) and fully heals by re-running the affected range — the
        # sum recompute rewrites those rows from committed state. For a
        # manual, lock-serialized service this is accepted rather than
        # spinning on an unbounded drain loop.
        await get_instance(hass).async_block_till_done()

        _LOGGER.info(
            "Importing historical energy for plant %s from %s to %s "
            "(%d unit(s), dry_run=%s)",
            plant_slug,
            start_date.isoformat(),
            end_date.isoformat(),
            len(units),
            dry_run,
        )

        day_values, api_calls = await _fetch_daily_values(
            fetch_method, units, start_date, end_date
        )

        requested_days = (end_date - start_date).days + 1
        series_summary: dict[str, Any] = {}
        wrote_any = False

        for spec in SERIES_SPECS:
            values = day_values.get(spec.attr) or {}
            source_attr = spec.attr
            if not values and spec.fallback_attr is not None:
                values = day_values.get(spec.fallback_attr) or {}
                source_attr = spec.fallback_attr

            statistic_id = f"{DOMAIN}:plant_{plant_slug}_{spec.key}"

            if not values:
                series_summary[spec.key] = {
                    "statistic_id": statistic_id,
                    "imported_days": 0,
                    "skipped_days": requested_days,
                    "total_kwh": 0.0,
                    "status": "no_data",
                }
                continue

            rows_written = await _merge_and_write(
                hass,
                statistic_id,
                f"{plant_name} {spec.label}",
                values,
                coordinator,
                start_date=start_date,
                end_date=end_date,
                dry_run=dry_run,
            )
            if not dry_run:
                wrote_any = True

            series_summary[spec.key] = {
                "statistic_id": statistic_id,
                "imported_days": len(values),
                "skipped_days": requested_days - len(values),
                "total_kwh": round(sum(values.values()), 3),
                "source_field": source_attr,
                "rows_written": 0 if dry_run else rows_written,
                "status": "dry_run" if dry_run else "imported",
            }

        if wrote_any:
            # Exit drain (defense in depth): our own writes above are only
            # queued. Wait for them to commit before releasing the lock so
            # "lock released" implies "rows visible" for the next import
            # and the summary below reflects committed data. Deliberately
            # skipped for dry runs (nothing was queued).
            await get_instance(hass).async_block_till_done()

    _LOGGER.info(
        "Historical import %s for plant %s: %d cloud call(s), series=%s",
        "previewed (dry run)" if dry_run else "completed",
        plant_slug,
        api_calls,
        {key: info["imported_days"] for key, info in series_summary.items()},
    )

    if not call.return_response:
        return None

    return {
        "config_entry": entry.entry_id,
        "plant_id": coordinator.plant_id,
        "dry_run": dry_run,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "requested_days": requested_days,
        "units_queried": len(units),
        "api_calls": api_calls,
        "series": series_summary,
    }


def _resolve_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    """Resolve and validate the targeted config entry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            f"Config entry {entry_id} not found",
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state != ConfigEntryState.LOADED:
        raise ServiceValidationError(
            f"Config entry {entry_id} is not loaded",
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry


def _require_cloud_client(coordinator: EG4DataUpdateCoordinator) -> Any:
    """Return the cloud client or raise if this entry has no cloud access."""
    connection_type = coordinator.entry.data.get(CONF_CONNECTION_TYPE)
    if (
        connection_type not in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID)
        or coordinator.client is None
    ):
        raise ServiceValidationError(
            "Historical import requires cloud credentials "
            "(HTTP or Hybrid connection mode)",
            translation_domain=DOMAIN,
            translation_key="cloud_required",
        )
    return coordinator.client


def _validate_range(start_date: date, end_date: date | None) -> tuple[date, date]:
    """Validate and normalize the requested date range."""
    today = dt_util.now().date()
    if end_date is None or end_date > today:
        end_date = today

    if start_date > today or start_date > end_date:
        raise ServiceValidationError(
            f"Invalid date range: {start_date.isoformat()} to {end_date.isoformat()}",
            translation_domain=DOMAIN,
            translation_key="invalid_date_range",
            translation_placeholders={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

    range_days = (end_date - start_date).days + 1
    if range_days > MAX_RANGE_DAYS:
        raise ServiceValidationError(
            f"Date range of {range_days} days exceeds the maximum of "
            f"{MAX_RANGE_DAYS} days (2 years)",
            translation_domain=DOMAIN,
            translation_key="date_range_too_large",
            translation_placeholders={
                "range_days": str(range_days),
                "max_days": str(MAX_RANGE_DAYS),
            },
        )

    return start_date, end_date


def _collect_units(
    coordinator: EG4DataUpdateCoordinator,
) -> list[tuple[str, bool]]:
    """Collect (serial, parallel) query units covering the whole plant.

    Each parallel group becomes one parallel-aggregate query (server-side
    aggregation, matching the EG4 app); a single-inverter group and each
    standalone inverter become plain per-inverter queries. GridBOSS/MID
    devices are never queried (they have no energy history endpoint).
    """
    station = coordinator.station
    if station is None:
        raise ServiceValidationError(
            "Cloud station data is not loaded yet; try again shortly",
            translation_domain=DOMAIN,
            translation_key="station_not_ready",
        )

    units: list[tuple[str, bool]] = []
    for group in getattr(station, "parallel_groups", None) or []:
        inverters = getattr(group, "inverters", None) or []
        serials = [
            serial
            for inverter in inverters
            if (serial := getattr(inverter, "serial_number", None))
        ]
        if not serials:
            continue
        # Prefer the group's designated first device (what the EG4 app
        # queries the parallel aggregate with); fall back to any member.
        first_serial = getattr(group, "first_device_serial", None) or serials[0]
        units.append((first_serial, len(serials) > 1))

    for inverter in getattr(station, "standalone_inverters", None) or []:
        serial = getattr(inverter, "serial_number", None)
        if serial:
            units.append((serial, False))

    if not units:
        raise ServiceValidationError(
            "No inverters found for this plant",
            translation_domain=DOMAIN,
            translation_key="no_devices",
        )
    return units


def _plant_slug(coordinator: EG4DataUpdateCoordinator) -> str:
    """Build a statistic-ID-safe slug from the plant ID."""
    raw = str(coordinator.plant_id or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if not slug:
        raise ServiceValidationError(
            "This config entry has no plant ID",
            translation_domain=DOMAIN,
            translation_key="station_not_ready",
        )
    return slug


def _iter_months(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """List (year, month) tuples covering the inclusive date range."""
    months: list[tuple[int, int]] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


async def _fetch_daily_values(
    fetch_method: Any,
    units: list[tuple[str, bool]],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, dict[date, float]], int]:
    """Fetch and accumulate per-day kWh values for every tracked attribute.

    Values are summed across query units (parallel groups + standalone
    inverters). Days outside the requested range, in the future, or with
    no data for an attribute are omitted from that attribute's map.

    Returns:
        Tuple of (attr -> {day -> kWh} maps, number of cloud calls made).
    """
    accumulated: dict[str, dict[date, float]] = {
        attr: {} for attr in _ACCUMULATED_ATTRS
    }
    today = dt_util.now().date()
    months = _iter_months(start_date, end_date)
    api_calls = 0

    for serial, parallel in units:
        for year, month in months:
            try:
                history = await fetch_method(serial, year, month, parallel=parallel)
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to fetch energy history for {serial} "
                    f"({year}-{month:02d}): {err}"
                ) from err
            api_calls += 1

            for entry in getattr(history, "days", None) or []:
                try:
                    day = date(year, month, int(entry.day))
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "Skipping history entry with unparseable day %r for %s %d-%02d",
                        getattr(entry, "day", None),
                        serial,
                        year,
                        month,
                    )
                    continue
                if day < start_date or day > end_date or day > today:
                    continue
                for attr in _ACCUMULATED_ATTRS:
                    value = getattr(entry, attr, None)
                    if value is None:
                        continue
                    # Energy totals cannot be negative; the cloud
                    # occasionally returns small negative consumption
                    # values (the EG4 app clamps them too).
                    kwh = max(0.0, float(value))
                    day_map = accumulated[attr]
                    day_map[day] = day_map.get(day, 0.0) + kwh

            await asyncio.sleep(FETCH_DELAY_SECONDS)

    return accumulated, api_calls


def _is_fixed_offset_timezone(tz: Any) -> bool:
    """Return True for zones without DST rules.

    ``_get_station_timezone()`` parses cloud strings like "GMT -8" into
    ``Etc/GMT±N`` zoneinfo zones; plain ``datetime.timezone`` offsets have
    no ``key`` attribute at all. Genuine IANA zones (e.g.
    "America/Los_Angeles", "Asia/Kathmandu") keep their own key and are
    not considered fixed.
    """
    key = getattr(tz, "key", None)
    return key is None or str(key).startswith("Etc/")


def _resolve_statistics_timezone(coordinator: EG4DataUpdateCoordinator) -> Any:
    """Pick the timezone used to place daily statistics rows.

    Prefer Home Assistant's configured (IANA, DST-aware) timezone whenever
    the station timezone is unknown, unparsable (e.g. "GMT +5:30"), or a
    fixed offset — fixed offsets would drift daily rows to 01:00 local
    for half the year under DST. The HA instance lives at the plant in
    essentially all deployments, so its timezone is the best DST-aware
    proxy. A genuine IANA station timezone is used as-is.
    """
    station_tz = _get_station_timezone(coordinator)
    if station_tz is None or _is_fixed_offset_timezone(station_tz):
        return dt_util.DEFAULT_TIME_ZONE
    return station_tz


def _resolve_stored_tz(tz_key: str) -> Any:
    """Best-effort resolve a previously stored timezone key to a tzinfo.

    Return ``None`` when an older marker format or the current zoneinfo
    database cannot resolve the stored key.
    """
    return dt_util.get_time_zone(tz_key)


def _tz_produces_same_utc_starts(
    old_tz: Any, new_tz: Any, start_date: date, end_date: date
) -> bool:
    """Return whether two zones produce equal UTC midnights for every day."""
    day = start_date
    while day <= end_date:
        old_utc = dt_util.as_utc(datetime(day.year, day.month, day.day, tzinfo=old_tz))
        new_utc = dt_util.as_utc(datetime(day.year, day.month, day.day, tzinfo=new_tz))
        if old_utc != new_utc:
            return False
        day += timedelta(days=1)
    return True


def _is_tz_change_significant(
    previous_key: str | None,
    tz_key: str,
    tz: Any,
    start_date: date,
    end_date: date,
) -> bool:
    """Return whether a stored marker change can shift requested row starts."""
    if previous_key is None or previous_key == tz_key:
        return False
    old_tz = _resolve_stored_tz(previous_key)
    if old_tz is not None and _tz_produces_same_utc_starts(
        old_tz, tz, start_date, end_date
    ):
        return False
    return True


def _build_statistics(
    existing_rows: dict[datetime, float],
    new_rows: dict[datetime, float],
    tz: Any,
) -> list[StatisticData]:
    """Merge daily rows and rebuild cumulative sums from the earliest row."""
    merged = {**existing_rows, **new_rows}

    statistics: list[StatisticData] = []
    running_sum = 0.0
    for start in sorted(merged):
        state = merged[start]
        running_sum += state
        # The recorder requires top-of-the-hour timestamps in the
        # representation it receives (it converts to UTC itself). Local
        # midnight satisfies this for every timezone — including
        # half-hour-offset zones where the UTC representation would not.
        statistics.append(
            {"start": start.astimezone(tz), "state": state, "sum": running_sum}
        )
    return statistics


async def _merge_and_write(
    hass: HomeAssistant,
    statistic_id: str,
    name: str,
    new_day_values: dict[date, float],
    coordinator: EG4DataUpdateCoordinator,
    *,
    start_date: date,
    end_date: date,
    dry_run: bool,
) -> int:
    """Merge new daily values with existing rows and write statistics.

    The cumulative sum is recomputed across the FULL merged series from its
    earliest row, so re-imports and overlapping ranges always converge to
    consistent, monotonic sums. The recorder upserts on
    (statistic_id, start), making the whole operation idempotent. The requested
    ``start_date`` and ``end_date`` guard any whole-series clear after a
    resolved-timezone change; gaps in ``new_day_values`` do not narrow that
    safety check.

    Returns:
        Number of statistics rows that would be (or were) written.
    """
    tz = _resolve_statistics_timezone(coordinator)
    tz_key = getattr(tz, "key", None) or str(tz)

    new_rows: dict[datetime, float] = {}
    for day, kwh in new_day_values.items():
        local_midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
        new_rows[dt_util.as_utc(local_midnight)] = kwh

    if dry_run:
        existing_rows = await _load_existing_rows(hass, statistic_id)
        statistics = _build_statistics(existing_rows, new_rows, tz)
        _LOGGER.debug(
            "Dry run: would write %d rows for %s (%d new/updated)",
            len(statistics),
            statistic_id,
            len(new_rows),
        )
        return len(statistics)

    async with _TZ_MARKER_LOCK:
        store = Store[dict[str, str]](
            hass, HISTORY_IMPORT_TZ_STORAGE_VERSION, HISTORY_IMPORT_TZ_STORAGE_KEY
        )
        markers = await store.async_load() or {}
        previous = markers.get(statistic_id)

        # No marker means this is the first known import for the series. There
        # is no prior timezone to compare and nothing that should be cleared.
        tz_change_is_significant = _is_tz_change_significant(
            previous, tz_key, tz, start_date, end_date
        )
        existing_rows = await _load_existing_rows(hass, statistic_id)

        if tz_change_is_significant and previous is not None:
            if existing_rows:
                # Legacy marker strings may no longer resolve. In that edge
                # case, use the current zone as a best-effort approximation of
                # the existing rows' calendar-day span.
                day_tz = _resolve_stored_tz(previous) or tz
                existing_days = {
                    start.astimezone(day_tz).date() for start in existing_rows
                }
                first_existing = min(existing_days)
                last_existing = max(existing_days)
                if start_date > first_existing or end_date < last_existing:
                    raise ServiceValidationError(
                        f"The resolved timezone for {statistic_id} changed from "
                        f"{previous} to {tz_key}. Re-importing only part of the "
                        "previously-imported history would leave stale rows at "
                        "the old timezone's midnight and cause double counting. "
                        "Re-run the import with a date range covering "
                        f"{first_existing.isoformat()} to "
                        f"{last_existing.isoformat()} (the full span of existing "
                        "statistics for this series) so they can be rebuilt "
                        "safely.",
                        translation_domain=DOMAIN,
                        translation_key="tz_change_range_required",
                        translation_placeholders={
                            "statistic_id": statistic_id,
                            "old_timezone": previous,
                            "new_timezone": tz_key,
                            "first_existing_date": first_existing.isoformat(),
                            "last_existing_date": last_existing.isoformat(),
                        },
                    )

            _LOGGER.warning(
                "Resolved timezone changed for %s from %s to %s; requested "
                "range covers the existing span, clearing before rebuilding",
                statistic_id,
                previous,
                tz_key,
            )
            recorder = get_instance(hass)
            recorder.async_clear_statistics([statistic_id])
            await recorder.async_block_till_done()
            existing_rows = {}

        statistics = _build_statistics(existing_rows, new_rows, tz)
        metadata: StatisticMetaData = {
            "has_sum": True,
            "mean_type": StatisticMeanType.NONE,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": EnergyConverter.UNIT_CLASS,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }
        async_add_external_statistics(hass, metadata, statistics)
        markers[statistic_id] = tz_key
        await store.async_save(markers)

        _LOGGER.debug(
            "Wrote %d rows for %s (%d new/updated, %d pre-existing)",
            len(statistics),
            statistic_id,
            len(new_rows),
            len(existing_rows),
        )
        return len(statistics)


async def _load_existing_rows(
    hass: HomeAssistant, statistic_id: str
) -> dict[datetime, float]:
    """Load all existing rows (start -> state) for an external statistic."""
    recorder = get_instance(hass)
    stats = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {statistic_id},
        "hour",
        None,
        {"state"},
    )

    existing: dict[datetime, float] = {}
    for row in stats.get(statistic_id, []):
        state = row.get("state")
        start_ts = row.get("start")
        if state is None or start_ts is None:
            continue
        existing[dt_util.utc_from_timestamp(float(start_ts))] = float(state)
    return existing
