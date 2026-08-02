"""Fixtures for EG4 Web Monitor integration tests."""

import inspect
import threading
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pylxpweb.client import LuxpowerClient
from pylxpweb.devices import HybridInverter, MIDDevice
from pylxpweb.transports import ModbusTransport
from pylxpweb.transports.data import (
    InverterEnergyData,
    InverterRuntimeData,
    MidboxRuntimeData,
)

pytest_plugins = "pytest_homeassistant_custom_component"


class CloudRequestInTest(RuntimeError):
    """Raised when a test reaches pylxpweb's real cloud request path.

    Exported (not name-mangled) so a test can assert on the type rather than
    matching the message text.
    """


_ALLOW_CLOUD_MARKER = "allow_real_cloud_request_path"

_REFUSAL_MESSAGE = (
    "A test reached the real EG4 cloud request path. Give the coordinator a "
    "stub client (see stub_cloud_client) instead of letting it attempt a live "
    f"request, or mark the test with @pytest.mark.{_ALLOW_CLOUD_MARKER} if "
    "reaching the path is the point."
)


def stub_cloud_client() -> SimpleNamespace:
    """A client double with the surface the coordinator's fetches touch.

    The optional getters are deliberately absent, so the production code's own
    "installed pylxpweb predates this getter" branches no-op rather than the
    call exploding on a thinner double.

    ``base_url`` is present because the coordinator reads it outside any fetch
    (``get_station_device_info`` builds the plant's configuration URL from it),
    so a double without it would fail there for a reason unrelated to the test.
    """
    return SimpleNamespace(
        analytics=SimpleNamespace(),
        api=SimpleNamespace(control=SimpleNamespace()),
        base_url="https://monitor.eg4electronics.com",
    )


_cloud_attempts: list[str] = []

# The production signature, captured before patching, so a test can prove the
# stand-in still mirrors it rather than merely being non-permissive.
PRODUCTION_REQUEST_SIGNATURE = inspect.signature(LuxpowerClient._request)
PRODUCTION_GET_SESSION_SIGNATURE = inspect.signature(LuxpowerClient._get_session)


async def _refuse_request(
    self: LuxpowerClient,
    method: str,
    endpoint: str,
    *,
    data: dict[str, Any] | None = None,
    cache_key: str | None = None,
    cache_endpoint: str | None = None,
    _retry_count: int = 0,
) -> NoReturn:
    """Stand-in for ``LuxpowerClient._request`` — records, then refuses."""
    _cloud_attempts.append(f"{method} {endpoint}")
    raise CloudRequestInTest(_REFUSAL_MESSAGE)


async def _refuse_session(self: LuxpowerClient) -> NoReturn:
    """Stand-in for ``LuxpowerClient._get_session`` — records, then refuses."""
    _cloud_attempts.append("_get_session")
    raise CloudRequestInTest(_REFUSAL_MESSAGE)


_cloud_patchers: list[Any] = []


def _start_cloud_refusal() -> None:
    """Patch both cloud seams for the entire pytest process.

    Applied from ``pytest_configure`` — before collection and before any
    fixture of any scope — and lifted in ``pytest_unconfigure``. Neither a
    per-test nor a session-scoped FIXTURE is sufficient: a fixture starts
    after collection and after the session fixtures pytest sets up ahead of
    it, and is restored before those same fixtures finish tearing down. Import
    or collection-time calls, and equal-scope setup/finalizers, would slip
    through those windows and retry against the network unrecorded.

    The coordinator constructs a REAL ``LuxpowerClient`` for http/hybrid
    entries (websession injection), so any code path reaching a cloud fetch
    lands in pylxpweb's request layer. There the injected aiohttp session
    belongs to a different event loop than the test's, every attempt fails, and
    pylxpweb retries with exponential backoff (1+2+4+8+16s) until the caller's
    ``wait_for`` cancels it. That is pure wall clock: one test spent 55s at ~1%
    CPU, and on a runner whose egress to the portal blackholes the same paths
    can exhaust the job timeout.

    Failing at the request boundary — rather than blocking sockets — is what
    removes the cost, because the backoff sleeps happen whether or not a socket
    ever connects.

    Both seams are closed, because ``_request`` alone is NOT complete: the
    plant-region lookup and the data export read the session directly
    (``endpoints/plants.py`` and ``endpoints/export.py`` call
    ``session.post``/``session.get`` after ``client._get_session()``), so they
    would bypass a ``_request``-only guard. ``_get_session`` is the accessor
    every network user shares, which makes the pair airtight; ``_request`` is
    still patched so the common path fails with a message naming the cause.
    """
    for attribute, replacement in (
        ("_request", _refuse_request),
        ("_get_session", _refuse_session),
    ):
        patcher = patch.object(LuxpowerClient, attribute, replacement)
        patcher.start()
        _cloud_patchers.append(patcher)


def _stop_cloud_refusal() -> None:
    """Lift the patches and report anything nobody else consumed.

    The per-test fixture drains the buffer at each teardown, but attempts made
    after the LAST test's teardown — a session finalizer, or interpreter
    shutdown work — have no test to be attributed to. Reporting them here
    means they are loud rather than lost.
    """
    while _cloud_patchers:
        _cloud_patchers.pop().stop()

    if _cloud_attempts:
        unattributed = sorted(set(_cloud_attempts))
        del _cloud_attempts[:]
        raise CloudRequestInTest(
            f"cloud request(s) attempted outside any test: {unattributed}. "
            f"{_REFUSAL_MESSAGE}"
        )


@pytest.fixture(autouse=True)
def refuse_real_cloud_requests(request: pytest.FixtureRequest):
    """FAIL the test that attempted a cloud request.

    Refusing is NOT enough on its own. Every cloud fetch call site wraps its
    work in a broad ``except Exception`` and carries values forward, so a
    refusal is swallowed into "optional data missing" and the offending test
    still passes — silently attempting a live request on every run. Recording
    the attempts and reporting them here is what makes the guarantee real
    rather than aspirational. Opt out with
    ``@pytest.mark.allow_real_cloud_request_path`` when reaching the path is
    the point of the test.

    Scope, measured rather than assumed:

    * Reported for a passing test, a failing test (the failure and the
      violation both surface), and each parametrized case independently.
    * A test skipped by ``@pytest.mark.skip`` never runs its body, so there is
      nothing to catch. A RUNTIME ``pytest.skip()`` is different: the body ran,
      so a prior violation is reported as SKIPPED plus ERROR.
    * Plain non-strict ``xfail`` is the hole: pytest absorbs the teardown error
      and the run still exits 0. ``xfail(raises=...)`` with a mismatch, and
      dynamic ``pytest.xfail()``, can still surface it. The suite has no xfail
      tests today, and a violation costs no wall clock because the refusal is
      immediate.
    * An attempt made after this fixture's teardown — during a finalizer that
      runs later — is still recorded, because the patches are held by
      ``pytest_configure``/``pytest_unconfigure`` rather than by any fixture,
      and surfaces against the NEXT test. Attribution is off by one test;
      detection is not lost. This is why the buffer is drained ONLY at
      teardown: clearing it on entry as well would discard exactly those late
      attempts instead of deferring them, turning an attribution quirk into a
      silent miss. Anything left over after the final test is reported by
      ``_stop_cloud_refusal``.
    * ``get_closest_marker`` honours class- and module-level marks, so a
      module-wide ``pytestmark`` would opt an entire file out. That is the
      normal pytest inheritance rule, not a special case here, but it means
      the marker should be applied per-test.
    """
    yield
    attempts = list(_cloud_attempts)
    del _cloud_attempts[:]

    if attempts and request.node.get_closest_marker(_ALLOW_CLOUD_MARKER) is None:
        unique = sorted(set(attempts))
        raise CloudRequestInTest(
            f"{len(attempts)} cloud request(s) attempted: {unique}. {_REFUSAL_MESSAGE}"
        )


def pytest_unconfigure(config):
    """Lift the cloud-refusal patches at the very end of the run."""
    _stop_cloud_refusal()


def wire_coordinator_write_helpers(coordinator: MagicMock) -> None:
    """Wire the extracted coordinator write-helpers onto a mock coordinator.

    ``require_client``, ``refresh_inverter_params_if_linked`` and
    ``params_are_local_raw`` were lifted out of the number/select/time entity
    platforms into the coordinator. This mirrors the pre-extraction inline code
    against the same sub-mocks: ``require_client`` reads the (possibly
    test-reassigned) ``client``, the post-write refresh honors the link-down
    gate, and ``params_are_local_raw`` reproduces the real predicate.
    """

    def _require_client() -> MagicMock:
        if coordinator.client is None:
            raise HomeAssistantError(
                "No local transport or cloud API available for parameter write."
            )
        return coordinator.client

    async def _refresh_if_linked(target: str) -> None:
        inv = coordinator.get_inverter_object(target)
        if inv and not coordinator.is_transport_link_down(target):
            await inv.refresh(force=True, include_parameters=True)

    def _params_local_raw(target: str, *, include_configured: bool = False) -> bool:
        if coordinator.is_local_only():
            return True
        if include_configured and coordinator.has_configured_local_transport(target):
            return True
        inv = coordinator.get_inverter_object(target)
        return getattr(inv, "transport", None) is not None

    coordinator.require_client = MagicMock(side_effect=_require_client)
    coordinator.refresh_inverter_params_if_linked = AsyncMock(
        side_effect=_refresh_if_linked
    )
    coordinator.params_are_local_raw = MagicMock(side_effect=_params_local_raw)


# =========================================================================
# Shape-faithful pylxpweb device builders (epic eg4-uqs)
# =========================================================================
# A plain MagicMock answers to ANY attribute, so a coordinator test passes even
# when the real pylxpweb object lacks the attribute the code reads — the exact
# blindness that let seam drift (e.g. eg4-ohz) ship undetected.
#
# These builders return REAL pylxpweb device objects (mock client — the client
# is only used for API calls, never by the property accessors) with REAL
# transport dataclasses injected.  The device's @property accessors compute for
# real, and reading an attribute the class does not define raises AttributeError
# — so a test fails the moment the integration relies on a non-existent
# pylxpweb attribute.  ``_map_device_properties`` then gets ``None`` for a
# missing property (its getattr default), exactly as in production.
#
# For pure transport dataclasses (InverterRuntimeData, InverterEnergyData,
# BatteryData, BatteryBankData, MidboxRuntimeData) construct the REAL dataclass
# directly in the test — they are trivial to instantiate and carry real field
# semantics; no helper is needed.


def make_real_inverter(
    serial_number: str = "1234567890",
    model: str = "FlexBOSS21",
    *,
    runtime: InverterRuntimeData | None = None,
    energy: InverterEnergyData | None = None,
    client: Any = None,
) -> HybridInverter:
    """Build a REAL HybridInverter with injected transport data.

    The client is mocked (only API methods use it); the property accessors read
    the injected ``InverterRuntimeData`` / ``InverterEnergyData``.  Reading an
    attribute the real class does not define raises AttributeError.
    """
    inverter = HybridInverter(client or MagicMock(), serial_number, model)
    if runtime is not None:
        inverter._transport_runtime = runtime
    if energy is not None:
        inverter._transport_energy = energy
    return inverter


def make_real_mid(
    serial_number: str = "0987654321",
    model: str = "GridBOSS",
    *,
    runtime: MidboxRuntimeData | None = None,
    client: Any = None,
) -> MIDDevice:
    """Build a REAL MIDDevice (GridBOSS) with injected runtime data."""
    mid = MIDDevice(client or MagicMock(), serial_number, model)
    if runtime is not None:
        mid._transport_runtime = runtime
    return mid


@pytest.fixture
def make_real_inverter_factory():
    """Fixture returning the ``make_real_inverter`` builder."""
    return make_real_inverter


@pytest.fixture
def make_real_mid_factory():
    """Fixture returning the ``make_real_mid`` builder."""
    return make_real_mid


def make_transport_spec(**attrs: Any) -> Any:
    """Build a shape-faithful stand-in for a pylxpweb network transport.

    The transport is the network CONNECTION object (Modbus/Dongle socket); a
    real connected one needs a live socket, so tests cannot use it directly.
    Unlike the device classes, ModbusTransport exposes ``host`` / ``is_connected``
    / ``split_phase`` and the read/connect coroutines at the CLASS level, so
    ``create_autospec(spec_set=True)`` gives a stand-in that is BOTH controllable
    (set host/is_connected/...) AND shape-faithful (reading or setting an
    attribute the real transport does not define raises AttributeError).  Use
    this instead of a bare MagicMock so a renamed transport attribute fails CI.
    """
    spec = create_autospec(ModbusTransport, spec_set=True, instance=True)
    if attrs:
        spec.configure_mock(**attrs)
    return spec


@pytest.fixture
def make_transport_spec_factory():
    """Fixture returning the ``make_transport_spec`` helper."""
    return make_transport_spec


def create_mock_station(
    station_id: str | int,
    station_name: str,
    country: str = "United States of America",
    timezone: str = "GMT -8",
    address: str = "123 Test St",
    create_date: str = "2025-01-01",
) -> MagicMock:
    """Create a mock Station object with all required fields.

    This helper ensures all mock stations have the complete set of fields
    that the coordinator expects to extract for station sensors.

    Args:
        station_id: Plant/station ID. The real API (pylxpweb ``Station.id``)
            returns an int, so tests that mirror production should pass an
            int (see issue #275).
        station_name: Station name
        country: Country name (defaults to "United States of America")
        timezone: Timezone string (defaults to "GMT -8")
        address: Physical address (defaults to "123 Test St")
        create_date: Plant creation date (defaults to "2025-01-01")

    Returns:
        MagicMock object configured as a Station with all required attributes
    """
    mock_station = MagicMock()
    mock_station.id = station_id
    mock_station.name = station_name
    mock_station.country = country
    mock_station.timezone = timezone
    mock_station.address = address
    mock_station.createDate = create_date
    return mock_station


def pytest_configure(config):
    """Register markers and allow asyncio shutdown threads.

    pytest-homeassistant-custom-component verifies no unexpected threads remain after tests.
    The asyncio event loop may create a daemon thread named '_run_safe_shutdown_loop'
    during shutdown which is expected and harmless. This configuration patches threading.enumerate
    to filter out this thread during cleanup verification.
    """
    config.addinivalue_line(
        "markers",
        f"{_ALLOW_CLOUD_MARKER}: test intends to reach pylxpweb's cloud "
        "request path; the refusal is still raised, but reaching it is not "
        "treated as a failure.",
    )
    _start_cloud_refusal()

    # Store original threading.enumerate
    original_enumerate = threading.enumerate

    def filtered_enumerate():
        """Return all threads except asyncio shutdown thread."""
        threads = original_enumerate()
        return [
            thread
            for thread in threads
            if not (thread.name and "_run_safe_shutdown_loop" in thread.name)
        ]

    # Monkey-patch threading.enumerate globally
    threading.enumerate = filtered_enumerate


# Enable custom integrations for testing
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def mock_luxpower_client():
    """Mock LuxpowerClient from pylxpweb 0.3.5."""
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    mock_client.clear_cache = MagicMock()
    mock_client.plants = MagicMock()
    mock_client.devices = MagicMock()
    mock_client.control = MagicMock()
    return mock_client


@pytest.fixture
def mock_station():
    """Mock Station object from pylxpweb 0.3.5."""
    mock = MagicMock()
    mock.id = "123456"
    mock.name = "Test Station"
    mock.country = "United States of America"
    mock.timezone = "GMT -8"
    mock.address = "123 Test St"
    mock.createDate = "2025-01-01"
    mock.load = AsyncMock(return_value=mock)
    mock.refresh = AsyncMock()
    mock.refresh_all_data = AsyncMock()
    mock.detect_dst_status = MagicMock(return_value=True)
    mock.sync_dst_setting = AsyncMock(return_value=True)
    mock.all_inverters = []
    mock.all_batteries = []
    return mock


@pytest.fixture
def mock_coordinator(mock_luxpower_client, mock_station):
    """Mock EG4DataUpdateCoordinator with pylxpweb 0.3.5 client."""
    mock = MagicMock()
    mock.client = mock_luxpower_client
    mock.station = mock_station
    mock.async_shutdown = AsyncMock()
    mock._last_available_state = True
    return mock
