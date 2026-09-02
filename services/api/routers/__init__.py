"""Mechanism 2 of five - physically separate router trees.

``docs/08_DATA_CONTRACTS.md`` 7: *"Routers are physically separate module trees,
not one router with an ``if``."* Advice-generating code is imported by
:mod:`services.api.routers.personal` and is not reachable from
:mod:`services.api.routers.public`. The point is that the separation is
structural - a grep for what the public tree imports is a complete answer - rather
than a conditional somebody can invert during a refactor.

Both trees are versioned: ``/v1/public/*`` and ``/v1/personal/*``
(``docs/10_PRE_BUILD_CORRECTIONS.md`` 6.5, *"free today, a breaking change
later"*). ``/health`` is deliberately unversioned - it is infrastructure, not API
surface, and a load balancer should not have to track a version to check liveness.
"""

from __future__ import annotations

#: Every API path carries this prefix. `/health` is the one exception.
API_V1 = "/v1"
