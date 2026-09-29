"""Tests for GridBOSS smart port option registers (const/midbox.py).

Covers the register codec, the coordinator's option read path (cadence,
retry, carry-forward) and the masked read-modify-write writer.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HYBRID,
    DOMAIN,
)
from custom_components.eg4_web_monitor.const.midbox import (
    MIDBOX_OPTION_FIELDS,
    MIDBOX_OPTION_READ_BLOCKS,
    decode_midbox_options,
    encode_midbox_field,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor.coordinator_http import HTTPUpdateMixin

GRIDBOSS_SERIAL = "9876543210"

# Live read of GridBOSS 5044850330 (fw IAAB-1300), 2026-09-29 (dump 10):
# ports 1-3 Smart Load, enabled, grid-on, based on SOC/Volt; shedding on
# ports 1-2. Registers not listed read 0.
LIVE_REGISTERS: dict[int, int] = {
    229: 0x3077,
    230: 0x4650,
    231: 0x555A,
    232: 0x325A,
    233: 0x3C5A,
    **{reg: 0x21C if reg % 2 == 0 else 0x1E0 for reg in range(234, 242)},
    242: 0x5A32,
    243: 0x5A32,
    244: 0x5A32,
    245: 0x540A,
    **{reg: 0x1F4 if reg % 2 == 0 else 0x21C for reg in range(246, 254)},
    254: 0,
    255: 0,
    256: 3,
    257: 0,
    258: 0x2850,
    259: 0x555A,
    260: 0x3C5A,
    261: 0x3C5A,
    **{reg: 0x21C if reg % 2 == 0 else 0x1E0 for reg in range(262, 270)},
    **{reg: 0 for reg in range(270, 318)},
    312: 0,
    313: 0x0201,
    2101: 0x3E,
}


# ── Codec ────────────────────────────────────────────────────────────


def test_every_field_is_covered_by_a_read_block():
    """The read blocks cover every field's register."""
    covered = {
        reg
        for start, count in MIDBOX_OPTION_READ_BLOCKS
        for reg in range(start, start + count)
    }
    assert {field.register for field in MIDBOX_OPTION_FIELDS.values()} <= covered
    assert all(count <= 40 for _, count in MIDBOX_OPTION_READ_BLOCKS)


def test_field_count():
    """Per port: 4 enables, based-on, 3 SOC pairs, 3 volt pairs, PV, 2x6 windows."""
    per_port = 4 + 1 + 6 + 6 + 1 + 2 * 6 * 2
    assert len(MIDBOX_OPTION_FIELDS) == 4 * per_port


def test_decode_live_read_matches_portal():
    """The live read decodes to the settings the portal showed."""
    values = decode_midbox_options(LIVE_REGISTERS)
    assert len(values) == len(MIDBOX_OPTION_FIELDS)
    # Port 1 (Garage): enabled, grid-on, shedding, SOC/Volt, 80/70, PS 80/40.
    assert values["FUNC_SMART_LOAD_EN_1"] is True
    assert values["FUNC_SMART_LOAD_GRID_ON_1"] is True
    assert values["FUNC_SHEDDING_MODE_EN_1"] is True
    assert values["FUNC_AC_COUPLE_EN_1"] is False
    assert values["BIT_SMART_LOAD_BASE_ON_1"] == 1
    assert values["MIDBOX_HOLD_SL_START_SOC_1"] == 80
    assert values["MIDBOX_HOLD_SL_END_SOC_1"] == 70
    assert values["MIDBOX_HOLD_SL_PS_START_SOC_1"] == 80
    assert values["MIDBOX_HOLD_SL_PS_END_SOC_1"] == 40
    assert values["MIDBOX_HOLD_SL_START_PV_P_1"] == 0.0
    # Port 3 (Cooktop): shedding off, 90/50, PV 0.3 kW.
    assert values["FUNC_SHEDDING_MODE_EN_3"] is False
    assert values["MIDBOX_HOLD_SL_START_SOC_3"] == 90
    assert values["MIDBOX_HOLD_SL_END_SOC_3"] == 50
    assert values["MIDBOX_HOLD_SL_START_PV_P_3"] == 0.3
    # Port 4: AC start SOC 10 in the low byte, end 84 in the high byte.
    assert values["MIDBOX_HOLD_AC_START_SOC_4"] == 10
    assert values["MIDBOX_HOLD_AC_END_SOC_4"] == 84
    assert values["BIT_SMART_LOAD_BASE_ON_4"] == 1
    # Voltages ÷10.
    assert values["MIDBOX_HOLD_SL_START_VOLT_2"] == 54.0
    assert values["MIDBOX_HOLD_SL_END_VOLT_2"] == 48.0
    assert values["MIDBOX_HOLD_AC_START_VOLT_4"] == 50.0
    # Window word: low byte hour, high byte minute (313 = 01:02).
    assert values["HOLD_MIDBOX_AC_COUPLE_4_END_HOUR_1"] == 1
    assert values["HOLD_MIDBOX_AC_COUPLE_4_END_MINUTE_1"] == 2


def test_decode_pinned_register_changes():
    """Register positions pinned by controlled portal/app changes."""
    # AC start SOC p4 8 -> 10 moved only the low byte of 245.
    assert decode_midbox_options({245: 0x5408})["MIDBOX_HOLD_AC_START_SOC_4"] == 8
    # AC window 2 p4 = 02:01-02:02 at 314/315.
    values = decode_midbox_options({314: 0x0102, 315: 0x0202})
    assert values["HOLD_MIDBOX_AC_COUPLE_4_START_HOUR_2"] == 2
    assert values["HOLD_MIDBOX_AC_COUPLE_4_START_MINUTE_2"] == 1
    assert values["HOLD_MIDBOX_AC_COUPLE_4_END_MINUTE_2"] == 2
    # Shedding p2 enable = bit 13 only; based-on p2 = bit 2 only.
    assert decode_midbox_options({229: 1 << 13})["FUNC_SHEDDING_MODE_EN_2"] is True
    based_on = decode_midbox_options({2101: 1 << 2})
    assert [based_on[f"BIT_SMART_LOAD_BASE_ON_{p}"] for p in (1, 2, 3, 4)] == [
        0,
        1,
        0,
        0,
    ]


@pytest.mark.parametrize(
    ("name", "raw", "value", "expected"),
    [
        ("FUNC_SMART_LOAD_EN_2", 0x3075, True, 0x3077),
        ("FUNC_SHEDDING_MODE_EN_2", 0x7875, False, 0x5875),
        # Based-on keeps the unexposed Time+SOC/Volt bits (4, 5) intact.
        ("BIT_SMART_LOAD_BASE_ON_3", 0x32, 1, 0x3A),
        ("BIT_SMART_LOAD_BASE_ON_3", 0x3A, 0, 0x32),
        ("MIDBOX_HOLD_AC_START_SOC_4", 0x5408, 10, 0x540A),
        ("MIDBOX_HOLD_SL_END_SOC_3", 0x465A, 33, 0x215A),
        ("MIDBOX_HOLD_SL_START_VOLT_1", 540, 52.5, 525),
        ("MIDBOX_HOLD_SL_START_PV_P_1", 0, 0.4, 4),
        ("HOLD_MIDBOX_SL_3_START_MINUTE_1", 0x0004, 5, 0x0504),
    ],
)
def test_encode_masks_one_field(name: str, raw: int, value: Any, expected: int):
    """Encoding changes only the named field's bits."""
    assert encode_midbox_field(MIDBOX_OPTION_FIELDS[name], raw, value) == expected


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MIDBOX_HOLD_SL_START_SOC_1", 256),
        ("MIDBOX_HOLD_SL_START_SOC_1", -1),
        ("MIDBOX_HOLD_SL_START_SOC_1", 50.5),
        ("BIT_SMART_LOAD_BASE_ON_1", 2),
        ("MIDBOX_HOLD_SL_START_VOLT_1", -0.1),
    ],
)
def test_encode_rejects_out_of_range(name: str, value: Any):
    """Values that do not fit the field raise instead of wrapping."""
    with pytest.raises(ValueError):
        encode_midbox_field(MIDBOX_OPTION_FIELDS[name], 0, value)


# ── Coordinator fixtures ─────────────────────────────────────────────


class FakeTransport:
    """Register-backed transport double serving block reads and writes."""

    def __init__(self, registers: dict[int, int]) -> None:
        self.registers = dict(registers)
        self.is_connected = True
        self.reads: list[tuple[int, int]] = []
        self.writes: list[dict[int, int]] = []
        self.fail_reads: list[Exception | None] = []
        self.revert_writes = False

    async def connect(self) -> None:
        self.is_connected = True

    async def read_parameters(self, start: int, count: int) -> dict[int, int]:
        self.reads.append((start, count))
        if self.fail_reads:
            failure = self.fail_reads.pop(0)
            if failure is not None:
                raise failure
        return {reg: self.registers.get(reg, 0) for reg in range(start, start + count)}

    async def write_parameters(self, values: dict[int, int]) -> None:
        self.writes.append(dict(values))
        if not self.revert_writes:
            self.registers.update(values)


@pytest.fixture
def hybrid_config_entry():
    """HYBRID config entry with a GridBOSS dongle transport."""
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
                    "serial": GRIDBOSS_SERIAL,
                    "host": "192.168.1.100",
                    "port": 8000,
                    "transport_type": "wifi_dongle",
                    "is_gridboss": True,
                },
            ],
        },
        options={},
        entry_id="hybrid_test",
    )


@pytest.fixture
async def coordinator(hass, hybrid_config_entry):
    """Real coordinator with one GridBOSS row and no retry delay."""
    hybrid_config_entry.add_to_hass(hass)
    coord = EG4DataUpdateCoordinator(hass, hybrid_config_entry)
    coord.async_update_listeners = MagicMock()
    coord.data = {
        "devices": {GRIDBOSS_SERIAL: {"type": "gridboss"}},
        "parameters": {GRIDBOSS_SERIAL: {}},
    }
    with patch(
        "custom_components.eg4_web_monitor.coordinator_local._MIDBOX_READ_RETRY_DELAY",
        0,
    ):
        yield coord


def _attach(coord: EG4DataUpdateCoordinator, transport: FakeTransport) -> None:
    coord.get_local_transport = MagicMock(return_value=transport)  # type: ignore[method-assign]


# ── Read path ────────────────────────────────────────────────────────


async def test_first_read_is_full_then_functions_only(coordinator):
    """First read covers every block; within the interval only 229 is read."""
    transport = FakeTransport(LIVE_REGISTERS)
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL
    )
    assert transport.reads == list(MIDBOX_OPTION_READ_BLOCKS)
    assert params == decode_midbox_options(LIVE_REGISTERS)

    coordinator.data["parameters"][GRIDBOSS_SERIAL] = params
    transport.reads.clear()
    transport.registers[229] = 0x3074  # SL_EN_1 / SL_EN_2 turned off
    transport.registers[230] = 0x0000  # not re-read this cycle
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL
    )
    assert transport.reads == [(229, 1)]
    assert params["FUNC_SMART_LOAD_EN_1"] is False
    assert params["MIDBOX_HOLD_SL_START_SOC_1"] == 80  # carried forward

    transport.reads.clear()
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL, poll_functions=False
    )
    assert transport.reads == []


async def test_full_read_due_after_parameter_interval(coordinator):
    """The full read repeats once the parameter refresh interval passes."""
    transport = FakeTransport(LIVE_REGISTERS)
    coordinator._parameter_refresh_interval = timedelta(minutes=60)
    with patch(
        "custom_components.eg4_web_monitor.coordinator_local.time.monotonic",
        return_value=1000.0,
    ):
        await coordinator._read_midbox_smart_port_options(transport, GRIDBOSS_SERIAL)
    assert coordinator._midbox_option_next_read[GRIDBOSS_SERIAL] == 1000.0 + 3600
    transport.reads.clear()
    with patch(
        "custom_components.eg4_web_monitor.coordinator_local.time.monotonic",
        return_value=1000.0 + 3600,
    ):
        await coordinator._read_midbox_smart_port_options(transport, GRIDBOSS_SERIAL)
    assert transport.reads == list(MIDBOX_OPTION_READ_BLOCKS)


async def test_first_read_on_fresh_host_is_not_throttled(coordinator):
    """monotonic() near 0 (freshly booted host) still reads everything."""
    transport = FakeTransport(LIVE_REGISTERS)
    with patch(
        "custom_components.eg4_web_monitor.coordinator_local.time.monotonic",
        return_value=0.5,
    ):
        await coordinator._read_midbox_smart_port_options(transport, GRIDBOSS_SERIAL)
    assert transport.reads == list(MIDBOX_OPTION_READ_BLOCKS)


async def test_misrouted_block_is_retried(coordinator):
    """One failed block read is retried immediately and succeeds."""
    transport = FakeTransport(LIVE_REGISTERS)
    transport.fail_reads = [None, None, RuntimeError("misrouted cloud response")]
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL
    )
    assert transport.reads.count((309, 9)) == 2
    assert params == decode_midbox_options(LIVE_REGISTERS)


async def test_failed_block_carries_forward_and_retries_soon(coordinator):
    """A block failing twice keeps its previous values; full read due soon."""
    previous = decode_midbox_options(LIVE_REGISTERS)
    coordinator.data["parameters"][GRIDBOSS_SERIAL] = previous
    changed = dict(LIVE_REGISTERS)
    changed[229] = 0
    changed[270] = 0x0506
    transport = FakeTransport(changed)
    boom = TimeoutError("dead socket")
    transport.fail_reads = [None, boom, boom]  # block 269+40 fails twice
    with patch(
        "custom_components.eg4_web_monitor.coordinator_local.time.monotonic",
        return_value=1000.0,
    ):
        params = await coordinator._read_midbox_smart_port_options(
            transport, GRIDBOSS_SERIAL
        )
    assert params["FUNC_SMART_LOAD_EN_1"] is False  # block 1 fresh
    assert params["HOLD_MIDBOX_SL_1_START_HOUR_1"] == 0  # block 2 carried
    assert params is not previous
    assert coordinator._midbox_option_next_read[GRIDBOSS_SERIAL] == 1120.0


async def test_total_failure_with_no_history_is_empty(coordinator):
    """No previous values and a dead link: empty store, never an exception."""
    coordinator.data = {}
    transport = FakeTransport({})
    transport.is_connected = False
    transport.connect = AsyncMock(side_effect=OSError("unreachable"))
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL
    )
    assert params == {}


async def test_http_pass_reads_only_live_transport_mids():
    """The HYBRID pass reads attached-and-up MIDs and skips the rest."""
    live_mid = MagicMock()
    live_mid.serial_number = GRIDBOSS_SERIAL
    live_mid.transport = MagicMock()
    live_mid.transport_link_down = False

    cloud_mid = MagicMock()
    cloud_mid.serial_number = "1111111111"
    cloud_mid.transport = None

    down_mid = MagicMock()
    down_mid.serial_number = "2222222222"
    down_mid.transport = MagicMock()
    down_mid.transport_link_down = True

    mock_self = MagicMock()
    mock_self.station.all_mid_devices = [live_mid, cloud_mid, down_mid]
    decoded = decode_midbox_options(LIVE_REGISTERS)
    mock_self._read_midbox_smart_port_options = AsyncMock(return_value=decoded)

    processed: dict = {
        "devices": {
            GRIDBOSS_SERIAL: {"type": "gridboss"},
            "1111111111": {"type": "gridboss"},
            "2222222222": {"type": "gridboss"},
        },
        "parameters": {},
    }
    await HTTPUpdateMixin._update_midbox_smart_port_options(mock_self, processed)
    mock_self._read_midbox_smart_port_options.assert_awaited_once_with(
        live_mid.transport, GRIDBOSS_SERIAL
    )
    assert processed["parameters"] == {GRIDBOSS_SERIAL: decoded}


# ── Writer ───────────────────────────────────────────────────────────


async def test_write_masks_field_and_seeds_cache(coordinator):
    """A byte write changes only its byte and seeds the verify decode."""
    transport = FakeTransport(LIVE_REGISTERS)
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL, {"MIDBOX_HOLD_SL_END_SOC_3": 60}
    )
    assert transport.writes == [{232: 0x3C5A}]
    params = coordinator.data["parameters"][GRIDBOSS_SERIAL]
    assert params["MIDBOX_HOLD_SL_END_SOC_3"] == 60
    assert params["MIDBOX_HOLD_SL_START_SOC_3"] == 90
    assert coordinator.has_active_parameter_write_seed(
        GRIDBOSS_SERIAL, "MIDBOX_HOLD_SL_END_SOC_3"
    )


async def test_write_preserves_unexposed_based_on_bits(coordinator):
    """Based-on writes keep bits 4-8 (mobile-only Time+SOC/Volt) intact."""
    transport = FakeTransport({2101: 0x30})
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL, {"BIT_SMART_LOAD_BASE_ON_1": 1}
    )
    assert transport.writes == [{2101: 0x32}]


async def test_write_time_window_hour_and_minute_together(coordinator):
    """Hour and minute of one window edge go out in a single write."""
    transport = FakeTransport(LIVE_REGISTERS)
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL,
        {"HOLD_MIDBOX_SL_3_START_HOUR_1": 4, "HOLD_MIDBOX_SL_3_START_MINUTE_1": 5},
    )
    assert transport.writes == [{282: 0x0504}]


async def test_write_uses_fresh_register_not_cache(coordinator):
    """A sibling bit changed in the portal since the last poll survives."""
    coordinator.data["parameters"][GRIDBOSS_SERIAL] = decode_midbox_options(
        {229: 0x3074}
    )
    transport = FakeTransport({229: 0x3076})  # SL_EN_2 turned on in the portal
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL, {"FUNC_SMART_LOAD_EN_1": True}
    )
    assert transport.writes == [{229: 0x3077}]


async def test_noop_write_skips_register_write(coordinator):
    """Writing the current value only verifies."""
    transport = FakeTransport(LIVE_REGISTERS)
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL, {"FUNC_SMART_LOAD_EN_1": True}
    )
    assert transport.writes == []


async def test_silent_revert_raises_after_seeding_truth(coordinator):
    """A write the firmware does not keep raises; the cache shows the truth."""
    transport = FakeTransport({229: 0x3074})
    transport.revert_writes = True
    _attach(coordinator, transport)
    with pytest.raises(HomeAssistantError, match="rejected"):
        await coordinator.write_midbox_options(
            GRIDBOSS_SERIAL, {"FUNC_SMART_LOAD_EN_4": True}
        )
    params = coordinator.data["parameters"][GRIDBOSS_SERIAL]
    assert params["FUNC_SMART_LOAD_EN_4"] is False


async def test_write_errors(coordinator):
    """No transport, bad value, read failure and cross-register calls fail."""
    coordinator.get_local_transport = MagicMock(return_value=None)  # type: ignore[method-assign]
    with pytest.raises(HomeAssistantError, match="No local transport"):
        await coordinator.write_midbox_options(
            GRIDBOSS_SERIAL, {"FUNC_SMART_LOAD_EN_1": True}
        )

    transport = FakeTransport(LIVE_REGISTERS)
    _attach(coordinator, transport)
    with pytest.raises(HomeAssistantError, match="Invalid value"):
        await coordinator.write_midbox_options(
            GRIDBOSS_SERIAL, {"MIDBOX_HOLD_SL_START_SOC_1": 300}
        )
    assert transport.writes == []

    boom = TimeoutError("dead socket")
    transport.fail_reads = [boom, boom]
    with pytest.raises(HomeAssistantError, match="Failed to write"):
        await coordinator.write_midbox_options(
            GRIDBOSS_SERIAL, {"FUNC_SMART_LOAD_EN_1": False}
        )

    with pytest.raises(ValueError):
        await coordinator.write_midbox_options(
            GRIDBOSS_SERIAL,
            {"FUNC_SMART_LOAD_EN_1": True, "MIDBOX_HOLD_SL_START_SOC_1": 90},
        )


async def test_later_read_confirms_write_seed(coordinator):
    """A full read agreeing with the write keeps the written value."""
    transport = FakeTransport(LIVE_REGISTERS)
    _attach(coordinator, transport)
    await coordinator.write_midbox_options(
        GRIDBOSS_SERIAL, {"MIDBOX_HOLD_SL_START_SOC_2": 95}
    )
    params = await coordinator._read_midbox_smart_port_options(
        transport, GRIDBOSS_SERIAL
    )
    assert params["MIDBOX_HOLD_SL_START_SOC_2"] == 95
