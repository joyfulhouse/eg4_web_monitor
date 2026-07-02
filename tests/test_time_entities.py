"""Tests for the EG4 time platform (AC charge schedule, issue #277).

Registers 68-73 hold the AC charge schedule as three windows × (start, end).
Each 16-bit register packs hour (low byte) | minute (high byte) — verified by
the live cloud register probe in pylxpweb docs/inverters/FlexBOSS21_52XXXXXX78.json,
where querying one register returns BOTH the *_HOUR and *_MINUTE cloud params.
"""

from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    AC_CHARGE_SCHEDULE_BASE_REGISTER,
    LOCAL_AC_CHARGE_TIME_PARAM_KEYS,
)
from custom_components.eg4_web_monitor.time import (
    EG4ACChargeTimeEntity,
    async_setup_entry,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    serial: str = "1234567890",
    model: str = "FlexBOSS21",
    has_local: bool = False,
    has_client: bool = True,
    local_only: bool = False,
    parameters: dict | None = None,
) -> MagicMock:
    """Build a mock coordinator for time entity tests."""
    coordinator = MagicMock()
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.write_register = AsyncMock(return_value=True)
    coordinator.get_device_info = MagicMock(return_value=None)

    coordinator.data = {
        "devices": {serial: {"type": "inverter", "model": model}},
        "device_info": {serial: {"deviceTypeText4APP": model}},
        "parameters": {serial: parameters or {}},
    }

    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    mock_inverter.transport = object() if has_local else None
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    if has_client:
        client = MagicMock()
        write_result = MagicMock()
        write_result.success = True
        client.api.control.write_parameter = AsyncMock(return_value=write_result)
        coordinator.client = client
    else:
        coordinator.client = None

    return coordinator


def _entity(
    coordinator: MagicMock,
    *,
    serial: str = "1234567890",
    window: int = 1,
    is_end: bool = False,
) -> EG4ACChargeTimeEntity:
    return EG4ACChargeTimeEntity(coordinator, serial, window, is_end=is_end)


def _prep(entity: EG4ACChargeTimeEntity) -> None:
    """Prepare entity for async action tests (set hass + entity_id)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "time.test_entity"
    entity.platform = None  # type: ignore[assignment]
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]


def _pack(hour: int, minute: int) -> int:
    """Packed register encoding: hour low byte, minute high byte."""
    return (hour & 0xFF) | ((minute & 0xFF) << 8)


# ── Platform registration ────────────────────────────────────────────


class TestTimePlatformRegistration:
    """The time platform must be forwarded on setup and unloaded."""

    def test_time_platform_in_platforms(self):
        """Platform.TIME is registered for setup and unload."""
        from homeassistant.const import Platform

        from custom_components.eg4_web_monitor import OTHER_PLATFORMS, PLATFORMS

        assert Platform.TIME in OTHER_PLATFORMS
        assert Platform.TIME in PLATFORMS


# ── Platform setup ───────────────────────────────────────────────────


class TestTimePlatformSetup:
    """Entity creation per device/family."""

    @pytest.mark.asyncio
    async def test_setup_creates_six_entities_per_inverter(self, hass):
        """A supported inverter gets 3 windows × (start, end) = 6 entities."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 6
        keys = sorted(e._attr_translation_key for e in entities)
        assert keys == [
            "ac_charge_end_time_1",
            "ac_charge_end_time_2",
            "ac_charge_end_time_3",
            "ac_charge_start_time_1",
            "ac_charge_start_time_2",
            "ac_charge_start_time_3",
        ]

    @pytest.mark.asyncio
    async def test_setup_sna_offgrid_family_creates_entities(self, hass):
        """The reporter's 12000XP: cloud model "SNA-US 15K" with EG4_OFFGRID
        family must get the schedule entities (family backstop, #259/#277)."""
        coordinator = _mock_coordinator(model="SNA-US 15K")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 6

    @pytest.mark.asyncio
    async def test_setup_hybrid_and_lxp_families(self, hass):
        """EG4_HYBRID and LXP families also get schedule entities."""
        for family in ("EG4_HYBRID", "LXP"):
            coordinator = _mock_coordinator(model="Mystery Model")
            coordinator.data["devices"]["1234567890"]["features"] = {
                "inverter_family": family
            }
            entry = MagicMock()
            entry.runtime_data = coordinator

            entities = []
            await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

            assert len(entities) == 6, family

    @pytest.mark.asyncio
    async def test_setup_unsupported_model_creates_nothing(self, hass):
        """Unknown model with no detected family gets no control entities."""
        coordinator = _mock_coordinator(model="Mystery Model")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities == []

    @pytest.mark.asyncio
    async def test_setup_skips_non_inverter_devices(self, hass):
        """GridBOSS/MID devices have no AC charge schedule."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"] = {
            "gb123": {"type": "gridboss", "model": "GridBOSS"}
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities == []

    @pytest.mark.asyncio
    async def test_window_1_enabled_windows_2_3_disabled_by_default(self, hass):
        """Most users use one window: windows 2/3 are registry-disabled."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        by_key = {e._attr_translation_key: e for e in entities}
        assert by_key["ac_charge_start_time_1"].entity_registry_enabled_default
        assert by_key["ac_charge_end_time_1"].entity_registry_enabled_default
        assert not by_key["ac_charge_start_time_2"].entity_registry_enabled_default
        assert not by_key["ac_charge_end_time_2"].entity_registry_enabled_default
        assert not by_key["ac_charge_start_time_3"].entity_registry_enabled_default
        assert not by_key["ac_charge_end_time_3"].entity_registry_enabled_default


# ── Register / cloud-parameter mapping ───────────────────────────────


class TestScheduleRegisterMapping:
    """Entity ↔ register ↔ cloud-parameter wiring."""

    def test_base_register(self):
        assert AC_CHARGE_SCHEDULE_BASE_REGISTER == 68

    @pytest.mark.parametrize(
        ("window", "is_end", "register"),
        [
            (1, False, 68),
            (1, True, 69),
            (2, False, 70),
            (2, True, 71),
            (3, False, 72),
            (3, True, 73),
        ],
    )
    def test_register_assignment(self, window, is_end, register):
        """Each window boundary maps to its packed schedule register."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, window=window, is_end=is_end)
        assert entity._register == register

    @pytest.mark.parametrize(
        ("window", "is_end", "hour_param", "minute_param"),
        [
            (1, False, "HOLD_AC_CHARGE_START_HOUR", "HOLD_AC_CHARGE_START_MINUTE"),
            (1, True, "HOLD_AC_CHARGE_END_HOUR", "HOLD_AC_CHARGE_END_MINUTE"),
            (2, False, "HOLD_AC_CHARGE_START_HOUR_1", "HOLD_AC_CHARGE_START_MINUTE_1"),
            (2, True, "HOLD_AC_CHARGE_END_HOUR_1", "HOLD_AC_CHARGE_END_MINUTE_1"),
            (3, False, "HOLD_AC_CHARGE_START_HOUR_2", "HOLD_AC_CHARGE_START_MINUTE_2"),
            (3, True, "HOLD_AC_CHARGE_END_HOUR_2", "HOLD_AC_CHARGE_END_MINUTE_2"),
        ],
    )
    def test_cloud_param_names(self, window, is_end, hour_param, minute_param):
        """Cloud params: window 1 unsuffixed, windows 2/3 suffixed _1/_2
        (live probe: FlexBOSS21_52XXXXXX78.json regs 68-73)."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, window=window, is_end=is_end)
        assert entity._cloud_hour_param == hour_param
        assert entity._cloud_minute_param == minute_param

    def test_local_alias_map_covers_all_schedule_registers(self):
        """Every schedule register has a local parameter-cache alias chain."""
        assert sorted(LOCAL_AC_CHARGE_TIME_PARAM_KEYS) == [68, 69, 70, 71, 72, 73]

    def test_unique_ids(self):
        coordinator = _mock_coordinator()
        start1 = _entity(coordinator, window=1, is_end=False)
        end3 = _entity(coordinator, window=3, is_end=True)
        assert start1._attr_unique_id == (
            "flexboss21_1234567890_ac_charge_start_time_1"
        )
        assert end3._attr_unique_id == "flexboss21_1234567890_ac_charge_end_time_3"

    def test_translation_key_only_no_attr_name(self):
        """Names come from translation_key; _attr_name must stay unset (#262)."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator)
        assert entity._attr_translation_key == "ac_charge_start_time_1"
        assert getattr(entity, "_attr_name", None) is None


# ── Packed round-trip (byte order) ───────────────────────────────────


class TestPackedTimeRoundTrip:
    """Packed format: hour low byte | minute high byte (pylxpweb pack_time)."""

    @pytest.mark.parametrize(
        ("hour", "minute", "packed"),
        [
            (0, 0, 0),  # 00:00
            (23, 59, (59 << 8) | 23),  # 23:59 = 15127
            (23, 30, 7703),  # pylxpweb doc example
            (8, 0, 8),  # 08:00 — hour in LOW byte
            (0, 30, 30 << 8),  # 00:30 — minute in HIGH byte
        ],
    )
    def test_round_trip(self, hour, minute, packed):
        from pylxpweb.constants import pack_time, unpack_time

        assert pack_time(hour, minute) == packed
        assert unpack_time(packed) == (hour, minute)


# ── native_value: LOCAL (raw packed cache) ───────────────────────────


class TestNativeValueLocalRaw:
    """LOCAL/HYBRID-with-transport: unpack raw packed register values."""

    def test_start_time_1_from_packed_reg_68(self):
        """Reg 68's packed value surfaces under pylxpweb's legacy alias."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(8, 0)

    def test_end_time_1_from_packed_reg_69(self):
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_MINUTE_1": _pack(20, 0)},
        )
        entity = _entity(coordinator, window=1, is_end=True)
        assert entity.native_value == time(20, 0)

    def test_start_time_3_from_packed_reg_72_enable_alias(self):
        """Reg 72 (window 3 start) hides under the misnamed ENABLE_1 alias."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_ENABLE_1": _pack(22, 15)},
        )
        entity = _entity(coordinator, window=3, is_end=False)
        assert entity.native_value == time(22, 15)

    def test_end_time_3_from_packed_reg_73_enable_alias(self):
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_ENABLE_2": _pack(23, 59)},
        )
        entity = _entity(coordinator, window=3, is_end=True)
        assert entity.native_value == time(23, 59)

    def test_plain_register_address_fallback_key(self):
        """A future pylxpweb that drops the aliases surfaces "68" instead."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"68": _pack(6, 45)},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(6, 45)

    def test_hybrid_transport_uses_local_raw_branch(self):
        """HYBRID with an attached transport also holds raw packed values."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(23, 30)},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(23, 30)

    def test_garbage_packed_value_yields_none(self):
        """Minute byte > 59 (corrupt read) must not raise or mislead."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": (99 << 8) | 8},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value is None

    def test_boolean_cache_value_is_skipped(self):
        """A bool (bit-field style decode) is never a packed time."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_ENABLE_1": True},
        )
        entity = _entity(coordinator, window=3, is_end=False)
        assert entity.native_value is None

    def test_missing_parameter_yields_none(self):
        coordinator = _mock_coordinator(local_only=True, parameters={})
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value is None


# ── native_value: CLOUD (separated hour/minute params) ──────────────


class TestNativeValueCloud:
    """CLOUD (and legacy flat HYBRID): separate *_HOUR / *_MINUTE params."""

    def test_start_time_1_from_cloud_strings(self):
        """Cloud returns zero-padded strings ("08"/"00")."""
        coordinator = _mock_coordinator(
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "08",
                "HOLD_AC_CHARGE_START_MINUTE": "00",
            },
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(8, 0)

    def test_end_time_2_from_cloud_ints(self):
        coordinator = _mock_coordinator(
            parameters={
                "HOLD_AC_CHARGE_END_HOUR_1": 20,
                "HOLD_AC_CHARGE_END_MINUTE_1": 30,
            },
        )
        entity = _entity(coordinator, window=2, is_end=True)
        assert entity.native_value == time(20, 30)

    def test_missing_minute_param_yields_none(self):
        coordinator = _mock_coordinator(
            parameters={"HOLD_AC_CHARGE_START_HOUR": "08"},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value is None

    def test_out_of_range_cloud_value_yields_none(self):
        coordinator = _mock_coordinator(
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "25",
                "HOLD_AC_CHARGE_START_MINUTE": "00",
            },
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value is None

    def test_non_numeric_cloud_value_yields_none(self):
        coordinator = _mock_coordinator(
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "garbage",
                "HOLD_AC_CHARGE_START_MINUTE": "00",
            },
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value is None


# ── Availability ─────────────────────────────────────────────────────


class TestAvailability:
    """Unavailable until the schedule parameter is loaded."""

    def test_unavailable_without_parameters(self):
        coordinator = _mock_coordinator(local_only=True, parameters={})
        entity = _entity(coordinator)
        assert entity.available is False

    def test_available_with_parameters(self):
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        entity = _entity(coordinator)
        assert entity.available is True

    def test_unavailable_when_coordinator_failed(self):
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.last_update_success = False
        entity = _entity(coordinator)
        assert entity.available is False


# ── Write paths ──────────────────────────────────────────────────────


class TestWritePaths:
    """LOCAL packed register write; CLOUD named hour/minute writes."""

    @pytest.mark.asyncio
    async def test_local_write_packs_hour_low_minute_high(self):
        """LOCAL: one packed write to the window's register."""
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(6, 30))

        coordinator.write_register.assert_awaited_once_with(
            68, (30 << 8) | 6, serial="1234567890"
        )
        coordinator.refresh_all_device_parameters.assert_awaited()
        coordinator.client.api.control.write_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_local_write_window_3_end_register_73(self):
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, window=3, is_end=True)
        _prep(entity)

        await entity.async_set_value(time(23, 59))

        coordinator.write_register.assert_awaited_once_with(
            73, (59 << 8) | 23, serial="1234567890"
        )

    @pytest.mark.asyncio
    async def test_cloud_write_sends_named_hour_and_minute(self):
        """CLOUD: two named-parameter writes (the portal's own params)."""
        coordinator = _mock_coordinator(has_local=False)
        entity = _entity(coordinator, window=1, is_end=True)
        _prep(entity)

        await entity.async_set_value(time(20, 0))

        calls = coordinator.client.api.control.write_parameter.await_args_list
        assert [c.args for c in calls] == [
            ("1234567890", "HOLD_AC_CHARGE_END_HOUR", "20"),
            ("1234567890", "HOLD_AC_CHARGE_END_MINUTE", "0"),
        ]
        coordinator.write_register.assert_not_awaited()
        coordinator.refresh_all_device_parameters.assert_awaited()

    @pytest.mark.asyncio
    async def test_cloud_write_window_2_suffixed_params(self):
        coordinator = _mock_coordinator(has_local=False)
        entity = _entity(coordinator, window=2, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(1, 5))

        calls = coordinator.client.api.control.write_parameter.await_args_list
        assert [c.args for c in calls] == [
            ("1234567890", "HOLD_AC_CHARGE_START_HOUR_1", "1"),
            ("1234567890", "HOLD_AC_CHARGE_START_MINUTE_1", "5"),
        ]

    @pytest.mark.asyncio
    async def test_cloud_write_failure_raises(self):
        coordinator = _mock_coordinator(has_local=False)
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.write_parameter = AsyncMock(return_value=failed)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_value(time(8, 0))

    @pytest.mark.asyncio
    async def test_no_transport_and_no_client_raises(self):
        coordinator = _mock_coordinator(has_local=False, has_client=False)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_value(time(8, 0))

    @pytest.mark.asyncio
    async def test_midnight_crossing_end_before_start_is_allowed(self):
        """Overnight windows (end < start, e.g. 20:00→08:00) are firmware-legal;
        the entities must not cross-validate the pair."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(20, 0)},
        )
        end_entity = _entity(coordinator, window=1, is_end=True)
        _prep(end_entity)

        await end_entity.async_set_value(time(8, 0))

        coordinator.write_register.assert_awaited_once_with(69, 8, serial="1234567890")

    @pytest.mark.asyncio
    async def test_optimistic_value_during_write(self):
        """The UI shows the target value while the write is in flight."""
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        seen: list[time | None] = []

        async def _capture(*args, **kwargs):
            seen.append(entity.native_value)
            return True

        coordinator.write_register = AsyncMock(side_effect=_capture)

        await entity.async_set_value(time(7, 15))

        assert seen == [time(7, 15)]
        # cleared after the write completes
        assert entity._optimistic_value is None

    @pytest.mark.asyncio
    async def test_seconds_are_dropped(self):
        """Registers store hour/minute only; seconds must not leak into packing."""
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(6, 30, 45))

        coordinator.write_register.assert_awaited_once_with(
            68, (30 << 8) | 6, serial="1234567890"
        )


# ── Failure convergence (PR #283 review P1/P2) ───────────────────────


class TestWriteFailureConvergence:
    """Partial cloud writes and failed refreshes must not hide device state."""

    @pytest.mark.asyncio
    async def test_cloud_partial_failure_refreshes_and_shows_device_state(self):
        """P1: hour write succeeds, minute write fails.

        The device now holds hour=new/minute=old. A best-effort parameter
        refresh must run BEFORE the error propagates, and the entity must
        reflect the refreshed (mixed) value — not the stale pre-write value
        and not the optimistic target.
        """
        serial = "1234567890"
        coordinator = _mock_coordinator(
            has_local=False,
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "8",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            },
        )

        ok = MagicMock()
        ok.success = True
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.write_parameter = AsyncMock(
            side_effect=[ok, failed]
        )

        async def _refresh_mixed(*args, **kwargs):
            # Device truth after the partial write: hour landed, minute not.
            coordinator.data["parameters"][serial] = {
                "HOLD_AC_CHARGE_START_HOUR": "20",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            }

        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=_refresh_mixed
        )

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await entity.async_set_value(time(20, 30))

        coordinator.refresh_all_device_parameters.assert_awaited()
        # Optimistic dropped; entity shows the re-read (mixed) device state.
        assert entity._optimistic_value is None
        assert entity.native_value == time(20, 0)

    @pytest.mark.asyncio
    async def test_cloud_partial_failure_on_exception_refreshes(self):
        """P1: a raised exception on the minute write converges the same way."""
        serial = "1234567890"
        coordinator = _mock_coordinator(
            has_local=False,
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "8",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            },
        )

        ok = MagicMock()
        ok.success = True
        coordinator.client.api.control.write_parameter = AsyncMock(
            side_effect=[ok, ConnectionError("boom")]
        )

        async def _refresh_mixed(*args, **kwargs):
            coordinator.data["parameters"][serial] = {
                "HOLD_AC_CHARGE_START_HOUR": "20",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            }

        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=_refresh_mixed
        )

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await entity.async_set_value(time(20, 30))

        coordinator.refresh_all_device_parameters.assert_awaited()
        assert entity._optimistic_value is None
        assert entity.native_value == time(20, 0)

    @pytest.mark.asyncio
    async def test_cloud_first_write_failure_does_not_refresh(self):
        """A failed FIRST write changed nothing on the device: no refresh,
        no "partially applied" wording, entity keeps the cached value."""
        coordinator = _mock_coordinator(
            has_local=False,
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "8",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            },
        )
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.write_parameter = AsyncMock(return_value=failed)

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError) as excinfo:
            await entity.async_set_value(time(20, 30))

        assert "partially applied" not in str(excinfo.value)
        coordinator.refresh_all_device_parameters.assert_not_awaited()
        assert entity._optimistic_value is None
        assert entity.native_value == time(8, 0)

    @pytest.mark.asyncio
    async def test_write_success_refresh_failure_retains_optimistic(self):
        """P2: the write landed on the device but the follow-up refresh died.

        Clearing the optimistic value would make the UI "revert" to the stale
        cached time even though hardware changed — keep the optimistic value.
        """
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=Exception("refresh died")
        )

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        # Write succeeds; refresh failure is logged, not raised.
        await entity.async_set_value(time(7, 15))

        coordinator.write_register.assert_awaited_once()
        assert entity._optimistic_value == time(7, 15)
        assert entity.native_value == time(7, 15)
        assert entity.available is True

    @pytest.mark.asyncio
    async def test_retained_optimistic_clears_when_cache_converges(self):
        """Retained optimistic value clears once fresh data shows the write."""
        serial = "1234567890"
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=Exception("refresh died")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(7, 15))
        assert entity._optimistic_value == time(7, 15)

        # A later successful parameter poll delivers the written value.
        coordinator.data["parameters"][serial] = {
            "HOLD_AC_CHARGE_START_HOUR_1": _pack(7, 15)
        }
        entity._handle_coordinator_update()

        assert entity._optimistic_value is None
        assert entity.native_value == time(7, 15)

    @pytest.mark.asyncio
    async def test_retained_optimistic_clears_on_other_fresh_value(self):
        """Fresh data with a DIFFERENT time (portal change) also clears it."""
        serial = "1234567890"
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=Exception("refresh died")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(7, 15))

        coordinator.data["parameters"][serial] = {
            "HOLD_AC_CHARGE_START_HOUR_1": _pack(21, 45)
        }
        entity._handle_coordinator_update()

        assert entity._optimistic_value is None
        assert entity.native_value == time(21, 45)

    @pytest.mark.asyncio
    async def test_retained_optimistic_survives_stale_coordinator_ticks(self):
        """Coordinator updates that still carry the stale pre-write value
        must NOT clear the retained optimistic value (that would be the
        P2 revert, just delayed one poll tick)."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.refresh_all_device_parameters = AsyncMock(
            side_effect=Exception("refresh died")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(7, 15))

        # Params cache unchanged (stale) — optimistic must survive the tick.
        entity._handle_coordinator_update()

        assert entity._optimistic_value == time(7, 15)
        assert entity.native_value == time(7, 15)

    @pytest.mark.asyncio
    async def test_local_write_failure_clears_optimistic(self):
        """A failed LOCAL write (single register, no partial state) drops the
        optimistic value and keeps the cached time."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.write_register = AsyncMock(
            side_effect=HomeAssistantError("write failed")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_value(time(7, 15))

        assert entity._optimistic_value is None
        assert entity.native_value == time(8, 0)
