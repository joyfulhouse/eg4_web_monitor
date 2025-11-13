"""Fixtures for EG4 Web Monitor integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


@pytest.fixture
def hass(event_loop):
    """Return a Home Assistant instance for testing."""
    hass = HomeAssistant()
    hass.config.skip_pip = True
    event_loop.run_until_complete(async_setup_component(hass, "homeassistant", {}))
    yield hass
    event_loop.run_until_complete(hass.async_stop(force=True))


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.eg4_web_monitor.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
