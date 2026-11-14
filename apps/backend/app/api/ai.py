"""AI 投稿接入：个人 API Token + 兼容 MCP 的投稿端点。

设计边界
--------
- 不接受账号密码：用户先登录站点，在「设置 → AI 投稿」创建个人 Token；
  明文只显示一次，数据库只存 SHA-256。
- Token 只有 ``submission:write`` / ``profile:read`` 两个作用域，不能管理
  用户、不能处置举报、不能改他人内容。
- 仍然走网页投稿同一套闸门：确认当版规范、敏感词、站内相似度、
  幂等、每小时 10 篇上限、AuditLog。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_tenant_id
from app.api.levels import CURRENT_RULES_VERSION
from app.core.db import get_db
from app.core.moderation import rejection_detail
from app.core.time import utcnow
from app.domain.submission._helpers import _snapshot_submission
from app.domain.submission.models import Submission
from app.domain.submission.similarity import check_against_site
from app.interfaces.http.submission.responses import _to_response
from app.interfaces.http.submission.schemas import SubmissionCreate, SubmissionResponse
from app.models import ApiToken, AuditLog, User

router = APIRouter(prefix="/ai", tags=["ai"])

_TOKEN_PREFIX = "rbk_"
_MAX_SUBMISSIONS_PER_HOUR = 10
_SCOPES = "submission:write profile:read"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: datetime | None) -> datetime | None:
    """SQLite 读回的时间可能没有 tzinfo；统一成 UTC 再比较。"""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    request_count: int


class TokenCreated(TokenOut):
    token: str


def _token_out(row: ApiToken) -> TokenOut:
    return TokenOut(
        id=row.id,
        name=row.name,
        prefix=row.token_prefix,
        scopes=row.scopes,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        request_count=row.request_count,
    )


def _extract_token(request: Request, x_api_key: str | None) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def get_api_token_identity(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> tuple[User, ApiToken]:
    """解析个人 API Token，返回 (用户, token 记录)。仅接受 rbk_ 前缀。"""
    raw = _extract_token(request, x_api_key)
    if not raw.startswith(_TOKEN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要个人 API Token（设置 → AI 投稿 创建），不接受账号密码",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tenant_id = require_tenant_id()
    now = utcnow()
    token = (
        await db.execute(
            select(ApiToken).where(
                ApiToken.tenant_id == tenant_id,
                ApiToken.token_hash == _hash_token(raw),
                ApiToken.revoked_at.is_(None),
                or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
            )
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效、已撤销或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = (
        await db.execute(
            select(User).where(
                User.id == token.user_id,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="账号已停用")
    if "submission:write" not in (token.scopes or "").split():
        raise HTTPException(status_code=403, detail="Token 没有投稿作用域")
    return user, token


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    """公开的能力说明，MCP 客户端可先读这里再决定如何调用。"""
    return {
        "name": "Rubbish AI Submission API",
        "version": "1.0",
        "auth": {
            "type": "personal_api_token",
            "header": "X-API-Key: rbk_...",
            "create_at": "/settings?tab=ai",
            "note": "不接受账号密码；Token 可撤销、默认 90 天过期。",
        },
        "scopes": _SCOPES.split(),
        "submit_endpoint": "POST /api/ai/submissions",
        "idempotency": "Idempotency-Key 请求头（≤100 字符），重复调用返回同一稿件",
        "rate_limit": f"{_MAX_SUBMISSIONS_PER_HOUR} 篇/小时/Token",
        "moderation": "与网页投稿一致：规范确认、敏感词、站内相似度；命中返回 422",
        "mcp": "仓库 tools/rubbish-mcp 提供 stdio MCP 服务",
    }


@router.get("/tokens", response_model=list[TokenOut])
async def list_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TokenOut]:
    """列出当前用户的 API Token（不含明文与哈希）。"""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(ApiToken)
                .where(
                    ApiToken.tenant_id == tenant_id,
                    ApiToken.user_id == current_user.id,
                )
                .order_by(ApiToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_token_out(r) for r in rows]


@router.post("/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: TokenCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenCreated:
    """创建个人 Token；明文只在本次响应返回，之后只能看到前缀。"""
    tenant_id = require_tenant_id()
    raw = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    now = utcnow()
    row = ApiToken(
        tenant_id=tenant_id,
        user_id=current_user.id,
        name=body.name.strip(),
        token_hash=_hash_token(raw),
        token_prefix=raw[:12],
        scopes=_SCOPES,
        created_at=now,
        expires_at=now + timedelta(days=body.expires_in_days),
    )
    db.add(row)
    await db.flush()
    await db.commit()
    await db.refresh(row)
    return TokenCreated(**_token_out(row).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", response_model=TokenOut)
async def revoke_token(
    token_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """撤销 Token；撤销后立即拒绝，已签发的稿件不受影响。"""
    tenant_id = require_tenant_id()
    row = (
        await db.execute(
            select(ApiToken).where(
                ApiToken.id == token_id,
                ApiToken.tenant_id == tenant_id,
                ApiToken.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Token 不存在")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        await db.commit()
        await db.refresh(row)
    return _token_out(row)


@router.get("/me")
async def token_me(
    identity: tuple[User, ApiToken] = Depends(get_api_token_identity),
) -> dict[str, Any]:
    user, token = identity
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
        },
        "token": {"id": token.id, "name": token.name, "prefix": token.token_prefix},
        "rules_ack_version": user.rules_ack_version,
        "current_rules_version": CURRENT_RULES_VERSION,
    }


@router.get("/submissions")
async def ai_list_submissions(
    status_filter: str | None = None,
    limit: int = 20,
    identity: tuple[User, ApiToken] = Depends(get_api_token_identity),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Token 视角的投稿列表，供 MCP「查进度」使用（最多 50 条）。"""
    user, _token = identity
    tenant_id = require_tenant_id()
    stmt = select(Submission).where(
        Submission.tenant_id == tenant_id, Submission.submitted_by == user.id
    )
    if status_filter:
        stmt = stmt.where(Submission.status == status_filter)
    rows = (
        (await db.execute(stmt.order_by(Submission.id.desc()).limit(min(limit, 50))))
        .scalars()
        .all()
    )
    return {
        "data": [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "source": r.source,
                "similarity_score": r.similarity_score,
                "submitted_at": r.submitted_at,
            }
            for r in rows
        ]
    }


@router.post(
    "/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ai_create_submission(
    body: SubmissionCreate,
    identity: tuple[User, ApiToken] = Depends(get_api_token_identity),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """AI/MCP 投稿。闸门与网页投稿一致，另加 Token 小时窗与幂等。"""
    user, token = identity
    tenant_id = require_tenant_id()
    client_ref = (idempotency_key or "").strip()[:100] or None

    if client_ref:
        existing = (
            await db.execute(
                select(Submission).where(
                    Submission.tenant_id == tenant_id,
                    Submission.submitted_by == user.id,
                    Submission.client_ref == client_ref,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_response(existing)

    if user.rules_ack_version != CURRENT_RULES_VERSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "rules_ack_required",
                "version": CURRENT_RULES_VERSION,
                "message": "请先在站点确认当版《Rubbish 投稿与编辑规范》，再让 AI 投稿。",
                "ack_url": "/settings?tab=profile",
            },
        )

    now = utcnow()
    started = _normalize(token.window_started_at)
    if started is None or now - started >= timedelta(hours=1):
        token.window_started_at = now
        token.window_count = 0
    if token.window_count >= _MAX_SUBMISSIONS_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"该 Token 每小时最多投稿 {_MAX_SUBMISSIONS_PER_HOUR} 篇，请稍后再试",
        )
    token.window_count += 1
    token.request_count = (token.request_count or 0) + 1
    token.last_used_at = now

    blocked = rejection_detail(f"{body.title}\n{body.abstract}")
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=blocked)
    similarity_score, similarity_matches = await check_against_site(
        db,
        tenant_id,
        title=body.title,
        abstract=body.abstract,
    )
    submission = Submission(
        tenant_id=tenant_id,
        submitted_by=user.id,
        status="pending",
        title=body.title,
        type=body.type,
        track=body.track,
        authors=body.authors,
        year=body.year,
        venue=body.venue,
        discipline=body.discipline,
        subdiscipline=body.subdiscipline,
        article_section=body.article_section,
        issue_part=body.issue_part,
        keywords=body.keywords,
        jel_codes=body.jel_codes,
        tags=body.tags,
        abstract=body.abstract,
        preview=body.preview,
        download_url=str(body.download_url) if body.download_url else None,
        external_url=str(body.external_url) if body.external_url else None,
        doi=body.doi,
        corresponding_author_email=body.corresponding_author_email,
        similarity_score=similarity_score,
        similarity_matches=similarity_matches,
        source="ai",
        client_ref=client_ref,
    )
    db.add(submission)
    await db.flush()
    await _snapshot_submission(db, submission, created_by=user.id)
    from app.domain.gamification import service as gamification

    await gamification.award(
        db, user, "submission.create", ref_type="submission", ref_id=str(submission.id)
    )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=user.id,
            action="ai.submission.create",
            target_type="submission",
            target_id=str(submission.id),
            payload={
                "token_id": token.id,
                "client_ref": client_ref,
                "similarity_score": similarity_score,
            },
        )
    )
    await db.commit()
    await db.refresh(submission)
    return _to_response(submission)
