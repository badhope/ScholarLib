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
    normalize_track,
    resolve_category,
    resolve_content_track,
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
# 娱乐轨文体（v1.16）：只对 content_track=essay 有意义，论文轨恒为 NULL。
EssayGenre = Literal["joke", "fiction", "review", "guide", "essay", "poetry", "rant"]


class ResourceBase(BaseModel):
    """Shared fields for create / update / response."""

    type: ResourceType
    # 论文子类型：serious=学术论文 / absurd=荒诞论文；副刊不使用该字段。
    # 旧客户端传 absurd 会保留，不再静默归一为 serious。
    track: Track = "serious"
    # 内容类别：academic（学术研究）/ fun（娱乐向）/ rant（吐槽向）。
    # 子类型标签——由 content_track 权威推导（paper→academic，essay→fun/rant），
    # 写入统一走 core.tracks.canonicalize_track_category，见 ResourceResponse 校正。
    content_category: ContentCategory | None = None
    # 内容赛道（唯一权威）：paper=学术研究（进 R 因子/篇均指标），
    # essay=娱乐/吐槽。缺省按 paper（本刊默认学术刊）。
    content_track: Literal["paper", "essay"] | None = None
    # 娱乐轨文体细分（v1.16）：小说/评论/指南/整活…；论文轨不填。
    content_genre: EssayGenre | None = None
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
        """论文子类型只接受 serious / absurd；脏值保守归 serious。"""
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
    # Nature 式栏目 / 期次分部分（021）
    article_section: str | None = Field(default=None, max_length=40)
    issue_part: str | None = Field(default=None, max_length=40)
    pages: str | None = Field(default=None, max_length=50)
    issn: str | None = Field(default=None, max_length=20)
    isbn: str | None = Field(default=None, max_length=20)
    publisher: str | None = Field(default=None, max_length=500)
    short_container_title: str | None = Field(default=None, max_length=200)
    keywords: list[str] | None = Field(default=None, max_length=50)
    language: str = Field(default="zh", max_length=10)
    publication_status: PublicationStatus = "published"
    # 质量评分（quality 模块 RQS v2.0）：0–100 与等级 A+/A/B/C/D。
    quality_score: float | None = Field(default=None, ge=0, le=100)
    quality_grade: str | None = Field(default=None, max_length=4)
    quality_breakdown: dict[str, Any] | None = None
    # 荒诞指数：0–10 风格坐标，不进质量分、不参与排序。
    absurdity_index: float | None = Field(default=None, ge=0, le=10)
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
    # 质量评分与封面（编辑可修正评分；评分口径见 /api/quality/rubric）。
    quality_score: float | None = Field(default=None, ge=0, le=100)
    quality_grade: str | None = Field(default=None, max_length=4)
    quality_breakdown: dict[str, Any] | None = None
    absurdity_index: float | None = Field(default=None, ge=0, le=10)
    cover_image: str | None = Field(default=None, max_length=500)
    cover_theme: str | None = Field(default=None, max_length=50)
    publish_at: datetime | None = None
    # Nature 式栏目与期次分部分（021）
    article_section: str | None = Field(default=None, max_length=40)
    issue_part: str | None = Field(default=None, max_length=40)
    # 内容赛道/类别：content_track 为唯一权威；只传类别时按类别回推赛道
    # （academic→paper，fun/rant→essay）。落库由 routes 统一走 canonicalize。
    content_track: Literal["paper", "essay"] | None = None
    content_category: ContentCategory | None = None
    # 娱乐轨文体细分（v1.16）：后台可改；论文轨忽略。
    content_genre: EssayGenre | None = None

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
    # 本站刊号：R-<六位刊号>-<YYYYMMDD>-<四位流水>，不是官方 DOI。
    site_id: str | None = None
    slug: str | None = None
    created_at: datetime
    updated_at: datetime
    has_file: bool = False
    # 是否有在线阅读用 Markdown 稿件（列表与详情都返回）
    has_markdown: bool = False
    # 内容赛道（唯一权威）：paper|essay。响应层按 track 校正 content_category。
    content_track: str | None = None  # type: ignore[assignment]
    # 特别篇：篇幅超过轨道上限、经显式特许的稿件。阅读端显示标签。
    is_special_issue: bool = False
    special_issue_reason: str | None = None
    # 中图分类号校正状态：valid / needs_correction / absent（由 clc_code 反推）。
    clc_status: str | None = None
    # 互动指标（R 指数）：列表与详情都返回，未取到时为 None
    reads: int | None = None
    downloads: int | None = None
    saves: int | None = None
    r_index: float | None = None
    quartile: str | None = None
    # P1：作者位明细（含认领状态）。未认领位 email 强制 null。
    authors_detail: list[AuthorDetail] | None = None

    @field_validator("content_genre", mode="before")
    @classmethod
    def _empty_genre_to_none(cls, v: Any) -> Any:
        # 历史库里有 content_genre=''（空串），Literal 校验会在
        # model_validator 之前就 500；空串与 None 等价，统一折成 None。
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            # 历史/人工回填可能写入白名单外的值（如 article）。读接口
            # 不能因为一条脏数据把整页目录打成 500，未知文体按“无文体”下发。
            allowed = {"joke", "fiction", "review", "guide", "essay", "poetry", "rant"}
            if v not in allowed:
                return None
        return v

    @model_validator(mode="after")
    def _derive_derived_fields(self) -> ResourceResponse:
        """读口径校正：content_track 为权威，content_category 按 track 反推。

        历史脏数据（paper+fun / essay+academic / 漏迁移）在响应层一律按
        track 覆盖，外部看到的永远自洽：paper→academic，essay→fun/rant。

        P0 收口：娱乐稿（content_track=essay）不下发任何学术评分字段——
        quality_score / quality_grade 一律置 null，学术稿（paper）保持原值。
        P1：构建 authors_detail；未认领作者位 email 一律 null（隐私）。
        """
        from app.domain.submission.clc import clc_status_of

        # 本站刊号：六位刊号 + 创建日期 + 四位全站流水。按 id 单调递增，
        # 因此按刊号排序与按发表时间排序一致；它不是 DOI，也不冒充 DOI。
        if not self.site_id:
            from app.core.config import settings

            code = (settings.publication_code or "000001").strip()
            self.site_id = f"R-{code}-{self.created_at:%Y%m%d}-{self.id:04d}"

        self.content_track = resolve_content_track(self.content_track, self.content_category)
        self.content_category = resolve_category(self.content_track, self.content_category)  # type: ignore[assignment]
        self.clc_status = clc_status_of(self.clc_code)
        if self.content_track == "paper":
            # 论文轨没有“文体”这个概念，历史脏值一律不下发。
            self.content_genre = None
        elif not self.content_genre:
            from app.domain.catalog.genre import classify_essay_genre

            self.content_genre = classify_essay_genre(self.title, category=self.content_category)  # type: ignore[assignment]
        if self.content_track == "essay":
            self.quality_score = None
            self.quality_grade = None
            # P1：中图分类号只论文有，娱乐稿不下发（DB 值不删，后续分类改判）。
            self.clc_code = None
            self.clc_label = None
            self.clc_status = "absent"
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
    # 内容赛道（paper / essay）分布；by_type 是资源形态（paper/book/dataset）。
    by_track: dict[str, int] = {}
    by_discipline: dict[str, int]
    # 娱乐轨文体分布（只统计 essay）；论文轨不产生 key。
    by_genre: dict[str, int] = {}
    # 论文轨内部 serious / absurd 的实时分布。前端论文页两个 tab 的计数
    # 必须用这份全量聚合，不能只数「随机推荐池」那 50 条。
    by_paper_kind: dict[str, int] = {}
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
    # 论文轨内部拆分：学术稿 / 荒诞稿。指标页必须分开说，否则 240 篇里
    # 231 篇荒诞稿会被读者误读成“学术产能”。
    serious_total: int = 0
    absurd_total: int = 0
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
    "EssayGenre",
    "FacetBucket",
    "IssueSummary",
    "JournalMetrics",
    "PaginationMeta",
    "PublicationStatus",
    "ResourceBase",
    "ResourceCreate",
    "ResourceFacets",
    "ResourceListResponse",
    "ResourceResponse",
    "ResourceStats",
    "ResourceType",
    "ResourceUpdate",
    "VolumeSummary",
    "VolumeSummaryList",
]
