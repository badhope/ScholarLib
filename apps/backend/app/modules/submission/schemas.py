"""Pydantic schemas for the submission module.

Create / Review / Response shapes. Field constraints mirror catalog
``ResourceBase`` so an approval can materialize a catalog Resource
without value re-validation surprises.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.schemas import Authors, MessageResponse, PaginationMeta
from app.core.tracks import Track, normalize_track

# 完整 workflow 状态机：
#   pending → under_review → (major_revision | minor_revision | accepted | rejected)
#   major_revision / minor_revision → resubmitted → under_review（再分配审稿人）
#   accepted → 自动物化 Resource 入 catalog（等价于旧 approved，保留向后兼容）
# pending = 作者已提交、待编辑分配审稿人；accepted = 旧 approved 的同义词。
# 旧测试用 pending/approved/rejected 路径仍走原 review 端点，保持兼容。
SubmissionStatus = Literal[
    "pending",
    "under_review",
    "major_revision",
    "minor_revision",
    "resubmitted",
    # 打回：评分 D 级时编辑发起的「补审/修改」状态（1.9.2 起）。
    # 与 major_revision 的区别：后者是审稿意见驱动的修回，前者是
    # 质量评分不达标驱动的打回，审稿人与作者都要有动作。
    "rework_requested",
    "accepted",
    "rejected",
    # 向后兼容别名（review 端点允许 approved 作为 accepted 的同义词写入）
    "approved",
]
SubmissionType = Literal["paper", "book", "dataset", "tutorial"]
EditorDecision = Literal[
    "accept",
    "minor_revision",
    "major_revision",
    "reject",
    # 向后兼容：旧 review 端点
    "approved",
    "rejected",
]


class SubmissionCreate(BaseModel):
    """Body for POST /submissions — author submits a record for review."""

    title: str = Field(min_length=1, max_length=1000)
    type: SubmissionType
    # 赛道：历史字段，已下线（见 core/tracks.py）。仅保留 serious 一档，
    # 旧客户端传 absurd 等值由 before-validator 归一为 serious，不 422。
    track: Track = "serious"
    authors: Authors = Field(min_length=1, max_length=200)
    year: int = Field(ge=-3000, le=2100)
    venue: str | None = Field(default=None, max_length=500)
    discipline: str = Field(min_length=1, max_length=100)
    subdiscipline: str | None = Field(default=None, max_length=100)
    # 栏目 / 期次分部：与 catalog Resource 字段同名，录用时直接物化。
    article_section: str | None = Field(default=None, max_length=40)
    issue_part: str | None = Field(default=None, max_length=40)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    jel_codes: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=50)
    abstract: str = Field(min_length=1, max_length=20000)
    # preview 可选：作者通常不知道要填，留空时自动从 abstract 截取前 500 字。
    # 之所以放宽是因为旧版本必填导致大量首次投稿 422 失败（实测摩擦点）。
    preview: str | None = Field(default=None, max_length=5000)
    download_url: AnyHttpUrl | None = None
    external_url: AnyHttpUrl | None = None
    doi: str | None = Field(default=None, max_length=200)
    corresponding_author_email: str | None = Field(default=None, max_length=255)

    @field_validator("track", mode="before")
    @classmethod
    def _normalize_track(cls, v: object) -> object:
        """赛道已下线：任意非 serious 输入（含历史 absurd）归一为 serious。"""
        if v is None:
            return None
        return normalize_track(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _fill_preview_from_abstract(self) -> SubmissionCreate:
        if not self.preview:
            # 留空时用 abstract 前 500 字作 preview；不超过 5000 字限制
            self.preview = (self.abstract or "")[:500]
        return self


class SubmissionReview(BaseModel):
    """Body for PATCH /submissions/{id}/review — editor decision.

    ``resource_id`` is only meaningful for approvals and is optional:
    if omitted on approval, a new catalog Resource is materialized from
    the submission payload.
    """

    status: Literal["approved", "rejected"]
    admin_note: str | None = Field(default=None, max_length=5000)
    resource_id: int | None = Field(default=None, ge=1)


class SubmissionDecision(BaseModel):
    """Body for PATCH /submissions/{id}/decision — editor final decision.

    4-元决定（accept/minor_revision/major_revision/reject）。accept 等价于
    旧 approved：自动物化 catalog Resource（除非 resource_id 指定现有资源）。
    major_revision / minor_revision 把状态置为相应值，等作者 resubmit。
    """

    decision: EditorDecision
    editor_note: str | None = Field(default=None, max_length=5000)
    resource_id: int | None = Field(default=None, ge=1)
    # accept 且新建物化时生效：published（默认，录用即刊，兼容旧行为）或
    # draft（暂存草稿——刊前整理阶段，之后由 admin PATCH /catalog/{id} 刊出）。
    # 指定现有 resource_id 时不改动该条目的刊出状态。
    publication_status: Literal["published", "draft"] = "published"
    # D 级（<60 分）默认不能录用：必须先打回审稿人补审或要求作者修改。
    # 确需破例时置 true，且必须在 editor_note 里写明理由——破例本身要
    # 可追溯，否则"D 级硬发"会变成常规操作。
    force_accept_d_grade: bool = False
    # 仲裁人第三方意见或编辑的冲突裁决理由；会并入 editor_note 留痕。
    arbitration_note: str | None = Field(default=None, max_length=5000)


class AnonymizedFileUpdate(BaseModel):
    """Body for PUT /submissions/{id}/anonymized-file — editor only.

    双盲评审下编辑提供给审稿人的匿名稿外链。与作者可控的 download_url
    完全隔离：本字段只能经此编辑端点写入。传 null 表示清除。
    """

    anonymized_file_url: AnyHttpUrl | None = None


class ReworkRequest(BaseModel):
    """打回稿件：必须列出具体修改要求。

    ``requirements`` 下限 3 条是刻意的：一句"不合格"对作者没有行动指引，
    对审稿人也没有可补的方向。打回的成本应该落在"说清楚问题"上，而不是
    落在作者反复猜测上。
    """

    requirements: list[str] = Field(min_length=3, max_length=20)
    note: str | None = Field(default=None, max_length=5000)


class WaiveReviewRequest(BaseModel):
    """Body for POST /submissions/{id}/waive-review — desk accept 前置声明。

    ``reason`` 强制非空且≥10 字：这条理由是「为什么这篇稿子没有走同行
    评审」的唯一书面依据，会进审计日志并随录用通知发给作者。允许空理由
    等于允许无声的例外。
    """

    reason: str = Field(min_length=10, max_length=2000)


class FormatCheckItem(BaseModel):
    """结构报告的单项检查结果（给作者的"离规范还差什么"）。"""

    key: str
    label: str
    ok: bool
    hint: str = ""


class FormatReport(BaseModel):
    """稿件结构报告：上传后即时生成，随响应返回。"""

    ok: bool
    word_count: int = 0
    items: list[FormatCheckItem] = []


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    type: str
    # 赛道：历史字段（已下线），库中恒为 serious，仅为兼容保留。
    track: Track = "serious"
    authors: list[str]
    year: int
    venue: str | None = None
    discipline: str
    subdiscipline: str | None = None
    article_section: str | None = None
    issue_part: str | None = None
    keywords: list[str] = Field(default_factory=list)
    jel_codes: list[str] = Field(default_factory=list)
    tags: list[str]
    abstract: str
    preview: str
    download_url: str | None = None
    external_url: str | None = None
    # 双盲下编辑提供的匿名稿外链（审稿人可见）；作者视角本字段可空
    anonymized_file_url: str | None = None
    doi: str | None = None
    corresponding_author_email: str | None = None
    status: SubmissionStatus
    admin_note: str | None = None
    editor_note: str | None = None
    # 关联目录条目的刊出状态（published/draft/in_review）；无关联时为 None。
    # 前端据此区分「已发表」与「刊前预览（暂存草稿）」。
    resource_publication_status: str | None = None
    resource_id: int | None = None
    cover_image: str | None = None
    file_path: str | None = None
    # 在线阅读用 Markdown 稿件的存储 key（可空 = 回退 PDF 视图）。
    markdown_path: str | None = None
    # 双盲评审下审稿人视角会被抹掉，因此可空
    submitted_by: int | None = None
    submitted_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    # 结构报告：仅上传文件端点返回（详情/列表不返回，避免重复计算）
    format_report: FormatReport | None = None
    # 上传结果提示（P0）：扩展名与实际格式不一致、needs_docx 原因、
    # 中图分类号待校正等。仅上传端点返回。
    upload_warnings: list[str] = []
    # 审稿进度（列表页/详情页共用）：发表闸门依赖这些数字。
    reports_completed: int = 0
    distinct_reviewers: int = 0
    accept_recommendations: int = 0
    reject_recommendations: int = 0
    can_decide: bool = False
    conflict: bool = False
    adjudicator_assigned: bool = False
    adjudicator_accepted: bool = False


class SubmissionListResponse(BaseModel):
    data: list[SubmissionResponse]
    meta: PaginationMeta


class ReviewerCandidate(BaseModel):
    """Editor 分配审稿人时的候选（持有 reviewer 角色且账号启用）。"""

    id: int
    username: str
    email: str


class ReviewerCandidateListResponse(BaseModel):
    data: list[ReviewerCandidate]


class SubmissionUpdate(BaseModel):
    """Body for PATCH /submissions/{id} — author edits their manuscript.

    仅在 pending / major_revision / minor_revision 状态下允许（编辑要求
    修改后，作者要能真正改内容，而不是只把状态翻回去）。所有字段可选，
    只更新提供的字段；约束与 SubmissionCreate 逐字段一致。
    """

    title: str | None = Field(default=None, min_length=1, max_length=1000)
    type: SubmissionType | None = None
    # 赛道：历史字段，已下线。None = 不修改；非 serious 输入归一为 serious。
    track: Track | None = None
    authors: Authors | None = Field(default=None, min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=-3000, le=2100)
    venue: str | None = Field(default=None, max_length=500)
    discipline: str | None = Field(default=None, min_length=1, max_length=100)
    subdiscipline: str | None = Field(default=None, max_length=100)
    article_section: str | None = Field(default=None, max_length=40)
    issue_part: str | None = Field(default=None, max_length=40)
    keywords: list[str] | None = Field(default=None, max_length=50)
    jel_codes: list[str] | None = Field(default=None, max_length=20)
    tags: list[str] | None = Field(default=None, max_length=50)
    abstract: str | None = Field(default=None, min_length=1, max_length=20000)
    preview: str | None = Field(default=None, max_length=5000)
    download_url: AnyHttpUrl | None = None
    external_url: AnyHttpUrl | None = None
    doi: str | None = Field(default=None, max_length=200)
    corresponding_author_email: str | None = Field(default=None, max_length=255)

    @field_validator("track", mode="before")
    @classmethod
    def _normalize_track(cls, v: object) -> object:
        """赛道已下线：非 serious 输入（含历史 absurd）归一为 serious。"""
        if v is None:
            return None
        return normalize_track(v) if isinstance(v, str) else v


class ResubmitRequest(BaseModel):
    """Body for POST /submissions/{id}/resubmit — optional author note."""

    note: str | None = Field(default=None, max_length=5000)


class SubmissionVersionResponse(BaseModel):
    """One immutable snapshot in a submission's version history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    version: int
    payload: dict[str, Any]
    cover_image: str | None = None
    file_path: str | None = None
    note: str | None = None
    created_by: int | None = None
    created_at: datetime


class SubmissionVersionListResponse(BaseModel):
    data: list[SubmissionVersionResponse]


__all__ = [
    "AnonymizedFileUpdate",
    "EditorDecision",
    "MessageResponse",
    "PaginationMeta",
    "ResubmitRequest",
    "ReviewerCandidate",
    "ReviewerCandidateListResponse",
    "SubmissionCreate",
    "SubmissionDecision",
    "SubmissionListResponse",
    "SubmissionResponse",
    "SubmissionReview",
    "SubmissionStatus",
    "SubmissionType",
    "SubmissionUpdate",
    "SubmissionVersionListResponse",
    "SubmissionVersionResponse",
]
