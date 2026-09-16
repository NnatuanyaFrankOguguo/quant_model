"""`packages.common.identity`: which security a ticker meant on a date. TG2, `OPERATIONS` §1.4.

The bug under test is a silent one. Guaranty Trust Bank became GTCO on 2021-08-01; if the
ticker is the join key, a rename or a reuse joins one company's new prices onto another
company's old history and **nothing raises**. So these tests do two things: they check that
resolution answers the dated question correctly, and they check that the database physically
refuses the rows that would make the question ambiguous.

The constraint tests matter more than the resolution tests. `docs/10` §2.11 calls
`no_overlapping_ids` "the only mechanism that makes `resolve_security` provably
single-valued", and a resolver is only as good as the rows it reads.

**On the shape of the constraint tests.** Each writes through a savepoint held *inside*
`pytest.raises`, never outside it: the failing flush aborts the savepoint, and letting
`begin_nested()` see the exception is what rolls it back and leaves the outer transaction
usable for the assertions that follow.
"""

from __future__ import annotations

import ast
import datetime as dt
import pathlib

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.identity import (
    CIK,
    TICKER,
    AmbiguousIdentifierError,
    company_for_identifier,
    current_identifiers,
    has_primary_ticker,
    identifier_exists,
    primary_tickers,
    resolve_security,
)
from packages.common.models import Company, Exchange, Security, SecurityIdentifier

pytestmark = pytest.mark.invariant

#: The real rename `docs/08` §2.1 uses as its worked example.
RENAMED_ON = dt.date(2021, 8, 1)
LAST_DAY_AS_GUARANTY = dt.date(2021, 7, 31)
TODAY = dt.date(2026, 9, 16)


def _exchange_id(session: Session, code: str) -> int:
    return session.execute(select(Exchange.id).where(Exchange.code == code)).scalar_one()


def _company(session: Session, name: str, country: str = "NG") -> Company:
    company = Company(
        legal_name=name, country=country, statement_template="bank", fiscal_year_end=12
    )
    session.add(company)
    session.flush()
    return company


def _security(session: Session, company: Company, exchange: str, currency: str = "NGN") -> Security:
    security = Security(
        company_id=company.id,
        exchange_id=_exchange_id(session, exchange),
        currency=currency,
    )
    session.add(security)
    session.flush()
    return security


def _identifier(
    session: Session,
    security: Security,
    value: str,
    *,
    valid_from: dt.date,
    id_type: str = TICKER,
    valid_to: dt.date | None = None,
    is_primary: bool = True,
    exchange_id: int | None = -1,  # -1 = take the security's own exchange
) -> SecurityIdentifier:
    row = SecurityIdentifier(
        security_id=security.id,
        id_type=id_type,
        id_value=value,
        valid_from=valid_from,
        valid_to=valid_to,
        exchange_id=security.exchange_id if exchange_id == -1 else exchange_id,
        is_primary=is_primary,
        source="test",
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def gtco(db_session: Session) -> Security:
    """One security, two ticker eras: GUARANTY through 2021-07-31, then GTCO.

    Both rows point at the same `security_id`, which is the whole point - the price history
    never splits, and a reader asking under either name reaches the same series.
    """
    company = _company(db_session, "Guaranty Trust Holding Company Plc")
    security = _security(db_session, company, "NGX")
    _identifier(
        db_session,
        security,
        "GUARANTY",
        valid_from=dt.date(1996, 1, 1),
        valid_to=LAST_DAY_AS_GUARANTY,
    )
    _identifier(db_session, security, "GTCO", valid_from=RENAMED_ON)
    return security


# --------------------------------------------------------------------------------------
# Resolution: the dated question
# --------------------------------------------------------------------------------------


def test_a_renamed_company_resolves_under_both_names_to_one_security(
    db_session: Session, gtco: Security
) -> None:
    """The reason `security_id` is the key and the ticker is an attribute."""
    before = resolve_security(db_session, value="GUARANTY", as_of=dt.date(2020, 6, 30))
    after = resolve_security(db_session, value="GTCO", as_of=TODAY)
    assert before is not None and after is not None
    assert before.security_id == after.security_id == gtco.id
    assert before.id_value == "GUARANTY" and after.id_value == "GTCO"


def test_the_last_day_of_validity_still_resolves(db_session: Session, gtco: Security) -> None:
    """`valid_to` is inclusive, and the boundary day is where an off-by-one would hide.

    `docs/08` §2.1's sample runs GUARANTY to 2021-07-31 and starts GTCO on 2021-08-01. Those
    two rows leave no gap only if 2021-07-31 belongs to GUARANTY, so it must resolve - and
    the day after must not.
    """
    on_the_day = resolve_security(db_session, value="GUARANTY", as_of=LAST_DAY_AS_GUARANTY)
    assert on_the_day is not None, "the last day of validity is inside the interval"
    assert resolve_security(db_session, value="GUARANTY", as_of=RENAMED_ON) is None
    assert resolve_security(db_session, value="GTCO", as_of=RENAMED_ON) is not None
    assert resolve_security(db_session, value="GTCO", as_of=LAST_DAY_AS_GUARANTY) is None


def test_a_ticker_resolves_to_nothing_before_it_was_issued(
    db_session: Session, gtco: Security
) -> None:
    assert resolve_security(db_session, value="GUARANTY", as_of=dt.date(1990, 1, 1)) is None


def test_a_reused_ticker_resolves_to_whoever_held_it_then(db_session: Session) -> None:
    """The merge this module exists to prevent, stated as a test.

    Two unrelated companies hold `ZENITH` in sequence. Asking without a date, or keying on
    the string, would join one's prices onto the other's history. Asking with a date cannot.
    """
    first = _security(db_session, _company(db_session, "First Holder Plc"), "NGX")
    second = _security(db_session, _company(db_session, "Second Holder Plc"), "NGX")
    _identifier(
        db_session,
        first,
        "ZENITH",
        valid_from=dt.date(2005, 1, 1),
        valid_to=dt.date(2015, 12, 31),
    )
    _identifier(db_session, second, "ZENITH", valid_from=dt.date(2016, 1, 1))

    then = resolve_security(db_session, value="ZENITH", as_of=dt.date(2010, 1, 1))
    now = resolve_security(db_session, value="ZENITH", as_of=TODAY)
    assert then is not None and now is not None
    assert then.security_id == first.id
    assert now.security_id == second.id
    assert then.security_id != now.security_id


def test_a_ticker_on_two_exchanges_is_ambiguous_unless_the_market_is_named(
    db_session: Session,
) -> None:
    """Across exchanges the constraint cannot make resolution single-valued, so it raises.

    One string listed on two markets is a real listing, not a defect. Picking one silently
    is the merge; naming the exchange is the answer. Nothing collides across the three
    registered exchanges today, and P3's Nigerian load is when that can change.
    """
    lagos = _security(db_session, _company(db_session, "Total Nigeria Plc"), "NGX")
    york = _security(db_session, _company(db_session, "Total Unrelated Inc", "US"), "NYSE", "USD")
    _identifier(db_session, lagos, "TOTAL", valid_from=dt.date(2019, 1, 1))
    _identifier(db_session, york, "TOTAL", valid_from=dt.date(2019, 1, 1))

    with pytest.raises(AmbiguousIdentifierError):
        resolve_security(db_session, value="TOTAL", as_of=TODAY)

    scoped = resolve_security(db_session, value="TOTAL", as_of=TODAY, exchange="NGX")
    assert scoped is not None and scoped.security_id == lagos.id


def test_resolution_will_not_run_without_a_date(db_session: Session, gtco: Security) -> None:
    """The same rule as `fx.convert`: a lookup without a date answers only for today."""
    with pytest.raises(TypeError):
        resolve_security(db_session, value="GTCO", as_of="2026-09-16")  # type: ignore[arg-type]


def test_an_unknown_identifier_type_is_refused(db_session: Session) -> None:
    with pytest.raises(ValueError, match="not an identifier type"):
        resolve_security(db_session, value="X", as_of=TODAY, id_type="ticker_v2")


def test_a_lookup_is_case_and_space_insensitive(db_session: Session, gtco: Security) -> None:
    resolved = resolve_security(db_session, value="  gtco ", as_of=TODAY)
    assert resolved is not None and resolved.id_value == "GTCO"


def test_existence_is_a_different_question_from_resolution(db_session: Session) -> None:
    """A predecessor CIK that expired years ago still exists; it resolves only in its window."""
    security = _security(db_session, _company(db_session, "Successor Plc"), "NGX")
    _identifier(
        db_session,
        security,
        "0000034088",
        id_type=CIK,
        valid_from=dt.date(2019, 12, 18),
        valid_to=dt.date(2026, 7, 1),
        exchange_id=None,
    )
    assert identifier_exists(db_session, value="0000034088", id_type=CIK) is True
    assert resolve_security(db_session, value="0000034088", as_of=TODAY, id_type=CIK) is None, (
        "the CIK stopped identifying the registrant when the successor took over"
    )
    inside = resolve_security(
        db_session, value="0000034088", as_of=dt.date(2020, 1, 1), id_type=CIK
    )
    assert inside is not None and inside.exchange_id is None


# --------------------------------------------------------------------------------------
# The constraints: what makes the answer provable rather than probable
# --------------------------------------------------------------------------------------


def test_overlapping_validity_windows_are_refused(db_session: Session, gtco: Security) -> None:
    """`no_overlapping_ids`, and the exact case `docs/10` §2.11 says the old key allowed.

    The dropped `UNIQUE (id_type, id_value, valid_from)` permitted this: a second security
    holding GTCO over an overlapping window, differing only in `valid_from`. It is the NGX
    ticker-reuse merge, and the exclusion constraint is what stops it at the row.
    """
    other = _security(db_session, _company(db_session, "Impostor Plc"), "NGX")
    with pytest.raises(IntegrityError, match="no_overlapping_ids"), db_session.begin_nested():
        _identifier(db_session, other, "GTCO", valid_from=RENAMED_ON + dt.timedelta(days=1))


def test_a_single_day_identity_cannot_be_duplicated(db_session: Session) -> None:
    """Why the constraint uses `valid_to + 1` rather than `docs/10` §2.11's literal SQL.

    `_record_predecessor` writes `valid_from == valid_to` when a payload shows no filing -
    "the succession day alone". Under a half-open bound on the raw `valid_to` that interval
    is the **empty range**, and an empty range overlaps nothing, so a duplicate would pass
    the constraint silently. Both live `cik` rows were written by that function.
    """
    one = _security(db_session, _company(db_session, "One Day Plc"), "NGX")
    two = _security(db_session, _company(db_session, "One Day Rival Plc"), "NGX")
    day = dt.date(2024, 3, 15)
    _identifier(db_session, one, "ONEDAY", valid_from=day, valid_to=day)
    with pytest.raises(IntegrityError, match="no_overlapping_ids"), db_session.begin_nested():
        _identifier(db_session, two, "ONEDAY", valid_from=day, valid_to=day)


def test_a_duplicate_global_identifier_is_refused(db_session: Session) -> None:
    """Why the constraint uses `COALESCE(exchange_id, 0)`.

    An ISIN has no exchange, so `exchange_id` is NULL - and `NULL = NULL` is NULL inside an
    exclusion constraint, not true. Under `docs/10` §2.11's literal SQL every global
    identifier would escape the check, including the one type that is globally unique by
    definition.
    """
    one = _security(db_session, _company(db_session, "Isin Holder Plc"), "NGX")
    two = _security(db_session, _company(db_session, "Isin Rival Plc"), "NGX")
    _identifier(
        db_session,
        one,
        "NGGUARANTY1",
        id_type="isin",
        valid_from=dt.date(2020, 1, 1),
        exchange_id=None,
        is_primary=False,
    )
    with pytest.raises(IntegrityError, match="no_overlapping_ids"), db_session.begin_nested():
        _identifier(
            db_session,
            two,
            "NGGUARANTY1",
            id_type="isin",
            valid_from=dt.date(2020, 1, 1),
            exchange_id=None,
            is_primary=False,
        )


def test_one_ticker_may_list_on_two_exchanges_from_the_same_day(db_session: Session) -> None:
    """Why the old unique key had to be dropped rather than kept beside the new constraint.

    `UNIQUE (id_type, id_value, valid_from)` was not exchange-scoped, so it rejected exactly
    this: one string, two markets, same start date. That is a dual listing, and refusing it
    would have made the exchange scoping unusable.
    """
    lagos = _security(db_session, _company(db_session, "Dual Listed Plc"), "NGX")
    york = _security(db_session, _company(db_session, "Dual Listed US Inc", "US"), "NYSE", "USD")
    day = dt.date(2022, 5, 4)
    _identifier(db_session, lagos, "DUAL", valid_from=day)
    _identifier(db_session, york, "DUAL", valid_from=day)
    assert resolve_security(db_session, value="DUAL", as_of=day, exchange="NGX") is not None
    assert resolve_security(db_session, value="DUAL", as_of=day, exchange="NYSE") is not None


def test_a_ticker_without_an_exchange_is_refused(db_session: Session) -> None:
    """`identifier_has_exchange`. A ticker with no market resolves against all of them."""
    security = _security(db_session, _company(db_session, "No Exchange Plc"), "NGX")
    with pytest.raises(IntegrityError, match="identifier_has_exchange"), db_session.begin_nested():
        _identifier(db_session, security, "NOEX", valid_from=dt.date(2020, 1, 1), exchange_id=None)


def test_an_identifier_type_outside_the_list_is_refused(db_session: Session) -> None:
    """`identifier_type_is_known`, restoring the list `docs/08` had narrowed."""
    security = _security(db_session, _company(db_session, "Bad Type Plc"), "NGX")
    with pytest.raises(IntegrityError, match="identifier_type_is_known"), db_session.begin_nested():
        _identifier(
            db_session,
            security,
            "X",
            id_type="bloomberg",
            valid_from=dt.date(2020, 1, 1),
            exchange_id=None,
        )


def test_an_interval_cannot_end_before_it_begins(db_session: Session) -> None:
    security = _security(db_session, _company(db_session, "Backwards Plc"), "NGX")
    matches = "identifier_interval_is_ordered"
    with pytest.raises(IntegrityError, match=matches), db_session.begin_nested():
        _identifier(
            db_session,
            security,
            "BACK",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(2019, 1, 1),
        )


def test_a_security_has_at_most_one_current_primary_ticker(db_session: Session) -> None:
    """`one_primary_ticker_per_security`: the guarantee that replaced a `min(id)` heuristic.

    EDGAR lists a registrant's notes and preferred series beside its common stock - Bank of
    America carries sixteen current tickers - and `list_companies` must show one. It used to
    pick the lowest id and hope; now the column says which and the index holds it to one.
    """
    security = _security(db_session, _company(db_session, "Two Primaries Plc"), "NGX")
    _identifier(db_session, security, "COMMON", valid_from=dt.date(2020, 1, 1), is_primary=True)
    assert has_primary_ticker(db_session, security_id=security.id) is True
    matches = "one_primary_ticker_per_security"
    with pytest.raises(IntegrityError, match=matches), db_session.begin_nested():
        _identifier(db_session, security, "PREF", valid_from=dt.date(2020, 1, 1))

    # A non-primary second ticker is fine, and is not what `primary_tickers` returns.
    _identifier(db_session, security, "PREF", valid_from=dt.date(2020, 1, 1), is_primary=False)
    primary = primary_tickers()
    tickers = (
        db_session.execute(select(primary.c.ticker).where(primary.c.security_id == security.id))
        .scalars()
        .all()
    )
    assert tickers == ["COMMON"]


def test_a_past_primary_and_a_current_primary_coexist(db_session: Session, gtco: Security) -> None:
    """The index covers current rows only, because a renamed ticker was primary in its day."""
    rows = db_session.execute(
        select(SecurityIdentifier.id_value, SecurityIdentifier.is_primary)
        .where(SecurityIdentifier.security_id == gtco.id)
        .order_by(SecurityIdentifier.valid_from)
    ).all()
    assert [(value, primary) for value, primary in rows] == [("GUARANTY", True), ("GTCO", True)]
    assert has_primary_ticker(db_session, security_id=gtco.id) is True


# --------------------------------------------------------------------------------------
# The rule itself: one module reads this table
# --------------------------------------------------------------------------------------

#: Everything that ships. Tests are excluded: they seed and introspect rows on purpose.
_SOURCE_ROOTS = ("packages", "services", "apps", "scripts")

#: The one module allowed to query it, and the one that declares it.
_PERMITTED = {
    pathlib.Path("packages/common/identity.py"),
    pathlib.Path("packages/common/models.py"),
}


def test_only_the_identity_module_queries_the_identity_table() -> None:
    """`OPERATIONS.md` §1.4: "no `WHERE ticker = ?` anywhere else in the codebase".

    A black-box test proves today's callers go through the resolver. This one makes the
    *next* edit fail loudly: the day somebody writes `SecurityIdentifier.id_value ==` in a
    router or a connector, CI names the file.

    Attribute access is the tell. `SecurityIdentifier.id_type` builds a query; calling
    `SecurityIdentifier(...)` writes a row, which a connector is still allowed to do.
    """
    repo = pathlib.Path(__file__).resolve().parents[2]
    offenders: dict[str, list[str]] = {}
    for root in _SOURCE_ROOTS:
        for path in sorted((repo / root).rglob("*.py")):
            relative = path.relative_to(repo)
            if pathlib.Path(*relative.parts) in _PERMITTED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            used = sorted(
                {
                    node.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "SecurityIdentifier"
                }
            )
            if used:
                offenders[relative.as_posix()] = used
    assert not offenders, (
        "these modules query security_identifiers directly; route them through "
        f"packages.common.identity instead: {offenders}"
    )


# --------------------------------------------------------------------------------------
# The CIK, since migration 0019 moved it out of `companies`
# --------------------------------------------------------------------------------------


def test_a_cik_reaches_its_company_through_the_security_that_carries_it(
    db_session: Session,
) -> None:
    """`companies.cik` is gone (0019); the hop is CIK to security to company.

    A CIK names a registrant rather than a listing, so it hangs off the registrant's
    primary security - the compromise 0011 made for predecessor CIKs, which 0019 follows.
    """
    company = _company(db_session, "Registrant Plc", "US")
    security = _security(db_session, company, "NYSE", "USD")
    _identifier(db_session, security, "TICK", valid_from=dt.date(2015, 1, 1))
    _identifier(
        db_session,
        security,
        "0000123456",
        id_type=CIK,
        valid_from=dt.date(2015, 1, 1),
        exchange_id=None,
        is_primary=False,
    )
    assert company_for_identifier(db_session, value="0000123456", as_of=TODAY) == company.id


def test_a_cik_that_identifies_nothing_reaches_no_company(db_session: Session) -> None:
    """The registration path depends on this: None is "not registered", not an error."""
    assert company_for_identifier(db_session, value="0009999999", as_of=TODAY) is None


def test_a_predecessor_cik_reaches_no_company_today_but_did_in_its_window(
    db_session: Session,
) -> None:
    """Why the connector keeps a successor map: an expired CIK resolves to nothing now.

    `_company_for_cik` tries the CIK as of today, and on None falls back to the successor
    it recorded. This is the first half of that, stated as a test.
    """
    company = _company(db_session, "Continuing Plc", "US")
    security = _security(db_session, company, "NYSE", "USD")
    _identifier(db_session, security, "CONT", valid_from=dt.date(2019, 1, 1))
    _identifier(
        db_session,
        security,
        "0001001039",
        id_type=CIK,
        valid_from=dt.date(2012, 2, 13),
        valid_to=dt.date(2019, 3, 20),
        exchange_id=None,
        is_primary=False,
    )
    assert company_for_identifier(db_session, value="0001001039", as_of=TODAY) is None
    inside = company_for_identifier(db_session, value="0001001039", as_of=dt.date(2015, 1, 1))
    assert inside == company.id


def test_a_security_has_at_most_one_current_cik(db_session: Session) -> None:
    """`one_current_cik_per_security` (0019), and why the exclusion constraint is not enough.

    `no_overlapping_ids` keys on the identifier *value*, so two *different* current CIKs on
    one security do not collide with each other. Then "this company's CIK", which four API
    responses print and every filing URL is built from, would have two answers.
    """
    company = _company(db_session, "Two Ciks Plc", "US")
    security = _security(db_session, company, "NYSE", "USD")
    _identifier(db_session, security, "TWOC", valid_from=dt.date(2020, 1, 1))
    _identifier(
        db_session,
        security,
        "0000111111",
        id_type=CIK,
        valid_from=dt.date(2020, 1, 1),
        exchange_id=None,
        is_primary=False,
    )
    matches = "one_current_cik_per_security"
    with pytest.raises(IntegrityError, match=matches), db_session.begin_nested():
        _identifier(
            db_session,
            security,
            "0000222222",
            id_type=CIK,
            valid_from=dt.date(2020, 1, 1),
            exchange_id=None,
            is_primary=False,
        )


def test_one_cik_cannot_identify_two_registrants_at_once(db_session: Session) -> None:
    """The constraint `companies.cik` never had.

    The dropped column carried no unique key and no index, so nothing but the connector's
    own `WHERE cik = ?` stopped two companies holding one CIK. `no_overlapping_ids` refuses
    it at the row, whichever security each points at.
    """
    first = _security(db_session, _company(db_session, "Claimant One Plc", "US"), "NYSE", "USD")
    second = _security(db_session, _company(db_session, "Claimant Two Plc", "US"), "NYSE", "USD")
    for security, ticker in ((first, "CLM1"), (second, "CLM2")):
        _identifier(db_session, security, ticker, valid_from=dt.date(2020, 1, 1))
    _identifier(
        db_session,
        first,
        "0000333333",
        id_type=CIK,
        valid_from=dt.date(2020, 1, 1),
        exchange_id=None,
        is_primary=False,
    )
    with pytest.raises(IntegrityError, match="no_overlapping_ids"), db_session.begin_nested():
        _identifier(
            db_session,
            second,
            "0000333333",
            id_type=CIK,
            valid_from=dt.date(2020, 1, 1),
            exchange_id=None,
            is_primary=False,
        )


def test_the_current_identifiers_subquery_answers_one_row_per_security(
    db_session: Session,
) -> None:
    """What `snapshot` joins to for the CIK column the API prints."""
    company = _company(db_session, "Subquery Plc", "US")
    security = _security(db_session, company, "NYSE", "USD")
    _identifier(db_session, security, "SUBQ", valid_from=dt.date(2020, 1, 1))
    _identifier(
        db_session,
        security,
        "0000444444",
        id_type=CIK,
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(2021, 1, 1),
        exchange_id=None,
        is_primary=False,
    )
    ciks = current_identifiers(CIK)
    expired = (
        db_session.execute(select(ciks.c.id_value).where(ciks.c.security_id == security.id))
        .scalars()
        .all()
    )
    assert expired == [], "an expired CIK is not the current one"

    _identifier(
        db_session,
        security,
        "0000555555",
        id_type=CIK,
        valid_from=dt.date(2021, 1, 2),
        exchange_id=None,
        is_primary=False,
    )
    ciks = current_identifiers(CIK)
    current = (
        db_session.execute(select(ciks.c.id_value).where(ciks.c.security_id == security.id))
        .scalars()
        .all()
    )
    assert current == ["0000555555"]


def test_the_subquery_refuses_an_identifier_type_outside_the_contract() -> None:
    with pytest.raises(ValueError, match="not an identifier type"):
        current_identifiers("bloomberg")
