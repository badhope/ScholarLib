"""Physical architecture contract.

Layering is not documentation: real implementations live in
``app/domain`` (business) and ``app/interfaces/http`` (inbound adapters),
while ``app/core`` stays the foundation. Legacy ``app/modules`` packages
are composition manifests + compatibility shims only.

The rules below fail CI if a future change reintroduces an inward-out
dependency (domain -> API/interface, foundation -> domain/interface).
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_domain_does_not_import_inbound_layers() -> None:
    offenders = []
    for path in _files(APP / "domain"):
        for name in _imports(path):
            if name.startswith(("app.api", "app.interfaces", "app.modules", "fastapi")):
                offenders.append(f"{path.relative_to(APP)} -> {name}")
    assert not offenders, "domain layer imports inbound layers:\n" + "\n".join(offenders)


def test_foundation_does_not_import_business_or_inbound() -> None:
    # app/core/modules.py is the composition root: loading manifests is the
    # one place where foundation must reach the module registry.
    offenders = []
    for path in _files(APP / "core"):
        rel = str(path.relative_to(APP))
        for name in _imports(path):
            if rel == "core/modules.py" and name.startswith("app.modules"):
                continue
            if name.startswith(("app.domain", "app.interfaces", "app.modules")):
                offenders.append(f"{rel} -> {name}")
    assert not offenders, "foundation layer imports business/inbound:\n" + "\n".join(offenders)


def test_each_domain_has_physical_layer_home() -> None:
    for name in ("catalog", "submission", "review", "notifications", "gamification"):
        assert (APP / "domain" / name / "models.py").is_file(), name
        assert (APP / "interfaces" / "http" / name / "routes.py").is_file(), name


def test_legacy_modules_are_manifests_or_shims_only() -> None:
    for path in _files(APP / "modules"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert text.startswith('"""Compatibility shim.'), (
            f"real code still lives under app/modules: {path.relative_to(APP)}"
        )


def test_submission_editor_routes_are_mounted() -> None:
    """Sub-route modules attach to the shared router via side-effect imports.

    A linter or refactor that drops those imports silently removes 10
    editor/review endpoints from OpenAPI. Keep an explicit contract.
    """
    from app.interfaces.http.submission.routes import router

    mounted = {route.path for route in router.routes}
    expected = {
        "/submissions/pending",
        "/submissions/reviewer-candidates",
        "/submissions/{submission_id}/anonymized-file",
        "/submissions/{submission_id}/assignments",
        "/submissions/{submission_id}/assignments/{assignment_id}",
        "/submissions/{submission_id}/decision",
        "/submissions/{submission_id}/reports",
        "/submissions/{submission_id}/review",
        "/submissions/{submission_id}/rework",
        "/submissions/{submission_id}/waive-review",
    }
    missing = expected - mounted
    assert not missing, f"shared submission router lost endpoints: {sorted(missing)}"
