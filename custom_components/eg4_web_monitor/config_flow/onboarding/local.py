"""Local-only (no cloud) onboarding mixin for EG4 Web Monitor config flow.

This module provides the LOCAL connection type which allows users to configure
multiple local devices (Modbus and/or WiFi Dongle) without any cloud credentials.
This is useful for users who want purely local operation.
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
from ..helpers import build_unique_id, format_entry_title
from ..schemas import INVERTER_FAMILY_OPTIONS, LOCAL_DEVICE_TYPE_OPTIONS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol

_LOGGER = logging.getLogger(__name__)


class LocalOnboardingMixin:
    """Mixin providing Local-only (no cloud) onboarding flow steps.

    This mixin handles the initial setup for purely local connections without
    any cloud credentials. Users can add multiple local devices (Modbus and/or
    WiFi Dongle) to a single config entry:

    1. Show local setup intro/information
    2. Loop: Add local device (Modbus or Dongle)
    3. After each device: Ask if user wants to add more
    4. Create config entry with all local devices

    The LOCAL mode differs from HYBRID in that:
    - No cloud credentials required
    - Can configure multiple inverters in one entry
    - No plant/station concept - devices are purely local

    Requires:
        - ConfigFlowProtocol attributes
        - _test_modbus_connection() method from EG4ConfigFlowBase
        - _test_dongle_connection() method from EG4ConfigFlowBase
        - _local_devices list to accumulate device configs
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
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
        # Station name for display
        _local_station_name: str | None

        async def _test_modbus_connection(self: ConfigFlowProtocol) -> str: ...
        async def _test_dongle_connection(self: ConfigFlowProtocol) -> None: ...
        async def async_set_unique_id(
            self: ConfigFlowProtocol, unique_id: str
        ) -> None: ...
        def _abort_if_unique_id_configured(self: ConfigFlowProtocol) -> None: ...
        def async_show_form(
            self: ConfigFlowProtocol,
            *,
            step_id: str,
            data_schema: vol.Schema | None = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        def async_create_entry(
            self: ConfigFlowProtocol,
            *,
            title: str,
            data: dict[str, Any],
        ) -> ConfigFlowResult: ...

    async def async_step_local_setup(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial local setup step.

        This is the main entry point for LOCAL onboarding. Shows information
        about local-only mode and collects an optional station/installation name.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to start local setup, or next step.
        """
        if user_input is not None:
            # Store optional station name for display purposes
            self._local_station_name = (
                user_input.get("station_name", "").strip() or None
            )
            # Initialize or clear the local devices list
            self._local_devices = []
            return await self.async_step_local_add_device()

        # Build schema for local setup intro
        setup_schema = vol.Schema(
            {
                vol.Optional("station_name", default=""): str,
            }
        )

        return self.async_show_form(
            step_id="local_setup",
            data_schema=setup_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_local_add_device(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a local device - select device type.

        Args:
            user_input: Form data with device type selection, or None.

        Returns:
            Form to select device type, or appropriate config step.
        """
        if user_input is not None:
            device_type = user_input.get("device_type")

            if device_type == "modbus":
                return await self.async_step_local_modbus_device()
            if device_type == "dongle":
                return await self.async_step_local_dongle_device()
            # Shouldn't happen but default to modbus
            _LOGGER.warning(
                "Unexpected device_type value: %s, defaulting to Modbus", device_type
            )
            return await self.async_step_local_modbus_device()

        # Build device type selection schema
        device_type_schema = vol.Schema(
            {
                vol.Required("device_type", default="modbus"): vol.In(
                    LOCAL_DEVICE_TYPE_OPTIONS
                ),
            }
        )

        # Show how many devices have been added so far
        device_count = len(self._local_devices) if self._local_devices else 0

        return self.async_show_form(
            step_id="local_add_device",
            data_schema=device_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
            },
        )

    async def async_step_local_modbus_device(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus device configuration for local mode.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect Modbus settings, or device added confirmation.
        """
        errors: dict[str, str] = {}

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
                    _LOGGER.info(
                        "Auto-detected inverter serial from Modbus: %s",
                        detected_serial,
                    )

                # Check for duplicate serial in already-added devices
                if self._local_devices:
                    for device in self._local_devices:
                        if device.get("serial") == self._inverter_serial:
                            errors["base"] = "duplicate_serial"
                            break

                if not errors:
                    # Add device to list
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
                    self._local_devices.append(device_config)
                    return await self.async_step_local_device_added()

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
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
                vol.Optional(CONF_MODBUS_UNIT_ID, default=DEFAULT_MODBUS_UNIT_ID): int,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(CONF_INVERTER_MODEL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="local_modbus_device",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_local_dongle_device(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle device configuration for local mode.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect dongle settings, or device added confirmation.
        """
        errors: dict[str, str] = {}

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

                # Check for duplicate serial in already-added devices
                if self._local_devices:
                    for device in self._local_devices:
                        if device.get("serial") == self._inverter_serial:
                            errors["base"] = "duplicate_serial"
                            break

                if not errors:
                    # Add device to list
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
                    self._local_devices.append(device_config)
                    return await self.async_step_local_device_added()

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
                vol.Required(CONF_DONGLE_HOST): str,
                vol.Optional(CONF_DONGLE_PORT, default=DEFAULT_DONGLE_PORT): int,
                vol.Required(CONF_DONGLE_SERIAL): str,
                vol.Required(CONF_INVERTER_SERIAL): str,
                vol.Optional(CONF_INVERTER_MODEL, default=""): str,
                vol.Optional(
                    CONF_INVERTER_FAMILY, default=DEFAULT_INVERTER_FAMILY
                ): vol.In(INVERTER_FAMILY_OPTIONS),
            }
        )

        return self.async_show_form(
            step_id="local_dongle_device",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_local_device_added(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle confirmation after a device is added.

        Asks user if they want to add another device or finish setup.

        Args:
            user_input: Form data with add_another choice, or None.

        Returns:
            Add device step, or entry creation.
        """
        if user_input is not None:
            add_another = user_input.get("add_another", False)

            if add_another:
                return await self.async_step_local_add_device()
            # User is done - create the entry
            return await self._create_local_entry()

        # Build schema for add another choice
        add_another_schema = vol.Schema(
            {
                vol.Required("add_another", default=False): bool,
            }
        )

        # Get info about the last added device for display
        last_device = self._local_devices[-1] if self._local_devices else {}
        last_serial = last_device.get("serial", "Unknown")
        last_type = last_device.get("transport_type", "unknown")
        device_count = len(self._local_devices)

        return self.async_show_form(
            step_id="local_device_added",
            data_schema=add_another_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_serial": last_serial,
                "device_type": last_type,
                "device_count": str(device_count),
            },
        )

    async def _create_local_entry(self: ConfigFlowProtocol) -> ConfigFlowResult:
        """Create config entry for local-only (no cloud) connection.

        Returns:
            Config entry creation result.
        """
        # Validate that we have at least one device
        assert self._local_devices, "At least one local device must be configured"

        # Build unique ID from all device serials (sorted for consistency)
        serials = sorted(device.get("serial", "") for device in self._local_devices)
        unique_id = build_unique_id("local", station_name="_".join(serials))
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

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

        return self.async_create_entry(title=title, data=data)
