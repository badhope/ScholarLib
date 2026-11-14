"""P1-10：审稿人季度校准。"""

from __future__ import annotations

from conftest import auth_headers, complete_one_review
from httpx import AsyncClient

_PAYLOAD = {
    "title": "Calibration Test Submission",
    "type": "paper",
    "authors": ["Calibration Author"],
    "year": 2024,
    "discipline": "computer science",
    "tags": ["test"],
    "abstract": "An abstract for calibration.",
    "preview": "A short preview for calibration.",
    "doi": "10.1234/test.calibration.001",
}


async def test_calibration_empty_quarter(client: AsyncClient, admin_user: dict) -> None:
    r = await client.get(
        "/api/review/calibration?year=2000&quarter=1",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reviewers"] == []
    assert body["submission_count"] == 0


async def test_calibration_reports_per_reviewer_after_two_reviews(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    r = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    assert r.status_code == 201, r.text
    submission_id = r.json()["id"]
    await complete_one_review(client, admin_user, submission_id, reviewer_name="cal")

    r = await client.get("/api/review/calibration", headers=auth_headers(admin_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submission_count"] >= 1
    assert len(body["reviewers"]) >= 2
    for row in body["reviewers"]:
        assert row["completed_reviews"] >= 1
        assert "insufficient_volume" in row["flags"]


async def test_calibration_requires_editor(client: AsyncClient, test_user: dict) -> None:
    r = await client.get("/api/review/calibration", headers=auth_headers(test_user))
    assert r.status_code == 403
