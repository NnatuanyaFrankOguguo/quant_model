# ADR-0006 — Streamlit is a thin client

- **Status:** ACCEPTED
- **Date:** 2026-08-30
- **Also known as:** AD-3
- **Source:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0006 — copied verbatim,
  with the enforcement detail expanded from
  [docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §2.3 and §7.

## Context

`apps/streamlit/` is the only user surface until P9. The tempting shortcut is for it to query
the database directly — it is a Python process with the connection string already in scope.

## Decision

Streamlit renders what the API returns. **No SQL, no arithmetic, no business logic in
`apps/streamlit/`.** If you ever find yourself putting a connection string into
`apps/streamlit/`, that is the defect.

## Consequences

- The P9 frontend swap is a re-skin, not a rebuild.
- Everything the UI shows has already passed the mode gate, the response-type assertion and
  the audit log, because it came through the API. A Streamlit page that queries the database
  bypasses all five compliance mechanisms at once.
- **Enforced by an import-linter contract and a CI grep**, not by discipline. The contract
  (`packages` must not import `apps` or `services`) is already in `pyproject.toml`; the
  `lint-imports` CI stage is commented out in `.github/workflows/ci.yml` until `apps/` and
  `packages/` contain modules to analyse — turned on at P1 per
  [docs/10](../10_PRE_BUILD_CORRECTIONS.md) §6.1, which defers import-linter "to when the
  directories exist".

## Alternatives rejected

- **Streamlit talks to the database directly for v0.x, and is rewritten against the API at
  P9.** Rejected: it means the mode gate is unexercised for nine phases, and every query in the
  UI is a second, untested implementation of something the API already does. It also makes the
  P9 swap a rewrite rather than a re-skin.
- **Streamlit as the shipped v1.0 product** — rejected in
  [ADR-0004](0004-python-everywhere-except-v1-frontend.md).
