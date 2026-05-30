"""Fixtures for EG4 Web Monitor integration tests."""

import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pylxpweb.devices import HybridInverter, MIDDevice
from pylxpweb.transports.data import (
    InverterEnergyData,
    InverterRuntimeData,
    MidboxRuntimeData,
)

pytest_plugins = "pytest_homeassistant_custom_component"


# =========================================================================
# Shape-faithful pylxpweb device builders (epic eg4-uqs)
# =========================================================================
# A plain MagicMock answers to ANY attribute, so a coordinator test passes even
# when the real pylxpweb object lacks the attribute the code reads — the exact
# blindness that let seam drift (e.g. eg4-ohz) ship undetected.
#
# These builders return REAL pylxpweb device objects (mock client — the client
# is only used for API calls, never by the property accessors) with REAL
# transport dataclasses injected.  The device's @property accessors compute for
# real, and reading an attribute the class does not define raises AttributeError
# — so a test fails the moment the integration relies on a non-existent
# pylxpweb attribute.  ``_map_device_properties`` then gets ``None`` for a
# missing property (its getattr default), exactly as in production.
#
# For pure transport dataclasses (InverterRuntimeData, InverterEnergyData,
# BatteryData, BatteryBankData, MidboxRuntimeData) construct the REAL dataclass
# directly in the test — they are trivial to instantiate and carry real field
# semantics; no helper is needed.


def make_real_inverter(
    serial_number: str = "1234567890",
    model: str = "FlexBOSS21",
    *,
    runtime: InverterRuntimeData | None = None,
    energy: InverterEnergyData | None = None,
    client: Any = None,
) -> HybridInverter:
    """Build a REAL HybridInverter with injected transport data.

    The client is mocked (only API methods use it); the property accessors read
    the injected ``InverterRuntimeData`` / ``InverterEnergyData``.  Reading an
    attribute the real class does not define raises AttributeError.
    """
    inverter = HybridInverter(client or MagicMock(), serial_number, model)
    if runtime is not None:
        inverter._transport_runtime = runtime
    if energy is not None:
        inverter._transport_energy = energy
    return inverter


def make_real_mid(
    serial_number: str = "0987654321",
    model: str = "GridBOSS",
    *,
    runtime: MidboxRuntimeData | None = None,
    client: Any = None,
) -> MIDDevice:
    """Build a REAL MIDDevice (GridBOSS) with injected runtime data."""
    mid = MIDDevice(client or MagicMock(), serial_number, model)
    if runtime is not None:
        mid._transport_runtime = runtime
    return mid


@pytest.fixture
def make_real_inverter_factory():
    """Fixture returning the ``make_real_inverter`` builder."""
    return make_real_inverter


@pytest.fixture
def make_real_mid_factory():
    """Fixture returning the ``make_real_mid`` builder."""
    return make_real_mid


def create_mock_station(
    station_id: str,
    station_name: str,
    country: str = "United States of America",
    timezone: str = "GMT -8",
    address: str = "123 Test St",
    create_date: str = "2025-01-01",
) -> MagicMock:
    """Create a mock Station object with all required fields.

    This helper ensures all mock stations have the complete set of fields
    that the coordinator expects to extract for station sensors.

    Args:
        station_id: Plant/station ID
        station_name: Station name
        country: Country name (defaults to "United States of America")
        timezone: Timezone string (defaults to "GMT -8")
        address: Physical address (defaults to "123 Test St")
        create_date: Plant creation date (defaults to "2025-01-01")

    Returns:
        MagicMock object configured as a Station with all required attributes
    """
    mock_station = MagicMock()
    mock_station.id = station_id
    mock_station.name = station_name
    mock_station.country = country
    mock_station.timezone = timezone
    mock_station.address = address
    mock_station.createDate = create_date
    return mock_station


def pytest_configure(config):
    """Configure pytest to allow asyncio shutdown threads.

    pytest-homeassistant-custom-component verifies no unexpected threads remain after tests.
    The asyncio event loop may create a daemon thread named '_run_safe_shutdown_loop'
    during shutdown which is expected and harmless. This configuration patches threading.enumerate
    to filter out this thread during cleanup verification.
    """
    # Store original threading.enumerate
    original_enumerate = threading.enumerate

    def filtered_enumerate():
        """Return all threads except asyncio shutdown thread."""
        threads = original_enumerate()
        return [
            thread
            for thread in threads
            if not (thread.name and "_run_safe_shutdown_loop" in thread.name)
        ]

    # Monkey-patch threading.enumerate globally
    threading.enumerate = filtered_enumerate


# Enable custom integrations for testing
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def mock_luxpower_client():
    """Mock LuxpowerClient from pylxpweb 0.3.5."""
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    mock_client.clear_cache = MagicMock()
    mock_client.plants = MagicMock()
    mock_client.devices = MagicMock()
    mock_client.control = MagicMock()
    return mock_client


@pytest.fixture
def mock_station():
    """Mock Station object from pylxpweb 0.3.5."""
    mock = MagicMock()
    mock.id = "123456"
    mock.name = "Test Station"
    mock.country = "United States of America"
    mock.timezone = "GMT -8"
    mock.address = "123 Test St"
    mock.createDate = "2025-01-01"
    mock.load = AsyncMock(return_value=mock)
    mock.refresh = AsyncMock()
    mock.refresh_all_data = AsyncMock()
    mock.detect_dst_status = MagicMock(return_value=True)
    mock.sync_dst_setting = AsyncMock(return_value=True)
    mock.all_inverters = []
    mock.all_batteries = []
    return mock


@pytest.fixture
def mock_coordinator(mock_luxpower_client, mock_station):
    """Mock EG4DataUpdateCoordinator with pylxpweb 0.3.5 client."""
    mock = MagicMock()
    mock.client = mock_luxpower_client
    mock.station = mock_station
    mock.async_shutdown = AsyncMock()
    mock._last_available_state = True
    return mock
