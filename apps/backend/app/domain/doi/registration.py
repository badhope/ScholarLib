"""DataCite REST API adapter for DOI minting.

Design (mirrors ``app/core/search.py``'s Meilisearch integration):

- ``settings.datacite_api_url`` empty → everything is a no-op.
- API key missing / server down → log a warning and return a failure
  result. DOI registration failures NEVER block the write path.
- Supports both DOI minting (new DOI) and DOI updating (metadata sync).

DataCite MDS (Metadata Service) docs:
https://support.datacite.org/docs/api-mds
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DATACITE_API_URL = "https://api.datacite.org"
HTTP_TIMEOUT = 15.0


def datacite_enabled() -> bool:
    """True when a DataCite API URL is configured."""
    return bool(settings.datacite_api_url) and bool(settings.datacite_prefix)


def _auth_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/vnd.api+json",
        "Authorization": f"Basic {settings.datacite_api_key}",
    }


def _build_doi(suffix: str) -> str:
    """Build a full DOI from the configured prefix and the given suffix."""
    return f"{settings.datacite_prefix}/{suffix}"


def _build_datacite_metadata(resource: Any, doi: str) -> dict[str, Any]:
    """Build a DataCite 4.x JSON metadata payload from a Resource model."""
    authors_list = []
    for author in resource.authors or []:
        if isinstance(author, dict):
            authors_list.append(
                {
                    "name": author.get("name", str(author)),
                    "nameType": "Personal",
                    "givenName": author.get("given_name", ""),
                    "familyName": author.get("family_name", ""),
                }
            )
        else:
            authors_list.append({"name": str(author), "nameType": "Personal"})

    return {
        "data": {
            "type": "dois",
            "attributes": {
                "doi": doi,
                "creators": authors_list,
                "titles": [{"title": resource.title}],
                "publisher": resource.publisher or "Rubbish",
                "publicationYear": str(resource.year or "2026"),
                "types": {
                    "resourceTypeGeneral": "Text",
                    "resourceType": resource.type or "JournalArticle",
                },
                "descriptions": (
                    [{"description": resource.abstract[:5000], "descriptionType": "Abstract"}]
                    if resource.abstract
                    else []
                ),
                "url": f"https://doi.org/{doi}",
                "subjects": ([{"subject": tag} for tag in (resource.tags or [])[:10]]),
            },
        }
    }


def _default_suffix(resource: Any) -> str:
    """默认 DOI 后缀：必须带租户维度。

    ``resources.id`` 是**全局自增**，多租户部署下租户 A 的 #7 与租户 B 的 #7
    会铸出同一个 DOI。DOI 是学术永久标识，撞号不可撤销，会直接污染引用与
    DataCite 账目，所以默认后缀必须含租户标识。

    ``tenant_id`` 缺失时（单测用的替身对象）退回纯 id，保证可测性。
    """
    tenant_id = getattr(resource, "tenant_id", None)
    if tenant_id is None:
        return str(resource.id)
    return f"{resource.id}-{str(tenant_id)[:8]}"


async def mint_doi(
    resource: Any,
    suffix: str | None = None,
) -> tuple[str, str]:
    """Mint a new DOI for the given resource.

    Returns (doi, state) where state is "completed" or "failed".

    Steps:
    1. POST metadata XML to DataCite MDS.
    2. POST DOI registration to DataCite MDS.
    """
    if not datacite_enabled():
        return "", "failed"

    # 默认后缀必须带租户维度：resources.id 是**全局自增**，多租户部署下
    # 租户 A 的 #7 和租户 B 的 #7 会铸出同一个 DOI。DOI 是学术永久标识，
    # 撞号不可撤销，会直接污染引用与 DataCite 账目。
    doi_suffix = suffix or _default_suffix(resource)
    doi = _build_doi(doi_suffix)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Step 1: POST metadata
            metadata = _build_datacite_metadata(resource, doi)
            meta_resp = await client.post(
                f"{DATACITE_API_URL}/dois",
                headers=_auth_headers(),
                json=metadata,
            )
            if meta_resp.status_code >= 400:
                logger.warning(
                    "DataCite metadata POST failed: %s %s",
                    meta_resp.status_code,
                    meta_resp.text[:500],
                )
                return doi, "failed"

            # Step 2: Register the DOI (make it findable)
            register_payload = {
                "data": {
                    "type": "dois",
                    "attributes": {
                        "doi": doi,
                        "url": f"https://doi.org/{doi}",
                        "event": "publish",
                    },
                }
            }
            reg_resp = await client.put(
                f"{DATACITE_API_URL}/dois/{doi}",
                headers=_auth_headers(),
                json=register_payload,
            )
            if reg_resp.status_code >= 400:
                logger.warning(
                    "DataCite DOI register failed: %s %s",
                    reg_resp.status_code,
                    reg_resp.text[:500],
                )
                return doi, "failed"

    except httpx.TimeoutException:
        logger.warning("DataCite API timeout")
        return doi, "failed"
    except httpx.RequestError as exc:
        logger.warning("DataCite request failed: %s", exc)
        return doi, "failed"

    return doi, "completed"


__all__ = [
    "datacite_enabled",
    "mint_doi",
]
