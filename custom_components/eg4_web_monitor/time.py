"""Time platform for EG4 Web Monitor integration.

Exposes the inverter's packed-time schedules as native Home Assistant ``time``
entities: per schedule type, 2 or 3 daily windows × (start, end). Each schedule
occupies ``2 × windows`` consecutive holding registers and each 16-bit register
packs hour (low byte) and minute (high byte) — verified by the live cloud
register probes in pylxpweb ``docs/inverters/``. Seven families are exposed:

- Classic (AC Charge/First, Forced Charge/Discharge; issues #277 + #295): 3
  windows, cloud params ``{prefix}_{START|END}_{HOUR|MINUTE}{suffix}`` with
  window 1 unsuffixed and windows 2/3 suffixed ``_1``/``_2``.
- writeTime (Generator/Off-Grid/Peak Shaving; pylxpweb PR #209): all windows
  suffixed ``_1..._N`` (no bare window); cloud writes use pylxpweb's atomic
  ``write_time_parameter`` (portal ``writeTime`` endpoint). Peak Shaving reads
  back under the interleaved ``LSP_HOLD_DIS_CHG_POWER_TIME_{n}`` params.

The schedule types, their registers, cloud parameter prefixes, window counts,
suffix schemes and family gates all come from the declarative
``SCHEDULE_TIME_TYPES`` table in const/modbus.py (mirroring pylxpweb's
``SCHEDULE_CONFIGS``). All schedule time entities are registry-disabled by
default (opt-in advanced feature).

Write paths:
- LOCAL / HYBRID with an attached transport: one packed register write (FC06)
  via :meth:`EG4DataUpdateCoordinator.write_register` (uniform across families).
- CLOUD: writeTime families use the atomic ``write_time_parameter``; classic
  families use the portal's separate ``*_HOUR`` + ``*_MINUTE`` writes.

Read path: the coordinator's parameter poll. Locally the packed raw values
surface under pylxpweb's parameter-cache keys (see each spec's
``local_param_keys`` alias chains); the cloud returns the separated
hour/minute values (or Peak Shaving's LSP params).
"""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.time import TimeEntity
else:
    from homeassistant.components.time import TimeEntity

from pylxpweb.constants import pack_time, unpack_time
from pylxpweb.endpoints.control import ControlEndpoints

from . import EG4ConfigEntry
from .base_entity import EG4BaseTime
from .const import SCHEDULE_TIME_TYPES, ScheduleTimeSpec
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    async_write_with_cloud_fallback,
    flag_offgrid_control_suppression,
    is_hybrid_family,
    is_offgrid_family,
    is_supported_control_model,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3

# The Generator/Off-Grid/Peak Shaving families write via pylxpweb's atomic
# ``write_time_parameter`` (portal writeTime endpoint). Older pylxpweb releases
# lack it, so those entities are not created there — the manifest floor bump
# lands at release time, not in this change. AC Charge/First/Forced families
# are unaffected.
_SUPPORTS_WRITE_TIME = hasattr(ControlEndpoints, "write_time_parameter")
_logged_missing_write_time = False


def _schedule_supported(spec: ScheduleTimeSpec, device_data: dict[str, Any]) -> bool:
    """Whether a device should get a schedule type's entities.

    Gates (see the ``ScheduleTimeSpec.gate`` docs in const/modbus.py):
    - ``offgrid``: only positively-identified EG4_OFFGRID (SNA) hardware —
      the portal shows the AC First section only on the SNA working-mode
      page (#295). Fails closed when the family is unknown.
    - ``hybrid`` / ``hybrid_or_offgrid``: only positively-identified
      EG4_HYBRID (plus EG4_OFFGRID for Generator charge) hardware — the
      families verified on the FlexBOSS21. Fails closed.
    - ``control`` / ``control_grid_tied``: the family-aware control gate
      (#259/#281); ``control_grid_tied`` additionally suppresses the
      entities on positively-identified EG4_OFFGRID hardware — the forced
      discharge schedule matches the forced discharge number controls
      (PR #220 / issue #197) and the forced charge schedule is
      cloud-rejected on the family (REMOTE_SET_ERROR on a 12000XP v2 plus
      portal absence, issue #295 live report).

    The writeTime families are additionally skipped when the installed
    pylxpweb is too old to provide ``write_time_parameter``.
    """
    if spec.write_via_time_api and not _SUPPORTS_WRITE_TIME:
        return False
    if spec.gate == "offgrid":
        return is_offgrid_family(device_data)
    if spec.gate == "hybrid":
        return is_hybrid_family(device_data)
    if spec.gate == "hybrid_or_offgrid":
        return is_hybrid_family(device_data) or is_offgrid_family(device_data)
    if not is_supported_control_model(device_data):
        return False
    return not (spec.gate == "control_grid_tied" and is_offgrid_family(device_data))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor time entities from a config entry."""
    coordinator = config_entry.runtime_data
    entities: list[TimeEntity] = []

    global _logged_missing_write_time
    if not _SUPPORTS_WRITE_TIME and not _logged_missing_write_time:
        _logged_missing_write_time = True
        _LOGGER.info(
            "Installed pylxpweb lacks write_time_parameter; Generator/Off-Grid/"
            "Peak Shaving schedule time entities are not created (upgrade pylxpweb "
            "to enable them)"
        )

    for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
        if device_data.get("type") != "inverter":
            continue

        entities.extend(
            EG4ScheduleTimeEntity(coordinator, serial, spec, window, is_end=is_end)
            for spec in SCHEDULE_TIME_TYPES
            if _schedule_supported(spec, device_data)
            for window in range(1, spec.windows + 1)
            for is_end in (False, True)
        )

        # Forced Charge schedule times were created on EG4_OFFGRID hardware in
        # beta.20/21 before the family gate landed (#295 live report: cloud
        # REMOTE_SET_ERROR + portal absence). One-shot Repairs notice for
        # anyone who had one registered — same machinery as the #307 Battery
        # Backup gate. Suffix-based probe: time unique IDs embed the model
        # slug ({clean_model}_{serial}_{key}); all variants end with
        # {serial}_{key}.
        if is_offgrid_family(device_data):
            flag_offgrid_control_suppression(
                hass,
                serial,
                device_data.get("model", "Unknown"),
                "time",
                tuple(
                    f"{serial.lower()}_forced_charge_{boundary}_time_{window}"
                    for boundary in ("start", "end")
                    for window in (1, 2, 3)
                ),
                issue_key="offgrid_forced_charge_times_removed",
            )

    if entities:
        _LOGGER.info("Setup complete: %d time entities created", len(entities))
        async_add_entities(entities, update_before_add=False)


class EG4ScheduleTimeEntity(EG4BaseTime, TimeEntity):
    """One boundary (start or end) of one schedule window.

    Every schedule time entity is created registry-disabled by default
    (explicit product decision) — schedules are an advanced feature users opt
    into. Users who previously enabled a window keep it (the registry persists;
    the default only affects new registrations). The window numbering is
    user-facing (1-N); the firmware/cloud period index is ``window - 1``.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: ScheduleTimeSpec,
        window: int,
        *,
        is_end: bool,
    ) -> None:
        """Initialize the schedule time entity.

        Args:
            coordinator: The data update coordinator.
            serial: Inverter serial number.
            spec: The schedule type's declarative table entry.
            window: User-facing window number (1-3).
            is_end: False for the window start boundary, True for the end.
        """
        super().__init__(coordinator, serial)
        self._spec = spec
        self._window = window
        self._is_end = is_end
        # Set when a successful write's follow-up parameter refresh failed:
        # the optimistic value is retained (the hardware holds the new time;
        # showing the stale cache would look like a silent revert) until
        # fresh parameter data arrives. ``_pre_write_value`` remembers what
        # the cache decoded to before the write so freshness is detectable.
        self._optimistic_retained = False
        self._pre_write_value: time | None = None

        boundary = "end" if is_end else "start"
        key = f"{spec.key}_{boundary}_time_{window}"
        self._attr_translation_key = key
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_{key}"
        self._attr_icon = "mdi:clock-end" if is_end else "mdi:clock-start"
        # All schedule time entities are opt-in (registry-disabled by default).
        self._attr_entity_registry_enabled_default = False

        # Packed schedule register: two registers per window (start, end)
        # from the schedule's base register.
        self._register = spec.base_register + (window - 1) * 2 + (1 if is_end else 0)

        # Cloud window suffix. Classic families leave window 1 unsuffixed and
        # suffix windows 2/3 ``_1``/``_2``; the writeTime families number ALL
        # windows ``_1..._N`` (portal holdParam convention, live register
        # probes).
        if spec.bare_first_window:
            suffix = "" if window == 1 else f"_{window - 1}"
        else:
            suffix = f"_{window}"

        # Cloud read param names. Peak Shaving reports its schedule under the
        # interleaved LSP_HOLD_DIS_CHG_POWER_TIME_{n} params rather than the
        # {prefix}_{START|END}_{HOUR|MINUTE} convention.
        if spec.read_lsp_base is not None:
            lsp_base = spec.read_lsp_base + (window - 1) * 4 + (2 if is_end else 0)
            self._cloud_hour_param = f"LSP_HOLD_DIS_CHG_POWER_TIME_{lsp_base}"
            self._cloud_minute_param = f"LSP_HOLD_DIS_CHG_POWER_TIME_{lsp_base + 1}"
        else:
            self._cloud_hour_param = (
                f"{spec.cloud_prefix}_{boundary.upper()}_HOUR{suffix}"
            )
            self._cloud_minute_param = (
                f"{spec.cloud_prefix}_{boundary.upper()}_MINUTE{suffix}"
            )

        # Composite writeTime param (writeTime families only): the portal's
        # atomic hour+minute boundary write target.
        self._cloud_time_param = f"{spec.cloud_prefix}_{boundary.upper()}_TIME{suffix}"

    # ── Value read ──────────────────────────────────────────────────

    def _params_are_local_raw(self) -> bool:
        """Whether this serial's parameter cache holds raw register values.

        Thin wrapper over :meth:`EG4DataUpdateCoordinator.params_are_local_raw`
        (the single implementation): a local-raw cache surfaces the raw packed
        schedule registers, while cloud-populated caches hold the separated
        hour/minute values instead.
        """
        return self.coordinator.params_are_local_raw(self.serial)

    def _decode_packed(self, params: dict[str, Any]) -> time | None:
        """Decode the packed register value from a local parameter cache."""
        for key in self._spec.local_param_keys[self._register]:
            raw = params.get(key)
            if raw is None or isinstance(raw, bool):
                # A bool means a bit-field style decode — never a packed
                # time; keep trying the fallback keys.
                continue
            packed = int(raw)
            hour, minute = unpack_time(packed)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return time(hour=hour, minute=minute)
            # Present but not a plausible packed time (corrupt read).
            return None
        return None

    def _decode_cloud(self, params: dict[str, Any]) -> time | None:
        """Decode the separated hour/minute cloud parameters."""
        hour_raw = params.get(self._cloud_hour_param)
        minute_raw = params.get(self._cloud_minute_param)
        if hour_raw is None or minute_raw is None:
            return None
        hour = int(hour_raw)
        minute = int(minute_raw)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)
        return None

    def _decode_from_cache(self) -> time | None:
        """Decode the boundary from the parameter cache (ignoring optimistic)."""
        params = self._parameter_data
        if not params:
            return None
        try:
            if self._params_are_local_raw():
                return self._decode_packed(params)
            return self._decode_cloud(params)
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> time | None:
        """Return the schedule boundary from the parameter cache."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self._decode_from_cache()

    @property
    def available(self) -> bool:
        """Unavailable until the schedule parameter has been polled."""
        return super().available and self.native_value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear a retained optimistic value once fresh parameter data arrives.

        A retained value exists only when a successful write's follow-up
        refresh failed (see :meth:`async_set_value`). Fresh data is anything
        that no longer decodes to the pre-write cache value — the written
        time coming back, or a newer portal-made change; a coordinator tick
        that still carries the stale pre-write value keeps the optimistic
        value (clearing there would be the silent-revert this guards
        against, just delayed one poll).
        """
        if self._optimistic_retained and self._optimistic_value is not None:
            current = self._decode_from_cache()
            if current == self._optimistic_value or current != self._pre_write_value:
                self._optimistic_value = None
                self._optimistic_retained = False
                self._pre_write_value = None
        super()._handle_coordinator_update()

    # ── Value write ─────────────────────────────────────────────────

    async def async_set_value(self, value: time) -> None:
        """Write the schedule boundary (local packed / cloud named).

        Overnight windows (end earlier than start, e.g. 20:00 → 08:00) are
        firmware-legal, so no cross-validation against the paired boundary
        is performed. Seconds are dropped — the register stores hour/minute.

        Optimistic handling (PR #283 review P1/P2): the optimistic value is
        cleared on write failure (after the cloud path's partial-failure
        convergence re-read the device) and after a successful follow-up
        refresh; when the write succeeded but the refresh failed, it is
        retained — the hardware holds the new time, and falling back to the
        stale cache would look like a silent revert — until fresh parameter
        data arrives (:meth:`_handle_coordinator_update`).
        """
        boundary_value = time(hour=value.hour, minute=value.minute)
        packed = pack_time(boundary_value.hour, boundary_value.minute)
        _LOGGER.info(
            "Setting %s %s time %d for %s to %s",
            self._spec.key,
            "end" if self._is_end else "start",
            self._window,
            self.serial,
            boundary_value.isoformat(timespec="minutes"),
        )

        pre_write_value = self._decode_from_cache()
        self._optimistic_retained = False
        self._pre_write_value = None
        self._optimistic_value = boundary_value
        self.async_write_ha_state()

        write_ok = False
        refresh_ok = False
        try:

            async def _local_write() -> None:
                await self.coordinator.write_register(
                    self._register, packed, serial=self.serial
                )

            await async_write_with_cloud_fallback(
                self.coordinator,
                self.serial,
                f"{self._spec.key} schedule time",
                local_write=_local_write,
                cloud_write=lambda: self._async_write_cloud(boundary_value),
            )
            write_ok = True
            if self.coordinator.is_transport_link_down(self.serial):
                # The packed register cannot be re-read on a dead link. Skip
                # the per-device parameter refresh and leave refresh_ok False
                # so the optimistic value is RETAINED — the acknowledged
                # cloud write IS device truth — until fresh parameter data
                # arrives on link recovery.
                refresh_ok = False
            else:
                refresh_ok = await self._async_refresh_parameters()
        finally:
            if not write_ok or refresh_ok:
                # Write failed (entity falls back to the parameter cache —
                # re-read device truth on the cloud partial-failure path) or
                # the cache was refreshed with the written value.
                self._optimistic_value = None
            else:
                # Write landed but the refresh failed: retain the optimistic
                # value until fresh parameter data arrives.
                self._optimistic_retained = True
                self._pre_write_value = pre_write_value
            self.async_write_ha_state()

    async def _async_write_cloud(self, value: time) -> None:
        """Write the schedule boundary via the cloud API.

        Two conventions:

        - writeTime families (Generator/Off-Grid/Peak Shaving): a single
          atomic ``write_time_parameter`` call sets the boundary's hour and
          minute together, so there is no partial-write / mixed-time window
          and no re-read convergence needed.
        - Classic families (AC Charge/First, Forced Charge/Discharge): the
          portal edits a schedule time as one write per field — hour then
          minute (pylxpweb's own cloud schedule helper uses the same
          parameters). The two writes are not atomic: if the minute write
          fails after the hour write succeeded, the device holds a MIXED
          time. In that case the parameters are re-read (best effort) BEFORE
          the error propagates, so the entity converges to what the device
          actually holds instead of hiding the partial write behind the stale
          cached value (PR #283 review P1).
        """
        client = self.coordinator.require_client()
        if self._spec.write_via_time_api:
            # write_time_parameter exists on the pylxpweb release this family is
            # gated on (_SUPPORTS_WRITE_TIME), but not on the older floor the
            # manifest still pins pre-release; typing the endpoint as Any keeps
            # a direct call from failing strict mypy against the installed stub.
            #
            # One atomic call sets both hour and minute (no partial-write /
            # mixed-time window), so no re-read convergence is needed — but
            # pylxpweb raises LuxpowerAPIError / LuxpowerConnectionError on
            # failures that survive its own retries (e.g. a persistent
            # DATAFRAME_TIMEOUT), so surface those as HomeAssistantError the
            # same way the classic branch below does.
            control: Any = client.api.control
            try:
                result = await control.write_time_parameter(
                    self.serial, self._cloud_time_param, value.hour, value.minute
                )
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to set {self._cloud_time_param} to "
                    f"{value.isoformat(timespec='minutes')} for {self.serial}: {err}"
                ) from err
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set {self._cloud_time_param} to "
                    f"{value.isoformat(timespec='minutes')} for {self.serial}"
                )
            return
        wrote_any = False
        for param, field in (
            (self._cloud_hour_param, value.hour),
            (self._cloud_minute_param, value.minute),
        ):
            try:
                result = await client.api.control.write_parameter(
                    self.serial, param, str(field)
                )
            except Exception as err:
                if wrote_any:
                    await self._async_raise_partial_write(param, err)
                raise HomeAssistantError(
                    f"Failed to set {param} to {field} for {self.serial}: {err}"
                ) from err
            if not result.success:
                if wrote_any:
                    await self._async_raise_partial_write(param, None)
                raise HomeAssistantError(
                    f"Failed to set {param} to {field} for {self.serial}"
                )
            wrote_any = True

    async def _async_raise_partial_write(
        self, failed_param: str, err: Exception | None
    ) -> None:
        """Re-read parameters after a partial cloud write, then raise.

        The hour parameter was written but ``failed_param`` was not — the
        device holds a mixed schedule time. A best-effort parameter refresh
        (its own errors suppressed) re-reads the device so the entity shows
        the actual (mixed) state once the optimistic value is dropped by
        the caller's failure path. Skipped while the local transport link
        is down — the re-read would hang on the dead link; the cloud param
        poll or link recovery converges the entity later.
        """
        _LOGGER.warning(
            "Cloud schedule write for %s partially applied (%s failed%s); "
            "re-reading device parameters to reflect the actual state",
            self.serial,
            failed_param,
            f": {err}" if err else "",
        )
        if not self.coordinator.is_transport_link_down(self.serial):
            await self._async_refresh_parameters()
        raise HomeAssistantError(
            f"Failed to set {failed_param} for {self.serial}: the schedule "
            "time may be partially applied (hour and minute are written "
            "separately) — device state was re-read"
        ) from err

    async def _async_refresh_parameters(self) -> bool:
        """Re-read parameters so all schedule entities converge on the write.

        Returns:
            True when the refresh completed; False when it failed (errors
            are logged, not raised — the write itself already succeeded, or
            an error is already propagating).
        """
        try:
            await self.coordinator.async_refresh_device_parameters(self.serial)
        except Exception as err:
            _LOGGER.error("Failed to refresh parameters after schedule write: %s", err)
            return False
        return True
