"""Tests for #563: AC Charge is schedule-defined on EG4_OFFGRID.

Covers the four halves of the fix:
- the AC Charge working-mode switch is suppressed on positively resolved
  EG4_OFFGRID inverters (FAMILY_UNSUPPORTED_CONTROL_PARAMS);
- already-registered ``{serial}_ac_charge`` switch entities are purged from
  the registry (with a Repairs notice) by the family-excluded cleanup that
  #548 generalized;
- the schedule-state binary sensors report whether any AC Charge / AC First
  window is configured;
- the clear-schedule buttons normalize every window to 00:00 -> 00:00 via
  the cloud (the only sanctioned off-grid write route, #558/#570).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.binary_sensor import (
    EG4ScheduleActiveBinarySensor,
    async_setup_entry as async_setup_binary_sensor,
)
from custom_components.eg4_web_monitor.button import (
    EG4ClearScheduleButton,
    async_setup_entry as async_setup_button,
)
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_LXP,
    INVERTER_FAMILY_UNKNOWN,
    SCHEDULE_TIME_TYPES,
)
from custom_components.eg4_web_monitor.switch import (
    EG4WorkingModeSwitch,
    async_setup_entry as async_setup_switch,
)
from tests.test_switch_entities import _mock_coordinator as _switch_coordinator

SERIAL = "1234567890"
SPECS = {spec.key: spec for spec in SCHEDULE_TIME_TYPES}

# The reporter's own retained schedule (#563 attachments): 23:05 -> 06:55 in
# window 1, windows 2/3 clear. Packed time is hour | (minute << 8), so
# 23:05 -> 0x0517 and 06:55 -> 0x3706 (H68/H69 in the diagnosis report).
REPORTER_PACKED = {"68": 0x0517, "69": 0x3706, "70": 0, "71": 0, "72": 0, "73": 0}
REPORTER_CLOUD = {
    "HOLD_AC_CHARGE_START_HOUR": 23,
    "HOLD_AC_CHARGE_START_MINUTE": 5,
    "HOLD_AC_CHARGE_END_HOUR": 6,
    "HOLD_AC_CHARGE_END_MINUTE": 55,
    "HOLD_AC_CHARGE_START_HOUR_1": 0,
    "HOLD_AC_CHARGE_START_MINUTE_1": 0,
    "HOLD_AC_CHARGE_END_HOUR_1": 0,
    "HOLD_AC_CHARGE_END_MINUTE_1": 0,
    "HOLD_AC_CHARGE_START_HOUR_2": 0,
    "HOLD_AC_CHARGE_START_MINUTE_2": 0,
    "HOLD_AC_CHARGE_END_HOUR_2": 0,
    "HOLD_AC_CHARGE_END_MINUTE_2": 0,
}


def _mock_coordinator(
    *,
    family: str | None = INVERTER_FAMILY_EG4_OFFGRID,
    device_type: str = "inverter",
    parameters: dict | None = None,
    local_raw: bool = False,
    has_http: bool = True,
    serial: str = SERIAL,
) -> MagicMock:
    """Build a mock coordinator for the schedule-state/clear-control tests."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.plant_id = "plant_123"
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.params_are_local_raw = MagicMock(return_value=local_raw)
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock(return_value=True)
    coordinator.control_transaction_lock = MagicMock(
        side_effect=lambda _serial, _control: asyncio.Lock()
    )

    features = {"inverter_family": family} if family is not None else {}
    coordinator.data = {
        "devices": {
            serial: {"type": device_type, "model": "12000XP", "features": features}
        },
        "parameters": {serial: parameters if parameters is not None else {}},
    }

    client = MagicMock()
    write_result = MagicMock()
    write_result.success = True
    client.api.control.write_parameter = AsyncMock(return_value=write_result)
    coordinator.require_client = MagicMock(return_value=client)
    return coordinator


def _config_entry(entry_id: str = "issue_563_test") -> MockConfigEntry:
    """Return a cloud config entry for registry-cleanup coverage."""
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 Web Monitor - Test Plant",
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_pass",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: True,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test Plant",
        },
        entry_id=entry_id,
    )


class TestACChargeSwitchSuppression:
    """The schedule-defined AC Charge switch is not created on EG4_OFFGRID."""

    @pytest.mark.asyncio
    async def test_offgrid_family_loses_ac_charge_switch_only(self, hass) -> None:
        """Positive EG4_OFFGRID resolution drops FUNC_AC_CHARGE, keeps the rest."""
        coordinator = _switch_coordinator(
            model="12000XP",
            device_data={"features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_switch(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_AC_CHARGE" not in params
        # The other unlisted working modes stay (fail-open adjudication).
        assert "FUNC_FORCED_CHG_EN" in params
        assert "FUNC_CHARGE_LAST" in params

    @pytest.mark.asyncio
    async def test_hybrid_family_keeps_ac_charge_switch(self, hass) -> None:
        """EG4_HYBRID has a genuine enable toggle — the switch stays."""
        coordinator = _switch_coordinator(
            model="FlexBOSS21",
            device_data={"features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_switch(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_AC_CHARGE" in params

    @pytest.mark.asyncio
    async def test_unresolved_family_keeps_ac_charge_switch(self, hass) -> None:
        """Suppression needs a positively identified family (fail-open)."""
        coordinator = _switch_coordinator(
            model="12000XP",
            device_data={"features": {"inverter_family": INVERTER_FAMILY_UNKNOWN}},
        )
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_switch(hass, entry, lambda e, **kw: entities.extend(e))

        params = {
            e._mode_config["param"]
            for e in entities
            if isinstance(e, EG4WorkingModeSwitch)
        }
        assert "FUNC_AC_CHARGE" in params


class TestACChargeSwitchRegistryCleanup:
    """Orphaned ac_charge switches are purged only for resolved off-grid units."""

    async def test_cleanup_is_family_domain_and_namespace_scoped(self, hass) -> None:
        """Purge the off-grid switch; preserve every adjacent entity."""
        from custom_components.eg4_web_monitor import async_setup_entry

        entry = _config_entry()
        entry.add_to_hass(hass)
        registry = er.async_get(hass)

        offgrid = "1000000002"
        hybrid = "1000000001"
        unknown = "1000000003"
        missing = "1000000004"
        lxp = "1000000005"

        for serial in (offgrid, hybrid, unknown, missing, lxp):
            registry.async_get_or_create(
                "switch", DOMAIN, f"{serial}_ac_charge", config_entry=entry
            )

        # Legacy model-prefixed registration of the same control: removed too.
        legacy_uid = f"12000xp_{offgrid}_ac_charge"
        registry.async_get_or_create("switch", DOMAIN, legacy_uid, config_entry=entry)

        # Adjacent entities that must survive: the energy sensor with an
        # ac_charge prefix, the flag-only battery-backup suppression (NOT
        # registry-removed), and a lowercase-serial variant boundary case.
        registry.async_get_or_create(
            "switch", DOMAIN, f"{offgrid}_battery_backup_ctrl", config_entry=entry
        )
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{offgrid}_ac_charge_energy", config_entry=entry
        )
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{offgrid}_ac_charge", config_entry=entry
        )

        coordinator = MagicMock()
        coordinator._async_load_pv_string_lifetime_state = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.data = {
            "devices": {
                offgrid: {
                    "type": "inverter",
                    "model": "12000XP",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID},
                },
                hybrid: {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "features": {"inverter_family": INVERTER_FAMILY_EG4_HYBRID},
                },
                unknown: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_UNKNOWN},
                },
                missing: {"type": "inverter", "features": {}},
                lxp: {
                    "type": "inverter",
                    "features": {"inverter_family": INVERTER_FAMILY_LXP},
                },
            }
        }

        with (
            patch(
                "custom_components.eg4_web_monitor.EG4DataUpdateCoordinator",
                return_value=coordinator,
            ),
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
        ):
            assert await async_setup_entry(hass, entry)

        get_eid = registry.async_get_entity_id
        assert get_eid("switch", DOMAIN, f"{offgrid}_ac_charge") is None
        assert get_eid("switch", DOMAIN, legacy_uid) is None
        for serial in (hybrid, unknown, missing, lxp):
            assert get_eid("switch", DOMAIN, f"{serial}_ac_charge") is not None, serial

        assert get_eid("switch", DOMAIN, f"{offgrid}_battery_backup_ctrl") is not None
        assert get_eid("sensor", DOMAIN, f"{offgrid}_ac_charge_energy") is not None
        assert get_eid("sensor", DOMAIN, f"{offgrid}_ac_charge") is not None

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN, f"offgrid_ac_charge_switch_removed_{offgrid}"
            )
            is not None
        )
        for serial in (hybrid, unknown, missing, lxp):
            assert (
                issue_registry.async_get_issue(
                    DOMAIN, f"offgrid_ac_charge_switch_removed_{serial}"
                )
                is None
            )


class TestScheduleActiveBinarySensor:
    """The schedule-state sensors answer 'is a window configured', never
    'is it charging'."""

    def _sensor(
        self, coordinator: MagicMock, key: str = "ac_charge"
    ) -> EG4ScheduleActiveBinarySensor:
        return EG4ScheduleActiveBinarySensor(coordinator, SERIAL, SPECS[key])

    def test_identity_and_translation_keys(self) -> None:
        coordinator = _mock_coordinator()
        sensor = self._sensor(coordinator)
        assert sensor.unique_id == f"{SERIAL}_ac_charge_schedule_active"
        assert sensor.translation_key == "ac_charge_schedule_active"
        first = self._sensor(coordinator, "ac_first")
        assert first.unique_id == f"{SERIAL}_ac_first_schedule_active"
        assert first.translation_key == "ac_first_schedule_active"

    def test_is_on_with_reporter_schedule_cloud(self) -> None:
        """The #563 reporter's retained 23:05 -> 06:55 window reads ON."""
        coordinator = _mock_coordinator(parameters=REPORTER_CLOUD)
        assert self._sensor(coordinator).is_on is True

    def test_is_on_with_reporter_schedule_local_raw(self) -> None:
        """The same window decodes ON from the raw packed registers."""
        coordinator = _mock_coordinator(parameters=REPORTER_PACKED, local_raw=True)
        assert self._sensor(coordinator).is_on is True

    def test_is_off_when_all_windows_zero(self) -> None:
        params = {
            f"HOLD_AC_CHARGE_{boundary}_{field}{suffix}": 0
            for boundary in ("START", "END")
            for field in ("HOUR", "MINUTE")
            for suffix in ("", "_1", "_2")
        }
        coordinator = _mock_coordinator(parameters=params)
        assert self._sensor(coordinator).is_on is False

    def test_is_on_with_overnight_second_window(self) -> None:
        """A configured window anywhere in the schedule reads ON."""
        params = {
            f"HOLD_AC_FIRST_{boundary}_{field}{suffix}": 0
            for boundary in ("START", "END")
            for field in ("HOUR", "MINUTE")
            for suffix in ("", "_1", "_2")
        }
        params["HOLD_AC_FIRST_START_HOUR_1"] = 20
        params["HOLD_AC_FIRST_END_HOUR_1"] = 8
        coordinator = _mock_coordinator(parameters=params)
        assert self._sensor(coordinator, "ac_first").is_on is True

    def test_is_none_when_params_missing(self) -> None:
        coordinator = _mock_coordinator(parameters={})
        assert self._sensor(coordinator).is_on is None

    def test_is_none_when_a_window_is_half_decodable(self) -> None:
        """A half-known window is unknown, never assumed clear."""
        params = dict(REPORTER_CLOUD)
        del params["HOLD_AC_CHARGE_END_HOUR_2"]
        coordinator = _mock_coordinator(parameters=params)
        assert self._sensor(coordinator).is_on is None

    def test_availability(self) -> None:
        coordinator = _mock_coordinator(parameters=REPORTER_CLOUD)
        assert self._sensor(coordinator).available is True
        coordinator.data["devices"][SERIAL]["error"] = "boom"
        assert self._sensor(coordinator).available is False

    @pytest.mark.asyncio
    async def test_created_for_offgrid_inverters_only(self, hass) -> None:
        """Hybrid/LXP/unknown families and non-inverters get no sensors."""
        for family, expected in (
            (INVERTER_FAMILY_EG4_OFFGRID, True),
            (INVERTER_FAMILY_EG4_HYBRID, False),
            (INVERTER_FAMILY_LXP, False),
            (INVERTER_FAMILY_UNKNOWN, False),
            (None, False),
        ):
            coordinator = _mock_coordinator(family=family)
            entry = MagicMock()
            entry.runtime_data = coordinator

            entities = []
            await async_setup_binary_sensor(
                hass, entry, lambda e, **kw: entities.extend(e)
            )
            sensors = [
                e for e in entities if isinstance(e, EG4ScheduleActiveBinarySensor)
            ]
            assert {s._spec.key for s in sensors} == (
                {"ac_charge", "ac_first"} if expected else set()
            ), family

    @pytest.mark.asyncio
    async def test_late_registration_on_family_resolution(self, hass) -> None:
        """A family that resolves off-grid after setup gains the sensors."""
        coordinator = _mock_coordinator(family=INVERTER_FAMILY_UNKNOWN)
        listeners = []
        coordinator.async_add_listener = MagicMock(
            side_effect=lambda cb, *a, **kw: (listeners.append(cb), lambda: None)[1]
        )
        entry = MagicMock()
        entry.runtime_data = coordinator
        entry.async_on_unload = MagicMock()

        entities = []
        await async_setup_binary_sensor(hass, entry, lambda e, **kw: entities.extend(e))
        assert not [e for e in entities if isinstance(e, EG4ScheduleActiveBinarySensor)]

        coordinator.data["devices"][SERIAL]["features"] = {
            "inverter_family": INVERTER_FAMILY_EG4_OFFGRID
        }
        for listener in listeners:
            listener()
        sensors = [e for e in entities if isinstance(e, EG4ScheduleActiveBinarySensor)]
        assert {s._spec.key for s in sensors} == {"ac_charge", "ac_first"}


class TestClearScheduleButton:
    """Cloud-routed schedule normalization (00:00 -> 00:00 every window)."""

    _EXPECTED_AC_CHARGE_WRITES = [
        f"HOLD_AC_CHARGE_{boundary}_{field}{suffix}"
        for suffix in ("", "_1", "_2")
        for boundary in ("START", "END")
        for field in ("HOUR", "MINUTE")
    ]

    def _button(
        self, coordinator: MagicMock, key: str = "ac_charge"
    ) -> EG4ClearScheduleButton:
        return EG4ClearScheduleButton(coordinator, SERIAL, SPECS[key])

    def test_identity_and_translation_keys(self) -> None:
        coordinator = _mock_coordinator()
        button = self._button(coordinator)
        assert button.unique_id == f"{SERIAL}_clear_ac_charge_schedule"
        assert button.translation_key == "clear_ac_charge_schedule"

    @pytest.mark.asyncio
    async def test_created_only_for_offgrid_with_cloud(self, hass) -> None:
        """No cloud client or no positive off-grid family: no button."""
        for family, has_http, expected in (
            (INVERTER_FAMILY_EG4_OFFGRID, True, True),
            (INVERTER_FAMILY_EG4_OFFGRID, False, False),
            (INVERTER_FAMILY_EG4_HYBRID, True, False),
            (INVERTER_FAMILY_UNKNOWN, True, False),
        ):
            coordinator = _mock_coordinator(family=family, has_http=has_http)
            entry = MagicMock()
            entry.runtime_data = coordinator

            entities = []
            await async_setup_button(hass, entry, lambda e, **kw: entities.extend(e))
            buttons = [e for e in entities if isinstance(e, EG4ClearScheduleButton)]
            assert {b._spec.key for b in buttons} == (
                {"ac_charge", "ac_first"} if expected else set()
            ), (family, has_http)

    @pytest.mark.asyncio
    async def test_press_writes_all_windows_zero_and_rereads(self) -> None:
        """All 12 cloud fields written '0', then a final parameter reread."""
        coordinator = _mock_coordinator()
        await self._button(coordinator).async_press()

        write = coordinator.require_client().api.control.write_parameter
        assert write.await_count == 12
        assert [c.args for c in write.await_args_list] == [
            (SERIAL, param, "0") for param in self._EXPECTED_AC_CHARGE_WRITES
        ]
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(SERIAL)
        # Schedule-wide lock: every window register's transaction lock held.
        assert {
            c.args for c in coordinator.control_transaction_lock.call_args_list
        } == {(SERIAL, f"schedule:{reg}") for reg in range(68, 74)}

    @pytest.mark.asyncio
    async def test_press_ac_first_uses_ac_first_params(self) -> None:
        coordinator = _mock_coordinator()
        await self._button(coordinator, "ac_first").async_press()

        write = coordinator.require_client().api.control.write_parameter
        params = [c.args[1] for c in write.await_args_list]
        assert params[0] == "HOLD_AC_FIRST_START_HOUR"
        assert params[-1] == "HOLD_AC_FIRST_END_MINUTE_2"
        assert all(p.startswith("HOLD_AC_FIRST_") for p in params)
        assert {
            c.args for c in coordinator.control_transaction_lock.call_args_list
        } == {(SERIAL, f"schedule:{reg}") for reg in range(152, 158)}

    @pytest.mark.asyncio
    async def test_partial_failure_rereads_and_reports(self) -> None:
        """A mid-sequence failure converges state and names the failed param."""
        from homeassistant.exceptions import HomeAssistantError

        coordinator = _mock_coordinator()
        write = coordinator.require_client().api.control.write_parameter
        ok = MagicMock()
        ok.success = True
        write.side_effect = [ok, ok, ok, ok, RuntimeError("boom")]

        with pytest.raises(HomeAssistantError, match="HOLD_AC_CHARGE_START_HOUR_1"):
            await self._button(coordinator).async_press()
        # The partial-clear convergence reread ran (best effort) after the
        # acknowledged prefix; the final reread did not.
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(SERIAL)

    @pytest.mark.asyncio
    async def test_first_write_failure_skips_reread(self) -> None:
        """Nothing acknowledged -> no convergence reread, plain error."""
        from homeassistant.exceptions import HomeAssistantError

        coordinator = _mock_coordinator()
        write = coordinator.require_client().api.control.write_parameter
        ok = MagicMock()
        ok.success = False
        write.return_value = ok

        with pytest.raises(HomeAssistantError, match="not acknowledged"):
            await self._button(coordinator).async_press()
        coordinator.async_refresh_device_parameters.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_final_reread_is_not_a_press_failure(self) -> None:
        """Acknowledged writes + failed reread: no error, entities converge
        on the next poll."""
        coordinator = _mock_coordinator()
        coordinator.async_refresh_device_parameters = AsyncMock(return_value=False)
        await self._button(coordinator).async_press()
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(SERIAL)
