"""Tests for EG4 firmware update entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import EntityCategory

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

    # _get_device_object default: returns a mock device
    mock_device = MagicMock()
    mock_device.start_firmware_update = AsyncMock()
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
    async def test_install_calls_device_and_refreshes(self):
        """Install triggers start_firmware_update then coordinator refresh."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        await entity.async_install(version=None, backup=False)

        device = coordinator._get_device_object("SN1")
        device.start_firmware_update.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_device_not_found(self):
        """When device object is None, install logs error and returns."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        coordinator._get_device_object = MagicMock(return_value=None)
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        # Should not raise
        await entity.async_install(version=None, backup=False)

        coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_install_reraises_exceptions(self):
        """Exceptions from start_firmware_update are re-raised."""
        coordinator = _mock_coordinator(
            devices={"SN1": {"type": "inverter", "model": "X"}}
        )
        device = coordinator._get_device_object("SN1")
        device.start_firmware_update = AsyncMock(
            side_effect=RuntimeError("connection lost")
        )
        entity = EG4FirmwareUpdateEntity(coordinator, "SN1")

        with pytest.raises(RuntimeError, match="connection lost"):
            await entity.async_install(version=None, backup=False)
