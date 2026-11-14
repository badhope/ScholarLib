from __future__ import annotations

import os
import time

from app.interfaces.http.submission import routes_files


def test_prunes_expired_source_previews(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes_files, "_source_preview_dir", lambda: tmp_path)
    now = time.time()
    expired = tmp_path / "expired.pdf"
    fresh = tmp_path / "fresh.pdf"
    expired.write_bytes(b"old")
    fresh.write_bytes(b"new")
    os.utime(expired, (now - 7 * 60 * 60, now - 7 * 60 * 60))
    os.utime(fresh, (now, now))

    routes_files._prune_source_previews(now=now)

    assert not expired.exists()
    assert fresh.exists()


def test_prunes_oldest_when_over_file_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes_files, "_source_preview_dir", lambda: tmp_path)
    monkeypatch.setattr(routes_files, "_SOURCE_PREVIEW_MAX_FILES", 2)
    now = time.time()
    for index in range(3):
        path = tmp_path / f"{index}.pdf"
        path.write_bytes(b"x")
        os.utime(path, (now - (3 - index), now - (3 - index)))

    routes_files._prune_source_previews(now=now)

    assert not (tmp_path / "0.pdf").exists()
    assert (tmp_path / "1.pdf").exists()
    assert (tmp_path / "2.pdf").exists()
