"""Which security an article is about. P5.2.

`docs/03` P5.2 asks for *"your own alias table plus fuzzy matching plus LLM entity
extraction"*, and states the bar in one sentence:

> "GTCO", "Guaranty Trust", and "GTBank" are the same company; a naive string match gets
> this wrong in both directions, and **a false tag on a watchlist alert is the fastest way
> to make a brief untrustworthy.**

Both directions matter and they do not cost the same. A missed tag loses one article out
of a feed that publishes thirty an hour and can be recovered by re-running a better matcher
over stored rows. A false tag puts a company's name on news that is not about it, inside a
brief the owner reads before trading, and the only way to find it is to already distrust
the brief. So every rule below is stated with the direction it errs in, and where the two
conflict, precision wins.

## The four tiers, and what each one refuses

* **`alias`** - a name out of `security_aliases`, matched as whole words with case,
  punctuation, accents and possessives folded away. *Refuses* a bare one-word alias that
  is short or is ordinary English, unless a corporate cue sits beside it.
* **`ticker`** - `$CAT`, `(NYSE: CAT)`: a symbol carrying a cue that says it is a symbol,
  resolved on the article's own date. *Refuses* a bare uppercase symbol, and refuses a
  symbol two exchanges both answer.
* **`fuzzy`** - `difflib` similarity over a token window, above :data:`FUZZY_THRESHOLD`.
  *Refuses* any alias shorter than :data:`FUZZY_MIN_ALIAS_CHARS`, and refuses any run of
  text that two different companies both clear the threshold on.
* **`llm`** - a span the model says names a company, then resolved by the tiers above.
  *Refuses* a span that is not in the article, and a span that resolves to nothing.

The refusals are the design. A tagger that fires on everything it can is the naive string
match P5.2 names, with more code.

**What the deterministic tiers deliberately give up:** a bare uppercase ticker in prose -
"GTCO rose 3%", "CAT fell" - is not matched. `CAT` is also a scan, `KO` is also a knockout,
`HD` is also a video format, `PG` is also a film rating, and every one of those reaches a
financial feed. Distinguishing them needs the sentence, not the token, which is exactly the
job the `llm` tier exists for and the reason the `EntityExtractor` Protocol resolves through
this module rather than around it.

## `confidence`, and what it means

One scale for every method: **the estimated probability that the tag is correct.** It is a
number we are willing to defend from a stated argument, not a measured frequency - there is
no labelled corpus yet, and inventing a calibration would be the kind of plausible-looking
figure this project exists to avoid. What the single scale buys is that a brief can sort
and threshold tags from different tiers against each other without a lookup table.

The bands, and why each sits where it does:

* :data:`ALIAS_MULTI_TOKEN_CONFIDENCE` **0.99** - two or more whole words matching a
  registered name exactly. Not 1.0: nothing here is certain, and reserving 1.0 keeps the
  scale honest.
* :data:`TICKER_EXCHANGE_CONFIDENCE` **0.97** - `(NYSE: CAT)`. Unambiguous by construction,
  but one tier below a name because a typo in a four-letter symbol is still a valid symbol.
* :data:`TICKER_CASHTAG_CONFIDENCE` **0.93** - `$CAT`. The same evidence without the
  exchange, so a cross-listed string is resolved by date alone.
* :data:`ALIAS_SINGLE_TOKEN_CONFIDENCE` **0.90** - one word. "Walmart" is a coined word and
  "Apple" is a fruit, and the tier does not pretend to tell them apart beyond
  :data:`AMBIGUOUS_SINGLE_TOKENS`; the number carries that residual risk for both.
* fuzzy **0.70 - 0.89** - the `difflib` ratio **mapped** onto this scale, never used raw. A
  0.90 string similarity is not a 0.90 probability of being the same company. The mapping
  puts the whole tier strictly below every exact match, which is the ordering a brief
  needs: a guess never outranks something we can point at.
* llm **up to** :data:`LLM_MAX_CONFIDENCE` **0.85** - the model's own number, clamped. An
  uncalibrated self-report is evidence of the model's disposition, not a probability, and
  it must not outrank a substring we can show a reader.

The bands for `fuzzy` and `llm` overlap on purpose. They are the same quantity measured two
ways, and a model that reads the sentence can legitimately be better evidence than an 0.88
string match.

## The threshold, measured rather than chosen

:data:`FUZZY_THRESHOLD` is 0.88, and the two bounds that pin it were measured on
2026-09-24 over this database's 24 securities plus the NGX names P3 will load.

* **Floor.** The highest `difflib` ratio between aliases of two *different* securities was
  **0.8276**, for `'unity bank plc'` against `'zenith bank plc'`. Any threshold at or below
  that merges two real Nigerian banks, which is the false tag in its purest form.
  `tests/unit/test_tagging.py::test_no_two_securities_aliases_collide_at_the_threshold`
  recomputes this over whatever `security_aliases` actually holds and fails the day a
  seeded alias gets close, so the figure cannot rot.
* **Ceiling.** The variants people actually write scored 0.907 to 0.984:
  `'jp morgan chase'` 0.966, `'proctor gamble'` 0.929, `'united health group'` 0.973,
  `'nigeria breweries'` 0.971, `'caterpiller'` 0.909. A threshold above ~0.90 starts losing
  one-letter typos and the split-word case.

0.88 sits in the gap with 0.052 of margin above the worst measured collision and 0.027
below the cheapest variant worth keeping - deliberately weighted towards precision.

:data:`FUZZY_MIN_ALIAS_CHARS` is **derived from** the threshold rather than chosen
separately. A single substituted character in a string of length n gives a ratio of
(n-1)/n, so the tier can only ever see a one-character typo once n >= 1/(1 - threshold) -
nine characters at 0.88. Below that the tier cannot fire on a typo at all; it can only fire
on differences *larger* than one character, which are different words rather than
misspellings. `'apple'`/`'ample'` is 0.80, `'intel'`/`'intl'` is 0.889 - the second would
clear the threshold, and `Intl Breweries` tagging Intel is exactly the bug the floor stops.

## What this module is not allowed to do

`OPERATIONS.md` §1.4: *"All ticker resolution goes through a single `resolve_security(...)`
function; no `WHERE ticker = ?` anywhere else in the codebase."*
`tests/unit/test_identity.py::test_only_the_identity_module_queries_the_identity_table`
walks the AST of the repository to keep it so. The `ticker` tier therefore calls
`packages.common.identity.resolve_security` with the article's own `known_as_of`, and
`security_aliases` holds no ticker at all - migration 0027 argues why at length.
"""

from __future__ import annotations

import datetime as dt
import difflib
import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.identity import TICKER, AmbiguousIdentifierError, resolve_security
from packages.common.models import Exchange, NewsItem, NewsTag, Security, SecurityAlias

__all__ = [
    "ALIAS",
    "ALIAS_MULTI_TOKEN_CONFIDENCE",
    "ALIAS_SINGLE_TOKEN_CONFIDENCE",
    "AMBIGUOUS_SINGLE_TOKENS",
    "FUZZY",
    "FUZZY_MAX_CONFIDENCE",
    "FUZZY_MIN_ALIAS_CHARS",
    "FUZZY_MIN_CONFIDENCE",
    "FUZZY_THRESHOLD",
    "LEGAL_FORM_SUFFIXES",
    "LEGAL_FORM_TOKENS",
    "LLM",
    "LLM_MAX_CONFIDENCE",
    "LLM_MIN_CONFIDENCE",
    "METHODS",
    "MIN_UNCUED_SINGLE_TOKEN_CHARS",
    "TAGGER_VERSION",
    "TICKER_CASHTAG_CONFIDENCE",
    "TICKER_EXCHANGE_CONFIDENCE",
    "TICKER_TAG",
    "AliasRecord",
    "CandidateTag",
    "EntityExtractor",
    "EntityMention",
    "ExchangeCoverage",
    "TaggingReport",
    "TickerMention",
    "Token",
    "alias_coverage",
    "derive_aliases",
    "exchange_codes",
    "fold",
    "load_aliases",
    "match_aliases",
    "normalise",
    "seed_aliases_for",
    "store_tags",
    "tag_article",
    "tag_articles",
    "ticker_mentions",
    "tokenise",
]

_log = structlog.get_logger(__name__)

#: `news_tags.method`. `docs/08` §2.6 names the first three; `ticker` is migration 0027's
#: documented fourth, because a symbol resolved through the dated identifier table is not
#: a name found in the alias table and a reader needs to know which they are trusting.
ALIAS = "alias"
FUZZY = "fuzzy"
TICKER_TAG = "ticker"
LLM = "llm"
METHODS = (ALIAS, FUZZY, TICKER_TAG, LLM)

#: Stamped on every row and part of `news_tags`' primary key, so a better matcher adds
#: rows instead of overwriting the ones a brief was built on. **Bump it whenever a
#: constant in this module changes which articles match** - the same discipline as
#: `packages.extract.reconciler.PROMPT_VERSION`, and for the same reason: an unchanged
#: version against changed behaviour makes two incomparable runs look like one.
TAGGER_VERSION = "p5.2-v1"

# --------------------------------------------------------------------------------------
# Confidence. One scale - the estimated probability that the tag is correct - for four
# tiers. The module docstring argues each band; the constants carry the one-line version.
# --------------------------------------------------------------------------------------

#: Two or more whole words matching a registered name exactly. Not 1.0, because nothing
#: here is certain and a scale with a reachable maximum stops meaning anything.
ALIAS_MULTI_TOKEN_CONFIDENCE = 0.99

#: `(NYSE: CAT)`. Unambiguous by construction, but one band below a name: a typo in a
#: four-letter symbol is still a valid symbol, whereas a typo in a name is not a name.
TICKER_EXCHANGE_CONFIDENCE = 0.97

#: `$CAT`. The same evidence without the exchange, so a string listed on two markets is
#: separated by date alone - and by the refusal in `_resolve_ticker` when even that fails.
TICKER_CASHTAG_CONFIDENCE = 0.93

#: One word. "Walmart" is coined and "Apple" is a fruit; beyond
#: :data:`AMBIGUOUS_SINGLE_TOKENS` this tier does not tell them apart, and the number
#: carries that residual risk for both.
ALIAS_SINGLE_TOKEN_CONFIDENCE = 0.90

#: Measured, not chosen. Floor: the highest similarity between two *different* securities'
#: aliases in the seedable universe was 0.8276 ('unity bank plc' vs 'zenith bank plc').
#: Ceiling: the variants people write scored 0.907-0.984. See the module docstring, and
#: `test_no_two_securities_aliases_collide_at_the_threshold`, which re-measures the floor
#: against whatever the table actually holds.
FUZZY_THRESHOLD = 0.88

#: The `difflib` ratio is mapped into this band rather than used raw: a 0.90 string
#: similarity is not a 0.90 probability of being the same company. The band sits strictly
#: below every exact match, so a guess never outranks something we can point at.
FUZZY_MIN_CONFIDENCE = 0.70
FUZZY_MAX_CONFIDENCE = 0.89

#: **Derived from** :data:`FUZZY_THRESHOLD`, not chosen beside it. One substituted
#: character in a string of length n gives a ratio of (n-1)/n, so a one-character typo can
#: only clear the threshold once n >= 1/(1 - threshold): nine characters at 0.88. Shorter
#: aliases are excluded from the tier entirely, because below that length the only things
#: that clear the bar are different words - 'intel' against 'intl' scores 0.889.
FUZZY_MIN_ALIAS_CHARS = math.ceil(1 / (1 - FUZZY_THRESHOLD))

#: The model's own number is clamped into this band. An uncalibrated self-report is
#: evidence of the model's disposition, not a probability; the cap keeps it below every
#: exact match, and the floor drops a mention the model itself did not believe.
LLM_MAX_CONFIDENCE = 0.85
LLM_MIN_CONFIDENCE = 0.50

#: How many decimal places a confidence is stored to. `news_tags.confidence` is NUMERIC ->
#: `Decimal` (`docs/08` §1.6), and rounding at the boundary makes a re-run byte-identical
#: rather than differing in the sixteenth place for reasons nobody can see.
CONFIDENCE_PLACES = Decimal("0.0001")

# --------------------------------------------------------------------------------------
# The false-positive guards. Everything here costs recall and buys precision, which is the
# trade `docs/03` P5.2 asks for explicitly.
# --------------------------------------------------------------------------------------

#: A single-token alias shorter than this needs a corporate cue beside it before it fires.
#: Every ticker-shaped collision in ordinary prose is short - KO is a knockout, HD is a
#: video format, PG is a film rating, CAT is a scan, DIS and ALL and ON and IT are words -
#: and a bare three-letter token in a headline is more often an abbreviation than a company.
#: Four rather than three so that "BUA" and "MTN" still need the cue their brand names
#: ("BUA Cement", "MTN Nigeria") supply anyway.
MIN_UNCUED_SINGLE_TOKEN_CHARS = 4

#: Single-word aliases whose ordinary-English sense turns up in financial prose. Each one
#: fires only with a corporate cue beside it, so "Apple Inc" tags and "apple harvest" does
#: not. **This is not a dictionary and it is knowingly incomplete** - an entry costs recall
#: on that company, an omission costs precision, and the omission is the expensive one.
#: `tests/unit/test_tagging.py::test_every_single_token_brand_the_seed_derives_is_classified`
#: pins it against the aliases the seed actually produces, so a new security that derives a
#: risky single word fails the build rather than quietly tagging the wrong articles.
AMBIGUOUS_SINGLE_TOKENS = frozenset(
    {
        # Produced by the current seed from `companies.legal_name`.
        "apple",  # the fruit
        "alphabet",  # the letters
        "intel",  # market intel
        "oracle",  # a prophet; "the oracle of Omaha" is a finance idiom
        # `docs/03` P5.2's own worked example, and the NGX names P3 will load beside it.
        "total",
        "access",
        "union",
        "unity",
        "first",
        "fidelity",
        "sterling",  # also a currency, which is worse
        "champion",
        "custodian",
        "cornerstone",
        # Generic nouns of financial prose. A single-word alias equal to one of these is a
        # false-tag generator whatever company registered it.
        "capital",
        "energy",
        "equity",
        "global",
        "group",
        "growth",
        "holdings",
        "industrial",
        "international",
        "mutual",
        "premier",
        "prime",
        "royal",
        "sovereign",
        "standard",
        "transport",
        "trust",
    }
)

#: The corporate cue. A risky single-token alias fires when one of these sits immediately
#: beside it: "Apple Inc" is the company, "apple harvest" is not. Immediate adjacency only,
#: because a legal form four words away is a coincidence rather than a cue.
LEGAL_FORM_TOKENS = frozenset(
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

#: Trailing words dropped from a legal name to derive the brand form. The same set as
#: :data:`LEGAL_FORM_TOKENS` because it is the same idea - words that say what kind of
#: company this is rather than which one. `Holdings` and `Group` are deliberately absent
#: from both: "UnitedHealth Group" is what people write, and stripping it would leave
#: something shorter, more ambiguous and no more correct.
LEGAL_FORM_SUFFIXES = LEGAL_FORM_TOKENS

#: EDGAR appends the state of incorporation to a conformed name - `BANK OF AMERICA CORP
#: /DE/`. A registry artefact, not part of the name, and it never appears in a headline.
_REGISTRY_ARTEFACT = re.compile(r"\s*/[A-Za-z]{2}/\s*$")

#: Punctuation left dangling once a trailing legal form goes: `Meta Platforms,` and
#: `JPMORGAN CHASE &`.
_DANGLING = " ,.;:-&"

#: A run of alphanumerics, Unicode-aware, underscore excluded. Everything between runs is a
#: token boundary, which is what makes "total" unable to match inside "totally" without a
#: single word-boundary assertion anywhere in this module.
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

#: Straight, curly and modifier apostrophes. `GTCO's` is one mention, not a mention plus a
#: stray `s` that would widen every fuzzy window around it by a token.
_APOSTROPHES = "'’ʼ"

#: `$CAT`. Upper case in the source text is required: `$cat` is not a cashtag, and the
#: symbol must start with a letter so `$50m` is a sum of money.
_CASHTAG = re.compile(r"\$([A-Z][A-Z0-9]{0,5})\b")


@dataclass(frozen=True)
class Token:
    """One folded word, and where it sits in the text it was folded from.

    The offsets are what let a tag carry `matched_text` - the article's own characters,
    with its own capitals and punctuation - rather than the folded form nobody wrote.
    """

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class AliasRecord:
    """One `security_aliases` row, pre-folded for matching.

    `company_id` rides along because ambiguity is a question about *companies*, not
    securities: two share classes of one issuer matching the same span is one company
    mentioned once, and two different issuers matching it is a collision that must tag
    neither.
    """

    alias_id: int
    security_id: int
    company_id: int
    alias: str
    alias_type: str
    #: The folded words of `alias`, in order. The matching key.
    tokens: tuple[str, ...]

    @property
    def normalised(self) -> str:
        return " ".join(self.tokens)


@dataclass(frozen=True)
class CandidateTag:
    """One tag, before it is written. Everything `news_tags` needs and nothing else."""

    security_id: int
    method: str
    confidence: float
    #: The article's own characters that caused this. `news_tags.matched_text`.
    matched_text: str
    alias_id: int | None = None

    def as_row(self, *, news_id: int, tagger_version: str) -> dict[str, object]:
        return {
            "news_id": news_id,
            "security_id": self.security_id,
            "method": self.method,
            "tagger_version": tagger_version,
            "confidence": Decimal(repr(self.confidence)).quantize(CONFIDENCE_PLACES),
            "matched_text": self.matched_text,
            "alias_id": self.alias_id,
        }


@dataclass(frozen=True)
class TickerMention:
    """A symbol in the text with a cue that says it is a symbol, not a word."""

    symbol: str
    #: The exchange code the text named, or None for a bare cashtag.
    exchange: str | None
    matched_text: str
    start: int
    end: int
    confidence: float


@dataclass(frozen=True)
class EntityMention:
    """A span the model says names a company, and how sure it says it is.

    Deliberately a **string**, never a `security_id`. A model that returns an id can
    invent a company into a brief; a model that returns a span it read out of the article
    can only propose something this module then has to resolve deterministically, and a
    proposal that resolves to nothing is dropped.
    """

    text: str
    confidence: float


@runtime_checkable
class EntityExtractor(Protocol):
    """The one tier that needs an API key. `packages.extract.pipeline.Reconciler`'s shape.

    Deliberately narrow, and deliberately *upstream* of resolution. It is handed the
    article and returns spans; it does not see the alias table, does not choose a
    `security_id`, and does not write anything. Everything it proposes is checked twice by
    code that does not share its opinions: the span must actually occur in the article
    (`_grounded`), and it must then resolve through the same alias and ticker machinery the
    deterministic tiers use.

    What it buys is the case the deterministic tiers refuse on purpose - a bare uppercase
    ticker, a one-word company name with no legal form beside it - because telling "CAT
    shares" from "CAT scan" needs the sentence. Inside `_llm_tags` those refusals are
    relaxed, and the confidence cap is what pays for relaxing them.

    `runtime_checkable` so a test can assert an implementation satisfies it. That checks
    only that the members exist, which is enough to catch the drift that would otherwise
    surface as an `AttributeError` the first time a key exists and nobody is watching.
    """

    model_name: str
    prompt_version: str

    def mentions(self, headline: str, body: str | None) -> Sequence[EntityMention]:
        """Spans of this article that name a company, with the model's own confidence."""
        ...


@dataclass(frozen=True)
class ExchangeCoverage:
    """How much of one exchange the tagger can actually reach.

    Exists so the NGX hole is a number in a report rather than an empty result set. A
    tagger that returns nothing for every Nigerian article looks exactly like a tagger
    that is working.
    """

    exchange: str
    securities: int
    securities_with_alias: int
    aliases: int

    @property
    def untaggable(self) -> str | None:
        """Why no article can be tagged to this exchange, or None if one can."""
        if self.securities == 0:
            return "no securities are loaded for this exchange"
        if self.securities_with_alias == 0:
            return f"none of its {self.securities} securities carries an alias"
        return None


@dataclass(frozen=True)
class TaggingReport:
    """What one run over a batch of articles did, and what it could not reach."""

    articles: int
    tagged: int
    tags_written: int
    aliases_loaded: int
    coverage: tuple[ExchangeCoverage, ...]

    @property
    def untagged(self) -> int:
        return self.articles - self.tagged

    @property
    def unreachable(self) -> tuple[str, ...]:
        """Exchange codes no article could have been tagged to, whatever it said."""
        return tuple(c.exchange for c in self.coverage if c.untaggable is not None)


# --------------------------------------------------------------------------------------
# Folding. One implementation, because it has to agree with itself across the alias and
# the article - two folds that differ by an apostrophe is a tier that silently stops firing.
# --------------------------------------------------------------------------------------


def fold(value: str) -> str:
    """One word, comparably. Accents decomposed and dropped, then case-folded.

    NFKD then dropping combining marks is what turns `Nestlé` into `nestle`, so an article
    that spells the accent and an alias that does not are one string. `casefold` rather
    than `lower` because it is the one defined for comparison.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def tokenise(text: str) -> tuple[Token, ...]:
    """The text as folded words, each remembering where it came from.

    Punctuation, hyphens, ampersands and periods are boundaries rather than characters, so
    `Coca-Cola`, `Coca Cola` and `COCA-COLA's` all tokenise to the same two words - and
    `total` cannot match inside `totally`, because a token is a whole word by construction
    rather than by a boundary assertion somebody has to remember to write.

    The `s` of a possessive is dropped. `GTCO's` is one mention; keeping the `s` would add
    a token to every fuzzy window that reaches across it.
    """
    tokens: list[Token] = []
    for match in _WORD.finditer(text):
        raw = match.group()
        if (
            len(raw) == 1
            and raw.casefold() == "s"
            and match.start() > 0
            and text[match.start() - 1] in _APOSTROPHES
        ):
            continue
        folded = fold(raw)
        if folded:
            tokens.append(Token(folded, match.start(), match.end()))
    return tuple(tokens)


def normalise(value: str) -> str:
    """The folded words of `value`, space separated. What fuzzy similarity is measured on."""
    return " ".join(token.text for token in tokenise(value))


# --------------------------------------------------------------------------------------
# Deriving aliases from what the database already knows
# --------------------------------------------------------------------------------------


def derive_aliases(legal_name: str) -> list[tuple[str, str]]:
    """`[(alias, alias_type)]` derivable from a company's legal name, and nothing more.

    Two rules, both reversible by eye:

    * `legal` - the name with the EDGAR state-of-incorporation artefact removed, so
      `BANK OF AMERICA CORP /DE/` becomes `BANK OF AMERICA CORP`.
    * `brand` - the same with trailing legal-form words dropped, so `Apple Inc.` becomes
      `Apple` and `JPMORGAN CHASE & CO` becomes `JPMORGAN CHASE`. Emitted only when it
      differs, so `JOHNSON & JOHNSON` yields one row rather than a duplicate.

    **Nothing else is invented.** "GTBank", "Amazon", "J&J" and "Big Blue" are all real
    aliases and not one of them follows from a legal name by a rule that would not also
    produce wrong ones. They are curation, and `alias_type` already has `former` and
    `colloquial` waiting to receive them.

    Migration 0027 carries a frozen copy of this rule, because a migration may not import
    application code. `test_the_migration_and_the_module_derive_the_same_aliases` is what
    keeps the two honest.
    """
    legal = _REGISTRY_ARTEFACT.sub("", legal_name).strip()
    if not legal:
        return []
    out = [(legal, "legal")]
    brand = _brand_form(legal)
    if brand and brand.casefold() != legal.casefold():
        out.append((brand, "brand"))
    return out


def _brand_form(legal: str) -> str:
    """Trailing legal-form words removed, one at a time, stopping at the first real word."""
    words = legal.split()
    while words:
        bare = re.sub(r"[^0-9a-z]", "", words[-1].casefold())
        if bare and bare not in LEGAL_FORM_SUFFIXES:
            break
        words.pop()
    return " ".join(words).strip(_DANGLING)


def seed_aliases_for(session: Session, *, security_id: int, legal_name: str, source: str) -> int:
    """Insert the derivable aliases for one security. Returns how many were new.

    Migration 0027 seeded the securities that existed when it ran. The EDGAR connector
    creates companies at runtime, so the next registrant it loads arrives unaliased; this
    is the same derivation as a callable, for whatever eventually closes that loop.
    Conflicts are skipped rather than overwritten - `CLAUDE.md`, no silent overwrites.
    """
    rows = [
        {
            "security_id": security_id,
            "alias": alias,
            "alias_type": alias_type,
            "source": source,
        }
        for alias, alias_type in derive_aliases(legal_name)
    ]
    if not rows:
        return 0
    statement = (
        pg_insert(SecurityAlias)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[
                SecurityAlias.security_id,
                func.lower(func.btrim(SecurityAlias.alias)),
            ]
        )
        .returning(SecurityAlias.id)
    )
    return len(session.execute(statement).fetchall())


# --------------------------------------------------------------------------------------
# Reading the tables
# --------------------------------------------------------------------------------------


def load_aliases(session: Session) -> tuple[AliasRecord, ...]:
    """Every alias, folded once, for reuse across a whole batch of articles.

    An alias whose fold is empty - punctuation only, which the CHECK constraints make hard
    but not impossible - is dropped with a warning rather than silently matching the empty
    token sequence at every position in every article.
    """
    rows = session.execute(
        select(
            SecurityAlias.id,
            SecurityAlias.security_id,
            Security.company_id,
            SecurityAlias.alias,
            SecurityAlias.alias_type,
        )
        .join(Security, Security.id == SecurityAlias.security_id)
        .order_by(SecurityAlias.id)
    ).all()
    records: list[AliasRecord] = []
    for alias_id, security_id, company_id, alias, alias_type in rows:
        tokens = tuple(token.text for token in tokenise(alias))
        if not tokens:
            _log.warning("tagging.alias_folds_to_nothing", alias_id=alias_id, alias=alias)
            continue
        records.append(
            AliasRecord(
                alias_id=alias_id,
                security_id=security_id,
                company_id=company_id,
                alias=alias,
                alias_type=alias_type,
                tokens=tokens,
            )
        )
    return tuple(records)


def exchange_codes(session: Session) -> frozenset[str]:
    """The exchange codes this database knows, for the `(NYSE: CAT)` cue.

    Read rather than hardcoded, so the cue vocabulary cannot drift from the venues that
    exist. A qualifier we do not recognise - `LSE:`, or India's `NSE:` - is treated as no
    qualifier at all, which sends the symbol down the ambiguity-refusing path instead of
    guessing a market.
    """
    return frozenset(session.execute(select(Exchange.code)).scalars())


def alias_coverage(session: Session) -> tuple[ExchangeCoverage, ...]:
    """Per exchange: securities, how many carry an alias, how many aliases in total.

    The loud version of the gap. Today NGX answers `(0, 0, 0)`, so no Nigerian article can
    be tagged to anything - and the three RSS feeds P5.1 ingests are all Nigerian. Without
    this, that state is indistinguishable from a working tagger reading quiet feeds.
    """
    aliased = (
        select(SecurityAlias.security_id, func.count().label("n"))
        .group_by(SecurityAlias.security_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Exchange.code,
            func.count(Security.id),
            func.count(aliased.c.security_id),
            func.coalesce(func.sum(aliased.c.n), 0),
        )
        .select_from(Exchange)
        .join(Security, Security.exchange_id == Exchange.id, isouter=True)
        .join(aliased, aliased.c.security_id == Security.id, isouter=True)
        .group_by(Exchange.code)
        .order_by(Exchange.code)
    ).all()
    return tuple(
        ExchangeCoverage(
            exchange=code,
            securities=securities,
            securities_with_alias=with_alias,
            aliases=int(aliases),
        )
        for code, securities, with_alias, aliases in rows
    )


# --------------------------------------------------------------------------------------
# The deterministic tiers
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Hit:
    """An alias matching a run of tokens. Internal; becomes a `CandidateTag` or is dropped."""

    record: AliasRecord
    first: int  # index of the first token matched
    last: int  # index of the last token matched, inclusive
    confidence: float
    method: str


def match_aliases(text: str, aliases: Sequence[AliasRecord]) -> list[CandidateTag]:
    """The `alias` and `fuzzy` tiers over one piece of text. No database, no date, no key.

    Pure, so the interesting cases - the headlines that must *not* match - are unit tests
    over literals rather than fixtures. `tag_article` adds the two tiers that need more:
    `ticker` needs the article's date and the identifier table, `llm` needs a model.

    The order of operations is the precision argument in code form:

    1. exact alias matches, longest first, each consuming its tokens so a shorter overlapping
       name cannot also fire;
    2. a span matched by two *different companies* tags neither - the same refusal
       `resolve_security` makes for an ambiguous ticker, for the same reason;
    3. fuzzy only over tokens no exact match consumed, and only for securities no exact
       match already found;
    4. the best single tag per security, because a brief needs one line per company.
    """
    tokens = tokenise(text)
    if not tokens or not aliases:
        return []
    hits = _exact_hits(tokens, aliases)
    consumed = {index for hit in hits for index in range(hit.first, hit.last + 1)}
    found = {hit.record.security_id for hit in hits}
    hits.extend(_fuzzy_hits(tokens, aliases, consumed=consumed, already_found=found))
    return _best_per_security(tokens, text, hits)


def _exact_hits(tokens: Sequence[Token], aliases: Sequence[AliasRecord]) -> list[_Hit]:
    """Whole-word runs equal to an alias, longest first, non-overlapping."""
    index: dict[tuple[str, ...], list[AliasRecord]] = {}
    for record in aliases:
        index.setdefault(record.tokens, []).append(record)
    lengths = sorted({len(key) for key in index}, reverse=True)
    words = tuple(token.text for token in tokens)

    hits: list[_Hit] = []
    taken: set[int] = set()
    for length in lengths:
        for first in range(len(words) - length + 1):
            last = first + length - 1
            if taken.intersection(range(first, last + 1)):
                continue
            records = index.get(words[first : last + 1])
            if not records:
                continue
            if length == 1 and _needs_cue(words[first]) and not _has_cue(words, first, last):
                _log.debug(
                    "tagging.single_token_alias_needs_a_cue",
                    token=words[first],
                    securities=sorted({r.security_id for r in records}),
                )
                continue
            if len({record.company_id for record in records}) > 1:
                _log.warning(
                    "tagging.alias_matches_two_companies",
                    alias=" ".join(words[first : last + 1]),
                    companies=sorted({record.company_id for record in records}),
                )
                continue
            taken.update(range(first, last + 1))
            confidence = (
                ALIAS_MULTI_TOKEN_CONFIDENCE if length > 1 else ALIAS_SINGLE_TOKEN_CONFIDENCE
            )
            hits.extend(
                _Hit(record=record, first=first, last=last, confidence=confidence, method=ALIAS)
                for record in records
            )
    return hits


def _needs_cue(word: str) -> bool:
    """Whether a one-word alias may fire on its own."""
    return len(word) < MIN_UNCUED_SINGLE_TOKEN_CHARS or word in AMBIGUOUS_SINGLE_TOKENS


def _has_cue(words: Sequence[str], first: int, last: int) -> bool:
    """A legal form immediately before or after the match. `Apple Inc`, `Plc Total`."""
    before = words[first - 1] if first > 0 else None
    after = words[last + 1] if last + 1 < len(words) else None
    return before in LEGAL_FORM_TOKENS or after in LEGAL_FORM_TOKENS


def _fuzzy_hits(
    tokens: Sequence[Token],
    aliases: Sequence[AliasRecord],
    *,
    consumed: set[int],
    already_found: set[int],
) -> list[_Hit]:
    """Near misses, over token windows, for aliases long enough for the tier to mean anything.

    Windows of n-1, n and n+1 tokens around the alias's own token count, because the most
    common real variant *changes* the count: `JPMorgan Chase` against `JP Morgan Chase`,
    `UnitedHealth Group` against `United Health Group`. Comparing only equal-length windows
    would miss exactly the case the tier is for.

    A run of text that two different companies both clear the threshold on tags **neither**
    - and the clusters are built over *overlapping* windows rather than identical ones,
    because two near-misses of different sizes over the same phrase is the same ambiguity
    wearing a disguise. `'unity bank plc'` against `'zenith bank plc'` scores 0.8276 and so
    never reaches here, but this refusal is the floor under the threshold rather than a
    consequence of it.
    """
    words = [token.text for token in tokens]
    eligible = [
        record
        for record in aliases
        if len(record.normalised) >= FUZZY_MIN_ALIAS_CHARS
        and record.security_id not in already_found
    ]
    if not eligible:
        return []

    raw: list[_Hit] = []
    matcher = difflib.SequenceMatcher(autojunk=False)
    for record in eligible:
        matcher.set_seq2(record.normalised)
        n = len(record.tokens)
        for size in {n - 1, n, n + 1}:
            if size < 1:
                continue
            for first in range(len(words) - size + 1):
                last = first + size - 1
                if consumed.intersection(range(first, last + 1)):
                    continue
                matcher.set_seq1(" ".join(words[first : last + 1]))
                # The documented cheap-to-expensive ladder: both are upper bounds on
                # `ratio()`, so a window that fails either cannot pass.
                if (
                    matcher.real_quick_ratio() < FUZZY_THRESHOLD
                    or matcher.quick_ratio() < FUZZY_THRESHOLD
                ):
                    continue
                ratio = matcher.ratio()
                if ratio < FUZZY_THRESHOLD:
                    continue
                raw.append(
                    _Hit(
                        record=record,
                        first=first,
                        last=last,
                        confidence=_fuzzy_confidence(ratio),
                        method=FUZZY,
                    )
                )
    return _unambiguous_clusters(raw, words)


def _unambiguous_clusters(raw: list[_Hit], words: Sequence[str]) -> list[_Hit]:
    """Drop every group of overlapping near-misses that names more than one company."""
    if not raw:
        return []
    raw.sort(key=lambda hit: (hit.first, hit.last))
    clusters: list[list[_Hit]] = []
    for hit in raw:
        if clusters and hit.first <= max(other.last for other in clusters[-1]):
            clusters[-1].append(hit)
        else:
            clusters.append([hit])
    kept: list[_Hit] = []
    for cluster in clusters:
        companies = {hit.record.company_id for hit in cluster}
        if len(companies) > 1:
            first = min(hit.first for hit in cluster)
            last = max(hit.last for hit in cluster)
            _log.warning(
                "tagging.fuzzy_window_matches_two_companies",
                window=" ".join(words[first : last + 1]),
                companies=sorted(companies),
            )
            continue
        kept.extend(cluster)
    return kept


def _fuzzy_confidence(ratio: float) -> float:
    """A `difflib` ratio mapped onto the shared probability scale.

    Linear from the threshold to 1.0 across
    [:data:`FUZZY_MIN_CONFIDENCE`, :data:`FUZZY_MAX_CONFIDENCE`]. The mapping exists
    because the raw ratio is a property of two strings and the column holds a property of
    a claim; using the ratio directly would put a 0.95 near-miss above a 0.93 exact ticker
    match, which inverts the ordering a brief depends on.
    """
    span = (ratio - FUZZY_THRESHOLD) / (1.0 - FUZZY_THRESHOLD)
    return FUZZY_MIN_CONFIDENCE + span * (FUZZY_MAX_CONFIDENCE - FUZZY_MIN_CONFIDENCE)


def _best_per_security(
    tokens: Sequence[Token], text: str, hits: Iterable[_Hit]
) -> list[CandidateTag]:
    """One tag per security - the strongest evidence found - in a stable order."""
    best: dict[int, _Hit] = {}
    for hit in hits:
        current = best.get(hit.record.security_id)
        if current is None or hit.confidence > current.confidence:
            best[hit.record.security_id] = hit
    return [
        CandidateTag(
            security_id=hit.record.security_id,
            method=hit.method,
            confidence=hit.confidence,
            matched_text=text[tokens[hit.first].start : tokens[hit.last].end],
            alias_id=hit.record.alias_id,
        )
        for _, hit in sorted(best.items())
    ]


def ticker_mentions(text: str, *, codes: frozenset[str]) -> list[TickerMention]:
    """Symbols carrying a cue that says they are symbols. `$CAT`, `(NYSE: CAT)`.

    **A bare uppercase symbol is not matched**, and that refusal is most of this tier's
    value. `CAT` is a scan, `KO` is a knockout, `HD` is a video format, `PG` is a film
    rating, `ALL` and `ON` and `IT` are words, and all of them reach a financial feed in
    upper case. Requiring the cue costs "GTCO rose 3%" and buys never tagging Caterpillar
    to a hospital story - which is the trade `docs/03` P5.2 asks to be made in that
    direction.

    `codes` comes from the `exchanges` table rather than a constant, so an unrecognised
    qualifier (`LSE:`) is treated as no qualifier and the symbol is left to the cashtag
    rule or to nothing at all.
    """
    mentions: list[TickerMention] = []
    seen: set[tuple[int, int]] = set()
    if codes:
        pattern = re.compile(
            r"\b(?i:" + "|".join(re.escape(code) for code in sorted(codes)) + r")\s*:\s*"
            r"([A-Z][A-Z0-9]{0,9})\b"
        )
        for match in pattern.finditer(text):
            code = match.group(0).split(":")[0].strip().upper()
            mentions.append(
                TickerMention(
                    symbol=match.group(1),
                    exchange=code if code in codes else None,
                    matched_text=match.group(0).strip(),
                    start=match.start(),
                    end=match.end(),
                    confidence=TICKER_EXCHANGE_CONFIDENCE,
                )
            )
            seen.add((match.start(1), match.end(1)))
    for match in _CASHTAG.finditer(text):
        if (match.start(1), match.end(1)) in seen:
            continue
        mentions.append(
            TickerMention(
                symbol=match.group(1),
                exchange=None,
                matched_text=match.group(0),
                start=match.start(),
                end=match.end(),
                confidence=TICKER_CASHTAG_CONFIDENCE,
            )
        )
    return mentions


# --------------------------------------------------------------------------------------
# Tagging an article: the two tiers that need more than the text
# --------------------------------------------------------------------------------------


def tag_article(
    session: Session,
    item: NewsItem,
    *,
    aliases: Sequence[AliasRecord] | None = None,
    codes: frozenset[str] | None = None,
    extractor: EntityExtractor | None = None,
) -> list[CandidateTag]:
    """Every security this article is about, with the evidence for each.

    `aliases` and `codes` are parameters so a batch loads them once; omitted, they are read
    per call, which is correct and slow.

    The date every ticker is resolved on is the article's own `known_as_of` - the Lagos
    calendar date of publication, generated by migration 0025 from `published_at`. Using
    today's date instead would resolve a 2019 article's `GUARANTY` against the 2026
    identifier table and find nothing, or worse, find somebody else.
    """
    records = load_aliases(session) if aliases is None else aliases
    venues = exchange_codes(session) if codes is None else codes
    text = item.headline if not item.body else f"{item.headline}\n{item.body}"

    tags = {tag.security_id: tag for tag in match_aliases(text, records)}
    for tag in _ticker_tags(session, text, codes=venues, as_of=item.known_as_of):
        tags.setdefault(tag.security_id, tag)
    if extractor is not None:
        for tag in _llm_tags(session, text, records, venues, item, extractor):
            tags.setdefault(tag.security_id, tag)
    return [tags[key] for key in sorted(tags)]


def _ticker_tags(
    session: Session, text: str, *, codes: frozenset[str], as_of: dt.date
) -> list[CandidateTag]:
    """Cued symbols, resolved on the article's date. Ambiguity tags nothing."""
    tags: list[CandidateTag] = []
    for mention in ticker_mentions(text, codes=codes):
        security_id = _resolve_ticker(session, mention.symbol, mention.exchange, as_of)
        if security_id is None:
            continue
        tags.append(
            CandidateTag(
                security_id=security_id,
                method=TICKER_TAG,
                confidence=mention.confidence,
                matched_text=mention.matched_text,
            )
        )
    return tags


def _resolve_ticker(
    session: Session, symbol: str, exchange: str | None, as_of: dt.date
) -> int | None:
    """`packages.common.identity`, and no other route to the identifier table.

    An ambiguous symbol - one string, one date, two exchanges - returns None rather than a
    choice. `identity.resolve_security` raises there deliberately, *"because picking one is
    the silent merge this module was written to stop"*, and the right answer to it here is
    to tag nothing and say so.
    """
    try:
        resolved = resolve_security(
            session, value=symbol, as_of=as_of, id_type=TICKER, exchange=exchange
        )
    except AmbiguousIdentifierError:
        _log.warning("tagging.ticker_is_ambiguous", symbol=symbol, as_of=as_of.isoformat())
        return None
    if resolved is None:
        _log.debug("tagging.ticker_identifies_nothing", symbol=symbol, as_of=as_of.isoformat())
        return None
    return resolved.security_id


def _llm_tags(
    session: Session,
    text: str,
    aliases: Sequence[AliasRecord],
    codes: frozenset[str],
    item: NewsItem,
    extractor: EntityExtractor,
) -> list[CandidateTag]:
    """Model-proposed spans, grounded in the article and then resolved deterministically.

    Two checks the model does not get to skip. The span must **occur in the article** - a
    name a model produced from its own memory of the company is not evidence about this
    article, and the failure is logged rather than swallowed because a model that
    routinely fails it is a prompt bug. Then it must **resolve**, through the same alias
    and ticker machinery as everything else, so the model can never name a security we do
    not hold.

    What is relaxed here, and only here: the corporate-cue requirement on a short or
    ordinary-word alias, and the cue requirement on a bare ticker. The model has read the
    sentence, which is the thing those rules stand in for. :data:`LLM_MAX_CONFIDENCE` is
    what pays for the relaxation - a relaxed match can never outrank a strict one.
    """
    words = tuple(token.text for token in tokenise(text))
    tags: list[CandidateTag] = []
    for mention in extractor.mentions(item.headline, item.body):
        span = tuple(token.text for token in tokenise(mention.text))
        if not span or not _grounded(words, span):
            _log.warning(
                "tagging.llm_mention_is_not_in_the_article",
                mention=mention.text,
                model=extractor.model_name,
                prompt_version=extractor.prompt_version,
            )
            continue
        confidence = min(mention.confidence, LLM_MAX_CONFIDENCE)
        if confidence < LLM_MIN_CONFIDENCE:
            continue
        security_id = _resolve_mention(session, span, aliases, codes, item.known_as_of)
        if security_id is None:
            _log.info(
                "tagging.llm_mention_resolves_to_no_security",
                mention=mention.text,
                model=extractor.model_name,
            )
            continue
        tags.append(
            CandidateTag(
                security_id=security_id,
                method=LLM,
                confidence=confidence,
                matched_text=mention.text,
                # NULL by contract: the `llm` tier cites no alias row, and migration 0027's
                # `tag_cites_an_alias_row_iff_it_matched_one` makes that an equivalence.
                alias_id=None,
            )
        )
    return tags


def _grounded(words: Sequence[str], span: Sequence[str]) -> bool:
    """Whether `span` occurs as a run of whole words in `words`."""
    length = len(span)
    return any(tuple(words[i : i + length]) == tuple(span) for i in range(len(words) - length + 1))


def _resolve_mention(
    session: Session,
    span: tuple[str, ...],
    aliases: Sequence[AliasRecord],
    codes: frozenset[str],
    as_of: dt.date,
) -> int | None:
    """A grounded span to a `security_id`, cue rules relaxed. None when it reaches nothing."""
    exact = [record for record in aliases if record.tokens == span]
    if exact:
        companies = {record.company_id for record in exact}
        return exact[0].security_id if len(companies) == 1 else None
    if len(span) == 1:
        # The bare ticker the deterministic tier refuses. `resolve_security` still refuses
        # an ambiguous one, and still answers for the article's own date.
        resolved = _resolve_ticker(session, span[0].upper(), None, as_of)
        if resolved is not None:
            return resolved
    text = " ".join(span)
    if len(text) < FUZZY_MIN_ALIAS_CHARS:
        return None
    matcher = difflib.SequenceMatcher(autojunk=False)
    # Same orientation as `_fuzzy_hits`: seq1 is the article's words, seq2 the alias. The
    # ratio is close to symmetric but not exactly, and two tiers disagreeing about a
    # borderline match for that reason would be a bug nobody could reproduce.
    matcher.set_seq1(text)
    best: tuple[float, int] | None = None
    tied = False
    for record in aliases:
        matcher.set_seq2(record.normalised)
        if matcher.real_quick_ratio() < FUZZY_THRESHOLD:
            continue
        ratio = matcher.ratio()
        if ratio < FUZZY_THRESHOLD:
            continue
        if best is None or ratio > best[0]:
            best, tied = (ratio, record.security_id), False
        elif ratio == best[0] and record.security_id != best[1]:
            tied = True
    if best is None or tied:
        return None
    return best[1]


# --------------------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------------------


def store_tags(
    session: Session,
    *,
    news_id: int,
    tags: Sequence[CandidateTag],
    tagger_version: str = TAGGER_VERSION,
) -> int:
    """Write tags for one article. Returns how many rows were new.

    `ON CONFLICT DO NOTHING` on the whole primary key, never an update: `news_tags` carries
    the `no_update` trigger and `CLAUDE.md` forbids the silent overwrite it would be. A
    re-run of the same `tagger_version` is therefore a no-op, and a re-run of a *new*
    version writes a second row beside the first, which is the point of the version being
    in the key.
    """
    if not tags:
        return 0
    rows = [tag.as_row(news_id=news_id, tagger_version=tagger_version) for tag in tags]
    statement = (
        pg_insert(NewsTag)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["news_id", "security_id", "method", "tagger_version"]
        )
        .returning(NewsTag.news_id)
    )
    return len(session.execute(statement).fetchall())


def tag_articles(
    session: Session,
    items: Sequence[NewsItem],
    *,
    extractor: EntityExtractor | None = None,
    store: bool = True,
    tagger_version: str = TAGGER_VERSION,
) -> TaggingReport:
    """Tag a batch, and report what the tagger could not have reached whatever it read.

    The coverage warnings are the loud half of P5.2. Every security in this database is
    US-listed and NGX holds none, while all three feeds `packages/ingestion/rss.py` reads
    are Nigerian - so today this returns zero tags for almost every article, and that is a
    missing universe rather than a broken matcher. The distinction is invisible in the
    output and has to be said out loud.
    """
    coverage = alias_coverage(session)
    for entry in coverage:
        reason = entry.untaggable
        if reason is not None:
            _log.warning(
                "tagging.exchange_cannot_be_tagged",
                exchange=entry.exchange,
                reason=reason,
                securities=entry.securities,
                aliases=entry.aliases,
            )
    aliases = load_aliases(session)
    codes = exchange_codes(session)

    tagged = 0
    written = 0
    for item in items:
        tags = tag_article(session, item, aliases=aliases, codes=codes, extractor=extractor)
        if tags:
            tagged += 1
        if store:
            written += store_tags(
                session, news_id=item.id, tags=tags, tagger_version=tagger_version
            )
    report = TaggingReport(
        articles=len(items),
        tagged=tagged,
        tags_written=written,
        aliases_loaded=len(aliases),
        coverage=coverage,
    )
    _log.info(
        "tagging.run",
        articles=report.articles,
        tagged=report.tagged,
        untagged=report.untagged,
        tags_written=report.tags_written,
        aliases=report.aliases_loaded,
        unreachable=report.unreachable,
        tagger_version=tagger_version,
    )
    return report
