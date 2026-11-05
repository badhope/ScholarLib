"""RQS v4.0 评分口径测试。

四条核心承诺必须被这些用例锁死：
1. 权重每套合计 100，维度分为 0–100 百分制；
2. 分数确定（同样的维度分 → 同样的总分）；
3. 学术诚信一票否决（integrity=0 → 总分归零，不予发表）；
4. 16 档等级带（ABCDEF 全字母）连续无缝隙：<40 才 rejected，50–52 为 E- 边缘稿。
"""

from __future__ import annotations

from app.modules.quality.review_form import (
    CHECK_ITEMS,
    CHECK_ITEMS_BY_DIMENSION,
    form_payload,
    prompt_payload,
    score_answers,
    suggest_dimension_score,
)
from app.modules.quality.rubric import (
    DIMENSIONS,
    GRADE_BANDS,
    PROFILES,
    DimensionScore,
    PaperMetrics,
    auto_precheck,
    evaluate,
    grade_for,
    rubric_payload,
)

_ALL_KEYS = tuple(k for k, _, _ in DIMENSIONS)


def _scores(value: float = 80) -> list[DimensionScore]:
    return [DimensionScore(k, value, "理由：正文第 3 节可核") for k in _ALL_KEYS]


def test_profile_weights_all_sum_to_100() -> None:
    for name, weights in PROFILES.items():
        assert sum(weights.values()) == 100, name
        # 每个画像都必须覆盖全部七个维度
        assert set(weights) == set(_ALL_KEYS), name


def test_argument_carries_most_weight_in_research() -> None:
    """论证链是学术写作的核心失败点，权重必须最高。"""
    w = PROFILES["research"]
    assert w["argument"] == max(w.values())
    # 形式类维度必须被压低，否则评分又会退化成"格式体检"
    assert w["presentation"] < w["argument"]
    assert w["presentation"] <= 10


def test_essay_profile_weights_argument_not_method() -> None:
    """随笔不靠数据取胜，方法权重应显著低于论证。"""
    assert PROFILES["essay"]["argument"] > PROFILES["essay"]["method"]
    assert PROFILES["essay"]["method"] < PROFILES["research"]["method"]


def test_full_marks_scores_100() -> None:
    result = evaluate(_scores(100))
    assert result["score"] == 100.0
    assert result["grade"] == "A+"


def test_all_zero_scores_zero() -> None:
    result = evaluate(_scores(0))
    assert result["score"] == 0.0
    assert result["grade"] == "F"
    assert result["rejected"] is True
    assert result["requires_rework"] is True


def test_integrity_veto_forces_rejected() -> None:
    """integrity=0 时，即使其他维度满分也必须总分归零、不予发表。"""
    scores = [DimensionScore(k, 100, "其余维度满分") for k in _ALL_KEYS if k != "integrity"]
    scores.append(DimensionScore("integrity", 0, "发现引用编造"))
    result = evaluate(scores)
    assert result["integrity_veto"] is True
    assert result["score"] == 0.0
    assert result["grade"] == "F"
    assert result["rejected"] is True
    assert result["requires_rework"] is True


def test_missing_dimension_raises() -> None:
    """漏填维度必须报错，不能当成 0 分。"""
    import pytest

    partial = _scores(80)[:-1]
    with pytest.raises(ValueError, match="Missing dimension"):
        evaluate(partial)


def test_reason_is_required() -> None:
    import pytest

    with pytest.raises(ValueError, match="reason is required"):
        DimensionScore("problem", 80, "   ")


def test_score_out_of_range_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="score must be 0–100"):
        DimensionScore("problem", 101, "越界")


def test_grade_bands_tolerate_fractions() -> None:
    """分数带按「下限」降序匹配，小数分必须落在正确档（历史 bug 防回归）。"""
    assert grade_for(96.9) == ("A", "顶尖")
    assert grade_for(79.5) == ("C+", "中等")
    assert grade_for(71.0) == ("C", "中等")
    assert grade_for(59.9) == ("E+", "基础")
    assert grade_for(40.0) == ("F", "及格")


def test_grade_bands_boundaries_v4() -> None:
    """v4.0 等级带边界：A+ 对标顶刊极难达到，40 分是及格/不合格的分水岭。"""
    assert grade_for(97) == ("A+", "典范")
    assert grade_for(96.9) == ("A", "顶尖")
    assert grade_for(92.9) == ("A-", "优秀")
    assert grade_for(49.9) == ("F", "及格")
    assert grade_for(56) == ("E+", "基础")
    assert grade_for(39.9) == ("F", "不合格")


def test_rejected_only_below_40() -> None:
    """F（40–49）及格可发表；<40 才 rejected；50–52 是 E- 边缘稿。"""
    assert evaluate(_scores(100), override_total=39.9)["rejected"] is True
    result_40 = evaluate(_scores(100), override_total=40)
    assert result_40["rejected"] is False
    assert result_40["grade"] == "F"
    assert result_40["requires_rework"] is False
    assert evaluate(_scores(100), override_total=49.9)["grade"] == "F"
    borderline = evaluate(_scores(100), override_total=51)
    assert borderline["borderline"] is True
    assert borderline["rejected"] is False
    assert evaluate(_scores(100), override_total=49.9)["borderline"] is False
    assert evaluate(_scores(100), override_total=52.5)["borderline"] is False


def test_grade_bands_contiguous() -> None:
    """16 档分数带必须连续无缝隙：上一档 min = 下一档 max + 1（向下）。"""
    ordered = list(GRADE_BANDS)
    for upper, lower in zip(ordered, ordered[1:]):
        assert upper[2] == lower[3] + 1, f"{upper[0]} 与 {lower[0]} 之间有缝隙"
    assert ordered[0][2] == 97 and ordered[0][3] == 100
    assert ordered[-1][2] == 40
    # 字母必须 ABCDEF 全覆盖
    letters = {c[0] for c in ordered}
    assert letters == set("ABCDEF")


def test_same_scores_same_total_deterministic() -> None:
    """确定性：同样的输入必须得到同样的总分（评分可复算）。"""
    a = evaluate(_scores(80))["score"]
    b = evaluate(_scores(80))["score"]
    assert a == b


def test_override_records_flag() -> None:
    result = evaluate(_scores(80), override_total=88.0)
    assert result["score"] == 88.0
    assert result["overridden"] is True


def test_auto_precheck_flags_missing_references() -> None:
    issues = auto_precheck(PaperMetrics(article_type="research", references=0, abstract_chars=300))
    assert any(i["level"] == "blocker" and "参考文献" in i["message"] for i in issues)


def test_auto_precheck_flags_missing_abstract() -> None:
    issues = auto_precheck(PaperMetrics(abstract_chars=0, references=20))
    assert any("摘要" in i["message"] for i in issues)


def test_rubric_payload_shape() -> None:
    payload = rubric_payload()
    assert payload["version"] == "4.0"
    assert len(payload["dimensions"]) == 7
    assert set(payload["profiles"]) == set(PROFILES)
    assert [g["code"] for g in payload["grades"]] == [
        "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
        "D+", "D", "D-", "E+", "E", "E-", "F",
    ]
    assert "integrity_veto" in payload
    assert "rejected_action" in payload
    assert "borderline_action" in payload
    # v3.0 移除了没人看得懂的换算系数
    assert "coefficient_formula" not in payload
    assert len(payload["score_anchors"]) == 7


# --- 审稿表单 -------------------------------------------------------------


def test_every_dimension_has_check_items() -> None:
    """每个维度都必须有可勾的检查项，否则该维度无法被一致地评。"""
    for key in _ALL_KEYS:
        assert CHECK_ITEMS_BY_DIMENSION[key], f"{key} 没有检查项"


def test_presentation_has_no_figure_check() -> None:
    """v3.0：图表格式不是学术质量，p_figures 已移除（走 auto_precheck warning）。"""
    keys = {item.key for item in CHECK_ITEMS_BY_DIMENSION["presentation"]}
    assert keys == {"p_structure", "p_language"}
    assert all(item.key != "p_figures" for item in CHECK_ITEMS)


def test_all_yes_suggests_full_marks() -> None:
    answers = {item.key: "yes" for item in CHECK_ITEMS}
    for key in _ALL_KEYS:
        assert suggest_dimension_score(answers, key) == 100.0


def test_all_no_suggests_zero() -> None:
    answers = {item.key: "no" for item in CHECK_ITEMS}
    for key in _ALL_KEYS:
        assert suggest_dimension_score(answers, key) == 0.0


def test_na_excluded_from_denominator() -> None:
    """全部不适用 → 中间偏上分（60），而不是 0（不能把"不适用"当"很差"）。"""
    items = CHECK_ITEMS_BY_DIMENSION["method"]
    answers = {item.key: "na" for item in items}
    assert suggest_dimension_score(answers, "method") == 60.0


def test_missing_answer_counts_as_unchecked() -> None:
    """漏答按 0 计入分母：漏答就是没检查。"""
    items = CHECK_ITEMS_BY_DIMENSION["integrity"]
    answers = {items[0].key: "yes"}  # 只答第一项
    score = suggest_dimension_score(answers, "integrity")
    assert score < 100.0


def test_form_payload_covers_all_dimensions() -> None:
    payload = form_payload()
    assert len(payload["dimensions"]) == 7
    for dim in payload["dimensions"]:
        assert dim["items"], dim["key"]


def test_prompt_payload_has_output_schema_and_rules() -> None:
    payload = prompt_payload("research")
    assert payload["rubric_version"] == "4.0"
    assert "output_schema" in payload
    assert len(payload["rules"]) >= 4
    assert payload["weights"] == PROFILES["research"]


def test_prompt_stability_same_answers_same_scores() -> None:
    """同一组答案折算出的维度分必须完全一致（AI 可复现的前提）。"""
    answers = {item.key: "partial" for item in CHECK_ITEMS}
    a = score_answers(answers)
    b = score_answers(answers)
    assert {k: v["suggested_score"] for k, v in a.items()} == {
        k: v["suggested_score"] for k, v in b.items()
    }
