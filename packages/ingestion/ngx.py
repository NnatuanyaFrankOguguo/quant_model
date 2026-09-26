"""NGX prices from afx.kwayisi.org - the free source, cached from day one. P4.7, TG1-NG.

`docs/03` P4.7 rates this source FRAGILE and states the whole argument in one line:
*"you cannot backfill history you never fetched."* `afx.kwayisi.org` is a third-party
aggregator with no API, no contract and no uptime guarantee. Its recommended treatment is
approach 3 - free as primary, the paid fallback (EODHD `.XNSA`) documented in advance so
switching is a decision rather than a scramble - and the operative half of it is that
**every raw response is stored permanently**. `Connector.run()` stores raw before it
parses, so a parser fixed in 2028 can still be run over bytes fetched in 2026, and the day
this site disappears we keep everything we ever fetched.

That last sentence is why nothing in this module raises on a bad row. See `write()`.

## What is being fetched, and what is deliberately not

`afx.kwayisi.org/robots.txt` allows this path and publishes **`Crawl-delay: 60`** - one
request per minute. `PoliteFetcher` reads that and clamps whatever a connector declares
down to it, so the site's own number wins whether or not we notice it.

At one request a minute, **only the listing page is ever fetched**. The site also has a
page per symbol; 147 of those is two and a half hours of nightly crawling for a table that
is already on one page, and it would be the fastest way to be blocked by a host that told
us its terms in writing.

The listing is **paginated** - `Showing 1 - 100 of 147 listings`, with a `?page=2`. One
`run()` is one fetch and one parse, so one run is one page, and the whole universe is two
runs a minute apart. `parse()` reads the coverage footer and says out loud when the page
it holds is not the whole list, because a connector that quietly returns the first hundred
of a hundred and forty-seven is the silent-scraper failure with a plausible-looking number
attached.

## The trap that decides whether a stored price means anything

The page is a **live snapshot**, not a daily close. The fixture in `tests/fixtures/ngx`
was taken at 09:17 UTC - 10:17 in Lagos, seventeen minutes into a session that runs to
14:30 - and 14 of its 100 rows had already moved off the previous close. Writing that
`Price` column into `price_history.close_raw` would put an intraday last into a column
whose one rule is that it is the closing price as traded, for every symbol, on a table
whose `no_update` trigger means it can never be corrected in place.

So the page's own `<time datetime=...>` stamp is parsed, carried on every record, and
`write()` refuses to store a bar from a snapshot taken before the 14:30 WAT close
(`packages.common.timez`). A mis-scheduled run then writes nothing and says why, and the
raw response is still cached forever - which is the outcome worth having, because the
bars can be produced later from stored bytes and a wrong close cannot be taken back.

Note that `timez.session_date_for` is **not** the function used here. It maps an instant
after the close to the *next* session, which is right for a news item that could not have
moved today's close and wrong for a price snapshot: a 15:00 WAT snapshot holds today's
closes, not tomorrow's. The trading date here is simply the Lagos calendar date of the
snapshot (`docs/08` 1.3 rule 3: a plain DATE is a calendar date in the market's own local
time).

## Two more things the page carries that are not what they look like

**`Change` is absolute naira, not a percent.** The gainers and losers tables on the same
page use percentages, so a parser that guessed from one and applied it to the other would
be wrong by two orders of magnitude on every row. It is parsed and kept on the record - it
is a free cross-check against the previous stored close - and it is not written, because
`price_history` has no column for a figure derivable from two of its own rows.

**A row with `class="ss"` is suspended, and it is not a bar.** Six of the fixture's 100
rows carry it; each has a price and an *empty* volume. Those are long-term listing
suspensions (AFRINSURE, AFROMEDIA and MULTITREX have been suspended for years), and the
price shown is the last one that traded, whenever that was. Writing it every night as that
night's close manufactures a flat price series for a stock that is not trading, which
`docs/01` 7.2 names directly: a missing day treated as a zero return depresses the
volatility estimate. `price_history.halted` is not the escape hatch it looks like either -
`docs/08` 2.4 defines it as the NGX price band halting a stock *for the day*, which is a
different fact. So a suspended row is parsed faithfully, counted, logged, and not written.

## The licensing row this connector needs, and why it is not the `NGX` one

`data_sources` already holds an `NGX` row, and it is the wrong row. Its own note says so:
*"This single row covers two distinct properties with different terms... P1/P2 should split
this into two rows when the first NGX connector is built."* That row governs NGX's own
X-Compliance library and its paid Market Data API. `afx.kwayisi.org` is neither - it is an
independent aggregator republishing prices under its own site terms - and pointing this
connector's documents at the exchange's row would put the wrong licence on the bytes and
credit the wrong party. `redistribution_allowed=False` either way.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.identity import AmbiguousIdentifierError, resolve_security
from packages.common.models import PriceHistory
from packages.common.timez import NGX_CLOSE_LOCAL, to_ngx, utctoday
from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    RawResponse,
    _data_source_id,
)
from packages.ingestion.polite import PoliteFetcher, require_document, shared_fetcher

__all__ = ["CRAWL_DELAY_SEC", "SOURCE_NAME", "AfxKwayisiConnector", "NgxQuote"]

_log = structlog.get_logger(__name__)

_BASE = "https://afx.kwayisi.org"
_PATH = "/ngx/"

#: The `data_sources.source_name` this connector's documents are filed under. Deliberately
#: not `"NGX"`: see the module docstring. The aggregator is named, not the exchange.
SOURCE_NAME = "AFX Kwayisi"

#: A descriptive agent with a contact address. The site never agreed to be scraped; the
#: least we owe it is identifying ourselves so an administrator can complain to a human.
_USER_AGENT = "quant_model/0.1 (nnatuanyafrankoguguo@churchofjesuschrist.org) research"

#: What `afx.kwayisi.org/robots.txt` publishes, in seconds, for `User-agent: *`. Verified
#: against the live file on 2026-09-24. `PoliteFetcher._rate_for` clamps the declared rate
#: to this on every request, so it is enforced whether or not this constant is right.
CRAWL_DELAY_SEC = 60.0

#: The exchange every ticker on this page belongs to. A ticker is exchange-scoped
#: (`docs/08` 2.1), and resolving one without saying which market is how an NGX ticker
#: gets joined onto a same-named US listing.
_EXCHANGE = "NGX"

#: Header cells the listing table must have, lowercased. Matched by *name* rather than by
#: position, so a reordered column is handled and a renamed one is caught. `parse()` raises
#: when `ticker` or `price` is missing rather than returning an empty list - a renamed
#: column is the classic silent scraper failure and it must not read as a quiet market.
_REQUIRED_COLUMNS = frozenset({"ticker", "price"})

#: `Showing 1 - 100 of 147 listings`, in an `<li>` under the table. The word "listings"
#: is load-bearing: the same page carries a `Showing 1 - 10 of 10+` for its news list.
_COVERAGE = re.compile(
    r"Showing\s+([\d,]+)\s*-\s*([\d,]+)\s+of\s+([\d,]+)\s+listings", re.IGNORECASE
)

#: Cell values that mean "no figure", not zero. A suspended row's volume arrives as an
#: empty string, and a volume of 0 is a claim that the stock traded nothing today, which
#: is a different fact from the page declining to say.
_ABSENT = frozenset({"", "-", "--", "n/a", "na", ".", "nil"})

#: Unresolved tickers named in one log line. 147 of them in a structured log field is a
#: line nobody reads; twenty is a sample somebody can act on, and the count is exact.
_SAMPLE_SIZE = 20


@dataclass(frozen=True)
class NgxQuote:
    """One row of the listing: what the page said about one symbol at one instant.

    Faithful to the page rather than to the database. A suspended row, a row with no
    volume and a row whose price would not parse all survive to `write()`, which is where
    the domain rules live and where anything dropped gets counted.
    """

    ticker: str
    name: str | None
    price: Decimal | None
    #: Absolute, in naira, against the previous close. Not a percent - see the docstring.
    change: Decimal | None
    volume: int | None
    #: The page marked this row `class="ss"`: suspended from trading, price stale.
    suspended: bool
    #: The page's own `<time datetime=...>`, as an aware UTC instant. Every record from one
    #: fetch carries the same one, because one page is one snapshot.
    snapshot_at: dt.datetime

    @property
    def trade_date(self) -> dt.date:
        """The Lagos calendar date this snapshot belongs to (`docs/08` 1.3 rule 3)."""
        return to_ngx(self.snapshot_at).date()

    @property
    def session_complete(self) -> bool:
        """Whether the 14:30 WAT close had happened when this snapshot was taken.

        False means the `price` is an intraday last. See the module docstring for why that
        is the difference between a bar worth storing and one that cannot be taken back.
        """
        return to_ngx(self.snapshot_at).time() >= NGX_CLOSE_LOCAL


class AfxKwayisiConnector(Connector[NgxQuote]):
    """The NGX listing page at `afx.kwayisi.org/ngx/`, one page per run.

    `run(session, page=2)` fetches the second page. Page 1 is the default because it is
    what the scheduler wants first and because the unparameterised URL is the one the site
    treats as canonical.
    """

    name = "ngx_afx"

    #: One request per published `Crawl-delay`, and no second delay on top of it. CBN
    #: declares both a rate and a `politeness_delay_sec` because CBN publishes no number
    #: and the 2s spacing is a rule we imposed on ourselves; this host published 60s, so
    #: the rule is the host's and it belongs in the rate. Stacking another 60s would
    #: declare a 120s spacing nobody asked for and make every run sleep a minute before
    #: its first request.
    #:
    #: 0.0166/s is one request every 60.24 seconds - a shade slower than required, and
    #: chosen for that reason: `1/60` is 0.016666666666666666, and `register()` compares a
    #: declared float against a stored `NUMERIC` by exact equality. A rate that does not
    #: round-trip would be rewritten into `data_sources` on every single run, forever,
    #: with nothing to show for it. `base._same_rate` documents the trap; this is the
    #: first connector that could have fallen into it.
    rate_limit_per_sec = 0.0166
    politeness_delay_sec = 0.0

    def __init__(self, *, timeout_sec: float = 60.0, fetcher: PoliteFetcher | None = None) -> None:
        self._timeout = timeout_sec
        # Shared, not per-instance, so page 1 and page 2 draw on one allowance for one
        # host. Two fetchers would be two 60s buckets, which is the behaviour the
        # Crawl-delay exists to prevent, with extra steps.
        #
        # Injectable so a test can drive `fetch` without a network or a real clock; `None`
        # means the process-wide one, which is what production always wants.
        self._fetcher = fetcher or shared_fetcher(user_agent=_USER_AGENT)

    def declare_licence(self) -> DataSourceLicence:
        """The aggregator's own row, which does not exist yet - see the module docstring.

        `redistribution_allowed=False`, and here that is the documented answer rather than
        conservatism. The underlying prices are NGX market data, governed by the Data
        Agreement the `NGX` row records; a third party republishing them cannot grant us
        rights over them, and the site publishes no licence of its own that would.
        """
        return DataSourceLicence(
            source_name=SOURCE_NAME,
            base_url=_BASE,
            licence_type="third_party_aggregator_no_terms",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: AFX (afx.kwayisi.org), data from Nigerian Exchange (NGX)",
            terms_url=f"{_BASE}/",
            terms_reviewed_on=dt.date(2026, 9, 24),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes=(
                "Third-party aggregator of NGX prices, separate from the exchange's own "
                "'NGX' row, whose note asks for exactly this split when the first NGX "
                "connector is built. robots.txt allows the path and publishes "
                "Crawl-delay: 60 (verified 2026-09-24); the listing page is the only path "
                "fetched. No API, no contract, no uptime guarantee - docs/03 P4.7 rates "
                "it FRAGILE and the mitigation is the permanent raw cache, not the site. "
                "The paid fallback is EODHD .XNSA, documented and not subscribed. "
                "redistribution_allowed=false: the underlying data is NGX market data "
                "under a Data Agreement, and an aggregator cannot grant rights to it."
            ),
        )

    def fetch(self, **params: object) -> RawResponse:
        """One page of the listing, at the rate `robots.txt` asked for.

        `cache_url()` is deliberately not overridden. Measured against the live host on
        2026-09-24: the response carries neither `ETag` nor `Last-Modified`, so a
        conditional request has nothing to send and would cost a database read per run to
        save nothing (`base.Connector.cache_url`). It is also the wrong instrument here -
        the page changes on every trade, so a 304 is not the outcome we are hoping for.
        """
        page = _page_number(params.get("page"))
        url = f"{_BASE}{_PATH}" if page == 1 else f"{_BASE}{_PATH}?page={page}"
        return require_document(
            self._fetcher.get(
                url,
                rate_per_sec=self.rate_limit_per_sec,
                politeness_delay_sec=self.politeness_delay_sec,
                media_type="text/html",
                timeout=self._timeout,
            )
        )

    def parse(self, raw: RawResponse) -> list[NgxQuote]:
        """Pure. One record per row of the listing table, in the order the page had them.

        **Raises rather than returning an empty list** when the page is not the page this
        parser understands: no listing table, no recognisable `Ticker`/`Price` header, no
        rows under the header, or no snapshot timestamp to date the prices with. Each of
        those is a redesign or a block page, and each would otherwise arrive as
        `status='ok'` with zero rows - indistinguishable, in `connector_runs`, from a
        market where nothing happened. Raising makes the run an error, which is what it is.

        Everything *inside* a row is parsed defensively and never raises: an unparseable
        price, an empty volume or a missing name costs that field and not the run. This
        page has no contract, and one odd cell must not throw away the other 146 rows.
        """
        # `errors="replace"` rather than strict: the bytes are whatever the host sent, and
        # a mojibake company name is a bad cell where a UnicodeDecodeError is a lost run
        # and - because run() rolls back on an exception - a lost cached document.
        document = raw.data.decode("utf-8", errors="replace")
        page = _ListingPage()
        page.feed(document)
        page.close()

        snapshot_at = page.snapshot_at
        if snapshot_at is None:
            raise ValueError(
                f"{self.name}: no <time datetime=...> on {raw.url!r}, so there is no "
                "instant to date these prices with. A price with a guessed date is worse "
                "than no price; the raw document is stored and can be re-parsed."
            )

        table = _listing_table(page.tables)
        if table is None:
            raise ValueError(
                f"{self.name}: no table on {raw.url!r} whose header carries "
                f"{sorted(_REQUIRED_COLUMNS)}. The page was redesigned, or this is a block "
                "page. Refusing to report zero rows as a quiet market."
            )
        columns, rows = table
        if not rows:
            raise ValueError(
                f"{self.name}: the listing table on {raw.url!r} has a header and no rows. "
                "An exchange with no listings is not a thing that happens."
            )

        quotes = [
            NgxQuote(
                ticker=_cell(cells, columns.get("ticker")).upper(),
                name=_cell(cells, columns.get("name")) or None,
                price=_positive(_decimal(_cell(cells, columns.get("price")))),
                change=_decimal(_cell(cells, columns.get("change"))),
                volume=_count(_cell(cells, columns.get("volume"))),
                suspended="ss" in (attrs.get("class") or "").split(),
                snapshot_at=snapshot_at,
            )
            for attrs, cells in rows
            if _cell(cells, columns.get("ticker"))
        ]
        _warn_on_partial_coverage(document, parsed=len(quotes), url=raw.url)
        return quotes

    def write(self, session: Session, records: list[NgxQuote], *, source_document_id: int) -> int:
        """Insert the bars this page supports, and **count out loud** everything it does not.

        **Nothing here raises, and that is the deliberate part.** `run()` stores the raw
        document and commits only after `write()` returns, so an exception rolls the
        `source_documents` row back and the permanent cache - the entire reason `docs/03`
        P4.7 says to start fetching on day one - never accumulates. `YahooChartConnector`
        raises on an unknown ticker and is right to: one symbol per run, and a symbol
        nobody registered was a scheduling mistake. Here 147 tickers arrive at once and
        **none of them resolves today**, because `securities` holds no NGX row at all. A
        connector that failed on that would throw away the history it exists to collect.

        So every dropped row is counted and named in the log, in four separate buckets,
        because they mean four different things and collapsing them would hide the one
        that matters:

        * **unresolved** - no security carries this ticker on this date. Today that is all
          of them, and the fix is registering the companies, not changing this file. Once
          they exist, a count that jumps is a rename or a delisting.
        * **suspended** - the page says the stock is not trading. Not a bar. See the
          module docstring.
        * **no price** - the cell did not parse as a positive number. `close_raw` is NOT
          NULL and inventing one is not available.
        * **unchanged** - already stored at these figures. The vintage rule, not a loss.

        `rows_written` therefore stays honest: it counts rows actually inserted, so
        `base.warn_if_no_rows_written` still fires on a run that stored nothing, and the
        log line beside it says which of the four reasons it was.
        """
        if not records:
            return 0

        # One page is one snapshot, so the gate is a property of the fetch rather than of
        # a row. Checked before any lookup: there is nothing to resolve if there is
        # nothing storable.
        first = records[0]
        if not first.session_complete:
            _log.warning(
                "ngx_snapshot_before_session_close",
                connector=self.name,
                snapshot_at=first.snapshot_at.isoformat(),
                lagos_time=to_ngx(first.snapshot_at).strftime("%Y-%m-%d %H:%M"),
                ngx_close_local=NGX_CLOSE_LOCAL.isoformat(),
                quotes=len(records),
                remedy=(
                    "the Price column is an intraday last, not a close; schedule this "
                    "connector after 14:30 WAT. The raw response is cached either way."
                ),
            )
            return 0

        trade_date = first.trade_date
        data_source_id = _data_source_id(session, self)

        storable: list[tuple[int, NgxQuote]] = []
        unresolved: list[str] = []
        ambiguous: list[str] = []
        suspended = 0
        no_price = 0
        for quote in records:
            if quote.suspended:
                suspended += 1
                continue
            if quote.price is None:
                no_price += 1
                continue
            try:
                resolved = resolve_security(
                    session,
                    value=quote.ticker,
                    # The snapshot's own date, not today's. Yahoo resolves as of today
                    # because its symbol came off this morning's wire; this connector is
                    # built to be re-run over documents cached years earlier, and
                    # resolving a 2026 ticker against 2031's identifier table is how a
                    # renamed company's old prices land on somebody else's security.
                    as_of=trade_date,
                    exchange=_EXCHANGE,
                )
            except AmbiguousIdentifierError:
                # Two NGX securities holding one ticker on one day is a database the
                # `no_overlapping_ids` constraint should have refused. Counted rather than
                # raised: one impossible row must not cost the other 146 and the document.
                ambiguous.append(quote.ticker)
                continue
            if resolved is None:
                unresolved.append(quote.ticker)
                continue
            storable.append((resolved.security_id, quote))

        _report(
            connector=self.name,
            trade_date=trade_date,
            quotes=len(records),
            resolved=len(storable),
            unresolved=unresolved,
            ambiguous=ambiguous,
            suspended=suspended,
            no_price=no_price,
        )
        if not storable:
            return 0
        return self._insert(
            session,
            storable,
            trade_date=trade_date,
            data_source_id=data_source_id,
            source_document_id=source_document_id,
        )

    def _insert(
        self,
        session: Session,
        storable: list[tuple[int, NgxQuote]],
        *,
        trade_date: dt.date,
        data_source_id: int,
        source_document_id: int,
    ) -> int:
        """The vintage rule, applied to one day's closes. Returns rows inserted.

        Identical to the one `YahooChartConnector` follows, and for the same reason: a bar
        seen for the first time is dated the day it traded, a bar re-served with the same
        figures is the same vintage and is not written, and a bar whose figures changed is
        a second row dated the day the change was seen. `price_history` carries a
        `no_update` trigger, so a correction is only ever an additional row.

        **One consequence of that, which this source runs into and Yahoo does not.** A
        vintage is a day, and this connector can be run twice on the same day a bar was
        first seen - two runs after the close, or a page still settling. The correction
        then wants the `known_as_of` the first row already holds, the key
        `(security_id, date, known_as_of)` collides, and `ON CONFLICT DO NOTHING` drops it
        without a word. Nothing here can fix that - a knowledge date invented to dodge the
        key would be a lie in the column whose whole job is to say when something was
        knowable - so it is counted and logged instead. Tomorrow's run stores it.
        """
        stored: dict[int, tuple[Decimal | None, int | None]] = {}
        rows = session.execute(
            select(
                PriceHistory.security_id,
                PriceHistory.known_as_of,
                PriceHistory.close_raw,
                PriceHistory.volume,
            )
            .where(PriceHistory.security_id.in_([security_id for security_id, _ in storable]))
            .where(PriceHistory.date == trade_date)
            .order_by(PriceHistory.known_as_of)
        ).all()
        for security_id, _known, close_raw, volume in rows:
            stored[security_id] = (close_raw, volume)  # ordered by vintage: the newest wins

        # `max` because `price_history_pit_sanity` requires known_as_of >= date, and a
        # Lagos date runs an hour ahead of UTC's for the last hour of the UTC day.
        seen_today = max(utctoday(), trade_date)
        to_insert: list[dict[str, object]] = []
        unchanged = 0
        for security_id, quote in storable:
            held = stored.get(security_id)
            if held is not None and _same(held, (quote.price, quote.volume)):
                unchanged += 1
                continue
            to_insert.append(
                {
                    "security_id": security_id,
                    "date": trade_date,
                    "known_as_of": trade_date if held is None else seen_today,
                    "open_raw": None,
                    "high_raw": None,
                    "low_raw": None,
                    # The listing gives one price per symbol and no intraday range. Every
                    # column it does not carry stays NULL rather than being filled with
                    # the close, which would invent a day with no high and no low.
                    "close_raw": quote.price,
                    "volume": quote.volume,
                    "vwap": None,
                    # Never True from this source: `halted` is the price band stopping a
                    # stock for the day (`docs/08` 2.4), and the page's only trading flag
                    # is a listing suspension, which is a different fact and is not
                    # written at all.
                    "halted": False,
                    "data_source_id": data_source_id,
                    "source_document_id": source_document_id,
                }
            )
        if unchanged:
            _log.info("ngx_unchanged_bars_skipped", count=unchanged, date=trade_date.isoformat())
        if not to_insert:
            return 0
        inserted = 0
        for start in range(0, len(to_insert), 2000):
            statement = (
                pg_insert(PriceHistory)
                .values(to_insert[start : start + 2000])
                .on_conflict_do_nothing(index_elements=["security_id", "date", "known_as_of"])
                .returning(PriceHistory.date)
            )
            inserted += len(session.execute(statement).fetchall())
        if inserted < len(to_insert):
            _log.warning(
                "ngx_same_day_correction_not_stored",
                count=len(to_insert) - inserted,
                date=trade_date.isoformat(),
                known_as_of=seen_today.isoformat(),
                remedy=(
                    "a changed close wants a known_as_of this bar already has, and a "
                    "vintage is a day. The stored figure stands until the next run on a "
                    "later date. See _insert()."
                ),
            )
        return inserted


def _report(
    *,
    connector: str,
    trade_date: dt.date,
    quotes: int,
    resolved: int,
    unresolved: list[str],
    ambiguous: list[str],
    suspended: int,
    no_price: int,
) -> None:
    """Say what happened to every parsed row, at a level that matches what it means.

    Split into three events on purpose. The first is the state of the world today and will
    be true every night until somebody registers the NGX companies, so it is a warning
    rather than an error: an error every night for a known, unfixable-here condition is how
    a check earns a mute, and `base.warn_if_no_rows_written` already fires beside it.
    The second is a database that should be impossible. The third is bookkeeping, and it
    is emitted on every run so the four buckets always add up to the rows parsed.
    """
    if unresolved:
        _log.warning(
            "ngx_tickers_unresolved",
            connector=connector,
            unresolved=len(unresolved),
            resolved=resolved,
            of=quotes,
            exchange=_EXCHANGE,
            as_of=trade_date.isoformat(),
            sample=sorted(unresolved)[:_SAMPLE_SIZE],
            remedy=(
                "no security on NGX carries these tickers on this date. Prices attach to "
                "a security, never to a ticker string - register the companies."
            ),
        )
    if ambiguous:
        _log.warning(
            "ngx_tickers_ambiguous",
            connector=connector,
            count=len(ambiguous),
            tickers=sorted(ambiguous)[:_SAMPLE_SIZE],
            as_of=trade_date.isoformat(),
            remedy=(
                "one ticker resolved to two NGX securities on one date, which "
                "no_overlapping_ids should refuse. Fix security_identifiers."
            ),
        )
    _log.info(
        "ngx_listing_resolved",
        connector=connector,
        date=trade_date.isoformat(),
        quotes=quotes,
        storable=resolved,
        unresolved=len(unresolved),
        ambiguous=len(ambiguous),
        suspended=suspended,
        no_price=no_price,
    )


class _ListingPage(HTMLParser):
    """Every table on the page as rows of text, plus the page's own timestamp.

    Standard library on purpose: this repository has no HTML parser in its dependencies
    (`pyproject.toml`), and adding lxml or BeautifulSoup for one table would be a wheel
    to build in CI for a page that is five columns wide.

    `convert_charrefs=True` so `&amp;` in a company name arrives as `&`. Cells keep only
    text, which is what discards the `<a href=...>` wrapper every ticker and name sits in.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[dict[str, str], list[str]]]] = []
        self.snapshot_at: dt.datetime | None = None
        self._table: list[tuple[dict[str, str], list[str]]] | None = None
        self._row: list[str] | None = None
        self._row_attrs: dict[str, str] = {}
        self._cell: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "table":
            # This page closes almost nothing - no `</tr>`, no `</td>` - so a start tag
            # has to close whatever is open. `HTMLParser` is a token stream, not a tree
            # builder, and will not do it for us.
            self._close_table()
            self._table = []
        elif tag == "tr":
            self._close_row()
            self._row, self._row_attrs = [], attributes
        elif tag in {"td", "th"}:
            self._close_cell()
            self._cell = ""
        elif tag == "time" and self.snapshot_at is None:
            self.snapshot_at = _instant(attributes.get("datetime"))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self._close_cell()
        elif tag == "tr":
            self._close_row()
        elif tag == "table":
            self._close_table()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell += data

    def close(self) -> None:
        super().close()
        self._close_table()

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(self._cell.strip())
        self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None and self._table is not None:
            self._table.append((self._row_attrs, self._row))
        self._row, self._row_attrs = None, {}

    def _close_table(self) -> None:
        self._close_row()
        if self._table:
            self.tables.append(self._table)
        self._table = None


def _listing_table(
    tables: list[list[tuple[dict[str, str], list[str]]]],
) -> tuple[dict[str, int], list[tuple[dict[str, str], list[str]]]] | None:
    """The table whose header names the columns we need, as (column index, data rows).

    Found by header text, not by position: the page also carries an index summary, a
    gainers table and a losers table, and which of the four comes first is the site's
    business. `docs/03` P1.3's lesson from CBN is that these pages get rebuilt.
    """
    for table in tables:
        if not table:
            continue
        header = [cell.strip().lower() for cell in table[0][1]]
        columns = {name: index for index, name in enumerate(header) if name}
        if set(columns) >= _REQUIRED_COLUMNS:
            return columns, table[1:]
    return None


def _warn_on_partial_coverage(document: str, *, parsed: int, url: str | None) -> None:
    """Say out loud when this page is not the whole list.

    The listing paginates at 100 and the exchange has more than that, so a run that takes
    page 1 and stops has 68% of the market and no error to show for it. The footer states
    the range and the total; both are reported, and a mismatch between the parsed row
    count and the range the page claims is reported too, because that is the shape a
    partly-broken row parser has.

    A regex over the text rather than a node from the parse: the footer is prose in an
    `<li>`, not structure, so there is no element to walk to and matching the sentence is
    the same fragility with a tenth of the code.
    """
    match = _COVERAGE.search(document)
    if match is None:
        _log.warning("ngx_coverage_footer_missing", url=url, parsed=parsed)
        return
    first, last, total = (int(group.replace(",", "")) for group in match.groups())
    if last - first + 1 != parsed:
        _log.warning(
            "ngx_row_count_disagrees_with_page",
            url=url,
            parsed=parsed,
            page_claims=last - first + 1,
            showing=f"{first}-{last}",
            of=total,
        )
    if last < total:
        _log.info(
            "ngx_listing_is_paginated",
            url=url,
            showing=f"{first}-{last}",
            of=total,
            remedy="run this connector again with page=N for the rest of the listing",
        )


def _page_number(value: object) -> int:
    """The page to fetch. Anything that is not a positive whole number is page 1.

    Tolerant rather than strict because the caller is a scheduler passing a job argument,
    and a malformed one should cost the second page rather than the night's fetch.
    """
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        return 1
    return page if page >= 1 else 1


def _cell(cells: list[str], index: int | None) -> str:
    """The text of a column, or empty when the row is short or the column is absent.

    Short rows happen: a `<td colspan=...>` note in the middle of a table is one row with
    one cell, and reaching past the end of it must not end the parse.
    """
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def _decimal(text: str) -> Decimal | None:
    """A number from a cell, or None. Never zero for an absent value.

    An empty volume becomes NULL and not 0, for the same reason CBN's empty `mpr` does
    (SPEC 4.1): 0 is a claim, NULL is the absence of one, and nothing downstream can tell
    a fabricated zero from a real one.
    """
    cleaned = text.strip().replace(",", "").replace("−", "-").lstrip("+")
    if cleaned.lower() in _ABSENT:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _positive(value: Decimal | None) -> Decimal | None:
    """A price is a positive number or it is not a price."""
    if value is None or value <= 0:
        return None
    return value


def _count(text: str) -> int | None:
    """A share volume: a whole, non-negative number, or None."""
    value = _decimal(text)
    if value is None or value < 0:
        return None
    try:
        return int(value)
    except (ValueError, ArithmeticError):
        return None


def _instant(value: str | None) -> dt.datetime | None:
    """The `<time datetime=...>` attribute as an aware UTC instant, or None.

    A naive stamp is rejected rather than assumed to be UTC (`packages.common.timez`):
    the site reports in UTC today, and guessing the offset the day it stops is how every
    price moves by an hour and every trading date by a day.
    """
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.UTC)


def _same(held: tuple[Decimal | None, int | None], figures: tuple[object, ...]) -> bool:
    """Whether a stored bar already carries these figures, comparing as numbers.

    `Decimal("7.00") != Decimal("7")` is False as numbers and True as strings, and the
    database round-trips `7.00` for a price the page wrote as `7.00`. Comparing text would
    make every unchanged bar look like a correction and write a new vintage a night.
    """
    for stored, parsed in zip(held, figures, strict=True):
        if stored is None and parsed is None:
            continue
        if stored is None or parsed is None or Decimal(str(stored)) != Decimal(str(parsed)):
            return False
    return True
