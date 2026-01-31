"""Unified config flow for EG4 Web Monitor integration.

Supports three connection modes (auto-derived from configured data):
- cloud: HTTP API only (username + plant_id, no local transports)
- local: Local transports only (1-N Modbus/Dongle devices, no cloud)
- hybrid: Both cloud API + local transports

Users don't pick a mode upfront. They start with either cloud credentials
or local devices, and can add the other at any time via reconfigure.

Directory Structure:
    config_flow/
    ├── __init__.py      # This file - unified EG4ConfigFlow class
    ├── discovery.py     # Device auto-discovery via Modbus/Dongle
    ├── schemas.py       # Voluptuous schema builders
    ├── helpers.py       # Utility functions (unique IDs, migration, etc.)
    └── options.py       # EG4OptionsFlow for interval configuration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import aiohttp_client
from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from .discovery import (
    DiscoveredDevice,
    build_device_config,
    discover_dongle_device,
    discover_modbus_device,
)
from .helpers import (
    build_unique_id,
    find_plant_by_id,
    find_serial_conflict,
    format_entry_title,
    get_ha_timezone,
    migrate_legacy_entry,
    timezone_observes_dst,
)
from .options import EG4OptionsFlow
from .schemas import (
    build_dongle_schema,
    build_http_credentials_schema,
    build_http_reconfigure_schema,
    build_modbus_schema,
    build_plant_selection_schema,
    build_reauth_schema,
)
from ..const import (
    BRAND_NAME,
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_INVERTER_SERIAL,
    CONF_LIBRARY_DEBUG,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    CONNECTION_TYPE_HYBRID,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


def _derive_connection_type(has_cloud: bool, has_local: bool) -> str:
    """Derive connection type from what's configured."""
    if has_cloud and has_local:
        return CONNECTION_TYPE_HYBRID
    if has_cloud:
        return CONNECTION_TYPE_HTTP
    return CONNECTION_TYPE_LOCAL


# =============================================================================
# CONFIG FLOW
# =============================================================================


class EG4ConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Unified config flow for EG4 Web Monitor.

    Replaces the previous 12-mixin architecture with a single class.
    Connection type is derived from configured data, not chosen upfront.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        # Cloud state
        self._username: str | None = None
        self._password: str | None = None
        self._base_url: str = DEFAULT_BASE_URL
        self._verify_ssl: bool = DEFAULT_VERIFY_SSL
        self._dst_sync: bool = True
        self._library_debug: bool = False
        self._plant_id: str | None = None
        self._plant_name: str | None = None
        self._plants: list[dict[str, Any]] | None = None

        # Local device state
        self._local_transports: list[dict[str, Any]] = []
        self._pending_device: DiscoveredDevice | None = None
        self._pending_transport_type: str | None = None
        self._pending_host: str | None = None
        self._pending_port: int | None = None
        self._pending_unit_id: int | None = None
        self._pending_dongle_serial: str | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EG4OptionsFlow:
        """Get the options flow for this handler."""
        return EG4OptionsFlow()

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def _has_cloud(self) -> bool:
        """Check if cloud credentials are configured."""
        return bool(self._username and self._plant_id)

    @property
    def _has_local(self) -> bool:
        """Check if local transports are configured."""
        return bool(self._local_transports)

    @property
    def _all_serials(self) -> set[str]:
        """Get all configured serial numbers."""
        return {t["serial"] for t in self._local_transports if t.get("serial")}

    # =========================================================================
    # ONBOARDING: Entry point
    # =========================================================================

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step - cloud-first menu with local-only skip option."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["cloud_credentials", "local_device_type"],
            description_placeholders={"brand_name": BRAND_NAME},
        )

    # =========================================================================
    # ONBOARDING: Cloud-first path
    # =========================================================================

    async def async_step_cloud_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect cloud API credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._store_cloud_input(user_input)
            errors = await self._validate_cloud_credentials()

            if not errors:
                assert self._plants is not None
                if len(self._plants) == 1:
                    self._plant_id = self._plants[0]["plantId"]
                    self._plant_name = self._plants[0]["name"]
                    return await self.async_step_cloud_add_local()
                return await self.async_step_cloud_station()

        dst_default = timezone_observes_dst(get_ha_timezone(self.hass))
        return self.async_show_form(
            step_id="cloud_credentials",
            data_schema=build_http_credentials_schema(dst_sync_default=dst_default),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_cloud_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select station/plant."""
        if user_input is not None:
            self._plant_id = user_input[CONF_PLANT_ID]
            plant = find_plant_by_id(self._plants, self._plant_id)
            self._plant_name = plant["name"] if plant else self._plant_id
            return await self.async_step_cloud_add_local()

        assert self._plants is not None
        return self.async_show_form(
            step_id="cloud_station",
            data_schema=build_plant_selection_schema(self._plants),
        )

    async def async_step_cloud_add_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether to add local devices."""
        return self.async_show_menu(
            step_id="cloud_add_local",
            menu_options=["local_device_type", "cloud_finish"],
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_cloud_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create cloud-only entry."""
        return await self._create_entry()

    # =========================================================================
    # ONBOARDING: Local device loop (shared by cloud-first and local-first)
    # =========================================================================

    async def async_step_local_device_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select local transport type (Modbus or Dongle)."""
        return self.async_show_menu(
            step_id="local_device_type",
            menu_options=["local_modbus", "local_dongle"],
        )

    async def async_step_local_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure Modbus TCP connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_MODBUS_HOST]
            port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)

            try:
                device = await discover_modbus_device(host, port, unit_id)
            except TimeoutError:
                errors["base"] = "modbus_timeout"
            except OSError:
                errors["base"] = "modbus_connection_failed"
            except Exception:
                _LOGGER.exception("Unexpected Modbus discovery error")
                errors["base"] = "unknown"

            if not errors:
                conflict = find_serial_conflict(
                    self.hass,
                    {device.serial} | self._all_serials,
                )
                if conflict and device.serial == conflict[0]:
                    errors["base"] = "duplicate_serial"

                if not errors:
                    self._pending_device = device
                    self._pending_transport_type = "modbus_tcp"
                    self._pending_host = host
                    self._pending_port = port
                    self._pending_unit_id = unit_id
                    return await self.async_step_local_device_confirmed()

        return self.async_show_form(
            step_id="local_modbus",
            data_schema=build_modbus_schema(),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure WiFi Dongle connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_DONGLE_HOST]
            port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input[CONF_DONGLE_SERIAL]
            inverter_serial = user_input[CONF_INVERTER_SERIAL]

            try:
                device = await discover_dongle_device(
                    host, dongle_serial, inverter_serial, port
                )
            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError:
                errors["base"] = "dongle_connection_failed"
            except Exception:
                _LOGGER.exception("Unexpected dongle discovery error")
                errors["base"] = "unknown"

            if not errors:
                conflict = find_serial_conflict(
                    self.hass,
                    {device.serial} | self._all_serials,
                )
                if conflict and device.serial == conflict[0]:
                    errors["base"] = "duplicate_serial"

                if not errors:
                    self._pending_device = device
                    self._pending_transport_type = "wifi_dongle"
                    self._pending_host = host
                    self._pending_port = port
                    self._pending_dongle_serial = dongle_serial
                    return await self.async_step_local_device_confirmed()

        return self.async_show_form(
            step_id="local_dongle",
            data_schema=build_dongle_schema(),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_local_device_confirmed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered device info and add to transport list."""
        assert self._pending_device is not None
        device = self._pending_device

        config = build_device_config(
            discovered=device,
            transport_type=self._pending_transport_type or "modbus_tcp",
            host=self._pending_host or "",
            port=self._pending_port or 0,
            dongle_serial=self._pending_dongle_serial,
            unit_id=self._pending_unit_id,
        )
        self._local_transports.append(config)
        self._clear_pending_state()

        device_type = "MID" if device.is_gridboss else "Inverter"
        menu_options = ["local_device_type", "local_finish"]
        if not self._has_cloud:
            menu_options = ["local_device_type", "local_add_cloud", "local_finish"]

        return self.async_show_menu(
            step_id="local_device_confirmed",
            menu_options=menu_options,
            description_placeholders={
                "device_type": device_type,
                "device_model": device.model,
                "device_serial": device.serial,
                "device_family": device.family,
                "device_firmware": device.firmware_version,
                "device_pv_power": str(int(device.pv_power)),
                "device_battery_soc": str(device.battery_soc),
                "device_count": str(len(self._local_transports)),
            },
        )

    async def async_step_local_add_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Redirect to cloud credentials from local-first flow."""
        return await self.async_step_cloud_credentials(user_input)

    async def async_step_local_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish local setup - ask for installation name if no cloud."""
        if self._has_cloud:
            return await self._create_entry()

        if user_input is not None:
            station_name = user_input.get("station_name", "").strip()
            if not station_name:
                first = self._local_transports[0]
                station_name = (
                    f"{first.get('model', 'Device')} {first.get('serial', '')}"
                )
            self._plant_name = station_name
            return await self._create_entry()

        return self.async_show_form(
            step_id="local_finish",
            data_schema=vol.Schema({vol.Optional("station_name", default=""): str}),
            description_placeholders={
                "device_summary": ", ".join(
                    f"{t.get('model', '?')} ({t.get('serial', '?')})"
                    for t in self._local_transports
                ),
            },
        )

    # =========================================================================
    # REAUTHENTICATION
    # =========================================================================

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication trigger."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm new password for reauthentication."""
        errors: dict[str, str] = {}

        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", "")
        )
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            self._username = entry.data.get(CONF_USERNAME)
            self._password = user_input[CONF_PASSWORD]
            self._base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            self._verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

            try:
                await self._test_cloud_credentials()
            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"

            if not errors:
                new_data = {**entry.data, CONF_PASSWORD: self._password}
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(
                    reason="reauth_successful",
                    description_placeholders={"brand_name": BRAND_NAME},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=build_reauth_schema(),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    # =========================================================================
    # RECONFIGURE: Entry point
    # =========================================================================

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure entry point - load state and show menu."""
        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", "")
        )
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Auto-migrate legacy entries (modbus/dongle -> local)
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_HTTP)
        if connection_type in ("modbus", "dongle"):
            migrated = migrate_legacy_entry(dict(entry.data))
            self.hass.config_entries.async_update_entry(entry, data=migrated)
            _LOGGER.info("Migrated legacy %s entry to unified format", connection_type)

        # Load current state from entry
        self._username = entry.data.get(CONF_USERNAME)
        self._password = entry.data.get(CONF_PASSWORD)
        self._base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        self._verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self._dst_sync = entry.data.get(CONF_DST_SYNC, True)
        self._library_debug = entry.data.get(CONF_LIBRARY_DEBUG, False)
        self._plant_id = entry.data.get(CONF_PLANT_ID)
        self._plant_name = entry.data.get(CONF_PLANT_NAME)
        self._local_transports = list(entry.data.get(CONF_LOCAL_TRANSPORTS, []))

        return await self.async_step_reconfigure_menu()

    async def async_step_reconfigure_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show reconfigure options menu."""
        menu_options: list[str] = []

        if self._has_cloud:
            menu_options.append("reconfigure_cloud_update")
            if self._has_local:
                menu_options.append("reconfigure_cloud_remove")
        else:
            menu_options.append("reconfigure_cloud_add")

        menu_options.append("reconfigure_devices")

        return self.async_show_menu(
            step_id="reconfigure_menu",
            menu_options=menu_options,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "entry_title": self._plant_name or "Local Installation",
            },
        )

    # =========================================================================
    # RECONFIGURE: Cloud credential management
    # =========================================================================

    async def async_step_reconfigure_cloud_update(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update existing cloud credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._store_cloud_input(user_input)
            errors = await self._validate_cloud_credentials()

            if not errors:
                return self._update_entry()

        return self.async_show_form(
            step_id="reconfigure_cloud_update",
            data_schema=build_http_reconfigure_schema(
                current_username=self._username,
                current_base_url=self._base_url,
                current_verify_ssl=self._verify_ssl,
                current_dst_sync=self._dst_sync,
            ),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_cloud_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add cloud credentials to a local-only entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._store_cloud_input(user_input)
            errors = await self._validate_cloud_credentials()

            if not errors:
                assert self._plants is not None
                if len(self._plants) == 1:
                    self._plant_id = self._plants[0]["plantId"]
                    self._plant_name = self._plants[0]["name"]
                    return self._update_entry()
                return await self.async_step_reconfigure_cloud_station()

        dst_default = timezone_observes_dst(get_ha_timezone(self.hass))
        return self.async_show_form(
            step_id="reconfigure_cloud_add",
            data_schema=build_http_credentials_schema(dst_sync_default=dst_default),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_cloud_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select station during reconfigure cloud change."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._plant_id = user_input[CONF_PLANT_ID]
            plant = find_plant_by_id(self._plants, self._plant_id)
            self._plant_name = plant["name"] if plant else self._plant_id
            return self._update_entry()

        # Fetch stations list if not already loaded
        if self._plants is None:
            errors = await self._validate_cloud_credentials()
            if errors:
                return self.async_abort(reason="invalid_auth")

        assert self._plants is not None
        return self.async_show_form(
            step_id="reconfigure_cloud_station",
            data_schema=build_plant_selection_schema(
                self._plants, current=self._plant_id
            ),
            errors=errors,
        )

    async def async_step_reconfigure_cloud_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove cloud credentials (hybrid -> local)."""
        if user_input is not None:
            self._username = None
            self._password = None
            self._base_url = DEFAULT_BASE_URL
            self._verify_ssl = DEFAULT_VERIFY_SSL
            self._plant_id = None
            self._plant_name = None
            self._dst_sync = False
            self._library_debug = False
            return self._update_entry()

        return self.async_show_form(
            step_id="reconfigure_cloud_remove",
            data_schema=vol.Schema({}),
            description_placeholders={"brand_name": BRAND_NAME},
        )

    # =========================================================================
    # RECONFIGURE: Device management
    # =========================================================================

    async def async_step_reconfigure_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show device list with management options."""
        device_lines = []
        for i, t in enumerate(self._local_transports):
            transport_type = (
                "Modbus" if t.get("transport_type") == "modbus_tcp" else "Dongle"
            )
            device_lines.append(
                f"{i + 1}. {t.get('model', '?')} ({t.get('serial', '?')}) "
                f"- {transport_type} @ {t.get('host', '?')}"
            )
        device_list = (
            "\n".join(device_lines) if device_lines else "No devices configured"
        )

        menu_options = ["reconfigure_device_add"]
        if self._local_transports:
            menu_options.append("reconfigure_device_remove")
        menu_options.append("reconfigure_devices_save")

        return self.async_show_menu(
            step_id="reconfigure_devices",
            menu_options=menu_options,
            description_placeholders={
                "device_count": str(len(self._local_transports)),
                "device_list": device_list,
            },
        )

    async def async_step_reconfigure_device_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a local device during reconfigure."""
        if user_input is not None:
            serial_to_remove = user_input.get("device")
            self._local_transports = [
                t for t in self._local_transports if t.get("serial") != serial_to_remove
            ]
            return await self.async_step_reconfigure_devices()

        # Build selection schema from current devices
        device_options = {
            t.get("serial", f"unknown_{i}"): (
                f"{t.get('model', '?')} ({t.get('serial', '?')}) - "
                f"{'Modbus' if t.get('transport_type') == 'modbus_tcp' else 'Dongle'}"
            )
            for i, t in enumerate(self._local_transports)
        }
        return self.async_show_form(
            step_id="reconfigure_device_remove",
            data_schema=vol.Schema({vol.Required("device"): vol.In(device_options)}),
        )

    async def async_step_reconfigure_devices_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save device changes and close reconfigure flow."""
        return self._update_entry()

    async def async_step_reconfigure_device_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new local device during reconfigure."""
        return self.async_show_menu(
            step_id="reconfigure_device_add",
            menu_options=["reconfigure_add_modbus", "reconfigure_add_dongle"],
        )

    async def async_step_reconfigure_add_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add Modbus device during reconfigure."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_MODBUS_HOST]
            port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)

            try:
                device = await discover_modbus_device(host, port, unit_id)
            except TimeoutError:
                errors["base"] = "modbus_timeout"
            except OSError:
                errors["base"] = "modbus_connection_failed"
            except Exception:
                _LOGGER.exception("Unexpected Modbus discovery error")
                errors["base"] = "unknown"

            if not errors:
                entry = self.hass.config_entries.async_get_entry(
                    self.context.get("entry_id", "")
                )
                exclude_id = entry.entry_id if entry else None
                conflict = find_serial_conflict(
                    self.hass, {device.serial} | self._all_serials, exclude_id
                )
                if conflict and device.serial == conflict[0]:
                    errors["base"] = "duplicate_serial"

            if not errors:
                config = build_device_config(
                    discovered=device,
                    transport_type="modbus_tcp",
                    host=host,
                    port=port,
                    unit_id=unit_id,
                )
                self._local_transports.append(config)
                return await self.async_step_reconfigure_devices()

        return self.async_show_form(
            step_id="reconfigure_add_modbus",
            data_schema=build_modbus_schema(),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_add_dongle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add Dongle device during reconfigure."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_DONGLE_HOST]
            port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input[CONF_DONGLE_SERIAL]
            inverter_serial = user_input[CONF_INVERTER_SERIAL]

            try:
                device = await discover_dongle_device(
                    host, dongle_serial, inverter_serial, port
                )
            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError:
                errors["base"] = "dongle_connection_failed"
            except Exception:
                _LOGGER.exception("Unexpected dongle discovery error")
                errors["base"] = "unknown"

            if not errors:
                entry = self.hass.config_entries.async_get_entry(
                    self.context.get("entry_id", "")
                )
                exclude_id = entry.entry_id if entry else None
                conflict = find_serial_conflict(
                    self.hass, {device.serial} | self._all_serials, exclude_id
                )
                if conflict and device.serial == conflict[0]:
                    errors["base"] = "duplicate_serial"

            if not errors:
                config = build_device_config(
                    discovered=device,
                    transport_type="wifi_dongle",
                    host=host,
                    port=port,
                    dongle_serial=dongle_serial,
                )
                self._local_transports.append(config)
                return await self.async_step_reconfigure_devices()

        return self.async_show_form(
            step_id="reconfigure_add_dongle",
            data_schema=build_dongle_schema(),
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _clear_pending_state(self) -> None:
        """Reset all pending device discovery state."""
        self._pending_device = None
        self._pending_transport_type = None
        self._pending_host = None
        self._pending_port = None
        self._pending_unit_id = None
        self._pending_dongle_serial = None

    def _store_cloud_input(self, user_input: dict[str, Any]) -> None:
        """Store cloud credential fields from user input."""
        self._username = user_input[CONF_USERNAME]
        self._password = user_input[CONF_PASSWORD]
        self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        self._verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self._dst_sync = user_input.get(CONF_DST_SYNC, True)
        self._library_debug = user_input.get(CONF_LIBRARY_DEBUG, False)

    async def _validate_cloud_credentials(self) -> dict[str, str]:
        """Test cloud credentials and return errors dict (empty on success)."""
        errors: dict[str, str] = {}
        try:
            await self._test_cloud_credentials()
        except LuxpowerAuthError:
            errors["base"] = "invalid_auth"
        except TimeoutError:
            errors["base"] = "timeout"
        except (OSError, LuxpowerAPIError, LuxpowerConnectionError):
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error testing credentials")
            errors["base"] = "unknown"
        return errors

    async def _test_cloud_credentials(self) -> None:
        """Test cloud credentials and load stations list."""
        session = aiohttp_client.async_get_clientsession(self.hass)
        assert self._username is not None
        assert self._password is not None

        async with LuxpowerClient(
            username=self._username,
            password=self._password,
            base_url=self._base_url,
            verify_ssl=self._verify_ssl,
            session=session,
        ) as client:
            from pylxpweb.devices import Station

            stations = await Station.load_all(client)
            self._plants = [
                {"plantId": station.id, "name": station.name} for station in stations
            ]
            if not self._plants:
                raise LuxpowerAPIError("No plants found for this account")

    def _build_entry_data(self) -> dict[str, Any]:
        """Build config entry data from current flow state."""
        connection_type = _derive_connection_type(self._has_cloud, self._has_local)

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: connection_type,
            CONF_LOCAL_TRANSPORTS: self._local_transports,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_LIBRARY_DEBUG: self._library_debug,
        }

        if self._has_cloud:
            data[CONF_USERNAME] = self._username
            data[CONF_PASSWORD] = self._password
            data[CONF_BASE_URL] = self._base_url
            data[CONF_PLANT_ID] = self._plant_id
            data[CONF_PLANT_NAME] = self._plant_name

        return data

    def _build_unique_id(self) -> str:
        """Build unique ID from current state."""
        if self._has_cloud:
            mode = "hybrid" if self._has_local else "http"
            return build_unique_id(
                mode, username=self._username, plant_id=self._plant_id
            )
        name = self._plant_name or "local"
        return build_unique_id("local", station_name=name)

    def _build_title(self) -> str:
        """Build entry title from current state."""
        connection_type = _derive_connection_type(self._has_cloud, self._has_local)
        return format_entry_title(connection_type, self._plant_name or "Unknown")

    async def _create_entry(self) -> ConfigFlowResult:
        """Create a new config entry from current flow state."""
        unique_id = self._build_unique_id()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=self._build_title(),
            data=self._build_entry_data(),
        )

    def _update_entry(self) -> ConfigFlowResult:
        """Update existing config entry during reconfigure."""
        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", "")
        )
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        new_data = self._build_entry_data()
        self.hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            title=self._build_title(),
        )
        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )


# =============================================================================
# BACKWARD COMPATIBILITY EXPORTS
# =============================================================================

# The old class name was EG4WebMonitorConfigFlow - alias for any external references
EG4WebMonitorConfigFlow = EG4ConfigFlow

__all__ = [
    "EG4ConfigFlow",
    "EG4WebMonitorConfigFlow",
    "EG4OptionsFlow",
]
