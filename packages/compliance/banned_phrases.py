"""Mechanism 4 of five - the banned-phrase linter for public free text.

    OWNER:          the project owner (git identity ``nnatuanyafrankoguguo``).
    REVIEW CADENCE: quarterly, alongside the regulatory sweep. TG16.
    LAST REVIEWED:  2026-09-01 (created; list intentionally empty - see below).
    REGISTER:       ``docs/REVIEW_CADENCE.md`` (P0.13) owns the reminder.

**Why the list is empty and that is not an oversight.**
``docs/10_PRE_BUILD_CORRECTIONS.md`` 6.1 defers the *list* to P4, because the
document set's one seed term (``"should"``) is unusable and a list written before
there is any public prose to lint is a list written blind. The *call site* is not
deferred: it is wired into the public response path today, so P4 fills a list
rather than retrofitting a mechanism into eleven handlers.

**What this is and is not.** ``docs/01_ARCHITECTURE.md`` 3: *"It is a net, not a
wall - which is why it is fifth of five and not first of one."* It catches
mechanism 3's blind spot: advice arriving as prose inside a structurally legal
type. It cannot catch advice phrased in a way the list did not anticipate.

**The better answer, for P4 to adopt.** ``docs/10`` 4.7: invert the default. A
public memo's ``bull_case``/``bear_case``/``risks`` should be *claim + citation
objects, never free paragraphs*, so there is no free text to lint. This denylist
stays as the secondary net over whatever free text survives that rule.

**The false-positive battery is part of the mechanism, not a nicety.** "share
buyback", "buy-side" and "buying power" are ordinary financial English. A linter
that blocks them will be switched off within a week, and a switched-off linter is
worse than none because it is still in the architecture diagram.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from functools import lru_cache
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from packages.compliance.mode import Mode, coerce_mode, log_compliance_error

__all__ = [
    "FALSE_POSITIVE_ALLOWANCES",
    "SEED_PHRASES",
    "BannedPhraseFound",
    "assert_clean",
    "iter_public_text",
    "load_phrases",
    "scan",
    "scan_payload",
]

#: Deliberately empty in P0. P4 fills it (``docs/10`` 6.1). Every addition needs a
#: matching entry in :data:`FALSE_POSITIVE_ALLOWANCES` if it has a benign homograph
#: in financial English, and a test in ``tests/compliance/test_banned_phrases.py``.
SEED_PHRASES: frozenset[str] = frozenset()

#: Spans matching any of these are never reported, even when a banned phrase sits
#: inside them. Whole-phrase, case-insensitive.
FALSE_POSITIVE_ALLOWANCES: frozenset[str] = frozenset(
    {
        "buy-side",
        "buy side",
        "buyback",
        "buying power",
        "sell-side",
        "sell side",
        "share buyback",
    }
)

_MAX_TEXT_WALK_DEPTH = 12


class BannedPhraseFound(HTTPException):
    """Advice phrasing was about to be emitted in public mode.

    500, for the same reason as :class:`~packages.compliance.response_types.
    ResponseTypeViolation`: the caller did nothing wrong, we did.
    """

    def __init__(self, phrases: list[str]) -> None:
        super().__init__(status_code=500, detail="advice phrasing illegal for public mode")
        self.phrases = phrases


def load_phrases() -> frozenset[str]:
    """The active denylist.

    P4 may move this to ``packages/compliance/banned_phrases.yml`` per ``docs/10``
    4.7. Keep the loader as the single accessor so that move touches one function
    and nothing else, and so a list that fails to load fails *loudly* rather than
    silently scanning against nothing.
    """
    return SEED_PHRASES


@lru_cache(maxsize=8)
def _compile(phrases: frozenset[str]) -> re.Pattern[str] | None:
    """Whole-word, case-insensitive alternation. ``None`` when the list is empty."""
    cleaned = sorted({p.strip().lower() for p in phrases if p and p.strip()})
    if not cleaned:
        return None
    # Internal whitespace matches any run of whitespace, so a phrase still matches
    # across a line break in a generated paragraph.
    alternatives = [r"\s+".join(re.escape(word) for word in phrase.split()) for phrase in cleaned]
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


def _allowance_spans(text: str) -> list[tuple[int, int]]:
    pattern = _compile(FALSE_POSITIVE_ALLOWANCES)
    if pattern is None:  # pragma: no cover - the allowance list is never empty
        return []
    return [match.span() for match in pattern.finditer(text)]


def scan(text: str, *, phrases: Iterable[str] | None = None) -> list[str]:
    """Return every banned phrase found in ``text``, minus the false positives."""
    if not text or not isinstance(text, str):
        return []
    active = frozenset(phrases) if phrases is not None else load_phrases()
    pattern = _compile(active)
    if pattern is None:
        return []
    allowed = _allowance_spans(text)
    hits: list[str] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        if any(a_start <= start and end <= a_end for a_start, a_end in allowed):
            continue
        hits.append(match.group(0).lower())
    return sorted(set(hits))


def iter_public_text(payload: Any, _depth: int = 0) -> Iterator[str]:
    """Every string reachable inside a response payload."""
    if _depth > _MAX_TEXT_WALK_DEPTH:  # pragma: no cover - pathological payload
        return
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, BaseModel):
        for name in type(payload).model_fields:
            yield from iter_public_text(getattr(payload, name, None), _depth + 1)
    elif isinstance(payload, Mapping):
        for value in payload.values():
            yield from iter_public_text(value, _depth + 1)
    elif isinstance(payload, list | tuple | set | frozenset):
        for value in payload:
            yield from iter_public_text(value, _depth + 1)


def scan_payload(payload: Any, *, phrases: Iterable[str] | None = None) -> list[str]:
    """Scan every string in a response payload."""
    hits: set[str] = set()
    for text in iter_public_text(payload):
        hits.update(scan(text, phrases=phrases))
    return sorted(hits)


def assert_clean(mode: Any, payload: Any, *, phrases: Iterable[str] | None = None) -> None:
    """Mechanism 4. Raise if public-mode output carries advice phrasing.

    A no-op while :data:`SEED_PHRASES` is empty - but a *live* no-op: it is called
    on every public response today, so P4's only job is to populate a list.
    """
    if coerce_mode(mode) is not Mode.PUBLIC:
        return
    hits = scan_payload(payload, phrases=phrases)
    if not hits:
        return
    # Log the matched phrases (ours, from our own list) - never the surrounding
    # text, which is the part that could carry a figure or a principal's name.
    log_compliance_error("banned_phrase_in_public_response", phrases=hits)
    raise BannedPhraseFound(hits)
