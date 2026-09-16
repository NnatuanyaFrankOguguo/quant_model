"""SEC EDGAR connectors: who a company is (submissions) and what it reported (companyfacts).

🟢 `docs/03` P2.1 rates this SOLID, with one hard operational rule set from
`DATA_FOUNDATION.md` §C, each of which is code here rather than memory:

* **Zero-pad the CIK to ten digits.** `320193` → `CIK0000320193`. `zero_pad_cik()`.
* **A descriptive `User-Agent` with a name and an email.** Requests without one are refused.
  It comes from `SEC_USER_AGENT`; with it unset the connector refuses to run at all rather
  than send an anonymous request and earn a block.
* **At most 10 requests a second.** Exceeding it returns 403/429 and blocks the IP for about
  ten minutes. `_Throttle` spaces requests 0.12 s apart across every connector instance in
  the process, and a 403 or 429 is raised as `EdgarRefusedError` and **never retried** —
  retrying is how a ten-minute block becomes a longer one.

## Two connectors, two record types

`EdgarSubmissionsConnector` reads `/submissions/CIK##########.json` — name, tickers,
exchanges, fiscal-year-end month, SIC code — and registers the company, its securities,
its tickers and its industry. It runs first, once per company.

`EdgarCompanyFactsConnector` reads `/api/xbrl/companyfacts/CIK##########.json` — every
XBRL fact the company has ever filed, by tag and unit — and writes statements and line items
through the chart of accounts (`packages.normalize`). Its `parse()` is pure: it turns the
JSON into `XbrlFact`s and nothing else. Everything that needs the database — which tags map
to which key, which company this is, what was already stored — happens in `write()`.

## The two dates, again

`filed` is `known_as_of`; `end` is the period. They differ by weeks and the difference is
the whole point (`docs/03` P2 "Expected inputs"). The fact's `fy`/`fp` describe the *filing*
and are not used to date the period — see `packages.normalize.periods`.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.config import get_settings
from packages.common.console import step
from packages.common.identity import (
    CIK,
    TICKER,
    company_for_identifier,
    has_primary_ticker,
    identifier_exists,
    resolve_security,
)
from packages.common.models import (
    Company,
    Exchange,
    ExtractionJob,
    Filing,
    Industry,
    Security,
    SecurityIdentifier,
    SharesOutstanding,
)
from packages.common.storage import StorageBackend
from packages.common.timez import utcnow
from packages.ingestion.base import (
    Connector,
    ConnectorRunResult,
    DataSourceLicence,
    RawResponse,
    record_run,
    store_raw,
)
from packages.normalize.chart import SOURCE_SYSTEM_BY_METHOD, load_chart, resolve
from packages.normalize.periods import fiscal_year_of, period_label, period_type_of
from packages.normalize.statements import ReportedStatement, StatementWriter

__all__ = [
    "CHART_VERSION",
    "CompanyRecord",
    "EdgarCompanyFactsConnector",
    "EdgarRefusedError",
    "EdgarSubmissionsConnector",
    "MissingUserAgentError",
    "XbrlFact",
    "load_ticker_map",
    "resolve_cik",
    "zero_pad_cik",
]

_log = structlog.get_logger(__name__)

_BASE = "https://data.sec.gov"
SOURCE_NAME = "SEC EDGAR"
SOURCE_SYSTEM = SOURCE_SYSTEM_BY_METHOD["xbrl"]


@dataclass(frozen=True)
class Predecessor:
    """The registrant whose filings carry a company's history before a new CIK took over."""

    cik: str  # zero-padded
    succeeded_on: dt.date  # the successor's 8-K12B filing date
    evidence: str  # that 8-K12B's accession number


#: Successor registrants. A holding-company reorganisation continues the listed security
#: under a new CIK: EDGAR's ticker list moves to the new number and every earlier filing
#: stays under the old one, so a ticker resolves to a company with one year of history
#: and the rest sits unreachable. This map says which old registrant a new one continued,
#: with the successor's own 8-K12B as the evidence - read from EDGAR, never inferred.
#: The predecessor's CIK is recorded as a time-bounded identifier of the security
#: (`security_identifiers`, id_type 'cik', valid_to the succession date), and its filings
#: are written under the continuing company.
PREDECESSORS: dict[str, Predecessor] = {
    # ExxonMobil Holdings Corp continued Exxon Mobil Corp on 2026-07-01.
    "0002115436": Predecessor("0000034088", dt.date(2026, 7, 1), "0001193125-26-291990"),
    # The Walt Disney Company (TWDC Holdco 613 Corp) continued the old Disney on 2019-03-20.
    "0001744489": Predecessor("0001001039", dt.date(2019, 3, 20), "0000950157-19-000301"),
}
_SUCCESSOR_BY_PREDECESSOR: dict[str, str] = {p.cik: s for s, p in PREDECESSORS.items()}


def successor_of(cik: str) -> str | None:
    """The CIK that continued this one, if this one is a known predecessor registrant."""
    return _SUCCESSOR_BY_PREDECESSOR.get(zero_pad_cik(cik))


def _company_for_cik(session: Session, cik: str) -> Company | None:
    """The company a CIK's filings belong to: its own row, or its successor's.

    Since migration 0019 the CIK is a dated identifier rather than a column on `companies`,
    so this resolves through `packages.common.identity` like every other identifier. The
    date is today because the question is "who files under this number now"; a CIK whose
    interval has closed is a predecessor, and the map below is what carries it forward.
    """
    company_id = company_for_identifier(session, value=cik, as_of=utcnow().date())
    if company_id is None:
        successor = successor_of(cik)
        if successor is None:
            return None
        company_id = company_for_identifier(session, value=successor, as_of=utcnow().date())
        if company_id is None:
            return None
    return session.get(Company, company_id)


def _record_cik(session: Session, company: Company, cik: str, *, observed_on: dt.date) -> int:
    """The company's own CIK, as a current identifier of its primary security.

    Written here because since 0019 nothing else records it, and a company whose CIK
    resolves to nothing is invisible to the next run - which would then create a duplicate.
    `_primary_security` raises when the company has no security at all, and that raise is
    deliberate: failing the run is visible in `connector_runs`, and a second company row
    for one registrant is silent corruption.

    `valid_from` is the day the CIK was first observed, a lower bound on its validity and
    never a claim about when it was issued - the same honesty `valid_from` carries for a
    ticker, and the reason migration 0019 derived the backfill from filing dates instead.
    """
    if identifier_exists(session, value=cik, id_type=CIK):
        return 0
    security = _primary_security(session, company)
    session.add(
        SecurityIdentifier(
            security_id=security.id,
            id_type=CIK,
            id_value=cik,
            valid_from=observed_on,
            valid_to=None,
            # A CIK names a registrant, not a listing, so it carries no exchange; and
            # `is_primary` is a ticker concept - `one_current_cik_per_security` is what
            # holds a security to one current CIK.
            exchange_id=None,
            is_primary=False,
            source="edgar_submissions",
        )
    )
    session.flush()
    return 1


CHART_VERSION = "v0.1"

#: 0.12 s between requests is ~8 per second, under EDGAR's ceiling of 10 with room for
#: the jitter of a laptop's clock. The ceiling is per IP, so the spacing is process-wide.
MIN_INTERVAL_SEC = 0.12

#: EDGAR's exchange names → our `exchanges.code`.
_EXCHANGE_CODES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}


class MissingUserAgentError(Exception):
    """`SEC_USER_AGENT` is not set. The connector refuses to run rather than be blocked."""


class EdgarRefusedError(Exception):
    """EDGAR answered 403 or 429. Stop; do not retry; wait out the block."""


def zero_pad_cik(cik: int | str) -> str:
    """`320193` → `'0000320193'`. Ten digits, always."""
    digits = str(cik).strip()
    if digits.upper().startswith("CIK"):
        digits = digits[3:]
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError(f"not a CIK: {cik!r}")
    return digits.zfill(10)


class _Throttle:
    """Process-wide spacing between EDGAR requests. Injectable clock and sleep for tests."""

    def __init__(
        self,
        interval_sec: float = MIN_INTERVAL_SEC,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval_sec
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> float:
        """Block until a request may be sent. Returns the seconds slept."""
        with self._lock:
            now = self._clock()
            slept = 0.0
            if self._last is not None:
                due = self._last + self._interval
                if now < due:
                    slept = due - now
                    self._sleep(slept)
                    now = self._clock()
            self._last = now
            return slept


_SHARED_THROTTLE = _Throttle()


class EdgarConnector(Connector[object]):
    """Shared licence, User-Agent and manners for every EDGAR endpoint."""

    rate_limit_per_sec = 8.0
    politeness_delay_sec = MIN_INTERVAL_SEC

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout_sec: float = 60.0,
        throttle: _Throttle | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_sec
        self._throttle = throttle or _SHARED_THROTTLE

    @property
    def user_agent(self) -> str:
        agent = self._user_agent or get_settings().sec_user_agent
        if not agent or "@" not in agent:
            raise MissingUserAgentError(
                "SEC_USER_AGENT is not set, or carries no email. EDGAR requires a descriptive "
                "User-Agent with a real name and email and refuses requests without one. Put "
                'SEC_USER_AGENT="Your Name you@example.com" in .env.'
            )
        return agent

    def declare_licence(self) -> DataSourceLicence:
        """Matches the reviewed `data_sources` row seeded in migration 0004.

        `redistribution_allowed=False`, as reviewed: EDGAR permits automated *access*
        (`DATA_FOUNDATION.md` §6.4) and that says nothing about re-serving. Almost certainly
        the most permissive source in the register — US federal works — but no reviewed
        determination exists, and `register()` refuses a connector that claims otherwise.
        """
        return DataSourceLicence(
            source_name=SOURCE_NAME,
            base_url=_BASE,
            licence_type="us_federal_public",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: U.S. Securities and Exchange Commission (EDGAR)",
            terms_url=None,
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=10,
            notes="See migration 0004: access permitted, redistribution not asserted.",
        )

    def _get(self, url: str) -> RawResponse:
        """One throttled request with the mandatory headers. 403/429 stops everything.

        A 5xx or a timeout is EDGAR's own trouble, not ours: it is retried once after a
        pause, because a backfill over a hundred filings should not fall over on one server
        hiccup or one slow multi-megabyte instance. A second failure is raised as it is.
        """
        try:
            response = self._request(url)
        except httpx.TimeoutException:
            _log.warning("edgar_timeout_retried", url=url)
            time.sleep(_SERVER_ERROR_PAUSE_SEC)
            response = self._request(url)
        else:
            if response.status_code >= 500:
                _log.warning("edgar_server_error_retried", url=url, status=response.status_code)
                time.sleep(_SERVER_ERROR_PAUSE_SEC)
                response = self._request(url)
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            url=url,
            http_status=response.status_code,
            etag=response.headers.get("etag"),
            last_modified=_parse_http_date(response.headers.get("last-modified")),
        )

    def _request(self, url: str) -> httpx.Response:
        self._throttle.wait()
        response = httpx.get(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=self._timeout,
            follow_redirects=False,
        )
        if response.status_code in (403, 429):
            raise EdgarRefusedError(
                f"EDGAR refused {url} with HTTP {response.status_code}. This is the rate limit "
                f"or a missing User-Agent, and it comes with a ~10-minute IP block. Not retried."
            )
        return response


#: How long to wait before the one retry of a 5xx. EDGAR's brief outages clear in seconds.
_SERVER_ERROR_PAUSE_SEC = 5.0

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


def load_ticker_map(session: Session, connector: EdgarConnector) -> dict[str, str]:
    """Ticker → zero-padded CIK, from EDGAR's own `company_tickers.json`, fetched once.

    The file is stored as a source document like any other response: it is the mapping
    the rest of the run relied on, and six months from now "why did AAPL resolve to this
    CIK" deserves an answer with a hash on it.
    """
    raw = connector._get(_TICKERS_URL)
    store_raw(session, raw, connector=connector)
    payload = json.loads(raw.data.decode("utf-8"))
    rows = payload.values() if isinstance(payload, dict) else payload
    mapping: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("ticker") and row.get("cik_str") is not None:
            mapping[str(row["ticker"]).upper()] = zero_pad_cik(str(row["cik_str"]))
    return mapping


def resolve_cik(
    session: Session,
    connector: EdgarConnector,
    ticker: str,
    *,
    ticker_map: dict[str, str] | None = None,
) -> str:
    """One ticker → CIK; pass `ticker_map` from `load_ticker_map` to resolve many."""
    wanted = ticker.strip().upper()
    mapping = ticker_map if ticker_map is not None else load_ticker_map(session, connector)
    try:
        return mapping[wanted]
    except KeyError:
        raise LookupError(f"ticker {wanted!r} is not in EDGAR's company_tickers.json") from None


# ---------------------------------------------------------------------------------------
# Submissions: who the company is
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompanyRecord:
    cik: str
    name: str
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    fiscal_year_end_month: int | None
    sic: str | None
    sic_description: str | None
    entity_type: str | None
    state_of_incorporation: str | None
    #: The earliest filing date in the payload's recent list: a day the CIK certainly
    #: identified the registrant. Not its first day - the list is capped at a thousand.
    earliest_filing_seen: dt.date | None = None


class EdgarSubmissionsConnector(EdgarConnector):
    """`/submissions/CIK##########.json` → companies, securities, tickers, industry."""

    name = "edgar_submissions"

    def fetch(self, **params: object) -> RawResponse:
        cik = zero_pad_cik(str(params["cik"]))
        return self._get(f"{_BASE}/submissions/CIK{cik}.json")

    def parse(self, raw: RawResponse) -> list[CompanyRecord]:  # type: ignore[override]
        payload = json.loads(raw.data.decode("utf-8"))
        fye_month = _fiscal_year_end_month(payload.get("fiscalYearEnd"))
        return [
            CompanyRecord(
                cik=zero_pad_cik(str(payload["cik"])),
                name=str(payload.get("name") or "").strip(),
                earliest_filing_seen=_earliest_filing_seen(payload),
                tickers=tuple(str(t).strip().upper() for t in payload.get("tickers") or [] if t),
                exchanges=tuple(str(e).strip() for e in payload.get("exchanges") or [] if e),
                fiscal_year_end_month=fye_month,
                sic=str(payload["sic"]).strip() if payload.get("sic") else None,
                sic_description=(
                    str(payload["sicDescription"]).strip()
                    if payload.get("sicDescription")
                    else None
                ),
                entity_type=str(payload["entityType"]) if payload.get("entityType") else None,
                state_of_incorporation=(
                    str(payload["stateOfIncorporation"])
                    if payload.get("stateOfIncorporation")
                    else None
                ),
            )
        ]

    def write(  # type: ignore[override]
        self, session: Session, records: list[CompanyRecord], *, source_document_id: int
    ) -> int:
        """Register the company. Reference data is inserted when absent, never overwritten.

        A company already present keeps its row: a changed legal name is logged, not
        applied (`CLAUDE.md`: no silent overwrites), and identity history is P3's TG2 work.
        Returns the number of rows inserted across the four tables.
        """
        inserted = 0
        for record in records:
            if record.fiscal_year_end_month is None:
                raise ValueError(
                    f"CIK {record.cik}: submissions carry no fiscalYearEnd; "
                    "companies.fiscal_year_end is NOT NULL and must not be guessed"
                )
            successor = successor_of(record.cik)
            if successor is not None:
                # The old registrant of a continuing company: its name, tickers and industry
                # are history, not identity. Record its CIK against the successor's security,
                # bounded by the succession date, and register nothing else.
                inserted += _record_predecessor(session, record, successor)
                continue
            industry_id, added = _upsert_industry(session, record)
            inserted += added
            company = _company_for_cik(session, record.cik)
            if company is None:
                company = Company(
                    legal_name=record.name,
                    country="US",
                    industry_id=industry_id,
                    statement_template=_template_for_sic(record.sic),
                    fiscal_year_end=record.fiscal_year_end_month,
                )
                session.add(company)
                session.flush()
                inserted += 1
            elif company.legal_name != record.name:
                _log.warning(
                    "company_name_differs_from_submissions",
                    cik=record.cik,
                    stored=company.legal_name,
                    submissions=record.name,
                )

            observed_on = utcnow().date()
            # EDGAR's `tickers` and `exchanges` are parallel lists, one entry per ticker:
            # Alphabet is tickers ["GOOGL", "GOOG"], exchanges ["Nasdaq", "Nasdaq"]. Each
            # ticker attaches to the security on its own exchange, and a security is
            # created once per exchange however many tickers it carries.
            securities_by_code: dict[str, Security] = {}
            for ticker, exchange_name in _ticker_exchange_pairs(record):
                code = _EXCHANGE_CODES.get(exchange_name)
                if code is None:
                    _log.warning("unknown_edgar_exchange", cik=record.cik, exchange=exchange_name)
                    continue
                security = securities_by_code.get(code)
                if security is None:
                    exchange = session.execute(
                        select(Exchange).where(Exchange.code == code)
                    ).scalar_one()
                    security = session.execute(
                        select(Security)
                        .where(Security.company_id == company.id)
                        .where(Security.exchange_id == exchange.id)
                    ).scalar_one_or_none()
                    if security is None:
                        security = Security(
                            company_id=company.id, exchange_id=exchange.id, currency="USD"
                        )
                        session.add(security)
                        session.flush()
                        inserted += 1
                    securities_by_code[code] = security
                # Resolved through the one resolver, and scoped to this exchange since
                # migration 0018: a ticker string is unique per market, not globally, so
                # the same string legitimately listed on two exchanges is two identifiers
                # of two securities rather than the first one found winning.
                current = resolve_security(session, value=ticker, as_of=observed_on, exchange=code)
                if current is None:
                    # valid_from is the day we first observed the ticker - a lower bound on
                    # its validity, never a claim about when it began. Submissions do not
                    # say; TG2 (P3) is where identifier history gets real dates.
                    #
                    # EDGAR lists a registrant's common stock before its notes and
                    # preferred series, so the first ticker stored for a security is the
                    # primary one. `one_primary_ticker_per_security` then holds it to one.
                    session.add(
                        SecurityIdentifier(
                            security_id=security.id,
                            id_type=TICKER,
                            id_value=ticker,
                            valid_from=observed_on,
                            valid_to=None,
                            exchange_id=security.exchange_id,
                            is_primary=not has_primary_ticker(session, security_id=security.id),
                            source="edgar_submissions",
                        )
                    )
                    session.flush()
                    inserted += 1

            # After the securities, because the CIK hangs off the primary one (0019).
            inserted += _record_cik(session, company, record.cik, observed_on=observed_on)
        session.flush()
        return inserted


def _record_predecessor(session: Session, record: CompanyRecord, successor: str) -> int:
    """A predecessor CIK as a time-bounded identifier of the successor's primary security.

    `valid_from` is the earliest filing date the payload shows - a day the CIK certainly
    identified the registrant, so the interval is one we can vouch for - and `valid_to` is
    the succession date. When the payload shows no filing, the interval is the succession
    day alone: coherent, and honest about what was seen.
    """
    cik = record.cik
    successor_company_id = company_for_identifier(session, value=successor, as_of=utcnow().date())
    company = session.get(Company, successor_company_id) if successor_company_id else None
    if company is None:
        raise LookupError(
            f"CIK {cik} is the predecessor of {successor}, which is not registered yet. "
            "Register the successor first (its ticker resolves to it); the predecessor's "
            "filings are then written under it."
        )
    security = _primary_security(session, company)
    # "Have we stored this already", not "what did it mean on a date" - so
    # `identifier_exists`, which takes no date, rather than the dated resolver.
    if identifier_exists(session, value=cik, id_type=CIK):
        return 0
    predecessor = PREDECESSORS[successor]
    valid_from = record.earliest_filing_seen or predecessor.succeeded_on
    session.add(
        SecurityIdentifier(
            security_id=security.id,
            id_type=CIK,
            id_value=cik,
            valid_from=min(valid_from, predecessor.succeeded_on),
            # Inclusive, as everywhere: the last day this CIK identified the registrant.
            # `exchange_id` stays NULL - a CIK names a registrant, not a listing.
            valid_to=predecessor.succeeded_on,
            source="edgar_predecessor_map",
        )
    )
    session.flush()
    _log.info(
        "predecessor_registrant_recorded",
        cik=cik,
        successor=successor,
        succeeded_on=predecessor.succeeded_on.isoformat(),
        evidence=predecessor.evidence,
    )
    return 1


def _ticker_exchange_pairs(record: CompanyRecord) -> list[tuple[str, str]]:
    """(ticker, exchange) pairs from EDGAR's parallel lists, tolerating a short exchange list."""
    if not record.tickers:
        return []
    exchanges = list(record.exchanges) or [""]
    pairs = []
    for index, ticker in enumerate(record.tickers):
        exchange = exchanges[index] if index < len(exchanges) else exchanges[-1]
        pairs.append((ticker, exchange))
    return pairs


def _earliest_filing_seen(payload: dict[str, object]) -> dt.date | None:
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    dates = recent.get("filingDate") if isinstance(recent, dict) else None
    if not isinstance(dates, list):
        return None
    parsed = []
    for value in dates:
        try:
            parsed.append(dt.date.fromisoformat(str(value)))
        except ValueError:
            continue
    return min(parsed) if parsed else None


def _fiscal_year_end_month(value: object) -> int | None:
    """EDGAR's `fiscalYearEnd` is 'MMDD' ('0926' for Apple). The month, or None if absent."""
    text = str(value or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    month = int(text[:2])
    return month if 1 <= month <= 12 else None


def _template_for_sic(sic: str | None) -> str:
    """`companies.statement_template` from the SIC division. Editable, and a default only."""
    if sic and sic.isdigit():
        code = int(sic)
        if 6000 <= code <= 6299 or 6700 <= code <= 6799:
            return "bank"
        if 6300 <= code <= 6499:
            return "insurance"
    return "non_financial"


def _upsert_industry(session: Session, record: CompanyRecord) -> tuple[int | None, int]:
    if not record.sic:
        return None, 0
    row = session.execute(
        select(Industry).where(Industry.scheme == "sic").where(Industry.code == record.sic)
    ).scalar_one_or_none()
    if row is not None:
        return row.id, 0
    row = Industry(
        scheme="sic",
        code=record.sic,
        name=record.sic_description or f"SIC {record.sic}",
        statement_template=_template_for_sic(record.sic),
    )
    session.add(row)
    session.flush()
    return row.id, 1


# ---------------------------------------------------------------------------------------
# Company facts: what the company reported
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class XbrlFact:
    """One XBRL fact as EDGAR carries it. `filed` is `known_as_of`; `end` is the period."""

    cik: str
    taxonomy: str  # 'us-gaap'|'dei'|...
    tag: str
    unit: str
    start: dt.date | None  # None for an instant (balance-sheet) fact
    end: dt.date
    value: Decimal | None
    accession_no: str
    form: str
    filed: dt.date
    #: The filing's reporting context. NOT the fact's period - see normalize.periods.
    fy: int | None
    fp: str | None
    frame: str | None


#: The cover-page share count every 10-K and 10-Q carries: an instant fact whose `end` is
#: the date the count was true of. It feeds `shares_outstanding` (`docs/08` §2.14 #49).
SHARES_OUTSTANDING_FACT = ("dei", "EntityCommonStockSharesOutstanding", "shares")


class EdgarCompanyFactsConnector(EdgarConnector):
    """`/api/xbrl/companyfacts/CIK##########.json` → statements, line items, share counts."""

    name = "edgar_companyfacts"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout_sec: float = 120.0,
        throttle: _Throttle | None = None,
        chart_version: str = CHART_VERSION,
        units: frozenset[str] = frozenset({"USD"}),
    ) -> None:
        super().__init__(user_agent=user_agent, timeout_sec=timeout_sec, throttle=throttle)
        self._chart_version = chart_version
        self._units = units

    def fetch(self, **params: object) -> RawResponse:
        cik = zero_pad_cik(str(params["cik"]))
        return self._get(f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json")

    def parse(self, raw: RawResponse) -> list[XbrlFact]:  # type: ignore[override]
        """Pure. Every us-gaap fact in a monetary unit, plus the cover-page share count.

        Nothing here knows the chart: which tags matter is a database question and belongs
        in `write()`. Keeping every monetary fact also means a mapping added next month is
        served by the raw document already stored, without a re-fetch.
        """
        payload = json.loads(raw.data.decode("utf-8"))
        cik = zero_pad_cik(str(payload["cik"]))
        facts: list[XbrlFact] = []
        for taxonomy, tags in (payload.get("facts") or {}).items():
            for tag, body in tags.items():
                for unit, entries in (body.get("units") or {}).items():
                    if not self._keeps(taxonomy, tag, unit):
                        continue
                    for entry in entries:
                        fact = _fact_from(cik, taxonomy, tag, unit, entry)
                        if fact is not None:
                            facts.append(fact)
        facts.sort(key=_fact_order)
        return facts

    def _keeps(self, taxonomy: str, tag: str, unit: str) -> bool:
        if taxonomy == "us-gaap" and unit in self._units:
            return True
        return (taxonomy, tag, unit) == SHARES_OUTSTANDING_FACT

    def write(  # type: ignore[override]
        self, session: Session, records: list[XbrlFact], *, source_document_id: int
    ) -> int:
        """Facts → filings → statements → line items, through the chart. Returns rows inserted.

        Filings are applied in the order they were filed, so a period's first report is
        version 1 and every later filing is judged against what was known before it.
        """
        if not records:
            return 0
        cik = records[0].cik
        if successor_of(cik) is not None:
            _log.info(
                "predecessor_filings_written_under_successor", cik=cik, successor=successor_of(cik)
            )
        records, unknowable = _split_unknowable(records)
        if unknowable:
            _log.warning(
                "facts_ending_after_their_filing_dropped",
                cik=cik,
                count=len(unknowable),
                facts=[
                    f"{f.tag} end={f.end} filed={f.filed} {f.form} {f.accession_no}"
                    for f in unknowable[:5]
                ],
            )
        company = _company_for_cik(session, cik)
        if company is None:
            raise LookupError(
                f"CIK {cik} is not registered. Run EdgarSubmissionsConnector first: a statement "
                "needs a company, a security and a fiscal year end, and none of those is guessed."
            )
        security = _primary_security(session, company)
        share_facts = [f for f in records if (f.taxonomy, f.tag, f.unit) == SHARES_OUTSTANDING_FACT]
        records = [f for f in records if (f.taxonomy, f.tag, f.unit) != SHARES_OUTSTANDING_FACT]
        shares_inserted = _write_share_counts(
            session,
            share_facts,
            security_id=security.id,
            source_document_id=source_document_id,
        )
        chart = load_chart(session, version=self._chart_version, source_system=SOURCE_SYSTEM)
        template = _chart_template(company.statement_template)
        tag_to_key = {m.source_label: key for key, group in chart.mappings.items() for m in group}

        job = ExtractionJob(
            source_document_id=source_document_id,
            method="xbrl",
            status="stored",
            started_at=utcnow(),
        )
        session.add(job)
        session.flush()

        # (accession) -> (statement_type, period_type, end) -> context start -> tag -> fact
        by_filing: dict[str, dict[_PeriodSlot, dict[dt.date | None, dict[str, XbrlFact]]]]
        by_filing = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        filing_meta: dict[str, tuple[str, dt.date, dt.date]] = {}  # accn -> (form, filed, max end)
        skipped_period = 0
        for fact in records:
            key = tag_to_key.get(fact.tag)
            if key is None:
                continue
            period_type = period_type_of(fact.start, fact.end, company.fiscal_year_end)
            if period_type is None:
                skipped_period += 1
                continue
            statement_type = chart.statement_of(key)
            slot = by_filing[fact.accession_no][(statement_type, period_type, fact.end)][fact.start]
            existing = slot.get(fact.tag)
            # Prefer the entry EDGAR marks with a calendar frame - its canonical one.
            if existing is None or (existing.frame is None and fact.frame is not None):
                slot[fact.tag] = fact
            form, filed, latest_end = filing_meta.get(
                fact.accession_no, (fact.form, fact.filed, fact.end)
            )
            filing_meta[fact.accession_no] = (form, filed, max(latest_end, fact.end))
        if skipped_period:
            _log.info("facts_with_unnamed_periods_skipped", cik=cik, count=skipped_period)

        writer = StatementWriter(
            session,
            company_id=company.id,
            security_id=security.id,
            chart=chart,
            template=template,
            currency="USD",
            source_document_id=source_document_id,
            extraction_job_id=job.id,
        )
        filings_inserted = 0
        for accession in sorted(by_filing, key=lambda a: (filing_meta[a][1], a)):
            form, filed, latest_end = filing_meta[accession]
            filing, added = _upsert_filing(
                session,
                company_id=company.id,
                form=form,
                filed=filed,
                period_end=latest_end,
                accession=accession,
                source_document_id=source_document_id,
            )
            filings_inserted += added
            reported: list[ReportedStatement] = []
            for (statement_type, period_type, end), contexts in sorted(
                by_filing[accession].items(), key=lambda item: (item[0][2], item[0][0], item[0][1])
            ):
                start, facts_by_tag = _merge_contexts(
                    contexts,
                    cik=cik,
                    accession=accession,
                    period=(statement_type, period_type, end),
                )
                keys = chart.keys_for(statement_type, template)
                reported_by_tag = {tag: f.value for tag, f in facts_by_tag.items()}
                values = resolve(reported_by_tag, chart, keys)
                # Keys none of whose tags were in this filing are absent, not reported-as-NULL.
                present = {
                    key: value
                    for key, value in values.items()
                    if any(m.source_label in reported_by_tag for m in chart.mappings.get(key, ()))
                }
                fiscal_year = fiscal_year_of(end, company.fiscal_year_end)
                reported.append(
                    ReportedStatement(
                        statement_type=statement_type,
                        period_type=period_type,
                        period_start=start,
                        period_end=end,
                        fiscal_year=fiscal_year,
                        period_label=period_label(period_type, fiscal_year),
                        values=present,
                        accession_no=accession,
                        form=form,
                        filed=filed,
                    )
                )
            writer.write_filing(reported, filing_id=filing.id)
        job.finished_at = utcnow()
        session.flush()
        outcome = writer.outcome
        _log.info(
            "edgar_statements_written",
            cik=cik,
            filings=len(by_filing),
            filings_inserted=filings_inserted,
            statements_inserted=outcome.statements_inserted,
            statements_restated=outcome.statements_restated,
            statements_unchanged=outcome.statements_unchanged,
            statements_stale=outcome.statements_stale,
            line_items_inserted=outcome.line_items_inserted,
            share_counts_inserted=shares_inserted,
            facts_unknowable_dropped=len(unknowable),
        )
        return outcome.line_items_inserted + filings_inserted + shares_inserted


_PeriodSlot = tuple[str, str, dt.date]  # (statement_type, period_type, period_end)


def _merge_contexts(
    contexts: dict[dt.date | None, dict[str, XbrlFact]],
    *,
    cik: str,
    accession: str,
    period: _PeriodSlot,
) -> tuple[dt.date | None, dict[str, XbrlFact]]:
    """One statement per named period, however many contexts the filing spread it over.

    Cisco's Q3 FY2011 10-Q reports the quarter to 2011-04-30 under two contexts: the
    thirteen weeks from 2011-01-30, carrying 36 facts, and four facts - gross profit among
    them - from 2011-02-01, a context-date slip. The period vocabulary names both `Q3`, and
    one filing cannot hold two version-1 statements of one period; the writer refused the
    second and the whole company was lost. The context carrying the most facts *is* the
    statement; the others contribute only the tags it lacks, and the merge is logged. A tag
    both carry with different values is a conflict: the statement's own value stands and
    the other is logged - never averaged, never guessed (`docs/08` §2.3).
    """
    if len(contexts) == 1:
        ((start, facts),) = contexts.items()
        return start, facts
    ranked = sorted(contexts.items(), key=lambda kv: (-len(kv[1]), kv[0] or dt.date.min))
    start, primary = ranked[0]
    merged = dict(primary)
    added: list[str] = []
    conflicts: list[str] = []
    for other_start, facts in ranked[1:]:
        for tag, fact in facts.items():
            mine = merged.get(tag)
            if mine is None:
                merged[tag] = fact
                added.append(f"{tag} from {other_start}")
            elif mine.value != fact.value:
                conflicts.append(
                    f"{tag}: {mine.value} from {start} vs {fact.value} from {other_start}"
                )
    _log.warning(
        "period_reported_under_several_contexts",
        cik=cik,
        accession=accession,
        period=f"{period[0]} {period[1]} to {period[2]}",
        contexts=[f"{s} ({len(f)} facts)" for s, f in ranked],
        tags_added=added[:5],
        conflicts=conflicts[:5],
    )
    return start, merged


def _newest_report(session: Session, cik: str) -> str | None:
    """The accession of the newest 10-K or 10-Q held for a company, or None."""
    company = _company_for_cik(session, cik)
    if company is None:
        return None
    return session.execute(
        select(Filing.accession_no)
        .where(Filing.company_id == company.id)
        .where(Filing.filing_type.in_(["10-K", "10-Q"]))
        .where(Filing.accession_no.is_not(None))
        .order_by(Filing.filing_date.desc(), Filing.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _split_unknowable(facts: list[XbrlFact]) -> tuple[list[XbrlFact], list[XbrlFact]]:
    """Keep the facts a filing could have known; set aside those it could not.

    A fact whose period ends *after* the filing that reported it cannot have been known on
    the filing date. It is a filer context error - Walmart's FY2011 and FY2012 10-Ks carry
    three, a cash balance "at 2012-12-31" filed 2012-03-27 among them - and every figure
    table's `pit_sanity` check (`known_as_of >= period_end`) refuses it, which aborted a
    whole company's load before this filter existed. The fact is dropped and logged, never
    date-corrected: the right date is not knowable from the filing, and the raw document
    keeps the fact as filed (`docs/08` §2.3).
    """
    kept = [f for f in facts if f.end <= f.filed]
    dropped = [f for f in facts if f.end > f.filed]
    return kept, dropped


# ---------------------------------------------------------------------------------------
# Per-class share counts, read from the filing's XBRL instance
# ---------------------------------------------------------------------------------------

#: Companies whose cover page counts each share class separately. companyfacts drops every
#: dimensioned fact, so their `dei:EntityCommonStockSharesOutstanding` never reaches it and
#: no P/E can be computed from that feed. The count lives in each filing's XBRL instance,
#: one fact per class member, and that is what `EdgarInstanceSharesConnector` reads.
CLASS_COUNTED_CIKS: frozenset[str] = frozenset(
    {
        "0001652044",  # Alphabet: Class A, Class B, Capital Class C
        "0001326801",  # Meta Platforms: Class A, Class B
    }
)

_XBRL_INSTANCE_NS = "http://www.xbrl.org/2003/instance"
_XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
_CLASS_AXIS = "StatementClassOfStockAxis"


@dataclass(frozen=True)
class ClassShareCount:
    """One class's cover-page count, as an instance document carries it."""

    cik: str
    accession_no: str
    share_class: str  # the axis member's local name without 'Member', or 'ordinary'
    as_of_date: dt.date
    shares: Decimal


class EdgarInstanceSharesConnector(EdgarConnector):
    """One filing's XBRL instance -> `shares_outstanding`, one row per share class.

    The folder index names the instance (`*_htm.xml`); the instance is what is stored and
    parsed. A count's `known_as_of` is the filing date of the accession the instance came
    from, read from `filings` at write time - the instance itself does not carry it.
    """

    name = "edgar_instance_shares"

    def fetch(self, **params: object) -> RawResponse:
        cik = zero_pad_cik(str(params["cik"]))
        accession = str(params["accession_no"])
        folder = f"{_ARCHIVE}/{int(cik)}/{accession.replace('-', '')}/"
        index = json.loads(self._get(folder + "index.json").data.decode("utf-8"))
        names = [
            str(item.get("name") or "")
            for item in (index.get("directory") or {}).get("item") or []
            if isinstance(item, dict)
        ]
        instances = _instance_documents(names)
        if len(instances) != 1:
            raise LookupError(
                f"{accession}: expected one XBRL instance in the folder, found "
                f"{instances or 'none'} among {sorted(n for n in names if n.endswith('.xml'))}"
            )
        return self._get(folder + instances[0])

    def parse(self, raw: RawResponse) -> list[ClassShareCount]:  # type: ignore[override]
        """Pure. Every `dei:EntityCommonStockSharesOutstanding` fact with its class and date.

        The accession is read from the stored URL, which names the filing's folder; the
        instance carries the CIK itself.
        """
        accession = _accession_from_url(raw.url or "")
        root = ET.fromstring(raw.data)
        contexts: dict[str, tuple[dt.date | None, str]] = {}
        for context in root.iter(f"{{{_XBRL_INSTANCE_NS}}}context"):
            instant = context.find(f"{{{_XBRL_INSTANCE_NS}}}period/{{{_XBRL_INSTANCE_NS}}}instant")
            share_class = "ordinary"
            for member in context.iter(f"{{{_XBRLDI_NS}}}explicitMember"):
                if str(member.get("dimension") or "").endswith(_CLASS_AXIS) and member.text:
                    share_class = member.text.strip().split(":")[-1].removesuffix("Member")
            date = (
                dt.date.fromisoformat(instant.text.strip())
                if instant is not None and instant.text
                else None
            )
            contexts[str(context.get("id"))] = (date, share_class)
        cik = ""
        for element in root.iter():
            if _is_dei(element, "EntityCentralIndexKey") and element.text:
                cik = zero_pad_cik(element.text.strip())
                break
        counts: list[ClassShareCount] = []
        for element in root.iter():
            if not _is_dei(element, "EntityCommonStockSharesOutstanding") or not element.text:
                continue
            date, share_class = contexts.get(str(element.get("contextRef")), (None, "ordinary"))
            if date is None:
                continue
            try:
                shares = Decimal(element.text.strip())
            except InvalidOperation:
                continue
            if shares <= 0:
                continue
            counts.append(
                ClassShareCount(
                    cik=cik,
                    accession_no=accession,
                    share_class=share_class,
                    as_of_date=date,
                    shares=shares,
                )
            )
        counts.sort(key=lambda c: (c.as_of_date, c.share_class))
        return counts

    def write(  # type: ignore[override]
        self, session: Session, records: list[ClassShareCount], *, source_document_id: int
    ) -> int:
        if not records:
            return 0
        cik = records[0].cik
        accession = records[0].accession_no
        company = _company_for_cik(session, cik)
        if company is None:
            raise LookupError(f"CIK {cik} is not registered; run the submissions connector first")
        filing = session.execute(
            select(Filing)
            .where(Filing.company_id == company.id)
            .where(Filing.accession_no == accession)
        ).scalar_one_or_none()
        if filing is None:
            raise LookupError(
                f"{accession} is not in filings for CIK {cik}; load the company facts first - "
                "a count's known_as_of is the filing date, and it is not guessed"
            )
        security = _primary_security(session, company)
        return _write_class_counts(
            session,
            records,
            security_id=security.id,
            filed=filing.filing_date,
            source_document_id=source_document_id,
        )


#: An inline-XBRL filing (2019 on) carries its instance as `<name>_htm.xml`; before that the
#: instance is `<prefix>-<yyyymmdd>.xml` beside the schema and the four linkbases, which
#: end in _cal, _def, _lab and _pre and are not instances.
_LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
_PLAIN_INSTANCE = re.compile(r"^[a-z0-9]+-\d{8}\.xml$", re.IGNORECASE)


def _instance_documents(names: list[str]) -> list[str]:
    inline = [n for n in names if n.endswith("_htm.xml")]
    if inline:
        return inline
    return [n for n in names if _PLAIN_INSTANCE.match(n) and not n.endswith(_LINKBASE_SUFFIXES)]


def _is_dei(element: ET.Element, local_name: str) -> bool:
    tag = element.tag
    return isinstance(tag, str) and tag.endswith("}" + local_name) and "xbrl.sec.gov/dei" in tag


def _accession_from_url(url: str) -> str:
    """`.../edgar/data/1652044/000165204426000071/goog-20260630_htm.xml` -> the accession."""
    match = re.search(r"/(\d{18})/[^/]*$", url)
    if match is None:
        raise ValueError(f"the stored URL does not name a filing folder: {url!r}")
    digits = match.group(1)
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def _write_class_counts(
    session: Session,
    counts: list[ClassShareCount],
    *,
    security_id: int,
    filed: dt.date,
    source_document_id: int,
) -> int:
    """Per-class counts -> `shares_outstanding`, one vintage rule with the cover-page path."""
    stored = session.execute(
        select(
            SharesOutstanding.share_class,
            SharesOutstanding.as_of_date,
            SharesOutstanding.known_as_of,
            SharesOutstanding.shares,
        )
        .where(SharesOutstanding.security_id == security_id)
        .where(SharesOutstanding.basic_or_diluted == "basic")
    ).all()
    history: dict[tuple[str, dt.date], list[tuple[dt.date, Decimal]]] = {}
    for share_class, as_of_date, known_as_of, shares in stored:
        history.setdefault((share_class, as_of_date), []).append((known_as_of, shares))
    for versions in history.values():
        versions.sort()
    rows: list[dict[str, object]] = []
    for count in counts:
        versions = history.get((count.share_class, count.as_of_date), [])
        if versions and versions[-1][1] == count.shares:
            continue  # the same count for the same date and class: the same vintage
        if any(known == filed for known, _ in versions):
            continue  # this filing's own vintage is already held
        rows.append(
            {
                "security_id": security_id,
                "as_of_date": count.as_of_date,
                "share_class": count.share_class,
                "basic_or_diluted": "basic",
                "known_as_of": filed,
                "shares": count.shares,
                "source_document_id": source_document_id,
                "page": None,
            }
        )
    if not rows:
        return 0
    statement = (
        pg_insert(SharesOutstanding)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(SharesOutstanding.as_of_date)
    )
    return len(session.execute(statement).fetchall())


# ---------------------------------------------------------------------------------------
# The scheduled refresh: identity, then statements, for one company, under one job name
# ---------------------------------------------------------------------------------------


class EdgarCompanyRefresh(EdgarConnector):
    """One company's nightly refresh: submissions, then company facts, as one scheduled job.

    Statements were loaded by hand (`scripts/ingest_edgar.py`) while P2 was built; the
    freshness flag on `/companies` then asked, on its first live run, for the Coca-Cola
    10-Q the copy did not hold. This is the job that answers it. It runs the same two
    connectors the script runs, records their runs under the same names the script uses
    (`edgar_submissions:<cik>`, `edgar_companyfacts:<cik>`) so history reads continuously,
    and records its own run under the job's identity (`edgar:<ticker>`) so the health check
    can expect exactly one thing per company per night.

    The ticker is resolved through EDGAR's own list once per process per UTC day, and the
    list is stored as a source document like every other response.
    """

    name = "edgar_refresh"

    #: (day the map was fetched, ticker -> CIK). One process, one fetch per day.
    _ticker_map: tuple[dt.date, dict[str, str]] | None = None

    def fetch(self, **params: object) -> RawResponse:
        raise NotImplementedError("EdgarCompanyRefresh runs two connectors; call run()")

    def parse(self, raw: RawResponse) -> list[object]:
        raise NotImplementedError("EdgarCompanyRefresh runs two connectors; call run()")

    def run(
        self,
        session: Session,
        *,
        storage: StorageBackend | None = None,
        run_name: str | None = None,
        **params: object,
    ) -> ConnectorRunResult:
        recorded_as = run_name or self.name
        started_at = utcnow()
        rows = 0
        parsed = 0
        error: str | None = None
        try:
            with step("resolve the company") as resolving:
                cik = self._cik_for(session, params)
                resolving.result(cik=cik)
            first = EdgarSubmissionsConnector(
                user_agent=self._user_agent, throttle=self._throttle
            ).run(session, storage=storage, run_name=f"edgar_submissions:{cik}", cik=cik)
            rows += first.rows_written
            parsed += first.records_parsed
            if first.status != "ok":
                error = f"submissions: {first.error}"
            else:
                second = EdgarCompanyFactsConnector(
                    user_agent=self._user_agent, throttle=self._throttle
                ).run(session, storage=storage, run_name=f"edgar_companyfacts:{cik}", cik=cik)
                rows += second.rows_written
                parsed += second.records_parsed
                if second.status != "ok":
                    error = f"companyfacts: {second.error}"
            if error is None and cik in CLASS_COUNTED_CIKS:
                # The newest 10-K or 10-Q's instance: the cover-page count per class,
                # which companyfacts never carries for these companies.
                newest = _newest_report(session, cik)
                if newest is not None:
                    third = EdgarInstanceSharesConnector(
                        user_agent=self._user_agent, throttle=self._throttle
                    ).run(
                        session,
                        storage=storage,
                        run_name=f"edgar_instance_shares:{cik}",
                        cik=cik,
                        accession_no=newest,
                    )
                    rows += third.rows_written
                    parsed += third.records_parsed
                    if third.status != "ok":
                        error = f"instance shares: {third.error}"
            predecessor = PREDECESSORS.get(cik)
            if error is None and predecessor is not None:
                # The old registrant's filings: registered as an identifier, then written
                # under the continuing company. A late restatement filed under the old CIK
                # is still a restatement of this company's history.
                for stage, connector in (
                    ("submissions", EdgarSubmissionsConnector),
                    ("companyfacts", EdgarCompanyFactsConnector),
                ):
                    run = connector(user_agent=self._user_agent, throttle=self._throttle).run(
                        session,
                        storage=storage,
                        run_name=f"edgar_{stage}:{predecessor.cik}",
                        cik=predecessor.cik,
                    )
                    rows += run.rows_written
                    parsed += run.records_parsed
                    if run.status != "ok":
                        error = f"predecessor {stage}: {run.error}"
                        break
        except Exception as exc:  # the lookup itself failed: unknown ticker, EDGAR refusal
            session.rollback()
            error = f"{type(exc).__name__}: {exc}"[:2000]
            _log.error("connector_failed", connector=self.name, error_type=type(exc).__name__)
        result = ConnectorRunResult(
            connector_name=recorded_as,
            status="error" if error else "ok",
            rows_written=rows,
            records_parsed=parsed,
            started_at=started_at,
            finished_at=utcnow(),
            error=error,
        )
        with step("record run") as recording:
            record_run(session, result)
            recording.result(status=result.status, rows_written=result.rows_written)
        return result

    def _cik_for(self, session: Session, params: dict[str, object]) -> str:
        if params.get("cik"):
            return zero_pad_cik(str(params["cik"]))
        ticker = str(params["ticker"]).strip().upper()
        today = utcnow().date()
        cached = EdgarCompanyRefresh._ticker_map
        if cached is None or cached[0] != today:
            cached = (today, load_ticker_map(session, self))
            EdgarCompanyRefresh._ticker_map = cached
        return resolve_cik(session, self, ticker, ticker_map=cached[1])


def _write_share_counts(
    session: Session, facts: list[XbrlFact], *, security_id: int, source_document_id: int
) -> int:
    """Cover-page share counts → `shares_outstanding`. A count is a vintage of its as-of date.

    The same as-of date re-reported with the same count in a later filing is the same
    vintage and is skipped; a different count for the same date is a second row with the
    later filing date as `known_as_of` - the rule every figure table here follows.
    """
    if not facts:
        return 0
    counts: dict[dt.date, list[tuple[dt.date, Decimal]]] = {}
    stored = session.execute(
        select(
            SharesOutstanding.as_of_date, SharesOutstanding.known_as_of, SharesOutstanding.shares
        )
        .where(SharesOutstanding.security_id == security_id)
        .where(SharesOutstanding.basic_or_diluted == "basic")
        .where(SharesOutstanding.share_class == "ordinary")
    ).all()
    for as_of_date, known_as_of, shares in stored:
        counts.setdefault(as_of_date, []).append((known_as_of, shares))
    for history in counts.values():
        history.sort()

    rows: list[dict[str, object]] = []
    for fact in sorted(facts, key=lambda f: (f.end, f.filed)):
        if fact.value is None or fact.value <= 0 or fact.start is not None:
            continue
        history = counts.get(fact.end, [])
        earlier = [v for v in history if v[0] < fact.filed]
        if earlier and earlier[-1][1] == fact.value:
            continue
        if any(v[0] == fact.filed for v in history):
            continue
        rows.append(
            {
                "security_id": security_id,
                "as_of_date": fact.end,
                "shares": fact.value,
                "share_class": "ordinary",
                "basic_or_diluted": "basic",
                "known_as_of": fact.filed,
                "source_document_id": source_document_id,
                "page": None,
            }
        )
        counts.setdefault(fact.end, []).append((fact.filed, fact.value))
        counts[fact.end].sort()
    if not rows:
        return 0
    statement = (
        pg_insert(SharesOutstanding)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[
                "security_id",
                "as_of_date",
                "share_class",
                "basic_or_diluted",
                "known_as_of",
            ]
        )
        .returning(SharesOutstanding.as_of_date)
    )
    return len(session.execute(statement).fetchall())


def _chart_template(company_template: str) -> str:
    """`companies.statement_template` vocabulary → the chart's.

    Insurers used to route to `financial` "until the chart grows a third shape". Chart v1
    grew one (migration `0020`), and it still does not belong here: every `insurance` mapping
    is `ng_ifrs_label`, because the template was built from AIICO's IFRS 17 and pre-IFRS 17
    statements. IFRS 17 "Insurance revenue" is a specific construct - the release of the
    contractual service margin plus expected claims - and not a US health insurer's total
    revenues. Mapping the two onto one key would repeat the `gross_earnings` → `revenue`
    error this chart exists to avoid.

    Routing to the bank chart was doing real damage in the meantime. UnitedHealth's stored
    statements carry no `revenue` row at all: 117 rows each of `gross_earnings` and
    `net_interest_income`, every one NULL, because those are bank keys a health insurer will
    never report. It does file `Revenues`, `OperatingIncomeLoss`, `IncomeTaxExpenseBenefit`,
    `NetIncomeLoss`, `Assets` and `InterestExpense`, all already mapped under `non_financial`
    and `both`, and none of them reachable from the template it was given.

    So a US insurer resolves as a profit and loss account, which is accurate as far as it
    goes and strictly better than two permanently empty bank keys. It does not capture
    medical costs or a loss ratio; that needs a US GAAP insurance template, which v1 does not
    have (`docs/08` §4.1). This changes only what future runs write - the statements already
    stored keep their template until something re-extracts them.
    """
    return {"bank": "financial", "insurance": "non_financial", "both": "both"}.get(
        company_template, "non_financial"
    )


def _primary_security(session: Session, company: Company) -> Security:
    securities = (
        session.execute(
            select(Security).where(Security.company_id == company.id).order_by(Security.id)
        )
        .scalars()
        .all()
    )
    if not securities:
        raise LookupError(f"company {company.id} ({company.legal_name}) has no security")
    return securities[0]


def _upsert_filing(
    session: Session,
    *,
    company_id: int,
    form: str,
    filed: dt.date,
    period_end: dt.date,
    accession: str,
    source_document_id: int,
) -> tuple[Filing, int]:
    row = session.execute(
        select(Filing)
        .where(Filing.company_id == company_id)
        .where(Filing.filing_type == form)
        .where(Filing.period_end == period_end)
        .where(Filing.filing_date == filed)
    ).scalar_one_or_none()
    if row is not None:
        return row, 0
    row = Filing(
        company_id=company_id,
        filing_type=form,
        filing_date=filed,
        period_end=period_end,
        accession_no=accession,
        source_document_id=source_document_id,
        known_as_of=filed,
    )
    session.add(row)
    session.flush()
    return row, 1


_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def _fact_from(cik: str, taxonomy: str, tag: str, unit: str, entry: object) -> XbrlFact | None:
    if not isinstance(entry, dict):
        return None
    end = _parse_date(entry.get("end"))
    filed = _parse_date(entry.get("filed"))
    accession = str(entry.get("accn") or "")
    form = str(entry.get("form") or "")
    if end is None or filed is None or not _ACCESSION.match(accession) or not form:
        return None
    start = _parse_date(entry.get("start"))
    fy = entry.get("fy")
    return XbrlFact(
        cik=cik,
        taxonomy=taxonomy,
        tag=tag,
        unit=unit,
        start=start,
        end=end,
        value=_parse_decimal(entry.get("val")),
        accession_no=accession,
        form=form,
        filed=filed,
        fy=int(fy) if isinstance(fy, int) else None,
        fp=str(entry["fp"]) if entry.get("fp") else None,
        frame=str(entry["frame"]) if entry.get("frame") else None,
    )


def _fact_order(fact: XbrlFact) -> tuple[dt.date, str, str, dt.date, str, str]:
    return (
        fact.filed,
        fact.accession_no,
        fact.tag,
        fact.end,
        fact.start.isoformat() if fact.start else "",
        fact.frame or "",
    )


def _parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_http_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _parse_decimal(value: object) -> Decimal | None:
    """Absent stays absent. XBRL values are numbers; anything else is not a figure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
