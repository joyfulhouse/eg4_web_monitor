"""Test reconfigure flow for EG4 Web Monitor integration."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from pylxpweb.exceptions import LuxpowerAuthError as EG4AuthError

from tests.test_config_flow import _mock_luxpower_client


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock async_setup_entry and platform setups to prevent integration setup."""
    with (
        patch(
            "custom_components.eg4_web_monitor.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_setup",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.eg4_web_monitor.coordinator.EG4DataUpdateCoordinator._should_refresh_parameters",
            return_value=False,
        ),
    ):
        yield


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry for reconfiguration tests."""
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="EG4 Electronics Web Monitor - Test Plant",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "123",
            CONF_PLANT_NAME: "Test Plant",
            CONF_LOCAL_TRANSPORTS: [],
        },
        source=config_entries.SOURCE_USER,
        unique_id="test@example.com_123",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api_single_plant():
    """Create a mock for LuxpowerClient with a single plant."""
    from tests.conftest import create_mock_station

    with _mock_luxpower_client(stations=[create_mock_station("123", "Test Plant")]):
        yield None


@pytest.fixture
def mock_api_multiple_plants():
    """Create a mock for LuxpowerClient with multiple plants."""
    from tests.conftest import create_mock_station

    stations = [
        create_mock_station("123", "Test Plant 1"),
        create_mock_station("456", "Test Plant 2"),
    ]
    with _mock_luxpower_client(stations=stations):
        yield None


async def _init_reconfigure(hass: HomeAssistant, entry: MockConfigEntry):
    """Init reconfigure flow and navigate to the reconfigure menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    # Reconfigure entry point loads state and goes to reconfigure_menu
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "reconfigure_menu"
    return result


async def test_reconfigure_flow_update_credentials(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration updating cloud credentials."""
    result = await _init_reconfigure(hass, mock_config_entry)

    # Select cloud update from menu
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "reconfigure_cloud_update"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure_cloud_update"

    # Submit new credentials
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "newpassword",
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_PASSWORD] == "newpassword"
    assert updated_entry.data[CONF_PLANT_ID] == "123"


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    """Test reconfiguration with invalid credentials shows error."""
    with _mock_luxpower_client(side_effect=EG4AuthError("Invalid credentials")):
        result = await _init_reconfigure(hass, mock_config_entry)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_cloud_update"},
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "wrongpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure_cloud_update"
        assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_update_base_url(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api_single_plant
):
    """Test reconfiguration can update base URL."""
    result = await _init_reconfigure(hass, mock_config_entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "reconfigure_cloud_update"},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword",
            CONF_BASE_URL: "https://custom.eg4.com",
            CONF_VERIFY_SSL: False,
            CONF_DST_SYNC: False,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_BASE_URL] == "https://custom.eg4.com"
    assert updated_entry.data[CONF_VERIFY_SSL] is False
    assert updated_entry.data[CONF_DST_SYNC] is False


# =====================================================
# RECONFIGURE MENU TESTS
# =====================================================


def _make_discovered_device(
    serial="1234567890",
    model="FlexBOSS21",
    family="EG4_HYBRID",
    device_type_code=10284,
    firmware_version="1.0.0",
    is_gridboss=False,
    pv_power=1500.0,
    battery_soc=65,
):
    """Create a DiscoveredDevice for use in reconfigure tests."""
    from custom_components.eg4_web_monitor._config_flow.discovery import (
        DiscoveredDevice,
    )

    return DiscoveredDevice(
        serial=serial,
        model=model,
        family=family,
        device_type_code=device_type_code,
        firmware_version=firmware_version,
        is_gridboss=is_gridboss,
        pv_power=pv_power,
        battery_soc=battery_soc,
    )


class TestReconfigureMenuOptions:
    """Tests for reconfigure_menu step dynamic options."""

    async def test_cloud_only_menu_shows_update_and_devices(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ):
        """Test cloud-only entry shows update option and devices option."""
        result = await _init_reconfigure(hass, mock_config_entry)

        assert result["type"] == data_entry_flow.FlowResultType.MENU
        assert result["step_id"] == "reconfigure_menu"
        assert "reconfigure_cloud_update" in result["menu_options"]
        assert "reconfigure_devices" in result["menu_options"]
        # No cloud_remove for cloud-only (no local devices)
        assert "reconfigure_cloud_remove" not in result["menu_options"]
        # No cloud_add since cloud is already configured
        assert "reconfigure_cloud_add" not in result["menu_options"]

    async def test_local_only_menu_shows_add_cloud(self, hass: HomeAssistant):
        """Test local-only entry shows add cloud option."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Local Setup",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_local_setup",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        assert "reconfigure_cloud_add" in result["menu_options"]
        assert "reconfigure_devices" in result["menu_options"]
        assert "reconfigure_cloud_update" not in result["menu_options"]

    async def test_hybrid_menu_shows_remove_cloud(self, hass: HomeAssistant):
        """Test hybrid entry shows remove cloud option."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Hybrid Setup",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_PLANT_ID: "123",
                CONF_PLANT_NAME: "Test Plant",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
            },
            source=config_entries.SOURCE_USER,
            unique_id="hybrid_test@example.com_123",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        assert "reconfigure_cloud_update" in result["menu_options"]
        assert "reconfigure_cloud_remove" in result["menu_options"]
        assert "reconfigure_devices" in result["menu_options"]


# =====================================================
# RECONFIGURE: Cloud removal (detach cloud)
# =====================================================


class TestReconfigureCloudRemove:
    """Tests for removing cloud credentials from a hybrid entry."""

    async def test_detach_cloud_from_hybrid(self, hass: HomeAssistant):
        """Test detaching cloud credentials converts hybrid to local."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Hybrid Setup",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_PLANT_ID: "123",
                CONF_PLANT_NAME: "Hybrid Plant",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
            },
            source=config_entries.SOURCE_USER,
            unique_id="hybrid_test@example.com_123",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        # Select cloud remove
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_cloud_remove"},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure_cloud_remove"

        # Confirm removal
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_CONNECTION_TYPE] == "local"
        assert CONF_USERNAME not in updated_entry.data
        assert CONF_PASSWORD not in updated_entry.data
        assert CONF_PLANT_ID not in updated_entry.data
        assert updated_entry.data[CONF_DST_SYNC] is False
        assert len(updated_entry.data[CONF_LOCAL_TRANSPORTS]) == 1


# =====================================================
# RECONFIGURE: Add cloud to local-only
# =====================================================


class TestReconfigureCloudAdd:
    """Tests for adding cloud credentials to a local-only entry."""

    async def test_add_cloud_to_local_entry(self, hass: HomeAssistant):
        """Test adding cloud credentials to a local-only entry creates hybrid."""
        from tests.conftest import create_mock_station

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Local Setup",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_local_setup",
        )
        entry.add_to_hass(hass)

        with _mock_luxpower_client(
            stations=[create_mock_station("789", "Cloud Plant")]
        ):
            result = await _init_reconfigure(hass, entry)

            # Select add cloud
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_cloud_add"},
            )
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_cloud_add"

            # Submit cloud credentials (single plant auto-selects)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test@example.com",
                    CONF_PASSWORD: "testpassword",
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_VERIFY_SSL: True,
                    CONF_DST_SYNC: True,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.ABORT
            assert result["reason"] == "reconfigure_successful"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_CONNECTION_TYPE] == "hybrid"
        assert updated_entry.data[CONF_USERNAME] == "test@example.com"
        assert updated_entry.data[CONF_PLANT_ID] == "789"
        assert updated_entry.data[CONF_PLANT_NAME] == "Cloud Plant"
        assert len(updated_entry.data[CONF_LOCAL_TRANSPORTS]) == 1

    async def test_add_cloud_with_multiple_plants(self, hass: HomeAssistant):
        """Test adding cloud with multiple plants shows station selection."""
        from tests.conftest import create_mock_station

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Local Setup",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_local_setup",
        )
        entry.add_to_hass(hass)

        stations = [
            create_mock_station("111", "Plant A"),
            create_mock_station("222", "Plant B"),
        ]
        with _mock_luxpower_client(stations=stations):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_cloud_add"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test@example.com",
                    CONF_PASSWORD: "testpassword",
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_VERIFY_SSL: True,
                    CONF_DST_SYNC: True,
                },
            )

            # Should show station selection since multiple plants
            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_cloud_station"

            # Select a plant
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PLANT_ID: "222"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.ABORT
            assert result["reason"] == "reconfigure_successful"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_PLANT_ID] == "222"
        assert updated_entry.data[CONF_PLANT_NAME] == "Plant B"

    async def test_add_cloud_invalid_auth(self, hass: HomeAssistant):
        """Test adding cloud with invalid auth shows error."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Local Setup",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1234567890",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    }
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_local_setup",
        )
        entry.add_to_hass(hass)

        with _mock_luxpower_client(side_effect=EG4AuthError("Invalid credentials")):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_cloud_add"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_USERNAME: "test@example.com",
                    CONF_PASSWORD: "wrongpassword",
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_VERIFY_SSL: True,
                    CONF_DST_SYNC: True,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_cloud_add"
            assert result["errors"] == {"base": "invalid_auth"}


# =====================================================
# RECONFIGURE: Device management
# =====================================================


class TestReconfigureDeviceManagement:
    """Tests for the reconfigure device management flow."""

    async def test_devices_menu_shows_device_list(self, hass: HomeAssistant):
        """Test devices menu shows device list with management options."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Local",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                    {
                        "transport_type": "wifi_dongle",
                        "serial": "2222222222",
                        "model": "18kPV",
                        "host": "192.168.1.200",
                        "port": 8000,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_my_local_setup",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_devices"},
        )

        assert result["type"] == data_entry_flow.FlowResultType.MENU
        assert result["step_id"] == "reconfigure_devices"
        assert result["description_placeholders"]["device_count"] == "2"
        assert "reconfigure_device_add" in result["menu_options"]
        assert "reconfigure_device_remove" in result["menu_options"]
        assert "reconfigure_devices_save" in result["menu_options"]

    async def test_devices_menu_no_remove_when_empty(self, hass: HomeAssistant):
        """Test devices menu hides remove option when no devices."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Empty",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpassword",
                CONF_BASE_URL: DEFAULT_BASE_URL,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: True,
                CONF_PLANT_ID: "123",
                CONF_PLANT_NAME: "Test Plant",
                CONF_LOCAL_TRANSPORTS: [],
            },
            source=config_entries.SOURCE_USER,
            unique_id="test@example.com_123",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_devices"},
        )

        assert result["step_id"] == "reconfigure_devices"
        assert result["description_placeholders"]["device_count"] == "0"
        assert "reconfigure_device_remove" not in result["menu_options"]

    async def test_remove_device_during_reconfigure(self, hass: HomeAssistant):
        """Test removing a local device during reconfigure."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Multi",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                    {
                        "transport_type": "wifi_dongle",
                        "serial": "2222222222",
                        "model": "18kPV",
                        "host": "192.168.1.200",
                        "port": 8000,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_multi_setup",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_devices"},
        )

        # Select remove device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_device_remove"},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure_device_remove"

        # Remove the second device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"device": "2222222222"},
        )

        # Should return to devices menu with 1 device
        assert result["step_id"] == "reconfigure_devices"
        assert result["description_placeholders"]["device_count"] == "1"

        # Save changes
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "reconfigure_devices_save"},
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert len(updated_entry.data[CONF_LOCAL_TRANSPORTS]) == 1
        assert updated_entry.data[CONF_LOCAL_TRANSPORTS][0]["serial"] == "1111111111"

    async def test_add_modbus_device_during_reconfigure(self, hass: HomeAssistant):
        """Test adding a Modbus device during reconfigure."""
        from unittest.mock import AsyncMock, patch

        device = _make_discovered_device(serial="3333333333", model="12kPV")

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Single",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_single_setup",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_device_add"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.MENU
            assert result["step_id"] == "reconfigure_device_add"

            # Select Modbus add
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_add_modbus"},
            )
            assert result["step_id"] == "reconfigure_add_modbus"

            # Submit Modbus config
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.101",
                    "modbus_port": 502,
                    "modbus_unit_id": 2,
                },
            )

            # Grid type form shown for inverter
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )

            # Should return to devices menu with 2 devices
            assert result["step_id"] == "reconfigure_devices"
            assert result["description_placeholders"]["device_count"] == "2"

            # Save changes
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices_save"},
            )

            assert result["type"] == data_entry_flow.FlowResultType.ABORT
            assert result["reason"] == "reconfigure_successful"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert len(updated_entry.data[CONF_LOCAL_TRANSPORTS]) == 2
        assert updated_entry.data[CONF_LOCAL_TRANSPORTS][1]["serial"] == "3333333333"

    async def test_add_dongle_device_during_reconfigure(self, hass: HomeAssistant):
        """Test adding a dongle device during reconfigure."""
        from unittest.mock import AsyncMock, patch

        device = _make_discovered_device(serial="4444444444", model="18kPV")

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Single",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "inverter_family": "EG4_HYBRID",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_single_setup2",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_device_add"},
            )

            # Select Dongle add
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_add_dongle"},
            )
            assert result["step_id"] == "reconfigure_add_dongle"

            # Submit dongle config
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.201",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ44444444",
                    "inverter_serial": "4444444444",
                },
            )

            # Grid type form shown for inverter
            assert result["step_id"] == "local_device_confirmed"

            # Submit grid type
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"grid_type": "split_phase"},
            )

            # Should return to devices menu with 2 devices
            assert result["step_id"] == "reconfigure_devices"
            assert result["description_placeholders"]["device_count"] == "2"

    async def test_reconfigure_add_modbus_timeout(self, hass: HomeAssistant):
        """Test Modbus timeout during reconfigure add shows error."""
        from unittest.mock import AsyncMock, patch

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Single",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_single_timeout",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(side_effect=TimeoutError("Connection timed out")),
        ):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_device_add"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_add_modbus"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.200",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_add_modbus"
            assert result["errors"] == {"base": "modbus_timeout"}

    async def test_reconfigure_add_dongle_connection_failed(self, hass: HomeAssistant):
        """Test dongle connection failure during reconfigure shows error."""
        from unittest.mock import AsyncMock, patch

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Single",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_single_dongle_err",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_dongle_device",
            new=AsyncMock(side_effect=OSError("Connection failed")),
        ):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_device_add"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_add_dongle"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "dongle_host": "192.168.1.200",
                    "dongle_port": 8000,
                    "dongle_serial": "BJ55555555",
                    "inverter_serial": "5555555555",
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_add_dongle"
            assert result["errors"] == {"base": "dongle_connection_failed"}

    async def test_reconfigure_add_duplicate_transport(self, hass: HomeAssistant):
        """Test adding duplicate host:port during reconfigure is rejected."""
        from unittest.mock import AsyncMock, patch

        device = _make_discovered_device(serial="9999999999")

        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Dup Test",
            data={
                CONF_CONNECTION_TYPE: "local",
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "transport_type": "modbus_tcp",
                        "serial": "1111111111",
                        "model": "FlexBOSS21",
                        "host": "192.168.1.100",
                        "port": 502,
                    },
                ],
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="local_dup_test",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.eg4_web_monitor._config_flow.discover_modbus_device",
            new=AsyncMock(return_value=device),
        ):
            result = await _init_reconfigure(hass, entry)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_devices"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_device_add"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"next_step_id": "reconfigure_add_modbus"},
            )

            # Submit same host:port as existing device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "modbus_host": "192.168.1.100",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                },
            )

            assert result["type"] == data_entry_flow.FlowResultType.FORM
            assert result["step_id"] == "reconfigure_add_modbus"
            assert result["errors"] == {"base": "duplicate_transport"}


# =====================================================
# RECONFIGURE: Legacy migration
# =====================================================


class TestReconfigureLegacyMigration:
    """Tests for auto-migration of legacy entries during reconfigure."""

    async def test_legacy_modbus_entry_auto_migrates(self, hass: HomeAssistant):
        """Test legacy modbus entry is auto-migrated on reconfigure."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Legacy Modbus",
            data={
                CONF_CONNECTION_TYPE: "modbus",
                "inverter_serial": "1234567890",
                "inverter_family": "EG4_HYBRID",
                "modbus_host": "192.168.1.100",
                "modbus_port": 502,
                "modbus_unit_id": 1,
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="modbus_1234567890",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        # Should show menu (migration happened silently)
        assert result["type"] == data_entry_flow.FlowResultType.MENU
        assert result["step_id"] == "reconfigure_menu"

        # Verify migration happened
        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_CONNECTION_TYPE] == "local"
        assert CONF_LOCAL_TRANSPORTS in updated_entry.data
        transports = updated_entry.data[CONF_LOCAL_TRANSPORTS]
        assert len(transports) == 1
        assert transports[0]["transport_type"] == "modbus_tcp"
        assert transports[0]["serial"] == "1234567890"

    async def test_legacy_dongle_entry_auto_migrates(self, hass: HomeAssistant):
        """Test legacy dongle entry is auto-migrated on reconfigure."""
        entry = MockConfigEntry(
            version=1,
            domain=DOMAIN,
            title="EG4 Electronics - Legacy Dongle",
            data={
                CONF_CONNECTION_TYPE: "dongle",
                "inverter_serial": "9876543210",
                "inverter_family": "LXP",
                "dongle_host": "192.168.1.200",
                "dongle_port": 8000,
                "dongle_serial": "BJ12345678",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
            },
            source=config_entries.SOURCE_USER,
            unique_id="dongle_9876543210",
        )
        entry.add_to_hass(hass)

        result = await _init_reconfigure(hass, entry)

        assert result["type"] == data_entry_flow.FlowResultType.MENU
        assert result["step_id"] == "reconfigure_menu"

        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_CONNECTION_TYPE] == "local"
        transports = updated_entry.data[CONF_LOCAL_TRANSPORTS]
        assert len(transports) == 1
        assert transports[0]["transport_type"] == "wifi_dongle"
        assert transports[0]["serial"] == "9876543210"
        assert transports[0]["dongle_serial"] == "BJ12345678"


# =====================================================
# RECONFIGURE: _build_entry_data
# =====================================================


class TestBuildEntryData:
    """Tests for the _build_entry_data helper method."""

    def test_cloud_only_entry_data(self):
        """Test _build_entry_data for cloud-only configuration."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._username = "user@example.com"
        flow._password = "secret"
        flow._base_url = DEFAULT_BASE_URL
        flow._verify_ssl = True
        flow._dst_sync = True
        flow._plant_id = "123"
        flow._plant_name = "My Plant"
        flow._local_transports = []

        data = flow._build_entry_data()

        assert data[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_HTTP
        assert data[CONF_USERNAME] == "user@example.com"
        assert data[CONF_PASSWORD] == "secret"
        assert data[CONF_PLANT_ID] == "123"
        assert data[CONF_PLANT_NAME] == "My Plant"
        assert data[CONF_LOCAL_TRANSPORTS] == []

    def test_local_only_entry_data(self):
        """Test _build_entry_data for local-only configuration."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._username = None
        flow._plant_id = None
        flow._local_transports = [
            {"transport_type": "modbus_tcp", "serial": "1234567890"}
        ]

        data = flow._build_entry_data()

        assert data[CONF_CONNECTION_TYPE] == "local"
        assert CONF_USERNAME not in data
        assert CONF_PASSWORD not in data
        assert CONF_PLANT_ID not in data
        assert len(data[CONF_LOCAL_TRANSPORTS]) == 1

    def test_hybrid_entry_data(self):
        """Test _build_entry_data for hybrid configuration."""
        from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow

        flow = EG4ConfigFlow()
        flow._username = "user@example.com"
        flow._password = "secret"
        flow._base_url = DEFAULT_BASE_URL
        flow._verify_ssl = True
        flow._dst_sync = True
        flow._plant_id = "123"
        flow._plant_name = "My Plant"
        flow._local_transports = [
            {"transport_type": "modbus_tcp", "serial": "1234567890"}
        ]

        data = flow._build_entry_data()

        assert data[CONF_CONNECTION_TYPE] == "hybrid"
        assert data[CONF_USERNAME] == "user@example.com"
        assert data[CONF_PLANT_ID] == "123"
        assert len(data[CONF_LOCAL_TRANSPORTS]) == 1


# =====================================================
# RECONFIGURE: Entry not found
# =====================================================


class TestReconfigureEntryNotFound:
    """Tests for reconfigure abort when entry not found."""

    async def test_reconfigure_aborts_if_entry_not_found(self, hass: HomeAssistant):
        """Test reconfigure aborts if the config entry is not found."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": "nonexistent_entry_id",
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "entry_not_found"
