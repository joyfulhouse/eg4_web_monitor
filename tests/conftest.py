"""Fixtures for EG4 Web Monitor integration tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import async_test_home_assistant


@pytest.fixture
async def hass(tmp_path):
    """Return a Home Assistant instance for testing."""
    hass = await async_test_home_assistant(tmp_path)
    yield hass
    await hass.async_stop(force=True)


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
