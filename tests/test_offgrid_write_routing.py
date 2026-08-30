"""Issue #558: unverified off-grid writes route cloud-only; no doomed H233.

Task A — the AC-charge SOC window (regs 160/161) writes CLOUD-ONLY on the
EG4_OFFGRID family: local writes there are hardware-unverified (all #331
write evidence is the cloud holdParam path) and a post-write readback is
structurally incapable of catching a wrong name→register mapping — a
wrong-but-writable register is firmware-ACKed and reads back exactly the
value written (#476). Pure-LOCAL off-grid installs get a clear
HomeAssistantError instead of an unverified local write. The routing gate
FAILS CLOSED (tribunal round 1): a missing/UNKNOWN family degrades to the
cloud-only route too — only a positively resolved non-off-grid family
keeps the local write. EG4_HYBRID keeps the local-first route for reg 160
per shipped behavior (the #570 sweep made H160 `hardware-toggle-proven`
on the tested FlexBOSS21/18kPV hybrids — via the CLOUD named path, so it
licenses no local write anywhere). AC charge power (reg 66) shares the
protected-register routing — no write tuple is recorded for H66 (the
#570 firmware verification proved raw 0..100 writable on CEAA/CCAA but
its charge-power semantics remain unverifiable).

#570 evidence sweep — the protected set is derived, not enumerated: EVERY
scalar holding register the number platform writes through the local-first
router lacks a local off-grid delta-test in the llmwiki ledger, so all of
them (74, 101, 102, 105, 125, 202, 227, 228, 169, 100, 22) share the
cloud-only routing on EG4_OFFGRID/unresolved families; see
TestSweepExtendedProtectedRouting.

Task B — the Quick Charge switch has NO working route on pure-LOCAL
off-grid: per the firmware verification posted on PR #569
(fw-verify-offgrid-writes), CEAA (12000XP lineage) rejects the H233
activation write outright (ILLEGAL DATA ADDRESS — proves #296), and CCAA
(6000XP lineage) implements the address but has no traced bit-0
quick-charge consumer, so neither lineage has a proven local route; with
no cloud fallback the switch is unavailable there and a forced service
call raises instead of firing the doomed-or-unproven write.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import INVERTER_FAMILY_EG4_OFFGRID
from custom_components.eg4_web_monitor.number import (
    ACChargeEndBatterySOCNumber,
    ACChargePowerNumber,
    ACChargeSOCLimitNumber,
    ACChargeStartBatterySOCNumber,
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
    EG4VoltageNumber,
    ForcedDischargePowerNumber,
    ForcedDischargeSOCLimitNumber,
    GridSellBackPowerNumber,
    GridPeakShavingPowerNumber,
    OffGridSOCCutoffNumber,
    OnGridSOCCutoffNumber,
    PVChargePowerNumber,
    QuickChargeDurationNumber,
    StartChargePowerNumber,
    StartDischargePowerNumber,
    StopDischargeVoltageNumber,
    SystemChargeSOCLimitNumber,
    SystemChargeVoltLimitNumber,
    VOLTAGE_NUMBER_SPECS,
)
from custom_components.eg4_web_monitor.switch import EG4QuickChargeSwitch
from tests.conftest import wire_coordinator_write_helpers

SERIAL = "1234567890"

OFFGRID_FEATURES = {"features": {"inverter_family": INVERTER_FAMILY_EG4_OFFGRID}}
HYBRID_FEATURES = {"features": {"inverter_family": "EG4_HYBRID"}}


def _mock_coordinator(
    *,
    has_http: bool = True,
    has_local: bool = False,
    local_only: bool = False,
    model: str = "12000XP",
    device_data: dict | None = None,
    parameters: dict | None = None,
) -> MagicMock:
    """Minimal mock coordinator for off-grid write-routing tests."""
    coordinator = MagicMock()
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.has_configured_local_transport = MagicMock(return_value=has_local)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock(return_value=True)
    coordinator.write_named_parameter = AsyncMock()
    coordinator.write_raw_parameter = AsyncMock()
    # Emission-faithful convergence wiring (#570 r7): note_parameters_written
    # merges acknowledged values into the same cache the entities read, and
    # has_active_parameter_write_seed reports them active — mirroring the
    # real coordinator's seed registry (settle-window semantics pinned by
    # TestParameterSeedSettleWindow in test_coordinator_local.py). Routing
    # tests can then assert native_value AFTER a cloud-routed write; without
    # convergence seeding those assertions go RED.
    _seeded_keys: set[str] = set()

    def _note_parameters_written(target: str, values: dict) -> None:
        coordinator.data["parameters"].setdefault(target, {}).update(values)
        _seeded_keys.update(values)

    coordinator.note_parameters_written = MagicMock(
        side_effect=_note_parameters_written
    )
    coordinator.has_active_parameter_write_seed = MagicMock(
        side_effect=lambda target, key: key in _seeded_keys
    )
    coordinator._quick_charge_minutes = {}
    # Live H233-b0 active check (cloud-routed on off-grid HYBRID, #296).
    # Default idle; the duration live-adjust tests override it.
    coordinator.is_quick_charge_active_live = AsyncMock(return_value=False)
    coordinator.get_device_info = MagicMock(return_value=None)
    # Battery control regime helpers (regime-gated voltage controls)
    coordinator.get_configured_control_modes = MagicMock(return_value=("soc", "soc"))
    coordinator.get_live_control_mode = MagicMock(return_value="soc")

    coordinator.data = {
        "devices": {
            SERIAL: {"type": "inverter", "model": model, **(device_data or {})},
        },
        "parameters": {SERIAL: parameters or {}},
    }

    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    mock_inverter.enable_quick_charge = AsyncMock(return_value=True)
    mock_inverter.disable_quick_charge = AsyncMock(return_value=True)
    mock_inverter.set_ac_charge_power = AsyncMock(return_value=True)
    # Cloud methods for the #570-extended protected scalars
    mock_inverter.set_pv_charge_power = AsyncMock(return_value=True)
    mock_inverter.set_battery_charge_current = AsyncMock(return_value=True)
    mock_inverter.set_battery_discharge_current = AsyncMock(return_value=True)
    mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
    mock_inverter.set_stop_discharge_voltage = AsyncMock(return_value=True)
    # Cloud methods for the r5 fail-open-created grid-tied scalars
    mock_inverter.set_ac_charge_soc_limit = AsyncMock(return_value=True)
    mock_inverter.set_forced_discharge_power = AsyncMock(return_value=True)
    mock_inverter.set_forced_discharge_soc_limit = AsyncMock(return_value=True)
    mock_inverter.set_feed_in_grid_power_kw = AsyncMock(return_value=True)
    # r6: pylxpweb's method is TRANSPORT-FIRST onto raw H206 — the entity
    # must only reach it on a positively resolved non-off-grid family.
    mock_inverter.set_grid_peak_shaving_power = AsyncMock(return_value=True)
    mock_inverter.transport = object() if has_local else None
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    if has_http:
        ok = MagicMock(success=True)
        client = MagicMock()
        client.api.control.write_parameter = AsyncMock(return_value=ok)
        client.api.control.write_parameters = AsyncMock(return_value=ok)
        # Readback that cannot testify (key absent) — verification is
        # exercised in test_number_entities.py; here it must only not fail.
        client.api.control.read_parameters = AsyncMock(
            return_value=MagicMock(parameters={})
        )
        client.api.control.start_quick_charge = AsyncMock(return_value=ok)
        client.api.control.stop_quick_charge = AsyncMock(return_value=ok)
        client.api.control.set_system_charge_soc_limit = AsyncMock(return_value=ok)
        coordinator.client = client
    else:
        coordinator.client = None

    wire_coordinator_write_helpers(coordinator)
    return coordinator


def _prep(entity: object) -> None:
    """Prepare an entity for async action tests (hass + entity_id doubles)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "test.test_entity"  # type: ignore[attr-defined]
    entity.platform = None  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


# ── Task A: regs 160/161 route cloud-only on EG4_OFFGRID ────────────────


class TestOffgridACChargeSOCCloudOnlyRouting:
    """Reg 160/161 writes never take the local path on EG4_OFFGRID (#558)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "param", "value"),
        [
            (ACChargeStartBatterySOCNumber, "HOLD_AC_CHARGE_START_BATTERY_SOC", 85),
            (ACChargeEndBatterySOCNumber, "HOLD_AC_CHARGE_END_BATTERY_SOC", 95),
        ],
    )
    async def test_offgrid_hybrid_write_goes_cloud_never_local(
        self, entity_cls, param, value
    ):
        """Off-grid + attached local transport + cloud: the write lands via
        the cloud holdParam path and the local named write is NEVER attempted
        — not even as the first try (#558 option 2, the #471/#472 pattern)."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, param, str(value)
        )
        # The cloud-landed write seeds the local-raw parameter cache so the
        # entity converges even though the local re-read is not trusted.
        coordinator.note_parameters_written.assert_called_once_with(
            SERIAL, {param: value}
        )
        assert entity.native_value == value  # r7 convergence

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "register"),
        [
            (ACChargeStartBatterySOCNumber, 160),
            (ACChargeEndBatterySOCNumber, 161),
        ],
    )
    async def test_offgrid_pure_local_write_raises_clear_error(
        self, entity_cls, register
    ):
        """Pure-LOCAL off-grid: the unverified local write is refused with an
        actionable error — the register write must never fire (#476 lesson:
        a wrong-but-writable register ACKs and reads back what you wrote)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=False,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(
            HomeAssistantError,
            match=rf"register {register}.*cloud API only.*558",
        ):
            await entity.async_set_native_value(80)

        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offgrid_pure_local_error_leaves_no_optimistic_value(self):
        """The refused write does not leave a phantom optimistic value."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=False,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
            parameters={"HOLD_AC_CHARGE_END_BATTERY_SOC": 100},
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(HomeAssistantError):
            await entity.async_set_native_value(80)

        assert entity._optimistic_value is None
        assert entity.native_value == 100

    @pytest.mark.asyncio
    async def test_hybrid_family_keeps_local_first_route(self):
        """EG4_HYBRID reg 160 keeps the local-first route per shipped
        behavior (H160 is now `hardware-toggle-proven` on the tested
        hybrids — via the cloud named path, #570 sweep); the #558 gate is
        a family gate, not a blanket change."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(85)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_START_BATTERY_SOC", 85, serial=SERIAL
        )
        coordinator.client.api.control.write_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_data",
        [
            {"features": {}},  # family missing entirely
            {"features": {"inverter_family": "UNKNOWN"}},  # unresolved
            {},  # no features key at all
        ],
        ids=["missing-family", "unknown-family", "no-features"],
    )
    async def test_unresolved_family_fails_closed_to_cloud(self, device_data):
        """Tribunal round 1: an unidentified unit might BE an off-grid
        inverter, so protected-register writes degrade to the cloud route —
        the local write is permitted only for a positively resolved
        non-off-grid family."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=device_data
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(95)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, "HOLD_AC_CHARGE_END_BATTERY_SOC", "95"
        )

    @pytest.mark.asyncio
    async def test_unresolved_family_pure_local_write_raises(self):
        """Unresolved family + no cloud: the protected write is refused,
        exactly as on a positively identified off-grid unit."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=False,
            local_only=True,
            device_data={"features": {"inverter_family": "UNKNOWN"}},
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(
            HomeAssistantError, match=r"register 161.*cloud API only.*558"
        ):
            await entity.async_set_native_value(95)

        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offgrid_cloud_only_install_unchanged(self):
        """CLOUD mode (the #331 reporter's): the cloud holdParam write is
        unchanged by the routing gate."""
        coordinator = _mock_coordinator(
            has_local=False, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(100)

        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, "HOLD_AC_CHARGE_END_BATTERY_SOC", "100"
        )
        coordinator.write_named_parameter.assert_not_awaited()


# ── Task A (spec-gate round): regs 158/159 voltage window, same routing ──

_VOLTAGE_SPECS_BY_KEY = {spec.key: spec for spec in VOLTAGE_NUMBER_SPECS}


class TestOffgridACChargeVoltageCloudOnlyRouting:
    """Regs 158/159 share the 160/161 situation and the same routing (#558).

    Every H158/H159 write proof is CLOUD-path (the #570 sweep's cloud
    named toggle/restore, `hardware-toggle-proven` on the tested
    FlexBOSS21/18kPV hybrids; the earlier H158 delta-test was
    scaled-values-only) — there is no local off-grid write proof for
    either, so EG4_OFFGRID routes them cloud-only too.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("spec_key", "register"),
        [
            ("ac_charge_start_voltage", 158),
            ("ac_charge_end_voltage", 159),
        ],
    )
    async def test_offgrid_hybrid_voltage_write_goes_cloud_never_local(
        self, spec_key, register
    ):
        """Off-grid + local transport + cloud: the raw-register cloud write
        runs and the local named write never fires."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        spec = _VOLTAGE_SPECS_BY_KEY[spec_key]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        await entity.async_set_native_value(55)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameters.assert_awaited_once_with(
            SERIAL, {register: 550}
        )
        coordinator.note_parameters_written.assert_called_once_with(
            SERIAL, {spec.param_key: 550}
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("spec_key", "register"),
        [
            ("ac_charge_start_voltage", 158),
            ("ac_charge_end_voltage", 159),
        ],
    )
    async def test_offgrid_pure_local_voltage_write_raises_clear_error(
        self, spec_key, register
    ):
        """Pure-LOCAL off-grid: the unverified voltage write is refused."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=False,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
        )
        entity = EG4VoltageNumber(coordinator, SERIAL, _VOLTAGE_SPECS_BY_KEY[spec_key])
        _prep(entity)

        with pytest.raises(
            HomeAssistantError,
            match=rf"register {register}.*cloud API only.*558",
        ):
            await entity.async_set_native_value(55)

        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offgrid_cutoff_voltage_routes_cloud(self):
        """#570 sweep (inverts the pre-sweep pin): the off-grid cutoff
        (reg 100, `lineage-inferred`, no off-grid write evidence) now shares
        the protected routing — cloud raw-register write, never local."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        spec = _VOLTAGE_SPECS_BY_KEY["off_grid_cutoff_voltage"]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        await entity.async_set_native_value(44.0)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameters.assert_awaited_once_with(
            SERIAL, {100: 440}
        )

    @pytest.mark.asyncio
    async def test_hybrid_family_voltage_write_keeps_local_first(self):
        """Non-off-grid families keep the local-first route for 158/159."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        spec = _VOLTAGE_SPECS_BY_KEY["ac_charge_start_voltage"]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        await entity.async_set_native_value(55)

        coordinator.write_named_parameter.assert_awaited_once_with(
            spec.param_key, 550, serial=SERIAL
        )
        coordinator.client.api.control.write_parameters.assert_not_awaited()


# ── Tribunal round 1, finding 4: AC charge power (reg 66) is protected ──


class TestACChargePowerProtectedRouting:
    """No write evidence is recorded for H66 (its `portal-correlated` grade
    rests on read/scaling evidence only) — same protected-register routing
    (#558).
    """

    @pytest.mark.asyncio
    async def test_offgrid_write_goes_cloud_never_local(self):
        """Off-grid + local transport + cloud: the inverter cloud method
        runs and the local named write never fires."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = ACChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_ac_charge_power.assert_awaited_once_with(power_kw=5.0)
        coordinator.note_parameters_written.assert_called_once_with(
            SERIAL, {"HOLD_AC_CHARGE_POWER_CMD": 50}
        )
        assert entity.native_value == pytest.approx(5.0)  # r7 convergence

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_data",
        [dict(OFFGRID_FEATURES), {"features": {"inverter_family": "UNKNOWN"}}],
        ids=["offgrid", "unknown-family"],
    )
    async def test_pure_local_write_raises_clear_error(self, device_data):
        """Pure-LOCAL off-grid/unresolved: the unverified write is refused."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=False, local_only=True, device_data=device_data
        )
        entity = ACChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(
            HomeAssistantError, match=r"register 66.*cloud API only.*558"
        ):
            await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolved_hybrid_family_keeps_local_first(self):
        """A positively resolved non-off-grid family keeps local-first."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = ACChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_POWER_CMD", 50, serial=SERIAL
        )
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_ac_charge_power.assert_not_awaited()


# ── #570 sweep: every remaining router-driven scalar joins the set ──────


class TestSweepExtendedProtectedRouting:
    """#570 evidence sweep: the protected set is DERIVED, not enumerated.

    Every scalar holding register the number platform writes through the
    local-first router lacks a local off-grid delta-test in the llmwiki
    ledger, so on EG4_OFFGRID/unresolved families they ALL route
    cloud-only: PV charge power (74), battery charge/discharge current
    (101/102), SOC cutoffs (105/125), stop-discharge voltage (202), system
    charge SOC/voltage limits (227/228), cutoff voltages (169/100) and PV
    start voltage (22 — `portal-correlated`, cloud named route only).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "value", "cloud_method", "cloud_kwargs"),
        [
            (PVChargePowerNumber, 5, "set_pv_charge_power", {"power_kw": 5}),
            (
                BatteryChargeCurrentNumber,
                100,
                "set_battery_charge_current",
                {"current_amps": 100},
            ),
            (
                BatteryDischargeCurrentNumber,
                100,
                "set_battery_discharge_current",
                {"current_amps": 100},
            ),
            (
                OnGridSOCCutoffNumber,
                20,
                "set_battery_soc_limits",
                {"on_grid_limit": 20},
            ),
            (
                OffGridSOCCutoffNumber,
                20,
                "set_battery_soc_limits",
                {"off_grid_limit": 20},
            ),
            (
                StopDischargeVoltageNumber,
                41.5,
                "set_stop_discharge_voltage",
                {"voltage": 41.5},
            ),
        ],
        ids=["pv-74", "chg-cur-101", "dischg-cur-102", "soc-105", "soc-125", "v-202"],
    )
    async def test_offgrid_scalar_write_goes_cloud_never_local(
        self, entity_cls, value, cloud_method, cloud_kwargs
    ):
        """Off-grid + local transport + cloud: the inverter cloud method
        runs and the local named write never fires."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        getattr(inverter, cloud_method).assert_awaited_once_with(**cloud_kwargs)
        # #570 r7 (grok): routing alone is not convergence — the cloud-routed
        # write must land in the entity's own read path (seeded cache beats
        # the stale inverter attribute during the settle window).
        assert entity.native_value == pytest.approx(value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "value", "register"),
        [
            (PVChargePowerNumber, 5, 74),
            (BatteryChargeCurrentNumber, 100, 101),
            (BatteryDischargeCurrentNumber, 100, 102),
            (OnGridSOCCutoffNumber, 20, 105),
            (OffGridSOCCutoffNumber, 20, 125),
            (StopDischargeVoltageNumber, 41.5, 202),
            (SystemChargeSOCLimitNumber, 90, 227),
            (SystemChargeVoltLimitNumber, 56.0, 228),
        ],
        ids=["74", "101", "102", "105", "125", "202", "227", "228"],
    )
    async def test_offgrid_pure_local_scalar_write_raises(
        self, entity_cls, value, register
    ):
        """Pure-LOCAL off-grid: the unverified write is refused with the
        actionable cloud-only error, and no local write fires."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=False,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(
            HomeAssistantError, match=rf"register {register}.*cloud API only.*558"
        ):
            await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.write_raw_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offgrid_system_charge_soc_goes_cloud(self):
        """Reg 227's inline 3-way write shares the routing: the cloud API
        branch runs and the local named write never fires on off-grid."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = SystemChargeSOCLimitNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(90)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.set_system_charge_soc_limit.assert_awaited_once_with(
            SERIAL, 90
        )
        assert entity.native_value == 90  # r7: converges via the cache seed

    @pytest.mark.asyncio
    async def test_offgrid_ac_charge_power_capped_at_firmware_10kw(self):
        """#570 review round 4: the CEAA/CCAA firmware writer rejects raw
        >100 (10 kW), so off-grid/unresolved families advertise and accept
        at most 10 kW — 10.0 lands via the cloud writer, 10.1 fails at the
        entity with a clear error before any writer runs."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = ACChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        assert entity.native_max_value == 10.0

        # BOTH advertised boundaries write as-is (r7).
        await entity.async_set_native_value(0.0)
        await entity.async_set_native_value(10.0)
        inverter = coordinator.get_inverter_object(SERIAL)
        kw_calls = inverter.set_ac_charge_power.await_args_list
        assert kw_calls[0].kwargs == {"power_kw": 0.0}
        assert kw_calls[1].kwargs == {"power_kw": 10.0}

        for bad in (-0.1, 10.1):
            with pytest.raises(HomeAssistantError, match=r"0\.0-10\.0 kW"):
                await entity.async_set_native_value(bad)
        assert inverter.set_ac_charge_power.await_count == 2  # unchanged
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolved_hybrid_ac_charge_power_keeps_15kw_ceiling(self):
        """Regression guard: the 15 kW ceiling is family-scoped — a
        positively resolved non-off-grid family keeps it (shipped status
        quo; no firmware proof narrows it there)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = ACChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        assert entity.native_max_value == 15.0

        await entity.async_set_native_value(15.0)
        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_POWER_CMD", 150, serial=SERIAL
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("spec_key", "min_v", "max_v", "bad_values"),
        [
            ("ac_charge_start_voltage", 39, 57, (38, 58)),
            ("ac_charge_end_voltage", 48, 59, (47, 60)),
        ],
        ids=["h158", "h159"],
    )
    async def test_offgrid_ac_charge_voltage_firmware_bounds(
        self, spec_key, min_v, max_v, bad_values
    ):
        """r6 (Codex MED) + r7 (Codex MED): the shared 38-60 V range let
        H158=60 / H159=38 pass HA validation and then fail at the
        CEAA/CCAA writer (exception 03); and r6's 38.4 V advertised floor
        let HA accept a boundary the whole-volt validation then rejected.
        Off-grid/unresolved families now advertise whole-volt bounds
        inside the firmware windows (H158 39-57, H159 48-59) and BOTH
        advertised boundaries write as-is via the cloud raw-register
        route; out-of-window values fail clearly at the entity."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        spec = _VOLTAGE_SPECS_BY_KEY[spec_key]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        assert entity.native_min_value == min_v
        assert entity.native_max_value == max_v

        # BOTH advertised boundaries are writable exactly as advertised.
        await entity.async_set_native_value(min_v)
        await entity.async_set_native_value(max_v)
        raw_calls = coordinator.client.api.control.write_parameters.await_args_list
        assert raw_calls[0].args == (SERIAL, {spec.register: min_v * 10})
        assert raw_calls[1].args == (SERIAL, {spec.register: max_v * 10})

        for bad in bad_values:
            with pytest.raises(HomeAssistantError, match=r"must be"):
                await entity.async_set_native_value(bad)
        assert coordinator.client.api.control.write_parameters.await_count == 2
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolved_hybrid_ac_charge_voltage_keeps_shared_range(self):
        """Regression guard: resolved non-off-grid families keep the shipped
        38-60 V range (no firmware proof narrows it there)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        spec = _VOLTAGE_SPECS_BY_KEY["ac_charge_start_voltage"]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        assert entity.native_min_value == 38
        assert entity.native_max_value == 60

        await entity.async_set_native_value(60)
        coordinator.write_named_parameter.assert_awaited_once_with(
            spec.param_key, 600, serial=SERIAL
        )

    @pytest.mark.asyncio
    async def test_offgrid_ac_charge_end_soc_floor_is_20(self):
        """r6 (Codex MED): H161 advertised 0-100 but the CEAA/CCAA writer
        enforces 20..100 — off-grid/unresolved families floor at 20; 20
        lands via the cloud holdParam write, 19 fails at the entity."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        assert entity.native_min_value == 20

        # BOTH advertised boundaries write as-is (r7).
        await entity.async_set_native_value(20)
        await entity.async_set_native_value(100)
        named_calls = coordinator.client.api.control.write_parameter.await_args_list
        assert named_calls[0].args == (SERIAL, "HOLD_AC_CHARGE_END_BATTERY_SOC", "20")
        assert named_calls[1].args == (SERIAL, "HOLD_AC_CHARGE_END_BATTERY_SOC", "100")

        for bad in (19, 101):
            with pytest.raises(HomeAssistantError, match=r"20-100"):
                await entity.async_set_native_value(bad)
        assert coordinator.client.api.control.write_parameter.await_count == 2
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offgrid_ac_charge_start_soc_floor_is_1(self):
        """#570 review round 4: the CEAA/CCAA firmware writer rejects
        H160=0 (exception 03), so off-grid/unresolved families accept a
        minimum of 1 — 1 lands via the cloud holdParam write, 0 fails at
        the entity before any writer runs."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        assert entity.native_min_value == 1

        # BOTH advertised boundaries write as-is (r7).
        await entity.async_set_native_value(1)
        await entity.async_set_native_value(90)
        named_calls = coordinator.client.api.control.write_parameter.await_args_list
        assert named_calls[0].args == (SERIAL, "HOLD_AC_CHARGE_START_BATTERY_SOC", "1")
        assert named_calls[1].args == (
            SERIAL,
            "HOLD_AC_CHARGE_START_BATTERY_SOC",
            "90",
        )

        for bad in (0, 91):
            with pytest.raises(HomeAssistantError, match=r"1-90"):
                await entity.async_set_native_value(bad)
        assert coordinator.client.api.control.write_parameter.await_count == 2
        coordinator.write_named_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolved_hybrid_ac_charge_start_soc_keeps_0_floor(self):
        """Regression guard: the 0 floor is family-scoped — a positively
        resolved non-off-grid family keeps it (shipped status quo; the
        firmware proof of 0's invalidity is CEAA/CCAA-scoped)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = ACChargeStartBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        assert entity.native_min_value == 0

        await entity.async_set_native_value(0)
        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_START_BATTERY_SOC", 0, serial=SERIAL
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [10, 90], ids=["min-10", "max-90"])
    async def test_offgrid_ongrid_soc_cutoff_boundaries_write_cloud(self, value):
        """Review round 2 MED: the entity's advertised range now matches the
        canonical H105 range (10-90) that pylxpweb's set_battery_soc_limits
        enforces — both boundary values pass validation and land via the
        cloud writer without a ValueError."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = OnGridSOCCutoffNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_battery_soc_limits.assert_awaited_once_with(on_grid_limit=value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [9, 91], ids=["below-min", "above-max"])
    async def test_offgrid_ongrid_soc_cutoff_out_of_range_raises_clearly(self, value):
        """Out-of-range values fail at the entity with a clear
        HomeAssistantError BEFORE any writer runs — never pylxpweb's raw
        ValueError (the pre-fix off-grid symptom, review round 2 MED)."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = OnGridSOCCutoffNumber(coordinator, SERIAL)
        _prep(entity)

        with pytest.raises(HomeAssistantError, match=r"10-90"):
            await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_battery_soc_limits.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [0, 100], ids=["min-0", "max-100"])
    async def test_offgrid_offgrid_soc_cutoff_full_range_writes_cloud(self, value):
        """Reg 125 is genuinely 0-100 everywhere (canonical definition and
        set_battery_soc_limits agree) — the full advertised range passes."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = OffGridSOCCutoffNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_battery_soc_limits.assert_awaited_once_with(off_grid_limit=value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("spec_key", "value", "register", "raw"),
        [
            ("on_grid_cutoff_voltage", 48.0, 169, 480),
            ("off_grid_cutoff_voltage", 44.0, 100, 440),
        ],
    )
    async def test_offgrid_cutoff_voltage_specs_go_cloud(
        self, spec_key, value, register, raw
    ):
        """The remaining voltage specs share the 158/159 routing on
        off-grid: cloud raw-register write, never the local named write."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        entity = EG4VoltageNumber(coordinator, SERIAL, _VOLTAGE_SPECS_BY_KEY[spec_key])
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameters.assert_awaited_once_with(
            SERIAL, {register: raw}
        )

    @pytest.mark.asyncio
    async def test_offgrid_pv_start_voltage_goes_cloud_named_volts(self):
        """Reg 22 (`portal-correlated`, cloud named route only — and the
        pylxpweb table notes it also carries LSP function bits) routes
        through its verified cloud route — the named-volts write — and
        never the local named write."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        spec = _VOLTAGE_SPECS_BY_KEY["pv_start_voltage"]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        await entity.async_set_native_value(150)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, spec.param_key, "150"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "value", "param", "local_value"),
        [
            (PVChargePowerNumber, 5, "HOLD_FORCED_CHG_POWER_CMD", 50),
            (SystemChargeSOCLimitNumber, 90, "HOLD_SYSTEM_CHARGE_SOC_LIMIT", 90),
        ],
        ids=["pv-74", "soc-227"],
    )
    async def test_resolved_hybrid_family_keeps_local_first(
        self, entity_cls, value, param, local_value
    ):
        """Regression guard: a positively resolved non-off-grid family keeps
        the local-first route for the sweep-extended registers too."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_awaited_once_with(
            param, local_value, serial=SERIAL
        )

    @pytest.mark.asyncio
    async def test_unresolved_family_fails_closed_to_cloud(self):
        """Tribunal round 1 polarity holds for the extended set: a missing
        family degrades a sweep-extended register to the cloud route."""
        coordinator = _mock_coordinator(has_local=True, has_http=True, device_data={})
        entity = BatteryChargeCurrentNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(100)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_battery_charge_current.assert_awaited_once_with(current_amps=100)


class TestQuickChargeDurationOffgridLiveAdjust:
    """#570 adversarial round 1: the live reg-234 adjust is family-gated.

    On EG4_OFFGRID + HYBRID the live active check is CLOUD-routed
    (``_quick_charge_prefers_cloud``, #296), so a cloud-started charge
    reports active WITHOUT any local H233 read standing in the way — the
    H233 rejection is CEAA-scoped and gates nothing here. H234 carries no
    off-grid write evidence, so off-grid/unresolved families must never
    reach the local reg-234 write: they store the start preference instead
    (the shipped CLOUD-mode behavior for the same situation).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_data",
        [dict(OFFGRID_FEATURES), {"features": {"inverter_family": "UNKNOWN"}}, {}],
        ids=["offgrid", "unknown-family", "no-features"],
    )
    async def test_offgrid_active_charge_never_writes_reg234_locally(self, device_data):
        """Off-grid/unresolved + local transport + cloud-visible ACTIVE
        charge: no local write fires, no live check runs (the gate
        short-circuits before it), and the preference is stored."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=device_data
        )
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=True)
        entity = QuickChargeDurationNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(45)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.is_quick_charge_active_live.assert_not_awaited()
        assert coordinator._quick_charge_minutes[SERIAL] == 45

    @pytest.mark.asyncio
    async def test_resolved_hybrid_active_charge_keeps_live_reg234_write(self):
        """Regression guard: a positively resolved non-off-grid family keeps
        the live reg-234 adjust."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        coordinator.is_quick_charge_active_live = AsyncMock(return_value=True)
        entity = QuickChargeDurationNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(45)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "SNA_HOLD_QUICK_CHARGE_MINUTE", 45, serial=SERIAL
        )


# ── #570 r5: first-run/unresolved family — fail-open creation, gated writes ──


class TestFirstRunUnresolvedProtectedRouting:
    """#570 review round 5: fail-open CREATION never yields an ungated write.

    Entity creation deliberately fails OPEN (suppression needs positive
    identification, #259/#219 — a 12000XP model string with an UNRESOLVED
    family still creates the grid-tied controls, pinned by
    test_number_entities.test_xp_model_without_family_fails_open). The
    WRITES of those fail-open-created entities (H67/H82/H83/H103/H116/H117)
    therefore fail CLOSED on the family, so the first-run window before
    family resolution cannot produce an unverified local write.
    """

    FIRST_RUN = {"features": {"inverter_family": "UNKNOWN"}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("entity_cls", "value", "cloud_method", "cloud_kwargs"),
        [
            (
                ACChargeSOCLimitNumber,
                80,
                "set_ac_charge_soc_limit",
                {"soc_percent": 80},
            ),
            (
                ForcedDischargePowerNumber,
                5.0,
                "set_forced_discharge_power",
                {"power_kw": 5.0},
            ),
            (
                ForcedDischargeSOCLimitNumber,
                20,
                "set_forced_discharge_soc_limit",
                {"soc_percent": 20},
            ),
            (
                GridSellBackPowerNumber,
                5.0,
                "set_feed_in_grid_power_kw",
                {"power_kw": 5.0},
            ),
        ],
        ids=["h67", "h82", "h83", "h103"],
    )
    async def test_first_run_unknown_family_write_goes_cloud_never_local(
        self, entity_cls, value, cloud_method, cloud_kwargs
    ):
        """First-run 12000XP model + UNKNOWN family + local transport +
        cloud: the write lands via the cloud method; no local named write."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="12000XP",
            device_data=dict(self.FIRST_RUN),
        )
        entity = entity_cls(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(value)

        coordinator.write_named_parameter.assert_not_awaited()
        inverter = coordinator.get_inverter_object(SERIAL)
        getattr(inverter, cloud_method).assert_awaited_once_with(**cloud_kwargs)

    @pytest.mark.asyncio
    async def test_first_run_unknown_family_start_discharge_goes_cloud_named(self):
        """H116 routes through the reporter-verified cloud named path."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="12000XP",
            device_data=dict(self.FIRST_RUN),
        )
        entity = StartDischargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(100)

        coordinator.write_named_parameter.assert_not_awaited()
        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, "HOLD_P_TO_USER_START_DISCHG", "100"
        )

    @pytest.mark.asyncio
    async def test_first_run_unknown_family_raw_h117_write_refused(self):
        """H117 is a RAW register write with NO cloud path: on an unresolved
        family it is refused outright — never fired, never silently ACKed."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="12000XP",
            device_data=dict(self.FIRST_RUN),
        )
        entity = StartChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        # r6: the message must NOT promise a cloud route (none exists) —
        # it names family resolution as the remedy instead.
        with pytest.raises(
            HomeAssistantError,
            match=r"register 117.*no cloud parameter name.*positively identified",
        ):
            await entity.async_set_native_value(-50)

        coordinator.write_raw_parameter.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_data",
        [dict(FIRST_RUN), {}],
        ids=["unknown-family", "no-features"],
    )
    async def test_first_run_grid_peak_shaving_goes_cloud_named_never_library(
        self, device_data
    ):
        """r6 (Grok MED): pylxpweb's set_grid_peak_shaving_power is
        TRANSPORT-FIRST onto raw H206 — an earlier derivation claim called
        the entity 'cloud-only by construction', which the pinned wheel
        falsifies. On off-grid/unresolved families the entity must write
        the cloud named parameter directly and never reach the library
        method."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, model="12000XP", device_data=device_data
        )
        entity = GridPeakShavingPowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_grid_peak_shaving_power.assert_not_awaited()
        coordinator.client.api.control.write_parameter.assert_awaited_once_with(
            SERIAL, "_12K_HOLD_GRID_PEAK_SHAVING_POWER", "5.0"
        )
        # r7: the cloud-named branch seeds convergence too (it previously
        # never called note_parameters_written at all).
        coordinator.note_parameters_written.assert_called_once_with(
            SERIAL, {"_12K_HOLD_GRID_PEAK_SHAVING_POWER": 5.0}
        )
        assert entity.native_value == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_resolved_hybrid_grid_peak_shaving_uses_library_method(self):
        """Regression guard: a positively resolved non-off-grid family keeps
        pylxpweb's transport-first method (hybrid-verified deci-kW raw
        encoding, cloud fallback inside the library)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = GridPeakShavingPowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(5.0)

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.set_grid_peak_shaving_power.assert_awaited_once_with(power_kw=5.0)

    @pytest.mark.asyncio
    async def test_resolved_hybrid_forced_discharge_keeps_local_first(self):
        """Regression guard: a positively resolved non-off-grid family keeps
        the local-first route for the fail-open-created scalars."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = ForcedDischargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_FORCED_DISCHG_POWER_CMD", 50, serial=SERIAL
        )

    @pytest.mark.asyncio
    async def test_resolved_hybrid_raw_h117_write_still_runs(self):
        """Regression guard: resolved non-off-grid keeps the raw H117 write
        (LOCAL/HYBRID-only by construction)."""
        coordinator = _mock_coordinator(
            has_local=True,
            has_http=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        entity = StartChargePowerNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(-50)

        coordinator.write_raw_parameter.assert_awaited_once_with(
            117, 65486, serial=SERIAL
        )


# ── Task B: pure-LOCAL off-grid Quick Charge has no working route ───────


class TestQuickChargePureLocalOffgrid:
    """The Quick Charge switch must not fire the doomed H233 write (#558)."""

    def test_offgrid_without_cloud_is_unavailable(self):
        """Pure-LOCAL off-grid: no working route (H233 firmware-rejected on
        CEAA, unproven on CCAA, #296; no cloud fallback) — the switch is
        unavailable."""
        coordinator = _mock_coordinator(
            has_http=False,
            has_local=True,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        assert switch.available is False

    def test_offgrid_with_cloud_stays_available(self):
        """Off-grid with a cloud client keeps the (cloud-driven) switch."""
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, device_data=dict(OFFGRID_FEATURES)
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        assert switch.available is True

    @pytest.mark.parametrize(
        "device_data",
        [{"features": {"inverter_family": "UNKNOWN"}}, {"features": {}}, {}],
        ids=["unknown-family", "missing-family", "no-features"],
    )
    def test_unresolved_family_without_cloud_is_unavailable(self, device_data):
        """Tribunal round 1: an unidentified pure-LOCAL unit might be a
        12000XP/6000XP with no proven local H233 route (rejected on CEAA,
        unproven on CCAA) — fail closed."""
        coordinator = _mock_coordinator(
            has_http=False, has_local=True, local_only=True, device_data=device_data
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        assert switch.available is False

    @pytest.mark.asyncio
    async def test_unresolved_family_without_cloud_toggle_raises_without_h233(self):
        """Unresolved family, pure-LOCAL: a forced toggle raises and the
        inverter's local-first method is never called."""
        coordinator = _mock_coordinator(
            has_http=False,
            has_local=True,
            local_only=True,
            device_data={"features": {"inverter_family": "UNKNOWN"}},
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        _prep(switch)

        with pytest.raises(HomeAssistantError, match=r"#296.*no cloud.*558"):
            await switch.async_turn_on()

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.enable_quick_charge.assert_not_called()

    def test_non_offgrid_without_cloud_stays_available(self):
        """Pure-LOCAL non-off-grid families keep the switch (H233 works)."""
        coordinator = _mock_coordinator(
            has_http=False,
            has_local=True,
            local_only=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        assert switch.available is True

    @pytest.mark.asyncio
    async def test_offgrid_without_cloud_toggle_raises_without_h233(self):
        """A forced service call on the unavailable switch raises a clear
        error and never reaches pylxpweb's local-first enable (which would
        fire the H233 write — firmware-rejected on CEAA, unproven on
        CCAA)."""
        coordinator = _mock_coordinator(
            has_http=False,
            has_local=True,
            local_only=True,
            device_data=dict(OFFGRID_FEATURES),
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        _prep(switch)

        with pytest.raises(HomeAssistantError, match=r"#296.*no cloud.*558"):
            await switch.async_turn_on()
        with pytest.raises(HomeAssistantError, match=r"#296.*no cloud.*558"):
            await switch.async_turn_off()

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.enable_quick_charge.assert_not_called()
        inverter.disable_quick_charge.assert_not_called()
        assert switch._pending_state is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_data",
        [
            dict(OFFGRID_FEATURES),
            {"features": {"inverter_family": "UNKNOWN"}},
            {},
        ],
        ids=["offgrid", "unknown-family", "no-features"],
    )
    async def test_offgrid_or_unresolved_with_cloud_toggles_cloud_direct(
        self, device_data
    ):
        """#570 review round 4: with a cloud client, off-grid AND
        unresolved families go cloud-direct — pylxpweb's local-first
        paired H233/H234 write is never invoked. An unresolved family
        might be a CCAA 6000XP, where the local H233 write is silently
        ACCEPTED with unproven bit-0 semantics, so 'the fallback works'
        was never a safety net there (#476 mechanism)."""
        coordinator = _mock_coordinator(
            has_http=True, has_local=True, device_data=device_data
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        _prep(switch)

        await switch.async_turn_on()
        await switch.async_turn_off()

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.enable_quick_charge.assert_not_called()
        inverter.disable_quick_charge.assert_not_called()
        coordinator.client.api.control.start_quick_charge.assert_awaited_once()
        coordinator.client.api.control.stop_quick_charge.assert_awaited_once_with(
            SERIAL
        )

    @pytest.mark.asyncio
    async def test_resolved_hybrid_with_cloud_keeps_local_first_enable(self):
        """Regression guard: a positively resolved non-off-grid family keeps
        pylxpweb's local-first quick-charge methods even with a cloud
        client configured."""
        coordinator = _mock_coordinator(
            has_http=True,
            has_local=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        _prep(switch)

        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.enable_quick_charge.assert_called_once_with(minute=60)
        coordinator.client.api.control.start_quick_charge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_offgrid_without_cloud_local_enable_still_runs(self):
        """Regression guard: the raise is off-grid-scoped — other families'
        pure-LOCAL toggles keep using pylxpweb's local-first methods."""
        coordinator = _mock_coordinator(
            has_http=False,
            has_local=True,
            local_only=True,
            model="FlexBOSS21",
            device_data=dict(HYBRID_FEATURES),
        )
        switch = EG4QuickChargeSwitch(coordinator, SERIAL)
        _prep(switch)

        await switch.async_turn_on()

        inverter = coordinator.get_inverter_object(SERIAL)
        inverter.enable_quick_charge.assert_called_once_with(minute=60)
