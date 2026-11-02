"""Edge paths of the submission file endpoints: size limit, Range, redirects."""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient

_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


async def _create_submission(client: AsyncClient, token: str) -> int:
    r = await client.post(
        "/api/submissions",
        json={
            "title": "Files Edge Cases",
            "type": "paper",
            "authors": ["边界作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证文件端点边界行为。",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _upload(
    client: AsyncClient,
    token: str,
    sid: int,
    content: bytes = _PDF,
    name: str = "paper.pdf",
    mime: str = "application/pdf",
):
    return await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": (name, content, mime)},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_upload_rejects_oversize_file(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.submission import routes_files

    monkeypatch.setattr(routes_files, "_MAX_UPLOAD_BYTES", 256)
    sid = await _create_submission(client, test_user["token"])
    r = await _upload(client, test_user["token"], sid, content=b"x" * 1024)
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_upload_truncates_overlong_extension(client: AsyncClient, test_user: dict) -> None:
    sid = await _create_submission(client, test_user["token"])
    r = await _upload(
        client,
        test_user["token"],
        sid,
        name=f"paper.{'a' * 30}",
        mime="text/plain",
        content=b"plain text body",
    )
    assert r.status_code == 200
    file_path = r.json().get("file_path") or ""
    # 新语义：不合规扩展名（超长）整体丢弃而不是截断——存储 key 里
    # 不应出现半个控制字符序列，截断可能留下它。
    assert "." not in file_path.rsplit("/", 1)[1]


@pytest.mark.asyncio
async def test_download_returns_206_for_valid_range(client: AsyncClient, test_user: dict) -> None:
    sid = await _create_submission(client, test_user["token"])
    up = await _upload(client, test_user["token"], sid)
    assert up.status_code == 200

    r = await client.get(
        f"/api/submissions/{sid}/files",
        headers={**auth_headers(test_user), "Range": "bytes=0-3"},
    )
    assert r.status_code == 206
    assert r.headers["Content-Range"].startswith("bytes 0-3/")
    assert r.headers["Accept-Ranges"] == "bytes"
    assert len(r.content) == 4


@pytest.mark.asyncio
async def test_download_open_ended_range(client: AsyncClient, test_user: dict) -> None:
    sid = await _create_submission(client, test_user["token"])
    await _upload(client, test_user["token"], sid)

    r = await client.get(
        f"/api/submissions/{sid}/files",
        headers={**auth_headers(test_user), "Range": "bytes=2-"},
    )
    assert r.status_code == 206
    assert r.headers["Content-Range"].startswith("bytes 2-")


@pytest.mark.asyncio
async def test_download_invalid_range_falls_back_to_200(
    client: AsyncClient, test_user: dict
) -> None:
    sid = await _create_submission(client, test_user["token"])
    await _upload(client, test_user["token"], sid)

    r = await client.get(
        f"/api/submissions/{sid}/files",
        headers={**auth_headers(test_user), "Range": "bytes=99999-"},
    )
    assert r.status_code == 200
    assert len(r.content) == len(_PDF)


@pytest.mark.asyncio
async def test_download_presigned_redirect(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.storage import get_storage

    sid = await _create_submission(client, test_user["token"])
    await _upload(client, test_user["token"], sid)

    monkeypatch.setattr(
        get_storage(), "presigned_url", lambda path: f"https://s3.example.com/{path}"
    )
    r = await client.get(f"/api/submissions/{sid}/files", headers=auth_headers(test_user))
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://s3.example.com/")


@pytest.mark.asyncio
async def test_download_missing_storage_file_404(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.storage import get_storage

    sid = await _create_submission(client, test_user["token"])
    await _upload(client, test_user["token"], sid)

    async def missing(path: str) -> bytes:
        raise FileNotFoundError(path)

    monkeypatch.setattr(get_storage(), "load", missing)
    r = await client.get(f"/api/submissions/{sid}/files", headers=auth_headers(test_user))
    assert r.status_code == 404


async def test_upload_accepts_markdown_latex_and_data_files(
    client: AsyncClient, test_user: dict
) -> None:
    """扩展名命中即放行：浏览器对 .md/.tex/.csv 报的 content-type 不可靠。"""
    sid = await _create_submission(client, test_user["token"])
    cases = [
        ("notes.md", "text/markdown", b"# heading\n"),
        ("paper.tex", "application/octet-stream", b"\\documentclass{article}"),
        ("table.csv", "", b"a,b\n1,2\n"),
        ("figure.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 64),
        ("bundle.zip", "application/x-zip-compressed", b"PK\x03\x04fake"),
    ]
    for name, mime, content in cases:
        r = await _upload(client, test_user["token"], sid, content=content, name=name, mime=mime)
        assert r.status_code == 200, f"{name}: {r.text[:200]}"


async def test_upload_rejects_unknown_extension(client: AsyncClient, test_user: dict) -> None:
    sid = await _create_submission(client, test_user["token"])
    r = await _upload(
        client,
        test_user["token"],
        sid,
        content=b"MZ\x90\x00",
        name="setup.exe",
        mime="application/x-msdownload",
    )
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]
    # 错误信息必须列出可接受扩展名，便于作者自救
    assert ".pdf" in r.json()["detail"]


async def test_capabilities_exposes_upload_limits(client: AsyncClient) -> None:
    body = (await client.get("/api/capabilities")).json()
    assert body["upload_max_bytes"] == 50 * 1024 * 1024
    assert ".pdf" in body["upload_extensions"]
    assert ".ipynb" in body["upload_extensions"]
