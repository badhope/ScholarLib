"""学术价值评分口径 v3.0（RQS v3.0）——ABCDF± 严厉客观制。

演进动机
--------
v1.0 的七个维度全部是**表层统计**（有没有引言、字数够不够、参考文献几条），
机器一测就有，也最容易被伪造；v2.0 把权重挪到需要判断力的维度（问题价值、
论证链、方法透明度、证据强度），但五档等级带（A/B/C/D）颗粒太粗：79.5 与
71 同样只差一档，编辑部无法据此区分"可直接发表"与"边缘可发表"。

v3.0 在保持七维学术价值体系不变的前提下，改为 **14 档带加减号的等级制**
（ABCDF±），并把判分标准调得**严厉而客观**：

- A+（95–100）是典范水准，刻意极少达到——多数正常稿子应落在 C/D；
- 分数带连续无缝隙，按「下限」降序匹配（见 ``grade_for``）；
- 只有总分 **低于 40 分**才算不合格（``rejected``），必须打回；
- F（40–54）是"合格"：可以阅读、仍可发表——字母 F 在这里不是"不及格"，
  而是"基础合格但无亮点"（这是本刊的刻意语义，别用常识去套）。

七个维度（合计 100）
--------------------
1. **问题价值 problem**（研究 18）— 研究问题是否真实、具体、未被充分回答。
2. **论证链 argument**（研究 21）— 从前提走到结论的链条是否完整、有无跳跃。
   权重最高：学术写作的核心失败不是数据少，是推论断。
3. **方法透明度 method**（研究 16）— 别人能否照着复现。
4. **证据强度 evidence**（研究 17）— 结论被证据支持的程度。
5. **创新与定位 novelty**（研究 12）— 相对已有工作补了哪一块。
6. **学术诚信 integrity**（研究 10）— 引用真实可核、数据可追。
   这一维**一票否决**：0 分即总分归零（不予发表）。
7. **表达清晰度 presentation**（研究 6）— 结构与语言是否让读者读得下去。
   权重刻意压低：图表格式等机器可测项已移出（图表相关问题只保留在
   ``auto_precheck`` 的 warning 里），此维只评结构与语言。

自动可测项（保留，但降级为证据）
--------------------------------
``PaperMetrics`` 仍然计算结构/篇幅/引用数/图数，但不再直接换成分数，
而是作为 ``auto_precheck`` 的硬伤检查输入。机器做机器擅长的（查漏），
人做人擅长的（判断）。

等级与处置
----------
A+ 95–100 · A 90–94 · A- 85–89 · B±/B 75–84 · C±/C 65–74 ·
D±/D 55–64（较弱，D- 为边缘稿）· F 40–54（合格，可发表）· <40 不合格。

**<40 才是打回**：不合格稿件（``rejected``）必须退回审稿人补审或要求作者
修改，并把缺陷逐条写清。55–57 的 D- 可发表但标记 ``borderline``，提示编辑
谨慎。见 ``app/modules/quality/review_form.py`` 与
``submission/routes_editor.py`` 的录用门禁与 ``request_rescore`` 端点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

RUBRIC_VERSION = "3.0"

# --- 维度定义 -------------------------------------------------------------

DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("problem", "问题价值", "研究问题是否真实、具体、值得回答"),
    ("argument", "论证链完整性", "从前提走到结论有无跳跃与循环论证"),
    ("method", "方法透明度", "他人能否照此复现：数据、样本、参数、失败案例"),
    ("evidence", "证据强度", "结论是否被证据支撑；相关是否被当因果"),
    ("novelty", "创新与定位", "相对已有工作补了哪一块，增量是什么"),
    ("integrity", "学术诚信", "引用真实可核、数据可追、声明完整（一票否决）"),
    ("presentation", "表达清晰度", "结构与语言是否让读者读得下去（图表格式走 auto_precheck）"),
)

DIMENSION_LABELS: dict[str, str] = {k: label for k, label, _ in DIMENSIONS}
DIMENSION_HINTS: dict[str, str] = {k: hint for k, _, hint in DIMENSIONS}

# 每类稿件一套权重；每套必须合计 100（test_quality_rubric 守住）。
# v3.0：presentation 检查项从 3 条减到 2 条（p_figures 移除，图表格式不是
# 学术质量），省出的 2 分挪给 argument / evidence 各 1 分。
# 差异体现在"这类写作里哪一维更该被问责"：
# - research：论证与证据是命门
# - review：问题价值与论证链（综述的失败是"文献堆砌没有立场"）
# - essay：论证与表达（随笔靠论证与文笔，不靠数据）
# - note：方法透明度与证据（简报的价值全在"能不能复现"）
PROFILES: dict[str, dict[str, int]] = {
    "research": {
        "problem": 18,
        "argument": 21,
        "method": 16,
        "evidence": 17,
        "novelty": 12,
        "integrity": 10,
        "presentation": 6,
    },
    "review": {
        "problem": 20,
        "argument": 23,
        "method": 10,
        "evidence": 13,
        "novelty": 16,
        "integrity": 10,
        "presentation": 8,
    },
    "essay": {
        "problem": 22,
        "argument": 27,
        "method": 6,
        "evidence": 13,
        "novelty": 14,
        "integrity": 10,
        "presentation": 8,
    },
    "note": {
        "problem": 14,
        "argument": 17,
        "method": 24,
        "evidence": 21,
        "novelty": 8,
        "integrity": 10,
        "presentation": 6,
    },
}

PROFILE_LABELS = {
    "research": "研究论文",
    "review": "综述",
    "essay": "随笔 / 评论",
    "note": "研究简报",
}

# 14 档等级带（v3.0）：分数带必须连续无缝隙，区间按「下限」降序排列。
# 注意本刊语义：F（40–54）= 合格、可发表；只有 <40 才是不合格（见
# evaluate 的 rejected 字段）。A+ 刻意只留 95–100，是典范水准，极少达到。
GRADE_BANDS: tuple[tuple[str, str, int, int], ...] = (
    ("A+", "极佳", 95, 100),
    ("A", "极佳", 90, 94),
    ("A-", "优秀", 85, 89),
    ("B+", "良好", 82, 84),
    ("B", "良好", 78, 81),
    ("B-", "良好", 75, 77),
    ("C+", "中等", 72, 74),
    ("C", "中等", 68, 71),
    ("C-", "中等", 65, 67),
    ("D+", "较弱", 62, 64),
    ("D", "较弱", 58, 61),
    ("D-", "较弱", 55, 57),
    ("F", "合格", 40, 54),
)

# 0–5 分锚点：每个维度都用同一把尺子，避免"这位审稿人手松"。
# 锚点必须具体到可判断，否则不同人给出的 3 分含义不同。
SCORE_ANCHORS: tuple[tuple[int, str], ...] = (
    (5, "达到该领域已发表论文的典型水准，无明显可改进处"),
    (4, "整体扎实，有 1–2 处可改进但不影响结论成立"),
    (3, "基本达标，但存在影响说服力的缺陷（需修回）"),
    (2, "明显不足，结论的可靠性受质疑（需大修或重新分析）"),
    (1, "该维度基本缺失或方法性错误（不足以支撑发表）"),
    (0, "完全缺失，或存在学术不端"),
)


@dataclass
class DimensionScore:
    """一个维度的评分：分值 + 必填理由。

    ``reason`` 强制非空——"给 2 分"没有信息量，"给 2 分因为样本仅 3 例
    却下了普适结论"才是可复核的判断。理由同时是给作者的修改指引。
    """

    key: str
    score: int  # 0–5
    reason: str

    def __post_init__(self) -> None:
        if self.key not in DIMENSION_LABELS:
            raise ValueError(f"Unknown dimension: {self.key}")
        if not 0 <= self.score <= 5:
            raise ValueError(f"{self.key}: score must be 0–5, got {self.score}")
        if not self.reason.strip():
            raise ValueError(f"{self.key}: reason is required (评分必须给理由)")


@dataclass
class PaperMetrics:
    """自动可测的客观事实。**不再直接换成分数**，只作为证据与硬伤检查。"""

    article_type: str = "research"
    cjk_chars: int = 0
    total_chars: int = 0
    pages: int = 0
    paragraphs: int = 0
    paragraph_cv: float = 0.0
    section_hits: dict[str, bool] = field(default_factory=dict)
    abstract_chars: int = 0
    has_problem: bool = False
    has_method: bool = False
    has_result: bool = False
    has_conclusion: bool = False
    keywords: int = 0
    references: int = 0
    reference_style: str = "none"
    reference_dois: int = 0
    doi_resolved: int = 0
    figure_numbers: int = 0
    figure_citations: int = 0
    table_numbers: int = 0
    table_citations: int = 0
    fonts: list[str] = field(default_factory=list)
    title_chars: int = 0
    title_lines: int = 1
    has_a4: bool = False
    has_affiliation_block: bool = False


REQUIRED_SECTIONS: tuple[str, ...] = (
    "引言",
    "相关工作",
    "方法",
    "结果",
    "讨论",
    "结论",
)

PROFILE_SECTIONS: dict[str, tuple[str, ...]] = {
    "research": REQUIRED_SECTIONS,
    "review": ("引言", "相关工作", "讨论", "结论"),
    "essay": ("引言", "讨论", "结论"),
    "note": ("引言", "方法", "结果", "结论"),
}

MIN_REFERENCES: dict[str, int] = {
    "research": 8,
    "review": 15,
    "essay": 0,
    "note": 4,
}

LENGTH_TIERS: dict[str, tuple[int, int, int]] = {
    "research": (2500, 5000, 8000),
    "review": (3000, 6000, 10000),
    "essay": (1500, 3000, 6000),
    "note": (1200, 2500, 5000),
}

ABSTRACT_MIN = 200
ABSTRACT_MAX = 350


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def grade_for(score: float) -> tuple[str, str]:
    """Band lookup that tolerates fractional scores.

    区间必须按「下限」降序比较：79.5 既不落在 [78,81] 也不在 [82,84]，
    写成闭区间会直接掉到最低档——一个 79.5 分的稿子被判最差档是硬 bug
    （v2.x 历史事故，不得复现）。低于 40 分不落在任何带内，返回
    ``("F", "不合格")``——字母仍是 F，但 label 与 40–54 的「合格」区分，
    真正的处置标记看 ``evaluate`` 的 ``rejected`` 字段。
    """
    for code, label, low, _high in GRADE_BANDS:
        if score >= low:
            return code, label
    return "F", "不合格"


def auto_precheck(m: PaperMetrics) -> list[dict[str, str]]:
    """自动硬伤检查：只报"机器能确定"的事实，不代替判断。

    每条返回 ``{level, dimension, message}``。``level`` 分
    ``blocker``（必须修）与 ``warning``（建议修）。这些不直接扣分，
    而是作为审稿人评分时的证据提示，以及作者的提交前自检。
    """
    issues: list[dict[str, str]] = []
    profile_type = m.article_type if m.article_type in PROFILES else "research"

    if m.abstract_chars == 0:
        issues.append(
            {
                "level": "blocker",
                "dimension": "presentation",
                "message": "未检测到摘要。摘要四要素（问题/方法/结果/结论）缺失时读者无法判断是否继续读。",
            }
        )
    elif m.abstract_chars < ABSTRACT_MIN:
        issues.append(
            {
                "level": "warning",
                "dimension": "presentation",
                "message": f"摘要约 {m.abstract_chars} 字，低于规范下限 {ABSTRACT_MIN} 字。",
            }
        )

    floor_refs = MIN_REFERENCES.get(profile_type, 8)
    if floor_refs > 0 and m.references < floor_refs:
        issues.append(
            {
                "level": "blocker" if m.references == 0 else "warning",
                "dimension": "integrity",
                "message": (
                    f"参考文献 {m.references} 条，低于该类稿件下限 {floor_refs} 条。"
                    "引用不足会让读者无法定位你的工作相对谁而做。"
                ),
            }
        )
    if m.references > 0 and m.reference_dois > 0:
        unresolved = m.reference_dois - m.doi_resolved
        if unresolved > 0:
            issues.append(
                {
                    "level": "warning",
                    "dimension": "integrity",
                    "message": (
                        f"{m.reference_dois} 条含 DOI 的文献中有 {unresolved} 条未能解析。"
                        "请逐条核实（编辑部会抽查 ≥30%）。"
                    ),
                }
            )
    if m.references > 0 and m.reference_style == "none":
        issues.append(
            {
                "level": "warning",
                "dimension": "presentation",
                "message": "参考文献未使用顺序编码制（[1][2]），不符合 GB/T 7714-2015。",
            }
        )

    required = PROFILE_SECTIONS.get(profile_type, REQUIRED_SECTIONS)
    missing = [s for s in required if not m.section_hits.get(s)]
    if missing:
        issues.append(
            {
                "level": "warning",
                "dimension": "presentation",
                "message": f"缺少以下章节：{'、'.join(missing)}。",
            }
        )

    if m.figure_numbers and m.figure_citations < m.figure_numbers:
        uncited = m.figure_numbers - m.figure_citations
        issues.append(
            {
                "level": "warning",
                "dimension": "presentation",
                "message": f"{uncited} 个图/表未在正文中被引用（正文须显式写「见图 2」）。",
            }
        )

    return issues


def evaluate(
    dimension_scores: list[DimensionScore],
    *,
    article_type: str = "research",
    metrics: PaperMetrics | None = None,
    override_total: float | None = None,
) -> dict[str, object]:
    """按维度评分计算 RQS v3.0。

    ``dimension_scores`` 必须覆盖全部七个维度——缺一个就拒绝计算，
    而不是按缺失维度给 0 分：那会让"审稿人漏填"看起来像"这篇很差"。

    ``override_total`` 供管理员在有理据时直接指定总分（记录在
    ``overridden`` 字段里，可追溯）。

    处置语义（v3.0）：

    - ``rejected``：总分 < 40，不合格，不予发表，必须打回（
      ``requires_rework`` 与之等价）；
    - ``borderline``：总分落在 55–57（D-），可发表但属边缘稿，
      payload 标记出来提示编辑谨慎；
    - F（40–54）= 合格，可阅读、可发表。
    """
    profile_type = article_type if article_type in PROFILES else "research"
    profile = PROFILES[profile_type]

    by_key = {d.key: d for d in dimension_scores}
    missing = [k for k, _, _ in DIMENSIONS if k not in by_key]
    if missing:
        raise ValueError(f"Missing dimension scores: {missing}")

    breakdown: dict[str, dict[str, object]] = {}
    total = 0.0
    for key, label, _hint in DIMENSIONS:
        weight = profile[key]
        d = by_key[key]
        # 0–5 分映射到 0–1，再乘权重。5 分 = 满分。
        ratio = d.score / 5.0
        points = round(weight * ratio, 2)
        total += points
        breakdown[key] = {
            "label": label,
            "score": d.score,
            "max_score": 5,
            "points": points,
            "max_points": weight,
            "ratio": round(ratio, 4),
            "reason": d.reason,
        }

    # 学术诚信一票否决：integrity = 0 总分直接归零，无论其他维度多高。
    integrity = by_key["integrity"].score
    veto = integrity == 0
    if veto:
        total = 0.0

    total = round(_clamp(total, 0, 100), 1)
    overridden = False
    if override_total is not None:
        total = round(_clamp(override_total, 0, 100), 1)
        overridden = True

    grade, grade_label = grade_for(total)
    # <40 才是不合格：必须打回，不得发表。F（40–54）是合格可发表，
    # 55–57 的 D- 可发表但提示编辑谨慎（边缘稿）。
    rejected = total < 40
    borderline = 55 <= total <= 57
    payload: dict[str, object] = {
        "rubric_version": RUBRIC_VERSION,
        "article_type": profile_type,
        "article_type_label": PROFILE_LABELS.get(profile_type, "研究论文"),
        "score": total,
        "grade": grade,
        "grade_label": grade_label,
        "breakdown": breakdown,
        "integrity_veto": veto,
        "overridden": overridden,
        "rejected": rejected,
        "borderline": borderline,
        # 不合格必须打回：这不是提示，是流程约束（见 routes_editor）。
        "requires_rework": rejected,
    }
    if metrics is not None:
        payload["auto_precheck"] = auto_precheck(metrics)
    return payload


def rubric_payload() -> dict[str, object]:
    """公开口径：审稿人、作者、外部 AI 都用这一份。"""
    return {
        "version": RUBRIC_VERSION,
        "dimensions": [
            {"key": key, "label": label, "hint": hint, "max_score": 5}
            for key, label, hint in DIMENSIONS
        ],
        "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS],
        "profiles": {
            name: {"label": PROFILE_LABELS[name], "weights": weights}
            for name, weights in PROFILES.items()
        },
        "grades": [
            {"code": code, "label": label, "min": low, "max": high}
            for code, label, low, high in GRADE_BANDS
        ],
        "required_sections": list(REQUIRED_SECTIONS),
        "profile_sections": {k: list(v) for k, v in PROFILE_SECTIONS.items()},
        "min_references": MIN_REFERENCES,
        "length_tiers": {
            k: {"short": v[0], "medium": v[1], "long": v[2]} for k, v in LENGTH_TIERS.items()
        },
        "abstract_band": [ABSTRACT_MIN, ABSTRACT_MAX],
        "integrity_veto": "integrity 维度 0 分 → 总分归零（学术不端一票否决，不予发表）",
        "rejected_below": 40,
        "rejected_action": "总分低于 40 分为不合格，不予发表，必须打回审稿人补审或要求作者修改",
        "borderline_band": [55, 57],
        "borderline_action": "D-（55–57 分）可发表，但属边缘稿，payload 标记 borderline 提示编辑谨慎",
    }


__all__ = [
    "ABSTRACT_MAX",
    "ABSTRACT_MIN",
    "DIMENSIONS",
    "DIMENSION_HINTS",
    "DIMENSION_LABELS",
    "DimensionScore",
    "GRADE_BANDS",
    "LENGTH_TIERS",
    "MIN_REFERENCES",
    "PROFILES",
    "PROFILE_LABELS",
    "PROFILE_SECTIONS",
    "PaperMetrics",
    "REQUIRED_SECTIONS",
    "RUBRIC_VERSION",
    "SCORE_ANCHORS",
    "auto_precheck",
    "evaluate",
    "grade_for",
    "rubric_payload",
]
