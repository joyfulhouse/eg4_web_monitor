"""Tests for EG4 firmware update entities."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import ENTITY_PREFIX
from custom_components.eg4_web_monitor.update import (
    async_setup_entry,
    EG4FirmwareUpdateEntity,
)


# -- Helpers ------------------------------------------------------------------


def _mock_coordinator(
    *,
    devices=None,
    last_update_success=True,
):
    """Build a mock EG4DataUpdateCoordinator for update entity tests.

    Args:
        devices: dict mapping serial -> device_data dicts.  When None the
            coordinator has valid data with an empty devices dict.
        last_update_success: value for coordinator.last_update_success.
    """
    coordinator = MagicMock()
    coordinator.last_update_success = last_update_success
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.get_device_info = MagicMock(return_value=None)

    if devices is not None:
        coordinator.data = {"devices": devices}
    else:
        coordinator.data = {"devices": {}}

    # _get_device_object default: returns a mock device whose orchestrated
    # update converges in one step (issue #353 result contract).
    mock_device = MagicMock()
    mock_device.start_firmware_update = AsyncMock()
    mock_device.run_firmware_update_to_completion = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            converged=True,
            steps_run=1,
            message="Firmware update complete after 1 step(s)",
            final_version="ccaa-1E1515",
        )
    )
    coordinator._get_device_object = MagicMock(return_value=mock_device)

    return coordinator


# -- async_setup_entry --------------------------------------------------------


class TestAsyncSetupEntry:
    """Test the update platform setup entry function."""

    @pytest.mark.asyncio
    async def test_no_data_creates_no_entities(self, hass):
        """When coordinator.data is None, no entities are created."""
        coordinator = _mock_coordinator()
        coordinator.data = None
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities == []

    @pytest.mark.asyncio
    async def test_no_devices_key_creates_no_entities(self, hass):
        """When coordinator.data has no 'devices' key, no entities are created."""
        coordinator = _mock_coordinator()
        coordinator.data = {"some_other_key": {}}
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities == []

    @pytest.mark.asyncio
    async def test_creates_entity_for_inverter(self, hass):
        """An inverter device should produce one firmware update entity."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 1
        assert isinstance(entities[0], EG4FirmwareUpdateEntity)

    @pytest.mark.asyncio
    async def test_creates_entity_for_gridboss(self, hass):
        """A gridboss device should produce one firmware update entity."""
        coordinator = _mock_coordinator(
            devices={"GB0001": {"type": "gridboss", "model": "GridBOSS"}}
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 1
        assert isinstance(entities[0], EG4FirmwareUpdateEntity)

    @pytest.mark.asyncio
    async def test_skips_parallel_group_and_unknown(self, hass):
        """parallel_group and unknown device types produce no entities."""
        coordinator = _mock_coordinator(
            devices={
                "PG001": {"type": "parallel_group", "model": "Group1"},
                "UNK01": {"type": "mystery_device", "model": "Foo"},
            }
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities == []

    @pytest.mark.asyncio
    async def test_mixed_device_types(self, hass):
        """Only inverter and gridboss devices produce update entities."""
        coordinator = _mock_coordinator(
            devices={
                "INV001": {"type": "inverter", "model": "FlexBOSS21"},
                "GB001": {"type": "gridboss", "model": "GridBOSS"},
                "PG001": {"type": "parallel_group", "model": "Group1"},
            }
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 2
        serials = {e._serial for e in entities}
        assert serials == {"INV001", "GB001"}


# -- EG4FirmwareUpdateEntity.__init__ ----------------------------------------


class TestEntityInit:
    """Test entity initialization and attribute assignment."""

    def test_unique_id_format(self):
        """Unique ID should be '{serial}_firmware_update'."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "1234567890")
        assert entity._attr_unique_id == "1234567890_firmware_update"

    def test_entity_id_inverter(self):
        """Inverter entity ID: update.{PREFIX}_{model_clean}_{serial}_firmware."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "1234567890")
        expected = f"update.{ENTITY_PREFIX}_flexboss21_1234567890_firmware"
        assert entity._attr_entity_id == expected

    def test_entity_id_inverter_with_spaces_and_hyphens(self):
        """Model with spaces/hyphens normalises to underscores, lowercase."""
        coordinator = _mock_coordinator(
            devices={"9999999999": {"type": "inverter", "model": "18kPV Hybrid-Pro"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "9999999999")
        expected = f"update.{ENTITY_PREFIX}_18kpv_hybrid_pro_9999999999_firmware"
        assert entity._attr_entity_id == expected

    def test_entity_id_gridboss(self):
        """GridBOSS entity ID: update.{PREFIX}_gridboss_{serial}_firmware."""
        coordinator = _mock_coordinator(
            devices={"GB0001": {"type": "gridboss", "model": "GridBOSS"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "GB0001")
        expected = f"update.{ENTITY_PREFIX}_gridboss_GB0001_firmware"
        assert entity._attr_entity_id == expected

    def test_name_is_firmware(self):
        """Name attribute should always be 'Firmware'."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "1234567890")
        assert entity._attr_name == "Firmware"

    def test_entity_category_diagnostic(self):
        """Entity category should be DIAGNOSTIC."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "1234567890")
        assert entity._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_supported_features(self):
        """Supported features include INSTALL and PROGRESS."""
        coordinator = _mock_coordinator(
            devices={"1234567890": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "1234567890")
        assert entity._attr_supported_features & UpdateEntityFeature.INSTALL
        assert entity._attr_supported_features & UpdateEntityFeature.PROGRESS


# -- Properties ---------------------------------------------------------------


class TestProperties:
    """Test the entity property accessors."""

    def test_installed_version_present(self):
        """installed_version returns firmware_version from device data."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {"type": "inverter", "model": "X", "firmware_version": "1.2.3"}
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.installed_version == "1.2.3"

    def test_installed_version_missing(self):
        """installed_version returns None when firmware_version is absent."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.installed_version is None

    def test_installed_version_no_device_data(self):
        """installed_version returns None when device is missing from data."""
        coordinator = _mock_coordinator(devices={})
        entity = EG4FirmwareUpdateEntity(coordinator, "SN_MISSING")
        assert entity.installed_version is None

    def test_latest_version_from_update_info(self):
        """latest_version prefers firmware_update_info.latest_version."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    "firmware_version": "1.0.0",
                    "firmware_update_info": {"latest_version": "2.0.0"},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.latest_version == "2.0.0"

    def test_latest_version_falls_back_to_installed(self):
        """When no firmware_update_info, latest_version equals installed_version."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {"type": "inverter", "model": "X", "firmware_version": "1.0.0"}
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.latest_version == "1.0.0"

    def test_release_summary(self):
        """release_summary from firmware_update_info."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    "firmware_update_info": {"release_summary": "Bug fixes"},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.release_summary == "Bug fixes"

    def test_release_summary_none(self):
        """release_summary is None when firmware_update_info is absent."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.release_summary is None

    def test_release_url(self):
        """release_url from firmware_update_info."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    "firmware_update_info": {"release_url": "https://example.com/fw"},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.release_url == "https://example.com/fw"

    def test_title_from_update_info(self):
        """title prefers firmware_update_info.title."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "firmware_update_info": {"title": "Critical Update"},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.title == "Critical Update"

    def test_title_falls_back_to_model_firmware(self):
        """title falls back to '{model} Firmware' when no update info."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "FlexBOSS21"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.title == "FlexBOSS21 Firmware"

    def test_title_fallback_device_when_model_missing(self):
        """title falls back to 'Device Firmware' when model key is absent."""
        coordinator = _mock_coordinator(devices={"SN1": {"type": "inverter"}})
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.title == "Device Firmware"

    def test_title_none_when_no_device_data(self):
        """title returns None when device serial is missing from data."""
        coordinator = _mock_coordinator(devices={})
        entity = EG4FirmwareUpdateEntity(coordinator, "SN_GONE")
        assert entity.title is None

    def test_in_progress_true(self):
        """in_progress is True when firmware_update_info says so."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    "firmware_update_info": {"in_progress": True},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.in_progress is True

    def test_in_progress_false_default(self):
        """in_progress defaults to False when not in update info."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.in_progress is False

    def test_in_progress_true_while_install_lock_held(self):
        """While this entity drives an install (lock held), in_progress stays
        True across the whole multi-component chain even if the coordinator
        cache momentarily reads idle between components (#353)."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    # coordinator's cached firmware status reads idle mid-chain
                    "firmware_update_info": {"in_progress": False},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        entity._install_lock = MagicMock()
        entity._install_lock.locked.return_value = True
        assert entity.in_progress is True

    def test_in_progress_false_no_device_data(self):
        """in_progress returns False when device is absent."""
        coordinator = _mock_coordinator(devices={})
        entity = EG4FirmwareUpdateEntity(coordinator, "SN_GONE")
        assert entity.in_progress is False

    def test_update_percentage(self):
        """update_percentage returns int from firmware_update_info."""
        coordinator = _mock_coordinator(
            devices={
                "SN1": {
                    "type": "inverter",
                    "model": "X",
                    "firmware_update_info": {"update_percentage": 42},
                }
            }
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.update_percentage == 42

    def test_update_percentage_none_without_info(self):
        """update_percentage is None when no firmware_update_info."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.update_percentage is None

    def test_available_true(self):
        """Entity is available when coordinator succeeds and serial is in data."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.available is True

    def test_available_false_update_failed(self):
        """Entity unavailable when last_update_success is False."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}},
            last_update_success=False,
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.available is False

    def test_available_false_serial_missing(self):
        """Entity unavailable when its serial is not in coordinator data."""
        coordinator = _mock_coordinator(devices={})
        entity = EG4FirmwareUpdateEntity(coordinator, "SN_GONE")
        assert entity.available is False

    def test_available_false_no_data(self):
        """Entity unavailable when coordinator.data is None."""
        coordinator = _mock_coordinator()
        coordinator.data = None
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.available is False

    def test_device_info_delegates_to_coordinator(self):
        """device_info calls coordinator.get_device_info with serial."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        sentinel = MagicMock()
        coordinator.get_device_info = MagicMock(return_value=sentinel)
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")
        assert entity.device_info is sentinel
        coordinator.get_device_info.assert_called_once_with("SN1")


# -- async_install ------------------------------------------------------------


class TestAsyncInstall:
    """Test the firmware install action."""

    @pytest.mark.asyncio
    async def test_install_runs_to_completion_and_refreshes(self):
        """Install runs the multi-step orchestrator then refreshes (#353)."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        await entity.async_install(version=None, backup=False)

        device = coordinator._get_device_object("SN1")
        device.run_firmware_update_to_completion.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_device_not_found_raises(self):
        """When device object is None, install raises instead of silently
        returning (#353 — silent no-op looked like success)."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        coordinator._get_device_object = MagicMock(return_value=None)
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        with pytest.raises(HomeAssistantError, match="not found"):
            await entity.async_install(version=None, backup=False)

        coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_install_failure_result_raises(self):
        """A non-success orchestration result raises with its message —
        a refused start must not log 'initiated' and vanish (#353)."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        device = coordinator._get_device_object("SN1")
        device.run_firmware_update_to_completion = AsyncMock(
            return_value=SimpleNamespace(
                success=False,
                converged=False,
                steps_run=1,
                message="API refused to start the firmware update",
                final_version="ccaa-1E1415",
            )
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        with pytest.raises(HomeAssistantError, match="API refused"):
            await entity.async_install(version=None, backup=False)

        # Refresh still happens (finally) so state reflects reality.
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_install_rejected(self):
        """Two same-window installs must not both reach the update API: HA
        skips its busy flag for native-progress entities and in_progress is
        coordinator-derived (lags), so the entity serializes via its own
        lock (post-beta.1 scan P2)."""
        import asyncio

        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        device = coordinator._get_device_object("SN1")
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_run():
            started.set()
            await release.wait()
            return SimpleNamespace(
                success=True,
                converged=True,
                steps_run=1,
                message="ok",
                final_version="V",
            )

        device.run_firmware_update_to_completion = AsyncMock(side_effect=_slow_run)
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        first = asyncio.create_task(entity.async_install(version=None, backup=False))
        await started.wait()

        with pytest.raises(HomeAssistantError, match="already running"):
            await entity.async_install(version=None, backup=False)

        release.set()
        await first
        assert device.run_firmware_update_to_completion.call_count == 1

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_mask_success(self):
        """A failing post-install refresh is swallowed: a successful update
        must not surface as an installation error (codex P2)."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        coordinator.async_request_refresh = AsyncMock(
            side_effect=RuntimeError("refresh boom")
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        await entity.async_install(version=None, backup=False)  # no raise

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_mask_orchestrator_error(self):
        """The orchestrator's exception wins over a refresh exception."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        device = coordinator._get_device_object("SN1")
        device.run_firmware_update_to_completion = AsyncMock(
            side_effect=RuntimeError("update boom")
        )
        coordinator.async_request_refresh = AsyncMock(
            side_effect=RuntimeError("refresh boom")
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        with pytest.raises(RuntimeError, match="update boom"):
            await entity.async_install(version=None, backup=False)

    @pytest.mark.asyncio
    async def test_install_reraises_exceptions(self):
        """Exceptions from the orchestrator are re-raised; refresh still runs."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        device = coordinator._get_device_object("SN1")
        device.run_firmware_update_to_completion = AsyncMock(
            side_effect=RuntimeError("connection lost")
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        with pytest.raises(RuntimeError, match="connection lost"):
            await entity.async_install(version=None, backup=False)

        coordinator.async_request_refresh.assert_called_once()


class TestInstallLockLifetime:
    """The install lock must survive entity replacement (config reload)."""

    def test_lock_shared_across_entity_instances_for_same_serial(self):
        """Two entity instances for the same serial share one lock; a
        different serial gets its own (codex review: per-instance locks
        would let a reloaded entity race an in-flight install)."""
        c1 = _mock_coordinator(devices={"SN1": {"type": "inverter", "model": "X"}})
        c2 = _mock_coordinator(devices={"SN1": {"type": "inverter", "model": "X"}})
        c3 = _mock_coordinator(devices={"SN2": {"type": "inverter", "model": "X"}})

        e1 = EG4FirmwareUpdateEntity(c1, "SN1")
        e2 = EG4FirmwareUpdateEntity(c2, "SN1")
        e3 = EG4FirmwareUpdateEntity(c3, "SN2")

        assert e1._install_lock is e2._install_lock
        assert e1._install_lock is not e3._install_lock
