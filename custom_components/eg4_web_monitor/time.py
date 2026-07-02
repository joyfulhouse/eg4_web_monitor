"""Time platform for EG4 Web Monitor integration.

Exposes the inverter's AC charge schedule (issue #277) as native Home
Assistant ``time`` entities: three daily windows × (start, end), backed by
holding registers 68-73. Each 16-bit register packs hour (low byte) and
minute (high byte) — verified by the live cloud register probe in pylxpweb
``docs/inverters/FlexBOSS21_52XXXXXX78.json``, where reading one register
returns BOTH the ``*_HOUR`` and ``*_MINUTE`` cloud parameters (window 1
unsuffixed, windows 2/3 suffixed ``_1``/``_2``).

Write paths:
- LOCAL / HYBRID with an attached transport: one packed register write
  (FC06) via :meth:`EG4DataUpdateCoordinator.write_register`.
- CLOUD: the portal's own named-parameter writes (``HOLD_AC_CHARGE_
  {START|END}_{HOUR|MINUTE}{suffix}``), one hour + one minute write.

Read path: the coordinator's parameter poll. Locally the packed raw values
surface under pylxpweb's legacy aliases (see
``LOCAL_AC_CHARGE_TIME_PARAM_KEYS``); the cloud returns the separated
hour/minute values.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.time import TimeEntity
else:
    from homeassistant.components.time import TimeEntity

from pylxpweb.constants import pack_time, unpack_time

from . import EG4ConfigEntry
from .base_entity import EG4BaseTime, optimistic_time_context
from .const import (
    AC_CHARGE_SCHEDULE_BASE_REGISTER,
    LOCAL_AC_CHARGE_TIME_PARAM_KEYS,
)
from .coordinator import EG4DataUpdateCoordinator
from .utils import is_supported_control_model

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 3

AC_CHARGE_SCHEDULE_WINDOWS = (1, 2, 3)


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

        # Family-aware control gate (#259/#281): matches by model-name
        # substring or, for cloud deviceTypeText variants the substrings
        # miss (e.g. "SNA-US 15K" — the reporter's 12000XP), by the
        # detected inverter family. AC charge scheduling exists on all
        # control-capable families (EG4_OFFGRID, EG4_HYBRID, LXP).
        if not is_supported_control_model(device_data):
            continue

        for window in AC_CHARGE_SCHEDULE_WINDOWS:
            entities.append(
                EG4ACChargeTimeEntity(coordinator, serial, window, is_end=False)
            )
            entities.append(
                EG4ACChargeTimeEntity(coordinator, serial, window, is_end=True)
            )

    if entities:
        _LOGGER.info("Setup complete: %d time entities created", len(entities))
        async_add_entities(entities, update_before_add=False)


class EG4ACChargeTimeEntity(EG4BaseTime, TimeEntity):
    """One boundary (start or end) of one AC charge schedule window.

    Window 1 (registers 68/69) is enabled by default; windows 2 and 3
    (registers 70-73) are created registry-disabled — most users schedule a
    single daily window. The window numbering is user-facing (1-3); the
    firmware/cloud period index is ``window - 1``.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        window: int,
        *,
        is_end: bool,
    ) -> None:
        """Initialize the schedule time entity.

        Args:
            coordinator: The data update coordinator.
            serial: Inverter serial number.
            window: User-facing window number (1-3).
            is_end: False for the window start boundary, True for the end.
        """
        super().__init__(coordinator, serial)
        self._window = window
        self._is_end = is_end

        boundary = "end" if is_end else "start"
        key = f"ac_charge_{boundary}_time_{window}"
        self._attr_translation_key = key
        self._attr_unique_id = f"{self._clean_model}_{serial.lower()}_{key}"
        self._attr_icon = "mdi:clock-end" if is_end else "mdi:clock-start"
        self._attr_entity_registry_enabled_default = window == 1

        # Packed schedule register: base 68, two registers per window
        # (start, end) — 68/69, 70/71, 72/73.
        self._register = (
            AC_CHARGE_SCHEDULE_BASE_REGISTER + (window - 1) * 2 + (1 if is_end else 0)
        )
        # Cloud parameter names: window 1 unsuffixed, windows 2/3 suffixed
        # _1/_2 (live probe, FlexBOSS21_52XXXXXX78.json regs 68-73).
        suffix = "" if window == 1 else f"_{window - 1}"
        self._cloud_hour_param = f"HOLD_AC_CHARGE_{boundary.upper()}_HOUR{suffix}"
        self._cloud_minute_param = f"HOLD_AC_CHARGE_{boundary.upper()}_MINUTE{suffix}"

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
        for key in LOCAL_AC_CHARGE_TIME_PARAM_KEYS[self._register]:
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

    @property
    def native_value(self) -> time | None:
        """Return the schedule boundary from the parameter cache."""
        if self._optimistic_value is not None:
            return self._optimistic_value
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
    def available(self) -> bool:
        """Unavailable until the schedule parameter has been polled."""
        return super().available and self.native_value is not None

    # ── Value write ─────────────────────────────────────────────────

    async def async_set_value(self, value: time) -> None:
        """Write the schedule boundary (local packed / cloud named).

        Overnight windows (end earlier than start, e.g. 20:00 → 08:00) are
        firmware-legal, so no cross-validation against the paired boundary
        is performed. Seconds are dropped — the register stores hour/minute.
        """
        boundary_value = time(hour=value.hour, minute=value.minute)
        packed = pack_time(boundary_value.hour, boundary_value.minute)
        _LOGGER.info(
            "Setting AC charge %s time %d for %s to %s",
            "end" if self._is_end else "start",
            self._window,
            self.serial,
            boundary_value.isoformat(timespec="minutes"),
        )
        with optimistic_time_context(self, boundary_value):
            if self.coordinator.has_local_transport(self.serial):
                await self.coordinator.write_register(
                    self._register, packed, serial=self.serial
                )
            elif self.coordinator.client is not None:
                await self._async_write_cloud(boundary_value)
            else:
                raise HomeAssistantError(
                    "No local transport or cloud API available for parameter write."
                )
            await self._async_refresh_parameters()

    async def _async_write_cloud(self, value: time) -> None:
        """Write the hour and minute named parameters via the cloud API.

        The portal edits a schedule time exactly this way — one write per
        field (pylxpweb's own cloud schedule helper uses the same
        parameters). The two writes are not atomic; the brief mixed state
        matches portal behavior and resolves with the second write.
        """
        client = self.coordinator.client
        if client is None:  # pragma: no cover - guarded by caller
            raise HomeAssistantError(
                "No local transport or cloud API available for parameter write."
            )
        for param, field in (
            (self._cloud_hour_param, value.hour),
            (self._cloud_minute_param, value.minute),
        ):
            result = await client.api.control.write_parameter(
                self.serial, param, str(field)
            )
            if not result.success:
                raise HomeAssistantError(
                    f"Failed to set {param} to {field} for {self.serial}"
                )

    async def _async_refresh_parameters(self) -> None:
        """Re-read parameters so all schedule entities converge on the write."""
        try:
            await self.coordinator.refresh_all_device_parameters()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to refresh parameters after schedule write: %s", err)
