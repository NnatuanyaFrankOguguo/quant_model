"""What is going on: every job, judged, and how fresh each data set is. Operations view.

    .venv\\Scripts\\python.exe -m streamlit run apps\\streamlit\\operations_page.py

A thin client over three routes the API already serves - `/v1/public/operations/connectors`,
`/v1/public/companies` and `/v1/public/macro/series` - with no SQL and no judgement of its
own: the server says which jobs are ok, which need a human, and which never ran, in the
console's own vocabulary (green, yellow, red), and the page shows it.

The point is to *glance* rather than run a command. `scripts/check_connectors.py` says the
same things in the terminal; this says them in a browser tab that can stay open.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.environ.get("QUANT_API_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("QUANT_API_TOKEN", "")
TIMEOUT = 30.0

#: The console's vocabulary, as marks a table can carry.
MARKS: dict[str, str] = {
    "ok": "🟢 ok",
    "warning": "🟡 warning",
    "error": "🔴 error",
    "never_ran": "🔴 never ran",
}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(f"{API_BASE}{path}", params=params, headers=_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30)
def fetch_health(window_days: int) -> dict[str, Any]:
    return _get("/v1/public/operations/connectors", {"window_days": window_days})


@st.cache_data(ttl=30)
def fetch_companies() -> dict[str, Any]:
    return _get("/v1/public/companies")


@st.cache_data(ttl=30)
def fetch_series() -> dict[str, Any]:
    return _get("/v1/public/macro/series")


def _family(name: str) -> str:
    """The job's family, for grouping: 'edgar', 'yahoo', 'fred', 'ndp', 'cbn', 'manual'."""
    if ":" in name:
        return name.split(":", 1)[0]
    if name.startswith("manual_csv_"):
        return "manual"
    if name.startswith("cbn_"):
        return "cbn"
    return name


def main() -> None:
    st.set_page_config(page_title="Operations", layout="wide")
    st.title("Operations")
    st.caption(
        "Every scheduled job and manual path, judged by the server; every data set with its "
        "as-of date. Green, yellow and red mean what they mean on the console."
    )
    window_days = st.slider("Window (days)", min_value=1, max_value=90, value=7)

    try:
        health = fetch_health(window_days)
    except httpx.HTTPError as exc:
        st.error(
            f"Cannot reach the API at {API_BASE} ({type(exc).__name__}). "
            f"Start it with: .venv\\Scripts\\python.exe -m uvicorn services.api.main:app"
        )
        return

    a, b, c, d = st.columns(4)
    a.metric("ok", health["ok"])
    b.metric("warning", health["warning"])
    c.metric("error", health["error"])
    d.metric("never ran", health["never_ran"])
    if health["needs_a_human"]:
        st.warning(
            f"Something needs a human. Checked {health['checked_at'][:19].replace('T', ' ')} UTC "
            f"over the last {health['window_days']} days."
        )
    else:
        st.success(
            f"Every expected job ran and wrote rows in the last {health['window_days']} days. "
            f"Checked {health['checked_at'][:19].replace('T', ' ')} UTC."
        )

    jobs = health["jobs"]
    families = sorted({_family(j["name"]) for j in jobs})
    chosen = st.multiselect("Job families", families, default=families)
    only_attention = st.checkbox("Only what needs attention", value=False)
    rows = [
        {
            "job": j["name"],
            "state": MARKS.get(j["level"], j["level"]),
            "scheduled (UTC)": j["scheduled_at_utc"] or "manual",
            "last run": (j["last_run_at"] or "")[:16].replace("T", " "),
            "last status": j["last_status"] or "—",
            "runs": j["runs_in_window"],
            "rows": j["rows_in_window"],
            "finding": j["finding"] or "",
        }
        for j in jobs
        if _family(j["name"]) in chosen and (not only_attention or j["level"] != "ok")
    ]
    st.dataframe(pd.DataFrame(rows).set_index("job") if rows else pd.DataFrame(), height=520)

    st.subheader("How fresh each data set is")
    try:
        companies = fetch_companies()["companies"]
        series = fetch_series()["series"]
    except httpx.HTTPError as exc:
        st.error(f"Could not load the freshness view: {type(exc).__name__}")
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Companies — newest report held, and whether one is overdue**")
        overdue = [c for c in companies if c["filing_overdue"]]
        st.write(
            f"{len(companies)} companies · {len(overdue)} overdue"
            + (f": {', '.join(c['ticker'] for c in overdue)}" if overdue else "")
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ticker": c["ticker"],
                        "newest period": c["latest_period_end"],
                        "filed": c["latest_filing_date"],
                        "next": f"{c['next_filing_form']} by {c['next_filing_due_by']}",
                        "state": "🔴 overdue" if c["filing_overdue"] else "🟢",
                    }
                    for c in companies
                ]
            ).set_index("ticker"),
            height=420,
        )
    with right:
        st.markdown("**Macro series — as of, and whether stale**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "series": s["code"],
                        "as of": s.get("latest_as_of") or "—",
                        "published": s.get("latest_known_as_of") or "—",
                        "points": s.get("observation_count", 0),
                        "state": (
                            "⚪ empty"
                            if s.get("is_stale") is None
                            else ("🔴 stale" if s["is_stale"] else "🟢")
                        ),
                    }
                    for s in series
                ]
            ).set_index("series"),
            height=420,
        )
    st.caption(
        "A job that never ran fails exactly like one that runs and writes nothing, except "
        "quieter - which is why absence is on this page. Times are UTC."
    )


if __name__ == "__main__":
    main()
