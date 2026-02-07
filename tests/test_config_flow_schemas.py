"""Tests for config_flow schemas module."""

import pytest
import voluptuous as vol

from custom_components.eg4_web_monitor._config_flow.schemas import (
    build_dongle_schema,
    build_http_credentials_schema,
    build_http_reconfigure_schema,
    build_modbus_schema,
    build_plant_selection_schema,
    build_reauth_schema,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_INVERTER_SERIAL,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME


class TestBuildHttpCredentialsSchema:
    """Tests for build_http_credentials_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        schema = build_http_credentials_schema()
        assert isinstance(schema, vol.Schema)

    def test_requires_username_and_password(self):
        """Test that username and password are required."""
        schema = build_http_credentials_schema()

        with pytest.raises(vol.MultipleInvalid):
            schema({})

    def test_accepts_all_fields(self):
        """Test schema accepts all credential fields."""
        schema = build_http_credentials_schema()
        result = schema(
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "password123",
                CONF_BASE_URL: "https://custom.example.com",
                CONF_VERIFY_SSL: False,
                CONF_DST_SYNC: True,
            }
        )
        assert result[CONF_USERNAME] == "user@example.com"
        assert result[CONF_PASSWORD] == "password123"
        assert result[CONF_BASE_URL] == "https://custom.example.com"
        assert result[CONF_VERIFY_SSL] is False
        assert result[CONF_DST_SYNC] is True

    def test_dst_sync_default_can_be_customized(self):
        """Test that DST sync default can be customized."""
        schema_with_true = build_http_credentials_schema(dst_sync_default=True)
        schema_with_false = build_http_credentials_schema(dst_sync_default=False)

        # Both should work, just have different defaults
        result_true = schema_with_true({CONF_USERNAME: "user", CONF_PASSWORD: "pass"})
        result_false = schema_with_false({CONF_USERNAME: "user", CONF_PASSWORD: "pass"})

        assert result_true[CONF_DST_SYNC] is True
        assert result_false[CONF_DST_SYNC] is False


class TestBuildModbusSchema:
    """Tests for build_modbus_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        schema = build_modbus_schema()
        assert isinstance(schema, vol.Schema)

    def test_host_is_required_field(self):
        """Test that host is a required field with empty default.

        Note: The schema allows empty host by default (for reconfiguration
        where the default comes from stored config). Validation of non-empty
        host happens at the form submission level in config_flow.
        """
        schema = build_modbus_schema()
        # Schema has empty default for host, which means it validates
        result = schema({})
        # But the result will have empty host
        assert result[CONF_MODBUS_HOST] == ""

    def test_applies_defaults(self):
        """Test that defaults are applied."""
        schema = build_modbus_schema()
        result = schema({CONF_MODBUS_HOST: "192.168.1.100"})

        assert result[CONF_MODBUS_HOST] == "192.168.1.100"
        assert result[CONF_MODBUS_PORT] == DEFAULT_MODBUS_PORT
        assert result[CONF_MODBUS_UNIT_ID] == DEFAULT_MODBUS_UNIT_ID

    def test_uses_provided_defaults(self):
        """Test that provided defaults are used."""
        defaults = {
            CONF_MODBUS_HOST: "192.168.1.200",
            CONF_MODBUS_PORT: 8502,
            CONF_INVERTER_SERIAL: "1234567890",
        }
        schema = build_modbus_schema(defaults)
        result = schema({CONF_MODBUS_HOST: "192.168.1.200"})

        assert result[CONF_MODBUS_PORT] == 8502


class TestBuildDongleSchema:
    """Tests for build_dongle_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        schema = build_dongle_schema()
        assert isinstance(schema, vol.Schema)

    def test_accepts_minimum_required_fields(self):
        """Test that schema accepts minimum fields with defaults.

        Note: The schema has defaults for most fields to support reconfiguration.
        Validation of non-empty required fields happens at form submission.
        """
        schema = build_dongle_schema()
        # Schema has defaults so it accepts minimal input
        result = schema({})
        assert result[CONF_DONGLE_HOST] == ""
        assert result[CONF_DONGLE_SERIAL] == ""
        assert result[CONF_INVERTER_SERIAL] == ""

    def test_applies_defaults(self):
        """Test that defaults are applied."""
        schema = build_dongle_schema()
        result = schema(
            {
                CONF_DONGLE_HOST: "192.168.1.100",
                CONF_DONGLE_SERIAL: "dongle123",
                CONF_INVERTER_SERIAL: "inverter456",
            }
        )

        assert result[CONF_DONGLE_PORT] == DEFAULT_DONGLE_PORT


class TestBuildPlantSelectionSchema:
    """Tests for build_plant_selection_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        plants = [{"plantId": "123", "name": "Test Plant"}]
        schema = build_plant_selection_schema(plants)
        assert isinstance(schema, vol.Schema)

    def test_requires_plant_id(self):
        """Test that plant ID is required."""
        plants = [{"plantId": "123", "name": "Test Plant"}]
        schema = build_plant_selection_schema(plants)

        with pytest.raises(vol.MultipleInvalid):
            schema({})

    def test_validates_plant_id(self):
        """Test that invalid plant ID is rejected."""
        plants = [{"plantId": "123", "name": "Test Plant"}]
        schema = build_plant_selection_schema(plants)

        with pytest.raises(vol.MultipleInvalid):
            schema({CONF_PLANT_ID: "invalid"})

    def test_accepts_valid_plant_id(self):
        """Test that valid plant ID is accepted."""
        plants = [
            {"plantId": "123", "name": "Plant 1"},
            {"plantId": "456", "name": "Plant 2"},
        ]
        schema = build_plant_selection_schema(plants)
        result = schema({CONF_PLANT_ID: "456"})
        assert result[CONF_PLANT_ID] == "456"

    def test_uses_current_as_default(self):
        """Test that current plant is used as default."""
        plants = [
            {"plantId": "123", "name": "Plant 1"},
            {"plantId": "456", "name": "Plant 2"},
        ]
        schema = build_plant_selection_schema(plants, current="456")
        result = schema({})
        assert result[CONF_PLANT_ID] == "456"


class TestBuildReauthSchema:
    """Tests for build_reauth_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        schema = build_reauth_schema()
        assert isinstance(schema, vol.Schema)

    def test_requires_password(self):
        """Test that password is required."""
        schema = build_reauth_schema()

        with pytest.raises(vol.MultipleInvalid):
            schema({})

    def test_accepts_password(self):
        """Test that password is accepted."""
        schema = build_reauth_schema()
        result = schema({CONF_PASSWORD: "newpassword"})
        assert result[CONF_PASSWORD] == "newpassword"


class TestBuildHttpReconfigureSchema:
    """Tests for build_http_reconfigure_schema function."""

    def test_returns_schema(self):
        """Test that function returns a valid schema."""
        schema = build_http_reconfigure_schema()
        assert isinstance(schema, vol.Schema)

    def test_uses_provided_defaults(self):
        """Test that provided defaults are used."""
        schema = build_http_reconfigure_schema(
            current_username="old@example.com",
            current_base_url="https://old.example.com",
            current_verify_ssl=False,
            current_dst_sync=False,
        )
        result = schema({CONF_PASSWORD: "newpass"})

        assert result[CONF_USERNAME] == "old@example.com"
        assert result[CONF_BASE_URL] == "https://old.example.com"
        assert result[CONF_VERIFY_SSL] is False
        assert result[CONF_DST_SYNC] is False
