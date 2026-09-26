"""Reading one principal's brief out of the database. P5.4.

The I/O half of the brief. :func:`collect_brief` takes a principal and a decision date
and returns a :class:`~packages.brief.content.Brief` - plain data, which
`packages.brief.content` renders and hashes without touching a session again
(`docs/08` §6).

**Per principal, built from their watchlist.** `CLAUDE.md`: *"never assume a single
user... portfolios, watchlists, risk limits, alerts, spend caps, and audit rows are keyed
by principal."* Every read below is scoped by `watchlists.principal_id`, and two
principals with different watchlists get different briefs because the scope differs, not
because a filter was remembered.

**Every read is point-in-time, and the decision date is mandatory.** There is no default
of today here or anywhere under it: `latest_price`, `filings_for` and `macro.list_series`
all take the date and filter on `known_as_of`, so a brief composed for a past date shows
what was known then. `packages.brief.job` is the one place that decides what day it is,
and it does so explicitly.

## Two things the gap sentences must never contain

The gap sentences below are part of the brief's hashed content (see
`packages.brief.content`), so they carry the same restriction the rendered text does:

* **no date, and no day count.** A sentence holding the decision date changes every
  morning, which would make the idempotency hash change every morning and the guard
  worthless. The decision date is in the header, where it is not hashed.
* **no judgement.** A gap says what could not be looked at. It does not say whether that
  matters.

Counts *are* allowed and are used - "44 articles are stored and none is tagged" is worth
more than "none is tagged". The consequence is deliberate: while the tagger is unbuilt
and the article count grows, the brief's content genuinely changes each day and so it
sends each day. That is the rule working, not an exception to it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.brief.content import (
    Brief,
    FilingLine,
    MacroLine,
    Move,
    NewsLine,
    SentimentLine,
)
from packages.common.adjust import cumulative_factor, factors_known
from packages.common.identity import primary_tickers
from packages.common.models import (
    Company,
    DataSource,
    NewsItem,
    NewsSentiment,
    NewsTag,
    Principal,
    Security,
    SecurityAlias,
    Watchlist,
    WatchlistItem,
)
from packages.ingestion import macro
from packages.valuation.snapshot import filings_for, latest_price

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "WatchedSecurity",
    "collect_brief",
    "principals_with_a_watchlist",
    "watchlist_for",
]

#: How far back "new" reaches, in days. A week, so a Monday brief still carries Friday's
#: filings and the reader who skipped two mornings has not lost anything. Part of the
#: hashed content: changing it changes what a brief covers, and every brief should resend
#: once when it does.
DEFAULT_WINDOW_DAYS = 7

#: A move is carried to four decimal places as a fraction, matching
#: `snapshot.PriceReaction`'s returns. Quantised here rather than at render time so the
#: number that is hashed is the number that is shown.
CHANGE_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class WatchedSecurity:
    """One security on one principal's watchlist, with what a brief needs to name it."""

    security_id: int
    company_id: int
    ticker: str | None
    legal_name: str
    currency: str

    @property
    def label(self) -> str:
        """What the reader is shown. The ticker when there is one, the legal name when
        there is not - never a fabricated symbol, and never a bare row id."""
        return self.ticker or self.legal_name


def watchlist_for(session: Session, *, principal_id: int) -> tuple[WatchedSecurity, ...]:
    """Every security on every watchlist this principal owns, once each, ordered by label.

    Ownership comes from `watchlists.principal_id`; `watchlist_items` inherits it through
    the parent rather than repeating it, which is what the schema-convention test calls
    user-scoped *via parent*.

    The ticker is read through `identity.primary_tickers()` and not by querying
    `security_identifiers` here - `OPERATIONS.md` §1.4 allows exactly one module to do
    that, and `tests/unit/test_identity.py` walks the AST of this repository to keep it
    that way. The join is outer, because a security with no primary ticker is a real
    state for an NGX listing whose identifier rows are still manual work.
    """
    primary = primary_tickers()
    rows = session.execute(
        select(
            Security.id,
            Security.company_id,
            primary.c.ticker,
            Company.legal_name,
            Security.currency,
        )
        .select_from(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .join(Security, Security.id == WatchlistItem.security_id)
        .join(Company, Company.id == Security.company_id)
        .outerjoin(primary, primary.c.security_id == Security.id)
        .where(Watchlist.principal_id == principal_id)
        .distinct()
    ).all()
    watched = [WatchedSecurity(*row) for row in rows]
    return tuple(sorted(watched, key=lambda item: item.label))


def principals_with_a_watchlist(session: Session) -> tuple[tuple[int, str], ...]:
    """`(principal_id, display_name)` for every enabled principal who owns a watchlist.

    **Owning a watchlist is the subscription.** There is no `principals.wants_a_brief`
    column and inventing one is not P5.4's to invent; asking for a watchlist is the act
    that says "tell me about these". It also keeps the public guest principal out of the
    morning send by construction rather than by a special case naming it.

    A disabled principal is excluded: `principals.disabled_at` is the off switch, and a
    brief that kept arriving after it would make the switch a lie.
    """
    rows = session.execute(
        select(Principal.id, Principal.display_name)
        .join(Watchlist, Watchlist.principal_id == Principal.id)
        .where(Principal.disabled_at.is_(None))
        .distinct()
        .order_by(Principal.id)
    ).all()
    return tuple((row[0], row[1]) for row in rows)


def collect_brief(
    session: Session,
    *,
    principal_id: int,
    decision_date: dt.date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Brief:
    """One principal's brief for one date, as data.

    Args:
        principal_id: whose watchlist to build from.
        decision_date: the date the reader is standing on. **Mandatory, no default** -
          `docs/01` §5 and every point-in-time accessor under this one take it the same
          way, and forgetting it must be a `TypeError` rather than a wrong number.
        window_days: how far back "new" reaches.

    Raises:
        TypeError: if `decision_date` is not a date.
        ValueError: if `window_days` is not positive.
        LookupError: if there is no such principal.
    """
    if not isinstance(decision_date, dt.date):
        raise TypeError("decision_date must be a date - there is no default of today")
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    name = session.execute(
        select(Principal.display_name).where(Principal.id == principal_id)
    ).scalar_one_or_none()
    if name is None:
        raise LookupError(f"no principal with id {principal_id}")

    since = decision_date - dt.timedelta(days=window_days)
    watched = watchlist_for(session, principal_id=principal_id)
    watchlist_gaps = _watchlist_gaps(session, watched=watched, principal_id=principal_id)

    moves, move_gaps = _collect_moves(session, watched=watched, decision_date=decision_date)
    filings, filing_gaps = _collect_filings(
        session, watched=watched, decision_date=decision_date, since=since
    )
    news, news_gaps = _collect_news(
        session, watched=watched, decision_date=decision_date, since=since
    )
    series, macro_gaps = _collect_macro(session, decision_date=decision_date, since=since)

    return Brief(
        principal_id=principal_id,
        principal_name=name,
        decision_date=decision_date,
        window_days=window_days,
        moves=moves,
        filings=filings,
        news=news,
        macro=series,
        watchlist_gaps=watchlist_gaps,
        move_gaps=move_gaps,
        filing_gaps=filing_gaps,
        news_gaps=news_gaps,
        macro_gaps=macro_gaps,
    )


# ---------------------------------------------------------------------------
# The watchlist itself
# ---------------------------------------------------------------------------


def _watchlist_gaps(
    session: Session, *, watched: tuple[WatchedSecurity, ...], principal_id: int
) -> tuple[str, ...]:
    """Why the brief has no scope, when it has none - stated before any empty section.

    The two states are different and the reader needs to tell them apart. No watchlist at
    all means nobody has ever said what to watch. A watchlist with no rows on it means
    somebody did, and then emptied it.
    """
    if watched:
        return ()
    loaded = session.execute(select(func.count()).select_from(Security)).scalar_one()
    lists = session.execute(
        select(func.count()).select_from(Watchlist).where(Watchlist.principal_id == principal_id)
    ).scalar_one()
    if lists == 0:
        return (
            f"this principal owns no watchlist, so the sections below had nothing to be "
            f"scoped to; {loaded} securities are loaded and none of them is being watched",
        )
    return (
        f"this principal's watchlist holds no securities, so the sections below had "
        f"nothing to be scoped to; {loaded} securities are loaded",
    )


# ---------------------------------------------------------------------------
# Watchlist moves
# ---------------------------------------------------------------------------


def _collect_moves(
    session: Session, *, watched: tuple[WatchedSecurity, ...], decision_date: dt.date
) -> tuple[tuple[Move, ...], tuple[str, ...]]:
    if not watched:
        return (), ("there is nothing on the watchlist to price",)
    return tuple(_move_for(session, item, decision_date=decision_date) for item in watched), ()


def _move_for(session: Session, item: WatchedSecurity, *, decision_date: dt.date) -> Move:
    """One security's last close and the change against the close before it.

    Two point-in-time reads, not one window: the newest bar known on the decision date,
    then the newest bar known on the day before *that bar's own date*. Asking for "the
    bar before the decision date" would compare a Friday close with a Thursday close on a
    Monday morning and call it Monday's move.

    **The change is computed on adjusted closes and the shown closes are as traded.** A
    4-for-1 split between the two bars leaves a 75% cliff in the raw series, and a brief
    that printed it would report the single most alarming number it is capable of
    producing about an event in which no holder lost anything. The factors are those
    *known on the decision date* (`packages.common.adjust`), so a split announced later
    does not reach back into a brief already sent.
    """
    latest = latest_price(session, security_id=item.security_id, on=decision_date)
    if latest is None:
        return Move(
            ticker=item.label,
            legal_name=item.legal_name,
            currency=item.currency,
            close=None,
            bar_date=None,
            known_as_of=None,
            previous_close=None,
            previous_bar_date=None,
            change=None,
            absent="no price bar is known for this security",
        )
    previous = latest_price(
        session, security_id=item.security_id, on=latest.date - dt.timedelta(days=1)
    )
    change: Decimal | None = None
    applied = 0
    if previous is not None:
        factors = factors_known(session, security_id=item.security_id, decision_date=decision_date)
        factor_now, actions_now = cumulative_factor(latest.date, factors)
        factor_then, actions_then = cumulative_factor(previous.date, factors)
        applied = actions_then - actions_now
        adjusted_now = latest.close_raw * factor_now
        adjusted_then = previous.close_raw * factor_then
        if adjusted_then > 0:
            change = ((adjusted_now / adjusted_then) - 1).quantize(CHANGE_PLACES)
    return Move(
        ticker=item.label,
        legal_name=item.legal_name,
        currency=item.currency,
        close=latest.close_raw,
        bar_date=latest.date,
        known_as_of=latest.known_as_of,
        previous_close=previous.close_raw if previous else None,
        previous_bar_date=previous.date if previous else None,
        change=change,
        actions_applied=applied,
    )


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------


def _collect_filings(
    session: Session,
    *,
    watched: tuple[WatchedSecurity, ...],
    decision_date: dt.date,
    since: dt.date,
) -> tuple[tuple[FilingLine, ...], tuple[str, ...]]:
    """Filings for the watchlist's companies, filed in the window and known on the date.

    `snapshot.filings_for` is the point-in-time read; the window is applied here rather
    than pushed into it, because that function is the shared company-page read and the
    brief's window is the brief's business.
    """
    if not watched:
        return (), ("there is nothing on the watchlist to look for filings against",)
    by_company: dict[int, WatchedSecurity] = {}
    for item in watched:
        by_company.setdefault(item.company_id, item)
    lines: list[FilingLine] = []
    held = 0
    for company_id, item in by_company.items():
        seen = filings_for(session, company_id=company_id, decision_date=decision_date)
        held += len(seen)
        lines.extend(
            FilingLine(
                ticker=item.label,
                legal_name=item.legal_name,
                filing_type=filing.filing_type,
                filing_date=filing.filing_date,
                period_end=filing.period_end,
                known_as_of=filing.known_as_of,
                accession_no=filing.accession_no,
            )
            for filing in seen
            if filing.filing_date >= since
        )
    lines.sort(key=lambda line: (line.filing_date, line.ticker), reverse=True)
    if not lines and held == 0:
        return (), (
            f"none of the {len(by_company)} companies on the watchlist has a single filing "
            f"loaded, so this section could not look",
        )
    return tuple(lines), ()


# ---------------------------------------------------------------------------
# Tagged news, and its sentiment
# ---------------------------------------------------------------------------


def _collect_news(
    session: Session,
    *,
    watched: tuple[WatchedSecurity, ...],
    decision_date: dt.date,
    since: dt.date,
) -> tuple[tuple[NewsLine, ...], tuple[str, ...]]:
    """Articles tagged to a watchlist security, published inside the window.

    The window is on `news_items.known_as_of` - a stored generated column over
    `published_at` in Lagos time - and never on `retrieved_at`, which is provenance and
    would be the scheduler's cron entry standing in for the market (`docs/08` §1.3).
    `news_tags.tagged_at` is filtered on for the same reason: it is not.
    """
    if not watched:
        return (), ("there is nothing on the watchlist to match articles against",)
    ids = [item.security_id for item in watched]
    labels = {item.security_id: item.label for item in watched}
    primary = primary_tickers()
    rows = session.execute(
        select(
            NewsItem.id,
            NewsItem.headline,
            NewsItem.url,
            DataSource.source_name,
            NewsItem.published_at,
            NewsItem.known_as_of,
            NewsTag.security_id,
            primary.c.ticker,
        )
        .select_from(NewsTag)
        .join(NewsItem, NewsItem.id == NewsTag.news_id)
        .join(DataSource, DataSource.id == NewsItem.data_source_id)
        .outerjoin(primary, primary.c.security_id == NewsTag.security_id)
        .where(NewsTag.security_id.in_(ids))
        .where(NewsItem.known_as_of >= since)
        .where(NewsItem.known_as_of <= decision_date)
        .order_by(NewsItem.published_at.desc(), NewsItem.id.desc())
    ).all()

    order: list[int] = []
    articles: dict[int, dict[str, object]] = {}
    for news_id, headline, url, source, published_at, known_as_of, security_id, ticker in rows:
        if news_id not in articles:
            order.append(news_id)
            articles[news_id] = {
                "headline": headline,
                "url": url,
                "source": source,
                "published_at": published_at,
                "known_as_of": known_as_of,
                "tickers": [],
            }
        names: list[str] = articles[news_id]["tickers"]  # type: ignore[assignment]
        name = ticker or labels.get(security_id, str(security_id))
        if name not in names:
            names.append(name)

    scores = _sentiment_for(session, news_ids=order)
    lines = tuple(
        NewsLine(
            news_id=news_id,
            headline=str(articles[news_id]["headline"]),
            url=str(articles[news_id]["url"]),
            source=str(articles[news_id]["source"]),
            published_at=articles[news_id]["published_at"],  # type: ignore[arg-type]
            known_as_of=articles[news_id]["known_as_of"],  # type: ignore[arg-type]
            tickers=tuple(sorted(articles[news_id]["tickers"])),  # type: ignore[call-overload]
            sentiment=scores.get(news_id),
        )
        for news_id in order
    )
    if lines:
        return lines, ()
    return (), _news_gaps(session, ids=ids)


def _news_gaps(session: Session, *, ids: list[int]) -> tuple[str, ...]:
    """Why no article matched - separating "none did" from "none could".

    `docs/03` P5.4's worst outcome is a brief that says nothing happened when the truth
    is that nothing was looked at. Two things make the search impossible rather than
    empty, and each gets its own sentence: an untagged corpus, and a watchlist of
    securities no alias points at.
    """
    gaps: list[str] = []
    tags = session.execute(select(func.count()).select_from(NewsTag)).scalar_one()
    if tags == 0:
        stored = session.execute(select(func.count()).select_from(NewsItem)).scalar_one()
        gaps.append(
            f"no article has been tagged to any security yet: {stored} articles are stored "
            f"and news_tags is empty, so nothing here could have matched"
        )
    with_aliases = session.execute(
        select(func.count(func.distinct(SecurityAlias.security_id))).where(
            SecurityAlias.security_id.in_(ids)
        )
    ).scalar_one()
    if with_aliases < len(ids):
        gaps.append(
            f"{len(ids) - with_aliases} of the {len(ids)} securities on the watchlist have no "
            f"registered alias, so no article could be matched to them by name"
        )
    return tuple(gaps)


def _sentiment_for(session: Session, *, news_ids: list[int]) -> dict[int, SentimentLine]:
    """The newest score per article, or nothing at all when none has been written.

    `news_sentiment` keeps `model_version` in its primary key so a re-scoring writes
    beside the old row rather than over it (`docs/08` §2.6). A brief shows one of them,
    and shows the most recently written, with the model and version named - `docs/03`
    P5.3 is explicit that these scores are weak and that nothing may act on one alone, so
    an unlabelled number would be the wrong thing to print.

    An empty result is "not scored yet", not "neutral". The scorer is P5.3 and may not
    have run; inventing a zero would be the fabricated figure this project exists to
    avoid.
    """
    if not news_ids:
        return {}
    rows = session.execute(
        select(
            NewsSentiment.news_id,
            NewsSentiment.label,
            NewsSentiment.score,
            NewsSentiment.model,
            NewsSentiment.model_version,
        )
        .where(NewsSentiment.news_id.in_(news_ids))
        .order_by(NewsSentiment.news_id, NewsSentiment.scored_at)
    ).all()
    newest: dict[int, SentimentLine] = {}
    for news_id, label, score, model, model_version in rows:
        newest[news_id] = SentimentLine(
            label=label, score=score, model=model, model_version=model_version
        )
    return newest


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------


def _collect_macro(
    session: Session, *, decision_date: dt.date, since: dt.date
) -> tuple[tuple[MacroLine, ...], tuple[str, ...]]:
    """Series released inside the window, plus every series currently overdue.

    Not scoped to the watchlist, and that is deliberate: the macro backdrop is a fact
    about the economy rather than about a holding, and a principal whose watchlist is
    empty still has one. What is per-principal about a brief is the watchlist; what is
    shared is the weather.

    "Released" means the newest observation's *vintage* - `known_as_of` - falls inside
    the window, so a figure published this week for a period three months ago counts, and
    a figure that has sat unchanged for a month does not.

    Overdue is `macro.SeriesSummary.is_stale`, computed against the decision date from
    `expected_lag_days`. `docs/03` P5 check 8 requires it to be visible in the message,
    and `CLAUDE.md` makes it a standing rule: *"every series shows its as-of date and
    flags when overdue."* An irregular series - the MPR moves when the MPC moves it -
    reports `None`, never `False`, and is not flagged either way.
    """
    summaries = macro.list_series(session, on=decision_date, as_known_on=decision_date)
    if not summaries:
        return (), ("no macro series are registered, so this section had nothing to read",)
    with_readings = [
        summary
        for summary in summaries
        if summary.latest_as_of is not None
        and summary.latest_known_as_of is not None
        and summary.latest_value is not None
    ]
    if not with_readings:
        return (), (
            f"{len(summaries)} macro series are registered and none of them has an "
            f"observation, so this section could not look",
        )
    lines = tuple(
        MacroLine(
            code=summary.code,
            name=summary.name,
            unit=summary.unit,
            value=summary.latest_value,  # type: ignore[arg-type]
            as_of_date=summary.latest_as_of,  # type: ignore[arg-type]
            known_as_of=summary.latest_known_as_of,  # type: ignore[arg-type]
            expected_lag_days=summary.expected_lag_days,
            stale=summary.is_stale,
            newly_released=summary.latest_known_as_of >= since,  # type: ignore[operator]
        )
        for summary in with_readings
        if summary.latest_known_as_of >= since or summary.is_stale  # type: ignore[operator]
    )
    return lines, ()
