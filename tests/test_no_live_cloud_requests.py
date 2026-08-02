"""The unit suite must never attempt a live EG4 cloud request.

The coordinator builds a REAL ``LuxpowerClient`` for http/hybrid entries, so a
test that drives any cloud-touching path reaches pylxpweb's request layer. The
injected aiohttp session belongs to a different event loop than the test's,
every attempt fails, and pylxpweb retries with exponential backoff — spending
wall clock (1+2+4+8+16s) until the caller's ``wait_for`` cancels it. One test
cost 55s at ~1% CPU, the full suite 25 minutes, and a release CI run wedged
past its job timeout twice.

``refuse_real_cloud_requests`` in conftest closes that off at the request
boundary, which is what removes the cost: the backoff sleeps happen whether or
not a socket ever connects, so blocking sockets alone would not have helped.

These tests keep both seams closed. They were verified to FAIL with the fixture
made non-autouse. A wall-clock assertion was deliberately NOT added alongside
them: an unreachable host resolves fast enough on a developer machine that the
timing never trips, so such a test would pass whether or not the guard existed
and would only look like protection.
"""

import pytest
from pylxpweb.client import LuxpowerClient

from .conftest import CloudRequestInTest


def _client() -> LuxpowerClient:
    return LuxpowerClient("user", "password", base_url="https://example.invalid")


async def test_request_path_is_refused():
    """The common seam: everything routed through ``_request``."""
    with pytest.raises(CloudRequestInTest):
        await _client()._request("POST", "/WManage/api/inverter/getInverterRuntime")


async def test_session_accessor_is_refused():
    """The second seam, and the reason ``_request`` alone is not enough.

    ``endpoints/plants.py`` and ``endpoints/export.py`` take the session from
    ``client._get_session()`` and call ``session.post``/``session.get``
    directly, bypassing ``_request`` entirely. Guarding only ``_request`` would
    leave those free to reach the network.
    """
    with pytest.raises(CloudRequestInTest):
        await _client()._get_session()
