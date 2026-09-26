"""What a daily brief says - as data, as text, and as one hash. P5.4.

`docs/08` §6: *"compute functions take data and return data, and do no I/O of their
own."* Nothing in this module opens a session or a socket. `packages.brief.collect`
does the reading; this module turns the result into the words the reader gets and the
hash that stops those words arriving twice.

## The three rules this module exists to keep

**Every figure carries its as-of date.** `docs/03` P5.4's output spec ends "with as-of
dates on every figure", and a brief is not exempt from the promise the rest of the
system makes. So there is no bare number anywhere below: a close carries the bar's date
*and* the vintage it was read at, a filing carries `known_as_of` beside `filing_date`, a
macro reading carries `as_of_date` beside `known_as_of`.

**Absence is explained, never implied.** A section that found nothing says which of two
things happened: it looked and there was nothing, or it could not look. `docs/03` P5.4's
worst failure is a brief reporting "nothing to report" when the truth is that `news_tags`
is empty and no article *could* have matched. Every section therefore carries its own
gap sentences naming what stopped it, and :func:`render` prints "nothing to report" only
when that tuple is empty.

**No advice, and none implied.** `DATA_FOUNDATION.md` §6.5. A brief reports what moved
and what was filed, so:

* **no emoji, anywhere.** "GTCO down 8%" is a fact; "GTCO down 8%" with a warning sign
  after it is an instruction wearing a fact's clothes.
* **no ranking.** Watchlist lines are ordered by ticker and macro lines by series code -
  alphabetically, which means nothing. Sorting by the size of a move would put the day's
  biggest number at the top of the message, and "look at this one first" is a judgement
  this module is not allowed to make. News and filings are ordered newest-first, which is
  chronology rather than importance.
* **no adjectives.** A move is a signed percentage. A macro reading is overdue or it is
  not, which is the vocabulary `CLAUDE.md` already uses: "staleness is visible".

## The idempotency hash, and exactly what is in it

`docs/03` P5.4: *"the same brief must never send twice. A retry after a network blip that
double-sends is how a useful bot becomes a muted one."* Migration 0029 puts the guard in
`alert_deliveries`, unique on `(principal_id, idempotency_hash)`, and says the hash is
**over the content**.

:func:`content_hash` is SHA-256 over :func:`canonical_payload`, which holds **the facts
and nothing else**:

* every figure and every date belonging to a figure - closes, bar dates, vintages,
  filing dates, period ends, article timestamps, macro values and their as-of dates;
* the gap sentences, because "nothing has been tagged to any security yet" is content the
  reader sees and the morning it stops being true the brief has genuinely changed;
* `window_days` and :data:`CONTENT_VERSION`, because both change what a brief covers.

And it deliberately excludes:

* **the decision date and every clock-derived figure.** This is the whole point. A hash
  containing today's date is a hash that never collides, which is idempotency in name
  only. The consequence is intended and worth stating plainly: a brief whose *facts* have
  not moved - a weekend, a public holiday, a day the price feed wrote nothing new - does
  not arrive a second time. That is the same mechanism that stops a retry double-sending,
  and it is why nothing rendered below may be derived from the clock. "Overdue" is a
  boolean on the payload and survives; a *days-since* count would not, and printing one
  would let two visibly different messages share one hash.
* **the principal.** The unique constraint already carries it, and migration 0029 is
  explicit that two people sent identical content are two deliveries, neither suppressing
  the other. The recipient's name is in the header and is not a fact about the market.
* **the channel.** `alert_deliveries` is unique on `(principal_id, idempotency_hash)`
  with no channel in the key, so the schema has already decided that one piece of content
  is delivered once. Folding the channel into the hash would route around that decision by
  making the "content hash" not a hash of the content. When a second channel lands, that
  is a schema question to answer then.

**The invariant that makes this safe, and the test that holds it:** everything
:func:`render` prints is in the payload, except the header line and the fixed section
labels. The hash is therefore at least as fine-grained as the message, so a change the
reader can see is a change the hash can see.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from packages.common.timez import ensure_utc

__all__ = [
    "CONTENT_VERSION",
    "TELEGRAM_MAX_CHARS",
    "Brief",
    "FilingLine",
    "MacroLine",
    "Move",
    "NewsLine",
    "SentimentLine",
    "canonical_payload",
    "content_hash",
    "render",
    "split_for_telegram",
]

#: Bumped when the *shape* of a brief changes - a section added, a figure that was never
#: shown starting to be shown. A reader receiving a brief that covers more than yesterday's
#: is receiving different content, and would otherwise be suppressed by a hash computed
#: over fields that happen not to have moved.
CONTENT_VERSION = 1

#: Telegram rejects a message longer than this. :func:`split_for_telegram` divides on line
#: boundaries rather than letting the API refuse the send, and never drops a section: a
#: brief that quietly lost its tail would be a brief that lies by omission.
TELEGRAM_MAX_CHARS = 4096


@dataclass(frozen=True)
class Move:
    """One watchlist security's last close, and what it did against the close before it.

    `close` and `previous_close` are **as traded**; `change` is computed on those closes
    *adjusted* by the corporate actions known on the decision date, which is what stops a
    4-for-1 split being reported as a 75% fall. `actions_applied` says how many factors
    the comparison had to apply, so a reader can see when it mattered.

    `absent` is set, and every figure is None, when there was nothing to read - the honest
    state for a security whose price feed has never run.
    """

    ticker: str
    legal_name: str
    currency: str
    close: Decimal | None
    bar_date: dt.date | None
    known_as_of: dt.date | None
    previous_close: Decimal | None
    previous_bar_date: dt.date | None
    change: Decimal | None
    actions_applied: int = 0
    absent: str | None = None


@dataclass(frozen=True)
class FilingLine:
    """One filing that landed inside the window, as known on the decision date."""

    ticker: str
    legal_name: str
    filing_type: str
    filing_date: dt.date
    period_end: dt.date
    known_as_of: dt.date
    accession_no: str | None


@dataclass(frozen=True)
class SentimentLine:
    """One model's read of one headline, named. `docs/03` P5.3: treat it as weak.

    The model and its version are printed beside the score for that reason - an unlabelled
    number invites the reader to trust it, and these are scorers trained on US financial
    English being pointed at Nigerian financial journalism.
    """

    label: str
    score: Decimal
    model: str
    model_version: str


@dataclass(frozen=True)
class NewsLine:
    """One article tagged to a watchlist security.

    `published_at` is the article's own clock and `known_as_of` the date derived from it;
    our fetch time (`news_items.retrieved_at`) is provenance and never appears here - it
    is the scheduler's cron entry, not the market (`docs/08` §1.3).
    """

    news_id: int
    headline: str
    url: str
    source: str
    published_at: dt.datetime
    known_as_of: dt.date
    tickers: tuple[str, ...]
    sentiment: SentimentLine | None = None


@dataclass(frozen=True)
class MacroLine:
    """One macro reading, with whether it is new in the window and whether it is overdue.

    `stale` is `macro.SeriesSummary.is_stale`, computed rather than stored, and `None` for
    a series nobody can judge - the MPR changes when the MPC changes it, so an unchanged
    rate is the normal state and flagging it would teach the reader to ignore the flag.
    """

    code: str
    name: str
    unit: str
    value: Decimal
    as_of_date: dt.date
    known_as_of: dt.date
    expected_lag_days: int
    stale: bool | None
    newly_released: bool


@dataclass(frozen=True)
class Brief:
    """One principal's brief for one decision date.

    `principal_name` and `decision_date` are the envelope, not the content: they are in
    the header and out of the hash. Everything else is a fact and is hashed.

    The five gap tuples are per section rather than one list, because a reader needs to
    know *which* question went unanswered. "The watchlist is empty" makes three sections
    meaningless; "nothing has been tagged yet" makes exactly one.
    """

    principal_id: int
    principal_name: str
    decision_date: dt.date
    window_days: int
    moves: tuple[Move, ...] = ()
    filings: tuple[FilingLine, ...] = ()
    news: tuple[NewsLine, ...] = ()
    macro: tuple[MacroLine, ...] = ()
    watchlist_gaps: tuple[str, ...] = ()
    move_gaps: tuple[str, ...] = ()
    filing_gaps: tuple[str, ...] = ()
    news_gaps: tuple[str, ...] = ()
    macro_gaps: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when no section found anything. Says nothing about *why* - see the gaps."""
        return not (self.moves or self.filings or self.news or self.macro)


# ---------------------------------------------------------------------------
# The hash
# ---------------------------------------------------------------------------


def _number(value: Decimal | None) -> str | None:
    """A Decimal as its exact stored text. `None` stays `None`, never "0"."""
    return None if value is None else str(value)


def _day(value: dt.date | None) -> str | None:
    return None if value is None else value.isoformat()


def canonical_payload(brief: Brief) -> str:
    """The brief's facts as one deterministic UTF-8 JSON string.

    Sorted keys and no whitespace, so the same facts serialise identically whatever order
    the reads returned them in. Decimals are written as their exact stored text rather
    than as floats: `NUMERIC` is the project's money type (`docs/08` §1.6) and a float
    round-trip would make two equal prices hash differently on some machines.

    Read the module docstring before adding a field. Anything derived from the clock does
    not belong here, and anything the reader can see does.
    """
    payload = {
        "v": CONTENT_VERSION,
        "window_days": brief.window_days,
        "moves": [
            {
                "ticker": move.ticker,
                "currency": move.currency,
                "close": _number(move.close),
                "bar_date": _day(move.bar_date),
                "known_as_of": _day(move.known_as_of),
                "previous_close": _number(move.previous_close),
                "previous_bar_date": _day(move.previous_bar_date),
                "change": _number(move.change),
                "actions_applied": move.actions_applied,
                "absent": move.absent,
            }
            for move in brief.moves
        ],
        "filings": [
            {
                "ticker": filing.ticker,
                "filing_type": filing.filing_type,
                "filing_date": _day(filing.filing_date),
                "period_end": _day(filing.period_end),
                "known_as_of": _day(filing.known_as_of),
                "accession_no": filing.accession_no,
            }
            for filing in brief.filings
        ],
        "news": [
            {
                "news_id": item.news_id,
                "headline": item.headline,
                "url": item.url,
                "source": item.source,
                "published_at": ensure_utc(item.published_at).isoformat(),
                "known_as_of": _day(item.known_as_of),
                "tickers": list(item.tickers),
                "sentiment": None
                if item.sentiment is None
                else {
                    "label": item.sentiment.label,
                    "score": _number(item.sentiment.score),
                    "model": item.sentiment.model,
                    "model_version": item.sentiment.model_version,
                },
            }
            for item in brief.news
        ],
        "macro": [
            {
                "code": series.code,
                "unit": series.unit,
                "value": _number(series.value),
                "as_of_date": _day(series.as_of_date),
                "known_as_of": _day(series.known_as_of),
                "expected_lag_days": series.expected_lag_days,
                "stale": series.stale,
                "newly_released": series.newly_released,
            }
            for series in brief.macro
        ],
        "gaps": {
            "watchlist": list(brief.watchlist_gaps),
            "moves": list(brief.move_gaps),
            "filings": list(brief.filing_gaps),
            "news": list(brief.news_gaps),
            "macro": list(brief.macro_gaps),
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(brief: Brief) -> str:
    """SHA-256 of :func:`canonical_payload`, lower-case hex - 64 chars, for `CHAR(64)`."""
    return hashlib.sha256(canonical_payload(brief).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------


def _percent(change: Decimal) -> str:
    """A signed percentage to two places: `+0.99%`, `-8.00%`. No arrow, no emoji."""
    pct = (change * 100).quantize(Decimal("0.01"))
    return f"{pct:+}%"


def _as_of(on: dt.date, known_as_of: dt.date) -> str:
    """`as of D` - plus the vintage, when the figure was learned after the day it is for."""
    if known_as_of == on:
        return f"as of {on.isoformat()}"
    return f"as of {on.isoformat()} (known {known_as_of.isoformat()})"


def _render_section(title: str, lines: list[str], gaps: tuple[str, ...]) -> list[str]:
    """One section, with the distinction the whole module exists for.

    Findings print. No findings and no gaps prints "nothing to report", which is a claim
    that the search happened and came back empty. No findings *with* gaps prints the gaps
    instead, because then the search did not happen and "nothing to report" would be a lie.
    """
    out = [title]
    if lines:
        out.extend(lines)
    elif not gaps:
        out.append("  nothing to report")
    out.extend(f"  - {gap}" for gap in gaps)
    return out


def _move_lines(brief: Brief) -> list[str]:
    lines: list[str] = []
    for move in brief.moves:
        if move.close is None or move.bar_date is None or move.known_as_of is None:
            lines.append(f"  {move.ticker}  {move.absent or 'no price bar known'}")
            continue
        lines.append(
            f"  {move.ticker}  {move.close} {move.currency}  "
            f"{_as_of(move.bar_date, move.known_as_of)}"
        )
        if move.change is None or move.previous_close is None or move.previous_bar_date is None:
            lines.append("        no earlier bar known, so no change is shown")
            continue
        plural = "" if move.actions_applied == 1 else "s"
        across = (
            f", across {move.actions_applied} corporate action{plural}"
            if move.actions_applied
            else ""
        )
        lines.append(
            f"        {_percent(move.change)} against {move.previous_close} "
            f"of {move.previous_bar_date.isoformat()}{across}"
        )
    return lines


def _filing_lines(brief: Brief) -> list[str]:
    return [
        f"  {filing.ticker}  {filing.filing_type}  filed {filing.filing_date.isoformat()}  "
        f"period ended {filing.period_end.isoformat()}  "
        f"(known {filing.known_as_of.isoformat()})"
        for filing in brief.filings
    ]


def _news_lines(brief: Brief) -> list[str]:
    lines: list[str] = []
    for item in brief.news:
        published = ensure_utc(item.published_at)
        lines.append(
            f"  {published.date().isoformat()}  {item.source}  "
            f"[{', '.join(item.tickers)}]  {item.headline}"
        )
        if item.sentiment is None:
            lines.append("        sentiment: not scored")
        else:
            lines.append(
                f"        sentiment: {item.sentiment.label} {item.sentiment.score} "
                f"({item.sentiment.model} {item.sentiment.model_version})"
            )
        lines.append(f"        {item.url}")
    return lines


def _macro_lines(brief: Brief) -> list[str]:
    lines: list[str] = []
    for series in brief.macro:
        notes = []
        if series.newly_released:
            notes.append("new in this window")
        if series.stale:
            notes.append(f"overdue: published about every {series.expected_lag_days} days")
        suffix = f"  [{'; '.join(notes)}]" if notes else ""
        lines.append(
            f"  {series.code}  {series.value} {series.unit}  "
            f"{_as_of(series.as_of_date, series.known_as_of)}{suffix}"
        )
    return lines


def render(brief: Brief) -> str:
    """The brief as the plain text that goes down the wire.

    Plain text on purpose: Telegram's Markdown and HTML parse modes both reject unescaped
    punctuation, and a company name with an underscore in it is not a reason for a brief
    to fail to send.

    The header carries the recipient and the decision date and is **not** hashed - see the
    module docstring. Everything else here is a field of the payload, and that
    correspondence is what makes the hash at least as fine as the message.
    """
    header = [
        f"Daily brief - {brief.principal_name} - prepared {brief.decision_date.isoformat()} (UTC)",
        "Every figure carries the date it is as of.",
    ]
    body: list[str] = [f"- {gap}" for gap in brief.watchlist_gaps]
    if body:
        body.append("")
    body.extend(_render_section("WATCHLIST", _move_lines(brief), brief.move_gaps))
    body.append("")
    # The window is stated in days rather than as a pair of dates, and that is not a
    # style choice: `window_days` is in the hashed payload and a date is not, so a title
    # carrying the decision date would be visible text the hash cannot see.
    body.extend(
        _render_section(
            f"FILINGS (filed in the last {brief.window_days} days)",
            _filing_lines(brief),
            brief.filing_gaps,
        )
    )
    body.append("")
    body.extend(
        _render_section(
            f"NEWS (tagged to the watchlist, published in the last {brief.window_days} days)",
            _news_lines(brief),
            brief.news_gaps,
        )
    )
    body.append("")
    body.extend(_render_section("MACRO", _macro_lines(brief), brief.macro_gaps))
    return "\n".join([*header, "", *body])


def split_for_telegram(text: str, *, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """`text` as one or more chunks no longer than `limit`, split on line boundaries.

    No section is dropped. A single line longer than `limit` is divided at `limit` rather
    than discarded, because a URL that is too long should still arrive split and visible
    rather than take the rest of the brief with it.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        pieces = [line[index : index + limit] for index in range(0, len(line), limit)] or [""]
        for piece in pieces:
            extra = len(piece) + (1 if current else 0)
            if current and size + extra > limit:
                chunks.append("\n".join(current))
                current, size = [piece], len(piece)
            else:
                current.append(piece)
                size += extra
    if current:
        chunks.append("\n".join(current))
    return chunks
