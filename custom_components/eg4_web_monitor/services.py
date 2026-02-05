"""Service handlers for EG4 Web Monitor integration.

This module provides service handlers for:
- reconcile_history: Backfill energy statistics from cloud API
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance  # type: ignore[attr-defined]
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )

    from .coordinator import EG4DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Energy types supported for reconciliation
# These correspond to the EG4 cloud API energy types and their HA sensor keys
ENERGY_TYPE_MAPPING: dict[str, dict[str, str]] = {
    "eInvDay": {
        "sensor_key": "yield",
        "description": "Solar Production",
    },
    "eToUserDay": {
        "sensor_key": "grid_import",
        "description": "Grid Import",
    },
    "eToGridDay": {
        "sensor_key": "grid_export",
        "description": "Grid Export",
    },
    "eAcChargeDay": {
        "sensor_key": "charging",
        "description": "AC Charging",
    },
    "eBatChargeDay": {
        "sensor_key": "charging",
        "description": "Battery Charging",
    },
    "eBatDischargeDay": {
        "sensor_key": "discharging",
        "description": "Battery Discharging",
    },
}

# Rate limit: delay between API calls (seconds)
API_RATE_LIMIT_DELAY = 1.0


async def async_reconcile_history(
    hass: HomeAssistant,
    call: ServiceCall,
) -> None:
    """Handle reconcile_history service call.

    Fetches historical energy data from the cloud API and imports it into
    Home Assistant's statistics database for gap periods.

    Args:
        hass: Home Assistant instance
        call: Service call with optional parameters:
            - lookback_hours: Hours to look back (default: 48)
            - start_date: Explicit start date (YYYY-MM-DD)
            - end_date: Explicit end date (YYYY-MM-DD)
            - entry_id: Specific config entry to reconcile
    """
    entry_id = call.data.get("entry_id")
    lookback_hours = call.data.get("lookback_hours", 48)
    start_date_str = call.data.get("start_date")
    end_date_str = call.data.get("end_date")

    # Determine date range
    now = dt_util.now()
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(
                tzinfo=dt_util.DEFAULT_TIME_ZONE
            )
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                tzinfo=dt_util.DEFAULT_TIME_ZONE
            )
        except ValueError as err:
            raise ServiceValidationError(
                f"Invalid date format. Use YYYY-MM-DD: {err}",
                translation_domain=DOMAIN,
                translation_key="invalid_date_format",
            ) from err
    else:
        end_date = now
        start_date = now - timedelta(hours=lookback_hours)

    _LOGGER.info(
        "Reconciling history from %s to %s",
        start_date.strftime("%Y-%m-%d %H:%M"),
        end_date.strftime("%Y-%m-%d %H:%M"),
    )

    # Get coordinators to reconcile
    coordinators: list[EG4DataUpdateCoordinator] = []

    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
            )
        if entry.state != ConfigEntryState.LOADED:
            raise ServiceValidationError(
                f"Config entry {entry_id} is not loaded",
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
            )
        coordinators.append(entry.runtime_data)
    else:
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            if config_entry.state == ConfigEntryState.LOADED:
                coordinators.append(config_entry.runtime_data)

    if not coordinators:
        raise ServiceValidationError(
            "No EG4 coordinators found to reconcile",
            translation_domain=DOMAIN,
            translation_key="no_coordinators",
        )

    total_imported = 0
    total_gaps_found = 0

    for coordinator in coordinators:
        # Check for cloud credentials
        connection_type = coordinator.entry.data.get(CONF_CONNECTION_TYPE)
        if connection_type not in (CONNECTION_TYPE_HTTP, CONNECTION_TYPE_HYBRID):
            _LOGGER.warning(
                "Skipping %s - reconciliation requires cloud credentials "
                "(connection type: %s)",
                coordinator.entry.title,
                connection_type,
            )
            continue

        if coordinator.client is None:
            _LOGGER.warning(
                "Skipping %s - no cloud client available",
                coordinator.entry.title,
            )
            continue

        try:
            imported, gaps = await _reconcile_coordinator(
                hass, coordinator, start_date, end_date
            )
            total_imported += imported
            total_gaps_found += gaps
        except Exception as err:
            _LOGGER.error(
                "Failed to reconcile history for %s: %s",
                coordinator.entry.title,
                err,
            )
            raise HomeAssistantError(
                f"Reconciliation failed for {coordinator.entry.title}: {err}"
            ) from err

    _LOGGER.info(
        "History reconciliation complete: imported %d data points, found %d gaps",
        total_imported,
        total_gaps_found,
    )


async def _reconcile_coordinator(
    hass: HomeAssistant,
    coordinator: EG4DataUpdateCoordinator,
    start_date: datetime,
    end_date: datetime,
) -> tuple[int, int]:
    """Reconcile history for a single coordinator.

    Args:
        hass: Home Assistant instance
        coordinator: The coordinator to reconcile
        start_date: Start of reconciliation period
        end_date: End of reconciliation period

    Returns:
        Tuple of (total imported data points, total gaps found)
    """
    total_imported = 0
    total_gaps = 0

    # Get all inverter serials from coordinator data
    if not coordinator.data or "devices" not in coordinator.data:
        _LOGGER.debug("No device data available for %s", coordinator.entry.title)
        return 0, 0

    entity_registry = er.async_get(hass)

    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type")
        if device_type != "inverter":
            continue

        _LOGGER.debug("Reconciling history for inverter %s", serial)

        for energy_type, mapping in ENERGY_TYPE_MAPPING.items():
            sensor_key = mapping["sensor_key"]

            # Find the corresponding entity
            entity_id = _find_energy_entity(
                entity_registry, coordinator.entry.entry_id, serial, sensor_key
            )
            if not entity_id:
                _LOGGER.debug(
                    "No entity found for %s sensor %s on inverter %s",
                    mapping["description"],
                    sensor_key,
                    serial,
                )
                continue

            try:
                imported, gaps = await _reconcile_energy_sensor(
                    hass,
                    coordinator,
                    serial,
                    entity_id,
                    energy_type,
                    mapping["description"],
                    start_date,
                    end_date,
                )
                total_imported += imported
                total_gaps += gaps

                # Rate limit API calls
                await asyncio.sleep(API_RATE_LIMIT_DELAY)

            except Exception as err:
                _LOGGER.warning(
                    "Failed to reconcile %s for inverter %s: %s",
                    mapping["description"],
                    serial,
                    err,
                )

    return total_imported, total_gaps


def _find_energy_entity(
    entity_registry: er.EntityRegistry,
    config_entry_id: str,
    serial: str,
    sensor_key: str,
) -> str | None:
    """Find the entity ID for an energy sensor.

    Args:
        entity_registry: HA entity registry
        config_entry_id: Config entry ID
        serial: Inverter serial number
        sensor_key: Sensor key (e.g., "yield", "grid_import")

    Returns:
        Entity ID if found, None otherwise
    """
    # Build expected unique_id pattern: {serial}_energy_{sensor_key}
    expected_unique_id = f"{serial}_energy_{sensor_key}"

    for entity in er.async_entries_for_config_entry(entity_registry, config_entry_id):
        if entity.unique_id == expected_unique_id:
            return entity.entity_id

    # Also try without data_type prefix (some sensors might not have it)
    expected_unique_id_alt = f"{serial}_{sensor_key}"
    for entity in er.async_entries_for_config_entry(entity_registry, config_entry_id):
        if entity.unique_id == expected_unique_id_alt:
            return entity.entity_id

    return None


async def _reconcile_energy_sensor(
    hass: HomeAssistant,
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    entity_id: str,
    energy_type: str,
    description: str,
    start_date: datetime,
    end_date: datetime,
) -> tuple[int, int]:
    """Reconcile history for a single energy sensor.

    Args:
        hass: Home Assistant instance
        coordinator: The coordinator with cloud client
        serial: Inverter serial number
        entity_id: HA entity ID for the sensor
        energy_type: EG4 API energy type (e.g., "eInvDay")
        description: Human-readable description
        start_date: Start of reconciliation period
        end_date: End of reconciliation period

    Returns:
        Tuple of (imported count, gaps found)
    """
    statistic_id = entity_id

    # Get existing statistics to find gaps
    existing_stats = await _get_existing_statistics(
        hass, statistic_id, start_date, end_date
    )

    # Find gap hours
    gap_hours = _find_gap_hours(existing_stats, start_date, end_date)

    if not gap_hours:
        _LOGGER.debug("No gaps found for %s (%s)", entity_id, description)
        return 0, 0

    _LOGGER.info(
        "Found %d gap hours for %s (%s), fetching from cloud",
        len(gap_hours),
        entity_id,
        description,
    )

    # Group gaps by day for efficient API calls
    days_to_fetch = _group_gaps_by_day(gap_hours)

    # Fetch data from cloud API
    hourly_data = await _fetch_cloud_data(
        coordinator, serial, energy_type, days_to_fetch
    )

    if not hourly_data:
        _LOGGER.debug("No cloud data available for gaps in %s", entity_id)
        return 0, len(gap_hours)

    # Filter to only gap hours and transform to statistics format
    statistics = _transform_to_statistics(hourly_data, gap_hours, existing_stats)

    if not statistics:
        _LOGGER.debug("No statistics to import for %s", entity_id)
        return 0, len(gap_hours)

    # Import statistics
    # Note: mean_type and unit_class are required by StatisticMetaData TypedDict
    # but are only used for display purposes. For energy sensors, we use:
    # - mean_type: None (not applicable for energy totals)
    # - unit_class: None (we specify unit_of_measurement directly)
    metadata: StatisticMetaData = {
        "has_mean": False,
        "has_sum": True,
        "mean_type": None,  # type: ignore[typeddict-item]
        "name": None,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_class": None,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }

    async_import_statistics(hass, metadata, statistics)

    _LOGGER.info(
        "Imported %d statistics for %s (%s)",
        len(statistics),
        entity_id,
        description,
    )

    return len(statistics), len(gap_hours)


async def _get_existing_statistics(
    hass: HomeAssistant,
    statistic_id: str,
    start_date: datetime,
    end_date: datetime,
) -> dict[datetime, float]:
    """Get existing statistics for a sensor.

    Args:
        hass: Home Assistant instance
        statistic_id: Statistics ID (typically entity_id)
        start_date: Start of period
        end_date: End of period

    Returns:
        Dict mapping datetime to sum value
    """
    recorder = get_instance(hass)

    # Convert to UTC for statistics API
    start_utc = dt_util.as_utc(start_date)
    end_utc = dt_util.as_utc(end_date)

    stats = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        start_utc,
        end_utc,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )

    existing: dict[datetime, float] = {}
    if statistic_id in stats:
        for stat in stats[statistic_id]:
            sum_value = stat.get("sum")
            start_time = stat.get("start")
            # stat["start"] is a Unix timestamp (float), convert to datetime
            # stat["sum"] can be None if no data exists
            if sum_value is not None and start_time is not None:
                start_dt = dt_util.utc_from_timestamp(start_time)
                existing[start_dt] = float(sum_value)

    return existing


def _find_gap_hours(
    existing_stats: dict[datetime, float],
    start_date: datetime,
    end_date: datetime,
) -> list[datetime]:
    """Find hours without statistics data.

    Args:
        existing_stats: Dict of existing statistics (datetime -> sum)
        start_date: Start of period
        end_date: End of period

    Returns:
        List of datetime objects representing gap hours (in UTC)
    """
    gaps: list[datetime] = []

    # Round start to hour boundary
    current = start_date.replace(minute=0, second=0, microsecond=0)
    current_utc = dt_util.as_utc(current)
    end_utc = dt_util.as_utc(end_date)

    while current_utc < end_utc:
        if current_utc not in existing_stats:
            gaps.append(current_utc)
        current_utc = current_utc + timedelta(hours=1)

    return gaps


def _group_gaps_by_day(gap_hours: list[datetime]) -> set[str]:
    """Group gap hours by day for batch API calls.

    Args:
        gap_hours: List of gap hour datetimes (UTC)

    Returns:
        Set of date strings (YYYY-MM-DD)
    """
    days: set[str] = set()
    for dt in gap_hours:
        days.add(dt.strftime("%Y-%m-%d"))
    return days


async def _fetch_cloud_data(
    coordinator: EG4DataUpdateCoordinator,
    serial: str,
    energy_type: str,
    days: set[str],
) -> dict[datetime, float]:
    """Fetch hourly energy data from cloud API.

    Args:
        coordinator: Coordinator with cloud client
        serial: Inverter serial number
        energy_type: EG4 API energy type
        days: Set of date strings to fetch

    Returns:
        Dict mapping UTC datetime to energy value (Wh)
    """
    hourly_data: dict[datetime, float] = {}

    # Verify client is available
    if coordinator.client is None:
        _LOGGER.warning("No cloud client available for coordinator")
        return hourly_data

    for date_str in sorted(days):
        try:
            response = await coordinator.client.analytics.get_energy_day_breakdown(
                serial,
                date_str,
                energy_type,
                parallel=False,
            )

            # Parse date
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")

            # Handle multiple possible API response formats:
            # Format 1: data: [{hour: int, energy: int}] - observed in live testing
            # Format 2: dataPoints: [{period: str, value: number}] - OpenAPI spec
            # Format 3: data: {timestamps: [], values: []} - parallel arrays
            data_points = response.get("data") or response.get("dataPoints") or []

            # Log response format for debugging
            _LOGGER.debug(
                "Analytics response for %s on %s: keys=%s, data_type=%s",
                serial,
                date_str,
                list(response.keys()),
                type(data_points).__name__,
            )

            # Process based on data structure
            if isinstance(data_points, list):
                # Format 1 or 2: list of objects
                for point in data_points:
                    if not isinstance(point, dict):
                        continue

                    # Try Format 1: {hour, energy}
                    hour = point.get("hour")
                    energy = point.get("energy")

                    # Fallback to Format 2: {period, value}
                    if hour is None and "period" in point:
                        period = point.get("period", "")
                        # Parse period like "00:00" or "01:00"
                        if ":" in str(period):
                            try:
                                hour = int(str(period).split(":")[0])
                            except (ValueError, IndexError):
                                hour = 0
                        else:
                            hour = 0
                    if energy is None:
                        energy = point.get("value", 0)

                    if hour is None:
                        continue

                    _LOGGER.debug("Processing point: hour=%s, energy=%s", hour, energy)

                    # Create UTC datetime for this hour
                    local_dt = date_obj.replace(
                        hour=int(hour), minute=0, second=0, microsecond=0
                    )

                    # Get station timezone from coordinator if available
                    station_tz = _get_station_timezone(coordinator)
                    if station_tz:
                        local_dt = local_dt.replace(tzinfo=station_tz)
                    else:
                        local_dt = local_dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

                    utc_dt = dt_util.as_utc(local_dt)

                    # Energy is in Wh, store as-is for now
                    # Conversion to kWh happens during transformation
                    if energy and float(energy) > 0:
                        hourly_data[utc_dt] = float(energy)

            elif isinstance(data_points, dict):
                # Format 3: {timestamps: [], values: []}
                timestamps = data_points.get("timestamps", [])
                values = data_points.get("values", [])

                for i, (ts, val) in enumerate(zip(timestamps, values)):
                    # Parse timestamp like "00:00" or use index as hour
                    if isinstance(ts, str) and ":" in ts:
                        try:
                            hour = int(ts.split(":")[0])
                        except (ValueError, IndexError):
                            hour = i
                    else:
                        hour = i

                    local_dt = date_obj.replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    )

                    station_tz = _get_station_timezone(coordinator)
                    if station_tz:
                        local_dt = local_dt.replace(tzinfo=station_tz)
                    else:
                        local_dt = local_dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

                    utc_dt = dt_util.as_utc(local_dt)

                    if val and float(val) > 0:
                        hourly_data[utc_dt] = float(val)

            # Rate limit
            await asyncio.sleep(API_RATE_LIMIT_DELAY)

        except Exception as err:
            _LOGGER.warning(
                "Failed to fetch %s data for %s on %s: %s",
                energy_type,
                serial,
                date_str,
                err,
            )

    return hourly_data


def _get_station_timezone(coordinator: EG4DataUpdateCoordinator) -> Any:
    """Get station timezone from coordinator.

    Args:
        coordinator: The coordinator

    Returns:
        Timezone object or None
    """
    # Try to get timezone from station data
    if coordinator.station:
        tz_str = getattr(coordinator.station, "timezone", None)
        if tz_str:
            try:
                import zoneinfo

                # Parse timezone string like "GMT -8" or "America/Los_Angeles"
                if tz_str.startswith("GMT"):
                    # Convert "GMT -8" to UTC offset
                    offset_str = tz_str.replace("GMT", "").strip()
                    offset_hours = int(offset_str)
                    return dt_util.get_time_zone(f"Etc/GMT{-offset_hours:+d}")
                else:
                    return zoneinfo.ZoneInfo(tz_str)
            except Exception:
                pass

    return None


def _transform_to_statistics(
    hourly_data: dict[datetime, float],
    gap_hours: list[datetime],
    existing_stats: dict[datetime, float],
) -> list[StatisticData]:
    """Transform hourly energy data to HA statistics format.

    Args:
        hourly_data: Dict of UTC datetime to energy (Wh)
        gap_hours: List of gap hours to fill (UTC)
        existing_stats: Existing statistics for reference

    Returns:
        List of StatisticData dicts
    """
    statistics: list[StatisticData] = []

    # Get the last known sum before the gaps
    last_known_sum = 0.0
    sorted_existing = sorted(existing_stats.items(), key=lambda x: x[0])
    if sorted_existing:
        # Find the last sum before the first gap
        min_gap = min(gap_hours) if gap_hours else None
        for dt, value in sorted_existing:
            if min_gap and dt < min_gap:
                last_known_sum = value

    # Build statistics for gap hours that have cloud data
    running_sum = last_known_sum

    for gap_hour in sorted(gap_hours):
        if gap_hour in hourly_data:
            # Convert Wh to kWh
            energy_kwh = hourly_data[gap_hour] / 1000.0
            running_sum += energy_kwh

            statistics.append(
                {
                    "start": gap_hour,
                    "state": energy_kwh,  # Current hour's energy
                    "sum": running_sum,  # Cumulative sum
                }
            )

    return statistics
