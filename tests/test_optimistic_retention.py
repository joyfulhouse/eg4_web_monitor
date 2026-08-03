"""Bounded optimistic-value retention across every control platform (#379).

PR #377 gave switches the #362 write-refresh semantics: when a write is
acknowledged but its post-write refresh fails, the entity RETAINS the
acknowledged value instead of republishing the stale pre-write cache value —
bounded by ``RETAINED_OPTIMISTIC_TTL`` so a firmware-silently-NAKed write
(#251 reg 233, #331 reg 67) cannot wedge a value the device never applied.

#379 extends the same machinery to the surfaces PR #377 left out:

- ``select.py`` — all four selects cleared their optimistic state BEFORE (or
  regardless of) the post-write refresh and discarded its result.
- ``number.py`` — ``optimistic_value_context`` cleared in a ``finally``, so a
  failed refresh reverted the UI the same way; the post-write parameter
  refresh outcome must drive its bounded retention envelope.
- ``time.py`` — retention existed since PR #283 but was UNBOUNDED, so a silent
  NAK plus one failed refresh showed a wrong value indefinitely.

Every test here pins one of those three, plus the two retention exits shared
by all platforms (convergence and TTL expiry).
"""

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eg4_web_monitor.base_entity import RETAINED_OPTIMISTIC_TTL
from custom_components.eg4_web_monitor.const import (
    PARAM_FUNC_BAT_CHARGE_CONTROL,
    PARAM_HOLD_PV_INPUT_MODE,
    SCHEDULE_TIME_TYPES,
)
from custom_components.eg4_web_monitor.number import SystemChargeSOCLimitNumber
from custom_components.eg4_web_monitor.select import (
    EG4BatteryChargeControlSelect,
    EG4OperatingModeSelect,
    EG4PVInputModeSelect,
    EG4SmartPortModeSelect,
)
from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_HTTP,
    DOMAIN,
)
from custom_components.eg4_web_monitor.time import EG4ScheduleTimeEntity
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import wire_coordinator_write_helpers

SERIAL = "1234567890"


@pytest.fixture
def config_entry():
    """Minimal CLOUD-mode config entry for real-coordinator tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Retention Test",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            "username": "user",
            "password": "pass",
            "plant_id": "plant_1",
        },
        options={},
        entry_id="retention_test",
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _coordinator(
    *,
    parameters: dict | None = None,
    sensors: dict | None = None,
    device_type: str = "inverter",
    refresh_device_ok: bool = True,
    refresh_all_ok: bool = True,
) -> MagicMock:
    """Coordinator whose post-write refreshes report a configurable outcome."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.has_http_api = MagicMock(return_value=True)
    coordinator.has_local_transport = MagicMock(return_value=False)
    coordinator.has_configured_local_transport = MagicMock(return_value=False)
    coordinator.is_local_only = MagicMock(return_value=False)
    coordinator.is_transport_link_down = MagicMock(return_value=False)
    coordinator.params_are_local_raw = MagicMock(return_value=False)
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh_device_parameters = AsyncMock(
        return_value=refresh_device_ok
    )
    coordinator.refresh_all_device_parameters = AsyncMock(return_value=refresh_all_ok)
    coordinator.refresh_inverter_params_if_linked = AsyncMock()
    coordinator.note_parameters_written = MagicMock()

    coordinator.data = {
        "devices": {
            SERIAL: {
                "type": device_type,
                "model": "FlexBOSS21",
                "sensors": sensors or {},
            }
        },
        "parameters": {SERIAL: parameters or {}},
    }

    coordinator.get_configured_control_modes = MagicMock(return_value=("soc", "soc"))

    inverter = MagicMock()
    inverter.set_operating_mode = AsyncMock(return_value=True)
    inverter.refresh = AsyncMock()
    # No attached transport: keeps ``params_are_local_raw`` on the CLOUD
    # branch, so the parameter cache below decodes as cloud-named params.
    inverter.transport = None
    coordinator.get_inverter_object = MagicMock(return_value=inverter)

    result = MagicMock()
    result.success = True
    coordinator.client.api.control.write_parameter = AsyncMock(return_value=result)
    coordinator.client.api.control.control_function = AsyncMock(return_value=result)
    coordinator.client.api.control.set_smart_port_mode = AsyncMock(return_value=result)
    coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
        return_value=result
    )
    coordinator.require_client = MagicMock(return_value=coordinator.client)

    wire_coordinator_write_helpers(coordinator)
    return coordinator


def _prep(entity: object, domain: str) -> None:
    """Attach the minimal HA plumbing an entity write path touches."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = f"{domain}.test_entity"  # type: ignore[attr-defined]
    entity.platform = None  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


def _device_data() -> dict:
    return {"type": "inverter", "model": "FlexBOSS21"}


def _expire(entity: object) -> None:
    """Move the retention deadline into the past."""
    entity._retention_expires = 0.0  # type: ignore[attr-defined]


def _schedule_spec(key: str = "ac_charge"):
    return next(spec for spec in SCHEDULE_TIME_TYPES if spec.key == key)


def _pack(hour: int, minute: int) -> int:
    return (hour & 0xFF) | ((minute & 0xFF) << 8)


# ── select.py: the #379 headline gap ─────────────────────────────────


class TestSelectRetainsAcknowledgedWrite:
    """All four selects must survive a failed post-write refresh.

    Pre-fix every one of them assigned ``_optimistic_state = None`` before
    (or without regard to) the refresh and discarded its boolean, so the UI
    snapped back to the stale pre-write option — the original #362 shape.
    """

    @pytest.mark.asyncio
    async def test_operating_mode_retains_on_failed_refresh(self):
        """Standby → Normal with a failed refresh keeps showing Normal."""
        coordinator = _coordinator(
            parameters={"FUNC_SET_TO_STANDBY": False}, refresh_device_ok=False
        )
        entity = EG4OperatingModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")
        assert entity.current_option == "Standby"

        await entity.async_select_option("Normal")

        assert entity.current_option == "Normal"
        assert entity._optimistic_retained is True

    @pytest.mark.asyncio
    async def test_operating_mode_clears_on_successful_refresh(self):
        """A completed refresh publishes device data, arming no retention."""
        coordinator = _coordinator(
            parameters={"FUNC_SET_TO_STANDBY": False}, refresh_device_ok=True
        )
        entity = EG4OperatingModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")

        await entity.async_select_option("Normal")

        assert entity._optimistic_retained is False
        assert entity._optimistic_state is None

    @pytest.mark.asyncio
    async def test_operating_mode_write_failure_still_reverts(self):
        """A FAILED write must still revert — retention is for the ack'd case."""
        coordinator = _coordinator(parameters={"FUNC_SET_TO_STANDBY": False})
        coordinator.get_inverter_object.return_value.set_operating_mode = AsyncMock(
            return_value=False
        )
        entity = EG4OperatingModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")

        with pytest.raises(Exception):
            await entity.async_select_option("Normal")

        assert entity._optimistic_state is None
        assert entity._optimistic_retained is False
        assert entity.current_option == "Standby"

    @pytest.mark.asyncio
    async def test_pv_input_mode_retains_on_failed_refresh(self):
        """PV Input Mode holds the written option across a failed refresh."""
        coordinator = _coordinator(
            parameters={PARAM_HOLD_PV_INPUT_MODE: 1}, refresh_device_ok=False
        )
        entity = EG4PVInputModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")
        pre_write = entity.current_option

        await entity.async_select_option("PV1 & PV2")

        assert pre_write != "PV1 & PV2"
        assert entity.current_option == "PV1 & PV2"
        assert entity._optimistic_retained is True

    @pytest.mark.asyncio
    async def test_battery_control_mode_retains_on_failed_refresh(self):
        """The group-wide all-device refresh reports failure the same way."""
        coordinator = _coordinator(
            parameters={PARAM_FUNC_BAT_CHARGE_CONTROL: False}, refresh_all_ok=False
        )
        entity = EG4BatteryChargeControlSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")
        assert entity.current_option == "SOC"

        await entity.async_select_option("Voltage")

        coordinator.refresh_all_device_parameters.assert_awaited_once()
        assert entity.current_option == "Voltage"
        assert entity._optimistic_retained is True

    @pytest.mark.asyncio
    async def test_smart_port_mode_retains_across_debounced_refresh(self):
        """``async_request_refresh`` is debounced: it returns before any new
        data exists, so clearing at that point republishes the pre-write mode
        with certainty. The written mode must survive until a tick converges."""
        coordinator = _coordinator(
            device_type="gridboss", sensors={"smart_port1_status": "unused"}
        )
        entity = EG4SmartPortModeSelect(coordinator, SERIAL, {}, 1)
        _prep(entity, "select")
        assert entity.current_option == "Unused"

        await entity.async_select_option("Smart Load")

        coordinator.async_request_refresh.assert_awaited_once()
        assert entity.current_option == "Smart Load"
        assert entity._optimistic_retained is True


class TestDeliberateSkipIsNotAFailure:
    """``_settle_acknowledged_write(refresh=None)`` = the caller skipped the
    refresh ON PURPOSE (the known-down cloud route, #485 F2).

    It takes the same retain branch as a failure but must not be logged as
    one — and it is still TTL-bounded, because a skip cannot tell an
    acknowledged-but-unreadable write apart from a silently NAKed one.
    """

    @staticmethod
    def _entity() -> EG4OperatingModeSelect:
        coordinator = _coordinator(parameters={"FUNC_SET_TO_STANDBY": False})
        entity = EG4OperatingModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")
        return entity

    @pytest.mark.asyncio
    async def test_skip_retains_without_warning(self, caplog):
        entity = self._entity()
        pre_write_state = entity._begin_optimistic_write("Normal")

        with caplog.at_level("WARNING"):
            await entity._settle_acknowledged_write("op mode", pre_write_state, None)

        assert entity._optimistic_retained is True
        assert entity.current_option == "Normal"
        assert "did not complete" not in caplog.text
        assert "Post-write refresh failed" not in caplog.text

    @pytest.mark.asyncio
    async def test_skip_is_still_ttl_bounded(self, caplog):
        entity = self._entity()
        pre_write_state = entity._begin_optimistic_write("Normal")
        await entity._settle_acknowledged_write("op mode", pre_write_state, None)
        _expire(entity)

        with caplog.at_level("WARNING"):
            entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.current_option == "Standby"
        assert "expired without device confirmation" in caplog.text

    @pytest.mark.asyncio
    async def test_reported_failure_still_warns(self, caplog):
        """The skip branch must not silence a GENUINE refresh failure."""
        entity = self._entity()
        pre_write_state = entity._begin_optimistic_write("Normal")

        async def _failed_refresh() -> bool:
            return False

        with caplog.at_level("WARNING"):
            await entity._settle_acknowledged_write(
                "op mode", pre_write_state, _failed_refresh
            )

        assert entity._optimistic_retained is True
        assert "did not complete" in caplog.text


class TestSelectRetentionExits:
    """Retention must be self-clearing on BOTH exits, never open-ended."""

    @staticmethod
    def _retained_entity() -> EG4OperatingModeSelect:
        coordinator = _coordinator(
            parameters={"FUNC_SET_TO_STANDBY": False}, refresh_device_ok=False
        )
        entity = EG4OperatingModeSelect(coordinator, SERIAL, _device_data())
        _prep(entity, "select")
        return entity

    @pytest.mark.asyncio
    async def test_retention_clears_when_device_confirms(self):
        """Fresh data carrying the written value ends retention."""
        entity = self._retained_entity()
        await entity.async_select_option("Normal")
        assert entity._optimistic_retained is True

        entity.coordinator.data["parameters"][SERIAL]["FUNC_SET_TO_STANDBY"] = True
        entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity._optimistic_state is None
        assert entity.current_option == "Normal"

    @pytest.mark.asyncio
    async def test_stale_tick_does_not_end_retention(self):
        """A tick still carrying the pre-write value is not convergence."""
        entity = self._retained_entity()
        await entity.async_select_option("Normal")

        entity._handle_coordinator_update()

        assert entity._optimistic_retained is True
        assert entity.current_option == "Normal"

    @pytest.mark.asyncio
    async def test_retention_expires_after_ttl(self, caplog):
        """The silent-NAK escape: an unconverged retention expires loudly.

        Without this bound a firmware-rejected write plus one failed refresh
        would show a value the device never applied forever, with no warning.
        """
        entity = self._retained_entity()
        await entity.async_select_option("Normal")
        assert entity._retention_expires > 0.0
        _expire(entity)

        with caplog.at_level("WARNING"):
            entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.current_option == "Standby"
        assert "expired without device confirmation" in caplog.text

    @pytest.mark.asyncio
    async def test_ttl_deadline_uses_the_shared_bound(self):
        """Select retention is bounded by the same TTL as switch retention."""
        entity = self._retained_entity()
        import time as time_module

        before = time_module.monotonic()
        await entity.async_select_option("Normal")

        assert entity._retention_expires >= before + RETAINED_OPTIMISTIC_TTL
        assert entity._retention_expires <= (
            time_module.monotonic() + RETAINED_OPTIMISTIC_TTL
        )


# ── number.py ────────────────────────────────────────────────────────


class TestNumberRetainsAcknowledgedWrite:
    """``optimistic_value_context`` cleared in a ``finally`` regardless of
    whether the post-write refresh actually happened."""

    @staticmethod
    def _entity(coordinator: MagicMock) -> SystemChargeSOCLimitNumber:
        entity = SystemChargeSOCLimitNumber(coordinator, SERIAL)
        _prep(entity, "number")
        return entity

    @pytest.mark.asyncio
    async def test_production_listener_runs_retention_convergence_and_ttl(self, caplog):
        """The registered coordinator callback must be the retention handler."""
        coordinator = _coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80},
            # The composed post-write path (#533) refreshes serial-scoped
            # parameters, not the broad all-device refresh.
            refresh_device_ok=False,
            refresh_all_ok=False,
        )
        entity = self._entity(coordinator)
        await entity.async_added_to_hass()

        callback = coordinator.async_add_listener.call_args.args[0]
        assert callback == entity._handle_coordinator_update

        await entity.async_set_native_value(95)
        assert entity._optimistic_retained is True
        _expire(entity)

        with caplog.at_level("WARNING"):
            callback()

        assert entity._optimistic_retained is False
        assert entity.native_value == 80
        assert "expired without device confirmation" in caplog.text

    @pytest.mark.asyncio
    async def test_retains_on_failed_refresh(self):
        """Write ack'd + refresh failed → the written value stays published."""
        coordinator = _coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80}, refresh_device_ok=False
        )
        entity = self._entity(coordinator)
        assert entity.native_value == 80

        await entity.async_set_native_value(95)

        assert entity.native_value == 95
        assert entity._optimistic_retained is True

    @pytest.mark.asyncio
    async def test_clears_on_successful_refresh(self):
        """A completed refresh settles on coordinator data as before."""
        coordinator = _coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80}, refresh_device_ok=True
        )
        entity = self._entity(coordinator)

        await entity.async_set_native_value(95)

        assert entity._optimistic_retained is False
        assert entity._optimistic_value is None

    @pytest.mark.asyncio
    async def test_write_failure_still_reverts(self):
        """A failed write clears and raises — unchanged by #379."""
        coordinator = _coordinator(parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80})
        failed = MagicMock()
        failed.success = False
        coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
            return_value=failed
        )
        entity = self._entity(coordinator)

        with pytest.raises(Exception):
            await entity.async_set_native_value(95)

        assert entity._optimistic_value is None
        assert entity._optimistic_retained is False
        assert entity.native_value == 80

    @pytest.mark.asyncio
    async def test_retention_expires_after_ttl(self, caplog):
        """Number retention is bounded, exactly like the switch's."""
        coordinator = _coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80}, refresh_device_ok=False
        )
        entity = self._entity(coordinator)
        await entity.async_set_native_value(95)
        _expire(entity)

        with caplog.at_level("WARNING"):
            entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.native_value == 80
        assert "expired without device confirmation" in caplog.text

    @pytest.mark.asyncio
    async def test_retention_clears_when_device_confirms(self):
        """Fresh data carrying the written value ends retention."""
        coordinator = _coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80}, refresh_device_ok=False
        )
        entity = self._entity(coordinator)
        await entity.async_set_native_value(95)

        coordinator.data["parameters"][SERIAL]["HOLD_SYSTEM_CHARGE_SOC_LIMIT"] = 95
        entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.native_value == 95


# ── time.py: the pre-existing UNBOUNDED retention ────────────────────


class TestScheduleTimeRetentionIsBounded:
    """PR #283 gave schedule times retention with no TTL escape.

    A silently-NAKed schedule write plus one failed refresh therefore left
    the entity showing a time the inverter never took, with no warning and
    no recovery short of a restart.
    """

    @staticmethod
    def _entity(coordinator: MagicMock) -> EG4ScheduleTimeEntity:
        entity = EG4ScheduleTimeEntity(
            coordinator, SERIAL, _schedule_spec(), 1, is_end=False
        )
        _prep(entity, "time")
        return entity

    @staticmethod
    def _coordinator(refresh_device_ok: bool) -> MagicMock:
        return _coordinator(
            parameters={
                "HOLD_AC_CHARGE_START_HOUR": 8,
                "HOLD_AC_CHARGE_START_MINUTE": 0,
            },
            refresh_device_ok=refresh_device_ok,
        )

    @pytest.mark.asyncio
    async def test_failed_refresh_still_retains(self):
        """The PR #283 behavior is preserved, not traded away for the bound."""
        coordinator = self._coordinator(refresh_device_ok=False)
        entity = self._entity(coordinator)
        assert entity.native_value == dt_time(8, 0)

        await entity.async_set_value(dt_time(20, 30))

        assert entity.native_value == dt_time(20, 30)
        assert entity._optimistic_retained is True

    @pytest.mark.asyncio
    async def test_retention_expires_after_ttl(self, caplog):
        """The new bound: an unconverged retention expires with a WARNING."""
        coordinator = self._coordinator(refresh_device_ok=False)
        entity = self._entity(coordinator)
        await entity.async_set_value(dt_time(20, 30))
        assert entity._retention_expires > 0.0
        _expire(entity)

        with caplog.at_level("WARNING"):
            entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.native_value == dt_time(8, 0)
        assert "expired without device confirmation" in caplog.text

    @pytest.mark.asyncio
    async def test_stale_tick_before_expiry_keeps_the_written_time(self):
        """Ticks inside the TTL keep retaining (unchanged from PR #283)."""
        coordinator = self._coordinator(refresh_device_ok=False)
        entity = self._entity(coordinator)
        await entity.async_set_value(dt_time(20, 30))

        entity._handle_coordinator_update()

        assert entity._optimistic_retained is True
        assert entity.native_value == dt_time(20, 30)

    @pytest.mark.asyncio
    async def test_convergence_clears_before_expiry(self):
        """Fresh parameter data carrying the written time ends retention."""
        coordinator = self._coordinator(refresh_device_ok=False)
        entity = self._entity(coordinator)
        await entity.async_set_value(dt_time(20, 30))

        params = coordinator.data["parameters"][SERIAL]
        params["HOLD_AC_CHARGE_START_HOUR"] = 20
        params["HOLD_AC_CHARGE_START_MINUTE"] = 30
        entity._handle_coordinator_update()

        assert entity._optimistic_retained is False
        assert entity.native_value == dt_time(20, 30)


# ── coordinator: the signal the platforms depend on ──────────────────


class TestRefreshAllDeviceParametersReportsOutcome:
    """``refresh_all_device_parameters`` returned None unconditionally, so a
    caller could not tell a completed group refresh from a failed one."""

    @pytest.mark.asyncio
    async def test_reports_success(self, hass, config_entry):
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, config_entry)
        coordinator.data = {"devices": {SERIAL: {"type": "inverter"}}}
        coordinator._refresh_device_parameters = AsyncMock(return_value=True)
        coordinator.async_request_refresh = AsyncMock()

        assert await coordinator.refresh_all_device_parameters() is True

    @pytest.mark.asyncio
    async def test_reports_failure_when_a_device_raises(self, hass, config_entry):
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, config_entry)
        coordinator.data = {
            "devices": {
                SERIAL: {"type": "inverter"},
                "0987654321": {"type": "inverter"},
            }
        }
        coordinator._refresh_device_parameters = AsyncMock(
            side_effect=[True, RuntimeError("range timeout")]
        )
        coordinator.async_request_refresh = AsyncMock()

        assert await coordinator.refresh_all_device_parameters() is False

    @pytest.mark.asyncio
    async def test_reports_failure_when_a_device_updates_no_cache(
        self, hass, config_entry
    ):
        """A silent no-op cannot be counted as a completed group refresh."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, config_entry)
        coordinator.data = {"devices": {SERIAL: {"type": "inverter"}}}
        coordinator._refresh_device_parameters = AsyncMock(return_value=False)
        coordinator.async_update_listeners = MagicMock()

        assert await coordinator.refresh_all_device_parameters() is False
        coordinator.async_update_listeners.assert_not_called()

    @pytest.mark.asyncio
    async def test_reports_failure_when_no_devices_are_known(self, hass, config_entry):
        """Nothing was refreshed, so nothing may be reported as refreshed."""
        from custom_components.eg4_web_monitor.coordinator import (
            EG4DataUpdateCoordinator,
        )

        config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, config_entry)
        coordinator.data = {"devices": {}}

        assert await coordinator.refresh_all_device_parameters() is False


class TestControlAvailabilityIgnoresLocalStalenessError:
    """Controls are setpoints: the LOCAL ``error`` staleness key must not
    blank them (documented contract on ``_sync_transport_link_state``;
    reasserted after the #534 review round)."""

    def test_number_stays_available_with_device_error_key(self):
        coordinator = _coordinator(parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 80})
        coordinator.data["devices"][SERIAL]["error"] = "Local transport link down"
        entity = SystemChargeSOCLimitNumber(coordinator, SERIAL)
        _prep(entity, "number")
        entity._control_discovery_supported = True

        assert entity._control_device_available() is True
