"""Sensor type definitions for the EG4 Web Monitor integration.

This module contains TypedDict definitions for sensor configurations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from homeassistant.const import EntityCategory


class SensorConfig(TypedDict, total=False):
    """TypedDict for sensor configuration.

    Attributes:
        name: Display name for the sensor
        unit: Unit of measurement (e.g., UnitOfPower.WATT)
        device_class: Home Assistant device class (power, energy, voltage, etc.)
        state_class: Home Assistant state class (measurement, total, total_increasing)
        icon: MDI icon string (e.g., "mdi:solar-power")
        entity_category: Entity category (diagnostic, config, etc.)
        suggested_display_precision: Number of decimal places to display
    """

    name: str
    unit: str | None
    device_class: str | None
    state_class: str | None
    icon: str
    entity_category: EntityCategory | None
    suggested_display_precision: int
