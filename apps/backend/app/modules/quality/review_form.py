"""审稿评分表单：把七个维度落成审稿人逐条可勾的检查项。

设计意图
--------
只给审稿人一个 0–5 滑杆是不够的——同一篇稿子，手松的审稿人给 4，
手紧的给 2，编辑部无从判断谁对。所以每个维度下面挂**具体的检查问题**：

- 检查项是**事实性问题**（"是否报告了样本量"），不是感受性问题
  （"你觉得方法好吗"）。事实性问题不同人答得一致。
- 每个维度至少 2 项，且必须全部作答才能提交——漏答会让"没检查"
  看起来像"检查了但没问题"。
- 检查项的答案（是/否/不适用）直接映射到该维度的建议分，审稿人可以
  覆盖建议分，但**必须写理由**（见 ``rubric.DimensionScore``）。

这套表单同时是给 AI 的输入规格：``prompt_payload`` 输出的 JSON 结构
就是要求外部模型返回的结构，配合 ``docs/quality-rubric-v2.md`` 里的
判分说明，能让不同 AI 对同一篇稿子得出接近的结论（见
``tests/test_quality_review_form.py`` 的稳定性用例）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.quality.rubric import (
    DIMENSION_HINTS,
    DIMENSION_LABELS,
    DIMENSIONS,
    SCORE_ANCHORS,
)


@dataclass(frozen=True)
class CheckItem:
    """一个事实性检查项。"""

    key: str
    dimension: str
    question: str
    # 权重：关键项（如"是否报告样本量"）比次要项更影响建议分
    weight: int = 1


CHECK_ITEMS: tuple[CheckItem, ...] = (
    # --- 问题价值 ---
    CheckItem("q_specific", "problem", "研究问题是否被明确表述为可回答的问题（而非泛泛的主题）？", 2),
    CheckItem("q_gap", "problem", "是否说明了既有研究为何未能回答该问题？", 2),
    CheckItem("q_significance", "problem", "是否说明了回答该问题的意义（理论或实践）？"),
    # --- 论证链 ---
    CheckItem("a_premise", "argument", "每个关键结论是否都有明确的前提支撑？", 2),
    CheckItem("a_nojump", "argument", "论证过程中是否存在未交代的跳跃（从 A 直接到 C）？", 2),
    CheckItem("a_counter", "argument", "是否讨论了与自身结论相反的解释或证据？", 2),
    CheckItem("a_circular", "argument", "是否存在循环论证（用结论证明前提）？"),
    # --- 方法透明度 ---
    CheckItem("m_data", "method", "数据来源与获取方式是否交代清楚？", 2),
    CheckItem("m_sample", "method", "样本量、抽样方式与筛选标准是否报告？", 2),
    CheckItem("m_params", "method", "关键参数、超参数或编码规则是否给出？", 2),
    CheckItem("m_random", "method", "随机性处理（种子、重复次数）是否说明？"),
    CheckItem("m_failure", "method", "失败案例或异常结果是否报告？"),
    # --- 证据强度 ---
    CheckItem("e_support", "evidence", "结论的强度是否与证据强度匹配（弱证据不下强结论）？", 2),
    CheckItem("e_causal", "evidence", "是否把相关性误述为因果？", 2),
    CheckItem("e_n", "evidence", "样本量是否足以支撑所下的结论？", 2),
    CheckItem("e_stats", "evidence", "统计检验（如适用）是否恰当报告效应量与不确定性？"),
    # --- 创新与定位 ---
    CheckItem("n_position", "novelty", "是否说清本工作相对既有研究的位置与增量？", 2),
    CheckItem("n_claim", "novelty", "创新性主张是否被正文内容支撑（而非仅在摘要宣称）？", 2),
    # --- 学术诚信 ---
    CheckItem("i_verifiable", "integrity", "引用是否真实可核（抽查可定位到原文）？", 3),
    CheckItem("i_data", "integrity", "数据与代码可用性声明是否给出且可执行？", 2),
    CheckItem("i_contrib", "integrity", "作者贡献（CRediT）与利益冲突声明是否完整？", 2),
    CheckItem("i_ethics", "integrity", "涉及人类/动物被试时是否有伦理审批说明？"),
    # --- 表达与结构 ---
    CheckItem("p_structure", "presentation", "结构是否让读者能按顺序理解研究？"),
    CheckItem("p_figures", "presentation", "图表是否自解释（标题、坐标轴、单位、图注齐全）？"),
    CheckItem("p_language", "presentation", "语言是否清晰到不需要反复重读才能理解？"),
)

CHECK_ITEMS_BY_DIMENSION: dict[str, tuple[CheckItem, ...]] = {
    key: tuple(item for item in CHECK_ITEMS if item.dimension == key) for key, _, _ in DIMENSIONS
}

# 答案枚举：no 记 0 分，partial 记半分，yes 记满分，na 不计入分母。
ANSWER_VALUES: dict[str, float] = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def suggest_dimension_score(answers: dict[str, str], dimension: str) -> float:
    """把检查项答案折算成该维度的建议分（0–5）。

    只作**建议**：审稿人可以覆盖，但覆盖必须写理由。这样既保留了
    一致性（大多数人直接采纳建议分），又保留了专业判断的空间
    （确有理由时可以偏离，且偏离本身可审计）。

    ``na``（不适用）从分母里剔除——一篇纯理论文章没有"样本量"，
    强制答 no 会把方法分错误地压低。
    """
    items = CHECK_ITEMS_BY_DIMENSION.get(dimension, ())
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
        # 全部不适用：该维度对这篇稿子不构成区分，给中间偏上（3 分），
        # 避免"不适用"被当成"零分"。
        return 3.0
    return round(5.0 * earned / total_weight, 2)


def score_answers(answers: dict[str, str]) -> dict[str, dict[str, object]]:
    """对全部七个维度给出建议分与检查项明细。"""
    out: dict[str, dict[str, object]] = {}
    for key, label, hint in DIMENSIONS:
        items = CHECK_ITEMS_BY_DIMENSION.get(key, ())
        out[key] = {
            "label": label,
            "hint": hint,
            "suggested_score": suggest_dimension_score(answers, key),
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


def form_payload() -> dict[str, object]:
    """公开表单定义：审稿页据此渲染，外部 AI 据此作答。"""
    return {
        "dimensions": [
            {
                "key": key,
                "label": label,
                "hint": hint,
                "items": [
                    {"key": i.key, "question": i.question, "weight": i.weight}
                    for i in CHECK_ITEMS_BY_DIMENSION.get(key, ())
                ],
            }
            for key, label, hint in DIMENSIONS
        ],
        "answers": [
            {"value": "yes", "label": "是"},
            {"value": "partial", "label": "部分"},
            {"value": "no", "label": "否"},
            {"value": "na", "label": "不适用"},
        ],
        "score_anchors": [{"score": s, "meaning": m} for s, m in SCORE_ANCHORS],
    }


def prompt_payload(article_type: str = "research") -> dict[str, object]:
    """给外部 AI 的完整判分规格（JSON）。

    包含：维度定义、检查项、0–5 锚点、画像权重、等级带、输出格式要求。
    目标是让不同模型对同一篇稿子的总分差异控制在 ±5 分以内——靠的是
    把"判断"拆成"逐条事实核查 + 固定的加权规则"，而不是让模型直接
    凭感觉给一个总分。
    """
    from app.modules.quality.rubric import PROFILES, PROFILE_LABELS, RUBRIC_VERSION

    return {
        "rubric_version": RUBRIC_VERSION,
        "task": "按下列检查项逐条作答，再按固定权重计算总分。禁止跳过检查项。",
        "article_type": article_type,
        "article_type_label": PROFILE_LABELS.get(article_type, "研究论文"),
        "weights": PROFILES.get(article_type, PROFILES["research"]),
        "form": form_payload(),
        "output_schema": {
            "answers": {"<check_item_key>": "yes | partial | no | na"},
            "dimensions": {
                "<dimension_key>": {
                    "score": "0-5 的整数或半分",
                    "reason": "必填：为什么给这个分，引用正文具体位置",
                }
            },
            "summary": "150 字以内的总体判断",
        },
        "rules": [
            "逐条作答，不得跳过；确实不适用才填 na。",
            "每个维度必须给出 reason，且必须引用正文的具体证据。",
            "integrity 维度若发现编造数据或引用，直接给 0 分。",
            "总分由权重计算得出，不得自行调高或调低。",
            "总分与 D 级（<60）时，必须列出至少 3 条具体修改要求。",
        ],
    }


__all__ = [
    "ANSWER_VALUES",
    "CHECK_ITEMS",
    "CHECK_ITEMS_BY_DIMENSION",
    "CheckItem",
    "DIMENSION_HINTS",
    "DIMENSION_LABELS",
    "form_payload",
    "prompt_payload",
    "score_answers",
    "suggest_dimension_score",
]
