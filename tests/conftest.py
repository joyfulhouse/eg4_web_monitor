"""Fixtures for EG4 Web Monitor integration tests."""

import threading
from unittest.mock import MagicMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


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
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
