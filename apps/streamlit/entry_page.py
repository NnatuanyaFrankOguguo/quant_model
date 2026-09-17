r"""The manual entry form: the PDF page beside the fields. P3.2.

    streamlit run apps\streamlit\entry_page.py --server.port 8504

`docs/03` P3.2: *"A Streamlit form (thin client, per AD-3) showing the PDF page beside the
input fields, writing through the API to `statement_line_items` with full provenance."*

**Thin means thin.** This file validates nothing of substance. Every rule - blank stores NULL,
a page must exist in the document, a key must belong to the statement, a period already
entered is a correction and not a second entry - lives in `packages/normalize/manual.py` and
is enforced by the API. A form that checked them itself would be a second implementation
that drifts, and would protect only the people who use the form; the same figures can arrive
from a script, and they must meet the same rules.

So what this file does is narrow: show the page, collect what the operator typed verbatim,
POST it, and render the refusal against the field it names.

**The one thing it must get right is not helping.** No default of zero, no "0" placeholder,
no coercing an empty box to a number. `st.text_input` returning `""` is the operator saying
the line is not on the page, and it must travel to the API as `""`. A `st.number_input` with
a default would silently turn every skipped line into a reported zero, which is
`SPEC.md` §4.1's fourth invariant broken by a widget choice.

The token is read from the environment, so the name on every figure is whoever holds it.
`reviewed_by` is not a field here and cannot be: the server takes it from the authenticated
principal.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from typing import Any

import httpx
import streamlit as st

API_BASE = os.environ.get("QUANT_API_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("QUANT_API_TOKEN", "")
TIMEOUT = 60.0

STATEMENT_TYPES = ("income", "balance", "cashflow")
PERIOD_TYPES = ("FY", "H1", "Q1", "Q2", "Q3", "Q4", "YTD")
#: `packages/common/units.py`'s whole vocabulary. A fourth entry here would be a figure
#: nobody downstream can read, so the list is not editable from the UI.
SCALES = ("units", "thousands", "millions")

#: Offered per statement, in the order a statement prints them. Not authoritative - the API
#: refuses a key that does not belong - but it saves the operator typing canonical keys and
#: keeps the common case honest.
SUGGESTED_KEYS: dict[str, tuple[str, ...]] = {
    "income": (
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_profit",
        "finance_income",
        "finance_costs",
        "interest_income",
        "net_interest_income",
        "loan_impairment_charges",
        "fee_and_commission_income",
        "insurance_revenue",
        "insurance_service_result",
        "gross_premium_written",
        "net_premium_income",
        "fx_loss_net",
        "profit_before_tax",
        "income_tax",
        "profit_after_tax",
    ),
    "balance": (
        "total_assets",
        "current_assets",
        "cash",
        "loans_and_advances_to_customers",
        "investment_securities_fvoci",
        "insurance_contract_liabilities",
        "total_liabilities",
        "current_liabilities",
        "long_term_debt",
        "deposits_from_customers",
        "total_equity",
    ),
    "cashflow": (
        "cash_from_ops",
        "depreciation_amortisation",
        "capex",
        "dividends_paid",
        "buybacks",
    ),
}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _companies() -> list[dict[str, Any]]:
    response = httpx.get(f"{API_BASE}/v1/public/companies", timeout=TIMEOUT)
    response.raise_for_status()
    return list(response.json().get("companies", []))


def _upload(name: str, data: bytes) -> dict[str, Any]:
    response = httpx.post(
        f"{API_BASE}/v1/personal/documents",
        files={"file": (name, data, "application/pdf")},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise _ApiRefusedError(response)
    return dict(response.json())


def _enter(payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{API_BASE}/v1/personal/statements",
        json=payload,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise _ApiRefusedError(response)
    return dict(response.json())


class _ApiRefusedError(Exception):
    """A 4xx from the API, carrying the field names it blamed.

    The body says `invalid_request` and never why (`docs/10` §4.7 keeps free text out of an
    error body, because a reason can quote a figure). The `request_id` is how the operator
    or whoever helps them finds the sentence in the log.
    """

    def __init__(self, response: httpx.Response) -> None:
        body: dict[str, Any] = {}
        with contextlib.suppress(ValueError):
            body = dict(response.json())
        self.status = response.status_code
        self.detail = str(body.get("detail", response.text[:200]))
        self.fields = [str(name) for name in body.get("fields") or []]
        self.request_id = body.get("request_id")
        super().__init__(self.detail)


def _explain(refusal: _ApiRefusedError) -> None:
    """Show a refusal against the fields it named, and say where the reason is."""
    if refusal.status == 403:
        st.error(
            "The API refused this as unauthorised. Set `QUANT_API_TOKEN` to a token for a "
            "principal with `personal_tier` - `scripts/mint_token.py` issues one."
        )
        return
    st.error(
        f"The API refused the entry ({refusal.status}: {refusal.detail}). Nothing was written."
    )
    if refusal.fields:
        st.write("Fields it blamed:")
        for name in refusal.fields:
            index = _figure_index(name)
            if index is None:
                st.markdown(f"- `{name}`")
            else:
                st.markdown(f"- row {index + 1} of the figures below")
    if refusal.request_id:
        st.caption(
            f"The reason is in the API log under request_id `{refusal.request_id}`. Error "
            f"bodies carry field names, never values, so the sentence stays server-side."
        )


def _figure_index(field_name: str) -> int | None:
    parts = field_name.split(".")
    if len(parts) >= 2 and parts[0] == "figures" and parts[1].isdigit():
        return int(parts[1])
    return None


def main() -> None:
    st.set_page_config(page_title="Type a statement", layout="wide")
    st.title("Type a statement from a report")
    st.caption(
        "Every figure is stored with the document, the page, the publication date and your "
        "name. Leave a box empty when the line is not on the page - it stores nothing, "
        "never zero."
    )

    if not TOKEN:
        st.warning(
            "`QUANT_API_TOKEN` is not set, so the API will refuse to write. Mint one with "
            "`scripts/mint_token.py` and restart with it in the environment."
        )

    # ---------------------------------------------------------------- the document
    st.header("1. The report")
    upload = st.file_uploader("The PDF the figures are read from", type=["pdf"])
    if upload is None:
        st.info("Upload a report to begin. It is stored once, by content hash.")
        return

    if st.session_state.get("uploaded_name") != upload.name:
        try:
            stored = _upload(upload.name, upload.getvalue())
        except _ApiRefusedError as refusal:
            _explain(refusal)
            return
        except httpx.HTTPError as exc:
            st.error(f"Cannot reach the API at {API_BASE} ({type(exc).__name__}).")
            return
        st.session_state["uploaded_name"] = upload.name
        st.session_state["document"] = stored

    document = st.session_state.get("document")
    if not document:
        return
    if document["created"]:
        st.success(f"Stored as document {document['document_id']}, {document['page_count']} pages.")
    else:
        st.info(
            f"Already held as document {document['document_id']} "
            f"({document['page_count']} pages). Re-uploading changed nothing."
        )
    st.caption(f"sha256 `{document['sha256']}`")

    page_of, figures_column = st.columns([3, 2])

    # ---------------------------------------------------------------- the page beside the fields
    with page_of:
        st.header("The page")
        page_shown = st.number_input(
            "Page",
            min_value=1,
            max_value=int(document["page_count"]),
            value=1,
            step=1,
            key="page_shown",
            help="Which page to render. Each figure records its own page separately.",
        )
        _render_page(upload.getvalue(), int(page_shown))

    # ---------------------------------------------------------------- the figures
    with figures_column:
        st.header("2. The statement")
        company = _pick_company()
        statement_type = st.selectbox("Statement", STATEMENT_TYPES)
        period_type = st.selectbox("Period", PERIOD_TYPES)
        period_end = st.date_input("Period end", value=dt.date(2025, 12, 31))
        known_as_of = st.date_input(
            "Published on",
            value=dt.date(2026, 4, 30),
            help=(
                "When the issuer published the report - not today. This decides whether a "
                "backtest deciding on an earlier date is allowed to see these figures."
            ),
        )
        currency = st.text_input("Currency", value="NGN", max_chars=3)
        scale = st.selectbox(
            "Scale",
            SCALES,
            index=1,
            help="Read it off the statement's own column heading, not from the magnitudes.",
        )
        is_audited = st.checkbox("Audited", value=True)
        is_consolidated = st.checkbox("Consolidated", value=True)

        st.subheader("3. The figures")
        st.caption(
            "Type what the page shows, including brackets and a dash. Empty means the line "
            "is not there."
        )
        rows = _figure_rows(statement_type, int(document["page_count"]))

    if st.button("Write these figures", type="primary", disabled=company is None):
        if company is None:
            return
        typed = [row for row in rows if row["printed"].strip() or row["include"]]
        if not typed:
            st.warning("Nothing to write: no figure was filled in.")
            return
        payload = {
            "ticker": company["ticker"],
            "exchange": company.get("exchange"),
            "statement_type": statement_type,
            "period_type": period_type,
            "period_end": str(period_end),
            "known_as_of": str(known_as_of),
            "currency": currency.upper(),
            "scale": scale,
            "source_document_id": document["document_id"],
            "is_audited": is_audited,
            "is_consolidated": is_consolidated,
            "figures": [
                {
                    "canonical_key": row["canonical_key"],
                    "printed": row["printed"],
                    "page": row["page"],
                }
                for row in typed
            ],
        }
        try:
            written = _enter(payload)
        except _ApiRefusedError as refusal:
            _explain(refusal)
            return
        except httpx.HTTPError as exc:
            st.error(f"Cannot reach the API at {API_BASE} ({type(exc).__name__}).")
            return
        st.success(
            f"Statement {written['statement_id']}: {written['line_items_written']} figures, "
            f"{written['figures_absent']} of them recorded as not reported. "
            f"Signed {written['reviewed_by']}."
        )
        st.caption(
            "To change one of these, use `scripts/correct_figure.py`. A second entry for the "
            "same period is refused: a correction versions the statement and records why."
        )


def _pick_company() -> dict[str, Any] | None:
    try:
        companies = _companies()
    except httpx.HTTPError as exc:
        st.error(f"Cannot list companies from {API_BASE} ({type(exc).__name__}).")
        return None
    if not companies:
        st.warning("No companies are registered yet, so there is nothing to attach a figure to.")
        return None
    labels = {f"{row['ticker']} - {row.get('legal_name', '')}": row for row in companies}
    return labels[st.selectbox("Company", sorted(labels))]


def _figure_rows(statement_type: str, page_count: int) -> list[dict[str, Any]]:
    """One row per suggested key: a box for what the page shows, and the page it is on."""
    rows: list[dict[str, Any]] = []
    default_page = int(st.session_state.get("page_shown", 1))
    for key in SUGGESTED_KEYS.get(statement_type, ()):
        printed_column, page_column, include_column = st.columns([3, 1, 1])
        printed = printed_column.text_input(
            key,
            value="",
            key=f"printed_{statement_type}_{key}",
            placeholder="",  # never "0"
        )
        page = page_column.number_input(
            "p.",
            min_value=1,
            max_value=page_count,
            value=min(default_page, page_count),
            step=1,
            key=f"page_{statement_type}_{key}",
            label_visibility="collapsed",
        )
        include = include_column.checkbox(
            "n/r",
            key=f"include_{statement_type}_{key}",
            help=(
                "Send this key even though the box is empty, to record that the company did "
                "not report it. Leave unticked to omit the key entirely."
            ),
        )
        rows.append(
            {"canonical_key": key, "printed": printed, "page": int(page), "include": include}
        )
    return rows


def _render_page(data: bytes, page: int) -> None:
    """Show one page of the PDF, or say plainly why it cannot be shown.

    `pymupdf` renders; it is in the `data` extra and may not be installed. A form that
    crashed on the import would be unusable for want of a picture, so the fallback is a
    message and the fields keep working - the figures are what matters, and the operator has
    the PDF open anyway.
    """
    try:
        import pymupdf  # noqa: PLC0415 - optional, and only for the preview
    except ImportError:
        st.info(
            "Install `pymupdf` (in the `data` extra) to see the page here. The fields below "
            "work without it."
        )
        return
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            rendered = pdf[page - 1].get_pixmap(dpi=150)
            st.image(rendered.tobytes("png"), use_container_width=True)
    except Exception as exc:  # noqa: BLE001 - a preview must not take the form down
        st.warning(f"Could not render page {page}: {type(exc).__name__}.")


if __name__ == "__main__":
    main()
