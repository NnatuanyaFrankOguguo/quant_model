"""P3 exit check 4: a 2-for-1 split produces a continuous adjusted series. TG2, TG12.

`docs/03` P3 names this file by path and states the expected result:

    | 4 | **Split adjustment** | `pytest tests/unit/test_corporate_actions.py` | A 2-for-1
    split produces a *continuous* adjusted series - no artificial 50% drop |

The check existed and the file did not, which is the one shape of gap a phase gate cannot
catch: the command fails to collect, and a suite that never ran reports nothing.

`OPERATIONS.md` §1.1 calls this the highest-priority gap and gives four hard rules. Three of
them are testable here and are tested:

1. `price_history` stores raw as-traded prices only, never back-adjusted in place. So every
   test below asserts `close_raw` is untouched alongside the adjusted figure.
2. Adjusted series are computed on read, applying only adjustments with
   `known_as_of <= decision_date`. That is `test_an_action_announced_after_the_decision_date`,
   and it is the TG12 leak: *"a corporate action CAN be announced after its own ex-date"*.
4. Corporate actions get the same provenance treatment as line items. The schema enforces it
   (`source_document_id NOT NULL`), so the fixtures here cannot avoid carrying a document.

## The ratio convention, which was a comment in three places and a test in none

`ratio_from` is the shares held **before**, `ratio_to` the shares held **after**, and
`adjustment_factors.factor` is `ratio_from / ratio_to`. That single rule covers all three
ratio actions, and the three documents that mention it agree once it is stated that way:

| Action | Held before | Held after | from/to | factor | Effect on a pre-ex price |
|---|---|---|---|---|---|
| 2-for-1 split | 1 | 2 | 1/2 | 0.5 | halved, matching the halved quote |
| 1-for-4 bonus | 4 | 5 | 4/5 | 0.8 | down 20%, which `OPERATIONS` §1.1 states |
| 1-for-4 consolidation | 4 | 1 | 4/1 | 4.0 | quadrupled, matching the quadrupled quote |

Only `split` has ever been written: `packages/ingestion/yahoo.py` writes a factor for splits
and for nothing else, and the live table holds 138 factors against 138 splits and no `bonus`,
`rights` or `consolidation` row at all. So the two Nigerian-relevant orientations were
entirely unexercised, and a sign error in either reproduces exactly the silent corruption the
table exists to prevent. They are pinned below against real events.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.adjust import adjusted_close, cumulative_factor, factors_known
from packages.common.identity import CIK, resolve_security
from packages.common.models import (
    AdjustmentFactor,
    CorporateAction,
    DataSource,
    PriceHistory,
    SourceDocument,
)
from packages.common.storage import LocalDiskBackend
from packages.common.timez import utctoday
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.edgar import EdgarSubmissionsConnector

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UA = "quant_model test suite (nnatuanyafrankoguguo@churchofjesuschrist.org)"
APPLE_CIK = "0000320193"

#: A 2-for-1 split: the quote halves overnight and the holder is no poorer.
SPLIT_EX = dt.date(2026, 6, 15)
#: Transnational Corporation's 1-for-4 share capital reconstruction, 28 October 2024
#: (`docs/UNIVERSE.md` §1: *"a corporate action this database must hold, not a curiosity"*).
#: 40.6bn shares became 10.2bn, and the quote appeared to quadruple.
TRANSCORP_EX = dt.date(2024, 10, 28)


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    return store


@pytest.fixture
def security(db_session: Session, local_store: LocalDiskBackend) -> Iterator[int]:
    """One registered security to hang bars and actions off."""
    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    connector.fetch = lambda **params: RawResponse(  # type: ignore[method-assign]
        data=(FIXTURES / "edgar" / "AAPL_submissions_trimmed.json").read_bytes(),
        media_type="application/json",
        url="s",
    )
    assert connector.run(db_session, cik=APPLE_CIK).status == "ok"
    resolved = resolve_security(db_session, value=APPLE_CIK, as_of=utctoday(), id_type=CIK)
    assert resolved is not None
    yield resolved.security_id


def _document(session: Session, marker: str) -> int:
    """A source document, because every action and every bar must cite one.

    The digest is a real hash of the marker plus a counter, not a repeated letter.
    `source_documents.sha256` is UNIQUE — that is the content addressing P3 check 1 rests on
    — so two documents in one test must differ, and the first version of this helper made
    them collide.
    """
    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Yahoo Finance")
    ).scalar_one()
    _document.issued = getattr(_document, "issued", 0) + 1  # type: ignore[attr-defined]
    digest = hashlib.sha256(f"{marker}:{_document.issued}".encode()).hexdigest()  # type: ignore[attr-defined]
    document = SourceDocument(
        data_source_id=source_id,
        url=f"file:///{marker}-{_document.issued}.json",  # type: ignore[attr-defined]
        storage_key=f"documents/sha256/{digest}",
        sha256=digest,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    session.add(document)
    session.flush()
    return document.id


def _bars(session: Session, security_id: int, closes: dict[str, str]) -> None:
    """Raw as-traded closes, each first known on its own trading day."""
    document_id = _document(session, "bars")
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


def _action(
    session: Session,
    security_id: int,
    *,
    action_type: str,
    ex_date: dt.date,
    ratio_from: str | None = None,
    ratio_to: str | None = None,
    cash_amount: str | None = None,
    known_as_of: dt.date | None = None,
    write_factor: bool = True,
) -> int:
    """One action, and its own factor unless the caller is testing the absence of one."""
    document_id = _document(session, "actions")
    action = CorporateAction(
        security_id=security_id,
        action_type=action_type,
        ex_date=ex_date,
        ratio_from=Decimal(ratio_from) if ratio_from else None,
        ratio_to=Decimal(ratio_to) if ratio_to else None,
        cash_amount=Decimal(cash_amount) if cash_amount else None,
        currency="USD",
        source_document_id=document_id,
        known_as_of=known_as_of or ex_date,
    )
    session.add(action)
    session.flush()
    if write_factor and ratio_from and ratio_to:
        session.add(
            AdjustmentFactor(
                security_id=security_id,
                ex_date=ex_date,
                action_id=action.id,
                factor=Decimal(ratio_from) / Decimal(ratio_to),
                known_as_of=action.known_as_of,
                source_document_id=document_id,
            )
        )
        session.flush()
    return action.id


# --------------------------------------------------------------------------------------
# P3 check 4, stated: a 2-for-1 split produces a continuous adjusted series
# --------------------------------------------------------------------------------------


def test_a_two_for_one_split_produces_a_continuous_adjusted_series(
    db_session: Session, security: int
) -> None:
    """The check `docs/03` names. The quote halves; the adjusted series does not notice.

    Four bars either side of the ex-date, with the raw quote stepping 100 -> 50 across it. On
    the raw series that is a 50% crash and any momentum or drawdown measure reads it as one.
    On the adjusted series the step must vanish, because nothing happened to the holder.
    """
    _bars(
        db_session,
        security,
        {
            "2026-06-11": "100.00",
            "2026-06-12": "100.00",
            "2026-06-15": "50.00",  # ex-date: the quote halves
            "2026-06-16": "50.00",
        },
    )
    _action(
        db_session, security, action_type="split", ex_date=SPLIT_EX, ratio_from="1", ratio_to="2"
    )

    decision = dt.date(2026, 7, 1)
    series = [
        adjusted_close(
            db_session,
            security_id=security,
            date=dt.date.fromisoformat(day),
            decision_date=decision,
        )
        for day in ("2026-06-11", "2026-06-12", "2026-06-15", "2026-06-16")
    ]
    assert all(bar is not None for bar in series)
    adjusted = [bar.close_adjusted for bar in series if bar is not None]

    assert adjusted == [Decimal("50.00"), Decimal("50.00"), Decimal("50.00"), Decimal("50.00")], (
        "the adjusted series must be flat across the split"
    )

    # The raw series is untouched, and still shows the step. OPERATIONS §1.1 hard rule 1.
    raw = [bar.close_raw for bar in series if bar is not None]
    assert raw == [Decimal("100.00"), Decimal("100.00"), Decimal("50.00"), Decimal("50.00")]

    # And say plainly what "no artificial drop" means as a number.
    before, across = adjusted[1], adjusted[2]
    assert (across - before) / before == Decimal(0), "no artificial 50% drop"


def test_the_factor_applies_to_bars_before_the_ex_date_and_not_on_it(
    db_session: Session, security: int
) -> None:
    """The boundary. The ex-date bar already trades at the new price, so it is not adjusted.

    Off by one day here and every series is wrong by the whole factor for exactly one bar -
    the least visible error this module can make, and the one a chart would never show.
    """
    _bars(db_session, security, {"2026-06-12": "100.00", "2026-06-15": "50.00"})
    _action(
        db_session, security, action_type="split", ex_date=SPLIT_EX, ratio_from="1", ratio_to="2"
    )
    decision = dt.date(2026, 7, 1)

    before = adjusted_close(
        db_session, security_id=security, date=dt.date(2026, 6, 12), decision_date=decision
    )
    on_ex = adjusted_close(db_session, security_id=security, date=SPLIT_EX, decision_date=decision)
    assert before is not None and on_ex is not None
    assert before.factor == Decimal("0.5") and before.actions_applied == 1
    assert on_ex.factor == Decimal(1) and on_ex.actions_applied == 0, (
        "the ex-date bar is already quoted post-split"
    )


# --------------------------------------------------------------------------------------
# The ratio convention, for the two orientations nothing has ever written
# --------------------------------------------------------------------------------------


def test_a_one_for_four_bonus_issue_removes_the_twenty_percent_step(
    db_session: Session, security: int
) -> None:
    """`OPERATIONS.md` §1.1: *"a 1-for-4 bonus drops the price ~20% overnight with no
    economic loss"*, and it calls this more consequential on NGX than on US markets because
    Nigerian issuers do it frequently.

    Five shares for every four held, so `ratio_from=4`, `ratio_to=5`, factor 0.8. A holder
    with 4 shares at 100 has 400 before and 5 at 80 after: the same 400.
    """
    _bars(db_session, security, {"2026-06-12": "100.00", "2026-06-15": "80.00"})
    _action(
        db_session, security, action_type="bonus", ex_date=SPLIT_EX, ratio_from="4", ratio_to="5"
    )
    decision = dt.date(2026, 7, 1)

    before = adjusted_close(
        db_session, security_id=security, date=dt.date(2026, 6, 12), decision_date=decision
    )
    after = adjusted_close(db_session, security_id=security, date=SPLIT_EX, decision_date=decision)
    assert before is not None and after is not None
    assert before.factor == Decimal("0.8")
    assert before.close_adjusted == after.close_adjusted == Decimal("80.00"), (
        "the 20% step is presentational, and must not survive adjustment"
    )


def test_transcorps_one_for_four_consolidation_does_not_look_like_a_quadrupling(
    db_session: Session, security: int
) -> None:
    """The real event `docs/UNIVERSE.md` §1 says this database must hold, on its real date.

    28 October 2024: 40.6bn shares reconstructed to 10.2bn, one share for every four held,
    which drove *"the reported ~300% price move that month"*. Unadjusted, a screen ranks
    Transcorp as the best-performing stock on the exchange for a month in which a holder
    gained nothing.

    Four held becoming one is the inverse orientation of a split: `ratio_from=4`,
    `ratio_to=1`, factor 4.0, and pre-ex prices are multiplied *up* to meet the new quote.
    """
    _bars(db_session, security, {"2024-10-25": "11.05", "2024-10-28": "44.20"})
    _action(
        db_session,
        security,
        action_type="consolidation",
        ex_date=TRANSCORP_EX,
        ratio_from="4",
        ratio_to="1",
    )
    decision = dt.date(2024, 12, 31)

    before = adjusted_close(
        db_session, security_id=security, date=dt.date(2024, 10, 25), decision_date=decision
    )
    after = adjusted_close(
        db_session, security_id=security, date=TRANSCORP_EX, decision_date=decision
    )
    assert before is not None and after is not None
    assert before.factor == Decimal(4)
    assert before.close_adjusted == Decimal("44.20"), "11.05 x 4 meets the relisting price"
    assert after.close_adjusted == Decimal("44.20")
    assert before.close_raw == Decimal("11.05"), "the as-traded price is still recoverable"


def test_the_three_ratio_orientations_are_one_rule(db_session: Session, security: int) -> None:
    """`ratio_from` is shares held before, `ratio_to` shares held after, factor is from/to.

    Stated once, as a test, because it was previously a comment in `0015`, a different
    comment in `OPERATIONS` §1.1, and a third in `docs/08` - none of which agreed on an
    example, though all three agree on the rule.
    """
    cases = {
        ("split", "1", "2"): Decimal("0.5"),
        ("bonus", "4", "5"): Decimal("0.8"),
        ("consolidation", "4", "1"): Decimal(4),
    }
    for (action_type, held_before, held_after), expected in cases.items():
        action_id = _action(
            db_session,
            security,
            action_type=action_type,
            ex_date=dt.date(2026, 3, 1) + dt.timedelta(days=len(action_type)),
            ratio_from=held_before,
            ratio_to=held_after,
        )
        factor = db_session.execute(
            select(AdjustmentFactor.factor).where(AdjustmentFactor.action_id == action_id)
        ).scalar_one()
        assert factor == expected, f"{action_type} {held_before}->{held_after}"


# --------------------------------------------------------------------------------------
# Point in time: TG12, the action announced after its own ex-date
# --------------------------------------------------------------------------------------


def test_an_action_announced_after_the_decision_date_is_not_applied(
    db_session: Session, security: int
) -> None:
    """`OPERATIONS.md` §1.1 hard rule 2, and the leak `known_as_of` exists to close.

    `docs/08` §2.4: *"A corporate action CAN be announced after its own ex-date - that is
    exactly the leak this column closes."* A backtest deciding on 20 June must see the
    unadjusted series, because on that day nobody knew the split had happened.

    The live table has no such row - every stored action was first seen on its ex-date - so
    this path has never occurred in the data and is only covered here.
    """
    _bars(db_session, security, {"2026-06-12": "100.00"})
    _action(
        db_session,
        security,
        action_type="split",
        ex_date=SPLIT_EX,
        ratio_from="1",
        ratio_to="2",
        known_as_of=dt.date(2026, 6, 30),  # announced a fortnight after the ex-date
    )

    blind = adjusted_close(
        db_session,
        security_id=security,
        date=dt.date(2026, 6, 12),
        decision_date=dt.date(2026, 6, 20),
    )
    informed = adjusted_close(
        db_session,
        security_id=security,
        date=dt.date(2026, 6, 12),
        decision_date=dt.date(2026, 7, 1),
    )
    assert blind is not None and informed is not None
    assert blind.factor == Decimal(1) and blind.actions_applied == 0, "not yet knowable"
    assert informed.factor == Decimal("0.5") and informed.actions_applied == 1
    assert blind.close_raw == informed.close_raw, "the raw bar never changes"


def test_a_corrected_ratio_is_a_new_vintage_and_the_newest_one_wins(
    db_session: Session, security: int
) -> None:
    """`0015`: *"a corrected ratio is a second row, never an edit"*, held by `no_update`.

    Both vintages stay readable, so a decision taken before the correction can still be
    reproduced with the factor that was believed then.
    """
    document_id = _document(db_session, "corrected")
    action_id = _action(
        db_session, security, action_type="split", ex_date=SPLIT_EX, ratio_from="1", ratio_to="2"
    )
    db_session.add(
        AdjustmentFactor(
            security_id=security,
            ex_date=SPLIT_EX,
            action_id=action_id,  # the same action, re-stated
            factor=Decimal("0.25"),
            known_as_of=dt.date(2026, 7, 10),
            source_document_id=document_id,
        )
    )
    db_session.flush()

    as_first_believed = factors_known(
        db_session, security_id=security, decision_date=dt.date(2026, 7, 1)
    )
    after_correction = factors_known(
        db_session, security_id=security, decision_date=dt.date(2026, 7, 20)
    )
    assert [factor for _ex, factor in as_first_believed] == [Decimal("0.5")]
    assert [factor for _ex, factor in after_correction] == [Decimal("0.25")], (
        "one factor per action, at its newest vintage - not two multiplied together"
    )


def test_a_cash_dividend_gets_no_adjustment_factor(db_session: Session, security: int) -> None:
    """`docs/08` §2.4 decided this: *"A dividend's factor is not written - adjusting a price
    series for cash dividends is a total-return choice for P6/P7 to make explicitly."*

    It matters for scope: cash dividends are most of what a Nigerian issuer announces, and
    none of them move the price series. The price-correctness payload is the ratio actions.
    """
    _bars(db_session, security, {"2026-06-12": "100.00"})
    _action(db_session, security, action_type="dividend", ex_date=SPLIT_EX, cash_amount="2.50")

    factors = factors_known(db_session, security_id=security, decision_date=dt.date(2026, 7, 1))
    assert factors == [], "a dividend is recorded, and does not adjust the series"
    bar = adjusted_close(
        db_session,
        security_id=security,
        date=dt.date(2026, 6, 12),
        decision_date=dt.date(2026, 7, 1),
    )
    assert bar is not None and bar.factor == Decimal(1)


def test_several_actions_compound_in_the_order_they_happened(
    db_session: Session, security: int
) -> None:
    """A bar before both a bonus and a split carries the product of the two factors.

    `adjustment_factors` holds one factor per action and never a running product, so the
    multiplication happens on read. Storing the cumulative figure instead would mean every
    earlier row had to be rewritten each time a new action arrived - into a table the
    `no_update` trigger forbids rewriting.
    """
    _bars(db_session, security, {"2026-01-05": "100.00"})
    _action(
        db_session,
        security,
        action_type="bonus",
        ex_date=dt.date(2026, 3, 2),
        ratio_from="4",
        ratio_to="5",
    )
    _action(
        db_session, security, action_type="split", ex_date=SPLIT_EX, ratio_from="1", ratio_to="2"
    )

    bar = adjusted_close(
        db_session,
        security_id=security,
        date=dt.date(2026, 1, 5),
        decision_date=dt.date(2026, 7, 1),
    )
    assert bar is not None
    assert bar.actions_applied == 2
    assert bar.factor == Decimal("0.4"), "0.8 x 0.5, applied to a bar that predates both"
    assert bar.close_adjusted == Decimal("40.00")


def test_the_pure_helper_takes_only_factors_dated_after_the_bar() -> None:
    """`cumulative_factor` is pure, so the ordering rule is checkable without a database."""
    factors = [
        (dt.date(2026, 3, 2), Decimal("0.8")),
        (dt.date(2026, 6, 15), Decimal("0.5")),
    ]
    assert cumulative_factor(dt.date(2026, 1, 5), factors) == (Decimal("0.40"), 2)
    assert cumulative_factor(dt.date(2026, 4, 1), factors) == (Decimal("0.5"), 1)
    assert cumulative_factor(dt.date(2026, 6, 15), factors) == (Decimal(1), 0)
    assert cumulative_factor(dt.date(2026, 7, 1), factors) == (Decimal(1), 0)


def test_adjustment_refuses_to_default_the_decision_date(
    db_session: Session, security: int
) -> None:
    """There is no "today" in a point-in-time read: the caller must say when it is deciding.

    A default would make lookahead the easy path, which `SPEC.md` §4.1 forbids and P7 check
    19 tests for.
    """
    with pytest.raises(TypeError, match="no default of today"):
        adjusted_close(
            db_session,
            security_id=security,
            date=dt.date(2026, 6, 12),
            decision_date=None,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------------------
# What the schema itself refuses
# --------------------------------------------------------------------------------------


def test_a_ratio_action_without_a_ratio_is_refused(db_session: Session, security: int) -> None:
    """`ratio_action_has_a_ratio`. A split with no ratio yields no factor and no error later."""
    document_id = _document(db_session, "noratio")
    with pytest.raises(Exception, match="ratio_action_has_a_ratio"), db_session.begin_nested():
        db_session.add(
            CorporateAction(
                security_id=security,
                action_type="split",
                ex_date=SPLIT_EX,
                source_document_id=document_id,
                known_as_of=SPLIT_EX,
            )
        )
        db_session.flush()


def test_a_dividend_without_an_amount_is_refused(db_session: Session, security: int) -> None:
    """`dividend_has_an_amount`. A dividend of nothing is a row that means nothing."""
    document_id = _document(db_session, "noamount")
    with pytest.raises(Exception, match="dividend_has_an_amount"), db_session.begin_nested():
        db_session.add(
            CorporateAction(
                security_id=security,
                action_type="dividend",
                ex_date=SPLIT_EX,
                source_document_id=document_id,
                known_as_of=SPLIT_EX,
            )
        )
        db_session.flush()


def test_an_invented_action_type_is_refused(db_session: Session, security: int) -> None:
    """`corporate_actions_type` permits five. `OPERATIONS` §1.1's comment named seven.

    The enum is `split|bonus|rights|dividend|consolidation`, so a capital reduction - which
    is what Transcorp's reconstruction legally was, under CAMA 2020 §§130-133 - is stored as
    `consolidation`, and a delisting is not a corporate action row at all.
    """
    document_id = _document(db_session, "badtype")
    with pytest.raises(Exception, match="corporate_actions_type"), db_session.begin_nested():
        db_session.add(
            CorporateAction(
                security_id=security,
                action_type="capital_reduction",
                ex_date=SPLIT_EX,
                source_document_id=document_id,
                known_as_of=SPLIT_EX,
            )
        )
        db_session.flush()


def test_an_action_cannot_be_edited_once_written(db_session: Session, security: int) -> None:
    """The `no_update` trigger. A wrong ratio is corrected by a new vintage, not in place."""
    from sqlalchemy import text

    action_id = _action(
        db_session, security, action_type="split", ex_date=SPLIT_EX, ratio_from="1", ratio_to="2"
    )
    db_session.commit()
    with pytest.raises(Exception, match="UPDATE forbidden"):
        db_session.execute(
            text("UPDATE corporate_actions SET ratio_to = 3 WHERE id = :id"), {"id": action_id}
        )
    db_session.rollback()


def test_a_factor_of_zero_is_refused(db_session: Session, security: int) -> None:
    """`adjustment_factor_positive`. A zero factor silently zeroes every earlier price."""
    document_id = _document(db_session, "zerofactor")
    action_id = _action(
        db_session,
        security,
        action_type="split",
        ex_date=SPLIT_EX,
        ratio_from="1",
        ratio_to="2",
        write_factor=False,
    )
    with pytest.raises(Exception, match="adjustment_factor_positive"), db_session.begin_nested():
        db_session.add(
            AdjustmentFactor(
                security_id=security,
                ex_date=SPLIT_EX,
                action_id=action_id,
                factor=Decimal(0),
                known_as_of=SPLIT_EX,
                source_document_id=document_id,
            )
        )
        db_session.flush()
