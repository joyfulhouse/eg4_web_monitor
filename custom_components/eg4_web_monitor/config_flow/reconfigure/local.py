"""Local reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for pure local (no cloud) connections,
allowing users to manage their local device configurations.

Uses the same simplified auto-detection flow as onboarding:
- Modbus: Only requires host IP (auto-detects serial, model, family)
- Dongle: Requires host + dongle serial + inverter serial (auto-detects model, family)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_DONGLE_HOST,
    CONF_DONGLE_PORT,
    CONF_DONGLE_SERIAL,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
)
from ..discovery import build_device_config
from ..helpers import build_unique_id, format_entry_title, get_reconfigure_entry

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol
    from ..discovery import DiscoveredDevice

_LOGGER = logging.getLogger(__name__)


class LocalReconfigureMixin:
    """Mixin providing Local (no cloud) reconfiguration flow steps.

    This mixin handles reconfiguration for pure local connections using
    the same simplified auto-detection flow as onboarding:

    1. Show current device list with options to add/edit/remove
    2. For new/edited devices: minimal input, auto-detect details
    3. Update config entry and reload

    The LOCAL mode is designed for users who want purely local operation
    without any cloud credentials.

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _discover_modbus_device() method from EG4ConfigFlowBase
        - _discover_dongle_device() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        # Local devices accumulator (None until loaded from entry)
        _local_devices: list[dict[str, Any]] | None
        _local_station_name: str | None
        # Reconfigure state
        _reconfigure_device_index: int | None
        _reconfigure_action: str | None
        # Pending device from discovery
        _pending_device: DiscoveredDevice | None
        _pending_transport_type: str | None
        _pending_host: str | None
        _pending_port: int | None
        _pending_unit_id: int | None
        _pending_dongle_serial: str | None

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
        def _abort_if_unique_id_configured(self: ConfigFlowProtocol) -> None: ...
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

    async def async_step_reconfigure_local(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Local reconfiguration flow - manage local devices.

        Gold tier requirement: Reconfiguration available through UI.

        For local mode, reconfiguration allows:
        - Viewing current devices
        - Adding new devices
        - Editing existing devices
        - Removing devices

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to manage devices, or abort on completion.
        """
        errors: dict[str, str] = {}

        # Get the current entry being reconfigured
        entry = get_reconfigure_entry(self.hass, self.context)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Load current devices from config entry (only on first entry to reconfigure)
        # _local_devices is initialized to None in base.py, so we check for None
        if self._local_devices is None:
            self._local_devices = list(entry.data.get(CONF_LOCAL_TRANSPORTS, []))
            _LOGGER.debug(
                "Loaded %d devices from config entry for reconfigure",
                len(self._local_devices),
            )
            self._local_station_name = entry.data.get("station_name")

        if user_input is not None:
            action = user_input.get("action")

            if action == "save":
                # Save current configuration
                return await self._update_local_entry(entry)
            if action == "add_modbus":
                # Add a new Modbus device
                return await self.async_step_reconfigure_local_modbus()
            if action == "add_dongle":
                # Add a new Dongle device
                return await self.async_step_reconfigure_local_dongle()
            if action and action.startswith("edit_"):
                # Edit existing device
                try:
                    device_index = int(action.replace("edit_", ""))
                    self._reconfigure_device_index = device_index
                    device = self._local_devices[device_index]
                    if device.get("transport_type") == "modbus_tcp":
                        return await self.async_step_reconfigure_local_modbus()
                    return await self.async_step_reconfigure_local_dongle()
                except (ValueError, IndexError):
                    errors["base"] = "unknown"
            if action and action.startswith("remove_"):
                # Remove device
                try:
                    device_index = int(action.replace("remove_", ""))
                    if len(self._local_devices) > 1:
                        self._local_devices.pop(device_index)
                    else:
                        # Can't remove last device
                        errors["base"] = "cannot_remove_last_device"
                except (ValueError, IndexError):
                    errors["base"] = "unknown"

        # Build device list display
        device_count = len(self._local_devices)
        device_descriptions: list[str] = []
        action_options: dict[str, str] = {}

        for i, device in enumerate(self._local_devices):
            transport = device.get("transport_type", "unknown")
            serial = device.get("serial", "Unknown")
            host = device.get("host", "Unknown")
            model = device.get("model", "Unknown")
            is_gridboss = device.get("is_gridboss", False)

            # Build device type string
            if is_gridboss:
                device_type = "GridBOSS"
            else:
                device_type = f"Inverter ({model})"

            # Build transport string
            if transport == "modbus_tcp":
                transport_str = "Modbus TCP"
            elif transport == "wifi_dongle":
                transport_str = "WiFi Dongle"
            else:
                transport_str = transport

            desc = f"{i + 1}. {device_type}: {serial} @ {host} [{transport_str}]"
            device_descriptions.append(desc)
            action_options[f"edit_{i}"] = f"Edit device {i + 1} ({serial})"
            action_options[f"remove_{i}"] = f"Remove device {i + 1} ({serial})"

        # Add new device options
        action_options["add_modbus"] = "Add Modbus device"
        action_options["add_dongle"] = "Add WiFi Dongle device"
        action_options["save"] = "Save and finish"

        # Build schema
        reconfigure_schema = vol.Schema(
            {
                vol.Required("action", default="save"): vol.In(action_options),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_local",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
                "device_list": "\n".join(device_descriptions)
                if device_descriptions
                else "No devices configured",
            },
        )

    async def async_step_reconfigure_local_modbus(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus device configuration during local reconfiguration.

        Uses simplified auto-detection: only requires host IP.
        Serial, model, and family are auto-detected from device registers.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to configure Modbus device, or redirect to discovered step.
        """
        errors: dict[str, str] = {}

        # Get defaults from existing device if editing
        defaults: dict[str, Any] = {}
        editing = (
            hasattr(self, "_reconfigure_device_index")
            and self._reconfigure_device_index is not None
        )
        if editing:
            try:
                device = self._local_devices[self._reconfigure_device_index]  # type: ignore[index]
                defaults = {
                    CONF_MODBUS_HOST: device.get("host", ""),
                    CONF_MODBUS_PORT: device.get("port", DEFAULT_MODBUS_PORT),
                    CONF_MODBUS_UNIT_ID: device.get("unit_id", DEFAULT_MODBUS_UNIT_ID),
                }
            except (IndexError, TypeError):
                editing = False

        if user_input is not None:
            host = user_input[CONF_MODBUS_HOST]
            port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            unit_id = user_input.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID)

            # Auto-detect device information
            try:
                discovered = await self._discover_modbus_device(host, port, unit_id)

                # Check for duplicate serial (excluding current device if editing)
                assert self._local_devices is not None
                for i, device in enumerate(self._local_devices):
                    if editing and i == self._reconfigure_device_index:
                        continue
                    if device.get("serial") == discovered.serial:
                        errors["base"] = "duplicate_serial"
                        break

                if not errors:
                    # Store pending device for confirmation
                    self._pending_device = discovered
                    self._pending_transport_type = "modbus_tcp"
                    self._pending_host = host
                    self._pending_port = port
                    self._pending_unit_id = unit_id
                    return await self.async_step_reconfigure_local_discovered()

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

        # Build simplified Modbus schema - only connection params
        modbus_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST, default=defaults.get(CONF_MODBUS_HOST, "")
                ): str,
                vol.Optional(
                    CONF_MODBUS_PORT,
                    default=defaults.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT),
                ): int,
                vol.Optional(
                    CONF_MODBUS_UNIT_ID,
                    default=defaults.get(CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_local_modbus",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "editing": "true" if editing else "false",
            },
        )

    async def async_step_reconfigure_local_dongle(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle device configuration during local reconfiguration.

        Uses simplified auto-detection: requires host + dongle serial + inverter serial.
        Model, family, and firmware are auto-detected from device registers.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to configure dongle device, or redirect to discovered step.
        """
        errors: dict[str, str] = {}

        # Get defaults from existing device if editing
        defaults: dict[str, Any] = {}
        editing = (
            hasattr(self, "_reconfigure_device_index")
            and self._reconfigure_device_index is not None
        )
        if editing:
            try:
                device = self._local_devices[self._reconfigure_device_index]  # type: ignore[index]
                defaults = {
                    CONF_DONGLE_HOST: device.get("host", ""),
                    CONF_DONGLE_PORT: device.get("port", DEFAULT_DONGLE_PORT),
                    CONF_DONGLE_SERIAL: device.get("dongle_serial", ""),
                    CONF_INVERTER_SERIAL: device.get("serial", ""),
                }
            except (IndexError, TypeError):
                editing = False

        if user_input is not None:
            host = user_input[CONF_DONGLE_HOST]
            port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            dongle_serial = user_input[CONF_DONGLE_SERIAL]
            inverter_serial = user_input[CONF_INVERTER_SERIAL]

            # Auto-detect device information
            try:
                discovered = await self._discover_dongle_device(
                    host=host,
                    dongle_serial=dongle_serial,
                    inverter_serial=inverter_serial,
                    port=port,
                )

                # Check for duplicate serial (excluding current device if editing)
                assert self._local_devices is not None
                for i, device in enumerate(self._local_devices):
                    if editing and i == self._reconfigure_device_index:
                        continue
                    if device.get("serial") == discovered.serial:
                        errors["base"] = "duplicate_serial"
                        break

                if not errors:
                    # Store pending device for confirmation
                    self._pending_device = discovered
                    self._pending_transport_type = "wifi_dongle"
                    self._pending_host = host
                    self._pending_port = port
                    self._pending_unit_id = None
                    self._pending_dongle_serial = dongle_serial
                    return await self.async_step_reconfigure_local_discovered()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        # Build simplified dongle schema - only connection params
        dongle_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DONGLE_HOST, default=defaults.get(CONF_DONGLE_HOST, "")
                ): str,
                vol.Required(
                    CONF_DONGLE_SERIAL, default=defaults.get(CONF_DONGLE_SERIAL, "")
                ): str,
                vol.Required(
                    CONF_INVERTER_SERIAL, default=defaults.get(CONF_INVERTER_SERIAL, "")
                ): str,
                vol.Optional(
                    CONF_DONGLE_PORT,
                    default=defaults.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="reconfigure_local_dongle",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "editing": "true" if editing else "false",
            },
        )

    async def async_step_reconfigure_local_discovered(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered device info and confirm adding to device list.

        This step displays the auto-detected device information and lets the user
        confirm adding it to their local installation.

        Args:
            user_input: Form data with confirmation, or None.

        Returns:
            Form showing discovered device, or back to device list.
        """
        if user_input is not None:
            # Add the pending device to the list
            assert self._pending_device is not None
            assert self._pending_transport_type is not None
            assert self._pending_host is not None
            assert self._pending_port is not None

            device_config = build_device_config(
                discovered=self._pending_device,
                transport_type=self._pending_transport_type,
                host=self._pending_host,
                port=self._pending_port,
                unit_id=self._pending_unit_id,
                dongle_serial=self._pending_dongle_serial,
            )

            editing = (
                hasattr(self, "_reconfigure_device_index")
                and self._reconfigure_device_index is not None
            )
            assert self._local_devices is not None
            if editing and self._reconfigure_device_index is not None:
                # Update existing device
                self._local_devices[self._reconfigure_device_index] = device_config
            else:
                # Add new device
                self._local_devices.append(device_config)

            _LOGGER.info(
                "Added %s device: serial=%s, model=%s, family=%s",
                "GridBOSS" if self._pending_device.is_gridboss else "inverter",
                self._pending_device.serial,
                self._pending_device.model,
                self._pending_device.family,
            )

            # Clear pending state
            self._pending_device = None
            self._pending_transport_type = None
            self._pending_host = None
            self._pending_port = None
            self._pending_unit_id = None
            self._pending_dongle_serial = None
            self._reconfigure_device_index = None

            # Return to device list
            return await self.async_step_reconfigure_local()

        # Build simple confirmation schema
        confirm_schema = vol.Schema({})

        # Get info about the discovered device for display
        assert self._pending_device is not None
        device_type = "GridBOSS" if self._pending_device.is_gridboss else "Inverter"

        return self.async_show_form(
            step_id="reconfigure_local_discovered",
            data_schema=confirm_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_type": device_type,
                "device_serial": self._pending_device.serial,
                "device_model": self._pending_device.model,
                "device_family": self._pending_device.family,
                "device_firmware": self._pending_device.firmware_version,
                "device_pv_power": str(int(self._pending_device.pv_power)),
                "device_battery_soc": str(self._pending_device.battery_soc),
            },
        )

    async def _update_local_entry(
        self: ConfigFlowProtocol, entry: config_entries.ConfigEntry[Any]
    ) -> ConfigFlowResult:
        """Update the Local config entry with new device data.

        Args:
            entry: The config entry to update.

        Returns:
            Abort result indicating success.
        """
        # Validate that we have at least one device
        if not self._local_devices:
            _LOGGER.error("Cannot save local entry with no devices")
            return self.async_abort(reason="no_devices")

        # Build unique ID from all device serials (sorted for consistency)
        serials = sorted(device.get("serial", "") for device in self._local_devices)
        unique_id = build_unique_id("local", station_name="_".join(serials))
        await self.async_set_unique_id(unique_id)
        # Note: We don't call _abort_if_unique_id_configured here because
        # the unique_id may legitimately change during reconfiguration

        # Create title
        if self._local_station_name:
            title = format_entry_title("local", self._local_station_name)
        else:
            # Use first serial as name if no station name provided
            first_serial = self._local_devices[0].get("serial", "Unknown")
            device_count = len(self._local_devices)
            if device_count == 1:
                title = format_entry_title("local", first_serial)
            else:
                title = format_entry_title(
                    "local", f"{first_serial} (+{device_count - 1})"
                )

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_LOCAL_TRANSPORTS: self._local_devices,
        }

        # Store optional station name
        if self._local_station_name:
            data["station_name"] = self._local_station_name

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
