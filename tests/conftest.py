"""Fixtures for EG4 Web Monitor integration tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant


@pytest.fixture
async def hass(tmp_path):
    """Return a Home Assistant instance for testing."""
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True

    await hass.async_block_till_done()
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
