"""Fixtures for EG4 Web Monitor integration tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


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
