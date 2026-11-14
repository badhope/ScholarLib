"""Ingest module — parse BibTeX/RIS/CSV files and fetch metadata by DOI/arXiv ID.

The ingest module is a thin "import gateway": it normalizes external
bibliographic data into a standard ``IngestResource`` shape but never
writes to the catalog table itself. The frontend takes the returned
objects and submits them via ``/api/submissions`` so the catalog keeps
a single write path.

Owns no database tables (stateless transformers + HTTP fetchers).
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.interfaces.http.ingest.routes import router

registry.register(
    ModuleManifest(
        name="ingest",
        version="0.1.0",
        description="Parse BibTeX/RIS/CSV and fetch metadata from Crossref/arXiv.",
        dependencies=frozenset(),
        router=router,
    )
)
