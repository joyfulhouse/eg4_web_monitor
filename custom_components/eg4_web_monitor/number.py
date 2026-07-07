"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
import math
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.number import (
        NumberEntity,
        NumberMode,
        RestoreNumber,
    )
else:
    from homeassistant.components.number import (
        NumberEntity,
        NumberMode,
        RestoreNumber,
    )

from . import EG4ConfigEntry
from .base_entity import EG4BaseNumber, optimistic_value_context
from .const import (
    AC_CHARGE_POWER_MAX,
    AC_CHARGE_POWER_MIN,
    AC_CHARGE_POWER_STEP,
    AC_CHARGE_VOLTAGE_MAX,
    AC_CHARGE_VOLTAGE_MIN,
    AC_CHARGE_VOLTAGE_STEP,
    BATTERY_CURRENT_MAX,
    BATTERY_CURRENT_MIN,
    BATTERY_CURRENT_STEP,
    CUTOFF_VOLTAGE_MAX,
    CUTOFF_VOLTAGE_MIN,
    CUTOFF_VOLTAGE_STEP,
    FORCED_DISCHARGE_POWER_MAX,
    FORCED_DISCHARGE_POWER_MIN,
    FORCED_DISCHARGE_POWER_STEP,
    FORCED_DISCHARGE_SOC_LIMIT_MAX,
    FORCED_DISCHARGE_SOC_LIMIT_MIN,
    FORCED_DISCHARGE_SOC_LIMIT_STEP,
    GRID_PEAK_SHAVING_POWER_MAX,
    GRID_PEAK_SHAVING_POWER_MIN,
    GRID_PEAK_SHAVING_POWER_STEP,
    GRID_SELL_BACK_POWER_MAX,
    GRID_SELL_BACK_POWER_MIN,
    GRID_SELL_BACK_POWER_STEP,
    PARAM_FUNC_GRID_PEAK_SHAVING,
    PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC,
    PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
    PARAM_HOLD_AC_CHARGE_POWER,
    PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
    PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC,
    PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
    PARAM_HOLD_CHARGE_CURRENT,
    PARAM_HOLD_DISCHARGE_CURRENT,
    PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
    PARAM_HOLD_FORCED_CHG_POWER,
    PARAM_HOLD_FORCED_DISCHG_POWER,
    PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT,
    PARAM_HOLD_GRID_PEAK_SHAVING_POWER,
    PARAM_HOLD_OFFGRID_DISCHG_SOC,
    PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
    PARAM_HOLD_ONGRID_DISCHG_SOC,
    PARAM_HOLD_ONGRID_EOD_VOLTAGE,
    PARAM_HOLD_P_TO_USER_START_DISCHG,
    PARAM_HOLD_PTOUSER_START_DISCHARGE,
    PARAM_HOLD_START_PV_VOLT,
    PARAM_HOLD_STOP_DISCHARGE_VOLTAGE,
    PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT,
    PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT,
    PARAM_RAW_PTOUSER_START_CHARGE,
    PARAM_SNA_QUICK_CHARGE_MINUTE,
    PV_CHARGE_POWER_MAX,
    PV_CHARGE_POWER_MIN,
    PV_CHARGE_POWER_STEP,
    PV_START_VOLTAGE_MAX,
    PV_START_VOLTAGE_MIN,
    PV_START_VOLTAGE_STEP,
    QUICK_CHARGE_DURATION_DEFAULT,
    QUICK_CHARGE_DURATION_MAX,
    QUICK_CHARGE_DURATION_MIN,
    QUICK_CHARGE_DURATION_STEP,
    REG_AC_CHARGE_END_VOLTAGE,
    REG_AC_CHARGE_START_VOLTAGE,
    AC_CHARGE_BATTERY_SOC_MAX,
    AC_CHARGE_BATTERY_SOC_MIN,
    AC_CHARGE_BATTERY_SOC_STEP,
    AC_CHARGE_SOC_LIMIT_MAX,
    AC_CHARGE_SOC_LIMIT_MIN,
    AC_CHARGE_SOC_LIMIT_STEP,
    REG_OFFGRID_EOD_VOLTAGE,
    REG_ONGRID_EOD_VOLTAGE,
    REG_PTOUSER_START_CHARGE,
    REG_SYSTEM_CHARGE_VOLT_LIMIT,
    SOC_LIMIT_MAX,
    SOC_LIMIT_MIN,
    SOC_LIMIT_STEP,
    START_CHARGE_POWER_MAX,
    START_CHARGE_POWER_MIN,
    START_CHARGE_POWER_STEP,
    START_DISCHARGE_POWER_MAX,
    START_DISCHARGE_POWER_MIN,
    START_DISCHARGE_POWER_STEP,
    STOP_DISCHARGE_VOLTAGE_MAX,
    STOP_DISCHARGE_VOLTAGE_MIN,
    STOP_DISCHARGE_VOLTAGE_STEP,
    SYSTEM_CHARGE_SOC_LIMIT_MAX,
    SYSTEM_CHARGE_SOC_LIMIT_MIN,
    SYSTEM_CHARGE_SOC_LIMIT_STEP,
    SYSTEM_CHARGE_VOLT_LIMIT_MAX,
    SYSTEM_CHARGE_VOLT_LIMIT_MIN,
    SYSTEM_CHARGE_VOLT_LIMIT_STEP,
    control_side_and_mode,
    is_control_active,
)
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    async_write_with_cloud_fallback,
    flag_offgrid_control_suppression,
    is_offgrid_family,
    is_supported_control_model,
    supports_grid_sellback,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


class EG4BaseNumberEntity(EG4BaseNumber, NumberEntity):
    """Base class for EG4 number entities with shared read/write helpers.

    Provides _read_param_value() for the common multi-tier parameter read
    pattern and _write_parameter() for local/cloud parameter write routing.
    """

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    # Unique-id suffix used to classify a regime-gated (SOC vs Voltage) control.
    # Left None for controls that are always shown (power, current, etc.).
    _control_key: str | None = None

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the base number entity.

        For regime-gated controls, the default-enabled state is derived from the
        configured battery control mode so the non-selected (SOC or Voltage) set
        starts disabled, reducing entity clutter. Users can still enable a
        disabled control manually.
        """
        super().__init__(coordinator, serial)
        if self._control_key is not None:
            charge_mode, discharge_mode = coordinator.get_configured_control_modes()
            self._attr_entity_registry_enabled_default = is_control_active(
                self._control_key, charge_mode, discharge_mode
            )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    # ── Regime effectiveness (SOC vs Voltage) ──────────────────────────────

    @property
    def _control_active_mode(self) -> str | None:
        """Live regime (soc/voltage) governing this control's side, or None."""
        if self._control_key is None:
            return None
        classification = control_side_and_mode(self._control_key)
        if classification is None:
            return None
        side, _mode = classification
        return self.coordinator.get_live_control_mode(
            self.serial, discharge=(side == "discharge")
        )

    @property
    def is_control_effective(self) -> bool:
        """Whether the inverter currently honors this control (live regime)."""
        if self._control_key is None:
            return True
        charge_live = self.coordinator.get_live_control_mode(self.serial)
        discharge_live = self.coordinator.get_live_control_mode(
            self.serial, discharge=True
        )
        return is_control_active(self._control_key, charge_live, discharge_live)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose effectiveness so users see when a limit is currently inactive."""
        if self._control_key is None:
            return None
        classification = control_side_and_mode(self._control_key)
        return {
            "control_regime": classification[1] if classification else None,
            "active_control_mode": self._control_active_mode,
            "is_effective": self.is_control_effective,
        }

    def _warn_if_ineffective(self) -> None:
        """Log a non-blocking warning when setting a currently-inactive control.

        The write still persists (it takes effect once the regime is switched),
        but the user is told it has no immediate effect.
        """
        if self._control_key is None or self.is_control_effective:
            return
        classification = control_side_and_mode(self._control_key)
        side = classification[0] if classification else "battery"
        regime = classification[1] if classification else ""
        _LOGGER.warning(
            "%s changed, but %s control is in %s mode — this %s limit has no "
            "effect until the %s control mode is set to %s (serial %s)",
            self._attr_name,
            side,
            self._control_active_mode,
            regime,
            side,
            regime,
            self.serial,
        )

    @abstractmethod
    def _get_related_entity_types(self) -> tuple[type, ...]:
        """Return tuple of related entity types for parameter refresh."""

    # ── Value read helpers ──────────────────────────────────────────

    def _params_are_local_raw(self) -> bool:
        """Whether this serial's parameter cache holds raw register values.

        Thin wrapper over :meth:`EG4DataUpdateCoordinator.params_are_local_raw`
        (the single implementation): a HYBRID transport surfaces raw register
        values, so treating cloud-populated (kW-scaled) caches as raw would
        mis-scale the display (12 kW would show 1.2).
        """
        return self.coordinator.params_are_local_raw(self.serial)

    @staticmethod
    def _volts_from_param(raw: Any) -> float:
        """Normalize a battery-voltage parameter to volts across transports.

        The local Modbus transport surfaces the raw register value (decivolts,
        e.g. ``595``), while the cloud API returns the already-scaled volts
        (e.g. ``59.5``). Battery-bank voltages for these inverters are well
        under 100 V, so any value of 100 or more is decivolts and is divided by
        ten; smaller values are already in volts.
        """
        value = float(raw)
        return round(value / 10.0 if value >= 100 else value, 1)

    def _value_from_params(
        self,
        param_key: str,
        value_min: float,
        value_max: float,
        param_transform: Callable[[Any], float] | None,
    ) -> float | None:
        """Extract numeric value from coordinator parameter data."""
        params = self._parameter_data
        if not params:
            return None
        raw = params.get(param_key)
        if raw is None:
            return None
        val = param_transform(raw) if param_transform else float(raw)
        if value_min <= val <= value_max:
            return val
        return None

    def _value_from_inverter(
        self,
        inverter_attr: str | None,
        dict_attr: str | None,
        dict_key: str | None,
        value_min: float,
        value_max: float,
    ) -> float | None:
        """Extract numeric value from inverter object attribute or dict."""
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            return None
        val: Any
        if dict_attr and dict_key:
            container = getattr(inverter, dict_attr, None)
            if not container:
                return None
            val = container.get(dict_key)
        elif inverter_attr:
            val = getattr(inverter, inverter_attr, None)
        else:
            return None
        if val is None:
            return None
        fval = float(val)
        if value_min <= fval <= value_max:
            return fval
        return None

    def _read_param_value(
        self,
        *,
        param_key: str,
        value_min: float,
        value_max: float,
        inverter_attr: str | None = None,
        inverter_dict_attr: str | None = None,
        inverter_dict_key: str | None = None,
        as_float: bool = False,
        precision: int = 1,
        param_transform: Callable[[Any], float] | None = None,
        params_first: bool = False,
    ) -> float | None:
        """Read parameter with standard multi-tier lookup.

        Standard order: optimistic -> local params -> inverter -> param fallback.
        With params_first: optimistic -> local params -> params -> inverter.
        """
        if self._optimistic_value is not None:
            if as_float:
                return float(round(self._optimistic_value, precision))
            return int(self._optimistic_value)

        def _fmt(raw: float | None) -> float | None:
            if raw is None:
                return None
            if as_float:
                return float(round(raw, precision))
            return int(raw)

        try:
            if self.coordinator.is_local_only():
                return _fmt(
                    self._value_from_params(
                        param_key, value_min, value_max, param_transform
                    )
                )

            if params_first:
                result = _fmt(
                    self._value_from_params(
                        param_key, value_min, value_max, param_transform
                    )
                )
                if result is not None:
                    return result
                return _fmt(
                    self._value_from_inverter(
                        inverter_attr,
                        inverter_dict_attr,
                        inverter_dict_key,
                        value_min,
                        value_max,
                    )
                )

            result = _fmt(
                self._value_from_inverter(
                    inverter_attr,
                    inverter_dict_attr,
                    inverter_dict_key,
                    value_min,
                    value_max,
                )
            )
            if result is not None:
                return result
            return _fmt(
                self._value_from_params(
                    param_key, value_min, value_max, param_transform
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    # ── Value write helpers ─────────────────────────────────────────

    async def _write_parameter(
        self,
        value: float,
        *,
        local_param: str,
        local_value: int | float | None = None,
        cloud_method: str | None = None,
        cloud_kwargs: dict[str, Any] | None = None,
        cloud_write: Callable[[], Awaitable[Any]] | None = None,
        label: str,
    ) -> None:
        """Write parameter via local transport or cloud API with optimistic context.

        The local write is attempted first when a transport is attached; on
        failure (or a known-down link) it falls back to the cloud path when a
        cloud client exists — HYBRID parity with the switch platform's
        ``_execute_local_with_fallback``. ``cloud_write`` overrides the
        default inverter-method cloud path for entities whose verified cloud
        route is a direct named-parameter write.
        """
        _LOGGER.info("Setting %s for %s", label, self.serial)
        self._warn_if_ineffective()
        write_val = local_value if local_value is not None else int(value)

        async def _local_write() -> None:
            await self.coordinator.write_named_parameter(
                local_param, write_val, serial=self.serial
            )
            await asyncio.sleep(0.5)

        async def _cloud_via_method() -> None:
            inverter = self._get_inverter_or_raise()
            method = getattr(inverter, cloud_method or "", None)
            if method is None:
                raise HomeAssistantError(
                    f"Failed to set {label}: pylxpweb is missing {cloud_method}"
                )
            success = await method(**(cloud_kwargs or {}))
            if not success:
                raise HomeAssistantError(f"Failed to set {label}")
            await inverter.refresh()

        with optimistic_value_context(self, value):
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                label,
                local_write=_local_write,
                cloud_write=cloud_write
                or (_cloud_via_method if cloud_method else None),
                local_values={local_param: write_val},
            )
            await self._refresh_related_entities()

    async def _write_voltage_register(
        self,
        *,
        value: float,
        param_name: str,
        register: int,
        label: str,
    ) -> None:
        """Write a decivolt voltage register (local by name, cloud by raw register).

        Voltage limit registers store decivolts (V × 10). The local path writes
        the named parameter via the transport's name map; the cloud path writes
        the raw register address directly (avoiding read/write name aliasing).
        In HYBRID mode a failed local write falls back to the cloud path.
        """
        raw_value = int(round(value * 10))
        _LOGGER.info("Setting %s for %s to %.1f V", label, self.serial, value)
        self._warn_if_ineffective()

        async def _local_write() -> None:
            await self.coordinator.write_named_parameter(
                param_name, raw_value, serial=self.serial
            )
            await asyncio.sleep(0.5)

        async def _cloud_write() -> None:
            client = self.coordinator.require_client()
            result = await client.api.control.write_parameters(
                self.serial, {register: raw_value}
            )
            if not result.success:
                raise HomeAssistantError(f"Failed to set {label}")
            await self.coordinator.refresh_inverter_params_if_linked(self.serial)

        with optimistic_value_context(self, value):
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                label,
                local_write=_local_write,
                cloud_write=_cloud_write,
                local_values={param_name: raw_value},
            )
            await self._refresh_related_entities()

    async def _refresh_related_entities(self) -> None:
        """Refresh parameters for all inverters and update related entities."""
        try:
            await self.coordinator.refresh_all_device_parameters()
            platform = self.platform
            if platform is not None:
                related_types = self._get_related_entity_types()
                related_entities = [
                    entity
                    for entity in platform.entities.values()
                    if isinstance(entity, related_types)
                ]
                _LOGGER.info(
                    "Updating %d related entities after parameter refresh",
                    len(related_entities),
                )
                update_tasks = [
                    entity.async_update()  # type: ignore[attr-defined]
                    for entity in related_entities
                ]
                await asyncio.gather(*update_tasks, return_exceptions=True)
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters and entities: %s", e)


# ── Platform setup ───────────────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor number entities from a config entry."""
    coordinator = config_entry.runtime_data
    entities: list[NumberEntity] = []

    for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
        device_type = device_data.get("type")
        if device_type == "inverter":
            model = device_data.get("model", "Unknown")

            # Matches by model-name substring or, for cloud deviceTypeText
            # variants the substrings miss (e.g. "SNA-US 15K", #259), by the
            # detected inverter family.
            if is_supported_control_model(device_data):
                # Quick Charge Duration — gated exactly like the Quick Charge
                # switch (switch.py). Cloud-only: a UI preference for the
                # `minute` start parameter. LOCAL/HYBRID: also written to
                # holding register 234 (the live duration setpoint).
                if (
                    coordinator.has_http_api()
                    or coordinator.has_configured_local_transport(serial)
                ):
                    entities.append(QuickChargeDurationNumber(coordinator, serial))

                # Grid-tied-only controls (Peak Shaving / Forced Discharge)
                # act on grid-parallel export/import blending; the
                # EG4_OFFGRID (SNA) platform has no sellback and no
                # grid-parallel operation, so they are inert there.
                # Suppressed per the PR #220 / issue #197 adjudication
                # (eg4-juzg); mirrors GRID_TIED_ONLY_WORKING_MODE_PARAMS in
                # switch.py.
                offgrid = is_offgrid_family(device_data)
                if offgrid:
                    # Suffix-based probe: number unique IDs embed the model
                    # slug ({clean_model}_{serial}_{key}), and registry
                    # entries from a misdetected-model era (e.g. "unknown",
                    # #219/#222) carry legacy prefixes — all variants end
                    # with {serial}_{key}.
                    flag_offgrid_control_suppression(
                        hass,
                        serial,
                        model,
                        "number",
                        (
                            f"{serial.lower()}_grid_peak_shaving_power",
                            f"{serial.lower()}_forced_discharge_power",
                            f"{serial.lower()}_forced_discharge_soc_limit",
                        ),
                    )
                    # AC Charge SOC Limit (reg 67) is family-rejected on
                    # EG4_OFFGRID (GH #331: live REMOTE_SET_ERROR on a
                    # 12000XP v2, reads 0 on the reference dump, absent from
                    # the off-grid portal page). The family's real AC-charge
                    # SOC window is regs 160/161, created below instead.
                    flag_offgrid_control_suppression(
                        hass,
                        serial,
                        model,
                        "number",
                        (f"{serial.lower()}_ac_charge_soc_limit",),
                        issue_key="offgrid_ac_charge_soc_limit_removed",
                    )
                    entities.extend(
                        [
                            ACChargeStartBatterySOCNumber(coordinator, serial),
                            ACChargeEndBatterySOCNumber(coordinator, serial),
                        ]
                    )
                else:
                    entities.extend(
                        [
                            GridPeakShavingPowerNumber(coordinator, serial),
                            ForcedDischargePowerNumber(coordinator, serial),
                            ForcedDischargeSOCLimitNumber(coordinator, serial),
                            # Reg 67 keeps working on grid-tied/unknown
                            # families — fail-open, matching the other gates.
                            ACChargeSOCLimitNumber(coordinator, serial),
                        ]
                    )

                entities.extend(
                    [
                        # Always-on controls (power, current)
                        ACChargePowerNumber(coordinator, serial),
                        PVChargePowerNumber(coordinator, serial),
                        PVStartVoltageNumber(coordinator, serial),
                        BatteryChargeCurrentNumber(coordinator, serial),
                        BatteryDischargeCurrentNumber(coordinator, serial),
                        # SOC limit controls (enabled when the matching control
                        # mode is SOC — default)
                        SystemChargeSOCLimitNumber(coordinator, serial),
                        OnGridSOCCutoffNumber(coordinator, serial),
                        OffGridSOCCutoffNumber(coordinator, serial),
                        # Voltage limit controls (enabled when the matching
                        # control mode is Voltage). Always created; disabled by
                        # default in SOC mode to reduce entity clutter.
                        SystemChargeVoltLimitNumber(coordinator, serial),
                        OnGridCutoffVoltageNumber(coordinator, serial),
                        OffGridCutoffVoltageNumber(coordinator, serial),
                        ACChargeStartVoltageNumber(coordinator, serial),
                        ACChargeEndVoltageNumber(coordinator, serial),
                        StopDischargeVoltageNumber(coordinator, serial),
                    ]
                )
                # Grid sell-back power cap (reg 103, GH #135) — grid-tied
                # families only; off-grid XP units have no sell-back.
                if supports_grid_sellback(device_data):
                    entities.append(GridSellBackPowerNumber(coordinator, serial))
                    # P_to_user start discharge/charge thresholds (regs
                    # 116/117, GH #272): CT-driven grid-import blending, so
                    # the same grid-tied family gate (EG4_HYBRID, LXP) —
                    # meaningless on EG4_OFFGRID, which has no grid-parallel
                    # operation.
                    entities.append(StartDischargePowerNumber(coordinator, serial))
                    # Reg 117 has no cloud parameter name (remoteRead names
                    # it <EMPTY> on every scanned model), so the entity only
                    # exists where a local register path can serve it — local
                    # modes, modern per-serial HYBRID transports, AND the
                    # deprecated flat single-transport format, which
                    # get_local_transport() still serves for writes (codex
                    # P2 on PR #284).
                    if coordinator.has_local_register_path(serial):
                        entities.append(StartChargePowerNumber(coordinator, serial))

    if entities:
        _LOGGER.info("Setup complete: %d number entities created", len(entities))
        async_add_entities(entities, update_before_add=False)


# ── Entity classes ───────────────────────────────────────────────────


class SystemChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for System Charge SOC Limit control (register 227).

    Values 10-100%: stop charging at this SOC.  101%: enable top balancing.
    """

    _control_key = "system_charge_soc_limit"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "System Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_system_charge_soc_limit"
        )
        self._attr_native_min_value = SYSTEM_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (SystemChargeSOCLimitNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current System Charge SOC limit (reads params first)."""
        return self._read_param_value(
            param_key="HOLD_SYSTEM_CHARGE_SOC_LIMIT",
            value_min=10,
            value_max=101,
            inverter_attr="system_charge_soc_limit",
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the System Charge SOC limit (3-way: local, cloud API, or client)."""
        int_value = int(value)
        if int_value < 10 or int_value > 101:
            raise HomeAssistantError(
                f"SOC limit must be an integer between 10-101%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(f"SOC limit must be an integer value, got {value}")

        _LOGGER.info(
            "Setting System Charge SOC Limit for %s to %d%%", self.serial, int_value
        )
        self._warn_if_ineffective()

        async def _local_write() -> None:
            await self.coordinator.write_named_parameter(
                PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT, int_value, serial=self.serial
            )

        async def _cloud_write() -> None:
            client = self.coordinator.require_client()
            result = await client.api.control.set_system_charge_soc_limit(
                self.serial, int_value
            )
            if not result.success:
                raise HomeAssistantError(f"Failed to set SOC limit to {int_value}%")
            await self.coordinator.refresh_inverter_params_if_linked(self.serial)

        with optimistic_value_context(self, value):
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                f"system charge SOC limit to {int_value}%",
                local_write=_local_write,
                cloud_write=_cloud_write,
                local_values={PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT: int_value},
            )
            await self._refresh_related_entities()


class QuickChargeDurationNumber(RestoreNumber, EG4BaseNumberEntity):
    """Number entity for the Quick Charge Duration (holding register 234, min).

    On LOCAL/HYBRID this entity faithfully mirrors holding register 234 — the
    writable duration setpoint, which the firmware also counts down as the live
    remaining minutes while a charge runs. Its displayed value is the live
    register (idle *and* active), not a retained preference; the firmware governs
    the value (it starts a charge at its own default and counts down, and rejects
    writes to reg 234 while quick charge is off). Writing the entity sets reg 234,
    which only sticks while a charge is running (raising it extends the charge,
    e.g. to keep cells balancing); an idle write is a no-op and the value reverts
    to whatever the register holds.

    On CLOUD there is no equivalent register, so the entity falls back to a
    per-serial preference (stored on the coordinator, restored across restarts
    via RestoreNumber) that is sent as the ``minute`` parameter when the cloud
    Quick Charge is started. Gated identically to the Quick Charge switch.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the Quick Charge Duration number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Quick Charge Duration"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_quick_charge_duration"
        )
        self._attr_native_min_value = QUICK_CHARGE_DURATION_MIN
        self._attr_native_max_value = QUICK_CHARGE_DURATION_MAX
        self._attr_native_step = QUICK_CHARGE_DURATION_STEP
        self._attr_native_unit_of_measurement = "min"
        self._attr_icon = "mdi:timer"
        self._attr_native_precision = 0

    @staticmethod
    def _is_valid_duration(value: float) -> bool:
        """True when value is a whole number of minutes within the bounds."""
        return (
            math.isfinite(value)
            and value == int(value)
            and QUICK_CHARGE_DURATION_MIN <= value <= QUICK_CHARGE_DURATION_MAX
        )

    def _seed_restored_preference(self, native_value: float | None) -> None:
        """Seed the coordinator from a restored value when it is valid.

        The stored preference is only meaningful on the CLOUD path (the start
        ``minute``). On LOCAL/HYBRID the entity mirrors the live holding register
        234, so a restored value is a stale countdown reading, not a preference —
        seeding it would leak that value into a cloud-fallback start duration
        (e.g. restore "3" mid-charge, then a HYBRID cloud fallback starts a
        3-minute charge). So only seed for cloud-only installs (no configured
        local transport). The restored value must also pass the same
        finite/integer/bounds checks as a live set; invalid restored data is
        ignored rather than raising, so a corrupt restore can never break setup.
        """
        if self.coordinator.has_configured_local_transport(self.serial):
            return
        if native_value is None or not self._is_valid_duration(native_value):
            return
        self.coordinator._quick_charge_minutes[self.serial] = int(native_value)

    async def async_added_to_hass(self) -> None:
        """Restore the saved duration preference, then wire up the listener."""
        await super().async_added_to_hass()
        # Only restore when the coordinator doesn't already hold a value for
        # this serial (e.g. set during this session).
        if self.serial not in self.coordinator._quick_charge_minutes:
            last_data = await self.async_get_last_number_data()
            self._seed_restored_preference(getattr(last_data, "native_value", None))

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (QuickChargeDurationNumber,)

    @property
    def native_value(self) -> float | None:
        """Mirror the live holding reg 234 value, else the cloud preference.

        On LOCAL/HYBRID the coordinator surfaces the raw holding register 234
        value (minutes) as ``quickChargeMinute`` whenever it has read it — idle
        or active — so the entity shows exactly what the register holds (the
        firmware governs that value). When that reading is absent (CLOUD, which
        has no such register, or before the first local read) it falls back to
        the stored preference (default 60) used as the cloud start ``minute``.
        The displayed value may be below native_min (1, e.g. an idle register of
        0); min/max only constrain user input, not the read-back state.
        """
        devices = (self.coordinator.data or {}).get("devices", {})
        status = devices.get(self.serial, {}).get("quick_charge_status")
        if isinstance(status, dict):
            register = status.get("quickChargeMinute")
            if register is not None:
                return int(register)
        return self.coordinator._quick_charge_minutes.get(
            self.serial, QUICK_CHARGE_DURATION_DEFAULT
        )

    async def async_set_native_value(self, value: float) -> None:
        """Write holding reg 234 live (LOCAL/HYBRID) or store the cloud preference.

        On LOCAL/HYBRID the firmware only accepts a write to holding register 234
        while a quick charge is *running*, so we confirm the live state (a fresh
        enable-bit read, not the throttled cache) first:

        - active  -> write reg 234 (extends/reduces the running charge);
        - idle    -> raise ServiceValidationError (the firmware would reject it
          and the entity faithfully mirrors the register, so a silent store would
          be a no-op that misreports success);
        - unknown -> raise (the state could not be read).

        On CLOUD there is no register, so the value is stored as the per-serial
        preference applied as the ``minute`` parameter when the charge starts.
        """
        if not self._is_valid_duration(value):
            raise HomeAssistantError(
                "Quick Charge Duration must be a whole number of minutes between "
                f"{QUICK_CHARGE_DURATION_MIN} and {QUICK_CHARGE_DURATION_MAX}, "
                f"got {value}"
            )
        minutes = int(value)
        if self.coordinator.has_local_transport(self.serial):
            active = await self.coordinator.is_quick_charge_active_live(self.serial)
            if active is None:
                raise HomeAssistantError(
                    "Could not read the inverter's Quick Charge state; the "
                    "duration was not changed. Please try again."
                )
            if not active:
                raise ServiceValidationError(
                    "Quick Charge must be running to set its duration — the "
                    "inverter only accepts a new duration while a charge is "
                    "active. Turn on Quick Charge first, then adjust this."
                )
            await self.coordinator.write_named_parameter(
                PARAM_SNA_QUICK_CHARGE_MINUTE, minutes, serial=self.serial
            )
            _LOGGER.debug(
                "Quick Charge duration for %s set to %d min (live reg 234 write)",
                self.serial,
                minutes,
            )
        else:
            # Cloud: no live register — store the preference used at start.
            self.coordinator._quick_charge_minutes[self.serial] = minutes
            _LOGGER.debug(
                "Quick Charge duration preference for %s stored as %d min (cloud)",
                self.serial,
                minutes,
            )
        self.async_write_ha_state()


class ACChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge Power control (stored as 100W units)."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_ac_charge_power"
        self._attr_native_min_value = AC_CHARGE_POWER_MIN
        self._attr_native_max_value = AC_CHARGE_POWER_MAX
        self._attr_native_step = AC_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge power in kW.

        Same dual-source handling as ForcedDischargePowerNumber: with a
        local transport the param cache holds the raw 100W value (scaled
        ÷10 here) and the pylxpweb property is NOT consulted — in HYBRID
        mode ``inverter.parameters`` is populated from that same transport,
        so raw values ≤15 (real ≤1.5 kW) would pass the bound and display
        10x (GH #207: 0.7 kW showed 7 kW). Cloud-only installs read the
        property, which returns cloud-scaled kW.
        """
        if self._params_are_local_raw():
            return self._read_param_value(
                param_key=PARAM_HOLD_AC_CHARGE_POWER,
                value_min=0,
                value_max=15,
                as_float=True,
                param_transform=lambda v: float(v) / 10.0,
            )
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_POWER,
            value_min=0,
            value_max=15,
            inverter_attr="ac_charge_power_limit",
            as_float=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge power (converts kW to 100W units for register)."""
        if value < 0.0 or value > 15.0:
            raise HomeAssistantError(
                f"AC charge power must be between 0.0-15.0 kW, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_POWER,
            local_value=int(value * 10),
            cloud_method="set_ac_charge_power",
            cloud_kwargs={"power_kw": value},
            label=f"AC charge power to {value:.1f} kW",
        )


class PVChargePowerNumber(EG4BaseNumberEntity):
    """Number entity for PV Charge Power control (reg 74, 100W units)."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "PV Charge Power"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_pv_charge_power"
        self._attr_native_min_value = PV_CHARGE_POWER_MIN
        self._attr_native_max_value = PV_CHARGE_POWER_MAX
        self._attr_native_step = PV_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargePowerNumber, PVChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current PV charge power in kW.

        The forced/PV charge power lives in holding register 74
        (``HOLD_FORCED_CHG_POWER_CMD``), stored in 100W units (0-150 = 0-15 kW)
        — the same encoding as AC charge power (reg 66). With a local
        transport the param cache holds the raw 100W value (scaled ÷10 here)
        and the pylxpweb property is NOT consulted (HYBRID raw-as-kW 10x
        hazard, see ACChargePowerNumber); cloud-only installs read the
        property, which returns kW.
        """
        if self._params_are_local_raw():
            return self._read_param_value(
                param_key=PARAM_HOLD_FORCED_CHG_POWER,
                value_min=0,
                value_max=15,
                param_transform=lambda v: float(v) / 10.0,
            )
        return self._read_param_value(
            param_key=PARAM_HOLD_FORCED_CHG_POWER,
            value_min=0,
            value_max=15,
            inverter_attr="pv_charge_power_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV charge power (kW -> reg 74 in 100W units; cloud takes kW)."""
        int_value = int(value)
        if int_value < 0 or int_value > 15:
            raise HomeAssistantError(
                f"PV charge power must be between 0-15 kW, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"PV charge power must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_FORCED_CHG_POWER,
            local_value=int(int_value * 10),
            cloud_method="set_pv_charge_power",
            cloud_kwargs={"power_kw": int_value},
            label=f"PV charge power to {int_value} kW",
        )


class PVStartVoltageNumber(EG4BaseNumberEntity):
    """Number entity for PV Start Voltage control (register 22).

    Controls the minimum PV voltage at which the MPPT tracker activates.
    Lowering this value (e.g. to 140V) keeps the MPPT engaged across a wider
    voltage range, reducing connect/disconnect cycling that can cause internal
    DC bus voltage spikes (vbus out of range / E019 faults).

    Register stores decivolts (raw 1400 = 140.0V).
    Cloud API accepts human-readable volts (valueText=140).
    Firmware rejects values below 140V (error code 3).
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "PV Start Voltage"
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_pv_start_voltage"
        self._attr_native_min_value = PV_START_VOLTAGE_MIN
        self._attr_native_max_value = PV_START_VOLTAGE_MAX
        self._attr_native_step = PV_START_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:solar-power-variant"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (PVStartVoltageNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current PV start voltage (raw decivolts / 10 -> V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_START_PV_VOLT,
            value_min=90,
            value_max=500,
            as_float=False,
            param_transform=lambda v: float(v) / 10.0,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the PV start voltage."""
        int_value = int(value)
        if int_value < PV_START_VOLTAGE_MIN or int_value > PV_START_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"PV start voltage must be between "
                f"{PV_START_VOLTAGE_MIN}-{PV_START_VOLTAGE_MAX} V, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"PV start voltage must be an integer value, got {value}"
            )

        _LOGGER.info("Setting PV start voltage for %s to %d V", self.serial, int_value)

        async def _local_write() -> None:
            # Local Modbus: write raw decivolts (140V -> 1400)
            await self.coordinator.write_named_parameter(
                PARAM_HOLD_START_PV_VOLT, int_value * 10, serial=self.serial
            )
            await asyncio.sleep(0.5)

        async def _cloud_write() -> None:
            # Cloud API: write human-readable volts
            client = self.coordinator.require_client()
            result = await client.api.control.write_parameter(
                self.serial, "HOLD_START_PV_VOLT", str(int_value)
            )
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set PV start voltage to {int_value} V"
                )
            await self.coordinator.refresh_inverter_params_if_linked(self.serial)

        with optimistic_value_context(self, value):
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                f"PV start voltage to {int_value} V",
                local_write=_local_write,
                cloud_write=_cloud_write,
                local_values={PARAM_HOLD_START_PV_VOLT: int_value * 10},
            )
            await self._refresh_related_entities()


class GridPeakShavingPowerNumber(EG4BaseNumberEntity):
    """Number entity for Grid Peak Shaving Power control.

    Cloud-write-only (eg4-gfu5): PS1 lives at holding register 206, not the
    register 231 the transport name map historically claimed, and the raw
    register encoding (presumed deci-kW) is unverified. The cloud write goes
    by parameter NAME, so the server resolves the true register and accepts
    float kW — local transport name-writes are never used for this control.

    Firmware coupling to Peak Shaving mode (#328, live-verified 2026-07):
    the inverter only accepts this setpoint while Peak Shaving mode
    (FUNC_GRID_PEAK_SHAVING, reg 179 bit 7) is enabled — writes with the
    mode off fail param-specifically with DATAFRAME_TIMEOUT — and the
    firmware ZEROES the stored setpoint whenever the mode deactivates. A
    0 readback right after the mode turns off is therefore firmware
    behavior, not a read bug.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Grid Peak Shaving Power"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_grid_peak_shaving_power"
        )
        self._attr_native_min_value = GRID_PEAK_SHAVING_POWER_MIN
        self._attr_native_max_value = GRID_PEAK_SHAVING_POWER_MAX
        self._attr_native_step = GRID_PEAK_SHAVING_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_native_precision = 1
        if coordinator.is_local_only():
            # Pure-LOCAL reads this control since #328 (reg 206, deci-kW
            # encoding verified; hybrid-family-gated targeted read) but the
            # write path is still cloud-routed — register it disabled so a
            # write-less config entity is opt-in. Users who attach cloud
            # credentials (or want the read-only view) can enable it.
            self._attr_entity_registry_enabled_default = False

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (GridPeakShavingPowerNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current grid peak shaving power (cloud-sourced kW)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_GRID_PEAK_SHAVING_POWER,
            value_min=0,
            value_max=25.5,
            inverter_attr="grid_peak_shaving_power_limit",
            as_float=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid peak shaving power via the cloud API.

        Deliberately NOT routed through the local transport name map: the
        old map entry pointed local writes at register 231 (an unknown,
        unrelated register), and the true PS1 register's raw encoding is
        unverified, so local raw writes cannot be constructed safely. The
        cloud name-write works in CLOUD and HYBRID modes; in pure-LOCAL mode
        this control cannot be written.

        Pre-check (#328): the firmware rejects this write (DATAFRAME_TIMEOUT)
        while Peak Shaving mode is disabled, and clears the setpoint whenever
        the mode deactivates — so a write with the mode known-off is refused
        up front with a clear message. Because the parameter cache refreshes
        ~hourly, a cached False is confirmed with a live reg-179 cloud read
        before blocking (verify-then-block) so a mode just enabled on the
        portal/LCD isn't wrongly refused. When the mode state is unknown
        (parameter absent, or the live read fails) the write proceeds
        fail-open rather than blocking on missing data.
        """
        if value < 0.0 or value > 25.5:
            raise HomeAssistantError(
                f"Grid peak shaving power must be between 0.0-25.5 kW, got {value}"
            )
        client = self.coordinator.client
        if client is None:
            raise HomeAssistantError(
                "Grid peak shaving power requires the cloud API: the local "
                "register encoding is unverified (the previous local write "
                "path targeted the wrong register). Add cloud credentials to "
                "this integration entry to use this control."
            )
        mode_state = self._parameter_data.get(PARAM_FUNC_GRID_PEAK_SHAVING)
        if mode_state is not None and not mode_state:
            # Verify-then-block: the parameter cache refreshes ~hourly, so a
            # user who just enabled Peak Shaving mode on the EG4 portal or
            # the inverter LCD would otherwise be locked out by a stale
            # cached False until the next refresh. Confirm with a live
            # single-register cloud read (reg 179 carries the FUNC bit)
            # before refusing; if the read fails or omits the bit, fail
            # open — the firmware is the final arbiter of the write.
            try:
                response = await client.api.control.read_parameters(
                    self.serial, start_register=179, point_number=1
                )
                mode_state = response.parameters.get(PARAM_FUNC_GRID_PEAK_SHAVING)
            except Exception as err:
                _LOGGER.debug(
                    "Live Peak Shaving mode check for %s failed (%s); "
                    "proceeding fail-open",
                    self.serial,
                    err,
                )
                mode_state = None
            if mode_state is not None and not mode_state:
                raise ServiceValidationError(
                    "Peak Shaving mode is disabled — enable it first: the "
                    "inverter rejects the power setpoint while the mode is "
                    "off, and the firmware clears the setpoint whenever the "
                    "mode deactivates."
                )
            if mode_state:
                # The cache said off but the device says ON — seed the
                # fresh truth so the mode switch stops showing stale state
                # until the next scheduled parameter refresh.
                self.coordinator.note_parameters_written(
                    self.serial, {PARAM_FUNC_GRID_PEAK_SHAVING: True}
                )
        _LOGGER.info(
            "Setting grid peak shaving power to %.1f kW for %s", value, self.serial
        )
        self._warn_if_ineffective()
        with optimistic_value_context(self, value):
            inverter = self._get_inverter_or_raise()
            success = await inverter.set_grid_peak_shaving_power(power_kw=value)
            if not success:
                raise HomeAssistantError(
                    f"Failed to set grid peak shaving power to {value:.1f} kW"
                )
            await inverter.refresh()
            await self._refresh_related_entities()


class ACChargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge SOC Limit control (reg 67).

    Grid-tied families only: on EG4_OFFGRID (SNA/12000XP/6000XP) the cloud
    REJECTS writes to HOLD_AC_CHARGE_SOC_LIMIT (GH #331: live
    REMOTE_SET_ERROR on a 12000XP v2), reg 67 reads 0 on the reference dump
    and the off-grid portal page does not carry the field — that family's
    AC-charge SOC window is regs 160/161 (ACChargeStartBatterySOCNumber /
    ACChargeEndBatterySOCNumber), so this entity is not created there.
    """

    _control_key = "ac_charge_soc_limit"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_soc_limit"
        )
        self._attr_native_min_value = AC_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = AC_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = AC_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge SOC limit."""
        return self._read_param_value(
            param_key="HOLD_AC_CHARGE_SOC_LIMIT",
            value_min=AC_CHARGE_SOC_LIMIT_MIN,
            value_max=AC_CHARGE_SOC_LIMIT_MAX,
            inverter_attr="ac_charge_soc_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge SOC limit."""
        int_value = int(value)
        if int_value < AC_CHARGE_SOC_LIMIT_MIN or int_value > AC_CHARGE_SOC_LIMIT_MAX:
            raise HomeAssistantError(
                f"AC charge SOC limit must be between "
                f"{AC_CHARGE_SOC_LIMIT_MIN}-{AC_CHARGE_SOC_LIMIT_MAX}%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge SOC limit must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
            cloud_method="set_ac_charge_soc_limit",
            cloud_kwargs={"soc_percent": int_value},
            label=f"AC charge SOC limit to {int_value}%",
        )


class ACChargeStartBatterySOCNumber(EG4BaseNumberEntity):
    """AC Charge Start Battery SOC (reg 160, EG4_OFFGRID only, GH #331).

    Battery SOC at which the off-grid family's AC Charge working mode starts
    charging from the grid — with reg 161 the family's PRIMARY AC-charge SOC
    window, a portal-verified writable holdParam on the off-grid working-mode
    page (the reference dump reads 90, the reporter's live config). Reg 67
    (AC Charge SOC Limit) is family-rejected there (REMOTE_SET_ERROR + portal
    absence + reads 0), so this entity replaces it on EG4_OFFGRID. Whole
    percent, SCALE_NONE on both paths; reg 160 is in pylxpweb's transport
    name map, so local named reads/writes work as-is.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge Start Battery SOC"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_start_battery_soc"
        )
        self._attr_native_min_value = AC_CHARGE_BATTERY_SOC_MIN
        self._attr_native_max_value = AC_CHARGE_BATTERY_SOC_MAX
        self._attr_native_step = AC_CHARGE_BATTERY_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-low"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeStartBatterySOCNumber, ACChargeEndBatterySOCNumber)

    @property
    def native_value(self) -> float | None:
        """Return the SOC that starts AC charging (whole percent, both paths)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC,
            value_min=AC_CHARGE_BATTERY_SOC_MIN,
            value_max=AC_CHARGE_BATTERY_SOC_MAX,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the SOC that starts AC charging (local named write or cloud)."""
        int_value = int(value)
        if (
            int_value < AC_CHARGE_BATTERY_SOC_MIN
            or int_value > AC_CHARGE_BATTERY_SOC_MAX
        ):
            raise HomeAssistantError(
                f"AC charge start battery SOC must be between "
                f"{AC_CHARGE_BATTERY_SOC_MIN}-{AC_CHARGE_BATTERY_SOC_MAX}%, "
                f"got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge start battery SOC must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC,
            # The named-param cloud writer is BOTH the cloud-mode path and
            # the HYBRID local-failure fallback — the portal's own
            # holdParam write (GH #331).
            cloud_write=lambda: _write_cloud_named_soc(
                self, PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC, int_value
            ),
            label=f"AC charge start battery SOC to {int_value}%",
        )


class ACChargeEndBatterySOCNumber(EG4BaseNumberEntity):
    """AC Charge End Battery SOC (reg 161, EG4_OFFGRID only, GH #331).

    Battery SOC at which the off-grid family's AC Charge working mode stops
    charging from the grid — with reg 160 the family's PRIMARY AC-charge SOC
    window, a portal-verified writable holdParam on the off-grid working-mode
    page (the reference dump reads 100, the reporter's live config). Reg 67
    (AC Charge SOC Limit) is family-rejected there (REMOTE_SET_ERROR + portal
    absence + reads 0), so this entity replaces it on EG4_OFFGRID.

    Whole percent, SCALE_NONE on both paths; reg 161 is in pylxpweb's
    transport name map from 0.9.36b28, so this entity mirrors the Start
    entity exactly (named reads/writes on every path).

    NOTE (PR #332 review): LOCAL Modbus writes to reg 161 are
    hardware-UNVERIFIED on the off-grid family — all #331 write evidence is
    the cloud holdParam path, and on grid-tied hardware reg 161 was observed
    read-only. A silently-ignored local write is covered by the named write
    path's post-write parameter readback plus the HYBRID cloud fallback, but
    flag this if a LOCAL-only off-grid report ever shows the value not
    sticking.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge End Battery SOC"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_end_battery_soc"
        )
        self._attr_native_min_value = AC_CHARGE_BATTERY_SOC_MIN
        self._attr_native_max_value = AC_CHARGE_BATTERY_SOC_MAX
        self._attr_native_step = AC_CHARGE_BATTERY_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeStartBatterySOCNumber, ACChargeEndBatterySOCNumber)

    @property
    def native_value(self) -> float | None:
        """Return the SOC that stops AC charging (whole percent, both paths)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC,
            value_min=AC_CHARGE_BATTERY_SOC_MIN,
            value_max=AC_CHARGE_BATTERY_SOC_MAX,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the SOC that stops AC charging (local named write or cloud)."""
        int_value = int(value)
        if (
            int_value < AC_CHARGE_BATTERY_SOC_MIN
            or int_value > AC_CHARGE_BATTERY_SOC_MAX
        ):
            raise HomeAssistantError(
                f"AC charge end battery SOC must be between "
                f"{AC_CHARGE_BATTERY_SOC_MIN}-{AC_CHARGE_BATTERY_SOC_MAX}%, "
                f"got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge end battery SOC must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC,
            # The named-param cloud writer is BOTH the cloud-mode path and
            # the HYBRID local-failure fallback — the portal's own
            # holdParam write (GH #331).
            cloud_write=lambda: _write_cloud_named_soc(
                self, PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC, int_value
            ),
            label=f"AC charge end battery SOC to {int_value}%",
        )


async def _write_cloud_named_soc(
    entity: EG4BaseNumberEntity, param: str, soc: int
) -> None:
    """Write an off-grid AC-charge SOC holdParam via the cloud named write.

    The portal's own call for the off-grid working-mode page (GH #331):
    remoteSet/write with the holdParam name and the whole-percent value as
    text. Bare writer — logging, optimistic state and the related-entity
    refresh are provided by the callers' write wrappers.
    """
    client = entity.coordinator.require_client()
    result = await client.api.control.write_parameter(entity.serial, param, str(soc))
    if not result.success:
        raise HomeAssistantError(f"Failed to set {param} to {soc}%")
    await entity.coordinator.refresh_inverter_params_if_linked(entity.serial)


class GridSellBackPowerNumber(EG4BaseNumberEntity):
    """Number entity for Grid Sell Back Power control (reg 103, kW).

    Maximum export (sell-back) power — "Grid Sell Back Power(kW)" in BOTH
    the EG4 and Luxpower web UIs (GH #135 + #274 screenshots). The register
    stores 100 W units, the reg-66/74/82 encoding, NOT the percent the
    protocol PDF claims: the 2026-04-13 live local probe read raw 160 on an
    18kPV + FlexBOSS21 while the same 18kPV's cloud named read returned
    "16" (= 16.0 kW), and the GH #274 LXP shows 12.1 kW (raw 121) —
    impossible as a 0-100 percent. Cloud named reads/writes are kW floats
    (server scales); local raw needs ÷10/×10, mirroring
    ForcedDischargePowerNumber. Only created for grid-tied families.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_translation_key = "grid_sell_back_power"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_grid_sell_back_power"
        )
        self._attr_native_min_value = GRID_SELL_BACK_POWER_MIN
        self._attr_native_max_value = GRID_SELL_BACK_POWER_MAX
        self._attr_native_step = GRID_SELL_BACK_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:transmission-tower-export"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (GridSellBackPowerNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current grid sell back power in kW.

        With a local transport the parameter cache holds the raw 100 W
        register value (scaled ÷10 here). Cloud-populated caches hold the
        server-scaled kW value ("16", "12.1") — read it as a float from the
        parameters dict rather than through pylxpweb's legacy
        ``feed_in_grid_power_percent`` property, whose int()+0-100 range
        check chokes on kW floats (the GH #274 "entity never changes"
        symptom).
        """
        if self._params_are_local_raw():
            return self._read_param_value(
                param_key=PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
                value_min=GRID_SELL_BACK_POWER_MIN,
                value_max=GRID_SELL_BACK_POWER_MAX,
                as_float=True,
                param_transform=lambda v: float(v) / 10.0,
            )
        return self._read_param_value(
            param_key=PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
            value_min=GRID_SELL_BACK_POWER_MIN,
            value_max=GRID_SELL_BACK_POWER_MAX,
            inverter_dict_attr="parameters",
            inverter_dict_key=PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
            as_float=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the grid sell back power in kW."""
        if value < GRID_SELL_BACK_POWER_MIN or value > GRID_SELL_BACK_POWER_MAX:
            raise HomeAssistantError(
                f"Grid sell back power must be between "
                f"{GRID_SELL_BACK_POWER_MIN}-{GRID_SELL_BACK_POWER_MAX} kW, "
                f"got {value}"
            )
        value = round(value, 1)
        inverter = self.coordinator.get_inverter_object(self.serial)
        if self.coordinator.has_local_transport(self.serial) or (
            inverter is not None and hasattr(inverter, "set_feed_in_grid_power_kw")
        ):
            await self._write_parameter(
                value,
                local_param=PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
                local_value=int(round(value * 10)),
                cloud_method="set_feed_in_grid_power_kw",
                cloud_kwargs={"power_kw": value},
                label=f"grid sell back power to {value:.1f} kW",
            )
            return
        # Cloud path on a pylxpweb without set_feed_in_grid_power_kw: write
        # the named parameter directly — the cloud takes kW strings for this
        # register (the website's own call), so no library upgrade is
        # required for the fix to work.
        await self._write_cloud_named_parameter_kw(value)

    async def _write_cloud_named_parameter_kw(self, value: float) -> None:
        """Write the kW value via the generic cloud named-parameter API."""
        client = self.coordinator.require_client()
        _LOGGER.info(
            "Setting grid sell back power for %s to %.1f kW", self.serial, value
        )
        self._warn_if_ineffective()
        with optimistic_value_context(self, value):
            result = await client.api.control.write_parameter(
                self.serial,
                PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
                f"{value:g}",
            )
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set grid sell back power to {value:.1f} kW"
                )
            inverter = self.coordinator.get_inverter_object(self.serial)
            if inverter:
                await inverter.refresh(force=True, include_parameters=True)
            await self._refresh_related_entities()


def _signed_from_register(raw: Any) -> float:
    """Decode a signed 16-bit register value (two's complement)."""
    value = float(raw)
    return value - 65536.0 if value > 32767.0 else value


class StartDischargePowerNumber(EG4BaseNumberEntity):
    """Start Discharge P_import threshold (HOLD 116, whole watts, GH #272).

    LXP-protocol ``PtoUserStartdischg``: on-grid CT installs start
    discharging the battery once grid import (P_to_user) exceeds this
    wattage (given SOC above the On-Grid SOC Cut-Off) — "Start Discharge
    P_import(W)" in the Luxpower web UI, which shows a ``[50, ]`` range
    hint. The protocol register table pins scale **1 W** (default 50 W), NOT
    the 100 W encoding of regs 66/74/82/103: fleet scanner reads show raw
    100 == cloud "100" == 100 W. One register, two parameter spellings:
    pylxpweb's local name map uses HOLD_PTOUSER_START_DISCHARGE, while the
    live cloud API uses HOLD_P_TO_USER_START_DISCHG (reporter-verified
    remoteSet call in the GH #272 browser console + every scanner dump).
    Watts on both paths — no scaling anywhere.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_translation_key = "start_discharge_power_threshold"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_start_discharge_power_threshold"
        )
        self._attr_native_min_value = START_DISCHARGE_POWER_MIN
        self._attr_native_max_value = START_DISCHARGE_POWER_MAX
        self._attr_native_step = START_DISCHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "W"
        self._attr_icon = "mdi:transmission-tower-import"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (StartDischargePowerNumber, StartChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current threshold in watts.

        Local register caches (LOCAL mode, HYBRID with an attached
        transport) hold the raw watt value under pylxpweb's name-map key;
        cloud-populated caches hold the same watt value under the live cloud
        key. No scaling on either path.
        """
        if self._params_are_local_raw():
            return self._read_param_value(
                param_key=PARAM_HOLD_PTOUSER_START_DISCHARGE,
                value_min=START_DISCHARGE_POWER_MIN,
                value_max=START_DISCHARGE_POWER_MAX,
            )
        return self._read_param_value(
            param_key=PARAM_HOLD_P_TO_USER_START_DISCHG,
            value_min=START_DISCHARGE_POWER_MIN,
            value_max=START_DISCHARGE_POWER_MAX,
            inverter_dict_attr="parameters",
            inverter_dict_key=PARAM_HOLD_P_TO_USER_START_DISCHG,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the start-discharge threshold in watts."""
        int_value = int(value)
        if (
            int_value < START_DISCHARGE_POWER_MIN
            or int_value > START_DISCHARGE_POWER_MAX
        ):
            raise HomeAssistantError(
                f"Start discharge power threshold must be between "
                f"{START_DISCHARGE_POWER_MIN}-{START_DISCHARGE_POWER_MAX} W, "
                f"got {value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Start discharge power threshold must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_PTOUSER_START_DISCHARGE,
            local_value=int_value,
            # The named-param cloud writer is BOTH the cloud-mode path and
            # the HYBRID local-failure fallback; pylxpweb's
            # set_start_discharge_power is deliberately bypassed (see
            # _write_cloud_named_parameter).
            cloud_write=lambda: self._write_cloud_named_parameter(int_value),
            label=f"start discharge power threshold to {int_value} W",
        )

    async def _write_cloud_named_parameter(self, watts: int) -> None:
        """Write the threshold via the generic cloud named-parameter API.

        The website's own call (reporter-verified in the GH #272 browser
        console): remoteSet/write with holdParam HOLD_P_TO_USER_START_DISCHG
        and the watt value as text. pylxpweb's ``set_start_discharge_power``
        is deliberately NOT used for cloud writes — its cloud leg writes the
        raw register by address, and its cloud read leg looks up the wrong
        key (the guessed HOLD_PTOUSER_START_DISCHARGE never exists on the
        server), so the named-param call is the only website-verified path.

        Bare writer: logging, ineffective-regime warning, optimistic state
        and the related-entity refresh are provided by ``_write_parameter``.
        """
        client = self.coordinator.require_client()
        result = await client.api.control.write_parameter(
            self.serial,
            PARAM_HOLD_P_TO_USER_START_DISCHG,
            str(watts),
        )
        if not result.success:
            raise HomeAssistantError(
                f"Failed to set start discharge power threshold to {watts} W"
            )
        await self.coordinator.refresh_inverter_params_if_linked(self.serial)


class StartChargePowerNumber(EG4BaseNumberEntity):
    """Start Charge P_import threshold (HOLD 117, SIGNED whole watts, GH #272).

    LXP-protocol ``PtoUserStartchg``: starts charging once grid import
    (P_to_user) drops below this wattage — signed, protocol default -50 W
    (i.e. once exporting more than 50 W). Documentation-only register the
    GH #272 reporter asked for to enable field testing: it is absent from
    the Luxpower web UI AND from the cloud API (remoteRead names reg 117
    ``<EMPTY>`` on every scanned model, incl. LXP-EU), so this entity is
    LOCAL/HYBRID-only and ships disabled by default. Reads surface as the
    raw "117" key (read_named_parameters falls back to ``str(addr)`` for
    unmapped registers); writes go through the raw-register transport write
    with two's-complement masking.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_translation_key = "start_charge_power_threshold"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_start_charge_power_threshold"
        )
        self._attr_native_min_value = START_CHARGE_POWER_MIN
        self._attr_native_max_value = START_CHARGE_POWER_MAX
        self._attr_native_step = START_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "W"
        self._attr_icon = "mdi:battery-arrow-up"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (StartDischargePowerNumber, StartChargePowerNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current threshold in watts (signed decode)."""
        return self._read_param_value(
            param_key=PARAM_RAW_PTOUSER_START_CHARGE,
            value_min=START_CHARGE_POWER_MIN,
            value_max=START_CHARGE_POWER_MAX,
            param_transform=_signed_from_register,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the start-charge threshold in watts (raw register write)."""
        int_value = int(value)
        if int_value < START_CHARGE_POWER_MIN or int_value > START_CHARGE_POWER_MAX:
            raise HomeAssistantError(
                f"Start charge power threshold must be between "
                f"{START_CHARGE_POWER_MIN}-{START_CHARGE_POWER_MAX} W, got {value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Start charge power threshold must be an integer value, got {value}"
            )
        if not self.coordinator.has_local_transport(self.serial):
            raise HomeAssistantError(
                "Start charge power threshold (register 117) requires a local "
                "Modbus/dongle connection — the cloud API has no parameter "
                "name for this register."
            )
        _LOGGER.info(
            "Setting start charge power threshold for %s to %d W",
            self.serial,
            int_value,
        )
        self._warn_if_ineffective()
        with optimistic_value_context(self, float(int_value)):
            # Two's-complement mask: -50 W writes 65486.
            await self.coordinator.write_raw_parameter(
                REG_PTOUSER_START_CHARGE, int_value & 0xFFFF, serial=self.serial
            )
            await asyncio.sleep(0.5)
            await self._refresh_related_entities()


class ForcedDischargePowerNumber(EG4BaseNumberEntity):
    """Number entity for Forced Discharge Power control (reg 82, kW).

    Discharge power level used while forced discharge
    (``FUNC_FORCED_DISCHG_EN``) is active. The register stores 100W units
    (0-255 = 0-25.5 kW) — the reg-74/66 encoding, hardware-verified in
    PR #249 (panel 2.5 kW reads raw 25); the cloud takes float kW
    directly. A power level rather than a stop limit, so deliberately
    NOT regime-gated (GH #207).
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Forced Discharge Power"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_forced_discharge_power"
        )
        self._attr_native_min_value = FORCED_DISCHARGE_POWER_MIN
        self._attr_native_max_value = FORCED_DISCHARGE_POWER_MAX
        self._attr_native_step = FORCED_DISCHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-arrow-down"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (
            ForcedDischargePowerNumber,
            ForcedDischargeSOCLimitNumber,
            StopDischargeVoltageNumber,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current forced discharge power in kW.

        With a local transport the coordinator parameter cache holds the
        raw 100W register value (scaled ÷10 here). The pylxpweb property
        is deliberately NOT consulted then: in HYBRID mode
        ``inverter.parameters`` is populated from the same local transport,
        so the property would surface the raw value (25) as kW (25.0) and
        pass the 25.5 bound — a 10x display/write-back hazard. Cloud-only
        installs read the property, which returns cloud-scaled kW.
        """
        if self._params_are_local_raw():
            return self._read_param_value(
                param_key=PARAM_HOLD_FORCED_DISCHG_POWER,
                value_min=0,
                value_max=25.5,
                as_float=True,
                param_transform=lambda v: float(v) / 10.0,
            )
        return self._read_param_value(
            param_key=PARAM_HOLD_FORCED_DISCHG_POWER,
            value_min=0,
            value_max=25.5,
            inverter_attr="forced_discharge_power",
            as_float=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the forced discharge power (kW -> reg 82 in 100W units)."""
        if value < 0.0 or value > 25.5:
            raise HomeAssistantError(
                f"Forced discharge power must be between 0.0-25.5 kW, got {value}"
            )
        # Cloud setter ships with pylxpweb > 0.9.36b3 — fail with a clear
        # message instead of an AttributeError if the installed library
        # predates it (the manifest bump lands with the next release).
        inverter = self.coordinator.get_inverter_object(self.serial)
        if (
            not self.coordinator.has_local_transport(self.serial)
            and inverter is not None
            and not hasattr(inverter, "set_forced_discharge_power")
        ):
            raise HomeAssistantError(
                "Forced discharge power requires a newer pylxpweb "
                "(set_forced_discharge_power missing) — update and reload"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_FORCED_DISCHG_POWER,
            local_value=int(round(value * 10)),
            cloud_method="set_forced_discharge_power",
            cloud_kwargs={"power_kw": value},
            label=f"forced discharge power to {value:.1f} kW",
        )


class ForcedDischargeSOCLimitNumber(EG4BaseNumberEntity):
    """Number entity for Forced Discharge SOC Limit control (reg 83, %).

    Forced discharge stops when the battery reaches this SOC. An SOC-regime
    stop limit, so it participates in the reg-179 regime gating like the
    on/off-grid SOC cutoffs (GH #207 / PR #249).
    """

    _control_key = "forced_discharge_soc_limit"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Forced Discharge SOC Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_forced_discharge_soc_limit"
        )
        self._attr_native_min_value = FORCED_DISCHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = FORCED_DISCHARGE_SOC_LIMIT_MAX
        self._attr_native_step = FORCED_DISCHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-20"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (
            ForcedDischargePowerNumber,
            ForcedDischargeSOCLimitNumber,
            StopDischargeVoltageNumber,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current forced discharge SOC limit."""
        return self._read_param_value(
            param_key=PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT,
            value_min=0,
            value_max=100,
            inverter_attr="forced_discharge_soc_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the forced discharge SOC limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"Forced discharge SOC limit must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Forced discharge SOC limit must be an integer value, got {value}"
            )
        # Cloud setter ships with pylxpweb > 0.9.36b3 — see the power
        # entity above for rationale.
        inverter = self.coordinator.get_inverter_object(self.serial)
        if (
            not self.coordinator.has_local_transport(self.serial)
            and inverter is not None
            and not hasattr(inverter, "set_forced_discharge_soc_limit")
        ):
            raise HomeAssistantError(
                "Forced discharge SOC limit requires a newer pylxpweb "
                "(set_forced_discharge_soc_limit missing) — update and reload"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_FORCED_DISCHG_SOC_LIMIT,
            cloud_method="set_forced_discharge_soc_limit",
            cloud_kwargs={"soc_percent": int_value},
            label=f"forced discharge SOC limit to {int_value}%",
        )


class StopDischargeVoltageNumber(EG4BaseNumberEntity):
    """Number entity for the forced-discharge Stop Discharge Voltage (reg 202).

    Forced discharge stops when the battery voltage drops to this level —
    the voltage-regime counterpart of ForcedDischargeSOCLimitNumber (the
    cloud maintain UI gates "Stop Discharge Volt 1(V)" with
    disChgVoltEnable), so it participates in the reg-179 discharge regime
    gating. Register 202 stores decivolts (raw 400 == 40.0 V, raw-verified
    2026-06-11); the cloud accepts float volts in [40, 56] (live round-trip
    40 -> 41.5 -> 40 V on an 18kPV and a FlexBOSS21). Bead eg4-aa3t.
    """

    _control_key = "stop_discharge_voltage"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Stop Discharge Voltage"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_stop_discharge_voltage"
        )
        self._attr_native_min_value = STOP_DISCHARGE_VOLTAGE_MIN
        self._attr_native_max_value = STOP_DISCHARGE_VOLTAGE_MAX
        self._attr_native_step = STOP_DISCHARGE_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-arrow-down-outline"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (
            ForcedDischargePowerNumber,
            ForcedDischargeSOCLimitNumber,
            StopDischargeVoltageNumber,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current stop discharge voltage (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_STOP_DISCHARGE_VOLTAGE,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the stop discharge voltage (V → reg 202 decivolts locally)."""
        # Normalize to the entity's 0.1 V precision first so the local
        # (decivolt) and cloud (float-volt string) paths always carry the
        # same value, and boundary float artifacts from service-call
        # arithmetic (56.0000001) are accepted (codex r1 LOW). The
        # non-negated chained comparison also rejects NaN.
        value = round(value, 1)
        if not STOP_DISCHARGE_VOLTAGE_MIN <= value <= STOP_DISCHARGE_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"Stop discharge voltage must be between "
                f"{STOP_DISCHARGE_VOLTAGE_MIN}-{STOP_DISCHARGE_VOLTAGE_MAX} V, "
                f"got {value}"
            )
        # Cloud setter ships with pylxpweb > 0.9.36b5 — fail with a clear
        # message instead of an AttributeError if the installed library
        # predates it (see ForcedDischargePowerNumber for rationale).
        inverter = self.coordinator.get_inverter_object(self.serial)
        if (
            not self.coordinator.has_local_transport(self.serial)
            and inverter is not None
            and not hasattr(inverter, "set_stop_discharge_voltage")
        ):
            raise HomeAssistantError(
                "Stop discharge voltage requires a newer pylxpweb "
                "(set_stop_discharge_voltage missing) — update and reload"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_STOP_DISCHARGE_VOLTAGE,
            local_value=int(round(value * 10)),
            cloud_method="set_stop_discharge_voltage",
            cloud_kwargs={"voltage": value},
            label=f"stop discharge voltage to {value:.1f} V",
        )


class OnGridSOCCutoffNumber(EG4BaseNumberEntity):
    """Number entity for On-Grid SOC Cut-Off control."""

    _control_key = "on_grid_soc_cutoff"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "On-Grid SOC Cut-Off"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_on_grid_soc_cutoff"
        )
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current on-grid SOC cutoff (reads from battery_soc_limits dict)."""
        return self._read_param_value(
            param_key="HOLD_DISCHG_CUT_OFF_SOC_EOD",
            value_min=0,
            value_max=100,
            inverter_dict_attr="battery_soc_limits",
            inverter_dict_key="on_grid_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid SOC cutoff."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"On-grid SOC cutoff must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_ONGRID_DISCHG_SOC,
            cloud_method="set_battery_soc_limits",
            cloud_kwargs={"on_grid_limit": int_value},
            label=f"on-grid SOC cutoff to {int_value}%",
        )


class OffGridSOCCutoffNumber(EG4BaseNumberEntity):
    """Number entity for Off-Grid SOC Cut-Off control."""

    _control_key = "off_grid_soc_cutoff"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Off-Grid SOC Cut-Off"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_off_grid_soc_cutoff"
        )
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeSOCLimitNumber, OnGridSOCCutoffNumber, OffGridSOCCutoffNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current off-grid SOC cutoff (reads from battery_soc_limits dict)."""
        return self._read_param_value(
            param_key="HOLD_SOC_LOW_LIMIT_EPS_DISCHG",
            value_min=0,
            value_max=100,
            inverter_dict_attr="battery_soc_limits",
            inverter_dict_key="off_grid_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid SOC cutoff."""
        int_value = int(value)
        if int_value < 0 or int_value > 100:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be between 0-100%, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Off-grid SOC cutoff must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_OFFGRID_DISCHG_SOC,
            cloud_method="set_battery_soc_limits",
            cloud_kwargs={"off_grid_limit": int_value},
            label=f"off-grid SOC cutoff to {int_value}%",
        )


class BatteryChargeCurrentNumber(EG4BaseNumberEntity):
    """Number entity for Battery Charge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Battery Charge Current"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_battery_charge_current"
        )
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-plus"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current battery charge current limit."""
        return self._read_param_value(
            param_key="HOLD_LEAD_ACID_CHARGE_RATE",
            value_min=0,
            value_max=250,
            inverter_attr="battery_charge_current_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery charge current limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery charge current must be between 0-250 A, got {int_value}"
            )
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"Battery charge current must be an integer value, got {value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_CHARGE_CURRENT,
            cloud_method="set_battery_charge_current",
            cloud_kwargs={"current_amps": int_value},
            label=f"battery charge current to {int_value} A",
        )


class BatteryDischargeCurrentNumber(EG4BaseNumberEntity):
    """Number entity for Battery Discharge Current control."""

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Battery Discharge Current"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_battery_discharge_current"
        )
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-minus"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (BatteryChargeCurrentNumber, BatteryDischargeCurrentNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current battery discharge current limit."""
        return self._read_param_value(
            param_key="HOLD_LEAD_ACID_DISCHARGE_RATE",
            value_min=0,
            value_max=250,
            inverter_attr="battery_discharge_current_limit",
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery discharge current limit."""
        int_value = int(value)
        if int_value < 0 or int_value > 250:
            raise HomeAssistantError(
                f"Battery discharge current must be between 0-250 A, got {int_value}"
            )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_DISCHARGE_CURRENT,
            cloud_method="set_battery_discharge_current",
            cloud_kwargs={"current_amps": int_value},
            label=f"battery discharge current to {int_value} A",
        )


# ── Voltage limit controls (open-loop / Voltage control mode) ─────────────────
# Twins of the SOC limit controls above. These are the registers the inverter
# honors when battery charge/discharge control is in Voltage mode (reg 179
# bits 9/10 = 1). They are gated/disabled-by-default by control mode and warn
# when set while the inverter is in SOC mode.


class SystemChargeVoltLimitNumber(EG4BaseNumberEntity):
    """Number entity for System Charge Voltage Limit control (register 228)."""

    _control_key = "system_charge_volt_limit"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "System Charge Voltage Limit"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_system_charge_volt_limit"
        )
        self._attr_native_min_value = SYSTEM_CHARGE_VOLT_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_VOLT_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_VOLT_LIMIT_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (SystemChargeVoltLimitNumber,)

    @property
    def native_value(self) -> float | None:
        """Return the current system charge voltage limit (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the system charge voltage limit."""
        if value < SYSTEM_CHARGE_VOLT_LIMIT_MIN or value > SYSTEM_CHARGE_VOLT_LIMIT_MAX:
            raise HomeAssistantError(
                f"System charge voltage limit must be between "
                f"{SYSTEM_CHARGE_VOLT_LIMIT_MIN}-{SYSTEM_CHARGE_VOLT_LIMIT_MAX} V, "
                f"got {value}"
            )
        await self._write_voltage_register(
            value=value,
            param_name=PARAM_HOLD_SYSTEM_CHARGE_VOLT_LIMIT,
            register=REG_SYSTEM_CHARGE_VOLT_LIMIT,
            label="System Charge Voltage Limit",
        )


class OnGridCutoffVoltageNumber(EG4BaseNumberEntity):
    """Number entity for On-Grid discharge Cut-Off Voltage control (register 169)."""

    _control_key = "on_grid_cutoff_voltage"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "On-Grid Cut-Off Voltage"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_on_grid_cutoff_voltage"
        )
        self._attr_native_min_value = CUTOFF_VOLTAGE_MIN
        self._attr_native_max_value = CUTOFF_VOLTAGE_MAX
        self._attr_native_step = CUTOFF_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (OnGridCutoffVoltageNumber, OffGridCutoffVoltageNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current on-grid cutoff voltage (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_ONGRID_EOD_VOLTAGE,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-grid cutoff voltage."""
        if value < CUTOFF_VOLTAGE_MIN or value > CUTOFF_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"On-grid cutoff voltage must be between "
                f"{CUTOFF_VOLTAGE_MIN}-{CUTOFF_VOLTAGE_MAX} V, got {value}"
            )
        await self._write_voltage_register(
            value=value,
            param_name=PARAM_HOLD_ONGRID_EOD_VOLTAGE,
            register=REG_ONGRID_EOD_VOLTAGE,
            label="On-Grid Cut-Off Voltage",
        )


class OffGridCutoffVoltageNumber(EG4BaseNumberEntity):
    """Number entity for Off-Grid discharge Cut-Off Voltage control (register 100)."""

    _control_key = "off_grid_cutoff_voltage"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Off-Grid Cut-Off Voltage"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_off_grid_cutoff_voltage"
        )
        self._attr_native_min_value = CUTOFF_VOLTAGE_MIN
        self._attr_native_max_value = CUTOFF_VOLTAGE_MAX
        self._attr_native_step = CUTOFF_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 1

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (OnGridCutoffVoltageNumber, OffGridCutoffVoltageNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current off-grid cutoff voltage (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the off-grid cutoff voltage."""
        if value < CUTOFF_VOLTAGE_MIN or value > CUTOFF_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"Off-grid cutoff voltage must be between "
                f"{CUTOFF_VOLTAGE_MIN}-{CUTOFF_VOLTAGE_MAX} V, got {value}"
            )
        await self._write_voltage_register(
            value=value,
            param_name=PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
            register=REG_OFFGRID_EOD_VOLTAGE,
            label="Off-Grid Cut-Off Voltage",
        )


class ACChargeStartVoltageNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge Start Voltage control (register 158).

    Whole-volt values only (firmware rejects fractional volts).
    """

    _control_key = "ac_charge_start_voltage"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge Start Voltage"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_start_voltage"
        )
        self._attr_native_min_value = AC_CHARGE_VOLTAGE_MIN
        self._attr_native_max_value = AC_CHARGE_VOLTAGE_MAX
        self._attr_native_step = AC_CHARGE_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-charging-low"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeStartVoltageNumber, ACChargeEndVoltageNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge start voltage (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge start voltage (whole volts only)."""
        int_value = int(value)
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge start voltage must be a whole number of volts, got {value}"
            )
        if int_value < AC_CHARGE_VOLTAGE_MIN or int_value > AC_CHARGE_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"AC charge start voltage must be between "
                f"{AC_CHARGE_VOLTAGE_MIN}-{AC_CHARGE_VOLTAGE_MAX} V, got {int_value}"
            )
        await self._write_voltage_register(
            value=float(int_value),
            param_name=PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
            register=REG_AC_CHARGE_START_VOLTAGE,
            label="AC Charge Start Voltage",
        )


class ACChargeEndVoltageNumber(EG4BaseNumberEntity):
    """Number entity for AC Charge End Voltage control (register 159).

    Whole-volt values only (firmware rejects fractional volts).
    """

    _control_key = "ac_charge_end_voltage"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge End Voltage"
        self._attr_unique_id = (
            f"{self._clean_model}_{serial.lower()}_ac_charge_end_voltage"
        )
        self._attr_native_min_value = AC_CHARGE_VOLTAGE_MIN
        self._attr_native_max_value = AC_CHARGE_VOLTAGE_MAX
        self._attr_native_step = AC_CHARGE_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_native_precision = 0

    def _get_related_entity_types(self) -> tuple[type, ...]:
        return (ACChargeStartVoltageNumber, ACChargeEndVoltageNumber)

    @property
    def native_value(self) -> float | None:
        """Return the current AC charge end voltage (decivolts → V)."""
        return self._read_param_value(
            param_key=PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
            value_min=20,
            value_max=70,
            as_float=True,
            param_transform=self._volts_from_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the AC charge end voltage (whole volts only)."""
        int_value = int(value)
        if abs(value - int_value) > 0.01:
            raise HomeAssistantError(
                f"AC charge end voltage must be a whole number of volts, got {value}"
            )
        if int_value < AC_CHARGE_VOLTAGE_MIN or int_value > AC_CHARGE_VOLTAGE_MAX:
            raise HomeAssistantError(
                f"AC charge end voltage must be between "
                f"{AC_CHARGE_VOLTAGE_MIN}-{AC_CHARGE_VOLTAGE_MAX} V, got {int_value}"
            )
        await self._write_voltage_register(
            value=float(int_value),
            param_name=PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
            register=REG_AC_CHARGE_END_VOLTAGE,
            label="AC Charge End Voltage",
        )
