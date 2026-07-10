"""Tests for the import_historical_data service (history_import.py)."""

import asyncio
import zoneinfo
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

from custom_components.eg4_web_monitor import async_setup, history_import
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


@pytest.fixture
def fake_marker_store():
    """Provide an in-memory replacement that isolates each Store identity."""

    class FakeMarkerStore:
        data_by_store: dict[tuple[int, str], dict] = {}
        saved_payloads_by_store: dict[tuple[int, str], list[dict]] = {}
        yield_on_load = False

        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, _hass, version, key):
            self.store_id = (version, key)
            type(self).data_by_store.setdefault(self.store_id, {})
            type(self).saved_payloads_by_store.setdefault(self.store_id, [])

        @classmethod
        def data(cls, key, version=1):
            return cls.data_by_store.setdefault((version, key), {})

        @classmethod
        def seed(cls, key, data, version=1):
            cls.data_by_store[(version, key)] = dict(data)

        @classmethod
        def saved_payloads(cls, key, version=1):
            return cls.saved_payloads_by_store.setdefault((version, key), [])

        async def async_load(self):
            snapshot = dict(type(self).data_by_store[self.store_id])
            if type(self).yield_on_load:
                await asyncio.sleep(0)
            return snapshot

        async def async_save(self, data):
            payload = dict(data)
            type(self).data_by_store[self.store_id] = payload
            type(self).saved_payloads_by_store[self.store_id].append(payload)

    return FakeMarkerStore


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
    """Patch the recorder seams used by history_import.

    The patched get_instance serves the handler's recorder-queue drains
    (entry/exit); its async_block_till_done mock is shared across calls
    so tests can assert drain counts.
    """
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
        patch(
            "custom_components.eg4_web_monitor.history_import.get_instance",
            return_value=MagicMock(async_block_till_done=AsyncMock()),
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch, drain_patch:
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

    async def test_missing_analytics_namespace(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """A pylxpweb without the analytics namespace raises a clean error."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)
        # Old client object with no analytics attribute at all
        mock_coordinator.client = SimpleNamespace()

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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch, drain_patch as mock_gi:
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

        # Recorder queue drained twice: entry (read committed state) and
        # exit (writes visible before the lock releases)
        assert mock_gi.return_value.async_block_till_done.await_count == 2

    async def test_dry_run_writes_nothing(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """dry_run computes a summary but never writes statistics."""
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.return_value = _month_history(2025, 1, [_day_entry(1, inverter_kwh=9.0)])

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch, drain_patch as mock_gi:
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
        # Dry runs still drain on entry (read committed state) but skip the
        # exit drain — nothing was queued
        assert mock_gi.return_value.async_block_till_done.await_count == 1

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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch, load_patch, delay_patch, drain_patch:
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

        add_patch, load_patch, delay_patch, drain_patch = _patch_stats()
        with add_patch as mock_add, load_patch, delay_patch, drain_patch:
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
                start_date=date(2025, 1, 2),
                end_date=date(2025, 1, 3),
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
                start_date=min(new_values),
                end_date=max(new_values),
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
                start_date=min(new_values),
                end_date=max(new_values),
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
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 2),
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
        # A genuine IANA station timezone is used as-is (no HA-tz fallback):
        # the rows sit at Kathmandu midnight, not HA-timezone midnight.
        expected = dt_util.as_utc(
            datetime(2025, 1, 1, tzinfo=zoneinfo.ZoneInfo("Asia/Kathmandu"))
        )
        assert rows[0]["start"] == expected

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
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                dry_run=True,
            )

        assert rows == 1
        mock_add.assert_not_called()


class TestTimezoneChangeIdempotency:
    """Re-import behavior when the resolved statistics timezone changes."""

    async def test_timezone_change_does_not_double_count_day(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """A timezone change replaces the stale row for the same calendar day."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(hass_, metadata, rows):
            for row in rows:
                store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(hass_, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in store.items()
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            for key in list(store):
                if key[0] in statistic_ids:
                    del store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
        ):
            await hass.config.async_set_time_zone("America/Los_Angeles")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 5.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

            await hass.config.async_set_time_zone("America/New_York")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 5.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

        rows = [
            values for (sid, _start), values in store.items() if sid == statistic_id
        ]
        assert rows == [(5.0, 5.0)]
        recorder.async_clear_statistics.assert_called_once_with([statistic_id])
        assert recorder.async_block_till_done.await_count == 2

    async def test_partial_range_timezone_change_preserves_out_of_range_days(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """A partial re-import re-anchors and preserves every known day."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        day_values = {
            date(2025, 1, 1): 1.0,
            date(2025, 1, 2): 2.0,
            date(2025, 1, 3): 3.0,
            date(2025, 1, 4): 4.0,
            date(2025, 1, 5): 5.0,
        }
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            for key in list(statistics_store):
                if key[0] in statistic_ids:
                    del statistics_store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/Los_Angeles")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                day_values,
                mock_coordinator,
                start_date=min(day_values),
                end_date=max(day_values),
                dry_run=False,
            )
            old_starts = {
                start for sid, start in statistics_store if sid == statistic_id
            }

            await hass.config.async_set_time_zone("America/New_York")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {
                    date(2025, 1, 4): 40.0,
                    date(2025, 1, 5): 50.0,
                },
                mock_coordinator,
                start_date=date(2025, 1, 4),
                end_date=date(2025, 1, 5),
                dry_run=False,
            )

        ordered_rows = sorted(
            (start, values)
            for (sid, start), values in statistics_store.items()
            if sid == statistic_id
        )
        new_york = zoneinfo.ZoneInfo("America/New_York")
        expected_starts = [
            dt_util.as_utc(datetime(day.year, day.month, day.day, tzinfo=new_york))
            for day in day_values
        ]
        assert len(ordered_rows) == 5
        assert [start for start, _values in ordered_rows] == expected_starts
        assert old_starts.isdisjoint(expected_starts)
        assert [state for _start, (state, _sum) in ordered_rows] == [
            1.0,
            2.0,
            3.0,
            40.0,
            50.0,
        ]
        assert [running_sum for _start, (_state, running_sum) in ordered_rows] == [
            1.0,
            3.0,
            6.0,
            46.0,
            96.0,
        ]
        recorder.async_clear_statistics.assert_called_once_with([statistic_id])
        assert recorder.async_block_till_done.await_count == 2
        assert mock_add.call_count == 2
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_covering_range_timezone_change_rebuilds_without_double_count(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """A covering range replaces old-midnight rows and rebuilds sums."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        day_values = {
            date(2025, 1, 1): 1.0,
            date(2025, 1, 2): 2.0,
            date(2025, 1, 3): 3.0,
            date(2025, 1, 4): 4.0,
            date(2025, 1, 5): 5.0,
        }
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            for key in list(statistics_store):
                if key[0] in statistic_ids:
                    del statistics_store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/Los_Angeles")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                day_values,
                mock_coordinator,
                start_date=min(day_values),
                end_date=max(day_values),
                dry_run=False,
            )
            old_starts = {
                start for sid, start in statistics_store if sid == statistic_id
            }

            await hass.config.async_set_time_zone("America/New_York")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                day_values,
                mock_coordinator,
                start_date=date(2024, 12, 31),
                end_date=date(2025, 1, 6),
                dry_run=False,
            )

        ordered_rows = sorted(
            (start, values)
            for (sid, start), values in statistics_store.items()
            if sid == statistic_id
        )
        new_york = zoneinfo.ZoneInfo("America/New_York")
        expected_starts = [
            dt_util.as_utc(datetime(day.year, day.month, day.day, tzinfo=new_york))
            for day in day_values
        ]
        assert len(ordered_rows) == 5
        assert [start for start, _values in ordered_rows] == expected_starts
        assert old_starts.isdisjoint(expected_starts)
        assert [state for _start, (state, _sum) in ordered_rows] == [
            1.0,
            2.0,
            3.0,
            4.0,
            5.0,
        ]
        assert [running_sum for _start, (_state, running_sum) in ordered_rows] == [
            1.0,
            3.0,
            6.0,
            10.0,
            15.0,
        ]
        recorder.async_clear_statistics.assert_called_once_with([statistic_id])
        assert recorder.async_block_till_done.await_count == 2
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_covering_range_timezone_change_preserves_response_gap(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """A missing response day survives a covering timezone migration."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        day_values = {
            date(2025, 1, 1): 1.0,
            date(2025, 1, 2): 2.0,
            date(2025, 1, 3): 3.0,
            date(2025, 1, 4): 4.0,
            date(2025, 1, 5): 5.0,
        }
        fresh_values = {
            date(2025, 1, 1): 10.0,
            date(2025, 1, 2): 20.0,
            date(2025, 1, 4): 40.0,
            date(2025, 1, 5): 50.0,
        }
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            for key in list(statistics_store):
                if key[0] in statistic_ids:
                    del statistics_store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/Los_Angeles")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                day_values,
                mock_coordinator,
                start_date=min(day_values),
                end_date=max(day_values),
                dry_run=False,
            )

            await hass.config.async_set_time_zone("America/New_York")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                fresh_values,
                mock_coordinator,
                start_date=min(day_values),
                end_date=max(day_values),
                dry_run=False,
            )

        ordered_rows = sorted(
            (start, values)
            for (sid, start), values in statistics_store.items()
            if sid == statistic_id
        )
        new_york = zoneinfo.ZoneInfo("America/New_York")
        expected_starts = [
            dt_util.as_utc(datetime(day.year, day.month, day.day, tzinfo=new_york))
            for day in day_values
        ]
        assert [start for start, _values in ordered_rows] == expected_starts
        assert [state for _start, (state, _sum) in ordered_rows] == [
            10.0,
            20.0,
            3.0,
            40.0,
            50.0,
        ]
        assert [running_sum for _start, (_state, running_sum) in ordered_rows] == [
            10.0,
            30.0,
            33.0,
            73.0,
            123.0,
        ]
        assert len(ordered_rows) == 5
        recorder.async_clear_statistics.assert_called_once_with([statistic_id])
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_union_span_timezone_change_detects_dst_divergence(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Existing summer data exposes zones that only agree in winter."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        winter_day = date(2025, 1, 15)
        summer_day = date(2025, 7, 15)
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            for key in list(statistics_store):
                if key[0] in statistic_ids:
                    del statistics_store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/Phoenix")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {winter_day: 1.0, summer_day: 7.0},
                mock_coordinator,
                start_date=winter_day,
                end_date=summer_day,
                dry_run=False,
            )
            phoenix_starts = {
                start for sid, start in statistics_store if sid == statistic_id
            }

            await hass.config.async_set_time_zone("America/Denver")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {winter_day: 10.0},
                mock_coordinator,
                start_date=winter_day,
                end_date=winter_day,
                dry_run=False,
            )

        phoenix = zoneinfo.ZoneInfo("America/Phoenix")
        denver = zoneinfo.ZoneInfo("America/Denver")
        old_winter_start = dt_util.as_utc(
            datetime(winter_day.year, winter_day.month, winter_day.day, tzinfo=phoenix)
        )
        new_winter_start = dt_util.as_utc(
            datetime(winter_day.year, winter_day.month, winter_day.day, tzinfo=denver)
        )
        old_summer_start = dt_util.as_utc(
            datetime(summer_day.year, summer_day.month, summer_day.day, tzinfo=phoenix)
        )
        new_summer_start = dt_util.as_utc(
            datetime(summer_day.year, summer_day.month, summer_day.day, tzinfo=denver)
        )
        assert old_winter_start == new_winter_start
        assert old_summer_start != new_summer_start
        assert phoenix_starts == {old_winter_start, old_summer_start}
        assert (statistic_id, old_summer_start) not in statistics_store
        assert statistics_store[(statistic_id, new_winter_start)] == (10.0, 10.0)
        assert statistics_store[(statistic_id, new_summer_start)] == (7.0, 17.0)
        assert len(statistics_store) == 2
        recorder.async_clear_statistics.assert_called_once_with([statistic_id])
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/Denver"
        }

    async def test_unresolvable_timezone_marker_fails_closed(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """An unknown old marker aborts without clearing, writing, or saving."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_TZ_STORAGE_KEY,
            {statistic_id: "Not/ARealZone"},
        )
        existing = {
            dt_util.as_utc(
                datetime(
                    imported_day.year,
                    imported_day.month,
                    imported_day.day,
                    tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
                )
            ): 5.0
        }
        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value=existing),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            with pytest.raises(
                ServiceValidationError, match="can no longer be resolved"
            ):
                await _merge_and_write(
                    hass,
                    statistic_id,
                    "Test Plant PV yield",
                    {imported_day: 6.0},
                    mock_coordinator,
                    start_date=imported_day,
                    end_date=imported_day,
                    dry_run=False,
                )

        recorder.async_clear_statistics.assert_not_called()
        recorder.async_block_till_done.assert_not_awaited()
        mock_add.assert_not_called()
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "Not/ARealZone"
        }
        assert (
            fake_marker_store.saved_payloads(
                history_import.HISTORY_IMPORT_TZ_STORAGE_KEY
            )
            == []
        )

    async def test_unresolvable_timezone_marker_with_empty_series_succeeds(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """An unknown old marker is replaceable when no rows need protection."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_TZ_STORAGE_KEY,
            {statistic_id: "Not/ARealZone"},
        )
        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            rows_written = await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 6.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

        assert rows_written == 1
        mock_add.assert_called_once()
        recorder.async_clear_statistics.assert_not_called()
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_missing_marker_with_misaligned_rows_fails_closed(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Untracked rows outside current-tz midnight alignment are rejected."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        existing = {datetime(2025, 1, 15, 12, tzinfo=dt_util.UTC): 5.0}
        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value=existing),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            with pytest.raises(ServiceValidationError) as err:
                await _merge_and_write(
                    hass,
                    statistic_id,
                    "Test Plant PV yield",
                    {imported_day: 6.0},
                    mock_coordinator,
                    start_date=imported_day,
                    end_date=imported_day,
                    dry_run=False,
                )

        assert err.value.translation_key == "tz_marker_missing_misaligned"
        recorder.async_clear_statistics.assert_not_called()
        mock_add.assert_not_called()
        assert (
            fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {}
        )

    async def test_missing_marker_with_aligned_rows_merges_normally(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Correctly anchored pre-marker history starts marker tracking."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        old_day = date(2025, 1, 14)
        new_day = date(2025, 1, 15)
        new_york = zoneinfo.ZoneInfo("America/New_York")
        existing = {
            dt_util.as_utc(
                datetime(old_day.year, old_day.month, old_day.day, tzinfo=new_york)
            ): 5.0
        }
        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ) as mock_add,
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value=existing),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            rows_written = await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {new_day: 6.0},
                mock_coordinator,
                start_date=new_day,
                end_date=new_day,
                dry_run=False,
            )

        assert rows_written == 2
        assert [row["state"] for row in mock_add.call_args.args[2]] == [5.0, 6.0]
        recorder.async_clear_statistics.assert_not_called()
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_migration_snapshot_precedes_clear_and_is_deleted_after_verify(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """A genuine migration snapshots first and removes it after verification."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        old_day = date(2025, 1, 14)
        new_day = date(2025, 1, 15)
        old_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        statistics_store = {
            (
                statistic_id,
                dt_util.as_utc(
                    datetime(old_day.year, old_day.month, old_day.day, tzinfo=old_tz)
                ),
            ): (5.0, 5.0)
        }
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_TZ_STORAGE_KEY,
            {statistic_id: "America/Los_Angeles"},
        )

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        def fake_clear(statistic_ids):
            migration_data = fake_marker_store.data(
                history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY
            )
            assert migration_data == {
                statistic_id: {
                    "tz_key": "America/New_York",
                    "rows": {old_day.isoformat(): 5.0},
                }
            }
            for key in list(statistics_store):
                if key[0] in statistic_ids:
                    del statistics_store[key]

        recorder = MagicMock()
        recorder.async_clear_statistics = MagicMock(side_effect=fake_clear)
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {new_day: 6.0},
                mock_coordinator,
                start_date=new_day,
                end_date=new_day,
                dry_run=False,
            )

        assert recorder.async_clear_statistics.call_count == 1
        snapshot_saves = fake_marker_store.saved_payloads(
            history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY
        )
        assert snapshot_saves[0][statistic_id]["rows"] == {old_day.isoformat(): 5.0}
        assert snapshot_saves[-1] == {}
        assert (
            fake_marker_store.data(history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY)
            == {}
        )
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }

    async def test_migration_verification_failure_keeps_marker_and_snapshot(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Missing post-write rows preserve recovery state without raising."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        old_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        existing = {
            dt_util.as_utc(
                datetime(
                    imported_day.year,
                    imported_day.month,
                    imported_day.day,
                    tzinfo=old_tz,
                )
            ): 5.0
        }
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_TZ_STORAGE_KEY,
            {statistic_id: "America/Los_Angeles"},
        )
        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(side_effect=[existing, {}]),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            rows_written = await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 6.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

        assert rows_written == 1
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/Los_Angeles"
        }
        assert fake_marker_store.data(
            history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY
        ) == {
            statistic_id: {
                "tz_key": "America/New_York",
                "rows": {imported_day.isoformat(): 5.0},
            }
        }

    async def test_pending_migration_recovers_empty_database_without_data_loss(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """A pending snapshot restores cleared rows and merges fresh data."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        recovered_day = date(2025, 1, 14)
        fresh_day = date(2025, 1, 15)
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_TZ_STORAGE_KEY,
            {statistic_id: "America/Los_Angeles"},
        )
        fake_marker_store.seed(
            history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY,
            {
                statistic_id: {
                    "tz_key": "America/New_York",
                    "rows": {recovered_day.isoformat(): 5.0},
                }
            },
        )

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/New_York")
            rows_written = await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {fresh_day: 6.0},
                mock_coordinator,
                start_date=fresh_day,
                end_date=fresh_day,
                dry_run=False,
            )

        ordered_rows = sorted(
            (start, values)
            for (stored_statistic_id, start), values in statistics_store.items()
            if stored_statistic_id == statistic_id
        )
        assert rows_written == 2
        assert [
            start.astimezone(zoneinfo.ZoneInfo("America/New_York")).date()
            for start, _ in ordered_rows
        ] == [
            recovered_day,
            fresh_day,
        ]
        assert [values for _start, values in ordered_rows] == [
            (5.0, 5.0),
            (6.0, 11.0),
        ]
        recorder.async_clear_statistics.assert_not_called()
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "America/New_York"
        }
        assert (
            fake_marker_store.data(history_import.HISTORY_IMPORT_MIGRATION_STORAGE_KEY)
            == {}
        )

    async def test_equivalent_timezone_alias_does_not_clear(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Equivalent timezone keys merge normally without a destructive clear."""
        statistic_id = "eg4_web_monitor:plant_12345_yield"
        imported_day = date(2025, 1, 15)
        statistics_store: dict[tuple[str, datetime], tuple[float, float]] = {}

        def fake_add(_hass, metadata, rows):
            for row in rows:
                statistics_store[(metadata["statistic_id"], row["start"])] = (
                    row["state"],
                    row["sum"],
                )

        async def fake_load(_hass, requested_statistic_id):
            return {
                start: state
                for (stored_statistic_id, start), (state, _sum) in (
                    statistics_store.items()
                )
                if stored_statistic_id == requested_statistic_id
            }

        recorder = MagicMock()
        recorder.async_block_till_done = AsyncMock()

        mock_coordinator.station.timezone = None
        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics",
                side_effect=fake_add,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=fake_load,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.get_instance",
                return_value=recorder,
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("UTC")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 5.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

            await hass.config.async_set_time_zone("Etc/UTC")
            await _merge_and_write(
                hass,
                statistic_id,
                "Test Plant PV yield",
                {imported_day: 5.0},
                mock_coordinator,
                start_date=imported_day,
                end_date=imported_day,
                dry_run=False,
            )

        rows = [
            values
            for (stored_statistic_id, _start), values in statistics_store.items()
            if stored_statistic_id == statistic_id
        ]
        assert rows == [(5.0, 5.0)]
        recorder.async_clear_statistics.assert_not_called()
        recorder.async_block_till_done.assert_not_awaited()
        assert fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY) == {
            statistic_id: "Etc/UTC"
        }

    async def test_concurrent_marker_writes_preserve_both_statistic_ids(
        self, hass: HomeAssistant, mock_coordinator, fake_marker_store
    ):
        """Cross-plant writes serialize the shared marker load-modify-save."""
        statistic_ids = (
            "eg4_web_monitor:plant_alpha_yield",
            "eg4_web_monitor:plant_beta_yield",
        )
        imported_day = date(2025, 1, 15)
        fake_marker_store.yield_on_load = True

        with (
            patch(
                "custom_components.eg4_web_monitor.history_import."
                "async_add_external_statistics"
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import._load_existing_rows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "custom_components.eg4_web_monitor.history_import.Store",
                new=fake_marker_store,
            ),
        ):
            await hass.config.async_set_time_zone("America/Los_Angeles")
            await asyncio.gather(
                *(
                    _merge_and_write(
                        hass,
                        statistic_id,
                        "Test Plant PV yield",
                        {imported_day: 5.0},
                        mock_coordinator,
                        start_date=imported_day,
                        end_date=imported_day,
                        dry_run=False,
                    )
                    for statistic_id in statistic_ids
                )
            )

        expected_markers = {
            statistic_id: "America/Los_Angeles" for statistic_id in statistic_ids
        }
        assert (
            fake_marker_store.data(history_import.HISTORY_IMPORT_TZ_STORAGE_KEY)
            == expected_markers
        )
        assert (
            fake_marker_store.saved_payloads(
                history_import.HISTORY_IMPORT_TZ_STORAGE_KEY
            )[-1]
            == expected_markers
        )


class TestTimezoneResolution:
    """Station timezone handling for daily row placement."""

    async def test_station_gmt_offset_prefers_ha_timezone(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """Fixed-offset cloud zones ("GMT -8") defer to HA's DST-aware tz."""
        await hass.config.async_set_time_zone("America/Los_Angeles")
        mock_coordinator.station.timezone = "GMT -8"
        la = zoneinfo.ZoneInfo("America/Los_Angeles")

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
                {date(2025, 1, 15): 1.0, date(2025, 7, 15): 2.0},
                mock_coordinator,
                start_date=date(2025, 1, 15),
                end_date=date(2025, 7, 15),
                dry_run=False,
            )

        rows = mock_add.call_args.args[2]
        # Winter (PST, -8) and summer (PDT, -7) rows both at LA local midnight
        assert rows[0]["start"] == dt_util.as_utc(datetime(2025, 1, 15, tzinfo=la))
        assert rows[1]["start"] == dt_util.as_utc(datetime(2025, 7, 15, tzinfo=la))
        # The fixed Etc/GMT+8 zone would have drifted the summer row to
        # 01:00 local (one hour later in UTC)
        fixed = dt_util.get_time_zone("Etc/GMT+8")
        assert rows[1]["start"] != dt_util.as_utc(datetime(2025, 7, 15, tzinfo=fixed))

    async def test_station_gmt_half_hour_string_falls_back_to_ha_tz(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """Unparsable "GMT +5:30" strings fall back to the HA timezone."""
        await hass.config.async_set_time_zone("America/Los_Angeles")
        mock_coordinator.station.timezone = "GMT +5:30"
        la = zoneinfo.ZoneInfo("America/Los_Angeles")

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
                {date(2025, 1, 1): 5.0},
                mock_coordinator,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                dry_run=False,
            )

        rows = mock_add.call_args.args[2]
        assert rows[0]["start"] == dt_util.as_utc(datetime(2025, 1, 1, tzinfo=la))
        assert rows[0]["start"].minute == 0

    async def test_dst_transition_days_have_single_midnight_rows(
        self, hass: HomeAssistant, mock_coordinator
    ):
        """23h/25h DST-transition days produce exactly one row at midnight."""
        await hass.config.async_set_time_zone("America/Los_Angeles")
        mock_coordinator.station.timezone = "GMT -8"
        la = zoneinfo.ZoneInfo("America/Los_Angeles")

        # US 2025: spring forward Mar 9 (23h day), fall back Nov 2 (25h day)
        spring = {date(2025, 3, 8): 1.0, date(2025, 3, 9): 2.0, date(2025, 3, 10): 3.0}
        fall = {date(2025, 11, 1): 1.0, date(2025, 11, 2): 2.0, date(2025, 11, 3): 3.0}

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
                spring,
                mock_coordinator,
                start_date=min(spring),
                end_date=max(spring),
                dry_run=False,
            )
            await _merge_and_write(
                hass,
                "eg4_web_monitor:plant_12345_yield",
                "Test Plant PV yield",
                fall,
                mock_coordinator,
                start_date=min(fall),
                end_date=max(fall),
                dry_run=False,
            )

        spring_rows = mock_add.call_args_list[0].args[2]
        fall_rows = mock_add.call_args_list[1].args[2]
        assert len(spring_rows) == 3
        assert len(fall_rows) == 3

        for rows, days in ((spring_rows, sorted(spring)), (fall_rows, sorted(fall))):
            for row, day in zip(rows, days, strict=True):
                assert row["start"] == dt_util.as_utc(
                    datetime(day.year, day.month, day.day, tzinfo=la)
                )
                assert row["start"].minute == 0

        # Compare absolute instants via timestamp(): subtracting aware
        # datetimes that share a tzinfo uses wall-clock arithmetic and
        # would hide the DST shift.
        spring_deltas = [
            b["start"].timestamp() - a["start"].timestamp()
            for a, b in zip(spring_rows, spring_rows[1:], strict=False)
        ]
        fall_deltas = [
            b["start"].timestamp() - a["start"].timestamp()
            for a, b in zip(fall_rows, fall_rows[1:], strict=False)
        ]
        assert spring_deltas == [24 * 3600, 23 * 3600]  # spring-forward day
        assert fall_deltas == [24 * 3600, 25 * 3600]  # fall-back day


class TestConcurrency:
    """Per-plant lock serializes concurrent imports."""

    async def test_concurrent_imports_for_same_plant_serialize(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Concurrent disjoint-range imports equal the serial result.

        The fakes model the real recorder: async_add_external_statistics
        only QUEUES rows (pending list); they become readable in the store
        only when get_instance(hass).async_block_till_done() is awaited.
        This guards BOTH the per-plant lock and the entry/exit queue
        drains — without the drains, queued rows are never visible to the
        next import's _load_existing_rows and the February sums would
        restart at zero instead of continuing from January.
        """
        await _setup_loaded_entry(hass, mock_config_entry, mock_coordinator)

        def fetch_side_effect(serial, year, month, *, parallel=False):
            if month == 1:
                return _month_history(
                    2025,
                    1,
                    [_day_entry(1, inverter_kwh=1.0), _day_entry(2, inverter_kwh=2.0)],
                )
            return _month_history(
                2025,
                2,
                [_day_entry(1, inverter_kwh=3.0), _day_entry(2, inverter_kwh=4.0)],
            )

        fetch = mock_coordinator.client.analytics.get_month_daily_energy
        fetch.side_effect = fetch_side_effect

        # Committed, readable statistics (what the DB would contain)
        store: dict[tuple, tuple] = {}
        # Queued-but-uncommitted writes (the recorder task queue)
        pending: list[tuple[str, list]] = []

        def fake_add(hass_, metadata, rows):
            pending.append((metadata["statistic_id"], list(rows)))

        def fake_get_instance(hass_):
            recorder = MagicMock()

            async def drain():
                # Both drains must run INSIDE the per-plant lock: a drain
                # awaited with the lock free means the recorder barrier
                # moved outside the critical section, reopening the
                # stale-snapshot race (round-3 review contract).
                assert any(
                    plant_lock.locked()
                    for plant_lock in history_import._IMPORT_LOCKS.values()
                ), "recorder drain awaited without holding the import lock"
                await asyncio.sleep(0)
                while pending:
                    sid, rows = pending.pop(0)
                    for row in rows:
                        store[(sid, row["start"])] = (row["state"], row["sum"])

            recorder.async_block_till_done = drain
            return recorder

        async def fake_load(hass_, statistic_id):
            # Snapshot committed state first, then suspend before
            # returning — mirroring the real recorder executor (DB read,
            # then resume on the event loop). Without the per-plant lock,
            # the other import writes during this suspension and the
            # snapshot is stale.
            snapshot = {
                start: state
                for (sid, start), (state, _sum) in store.items()
                if sid == statistic_id
            }
            await asyncio.sleep(0)
            return snapshot

        def call_jan():
            return _call(
                {
                    "config_entry": "test_entry_id",
                    "start_date": date(2025, 1, 1),
                    "end_date": date(2025, 1, 31),
                }
            )

        def call_feb():
            return _call(
                {
                    "config_entry": "test_entry_id",
                    "start_date": date(2025, 2, 1),
                    "end_date": date(2025, 2, 28),
                }
            )

        def patches():
            return (
                patch(
                    "custom_components.eg4_web_monitor.history_import."
                    "async_add_external_statistics",
                    side_effect=fake_add,
                ),
                patch(
                    "custom_components.eg4_web_monitor.history_import."
                    "_load_existing_rows",
                    new=fake_load,
                ),
                patch(
                    "custom_components.eg4_web_monitor.history_import."
                    "FETCH_DELAY_SECONDS",
                    0,
                ),
                patch(
                    "custom_components.eg4_web_monitor.history_import.get_instance",
                    side_effect=fake_get_instance,
                ),
            )

        # Serial ground truth
        add_patch, load_patch, delay_patch, drain_patch = patches()
        with add_patch, load_patch, delay_patch, drain_patch:
            await async_import_historical_data(hass, call_jan())
            await async_import_historical_data(hass, call_feb())
        # The exit drain must have committed everything before returning
        assert not pending
        store_serial = dict(store)
        store.clear()
        pending.clear()

        # Concurrent run must converge to the identical final rows
        add_patch, load_patch, delay_patch, drain_patch = patches()
        with add_patch, load_patch, delay_patch, drain_patch:
            await asyncio.gather(
                async_import_historical_data(hass, call_jan()),
                async_import_historical_data(hass, call_feb()),
            )

        assert not pending
        assert store == store_serial

        # Recompute math: February sums continue from January's total
        yield_id = "eg4_web_monitor:plant_12345_yield"
        ordered = sorted(
            (start, values) for (sid, start), values in store.items() if sid == yield_id
        )
        assert [state for _, (state, _sum) in ordered] == [1.0, 2.0, 3.0, 4.0]
        assert [running for _, (_state, running) in ordered] == [1.0, 3.0, 6.0, 10.0]


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
