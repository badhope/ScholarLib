"""学术价值评分口径 v5.0（RQS v5.0）——五维双赛道 + 分区硬门槛。

为什么改
--------
v4.0 是七维百分制，但站内对外一直写“五维两段式”；更要命的是七维同一套
权重套到荒诞稿上，会把“无厘头但自洽”的稿子按样本量、伦理审批逐条扣死。
v5.0 收成两件事：

1. **两条赛道、各五个维度。** 学术稿按同行评审的五个判断面审；荒诞稿按
   “设定是否真荒诞、内部是否自洽、是否一本正经执行、材料是否可核、文风
   是否立得住”审。两套维度名、权重、锚点都不同，不共用一把尺子。
2. **每个维度都要“分 + 理由 + 证据”。** 只有分数没有证据的评分一律拒绝。
   证据必须能落到正文位置（章节/段落/图表/引用编号），不是“感觉不错”。

分区口径（用户已定，不再改）
--------------------------
90–100 = 顶刊级（T1）；80–89 = 一区（Q1）；70–79 = 二区（Q2）；
60–69 = 三区（Q3）；50–59 = 四区（Q4）；<50 = 退稿，不入区。

硬门槛（防止“每项都 70，平均分被拉高”）
------------------------------------
- 学术：诚信 0 分 → 总分归零（一票否决）。
- 任一维度 < 50 → 总分封顶 59；两项及以上 < 50 → 封顶 49（退稿）。
- 任一维度 < 60 → 总分封顶 79（进不了 Q1/顶刊）。
- 论证 < 50 → 封顶 59：论证断链不能靠数据好看进区。
- 荒诞：自洽 < 50 → 封顶 59；执行 < 50 → 封顶 69；任一维度 < 60 → 封顶 79。
  荒诞允许“无中生有”，不允许“前后打架、写不下去、梗硬凑”。

分数锚点
--------
每个赛道一套，90 分以上必须是“该赛道里可以作为范本”的完成度。
"""

from __future__ import annotations

from dataclasses import dataclass, field

RUBRIC_VERSION = "5.0"

# --- 赛道与维度 -----------------------------------------------------------

TRACK_LABELS: dict[str, str] = {
    "academic": "学术赛道",
    "absurd": "荒诞赛道",
}

ACADEMIC_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("question", "选题与真问题", "研究问题真实、具体、未被回答；创新增量说得清"),
    ("argument", "论证与自洽", "前提走到结论无跳跃、无循环；反面解释被处理"),
    ("method", "方法与可复现", "数据、样本、参数、失败案例交代到别人能照着做"),
    ("evidence", "证据与结论", "证据强度匹配结论强度；相关不被写成因果"),
    ("integrity", "规范与诚信", "引用可核、数据可追、声明完整（0 分一票否决）"),
)

ABSURD_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("concept", "荒诞设定与原创", "设定是否真荒诞、新鲜、有记忆点，而不是普通的胡说"),
    ("coherence", "内部自洽", "在这个设定下规则是否自洽、前后不打架"),
    ("execution", "一本正经的执行", "是否用完整结构把荒诞当正事推进，而不是段子拼贴"),
    ("material", "材料与梗的可核查", "梗、数据、案例有出处，或自造规则被明确交代"),
    ("voice", "文风与节奏", "读起来有节奏、有包袱、不啰嗦，荒诞感靠写法立住"),
)

DIMENSIONS_BY_TRACK: dict[str, tuple[tuple[str, str, str], ...]] = {
    "academic": ACADEMIC_DIMENSIONS,
    "absurd": ABSURD_DIMENSIONS,
}

# 兼容旧导入：默认学术五维。
DIMENSIONS = ACADEMIC_DIMENSIONS
DIMENSION_LABELS: dict[str, str] = {k: label for k, label, _ in ACADEMIC_DIMENSIONS}
DIMENSION_HINTS: dict[str, str] = {k: hint for k, _, hint in ACADEMIC_DIMENSIONS}
ABSURD_DIMENSION_LABELS: dict[str, str] = {k: label for k, label, _ in ABSURD_DIMENSIONS}

WEIGHTS: dict[str, dict[str, int]] = {
    "academic": {
        "question": 20,
        "argument": 25,
        "method": 20,
        "evidence": 20,
        "integrity": 15,
    },
    "absurd": {
        "concept": 25,
        "coherence": 20,
        "execution": 20,
        "material": 20,
        "voice": 15,
    },
}

# 学术稿子类型只影响“章节要求/参考文献下限”，不改变五维权重：同一把尺子
# 才能比较研究论文和综述。旧四套 PROFILES 保留为别名，避免调用方 500。
PROFILES: dict[str, dict[str, int]] = {
    "research": WEIGHTS["academic"],
    "review": WEIGHTS["academic"],
    "essay": WEIGHTS["academic"],
    "note": WEIGHTS["academic"],
}

PROFILE_LABELS = {
    "research": "研究论文",
    "review": "综述",
    "essay": "随笔 / 评论",
    "note": "研究简报",
}

# 分区：下限降序。90+ 才是顶刊级，刻意稀缺。
GRADE_BANDS: tuple[tuple[str, str, int, int], ...] = (
    ("T1+", "顶刊范本", 95, 100),
    ("T1", "顶刊级", 90, 94),
    ("Q1", "一区", 80, 89),
    ("Q2", "二区", 70, 79),
    ("Q3", "三区", 60, 69),
    ("Q4", "四区", 50, 59),
    ("R", "退稿", 0, 49),
)

# 每个赛道一套锚点：90 分以上是“范本”，不是“还不错”。
SCORE_ANCHORS: dict[str, tuple[tuple[int, str], ...]] = {
    "academic": (
        (
            95,
            "顶刊范本：该维度可直接作为同领域写作范例，审稿人找不到需要实质修改的地方；极少稿件能达到。",
        ),
        (
            90,
            "顶刊门槛：完成度、证据强度与判断力达到顶刊同领域已发表论文水准，仅有个别编辑性问题。",
        ),
        (80, "一区：五个判断面都站得住，有清晰增量；短板只在局部，不影响结论。"),
        (70, "二区：问题与论证成立，方法或证据有一处可指出的实质不足，修回后可成立。"),
        (60, "三区：能自圆其说，但方法透明度或证据链有明显缺口，需大修后重审。"),
        (50, "四区：核心环节勉强成立，结论可靠性存疑；只能作为边缘稿处理。"),
        (0, "退稿：该维度缺失、方法性错误，或存在学术不端；诚信 0 分一票否决。"),
    ),
    "absurd": (
        (95, "荒诞范本：设定、执行、文风三者合一，读完想转给别人；不是靠堆梗。"),
        (90, "顶刊级荒诞：设定极新，内部规则严丝合缝，一本正经到让人忘记它在胡说。"),
        (80, "一区：荒诞点清楚，结构完整，梗有出处或规则自洽，只有局部节奏可打磨。"),
        (70, "二区：设定成立，执行基本完整，但有段落靠硬凑梗或解释过度。"),
        (60, "三区：有荒诞点，但内部规则开始打架，或后半程写不下去。"),
        (50, "四区：只有零散段子，缺少完整设定与推进；可读但不成篇。"),
        (0, "退稿：设定平庸或前后矛盾，通篇靠梗堆砌，读完没有记忆点。"),
    ),
}

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


def dimensions_for(track: str) -> tuple[tuple[str, str, str], ...]:
    return DIMENSIONS_BY_TRACK.get(track, ACADEMIC_DIMENSIONS)


def weights_for(track: str) -> dict[str, int]:
    return WEIGHTS.get(track, WEIGHTS["academic"])


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def grade_for(score: float, track: str = "academic") -> tuple[str, str]:
    """按分区下限降序比较；小数分不会掉档。"""
    del track  # 两个赛道共用同一套分区，只是锚点措辞不同
    for code, label, low, _high in GRADE_BANDS:
        if score >= low:
            return code, label
    return "R", "退稿"


def auto_precheck(m: PaperMetrics) -> list[dict[str, str]]:
    """自动硬伤检查：只报机器能确定的事实，不代替判断。"""
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


@dataclass
class DimensionScore:
    """一个维度的评分：分值 + 必填理由 + 必填证据。

    只有“70 分”没有信息量；只有“写得不错”也无法复核。证据要能落到正文
    位置（章节/段落/图号/表号/引用编号/链接），审核记录才可追溯。
    """

    key: str
    score: float  # 0–100
    reason: str
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.evidence.strip() and not self.reason.strip():
            raise ValueError(f"{self.key}: evidence requires a reason")
        if self.reason.strip() and len(self.evidence.strip()) < 8:
            raise ValueError(
                f"{self.key}: evidence is required (每个分数必须附正文证据，至少 8 字)"
            )
        if not 0 <= self.score <= 100:
            raise ValueError(f"{self.key}: score must be 0–100, got {self.score}")
        if not self.reason.strip():
            raise ValueError(f"{self.key}: reason is required (评分必须给理由)")


@dataclass
class PaperMetrics:
    """自动可测的客观事实。**不直接换成分数**，只作为证据与硬伤检查。"""

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


def _caps_for(track: str, by_key: dict[str, DimensionScore]) -> tuple[float | None, list[str]]:
    """硬门槛：缺项不能靠其他维度补齐。返回（封顶分，触发的门槛说明）。"""
    caps: list[float] = []
    notes: list[str] = []
    keys = [k for k, _, _ in dimensions_for(track)]
    values = {k: by_key[k].score for k in keys if k in by_key}

    if track == "academic" and values.get("integrity") == 0:
        return 0.0, ["诚信维度 0 分：学术不端一票否决，总分归零"]

    low = [k for k, v in values.items() if v < 50]
    if len(low) >= 2:
        caps.append(49.0)
        notes.append(f"两项及以上维度低于 50 分（{', '.join(low)}）：总分封顶 49，退稿")
    elif len(low) == 1:
        caps.append(59.0)
        notes.append(f"{low[0]} 低于 50 分：总分封顶 59，不进三区及以上")

    mid = [k for k, v in values.items() if 50 <= v < 60]
    if mid and not low:
        caps.append(79.0)
        notes.append(f"以下维度低于 60 分（{', '.join(mid)}）：总分封顶 79，不进一区/顶刊")

    if track == "academic" and values.get("argument", 100) < 50:
        caps.append(59.0)
        notes.append("论证与自洽低于 50 分：论证断链不能靠数据好看进区，封顶 59")

    if track == "absurd":
        if values.get("coherence", 100) < 50:
            caps.append(59.0)
            notes.append("内部自洽低于 50 分：设定前后打架，封顶 59")
        if values.get("execution", 100) < 50:
            caps.append(69.0)
            notes.append("一本正经的执行低于 50 分：段子拼贴不成篇，封顶 69")

    return (min(caps), notes) if caps else (None, [])


def evaluate(
    dimension_scores: list[DimensionScore],
    *,
    track: str = "academic",
    article_type: str = "research",
    metrics: PaperMetrics | None = None,
    override_total: float | None = None,
) -> dict[str, object]:
    """按维度评分计算 RQS v5.0。

    ``dimension_scores`` 必须覆盖该赛道全部五个维度——缺一个就拒绝计算，
    而不是按缺失维度给 0 分：那会让“审稿人漏填”看起来像“这篇很差”。
    """
    track = track if track in WEIGHTS else "academic"
    profile_type = article_type if article_type in PROFILES else "research"
    profile = weights_for(track)
    dims = dimensions_for(track)

    by_key = {d.key: d for d in dimension_scores}
    missing = [k for k, _, _ in dims if k not in by_key]
    unknown = [k for k in by_key if k not in profile]
    if missing:
        raise ValueError(f"Missing dimension scores: {missing}")
    if unknown:
        raise ValueError(f"Unknown dimension for track {track}: {unknown}")
    for key, _label, _hint in dims:
        d = by_key[key]
        if not d.reason.strip():
            raise ValueError(f"{key}: reason is required")
        if len(d.evidence.strip()) < 8:
            raise ValueError(f"{key}: evidence is required (每个分数必须附正文证据)")

    breakdown: dict[str, dict[str, object]] = {}
    total = 0.0
    for key, label, _hint in dims:
        weight = profile[key]
        d = by_key[key]
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
            "evidence": d.evidence,
        }

    cap, cap_notes = _caps_for(track, by_key)
    uncapped = round(_clamp(total, 0, 100), 1)
    total = cap if (cap is not None and uncapped > cap) else uncapped

    total = round(_clamp(total, 0, 100), 1)
    overridden = False
    if override_total is not None:
        total = round(_clamp(override_total, 0, 100), 1)
        overridden = True

    # 完整性闸门：任一维 < 50 说明这个部分“没有交付”，不是“质量差一点”。
    # 没有交付的稿子不进入分区，不能用一个加权总分把它抬进 Q3/Q4；
    # 完整稿（五维都 >= 50）才评“上限”，50–59 是完整但最弱的一档。
    veto = track == "academic" and by_key["integrity"].score == 0
    incomplete = [key for key, _label, _hint in dims if by_key[key].score < 50]
    if veto and "integrity" not in incomplete:
        incomplete.append("integrity")
    complete = not incomplete
    if complete:
        grade, grade_label = grade_for(total, track)
        rejected = total < 50
        borderline = 50 <= total <= 52
        quartile: str | None = grade
    else:
        grade = "NA"
        grade_label = "待编辑部补全，暂不评级"
        # 不完整不等于退稿：由编辑部按作者原思路补全后直接进入评级/发布，
        # 不打回作者。rejected 只表示“完整稿但总分 <50”。
        rejected = veto
        borderline = False
        quartile = None
        # 诊断分不封顶：封顶只在“完整稿”里限制等级；不完整稿本就不评级。
        # 诚信一票否决仍保留 0 分，不能用“诊断”名义把造假稿救回来。
        total = 0.0 if veto else uncapped
    requires_rework = rejected
    payload: dict[str, object] = {
        "rubric_version": RUBRIC_VERSION,
        "track": track,
        "track_label": TRACK_LABELS[track],
        "article_type": profile_type,
        "article_type_label": PROFILE_LABELS.get(profile_type, "研究论文"),
        "score": total,
        "uncapped_score": uncapped,
        "cap": cap,
        "cap_notes": cap_notes,
        "grade": grade,
        "grade_label": grade_label,
        "quartile": quartile,
        "complete": complete,
        "incomplete_dimensions": incomplete,
        "completeness_note": (
            "五维完整，进入上限评审"
            if complete
            else "存在未交付维度（<50）：由编辑部按原思路补全，补全后再评级；不打回作者"
        ),
        "editorial_completion_required": (not complete) and not veto,
        "completion_owner": "editorial" if ((not complete) and not veto) else None,
        "breakdown": breakdown,
        "integrity_veto": veto,
        "overridden": overridden,
        "rejected": rejected,
        "borderline": borderline,
        "requires_rework": requires_rework,
    }
    if metrics is not None:
        payload["auto_precheck"] = auto_precheck(metrics)
    return payload


def rubric_payload() -> dict[str, object]:
    """公开口径：审稿人、作者、外部 AI 都用这一份。"""
    return {
        "version": RUBRIC_VERSION,
        "model": "五维双赛道百分制；每维必须附理由与正文证据",
        "tracks": {
            "academic": {
                "label": TRACK_LABELS["academic"],
                "dimensions": [
                    {
                        "key": k,
                        "label": label,
                        "hint": h,
                        "max_score": 100,
                        "weight": WEIGHTS["academic"][k],
                    }
                    for k, label, h in ACADEMIC_DIMENSIONS
                ],
                "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS["academic"]],
            },
            "absurd": {
                "label": TRACK_LABELS["absurd"],
                "dimensions": [
                    {
                        "key": k,
                        "label": label,
                        "hint": h,
                        "max_score": 100,
                        "weight": WEIGHTS["absurd"][k],
                    }
                    for k, label, h in ABSURD_DIMENSIONS
                ],
                "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS["absurd"]],
            },
        },
        "dimensions": [
            {
                "key": k,
                "label": label,
                "hint": h,
                "max_score": 100,
                "weight": WEIGHTS["academic"][k],
            }
            for k, label, h in ACADEMIC_DIMENSIONS
        ],
        "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS["academic"]],
        "profiles": {
            name: {"label": PROFILE_LABELS[name], "weights": weights, "track": "academic"}
            for name, weights in PROFILES.items()
        },
        "grades": [
            {"code": code, "label": label, "min": low, "max": high}
            for code, label, low, high in GRADE_BANDS
        ],
        "quartiles": {
            "T1": "90–100 顶刊级（95+ 为范本）",
            "Q1": "80–89 一区",
            "Q2": "70–79 二区",
            "Q3": "60–69 三区",
            "Q4": "50–59 四区",
            "R": "0–49 退稿，不入区",
        },
        "required_sections": list(REQUIRED_SECTIONS),
        "profile_sections": {k: list(v) for k, v in PROFILE_SECTIONS.items()},
        "min_references": MIN_REFERENCES,
        "length_tiers": {
            k: {"short": v[0], "medium": v[1], "long": v[2]} for k, v in LENGTH_TIERS.items()
        },
        "abstract_band": [ABSTRACT_MIN, ABSTRACT_MAX],
        "evidence_required": "每个维度必须给出 ≥8 字的正文证据（章节/段落/图表/引用编号/链接），只写分数或只写评语不受理",
        "integrity_veto": "学术赛道 integrity 维度 0 分 → 总分归零（学术不端一票否决）",
        "gates": [
            "任一维度 < 60 → 总分封顶 79（不进一区/顶刊）",
            "任一维度 < 50 → 总分封顶 59（不进三区及以上）",
            "两项及以上维度 < 50 → 总分封顶 49（退稿）",
            "学术赛道论证 < 50 → 总分封顶 59",
            "荒诞赛道自洽 < 50 → 总分封顶 59；执行 < 50 → 总分封顶 69",
        ],
        "rejected_below": 50,
        "rejected_action": "总分低于 50 分为退稿，不入区，必须打回审稿人补审或要求作者修改",
        "borderline_band": [50, 52],
        "borderline_action": "50–52 分为四区边缘稿，可发表但 payload 标记 borderline 提示编辑谨慎",
    }


__all__ = [
    "ABSTRACT_MAX",
    "ABSTRACT_MIN",
    "ABSURD_DIMENSIONS",
    "ABSURD_DIMENSION_LABELS",
    "ACADEMIC_DIMENSIONS",
    "DIMENSIONS",
    "DIMENSIONS_BY_TRACK",
    "DIMENSION_HINTS",
    "DIMENSION_LABELS",
    "GRADE_BANDS",
    "LENGTH_TIERS",
    "MIN_REFERENCES",
    "PROFILES",
    "PROFILE_LABELS",
    "PROFILE_SECTIONS",
    "REQUIRED_SECTIONS",
    "RUBRIC_VERSION",
    "SCORE_ANCHORS",
    "TRACK_LABELS",
    "WEIGHTS",
    "DimensionScore",
    "PaperMetrics",
    "auto_precheck",
    "dimensions_for",
    "evaluate",
    "grade_for",
    "rubric_payload",
    "weights_for",
]
