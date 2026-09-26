"""Collect DMO figures for Collector task H and write a reviewable CSV. One-off, not a connector.

`TEAM_BRIEF` §2.2-H names four things in the monthly macro download: NBS CPI, the CBN MPR,
FX, and **DMO auction results**. The first three have automated connectors. DMO has none -
`DATA_FOUNDATION` T13 leaves it to the manual CSV path until a scraper exists - and the two
DMO series declared in migration `0005` had never received a single observation:

* `NG_FGN_BOND_STOP_RATE` - "FGN bond auction stop rate (10-year benchmark)", monthly, percent
* `NG_PUBLIC_DEBT_TOTAL`  - "Nigeria total public debt stock", quarterly, ngn_billions

This reads DMO's published PDFs and emits the CSV that `scripts/ingest_csv.py` takes. It
stays a script rather than becoming a connector because the roadmap has not reached T13, and
a connector nobody scheduled is worse than a script somebody ran.

## Three things DMO does that make guessing dangerous

**The naira column changes unit between vintages.** September 2023 prints trillions under
`(N'Trn)`; March 2026 prints millions under `(N'M)`; March 2025 writes millions `(N'Mn)`.
All three print a bare numeral - `87.91`, `159,351,581.44` - and nothing in the digits says
which. Reading the first as millions makes Nigeria's public debt NGN 0.09 billion, a
1,000,000x error, and it is the exact failure `docs/08` §1.4 works through. The unit is read
from the header, and an unrecognised one is refused.

**The header moves.** Sometimes both units sit adjacent on one line, sometimes the naira
header precedes the dollar one, sometimes each is alone on its own line. So the naira token
is found on its own rather than by its position relative to the dollar token.

**Every table states its own exchange rate**, which makes each row checkable against the
document that carries it: the naira total must equal the dollar total times the quoted rate.
That check is what would catch a swapped column, and it is applied to every row before the
row is allowed out.

The auction format moved too: "10-Year" became "10 Years" between April and May 2026.

## What is refused rather than defaulted

A month whose auction offered no 10-year paper gets an explicit empty value - the CSV
contract's "genuine no observation" - because a gap would be indistinguishable from a month
nobody collected. A month offering *two* instruments DMO both labels 10-year is refused: the
series says "the 10-year benchmark" and does not say which, and choosing would invent a rule.

`known_as_of` is DMO's own `datePublished` from the listing row, or the PDF's creation
timestamp where that is later. Taking the later of two honest signals can only be
conservative; claiming the earlier date is the lookahead that makes a P7 backtest profitable
and wrong.

    .venv\\Scripts\\python.exe scripts\\collect_dmo.py [months] [out.csv]
    .venv\\Scripts\\python.exe scripts\\ingest_csv.py --source DMO --path out.csv

Read the printed table before ingesting. `ingest_csv.py` rejects the whole file if any row
is malformed, so a refusal there costs nothing; a plausible wrong number costs everything.

## Open, as of the 2026-09-17 collection (25 rows ingested, 6 of them explicit NULLs)

**January 2026 has no stop rate**, and cannot get one from this script. DMO labelled two
instruments 10-year that month - 19.00% FGN FEB 2034 at 17.5000% and 22.60% FGN JAN 2035 at
17.5200% - and `NG_FGN_BOND_STOP_RATE` says only "the 10-year benchmark". Closing this means
deciding what the series means when there are two, and writing that rule into the series
description rather than into this file. Nearest-to-ten-years-remaining would pick JAN 2035;
so would "the longer bond"; nothing in the documents says either.

**Q4 2024 and Q1 2025 public debt are not ingested.** Those two DMO tables state no exchange
rate, so the naira column cannot be checked against anything inside the document, and every
other quarter's is. They can be added by hand if someone is willing to accept the header's
word alone - the figures are NGN 144,665.45bn and NGN 149,389.00bn - but that is a decision
about evidence, not a parsing problem.

**The Q1-to-Q2 2023 jump is real, not an error.** Total public debt goes from NGN 49,853.69bn
to NGN 87,379.40bn in one quarter, +75%. Both rows verify against their own tables'
exchange rates, so the figures are as DMO published them. The cause is widely reported to be
the securitisation of CBN Ways and Means advances, which is **not** confirmed from a DMO
document here and should be before anything in the product explains the step to a reader.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
import pathlib
import re
import sys
import time
import urllib.request
from decimal import Decimal

# `pdfplumber` is imported inside `document()`, not here. It lives in the `data` extra
# (`pyproject.toml`), which CI does not install, and every parser below this line is a pure
# string function that never touches it. A module-level import would make `pytest tests/unit`
# fail in CI over a dependency the tests do not use.

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
BASE = "https://www.dmo.gov.ng"
CACHE = pathlib.Path(os.path.expanduser("~/dmo_cache"))
CACHE.mkdir(exist_ok=True)

MONTH_NAMES = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)
MONTHS = {name: number for number, name in enumerate(MONTH_NAMES, start=1)}

#: Printed unit -> how many billions one unit is. `Mn` and `M` both mean millions; DMO has
#: used both. The apostrophe is sometimes U+2019, so it is normalised away before lookup.
UNIT_IN_BILLIONS = {
    "m": Decimal("0.001"),
    "mn": Decimal("0.001"),
    "bn": Decimal(1),
    "b": Decimal(1),
    "trn": Decimal(1000),
    "tn": Decimal(1000),
}

#: How far the naira total may sit from dollars x the table's own rate before the row is
#: refused. The dollar and naira columns are each rounded independently, and the states'
#: sub-totals are as-at earlier dates in some vintages, so a fraction of a percent of drift
#: is normal. A swapped column or a misread unit is out by 1000x, not by 1%.
FX_TOLERANCE = Decimal("0.01")


def get(url: str) -> bytes:
    key = CACHE / (re.sub(r"[^0-9a-zA-Z]+", "_", url)[-80:] + ".bin")
    if key.exists():
        return key.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed host
        body = response.read()
    key.write_bytes(body)
    time.sleep(1.0)  # someone else's server
    return body


def listing(page: str) -> list[tuple[str, dt.date | None]]:
    """Fetch one DMO index page and return its document rows."""
    return listing_rows(get(f"{BASE}/{page}").decode("utf-8", "replace"))


def listing_rows(html: str) -> list[tuple[str, dt.date | None]]:
    """(href, datePublished) per document row, newest first.

    Split on `<tr` first. A regex allowed to run past `</tr>` matches the *next* row's
    `datePublished`, which stamps every document with its successor's date - a silent
    off-by-one across the whole series, in the one field that decides what a point-in-time
    query is allowed to see. The first version of this function did exactly that.
    """
    rows: list[tuple[int, str, dt.date | None]] = []
    for block in re.split(r"<tr\b", html):
        href = re.search(r'href="/(\d{3,5})-([^"]*?)"', block)
        if not href or href.group(2).endswith("/file"):
            continue
        stamp = re.search(r'itemprop="datePublished"\s+datetime="(\d{4})-(\d{2})-(\d{2})', block)
        published = dt.date(int(stamp[1]), int(stamp[2]), int(stamp[3])) if stamp else None
        # The document id doubles as the sort key: DMO issues them in publication order.
        rows.append((int(href.group(1)), f"/{href.group(1)}-{href.group(2)}", published))
    rows.sort(key=lambda row: row[0], reverse=True)
    return [(href, published) for _id, href, published in rows]


def document(href: str) -> tuple[str, dt.date | None, str]:
    body = get(f"{BASE}{href}/file")
    digest = hashlib.sha256(body).hexdigest()
    import pdfplumber  # noqa: PLC0415 - see the note where the other imports are

    scratch = CACHE / f"~{digest[:12]}.pdf"
    scratch.write_bytes(body)
    with pdfplumber.open(scratch) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        raw = (pdf.metadata or {}).get("CreationDate") or ""
    scratch.unlink(missing_ok=True)
    made = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    created = dt.date(int(made[1]), int(made[2]), int(made[3])) if made else None
    return text, created, digest


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)


def scale_of(text: str, currency: str) -> tuple[str, Decimal]:
    """The printed unit of one currency column, and its value in billions.

    Raises rather than defaulting, because a defaulted unit is every row in the series wrong
    by the same factor - which no cross-row sanity check can see.
    """
    # The unit token is captured generously and rejected on lookup, so that an unfamiliar
    # spelling reports itself by name. Matching only the units already known would make a
    # new one indistinguishable from a missing header, and send the next collector looking
    # for the wrong problem.
    pattern = (
        r"\(\s*US\$\s*[’']?\s*([A-Za-z]{1,10})\s*\)"
        if currency == "usd"
        else (r"\(\s*N\s*[’']?\s*([A-Za-z]{1,10})\s*\)")
    )
    found = re.search(pattern, text)
    if not found:
        raise ValueError(f"no {currency} column header: cannot tell millions from trillions")
    printed = found.group(1)
    factor = UNIT_IN_BILLIONS.get(printed.lower())
    if factor is None:
        raise ValueError(f"unrecognised {currency} unit {printed!r}: refusing to guess magnitude")
    return printed, factor


def quoted_fx_rate(text: str) -> Decimal | None:
    """The CBN rate the table says it used, e.g. "US$1/N1386.2156" or "US$1 to N899.393"."""
    # March 2023 writes "NGN460.35" where March 2026 writes "N1386.2156".
    found = re.search(r"US\$\s*1\s*(?:/|to)\s*N(?:GN)?\s*([\d,]+\.?\d*)", text)
    return Decimal(found.group(1).replace(",", "")) if found else None


def total_public_debt(text: str) -> tuple[Decimal, Decimal]:
    """(usd, naira) from the "Total Public Debt(A+B)" row, as printed."""
    row = re.search(
        r"Total Public Debt\s*\(?\s*A\s*\+\s*B\s*\)?\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)", text
    )
    if not row:
        raise ValueError("could not read the Total Public Debt (A+B) row")
    return Decimal(row.group(1).replace(",", "")), Decimal(row.group(2).replace(",", ""))


def debt_in_billions(text: str) -> tuple[Decimal, str]:
    """Total public debt in NGN billions, checked against the table's own exchange rate."""
    usd_printed, usd_factor = scale_of(text, "usd")
    ngn_printed, ngn_factor = scale_of(text, "ngn")
    usd, naira = total_public_debt(text)
    billions = naira * ngn_factor

    rate = quoted_fx_rate(text)
    if rate is None:
        raise ValueError("the table quotes no exchange rate, so its naira column is uncheckable")
    implied = usd * usd_factor * rate
    if implied == 0:
        raise ValueError("implied naira total is zero")
    drift = abs(billions - implied) / implied
    if drift > FX_TOLERANCE:
        raise ValueError(
            f"naira total {billions:,.2f}bn disagrees with US${usd:,.2f}{usd_printed} x "
            f"N{rate} = {implied:,.2f}bn by {drift:.1%} - a swapped column or a misread unit"
        )
    return billions, f"{naira:,.2f} N'{ngn_printed} (checked to {drift:.2%} on N{rate})"


def ten_year_rates(text: str) -> list[tuple[str, str]]:
    """(instrument, marginal rate) for every column DMO labels a 10-year tenor."""
    tenors = re.search(r"^Tenors?:\s*(.+)$", text, re.M)
    rates = re.search(r"^Marginal Rates?:\s*(.+)$", text, re.M)
    names = re.search(r"^DESCRIPTION\s+(.+)$", text, re.M)
    if not (tenors and rates):
        raise ValueError("no Tenors or Marginal Rates row")
    # DMO changed format between April and May 2026: "10-Year" became "10 Years".
    tenor_list = re.findall(r"(\d+)\s*-?\s*Years?", tenors.group(1))
    rate_list = re.findall(r"(\d+\.\d+)\s*%", rates.group(1))
    if len(tenor_list) != len(rate_list):
        raise ValueError(f"{len(tenor_list)} tenors against {len(rate_list)} rates: not pairable")
    instruments = re.findall(r"(\d+\.?\d*%\s*FGN\s+\w+\s+\d{4})", names.group(1) if names else "")
    instruments += ["?"] * (len(tenor_list) - len(instruments))
    return [(instruments[i], rate_list[i]) for i, tenor in enumerate(tenor_list) if tenor == "10"]


def main() -> int:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("dmo_task_h.csv")
    rows: list[dict[str, str]] = []
    refused: list[str] = []

    def record(series: str, as_of: dt.date, known: dt.date, value: str) -> None:
        rows.append(
            {
                "series_code": series,
                "as_of_date": as_of.isoformat(),
                "known_as_of": known.isoformat(),
                "value": value,
            }
        )

    print("NG_FGN_BOND_STOP_RATE  -  10-year benchmark, percent")
    print("-" * 108)
    print(f"{'as_of':11} {'known':11} {'value':>9}  {'pub':11} {'pdf':11} instrument / note")
    seen: set[dt.date] = set()
    for href, published in listing("fgn-bonds/auction"):
        if len(seen) >= want:
            break
        if not re.search(r"auction-result", href, re.I):
            continue
        text, created, digest = document(href)
        head = re.search(r"^([A-Z]+)\s+(\d{4})\s+FGN BOND AUCTION RESULT", text, re.M)
        if not head:
            refused.append(f"{href}: the PDF title names no month")
            continue
        month = month_end(int(head.group(2)), MONTHS[head.group(1)])
        if month in seen:  # DMO listed the September 2026 result twice, byte-identical
            continue
        seen.add(month)
        # `as_of_date` is the auction date, not the month end.
        #
        # `ingest_csv.py` refused the month-end version outright: "known_as_of (2025-08-26)
        # precedes as_of_date (2025-08-31). A figure cannot be published before the period it
        # describes." It was right, and dating an auction to the month end was the error. A
        # CPI figure describes a whole month and cannot exist until the month ends; an
        # auction is a point event that describes one day, and the rate struck on 14
        # September is knowable that afternoon. The series stays monthly in cadence -
        # roughly one auction a month - which is what `frequency` records.
        struck = re.search(r"^Auction Date:\s*([A-Z][a-z]+)\s+(\d+),\s*(\d{4})", text, re.M)
        if not struck:
            refused.append(f"{month} ({href}): the PDF states no auction date")
            print(f"{month} {'?':11} {'REFUSED':>9}  {published} {created} no auction date")
            continue
        as_of = dt.date(int(struck.group(3)), MONTHS[struck.group(1).upper()], int(struck.group(2)))
        known = max([d for d in (published, created, as_of) if d])
        try:
            tens = ten_year_rates(text)
        except ValueError as exc:
            refused.append(f"{as_of} ({href}): {exc}")
            print(f"{as_of} {known} {'REFUSED':>9}  {published} {created} {exc}")
            continue
        if len(tens) > 1:
            detail = ", ".join(f"{name} at {rate}%" for name, rate in tens)
            refused.append(
                f"{as_of}: DMO labels {len(tens)} instruments 10-year ({detail}). The series "
                f'says "the 10-year benchmark" and does not say which. Needs a stated rule.'
            )
            print(f"{as_of} {known} {'REFUSED':>9}  {published} {created} {len(tens)} 10Y columns")
            continue
        value = tens[0][1] if tens else ""
        note = tens[0][0] if tens else "no 10-year paper offered -> explicit NULL"
        record("NG_FGN_BOND_STOP_RATE", as_of, known, value)
        print(f"{as_of} {known} {value or 'NULL':>9}  {published} {created} {note}")

    print()
    print("NG_PUBLIC_DEBT_TOTAL  -  ngn_billions, each row checked against the table's own rate")
    print("-" * 108)
    print(f"{'as_of':11} {'known':11} {'value':>13}  {'pub':11} {'pdf':11} as printed")
    quarters = 0
    for href, published in listing("debt-profile/total-public-debt"):
        if quarters >= want:
            break
        if not re.search(r"public-debt", href, re.I):
            continue
        text, created, digest = document(href)
        head = re.search(r"AS AT\s+([A-Z]+)\s+(\d+),\s*(\d{4})", text, re.I)
        if not head:
            refused.append(f"{href}: no as-at date in the PDF heading")
            continue
        quarters += 1
        as_of = dt.date(int(head.group(3)), MONTHS[head.group(1).upper()], int(head.group(2)))
        known = max([d for d in (published, created) if d] or [as_of])
        try:
            billions, shown = debt_in_billions(text)
        except ValueError as exc:
            refused.append(f"{as_of} ({href}): {exc}")
            print(f"{as_of} {known} {'REFUSED':>13}  {published} {created} {exc}")
            continue
        record("NG_PUBLIC_DEBT_TOTAL", as_of, known, f"{billions:.2f}")
        print(f"{as_of} {known} {billions:>13,.2f}  {published} {created} {shown}")

    rows.sort(key=lambda row: (row["series_code"], row["as_of_date"]))
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["series_code", "as_of_date", "known_as_of", "value"]
        )
        writer.writeheader()
        writer.writerows(rows)

    nulls = sum(1 for row in rows if not row["value"])
    print()
    print(f"wrote {len(rows)} rows to {out}  ({nulls} explicit NULLs)")
    if refused:
        print()
        print("REFUSED - each of these needs a decision, not a default:")
        for line in refused:
            print(f"  * {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
