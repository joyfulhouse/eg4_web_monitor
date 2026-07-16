"""Tests for the cloud event-log Last Event sensor + fetch_events service (#327).

Some events exist ONLY in the portal's event log (transients between polls,
pushed to the cloud out-of-band). These tests cover:

- normalize_event_row: normalization of the live-validated
  /WManage/api/analyze/event/list row shape (docs/api/openapi.yaml).
- EG4DataUpdateCoordinator._fetch_last_event: throttled cloud fetch,
  carry-forward, truncation, LOCAL-mode no-op.
- EG4LastEventSensor: entity creation gating, state and attributes.
- eg4_web_monitor.fetch_events service: response payload, serial filtering,
  and ServiceValidationError paths (pure LOCAL, unknown serial).
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor import SERVICE_FETCH_EVENTS, async_setup
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.sensor import (
    EG4LastEventSensor,
    _create_inverter_sensors,
    _create_simple_device_sensors,
)
from custom_components.eg4_web_monitor.services import async_fetch_events
from custom_components.eg4_web_monitor.utils import normalize_event_row
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

INVERTER_SERIAL = "1234567890"
GRIDBOSS_SERIAL = "4524850115"

# Row shape live-validated against the portal 2026-07-15 (docs/api/openapi.yaml
# EventRow schema) — NOT the (incorrect) pylxpweb docstring field names.
FAULT_ROW: dict[str, Any] = {
    "recordId": 7583193,
    "plantName": "Test Plant",
    "serialNum": INVERTER_SERIAL,
    "datalogSn": "BC33600194",
    "eventTypeText": "Fault",
    "eventType": "FAULT",
    "eventText": "Bus voltage high",
    "event": "E019",
    "startTime": "2026-07-01 16:50:28",
    "renormalTime": "2026-07-01 18:04:31",
    "faultDuration": "1.23",
    "startSlashTime": "2026/07/01 16:50:28",
    "renormalSlashTime": "2026/07/01 18:04:31",
    "status": "CLOSE",
}

# GridBOSS rows carry eventType values beyond the FAULT/WARNING/INFO enum.
MIDBOX_ROW: dict[str, Any] = {
    "recordId": 7298160,
    "serialNum": GRIDBOSS_SERIAL,
    "eventTypeText": "Notice",
    "eventType": "MIDBOX_WARNING",
    "eventText": "Grid frequency abnormality",
    "event": "W018",
    "startTime": "2026-06-15 15:45:24",
    "renormalTime": None,
    "status": "OPEN",
}


def _event_response(rows: list[dict[str, Any]], total: int | None = None) -> dict:
    return {
        "success": True,
        "total": total if total is not None else len(rows),
        "rows": rows,
    }


# ── normalize_event_row ──────────────────────────────────────────────


class TestNormalizeEventRow:
    """Normalization of raw portal event rows."""

    def test_closed_fault_row(self):
        """CLOSE status maps to RESOLVED; fields map to the normalized keys."""
        event = normalize_event_row(FAULT_ROW)
        assert event == {
            "record_id": 7583193,
            "event_code": "E019",
            "event_text": "Bus voltage high",
            "event_type": "FAULT",
            "start_time": "2026-07-01 16:50:28",
            "end_time": "2026-07-01 18:04:31",
            "status": "RESOLVED",
        }

    def test_open_midbox_row(self):
        """OPEN maps to ACTIVE; non-enum eventType passes through verbatim;
        an ongoing event has end_time None."""
        event = normalize_event_row(MIDBOX_ROW)
        assert event["status"] == "ACTIVE"
        assert event["event_type"] == "MIDBOX_WARNING"
        assert event["end_time"] is None

    def test_unknown_status_passes_through(self):
        """A status outside OPEN/CLOSE is not mangled."""
        assert normalize_event_row({"status": "PENDING"})["status"] == "PENDING"

    def test_missing_fields_are_none(self):
        """A defensive normalize of an empty row yields all-None values."""
        event = normalize_event_row({})
        assert event is not None
        assert all(value is None for value in event.values())

    def test_non_dict_row_returns_none(self):
        """The row schema is effectively unvalidated upstream — a non-dict
        row is reported as None (parse failure), never an AttributeError."""
        assert normalize_event_row("garbage") is None
        assert normalize_event_row(None) is None
        assert normalize_event_row(["list"]) is None


# ── Coordinator fetch ────────────────────────────────────────────────


@pytest.fixture
def mock_config_entry():
    """Cloud-mode config entry."""
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
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
        },
        entry_id="test_entry_id",
    )


def _coordinator_with_events(
    hass, mock_config_entry, rows: list[Any]
) -> EG4DataUpdateCoordinator:
    """Real coordinator with a mocked cloud event-list endpoint."""
    coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
    client = MagicMock()
    client.analytics.get_event_list = AsyncMock(return_value=_event_response(rows))
    coordinator.client = client
    return coordinator


class TestFetchLastEvent:
    """Coordinator._fetch_last_event behavior."""

    async def test_publishes_state_and_detail(self, hass, mock_config_entry):
        """A fresh fetch publishes the newest event text + normalized detail."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(hass, mock_config_entry, [FAULT_ROW])
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        coordinator.client.analytics.get_event_list.assert_awaited_once_with(
            INVERTER_SERIAL, rows=1
        )
        assert target["sensors"]["last_event"] == "Bus voltage high"
        detail = target["last_event_detail"]
        assert detail["event_code"] == "E019"
        assert detail["status"] == "RESOLVED"

    async def test_empty_rows_publishes_unknown(self, hass, mock_config_entry):
        """No events -> state None (HA unknown), never an empty string."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(hass, mock_config_entry, [])
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert "last_event" in target["sensors"]
        assert target["sensors"]["last_event"] is None
        assert target["last_event_detail"] is None

    async def test_no_client_publishes_nothing(self, hass, mock_config_entry):
        """Pure LOCAL (no cloud client): the key is never published, so the
        sensor entity is never created."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        coordinator.client = None
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert "last_event" not in target["sensors"]
        assert "last_event_detail" not in target

    async def test_missing_endpoint_publishes_nothing(self, hass, mock_config_entry):
        """A pylxpweb without analytics.get_event_list is a silent no-op."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        client = MagicMock()
        client.analytics = MagicMock(spec=[])  # no get_event_list attribute
        coordinator.client = client
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert "last_event" not in target["sensors"]

    async def test_throttle_carries_forward(self, hass, mock_config_entry):
        """A second call inside the 5-minute window does not hit the cloud;
        the previous cycle's published value is carried forward."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(hass, mock_config_entry, [FAULT_ROW])

        first: dict[str, Any] = {"sensors": {}}
        await coordinator._fetch_last_event(INVERTER_SERIAL, first)
        # Simulate the processed dict becoming the coordinator's data.
        coordinator.data = {"devices": {INVERTER_SERIAL: first}}

        second: dict[str, Any] = {"sensors": {}}
        await coordinator._fetch_last_event(INVERTER_SERIAL, second)

        coordinator.client.analytics.get_event_list.assert_awaited_once()
        assert second["sensors"]["last_event"] == "Bus voltage high"
        assert second["last_event_detail"]["event_code"] == "E019"

    async def test_failure_carries_previous_value(self, hass, mock_config_entry):
        """A failed cloud read must not flicker the sensor to unknown."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        client = MagicMock()
        client.analytics.get_event_list = AsyncMock(side_effect=OSError("boom"))
        coordinator.client = client
        coordinator.data = {
            "devices": {
                INVERTER_SERIAL: {
                    "sensors": {"last_event": "Bus voltage high"},
                    "last_event_detail": {"event_code": "E019"},
                }
            }
        }
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert target["sensors"]["last_event"] == "Bus voltage high"
        assert target["last_event_detail"] == {"event_code": "E019"}

    async def test_failure_without_previous_publishes_unknown(
        self, hass, mock_config_entry
    ):
        """First-ever fetch failing still publishes the key (state unknown)
        so the entity exists."""
        mock_config_entry.add_to_hass(hass)
        coordinator = EG4DataUpdateCoordinator(hass, mock_config_entry)
        client = MagicMock()
        client.analytics.get_event_list = AsyncMock(side_effect=OSError("boom"))
        coordinator.client = client
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert "last_event" in target["sensors"]
        assert target["sensors"]["last_event"] is None

    async def test_malformed_row_carries_forward_and_spares_other_sensors(
        self, hass, mock_config_entry
    ):
        """Codex P2: a malformed (non-dict) event row must stay inside the
        fetch's exception boundary — it degrades to carry-forward and leaves
        the device's other sensors untouched, instead of escaping to the
        outer per-device handler (which would blank EVERY sensor for the
        cycle)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(
            hass, mock_config_entry, ["not-a-dict-row"]
        )
        coordinator.data = {
            "devices": {
                INVERTER_SERIAL: {
                    "sensors": {"last_event": "Bus voltage high"},
                    "last_event_detail": {"event_code": "E019"},
                }
            }
        }
        target: dict[str, Any] = {"sensors": {"status_code": 0, "yield": 12.5}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        # Previous event carried forward, not blanked and not raising.
        assert target["sensors"]["last_event"] == "Bus voltage high"
        assert target["last_event_detail"] == {"event_code": "E019"}
        # Other sensors on the device dict are untouched.
        assert target["sensors"]["status_code"] == 0
        assert target["sensors"]["yield"] == 12.5
        # The failed parse consumed the throttle slot (no retry storm).
        assert f"events_{INVERTER_SERIAL}" in coordinator._last_status_fetch

    async def test_state_truncated_to_255_chars(self, hass, mock_config_entry):
        """HA rejects states >255 chars — the state is truncated defensively;
        the detail keeps the full text."""
        long_text = "x" * 300
        row = {**FAULT_ROW, "eventText": long_text}
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(hass, mock_config_entry, [row])
        target: dict[str, Any] = {"sensors": {}}

        await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        assert target["sensors"]["last_event"] == "x" * 255
        assert target["last_event_detail"]["event_text"] == long_text

    async def test_first_fetch_on_freshly_booted_host(self, hass, mock_config_entry):
        """time.monotonic() is host uptime on Linux — on a freshly booted
        host (HAOS reboot, CI runner) it is smaller than the 5-minute
        throttle interval, and a 0.0 "never fetched" default would classify
        the FIRST-EVER fetch as inside the window and silently skip it
        (regression: exactly how the Gold coverage CI job failed while the
        same tests passed on a long-uptime dev machine)."""
        mock_config_entry.add_to_hass(hass)
        coordinator = _coordinator_with_events(hass, mock_config_entry, [FAULT_ROW])
        target: dict[str, Any] = {"sensors": {}}

        with patch(
            "custom_components.eg4_web_monitor.coordinator_mixins.time"
        ) as mock_time:
            mock_time.monotonic.return_value = 10.0  # 10s of uptime
            await coordinator._fetch_last_event(INVERTER_SERIAL, target)

        coordinator.client.analytics.get_event_list.assert_awaited_once_with(
            INVERTER_SERIAL, rows=1
        )
        assert target["sensors"]["last_event"] == "Bus voltage high"
        assert coordinator._last_status_fetch[f"events_{INVERTER_SERIAL}"] == 10.0


# ── Sensor entity ────────────────────────────────────────────────────


def _mock_sensor_coordinator(devices: dict[str, dict[str, Any]]) -> MagicMock:
    """Minimal mock coordinator for sensor entity construction."""
    coordinator = MagicMock()
    coordinator.plant_id = "12345"
    coordinator.last_update_success = True
    coordinator.get_device_info = MagicMock(return_value=None)
    coordinator.has_http_api = MagicMock(return_value=False)
    coordinator.has_configured_local_transport = MagicMock(return_value=False)
    coordinator.data = {"devices": devices}
    return coordinator


class TestLastEventSensorEntity:
    """EG4LastEventSensor creation gating, state and attributes."""

    def test_created_for_inverter_when_key_published(self):
        """CLOUD/HYBRID: the coordinator publishes last_event -> the dedicated
        sensor class is created."""
        device = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"last_event": "Bus voltage high"},
            "batteries": {},
        }
        coordinator = _mock_sensor_coordinator({INVERTER_SERIAL: device})
        entities, _ = _create_inverter_sensors(coordinator, INVERTER_SERIAL, device)
        last_event = [e for e in entities if isinstance(e, EG4LastEventSensor)]
        assert len(last_event) == 1
        assert last_event[0].unique_id == f"{INVERTER_SERIAL}_last_event"

    def test_not_created_without_key(self):
        """Pure LOCAL: the coordinator never publishes the key -> no entity."""
        device = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"status_code": 0},
            "batteries": {},
        }
        coordinator = _mock_sensor_coordinator({INVERTER_SERIAL: device})
        entities, _ = _create_inverter_sensors(coordinator, INVERTER_SERIAL, device)
        assert not [e for e in entities if isinstance(e, EG4LastEventSensor)]

    def test_created_for_gridboss(self):
        """GridBOSS devices get the sensor too (live-validated events)."""
        device = {
            "type": "gridboss",
            "model": "GridBOSS",
            "sensors": {"last_event": "Grid frequency abnormality"},
        }
        coordinator = _mock_sensor_coordinator({GRIDBOSS_SERIAL: device})
        entities = _create_simple_device_sensors(
            coordinator, GRIDBOSS_SERIAL, device, "gridboss"
        )
        last_event = [e for e in entities if isinstance(e, EG4LastEventSensor)]
        assert len(last_event) == 1

    def test_state_and_attributes(self):
        """State mirrors the sensors value; attributes mirror the detail —
        including record_id, the automation dedupe key (two distinct events
        with identical text produce no state change)."""
        detail = {
            "record_id": 7583193,
            "event_code": "E019",
            "event_text": "Bus voltage high",
            "event_type": "FAULT",
            "start_time": "2026-07-01 16:50:28",
            "end_time": "2026-07-01 18:04:31",
            "status": "RESOLVED",
        }
        device = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"last_event": "Bus voltage high"},
            "last_event_detail": detail,
            "batteries": {},
        }
        coordinator = _mock_sensor_coordinator({INVERTER_SERIAL: device})
        sensor = EG4LastEventSensor(
            coordinator=coordinator,
            serial=INVERTER_SERIAL,
            sensor_key="last_event",
            device_type="inverter",
        )
        assert sensor.native_value == "Bus voltage high"
        assert sensor.extra_state_attributes == {
            "record_id": 7583193,
            "event_code": "E019",
            "event_type": "FAULT",
            "start_time": "2026-07-01 16:50:28",
            "end_time": "2026-07-01 18:04:31",
            "status": "RESOLVED",
        }

    def test_unknown_state_and_no_attributes_without_events(self):
        """No events: state None (unknown) and no attributes."""
        device = {
            "type": "inverter",
            "model": "FlexBOSS21",
            "sensors": {"last_event": None},
            "last_event_detail": None,
            "batteries": {},
        }
        coordinator = _mock_sensor_coordinator({INVERTER_SERIAL: device})
        sensor = EG4LastEventSensor(
            coordinator=coordinator,
            serial=INVERTER_SERIAL,
            sensor_key="last_event",
            device_type="inverter",
        )
        assert sensor.native_value is None
        assert sensor.extra_state_attributes is None


# ── fetch_events service ─────────────────────────────────────────────


def _service_call(data: dict[str, Any]) -> Any:
    """Minimal ServiceCall stand-in for direct handler tests."""
    payload = {"count": 30}
    payload.update(data)
    return SimpleNamespace(data=payload, return_response=True)


def _cloud_entry_with_devices(
    hass,
    devices: dict[str, dict[str, Any]],
    rows_by_serial: dict[str, list] | None = None,
) -> MockConfigEntry:
    """LOADED cloud entry whose coordinator serves mocked event lists."""
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP}
    coordinator.data = {"devices": devices}
    client = MagicMock()

    async def fake_get_event_list(serial: str, rows: int = 30) -> dict:
        return _event_response((rows_by_serial or {}).get(serial, [])[:rows])

    client.analytics.get_event_list = AsyncMock(side_effect=fake_get_event_list)
    coordinator.client = client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP},
        entry_id="cloud_entry",
    )
    entry.runtime_data = coordinator
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


class TestFetchEventsService:
    """eg4_web_monitor.fetch_events service."""

    async def test_setup_registers_service(self, hass: HomeAssistant):
        """async_setup registers fetch_events."""
        assert await async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, SERVICE_FETCH_EVENTS)

    async def test_full_service_call_returns_events(self, hass: HomeAssistant):
        """End-to-end call returns normalized events for every inverter and
        GridBOSS; parallel groups are excluded."""
        await async_setup(hass, {})
        _cloud_entry_with_devices(
            hass,
            devices={
                INVERTER_SERIAL: {"type": "inverter"},
                GRIDBOSS_SERIAL: {"type": "gridboss"},
                "parallel_group_group a": {"type": "parallel_group"},
            },
            rows_by_serial={
                INVERTER_SERIAL: [FAULT_ROW],
                GRIDBOSS_SERIAL: [MIDBOX_ROW],
            },
        )

        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_FETCH_EVENTS,
            {"config_entry": "cloud_entry"},
            blocking=True,
            return_response=True,
        )

        devices = response["devices"]
        assert set(devices) == {INVERTER_SERIAL, GRIDBOSS_SERIAL}
        inverter_events = devices[INVERTER_SERIAL]["events"]
        assert inverter_events[0]["record_id"] == 7583193
        assert inverter_events[0]["event_code"] == "E019"
        assert inverter_events[0]["status"] == "RESOLVED"
        gridboss_events = devices[GRIDBOSS_SERIAL]["events"]
        assert gridboss_events[0]["event_type"] == "MIDBOX_WARNING"
        assert gridboss_events[0]["status"] == "ACTIVE"

    async def test_serial_filter(self, hass: HomeAssistant):
        """An explicit serial fetches only that device."""
        entry = _cloud_entry_with_devices(
            hass,
            devices={
                INVERTER_SERIAL: {"type": "inverter"},
                GRIDBOSS_SERIAL: {"type": "gridboss"},
            },
            rows_by_serial={GRIDBOSS_SERIAL: [MIDBOX_ROW]},
        )

        response = await async_fetch_events(
            hass,
            _service_call({"config_entry": "cloud_entry", "serial": GRIDBOSS_SERIAL}),
        )

        assert set(response["devices"]) == {GRIDBOSS_SERIAL}
        client = entry.runtime_data.client
        client.analytics.get_event_list.assert_awaited_once_with(
            GRIDBOSS_SERIAL, rows=30
        )

    async def test_unknown_serial_raises(self, hass: HomeAssistant):
        """A serial not in the plant raises ServiceValidationError."""
        _cloud_entry_with_devices(hass, devices={INVERTER_SERIAL: {"type": "inverter"}})

        with pytest.raises(ServiceValidationError, match="not found"):
            await async_fetch_events(
                hass,
                _service_call({"config_entry": "cloud_entry", "serial": "0000000000"}),
            )

    async def test_local_only_entry_raises(self, hass: HomeAssistant):
        """Pure LOCAL entries (no cloud client) are rejected."""
        coordinator = MagicMock()
        coordinator.entry = MagicMock()
        coordinator.entry.data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
        coordinator.client = None
        coordinator.data = {"devices": {INVERTER_SERIAL: {"type": "inverter"}}}
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
            entry_id="local_entry",
        )
        entry.runtime_data = coordinator
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)

        with pytest.raises(ServiceValidationError, match="cloud credentials"):
            await async_fetch_events(
                hass, _service_call({"config_entry": "local_entry"})
            )

    async def test_empty_event_list(self, hass: HomeAssistant):
        """A device with no events yields an empty list, not an error."""
        _cloud_entry_with_devices(
            hass, devices={INVERTER_SERIAL: {"type": "inverter"}}, rows_by_serial={}
        )

        response = await async_fetch_events(
            hass, _service_call({"config_entry": "cloud_entry"})
        )

        assert response["devices"][INVERTER_SERIAL] == {"total": 0, "events": []}

    async def test_malformed_row_among_good_rows_is_skipped(self, hass: HomeAssistant):
        """Codex P2: one bad row among good ones must not abort the whole
        service response — malformed rows are skipped, good rows returned."""
        _cloud_entry_with_devices(
            hass,
            devices={INVERTER_SERIAL: {"type": "inverter"}},
            rows_by_serial={INVERTER_SERIAL: [FAULT_ROW, "not-a-dict-row", MIDBOX_ROW]},
        )

        response = await async_fetch_events(
            hass, _service_call({"config_entry": "cloud_entry"})
        )

        events = response["devices"][INVERTER_SERIAL]["events"]
        assert [e["event_code"] for e in events] == ["E019", "W018"]
        # total reflects what the portal reported, not the skipped count.
        assert response["devices"][INVERTER_SERIAL]["total"] == 3

    async def test_missing_endpoint_raises(self, hass: HomeAssistant):
        """A pylxpweb without the event-list API raises ServiceValidationError."""
        entry = _cloud_entry_with_devices(
            hass, devices={INVERTER_SERIAL: {"type": "inverter"}}
        )
        entry.runtime_data.client.analytics = MagicMock(spec=[])

        with pytest.raises(ServiceValidationError, match="event log"):
            await async_fetch_events(
                hass, _service_call({"config_entry": "cloud_entry"})
            )

    async def test_unknown_entry_raises(self, hass: HomeAssistant):
        """An unknown config entry id raises ServiceValidationError."""
        with pytest.raises(ServiceValidationError, match="not found"):
            await async_fetch_events(hass, _service_call({"config_entry": "missing"}))
