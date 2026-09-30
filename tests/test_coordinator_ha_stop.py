"""HA stop must close the refresh producer, not just its current timer."""

import asyncio

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eg4_web_monitor.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator


async def test_ha_stop_terminally_shuts_down_inflight_debounced_refresh(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
    )
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    started = asyncio.Event()
    release = asyncio.Event()

    async def refresh():
        started.set()
        await release.wait()

    coordinator._debounced_refresh.function = refresh
    task = asyncio.create_task(coordinator.async_request_refresh())
    coordinator._background_tasks.add(task)
    try:
        await started.wait()
        await coordinator._async_handle_shutdown(None)
        assert task.cancelled()
        assert coordinator._shutdown_requested
        assert coordinator._debounced_refresh._shutdown_requested
        assert coordinator._debounced_refresh._timer_task is None
    finally:
        release.set()
        await coordinator.async_shutdown()
