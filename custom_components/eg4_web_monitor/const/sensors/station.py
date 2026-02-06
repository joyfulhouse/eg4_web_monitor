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
    # -------------------------------------------------------------------------
    # API Monitoring Sensors — track cloud API usage for rate limit compliance.
    # Only real HTTP calls are counted, not client cache hits.
    # -------------------------------------------------------------------------
    "api_request_rate": {
        "name": "API Request Rate",
        "icon": "mdi:api",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "unit_of_measurement": "req/hr",
        "state_class": "measurement",
    },
    "api_peak_request_rate": {
        "name": "API Peak Request Rate",
        "icon": "mdi:chart-bell-curve-cumulative",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "unit_of_measurement": "req/min",
        "state_class": "measurement",
    },
    "api_requests_today": {
        "name": "API Requests Today",
        "icon": "mdi:counter",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "unit_of_measurement": "requests",
        "state_class": "total",
    },
}
