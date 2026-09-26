"""P6 checks 7 and 8 against the database — saving, reloading and recomputing a scenario.

Check 7 is *"same assumptions → identical output"* and check 8 is *"two principals'
scenarios do not collide"*. Both are `docs/05` US-060, and neither can be tested on the
arithmetic alone: check 7 is only interesting once the assumptions have been through
JSONB and the figures have been re-read from the point-in-time accessor, and check 8 is a
statement about rows.

The sharp version of check 7 is the last test in the file. Re-running a scenario is not
"the same function twice in a row" — it is *the same function a month later, against a
database that has moved on*. A restated FY2024 filed in August and a price bar from the
same week must not touch a scenario dated 30 June, because the whole promise of
`inputs_as_of` is that the answer belongs to that date. A stored result would have hidden
this either way, which is why `docs/08` §2.9 does not have one.

The company is the same ordinary Nigerian importer as `tests/known_answer/test_scenarios`,
seeded here as real rows: one FY2024 filing known on 2025-03-31, a price bar, a share
count, and an end-2024 dollar rate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.fx import NFEM_OFFICIAL
from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Filing,
    FxRate,
    PriceHistory,
    Principal,
    Security,
    SharesOutstanding,
    SourceDocument,
    Statement,
    StatementLineItem,
)
from packages.common.timez import utcnow
from packages.valuation.scenarios import (
    CODE_VERSION,
    FxShock,
    MissingFactsError,
    ScenarioAssumptions,
    ScenarioExistsError,
    delete_scenario,
    facts_for,
    list_scenarios,
    load_scenario,
    run_saved,
    save_scenario,
)

D = Decimal
BN = D(1_000_000_000)

PERIOD_END = dt.date(2024, 12, 31)
FILED = dt.date(2025, 3, 31)
#: The decision date every scenario below is saved against.
AS_OF = dt.date(2025, 6, 30)
#: After it. Nothing dated here may reach a scenario dated `AS_OF`.
LATER = dt.date(2025, 8, 1)

CHART = "v1"
TEMPLATE = "non_financial"

FIGURES: dict[str, Decimal] = {
    "revenue": 1000 * BN,
    "cost_of_revenue": 600 * BN,
    "gross_profit": 400 * BN,
    "operating_profit": 200 * BN,
    "profit_before_tax": 180 * BN,
    "income_tax": 54 * BN,
    "profit_after_tax": 126 * BN,
    "cash_from_ops": 160 * BN,
    "capex": 40 * BN,
    "depreciation_amortisation": 30 * BN,
    "interest_expense": 20 * BN,
    "dividends_paid": 20 * BN,
    "long_term_debt": 150 * BN,
    "cash": 50 * BN,
    "total_assets": 900 * BN,
    "total_liabilities": 500 * BN,
    "total_equity": 400 * BN,
    "current_assets": 350 * BN,
    "current_liabilities": 250 * BN,
}


@dataclass(frozen=True)
class Book:
    """The ids the tests need, and nothing else."""

    security_id: int
    owner_id: int
    family_id: int
    document_id: int
    company_id: int
    data_source_id: int


@pytest.fixture
def book(db_session: Session) -> Book:
    """One importer with one filing, one price, one share count, and two principals."""
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///importer-2024.pdf",
        storage_key="documents/sha256/" + "7" * 64,
        sha256="7" * 64,
        media_type="application/pdf",
        retrieved_at=utcnow(),
    )
    company = Company(
        legal_name="Scenario Test Importer Plc",
        country="NG",
        statement_template=TEMPLATE,
        fiscal_year_end=12,
    )
    owner = Principal(display_name="Owner", kind="owner")
    family = Principal(display_name="Family", kind="family")
    db_session.add_all([document, company, owner, family])
    db_session.flush()

    exchange_id = db_session.execute(select(Exchange.id).where(Exchange.code == "NGX")).scalar_one()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
    filing = Filing(
        company_id=company.id,
        filing_type="annual",
        filing_date=FILED,
        period_end=PERIOD_END,
        accession_no="ngx-2024-0002",
        source_document_id=document.id,
        known_as_of=FILED,
    )
    db_session.add_all([security, filing])
    db_session.flush()

    statement = _statement(company.id, filing.id, document.id, version=1, known_as_of=FILED)
    db_session.add(statement)
    db_session.flush()
    db_session.add_all(
        [
            _item(statement.id, security.id, document.id, key, value, known_as_of=FILED)
            for key, value in FIGURES.items()
        ]
    )
    db_session.add_all(
        [
            PriceHistory(
                security_id=security.id,
                date=dt.date(2025, 6, 27),
                known_as_of=dt.date(2025, 6, 27),
                close_raw=D(60),
                data_source_id=source_id,
                source_document_id=document.id,
            ),
            SharesOutstanding(
                security_id=security.id,
                as_of_date=PERIOD_END,
                share_class="ordinary",
                basic_or_diluted="basic",
                known_as_of=FILED,
                shares=4 * BN,
                source_document_id=document.id,
            ),
            FxRate(
                base_currency="USD",
                quote_currency="NGN",
                rate_type=NFEM_OFFICIAL,
                as_of_date=dt.date(2025, 6, 27),
                known_as_of=dt.date(2025, 6, 27),
                rate=D("1535.0"),
                data_source_id=source_id,
                source_document_id=document.id,
            ),
        ]
    )
    db_session.flush()
    return Book(
        security_id=security.id,
        owner_id=owner.id,
        family_id=family.id,
        document_id=document.id,
        company_id=company.id,
        data_source_id=source_id,
    )


def _statement(
    company_id: int, filing_id: int | None, document_id: int, *, version: int, known_as_of: dt.date
) -> Statement:
    return Statement(
        filing_id=filing_id,
        company_id=company_id,
        statement_type="income_statement",
        period_type="FY",
        period_end=PERIOD_END,
        fiscal_year=2024,
        calendar_year=2024,
        period_label="FY2024",
        presentation_currency="NGN",
        presentation_multiplier=1,
        known_as_of=known_as_of,
        chart_version=CHART,
        statement_template=TEMPLATE,
        is_consolidated=True,
        version=version,
        source_document_id=document_id,
    )


def _item(
    statement_id: int,
    security_id: int,
    document_id: int,
    key: str,
    value: Decimal,
    *,
    known_as_of: dt.date,
    version: int = 1,
    restatement: bool = False,
) -> StatementLineItem:
    return StatementLineItem(
        statement_id=statement_id,
        security_id=security_id,
        canonical_key=key,
        chart_version=CHART,
        as_printed_label=key,
        as_printed_value=str(value),
        value=value,
        currency="NGN",
        unit_multiplier=1,
        period_end=PERIOD_END,
        known_as_of=known_as_of,
        version=version,
        restatement_flag=restatement,
        source_document_id=document_id,
        page=1,
        extraction_method="manual",
    )


def bear(**overrides: object) -> ScenarioAssumptions:
    """The owner's own numbers: 24% discount rate, naira at ₦2,000, half the inputs imported."""
    fields: dict[str, object] = {
        "growth_rates": (D("0.15"), D("0.12"), D("0.10")),
        "discount_rate": D("0.24"),
        "terminal_growth": D("0.08"),
        "fx": FxShock(
            scenario_rate=D(2000),
            base_rate=D("1535.0"),
            cost_exposure=D("0.5"),
            revenue_exposure=D("0"),
            tax_rate=D("0.30"),
        ),
    }
    fields.update(overrides)
    return ScenarioAssumptions(**fields)  # type: ignore[arg-type]


def digits(result: object) -> list[str]:
    """Every number in the answer as the string it printed, not as a rounded float."""
    assert hasattr(result, "dcf")
    dcf = result.dcf  # type: ignore[attr-defined]
    ratios = result.ratios  # type: ignore[attr-defined]
    return [
        str(dcf.value_per_share),
        str(dcf.equity_value),
        str(dcf.enterprise_value),
        str(dcf.terminal_value),
        *[str(v) for v in dcf.present_values],
        *[f"{key}={ratios[key]}" for key in sorted(ratios)],
    ]


# --------------------------------------------------------------------------------------
# Check 8 — scenarios are per principal
# --------------------------------------------------------------------------------------


def test_check_8_two_principals_can_both_have_a_bear_on_the_same_security(
    db_session: Session, book: Book
) -> None:
    """ "Bear" means different things to different people, and the rows say so."""
    save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="bear",
        assumptions=bear(),
        inputs_as_of=AS_OF,
    )
    save_scenario(
        db_session,
        principal_id=book.family_id,
        security_id=book.security_id,
        name="bear",
        assumptions=bear(discount_rate=D("0.30")),
        inputs_as_of=AS_OF,
    )

    mine = load_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
    )
    theirs = load_scenario(
        db_session, principal_id=book.family_id, security_id=book.security_id, name="bear"
    )
    assert mine is not None and theirs is not None
    assert mine.id != theirs.id
    assert mine.assumptions.discount_rate == D("0.24")
    assert theirs.assumptions.discount_rate == D("0.30")

    # ...and the answers differ, which is the point of having two of them.
    assert run_saved(db_session, mine).dcf.value_per_share != (
        run_saved(db_session, theirs).dcf.value_per_share
    )


def test_check_8_a_principal_sees_and_deletes_only_their_own(
    db_session: Session, book: Book
) -> None:
    for principal_id, rate in ((book.owner_id, D("0.24")), (book.family_id, D("0.30"))):
        save_scenario(
            db_session,
            principal_id=principal_id,
            security_id=book.security_id,
            name="bear",
            assumptions=bear(discount_rate=rate),
            inputs_as_of=AS_OF,
        )
    save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="base",
        assumptions=bear(fx=None),
        inputs_as_of=AS_OF,
    )

    assert [s.name for s in list_scenarios(db_session, principal_id=book.owner_id)] == [
        "base",
        "bear",
    ]
    assert [s.name for s in list_scenarios(db_session, principal_id=book.family_id)] == ["bear"]

    assert delete_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
    )
    assert (
        load_scenario(
            db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
        )
        is None
    )
    # The other principal's scenario of the same name is untouched.
    survivor = load_scenario(
        db_session, principal_id=book.family_id, security_id=book.security_id, name="bear"
    )
    assert survivor is not None
    assert survivor.assumptions.discount_rate == D("0.30")
    # Deleting a name you do not have deletes nothing rather than somebody else's row.
    assert not delete_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
    )
    assert len(list_scenarios(db_session, principal_id=book.family_id)) == 1


def test_the_same_name_is_not_silently_overwritten(db_session: Session, book: Book) -> None:
    """`CLAUDE.md`: no silent overwrites. Replacing a saved scenario has to be asked for."""
    keys = {
        "principal_id": book.owner_id,
        "security_id": book.security_id,
        "name": "bear",
        "inputs_as_of": AS_OF,
    }
    save_scenario(db_session, assumptions=bear(), **keys)  # type: ignore[arg-type]
    with pytest.raises(ScenarioExistsError, match="bear"):
        save_scenario(db_session, assumptions=bear(discount_rate=D("0.19")), **keys)  # type: ignore[arg-type]

    save_scenario(
        db_session,
        assumptions=bear(discount_rate=D("0.19")),
        overwrite=True,
        **keys,  # type: ignore[arg-type]
    )
    replaced = load_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
    )
    assert replaced is not None
    assert replaced.assumptions.discount_rate == D("0.19")
    assert len(list_scenarios(db_session, principal_id=book.owner_id)) == 1


# --------------------------------------------------------------------------------------
# Check 7 — the same assumptions produce identical output
# --------------------------------------------------------------------------------------


def test_check_7_a_saved_scenario_reloads_as_the_numbers_that_were_typed(
    db_session: Session, book: Book
) -> None:
    """Through JSONB and back, to the digit. A float round trip would lose this."""
    original = bear(
        base_free_cash_flow=D("123456789.123456789"),
        overrides={"revenue": D("1000000000.5")},
        shares=D("4000000000"),
    )
    saved = save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="naira at 2000",
        assumptions=original,
        inputs_as_of=AS_OF,
    )
    db_session.expire_all()  # force a real read rather than the identity map's copy

    loaded = load_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="naira at 2000",
    )
    assert loaded is not None
    assert loaded.assumptions == original
    assert str(loaded.assumptions.discount_rate) == "0.24"
    assert str(loaded.assumptions.base_free_cash_flow) == "123456789.123456789"
    assert loaded.assumptions.fx is not None
    assert str(loaded.assumptions.fx.cost_exposure) == "0.5"
    assert loaded.inputs_as_of == AS_OF
    assert loaded.code_version == CODE_VERSION == saved.code_version


def test_check_7_reopening_a_scenario_reproduces_identical_output(
    db_session: Session, book: Book
) -> None:
    """US-060: saved as "bear", reopened, and the same numbers come back."""
    save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="bear",
        assumptions=bear(),
        inputs_as_of=AS_OF,
    )
    keys = {"principal_id": book.owner_id, "security_id": book.security_id, "name": "bear"}

    first = run_saved(db_session, load_scenario(db_session, **keys))  # type: ignore[arg-type]
    db_session.expire_all()
    second = run_saved(db_session, load_scenario(db_session, **keys))  # type: ignore[arg-type]

    assert digits(first) == digits(second)
    assert first == second
    # And it is not vacuous: the assumptions really did produce an answer.
    assert first.dcf.value_per_share is not None
    assert first.fx is not None
    assert first.code_version_changed is False


@pytest.mark.invariant
def test_check_7_data_published_after_the_decision_date_cannot_move_the_answer(
    db_session: Session, book: Book
) -> None:
    """`SPEC.md` §4.1, point-in-time only — the reason there is no stored result.

    A restated FY2024 revenue filed on 1 August and a price bar from the same week are
    invisible to a scenario dated 30 June, and visible to one dated 1 September. If
    re-running took "the latest figures", the first assertion would fail and every saved
    scenario would silently mean something different each time it was opened.
    """
    for name, when in (("bear", AS_OF), ("bear in september", dt.date(2025, 9, 1))):
        save_scenario(
            db_session,
            principal_id=book.owner_id,
            security_id=book.security_id,
            name=name,
            assumptions=bear(),
            inputs_as_of=when,
        )
    june = load_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="bear"
    )
    assert june is not None
    before = run_saved(db_session, june)

    restated = _statement(book.company_id, None, book.document_id, version=2, known_as_of=LATER)
    db_session.add(restated)
    db_session.flush()
    db_session.add_all(
        [
            _item(
                restated.id,
                book.security_id,
                book.document_id,
                "revenue",
                D(700) * BN,
                known_as_of=LATER,
                version=2,
                restatement=True,
            ),
            PriceHistory(
                security_id=book.security_id,
                date=LATER,
                known_as_of=LATER,
                close_raw=D(21),
                data_source_id=book.data_source_id,
                source_document_id=book.document_id,
            ),
        ]
    )
    db_session.flush()
    db_session.expire_all()

    after = run_saved(db_session, june)
    assert digits(after) == digits(before)
    assert after.facts.price == D(60)
    assert after.line_items_as_reported["revenue"] == 1000 * BN

    september = load_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="bear in september",
    )
    assert september is not None
    later = run_saved(db_session, september)
    assert later.line_items_as_reported["revenue"] == 700 * BN
    assert later.facts.price == D(21)
    assert digits(later) != digits(before), "the same assumptions on later data must differ"


def test_a_scenario_runs_at_its_own_date_and_not_at_todays(db_session: Session, book: Book) -> None:
    """A date before the filing was knowable has no statements to read, and says so."""
    save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="too early",
        assumptions=bear(),
        inputs_as_of=dt.date(2025, 1, 15),
    )
    early = load_scenario(
        db_session, principal_id=book.owner_id, security_id=book.security_id, name="too early"
    )
    assert early is not None
    with pytest.raises(MissingFactsError) as raised:
        run_saved(db_session, early)
    assert set(raised.value.missing) == {"cost_of_revenue"}


# --------------------------------------------------------------------------------------
# The read path
# --------------------------------------------------------------------------------------


def test_facts_are_the_point_in_time_read_paths_and_carry_their_dates(
    db_session: Session, book: Book
) -> None:
    facts = facts_for(db_session, security_id=book.security_id, inputs_as_of=AS_OF)
    assert facts.period_label == "FY2024"
    assert facts.period_known_as_of == FILED
    assert facts.currency == "NGN"
    assert facts.line_items["revenue"] == 1000 * BN
    assert facts.price == D(60)
    assert facts.price_date == dt.date(2025, 6, 27)
    assert facts.shares == 4 * BN
    assert facts.shares_basis == "basic"
    # The exchange rate is a fact too, read as known on the same date.
    assert facts.fx_pair == "USD/NGN"
    assert facts.fx_rate == D("1535.0")
    assert facts.fx_rate_as_of == dt.date(2025, 6, 27)


def test_a_shock_without_a_typed_base_rate_uses_the_one_on_file(
    db_session: Session, book: Book
) -> None:
    """The rate the figures were earned at is a fact; the rate being assumed never is."""
    saved = save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="naira at 2000",
        assumptions=bear(
            fx=FxShock(
                scenario_rate=D(2000),
                cost_exposure=D("0.5"),
                revenue_exposure=D("0"),
                tax_rate=D("0.30"),
            )
        ),
        inputs_as_of=AS_OF,
    )
    result = run_saved(db_session, saved)
    assert result.fx is not None
    assert result.fx.base_rate == D("1535.0")
    sources = {item.name: item.source for item in result.inputs}
    assert sources["fx.base_rate"] == "USD/NGN as of 2025-06-27, known on 2025-06-30"
    assert sources["fx.scenario_rate"] == "user"
    # The saved row still carries only what the user typed - no rate was written into it.
    assert "base_rate" not in saved.assumptions.to_json()["fx"]


def test_the_result_names_the_scenario_and_the_version_that_produced_it(
    db_session: Session, book: Book
) -> None:
    saved = save_scenario(
        db_session,
        principal_id=book.owner_id,
        security_id=book.security_id,
        name="bear",
        assumptions=bear(),
        inputs_as_of=AS_OF,
    )
    result = run_saved(db_session, saved)
    assert result.scenario is not None
    assert result.scenario.name == "bear"
    assert result.scenario.principal_id == book.owner_id
    assert result.code_version == CODE_VERSION
    assert result.code_version_at_save == CODE_VERSION
    assert result.assumptions == saved.assumptions
