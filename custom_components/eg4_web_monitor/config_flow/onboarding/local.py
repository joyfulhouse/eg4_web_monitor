"""Unified local-only onboarding mixin for EG4 Web Monitor config flow.

This module provides a streamlined LOCAL connection type which allows users to
configure local devices (Modbus and/or WiFi Dongle) with minimal input.
All device details (serial, model, family) are auto-detected.

This unified flow replaces the separate Modbus/Dongle/LOCAL flows, providing:
- Minimal user input (Host only for Modbus; Host + Dongle serial for Dongle)
- Full auto-detection of device information
- Support for 1 to N devices in the same flow
- Clear explanation of what an "installation name" means
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from ...const import (
    BRAND_NAME,
    CONF_CONNECTION_TYPE,
    CONF_LOCAL_TRANSPORTS,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_DONGLE_PORT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_UNIT_ID,
)
from ..helpers import build_unique_id, format_entry_title
from ..schemas import LOCAL_DEVICE_TYPE_OPTIONS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

    from ..base import ConfigFlowProtocol
    from ..discovery import DiscoveredDevice

_LOGGER = logging.getLogger(__name__)


class LocalOnboardingMixin:
    """Mixin providing unified local onboarding flow with auto-detection.

    This mixin handles the streamlined setup for local connections:

    Flow:
    1. Transport type selection (Modbus TCP or WiFi Dongle)
    2. Minimal connection input:
       - Modbus: Host IP only (port and unit_id have sensible defaults)
       - Dongle: Host IP + Dongle Serial (required for auth)
    3. Auto-discovery shows detected device info (serial, model, family, firmware)
    4. "Add another device?" loop
    5. Name your installation (with clear explanation)
    6. Create config entry

    The LOCAL mode supports 1 to N devices. If only one device is configured,
    it works identically to the old single-device Modbus/Dongle modes but with
    much less manual input.

    Requires:
        - ConfigFlowProtocol attributes
        - _discover_modbus_device() and _discover_dongle_device() from EG4ConfigFlowBase
        - _local_devices list to accumulate device configs
    """

    # Type hints for mixin - these come from ConfigFlowProtocol
    if TYPE_CHECKING:
        # Local devices accumulator (None until initialized)
        _local_devices: list[dict[str, Any]] | None
        # Station name for display
        _local_station_name: str | None
        # Temporary storage during device add flow
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
        """Handle the initial local setup step - device type selection.

        This is the main entry point for LOCAL onboarding. Users select
        the transport type (Modbus or Dongle) for their first device.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to select transport type, or next step.
        """
        if user_input is not None:
            # Initialize the local devices list
            self._local_devices = []
            self._local_station_name = None

            device_type = user_input.get("device_type")
            if device_type == "dongle":
                return await self.async_step_local_dongle_connect()
            # Default to modbus
            return await self.async_step_local_modbus_connect()

        # Build device type selection schema
        device_type_schema = vol.Schema(
            {
                vol.Required("device_type", default="modbus"): vol.In(
                    LOCAL_DEVICE_TYPE_OPTIONS
                ),
            }
        )

        return self.async_show_form(
            step_id="local_setup",
            data_schema=device_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
            },
        )

    async def async_step_local_modbus_connect(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Modbus connection - minimal input with auto-detection.

        Only requires the host IP address. Port and unit_id have good defaults.
        All device information is auto-detected from Modbus registers.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect host, or device discovered step on success.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get("modbus_host", "").strip()
            port = user_input.get("modbus_port", DEFAULT_MODBUS_PORT)
            unit_id = user_input.get("modbus_unit_id", DEFAULT_MODBUS_UNIT_ID)

            if not host:
                errors["modbus_host"] = "required"
            else:
                try:
                    # Auto-detect device info
                    discovered = await self._discover_modbus_device(
                        host=host,
                        port=port,
                        unit_id=unit_id,
                    )

                    # Check for duplicate serial in already-added devices
                    if self._local_devices:
                        for device in self._local_devices:
                            if device.get("serial") == discovered.serial:
                                errors["base"] = "duplicate_serial"
                                break

                    if not errors:
                        # Store pending device info for confirmation
                        self._pending_device = discovered
                        self._pending_transport_type = "modbus_tcp"
                        self._pending_host = host
                        self._pending_port = port
                        self._pending_unit_id = unit_id
                        self._pending_dongle_serial = None
                        return await self.async_step_local_device_discovered()

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

        # Build minimal Modbus schema - only host is required
        modbus_schema = vol.Schema(
            {
                vol.Required("modbus_host"): str,
                vol.Optional("modbus_port", default=DEFAULT_MODBUS_PORT): int,
                vol.Optional("modbus_unit_id", default=DEFAULT_MODBUS_UNIT_ID): int,
            }
        )

        device_count = len(self._local_devices) if self._local_devices else 0

        return self.async_show_form(
            step_id="local_modbus_connect",
            data_schema=modbus_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
            },
        )

    async def async_step_local_dongle_connect(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle WiFi Dongle connection.

        Requires host IP, dongle serial, AND inverter serial. The inverter serial
        is required because the dongle protocol uses it for authentication in
        every packet header - we cannot connect without it.

        Model/family/firmware are still auto-detected from registers.

        Args:
            user_input: Form data from user, or None for initial display.

        Returns:
            Form to collect connection info, or device discovered step.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get("dongle_host", "").strip()
            port = user_input.get("dongle_port", DEFAULT_DONGLE_PORT)
            dongle_serial = user_input.get("dongle_serial", "").strip()
            inverter_serial = user_input.get("inverter_serial", "").strip()

            if not host:
                errors["dongle_host"] = "required"
            elif not dongle_serial:
                errors["dongle_serial"] = "required"
            elif not inverter_serial:
                errors["inverter_serial"] = "required"
            else:
                try:
                    # Auto-detect device info (model, family, firmware)
                    discovered = await self._discover_dongle_device(
                        host=host,
                        dongle_serial=dongle_serial,
                        inverter_serial=inverter_serial,
                        port=port,
                    )

                    # Check for duplicate serial in already-added devices
                    if self._local_devices:
                        for device in self._local_devices:
                            if device.get("serial") == discovered.serial:
                                errors["base"] = "duplicate_serial"
                                break

                    if not errors:
                        # Store pending device info for confirmation
                        self._pending_device = discovered
                        self._pending_transport_type = "wifi_dongle"
                        self._pending_host = host
                        self._pending_port = port
                        self._pending_unit_id = None
                        self._pending_dongle_serial = dongle_serial
                        return await self.async_step_local_device_discovered()

                except TimeoutError:
                    errors["base"] = "dongle_timeout"
                except OSError as e:
                    _LOGGER.error("Dongle connection error: %s", e)
                    errors["base"] = "dongle_connection_failed"
                except Exception as e:
                    _LOGGER.exception("Unexpected dongle error: %s", e)
                    errors["base"] = "unknown"

        # Dongle requires: host, dongle_serial, and inverter_serial
        # (inverter_serial is needed for authentication protocol)
        dongle_schema = vol.Schema(
            {
                vol.Required("dongle_host"): str,
                vol.Required("dongle_serial"): str,
                vol.Required("inverter_serial"): str,
                vol.Optional("dongle_port", default=DEFAULT_DONGLE_PORT): int,
            }
        )

        device_count = len(self._local_devices) if self._local_devices else 0

        return self.async_show_form(
            step_id="local_dongle_connect",
            data_schema=dongle_schema,
            errors=errors,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
            },
        )

    async def async_step_local_device_discovered(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered device info and ask to add another or finish.

        Args:
            user_input: Form data with add_another choice, or None.

        Returns:
            Form showing discovered device, or next step.
        """
        if user_input is not None:
            # Add the pending device to the list
            assert self._pending_device is not None
            assert self._pending_transport_type is not None
            assert self._pending_host is not None
            assert self._pending_port is not None

            device_config: dict[str, Any] = {
                "serial": self._pending_device.serial,
                "transport_type": self._pending_transport_type,
                "host": self._pending_host,
                "port": self._pending_port,
                "model": self._pending_device.model,
                "inverter_family": self._pending_device.family,
                "is_gridboss": self._pending_device.is_gridboss,
                # Parallel group configuration (from register 113)
                "parallel_number": self._pending_device.parallel_number,
                "parallel_master_slave": self._pending_device.parallel_master_slave,
                "parallel_phase": self._pending_device.parallel_phase,
            }

            if self._pending_transport_type == "modbus_tcp":
                device_config["unit_id"] = (
                    self._pending_unit_id or DEFAULT_MODBUS_UNIT_ID
                )
            elif self._pending_transport_type == "wifi_dongle":
                device_config["dongle_serial"] = self._pending_dongle_serial

            # _local_devices is initialized in async_step_local_setup
            assert self._local_devices is not None
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

            add_another = user_input.get("add_another", False)
            if add_another:
                return await self.async_step_local_add_device()

            # User is done adding devices - go to naming step
            return await self.async_step_local_name()

        # Build schema for add another choice
        add_another_schema = vol.Schema(
            {
                vol.Required("add_another", default=False): bool,
            }
        )

        # Get info about the discovered device for display
        assert self._pending_device is not None
        assert self._local_devices is not None
        device_type = "GridBOSS" if self._pending_device.is_gridboss else "Inverter"
        device_count = len(self._local_devices) + 1  # Include pending device

        return self.async_show_form(
            step_id="local_device_discovered",
            data_schema=add_another_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_type": device_type,
                "device_serial": self._pending_device.serial,
                "device_model": self._pending_device.model,
                "device_family": self._pending_device.family,
                "device_firmware": self._pending_device.firmware_version,
                "device_pv_power": str(int(self._pending_device.pv_power)),
                "device_battery_soc": str(self._pending_device.battery_soc),
                "device_count": str(device_count),
            },
        )

    async def async_step_local_add_device(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding another device - select device type.

        Args:
            user_input: Form data with device type selection, or None.

        Returns:
            Form to select device type, or appropriate config step.
        """
        if user_input is not None:
            device_type = user_input.get("device_type")

            if device_type == "dongle":
                return await self.async_step_local_dongle_connect()
            return await self.async_step_local_modbus_connect()

        # Build device type selection schema
        device_type_schema = vol.Schema(
            {
                vol.Required("device_type", default="modbus"): vol.In(
                    LOCAL_DEVICE_TYPE_OPTIONS
                ),
            }
        )

        device_count = len(self._local_devices) if self._local_devices else 0

        return self.async_show_form(
            step_id="local_add_device",
            data_schema=device_type_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
            },
        )

    async def async_step_local_name(
        self: ConfigFlowProtocol, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle naming the installation.

        This step explains what an "installation name" is and allows users
        to give their setup a friendly name.

        Args:
            user_input: Form data with optional station_name, or None.

        Returns:
            Form to collect name, or entry creation.
        """
        if user_input is not None:
            self._local_station_name = (
                user_input.get("station_name", "").strip() or None
            )
            return await self._create_local_entry()

        # Build schema for naming
        name_schema = vol.Schema(
            {
                vol.Optional("station_name", default=""): str,
            }
        )

        # Build device summary for display
        assert self._local_devices is not None
        device_count = len(self._local_devices)
        device_list = []
        for device in self._local_devices:
            model = device.get("model", "Unknown")
            serial = device.get("serial", "Unknown")
            device_list.append(f"{model} ({serial})")
        device_summary = ", ".join(device_list)

        return self.async_show_form(
            step_id="local_name",
            data_schema=name_schema,
            description_placeholders={
                "brand_name": BRAND_NAME,
                "device_count": str(device_count),
                "device_summary": device_summary,
            },
        )

    async def _create_local_entry(self: ConfigFlowProtocol) -> ConfigFlowResult:
        """Create config entry for local-only connection.

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
            # Use first device model and serial as name
            first_device = self._local_devices[0]
            first_model = first_device.get("model", "Unknown")
            first_serial = first_device.get("serial", "Unknown")
            device_count = len(self._local_devices)
            if device_count == 1:
                title = format_entry_title("local", f"{first_model} ({first_serial})")
            else:
                title = format_entry_title(
                    "local", f"{first_model} (+{device_count - 1} more)"
                )

        data: dict[str, Any] = {
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
            CONF_LOCAL_TRANSPORTS: self._local_devices,
        }

        # Store optional station name
        if self._local_station_name:
            data["station_name"] = self._local_station_name

        return self.async_create_entry(title=title, data=data)
