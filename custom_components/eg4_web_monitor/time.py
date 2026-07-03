"""Time platform for EG4 Web Monitor integration.

Exposes the inverter's packed-time schedules (issues #277 + #295) as native
Home Assistant ``time`` entities: per schedule type, three daily windows ×
(start, end). Each schedule occupies six consecutive holding registers and
each 16-bit register packs hour (low byte) and minute (high byte) — verified
by the live cloud register probes in pylxpweb ``docs/inverters/`` (FlexBOSS21
for AC charge 68-73, SNA12K-US blocks 106-111 for AC First 152-157), where
reading one register returns BOTH the ``*_HOUR`` and ``*_MINUTE`` cloud
parameters (window 1 unsuffixed, windows 2/3 suffixed ``_1``/``_2``).

The schedule types, their registers, cloud parameter prefixes and family
gates all come from the declarative ``SCHEDULE_TIME_TYPES`` table in
const/modbus.py (mirroring pylxpweb's ``SCHEDULE_CONFIGS``).

Write paths:
- LOCAL / HYBRID with an attached transport: one packed register write
  (FC06) via :meth:`EG4DataUpdateCoordinator.write_register`.
- CLOUD: the portal's own named-parameter writes
  (``{prefix}_{START|END}_{HOUR|MINUTE}{suffix}``), one hour + one minute
  write.

Read path: the coordinator's parameter poll. Locally the packed raw values
surface under pylxpweb's parameter-cache keys (see each spec's
``local_param_keys`` alias chains); the cloud returns the separated
hour/minute values.
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

from . import EG4ConfigEntry
from .base_entity import EG4BaseTime
from .const import SCHEDULE_TIME_TYPES, ScheduleTimeSpec
from .coordinator import EG4DataUpdateCoordinator
from .utils import (
    async_write_with_cloud_fallback,
    is_offgrid_family,
    is_supported_control_model,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3

SCHEDULE_WINDOWS = (1, 2, 3)


def _schedule_supported(spec: ScheduleTimeSpec, device_data: dict[str, Any]) -> bool:
    """Whether a device should get a schedule type's entities.

    Gates (see the ``ScheduleTimeSpec.gate`` docs in const/modbus.py):
    - ``offgrid``: only positively-identified EG4_OFFGRID (SNA) hardware —
      the portal shows the AC First section only on the SNA working-mode
      page (#295). Fails closed when the family is unknown.
    - ``control`` / ``control_grid_tied``: the family-aware control gate
      (#259/#281); ``control_grid_tied`` additionally suppresses the
      entities on positively-identified EG4_OFFGRID hardware, matching the
      forced discharge number controls (PR #220 / issue #197).
    """
    if spec.gate == "offgrid":
        return is_offgrid_family(device_data)
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

    for serial, device_data in (coordinator.data or {}).get("devices", {}).items():
        if device_data.get("type") != "inverter":
            continue

        entities.extend(
            EG4ScheduleTimeEntity(coordinator, serial, spec, window, is_end=is_end)
            for spec in SCHEDULE_TIME_TYPES
            if _schedule_supported(spec, device_data)
            for window in SCHEDULE_WINDOWS
            for is_end in (False, True)
        )

    if entities:
        _LOGGER.info("Setup complete: %d time entities created", len(entities))
        async_add_entities(entities, update_before_add=False)


class EG4ScheduleTimeEntity(EG4BaseTime, TimeEntity):
    """One boundary (start or end) of one schedule window.

    Per schedule type, window 1 is enabled by default; windows 2 and 3 are
    created registry-disabled — most users schedule a single daily window.
    The window numbering is user-facing (1-3); the firmware/cloud period
    index is ``window - 1``.
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
        self._attr_entity_registry_enabled_default = window == 1

        # Packed schedule register: two registers per window (start, end)
        # from the schedule's base register.
        self._register = spec.base_register + (window - 1) * 2 + (1 if is_end else 0)
        # Cloud parameter names: window 1 unsuffixed, windows 2/3 suffixed
        # _1/_2 (portal holdParam convention, live register probes).
        suffix = "" if window == 1 else f"_{window - 1}"
        self._cloud_hour_param = f"{spec.cloud_prefix}_{boundary.upper()}_HOUR{suffix}"
        self._cloud_minute_param = (
            f"{spec.cloud_prefix}_{boundary.upper()}_MINUTE{suffix}"
        )

    # ── Value read ──────────────────────────────────────────────────

    def _params_are_local_raw(self) -> bool:
        """Whether this serial's parameter cache holds raw register values.

        Mirrors the number-platform helper: true in local-only modes and
        when the pylxpweb inverter object has a local transport attached
        (HYBRID) — both populate the cache via ``read_named_parameters``,
        which surfaces the raw packed schedule registers. Cloud-populated
        caches hold the separated hour/minute values instead.
        """
        if self.coordinator.is_local_only():
            return True
        inverter = self.coordinator.get_inverter_object(self.serial)
        return getattr(inverter, "transport", None) is not None

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
        """Write the hour and minute named parameters via the cloud API.

        The portal edits a schedule time exactly this way — one write per
        field (pylxpweb's own cloud schedule helper uses the same
        parameters). The two writes are not atomic (the cloud offers no
        transaction): if the minute write fails after the hour write
        succeeded, the device holds a MIXED time. In that case the
        parameters are re-read (best effort) BEFORE the error propagates,
        so the entity converges to what the device actually holds instead
        of hiding the partial write behind the stale cached value
        (PR #283 review P1).
        """
        client = self.coordinator.client
        if client is None:  # pragma: no cover - guarded by caller
            raise HomeAssistantError(
                "No local transport or cloud API available for parameter write."
            )
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
        the caller's failure path.
        """
        _LOGGER.warning(
            "Cloud schedule write for %s partially applied (%s failed%s); "
            "re-reading device parameters to reflect the actual state",
            self.serial,
            failed_param,
            f": {err}" if err else "",
        )
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
            await self.coordinator.refresh_all_device_parameters()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to refresh parameters after schedule write: %s", err)
            return False
        return True
