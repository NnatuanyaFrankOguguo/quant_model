"""Every connector that touches the network obeys the politeness rule. P4 check 12.

`DATA_FOUNDATION.md` §3.5 states the rule and its single exception in one line:

    Politeness (robots.txt; descriptive User-Agent + contact email; 1 req/2-5s per domain;
    nightly windows); rate limiting/backoff (token bucket per domain; exponential backoff
    on 429/5xx; <=10 req/sec for EDGAR)

P4 TEST CHECKPOINT check 12 turns it into something measurable: *"Run the scraper -> >=2s
between requests to one domain."*

The point of testing it this way rather than connector by connector is that a per-connector
test only covers the connectors somebody remembered to write one for. Yahoo sat at a 1.0s
delay - half the required spacing - through every review this project has had, because
nothing enforced the number and no test asked the question of *all* of them at once. A
connector added next year gets asked automatically.

Written as a property over the class hierarchy, so a subclass that overrides a figure is
checked too.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import packages.ingestion as ingestion_pkg
from packages.ingestion.base import Connector

pytestmark = pytest.mark.invariant

#: The one exception `DATA_FOUNDATION.md` §3.5 names, and the reason it is allowed: SEC
#: publishes a limit of 10 req/s and asks only for a User-Agent. An exception granted by
#: the source is not the same kind of thing as one we granted ourselves.
EXEMPT: dict[str, str] = {
    "edgar": "SEC explicitly permits <=10 req/s with a User-Agent (DATA_FOUNDATION.md §6.4)",
    "manual_csv": "reads a local file; there is no domain to be impolite to",
}

MIN_SPACING_SEC = 2.0


def _network_connectors() -> list[tuple[str, type[Connector]]]:
    """Every concrete `Connector` in `packages.ingestion`, with the module it came from.

    Discovered rather than listed, because a list is a thing you forget to add to - and
    forgetting is the exact failure this file exists to catch.
    """
    found: list[tuple[str, type[Connector]]] = []
    for info in pkgutil.iter_modules(ingestion_pkg.__path__):
        module = importlib.import_module(f"{ingestion_pkg.__name__}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Connector)
                and obj is not Connector
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                found.append((info.name, obj))
    return found


def test_discovery_actually_finds_the_connectors() -> None:
    """A test that silently checks nothing is worse than no test.

    If the walk breaks - a rename, a package move - every assertion below passes over an
    empty list and reports green. So the count is asserted first.
    """
    found = _network_connectors()
    modules = {module for module, _ in found}
    assert len(found) >= 10, f"only found {len(found)} connectors: {sorted(modules)}"
    for expected in ("cbn", "fred", "yahoo", "edgar", "nigeria_data_portal"):
        assert expected in modules, f"{expected} connectors were not discovered"


@pytest.mark.parametrize(
    "module_name,connector", _network_connectors(), ids=lambda v: getattr(v, "__name__", v)
)
def test_requests_to_one_domain_are_at_least_two_seconds_apart(
    module_name: str, connector: type[Connector]
) -> None:
    """The declared spacing, from whichever of the two figures is doing the work.

    A connector can space requests with `politeness_delay_sec`, or by declaring a rate slow
    enough that the token bucket does it, or both. What matters is the interval that comes
    out, so the assertion is on the larger of the two - which is what `PoliteFetcher`
    actually waits, since the delay is applied on top of the bucket.
    """
    if module_name in EXEMPT:
        pytest.skip(f"{module_name}: {EXEMPT[module_name]}")

    from_rate = 1.0 / connector.rate_limit_per_sec if connector.rate_limit_per_sec else float("inf")
    spacing = max(connector.politeness_delay_sec, from_rate)
    assert spacing >= MIN_SPACING_SEC, (
        f"{connector.__name__} spaces requests {spacing:.2f}s apart. "
        f"DATA_FOUNDATION.md §3.5 asks for 2-5s per domain and names EDGAR as the only "
        f"exception. Either raise politeness_delay_sec / lower rate_limit_per_sec, or add "
        f"{module_name!r} to EXEMPT above with the source's own published permission."
    )


@pytest.mark.parametrize(
    "module_name,connector", _network_connectors(), ids=lambda v: getattr(v, "__name__", v)
)
def test_every_connector_declares_a_usable_rate(
    module_name: str, connector: type[Connector]
) -> None:
    """Zero or negative would make `TokenBucket` raise at the first fetch, in production.

    `TokenBucket.__init__` rejects a non-positive rate, which is right - a bucket that
    refills at zero never hands out a token and the connector hangs forever rather than
    failing. But that rejection happens on the first real request, at night, in the
    scheduler. Here costs nothing.
    """
    assert connector.rate_limit_per_sec > 0, (
        f"{connector.__name__} declares rate_limit_per_sec="
        f"{connector.rate_limit_per_sec}, which TokenBucket refuses. A connector cannot "
        f"declare a rate that would stop it fetching at all."
    )
    assert connector.politeness_delay_sec >= 0, (
        f"{connector.__name__} declares a negative politeness_delay_sec, which would be "
        f"read as haste and slept on as a positive number or not at all."
    )
