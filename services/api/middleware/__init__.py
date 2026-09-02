"""The compliance middleware stack.

Order matters and is asserted by ``tests/compliance/test_middleware_order.py``.
Starlette runs the *last* added middleware outermost, so ``main.py`` adds
:class:`~services.api.middleware.mode.ModeMiddleware` first and
:class:`~services.api.middleware.audit.AuditMiddleware` second:

    ServerError -> Audit -> Mode -> ExceptionMiddleware -> router -> guarded endpoint

Audit sits outside Mode so it records requests that never reach a route (404s,
405s) and requests whose handler raised. Mode sits outside the router so a request
cannot reach a handler without a derived mode - the "applied globally, endpoints
opt in to nothing" option in ``docs/01_ARCHITECTURE.md`` 3, chosen because a
forgotten decorator is an unguarded endpoint and nothing detects it.

Mechanisms 3 and 4 are not middleware. They run in
:mod:`services.api.middleware.assert_response`, at the route layer, because by the
time bytes reach a middleware the Python type is gone and there is nothing left to
assert on.
"""
