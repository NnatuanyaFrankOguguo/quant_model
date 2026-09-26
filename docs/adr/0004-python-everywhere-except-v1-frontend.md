# ADR-0004 — Python everywhere except the v1.0 frontend

- **Status:** ACCEPTED
- **Date:** 2026-08-30
- **Also known as:** AD-1
- **Source:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0004 — copied verbatim,
  with the note at the end added from
  [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §1.

## Context

The stack has to be chosen once, at the point where the packages are scaffolded, because a
second toolchain is a second CI configuration, a second dependency manager and a second set of
security updates for the life of the project.

## Decision

All **14** packages ([SPEC.md](../../SPEC.md) §3.1's thirteen plus `/packages/scheduler` per
[ADR-0002](0002-packages-scheduler.md)) and the API are Python. The Next.js frontend at P9 is
the only non-Python component.

## Consequences

One TypeScript toolchain to maintain, from P9 only.

**Note added 2026-09-01:** Node is a P9 prerequisite that no planning document mentioned
([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §1). It is installed on the build machine
(v24.14.0) and belongs in P9's entry criteria so it is not discovered at P9.

## Alternatives rejected

An **all-Python frontend** (Reflex, NiceGUI, or Streamlit as the shipped product). Rejected
because [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9's B2B customers touch the frontend,
and Streamlit does not read as a product. It remains correct for v0.x, where the only user is
the builder — see [ADR-0006](0006-streamlit-is-a-thin-client.md).
