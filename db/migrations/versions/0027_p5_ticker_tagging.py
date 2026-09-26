"""0027 - security_aliases and news_tags: which company an article is about. P5.2.

Revision ID: 0027_p5_ticker_tagging
Revises: 0026_p4_afx_kwayisi_source
Create Date: 2026-09-24

`docs/03` P5.2 and `docs/08` §2.6. Two tables, one purpose: turn a headline into a
`security_id` a watchlist can be filtered on. `docs/03` P5.2 states the bar in one
sentence - *"a false tag on a watchlist alert is the fastest way to make a brief
untrustworthy"* - and every decision below is weighted by which direction it errs in. A
missed tag costs one article out of a feed that publishes thirty an hour. A false tag puts
a company's name on news that is not about it, in a brief the owner reads before trading.
The two are not symmetric and the schema does not pretend they are.

`security_aliases` is labelled **P3** in `docs/08` §2.0's table map, not P5. It is overdue
rather than early, and P5.2 is the first task that cannot proceed without it.

## The `docs/08` contradiction about dating, and how it is resolved

`docs/08` §1.3 lists `valid_from`/`valid_to` as the columns for *"time-bounded attributes
such as tickers **and name aliases**"*, and its worked example is GTBank becoming GTCO in
2021. The `security_aliases` DDL in §2.6 has neither column. They cannot both be right.

**Decided: no dates on `security_aliases`.** The argument turns on what a row in each
table asserts.

* `security_identifiers.id_value` asserts *"this string identified this security on these
  dates"*. A ticker is **reassignable** - the exchange can and does hand `GUARANTY` to
  somebody else - so without dates the claim is false outside its window, and
  `packages/common/identity.py` exists to make every lookup carry one.
* `security_aliases.alias` asserts *"this string is a name people use for this company"*.
  A name is not reassigned by an exchange. "GTBank" meant Guaranty Trust in 2019, means it
  in a 2026 article written by a journalist who never updated their habits, and will still
  mean it in the archive. That is `alias_type = 'former'`, and it is a statement about
  usage rather than about a window.

Dating the alias would therefore *lose* tags without buying any accuracy: a 2026 article
saying "GTBank" would fall outside a `valid_to` of 2021-06-23 and go untagged, which is
the failure mode P5.2's first sentence is about, applied in the wrong direction.

The case §1.3 is actually describing - one string meaning company A and later company B -
is real, and it is already served: it is a **ticker**, it lives in `security_identifiers`
with its dates, and `resolve_security(value, as_of)` answers it. So the two tables divide
cleanly, and the tagger uses each for what it holds: `packages/normalize/tagging.py`
matches names out of `security_aliases` undated, and resolves a ticker mention through
`identity.resolve_security` with the article's own `known_as_of` as the date.

**The consequence to accept deliberately:** a genuinely reassigned *name* - a brand sold
from one listed company to another - cannot be represented here. If that ever happens the
fix is `valid_from`/`valid_to` on this table plus a dated load, not a hand-edit of the row,
and it should be a migration with this paragraph quoted in it.

**No ticker is copied into this table.** That is the same decision seen from the other
side: a ticker in an undated table is precisely the GUARANTY bug `identity.py` was written
to prevent, and `OPERATIONS.md` §1.4's rule - *"no `WHERE ticker = ?` anywhere else in the
codebase"* - would be defeated by a copy of the ticker under another column name.

## Where this deviates from `docs/08` §2.6, and why

The contract's DDL for `news_tags` is four columns keyed `(news_id, security_id)`:

    news_id, security_id, method TEXT ('alias'|'fuzzy'|'llm'), confidence NUMERIC

**`tagger_version` joins the primary key**, exactly as `model_version` does in
`news_sentiment` three DDL blocks above it, and for the reason §2.6 itself gives there:
*"re-scoring with a new model adds rows rather than destroying the old scores, so you can
compare."* A matcher is a model in every way that matters here. Under the contract's key,
improving the threshold would have to UPDATE the existing tag - the one write `CLAUDE.md`
forbids and the `no_update` trigger below rejects - or silently do nothing, which leaves a
tag written by code nobody can identify. `method` joins it for the same reason at a
smaller scale: the alias tier and a later LLM tier agreeing is two pieces of evidence, and
collapsing them into one row throws the second away.

**`matched_text` is added, and it is the column that makes a tag reviewable.** It holds the
exact substring of the article that caused the tag. A tag whose evidence cannot be seen
cannot be disproved, and an untrustworthy brief is exactly a brief whose claims cannot be
checked. It is also what keeps a tag honest when its alias row is later corrected: the
tag says what the article said, not what the alias table currently says.

**`alias_id` is added** so a reviewer can go from a wrong tag to the row that produced it
and fix the cause rather than the symptom. It is NULL for the `ticker` and `llm` tiers,
which cite no alias row, and the CHECK below makes that an equivalence rather than a
convention.

**`method` admits a fourth value, `ticker`.** `docs/08`'s three are alias, fuzzy and llm;
a ticker mention (`$CAT`, `(NYSE: CAT)`) is none of them. Recording it as `alias` would be
a provenance lie of exactly the kind this project's rules exist to stop - the evidence is a
symbol resolved through a dated identifier table, not a name found in an alias table, and a
reader deciding whether to trust the tag needs to know which. The CHECK names all four, so
a fifth cannot appear by typo.

**`source` on `security_aliases`** follows migration `0023`'s argument for the same column
on `trading_calendar`: an alias derived by a script from `companies.legal_name` and an
alias typed by a person are not equally strong, and without the column they are
indistinguishable.

## The constraints, and the one written the long way

`alias_cites_an_alias_row` is `(alias_id IS NOT NULL) = (method IN ('alias','fuzzy'))`.
Both sides are computed from NOT NULL columns, so the predicate is never NULL and the
constraint is total - which is the property migration `0021` is this repository's record of
not having. `0021` found a CHECK that rejected a *zero* ratio and admitted a *missing* one,
because a predicate over NULL evaluates to NULL and a CHECK rejects only FALSE. Every
nullable column touched below is therefore written `IS NULL OR <predicate>` or as an
equivalence between two non-nullable expressions, never as a bare comparison.

`confidence_is_a_probability` is `confidence > 0 AND confidence <= 1`. Strictly greater
than zero: a zero-confidence tag is a non-tag that still puts the company's name on the
article, with our own record saying we did not believe it.

`alias_is_long_enough` admits two characters, not three. The floor here is junk rejection;
the floor that protects against `"TOTAL" in headline` is a matching decision and lives in
`packages/normalize/tagging.py`, where it can be stated as "a short bare token needs a
corporate cue" rather than as "this row may not exist". "3M" is the name this distinction
was checked against.

`ux_security_aliases_one_per_security` is a unique index over
`(security_id, lower(btrim(alias)))` rather than the contract's `UNIQUE (alias,
security_id)`. The contract's form admits "GTCO" and "gtco" as two rows for one security,
which is not a second alias, it is the same alias counted twice - and the tagger folds case
before matching, so both would fire on one headline. The richer fold the matcher applies
(accents, punctuation, possessives) is deliberately **not** duplicated here: it has to agree
exactly with the fold applied to the article text, and a second implementation in SQL would
drift from the Python one the day either changed. `lower(btrim(...))` is what SQL can
express immutably and without a locale argument; the rest has one home and a test.

## `no_update` on `news_tags`, and none on `security_aliases`

A tag is an assertion a brief was built on, so it gets the trigger: `docs/08` §2.16's point
is that application code can be bypassed at 1am by somebody with `psql`, and a rewritten
confidence would mean the archive no longer says what the brief said.

`security_aliases` gets no trigger, which matches every other reference table in this
schema - `security_identifiers`, `chart_of_accounts`, `account_mappings`, `data_sources`
and `trading_calendar` all carry none, and `0023` argued the case for the last of them.
An alias is a curated claim about usage, not an observation, and it is corrected rather
than superseded. What keeps the correction honest is `matched_text` on the tag: the
evidence for a tag is the text of the article, which no edit to this table can change.

## What gets seeded, and what deliberately does not

One or two rows per **existing** security, derived from `companies.legal_name` and nothing
else:

* `alias_type='legal'` - the legal name with a registry artefact removed. EDGAR appends the
  state of incorporation, so `companies.legal_name` for security 9 is
  `BANK OF AMERICA CORP /DE/`; `/DE/` is Delaware, not part of the name.
* `alias_type='brand'` - the same with trailing legal-form words dropped
  (`Inc`, `Corp`, `Co`, `Plc`, `Ltd` and the rest of `LEGAL_FORM_SUFFIXES`), so
  `Apple Inc.` yields `Apple` and `JPMORGAN CHASE & CO` yields `JPMORGAN CHASE`. Emitted
  only when it differs from the legal form, so `JOHNSON & JOHNSON` gets one row.

**Nothing else is invented.** "GTBank", "Amazon", "J&J" and "Big Blue" are all real aliases
and none of them is derivable from a legal name by any rule that would not also produce
wrong ones. They are curation, and the table now exists to receive it; `alias_type` already
has `'former'` and `'colloquial'` waiting for them.

**Every security in this database is US-listed and NGX holds none**, so this seed tags
nothing Nigerian. That gap is the reason `packages/normalize/tagging.py` has
`alias_coverage()` and logs a warning naming each exchange that cannot produce a tag: a
tagger that silently returns nothing for every Nigerian article looks exactly like a
tagger that is working.

**Securities created after this migration get no aliases from it.** The EDGAR connector
creates companies at runtime, so the next registrant it loads arrives unaliased.
`packages.normalize.tagging.seed_aliases_for()` is the same derivation as a callable, and
`alias_coverage()` is what reports the shortfall until somebody calls it.

On a freshly migrated **test** database `companies` is empty - the 24 securities were
loaded by the EDGAR connector, not by a migration - so this seed inserts nothing there and
the tests seed their own rows.

**The derivation is written out again here rather than imported.** A migration is pinned to
a moment in the schema's history and must keep running after the module it was written
beside has been renamed or rewritten; no migration in this repository imports from
`packages`. The duplication is made safe by
`tests/unit/test_tagging.py::test_the_migration_and_the_module_derive_the_same_aliases`,
which loads this file and asserts the two rules agree name for name.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_p5_ticker_tagging"
down_revision: str | None = "0026_p4_afx_kwayisi_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIASES = "security_aliases"
TAGS = "news_tags"

#: `docs/08` §2.6's vocabulary for `alias_type`, verbatim. `legal` is the registered name,
#: `brand` the trading name, `former` a name the company has stopped using but the press
#: has not, `colloquial` what people actually type.
ALIAS_TYPES = ("legal", "brand", "former", "colloquial")

#: `docs/08` §2.6's three, plus `ticker`. The deviation is argued in the module docstring:
#: a symbol resolved through the dated identifier table is different evidence from a name
#: found in the alias table, and a reader deciding whether to trust the tag needs to know.
TAG_METHODS = ("alias", "fuzzy", "ticker", "llm")

#: Trailing words that say what *kind* of company this is rather than *which* company it
#: is. Dropped from the end of a legal name to derive the brand form, only from the end and
#: only as whole words.
#:
#: `Holding`/`Holdings` and `Group` are deliberately absent. They read like legal forms and
#: are not: "Guaranty Trust Holding" and "UnitedHealth Group" are what people write, and
#: stripping them would leave "Guaranty Trust" and "UnitedHealth" - shorter, more
#: ambiguous, and no more correct. The rule strips what the registrar added, not what the
#: company calls itself.
LEGAL_FORM_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "companies",
        "plc",
        "ltd",
        "limited",
        "llc",
        "lp",
        "llp",
        "nv",
        "sa",
        "ag",
        "gmbh",
    }
)

#: EDGAR appends the state of incorporation to a registrant's conformed name:
#: `BANK OF AMERICA CORP /DE/`. It is a registry artefact, not part of the name, and it
#: would never appear in a headline.
_REGISTRY_ARTEFACT = re.compile(r"\s*/[A-Za-z]{2}/\s*$")

#: Punctuation left dangling once a trailing legal form is removed: `Meta Platforms,` and
#: `JPMORGAN CHASE &`.
_DANGLING = " ,.;:-&"

#: What `security_aliases.source` records for a row this migration wrote. The convention is
#: `<how>:<from where>`; a hand-curated row would read `manual:<who>`.
SEED_SOURCE = "derived:companies.legal_name"


def _sql_in_list(values: Sequence[str]) -> str:
    """`('a','b')` - the right-hand side of an `IN` in a CHECK, from a Python tuple."""
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _legal_form(name: str) -> str:
    """The legal name as it would be written, registry artefacts removed."""
    return _REGISTRY_ARTEFACT.sub("", name).strip()


def _brand_form(name: str) -> str:
    """The legal name with trailing legal-form words dropped. `Apple Inc.` -> `Apple`.

    Compared word by word against `LEGAL_FORM_SUFFIXES` after stripping the word's own
    punctuation, so `Inc.` and `INC` and `inc,` are all the same word. A word that reduces
    to nothing - a bare `&` - is dropped too, because it is only there to join the two
    words around it and one of them has just gone.
    """
    words = _legal_form(name).split()
    while words:
        bare = re.sub(r"[^0-9a-z]", "", words[-1].casefold())
        if bare and bare not in LEGAL_FORM_SUFFIXES:
            break
        words.pop()
    return " ".join(words).strip(_DANGLING)


def derived_aliases(legal_name: str) -> list[tuple[str, str]]:
    """`[(alias, alias_type)]` for one company name. The whole of what this seed invents.

    The brand form is emitted only when it differs from the legal form, so a name carrying
    no legal-form suffix - `JOHNSON & JOHNSON` - produces one row rather than a duplicate.
    """
    legal = _legal_form(legal_name)
    if not legal:
        return []
    out = [(legal, "legal")]
    brand = _brand_form(legal_name)
    if brand and brand.casefold() != legal.casefold():
        out.append((brand, "brand"))
    return out


def upgrade() -> None:
    op.create_table(
        ALIASES,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        # A name people use for this company. Undated on purpose - see the module docstring.
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_type", sa.Text(), nullable=False),
        # Where the row came from: `derived:companies.legal_name`, `manual:<who>`. An alias
        # a script inferred and an alias a person vouched for are not equally strong
        # (migration 0023 made the same argument for `trading_calendar.source`).
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "alias_type IN " + _sql_in_list(ALIAS_TYPES), name="alias_type_is_in_the_contract"
        ),
        sa.CheckConstraint("btrim(alias) <> ''", name="alias_is_not_blank"),
        # Junk rejection, not match safety. A one-character alias names nothing; "3M" is
        # why the floor is two and not three. The rule that stops a short bare token
        # matching ordinary prose is in `packages/normalize/tagging.py`, where it can
        # require a corporate cue instead of refusing the row.
        sa.CheckConstraint("char_length(btrim(alias)) >= 2", name="alias_is_long_enough"),
        sa.CheckConstraint("btrim(source) <> ''", name="alias_source_is_not_blank"),
    )
    # "GTCO" and "gtco" are one alias, not two: the matcher folds case before comparing, so
    # both would fire on one headline and the article would carry the company twice.
    op.create_index(
        "ux_security_aliases_one_per_security",
        ALIASES,
        ["security_id", sa.text("lower(btrim(alias))")],
        unique=True,
    )
    # The tagger's own query: every alias, once per run, ordered so the load is stable.
    op.create_index("ix_security_aliases_security", ALIASES, ["security_id"])

    op.create_table(
        TAGS,
        sa.Column("news_id", sa.BigInteger(), sa.ForeignKey("news_items.id"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        # What the tag means is one number on one scale for every method:
        # `packages/normalize/tagging.py` defines it as the estimated probability that the
        # tag is correct, and pins each tier's value to a stated argument.
        sa.Column("confidence", sa.Numeric(), nullable=False),
        # The exact substring of the article that caused this tag. The column that makes a
        # tag reviewable, and the one that keeps it honest if its alias row is later
        # corrected.
        sa.Column("matched_text", sa.Text(), nullable=False),
        # Which alias row fired. NULL for `ticker` and `llm`, which cite no alias row.
        sa.Column("alias_id", sa.Integer(), sa.ForeignKey("security_aliases.id"), nullable=True),
        # Which matcher said so. In the key, like `news_sentiment.model_version`: a better
        # matcher adds rows and the old ones stay comparable.
        sa.Column("tagger_version", sa.Text(), nullable=False),
        # When we asserted it. Provenance only - the point-in-time date of a tag is the
        # article's `news_items.known_as_of`, never this (`docs/08` §1.3).
        sa.Column(
            "tagged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "news_id", "security_id", "method", "tagger_version", name="news_tags_pkey"
        ),
        sa.CheckConstraint(
            "method IN " + _sql_in_list(TAG_METHODS), name="tag_method_is_in_the_contract"
        ),
        # Strictly above zero: a zero-confidence tag still prints the company's name, with
        # our own record saying we did not believe it.
        sa.CheckConstraint(
            "confidence > 0 AND confidence <= 1", name="tag_confidence_is_a_probability"
        ),
        sa.CheckConstraint("btrim(matched_text) <> ''", name="tag_matched_text_is_not_blank"),
        sa.CheckConstraint("btrim(tagger_version) <> ''", name="tag_tagger_version_is_not_blank"),
        # An equivalence between two expressions over NOT NULL columns, so it is never
        # NULL and therefore never silently satisfied - migration 0021 is the record of
        # what a CHECK that can evaluate to NULL costs.
        sa.CheckConstraint(
            "(alias_id IS NOT NULL) = (method IN ('alias','fuzzy'))",
            name="tag_cites_an_alias_row_iff_it_matched_one",
        ),
    )
    # The watchlist query: every article tagged to this security, newest article first.
    op.create_index("ix_news_tags_security", TAGS, ["security_id", "news_id"])
    op.execute(
        f"CREATE TRIGGER no_update BEFORE UPDATE ON {TAGS} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )

    _seed_aliases()


def _seed_aliases() -> None:
    """One or two rows per existing security, derived from its company's legal name.

    Inserts nothing when `companies` is empty, which is the state of a freshly migrated
    test database - the securities in the dev database were loaded by the EDGAR connector
    at runtime and by no migration.
    """
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT s.id AS security_id, c.legal_name "
            "FROM securities s JOIN companies c ON c.id = s.company_id "
            "ORDER BY s.id"
        )
    ).all()
    seeds: list[dict[str, object]] = []
    for security_id, legal_name in rows:
        seen: set[str] = set()
        for alias, alias_type in derived_aliases(legal_name):
            # The unique index folds case; two derivations that differ only in case would
            # be one row and the second insert would fail the whole migration.
            if alias.casefold() in seen:
                continue
            seen.add(alias.casefold())
            seeds.append(
                {
                    "security_id": security_id,
                    "alias": alias,
                    "alias_type": alias_type,
                    "source": SEED_SOURCE,
                }
            )
    if not seeds:
        return
    op.bulk_insert(
        sa.table(
            ALIASES,
            sa.column("security_id", sa.Integer),
            sa.column("alias", sa.Text),
            sa.column("alias_type", sa.Text),
            sa.column("source", sa.Text),
        ),
        seeds,
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS no_update ON {TAGS};")
    # Tags first: they hold the foreign key into the aliases.
    op.drop_table(TAGS)
    op.drop_table(ALIASES)
