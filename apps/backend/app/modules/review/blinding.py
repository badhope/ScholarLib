"""Review blinding policy — single-blind (default) or double-blind.

Terminology (COPE / ICMJE 通行定义):

- **single-blind**（默认）：审稿人知道作者是谁，作者不知道审稿人是谁。
- **double-blind**：双方互不知情——审稿人也看不到作者姓名、单位、
  通讯邮箱等可识别信息。

作者侧的剥离（作者看不到审稿人身份）在两种模式下都生效，本模块只
额外处理 double-blind 特有的「审稿人侧剥离」。

模式存放在 ``Tenant.settings["review_mode"]``，无需 schema 迁移；
未设置时按 single-blind 处理（向后兼容既有部署）。
"""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant

ReviewMode = Literal["single_blind", "double_blind"]

DEFAULT_REVIEW_MODE: ReviewMode = "single_blind"
VALID_REVIEW_MODES: frozenset[str] = frozenset({"single_blind", "double_blind"})

# 双盲下对审稿人隐藏的占位文案。用可读占位而不是 None，让审稿人
# 明确知道「这里被刻意隐藏了」，而不是误以为作者没填。
ANONYMIZED_AUTHOR = "[双盲评审：作者信息已隐藏]"

# 审稿人视角**允许看到**的字段白名单。
#
# 为什么改成白名单：早期实现是黑名单（枚举要抹掉的字段），结果
# ``admin_note`` / ``editor_note`` / ``reviewed_by`` 三个字段漏网——
# 编辑写下的内部备注（"该作者组近期多篇灌水""第三轮仍未按意见修改"）
# 原样出现在审稿人面前。这类备注经常直接点名作者单位，等于一条穿过
# 双盲的侧信道，而且是"编辑主动写、审稿人意外看到"的形态，比正文
# 残留更难被发现。
#
# 白名单的代价是新增字段必须显式登记才会被审稿人看到——这个方向是
# 对的：漏放一个字段只是少看到点信息，漏抹一个字段是破盲。
REVIEWER_VISIBLE_FIELDS: frozenset[str] = frozenset(
    {
        # 学术内容（评审真正需要的东西）
        "id",
        "title",
        "type",
        "track",
        "year",
        "discipline",
        "subdiscipline",
        "keywords",
        "jel_codes",
        "tags",
        "abstract",
        "preview",
        "status",
        "submitted_at",
        "resource_id",
        # 编辑提供的匿名稿（由编辑端点写入，不含作者身份）
        "anonymized_file_url",
        "file_path",
        # 单盲模式下同样可见、双盲下被抹掉（值置空而非删键，保持响应形状稳定）
        "authors",
        "venue",
        "doi",
        "download_url",
        "external_url",
        "corresponding_author_email",
        "submitted_by",
        # 编辑侧工作流字段：审稿人不需要，双盲下置空
        "admin_note",
        "editor_note",
        "reviewed_by",
        "reviewed_at",
    }
)

# 双盲下即使出现在白名单里也必须抹空的字段（值置空，不删键）。
_DOUBLE_BLIND_SCRUB: dict[str, Any] = {
    "authors": [ANONYMIZED_AUTHOR],
    "corresponding_author_email": None,
    "submitted_by": None,
    "venue": None,
    "doi": None,
    "download_url": None,
    "external_url": None,
    # 编辑内部备注：编辑↔作者或编辑↔编辑的私密沟通，双盲下绝不能
    # 出现在审稿人面前（见上面白名单注释里的破盲场景）。
    "admin_note": None,
    "editor_note": None,
    "reviewed_by": None,
    "reviewed_at": None,
}


async def get_review_mode(db: AsyncSession, tenant_id: UUID) -> ReviewMode:
    """Read the tenant's review mode; falls back to single-blind."""
    settings_blob = (
        await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not isinstance(settings_blob, dict):
        return DEFAULT_REVIEW_MODE
    mode = settings_blob.get("review_mode")
    if mode in VALID_REVIEW_MODES:
        return cast(ReviewMode, mode)
    return DEFAULT_REVIEW_MODE


async def set_review_mode(db: AsyncSession, tenant_id: UUID, mode: ReviewMode) -> None:
    """Persist the tenant's review mode (merged into the settings blob)."""
    if mode not in VALID_REVIEW_MODES:
        raise ValueError(f"Invalid review mode: {mode}")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise LookupError("Tenant not found")
    # JSON 列必须整体替换，原地改 dict 不会被 SQLAlchemy 识别为脏数据。
    merged: dict[str, Any] = dict(tenant.settings or {})
    merged["review_mode"] = mode
    tenant.settings = merged


def reviewer_facing_payload(payload: dict[str, Any], *, double_blind: bool) -> dict[str, Any]:
    """审稿人视角的稿件字段：始终按白名单裁剪，双盲时再抹身份。

    两种模式都要裁：``admin_note`` / ``editor_note`` 是编辑侧的内部沟通，
    单盲下审稿人同样不该看到（单盲只意味着"审稿人知道作者"，不意味着
    "审稿人知道编辑的内部评语"）。早期实现只在双盲时处理，导致单盲
    部署里编辑备注一直是对审稿人可见的。
    """
    scrubbed = {k: v for k, v in payload.items() if k in REVIEWER_VISIBLE_FIELDS}
    # 编辑侧工作流字段在任何盲法下都不给审稿人。
    for field in ("admin_note", "editor_note", "reviewed_by", "reviewed_at"):
        if field in scrubbed:
            scrubbed[field] = None
    if double_blind:
        for field, value in _DOUBLE_BLIND_SCRUB.items():
            if field in scrubbed:
                scrubbed[field] = value
    return scrubbed


def anonymize_submission_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip author-identifying fields from a submission payload.

    Applied to the reviewer-facing view under double-blind. Returns a new
    dict; the caller's data is not mutated.

    实现方式：先按 ``REVIEWER_VISIBLE_FIELDS`` 白名单裁掉一切未登记的
    字段，再对 ``_DOUBLE_BLIND_SCRUB`` 里的字段置空。两步都必要——
    白名单防止新字段默认泄漏，置空表保证已登记的字段在双盲下确实为空。

    历史教训：早期是纯黑名单，``admin_note`` / ``editor_note`` /
    ``reviewed_by`` 三个字段从未被抹，编辑的内部评语（常含作者单位）
    直接送到审稿人面前，构成穿过双盲的侧信道。
    """
    scrubbed = {k: v for k, v in payload.items() if k in REVIEWER_VISIBLE_FIELDS}
    for field, value in _DOUBLE_BLIND_SCRUB.items():
        if field in scrubbed:
            scrubbed[field] = value
    return scrubbed
