"""Local reconfigure mixin for EG4 Web Monitor config flow.

This module provides reconfiguration for pure local (no cloud) connections,
allowing users to manage their local device configurations.
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
    CONF_INVERTER_FAMILY,
    CONF_INVERTER_MODEL,
    CONF_INVERTER_SERIAL,
    CONF_LOCAL_TRANSPORTS,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_INVERTER_FAMILY,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
)
from ..helpers import build_unique_id, format_entry_title, get_reconfigure_entry
from ..schemas import INVERTER_FAMILY_OPTIONS

if TYPE_CHECKING:
    from homeassistant import config_entries
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


class LocalReconfigureMixin:
    """Mixin providing Local (no cloud) reconfiguration flow steps.

    This mixin handles reconfiguration for pure local connections:

    1. Show current device list with options to add/edit/remove
    2. Update device configurations as needed
    3. Update config entry and reload

    The LOCAL mode is designed for users who want purely local operation
    without any cloud credentials.

    Gold tier requirement: Reconfiguration available through UI.

    Requires:
        - ConfigFlowProtocol attributes
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - _test_dongle_connection() method from EG4ConfigFlowBase
        - hass: HomeAssistant instance
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        hass: HomeAssistant
        context: dict[str, Any]
        # Modbus fields
        _modbus_host: str | None
        _modbus_port: int | None
        _modbus_unit_id: int | None
        # Dongle fields
        _dongle_host: str | None
        _dongle_port: int | None
        _dongle_serial: str | None
        # Shared local fields
        _inverter_serial: str | None
        _inverter_model: str | None
        _inverter_family: str | None
        # Local devices accumulator
        _local_devices: list[dict[str, Any]]
        _local_station_name: str | None
        # Reconfigure state
        _reconfigure_device_index: int | None
        _reconfigure_action: str | None

        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def _test_dongle_connection(self: ConfigFlowProtocol) -> None: ...
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

        # Load current devices from config
        if not hasattr(self, "_local_devices") or self._local_devices is None:
            self._local_devices = list(entry.data.get(CONF_LOCAL_TRANSPORTS, []))
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
            desc = f"{i + 1}. {transport}: {serial} @ {host}"
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

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to configure Modbus device, or redirect to main reconfigure.
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
                    CONF_INVERTER_SERIAL: device.get("serial", ""),
                    CONF_INVERTER_MODEL: device.get("model", ""),
                    CONF_INVERTER_FAMILY: device.get(
                        "inverter_family", DEFAULT_INVERTER_FAMILY
                    ),
                }
            except (IndexError, TypeError):
                editing = False

        if user_input is not None:
            # Store Modbus configuration temporarily
            self._modbus_host = user_input[CONF_MODBUS_HOST]
            self._modbus_port = user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT)
            self._modbus_unit_id = user_input.get(
                CONF_MODBUS_UNIT_ID, DEFAULT_MODBUS_UNIT_ID
            )
            self._inverter_serial = user_input.get(CONF_INVERTER_SERIAL, "")
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test Modbus connection
            try:
                detected_serial = await self._test_modbus_connection()
                # Use detected serial if user didn't provide one
                if not self._inverter_serial and detected_serial:
                    self._inverter_serial = detected_serial

                # Check for duplicate serial (excluding current device if editing)
                for i, device in enumerate(self._local_devices):
                    if editing and i == self._reconfigure_device_index:
                        continue
                    if device.get("serial") == self._inverter_serial:
                        errors["base"] = "duplicate_serial"
                        break

                if not errors:
                    # Build device config
                    device_config = {
                        "serial": self._inverter_serial,
                        "transport_type": "modbus_tcp",
                        "host": self._modbus_host,
                        "port": self._modbus_port,
                        "unit_id": self._modbus_unit_id,
                        "model": self._inverter_model or "",
                        "inverter_family": self._inverter_family
                        or DEFAULT_INVERTER_FAMILY,
                    }

                    if editing and self._reconfigure_device_index is not None:
                        # Update existing device
                        self._local_devices[self._reconfigure_device_index] = (
                            device_config
                        )
                    else:
                        # Add new device
                        self._local_devices.append(device_config)

                    # Reset editing state and return to main reconfigure
                    self._reconfigure_device_index = None
                    return await self.async_step_reconfigure_local()

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

        # Build Modbus configuration schema
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
                vol.Optional(
                    CONF_INVERTER_SERIAL, default=defaults.get(CONF_INVERTER_SERIAL, "")
                ): str,
                vol.Optional(
                    CONF_INVERTER_MODEL, default=defaults.get(CONF_INVERTER_MODEL, "")
                ): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY,
                    default=defaults.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY),
                ): vol.In(INVERTER_FAMILY_OPTIONS),
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

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to configure dongle device, or redirect to main reconfigure.
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
                    CONF_INVERTER_MODEL: device.get("model", ""),
                    CONF_INVERTER_FAMILY: device.get(
                        "inverter_family", DEFAULT_INVERTER_FAMILY
                    ),
                }
            except (IndexError, TypeError):
                editing = False

        if user_input is not None:
            # Store dongle configuration temporarily
            self._dongle_host = user_input[CONF_DONGLE_HOST]
            self._dongle_port = user_input.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT)
            self._dongle_serial = user_input[CONF_DONGLE_SERIAL]
            self._inverter_serial = user_input[CONF_INVERTER_SERIAL]
            self._inverter_model = user_input.get(CONF_INVERTER_MODEL, "")
            self._inverter_family = user_input.get(
                CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY
            )

            # Test dongle connection
            try:
                await self._test_dongle_connection()

                # Check for duplicate serial (excluding current device if editing)
                for i, device in enumerate(self._local_devices):
                    if editing and i == self._reconfigure_device_index:
                        continue
                    if device.get("serial") == self._inverter_serial:
                        errors["base"] = "duplicate_serial"
                        break

                if not errors:
                    # Build device config
                    device_config = {
                        "serial": self._inverter_serial,
                        "transport_type": "wifi_dongle",
                        "host": self._dongle_host,
                        "port": self._dongle_port,
                        "dongle_serial": self._dongle_serial,
                        "model": self._inverter_model or "",
                        "inverter_family": self._inverter_family
                        or DEFAULT_INVERTER_FAMILY,
                    }

                    if editing and self._reconfigure_device_index is not None:
                        # Update existing device
                        self._local_devices[self._reconfigure_device_index] = (
                            device_config
                        )
                    else:
                        # Add new device
                        self._local_devices.append(device_config)

                    # Reset editing state and return to main reconfigure
                    self._reconfigure_device_index = None
                    return await self.async_step_reconfigure_local()

            except TimeoutError:
                errors["base"] = "dongle_timeout"
            except OSError as e:
                _LOGGER.error("Dongle connection error: %s", e)
                errors["base"] = "dongle_connection_failed"
            except Exception as e:
                _LOGGER.exception("Unexpected dongle error: %s", e)
                errors["base"] = "unknown"

        # Build dongle configuration schema
        dongle_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DONGLE_HOST, default=defaults.get(CONF_DONGLE_HOST, "")
                ): str,
                vol.Optional(
                    CONF_DONGLE_PORT,
                    default=defaults.get(CONF_DONGLE_PORT, DEFAULT_DONGLE_PORT),
                ): int,
                vol.Required(
                    CONF_DONGLE_SERIAL, default=defaults.get(CONF_DONGLE_SERIAL, "")
                ): str,
                vol.Required(
                    CONF_INVERTER_SERIAL, default=defaults.get(CONF_INVERTER_SERIAL, "")
                ): str,
                vol.Optional(
                    CONF_INVERTER_MODEL, default=defaults.get(CONF_INVERTER_MODEL, "")
                ): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY,
                    default=defaults.get(CONF_INVERTER_FAMILY, DEFAULT_INVERTER_FAMILY),
                ): vol.In(INVERTER_FAMILY_OPTIONS),
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
