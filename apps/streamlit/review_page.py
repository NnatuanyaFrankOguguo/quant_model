r"""The review queue: what needs a human, worst first. P4.4.

    .venv\\Scripts\\python.exe -m streamlit run apps\\streamlit\\review_page.py --server.port 8505

`docs/03` P4.4 asks for three things, and this page is two of them:

* **a queue prioritised by materiality** - *"a FIFO queue wastes your scarcest resource,
  reviewer attention, on trivia"*;
* **the correction rate as a headline metric** - *"if it isn't falling, the extractor isn't
  learning and something is wrong with the feedback loop."*

The third is the editable form beside the PDF page, and it already exists:
`apps/streamlit/entry_page.py` is P3.2's typed-entry form, which writes a corrected figure
with full provenance and the reviewer's name. This page's job is to decide *what to open*,
and then hand over. Rebuilding the form here would be a second write path to the same
table, with its own bugs, for figures that are already the hardest in the system to get
right.

A thin client, per AD-3 and like every other page here: it calls the API and shows what
comes back. No SQL, no arithmetic, no opinion of its own about what is worst. The server
computed the ordering and the page displays it - which is what makes the ordering testable
in `tests/compliance/test_review_api.py` rather than something you eyeball.

**A token is required.** These routes are personal-tier, because the queue names companies
beside figures this system believes are wrong. That is an internal judgement rather than a
fact about the company, and an anonymous reader of it would be reading an accusation.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.environ.get("QUANT_API_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("QUANT_API_TOKEN", "")
TIMEOUT = 60.0

#: How far back the correction rate is measured by default. Long enough to hold several
#: weeks of extraction - P4.4 wants the *trend*, and a window of days is mostly noise.
DEFAULT_WINDOW_DAYS = 90

#: Findings that mean the figures cannot all be true at once, rather than that one looks
#: unusual. `packages.normalize.review.IMPOSSIBLE_IDENTITIES` decides the severity; this is
#: only how the page marks it.
IMPOSSIBLE = ("_within_", "_is_positive", "_not_negative", "_less_")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(f"{API_BASE}{path}", params=params, headers=_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def fetch_queue(limit: int, company_id: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if company_id:
        params["company_id"] = company_id
    return _get("/v1/personal/review/queue", params)


@st.cache_data(ttl=60)
def fetch_correction_rate(start: dt.date, end: dt.date) -> dict[str, Any]:
    return _get(
        "/v1/personal/review/correction-rate",
        {"start": start.isoformat(), "end": end.isoformat()},
    )


def _mark(finding: str) -> str:
    """Impossible, or merely suspicious. The distinction a reviewer triages on."""
    return "🔴" if any(token in finding for token in IMPOSSIBLE) else "🟡"


def main() -> None:
    st.set_page_config(page_title="Review queue", layout="wide")
    st.title("Review queue")
    st.caption(
        "Worst first, by materiality. Open a figure in the entry form to correct it - "
        "corrections are written there, with provenance and your name on them."
    )

    if not TOKEN:
        st.error(
            "Set `QUANT_API_TOKEN`. These routes are personal-tier: the queue names "
            "companies beside figures this system believes are wrong, which is an "
            "internal judgement rather than a fact about the company."
        )
        return

    with st.sidebar:
        st.header("Scope")
        limit = st.slider("Items to show", min_value=10, max_value=200, value=50, step=10)
        company_id = st.number_input(
            "One company only (id)",
            min_value=0,
            value=0,
            help="0 shows every company. Useful once a systematic problem is being worked.",
        )
        window_days = st.slider(
            "Correction-rate window (days)",
            min_value=7,
            max_value=365,
            value=DEFAULT_WINDOW_DAYS,
            step=7,
        )

    try:
        queue = fetch_queue(int(limit), int(company_id) or None)
        end = dt.date.today()
        rate = fetch_correction_rate(end - dt.timedelta(days=int(window_days)), end)
    except httpx.HTTPStatusError as exc:
        st.error(
            f"The API refused: HTTP {exc.response.status_code}. A 403 means the token is "
            f"authenticated but not entitled to the personal tier."
        )
        return
    except httpx.HTTPError as exc:
        st.error(f"Could not reach the API at {API_BASE}: {type(exc).__name__}")
        return

    _headline(queue, rate, int(window_days))
    _queue_table(queue)


def _headline(queue: dict[str, Any], rate: dict[str, Any], window_days: int) -> None:
    """The two numbers P4.4 watches, side by side."""
    shown, limit = queue["shown"], queue["limit"]
    left, middle, right = st.columns(3)
    left.metric(
        "In the queue",
        f"{shown}",
        help=(
            "How many came back, not how many exist: the server returns at most "
            f"{limit}. Raise the limit in the sidebar to see whether the queue is deeper."
        ),
    )
    # `None` is not 0%. A window in which nothing was written has an unknown rate, and
    # showing 0.0% for a quiet week would read as the best week on record.
    correction = rate["correction_rate"]
    middle.metric(
        f"Correction rate ({window_days}d)",
        "unknown" if correction is None else f"{float(correction):.2%}",
        help=(
            "Our errors over items written. TEAM_BRIEF Part 3: if it is not falling, the "
            "extractor is not learning and the feedback loop is broken. 'unknown' means "
            "nothing was written in the window - which is not the same as no errors."
        ),
    )
    right.metric(
        "Restatements",
        f"{rate['restatements']}",
        help=(
            "Excluded from the rate. A company revising its own figures is the world "
            "changing its mind, not this system being wrong."
        ),
    )
    if shown == limit:
        st.info(
            f"Showing the worst {limit}, which is all that was asked for - the queue may "
            f"be deeper. Queue depth growing week over week is P4's reviewer-capacity "
            f"warning sign."
        )


def _queue_table(queue: dict[str, Any]) -> None:
    items = queue["items"]
    if not items:
        st.success("Nothing outstanding. Every checkable identity passes.")
        return

    rows = []
    for item in items:
        span = (
            f"{item['first_period']} → {item['period_end']}"
            if item["occurrences"] > 1
            else str(item["period_end"])
        )
        rows.append(
            {
                "": _mark(item["finding"]),
                "Company": item["company_name"],
                "Period": span,
                # More than one period means systematic - a mapping or a definition rather
                # than a typo - which is the most useful thing to know before opening
                # anything, so it gets a column rather than a footnote.
                "Periods": item["occurrences"],
                "Finding": item["finding"],
                "Key": item["canonical_key"] or "",
                "Required": "yes" if item["is_required"] else "",
                "Share of statement": (
                    f"{float(item['share_of_anchor']):.1%}"
                    if float(item["share_of_anchor"]) > 0
                    else ""
                ),
                "Priority": round(float(item["priority"]), 2),
                "Detail": item["detail"],
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "🔴 the figures cannot all be true at once. 🟡 one of them looks wrong. "
        "Order is the server's, by severity × share of the statement × whether the key is "
        "required - not by age."
    )


if __name__ == "__main__":
    main()
