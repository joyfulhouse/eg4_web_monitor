"""Fixtures for EG4 Web Monitor integration tests."""

import threading
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


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
