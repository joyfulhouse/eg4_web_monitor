"""Released pylxpweb recognition must reach HA control platform discovery.

These are software acceptance checks for #612 and the recognition part of #659.
Only raw identification inputs are supplied; family detection, feature mapping,
and platform discovery run their real code. No control is invoked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pylxpweb.devices import HybridInverter
from pylxpweb.transports.discovery import discover_device_info

from custom_components.eg4_web_monitor.coordinator_mixins import DeviceProcessingMixin
from tests.test_control_discovery import SERIAL, _coordinator_for, _setup_for


class _IdentificationTransport:
    """Read-only register boundary for the released local discovery function."""

    serial = SERIAL

    def __init__(self, raw_code: int) -> None:
        self.raw_code = raw_code

    async def read_parameters(self, start: int, count: int) -> dict[int, int]:
        if (start, count) == (19, 1):
            return {19: self.raw_code}
        assert (start, count) == (107, 2)
        return {107: 0, 108: 0}


@pytest.mark.parametrize("platform", ("number", "switch", "select"))
@pytest.mark.parametrize(
    ("raw_code", "model", "family"),
    [(20, "GEN-LB-EU 3.6K", "LXP"), (2102, "12000XP", "EG4_OFFGRID")],
)
@pytest.mark.parametrize("late", [False, True], ids=["initial", "late"])
async def test_released_recognition_reaches_control_discovery(
    hass, platform, raw_code, model, family, late
):
    """Real released detection creates controls, retaining off-grid exclusions."""
    discovery = await discover_device_info(_IdentificationTransport(raw_code))
    assert discovery.device_type_code == raw_code
    assert discovery.model_family == family
    assert discovery.is_inverter
    assert not discovery.is_gridboss

    # Match the reports: code 20 is Cloud EU; code 2102 has a local link
    # alongside cloud. The local boundary deliberately has no write methods.
    hybrid = raw_code == 2102
    inverter = HybridInverter(
        SimpleNamespace(),
        SERIAL,
        model,
        transport=_IdentificationTransport(raw_code) if hybrid else None,
    )
    # Model the cached cloud parameter response, including string-valued codes.
    # No detected family or feature object is supplied by the test.
    inverter.parameters = {"HOLD_DEVICE_TYPE_CODE": str(raw_code)}
    detected = await inverter.detect_features()
    assert detected.model_family.value == family
    assert detected.device_type_code == raw_code
    features = DeviceProcessingMixin._extract_inverter_features(inverter)
    assert features["inverter_family"] == discovery.model_family
    assert features["device_type_code"] == raw_code
    assert features.get("family_source") != "model_fallback"

    coordinator = _coordinator_for(platform)
    coordinator.get_inverter_object.return_value = inverter
    coordinator.has_local_transport.return_value = hybrid
    coordinator.has_configured_local_transport.return_value = hybrid
    coordinator.has_local_register_path.return_value = hybrid
    device = {"type": "inverter", "model": model, "features": features}
    coordinator.data["devices"] = {} if late else {SERIAL: device}
    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    setup, _ = _setup_for(platform)
    entities = []
    await setup(hass, entry, lambda batch, **kwargs: entities.extend(batch))
    if late:
        assert not entities
        coordinator.data["devices"][SERIAL] = device
        callbacks[0]()

    keys = {entity.unique_id.removeprefix(f"{SERIAL}_") for entity in entities}
    assert len(keys) == len(entities)
    common = {
        "number": {
            "ac_charge_power",
            "pv_charge_power",
            "battery_charge_current",
            "battery_discharge_current",
            "quick_charge_duration",
        },
        "switch": {"quick_charge", "battery_backup", "off_grid_mode", "share_battery"},
        "select": {
            "operating_mode",
            "pv_input_mode",
            "battery_charge_control",
            "battery_discharge_control",
        },
    }[platform]
    assert common <= keys
    grid_tied = {
        "number": {
            "grid_peak_shaving_power",
            "forced_discharge_power",
            "forced_discharge_soc_limit",
            "ac_charge_soc_limit",
            "grid_sell_back_power",
            "start_discharge_power_threshold",
        },
        "switch": {
            "ac_charge",
            "battery_backup_ctrl",
            "forced_dischg_en",
            "grid_peak_shaving",
            "feed_in_grid_en",
            "pv_sell_to_grid_en",
            "fast_zero_export",
        },
        "select": set(),
    }[platform]
    if family == "EG4_OFFGRID":
        assert keys.isdisjoint(grid_tied)
        if platform == "number":
            assert {"ac_charge_start_battery_soc", "ac_charge_end_battery_soc"} <= keys
    else:
        assert grid_tied <= keys
        if platform == "number":
            # LXP recognition must not enable the hybrid-only start SOC gate.
            assert "ac_charge_start_battery_soc" not in keys

    # Repeat coordinator updates must not register duplicate controls.
    callbacks[0]()
    assert len(entities) == len(keys)


@pytest.mark.parametrize("platform", ("number", "switch", "select"))
async def test_unobserved_high_byte_variant_does_not_gain_controls(hass, platform):
    """Recognizing exact code 20 must not classify arbitrary packed variants."""
    raw_code = 0x0114
    discovery = await discover_device_info(_IdentificationTransport(raw_code))
    inverter = HybridInverter(SimpleNamespace(), SERIAL, "GEN-LB-EU 3.6K")
    inverter.parameters = {"HOLD_DEVICE_TYPE_CODE": raw_code}
    detected = await inverter.detect_features()
    features = DeviceProcessingMixin._extract_inverter_features(inverter)
    assert discovery.device_type_code == detected.device_type_code == raw_code
    assert discovery.model_family == detected.model_family.value == "UNKNOWN"
    assert features["inverter_family"] == "UNKNOWN"

    coordinator = _coordinator_for(platform)
    coordinator.data["devices"][SERIAL] = {
        "type": "inverter",
        "model": inverter.model,
        "features": features,
    }
    entry = MagicMock()
    entry.runtime_data = coordinator
    setup, _ = _setup_for(platform)
    entities = []
    await setup(hass, entry, lambda batch, **kwargs: entities.extend(batch))
    assert not entities
