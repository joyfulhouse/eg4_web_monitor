# Config Flow Refactoring Design Document

## Overview

This document outlines the refactoring of `config_flow.py` into a modular, mixin-based architecture for better maintainability, testability, and extensibility.

## Recent Context

The config_flow.py file was recently simplified in commit 9ed44b1 (Jan 26, 2026), reducing code by ~244 lines through helper patterns. However, the file continues to grow due to:
1. Support for 5 connection types (HTTP, Modbus, Dongle, Hybrid, Local)
2. Duplicate reconfigure flows for each connection type
3. Addition of LOCAL multi-device mode (PR #90, PR #94)

This mixin-based refactoring builds upon those improvements while addressing the architectural complexity from supporting multiple connection types.

## Current State Analysis

### Line Count: ~2000+ lines (varies with pending PRs)

**Note**: The LOCAL multi-device mode (CONNECTION_TYPE_LOCAL) adds significant functionality. This design accounts for all 5 connection types.

### Current Class Structure
- `EG4WebMonitorConfigFlow` - Main config flow class
- `EG4OptionsFlow` - Options/settings flow class

### Current Methods by Category

#### 1. Shared/Base Methods
| Method | Lines | Description |
|--------|-------|-------------|
| `__init__` | 146-177 | Initialize flow instance variables |
| `async_get_options_flow` | 178-182 | Static method to get options flow |
| `async_step_user` | 184-222 | Entry point - connection type selection |
| `_timezone_observes_dst` | 91-117 | Module-level helper for DST check |
| `_build_user_data_schema` | 120-138 | Module-level helper for HTTP schema |
| `_test_credentials` | 1036-1071 | Test HTTP API credentials |
| `_test_modbus_connection` | 355-411 | Test Modbus TCP connection |
| `_test_dongle_connection` | 502-545 | Test WiFi dongle connection |

#### 2. HTTP Onboarding (Cloud API)
| Method | Lines | Description |
|--------|-------|-------------|
| `async_step_http_credentials` | 225-280 | HTTP login form |
| `async_step_plant` | 982-1034 | Station/plant selection |
| `_create_http_entry` | 1073-1108 | Create HTTP config entry |

#### 3. Modbus Onboarding
| Method | Lines | Description |
|--------|-------|-------------|
| `async_step_modbus` | 282-353 | Modbus config form |
| `_create_modbus_entry` | 413-440 | Create Modbus config entry |

#### 4. Dongle Onboarding
| Method | Lines | Description |
|--------|-------|-------------|
| `async_step_dongle` | 442-500 | Dongle config form |
| `_create_dongle_entry` | 547-573 | Create Dongle config entry |

#### 5. Hybrid Onboarding (HTTP + Local)
| Method | Lines | Description |
|--------|-------|-------------|
| `async_step_hybrid_http` | 575-626 | Hybrid HTTP credentials |
| `async_step_hybrid_plant` | 628-677 | Hybrid plant selection |
| `async_step_hybrid_local_type` | 679-722 | Choose Modbus vs Dongle |
| `async_step_hybrid_modbus` | 800-883 | Hybrid Modbus config |
| `async_step_hybrid_dongle` | 724-798 | Hybrid Dongle config |
| `_create_hybrid_entry` | 885-980 | Create Hybrid config entry |

#### 6. Local Multi-Device Onboarding (No Cloud)
| Method | Description |
|--------|-------------|
| `async_step_local_setup` | Station name configuration |
| `async_step_local_add_device` | Device type selection (Modbus/Dongle) |
| `async_step_local_modbus_device` | Configure Modbus device |
| `async_step_local_dongle_device` | Configure Dongle device |
| `async_step_local_device_added` | Loop control - add more or finish |
| `_create_local_entry` | Create Local config entry |

#### 7. Reauth
| Method | Description |
|--------|-------------|
| `async_step_reauth` | Reauth entry point |
| `async_step_reauth_confirm` | Reauth confirmation form |

#### 8. HTTP Reconfigure
| Method | Description |
|--------|-------------|
| `async_step_reconfigure` | Reconfigure router (routes by connection type) |
| `async_step_reconfigure_http` | HTTP reconfigure form |
| `async_step_reconfigure_plant` | Plant selection during reconfig |
| `_update_http_entry` | Update HTTP entry |

#### 9. Modbus Reconfigure
| Method | Description |
|--------|-------------|
| `async_step_reconfigure_modbus` | Modbus reconfigure form |
| `_update_modbus_entry` | Update Modbus entry |

#### 10. Hybrid Reconfigure
| Method | Description |
|--------|-------------|
| `async_step_reconfigure_hybrid` | Hybrid reconfigure form |
| `async_step_reconfigure_hybrid_plant` | Hybrid plant selection |
| `_update_hybrid_entry_from_reconfigure` | Update Hybrid entry |

#### 11. Local Reconfigure
| Method | Description |
|--------|-------------|
| `async_step_reconfigure_local` | Local station name reconfigure |

#### 12. Options Flow
| Method | Description |
|--------|-------------|
| `EG4OptionsFlow.__init__` | Initialize options flow |
| `async_step_init` | Options main form (routes by type) |
| `async_step_local_options` | Local mode device management menu |
| `async_step_local_add_device_type` | Select device type to add |
| `async_step_local_options_modbus` | Add Modbus device in options |
| `async_step_local_options_dongle` | Add Dongle device in options |
| `async_step_local_remove_device` | Remove device selection |
| `async_step_local_intervals` | Local polling interval config |
| `_finish_local_options` | Apply local options changes |

## Target Architecture

### Directory Structure

```
custom_components/eg4_web_monitor/
├── config_flow.py              # Backward compat re-export
└── config_flow/
    ├── __init__.py             # Assembles & exports classes
    ├── base.py                 # Base class + shared logic
    ├── schemas.py              # Schema builders
    ├── helpers.py              # Utility functions
    ├── options.py              # EG4OptionsFlow
    ├── onboarding/
    │   ├── __init__.py
    │   ├── http.py             # HttpOnboardingMixin
    │   ├── modbus.py           # ModbusOnboardingMixin
    │   ├── dongle.py           # DongleOnboardingMixin
    │   ├── hybrid.py           # HybridOnboardingMixin
    │   └── local.py            # LocalOnboardingMixin
    ├── reconfigure/
    │   ├── __init__.py
    │   ├── reauth.py           # ReauthMixin
    │   ├── http.py             # HttpReconfigureMixin
    │   ├── modbus.py           # ModbusReconfigureMixin
    │   ├── hybrid.py           # HybridReconfigureMixin
    │   └── local.py            # LocalReconfigureMixin
    └── transitions/
        ├── __init__.py
        ├── base.py             # TransitionBuilder base
        ├── http_to_hybrid.py   # HTTP → Hybrid
        └── hybrid_to_http.py   # Hybrid → HTTP
```

### Mixin Inheritance Order (MRO)

```python
# Note: domain=DOMAIN must be on the final class, not the base.
# Home Assistant's ConfigFlow uses a metaclass that reads domain from
# the class definition, so we must specify it on the final assembled class.

class EG4WebMonitorConfigFlow(
    # Onboarding mixins (setup flows)
    HttpOnboardingMixin,
    ModbusOnboardingMixin,
    DongleOnboardingMixin,
    HybridOnboardingMixin,
    LocalOnboardingMixin,
    # Reconfigure mixins
    ReauthMixin,
    HttpReconfigureMixin,
    ModbusReconfigureMixin,
    HybridReconfigureMixin,
    LocalReconfigureMixin,
    # Transitions (HTTP↔Hybrid)
    TransitionMixin,
    # Base class with shared state/methods
    EG4ConfigFlowBase,
    # ConfigFlow must be last - domain registration happens here
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle a config flow for EG4 Web Monitor."""
    VERSION = 1
```

### Module Contents

#### 1. `base.py` - Base Class
```python
class EG4ConfigFlowBase:
    """Base config flow mixin with shared state and utilities.

    Note: This is NOT a ConfigFlow subclass. The domain=DOMAIN parameter
    must be on the final assembled class (EG4WebMonitorConfigFlow), not here.
    This class provides shared state and methods that mixins can use.
    """

    # Instance variables (moved from __init__)
    _connection_type: str | None
    _username: str | None
    _password: str | None
    # ... etc

    def __init__(self) -> None:
        """Initialize shared state for config flow."""
        super().__init__()
        self._connection_type = None
        self._username = None
        self._password = None
        # ... etc

    # Shared methods
    async def _test_credentials(self) -> None: ...
    async def _test_modbus_connection(self) -> str: ...
    async def _test_dongle_connection(self) -> None: ...

    # Entry point
    async def async_step_user(self, ...) -> ConfigFlowResult: ...

    # Routing
    async def async_step_reconfigure(self, ...) -> ConfigFlowResult: ...

    @staticmethod
    def async_get_options_flow(...) -> OptionsFlow: ...
```

#### 2. `schemas.py` - Schema Builders
```python
def build_http_credentials_schema(dst_sync_default: bool = True) -> vol.Schema: ...
def build_modbus_schema(defaults: dict | None = None) -> vol.Schema: ...
def build_dongle_schema(defaults: dict | None = None) -> vol.Schema: ...
def build_hybrid_modbus_schema(serial: str = "", ...) -> vol.Schema: ...
def build_hybrid_dongle_schema(serial: str = "", ...) -> vol.Schema: ...
def build_plant_selection_schema(plants: list, current: str | None = None) -> vol.Schema: ...
def build_interval_options_schema(current_sensor: int, current_param: int) -> vol.Schema: ...

INVERTER_FAMILY_OPTIONS = {
    INVERTER_FAMILY_PV_SERIES: "EG4 18kPV / FlexBOSS (PV Series)",
    INVERTER_FAMILY_SNA: "EG4 12000XP / 6000XP (SNA Series)",
    INVERTER_FAMILY_LXP_EU: "LXP-EU 12K (European)",
}
```

#### 3. `helpers.py` - Utility Functions
```python
def timezone_observes_dst(timezone_name: str | None) -> bool: ...
def get_ha_timezone(hass: HomeAssistant) -> str | None: ...
def format_entry_title(brand: str, mode: str, name: str) -> str: ...
def build_unique_id(mode: str, username: str | None, plant_id: str | None, serial: str | None) -> str: ...
```

### Protocol/ABC for Type Safety

```python
from typing import Protocol

class ConfigFlowProtocol(Protocol):
    """Protocol defining the interface mixins expect from base class."""

    hass: HomeAssistant
    context: dict[str, Any]

    # State
    _connection_type: str | None
    _username: str | None
    _password: str | None
    _base_url: str | None
    _verify_ssl: bool | None
    _dst_sync: bool | None
    _library_debug: bool | None
    _plant_id: str | None
    _plants: list[dict[str, Any]] | None
    _modbus_host: str | None
    _modbus_port: int | None
    _modbus_unit_id: int | None
    _inverter_serial: str | None
    _inverter_model: str | None
    _inverter_family: str | None
    _dongle_host: str | None
    _dongle_port: int | None
    _dongle_serial: str | None
    _hybrid_local_type: str | None

    # Required methods
    async def _test_credentials(self) -> None: ...
    async def _test_modbus_connection(self) -> str: ...
    async def _test_dongle_connection(self) -> None: ...
    def async_show_form(self, **kwargs) -> ConfigFlowResult: ...
    def async_create_entry(self, **kwargs) -> ConfigFlowResult: ...
    def async_abort(self, **kwargs) -> ConfigFlowResult: ...
    async def async_set_unique_id(self, unique_id: str) -> ConfigEntry | None: ...
```

## Backward Compatibility Strategy

### 1. Keep `config_flow.py` as re-export module
```python
# custom_components/eg4_web_monitor/config_flow.py
"""Config flow for EG4 Web Monitor integration.

This module re-exports from the config_flow package for backward compatibility.
"""
from .config_flow import EG4OptionsFlow, EG4WebMonitorConfigFlow

__all__ = ["EG4WebMonitorConfigFlow", "EG4OptionsFlow"]
```

### 2. Ensure domain registration works
The `domain=DOMAIN` parameter must be on the final assembled class, not the base.

### 3. Maintain all existing unique_id formats
- HTTP: `{username}_{plant_id}`
- Hybrid: `hybrid_{username}_{plant_id}`
- Modbus: `modbus_{serial}`
- Dongle: `dongle_{serial}`
- Local: `local_{station_name}` (normalized, lowercase, underscores)

## Testing Strategy

### 1. Unit Tests per Mixin
- `test_http_onboarding.py`
- `test_modbus_onboarding.py`
- `test_dongle_onboarding.py`
- `test_hybrid_onboarding.py`
- `test_local_onboarding.py`
- `test_reauth.py`
- `test_http_reconfigure.py`
- `test_modbus_reconfigure.py`
- `test_hybrid_reconfigure.py`
- `test_local_reconfigure.py`
- `test_options.py`
- `test_transitions.py`

### 2. Integration Tests
- Full flow tests using assembled class
- Backward compatibility tests
- Import path tests

### 3. Coverage Target
- Maintain >95% coverage
- Each mixin file should have corresponding test file

## Implementation Order

1. **Create directory structure** and `__init__.py` files
2. **Extract `helpers.py`** - standalone utilities
3. **Extract `schemas.py`** - schema builders
4. **Create `base.py`** - base class with shared state/methods
5. **Extract onboarding mixins** (parallel-safe):
   - `http.py`
   - `modbus.py`
   - `dongle.py`
   - `hybrid.py`
   - `local.py`
6. **Extract reconfigure mixins** (parallel-safe):
   - `reauth.py`
   - `http.py`
   - `modbus.py`
   - `hybrid.py`
   - `local.py`
7. **Create transitions module** (new feature):
   - `base.py`
   - `http_to_hybrid.py`
   - `hybrid_to_http.py`
8. **Extract `options.py`** - OptionsFlow class
9. **Assemble in `__init__.py`**
10. **Update root `config_flow.py`** for backward compat
11. **Update tests**
12. **Validate with full test suite**

## Risk Mitigation

### 1. Method Resolution Order (MRO)
- Mixins don't define `__init__` (use base class)
- No conflicting method names between mixins
- Base class is always last in inheritance list

### 2. Type Checking
- Use Protocol for mixin type hints
- Run mypy strict on all new files
- Verify no regression in existing type coverage

### 3. Runtime Compatibility
- Test with multiple HA versions (2024.1+)
- Verify ConfigFlowResult import handling
- Test both fresh install and upgrade paths

## Success Criteria

1. All existing tests pass without modification
2. New tests achieve >95% coverage
3. mypy strict passes on all files
4. ruff check passes with zero errors
5. Integration loads correctly in HA
6. All config flows function identically to before
7. Transitions feature works correctly
