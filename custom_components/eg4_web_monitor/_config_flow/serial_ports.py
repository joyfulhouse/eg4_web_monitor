"""Serial port detection and listing for config flow.

This module provides functions to enumerate available serial ports
for the USB/RS485 configuration dropdown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Keywords that suggest RS485/USB-serial adapters
RS485_KEYWORDS = frozenset(
    {"rs485", "ch340", "ch341", "ftdi", "prolific", "pl2303", "cp210", "usb"}
)


async def _async_scan_serial_ports(hass: HomeAssistant) -> Any:
    """Load USB discovery only when the config flow requests serial ports."""
    from homeassistant.components.usb import async_scan_serial_ports

    return await async_scan_serial_ports(hass)


@dataclass
class SerialPortInfo:
    """Information about a detected serial port."""

    device: str
    """Device path (e.g., /dev/ttyUSB0, COM3)."""

    description: str
    """Human-readable description."""

    manufacturer: str | None = None
    """Manufacturer name if available."""

    product: str | None = None
    """Product name if available."""


def _is_rs485_adapter(port: Any) -> bool:
    """Check if a port looks like an RS485 adapter based on its metadata."""
    searchable = " ".join(
        filter(None, [port.description, port.manufacturer, port.product, port.device])
    ).lower()
    return any(keyword in searchable for keyword in RS485_KEYWORDS)


def _build_port_description(port: Any) -> str:
    """Build human-readable description for a serial port."""
    desc_parts = [p for p in (port.manufacturer, port.product) if p]
    if not desc_parts:
        desc_parts = [port.description or port.device]
    return f"{port.device} ({' - '.join(desc_parts)})"


async def list_serial_ports(hass: HomeAssistant) -> list[SerialPortInfo]:
    """Detect available serial ports.

    Returns:
        List of SerialPortInfo objects for each detected port,
        sorted with likely RS485 adapters first.
    """
    try:
        raw_ports = await _async_scan_serial_ports(hass)

        # Build port info list with RS485 classification
        port_data = [
            (
                SerialPortInfo(
                    device=port.device,
                    description=_build_port_description(port),
                    manufacturer=port.manufacturer,
                    product=port.product,
                ),
                _is_rs485_adapter(port),
            )
            for port in raw_ports
        ]

        # Sort with RS485 adapters first (stable sort preserves relative order)
        port_data.sort(key=lambda x: not x[1])
        all_ports = [info for info, _ in port_data]

        rs485_count = sum(1 for _, is_rs485 in port_data if is_rs485)
        _LOGGER.debug(
            "Detected %d serial ports (%d likely RS485): %s",
            len(all_ports),
            rs485_count,
            [p.device for p in all_ports],
        )

        return all_ports

    except Exception as err:
        _LOGGER.warning("Failed to list serial ports: %s", err)
        return []


def build_port_selector_options(
    ports: list[SerialPortInfo],
) -> dict[str, str]:
    """Build selector options dict for voluptuous schema.

    Args:
        ports: List of SerialPortInfo from list_serial_ports().

    Returns:
        Dict mapping device path to human description.
        Includes "manual_entry" option for custom paths.
    """
    options = {port.device: port.description for port in ports}
    options["manual_entry"] = "Enter manually..."
    return options
