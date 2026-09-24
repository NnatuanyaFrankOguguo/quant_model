"""P5.4: a brief says what it could see, and says it once.

`docs/03` P5 test checkpoint, checks 6, 7 and 9:

    | 6 | **Idempotency** | Run the brief job twice; exactly one message sent |
    | 7 | Per-principal briefs | Two principals with different watchlists get different
          briefs |
    | 9 | Compliance green | Public-tier content only; no advice phrasing in the brief |

plus the two the prose insists on and the table does not name: the empty case must say
*why* it is empty, and a send with no bot token must refuse loudly rather than record a
message it never sent.

The pure half of the suite needs no database, which is the point of `docs/08` §6's split
- a brief's wording and its hash are checkable without one.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.brief.collect import collect_brief, principals_with_a_watchlist, watchlist_for
from packages.brief.content import (
    Brief,
    FilingLine,
    MacroLine,
    Move,
    NewsLine,
    SentimentLine,
    canonical_payload,
    content_hash,
    render,
    split_for_telegram,
)
from packages.brief.delivery import (
    PENDING,
    SENT,
    SUPPRESSED,
    TELEGRAM_CHAT_ID_PREFIX,
    DeliveryRefused,
    TelegramChannel,
    deliver,
    recipient_for,
)
from packages.brief.job import run_daily_brief
from packages.common.models import (
    AlertDelivery,
    Company,
    DataSource,
    Exchange,
    PriceHistory,
    Principal,
    Security,
    SecurityIdentifier,
    SourceDocument,
    SystemConfig,
    Watchlist,
    WatchlistItem,
)

DECISION = dt.date(2026, 9, 24)
NOW = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------------------------
# A brief built by hand, so the pure tests own every field they assert on
# --------------------------------------------------------------------------------------


def _brief(**overrides: object) -> Brief:
    base = Brief(
        principal_id=1,
        principal_name="Frank Oguguo",
        decision_date=DECISION,
        window_days=7,
        moves=(
            Move(
                ticker="AAPL",
                legal_name="Apple Inc.",
                currency="USD",
                close=Decimal("332.4100"),
                bar_date=dt.date(2026, 9, 16),
                known_as_of=dt.date(2026, 9, 16),
                previous_close=Decimal("331.3400"),
                previous_bar_date=dt.date(2026, 9, 15),
                change=Decimal("0.0032"),
            ),
        ),
        filings=(
            FilingLine(
                ticker="AAPL",
                legal_name="Apple Inc.",
                filing_type="10-Q",
                filing_date=dt.date(2026, 9, 18),
                period_end=dt.date(2026, 8, 31),
                known_as_of=dt.date(2026, 9, 18),
                accession_no="0000320193-26-000077",
            ),
        ),
        news=(
            NewsLine(
                news_id=77,
                headline="Apple reports third-quarter revenue of $94.9bn",
                url="https://example.test/apple-q3",
                source="Nairametrics",
                published_at=dt.datetime(2026, 9, 23, 9, 14, tzinfo=dt.UTC),
                known_as_of=dt.date(2026, 9, 23),
                tickers=("AAPL",),
                sentiment=SentimentLine(
                    label="positive", score=Decimal("0.62"), model="vader", model_version="3.3.2"
                ),
            ),
        ),
        macro=(
            MacroLine(
                code="US_10Y_TREASURY",
                name="US 10-year Treasury constant maturity rate",
                unit="percent",
                value=Decimal("4.96"),
                as_of_date=dt.date(2026, 9, 22),
                known_as_of=dt.date(2026, 9, 23),
                expected_lag_days=5,
                stale=False,
                newly_released=True,
            ),
        ),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The hash: what is in it, and what is deliberately not
# --------------------------------------------------------------------------------------


def test_the_hash_ignores_the_envelope_and_only_the_envelope() -> None:
    """The decision date and the recipient are not content, and everything else is.

    This is the pair of claims `packages.brief.content` makes in prose, checked
    mechanically. A hash containing the date would never collide and the idempotency
    guard would be decorative; a hash missing a figure would suppress a brief the reader
    can see has changed.
    """
    base = _brief()
    for other in (
        _brief(decision_date=dt.date(2026, 9, 25)),
        _brief(principal_name="Somebody Else"),
        _brief(principal_id=99),
    ):
        assert content_hash(other) == content_hash(base), (
            "the envelope leaked into the hash: a brief whose facts are unchanged must "
            "hash the same however it is addressed and whenever it is prepared"
        )
    # The two that are visible are visible only in the header, which is the single place
    # the "everything rendered is hashed" invariant is allowed an exception.
    assert render(_brief(decision_date=dt.date(2026, 9, 25))) != render(base)
    assert render(_brief(principal_name="Somebody Else")) != render(base)
    # The principal id is not shown at all; the unique constraint carries it instead.
    assert render(_brief(principal_id=99)) == render(base)
    header, body = render(base).split("\n", 1)
    assert DECISION.isoformat() in header
    assert DECISION.isoformat() not in body, (
        "the decision date reached the body, where the hash cannot see it"
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("window_days", 14),
        ("moves", (dataclasses.replace(_brief().moves[0], close=Decimal("332.4200")),)),
        ("moves", (dataclasses.replace(_brief().moves[0], change=Decimal("0.0033")),)),
        # Same figure, republished. A revision is news, and the vintage is what says so.
        (
            "moves",
            (dataclasses.replace(_brief().moves[0], known_as_of=dt.date(2026, 9, 17)),),
        ),
        ("filings", ()),
        (
            "filings",
            (dataclasses.replace(_brief().filings[0], filing_type="10-K"),),
        ),
        ("news", ()),
        (
            "news",
            (dataclasses.replace(_brief().news[0], sentiment=None),),
        ),
        (
            "macro",
            (dataclasses.replace(_brief().macro[0], stale=True),),
        ),
        ("news_gaps", ("the tagger has not run",)),
        ("macro_gaps", ("no macro series are registered",)),
        ("watchlist_gaps", ("this principal owns no watchlist",)),
    ],
)
def test_every_change_the_reader_can_see_changes_the_hash(field_name: str, value: object) -> None:
    """The invariant `content.py` rests on, one field at a time.

    Rendered text and hash must move together. If the text changed and the hash did not,
    a genuinely different brief would be suppressed as a duplicate - which is the failure
    `docs/03` P5.4 names as "too coarse".
    """
    base = _brief()
    other = _brief(**{field_name: value})
    assert render(other) != render(base), f"{field_name} is hashed but invisible to the reader"
    assert content_hash(other) != content_hash(base), (
        f"{field_name} is visible to the reader and invisible to the hash"
    )


def test_the_hash_is_a_sha256_of_the_canonical_payload() -> None:
    """Stated explicitly, so the column's `CHAR(64)` and the algorithm cannot drift apart."""
    brief = _brief()
    digest = content_hash(brief)
    assert len(digest) == 64
    assert digest == hashlib.sha256(canonical_payload(brief).encode("utf-8")).hexdigest()


def test_the_payload_holds_no_clock() -> None:
    """No date in the payload may be today's, because none of them is about today."""
    payload = canonical_payload(_brief())
    assert DECISION.isoformat() not in payload
    assert "Frank Oguguo" not in payload


# --------------------------------------------------------------------------------------
# The words: as-of dates, honest absence, no advice
# --------------------------------------------------------------------------------------


def test_every_figure_carries_its_as_of_date() -> None:
    """`docs/03` P5.4's output spec ends "with as-of dates on every figure"."""
    text = render(_brief())
    assert "332.4100 USD  as of 2026-09-16" in text
    assert "against 331.3400 of 2026-09-15" in text
    assert "filed 2026-09-18" in text and "period ended 2026-08-31" in text
    assert "4.96 percent  as of 2026-09-22 (known 2026-09-23)" in text
    assert "2026-09-23  Nairametrics" in text


def test_a_vintage_is_shown_only_when_it_differs_from_the_figures_own_date() -> None:
    """Noise suppression with a rule behind it: `(known ...)` means "learned later"."""
    same_day = render(_brief())
    assert "332.4100 USD  as of 2026-09-16\n" in same_day
    revised = render(
        _brief(moves=(dataclasses.replace(_brief().moves[0], known_as_of=dt.date(2026, 9, 18)),))
    )
    assert "332.4100 USD  as of 2026-09-16 (known 2026-09-18)" in revised


def test_a_stale_macro_figure_is_flagged_in_the_message() -> None:
    """`docs/03` P5 check 8, and `CLAUDE.md`'s standing rule that staleness is visible.

    The flag is a fact - the reading is older than the interval the series publishes on -
    and it is worded as one. It carries no day count, because a number that changes every
    morning would be text the idempotency hash cannot see.
    """
    overdue = dataclasses.replace(
        _brief().macro[0], code="NG_CPI_YOY", expected_lag_days=70, stale=True
    )
    text = render(_brief(macro=(overdue,)))
    assert "overdue: published about every 70 days" in text
    # An irregular series (the MPR moves when the MPC moves it) is judged by nobody.
    unjudgeable = dataclasses.replace(_brief().macro[0], code="NG_MPR", stale=None)
    assert "overdue" not in render(_brief(macro=(unjudgeable,)))


def test_nothing_to_report_is_claimed_only_when_the_search_happened() -> None:
    """The failure `docs/03` P5.4 cares most about, in one assertion pair.

    An empty section with no gaps looked and found nothing, and says so. An empty section
    with a gap could not look, and must not say the same words.
    """
    looked = render(_brief(news=()))
    assert "nothing to report" in looked

    could_not = render(_brief(news=(), news_gaps=("no article has been tagged to any security",)))
    news_block = could_not.split("NEWS")[1].split("MACRO")[0]
    assert "nothing to report" not in news_block
    assert "no article has been tagged to any security" in news_block


#: Words that turn a report into an instruction. Not a general-purpose advice detector -
#: `packages.compliance.banned_phrases` is that, and P4 fills its list. This is the narrow
#: guard `DATA_FOUNDATION.md` §6.5 asks of the brief: report what moved, not what to do.
_ADVICE_WORDS = (
    "buy",
    "sell",
    "hold",
    "recommend",
    "should",
    "target price",
    "undervalued",
    "overvalued",
    "opportunity",
    "outperform",
    "alert",
)


def test_the_brief_neither_advises_nor_nudges() -> None:
    """`DATA_FOUNDATION.md` §6.5, and `docs/03` P5 check 9.

    Two halves. The words are the obvious half. The emoji are the half that slips through
    review: "GTCO down 8%" is a fact and the same line with a warning sign after it is an
    editorial instruction, so the brief is held to pure ASCII and the test says why.
    """
    text = render(_brief())
    lowered = text.lower()
    found = [word for word in _ADVICE_WORDS if word in lowered]
    assert not found, f"advice phrasing in a brief: {found}"
    assert text.isascii(), (
        "a brief is ASCII: an emoji or an arrow is a judgement about a number, and "
        "DATA_FOUNDATION 6.5 does not allow the brief to make one"
    )


def test_the_brief_passes_the_banned_phrase_linter() -> None:
    """The mechanism, not the list. `packages/compliance/banned_phrases.py` is empty until
    P4 fills it; wiring the call now means P4 fills a list rather than hunting call sites."""
    from packages.compliance.banned_phrases import scan

    assert scan(render(_brief())) == []


def test_watchlist_lines_are_ordered_by_ticker_and_not_by_the_size_of_the_move() -> None:
    """Ordering is framing. Alphabetical means nothing, which is the intention."""
    moves = (
        Move("AAA", "A", "USD", Decimal("1"), DECISION, DECISION, Decimal("1"), DECISION, None),
        Move("ZZZ", "Z", "USD", Decimal("1"), DECISION, DECISION, Decimal("2"), DECISION, None),
    )
    text = render(_brief(moves=moves))
    assert text.index("AAA") < text.index("ZZZ")


def test_split_for_telegram_never_drops_a_line() -> None:
    """Telegram refuses a message over 4096 characters; a brief must not lose its tail."""
    text = "\n".join(f"line {index}" for index in range(2000))
    chunks = split_for_telegram(text, limit=200)
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert "\n".join(chunks) == text


def test_split_for_telegram_divides_a_line_too_long_to_fit() -> None:
    chunks = split_for_telegram("x" * 500, limit=100)
    assert len(chunks) == 5
    assert "".join(chunks) == "x" * 500


# --------------------------------------------------------------------------------------
# Channels the tests own
# --------------------------------------------------------------------------------------


@dataclass
class _Recorder:
    """A channel that delivers to a list. Used only where the test is about the guard."""

    name: str = "test"
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, *, recipient: str, text: str) -> None:
        self.sent.append((recipient, text))


@dataclass
class _Exploder:
    """A channel that fails *after* attempting, which is the un-retryable kind."""

    name: str = "test"

    def send(self, *, recipient: str, text: str) -> None:
        raise RuntimeError("the wire went away mid-request")


# --------------------------------------------------------------------------------------
# Database fixtures: three principals, two watchlists, real bars
# --------------------------------------------------------------------------------------


def _document(session: Session, marker: str) -> int:
    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Yahoo Finance")
    ).scalar_one()
    digest = hashlib.sha256(marker.encode()).hexdigest()
    document = SourceDocument(
        data_source_id=source_id,
        url=f"file:///{marker}.json",
        storage_key=f"documents/sha256/{digest}",
        sha256=digest,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    session.add(document)
    session.flush()
    return document.id


def _security(session: Session, ticker: str, name: str) -> int:
    exchange_id = session.execute(select(Exchange.id).where(Exchange.code == "NASDAQ")).scalar_one()
    company = Company(
        legal_name=name, country="US", statement_template="non_financial", fiscal_year_end=12
    )
    session.add(company)
    session.flush()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="USD")
    session.add(security)
    session.flush()
    session.add(
        SecurityIdentifier(
            security_id=security.id,
            id_type="ticker",
            id_value=ticker,
            valid_from=dt.date(2020, 1, 1),
            valid_to=None,
            exchange_id=exchange_id,
            is_primary=True,
            source="test",
        )
    )
    session.flush()
    return security.id


def _bars(session: Session, security_id: int, closes: dict[str, str]) -> None:
    document_id = _document(session, f"bars-{security_id}")
    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Yahoo Finance")
    ).scalar_one()
    for day, close in closes.items():
        session.add(
            PriceHistory(
                security_id=security_id,
                date=dt.date.fromisoformat(day),
                known_as_of=dt.date.fromisoformat(day),
                close_raw=Decimal(close),
                data_source_id=source_id,
                source_document_id=document_id,
            )
        )
    session.flush()


def _principal(session: Session, name: str) -> int:
    principal = Principal(display_name=name, kind="family")
    session.add(principal)
    session.flush()
    return principal.id


def _watchlist(session: Session, principal_id: int, security_ids: list[int]) -> None:
    watchlist = Watchlist(principal_id=principal_id, name="main")
    session.add(watchlist)
    session.flush()
    for security_id in security_ids:
        session.add(WatchlistItem(watchlist_id=watchlist.id, security_id=security_id))
    session.flush()


def _chat_id(session: Session, principal_id: int, value: str) -> None:
    session.add(
        SystemConfig(
            key=f"{TELEGRAM_CHAT_ID_PREFIX}.{principal_id}",
            value=value,
            effective_from=dt.date(2026, 1, 1),
            set_by="test",
            reason="delivery target for the P5.4 brief",
        )
    )
    session.flush()


@dataclass(frozen=True)
class _World:
    alice: int
    bob: int
    quiet: int


@pytest.fixture
def world(db_session: Session) -> Iterator[_World]:
    """Two principals with different watchlists, and one with a watchlist of a name that
    has never been priced - the honest empty case rather than a contrived one."""
    aapl = _security(db_session, "TAPL", "Test Apple Inc.")
    cat = _security(db_session, "TCAT", "Test Caterpillar Inc.")
    unpriced = _security(db_session, "TNIL", "Test Never Priced plc")
    _bars(db_session, aapl, {"2026-09-15": "331.34", "2026-09-16": "332.41"})
    _bars(db_session, cat, {"2026-09-15": "783.54", "2026-09-16": "782.72"})

    alice = _principal(db_session, "Alice")
    bob = _principal(db_session, "Bob")
    quiet = _principal(db_session, "Quiet")
    _watchlist(db_session, alice, [aapl])
    _watchlist(db_session, bob, [cat])
    _watchlist(db_session, quiet, [unpriced])
    for principal_id in (alice, bob, quiet):
        _chat_id(db_session, principal_id, f"chat-{principal_id}")
    db_session.commit()
    yield _World(alice=alice, bob=bob, quiet=quiet)


# --------------------------------------------------------------------------------------
# Check 6: run it twice, one message
# --------------------------------------------------------------------------------------


def test_the_same_brief_twice_sends_once(db_session: Session, world: _World) -> None:
    """`docs/03` P5 check 6, and the sentence behind it: *"a retry after a network blip
    that double-sends is how a useful bot becomes a muted one."*"""
    channel = _Recorder()
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)

    first = deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)
    second = deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)

    assert first.sent is True and first.status == SENT
    assert second.sent is False and second.status == SENT
    assert len(channel.sent) == 1, "the same content went down the wire twice"

    rows = (
        db_session.execute(select(AlertDelivery).where(AlertDelivery.principal_id == world.alice))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == SENT
    assert rows[0].delivered_at is not None
    assert rows[0].alert_id is None, "a brief has no rule behind it - migration 0029"


def test_running_the_whole_job_twice_sends_one_message_each(
    db_session: Session, world: _World
) -> None:
    """The check as `docs/03` phrases it - the *job* twice, not the delivery twice."""
    channel = _Recorder()
    first = run_daily_brief(db_session, decision_date=DECISION, channel=channel, now=NOW)
    second = run_daily_brief(db_session, decision_date=DECISION, channel=channel, now=NOW)

    assert len(first) == 3 and all(outcome.sent for outcome in first)
    assert len(second) == 3 and not any(outcome.sent for outcome in second)
    assert len(channel.sent) == 3, "one message per principal, not two"


def test_a_changed_figure_is_not_suppressed(db_session: Session, world: _World) -> None:
    """The other half of the requirement: too coarse a hash silences real news."""
    channel = _Recorder()
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)

    moved = dataclasses.replace(
        brief, moves=(dataclasses.replace(brief.moves[0], close=Decimal("999.99")),)
    )
    outcome = deliver(db_session, moved, channel=channel, recipient="chat", now=NOW)
    assert outcome.sent is True
    assert len(channel.sent) == 2


# --------------------------------------------------------------------------------------
# Check 7: per-principal isolation
# --------------------------------------------------------------------------------------


def test_two_principals_with_different_watchlists_get_different_briefs(
    db_session: Session, world: _World
) -> None:
    """`docs/03` P5 check 7. The scope differs, so the content differs, so the hash does."""
    alice = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    bob = collect_brief(db_session, principal_id=world.bob, decision_date=DECISION)

    assert [move.ticker for move in alice.moves] == ["TAPL"]
    assert [move.ticker for move in bob.moves] == ["TCAT"]
    assert content_hash(alice) != content_hash(bob)
    assert "TCAT" not in render(alice)
    assert "TAPL" not in render(bob)


def test_one_principals_delivery_does_not_suppress_anothers(
    db_session: Session, world: _World
) -> None:
    """Migration 0029: *"two people can be sent the same content and neither send
    suppresses the other."* Same content, two principals, two deliveries."""
    channel = _Recorder()
    alice = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    shared = dataclasses.replace(alice, principal_id=world.bob, principal_name="Bob")
    assert content_hash(alice) == content_hash(shared)

    assert deliver(db_session, alice, channel=channel, recipient="a", now=NOW).sent is True
    assert deliver(db_session, shared, channel=channel, recipient="b", now=NOW).sent is True
    assert len(channel.sent) == 2


def test_a_principal_without_a_watchlist_is_not_sent_a_brief(db_session: Session) -> None:
    """Owning a watchlist is the subscription; the public guest principal never asked."""
    lonely = _principal(db_session, "No watchlist here")
    db_session.commit()
    assert lonely not in [
        principal_id for principal_id, _ in principals_with_a_watchlist(db_session)
    ]


def test_a_disabled_principal_stops_receiving(db_session: Session, world: _World) -> None:
    """`principals.disabled_at` is the off switch, and a brief that kept arriving after it
    would make the switch a lie."""
    principal = db_session.get(Principal, world.bob)
    assert principal is not None
    principal.disabled_at = NOW
    db_session.flush()
    assert world.bob not in [pid for pid, _ in principals_with_a_watchlist(db_session)]


# --------------------------------------------------------------------------------------
# The empty case, which must say why
# --------------------------------------------------------------------------------------


def test_the_empty_case_says_what_it_could_not_look_at(db_session: Session, world: _World) -> None:
    """The failure this project cares most about: "nothing to report" when nothing could
    be looked at. Three sections, three different reasons, none of them silence."""
    brief = collect_brief(db_session, principal_id=world.quiet, decision_date=DECISION)
    text = render(brief)

    assert brief.moves[0].absent == "no price bar is known for this security"
    assert "no price bar is known" in text

    assert brief.filing_gaps, "a company with no filings at all is a gap, not an absence"
    assert "could not look" in " ".join(brief.filing_gaps)

    assert brief.news_gaps, "an empty news_tags is a gap, not an absence"
    assert "news_tags is empty" in " ".join(brief.news_gaps)

    news_block = text.split("NEWS")[1].split("MACRO")[0]
    assert "nothing to report" not in news_block


def test_a_principal_with_no_watchlist_is_told_the_brief_had_no_scope(
    db_session: Session,
) -> None:
    """Composing for a principal with no watchlist is legal and honest, not an error."""
    lonely = _principal(db_session, "Nobody's list")
    db_session.flush()
    brief = collect_brief(db_session, principal_id=lonely, decision_date=DECISION)
    text = render(brief)
    assert brief.watchlist_gaps
    assert "owns no watchlist" in text
    assert "there is nothing on the watchlist to price" in text


def test_the_decision_date_is_mandatory(db_session: Session, world: _World) -> None:
    """`docs/01` §5: forgetting it must be a TypeError, not a wrong number."""
    with pytest.raises(TypeError):
        collect_brief(db_session, principal_id=world.alice, decision_date="2026-09-24")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        collect_brief(db_session, principal_id=world.alice)  # type: ignore[call-arg]


def test_a_brief_for_an_earlier_date_cannot_see_later_bars(
    db_session: Session, world: _World
) -> None:
    """Point-in-time, checked rather than asserted in a docstring."""
    earlier = collect_brief(
        db_session, principal_id=world.alice, decision_date=dt.date(2026, 9, 15)
    )
    assert earlier.moves[0].bar_date == dt.date(2026, 9, 15)
    assert earlier.moves[0].change is None, "there is no earlier bar, so there is no change"


def test_the_watchlist_read_is_scoped_by_principal(db_session: Session, world: _World) -> None:
    assert [item.ticker for item in watchlist_for(db_session, principal_id=world.alice)] == ["TAPL"]
    assert [item.ticker for item in watchlist_for(db_session, principal_id=world.bob)] == ["TCAT"]


# --------------------------------------------------------------------------------------
# Delivery is gated, not faked
# --------------------------------------------------------------------------------------


def test_a_send_without_a_token_refuses_and_records_that_it_did(
    db_session: Session, world: _World
) -> None:
    """There is no bot token and none is coming. The row must say `suppressed`, carry no
    `delivered_at`, and never claim `sent` - which the `alert_deliveries_sent_has_a_time`
    CHECK is the second lock on."""
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    outcome = deliver(
        db_session, brief, channel=TelegramChannel(token=None), recipient="chat", now=NOW
    )

    assert outcome.sent is False
    assert outcome.status == SUPPRESSED
    assert "no Telegram bot token is configured" in outcome.reason

    row = db_session.execute(
        select(AlertDelivery).where(AlertDelivery.principal_id == world.alice)
    ).scalar_one()
    assert row.status == SUPPRESSED
    assert row.delivered_at is None
    assert row.channel == "telegram"


def test_the_channel_itself_refuses_before_touching_the_network() -> None:
    """`DeliveryRefused` means *nothing was attempted*, which is what makes a retry safe."""
    with pytest.raises(DeliveryRefused, match="no Telegram bot token"):
        TelegramChannel(token=None).send(recipient="chat", text="hello")
    with pytest.raises(DeliveryRefused, match="no Telegram chat id"):
        TelegramChannel(token="pretend-token").send(recipient="", text="hello")


def test_a_missing_chat_id_is_recorded_rather_than_skipped(
    db_session: Session, world: _World
) -> None:
    """A principal who owns a watchlist asked for a brief. Why they did not get one
    belongs in `alert_deliveries`, where somebody can see it."""
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    outcome = deliver(
        db_session, brief, channel=TelegramChannel(token="pretend"), recipient=None, now=NOW
    )
    assert outcome.status == SUPPRESSED
    assert "no Telegram chat id" in outcome.reason


def test_a_suppressed_brief_is_delivered_once_a_token_arrives(
    db_session: Session, world: _World
) -> None:
    """The reason `suppressed` is the one retryable status: nothing was ever sent, so the
    token-less runs of today must not block the first run that can deliver."""
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    deliver(db_session, brief, channel=TelegramChannel(token=None), recipient="chat", now=NOW)

    channel = _Recorder()
    outcome = deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)
    assert outcome.sent is True and outcome.status == SENT
    assert len(channel.sent) == 1

    rows = (
        db_session.execute(select(AlertDelivery).where(AlertDelivery.principal_id == world.alice))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the retry reuses the claim rather than writing a second row"
    assert rows[0].status == SENT and rows[0].delivered_at is not None


def test_a_send_that_raised_after_attempting_is_never_retried(
    db_session: Session, world: _World
) -> None:
    """An HTTP call that raised may still have been delivered, so the content stays
    claimed. Over-sending is the named danger; a stuck row is visible and a person can
    act on it."""
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    failed = deliver(db_session, brief, channel=_Exploder(), recipient="chat", now=NOW)
    assert failed.status == "failed" and failed.sent is False

    channel = _Recorder()
    again = deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)
    assert again.sent is False
    assert channel.sent == []

    row = db_session.execute(
        select(AlertDelivery).where(AlertDelivery.principal_id == world.alice)
    ).scalar_one()
    assert row.status == "failed"
    assert row.delivered_at is None


def test_no_delivery_row_ever_claims_to_be_sent_without_a_time(
    db_session: Session, world: _World
) -> None:
    """The invariant the CHECK constraint also holds, asserted where it is easier to read."""
    brief = collect_brief(db_session, principal_id=world.alice, decision_date=DECISION)
    for channel in (TelegramChannel(token=None), _Exploder(), _Recorder()):
        deliver(db_session, brief, channel=channel, recipient="chat", now=NOW)
    rows = db_session.execute(select(AlertDelivery)).scalars().all()
    assert rows
    for row in rows:
        assert (row.status == SENT) == (row.delivered_at is not None)
        assert row.status != PENDING, "a delivery left pending is a delivery nobody resolved"


def test_the_whole_job_refuses_loudly_with_no_token(db_session: Session, world: _World) -> None:
    """End to end in the state this session is actually in: three subscribers, no token,
    three honest `suppressed` rows and not one message."""
    outcomes = run_daily_brief(
        db_session, decision_date=DECISION, channel=TelegramChannel(token=None), now=NOW
    )
    assert len(outcomes) == 3
    assert all(outcome.status == SUPPRESSED and not outcome.sent for outcome in outcomes)
    rows = db_session.execute(select(AlertDelivery)).scalars().all()
    assert len(rows) == 3
    assert not any(row.status == SENT for row in rows)


def test_the_recipient_is_read_from_dated_config(db_session: Session, world: _World) -> None:
    assert recipient_for(db_session, principal_id=world.alice, on=DECISION) == f"chat-{world.alice}"
    assert recipient_for(db_session, principal_id=99999, on=DECISION) is None
