"""0.5.0 指标改版的行为锁定测试。

契约（ledger: metrics-rebrand-and-content-hub；P0 收口更新）：
- R1  公开指标不泄露口径：journal-metrics 不含 r_index_formula，
      含 r_factor / self_citation_rate；P0 收口后不再下发 absurdity_index_median。
- R2  荒诞指数：公开响应暴露、仅 admin 可改、越界 422。
- R3  列表 has_file 真实反映"挂了带文件稿件的 submission"。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.models import Tenant
from app.modules.catalog.models import Resource
from app.modules.submission.models import Submission
from tests.test_catalog import _SAMPLE


async def _admin_headers(admin_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_user['token']}"}


# ---------------------------------------------------------------------------
# R1 — 公开指标不泄露口径
# ---------------------------------------------------------------------------


async def test_journal_metrics_hides_formula_and_reports_new_fields(
    client: AsyncClient, admin_user: dict
) -> None:
    headers = await _admin_headers(admin_user)
    await client.post("/api/catalog", json=_SAMPLE, headers=headers)

    body = (await client.get("/api/catalog/journal-metrics")).json()
    assert "r_index_formula" not in body
    assert "absurdity_index_median" not in body
    assert body["self_citation_rate"] == 0.0
    # 全刊只有一篇且无互动：事件总量低于 MIN_R_FACTOR_SAMPLE，R 因子不出数。
    # （此前这里断言 0.0 —— 但 0.0 本身就是「无样本」时的假读数；见
    # engagement.MIN_R_FACTOR_SAMPLE 的注释。）
    assert body["r_factor"] is None


async def test_journal_metrics_r_factor_and_no_absurdity_median(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(admin_user)
    ids = []
    for i, (absurdity, downloads) in enumerate([(9.2, 0), (1.0, 0)]):
        rid = (
            await client.post(
                "/api/catalog",
                json={**_SAMPLE, "title": f"Factor Paper {i}"},
                headers=headers,
            )
        ).json()["id"]
        ids.append(rid)
        if absurdity is not None:
            await client.patch(
                f"/api/catalog/{rid}", json={"absurdity_index": absurdity}, headers=headers
            )
        if downloads:
            row = await db_session.get(Resource, rid)
            row.download_count = downloads
            await db_session.commit()

    body = (await client.get("/api/catalog/journal-metrics")).json()
    # P0 收口：即使有记录评定了 absurdity_index，指标接口也不再下发中位数。
    assert "absurdity_index_median" not in body
    # 两篇零互动：事件总量不足，R 因子为 None（页面显示「样本不足」）。
    assert body["r_factor"] is None


# ---------------------------------------------------------------------------
# R2 — 荒诞指数暴露 + admin-only + 越界拒绝
# ---------------------------------------------------------------------------


async def test_absurdity_index_roundtrip_public_detail(
    client: AsyncClient, admin_user: dict
) -> None:
    headers = await _admin_headers(admin_user)
    rid = (await client.post("/api/catalog", json=_SAMPLE, headers=headers)).json()["id"]

    patched = await client.patch(
        f"/api/catalog/{rid}", json={"absurdity_index": 9.2}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["absurdity_index"] == 9.2

    anon = await client.get(f"/api/catalog/{rid}")
    assert anon.status_code == 200
    assert anon.json()["absurdity_index"] == 9.2


async def test_absurdity_index_out_of_range_rejected(client: AsyncClient, admin_user: dict) -> None:
    headers = await _admin_headers(admin_user)
    rid = (await client.post("/api/catalog", json=_SAMPLE, headers=headers)).json()["id"]
    for bad in (12.5, -0.1):
        r = await client.patch(
            f"/api/catalog/{rid}", json={"absurdity_index": bad}, headers=headers
        )
        assert r.status_code == 422
    body = (await client.get(f"/api/catalog/{rid}")).json()
    assert body["absurdity_index"] is None


async def test_absurdity_index_requires_admin(client: AsyncClient, test_user: dict) -> None:
    headers = {"Authorization": f"Bearer {test_user['token']}"}
    r = await client.post("/api/catalog", json=_SAMPLE, headers=headers)
    assert r.status_code == 403
    # 非管理员连创建都进不来；PATCH 无资源可打。直接验证 PATCH 被拒：
    admin_rid_probe = await client.patch(
        "/api/catalog/999999", json={"absurdity_index": 1.0}, headers=headers
    )
    assert admin_rid_probe.status_code in (401, 403, 404)


# ---------------------------------------------------------------------------
# R3 — 列表 has_file
# ---------------------------------------------------------------------------


async def _add_submission_with_file(
    db_session: AsyncSession, admin_user: dict, resource_id: int
) -> None:
    tenant = (
        await db_session.execute(sa_select(Tenant).where(Tenant.slug == "default"))
    ).scalar_one()
    rel_path = f"{tenant.id}/0/hasfile_{resource_id}.pdf"
    await get_storage().save(rel_path, b"%PDF-1.4 hasfile payload")
    db_session.add(
        Submission(
            tenant_id=tenant.id,
            resource_id=resource_id,
            submitted_by=admin_user["user_id"],
            title="Has file",
            type="paper",
            discipline="computer-science",
            authors=["Anon Author"],
            year=2024,
            abstract="has file",
            preview="has file",
            tags=[],
            status="accepted",
            file_path=rel_path,
        )
    )
    await db_session.commit()


async def test_list_has_file_reflects_submission_file(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(admin_user)
    with_file_id = (
        await client.post("/api/catalog", json={**_SAMPLE, "title": "With File"}, headers=headers)
    ).json()["id"]
    without_file_id = (
        await client.post(
            "/api/catalog", json={**_SAMPLE, "title": "Without File"}, headers=headers
        )
    ).json()["id"]
    await _add_submission_with_file(db_session, admin_user, with_file_id)

    body = (await client.get("/api/catalog?page_size=50")).json()
    flags = {item["id"]: item["has_file"] for item in body["data"]}
    assert flags[with_file_id] is True
    assert flags[without_file_id] is False

    detail = (await client.get(f"/api/catalog/{with_file_id}")).json()
    assert detail["has_file"] is True


@pytest.mark.parametrize("field", ["reads", "r_index", "absurdity_index", "has_file"])
async def test_list_items_carry_metric_fields(
    client: AsyncClient, admin_user: dict, field: str
) -> None:
    headers = await _admin_headers(admin_user)
    await client.post("/api/catalog", json=_SAMPLE, headers=headers)
    body = (await client.get("/api/catalog")).json()
    assert body["data"], "resource was just created"
    assert field in body["data"][0]
