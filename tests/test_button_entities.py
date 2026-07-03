"""Unit tests for button entity logic without HA instance."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.eg4_web_monitor.button import (
    EG4RefreshButton,
    EG4BatteryRefreshButton,
    EG4StationRefreshButton,
)


class TestEG4RefreshButton:
    """Test EG4RefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                }
            }
        }
        coordinator.get_device_info.return_value = {
            "identifiers": {("eg4_web_monitor", "1234567890")},
            "name": "FlexBOSS21 1234567890",
            "model": "FlexBOSS21",
        }
        device_data = {"type": "inverter", "model": "FlexBOSS21"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        assert entity._serial == "1234567890"
        assert entity._model == "FlexBOSS21"
        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing button refreshes coordinator."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {"type": "inverter"}}}
        coordinator.get_device_info.return_value = {}
        coordinator.async_request_refresh = AsyncMock()

        # Mock inverter object with async refresh method
        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        device_data = {"type": "inverter"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        await entity.async_press()

        # Verify inverter refresh was called
        mock_inverter.refresh.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    def test_device_info(self):
        """Test device info is correctly set."""
        coordinator = MagicMock()
        coordinator.data = {"devices": {"1234567890": {}}}
        device_info = {
            "identifiers": {("eg4_web_monitor", "1234567890")},
            "name": "FlexBOSS21 1234567890",
            "model": "FlexBOSS21",
            "manufacturer": "EG4 Electronics",
        }
        coordinator.get_device_info.return_value = device_info
        device_data = {"type": "inverter"}

        entity = EG4RefreshButton(
            coordinator=coordinator,
            serial="1234567890",
            device_data=device_data,
            model="FlexBOSS21",
        )

        assert entity.device_info == device_info


class TestEG4BatteryRefreshButton:
    """Test EG4BatteryRefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {
                "1234567890": {"batteries": {"1234567890-01": {"state_of_charge": 85}}}
            }
        }

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
        )

        assert entity._parent_serial == "1234567890"
        assert entity._battery_key == "1234567890-01"
        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing battery refresh button."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"batteries": {"1234567890-01": {}}}}
        }
        coordinator.async_request_refresh = AsyncMock()

        # Mock inverter object with async refresh method
        mock_inverter = MagicMock()
        mock_inverter.refresh = AsyncMock()
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
        )

        await entity.async_press()

        # Verify parent inverter refresh was called (which refreshes batteries)
        mock_inverter.refresh.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    def test_unique_id(self):
        """Test unique ID includes battery key."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": {"1234567890": {"batteries": {"1234567890-01": {}}}}
        }

        entity = EG4BatteryRefreshButton(
            coordinator=coordinator,
            parent_serial="1234567890",
            battery_key="1234567890-01",
        )

        assert "1234567890" in entity.unique_id
        assert "1234567890-01" in entity.unique_id
        assert "refresh" in entity.unique_id.lower()


class TestEG4StationRefreshButton:
    """Test EG4StationRefreshButton entity logic."""

    def test_initialization(self):
        """Test entity initialization."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert "Refresh" in entity._attr_name

    @pytest.mark.asyncio
    async def test_async_press_refreshes_coordinator(self):
        """Test pressing station refresh button."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.async_request_refresh = AsyncMock()

        entity = EG4StationRefreshButton(coordinator=coordinator)

        await entity.async_press()

        coordinator.async_request_refresh.assert_called_once()

    def test_device_info(self):
        """Test station device info."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.get_station_device_info.return_value = {
            "identifiers": {("eg4_web_monitor", "station_12345")},
            "name": "Test Plant",
            "manufacturer": "EG4 Electronics",
        }

        entity = EG4StationRefreshButton(coordinator=coordinator)

        device_info = entity.device_info
        assert device_info is not None
        assert ("eg4_web_monitor", "station_12345") in device_info["identifiers"]
        assert "Test Plant" in device_info["name"]

    def test_unique_id(self):
        """Test station unique ID."""
        coordinator = MagicMock()
        coordinator.plant_id = "12345"

        entity = EG4StationRefreshButton(coordinator=coordinator)

        assert "12345" in entity.unique_id
        assert "refresh" in entity.unique_id.lower()


class TestLateBatteryButtonRegistration:
    """Late registration of per-battery refresh buttons (eg4-68y review)."""

    @staticmethod
    def _coordinator(batteries: dict | None = None) -> MagicMock:
        coordinator = MagicMock()
        coordinator.plant_id = "12345"
        coordinator.async_add_listener = MagicMock(return_value=lambda: None)
        coordinator.get_device_info.return_value = None
        coordinator.get_battery_device_info.return_value = None
        coordinator.data = {
            "devices": {
                "INV001": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "sensors": {},
                    "batteries": batteries or {},
                },
            },
        }
        return coordinator

    @pytest.mark.asyncio
    async def test_batteries_appearing_late_get_buttons(self):
        """Batteries discovered after setup get refresh buttons."""
        from custom_components.eg4_web_monitor.button import async_setup_entry

        coordinator = self._coordinator(batteries={})
        entry = MagicMock()
        entry.runtime_data = coordinator
        entry.async_on_unload = MagicMock()

        added: list = []

        def add_entities(entities, *args):
            added.extend(entities)

        await async_setup_entry(MagicMock(), entry, add_entities)
        # Setup created no battery buttons (LOCAL static first refresh has none)
        assert not any(isinstance(e, EG4BatteryRefreshButton) for e in added)

        battery_callback = next(
            call[0][0]
            for call in coordinator.async_add_listener.call_args_list
            if call[0][0].__name__ == "_async_discover_battery_buttons"
        )

        coordinator.data["devices"]["INV001"]["batteries"]["INV001-01"] = {
            "battery_real_voltage": 53.2,
        }

        added.clear()
        battery_callback()

        battery_buttons = [e for e in added if isinstance(e, EG4BatteryRefreshButton)]
        assert len(battery_buttons) == 1
        assert battery_buttons[0]._battery_key == "INV001-01"

        # No duplicates on a second fire
        added.clear()
        battery_callback()
        assert added == []

    @pytest.mark.asyncio
    async def test_setup_time_batteries_not_readded(self):
        """Batteries present at setup are seeded as known."""
        from custom_components.eg4_web_monitor.button import async_setup_entry

        coordinator = self._coordinator(
            batteries={"INV001-01": {"battery_real_voltage": 53.2}}
        )
        entry = MagicMock()
        entry.runtime_data = coordinator
        entry.async_on_unload = MagicMock()

        added: list = []

        def add_entities(entities, *args):
            added.extend(entities)

        await async_setup_entry(MagicMock(), entry, add_entities)
        setup_buttons = [e for e in added if isinstance(e, EG4BatteryRefreshButton)]
        assert len(setup_buttons) == 1

        battery_callback = next(
            call[0][0]
            for call in coordinator.async_add_listener.call_args_list
            if call[0][0].__name__ == "_async_discover_battery_buttons"
        )

        added.clear()
        battery_callback()
        assert added == []
