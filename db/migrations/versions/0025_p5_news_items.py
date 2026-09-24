"""0025 - news_items: an article is a dated, versioned, content-addressed row. P5.1.

Revision ID: 0025_p5_news_items
Revises: 0024_p3_heartbeat_interval
Create Date: 2026-09-24

`docs/03` P5.1 and `docs/08` §2.6. The first table in this schema that holds *text* rather
than a figure, and the reason it still needs every discipline the figure tables have is that
a headline is an input to a decision: P5.2 tags it to a security, P5.3 scores it, P5.4 puts
it in a brief, and P7 will read the score as a feature. A news row that can be silently
rewritten, silently duplicated, or silently back-dated is a feature that lies.

**Why RSS at all.** `DATA_FOUNDATION.md` §D checked the paid news APIs and the finding is
explicit: *"None explicitly confirm Nigerian-source coverage; Finnhub free is US-only; Alpha
Vantage lists only NA/Europe/APAC."* Free RSS is not the budget option for this market, it is
the option that covers it.

## The three seeded sources, and the two the plan names that are not here

`packages/ingestion/rss.py` implements Nairametrics, BusinessDay and Punch, and each gets a
`data_sources` row below. `docs/03` P5.1 also names Proshare and Reuters Africa; both were
checked against the live sites on 2026-09-24 and neither is ingestible today:

* **Proshare** publishes no feed. `proshare.co` carries no `<link rel="alternate">`, no RSS
  icon and no `/rss`, `/feed` path - both answer the site's own 404 page with HTTP 200,
  which is itself worth knowing, because a naive fetcher would store the 404 page forever
  and report success. The former domain `www.proshareng.com` no longer presents a valid
  certificate.
* **Reuters** disallows us outright. `www.reuters.com/robots.txt` ends with
  `# Block all other bots` / `User-agent: *` / `Allow: /plus/` / `Disallow: /`, so every
  path except `/plus/` is refused to this client. `PoliteFetcher` would raise
  `RobotsRefusedError` before the first request, which is the correct outcome and not one to
  route around.

`TheCable`, the obvious substitute from `DATA_FOUNDATION.md` §A, answers 403 to our
User-Agent. A 403 is terminal in `polite.py` and is never retried - repeating it is how a
refusal becomes an IP block - so it is recorded here and not implemented.

## Where this deviates from `docs/08` §2.6, and why each deviation is load-bearing

The contract's DDL is seven columns and one constraint:

    url TEXT NOT NULL UNIQUE, headline, body, published_at, retrieved_at, content_hash

**`UNIQUE (url)` is dropped.** It makes an edited article an UPDATE, which is the one write
`CLAUDE.md` forbids outright and which the `no_update` trigger below rejects. Nigerian
newsrooms correct headlines after publication - the evening version of a morning story is
routinely a different sentence - and under `UNIQUE (url)` the correction would either
destroy what the market actually read at 09:00 or be dropped on the floor. Identity is
`(data_source_id, item_key, content_hash)` instead: same source, same article, same words
is one row; same article, *different* words is a second row, and the earlier text survives.

**`url_canonical` joins `url`.** The link a feed serves is not a stable identifier. Every
Punch link arrives with `?utm_source=rss.punchng.com&utm_medium=web` attached, and a
campaign parameter that changes would re-insert the entire feed as new articles. `url` is
what the feed said, kept for provenance; `url_canonical` is what identity is computed from,
and `packages/ingestion/rss.py:canonical_url` is the single place the rule lives.

**`item_key` is the feed's own `<guid>` when it has one.** WordPress serves
`<guid isPermaLink="false">https://nairametrics.com/?p=550279</guid>` - a post id that
survives a slug rewrite, which is exactly the rename that would otherwise duplicate an
article. A guid that is itself a URL is canonicalised first, because Punch's guid carries
the same campaign parameters its link does.

**`content_hash` is over the text, not over the row.** SHA-256 of the normalised headline
and body and nothing else, so an identical wire story republished by two outlets carries the
same hash under two `data_source_id`s. The rows are deliberately *not* merged - attribution
and the licence that governs our copy are per publisher - but `ix_news_items_content_hash`
makes "this is the same story we already have" a single indexed lookup, which is what P5.4
needs so a brief does not print one event three times.

**`source_document_id` is NOT NULL.** `CLAUDE.md`: provenance on every figure. The feed XML
this row was parsed out of is stored by `store_raw` before `parse()` ever runs, so every
headline can be shown the exact bytes it came from and every row can be re-derived after a
parser fix without re-fetching a feed that has long since dropped the item.

**`known_as_of` is generated, not written.** `docs/08` §1.3's point-in-time rule is that a
feature joins on `known_as_of <= decision_date`. For an article the knowledge date is the
publication date, so a hand-written column would be a copy of `published_at` that some
future writer could get wrong once. It is a stored generated column instead, so the two
cannot disagree:

    (published_at AT TIME ZONE INTERVAL '01:00')::date

`AT TIME ZONE INTERVAL` rather than `AT TIME ZONE 'Africa/Lagos'` because PostgreSQL marks
the named-zone form STABLE - the zone database can change - and a generated column requires
an IMMUTABLE expression. The fixed hour is correct here and is asserted by
`tests/unit/test_schema_conventions.py:test_wat_is_utc_plus_one_with_no_daylight_saving`:
West Africa Time is UTC+1 all year with no daylight saving. `docs/08` §1.3 is why the offset
is applied at all rather than taking the UTC date - a plain `DATE` in this schema is a
calendar date in the market's own local time, and 23:30 UTC is already tomorrow in Lagos.

## The constraints, and the one that is written the long way on purpose

`published_before_retrieved` is the point-in-time guard: we cannot have fetched an article
before it existed, so a row claiming otherwise is a clock error or a scheduled post, and
admitting it would let a brief announce news that has not happened. The parser drops such
items with a warning, and this is the floor under the parser, because `docs/08` §2.16's
argument applies here too - application code can be bypassed at 1am by a person with `psql`.

`body_is_absent_or_present` is written `body IS NULL OR btrim(body) <> ''` rather than
`btrim(body) <> ''`. Migration `0021` is this repository's record of what the short form
costs: a CHECK rejects a row only when its predicate is FALSE, and a predicate over a NULL
column evaluates to NULL, so the bare form admits every NULL it was written to think about.
`body` is legitimately NULL - a feed that carries no summary carries no summary, and
`SPEC.md` §4.1's null rule says absent is absent - so NULL is admitted explicitly, and the
empty string, which is what a feed actually sends for an absent summary, is not.

## `expected_run_interval_hours = 3`, and what it assumes

`0024` seeds this column so `scripts/check_heartbeat.py` has something to measure silence
against, and NULL there means "nothing is watching this". These three sources are seeded
with 3 hours, which is the **hourly** cadence `packages/ingestion/rss.py` asks for plus the
same two-hour grace `0024` and `scripts/backup.ps1` already use.

Hourly is not a preference, it is what the feed windows force. BusinessDay's feed carried
**five** items when it was measured, Nairametrics twenty, Punch thirty; at those publishers'
volumes a five-item window empties in about an hour, and anything slower silently loses
articles that were never ours to re-request - RSS has no backfill. Two of the three send
`ETag` and `Last-Modified`, so most of those polls cost a 304 and no body at all.

**If the schedule lands at anything other than hourly, this number is wrong** and the
heartbeat will either cry wolf or stay quiet through an outage. It is one `UPDATE` and it
belongs in the same change as the cron entry.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0025_p5_news_items"
down_revision: str | None = "0024_p3_heartbeat_interval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "news_items"

#: The hourly cadence `packages/ingestion/rss.py` asks for, plus `0024`'s two-hour grace.
#: A deadline equal to the period fires on every ordinary jitter.
HOURLY_HEARTBEAT_HOURS = 3

#: A published limit exists for none of these hosts and none of them publishes a
#: `Crawl-delay`, so this is the figure we chose rather than one we were given:
#: `DATA_FOUNDATION.md` §3.5's 1 request per 2-5 seconds per domain, at the slow end.
#: It matches `RssNewsConnector.rate_limit_per_sec`, and `register()` keeps the two
#: equal on every run.
RATE_PER_SEC = 0.5

data_sources_table = sa.table(
    "data_sources",
    sa.column("source_name", sa.Text),
    sa.column("base_url", sa.Text),
    sa.column("licence_type", sa.Text),
    sa.column("redistribution_allowed", sa.Boolean),
    sa.column("attribution_required", sa.Boolean),
    sa.column("attribution_text", sa.Text),
    sa.column("terms_url", sa.Text),
    sa.column("terms_reviewed_on", sa.Date),
    sa.column("reviewed_by", sa.Text),
    sa.column("rate_limit_per_sec", sa.Numeric),
    sa.column("notes", sa.Text),
    sa.column("expected_run_interval_hours", sa.Integer),
)

#: One row per publisher, not per feed. The licence question - may we republish this? - is
#: answered by the publisher, and a second feed from the same masthead does not re-open it.
#: Which feed a given article came from is recorded by its `source_documents` row, whose
#: `url` is the feed URL that was fetched.
#:
#: `redistribution_allowed` is **False** for all three, and this is the conservative answer
#: rather than a researched permission. An RSS feed is an invitation to read and to link; it
#: is not a copyright licence, and a headline and standfirst are the publisher's protected
#: text. `DataSourceLicence`'s own docstring sets the rule: when the terms are unclear the
#: answer is False plus a note saying why. `PROJECT_CONTEXT.md` §9.3 calls redistribution
#: "the question that kills deals", and serving these summaries to the public tier would be
#: a decision nobody has taken.
#:
#: `terms_url` is NULL for two of the three, on `0022`'s reasoning: only BusinessDay
#: publishes a copyright page, and inventing a URL for the other two would be worse than
#: admitting there isn't one. Both link a privacy policy, which governs personal data and
#: says nothing about reuse.
NEWS_SOURCES: list[dict[str, object]] = [
    {
        "source_name": "Nairametrics",
        "base_url": "https://nairametrics.com",
        "licence_type": "news_publisher_copyright",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Nairametrics",
        "terms_url": None,
        "terms_reviewed_on": date(2026, 9, 24),
        "reviewed_by": "nnatuanyafrankoguguo",
        "rate_limit_per_sec": RATE_PER_SEC,
        "expected_run_interval_hours": HOURLY_HEARTBEAT_HOURS,
        "notes": (
            "RSS at https://nairametrics.com/feed/ (WordPress, 20 items, sy:updatePeriod "
            "hourly), named as a starting point by DATA_FOUNDATION.md D. robots.txt is "
            "`User-agent: * / Disallow:` - everything allowed, no Crawl-delay - checked "
            "2026-09-24. Sends ETag and Last-Modified, so the connector revalidates. No "
            "terms-of-use or copyright page is linked from the site; only a privacy "
            "policy (https://nairametrics.com/privacy-policy), which governs personal "
            "data and not reuse, so terms_url is NULL rather than invented. Headlines and "
            "summaries are the publisher's copyright: redistribution NOT permitted."
        ),
    },
    {
        "source_name": "BusinessDay",
        "base_url": "https://businessday.ng",
        "licence_type": "news_publisher_copyright",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: BusinessDay NG",
        "terms_url": "https://businessday.ng/copyright/",
        "terms_reviewed_on": date(2026, 9, 24),
        "reviewed_by": "nnatuanyafrankoguguo",
        "rate_limit_per_sec": RATE_PER_SEC,
        "expected_run_interval_hours": HOURLY_HEARTBEAT_HOURS,
        "notes": (
            "RSS at https://businessday.ng/feed/ (WordPress), named by DATA_FOUNDATION.md "
            "D. robots.txt allows the feed - it disallows /search/, /?s=, wp-login and "
            "some AMP query shapes only - and publishes no Crawl-delay; checked "
            "2026-09-24. Sends ETag and Last-Modified. The feed carried FIVE items when "
            "measured, which is why the connector asks to be run hourly: at this "
            "publisher's volume a five-item window turns over in about an hour and RSS "
            "has no backfill. Redistribution NOT permitted - see the copyright page."
        ),
    },
    {
        "source_name": "Punch",
        "base_url": "https://punchng.com",
        "licence_type": "news_publisher_copyright",
        "redistribution_allowed": False,
        "attribution_required": True,
        "attribution_text": "Source: Punch Newspapers",
        "terms_url": None,
        "terms_reviewed_on": date(2026, 9, 24),
        "reviewed_by": "nnatuanyafrankoguguo",
        "rate_limit_per_sec": RATE_PER_SEC,
        "expected_run_interval_hours": HOURLY_HEARTBEAT_HOURS,
        "notes": (
            "docs/03 P5.1 names 'Punch business'. The site declares that feed at "
            "https://punchng.com/topics/business/feed/, which 302s to "
            "https://rss.punchng.com/v1/category/latest_news - the RSS host drops the "
            "category. The category-scoped URL exists "
            "(https://rss.punchng.com/v1/category/business) and served a well-formed feed "
            "with ZERO items on 2026-09-24, which is the silent-failure signature this "
            "project keeps finding, so the general feed is ingested and scope is left to "
            "P5.2's tagging. robots.txt on both punchng.com and rss.punchng.com allows "
            "everything and publishes no Crawl-delay. Sends no ETag and no Last-Modified "
            "and Cache-Control: no-store, so every poll transfers the body. "
            "Redistribution NOT permitted."
        ),
    },
]


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        # The feed's own identifier for this article: its <guid>, canonicalised when that
        # is a URL, and the canonical link when the feed serves no guid.
        sa.Column("item_key", sa.Text(), nullable=False),
        # As the feed served it. Provenance, never identity.
        sa.Column("url", sa.Text(), nullable=False),
        # Identity. Tracking parameters removed, host lowercased - see rss.canonical_url.
        sa.Column("url_canonical", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        # The feed's summary with markup removed. NULL when the feed carried none; never
        # the empty string, which is what a feed actually sends for an absent summary.
        sa.Column("body", sa.Text(), nullable=True),
        # The feed's own category labels, verbatim. Empty when the feed listed none - a set
        # of labels is not a figure, so the empty set is the accurate value and not a
        # fabricated zero.
        sa.Column(
            "categories",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        # When the world learned it. The business timestamp AND the knowledge instant.
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        # When we fetched it. Provenance and cache invalidation only (docs/08 1.3).
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        # SHA-256 of the normalised headline and body. The version key, and the
        # cross-publisher duplicate detector.
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "known_as_of",
            sa.Date(),
            sa.Computed("(published_at AT TIME ZONE INTERVAL '01:00')::date", persisted=True),
            nullable=False,
        ),
        # Same source, same article, same words - once. Different words are a new row.
        sa.UniqueConstraint(
            "data_source_id", "item_key", "content_hash", name="news_item_version_is_unique"
        ),
        sa.CheckConstraint("btrim(headline) <> ''", name="news_headline_is_not_blank"),
        # `IS NULL OR`, never a bare predicate: migration 0021 is the record of a CHECK
        # that admitted every NULL because a NULL predicate is not FALSE. NULL is a
        # legitimate value here and is admitted on purpose; '' is not.
        sa.CheckConstraint(
            "body IS NULL OR btrim(body) <> ''", name="news_body_is_absent_or_present"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="news_content_hash_is_sha256_hex"
        ),
        # We cannot have fetched an article before it existed.
        sa.CheckConstraint("published_at <= retrieved_at", name="news_published_before_retrieved"),
    )
    # The brief's query: what was knowable by this date, newest first.
    op.create_index("ix_news_items_known_as_of", TABLE, ["known_as_of", "published_at"])
    # "Do we already hold this article?", and "which version is current?" - newest row for
    # an item_key. Not unique: a corrected headline is a second row under the same key.
    op.create_index("ix_news_items_item_key", TABLE, ["data_source_id", "item_key", "id"])
    # "Have we seen these exact words from anyone else?" P5.4 asks this per brief item.
    op.create_index("ix_news_items_content_hash", TABLE, ["content_hash"])
    op.execute(
        f"CREATE TRIGGER no_update BEFORE UPDATE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )

    connection = op.get_bind()
    for source in NEWS_SOURCES:
        already = connection.execute(
            sa.text("SELECT count(*) FROM data_sources WHERE source_name = :n"),
            {"n": source["source_name"]},
        ).scalar_one()
        if not already:
            op.bulk_insert(data_sources_table, [source])


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS no_update ON {TABLE};")
    op.drop_table(TABLE)
    # The register rows go with the table, but only while nothing else points at them. A
    # downgrade after the connector has run leaves `source_documents` rows holding the
    # stored feed XML, and a source row deleted from under those would erase the licence
    # that governs bytes we still hold. `upgrade()` skips a name that is already present,
    # so either outcome replays cleanly - which is the property that matters here.
    for source in NEWS_SOURCES:
        op.execute(
            sa.text(
                "DELETE FROM data_sources d WHERE d.source_name = :n AND NOT EXISTS ("
                "SELECT 1 FROM source_documents s WHERE s.data_source_id = d.id)"
            ).bindparams(n=source["source_name"])
        )
