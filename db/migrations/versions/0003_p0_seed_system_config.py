"""0003 - seed `system_config` (P0.12 / TG20).

Revision ID: 0003_p0_seed_system_config
Revises: 0002_p0_structural_enforcement
Create Date: 2026-09-01

The dated regulatory config named in `docs/10_PRE_BUILD_CORRECTIONS.md` §6.2 task P0.12
and in `docs/08_DATA_CONTRACTS.md` §2.15: *"Seeded in P0: licence_status,
family_tier_max_principals (6), the NGX fee stack, the ±10% band, the movement threshold,
settlement days, Nigerian CGT, and the four extraction thresholds from §3.1."*

**Why the table is dated, and why that is not ceremony.** The NGX movement rule and the
Nigerian CGT thresholds *both moved during the planning of this project*. A backtest over
2024 that reads today's numbers is measuring a market that did not exist. `effective_from`
on the CGT row is 2026-01-01, the Nigeria Tax Act 2025's commencement, not the date this
migration ran.

**The `[NEEDS VERIFICATION]` markers are load-bearing.** Several of these numbers are
ranges, broker-specific, or contested between sources in the planning documents. Where the
document set does not settle a figure, the marker is carried into `reason` verbatim rather
than dropped. A config row that looks clean and is not is worse than no row: the number
gets used, the uncertainty does not travel with it, and nobody re-checks a value that
never advertised a doubt. Anything reading these values for money decisions (P7 backtest,
P10 portfolio, P11 paper trading) must resolve its markers first.

`downgrade()` deletes exactly the `(key, effective_from)` pairs inserted here — never the
whole table, which by then may hold rows a human added.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_p0_seed_system_config"
down_revision: str | None = "0002_p0_structural_enforcement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Who recorded these. `set_by` answers "whose decision was this", not "which process ran".
SET_BY = "nnatuanyafrankoguguo"

# The date this configuration takes effect for everything except CGT, which commences on
# its own statutory date.
SEEDED_ON = date(2026, 9, 1)

# Nigeria Tax Act 2025 commencement (SPEC.md §2H).
TAX_ACT_2025_COMMENCEMENT = date(2026, 1, 1)

NEEDS_VERIFICATION = "[NEEDS VERIFICATION]"

SEED_ROWS: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- licence
    {
        "key": "licence_status",
        "value": "UNLICENSED",
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "No SEC Nigeria registration is held. This row is the licence half of the mode "
            "gate: personal-tier advice is served today because access is restricted to the "
            "owner and family, no fee is charged and no funds are pooled (SPEC.md §1.2, "
            "docs/10 §8 D2) — not because a licence exists. Flip to LICENSED only when both "
            "the adviser and fund-manager registrations are in hand. Reads fail closed: a "
            "missing, NULL or unparseable value resolves to UNLICENSED "
            "(docs/08 §2.15, packages/common/system_config.py)."
        ),
        "source_url": None,
        "adr_ref": "docs/08_DATA_CONTRACTS.md §2.15",
    },
    # ------------------------------------------------------------ family cap
    {
        "key": "family_tier_max_principals",
        "value": 6,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "Decision D2, resolved 2026-08-30: own capital and family capital, no fee. Six "
            "covers a household plus first-degree relatives with room to spare. The cap is "
            "not a limit on the family — it is a tripwire. Adding a seventh principal fails "
            "loudly and forces a deliberate decision, instead of drifting from three "
            "relatives to eleven acquaintances, one of whom offers to cover the server bill. "
            "Every technical permission check would still pass on that day."
        ),
        "source_url": None,
        "adr_ref": "docs/10_PRE_BUILD_CORRECTIONS.md §8 D2",
    },
    # --------------------------------------------------------- NGX fee stack
    {
        "key": "ngx_fee_stack",
        "value": {
            "currency": "NGN",
            "brokerage_pct": 0.0135,
            "brokerage_pct_range": [0.0075, 0.0135],
            "brokerage_applies_to": "both",
            "sec_fee_pct": 0.003,
            "sec_fee_applies_to": "both",
            "ngx_fee_pct": 0.003,
            "ngx_fee_applies_to": "sell",
            "cscs_fee_pct": 0.003,
            "cscs_fee_applies_to": "sell",
            "stamp_duty_pct": 0.00075,
            "stamp_duty_applies_to": "buy",
            "vat_pct_on_fees": 0.075,
            "vat_base": "brokerage_and_regulatory_fees_not_principal",
            "cscs_trade_alert_ngn": 4,
            "needs_verification": [
                "brokerage_pct",
                "cscs_fee_pct",
                "cscs_trade_alert_ngn",
            ],
        },
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "SPEC.md §2C. SEC 0.3%, NGX 0.3% (sell), CSCS 0.3% (sell), stamp duty 0.075% "
            "(buy), VAT 7.5% on brokerage and regulatory fees (never on principal). "
            f"{NEEDS_VERIFICATION} brokerage_pct: SPEC gives a 0.75%–1.35% range (traditional "
            "brokers to 1.35%, CardinalStone 1.20%, Chaka ~0.5% or ₦100 min, Bamboo ~1%); "
            "0.0135 is seeded as the conservative ceiling and MUST be replaced with the "
            "owner's actual contract-note rate before any live sizing. Brokerage is the one "
            "negotiable component and docs/10 §3.4 calls renegotiating it the highest-value "
            f"action in the trading plan. {NEEDS_VERIFICATION} cscs_fee_pct: SPEC notes "
            f"'some cite 0.06%–0.3%'. {NEEDS_VERIFICATION} cscs_trade_alert_ngn: SPEC gives "
            "₦4–6 flat per ticket. Not included here and NOT a fee: bid-ask spread and market "
            "impact, which docs/10 §3.5 shows are larger than the whole enumerated stack on "
            "NGX — they belong to the P7/P11 cost model, seeded when measured from real "
            "contract notes."
        ),
        "source_url": None,
        "adr_ref": "SPEC.md §2C; docs/10_PRE_BUILD_CORRECTIONS.md §3.5",
    },
    # -------------------------------------------------------- NGX price band
    {
        "key": "ngx_price_band",
        "value": {"pct": 0.10, "symmetric": True, "on_hit": "halt_for_day"},
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "SPEC.md §2C: NGX imposes a ±10% daily price band that HALTS the stock for the "
            "day when hit. It does not pause-and-resume like NYSE's 7/13/20% breakers or the "
            "LSE's 8%, so a backtest that fills at the band price is fictional — on a halted "
            "day there is no fill at all. Modelled by the P7 backtester and the P11 paper "
            "trader; also why a stop-loss is not an executable instrument on NGX and position "
            "size is the risk control instead."
        ),
        "source_url": None,
        "adr_ref": "SPEC.md §2C",
    },
    # ----------------------------------------------------- NGX movement rule
    {
        "key": "ngx_movement_rule",
        "value": {"basis": "flat", "units": 100000, "regulatory_status": "in_flux"},
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "SPEC.md §2C, per Nairametrics 2026-05-30: 100,000 shares must change hands "
            "before a stock price can move at all. "
            f"{NEEDS_VERIFICATION} — REGULATORY IN FLUX, and this row is dated precisely "
            "because of it. A tiered replacement (Group A ≥₦1,000: 10,000 units; Group B "
            "₦500–999.99: 50,000; Group C <₦500: 100,000) was SEC-approved 2026-06-16 and "
            "scheduled for 2026-08-17, then postponed a day before rollout (Nairametrics "
            "2026-08-16). The flat 100,000-unit rule remains in force as of 2026-09-01, on "
            "the authority of a secondary source and not of an NGX circular this project has "
            "read. When the tiered rule commences, close this row with effective_to and "
            "insert a new one — never edit this value, or every backtest over 2026 silently "
            "changes."
        ),
        "source_url": None,
        "adr_ref": "SPEC.md §2C",
    },
    # ------------------------------------------------------ settlement cycle
    {
        "key": "ngx_settlement_days",
        "value": 3,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "T+3, SPEC.md §2C and §2H. No same-day round trips; the capital lock-up is real "
            "and must be modelled. Mirrored on exchanges.settlement_days per docs/08 §2.1 "
            "('NGX = 3. Never hardcode T+3 in code') — this row is the dated policy value, "
            "the exchanges column is the per-venue operational value."
        ),
        "source_url": None,
        "adr_ref": "SPEC.md §2C",
    },
    # ------------------------------------------------------------ Nigeria CGT
    {
        "key": "ng_cgt_shares",
        "value": {
            "proceeds_exemption_ngn": 150000000,
            "chargeable_gain_exemption_ngn": 10000000,
            "lookback_months": 12,
            "individual_treatment": "progressive_personal_income_tax_bands",
            "individual_band_range_pct": [0.0, 0.25],
            "company_rate_pct": 0.30,
            "reinvestment_relief_same_year_of_assessment": True,
            "dividend_wht_pct": 0.10,
            "needs_verification": [
                "individual_treatment",
                "individual_band_range_pct",
                "company_rate_pct",
            ],
        },
        # The Act's commencement, NOT the date this migration ran. This is the reason
        # system_config is dated at all.
        "effective_from": TAX_ACT_2025_COMMENCEMENT,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "Nigeria Tax Act 2025, effective 2026-01-01 (SPEC.md §2H). Per the Act's "
            "Explanatory Memorandum as quoted in SPEC: gains on disposal of shares in "
            "Nigerian companies are not chargeable where disposal proceeds in aggregate are "
            "less than ₦150,000,000 AND the chargeable gain does not exceed ₦10,000,000 in "
            "any 12 consecutive months (raised from the prior ₦100m), or where proceeds are "
            "reinvested in the same year of assessment. Dividend withholding tax 10% "
            f"(SPEC.md §2H, sourced). {NEEDS_VERIFICATION} individual_treatment, "
            "individual_band_range_pct and company_rate_pct: SPEC states CGT for individuals "
            "is folded into progressive PIT bands (0%–25%) and that the company rate rose to "
            "'effectively 30%', but cites the Explanatory Memorandum only for the two "
            "thresholds. Read the Act's own text before computing a tax figure a human acts "
            "on. NOT seeded: the pre-2026 regime (₦100m threshold, flat 10% for "
            "individuals) — a prior row needs a verified commencement date this project does "
            "not have, and inventing one would date a backtest wrongly."
        ),
        "source_url": None,
        "adr_ref": "SPEC.md §2H",
    },
    # --------------------------------------------- P4.0 extraction thresholds
    {
        "key": "extraction_target_headline",
        "value": 0.95,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "docs/10 §3.1, accepted unchanged by the owner as decision D3 (2026-08-30). The "
            "~25 materiality-weighted headline canonical keys — revenue, PAT, total assets, "
            "total liabilities, total equity, cash-flow subtotals. P4 does not exit below "
            "this. Metric: one canonical_key per statement per company-year; denominator is "
            "every line item in the golden JSON (an omitted key counts as wrong, a correctly "
            "null key counts as right); match is numeric equality after unit conversion, "
            "tolerance ±0.5% or ±₦1,000 whichever is larger, sign exact. The gate is on the "
            "PRE-review number."
        ),
        "source_url": None,
        "adr_ref": "docs/10_PRE_BUILD_CORRECTIONS.md §3.1; §8 D3",
    },
    {
        "key": "extraction_target_all_items",
        "value": 0.90,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "docs/10 §3.1, accepted as decision D3. All canonical keys, pre-review. Matches "
            "DATA_FOUNDATION.md §3.1's '~60% → 90%+' claim for the hybrid extraction "
            "pipeline. Same metric and tolerance as extraction_target_headline."
        ),
        "source_url": None,
        "adr_ref": "docs/10_PRE_BUILD_CORRECTIONS.md §3.1; §8 D3",
    },
    {
        "key": "extraction_abandon_floor",
        "value": 0.85,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "docs/10 §3.1, accepted as decision D3. Gate G-A: below this after two weeks, "
            "stop building the extractor and buy EODHD. A FLOOR, NOT A TARGET — the audit "
            "found three unrelated 0.85s within a page of each other in P4, which made "
            "clearing 'abandon' read as passing. Do not conflate with "
            "extraction_confidence_route, which shares the number and means something else."
        ),
        "source_url": None,
        "adr_ref": "docs/10_PRE_BUILD_CORRECTIONS.md §3.1; §8 D3",
    },
    {
        "key": "extraction_confidence_route",
        "value": 0.85,
        "effective_from": SEEDED_ON,
        "effective_to": None,
        "set_by": SET_BY,
        "reason": (
            "docs/10 §3.1, accepted as decision D3. Per-extraction human-review routing "
            "threshold used by P4.3: an extraction scoring below this goes to a reviewer. "
            "UNRELATED to the three accuracy gates above despite sharing the value 0.85 — "
            "that collision is the specific confusion docs/10 §3.1 was written to end."
        ),
        "source_url": None,
        "adr_ref": "docs/10_PRE_BUILD_CORRECTIONS.md §3.1; §8 D3",
    },
]


system_config_table = sa.table(
    "system_config",
    sa.column("key", sa.Text()),
    sa.column("value", postgresql.JSONB()),
    sa.column("effective_from", sa.Date()),
    sa.column("effective_to", sa.Date()),
    sa.column("set_by", sa.Text()),
    sa.column("reason", sa.Text()),
    sa.column("source_url", sa.Text()),
    sa.column("adr_ref", sa.Text()),
)


def upgrade() -> None:
    op.bulk_insert(system_config_table, SEED_ROWS)


def downgrade() -> None:
    # Exactly the keys this revision inserted, matched on the full primary key. A blanket
    # DELETE would take rows a human added between then and now.
    for row in SEED_ROWS:
        op.execute(
            system_config_table.delete().where(
                sa.and_(
                    system_config_table.c.key == row["key"],
                    system_config_table.c.effective_from == row["effective_from"],
                )
            )
        )
