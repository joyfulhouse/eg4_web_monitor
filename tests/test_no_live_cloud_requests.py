"""No test may attempt a live EG4 cloud request — and now it is enforced.

Before enforcement this file's opening claim was aspirational: 33 tests
attempted a request on every run and were merely refused, which the call sites'
broad ``except Exception`` swallowed. ``refuse_real_cloud_requests`` now records
attempts and raises at teardown, so the sentence above is a checked property
rather than an intention. Its exact scope, including the xfail hole, is
documented on that fixture.

Why it mattered: the coordinator builds a REAL ``LuxpowerClient`` for
http/hybrid entries, so a test driving any cloud-touching path reaches
pylxpweb's request layer. The injected aiohttp session belongs to a different
event loop than the test's, every attempt fails, and pylxpweb retries with
exponential backoff — spending wall clock (1+2+4+8+16s) until the caller's
``wait_for`` cancels it. One test cost 55s at ~1% CPU, the full suite 25
minutes, and a release CI run wedged past its job timeout twice. Closing this
at the request boundary is what removes the cost: the backoff sleeps happen
whether or not a socket ever connects, so blocking sockets would not have
helped.

These tests keep both seams closed and were verified to FAIL with the patches
lifted. A wall-clock assertion was deliberately NOT added alongside them: an
unreachable host resolves fast enough on a developer machine that the timing
never trips, so such a test would pass whether or not the guard existed and
would only look like protection.
"""

import inspect
from typing import Any

import pytest
from pylxpweb.client import LuxpowerClient

from .conftest import PRODUCTION_REQUEST_SIGNATURE, CloudRequestInTest


def _client() -> LuxpowerClient:
    return LuxpowerClient("user", "password", base_url="https://example.invalid")


@pytest.mark.allow_real_cloud_request_path
async def test_request_path_is_refused():
    """The common seam: everything routed through ``_request``."""
    with pytest.raises(CloudRequestInTest, match="real EG4 cloud request path"):
        await _client()._request("POST", "/WManage/api/inverter/getInverterRuntime")


@pytest.mark.allow_real_cloud_request_path
async def test_session_accessor_is_refused():
    """The second seam, and the reason ``_request`` alone is not enough.

    ``endpoints/plants.py`` and ``endpoints/export.py`` take the session from
    ``client._get_session()`` and call ``session.post``/``session.get``
    directly, bypassing ``_request`` entirely. Guarding only ``_request`` would
    leave those free to reach the network.
    """
    with pytest.raises(CloudRequestInTest, match="real EG4 cloud request path"):
        await _client()._get_session()


@pytest.mark.allow_real_cloud_request_path
def test_refusal_matches_production_request_signature():
    """The stand-in must mirror the real ``_request`` signature exactly.

    ``create_autospec(LuxpowerClient)`` derives its spec from whatever is
    patched onto the class, so a stand-in whose signature drifts from
    production silently changes what every autospec-based test accepts.

    Comparing against the signature captured BEFORE patching is what makes
    this a real check: asserting only that some call raises ``TypeError``
    would still pass for a stand-in missing a keyword-only parameter. And
    drift is not hypothetical in one direction — the pylxpweb pin is
    unbounded, so an added parameter that production starts passing would
    make argument binding raise before the attempt is ever recorded, and the
    broad production ``except`` would swallow it.
    """

    def _binding_shape(sig: inspect.Signature) -> list[tuple[str, Any, Any]]:
        """Name, kind and default — what argument binding actually uses.

        Annotations are excluded on purpose: pylxpweb uses postponed
        evaluation, so its annotations are strings while the stand-in's are
        objects. Comparing those would fail on a cosmetic difference and say
        nothing about which calls bind.
        """
        return [(p.name, p.kind, p.default) for p in sig.parameters.values()]

    assert _binding_shape(inspect.signature(LuxpowerClient._request)) == _binding_shape(
        PRODUCTION_REQUEST_SIGNATURE
    ), (
        "the refusal stand-in no longer mirrors LuxpowerClient._request; "
        "update it to the current production signature"
    )
