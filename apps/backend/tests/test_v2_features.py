"""2.0 新能力回归：JATS 导出、批量重审、每期 60 篇重排、在线正文编辑。

用户需求的验收面：

1. JATS XML 全文导出 —— well-formed XML、标题层级/行内标记/表格转换；
2. 批量重审 —— 七维分数 + 荒诞指数（必填）+ 显式类别落库、审计留痕；
3. 每期固定 60 篇 —— dry_run 预览 + 执行后按质量分顺序重排；
4. 在线正文编辑器 —— 作者可写/改正文，进入阅读与导出通道。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from conftest import auth_headers, register_user
from httpx import AsyncClient

from app.modules.export.exporters import export_resources
from app.modules.export.jats import JatsMeta, markdown_to_jats

_DIMS = ("problem", "argument", "method", "evidence", "novelty", "integrity", "presentation")


def _all(value: int, reason: str = "理由：正文第 2 节可核") -> list[dict[str, object]]:
    return [{"key": k, "score": value, "reason": reason} for k in _DIMS]


# --- JATS 转换器 -----------------------------------------------------------


def _parse(xml: str) -> ET.Element:
    """去掉 DOCTYPE 后解析（ElementTree 不取外部 DTD）。"""
    body = "\n".join(line for line in xml.splitlines() if not line.startswith("<!DOCTYPE"))
    return ET.fromstring(body)


def test_jats_converts_headings_and_inline_marks() -> None:
    md = (
        "# 1 引言\n\n这是**加粗**与*斜体*、《书名号》和 <mark>高亮</mark>。\n\n"
        "## 1.1 方法\n\nx<sup>2</sup> 与 H<sub>2</sub>O，<u>下划线</u>。\n\n"
        "- 甲\n- 乙\n\n| 项目 | 数值 |\n| --- | --- |\n| 甲 | 1 |\n"
    )
    xml = markdown_to_jats(md, JatsMeta(title="测试稿", authors=["张三"], year=2026))
    root = _parse(xml)  # must be well-formed
    assert root.tag == "article"
    body = root.find("body")
    assert body is not None
    text = ET.tostring(body, encoding="unicode")
    for tag in (
        "<bold>加粗</bold>",
        "<italic>斜体</italic>",
        "<styled-content",
        "<underline>下划线</underline>",
        "<sup>2</sup>",
        "<sub>2</sub>",
        "<list",
        "<table-wrap>",
        "<sec><title>1 引言</title>",
    ):
        assert tag in text, tag


def test_jats_escapes_raw_html_and_xml_specials() -> None:
    md = "段落含 <div>裸标签</div>、A&B 与 <script>alert(1)</script>。"
    xml = markdown_to_jats(md)
    root = _parse(xml)
    text = ET.tostring(root.find("body"), encoding="unicode")
    assert "<div>" not in text and "<script>" not in text
    assert "A&amp;B" in text


def test_bibliographic_jats_exporter(tmp_path) -> None:
    class R:  # Exportable duck type
        from typing import ClassVar

        id = 1
        title = "JATS Paper"
        authors: ClassVar[list[str]] = ["Alice"]
        year = 2026
        venue = "Rubbish"
        type = "paper"
        discipline = None
        tags: ClassVar[list[str]] = ["x"]
        abstract = "Abs"
        doi = "10.1/x"
        download_url = None
        external_url = None
        volume = "1"
        issue = "01"
        pages = "1-2"
        keywords: ClassVar[list[str]] = ["k"]

    out = export_resources("jats", [R()])
    root = _parse(out)
    assert root.tag == "article"
    assert root.findtext(".//article-title") == "JATS Paper"
    assert root.findtext(".//volume") == "1"


# --- 批量重审 --------------------------------------------------------------


async def _create_resource(client: AsyncClient, admin: dict, title: str, **extra) -> dict:
    payload = {
        "type": "paper",
        "title": title,
        "authors": ["Alice Author"],
        "year": 2024,
        "venue": "Journal of Testing",
        "discipline": "computer-science",
        "tags": ["test"],
        "abstract": "Abstract.",
        "preview": "Preview.",
        "keywords": ["k"],
        "publication_status": "published",
        **extra,
    }
    r = await client.post("/api/catalog", json=payload, headers=auth_headers(admin))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_batch_rescore_updates_score_absurdity_and_category(
    client: AsyncClient, admin_user: dict
) -> None:
    res = await _create_resource(client, admin_user, "重审目标稿")
    rid = res["id"]
    r = await client.post(
        "/api/quality/batch-rescore",
        json={
            "items": [
                {
                    "resource_id": rid,
                    "article_type": "research",
                    "dimensions": _all(62),
                    "absurdity_index": 3.5,
                    "content_category": "fun",
                    "verdict": "keep",
                    "note": "论证完整但方法偏薄",
                }
            ]
        },
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 1
    item = body["results"][0]
    assert item["ok"] is True
    assert item["grade"].startswith(("D", "C"))
    assert item["absurdity_index"] == 3.5
    assert item["category_changed"] is True

    # 落库复核：公开详情可见荒诞指数与类别
    detail = await client.get(f"/api/catalog/{rid}")
    assert detail.status_code == 200
    assert detail.json()["absurdity_index"] == 3.5
    assert detail.json()["content_category"] == "fun"

    # 审计留痕
    logs = await client.get(
        "/api/admin/audit-logs?action=quality.batch_rescore", headers=auth_headers(admin_user)
    )
    assert logs.status_code == 200


@pytest.mark.asyncio
async def test_batch_rescore_requires_admin(client: AsyncClient, test_user: dict) -> None:
    r = await client.post(
        "/api/quality/batch-rescore",
        json={"items": [{"resource_id": 1, "dimensions": _all(50), "absurdity_index": 1}]},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_batch_rescore_rejects_missing_dimension(
    client: AsyncClient, admin_user: dict
) -> None:
    res = await _create_resource(client, admin_user, "缺维度稿")
    r = await client.post(
        "/api/quality/batch-rescore",
        json={
            "items": [
                {
                    "resource_id": res["id"],
                    "dimensions": _all(50)[:-1],
                    "absurdity_index": 1,
                }
            ]
        },
        headers=auth_headers(admin_user),
    )
    # 请求级校验直接 422：缺维度的批请求整体拒绝，不做部分落库
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rework_queue_can_include_published(client: AsyncClient, admin_user: dict) -> None:
    res = await _create_resource(client, admin_user, "低分已发布稿")
    rid = res["id"]
    await client.post(
        "/api/quality/batch-rescore",
        json={"items": [{"resource_id": rid, "dimensions": _all(10), "absurdity_index": 8}]},
        headers=auth_headers(admin_user),
    )
    default = await client.get("/api/quality/rework-queue", headers=auth_headers(admin_user))
    ids_default = [row["id"] for row in default.json()["data"]]
    assert rid not in ids_default  # 已发布默认不进队列
    widened = await client.get(
        "/api/quality/rework-queue?include_published=true", headers=auth_headers(admin_user)
    )
    assert rid in [row["id"] for row in widened.json()["data"]]


# --- 每期 60 篇 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_rebalance_fixed_size_and_quality_order(
    client: AsyncClient, admin_user: dict
) -> None:
    ids: list[int] = []
    for i in range(65):
        res = await _create_resource(
            client, admin_user, f"重排稿 {i:02d}", doi=None, volume=None, issue=None
        )
        ids.append(res["id"])
    # 给前 10 篇高质量分（通过批量重审），验证排序键生效
    await client.post(
        "/api/quality/batch-rescore",
        json={
            "items": [
                {"resource_id": rid, "dimensions": _all(90), "absurdity_index": 1}
                for rid in ids[:10]
            ]
        },
        headers=auth_headers(admin_user),
    )
    preview = await client.post(
        "/api/catalog/issues/rebalance",
        json={"issue_size": 60, "dry_run": True},
        headers=auth_headers(admin_user),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["issues"] == {"01": 60, "02": 5}
    assert preview.json()["dry_run"] is True

    done = await client.post(
        "/api/catalog/issues/rebalance",
        json={"issue_size": 60},
        headers=auth_headers(admin_user),
    )
    assert done.status_code == 200
    assert done.json()["issues"] == {"01": 60, "02": 5}

    listing = await client.get("/api/catalog", params={"page_size": 1})
    assert listing.status_code == 200
    # 高质量分应排在第 1 期
    first_issue_ids = [a["resource_id"] for a in done.json()["assignments"][:10]]
    assert set(ids[:10]).issubset(set(first_issue_ids))


# --- 在线正文编辑器 ---------------------------------------------------------


_SUBMISSION = {
    "title": "在线正文测试稿",
    "type": "paper",
    "authors": ["Bob Writer"],
    "year": 2026,
    "discipline": "computer science",
    "tags": ["editor"],
    "abstract": "摘要",
    "preview": "预览",
}


@pytest.mark.asyncio
async def test_online_markdown_roundtrip(client: AsyncClient, test_user: dict) -> None:
    created = (
        await client.post("/api/submissions", json=_SUBMISSION, headers=auth_headers(test_user))
    ).json()
    sid = created["id"]
    body_md = "# 1 引言\n\n**加粗**正文与《书名号》。"
    saved = await client.put(
        f"/api/submissions/{sid}/markdown",
        json={"content": body_md},
        headers=auth_headers(test_user),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["markdown_path"]

    fetched = await client.get(f"/api/submissions/{sid}/markdown", headers=auth_headers(test_user))
    assert fetched.status_code == 200
    assert fetched.json()["content"] == body_md


@pytest.mark.asyncio
async def test_online_markdown_forbidden_for_stranger(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    created = (
        await client.post("/api/submissions", json=_SUBMISSION, headers=auth_headers(test_user))
    ).json()
    stranger = await register_user(client, email="stranger@example.com", username="stranger_md")
    r = await client.put(
        f"/api/submissions/{created['id']}/markdown",
        json={"content": "x"},
        headers=auth_headers(stranger),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_online_markdown_size_limit(client: AsyncClient, test_user: dict) -> None:
    created = (
        await client.post("/api/submissions", json=_SUBMISSION, headers=auth_headers(test_user))
    ).json()
    r = await client.put(
        f"/api/submissions/{created['id']}/markdown",
        json={"content": "x" * 1_000_001},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 422
