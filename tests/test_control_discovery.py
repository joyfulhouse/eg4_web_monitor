"""Regression tests for late control discovery and stable control identities."""

from datetime import time
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.eg4_web_monitor.switch as switch_module
from custom_components.eg4_web_monitor.const import DOMAIN
from custom_components.eg4_web_monitor.number import (
    ACChargePowerNumber,
    GridPeakShavingPowerNumber,
    QuickChargeDurationNumber,
    async_setup_entry as async_setup_number,
)
from custom_components.eg4_web_monitor.select import (
    EG4OperatingModeSelect,
    async_setup_entry as async_setup_select,
)
from custom_components.eg4_web_monitor.sensor import EG4InverterSensor
from custom_components.eg4_web_monitor.switch import (
    EG4OffGridModeSwitch,
    EG4QuickChargeSwitch,
    EG4WorkingModeSwitch,
    async_setup_entry as async_setup_switch,
)
from custom_components.eg4_web_monitor.time import (
    EG4ScheduleTimeEntity,
    async_setup_entry as async_setup_time,
)
from tests.test_number_entities import _mock_coordinator as _number_coordinator
from tests.test_select_entities import _mock_coordinator as _select_coordinator
from tests.test_switch_entities import _mock_coordinator as _switch_coordinator
from tests.test_time_entities import (
    _entity as _time_entity,
    _mock_coordinator as _time_coordinator,
)

SERIAL = "1234567890"
UNKNOWN_FEATURES = {"inverter_family": "UNKNOWN"}
HYBRID_FEATURES = {"inverter_family": "EG4_HYBRID"}


def _coordinator_for(platform: str) -> MagicMock:
    """Build a control coordinator whose model and family begin unknown."""
    if platform == "switch":
        return _switch_coordinator(
            model="Mystery Inverter", device_data={"features": UNKNOWN_FEATURES}
        )
    if platform == "number":
        coordinator = _number_coordinator(model="Mystery Inverter")
    elif platform == "select":
        coordinator = _select_coordinator(model="Mystery Inverter")
    else:
        coordinator = _time_coordinator(model="Mystery Inverter")
    coordinator.data["devices"][SERIAL]["features"] = dict(UNKNOWN_FEATURES)
    return coordinator


def _setup_for(platform: str) -> tuple[Any, type[Any]]:
    """Return the setup callable and one representative entity class."""
    return {
        "switch": (async_setup_switch, EG4OffGridModeSwitch),
        "number": (async_setup_number, ACChargePowerNumber),
        "select": (async_setup_select, EG4OperatingModeSelect),
        "time": (async_setup_time, EG4ScheduleTimeEntity),
    }[platform]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ("switch", "number", "select", "time"))
async def test_controls_converge_across_late_discovery_and_removal(hass, platform):
    """All control platforms follow unknown -> known -> absent transitions.

    Discovery must happen from a coordinator update without reloading the config
    entry. Controls that later become inapplicable stay registered but become
    unavailable; restoring the capability reuses the original registry identity.
    """
    coordinator = _coordinator_for(platform)
    setup, representative_type = _setup_for(platform)
    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    batches: list[list[Any]] = []
    entities: list[Any] = []

    def add_entities(new_entities, **_kwargs):
        batch = list(new_entities)
        batches.append(batch)
        entities.extend(batch)

    await setup(hass, entry, add_entities)

    assert not any(isinstance(entity, representative_type) for entity in entities)
    assert len(callbacks) == 1
    entry.async_on_unload.assert_called_once()

    device_data = coordinator.data["devices"][SERIAL]
    device_data["features"] = dict(HYBRID_FEATURES)
    callbacks[0]()

    representative = next(
        entity for entity in entities if isinstance(entity, representative_type)
    )
    if platform == "time":
        # Schedule availability also requires a decoded value. Keep that
        # independent condition satisfied while exercising discovery support.
        representative._optimistic_value = time(1, 0)
    assert representative.available
    unique_id = representative.unique_id
    batch_count = len(batches)

    # An unchanged high-frequency coordinator tick must be a no-op.
    callbacks[0]()
    assert len(batches) == batch_count

    # A capability downgrade prunes the control from the active set without
    # removing its registry identity or leaving an actionable stale control.
    device_data["features"] = dict(UNKNOWN_FEATURES)
    callbacks[0]()
    assert not representative.available

    # Capability recovery reuses the same entity; no duplicate is added.
    device_data["features"] = dict(HYBRID_FEATURES)
    callbacks[0]()
    assert representative.available
    assert [entity.unique_id for entity in entities].count(unique_id) == 1

    # Device removal is handled identically on every control platform.
    coordinator.data["devices"].pop(SERIAL)
    callbacks[0]()
    assert not representative.available


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ("switch", "number", "select", "time"))
async def test_controls_discover_when_initial_snapshot_has_no_devices(hass, platform):
    """Platform setup with no data still installs the late-discovery listener."""
    coordinator = _coordinator_for(platform)
    late_data = coordinator.data
    late_data["devices"][SERIAL]["features"] = dict(HYBRID_FEATURES)
    coordinator.data = None
    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    entities: list[Any] = []
    setup, representative_type = _setup_for(platform)

    await setup(hass, entry, lambda new, **_kwargs: entities.extend(new))

    assert not entities
    assert len(callbacks) == 1
    coordinator.data = late_data
    callbacks[0]()
    assert any(isinstance(entity, representative_type) for entity in entities)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ("switch", "number", "time"))
async def test_family_specific_controls_become_inapplicable_without_duplicates(
    hass, platform
):
    """A family change prunes only invalid controls and can later recover them."""
    coordinator = _coordinator_for(platform)
    coordinator.data["devices"][SERIAL]["features"] = dict(HYBRID_FEATURES)
    setup, _representative_type = _setup_for(platform)
    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    entities: list[Any] = []
    await setup(hass, entry, lambda new, **_kwargs: entities.extend(new))

    if platform == "switch":
        target = next(
            entity
            for entity in entities
            if isinstance(entity, EG4WorkingModeSwitch)
            and entity._mode_config["param"] == "FUNC_GRID_PEAK_SHAVING"
        )
        survivor = next(
            entity for entity in entities if isinstance(entity, EG4OffGridModeSwitch)
        )
    elif platform == "number":
        target = next(
            entity
            for entity in entities
            if isinstance(entity, GridPeakShavingPowerNumber)
        )
        survivor = next(
            entity for entity in entities if isinstance(entity, ACChargePowerNumber)
        )
    else:
        target = next(
            entity
            for entity in entities
            if isinstance(entity, EG4ScheduleTimeEntity)
            and entity._attr_translation_key == "forced_discharge_start_time_1"
        )
        survivor = next(
            entity
            for entity in entities
            if isinstance(entity, EG4ScheduleTimeEntity)
            and entity._attr_translation_key == "ac_charge_start_time_1"
        )
        target._optimistic_value = time(1, 0)
        survivor._optimistic_value = time(1, 0)

    assert target.available
    assert survivor.available
    target_id = target.unique_id

    coordinator.data["devices"][SERIAL]["features"] = {"inverter_family": "EG4_OFFGRID"}
    callbacks[0]()

    assert not target.available
    assert survivor.available

    coordinator.data["devices"][SERIAL]["features"] = dict(HYBRID_FEATURES)
    callbacks[0]()

    assert target.available
    assert [entity.unique_id for entity in entities].count(target_id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ("switch", "number"))
async def test_transport_gated_controls_are_discovered_after_route_recovery(
    hass, platform
):
    """Configured local transport recovery adds route-gated controls live."""
    if platform == "switch":
        coordinator = _switch_coordinator(
            has_http=False,
            has_local=False,
            transport_attached=False,
            model="FlexBOSS21",
        )
        expected_type = EG4QuickChargeSwitch
    else:
        coordinator = _number_coordinator(
            has_http=False, has_local=False, model="FlexBOSS21"
        )
        expected_type = QuickChargeDurationNumber

    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    entities: list[Any] = []
    setup, _representative_type = _setup_for(platform)
    await setup(hass, entry, lambda new, **_kwargs: entities.extend(new))
    assert not any(isinstance(entity, expected_type) for entity in entities)

    coordinator.has_configured_local_transport.return_value = True
    if platform == "number":
        coordinator.has_local_register_path.return_value = True
    callbacks[0]()

    assert sum(isinstance(entity, expected_type) for entity in entities) == 1


@pytest.mark.asyncio
async def test_fast_parameter_ticks_do_not_rebuild_control_candidates(hass) -> None:
    """Ordinary value updates avoid control construction and registry work."""
    coordinator = _switch_coordinator(model="FlexBOSS21")
    callbacks = []
    coordinator.async_add_listener.side_effect = lambda callback: (
        callbacks.append(callback) or (lambda: None)
    )
    entry = MagicMock()
    entry.runtime_data = coordinator

    with patch(
        "custom_components.eg4_web_monitor.switch._create_switch_entities",
        wraps=switch_module._create_switch_entities,
    ) as factory:
        await async_setup_switch(hass, entry, lambda _new, **_kwargs: None)
        assert factory.call_count == 1

        coordinator.data["parameters"][SERIAL]["FUNC_GREEN_EN"] = True
        callbacks[0]()

        assert factory.call_count == 1


def test_number_unique_id_is_independent_of_model_discovery() -> None:
    """A model upgrade cannot create a second number registry identity."""
    unknown = ACChargePowerNumber(
        _number_coordinator(model="Unknown"), SERIAL
    ).unique_id
    known = ACChargePowerNumber(
        _number_coordinator(model="FlexBOSS21"), SERIAL
    ).unique_id

    assert unknown == known == f"{SERIAL}_ac_charge_power"


def test_time_unique_id_is_independent_of_model_discovery() -> None:
    """A model upgrade cannot create a second schedule registry identity."""
    unknown = _time_entity(_time_coordinator(model="Unknown")).unique_id
    known = _time_entity(_time_coordinator(model="FlexBOSS21")).unique_id

    assert unknown == known == f"{SERIAL}_ac_charge_start_time_1"


def test_parallel_group_unique_ids_include_group_identity() -> None:
    """Parallel groups never compete for the same registry unique_id."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.get_device_info.return_value = None
    coordinator.data = {
        "devices": {
            "parallel_group_a": {"type": "parallel_group", "model": "Parallel"},
            "parallel_group_b": {"type": "parallel_group", "model": "Parallel"},
        }
    }

    group_a = EG4InverterSensor(
        coordinator, "parallel_group_a", "pv_total_power", "parallel_group"
    )
    group_b = EG4InverterSensor(
        coordinator, "parallel_group_b", "pv_total_power", "parallel_group"
    )

    assert group_a.unique_id == "parallel_group_a_pv_total_power"
    assert group_b.unique_id == "parallel_group_b_pv_total_power"
    assert group_a.unique_id != group_b.unique_id
    assert not hasattr(group_a, "_attr_entity_id")
    assert not hasattr(group_b, "_attr_entity_id")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "legacy_unique_id", "new_unique_id"),
    (
        (
            "number",
            async_setup_number,
            _number_coordinator,
            f"flexboss21_{SERIAL}_ac_charge_power",
            f"{SERIAL}_ac_charge_power",
        ),
        (
            "time",
            async_setup_time,
            _time_coordinator,
            f"flexboss21_{SERIAL}_ac_charge_start_time_1",
            f"{SERIAL}_ac_charge_start_time_1",
        ),
    ),
)
async def test_model_prefixed_control_identity_is_migrated_in_place(
    hass, platform, setup, coordinator, legacy_unique_id, new_unique_id
):
    """Legacy model-prefixed IDs preserve entity_id and user customization."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{platform} migration",
        data={},
        entry_id=f"control-migration-{platform}",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator()
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        platform,
        DOMAIN,
        legacy_unique_id,
        config_entry=entry,
        suggested_object_id=f"kept_{platform}_entity",
    )

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    migrated = registry.async_get(legacy.entity_id)
    assert migrated is not None
    assert migrated.unique_id == new_unique_id
    assert registry.async_get_entity_id(platform, DOMAIN, legacy_unique_id) is None
    assert (
        registry.async_get_entity_id(platform, DOMAIN, new_unique_id)
        == legacy.entity_id
    )


def _registry_control(
    registry: er.EntityRegistry,
    entry: MockConfigEntry,
    platform: str,
    unique_id: str,
    **kwargs: Any,
) -> er.RegistryEntry:
    """Register one control identity for ``entry``."""
    return registry.async_get_or_create(
        platform, DOMAIN, unique_id, config_entry=entry, **kwargs
    )


def _control_entry(hass, platform: str, coordinator: Any) -> MockConfigEntry:
    """Add a config entry whose runtime data is ``coordinator``."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{platform} migration",
        data={},
        entry_id=f"control-migration-{platform}",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    return entry


_LEGACY_CONTROL_CASES = (
    ("number", async_setup_number, _number_coordinator, "ac_charge_power"),
    ("time", async_setup_time, _time_coordinator, "ac_charge_start_time_1"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
async def test_foreign_stable_identity_preserves_local_legacy_controls(
    hass, caplog, platform, setup, coordinator, key
):
    """A stable identity owned by another config entry cannot consume ours."""
    runtime = coordinator()
    entry = _control_entry(hass, platform, runtime)
    foreign = MockConfigEntry(domain=DOMAIN, data={}, entry_id=f"foreign-{platform}")
    foreign.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = [
        _registry_control(registry, entry, platform, f"{model}_{SERIAL}_{key}")
        for model in ("lxp_eu_12k", "lxp_lb_eu_12k")
    ]
    legacy[0] = registry.async_update_entity(legacy[0].entity_id, name="My control")
    stable = _registry_control(registry, foreign, platform, f"{SERIAL}_{key}")
    added = []

    await setup(hass, entry, lambda entities, **_kwargs: added.extend(entities))

    # A later capability change must neither register the conflict nor warn again.
    rediscover = runtime.async_add_listener.call_args.args[0]
    runtime.data["devices"][SERIAL].setdefault("features", {})["conflict_probe"] = True
    rediscover()

    for original in (*legacy, stable):
        assert registry.async_get(original.entity_id) == original
    assert added
    assert all(entity.unique_id != stable.unique_id for entity in added)
    warnings = [
        record
        for record in caplog.records
        if record.name == "custom_components.eg4_web_monitor.control_discovery"
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert stable.entity_id in warnings[0].message
    assert foreign.entry_id in warnings[0].message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
@pytest.mark.parametrize("restored", (False, True))
@pytest.mark.parametrize("disabled_by", (None, er.RegistryEntryDisabler.USER))
async def test_enabled_stable_identity_survives_legacy_cleanup(
    hass, freezer, caplog, platform, setup, coordinator, key, restored, disabled_by
):
    """Keep the working stable control even when its legacy copies are disabled."""
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    legacy = [
        _registry_control(
            registry,
            entry,
            platform,
            f"{model}_{SERIAL}_{key}",
            disabled_by=disabled_by,
        )
        for model in ("lxp_eu_12k", "lxp_lb_eu_12k")
    ]
    freezer.tick(60)
    stable = _registry_control(
        registry,
        entry,
        platform,
        f"{SERIAL}_{key}",
        suggested_object_id="working_control",
    )
    assert stable.disabled_by is None
    if restored:
        hass.states.async_set(stable.entity_id, "unavailable", {"restored": True})

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert registry.async_get(stable.entity_id) == stable
    assert (
        registry.async_get_entity_id(platform, DOMAIN, stable.unique_id)
        == stable.entity_id
    )
    for removed in legacy:
        assert registry.async_get(removed.entity_id) is None
        assert any(
            record.levelno == logging.WARNING
            and removed.entity_id in record.message
            and removed.unique_id in record.message
            for record in caplog.records
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
@pytest.mark.parametrize("customisation", ("entity_id", "aliases", "options"))
async def test_stable_identity_retains_registry_customisation(
    hass, platform, setup, coordinator, key, customisation
):
    """Stable registry identity and user metadata survive unloaded startup."""
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    legacy = [
        _registry_control(registry, entry, platform, f"{model}_{SERIAL}_{key}")
        for model in ("lxp_eu_12k", "lxp_lb_eu_12k")
    ]
    stable = _registry_control(registry, entry, platform, f"{SERIAL}_{key}")
    if customisation == "entity_id":
        stable = registry.async_update_entity(
            stable.entity_id, new_entity_id=f"{platform}.my_working_control"
        )
    elif customisation == "aliases":
        stable = registry.async_update_entity(
            stable.entity_id, aliases=["My working control"]
        )
    else:
        registry.async_update_entity_options(
            stable.entity_id, platform, {"mode": "box"}
        )
        stable = registry.async_get(stable.entity_id)
    assert stable is not None

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert registry.async_get(stable.entity_id) == stable
    assert (
        registry.async_get_entity_id(platform, DOMAIN, stable.unique_id)
        == stable.entity_id
    )
    assert all(registry.async_get(item.entity_id) is None for item in legacy)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("object_ids", (("original_2", "original"), ("zebra", "alpha")))
async def test_tied_legacy_creation_times_have_deterministic_survivor(
    hass, freezer, platform, setup, coordinator, key, reverse, object_ids
):
    """Backfilled timestamps prefer an unsuffixed ID, then lexical ordering."""
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    registrations = list(zip(("lxp_eu_12k", "lxp_lb_eu_12k"), object_ids, strict=True))
    if reverse:
        registrations.reverse()
    legacy = [
        _registry_control(
            registry,
            entry,
            platform,
            f"{model}_{SERIAL}_{key}",
            suggested_object_id=object_id,
        )
        for model, object_id in registrations
    ]
    assert legacy[0].created_at == legacy[1].created_at
    expected_id = f"{platform}.{object_ids[1]}"

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert (
        registry.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}") == expected_id
    )
    assert (
        registry.async_get(
            next(item.entity_id for item in legacy if item.entity_id != expected_id)
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
async def test_one_of_several_model_prefixed_identities_is_kept(
    hass, freezer, platform, setup, coordinator, key
):
    """A control registered under two models keeps the newest entry (#656).

    The older one is removed instead of leaving both behind next to a newly
    registered stable entity.
    """
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    older = _registry_control(registry, entry, platform, f"lxp_eu_12k_{SERIAL}_{key}")
    freezer.tick(60)
    newer = _registry_control(
        registry, entry, platform, f"lxp_lb_eu_12k_{SERIAL}_{key}"
    )

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    new_unique_id = f"{SERIAL}_{key}"
    assert registry.async_get_entity_id(platform, DOMAIN, new_unique_id) == (
        newer.entity_id
    )
    assert registry.async_get(older.entity_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
async def test_enabled_model_prefixed_identity_wins_over_newer_disabled(
    hass, freezer, platform, setup, coordinator, key
):
    """An entry the user disabled is not the one kept."""
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    enabled = _registry_control(registry, entry, platform, f"lxp_eu_12k_{SERIAL}_{key}")
    freezer.tick(60)
    disabled = _registry_control(
        registry,
        entry,
        platform,
        f"lxp_lb_eu_12k_{SERIAL}_{key}",
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert registry.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}") == (
        enabled.entity_id
    )
    assert registry.async_get(disabled.entity_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
@pytest.mark.parametrize(
    "customisation",
    (
        {"name": "My control"},
        {"icon": "mdi:solar-power"},
        {"area_id": "my_area"},
        {"labels": {"my_label"}},
        {"hidden_by": er.RegistryEntryHider.USER},
        {"disabled_by": er.RegistryEntryDisabler.USER},
        "loaded",
    ),
    ids=("name", "icon", "area", "labels", "hidden", "disabled", "loaded"),
)
async def test_model_prefixed_leftovers_removed_once_stable_identity_exists(
    hass, caplog, platform, setup, coordinator, key, customisation
):
    """A customised or loaded stable entry survives legacy cleanup."""
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    legacy = [
        _registry_control(registry, entry, platform, f"{model}_{SERIAL}_{key}")
        for model in ("lxp_eu_12k", "lxp_lb_eu_12k")
    ]
    stable = _registry_control(registry, entry, platform, f"{SERIAL}_{key}")
    if customisation == "loaded":
        hass.states.async_set(stable.entity_id, "1")
    else:
        stable = registry.async_update_entity(stable.entity_id, **customisation)

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert registry.async_get(stable.entity_id) is not None
    assert registry.async_get(stable.entity_id).unique_id == f"{SERIAL}_{key}"
    for entry_ in legacy:
        assert registry.async_get(entry_.entity_id) is None
        assert any(
            record.levelno == logging.WARNING and entry_.entity_id in record.message
            for record in caplog.records
        )
    assert registry.async_get(stable.entity_id) == stable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "setup", "coordinator", "key"), _LEGACY_CONTROL_CASES
)
async def test_model_prefixed_entry_backing_a_live_entity_is_kept(
    hass, platform, setup, coordinator, key
):
    """Only orphans are removed: a loaded entity's entry is left alone.

    A restored placeholder state (what HA writes for an entry with no entity)
    does not count as loaded.
    """
    entry = _control_entry(hass, platform, coordinator())
    registry = er.async_get(hass)
    live, placeholder = (
        _registry_control(registry, entry, platform, f"{model}_{SERIAL}_{key}")
        for model in ("lxp_eu_12k", "lxp_lb_eu_12k")
    )
    stable = _registry_control(registry, entry, platform, f"{SERIAL}_{key}")
    hass.states.async_set(stable.entity_id, "1")
    hass.states.async_set(live.entity_id, "1")
    hass.states.async_set(placeholder.entity_id, "unavailable", {"restored": True})

    await setup(hass, entry, lambda _entities, **_kwargs: None)

    assert registry.async_get(live.entity_id) is not None
    assert registry.async_get(placeholder.entity_id) is None
