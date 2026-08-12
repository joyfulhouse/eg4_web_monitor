"""Number platform for EG4 Web Monitor integration."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
    ATTR_QC_START_PREFERENCE,
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
    REG_START_PV_VOLT,
    AC_CHARGE_BATTERY_SOC_MAX,
    AC_CHARGE_BATTERY_SOC_MIN,
    AC_CHARGE_BATTERY_SOC_STEP,
    AC_CHARGE_START_BATTERY_SOC_MAX,
    AC_COUPLE_END_SOC_DISABLED_SENTINEL,
    AC_COUPLE_SOC_MAX,
    AC_COUPLE_SOC_MIN,
    AC_COUPLE_SOC_STEP,
    AC_CHARGE_SOC_LIMIT_MAX,
    AC_CHARGE_SOC_LIMIT_MIN,
    AC_CHARGE_SOC_LIMIT_STEP,
    REG_OFFGRID_EOD_VOLTAGE,
    REG_ONGRID_EOD_VOLTAGE,
    REG_PTOUSER_START_CHARGE,
    REG_SYSTEM_CHARGE_VOLT_LIMIT,
    SMART_LOAD_PV_POWER_MAX,
    SMART_LOAD_PV_POWER_MIN,
    SMART_LOAD_PV_POWER_STEP,
    SMART_LOAD_SOC_MAX,
    SMART_LOAD_SOC_MIN,
    SMART_LOAD_SOC_STEP,
    SMART_LOAD_VOLT_MAX,
    SMART_LOAD_VOLT_MIN,
    SMART_LOAD_VOLT_STEP,
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
from .control_discovery import setup_control_entity_discovery
from .utils import (
    async_write_with_cloud_fallback,
    flag_offgrid_control_suppression,
    is_hybrid_family,
    is_offgrid_family,
    is_supported_control_model,
    supports_grid_sellback,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


def _coerce_int_in_range(
    value: float,
    *,
    min_v: int | float,
    max_v: int | float,
    label: str,
    unit: str = "%",
    require_integer: bool = False,
) -> int:
    """Coerce ``value`` to int, validating range (and optionally integer-ness)."""
    int_value = int(value)
    if int_value < min_v or int_value > max_v:
        raise HomeAssistantError(
            f"{label} must be between {min_v}-{max_v}{unit}, got {int_value}"
        )
    if require_integer and abs(value - int_value) > 0.01:
        raise HomeAssistantError(f"{label} must be an integer value, got {value}")
    return int_value


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
        """Register the retention-aware coordinator callback."""
        await super().async_added_to_hass()

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

    @property
    def _device_data(self) -> dict[str, Any]:
        """Device data dictionary for this entity's inverter (empty when absent)."""
        data = self.coordinator.data or {}
        devices = data.get("devices") or {}
        device: dict[str, Any] = devices.get(self.serial) or {}
        return device

    def _offgrid_cloud_only_reason(self, register: int, label: str) -> str | None:
        """Cloud-only routing reason for hardware-unverified off-grid writes.

        Returns a non-None reason exactly when this entity's device is
        positively identified as EG4_OFFGRID (family gate, never model
        substrings). Passed to ``_write_parameter`` /
        ``_write_voltage_register`` it disables the local write path: local
        Modbus writes to the AC-charge window registers — SOC 160/161 (all
        #331 write evidence is the cloud holdParam path) and voltage 158/159
        (the only write evidence is a cloud-path delta-test, graded
        ``portal-correlated`` with the target family unrecorded) — are
        hardware-UNVERIFIED on the off-grid family, and a post-write
        readback is structurally incapable of catching a wrong
        name→register mapping there, because a wrong-but-writable register
        is firmware-ACKed and reads back exactly the value written (#476,
        #558). Matching the #471/#472 precedent for unpinned writes, the
        write routes through the cloud until a local write is
        hardware-confirmed; on a pure-LOCAL install the returned reason is
        raised instead of silently writing an unverified register.
        """
        if not is_offgrid_family(self._device_data):
            return None
        return (
            f"Cannot set {label}: local Modbus writes to register {register} "
            "are not hardware-verified on this inverter family, so this "
            "control writes through the EG4 cloud API only (issue #558) — "
            "add cloud credentials to this integration entry to use it"
        )

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

    def _cache_state(self) -> float | None:
        """Return ``native_value`` as decoded from coordinator data.

        The retention hook of :class:`EG4OptimisticEntity`: masks the
        optimistic value so ``native_value`` falls through to the parameter
        cache / inverter object (every read path prefers the optimistic
        value when set). Synchronous — the mask never spans an await point.
        """
        saved = self._optimistic_value
        self._optimistic_value = None
        try:
            return self.native_value
        finally:
            self._optimistic_value = saved

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
        local_write_blocked_reason: str | None = None,
    ) -> None:
        """Write parameter via local transport or cloud API with optimistic context.

        The local write is attempted first when a transport is attached; on
        failure (or a known-down link) it falls back to the cloud path when a
        cloud client exists — HYBRID parity with the switch platform's
        ``_execute_local_with_fallback``. ``cloud_write`` overrides the
        default inverter-method cloud path for entities whose verified cloud
        route is a direct named-parameter write.

        ``local_write_blocked_reason`` routes the write CLOUD-ONLY: the local
        path is never attempted (see
        :func:`~.utils.async_write_with_cloud_fallback`), and without a cloud
        client the given reason is raised as a ``HomeAssistantError`` instead
        of an unverified local register write (#558).
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

        with optimistic_value_context(self, value, label) as write:
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                label,
                local_write=_local_write,
                cloud_write=cloud_write
                or (_cloud_via_method if cloud_method else None),
                local_values={local_param: write_val},
                local_write_blocked_reason=local_write_blocked_reason,
            )
            write.refresh_ok = await self._refresh_related_entities()

    async def _write_voltage_register(
        self,
        *,
        value: float,
        param_name: str,
        register: int,
        label: str,
        cloud_write: Callable[[], Awaitable[None]] | None = None,
        local_write_blocked_reason: str | None = None,
    ) -> None:
        """Write a decivolt voltage register (local by name, cloud by raw register).

        Voltage limit registers store decivolts (V × 10). The local path writes
        the named parameter via the transport's name map; the cloud path writes
        the raw register address directly (avoiding read/write name aliasing).
        In HYBRID mode a failed local write falls back to the cloud path.
        ``cloud_write`` overrides the raw-register cloud path for parameters
        whose verified cloud route differs (e.g. named volts writes).

        ``local_write_blocked_reason`` routes the write CLOUD-ONLY, exactly as
        on :meth:`_write_parameter` — the local path is never attempted, and
        without a cloud client the given reason is raised instead of an
        unverified local register write (#558).
        """
        raw_value = int(round(value * 10))
        _LOGGER.info("Setting %s for %s to %.1f V", label, self.serial, value)
        self._warn_if_ineffective()

        async def _local_write() -> None:
            await self.coordinator.write_named_parameter(
                param_name, raw_value, serial=self.serial
            )
            await asyncio.sleep(0.5)

        async def _cloud_write_raw_register() -> None:
            client = self.coordinator.require_client()
            result = await client.api.control.write_parameters(
                self.serial, {register: raw_value}
            )
            if not result.success:
                raise HomeAssistantError(f"Failed to set {label}")

        with optimistic_value_context(self, value, label) as write:
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                label,
                local_write=_local_write,
                cloud_write=cloud_write or _cloud_write_raw_register,
                local_values={param_name: raw_value},
                local_write_blocked_reason=local_write_blocked_reason,
            )
            write.refresh_ok = await self._refresh_related_entities()

    async def _refresh_related_entities(self) -> bool:
        """Refresh and publish parameters for only this entity's inverter.

        Returns:
            True when this device's parameter refresh completed; False when
            it failed or this method raised. Errors are logged, never raised
            (#362/#379): a post-write caller must be able to
            tell "write+refresh ok" from "write ok, refresh failed" — the old
            swallow-and-return-None contract made a failed refresh look
            identical to success, so the number entity cleared its optimistic
            value onto the stale pre-write cache value and visibly reverted a
            write the device had acknowledged.
        """
        try:
            return await self.coordinator.async_refresh_device_parameters(self.serial)
        except Exception as e:
            _LOGGER.error("Failed to refresh parameters for %s: %s", self.serial, e)
            return False


# ── Platform setup ───────────────────────────────────────────────────


def _create_number_entities(
    hass: HomeAssistant,
    coordinator: EG4DataUpdateCoordinator,
) -> list[EG4BaseNumberEntity]:
    """Build controls applicable to the coordinator's current capabilities."""
    entities: list[EG4BaseNumberEntity] = []

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

                # AC Couple Start/End SOC (GH #352): CLOUD-ONLY holdParams
                # (_12K_HOLD_AC_COUPLE_{START,END}_SOC) with no pinned local
                # register, so the entities only exist where a cloud client
                # can read and write them (CLOUD/HYBRID); pure-LOCAL can
                # never see the params. NOT family-gated: the evidence spans
                # families — the off-grid reporter's 12000XP v2 AND
                # grid-tied hardware (factory END=255/START=100 pairs on
                # 12KPV/FlexBOSS18/21 dumps; ivanfmartinez runs live 90/95
                # AC-couple thresholds on an on-grid hybrid LXP, issue #352).
                # Devices that truly lack the params read None from the
                # cloud getter and the entities go unavailable instead.
                if coordinator.has_http_api():
                    entities.extend(
                        [
                            ACCoupleStartSOCNumber(coordinator, serial),
                            ACCoupleEndSOCNumber(coordinator, serial),
                        ]
                    )

                # Smart Load panel (GH #499): the same cloud-only arrangement
                # — five holdParams with no pinned local register, so the
                # entities exist only where a cloud client can read and write
                # them. NOT family-gated: the params answered on an 18kPV and
                # a FlexBOSS21 in the maintainer's own plant and the reporter
                # runs them on a 12000XP (EG4_OFFGRID). An INVERTER whose read
                # omits them reads None and goes unavailable — this block is
                # inverter-only, so a GridBOSS never reaches it at all.
                if coordinator.has_http_api():
                    entities.extend(
                        SmartLoadNumber(coordinator, serial, spec)
                        for spec in SMART_LOAD_NUMBER_SPECS
                    )

                # Grid-tied-only controls (Peak Shaving / Forced Discharge)
                # act on grid-parallel export/import blending; the
                # EG4_OFFGRID (SNA) platform has no sellback and no
                # grid-parallel operation, so they are inert there.
                # Suppressed per the PR #220 / issue #197 adjudication
                # (eg4-juzg); mirrors GRID_TIED_ONLY_WORKING_MODE_PARAMS in
                # switch.py.
                offgrid = is_offgrid_family(device_data)
                if offgrid:
                    # Suffix-based probe matches current stable IDs and legacy
                    # model-prefixed IDs from a misdetected-model era (e.g.
                    # "unknown", #219/#222). All variants end in
                    # {serial}_{key}.
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
                    # Reg 160 (AC Charge Start Battery SOC) is live on
                    # EG4_HYBRID too, not just EG4_OFFGRID: on a FlexBOSS21
                    # (fw FAAB-2727) it starts AC charging whenever battery
                    # SOC is below it — in or out of the AC-charge time
                    # windows and regardless of the reg-120 ACChargeType
                    # selector — and the portal exposes it for the family
                    # as "Start AC Charge SOC(%)". Hidden from HA, it
                    # silently overrides any charge schedule (its factory
                    # 90 kept a ToU battery pinned high around the clock).
                    # Gated on is_hybrid_family() — fails CLOSED, the
                    # convention for capabilities verified on hybrid
                    # hardware (the schedule families in time.py) — because
                    # the evidence is one EG4_HYBRID unit; LXP and
                    # unidentified hardware are excluded until verified.
                    # Reg 161 (End) is NOT created here: pylxpweb models
                    # the grid-tied stop as reg 67 (set_ac_charge_soc_limits
                    # pairs 160 with 67), and the #332 note records reg 161
                    # as read-only on grid-tied hardware.
                    if is_hybrid_family(device_data):
                        entities.append(
                            ACChargeStartBatterySOCNumber(coordinator, serial)
                        )

                entities.extend(
                    [
                        # Always-on controls (power, current)
                        ACChargePowerNumber(coordinator, serial),
                        PVChargePowerNumber(coordinator, serial),
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
                        *[
                            EG4VoltageNumber(coordinator, serial, spec)
                            for spec in VOLTAGE_NUMBER_SPECS
                        ],
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

    return entities


def _number_route_signature(coordinator: EG4DataUpdateCoordinator) -> object:
    """Return transport state that can change the number candidate set."""
    serials = (coordinator.data or {}).get("devices", {})
    return (
        bool(coordinator.has_http_api()),
        bool(coordinator.is_local_only()),
        tuple(
            sorted(
                (
                    str(serial),
                    bool(coordinator.has_configured_local_transport(serial)),
                    bool(coordinator.has_local_register_path(serial)),
                )
                for serial in serials
            )
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up and continuously converge EG4 number entities."""
    coordinator = config_entry.runtime_data
    setup_control_entity_discovery(
        hass,
        config_entry,
        coordinator,
        async_add_entities,
        lambda: _create_number_entities(hass, coordinator),
        platform="number",
        extra_signature=lambda: _number_route_signature(coordinator),
        migrate_model_prefix=True,
    )


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
        self._attr_unique_id = self._stable_control_unique_id("system_charge_soc_limit")
        self._attr_native_min_value = SYSTEM_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 0

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

        label = f"system charge SOC limit to {int_value}%"
        with optimistic_value_context(self, value, label) as write:
            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                label,
                local_write=_local_write,
                cloud_write=_cloud_write,
                local_values={PARAM_HOLD_SYSTEM_CHARGE_SOC_LIMIT: int_value},
            )
            write.refresh_ok = await self._refresh_related_entities()


class QuickChargeDurationNumber(RestoreNumber, EG4BaseNumberEntity):
    """Number entity for the Quick Charge duration (start preference + live reg 234).

    While a charge is RUNNING on LOCAL/HYBRID the entity mirrors holding
    register 234 — the live remaining-minutes countdown — and setting it
    writes reg 234 to extend/reduce the running charge (e.g. to keep cells
    balancing).

    While IDLE (and always on CLOUD, which has no such register) the entity
    shows the per-serial start preference (stored on the coordinator,
    restored across restarts via RestoreNumber), and setting it stores that
    preference. The Quick Charge switch applies it when starting: as the
    cloud ``minute`` parameter, or on LOCAL/HYBRID as the reg 234 value
    written together with the reg 233 activation in one contiguous frame
    (pylxpweb 0.9.38b3 paired-frame start, live-validated on FlexBOSS21
    2026-07-12 — reg 234 alone is firmware-rejected while idle, #251).
    Gated identically to the Quick Charge switch.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the Quick Charge Duration number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "Quick Charge Duration"
        self._attr_unique_id = self._stable_control_unique_id("quick_charge_duration")
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the start preference independently of the displayed value.

        The entity's state is multiplexed (live reg 234 countdown while a
        charge runs, start preference otherwise), so restoring from the
        state alone would turn a mid-charge restart's countdown reading
        into the next start's duration. This attribute always carries the
        real preference, and restore reads it in favour of the state.
        """
        return {
            ATTR_QC_START_PREFERENCE: self.coordinator._quick_charge_minutes.get(
                self.serial, QUICK_CHARGE_DURATION_DEFAULT
            )
        }

    def _seed_restored_preference(self, native_value: float | None) -> None:
        """Seed the coordinator from a restored value when it is valid.

        The restored value must pass the same finite/integer/bounds checks
        as a live set; invalid restored data is ignored rather than raising,
        so a corrupt restore can never break setup.
        """
        if native_value is None or not self._is_valid_duration(native_value):
            return
        self.coordinator._quick_charge_minutes[self.serial] = int(native_value)

    async def async_added_to_hass(self) -> None:
        """Restore the saved duration preference, then wire up the listener.

        The ``start_preference`` attribute is the preference's own
        persistence channel, immune to the state's mid-charge countdown
        multiplexing. The state value is only used as a legacy fallback for
        restores saved by versions without the attribute (one restart
        window on upgrade; a mid-charge legacy restore can seed the
        countdown reading, which the user re-sets once).
        """
        await super().async_added_to_hass()
        # Only restore when the coordinator doesn't already hold a value for
        # this serial (e.g. set during this session).
        if self.serial in self.coordinator._quick_charge_minutes:
            return
        restored: float | None = None
        last_state = await self.async_get_last_state()
        if last_state is not None:
            attr = last_state.attributes.get(ATTR_QC_START_PREFERENCE)
            if isinstance(attr, (int, float)) and not isinstance(attr, bool):
                restored = float(attr)
        if restored is None:
            last_data = await self.async_get_last_number_data()
            restored = getattr(last_data, "native_value", None)
        self._seed_restored_preference(restored)

    @property
    def native_value(self) -> float | None:
        """Live reg 234 countdown while charging, else the start preference.

        While a charge is running on LOCAL/HYBRID the coordinator surfaces
        the raw holding register 234 value (minutes) as ``quickChargeMinute``
        and the entity mirrors it — the firmware counts it down live. Idle
        (reg 234 reads 0 — the firmware zeroes it at session end) and on
        CLOUD (no such register) it shows the stored start preference
        (default 60) that the switch applies when starting a charge.
        """
        devices = (self.coordinator.data or {}).get("devices", {})
        status = devices.get(self.serial, {}).get("quick_charge_status")
        if isinstance(status, dict) and status.get("hasUnclosedQuickChargeTask"):
            register = status.get("quickChargeMinute")
            if register is not None:
                return int(register)
        return self.coordinator._quick_charge_minutes.get(
            self.serial, QUICK_CHARGE_DURATION_DEFAULT
        )

    async def async_set_native_value(self, value: float) -> None:
        """Adjust the running charge live, or store the start preference.

        On LOCAL/HYBRID the live state decides (a fresh enable-bit read, not
        the throttled cache — a stale-active cache must never trigger a reg
        234 write the firmware would reject right after auto-expiry):

        - active  -> write reg 234 (extends/reduces the running charge; the
          start preference is deliberately NOT touched — a live extension is
          a one-off adjustment, not a new default);
        - idle    -> store the start preference the switch applies at the
          next start (the reg 234 half of the paired-frame start; a lone
          idle reg 234 write is firmware-rejected, #251);
        - unknown -> raise (a live adjust that silently became a stored
          preference must never look like it changed the running charge).

        On CLOUD there is no register, so the value is stored as the
        per-serial preference applied as the ``minute`` start parameter.
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
            if active:
                await self.coordinator.write_named_parameter(
                    PARAM_SNA_QUICK_CHARGE_MINUTE, minutes, serial=self.serial
                )
                # Seed the throttled status cache so the state published
                # below reflects the accepted write: the quick-charge poll
                # can be up to 30s stale, and a stale-idle cache would make
                # native_value fall back to the untouched start preference
                # right after a successful live write. Seed unconditionally,
                # creating the status dict if a prior status read failed (left
                # it absent/None) — otherwise the entity would keep publishing
                # the untouched preference until the next successful poll.
                data = self.coordinator.data
                if data is not None:
                    device = data.setdefault("devices", {}).setdefault(self.serial, {})
                    status = device.get("quick_charge_status")
                    if not isinstance(status, dict):
                        status = device["quick_charge_status"] = {}
                    status["hasUnclosedQuickChargeTask"] = True
                    status["quickChargeMinute"] = minutes
                _LOGGER.debug(
                    "Quick Charge duration for %s set to %d min (live reg 234 write)",
                    self.serial,
                    minutes,
                )
            else:
                self.coordinator._quick_charge_minutes[self.serial] = minutes
                _LOGGER.debug(
                    "Quick Charge duration preference for %s stored as %d min "
                    "(idle — applied at the next start)",
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
        self._attr_unique_id = self._stable_control_unique_id("ac_charge_power")
        self._attr_native_min_value = AC_CHARGE_POWER_MIN
        self._attr_native_max_value = AC_CHARGE_POWER_MAX
        self._attr_native_step = AC_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 1

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
        self._attr_unique_id = self._stable_control_unique_id("pv_charge_power")
        self._attr_native_min_value = PV_CHARGE_POWER_MIN
        self._attr_native_max_value = PV_CHARGE_POWER_MAX
        self._attr_native_step = PV_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:solar-power"
        self._attr_native_precision = 0

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
        self._attr_unique_id = self._stable_control_unique_id("grid_peak_shaving_power")
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
        label = f"grid peak shaving power to {value:.1f} kW"
        with optimistic_value_context(self, value, label) as write:
            inverter = self._get_inverter_or_raise()
            success = await inverter.set_grid_peak_shaving_power(power_kw=value)
            if not success:
                raise HomeAssistantError(
                    f"Failed to set grid peak shaving power to {value:.1f} kW"
                )
            write.refresh_ok = await self._refresh_related_entities()


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
        self._attr_unique_id = self._stable_control_unique_id("ac_charge_soc_limit")
        self._attr_native_min_value = AC_CHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = AC_CHARGE_SOC_LIMIT_MAX
        self._attr_native_step = AC_CHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-medium"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=AC_CHARGE_SOC_LIMIT_MIN,
            max_v=AC_CHARGE_SOC_LIMIT_MAX,
            label="AC charge SOC limit",
            require_integer=True,
        )
        await self._write_parameter(
            value,
            local_param=PARAM_HOLD_AC_CHARGE_SOC_LIMIT,
            cloud_method="set_ac_charge_soc_limit",
            cloud_kwargs={"soc_percent": int_value},
            label=f"AC charge SOC limit to {int_value}%",
        )


class ACChargeStartBatterySOCNumber(EG4BaseNumberEntity):
    """AC Charge Start Battery SOC (reg 160, EG4_OFFGRID + EG4_HYBRID, GH #331).

    Battery SOC at which AC Charge starts charging from the grid.

    On EG4_OFFGRID (the original GH #331 case) this pairs with reg 161 as
    the family's PRIMARY AC-charge SOC window, a portal-verified writable
    holdParam on the off-grid working-mode page (the reference dump reads
    90, the reporter's live config). Reg 67 (AC Charge SOC Limit) is
    family-rejected there (REMOTE_SET_ERROR + portal absence + reads 0), so
    this entity replaces it on EG4_OFFGRID.

    On EG4_HYBRID the register is equally live and MORE dangerous for being
    invisible: FlexBOSS21 hardware evidence (fw FAAB-2727, local dongle
    Modbus, read+write verified) shows reg 160 initiates AC charging
    whenever battery SOC is below it, regardless of the reg-120
    ACChargeType selector and of the AC-charge time windows — charges start
    out-of-window at SOC < value, and no window charge starts at
    SOC > value. The portal exposes the field for the family as "Start AC
    Charge SOC(%)"; without this entity its factory default of 90 silently
    defeats any window/ToU charge schedule. There it pairs with reg 67
    (pylxpweb's set_ac_charge_soc_limits writes 160 as start and 67 as
    end), so the related-refresh set spans all three SOC-window entities.

    Whole percent, SCALE_NONE on both paths; reg 160 is in pylxpweb's
    transport name map, so local named reads/writes work as-is. Writes cap
    at 90% (pylxpweb's register definition and hybrid setter bound); reads
    keep the tolerant 0-100 window so an out-of-spec register value still
    displays rather than blanking.

    WRITE ROUTING (#558): on EG4_OFFGRID the write is CLOUD-ONLY — local
    reg 160 writes are hardware-unverified there (all #331 write evidence
    is the cloud holdParam path) and no readback can prove a wrong
    name→register mapping didn't land elsewhere (#476), so the local path
    is not attempted; a pure-LOCAL off-grid install gets a clear error
    instead. On EG4_HYBRID the local write IS hardware-verified
    (FlexBOSS21, fw FAAB-2727, read+write) and keeps the normal
    local-first route. Local READS stay on for both families — reads are
    harmless and reg 160 reads are verified.
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge Start Battery SOC"
        self._attr_unique_id = self._stable_control_unique_id(
            "ac_charge_start_battery_soc"
        )
        self._attr_native_min_value = AC_CHARGE_BATTERY_SOC_MIN
        self._attr_native_max_value = AC_CHARGE_START_BATTERY_SOC_MAX
        self._attr_native_step = AC_CHARGE_BATTERY_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-low"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=AC_CHARGE_BATTERY_SOC_MIN,
            max_v=AC_CHARGE_START_BATTERY_SOC_MAX,
            label="AC charge start battery SOC",
            require_integer=True,
        )
        await self._write_parameter(
            value,
            local_write_blocked_reason=self._offgrid_cloud_only_reason(
                160, "AC charge start battery SOC"
            ),
            local_param=PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC,
            # The named-param cloud writer is BOTH the cloud-mode path and
            # the HYBRID local-failure fallback — the portal's own
            # holdParam write (GH #331). verify_register: grid-tied cloud
            # writes of this register are otherwise untested, so an
            # acknowledged-but-unapplied write must not surface as success.
            cloud_write=lambda: _write_cloud_named_parameter(
                self,
                PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC,
                int_value,
                f"Failed to set {PARAM_HOLD_AC_CHARGE_START_BATTERY_SOC} "
                f"to {int_value}%",
                verify_register=160,
            ),
            label=f"AC charge start battery SOC to {int_value}%",
        )


class ACChargeEndBatterySOCNumber(EG4BaseNumberEntity):
    """AC Charge End Battery SOC (reg 161, EG4_OFFGRID only, GH #331).

    Battery SOC at which the off-grid family's AC Charge working mode stops
    charging from the grid — with reg 160 the family's PRIMARY AC-charge
    SOC window, a portal-verified writable holdParam on the off-grid
    working-mode page (the reference dump reads 100, the reporter's live
    config). Reg 67 (AC Charge SOC Limit) is family-rejected there
    (REMOTE_SET_ERROR + portal absence + reads 0), so this entity replaces
    it on EG4_OFFGRID.

    Deliberately NOT created on grid-tied families (unlike the Start
    entity): pylxpweb models the grid-tied stop threshold as reg 67
    (set_ac_charge_soc_limits pairs 160 with 67), and the #332 note records
    reg 161 as READ-ONLY on grid-tied hardware — reads fine, no verified
    write. If a grid-tied write is ever verified, revisit.

    Whole percent, SCALE_NONE on both paths; reg 161 is in pylxpweb's
    transport name map from 0.9.36b28, so this entity mirrors the Start
    entity exactly (named reads on every path).

    WRITE ROUTING (#558, superseding the PR #332 review note): LOCAL
    Modbus writes to reg 161 are hardware-UNVERIFIED on the off-grid
    family — all #331 write evidence is the cloud holdParam path — and a
    post-write readback CANNOT discharge that risk: a wrong-but-writable
    register is firmware-ACKed and reads back exactly the value written
    (#476), so the readback reports success on precisely the failure it
    was cited against. The write is therefore CLOUD-ONLY on this entity
    (created for EG4_OFFGRID only), matching the #471/#472 precedent for
    unpinned writes; a pure-LOCAL install gets a clear error instead of an
    unverified local write. Local READS stay on — reads are harmless and
    verified. Revisit if a local reg 161 write is ever hardware-confirmed
    on off-grid hardware (named vendor action, raw register read before
    and after, restoration).
    """

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_name = "AC Charge End Battery SOC"
        self._attr_unique_id = self._stable_control_unique_id(
            "ac_charge_end_battery_soc"
        )
        self._attr_native_min_value = AC_CHARGE_BATTERY_SOC_MIN
        self._attr_native_max_value = AC_CHARGE_BATTERY_SOC_MAX
        self._attr_native_step = AC_CHARGE_BATTERY_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=AC_CHARGE_BATTERY_SOC_MIN,
            max_v=AC_CHARGE_BATTERY_SOC_MAX,
            label="AC charge end battery SOC",
            require_integer=True,
        )
        await self._write_parameter(
            value,
            local_write_blocked_reason=self._offgrid_cloud_only_reason(
                161, "AC charge end battery SOC"
            ),
            local_param=PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC,
            # The named-param cloud writer is BOTH the cloud-mode path and
            # the HYBRID local-failure fallback — the portal's own
            # holdParam write (GH #331).
            cloud_write=lambda: _write_cloud_named_parameter(
                self,
                PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC,
                int_value,
                f"Failed to set {PARAM_HOLD_AC_CHARGE_END_BATTERY_SOC} to {int_value}%",
                verify_register=161,
            ),
            label=f"AC charge end battery SOC to {int_value}%",
        )


# Post-write readback settle (PR #488 fix round, item 1). The portal can ACK
# a holdParam write seconds before the register reflects it (firmware-side
# delayed apply / concurrent propagation), matching pylxpweb's own
# ~2 s write-and-verify guidance. So an immediate mismatch is not yet
# evidence of a no-op: the first read is taken with no delay (fast path for a
# write that landed at once), and only a value that STAYS wrong across a
# settle re-read fails the write. A false failure on a write that DID apply is
# worse than trusting it -- the user retries a write that already succeeded.
_READBACK_SETTLE_SECONDS = 2.0
_READBACK_ATTEMPTS = 2


async def _write_cloud_named_parameter(
    entity: EG4BaseNumberEntity,
    param: str,
    value: int,
    error_message: str,
    verify_register: int | None = None,
) -> None:
    """Write a cloud holdParam value through the generic named-write API.

    Bare writer — logging, optimistic state and the related-entity refresh are
    provided by the callers' write wrappers.

    ``verify_register`` arms an equality-checked readback: after a
    ``success: true`` response the register is re-read through the cloud
    (pylxpweb invalidates its parameter cache on a successful write, so the
    read is fresh) and a value that STAYS DIFFERENT from the write across a
    settle re-read (see ``_READBACK_SETTLE_SECONDS``) raises instead of
    reporting success — the acknowledged-but-unapplied class (portal says OK,
    register unchanged).

    The readback catches a *definite, persistent numeric mismatch* and nothing
    more: it is deliberately fail-safe toward the write, so a readback that
    cannot testify — a read that raises, an absent key, or a non-numeric value
    — is trusted rather than failed (a flaky read must not fail a write that in
    all likelihood landed). So a ``success: true`` whose readback times out or
    omits the key still reports success; only a register that keeps reading a
    different value does not.
    """
    client = entity.coordinator.require_client()
    result = await client.api.control.write_parameter(entity.serial, param, str(value))
    if not result.success:
        raise HomeAssistantError(error_message)
    if verify_register is not None:
        # None => could not testify (unreadable / absent / non-numeric);
        # True/False => a numeric comparison was made. Only a persistent False
        # fails the write.
        verified: bool | None = None
        readback: Any = None
        for attempt in range(_READBACK_ATTEMPTS):
            if attempt > 0:
                # Let a slow-to-apply write propagate before the deciding read.
                await asyncio.sleep(_READBACK_SETTLE_SECONDS)
            try:
                response = await client.api.control.read_parameters(
                    entity.serial, verify_register, 1
                )
                readback = response.parameters.get(param)
            except Exception as err:
                _LOGGER.warning(
                    "Post-write readback of %s failed for %s: %s "
                    "(write was acknowledged; skipping verification)",
                    param,
                    entity.serial,
                    err,
                )
                verified = None
                break
            if readback is None:
                verified = None  # key absent — cannot testify
                break
            try:
                verified = int(float(readback)) == value
            except (TypeError, ValueError):
                verified = None  # non-numeric readback proves nothing
                break
            if verified:
                break
            # A mismatch on the first read may just be propagation lag; loop to
            # settle and re-read before deciding it is a genuine no-op.
        if verified is False:
            raise HomeAssistantError(
                f"{error_message}: the write was acknowledged but the "
                f"register still reads {readback}"
            )


class ACCoupleSOCNumberBase(EG4BaseNumberEntity):
    """Shared behavior for the AC Couple Start/End SOC pair (GH #352).

    SOC window governing the AC-coupled source on the inverter's smart port:
    the source is enabled when battery SOC drops below START and disabled
    above END. The reporter (mjstrand, 12000XP v2) scripts these to
    de-energize the smart port before transferring a grid-tied SolarEdge
    between grid and smart port; ivanfmartinez runs live 90/95 thresholds on
    an on-grid hybrid LXP (issue #352) — the params are NOT family-specific,
    so creation is gated only on a cloud client being present.

    CLOUD-ONLY, dedicated store: the portal writes the
    ``_12K_HOLD_AC_COUPLE_{START,END}_SOC`` holdParams and no local Modbus
    register is pinned (pylxpweb PR #235 — probe evidence ambiguous). The
    values deliberately do NOT live in the parameter cache — with an
    attached local transport pylxpweb rebuilds ``inverter.parameters`` from
    local register reads alone, so any cache-seeded value would be wiped by
    the next parameter refresh (PR #380 review P1). Instead the coordinator
    maintains the ``ac_couple_soc`` device-data store (throttled 5-minute
    cloud getter reads + carry-forward + post-write seeding), and this
    entity reads that store in every mode — one code path for CLOUD and
    HYBRID. Writes always route through the cloud client (the XP Quick
    Charge cloud-routing precedent, #296/#308). The entity is unavailable
    while its value is absent from the store — a device that truly lacks
    the params must never render a fake 0.
    """

    # Store key within the coordinator's ac_couple_soc device-data store,
    # and the pylxpweb control-endpoint writer method.
    _store_key: str
    _cloud_method: str
    _label: str

    @property
    def _stored_value(self) -> int | None:
        """This threshold's value from the coordinator's dedicated store."""
        devices = (self.coordinator.data or {}).get("devices", {})
        store = devices.get(self.serial, {}).get("ac_couple_soc") or {}
        value = store.get(self._store_key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    @property
    def available(self) -> bool:
        """Available only while the store holds a value (or mid-write).

        Absent value — first cloud fetch pending, or a device whose family
        genuinely lacks the AC couple params (the cloud getter reports
        ``None``) — must show unavailable, never a fake value.
        """
        if not super().available:
            return False
        if self._optimistic_value is not None:
            return True
        return self._stored_value is not None

    @property
    def native_value(self) -> float | None:
        """Whole-percent threshold from the dedicated store.

        The END entity's 255 disabled/"never stop" sentinel fails the 0-100
        range check and reads None (HA cannot render 255 on a 0-100 slider);
        the sentinel is surfaced via ``disabled_sentinel`` instead.
        """
        if self._optimistic_value is not None:
            return int(self._optimistic_value)
        value = self._stored_value
        if value is None or not AC_COUPLE_SOC_MIN <= value <= AC_COUPLE_SOC_MAX:
            return None
        return value

    async def async_set_native_value(self, value: float) -> None:
        """Write the threshold through the cloud client (every mode)."""
        int_value = _coerce_int_in_range(
            value,
            min_v=AC_COUPLE_SOC_MIN,
            max_v=AC_COUPLE_SOC_MAX,
            label=self._label,
            require_integer=True,
        )
        client = self.coordinator.require_client()
        _LOGGER.info("Setting %s to %d%% for %s", self._label, int_value, self.serial)
        # No refresh wiring: this control has no parameter-cache refresh to
        # fail — the dedicated store seed below IS its convergence channel,
        # so the write settles immediately (OptimisticWrite defaults to
        # refresh_ok=True) rather than arming retention it could never clear.
        with optimistic_value_context(self, value, self._label):
            method = getattr(client.api.control, self._cloud_method, None)
            if method is None:
                raise HomeAssistantError(
                    f"Failed to set {self._label}: pylxpweb is missing "
                    f"{self._cloud_method} (requires >= 0.9.39b2)"
                )
            result = await method(self.serial, int_value)
            if not result.success:
                raise HomeAssistantError(f"Failed to set {self._label} to {int_value}%")
            # Seed the dedicated store (sibling-preserving) with the
            # acknowledged value; the next throttled getter read confirms.
            # No parameter refresh: the parameter cache does not carry these.
            self.coordinator.note_ac_couple_soc_written(
                self.serial, self._store_key, int_value
            )


class ACCoupleStartSOCNumber(ACCoupleSOCNumberBase):
    """AC Couple Start SOC (GH #352, cloud client required).

    Battery SOC below which the AC-coupled source on the smart port is
    enabled. Cloud holdParam ``_12K_HOLD_AC_COUPLE_START_SOC``; the factory
    disabled pair reads START=100 (a legal slider value, no sentinel).
    """

    _store_key = "start_soc"
    _cloud_method = "set_inverter_ac_couple_start_soc"
    _label = "AC couple start SOC"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_translation_key = "ac_couple_start_soc"
        self._attr_unique_id = self._stable_control_unique_id("ac_couple_start_soc")
        self._attr_native_min_value = AC_COUPLE_SOC_MIN
        self._attr_native_max_value = AC_COUPLE_SOC_MAX
        self._attr_native_step = AC_COUPLE_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-low"
        self._attr_native_precision = 0


class ACCoupleEndSOCNumber(ACCoupleSOCNumberBase):
    """AC Couple End SOC (GH #352, cloud client required).

    Battery SOC above which the AC-coupled source on the smart port is
    disabled. Cloud holdParam ``_12K_HOLD_AC_COUPLE_END_SOC``. Reads of the
    255 factory disabled/"never stop" sentinel render as unknown with the
    ``disabled_sentinel`` attribute set — 255 is deliberately NOT writable
    from the 0-100 slider (restore it from the portal if needed).
    """

    _store_key = "end_soc"
    _cloud_method = "set_inverter_ac_couple_end_soc"
    _label = "AC couple end SOC"

    def __init__(self, coordinator: EG4DataUpdateCoordinator, serial: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, serial)
        self._attr_translation_key = "ac_couple_end_soc"
        self._attr_unique_id = self._stable_control_unique_id("ac_couple_end_soc")
        self._attr_native_min_value = AC_COUPLE_SOC_MIN
        self._attr_native_max_value = AC_COUPLE_SOC_MAX
        self._attr_native_step = AC_COUPLE_SOC_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-charging-high"
        self._attr_native_precision = 0

    @property
    def _disabled_sentinel_active(self) -> bool:
        """Whether the device reports the 255 disabled/"never stop" sentinel."""
        return self._stored_value == AC_COUPLE_END_SOC_DISABLED_SENTINEL

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the 255 sentinel a 0-100 slider cannot render as a value."""
        return {"disabled_sentinel": self._disabled_sentinel_active}


@dataclass(frozen=True)
class SmartLoadNumberSpec:
    """Declarative configuration for one Smart Load panel number (GH #499)."""

    #: Field within the coordinator's ``smart_load`` store.
    store_key: str
    #: pylxpweb control-endpoint writer method.
    cloud_method: str
    translation_key: str
    unique_id_suffix: str
    #: Human label used in log and error messages.
    label: str
    min_value: float
    max_value: float
    step: float
    unit: str
    icon: str
    precision: int
    #: True for the percent pair — writes are coerced to whole ints and a
    #: fractional request is rejected rather than silently truncated.
    whole_number: bool


SMART_LOAD_NUMBER_SPECS: tuple[SmartLoadNumberSpec, ...] = (
    SmartLoadNumberSpec(
        store_key="start_soc",
        cloud_method="set_inverter_smart_load_start_soc",
        translation_key="smart_load_start_soc",
        unique_id_suffix="smart_load_start_soc",
        label="Smart Load start SOC",
        min_value=SMART_LOAD_SOC_MIN,
        max_value=SMART_LOAD_SOC_MAX,
        step=SMART_LOAD_SOC_STEP,
        unit="%",
        icon="mdi:battery-charging-high",
        precision=0,
        whole_number=True,
    ),
    SmartLoadNumberSpec(
        store_key="end_soc",
        cloud_method="set_inverter_smart_load_end_soc",
        translation_key="smart_load_end_soc",
        unique_id_suffix="smart_load_end_soc",
        label="Smart Load end SOC",
        min_value=SMART_LOAD_SOC_MIN,
        max_value=SMART_LOAD_SOC_MAX,
        step=SMART_LOAD_SOC_STEP,
        unit="%",
        icon="mdi:battery-charging-low",
        precision=0,
        whole_number=True,
    ),
    SmartLoadNumberSpec(
        store_key="start_pv_power",
        cloud_method="set_inverter_smart_load_start_pv_power",
        translation_key="smart_load_start_pv_power",
        unique_id_suffix="smart_load_start_pv_power",
        label="Smart Load start PV power",
        min_value=SMART_LOAD_PV_POWER_MIN,
        max_value=SMART_LOAD_PV_POWER_MAX,
        step=SMART_LOAD_PV_POWER_STEP,
        unit="kW",
        icon="mdi:solar-power",
        precision=1,
        whole_number=False,
    ),
    SmartLoadNumberSpec(
        store_key="start_volt",
        cloud_method="set_inverter_smart_load_start_volt",
        translation_key="smart_load_start_volt",
        unique_id_suffix="smart_load_start_volt",
        label="Smart Load start voltage",
        min_value=SMART_LOAD_VOLT_MIN,
        max_value=SMART_LOAD_VOLT_MAX,
        step=SMART_LOAD_VOLT_STEP,
        unit="V",
        icon="mdi:flash",
        precision=1,
        whole_number=False,
    ),
    SmartLoadNumberSpec(
        store_key="end_volt",
        cloud_method="set_inverter_smart_load_end_volt",
        translation_key="smart_load_end_volt",
        unique_id_suffix="smart_load_end_volt",
        label="Smart Load end voltage",
        min_value=SMART_LOAD_VOLT_MIN,
        max_value=SMART_LOAD_VOLT_MAX,
        step=SMART_LOAD_VOLT_STEP,
        unit="V",
        icon="mdi:flash-outline",
        precision=1,
        whole_number=False,
    ),
)


class SmartLoadNumber(EG4BaseNumberEntity):
    """Spec-driven Smart Load panel number (GH #499, cloud client required).

    The portal's Maintenance -> Remote Set -> Smart Load Port -> "Smart Load"
    tab governs when the inverter's smart load port is energized: the SOC pair
    (start/end percent), the PV-power threshold, and a voltage pair that
    appears to stand in for the SOC pair under a voltage mode (the reporter's
    screenshot greys it out while SOC mode is active — UNTESTED here, and no
    mode parameter was found to gate on, so both pairs are exposed).
    @brendonlobo123 asked for all of them on a 12000XP (#499); Grid Always On
    from the same panel shipped first (#484).

    CLOUD-ONLY, dedicated store — the same arrangement as the AC Couple SOC
    pair (#352) for the same reasons: the portal writes
    ``_12K_HOLD_SMART_LOAD_{START,END}_{SOC,VOLT}`` and
    ``_12K_HOLD_START_PV_POWER`` and no local Modbus register is pinned for
    any of them, and a cache-seeded value would be wiped by the next parameter
    refresh under a local transport (PR #380 review P1). Values come from the
    coordinator's ``smart_load`` store (throttled 5-minute cloud getter reads +
    carry-forward + post-write seeding) in every mode, and writes always route
    through the cloud client.

    Unavailable while the value is absent from the store — never a confident 0
    on an inverter that does not carry the param. That the cloud really does
    answer with FUNC_SMART_LOAD_ENABLE present and all five holdParams missing
    is established, not assumed: it is what a GridBOSS returns (live probe
    2026-08-01). A GridBOSS itself never gets these entities — setup creates
    them only for inverters — so the case this guards is an INVERTER whose
    portal read comes back in that same partial shape.

    Disabled by default: niche, and the WRITE path is unverified on hardware
    (#484's read-verified/write-unverified position, awaiting the reporter).
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: SmartLoadNumberSpec,
    ) -> None:
        """Initialize a Smart Load number entity from its spec."""
        self._spec = spec
        super().__init__(coordinator, serial)
        self._attr_translation_key = spec.translation_key
        self._attr_unique_id = self._stable_control_unique_id(spec.unique_id_suffix)
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon
        self._attr_native_precision = spec.precision

    @property
    def _stored_value(self) -> float | None:
        """This setting's value from the coordinator's ``smart_load`` store."""
        devices = (self.coordinator.data or {}).get("devices", {})
        store = devices.get(self.serial, {}).get("smart_load") or {}
        value = store.get(self._spec.store_key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @property
    def available(self) -> bool:
        """Available only while the store holds a value (or mid-write)."""
        if not super().available:
            return False
        if self._optimistic_value is not None:
            return True
        return self._stored_value is not None

    @property
    def native_value(self) -> float | None:
        """Value from the dedicated store, or None while out of range.

        A value outside the entity's range cannot be rendered on the slider;
        surfacing None is the honest answer, and the bounds are wide enough
        that a real setting reaching this branch is a signal worth a bug
        report rather than something to clamp away.
        """
        value = self._optimistic_value
        if value is None:
            value = self._stored_value
            if (
                value is None
                or not self._spec.min_value <= value <= self._spec.max_value
            ):
                return None
        # Shaped identically whether it came from the store or from an
        # in-flight write: returning a float here and an int once the store
        # caught up would flip the percent pair's state from "80.0" to "80"
        # on convergence, breaking exact-string automation conditions.
        return int(value) if self._spec.whole_number else round(value, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting through the cloud client (every mode)."""
        spec = self._spec
        write_value: float
        if spec.whole_number:
            write_value = _coerce_int_in_range(
                value,
                min_v=spec.min_value,
                max_v=spec.max_value,
                label=spec.label,
                unit=spec.unit,
                require_integer=True,
            )
        else:
            if not spec.min_value <= value <= spec.max_value:
                raise HomeAssistantError(
                    f"{spec.label} must be between "
                    f"{spec.min_value}-{spec.max_value}{spec.unit}, got {value}"
                )
            write_value = round(value, 1)
        client = self.coordinator.require_client()
        _LOGGER.info(
            "Setting %s to %s%s for %s",
            spec.label,
            write_value,
            spec.unit,
            self.serial,
        )
        # No refresh wiring, matching the AC Couple SOC pair: the store seed
        # below IS this control's convergence channel, so the write settles
        # immediately rather than arming retention it could never clear.
        with optimistic_value_context(self, write_value, spec.label):
            method = getattr(client.api.control, spec.cloud_method, None)
            if method is None:
                raise HomeAssistantError(
                    f"Failed to set {spec.label}: pylxpweb is missing "
                    f"{spec.cloud_method} (requires >= 0.9.39b6)"
                )
            result = await method(self.serial, write_value)
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set {spec.label} to {write_value}{spec.unit}"
                )
            self.coordinator.note_smart_load_written(
                self.serial, spec.store_key, write_value
            )


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
        self._attr_unique_id = self._stable_control_unique_id("grid_sell_back_power")
        self._attr_native_min_value = GRID_SELL_BACK_POWER_MIN
        self._attr_native_max_value = GRID_SELL_BACK_POWER_MAX
        self._attr_native_step = GRID_SELL_BACK_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:transmission-tower-export"
        self._attr_native_precision = 1

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
        label = f"grid sell back power to {value:.1f} kW"
        with optimistic_value_context(self, value, label) as write:
            result = await client.api.control.write_parameter(
                self.serial,
                PARAM_HOLD_FEED_IN_GRID_POWER_PERCENT,
                f"{value:g}",
            )
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set grid sell back power to {value:.1f} kW"
                )
            write.refresh_ok = await self._refresh_related_entities()


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
        self._attr_unique_id = self._stable_control_unique_id(
            "start_discharge_power_threshold"
        )
        self._attr_native_min_value = START_DISCHARGE_POWER_MIN
        self._attr_native_max_value = START_DISCHARGE_POWER_MAX
        self._attr_native_step = START_DISCHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "W"
        self._attr_icon = "mdi:transmission-tower-import"
        self._attr_native_precision = 0

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
            # the HYBRID local-failure fallback. The website's own call
            # (reporter-verified in the GH #272 browser console) is
            # remoteSet/write with holdParam HOLD_P_TO_USER_START_DISCHG;
            # pylxpweb's set_start_discharge_power is deliberately bypassed —
            # its cloud leg writes the raw register by address and its read
            # leg looks up a key that never exists on the server.
            cloud_write=lambda: _write_cloud_named_parameter(
                self,
                PARAM_HOLD_P_TO_USER_START_DISCHG,
                int_value,
                f"Failed to set start discharge power threshold to {int_value} W",
            ),
            label=f"start discharge power threshold to {int_value} W",
        )


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
        self._attr_unique_id = self._stable_control_unique_id(
            "start_charge_power_threshold"
        )
        self._attr_native_min_value = START_CHARGE_POWER_MIN
        self._attr_native_max_value = START_CHARGE_POWER_MAX
        self._attr_native_step = START_CHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "W"
        self._attr_icon = "mdi:battery-arrow-up"
        self._attr_native_precision = 0

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
        label = f"start charge power threshold to {int_value} W"
        with optimistic_value_context(self, float(int_value), label) as write:
            # Two's-complement mask: -50 W writes 65486.
            await self.coordinator.write_raw_parameter(
                REG_PTOUSER_START_CHARGE, int_value & 0xFFFF, serial=self.serial
            )
            await asyncio.sleep(0.5)
            write.refresh_ok = await self._refresh_related_entities()


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
        self._attr_unique_id = self._stable_control_unique_id("forced_discharge_power")
        self._attr_native_min_value = FORCED_DISCHARGE_POWER_MIN
        self._attr_native_max_value = FORCED_DISCHARGE_POWER_MAX
        self._attr_native_step = FORCED_DISCHARGE_POWER_STEP
        self._attr_native_unit_of_measurement = "kW"
        self._attr_icon = "mdi:battery-arrow-down"
        self._attr_native_precision = 1

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
        self._attr_unique_id = self._stable_control_unique_id(
            "forced_discharge_soc_limit"
        )
        self._attr_native_min_value = FORCED_DISCHARGE_SOC_LIMIT_MIN
        self._attr_native_max_value = FORCED_DISCHARGE_SOC_LIMIT_MAX
        self._attr_native_step = FORCED_DISCHARGE_SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-20"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=0,
            max_v=100,
            label="Forced discharge SOC limit",
            require_integer=True,
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
        self._attr_unique_id = self._stable_control_unique_id("stop_discharge_voltage")
        self._attr_native_min_value = STOP_DISCHARGE_VOLTAGE_MIN
        self._attr_native_max_value = STOP_DISCHARGE_VOLTAGE_MAX
        self._attr_native_step = STOP_DISCHARGE_VOLTAGE_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-arrow-down-outline"
        self._attr_native_precision = 1

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
        self._attr_unique_id = self._stable_control_unique_id("on_grid_soc_cutoff")
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=0,
            max_v=100,
            label="On-grid SOC cutoff",
            require_integer=True,
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
        self._attr_unique_id = self._stable_control_unique_id("off_grid_soc_cutoff")
        self._attr_native_min_value = SOC_LIMIT_MIN
        self._attr_native_max_value = SOC_LIMIT_MAX
        self._attr_native_step = SOC_LIMIT_STEP
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:battery-outline"
        self._attr_native_precision = 0

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
        int_value = _coerce_int_in_range(
            value,
            min_v=0,
            max_v=100,
            label="Off-grid SOC cutoff",
            require_integer=True,
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
        self._attr_unique_id = self._stable_control_unique_id("battery_charge_current")
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-plus"
        self._attr_native_precision = 0

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
        self._attr_unique_id = self._stable_control_unique_id(
            "battery_discharge_current"
        )
        self._attr_native_min_value = BATTERY_CURRENT_MIN
        self._attr_native_max_value = BATTERY_CURRENT_MAX
        self._attr_native_step = BATTERY_CURRENT_STEP
        self._attr_native_unit_of_measurement = "A"
        self._attr_icon = "mdi:battery-minus"
        self._attr_native_precision = 0

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
        self._attr_unique_id = self._stable_control_unique_id(
            "system_charge_volt_limit"
        )
        self._attr_native_min_value = SYSTEM_CHARGE_VOLT_LIMIT_MIN
        self._attr_native_max_value = SYSTEM_CHARGE_VOLT_LIMIT_MAX
        self._attr_native_step = SYSTEM_CHARGE_VOLT_LIMIT_STEP
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = "mdi:battery-charging"
        self._attr_native_precision = 1

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


@dataclass(frozen=True)
class VoltageNumberSpec:
    """Declarative configuration for a voltage-register number entity."""

    key: str
    name: str
    message_label: str
    unique_id_suffix: str
    param_key: str
    register: int
    min_value: int | float
    max_value: int | float
    step: int | float
    precision: int
    require_whole: bool
    control_key: str | None
    icon: str
    related_group: tuple[str, ...]
    read_value_min: int | float = 20
    read_value_max: int | float = 70
    # Raw parameter values at or above this are decivolts and divided by 10;
    # smaller values are already volts. The default suits battery-bank
    # voltages (< 100 V); registers whose legit volts exceed 100 (e.g. PV
    # start voltage, 140-500 V) need a threshold above their volts maximum.
    decivolt_threshold: float = 100.0
    # The default cloud path writes the raw register (decivolts). Set True
    # for parameters whose verified cloud route is a named write in
    # human-readable volts (portal valueText semantics).
    cloud_write_volts_named: bool = False
    # Whether native_value returns a float (True, battery voltages with
    # fractional volts) or truncates to int (False — preserves the retired
    # PV start class's integer state, e.g. "140" not "140.0", for
    # exact-string automation conditions). Independent of display precision.
    read_as_float: bool = True
    # Local writes to this register are hardware-UNVERIFIED on EG4_OFFGRID:
    # the write routes CLOUD-ONLY there (#558, the #471/#472 pattern) and a
    # pure-LOCAL off-grid install gets a clear error instead — a readback
    # cannot catch a wrong name→register mapping (#476), so not attempting
    # the write is the only safe policy until hardware-confirmed. Other
    # families keep the local-first route.
    offgrid_local_write_unverified: bool = False


VOLTAGE_NUMBER_SPECS: tuple[VoltageNumberSpec, ...] = (
    VoltageNumberSpec(
        key="on_grid_cutoff_voltage",
        name="On-Grid Cut-Off Voltage",
        message_label="On-grid cutoff voltage",
        unique_id_suffix="on_grid_cutoff_voltage",
        param_key=PARAM_HOLD_ONGRID_EOD_VOLTAGE,
        register=REG_ONGRID_EOD_VOLTAGE,
        min_value=CUTOFF_VOLTAGE_MIN,
        max_value=CUTOFF_VOLTAGE_MAX,
        step=CUTOFF_VOLTAGE_STEP,
        precision=1,
        require_whole=False,
        control_key="on_grid_cutoff_voltage",
        icon="mdi:battery-alert",
        related_group=("on_grid_cutoff_voltage", "off_grid_cutoff_voltage"),
    ),
    VoltageNumberSpec(
        key="off_grid_cutoff_voltage",
        name="Off-Grid Cut-Off Voltage",
        message_label="Off-grid cutoff voltage",
        unique_id_suffix="off_grid_cutoff_voltage",
        param_key=PARAM_HOLD_OFFGRID_EOD_VOLTAGE,
        register=REG_OFFGRID_EOD_VOLTAGE,
        min_value=CUTOFF_VOLTAGE_MIN,
        max_value=CUTOFF_VOLTAGE_MAX,
        step=CUTOFF_VOLTAGE_STEP,
        precision=1,
        require_whole=False,
        control_key="off_grid_cutoff_voltage",
        icon="mdi:battery-outline",
        related_group=("on_grid_cutoff_voltage", "off_grid_cutoff_voltage"),
    ),
    VoltageNumberSpec(
        key="ac_charge_start_voltage",
        name="AC Charge Start Voltage",
        message_label="AC charge start voltage",
        unique_id_suffix="ac_charge_start_voltage",
        param_key=PARAM_HOLD_AC_CHARGE_START_VOLTAGE,
        register=REG_AC_CHARGE_START_VOLTAGE,
        min_value=AC_CHARGE_VOLTAGE_MIN,
        max_value=AC_CHARGE_VOLTAGE_MAX,
        step=AC_CHARGE_VOLTAGE_STEP,
        precision=0,
        require_whole=True,
        control_key="ac_charge_start_voltage",
        icon="mdi:battery-charging-low",
        related_group=("ac_charge_start_voltage", "ac_charge_end_voltage"),
        # Reg 158's only write evidence is a cloud-path delta-test
        # (`portal-correlated`, family unrecorded) — no local off-grid
        # write proof exists, so EG4_OFFGRID routes cloud-only (#558).
        offgrid_local_write_unverified=True,
    ),
    VoltageNumberSpec(
        key="ac_charge_end_voltage",
        name="AC Charge End Voltage",
        message_label="AC charge end voltage",
        unique_id_suffix="ac_charge_end_voltage",
        param_key=PARAM_HOLD_AC_CHARGE_END_VOLTAGE,
        register=REG_AC_CHARGE_END_VOLTAGE,
        min_value=AC_CHARGE_VOLTAGE_MIN,
        max_value=AC_CHARGE_VOLTAGE_MAX,
        step=AC_CHARGE_VOLTAGE_STEP,
        precision=0,
        require_whole=True,
        control_key="ac_charge_end_voltage",
        icon="mdi:battery-charging-high",
        related_group=("ac_charge_start_voltage", "ac_charge_end_voltage"),
        # Reg 159 mirrors 158: cloud-path write evidence only (#558).
        offgrid_local_write_unverified=True,
    ),
    VoltageNumberSpec(
        # MPPT activation floor (register 22). Lowering it (e.g. to 140 V)
        # keeps the MPPT engaged across a wider voltage range, reducing
        # connect/disconnect cycling that can cause internal DC bus voltage
        # spikes (vbus out of range / E019 faults). Firmware rejects values
        # below 140 V (error code 3). No control_key: this is a PV control,
        # not gated by the battery charge/discharge regime.
        key="pv_start_voltage",
        name="PV Start Voltage",
        message_label="PV start voltage",
        unique_id_suffix="pv_start_voltage",
        param_key=PARAM_HOLD_START_PV_VOLT,
        register=REG_START_PV_VOLT,
        min_value=PV_START_VOLTAGE_MIN,
        max_value=PV_START_VOLTAGE_MAX,
        step=PV_START_VOLTAGE_STEP,
        precision=0,
        require_whole=True,
        control_key=None,
        icon="mdi:solar-power-variant",
        related_group=("pv_start_voltage",),
        read_value_min=90,
        read_value_max=500,
        # Legit volts run 90-500, raw decivolts 900-5000: 600 cleanly
        # separates them (the battery default of 100 would mis-split —
        # cloud's already-scaled 140 V is >= 100 and got divided again,
        # the pure-CLOUD unknown-value bug this spec entry fixes).
        decivolt_threshold=600,
        # Verified cloud route writes the named parameter in volts
        # (portal valueText=140); raw-register 22 writes are unproven.
        cloud_write_volts_named=True,
        # Integer state ("140"), matching the retired dedicated class.
        read_as_float=False,
    ),
)


class EG4VoltageNumber(EG4BaseNumberEntity):
    """Spec-driven number entity for standard decivolt voltage registers."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: VoltageNumberSpec,
    ) -> None:
        """Initialize a voltage-register number entity from its spec."""
        self._spec = spec
        self._control_key = spec.control_key
        super().__init__(coordinator, serial)
        self._attr_name = spec.name
        self._attr_unique_id = self._stable_control_unique_id(spec.unique_id_suffix)
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = "V"
        self._attr_icon = spec.icon
        self._attr_native_precision = spec.precision

    def _volts_from_spec_param(self, raw: Any) -> float:
        """Normalize a voltage parameter to volts using the spec's threshold.

        Same magnitude heuristic as ``_volts_from_param`` (local Modbus
        surfaces raw decivolts, cloud returns already-scaled volts), but the
        split point comes from the spec so registers whose legit volts exceed
        100 (PV start voltage) don't get their cloud values divided again.
        """
        value = float(raw)
        threshold = self._spec.decivolt_threshold
        return round(value / 10.0 if value >= threshold else value, 1)

    @property
    def native_value(self) -> float | None:
        """Return the current voltage, normalizing raw decivolts when needed."""
        return self._read_param_value(
            param_key=self._spec.param_key,
            value_min=self._spec.read_value_min,
            value_max=self._spec.read_value_max,
            as_float=self._spec.read_as_float,
            param_transform=self._volts_from_spec_param,
            params_first=True,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Validate and write the configured voltage register."""
        spec = self._spec
        write_value = value
        if spec.require_whole:
            int_value = int(value)
            if abs(value - int_value) > 0.01:
                raise HomeAssistantError(
                    f"{spec.message_label} must be a whole number of volts, got {value}"
                )
            int_value = _coerce_int_in_range(
                value,
                min_v=spec.min_value,
                max_v=spec.max_value,
                label=spec.message_label,
                unit=" V",
            )
            write_value = float(int_value)
        elif value < spec.min_value or value > spec.max_value:
            raise HomeAssistantError(
                f"{spec.message_label} must be between "
                f"{spec.min_value}-{spec.max_value} V, got {value}"
            )

        cloud_write: Callable[[], Awaitable[None]] | None = None
        if spec.cloud_write_volts_named:
            volts = int(write_value)

            async def _cloud_write_named_volts() -> None:
                await _write_cloud_named_parameter(
                    self,
                    spec.param_key,
                    volts,
                    f"Failed to set {spec.message_label} to {volts} V",
                )

            cloud_write = _cloud_write_named_volts

        await self._write_voltage_register(
            value=write_value,
            param_name=spec.param_key,
            register=spec.register,
            label=spec.name,
            cloud_write=cloud_write,
            local_write_blocked_reason=(
                self._offgrid_cloud_only_reason(spec.register, spec.message_label)
                if spec.offgrid_local_write_unverified
                else None
            ),
        )
