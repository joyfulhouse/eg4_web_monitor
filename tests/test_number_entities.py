"""Tests for EG4 number entities and shared read/write helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.eg4_web_monitor.const import (
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_CHG_POWER_PERCENT,
)
from custom_components.eg4_web_monitor.number import (
    async_setup_entry,
    ACChargePowerNumber,
    ACChargeSOCLimitNumber,
    BatteryChargeCurrentNumber,
    BatteryDischargeCurrentNumber,
    OnGridSOCCutoffNumber,
    PVChargePowerNumber,
    SystemChargeSOCLimitNumber,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_coordinator(
    *,
    serial: str = "1234567890",
    model: str = "FlexBOSS21",
    has_local: bool = False,
    has_http: bool = True,
    local_only: bool = False,
    parameters: dict | None = None,
    inverter_attrs: dict | None = None,
) -> MagicMock:
    """Build a mock coordinator for number entity tests."""
    coordinator = MagicMock()
    coordinator.has_local_transport = MagicMock(return_value=has_local)
    coordinator.has_http_api = MagicMock(return_value=has_http)
    coordinator.is_local_only = MagicMock(return_value=local_only)
    coordinator.last_update_success = True
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.refresh_all_device_parameters = AsyncMock()
    coordinator.write_named_parameter = AsyncMock()

    coordinator.data = {
        "devices": {serial: {"type": "inverter", "model": model}},
        "device_info": {serial: {"deviceTypeText4APP": model}},
        "parameters": {serial: parameters or {}},
    }
    coordinator.get_device_info = MagicMock(return_value=None)

    # Mock inverter object with configurable attributes
    mock_inverter = MagicMock()
    mock_inverter.refresh = AsyncMock()
    attrs = inverter_attrs or {}
    for attr_name, attr_value in attrs.items():
        setattr(mock_inverter, attr_name, attr_value)
    # Default cloud methods
    mock_inverter.set_ac_charge_power = AsyncMock(return_value=True)
    mock_inverter.set_pv_charge_power = AsyncMock(return_value=True)
    mock_inverter.set_ac_charge_soc_limit = AsyncMock(return_value=True)
    mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)
    mock_inverter.set_battery_charge_current = AsyncMock(return_value=True)
    mock_inverter.set_battery_discharge_current = AsyncMock(return_value=True)
    mock_inverter.set_grid_peak_shaving_power = AsyncMock(return_value=True)
    coordinator.get_inverter_object = MagicMock(return_value=mock_inverter)

    return coordinator


def _prep(entity: object) -> None:
    """Prepare entity for async action tests (set hass + entity_id)."""
    entity.hass = MagicMock()  # type: ignore[attr-defined]
    entity.entity_id = "number.test_entity"  # type: ignore[attr-defined]
    entity.platform = None  # type: ignore[attr-defined]
    entity.async_write_ha_state = MagicMock()  # type: ignore[attr-defined]


# ── Platform setup ───────────────────────────────────────────────────


class TestNumberPlatformSetup:
    """Test number platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_inverter(self, hass):
        """FlexBOSS inverter creates 13 number entities."""
        coordinator = _mock_coordinator()
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 13
        type_names = [type(e).__name__ for e in entities]
        assert "ACChargePowerNumber" in type_names
        assert "SystemChargeSOCLimitNumber" in type_names

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_gridboss(self, hass):
        """GridBOSS should not create number entities."""
        coordinator = _mock_coordinator()
        coordinator.data["devices"] = {
            "gb123": {"type": "gridboss", "model": "GridBOSS"}
        }
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) == 0

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_xp(self, hass):
        """XP device creates number entities."""
        coordinator = _mock_coordinator(model="12000XP")
        entry = MagicMock()
        entry.runtime_data = coordinator

        entities = []
        await async_setup_entry(hass, entry, lambda e, **kw: entities.extend(e))

        assert len(entities) > 0


# ── _read_param_value (via ACChargeSOCLimitNumber) ───────────────────


class TestReadParamValue:
    """Test the _read_param_value helper via concrete entities."""

    def test_optimistic_takes_precedence(self):
        """Optimistic value overrides all data sources."""
        coordinator = _mock_coordinator(parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 80})
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        entity._optimistic_value = 42.0
        assert entity.native_value == 42

    def test_local_only_reads_params(self):
        """Local-only mode reads from parameter data."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 75},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 75

    def test_inverter_first_then_params_fallback(self):
        """Default order: inverter -> params fallback."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_soc_limit": 60},
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 70},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 60

    def test_params_fallback_when_no_inverter(self):
        """Falls back to params when inverter value is None."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_soc_limit": None},
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 80},
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 80

    def test_none_when_no_data(self):
        """Returns None when no data is available."""
        coordinator = _mock_coordinator()
        coordinator.get_inverter_object = MagicMock(return_value=None)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value is None

    def test_out_of_range_returns_none(self):
        """Values outside min/max range return None."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={"HOLD_AC_CHARGE_SOC_LIMIT": 200},  # > 100
        )
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value is None


class TestReadParamValueFloat:
    """Test _read_param_value with as_float=True (via ACChargePowerNumber)."""

    def test_float_from_params_with_transform(self):
        """Param value in 100W units transformed to kW."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_AC_CHARGE_POWER: 50},  # 50 * 100W = 5.0 kW
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 5.0

    def test_float_from_inverter(self):
        """Inverter attribute value as float."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_power_limit": 3.5},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 3.5

    def test_float_precision(self):
        """Float value rounds to 1 decimal."""
        coordinator = _mock_coordinator(
            inverter_attrs={"ac_charge_power_limit": 3.456},
        )
        entity = ACChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 3.5


class TestReadParamValueDict:
    """Test _read_param_value with inverter_dict_attr (via OnGridSOCCutoffNumber)."""

    def test_reads_from_dict(self):
        """Reads from inverter dict attribute."""
        coordinator = _mock_coordinator(
            inverter_attrs={"battery_soc_limits": {"on_grid_limit": 20}},
        )
        entity = OnGridSOCCutoffNumber(coordinator, "1234567890")
        assert entity.native_value == 20

    def test_dict_missing_returns_none(self):
        """Missing dict key returns None, falls to params."""
        coordinator = _mock_coordinator(
            inverter_attrs={"battery_soc_limits": {}},
            parameters={"HOLD_DISCHG_CUT_OFF_SOC_EOD": 15},
        )
        entity = OnGridSOCCutoffNumber(coordinator, "1234567890")
        assert entity.native_value == 15


class TestReadParamValueParamsFirst:
    """Test _read_param_value with params_first=True (via SystemChargeSOCLimitNumber)."""

    def test_params_first_order(self):
        """With params_first, reads params before inverter."""
        coordinator = _mock_coordinator(
            parameters={"HOLD_SYSTEM_CHARGE_SOC_LIMIT": 90},
            inverter_attrs={"system_charge_soc_limit": 80},
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 90

    def test_params_first_falls_to_inverter(self):
        """params_first with no params falls back to inverter."""
        coordinator = _mock_coordinator(
            inverter_attrs={"system_charge_soc_limit": 80},
        )
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        assert entity.native_value == 80


# ── PVChargePowerNumber (custom native_value) ────────────────────────


class TestPVChargePowerNativeValue:
    """Test PVChargePower's custom native_value (strict 0 < inverter check)."""

    def test_from_params_pct_to_kw(self):
        """Parameter percentage converted to kW."""
        coordinator = _mock_coordinator(
            local_only=True,
            parameters={PARAM_HOLD_CHG_POWER_PERCENT: 100},  # 100% of 15kW = 15
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 15

    def test_from_inverter_rejects_zero(self):
        """Inverter value of 0 is rejected (means 'unset')."""
        coordinator = _mock_coordinator(
            inverter_attrs={"pv_charge_power_limit": 0},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        # 0 is rejected -> falls to params -> None
        assert entity.native_value is None

    def test_from_inverter_positive_value(self):
        """Positive inverter value returned as int."""
        coordinator = _mock_coordinator(
            inverter_attrs={"pv_charge_power_limit": 10},
        )
        entity = PVChargePowerNumber(coordinator, "1234567890")
        assert entity.native_value == 10


# ── _write_parameter (via ACChargeSOCLimitNumber) ────────────────────


class TestWriteParameter:
    """Test the _write_parameter helper via concrete entities."""

    @pytest.mark.asyncio
    async def test_write_local(self):
        """Local transport writes named parameter."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(75.0)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        assert call_args[0][1] == 75  # int(value)

    @pytest.mark.asyncio
    async def test_write_cloud(self):
        """Cloud mode calls inverter method."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(80.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_ac_charge_soc_limit.assert_called_once_with(soc_percent=80)

    @pytest.mark.asyncio
    async def test_write_validation_range(self):
        """Out of range values raise HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be between"):
            await entity.async_set_native_value(150.0)

    @pytest.mark.asyncio
    async def test_write_validation_integer(self):
        """Non-integer value for integer entity raises HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = ACChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="must be an integer"):
            await entity.async_set_native_value(50.5)


class TestACChargePowerWrite:
    """Test ACChargePower write (kW -> 100W units conversion)."""

    @pytest.mark.asyncio
    async def test_write_local_converts_kw_to_100w(self):
        """Local transport converts kW to 100W units for register."""
        coordinator = _mock_coordinator(has_local=True)
        entity = ACChargePowerNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(5.0)

        coordinator.write_named_parameter.assert_called_once()
        call_args = coordinator.write_named_parameter.call_args
        # 5.0 kW * 10 = 50 (100W units)
        assert call_args[0][1] == 50


class TestBatteryCurrentWrite:
    """Test BatteryChargeCurrent and BatteryDischargeCurrent write."""

    @pytest.mark.asyncio
    async def test_charge_current_write_cloud(self):
        """Cloud mode calls set_battery_charge_current."""
        coordinator = _mock_coordinator(has_local=False, has_http=True)
        entity = BatteryChargeCurrentNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(100.0)

        inverter = coordinator.get_inverter_object("1234567890")
        inverter.set_battery_charge_current.assert_called_once_with(current_amps=100)

    @pytest.mark.asyncio
    async def test_discharge_current_no_integer_check(self):
        """BatteryDischargeCurrent intentionally skips fraction check."""
        coordinator = _mock_coordinator(has_local=True)
        entity = BatteryDischargeCurrentNumber(coordinator, "1234567890")
        _prep(entity)

        # This should NOT raise — discharge current has no fraction check
        await entity.async_set_native_value(100.0)
        coordinator.write_named_parameter.assert_called_once()


class TestSystemChargeSOCWrite:
    """Test SystemChargeSOCLimit's custom 3-way write path."""

    @pytest.mark.asyncio
    async def test_write_local(self):
        """Local transport writes named parameter."""
        coordinator = _mock_coordinator(has_local=True)
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.write_named_parameter.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_cloud_api(self):
        """Cloud uses client.api.control.set_system_charge_soc_limit."""
        coordinator = _mock_coordinator(has_local=False)
        # Mock client.api.control path
        mock_result = MagicMock()
        mock_result.success = True
        coordinator.client = MagicMock()
        coordinator.client.api.control.set_system_charge_soc_limit = AsyncMock(
            return_value=mock_result
        )

        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(90.0)

        coordinator.client.api.control.set_system_charge_soc_limit.assert_called_once_with(
            "1234567890", 90
        )

    @pytest.mark.asyncio
    async def test_write_no_transport_raises(self):
        """No local or cloud raises HomeAssistantError."""
        coordinator = _mock_coordinator(has_local=False)
        coordinator.client = None

        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        with pytest.raises(HomeAssistantError, match="No local transport or cloud API"):
            await entity.async_set_native_value(90.0)

    @pytest.mark.asyncio
    async def test_write_range_101_allowed(self):
        """101% (top balancing) is within valid range."""
        coordinator = _mock_coordinator(has_local=True)
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        _prep(entity)

        await entity.async_set_native_value(101.0)
        coordinator.write_named_parameter.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_below_range_raises(self):
        """Below 10% raises HomeAssistantError."""
        coordinator = _mock_coordinator()
        entity = SystemChargeSOCLimitNumber(coordinator, "1234567890")
        entity.hass = MagicMock()

        with pytest.raises(
            HomeAssistantError, match="must be an integer between 10-101"
        ):
            await entity.async_set_native_value(5.0)
