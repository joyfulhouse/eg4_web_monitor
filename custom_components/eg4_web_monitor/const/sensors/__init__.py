"""Sensor definitions for the EG4 Web Monitor integration.

This subpackage contains sensor type definitions and configurations for
all entity types in the integration.

Submodules (to be populated during refactoring):
- types: SensorConfig TypedDict definition
- inverter: Main SENSOR_TYPES dictionary
- mappings: Field mappings and sensor lists
- gridboss: GridBOSS sensor definitions
- station: Station/plant sensor definitions
"""

from __future__ import annotations

# Type definitions - extracted to types.py
from .types import SensorConfig

# Inverter sensor definitions - extracted to inverter.py
from .inverter import SENSOR_TYPES

__all__ = [
    "SensorConfig",
    "SENSOR_TYPES",
]
