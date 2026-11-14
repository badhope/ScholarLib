"""Ingest API routes — ``POST /api/ingest/parse`` and ``POST /api/ingest/fetch``.

Both endpoints require authentication (any logged-in user can ingest;
the resulting ``IngestResource`` is returned to the caller, never
written to the catalog directly). The frontend submits the returned
object through ``/api/submissions`` to keep the catalog write path
single.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.domain.ingest.fetchers import (
    ResourceNotFoundError,
    UpstreamError,
    fetch_arxiv,
    fetch_crossref,
    fetch_openalex,
    fetch_pubmed,
    fetch_semantic_scholar,
)
from app.domain.ingest.parsers import parse_bibtex, parse_csv, parse_json, parse_ris
from app.interfaces.http.ingest.schemas import (
    FetchRequest,
    IngestResource,
    ParseRequest,
    ParseResponse,
)
from app.models import User

router = APIRouter(prefix="/ingest", tags=["ingest"])

_PARSERS = {
    "bibtex": parse_bibtex,
    "ris": parse_ris,
    "csv": parse_csv,
    "json": parse_json,
}


@router.post("/parse", response_model=ParseResponse)
async def parse_endpoint(
    payload: ParseRequest,
    _: User = Depends(get_current_user),
) -> ParseResponse:
    """Parse a BibTeX/RIS/CSV/JSON string into a list of normalised resources.

    Per-entry parse failures are returned in ``errors`` (with a 1-based
    line/index); the whole request still returns 200 so the caller can
    act on the successfully-parsed entries.
    """
    parser = _PARSERS[payload.format]
    # bibtexparser is synchronous; a 2MB malformed input would block the
    # event loop. Offload to a threadpool so the loop keeps serving other
    # requests while the parse runs.
    resources, errors = await run_in_threadpool(parser, payload.content)
    return ParseResponse(
        data=resources,
        count=len(resources),
        errors=errors,
    )


@router.post("/fetch", response_model=IngestResource)
async def fetch_endpoint(
    payload: FetchRequest,
    _: User = Depends(get_current_user),
) -> IngestResource:
    """Fetch metadata from the upstream API for the given source and id."""
    try:
        if payload.source == "crossref":
            return await fetch_crossref(payload.id)
        if payload.source == "arxiv":
            return await fetch_arxiv(payload.id)
        if payload.source == "pubmed":
            return await fetch_pubmed(payload.id)
        if payload.source == "openalex":
            return await fetch_openalex(payload.id)
        return await fetch_semantic_scholar(payload.id)
    except ResourceNotFoundError:
        # Do not echo user input back in the error detail — a reflected
        # value would land in log aggregators and could be leveraged for
        # log injection.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found in upstream",
        ) from None
    except UpstreamError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream service error",
        ) from None
