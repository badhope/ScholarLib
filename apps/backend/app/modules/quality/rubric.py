"""学术价值评分口径 v4.0（RQS v4.0）——七维百分制 + ABCDEF 全字母制。

演进动机
--------
v1.0 的七个维度全部是**表层统计**（有没有引言、字数够不够、参考文献几条），
机器一测就有，也最容易被伪造；v2.0 把权重挪到需要判断力的维度；v3.0 改为
严厉等级制，但每个维度只有 0–5 五个锚点——颗粒太粗：审稿人想说"这篇比
那篇好一点"时只能给同一个 4 分，无法表达细差异。

v4.0 在保持七维学术价值体系不变的前提下做三件事：

1. **每个维度改用 0–100 百分制**，总分 = Σ(维度分 × 权重 ÷ 100)。
   检查项答案仍自动折算建议分，但审稿人可以在整条 0–100 的刻度上表达
   信心差异。
2. **A 级对标顶刊**：A+（97–100）的定义是"可作为领域范本被引用的
   Science/Nature 级处理"，刻意极少达到；多数正常稿子应落在 C/D/E。
   分档锚点全部按顶刊标准措辞，宁严勿宽。
3. **等级字母补全为 ABCDEF 全字母**：v3.0 沿用美制跳过了 E，与"字母
   随分数递增"的直觉冲突；v4.0 改为 F（及格，40–49）向上依次是
   E（基础）、D（达标）、C（中等）、B（良好）、A（优秀以上）。
   低档位的称号全部使用中性描述（基础/达标/及格），不使用任何贬义词。

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

自动可测项（保留，但降级为证据）
--------------------------------
``PaperMetrics`` 仍然计算结构/篇幅/引用数/图数，但不再直接换成分数，
而是作为 ``auto_precheck`` 的硬伤检查输入。机器做机器擅长的（查漏），
人做人擅长的（判断）。

等级与处置
----------
A+ 97–100（典范，对标顶刊）· A 93–96 · A- 90–92 · B± 80–89 ·
C± 70–79 · D± 60–69 · E± 50–59 · F 40–49（及格，可发表）·
<40 不合格（无等级，打回修改）。

**<40 才是打回**：不合格稿件必须退回审稿人补审或要求作者修改，并把缺陷
逐条写清。50–52 的 E- 属边缘稿，标记 ``borderline`` 提示编辑谨慎。
见 ``app/modules/quality/review_form.py`` 与 ``submission/routes_editor.py``
的录用门禁与 ``request_rescore`` 端点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

RUBRIC_VERSION = "4.0"

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

# 16 档等级带（v4.0）：字母补全 ABCDEF，分数带连续无缝隙，按「下限」降序。
# 称号全部中性：不给低分段起难听的称号，避免打击作者信心。
# A+ 对标顶刊（Science/Nature 级），刻意极少达到；F（40–49）= 及格。
GRADE_BANDS: tuple[tuple[str, str, int, int], ...] = (
    ("A+", "典范", 97, 100),
    ("A", "顶尖", 93, 96),
    ("A-", "优秀", 90, 92),
    ("B+", "优秀", 87, 89),
    ("B", "良好", 83, 86),
    ("B-", "良好", 80, 82),
    ("C+", "中等", 77, 79),
    ("C", "中等", 73, 76),
    ("C-", "中等", 70, 72),
    ("D+", "达标", 66, 69),
    ("D", "达标", 62, 65),
    ("D-", "达标", 60, 61),
    ("E+", "基础", 56, 59),
    ("E", "基础", 52, 55),
    ("E-", "基础", 50, 51),
    ("F", "及格", 40, 49),
)

# 0–100 分锚点：每个维度都用同一把尺子，避免"这位审稿人手松"。
# 锚点按顶刊标准措辞，宁严勿宽——A 级必须是能拿去和顶刊文章对话的水准。
SCORE_ANCHORS: tuple[tuple[int, str], ...] = (
    (95, "顶刊典范（Science/Nature 级）：该维度的处理可以作为领域范本被引用，几乎无可指摘。绝大多数稿件达不到这一档。"),
    (90, "顶刊门槛：明显超出本领域已发表文章的典型水准，判断与执行都无可辩驳。A 级刻意稀缺。"),
    (80, "一流水准：整体扎实且有明显亮点，仅有 1–2 处可改进但不影响结论成立。"),
    (70, "合格期刊水准：方法与论证基本可靠，存在可指出的缺陷但不致命（需小幅修回）。"),
    (60, "达标但平淡：能自圆其说，深度或严谨性有明显欠缺（需大修）。"),
    (50, "勉强及格：存在影响可信度的实质缺陷，结论的可靠性受质疑（需实质性修改后重审）。"),
    (0, "不及格：该维度基本缺失、方法性错误，或存在学术不端（诚信维度 0 分即一票否决）。"),
)


@dataclass
class DimensionScore:
    """一个维度的评分：0–100 百分制分值 + 必填理由。

    ``reason`` 强制非空——"给 60 分"没有信息量，"给 60 分因为样本仅 3 例
    却下了普适结论"才是可复核的判断。理由同时是给作者的修改指引。
    """

    key: str
    score: float  # 0–100
    reason: str

    def __post_init__(self) -> None:
        if self.key not in DIMENSION_LABELS:
            raise ValueError(f"Unknown dimension: {self.key}")
        if not 0 <= self.score <= 100:
            raise ValueError(f"{self.key}: score must be 0–100, got {self.score}")
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

    区间必须按「下限」降序比较：分数带写成闭区间会让小数分直接掉到
    最低档——一个 79.5 分的稿子被判最差档是硬 bug（v2.x 历史事故，不得
    复现）。低于 40 分不落在任何带内，返回 ``("F", "不合格")``——字母
    与 40–49 的「及格」同为 F，但 label 区分，真正的处置标记看
    ``evaluate`` 的 ``rejected`` 字段。
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

    处置语义（v4.0）：

    - ``rejected``：总分 < 40，不合格，不予发表，必须打回（
      ``requires_rework`` 与之等价）；
    - ``borderline``：总分落在 50–52（E-），及格但属边缘稿，
      payload 标记出来提示编辑谨慎；
    - F（40–49）= 及格，可阅读、可发表；E/D/C/B 依次向上。
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
        # 0–100 百分制映射到 0–1，再乘权重。100 分 = 满分。
        ratio = d.score / 100.0
        points = round(weight * ratio, 2)
        total += points
        breakdown[key] = {
            "label": label,
            "score": d.score,
            "max_score": 100,
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
    # <40 才是不合格：必须打回，不得发表。F（40–49）是及格可发表，
    # 50–52 的 E- 可发表但提示编辑谨慎（边缘稿）。
    rejected = total < 40
    borderline = 50 <= total <= 52
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
            {"key": key, "label": label, "hint": hint, "max_score": 100}
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
        "borderline_band": [50, 52],
        "borderline_action": "E-（50–52 分）及格可发表，但属边缘稿，payload 标记 borderline 提示编辑谨慎",
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
