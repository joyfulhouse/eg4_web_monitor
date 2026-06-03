# Grid Type Fix Implementation Plan (Issue #159)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix voltage sensor visibility for LXP-family inverters on single-phase and split-phase grids, add phase-aware common voltage sensors, and remove incorrect grid type mismatch detection.

**Architecture:** Two-repo fix: pylxpweb (feature detection + register filter) and eg4_web_monitor (common voltage sensors, mismatch removal). Config-stored grid_type is authoritative for sensor filtering.

**Tech Stack:** Python 3.13, pylxpweb (Modbus library), Home Assistant custom component, pytest

---

### Task 1: pylxpweb — Fix LXP-LB Feature Detection

**Files:**
- Modify: `pylxpweb/src/pylxpweb/devices/inverters/_features.py:523-530`
- Test: `pylxpweb/tests/` (new test for dtc=44)

**Step 1: Write the failing test**

Create or add to the appropriate test file:

```python
def test_from_device_type_code_lxp_lb_split_phase():
    """LXP-LB (device_type_code=44) should default to split-phase, not three-phase."""
    features = InverterFeatures.from_device_type_code(44)
    assert features.model_family == InverterFamily.LXP
    assert features.grid_type == GridType.SPLIT_PHASE
    assert features.split_phase is True
    assert features.three_phase_capable is False

def test_from_device_type_code_lxp_eu_three_phase():
    """LXP-EU (device_type_code=12) should remain three-phase."""
    features = InverterFeatures.from_device_type_code(12)
    assert features.model_family == InverterFamily.LXP
    assert features.three_phase_capable is True
    assert features.split_phase is False
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb && uv run pytest tests/ -k "test_from_device_type_code_lxp_lb" -v`
Expected: FAIL — `assert features.split_phase is True` fails (currently False from LXP defaults)

**Step 3: Implement the fix**

In `_features.py`, method `InverterFeatures.from_device_type_code()`, replace lines 527-528:

```python
        # OLD:
        elif family == InverterFamily.LXP:
            features.grid_type = GridType.SINGLE_PHASE  # Can also be three-phase

        # NEW:
        elif family == InverterFamily.LXP:
            if device_type_code == DEVICE_TYPE_CODE_LXP_LB:  # 44 - Americas
                features.grid_type = GridType.SPLIT_PHASE
                features.split_phase = True
                features.three_phase_capable = False
            else:
                features.grid_type = GridType.SINGLE_PHASE
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb && uv run pytest tests/ -k "test_from_device_type_code_lxp" -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git add src/pylxpweb/devices/inverters/_features.py tests/
git commit -m "fix: LXP-LB (dtc=44) defaults to split-phase, not three-phase"
```

---

### Task 2: pylxpweb — Widen Register Model Filter

**Files:**
- Modify: `pylxpweb/src/pylxpweb/registers/inverter_input.py` (8 register definitions)

**Step 1: Change `models=EG4` to `models=ALL` for registers 127-132, 193-194**

These registers are at addresses 127, 128, 129, 130, 131, 132, 193, 194 in the `INVERTER_INPUT_REGISTERS` list. Each currently has `models=EG4`. Change each to `models=ALL`.

Register 127: `eps_l1_voltage` (eps_voltage_l1)
Register 128: `eps_l2_voltage` (eps_voltage_l2)
Register 129: `eps_l1_active_power`
Register 130: `eps_l2_active_power`
Register 131: `eps_l1_apparent_power`
Register 132: `eps_l2_apparent_power`
Register 193: `grid_l1_voltage` (grid_voltage_l1)
Register 194: `grid_l2_voltage` (grid_voltage_l2)

For each, change: `models=EG4,` → remove the `models=` line (defaults to ALL) or change to `models=ALL,`

**Step 2: Run existing tests**

Run: `cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb && uv run pytest tests/ -x --tb=short`
Expected: All pass (model filter is only used at read time, not in tests)

**Step 3: Commit**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git add src/pylxpweb/registers/inverter_input.py
git commit -m "fix: widen split-phase register filter to ALL models (regs 127-132, 193-194)"
```

---

### Task 3: eg4_web_monitor — Add Common Voltage Sensor Definitions

**Files:**
- Modify: `custom_components/eg4_web_monitor/const/sensors/inverter.py` (add 2 sensor defs)
- Modify: `custom_components/eg4_web_monitor/const/device_types.py` (add NON_THREE_PHASE_SENSORS)
- Modify: `custom_components/eg4_web_monitor/sensor.py` (update _should_create_sensor)

**Step 1: Add sensor type definitions**

In `const/sensors/inverter.py`, add after the `grid_voltage_r` definition block:

```python
    "grid_voltage": {
        "name": "Grid Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:transmission-tower",
        "suggested_display_precision": 1,
    },
```

And after the `eps_voltage_r` definition block:

```python
    "eps_voltage": {
        "name": "EPS Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:power-plug",
        "suggested_display_precision": 1,
    },
```

**Step 2: Add NON_THREE_PHASE_SENSORS frozenset**

In `const/device_types.py`, after `THREE_PHASE_ONLY_SENSORS`, add:

```python
# Common voltage sensors for single-phase and split-phase configurations.
# These alias register 12 (grid_voltage_r) and register 20 (eps_voltage_r)
# with phase-neutral names. Not created for three-phase (R/S/T sensors used instead).
NON_THREE_PHASE_SENSORS: frozenset[str] = frozenset(
    {
        "grid_voltage",
        "eps_voltage",
    }
)
```

**Step 3: Export the new constant**

Add `NON_THREE_PHASE_SENSORS` to `const/__init__.py` imports and `__all__`.

**Step 4: Update `_should_create_sensor()` in `sensor.py`**

Add import of `NON_THREE_PHASE_SENSORS` and add the check:

```python
from .const import (
    DISCHARGE_RECOVERY_SENSORS,
    NON_THREE_PHASE_SENSORS,
    SENSOR_TYPES,
    SPLIT_PHASE_ONLY_SENSORS,
    STATION_SENSOR_TYPES,
    THREE_PHASE_ONLY_SENSORS,
    VOLT_WATT_SENSORS,
)
```

In the function, add after the three-phase check:

```python
    # Check common voltage sensors (only for single/split-phase, not three-phase)
    if sensor_key in NON_THREE_PHASE_SENSORS:
        return not bool(features.get("supports_three_phase", False))
```

**Step 5: Run lint/type check**

Run: `cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor && uv run ruff check custom_components/ --fix && uv run ruff format custom_components/`

**Step 6: Commit**

```bash
git add custom_components/eg4_web_monitor/const/sensors/inverter.py custom_components/eg4_web_monitor/const/device_types.py custom_components/eg4_web_monitor/const/__init__.py custom_components/eg4_web_monitor/sensor.py
git commit -m "feat: add grid_voltage/eps_voltage common sensors for single/split-phase"
```

---

### Task 4: eg4_web_monitor — Add Coordinator Voltage Aliasing

**Files:**
- Modify: `custom_components/eg4_web_monitor/coordinator_mappings.py` (add helper + update key set)
- Modify: `custom_components/eg4_web_monitor/coordinator_local.py` (call alias helper)
- Modify: `custom_components/eg4_web_monitor/coordinator_mixins.py` (call alias helper in HTTP path)

**Step 1: Add alias helper and update INVERTER_RUNTIME_KEYS**

In `coordinator_mappings.py`, add `"grid_voltage"` and `"eps_voltage"` to `INVERTER_RUNTIME_KEYS` frozenset (they flow through ALL_INVERTER_SENSOR_KEYS for static entity creation).

Add a module-level helper function:

```python
def alias_common_voltage_sensors(
    sensors: dict[str, Any], features: dict[str, Any]
) -> None:
    """Alias R-phase voltage readings to phase-neutral names for non-three-phase.

    For single-phase and split-phase configurations, copies grid_voltage_r
    and eps_voltage_r to grid_voltage and eps_voltage respectively. Three-phase
    configurations use the R/S/T naming convention and skip this aliasing.

    Args:
        sensors: Mutable sensor dict to update.
        features: Feature flags dict (must contain "supports_three_phase").
    """
    if features.get("supports_three_phase", False):
        return
    if (v := sensors.get("grid_voltage_r")) is not None:
        sensors["grid_voltage"] = v
    if (v := sensors.get("eps_voltage_r")) is not None:
        sensors["eps_voltage"] = v
```

**Step 2: Call from LOCAL path**

In `coordinator_local.py`, in `_build_local_device_data()` around line 308-315, after `device_data["features"] = features`, add:

```python
        if features:
            device_data["features"] = features
            alias_common_voltage_sensors(device_data["sensors"], features)
```

Import `alias_common_voltage_sensors` from `coordinator_mappings`.

**Step 3: Call from HTTP/Cloud path**

In `coordinator_mixins.py`, in `_process_inverter_object()` around line 495, after sensors are mapped and grid_type override is applied, add:

```python
        # Alias R-phase voltages to common names for non-three-phase configs
        alias_common_voltage_sensors(processed["sensors"], features)
```

Import `alias_common_voltage_sensors` from `coordinator_mappings`.

**Step 4: Run lint/type check**

Run: `cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor && uv run ruff check custom_components/ --fix && uv run ruff format custom_components/`

**Step 5: Commit**

```bash
git add custom_components/eg4_web_monitor/coordinator_mappings.py custom_components/eg4_web_monitor/coordinator_local.py custom_components/eg4_web_monitor/coordinator_mixins.py
git commit -m "feat: alias grid_voltage_r/eps_voltage_r to common names for non-three-phase"
```

---

### Task 5: eg4_web_monitor — Remove Grid Type Mismatch Detection

**Files:**
- Modify: `custom_components/eg4_web_monitor/coordinator_local.py` (remove methods + call sites)
- Modify: `custom_components/eg4_web_monitor/coordinator_mixins.py` (remove `_grid_type_mismatch_notified` type hint)
- Modify: `custom_components/eg4_web_monitor/coordinator.py` (remove `_grid_type_mismatch_notified` init)
- Modify: `custom_components/eg4_web_monitor/strings.json` (remove issues keys)
- Modify: 13 `custom_components/eg4_web_monitor/translations/*.json` files

**Step 1: Remove methods from coordinator_local.py**

Delete `_check_grid_type_mismatch()` (lines 142-207) and `_check_missing_grid_type()` (lines 209-238).

**Step 2: Remove call sites in coordinator_local.py**

In `_process_single_local_device()` around lines 815-820, remove:
```python
                if features and serial not in self._grid_type_mismatch_notified:
                    if config.get("grid_type") is None:
                        self._check_missing_grid_type(serial, model, features)
                    else:
                        self._check_grid_type_mismatch(serial, model, config, features)
```

In `_deferred_local_parameter_load()` around lines 1025-1051, remove:
```python
            config_by_serial: dict[str, dict[str, Any]] = {
                c.get("serial", ""): c for c in self._local_transport_configs
            }
```
And the grid_type mismatch check block inside the for loop (lines 1038-1051):
```python
                        if serial not in self._grid_type_mismatch_notified:
                            features = self._extract_inverter_features(inverter)
                            config = config_by_serial.get(serial, {})
                            model = config.get("model", "")
                            if features:
                                if config.get("grid_type") is None:
                                    self._check_missing_grid_type(...)
                                else:
                                    self._check_grid_type_mismatch(...)
```

Remove unused `import homeassistant.helpers.issue_registry as ir` if no other uses remain.

**Step 3: Remove `_grid_type_mismatch_notified` from coordinator**

In `coordinator.py` line 276, remove: `self._grid_type_mismatch_notified: set[str] = set()`

In `coordinator_mixins.py` line 207, remove: `_grid_type_mismatch_notified: set[str]`

**Step 4: Remove translation keys**

In `strings.json`, remove the `grid_type_mismatch` and `grid_type_missing` entries from the `"issues"` section (keep `dongle_validation_disabled` if it exists).

In all 13 `translations/*.json` files, remove the same two keys from `"issues"`.

**Step 5: Run lint + tests**

Run: `cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor && uv run ruff check custom_components/ --fix && uv run ruff format custom_components/`

**Step 6: Commit**

```bash
git add custom_components/
git commit -m "fix: remove grid type mismatch detection (config is authoritative)"
```

---

### Task 6: Tests — Remove Mismatch Tests + Add Voltage Sensor Tests

**Files:**
- Modify: `tests/test_coordinator.py` (remove TestGridTypeMismatch, TestMissingGridType; add voltage tests)

**Step 1: Remove test classes**

Delete `TestGridTypeMismatch` (lines 3875-4041) and `TestMissingGridType` (lines 4042-4150) from `test_coordinator.py`. Also remove any fixtures only used by those classes (e.g., `lxp_no_grid_config_entry` if unused elsewhere).

**Step 2: Add common voltage sensor tests**

```python
class TestCommonVoltageSensors:
    """Test grid_voltage/eps_voltage aliasing for non-three-phase configs."""

    def test_alias_fires_for_split_phase(self):
        """Split-phase config gets grid_voltage aliased from grid_voltage_r."""
        sensors = {"grid_voltage_r": 240.1, "eps_voltage_r": 120.5}
        features = {"supports_three_phase": False}
        alias_common_voltage_sensors(sensors, features)
        assert sensors["grid_voltage"] == 240.1
        assert sensors["eps_voltage"] == 120.5

    def test_alias_fires_for_single_phase(self):
        """Single-phase config gets grid_voltage aliased from grid_voltage_r."""
        sensors = {"grid_voltage_r": 230.0, "eps_voltage_r": 230.0}
        features = {"supports_three_phase": False}
        alias_common_voltage_sensors(sensors, features)
        assert sensors["grid_voltage"] == 230.0
        assert sensors["eps_voltage"] == 230.0

    def test_alias_skipped_for_three_phase(self):
        """Three-phase config does NOT get grid_voltage alias."""
        sensors = {"grid_voltage_r": 230.0, "eps_voltage_r": 230.0}
        features = {"supports_three_phase": True}
        alias_common_voltage_sensors(sensors, features)
        assert "grid_voltage" not in sensors
        assert "eps_voltage" not in sensors

    def test_alias_handles_missing_values(self):
        """Missing R-phase values don't create None aliases."""
        sensors = {}
        features = {"supports_three_phase": False}
        alias_common_voltage_sensors(sensors, features)
        assert "grid_voltage" not in sensors
        assert "eps_voltage" not in sensors
```

**Step 3: Add sensor filtering test**

```python
    def test_should_create_grid_voltage_for_single_phase(self):
        """grid_voltage should be created for single-phase."""
        features = {"supports_three_phase": False, "supports_split_phase": False}
        assert _should_create_sensor("grid_voltage", features) is True

    def test_should_not_create_grid_voltage_for_three_phase(self):
        """grid_voltage should NOT be created for three-phase."""
        features = {"supports_three_phase": True, "supports_split_phase": False}
        assert _should_create_sensor("grid_voltage", features) is False

    def test_should_create_grid_voltage_for_split_phase(self):
        """grid_voltage should be created for split-phase."""
        features = {"supports_three_phase": False, "supports_split_phase": True}
        assert _should_create_sensor("grid_voltage", features) is True
```

**Step 4: Run all tests**

Run: `cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor && uv run pytest tests/ -x --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add tests/
git commit -m "test: add common voltage sensor tests, remove grid type mismatch tests"
```

---

### Task 7: Translations — Add Common Voltage Sensor Names

**Files:**
- Modify: `custom_components/eg4_web_monitor/strings.json`
- Modify: 13 `custom_components/eg4_web_monitor/translations/*.json`

**Step 1: Add sensor name translations**

If sensor names use the translation system (check existing patterns), add `grid_voltage` and `eps_voltage` entries to `strings.json` and all 13 locale files.

If sensor names come directly from the SENSOR_TYPES dict (the `"name"` key), this task is already done by Task 3.

**Step 2: Run full validation**

```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
```

**Step 3: Commit**

```bash
git add custom_components/
git commit -m "i18n: add grid_voltage/eps_voltage sensor translations"
```

---

### Task 8: Final Validation

**Step 1: Run full test suite**

```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor
uv run pytest tests/ -x --tb=short -q
```

**Step 2: Run pylxpweb tests**

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/ -x --tb=short -q
```

**Step 3: Run type checking**

```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
```

**Step 4: Verify key drift prevention**

Run the existing key consistency tests to ensure ALL_INVERTER_SENSOR_KEYS still matches:

```bash
uv run pytest tests/test_coordinator.py::TestMappingKeyConsistency -v
```

**Step 5: Commit any final fixes and push**
