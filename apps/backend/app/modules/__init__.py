"""Enabled modules — the explicit registry.

To enable a module, add its package name (under ``app.modules.<name>``)
to ``ENABLED_MODULES``. The startup ``load_all()`` imports each name in
order; each module's ``__init__.py`` constructs a ``ModuleManifest`` and
calls ``registry.register(...)``.

Why explicit list (not entry-point scanning):

- Zero third-party dependency, debuggable, no surprises at startup.
- rubbish does not run a plugin marketplace (see ARCHITECTURE.md
  "What we chose not to do"); vendored modules are all we need.
- Adding/removing a module is one line in one file.
"""

from __future__ import annotations

# Add module names here as they are implemented. All domain modules
# are now enabled. To add a new module, append its package name below;
# its package must exist at app/modules/<name>/ and its __init__.py must
# register a ModuleManifest.
ENABLED_MODULES: list[str] = [
    "catalog",
    "comments",
    "export",
    "reader",
    "submission",
    "review",
    "notifications",
    "follows",
    "library",
    "ingest",
    "recommendations",
    "doi",
    "gamification",
    "announcements",
    "quality",
    "forum",
]
