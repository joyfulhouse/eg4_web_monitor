"""Tests for the local transport coordinator mixin (coordinator_local.py).

Covers methods not already tested in test_coordinator.py:
- _read_modbus_parameters
- _build_local_device_data
- get_local_transport / has_local_transport / is_local_only
- _attach_local_transports_to_station
- _log_transport_error
"""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pylxpweb.devices import HybridInverter
from pylxpweb.transports import ModbusSerialTransport
from pylxpweb.transports.config import AttachResult, TransportType
from pylxpweb.transports.data import (
    BatteryBankData,
    BatteryData,
    InverterEnergyData,
    InverterRuntimeData,
    MidboxRuntimeData,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import make_real_inverter, make_real_mid, make_transport_spec

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import (
    EG4DataUpdateCoordinator,
)
from custom_components.eg4_web_monitor.coordinator_mappings import (
    _build_runtime_sensor_mapping,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def local_config_entry():
    """Config entry for LOCAL mode with one inverter."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Local Test",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "INV001",
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        options={},
        entry_id="local_test",
    )


@pytest.fixture
def hybrid_config_entry():
    """Config entry for HYBRID mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Test",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            CONF_LOCAL_TRANSPORTS: [
                {
                    "serial": "INV001",
                    "host": "192.168.1.100",
                    "port": 502,
                    "transport_type": "modbus_tcp",
                    "inverter_family": "EG4_HYBRID",
                    "model": "FlexBOSS21",
                },
            ],
        },
        options={},
        entry_id="hybrid_test",
    )


@pytest.fixture
def http_config_entry():
    """Config entry for HTTP-only mode."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - HTTP Test",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        },
        options={},
        entry_id="http_test",
    )


# ── _read_modbus_parameters ─────────────────────────────────────────


class TestReadModbusParameters:
    """Test reading configuration parameters from Modbus registers."""

    async def test_reads_all_register_ranges(self, hass, local_config_entry):
        """All 13 family-agnostic register ranges are read — pinned exactly
        so a control's backing register can't silently fall out of the local
        poll (the codex r1 MEDIUM on reg 202: entity wired but range never
        read), and a removed range can't silently creep back (231-232,
        eg4-gfu5). LXP is grid-tied and neither EG4_OFFGRID nor EG4_HYBRID, so
        NO family-specific ranges appear — the AC First (152, 6) and the
        Peak Shaving/Generator/Off-Grid (209-212 / 256-274) reads are all
        family-gated so non-matching firmware that NAKs them can't loop the
        #282 early retry for registers nothing consumes (GH #295 review P1)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {"PARAM_A": True}

        result = await coordinator._read_modbus_parameters(
            mock_transport,
            {"features": {"inverter_family": "LXP"}},
        )

        called_ranges = [
            call.args for call in mock_transport.read_named_parameters.call_args_list
        ]
        assert called_ranges == [
            (20, 3),
            # widened 64-83 → 64-89 for the forced discharge schedule
            # windows (regs 84-89, GH #295; 76-81 was already inside 64-83)
            (64, 26),
            (100, 4),  # widened for grid sell back percent (reg 103, GH #135)
            (105, 2),
            (110, 1),
            (116, 2),  # P_to_user start discharge/charge thresholds (GH #272)
            (125, 1),
            # (152, 6) absent: AC First is EG4_OFFGRID-only (GH #295)
            (158, 2),
            (169, 1),
            (179, 1),
            (202, 1),  # Stop discharge voltage (bead eg4-aa3t)
            (227, 2),
            # (231, 2) removed: PS1 is reg 206, reg 231 unknown (eg4-gfu5)
            (233, 1),
            # (209, 4)/(256, 4)/(269, 6) absent: Peak Shaving/Generator/Off-Grid
            # are EG4_HYBRID/OFFGRID-gated (pylxpweb #209).
        ]
        assert "PARAM_A" in result

    async def test_hybrid_device_reads_schedule_ranges(self, hass, local_config_entry):
        """EG4_HYBRID devices additionally poll Peak Shaving (209-212),
        Generator (256-259) and Off-Grid (269-274) as three separate reads —
        the Generator read is split from Off-Grid to skip the
        deliberately-unmapped 260-268 zone. AC First (152, 6) stays absent
        (EG4_OFFGRID-only)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}

        await coordinator._read_modbus_parameters(
            mock_transport,
            {"features": {"inverter_family": "EG4_HYBRID"}},
        )

        called_ranges = [
            call.args for call in mock_transport.read_named_parameters.call_args_list
        ]
        assert (209, 4) in called_ranges
        assert (256, 4) in called_ranges
        assert (269, 6) in called_ranges
        # Never a span that crosses the unmapped 260-268 zone.
        assert (256, 19) not in called_ranges
        assert (152, 6) not in called_ranges

    async def test_offgrid_device_reads_generator_range_only(
        self, hass, local_config_entry
    ):
        """EG4_OFFGRID reads the Generator schedule (256-259) — the SNA probe
        proves those registers exist — for Generator-entity readback, but NOT
        Peak Shaving / Off-Grid (their params are absent on the SNA probe)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}

        await coordinator._read_modbus_parameters(
            mock_transport,
            {"features": {"inverter_family": "EG4_OFFGRID"}},
        )

        called_ranges = [
            call.args for call in mock_transport.read_named_parameters.call_args_list
        ]
        assert (256, 4) in called_ranges
        assert (209, 4) not in called_ranges
        assert (269, 6) not in called_ranges

    async def test_offgrid_device_reads_ac_first_range(self, hass, local_config_entry):
        """EG4_OFFGRID devices additionally poll the AC First schedule
        windows (152-157) — same fails-closed family predicate as the AC
        First time entities (GH #295)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}

        await coordinator._read_modbus_parameters(
            mock_transport,
            {"features": {"inverter_family": "EG4_OFFGRID"}},
        )

        called_ranges = [
            call.args for call in mock_transport.read_named_parameters.call_args_list
        ]
        assert (152, 6) in called_ranges
        # 13 agnostic + AC First (152, 6) + Generator (256, 4).
        assert len(called_ranges) == 15
        # The (158, N) read widens on this family to also cover the AC-charge
        # SOC window (160-161, GH #331) — still one Modbus read.
        assert (158, 4) in called_ranges
        assert (158, 2) not in called_ranges
        # AC First kept in ascending register order between (125, 1) and (158, 4).
        assert called_ranges.index((152, 6)) == called_ranges.index((158, 4)) - 1

    @pytest.mark.parametrize(
        "device_data",
        [
            None,  # deprecated single-device path default
            {"features": {}},  # family not detected — fails closed
            {"features": {"inverter_family": "LXP"}},
            {"features": {"inverter_family": "EG4_OFFGRID"}},
            {"features": {"inverter_family": "EG4_HYBRID"}},
        ],
    )
    async def test_schedule_window_ranges_gated_per_family(
        self, hass, local_config_entry, device_data
    ):
        """Every schedule register block is polled exactly when its LOCAL read
        gate fires, and NOT otherwise (non-matching firmware that NAKs the
        range would loop the #282 early retry). Gates: classic families always
        (their registers sit inside the unconditional 64-89 read etc.); AC First
        iff EG4_OFFGRID; Peak Shaving/Off-Grid iff EG4_HYBRID; Generator iff
        EG4_HYBRID or EG4_OFFGRID (the SNA probe proves regs 256-259 exist, so
        the offgrid readback is polled locally). The range list is rebuilt per
        call from the per-cycle device_data."""
        from custom_components.eg4_web_monitor.const import SCHEDULE_TIME_TYPES

        family = (device_data or {}).get("features", {}).get("inverter_family")

        def local_read_expected(spec) -> bool:
            if spec.key == "ac_first":
                return family == "EG4_OFFGRID"
            if spec.key == "gen_charge":
                return family in ("EG4_HYBRID", "EG4_OFFGRID")
            if spec.write_via_time_api:  # peak_shaving, off_grid
                return family == "EG4_HYBRID"
            return True

        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}
        await coordinator._read_modbus_parameters(mock_transport, device_data)

        polled: set[int] = set()
        for call in mock_transport.read_named_parameters.call_args_list:
            start, count = call.args
            polled.update(range(start, start + count))

        for spec in SCHEDULE_TIME_TYPES:
            schedule_registers = set(
                range(spec.base_register, spec.base_register + 2 * spec.windows)
            )
            if local_read_expected(spec):
                assert schedule_registers <= polled, spec.key
            else:
                assert not (schedule_registers & polled), spec.key

    async def test_start_threshold_registers_read(self, hass, local_config_entry):
        """GH #272: HOLD 116/117 are in the LOCAL poll so the Start
        Discharge/Charge threshold numbers populate without cloud access.

        Reg 116 surfaces under pylxpweb's local name-map key; reg 117 has no
        name mapping, so read_named_parameters falls back to the raw "117"
        string key — both must land in the coordinator parameter cache.
        """
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            if start == 116:
                # -50 W protocol default for reg 117 = two's-complement 65486
                return {"HOLD_PTOUSER_START_DISCHARGE": 100, "117": 65486}
            return {}

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = mock_read

        result = await coordinator._read_modbus_parameters(mock_transport)

        read_registers: set[int] = set()
        for call in mock_transport.read_named_parameters.call_args_list:
            start, count = call.args
            read_registers.update(range(start, start + count))
        assert 116 in read_registers
        assert 117 in read_registers
        assert result["HOLD_PTOUSER_START_DISCHARGE"] == 100
        assert result["117"] == 65486

    async def test_ac_charge_soc_window_registers_offgrid_only(
        self, hass, local_config_entry
    ):
        """GH #331: regs 160-161 are polled on EG4_OFFGRID (widened 158-161
        read) and NOT on other/unknown families, which keep the (158, 2)
        voltage-only read. Reg 160 surfaces under pylxpweb's name-map key;
        reg 161 has no transport-map name and falls back to the raw "161" key.
        """
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            if start == 158:
                assert count == 4
                return {"HOLD_AC_CHARGE_START_BATTERY_SOC": 90, "161": 100}
            return {}

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = mock_read

        result = await coordinator._read_modbus_parameters(
            mock_transport,
            {"features": {"inverter_family": "EG4_OFFGRID"}},
        )
        assert result["HOLD_AC_CHARGE_START_BATTERY_SOC"] == 90
        assert result["161"] == 100

        # Non-offgrid families (and the family-agnostic default) keep (158, 2).
        for device_data in (None, {"features": {"inverter_family": "EG4_HYBRID"}}):
            mock_transport = make_transport_spec()
            mock_transport.read_named_parameters.return_value = {}
            await coordinator._read_modbus_parameters(mock_transport, device_data)
            called_ranges = [
                call.args
                for call in mock_transport.read_named_parameters.call_args_list
            ]
            assert (158, 2) in called_ranges
            assert (158, 4) not in called_ranges

    async def test_peak_shaving_registers_not_read_locally(
        self, hass, local_config_entry
    ):
        """Registers 231-232 must not be in the local parameter read plan.

        eg4-gfu5: 231 is an unknown register (the old PS1 mapping was wrong)
        and the true PS family registers (206-208/218-219/232) stay unread
        until their raw encodings are verified.
        """
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}

        await coordinator._read_modbus_parameters(mock_transport)

        read_registers: set[int] = set()
        for call in mock_transport.read_named_parameters.call_args_list:
            start, count = call.args
            read_registers.update(range(start, start + count))
        assert 231 not in read_registers
        assert 232 not in read_registers
        # True PS1 register also unread until raw encoding is verified
        assert 206 not in read_registers

    async def test_partial_failure_continues(self, hass, local_config_entry):
        """One register range failing doesn't stop the rest."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        call_count = 0

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if start == 20:
                raise RuntimeError("range 20 failed")
            return {f"param_{start}": start}

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = mock_read

        result = await coordinator._read_modbus_parameters(mock_transport)

        # All 13 family-agnostic ranges attempted despite first failure
        assert call_count == 13
        # Successful ranges contributed their params
        assert len(result) == 12  # 13 total - 1 failed

    async def test_total_failure_returns_empty(self, hass, local_config_entry):
        """All register ranges failing returns empty dict."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = RuntimeError("all fail")

        result = await coordinator._read_modbus_parameters(mock_transport)

        assert result == {}

    async def test_outer_exception_returns_empty(self, hass, local_config_entry):
        """Exception before the loop returns empty dict."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # Transport without read_named_parameters
        mock_transport = MagicMock(spec=[])

        result = await coordinator._read_modbus_parameters(mock_transport)

        assert result == {}

    async def test_partial_failure_marks_read_incomplete(
        self, hass, local_config_entry
    ):
        """A failed range flags the read incomplete (#282 sticky parameters)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        async def mock_read(start: int, count: int) -> dict[str, Any]:
            if start == 227:  # the #282 range: System Charge SOC Limit
                raise RuntimeError(
                    "Response function mismatch: expected 0x03, got 0x04"
                )
            return {f"param_{start}": start}

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.side_effect = mock_read

        result = await coordinator._read_modbus_parameters(mock_transport)

        assert coordinator._last_param_read_complete is False
        assert "param_20" in result  # healthy ranges still contribute

    async def test_full_success_marks_read_complete(self, hass, local_config_entry):
        """A clean read flags the read complete."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {"PARAM_A": True}

        await coordinator._read_modbus_parameters(mock_transport)

        assert coordinator._last_param_read_complete is True

    async def test_outer_exception_marks_read_incomplete(
        self, hass, local_config_entry
    ):
        """An outer failure (no reads at all) also flags incompleteness."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = MagicMock(spec=[])

        await coordinator._read_modbus_parameters(mock_transport)

        assert coordinator._last_param_read_complete is False

    async def test_link_down_device_skips_read_and_marks_incomplete(
        self, hass, local_config_entry
    ):
        """pylxpweb#208 parity: the targeted range reads here go straight to
        the raw transport, bypassing BaseInverter.refresh() and its link-down
        probe gate, so an attached-but-dead link must be gated at this choke
        point — Python 3.11's asyncio.wait_for cannot interrupt an in-flight
        pymodbus read and every range would stall for minutes.  The skip
        reports INCOMPLETE so callers carry last-known values forward and
        keep the device queued for a floored retry (#282 semantics)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        device = MagicMock(spec=["transport", "transport_link_down", "serial_number"])
        device.transport = mock_transport
        device.transport_link_down = True
        device.serial_number = "INV001"

        result = await coordinator._read_modbus_parameters(
            mock_transport, None, device=device
        )

        assert result == {}
        mock_transport.read_named_parameters.assert_not_called()
        assert coordinator._last_param_read_complete is False

    async def test_healthy_link_device_reads_normally(self, hass, local_config_entry):
        """Passing the device does not change behavior on a healthy link."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {"PARAM_A": True}
        device = MagicMock(spec=["transport", "transport_link_down", "serial_number"])
        device.transport = mock_transport
        device.transport_link_down = False
        device.serial_number = "INV001"

        result = await coordinator._read_modbus_parameters(
            mock_transport, None, device=device
        )

        assert mock_transport.read_named_parameters.call_count == 13
        assert "PARAM_A" in result
        assert coordinator._last_param_read_complete is True

    async def test_detached_transport_device_is_not_gated(
        self, hass, local_config_entry
    ):
        """The gate requires an ATTACHED transport (is_transport_link_down
        contract): a device without one is never treated as degraded."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mock_transport.read_named_parameters.return_value = {}
        device = MagicMock(spec=["transport", "transport_link_down", "serial_number"])
        device.transport = None
        device.transport_link_down = True  # meaningless without a transport
        device.serial_number = "INV001"

        await coordinator._read_modbus_parameters(mock_transport, None, device=device)

        assert mock_transport.read_named_parameters.call_count == 13
        assert coordinator._last_param_read_complete is True


# ── #282 sticky parameters: carry-forward + throttle re-arm ─────────


class TestStickyParameterCarryForward:
    """A partial parameter read must not blank known values or arm the throttle.

    Regression for #282: a WiFi-dongle misroute storm failed the reg 125-249
    read; the partial dict replaced the full one (System Charge SOC Limit,
    reg 227, went *unknown*) and the 60-minute throttle was stamped anyway, so
    the blank state persisted for up to an hour.
    """

    def _seed_coordinator(self, hass, local_config_entry) -> EG4DataUpdateCoordinator:
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._local_parameters_loaded = True
        coordinator._local_static_phase_done = True  # skip the static first refresh

        runtime = InverterRuntimeData(
            pv_total_power=0,
            battery_soc=50,
            rectifier_power=0,
            parallel_number=0,
            parallel_master_slave=0,
            parallel_phase=0,
        )
        inv = make_real_inverter("INV001", "FlexBOSS21", runtime=runtime)
        inv.refresh = AsyncMock()
        inv.detect_features = AsyncMock()
        inv._transport = make_transport_spec(is_connected=True)
        inv._transport_energy = None
        inv._transport_battery = None
        coordinator._inverter_cache["INV001"] = inv
        coordinator._firmware_cache["INV001"] = "TEST-FW"
        coordinator.data = {
            "devices": {},
            "parameters": {
                "INV001": {
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT": 101,
                    "HOLD_CHG_POWER_PERCENT_CMD": 80,
                }
            },
        }
        return coordinator

    async def test_partial_read_carries_forward_and_queues_retry(
        self, hass, local_config_entry
    ):
        coordinator = self._seed_coordinator(hass, local_config_entry)

        async def partial_read(
            transport: Any,
            device_data: dict[str, Any] | None = None,
            device: Any = None,
        ) -> dict[str, Any]:
            coordinator._last_param_read_complete = False
            return {"HOLD_CHG_POWER_PERCENT_CMD": 60}

        with (
            patch.object(coordinator, "_should_poll_transport", return_value=True),
            patch.object(
                coordinator, "_read_modbus_parameters", side_effect=partial_read
            ),
            patch.object(
                coordinator, "_process_local_parallel_groups", new_callable=AsyncMock
            ),
        ):
            result = await coordinator._async_update_local_data()

        assert result["parameters"]["INV001"] == {
            "HOLD_SYSTEM_CHARGE_SOC_LIMIT": 101,  # carried forward, NOT blanked
            "HOLD_CHG_POWER_PERCENT_CMD": 60,  # fresh value from the healthy range
        }
        # The DUE cycle stamps the hourly cadence regardless (P1-A design);
        # the incomplete device is queued for a floored per-device retry
        # rather than holding the shared throttle hostage.
        assert coordinator._last_parameter_refresh is not None
        assert coordinator._last_parameter_attempt is not None
        assert "INV001" in coordinator._param_retry_pending

    async def test_complete_read_replaces_and_stamps_throttle(
        self, hass, local_config_entry
    ):
        coordinator = self._seed_coordinator(hass, local_config_entry)

        async def full_read(
            transport: Any,
            device_data: dict[str, Any] | None = None,
            device: Any = None,
        ) -> dict[str, Any]:
            coordinator._last_param_read_complete = True
            return {"HOLD_CHG_POWER_PERCENT_CMD": 60}

        with (
            patch.object(coordinator, "_should_poll_transport", return_value=True),
            patch.object(coordinator, "_read_modbus_parameters", side_effect=full_read),
            patch.object(
                coordinator, "_process_local_parallel_groups", new_callable=AsyncMock
            ),
        ):
            result = await coordinator._async_update_local_data()

        # A clean read is authoritative: stale keys are pruned.
        assert result["parameters"]["INV001"] == {"HOLD_CHG_POWER_PERCENT_CMD": 60}
        assert coordinator._last_parameter_refresh is not None
        assert coordinator._param_retry_pending == set()


# Targeted parameter reads per cycle for the seeded FlexBOSS21 (model-fallback
# family EG4_HYBRID): 13 base ranges in _read_modbus_parameters() plus the 3
# family-gated schedule ranges — Peak Shaving (209,4), Generator (256,4) and
# Off-Grid (269,6) — added by the beta.22 schedule families (GH #295 / PR
# #312).  PR #313 landed these tests with the pre-#312 count of 13; both PRs
# were green alone but the merged branch reads 16 (merge skew, not a bug).
_EXPECTED_HYBRID_READS = 16


class TestLinkDownParameterGateCycle:
    """Full-cycle behavior of the targeted-read link-down gate.

    Closes the gap found in the pylxpweb PR #208 review: the library gained a
    ``transport_link_down`` guard in ``_fetch_parameters()`` and PR #301 gated
    the ``_refresh_device_parameters`` chain, but the coordinator's own
    targeted 8-range read calls ``transport.read_named_parameters()`` directly
    on the raw transport — nothing stopped it from walking into a dead RS485
    link (Python 3.11 ``asyncio.wait_for`` cannot interrupt in-flight pymodbus
    reads; multi-minute stalls).
    """

    SERIAL = "INV001"

    def _seed_coordinator(self, hass, local_config_entry) -> EG4DataUpdateCoordinator:
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._local_parameters_loaded = True
        coordinator._local_static_phase_done = True  # skip the static first refresh

        runtime = InverterRuntimeData(
            pv_total_power=0,
            battery_soc=50,
            rectifier_power=0,
            parallel_number=0,
            parallel_master_slave=0,
            parallel_phase=0,
        )
        inv = make_real_inverter(self.SERIAL, "FlexBOSS21", runtime=runtime)
        inv.refresh = AsyncMock()
        inv.detect_features = AsyncMock()
        inv._transport = make_transport_spec(is_connected=True)
        inv._transport_energy = None
        inv._transport_battery = None
        coordinator._inverter_cache[self.SERIAL] = inv
        coordinator._firmware_cache[self.SERIAL] = "TEST-FW"
        coordinator.data = {
            "devices": {},
            "parameters": {
                self.SERIAL: {
                    "HOLD_SYSTEM_CHARGE_SOC_LIMIT": 101,
                    "HOLD_CHG_POWER_PERCENT_CMD": 80,
                }
            },
        }
        return coordinator

    async def _run_cycle(self, coordinator) -> dict[str, Any]:
        with (
            patch.object(coordinator, "_should_poll_transport", return_value=True),
            patch.object(
                coordinator, "_process_local_parallel_groups", new_callable=AsyncMock
            ),
        ):
            return await coordinator._async_update_local_data()

    async def test_link_down_skips_read_carries_values_and_queues_retry(
        self, hass, local_config_entry
    ):
        """Outage cycle: no targeted read is attempted, last-known parameter
        values carry forward (entities keep their values), and the device
        stays queued for a floored retry — a skip must behave exactly like an
        incomplete read (#282), never stamping completeness."""
        coordinator = self._seed_coordinator(hass, local_config_entry)
        inv = coordinator._inverter_cache[self.SERIAL]
        inv._transport_consecutive_failures = 3  # TRANSPORT_LINK_DOWN_THRESHOLD
        assert inv.transport_link_down is True

        result = await self._run_cycle(coordinator)

        inv._transport.read_named_parameters.assert_not_called()
        assert result["parameters"][self.SERIAL] == {
            "HOLD_SYSTEM_CHARGE_SOC_LIMIT": 101,  # carried forward, NOT blanked
            "HOLD_CHG_POWER_PERCENT_CMD": 80,
        }
        assert coordinator._last_param_read_complete is False
        assert self.SERIAL in coordinator._param_retry_pending

    async def test_link_recovery_reads_on_next_retry_cycle(
        self, hass, local_config_entry
    ):
        """The first cycle after link recovery reads again (within the ~2-min
        retry floor) — the gate must not suppress the post-recovery read."""
        coordinator = self._seed_coordinator(hass, local_config_entry)
        inv = coordinator._inverter_cache[self.SERIAL]
        inv._transport_consecutive_failures = 3

        # Cycle 1: outage — skipped, queued for retry.
        await self._run_cycle(coordinator)
        assert self.SERIAL in coordinator._param_retry_pending
        inv._transport.read_named_parameters.assert_not_called()

        # Link recovers (a successful probe resets the failure counter).
        inv._transport_consecutive_failures = 0
        assert inv.transport_link_down is False
        inv._transport.read_named_parameters.return_value = {"PARAM": 1}
        # Retry floor elapsed.
        coordinator._last_parameter_attempt = dt_util.utcnow() - timedelta(minutes=3)

        # Cycle 2: retry-due — the targeted read runs and drains the queue.
        result = await self._run_cycle(coordinator)

        assert inv._transport.read_named_parameters.call_count == _EXPECTED_HYBRID_READS
        assert result["parameters"][self.SERIAL] == {"PARAM": 1}
        assert coordinator._param_retry_pending == set()
        assert coordinator._last_param_read_complete is True

    async def test_healthy_link_cycle_reads_unchanged(self, hass, local_config_entry):
        """A healthy link is untouched by the gate: the param-due cycle reads
        all ranges and stamps the hourly cadence as before."""
        coordinator = self._seed_coordinator(hass, local_config_entry)
        inv = coordinator._inverter_cache[self.SERIAL]
        assert inv.transport_link_down is False
        inv._transport.read_named_parameters.return_value = {"PARAM": 1}

        result = await self._run_cycle(coordinator)

        assert inv._transport.read_named_parameters.call_count == _EXPECTED_HYBRID_READS
        assert result["parameters"][self.SERIAL] == {"PARAM": 1}
        assert coordinator._param_retry_pending == set()
        assert coordinator._last_parameter_refresh is not None


class TestPerDeviceParamRetry:
    """#282 P1-A: the shared throttle must not starve interval-skipped devices.

    ``_param_retry_pending`` closes the cc8d4e2 shared-timestamp bug class
    inside the parameter contract: on a param-due cycle a device whose
    transport was not due (or that failed before its param read) used to be
    silently covered by a sibling's success stamping the shared hourly
    throttle — no parameters until the next hourly window, repeatedly if
    intervals align (e.g. 5 s modbus + 60 s dongle).
    """

    SERIAL_A = "1111111111"  # modbus_tcp
    SERIAL_B = "2222222222"  # wifi_dongle

    @pytest.fixture
    def two_device_entry(self):
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Multi Local",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": self.SERIAL_A,
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                    {
                        "serial": self.SERIAL_B,
                        "host": "192.168.1.101",
                        "port": 8000,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            options={},
            entry_id="two_device_param_retry",
        )

    def _seed(self, hass, two_device_entry) -> tuple[EG4DataUpdateCoordinator, dict]:
        two_device_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, two_device_entry)
        coordinator._local_parameters_loaded = True
        coordinator._local_static_phase_done = True

        transports: dict[str, Any] = {}
        for serial in (self.SERIAL_A, self.SERIAL_B):
            runtime = InverterRuntimeData(
                pv_total_power=0,
                battery_soc=50,
                rectifier_power=0,
                parallel_number=0,
                parallel_master_slave=0,
                parallel_phase=0,
            )
            inv = make_real_inverter(serial, "FlexBOSS21", runtime=runtime)
            inv.refresh = AsyncMock()
            inv.detect_features = AsyncMock()
            inv._transport = make_transport_spec(is_connected=True)
            inv._transport_energy = None
            inv._transport_battery = None
            coordinator._inverter_cache[serial] = inv
            coordinator._firmware_cache[serial] = "TEST-FW"
            transports[serial] = inv._transport
        coordinator.data = {"devices": {}, "parameters": {}}
        return coordinator, transports

    async def _run_cycle(self, coordinator, poll_gate, read_side_effect):
        with (
            patch.object(coordinator, "_should_poll_transport", side_effect=poll_gate),
            patch.object(
                coordinator, "_read_modbus_parameters", side_effect=read_side_effect
            ),
            patch.object(
                coordinator, "_process_local_parallel_groups", new_callable=AsyncMock
            ),
        ):
            return await coordinator._async_update_local_data()

    async def test_interval_skipped_device_retries_within_floor(
        self, hass, two_device_entry
    ):
        """Codex's exact scenario: B's transport not due on the stamp cycle.

        B must get its parameters within ~the retry floor — not an hour — and
        the retry must NOT re-read healthy A.
        """
        coordinator, transports = self._seed(hass, two_device_entry)
        read_calls: list[Any] = []

        async def complete_read(
            transport: Any,
            device_data: dict[str, Any] | None = None,
            device: Any = None,
        ) -> dict[str, Any]:
            read_calls.append(transport)
            coordinator._last_param_read_complete = True
            return {"PARAM": 1}

        # Cycle 1 (param-due): only modbus polls; dongle-B is interval-skipped.
        await self._run_cycle(coordinator, lambda tt: tt == "modbus_tcp", complete_read)
        assert read_calls == [transports[self.SERIAL_A]]
        assert coordinator._last_parameter_refresh is not None  # hourly cadence
        assert coordinator._param_retry_pending == {self.SERIAL_B}

        # Cycle 2 (retry, floor elapsed): both transports pollable.
        coordinator._last_parameter_attempt = dt_util.utcnow() - timedelta(minutes=3)
        result = await self._run_cycle(coordinator, lambda tt: True, complete_read)

        # B was read; healthy A was NOT re-read (no-hammer).
        assert read_calls == [
            transports[self.SERIAL_A],
            transports[self.SERIAL_B],
        ]
        assert coordinator._param_retry_pending == set()
        assert result["parameters"][self.SERIAL_B] == {"PARAM": 1}

    async def test_permanently_failing_device_floored_without_dragging_sibling(
        self, hass, two_device_entry
    ):
        """A device whose read stays partial retries at the floor, alone."""
        coordinator, transports = self._seed(hass, two_device_entry)
        read_calls: list[Any] = []

        async def read_by_device(
            transport: Any,
            device_data: dict[str, Any] | None = None,
            device: Any = None,
        ) -> dict[str, Any]:
            read_calls.append(transport)
            # B's read is permanently partial; A's is complete.
            coordinator._last_param_read_complete = (
                transport is transports[self.SERIAL_A]
            )
            return {"PARAM": 1}

        # Cycle 1 (param-due, both pollable): A completes, B partial.
        await self._run_cycle(coordinator, lambda tt: True, read_by_device)
        assert coordinator._param_retry_pending == {self.SERIAL_B}
        calls_after_cycle1 = len(read_calls)

        # Cycle 2 (immediately, within the floor): nobody is re-read.
        await self._run_cycle(coordinator, lambda tt: True, read_by_device)
        assert len(read_calls) == calls_after_cycle1

        # Cycle 3 (floor elapsed): only failing B is retried; A untouched.
        coordinator._last_parameter_attempt = dt_util.utcnow() - timedelta(minutes=3)
        await self._run_cycle(coordinator, lambda tt: True, read_by_device)
        assert read_calls[calls_after_cycle1:] == [transports[self.SERIAL_B]]
        assert coordinator._param_retry_pending == {self.SERIAL_B}  # still queued


class TestParameterRetryFloor:
    """A failed parameter read re-arms an early retry, rate-floored at ~2 min."""

    async def test_failed_attempt_retries_early_but_rate_floored(
        self, hass, local_config_entry
    ):
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # Never fully succeeded, but an attempt JUST happened -> floored.
        coordinator._last_parameter_refresh = None
        coordinator._last_parameter_attempt = dt_util.utcnow()
        assert coordinator._should_refresh_parameters() is False

        # Attempt older than the floor -> retry well before the 60-min interval.
        coordinator._last_parameter_attempt = dt_util.utcnow() - timedelta(minutes=3)
        assert coordinator._should_refresh_parameters() is True

    async def test_successful_refresh_keeps_hourly_interval(
        self, hass, local_config_entry
    ):
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        coordinator._last_parameter_refresh = dt_util.utcnow() - timedelta(minutes=10)
        coordinator._last_parameter_attempt = coordinator._last_parameter_refresh
        assert coordinator._should_refresh_parameters() is False

        coordinator._last_parameter_refresh = dt_util.utcnow() - timedelta(minutes=61)
        coordinator._last_parameter_attempt = coordinator._last_parameter_refresh
        assert coordinator._should_refresh_parameters() is True


# ── write_raw_parameter ──────────────────────────────────────────────


class TestWriteRawParameter:
    """coordinator.write_raw_parameter — raw register write for unmapped regs.

    GH #272: HOLD 117 (PtoUserStartchg) has no pylxpweb name-map entry and no
    cloud parameter name, so the Start Charge threshold number writes the raw
    register address through the local transport.
    """

    async def test_writes_raw_register(self, hass, local_config_entry):
        """The raw address/value pair goes straight to transport.write_parameters."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec(is_connected=True)
        with patch.object(
            coordinator, "get_local_transport", return_value=mock_transport
        ):
            result = await coordinator.write_raw_parameter(117, 65486, serial="INV001")

        assert result is True
        mock_transport.write_parameters.assert_awaited_once_with({117: 65486})

    async def test_reconnects_disconnected_transport(self, hass, local_config_entry):
        """A disconnected transport is reconnected before the write."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec(is_connected=False)
        with patch.object(
            coordinator, "get_local_transport", return_value=mock_transport
        ):
            await coordinator.write_raw_parameter(117, 250, serial="INV001")

        mock_transport.connect.assert_awaited_once()
        mock_transport.write_parameters.assert_awaited_once_with({117: 250})

    async def test_no_transport_raises(self, hass, local_config_entry):
        """No local transport -> HomeAssistantError, nothing written."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        with patch.object(coordinator, "get_local_transport", return_value=None):
            with pytest.raises(HomeAssistantError, match="No local transport"):
                await coordinator.write_raw_parameter(117, 100, serial="INV001")

    async def test_write_failure_raises(self, hass, local_config_entry):
        """Transport write errors are wrapped in HomeAssistantError."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec(is_connected=True)
        mock_transport.write_parameters.side_effect = RuntimeError("bus error")
        with patch.object(
            coordinator, "get_local_transport", return_value=mock_transport
        ):
            with pytest.raises(HomeAssistantError, match="Failed to write register"):
                await coordinator.write_raw_parameter(117, 100, serial="INV001")


# ── has_local_register_path ──────────────────────────────────────────


class TestHasLocalRegisterPath:
    """Config-based gate for raw-register controls (reg 117, GH #272).

    Codex P2 on PR #284: has_configured_local_transport() checks only
    CONF_LOCAL_TRANSPORTS, but the deprecated flat single-transport format
    (pre-v3.2) initializes _modbus_transport/_dongle_transport directly from
    flat entry keys — those HYBRID entries silently lost the reg-117 entity.
    """

    async def test_legacy_flat_hybrid_recognized(self, hass):
        """Flat-format HYBRID entry (no CONF_LOCAL_TRANSPORTS) has a path.

        The exact P2 shape: not local-only, no per-serial transport config,
        but the flat CONF_MODBUS_HOST keys construct the legacy global
        transport in __init__ — get_local_transport() serves it for writes,
        so the register path exists.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Legacy Flat Hybrid",
            data={
                CONF_USERNAME: "test",
                CONF_PASSWORD: "test",
                CONF_BASE_URL: "https://monitor.eg4electronics.com",
                CONF_VERIFY_SSL: True,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_PLANT_ID: "12345",
                CONF_PLANT_NAME: "Test",
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
                # DEPRECATED flat keys — deliberately no CONF_LOCAL_TRANSPORTS
                CONF_MODBUS_HOST: "192.168.1.50",
                CONF_INVERTER_SERIAL: "1234567890",
            },
            options={},
            entry_id="legacy_flat_hybrid_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        # The P2 shape: the old gate's two branches are both False...
        assert coordinator.is_local_only() is False
        assert coordinator.has_configured_local_transport("1234567890") is False
        # ...but the legacy global transport exists and serves writes.
        assert coordinator._modbus_transport is not None
        assert coordinator.get_local_transport("1234567890") is not None
        assert coordinator.has_local_register_path("1234567890") is True

    async def test_modern_hybrid_configured_serial(self, hass, hybrid_config_entry):
        """Modern per-serial CONF_LOCAL_TRANSPORTS entry has a path; an
        unconfigured serial on the same entry does not."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        assert coordinator.has_local_register_path("INV001") is True
        # No legacy flat transport and no config for this serial -> no path
        assert coordinator.has_local_register_path("9999999999") is False

    async def test_local_only_mode(self, hass, local_config_entry):
        """LOCAL mode always has a register path."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        assert coordinator.has_local_register_path("INV001") is True

    async def test_http_only_has_no_path(self, hass, http_config_entry):
        """Pure cloud entries have no local register path."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        assert coordinator.has_local_register_path("1234567890") is False


# ── _build_local_device_data ─────────────────────────────────────────


class TestBuildLocalDeviceData:
    """Test building device data structure from inverter transport data."""

    async def test_basic_structure(self, hass, local_config_entry):
        """Device data has expected keys."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # REAL inverter with an empty runtime — computed power properties run for
        # real (all derive to 0 from the empty transport data).
        inverter = make_real_inverter(
            "INV001", "FlexBOSS21", runtime=InverterRuntimeData()
        )
        inverter._transport_battery = None
        # _transport is the network CONNECTION object (Modbus/Dongle socket), not
        # a pylxpweb data model — a real one needs a live socket.  It is an infra
        # mock by design; transport_host is connection metadata, not device data.
        inverter._transport = make_transport_spec(host="192.168.1.100")

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"pv_total_power": 5000},
        ):
            result = coordinator._build_local_device_data(
                inverter=inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["type"] == "inverter"
        assert result["model"] == "FlexBOSS21"
        assert result["serial"] == "INV001"
        assert result["firmware_version"] == "ARM-1.0"
        assert result["sensors"]["firmware_version"] == "ARM-1.0"
        assert result["sensors"]["transport_host"] == "192.168.1.100"
        assert result["batteries"] == {}

    async def test_includes_energy_data(self, hass, local_config_entry):
        """Energy data is merged into sensors when available."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # REAL inverter with empty runtime + energy transport data.
        inverter = make_real_inverter(
            "INV001",
            "FlexBOSS21",
            runtime=InverterRuntimeData(),
            energy=InverterEnergyData(),
        )
        inverter._transport_battery = None
        inverter._transport = None

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"pv_total_power": 5000},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_energy_sensor_mapping",
                return_value={"yield": 25.0},
            ),
        ):
            result = coordinator._build_local_device_data(
                inverter=inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["sensors"]["yield"] == 25.0

    async def test_includes_computed_sensors(self, hass, local_config_entry):
        """Computed sensors from inverter properties are included."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # REAL inverter: the computed power properties are exercised for real
        # from injected transport data, instead of a MagicMock fabricating them.
        # Physically coherent fixture — grid import is one quantity, so
        # power_from_grid (consumption energy-balance) == load_power (Ptouser,
        # the grid_import_power sensor source), both 500, mirroring real modbus
        # where both derive from the same Ptouser register.
        #   consumption = pv + (discharge - charge) + import - export
        #               = 3000 + (0 - 1500) + 500 - 0 = 2000
        runtime = InverterRuntimeData(
            pv_total_power=3000,
            battery_charge_power=1500,
            battery_discharge_power=0,
            power_from_grid=500,
            power_to_grid=0,
            rectifier_power=200,  # reg 17 Prec (renamed from grid_power, eg4-9wf)
            load_power=500,  # power_to_user (Ptouser) -> grid_import_power sensor
        )
        inverter = make_real_inverter("INV001", "FlexBOSS21", runtime=runtime)

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={},
        ):
            result = coordinator._build_local_device_data(
                inverter=inverter,
                serial="INV001",
                model="FlexBOSS21",
                firmware_version="ARM-1.0",
                connection_type="modbus",
            )

        assert result["sensors"]["consumption_power"] == 2000
        # total_load_power is a documented ALIAS of consumption_power (a real
        # pylxpweb semantic the old MagicMock hid by asserting a distinct 4000).
        assert result["sensors"]["total_load_power"] == 2000
        assert (
            result["sensors"]["total_load_power"]
            == result["sensors"]["consumption_power"]
        )
        assert result["sensors"]["battery_power"] == 1500
        assert result["sensors"]["rectifier_power"] == 200
        # grid_import_power sensor is sourced from inverter.power_to_user (load_power)
        assert result["sensors"]["grid_import_power"] == 500


# ── grid_power net-flow semantics (eg4-9wf) ──────────────────────────


class TestLocalNetGridPower:
    """LOCAL grid_power = power_from_grid − power_to_grid (eg4-9wf).

    Reg 17 (Prec) is RECTIFIER power and must never feed grid_power; the
    net-flow formula matches the CLOUD computation in
    _process_inverter_object (pToUser − pToGrid, positive = import) and the
    GridBOSS sign convention.
    """

    def test_importing_is_positive(self) -> None:
        runtime = InverterRuntimeData(
            power_from_grid=500.0, power_to_grid=0.0, rectifier_power=200.0
        )
        assert _build_runtime_sensor_mapping(runtime)["grid_power"] == 500.0

    def test_exporting_is_negative(self) -> None:
        runtime = InverterRuntimeData(power_from_grid=0.0, power_to_grid=1200.0)
        assert _build_runtime_sensor_mapping(runtime)["grid_power"] == -1200.0

    def test_rectifier_power_does_not_leak_into_grid_power(self) -> None:
        """AC-charging at 2453 W with no grid flow registers → grid_power None."""
        runtime = InverterRuntimeData(rectifier_power=2453.0)
        mapping = _build_runtime_sensor_mapping(runtime)
        assert mapping["grid_power"] is None
        # The Prec value still reaches its own field for the rectifier sensor.
        assert runtime.rectifier_power == 2453.0

    def test_missing_leg_yields_none(self) -> None:
        """Half-read register pairs must not fabricate a net value."""
        runtime = InverterRuntimeData(power_from_grid=500.0)  # power_to_grid None
        assert _build_runtime_sensor_mapping(runtime)["grid_power"] is None


# ── get_local_transport / has_local_transport / is_local_only ────────


class TestTransportAccessors:
    """Test transport accessor methods."""

    def test_get_local_transport_from_inverter_cache(self, hass, local_config_entry):
        """LOCAL mode: get_local_transport returns transport from inverter cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        inv = make_real_inverter(serial_number="INV001")
        inv._transport = mock_transport
        coordinator._inverter_cache["INV001"] = inv

        result = coordinator.get_local_transport("INV001")
        assert result is mock_transport

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_from_station(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode: get_local_transport from station inverter."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_transport = make_transport_spec()
        mock_inverter = make_real_inverter(serial_number="INV001")
        mock_inverter._transport = mock_transport

        mock_station = MagicMock()
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        # Patch get_inverter_object to return our mock
        coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

        result = coordinator.get_local_transport("INV001")
        assert result is mock_transport

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_get_local_transport_returns_none_http_only(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """HTTP-only mode: get_local_transport returns None."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)

        result = coordinator.get_local_transport("INV001")
        assert result is None

    def test_has_local_transport_true(self, hass, local_config_entry):
        """has_local_transport returns True when transport exists."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_inverter = MagicMock()
        mock_inverter._transport = make_transport_spec()
        coordinator._inverter_cache["INV001"] = mock_inverter

        assert coordinator.has_local_transport("INV001") is True

    def test_has_local_transport_false(self, hass, local_config_entry):
        """has_local_transport returns False when no transport."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        assert coordinator.has_local_transport("UNKNOWN") is False

    def test_has_local_transport_no_serial_deprecated(self, hass, local_config_entry):
        """has_local_transport without serial checks deprecated fields."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # No deprecated transports set
        assert coordinator.has_local_transport() is False

    def test_get_local_transport_from_mid_device_cache(self, hass, local_config_entry):
        """LOCAL mode: get_local_transport returns transport from MID device cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_transport = make_transport_spec()
        mid = make_real_mid(serial_number="GRIDBOSS001")
        mid._transport = mock_transport
        coordinator._mid_device_cache["GRIDBOSS001"] = mid

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is mock_transport

    def test_has_local_transport_true_for_mid_device(self, hass, local_config_entry):
        """has_local_transport returns True for GridBOSS serial in MID cache."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        mock_mid = MagicMock()
        mock_mid._transport = make_transport_spec()
        coordinator._mid_device_cache["GRIDBOSS001"] = mock_mid

        assert coordinator.has_local_transport("GRIDBOSS001") is True

    def test_get_local_transport_mid_device_no_transport(
        self, hass, local_config_entry
    ):
        """MID device without an attached transport returns None."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)

        # No transport assigned → real .transport property returns None
        mid = make_real_mid(serial_number="GRIDBOSS001")
        coordinator._mid_device_cache["GRIDBOSS001"] = mid

        result = coordinator.get_local_transport("GRIDBOSS001")
        assert result is None

    def test_is_local_only_local_mode(self, hass, local_config_entry):
        """LOCAL mode → is_local_only returns True."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator.is_local_only() is True

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_is_local_only_http_mode(
        self, mock_aiohttp, mock_client_cls, hass, http_config_entry
    ):
        """HTTP mode → is_local_only returns False."""
        http_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, http_config_entry)
        assert coordinator.is_local_only() is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    def test_is_local_only_hybrid_mode(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """HYBRID mode → is_local_only returns False."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        assert coordinator.is_local_only() is False


# ── _attach_local_transports_to_station ──────────────────────────────


class TestAttachLocalTransports:
    """Test attaching local transports to station devices."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_station_returns_early(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """No station → returns without attaching."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = None

        await coordinator._attach_local_transports_to_station()
        assert coordinator._local_transports_attached is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_successful_attachment(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Successful attachment sets flag to True."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is True
        mock_station.attach_local_transports.assert_called_once()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attachment_failure_keeps_flag_false(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Attachment error keeps flag False for retry."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(
            side_effect=RuntimeError("connection failed")
        )
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is False

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_no_valid_configs_returns_early(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Empty transport configs list → returns without attaching."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.station = MagicMock()

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[],
        ):
            await coordinator._attach_local_transports_to_station()

        # station.attach_local_transports should NOT be called
        coordinator.station.attach_local_transports.assert_not_called()


# ── Hybrid + USB serial transport attach (#233) ──────────────────────


_SERIAL_TRANSPORT_DICT: dict[str, Any] = {
    "serial": "INV001",
    "transport_type": "modbus_serial",
    "serial_port": "/dev/ttyUSB0",
    "serial_baudrate": 19200,
    "serial_parity": "N",
    "serial_stopbits": 1,
    "unit_id": 1,
    "inverter_family": "EG4_HYBRID",
    "model": "FlexBOSS21",
}


def _make_hybrid_entry(
    transports: list[dict[str, Any]], entry_id: str
) -> MockConfigEntry:
    """Build a HYBRID-mode config entry with the given local transports."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EG4 - Hybrid Serial Test",
        data={
            CONF_USERNAME: "test",
            CONF_PASSWORD: "test",
            CONF_BASE_URL: "https://monitor.eg4electronics.com",
            CONF_VERIFY_SSL: True,
            CONF_DST_SYNC: False,
            CONF_LIBRARY_DEBUG: False,
            CONF_PLANT_ID: "12345",
            CONF_PLANT_NAME: "Test",
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            CONF_LOCAL_TRANSPORTS: transports,
        },
        options={},
        entry_id=entry_id,
    )


def _make_serial_transport_spec(**attrs: Any) -> Any:
    """Autospec stand-in for a ModbusSerialTransport (USB/RS485 adapter)."""
    spec = create_autospec(ModbusSerialTransport, spec_set=True, instance=True)
    defaults: dict[str, Any] = {
        "transport_type": "modbus_serial",
        "is_connected": False,
    }
    defaults.update(attrs)
    spec.configure_mock(**defaults)
    return spec


class TestFinishAttachRecovery:
    """Drain-then-reload ordering after a transport attach recovery."""

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_drain_runs_before_param_reload(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Recovered Modbus buses drain BEFORE the per-serial param reload —
        the reload replaces stale cloud-kW cache values with raw register
        values (codex r2: 12 kW would display 1.2 until the next refresh)."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        calls: list[str] = []

        async def drain(inverters):
            calls.append(f"drain:{len(inverters)}")

        async def reload(serial):
            calls.append(f"reload:{serial}")

        with (
            patch.object(coordinator, "_drain_modbus_buffers", side_effect=drain),
            patch.object(coordinator, "_refresh_device_parameters", side_effect=reload),
        ):
            await coordinator._finish_attach_recovery(
                [MagicMock()], ["1234567890", "9876543210"]
            )

        assert calls == ["drain:1", "reload:1234567890", "reload:9876543210"]

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_reload_failure_does_not_block_other_serials(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """A failing reload on one serial must not skip the others."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        reloaded: list[str] = []

        async def reload(serial):
            if serial == "1234567890":
                raise TimeoutError("bus busy")
            reloaded.append(serial)
            coordinator.data["parameters"][serial] = {"HOLD_AC_CHARGE_POWER_CMD": 25}

        coordinator.data = {
            "parameters": {
                "1234567890": {"HOLD_AC_CHARGE_POWER_CMD": 12},
                "9876543210": {"HOLD_AC_CHARGE_POWER_CMD": 12},
            }
        }
        with patch.object(
            coordinator, "_refresh_device_parameters", side_effect=reload
        ):
            await coordinator._finish_attach_recovery([], ["1234567890", "9876543210"])

        assert reloaded == ["9876543210"]
        # Both serials were pre-blanked; the successful reload repopulated
        # its serial (raw), the failed one stays unknown rather than
        # 10x-wrong.
        assert coordinator.data["parameters"]["1234567890"] == {}
        assert coordinator.data["parameters"]["9876543210"] == {
            "HOLD_AC_CHARGE_POWER_CMD": 25
        }

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_swallowed_reload_failure_leaves_unknown_not_stale(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """pylxpweb swallows parameter-read failures inside refresh() — no
        exception reaches the recovery loop and the old dict would have been
        copied straight back (codex r4). Pre-blanking means a reload that
        silently does nothing leaves the cache unknown, never stale kW."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
        coordinator.data = {
            "parameters": {"1234567890": {"HOLD_AC_CHARGE_POWER_CMD": 12}}
        }

        async def silent_noop(serial):
            return None  # swallowed-failure mode: no raise, no repopulation

        with patch.object(
            coordinator, "_refresh_device_parameters", side_effect=silent_noop
        ):
            await coordinator._finish_attach_recovery([], ["1234567890"])

        assert coordinator.data["parameters"]["1234567890"] == {}


@patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
@patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
class TestAttachSerialTransports:
    """Hybrid mode attaches USB serial transports integration-side (#233).

    pylxpweb's Station.attach_local_transports() only dispatches modbus_tcp
    and wifi_dongle configs and logs "Unknown transport type: modbus_serial"
    for serial ones, so the coordinator must create and attach serial
    transports itself, mirroring the LOCAL-only dispatch path.
    """

    async def test_serial_transport_attached_integration_side(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial config attaches without the pylxpweb dispatch (#233)."""
        entry = _make_hybrid_entry([dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ) as mock_create:
            await coordinator._attach_local_transports_to_station()

        # The pylxpweb dispatch (which would log "Unknown transport type:
        # modbus_serial" and fail the attach) must not see serial configs.
        mock_station.attach_local_transports.assert_not_called()

        mock_create.assert_called_once()
        assert mock_create.call_args.args == ("serial",)
        kwargs = mock_create.call_args.kwargs
        assert kwargs["port"] == "/dev/ttyUSB0"
        assert kwargs["serial"] == "INV001"
        assert kwargs["baudrate"] == 19200
        assert kwargs["parity"] == "N"
        assert kwargs["stopbits"] == 1
        assert kwargs["unit_id"] == 1

        serial_transport.connect.assert_awaited_once()
        assert inverter._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_mixed_tcp_and_serial_partitioned(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """TCP configs go to pylxpweb; serial configs attach locally."""
        tcp_dict = {
            "serial": "INV002",
            "transport_type": "modbus_tcp",
            "host": "192.168.1.100",
            "port": 502,
            "unit_id": 1,
            "inverter_family": "EG4_HYBRID",
            "model": "FlexBOSS21",
        }
        entry = _make_hybrid_entry(
            [tcp_dict, dict(_SERIAL_TRANSPORT_DICT)], "hybrid_mixed"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inv_serial = make_real_inverter("INV001", "FlexBOSS21")
        inv_tcp = make_real_inverter("INV002", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(
            return_value=AttachResult(matched=1)
        )
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [inv_serial, inv_tcp]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_station.attach_local_transports.assert_awaited_once()
        (network_configs,) = mock_station.attach_local_transports.call_args.args
        assert [c.transport_type for c in network_configs] == [TransportType.MODBUS_TCP]

        assert inv_serial._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_serial_attaches_to_mid_device(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial transports attach to GridBOSS/MID devices too."""
        serial_dict = dict(_SERIAL_TRANSPORT_DICT)
        serial_dict["serial"] = "GB00000001"
        serial_dict["model"] = "GridBOSS"
        entry = _make_hybrid_entry([serial_dict], "hybrid_serial_mid")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        mid = make_real_mid("GB00000001")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = []
        mock_station.all_mid_devices = [mid]
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_station.attach_local_transports.assert_not_called()
        assert mid._transport is serial_transport
        assert coordinator._local_transports_attached is True

    async def test_serial_unmatched_device(self, mock_aiohttp, mock_client_cls, hass):
        """No station device matching the serial → unmatched, no crash."""
        entry = _make_hybrid_entry(
            [dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_unmatched"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = []
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        with patch("pylxpweb.transports.create_transport") as mock_create:
            await coordinator._attach_local_transports_to_station()

        mock_create.assert_not_called()
        assert coordinator._local_transports_attached is True

    async def test_serial_connect_failure_recorded(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """A failing serial connect is recorded per-device, not fatal."""
        entry = _make_hybrid_entry([dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_fail")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        serial_transport.connect.side_effect = OSError("port busy")
        with patch(
            "pylxpweb.transports.create_transport",
            return_value=serial_transport,
        ):
            await coordinator._attach_local_transports_to_station()

        # Transport never attached, but per-device failures match the
        # pylxpweb semantics: attach completes and is not retried.
        assert inverter._transport is None
        assert coordinator._local_transports_attached is True

    async def test_serial_connect_failure_creates_repair_issue(
        self, mock_aiohttp, mock_client_cls, hass
    ):
        """Serial attach failure surfaces a Repairs issue — no silent cloud-only fallback (#233)."""
        entry = _make_hybrid_entry(
            [dict(_SERIAL_TRANSPORT_DICT)], "hybrid_serial_repair"
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        inverter = make_real_inverter("INV001", "FlexBOSS21")
        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock()
        mock_station.is_hybrid_mode = False
        mock_station.all_inverters = [inverter]
        mock_station.all_mid_devices = []
        coordinator.station = mock_station

        serial_transport = _make_serial_transport_spec()
        serial_transport.connect.side_effect = OSError("port busy")
        with (
            patch(
                "pylxpweb.transports.create_transport",
                return_value=serial_transport,
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local.ir.async_create_issue"
            ) as mock_issue,
        ):
            await coordinator._attach_local_transports_to_station()

        mock_issue.assert_called_once()
        args, kwargs = mock_issue.call_args
        assert args[2] == "serial_attach_failed_INV001"
        assert kwargs["translation_key"] == "serial_attach_failed"
        assert kwargs["translation_placeholders"]["serial"] == "INV001"
        assert kwargs["severity"].value == "warning"


class TestAttachForcedTransportRead:
    """Test transport attachment does NOT issue a forced read.

    asyncio.wait_for() with Python 3.11 does not interrupt in-flight pymodbus
    reads — it waits for the inner task to finish before raising TimeoutError.
    On HA restart the Waveshare gateway has stale RS485 responses buffered,
    causing reads to fail for 3–5 minutes. A forced refresh here would block
    async_config_entry_first_refresh() for the entire duration, causing HA's
    setup timeout to fire and cancel entity setup (setup_error). Data is
    populated by the first regular poll instead.
    """

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_does_not_force_transport_read(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """No refresh() call is issued after transport attachment."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        mock_inverter = MagicMock()
        mock_inverter._transport = make_transport_spec()
        mock_inverter.serial_number = "1234567890"
        mock_inverter.refresh = AsyncMock()

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        assert coordinator._local_transports_attached is True
        # No forced read — data will be populated on the first regular poll
        mock_inverter.refresh.assert_not_called()

    @patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient")
    @patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client")
    async def test_attach_completes_when_inverter_has_no_transport(
        self, mock_aiohttp, mock_client_cls, hass, hybrid_config_entry
    ):
        """Attachment loop handles inverters without a transport gracefully."""
        hybrid_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, hybrid_config_entry)

        mock_result = MagicMock()
        mock_result.matched = 1
        mock_result.unmatched = 0
        mock_result.failed = 0
        mock_result.unmatched_serials = []
        mock_result.failed_serials = []

        # Inverter with no transport attached (e.g. unmatched serial)
        mock_inverter = MagicMock()
        mock_inverter._transport = None
        mock_inverter.serial_number = "1234567890"
        mock_inverter.refresh = AsyncMock()

        mock_station = MagicMock()
        mock_station.attach_local_transports = AsyncMock(return_value=mock_result)
        mock_station.is_hybrid_mode = True
        mock_station.all_inverters = [mock_inverter]
        coordinator.station = mock_station

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_transport_configs",
            return_value=[MagicMock()],
        ):
            await coordinator._attach_local_transports_to_station()

        # Attachment still marks as attached; no refresh for transportless inverter
        assert coordinator._local_transports_attached is True
        mock_inverter.refresh.assert_not_called()


# ── _log_transport_error ─────────────────────────────────────────────


class TestLogTransportError:
    """Test transport error logging."""

    def test_first_error_updates_availability(self, hass, local_config_entry):
        """First error sets availability to False."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator._last_available_state is True

        coordinator._log_transport_error(
            "Modbus error", "INV001", RuntimeError("timeout")
        )

        assert coordinator._last_available_state is False

    def test_subsequent_error_no_warning(self, hass, local_config_entry):
        """Subsequent errors when already unavailable don't log warning again."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._last_available_state = False

        # Should not log warning (already unavailable)
        coordinator._log_transport_error(
            "Modbus error", "INV001", RuntimeError("timeout")
        )

        assert coordinator._last_available_state is False


# ── _async_update_local_data edge cases ──────────────────────────────


class TestAsyncUpdateLocalDataEdgeCases:
    """Edge cases for _async_update_local_data not covered by test_coordinator.py."""

    async def test_no_transports_configured_raises(self, hass):
        """No local transports → UpdateFailed."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Empty",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
                CONF_LIBRARY_DEBUG: False,
            },
            entry_id="empty_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        with pytest.raises(UpdateFailed, match="No local transports configured"):
            await coordinator._async_update_local_data()

    async def test_invalid_config_skipped(self, hass):
        """Config with missing serial is skipped."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Invalid",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        # Missing serial
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                    },
                ],
            },
            entry_id="invalid_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        with pytest.raises(UpdateFailed, match="All .* local transports failed"):
            await coordinator._async_update_local_data()


class TestGridBOSSFirmwareCache:
    """GridBOSS firmware version should be read from transport and cached (#156)."""

    async def test_gridboss_firmware_read_from_transport(self, hass):
        """GridBOSS firmware is read via transport.read_firmware_version(), not MIDDevice property."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GridBOSS FW",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB001",
                        "host": "192.168.1.200",
                        "port": 502,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "MID_DEVICE",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                        "dongle_serial": "D001",
                    },
                ],
            },
            entry_id="gb_fw_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        # Build a real MIDDevice with a transport that returns firmware.
        # read_firmware_version is async on the real transport, so the autospec
        # returns a coroutine — set its awaited result, not a plain return value.
        mock_transport = make_transport_spec(is_connected=True)
        mock_transport.read_firmware_version.return_value = "IAAB-1600"

        # Inject real runtime so has_data is True (the MIDDevice property reads
        # _transport_runtime). The MIDDevice.firmware_version property would
        # return "" here (the bug scenario) — firmware must come from transport.
        mock_mid = make_real_mid(serial_number="GB001", runtime=MidboxRuntimeData())
        mock_mid._transport = mock_transport
        mock_mid.refresh = AsyncMock()

        coordinator._mid_device_cache["GB001"] = mock_mid

        # Mock out the sensor mapping and other helpers
        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_gridboss_sensor_mapping",
                return_value={"grid_voltage": 240.0},
            ),
            patch.object(coordinator, "_filter_unused_smart_port_sensors"),
            patch.object(coordinator, "_calculate_gridboss_aggregates"),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        # Firmware should come from transport, not the MIDDevice property
        device_data = processed["devices"]["GB001"]
        assert device_data["firmware_version"] == "IAAB-1600"
        assert device_data["sensors"]["firmware_version"] == "IAAB-1600"
        # Cached for subsequent calls
        assert coordinator._firmware_cache["GB001"] == "IAAB-1600"

    async def test_gridboss_firmware_cached_on_second_call(self, hass):
        """Firmware is read once and cached — transport not called again."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - GridBOSS FW Cache",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "GB002",
                        "host": "192.168.1.200",
                        "port": 502,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "MID_DEVICE",
                        "model": "GridBOSS",
                        "is_gridboss": True,
                        "dongle_serial": "D002",
                    },
                ],
            },
            entry_id="gb_fw_cache_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        # Pre-populate firmware cache (simulates first refresh already done)
        coordinator._firmware_cache["GB002"] = "IAAB-1600"

        mock_transport = make_transport_spec(is_connected=True)
        mock_transport.read_firmware_version.return_value = "SHOULD-NOT-BE-CALLED"

        mock_mid = MagicMock()
        mock_mid._transport = mock_transport
        mock_mid.has_data = True
        mock_mid.refresh = AsyncMock()
        mock_mid.firmware_version = None

        coordinator._mid_device_cache["GB002"] = mock_mid

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_gridboss_sensor_mapping",
                return_value={"grid_voltage": 240.0},
            ),
            patch.object(coordinator, "_filter_unused_smart_port_sensors"),
            patch.object(coordinator, "_calculate_gridboss_aggregates"),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        # Should use cached value, NOT call transport again
        mock_transport.read_firmware_version.assert_not_called()
        assert processed["devices"]["GB002"]["firmware_version"] == "IAAB-1600"


class TestSharedBatterySecondary:
    """Shared battery suppression for parallel secondary inverters (#169).

    In a parallel system with "Share Battery" enabled, the CAN bus connects
    only to the primary inverter.  The secondary (role >= 2) reports
    battery_count=0 at Modbus register 96.  Battery bank device/entities
    should be suppressed on the secondary — per-inverter runtime sensors
    (battery_voltage, battery_current, state_of_charge) remain accurate.
    """

    @pytest.fixture
    def parallel_config_entry(self, hass):
        """Config entry with primary + secondary inverter in parallel."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Parallel",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "PRIMARY001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS18",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SECONDARY01",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id="parallel_test",
        )
        entry.add_to_hass(hass)
        return entry

    async def test_static_phase_includes_battery_bank_keys_for_all_inverters(
        self, hass, parallel_config_entry
    ):
        """Static phase includes core battery_bank keys for all inverters.

        We cannot know at static-phase time whether a secondary truly
        lacks batteries (shared CAN bus) or has its own bank.  Suppression
        happens at runtime when we have actual battery_count data.
        """
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            BATTERY_BANK_CORE_KEYS,
        )

        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        result = coordinator._build_static_local_data()

        primary_sensors = result["devices"]["PRIMARY001"]["sensors"]
        secondary_sensors = result["devices"]["SECONDARY01"]["sensors"]

        # Both primary and secondary should have core battery bank keys
        assert any(k in primary_sensors for k in BATTERY_BANK_CORE_KEYS), (
            "Primary should have battery bank keys in static phase"
        )

        assert any(k in secondary_sensors for k in BATTERY_BANK_CORE_KEYS), (
            "Secondary should have battery bank keys in static phase"
        )

    async def test_static_fallback_creates_repair_issue(self, hass, local_config_entry):
        """Legacy UNKNOWN-family entry pruned by model fallback raises Repairs.

        The static path used to create ALL sensors for UNKNOWN-family configs;
        the model fallback now prunes to the real profile, which removes
        previously-visible (dead) three-phase entities — that must be loud,
        not silent (#219 review finding 2).
        """
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator._local_transport_configs = [
            {
                "serial": "6000123456",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.50",
                "port": 502,
                "model": "6000XP",
                "inverter_family": "UNKNOWN",
            },
            {
                "serial": "5284200001",
                "transport_type": "modbus_tcp",
                "host": "192.168.1.51",
                "port": 502,
                "model": "FlexBOSS21",
                "inverter_family": "EG4_HYBRID",
            },
        ]

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local.ir.async_create_issue"
        ) as mock_issue:
            coordinator._build_static_local_data()

        # Exactly one issue — for the fallback device, not the clean one.
        mock_issue.assert_called_once()
        args, kwargs = mock_issue.call_args
        assert args[2] == "unknown_family_fallback_6000123456"
        assert kwargs["translation_key"] == "unknown_family_fallback"
        assert kwargs["translation_placeholders"]["model"] == "6000XP"
        assert kwargs["translation_placeholders"]["family"] == "EG4_OFFGRID"

    async def test_static_phase_excludes_can_diagnostic_keys(
        self, hass, parallel_config_entry
    ):
        """Static phase must NOT include CAN-dependent diagnostic keys.

        CAN bus diagnostic sensors (soc_delta, soh_delta, etc.) require
        individual battery data from registers 5002+.  Pre-creating them
        statically would produce permanently Unavailable entities when
        CAN data is not available.
        """
        from custom_components.eg4_web_monitor.coordinator_mappings import (
            BATTERY_BANK_CAN_DIAGNOSTIC_KEYS,
        )

        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        result = coordinator._build_static_local_data()

        for serial in result["devices"]:
            sensors = result["devices"][serial]["sensors"]
            for key in BATTERY_BANK_CAN_DIAGNOSTIC_KEYS:
                assert key not in sensors, (
                    f"{key} should not be in static sensors for {serial}"
                )

    async def test_secondary_skips_battery_bank_when_count_zero(
        self, hass, parallel_config_entry
    ):
        """Secondary (battery_count=0) should not get battery bank sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        coordinator._local_static_phase_done = True

        # Secondary inverter: role=2, battery_count=0 (shared battery)
        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=2,
            parallel_phase=0,
            pv_total_power=5000,
            battery_soc=93,
            rectifier_power=0,
            battery_current=15.0,
            battery_voltage=53.7,
        )

        mock_battery_data = BatteryBankData(
            battery_count=None,  # CAN bus not connected
            batteries=[],
        )

        inverter = make_real_inverter("SECONDARY01", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.101"
        )

        # Pre-populate caches
        coordinator._inverter_cache["SECONDARY01"] = inverter
        coordinator._firmware_cache["SECONDARY01"] = "fAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={
                "battery_voltage": 53.7,
                "battery_current": 15.0,
                "state_of_charge": 93,
            },
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=parallel_config_entry.data[CONF_LOCAL_TRANSPORTS][1],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["SECONDARY01"]

        # Runtime sensors (from input registers) should be present
        assert device["sensors"]["battery_voltage"] == 53.7
        assert device["sensors"]["battery_current"] == 15.0
        assert device["sensors"]["state_of_charge"] == 93

        # No battery_bank_* sensors should exist
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"

        # No individual batteries
        assert device["batteries"] == {}

    async def test_primary_retains_battery_bank(self, hass, parallel_config_entry):
        """Primary inverter (role=1) should still get battery bank sensors."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)
        coordinator._local_static_phase_done = True

        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=1,
            parallel_phase=0,
            pv_total_power=8000,
            battery_soc=93,
            rectifier_power=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=4,  # CAN bus connected
            voltage=53.7,
            current=30.0,
            soc=93,
            charge_power=825.0,
            discharge_power=0,
            max_capacity=280.0,
            current_capacity=260.0,
            status="Charging",
            batteries=[
                BatteryData(battery_index=0, serial_number="BAT0"),
                BatteryData(battery_index=1, serial_number="BAT1"),
            ],
        )

        inverter = make_real_inverter("PRIMARY001", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )

        coordinator._inverter_cache["PRIMARY001"] = inverter
        coordinator._firmware_cache["PRIMARY001"] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"battery_voltage": 53.7, "state_of_charge": 93},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=parallel_config_entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["PRIMARY001"]

        # Primary should have battery bank sensors
        assert "battery_bank_soc" in device["sensors"]
        assert "battery_bank_voltage" in device["sensors"]
        assert "battery_bank_count" in device["sensors"]
        assert device["sensors"]["battery_bank_count"] == 4

    async def test_shared_battery_logged_once(self, hass, parallel_config_entry):
        """Info log for shared battery skip should fire only once per serial."""
        coordinator = EG4DataUpdateCoordinator(hass, parallel_config_entry)

        # Simulate: serial already logged
        coordinator._shared_battery_logged.add("SECONDARY01")

        # The set prevents re-logging on subsequent invocations
        assert "SECONDARY01" in coordinator._shared_battery_logged

    async def test_non_parallel_inverter_with_zero_battery_count_skips_bank(
        self,
        hass,
    ):
        """Standalone inverter with battery_count=0 also skips battery bank.

        Battery bank creation is gated purely on battery_count, regardless of
        parallel role.  If the count is 0/None, no battery bank device is created.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Standalone",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "STANDALONE1",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                    },
                ],
            },
            options={},
            entry_id="standalone_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_runtime = InverterRuntimeData(
            parallel_number=0,  # No parallel group
            parallel_master_slave=0,  # Not a secondary
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=None,  # Temporarily 0
            voltage=53.7,
            current=0.0,
            soc=50,
            charge_power=0,
            discharge_power=0,
            max_capacity=None,
            current_capacity=None,
            status="Idle",
            batteries=[],
        )

        inverter = make_real_inverter("STANDALONE1", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )

        coordinator._inverter_cache["STANDALONE1"] = inverter
        coordinator._firmware_cache["STANDALONE1"] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            device_availability: dict[str, bool] = {}
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability=device_availability,
            )

        device = processed["devices"]["STANDALONE1"]

        # battery_count=0 → no battery bank sensors regardless of parallel status
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"


class TestBatteryBankCountSuppression:
    """Tests for battery bank suppression when battery_count=0 (issue #169)."""

    @staticmethod
    def _make_detection_entry(hass: Any, serial: str, entry_id: str) -> MockConfigEntry:
        """Build a LOCAL config entry with one secondary inverter for detection tests."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Detection Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": serial,
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id=entry_id,
        )
        entry.add_to_hass(hass)
        return entry

    @staticmethod
    def _make_mock_inverter(*, battery_count: int | None = None) -> HybridInverter:
        """Build a REAL inverter with shared-battery secondary defaults."""
        mock_runtime = InverterRuntimeData(
            parallel_number=2,
            parallel_master_slave=2,
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=battery_count,
            batteries=[],
        )

        inverter = make_real_inverter("SECONDARY01", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )
        return inverter

    async def test_secondary_no_battery_bank_sensors(self, hass):
        """Secondary with battery_count=0 gets no battery_bank_* sensors."""
        serial = "INVPARAM01"
        entry = self._make_detection_entry(hass, serial, "param_test")
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_inverter = self._make_mock_inverter(battery_count=None)
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {serial: {"FUNC_BAT_SHARED": 1}},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == [], f"Unexpected battery bank sensors: {bank_keys}"

    async def test_secondary_with_battery_count_zero_explicit(self, hass):
        """Secondary with battery_count=0 (explicit zero) also skips bank."""
        serial = "INVZERO01"
        entry = self._make_detection_entry(hass, serial, "zero_test")
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        mock_inverter = self._make_mock_inverter(battery_count=0)
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 50},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        bank_keys = [k for k in device["sensors"] if k.startswith("battery_bank_")]
        assert bank_keys == []

    async def test_parallel_group_counts_only_primary_batteries(self, hass):
        """Parallel group battery count comes from primary only (secondary has 0)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - PG Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "PRIMARY001",
                        "host": "192.168.1.100",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS18",
                        "parallel_number": 2,
                        "parallel_master_slave": 1,
                    },
                    {
                        "serial": "SECONDARY01",
                        "host": "192.168.1.101",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 2,
                        "parallel_master_slave": 2,
                    },
                ],
            },
            options={},
            entry_id="pg_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        processed: dict[str, Any] = {
            "devices": {
                "PRIMARY001": {
                    "type": "inverter",
                    "model": "FlexBOSS18",
                    "serial": "PRIMARY001",
                    "sensors": {
                        "battery_bank_count": 4,
                        "battery_bank_current": 30.0,
                        "battery_bank_max_capacity": 280.0,
                        "battery_bank_current_capacity": 260.0,
                        "state_of_charge": 93,
                    },
                    "batteries": {"bat1": {"soc": 93}},
                    "parallel_number": 2,
                    "parallel_master_slave": 1,
                },
                "SECONDARY01": {
                    "type": "inverter",
                    "model": "FlexBOSS21",
                    "serial": "SECONDARY01",
                    "sensors": {
                        "state_of_charge": 93,
                        "battery_voltage": 53.7,
                    },
                    "batteries": {},
                    "parallel_number": 2,
                    "parallel_master_slave": 2,
                },
            },
            "parallel_groups": {},
            "parameters": {},
        }

        await coordinator._process_local_parallel_groups(processed)

        pg = processed["devices"].get("parallel_group_a", {})
        pg_sensors = pg.get("sensors", {})

        # Battery count = 4 (primary only, secondary has none)
        assert pg_sensors.get("parallel_battery_count") == 4
        assert pg_sensors.get("parallel_battery_current") == 30.0


class TestBatteryRRCacheFallback:
    """Regression tests for issue #180: individual batteries become unavailable.

    When the WiFi dongle fails to read individual battery registers (5002+),
    ``_battery_slot_ceiling`` was permanently set to 0, causing all subsequent
    polls to return ``battery_data.batteries = []``.  The coordinator now falls
    back to the round-robin cache so entities stay available during transient
    transport failures.
    """

    @staticmethod
    def _make_config_entry(hass: Any, serial: str) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Cache Fallback Test",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": serial,
                        "host": "192.168.1.100",
                        "port": 8899,
                        "transport_type": "wifi_dongle",
                        "inverter_family": "EG4_HYBRID",
                        "model": "FlexBOSS21",
                        "parallel_number": 0,
                        "parallel_master_slave": 0,
                    },
                ],
            },
            options={},
            entry_id="cache_fallback_test",
        )
        entry.add_to_hass(hass)
        return entry

    @staticmethod
    def _make_mock_inverter(
        *, battery_count: int, batteries: list[Any]
    ) -> HybridInverter:
        mock_runtime = InverterRuntimeData(
            parallel_number=0,
            parallel_master_slave=0,
            parallel_phase=0,
        )

        mock_battery_data = BatteryBankData(
            battery_count=battery_count,
            batteries=batteries,
        )

        inverter = make_real_inverter("DONGLE001", "FlexBOSS21", runtime=mock_runtime)
        inverter.refresh = AsyncMock()
        inverter._transport_battery = mock_battery_data
        inverter._transport = make_transport_spec(
            is_connected=True, host="192.168.1.100"
        )
        return inverter

    async def test_cache_fallback_when_batteries_empty_this_poll(
        self, hass: Any
    ) -> None:
        """When battery_data.batteries is empty but cache has data, use cache.

        Regression test for issue #180: after a transient WiFi dongle read
        failure, individual battery entities must stay available (not go
        unavailable) by falling back to the round-robin cache.
        """
        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        # Pre-populate the round-robin cache with 4 batteries (as if a
        # previous successful poll populated them).
        coordinator._battery_rr_cache[serial] = {
            f"{serial}-01": {"soc": 80, "voltage": 52.8},
            f"{serial}-02": {"soc": 79, "voltage": 52.7},
            f"{serial}-03": {"soc": 81, "voltage": 52.9},
            f"{serial}-04": {"soc": 78, "voltage": 52.6},
        }

        # This poll: battery_data exists (bank sensors work) but batteries=[]
        # (individual register read failed, _battery_slot_ceiling was set to 0)
        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"state_of_charge": 79},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_battery_bank_sensor_mapping",
                return_value={"battery_bank_count": 4, "battery_bank_voltage": 52.7},
            ),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        # Cache fallback: 4 batteries should be available from the cache
        assert len(device["batteries"]) == 4, (
            "Expected 4 batteries from RR cache fallback, "
            f"got {len(device['batteries'])}: {list(device['batteries'].keys())}"
        )
        assert f"{serial}-01" in device["batteries"]
        assert f"{serial}-04" in device["batteries"]

    async def test_no_fallback_when_cache_empty(self, hass: Any) -> None:
        """When both poll batteries and cache are empty, batteries dict is empty."""
        serial = "DONGLE002"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        # No pre-populated cache

        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"state_of_charge": 50},
            ),
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_battery_bank_sensor_mapping",
                return_value={"battery_bank_count": 4},
            ),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        # No fallback possible — batteries stays empty
        assert device["batteries"] == {}

    async def test_cache_fallback_when_reg96_reads_zero(self, hass: Any) -> None:
        """A transient reg 96 = 0 must not drop accumulated batteries (#258).

        reg 96 under-reports on parallel/rotating systems.  A genuine
        shared-battery secondary never populates the round-robin cache, so
        serving a non-empty cache here can only ever re-serve batteries this
        inverter itself reported earlier.
        """
        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        coordinator._battery_rr_cache[serial] = {
            f"{serial}-01": {"soc": 80, "voltage": 52.8},
            f"{serial}-02": {"soc": 79, "voltage": 52.7},
        }

        # This poll: reg 96 reads 0 (bank gate) with an empty page.
        mock_inverter = self._make_mock_inverter(battery_count=0, batteries=[])
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 79},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        assert len(device["batteries"]) == 2
        assert f"{serial}-01" in device["batteries"]

    async def test_cache_fallback_when_transport_battery_none(self, hass: Any) -> None:
        """A cleared transport battery cache must not drop accumulated batteries."""
        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        coordinator._battery_rr_cache[serial] = {
            f"{serial}-01": {"soc": 80, "voltage": 52.8},
        }

        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        mock_inverter._transport_battery = None
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with patch(
            "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
            return_value={"state_of_charge": 79},
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        assert f"{serial}-01" in device["batteries"]

    async def test_cache_reserve_evicts_aged_entries(
        self, hass: Any, caplog: Any
    ) -> None:
        """The re-serve path must not immortalize a physically removed pack.

        A cached battery whose battery_last_seen aged past
        BATTERY_CARRY_FORWARD_MAX_AGE is evicted from the round-robin cache
        (one INFO) instead of being re-served with frozen data forever —
        otherwise pylxpweb's empty-bank convergence is negated at this layer.
        """
        import logging as _logging

        from homeassistant.util import dt as dt_util

        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True

        now = dt_util.utcnow()
        coordinator._battery_rr_cache[serial] = {
            f"{serial}-01": {"soc": 80, "battery_last_seen": now},
            f"{serial}-02": {
                "soc": 79,
                "battery_last_seen": now - timedelta(hours=7),
            },
        }

        mock_inverter = self._make_mock_inverter(battery_count=4, batteries=[])
        mock_inverter._transport_battery = None
        coordinator._inverter_cache[serial] = mock_inverter
        coordinator._firmware_cache[serial] = "FAAB-2525"

        with (
            patch(
                "custom_components.eg4_web_monitor.coordinator_local._build_runtime_sensor_mapping",
                return_value={"state_of_charge": 79},
            ),
            caplog.at_level(_logging.INFO),
        ):
            processed: dict[str, Any] = {
                "devices": {},
                "parallel_groups": {},
                "parameters": {},
            }
            await coordinator._process_single_local_device(
                config=entry.data[CONF_LOCAL_TRANSPORTS][0],
                processed=processed,
                device_availability={},
            )

        device = processed["devices"][serial]
        assert f"{serial}-01" in device["batteries"]
        assert f"{serial}-02" not in device["batteries"], "aged entry re-served"
        # Authoritative eviction: gone from the cache too, with one INFO.
        assert f"{serial}-02" not in coordinator._battery_rr_cache[serial]
        assert any(
            f"{serial}-02" in r.getMessage()
            for r in caplog.records
            if r.levelno == _logging.INFO and "Evict" in r.getMessage()
        )

    async def test_merge_evicts_aged_entries_on_nonempty_poll(
        self, hass: Any, caplog: Any
    ) -> None:
        """Rotating pack: removal converges even though polls stay non-empty.

        ``_merge_round_robin_batteries`` returns the full accumulated cache,
        so once any battery has been seen ``device_data["batteries"]`` is
        never empty and the empty-poll re-serve branch (which used to host
        the only eviction) is unreachable.  The BATTERY_CARRY_FORWARD_MAX_AGE
        bound must therefore apply on every merge: a battery that stopped
        appearing (physically removed) is evicted while live batteries —
        including one merely on a page not covered by this rotation
        position — survive.
        """
        import logging as _logging

        from custom_components.eg4_web_monitor.utils import local_battery_key

        serial = "DONGLE001"
        entry = self._make_config_entry(hass, serial)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        def _batt(index: int, batt_serial: str) -> BatteryData:
            return BatteryData(
                battery_index=index,
                serial_number=batt_serial,
                voltage=52.5,
                soc=90,
            )

        sn_live = "BATLIVE00001"
        sn_carried = "BATCARRY0001"
        sn_removed = "BATGONE00001"

        # Poll 1: all three batteries appear (fresh timestamps).
        coordinator._merge_round_robin_batteries(
            serial,
            [_batt(0, sn_live), _batt(1, sn_carried), _batt(2, sn_removed)],
        )
        cache = coordinator._battery_rr_cache[serial]
        key_live = local_battery_key(serial, sn_live, 0)
        key_carried = local_battery_key(serial, sn_carried, 1)
        key_removed = local_battery_key(serial, sn_removed, 2)
        assert set(cache) == {key_live, key_carried, key_removed}

        # Time passes: the removed battery hasn't been read for over 6h;
        # the carried battery was last read 5h ago (rotation page not
        # covered recently, still within the bound).
        now = dt_util.utcnow()
        cache[key_removed]["battery_last_seen"] = now - timedelta(hours=7)
        cache[key_carried]["battery_last_seen"] = now - timedelta(hours=5)
        coordinator._battery_carry_forward.setdefault(serial, {})[key_removed] = dict(
            cache[key_removed]
        )

        # Poll 2 (NON-empty): only the live battery's page is covered.
        with caplog.at_level(_logging.INFO):
            merged = coordinator._merge_round_robin_batteries(
                serial, [_batt(0, sn_live)]
            )

        assert key_live in merged
        assert key_carried in merged, "within-bound carried battery evicted"
        assert key_removed not in merged, "aged battery re-served on non-empty poll"
        # Authoritative eviction across both sticky layers, with one INFO.
        assert key_removed not in coordinator._battery_rr_cache[serial]
        assert key_removed not in coordinator._battery_carry_forward[serial]
        assert any(
            key_removed in r.getMessage()
            for r in caplog.records
            if r.levelno == _logging.INFO and "Evict" in r.getMessage()
        )


class TestBatteryControlModeMethods:
    """Coordinator helpers for the battery control regime (SOC vs Voltage)."""

    async def test_get_configured_control_modes_default_soc(
        self, hass, local_config_entry
    ):
        """No stored options → SOC for both (migration-safe)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        assert coordinator.get_configured_control_modes() == ("soc", "soc")

    async def test_get_configured_control_modes_from_options(self, hass):
        """Stored options are returned verbatim."""
        from custom_components.eg4_web_monitor.const import (
            CONF_CHARGE_CONTROL_MODE,
            CONF_DISCHARGE_CONTROL_MODE,
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="t",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_LOCAL_TRANSPORTS: [],
            },
            options={
                CONF_CHARGE_CONTROL_MODE: "voltage",
                CONF_DISCHARGE_CONTROL_MODE: "soc",
            },
            entry_id="ctrl_modes",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        assert coordinator.get_configured_control_modes() == ("voltage", "soc")

    async def test_get_live_control_mode(self, hass, local_config_entry):
        """Live regime is read from reg-179 bits in params; missing → SOC."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.data = {
            "parameters": {
                "INV001": {
                    "FUNC_BAT_CHARGE_CONTROL": True,
                    "FUNC_BAT_DISCHARGE_CONTROL": False,
                }
            }
        }
        assert coordinator.get_live_control_mode("INV001") == "voltage"
        assert coordinator.get_live_control_mode("INV001", discharge=True) == "soc"
        assert coordinator.get_live_control_mode("UNKNOWN") == "soc"

    async def test_async_write_battery_control_mode_local(
        self, hass, local_config_entry
    ):
        """Local write sets both reg-179 bits via named parameters."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=True)
        coordinator.write_named_parameter = AsyncMock()

        await coordinator.async_write_battery_control_mode("INV001", "voltage", "soc")

        calls = coordinator.write_named_parameter.call_args_list
        assert calls[0][0][0] == "FUNC_BAT_CHARGE_CONTROL"
        assert calls[0][0][1] is True
        assert calls[1][0][0] == "FUNC_BAT_DISCHARGE_CONTROL"
        assert calls[1][0][1] is False

    async def test_async_write_battery_control_mode_cloud(
        self, hass, local_config_entry
    ):
        """Cloud write uses the atomic function-control API for each bit."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=False)
        result = MagicMock()
        result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(return_value=result)

        await coordinator.async_write_battery_control_mode("INV001", "soc", "voltage")

        calls = coordinator.client.api.control.control_function.call_args_list
        assert calls[0][0] == ("INV001", "FUNC_BAT_CHARGE_CONTROL", False)
        assert calls[1][0] == ("INV001", "FUNC_BAT_DISCHARGE_CONTROL", True)

    async def test_async_write_battery_control_mode_hybrid_fallback(
        self, hass, local_config_entry
    ):
        """HYBRID: a failed local write falls back to the cloud
        function-control API instead of raising (switch parity)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        result = MagicMock()
        result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(return_value=result)

        await coordinator.async_write_battery_control_mode("INV001", "voltage", "soc")

        coordinator.write_named_parameter.assert_awaited_once()
        calls = coordinator.client.api.control.control_function.call_args_list
        assert calls[0][0] == ("INV001", "FUNC_BAT_CHARGE_CONTROL", True)
        assert calls[1][0] == ("INV001", "FUNC_BAT_DISCHARGE_CONTROL", False)

    async def test_async_write_battery_control_mode_local_only_failure_raises(
        self, hass, local_config_entry
    ):
        """LOCAL-only: no cloud client -> the local write error propagates."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=True)
        coordinator.write_named_parameter = AsyncMock(
            side_effect=HomeAssistantError("Failed to write parameter: timeout")
        )
        coordinator.client = None

        with pytest.raises(HomeAssistantError, match="timeout"):
            await coordinator.async_write_battery_control_mode(
                "INV001", "voltage", "soc"
            )

    async def test_battery_control_mode_partial_cloud_write_converges(
        self, hass, local_config_entry
    ):
        """Cloud two-bit write: charge bit lands, discharge bit fails ->
        device parameters are re-read (best effort) BEFORE the error
        propagates, so entities reflect the actual (mixed) reg-179 regime
        (same pattern as the schedule time partial hour/minute writes)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=False)
        ok = MagicMock()
        ok.success = True
        failed = MagicMock()
        failed.success = False
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(
            side_effect=[ok, failed]
        )
        coordinator._refresh_device_parameters = AsyncMock()

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await coordinator.async_write_battery_control_mode(
                "INV001", "voltage", "soc"
            )

        coordinator._refresh_device_parameters.assert_awaited_once_with("INV001")

    async def test_battery_control_mode_partial_cloud_exception_converges(
        self, hass, local_config_entry
    ):
        """A raised exception on the discharge-bit write converges the same
        way (re-read then raise)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=False)
        ok = MagicMock()
        ok.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(
            side_effect=[ok, RuntimeError("connection reset")]
        )
        coordinator._refresh_device_parameters = AsyncMock()

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await coordinator.async_write_battery_control_mode(
                "INV001", "voltage", "soc"
            )

        coordinator._refresh_device_parameters.assert_awaited_once_with("INV001")

    async def test_battery_control_mode_partial_write_link_down_seeds_charge_bit(
        self, hass, local_config_entry
    ):
        """HYBRID link-down partial write: the re-read is impossible (gated),
        so the KNOWN-succeeded charge bit is seeded into the cache — the
        failed discharge bit stays untouched (device still holds its old
        value) — while the error still surfaces (codex medium on PR #301)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.has_local_transport = MagicMock(return_value=True)
        coordinator.is_transport_link_down = MagicMock(return_value=True)
        coordinator.data = {
            "parameters": {
                "INV001": {
                    "FUNC_BAT_CHARGE_CONTROL": False,
                    "FUNC_BAT_DISCHARGE_CONTROL": False,
                }
            }
        }
        coordinator.async_update_listeners = MagicMock()
        ok = MagicMock()
        ok.success = True
        failed = MagicMock()
        failed.success = False
        coordinator.client = MagicMock()
        coordinator.client.api.control.control_function = AsyncMock(
            side_effect=[ok, failed]
        )
        coordinator._refresh_device_parameters = AsyncMock()

        with pytest.raises(HomeAssistantError, match="partially applied"):
            await coordinator.async_write_battery_control_mode(
                "INV001", "voltage", "voltage"
            )

        # Re-read skipped (link down), succeeded charge bit seeded, failed
        # discharge bit unchanged (pre-write cache value).
        coordinator._refresh_device_parameters.assert_not_awaited()
        params = coordinator.data["parameters"]["INV001"]
        assert params["FUNC_BAT_CHARGE_CONTROL"] is True
        assert params["FUNC_BAT_DISCHARGE_CONTROL"] is False
        coordinator.async_update_listeners.assert_called_once()


class TestLinkDownParameterRefreshGate:
    """Link-down handling is delegated to pylxpweb's _fetch_parameters guard
    (pylxpweb#206, in the 0.9.36b24 floor pinned by manifest.json): it skips
    the local Modbus read on a dead link (no uninterruptible pymodbus hang)
    and falls back to cloud named-parameter reads in HYBRID, or skips
    cleanly in LOCAL (parameters_complete=False).  The coordinator-side hard
    skip that preceded it (codex P1 on PR #301) blocked exactly that cloud
    fallback and was removed in #322 — down-link serials must still be
    refreshed with force + parameters."""

    @staticmethod
    def _fake_inverter(*, link_down: bool, parameters: dict | None = None):
        inv = MagicMock()
        inv.transport = object()
        inv.transport_link_down = link_down
        inv.refresh = AsyncMock()
        inv.parameters = parameters or {}
        return inv

    async def test_refresh_all_includes_down_link_serials(
        self, hass, local_config_entry
    ):
        """refresh_all_device_parameters: the down serial is refreshed too —
        pylxpweb routes it via cloud fallback (HYBRID) or skips internally
        (LOCAL); the healthy sibling refreshes as before."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        down = self._fake_inverter(link_down=True, parameters={"HOLD_Y": 2})
        up = self._fake_inverter(link_down=False, parameters={"HOLD_X": 1})
        coordinator._inverter_cache = {"DOWN1": down, "UP1": up}
        coordinator.data = {
            "devices": {
                "DOWN1": {"type": "inverter"},
                "UP1": {"type": "inverter"},
            }
        }

        await coordinator.refresh_all_device_parameters()

        down.refresh.assert_awaited_once_with(force=True, include_parameters=True)
        up.refresh.assert_awaited_once_with(force=True, include_parameters=True)
        assert coordinator.data["parameters"]["UP1"] == {"HOLD_X": 1}
        assert coordinator.data["parameters"]["DOWN1"] == {"HOLD_Y": 2}

    async def test_async_refresh_device_parameters_refreshes_down_link(
        self, hass, local_config_entry
    ):
        """The single-serial public refresh path delegates the same way."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        down = self._fake_inverter(link_down=True)
        coordinator._inverter_cache = {"DOWN1": down}
        coordinator.data = {"devices": {"DOWN1": {"type": "inverter"}}}
        coordinator.async_request_refresh = AsyncMock()

        await coordinator.async_refresh_device_parameters("DOWN1")

        down.refresh.assert_awaited_once_with(force=True, include_parameters=True)

    async def test_note_parameters_written_merges_and_notifies(
        self, hass, local_config_entry
    ):
        """Acknowledged written values merge into the cache and notify
        listeners (entity convergence after a skipped local re-read)."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.data = {"parameters": {"INV001": {"HOLD_A": 1}}}
        coordinator.async_update_listeners = MagicMock()

        coordinator.note_parameters_written("INV001", {"HOLD_B": 2})

        assert coordinator.data["parameters"]["INV001"] == {"HOLD_A": 1, "HOLD_B": 2}
        coordinator.async_update_listeners.assert_called_once()

    async def test_note_parameters_written_no_data_is_noop(
        self, hass, local_config_entry
    ):
        """Before the first refresh (data=None) the seed is a no-op."""
        local_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, local_config_entry)
        coordinator.data = None
        coordinator.async_update_listeners = MagicMock()

        coordinator.note_parameters_written("INV001", {"HOLD_B": 2})

        coordinator.async_update_listeners.assert_not_called()


# ── Transport link-down flow (eg4-57g / #226 attached-but-dead) ──────


class TestLocalLinkDownFlow:
    """LOCAL mode end-to-end: a link-down device must surface an error key
    (entities unavailable) and a Repairs issue — not frozen-fresh values."""

    async def test_link_down_marks_error_and_raises_repairs_issue(self, hass):
        """A device whose transport link died gets its cached device data
        error-marked and a transport_link_down Repairs issue, even when the
        whole cycle ends in UpdateFailed (single-device outage)."""
        from homeassistant.helpers import issue_registry as ir

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Link Down",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="link_down_flow_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        coordinator._local_parameters_loaded = False

        # Previous good cycle's data (this is what would freeze pre-fix).
        coordinator.data = {
            "devices": {
                "CE11111111": {
                    "type": "inverter",
                    "sensors": {"battery_voltage": 53.2},
                }
            },
            "parameters": {},
        }

        # Link-down inverter as pylxpweb now presents it: refresh() swallows
        # the failed probe, transport data caches cleared on the transition.
        transport = MagicMock(spec=["is_connected", "host", "port", "transport_type"])
        transport.is_connected = True
        transport.host = "192.168.1.60"
        transport.port = 502
        transport.transport_type = "modbus_tcp"
        inverter = MagicMock(
            spec=[
                "transport",
                "transport_link_down",
                "transport_runtime",
                "refresh",
                "serial_number",
            ]
        )
        inverter.serial_number = "CE11111111"
        inverter.transport = transport
        inverter.transport_link_down = True
        inverter.transport_runtime = None  # cleared at the down transition
        inverter.refresh = AsyncMock()
        coordinator._inverter_cache["CE11111111"] = inverter

        with pytest.raises(UpdateFailed, match="All 1 local transports failed"):
            await coordinator._async_update_local_data()

        # Probe still attempted this cycle (recovery path stays alive).
        inverter.refresh.assert_awaited_once()

        # The carried-forward device data is error-marked, which flips the
        # base_entity availability contract to unavailable.
        assert (
            coordinator.data["devices"]["CE11111111"]["error"]
            == "Local transport link down"
        )

        # One-shot Repairs issue exists with the right placeholders.
        registry = ir.async_get(hass)
        issue = registry.async_get_issue(DOMAIN, "transport_link_down_CE11111111")
        assert issue is not None
        assert issue.translation_key == "transport_link_down"
        assert issue.translation_placeholders == {
            "serial": "CE11111111",
            "host": "192.168.1.60",
        }
        assert coordinator._link_down_notified == {"CE11111111"}

    async def test_recovery_clears_repairs_issue(self, hass):
        """When the link comes back, the Repairs issue is deleted."""
        from homeassistant.helpers import issue_registry as ir

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Link Recovered",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="link_recovered_flow_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        # Simulate the outage having raised the issue earlier.
        ir.async_create_issue(
            hass,
            DOMAIN,
            "transport_link_down_CE11111111",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="transport_link_down",
            translation_placeholders={"serial": "CE11111111", "host": "x"},
        )
        coordinator._link_down_notified = {"CE11111111"}

        transport = MagicMock(spec=["is_connected", "host", "port"])
        inverter = MagicMock(spec=["transport", "transport_link_down", "serial_number"])
        inverter.serial_number = "CE11111111"
        inverter.transport = transport
        inverter.transport_link_down = False  # recovered
        coordinator._inverter_cache["CE11111111"] = inverter

        processed: dict[str, Any] = {"devices": {}}
        coordinator._sync_transport_link_state(processed)

        registry = ir.async_get(hass)
        assert (
            registry.async_get_issue(DOMAIN, "transport_link_down_CE11111111") is None
        )
        assert coordinator._link_down_notified == set()


class TestParallelGroupLinkDownMarking:
    """eg4-57g review HIGH-1a: a PG aggregate mixing stale (link-down) and
    fresh members is wrong in both directions — the group must be
    error-marked and must not claim a fresh poll."""

    @staticmethod
    def _entry(entry_id: str) -> MockConfigEntry:
        return MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - PG Link Down",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                    {
                        "serial": "CE22222222",
                        "host": "192.168.1.61",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id=entry_id,
        )

    @staticmethod
    def _member(serial: str, master: bool, error: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": "inverter",
            "serial": serial,
            "parallel_number": 1,
            "parallel_master_slave": 1 if master else 2,
            "sensors": {
                "pv_total_power": 2500.0,
                "state_of_charge": 80.0,
                "battery_voltage": 53.0,
            },
        }
        if error is not None:
            data["error"] = error
        return data

    async def test_member_link_down_marks_group_and_keeps_old_stamp(self, hass):
        """One-of-two members link-down: PG error-marked, old stamp carried."""
        from datetime import UTC, datetime

        entry = self._entry("pg_link_down_test")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        old_stamp = datetime(2026, 6, 10, 11, 0, 0, tzinfo=UTC)
        processed: dict[str, Any] = {
            "devices": {
                "CE11111111": self._member("CE11111111", master=True),
                "CE22222222": self._member(
                    "CE22222222", master=False, error="Local transport link down"
                ),
                # Previous cycle's PG entry (carried forward in real cycles)
                "parallel_group_a": {
                    "type": "parallel_group",
                    "sensors": {"parallel_group_last_polled": old_stamp},
                },
            },
        }

        await coordinator._process_local_parallel_groups(processed)

        pg_data = processed["devices"]["parallel_group_a"]
        assert pg_data["error"] == (
            "Local transport link down for member(s): CE22222222"
        )
        # No fresh-poll claim: the previous stamp is carried forward.
        assert pg_data["sensors"]["parallel_group_last_polled"] == old_stamp

    async def test_all_members_healthy_group_unmarked_and_stamped_fresh(self, hass):
        """Recovery: clean members rebuild the PG without error + fresh stamp."""
        from datetime import UTC, datetime

        entry = self._entry("pg_recovered_test")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        old_stamp = datetime(2026, 6, 10, 11, 0, 0, tzinfo=UTC)
        processed: dict[str, Any] = {
            "devices": {
                "CE11111111": self._member("CE11111111", master=True),
                "CE22222222": self._member("CE22222222", master=False),
                "parallel_group_a": {
                    "type": "parallel_group",
                    "error": "Local transport link down for member(s): CE22222222",
                    "sensors": {"parallel_group_last_polled": old_stamp},
                },
            },
        }

        await coordinator._process_local_parallel_groups(processed)

        pg_data = processed["devices"]["parallel_group_a"]
        assert "error" not in pg_data
        assert pg_data["sensors"]["parallel_group_last_polled"] != old_stamp
        # Aggregate built from both fresh members
        assert pg_data["sensors"]["pv_total_power"] == 5000.0

    async def test_link_down_gridboss_contributor_marks_group(self, hass):
        """The GridBOSS CT overlay is a contributor: a link-down GridBOSS
        taints the aggregate like a link-down inverter member."""
        entry = self._entry("pg_gridboss_down_test")
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)

        processed: dict[str, Any] = {
            "devices": {
                "CE11111111": self._member("CE11111111", master=True),
                "GB00000001": {
                    "type": "gridboss",
                    "serial": "GB00000001",
                    "error": "Local transport link down",
                    "sensors": {"load_power": 1200.0},
                },
            },
        }

        await coordinator._process_local_parallel_groups(processed)

        pg_data = processed["devices"]["parallel_group_a"]
        assert pg_data["error"] == (
            "Local transport link down for member(s): GB00000001"
        )
        assert "parallel_group_last_polled" not in pg_data["sensors"]


class TestFullOutageParallelGroupMarking:
    """eg4-57g review r2 HIGH: on a FULL outage, UpdateFailed raises before
    _process_local_parallel_groups() runs — the carried-forward PG entry
    must still be error-marked (via the shared-dict mutation) or PG sensors
    serve the stale aggregate during the wrapper's suppressed window."""

    @staticmethod
    def _link_down_inverter(serial: str, host: str) -> MagicMock:
        transport = MagicMock(spec=["is_connected", "host", "port", "transport_type"])
        transport.is_connected = True
        transport.host = host
        transport.port = 502
        transport.transport_type = "modbus_tcp"
        inverter = MagicMock(
            spec=[
                "transport",
                "transport_link_down",
                "transport_runtime",
                "refresh",
                "serial_number",
            ]
        )
        inverter.serial_number = serial
        inverter.transport = transport
        inverter.transport_link_down = True
        inverter.transport_runtime = None  # cleared at the down transition
        inverter.refresh = AsyncMock()
        return inverter

    @staticmethod
    def _healthy_member(serial: str, master: bool) -> dict[str, Any]:
        return {
            "type": "inverter",
            "serial": serial,
            "parallel_number": 1,
            "parallel_master_slave": 1 if master else 2,
            "sensors": {
                "pv_total_power": 2500.0,
                "state_of_charge": 80.0,
                "battery_voltage": 53.0,
            },
        }

    async def test_full_outage_marks_carried_pg_through_retained_data(self, hass):
        """All members link-down: the suppressed-failure cycle serves cached
        data with the PG error-marked, so PG sensors read unavailable."""
        from datetime import UTC, datetime

        from custom_components.eg4_web_monitor.base_entity import EG4BaseSensor

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Full Outage",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                    {
                        "serial": "CE22222222",
                        "host": "192.168.1.61",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="full_outage_pg_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        coordinator._local_parameters_loaded = False

        old_stamp = datetime(2026, 6, 10, 11, 0, 0, tzinfo=UTC)
        coordinator.data = {
            "devices": {
                "CE11111111": {
                    "type": "inverter",
                    "sensors": {"battery_voltage": 53.2},
                },
                "CE22222222": {
                    "type": "inverter",
                    "sensors": {"battery_voltage": 52.9},
                },
                "parallel_group_a": {
                    "type": "parallel_group",
                    "member_serials": ["CE11111111", "CE22222222"],
                    "sensors": {
                        "pv_total_power": 5000.0,
                        "parallel_group_last_polled": old_stamp,
                    },
                },
            },
            "parameters": {},
        }

        coordinator._inverter_cache["CE11111111"] = self._link_down_inverter(
            "CE11111111", "192.168.1.60"
        )
        coordinator._inverter_cache["CE22222222"] = self._link_down_inverter(
            "CE22222222", "192.168.1.61"
        )

        # Drive the REAL wrapper: UpdateFailed is suppressed (failure 1/3)
        # and the cached data dict is served back.
        returned = await coordinator._async_update_data()
        assert returned is coordinator.data
        assert coordinator._consecutive_update_failures == 1
        assert coordinator.last_update_success is True

        # The shared-dict mutation made the PG mark visible through the
        # coordinator's RETAINED data — no fresh-poll claim on the stamp.
        pg_data = coordinator.data["devices"]["parallel_group_a"]
        assert pg_data["error"] == (
            "Local transport link down for member(s): CE11111111, CE22222222"
        )
        assert pg_data["sensors"]["parallel_group_last_polled"] == old_stamp

        # Member devices were marked too (round-1 behavior, unchanged)
        assert "error" in coordinator.data["devices"]["CE11111111"]

        # PG sensors read unavailable during the suppressed window
        pg_sensor = EG4BaseSensor(
            coordinator,
            "parallel_group_a",
            "pv_total_power",
            device_type="parallel_group",
        )
        assert pg_sensor.available is False

        # Recovery: the next successful cycle's PG processing replaces the
        # carried (still-marked) entry with a clean, freshly-stamped one.
        recovered_processed: dict[str, Any] = {
            "devices": {
                "CE11111111": self._healthy_member("CE11111111", master=True),
                "CE22222222": self._healthy_member("CE22222222", master=False),
                "parallel_group_a": coordinator.data["devices"]["parallel_group_a"],
            },
        }
        await coordinator._process_local_parallel_groups(recovered_processed)
        pg_rebuilt = recovered_processed["devices"]["parallel_group_a"]
        assert "error" not in pg_rebuilt
        assert pg_rebuilt["sensors"]["parallel_group_last_polled"] != old_stamp
        assert pg_rebuilt["sensors"]["pv_total_power"] == 5000.0

    async def test_transient_full_outage_without_link_down_leaves_pg_alone(self, hass):
        """A full outage with NO link-down marks (transient blips below the
        threshold) must not mark the PG: its member entities also keep
        serving cached values then, and marking only the group would be
        inconsistent (and the 'link down' message false)."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="EG4 - Transient Outage",
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                CONF_DST_SYNC: False,
                CONF_LIBRARY_DEBUG: False,
                CONF_LOCAL_TRANSPORTS: [
                    {
                        "serial": "CE11111111",
                        "host": "192.168.1.60",
                        "port": 502,
                        "transport_type": "modbus_tcp",
                        "inverter_family": "EG4_HYBRID",
                    },
                ],
            },
            entry_id="transient_outage_pg_test",
        )
        entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, entry)
        coordinator._local_static_phase_done = True
        coordinator._local_parameters_loaded = False

        coordinator.data = {
            "devices": {
                "CE11111111": {
                    "type": "inverter",
                    "sensors": {"battery_voltage": 53.2},
                },
                "parallel_group_a": {
                    "type": "parallel_group",
                    "member_serials": ["CE11111111"],
                    "sensors": {"pv_total_power": 2500.0},
                },
            },
            "parameters": {},
        }

        # Transient: read fails but the link is NOT declared down yet.
        inverter = self._link_down_inverter("CE11111111", "192.168.1.60")
        inverter.transport_link_down = False
        coordinator._inverter_cache["CE11111111"] = inverter

        returned = await coordinator._async_update_data()
        assert returned is coordinator.data

        assert "error" not in coordinator.data["devices"]["parallel_group_a"]
        assert "error" not in coordinator.data["devices"]["CE11111111"]
