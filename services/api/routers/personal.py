"""The personal router - requires ``entitlements.personal_tier``.

Pre-licence this tier is lawful because no fee is charged and no funds are pooled
(``PROJECT_CONTEXT.md`` 4, ``SPEC.md`` 1.2), and it is reachable only by principals
whose ``kind`` is ``owner`` or ``family`` - the entitlement flag alone is not
sufficient (``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6, invariant I11).

``require_personal`` is a router-level dependency, not a per-endpoint one: a route
added to this file inherits the gate whether or not its author remembers it.
"""

import datetime as dt
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from packages.common.db import get_session
from packages.common.identity import TICKER, AmbiguousIdentifierError, resolve_security
from packages.common.timez import utcnow, utctoday
from packages.common.units import UnreadableFigureError
from packages.ingestion.documents import NotAPdfError, store_uploaded_report
from packages.normalize.manual import (
    EntryRefusedError,
    ManualStatement,
    TypedFigure,
    enter_statement,
)
from packages.normalize.review import correction_rate, review_queue
from services.api.deps import RequestContext, require_personal
from services.api.errors import FieldedHTTPException
from services.api.middleware.assert_response import GuardedAPIRoute
from services.api.routers import API_V1
from services.api.schemas import (
    CorrectionRateReport,
    DocumentStored,
    ManualEntryAccepted,
    ManualStatementIn,
    PersonalPing,
    ReviewQueue,
    ReviewQueueItem,
)

_log = structlog.get_logger(__name__)

#: How big an uploaded report may be. Nigerian annual reports run to a few megabytes; this
#: is generous for one and small enough that a mistaken upload fails fast rather than filling
#: the store.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

router = APIRouter(
    prefix=f"{API_V1}/personal",
    tags=["personal"],
    route_class=GuardedAPIRoute,
    dependencies=[Depends(require_personal)],
)


@router.get("/ping", response_model=PersonalPing)
async def ping(ctx: RequestContext = Depends(require_personal)) -> PersonalPing:
    """403 for anyone the server did not derive personal mode for.

    Anonymous, an expired or revoked token, a disabled principal, an unentitled
    principal, a service principal, and a ``kind='public'`` principal holding
    ``personal_tier`` pre-licence all land on the same 403 with the same body. The
    caller cannot tell which of those they are, which is the intent.
    """
    return PersonalPing(mode=ctx.mode)


@router.post(
    "/documents",
    response_model=DocumentStored,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require_personal),
) -> DocumentStored:
    """Store an uploaded report immutably and return its place in the store. P3.1.

    201 whether the bytes were new or already held: the request succeeded either way, and
    `created` says which happened. Re-uploading the same file is a no-op that returns the row
    already there, which is P3 check 1.

    422 for anything that is not a readable PDF. A `page` citation into an HTML error page a
    download captured instead of the report would mean nothing, so the bytes are checked
    rather than the filename.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise FieldedHTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, fields=["file"])
    with get_session() as session:
        try:
            stored = store_uploaded_report(session, data, url=file.filename)
        except NotAPdfError as exc:
            _log.warning("upload_refused", filename=file.filename, reason=str(exc))
            raise FieldedHTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, fields=["file"]
            ) from exc
    return DocumentStored(
        document_id=stored.document_id,
        sha256=stored.sha256,
        page_count=stored.page_count,
        created=stored.created,
    )


@router.post(
    "/statements",
    response_model=ManualEntryAccepted,
    status_code=status.HTTP_201_CREATED,
)
async def enter_typed_statement(
    body: ManualStatementIn,
    ctx: RequestContext = Depends(require_personal),
) -> ManualEntryAccepted:
    """Write one hand-typed statement with full provenance, or refuse and write nothing. P3.2.

    **`reviewed_by` comes from the authenticated principal, never from the body.** A caller
    who could name the reviewer could attribute their typing to somebody else, and the only
    value that column has is telling a later reader who to ask.

    422 carries the refusal verbatim. Every message names the figure and what is wrong with
    it, because "invalid entry" sends an operator back through forty fields looking for it;
    and because nothing was written, the fix is to correct the field and send it again.
    """
    with get_session() as session:
        security_id = _resolve_ticker(session, body)

    entry = ManualStatement(
        security_id=security_id,
        statement_type=body.statement_type,
        period_type=body.period_type,
        period_end=body.period_end,
        known_as_of=body.known_as_of,
        currency=body.currency,
        scale=body.scale,
        source_document_id=body.source_document_id,
        reviewed_by=ctx.principal_label,
        figures=tuple(
            TypedFigure(canonical_key=f.canonical_key, printed=f.printed, page=f.page)
            for f in body.figures
        ),
        period_start=body.period_start,
        is_audited=body.is_audited,
        is_consolidated=body.is_consolidated,
        chart_version=body.chart_version,
    )
    with get_session() as session:
        try:
            result = enter_statement(session, entry)
        except (EntryRefusedError, UnreadableFigureError) as exc:
            # Raised inside the `get_session` block, so the transaction rolls back and the
            # refusal is total. That is the promise the entry module makes, held here too.
            #
            # The reason goes to the log, where the operator finds it by `request_id`; the
            # body carries the field *names* only. `docs/10` §4.7 keeps free text out of an
            # error body, and the reason can quote a figure the caller typed.
            _log.warning(
                "manual_entry_refused",
                ticker=body.ticker,
                period_end=str(body.period_end),
                reason=str(exc),
                reviewed_by=entry.reviewed_by,
            )
            raise FieldedHTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                fields=_fields_named_in(str(exc), body),
            ) from exc
        accepted = ManualEntryAccepted(
            statement_id=result.statement_id,
            line_items_written=result.line_items_written,
            figures_absent=result.figures_absent,
            keys=list(result.keys),
            reviewed_by=entry.reviewed_by,
        )
    return accepted


def _fields_named_in(reason: str, body: ManualStatementIn) -> list[str]:
    """Which request fields a refusal was about, by name.

    The refusal messages name a canonical key, and the form needs to know which row to put
    the error beside. This maps a key back to its index in `figures`, so the response says
    `figures.3.printed` and never what was typed into it.

    Falls back to the whole `figures` list when the reason names no key - better to point at
    the block than to point at nothing.
    """
    named = [
        f"figures.{index}.printed"
        for index, figure in enumerate(body.figures)
        if figure.canonical_key and figure.canonical_key in reason
    ]
    if named:
        return named
    for candidate in ("known_as_of", "period_end", "period_start", "scale", "reviewed_by"):
        if candidate in reason:
            return [candidate]
    if "source document" in reason:
        return ["source_document_id"]
    if "security" in reason:
        return ["security_id"]
    if "already entered" in reason:
        return ["period_end", "period_type"]
    return ["figures"]


def _resolve_ticker(session: Session, body: ManualStatementIn) -> int:
    """The security the ticker names, or a 422 blaming the ticker.

    Resolved as of today, not as of the period being typed, and for the same reason
    `packages/valuation/snapshot.py`'s `find_security` does: every ticker row currently
    carries `valid_from` = the day EDGAR was first read, which is a lower bound and not a
    claim. Resolving `GTCO` as of 2019 against that would find nothing and refuse an entry
    the operator is right to be making. When `TEAM_BRIEF` §2.2-F gives the intervals real
    dates, this passes `body.period_end` instead - which is the stricter and correct
    question, since a ticker can be reassigned between the period and today.
    """
    try:
        resolved = resolve_security(
            session,
            value=body.ticker.strip().upper(),
            as_of=utctoday(),
            id_type=TICKER,
            exchange=body.exchange,
        )
    except AmbiguousIdentifierError as exc:
        _log.warning("manual_entry_ambiguous_ticker", ticker=body.ticker, reason=str(exc))
        raise FieldedHTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, fields=["ticker", "exchange"]
        ) from exc
    if resolved is None:
        _log.warning("manual_entry_unknown_ticker", ticker=body.ticker)
        raise FieldedHTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, fields=["ticker"]
        ) from None
    return resolved.security_id


@router.get("/review/queue", response_model=ReviewQueue)
async def review_queue_endpoint(
    limit: int = 50,
    since: dt.date | None = None,
    company_id: int | None = None,
) -> ReviewQueue:
    """What needs a human, worst first. P4.4.

    `docs/03` P4.4 asks for the queue to be *"prioritised by materiality"* because *"a FIFO
    queue wastes your scarcest resource - reviewer attention - on trivia"*. The ordering
    and its components both come back, so a reviewer who disagrees with the order can see
    what produced it instead of having to trust it.

    Personal-tier, and not merely because it is a write-adjacent surface: this names
    companies beside figures the system believes are wrong. That is an internal judgement,
    not a fact about the company, and serving it anonymously would be publishing an
    accusation.

    `shown` is deliberately separate from `limit`. A queue that returned fifty items and
    said nothing else looks identical whether fifty or five thousand are waiting, and the
    depth of the queue is the number `docs/03` P4 watches for reviewer-capacity trouble.
    """
    # No `ctx` parameter: `require_personal` is a router-level dependency (see the
    # APIRouter above), so the gate is already closed before this runs. Taking one here
    # would imply the endpoint was doing the authorising, and neither of these needs the
    # principal - unlike the write surfaces, where the reviewer's name is the point.
    with get_session() as session:
        items = review_queue(session, limit=limit, since=since, company_id=company_id)
    return ReviewQueue(
        generated_at=utcnow(),
        shown=len(items),
        limit=limit,
        items=[
            ReviewQueueItem(
                company_id=item.company_id,
                company_name=item.company_name,
                period_type=item.period_type,
                period_end=item.period_end,
                finding=item.finding,
                detail=item.why,
                canonical_key=item.canonical_key,
                priority=item.priority,
                severity=item.severity,
                share_of_anchor=item.share_of_anchor,
                is_required=item.is_required,
                occurrences=item.occurrences,
                first_period=item.first_period,
            )
            for item in items
        ],
    )


@router.get("/review/correction-rate", response_model=CorrectionRateReport)
async def correction_rate_endpoint(
    start: dt.date,
    end: dt.date,
) -> CorrectionRateReport:
    """P4.4's headline metric over a window. P4 exit criterion.

    `TEAM_BRIEF.md` Part 3: *"if it isn't falling, the extractor isn't learning and
    something is wrong with the feedback loop."* That single number is the early-warning
    signal for the whole phase, which is why it is served rather than computed by hand.

    Restatements are returned beside the rate and excluded from it. A company revising its
    own figures is the world changing its mind, not this system being wrong, and counting
    them would move the rate every time a filer amended something - in whichever direction,
    meaninglessly.
    """
    if end < start:
        raise FieldedHTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, fields=["start", "end"])
    with get_session() as session:
        rate = correction_rate(session, start=start, end=end)
    return CorrectionRateReport(
        period_start=rate.period_start,
        period_end=rate.period_end,
        items_written=rate.items_written,
        our_corrections=rate.our_corrections,
        restatements=rate.restatements,
        # Not zero when nothing was written. A dashboard showing 0.0% for a week nothing
        # ran would read as the best week on record.
        correction_rate=(
            Decimal(rate.our_corrections) / Decimal(rate.items_written)
            if rate.items_written
            else None
        ),
    )
