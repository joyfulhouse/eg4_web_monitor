"""Tests for __init__.py (setup and teardown) in EG4 Web Monitor integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.entity_registry as er
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ServiceValidationError
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import (
    async_migrate_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    GRIDBOSS_STATIC_ENTITY_KEYS,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DOMAIN,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.entry_id = "test_entry_id"
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    coordinator.client = MagicMock()
    coordinator.client.close = AsyncMock()
    # Transports are None for HTTP-only connections
    coordinator._modbus_transport = None
    coordinator._dongle_transport = None
    # Add minimal data structure for platforms to work with
    coordinator.data = {
        "devices": {},
        "device_info": {},
        "parameters": {},
    }
    return coordinator


@pytest.fixture
def mock_config_entry(mock_coordinator):
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Electronics Web Monitor - Test Plant",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id="test_entry_id",
    )
    entry.runtime_data = mock_coordinator
    return entry


class TestAsyncSetup:
    """Test async_setup function."""

    async def test_setup_registers_service(self, hass: HomeAssistant):
        """Test that setup registers the refresh_data service."""
        result = await async_setup(hass, {})

        assert result is True
        assert hass.services.has_service(DOMAIN, "refresh_data")

    async def test_refresh_service_with_valid_entry_id(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test refresh service with valid entry_id."""
        # Ensure async methods are AsyncMock
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()

        # Setup integration
        await async_setup(hass, {})

        # Add config entry and set it up properly
        mock_config_entry.add_to_hass(hass)

        # Mock coordinator creation and prevent platform setup
        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=mock_coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            # Use HA's setup mechanism to properly manage entry state
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

        # Call service
        await hass.services.async_call(
            DOMAIN,
            "refresh_data",
            {"entry_id": "test_entry_id"},
            blocking=True,
        )

        # Verify coordinator was refreshed
        mock_coordinator.async_request_refresh.assert_called_once()

    async def test_refresh_service_with_invalid_entry_id(self, hass: HomeAssistant):
        """Test refresh service raises error for invalid entry_id."""
        await async_setup(hass, {})

        with pytest.raises(ServiceValidationError, match="not found"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": "non_existent_id"},
                blocking=True,
            )

    async def test_refresh_service_with_unloaded_entry(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test refresh service raises error for unloaded entry."""
        await async_setup(hass, {})

        # Add config entry but don't load it
        mock_config_entry.add_to_hass(hass)
        # State defaults to NOT_LOADED, no need to set it

        with pytest.raises(ServiceValidationError, match="not loaded"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {"entry_id": "test_entry_id"},
                blocking=True,
            )

    async def test_refresh_service_without_entry_id_refreshes_all(
        self, hass: HomeAssistant
    ):
        """Test refresh service without entry_id refreshes all coordinators."""
        await async_setup(hass, {})

        # Create multiple mock coordinators
        mock_coord1 = MagicMock()
        mock_coord1.entry = MagicMock()
        mock_coord1.entry.entry_id = "entry_1"
        mock_coord1.async_request_refresh = AsyncMock()
        mock_coord1.async_config_entry_first_refresh = AsyncMock()
        mock_coord1.data = {"devices": {}, "device_info": {}, "parameters": {}}
        mock_coord1.api = MagicMock()
        mock_coord1.api.close = AsyncMock()

        mock_coord2 = MagicMock()
        mock_coord2.entry = MagicMock()
        mock_coord2.entry.entry_id = "entry_2"
        mock_coord2.async_request_refresh = AsyncMock()
        mock_coord2.async_config_entry_first_refresh = AsyncMock()
        mock_coord2.data = {"devices": {}, "device_info": {}, "parameters": {}}
        mock_coord2.api = MagicMock()
        mock_coord2.api.close = AsyncMock()

        # Create config entries
        entry1 = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
                CONF_USERNAME: "user1",
                CONF_PASSWORD: "pass1",
                CONF_PLANT_ID: "1",
            },
            entry_id="entry_1",
        )
        entry1.add_to_hass(hass)

        entry2 = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
                CONF_USERNAME: "user2",
                CONF_PASSWORD: "pass2",
                CONF_PLANT_ID: "2",
            },
            entry_id="entry_2",
        )
        entry2.add_to_hass(hass)

        # Set up both entries using direct function calls to avoid state conflicts
        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                side_effect=[mock_coord1, mock_coord2],
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            # Directly call async_setup_entry for each entry
            assert await async_setup_entry(hass, entry1)
            object.__setattr__(entry1, "state", ConfigEntryState.LOADED)

            assert await async_setup_entry(hass, entry2)
            object.__setattr__(entry2, "state", ConfigEntryState.LOADED)

        # Call service without entry_id
        await hass.services.async_call(
            DOMAIN,
            "refresh_data",
            {},
            blocking=True,
        )

        # Verify both coordinators were refreshed
        mock_coord1.async_request_refresh.assert_called_once()
        mock_coord2.async_request_refresh.assert_called_once()

    async def test_refresh_service_with_no_coordinators(self, hass: HomeAssistant):
        """Test refresh service raises error when no coordinators exist."""
        await async_setup(hass, {})

        with pytest.raises(ServiceValidationError, match="No EG4 coordinators"):
            await hass.services.async_call(
                DOMAIN,
                "refresh_data",
                {},
                blocking=True,
            )


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_success(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test successful setup of config entry."""
        mock_config_entry.add_to_hass(hass)

        # Mock coordinator
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        # Mock platform setup
        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward:
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            mock_coordinator.async_config_entry_first_refresh.assert_called_once()
            assert mock_config_entry.runtime_data == mock_coordinator
            # Called twice: sensor platform first, then remaining platforms
            assert mock_forward.call_count == 2

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_creates_coordinator_with_correct_params(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test that coordinator is created with correct parameters."""
        mock_config_entry.add_to_hass(hass)

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ):
            await async_setup_entry(hass, mock_config_entry)

            # Verify coordinator was created with correct params
            mock_coordinator_class.assert_called_once_with(hass, mock_config_entry)

    @patch("custom_components.eg4_web_monitor.EG4DataUpdateCoordinator")
    async def test_setup_entry_forwards_to_all_platforms(
        self, mock_coordinator_class, hass: HomeAssistant, mock_config_entry
    ):
        """Test that entry setup is forwarded to all platforms."""
        mock_config_entry.add_to_hass(hass)

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_class.return_value = mock_coordinator

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward:
            await async_setup_entry(hass, mock_config_entry)

            # Verify all platforms were forwarded across both calls
            all_platforms = []
            for call in mock_forward.call_args_list:
                all_platforms.extend(p.value for p in call[0][1])
            assert "sensor" in all_platforms
            assert "number" in all_platforms
            assert "switch" in all_platforms
            assert "button" in all_platforms
            assert "select" in all_platforms


class TestSmartPortCleanupOnReboot:
    """Regression tests for #217: smart-port registry cleanup across restarts.

    The LOCAL-mode first refresh returns static placeholder data without
    smart-port keys.  The setup-time cleanup must NOT treat that as
    authoritative — doing so deleted every smart-port registry entry on each
    reboot and re-created them moments later under NEW registry entry IDs,
    permanently breaking automations pinned to the old entry ID.
    """

    GRIDBOSS_SERIAL = "4434850364"
    # Keys an automation may be pinned to (port 1 = active smart load)
    ACTIVE_KEYS = ("smart_load1_power_l1", "smart_load1_power", "smart_load_power")
    # Key for a port that is genuinely inactive (stale, should be cleaned)
    STALE_KEY = "ac_couple2_power_l1"
    # Non-smart-port GridBOSS sensor (must never be touched)
    PLAIN_KEY = "grid_power"

    def _seed_registry(self, hass, entry):
        """Pre-create registry entries as they exist after a previous session."""
        registry = er.async_get(hass)
        entries = {}
        for key in (*self.ACTIVE_KEYS, self.STALE_KEY, self.PLAIN_KEY):
            entries[key] = registry.async_get_or_create(
                "sensor",
                DOMAIN,
                f"{self.GRIDBOSS_SERIAL}_{key}",
                config_entry=entry,
            )
        return entries

    def _static_data(self):
        """Coordinator data as returned by the LOCAL static first refresh."""
        return {
            "devices": {
                self.GRIDBOSS_SERIAL: {
                    "type": "gridboss",
                    "serial": self.GRIDBOSS_SERIAL,
                    "model": "GridBOSS",
                    "sensors": {k: None for k in GRIDBOSS_STATIC_ENTITY_KEYS},
                    "binary_sensors": {},
                }
            },
            "device_info": {},
            "parameters": {},
        }

    def _authoritative_data(self):
        """Coordinator data after a real poll (port 1 active, others unused)."""
        sensors: dict = {k: None for k in GRIDBOSS_STATIC_ENTITY_KEYS}
        sensors.update(
            {
                "smart_port1_status": "smart_load",
                "smart_port2_status": "unused",
                "smart_port3_status": "unused",
                "smart_port4_status": "unused",
                "smart_load1_power_l1": 120.0,
                "smart_load1_power_l2": 80.0,
                "smart_load1_power": 200.0,
                "smart_load_power": 200.0,
                "grid_power": 1500.0,
            }
        )
        return {
            "devices": {
                self.GRIDBOSS_SERIAL: {
                    "type": "gridboss",
                    "serial": self.GRIDBOSS_SERIAL,
                    "model": "GridBOSS",
                    "sensors": sensors,
                    "binary_sensors": {},
                }
            },
            "device_info": {},
            "parameters": {},
        }

    async def _setup_with_data(self, hass, entry, data):
        """Run async_setup_entry with a mock coordinator holding given data."""
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.data = data
        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=mock_coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            assert await async_setup_entry(hass, entry)
        return mock_coordinator

    async def test_static_first_refresh_preserves_registry_entries(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Static (non-authoritative) data must not remove any registry entry."""
        mock_config_entry.add_to_hass(hass)
        seeded = self._seed_registry(hass, mock_config_entry)

        coordinator = await self._setup_with_data(
            hass, mock_config_entry, self._static_data()
        )

        registry = er.async_get(hass)
        for key, entry in seeded.items():
            current = registry.async_get(entry.entity_id)
            assert current is not None, f"{key} was removed during static setup"
            # Same registry entry ID => automations pinned to it stay valid
            assert current.id == entry.id

        # Cleanup deferred: exactly one coordinator listener registered
        coordinator.async_add_listener.assert_called_once()

    async def test_deferred_cleanup_preserves_active_and_removes_stale(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """When real data arrives, stale keys go but active entries keep their ID."""
        mock_config_entry.add_to_hass(hass)
        seeded = self._seed_registry(hass, mock_config_entry)

        coordinator = await self._setup_with_data(
            hass, mock_config_entry, self._static_data()
        )
        deferred_cleanup = coordinator.async_add_listener.call_args[0][0]
        unsub = coordinator.async_add_listener.return_value

        # First real poll lands: port 1 active, port 2 unused
        coordinator.data = self._authoritative_data()
        deferred_cleanup()

        registry = er.async_get(hass)
        for key in self.ACTIVE_KEYS:
            current = registry.async_get(seeded[key].entity_id)
            assert current is not None, f"active key {key} was removed"
            assert current.id == seeded[key].id, f"registry ID churned for {key}"
        assert registry.async_get(seeded[self.PLAIN_KEY].entity_id) is not None
        assert registry.async_get(seeded[self.STALE_KEY].entity_id) is None

        # Listener unsubscribed after authoritative cleanup; re-firing is a no-op
        unsub.assert_called_once()
        deferred_cleanup()
        unsub.assert_called_once()

    async def test_deferred_cleanup_waits_while_data_stays_static(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """An offline GridBOSS (no real poll yet) must defer cleanup forever."""
        mock_config_entry.add_to_hass(hass)
        seeded = self._seed_registry(hass, mock_config_entry)

        coordinator = await self._setup_with_data(
            hass, mock_config_entry, self._static_data()
        )
        deferred_cleanup = coordinator.async_add_listener.call_args[0][0]
        unsub = coordinator.async_add_listener.return_value

        # Coordinator updates but the GridBOSS data is still the static shape
        deferred_cleanup()
        deferred_cleanup()

        registry = er.async_get(hass)
        for key, entry in seeded.items():
            assert registry.async_get(entry.entity_id) is not None, f"{key} removed"
        unsub.assert_not_called()

    async def test_authoritative_first_refresh_cleans_immediately(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Cloud-style real first refresh cleans stale keys without a listener."""
        mock_config_entry.add_to_hass(hass)
        seeded = self._seed_registry(hass, mock_config_entry)

        coordinator = await self._setup_with_data(
            hass, mock_config_entry, self._authoritative_data()
        )

        registry = er.async_get(hass)
        for key in self.ACTIVE_KEYS:
            current = registry.async_get(seeded[key].entity_id)
            assert current is not None, f"active key {key} was removed"
            assert current.id == seeded[key].id
        assert registry.async_get(seeded[self.PLAIN_KEY].entity_id) is not None
        assert registry.async_get(seeded[self.STALE_KEY].entity_id) is None

        # No pending GridBOSS serials => no deferred-cleanup listener
        coordinator.async_add_listener.assert_not_called()


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    async def test_unload_entry_success(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test successful unload of config entry."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ) as mock_unload:
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is True
            mock_unload.assert_called_once()
            mock_coordinator.async_shutdown.assert_called_once()
            mock_coordinator.client.close.assert_called_once()

    async def test_unload_entry_failure(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test failed unload of config entry."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=False),
        ) as mock_unload:
            result = await async_unload_entry(hass, mock_config_entry)

            assert result is False
            mock_unload.assert_called_once()
            # Client should not be closed if unload failed
            mock_coordinator.client.close.assert_not_called()

    async def test_unload_entry_cleans_up_api(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test that client connection is closed on unload."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            await async_unload_entry(hass, mock_config_entry)

            # Verify client close was called
            mock_coordinator.client.close.assert_called_once()

    async def test_unload_entry_unloads_all_platforms(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test that all platforms are unloaded."""
        mock_config_entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ) as mock_unload:
            await async_unload_entry(hass, mock_config_entry)

            # Verify all platforms were unloaded
            call_args = mock_unload.call_args
            platforms = call_args[0][1]
            assert "sensor" in [p.value for p in platforms]
            assert "number" in [p.value for p in platforms]
            assert "switch" in [p.value for p in platforms]
            assert "button" in [p.value for p in platforms]
            assert "select" in [p.value for p in platforms]


class TestAsyncMigrateEntry:
    """Test async_migrate_entry function."""

    async def test_migrate_v1_modbus_to_v2(self, hass: HomeAssistant):
        """Test migration of version 1 modbus entry to version 2."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            data={
                "connection_type": "modbus",
                "inverter_serial": "1234567890",
                "inverter_family": "EG4_HYBRID",
                "modbus_host": "192.168.1.100",
                "modbus_port": 502,
                "modbus_unit_id": 1,
            },
            entry_id="test_modbus_entry",
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2
        assert entry.data["connection_type"] == "local"
        assert "local_transports" in entry.data
        assert len(entry.data["local_transports"]) == 1

        transport = entry.data["local_transports"][0]
        assert transport["transport_type"] == "modbus_tcp"
        assert transport["serial"] == "1234567890"
        assert transport["host"] == "192.168.1.100"

    async def test_migrate_v1_dongle_to_v2(self, hass: HomeAssistant):
        """Test migration of version 1 dongle entry to version 2."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            data={
                "connection_type": "dongle",
                "inverter_serial": "9876543210",
                "inverter_family": "LXP",
                "dongle_host": "192.168.1.200",
                "dongle_port": 8000,
                "dongle_serial": "DONGLE123",
            },
            entry_id="test_dongle_entry",
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2
        assert entry.data["connection_type"] == "local"
        assert "local_transports" in entry.data

        transport = entry.data["local_transports"][0]
        assert transport["transport_type"] == "wifi_dongle"
        assert transport["serial"] == "9876543210"
        assert transport["host"] == "192.168.1.200"
        assert transport["dongle_serial"] == "DONGLE123"

    async def test_migrate_v1_http_unchanged(self, hass: HomeAssistant):
        """Test migration of version 1 HTTP entry (should be unchanged but version updated)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            data={
                "connection_type": "http",
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "secret",
                CONF_PLANT_ID: "12345",
            },
            entry_id="test_http_entry",
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2
        # HTTP entry data should be unchanged
        assert entry.data["connection_type"] == "http"
        assert entry.data[CONF_USERNAME] == "user@example.com"
        assert entry.data[CONF_PLANT_ID] == "12345"

    async def test_migrate_v2_no_change(self, hass: HomeAssistant):
        """Test that version 2 entries are not modified."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={
                "connection_type": "local",
                "local_transports": [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "host": "192.168.1.100",
                    }
                ],
            },
            entry_id="test_v2_entry",
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2

    async def test_migrate_future_version_fails(self, hass: HomeAssistant):
        """Test that migration from future version fails."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=99,
            data={"connection_type": "http"},
            entry_id="test_future_entry",
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is False
