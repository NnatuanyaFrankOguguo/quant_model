"""The macro dashboard. P1.6 — v0.1's visible output.

    .venv\\Scripts\\python.exe -m streamlit run apps/streamlit/macro_dashboard.py

**A thin client, and that is a rule with teeth (AD-3).** This module calls the API and
renders what comes back. There is no SQL here, and no arithmetic on the figures — if you
find yourself computing a year-on-year change in a callback, it belongs behind the API in a
package. That is what makes replacing Streamlit with Next.js at P9 a presentation change
rather than a rewrite, and it is the discipline that quietly decays first.

**Staleness is deliberately loud.** `CLAUDE.md` requires that staleness be visible, and
`docs/03` P1.6 says not to use a subtle grey — the point is that you cannot miss it. An
overdue series gets a red banner and a warning row, not a muted caption.

**"No data yet" is shown as its own state**, distinct from fresh and from stale. Most of
these series have no connector until CBN scraping lands, and rendering an empty series as
though it were healthy would be the dashboard telling its first lie.
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


def _headers() -> dict[str, str]:
    """Macro data is public-tier, so a token is optional here.

    It is still sent when present, because every request should carry the principal it
    belongs to — the `audit_log` row is only as useful as the identity on it.
    """
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


@st.cache_data(ttl=60)
def fetch_series() -> dict[str, Any]:
    response = httpx.get(f"{API_BASE}/v1/public/macro/series", headers=_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def fetch_observations(code: str, as_known_on: str | None, limit: int = 2000) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if as_known_on:
        params["as_known_on"] = as_known_on
    response = httpx.get(
        f"{API_BASE}/v1/public/macro/series/{code}/observations",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _freshness_label(row: dict[str, Any]) -> str:
    if row["observation_count"] == 0:
        return "⬜ no data yet"
    if row["is_stale"] is None:
        return "➖ n/a (irregular)"
    if row["is_stale"]:
        return f"🔴 OVERDUE ({row['days_since_as_of']}d)"
    return f"🟢 fresh ({row['days_since_as_of']}d)"


def main() -> None:
    st.set_page_config(page_title="Macro backdrop", layout="wide")
    st.title("Macro backdrop")
    st.caption(
        "Nigeria and US macro series. Every figure carries the period it describes "
        "(as-of) and the date it was published (known-as-of). They are not the same date, "
        "and the difference is what makes point-in-time analysis honest."
    )

    try:
        payload = fetch_series()
    except httpx.HTTPError as exc:
        st.error(
            f"Cannot reach the API at {API_BASE} ({type(exc).__name__}). "
            f"Start it with: .venv\\Scripts\\python.exe -m uvicorn services.api.main:app"
        )
        return

    series = payload["series"]
    if not series:
        st.warning("No series are configured. Run `alembic upgrade head` to seed them.")
        return

    overdue = [s for s in series if s["is_stale"]]
    empty = [s for s in series if s["observation_count"] == 0]

    if overdue:
        st.error(
            f"**{len(overdue)} series overdue:** "
            + ", ".join(f"{s['code']} ({s['days_since_as_of']}d)" for s in overdue)
        )
    if empty:
        st.warning(
            f"**{len(empty)} series have no observations yet:** "
            + ", ".join(s["code"] for s in empty)
            + ".  These are the sources with no machine-readable feed — NBS publishes "
            "through a portal and DMO publishes PDFs. Feed them with "
            "`scripts/ingest_csv.py`, which needs no API key."
        )

    table = pd.DataFrame(
        [
            {
                "Series": s["code"],
                "Name": s["name"],
                "Latest": s["latest_value"],
                "Unit": s["unit"],
                "As of": s["latest_as_of"] or "—",
                "Published": s["latest_known_as_of"] or "—",
                "Freshness": _freshness_label(s),
                "Source": s["source_name"],
                "Points": s["observation_count"],
            }
            for s in series
        ]
    )
    st.subheader("Series")
    st.dataframe(table, use_container_width=True, hide_index=True)

    with_data = [s for s in series if s["observation_count"] > 0]
    if not with_data:
        st.info(
            "Nothing to chart yet. The series list above is real — it is the decided P1 "
            "list — but no observations have been ingested."
        )
        _footer(series)
        return

    st.subheader("History")
    chosen = st.selectbox(
        "Series", [s["code"] for s in with_data], format_func=lambda c: _name_for(series, c)
    )
    as_known_on = st.text_input(
        "Point-in-time view (YYYY-MM-DD, optional)",
        help=(
            "Show only what was published on or before this date. This is how a decision "
            "made in the past should see the data: later revisions are hidden."
        ),
    ).strip()

    try:
        observations = fetch_observations(chosen, as_known_on or None)
    except httpx.HTTPError as exc:
        st.error(f"Could not load {chosen}: {type(exc).__name__}")
        return

    points = observations["observations"]
    if not points:
        st.info(
            "No observations were visible at that date. Before it was published, the figure "
            "did not exist — it is not zero."
        )
    else:
        if observations.get("truncated"):
            # Said out loud, not inferred from a short line. A reader who thinks they are
            # looking at the whole history when they are looking at the most recent slice
            # will draw the wrong conclusion and have no way to notice.
            st.info(
                f"Showing the most recent {len(points):,} of "
                f"{observations['total_available']:,} periods. Set a start date to see "
                f"earlier history."
            )
        frame = pd.DataFrame(points)
        frame["as_of_date"] = pd.to_datetime(frame["as_of_date"])
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        st.line_chart(frame.set_index("as_of_date")["value"], height=320)
        st.caption(
            f"{observations['name']} — {observations['unit']}. "
            + (
                f"As known on {observations['as_known_on']}."
                if observations["as_known_on"]
                else "Newest vintage per period."
            )
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)

    _footer(series)


def _name_for(series: list[dict[str, Any]], code: str) -> str:
    for row in series:
        if row["code"] == code:
            return f"{row['code']} — {row['name']}"
    return code


def _footer(series: list[dict[str, Any]]) -> None:
    """Attribution, because the licensing register says it is required.

    It travels with the data from the API rather than being hardcoded here, so a source
    whose terms change updates one database row and every surface follows.
    """
    attributions = sorted({s["attribution"] for s in series if s.get("attribution")})
    if attributions:
        st.divider()
        st.caption("  ·  ".join(attributions))


if __name__ == "__main__":
    # Streamlit's script runner executes this file with `__name__ == "__main__"`, so this
    # is the entry point for `streamlit run` as well as for a direct invocation. It must
    # stay guarded: an unguarded call would render the whole dashboard as a side effect of
    # importing the module, including from a test.
    main()
