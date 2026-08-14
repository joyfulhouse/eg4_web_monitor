"""Tests for utility functions in EG4 Web Monitor integration."""

from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.eg4_web_monitor.utils import (
    _resolve_chart_day_timezone,
    battery_row_is_absent,
    clean_battery_display_name,
    create_device_info,
    generate_unique_id,
    is_supported_control_model,
)


class TestChartDayTimezoneResolution:
    """Timezone selection for cloud chart calendar dates."""

    def test_fixed_station_offset_is_used(self, monkeypatch: pytest.MonkeyPatch):
        """A fixed station offset still defines the plant's calendar day."""
        ha_tz = dt_util.get_time_zone("America/Los_Angeles")
        coordinator = SimpleNamespace(station=SimpleNamespace(timezone="GMT +12"))

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(dt_util, "DEFAULT_TIME_ZONE", ha_tz)
            resolved = _resolve_chart_day_timezone(coordinator)

        assert resolved.key == "Etc/GMT-12"
        assert resolved is not ha_tz

    @pytest.mark.parametrize("station_timezone", [None, "GMT +5:30"])
    def test_absent_or_unparsable_station_timezone_uses_ha_timezone(
        self, monkeypatch: pytest.MonkeyPatch, station_timezone: str | None
    ):
        """Missing or invalid station zones fall back to Home Assistant."""
        ha_tz = dt_util.get_time_zone("America/Los_Angeles")
        station = (
            None
            if station_timezone is None
            else SimpleNamespace(timezone=station_timezone)
        )

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(dt_util, "DEFAULT_TIME_ZONE", ha_tz)
            assert (
                _resolve_chart_day_timezone(SimpleNamespace(station=station)) is ha_tz
            )


class TestBatteryRowIsAbsent:
    """#506: the single canonical empty-slot predicate for transport rows."""

    def test_delegates_to_pylxpweb_is_absent(self):
        """A row exposing is_absent() is judged by pylxpweb, not by voltage/SOC."""
        absent = SimpleNamespace(voltage=0.0, soc=0, is_absent=lambda: True)
        present = SimpleNamespace(voltage=52.5, soc=90, is_absent=lambda: False)
        assert battery_row_is_absent(absent) is True
        assert battery_row_is_absent(present) is False

    def test_present_but_degraded_row_is_not_absent(self):
        """The behaviour change: 0 V/0 % with live signals stays in the bank.

        The old inline predicate dropped this row; pylxpweb's canonical
        definition keeps it because the cell block can be lost while current
        and temperature stay live (pylxpweb #249/#248).
        """
        degraded = SimpleNamespace(voltage=0.0, soc=0, is_absent=lambda: False)
        assert battery_row_is_absent(degraded) is False

    def test_fallback_without_is_absent(self):
        """Against a pylxpweb without is_absent(), the old predicate applies.

        Pins older than 0.9.39b6 keep the previous behaviour rather than
        crashing, so the widened definition activates exactly at the bump.
        """
        ghost = SimpleNamespace(voltage=0.0, soc=0)
        live = SimpleNamespace(voltage=52.5, soc=90)
        half_live_voltage = SimpleNamespace(voltage=52.5, soc=0)
        half_live_soc = SimpleNamespace(voltage=0.0, soc=90)
        assert battery_row_is_absent(ghost) is True
        assert battery_row_is_absent(live) is False
        assert battery_row_is_absent(half_live_voltage) is False
        assert battery_row_is_absent(half_live_soc) is False

    def test_non_callable_is_absent_falls_back(self):
        """A non-callable attribute must not be invoked."""
        odd = SimpleNamespace(voltage=0.0, soc=0, is_absent=True)
        assert battery_row_is_absent(odd) is True

    def test_mock_stand_in_does_not_empty_the_bank(self):
        """An unbound Mock attribute must not classify a live row as absent.

        ``Mock().is_absent()`` is callable and returns a truthy ``Mock``, so
        honouring a non-bool verdict would silently drop every battery. Same
        fail-safe rule as the cloud-lost blanking check's ``is True`` guard.
        """
        from unittest.mock import MagicMock

        live = MagicMock()
        live.voltage = 52.5
        live.soc = 90
        assert battery_row_is_absent(live) is False

    def test_partial_stand_in_without_fields(self):
        """Partial objects (the HYBRID freshness probe's case) read as absent."""
        assert battery_row_is_absent(SimpleNamespace()) is True


class TestCleanBatteryDisplayName:
    """Test clean_battery_display_name function."""

    def test_empty_key(self):
        """Test empty battery key."""
        assert clean_battery_display_name("", "1234567890") == "01"

    def test_battery_id_format(self):
        """Test Battery_ID format."""
        assert (
            clean_battery_display_name("Battery_ID_01", "1234567890") == "1234567890-01"
        )

    def test_serial_battery_id_format(self):
        """Test serial_Battery_ID format."""
        result = clean_battery_display_name("1234567890_Battery_ID_02", "1234567890")
        assert result == "1234567890-02"

    def test_bat_prefix(self):
        """Test BAT prefix format."""
        assert clean_battery_display_name("BAT001", "1234567890") == "BAT001"

    def test_numeric_key(self):
        """Test numeric key."""
        assert clean_battery_display_name("1", "1234567890") == "1234567890-01"

    def test_two_digit_numeric(self):
        """Test two-digit numeric key."""
        assert clean_battery_display_name("05", "1234567890") == "1234567890-05"

    def test_generic_key(self):
        """Test generic key with underscores."""
        assert (
            clean_battery_display_name("some_key_name", "1234567890") == "some-key-name"
        )


class TestCreateDeviceInfo:
    """Test create_device_info function."""

    def test_inverter_device(self):
        """Test inverter device info creation."""
        info = create_device_info("1234567890", "FlexBOSS21")

        assert info["identifiers"] == {("eg4_web_monitor", "1234567890")}
        assert info["name"] == "FlexBOSS21 1234567890"
        assert info["manufacturer"] == "EG4 Electronics"
        assert info["model"] == "FlexBOSS21"
        assert info["serial_number"] == "1234567890"

    def test_gridboss_device(self):
        """Test GridBOSS device info creation."""
        info = create_device_info("9876543210", "GridBOSS")

        assert info["name"] == "GridBOSS 9876543210"
        assert info["model"] == "GridBOSS"


class TestGenerateUniqueId:
    """Test generate_unique_id function."""

    def test_basic_unique_id(self):
        """Test basic unique ID generation."""
        unique_id = generate_unique_id("1234567890", "ac_power")
        assert unique_id == "1234567890_ac_power"

    def test_with_suffix(self):
        """Test unique ID with suffix."""
        unique_id = generate_unique_id("1234567890", "battery", "01")
        assert unique_id == "1234567890_battery_01"


class TestIsSupportedControlModel:
    """Test is_supported_control_model — the control/config entity gate (#259)."""

    def test_model_substring_match(self):
        """A model whose name contains a known substring is supported."""
        assert is_supported_control_model({"model": "12000XP"}) is True
        assert is_supported_control_model({"model": "FlexBOSS21"}) is True
        assert is_supported_control_model({"model": "18kPV"}) is True
        # SNA-US 12K accidentally matches "12k" — still supported.
        assert is_supported_control_model({"model": "SNA-US 12K"}) is True

    def test_sna_15k_falls_back_to_family(self):
        """#259: "SNA-US 15K" matches no substring but is EG4_OFFGRID family.

        device type code 54 (SNA12K-US) reports deviceTypeText "SNA-US 15K" in
        cloud mode — "15k" is not in SUPPORTED_INVERTER_MODELS and there is no
        "xp"/"sna" token, so the substring gate fails. The detected family
        backstops it so control/config entities are still created.
        """
        assert (
            is_supported_control_model(
                {"model": "SNA-US 15K", "features": {"inverter_family": "EG4_OFFGRID"}}
            )
            is True
        )

    def test_hybrid_and_lxp_families_supported(self):
        """EG4_HYBRID and LXP families are control-capable even with odd names."""
        assert (
            is_supported_control_model(
                {"model": "Mystery 99K", "features": {"inverter_family": "EG4_HYBRID"}}
            )
            is True
        )
        assert (
            is_supported_control_model(
                {"model": "Mystery 99K", "features": {"inverter_family": "LXP"}}
            )
            is True
        )

    def test_unknown_model_and_family_not_supported(self):
        """No substring match and no known family → not supported (fails closed)."""
        assert (
            is_supported_control_model(
                {"model": "SNA-US 15K", "features": {"inverter_family": "UNKNOWN"}}
            )
            is False
        )
        assert is_supported_control_model({"model": "SomeGenericThing"}) is False
        assert is_supported_control_model({}) is False

    def test_non_string_model_is_safe(self):
        """A non-string model must not raise; only family can rescue it."""
        assert is_supported_control_model({"model": None}) is False
        assert (
            is_supported_control_model(
                {"model": None, "features": {"inverter_family": "EG4_OFFGRID"}}
            )
            is True
        )
