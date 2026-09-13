"""Yahoo Finance daily bars, stored as traded. P2.3, the US half of TG1.

🟡 `docs/03` P2.3 rates the source WATCH: "free, fragile, fine for personal US". This is the
v8 chart endpoint `yfinance` reads underneath — undocumented, no contract — called directly
so that the **raw response is what gets stored** and `parse()` is a pure function of it.
When it breaks, or when the owner upgrades to a paid feed, the swap is a connector
(`DATA_FOUNDATION.md` §C; the interface is the contract).

## The one thing that would have been silently wrong

Yahoo's historical prices are **split-adjusted retroactively**: after Apple's 4-for-1 split
of 2020-08-31, the 2020-08-28 close is served as 124.81. The price that traded that day was
499.23. Storing the served number as `close_raw` would violate the column's one rule — AS
TRADED — for every bar before every split, and `docs/08` §2.4 explains at length why that
rule exists: an adjustment you cannot undo cannot be corrected, and an adjustment that
embeds a later corporate action is lookahead.

So the connector reverses the provider's own adjustment: each bar's price is multiplied by
the product of the split ratios whose ex-date falls **after** the bar, and its volume is
divided by the same. The split list comes from the same response, so the arithmetic is a
deterministic function of stored bytes — a re-parse gives the same bars, and a future split
(which rewrites Yahoo's whole history downward) leaves `close_raw` exactly where it was.

Dividends are not reversed: Yahoo's `close` is split-adjusted only; its `adjclose` is the
dividend-adjusted series and is deliberately not stored (`docs/08` §2.4: no adjusted column;
adjustments are computed on read from `adjustment_factors`, TG2). The split and dividend
events themselves stay in the raw document for P3 to turn into `corporate_actions`.

## Vintages

`known_as_of` is in the primary key. A bar seen for the first time is dated the day it
traded — its close was public at the close. A bar seen again with the same figures is the
same vintage and is not written. A bar seen again with different figures — Yahoo does
correct late prints — is a second row, `known_as_of` the day the change was observed.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.models import DataSource, PriceHistory, SecurityIdentifier
from packages.common.timez import utctoday
from packages.ingestion.base import Connector, DataSourceLicence, RawResponse

__all__ = ["PriceBar", "YahooChartConnector", "unadjust"]

_log = structlog.get_logger(__name__)

_BASE = "https://query2.finance.yahoo.com"
SOURCE_NAME = "Yahoo Finance"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) quant_model/0.1 research"

#: US equities trade in cents; four decimals keeps sub-penny prints and drops float noise.
_PRICE_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class PriceBar:
    """One daily bar, as traded."""

    symbol: str
    date: dt.date
    open_raw: Decimal | None
    high_raw: Decimal | None
    low_raw: Decimal | None
    close_raw: Decimal
    volume: int | None
    currency: str | None


@dataclass(frozen=True)
class Split:
    ex_date: dt.date
    ratio: Decimal  # numerator / denominator: 4 for a 4-for-1


class YahooChartConnector(Connector[PriceBar]):
    """`/v8/finance/chart/{symbol}` → `price_history`, one symbol per run."""

    name = "yahoo_chart"
    rate_limit_per_sec = 1.0
    politeness_delay_sec = 1.0

    def __init__(self, *, timeout_sec: float = 60.0) -> None:
        self._timeout = timeout_sec

    def declare_licence(self) -> DataSourceLicence:
        """Matches the reviewed `data_sources` row seeded in migration 0012."""
        return DataSourceLicence(
            source_name=SOURCE_NAME,
            base_url=_BASE,
            licence_type="personal_use_terms",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: Yahoo Finance",
            terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
            terms_reviewed_on=dt.date(2026, 9, 13),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes="See migration 0012. Personal use; redistribution not asserted; US only.",
        )

    def fetch(self, **params: object) -> RawResponse:
        """One symbol's daily bars over a window, with split and dividend events.

        `lookback_days=N` asks for the last N days; nothing asks for the whole history,
        which is what the first load of a symbol wants. Both ends are recorded in the URL.
        """
        symbol = str(params["symbol"]).strip().upper()
        today = utctoday()
        lookback = params.get("lookback_days")
        if lookback is not None:
            start = today - dt.timedelta(days=int(str(lookback)))
            period1 = int(
                dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC).timestamp()
            )
        else:
            period1 = 0
        tomorrow = today + dt.timedelta(days=1)
        period2 = int(
            dt.datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=dt.UTC).timestamp()
        )
        query = {
            "period1": str(period1),
            "period2": str(period2),
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        url = f"{_BASE}/v8/finance/chart/{symbol}"
        response = httpx.get(
            url, params=query, headers={"User-Agent": _USER_AGENT}, timeout=self._timeout
        )
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            url=f"{url}?" + "&".join(f"{k}={v}" for k, v in query.items()),
            http_status=response.status_code,
        )

    def parse(self, raw: RawResponse) -> list[PriceBar]:
        """Pure. Split-adjusted bars in, as-traded bars out; bars with no close are skipped."""
        payload = json.loads(raw.data.decode("utf-8"))
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise ValueError(f"Yahoo chart error: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            return []
        result = results[0]
        meta = result.get("meta") or {}
        symbol = str(meta.get("symbol") or "").upper()
        currency = str(meta["currency"]) if meta.get("currency") else None
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        # Bars are stamped at the exchange's open. The trading date is the exchange's date,
        # not UTC's (TG21) - the two differ for any market east of Greenwich.
        zone = _zone(meta.get("exchangeTimezoneName"))
        splits = _splits_from(result.get("events") or {}, zone)

        bars: list[PriceBar] = []
        for index, stamp in enumerate(timestamps):
            close = _number(quote.get("close"), index)
            if close is None:
                continue  # a holiday placeholder or a gap; there is no bar to store
            date = dt.datetime.fromtimestamp(int(stamp), zone).date()
            factor = unadjust(date, splits)
            volume = _number(quote.get("volume"), index)
            close_raw = (close * factor).quantize(_PRICE_PLACES, rounding=ROUND_HALF_UP)
            bars.append(
                PriceBar(
                    symbol=symbol,
                    date=date,
                    open_raw=_price(_number(quote.get("open"), index), factor),
                    high_raw=_price(_number(quote.get("high"), index), factor),
                    low_raw=_price(_number(quote.get("low"), index), factor),
                    close_raw=close_raw,
                    volume=int((volume / factor).to_integral_value(ROUND_HALF_UP))
                    if volume is not None
                    else None,
                    currency=currency,
                )
            )
        bars.sort(key=lambda bar: bar.date)
        return bars

    def write(self, session: Session, records: list[PriceBar], *, source_document_id: int) -> int:
        """Insert bars the table does not already hold at these figures. Returns rows inserted."""
        if not records:
            return 0
        symbol = records[0].symbol
        security_id = _security_for_ticker(session, symbol)
        data_source_id = session.execute(
            select(DataSource.id).where(DataSource.source_name == SOURCE_NAME)
        ).scalar_one()

        dates = [bar.date for bar in records]
        latest: dict[dt.date, tuple[Decimal | None, ...]] = {}
        rows = session.execute(
            select(
                PriceHistory.date,
                PriceHistory.known_as_of,
                PriceHistory.open_raw,
                PriceHistory.high_raw,
                PriceHistory.low_raw,
                PriceHistory.close_raw,
                PriceHistory.volume,
            )
            .where(PriceHistory.security_id == security_id)
            .where(PriceHistory.date.between(min(dates), max(dates)))
            .order_by(PriceHistory.date, PriceHistory.known_as_of)
        ).all()
        for date, _known, open_, high, low, close, volume in rows:
            latest[date] = (open_, high, low, close, volume)  # ordered: last one wins

        today = utctoday()
        to_insert = []
        unchanged = 0
        for bar in records:
            figures = (bar.open_raw, bar.high_raw, bar.low_raw, bar.close_raw, bar.volume)
            stored = latest.get(bar.date)
            if stored is not None and _same(stored, figures):
                unchanged += 1
                continue
            to_insert.append(
                {
                    "security_id": security_id,
                    "date": bar.date,
                    # First sight: the day it traded. A changed bar: the day we saw it change.
                    "known_as_of": bar.date if stored is None else today,
                    "open_raw": bar.open_raw,
                    "high_raw": bar.high_raw,
                    "low_raw": bar.low_raw,
                    "close_raw": bar.close_raw,
                    "volume": bar.volume,
                    "vwap": None,
                    "halted": False,
                    "data_source_id": data_source_id,
                    "source_document_id": source_document_id,
                }
            )
        if unchanged:
            _log.info("unchanged_bars_skipped", symbol=symbol, count=unchanged)
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
        return inserted


def unadjust(date: dt.date, splits: list[Split]) -> Decimal:
    """The factor that turns a split-adjusted figure on `date` back into what traded.

    The product of the ratios of every split whose ex-date is after the bar's date. A bar
    on the ex-date itself is already in post-split terms and is left alone.
    """
    factor = Decimal(1)
    for split in splits:
        if split.ex_date > date:
            factor *= split.ratio
    return factor


def _zone(name: object) -> dt.tzinfo:
    try:
        return ZoneInfo(str(name)) if name else dt.UTC
    except (KeyError, ValueError):
        return dt.UTC


def _splits_from(events: dict[str, object], zone: dt.tzinfo) -> list[Split]:
    splits: list[Split] = []
    raw = events.get("splits") or {}
    if not isinstance(raw, dict):
        return splits
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        try:
            numerator = Decimal(str(entry["numerator"]))
            denominator = Decimal(str(entry["denominator"]))
            stamp = int(entry["date"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        if numerator <= 0 or denominator <= 0:
            continue
        splits.append(
            Split(
                ex_date=dt.datetime.fromtimestamp(stamp, zone).date(),
                ratio=numerator / denominator,
            )
        )
    return splits


def _number(series: object, index: int) -> Decimal | None:
    if not isinstance(series, list) or index >= len(series):
        return None
    value = series[index]
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _price(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return (value * factor).quantize(_PRICE_PLACES, rounding=ROUND_HALF_UP)


def _same(stored: tuple[Decimal | None, ...], figures: tuple[object, ...]) -> bool:
    for a, b in zip(stored, figures, strict=True):
        if a is None and b is None:
            continue
        if a is None or b is None or Decimal(str(a)) != Decimal(str(b)):
            return False
    return True


def _security_for_ticker(session: Session, symbol: str) -> int:
    row = session.execute(
        select(SecurityIdentifier.security_id)
        .where(SecurityIdentifier.id_type == "ticker")
        .where(SecurityIdentifier.id_value == symbol)
        .where(SecurityIdentifier.valid_to.is_(None))
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(
            f"no current security carries ticker {symbol!r}. Register the company first "
            "(scripts/ingest_edgar.py): prices attach to a security, never to a ticker string."
        )
    return row
