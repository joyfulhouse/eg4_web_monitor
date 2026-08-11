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
    PARAM_FUNC_AC_CHARGE,
    PARAM_FUNC_AC_COUPLING_FUNCTION,
    PARAM_FUNC_BAT_SHARED,
    PARAM_FUNC_BATTERY_BACKUP_CTRL,
    PARAM_FUNC_CHARGE_LAST,
    PARAM_FUNC_EPS_EN,
    PARAM_FUNC_FEED_IN_GRID_EN,
    PARAM_FUNC_FORCED_CHG_EN,
    PARAM_FUNC_FORCED_DISCHG_EN,
    PARAM_FUNC_GREEN_EN,
    PARAM_FUNC_GRID_PEAK_SHAVING,
    PARAM_FUNC_ON_GRID_ALWAYS_ON,
    PARAM_FUNC_PV_SELL_TO_GRID_EN,
    PARAM_FUNC_RUN_WITHOUT_GRID,
    QUICK_CHARGE_DURATION_DEFAULT,
    WORKING_MODES,
)
from .coordinator import EG4DataUpdateCoordinator
from .control_discovery import setup_control_entity_discovery
from .utils import (
    flag_offgrid_control_suppression,
    is_family_control_supported,
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

# Battery backup control key suppressed on EG4_OFFGRID via the family
# capability map (FAMILY_UNSUPPORTED_CONTROL_PARAMS, GH #289): the Battery
# Backup Mode working switch (entity_key "battery_backup_ctrl",
# FUNC_BATTERY_BACKUP_CTRL — the one with a live rejected-write report).
# Same suffix-matched Repairs probe as above. The EPS Battery Backup
# switch is deliberately NOT here — see the capability map's rationale.
_SUPPRESSED_OFFGRID_BATTERY_BACKUP_KEYS: tuple[str, ...] = ("battery_backup_ctrl",)


def _supports_eps_battery_backup(device_data: dict[str, Any]) -> bool:
    """Check if device supports EPS battery backup parameter.

    The EPS battery backup switch controls a specific inverter parameter.
    Some devices (like XP series) don't support this parameter through the API,
    even though they have off-grid capability in hardware.

    NOT family-gated (#289 / PR #307 review): the SNA12K-US reference dump
    (pylxpweb docs/inverters/SNA12KUS_52XXXXXX68.md) shows FUNC_EPS_EN live
    and actively ENABLED on EG4_OFFGRID hardware, so the XP-v2
    portal-absence evidence does not generalize to the family — a family
    gate would strip a working switch from SNA-US owners. Feature-detected
    devices keep the switch; only the legacy model-string fallback for
    feature-less XP devices excludes it.

    Args:
        device_data: Device data dictionary with model and features

    Returns:
        True if the device supports the EPS battery backup parameter
    """
    features = device_data.get("features")

    # If features are available, use feature-based detection
    if features:
        # All positively identified families keep the EPS parameter switch
        return bool(features.get("supports_off_grid", True))

    # Fallback to string matching for backward compatibility
    # XP devices (12000XP, 6000XP) don't support the standard EPS parameter
    model = device_data.get("model", "Unknown")
    model_lower = model.lower()
    return "xp" not in model_lower


def _params_are_local_raw(coordinator: EG4DataUpdateCoordinator, serial: str) -> bool:
    """Whether this serial's parameter cache is (or will become) local-raw.

    Thin wrapper over :meth:`EG4DataUpdateCoordinator.params_are_local_raw`
    (the single implementation). A key the installed pylxpweb cannot decode
    from a register (see ``_local_params_can_carry``) can never appear in a
    local-raw cache, so a switch reading it would permanently report OFF.

    Unlike the number-entity property this is evaluated once at setup, so it
    passes ``include_configured=True`` to also consult the CONFIGURED
    transports: a hybrid attach that fails at startup and recovers later
    (eg4-05l) must not slip a cloud-param-only switch through the gate.
    """
    return coordinator.params_are_local_raw(serial, include_configured=True)


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


def _create_switch_entities(
    hass: HomeAssistant,
    coordinator: EG4DataUpdateCoordinator,
) -> list[EG4BaseSwitch]:
    """Build device switches applicable to current capabilities and routes."""
    entities: list[EG4BaseSwitch] = []

    if not coordinator.data:
        return entities

    # Skip device switches if no devices data
    if "devices" not in coordinator.data:
        return entities

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

                # AC Couple switch (GH #471/#472): the function param
                # FUNC_AC_COUPLING_FUNCTION, readable and writable over the
                # cloud in every mode and — since it was mapped to reg 179
                # bit 11 — over local Modbus too. Created wherever EITHER
                # route exists, so pure-LOCAL installs gain it; NOT
                # family-gated. Devices that truly lack the param read None
                # from both routes and the switch goes unavailable instead.
                # The local half needs the installed pylxpweb to decode the
                # name from a register — 0.9.39b6 carries the bit-11 mapping
                # and is the manifest floor — probed the same way the working
                # modes probe theirs, by asking the map rather than trusting a
                # version string.
                #
                # KNOWN GAP, pure LOCAL ONLY: the cloud getter's None IS the
                # capability probe — a device whose family lacks the function
                # never reports the param. Reg 179 bit 11 has no such tell: it
                # decodes to a bool on any device that answers the register,
                # so a LOCAL-only install shows the switch on every
                # control-capable inverter, reading OFF where the hardware has
                # no AC-coupled input. There is no local capability signal to
                # gate on (pylxpweb's InverterFeatures has no AC-couple or
                # smart-port flag), and inventing a model-string gate would
                # repeat the #259 mistake.
                #
                # HYBRID does NOT share this gap: wherever a cloud client
                # exists the store's tri-state gates availability (see
                # EG4ACCoupleSwitch.available). An earlier revision claimed
                # that protection while local precedence actually overrode it
                # — the phantom switch was real in HYBRID too until the
                # availability gate was fixed to consult the probe.
                if coordinator.has_http_api() or (
                    coordinator.has_configured_local_transport(serial)
                    and _local_params_can_carry(PARAM_FUNC_AC_COUPLING_FUNCTION)
                ):
                    entities.append(EG4ACCoupleSwitch(coordinator, serial))

                # Smart Load enable (GH #499). CLOUD-ONLY, and deliberately
                # NOT sharing the local-first gate above: #472 pinned reg 179
                # bit 11 for AC Couple, but FUNC_SMART_LOAD_ENABLE has no
                # pinned bit at all (179 bit 13 is still a FUNC_179_BIT13
                # placeholder in pylxpweb's table). A guessed bit is ACKed by
                # the firmware, so a wrong local write would neither fall back
                # nor fail a readback — the #476 lesson. Read through the
                # smart_load store; a device without the param goes
                # unavailable rather than showing a fake OFF.
                if coordinator.has_http_api():
                    entities.append(EG4SmartLoadSwitch(coordinator, serial))

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
                    # Battery Backup Mode is write-rejected on this family
                    # (#289) — separate issue text from the inert grid-tied
                    # controls above.
                    flag_offgrid_control_suppression(
                        hass,
                        serial,
                        device_data.get("model", "Unknown"),
                        "switch",
                        tuple(
                            f"{serial}_{key}"
                            for key in _SUPPRESSED_OFFGRID_BATTERY_BACKUP_KEYS
                        ),
                        issue_key="offgrid_battery_backup_removed",
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
                    # Family capability map (#289): controls the family's
                    # firmware rejects and the vendor portal never exposes
                    # (e.g. Battery Backup Mode on EG4_OFFGRID) are not
                    # created — the write path can only error.
                    if not is_family_control_supported(device_data, param):
                        _LOGGER.debug(
                            "Skipping working mode %s for %s (unsupported "
                            "on this inverter family, GH #289)",
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

    return entities


def _switch_route_signature(coordinator: EG4DataUpdateCoordinator) -> object:
    """Return transport/cache state that can change switch candidates."""
    serials = (coordinator.data or {}).get("devices", {})
    return (
        bool(coordinator.has_http_api()),
        bool(coordinator.is_local_only()),
        tuple(
            sorted(
                (
                    str(serial),
                    bool(coordinator.has_configured_local_transport(serial)),
                    bool(
                        coordinator.params_are_local_raw(
                            serial, include_configured=True
                        )
                    ),
                )
                for serial in serials
            )
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up station switches and continuously converge device switches."""
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    if coordinator.data and "station" in coordinator.data:
        async_add_entities([EG4DSTSwitch(coordinator)], update_before_add=True)

    setup_control_entity_discovery(
        hass,
        entry,
        coordinator,
        async_add_entities,
        lambda: _create_switch_entities(hass, coordinator),
        platform="switch",
        extra_signature=lambda: _switch_route_signature(coordinator),
    )


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
# Kept NUMERICALLY EQUAL to base_entity.RETAINED_OPTIMISTIC_TTL on purpose:
# after a quick-charge write-ok + refresh-fail both holds arm together and
# only equal TTLs keep them expiring together. Change both or neither.
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

    def _cache_state(self) -> bool | None:
        """Peek genuine status data: mask the #296 pending-state hold too.

        The base peek masks only ``_optimistic_state``; quick charge's
        ``is_on`` would then fall through to the ``_pending_state`` hold,
        which (a) echoes the commanded value back — false convergence for
        the #362 retention — and (b) can MUTATE ``_pending_state`` as a side
        effect of the read (the hold is consumed on a fresh confirming or
        expired read). Masking it keeps the peek side-effect-free and
        reading actual device/status truth, per the base contract.
        """
        saved = self._pending_state
        self._pending_state = None
        try:
            return super()._cache_state()
        finally:
            self._pending_state = saved

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

        pylxpweb's enable/disable prefer the local transport — the start
        writes the reg 233 activation together with the reg 234 duration
        (the stored preference) in one contiguous frame, falling back to
        cloud on failure (HYBRID). On the EG4_OFFGRID family register 233 is
        firmware-rejected, so the cloud-direct callables are used instead
        (#296). On success the
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


class EG4CloudStoreSwitch(EG4BaseSwitch):
    """Switch whose state lives in a cloud-only device-data store.

    CLOUD-ONLY controls: the portal writes a function param for which no local
    register is pinned, so writes route through the cloud client in every mode
    and state reads from the coordinator's dedicated store (throttled 5-minute
    getter + carry-forward + post-write seeding), never the parameter cache — a
    HYBRID parameter refresh rebuilds the cache from local registers alone and
    would wipe any cloud-seeded value (PR #380 review P1).

    The base class's full-refresh write envelope is deliberately NOT used: the
    store IS the state source and the acknowledged write seeds it directly, so
    a full coordinator refresh would burn API calls without re-reading the
    throttled store.
    """

    #: Store key under the device data holding this switch's ``enabled`` field.
    _store_key: str
    #: pylxpweb control-endpoint writer method.
    _cloud_method: str
    #: Minimum pylxpweb version providing ``_cloud_method``.
    _min_pylxpweb: str
    #: Human label used in log and error messages.
    _label: str

    @property
    def _stored_enabled(self) -> bool | None:
        """The function-param state from the dedicated store."""
        store = self._device_data.get(self._store_key) or {}
        value = store.get("enabled")
        return value if isinstance(value, bool) else None

    @property
    def _state_known(self) -> bool:
        """Whether a real state has been observed for this control.

        The one thing :attr:`available` gates on beyond coordinator health,
        factored out so a subclass with ADDITIONAL state sources overrides
        THIS rather than ``available`` itself. A subclass that overrode
        ``available`` would reach this class through ``super().available``
        and silently re-acquire the cloud-store gate below — which is how the
        AC Couple switch lost its pure-LOCAL availability when the two
        features first merged, caught by #472's own tests.
        """
        return self._stored_enabled is not None

    @property
    def available(self) -> bool:
        """Available only while a state is known (or mid-write).

        Absent state — first cloud fetch pending, a pylxpweb predating the
        getter, or a device whose family genuinely lacks the function param —
        must show unavailable, never a fake OFF.
        """
        if not super().available:
            return False
        if self._optimistic_state is not None:
            return True
        return self._state_known

    @property
    def is_on(self) -> bool | None:
        """Return the function state."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        return self._stored_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the function."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the function."""
        await self._async_set_enabled(False)

    def _note_written(self, enabled: bool) -> None:
        """Seed the acknowledged state into this switch's store."""
        raise NotImplementedError

    async def _async_set_enabled(self, enabled: bool) -> None:
        """Write the function param through the cloud client."""
        client = self.coordinator.require_client()
        method = getattr(client.api.control, self._cloud_method, None)
        if method is None:
            raise HomeAssistantError(
                f"Failed to set {self._label}: pylxpweb is missing "
                f"{self._cloud_method} (requires >= {self._min_pylxpweb})"
            )
        action = "enable" if enabled else "disable"
        _LOGGER.info("Setting %s to %sd for %s", self._label, action, self._serial)
        self._optimistic_state = enabled
        self.async_write_ha_state()
        try:
            result = await method(self._serial, enabled)
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to {action} {self._label} for {self._serial}"
                )
        except HomeAssistantError:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        except Exception as e:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to {action} {self._label} for {self._serial}: {e}"
            ) from e
        # Seed the dedicated store (sibling-preserving) with the acknowledged
        # state; the next throttled getter read confirms. Clear the
        # optimistic state first — the seed fires listeners, which publish
        # the store value.
        self._optimistic_state = None
        self._note_written(enabled)


class EG4ACCoupleSwitch(EG4CloudStoreSwitch):
    """AC Couple function switch (GH #471/#472), family-neutral.

    Toggles the inverter-level ``FUNC_AC_COUPLING_FUNCTION`` — enabling or
    disabling the AC-coupled source on the smart port outright, regardless
    of the Start/End SOC window (GH #352's number pair; portal wire name
    confirmed by two independent reporters in that issue). Distinct from the
    GridBOSS per-port ``FUNC_AC_COUPLE_EN_{n}`` functions.

    Two state sources, LOCAL-FIRST (GH #472):

    * With a local transport attached, the param resolves from holding
      register 179 bit 11, so it rides the ordinary parameter cache like
      every other reg-179 function (Export PV Only, Grid Peak Shaving).
      LOCAL-only installs gain the switch outright; HYBRID gets a local read
      that no longer waits on the 5-minute cloud getter.
    * The cloud ``ac_couple_soc`` store (throttled getter + carry-forward +
      post-write seeding) stays the source for pure CLOUD, and the fallback
      whenever the parameter cache carries no value — the SOC pair beside it
      is still cloud-only (no pinned register for those holdParams), so the
      store is fetched regardless.

    FRESHNESS TRADE-OFF, deliberate: in HYBRID the parameter cache refreshes
    on the parameter tier (``parameter_refresh_interval``, default 60 min)
    while that cloud store refreshes every 5 minutes, so preferring the
    local value can surface a PORTAL-side toggle later than #471 did. That
    is the behavior of every other reg-179 switch (Export PV Only, Grid Peak
    Shaving) and is what local-first means here; changes made from HA are
    unaffected, since the write path updates the cache in place. Users who
    want portal changes reflected faster lower the parameter interval.

    Bit 11 is NOT pinned by this project's raw↔named lockstep standard. It
    ships on lineage inference — the Luxpower Modbus doc and the
    ant0nkr/luxpower-ha-integration map both place AC coupling there, that
    reg-179 layout is the one whose bits 3/7/9/10 are hardware-proven on EG4
    hardware, and #471's reporter has driven the control through the mapping
    on his LXP — exactly the #476 green-mode precedent. Writes are
    local-first with cloud fallback, and a local write forces a parameter
    re-read of register 179 before returning, so a write that fails to land
    is visible within the cycle rather than at the next scheduled parameter
    refresh. A write that lands on the WRONG bit would still ACK, which no
    readback can catch — that is what the lockstep toggle requested in #472
    would rule out.

    The base class's full-refresh write envelope is deliberately NOT used on
    the pure-cloud path: the store IS the state source there and the
    acknowledged write seeds it directly (``note_ac_couple_soc_written``),
    so a full coordinator refresh would burn API calls without re-reading
    the throttled store.

    The cloud half of all this — the store read, availability on a known
    state, and the cloud write envelope — lives in EG4CloudStoreSwitch,
    shared with EG4SmartLoadSwitch (GH #499). Everything LOCAL-first is
    overridden here and must stay here: Smart Load's function param has no
    pinned bit at all, so a local path on the shared base would hand it a
    guessed-bit write that the firmware ACKs.
    """

    _store_key = "ac_couple_soc"
    _cloud_method = "set_inverter_ac_couple_enabled"
    _min_pylxpweb = "0.9.39b3"
    _label = "AC couple"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the AC couple switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="ac_couple",
            name="AC Couple",
            icon="mdi:solar-power-variant",
            translation_key="ac_couple",
        )
        # Version guard, evaluated once: an installed pylxpweb that cannot
        # decode the name from a register can neither surface it in a
        # local-raw parameter cache nor accept a local named write, so such
        # installs stay on the cloud store exactly as they did before #472.
        self._local_param_supported = _local_params_can_carry(
            PARAM_FUNC_AC_COUPLING_FUNCTION
        )

    @property
    def _uses_local_param(self) -> bool:
        """Whether the reg-179 bit-11 parameter path applies right now."""
        return self._local_param_supported and self.coordinator.has_local_transport(
            self._serial
        )

    @property
    def _local_enabled(self) -> bool | None:
        """FUNC_AC_COUPLING_FUNCTION state from the parameter cache.

        None when the local path does not apply or the key has not arrived
        yet — key ABSENCE is unknown, not OFF (#497).
        """
        if not self._uses_local_param:
            return None
        value = self._parameter_data.get(PARAM_FUNC_AC_COUPLING_FUNCTION)
        if isinstance(value, bool):
            return value
        return bool(value) if isinstance(value, int) else None

    # _stored_enabled (the cloud-store read) comes from EG4CloudStoreSwitch
    # via _store_key — byte-identical to the copy this class used to carry.

    @property
    def _capability_known(self) -> bool:
        """Whether a source has positively evidenced the function exists.

        The single notion behind both :attr:`available` and :attr:`is_on`,
        so an unsupported device cannot be unavailable-but-confidently-OFF.
        """
        if self.coordinator.has_http_api():
            return self._stored_enabled is not None
        return self._local_enabled is not None

    @property
    def _state_known(self) -> bool:
        """Available only while the capability is known (or mid-write).

        The CLOUD store is the capability probe wherever a cloud client
        exists — including HYBRID. A device whose family lacks the function
        never reports the param, so the store's ``enabled`` stays None and
        the switch is unavailable.

        Register 179 bit 11 CANNOT serve as that probe: it decodes to a bool
        on any device that answers the register, so an unsupported device
        yields a confident False. Gating HYBRID on the local value alone
        therefore published a phantom, toggleable OFF switch on hardware
        with no AC-coupled input — the local read is a state source, never
        an existence proof.

        Pure LOCAL has no cloud probe to consult and keeps the documented
        gap: there the local decode is all there is (see the creation gate).
        The startup window where the store has not been fetched yet reads
        unavailable, exactly as it did before #472.

        Overrides the shared predicate rather than ``available`` itself: the
        base's ``available`` is unchanged (coordinator health, then optimistic
        state, then this), but overriding ``available`` here would route
        through EG4CloudStoreSwitch's cloud-store gate on the way to
        EG4BaseSwitch and make pure LOCAL permanently unavailable.
        """
        return self._capability_known

    @property
    def is_on(self) -> bool | None:
        """Return the AC couple function state (local first, then cloud).

        Unknown capability reads unknown, never a confident OFF — the same
        guarantee :attr:`available` gives, kept in lockstep with it so the
        two cannot disagree about an unsupported device.
        """
        if self._optimistic_state is not None:
            return self._optimistic_state
        if not self._capability_known:
            return None
        local = self._local_enabled
        return local if local is not None else self._stored_enabled

    # async_turn_on/off come from EG4CloudStoreSwitch, which delegates to
    # _async_set_enabled below (this class's local-first override).

    async def _verify_local_write(self) -> None:
        """Re-read register 179 to verify an acknowledged local write.

        The shared local-write envelope only mutates the cached value and
        runs a coordinator DATA refresh; parameters live on their own tier,
        so without this the register is not re-read until the next scheduled
        parameter cycle (default 60 min) and nothing verifies the write.
        That is tolerable for a hardware-pinned bit — bit 11 is inferred, so
        the readback is the point. It is also what lets a LOCAL/CLOUD
        disagreement surface within the cycle.

        Forced, but through the same public method the cloud path uses, so
        pylxpweb's #282 partial-read carry-forward and retry floor apply
        unchanged. Never raises: a failed verification must not fail a
        command the device already acknowledged.

        On failure the commanded value keeps showing — that part is fine —
        but it must not show UNVERIFIED indefinitely, which is what would
        happen if parameter reads kept failing (cache already seeded,
        optimistic state already cleared). So the device is queued for a
        floored per-device retry: bounded at roughly the #282 two-minute
        attempt floor rather than the full hourly window.
        """
        if await self.coordinator.async_refresh_device_parameters(self._serial):
            return
        self.coordinator.note_parameter_verification_pending(self._serial)
        _LOGGER.warning(
            "AC couple write acknowledged for %s but the verifying parameter "
            "re-read did not complete; showing the commanded value and "
            "retrying the read shortly",
            self._serial,
        )

    async def _async_set_enabled(self, enabled: bool) -> None:
        """Write FUNC_AC_COUPLING_FUNCTION, local-first when reg 179 applies.

        Overrides the shared cloud-only writer: EG4CloudStoreSwitch's version
        always routes through the cloud client, which is correct for Smart
        Load and correct here ONLY once the local route is ruled out below.
        """
        if self._uses_local_param:
            # Local named write (pylxpweb does the sibling-preserving
            # read-modify-write on reg 179) with cloud function-control
            # fallback — the same route, and the same seeding, every other
            # reg-179 switch uses.
            #
            # Deliberately NOT seeded into the cloud ``ac_couple_soc`` store:
            # while bit 11 is unpinned that store is an INDEPENDENT
            # observation of the same function, and seeding it would mask a
            # disagreement between what we wrote locally and what the portal
            # reports — the exact signal #472's lockstep capture is after.
            # The readback runs ONLY on the local route (see
            # _verify_local_write). A cloud FALLBACK write already refreshes
            # parameters inside its own envelope, so running both would
            # spend two forced reads on one logical write.
            await self._execute_local_with_fallback(
                action_name="AC couple",
                parameter=PARAM_FUNC_AC_COUPLING_FUNCTION,
                value=enabled,
                after_local_write=self._verify_local_write,
            )
            return

        # Pure-cloud route: identical to the shared implementation, down to
        # every message string — the class attributes above reproduce them
        # exactly — so it is delegated rather than duplicated. The store seed
        # lands through _note_written below.
        await super()._async_set_enabled(enabled)

    def _note_written(self, enabled: bool) -> None:
        """Seed the acknowledged cloud state into the ac_couple_soc store."""
        self.coordinator.note_ac_couple_soc_written(self._serial, "enabled", enabled)


class EG4SmartLoadSwitch(EG4CloudStoreSwitch):
    """Smart Load enable switch (GH #499, cloud client required).

    Toggles the inverter-level ``FUNC_SMART_LOAD_ENABLE`` — the parent
    enable/disable of the smart load port, above the Start/End SOC, PV-power
    and voltage thresholds that decide WHEN it energizes within that. Same
    portal panel as Grid Always On (#484), which shipped first.

    Distinct from the GridBOSS/MID per-port ``FUNC_SMART_LOAD_EN_{n}``
    functions, which address different hardware.

    The WRITE path is hardware-confirmed: the #499 reporter toggled the switch
    in Home Assistant and watched the portal reflect it (2026-08-02, 12000XP).
    Disabled by default because it only matters once the smart load port is
    configured.

    CONFIG category to sit beside Grid Always On and the five threshold
    numbers from the same portal panel — shipping without a category filed it
    under Controls while every sibling was under Configuration (#499 report).
    """

    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.CONFIG

    _store_key = "smart_load"
    _cloud_method = "set_inverter_smart_load_enabled"
    _min_pylxpweb = "0.9.39b6"
    _label = "Smart Load"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the Smart Load switch."""
        super().__init__(
            coordinator=coordinator,
            serial=serial,
            entity_key="smart_load",
            name="Smart Load",
            icon="mdi:home-lightning-bolt",
            translation_key="smart_load",
        )

    def _note_written(self, enabled: bool) -> None:
        self.coordinator.note_smart_load_written(self._serial, "enabled", enabled)


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
        """Return True if off-grid mode is enabled, None when unknown.

        An absent FUNC_GREEN_EN key means UNKNOWN, not off: a local
        parameter refresh replaces the serial's parameter dict wholesale
        (coordinator_mixins._refresh_device_parameters), so a partial
        read that missed register 110 must not flip a cloud-confirmed/
        seeded "on" to "off". Local reads decode the hardware-verified
        register 110 bit 14 on every family (pylxpweb >= 0.9.39b4, #476).
        """
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            return self._optimistic_state

        # Check parameter data from coordinator
        value = self._parameter_data.get(PARAM_FUNC_GREEN_EN)
        if value is None:
            return None
        return bool(value)

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable off-grid mode."""
        await self._execute_local_with_fallback(
            action_name="off-grid mode (Green Mode)",
            parameter=PARAM_FUNC_GREEN_EN,
            value=True,
            cloud_enable_method="enable_green_mode",
            cloud_disable_method="disable_green_mode",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable off-grid mode."""
        await self._execute_local_with_fallback(
            action_name="off-grid mode (Green Mode)",
            parameter=PARAM_FUNC_GREEN_EN,
            value=False,
            cloud_enable_method="enable_green_mode",
            cloud_disable_method="disable_green_mode",
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
    # Register 110, bit 4 (GH #177) — "Charge Last" in the portal. The
    # name resolves locally across the supported register maps. Deliberately
    # absent from _WORKING_MODE_METHODS: the cloud path goes through the
    # generic function-control API — the same route the vendor website uses.
    "FUNC_CHARGE_LAST": PARAM_FUNC_CHARGE_LAST,
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
    # Register 110, bit 3 (GH #288) — "Share Battery" in the portals. Same
    # bit in pylxpweb's base and SNA register-110 tables, so the name
    # resolves locally on every supported install. Deliberately absent from
    # _WORKING_MODE_METHODS: the cloud path goes through the generic
    # function-control API with FUNC_BAT_SHARED — the exact call the
    # website makes (reporter-verified).
    "FUNC_BAT_SHARED": PARAM_FUNC_BAT_SHARED,
    # Register 179, bit 15 (GH #559) — Grid Always On. App-write-path-proven
    # via EG4 mobile Local12KSetFragment.getBitByFunction (smali); 4-for-4
    # against confirmed anchors bits 3/7/9/10. Not hardware-toggle-proven —
    # readback-verify stays on. Requires pylxpweb with the bit-15 mapping
    # (PR #270); older installs are handled by _local_params_can_carry().
    "FUNC_ON_GRID_ALWAYS_ON": PARAM_FUNC_ON_GRID_ALWAYS_ON,
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

        # Niche modes register disabled by default (e.g. Share Battery,
        # GH #288 — multi-inverter shared-bank setups only). Truthiness (not
        # an ``is False`` identity check) so a future non-bool falsy value
        # (0, None, "") can't silently ship the entity enabled (#310).
        if not mode_config.get("enabled_default", True):
            self._attr_entity_registry_enabled_default = False

    @property
    def _state_key_present(self) -> bool:
        """Whether the parameter cache actually carries this mode's state key.

        Distinguishes "the device reports this function OFF" from "no value
        has ever arrived" — the two the ``.get(param_key, False)`` read below
        otherwise collapses into a confident False.
        """
        param_key = FUNCTION_PARAM_MAPPING.get(self._mode_config["param"])
        return bool(param_key) and param_key in self._parameter_data

    @property
    def available(self) -> bool:
        """Return if the switch is available.

        Modes flagged ``requires_known_state`` go UNAVAILABLE while their
        state key is absent, rather than presenting a confident, toggleable
        OFF. That matters for a mode created without a family gate (GH #484
        Grid Always On): on a device whose cloud read omits the param — a
        family beyond those probed, or simply a parameter read that has not
        landed yet — a fake OFF is indistinguishable from the real thing.
        Same guarantee the AC Couple switch's override gives (GH #471), which
        is the precedent Grid Always On's family-neutral gate is modelled on.

        Charge Last and Share Battery opted in for the same reason (GH #497):
        both are ungated by family, so they carried the identical exposure.
        Their state does come from register 110 (bits 4 and 3) on LOCAL and
        HYBRID, but that narrows the absent window rather than closing it —
        a bit-field register decodes every one of its names on each
        successful read, so the keys are present whatever the bits' values,
        and what remains is the pre-first-read window.

        Still OPT-IN rather than the shared base: the remaining modes are
        family- or capability-gated, and flipping them would change
        long-standing behavior during the pre-first-parameter-read window
        for no established exposure.
        """
        if not super().available:
            return False
        if not self._mode_config.get("requires_known_state"):
            return True
        if self._optimistic_state is not None:
            return True
        return self._state_key_present

    @property
    def is_on(self) -> bool | None:
        """Return if the switch is on (None when the state is unknown)."""
        # Use optimistic state if available (for immediate UI feedback)
        if self._optimistic_state is not None:
            _LOGGER.debug(
                "Working mode switch %s using optimistic state: %s",
                self._mode_config["param"],
                self._optimistic_state,
            )
            return self._optimistic_state

        # Absent state must not read as OFF for modes that opted in — see
        # available(). Unflagged modes keep the historical False default.
        if (
            self._mode_config.get("requires_known_state")
            and not self._state_key_present
        ):
            return None

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
        legacy_attrs = self._mode_config.get("legacy_attrs")
        if isinstance(legacy_attrs, dict):
            # A folded standalone switch may opt into its historical attribute
            # names and None-on-empty behavior without changing other modes.
            legacy_attributes = {
                attribute_name: self._parameter_data[parameter_key]
                for attribute_name, parameter_key in legacy_attrs.items()
                if parameter_key in self._parameter_data
                and self._parameter_data[parameter_key] is not None
            }
            if self._optimistic_state is not None:
                legacy_attributes["optimistic_state"] = self._optimistic_state
            return legacy_attributes if legacy_attributes else None

        # A known-state mode with no known state publishes nothing, matching
        # the legacy branch above, which returns None when it has no value
        # (GH #497 review: Charge Last returned None on an absent key while
        # Share Battery still returned a full metadata dict — two switches of
        # the same class disagreeing on the same input). The entity is
        # unavailable in this state, so a dict here is decoration on a control
        # that is reporting "I do not know".
        #
        # Scoped to requires_known_state deliberately. Unflagged modes keep
        # publishing their metadata unconditionally (pinned for ac_charge_mode),
        # and the reverse alignment — giving Charge Last the generic attrs — is
        # prohibited: legacy_attrs exists to preserve its exact pre-fold
        # attribute shape, which is pinned to EXCLUDE them.
        if (
            self._mode_config.get("requires_known_state")
            and not self._state_key_present
            and self._optimistic_state is None
        ):
            return None

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
        action_name = self._mode_config.get("action_name", f"working mode {param}")
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
                action_name=action_name,
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
                action_name=action_name,
                parameter=param_name,
                value=turn_on,
            )
        elif self.coordinator.has_http_api() and methods:
            # Cloud-only, no local parameter mapping. A transport can still
            # be attached here (the version guard above degrades legacy
            # flat-HYBRID installs to this branch), so seed the parameter
            # cache with the acknowledged value like the fallback path —
            # otherwise a link-down write reverts to the stale pre-write
            # state until link recovery (#310). Pure-cloud stays unseeded
            # via the has_local_transport guard in the seeding helper.
            await self._execute_switch_action(
                action_name=action_name,
                enable_method=methods[0],
                disable_method=methods[1],
                turn_on=turn_on,
                refresh_params=True,
                seed_param_key=FUNCTION_PARAM_MAPPING.get(param),
            )
        elif self.coordinator.has_http_api():
            # Cloud-only with NEITHER a local parameter mapping NOR dedicated
            # pylxpweb enable/disable methods: drive the generic
            # function-control API — the exact call the vendor portal makes
            # for FUNC_ bits. Without this branch such a mode would fall
            # through to the raise below and every write would fail, so a
            # mode may omit both mappings only because this route exists.
            # Seeding is a no-op on pure cloud (the helper guards on
            # has_local_transport). (Grid Always On used this branch until
            # GH #559 pinned reg 179 bit 15 and wired it locally.)
            await self._execute_cloud_function_action(
                action_name=action_name,
                parameter=param,
                value=turn_on,
                seed_param_key=FUNCTION_PARAM_MAPPING.get(param),
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
