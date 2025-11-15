"""Fixtures for EG4 Web Monitor integration tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import get_test_home_assistant


@pytest.fixture
def hass(event_loop):
    """Return a Home Assistant instance for testing."""
    hass_instance = get_test_home_assistant()
    yield hass_instance
    event_loop.run_until_complete(hass_instance.async_stop(force=True))


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
