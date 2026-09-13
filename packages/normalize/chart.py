"""The canonical chart of accounts, one version at a time, with its source mappings.

The chart and its mappings are **data**, seeded by migration 0011 and edited by people
(`docs/08` §2.3: a table gives versioning and an audit trail for free). This module reads
one `chart_version` into an immutable object a connector can resolve against, so that a
mapping edit takes effect on the next run and nothing about the vocabulary lives in code.

**Resolution is by priority.** XBRL offers several tags for one concept — `Revenues`,
`RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet` — and a filer uses
one of them. For each canonical key, the first mapped tag (lowest `priority`) that has a
figure for the period wins. A key with no mapped tag reporting is **absent**: the caller
writes NULL, never 0 (`SPEC.md` §4.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import AccountMapping, ChartAccount

__all__ = ["ChartVersion", "LabelMapping", "load_chart", "resolve"]


@dataclass(frozen=True)
class Account:
    canonical_key: str
    statement: str  # 'income'|'balance'|'cashflow'
    template: str  # 'financial'|'non_financial'|'both'
    display_name: str
    sign_convention: str
    is_required: bool


@dataclass(frozen=True)
class LabelMapping:
    source_label: str
    canonical_key: str
    priority: int


@dataclass(frozen=True)
class ChartVersion:
    """One version of the vocabulary and the mappings for one source system."""

    version: str
    source_system: str
    accounts: dict[str, Account]
    #: canonical key -> mappings, lowest priority number first
    mappings: dict[str, tuple[LabelMapping, ...]]

    def keys_for(self, statement: str, template: str) -> tuple[str, ...]:
        """Every canonical key a statement of this type has under this template.

        `'both'` keys belong to every template. Order is the seeded order, which is the
        display order.
        """
        return tuple(
            key
            for key, account in self.accounts.items()
            if account.statement == statement and account.template in (template, "both")
        )

    @property
    def mapped_labels(self) -> frozenset[str]:
        """Every source label any key maps from - what a parser needs to keep."""
        return frozenset(m.source_label for group in self.mappings.values() for m in group)

    def statement_of(self, canonical_key: str) -> str:
        return self.accounts[canonical_key].statement


def load_chart(session: Session, *, version: str, source_system: str) -> ChartVersion:
    """Read one chart version and the mappings for one source system."""
    accounts: dict[str, Account] = {}
    for account_row in session.execute(
        select(ChartAccount).where(ChartAccount.chart_version == version)
    ).scalars():
        accounts[account_row.canonical_key] = Account(
            canonical_key=account_row.canonical_key,
            statement=account_row.statement,
            template=account_row.template,
            display_name=account_row.display_name,
            sign_convention=account_row.sign_convention,
            is_required=account_row.is_required,
        )
    if not accounts:
        raise LookupError(f"chart_of_accounts has no rows for version {version!r}")

    grouped: dict[str, list[LabelMapping]] = {}
    for mapping_row in session.execute(
        select(AccountMapping)
        .where(AccountMapping.chart_version == version)
        .where(AccountMapping.source_system == source_system)
        .order_by(AccountMapping.canonical_key, AccountMapping.priority, AccountMapping.id)
    ).scalars():
        grouped.setdefault(mapping_row.canonical_key, []).append(
            LabelMapping(
                source_label=mapping_row.source_label,
                canonical_key=mapping_row.canonical_key,
                priority=mapping_row.priority,
            )
        )
    return ChartVersion(
        version=version,
        source_system=source_system,
        accounts=accounts,
        mappings={key: tuple(group) for key, group in grouped.items()},
    )


def resolve(
    reported: Mapping[str, Decimal | None], chart: ChartVersion, keys: Iterable[str]
) -> dict[str, Decimal | None]:
    """For each canonical key, the figure from its highest-priority reporting label.

    `reported` is label -> value for one period from one filing. A key none of whose labels
    appear is absent and maps to None. A key whose winning label is present with a None
    value is also None — absent is absent, however it arrived.
    """
    resolved: dict[str, Decimal | None] = {}
    for key in keys:
        value: Decimal | None = None
        for mapping in chart.mappings.get(key, ()):
            if mapping.source_label in reported:
                value = reported[mapping.source_label]
                break
        resolved[key] = value
    return resolved
