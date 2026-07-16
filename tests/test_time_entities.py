"""Tests for the EG4 time platform (schedule windows, issues #277 + #295).

Seven packed-time schedule families share one data-driven implementation
(``SCHEDULE_TIME_TYPES`` in const/modbus.py):

Classic (3 windows, cloud params ``{prefix}_{START|END}_{HOUR|MINUTE}{suffix}``,
window 1 unsuffixed / 2-3 ``_1``/``_2``):

- AC Charge      — regs 68-73  (#277), all control-capable families
- AC First       — regs 152-157 (#295), EG4_OFFGRID (SNA) only
- Forced Charge  — regs 76-81  (#295), control-capable grid-tied families
  (EG4_OFFGRID cloud-rejects the writes — REMOTE_SET_ERROR, #295 live report)
- Forced Discharge — regs 84-89 (#295), control-capable grid-tied families

writeTime (all windows suffixed ``_1..._N``, atomic ``write_time_parameter``
cloud writes; pylxpweb PR #209):

- Peak Shaving   — regs 209-212, 2 windows, EG4_HYBRID only (cloud reads via
  interleaved ``LSP_HOLD_DIS_CHG_POWER_TIME_{n}`` params)
- Generator Charge — regs 256-259, 2 windows, EG4_HYBRID or EG4_OFFGRID
- Off-Grid       — regs 269-274, 3 windows, EG4_HYBRID only

Each 16-bit register packs hour (low byte) | minute (high byte) — verified by
the live cloud register probes in pylxpweb docs/inverters/. Every schedule time
entity is registry-disabled by default (opt-in advanced feature).
"""

from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    AC_CHARGE_SCHEDULE_BASE_REGISTER,
    LOCAL_AC_CHARGE_TIME_PARAM_KEYS,
    SCHEDULE_TIME_TYPES,
    ScheduleTimeSpec,
)
from custom_components.eg4_web_monitor.time import (
    EG4ScheduleTimeEntity,
    async_setup_entry,
)
from tests.conftest import wire_coordinator_write_helpers

SCHEDULE_KEYS = tuple(spec.key for spec in SCHEDULE_TIME_TYPES)


def _spec(key: str) -> ScheduleTimeSpec:
    return next(spec for spec in SCHEDULE_TIME_TYPES if spec.key == key)


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
    coordinator.has_http_api = MagicMock(return_value=has_client)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock()
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
        client.api.control.write_time_parameter = AsyncMock(return_value=write_result)
        coordinator.client = client
    else:
        coordinator.client = None

    wire_coordinator_write_helpers(coordinator)
    return coordinator


def _entity(
    coordinator: MagicMock,
    *,
    serial: str = "1234567890",
    schedule: str = "ac_charge",
    window: int = 1,
    is_end: bool = False,
) -> EG4ScheduleTimeEntity:
    return EG4ScheduleTimeEntity(
        coordinator, serial, _spec(schedule), window, is_end=is_end
    )


def _prep(entity: EG4ScheduleTimeEntity) -> None:
    """Prepare entity for async action tests (set hass + entity_id)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "time.test_entity"
    entity.platform = None  # type: ignore[assignment]
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]


def _pack(hour: int, minute: int) -> int:
    """Packed register encoding: hour low byte, minute high byte."""
    return (hour & 0xFF) | ((minute & 0xFF) << 8)


async def _setup_keys(hass, coordinator) -> set[str]:
    """Run async_setup_entry and return the created translation keys."""
    entry = MagicMock()
    entry.runtime_data = coordinator
    entities = []
    await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))
    return {e._attr_translation_key for e in entities}


def _expected_keys(*schedules: str) -> set[str]:
    """Translation keys for the given schedules, respecting each family's
    window count (classic = 3, Generator/Peak Shaving = 2, Off-Grid = 3)."""
    return {
        f"{schedule}_{boundary}_time_{window}"
        for schedule in schedules
        for boundary in ("start", "end")
        for window in range(1, _spec(schedule).windows + 1)
    }


# ── Schedule table (drift guards) ────────────────────────────────────


class TestScheduleTable:
    """The declarative table is the single source of schedule truth."""

    def test_expected_schedule_types(self):
        assert SCHEDULE_KEYS == (
            "ac_charge",
            "ac_first",
            "forced_charge",
            "forced_discharge",
            "peak_shaving",
            "gen_charge",
            "off_grid",
        )

    @pytest.mark.parametrize(
        (
            "key",
            "cloud_prefix",
            "base_register",
            "gate",
            "windows",
            "bare",
            "wt",
            "lsp",
        ),
        [
            ("ac_charge", "HOLD_AC_CHARGE", 68, "control", 3, True, False, None),
            ("ac_first", "HOLD_AC_FIRST", 152, "offgrid", 3, True, False, None),
            (
                "forced_charge",
                "HOLD_FORCED_CHARGE",
                76,
                "control_grid_tied",
                3,
                True,
                False,
                None,
            ),
            (
                "forced_discharge",
                "HOLD_FORCED_DISCHARGE",
                84,
                "control_grid_tied",
                3,
                True,
                False,
                None,
            ),
            ("peak_shaving", "HOLD_PEAK_SHAVING", 209, "hybrid", 2, False, True, 37),
            ("gen_charge", "HOLD_GEN", 256, "hybrid_or_offgrid", 2, False, True, None),
            ("off_grid", "HOLD_OFF_GRID", 269, "hybrid", 3, False, True, None),
        ],
    )
    def test_table_entries(
        self, key, cloud_prefix, base_register, gate, windows, bare, wt, lsp
    ):
        """Independently-derived literals: portal holdParams + register probes
        (FlexBOSS21 68-73/209-212/256-259, SNA12K-US blocks 106-111 → 152-157),
        the EG4-18KPV Modbus spec (76-81 / 84-89), and pylxpweb PR #209
        (209-212 / 256-259 / 269-274)."""
        spec = _spec(key)
        assert spec.cloud_prefix == cloud_prefix
        assert spec.base_register == base_register
        assert spec.gate == gate
        assert spec.windows == windows
        assert spec.bare_first_window is bare
        assert spec.write_via_time_api is wt
        assert spec.read_lsp_base == lsp

    def test_table_matches_pylxpweb_schedule_configs(self):
        """Drift guard: the integration table must agree with pylxpweb's
        SCHEDULE_CONFIGS wherever the installed pylxpweb knows the type.

        Newer types ship in later pylxpweb releases; on older versions only the
        integration-side literals above pin their layout, so a type missing
        from ``ScheduleType`` is skipped (not a failure).
        """
        from pylxpweb.constants import SCHEDULE_CONFIGS, ScheduleType

        checked = 0
        for spec in SCHEDULE_TIME_TYPES:
            try:
                schedule_type = ScheduleType(spec.key)
            except ValueError:
                continue
            config = SCHEDULE_CONFIGS[schedule_type]
            assert config.cloud_prefix == spec.cloud_prefix, spec.key
            assert config.base_register == spec.base_register, spec.key
            assert config.periods == spec.windows, spec.key
            assert config.write_via_time_api == spec.write_via_time_api, spec.key
            assert config.read_lsp_base == spec.read_lsp_base, spec.key
            # bare-first-window ⇔ pylxpweb's first period suffix is "".
            assert (config.period_suffixes[0] == "") == spec.bare_first_window, spec.key
            checked += 1
        assert checked >= 4

    def test_register_blocks_do_not_overlap(self):
        merged: set[int] = set()
        for spec in SCHEDULE_TIME_TYPES:
            block = set(
                range(spec.base_register, spec.base_register + 2 * spec.windows)
            )
            assert not (merged & block), spec.key
            merged |= block

    @pytest.mark.parametrize("key", SCHEDULE_KEYS)
    def test_local_alias_map_covers_all_registers(self, key):
        """Every schedule register (2 × windows) has a local parameter-cache
        alias chain ending in the plain register-address fallback."""
        spec = _spec(key)
        expected_registers = [
            spec.base_register + offset for offset in range(2 * spec.windows)
        ]
        assert sorted(spec.local_param_keys) == expected_registers
        for register, chain in spec.local_param_keys.items():
            assert chain[-1] == str(register)

    def test_ac_charge_spec_keeps_stale_alias_chains(self):
        """AC charge keeps the pylxpweb stale-name chains (zero churn)."""
        assert _spec("ac_charge").local_param_keys is LOCAL_AC_CHARGE_TIME_PARAM_KEYS
        assert AC_CHARGE_SCHEDULE_BASE_REGISTER == 68

    @pytest.mark.parametrize(
        ("key", "register", "primary"),
        [
            ("forced_charge", 76, "HOLD_FORCED_CHARGE_TIME_0_START"),
            ("forced_charge", 81, "HOLD_FORCED_CHARGE_TIME_2_END"),
            ("forced_discharge", 84, "HOLD_FORCED_DISCHARGE_TIME_0_START"),
            ("forced_discharge", 89, "HOLD_FORCED_DISCHARGE_TIME_2_END"),
            ("ac_first", 152, "HOLD_AC_FIRST_TIME_0_START"),
            ("ac_first", 157, "HOLD_AC_FIRST_TIME_2_END"),
            ("peak_shaving", 209, "HOLD_PEAK_SHAVING_TIME_0_START"),
            ("peak_shaving", 212, "HOLD_PEAK_SHAVING_TIME_1_END"),
            ("gen_charge", 256, "HOLD_GEN_TIME_0_START"),
            ("gen_charge", 259, "HOLD_GEN_TIME_1_END"),
            ("off_grid", 269, "HOLD_OFF_GRID_TIME_0_START"),
            ("off_grid", 274, "HOLD_OFF_GRID_TIME_2_END"),
        ],
    )
    def test_canonical_local_alias_chains(self, key, register, primary):
        """New schedule types surface under pylxpweb's canonical packed
        names, with the raw register-address string as fallback."""
        assert _spec(key).local_param_keys[register] == (primary, str(register))


# ── Platform registration ────────────────────────────────────────────


class TestTimePlatformRegistration:
    """The time platform must be forwarded on setup and unloaded."""

    def test_time_platform_in_platforms(self):
        """Platform.TIME is registered for setup and unload."""
        from homeassistant.const import Platform

        from custom_components.eg4_web_monitor import OTHER_PLATFORMS, PLATFORMS

        assert Platform.TIME in OTHER_PLATFORMS
        assert Platform.TIME in PLATFORMS


# ── Platform setup / family gating ───────────────────────────────────


class TestTimePlatformSetup:
    """Entity creation per device/family."""

    @pytest.mark.asyncio
    async def test_setup_control_capable_model(self, hass):
        """A supported grid-tied model (no detected family) gets AC charge,
        forced charge and forced discharge — 18 entities — but NOT AC First
        (which needs positive EG4_OFFGRID identification)."""
        coordinator = _mock_coordinator()

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys("ac_charge", "forced_charge", "forced_discharge")

    @pytest.mark.asyncio
    async def test_setup_sna_offgrid_family(self, hass):
        """EG4_OFFGRID (the reporter's SNA-US class hardware): AC First is
        created; forced discharge is suppressed (#197/#220 adjudication);
        forced charge is suppressed too (cloud REMOTE_SET_ERROR on a
        12000XP v2 + zero HOLD_FORCED_CHARGE params on the SNA portal page,
        #295 live report); Generator charge is created (hybrid_or_offgrid
        gate — regs 256-259 carry gen params on the SNA12K-US probe); Peak
        Shaving/Off-Grid are EG4_HYBRID-only, so absent."""
        coordinator = _mock_coordinator(model="SNA-US 15K")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys("ac_charge", "ac_first", "gen_charge")

    @pytest.mark.asyncio
    async def test_offgrid_repairs_issue_for_registered_forced_charge_time(self, hass):
        """A previously-registered Forced Charge time entity (beta.20/21
        created them on EG4_OFFGRID) raises the one-shot Repairs issue."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        registry = er.async_get(hass)
        registry.async_get_or_create(
            "time", DOMAIN, f"12000xp_{serial}_forced_charge_start_time_1"
        )

        coordinator = _mock_coordinator(model="12000XP")
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }

        await _setup_keys(hass, coordinator)

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_forced_charge_times_removed_{serial}"
        )
        assert issue is not None

    @pytest.mark.asyncio
    async def test_offgrid_no_repairs_issue_without_registered_entity(self, hass):
        """No Forced Charge time entity in the registry → no Repairs issue
        (schedule entities are disabled-by-default; most users never had one)."""
        from homeassistant.helpers import issue_registry as ir

        from custom_components.eg4_web_monitor.const import DOMAIN

        serial = "1234567890"
        coordinator = _mock_coordinator(model="12000XP")
        coordinator.data["devices"][serial]["features"] = {
            "inverter_family": "EG4_OFFGRID"
        }

        await _setup_keys(hass, coordinator)

        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"offgrid_forced_charge_times_removed_{serial}"
        )
        assert issue is None

    @pytest.mark.asyncio
    async def test_setup_hybrid_family_gets_writetime_families(self, hass):
        """EG4_HYBRID gets the grid-tied classic set plus all three writeTime
        families (Peak Shaving/Generator/Off-Grid); no AC First (SNA-only)."""
        coordinator = _mock_coordinator(model="Mystery Model")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_HYBRID"
        }

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys(
            "ac_charge",
            "forced_charge",
            "forced_discharge",
            "peak_shaving",
            "gen_charge",
            "off_grid",
        )

    @pytest.mark.asyncio
    async def test_setup_lxp_family_no_writetime_families(self, hass):
        """LXP gets only the classic grid-tied set — the writeTime families
        were not verified on LXP, so they fail closed (no AC First either)."""
        coordinator = _mock_coordinator(model="Mystery Model")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "LXP"
        }

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys("ac_charge", "forced_charge", "forced_discharge")

    @pytest.mark.asyncio
    async def test_setup_offgrid_model_without_family_features(self, hass):
        """A 12000XP model string WITHOUT detected features is control-capable
        but not positively EG4_OFFGRID/HYBRID: no AC First / writeTime families
        (all fail closed on unknown family), forced charge and forced
        discharge stay (suppression also needs positive identification)."""
        coordinator = _mock_coordinator(model="12000XP")

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys("ac_charge", "forced_charge", "forced_discharge")

    @pytest.mark.asyncio
    async def test_setup_unsupported_model_creates_nothing(self, hass):
        """Unknown model with no detected family gets no control entities."""
        coordinator = _mock_coordinator(model="Mystery Model")

        assert await _setup_keys(hass, coordinator) == set()

    @pytest.mark.asyncio
    async def test_setup_skips_non_inverter_devices(self, hass):
        """GridBOSS/MID devices have no inverter schedules."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"] = {
            "gb123": {"type": "gridboss", "model": "GridBOSS"}
        }

        assert await _setup_keys(hass, coordinator) == set()

    @pytest.mark.asyncio
    async def test_all_schedule_entities_disabled_by_default(self, hass):
        """Every schedule time entity — classic and writeTime families, every
        window (window 1 included) — is registry-disabled by default (opt-in
        advanced feature; users who enabled a window keep it via the registry)."""
        coordinator = _mock_coordinator(model="FlexBOSS21")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_HYBRID"
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert entities  # sanity: the hybrid device produced schedule entities
        for entity in entities:
            assert entity.entity_registry_enabled_default is False, (
                entity._attr_translation_key
            )


# ── Register / cloud-parameter mapping ───────────────────────────────


class TestScheduleRegisterMapping:
    """Entity ↔ register ↔ cloud-parameter wiring."""

    @pytest.mark.parametrize(
        ("schedule", "base"),
        [
            ("ac_charge", 68),
            ("ac_first", 152),
            ("forced_charge", 76),
            ("forced_discharge", 84),
        ],
    )
    @pytest.mark.parametrize(
        ("window", "is_end", "offset"),
        [
            (1, False, 0),
            (1, True, 1),
            (2, False, 2),
            (2, True, 3),
            (3, False, 4),
            (3, True, 5),
        ],
    )
    def test_register_assignment(self, schedule, base, window, is_end, offset):
        """Each window boundary maps to its packed schedule register."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        assert entity._register == base + offset

    @pytest.mark.parametrize(
        "schedule", ("ac_charge", "ac_first", "forced_charge", "forced_discharge")
    )
    @pytest.mark.parametrize(
        ("window", "is_end", "suffix"),
        [
            (1, False, ""),
            (1, True, ""),
            (2, False, "_1"),
            (2, True, "_1"),
            (3, False, "_2"),
            (3, True, "_2"),
        ],
    )
    def test_cloud_param_names(self, schedule, window, is_end, suffix):
        """Classic cloud params: window 1 unsuffixed, windows 2/3 suffixed
        _1/_2 (portal holdParam convention, live probes)."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        prefix = _spec(schedule).cloud_prefix
        boundary = "END" if is_end else "START"
        assert entity._cloud_hour_param == f"{prefix}_{boundary}_HOUR{suffix}"
        assert entity._cloud_minute_param == f"{prefix}_{boundary}_MINUTE{suffix}"

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "hour_param", "minute_param", "time_param"),
        [
            # writeTime families number ALL windows _1.._N (no bare window).
            (
                "gen_charge",
                1,
                False,
                "HOLD_GEN_START_HOUR_1",
                "HOLD_GEN_START_MINUTE_1",
                "HOLD_GEN_START_TIME_1",
            ),
            (
                "gen_charge",
                2,
                True,
                "HOLD_GEN_END_HOUR_2",
                "HOLD_GEN_END_MINUTE_2",
                "HOLD_GEN_END_TIME_2",
            ),
            (
                "off_grid",
                3,
                False,
                "HOLD_OFF_GRID_START_HOUR_3",
                "HOLD_OFF_GRID_START_MINUTE_3",
                "HOLD_OFF_GRID_START_TIME_3",
            ),
        ],
    )
    def test_writetime_cloud_param_names(
        self, schedule, window, is_end, hour_param, minute_param, time_param
    ):
        """Generator/Off-Grid: one-based window suffixes + the composite
        writeTime param used for atomic cloud writes."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        assert entity._cloud_hour_param == hour_param
        assert entity._cloud_minute_param == minute_param
        assert entity._cloud_time_param == time_param

    @pytest.mark.parametrize(
        ("window", "is_end", "lsp_hour", "lsp_minute"),
        [
            (1, False, 37, 38),
            (1, True, 39, 40),
            (2, False, 41, 42),
            (2, True, 43, 44),
        ],
    )
    def test_peak_shaving_lsp_read_param_names(
        self, window, is_end, lsp_hour, lsp_minute
    ):
        """Peak Shaving reads back under the interleaved LSP params
        (37/38 = start1 h/m, 39/40 = end1, 41/42 = start2, 43/44 = end2)."""
        coordinator = _mock_coordinator()
        entity = _entity(
            coordinator, schedule="peak_shaving", window=window, is_end=is_end
        )
        assert entity._cloud_hour_param == f"LSP_HOLD_DIS_CHG_POWER_TIME_{lsp_hour}"
        assert entity._cloud_minute_param == f"LSP_HOLD_DIS_CHG_POWER_TIME_{lsp_minute}"
        # Writes still use the composite writeTime param.
        boundary = "END" if is_end else "START"
        assert entity._cloud_time_param == f"HOLD_PEAK_SHAVING_{boundary}_TIME_{window}"

    def test_unique_ids(self):
        """AC charge unique_ids stay exactly as shipped in #277 (zero churn);
        new schedules follow the same pattern."""
        coordinator = _mock_coordinator()
        assert (
            _entity(coordinator, window=1)._attr_unique_id
            == "flexboss21_1234567890_ac_charge_start_time_1"
        )
        assert (
            _entity(coordinator, window=3, is_end=True)._attr_unique_id
            == "flexboss21_1234567890_ac_charge_end_time_3"
        )
        assert (
            _entity(coordinator, schedule="ac_first", window=2)._attr_unique_id
            == "flexboss21_1234567890_ac_first_start_time_2"
        )
        assert (
            _entity(
                coordinator, schedule="forced_discharge", window=1, is_end=True
            )._attr_unique_id
            == "flexboss21_1234567890_forced_discharge_end_time_1"
        )

    @pytest.mark.parametrize("schedule", SCHEDULE_KEYS)
    def test_translation_key_only_no_attr_name(self, schedule):
        """Names come from translation_key; _attr_name must stay unset (#262)."""
        coordinator = _mock_coordinator()
        entity = _entity(coordinator, schedule=schedule)
        assert entity._attr_translation_key == f"{schedule}_start_time_1"
        assert getattr(entity, "_attr_name", None) is None

    def test_translation_keys_exist_in_strings_json(self):
        """Every schedule/boundary/window translation key is defined."""
        import json
        from pathlib import Path

        strings = json.loads(
            (Path("custom_components/eg4_web_monitor") / "strings.json").read_text()
        )
        time_keys = strings["entity"]["time"]
        for key in _expected_keys(*SCHEDULE_KEYS):
            assert key in time_keys, key


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

    def test_ac_charge_start_1_from_packed_reg_68(self):
        """Reg 68's packed value surfaces under pylxpweb's legacy alias."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(8, 0)

    def test_ac_charge_start_3_from_packed_reg_72_enable_alias(self):
        """Reg 72 (window 3 start) hides under the misnamed ENABLE_1 alias."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_ENABLE_1": _pack(22, 15)},
        )
        entity = _entity(coordinator, window=3, is_end=False)
        assert entity.native_value == time(22, 15)

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "param"),
        [
            ("forced_charge", 1, False, "HOLD_FORCED_CHARGE_TIME_0_START"),
            ("forced_charge", 3, True, "HOLD_FORCED_CHARGE_TIME_2_END"),
            ("forced_discharge", 1, False, "HOLD_FORCED_DISCHARGE_TIME_0_START"),
            ("forced_discharge", 2, True, "HOLD_FORCED_DISCHARGE_TIME_1_END"),
            ("ac_first", 1, False, "HOLD_AC_FIRST_TIME_0_START"),
            ("ac_first", 3, True, "HOLD_AC_FIRST_TIME_2_END"),
        ],
    )
    def test_canonical_named_packed_values(self, schedule, window, is_end, param):
        """New schedule registers surface under pylxpweb's canonical names."""
        coordinator = _mock_coordinator(
            local_only=True, parameters={param: _pack(21, 45)}
        )
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        assert entity.native_value == time(21, 45)

    @pytest.mark.parametrize(
        ("schedule", "register"),
        [
            ("ac_charge", "68"),
            ("ac_first", "152"),
            ("forced_charge", "76"),
            ("forced_discharge", "84"),
        ],
    )
    def test_plain_register_address_fallback_key(self, schedule, register):
        """A pylxpweb without the name mapping surfaces the raw address key
        (the shipped 0.9.36b21 behaviour for 84-89 and 152-157)."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={register: _pack(6, 45)},
        )
        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
        assert entity.native_value == time(6, 45)

    def test_hybrid_transport_uses_local_raw_branch(self):
        """HYBRID with an attached transport also holds raw packed values."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(23, 30)},
        )
        entity = _entity(coordinator, window=1, is_end=False)
        assert entity.native_value == time(23, 30)

    @pytest.mark.parametrize("schedule", SCHEDULE_KEYS)
    def test_garbage_packed_value_yields_none(self, schedule):
        """Minute byte > 59 (corrupt read) must not raise or mislead."""
        spec = _spec(schedule)
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={str(spec.base_register): (99 << 8) | 8},
        )
        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
        assert entity.native_value is None

    def test_boolean_cache_value_is_skipped(self):
        """A bool (bit-field style decode) is never a packed time."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_ENABLE_1": True},
        )
        entity = _entity(coordinator, window=3, is_end=False)
        assert entity.native_value is None

    @pytest.mark.parametrize("schedule", SCHEDULE_KEYS)
    def test_missing_parameter_yields_none(self, schedule):
        coordinator = _mock_coordinator(local_only=True, parameters={})
        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
        assert entity.native_value is None


# ── native_value: CLOUD (separated hour/minute params) ──────────────


class TestNativeValueCloud:
    """CLOUD (and legacy flat HYBRID): separate *_HOUR / *_MINUTE params."""

    @pytest.mark.parametrize(
        ("schedule", "hour_param", "minute_param"),
        [
            ("ac_charge", "HOLD_AC_CHARGE_START_HOUR", "HOLD_AC_CHARGE_START_MINUTE"),
            ("ac_first", "HOLD_AC_FIRST_START_HOUR", "HOLD_AC_FIRST_START_MINUTE"),
            (
                "forced_charge",
                "HOLD_FORCED_CHARGE_START_HOUR",
                "HOLD_FORCED_CHARGE_START_MINUTE",
            ),
            (
                "forced_discharge",
                "HOLD_FORCED_DISCHARGE_START_HOUR",
                "HOLD_FORCED_DISCHARGE_START_MINUTE",
            ),
        ],
    )
    def test_start_time_1_from_cloud_strings(self, schedule, hour_param, minute_param):
        """Cloud returns zero-padded strings ("08"/"00")."""
        coordinator = _mock_coordinator(
            parameters={hour_param: "08", minute_param: "00"},
        )
        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
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
                "HOLD_AC_FIRST_START_HOUR": "25",
                "HOLD_AC_FIRST_START_MINUTE": "00",
            },
        )
        entity = _entity(coordinator, schedule="ac_first", window=1, is_end=False)
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

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "register"),
        [
            ("ac_charge", 1, False, 68),
            ("ac_charge", 3, True, 73),
            ("ac_first", 1, False, 152),
            ("ac_first", 2, True, 155),
            ("forced_charge", 1, False, 76),
            ("forced_charge", 3, False, 80),
            ("forced_discharge", 1, True, 85),
            ("forced_discharge", 3, True, 89),
        ],
    )
    @pytest.mark.asyncio
    async def test_local_write_packs_hour_low_minute_high(
        self, schedule, window, is_end, register
    ):
        """LOCAL: one packed write to the window's register."""
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        _prep(entity)

        await entity.async_set_value(time(6, 30))

        coordinator.write_register.assert_awaited_once_with(
            register, (30 << 8) | 6, serial="1234567890"
        )
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(
            "1234567890"
        )
        coordinator.client.api.control.write_parameter.assert_not_awaited()

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "hour_param", "minute_param"),
        [
            (
                "ac_charge",
                1,
                True,
                "HOLD_AC_CHARGE_END_HOUR",
                "HOLD_AC_CHARGE_END_MINUTE",
            ),
            (
                "ac_first",
                1,
                False,
                "HOLD_AC_FIRST_START_HOUR",
                "HOLD_AC_FIRST_START_MINUTE",
            ),
            (
                "forced_charge",
                2,
                False,
                "HOLD_FORCED_CHARGE_START_HOUR_1",
                "HOLD_FORCED_CHARGE_START_MINUTE_1",
            ),
            (
                "forced_discharge",
                3,
                True,
                "HOLD_FORCED_DISCHARGE_END_HOUR_2",
                "HOLD_FORCED_DISCHARGE_END_MINUTE_2",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_cloud_write_sends_named_hour_and_minute(
        self, schedule, window, is_end, hour_param, minute_param
    ):
        """CLOUD: two named-parameter writes (the portal's own params)."""
        coordinator = _mock_coordinator(has_local=False)
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        _prep(entity)

        await entity.async_set_value(time(20, 5))

        calls = coordinator.client.api.control.write_parameter.await_args_list
        assert [c.args for c in calls] == [
            ("1234567890", hour_param, "20"),
            ("1234567890", minute_param, "5"),
        ]
        coordinator.write_register.assert_not_awaited()
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(
            "1234567890"
        )

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
    async def test_hybrid_local_write_failure_falls_back_to_cloud(self):
        """HYBRID: transport attached but the register write fails (e.g.
        transport_link_down Modbus timeout) -> the cloud named-parameter
        branch is used and the service call succeeds (switch parity)."""
        coordinator = _mock_coordinator(has_local=True)
        coordinator.write_register = AsyncMock(
            side_effect=HomeAssistantError("Failed to write register 68: timeout")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(8, 15))

        coordinator.write_register.assert_awaited_once()
        calls = coordinator.client.api.control.write_parameter.await_args_list
        assert [c.args for c in calls] == [
            ("1234567890", "HOLD_AC_CHARGE_START_HOUR", "8"),
            ("1234567890", "HOLD_AC_CHARGE_START_MINUTE", "15"),
        ]
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(
            "1234567890"
        )

    @pytest.mark.asyncio
    async def test_local_only_write_failure_still_raises(self):
        """LOCAL-only: no cloud to fall back to -> the local error propagates."""
        coordinator = _mock_coordinator(
            has_local=True, has_client=False, local_only=True
        )
        coordinator.write_register = AsyncMock(
            side_effect=HomeAssistantError("Failed to write register 68: timeout")
        )
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="register 68"):
            await entity.async_set_value(time(8, 15))

        coordinator.write_register.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hybrid_known_link_down_prefers_cloud_immediately(self):
        """HYBRID with pylxpweb reporting transport_link_down: the doomed
        local write is skipped entirely and the cloud is used directly."""
        coordinator = _mock_coordinator(has_local=True)
        coordinator.is_transport_link_down = MagicMock(return_value=True)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(20, 30))

        coordinator.write_register.assert_not_awaited()
        assert coordinator.client.api.control.write_parameter.await_count == 2

    @pytest.mark.asyncio
    async def test_link_down_write_skips_param_refresh_and_retains_optimistic(self):
        """Known-down link: the post-write parameter refresh must NOT run
        (pylxpweb's param fetch has no link gate — the local reads would
        hang, codex P1 on PR #301); the optimistic value is RETAINED — the
        acknowledged cloud write is device truth — until fresh parameter
        data arrives on link recovery."""
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.is_transport_link_down = MagicMock(return_value=True)
        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        await entity.async_set_value(time(20, 30))

        coordinator.write_register.assert_not_awaited()
        coordinator.async_refresh_device_parameters.assert_not_awaited()
        coordinator.refresh_all_device_parameters.assert_not_awaited()
        assert entity._optimistic_retained is True
        assert entity.native_value == time(20, 30)

    @pytest.mark.parametrize("schedule", SCHEDULE_KEYS)
    @pytest.mark.asyncio
    async def test_midnight_crossing_end_before_start_is_allowed(self, schedule):
        """Overnight windows (end < start, e.g. 20:00→08:00) are firmware-legal;
        the entities must not cross-validate the pair."""
        spec = _spec(schedule)
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={str(spec.base_register): _pack(20, 0)},
        )
        end_entity = _entity(coordinator, schedule=schedule, window=1, is_end=True)
        _prep(end_entity)

        await end_entity.async_set_value(time(8, 0))

        coordinator.write_register.assert_awaited_once_with(
            spec.base_register + 1, 8, serial="1234567890"
        )

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


# ── Parameter refresh convergence and scope ─────────────────────────


class TestParameterRefreshScope:
    """Post-write refreshes converge schedule entities from parameter data."""

    @pytest.mark.asyncio
    async def test_successful_write_refreshes_same_serial_schedule_siblings(self):
        """A refreshed cache converges both boundaries on the written device."""
        serial = "1234567890"
        coordinator = _mock_coordinator(
            serial=serial,
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "8",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
                "HOLD_AC_CHARGE_END_HOUR": "9",
                "HOLD_AC_CHARGE_END_MINUTE": "0",
            },
        )

        async def _refresh_device(refresh_serial: str) -> bool:
            assert refresh_serial == serial
            coordinator.data["parameters"][serial] = {
                "HOLD_AC_CHARGE_START_HOUR": "20",
                "HOLD_AC_CHARGE_START_MINUTE": "30",
                "HOLD_AC_CHARGE_END_HOUR": "21",
                "HOLD_AC_CHARGE_END_MINUTE": "45",
            }
            await coordinator.async_request_refresh()
            return True

        coordinator.async_refresh_device_parameters = AsyncMock(
            side_effect=_refresh_device
        )
        written_entity = _entity(coordinator, serial=serial, is_end=False)
        sibling_entity = _entity(coordinator, serial=serial, is_end=True)
        _prep(written_entity)

        assert written_entity.native_value == time(8, 0)
        assert sibling_entity.native_value == time(9, 0)

        await written_entity.async_set_value(time(20, 30))

        coordinator.async_refresh_device_parameters.assert_awaited_once_with(serial)
        coordinator.async_request_refresh.assert_awaited_once_with()
        assert written_entity.native_value == time(20, 30)
        assert sibling_entity.native_value == time(21, 45)

    @pytest.mark.asyncio
    async def test_successful_write_refreshes_only_written_serial(self):
        """A write refreshes its serial without changing another device's cache."""
        written_serial = "1234567890"
        other_serial = "0987654321"
        coordinator = _mock_coordinator(
            serial=written_serial,
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": "8",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            },
        )
        coordinator.data["devices"][other_serial] = {
            "type": "inverter",
            "model": "FlexBOSS21",
        }
        coordinator.data["device_info"][other_serial] = {
            "deviceTypeText4APP": "FlexBOSS21"
        }
        coordinator.data["parameters"][other_serial] = {
            "HOLD_AC_CHARGE_START_HOUR": "10",
            "HOLD_AC_CHARGE_START_MINUTE": "0",
        }

        async def _refresh_device(refresh_serial: str) -> bool:
            coordinator.data["parameters"][refresh_serial] = {
                "HOLD_AC_CHARGE_START_HOUR": "20",
                "HOLD_AC_CHARGE_START_MINUTE": "30",
            }
            await coordinator.async_request_refresh()
            return True

        coordinator.async_refresh_device_parameters = AsyncMock(
            side_effect=_refresh_device
        )
        written_entity = _entity(coordinator, serial=written_serial)
        other_entity = _entity(coordinator, serial=other_serial)
        _prep(written_entity)

        assert other_entity.native_value == time(10, 0)

        await written_entity.async_set_value(time(20, 30))

        coordinator.async_refresh_device_parameters.assert_awaited_once_with(
            written_serial
        )
        coordinator.refresh_all_device_parameters.assert_not_awaited()
        assert other_entity.native_value == time(10, 0)


# ── Failure convergence (PR #283 review P1/P2) ───────────────────────


class TestWriteFailureConvergence:
    """Partial cloud writes and failed refreshes must not hide device state."""

    @pytest.mark.parametrize("schedule", ("ac_charge", "ac_first"))
    @pytest.mark.asyncio
    async def test_cloud_partial_failure_refreshes_and_shows_device_state(
        self, schedule
    ):
        """P1: hour write succeeds, minute write fails.

        The device now holds hour=new/minute=old. A best-effort parameter
        refresh must run BEFORE the error propagates, and the entity must
        reflect the refreshed (mixed) value — not the stale pre-write value
        and not the optimistic target.
        """
        serial = "1234567890"
        prefix = _spec(schedule).cloud_prefix
        coordinator = _mock_coordinator(
            has_local=False,
            parameters={
                f"{prefix}_START_HOUR": "8",
                f"{prefix}_START_MINUTE": "0",
            },
        )

        ok = MagicMock()
        ok.success = True
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.write_parameter = AsyncMock(
            side_effect=[ok, failed]
        )

        async def _refresh_mixed(refresh_serial: str):
            assert refresh_serial == serial
            # Device truth after the partial write: hour landed, minute not.
            coordinator.data["parameters"][serial] = {
                f"{prefix}_START_HOUR": "20",
                f"{prefix}_START_MINUTE": "0",
            }

        coordinator.async_refresh_device_parameters = AsyncMock(
            side_effect=_refresh_mixed
        )

        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await entity.async_set_value(time(20, 30))

        coordinator.async_refresh_device_parameters.assert_awaited_once_with(serial)
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

        async def _refresh_mixed(refresh_serial: str):
            assert refresh_serial == serial
            coordinator.data["parameters"][serial] = {
                "HOLD_AC_CHARGE_START_HOUR": "20",
                "HOLD_AC_CHARGE_START_MINUTE": "0",
            }

        coordinator.async_refresh_device_parameters = AsyncMock(
            side_effect=_refresh_mixed
        )

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await entity.async_set_value(time(20, 30))

        coordinator.async_refresh_device_parameters.assert_awaited_once_with(serial)
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
        coordinator.async_refresh_device_parameters.assert_not_awaited()
        assert entity._optimistic_value is None
        assert entity.native_value == time(8, 0)

    @pytest.mark.parametrize("schedule", ("ac_charge", "ac_first", "forced_discharge"))
    @pytest.mark.asyncio
    async def test_write_success_refresh_failure_retains_optimistic(self, schedule):
        """P2: the write landed on the device but the follow-up refresh died.

        Clearing the optimistic value would make the UI "revert" to the stale
        cached time even though hardware changed — keep the optimistic value.
        """
        spec = _spec(schedule)
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={str(spec.base_register): _pack(8, 0)},
        )
        # The real coordinator method catches its own exceptions and reports
        # failure by returning False (#362, coordinator_mixins.py), so this
        # raise cannot occur in production — this test pins time.py's
        # DEFENSIVE except-branch only; the production-reachable paths are the
        # False return (test below) and the explicit link-down branch.
        coordinator.async_refresh_device_parameters = AsyncMock(
            side_effect=Exception("refresh died")
        )

        entity = _entity(coordinator, schedule=schedule, window=1, is_end=False)
        _prep(entity)

        # Write succeeds; refresh failure is logged, not raised.
        await entity.async_set_value(time(7, 15))

        coordinator.write_register.assert_awaited_once()
        assert entity._optimistic_value == time(7, 15)
        assert entity.native_value == time(7, 15)
        assert entity.available is True

    @pytest.mark.asyncio
    async def test_write_success_refresh_reports_failure_retains_optimistic(self):
        """#362 golden path: the coordinator refresh helper reports failure
        by RETURNING False (it logs and swallows its own exceptions), so the
        schedule entity's retain-optimistic branch must fire on that signal —
        before #362 the helper swallowed the error and returned None-as-
        success, silently reverting the entity to the stale pre-write time.
        """
        coordinator = _mock_coordinator(
            has_local=True,
            parameters={"HOLD_AC_CHARGE_START_HOUR_1": _pack(8, 0)},
        )
        coordinator.async_refresh_device_parameters = AsyncMock(return_value=False)

        entity = _entity(coordinator, window=1, is_end=False)
        _prep(entity)

        # Write succeeds; the reported refresh failure is not raised.
        await entity.async_set_value(time(7, 15))

        coordinator.write_register.assert_awaited_once()
        assert entity._optimistic_value == time(7, 15)
        assert entity._optimistic_retained is True
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
        coordinator.async_refresh_device_parameters = AsyncMock(
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
        coordinator.async_refresh_device_parameters = AsyncMock(
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
        coordinator.async_refresh_device_parameters = AsyncMock(
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
        """A failed LOCAL-only write (single register, no partial state, no
        cloud to fall back to) drops the optimistic value and keeps the
        cached time. With a cloud client the same failure falls back to the
        cloud instead (TestWritePaths hybrid fallback tests)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_client=False,
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


# ── writeTime families (Generator / Off-Grid / Peak Shaving) ──────────


class TestWriteTimeFamilies:
    """The Generator/Off-Grid/Peak Shaving families: atomic writeTime cloud
    writes, uniform local packed writes, and the LSP cloud read for Peak
    Shaving."""

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "register"),
        [
            ("peak_shaving", 1, False, 209),
            ("peak_shaving", 2, True, 212),
            ("gen_charge", 1, False, 256),
            ("gen_charge", 2, True, 259),
            ("off_grid", 1, False, 269),
            ("off_grid", 3, True, 274),
        ],
    )
    @pytest.mark.asyncio
    async def test_local_write_packs_to_register(
        self, schedule, window, is_end, register
    ):
        """LOCAL packed write is uniform across families: base + window*2."""
        coordinator = _mock_coordinator(has_local=True)
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        _prep(entity)

        await entity.async_set_value(time(6, 30))

        coordinator.write_register.assert_awaited_once_with(
            register, (30 << 8) | 6, serial="1234567890"
        )
        coordinator.client.api.control.write_time_parameter.assert_not_awaited()

    @pytest.mark.parametrize(
        ("schedule", "window", "is_end", "time_param"),
        [
            ("gen_charge", 1, False, "HOLD_GEN_START_TIME_1"),
            ("gen_charge", 2, True, "HOLD_GEN_END_TIME_2"),
            ("off_grid", 3, False, "HOLD_OFF_GRID_START_TIME_3"),
            ("peak_shaving", 1, True, "HOLD_PEAK_SHAVING_END_TIME_1"),
        ],
    )
    @pytest.mark.asyncio
    async def test_cloud_write_uses_atomic_write_time(
        self, schedule, window, is_end, time_param
    ):
        """CLOUD: a single atomic write_time_parameter call (hour+minute
        together) — no separate hour/minute write_parameter, no partial-write
        re-read machinery."""
        coordinator = _mock_coordinator(has_local=False)
        entity = _entity(coordinator, schedule=schedule, window=window, is_end=is_end)
        _prep(entity)

        await entity.async_set_value(time(20, 5))

        coordinator.client.api.control.write_time_parameter.assert_awaited_once_with(
            "1234567890", time_param, 20, 5
        )
        coordinator.client.api.control.write_parameter.assert_not_awaited()
        coordinator.write_register.assert_not_awaited()
        coordinator.async_refresh_device_parameters.assert_awaited_once_with(
            "1234567890"
        )

    @pytest.mark.asyncio
    async def test_cloud_write_time_failure_raises(self):
        coordinator = _mock_coordinator(has_local=False)
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.write_time_parameter = AsyncMock(
            return_value=failed
        )
        entity = _entity(coordinator, schedule="gen_charge", window=1, is_end=False)
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_value(time(8, 0))

    @pytest.mark.asyncio
    async def test_cloud_write_time_exception_becomes_home_assistant_error(self):
        """A raw pylxpweb exception (e.g. persistent DATAFRAME_TIMEOUT surviving
        its retries) is wrapped in HomeAssistantError, not propagated raw out of
        async_set_value."""
        coordinator = _mock_coordinator(has_local=False)
        coordinator.client.api.control.write_time_parameter = AsyncMock(
            side_effect=RuntimeError("DATAFRAME_TIMEOUT")
        )
        entity = _entity(coordinator, schedule="peak_shaving", window=1, is_end=True)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="DATAFRAME_TIMEOUT"):
            await entity.async_set_value(time(20, 59))
        # Optimistic value cleared on write failure (falls back to cache).
        assert entity._optimistic_value is None

    def test_local_read_decodes_new_family_register(self):
        """LOCAL: Generator window 2 end (reg 259) unpacks from the canonical
        packed name."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_GEN_TIME_1_END": _pack(23, 59)},
        )
        entity = _entity(coordinator, schedule="gen_charge", window=2, is_end=True)
        assert entity.native_value == time(23, 59)

    def test_local_read_address_fallback(self):
        """LOCAL: older pylxpweb surfaces the raw address key; the alias chain
        fallback still decodes it."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"269": _pack(22, 0)},
        )
        entity = _entity(coordinator, schedule="off_grid", window=1, is_end=False)
        assert entity.native_value == time(22, 0)

    def test_peak_shaving_cloud_read_from_lsp_params(self):
        """CLOUD: Peak Shaving window 2 end reads LSP_..._43 / _44."""
        coordinator = _mock_coordinator(
            parameters={
                "LSP_HOLD_DIS_CHG_POWER_TIME_43": 2,
                "LSP_HOLD_DIS_CHG_POWER_TIME_44": 10,
            },
        )
        entity = _entity(coordinator, schedule="peak_shaving", window=2, is_end=True)
        assert entity.native_value == time(2, 10)


class TestWriteTimeFeatureDetection:
    """The writeTime families are skipped when pylxpweb lacks write_time_parameter."""

    @pytest.mark.asyncio
    async def test_old_pylxpweb_skips_writetime_families(self, hass, monkeypatch):
        """With _SUPPORTS_WRITE_TIME False, an EG4_HYBRID device gets only the
        classic families (the writeTime families are not created)."""
        import custom_components.eg4_web_monitor.time as time_module

        monkeypatch.setattr(time_module, "_SUPPORTS_WRITE_TIME", False)

        coordinator = _mock_coordinator(model="FlexBOSS21")
        coordinator.data["devices"]["1234567890"]["features"] = {
            "inverter_family": "EG4_HYBRID"
        }

        keys = await _setup_keys(hass, coordinator)

        assert keys == _expected_keys("ac_charge", "forced_charge", "forced_discharge")
