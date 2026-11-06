"""SQLAlchemy models for the catalog module.

All tables are tenant-scoped with RLS:

- ``resources`` — core bibliographic record (title, authors, year, venue,
  discipline, tags, abstract, DOI, journal metadata). No view/download
  counters: the promised tracking endpoints were never built, so the
  half-finished ``resource_stats`` table was dropped in migration 021.

The optional ``Author`` table for ORCID/affiliation enrichment is
reserved for a future phase; the primary author storage is the JSON
``authors`` column on ``resources``.

All catalog models inherit from the core ``Base`` so cross-module FKs
(e.g. ``resources.tenant_id → tenants.id``) resolve without metadata
gymnastics. This matches ARCHITECTURE.md "All modules share the
tenant's PostgreSQL database".
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models import Base, JSONBVariant, TenantScopedMixin


class Resource(Base, TenantScopedMixin):
    """A catalog record (paper / book / dataset / tutorial / ...).

    The ``slug`` is an optional stable URL identifier. When absent, the
    frontend uses the integer id. ``authors`` is the primary author
    storage (JSON list[str]); structured author entities with ORCID etc.
    are a future concern (reserved ``Author`` table).
    """

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Optional stable URL slug. Unique per tenant; null allowed for records
    # imported without a slug (frontend falls back to int id).
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Primary author storage. JSON list[str], e.g. ["Alice Author", "Bob"].
    authors: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    discipline: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subdiscipline: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    tags: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 同一 DOI 不得落到两个资源上（可空；Postgres 唯一索引允许多个 NULL）。
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True, unique=True)

    # Optional per-author enrichment (e.g. ORCID iDs). Stored as a
    # JSON list parallel to ``authors``: each entry has at least a
    # ``name`` field, optionally ``orcid``, ``affiliation``,
    # ``email``. The ``authors`` column stays the source of truth for
    # display; this column enriches it for academic citation needs.
    # Format:
    #   [{"name": "Alice Author", "orcid": "0000-0002-1825-0097", ...}]
    authors_meta: Mapped[list[dict[str, str]] | None] = mapped_column(JSON, nullable=True)
    # Journal metadata (Phase 1)
    volume: Mapped[str | None] = mapped_column(String(50), nullable=True)
    issue: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pages: Mapped[str | None] = mapped_column(String(50), nullable=True)
    issn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    short_container_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(JSONBVariant, nullable=True)
    # 本站是中文期刊：默认 zh 而不是 en。稿件的语言在目录条目上维护，
    # 因为 submission 模型没有 language 列（物化时沿用这里的中文默认值）。
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    publication_status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    # 定时发布：published 但 publish_at 在未来 = 已排期、尚未对公众可见。
    # 编辑部把整期排在月初，到点自动上线（判定见 catalog/visibility.py）。
    # 单列索引不需要：公开面过滤永远是 (tenant_id, publish_at) 组合，
    # 复合索引已覆盖；多余的 index=True 会让 alembic metadata 与迁移漂移。
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 下载计数：公开 /api/catalog/{id}/file 每次命中 +1，用于 R 指数
    # （见 app/modules/catalog/engagement.py）。只做原子自增，不做行锁。
    download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # 荒诞指数：编辑部对单篇内容离谱程度的评定（0–10，一位小数）。
    # 与 R 指数（读者注意力）相互独立；可空——正经论文可以不评定。
    absurdity_index: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    # 赛道：历史字段，已下线（见 core/tracks.py）。serious / absurd 双赛道
    # 已由每篇论文的荒诞指数（absurdity_index）取代，为兼容历史数据保留
    # 本列，新写入恒为 serious。复合索引见迁移 013
    # （(tenant_id, track, publication_status)），单列 index=True 会让公开面
    # 列表多一次回表。
    track: Mapped[str] = mapped_column(
        String(16), nullable=False, default="serious", server_default="serious"
    )
    # --- 质量评分（quality 模块 RQS v2.0，冻结口径） ---
    # 0–100；grade = A+/A/B/C/D；breakdown 存各维度得分明细（可复现）。
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    quality_grade: Mapped[str | None] = mapped_column(String(4), nullable=True)
    quality_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 封面：主题图本地化的相对路径（/assets/covers/xxx.jpg）。
    # 为空时前端回退到生成的纸面卡（CoverArt），不会出现破图。
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 内容类别（v1.11）：编辑部评定的一等公民属性——academic（学术研究）/
    # fun（娱乐向）/ rant（吐槽向）。这是「类别」而不是「等级」：内容不分
    # 等级，层级只与创作者经验挂钩；同类别内容才能互相比对（排行/推荐
    # 均按本字段分域）。发布时必填（无值由发布流程按荒诞指数折算回填）。
    content_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 归类键：封面主题、专题聚合使用（如 universe / lab / ocean / society）。
    cover_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    # __table_args__ 放在类体末尾：其中的 created_at.desc() 需要引用
    # 上面已定义的 created_at 列对象（类体自上而下求值）。
    #
    # ↓ 以下 4 个索引与 020_performance_indexes 迁移一一对应。
    # 该迁移用 raw DDL 建索引，DB 里有而 ORM metadata 没有，alembic
    # check 会判 "Detected removed index"（CI migrations job 因此挂）。
    # 在模型侧声明同名同形的索引让 metadata 与迁移后 schema 一致。
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_resources_tenant_slug"),
        Index(
            "ix_resources_tenant_created",
            "tenant_id",
            created_at.desc(),
        ),
        Index(
            "ix_resources_tenant_type_created",
            "tenant_id",
            "type",
            created_at.desc(),
        ),
        # GIN trigram（pg_trgm）索引：PG 专属，SQLite 下 create_all 忽略
        # using/ops 参数，仅退化为普通索引（无害）。
        Index("ix_resources_tenant_publish_at", "tenant_id", "publish_at"),
        Index(
            "ix_resources_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_resources_abstract_trgm",
            "abstract",
            postgresql_using="gin",
            postgresql_ops={"abstract": "gin_trgm_ops"},
        ),
    )


class Discipline(Base, TenantScopedMixin):
    """学科本体表。供分类一致性校验和统计聚合使用。

    A controlled vocabulary of academic disciplines. Resources
    reference these by string name (we keep the historical column
    shape rather than introducing a hard FK, so legacy data
    ingested before this table existed still loads cleanly). New
    resources are validated against the table on create/update
    by ``app.modules.catalog.onto``.

    Each discipline may have zero or more ``Subdiscipline`` rows.
    """

    __tablename__ = "disciplines"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_disciplines_tenant_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # URL slug (lower-case, hyphenated). Unique per tenant.
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    # Display name (e.g. "Computer Science").
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Short description for the directory UI.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    subdisciplines: Mapped[list[Subdiscipline]] = relationship(
        back_populates="discipline", cascade="all, delete-orphan"
    )


class Subdiscipline(Base, TenantScopedMixin):
    """学科下的子领域。Resource.subdiscipline 是字符串，但需校验
    该字符串存在于此表中（按学科过滤）。"""

    __tablename__ = "subdisciplines"
    __table_args__ = (
        UniqueConstraint("discipline_id", "slug", name="uq_subdisciplines_discipline_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discipline_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("disciplines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    discipline: Mapped[Discipline] = relationship(back_populates="subdisciplines")


class AuthorClaim(Base, TenantScopedMixin):
    """作者认领申请：站内用户认领一篇"无人认领"的存量文章。

    背景：本刊早期文章由编辑部批量导入（authors 是纯字符串数组，
    与站内账号无关）。作者想在站内名下挂上自己的文章，需要走认领
    流程：用户对资源发起认领 → 编辑部批准后自动创建一条关联投稿
    （``submissions.submitted_by`` = 认领人），从此"我的文章"、
    录用数统计、刊前预览等一切基于 Submission 链路的功能都能生效。

    状态机：``pending`` → ``approved`` | ``rejected``（终态）。
    同一 (tenant, resource, user) 只允许一条申请（唯一约束）；
    同一资源同一时刻只允许一条 pending（由服务层校验）。
    """

    __tablename__ = "author_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "resource_id", "user_id", name="uq_author_claims_once"),
        Index("ix_author_claims_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 认领说明（申请人填写，如"我是本文作者"）。
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # 编辑部决定说明（批准/拒绝理由，通知里带给申请人）。
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["AuthorClaim", "Discipline", "Resource", "Subdiscipline"]
