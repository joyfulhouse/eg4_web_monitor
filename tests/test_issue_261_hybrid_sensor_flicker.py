"""Regression tests for issue #261 — HYBRID sensors flickering unknown/unavailable.

Two independent HYBRID-only root causes made transport-sourced sensors drop out
of ``coordinator.data`` on transient local-transport hiccups (the coordinator
rebuilds the sensor dict every poll and writes a key only when its source value
is non-None):

A. **Battery Bank SOC → unavailable.**  ``_process_inverter_object`` built the
   battery-bank aggregate from the local transport but gated it on
   ``transport_battery.battery_count > 0`` — i.e. reg 96, which is unreliable on
   parallel/multi-battery systems (#258/#170) and intermittently reads 0 even
   when the bank is real.  When it read 0 the code skipped the bank with **no
   fallback** to the still-valid cloud ``_battery_bank``, so every
   ``battery_bank_*`` key vanished and ``EG4BatteryBankEntity.available`` went
   False.  Fix: fall back to the cloud bank when the transport count is 0/None.
   A genuine shared-battery secondary reports 0 on BOTH sources and stays
   correctly skipped (#169).

B. **Fault Code → unknown.**  ``fault_code``/``warning_code`` are
   transport-exclusive (the cloud API has no field) and are injected by
   ``_TRANSPORT_OVERLAY`` only while ``transport_runtime`` is present.  When the
   local Modbus link drops, pylxpweb clears ``_transport_runtime`` and the
   overlay skipped the codes, flickering Fault Code to ``unknown`` while
   cloud-backed Status Code stayed alive.  Fix: carry the last-known
   fault/warning code forward during a link-down (status codes only — never
   measurements, which must read honestly during an outage, #226).
"""

from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from pylxpweb.transports.data import (
    BatteryBankData,
    BatteryData,
    InverterRuntimeData,
)

from tests.conftest import make_real_inverter, make_transport_spec


@pytest.fixture
def mock_config_entry():
    """A cloud config entry (HYBRID is simulated by attaching a transport)."""
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
        entry_id="issue_261_test",
    )


def _cloud_bank(*, soc, battery_count, voltage=53.4):
    """Minimal stand-in for a cloud ``BatteryBank`` device object.

    The cloud adapter reads attributes defensively (``getattr(..., None)``) and
    skips None, so a SimpleNamespace carrying only the fields under test is
    faithful — unset attributes resolve to None and are omitted, exactly like a
    real cloud bank that lacks a field.
    """
    return SimpleNamespace(soc=soc, battery_count=battery_count, voltage=voltage)


async def _make_hybrid_inverter(serial="1111111111"):
    """A real HYBRID inverter: live transport runtime + attached transport."""
    runtime = InverterRuntimeData(fault_code=0, warning_code=0, pv_total_power=1500)
    inverter = make_real_inverter(serial, "LXP-LB-US 10K", runtime=runtime)
    inverter.refresh = AsyncMock()
    inverter.detect_features = AsyncMock()
    inverter._transport = make_transport_spec()
    return inverter


# ── Root cause A: battery-bank cloud fallback (reg-96 flicker) ────────


class TestBatteryBankReg96Fallback:
    """The battery-bank aggregate must survive a transport reg-96 = 0 read."""

    async def test_reg96_zero_falls_back_to_cloud_bank(self, hass, mock_config_entry):
        """reg 96 = 0 (battery_count None) but cloud reports a populated bank.

        This is the user's captured log: ``battery_count (reg 96) = 0`` while the
        cloud shows 8 batteries.  The bank's aggregate ``soc`` is still valid, so
        battery_bank_soc must remain present via the cloud fallback instead of
        vanishing (which made the entity unavailable).
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = await _make_hybrid_inverter()
        # Combined read with reg 96 = 0: aggregate soc valid, count None, no
        # individual batteries parsed.
        inverter._transport_battery = BatteryBankData(
            soc=82, battery_count=None, batteries=[]
        )
        # Cloud still reports a populated, healthy bank.
        inverter._battery_bank = _cloud_bank(soc=82, battery_count=8)

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors.get("battery_bank_soc") == 82
        assert sensors.get("battery_bank_count") == 8

    async def test_transport_count_positive_prefers_transport(
        self, hass, mock_config_entry
    ):
        """A trustworthy transport count keeps the live local bank (unchanged)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = await _make_hybrid_inverter()
        inverter._transport_battery = BatteryBankData(
            soc=90,
            battery_count=4,
            batteries=[
                BatteryData(battery_index=0, soc=90, voltage=53.0, serial_number="B0")
            ],
        )
        # Cloud disagrees — transport must win when its count is trustworthy.
        inverter._battery_bank = _cloud_bank(soc=70, battery_count=8)

        result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"].get("battery_bank_soc") == 90

    async def test_shared_battery_secondary_still_skipped(
        self, hass, mock_config_entry
    ):
        """#169 preserved: a genuine secondary reports 0 on BOTH sources → skip."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = await _make_hybrid_inverter()
        inverter._transport_battery = BatteryBankData(
            soc=None, battery_count=None, batteries=[]
        )
        inverter._battery_bank = _cloud_bank(soc=82, battery_count=0)

        result = await coordinator._process_inverter_object(inverter)

        assert "battery_bank_soc" not in result["sensors"]


# ── Root cause B: sticky fault/warning code across a link-down ────────


class TestFaultCodeStickyOnLinkDown:
    """Transport-exclusive status codes carry forward when the link drops."""

    async def test_fault_code_carried_forward_when_link_down(
        self, hass, mock_config_entry
    ):
        """transport_runtime None (link down) → keep the last fault/warning code.

        has_data stays True via the cloud ``_runtime`` (HTTP fallback), so the
        method runs the overlay (which skips the codes) — the carry-forward must
        then restore them from the previous poll.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "LXP-LB-US 10K")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()
        inverter._transport_runtime = None  # link down: pylxpweb cleared it
        inverter._runtime = InverterRuntimeData()  # cloud fallback keeps has_data

        # Previous successful poll captured the codes while the link was up.
        coordinator.data = {
            "devices": {
                "1111111111": {
                    "sensors": {"fault_code": 0x0000_0010, "warning_code": 0x0000_0001}
                }
            }
        }

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors.get("fault_code") == 0x0000_0010
        assert sensors.get("warning_code") == 0x0000_0001

    async def test_no_carry_forward_without_prior_value(self, hass, mock_config_entry):
        """Link down with no prior poll → codes simply absent (no crash)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "LXP-LB-US 10K")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()
        inverter._transport_runtime = None
        inverter._runtime = InverterRuntimeData()
        coordinator.data = None  # first ever poll

        result = await coordinator._process_inverter_object(inverter)

        assert "fault_code" not in result["sensors"]

    async def test_live_overlay_wins_over_stale_carry_forward(
        self, hass, mock_config_entry
    ):
        """Link up: the live overlay value is used, not a stale prior value."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        runtime = InverterRuntimeData(fault_code=0x0000_0020, warning_code=0)
        inverter = make_real_inverter("1111111111", "LXP-LB-US 10K", runtime=runtime)
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        inverter._transport = make_transport_spec()
        coordinator.data = {
            "devices": {"1111111111": {"sensors": {"fault_code": 0x0000_0010}}}
        }

        result = await coordinator._process_inverter_object(inverter)

        assert result["sensors"].get("fault_code") == 0x0000_0020

    async def test_no_carry_forward_in_pure_cloud(self, hass, mock_config_entry):
        """Pure CLOUD (no transport attached) never carries codes forward.

        The carry-forward is gated on `inverter.transport is not None`, keeping
        it a HYBRID-only path. A cloud-only inverter has no transport, so even a
        prior `fault_code` in coordinator data must NOT resurface — the codes
        belong to the local transport and the cloud has no fault field. Without
        the gate this would (incidentally) carry the stale value, since
        `transport_runtime` is always None in pure CLOUD.
        """
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)

        inverter = make_real_inverter("1111111111", "LXP-LB-US 10K")
        inverter.refresh = AsyncMock()
        inverter.detect_features = AsyncMock()
        # No transport attached (pure CLOUD); cloud runtime keeps has_data True.
        inverter._runtime = InverterRuntimeData()
        coordinator.data = {
            "devices": {"1111111111": {"sensors": {"fault_code": 0x0000_0010}}}
        }

        result = await coordinator._process_inverter_object(inverter)

        assert "fault_code" not in result["sensors"]
