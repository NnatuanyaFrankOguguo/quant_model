"""A key may only be used by a statement its template allows. P4.6.

`TEAM_BRIEF.md` Part 3 item 2 states the failure this guards against, and states it
bluntly: *"GTCO's income statement has no 'revenue' line - it has gross earnings, net
interest income, and impairments. A schema built on MTN will not survive a bank."*
`DATA_FOUNDATION.md` §3.4 prescribes the fix - a `statement_template` per industry, with a
parallel chart for banks.

The reason it needs a structural check rather than a review is the shape of the mistake.
Mapping a bank's `gross_earnings` onto `revenue` produces a number that is real, is
correctly extracted, has honest provenance, and passes every arithmetic identity in P4.3 -
and means something different from the `revenue` beside it in a comparison. `docs/03` P4
check 18 says so in as many words: *"This is the failure that survives every automated
check, because both numbers are real and both are plausible."*

So the check is not on the figures. It is on the vocabulary: a `financial` key on a
`non_financial` statement is a structural impossibility, whatever the figure attached to it
says. This is the query that makes it one.

Currently clean across the whole database - 8,212 statements under two chart versions, no
key outside its template and no key without a chart row. These tests exist so it stays that
way through the next chart version, which is where the risk actually lives: `0020` carried
v0.1's mappings forward into v1, and a carry-forward that moved a key between templates
would produce exactly this and nothing else would notice.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Security,
    SourceDocument,
    Statement,
    StatementLineItem,
)

pytestmark = pytest.mark.invariant

#: A bank's income statement, in the bank chart's own words. No `revenue` line, because a
#: bank does not have one - which is the whole of `TEAM_BRIEF.md` Part 3 item 2.
BANK_FIGURES = {
    "gross_earnings": Decimal("1250000"),
    "interest_income": Decimal("900000"),
    "interest_expense": Decimal("-300000"),
    "net_interest_income": Decimal("600000"),
    "profit_before_tax": Decimal("400000"),
    "income_tax": Decimal("-60000"),
    "profit_after_tax": Decimal("340000"),
}
#: The same company-shaped facts for a manufacturer, in the words a manufacturer uses.
INDUSTRIAL_FIGURES = {
    "revenue": Decimal("2000000"),
    "cost_of_revenue": Decimal("-1400000"),
    "gross_profit": Decimal("600000"),
    "profit_before_tax": Decimal("400000"),
    "income_tax": Decimal("-60000"),
    "profit_after_tax": Decimal("340000"),
}
PERIOD_END = dt.date(2024, 12, 31)


def _document(session: Session, marker: str) -> int:
    source_id = session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    row = SourceDocument(
        data_source_id=source_id,
        url=f"file:///chart-template-{marker}.json",
        storage_key="documents/sha256/" + marker * 64,
        sha256=marker * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    session.add(row)
    session.flush()
    return row.id


def _typed_company(
    session: Session, *, name: str, template: str, figures: dict[str, Decimal], marker: str
) -> int:
    """One company, one income statement, and its figures - typed through chart v1.

    Written straight in rather than through an extraction path, because these tests must be
    able to see badly typed data if any ever exists. A fixture that can only produce
    correct rows cannot demonstrate that the check would catch incorrect ones.
    """
    exchange_id = session.execute(select(Exchange.id).order_by(Exchange.id)).scalars().first()
    document_id = _document(session, marker)
    company = Company(
        legal_name=name, country="NG", statement_template=template, fiscal_year_end=12
    )
    session.add(company)
    session.flush()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
    session.add(security)
    session.flush()
    chart_template = "financial" if template == "bank" else "non_financial"
    statement = Statement(
        company_id=company.id,
        statement_type="income",
        period_type="FY",
        period_end=PERIOD_END,
        fiscal_year=PERIOD_END.year,
        calendar_year=PERIOD_END.year,
        period_label=f"FY{PERIOD_END.year}",
        presentation_currency="NGN",
        presentation_multiplier=1,
        is_audited=True,
        is_consolidated=True,
        statement_template=chart_template,
        chart_version="v1",
        version=1,
        known_as_of=PERIOD_END + dt.timedelta(days=120),
        source_document_id=document_id,
    )
    session.add(statement)
    session.flush()
    for key, value in figures.items():
        session.add(
            StatementLineItem(
                statement_id=statement.id,
                security_id=security.id,
                canonical_key=key,
                chart_version="v1",
                value=value,
                currency="NGN",
                unit_multiplier=1,
                period_end=PERIOD_END,
                known_as_of=PERIOD_END + dt.timedelta(days=120),
                version=1,
                correction_type="none",
                source_document_id=document_id,
                page=1,
                extraction_method="manual",
            )
        )
    session.flush()
    return statement.id


@pytest.fixture
def one_of_each(db_session: Session) -> tuple[int, int]:
    """A bank and an industrial, so the queries below have something to be wrong about."""
    bank = _typed_company(
        db_session,
        name="zz-test-chart Bank Plc",
        template="bank",
        figures=BANK_FIGURES,
        marker="a",
    )
    industrial = _typed_company(
        db_session,
        name="zz-test-chart Manufacturing Plc",
        template="non_financial",
        figures=INDUSTRIAL_FIGURES,
        marker="b",
    )
    return bank, industrial


def test_the_fixture_actually_wrote_rows(db_session: Session, one_of_each: tuple[int, int]) -> None:
    """Asserted first, because every check below is a search for bad rows.

    Against an empty table each of them finds none and reports green - which is the silent
    pass this whole file exists to prevent, arriving inside the file that prevents it.
    """
    written = db_session.execute(
        text(
            "SELECT count(*) FROM statement_line_items li JOIN statements st "
            "ON st.id = li.statement_id WHERE st.id IN (:bank, :industrial)"
        ),
        {"bank": one_of_each[0], "industrial": one_of_each[1]},
    ).scalar_one()
    assert written == len(BANK_FIGURES) + len(INDUSTRIAL_FIGURES)


#: The template that means "this key is universal". `profit_after_tax` is the same fact for
#: a bank and a manufacturer, and duplicating it per template would be the real error.
BOTH = "both"

_OUT_OF_TEMPLATE = text("""
    SELECT st.chart_version,
           st.statement_template AS statement_template,
           a.template            AS key_template,
           li.canonical_key,
           count(*)              AS rows_affected
      FROM statement_line_items li
      JOIN statements st ON st.id = li.statement_id
      JOIN chart_of_accounts a ON a.canonical_key = li.canonical_key
                              AND a.chart_version = st.chart_version
     WHERE a.template <> :both
       AND a.template <> st.statement_template
     GROUP BY 1, 2, 3, 4
     ORDER BY 5 DESC
""")

_ORPHANED = text("""
    SELECT st.chart_version, li.canonical_key, count(*) AS rows_affected
      FROM statement_line_items li
      JOIN statements st ON st.id = li.statement_id
     WHERE NOT EXISTS (
               SELECT 1 FROM chart_of_accounts a
                WHERE a.canonical_key = li.canonical_key
                  AND a.chart_version = st.chart_version)
     GROUP BY 1, 2
     ORDER BY 3 DESC
""")


def test_no_key_is_used_outside_the_template_that_declares_it(
    db_session: Session, one_of_each: tuple[int, int]
) -> None:
    """The bank-versus-industrial vocabulary boundary, enforced rather than reviewed.

    A `financial` key on a `non_financial` statement - or the reverse - is the
    `gross_earnings` → `revenue` mistake in its structural form. `both` is exempt because
    that is what `both` is for.
    """
    offenders = db_session.execute(_OUT_OF_TEMPLATE, {"both": BOTH}).all()
    assert not offenders, (
        "a canonical key is being used by a statement whose template does not declare it, "
        "which is how a bank's gross earnings end up in a column labelled revenue:\n"
        + "\n".join(
            f"  {r.chart_version}: {r.canonical_key!r} is a {r.key_template} key on "
            f"{r.rows_affected} {r.statement_template} rows"
            for r in offenders
        )
    )


def test_every_stored_key_exists_in_the_chart_version_it_was_stored_under(
    db_session: Session,
    one_of_each: tuple[int, int],
) -> None:
    """An orphan is a key that resolved once and does not any more.

    `chart_version` is in the primary key precisely so a new vocabulary costs a version
    rather than a re-extraction, and migration `0020` carried v0.1's mappings into v1 with
    a guard for exactly this. The guard runs at migration time, once; this runs against
    what is actually stored, every time.
    """
    orphans = db_session.execute(_ORPHANED).all()
    assert not orphans, (
        "stored line items whose canonical key has no row in their chart version - the key "
        "resolved when it was written and does not now:\n"
        + "\n".join(
            f"  {r.chart_version}: {r.canonical_key!r} on {r.rows_affected} rows" for r in orphans
        )
    )


def test_the_rival_top_lines_never_appear_on_one_statement(
    db_session: Session, one_of_each: tuple[int, int]
) -> None:
    """`revenue` and `gross_earnings` are two answers to one question.

    A statement carrying both has been typed through two vocabularies at once, and whichever
    of the two a later comparison picks up, half the companies in it mean something else.
    Narrower than the template check above and kept separate because it is the specific
    case `TEAM_BRIEF.md` names, and a reader looking for that case should find a test with
    its name on it.
    """
    both = db_session.execute(
        text("""
        SELECT c.legal_name, st.period_end, st.chart_version
          FROM statements st
          JOIN companies c ON c.id = st.company_id
         WHERE EXISTS (SELECT 1 FROM statement_line_items li
                        WHERE li.statement_id = st.id AND li.canonical_key = 'revenue')
           AND EXISTS (SELECT 1 FROM statement_line_items li
                        WHERE li.statement_id = st.id AND li.canonical_key = 'gross_earnings')
         LIMIT 20
    """)
    ).all()
    assert not both, "statements carrying both revenue and gross_earnings:\n" + "\n".join(
        f"  {r.legal_name} {r.period_end} ({r.chart_version})" for r in both
    )


def test_the_bank_and_the_industrial_really_do_have_different_shapes(
    db_session: Session,
    one_of_each: tuple[int, int],
) -> None:
    """P4 check 18, as a test rather than as an afternoon.

    *"Extract one bank and one industrial, and compare the shapes. Confirm the bank did not
    silently map 'gross earnings' to `revenue`."* Both are typed through chart v1: JPMorgan
    under `financial`, Caterpillar under `non_financial`.

    Verified here on a seeded pair rather than on the real ones, so it runs in CI. The
    real pair - JPMorgan under `financial`, Caterpillar under `non_financial`, both typed
    through chart v1 - is what established the shapes this asserts.
    """
    rows = db_session.execute(
        text("""
        SELECT st.statement_template, li.canonical_key
          FROM statement_line_items li
          JOIN statements st ON st.id = li.statement_id
         WHERE st.chart_version = 'v1' AND st.statement_type = 'income'
         GROUP BY 1, 2
    """)
    ).all()
    financial = {r.canonical_key for r in rows if r.statement_template == "financial"}
    non_financial = {r.canonical_key for r in rows if r.statement_template == "non_financial"}
    assert financial and non_financial, (
        "the fixture seeds one of each, so an empty side means the seed did not land and "
        "every assertion below would pass over nothing"
    )
    assert "revenue" not in financial, "a bank acquired a revenue line"
    assert "gross_earnings" not in non_financial, "an industrial acquired gross earnings"
    assert "net_interest_income" in financial, (
        "the bank chart's defining key is missing, so the parallel chart is not in use"
    )
    # And the keys that genuinely mean the same thing for both are shared rather than
    # duplicated, which is the other half of getting the split right.
    assert {"profit_after_tax", "profit_before_tax", "income_tax"} <= (financial & non_financial)


# --------------------------------------------------------------------------------------
# Proving the checks can fail
#
# Every assertion above is a search for rows that should not exist, and every one of them
# currently finds none. That is the desired answer and it is also what a broken query
# returns, so each check is run once against a row built to trip it. `db_session` rolls
# back, so the bad rows exist only for the length of the test that needs them.
# --------------------------------------------------------------------------------------


def test_the_template_check_catches_a_bank_key_on_an_industrial_statement(
    db_session: Session,
) -> None:
    """The `gross_earnings` → `revenue` mistake, built deliberately and then caught.

    Without this, a query with a typo in it would report "no violations" forever and the
    protection would be imaginary.
    """
    statement_id = _typed_company(
        db_session,
        name="zz-test-chart Mislabelled Plc",
        template="non_financial",
        figures={"revenue": Decimal("2000000")},
        marker="c",
    )
    # A financial key hung on a non-financial statement: exactly what must never happen.
    security_id = db_session.execute(
        text("SELECT security_id FROM statement_line_items WHERE statement_id = :s LIMIT 1"),
        {"s": statement_id},
    ).scalar_one()
    document_id = db_session.execute(
        text("SELECT source_document_id FROM statements WHERE id = :s"),
        {"s": statement_id},
    ).scalar_one()
    db_session.add(
        StatementLineItem(
            statement_id=statement_id,
            security_id=security_id,
            canonical_key="net_interest_income",
            chart_version="v1",
            value=Decimal("600000"),
            currency="NGN",
            unit_multiplier=1,
            period_end=PERIOD_END,
            known_as_of=PERIOD_END + dt.timedelta(days=120),
            version=1,
            correction_type="none",
            source_document_id=document_id,
            page=1,
            extraction_method="manual",
        )
    )
    db_session.flush()

    offenders = db_session.execute(_OUT_OF_TEMPLATE, {"both": BOTH}).all()
    assert any(r.canonical_key == "net_interest_income" for r in offenders), (
        "a financial key was hung on a non-financial statement and the query did not "
        "notice, which means every green run of the test above proved nothing"
    )


def test_the_rival_top_line_check_catches_a_statement_carrying_both(
    db_session: Session,
) -> None:
    """Same reasoning, for the narrower check that names the specific case."""
    statement_id = _typed_company(
        db_session,
        name="zz-test-chart Confused Plc",
        template="non_financial",
        figures={"revenue": Decimal("2000000")},
        marker="d",
    )
    security_id = db_session.execute(
        text("SELECT security_id FROM statement_line_items WHERE statement_id = :s LIMIT 1"),
        {"s": statement_id},
    ).scalar_one()
    document_id = db_session.execute(
        text("SELECT source_document_id FROM statements WHERE id = :s"),
        {"s": statement_id},
    ).scalar_one()
    db_session.add(
        StatementLineItem(
            statement_id=statement_id,
            security_id=security_id,
            canonical_key="gross_earnings",
            chart_version="v1",
            value=Decimal("2000000"),
            currency="NGN",
            unit_multiplier=1,
            period_end=PERIOD_END,
            known_as_of=PERIOD_END + dt.timedelta(days=120),
            version=1,
            correction_type="none",
            source_document_id=document_id,
            page=1,
            extraction_method="manual",
        )
    )
    db_session.flush()

    both = db_session.execute(
        text("""
        SELECT c.legal_name
          FROM statements st
          JOIN companies c ON c.id = st.company_id
         WHERE EXISTS (SELECT 1 FROM statement_line_items li
                        WHERE li.statement_id = st.id AND li.canonical_key = 'revenue')
           AND EXISTS (SELECT 1 FROM statement_line_items li
                        WHERE li.statement_id = st.id AND li.canonical_key = 'gross_earnings')
    """)
    ).all()
    assert any("Confused" in r.legal_name for r in both)
