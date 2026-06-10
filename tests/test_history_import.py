"""Tests for the import_historical_data service (history_import.py)."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import async_setup
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.history_import import (
    SERVICE_IMPORT_HISTORICAL_DATA,
    _iter_months,
    _merge_and_write,
    _load_existing_rows,
    _plant_slug,
    _validate_range,
    async_import_historical_data,
)

SERIAL = "1111111111"
SERIAL_2 = "2222222222"


def _day_entry(day, **kwh):
    """Build a fake DailyEnergyHistoryEntry with kWh properties."""
    attrs = {
        "inverter_kwh": None,
        "pv_kwh": None,
        "consumption_kwh": None,
        "import_kwh": None,
        "export_kwh": None,
        "charge_kwh": None,
        "discharge_kwh": None,
    }
    attrs.update(kwh)
    return SimpleNamespace(day=day, **attrs)


def _month_history(year, month, days):
    """Build a fake MonthlyEnergyHistory."""
    return SimpleNamespace(success=True, year=year, month=month, days=days)


@pytest.fixture
def mock_coordinator():
    """Create a mock cloud coordinator with station hierarchy."""
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.entry_id = "test_entry_id"
    coordinator.entry.title = "EG4 - Test Plant"
    coordinator.entry.data = {
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        CONF_PLANT_ID: "12345",
        CONF_PLANT_NAME: "Test Plant",
    }
    coordinator.plant_id = "12345"
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()

    coordinator.client = MagicMock()
    coordinator.client.close = AsyncMock()
    coordinator.client.analytics = MagicMock()
    coordinator.client.analytics.get_month_daily_energy = AsyncMock()

    inverter = MagicMock()
    inverter.serial_number = SERIAL
    group = MagicMock()
    group.inverters = [inverter]
    group.first_device_serial = SERIAL

    coordinator.station = MagicMock()
    coordinator.station.timezone = None
    coordinator.station.parallel_groups = [group]
    coordinator.station.standalone_inverters = []

    coordinator.data = {
        "devices": {SERIAL: {"type": "inverter", "model": "18kPV"}},
        "device_info": {},
        "parameters": {},
    }
    return coordinator


@pytest.fixture
def mock_config_entry(mock_coordinator):
    """Create a mock cloud config entry wired to the mock coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Test Plant",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )
    entry.runtime_data = mock_coordinator
    return entry


async def _setup_loaded_entry(hass, entry, coordinator):
    """Register the services and bring the entry into LOADED state."""
    await async_setup(hass, {})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)


def _call(data):
    """Build a minimal ServiceCall stand-in for direct handler tests."""
    payload = {"dry_run": False}
    payload.update(data)
    return SimpleNamespace(data=payload, return_response=True)


def _patch_stats():
    """Patch the recorder seams used by history_import."""
    return (
        patch(
            "custom_components.eg4_web_monitor.history_import."
            "async_add_external_statistics"
        ),
        patch(
            "custom_components.eg4_web_monitor.history_import._load_existing_rows",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.eg4_web_monitor.history_import.FETCH_DELAY_SECONDS",
            0,
        ),
    )


class TestServiceRegistration:
    """Service registration and end-to-end call."""

    async def test_setup_registers_service(self, hass: HomeAssistant):
        """async_setup registers the import_historical_data service."""
        assert await async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORICAL_DATA)

    async def test_full_service_call_with_response(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """A full service call imports statistics and returns a summary."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        mock_coordinator.client.analytics.get_month_daily_energy.return_value = (
            _month_history(
                2025,
                1,
                [
                    _day_entry(
                        1,
                        inverter_kwh=10.0,
                        import_kwh=1.5,
                        export_kwh=2.0,
                        charge_kwh=4.0,
                        discharge_kwh=3.5,
                        consumption_kwh=8.0,
                    ),
                    _day_entry(2, inverter_kwh=12.0),
                ],
            )
        )

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch:
            response = await hass.services.async_call(
                DOMAIN,
                SERVICE_IMPORT_HISTORICAL_DATA,
                {
                    "config_entry": "test_entry_id",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-02",
                },
                blocking=True,
                return_response=True,
            )

        assert response["plant_id"] == "12345"
        assert response["dry_run"] is False
        assert response["requested_days"] == 2
        assert response["api_calls"] == 1
        assert response["series"]["yield"]["imported_days"] == 2
        assert response["series"]["yield"]["total_kwh"] == 22.0
        assert (
            response["series"]["yield"]["statistic_id"]
            == "eg4_web_monitor:plant_12345_yield"
        )
        # 6 series, but only day 1 has data for the non-yield series
        assert response["series"]["grid_import"]["imported_days"] == 1
        assert mock_add.call_count == 6

    async def test_service_rejects_unknown_entry(self, hass: HomeAssistant):
        """Unknown config entry raises ServiceValidationError."""
        await async_setup(hass, {})
        with pytest.raises(ServiceValidationError, match="not found"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_IMPORT_HISTORICAL_DATA,
                {"config_entry": "missing", "start_date": "2025-01-01"},
                blocking=True,
                return_response=True,
            )

    async def test_service_rejects_unloaded_entry(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """A not-loaded entry raises ServiceValidationError."""
        await async_setup(hass, {})
        mock_config_entry.add_to_hass(hass)
        with pytest.raises(ServiceValidationError, match="not loaded"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_IMPORT_HISTORICAL_DATA,
                {"config_entry": "test_entry_id", "start_date": "2025-01-01"},
                blocking=True,
                return_response=True,
            )


class TestValidation:
    """Input validation for the handler."""

    async def test_local_only_entry_rejected(self, hass: HomeAssistant):
        """Local-only entries (no cloud client) are rejected."""
        coordinator = MagicMock()
        coordinator.entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
        coordinator.client = None
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
            entry_id="local_entry",
        )
        entry.runtime_data = coordinator
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)

        with pytest.raises(ServiceValidationError, match="cloud credentials"):
            await async_import_historical_data(
                hass,
                _call({"config_entry": "local_entry", "start_date": date(2025, 1, 1)}),
            )

    def test_validate_range_start_after_end(self):
        """start_date after end_date raises."""
        with pytest.raises(ServiceValidationError, match="Invalid date range"):
            _validate_range(date(2025, 2, 1), date(2025, 1, 1))

    def test_validate_range_start_in_future(self):
        """A future start_date raises."""
        future = dt_util.now().date() + timedelta(days=30)
        with pytest.raises(ServiceValidationError, match="Invalid date range"):
            _validate_range(future, None)

    def test_validate_range_too_large(self):
        """Ranges over two years are refused."""
        with pytest.raises(ServiceValidationError, match="exceeds the maximum"):
            _validate_range(date(2023, 1, 1), date(2025, 6, 1))

    def test_validate_range_defaults_and_clamps_end(self):
        """Missing end defaults to today; future end clamps to today."""
        today = dt_util.now().date()
        start = today - timedelta(days=5)

        assert _validate_range(start, None) == (start, today)
        assert _validate_range(start, today + timedelta(days=90)) == (start, today)

    def test_plant_slug(self, mock_coordinator):
        """Plant slug is statistic-id safe."""
        assert _plant_slug(mock_coordinator) == "12345"

        mock_coordinator.plant_id = "My Plant-42"
        assert _plant_slug(mock_coordinator) == "my_plant_42"

        mock_coordinator.plant_id = None
        with pytest.raises(ServiceValidationError):
            _plant_slug(mock_coordinator)

    def test_iter_months(self):
        """Month iteration covers the inclusive range across year boundaries."""
        assert _iter_months(date(2024, 11, 15), date(2025, 2, 3)) == [
            (2024, 11),
            (2024, 12),
            (2025, 1),
            (2025, 2),
        ]
        assert _iter_months(date(2025, 3, 1), date(2025, 3, 31)) == [(2025, 3)]


class TestStationAndUnits:
    """Station readiness and unit collection."""

    async def test_station_not_ready(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Missing station raises station_not_ready."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)
        mock_coordinator.station = None

        with pytest.raises(ServiceValidationError, match="not loaded yet"):
            await async_import_historical_data(
                hass,
                _call(
                    {"config_entry": "test_entry_id", "start_date": date(2025, 1, 1)}
                ),
            )

    async def test_no_devices(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """A station with no inverters raises no_devices."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)
        mock_coordinator.station.parallel_groups = []
        mock_coordinator.station.standalone_inverters = []

        with pytest.raises(ServiceValidationError, match="No inverters"):
            await async_import_historical_data(
                hass,
                _call(
                    {"config_entry": "test_entry_id", "start_date": date(2025, 1, 1)}
                ),
            )

    async def test_missing_library_method(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """A pylxpweb without the history API raises a clean error."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)
        mock_coordinator.client.analytics = SimpleNamespace()  # no method

        with pytest.raises(ServiceValidationError, match="pylxpweb"):
            await async_import_historical_data(
                hass,
                _call(
                    {"config_entry": "test_entry_id", "start_date": date(2025, 1, 1)}
                ),
            )

    async def test_parallel_group_uses_parallel_endpoint(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Multi-inverter groups query the parallel aggregate once."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        inverter2 = MagicMock()
        inverter2.serial_number = SERIAL_2
        mock_coordinator.station.parallel_groups[0].inverters.append(inverter2)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(2025, 1, [_day_entry(1, inverter_kwh=20.0)])

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 31),
                    }
                ),
            )

        fetch.assert_awaited_once_with(SERIAL, 2025, 1, parallel=True)
        assert response["units_queried"] == 1

    async def test_parallel_group_without_first_device_serial(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Groups without first_device_serial fall back to a member serial."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        group = mock_coordinator.station.parallel_groups[0]
        group.first_device_serial = None
        inverter2 = MagicMock()
        inverter2.serial_number = SERIAL_2
        group.inverters.append(inverter2)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(2025, 1, [_day_entry(1, inverter_kwh=1.0)])

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch, load_patch, delay_patch:
            await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 31),
                    }
                ),
            )

        fetch.assert_awaited_once_with(SERIAL, 2025, 1, parallel=True)

    async def test_multiple_units_summed(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Values from multiple standalone inverters are summed per day."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        inverter2 = MagicMock()
        inverter2.serial_number = SERIAL_2
        mock_coordinator.station.standalone_inverters = [inverter2]

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.side_effect = [
            _month_history(2025, 1, [_day_entry(1, inverter_kwh=10.0)]),
            _month_history(2025, 1, [_day_entry(1, inverter_kwh=5.5)]),
        ]

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 2),
                    }
                ),
            )

        assert response["api_calls"] == 2
        assert response["units_queried"] == 2
        assert response["series"]["yield"]["total_kwh"] == 15.5

        # The yield series rows carry the summed state
        yield_calls = [
            call
            for call in mock_add.call_args_list
            if call.args[1]["statistic_id"] == "eg4_web_monitor:plant_12345_yield"
        ]
        assert len(yield_calls) == 1
        rows = yield_calls[0].args[2]
        assert len(rows) == 1
        assert rows[0]["state"] == 15.5
        assert rows[0]["sum"] == 15.5


class TestStatisticsWrites:
    """Statistics metadata, rows, sums, dry run."""

    async def test_metadata_and_rows(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Metadata and row structure follow the external statistics contract."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(
            2025,
            1,
            [
                _day_entry(1, inverter_kwh=10.0),
                _day_entry(2, inverter_kwh=0.0),
                _day_entry(3, inverter_kwh=12.5),
            ],
        )

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch:
            await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 3),
                    }
                ),
            )

        yield_call = next(
            call
            for call in mock_add.call_args_list
            if call.args[1]["statistic_id"] == "eg4_web_monitor:plant_12345_yield"
        )
        metadata = yield_call.args[1]
        assert metadata["source"] == DOMAIN
        assert metadata["has_sum"] is True
        assert metadata["mean_type"] is StatisticMeanType.NONE
        assert metadata["unit_of_measurement"] == UnitOfEnergy.KILO_WATT_HOUR
        assert metadata["unit_class"] == "energy"
        assert metadata["name"] == "Test Plant PV yield"

        rows = yield_call.args[2]
        assert [row["state"] for row in rows] == [10.0, 0.0, 12.5]
        assert [row["sum"] for row in rows] == [10.0, 10.0, 22.5]
        # Rows start at local midnight, top of the hour, tz-aware
        for index, row in enumerate(rows):
            expected = dt_util.as_utc(
                datetime(2025, 1, 1 + index, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            )
            assert row["start"] == expected
            assert row["start"].minute == 0

    async def test_dry_run_writes_nothing(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """dry_run computes a summary but never writes statistics."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(2025, 1, [_day_entry(1, inverter_kwh=9.0)])

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 31),
                        "dry_run": True,
                    }
                ),
            )

        mock_add.assert_not_called()
        assert response["dry_run"] is True
        assert response["series"]["yield"]["status"] == "dry_run"
        assert response["series"]["yield"]["rows_written"] == 0
        assert response["series"]["yield"]["total_kwh"] == 9.0

    async def test_days_outside_range_and_future_skipped(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Days outside the range, future days and bad days are skipped."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(
            2025,
            2,
            [
                _day_entry(9, inverter_kwh=1.0),  # before range
                _day_entry(10, inverter_kwh=2.0),
                _day_entry(11, inverter_kwh=3.0),
                _day_entry(12, inverter_kwh=4.0),  # after range
                _day_entry(30, inverter_kwh=99.0),  # Feb 30 — invalid
            ],
        )

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 2, 10),
                        "end_date": date(2025, 2, 11),
                    }
                ),
            )

        assert response["series"]["yield"]["imported_days"] == 2
        assert response["series"]["yield"]["total_kwh"] == 5.0

    async def test_yield_falls_back_to_pv(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Without eInvDay data the yield series uses PV string totals."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(
            2025, 1, [_day_entry(1, pv_kwh=11.0), _day_entry(2, pv_kwh=13.0)]
        )

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 2),
                    }
                ),
            )

        assert response["series"]["yield"]["source_field"] == "pv_kwh"
        assert response["series"]["yield"]["total_kwh"] == 24.0
        assert response["series"]["consumption"]["status"] == "no_data"

    async def test_negative_values_clamped(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Negative cloud values are clamped to zero (matching the EG4 app)."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(
            2025, 1, [_day_entry(1, consumption_kwh=-2.5, inverter_kwh=5.0)]
        )

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch, load_patch, delay_patch:
            response = await async_import_historical_data(
                hass,
                _call(
                    {
                        "config_entry": "test_entry_id",
                        "start_date": date(2025, 1, 1),
                        "end_date": date(2025, 1, 1),
                    }
                ),
            )

        assert response["series"]["consumption"]["total_kwh"] == 0.0
        assert response["series"]["yield"]["total_kwh"] == 5.0

    async def test_fetch_error_raises_home_assistant_error(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """A cloud failure aborts the import with HomeAssistantError."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.side_effect = RuntimeError("boom")

        add_patch, load_patch, delay_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch:
            with pytest.raises(HomeAssistantError, match="Failed to fetch"):
                await async_import_historical_data(
                    hass,
                    _call(
                        {
                            "config_entry": "test_entry_id",
                            "start_date": date(2025, 1, 1),
                        }
                    ),
                )
        mock_add.assert_not_called()


class TestMergeAndIdempotency:
    """Sum reconstruction across existing and new rows."""

    async def test_merge_recomputes_sums_across_existing_rows(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """New rows merge with existing ones; sums rebuild monotonically."""
        tz = dt_util.DEFAULT_TIME_ZONE
        jan1 = dt_util.as_utc(datetime(2025, 1, 1, tzinfo=tz))
        jan3 = dt_util.as_utc(datetime(2025, 1, 3, tzinfo=tz))
        existing = {jan1: 1.0, jan3: 3.0}

        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value=existing),
            ),
        ):
            rows_written = await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                {date(2025, 1, 2): 2.0, date(2025, 1, 3): 3.5},
                mock_coordinator,
                dry_run=False,
            )

        assert rows_written == 3
        rows = mock_add.call_args.args[2]
        assert [row["state"] for row in rows] == [1.0, 2.0, 3.5]
        assert [row["sum"] for row in rows] == [1.0, 3.0, 6.5]
        sums = [row["sum"] for row in rows]
        assert sums == sorted(sums)

    async def test_reimport_same_range_is_idempotent(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """Re-importing identical data produces identical rows (no doubling)."""
        new_values = {date(2025, 1, 1): 5.0, date(2025, 1, 2): 6.0}
        tz = dt_util.DEFAULT_TIME_ZONE

        # First import: no existing rows
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add_1,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value={}),
            ),
        ):
            await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                new_values,
                mock_coordinator,
                dry_run=False,
            )
        first_rows = mock_add_1.call_args.args[2]

        # Second import: existing rows are what the first import wrote
        existing = {row["start"]: row["state"] for row in first_rows}
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add_2,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value=existing),
            ),
        ):
            await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                new_values,
                mock_coordinator,
                dry_run=False,
            )
        second_rows = mock_add_2.call_args.args[2]

        assert first_rows == second_rows
        expected_start = dt_util.as_utc(datetime(2025, 1, 1, tzinfo=tz))
        assert first_rows[0]["start"] == expected_start

    async def test_half_hour_timezone_rows_are_top_of_hour(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """Half-hour-offset station timezones still produce valid rows.

        The recorder requires minute == 0 in the representation it
        receives; UTC-converted midnights in zones like Asia/Kathmandu
        (+5:45) would violate that, so rows must be station-local.
        """
        mock_coordinator.station.timezone = "Asia/Kathmandu"

        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value={}),
            ),
        ):
            await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                {date(2025, 1, 1): 5.0, date(2025, 1, 2): 6.0},
                mock_coordinator,
                dry_run=False,
            )

        rows = mock_add.call_args.args[2]
        assert len(rows) == 2
        for row in rows:
            assert row["start"].minute == 0
            assert row["start"].second == 0
            assert row["start"].tzinfo is not None
        # Consecutive local midnights are 24h apart
        delta = rows[1]["start"] - rows[0]["start"]
        assert delta.total_seconds() == 86400

    async def test_dry_run_merge_does_not_write(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """_merge_and_write with dry_run never calls the recorder."""
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value={}),
            ),
        ):
            rows = await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                {date(2025, 1, 1): 5.0},
                mock_coordinator,
                dry_run=True,
            )

        assert rows == 1
        mock_add.assert_not_called()


class TestLoadExistingRows:
    """Reading existing external statistic rows from the recorder."""

    async def test_load_existing_rows_converts_timestamps(self, hass: HomeAssistant):
        """Rows come back keyed by UTC datetime with float states."""
        stat_id = "eg4_web_monitor:plant_12345_yield"
        ts1 = dt_util.as_utc(datetime(2025, 1, 1, tzinfo=dt_util.UTC)).timestamp()
        ts2 = ts1 + 86400

        recorder = MagicMock()
        recorder.async_add_executor_job = AsyncMock(
            return_value={
                stat_id: [
                    {"start": ts1, "state": 1.5},
                    {"start": ts2, "state": None},  # ignored
                    {"start": None, "state": 2.0},  # ignored
                ]
            }
        )

        with patch(
            "custom_components.eg4_web_monitor.history_import.get_instance",
            return_value=recorder,
        ):
            rows = await _load_existing_rows(hass, stat_id)

        assert rows == {dt_util.utc_from_timestamp(ts1): 1.5}
        # statistics_during_period invoked through the recorder executor
        assert recorder.async_add_executor_job.await_count == 1
