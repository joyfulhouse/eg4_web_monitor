"""Button platform for EG4 Web Monitor integration."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
else:
    from homeassistant.components.button import (  # type: ignore[assignment]
        ButtonEntity,
        ButtonEntityDescription,
    )

from . import EG4ConfigEntry
from .base_entity import EG4BatteryEntity, EG4DeviceEntity, EG4StationEntity
from .const import (
    DOMAIN,
    ScheduleTimeSpec,
)
from .coordinator import (
    DISCOVERY_LISTENER_CONTEXT,
    EG4DataUpdateCoordinator,
    listener_changed_device_items,
)
from .time import (
    offgrid_schedule_devices,
    schedule_boundary_params,
    schedule_register_locks,
)
from .utils import (
    generate_unique_id,
)

_LOGGER = logging.getLogger(__name__)

# Silver tier requirement: Specify parallel update count
MAX_PARALLEL_UPDATES = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EG4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EG4 Web Monitor button entities.

    Entity registration is split into two phases to ensure proper device hierarchy:
    1. Phase 1: Station and device refresh buttons (creates parent devices first)
    2. Phase 2: Individual battery refresh buttons (can safely reference battery bank)

    This ordering prevents HA warning about non-existing via_device references.
    See: https://github.com/joyfulhouse/eg4_web_monitor/issues/81
    """
    coordinator: EG4DataUpdateCoordinator = entry.runtime_data

    # Phase 1 entities: devices that don't reference battery bank via via_device
    phase1_entities: list[ButtonEntity] = []
    # Phase 2 entities: individual batteries that reference battery bank via via_device
    phase2_entities: list[ButtonEntity] = []

    if not coordinator.data:
        _LOGGER.warning("No coordinator data available for button setup")
        return

    # Create station refresh button if station data is available
    if "station" in coordinator.data:
        phase1_entities.append(EG4StationRefreshButton(coordinator))

    # Skip device buttons if no device data
    if "devices" not in coordinator.data:
        _LOGGER.warning(
            "No device data available for button setup, only creating station buttons"
        )
        if phase1_entities:
            async_add_entities(phase1_entities)
        return

    # Create refresh diagnostic buttons for all devices (phase 1)
    for serial, device_data in coordinator.data["devices"].items():
        # Get device info for proper naming
        device_type = device_data.get("type", "unknown")
        if device_type == "parallel_group":
            # For parallel groups, get model from device data itself
            model = device_data.get("model", "Parallel Group")
        else:
            # For other devices, get model from device_info from API
            device_info = coordinator.data.get("device_info", {}).get(serial, {})
            model = device_info.get("deviceTypeText4APP", "Unknown")

        # Create refresh button for all device types
        phase1_entities.append(
            EG4RefreshButton(coordinator, serial, device_data, model)
        )

    # Clear-schedule buttons (#563) for positively resolved EG4_OFFGRID
    # inverters when a cloud client exists (the only sanctioned write route
    # for off-grid schedule normalization — see EG4ClearScheduleButton).
    clear_buttons, known_clear_buttons = _new_clear_schedule_buttons(coordinator, set())
    phase1_entities.extend(clear_buttons)

    # Create refresh buttons for individual batteries (phase 2)
    for serial, device_data in coordinator.data["devices"].items():
        # Check if this device has individual batteries
        if "batteries" in device_data:
            for battery_key in device_data["batteries"]:
                # Create refresh button for each individual battery
                phase2_entities.append(
                    EG4BatteryRefreshButton(
                        coordinator=coordinator,
                        parent_serial=serial,
                        battery_key=battery_key,
                    )
                )

    # Phase 1: Register parent device buttons first
    # This ensures battery bank devices exist before individual batteries reference them
    if phase1_entities:
        async_add_entities(phase1_entities)
        _LOGGER.debug(
            "Phase 1: Added %d button entities (station, devices)", len(phase1_entities)
        )

    # Phase 2: Register individual battery buttons (reference battery bank via via_device)
    if phase2_entities:
        async_add_entities(phase2_entities)
        _LOGGER.debug(
            "Phase 2: Added %d individual battery button entities", len(phase2_entities)
        )

    # Track known battery keys for late registration.  Individual batteries
    # are discovered only when a real battery read completes — the LOCAL
    # static first refresh has none, and in HYBRID a failed cloud battery
    # fetch on the first cycle leaves them empty until the local transport
    # read.  The sensor platform already late-registers battery sensors;
    # without this listener the matching refresh buttons stayed missing
    # until reload (eg4-68y review follow-up).
    known_battery_keys: dict[str, set[str]] = {
        serial: set(device_data.get("batteries", {}))
        for serial, device_data in coordinator.data["devices"].items()
    }

    @callback
    def _async_discover_battery_buttons() -> None:
        """Register battery refresh buttons that appear after initial setup."""
        if not coordinator.data or "devices" not in coordinator.data:
            return
        new_entities: list[ButtonEntity] = []
        for serial, device_data in listener_changed_device_items(coordinator):
            known = known_battery_keys.setdefault(serial, set())
            for battery_key in device_data.get("batteries", {}):
                if battery_key in known:
                    continue
                known.add(battery_key)
                new_entities.append(
                    EG4BatteryRefreshButton(
                        coordinator=coordinator,
                        parent_serial=serial,
                        battery_key=battery_key,
                    )
                )
        if new_entities:
            _LOGGER.info(
                "Late battery button registration: adding %d entities",
                len(new_entities),
            )
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(
            _async_discover_battery_buttons, DISCOVERY_LISTENER_CONTEXT
        )
    )

    # The inverter family can resolve to EG4_OFFGRID only on a later refresh
    # (UNKNOWN while the parameter fetch fails) — re-check on each update.
    @callback
    def _async_discover_clear_schedule_buttons() -> None:
        """Add clear-schedule buttons for newly resolved off-grid inverters."""
        new_entities, _ = _new_clear_schedule_buttons(coordinator, known_clear_buttons)
        if new_entities:
            _LOGGER.info(
                "Late clear-schedule button registration: adding %d entities",
                len(new_entities),
            )
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(
            _async_discover_clear_schedule_buttons, DISCOVERY_LISTENER_CONTEXT
        )
    )


def _new_clear_schedule_buttons(
    coordinator: EG4DataUpdateCoordinator,
    known: set[tuple[str, str]],
) -> tuple[list["EG4ClearScheduleButton"], set[tuple[str, str]]]:
    """Build clear-schedule buttons for off-grid inverters not in ``known``.

    The device iteration and family gate live in
    ``time.offgrid_schedule_devices`` (shared with the schedule-state
    sensors); the button platform ALONE additionally gates on a cloud
    client: the clear is cloud-routed only — local off-grid schedule writes
    remain evidence-gated (#558/#570), so a LOCAL-only install gets no
    button rather than an unsanctioned write path (the read-only sensors
    must not be cloud-gated).

    Args:
        coordinator: The data update coordinator.
        known: ``(serial, schedule key)`` pairs already registered; updated
            in place with every pair this call returns.

    Returns:
        The newly built entities and the updated known set.
    """
    if not coordinator.has_http_api():
        return [], known
    entities: list[EG4ClearScheduleButton] = []
    for serial, spec in offgrid_schedule_devices(coordinator):
        if (serial, spec.key) in known:
            continue
        known.add((serial, spec.key))
        entities.append(EG4ClearScheduleButton(coordinator, serial, spec))
    return entities, known


class EG4RefreshButton(EG4DeviceEntity, ButtonEntity):
    """Button to refresh device data and invalidate cache.

    Inherits common functionality from EG4DeviceEntity including:
    - Device info lookup via coordinator
    - Serial number management
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        device_data: dict[str, Any],
        model: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, serial)

        self._model = model

        device_type = device_data.get("type", "unknown")
        if device_type == "parallel_group":
            if "Parallel Group" in model and len(model) > len("Parallel Group"):
                # "Parallel Group A" -> parallel_group_a_refresh_data
                group_letter = model.replace("Parallel Group", "").strip().lower()
                self._attr_unique_id = f"parallel_group_{group_letter}_refresh_data"
            else:
                self._attr_unique_id = "parallel_group_refresh_data"
        else:
            self._attr_unique_id = generate_unique_id(serial, "refresh_data")

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{serial}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add device type info
        if self.coordinator.data and "devices" in self.coordinator.data:
            device_data = self.coordinator.data["devices"].get(self._serial, {})
            device_type = device_data.get("type", "unknown")
            attributes["device_type"] = device_type

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.debug(
                "Refresh button pressed for device %s - using device object",
                self._serial,
            )

            # Get device object and refresh using high-level method
            device_data = (
                (self.coordinator.data or {}).get("devices", {}).get(self._serial, {})
            )
            device_type = device_data.get("type", "unknown")

            incomplete = False
            if device_type == "inverter":
                # Force a full refresh INCLUDING parameters (holding
                # registers).  A bare refresh() respects pylxpweb cache TTLs
                # (re-reads nothing shortly after a poll) and never touches
                # parameters, so control values changed outside HA (e.g. on
                # the EG4 portal) took until the hourly parameter cycle to
                # appear (#322).  The coordinator helper calls
                # inverter.refresh(force=True, include_parameters=True) and
                # stores the fresh parameters; link-down handling lives in
                # pylxpweb's _fetch_parameters guard (cloud fallback in
                # HYBRID, clean skip in LOCAL — no hang risk). The private
                # method's include_runtime_data=True path is intentional: the
                # public parameter wrapper now performs only a narrow holding-
                # register fetch and in-place publication, while this explicit
                # Refresh button promises fresh runtime, energy, battery, and
                # parameter data. This button also performs its own
                # completeness check: refresh() gathers its fetch tasks with
                # return_exceptions=True, so read failures never raise — they
                # surface only as parameters_complete=False.
                _LOGGER.debug(
                    "Force-refreshing inverter %s including parameters",
                    self._serial,
                )
                await self.coordinator._refresh_device_parameters(
                    self._serial, include_runtime_data=True
                )
                inverter = self.coordinator.get_inverter_object(self._serial)
                incomplete = inverter is not None and not getattr(
                    inverter, "parameters_complete", True
                )

            # Publish whatever was read (partial data plus sticky
            # carry-forward); also the fallback path for other device types.
            await self.coordinator.async_request_refresh()

            if incomplete:
                # The device read silently came up short (dead link with no
                # cloud fallback, failed register ranges, ...) — surface it
                # in the UI instead of reporting a successful refresh.
                raise HomeAssistantError(
                    f"Parameter refresh incomplete for {self._serial}: device"
                    " unreachable or link degraded; showing last known values"
                )
            _LOGGER.debug("Successfully refreshed data for device %s", self._serial)

        except Exception as e:
            _LOGGER.error("Failed to refresh data for device %s: %s", self._serial, e)
            raise


class EG4BatteryRefreshButton(EG4BatteryEntity, ButtonEntity):
    """Button to refresh individual battery data and invalidate cache.

    Inherits common functionality from EG4BatteryEntity including:
    - Battery device info lookup via coordinator
    - Parent serial and battery key management
    - Availability checking for battery presence
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        parent_serial: str,
        battery_key: str,
    ) -> None:
        """Initialize the battery refresh button."""
        super().__init__(coordinator, parent_serial, battery_key)

        # Create unique identifiers - match battery device pattern
        self._attr_unique_id = f"{parent_serial}_{battery_key}_refresh_data"

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"{battery_key}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attributes = {}

        # Add parent device info
        attributes["parent_device"] = self._parent_serial
        attributes["battery_id"] = self._battery_key

        return attributes if attributes else None

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.debug(
                "Refresh button pressed for battery %s",
                self._battery_key,
            )

            # Get parent inverter object and refresh (which refreshes all
            # batteries).  force=True bypasses the pylxpweb cache TTLs so a
            # press actually re-reads instead of serving cached data (#322);
            # parameters are not needed here (battery data lives in input
            # registers).
            inverter = self.coordinator.get_inverter_object(self._parent_serial)
            if inverter:
                await inverter.refresh(force=True)
            else:
                _LOGGER.warning(
                    "Parent inverter object not found for %s", self._parent_serial
                )

            # Force immediate coordinator refresh to update all entities
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh data for battery %s: %s", self._battery_key, e
            )
            raise


class EG4StationRefreshButton(EG4StationEntity, ButtonEntity):
    """Button to refresh station/plant data.

    Inherits common functionality from EG4StationEntity including:
    - Station device info lookup via coordinator
    - Availability checking for station data
    """

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
    ) -> None:
        """Initialize the station refresh button."""
        super().__init__(coordinator)

        # Create unique identifiers
        self._attr_unique_id = f"station_{coordinator.plant_id}_refresh_data"

        # Set device attributes
        self._attr_has_entity_name = True
        self._attr_name = "Refresh Data"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set entity description
        self.entity_description = ButtonEntityDescription(
            key=f"station_{coordinator.plant_id}_refresh",
            name="Refresh Data",
            icon="mdi:refresh",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            # Force immediate coordinator refresh to fetch fresh station data
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Failed to refresh station data for plant %s: %s",
                self.coordinator.plant_id,
                e,
            )
            raise


class EG4ClearScheduleButton(EG4DeviceEntity, ButtonEntity):
    """Normalize every window of an off-grid schedule to 00:00 → 00:00 (#563).

    On the EG4_OFFGRID family AC Charge / AC First are schedule-defined
    working modes — the portal has no master enable toggle, so "clear the
    schedule" is the only way to stop the mode. The 00:00 → 00:00
    normalization target follows the #277/#295 live reports that an all-zero
    window disables the schedule; that convention remains
    asserted-unverified, which is acceptable here because zero-length
    windows cannot run regardless.

    CLOUD-ROUTED ONLY by construction (the button is not created without a
    cloud client): local off-grid writes stay evidence-gated per #558/#570,
    and the classic cloud schedule write is one call per hour/minute field
    (non-atomic), which the partial-failure path below accounts for.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-remove-outline"

    def __init__(
        self,
        coordinator: EG4DataUpdateCoordinator,
        serial: str,
        spec: ScheduleTimeSpec,
    ) -> None:
        """Initialize the clear-schedule button.

        Args:
            coordinator: The data update coordinator.
            serial: Inverter serial number.
            spec: The schedule type's declarative table entry.
        """
        super().__init__(coordinator, serial)
        self._spec = spec
        # Name comes from the translation key
        # (entity.button.clear_{key}_schedule.name) so it localizes.
        self._attr_translation_key = f"clear_{spec.key}_schedule"
        self._attr_unique_id = f"{serial}_clear_{spec.key}_schedule"

    async def async_press(self) -> None:
        """Write 00:00 to every window boundary of the schedule via the cloud.

        The whole schedule is written under every window's transaction lock
        (acquired in register order, so a concurrent single-boundary time
        write — which holds exactly one of them — cannot deadlock), followed
        by a parameter re-read so the time entities and the schedule-state
        binary sensor converge on what the device actually holds.

        The classic cloud schedule write is one call per field (hour and
        minute separately), so a mid-sequence failure leaves the schedule
        PARTIALLY cleared: on any failure after at least one acknowledged
        write the parameters are re-read (best effort) BEFORE the error
        propagates, and the raised error says the clear may be partial.

        Raises:
            HomeAssistantError: If a write fails, or no cloud client exists.
        """
        # One pass over schedule_boundary_params yields both the cloud field
        # writes and the registers to lock — the register arithmetic has a
        # single source.
        writes: list[str] = []
        registers: set[int] = set()
        for window in range(1, self._spec.windows + 1):
            for is_end in (False, True):
                register, hour_param, minute_param = schedule_boundary_params(
                    self._spec, window, is_end=is_end
                )
                writes.extend((hour_param, minute_param))
                registers.add(register)

        async with schedule_register_locks(self.coordinator, self._serial, registers):
            await self._async_clear_locked(writes)

    async def _async_clear_locked(self, writes: list[str]) -> None:
        """Execute the clear with all of the schedule's locks held."""
        _LOGGER.info(
            "Clearing %s schedule for %s (%d cloud field writes)",
            self._spec.key,
            self._serial,
            len(writes),
        )
        client = self.coordinator.require_client()
        written = 0
        for param in writes:
            try:
                result = await client.api.control.write_parameter(
                    self._serial, param, "0"
                )
            except asyncio.CancelledError:
                if written:
                    await self._async_converge_partial_clear(param)
                raise
            except Exception as err:
                if written:
                    await self._async_converge_partial_clear(param)
                raise HomeAssistantError(
                    f"Failed to clear {self._spec.key} schedule for "
                    f"{self._serial}: {param} write failed ({err})",
                    translation_domain=DOMAIN,
                    translation_key="clear_schedule_write_failed",
                    translation_placeholders={
                        "schedule": self._spec.key,
                        "serial": self._serial,
                        "param": param,
                        "error": str(err),
                    },
                ) from err
            if not result.success:
                if written:
                    await self._async_converge_partial_clear(param)
                raise HomeAssistantError(
                    f"Failed to clear {self._spec.key} schedule for "
                    f"{self._serial}: {param} write was not acknowledged",
                    translation_domain=DOMAIN,
                    translation_key="clear_schedule_write_not_acknowledged",
                    translation_placeholders={
                        "schedule": self._spec.key,
                        "serial": self._serial,
                        "param": param,
                    },
                )
            written += 1

        # Final reread: the writes are acknowledged, so a failed refresh must
        # NOT convert the successful clear into a user-facing error — the
        # next parameter poll converges the entities instead.
        if not await self.coordinator.async_refresh_device_parameters(self._serial):
            _LOGGER.warning(
                "Post-clear parameter refresh did not complete for %s; the "
                "%s schedule entities converge on the next poll",
                self._serial,
                self._spec.key,
            )

    async def _async_converge_partial_clear(self, failed_param: str) -> None:
        """Best-effort re-read after an acknowledged prefix of the clear.

        The device holds a partially cleared schedule; re-reading parameters
        (its own errors suppressed by the coordinator helper, which returns
        False on failure) lets the entities show the actual state once the
        caller's error propagates.
        """
        _LOGGER.warning(
            "Clear of %s schedule for %s partially applied (%s failed); "
            "re-reading device parameters to reflect the actual state",
            self._spec.key,
            self._serial,
            failed_param,
        )
        await self.coordinator.async_refresh_device_parameters(self._serial)
