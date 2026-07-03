"""Switch platform for EG4 Web Monitor integration."""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    from homeassistant.components.switch import SwitchEntity  # type: ignore[assignment]
    from homeassistant.helpers.update_coordinator import (
        CoordinatorEntity,  # type: ignore[assignment]
    )

from . import EG4ConfigEntry
from .base_entity import EG4BaseSwitch
from .const import (
    FUNCTION_PARAM_MAPPING,
    INVERTER_FAMILY_EG4_OFFGRID,
    PARAM_FUNC_AC_CHARGE,
    PARAM_FUNC_BATTERY_BACKUP_CTRL,
    PARAM_FUNC_CHARGE_LAST,
    PARAM_FUNC_EPS_EN,
    PARAM_FUNC_FEED_IN_GRID_EN,
    PARAM_FUNC_FORCED_CHG_EN,
    PARAM_FUNC_FORCED_DISCHG_EN,
    PARAM_FUNC_GREEN_EN,
    PARAM_FUNC_GRID_PEAK_SHAVING,
    PARAM_FUNC_PV_SELL_TO_GRID_EN,
    PARAM_FUNC_RUN_WITHOUT_GRID,
    QUICK_CHARGE_DURATION_DEFAULT,
    WORKING_MODES,
)
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    flag_offgrid_control_suppression,
    is_offgrid_family,
    is_supported_control_model,
    supports_grid_sellback,
)

_LOGGER = logging.getLogger(__name__)

# Working modes that act on grid-parallel export/import blending. The
# EG4_OFFGRID (SNA) platform has no grid sellback and no grid-parallel
# operation (bypass-or-invert topology), so these functions are inert there:
# the registers exist on the shared Luxpower layout but always read disabled
# (stock SNA12K-US cloud dump and the 6000XP capture in #222 both show
# FUNC_GRID_PEAK_SHAVING=False / FUNC_FORCED_DISCHG_EN=False), and the SNA
# platform manages battery-vs-grid priority through its own LSP_* /
# discharge-control parameters instead. Suppressed for that family per the
# PR #220 / issue #197 adjudication (eg4-juzg).
GRID_TIED_ONLY_WORKING_MODE_PARAMS: frozenset[str] = frozenset(
    {
        "FUNC_GRID_PEAK_SHAVING",
        "FUNC_FORCED_DISCHG_EN",
    }
)

# Control keys of the suppressed working-mode switches (entity_key is the
# param name lowercased without the "func_" prefix — see
# EG4WorkingModeSwitch.__init__). Unique IDs are ``{serial}_{key}``; the
# Repairs probe matches by suffix so legacy-prefixed registry entries are
# caught too.
_SUPPRESSED_OFFGRID_SWITCH_KEYS: tuple[str, ...] = (
    "grid_peak_shaving",
    "forced_dischg_en",
)


def _supports_eps_battery_backup(device_data: dict[str, Any]) -> bool:
    """Check if device supports EPS battery backup parameter.

    The EPS battery backup switch controls a specific inverter parameter.
    Some devices (like XP series) don't support this parameter through the API,
    even though they have off-grid capability in hardware.

    Args:
        device_data: Device data dictionary with model and features

    Returns:
        True if the device supports the EPS battery backup parameter
    """
    features = device_data.get("features")

    # If features are available, use feature-based detection
    if features:
        # EG4 Off-Grid series (12000XP, 6000XP) supports EPS natively
        # but the parameter control may be different
        inverter_family = features.get("inverter_family")
        if inverter_family == INVERTER_FAMILY_EG4_OFFGRID:
            # EG4_OFFGRID devices support EPS but may use different parameter
            # For now, keep them enabled until we confirm parameter support
            return bool(features.get("supports_off_grid", True))

        # EG4_HYBRID and others generally support the EPS parameter
        return bool(features.get("supports_off_grid", True))

    # Fallback to string matching for backward compatibility
    # XP devices (12000XP, 6000XP) don't support the standard EPS parameter
    model = device_data.get("model", "Unknown")
    model_lower = model.lower()
    return "xp" not in model_lower


def _params_are_local_raw(coordinator: EG4DataUpdateCoordinator, serial: str) -> bool:
    """Whether this serial's parameter cache is (or will become) local-raw.

    Mirrors ``EG4BaseNumberEntity._params_are_local_raw()``: in local-only
    mode and with a HYBRID local transport the parameter cache is decoded
    from registers, so a key the installed pylxpweb cannot decode from a
    register (see ``_local_params_can_carry``) can never appear and a
    switch reading it would permanently report OFF.

    Unlike the number-entity property this is evaluated once at setup, so
    it also consults the CONFIGURED transports: a hybrid attach that fails
    at startup and recovers later (eg4-05l) must not slip a
    cloud-param-only switch through the gate.
    """
    if coordinator.is_local_only():
        return True
    if coordinator.has_configured_local_transport(serial):
        return True
    inverter = coordinator.get_inverter_object(serial)
    return getattr(inverter, "transport", None) is not None


def _local_params_can_carry(param: str) -> bool:
    """Whether the installed pylxpweb decodes ``param`` from local registers.

    A local-raw parameter cache (LOCAL mode, or HYBRID with a transport)
    only contains keys named in pylxpweb's register map — a key absent from
    the map can never appear, so a switch reading it would permanently
    report OFF and local writes of it would fail.  Probing the map at setup
    doubles as the version guard for newly pinned bits: e.g.
    ``FUNC_PV_SELL_TO_GRID_EN`` (reg 179 bit 3, pinned 2026-06-12) resolves
    from pylxpweb 0.9.36b6 on, while older installs keep the pre-pin
    cloud-only behavior (same hasattr-style probing the Stop Discharge
    Voltage number entity uses for new pylxpweb methods).
    """
    from pylxpweb.constants.registers import REGISTER_TO_PARAM_KEYS

    return any(param in names for names in REGISTER_TO_PARAM_KEYS.values())


# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor switch entities."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    entities: list[SwitchEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for switch setup")
        return

    # Create station DST switch if station data is available
    if "station" in coordinator.data:
        entities.append(EG4DSTSwitch(coordinator))

    # Skip device switches if no devices data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data for switch setup, creating station switches only"
        )
        if entities:
            async_add_entities(entities, True)
        return

    # Create switch entities for compatible devices
    for serial, device_data in coordinator.data["devices"].items():
        device_type = device_data.get("type", "unknown")

        # Only create switches for standard inverters (not GridBOSS)
        if device_type == "inverter":
            # Get device model for compatibility check (defensive against a
            # non-str model, matching is_supported_control_model()).
            model = device_data.get("model", "Unknown")
            model_lower = model.lower() if isinstance(model, str) else ""

            # Check if device model is known to support switch functions.
            # Matches by model-name substring or, for cloud deviceTypeText
            # variants the substrings miss (e.g. "SNA-US 15K", #259), by the
            # detected inverter family.
            _LOGGER.debug(
                "Switch setup for %s: model=%s, model_lower=%s, family=%s",
                serial,
                model,
                model_lower,
                (device_data.get("features") or {}).get("inverter_family"),
            )
            if is_supported_control_model(device_data):
                # Add quick charge switch. Works over the cloud API or, for a
                # supported model with a local transport, directly via holding
                # registers 233/234 (HYBRID prefers local; pylxpweb routes it).
                if (
                    coordinator.has_http_api()
                    or coordinator.has_configured_local_transport(serial)
                ):
                    entities.append(EG4QuickChargeSwitch(coordinator, serial))
                else:
                    _LOGGER.debug(
                        "Skipping Quick Charge switch for %s (no transport available)",
                        serial,
                    )

                # Add battery backup switch (EPS) based on feature detection
                eps_supported = _supports_eps_battery_backup(device_data)
                _LOGGER.debug(
                    "EPS support check for %s: supported=%s, features=%s",
                    serial,
                    eps_supported,
                    device_data.get("features"),
                )
                if eps_supported:
                    entities.append(EG4BatteryBackupSwitch(coordinator, serial))
                else:
                    _LOGGER.debug(
                        "Skipping EPS Battery Backup switch for %s (not supported)",
                        serial,
                    )

                # Add off-grid mode switch (Green Mode)
                entities.append(EG4OffGridModeSwitch(coordinator, serial))

                # Add charge last switch (reg 110 bit 4) — issue #177
                entities.append(EG4ChargeLastSwitch(coordinator, serial))

                # Add working mode switches
                sellback_supported = supports_grid_sellback(device_data)
                params_local_raw = _params_are_local_raw(coordinator, serial)
                offgrid = is_offgrid_family(device_data)
                if offgrid:
                    # One-shot Repairs issue for users who already had the
                    # suppressed grid-tied controls registered (#219
                    # precedent: explain disappearing entities).
                    flag_offgrid_control_suppression(
                        hass,
                        serial,
                        device_data.get("model", "Unknown"),
                        "switch",
                        tuple(
                            f"{serial}_{key}" for key in _SUPPRESSED_OFFGRID_SWITCH_KEYS
                        ),
                    )
                for mode_config in WORKING_MODES.values():
                    param = mode_config.get("param", "")
                    # Grid-tied-only controls are inert on EG4_OFFGRID
                    # hardware — see GRID_TIED_ONLY_WORKING_MODE_PARAMS.
                    if offgrid and param in GRID_TIED_ONLY_WORKING_MODE_PARAMS:
                        _LOGGER.debug(
                            "Skipping working mode %s for %s (grid-tied only; "
                            "family=EG4_OFFGRID)",
                            param,
                            serial,
                        )
                        continue
                    # Grid sell-back controls are meaningless on off-grid
                    # families (GH #135)
                    if mode_config.get("grid_tied_only") and not sellback_supported:
                        _LOGGER.debug(
                            "Skipping working mode %s for %s (no grid sell-back)",
                            param,
                            serial,
                        )
                        continue
                    # State keys the installed pylxpweb cannot decode from
                    # local registers never appear in a local-raw parameter
                    # cache — skip rather than show a lying OFF state.  This
                    # probe is also the version guard for newly pinned bits
                    # (FUNC_PV_SELL_TO_GRID_EN needs pylxpweb >= 0.9.36b6).
                    if params_local_raw and not _local_params_can_carry(param):
                        _LOGGER.debug(
                            "Skipping working mode %s for %s (state key not "
                            "decodable from local registers by installed "
                            "pylxpweb)",
                            param,
                            serial,
                        )
                        continue
                    # For local-only mode, skip working modes without a Modbus
                    # register mapping in _WORKING_MODE_PARAMETERS.
                    if coordinator.is_local_only() and not _WORKING_MODE_PARAMETERS.get(
                        param
                    ):
                        _LOGGER.debug(
                            "Skipping working mode %s for %s (no Modbus support)",
                            param,
                            serial,
                        )
                        continue

                    entities.append(
                        EG4WorkingModeSwitch(
                            coordinator=coordinator,
                            serial=serial,
                            mode_config=mode_config,
                        )
                    )

    if entities:
        async_add_entities(entities)


# Bound (seconds) on how long the Quick Charge switch distrusts a FRESH but
# UNCONFIRMING status read after a successful write (#296): within the bound
# the cloud may simply not have registered the new task yet; past it a fresh
# read is trusted in either direction. Known-stale data (carried forward, or
# read before the write) NEVER overrides the commanded state regardless of
# this bound — falling back to it at expiry would reproduce the reported flap
# (ON -> stale OFF at t+TTL -> eventual fresh ON) during exactly the cloud
# 502 storms the reporter's environment produces. A fresh read normally lands
# within one 30s status throttle window and ends the hold.
#
# Intentional trade-off: because the hold is fresh-data-terminated, a
# PERMANENT status-source outage after a command retains the commanded state
# indefinitely (the last thing we know the inverter accepted) — this reverses
# the earlier "a dead status source can never pin state forever" guarantee.
# Showing the accepted command beats flapping to provably pre-write data.
QUICK_CHARGE_OPTIMISTIC_TTL = 300.0


class EG4QuickChargeSwitch(EG4BaseSwitch):
    """Switch to control quick charge functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the quick charge switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="quick_charge",
            name="Quick Charge",
            icon="mdi:battery-charging",
        )
        # Post-write optimistic retention (#296): after a successful
        # enable/disable, hold the commanded state until a quick-charge
        # status read FRESHER than the write confirms either state. The
        # coordinator refresh inside _execute_switch_action can serve a
        # stale/carried-forward status (30s throttle) or one read before the
        # cloud registered the new task — clearing optimistic state on that
        # data flipped the switch OFF ~7s after a successful (cloud-fallback)
        # start while the inverter kept charging.
        self._pending_state: bool | None = None
        self._pending_since: float = 0.0

    def _prefers_cloud_control(self) -> bool:
        """True when quick charge must be driven via the cloud endpoints.

        The EG4_OFFGRID family (12000XP/6000XP) firmware rejects writes to
        holding register 233 (ILLEGAL DATA ADDRESS, #296), so pylxpweb's
        local-first enable/disable burns a doomed Modbus write + warning on
        every toggle before falling back to the cloud. Go straight to the
        cloud start/stop endpoints when a cloud client is configured; other
        families keep the local-first behavior (register 233 works there).
        """
        return is_offgrid_family(self._device_data) and self.coordinator.has_http_api()

    async def _cloud_enable_quick_charge(self, minute: int | None = None) -> bool:
        """Start quick charge via the cloud endpoint (offgrid family, #296)."""
        client = self.coordinator.client
        if client is None:
            return False
        result = await client.api.control.start_quick_charge(
            self._serial, minute=minute
        )
        return bool(result.success)

    async def _cloud_disable_quick_charge(self) -> bool:
        """Stop quick charge via the cloud endpoint (offgrid family, #296)."""
        client = self.coordinator.client
        if client is None:
            return False
        result = await client.api.control.stop_quick_charge(self._serial)
        return bool(result.success)

    @property
    def is_on(self) -> bool | None:
        """Return True if quick charge is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        quick_charge_status = self._device_data.get("quick_charge_status")
        status = quick_charge_status if isinstance(quick_charge_status, dict) else None

        # Post-write retention (#296): the commanded state holds until a
        # status read performed AFTER the write (fetched_at newer than the
        # write) reports on the charge. Known-stale data — carried forward or
        # read pre-write — never overrides the command, even past the TTL:
        # trusting it at expiry would flap the switch to the pre-write value
        # mid-charge (Codex review). A fresh CONFIRMING read ends the hold
        # immediately; a fresh UNCONFIRMING read is trusted only after the
        # TTL (within it, the cloud may not have registered the task yet).
        if self._pending_state is not None:
            fetched_at = status.get("fetched_at") if status else None
            if fetched_at is None or fetched_at < self._pending_since:
                return self._pending_state  # stale/absent — hold
            reported = status.get("hasUnclosedQuickChargeTask") if status else None
            confirming = reported is not None and bool(reported) == self._pending_state
            expired = (
                time.monotonic() - self._pending_since > QUICK_CHARGE_OPTIMISTIC_TTL
            )
            if not confirming and not expired:
                return self._pending_state  # fresh but unconfirming — hold
            self._pending_state = None

        if status:
            # Parse the hasUnclosedQuickChargeTask field from getStatusInfo response
            has_unclosed_task = status.get("hasUnclosedQuickChargeTask")
            if has_unclosed_task is not None:
                return bool(has_unclosed_task)

        # Default to False if we don't have status information
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add quick charge task details if available
        quick_charge_status = self._device_data.get("quick_charge_status")
        if quick_charge_status and isinstance(quick_charge_status, dict):
            # Add useful status information as attributes
            task_id = quick_charge_status.get("unclosedQuickChargeTaskId")
            task_status = quick_charge_status.get("unclosedQuickChargeTaskStatus")

            if task_id:
                attributes["task_id"] = task_id
            if task_status:
                attributes["task_status"] = task_status

            # Remaining minutes for a fixed-duration quick charge (new firmware).
            # remainTimeBeforeQuickChargeStop is reported in seconds.
            remain = quick_charge_status.get("remainTimeBeforeQuickChargeStop")
            if remain:
                attributes["minutes_remaining"] = math.ceil(remain / 60)

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on quick charge using the stored duration preference."""
        minute = self.coordinator._quick_charge_minutes.get(
            self._serial, QUICK_CHARGE_DURATION_DEFAULT
        )
        await self._async_set_quick_charge(True, enable_kwargs={"minute": minute})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off quick charge."""
        await self._async_set_quick_charge(False)

    async def _async_set_quick_charge(
        self, turn_on: bool, enable_kwargs: dict[str, Any] | None = None
    ) -> None:
        """Run the enable/disable action and arm the post-write retention.

        pylxpweb's enable/disable prefer the local transport (register 233);
        on the EG4_OFFGRID family that register is firmware-rejected, so the
        cloud-direct callables are used instead (#296). On success the
        commanded state is retained until a status read fresher than the
        write confirms either state (see ``is_on``); a failed action clears
        any prior hold and re-raises.
        """
        enable_method: str | Callable[..., Awaitable[bool]] = "enable_quick_charge"
        disable_method: str | Callable[..., Awaitable[bool]] = "disable_quick_charge"
        if self._prefers_cloud_control():
            enable_method = self._cloud_enable_quick_charge
            disable_method = self._cloud_disable_quick_charge

        self._pending_state = None
        await self._execute_switch_action(
            action_name="quick charge",
            enable_method=enable_method,
            disable_method=disable_method,
            turn_on=turn_on,
            refresh_params=False,
            enable_kwargs=enable_kwargs,
        )
        # Success (no exception raised): hold the commanded state until a
        # fresh post-write status read confirms either state (#296).
        self._pending_state = turn_on
        self._pending_since = time.monotonic()
        self.async_write_ha_state()


class EG4BatteryBackupSwitch(EG4BaseSwitch):
    """Switch to control battery backup (EPS) functionality."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the battery backup switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="battery_backup",
            name="EPS Battery Backup",
            icon="mdi:battery-charging",
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if battery backup is enabled."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check battery backup status data from coordinator (real-time)
        battery_backup_status = self._device_data.get("battery_backup_status")
        if battery_backup_status and isinstance(battery_backup_status, dict):
            # Use the enabled field from battery backup status
            enabled = battery_backup_status.get("enabled")
            if enabled is not None:
                return bool(enabled)

        # Fallback: Check parameter data from coordinator
        return bool(self._parameter_data.get("FUNC_EPS_EN", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add battery backup status details if available
        battery_backup_status = self._device_data.get("battery_backup_status")
        if battery_backup_status and isinstance(battery_backup_status, dict):
            # Add battery backup status information
            func_eps_en = battery_backup_status.get("FUNC_EPS_EN")
            if func_eps_en is not None:
                attributes["func_eps_en"] = func_eps_en
            # Add any error information
            error = battery_backup_status.get("error")
            if error:
                attributes["status_error"] = error
        elif self._parameter_data:
            # Fallback: Add parameter details if available
            func_eps_en = self._parameter_data.get("FUNC_EPS_EN")
            if func_eps_en is not None:
                attributes["func_eps_en"] = func_eps_en

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable battery backup."""
        await self._execute_local_with_fallback(
            action_name="battery backup (EPS)",
            parameter=PARAM_FUNC_EPS_EN,
            value=True,
            cloud_enable_method="enable_battery_backup",
            cloud_disable_method="disable_battery_backup",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable battery backup."""
        await self._execute_local_with_fallback(
            action_name="battery backup (EPS)",
            parameter=PARAM_FUNC_EPS_EN,
            value=False,
            cloud_enable_method="enable_battery_backup",
            cloud_disable_method="disable_battery_backup",
        )


class EG4OffGridModeSwitch(EG4BaseSwitch):
    """Switch to control off-grid mode (Green Mode) functionality.

    Off-Grid Mode (called "Green Mode" in pylxpweb) controls the off-grid
    operating mode toggle visible in the EG4 web monitoring interface.
    When enabled, the inverter operates in an off-grid optimized configuration.

    Note: This is FUNC_GREEN_EN in register 110, distinct from FUNC_EPS_EN
    (battery backup/EPS mode) in register 21.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the off-grid mode switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="off_grid_mode",
            name="Off Grid Mode",
            icon="mdi:transmission-tower-off",
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if off-grid mode is enabled."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check parameter data from coordinator
        return bool(self._parameter_data.get("FUNC_GREEN_EN", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add parameter details if available
        if self._parameter_data:
            func_green_en = self._parameter_data.get("FUNC_GREEN_EN")
            if func_green_en is not None:
                attributes["func_green_en"] = func_green_en

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    @property
    def _green_mode_cloud_only(self) -> bool:
        """Local FUNC_GREEN_EN writes are withheld on EG4_OFFGRID.

        The SNA register-110 upper-bit layout is hardware-proven to differ
        from the 18kPV table (buzzer at bit 7, ECO at bit 15 — PR #220 /
        eg4-juzg), and green's true position on this family is unverified
        (the lxp_modbus reference puts it at bit 14, not the mapped bit 8).
        A local bit-8 write on SNA hardware would likely flip a CT-sampling
        config bit while reading back as success. The cloud applies the bit
        server-side and is always correct, so offgrid green-mode writes are
        cloud-only until a community toggle capture pins the bit.
        """
        return is_offgrid_family(self._device_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable off-grid mode."""
        await self._execute_local_with_fallback(
            action_name="off-grid mode (Green Mode)",
            parameter=PARAM_FUNC_GREEN_EN,
            value=True,
            cloud_enable_method="enable_green_mode",
            cloud_disable_method="disable_green_mode",
            cloud_only=self._green_mode_cloud_only,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable off-grid mode."""
        await self._execute_local_with_fallback(
            action_name="off-grid mode (Green Mode)",
            parameter=PARAM_FUNC_GREEN_EN,
            value=False,
            cloud_enable_method="enable_green_mode",
            cloud_disable_method="disable_green_mode",
            cloud_only=self._green_mode_cloud_only,
        )


class EG4ChargeLastSwitch(EG4BaseSwitch):
    """Switch to control the battery Charge Last function.

    Charge Last (FUNC_CHARGE_LAST, register 110 bit 4) flips the PV surplus
    priority. Disabled (default, "charge first"): PV charges the battery
    before exporting surplus to the grid. Enabled ("charge last"): PV serves
    house loads and grid export first and charges the battery last — useful
    to reserve battery headroom for peak production when PV capacity exceeds
    the export limit (issue #177).

    Local writes go through the named-parameter map (read-modify-write of
    register 110); cloud writes use the function-control API — the same
    routes pylxpweb's own get/set_charge_last helpers use.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the charge last switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="charge_last",
            name="Charge Last",
            icon="mdi:battery-clock",
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if charge last mode is enabled."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check parameter data from coordinator
        return bool(self._parameter_data.get(PARAM_FUNC_CHARGE_LAST, False))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {}

        # Add parameter details if available
        if self._parameter_data:
            func_charge_last = self._parameter_data.get(PARAM_FUNC_CHARGE_LAST)
            if func_charge_last is not None:
                attributes["func_charge_last"] = func_charge_last

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes if attributes else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable charge last mode."""
        await self._execute_local_with_fallback(
            action_name="charge last",
            parameter=PARAM_FUNC_CHARGE_LAST,
            value=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable charge last mode."""
        await self._execute_local_with_fallback(
            action_name="charge last",
            parameter=PARAM_FUNC_CHARGE_LAST,
            value=False,
        )


# Mapping of working mode parameters to inverter method names (HTTP API)
_WORKING_MODE_METHODS = {
    "FUNC_AC_CHARGE": ("enable_ac_charge_mode", "disable_ac_charge_mode"),
    "FUNC_FORCED_CHG_EN": ("enable_pv_charge_priority", "disable_pv_charge_priority"),
    "FUNC_FORCED_DISCHG_EN": ("enable_forced_discharge", "disable_forced_discharge"),
    "FUNC_GRID_PEAK_SHAVING": ("enable_peak_shaving_mode", "disable_peak_shaving_mode"),
    "FUNC_BATTERY_BACKUP_CTRL": (
        "enable_battery_backup_ctrl",
        "disable_battery_backup_ctrl",
    ),
    "FUNC_FEED_IN_GRID_EN": ("enable_feed_in_grid", "disable_feed_in_grid"),
    "FUNC_PV_SELL_TO_GRID_EN": ("enable_pv_sell_to_grid", "disable_pv_sell_to_grid"),
}

# Mapping of working mode function names to named-parameter constants used by
# local Modbus writes.  A non-None value means the mode is writable locally.
_WORKING_MODE_PARAMETERS: dict[str, str | None] = {
    "FUNC_AC_CHARGE": PARAM_FUNC_AC_CHARGE,
    "FUNC_FORCED_CHG_EN": PARAM_FUNC_FORCED_CHG_EN,
    "FUNC_FORCED_DISCHG_EN": PARAM_FUNC_FORCED_DISCHG_EN,
    # Extended function registers (verified via Modbus probe 2026-02-13)
    "FUNC_GRID_PEAK_SHAVING": PARAM_FUNC_GRID_PEAK_SHAVING,  # Register 179, bit 7
    "FUNC_BATTERY_BACKUP_CTRL": PARAM_FUNC_BATTERY_BACKUP_CTRL,  # Register 233, bit 1
    "FUNC_FEED_IN_GRID_EN": PARAM_FUNC_FEED_IN_GRID_EN,  # Register 21, bit 15
    # Register 179, bit 3 (GH #135) — pinned 2026-06-12 via authorized live
    # cloud toggles raw-verified on BOTH 12K-hybrid models (FlexBOSS21
    # 52842P0581 and 18kPV 4512670118: reg-179 raw 0x104c <-> 0x1044, XOR
    # 0x0008 = single bit 3, restores verified by re-read).  Requires
    # pylxpweb >= 0.9.36b6 for the name to resolve locally; older installs
    # are handled by the _local_params_can_carry() setup gate.
    "FUNC_PV_SELL_TO_GRID_EN": PARAM_FUNC_PV_SELL_TO_GRID_EN,
    # Register 110, bit 1 (GH #274) — "Fast Zero Export" in both web UIs
    # ("FunctionEn1.ubFastZeroExport" in the LXP protocol PDF). Same bit in
    # pylxpweb's base and SNA register-110 tables, so the name resolves
    # locally on every supported install. Deliberately absent from
    # _WORKING_MODE_METHODS: the cloud path goes through the generic
    # function-control API — the exact call the website makes.
    "FUNC_RUN_WITHOUT_GRID": PARAM_FUNC_RUN_WITHOUT_GRID,
}


class EG4WorkingModeSwitch(EG4BaseSwitch):
    """Switch for controlling EG4 working modes."""

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        mode_config: dict[str, Any],
    ) -> None:
        """Initialize the working mode switch."""
        self._mode_config = mode_config

        # Clean parameter name for entity key (remove func_ prefix for cleaner
        # IDs). Modes may override via "entity_key" when the param-derived
        # default would mislead (e.g. FUNC_RUN_WITHOUT_GRID -> fast_zero_export).
        param_clean = mode_config["param"].lower().replace("func_", "")

        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key=mode_config.get("entity_key", param_clean),
            name=mode_config["name"],
            icon=mode_config.get("icon", "mdi:toggle-switch"),
            entity_category=mode_config.get("entity_category"),
            translation_key=mode_config.get("translation_key"),
        )

    @property
    def is_on(self) -> bool:
        """Return if the switch is on."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            _LOGGER.debug(
                "Working mode switch %s using optimistic state: %s",
                self._mode_config["param"],
                self._optimistic_state,
            )
            return self._optimistic_state

        # Read state from coordinator parameters
        try:
            # Map function parameter to parameter register
            param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
            if param_key:
                param_value = self._parameter_data.get(param_key, False)
                # Handle both bool and int values
                if isinstance(param_value, bool):
                    is_enabled = param_value
                else:
                    is_enabled = param_value == 1

                _LOGGER.debug(
                    "Working mode switch %s (%s) - param_key=%s, raw_value=%s (type=%s), final_state=%s",
                    self._mode_config["param"],
                    self._serial,
                    param_key,
                    param_value,
                    type(param_value).__name__,
                    is_enabled,
                )
                return is_enabled
            else:
                _LOGGER.warning(
                    "Working mode switch %s (%s) - no param_key mapping found",
                    self._mode_config["param"],
                    self._serial,
                )
        except Exception as err:
            _LOGGER.error(
                "Error reading working mode state for %s: %s",
                self._mode_config["param"],
                err,
            )

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes: dict[str, Any] = {
            "description": self._mode_config["description"],
            "function_parameter": self._mode_config["param"],
        }

        # Add parameter register information
        param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
        if param_key:
            attributes["parameter_register"] = param_key

        # Add optimistic state indicator for debugging
        if self._optimistic_state is not None:
            attributes["optimistic_state"] = self._optimistic_state

        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._execute_working_mode(turn_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._execute_working_mode(turn_on=False)

    async def _execute_working_mode(self, turn_on: bool) -> None:
        """Execute working mode toggle, preferring local transport."""
        param = self._mode_config["param"]
        param_name = _WORKING_MODE_PARAMETERS.get(param)
        methods = _WORKING_MODE_METHODS.get(param)

        if param_name and not _local_params_can_carry(param_name):
            # Execution-time mirror of the setup version guard: the installed
            # pylxpweb cannot resolve this name to a register (e.g.
            # FUNC_PV_SELL_TO_GRID_EN before 0.9.36b6), so a local write
            # could only fail.  Degrade to the cloud method path — legacy
            # flat HYBRID creates this entity (its parameter cache is
            # cloud-fed) yet still reports a local transport.
            param_name = None

        if param_name and methods:
            # Both local and cloud paths available — use fallback pattern
            await self._execute_local_with_fallback(
                action_name=f"working mode {param}",
                parameter=param_name,
                value=turn_on,
                cloud_enable_method=methods[0],
                cloud_disable_method=methods[1],
            )
        elif param_name:
            # No dedicated cloud methods: prefer the local named write and
            # fall back to (or, without a transport, go straight to) the
            # generic cloud function-control API — the same route the
            # vendor websites use for FUNC_ bits (e.g. FUNC_RUN_WITHOUT_GRID,
            # GH #274).
            await self._execute_local_with_fallback(
                action_name=f"working mode {param}",
                parameter=param_name,
                value=turn_on,
            )
        elif self.coordinator.has_http_api() and methods:
            # Cloud-only, no local parameter mapping
            await self._execute_switch_action(
                action_name=f"working mode {param}",
                enable_method=methods[0],
                disable_method=methods[1],
                turn_on=turn_on,
                refresh_params=True,
            )
        else:
            raise HomeAssistantError(
                f"Working mode {param} not available via any transport"
            )


class EG4DSTSwitch(CoordinatorEntity[EG4DataUpdateCoordinator], SwitchEntity):
    """Switch entity for station Daylight Saving Time configuration.

    Note: This switch doesn't inherit from EG4BaseSwitch because it operates
    on station-level data rather than device-level data.
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
    ) -> None:
        """Initialize the DST switch."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_name = "Daylight Saving Time"
        self._attr_icon = "mdi:clock-time-four"
        self._attr_entity_category = EntityCategory.CONFIG

        # Build unique ID
        self._attr_unique_id = f"station_{coordinator.plant_id}_dst"

        # Optimistic state for immediate UI feedback
        self._optimistic_state: bool | None = None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information."""
        # Typed local: the mixin call resolves Any-typed under HA 2026.1.
        info: DeviceInfo | None = self.coordinator.get_station_device_info()
        return info

    @property
    def is_on(self) -> bool:
        """Return true if DST is enabled."""
        # Use optimistic state if available (during turn_on/turn_off)
        if self._optimistic_state is not None:
            return self._optimistic_state

        if not self.coordinator.data or "station" not in self.coordinator.data:
            return False

        station_data = self.coordinator.data["station"]
        dst_value = station_data.get("daylightSavingTime", False)
        _LOGGER.debug(
            "DST switch state for plant %s: daylightSavingTime=%s (type: %s)",
            self.coordinator.plant_id,
            dst_value,
            type(dst_value).__name__,
        )
        return bool(dst_value)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and "station" in self.coordinator.data
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Daylight Saving Time."""
        await self._set_dst(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Daylight Saving Time."""
        await self._set_dst(enabled=False)

    async def _set_dst(self, enabled: bool) -> None:
        """Set Daylight Saving Time state."""
        action = "Enabling" if enabled else "Disabling"
        try:
            _LOGGER.info(
                "%s Daylight Saving Time for station %s",
                action,
                self.coordinator.plant_id,
            )

            # Set optimistic state immediately for UI responsiveness
            self._optimistic_state = enabled
            self.async_write_ha_state()

            # Get station device object
            station = self.coordinator.station
            if not station:
                raise HomeAssistantError(
                    f"Station {self.coordinator.plant_id} not found"
                )

            # Use device object convenience method
            success = await station.set_daylight_saving_time(enabled=enabled)
            if not success:
                raise HomeAssistantError(
                    f"Failed to {'enable' if enabled else 'disable'} Daylight Saving Time"
                )

            _LOGGER.info(
                "Successfully %s Daylight Saving Time for station %s",
                "enabled" if enabled else "disabled",
                self.coordinator.plant_id,
            )

            # Wait 2 seconds for server to apply changes before refreshing
            await asyncio.sleep(2)

            # Request coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()

            # Clear optimistic state after refresh
            self._optimistic_state = None
            self.async_write_ha_state()

        except HomeAssistantError:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        except Exception as e:
            _LOGGER.error(
                "Failed to %s Daylight Saving Time for station %s: %s",
                action.lower(),
                self.coordinator.plant_id,
                e,
            )
            # Revert optimistic state on error
            self._optimistic_state = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action.lower()} Daylight Saving Time: {e}"
            ) from e
