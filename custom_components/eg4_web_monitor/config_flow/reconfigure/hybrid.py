"""Hybrid reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for hybrid (cloud + local) connections,
allowing users to update HTTP credentials and manage local transport settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.data_entry_flow import AbortFlow
from pylxpweb.exceptions import (
    LuxpowerAPIError,
    LuxpowerAuthError,
    LuxpowerConnectionError,
)

from ...const import (
    BRAND_NAME,
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_DST_SYNC,
    CONF_HYBRID_LOCAL_TYPE,
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HYBRID,
    DEFAULT_BASE_URL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
    HYBRID_LOCAL_DONGLE,
    HYBRID_LOCAL_MODBUS,
)
from ..discovery import DiscoveredDevice
from ..helpers import find_plant_by_id, format_entry_title, get_reconfigure_entry

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol
else:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

_LOGGER = logging.getLogger(__name__)


class HybridReconfigureMixin:
    """Mixin providing Hybrid (cloud + local) reconfiguration flow steps.

    This mixin handles reconfiguration for hybrid connections with a menu-based UI:

    1. Main menu: Choose "Update Credentials" or "Manage Local Transports"
    2. Credentials flow: Update HTTP settings, optionally change plant
    3. Transports flow: List, add, edit, or remove local transports

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _test_credentials() method from EG4ConfigFlowBase
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - _test_dongle_connection() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        # HTTP fields
        _username: str | None
        _password: str | None
        _base_url: str | None
        _verify_ssl: bool | None
        _dst_sync: bool | None
        _plants: list[dict[str, Any]] | None
        _plant_id: str | None
        # Modbus fields
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        _inverter_serial: str | None
        _inverter_family: str | None
        # Dongle fields
        _dongle_host: str | None
        _dongle_port: int | None
        _dongle_serial: str | None
        # Hybrid per-device flow fields (shared with onboarding)
        _hybrid_local_transports: list[dict[str, Any]] | None
        _reconfigure_device_index: int | None

        async def _test_credentials(self: ConfigFlowProtocol) -> None: ...
        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def _test_dongle_connection(self: ConfigFlowProtocol) -> None: ...
        async def _discover_modbus_device(
            self: ConfigFlowProtocol,
            host: str,
            port: int,
            unit_id: int,
        ) -> DiscoveredDevice: ...
        async def _discover_dongle_device(
            self: ConfigFlowProtocol,
            host: str,
            dongle_serial: str,
            inverter_serial: str,
            port: int,
        ) -> DiscoveredDevice: ...
        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> Any: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_abort(
            self: ConfigFlowProtocol,
            *,
            reason: str,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_show_menu(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            menu_options: list[str] | dict[str, str],
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...

    async def async_step_reconfigure_hybrid(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show menu for hybrid reconfiguration options.

        Gold tier requirement: Reconfiguration available through UI.

        Args:
            user_input: Not used for menu step.

        Returns:
            Menu with credential update and transport management options.
        """
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Get current transport summary for description
        transports = entry.data.get(CONF_LOCAL_TRANSPORTS, [])
        transport_count = len(transports)

        return self.async_show_menu(
            step_id="reconfigure_hybrid",
            menu_options={
                "reconfigure_hybrid_credentials": "Update Cloud Credentials",
                "reconfigure_hybrid_transports": "Manage Local Transports",
            },
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
                "transport_count": str(transport_count),
            },
        )

    async def async_step_reconfigure_hybrid_credentials(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle HTTP credential reconfiguration for hybrid mode.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to update HTTP settings, plant selection, or abort on completion.
        """
        errors: dict[str, str] = {}

        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            # Store HTTP credentials
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            self._verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            self._dst_sync = user_input.get(CONF_DST_SYNC, True)

            try:
                # Test HTTP credentials
                await self._test_credentials()

                # Check if we're changing accounts (username changed)
                if self._username != entry.data.get(CONF_USERNAME):
                    # Changing accounts - need to select plant again
                    assert self._plants is not None, "Plants must be loaded"
                    if len(self._plants) == 1:
                        plant = self._plants[0]
                        self._plant_id = plant["plantId"]
                        return await self._update_hybrid_credentials(
                            entry=entry,
                            plant_id=plant["plantId"],
                            plant_name=plant["name"],
                        )
                    # Multiple plants - show selection step
                    return await self.async_step_reconfigure_hybrid_plant()

                # Same account - keep existing plant
                plant_id = entry.data.get(CONF_PLANT_ID)
                plant_name = entry.data.get(CONF_PLANT_NAME)
                assert plant_id is not None and plant_name is not None, (
                    "Plant ID and name must be set"
                )
                return await self._update_hybrid_credentials(
                    entry=entry,
                    plant_id=plant_id,
                    plant_name=plant_name,
                )

            except LuxpowerAuthError:
                errors["base"] = "invalid_auth"
            except LuxpowerConnectionError:
                errors["base"] = "cannot_connect"
            except LuxpowerAPIError as e:
                _LOGGER.error("API error during reconfiguration: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error during reconfiguration: %s", e)
                errors["base"] = "unknown"

        # Build HTTP credentials schema with current values
        credentials_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME)): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_BASE_URL,
                    default=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                ): str,
                vol.Optional(
                    CONF_VERIFY_SSL, default=entry.data.get(CONF_VERIFY_SSL, True)
                ): bool,
                vol.Optional(
                    CONF_DST_SYNC, default=entry.data.get(CONF_DST_SYNC, True)
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_credentials",
            data_schema=credentials_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def async_step_reconfigure_hybrid_plant(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant selection during hybrid reconfiguration.

        Args:
            user_input: Form data with plant selection, or None for initial display.

        Returns:
            Form to select plant, or abort on completion.
        """
        errors: dict[str, str] = {}

        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            try:
                plant_id = user_input[CONF_PLANT_ID]

                # Find the selected plant using helper
                selected_plant = find_plant_by_id(self._plants, plant_id)

                if not selected_plant:
                    errors["base"] = "invalid_plant"
                else:
                    return await self._update_hybrid_credentials(
                        entry=entry,
                        plant_id=selected_plant["plantId"],
                        plant_name=selected_plant["name"],
                    )

            except AbortFlow:
                raise
            except Exception as e:
                _LOGGER.exception("Error during plant selection: %s", e)
                errors["base"] = "unknown"

        # Build plant selection schema
        plant_options = {
            plant["plantId"]: plant["name"] for plant in self._plants or []
        }

        plant_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PLANT_ID, default=entry.data.get(CONF_PLANT_ID)
                ): vol.In(plant_options),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_plant",
            data_schema=plant_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "plant_count": str(len(plant_options)),
                "current_station": entry.data.get(CONF_PLANT_NAME, "Unknown"),
            },
        )

    async def async_step_reconfigure_hybrid_transports(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show transport management menu for hybrid mode.

        Lists current transports and allows add/edit/remove operations.

        Args:
            user_input: Form data with action selection, or None for display.

        Returns:
            Form with transport list and actions.
        """
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Initialize transports list from entry if not already done
        if self._hybrid_local_transports is None:
            self._hybrid_local_transports = list(
                entry.data.get(CONF_LOCAL_TRANSPORTS, [])
            )

        if user_input is not None:
            action = user_input.get("action", "done")

            if action == "add":
                return await self.async_step_reconfigure_hybrid_add_transport()
            elif action.startswith("edit_"):
                # Extract device index from action
                try:
                    idx = int(action.replace("edit_", ""))
                    self._reconfigure_device_index = idx
                    return await self.async_step_reconfigure_hybrid_edit_transport()
                except (ValueError, IndexError):
                    pass
            elif action.startswith("remove_"):
                # Extract device index and remove
                try:
                    idx = int(action.replace("remove_", ""))
                    if 0 <= idx < len(self._hybrid_local_transports):
                        removed = self._hybrid_local_transports.pop(idx)
                        _LOGGER.info(
                            "Removed transport for device %s",
                            removed.get("serial", "unknown"),
                        )
                except (ValueError, IndexError):
                    pass
            elif action == "done":
                return await self._update_hybrid_transports(entry)

        # Build action options including edit/remove for each transport
        action_options: dict[str, str] = {"add": "Add New Device Transport"}

        transports = self._hybrid_local_transports or []
        for idx, transport in enumerate(transports):
            serial = transport.get("serial", "Unknown")
            transport_type = transport.get("transport_type", "unknown")
            host = transport.get("host", "Unknown")
            label = f"{serial} ({transport_type} @ {host})"
            action_options[f"edit_{idx}"] = f"Edit: {label}"
            action_options[f"remove_{idx}"] = f"Remove: {label}"

        action_options["done"] = "Save and Finish"

        schema = vol.Schema(
            {
                vol.Required("action", default="done"): vol.In(action_options),
            }
        )

        # Build device list summary for description
        device_list = []
        for transport in transports:
            serial = transport.get("serial", "Unknown")
            ttype = transport.get("transport_type", "unknown")
            host = transport.get("host", "Unknown")
            device_list.append(f"• {serial}: {ttype} @ {host}")

        device_summary = (
            "\n".join(device_list) if device_list else "(No local transports)"
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_transports",
            data_schema=schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(len(transports)),
                "device_list": device_summary,
            },
        )

    async def async_step_reconfigure_hybrid_add_transport(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select transport type when adding a new device.

        Args:
            user_input: Form data with transport type selection, or None.

        Returns:
            Transport type selection form, or modbus/dongle config step.
        """
        if user_input is not None:
            transport_type = user_input.get("transport_type", "modbus")

            if transport_type == "modbus":
                return await self.async_step_reconfigure_hybrid_add_modbus()
            elif transport_type == "dongle":
                return await self.async_step_reconfigure_hybrid_add_dongle()

        schema = vol.Schema(
            {
                vol.Required("transport_type", default="modbus"): vol.In(
                    {
                        "modbus": "Modbus TCP (RS485 Adapter)",
                        "dongle": "WiFi Dongle",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_add_transport",
            data_schema=schema,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_hybrid_add_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new Modbus transport with auto-discovery.

        Uses auto-discovery to detect serial, model, and family from the device.
        User only needs to provide connection details (host, port, unit_id).

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Modbus config form, or back to transports list on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get(CONF_MODBUS_HOST, "").strip()
            port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)

            if not host:
                errors[CONF_MODBUS_HOST] = "required"
            else:
                try:
                    # Auto-discover device info (serial, model, family)
                    discovered = await self._discover_modbus_device(
                        host=host,
                        port=port,
                        unit_id=unit_id,
                    )

                    # Check for duplicate serial
                    existing_serials = {
                        t.get("serial") for t in (self._hybrid_local_transports or [])
                    }
                    if discovered.serial in existing_serials:
                        errors["base"] = "duplicate_serial"
                    else:
                        # Add to transports list
                        assert self._hybrid_local_transports is not None
                        self._hybrid_local_transports.append(
                            {
                                "serial": discovered.serial,
                                "transport_type": "modbus_tcp",
                                "host": host,
                                "port": port,
                                "unit_id": unit_id,
                                "inverter_family": discovered.family,
                                "model": discovered.model,
                                "is_gridboss": discovered.is_gridboss,
                                "parallel_number": discovered.parallel_number,
                                "parallel_master_slave": discovered.parallel_master_slave,
                                "parallel_phase": discovered.parallel_phase,
                            }
                        )

                        _LOGGER.info(
                            "Discovered and added Modbus transport: "
                            "serial=%s, model=%s, family=%s at %s:%s",
                            discovered.serial,
                            discovered.model,
                            discovered.family,
                            host,
                            port,
                        )

                        return await self.async_step_reconfigure_hybrid_transports()

                except ImportError:
                    errors["base"] = "modbus_not_installed"
                except TimeoutError:
                    errors["base"] = "modbus_timeout"
                except OSError as e:
                    _LOGGER.error("Modbus connection error: %s", e)
                    errors["base"] = "modbus_connection_failed"
                except Exception as e:
                    _LOGGER.exception("Unexpected Modbus error: %s", e)
                    errors["base"] = "unknown"

        # Minimal schema - just connection details, everything else auto-detected
        schema = vol.Schema(
            {
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_add_modbus",
            data_schema=schema,
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_hybrid_add_dongle(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new WiFi Dongle transport with auto-discovery.

        Uses auto-discovery to detect model and family from the device.
        User provides connection details and inverter serial (required for auth).

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Dongle config form, or back to transports list on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get(CONF_DONGLE_HOST, "").strip()
            port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input.get(CONF_DONGLE_SERIAL, "").strip()
            inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "").strip()

            if not host:
                errors[CONF_DONGLE_HOST] = "required"
            elif not dongle_serial:
                errors[CONF_DONGLE_SERIAL] = "required"
            elif not inverter_serial:
                errors[CONF_INVERTER_SERIAL] = "required"
            else:
                try:
                    # Auto-discover device info (model, family)
                    discovered = await self._discover_dongle_device(
                        host=host,
                        dongle_serial=dongle_serial,
                        inverter_serial=inverter_serial,
                        port=port,
                    )

                    # Check for duplicate serial
                    existing_serials = {
                        t.get("serial") for t in (self._hybrid_local_transports or [])
                    }
                    if inverter_serial in existing_serials:
                        errors["base"] = "duplicate_serial"
                    else:
                        # Add to transports list
                        assert self._hybrid_local_transports is not None
                        self._hybrid_local_transports.append(
                            {
                                "serial": inverter_serial,
                                "transport_type": "wifi_dongle",
                                "host": host,
                                "port": port,
                                "dongle_serial": dongle_serial,
                                "inverter_family": discovered.family,
                                "model": discovered.model,
                                "is_gridboss": discovered.is_gridboss,
                                "parallel_number": discovered.parallel_number,
                                "parallel_master_slave": discovered.parallel_master_slave,
                                "parallel_phase": discovered.parallel_phase,
                            }
                        )

                        _LOGGER.info(
                            "Discovered and added WiFi Dongle transport: "
                            "serial=%s, model=%s, family=%s at %s:%s",
                            inverter_serial,
                            discovered.model,
                            discovered.family,
                            host,
                            port,
                        )

                        return await self.async_step_reconfigure_hybrid_transports()

                except TimeoutError:
                    errors["base"] = "dongle_timeout"
                except OSError as e:
                    _LOGGER.error("Dongle connection error: %s", e)
                    errors["base"] = "dongle_connection_failed"
                except Exception as e:
                    _LOGGER.exception("Unexpected dongle error: %s", e)
                    errors["base"] = "unknown"

        # Dongle requires: host, dongle_serial, inverter_serial (for auth)
        # Family is auto-detected from registers
        schema = vol.Schema(
            {
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_hybrid_add_dongle",
            data_schema=schema,
            errors=errors,
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def async_step_reconfigure_hybrid_edit_transport(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing transport (connection details only, not serial).

        Uses auto-discovery to detect model and family from the device.
        User provides connection details; serial is preserved from original config.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Edit form pre-filled with current values, or back to list on success.
        """
        errors: dict[str, str] = {}

        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        idx = self._reconfigure_device_index
        if idx is None or not self._hybrid_local_transports:
            return await self.async_step_reconfigure_hybrid_transports()

        if idx >= len(self._hybrid_local_transports):
            return await self.async_step_reconfigure_hybrid_transports()

        current_transport = self._hybrid_local_transports[idx]
        transport_type = current_transport.get("transport_type", "modbus_tcp")
        original_serial = current_transport.get("serial", "")

        if user_input is not None:
            # Update based on transport type
            if transport_type == "modbus_tcp":
                host = user_input.get(CONF_MODBUS_HOST, "").strip()
                port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
                unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)

                if not host:
                    errors[CONF_MODBUS_HOST] = "required"
                else:
                    try:
                        # Auto-discover device info (serial, model, family)
                        discovered = await self._discover_modbus_device(
                            host=host,
                            port=port,
                            unit_id=unit_id,
                        )

                        # Verify discovered serial matches original
                        if discovered.serial != original_serial:
                            _LOGGER.warning(
                                "Discovered serial %s doesn't match expected %s",
                                discovered.serial,
                                original_serial,
                            )
                            errors["base"] = "serial_mismatch"
                        else:
                            # Update transport with discovered info
                            self._hybrid_local_transports[idx] = {
                                "serial": original_serial,
                                "transport_type": "modbus_tcp",
                                "host": host,
                                "port": port,
                                "unit_id": unit_id,
                                "inverter_family": discovered.family,
                                "model": discovered.model,
                                "is_gridboss": discovered.is_gridboss,
                                "parallel_number": discovered.parallel_number,
                                "parallel_master_slave": discovered.parallel_master_slave,
                                "parallel_phase": discovered.parallel_phase,
                            }

                            _LOGGER.info(
                                "Updated Modbus transport: serial=%s, model=%s, "
                                "family=%s at %s:%s",
                                original_serial,
                                discovered.model,
                                discovered.family,
                                host,
                                port,
                            )

                            return await self.async_step_reconfigure_hybrid_transports()

                    except ImportError:
                        errors["base"] = "modbus_not_installed"
                    except TimeoutError:
                        errors["base"] = "modbus_timeout"
                    except OSError as e:
                        _LOGGER.error("Modbus connection error: %s", e)
                        errors["base"] = "modbus_connection_failed"
                    except Exception as e:
                        _LOGGER.exception("Unexpected error: %s", e)
                        errors["base"] = "unknown"

            elif transport_type == "wifi_dongle":
                host = user_input.get(CONF_DONGLE_HOST, "").strip()
                port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
                dongle_serial = user_input.get(CONF_DONGLE_SERIAL, "").strip()

                if not host:
                    errors[CONF_DONGLE_HOST] = "required"
                elif not dongle_serial:
                    errors[CONF_DONGLE_SERIAL] = "required"
                else:
                    try:
                        # Auto-discover device info (model, family)
                        discovered = await self._discover_dongle_device(
                            host=host,
                            dongle_serial=dongle_serial,
                            inverter_serial=original_serial,
                            port=port,
                        )

                        # Update transport with discovered info
                        self._hybrid_local_transports[idx] = {
                            "serial": original_serial,
                            "transport_type": "wifi_dongle",
                            "host": host,
                            "port": port,
                            "dongle_serial": dongle_serial,
                            "inverter_family": discovered.family,
                            "model": discovered.model,
                            "is_gridboss": discovered.is_gridboss,
                            "parallel_number": discovered.parallel_number,
                            "parallel_master_slave": discovered.parallel_master_slave,
                            "parallel_phase": discovered.parallel_phase,
                        }

                        _LOGGER.info(
                            "Updated WiFi Dongle transport: serial=%s, model=%s, "
                            "family=%s at %s:%s",
                            original_serial,
                            discovered.model,
                            discovered.family,
                            host,
                            port,
                        )

                        return await self.async_step_reconfigure_hybrid_transports()

                    except TimeoutError:
                        errors["base"] = "dongle_timeout"
                    except OSError as e:
                        _LOGGER.error("Dongle connection error: %s", e)
                        errors["base"] = "dongle_connection_failed"
                    except Exception as e:
                        _LOGGER.exception("Unexpected error: %s", e)
                        errors["base"] = "unknown"

        # Build form based on transport type - minimal fields, family auto-detected
        serial = current_transport.get("serial", "Unknown")

        if transport_type == "modbus_tcp":
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_MODBUS_HOST,
                        default=current_transport.get("host", ""),
                    ): str,
                    vol.Optional(
                        CONF_MODBUS_PORT,
                        default=current_transport.get("port", DEFAULT_MODBUS_PORT),
                    ): int,
                    vol.Optional(
                        CONF_MODBUS_UNIT_ID,
                        default=current_transport.get(
                            "unit_id", DEFAULT_MODBUS_UNIT_ID
                        ),
                    ): int,
                }
            )
        else:  # wifi_dongle
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_DONGLE_HOST,
                        default=current_transport.get("host", ""),
                    ): str,
                    vol.Optional(
                        CONF_DONGLE_PORT,
                        default=current_transport.get("port", DEFAULT_DONGLE_PORT),
                    ): int,
                    vol.Required(
                        CONF_DONGLE_SERIAL,
                        default=current_transport.get("dongle_serial", ""),
                    ): str,
                }
            )

        return self.async_show_form(
            step_id="reconfigure_hybrid_edit_transport",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_serial": serial,
                "transport_type": transport_type,
            },
        )

    async def _update_hybrid_credentials(
        self: ConfigFlowProtocol,
        entry: config_entries.ConfigEntry[Any],
        plant_id: str,
        plant_name: str,
    ) -> ConfigFlowResult:
        """Update the Hybrid config entry with new HTTP credentials.

        Preserves existing local transports.

        Args:
            entry: The config entry to update.
            plant_id: The plant/station ID.
            plant_name: The plant/station name.

        Returns:
            Abort result indicating success or conflict.
        """
        assert self._username is not None
        assert self._password is not None
        assert self._base_url is not None
        assert self._verify_ssl is not None
        assert self._dst_sync is not None

        unique_id = f"hybrid_{self._username}_{plant_id}"

        # Check for conflicts
        existing_entry = await self.async_set_unique_id(unique_id)
        if existing_entry and existing_entry.entry_id != entry.entry_id:
            _LOGGER.warning(
                "Cannot reconfigure to account %s with plant %s - already configured",
                self._username,
                plant_name,
            )
            return self.async_abort(reason="already_configured")

        title = format_entry_title("hybrid", plant_name)

        # Build updated data preserving existing transports
        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HYBRID,
            # HTTP settings (updated)
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_BASE_URL: self._base_url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_DST_SYNC: self._dst_sync,
            CONF_PLANT_ID: plant_id,
            CONF_PLANT_NAME: plant_name,
            # Preserve existing local transport settings
            CONF_LOCAL_TRANSPORTS: entry.data.get(CONF_LOCAL_TRANSPORTS, []),
        }

        # Preserve backward-compatible fields
        for key in [
            CONF_HYBRID_LOCAL_TYPE,
            CONF_INVERTER_SERIAL,
            CONF_INVERTER_FAMILY,
            CONF_MODBUS_HOST,
            CONF_MODBUS_PORT,
            CONF_MODBUS_UNIT_ID,
            CONF_DONGLE_HOST,
            CONF_DONGLE_PORT,
            CONF_DONGLE_SERIAL,
        ]:
            if key in entry.data:
                data[key] = entry.data[key]

        self.hass.config_entries.async_update_entry(
            entry,
            title=title,
            data=data,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)

        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )

    async def _update_hybrid_transports(
        self: ConfigFlowProtocol,
        entry: config_entries.ConfigEntry[Any],
    ) -> ConfigFlowResult:
        """Update the Hybrid config entry with modified local transports.

        Preserves existing HTTP credentials.

        Args:
            entry: The config entry to update.

        Returns:
            Abort result indicating success.
        """
        # Build updated data preserving HTTP settings
        data = dict(entry.data)

        # Update transports list
        data[CONF_LOCAL_TRANSPORTS] = self._hybrid_local_transports or []

        # Update backward-compatible fields from first transport
        transports = self._hybrid_local_transports or []
        if transports:
            first = transports[0]
            if first.get("transport_type") == "modbus_tcp":
                data[CONF_HYBRID_LOCAL_TYPE] = HYBRID_LOCAL_MODBUS
                data[CONF_MODBUS_HOST] = first.get("host", "")
                data[CONF_MODBUS_PORT] = first.get("port", DEFAULT_MODBUS_PORT)
                data[CONF_MODBUS_UNIT_ID] = first.get("unit_id", DEFAULT_MODBUS_UNIT_ID)
            elif first.get("transport_type") == "wifi_dongle":
                data[CONF_HYBRID_LOCAL_TYPE] = HYBRID_LOCAL_DONGLE
                data[CONF_DONGLE_HOST] = first.get("host", "")
                data[CONF_DONGLE_PORT] = first.get("port", DEFAULT_DONGLE_PORT)
                data[CONF_DONGLE_SERIAL] = first.get("dongle_serial", "")

            data[CONF_INVERTER_SERIAL] = first.get("serial", "")
            data[CONF_INVERTER_FAMILY] = first.get(
                "inverter_family", DEFAULT_INVERTER_FAMILY
            )
        else:
            # No transports - clear legacy fields
            data.pop(CONF_HYBRID_LOCAL_TYPE, None)
            data.pop(CONF_MODBUS_HOST, None)
            data.pop(CONF_MODBUS_PORT, None)
            data.pop(CONF_MODBUS_UNIT_ID, None)
            data.pop(CONF_DONGLE_HOST, None)
            data.pop(CONF_DONGLE_PORT, None)
            data.pop(CONF_DONGLE_SERIAL, None)

        self.hass.config_entries.async_update_entry(
            entry,
            data=data,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)

        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders={"brand_name": BRAND_NAME},
        )

    # Keep legacy method for backward compatibility with existing tests
    async def _update_hybrid_entry_from_reconfigure(
        self: ConfigFlowProtocol,
        entry: config_entries.ConfigEntry[Any],
        plant_id: str,
        plant_name: str,
    ) -> ConfigFlowResult:
        """Legacy method - redirects to _update_hybrid_credentials."""
        return await self._update_hybrid_credentials(entry, plant_id, plant_name)
