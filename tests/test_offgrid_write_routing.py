"""Issue #558: unverified off-grid writes route cloud-only; no doomed H233.

Task A — the AC-charge SOC window (regs 160/161) writes CLOUD-ONLY on the
EG4_OFFGRID family: local writes there are hardware-unverified (all #331
write evidence is the cloud holdParam path) and a post-write readback is
structurally incapable of catching a wrong name→register mapping — a
wrong-but-writable register is firmware-ACKed and reads back exactly the
value written (#476). Pure-LOCAL off-grid installs get a clear
HomeAssistantError instead of an unverified local write. EG4_HYBRID keeps
the hardware-verified local-first route for reg 160; unidentified families
fail open to the pre-#558 behavior.

Task B — the Quick Charge switch has NO working route on pure-LOCAL
off-grid (firmware rejects the H233 activation write, ILLEGAL DATA ADDRESS,
#296, and there is no cloud fallback): the switch is unavailable there and
a forced service call raises instead of firing the doomed write.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import INVERTER_FAMILY_EG4_OFFGRID
from custom_components.eg4_web_monitor.number import (
    ACChargeEndBatterySOCNumber,
    ACChargeStartBatterySOCNumber,
    EG4VoltageNumber,
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
    coordinator.note_parameters_written = MagicMock()
    coordinator._quick_charge_minutes = {}
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
        """EG4_HYBRID reg 160 local writes are hardware-verified (FlexBOSS21,
        fw FAAB-2727) and keep the local-first route — the #558 gate is a
        family gate, not a blanket change."""
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
    async def test_unknown_family_fails_open_to_local_first(self):
        """A device without a positively identified family keeps the
        pre-#558 local-first behavior (is_offgrid_family fails open)."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data={"features": {}}
        )
        entity = ACChargeEndBatterySOCNumber(coordinator, SERIAL)
        _prep(entity)

        await entity.async_set_native_value(95)

        coordinator.write_named_parameter.assert_awaited_once_with(
            "HOLD_AC_CHARGE_END_BATTERY_SOC", 95, serial=SERIAL
        )

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

    Their only write evidence is a cloud-path delta-test (llmwiki grades
    H158/H159 `portal-correlated`, target family unrecorded) — there is no
    local off-grid write proof, so EG4_OFFGRID routes them cloud-only too.
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
    async def test_offgrid_cutoff_voltage_keeps_local_first(self):
        """The gate is spec-scoped: other voltage registers (e.g. the
        off-grid cutoff, reg 100) keep the local-first route on off-grid."""
        coordinator = _mock_coordinator(
            has_local=True, has_http=True, device_data=dict(OFFGRID_FEATURES)
        )
        spec = _VOLTAGE_SPECS_BY_KEY["off_grid_cutoff_voltage"]
        entity = EG4VoltageNumber(coordinator, SERIAL, spec)
        _prep(entity)

        await entity.async_set_native_value(44.0)

        coordinator.write_named_parameter.assert_awaited_once_with(
            spec.param_key, 440, serial=SERIAL
        )
        coordinator.client.api.control.write_parameters.assert_not_awaited()

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


# ── Task B: pure-LOCAL off-grid Quick Charge has no working route ───────


class TestQuickChargePureLocalOffgrid:
    """The Quick Charge switch must not fire the doomed H233 write (#558)."""

    def test_offgrid_without_cloud_is_unavailable(self):
        """Pure-LOCAL off-grid: no working route (H233 firmware-rejected,
        #296; no cloud fallback) — the switch is unavailable."""
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
        fire the firmware-rejected H233 write)."""
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
