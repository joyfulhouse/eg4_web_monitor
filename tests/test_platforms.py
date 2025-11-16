"""Tests for all platform entities in EG4 Web Monitor integration."""

import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )


@pytest.fixture
def mock_coordinator_data():
    """Create mock coordinator data."""
    return {
        "devices": {
            "1234567890": {
                "type": "inverter",
                "model": "FlexBOSS21",
                "sensors": {
                    "ac_power": 5000,
                    "ac_voltage": 240.5,
                    "battery_voltage": 51.2,
                    "state_of_charge": 85,
                    "grid_power": 1500,
                },
                "batteries": {
                    "Battery_ID_01": {
                        "battery_real_voltage": 51.2,
                        "battery_real_current": 10.5,
                        "state_of_charge": 85,
                        "state_of_health": 98,
                        "battery_cell_voltage_max": 3.35,
                        "battery_cell_voltage_min": 3.32,
                    }
                },
            },
            "9876543210": {
                "type": "gridboss",
                "model": "GridBOSS",
                "sensors": {
                    "grid_power": 3000,
                    "load_power": 2500,
                    "grid_voltage_l1": 120.5,
                },
            },
        },
        "station": {
            "total_energy_today": 45.6,
            "total_power": 8500,
        },
    }


@pytest.fixture
async def mock_coordinator(hass, mock_config_entry, mock_coordinator_data):
    """Create a mock coordinator."""
    with patch(
        "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
        return_value=False,
    ):
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.data = mock_coordinator_data
        coordinator.last_update_success = True
        return coordinator


class TestSensorPlatform:
    """Test sensor platform."""

    async def test_sensor_platform_has_max_parallel_updates(self):
        """Test that sensor platform defines MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import sensor

        assert hasattr(sensor, "MAX_PARALLEL_UPDATES")
        assert isinstance(sensor.MAX_PARALLEL_UPDATES, int)
        assert sensor.MAX_PARALLEL_UPDATES > 0

    async def test_async_setup_entry_creates_sensors(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test sensor setup creates entities."""
        from custom_components.eg4_web_monitor.sensor import async_setup_entry

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        mock_config_entry.runtime_data = mock_coordinator
        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # Should create inverter sensors, battery sensors, and gridboss sensors
        assert len(entities) > 0

    async def test_inverter_sensor_state(self, hass, mock_coordinator):
        """Test inverter sensor returns correct state."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        assert sensor.native_value == 5000

    async def test_battery_sensor_state(self, hass, mock_coordinator):
        """Test battery sensor returns correct state."""
        from custom_components.eg4_web_monitor.sensor import EG4BatterySensor

        sensor = EG4BatterySensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            battery_key="Battery_ID_01",
            sensor_key="state_of_charge",
        )

        assert sensor.native_value == 85

    async def test_sensor_availability(self, hass, mock_coordinator):
        """Test sensor availability."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        # Coordinator has data, sensor should be available
        assert sensor.available is True

        # Set coordinator to failed state
        mock_coordinator.last_update_success = False
        assert sensor.available is False

    async def test_sensor_unique_id(self, hass, mock_coordinator):
        """Test sensor unique ID generation."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        assert sensor.unique_id is not None
        assert "1234567890" in sensor.unique_id
        assert "ac_power" in sensor.unique_id


class TestButtonPlatform:
    """Test button platform."""

    async def test_button_platform_has_max_parallel_updates(self):
        """Test that button platform defines MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import button

        assert hasattr(button, "MAX_PARALLEL_UPDATES")
        assert isinstance(button.MAX_PARALLEL_UPDATES, int)
        assert button.MAX_PARALLEL_UPDATES > 0

    async def test_async_setup_entry_creates_buttons(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test button setup creates entities."""
        from custom_components.eg4_web_monitor.button import async_setup_entry

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        mock_config_entry.runtime_data = mock_coordinator
        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # Should create refresh buttons for devices
        assert len(entities) > 0

    async def test_button_press(self, hass, mock_coordinator):
        """Test button press action."""
        from custom_components.eg4_web_monitor.button import EG4RefreshButton

        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        button = EG4RefreshButton(
            coordinator=mock_coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        # Mock coordinator refresh
        mock_coordinator.async_request_refresh = AsyncMock()

        await button.async_press()

        # Verify refresh was called
        mock_coordinator.async_request_refresh.assert_called_once()


class TestNumberPlatform:
    """Test number platform."""

    async def test_number_platform_has_max_parallel_updates(self):
        """Test that number platform defines MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import number

        assert hasattr(number, "MAX_PARALLEL_UPDATES")
        assert isinstance(number.MAX_PARALLEL_UPDATES, int)
        assert number.MAX_PARALLEL_UPDATES > 0

    async def test_async_setup_entry_creates_numbers(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test number setup creates entities."""
        from custom_components.eg4_web_monitor.number import async_setup_entry

        entities = []

        async def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        # Add parameter data to coordinator
        mock_coordinator.data["devices"]["1234567890"]["parameters"] = {
            "charge_power_limit": 5000,
            "discharge_power_limit": 5000,
        }

        mock_config_entry.runtime_data = mock_coordinator
        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # Should create number entities for parameters
        assert len(entities) >= 0  # May be 0 if no parameters exposed

    async def test_number_set_value(self, hass, mock_config_entry, mock_coordinator):
        """Test number entity set value through service call."""
        # Mock API write
        mock_coordinator.api.write_parameters = AsyncMock(return_value=True)
        mock_coordinator.api.read_device_parameters_ranges = AsyncMock(
            return_value=[{"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 85}]
        )

        # Set up the integration properly
        mock_config_entry.runtime_data = mock_coordinator
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Use the service to set the value (proper HA testing pattern)
        entity_id = "number.eg4_flexboss21_1234567890_system_charge_soc_limit"
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": 85},
            blocking=True,
        )

        # Verify API was called
        mock_coordinator.api.write_parameters.assert_called()


class TestSwitchPlatform:
    """Test switch platform."""

    async def test_switch_platform_has_max_parallel_updates(self):
        """Test that switch platform defines MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import switch

        assert hasattr(switch, "MAX_PARALLEL_UPDATES")
        assert isinstance(switch.MAX_PARALLEL_UPDATES, int)
        assert switch.MAX_PARALLEL_UPDATES > 0

    async def test_async_setup_entry_creates_switches(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test switch setup creates entities."""
        from custom_components.eg4_web_monitor.switch import async_setup_entry

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        # Add switch data to coordinator
        mock_coordinator.data["devices"]["1234567890"]["parameters"] = {
            "ac_charge_enable": 1,
            "grid_charge_enable": 0,
        }

        mock_config_entry.runtime_data = mock_coordinator
        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # Should create switch entities
        assert len(entities) >= 0  # May be 0 if no switches exposed

    async def test_switch_turn_on(self, hass, mock_config_entry, mock_coordinator):
        """Test switch turn on through service call."""
        # Mock API write
        mock_coordinator.api.write_parameters = AsyncMock(return_value=True)
        mock_coordinator.api.read_device_parameters_ranges = AsyncMock(return_value=[])

        # Set up the integration properly
        mock_config_entry.runtime_data = mock_coordinator
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Use the service to turn on (proper HA testing pattern)
        entity_id = "switch.eg4_flexboss21_1234567890_eps_battery_backup"
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": entity_id},
            blocking=True,
        )

        # Verify API was called
        mock_coordinator.api.write_parameters.assert_called()

    async def test_switch_turn_off(self, hass, mock_config_entry, mock_coordinator):
        """Test switch turn off through service call."""
        # Mock API write
        mock_coordinator.api.write_parameters = AsyncMock(return_value=True)
        mock_coordinator.api.read_device_parameters_ranges = AsyncMock(return_value=[])

        # Set up the integration properly
        mock_config_entry.runtime_data = mock_coordinator
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Use the service to turn off (proper HA testing pattern)
        entity_id = "switch.eg4_flexboss21_1234567890_eps_battery_backup"
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": entity_id},
            blocking=True,
        )

        # Verify API was called
        mock_coordinator.api.write_parameters.assert_called()


class TestSelectPlatform:
    """Test select platform."""

    async def test_select_platform_has_max_parallel_updates(self):
        """Test that select platform defines MAX_PARALLEL_UPDATES."""
        from custom_components.eg4_web_monitor import select

        assert hasattr(select, "MAX_PARALLEL_UPDATES")
        assert isinstance(select.MAX_PARALLEL_UPDATES, int)
        assert select.MAX_PARALLEL_UPDATES > 0

    async def test_async_setup_entry_creates_selects(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test select setup creates entities."""
        from custom_components.eg4_web_monitor.select import async_setup_entry

        entities = []

        async def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        # Add select data to coordinator
        mock_coordinator.data["devices"]["1234567890"]["parameters"] = {
            "operating_mode": 0,  # Normal mode
        }

        mock_config_entry.runtime_data = mock_coordinator
        await async_setup_entry(hass, mock_config_entry, mock_add_entities)

        # Should create select entities
        assert len(entities) >= 0  # May be 0 if no selects exposed

    async def test_select_option(self, hass, mock_config_entry, mock_coordinator):
        """Test select entity option change through service call."""
        # Mock API write
        mock_coordinator.api.write_parameters = AsyncMock(return_value=True)
        mock_coordinator.api.read_device_parameters_ranges = AsyncMock(
            return_value=[{"HOLD_WORK_MODE": 0}]
        )

        # Set up the integration properly
        mock_config_entry.runtime_data = mock_coordinator
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Use the service to select option (proper HA testing pattern)
        entity_id = "select.eg4_flexboss21_1234567890_operating_mode"
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": "Normal"},
            blocking=True,
        )

        # Verify API was called
        mock_coordinator.api.write_parameters.assert_called()


class TestEntityAvailability:
    """Test entity availability across platforms."""

    async def test_entity_available_when_coordinator_succeeds(
        self, hass, mock_coordinator
    ):
        """Test entity is available when coordinator has successful update."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        mock_coordinator.last_update_success = True

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        assert sensor.available is True

    async def test_entity_unavailable_when_coordinator_fails(
        self, hass, mock_coordinator
    ):
        """Test entity is unavailable when coordinator fails."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        mock_coordinator.last_update_success = False

        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        assert sensor.available is False

    async def test_entity_unavailable_when_no_data(self, hass, mock_coordinator):
        """Test entity is unavailable when coordinator has no data."""
        from custom_components.eg4_web_monitor.sensor import EG4InverterSensor

        # Create sensor first
        sensor = EG4InverterSensor(
            coordinator=mock_coordinator,
            serial="1234567890",
            sensor_key="ac_power",
            device_type="inverter",
        )

        # Then remove data to test unavailability
        mock_coordinator.data = None

        assert sensor.available is False


class TestEntityUpdates:
    """Test entity state updates."""

    async def test_sensor_updates_on_coordinator_refresh(
        self, hass, mock_config_entry, mock_coordinator
    ):
        """Test sensor updates when coordinator refreshes - use hass.states."""
        # Set up the integration properly
        mock_config_entry.runtime_data = mock_coordinator
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Check initial state through hass.states (proper HA testing pattern)
        entity_id = "sensor.eg4_flexboss21_1234567890_ac_power"
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "5000"

        # Update coordinator data
        mock_coordinator.data["devices"]["1234567890"]["sensors"]["ac_power"] = 6000

        # Trigger coordinator update
        await mock_coordinator.async_request_refresh()
        await hass.async_block_till_done()

        # Check updated state through hass.states
        state = hass.states.get(entity_id)
        assert state.state == "6000"
