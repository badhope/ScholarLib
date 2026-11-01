"""Tests for the pluggable storage layer (local / S3).

Local backend is exercised for real against tmp_path. The S3 backend is
tested with a stubbed boto3 client — the contract under test is key
validation, not-found translation, and presigned-URL degradation, none
of which need a live server.

End-to-end: upload → download через the submission routes, including the
authorization matrix (author / editor / assigned reviewer / stranger).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from conftest import auth_headers, register_user
from httpx import AsyncClient

from app.core import storage as storage_mod
from app.core.config import settings
from app.core.storage import LocalStorage, S3Storage, StorageError


@pytest.fixture(autouse=True)
def _reset_storage() -> Any:
    storage_mod.reset_storage_cache()
    yield
    storage_mod.reset_storage_cache()


# ---------------------------------------------------------------------------
# LocalStorage
# ---------------------------------------------------------------------------


async def test_local_roundtrip(tmp_path: Path) -> None:
    s = LocalStorage(str(tmp_path))
    await s.save("1/2/file.pdf", b"hello")
    assert await s.exists("1/2/file.pdf") is True
    assert await s.load("1/2/file.pdf") == b"hello"
    assert s.presigned_url("1/2/file.pdf") is None  # local never issues URLs
    await s.delete("1/2/file.pdf")
    assert await s.exists("1/2/file.pdf") is False


async def test_local_load_missing_raises(tmp_path: Path) -> None:
    s = LocalStorage(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        await s.load("nope/missing.pdf")


@pytest.mark.parametrize("bad_key", ["/etc/passwd", "../secret", "a/../../b", ""])
async def test_local_rejects_traversal(tmp_path: Path, bad_key: str) -> None:
    s = LocalStorage(str(tmp_path))
    with pytest.raises(StorageError):
        await s.save(bad_key, b"x")


# ---------------------------------------------------------------------------
# S3Storage (stubbed client)
# ---------------------------------------------------------------------------


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.presign_ok = True

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise _not_found()
        return {"Body": BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise _not_found()
        return {}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop(Key, None)

    def generate_presigned_url(self, *_a: Any, **_k: Any) -> str:
        if not self.presign_ok:
            raise RuntimeError("presign broken")
        return "https://s3.example.org/signed"


def _not_found() -> Exception:
    exc = RuntimeError("not found")
    exc.response = {  # type: ignore[attr-defined]
        "Error": {"Code": "NoSuchKey"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }
    return exc


def _make_s3(monkeypatch: pytest.MonkeyPatch) -> tuple[S3Storage, _FakeS3Client]:
    fake = _FakeS3Client()
    s = S3Storage.__new__(S3Storage)
    s._bucket = "test-bucket"
    s._client = fake
    return s, fake


async def test_s3_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    s, _fake = _make_s3(monkeypatch)
    await s.save("1/2/f.pdf", b"data", content_type="application/pdf")
    assert await s.exists("1/2/f.pdf") is True
    assert await s.load("1/2/f.pdf") == b"data"
    await s.delete("1/2/f.pdf")
    assert await s.exists("1/2/f.pdf") is False


async def test_s3_missing_translates_to_file_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s, _ = _make_s3(monkeypatch)
    with pytest.raises(FileNotFoundError):
        await s.load("ghost.pdf")


async def test_s3_presign_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    s, fake = _make_s3(monkeypatch)
    assert s.presigned_url("k.pdf") == "https://s3.example.org/signed"
    fake.presign_ok = False
    assert s.presigned_url("k.pdf") is None  # 失败 → None → 路由回落流式


# ---------------------------------------------------------------------------
# End-to-end: upload → download + authorization matrix
# ---------------------------------------------------------------------------

_PAYLOAD = {
    "title": "Storage E2E Test",
    "type": "paper",
    "authors": ["Alice"],
    "year": 2024,
    "discipline": "computer science",
    "tags": [],
    "abstract": "abstract for storage e2e",
}


async def _submit_with_file(
    client: AsyncClient, user: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    monkeypatch.setattr(settings, "storage_path", str(tmp_path), raising=False)
    storage_mod.reset_storage_cache()
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(user))
    assert created.status_code == 201
    submission = created.json()
    uploaded = await client.post(
        f"/api/submissions/{submission['id']}/files",
        files={"file": ("paper.pdf", BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        headers=auth_headers(user),
    )
    assert uploaded.status_code == 200
    return uploaded.json()


async def test_author_downloads_own_file(
    client: AsyncClient, test_user: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submission = await _submit_with_file(client, test_user, tmp_path, monkeypatch)
    resp = await client.get(
        f"/api/submissions/{submission['id']}/files", headers=auth_headers(test_user)
    )
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 test"
    assert "attachment" in resp.headers["content-disposition"]


async def test_admin_downloads_file(
    client: AsyncClient,
    admin_user: dict,
    test_user: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = await _submit_with_file(client, test_user, tmp_path, monkeypatch)
    resp = await client.get(
        f"/api/submissions/{submission['id']}/files", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200


async def test_stranger_cannot_download(
    client: AsyncClient,
    test_user: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既非作者、也非编辑/审稿人的普通用户必须拿不到未发表稿件。"""
    submission = await _submit_with_file(client, test_user, tmp_path, monkeypatch)
    stranger = await register_user(client, email="stranger@example.com", username="stranger")
    resp = await client.get(
        f"/api/submissions/{submission['id']}/files",
        headers={"Authorization": f"Bearer {stranger['token']}"},
    )
    assert resp.status_code == 403


async def test_download_404_when_no_file(client: AsyncClient, test_user: dict) -> None:
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    assert created.status_code == 201
    resp = await client.get(
        f"/api/submissions/{created.json()['id']}/files",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 404


async def test_download_requires_auth(
    client: AsyncClient, test_user: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submission = await _submit_with_file(client, test_user, tmp_path, monkeypatch)
    resp = await client.get(f"/api/submissions/{submission['id']}/files")
    assert resp.status_code == 401


async def test_replace_upload_removes_old_file(
    client: AsyncClient, test_user: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """替换式上传应清理被覆盖的旧文件，否则磁盘 / S3 会累积孤儿对象。"""
    monkeypatch.setattr(settings, "storage_path", str(tmp_path), raising=False)
    storage_mod.reset_storage_cache()
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    assert created.status_code == 201
    sid = created.json()["id"]

    first = await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": ("a.pdf", BytesIO(b"%PDF-1.4 first"), "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert first.status_code == 200
    old_fp = first.json()["file_path"]
    assert await storage_mod.get_storage().exists(old_fp) is True

    second = await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": ("b.pdf", BytesIO(b"%PDF-1.4 second"), "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert second.status_code == 200
    new_fp = second.json()["file_path"]
    assert new_fp != old_fp
    # 旧文件应已被 best-effort 清理，新文件保留。
    assert await storage_mod.get_storage().exists(old_fp) is False
    assert await storage_mod.get_storage().exists(new_fp) is True


async def test_delete_submission_removes_file(
    client: AsyncClient, test_user: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """删除 pending 稿件应同步清理其存储文件，避免残留 PDF 孤儿对象。"""
    monkeypatch.setattr(settings, "storage_path", str(tmp_path), raising=False)
    storage_mod.reset_storage_cache()
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    assert created.status_code == 201
    sid = created.json()["id"]

    up = await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": ("p.pdf", BytesIO(b"%PDF-1.4 del"), "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert up.status_code == 200
    fp = up.json()["file_path"]
    assert await storage_mod.get_storage().exists(fp) is True

    deleted = await client.delete(f"/api/submissions/{sid}", headers=auth_headers(test_user))
    assert deleted.status_code == 200
    # 稿件已删，存储文件应一并清理。
    assert await storage_mod.get_storage().exists(fp) is False
