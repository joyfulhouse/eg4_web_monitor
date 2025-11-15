"""Fixtures for EG4 Web Monitor integration tests."""

from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


# Enable custom integrations for testing
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def allow_shutdown_thread(monkeypatch):
    """Allow asyncio's _run_safe_shutdown_loop thread during cleanup verification.

    pytest-homeassistant-custom-component verifies no unexpected threads remain after tests.
    The asyncio event loop may create a daemon thread named '_run_safe_shutdown_loop'
    during shutdown which is expected and harmless. This fixture patches the verification
    to allow that specific thread.
    """
    import threading

    try:
        from pytest_homeassistant_custom_component import plugins

        original_verify_cleanup = plugins.verify_cleanup

        def patched_verify_cleanup(hass_storage, event_loop, application):
            """Modified cleanup verification that allows _run_safe_shutdown_loop thread."""
            # Get all threads
            threads = [thread for thread in threading.enumerate() if thread.is_alive()]

            # Filter out the allowed shutdown thread
            filtered_threads = [
                thread
                for thread in threads
                if not (
                    thread.name and "_run_safe_shutdown_loop" in thread.name
                )
            ]

            # Temporarily replace threading.enumerate to return filtered list
            orig_enumerate = threading.enumerate
            threading.enumerate = lambda: filtered_threads

            try:
                # Call original verify_cleanup with filtered threads
                return original_verify_cleanup(hass_storage, event_loop, application)
            finally:
                # Restore original enumerate
                threading.enumerate = orig_enumerate

        monkeypatch.setattr(plugins, "verify_cleanup", patched_verify_cleanup)
    except (ImportError, AttributeError):
        pass  # Plugin not available or different version

    yield


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
