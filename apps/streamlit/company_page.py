"""Screen A for a US company: statements, ratios and a DCF on your assumptions. P2.

    .venv\\Scripts\\python.exe -m streamlit run apps\\streamlit\\company_page.py

A thin client, like the macro dashboard: it calls the API and shows what comes back. No
SQL, no arithmetic. The ratios and the DCF are computed by the server from the figures it
holds; this page's only job is to show them with their provenance and to send your
assumptions along.

Every figure on this page carries the filing that made it public and the date it did so.
The point-in-time control ("as known on") is the honest one: with it set, restatements
filed after that date are unseen, which is what a decision-maker on that date actually had.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.environ.get("QUANT_API_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("QUANT_API_TOKEN", "")
TIMEOUT = 30.0

#: Display order for the statements table. Every key the chart has, grouped as printed.
STATEMENT_ROWS: dict[str, tuple[str, ...]] = {
    "Income statement": (
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "rd_expense",
        "operating_profit",
        "interest_expense",
        "income_tax",
        "profit_after_tax",
        "gross_earnings",
        "net_interest_income",
        "fx_loss_net",
    ),
    "Balance sheet": (
        "total_assets",
        "current_assets",
        "cash",
        "total_liabilities",
        "current_liabilities",
        "long_term_debt",
        "total_equity",
    ),
    "Cash flow": (
        "cash_from_ops",
        "capex",
        "depreciation_amortisation",
        "dividends_paid",
        "buybacks",
    ),
}

RATIO_GROUPS: dict[str, tuple[str, ...]] = {
    "Profitability": ("gross_margin", "operating_margin", "net_margin", "fcf_margin"),
    "Returns": ("roe", "roa"),
    "Balance sheet": (
        "current_ratio",
        "debt_to_equity",
        "liabilities_to_assets",
        "interest_coverage",
    ),
    "Per share": ("eps", "book_value_per_share", "fcf_per_share"),
    "Multiples": (
        "pe",
        "pb",
        "ps",
        "ev_sales",
        "ev_ebitda",
        "earnings_yield",
        "fcf_yield",
        "dividend_yield",
    ),
}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(f"{API_BASE}{path}", params=params, headers=_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def fetch_companies() -> dict[str, Any]:
    return _get("/v1/public/companies")


@st.cache_data(ttl=60)
def fetch_statements(ticker: str, as_known_on: str, period_type: str) -> dict[str, Any]:
    return _get(
        f"/v1/public/companies/{ticker}/statements",
        {"as_known_on": as_known_on, "period_type": period_type},
    )


@st.cache_data(ttl=60)
def fetch_ratios(ticker: str, as_known_on: str, period: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"as_known_on": as_known_on}
    if period:
        params["period"] = period
    return _get(f"/v1/public/companies/{ticker}/ratios", params)


def fetch_dcf(ticker: str, params: dict[str, Any]) -> dict[str, Any]:
    return _get(f"/v1/public/companies/{ticker}/dcf", params)


#: What each kind of blank says. The company's silence and our missing mapping are
#: different answers to "why is this empty?", and the screen must not blame the company
#: for the second (docs/05 §11, Q21).
BLANKS: dict[str | None, str] = {
    "not_in_filing": "—  not reported in the filing",
    "no_mapping": "—  no XBRL tag mapped for this key yet",
    None: "—",
}


def _millions(value: str | None) -> str:
    """Display only. The API's Decimal string becomes a millions figure, or a visible blank."""
    if value is None:
        return BLANKS[None]
    return f"{Decimal(value) / Decimal(1_000_000):,.0f}"


def _cell(figure: dict[str, Any] | None) -> str:
    """One statement cell: the figure in millions, or the reason there is none.

    A restated figure carries a mark; the list under the tables says from what and when.
    """
    if figure is None:
        return "—  not in this period's statement"
    if figure["value"] is None:
        return BLANKS[figure.get("absent_because")]
    mark = "  ↻" if figure.get("restated") else ""
    return _millions(figure["value"]) + mark


def _restatements(periods: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Every restated cell in view: what it was, when that was public, what it is now."""
    rows = []
    for p in periods:
        for key, figure in p["items"].items():
            if figure.get("restated"):
                rows.append(
                    {
                        "period": p["period_label"],
                        "line item": key,
                        "was": _millions(figure.get("previous_value")),
                        "public since": figure.get("previous_known_as_of") or "—",
                        "now": _millions(figure["value"]),
                        "restated on": figure["known_as_of"],
                    }
                )
    return rows


def _fraction(value: str | None, places: int = 2, percent: bool = False) -> str:
    if value is None:
        return "—"
    number = Decimal(value)
    return f"{number * 100:,.{places}f}%" if percent else f"{number:,.{places}f}"


def main() -> None:
    st.set_page_config(page_title="Company", layout="wide")
    st.title("Company")
    st.caption(
        "Statements from SEC EDGAR, prices from Yahoo Finance, every figure with the filing "
        "that made it public. Ratios are facts; the DCF runs on assumptions you type."
    )

    try:
        companies = fetch_companies()["companies"]
    except httpx.HTTPError as exc:
        st.error(
            f"Cannot reach the API at {API_BASE} ({type(exc).__name__}). "
            f"Start it with: .venv\\Scripts\\python.exe -m uvicorn services.api.main:app"
        )
        return
    if not companies:
        st.warning("No companies are loaded. Run `scripts/ingest_edgar.py --ticker AAPL`.")
        return

    tickers = [c["ticker"] for c in companies]
    left, middle, right = st.columns([1, 1, 1])
    ticker = left.selectbox(
        "Ticker", tickers, index=tickers.index("AAPL") if "AAPL" in tickers else 0
    )
    as_known_on = middle.date_input(
        "As known on",
        value=dt.date.today(),
        # Streamlit's default range is ten years back; XBRL history starts in 2009 and the
        # price history in 1980, so the control must reach every date the data does.
        min_value=dt.date(1980, 1, 1),
        max_value=dt.date.today(),
        help="What a reader on this date could have seen. Filings made after it - "
        "restatements included - are hidden, so the figures are the ones a decision "
        "on that day actually had.",
    )
    period_type = right.selectbox("Periods", ["FY", "Q1", "Q2", "Q3", "H1", "YTD"], index=0)
    company = next(c for c in companies if c["ticker"] == ticker)
    st.write(
        f"**{company['legal_name']}**  ·  {company['exchange']}  ·  CIK {company['cik']}  ·  "
        f"{company['statement_periods']} periods loaded, "
        f"newest filed {company['latest_filing_date']}"
    )
    if company["filing_overdue"]:
        st.warning(
            f"🔴 Overdue: a {company['next_filing_form']} was due by "
            f"{company['next_filing_due_by']} (the SEC's longest deadline) and is not held. "
            "Either the company is late or our copy is - refresh before relying on this page."
        )
    elif company["next_filing_due_by"]:
        st.caption(
            f"🟢 Up to date. Next: a {company['next_filing_form']} due by "
            f"{company['next_filing_due_by']}."
        )

    try:
        statements = fetch_statements(ticker, as_known_on.isoformat(), period_type)
    except httpx.HTTPError as exc:
        st.error(f"Could not load {ticker}: {type(exc).__name__}")
        return

    periods = statements["periods"][:8]
    if not periods:
        st.warning(f"Nothing of type {period_type} was known for {ticker} on {as_known_on}.")
        return

    st.subheader(f"Statements as known on {statements['as_known_on']}  (USD millions)")
    columns = [p["period_label"] for p in periods]
    for title, keys in STATEMENT_ROWS.items():
        rows = []
        for key in keys:
            if not any(key in p["items"] for p in periods):
                continue
            rows.append([key] + [_cell(p["items"].get(key)) for p in periods])
        if rows:
            st.markdown(f"**{title}**")
            st.table(pd.DataFrame(rows, columns=["line item"] + columns).set_index("line item"))
    provenance = pd.DataFrame(
        [
            {
                "period": p["period_label"],
                "period end": p["period_end"],
                "filed": p["filing_date"],
                "form": p["filing_type"],
                "accession": p["accession_no"],
                "filing": p["filing_url"],
                "known as of": p["known_as_of"],
                "document": p["source_document_id"],
            }
            for p in periods
        ]
    ).set_index("period")
    restated = _restatements(periods)
    if restated:
        with st.expander(f"↻ Restated in what you see — {len(restated)} figure(s)", expanded=True):
            st.caption(
                "Each of these was published once and then changed by a later filing. Both "
                "vintages are held; set 'as known on' before the restatement date to see the "
                "original everywhere."
            )
            st.table(pd.DataFrame(restated).set_index(["period", "line item"]))
    with st.expander("Provenance — the filing behind each column"):
        st.dataframe(
            provenance,
            column_config={
                "filing": st.column_config.LinkColumn(
                    "filing", help="The filing's folder on sec.gov", display_text="open on EDGAR"
                )
            },
        )
    st.caption(statements["attribution"])

    st.subheader("Ratios")
    period_choice = st.selectbox("Period", columns, index=0)
    try:
        ratios = fetch_ratios(ticker, as_known_on.isoformat(), period_choice)
    except httpx.HTTPError as exc:
        st.error(f"Could not compute ratios: {type(exc).__name__}")
        return
    price, shares = ratios.get("price"), ratios.get("shares")
    if price:
        age = price["age_days"]
        flag = "🔴" if age > 7 else "🟢"
        st.write(
            f"{flag} Price used: **{Decimal(price['close_raw']):,.2f}** on {price['date']} "
            f"({age} days before the decision date)  ·  {price['attribution']}"
        )
    else:
        st.warning("No price was known on this date, so every multiple is blank.")
    if shares:
        st.write(
            f"Shares used: **{Decimal(shares['shares']):,.0f}** ({shares['basic_or_diluted']}), "
            f"as of {shares['as_of_date']}, known {shares['known_as_of']}"
        )
    else:
        st.warning("No share count was known on this date, so per-share figures are blank.")
    ratio_columns = st.columns(len(RATIO_GROUPS))
    for column, (group, keys) in zip(ratio_columns, RATIO_GROUPS.items(), strict=True):
        column.markdown(f"**{group}**")
        percent = group in ("Profitability", "Returns") or keys[0].endswith("yield")
        for key in keys:
            value = ratios["ratios"].get(key)
            is_pct = percent or key.endswith("yield")
            column.write(f"{key}: {_fraction(value, percent=is_pct)}")

    st.subheader("DCF — on your assumptions")
    st.caption(
        "Growth, discount rate and terminal growth are yours; the model never chooses them. "
        "Base cash flow, net debt and shares default to the stored figures and are echoed back."
    )
    with st.form("dcf"):
        c1, c2, c3, c4 = st.columns(4)
        growth = c1.text_input("Growth per year (fractions)", value="0.06,0.05,0.04,0.03,0.03")
        discount_rate = c2.number_input("Discount rate", value=0.09, step=0.005, format="%.3f")
        terminal_growth = c3.number_input("Terminal growth", value=0.02, step=0.005, format="%.3f")
        mid_year = c4.checkbox("Mid-year convention", value=False)
        submitted = st.form_submit_button("Run")
    if submitted:
        try:
            result = fetch_dcf(
                ticker,
                {
                    "growth": growth,
                    "discount_rate": f"{discount_rate:.4f}",
                    "terminal_growth": f"{terminal_growth:.4f}",
                    "mid_year": str(mid_year).lower(),
                    "as_known_on": as_known_on.isoformat(),
                },
            )
        except httpx.HTTPStatusError as exc:
            st.error(
                f"The model refused these inputs ({exc.response.status_code}). Terminal growth "
                "must be below the discount rate, and a base cash flow must be available."
            )
            return
        except httpx.HTTPError as exc:
            st.error(f"Could not run the DCF: {type(exc).__name__}")
            return
        used = result["assumptions"]
        a, b, c = st.columns(3)
        a.metric("Equity value (USD m)", _millions(result["equity_value"]))
        b.metric(
            "Value per share (USD)",
            f"{Decimal(result['value_per_share']):,.2f}" if result["value_per_share"] else "—",
        )
        c.metric(
            "Terminal value share of EV", _fraction(result["terminal_share_of_value"], percent=True)
        )
        st.markdown("**Inputs the model ran on**")
        st.table(
            pd.DataFrame(
                [
                    [
                        "base free cash flow",
                        _millions(used["base_free_cash_flow"]),
                        used["base_free_cash_flow_source"],
                    ],
                    ["growth rates", ", ".join(used["growth_rates"]), "user"],
                    ["discount rate", used["discount_rate"], "user"],
                    ["terminal growth", used["terminal_growth"], "user"],
                    ["net debt", _millions(used["net_debt"]), used["net_debt_source"]],
                    [
                        "shares",
                        f"{Decimal(used['shares']):,.0f}" if used["shares"] else "—",
                        used["shares_source"] or "—",
                    ],
                ],
                columns=["input", "value", "source"],
            ).set_index("input")
        )
        schedule = pd.DataFrame(
            {
                "year": list(range(1, len(result["present_values"]) + 1)),
                "free cash flow (m)": [_millions(v) for v in result["projected_free_cash_flow"]],
                "discount factor": [_fraction(v, places=4) for v in result["discount_factors"]],
                "present value (m)": [_millions(v) for v in result["present_values"]],
            }
        ).set_index("year")
        st.table(schedule)
        st.write(
            f"Sum of present values {_millions(result['sum_of_present_values'])}m  +  "
            f"PV of terminal value {_millions(result['present_value_of_terminal'])}m  =  "
            f"enterprise value {_millions(result['enterprise_value'])}m"
        )


if __name__ == "__main__":
    main()
