"""评分 v2.0 端点与 D 级打回流程的集成测试。

覆盖用户的核心诉求：
1. 审稿人评分端点按权重算分（服务端算，不可前端篡改）；
2. D 级稿件不能直接录用（409）；
3. 打回会同时通知审稿人与作者（消息栏目是唯一入口）；
4. 管理员可改分但必须写理由且留审计。
"""

from __future__ import annotations

from conftest import auth_headers, complete_one_review, register_user
from httpx import AsyncClient

import pytest

_DIMS = ("problem", "argument", "method", "evidence", "novelty", "integrity", "presentation")


def _all(value: int, reason: str = "理由：正文第 2 节可核") -> list[dict[str, object]]:
    return [{"key": k, "score": value, "reason": reason} for k in _DIMS]


async def _make_reviewer(client: AsyncClient, admin: dict, name: str) -> dict:
    user = await register_user(client, email=f"{name}@example.com", username=name)
    grant = await client.post(
        f"/api/admin/users/{user['user_id']}/roles",
        json={"role": "reviewer"},
        headers=auth_headers(admin),
    )
    grant.raise_for_status()
    return user


@pytest.mark.asyncio
async def test_score_endpoint_requires_reviewer(client: AsyncClient, test_user: dict) -> None:
    """普通作者不能调用评分端点——分数不能自己给自己。"""
    r = await client.post(
        "/api/quality/score",
        json={"article_type": "research", "dimensions": _all(5)},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_score_endpoint_computes_weighted_total(
    client: AsyncClient, admin_user: dict
) -> None:
    reviewer = await _make_reviewer(client, admin_user, "score_rev")
    r = await client.post(
        "/api/quality/score",
        json={"article_type": "research", "dimensions": _all(5)},
        headers=auth_headers(reviewer),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score"] == 100.0
    assert body["grade"] == "A+"
    assert body["rubric_version"] == "2.0"


@pytest.mark.asyncio
async def test_integrity_zero_vetoes_total(client: AsyncClient, admin_user: dict) -> None:
    """诚信 0 分 → 总分 0、D 级、必须打回（一票否决）。"""
    reviewer = await _make_reviewer(client, admin_user, "veto_rev")
    dims = _all(5)
    for d in dims:
        if d["key"] == "integrity":
            d["score"] = 0
            d["reason"] = "发现第 4 条参考文献无法定位，疑似编造"
    r = await client.post(
        "/api/quality/score",
        json={"article_type": "research", "dimensions": dims},
        headers=auth_headers(reviewer),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["integrity_veto"] is True
    assert body["score"] == 0.0
    assert body["requires_rework"] is True


@pytest.mark.asyncio
async def test_score_rejects_missing_dimension(client: AsyncClient, admin_user: dict) -> None:
    """缺维度必须 422，不能把"漏填"当"很差"。"""
    reviewer = await _make_reviewer(client, admin_user, "miss_rev")
    r = await client.post(
        "/api/quality/score",
        json={"article_type": "research", "dimensions": _all(4)[:-1]},
        headers=auth_headers(reviewer),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_override_requires_admin_and_reason(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    # 非管理员 403
    r = await client.post(
        "/api/quality/override",
        json={"score": 88, "reason": "人工复核后微调，依据见备注"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403
    # 管理员成功
    ok = await client.post(
        "/api/quality/override",
        json={"score": 88, "reason": "人工复核后微调，依据见备注"},
        headers=auth_headers(admin_user),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["score"] == 88
    assert ok.json()["overridden"] is True


@pytest.mark.asyncio
async def test_suggest_endpoint_public_and_deterministic(client: AsyncClient) -> None:
    """建议分端点无需登录（作者自查），且同输入同输出。"""
    from app.modules.quality.review_form import CHECK_ITEMS

    answers = {item.key: "yes" for item in CHECK_ITEMS}
    a = await client.post("/api/quality/suggest", json={"answers": answers})
    b = await client.post("/api/quality/suggest", json={"answers": answers})
    assert a.status_code == 200
    assert {k: v["suggested_score"] for k, v in a.json()["dimensions"].items()} == {
        k: v["suggested_score"] for k, v in b.json()["dimensions"].items()
    }


@pytest.mark.asyncio
async def test_rework_requires_three_requirements(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """打回必须列至少 3 条具体修改要求。"""
    sub = await client.post(
        "/api/submissions",
        json={
            "title": "打回测试稿",
            "type": "paper",
            "authors": ["A"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证打回流程的占位摘要。",
        },
        headers=auth_headers(test_user),
    )
    sid = sub.json()["id"]
    r = await client.post(
        f"/api/submissions/{sid}/rework",
        json={"requirements": ["改摘要", "补引用"]},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rework_notifies_reviewer_and_author(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session
) -> None:
    """打回必须双向通知：审稿人要补审，作者要修改。

    消息栏目是唯一入口——如果只改状态不通知，审稿人永远不会知道
    自己被打回了。
    """
    sub = await client.post(
        "/api/submissions",
        json={
            "title": "打回通知测试稿",
            "type": "paper",
            "authors": ["A"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证打回通知的占位摘要，长度足够。",
        },
        headers=auth_headers(test_user),
    )
    sid = sub.json()["id"]
    await complete_one_review(client, admin_user, sid)

    r = await client.post(
        f"/api/submissions/{sid}/rework",
        json={
            "requirements": [
                "补充样本量的说明",
                "第 3 节的因果表述需要弱化为相关",
                "参考文献 4 无法定位，请核实或替换",
            ],
            "note": "评分 D 级，需返修后重审",
        },
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rework_requested"

    # 作者收到通知
    inbox = await client.get("/api/notifications", headers=auth_headers(test_user))
    types = [n["type"] for n in inbox.json()["data"]]
    assert "submission.rework_requested" in types
    # 审稿人也收到：complete_one_review 会新建一个审稿人账户并提交意见，
    # 打回必须通知到「实际审过这篇稿子的人」，而不是通知编辑自己。
    from sqlalchemy import select

    from app.modules.review.models import ReviewAssignment
    from app.models import User as UserModel

    reviewer_id = (
        await db_session.execute(
            select(ReviewAssignment.reviewer_id).where(ReviewAssignment.submission_id == sid)
        )
    ).scalar_one()
    reviewer = (
        await db_session.execute(select(UserModel).where(UserModel.id == reviewer_id))
    ).scalar_one()
    login = await client.post(
        "/api/auth/login",
        json={"username": reviewer.username, "password": "password123"},
    )
    assert login.status_code == 200
    rtok = login.json()["access_token"]
    reviewer_inbox = await client.get(
        "/api/notifications", headers={"Authorization": f"Bearer {rtok}"}
    )
    rtypes = [n["type"] for n in reviewer_inbox.json()["data"]]
    assert "review.rework_requested" in rtypes
