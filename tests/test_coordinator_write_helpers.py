"""Unit tests for the coordinator write helpers (require_client,
refresh_inverter_params_if_linked, params_are_local_raw) against the REAL
EG4DataUpdateCoordinator — conftest.wire_coordinator_write_helpers only
re-implements these on a MagicMock and cannot catch drift."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from homeassistant.exceptions import HomeAssistantError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


@pytest.fixture
def local_config_entry():
    """Create a config entry for LOCAL connection mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Electronics - FlexBOSS21",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "1234567890",
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        entry_id="local_write_helpers_test_entry",
    )


@pytest.fixture
def real_coordinator(hass, local_config_entry):
    """Create a real coordinator without replacing its write helpers."""
    return EG4DataUpdateCoordinator(hass, local_config_entry)


def test_require_client_returns_client(real_coordinator):
    real_coordinator.client = MagicMock()
    assert real_coordinator.require_client() is real_coordinator.client


def test_require_client_raises_exact_message(real_coordinator):
    real_coordinator.client = None
    with pytest.raises(HomeAssistantError) as exc:
        real_coordinator.require_client()
    assert str(exc.value) == (
        "No local transport or cloud API available for parameter write."
    )


async def test_refresh_if_linked_calls_refresh_when_linked(real_coordinator):
    inv = MagicMock()
    inv.refresh = AsyncMock()
    real_coordinator.get_inverter_object = MagicMock(return_value=inv)
    real_coordinator.is_transport_link_down = MagicMock(return_value=False)
    await real_coordinator.refresh_inverter_params_if_linked("123")
    inv.refresh.assert_awaited_once_with(force=True, include_parameters=True)


async def test_refresh_if_linked_skips_when_link_down(real_coordinator):
    inv = MagicMock()
    inv.refresh = AsyncMock()
    real_coordinator.get_inverter_object = MagicMock(return_value=inv)
    real_coordinator.is_transport_link_down = MagicMock(return_value=True)
    await real_coordinator.refresh_inverter_params_if_linked("123")
    inv.refresh.assert_not_awaited()


async def test_refresh_if_linked_skips_when_no_inverter(real_coordinator):
    real_coordinator.get_inverter_object = MagicMock(return_value=None)
    real_coordinator.is_transport_link_down = MagicMock(return_value=False)
    await real_coordinator.refresh_inverter_params_if_linked("123")  # no raise


def test_params_local_raw_local_only_short_circuits(real_coordinator):
    real_coordinator.is_local_only = MagicMock(return_value=True)
    assert real_coordinator.params_are_local_raw("123") is True


def test_params_local_raw_include_configured_branch(real_coordinator):
    real_coordinator.is_local_only = MagicMock(return_value=False)
    real_coordinator.has_configured_local_transport = MagicMock(return_value=True)
    real_coordinator.get_inverter_object = MagicMock(
        return_value=MagicMock(transport=None)
    )
    # flag off -> falls through to live transport (None) -> False
    assert real_coordinator.params_are_local_raw("123") is False
    # flag on -> configured transport counts -> True
    assert real_coordinator.params_are_local_raw("123", include_configured=True) is True


def test_params_local_raw_live_transport_present(real_coordinator):
    real_coordinator.is_local_only = MagicMock(return_value=False)
    real_coordinator.has_configured_local_transport = MagicMock(return_value=False)
    real_coordinator.get_inverter_object = MagicMock(
        return_value=MagicMock(transport=object())
    )
    assert real_coordinator.params_are_local_raw("123") is True
