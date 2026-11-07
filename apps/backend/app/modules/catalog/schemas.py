"""Pydantic schemas for the catalog module.

Public read endpoints use ``ResourceResponse``; admin write endpoints
use ``ResourceCreate`` / ``ResourceUpdate``. List responses carry
pagination metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.schemas import Authors, PaginationMeta
from app.core.tracks import (
    Track,
    derive_content_track,
    normalize_track,
)


def _build_authors_detail(
    authors: list[str] | None,
    authors_meta: list[Any] | None,
) -> list[AuthorDetail]:
    """由 authors（字符串列表）+ authors_meta（结构化位）构建对外作者位。

    隐私铁律：未认领（claimed=False）的作者位，email 一律为 None——
    不下发 PDF/Word 解析出的私人邮箱。已认领位的 email 已在批准时
    从账号资料拷入 authors_meta，此处直接透出。
    """
    names = authors or []
    meta = authors_meta or []
    out: list[AuthorDetail] = []
    for i, name in enumerate(names):
        raw = meta[i] if i < len(meta) else {}
        # Pydantic 校验后 entry 可能是 AuthorMeta 对象，统一转 dict。
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        entry = raw if isinstance(raw, dict) else {}
        claimed = bool(entry.get("claimed"))
        roles_raw = entry.get("roles") or (["first"] if i == 0 else [])
        roles = [r for r in roles_raw if r in ("first", "corresponding")]
        out.append(
            AuthorDetail(
                name=name,
                order=i + 1,
                roles=roles,
                claimed=claimed,
                user_id=entry.get("user_id") if claimed else None,
                affiliation=entry.get("affiliation"),
                email=entry.get("email") if claimed else None,
            )
        )
    return out


class AuthorMeta(BaseModel):
    """Per-author enrichment object.

    Parallel to the ``authors`` list (which is the display source of
    truth). ``name`` matches the corresponding entry in ``authors``
    by position; ``orcid`` and ``affiliation`` / ``email`` are
    optional metadata.

    Validation: ``orcid`` is canonicalised by ``app.core.orcid``.
    """

    name: str = Field(min_length=1, max_length=200)
    orcid: str | None = Field(default=None, max_length=20)
    affiliation: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=255)
    # P1：认领状态与角色（公开面由 _build_authors_detail 统一透出）。
    claimed: bool = False
    user_id: int | None = None
    roles: list[str] = Field(default_factory=list)

    @field_validator("orcid")
    @classmethod
    def _canonicalise_orcid(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        from app.core.orcid import is_valid_orcid, normalize_orcid

        if not is_valid_orcid(value):
            raise ValueError(f"Invalid ORCID iD: {value!r}")
        return normalize_orcid(value)


# Resource type enum; may grow per deployment.
ResourceType = Literal["paper", "book", "dataset", "tutorial"]
PublicationStatus = Literal["published", "in_review", "draft"]
# 内容类别（v1.11）：类别不是等级——内容不分等级，层级只与创作者经验
# 挂钩；排行/推荐只允许同类别内容互相比对。
ContentCategory = Literal["academic", "fun", "rant"]


class ResourceBase(BaseModel):
    """Shared fields for create / update / response."""

    type: ResourceType
    # 赛道：历史字段，已下线（见 core/tracks.py）。仅保留 serious 一档，
    # 旧客户端传 absurd 等值由 before-validator 归一为 serious，不 422。
    track: Track = "serious"
    # 内容类别：academic（学术研究）/ fun（娱乐向）/ rant（吐槽向）。
    # 可空：历史数据由迁移 019 回填，新发布由物化流程折算，编辑部可改口。
    content_category: ContentCategory | None = None
    # 中图分类号（P0）：clc_code 如 TP3，clc_label 如「计算技术、计算机技术」。
    # 从稿件 front-matter 解析；非法值原样保留，详情接口 clc_status 标待校正。
    clc_code: str | None = Field(default=None, max_length=20)
    clc_label: str | None = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=1000)
    authors: Authors = Field(min_length=1, max_length=200)
    year: int = Field(ge=-3000, le=2100)
    venue: str | None = Field(default=None, max_length=500)
    discipline: str = Field(min_length=1, max_length=100)
    subdiscipline: str | None = Field(default=None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    abstract: str = Field(min_length=1, max_length=20000)
    # Optional preview; falls back to the first 500 chars of abstract (matches SubmissionCreate).
    preview: str | None = Field(default=None, max_length=5000)
    # download_url / external_url 允许两种形态：
    #   1) http(s) 绝对链接（外部托管）；
    #   2) 以 / 开头的同源相对路径（本地托管的稿件文件，如 /uploads/...）。
    # 其余 scheme（javascript:、data: 等）一律拒绝，避免存入后
    # 被阅读器 iframe 当成可执行内容（存储型 XSS）。
    download_url: str | None = None
    external_url: str | None = None
    doi: str | None = Field(default=None, max_length=200)

    @field_validator("download_url", "external_url")
    @classmethod
    def _safe_url(cls, v: str | None) -> str | None:
        if v is None or v.startswith("/"):
            return v
        parsed = urlparse(v)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return v
        raise ValueError("url 必须以 http(s) 开头，或为 / 开头的同源相对路径")

    @field_validator("track", mode="before")
    @classmethod
    def _normalize_track(cls, v: object) -> object:
        """赛道已下线：任意非 serious 输入（含历史 absurd）归一为 serious。"""
        if v is None:
            return None
        return normalize_track(v) if isinstance(v, str) else v

    # Optional parallel list of author enrichment objects. Must have the same length as ``authors`` (when set), or be empty/null.
    authors_meta: list[AuthorMeta] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _authors_meta_length_matches(self) -> ResourceBase:
        if self.authors_meta is None:
            return self
        # Off-by-one checks: the metadata list is optional and may be
        # shorter (caller only knows ORCID for some authors) but must
        # never claim more entries than the authors list.
        if len(self.authors_meta) > len(self.authors):
            raise ValueError(
                f"authors_meta has {len(self.authors_meta)} entries but "
                f"authors has only {len(self.authors)}"
            )
        return self

    # Journal metadata
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    issn: str | None = Field(default=None, max_length=20)
    isbn: str | None = Field(default=None, max_length=20)
    publisher: str | None = Field(default=None, max_length=500)
    short_container_title: str | None = Field(default=None, max_length=200)
    keywords: list[str] | None = Field(default=None, max_length=50)
    language: str = Field(default="zh", max_length=10)
    publication_status: PublicationStatus = "published"
    # 荒诞指数：编辑部评定（0–10，一位小数），None 表示未评定。
    absurdity_index: float | None = Field(default=None, ge=0, le=10)
    # 质量评分（quality 模块 RQS v2.0）：0–100 与等级 A+/A/B/C/D。
    quality_score: float | None = Field(default=None, ge=0, le=100)
    quality_grade: str | None = Field(default=None, max_length=4)
    quality_breakdown: dict[str, Any] | None = None
    # 封面：主题图相对路径（/assets/covers/xxx.jpg）；为空时前端用生成式封面。
    cover_image: str | None = Field(default=None, max_length=500)
    cover_theme: str | None = Field(default=None, max_length=50)
    # 定时发布：published + 未来时间 = 已排期未上线（公开面不可见）。
    publish_at: datetime | None = None

    @model_validator(mode="after")
    def _fill_preview_from_abstract(self) -> ResourceBase:
        if not self.preview:
            # Fall back to the first 500 chars of abstract; stays under the 5000-char limit.
            self.preview = (self.abstract or "")[:500]
        return self


class ResourceCreate(ResourceBase):
    """Body for POST /catalog/."""

    slug: str | None = Field(default=None, min_length=1, max_length=100)


class ResourceUpdate(BaseModel):
    """Body for PATCH /catalog/{id}. All fields optional."""

    type: ResourceType | None = None
    # 赛道：历史字段，已下线。None = 不修改；非 serious 输入归一为 serious。
    track: Track | None = None
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    # 与 ResourceCreate 用同一个 Authors 注解：PATCH 也必须做逐元素校验
    # （长度 1..200、非空），否则可以写入空串或超长作者名。
    authors: Authors | None = None
    year: int | None = Field(default=None, ge=-3000, le=2100)
    venue: str | None = Field(default=None, max_length=500)
    discipline: str | None = Field(default=None, min_length=1, max_length=100)
    subdiscipline: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=50)
    abstract: str | None = Field(default=None, min_length=1, max_length=20000)
    preview: str | None = Field(default=None, min_length=1, max_length=5000)
    # URL scheme 安全性由 ResourceBase._safe_url 统一校验（http/https 或同源相对路径）。
    download_url: str | None = None
    external_url: str | None = None
    doi: str | None = Field(default=None, max_length=200)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    issn: str | None = Field(default=None, max_length=20)
    isbn: str | None = Field(default=None, max_length=20)
    publisher: str | None = Field(default=None, max_length=500)
    short_container_title: str | None = Field(default=None, max_length=200)
    keywords: list[str] | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, max_length=10)
    publication_status: PublicationStatus | None = None
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    authors_meta: list[AuthorMeta] | None = Field(default=None, max_length=200)
    # 荒诞指数：编辑部评定（0–10，一位小数），None 表示未评定。
    absurdity_index: float | None = Field(default=None, ge=0, le=10)
    # 质量评分与封面（编辑可修正评分；评分口径见 /api/quality/rubric）。
    quality_score: float | None = Field(default=None, ge=0, le=100)
    quality_grade: str | None = Field(default=None, max_length=4)
    quality_breakdown: dict[str, Any] | None = None
    cover_image: str | None = Field(default=None, max_length=500)
    cover_theme: str | None = Field(default=None, max_length=50)
    publish_at: datetime | None = None

    @field_validator("track", mode="before")
    @classmethod
    def _normalize_track(cls, v: object) -> object:
        """赛道已下线：非 serious 输入（含历史 absurd）归一为 serious。"""
        if v is None:
            return None
        return normalize_track(v) if isinstance(v, str) else v


class AuthorDetail(BaseModel):
    """P1 对外作者位：含认领状态与归属。

    未认领（claimed=false）的作者位，user_id / affiliation / email 一律为 null，
    不下发 PDF/Word 解析出的私人邮箱。已认领位的 email 取自账号资料。
    """

    name: str
    order: int
    roles: list[str] = Field(default_factory=list)  # ["first","corresponding"]
    claimed: bool = False
    user_id: int | None = None
    affiliation: str | None = None
    email: str | None = None


class ResourceResponse(ResourceBase):
    """Response body for read endpoints.

    ``has_file`` is filled only by the detail endpoint (list responses keep
    the default false): it drives the "下载 PDF" action without forcing the
    browser to probe a 404 for records that were imported without a file.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str | None = None
    created_at: datetime
    updated_at: datetime
    has_file: bool = False
    # 是否有在线阅读用 Markdown 稿件（列表与详情都返回）
    has_markdown: bool = False
    # 内容赛道派生值（P0）：paper|essay。DB 值缺失时按 content_category 回退。
    content_track: str | None = None
    # 中图分类号校正状态：valid / needs_correction / absent（由 clc_code 反推）。
    clc_status: str | None = None
    # 互动指标（R 指数）：列表与详情都返回，未取到时为 None
    reads: int | None = None
    downloads: int | None = None
    saves: int | None = None
    r_index: float | None = None
    quartile: str | None = None
    # absurdity_index 继承自 ResourceBase（编辑部评定，0–10，可空）。
    # P1：作者位明细（含认领状态）。未认领位 email 强制 null。
    authors_detail: list[AuthorDetail] | None = None

    @model_validator(mode="after")
    def _derive_derived_fields(self) -> "ResourceResponse":
        """content_track 按 content_category 回退派生；clc_status 由 clc_code 反推。

        P0 收口：娱乐稿（content_track=essay）不下发任何学术评分字段——
        absurdity_index / quality_score / quality_grade 一律置 null，
        学术稿（paper）保持原值。
        P1：构建 authors_detail；未认领作者位 email 一律 null（隐私）。
        """
        from app.modules.submission.clc import clc_status_of

        self.content_track = derive_content_track(self.content_category, self.content_track)
        self.clc_status = clc_status_of(self.clc_code)
        if self.content_track == "essay":
            self.absurdity_index = None
            self.quality_score = None
            self.quality_grade = None
        self.authors_detail = _build_authors_detail(self.authors, self.authors_meta)
        return self


class ResourceListResponse(BaseModel):
    data: list[ResourceResponse]
    meta: PaginationMeta


class IssueSummary(BaseModel):
    issue: str
    article_count: int
    first_year: int | None = None
    last_year: int | None = None


class VolumeSummary(BaseModel):
    """一卷的汇总（期数、文章数）。

    为什么不复用列表接口：列表单页上限 100，管理端的卷统计需要的是
    **全量**聚合。前端拿一页数据自己数，期刊一过 100 篇就会显示
    「100 篇」，并附一句「数字可能偏小」——那是把后端的活推给用户看。
    """

    volume: str
    issue_count: int
    article_count: int
    issues: list[IssueSummary] = []


class VolumeSummaryList(BaseModel):
    data: list[VolumeSummary]


class ResourceStats(BaseModel):
    total: int
    by_type: dict[str, int]
    by_discipline: dict[str, int]
    # by_track 已随赛道下线移除：文章气质由 absurdity_index 表达，
    # 不再按赛道分组统计。
    downloads_total: int = 0
    reads_total: int = 0


class JournalMetrics(BaseModel):
    """Public journal-level metrics (``GET /api/catalog/journal-metrics``).

    Everything here is computed from the platform's own event tables.
    Fields that need a minimum sample (acceptance rate, review turnaround)
    are Optional: ``None`` means "not enough data yet", which the UI must
    render as such instead of showing 0.

    口径说明刻意不进响应：公式与权重是编辑部的内部口径，页面上只呈现
    数值与含义，不呈现算法（改自 0.5.0，此前暴露 r_index_formula）。
    """

    published_total: int
    by_type: dict[str, int]
    by_discipline: dict[str, int]
    discipline_count: int
    downloads_total: int
    reads_total: int
    saves_total: int
    decided_submissions: int
    accepted_submissions: int
    acceptance_rate: float | None = None
    avg_review_days: float | None = None
    median_review_days: float | None = None
    open_access_rate: float | None = None
    # R 因子：全刊已发表记录 R 指数的均值（保留两位小数）——本刊自设计
    # 的旗舰指标，角色类似传统影响因子，但口径不公开。
    r_factor: float | None = None
    # 无引文数据，自引率恒为 0.0（诚实标注，页面上作为固定项展示）。
    self_citation_rate: float = 0.0


class FacetBucket(BaseModel):
    value: str
    count: int


class ResourceFacets(BaseModel):
    years: list[FacetBucket]
    tags: list[FacetBucket]


__all__ = [
    "AuthorMeta",
    "FacetBucket",
    "JournalMetrics",
    "PaginationMeta",
    "PublicationStatus",
    "ResourceBase",
    "ResourceCreate",
    "ResourceFacets",
    "ResourceListResponse",
    "ResourceResponse",
    "ResourceStats",
    "IssueSummary",
    "VolumeSummary",
    "VolumeSummaryList",
    "ResourceType",
    "ResourceUpdate",
]
