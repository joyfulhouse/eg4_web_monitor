"""Tests for config_flow helpers module."""

from unittest.mock import MagicMock

import pytest

from custom_components.eg4_web_monitor.config_flow.helpers import (
    build_unique_id,
    find_plant_by_id,
    format_entry_title,
    get_ha_timezone,
    get_reconfigure_entry,
    timezone_observes_dst,
)


class TestTimezoneObservesDst:
    """Tests for timezone_observes_dst function."""

    def test_none_timezone(self):
        """Test with None timezone."""
        assert timezone_observes_dst(None) is False

    def test_empty_timezone(self):
        """Test with empty string timezone."""
        assert timezone_observes_dst("") is False

    def test_utc_no_dst(self):
        """Test UTC which does not observe DST."""
        assert timezone_observes_dst("UTC") is False

    def test_america_new_york_has_dst(self):
        """Test America/New_York which observes DST."""
        assert timezone_observes_dst("America/New_York") is True

    def test_america_los_angeles_has_dst(self):
        """Test America/Los_Angeles which observes DST."""
        assert timezone_observes_dst("America/Los_Angeles") is True

    def test_asia_tokyo_no_dst(self):
        """Test Asia/Tokyo which does not observe DST."""
        assert timezone_observes_dst("Asia/Tokyo") is False

    def test_europe_london_has_dst(self):
        """Test Europe/London which observes DST (BST)."""
        assert timezone_observes_dst("Europe/London") is True

    def test_invalid_timezone(self):
        """Test invalid timezone name."""
        assert timezone_observes_dst("Invalid/Timezone") is False


class TestGetHaTimezone:
    """Tests for get_ha_timezone function."""

    def test_gets_timezone_from_hass_config(self):
        """Test that function gets timezone from hass.config."""
        mock_hass = MagicMock()
        mock_hass.config.time_zone = "America/Chicago"

        result = get_ha_timezone(mock_hass)

        assert result == "America/Chicago"

    def test_returns_none_if_no_timezone(self):
        """Test when timezone is not configured."""
        mock_hass = MagicMock()
        mock_hass.config.time_zone = None

        result = get_ha_timezone(mock_hass)

        assert result is None


class TestFormatEntryTitle:
    """Tests for format_entry_title function."""

    def test_web_monitor_mode(self):
        """Test title for Web Monitor mode."""
        result = format_entry_title("Web Monitor", "My Station")
        # BRAND_NAME is "EG4 Electronics" from const.py
        assert result == "EG4 Electronics Web Monitor - My Station"

    def test_modbus_mode(self):
        """Test title for Modbus mode."""
        result = format_entry_title("Modbus", "1234567890")
        assert result == "EG4 Electronics Modbus - 1234567890"

    def test_dongle_mode(self):
        """Test title for Dongle mode."""
        result = format_entry_title("Dongle", "9876543210")
        assert result == "EG4 Electronics Dongle - 9876543210"

    def test_hybrid_mode(self):
        """Test title for Hybrid mode."""
        result = format_entry_title("Hybrid", "My Hybrid Station")
        assert result == "EG4 Electronics Hybrid - My Hybrid Station"


class TestBuildUniqueId:
    """Tests for build_unique_id function."""

    def test_http_mode(self):
        """Test unique ID for HTTP mode."""
        result = build_unique_id("http", username="user@example.com", plant_id="12345")
        assert result == "user@example.com_12345"

    def test_http_mode_missing_username(self):
        """Test HTTP mode raises error without username."""
        with pytest.raises(
            ValueError, match="HTTP mode requires username and plant_id"
        ):
            build_unique_id("http", plant_id="12345")

    def test_http_mode_missing_plant_id(self):
        """Test HTTP mode raises error without plant_id."""
        with pytest.raises(
            ValueError, match="HTTP mode requires username and plant_id"
        ):
            build_unique_id("http", username="user@example.com")

    def test_hybrid_mode(self):
        """Test unique ID for Hybrid mode."""
        result = build_unique_id(
            "hybrid", username="user@example.com", plant_id="12345"
        )
        assert result == "hybrid_user@example.com_12345"

    def test_hybrid_mode_missing_params(self):
        """Test Hybrid mode raises error without required params."""
        with pytest.raises(
            ValueError, match="Hybrid mode requires username and plant_id"
        ):
            build_unique_id("hybrid", username="user@example.com")

    def test_modbus_mode(self):
        """Test unique ID for Modbus mode."""
        result = build_unique_id("modbus", serial="1234567890")
        assert result == "modbus_1234567890"

    def test_modbus_mode_missing_serial(self):
        """Test Modbus mode raises error without serial."""
        with pytest.raises(ValueError, match="Modbus mode requires serial"):
            build_unique_id("modbus")

    def test_dongle_mode(self):
        """Test unique ID for Dongle mode."""
        result = build_unique_id("dongle", serial="9876543210")
        assert result == "dongle_9876543210"

    def test_dongle_mode_missing_serial(self):
        """Test Dongle mode raises error without serial."""
        with pytest.raises(ValueError, match="Dongle mode requires serial"):
            build_unique_id("dongle")

    def test_local_mode(self):
        """Test unique ID for Local mode."""
        result = build_unique_id("local", station_name="My Local Station")
        assert result == "local_my_local_station"

    def test_local_mode_normalizes_name(self):
        """Test Local mode normalizes station name."""
        result = build_unique_id("local", station_name="My Station Name")
        assert result == "local_my_station_name"

    def test_local_mode_missing_station_name(self):
        """Test Local mode raises error without station_name."""
        with pytest.raises(ValueError, match="Local mode requires station_name"):
            build_unique_id("local")

    def test_unknown_mode(self):
        """Test unknown mode raises error."""
        with pytest.raises(ValueError, match="Unknown mode: invalid"):
            build_unique_id("invalid")


class TestGetReconfigureEntry:
    """Tests for get_reconfigure_entry function."""

    def test_returns_entry_when_found(self):
        """Test returns config entry when entry_id is valid."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_hass.config_entries.async_get_entry.return_value = mock_entry

        context = {"entry_id": "test-entry-id"}

        result = get_reconfigure_entry(mock_hass, context)

        assert result == mock_entry
        mock_hass.config_entries.async_get_entry.assert_called_once_with("test-entry-id")

    def test_returns_none_when_no_entry_id(self):
        """Test returns None when entry_id not in context."""
        mock_hass = MagicMock()
        context = {}

        result = get_reconfigure_entry(mock_hass, context)

        assert result is None
        mock_hass.config_entries.async_get_entry.assert_not_called()

    def test_returns_none_when_entry_not_found(self):
        """Test returns None when entry doesn't exist."""
        mock_hass = MagicMock()
        mock_hass.config_entries.async_get_entry.return_value = None
        context = {"entry_id": "nonexistent-id"}

        result = get_reconfigure_entry(mock_hass, context)

        assert result is None


class TestFindPlantById:
    """Tests for find_plant_by_id function."""

    def test_finds_plant_in_list(self):
        """Test finding plant by ID in list."""
        plants = [
            {"plantId": "plant-1", "name": "Plant One"},
            {"plantId": "plant-2", "name": "Plant Two"},
            {"plantId": "plant-3", "name": "Plant Three"},
        ]

        result = find_plant_by_id(plants, "plant-2")

        assert result == {"plantId": "plant-2", "name": "Plant Two"}

    def test_returns_none_for_missing_plant(self):
        """Test returns None when plant ID not found."""
        plants = [
            {"plantId": "plant-1", "name": "Plant One"},
        ]

        result = find_plant_by_id(plants, "nonexistent")

        assert result is None

    def test_returns_none_for_empty_list(self):
        """Test returns None when plant list is empty."""
        result = find_plant_by_id([], "any-id")

        assert result is None

    def test_returns_none_for_none_list(self):
        """Test returns None when plant list is None."""
        result = find_plant_by_id(None, "any-id")

        assert result is None

    def test_returns_first_match_for_duplicates(self):
        """Test returns first matching plant if duplicates exist."""
        plants = [
            {"plantId": "dup", "name": "First"},
            {"plantId": "dup", "name": "Second"},
        ]

        result = find_plant_by_id(plants, "dup")

        assert result == {"plantId": "dup", "name": "First"}
