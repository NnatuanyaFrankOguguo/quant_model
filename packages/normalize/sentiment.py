"""How a headline reads, and when to stop trusting the cheap answer. P5.3.

`SPEC.md` 2F specifies the tiering and says what it is for: *"FinBERT/VADER for bulk cheap
tagging, LLM for ambiguous headlines"*. It is a **cost-control** design. Most headlines are
unambiguous, an LLM call costs 300-500x a lexicon lookup, and a tier that escalates
everything is not a tier.

The bulk tier is `vaderSentiment` 3.3.2, declared in the `data` extra. The choice is
reversible by construction: `model_version` is in `news_sentiment`'s primary key
(migration 0029), so a second scorer writes **beside** this one rather than over it, and
the `no_update` trigger makes that the only option. That reversibility is why the cheap
option was taken first.

## Every score here is a weak signal, and this module says so in code

`docs/03` P5.3, in full:

> Sentiment models are trained on US financial English. Nigerian financial journalism has
> different idiom and different framing conventions. Treat the scores as a weak signal,
> verify a sample by hand, and **do not let a sentiment score drive anything on its own.**

So: nothing in this module recommends anything, and no constant below is a decision
boundary. :data:`LABEL_BAND` turns a number into one of three words the schema accepts and
is VADER's own published convention rather than ours; :data:`CONTESTED_MINORITY_SHARE`
decides *which tier reads a headline*, not what anybody should do about it. A threshold
that routed work is not a threshold that traded.

## What "ambiguous" means here, and what it deliberately does not mean

The obvious rule is a band around zero - escalate when `abs(compound) < eps`. It is wrong,
and measurably so. Of the 44 Nigerian articles in `news_items`, **20 score exactly 0.0000**,
because VADER found no word it scores at all. A band of any width sends all twenty to a
paid model, and most of them are announcements with nothing to judge:

    "FG to reopen First Niger Bridge next week after rehabilitation"     0.0000
    "Dangote supplied 71% of Nigeria's August petrol - NMDPRA report"    0.0000
    "Learn Africa announces retirement of director Egbichi Akinsanya"    0.0000

Those are not ambiguous. They are **unambiguously neutral**, and a compound of zero is the
right answer. Meanwhile the same band lets through, at face value, every headline VADER
scored *confidently and wrongly* - which on this corpus is where the real damage is.

Worse, the band does not even catch the cases it was reached for. VADER normalises the
summed valence `x` as `x / sqrt(x**2 + 15)`, which is steep near the origin: staying inside
`abs(compound) < 0.05` needs `abs(x) < 0.194`, **a tenth of one ordinary word** (`good` is
1.9). Two sentiment words that disagree do not cancel that finely - *"reported profit and
weak demand"* leaves a residue and lands at -0.1280, outside the band, escalated by nothing.

So a band around zero is not a band around ambiguity. It is a band around *silence*: it
catches every headline with no sentiment words in it and misses almost every headline whose
sentiment words disagreed. It is precisely backwards, and
`test_a_band_around_zero_is_a_band_around_silence` pins the arithmetic.

A zero therefore has to be read for its cause, and there are three:

* **no sentiment words** - VADER found nothing to score and there is nothing in the text
  it is known to be blind to. Neutral, cheaply, and that is the finding. :data:`CLEAR`'s
  quiet twin, and the reason the tier pays for itself.
* **conflicting words** - VADER found sentiment on both sides and they cancelled. The
  compound is an *average over disagreement*, which is a different object from an absence
  of sentiment and the arithmetic cannot tell them apart. :data:`CONFLICTING_WORDS`.
* **a gap in the lexicon** - the headline's financial verb is one VADER does not hold, so
  its silence is a vocabulary failure rather than a reading. :data:`LEXICON_GAP`.

and a confident score has two more causes worth doubting:

* **a false friend** - VADER scored a word whose general-English sense is not its
  financial one. :data:`FALSE_FRIEND`.
* **a company's own name** - the name scored as sentiment. :data:`NAME_IN_LEXICON`.

## The gap list is derived, not invented

:data:`UNSCORED_FINANCE_TERMS` holds only words **absent from VADER's lexicon**, and a test
asserts that (`test_every_gap_term_is_actually_absent_from_the_lexicon`). A word VADER
already scores does not belong: it would be double-counted and the module would be quietly
building a second lexicon, which is the one thing the reversibility argument above exists
to avoid. Nothing here produces a score. The stored score is VADER's, always.

What the derivation turned up is the argument for the whole tier. VADER's coverage of
financial movement vocabulary is not thin, it is **accidental**:

    fallen  -1.5   but  fall, falls, fell      absent
    drop    -1.1   but  drops, dropped         absent
    gain    +2.4   but  rise, surge, soar,
                        rally, climb, jump     absent
    low     -1.1   but  high                   absent
    deficit -1.7   but  surplus                absent
    crash   -1.7   but  crashes, crashed       absent
    fine    +0.8    <-  a regulatory fine reads as "that's fine"

"Profit has fallen" is negative and "Profit falls" is neutral, for the same event. A record
low is negative and a record high is nothing. That is not a model with a view about
finance; it is a general-English lexicon that happens to intersect one.

## The conflict threshold is derived too

:data:`CONTESTED_MINORITY_SHARE` is 0.30, and it is pinned by a countable fact rather than
chosen. Measured against VADER 3.3.2 on one sentence with words of ordinary strength:

    1 positive : 1 negative   minority share 0.484
    2 positive : 1 negative   minority share 0.333   <- escalates
    3 positive : 1 negative   minority share 0.239   <- does not
    4 positive : 1 negative   minority share 0.182

0.30 is the only round value between the 2:1 and 3:1 cases, so the rule states itself: **a
lone opposing word is noise against three or more agreeing words and a conflict against two
or fewer.** `test_the_documented_measurements_still_hold` re-measures all four, so a lexicon
change that moved them would fail rather than silently re-tier the corpus.

## The headline is the unit

`compound` is normalised over the whole text, so appending an RSS summary re-weights the
headline's own words by however much summary that feed happened to serve - and these feeds
serve 199 to 518 characters of it. On the 44 stored articles, **scoring headline+body
instead of the headline changes the label of 12**. Two publishers carrying one wire story
are already two rows (`NewsItem.content_hash` is over headline and body together); giving
them two different sentiments for a reason that is about the feed and not about the news
would compound that.

The body is not discarded - it is handed to the ambiguous tier as context, which is where
paying for a longer read is worth it.

## Point in time

`scored_at` is provenance: the moment this process ran. **The point-in-time date of a
sentiment row is the article's `NewsItem.known_as_of`**, and a downstream feature joined on
`scored_at` would be reading the scheduler's cron entry as if it were the market
(`docs/08` §1.3). Nothing in this module returns `scored_at` for anything but writing it.

## What this module is not allowed to do

Recommend. Nothing here emits a view, a direction, a signal, or a threshold anybody is
meant to act at. :class:`SentimentReport` counts articles and tiers; it does not aggregate
scores into a mood, because a mean of weak signals is a weak signal with the caveat
rounded off.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.models import NewsItem, NewsSentiment
from packages.common.timez import utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only; the runtime import is deferred
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

__all__ = [
    "AMBIGUOUS",
    "AMBIGUOUS_REASONS",
    "BATCH_LIMIT",
    "BULK",
    "CLEAR",
    "CONFLICTING_WORDS",
    "CONTESTED_MINORITY_SHARE",
    "DEFAULT_LLM_MODEL",
    "FALSE_FRIEND",
    "FALSE_FRIEND_TERMS",
    "LABEL_BAND",
    "LEXICON_GAP",
    "MODEL",
    "NAME_IN_LEXICON",
    "NEGATIVE",
    "NEUTRAL",
    "NO_SENTIMENT_WORDS",
    "PROMPT_VERSION",
    "REASONS",
    "SCORE_PLACES",
    "SYSTEM_PROMPT",
    "UNSCORED_FINANCE_TERMS",
    "AmbiguousScorer",
    "ClaudeSentimentScorer",
    "LlmReading",
    "MissingApiKeyError",
    "Reading",
    "Score",
    "SentimentReport",
    "analyzer",
    "label_for",
    "lexicon_scores",
    "model_version",
    "parse_llm_reading",
    "read",
    "route",
    "score_articles",
    "score_new_articles",
    "score_text",
    "store_score",
    "unscored_articles",
]

_log = structlog.get_logger(__name__)

# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------

#: `news_sentiment.model`. The scorer, not the library: a second tier writing under
#: `claude-haiku-4-5` is a different model on the same article, which is what the composite
#: primary key is for.
MODEL = "vader"

#: The three words `news_sentiment_label_known` admits. A label is a restatement of the
#: score in the vocabulary the schema accepts - never a view, and never a recommendation.
POSITIVE = "positive"
NEGATIVE = "negative"
NEUTRAL = "neutral"

#: VADER's **own** published convention for turning a compound into a label (Hutto &
#: Gilbert's README: positive at >= 0.05, negative at <= -0.05, neutral between). It is
#: pinned here rather than chosen here, and that is what makes `model_version` honest: the
#: label is a property of "vaderSentiment 3.3.2" in the same sense the score is.
#:
#: **Changing this number changes what a row means without changing its key**, and the
#: `no_update` trigger means the old label would simply survive the re-score. If a future
#: banding is genuinely ours rather than the library's, it has to be carried in
#: `model_version` - see the module docstring and `store_score`.
LABEL_BAND = Decimal("0.05")

#: `score` is NUMERIC and compared for equality in tests (`docs/08` §1.5). VADER rounds its
#: own compound to four places, so this quantisation is exact rather than lossy.
SCORE_PLACES = Decimal("0.0001")


def model_version() -> str:
    """The installed `vaderSentiment` version, read rather than hardcoded.

    A constant compiled into the module goes stale silently - the same failure
    `packages.extract.reconciler.ModelPricing` refuses to accept for prices. Here it would
    be worse than stale: the version is part of the primary key, so a wrong one makes two
    genuinely different scorers collide on one row, and `no_update` turns that into a
    silent no-op rather than an error.
    """
    from importlib.metadata import version  # noqa: PLC0415 - stdlib, kept beside its use

    # The band is part of the version, and migration 0030 records why. `score` does not
    # depend on `LABEL_BAND`; `label` does. With the library version alone, rebanding
    # would change what a label means while leaving the primary key identical - so the
    # re-score inserts nothing, `no_update` forbids the alternative, and the old label
    # silently survives the new rule. This makes (model, model_version) identify the
    # whole function from text to (score, label), which is what a version is for.
    return f"{version('vaderSentiment')}+band{LABEL_BAND.normalize()}"


# --------------------------------------------------------------------------------------
# Tiers and the reason a headline landed in one
# --------------------------------------------------------------------------------------

#: Scored by the lexicon and left there. The tier that has to hold most of the corpus for
#: the design to be worth anything.
BULK = "bulk"
#: Scored by the lexicon, and flagged because the lexicon is not to be trusted on it.
AMBIGUOUS = "ambiguous"

#: VADER found one-sided sentiment, holds the vocabulary in play, and nothing in the text
#: is a known trap. Bulk.
CLEAR = "clear"
#: VADER found no word it scores, and no word it is known to be blind to. A compound of
#: zero here is a reading, not a shrug. Bulk - and this is where the cost control lives.
NO_SENTIMENT_WORDS = "no_sentiment_words"
#: Sentiment on both sides, neither dominant. The compound is an average over
#: disagreement. Ambiguous.
CONFLICTING_WORDS = "conflicting_words"
#: A financial movement or distress term VADER does not hold. Ambiguous.
LEXICON_GAP = "lexicon_gap"
#: A word VADER scores in a sense that is not its financial one. Ambiguous.
FALSE_FRIEND = "false_friend"
#: A company's own name carried the score. Ambiguous.
NAME_IN_LEXICON = "name_in_lexicon"

REASONS = (
    CLEAR,
    NO_SENTIMENT_WORDS,
    CONFLICTING_WORDS,
    LEXICON_GAP,
    FALSE_FRIEND,
    NAME_IN_LEXICON,
)
#: The reasons that escalate. Everything else is answered for the price of a dict lookup.
AMBIGUOUS_REASONS = (CONFLICTING_WORDS, LEXICON_GAP, FALSE_FRIEND, NAME_IN_LEXICON)

#: The share of the polar mass that has to point against the majority before the compound
#: is read as disagreement rather than as sentiment. Derived, not chosen - the module
#: docstring gives the four measurements and `test_the_documented_measurements_still_hold`
#: re-runs them.
CONTESTED_MINORITY_SHARE = 0.30

# --------------------------------------------------------------------------------------
# The two word lists. Neither one scores anything.
# --------------------------------------------------------------------------------------

#: Financial movement, quantity and distress vocabulary that **VADER does not hold**.
#: Membership is asserted against the live lexicon by
#: `test_every_gap_term_is_actually_absent_from_the_lexicon`, so a lexicon that grew to
#: cover one of these fails the suite instead of quietly double-counting it.
#:
#: Deliberately carries no direction. A direction would make this a second lexicon, and
#: finance will not supply one anyway: falling inflation is good and falling revenue is
#: bad, and the word is the same word. The claim being made is only *"VADER cannot see the
#: verb this headline turns on"*, which is true regardless of which way the verb points.
UNSCORED_FINANCE_TERMS = frozenset(
    {
        # Price and quantity, downward. `fallen` and `drop` are absent from this list
        # because VADER *does* hold them - which is the asymmetry the docstring is about,
        # not an omission.
        "fall", "falls", "fell", "decline", "declines", "declined", "drops", "dropped",
        "slump", "slumps", "slumped", "plunge", "plunges", "plunged", "tumble", "tumbles",
        "tumbled", "shed", "sheds", "slid", "slide", "slides", "dip", "dips", "dipped",
        "contraction", "contracted", "trough",
        # Price and quantity, upward. `gain` and `growth` are VADER's; everything a
        # Nigerian market report actually uses is not.
        "rise", "rises", "rose", "risen", "surge", "surges", "surged", "soar", "soars",
        "soared", "rally", "rallies", "rallied", "climb", "climbs", "climbed", "jump",
        "jumps", "jumped", "rebound", "rebounds", "rebounded", "recover", "recovers",
        "recovery", "expansion", "surplus", "peak", "record", "high",
        # The naira, which is the single most consequential number in this corpus and
        # about which VADER holds no word at all.
        "devalue", "devalued", "devaluation", "depreciate", "depreciated", "depreciation",
        "inflow", "inflows", "outflow", "outflows",
        # Credit and distress.
        "downgrade", "downgraded", "default", "defaults", "defaulted", "arrears",
        "shortfall", "impairment", "provisioning", "writedown", "writedowns",
        "insolvency", "liquidation", "receivership", "forbearance", "stagflation",
        "stagnate", "stagnant", "glut", "backlog", "underperform", "underperformed",
        "scarcity", "layoff", "layoffs", "retrench", "retrenchment",
        # Regulatory and market-structure events. These are announcements, and whether one
        # is good news is a question about the subject - which is exactly why the tier
        # that can read the subject should have them.
        "halt", "halts", "halted", "suspends", "suspension", "delist", "delisted",
        "delisting", "probe", "probes", "moratorium", "embargo", "fines", "penalties",
        # Capital actions and rates. Corporate-finance vocabulary, none of it in a
        # general-English lexicon, most of it two-sided: a rights issue funds growth and
        # dilutes holders in the same sentence.
        "dividend", "dividends", "payout", "upgrade", "upgraded", "oversubscribed",
        "recapitalisation", "recapitalization", "divest", "divestment", "buyback",
        "repurchase", "issuance", "hike", "hikes", "hiked", "raise", "raises", "raised",
        # Inflections of words VADER holds in the singular and not the plural, or the
        # present and not the past. Listed so the tiering does not depend on tense.
        "crashes", "crashed",
    }
)  # fmt: skip

#: Words VADER **does** score, in a sense that does not survive the move into a financial
#: page. The valence is in the comment because the point is not that these are hard words -
#: it is that VADER already has an answer and the answer is about a different language.
FALSE_FRIEND_TERMS = frozenset(
    {
        "fine",  # +0.8, as in "that's fine". A regulatory fine is a penalty; sign inverted
        "cut",  # -1.1, and a rate cut, a tax cut and a job cut are three different events
        "cuts",  # -1.2. The most common false negative in this corpus
        "slash",  # -1.1, the same event reported louder
        "slashes",  # -0.8
        "slashed",  # -0.9
        "crash",  # -1.7. "NTB stop rates crash" is yields falling, which is not a crash
        "freeze",  # +0.2. A tariff or price freeze; the valence is noise in either direction
        "low",  # -1.1. A record low of inflation and of revenue are opposite events - and
        # VADER holds no entry for `high` at all, so the pair is not even symmetric
        "strike",  # -0.5. Industrial action, a strike price, or a deal struck
        "strikes",  # -1.5
        "stop",  # "stop rates" is the clearing yield at a Treasury-bill auction. Very
        "stops",  # Nigerian, very common here, and not a stop of anything
    }
)

#: A trailing possessive, straight or curly. VADER's tokeniser keeps `Nigeria's` and
#: `CBN’s` whole, and a term list that does not fold them misses every possessive form.
_POSSESSIVE = re.compile(r"[’'ʼ]s$")
#: Everything a word may be wrapped in that is not part of it.
_EDGE = "\"'’‘“”()[]{}.,;:!?-–—"


def _normalise(word: str) -> str:
    """One of VADER's tokens, folded to the form the word lists are written in."""
    return _POSSESSIVE.sub("", word.strip(_EDGE).lower())


# --------------------------------------------------------------------------------------
# The bulk tier
# --------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def analyzer() -> SentimentIntensityAnalyzer:
    """The VADER analyzer, built once.

    Imported inside the call rather than at module scope, for the reason
    `packages.extract.reconciler.ClaudeReconciler` defers `anthropic` and
    `packages.ingestion.documents` defers `pdfplumber`: `vaderSentiment` lives in the
    `data` extra, and a module-level import would make importing `packages.normalize` fail
    on a machine that installed only the defaults.

    Cached because the constructor parses a 7.5k-entry lexicon file off disk, and the
    scheduler scores a feed's worth of articles in a loop.
    """
    from vaderSentiment.vaderSentiment import (  # noqa: PLC0415 - `data` extra; see above
        SentimentIntensityAnalyzer,
    )

    return SentimentIntensityAnalyzer()


def lexicon_scores(word: str) -> bool:
    """Whether VADER holds a valence for this word. The predicate the gap list is built on."""
    return _normalise(word) in analyzer().lexicon


@dataclass(frozen=True)
class Reading:
    """What VADER said about one text, with the evidence for it.

    The evidence is here because `docs/03` P5.3 asks for a sample verified by hand, and a
    bare compound cannot be checked by hand - you cannot tell `-0.66` driven by the word
    *cancer* in an institution's name from `-0.66` driven by the news.
    """

    text: str
    #: VADER's `compound`, in [-1, 1].
    compound: Decimal
    #: VADER's `pos` and `neg` shares. Their sum is the polar mass; `neu` is the rest.
    positive: float
    negative: float
    #: The words VADER actually scored, in the order they appear. What makes a hand check
    #: a check rather than a second opinion.
    scored_words: tuple[str, ...]
    #: Words from :data:`UNSCORED_FINANCE_TERMS` present in the text.
    gap_words: tuple[str, ...]
    #: Words from :data:`FALSE_FRIEND_TERMS` that VADER scored here.
    false_friends: tuple[str, ...]
    #: Words belonging to a company name supplied by the caller that VADER scored.
    name_words: tuple[str, ...]

    @property
    def polar_mass(self) -> float:
        """How much of the text VADER read as carrying sentiment at all."""
        return self.positive + self.negative

    @property
    def minority_share(self) -> float:
        """How much of the polar mass points against the majority. 0.0 when one-sided.

        The quantity :data:`CONTESTED_MINORITY_SHARE` is compared against, and the reason
        the conflict test is not a band around zero: it separates "the words cancelled"
        from "there were no words", which a compound of 0.0 cannot.
        """
        if self.polar_mass == 0:
            return 0.0
        return min(self.positive, self.negative) / self.polar_mass


def read(text: str, *, names: Sequence[str] = ()) -> Reading:
    """Score one text and collect everything needed to decide whether to believe it.

    Pure: no database, no network, no clock (`docs/08` §6). `names` are company names known
    to occur in this text - `packages.normalize.tagging.match_aliases` produces them - and
    are used only to notice when a company's own name is carrying the score. Supplying
    none is valid and simply switches that check off.
    """
    vader = analyzer()
    raw = vader.polarity_scores(text)
    tokens = _tokens(text)
    present = {word for _, word in tokens}

    name_tokens = {
        word
        for name in names
        for _, word in _tokens(name)
        if word in present and word in vader.lexicon
    }
    return Reading(
        text=text,
        compound=Decimal(str(raw["compound"])).quantize(SCORE_PLACES),
        positive=raw["pos"],
        negative=raw["neg"],
        scored_words=tuple(original for original, word in tokens if word in vader.lexicon),
        gap_words=tuple(
            dict.fromkeys(word for _, word in tokens if word in UNSCORED_FINANCE_TERMS)
        ),
        false_friends=tuple(
            dict.fromkeys(
                word for _, word in tokens if word in FALSE_FRIEND_TERMS and word in vader.lexicon
            )
        ),
        name_words=tuple(sorted(name_tokens)),
    )


def _tokens(text: str) -> tuple[tuple[str, str], ...]:
    """`(as written, folded)` for every token, on **VADER's own** token boundaries.

    Using VADER's tokeniser rather than one of our own is the whole basis of the gap list:
    "a word VADER did not score" is only a true statement about the words VADER saw.
    """
    from vaderSentiment.vaderSentiment import SentiText  # noqa: PLC0415 - `data` extra

    return tuple((word, _normalise(word)) for word in SentiText(text).words_and_emoticons)


def route(reading: Reading) -> tuple[str, str]:
    """`(tier, reason)` for one reading. The tiering decision, and nothing else.

    Order matters and is argued rather than incidental. Conflict is tested first because it
    is a statement about the score's *construction* - an average over disagreement is not a
    weak reading of the text, it is the wrong summary of it - and that holds however the
    vocabulary lands. The vocabulary traps are tested next, in decreasing confidence that
    VADER is wrong: a term it does not hold at all, then one it holds in the wrong sense,
    then a company's name. `no_sentiment_words` is last and is a *conclusion*: everything
    that could have made a zero suspicious has been ruled out.
    """
    if reading.polar_mass > 0 and reading.minority_share >= CONTESTED_MINORITY_SHARE:
        return AMBIGUOUS, CONFLICTING_WORDS
    if reading.gap_words:
        return AMBIGUOUS, LEXICON_GAP
    if reading.false_friends:
        return AMBIGUOUS, FALSE_FRIEND
    if reading.name_words:
        return AMBIGUOUS, NAME_IN_LEXICON
    if reading.polar_mass == 0:
        return BULK, NO_SENTIMENT_WORDS
    return BULK, CLEAR


def label_for(compound: Decimal) -> str:
    """The score in the three words the schema admits. Not a view; a restatement."""
    if compound >= LABEL_BAND:
        return POSITIVE
    if compound <= -LABEL_BAND:
        return NEGATIVE
    return NEUTRAL


@dataclass(frozen=True)
class Score:
    """One row's worth of sentiment, plus why it should or should not be believed.

    `tier` and `reason` have **nowhere to go in `news_sentiment`** - the table is
    `(news_id, model, model_version, score, label, scored_at)` and migration 0029 may not
    be touched here. They are carried on the report and in the logs, and the gap is called
    out in this module's report rather than papered over by smuggling a routing decision
    into `model_version`, which is provenance and not a flag field.
    """

    score: Decimal
    label: str
    tier: str
    reason: str
    reading: Reading

    @property
    def is_ambiguous(self) -> bool:
        return self.tier == AMBIGUOUS


def score_text(text: str, *, names: Sequence[str] = ()) -> Score:
    """Read a text, decide which tier owns it, and say what would be stored.

    Pure. The unit is one text - the caller decides that this is a headline rather than a
    headline and a body, and the module docstring argues why it should be the headline.
    """
    reading = read(text, names=names)
    tier, reason = route(reading)
    return Score(
        score=reading.compound,
        label=label_for(reading.compound),
        tier=tier,
        reason=reason,
        reading=reading,
    )


# --------------------------------------------------------------------------------------
# The ambiguous tier. Built, gated, and loud about being gated.
# --------------------------------------------------------------------------------------


class MissingApiKeyError(RuntimeError):
    """No `ANTHROPIC_API_KEY`. Refused at the moment of use, like the reconciler's."""


#: `SPEC.md` §2E's cost tiering puts a *"cheap model (Haiku-class)"* on ticker tagging and
#: sentiment and reserves the expensive one for the arbitrator and the memo. This is the
#: escalation tier of a cost-control design, so taking the expensive model here would
#: dismantle the thing being built.
DEFAULT_LLM_MODEL = "claude-haiku-4-5"

#: Bumped whenever :data:`SYSTEM_PROMPT` or the request shape changes, for the reason
#: `packages.extract.reconciler.PROMPT_VERSION` documents: it is part of the identity of a
#: stored answer, and an unchanged version against a changed prompt makes two incomparable
#: runs look like one. It reaches `news_sentiment.model_version` for this tier's rows.
PROMPT_VERSION = "p5.3-v1"

#: What the escalation tier is asked. Three constraints, each preventing something.
#:
#: *"the sentiment a Nigerian financial reader would take"* - the escalation exists because
#: the lexicon is US-trained, so a model asked for generic sentiment would reproduce the
#: failure it was called in to fix.
#:
#: *"Return `neutral` when the headline reports a fact with no directional content"* -
#: without it a model asked to classify will find a direction in an auction result, and the
#: tier would trade a lexicon's false confidence for a model's.
#:
#: *"Do not give investment advice... Do not say what anyone should do"* - `docs/03` P5.3
#: forbids a sentiment score driving anything, and the compliance linter checks the brief,
#: not this. The instruction is here because the prompt is the first place to say it.
SYSTEM_PROMPT = (
    "You classify the sentiment of a financial news headline about a Nigerian or US "
    "listed company or market. Judge the sentiment a Nigerian financial reader would "
    "take from it, not the sentiment of the English words in isolation. Return `neutral` "
    "when the headline reports a fact with no directional content, such as a scheduled "
    "meeting, an appointment, or an auction result. Score in [-1, 1]. Do not give "
    "investment advice, do not forecast, and do not say what anyone should do."
)

#: The response shape, enforced by the API rather than by parsing. `strict`/`json_schema`
#: means a malformed answer is the server's problem, not a `try: json.loads` here.
RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": -1, "maximum": 1},
        "label": {"type": "string", "enum": [POSITIVE, NEGATIVE, NEUTRAL]},
        "rationale": {"type": "string"},
    },
    "required": ["score", "label", "rationale"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LlmReading:
    """One escalated headline, as the model answered it."""

    score: Decimal
    label: str
    #: One sentence, for the hand check `docs/03` P5.3 asks for. Not stored - there is no
    #: column for it - but logged, which is where a reviewer can still find it.
    rationale: str


@runtime_checkable
class AmbiguousScorer(Protocol):
    """What the escalation tier has to look like, so a test can be one.

    A Protocol rather than a base class for the same reason
    `packages.normalize.tagging.EntityExtractor` is one: the batch path must be exercisable
    with a deterministic stub and no key, and inheritance would make the stub depend on the
    thing it stands in for.
    """

    model_name: str
    model_version: str

    def score(self, headline: str, body: str | None) -> LlmReading: ...


class ClaudeSentimentScorer:
    """`AmbiguousScorer`, against the Anthropic API. **Not runnable in this repository.**

    There is no `ANTHROPIC_API_KEY`, so `score()` raises :class:`MissingApiKeyError` before
    it reaches `messages.create`. Everything up to that line is built and tested: the
    prompt, the schema, the model choice, the reading of the response, and the routing that
    decides which headlines arrive here at all.

    That is deliberate and it is the same shape `packages.extract.reconciler` takes for
    P4.2. The alternative - stubbing a plausible score into `news_sentiment` so the table
    looks finished - would put a fabricated number behind a `model` column that names a
    real model, in a table with a `no_update` trigger that makes it permanent.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = DEFAULT_LLM_MODEL,
        max_output_tokens: int = 256,
        timeout_sec: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self.model_name = model_name
        #: This tier's `news_sentiment.model_version`. The prompt, not a library version:
        #: for a hosted model the prompt is the part of the scorer that we control and
        #: that changes, and two prompts against one model are two scorers.
        self.model_version = PROMPT_VERSION
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout_sec

    @property
    def api_key(self) -> str:
        """The key, or a refusal naming what still works without it.

        Absent is a legitimate state for the rest of P5.3 - the bulk tier needs no key and
        covers most of the corpus, which is the point of the tiering - so this refuses at
        the moment of use rather than at import.
        """
        from packages.common.config import get_settings  # noqa: PLC0415 - deferred

        key = self._api_key or getattr(get_settings(), "anthropic_api_key", None)
        if not key:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set, so the ambiguous sentiment tier cannot run. "
                "The bulk tier needs no key; every article still gets a `vader` row, and "
                "the ones this tier would have re-read are counted in "
                "`SentimentReport.escalated` and logged as "
                "`sentiment.ambiguous_tier_is_not_configured`."
            )
        return str(key)

    def user_prompt(self, headline: str, body: str | None) -> str:
        """The headline, and the body as context.

        The body is here and not in the bulk tier on purpose: `compound` is normalised over
        whatever it is given, so a summary of unpredictable length distorts it, while a
        model reading for meaning is helped by the same text. Labelled, so the model is not
        left to guess which half it is being asked about.
        """
        if not body:
            return f"HEADLINE: {headline}"
        return f"HEADLINE: {headline}\n\nCONTEXT (the feed's own summary):\n{body}"

    def score(self, headline: str, body: str | None) -> LlmReading:
        """One escalated headline in, one classification out."""
        import anthropic  # noqa: PLC0415 - `data` extra; see `analyzer`

        client = anthropic.Anthropic(api_key=self.api_key, timeout=self._timeout)
        response = client.messages.create(
            model=self.model_name,
            max_tokens=self._max_output_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self.user_prompt(headline, body)}],
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_llm_reading(text)


def parse_llm_reading(payload: str | Mapping[str, object]) -> LlmReading:
    """Read the escalation tier's answer, or refuse it.

    Separate from the call so the contract is testable without a key, the way
    `packages.extract.contract.parse_extraction` is. `output_config` makes a malformed
    response unlikely rather than impossible, and a score outside [-1, 1] would be rejected
    by `news_sentiment_score_in_range` at the far end of a transaction instead of here.
    """
    data = payload if isinstance(payload, Mapping) else json.loads(payload)
    if not isinstance(data, Mapping):
        raise ValueError(f"response is a {type(data).__name__}, not a JSON object")
    raw = data.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        raise ValueError(f"response.score must be a number, got {raw!r}")
    try:
        # Through `str` so a JSON float arrives as the figure it was written as rather
        # than as its binary approximation.
        score = Decimal(str(raw)).quantize(SCORE_PLACES)
    except InvalidOperation as exc:
        # `"up"` is a string and passes the type check above; it is not a number.
        # `InvalidOperation` is an `ArithmeticError`, so it would escape a caller
        # guarding this the way it guards every other malformed-response case.
        raise ValueError(f"response.score={raw!r} is not a number") from exc
    if not -1 <= score <= 1:
        raise ValueError(f"response.score={score} is outside [-1, 1]")
    label = data.get("label")
    if label not in (POSITIVE, NEGATIVE, NEUTRAL):
        raise ValueError(f"response.label={label!r} is not one of {(POSITIVE, NEGATIVE, NEUTRAL)}")
    rationale = data.get("rationale")
    return LlmReading(
        score=score, label=label, rationale=str(rationale) if rationale is not None else ""
    )


# --------------------------------------------------------------------------------------
# Reading and writing
# --------------------------------------------------------------------------------------


def unscored_articles(
    session: Session, *, model: str, version: str, limit: int | None = None
) -> list[NewsItem]:
    """Articles with no row from this exact scorer, oldest first.

    Keyed on `(model, model_version)` and not on `news_id`, because that is the primary
    key: an article scored by `vader` 3.3.2 is *unscored* by `vader` 4.0 and by
    `claude-haiku-4-5`, and a re-score under a new version is supposed to find it and write
    beside the old row.

    Ordered by `known_as_of` - the article's own date, never `retrieved_at` or `scored_at`
    (`docs/08` §1.3). It only decides which rows a capped batch takes, but the habit is the
    point: the day one of these orderings reaches a feature join, the wrong one is a
    look-ahead nobody will see.
    """
    already = select(NewsSentiment.news_id).where(
        NewsSentiment.news_id == NewsItem.id,
        NewsSentiment.model == model,
        NewsSentiment.model_version == version,
    )
    statement = (
        select(NewsItem).where(~already.exists()).order_by(NewsItem.known_as_of, NewsItem.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def store_score(
    session: Session,
    *,
    news_id: int,
    score: Decimal,
    label: str,
    tier: str,
    reason: str,
    model: str = MODEL,
    version: str | None = None,
    scored_at: dt.datetime | None = None,
) -> bool:
    """Write one sentiment row. Returns whether it was new.

    `ON CONFLICT DO NOTHING` on the whole primary key, never an update. `news_sentiment`
    carries migration 0029's `no_update` trigger, which raises rather than overwriting, and
    `CLAUDE.md` forbids the silent overwrite it would be anyway. So a re-run of the same
    scorer at the same version is a no-op - deliberately, because the second run's
    `scored_at` is not new information - and a run of a *different* version writes a second
    row beside the first, which is the entire reason `model_version` is in the key.

    `tier` and `reason` are stored beside the score because on this corpus the score alone
    is not evidence: 20 of the 44 articles held score exactly 0.0000, and hand-checking
    says most of those are unreadable rather than neutral. A consumer can ask for the
    scores the lexicon was competent to give rather than for all of them. Migration 0030.

    `scored_at` is provenance and nothing else. It records when this process ran. The
    point-in-time date of what this row says is the article's `NewsItem.known_as_of`, and a
    downstream join on `scored_at` reads the scheduler's cron entry as if it were the
    market (`docs/08` §1.3).
    """
    statement = (
        pg_insert(NewsSentiment)
        .values(
            news_id=news_id,
            model=model,
            model_version=version if version is not None else model_version(),
            score=score,
            label=label,
            tier=tier,
            reason=reason,
            scored_at=scored_at if scored_at is not None else utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["news_id", "model", "model_version"])
        .returning(NewsSentiment.news_id)
    )
    return session.execute(statement).fetchone() is not None


@dataclass(frozen=True)
class SentimentReport:
    """What a run did, and what it could not answer.

    Counts, never an aggregate score. A mean compound over a feed is exactly the object
    `docs/03` P5.3 forbids - a weak signal with the caveat rounded off - and it would be
    the first thing a brief reached for if this returned one.
    """

    articles: int
    rows_written: int
    #: How many landed in each :data:`REASONS` bucket.
    by_reason: Mapping[str, int]
    #: Sent to the ambiguous tier, or which would have been had one been configured.
    escalated: int
    #: Escalated and actually re-read by a model. Zero without `ANTHROPIC_API_KEY`, and the
    #: distance between this and `escalated` is the size of what is not built.
    escalated_scored: int
    model: str
    model_version: str

    @property
    def escalation_rate(self) -> float:
        """The number the tiering exists to keep small. Not a quality measure."""
        return self.escalated / self.articles if self.articles else 0.0


def score_articles(
    session: Session,
    items: Sequence[NewsItem],
    *,
    scorer: AmbiguousScorer | None = None,
    names_for: Mapping[int, Sequence[str]] | None = None,
    store: bool = True,
) -> SentimentReport:
    """Score a batch, escalate what the lexicon should not be trusted on, and report both.

    Every article gets a `vader` row, including the escalated ones. Two reasons, and the
    second is the deciding one. A `vader` row is an honest record of what VADER said, which
    is true whether or not we believe it - the belief is the tier, not the score. And
    withholding it would make *"the lexicon was unsure"* indistinguishable from *"this
    article was never scored"*, which is the silent absence this repository keeps finding
    in its own data (`docs/03` P5.1's "200 OK, zero new items").

    When `scorer` is None - which is the state of this repository, because there is no
    `ANTHROPIC_API_KEY` - the escalated articles are counted and logged at warning level
    and no second row is written. Nothing is invented to fill the gap.
    """
    version = model_version()
    counts = dict.fromkeys(REASONS, 0)
    written = 0
    escalated = 0
    escalated_scored = 0

    for item in items:
        names = (names_for or {}).get(item.id, ())
        scored = score_text(item.headline, names=names)
        counts[scored.reason] += 1
        if store:
            written += store_score(
                session,
                news_id=item.id,
                score=scored.score,
                label=scored.label,
                tier=scored.tier,
                reason=scored.reason,
                model=MODEL,
                version=version,
            )
        if not scored.is_ambiguous:
            continue
        escalated += 1
        if scorer is None:
            _log.warning(
                "sentiment.ambiguous_tier_is_not_configured",
                news_id=item.id,
                reason=scored.reason,
                headline=item.headline,
                vader_score=str(scored.score),
                evidence=_evidence(scored.reading),
                detail=(
                    "the lexicon's score is stored and flagged, and no model re-read it; "
                    "set ANTHROPIC_API_KEY and pass a scorer"
                ),
            )
            continue
        reading = scorer.score(item.headline, item.body)
        escalated_scored += 1
        _log.info(
            "sentiment.escalated",
            news_id=item.id,
            reason=scored.reason,
            model=scorer.model_name,
            rationale=reading.rationale,
        )
        if store:
            written += store_score(
                session,
                news_id=item.id,
                score=reading.score,
                label=reading.label,
                # The escalation's own reason, not a third tier value. This row exists
                # *because* the lexicon hit `scored.reason` on this headline, and that is
                # what the pair records; `model` already says who resolved it. A row
                # cannot claim `bulk` here, which migration 0030's CHECK enforces.
                tier=AMBIGUOUS,
                reason=scored.reason,
                model=scorer.model_name,
                version=scorer.model_version,
            )

    report = SentimentReport(
        articles=len(items),
        rows_written=written,
        by_reason=counts,
        escalated=escalated,
        escalated_scored=escalated_scored,
        model=MODEL,
        model_version=version,
    )
    _log.info(
        "sentiment.run",
        articles=report.articles,
        rows_written=report.rows_written,
        escalated=report.escalated,
        escalated_scored=report.escalated_scored,
        model=report.model,
        model_version=report.model_version,
        **{f"reason_{name}": count for name, count in counts.items()},
    )
    return report


#: How many articles one scheduled pass will score. A ceiling rather than a target: the
#: three feeds together publish tens of items an hour, so this is only ever reached on a
#: first run or after an outage, and it keeps that run from holding one session open over
#: a whole backlog.
BATCH_LIMIT = 500


def score_new_articles(limit: int = BATCH_LIMIT) -> SentimentReport:
    """The scheduler's entry point: everything this scorer has not scored yet.

    Runs the bulk tier only. The escalation tier is not wired in here and will not be
    until there is an `ANTHROPIC_API_KEY`: a scheduled job is the worst place to discover
    a missing credential, and `score_articles` already counts and logs every article that
    would have been escalated, so the gap is visible in the run's own log line rather
    than as a silence.

    Idempotent by construction. `unscored_articles` is keyed on `(model, model_version)`
    and `store_score` is `ON CONFLICT DO NOTHING`, so a second pass in the same hour
    writes nothing and a pass after a `vaderSentiment` upgrade re-scores the whole corpus
    under the new version, beside the old rows rather than over them.
    """
    from packages.common.db import get_session  # noqa: PLC0415 - deferred, as in P5.4

    with get_session() as session:
        items = unscored_articles(session, model=MODEL, version=model_version(), limit=limit)
        return score_articles(session, items)


def _evidence(reading: Reading) -> str:
    """The words behind a score, for a log line somebody has to act on.

    A warning that says only *"this headline is ambiguous"* cannot be triaged. One that
    says `scored=profit; gap=falls` can be read once and understood.
    """
    parts = [
        f"{name}={','.join(words)}"
        for name, words in (
            ("scored", reading.scored_words),
            ("gap", reading.gap_words),
            ("false_friend", reading.false_friends),
            ("name", reading.name_words),
        )
        if words
    ]
    return "; ".join(parts) or "none"


def describe(scores: Iterable[Score]) -> str:
    """A run as a block of text, for a human reading a sample by hand.

    `docs/03` P5.3's instruction is *"verify a sample by hand"* and check 11 of the P5 test
    checkpoint is *"check ten sentiment scores against the headlines"*. Neither is possible
    from a column of numbers, so the evidence is printed beside each one.
    """
    lines = []
    for scored in scores:
        lines.append(
            f"{scored.score:>8} {scored.label:<8} {scored.tier:<9} {scored.reason:<18} "
            f"{_evidence(scored.reading):<34} {scored.reading.text}"
        )
    return "\n".join(lines)
