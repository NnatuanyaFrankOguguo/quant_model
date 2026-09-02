"""0004 - seed `data_sources`, the licensing register (P0.10 / TG5).

Revision ID: 0004_p0_seed_data_sources
Revises: 0003_p0_seed_system_config
Create Date: 2026-09-01

`CLAUDE.md` hard rule: *"Data licensing before ingestion — confirm redistribution rights
before a source enters the dataset."* `PROJECT_CONTEXT.md` §9.3 calls the redistribution
question "the one that kills deals". `docs/08_DATA_CONTRACTS.md` §2.2 makes
`redistribution_allowed` `NOT NULL` because **that is the whole mechanism**: it forces an
answer at registration time, and a connector whose source row is absent or incomplete
cannot be enabled.

One row per source `DATA_FOUNDATION.md` §2–3 actually verifies: FRED, SEC EDGAR, NGX, CBN,
NBS, DMO.

**Every row is seeded `redistribution_allowed = false`, and that is a deliberate reading,
not laziness.** `DATA_FOUNDATION.md` §6.3–6.4 establishes what this project has actually
verified: that scraping public filings and public agency data for **personal use** is
low-risk, that NGX market data is governed by a Data Agreement restricting redistribution,
and that *"for public launch prefer licensed/API paths for anything you redistribute"*. It
verifies **access**, not **redistribution**. For no source in the document set is there an
affirmative, reviewed statement that this project may re-serve the data — so the
conservative answer is the only honest one, and each row's `notes` says exactly what the
document does and does not establish.

This costs nothing today: `false` means "may not be re-served raw", and P0 serves nobody
outside the family. It becomes load-bearing at public launch, which is when a row flipped
to `true` on a guess would have become a liability. `08` §2.2's illustrative sample table
shows EDGAR and FRED as `true`; §1.8 states the sample numbers are illustrative, so it is
not treated as a determination. Raising any of these to `true` is a one-row change with a
new `terms_reviewed_on` and a reviewer who has read the linked terms.

`terms_url` is populated only where the URL is known-good. A guessed URL in a compliance
register is worse than a null one, because it looks reviewed.

`downgrade()` deletes exactly the six `source_name` values inserted here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0004_p0_seed_data_sources"
down_revision: str | None = "0003_p0_seed_system_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEWED_ON = date(2026, 9, 1)
REVIEWED_BY = "nnatuanyafrankoguguo"

# The sentence appended to every note, so the basis of `false` travels with the row.
CONSERVATIVE = (
    "redistribution_allowed=false is the conservative default per CLAUDE.md's "
    "'data licensing before ingestion' rule: DATA_FOUNDATION.md verifies access terms, not "
    "redistribution rights. Raise to true only after a reviewer reads the terms and updates "
    "terms_reviewed_on."
)

SEED_ROWS: list[dict[str, Any]] = [
    {
        "source_name": "FRED",
        "base_url": "https://api.stlouisfed.org/fred",
        "licence_type": "public_api_attribution",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Federal Reserve Bank of St. Louis (FRED)",
        "terms_url": "https://fred.stlouisfed.org/legal/",
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": None,
        "notes": (
            "DATA_FOUNDATION.md §2B/§2C: free API key, ~94 World Bank Nigeria series, ALFRED "
            "vintage endpoints (which supply both the observation date and realtime_start, "
            "i.e. macro_observations.known_as_of, directly — most sources will not). The "
            "document does not state a request-rate limit, so rate_limit_per_sec is left "
            "NULL rather than guessed; the connector must set its own polite default. FRED "
            "redistributes third-party series alongside public-domain federal ones and its "
            "terms differ per series, so a blanket 'true' would be wrong even if generous. "
            + CONSERVATIVE
        ),
    },
    {
        "source_name": "SEC EDGAR",
        "base_url": "https://data.sec.gov",
        "licence_type": "us_federal_public",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: U.S. Securities and Exchange Commission (EDGAR)",
        "terms_url": None,
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": 10,
        "notes": (
            "DATA_FOUNDATION.md §2C: companyfacts / companyconcept / submissions, free and "
            "keyless, MANDATORY descriptive User-Agent (name + email) — omitting it is the "
            "documented cause of 403s. Rate limit 10 req/sec is stated explicitly and is the "
            "one verified numeric limit in the register; exceeding it earns a 403/429 and a "
            "~10-minute IP block, so use ~0.12s spacing. CIKs zero-pad to 10 digits. §6.4 "
            "records that EDGAR explicitly permits automated access — that is an ACCESS "
            "permission and says nothing about re-serving the data. Likely the most "
            "permissive source here (US federal works), but no reviewed determination "
            "exists. terms_url is NULL because no specific SEC terms page has been read and "
            "recorded. " + CONSERVATIVE
        ),
    },
    {
        "source_name": "NGX",
        "base_url": "https://ngxgroup.com",
        "licence_type": "ngx_data_agreement",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Nigerian Exchange Group (NGX)",
        "terms_url": None,
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": None,
        "notes": (
            "THE ROW THAT MATTERS. DATA_FOUNDATION.md §6.3: NGX Market Data is governed by a "
            "Data Agreement restricting redistribution; a public product must either licence "
            "redistribution, present only derived/transformed analytics, or honour the "
            "delays and attribution the source permits. NGX data may be used internally and "
            "MAY NOT BE RE-SERVED RAW — derived analytics only. This single row covers two "
            "distinct properties with different terms and that is a known simplification: "
            "(a) X-Compliance disclosure PDFs at doclib.ngxgroup.com, publicly posted "
            "regulatory filings, free to view, low-risk to scrape politely; (b) the paid NGX "
            "Market Data API (marketdataapiv3.ngxgroup.com), no free tier, Data Agreement "
            "terms. P1/P2 should split this into two rows when the first NGX connector is "
            "built, because the licence answer is genuinely different for each. terms_url is "
            "NULL: the Data Agreement is a contract, not a public page. false here is not "
            "conservatism, it is the documented answer."
        ),
    },
    {
        "source_name": "CBN",
        "base_url": "https://www.cbn.gov.ng",
        "licence_type": "ng_public_agency",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Central Bank of Nigeria",
        "terms_url": None,
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": None,
        "notes": (
            "DATA_FOUNDATION.md §2B: MPR and MPC decisions/calendar, NFEM volume-weighted "
            "official FX rate, money-market indicators, T-bill auctions and stop rates, "
            "money supply, reserves. HTML with 'Export to Excel' plus the Statistics "
            "Database LiveShop; NO REST API, so this is scrape-and-parse and every fetch "
            "must be cached as a source_document. The 364-day NTB stop rate from here is the "
            "risk-free series the backtest gate compares against (docs/10 §3.3). No "
            "published rate limit and no terms page reviewed. " + CONSERVATIVE
        ),
    },
    {
        "source_name": "NBS",
        "base_url": "https://nigerianstat.gov.ng",
        "licence_type": "ng_public_agency",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: National Bureau of Statistics, Nigeria",
        "terms_url": None,
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": None,
        "notes": (
            "DATA_FOUNDATION.md §2B: CPI, GDP, unemployment, capital importation, trade, "
            "NLSS/GHS microdata. PDF and Excel, no REST API. CPI is published mid-month for "
            "the prior month — that lag is macro_series.expected_lag_days and it is why "
            "macro_observations.known_as_of exists at all. CPI was REBASED to a 2024 base "
            "(2023 weights, 934 varieties, COICOP 2018) and GDP to 2019, backcast to 1981: "
            "rebasing changes past values, so macro_series.base_period is part of the series "
            "identity and revisions must be stored as new vintages, never overwritten. No "
            "published rate limit and no terms page reviewed. " + CONSERVATIVE
        ),
    },
    {
        "source_name": "DMO",
        "base_url": "https://www.dmo.gov.ng",
        "licence_type": "ng_public_agency",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Debt Management Office, Nigeria",
        "terms_url": None,
        "terms_reviewed_on": REVIEWED_ON,
        "reviewed_by": REVIEWED_BY,
        "rate_limit_per_sec": None,
        "notes": (
            "DATA_FOUNDATION.md §2B: FGN bond auction results, FGN Savings Bond offers and "
            "allotments, Eurobond closing prices and yields, total public debt. PDFs served "
            "through docman; monthly cadence. No REST API, no published rate limit, no terms "
            "page reviewed. " + CONSERVATIVE
        ),
    },
]


data_sources_table = sa.table(
    "data_sources",
    sa.column("source_name", sa.Text()),
    sa.column("base_url", sa.Text()),
    sa.column("licence_type", sa.Text()),
    sa.column("redistribution_allowed", sa.Boolean()),
    sa.column("attribution_required", sa.Boolean()),
    sa.column("attribution_text", sa.Text()),
    sa.column("terms_url", sa.Text()),
    sa.column("terms_reviewed_on", sa.Date()),
    sa.column("reviewed_by", sa.Text()),
    sa.column("rate_limit_per_sec", sa.Numeric()),
    sa.column("notes", sa.Text()),
)


def upgrade() -> None:
    op.bulk_insert(data_sources_table, SEED_ROWS)


def downgrade() -> None:
    names = [row["source_name"] for row in SEED_ROWS]
    op.execute(data_sources_table.delete().where(data_sources_table.c.source_name.in_(names)))
