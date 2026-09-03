# Architecture Decision Records

One file per non-obvious decision, named `NNNN-kebab-title.md`, each with **Context**,
**Decision**, **Consequences**, and **Alternatives rejected**
([OPERATIONS.md](../../OPERATIONS.md) §3.1).

## The rule that matters most

**An accepted ADR is the answer to a spec conflict, not a reason to stop.** [CLAUDE.md](../../CLAUDE.md)
is explicit: *"'Stop and ask on a conflict with SPEC.md' means check for an ADR first."* These
records sit second in the precedence order — below
[docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md), above everything else. When
one of them contradicts `SPEC.md`, the ADR wins on the point it decides, and only on that point.

## The log

| ADR | Decision | Status | Closes / amends |
|---|---|---|---|
| [0001](0001-storage-engine-postgresql.md) | PostgreSQL from day one — not DuckDB, not engine-agnostic | ACCEPTED | TG9; amended by 0008 |
| [0002](0002-packages-scheduler.md) | `/packages/scheduler` added to SPEC §3.1's monorepo | ACCEPTED | TG8 |
| [0003](0003-auth-hashed-bearer-tokens.md) | Hashed bearer tokens in Postgres now; hosted IdP at P9 | ACCEPTED | TG3 |
| [0004](0004-python-everywhere-except-v1-frontend.md) | Python everywhere except the v1.0 frontend | ACCEPTED | AD-1 |
| [0005](0005-fastapi-in-p0-not-p9.md) | FastAPI stands up in P0, not P9 — a deliberate deviation from SPEC §4.2's ordering | ACCEPTED | AD-2 |
| [0006](0006-streamlit-is-a-thin-client.md) | Streamlit is a thin client; business logic in a callback is a defect | ACCEPTED | AD-3 |
| [0007](0007-multi-user-from-day-one.md) | Multi-user from day one; everything keyed by principal | ACCEPTED | AD-4 |
| [0008](0008-neon-managed-postgres.md) | Neon managed PostgreSQL, not local Docker | ACCEPTED | Amends 0001; reframes TG19 |
| [0009](0009-object-storage-and-immutability.md) | Content-addressed, write-once document storage; local disk at P1, B2 at P3 | ACCEPTED (policy), **not implemented** | TG17 (P0.11) |
| [0010](0010-bulk-export-via-exportview.md) | Bulk export goes through a versioned `ExportView`, never a raw `SELECT` | ACCEPTED (design), **built at P12** | TG22 |

0002 and 0004–0007 were already written in [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9
and are copied here rather than rewritten. 0001, 0003, 0008, 0009 and 0010 were written during P0.

**0009 and 0010 decide things P0 does not build.** That is deliberate, and it is the direct
answer to [docs/10](../10_PRE_BUILD_CORRECTIONS.md)'s central finding: work recorded in an
appendix and never written into a roadmap does not get done. Both decisions are cheap today and
expensive to retrofit — object storage because P3.1 already assumes it exists, bulk export
because its obvious implementation defeats three of the five compliance mechanisms.

## When to write one

When you decide something that is expensive to reverse, contradicts a document, or that a
reasonable person would re-litigate later. [docs/00_START_HERE.md](../00_START_HERE.md) §12:
*"Six months later you will not remember why."*

Also write one when you **keep** a decision whose reasoning has expired — the value of this
directory is as much in stopping a stale decision from surviving on inertia as in stopping a
settled one from being reopened.

## Template

```markdown
# ADR-NNNN — Title in one line

- **Status:** PROPOSED | ACCEPTED | SUPERSEDED by ADR-MMMM
- **Date:** YYYY-MM-DD
- **Closes:** TGn, or —
- **Sources:** the documents this decision reads or contradicts

## Context
What forced the decision. Include the contradiction or constraint verbatim where one exists.

## Decision
What we are doing. Present tense, no hedging.

## Consequences
What this makes easy, what it makes hard, and what it costs. **Write the costs down** — an ADR
with only benefits is marketing, and it is the honest cost list that makes the record worth
re-reading when the decision starts to hurt.

## Alternatives rejected
Each one, with what it was good for and why it lost. Someone will propose it again.
```

Mark anything not confirmed by a source document or a direct check as **[NEEDS VERIFICATION]**
([docs/00_START_HERE.md](../00_START_HERE.md) §11) rather than asserting it.
