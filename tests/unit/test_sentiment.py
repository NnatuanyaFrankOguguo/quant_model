"""`packages.normalize.sentiment`: the tiered scorer. P5.3.

`SPEC.md` 2F makes the tiering a **cost control** - *"the LLM only for ambiguous cases"* -
and `docs/03` P5.3 makes every score a weak signal: *"Nigerian financial journalism has
different idiom and different framing conventions... do not let a sentiment score drive
anything on its own."* Between them they set what has to be tested, which is not "is the
score right" - it is not, and the module says so - but:

* **is the tiering cheap** - does an unambiguous factual announcement stay out of the
  expensive tier, and
* **is the tiering honest** - does a headline VADER reads confidently and wrongly get
  flagged, rather than passing because the number looked decisive.

Six groups:

* **the derivation** - every constant that was measured rather than chosen is re-measured
  here. `UNSCORED_FINANCE_TERMS` is defined as "absent from VADER's lexicon", so a lexicon
  release that added one of them must fail rather than silently double-count it; the
  conflict threshold is pinned by four ratios that a lexicon change would move.
* **what "ambiguous" means** - the distinction the whole module turns on, stated as the
  two headlines that a band around zero gets backwards.
* **the real corpus** - eleven headlines from `news_items`, verbatim, with the tier each
  one was hand-checked into. This is `docs/03` P5.3's *"verify a sample by hand"* turned
  into a regression test, so a later change has to re-argue the sample rather than quietly
  re-tier it.
* **the label** - three words, at the band VADER publishes, and nothing else.
* **the escalation tier** - built, gated, and refusing loudly. There is no
  `ANTHROPIC_API_KEY`, so every test here stops at the call.
* **the write path** - against the database, because `news_sentiment` carries a
  `no_update` trigger and two CHECKs, and this repository's recurring bug (migration 0021)
  is a constraint that admits what it was written to reject. The only way to know is to
  try the row.

**Seed before asserting.** The test database is empty; every database test writes its own
article and asserts the write landed.

**Constraint tests hold the savepoint inside `pytest.raises`**, following
`tests/unit/test_identity.py` and `tests/unit/test_tagging.py`: the failing flush aborts
the savepoint, and letting `begin_nested()` see the exception is what leaves the outer
transaction usable.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from packages.common.models import DataSource, NewsItem, NewsSentiment, SourceDocument
from packages.normalize.sentiment import (
    AMBIGUOUS,
    AMBIGUOUS_REASONS,
    BULK,
    CLEAR,
    CONFLICTING_WORDS,
    CONTESTED_MINORITY_SHARE,
    DEFAULT_LLM_MODEL,
    FALSE_FRIEND,
    FALSE_FRIEND_TERMS,
    LABEL_BAND,
    LEXICON_GAP,
    MODEL,
    NAME_IN_LEXICON,
    NEGATIVE,
    NEUTRAL,
    NO_SENTIMENT_WORDS,
    POSITIVE,
    PROMPT_VERSION,
    REASONS,
    SYSTEM_PROMPT,
    UNSCORED_FINANCE_TERMS,
    AmbiguousScorer,
    ClaudeSentimentScorer,
    LlmReading,
    MissingApiKeyError,
    Score,
    SentimentReport,
    analyzer,
    label_for,
    model_version,
    parse_llm_reading,
    read,
    route,
    score_articles,
    score_text,
    store_score,
    unscored_articles,
)

#: Dated so that `known_as_of` (the Lagos date of `published_at`) is unambiguous.
PUBLISHED = dt.datetime(2026, 9, 20, 9, 30, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, 10, 0, tzinfo=dt.UTC)

#: Eleven of the 44 Nigerian articles in `news_items` on 2026-09-24, **verbatim**, with the
#: tier and reason each was hand-checked into. Literals rather than a query: the point is
#: what the rule does to *these strings*, and a test that read the table would pass on an
#: empty test database without reading anything.
#:
#: The comment on each says what the hand check found, which is the part `docs/03` P5.3
#: asks for and the part a number cannot carry.
CORPUS: tuple[tuple[str, str, str], ...] = (
    # Stays cheap. Factual announcements with nothing to judge - the 34% of this corpus
    # that makes the tiering worth having.
    ("FG to reopen First Niger Bridge next week after rehabilitation", BULK, NO_SENTIMENT_WORDS),
    (
        "Learn Africa announces retirement of director Egbichi Akinsanya after six years",
        BULK,
        NO_SENTIMENT_WORDS,
    ),
    ("Dangote supplied 71% of Nigeria's August petrol – NMDPRA report", BULK, NO_SENTIMENT_WORDS),
    ("CEOs of the largest Registrars in Nigeria – 2026", BULK, NO_SENTIMENT_WORDS),
    # Escalated on a word VADER does not hold. Each is a real financial event whose
    # direction VADER reports as exactly zero.
    (
        "Petrol imports fall 26% to 14.6 million litres daily in August – NMDPRA",
        AMBIGUOUS,
        LEXICON_GAP,
    ),
    (
        "Nigeria's raw material trade balance swings to a N466.79 billion surplus in H1 2026",
        AMBIGUOUS,
        LEXICON_GAP,
    ),
    (
        "NGX market capitalization hits record N163.06 trillion as ASI rises 0.23%",
        AMBIGUOUS,
        LEXICON_GAP,
    ),
    (
        "NASD targets N12 billion in rights issue to fund technology push, market expansion",
        AMBIGUOUS,
        LEXICON_GAP,
    ),
    # Escalated on a word VADER holds in the wrong sense. These are the ones a band around
    # zero waves through: VADER is confident, and it is confidently reading the wrong
    # language.
    (
        "NTB stop rates crash across tenors after CBN's 350bps rate cut; see new rates",
        AMBIGUOUS,
        FALSE_FRIEND,
    ),
    (
        "MAN warns 23% MPR cut may have little impact with lending rates at 30%",
        AMBIGUOUS,
        FALSE_FRIEND,
    ),
    ("Electricity subsidy may hit N2tn amid tariff freeze", AMBIGUOUS, FALSE_FRIEND),
)


# --------------------------------------------------------------------------------------
# Fixtures. Everything is written by the test, and the write is asserted.
# --------------------------------------------------------------------------------------


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
        item_key=f"sentiment-{marker}",
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
    assert item.id is not None, "the article did not land; nothing below it would be a test"
    return item


def _rows(session: Session, news_id: int) -> list[NewsSentiment]:
    return list(
        session.scalars(
            select(NewsSentiment)
            .where(NewsSentiment.news_id == news_id)
            .order_by(NewsSentiment.model, NewsSentiment.model_version)
        )
    )


class StubScorer:
    """An `AmbiguousScorer` that answers without a key, a network or a model.

    Records what it was asked, because the thing worth asserting about the escalation tier
    is *which* articles reach it - the routing is the deliverable, the call is not.
    """

    model_name = "stub-scorer"
    model_version = "test-v1"

    def __init__(self, score: Decimal = Decimal("-0.5000"), label: str = NEGATIVE) -> None:
        self._score = score
        self._label = label
        self.asked: list[tuple[str, str | None]] = []

    def score(self, headline: str, body: str | None) -> LlmReading:
        self.asked.append((headline, body))
        return LlmReading(score=self._score, label=self._label, rationale="a stub")


# --------------------------------------------------------------------------------------
# The derivation. Every constant that was measured rather than chosen, re-measured.
# --------------------------------------------------------------------------------------


class TestTheDerivation:
    def test_every_gap_term_is_actually_absent_from_the_lexicon(self) -> None:
        """`UNSCORED_FINANCE_TERMS` is *defined* as the words VADER does not score.

        A term VADER already holds would be counted twice - once as valence, once as a
        reason to disbelieve that valence - and the list would have quietly become a
        second lexicon, which is the thing the module's reversibility argument exists to
        avoid. A lexicon release that added one of these must fail here.
        """
        held = sorted(word for word in UNSCORED_FINANCE_TERMS if word in analyzer().lexicon)
        assert held == [], (
            f"vaderSentiment {model_version()} now scores {held}, so these are no longer "
            f"gaps. Move each one to FALSE_FRIEND_TERMS or drop it - leaving it here "
            f"escalates a headline for a word the lexicon can read."
        )

    def test_every_false_friend_is_actually_in_the_lexicon(self) -> None:
        """The mirror. A false friend is a word VADER *does* score, wrongly for finance.

        One that is absent can never fire - `read` requires the lexicon hit - so it would
        sit in the list looking like coverage while covering nothing.
        """
        missing = sorted(word for word in FALSE_FRIEND_TERMS if word not in analyzer().lexicon)
        assert missing == [], (
            f"vaderSentiment {model_version()} does not score {missing}, so they can never "
            f"fire as false friends. They belong in UNSCORED_FINANCE_TERMS."
        )

    def test_the_two_lists_do_not_overlap(self) -> None:
        """A word cannot be both absent from the lexicon and present in it."""
        assert not UNSCORED_FINANCE_TERMS & FALSE_FRIEND_TERMS

    @pytest.mark.parametrize(
        ("positives", "expected"),
        [(1, 0.484), (2, 0.333), (3, 0.239), (4, 0.182)],
    )
    def test_the_documented_measurements_still_hold(self, positives: int, expected: float) -> None:
        """The four ratios `CONTESTED_MINORITY_SHARE` is pinned between.

        The constant is not a taste. It is the only round value between the 2:1 case
        (0.333, escalates) and the 3:1 case (0.239, does not), which is what lets the rule
        be stated as *a lone opposing word is noise against three or more agreeing words
        and a conflict against two or fewer*. If a lexicon change moved these, the
        sentence in the module docstring would be false and the corpus would re-tier
        silently - so it fails here instead.
        """
        words = ["good", "strong", "excellent", "superb"][:positives]
        sentence = f"Zenith Bank posted a {' '.join(words)} result and a terrible outlook"
        assert read(sentence).minority_share == pytest.approx(expected, abs=0.001)

    def test_the_threshold_sits_between_the_two_one_and_three_one_cases(self) -> None:
        two_to_one = read("Zenith Bank posted a good strong result and a terrible outlook")
        three_to_one = read(
            "Zenith Bank posted a good strong excellent result and a terrible outlook"
        )
        assert three_to_one.minority_share < CONTESTED_MINORITY_SHARE <= two_to_one.minority_share

    @pytest.mark.parametrize(
        ("held", "absent"),
        [
            # The same event in two tenses, scored and unscored. This is the single
            # clearest statement that VADER's finance coverage is accidental.
            ("fallen", "fall"),
            ("drop", "dropped"),
            ("crash", "crashed"),
            # Two pairs where only one direction exists at all.
            ("low", "high"),
            ("deficit", "surplus"),
            ("gain", "rise"),
        ],
    )
    def test_the_documented_lexicon_asymmetries_still_hold(self, held: str, absent: str) -> None:
        """The module docstring's table, as assertions.

        These are the evidence for the whole escalation tier. If VADER ever became
        symmetric about them, the argument for `UNSCORED_FINANCE_TERMS` would need
        rewriting - and this is where that would be noticed.
        """
        lexicon = analyzer().lexicon
        assert held in lexicon, f"{held!r} was scored by vaderSentiment {model_version()}"
        assert absent not in lexicon, f"{absent!r} is now scored, so the pair is no longer split"

    def test_a_regulatory_fine_reads_as_that_is_fine(self) -> None:
        """`fine` is **positive** in VADER. The one false friend whose sign is inverted."""
        assert analyzer().lexicon["fine"] > 0

    def test_the_model_column_names_the_scorer_and_the_version_is_read_not_written(self) -> None:
        """`model` plus `model_version` is provenance, and the version comes from the install.

        A hardcoded version is the failure mode `model_version`'s docstring names: it is
        part of the primary key, so a wrong one makes two different scorers collide on one
        row and `no_update` turns the collision into a silent no-op.
        """
        from importlib.metadata import version

        assert MODEL == "vader"
        assert model_version().startswith(version("vaderSentiment"))

    def test_the_version_carries_the_label_band(self) -> None:
        """Migration 0030, and a silent-failure path rather than a cosmetic one.

        `score` does not depend on `LABEL_BAND`; `label` does. With the library version
        alone, rebanding would change what a label means while leaving the primary key
        identical - so the re-score inserts nothing, `no_update` forbids the alternative,
        and the old label survives the new rule with nothing to show for it. The version
        has to identify the whole function from text to (score, label).
        """
        from importlib.metadata import version

        assert model_version() == f"{version('vaderSentiment')}+band{LABEL_BAND.normalize()}"
        assert str(LABEL_BAND.normalize()) in model_version()


# --------------------------------------------------------------------------------------
# What "ambiguous" means. The distinction the module exists to make.
# --------------------------------------------------------------------------------------


class TestWhatAmbiguousMeans:
    def test_a_confidently_neutral_announcement_is_not_ambiguous(self) -> None:
        """The case `docs/03`'s cost control depends on.

        "Access Bank announces board meeting" scores exactly 0.0000 and is *unambiguously
        neutral*: there is nothing to judge, and a tier that sends it to a paid model has
        defeated itself. A band around zero sends it.
        """
        scored = score_text("Access Bank announces board meeting")
        assert scored.score == Decimal("0.0000")
        assert scored.label == NEUTRAL
        assert (scored.tier, scored.reason) == (BULK, NO_SENTIMENT_WORDS)

    def test_a_near_zero_from_cancelling_words_is_ambiguous(self) -> None:
        """The same small number, the other cause.

        A compound near zero because positive and negative words cancelled is an *average
        over disagreement*, not an absence of sentiment. The compound cannot tell the two
        apart - it is one number either way - which is exactly why the rule reads `pos`
        and `neg` instead.
        """
        scored = score_text("GTCO reported profit and weak loan demand")
        assert scored.reading.positive > 0 and scored.reading.negative > 0
        assert scored.reading.minority_share >= CONTESTED_MINORITY_SHARE
        assert (scored.tier, scored.reason) == (AMBIGUOUS, CONFLICTING_WORDS)

    def test_a_band_around_zero_is_a_band_around_silence(self) -> None:
        """The arithmetic that makes the naive rule backwards, pinned.

        VADER normalises the summed valence `x` as `x / sqrt(x**2 + 15)`, so
        `abs(compound) < 0.05` needs `abs(x) < 0.194` - a tenth of one ordinary word, since
        `good` is 1.9. Two words that disagree leave a bigger residue than that, so they
        land *outside* the band, while a headline with no sentiment words at all lands
        exactly on zero and inside it.

        A band therefore escalates the announcements and waves the conflicts through. Both
        halves are asserted, because either one alone could be read as a coincidence.
        """
        announcement = score_text("Access Bank announces board meeting")
        conflict = score_text("GTCO reported profit and weak loan demand")

        assert announcement.score == Decimal("0.0000")
        assert abs(announcement.score) < LABEL_BAND, "a band catches the one with nothing in it"
        assert announcement.tier == BULK, "and this rule does not"

        assert abs(conflict.score) > LABEL_BAND, "a band misses the one whose words disagreed"
        assert conflict.tier == AMBIGUOUS, "and this rule does not"

    def test_the_normalisation_is_what_makes_the_band_that_narrow(self) -> None:
        """The `abs(x) < 0.194` claim above, measured rather than asserted."""
        from vaderSentiment.vaderSentiment import normalize

        assert normalize(0.19) < float(LABEL_BAND) <= normalize(0.20)
        assert normalize(1.9) > 0.4, "one ordinary word is ten times the whole band"

    def test_a_confident_score_over_a_verb_vader_cannot_see_is_ambiguous(self) -> None:
        """The other half, and the expensive one.

        VADER reads `profit` (+) and has no entry for `falls` at all, so it reports a
        clean positive on a headline that says the opposite. The score is decisive, which
        is precisely why a band around zero lets it through untouched.
        """
        scored = score_text("Dangote Cement profit falls despite higher revenue")
        assert scored.score > 0, "VADER reads this as positive"
        assert scored.label == POSITIVE
        assert (scored.tier, scored.reason) == (AMBIGUOUS, LEXICON_GAP)
        assert "falls" in scored.reading.gap_words
        assert "profit" in [word.lower() for word in scored.reading.scored_words]

    def test_a_word_in_the_wrong_sense_is_ambiguous(self) -> None:
        """`fine` is +0.8 in general English and a penalty on a financial page."""
        scored = score_text("SEC hands Zenith Bank a fine over disclosure lapse")
        assert (scored.tier, scored.reason) == (AMBIGUOUS, FALSE_FRIEND)
        assert "fine" in scored.reading.false_friends

    def test_a_company_name_that_scores_as_sentiment_is_ambiguous(self) -> None:
        """A real NGX name. VADER scores `United` at +2.0, so UBA opens every headline
        about itself at +0.42 before a word of news has been read.

        The check needs the names, because there is no way to tell a proper noun from a
        word without knowing which companies the article is about - which P5.2's tagger
        already worked out. Supplying none simply switches the check off, and the test
        below asserts that rather than leaving it implied.
        """
        headline = "United Bank for Africa announces board meeting"
        with_names = score_text(headline, names=["United Bank for Africa"])
        assert with_names.score > 0, "the score comes entirely from the company's own name"
        assert (with_names.tier, with_names.reason) == (AMBIGUOUS, NAME_IN_LEXICON)
        assert with_names.reading.name_words == ("united",)

    def test_without_names_the_name_check_is_simply_off(self) -> None:
        without = score_text("United Bank for Africa announces board meeting")
        assert without.reading.name_words == ()
        assert without.tier == BULK

    def test_a_name_that_is_not_in_the_lexicon_is_not_flagged(self) -> None:
        """The check is about the lexicon, not about names. Most names are not in it."""
        scored = score_text("Dangote Cement announces board meeting", names=["Dangote Cement"])
        assert scored.reading.name_words == ()
        assert (scored.tier, scored.reason) == (BULK, NO_SENTIMENT_WORDS)

    def test_conflict_is_tested_before_the_vocabulary_traps(self) -> None:
        """Order is argued in `route`, so it is pinned here.

        An average over disagreement is the wrong *summary* of the text however the
        vocabulary lands, so it outranks a reason to doubt one word in it.
        """
        reading = read("Zenith Bank posted a good result and a terrible outlook after a rate cut")
        assert reading.false_friends == ("cut",), "the false friend is present"
        assert route(reading) == (AMBIGUOUS, CONFLICTING_WORDS)

    def test_clear_is_reserved_for_one_sided_sentiment_with_no_trap_in_it(self) -> None:
        scored = score_text("Police arrest bike thieves over killing of nine in Jigawa")
        assert (scored.tier, scored.reason) == (BULK, CLEAR)
        assert scored.reading.minority_share == 0.0

    def test_every_reason_is_either_bulk_or_ambiguous_and_the_sets_partition(self) -> None:
        assert set(AMBIGUOUS_REASONS) < set(REASONS)
        assert set(REASONS) - set(AMBIGUOUS_REASONS) == {CLEAR, NO_SENTIMENT_WORDS}

    def test_a_possessive_does_not_hide_a_gap_word(self) -> None:
        """VADER's tokeniser keeps `CBN's` whole; a term list that does not fold the
        possessive misses every possessive form, and Nigerian headlines are full of them."""
        assert "raises" in read("CBN's MPC raises the benchmark rate").gap_words


# --------------------------------------------------------------------------------------
# The real corpus, hand-checked. `docs/03` P5.3: "verify a sample by hand".
# --------------------------------------------------------------------------------------


class TestTheRealCorpus:
    @pytest.mark.parametrize(("headline", "tier", "reason"), CORPUS)
    def test_a_hand_checked_headline_lands_where_it_was_checked_into(
        self, headline: str, tier: str, reason: str
    ) -> None:
        scored = score_text(headline)
        assert (scored.tier, scored.reason) == (tier, reason), (
            f"{headline!r} moved tier. The sample was checked by hand; re-check it rather "
            f"than re-baselining this list. Evidence: scored={scored.reading.scored_words} "
            f"gap={scored.reading.gap_words} false_friend={scored.reading.false_friends}"
        )

    def test_the_sample_escalates_a_minority_of_itself(self) -> None:
        """The tier is a cost control before it is anything else.

        On the full 44 stored articles this rule escalates 11 (25%); a band of any width
        around zero escalates 20 (45%), because 20 of the 44 score exactly 0.0000. The
        eleven below are a deliberately trap-heavy slice of that corpus and still escalate
        a minority - a rule that escalated most of *this* sample would escalate most of
        the feed.
        """
        escalated = [row for row in CORPUS if row[1] == AMBIGUOUS]
        assert len(escalated) < len(CORPUS) - len(escalated) + 4
        assert len(escalated) == 7

    def test_the_ngx_record_high_headline_is_not_read_as_flat(self) -> None:
        """One worth naming: an all-time-high market capitalisation, scored 0.0000.

        `record`, `hits` and `rises` are all absent from VADER's lexicon, so the most
        unambiguously positive NGX headline in the corpus reads as no sentiment at all.
        Without the gap list this is indistinguishable from a board-meeting notice.
        """
        scored = score_text("NGX market capitalization hits record N163.06 trillion as ASI rises")
        assert scored.score == Decimal("0.0000")
        assert scored.reading.scored_words == ()
        assert (scored.tier, scored.reason) == (AMBIGUOUS, LEXICON_GAP)
        assert set(scored.reading.gap_words) == {"record", "rises"}


# --------------------------------------------------------------------------------------
# The label. Three words, at VADER's own band.
# --------------------------------------------------------------------------------------


class TestTheLabel:
    @pytest.mark.parametrize(
        ("compound", "expected"),
        [
            (Decimal("1"), POSITIVE),
            (Decimal("0.0500"), POSITIVE),
            (Decimal("0.0499"), NEUTRAL),
            (Decimal("0.0000"), NEUTRAL),
            (Decimal("-0.0499"), NEUTRAL),
            (Decimal("-0.0500"), NEGATIVE),
            (Decimal("-1"), NEGATIVE),
        ],
    )
    def test_the_band_is_closed_on_both_sides_at_vaders_published_value(
        self, compound: Decimal, expected: str
    ) -> None:
        assert label_for(compound) == expected

    def test_the_label_is_always_one_the_check_constraint_admits(self) -> None:
        """`news_sentiment_label_known` admits three strings and nothing else."""
        for headline, _, _ in CORPUS:
            assert score_text(headline).label in (POSITIVE, NEGATIVE, NEUTRAL)

    def test_a_score_is_within_the_range_the_check_constraint_admits(self) -> None:
        for headline, _, _ in CORPUS:
            assert Decimal("-1") <= score_text(headline).score <= Decimal("1")


# --------------------------------------------------------------------------------------
# What the module refuses to be. `docs/03` P5.3: not a recommendation, not a signal.
# --------------------------------------------------------------------------------------


class TestItRecommendsNothing:
    def test_a_score_carries_no_clock(self) -> None:
        """`scored_at` is set by the writer, never by the compute path.

        A timestamp on a pure result is how a processing time ends up joined to a feature,
        and `docs/08` §1.3 is explicit that only the article's `known_as_of` may be.
        """
        fields = {field.name for field in dataclasses.fields(Score)}
        assert "scored_at" not in fields
        assert not fields & {"as_of", "timestamp", "date"}

    def test_the_report_counts_and_does_not_aggregate(self) -> None:
        """A mean compound over a feed is a weak signal with the caveat rounded off.

        The report is deliberately countable only; if a `mean_score` or `mood` ever
        appears here it will have been added against the docstring, and this fails.
        """
        fields = {field.name for field in dataclasses.fields(SentimentReport)}
        assert not fields & {"mean_score", "average", "mood", "sentiment", "net_score"}

    def test_the_compute_path_is_deterministic(self) -> None:
        """Same text in, same everything out - which is what "no I/O" buys."""
        first = score_text("Dangote Cement profit falls despite higher revenue")
        second = score_text("Dangote Cement profit falls despite higher revenue")
        assert first == second

    def test_the_prompt_forbids_advice(self) -> None:
        """The escalation tier's prompt says it too, because it is the first place to."""
        assert "Do not give investment advice" in SYSTEM_PROMPT
        assert "do not say what anyone should do" in SYSTEM_PROMPT.lower()


# --------------------------------------------------------------------------------------
# The escalation tier. Built, gated, refusing loudly.
# --------------------------------------------------------------------------------------


class TestTheEscalationTier:
    def test_the_stub_satisfies_the_protocol(self) -> None:
        assert isinstance(StubScorer(), AmbiguousScorer)

    def test_there_is_no_key_and_the_refusal_says_what_still_works(self) -> None:
        """`docs/03`'s gate, the same shape `packages.extract.reconciler` takes for P4.2.

        The message matters as much as the exception: the bulk tier covers most of the
        corpus without a key, and a refusal that did not say so reads like the feature is
        broken rather than partly gated.
        """
        with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY is not set"):
            _ = ClaudeSentimentScorer().api_key

    def test_the_escalation_tier_uses_the_cheap_model_spec_2e_reserves_for_it(self) -> None:
        """`SPEC.md` §2E puts a Haiku-class model on sentiment and keeps the expensive one
        for the arbitrator. Taking the expensive model in the escalation tier of a
        cost-control design would dismantle the design."""
        assert DEFAULT_LLM_MODEL == "claude-haiku-4-5"
        assert ClaudeSentimentScorer().model_name == DEFAULT_LLM_MODEL

    def test_this_tiers_version_is_the_prompt_not_a_library(self) -> None:
        """For a hosted model the prompt is the part of the scorer that we control and
        that changes, so two prompts against one model are two scorers and must not share
        a primary key."""
        assert ClaudeSentimentScorer().model_version == PROMPT_VERSION

    def test_the_body_is_context_for_this_tier_and_labelled_as_such(self) -> None:
        """The bulk tier scores the headline alone; this one gets the summary too, because
        a model reading for meaning is helped by text that distorts a normalised average."""
        scorer = ClaudeSentimentScorer()
        assert scorer.user_prompt("A headline", None) == "HEADLINE: A headline"
        with_body = scorer.user_prompt("A headline", "Some summary text.")
        assert "HEADLINE: A headline" in with_body
        assert "Some summary text." in with_body

    def test_a_well_formed_answer_is_read(self) -> None:
        reading = parse_llm_reading(
            '{"score": -0.35, "label": "negative", "rationale": "a rate cut squeezes margins"}'
        )
        assert reading == LlmReading(
            score=Decimal("-0.3500"),
            label=NEGATIVE,
            rationale="a rate cut squeezes margins",
        )

    @pytest.mark.parametrize(
        "payload",
        [
            '{"score": 1.4, "label": "positive", "rationale": "x"}',
            '{"score": "up", "label": "positive", "rationale": "x"}',
            '{"score": true, "label": "positive", "rationale": "x"}',
            '{"score": 0.1, "label": "bullish", "rationale": "x"}',
            '{"label": "positive", "rationale": "x"}',
        ],
    )
    def test_an_answer_the_schema_would_reject_is_refused_here_too(self, payload: str) -> None:
        """`output_config` makes a malformed answer unlikely rather than impossible, and a
        score outside [-1, 1] would otherwise be caught by `news_sentiment_score_in_range`
        at the far end of a transaction."""
        with pytest.raises(ValueError, match="response"):
            parse_llm_reading(payload)


# --------------------------------------------------------------------------------------
# The write path. Against the database, because the constraints are the design.
# --------------------------------------------------------------------------------------


def _neutral(session: Session, news_id: int) -> bool:
    """A plain bulk-tier neutral row. The tier is passed rather than defaulted because
    migration 0030 gives the column no server default: a row must not be able to claim a
    tier nobody decided."""
    return store_score(
        session,
        news_id=news_id,
        score=Decimal("0"),
        label=NEUTRAL,
        tier=BULK,
        reason=NO_SENTIMENT_WORDS,
    )


class TestTheWritePath:
    def test_a_score_lands_and_can_be_read_back(self, db_session: Session) -> None:
        item = _article(db_session, "Access Bank announces board meeting", marker="w1")
        scored = score_text(item.headline)
        assert (
            store_score(
                db_session,
                news_id=item.id,
                score=scored.score,
                label=scored.label,
                tier=scored.tier,
                reason=scored.reason,
            )
            is True
        )
        rows = _rows(db_session, item.id)
        assert len(rows) == 1
        assert rows[0].model == MODEL
        assert rows[0].model_version == model_version()
        assert rows[0].score == Decimal("0.0000")
        assert rows[0].label == NEUTRAL

    def test_the_same_scorer_run_twice_writes_once(self, db_session: Session) -> None:
        """A re-run is a no-op deliberately: the second run's `scored_at` is not new
        information, and `ON CONFLICT DO NOTHING` is the only option a `no_update` trigger
        leaves."""
        item = _article(db_session, "Access Bank announces board meeting", marker="w2")
        assert _neutral(db_session, item.id) is True
        assert _neutral(db_session, item.id) is False
        assert len(_rows(db_session, item.id)) == 1

    def test_a_new_version_writes_beside_the_old_one_rather_than_over_it(
        self, db_session: Session
    ) -> None:
        """Migration 0029's stated reason for `model_version` being in the key, exercised.

        This is what makes the choice of VADER reversible: a second scorer adds a row, the
        old score survives, and the two can be compared.
        """
        item = _article(db_session, "Dangote Cement profit falls", marker="w3")
        store_score(
            db_session,
            news_id=item.id,
            score=Decimal("0.44"),
            label=POSITIVE,
            tier=BULK,
            reason=CLEAR,
        )
        store_score(
            db_session,
            news_id=item.id,
            score=Decimal("-0.60"),
            label=NEGATIVE,
            tier=AMBIGUOUS,
            reason=LEXICON_GAP,
            model="claude-haiku-4-5",
            version=PROMPT_VERSION,
        )
        rows = _rows(db_session, item.id)
        assert len(rows) == 2
        assert {row.model for row in rows} == {MODEL, "claude-haiku-4-5"}
        assert {row.label for row in rows} == {POSITIVE, NEGATIVE}

    def test_the_no_update_trigger_makes_a_re_score_an_insert_or_nothing(
        self, db_session: Session
    ) -> None:
        """The claim the whole reversibility argument rests on, tried rather than assumed."""
        item = _article(db_session, "Access Bank announces board meeting", marker="w4")
        _neutral(db_session, item.id)
        with pytest.raises(DatabaseError), db_session.begin_nested():
            db_session.execute(
                text("UPDATE news_sentiment SET label = 'positive' WHERE news_id = :id"),
                {"id": item.id},
            )
        assert _rows(db_session, item.id)[0].label == NEUTRAL

    @pytest.mark.parametrize(
        ("score", "label"),
        [(Decimal("1.5"), POSITIVE), (Decimal("-1.5"), NEGATIVE), (Decimal("0"), "bullish")],
    )
    def test_the_check_constraints_reject_what_they_were_written_to_reject(
        self, db_session: Session, score: Decimal, label: str
    ) -> None:
        """Migration 0021 is this repository's reminder that a CHECK can admit what it was
        written to reject, and the only way to know is to try the row."""
        item = _article(db_session, "Access Bank announces board meeting", marker="w5")
        with pytest.raises(IntegrityError), db_session.begin_nested():
            store_score(
                db_session,
                news_id=item.id,
                score=score,
                label=label,
                tier=BULK,
                reason=CLEAR,
            )

    @pytest.mark.parametrize(
        ("tier", "reason"),
        [
            ("bulk", LEXICON_GAP),
            (AMBIGUOUS, CLEAR),
            (AMBIGUOUS, NO_SENTIMENT_WORDS),
            ("unsure", CLEAR),
            (BULK, "vibes"),
        ],
    )
    def test_the_tier_and_the_reason_must_agree(
        self, db_session: Session, tier: str, reason: str
    ) -> None:
        """Migration 0030. The two are not independent: `clear` and `no_sentiment_words`
        are the lexicon being trusted and the other four are it not being, so a row
        saying "ambiguous because the reading was clear" is a bug in the router and the
        database should not hold it. Tried rather than assumed, per migration 0021."""
        item = _article(db_session, "Access Bank announces board meeting", marker="w7")
        with pytest.raises(IntegrityError), db_session.begin_nested():
            store_score(
                db_session,
                news_id=item.id,
                score=Decimal("0"),
                label=NEUTRAL,
                tier=tier,
                reason=reason,
            )

    def test_the_router_never_produces_a_pair_the_database_would_reject(self) -> None:
        """The other half of the above: every pair `route` can emit must be storable."""
        for reason in REASONS:
            tier = BULK if reason in (CLEAR, NO_SENTIMENT_WORDS) else AMBIGUOUS
            assert (tier == BULK) == (reason in (CLEAR, NO_SENTIMENT_WORDS))
            assert (reason in AMBIGUOUS_REASONS) == (tier == AMBIGUOUS)

    def test_unscored_articles_is_keyed_on_the_scorer_not_on_the_article(
        self, db_session: Session
    ) -> None:
        """An article scored by one model is *unscored* by the next, which is what lets a
        re-score under a new version find its work."""
        item = _article(db_session, "Access Bank announces board meeting", marker="w6")
        version = model_version()
        assert item.id in {
            row.id for row in unscored_articles(db_session, model=MODEL, version=version)
        }

        _neutral(db_session, item.id)
        assert item.id not in {
            row.id for row in unscored_articles(db_session, model=MODEL, version=version)
        }
        assert item.id in {
            row.id for row in unscored_articles(db_session, model=MODEL, version="9.9.9")
        }
        assert item.id in {
            row.id
            for row in unscored_articles(db_session, model="claude-haiku-4-5", version=version)
        }


class TestTheBatch:
    def test_an_escalated_article_still_gets_its_vader_row(self, db_session: Session) -> None:
        """Withholding it would make "the lexicon was unsure" indistinguishable from "this
        was never scored", which is the silent absence this repository keeps finding."""
        item = _article(
            db_session, "Dangote Cement profit falls despite higher revenue", marker="b1"
        )
        report = score_articles(db_session, [item])
        assert report.escalated == 1
        assert report.escalated_scored == 0, "there is no key, so nothing re-read it"
        assert report.rows_written == 1
        rows = _rows(db_session, item.id)
        assert [row.model for row in rows] == [MODEL]

    def test_with_a_scorer_the_escalated_article_gets_a_second_row(
        self, db_session: Session
    ) -> None:
        item = _article(
            db_session,
            "Dangote Cement profit falls despite higher revenue",
            body="The company reported lower earnings for the half year.",
            marker="b2",
        )
        scorer = StubScorer()
        report = score_articles(db_session, [item], scorer=scorer)
        assert report.escalated == 1
        assert report.escalated_scored == 1
        assert report.rows_written == 2
        assert scorer.asked == [(item.headline, item.body)], "the body is this tier's context"
        rows = _rows(db_session, item.id)
        assert {row.model for row in rows} == {MODEL, "stub-scorer"}

    def test_an_unambiguous_article_never_reaches_the_scorer(self, db_session: Session) -> None:
        """The cost control, asserted at the only place it can be: the call that is not
        made."""
        item = _article(db_session, "Access Bank announces board meeting", marker="b3")
        scorer = StubScorer()
        report = score_articles(db_session, [item], scorer=scorer)
        assert scorer.asked == []
        assert report.escalated == 0
        assert report.by_reason[NO_SENTIMENT_WORDS] == 1

    def test_the_report_counts_every_reason_and_the_counts_sum_to_the_batch(
        self, db_session: Session
    ) -> None:
        items = [
            _article(db_session, headline, marker=f"b4-{index}")
            for index, (headline, _, _) in enumerate(CORPUS)
        ]
        report = score_articles(db_session, items, store=False)
        assert set(report.by_reason) == set(REASONS)
        assert sum(report.by_reason.values()) == len(CORPUS)
        assert report.rows_written == 0, "store=False writes nothing"
        assert report.escalated == sum(1 for _, tier, _ in CORPUS if tier == AMBIGUOUS)
        assert 0 < report.escalation_rate < 1

    def test_names_reach_the_name_check_through_the_batch(self, db_session: Session) -> None:
        item = _article(db_session, "United Bank for Africa announces board meeting", marker="b5")
        plain = score_articles(db_session, [item], store=False)
        assert plain.escalated == 0
        named = score_articles(
            db_session, [item], store=False, names_for={item.id: ["United Bank for Africa"]}
        )
        assert named.by_reason[NAME_IN_LEXICON] == 1
