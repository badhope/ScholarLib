"""DOI module — mint and manage DOIs via DataCite API.

Stateless HTTP adapter: on request, POSTs metadata to DataCite's
MDS (Metadata Service) and DOI registration endpoints, then records
the registration event in the local ``doi_registrations`` table.

Only the *registration* side lives here. Ingest/fetch of existing
metadata by DOI lives in the ``ingest`` module (``fetch_crossref``).
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.domain.doi import models  # noqa: F401
from app.interfaces.http.doi.routes import router

registry.register(
    ModuleManifest(
        name="doi",
        version="0.1.0",
        description="DOI minting and registration via DataCite API.",
        dependencies=frozenset(),
        router=router,
    )
)

__all__ = ["router"]
