# ADR-0009 — Object storage for source documents, and the immutability policy

- **Status:** ACCEPTED (policy) · **NOT YET IMPLEMENTED** (bucket, backend)
- **Date:** 2026-09-03
- **Task:** P0.11 · **Closes:** TG17 (policy half). Implementation lands at **P1.0**
  (`StorageBackend` + local disk) and **P3 entry** (remote bucket)
- **Sources:** [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §5.4;
  [docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §4, §8, §14;
  [CLAUDE.md](../../CLAUDE.md) provenance rule

## Context

The provenance rule says every original document must be retrievable **forever**, including
after the source website has been redesigned or has vanished —
[TEAM_BRIEF.md](../../TEAM_BRIEF.md) Part 3 names that as a live risk for the Nigerian sources
specifically, which is where the moat is.

**Nobody owned this.** [docs/10](../10_PRE_BUILD_CORRECTIONS.md) §5.4: four index tables say
TG17 "lands in P0"; P0's ten tasks, seventeen checks and exit criteria contain no bucket task,
and searching `TG17` across both roadmaps, the user stories and the test strategy returns
nothing. Worse, the two halves of `02` disagree: §4 says local disk is fine for P0–P8, while §8
and §14 assume an off-site content-hash bucket from P0. **Under one reading the entire P3/P4
extraction campaign — the most expensive human work in the project — sits on one Windows
laptop**, whose disk is currently unencrypted and holds both backup copies.

Deciding this in P0 rather than P3 matters because **P3.1 assumes the storage already exists**.
A phase that depends on infrastructure nobody scheduled stops on the morning it starts.

## Decision

**The policy is decided now and binds every phase. The backend is built in two steps.**

**The policy — true of every backend, from the first file:**

1. **Key by content hash, never by name:** `documents/sha256/<64-hex>.pdf`, flat. Deduplication
   is automatic and the key itself proves the bytes never changed.
2. **Write once. Never overwrite, never delete.** A reissued or corrected report is a **new
   object**, exactly as a corrected figure is a new row ([CLAUDE.md](../../CLAUDE.md): no silent
   overwrites). There is no code path that deletes a document, in any phase.
3. **Metadata in `source_documents`, bytes in storage.** `source_documents.sha256` is
   `CHAR(64) NOT NULL UNIQUE` and *is* the content address — the join between the two halves.
4. **Verification is scheduled, not assumed.** `scripts/verify_documents.py` re-hashes every
   stored object against its row, quarterly, alongside the restore drill
   ([docs/REVIEW_CADENCE.md](../REVIEW_CADENCE.md)). Storage that is never read back is storage
   nobody knows is intact.
5. **Where the provider offers Object Lock and versioning, both are on, with no expiry rule
   ever.** That is what turns "never overwrite" from a discipline into a guarantee — the same
   argument [docs/08](../08_DATA_CONTRACTS.md) §2.16 makes for enforcing the no-update rule with
   a trigger rather than in review, because "the same person at 1am has `psql`".

**The backend, in two steps:**

| Step | Phase | What |
|---|---|---|
| **Local disk** | **P1.0** | `StorageBackend` interface + `LocalDiskBackend` writing `data/documents/sha256/<hash>`, write-once (refuse to replace an existing key). Git-ignored; covered by `scripts/backup.ps1` |
| **Remote bucket** | **P3 entry** | The same interface, a remote backend. Buckets `quant-docs-prod` / `quant-docs-dev` |

**Provider: Backblaze B2** — ~$0.006/GB/mo, so 16 GB ≈ **$0.10/month**
([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §5.4).

**The interface is the decision that matters; the provider is not.** Because everything goes
through `StorageBackend`, switching providers is a class, not a migration — which is why it is
safe to defer the account and cheap to change if B2 disappoints.

## Consequences

- **P1.0 is unblocked and P3.1's assumption becomes true**, which was the point.
- **P0 through P1 run on local disk only.** Both copies are on one physical disk (see
  [ADR-0008](0008-neon-managed-postgres.md) and the 3-2-1 warning `scripts/backup.ps1` prints).
  Until the remote bucket exists, **document loss is a single disk failure away**, and the PDFs
  are the part that cannot be re-fetched once a Nigerian source rotates its URLs.
- **A B2 account must be created before P3 collects documents at scale.** That is an owner
  action with a payment method attached; it is not something the build can do for itself. It
  belongs in P3's entry criteria, and it is listed in
  [docs/00_START_HERE.md](../00_START_HERE.md) §6's next actions.
- The no-delete rule means storage only grows. At the sizing in
  [docs/02](../02_INFRASTRUCTURE.md) §3.2 (~16 GB of PDFs) that is financially irrelevant for
  the life of the project, so there is never a reason to trade the guarantee for cost.
- **Immutable storage and a data-subject erasure request will collide at P12.** Source documents
  are published company filings rather than personal data, so the conflict is expected to be
  narrow — but it must be answered in P12.1 (data-subject rights), not discovered there.
  **[NEEDS VERIFICATION]** against the NDPA.

## Alternatives rejected

**Cloudflare R2** ([docs/02](../02_INFRASTRUCTURE.md) §4's recommendation from P9) — ~$0.015/GB/mo
with **zero egress**. *For:* egress-free re-reads matter, because re-parsing the whole corpus
after an extraction-prompt improvement is a routine P4 operation, not an edge case. *Against:*
2.5× the storage price, and at 16 GB both numbers are noise. **This is the closest call here.**
If re-parsing turns out to be frequent enough that egress shows up on a bill, R2 is the swap,
and the `StorageBackend` interface is what makes it an afternoon.

**AWS S3** — works, mature, and the egress charges are the annoyance. No advantage at this scale
that the other two do not have more cheaply.

**Local disk forever** — free, and genuinely sufficient for P0–P8 by
[docs/02](../02_INFRASTRUCTURE.md) §4's own reading. Rejected because it makes the *one*
unrecoverable failure in the project ([PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9.3: the
dataset is the asset) depend on one laptop's disk.

**Documents in the database as `BYTEA`** — one backup, transactional consistency with the
metadata. Rejected: it inflates every `pg_dump` by ~16 GB, making the backup slow enough to skip
and the restore drill painful enough to stop running, which trades a small risk for the failure
mode that actually kills datasets.
