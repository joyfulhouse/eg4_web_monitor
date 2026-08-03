"""Regression tests for account-scoped cloud cookie sessions (eg4-06er.15)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession
from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_CLOSE,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest
from yarl import URL

from custom_components.eg4_web_monitor._config_flow import EG4ConfigFlow
from custom_components.eg4_web_monitor.const import (
    CONF_BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DST_SYNC,
    CONF_PLANT_ID,
    CONF_VERIFY_SSL,
    CONNECTION_TYPE_HTTP,
    DOMAIN,
)
from custom_components.eg4_web_monitor.coordinator import EG4DataUpdateCoordinator
from custom_components.eg4_web_monitor import async_unload_entry
from pylxpweb.exceptions import LuxpowerAPIError


BASE_URL = "https://monitor.eg4electronics.com"
COOKIE_NAME = "JSESSIONID"


def _http_entry(
    entry_id: str, username: str, *, verify_ssl: bool = True
) -> MockConfigEntry:
    """Build one cloud entry on the shared EG4 origin."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"EG4 - {username}",
        data={
            CONF_USERNAME: username,
            CONF_PASSWORD: "secret",
            CONF_BASE_URL: BASE_URL,
            CONF_VERIFY_SSL: verify_ssl,
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_HTTP,
            CONF_PLANT_ID: entry_id,
            CONF_DST_SYNC: False,
        },
        entry_id=entry_id,
    )


def _client_session(coordinator: EG4DataUpdateCoordinator) -> ClientSession:
    """Return the real session injected into pylxpweb."""
    client = coordinator.require_client()
    session = getattr(client, "_session", None)
    assert isinstance(session, ClientSession)
    return session


def _set_cookie(session: ClientSession, value: str) -> None:
    """Apply the cookie shape returned by a login on the common API origin."""
    session.cookie_jar.update_cookies({COOKIE_NAME: value}, response_url=URL(BASE_URL))


def _cookie_value(session: ClientSession) -> str:
    """Read the cookie that would be sent to the common API origin."""
    return session.cookie_jar.filter_cookies(URL(BASE_URL))[COOKIE_NAME].value


async def test_loaded_accounts_keep_distinct_cookies_on_one_ha_connector(
    hass: HomeAssistant,
) -> None:
    """A login for account B must not replace account A's domain cookie."""
    entry_a = _http_entry("plant-a", "account-a")
    entry_b = _http_entry("plant-b", "account-b")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    coordinator_a = EG4DataUpdateCoordinator(hass, entry_a)
    coordinator_b = EG4DataUpdateCoordinator(hass, entry_b)
    session_a = _client_session(coordinator_a)
    session_b = _client_session(coordinator_b)
    default_session = aiohttp_client.async_get_clientsession(hass)

    try:
        assert session_a is not session_b
        assert session_a.cookie_jar is not session_b.cookie_jar
        assert session_a is not default_session
        assert session_b is not default_session
        assert session_a.connector is default_session.connector
        assert session_b.connector is default_session.connector

        _set_cookie(session_a, "account-a-session")
        _set_cookie(session_b, "account-b-session")

        assert _cookie_value(session_a) == "account-a-session"
        assert _cookie_value(session_b) == "account-b-session"
    finally:
        await coordinator_a.async_shutdown()
        await coordinator_b.async_shutdown()


async def test_coordinator_shutdown_detaches_only_its_private_session(
    hass: HomeAssistant,
) -> None:
    """Unloading one entry must neither leak nor break another entry's session."""
    entry_a = _http_entry("shutdown-a", "account-a")
    entry_b = _http_entry("shutdown-b", "account-b")
    coordinator_a = EG4DataUpdateCoordinator(hass, entry_a)
    coordinator_b = EG4DataUpdateCoordinator(hass, entry_b)
    session_a = _client_session(coordinator_a)
    session_b = _client_session(coordinator_b)
    default_session = aiohttp_client.async_get_clientsession(hass)

    await coordinator_a.async_shutdown()
    try:
        assert session_a.closed
        assert not session_b.closed
        assert not default_session.closed
        assert not default_session.connector.closed
    finally:
        await coordinator_b.async_shutdown()

    assert session_b.closed
    assert not default_session.closed
    assert not default_session.connector.closed


async def test_shutdown_closes_dependency_before_detaching_session(
    hass: HomeAssistant,
) -> None:
    """Dependency-owned auth work must stop before its HTTP session disappears."""
    coordinator = EG4DataUpdateCoordinator(
        hass, _http_entry("shutdown-order", "account-a")
    )
    client = coordinator.require_client()
    session = _client_session(coordinator)
    real_detach = session.detach
    events: list[str] = []

    async def _close_client() -> None:
        events.append("client-close")

    def _detach_session() -> None:
        events.append("session-detach")
        real_detach()

    with (
        patch.object(client, "close", new=AsyncMock(side_effect=_close_client)),
        patch.object(session, "detach", new=MagicMock(side_effect=_detach_session)),
    ):
        await coordinator.async_shutdown()

    assert events == ["client-close", "session-detach"]
    assert session.closed


async def test_homeassistant_stop_detaches_private_session(
    hass: HomeAssistant,
) -> None:
    """Core stop without entry unload must also release the session wrapper."""
    coordinator = EG4DataUpdateCoordinator(
        hass, _http_entry("homeassistant-stop", "account-a")
    )
    client = coordinator.require_client()
    session = _client_session(coordinator)
    default_session = aiohttp_client.async_get_clientsession(hass)
    real_detach = session.detach
    events: list[str] = []

    async def _close_client() -> None:
        events.append("client-close")

    def _detach_session() -> None:
        events.append("session-detach")
        real_detach()

    with (
        patch.object(client, "close", new=AsyncMock(side_effect=_close_client)),
        patch.object(session, "detach", new=MagicMock(side_effect=_detach_session)),
    ):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()

        assert events == ["client-close", "session-detach"]
        assert session.closed
        assert not default_session.closed
        assert not default_session.connector.closed

        # A later unload callback remains safe and does not detach twice.
        await coordinator.async_shutdown()

    assert events == ["client-close", "session-detach", "client-close"]


async def test_entry_unload_detaches_injected_session(
    hass: HomeAssistant,
) -> None:
    """The public integration unload path must release its injected session."""
    entry = _http_entry("entry-unload", "account-a")
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    entry.runtime_data = coordinator
    session = _client_session(coordinator)
    default_session = aiohttp_client.async_get_clientsession(hass)

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(hass, entry)

    assert session.closed
    assert not default_session.closed
    assert not default_session.connector.closed


async def test_config_entry_setup_cleanup_detaches_cloud_session(
    hass: HomeAssistant,
) -> None:
    """The coordinator's failed-setup callback must release its private wrapper."""
    entry = _http_entry("failed-setup", "account-a")
    token = config_entries.current_entry.set(entry)
    try:
        coordinator = EG4DataUpdateCoordinator(hass, entry)
    finally:
        config_entries.current_entry.reset(token)
    session = _client_session(coordinator)

    assert not session.closed
    await entry._async_process_on_unload(hass)
    assert session.closed

    # The integration's explicit shutdown path is idempotent with HA cleanup.
    await coordinator.async_shutdown()
    assert session.closed


async def test_unverified_entry_uses_ha_unverified_connector(
    hass: HomeAssistant,
) -> None:
    """The entry's SSL policy must select the matching HA connector pool."""
    entry = _http_entry("unverified", "account-a", verify_ssl=False)
    coordinator = EG4DataUpdateCoordinator(hass, entry)
    session = _client_session(coordinator)
    unverified_default = aiohttp_client.async_get_clientsession(hass, verify_ssl=False)
    verified_default = aiohttp_client.async_get_clientsession(hass, verify_ssl=True)

    try:
        assert session is not unverified_default
        assert session.connector is unverified_default.connector
        assert session.connector is not verified_default.connector
    finally:
        await coordinator.async_shutdown()


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_coordinator_passes_ssl_policy_to_private_session_factory(
    hass: HomeAssistant, verify_ssl: bool
) -> None:
    """Both SSL policies must reach HA's isolated-session factory unchanged."""
    from custom_components.eg4_web_monitor import coordinator as coordinator_module

    real_create = aiohttp_client.async_create_clientsession
    with patch.object(
        coordinator_module.aiohttp_client,
        "async_create_clientsession",
        wraps=real_create,
    ) as create_session:
        coordinator = EG4DataUpdateCoordinator(
            hass,
            _http_entry(
                f"ssl-policy-{verify_ssl}",
                "account-a",
                verify_ssl=verify_ssl,
            ),
        )

    create_session.assert_called_once_with(
        hass,
        verify_ssl=verify_ssl,
        auto_cleanup=True,
    )
    await coordinator.async_shutdown()


async def test_client_constructor_failure_detaches_created_session(
    hass: HomeAssistant,
) -> None:
    """A synchronous dependency constructor failure must not leak a session."""
    from custom_components.eg4_web_monitor import coordinator as coordinator_module

    entry = _http_entry("constructor-failure", "account-a")
    created_sessions: list[ClientSession] = []
    real_create = aiohttp_client.async_create_clientsession

    def _capture_session(*args, **kwargs) -> ClientSession:
        session = real_create(*args, **kwargs)
        created_sessions.append(session)
        return session

    with (
        patch.object(
            coordinator_module.aiohttp_client,
            "async_create_clientsession",
            side_effect=_capture_session,
        ),
        patch.object(
            coordinator_module,
            "LuxpowerClient",
            side_effect=RuntimeError("constructor failed"),
        ),
        pytest.raises(RuntimeError, match="constructor failed"),
    ):
        EG4DataUpdateCoordinator(hass, entry)

    assert len(created_sessions) == 1
    assert created_sessions[0].closed


async def test_post_client_constructor_failure_uses_entry_cleanup_fallback(
    hass: HomeAssistant,
) -> None:
    """A later coordinator constructor failure retains HA's detach fallback."""
    from custom_components.eg4_web_monitor import coordinator as coordinator_module

    entry = _http_entry("post-client-failure", "account-a")
    created_sessions: list[ClientSession] = []
    real_create = aiohttp_client.async_create_clientsession

    def _capture_session(*args, **kwargs) -> ClientSession:
        session = real_create(*args, **kwargs)
        created_sessions.append(session)
        return session

    token = config_entries.current_entry.set(entry)
    try:
        with (
            patch.object(
                coordinator_module.aiohttp_client,
                "async_create_clientsession",
                side_effect=_capture_session,
            ),
            patch.object(
                coordinator_module.DataUpdateCoordinator,
                "__init__",
                side_effect=RuntimeError("coordinator init failed"),
            ),
            pytest.raises(RuntimeError, match="coordinator init failed"),
        ):
            EG4DataUpdateCoordinator(hass, entry)
    finally:
        config_entries.current_entry.reset(token)

    assert len(created_sessions) == 1
    assert not created_sessions[0].closed
    await entry._async_process_on_unload(hass)
    assert created_sessions[0].closed


async def test_post_client_constructor_failure_has_hass_close_fallback(
    hass: HomeAssistant,
) -> None:
    """Outside entry context, HA close still detaches an orphaned wrapper."""
    from custom_components.eg4_web_monitor import coordinator as coordinator_module

    entry = _http_entry("post-client-close-fallback", "account-a")
    created_sessions: list[ClientSession] = []
    real_create = aiohttp_client.async_create_clientsession

    def _capture_session(*args, **kwargs) -> ClientSession:
        session = real_create(*args, **kwargs)
        created_sessions.append(session)
        return session

    with (
        patch.object(
            coordinator_module.aiohttp_client,
            "async_create_clientsession",
            side_effect=_capture_session,
        ),
        patch.object(
            coordinator_module.DataUpdateCoordinator,
            "__init__",
            side_effect=RuntimeError("coordinator init failed"),
        ),
        pytest.raises(RuntimeError, match="coordinator init failed"),
    ):
        EG4DataUpdateCoordinator(hass, entry)

    assert len(created_sessions) == 1
    assert not created_sessions[0].closed
    hass.bus.async_fire(EVENT_HOMEASSISTANT_CLOSE)
    await hass.async_block_till_done()
    assert created_sessions[0].closed


class _CookieWritingClient:
    """Config-flow client double that emulates a successful account-B login."""

    instances: list[_CookieWritingClient] = []

    def __init__(self, *args, session: ClientSession, **kwargs) -> None:
        del args, kwargs
        self.session = session
        self.connector = session.connector
        type(self).instances.append(self)

    async def login(self) -> None:
        """Emulate the login side effect used by the production client."""
        _set_cookie(self.session, "account-b-session")

    async def close(self) -> None:
        """Injected sessions remain owned by the integration."""

    async def __aenter__(self) -> _CookieWritingClient:
        await self.login()
        return self

    async def __aexit__(self, *args) -> None:
        del args


class _ShieldedAuthenticationClient:
    """Client double whose login work deliberately outlives its caller."""

    instances: list[_ShieldedAuthenticationClient] = []

    def __init__(self, *args, session: ClientSession, **kwargs) -> None:
        del args, kwargs
        self.session = session
        self.events: list[str] = []
        self.authentication_started = asyncio.Event()
        self.authentication_task: asyncio.Task[None] | None = None
        type(self).instances.append(self)

    async def _authenticate(self) -> None:
        self.events.append("auth-start")
        self.authentication_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.events.append("auth-end")

    async def login(self) -> None:
        self.authentication_task = asyncio.create_task(self._authenticate())
        await asyncio.shield(self.authentication_task)

    async def __aenter__(self) -> _ShieldedAuthenticationClient:
        await self.login()
        return self

    async def __aexit__(self, *args) -> None:
        del args
        await self.close()

    async def close(self) -> None:
        self.events.append("close-start")
        task = self.authentication_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.events.append("close-end")


async def test_config_flow_login_cannot_overwrite_loaded_account_cookie(
    hass: HomeAssistant,
) -> None:
    """Temporary config-flow auth gets an isolated jar and immediate cleanup."""
    coordinator = EG4DataUpdateCoordinator(
        hass, _http_entry("loaded-account", "account-a")
    )
    loaded_session = _client_session(coordinator)
    _set_cookie(loaded_session, "account-a-session")

    flow = EG4ConfigFlow()
    flow.hass = hass
    flow._username = "account-b"
    flow._password = "secret"
    flow._base_url = BASE_URL
    flow._verify_ssl = True
    _CookieWritingClient.instances.clear()

    try:
        with (
            patch(
                "custom_components.eg4_web_monitor._config_flow.LuxpowerClient",
                _CookieWritingClient,
            ),
            patch(
                "pylxpweb.devices.Station.load_all",
                new=AsyncMock(
                    return_value=[SimpleNamespace(id="plant-b", name="Plant B")]
                ),
            ),
        ):
            await flow._test_cloud_credentials()

        temporary_client = _CookieWritingClient.instances[-1]
        assert temporary_client.session is not loaded_session
        assert temporary_client.connector is loaded_session.connector
        assert temporary_client.session.closed
        assert not loaded_session.closed
        assert _cookie_value(loaded_session) == "account-a-session"
        assert flow._plants == [{"plantId": "plant-b", "name": "Plant B"}]
    finally:
        await coordinator.async_shutdown()


async def test_config_flow_failure_also_detaches_temporary_session(
    hass: HomeAssistant,
) -> None:
    """A validation exception must not retain its cookie jar until HA stops."""
    flow = EG4ConfigFlow()
    flow.hass = hass
    flow._username = "account-b"
    flow._password = "secret"
    flow._base_url = BASE_URL
    flow._verify_ssl = True
    _CookieWritingClient.instances.clear()

    with (
        patch(
            "custom_components.eg4_web_monitor._config_flow.LuxpowerClient",
            _CookieWritingClient,
        ),
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(side_effect=LuxpowerAPIError("station load failed")),
        ),
        pytest.raises(LuxpowerAPIError, match="station load failed"),
    ):
        await flow._test_cloud_credentials()

    assert _CookieWritingClient.instances[-1].session.closed


async def test_config_flow_uses_configured_unverified_connector(
    hass: HomeAssistant,
) -> None:
    """Temporary validation must honor the flow's configured SSL policy."""
    flow = EG4ConfigFlow()
    flow.hass = hass
    flow._username = "account-b"
    flow._password = "secret"
    flow._base_url = BASE_URL
    flow._verify_ssl = False
    _CookieWritingClient.instances.clear()

    unverified_default = aiohttp_client.async_get_clientsession(hass, verify_ssl=False)
    verified_default = aiohttp_client.async_get_clientsession(hass, verify_ssl=True)
    with (
        patch(
            "custom_components.eg4_web_monitor._config_flow.LuxpowerClient",
            _CookieWritingClient,
        ),
        patch(
            "pylxpweb.devices.Station.load_all",
            new=AsyncMock(return_value=[SimpleNamespace(id="plant-b", name="Plant B")]),
        ),
    ):
        await flow._test_cloud_credentials()

    temporary_client = _CookieWritingClient.instances[-1]
    assert temporary_client.connector is unverified_default.connector
    assert temporary_client.connector is not verified_default.connector
    assert temporary_client.session.closed


async def test_config_flow_cancellation_drains_shielded_login_before_detach(
    hass: HomeAssistant,
) -> None:
    """Cancellation during login must not orphan auth on a detached session."""
    flow = EG4ConfigFlow()
    flow.hass = hass
    flow._username = "account-b"
    flow._password = "secret"
    flow._base_url = BASE_URL
    flow._verify_ssl = True
    _ShieldedAuthenticationClient.instances.clear()

    with patch(
        "custom_components.eg4_web_monitor._config_flow.LuxpowerClient",
        _ShieldedAuthenticationClient,
    ):
        validation_task = asyncio.create_task(flow._test_cloud_credentials())
        while not _ShieldedAuthenticationClient.instances:
            await asyncio.sleep(0)
        client = _ShieldedAuthenticationClient.instances[-1]
        await client.authentication_started.wait()

        real_detach = client.session.detach

        def _detach_session() -> None:
            client.events.append("session-detach")
            real_detach()

        with patch.object(
            client.session,
            "detach",
            new=MagicMock(side_effect=_detach_session),
        ):
            validation_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await validation_task

    events_before_test_cleanup = list(client.events)
    authentication_task = client.authentication_task
    try:
        assert events_before_test_cleanup == [
            "auth-start",
            "close-start",
            "auth-end",
            "close-end",
            "session-detach",
        ]
        assert authentication_task is not None
        assert authentication_task.done()
        assert client.session.closed
    finally:
        if authentication_task is not None and not authentication_task.done():
            authentication_task.cancel()
            await asyncio.gather(authentication_task, return_exceptions=True)
        if not client.session.closed:
            client.session.detach()


async def test_repeated_shutdown_cancellation_waits_for_close_before_detach(
    hass: HomeAssistant,
) -> None:
    """A second cancellation must not detach beneath dependency cleanup."""
    coordinator = EG4DataUpdateCoordinator(
        hass, _http_entry("repeated-cancel", "account-a")
    )
    client = coordinator.require_client()
    session = _client_session(coordinator)
    default_session = aiohttp_client.async_get_clientsession(hass)
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    events: list[str] = []
    loop_errors: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    real_detach = session.detach

    async def _close_client() -> None:
        events.append("close-start")
        close_started.set()
        await allow_close.wait()
        events.append("close-end")
        raise ValueError("close failed after cancellation")

    def _detach_session() -> None:
        events.append("session-detach")
        real_detach()

    try:
        loop.set_exception_handler(
            lambda _loop, context: loop_errors.append(dict(context))
        )
        with (
            patch.object(client, "close", new=AsyncMock(side_effect=_close_client)),
            patch.object(session, "detach", new=MagicMock(side_effect=_detach_session)),
        ):
            shutdown_task = asyncio.create_task(coordinator.async_shutdown())
            await close_started.wait()
            shutdown_task.cancel()
            await asyncio.sleep(0)
            shutdown_task.cancel()
            allow_close.set()

            with pytest.raises(asyncio.CancelledError) as cancelled:
                await shutdown_task

        await asyncio.sleep(0)
        assert events == ["close-start", "close-end", "session-detach"]
        assert isinstance(cancelled.value.__cause__, ValueError)
        assert loop_errors == []
        assert session.closed
        assert not default_session.closed
        assert not default_session.connector.closed
    finally:
        loop.set_exception_handler(previous_exception_handler)
        allow_close.set()
        if not session.closed:
            session.detach()
