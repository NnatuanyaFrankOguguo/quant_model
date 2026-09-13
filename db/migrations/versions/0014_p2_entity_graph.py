"""0014 - the entity graph, created empty: persons, roles, holders, relationships, indices. P2.

Revision ID: 0014_p2_entity_graph
Revises: 0013_p2_shares_outstanding
Create Date: 2026-09-13

`docs/08` §2.14 #50–54 and `docs/10` §6.7. Five tables the first draft of the plan omitted
entirely - a company's *relationships*, which the Bloomberg company view shows and which
the model described nowhere: board seats and executive roles, dated; substantial holders;
subsidiaries, auditors, related parties and major customers as one edge table; and
point-in-time index membership, which P7's survivorship check needs whatever the product
does with it.

**Created empty here, on purpose, and populated later.** `index_membership` is filled by
hand in P3 for the initial universe; the other four are extraction targets on documents P4
is already parsing - the Directors' Report, the substantial-shareholders schedule, the audit
report, the related-party note. The schema is the only part that is expensive to defer
(`docs/10` §6.7's sequencing table), so it lands with the phase that creates the rest of
the P2 schema.

Every table carries `known_as_of` and `source_document_id NOT NULL`: a board membership is a
fact extracted from a page and is corrected the way a revenue figure is. `entity_roles`,
`shareholdings` and `company_relationships` carry `needs_review` so they route through the
same human-review queue as line items.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_p2_entity_graph"
down_revision: str | None = "0013_p2_shares_outstanding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        # Nigerian names carry honorifics and spellings; this is what matching joins on.
        sa.Column("normalised_name", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_persons_normalised_name", "persons", ["normalised_name"])

    op.create_table(
        "entity_roles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("person_id", sa.BigInteger(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        # 'chairman'|'ceo'|'cfo'|'executive'|'ned'|'independent_ned'|'company_secretary'
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_entity_roles_company", "entity_roles", ["company_id", "valid_from"])

    op.create_table(
        "shareholdings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("holder_name", sa.Text(), nullable=False),
        # 'person'|'company'|'government'|'fund'|'nominee'
        sa.Column("holder_type", sa.Text(), nullable=False),
        sa.Column("holder_person_id", sa.BigInteger(), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("holder_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("units", sa.Numeric(), nullable=True),
        sa.Column("pct_held", sa.Numeric(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_shareholdings_company", "shareholdings", ["company_id", "as_of_date"])

    op.create_table(
        "company_relationships",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("from_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("to_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("to_name", sa.Text(), nullable=True),
        # 'parent'|'subsidiary'|'associate'|'joint_venture'|'auditor'|'related_party'
        # |'major_customer'|'supplier'
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("ownership_pct", sa.Numeric(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "to_company_id IS NOT NULL OR to_name IS NOT NULL", name="relationship_has_a_target"
        ),
    )

    op.create_table(
        "index_membership",
        # 'NGX30'|'NGXBNK'|'NGXCNSMR'|'NGXASI'|'SP500'
        sa.Column("index_code", sa.Text(), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("index_code", "security_id", "valid_from", "known_as_of"),
    )


def downgrade() -> None:
    for table in (
        "index_membership",
        "company_relationships",
        "shareholdings",
        "entity_roles",
        "persons",
    ):
        op.drop_table(table)
