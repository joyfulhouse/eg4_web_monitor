"""Tests for issue #479 — cloud-lost inverter measurements blank to unknown.

When an inverter's dongle loses its internet link, the EG4 portal keeps
answering ``getInverterRuntime`` with ``success:true`` and the last register
mirror it received, flagged only by ``lost:true`` / ``statusText:"offline"``.
Before the fix every runtime/energy sensor froze at its pre-outage value for
the whole outage.  The coordinator now blanks measurement sensors to None
(HA "unknown") while keeping the diagnostic/status keys so the device stays
present and clearly reports the outage (#256 philosophy: present-but-unknown).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pylxpweb.models import InverterRuntime
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
from custom_components.eg4_web_monitor.coordinator_mappings import (
    LOST_KEEP_SENSOR_KEYS,
    blank_lost_battery_measurements,
    blank_lost_inverter_measurements,
)

from .conftest import make_real_inverter

try:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
except ImportError:  # pragma: no cover
    CONF_USERNAME = "username"
    CONF_PASSWORD = "password"


def _cloud_runtime(*, lost: bool, serial: str = "5555555555") -> InverterRuntime:
    """Build a cloud getInverterRuntime payload.

    A lost payload mirrors real portal behavior: the live aggregate fields
    (status/soc/vBat/ppv/pinv/...) are omitted, but the register-mirror
    fields (per-string PV, voltages, temperatures, pToGrid) keep serving the
    FROZEN pre-outage values — exactly the values #479 saw stuck in HA.
    """
    payload: dict[str, object] = {
        "success": True,
        "serialNum": serial,
        "fwCode": "fAAB-2727",
        "powerRatingText": "12kW",
        "lost": lost,
        "statusText": "offline" if lost else "normal",
        "batteryType": "LITHIUM",
        "serverTime": "2026-07-21 16:00:00",
        "deviceTime": "2026-07-21 10:00:00",
        "vpv1": 3050,
        "vpv2": 2980,
        "ppv1": 1500,
        "ppv2": 1200,
        "vacr": 2400,
        "vacs": 0,
        "vact": 0,
        "fac": 5999,
        "pf": "1.0",
        "vepsr": 2400,
        "vepss": 0,
        "vepst": 0,
        "feps": 5999,
        "seps": 0,
        "pToGrid": 200,
        "pToUser": 0,
        "tinner": 45,
        "tradiator1": 41,
        "tradiator2": 39,
        "tBat": 25,
        "vBus1": 38000,
        "vBus2": 37500,
    }
    if not lost:
        payload.update(
            {
                "status": 0x10,
                "soc": 80,
                "vBat": 532,
                "ppv": 2700,
                "pCharge": 0,
                "pDisCharge": 500,
                "batPower": -500,
                "pinv": 2000,
                "prec": 0,
                "peps": 0,
            }
        )
    return InverterRuntime.model_validate(payload)


# ── blank_lost_inverter_measurements (pure helper) ───────────────────


class TestBlankLostInverterMeasurements:
    """Unit tests for the blanking helper."""

    def _processed(self) -> dict:
        return {
            "sensors": {
                "pv1_power": 1500,
                "grid_power": 200.0,
                "yield": 12.3,
                "yield_lifetime": 4188.0,
                "state_of_charge": 80,
                "firmware_version": "fAAB-2727",
                "inverter_family": "EG4_HYBRID",
                "device_type_code": 6,
                "grid_type": "split_phase",
                "status_text": "offline",
                "operating_state": None,
                "fault_code": 0,
                "warning_code": 0,
            },
            "binary_sensors": {"is_lost": True, "is_using_generator": False},
        }

    def test_measurements_blank_to_none(self) -> None:
        processed = self._processed()
        blank_lost_inverter_measurements(processed)
        sensors = processed["sensors"]
        assert sensors["pv1_power"] is None
        assert sensors["grid_power"] is None
        assert sensors["yield"] is None
        assert sensors["yield_lifetime"] is None
        assert sensors["state_of_charge"] is None

    def test_keys_stay_present_for_entity_availability(self) -> None:
        """Blanked keys must remain in the dict (None, not deleted)."""
        processed = self._processed()
        keys_before = set(processed["sensors"])
        blank_lost_inverter_measurements(processed)
        assert set(processed["sensors"]) == keys_before

    def test_diagnostic_and_status_keys_survive(self) -> None:
        processed = self._processed()
        blank_lost_inverter_measurements(processed)
        sensors = processed["sensors"]
        assert sensors["firmware_version"] == "fAAB-2727"
        assert sensors["inverter_family"] == "EG4_HYBRID"
        assert sensors["device_type_code"] == 6
        assert sensors["grid_type"] == "split_phase"
        assert sensors["status_text"] == "offline"
        assert sensors["fault_code"] == 0
        assert sensors["warning_code"] == 0

    def test_is_lost_binary_sensor_survives(self) -> None:
        processed = self._processed()
        blank_lost_inverter_measurements(processed)
        assert processed["binary_sensors"]["is_lost"] is True
        # Other binary readings are cloud mirrors and blank like measurements.
        assert processed["binary_sensors"]["is_using_generator"] is None

    def test_keep_set_matches_helper_behavior(self) -> None:
        """Every keep-key survives; everything else blanks."""
        processed = {
            "sensors": dict.fromkeys(LOST_KEEP_SENSOR_KEYS, "kept")
            | {"some_measurement": 1.0},
            "binary_sensors": {},
        }
        blank_lost_inverter_measurements(processed)
        for key in LOST_KEEP_SENSOR_KEYS:
            assert processed["sensors"][key] == "kept"
        assert processed["sensors"]["some_measurement"] is None


# ── coordinator path ─────────────────────────────────────────────────


@pytest.fixture
def mock_config_entry():
    """Minimal cloud config entry for coordinator construction."""
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
        entry_id="issue_479_test",
    )


def _make_coordinator(hass, entry) -> EG4DataUpdateCoordinator:
    """Coordinator with a mocked LuxpowerClient — hermetic, no network."""
    with (
        patch("custom_components.eg4_web_monitor.coordinator.LuxpowerClient"),
        patch("custom_components.eg4_web_monitor.coordinator.aiohttp_client"),
    ):
        return EG4DataUpdateCoordinator(hass, entry)


def _make_cloud_inverter(*, lost: bool):
    """Real HybridInverter carrying only a cloud runtime payload (pure CLOUD)."""
    inverter = make_real_inverter("5555555555", "FlexBOSS21")
    inverter._runtime = _cloud_runtime(lost=lost)
    inverter.refresh = AsyncMock()
    inverter.detect_features = AsyncMock()
    return inverter


class TestProcessInverterObjectLost:
    """_process_inverter_object blanks measurements when cloud reports lost."""

    async def test_lost_inverter_measurements_blank(self, hass, mock_config_entry):
        """The #479 scenario: lost=true payload with frozen register mirror."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=True)
        assert inverter.is_lost is True  # precondition
        assert inverter.has_data is True  # NOT the #256 no-data early return

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        # Frozen register-mirror values must read unknown, not pre-outage.
        assert sensors["pv1_power"] is None
        assert sensors["pv1_voltage"] is None
        assert sensors["radiator1_temperature"] is None
        assert sensors["grid_power"] is None
        # ... but the keys stay present so the entities remain available.
        assert "pv1_power" in sensors

        # Fresh, honest signals survive.
        assert sensors["status_text"] == "offline"
        assert sensors["firmware_version"] == "fAAB-2727"
        assert result["binary_sensors"]["is_lost"] is True
        # last_polled is stamped after blanking — the poll DID happen.
        assert sensors["last_polled"] is not None

    async def test_online_inverter_keeps_measurements(self, hass, mock_config_entry):
        """Control: identical payload with lost=false keeps every value."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=False)
        assert inverter.is_lost is False

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]

        assert sensors["pv1_power"] == 1500
        assert sensors["pv1_voltage"] == 305.0
        assert sensors["state_of_charge"] == 80
        assert sensors["status_text"] == "normal"
        assert result["binary_sensors"]["is_lost"] is False

    async def test_hybrid_local_data_overrides_cloud_lost(
        self, hass, mock_config_entry
    ):
        """HYBRID with live transport runtime ignores the cloud lost flag.

        pylxpweb ``is_lost`` returns False whenever transport runtime is
        attached — local Modbus data is fresh even if the dongle lost its
        internet route to the portal.
        """
        from pylxpweb.transports.data import InverterRuntimeData

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=True)
        inverter._transport_runtime = InverterRuntimeData(pv1_power=999)
        assert inverter.is_lost is False

        result = await coordinator._process_inverter_object(inverter)
        assert result["sensors"]["pv1_power"] == 999


# ── round-2 review fixes ─────────────────────────────────────────────


class TestLostStatusAndRatingsSurvive:
    """The Connection Lost sensor and static ratings must not blank (#479 r2)."""

    def test_lost_status_sensor_survives(self) -> None:
        """inverter_lost_status IS the Connection Lost entity — blanking it
        would read unknown at the exact moment it must read lost."""
        processed = {
            "sensors": {"inverter_lost_status": True, "pv1_power": 1500},
            "binary_sensors": {},
        }
        blank_lost_inverter_measurements(processed)
        assert processed["sensors"]["inverter_lost_status"] is True
        assert processed["sensors"]["pv1_power"] is None

    def test_static_ratings_survive(self) -> None:
        processed = {
            "sensors": {"power_rating": "12kW", "inverter_power_rating": "12kW"},
            "binary_sensors": {},
        }
        blank_lost_inverter_measurements(processed)
        assert processed["sensors"]["power_rating"] == "12kW"
        assert processed["sensors"]["inverter_power_rating"] == "12kW"


class TestBlankLostBatteryMeasurements:
    """Individual battery values blank while identity/spec metadata stays."""

    def test_measurements_blank_metadata_survives(self) -> None:
        battery = {
            "battery_real_voltage": 53.2,
            "battery_real_current": -4.1,
            "battery_rsoc": 81,
            "battery_max_cell_voltage": 3.331,
            "cycle_count": 412,
            "battery_serial_number": "BAT001122334",
            "battery_index": 1,
            "battery_model": "WallMount",
            "battery_bms_model": "BMS01",
            "battery_type_text": "Lithium",
            "battery_firmware_version": "1.9",
            "battery_design_capacity": 280,
            "battery_last_seen": "2026-07-21T10:00:00",
            "battery_last_polled": "2026-07-21T16:00:00",
        }
        keys_before = set(battery)
        blank_lost_battery_measurements(battery)
        assert set(battery) == keys_before  # keys stay present
        assert battery["battery_real_voltage"] is None
        assert battery["battery_real_current"] is None
        assert battery["battery_rsoc"] is None
        assert battery["battery_max_cell_voltage"] is None
        assert battery["cycle_count"] is None
        assert battery["battery_serial_number"] == "BAT001122334"
        assert battery["battery_index"] == 1
        assert battery["battery_model"] == "WallMount"
        assert battery["battery_firmware_version"] == "1.9"
        assert battery["battery_design_capacity"] == 280
        assert battery["battery_last_seen"] == "2026-07-21T10:00:00"


class TestParallelGroupLostMember:
    """Group aggregates blank when any member is cloud-lost (#479 r2)."""

    async def test_lost_member_blanks_group_aggregates(
        self, hass, mock_config_entry
    ) -> None:
        from unittest.mock import MagicMock

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        lost_member = _make_cloud_inverter(lost=True)
        group = MagicMock()
        group.name = "Group1"
        group.first_device_serial = "5555555555"
        group.inverters = [lost_member]
        group.pv_total_power = 2700
        group.grid_power = 200
        group.today_yielding = 12.3
        group.transport_energy = None

        result = await coordinator._process_parallel_group_object(group)
        sensors = result["sensors"]
        assert sensors["pv_total_power"] is None
        assert sensors["grid_power"] is None
        assert sensors["yield"] is None
        # The poll timestamp is honest — the poll did happen.
        assert sensors["parallel_group_last_polled"] is not None

    async def test_online_members_keep_group_aggregates(
        self, hass, mock_config_entry
    ) -> None:
        from unittest.mock import MagicMock

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        member = _make_cloud_inverter(lost=False)
        group = MagicMock()
        group.name = "Group1"
        group.first_device_serial = "5555555555"
        group.inverters = [member]
        group.pv_total_power = 2700
        group.transport_energy = None

        result = await coordinator._process_parallel_group_object(group)
        assert result["sensors"]["pv_total_power"] == 2700


class TestHybridCloudSupplementalLost:
    """HYBRID with live transport but a lost cloud mirror blanks only the
    cloud-supplemental #222 load-split keys (#479 r2)."""

    async def test_cloud_supplemental_keys_blank(self, hass, mock_config_entry):
        from pylxpweb.transports.data import InverterRuntimeData

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=True)
        inverter._transport_runtime = InverterRuntimeData(pv1_power=999)
        assert inverter.is_lost is False  # transport keeps the device live

        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]
        # Live local measurement survives.
        assert sensors["pv1_power"] == 999
        # Cloud-supplemental keys must not freeze: either blanked to None or
        # never published this cycle.
        for key in ("smart_load_power", "grid_load_power", "eps_load_power"):
            assert sensors.get(key) is None


class TestLostRecoveryStateful:
    """Same inverter object transitions lost → recovered (#479 r2)."""

    async def test_recovery_restores_measurements(self, hass, mock_config_entry):
        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=True)
        result = await coordinator._process_inverter_object(inverter)
        assert result["sensors"]["pv1_power"] is None
        assert result["binary_sensors"]["is_lost"] is True

        # The dongle reconnects: the next poll serves a live payload.
        inverter._runtime = _cloud_runtime(lost=False)
        result = await coordinator._process_inverter_object(inverter)
        assert result["sensors"]["pv1_power"] == 1500
        assert result["sensors"]["state_of_charge"] == 80
        assert result["binary_sensors"]["is_lost"] is False


class TestGroupResurrectionPaths:
    """Post-blanking pipeline steps must not resurrect group values (#479 r2)."""

    def test_ac_couple_adjustment_skips_blanked_pv(self) -> None:
        """A blanked (None) pv_total_power must stay None — writing only the
        AC-couple contribution would publish an understated real value."""
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            apply_ac_couple_pv_adjustment,
        )

        pg_sensors = {"pv_total_power": None}
        gb_sensors = {
            "smart_port1_status": "ac_couple",
            "ac_couple1_power_l1": 1200,
            "ac_couple1_power_l2": 1100,
        }
        apply_ac_couple_pv_adjustment(
            pg_sensors, gb_sensors, "g1", include_ac_couple=True
        )
        assert pg_sensors["pv_total_power"] is None

    def test_ac_couple_adjustment_still_adds_to_live_pv(self) -> None:
        from custom_components.eg4_web_monitor.coordinator_mixins import (
            apply_ac_couple_pv_adjustment,
        )

        pg_sensors = {"pv_total_power": 500.0}
        gb_sensors = {
            "smart_port1_status": "ac_couple",
            "ac_couple1_power_l1": 1200,
            "ac_couple1_power_l2": 1100,
        }
        apply_ac_couple_pv_adjustment(
            pg_sensors, gb_sensors, "g1", include_ac_couple=True
        )
        assert pg_sensors["pv_total_power"] == 2800.0

    async def test_group_flag_published(self, hass, mock_config_entry) -> None:
        """_process_parallel_group_object publishes has_lost_member for the
        downstream battery count/current override gate."""
        from unittest.mock import MagicMock

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        group = MagicMock()
        group.name = "Group1"
        group.first_device_serial = "5555555555"
        group.inverters = [_make_cloud_inverter(lost=True)]
        group.transport_energy = None
        result = await coordinator._process_parallel_group_object(group)
        assert result["has_lost_member"] is True

        group.inverters = [_make_cloud_inverter(lost=False)]
        result = await coordinator._process_parallel_group_object(group)
        assert result["has_lost_member"] is False

    async def test_pipeline_does_not_resurrect_battery_current(
        self, hass, mock_config_entry
    ) -> None:
        """Full station pipeline: with a lost member, the member-battery
        aggregation override must not write parallel_battery_current back
        over the blanked group sensors."""
        from unittest.mock import AsyncMock, MagicMock

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        from types import SimpleNamespace

        lost = _make_cloud_inverter(lost=True)
        live = _make_cloud_inverter(lost=False)
        live._runtime = _cloud_runtime(lost=False, serial="6666666666")
        live.serial_number = "6666666666"
        # Give the LIVE member a real bank current so the aggregation loop's
        # has_current actually trips — without this the guarded write is
        # never reached and the test passes vacuously with or without the
        # has_lost_member gate (round-3 review).  batteries=[] keeps the
        # individual-battery loop on its quiet carry-forward path.
        live._battery_bank = SimpleNamespace(
            battery_count=2, current=10.0, batteries=[]
        )

        group = MagicMock()
        group.name = "Group1"
        group.first_device_serial = "5555555555"
        group.inverters = [lost, live]
        group.mid_device = None
        group.transport_energy = None
        group._fetch_energy_data = AsyncMock()

        station = MagicMock()
        station.id = "12345"
        station.name = "Test Station"
        station.timezone = "GMT -8"
        station.all_inverters = [lost, live]
        station.all_mid_devices = []
        station.refresh_all_data = AsyncMock()
        station.detect_dst_status = MagicMock(return_value=None)
        station.sync_dst_setting = AsyncMock(return_value=True)
        station.parallel_groups = [group]
        coordinator.station = station

        result = await coordinator._process_station_data()

        pg = result["devices"]["parallel_group_group1"]
        assert pg["has_lost_member"] is True
        # No partial sum resurrected over the blanked aggregates.
        assert pg["sensors"].get("parallel_battery_current") is None
        assert pg["sensors"].get("pv_total_power") is None
        assert pg["sensors"].get("parallel_battery_count") is None


class TestLostCloudBankKeepsKeys:
    """A lost cloud bank blanks values but keeps keys (#479 r3/#261).

    Bank-entity availability is key-presence: dropping the keys would flip
    the aggregate entities unavailable (the #261 flicker) instead of the
    intended present-but-unknown.
    """

    async def test_lost_bank_extracts_keys_with_none_values(
        self, hass, mock_config_entry
    ) -> None:
        from types import SimpleNamespace

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        # Inverter NOT lost (runtime and battery endpoints have separate
        # cadences and can transiently disagree) — isolates the bank-level
        # gate from the inverter-level blanking.
        inverter = _make_cloud_inverter(lost=False)
        inverter._battery_bank = SimpleNamespace(
            battery_count=2,
            current=10.0,
            voltage=53.2,
            is_lost=True,
            batteries=[],
        )
        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]
        # Keys present (entities stay available) but values unknown.
        assert "battery_bank_current" in sensors
        assert sensors["battery_bank_current"] is None
        assert "battery_bank_voltage" in sensors
        assert sensors["battery_bank_voltage"] is None

    async def test_live_bank_keeps_values(self, hass, mock_config_entry) -> None:
        from types import SimpleNamespace

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=False)
        inverter._battery_bank = SimpleNamespace(
            battery_count=2,
            current=10.0,
            voltage=53.2,
            is_lost=False,
            batteries=[],
        )
        result = await coordinator._process_inverter_object(inverter)
        assert result["sensors"]["battery_bank_current"] == 10.0


class TestCarryForwardCacheBlanking:
    """The blanking pass must reach the #258 carry-forward store (#479 r4).

    The post-loop blanking mutates per-battery dicts in place; the
    carry-forward store snapshots dict(current) — a SHALLOW copy sharing
    those inner dicts — so the cache blanks by aliasing.  This test pins
    that coupling: if either side starts deep-copying, a later
    carry-forward cycle would resurrect the frozen pre-outage values.
    """

    async def test_blanking_propagates_into_carry_forward_cache(
        self, hass, mock_config_entry
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        serial = "5555555555"
        battery = {
            "battery_real_voltage": 53.2,
            "battery_serial_number": "BAT001122334",
        }
        device_data = {"type": "inverter", "batteries": {"key1": battery}}
        # Seed the carry-forward store the way the pipeline does (shallow
        # snapshot of the current batteries dict).
        coordinator._apply_battery_carry_forward(serial, device_data)
        assert coordinator._battery_carry_forward[serial]["key1"] is battery

        blank_lost_battery_measurements(battery)

        cached = coordinator._battery_carry_forward[serial]["key1"]
        assert cached["battery_real_voltage"] is None
        assert cached["battery_serial_number"] == "BAT001122334"


class TestLostBankOmittedFieldKeys:
    """A lost bank's OMITTED fields must still publish None keys (#479 r5).

    The cloud extractor skips fields the lost payload omits, so without the
    prior-cycle key union the already-created entities behind those keys
    would flip unavailable (key-presence availability) instead of unknown.
    """

    async def test_prior_cycle_bank_keys_union_as_none(
        self, hass, mock_config_entry
    ) -> None:
        from types import SimpleNamespace

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        # Previous healthy cycle published a bank SOC the lost payload omits.
        coordinator.data = {
            "devices": {
                "5555555555": {
                    "sensors": {
                        "battery_bank_soc": 80,
                        "battery_status": "Normal",
                        "pv1_power": 1500,
                    }
                }
            }
        }
        inverter = _make_cloud_inverter(lost=False)
        # Lost bank still mirrors current/voltage but omits soc entirely.
        inverter._battery_bank = SimpleNamespace(
            battery_count=2,
            current=10.0,
            voltage=53.2,
            is_lost=True,
            batteries=[],
        )
        result = await coordinator._process_inverter_object(inverter)
        sensors = result["sensors"]
        assert "battery_bank_soc" in sensors  # unioned from the prior cycle
        assert sensors["battery_bank_soc"] is None
        assert "battery_status" in sensors
        assert sensors["battery_status"] is None
        # Non-bank prior keys are NOT unioned by this path.
        assert sensors.get("pv1_power") == 1500


class TestBatteryBlankingOnBankEndpointDisagreement:
    """Per-battery blanking also fires on a lost BANK with an online runtime
    (#479 r5): the endpoints poll independently and can transiently disagree;
    the frozen module mirror must not republish through the gap."""

    async def test_bank_lost_runtime_online_blanks_batteries(
        self, hass, mock_config_entry
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock as _AsyncMock

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        from homeassistant.util import dt as dt_util

        # Runtime says ONLINE; only the battery endpoint is lost (empty
        # module array), and the #258 carry-forward store still holds the
        # frozen pre-outage module — the republish path Codex flagged.
        inverter = _make_cloud_inverter(lost=False)
        inverter._battery_bank = SimpleNamespace(
            is_lost=True, battery_count=1, batteries=[]
        )
        coordinator._battery_carry_forward = {
            "5555555555": {
                "key1": {
                    "battery_real_voltage": 53.2,
                    "battery_serial_number": "BAT001122334",
                    "battery_last_seen": dt_util.utcnow(),
                }
            }
        }
        coordinator._inverter_cache = {"5555555555": inverter}
        coordinator.station = SimpleNamespace(
            id="12345",
            name="Test Station",
            timezone="GMT -8",
            all_inverters=[inverter],
            all_mid_devices=[],
            refresh_all_data=_AsyncMock(),
            detect_dst_status=lambda: None,
            sync_dst_setting=_AsyncMock(return_value=True),
            parallel_groups=[],
        )

        result = await coordinator._process_station_data()
        device = result["devices"]["5555555555"]
        assert device["batteries"], "frozen module should still be published"
        for battery_sensors in device["batteries"].values():
            # Measurements blanked; identity metadata survives.
            assert battery_sensors.get("battery_serial_number") == "BAT001122334"
            for key, value in battery_sensors.items():
                if key not in (
                    "battery_serial_number",
                    "battery_index",
                    "battery_model",
                    "battery_bms_model",
                    "battery_type",
                    "battery_type_text",
                    "battery_firmware_version",
                    "battery_design_capacity",
                    "battery_last_seen",
                    "battery_last_polled",
                ):
                    assert value is None, f"{key} not blanked: {value!r}"


class TestStaleTransportAccumulatorDoesNotExempt:
    """A merely NON-EMPTY transport accumulator must not suppress blanking
    (#479 r6): 5002+ block reads can fail while runtime reads keep the link
    up, so the never-evict accumulator serves stale blocks the merge overlay
    already skips — the gate must apply the same freshness rule."""

    async def test_stale_blocks_do_not_exempt_blanking(
        self, hass, mock_config_entry
    ) -> None:
        from datetime import timedelta
        from types import SimpleNamespace
        from unittest.mock import AsyncMock as _AsyncMock

        from homeassistant.util import dt as dt_util

        mock_config_entry.add_to_hass(hass)
        coordinator = _make_coordinator(hass, mock_config_entry)

        inverter = _make_cloud_inverter(lost=False)  # runtime online
        from pylxpweb.transports.data import BatteryData

        stale_block = BatteryData(
            battery_index=0,
            serial_number="BAT001122334",
            voltage=53.2,
            soc=80,
        )
        stale_block.last_seen = dt_util.utcnow() - timedelta(minutes=10)
        inverter._battery_bank = SimpleNamespace(is_lost=True, batteries=[])
        inverter._transport_battery = SimpleNamespace(batteries=[stale_block])
        coordinator._battery_carry_forward = {
            "5555555555": {
                "key1": {
                    "battery_real_voltage": 53.2,
                    "battery_serial_number": "BAT001122334",
                    "battery_last_seen": dt_util.utcnow(),
                }
            }
        }
        coordinator._inverter_cache = {"5555555555": inverter}
        coordinator.station = SimpleNamespace(
            id="12345",
            name="Test Station",
            timezone="GMT -8",
            all_inverters=[inverter],
            all_mid_devices=[],
            refresh_all_data=_AsyncMock(),
            detect_dst_status=lambda: None,
            sync_dst_setting=_AsyncMock(return_value=True),
            parallel_groups=[],
        )

        result = await coordinator._process_station_data()
        batteries = result["devices"]["5555555555"]["batteries"]
        assert batteries
        for battery_sensors in batteries.values():
            assert battery_sensors.get("battery_real_voltage") is None

    async def test_fresh_block_exempts_blanking(self, hass, mock_config_entry) -> None:
        """Control: one block read within the window keeps HYBRID data live."""
        from types import SimpleNamespace

        from homeassistant.util import dt as dt_util

        from custom_components.eg4_web_monitor.coordinator_http import (
            HYBRID_TRANSPORT_FRESHNESS,
        )

        fresh_block = SimpleNamespace(
            battery_sn="BAT001122334", last_seen=dt_util.utcnow()
        )
        transport_battery = SimpleNamespace(batteries=[fresh_block])
        has_fresh = any(
            (ls := getattr(b, "last_seen", None)) is not None
            and dt_util.utcnow() - dt_util.as_utc(ls) <= HYBRID_TRANSPORT_FRESHNESS
            for b in getattr(transport_battery, "batteries", None) or []
        )
        assert has_fresh is True
