"""Tests for sensor platform — late battery entity registration."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import (
    EG4DataUpdateCoordinator,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    ALL_INVERTER_SENSOR_KEYS,
)
from custom_components.eg4_web_monitor.sensor import async_setup_entry


class TestLateBatteryRegistration:
    """Tests for dynamic battery entity discovery after static first refresh."""

    @pytest.fixture
    def local_config_entry(self):
        """Config entry for LOCAL connection type with one inverter."""
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
            entry_id="sensor_test_entry",
        )

    @pytest.fixture
    def mock_coordinator_static(self):
        """Coordinator with static data (no batteries yet)."""
        coord = MagicMock(spec=EG4DataUpdateCoordinator)
        coord.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "serial": "1234567890",
                    "firmware_version": "ARM-1.0",
                    "sensors": {k: None for k in ALL_INVERTER_SENSOR_KEYS},
                    "batteries": {},
                    "features": {},
                },
            },
            "parameters": {"1234567890": {}},
        }
        coord.last_update_success = True
        coord.config_entry = MagicMock()
        coord.plant_id = None
        coord.get_device_info = MagicMock(
            return_value={
                "identifiers": {(DOMAIN, "1234567890")},
                "name": "FlexBOSS21 1234567890",
                "manufacturer": "EG4 Electronics",
            }
        )
        coord.get_battery_bank_device_info = MagicMock(
            return_value={
                "identifiers": {(DOMAIN, "1234567890_battery_bank")},
                "name": "Battery Bank 1234567890",
                "manufacturer": "EG4 Electronics",
            }
        )
        coord.get_battery_device_info = MagicMock(
            return_value={
                "identifiers": {(DOMAIN, "battery_01")},
                "name": "Battery 01",
                "manufacturer": "EG4 Electronics",
            }
        )
        # Store registered listeners so we can invoke them
        coord._listeners: list = []

        def add_listener(callback):
            coord._listeners.append(callback)
            return lambda: coord._listeners.remove(callback)

        coord.async_add_listener = MagicMock(side_effect=add_listener)
        return coord

    async def test_batteries_added_after_second_refresh(
        self, hass, local_config_entry, mock_coordinator_static
    ):
        """Battery entities are registered when coordinator data adds batteries."""
        local_config_entry.add_to_hass(hass)
        local_config_entry.runtime_data = mock_coordinator_static
        mock_add_entities = MagicMock()

        # Set up entities — should create inverter sensors but no batteries
        await async_setup_entry(hass, local_config_entry, mock_add_entities)

        # Verify listeners registered (batteries + smart port sensors)
        assert mock_coordinator_static.async_add_listener.call_count == 2

        # Simulate second refresh: batteries appear
        battery_sensors = {
            "battery_rsoc": 95,
            "battery_real_voltage": 48.5,
        }
        mock_coordinator_static.data["devices"]["1234567890"]["batteries"] = {
            "1234567890-01": battery_sensors,
        }

        # Trigger the listener callback
        listener = mock_coordinator_static._listeners[0]
        listener()

        # async_add_entities should have been called again with new battery entities
        # First calls are phase1 and phase2 (phase2 is empty for static data)
        # The listener call adds the third invocation
        assert mock_add_entities.call_count >= 2  # Initial + late registration

        # Check the last call has battery entities
        last_call_entities = mock_add_entities.call_args_list[-1][0][0]
        assert len(last_call_entities) > 0

    async def test_no_duplicate_battery_entities(
        self, hass, local_config_entry, mock_coordinator_static
    ):
        """Existing batteries are not re-registered on coordinator updates."""
        local_config_entry.add_to_hass(hass)
        local_config_entry.runtime_data = mock_coordinator_static
        mock_add_entities = MagicMock()

        await async_setup_entry(hass, local_config_entry, mock_add_entities)

        # Simulate second refresh: batteries appear
        battery_sensors = {
            "battery_rsoc": 95,
            "battery_real_voltage": 48.5,
        }
        mock_coordinator_static.data["devices"]["1234567890"]["batteries"] = {
            "1234567890-01": battery_sensors,
        }

        listener = mock_coordinator_static._listeners[0]

        # First trigger: should register batteries
        listener()
        call_count_after_first = mock_add_entities.call_count

        # Second trigger with same batteries: should NOT register again
        listener()
        assert mock_add_entities.call_count == call_count_after_first
