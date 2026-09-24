"""`packages.normalize.tagging`: which security an article is about. P5.2.

`docs/03` P5.2: *"a naive string match gets this wrong in both directions, and a false tag
on a watchlist alert is the fastest way to make a brief untrustworthy."* The two directions
are not equally expensive, and neither is the test file. **Most of what is below is
headlines that must not match**, written as real sentences rather than adversarial noise,
because the false tag is the failure that has to be found here rather than in a brief.

Four groups:

* the fold - accents, possessives, hyphens, ampersands, case - because two spellings of one
  name that fold differently is a tier that silently stops firing;
* the refusals - `CAT` the scan, `apple` the fruit, `PG` the film rating, `Intl` the
  abbreviation, `Zenith` against `Unity`;
* the matches that must still happen, so the refusals are not achieved by refusing
  everything;
* the schema, because a CHECK that admits what it was written to reject is this
  repository's recurring bug (migration `0021`) and the only way to know is to try the row.

**Seed before asserting.** Every database test writes its own companies, securities and
aliases and asserts the write landed before looking for what should not be there. A test
that scans for bad rows on an empty table passes for the wrong reason, and on a fresh test
database `companies` is empty - the 24 securities in the dev database were loaded by the
EDGAR connector, not by a migration.

**Nothing asserts an unscoped global count.** Counts are taken as deltas around the rows
this test wrote, so a row committed by another test cannot turn a pass into a failure.

**Constraint tests hold the savepoint inside `pytest.raises`**, following
`tests/unit/test_identity.py`: the failing flush aborts the savepoint, and letting
`begin_nested()` see the exception is what leaves the outer transaction usable.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import importlib.util
import itertools
import pathlib
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    NewsItem,
    NewsTag,
    Security,
    SecurityAlias,
    SecurityIdentifier,
    SourceDocument,
)
from packages.normalize.tagging import (
    ALIAS,
    ALIAS_MULTI_TOKEN_CONFIDENCE,
    ALIAS_SINGLE_TOKEN_CONFIDENCE,
    AMBIGUOUS_SINGLE_TOKENS,
    FUZZY,
    FUZZY_MAX_CONFIDENCE,
    FUZZY_MIN_ALIAS_CHARS,
    FUZZY_MIN_CONFIDENCE,
    FUZZY_THRESHOLD,
    LLM,
    LLM_MAX_CONFIDENCE,
    LLM_MIN_CONFIDENCE,
    TAGGER_VERSION,
    TICKER_CASHTAG_CONFIDENCE,
    TICKER_EXCHANGE_CONFIDENCE,
    TICKER_TAG,
    AliasRecord,
    CandidateTag,
    EntityExtractor,
    EntityMention,
    alias_coverage,
    derive_aliases,
    exchange_codes,
    load_aliases,
    match_aliases,
    normalise,
    seed_aliases_for,
    store_tags,
    tag_article,
    tag_articles,
    ticker_mentions,
    tokenise,
)

#: Loaded by path rather than imported: `db/migrations/versions` is not a package, and the
#: point of the test that uses it is precisely that the migration does not import the
#: module it has to agree with.
_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "db"
    / "migrations"
    / "versions"
    / "0027_p5_ticker_tagging.py"
)

#: The 24 `companies.legal_name` values in the dev database on 2026-09-24, verbatim, EDGAR
#: artefacts included. Literals rather than a query, because the point of the derivation
#: tests is what the rule does to *these strings* - a test that read the column would pass
#: on an empty test database without deriving anything.
LEGAL_NAMES = (
    "Apple Inc.",
    "MICROSOFT CORP",
    "AMAZON COM INC",
    "Meta Platforms, Inc.",
    "NVIDIA CORP",
    "Tesla, Inc.",
    "JPMORGAN CHASE & CO",
    "BANK OF AMERICA CORP /DE/",
    "ExxonMobil Holdings Corp",
    "CHEVRON CORP",
    "JOHNSON & JOHNSON",
    "PFIZER INC",
    "PROCTER & GAMBLE Co",
    "COCA COLA CO",
    "Walmart Inc.",
    "HOME DEPOT, INC.",
    "Walt Disney Co",
    "CATERPILLAR INC",
    "INTERNATIONAL BUSINESS MACHINES CORP",
    "INTEL CORP",
    "CISCO SYSTEMS, INC.",
    "ORACLE CORP",
    "UNITEDHEALTH GROUP INC",
    "Alphabet Inc.",
)

#: Every one-word alias the seed derives from :data:`LEGAL_NAMES`, split by whether it may
#: fire on its own. The split is a decision about false tags, so it is pinned here: a new
#: security whose brand name is a single ordinary word fails this test rather than quietly
#: tagging the wrong articles. Moving a name from one set to the other is the decision.
UNCUED_SINGLE_TOKEN_BRANDS = frozenset(
    {"caterpillar", "chevron", "microsoft", "nvidia", "pfizer", "tesla", "walmart"}
)
CUED_SINGLE_TOKEN_BRANDS = frozenset({"alphabet", "apple", "intel", "oracle"})

#: Dated so that `known_as_of` (the Lagos date of `published_at`) is unambiguous.
PUBLISHED = dt.datetime(2026, 9, 20, 9, 30, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, 10, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------------------------
# Fixtures. Everything is written by the test, and the write is asserted.
# --------------------------------------------------------------------------------------


def _exchange_id(session: Session, code: str) -> int:
    return session.execute(select(Exchange.id).where(Exchange.code == code)).scalar_one()


def _security(session: Session, legal_name: str, *, exchange: str = "NASDAQ") -> Security:
    company = Company(
        legal_name=legal_name,
        country="US" if exchange != "NGX" else "NG",
        statement_template="non_financial",
        fiscal_year_end=12,
    )
    session.add(company)
    session.flush()
    security = Security(
        company_id=company.id,
        exchange_id=_exchange_id(session, exchange),
        currency="USD" if exchange != "NGX" else "NGN",
    )
    session.add(security)
    session.flush()
    return security


def _aliased(session: Session, legal_name: str, *, exchange: str = "NASDAQ") -> Security:
    """A security with the aliases the seed would have derived for it."""
    security = _security(session, legal_name, exchange=exchange)
    written = seed_aliases_for(
        session,
        security_id=security.id,
        legal_name=legal_name,
        source="derived:companies.legal_name",
    )
    assert written == len(derive_aliases(legal_name)), (
        f"the seed for {legal_name!r} did not land; every assertion below it would be "
        "about an empty alias table"
    )
    return security


def _ticker(
    session: Session,
    security: Security,
    value: str,
    *,
    valid_from: dt.date = dt.date(2000, 1, 1),
    valid_to: dt.date | None = None,
) -> None:
    session.add(
        SecurityIdentifier(
            security_id=security.id,
            id_type="ticker",
            id_value=value,
            exchange_id=security.exchange_id,
            valid_from=valid_from,
            valid_to=valid_to,
            is_primary=True,
            source="test",
        )
    )
    session.flush()


def _article(session: Session, headline: str, *, body: str | None = None, marker: str) -> NewsItem:
    """One stored article. `content_hash` is hex because migration 0025 checks that it is."""
    digest = hashlib.sha256(marker.encode()).hexdigest()
    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Nairametrics")
    ).scalar_one()
    document = SourceDocument(
        data_source_id=source_id,
        url="https://nairametrics.com/feed/",
        storage_key=f"documents/sha256/{digest}",
        sha256=digest,
        media_type="application/rss+xml",
        retrieved_at=RETRIEVED,
    )
    session.add(document)
    session.flush()
    item = NewsItem(
        data_source_id=source_id,
        source_document_id=document.id,
        item_key=f"test-{marker}",
        url=f"https://nairametrics.com/{marker}",
        url_canonical=f"https://nairametrics.com/{marker}",
        headline=headline,
        body=body,
        published_at=PUBLISHED,
        retrieved_at=RETRIEVED,
        content_hash=digest,
    )
    session.add(item)
    session.flush()
    session.refresh(item)  # `known_as_of` is generated by the database
    return item


def _offline(*legal_names: str) -> tuple[AliasRecord, ...]:
    """Alias records for a set of companies, without touching the database.

    The pure tiers need `AliasRecord`s and nothing else, so most of this file builds them
    directly: a headline that must not match is a fact about strings, not about storage,
    and a test that needs no database is a test that runs in milliseconds and cannot be
    dropped by a Neon connection.

    `security_id` and `company_id` are both the index of the name in `legal_names`, which
    is the one-security-per-company shape the real table has today.
    """
    records: list[AliasRecord] = []
    for company_id, legal_name in enumerate(legal_names, start=1):
        for alias, alias_type in derive_aliases(legal_name):
            records.append(
                AliasRecord(
                    alias_id=len(records) + 1,
                    security_id=company_id,
                    company_id=company_id,
                    alias=alias,
                    alias_type=alias_type,
                    tokens=tuple(token.text for token in tokenise(alias)),
                )
            )
    return tuple(records)


#: The whole seeded universe, as the pure tiers see it. Used by every match test below so
#: that a headline is tested against *all* the aliases at once, which is the only way a
#: cross-company collision can show up.
EVERYTHING = _offline(*LEGAL_NAMES)


def _securities_matched(headline: str, aliases: tuple[AliasRecord, ...] = EVERYTHING) -> set[int]:
    return {tag.security_id for tag in match_aliases(headline, aliases)}


def _only(headline: str, aliases: tuple[AliasRecord, ...] = EVERYTHING) -> CandidateTag:
    tags = match_aliases(headline, aliases)
    assert len(tags) == 1, f"expected exactly one tag for {headline!r}, got {tags}"
    return tags[0]


# --------------------------------------------------------------------------------------
# The fold. Two spellings of one name that fold differently is a tier that stops firing.
# --------------------------------------------------------------------------------------


class TestFolding:
    def test_case_punctuation_and_accents_all_fold_to_the_same_words(self) -> None:
        assert normalise("Coca-Cola") == "coca cola"
        assert normalise("COCA COLA") == "coca cola"
        assert normalise("coca.cola") == "coca cola"
        assert normalise("Nestlé Nigeria") == "nestle nigeria"
        assert normalise("Johnson & Johnson") == "johnson johnson"
        assert normalise("Amazon.com") == "amazon com"

    def test_a_possessive_is_one_mention_not_a_mention_and_a_stray_s(self) -> None:
        """`GTCO's` must fold to `gtco`. The trailing `s` would widen every fuzzy window."""
        assert normalise("GTCO's results") == "gtco results"
        assert normalise("GTCO’s results") == "gtco results", "curly apostrophe"
        assert normalise("Coca-Cola's bottler") == "coca cola bottler"

    def test_a_plural_s_that_is_not_a_possessive_survives(self) -> None:
        """`systems` is a word. Only the `s` *after an apostrophe* is dropped."""
        assert normalise("Cisco Systems") == "cisco systems"
        assert normalise("S&P said") == "s p said"

    def test_offsets_point_back_at_the_original_characters(self) -> None:
        """What makes `matched_text` the article's own words rather than the folded form."""
        text = "Coca-Cola's bottler"
        tokens = tokenise(text)
        assert text[tokens[0].start : tokens[1].end] == "Coca-Cola"


# --------------------------------------------------------------------------------------
# Deriving aliases: exactly two rules, and nothing invented
# --------------------------------------------------------------------------------------


class TestDerivation:
    @pytest.mark.parametrize(
        ("legal_name", "expected"),
        [
            ("Apple Inc.", [("Apple Inc.", "legal"), ("Apple", "brand")]),
            ("COCA COLA CO", [("COCA COLA CO", "legal"), ("COCA COLA", "brand")]),
            (
                "BANK OF AMERICA CORP /DE/",
                [("BANK OF AMERICA CORP", "legal"), ("BANK OF AMERICA", "brand")],
            ),
            (
                "JPMORGAN CHASE & CO",
                [("JPMORGAN CHASE & CO", "legal"), ("JPMORGAN CHASE", "brand")],
            ),
            (
                "Meta Platforms, Inc.",
                [("Meta Platforms, Inc.", "legal"), ("Meta Platforms", "brand")],
            ),
            # No legal-form suffix, so one row rather than a duplicate.
            ("JOHNSON & JOHNSON", [("JOHNSON & JOHNSON", "legal")]),
            # `GROUP` is not a legal form: "UnitedHealth Group" is what people write.
            (
                "UNITEDHEALTH GROUP INC",
                [("UNITEDHEALTH GROUP INC", "legal"), ("UNITEDHEALTH GROUP", "brand")],
            ),
        ],
    )
    def test_the_two_rules(self, legal_name: str, expected: list[tuple[str, str]]) -> None:
        assert derive_aliases(legal_name) == expected

    def test_nothing_beyond_the_two_rules_is_invented(self) -> None:
        """ "Amazon" is a real alias of `AMAZON COM INC` and is deliberately not derived.

        No rule produces it that would not also produce wrong ones, and `docs/03` P5.2's
        whole point is which direction to err in. It is curation, and `alias_type` has
        `colloquial` waiting for it.
        """
        aliases = {alias for alias, _ in derive_aliases("AMAZON COM INC")}
        assert aliases == {"AMAZON COM INC", "AMAZON COM"}
        assert "AMAZON" not in aliases

    def test_every_single_token_brand_the_seed_derives_is_classified(self) -> None:
        """A new one-word brand name must be a decision, not a default.

        Whether a single word may fire without a corporate cue beside it is the difference
        between tagging Apple Inc. and tagging an article about the apple harvest. The two
        sets below are that decision written down; this asserts the seed produces exactly
        them, so a security whose brand is a new ordinary word fails the build.
        """
        singles = {
            tuple(token.text for token in tokenise(alias))[0]
            for name in LEGAL_NAMES
            for alias, _ in derive_aliases(name)
            if len(tokenise(alias)) == 1
        }
        assert singles == UNCUED_SINGLE_TOKEN_BRANDS | CUED_SINGLE_TOKEN_BRANDS
        assert CUED_SINGLE_TOKEN_BRANDS <= AMBIGUOUS_SINGLE_TOKENS
        assert not (UNCUED_SINGLE_TOKEN_BRANDS & AMBIGUOUS_SINGLE_TOKENS)

    def test_the_migration_and_the_module_derive_the_same_aliases(self) -> None:
        """Migration 0027 carries a frozen copy of the rule; this is what keeps it honest.

        No migration in this repository imports from `packages`, because a migration is
        pinned to a moment in the schema's history and has to keep running after the module
        beside it has been rewritten. The duplication is deliberate; the drift is not.
        """
        spec = importlib.util.spec_from_file_location("migration_0027", _MIGRATION_PATH)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        for name in LEGAL_NAMES:
            assert migration.derived_aliases(name) == derive_aliases(name), name


# --------------------------------------------------------------------------------------
# The refusals. Real headlines that must tag nothing.
# --------------------------------------------------------------------------------------


class TestFalsePositives:
    """Every case here is a sentence a financial feed could plausibly carry.

    `docs/03` P5.2's warning is that a naive matcher gets this wrong "in both directions",
    and the brief adds the mechanism: a short ticker is a word, and `"TOTAL" in headline`
    tags every article containing the word "total". These are the headlines that prove the
    guards are load-bearing rather than decorative.
    """

    @pytest.mark.parametrize(
        "headline",
        [
            # A one-word brand that is an ordinary noun, with no corporate cue beside it.
            "Apple harvest in Jos pushes food prices lower",
            "Traders swap intel on the floor before the open",
            "The oracle of Omaha trimmed his stake again",
            "An alphabet soup of regulators now oversees fintech",
            # The same words inside longer words: token boundaries, not substrings.
            "Shoppers are apparently unmoved by the price rise",
            # Short uppercase strings that are tickers somewhere and words here.
            "Boxer wins by KO in the third round at Teslim Balogun",
            "Netflix drops its HD-only tier in Nigeria",
            "The film is rated PG for mild language",
            "Hospital installs a new CAT scanner in Ikeja",
            "ALL eyes on the MPC decision this afternoon",
            # A different company whose name is one letter from an alias.
            "Chevrolet dealers report a slow quarter in Lagos",
            # An abbreviation that scores 0.889 against `intel` - above the threshold, and
            # excluded by FUZZY_MIN_ALIAS_CHARS rather than by luck.
            "Intl Breweries lifts full-year guidance",
        ],
    )
    def test_a_real_headline_that_must_tag_nothing(self, headline: str) -> None:
        assert match_aliases(headline, EVERYTHING) == [], headline

    def test_the_total_case_docs_03_names_by_name(self) -> None:
        """`docs/03` P5.2's own example, with an NGX-shaped alias actually seeded.

        `TotalEnergies Marketing Nigeria Plc` derives the brand `TotalEnergies Marketing
        Nigeria`, and a curator would add `Total`. Both are seeded here; neither may fire
        on the word "total" in ordinary prose, and the second must still fire when the
        legal form is beside it.
        """
        aliases = (
            *_offline("TotalEnergies Marketing Nigeria Plc"),
            AliasRecord(
                alias_id=900,
                security_id=1,
                company_id=1,
                alias="Total",
                alias_type="colloquial",
                tokens=("total",),
            ),
        )
        assert match_aliases("Total credit to the private sector rose 12%", aliases) == []
        assert match_aliases("The total number of listed firms fell", aliases) == []
        assert _securities_matched("Total Plc lifts pump prices", aliases) == {1}

    def test_two_banks_one_letter_apart_tag_neither(self) -> None:
        """The measured floor under `FUZZY_THRESHOLD`, as a headline.

        `'unity bank plc'` against `'zenith bank plc'` scores 0.8276, the highest
        cross-company similarity in the seedable universe. A threshold at or below it
        merges two real Nigerian banks on every earnings story either of them files.
        """
        aliases = _offline("Zenith Bank Plc", "Unity Bank Plc", "Wema Bank Plc")
        assert _securities_matched("Zenith Bank posts record half-year profit", aliases) == {1}
        assert _securities_matched("Unity Bank returns to profit", aliases) == {2}

    def test_sibling_brands_of_one_group_do_not_tag_each_other(self) -> None:
        """ "Dangote Cement" and "Dangote Sugar" share a word and nothing else."""
        aliases = _offline("Dangote Cement Plc", "Dangote Sugar Refinery Plc")
        assert _securities_matched("Dangote Cement lifts dividend", aliases) == {1}
        assert _securities_matched("Dangote Sugar Refinery cuts output", aliases) == {2}

    def test_a_span_two_companies_both_claim_tags_neither(self) -> None:
        """Ambiguity tags nothing - the rule `identity.resolve_security` already applies.

        Two unrelated issuers holding the same alias is a data problem, and the answer to
        it is a warning and no tag, not a coin toss. `identity.py`: *"picking one is the
        silent merge this module was written to stop."*
        """
        shared = tuple(
            AliasRecord(
                alias_id=index,
                security_id=index,
                company_id=index,
                alias="Sterling Financial Holdings",
                alias_type="legal",
                tokens=("sterling", "financial", "holdings"),
            )
            for index in (1, 2)
        )
        assert match_aliases("Sterling Financial Holdings raises capital", shared) == []

    def test_a_bare_uppercase_ticker_is_not_a_ticker_mention(self) -> None:
        """The refusal that makes the `ticker` tier safe, and its cost, in one test."""
        codes = frozenset({"NGX", "NASDAQ", "NYSE"})
        assert ticker_mentions("CAT fell 2% in early trade", codes=codes) == []
        assert ticker_mentions("GTCO rose 3% after the results", codes=codes) == []
        assert ticker_mentions("Oil rallied to $95 a barrel", codes=codes) == []
        assert ticker_mentions("$cat is not a cashtag", codes=codes) == []

    def test_an_unrecognised_exchange_qualifier_is_not_a_cue(self) -> None:
        """`LSE:` and India's `NSE:` name venues this database does not hold.

        Treating an unknown qualifier as a cue would resolve the symbol against whatever
        market happened to answer, which is how an Indian ticker tags a Nigerian company.
        """
        codes = frozenset({"NGX", "NASDAQ", "NYSE"})
        assert ticker_mentions("(LSE: CAT) slipped", codes=codes) == []
        assert ticker_mentions("(NSE: TOTAL) gained", codes=codes) == []


# --------------------------------------------------------------------------------------
# The matches that must still happen
# --------------------------------------------------------------------------------------


class TestTruePositives:
    def test_a_legal_name_in_a_headline_is_the_strongest_evidence_there_is(self) -> None:
        tag = _only("Apple Inc. reports a record September quarter")
        assert tag.method == ALIAS
        assert tag.confidence == ALIAS_MULTI_TOKEN_CONFIDENCE
        # The span runs from the first matched word to the last, so the sentence's own
        # full stop is outside it. The article's characters, not the folded form.
        assert tag.matched_text == "Apple Inc"

    def test_punctuation_and_a_possessive_do_not_stop_a_match(self) -> None:
        tag = _only("Coca-Cola's Nigerian bottler raises prices")
        assert tag.matched_text == "Coca-Cola"
        assert tag.confidence == ALIAS_MULTI_TOKEN_CONFIDENCE

    def test_a_distinctive_one_word_brand_fires_without_a_cue(self) -> None:
        """The recall side of the single-token rule. "Nvidia" is a coined word."""
        tag = _only("Nvidia beats estimates on data-centre demand")
        assert tag.method == ALIAS
        assert tag.confidence == ALIAS_SINGLE_TOKEN_CONFIDENCE

    def test_an_ordinary_word_brand_fires_when_the_legal_form_is_beside_it(self) -> None:
        """ "apple harvest" tags nothing; "Apple Inc" tags Apple. Same word, different cue."""
        assert _securities_matched("Apple Inc said the chip shortage has eased")
        assert not _securities_matched("Apple growers in Jos report a poor season")

    def test_the_longest_name_wins_and_the_company_is_tagged_once(self) -> None:
        """ "Apple" and "Apple Inc." both match; the article names one company, once."""
        tags = match_aliases("Apple Inc. and Apple retail stores", EVERYTHING)
        assert len(tags) == 1
        assert tags[0].confidence == ALIAS_MULTI_TOKEN_CONFIDENCE

    @pytest.mark.parametrize(
        ("headline", "expected_text"),
        [
            # The split-word variant: `JPMORGAN CHASE` against `JP Morgan Chase`, 0.966.
            ("JP Morgan Chase names a new CFO", "JP Morgan Chase"),
            # The other direction: `UNITEDHEALTH GROUP` against `United Health Group`.
            ("United Health Group lifts its forecast", "United Health Group"),
            # A one-letter typo in a long enough name: `PROCTER` against `Proctor`, 0.929.
            ("Proctor & Gamble raises prices again", "Proctor & Gamble"),
        ],
    )
    def test_the_variants_people_actually_write(self, headline: str, expected_text: str) -> None:
        tag = _only(headline)
        assert tag.method == FUZZY
        assert tag.matched_text == expected_text
        assert FUZZY_MIN_CONFIDENCE <= tag.confidence <= FUZZY_MAX_CONFIDENCE

    def test_two_companies_in_one_headline_are_two_tags(self) -> None:
        assert _securities_matched("Microsoft and Nvidia extend their partnership") == {2, 5}

    def test_an_accented_name_matches_its_unaccented_alias(self) -> None:
        aliases = _offline("Nestle Nigeria Plc")
        assert _securities_matched("Nestlé Nigeria lifts interim dividend", aliases) == {1}


# --------------------------------------------------------------------------------------
# The threshold and the confidence scale
# --------------------------------------------------------------------------------------


class TestThresholdAndConfidence:
    def test_the_minimum_alias_length_is_where_a_typo_first_clears_the_threshold(self) -> None:
        """`FUZZY_MIN_ALIAS_CHARS` is derived from `FUZZY_THRESHOLD`, not chosen beside it.

        One substituted character in a string of length n gives (n-1)/n. Below the derived
        length the tier cannot see a typo at all, so everything it would still admit is a
        *different word* - which is the `intel`/`intl` bug.
        """
        at_length = difflib.SequenceMatcher(
            None, "x" * FUZZY_MIN_ALIAS_CHARS, "y" + "x" * (FUZZY_MIN_ALIAS_CHARS - 1)
        ).ratio()
        one_shorter = difflib.SequenceMatcher(
            None, "x" * (FUZZY_MIN_ALIAS_CHARS - 1), "y" + "x" * (FUZZY_MIN_ALIAS_CHARS - 2)
        ).ratio()
        assert at_length >= FUZZY_THRESHOLD
        assert one_shorter < FUZZY_THRESHOLD

    def test_the_documented_measurements_still_hold(self) -> None:
        """The figures the module docstring quotes, recomputed. A docstring can rot."""
        ratio = difflib.SequenceMatcher(None, "unity bank plc", "zenith bank plc").ratio()
        assert round(ratio, 4) == 0.8276
        assert ratio < FUZZY_THRESHOLD, "the worst measured collision must stay below"
        for variant, alias in [
            ("jp morgan chase", "jpmorgan chase"),
            ("proctor gamble", "procter gamble"),
            ("united health group", "unitedhealth group"),
            ("caterpiller", "caterpillar"),
        ]:
            assert difflib.SequenceMatcher(None, variant, alias).ratio() >= FUZZY_THRESHOLD

    def test_confidence_is_one_scale_and_a_guess_never_outranks_a_match(self) -> None:
        """What makes the number comparable across methods, stated as an ordering.

        A brief sorts tags from four tiers into one list. If a 0.95 string similarity were
        stored raw it would outrank a 0.93 exact ticker match, and the list would put a
        guess above something we can point a reader at.
        """
        assert FUZZY_MAX_CONFIDENCE < ALIAS_SINGLE_TOKEN_CONFIDENCE
        assert ALIAS_SINGLE_TOKEN_CONFIDENCE < TICKER_CASHTAG_CONFIDENCE
        assert TICKER_CASHTAG_CONFIDENCE < TICKER_EXCHANGE_CONFIDENCE
        assert TICKER_EXCHANGE_CONFIDENCE < ALIAS_MULTI_TOKEN_CONFIDENCE
        assert ALIAS_MULTI_TOKEN_CONFIDENCE < 1.0, "1.0 is reserved; nothing here is certain"
        assert LLM_MAX_CONFIDENCE < ALIAS_SINGLE_TOKEN_CONFIDENCE

    def test_a_fuzzy_ratio_is_mapped_onto_the_scale_rather_than_stored_raw(self) -> None:
        tag = _only("JP Morgan Chase names a new CFO")
        raw = difflib.SequenceMatcher(None, "jp morgan chase", "jpmorgan chase").ratio()
        assert tag.confidence != pytest.approx(raw), "the ratio is not a probability"
        assert tag.confidence < ALIAS_SINGLE_TOKEN_CONFIDENCE


# --------------------------------------------------------------------------------------
# The ticker tier, which needs a date and the identifier table
# --------------------------------------------------------------------------------------


class TestTickerMentions:
    def test_a_cue_is_what_makes_a_symbol_a_symbol(self) -> None:
        codes = frozenset({"NGX", "NASDAQ", "NYSE"})
        cashtag = ticker_mentions("$CAT gained 2% on the open", codes=codes)
        assert [(m.symbol, m.exchange, m.matched_text) for m in cashtag] == [("CAT", None, "$CAT")]
        assert cashtag[0].confidence == TICKER_CASHTAG_CONFIDENCE

        qualified = ticker_mentions("Caterpillar (NYSE: CAT) lifted guidance", codes=codes)
        assert [(m.symbol, m.exchange) for m in qualified] == [("CAT", "NYSE")]
        assert qualified[0].confidence == TICKER_EXCHANGE_CONFIDENCE

    def test_one_symbol_written_both_ways_is_counted_once(self) -> None:
        codes = frozenset({"NGX", "NASDAQ", "NYSE"})
        assert len(ticker_mentions("NASDAQ: MSFT rose", codes=codes)) == 1


# --------------------------------------------------------------------------------------
# The LLM tier: a Protocol, a stub, and the two checks a model does not get to skip
# --------------------------------------------------------------------------------------


class _StubExtractor:
    """An `EntityExtractor` that returns whatever the test hands it.

    There is no `ANTHROPIC_API_KEY` and the deterministic tiers must be complete without
    one, which is the same arrangement `packages.extract.pipeline.Reconciler` has. What is
    testable here is everything except the request: grounding, resolution, the clamp and
    the drop.
    """

    model_name = "stub"
    prompt_version = "test"

    def __init__(self, mentions: list[EntityMention]) -> None:
        self._mentions = mentions

    def mentions(self, headline: str, body: str | None) -> list[EntityMention]:  # noqa: D102
        del headline, body
        return self._mentions


class TestLlmTier:
    def test_the_stub_satisfies_the_protocol(self) -> None:
        assert isinstance(_StubExtractor([]), EntityExtractor)

    def test_a_mention_that_is_not_in_the_article_is_dropped(self, db_session: Session) -> None:
        """A name from the model's memory is not evidence about *this* article."""
        security = _aliased(db_session, "Apple Inc.")
        item = _article(db_session, "Chip demand cooled in the third quarter", marker="a")
        extractor = _StubExtractor([EntityMention(text="Apple Inc.", confidence=0.9)])
        assert tag_article(db_session, item, extractor=extractor) == []
        assert security.id  # the alias table was not empty; the drop was the model's

    def test_a_grounded_mention_resolves_a_bare_ticker_the_strict_tier_refuses(
        self, db_session: Session
    ) -> None:
        """What the tier is for: the sentence disambiguates what the token cannot."""
        security = _aliased(db_session, "CATERPILLAR INC", exchange="NYSE")
        _ticker(db_session, security, "CAT")
        item = _article(db_session, "CAT shares rose after the guidance lift", marker="b")

        assert tag_article(db_session, item) == [], "the strict tiers refuse a bare symbol"

        extractor = _StubExtractor([EntityMention(text="CAT", confidence=0.95)])
        tags = tag_article(db_session, item, extractor=extractor)
        assert [(t.security_id, t.method) for t in tags] == [(security.id, LLM)]
        assert tags[0].confidence == LLM_MAX_CONFIDENCE, "an uncalibrated self-report is capped"
        assert tags[0].alias_id is None, "the llm tier cites no alias row"

    def test_a_mention_the_model_did_not_believe_is_dropped(self, db_session: Session) -> None:
        security = _aliased(db_session, "CATERPILLAR INC", exchange="NYSE")
        _ticker(db_session, security, "CAT")
        item = _article(db_session, "CAT shares rose after the guidance lift", marker="c")
        extractor = _StubExtractor(
            [EntityMention(text="CAT", confidence=LLM_MIN_CONFIDENCE - 0.01)]
        )
        assert tag_article(db_session, item, extractor=extractor) == []

    def test_a_grounded_mention_that_resolves_to_nothing_tags_nothing(
        self, db_session: Session
    ) -> None:
        """The model cannot name a security we do not hold, however sure it says it is."""
        _aliased(db_session, "Apple Inc.")
        item = _article(db_session, "Kongalende Microfinance opened in Kano", marker="d")
        extractor = _StubExtractor([EntityMention(text="Kongalende", confidence=1.0)])
        assert tag_article(db_session, item, extractor=extractor) == []

    def test_the_deterministic_tiers_win_when_both_fire(self, db_session: Session) -> None:
        """A relaxed match must never displace a strict one for the same security."""
        security = _aliased(db_session, "Apple Inc.")
        item = _article(db_session, "Apple Inc. lifted its dividend", marker="e")
        extractor = _StubExtractor([EntityMention(text="Apple Inc.", confidence=0.85)])
        tags = tag_article(db_session, item, extractor=extractor)
        assert [(t.security_id, t.method) for t in tags] == [(security.id, ALIAS)]


# --------------------------------------------------------------------------------------
# The database: the schema, the trigger, and the round trip
# --------------------------------------------------------------------------------------


class TestSchema:
    def test_the_seed_lands_and_is_readable_as_alias_records(self, db_session: Session) -> None:
        """Asserted first: every test below it is about rows that must exist."""
        before = len(load_aliases(db_session))
        security = _aliased(db_session, "COCA COLA CO", exchange="NYSE")
        records = [r for r in load_aliases(db_session) if r.security_id == security.id]
        assert len(load_aliases(db_session)) - before == 2
        assert {r.alias for r in records} == {"COCA COLA CO", "COCA COLA"}
        assert {r.alias_type for r in records} == {"legal", "brand"}
        assert {r.tokens for r in records} == {("coca", "cola", "co"), ("coca", "cola")}

    def test_an_alias_type_outside_the_contract_is_refused(self, db_session: Session) -> None:
        security = _security(db_session, "Contract Test Plc")
        with (
            pytest.raises(IntegrityError, match="alias_type_is_in_the_contract"),
            db_session.begin_nested(),
        ):
            db_session.add(
                SecurityAlias(
                    security_id=security.id, alias="Contract", alias_type="nickname", source="test"
                )
            )
            db_session.flush()

    @pytest.mark.parametrize(
        ("alias", "constraint"),
        [
            # An empty alias breaks both floors at once and Postgres names whichever it
            # reached first, so the test asserts a refusal rather than which one.
            ("", "alias_is_not_blank|alias_is_long_enough"),
            ("   ", "alias_is_not_blank|alias_is_long_enough"),
            ("X", "alias_is_long_enough"),
        ],
    )
    def test_an_alias_that_names_nothing_is_refused(
        self, db_session: Session, alias: str, constraint: str
    ) -> None:
        security = _security(db_session, f"Blank Alias {alias!r} Plc")
        with pytest.raises(IntegrityError, match=constraint), db_session.begin_nested():
            db_session.add(
                SecurityAlias(
                    security_id=security.id, alias=alias, alias_type="brand", source="test"
                )
            )
            db_session.flush()

    def test_two_characters_are_admitted_because_3m_is_a_real_name(
        self, db_session: Session
    ) -> None:
        """The floor is junk rejection. The match-safety rule is the matcher's, not the DB's."""
        security = _security(db_session, "3M Company")
        db_session.add(
            SecurityAlias(security_id=security.id, alias="3M", alias_type="brand", source="test")
        )
        db_session.flush()
        record = next(r for r in load_aliases(db_session) if r.security_id == security.id)
        assert record.tokens == ("3m",)
        # ...and the matcher still refuses to fire on it without a cue.
        assert match_aliases("The 3m sprint was cancelled", (record,)) == []
        assert match_aliases("3M Co lifted guidance", (record,))

    def test_the_same_alias_in_two_cases_is_one_alias(self, db_session: Session) -> None:
        """`docs/08` §2.6's `UNIQUE (alias, security_id)` would admit both, and both fire."""
        security = _security(db_session, "Case Fold Plc")
        db_session.add(
            SecurityAlias(security_id=security.id, alias="GTCO", alias_type="brand", source="test")
        )
        db_session.flush()
        with (
            pytest.raises(IntegrityError, match="ux_security_aliases_one_per_security"),
            db_session.begin_nested(),
        ):
            db_session.add(
                SecurityAlias(
                    security_id=security.id, alias=" gtco ", alias_type="former", source="test"
                )
            )
            db_session.flush()

    def test_no_two_securities_aliases_collide_at_the_threshold(self, db_session: Session) -> None:
        """The floor under `FUZZY_THRESHOLD`, re-measured against the table itself.

        The threshold was set from a measurement, and a measurement rots. This recomputes
        it over the aliases actually stored and fails the day a seeded name gets close
        enough to another company's to be merged with it. The rows are written here and
        the assertion is scoped to them, so an empty table cannot make it pass vacuously
        and another test's rows cannot make it fail.
        """
        mine = {
            _aliased(db_session, name, exchange="NGX").id
            for name in (
                "Zenith Bank Plc",
                "Unity Bank Plc",
                "Wema Bank Plc",
                "Fidelity Bank Plc",
                "Access Holdings Plc",
                "Dangote Cement Plc",
                "Dangote Sugar Refinery Plc",
                "Guaranty Trust Holding Company Plc",
                "United Bank for Africa Plc",
                "Union Bank of Nigeria Plc",
            )
        }
        records = [r for r in load_aliases(db_session) if r.security_id in mine]
        assert len(records) >= 2 * len(mine), "the seed did not land; nothing to measure"

        worst = max(
            (
                (
                    difflib.SequenceMatcher(None, a.normalised, b.normalised).ratio(),
                    a.alias,
                    b.alias,
                )
                for a, b in itertools.combinations(records, 2)
                if a.company_id != b.company_id
            ),
            default=(0.0, "", ""),
        )
        assert worst[0] < FUZZY_THRESHOLD, (
            f"{worst[1]!r} and {worst[2]!r} belong to different companies and score "
            f"{worst[0]:.4f}, at or above the {FUZZY_THRESHOLD} threshold. One earnings "
            "story would tag both."
        )


class TestTagConstraints:
    @pytest.fixture
    def tagged(self, db_session: Session) -> tuple[NewsItem, Security, int]:
        security = _aliased(db_session, "Apple Inc.")
        item = _article(db_session, "Apple Inc. lifted its dividend", marker="f")
        alias_id = db_session.execute(
            select(SecurityAlias.id).where(SecurityAlias.security_id == security.id).limit(1)
        ).scalar_one()
        return item, security, alias_id

    def test_a_method_outside_the_contract_is_refused(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int]
    ) -> None:
        item, security, _ = tagged
        with (
            pytest.raises(IntegrityError, match="tag_method_is_in_the_contract"),
            db_session.begin_nested(),
        ):
            db_session.add(
                NewsTag(
                    news_id=item.id,
                    security_id=security.id,
                    method="vibes",
                    tagger_version=TAGGER_VERSION,
                    confidence=Decimal("0.9"),
                    matched_text="Apple Inc.",
                    # NULL, so the alias-citation equivalence holds and this row can only
                    # be rejected for the method itself.
                    alias_id=None,
                )
            )
            db_session.flush()

    @pytest.mark.parametrize("confidence", ["0", "-0.1", "1.01"])
    def test_a_confidence_outside_zero_to_one_is_refused(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int], confidence: str
    ) -> None:
        """Zero included: a tag we did not believe still prints the company's name."""
        item, security, alias_id = tagged
        with (
            pytest.raises(IntegrityError, match="tag_confidence_is_a_probability"),
            db_session.begin_nested(),
        ):
            db_session.add(
                NewsTag(
                    news_id=item.id,
                    security_id=security.id,
                    method=ALIAS,
                    tagger_version=TAGGER_VERSION,
                    confidence=Decimal(confidence),
                    matched_text="Apple Inc.",
                    alias_id=alias_id,
                )
            )
            db_session.flush()

    def test_an_alias_tag_must_cite_the_alias_row_it_matched(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int]
    ) -> None:
        """The nullable column, and the reason the CHECK is an equivalence.

        A predicate over a NULL column evaluates to NULL and a CHECK rejects only FALSE -
        migration 0021 is this repository's record of what that costs. Written as an
        equivalence between two NOT NULL expressions, the constraint is total, and this is
        the half a bare comparison would have admitted.
        """
        item, security, _ = tagged
        with (
            pytest.raises(IntegrityError, match="tag_cites_an_alias_row_iff_it_matched_one"),
            db_session.begin_nested(),
        ):
            db_session.add(
                NewsTag(
                    news_id=item.id,
                    security_id=security.id,
                    method=ALIAS,
                    tagger_version=TAGGER_VERSION,
                    confidence=Decimal("0.99"),
                    matched_text="Apple Inc.",
                    alias_id=None,
                )
            )
            db_session.flush()

    def test_an_llm_tag_may_not_cite_an_alias_row(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int]
    ) -> None:
        item, security, alias_id = tagged
        with (
            pytest.raises(IntegrityError, match="tag_cites_an_alias_row_iff_it_matched_one"),
            db_session.begin_nested(),
        ):
            db_session.add(
                NewsTag(
                    news_id=item.id,
                    security_id=security.id,
                    method=LLM,
                    tagger_version=TAGGER_VERSION,
                    confidence=Decimal("0.8"),
                    matched_text="Apple Inc.",
                    alias_id=alias_id,
                )
            )
            db_session.flush()

    def test_a_tag_with_no_evidence_is_refused(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int]
    ) -> None:
        item, security, _ = tagged
        with (
            pytest.raises(IntegrityError, match="tag_matched_text_is_not_blank"),
            db_session.begin_nested(),
        ):
            db_session.add(
                NewsTag(
                    news_id=item.id,
                    security_id=security.id,
                    method=TICKER_TAG,
                    tagger_version=TAGGER_VERSION,
                    confidence=Decimal("0.93"),
                    matched_text="   ",
                    alias_id=None,
                )
            )
            db_session.flush()

    def test_a_tag_cannot_be_rewritten(
        self, db_session: Session, tagged: tuple[NewsItem, Security, int]
    ) -> None:
        """`CLAUDE.md`: no silent overwrites, enforced at the row rather than in review.

        A brief was built on this number. An UPDATE would mean the archive no longer says
        what the brief said, and `docs/08` §2.16's argument is that application code can be
        bypassed at 1am by somebody with a SQL client.
        """
        item, security, alias_id = tagged
        assert (
            store_tags(
                db_session,
                news_id=item.id,
                tags=[
                    CandidateTag(
                        security_id=security.id,
                        method=ALIAS,
                        confidence=0.99,
                        matched_text="Apple Inc.",
                        alias_id=alias_id,
                    )
                ],
            )
            == 1
        )
        with pytest.raises(Exception, match="UPDATE forbidden"), db_session.begin_nested():
            db_session.execute(
                text("UPDATE news_tags SET confidence = 0.10 WHERE news_id = :id"),
                {"id": item.id},
            )


class TestWritingAndReporting:
    def test_a_rerun_writes_nothing_and_a_new_version_writes_beside_it(
        self, db_session: Session
    ) -> None:
        """Why `tagger_version` is in the key: a better matcher adds rows, never overwrites."""
        security = _aliased(db_session, "Apple Inc.")
        item = _article(db_session, "Apple Inc. lifted its dividend", marker="g")
        tags = tag_article(db_session, item)
        assert [t.security_id for t in tags] == [security.id]

        assert store_tags(db_session, news_id=item.id, tags=tags) == 1
        assert store_tags(db_session, news_id=item.id, tags=tags) == 0, "idempotent"
        assert store_tags(db_session, news_id=item.id, tags=tags, tagger_version="p5.2-v2") == 1

        rows = db_session.execute(
            select(NewsTag.tagger_version, NewsTag.confidence, NewsTag.matched_text).where(
                NewsTag.news_id == item.id
            )
        ).all()
        assert {row[0] for row in rows} == {TAGGER_VERSION, "p5.2-v2"}
        assert {row[1] for row in rows} == {Decimal("0.9900")}
        assert {row[2] for row in rows} == {"Apple Inc"}, "the evidence, stored verbatim"

    def test_the_stored_row_carries_the_evidence_a_reviewer_needs(
        self, db_session: Session
    ) -> None:
        security = _aliased(db_session, "COCA COLA CO", exchange="NYSE")
        item = _article(
            db_session,
            "Bottler raises prices",
            body="Coca-Cola's Nigerian bottler has raised prices again.",
            marker="h",
        )
        assert store_tags(db_session, news_id=item.id, tags=tag_article(db_session, item)) == 1
        row = db_session.execute(select(NewsTag).where(NewsTag.news_id == item.id)).scalar_one()
        assert row.security_id == security.id
        assert row.method == ALIAS
        assert row.matched_text == "Coca-Cola", "the body is matched too, and quoted verbatim"
        assert row.alias_id is not None, "a reviewer can reach the row that caused this"

    def test_a_ticker_resolves_on_the_articles_own_date_not_todays(
        self, db_session: Session
    ) -> None:
        """The dated half of the docs/08 tension, exercised end to end.

        `security_aliases` is undated because a name is not reassigned. A **ticker** is,
        and this is the case that proves the two tables divide the way migration 0027 says:
        the symbol is resolved through `identity.resolve_security` with the article's own
        `known_as_of`, so a 2026 article does not reach a security that stopped answering
        to that symbol in 2021.
        """
        gtco = _security(db_session, "Guaranty Trust Holding Company Plc", exchange="NGX")
        _ticker(db_session, gtco, "GUARANTY", valid_to=dt.date(2021, 6, 23))
        _ticker(db_session, gtco, "GTCO", valid_from=dt.date(2021, 6, 24))
        item = _article(db_session, "$GUARANTY slipped on the close", marker="i")
        assert item.known_as_of == dt.date(2026, 9, 20)

        assert tag_article(db_session, item) == [], "GUARANTY identified nothing in 2026"

        current = _article(db_session, "$GTCO slipped on the close", marker="j")
        tags = tag_article(db_session, current)
        assert [(t.security_id, t.method, t.matched_text) for t in tags] == [
            (gtco.id, TICKER_TAG, "$GTCO")
        ]
        assert tags[0].confidence == TICKER_CASHTAG_CONFIDENCE

    def test_a_symbol_two_exchanges_both_answer_tags_neither(self, db_session: Session) -> None:
        """`identity.AmbiguousIdentifierError` is an answer, and the answer is "no tag"."""
        one = _security(db_session, "Twin Listing NG Plc", exchange="NGX")
        two = _security(db_session, "Twin Listing US Inc", exchange="NYSE")
        _ticker(db_session, one, "TWIN")
        _ticker(db_session, two, "TWIN")
        item = _article(db_session, "$TWIN rallied", marker="k")
        assert tag_article(db_session, item) == []

    def test_the_report_names_the_exchange_no_article_could_reach(
        self, db_session: Session
    ) -> None:
        """The loud version of the NGX gap, which is the real state of this database today.

        Every security loaded so far is US-listed and NGX holds none, while all three feeds
        `packages/ingestion/rss.py` reads are Nigerian. A tagger returning nothing for every
        Nigerian article is indistinguishable from a working one unless it says so.
        """
        _aliased(db_session, "Apple Inc.")
        # An NGX security with no alias: present, and still unreachable.
        _security(db_session, "Unaliased Nigeria Plc", exchange="NGX")
        item = _article(db_session, "Apple Inc. lifted its dividend", marker="l")

        report = tag_articles(db_session, [item])
        assert report.articles == 1
        assert report.tagged == 1
        assert report.untagged == 0
        assert report.tags_written == 1
        assert "NGX" in report.unreachable

        ngx = next(entry for entry in report.coverage if entry.exchange == "NGX")
        assert ngx.securities_with_alias == 0
        assert ngx.untaggable is not None and "alias" in ngx.untaggable

    def test_coverage_counts_only_what_is_there(self, db_session: Session) -> None:
        """Deltas, never totals: another test's committed row must not break this."""
        before = {entry.exchange: entry for entry in alias_coverage(db_session)}
        _aliased(db_session, "Walmart Inc.")
        after = {entry.exchange: entry for entry in alias_coverage(db_session)}
        assert after["NASDAQ"].securities - before["NASDAQ"].securities == 1
        assert after["NASDAQ"].securities_with_alias - before["NASDAQ"].securities_with_alias == 1
        assert after["NASDAQ"].aliases - before["NASDAQ"].aliases == 2

    def test_the_exchange_cue_vocabulary_comes_from_the_database(self, db_session: Session) -> None:
        assert exchange_codes(db_session) == frozenset({"NGX", "NASDAQ", "NYSE"})

    def test_seeding_the_same_security_twice_adds_nothing(self, db_session: Session) -> None:
        security = _security(db_session, "Idempotent Plc")
        first = seed_aliases_for(
            db_session, security_id=security.id, legal_name="Idempotent Plc", source="test"
        )
        again = seed_aliases_for(
            db_session, security_id=security.id, legal_name="Idempotent Plc", source="test"
        )
        assert (first, again) == (2, 0)
        count = db_session.execute(
            select(func.count())
            .select_from(SecurityAlias)
            .where(SecurityAlias.security_id == security.id)
        ).scalar_one()
        assert count == 2
