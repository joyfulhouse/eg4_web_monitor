"""Tests for sensor platform — late battery and device entity registration."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    SENSOR_TYPES,
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

        # Verify listeners registered (batteries + smart ports + device sensors)
        assert mock_coordinator_static.async_add_listener.call_count == 3

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


class TestLateDeviceSensorRegistration:
    """Tests for dynamic device sensor discovery in HYBRID mode.

    In HYBRID mode, the first coordinator update has _transport_runtime=None,
    so transport-only sensor keys (per-leg power, overlay sensors) are missing.
    The late registration listener picks these up on subsequent updates.
    """

    # Minimal set of HTTP-only sensor keys (present from first poll)
    HTTP_SENSOR_KEYS = {
        "pv_total_power",
        "pv1_power",
        "pv2_power",
        "battery_power",
        "state_of_charge",
        "consumption_power",
        "output_power",
        "ac_power",
        "eps_power",
        "grid_voltage_r",
        "grid_frequency",
        "internal_temperature",
        "yield",
        "yield_lifetime",
        "grid_import",
        "grid_export",
    }

    # Transport-only sensor keys (appear after local transport attached)
    TRANSPORT_ONLY_KEYS = {
        "inverter_power_l1",
        "inverter_power_l2",
        "rectifier_power_l1",
        "rectifier_power_l2",
        "grid_export_power_l1",
        "grid_export_power_l2",
        "grid_import_power_l1",
        "grid_import_power_l2",
        "bt_temperature",
        "battery_current",
        "total_load_power",
    }

    @pytest.fixture
    def hybrid_config_entry(self):
        """Config entry for HYBRID connection type."""
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 Electronics - Test Plant",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
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
            entry_id="hybrid_sensor_test",
        )

    @pytest.fixture
    def mock_coordinator_http_only(self):
        """Coordinator with HTTP-only data (no transport sensors yet)."""
        coord = MagicMock(spec=EG4DataUpdateCoordinator)
        # Initial data: only HTTP-available sensor keys
        coord.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "serial": "1234567890",
                    "firmware_version": "ARM-1.0",
                    "sensors": {k: 0 for k in self.HTTP_SENSOR_KEYS},
                    "batteries": {},
                    "features": {
                        "supports_split_phase": True,
                        "supports_three_phase": False,
                    },
                },
            },
            "parameters": {"1234567890": {}},
        }
        coord.last_update_success = True
        coord.config_entry = MagicMock()
        coord.plant_id = "12345"
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
        coord._listeners: list = []

        def add_listener(callback):
            coord._listeners.append(callback)
            return lambda: coord._listeners.remove(callback)

        coord.async_add_listener = MagicMock(side_effect=add_listener)
        return coord

    async def test_transport_sensors_registered_after_second_update(
        self, hass, hybrid_config_entry, mock_coordinator_http_only
    ):
        """Transport-only sensors are registered when they appear in data."""
        hybrid_config_entry.add_to_hass(hass)
        hybrid_config_entry.runtime_data = mock_coordinator_http_only
        mock_add_entities = MagicMock()

        await async_setup_entry(hass, hybrid_config_entry, mock_add_entities)

        initial_call_count = mock_add_entities.call_count

        # Simulate second update: transport sensors appear
        device_sensors = mock_coordinator_http_only.data["devices"]["1234567890"][
            "sensors"
        ]
        for key in self.TRANSPORT_ONLY_KEYS:
            device_sensors[key] = 0

        # Trigger the device sensor listener (third listener: index 2)
        device_listener = mock_coordinator_http_only._listeners[2]
        device_listener()

        # New entities should have been registered
        assert mock_add_entities.call_count > initial_call_count

        # Check the new entities are transport-only sensors
        last_call_entities = mock_add_entities.call_args_list[-1][0][0]
        new_keys = {e._sensor_key for e in last_call_entities}
        # All transport-only keys that are also in SENSOR_TYPES should be registered
        expected = {k for k in self.TRANSPORT_ONLY_KEYS if k in SENSOR_TYPES}
        assert new_keys == expected

    async def test_no_duplicate_device_sensor_registration(
        self, hass, hybrid_config_entry, mock_coordinator_http_only
    ):
        """Device sensors are not re-registered on repeated updates."""
        hybrid_config_entry.add_to_hass(hass)
        hybrid_config_entry.runtime_data = mock_coordinator_http_only
        mock_add_entities = MagicMock()

        await async_setup_entry(hass, hybrid_config_entry, mock_add_entities)

        # Add transport sensors
        device_sensors = mock_coordinator_http_only.data["devices"]["1234567890"][
            "sensors"
        ]
        for key in self.TRANSPORT_ONLY_KEYS:
            device_sensors[key] = 0

        device_listener = mock_coordinator_http_only._listeners[2]

        # First trigger: should register new sensors
        device_listener()
        count_after_first = mock_add_entities.call_count

        # Second trigger with same sensors: should NOT register again
        device_listener()
        assert mock_add_entities.call_count == count_after_first

    async def test_feature_filtering_on_late_registration(
        self, hass, hybrid_config_entry, mock_coordinator_http_only
    ):
        """Late-registered sensors respect feature-based filtering."""
        hybrid_config_entry.add_to_hass(hass)
        hybrid_config_entry.runtime_data = mock_coordinator_http_only
        mock_add_entities = MagicMock()

        await async_setup_entry(hass, hybrid_config_entry, mock_add_entities)

        # Add a three-phase-only sensor to split-phase device
        # (features say supports_three_phase=False)
        device_sensors = mock_coordinator_http_only.data["devices"]["1234567890"][
            "sensors"
        ]
        device_sensors["grid_voltage_t"] = 0  # Three-phase only

        device_listener = mock_coordinator_http_only._listeners[2]
        device_listener()

        # grid_voltage_t should NOT be registered (split-phase device)
        if mock_add_entities.call_count > 2:
            last_entities = mock_add_entities.call_args_list[-1][0][0]
            registered_keys = {e._sensor_key for e in last_entities}
            assert "grid_voltage_t" not in registered_keys
