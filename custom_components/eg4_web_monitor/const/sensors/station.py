"""Station sensor type definitions for the EG4 Web Monitor integration.

This module contains sensor configurations for station/plant-level entities.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory

# Station sensor types - read-only display sensors
STATION_SENSOR_TYPES = {
    "station_name": {
        "name": "Station Name",
        "icon": "mdi:home-lightning-bolt-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_country": {
        "name": "Country",
        "icon": "mdi:map-marker",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_timezone": {
        "name": "Timezone",
        "icon": "mdi:clock-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_create_date": {
        "name": "Created",
        "icon": "mdi:calendar",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "station_address": {
        "name": "Address",
        "icon": "mdi:map-marker-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    # -------------------------------------------------------------------------
    # Last Polled Diagnostic Sensor
    # Shows when station data was last fetched, not when it last changed.
    # Helps users understand if the integration is actively polling.
    # -------------------------------------------------------------------------
    "station_last_polled": {
        "name": "Last Polled",
        "device_class": "timestamp",
        "icon": "mdi:clock-check",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
}
