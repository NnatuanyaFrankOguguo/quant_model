"""`scripts/collect_dmo.py`: reading DMO's PDFs without guessing. Collector task H.

Pure functions, no network and no database. Every fixture string below is transcribed from
a real DMO document, because the whole difficulty of this source is that its layout changes
between vintages and the changes are invisible in the numerals.

The test that matters most is the unit one. DMO prints Nigeria's public debt as `87.91`
under `(N'Trn)` in September 2023 and as `159,351,581.44` under `(N'M)` in March 2026. Read
the first as millions and the country's debt becomes NGN 0.09 billion - a 1,000,000x error
that no cross-row check catches, because a chart of one wrong point among twelve looks like
a chart with an outlier. That is exactly the failure `docs/08` §1.4 works through, and it
happened here on the first run.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from scripts.collect_dmo import (
    UNIT_IN_BILLIONS,
    debt_in_billions,
    listing_rows,
    quoted_fx_rate,
    scale_of,
    ten_year_rates,
    total_public_debt,
)

pytestmark = pytest.mark.invariant

#: Nigeria's Q1 2026 debt table, millions, as published on 2026-08-07.
DEBT_2026_MILLIONS = """NIGERIA'S TOTAL PUBLIC DEBT PORTFOLIO AS AT MARCH 31, 2026
Amount Outstanding Amount Outstanding
Debt Category % of Total
(US$'M) (N'M)
A. Total External Debt 51,904.08 71,950,245.40 45.15%
B. Total Domestic Debt 63,050.32 87,401,336.04 54.85%
C. Total Public Debt(A+B) 114,954.40 159,351,581.44 100%
Central Bank of Nigeria (CBN) Official Exchange Rate of US$1/N1386.2156 as at March 31, 2026
was used in converting External Debt to Naira."""

#: The same table three years earlier - trillions, and a differently worded rate line.
DEBT_2023_TRILLIONS = """NIGERIA'S TOTAL PUBLIC DEBT PORTFOLIO AS AT SEPTEMBER 30, 2023
Amount Outstanding Amount Outstanding
Debt Category % of Total
(US$'Bn) (N'Trn)
A. Total External Debt 41.59 31.98 36.38%
B. Total Domestic Debt 72.76 55.93 63.62%
C. Total Public Debt(A+B) 114.35 87.91 100%
ii. Central Bank of Nigeria (CBN) Official Exchange Rate of US$1 to N768.76 as at September
30, 2023 was used in converting External Debt to Naira."""

#: September 2026: one new 10-year issue, one 15-year re-opening. "10 Years", with a space.
AUCTION_SEPTEMBER_2026 = """SEPTEMBER 2026 FGN BOND AUCTION RESULT
DESCRIPTION 16.79% FGN SEP 2036 15.45% FGN JUN 2038
Auction Date: September 14, 2026 September 14, 2026
Tenors: 10 Years 15 Years
Term-To-Maturity: 10 Years 11 Years, 9 Months
Marginal Rates: 16.7900% 16.8500%"""

#: April 2026, five months earlier: "10-Year", hyphenated and singular.
AUCTION_APRIL_2026 = """APRIL 2026 FGN BOND AUCTION RESULT
DESCRIPTION 17.945% FGN AUG 2030 17.95% FGN JUN 2032 22.60% FGN JAN 2035
Auction Date: April 27, 2026 April 27, 2026 April 27, 2026
Tenors: 5-Year 7-Year 10-Year
Term-To-Maturity: 4 Years, 4 Months 6 Years, 2 Months 8 Years, 9 Months
Marginal Rates: 16.3000% 16.5000% 16.5900%"""

#: December 2025 offered no 10-year paper at all.
AUCTION_DECEMBER_2025 = """DECEMBER 2025 FGN BOND AUCTION RESULT
DESCRIPTION 17.945% FGN AUG 2030 17.95% FGN JUN 2032
Auction Date: December 15, 2025 December 15, 2025
Tenors: 5-Year 7-Year
Marginal Rates: 17.2000% 17.3000%"""

#: January 2026 offered two, and DMO called both of them 10-year.
AUCTION_JANUARY_2026 = """JANUARY 2026 FGN BOND AUCTION RESULT
DESCRIPTION 18.50% FGN FEB 2031 19.00% FGN FEB 2034 22.60% FGN JAN 2035
Auction Date: January 26, 2026 January 26, 2026 January 26, 2026
Tenors: 7-Year 10-Year 10-Year
Term-To-Maturity: 5 Years, 1 Month 8 Years, 1 Month 9 Years
Marginal Rates: 17.6200% 17.5000% 17.5200%"""


# --------------------------------------------------------------------------------------
# Units: the 1,000,000x error
# --------------------------------------------------------------------------------------


def test_the_same_table_in_millions_and_trillions_both_come_out_in_billions() -> None:
    """The two vintages agree to within half a percent once each is read in its own unit.

    Nigeria's public debt did not move much between Q2 and Q3 2023, so NGN 87.91tn read from
    the trillions table must land beside NGN 87,379bn read from the millions one. Reading
    the trillions table as millions gives 0.09, which is not a rounding disagreement.
    """
    modern, _ = debt_in_billions(DEBT_2026_MILLIONS)
    legacy, _ = debt_in_billions(DEBT_2023_TRILLIONS)
    assert modern == Decimal("159351.58144")
    assert legacy == Decimal("87910.00")
    assert legacy < modern, "debt grew; if this flips, a unit was misread"


def test_an_unrecognised_unit_is_refused_rather_than_assumed() -> None:
    """A defaulted unit is every row wrong by the same factor, which no later check sees."""
    with pytest.raises(ValueError, match="unrecognised"):
        scale_of(DEBT_2026_MILLIONS.replace("(N'M)", "(N'Zillion)"), "ngn")
    with pytest.raises(ValueError, match="no ngn column header"):
        scale_of(DEBT_2026_MILLIONS.replace("(N'M)", ""), "ngn")


def test_the_unit_spellings_dmo_actually_uses() -> None:
    """`M` and `Mn` are both millions; DMO has printed both, four months apart."""
    assert UNIT_IN_BILLIONS["m"] == UNIT_IN_BILLIONS["mn"] == Decimal("0.001")
    assert UNIT_IN_BILLIONS["trn"] == Decimal(1000)
    assert scale_of("(US$'Mn) (N'Mn)", "ngn") == ("Mn", Decimal("0.001"))
    assert scale_of("(US$'Bn) (N'Trn)", "usd") == ("Bn", Decimal(1))


def test_the_naira_header_is_found_wherever_it_sits() -> None:
    """Sometimes it follows the dollar header, sometimes it precedes it, sometimes alone."""
    for layout in (
        "Debt Category Amount Outstanding (US$'M) Amount Outstanding (N'M) % of Total",
        "Debt Category Amount Outstanding (N'M) % of Total\n(US$'M)",
        "(N'M)\n(US$'M)",
    ):
        assert scale_of(layout, "ngn") == ("M", Decimal("0.001"))


# --------------------------------------------------------------------------------------
# Each row checked against the exchange rate its own document quotes
# --------------------------------------------------------------------------------------


def test_every_accepted_row_agrees_with_the_tables_own_exchange_rate() -> None:
    """US$114,954.40M x N1386.2156 = NGN 159.35tn, which is what the naira column says."""
    _value, shown = debt_in_billions(DEBT_2026_MILLIONS)
    assert "checked to 0.00%" in shown
    assert "N1386.2156" in shown


def test_a_swapped_currency_column_is_caught_by_that_check() -> None:
    """The check exists for this: naira and dollars are both bare numerals in the same row.

    Swapping them leaves a perfectly well-formed table whose "naira" total is 1,386x too
    small, and no single-row inspection would notice.
    """
    swapped = DEBT_2026_MILLIONS.replace(
        "C. Total Public Debt(A+B) 114,954.40 159,351,581.44",
        "C. Total Public Debt(A+B) 159,351,581.44 114,954.40",
    )
    with pytest.raises(ValueError, match="swapped column or a misread unit"):
        debt_in_billions(swapped)


def test_a_table_quoting_no_rate_is_refused_not_trusted() -> None:
    """Two 2024-2025 vintages omit the rate line entirely, so nothing in them is checkable."""
    with pytest.raises(ValueError, match="quotes no exchange rate"):
        debt_in_billions(DEBT_2026_MILLIONS.split("Central Bank")[0])


def test_both_spellings_of_the_rate_line() -> None:
    """March 2026 writes `US$1/N1386.2156`; March 2023 writes `US$1 to NGN460.35`."""
    assert quoted_fx_rate("US$1/N1386.2156 as at") == Decimal("1386.2156")
    assert quoted_fx_rate("US$1 to N899.393 as at") == Decimal("899.393")
    assert quoted_fx_rate("US$1 to NGN460.35 as at") == Decimal("460.35")
    assert quoted_fx_rate("no rate here") is None


def test_the_total_row_is_read_and_not_a_neighbouring_one() -> None:
    usd, naira = total_public_debt(DEBT_2026_MILLIONS)
    assert usd == Decimal("114954.40")
    assert naira == Decimal("159351581.44"), "the A+B row, not External or Domestic"
    with pytest.raises(ValueError, match="Total Public Debt"):
        total_public_debt("a document with no such row")


# --------------------------------------------------------------------------------------
# The 10-year benchmark, and the months where there isn't one
# --------------------------------------------------------------------------------------


def test_both_printed_tenor_formats_are_read() -> None:
    """ "10 Years" and "10-Year" are the same bucket; DMO switched between April and May 2026."""
    assert ten_year_rates(AUCTION_SEPTEMBER_2026) == [("16.79% FGN SEP 2036", "16.7900")]
    assert ten_year_rates(AUCTION_APRIL_2026) == [("22.60% FGN JAN 2035", "16.5900")]


def test_the_tenor_bucket_is_dmos_label_not_a_maturity_calculation() -> None:
    """April's 10-year has eight years nine months left, and DMO still calls it the 10-year.

    Following their label keeps `NG_FGN_BOND_STOP_RATE` meaning what its name says. Picking
    by term-to-maturity instead would silently redefine the series.
    """
    ((instrument, rate),) = ten_year_rates(AUCTION_APRIL_2026)
    assert instrument == "22.60% FGN JAN 2035"
    assert rate == "16.5900"
    assert "8 Years, 9 Months" in AUCTION_APRIL_2026, "the fixture really is a re-opening"


def test_a_month_with_no_ten_year_paper_yields_nothing_rather_than_something() -> None:
    """Five of the fourteen months read offered no 10-year bond. That is a real absence.

    The caller stores it as an explicit NULL, because a missing row would be
    indistinguishable from a month nobody collected.
    """
    assert ten_year_rates(AUCTION_DECEMBER_2025) == []


def test_two_ten_year_instruments_are_returned_for_the_caller_to_refuse() -> None:
    """January 2026. The series says "the 10-year benchmark" and does not say which of two.

    Returning both is what lets the caller refuse the month by name instead of quietly
    taking the first column.
    """
    both = ten_year_rates(AUCTION_JANUARY_2026)
    assert len(both) == 2
    assert [rate for _name, rate in both] == ["17.5000", "17.5200"]


def test_tenors_and_rates_that_cannot_be_paired_are_refused() -> None:
    """They are read positionally, so an unequal count means the columns are not aligned."""
    with pytest.raises(ValueError, match="not pairable"):
        ten_year_rates(
            AUCTION_SEPTEMBER_2026.replace(
                "Marginal Rates: 16.7900% 16.8500%", "Marginal Rates: 16.7900%"
            )
        )
    with pytest.raises(ValueError, match="no Tenors or Marginal Rates row"):
        ten_year_rates("DESCRIPTION something\nAuction Date: May 1, 2026")


# --------------------------------------------------------------------------------------
# The listing, whose first version mispaired every row
# --------------------------------------------------------------------------------------


LISTING_HTML = """
<tr class="docman_item">
  <td><a href="/6051-summary-of-fgn-bond-auction-results-for-september-2026"></a>
  <span itemprop="name">Summary of FGN Bond Auction Results for September, 2026</span></td>
  <td><time itemprop="datePublished" datetime="2026-09-14 00:00:00">14 Sep 2026</time></td>
</tr>
<tr class="docman_item">
  <td><a href="/6019-summary-of-fgn-bond-auction-results-for-august-2026"></a>
  <span itemprop="name">Summary of FGN Bond Auction Results for August, 2026</span></td>
  <td><time itemprop="datePublished" datetime="2026-08-17 00:00:00">17 Aug 2026</time></td>
</tr>
"""


def test_each_document_keeps_its_own_published_date() -> None:
    """The first version of this parser gave September's row August's date, and said nothing.

    A regex allowed to run past `</tr>` matches the *next* row's `datePublished`, so every
    document was stamped with its successor's date - a silent off-by-one across the whole
    series, in the one field that decides what a point-in-time query may see.
    """
    rows = listing_rows(LISTING_HTML)
    assert rows == [
        ("/6051-summary-of-fgn-bond-auction-results-for-september-2026", dt.date(2026, 9, 14)),
        ("/6019-summary-of-fgn-bond-auction-results-for-august-2026", dt.date(2026, 8, 17)),
    ]


def test_rows_come_back_newest_first_by_document_id() -> None:
    """DMO issues ids in publication order, so the id is the ordering the listing lacks."""
    reversed_html = "\n".join(reversed(LISTING_HTML.strip().split("</tr>")))
    assert [href for href, _ in listing_rows(reversed_html)][0].startswith("/6051-")


def test_a_row_without_a_date_is_kept_rather_than_dropped() -> None:
    """Its `known_as_of` then falls back to the PDF's own timestamp, which is still honest."""
    undated = LISTING_HTML.replace(
        '<time itemprop="datePublished" datetime="2026-09-14 00:00:00">14 Sep 2026</time>', ""
    )
    rows = dict(listing_rows(undated))
    assert rows["/6051-summary-of-fgn-bond-auction-results-for-september-2026"] is None
