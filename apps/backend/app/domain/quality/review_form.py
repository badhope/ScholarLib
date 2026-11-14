"""审稿评分表单：五维双赛道，每个维度落成审稿人逐条可勾的检查项。

设计意图
--------
只给审稿人一个孤立的滑杆是不够的——同一篇稿子，手松的审稿人给 85，
手紧的给 60，编辑部无从判断谁对。所以每个维度下面挂**具体的检查问题**：

- 检查项是**事实性问题**（“是否报告了样本量”），不是感受性问题
  （“你觉得方法好吗”）。事实性问题不同人答得一致。
- 每个维度至少 3 项，且必须全部作答才能提交——漏答会让“没检查”
  看起来像“检查了但没问题”。
- 检查项的答案（是/部分/否/不适用）只折算成**建议分**，审稿人可以覆盖，
  但必须写理由 + 正文证据（见 ``rubric.DimensionScore``）。v5.0 起证据是
  硬性字段：没有证据的分数不进入计算。
- 学术/荒诞两套检查项完全分开：荒诞稿不审“伦理审批”“样本量”，改审
  “设定是否真荒诞、规则是否自洽、梗是否有出处”。

这套表单同时是给 AI 的输入规格：``prompt_payload`` 输出的 JSON 结构
就是要求外部模型返回的结构。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.quality.rubric import (
    DIMENSION_HINTS,
    DIMENSION_LABELS,
    SCORE_ANCHORS,
    TRACK_LABELS,
    dimensions_for,
)


@dataclass(frozen=True)
class CheckItem:
    """一个事实性检查项。"""

    key: str
    dimension: str
    question: str
    weight: int = 1


ACADEMIC_CHECK_ITEMS: tuple[CheckItem, ...] = (
    # --- 选题与真问题 ---
    CheckItem("q_specific", "question", "研究问题是否被写成可回答的问题（而非泛泛的主题）？", 2),
    CheckItem("q_gap", "question", "是否说明了既有研究为何未能回答该问题？", 2),
    CheckItem("q_significance", "question", "是否说明回答该问题的理论或实践意义？"),
    CheckItem("q_novel", "question", "创新增量是否被具体说出（相对哪一篇、补了哪一块）？", 2),
    # --- 论证与自洽 ---
    CheckItem("a_premise", "argument", "每个关键结论是否都有明确前提支撑？", 2),
    CheckItem("a_nojump", "argument", "是否避免了未交代的跳跃（从 A 直接到 C）？", 2),
    CheckItem("a_counter", "argument", "是否处理了与自身结论相反的解释或证据？", 2),
    CheckItem("a_circular", "argument", "是否避免了循环论证（用结论证明前提）？"),
    # --- 方法与可复现 ---
    CheckItem("m_data", "method", "数据来源与获取方式是否交代清楚？", 2),
    CheckItem("m_sample", "method", "样本量、抽样方式与筛选标准是否报告？", 2),
    CheckItem("m_params", "method", "关键参数、超参数或编码规则是否给出？", 2),
    CheckItem("m_failure", "method", "失败案例或异常结果是否报告？"),
    # --- 证据与结论 ---
    CheckItem("e_support", "evidence", "结论强度是否与证据强度匹配（弱证据不下强结论）？", 2),
    CheckItem("e_causal", "evidence", "是否避免了把相关性写成因果？", 2),
    CheckItem("e_n", "evidence", "样本量或材料规模是否足以支撑所下结论？", 2),
    CheckItem("e_stats", "evidence", "统计检验（如适用）是否报告效应量与不确定性？"),
    # --- 规范与诚信 ---
    CheckItem("i_verifiable", "integrity", "引用是否真实可核（抽查能定位到原文）？", 3),
    CheckItem("i_data", "integrity", "数据/代码可用性声明是否给出且可执行？", 2),
    CheckItem("i_contrib", "integrity", "作者贡献、利益冲突与资助声明是否完整？", 2),
    CheckItem("i_ethics", "integrity", "涉及人类/动物被试时是否给出伦理审批？"),
)

ABSURD_CHECK_ITEMS: tuple[CheckItem, ...] = (
    # --- 荒诞设定与原创 ---
    CheckItem("x_new", "concept", "设定是否真的荒诞且新，不是把普通吐槽换个说法？", 2),
    CheckItem("x_nonsense", "concept", "“无中生有”的部分是否有明确边界（读者知道哪里在胡说）？", 2),
    CheckItem("x_hook", "concept", "是否有一个能复述给别人的核心记忆点？", 2),
    # --- 内部自洽 ---
    CheckItem("x_rules", "coherence", "设定内的规则是否被明确交代？", 2),
    CheckItem("x_consistency", "coherence", "前后是否不打架（人物、时间、规则、数字一致）？", 3),
    CheckItem("x_ending", "coherence", "结尾是否收得住，而不是写不下去就停？", 2),
    # --- 一本正经的执行 ---
    CheckItem(
        "x_format", "execution", "是否用完整结构（摘要/方法/结果或叙事推进）把荒诞当正事写？", 2
    ),
    CheckItem("x_serious", "execution", "语气是否稳得住，不靠作者自己跳出来解释“这很好笑”？", 2),
    CheckItem("x_progress", "execution", "是否有推进，而不是同一层级的段子反复堆叠？", 2),
    # --- 材料与梗的可核查 ---
    CheckItem(
        "x_source", "material", "引用的梗、案例、数据是否给出可核出处（链接/作品/时间）？", 2
    ),
    CheckItem("x_rule_clarity", "material", "自造数据/规则是否说明是自造，而不是冒充真实来源？", 2),
    CheckItem("x_quote", "material", "引用原文/台词/论文是否准确，没有被张冠李戴？", 2),
    # --- 文风与节奏 ---
    CheckItem("x_rhythm", "voice", "长短句与段落节奏是否有控制，不是一路平推？", 2),
    CheckItem("x_punch", "voice", "包袱是否有落点，笑点不是靠括号解释？", 2),
    CheckItem("x_word", "voice", "是否避免了口水话、重复词和明显凑字数？"),
)

CHECK_ITEMS_BY_TRACK: dict[str, tuple[CheckItem, ...]] = {
    "academic": ACADEMIC_CHECK_ITEMS,
    "absurd": ABSURD_CHECK_ITEMS,
}

# 兼容旧导入：默认学术赛道。
CHECK_ITEMS = ACADEMIC_CHECK_ITEMS
CHECK_ITEMS_BY_DIMENSION: dict[str, tuple[CheckItem, ...]] = {
    key: tuple(item for item in ACADEMIC_CHECK_ITEMS if item.dimension == key)
    for key, _, _ in dimensions_for("academic")
}

ANSWER_VALUES: dict[str, float] = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def _items_for(track: str, dimension: str) -> tuple[CheckItem, ...]:
    return tuple(
        item
        for item in CHECK_ITEMS_BY_TRACK.get(track, ACADEMIC_CHECK_ITEMS)
        if item.dimension == dimension
    )


def suggest_dimension_score(
    answers: dict[str, str], dimension: str, track: str = "academic"
) -> float:
    """把检查项答案折算成该维度的建议分（0–100 百分制）。

    只作**建议**：审稿人可以覆盖，但覆盖必须写理由与证据。``na`` 从分母里
    剔除——一篇纯理论文章没有“样本量”，强制答 no 会把方法分错误地压低。
    """
    items = _items_for(track, dimension)
    if not items:
        return 0.0
    earned = 0.0
    total_weight = 0
    for item in items:
        ans = answers.get(item.key)
        if ans is None:
            # 漏答按 0 计而不是跳过：漏答就是没检查。
            total_weight += item.weight
            continue
        if ans == "na":
            continue
        total_weight += item.weight
        earned += item.weight * ANSWER_VALUES.get(ans, 0.0)
    if total_weight == 0:
        # 全部不适用：该维度对这篇稿子不构成区分，给中间偏上（60 分），
        # 避免“不适用”被当成“零分”。
        return 60.0
    return round(100.0 * earned / total_weight, 1)


def score_answers(answers: dict[str, str], track: str = "academic") -> dict[str, dict[str, object]]:
    """对全部五个维度给出建议分与检查项明细。"""
    track = track if track in CHECK_ITEMS_BY_TRACK else "academic"
    out: dict[str, dict[str, object]] = {}
    for key, label, hint in dimensions_for(track):
        items = _items_for(track, key)
        out[key] = {
            "label": label,
            "hint": hint,
            "suggested_score": suggest_dimension_score(answers, key, track),
            "items": [
                {
                    "key": item.key,
                    "question": item.question,
                    "weight": item.weight,
                    "answer": answers.get(item.key),
                }
                for item in items
            ],
        }
    return out


def form_payload(track: str = "academic") -> dict[str, object]:
    """公开表单定义：审稿页据此渲染，外部 AI 据此作答。"""
    track = track if track in CHECK_ITEMS_BY_TRACK else "academic"
    return {
        "track": track,
        "track_label": TRACK_LABELS[track],
        "dimensions": [
            {
                "key": key,
                "label": label,
                "hint": hint,
                "items": [
                    {"key": i.key, "question": i.question, "weight": i.weight}
                    for i in _items_for(track, key)
                ],
            }
            for key, label, hint in dimensions_for(track)
        ],
        "answers": [
            {"value": "yes", "label": "是"},
            {"value": "partial", "label": "部分"},
            {"value": "no", "label": "否"},
            {"value": "na", "label": "不适用"},
        ],
        "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS[track]],
        "evidence_policy": {
            "required": True,
            "min_chars": 8,
            "what_counts": "章节/段落/图号/表号/引用编号/公开链接；只写“感觉”“整体不错”不算证据",
        },
        # 荒诞指数是审核必填事实（0–10 风格坐标），不进总分、不参与排序。
        "absurdity_index": {
            "required": True,
            "range": [0, 10],
            "definition": "风格坐标：这篇内容站在『学术↔吐槽』光谱的哪里。0 = 纯学术，"
            "2.5–7.5 = 娱乐向，≥7.5 = 吐槽向。描述风格，不评价好坏。",
            "bands": [
                {"min": 0, "max": 2.5, "label": "学术"},
                {"min": 2.5, "max": 7.5, "label": "娱乐"},
                {"min": 7.5, "max": 10, "label": "吐槽"},
            ],
            "goes_into_score": False,
            "used_for": "content_category 判定（编辑部显式指定 > 荒诞指数折算 > 类型兜底）",
        },
    }


def prompt_payload(article_type: str = "research", track: str = "academic") -> dict[str, object]:
    """给外部 AI 的完整判分规格（JSON）。

    包含：赛道维度、检查项、0–100 锚点、权重、分区门槛、输出格式要求。
    目标是让不同模型对同一篇稿子的总分差异控制在 ±5 分以内——靠的是
    把“判断”拆成“逐条事实核查 + 固定加权 + 证据定位”，而不是凭感觉。
    """
    from app.domain.quality.rubric import (
        PROFILE_LABELS,
        PROFILES,
        RUBRIC_VERSION,
        TRACK_LABELS,
        weights_for,
    )

    track = track if track in CHECK_ITEMS_BY_TRACK else "academic"
    return {
        "rubric_version": RUBRIC_VERSION,
        "task": "按下列检查项逐条作答，再按固定权重计算总分。禁止跳过检查项；每个维度必须给出正文证据。",
        "track": track,
        "track_label": TRACK_LABELS[track],
        "article_type": article_type,
        "article_type_label": PROFILE_LABELS.get(article_type, "研究论文"),
        "weights": weights_for(track)
        if track == "absurd"
        else PROFILES.get(article_type, PROFILES["research"]),
        "form": form_payload(track),
        "output_schema": {
            "answers": {"<check_item_key>": "yes | partial | no | na"},
            "dimensions": {
                "<dimension_key>": {
                    "score": "0-100 的整数",
                    "reason": "必填：为什么给这个分",
                    "evidence": "必填：引用正文具体位置（章节/段落/图号/表号/引用编号/链接）",
                }
            },
            "summary": "150 字以内的总体判断",
            "recommendation": "accept | minor_revision | major_revision | reject",
        },
        "rules": [
            "逐条作答，不得跳过；确实不适用才填 na。",
            "每个维度必须给出 reason 与 evidence；没有证据的维度分不进入总分。",
            "学术赛道：integrity 维度若发现编造数据或引用，直接给 0 分并总分归零。",
            "荒诞赛道：允许无中生有；但设定内规则必须自洽，梗与材料必须可核或明确标注自造。",
            "总分由权重计算得出，不得自行调高或调低；触发任一硬门槛时按门槛封顶。",
            "总分低于 50（退稿）时，必须列出至少 3 条具体修改要求。",
        ],
    }


__all__ = [
    "ABSURD_CHECK_ITEMS",
    "ACADEMIC_CHECK_ITEMS",
    "ANSWER_VALUES",
    "CHECK_ITEMS",
    "CHECK_ITEMS_BY_DIMENSION",
    "CHECK_ITEMS_BY_TRACK",
    "DIMENSION_HINTS",
    "DIMENSION_LABELS",
    "CheckItem",
    "form_payload",
    "prompt_payload",
    "score_answers",
    "suggest_dimension_score",
]
