"""Brand configuration constants for the EG4 Web Monitor integration.

This module contains all brand-related constants including:
- BrandConfig dataclass for defining brand configurations
- Pre-defined brand configurations (EG4, LuxPower, Fortress)
- Current brand selection and derived constants
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandConfig:
    """Configuration for a brand.

    Attributes:
        domain: Home Assistant integration domain (e.g., "eg4_web_monitor")
        brand_name: Full brand name for display (e.g., "EG4 Electronics")
        short_name: Short brand name for entity IDs (e.g., "EG4")
        entity_prefix: Prefix for entity IDs (e.g., "eg4")
        default_base_url: Default API base URL for this brand
        default_verify_ssl: Default SSL verification setting
        manufacturer: Manufacturer name for device registry
    """

    domain: str
    brand_name: str
    short_name: str
    entity_prefix: str
    default_base_url: str
    default_verify_ssl: bool
    manufacturer: str


# Brand definitions
BRAND_EG4 = BrandConfig(
    domain="eg4_web_monitor",
    brand_name="EG4 Electronics",
    short_name="EG4",
    entity_prefix="eg4",
    default_base_url="https://monitor.eg4electronics.com",
    default_verify_ssl=True,
    manufacturer="EG4 Electronics",
)

BRAND_LUXPOWER = BrandConfig(
    domain="lxp_web_monitor",
    brand_name="LuxpowerTek",
    short_name="LXP",
    entity_prefix="lxp",
    default_base_url="https://eu.luxpowertek.com",
    default_verify_ssl=True,
    manufacturer="LuxpowerTek",
)

BRAND_FORTRESS = BrandConfig(
    domain="fortress_web_monitor",
    brand_name="Fortress Power",
    short_name="FPR",
    entity_prefix="fpr",
    default_base_url="https://envy.fortresspower.io",
    default_verify_ssl=False,
    manufacturer="Fortress Power",
)

# Current brand configuration - change this to switch brands
CURRENT_BRAND = BRAND_EG4

# Integration constants derived from brand configuration
DOMAIN = CURRENT_BRAND.domain
DEFAULT_BASE_URL = CURRENT_BRAND.default_base_url
DEFAULT_VERIFY_SSL = CURRENT_BRAND.default_verify_ssl
BRAND_NAME = CURRENT_BRAND.brand_name
ENTITY_PREFIX = CURRENT_BRAND.entity_prefix
MANUFACTURER = CURRENT_BRAND.manufacturer

# Default update interval (seconds)
DEFAULT_UPDATE_INTERVAL = 30
