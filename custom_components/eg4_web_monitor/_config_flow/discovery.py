"""Device discovery utilities for config flow auto-detection.

This module provides functions to auto-detect device information
from Modbus TCP and WiFi dongle connections, minimizing the manual
input required during onboarding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..const import (
    DEFAULT_DONGLE_PORT,
    DEFAULT_DONGLE_TIMEOUT,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_UNIT_ID,
    DEFAULT_SERIAL_BAUDRATE,
    DEFAULT_SERIAL_PARITY,
    DEFAULT_SERIAL_STOPBITS,
    DEFAULT_SERIAL_TIMEOUT,
    INVERTER_FAMILY_EG4_HYBRID,
    INVERTER_FAMILY_EG4_OFFGRID,
    INVERTER_FAMILY_LXP,
)

_LOGGER = logging.getLogger(__name__)

# Device type codes from holding register 19
DEVICE_TYPE_CODE_GRIDBOSS = 50
DEVICE_TYPE_CODE_EG4_OFFGRID = 54  # 12000XP, 6000XP
DEVICE_TYPE_CODE_EG4_HYBRID = 2092  # 18kPV, 12kPV
DEVICE_TYPE_CODE_FLEXBOSS = 10284  # FlexBOSS21, FlexBOSS18
DEVICE_TYPE_CODE_LXP_EU = 12  # LXP-EU 12K
DEVICE_TYPE_CODE_LXP_BR = 44  # LXP-LB-BR 10K


@dataclass
class DiscoveredDevice:
    """Information discovered from a local transport connection.

    Attributes:
        serial: Device serial number (auto-detected from registers)
        model: Human-readable model name (e.g., "FlexBOSS21", "18kPV")
        family: Inverter family constant for register mapping
        device_type_code: Raw device type code from register 19
        firmware_version: Firmware version string if available
        is_gridboss: True if device is a GridBOSS/MID controller
        pv_power: Current PV power reading (for verification)
        battery_soc: Current battery SOC (for verification)
        parallel_number: Parallel group number (0=standalone, 1-n=group)
        parallel_master_slave: Role in group (0=standalone, 1=master, 2=slave)
        parallel_phase: Phase assignment in group (0=R, 1=S, 2=T)
    """

    serial: str
    model: str
    family: str
    device_type_code: int
    firmware_version: str
    is_gridboss: bool
    pv_power: float = 0.0
    battery_soc: int = 0
    parallel_number: int = 0
    parallel_master_slave: int = 0
    parallel_phase: int = 0

    @property
    def parallel_group_name(self) -> str | None:
        """Get parallel group name (e.g., 'A', 'B') or None if standalone.

        Returns:
            Group name ('A' for group 1, 'B' for group 2, etc.) or None
            if the device is standalone.
        """
        if self.parallel_number == 0:
            return None
        return chr(ord("A") + self.parallel_number - 1)

    @property
    def is_standalone(self) -> bool:
        """Check if device is standalone (not in parallel group).

        Returns:
            True if device is standalone, False if in a parallel group.
        """
        return self.parallel_number == 0 or self.parallel_master_slave == 0

    @property
    def is_master(self) -> bool:
        """Check if device is the master in a parallel group.

        Returns:
            True if device is the master (primary) inverter.
        """
        return self.parallel_master_slave == 1


def _get_model_from_device_type(device_type_code: int) -> tuple[str, str]:
    """Derive model name and family from device type code.

    Args:
        device_type_code: Value from holding register 19.

    Returns:
        Tuple of (model_name, inverter_family).
        For GridBOSS, inverter_family is "MID" (Microgrid Interconnect Device).
    """
    model_map = {
        DEVICE_TYPE_CODE_GRIDBOSS: ("GridBOSS", "MID_DEVICE"),
        DEVICE_TYPE_CODE_EG4_OFFGRID: ("12000XP", INVERTER_FAMILY_EG4_OFFGRID),
        DEVICE_TYPE_CODE_EG4_HYBRID: ("18kPV", INVERTER_FAMILY_EG4_HYBRID),
        DEVICE_TYPE_CODE_FLEXBOSS: ("FlexBOSS21", INVERTER_FAMILY_EG4_HYBRID),
        DEVICE_TYPE_CODE_LXP_EU: ("LXP-EU 12K", INVERTER_FAMILY_LXP),
        DEVICE_TYPE_CODE_LXP_BR: ("LXP-LB-BR 10K", INVERTER_FAMILY_LXP),
    }
    return model_map.get(device_type_code, ("Unknown", INVERTER_FAMILY_EG4_HYBRID))


async def _read_device_info_from_transport(
    transport: Any,
    serial: str,
) -> DiscoveredDevice:
    """Read device information from an already-connected transport.

    Extracts device type, firmware, runtime, and parallel config from registers.
    This shared helper eliminates duplication across modbus/dongle/serial discovery.

    Args:
        transport: Connected transport object with read methods.
        serial: Device serial number (either auto-detected or provided).

    Returns:
        DiscoveredDevice with all extracted information.
    """
    # Read device type code from holding register 19
    device_type_code = await transport.read_device_type()
    model, family = _get_model_from_device_type(device_type_code)
    is_gridboss = device_type_code == DEVICE_TYPE_CODE_GRIDBOSS

    # Read firmware version
    firmware_version = ""
    try:
        firmware_version = await transport.read_firmware_version()
    except Exception as err:
        _LOGGER.debug("Could not read firmware version: %s", err)

    # Read runtime data for verification (skip for GridBOSS)
    pv_power = 0.0
    battery_soc = 0
    if not is_gridboss:
        try:
            runtime = await transport.read_runtime()
            pv_power = runtime.pv_total_power or 0.0
            battery_soc = runtime.battery_soc or 0
        except Exception as err:
            _LOGGER.debug("Could not read runtime data: %s", err)

    # Read parallel group configuration from input register 113
    parallel_number = 0
    parallel_master_slave = 0
    parallel_phase = 0
    try:
        reg113_raw = await transport.read_parallel_config()
        if reg113_raw > 0:
            parallel_master_slave = reg113_raw & 0x03
            parallel_phase = (reg113_raw >> 2) & 0x03
            parallel_number = (reg113_raw >> 8) & 0xFF
            _LOGGER.debug(
                "Parallel config for %s: raw=0x%04X, role=%d, phase=%d, group=%d",
                serial,
                reg113_raw,
                parallel_master_slave,
                parallel_phase,
                parallel_number,
            )
    except Exception as err:
        _LOGGER.debug("Could not read parallel config: %s", err)

    return DiscoveredDevice(
        serial=serial,
        model=model,
        family=family,
        device_type_code=device_type_code,
        firmware_version=firmware_version or "Unknown",
        is_gridboss=is_gridboss,
        pv_power=pv_power,
        battery_soc=battery_soc,
        parallel_number=parallel_number,
        parallel_master_slave=parallel_master_slave,
        parallel_phase=parallel_phase,
    )


async def discover_modbus_device(
    host: str,
    port: int = DEFAULT_MODBUS_PORT,
    unit_id: int = DEFAULT_MODBUS_UNIT_ID,
) -> DiscoveredDevice:
    """Connect to Modbus TCP and auto-detect device information.

    Only requires the host IP address. Everything else is auto-detected:
    - Serial number (from input registers 115-119)
    - Device type/model (from holding register 19)
    - Firmware version (from holding registers 7-10)
    - Inverter family (derived from device type)

    Args:
        host: IP address of the Modbus TCP gateway.
        port: TCP port (default 502).
        unit_id: Modbus unit/slave ID (default 1).

    Returns:
        DiscoveredDevice with all auto-detected information.

    Raises:
        TimeoutError: If connection times out.
        OSError: If connection fails.
        Exception: If device discovery fails.
    """
    from pylxpweb.transports import create_modbus_transport

    transport = create_modbus_transport(
        host=host,
        port=port,
        unit_id=unit_id,
        serial="",  # Will be auto-detected
        timeout=DEFAULT_MODBUS_TIMEOUT,
    )

    try:
        await transport.connect()

        # Read serial number from input registers 115-119
        serial = await transport.read_serial_number()
        if not serial:
            raise ValueError("Failed to read serial number from device")

        device = await _read_device_info_from_transport(transport, serial)

        _LOGGER.info(
            "Discovered %s device: serial=%s, model=%s, family=%s, fw=%s, parallel=%s",
            "GridBOSS" if device.is_gridboss else "inverter",
            device.serial,
            device.model,
            device.family,
            device.firmware_version,
            f"group {device.parallel_number}"
            if device.parallel_number > 0
            else "standalone",
        )

        return device

    finally:
        await transport.disconnect()


async def discover_dongle_device(
    host: str,
    dongle_serial: str,
    inverter_serial: str,
    port: int = DEFAULT_DONGLE_PORT,
) -> DiscoveredDevice:
    """Connect to WiFi dongle and auto-detect device information.

    Requires host IP, dongle serial, AND inverter serial. The inverter serial
    is needed because the dongle protocol includes it in the authentication
    header of every packet - we cannot connect without it.

    Auto-detected from registers:
    - Device type/model (from holding register 19)
    - Firmware version (from holding registers 7-10)
    - Inverter family (derived from device type)

    Args:
        host: IP address of the WiFi dongle.
        dongle_serial: Serial number printed on the dongle (e.g., "BJ12345678").
        inverter_serial: Serial number of the inverter (e.g., "4512345678").
        port: TCP port (default 8000).

    Returns:
        DiscoveredDevice with all auto-detected information.

    Raises:
        TimeoutError: If connection times out.
        OSError: If connection fails.
        Exception: If device discovery fails.
    """
    from pylxpweb.transports import create_dongle_transport

    transport = create_dongle_transport(
        host=host,
        dongle_serial=dongle_serial,
        inverter_serial=inverter_serial,
        port=port,
        timeout=DEFAULT_DONGLE_TIMEOUT,
    )

    try:
        await transport.connect()

        # Use the provided serial (we can't auto-detect it for dongle)
        serial = inverter_serial

        device = await _read_device_info_from_transport(transport, serial)

        _LOGGER.info(
            "Discovered %s device via dongle: serial=%s, model=%s, family=%s, fw=%s, parallel=%s",
            "GridBOSS" if device.is_gridboss else "inverter",
            device.serial,
            device.model,
            device.family,
            device.firmware_version,
            f"group {device.parallel_number}"
            if device.parallel_number > 0
            else "standalone",
        )

        return device

    finally:
        await transport.disconnect()


async def discover_serial_device(
    port: str,
    baudrate: int = DEFAULT_SERIAL_BAUDRATE,
    unit_id: int = DEFAULT_MODBUS_UNIT_ID,
    parity: str = DEFAULT_SERIAL_PARITY,
    stopbits: int = DEFAULT_SERIAL_STOPBITS,
) -> DiscoveredDevice:
    """Connect to Modbus RTU over serial and auto-detect device information.

    Similar to discover_modbus_device() but uses USB/RS485 serial transport.

    Args:
        port: Serial port path (e.g., /dev/ttyUSB0, COM3).
        baudrate: Serial baudrate (default 19200 for EG4 inverters).
        unit_id: Modbus unit/slave ID (default 1).
        parity: Parity setting ('N', 'E', 'O').
        stopbits: Stop bits (1 or 2).

    Returns:
        DiscoveredDevice with all auto-detected information.

    Raises:
        TimeoutError: If connection times out.
        PermissionError: If serial port access is denied.
        OSError: If serial port cannot be opened.
        Exception: If device discovery fails.
    """
    from pylxpweb.transports import create_serial_transport

    transport = create_serial_transport(
        port=port,
        serial="",  # Will be auto-detected
        baudrate=baudrate,
        parity=parity,
        stopbits=stopbits,
        unit_id=unit_id,
        timeout=DEFAULT_SERIAL_TIMEOUT,
    )

    try:
        await transport.connect()

        # Read serial number from input registers 115-119
        serial = await transport.read_serial_number()
        if not serial:
            raise ValueError("Failed to read serial number from device")

        device = await _read_device_info_from_transport(transport, serial)

        _LOGGER.info(
            "Discovered %s device via serial: port=%s, serial=%s, model=%s, family=%s, fw=%s, parallel=%s",
            "GridBOSS" if device.is_gridboss else "inverter",
            port,
            device.serial,
            device.model,
            device.family,
            device.firmware_version,
            f"group {device.parallel_number}"
            if device.parallel_number > 0
            else "standalone",
        )

        return device

    finally:
        await transport.disconnect()


def build_device_config(
    discovered: DiscoveredDevice,
    transport_type: str,
    host: str | None = None,
    port: int | None = None,
    dongle_serial: str | None = None,
    unit_id: int | None = None,
    serial_port: str | None = None,
    serial_baudrate: int | None = None,
    serial_parity: str | None = None,
    serial_stopbits: int | None = None,
) -> dict[str, Any]:
    """Build a device configuration dict from discovered info.

    Args:
        discovered: Auto-detected device information.
        transport_type: "modbus_tcp", "wifi_dongle", or "modbus_serial".
        host: IP address of the device/gateway (TCP transports).
        port: TCP port (TCP transports).
        dongle_serial: Dongle serial (for wifi_dongle only).
        unit_id: Modbus unit ID (for modbus_tcp and modbus_serial).
        serial_port: Serial port path (for modbus_serial only).
        serial_baudrate: Serial baudrate (for modbus_serial only).
        serial_parity: Serial parity (for modbus_serial only).
        serial_stopbits: Serial stop bits (for modbus_serial only).

    Returns:
        Configuration dict ready for storage.
    """
    config: dict[str, Any] = {
        "transport_type": transport_type,
        "serial": discovered.serial,
        "model": discovered.model,
        "inverter_family": discovered.family,
        "device_type_code": discovered.device_type_code,
        "firmware_version": discovered.firmware_version,
        "is_gridboss": discovered.is_gridboss,
        # Parallel group configuration
        "parallel_number": discovered.parallel_number,
        "parallel_master_slave": discovered.parallel_master_slave,
        "parallel_phase": discovered.parallel_phase,
    }

    if transport_type == "modbus_tcp":
        config["host"] = host
        config["port"] = port
        if unit_id is not None:
            config["unit_id"] = unit_id
    elif transport_type == "wifi_dongle":
        config["host"] = host
        config["port"] = port
        if dongle_serial:
            config["dongle_serial"] = dongle_serial
    elif transport_type == "modbus_serial":
        config["serial_port"] = serial_port
        if serial_baudrate is not None:
            config["serial_baudrate"] = serial_baudrate
        if serial_parity is not None:
            config["serial_parity"] = serial_parity
        if serial_stopbits is not None:
            config["serial_stopbits"] = serial_stopbits
        if unit_id is not None:
            config["unit_id"] = unit_id

    return config
