"""在线阅读 Markdown 稿件：转换服务 + /catalog/{id}/manuscript 端点。"""

from __future__ import annotations

import io
import zipfile

import pymupdf
import pytest
from httpx import AsyncClient

from app.modules.submission.manuscript import convert_to_markdown, markdown_storage_key
from tests.test_catalog import _SAMPLE


def _make_pdf(text: str = "奶蛙叙事的演化路径考察") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    # P0 质量闸门要求正文 ≥300 字：样例 PDF 用一长段不重复中文，
    # 使闸门通过；断言仍校验关键短语出现在抽取结果里。
    body = (
        text
        + "。"
        + "".join(
            f"第{i}段：这是用于凑足质量闸门阈值的不重复中文正文，讨论{n}话题的相关内容。"
            for i, n in enumerate(
                [
                    "分布一致性",
                    "事务隔离",
                    "容错恢复",
                    "排队论",
                    "数据建模",
                    "系统设计",
                    "缓存策略",
                    "负载均衡",
                    "监控告警",
                    "容量规划",
                    "灰度发布",
                    "容灾备份",
                    "权限模型",
                    "审计日志",
                    "接口契约",
                    "测试覆盖",
                    "性能调优",
                    "成本核算",
                ],
                start=1,
            )
        )
    )
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 780), body, fontname="china-s", fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _make_pdf_with_image(text: str = "含图论文") -> bytes:
    """含位图的 PDF：pymupdf4llm 会抽取图片并在 Markdown 里留文件引用。"""
    doc = pymupdf.open()
    page = doc.new_page()
    body = (
        text
        + "。"
        + "".join(
            f"第{i}段：这是凑足质量闸门阈值的不重复中文正文，讨论{n}话题的相关内容。"
            for i, n in enumerate(
                [
                    "一致性",
                    "隔离",
                    "容错",
                    "建模",
                    "设计",
                    "缓存",
                    "均衡",
                    "告警",
                    "规划",
                    "灰度",
                    "容灾",
                    "权限",
                    "审计",
                    "契约",
                    "覆盖",
                ],
                start=1,
            )
        )
    )
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 220), body, fontname="china-s", fontsize=9)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(72, 260, 300, 380), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _make_docx(text: str = "排队论建模的实证研究") -> bytes:
    """最小可解析 docx（mammoth 只需 document.xml 的段落文本）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 转换服务
# ---------------------------------------------------------------------------


def test_convert_pdf_extracts_text() -> None:
    md = convert_to_markdown(_make_pdf(), "thesis.pdf")
    assert md is not None
    assert "奶蛙叙事" in md


def test_convert_pdf_images_are_inlined_as_data_uri() -> None:
    """回归：Windows 下 pymupdf4llm 产出 `![](C:/.../rubbish-md-xxx/-0001-00.png)`
    绝对路径，旧实现按相对文件名匹配，图片全部落空（data URI 0 个、阅读器空图）。
    1.6.0 起默认输出 JPEG，故只断言 data URI 而非具体格式。"""
    md = convert_to_markdown(_make_pdf_with_image(), "with-image.pdf")
    assert md is not None
    assert "data:image/" in md
    assert ";base64," in md
    assert "rubbish-md-" not in md
    assert "C:/" not in md


def test_pdf_image_embedding_does_not_replace_unrelated_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    import pymupdf4llm

    def fake_convert(doc: object, **kwargs: object) -> str:
        image_path = Path(str(kwargs["image_path"])) / "image.png"
        image_path.write_bytes(b"image")
        return f"![local]({image_path.as_posix()})\n![remote](https://example.org/image.png)"

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_convert)
    from app.modules.submission.manuscript import _pdf_to_markdown

    md = _pdf_to_markdown(_make_pdf())
    assert md is not None
    assert "![local](data:image/png;base64," in md
    assert "![remote](https://example.org/image.png)" in md


def test_pdf_embedded_jpeg_preserves_original_bytes() -> None:
    import base64
    import re

    from app.modules.submission.manuscript import _pdf_to_markdown

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(150)
    original = pix.tobytes("jpeg")
    doc = pymupdf.open()
    page = doc.new_page()
    xref = page.insert_image(pymupdf.Rect(72, 140, 300, 260), stream=original)
    doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
    contents = doc.tobytes()
    doc.close()

    md = _pdf_to_markdown(contents)
    assert md is not None
    images = re.findall(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", md)
    assert any(base64.b64decode(image) == original for image in images)


@pytest.mark.parametrize(
    "pdf_colorspace", ["/DeviceGray", "/DeviceCMYK", "[/CalRGB << /WhitePoint [1 1 1] >>]"]
)
def test_pdf_original_image_rejects_mismatched_colorspace(pdf_colorspace: str) -> None:
    from app.modules.submission.manuscript import _original_simple_pdf_image

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(150)
    doc = pymupdf.open()
    page = doc.new_page()
    xref = page.insert_image(pymupdf.Rect(72, 140, 300, 260), stream=pix.tobytes("jpeg"))
    doc.xref_set_key(xref, "ColorSpace", pdf_colorspace)
    assert _original_simple_pdf_image(doc) is None
    doc.close()


@pytest.mark.parametrize(
    "variant",
    [
        "text",
        "drawing",
        "two_images",
        "rotated",
        "masked",
        "two_pages",
        "clipped",
        "decode",
        "stretched",
        "color_key_mask",
        "default_rgb",
        "inherited_default_rgb",
    ],
)
def test_pdf_original_image_requires_simple_page(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    from pathlib import Path

    import pymupdf4llm

    from app.modules.submission.manuscript import _pdf_to_markdown

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(150)
    original = pix.tobytes("jpeg")
    doc = pymupdf.open()
    page = doc.new_page()
    rect = pymupdf.Rect(72, 140, 300, 260)
    if variant == "masked":
        mask = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 120, 80), False)
        mask.clear_with(128)
        page.insert_image(rect, stream=original, mask=mask.tobytes("png"))
    else:
        page.insert_image(
            rect,
            stream=original,
            rotate=90 if variant == "rotated" else 0,
            keep_proportion=variant != "stretched",
        )
    doc.xref_set_key(page.get_images()[0][0], "ColorSpace", "/DeviceRGB")
    if variant == "color_key_mask":
        doc.xref_set_key(page.get_images()[0][0], "Mask", "[0 255 0 255 0 255]")
    if variant in {"default_rgb", "inherited_default_rgb"}:
        resources = doc.xref_get_key(page.xref, "Resources")[1]
        resource_xref = int(resources.split()[0])
        doc.xref_set_key(
            resource_xref, "ColorSpace", "<< /DefaultRGB [/CalRGB << /WhitePoint [1 1 1] >>] >>"
        )
        if variant == "inherited_default_rgb":
            parent = int(doc.xref_get_key(page.xref, "Parent")[1].split()[0])
            doc.xref_set_key(parent, "Resources", resources)
            doc.xref_set_key(page.xref, "Resources", "null")
    if variant == "decode":
        doc.xref_set_key(page.get_images()[0][0], "Decode", "[1 0 1 0 1 0]")
    if variant == "text":
        page.insert_text((72, 100), "text")
    if variant == "drawing":
        page.draw_rect(pymupdf.Rect(10, 10, 20, 20))
    if variant == "two_images":
        page.insert_image(pymupdf.Rect(10, 10, 50, 50), stream=original)
    if variant == "two_pages":
        doc.new_page()
    if variant == "clipped":
        xref = page.get_contents()[0]
        stream = doc.xref_stream(xref)
        doc.update_stream(xref, b"q 001010 re W n " + stream + b" Q")
    contents = doc.tobytes()
    doc.close()

    def fake_convert(doc: object, **kwargs: object) -> str:
        path = Path(str(kwargs["image_path"])) / "image.jpeg"
        path.write_bytes(b"rendered")
        return f"![image]({path.as_posix()})"

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_convert)
    md = _pdf_to_markdown(contents)
    assert md is not None
    assert base64.b64encode(b"rendered").decode() in md
    assert base64.b64encode(original).decode() not in md


def test_pdf_original_image_inspection_exception_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    from pathlib import Path

    import pymupdf4llm

    from app.modules.submission.manuscript import _pdf_to_markdown

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(150)
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(72, 140, 300, 260), stream=pix.tobytes("jpeg"))
    contents = doc.tobytes()
    doc.close()

    def fake_convert(doc: object, **kwargs: object) -> str:
        path = Path(str(kwargs["image_path"])) / "image.jpeg"
        path.write_bytes(b"rendered")
        return f"![image]({path.as_posix()})"

    def fail_inspection(*args: object, **kwargs: object) -> object:
        raise OSError("inspection failed")

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_convert)
    monkeypatch.setattr(pymupdf.Document, "extract_image", fail_inspection)
    md = _pdf_to_markdown(contents)
    assert md is not None
    assert base64.b64encode(b"rendered").decode() in md


def test_pdf_image_with_overlay_keeps_rendered_content() -> None:
    import base64
    import re

    from app.modules.submission.manuscript import _pdf_to_markdown

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.clear_with(150)
    original = pix.tobytes("jpeg")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 140, 300, 260), stream=original)
    page.draw_rect(pymupdf.Rect(140, 170, 230, 230), color=(1, 0, 0), fill=(1, 0, 0))
    contents = doc.tobytes()
    doc.close()

    md = _pdf_to_markdown(contents)
    assert md is not None
    images = re.findall(r"data:image/(?:jpeg|png);base64,([A-Za-z0-9+/=]+)", md)
    assert images
    rendered = [base64.b64decode(image) for image in images]
    assert original not in rendered
    assert any(
        pix.n == 3
        and any(
            r > 200 and g < 80 and b < 80
            for r, g, b in zip(pix.samples[0::3], pix.samples[1::3], pix.samples[2::3], strict=True)
        )
        for pix in (pymupdf.Pixmap(image) for image in rendered)
    )


def test_convert_docx_extracts_text() -> None:
    md = convert_to_markdown(_make_docx(), "thesis.docx")
    assert md is not None
    assert "排队论建模" in md


def test_convert_unsupported_returns_none() -> None:
    assert convert_to_markdown(b"PK\x03\x04 zip bytes", "attachment.zip") is None
    assert convert_to_markdown(b"\xd0\xcf\x11\xe0 legacy doc", "legacy.doc") is None


def test_convert_corrupt_pdf_fails_closed() -> None:
    assert convert_to_markdown(b"%PDF-1.4 not really a pdf", "broken.pdf") is None


def test_markdown_storage_key_pairs_with_file() -> None:
    assert markdown_storage_key("tenant/3/abc.pdf") == "tenant/3/abc.md"
    assert markdown_storage_key("tenant/3/abc") == "tenant/3/abc.md"


# ---------------------------------------------------------------------------
# 端点：上传 → 转换 → 录用刊出 → 匿名可读
# ---------------------------------------------------------------------------


async def _author_submit_with_docx(client: AsyncClient, test_user: dict) -> int:
    r = await client.post(
        "/api/submissions",
        json={
            "title": "Markdown 稿件流程验证",
            "type": "paper",
            "authors": ["流程作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证 markdown 转换链路。",
        },
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    up = await client.post(
        f"/api/submissions/{sid}/files",
        files={
            "file": (
                "thesis.docx",
                _make_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert up.status_code == 200, up.text[:200]
    return sid


async def test_markdown_upload_preserves_original_bytes(
    client: AsyncClient, test_user: dict
) -> None:
    sid = await _author_submit_with_docx(client, test_user)
    original = b"# Heading\r\n\r\nFirst line\r\nsecond line\r\n"
    headers = {"Authorization": f"Bearer {test_user['token']}"}
    response = await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": ("original.md", original, "text/markdown")},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["file_path"] != response.json()["markdown_path"]
    downloaded = await client.get(f"/api/submissions/{sid}/files?format=md", headers=headers)
    assert downloaded.content == original


async def test_upload_converts_docx_to_markdown(client: AsyncClient, test_user: dict) -> None:
    sid = await _author_submit_with_docx(client, test_user)
    mine = await client.get(
        "/api/submissions/me", headers={"Authorization": f"Bearer {test_user['token']}"}
    )
    entry = next(s for s in mine.json()["data"] if s["id"] == sid)
    assert entry["markdown_path"]


async def test_manuscript_public_after_publish(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sid = await _author_submit_with_docx(client, test_user)
    from conftest import complete_one_review

    await complete_one_review(client, admin_user, sid)
    d = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert d.status_code == 200
    rid = d.json().get("resource_id")
    assert rid

    anon = await client.get(f"/api/catalog/{rid}/manuscript")
    assert anon.status_code == 200
    assert anon.headers["content-type"].startswith("text/markdown")
    assert "排队论建模" in anon.text

    detail = (await client.get(f"/api/catalog/{rid}")).json()
    assert detail["has_markdown"] is True
    assert detail["has_file"] is True


@pytest.mark.parametrize("status_value", ["draft", "in_review"])
async def test_manuscript_hidden_for_unpublished(
    client: AsyncClient, admin_user: dict, status_value: str
) -> None:
    """未刊稿的 md 与 PDF 同边界：对无权限者 404。"""
    r = await client.post(
        "/api/catalog",
        json={
            **_SAMPLE,
            "title": f"Manuscript Hidden {status_value}",
            "publication_status": status_value,
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = r.json()["id"]
    anon = await client.get(f"/api/catalog/{rid}/manuscript")
    assert anon.status_code == 404


async def test_manuscript_404_when_no_submission_file(
    client: AsyncClient, admin_user: dict
) -> None:
    r = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": "No Manuscript Here"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = r.json()["id"]
    assert (await client.get(f"/api/catalog/{rid}/manuscript")).status_code == 404


async def test_list_has_markdown_flag(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sid = await _author_submit_with_docx(client, test_user)
    from conftest import complete_one_review

    await complete_one_review(client, admin_user, sid)
    d = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = d.json()["resource_id"]
    listing = (await client.get("/api/catalog?page_size=50")).json()
    flags = {item["id"]: item["has_markdown"] for item in listing["data"]}
    assert flags[rid] is True


# --- 1.14.1：内嵌 data-URI 图片拆分为 /img/{n} 只读端点 --------------------

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


async def _seed_published_md(
    client: AsyncClient,
    db_session,
    admin_user: dict,
    *,
    md_text: str,
    status: str = "published",
) -> int:
    """落一篇带内嵌图 Markdown 的资源，返回 resource id。"""
    from sqlalchemy import select as sa_select

    from app.core.storage import get_storage
    from app.models import Tenant
    from app.modules.submission.models import Submission
    from tests.test_catalog import _SAMPLE

    payload = {**_SAMPLE, "title": "Embedded Image Split", "publication_status": status}
    r = await client.post(
        "/api/catalog", json=payload, headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    r.raise_for_status()
    rid = r.json()["id"]
    tenant = (
        await db_session.execute(sa_select(Tenant).where(Tenant.slug == "default"))
    ).scalar_one()
    rel = f"{tenant.id}/{rid}/embedded.md"
    await get_storage().save(rel, md_text.encode("utf-8"))
    db_session.add(
        Submission(
            tenant_id=tenant.id,
            resource_id=rid,
            submitted_by=admin_user["user_id"],
            title="Embedded Image Split",
            type="paper",
            discipline="computer-science",
            authors=["Anon"],
            year=2026,
            abstract="abstract",
            preview="preview",
            tags=[],
            status="accepted",
            markdown_path=rel,
        )
    )
    await db_session.commit()
    return rid


async def test_manuscript_rewrites_data_uri_to_img_endpoint(
    client: AsyncClient, db_session, admin_user: dict
) -> None:
    md_text = (
        "# 拆分测试\n\n"
        "正文第一段必须原样保留。\n\n"
        f"![示意图](data:image/png;base64,{_TINY_PNG_B64})\n\n"
        "## 1 引言\n\n"
        "后续文字。\n"
    )
    rid = await _seed_published_md(client, db_session, admin_user, md_text=md_text)

    resp = await client.get(f"/api/catalog/{rid}/manuscript")
    assert resp.status_code == 200
    body = resp.text
    # 内嵌 data URI 被就地替换
    assert "data:image/" not in body
    assert f"/api/catalog/{rid}/img/1" in body
    # 正文与图注不丢
    assert "正文第一段必须原样保留。" in body
    assert "![示意图]" in body


async def test_img_endpoint_serves_bytes_and_headers(
    client: AsyncClient, db_session, admin_user: dict
) -> None:
    import base64

    md_text = f"# 图\n\n![a](data:image/png;base64,{_TINY_PNG_B64})\n"
    rid = await _seed_published_md(client, db_session, admin_user, md_text=md_text)

    img = await client.get(f"/api/catalog/{rid}/img/1")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content == base64.b64decode(_TINY_PNG_B64)
    assert "immutable" in img.headers["cache-control"]
    assert img.headers.get("etag")

    # 越界 → 404
    assert (await client.get(f"/api/catalog/{rid}/img/2")).status_code == 404
    assert (await client.get(f"/api/catalog/{rid}/img/0")).status_code == 404

    # 协商缓存 304
    etag = img.headers["etag"]
    again = await client.get(f"/api/catalog/{rid}/img/1", headers={"If-None-Match": etag})
    assert again.status_code == 304


async def test_manuscript_without_data_uri_is_untouched(
    client: AsyncClient, db_session, admin_user: dict
) -> None:
    md_text = "# 纯文字\n\n没有图片的正文段落。\n"
    rid = await _seed_published_md(client, db_session, admin_user, md_text=md_text)
    resp = await client.get(f"/api/catalog/{rid}/manuscript")
    assert resp.status_code == 200
    assert "没有图片的正文段落。" in resp.text
    assert "/img/" not in resp.text


async def test_img_endpoint_hidden_for_unpublished(
    client: AsyncClient, db_session, admin_user: dict
) -> None:
    md_text = f"# 私密\n\n![x](data:image/png;base64,{_TINY_PNG_B64})\n"
    rid = await _seed_published_md(client, db_session, admin_user, md_text=md_text, status="draft")
    # 匿名访问：manuscript 与 img 同边界
    assert (await client.get(f"/api/catalog/{rid}/manuscript")).status_code == 404
    assert (await client.get(f"/api/catalog/{rid}/img/1")).status_code == 404
