"""RQS v5.0 评分口径测试。

锁死六条核心承诺：
1. 两条赛道各五维、各套权重合计 100；
2. 每个维度必须同时有分数、理由、正文证据；
3. 学术诚信一票否决；
4. 分区边界：90 顶刊、80/70/60/50 一/二/三/四区、<50 退稿；
5. 硬门槛：任一维 <60 封顶 79、<50 封顶 59、两维 <50 封顶 49；
6. 荒诞赛道不套学术维度，自洽/执行各有独立封顶。
"""

from __future__ import annotations

import itertools

import pytest

from app.modules.quality.review_form import (
    ABSURD_CHECK_ITEMS,
    ACADEMIC_CHECK_ITEMS,
    CHECK_ITEMS,
    CHECK_ITEMS_BY_TRACK,
    form_payload,
    prompt_payload,
    score_answers,
    suggest_dimension_score,
)
from app.modules.quality.rubric import (
    GRADE_BANDS,
    WEIGHTS,
    DimensionScore,
    PaperMetrics,
    auto_precheck,
    dimensions_for,
    evaluate,
    grade_for,
    rubric_payload,
)

_ACADEMIC_KEYS = tuple(k for k, _, _ in dimensions_for("academic"))
_ABSURD_KEYS = tuple(k for k, _, _ in dimensions_for("absurd"))


def _scores(value: float = 80, track: str = "academic") -> list[DimensionScore]:
    keys = _ACADEMIC_KEYS if track == "academic" else _ABSURD_KEYS
    return [
        DimensionScore(k, value, "理由：正文第 3 节可核", "证据：第 3 节第 2 段与表 1")
        for k in keys
    ]


def test_track_weights_sum_to_100() -> None:
    for track, weights in WEIGHTS.items():
        assert sum(weights.values()) == 100, track
        assert set(weights) == set(k for k, _, _ in dimensions_for(track)), track


def test_absurd_track_has_different_dimensions() -> None:
    assert set(_ACADEMIC_KEYS).isdisjoint(set(_ABSURD_KEYS))
    assert len(_ACADEMIC_KEYS) == len(_ABSURD_KEYS) == 5


def test_academic_argument_has_highest_weight() -> None:
    w = WEIGHTS["academic"]
    assert w["argument"] == max(w.values())


def test_full_marks_scores_100() -> None:
    result = evaluate(_scores(100))
    assert result["score"] == 100.0
    assert result["grade"] == "T1+"


def test_all_zero_scores_zero() -> None:
    result = evaluate(_scores(0))
    assert result["score"] == 0.0
    assert result["complete"] is False
    assert result["grade"] == "NA"
    assert result["rejected"] is True
    assert result["editorial_completion_required"] is False


def test_integrity_veto_forces_zero() -> None:
    scores = [
        DimensionScore(k, 100, "其余维度满分", "证据：第 3 节")
        for k in _ACADEMIC_KEYS
        if k != "integrity"
    ]
    scores.append(DimensionScore("integrity", 0, "发现引用编造", "证据：参考文献[3]无法定位"))
    result = evaluate(scores)
    assert result["integrity_veto"] is True
    assert result["score"] == 0.0
    assert result["complete"] is False
    assert result["grade"] == "NA"
    assert result["rejected"] is True
    assert result["editorial_completion_required"] is False


def test_evidence_is_required() -> None:
    with pytest.raises(ValueError, match="evidence is required"):
        DimensionScore("question", 80, "问题成立", "太短")


def test_reason_is_required() -> None:
    with pytest.raises(ValueError, match="evidence requires a reason"):
        DimensionScore("question", 80, "   ", "证据：第 3 节第 2 段")


def test_missing_dimension_raises() -> None:
    partial = _scores(80)[:-1]
    with pytest.raises(ValueError, match="Missing dimension"):
        evaluate(partial)


def test_wrong_track_dimensions_raise() -> None:
    with pytest.raises(ValueError, match="Missing dimension"):
        evaluate(_scores(80), track="absurd")


def test_score_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="score must be 0–100"):
        DimensionScore("question", 101, "越界", "证据：第 3 节第 2 段")


def test_quartile_boundaries() -> None:
    assert grade_for(95) == ("T1+", "顶刊范本")
    assert grade_for(90) == ("T1", "顶刊级")
    assert grade_for(89.9) == ("Q1", "一区")
    assert grade_for(80) == ("Q1", "一区")
    assert grade_for(70) == ("Q2", "二区")
    assert grade_for(60) == ("Q3", "三区")
    assert grade_for(50) == ("Q4", "四区")
    assert grade_for(49.9) == ("R", "退稿")


def test_rejected_only_below_50() -> None:
    assert evaluate(_scores(100), override_total=49.9)["rejected"] is True
    result_50 = evaluate(_scores(100), override_total=50)
    assert result_50["rejected"] is False
    assert result_50["grade"] == "Q4"
    borderline = evaluate(_scores(100), override_total=51)
    assert borderline["borderline"] is True


def test_grade_bands_contiguous() -> None:
    ordered = list(GRADE_BANDS)
    for upper, lower in itertools.pairwise(ordered):
        assert upper[2] == lower[3] + 1, f"{upper[0]} 与 {lower[0]} 之间有缝隙"
    assert ordered[0][2] == 95 and ordered[0][3] == 100
    assert ordered[-1][2] == 0 and ordered[-1][3] == 49


def test_low_dimension_caps_at_79() -> None:
    scores = _scores(95)
    scores[1] = DimensionScore("argument", 55, "论证有跳跃", "证据：§2 第 4 段直接跳到结论")
    result = evaluate(scores)
    assert result["uncapped_score"] > 79
    assert result["score"] == 79.0
    assert result["grade"] == "Q2"


def test_one_dimension_below_50_is_incomplete_not_quartile() -> None:
    scores = _scores(95)
    scores[2] = DimensionScore("method", 45, "方法不可复现", "证据：§3 未报告样本量与参数")
    result = evaluate(scores)
    assert result["score"] == 85.0  # 诊断分不封顶，封顶只用于完整稿评级
    assert result["complete"] is False
    assert result["incomplete_dimensions"] == ["method"]
    assert result["grade"] == "NA"
    assert result["quartile"] is None


def test_two_dimensions_below_50_caps_at_49() -> None:
    scores = _scores(95)
    scores[2] = DimensionScore("method", 45, "方法不可复现", "证据：§3 未报告样本量")
    scores[3] = DimensionScore("evidence", 40, "证据不足", "证据：§4 仅 3 个样本")
    result = evaluate(scores)
    assert result["score"] == 74.0  # 诊断分不封顶
    assert result["complete"] is False
    assert result["grade"] == "NA"
    assert result["rejected"] is False
    assert result["editorial_completion_required"] is True


def test_absurd_coherence_gate() -> None:
    scores = _scores(95, track="absurd")
    scores[1] = DimensionScore("coherence", 45, "规则打架", "证据：第 2 节与第 5 节时间线冲突")
    result = evaluate(scores, track="absurd")
    assert result["score"] == 85.0  # 诊断分不封顶


def test_same_scores_same_total() -> None:
    a = evaluate(_scores(80))["score"]
    b = evaluate(_scores(80))["score"]
    assert a == b


def test_auto_precheck_flags_missing_references() -> None:
    issues = auto_precheck(PaperMetrics(article_type="research", references=0, abstract_chars=300))
    assert any(i["level"] == "blocker" and "参考文献" in i["message"] for i in issues)


def test_auto_precheck_flags_missing_abstract() -> None:
    issues = auto_precheck(PaperMetrics(abstract_chars=0, references=20))
    assert any("摘要" in i["message"] for i in issues)


def test_rubric_payload_shape() -> None:
    payload = rubric_payload()
    assert payload["version"] == "5.0"
    assert len(payload["dimensions"]) == 5
    assert set(payload["tracks"]) == {"academic", "absurd"}
    assert [g["code"] for g in payload["grades"]] == ["T1+", "T1", "Q1", "Q2", "Q3", "Q4", "R"]
    assert "integrity_veto" in payload
    assert "gates" in payload
    assert len(payload["score_anchors"]) == 7
    assert payload["rejected_below"] == 50


# --- 审稿表单 -------------------------------------------------------------


def test_every_dimension_has_check_items() -> None:
    for track, items in CHECK_ITEMS_BY_TRACK.items():
        for key, _, _ in dimensions_for(track):
            assert [i for i in items if i.dimension == key], f"{track}/{key} 没有检查项"


def test_academic_and_absurd_forms_are_separate() -> None:
    academic = form_payload("academic")
    absurd = form_payload("absurd")
    assert len(academic["dimensions"]) == 5
    assert len(absurd["dimensions"]) == 5
    assert academic["track"] == "academic"
    assert absurd["track"] == "absurd"
    assert {i["key"] for d in academic["dimensions"] for i in d["items"]}.isdisjoint(
        {i["key"] for d in absurd["dimensions"] for i in d["items"]}
    )


def test_all_yes_suggests_full_marks() -> None:
    answers = {item.key: "yes" for item in ACADEMIC_CHECK_ITEMS}
    for key in _ACADEMIC_KEYS:
        assert suggest_dimension_score(answers, key) == 100.0


def test_all_no_suggests_zero() -> None:
    answers = {item.key: "no" for item in ACADEMIC_CHECK_ITEMS}
    for key in _ACADEMIC_KEYS:
        assert suggest_dimension_score(answers, key) == 0.0


def test_na_excluded_from_denominator() -> None:
    items = [i for i in CHECK_ITEMS if i.dimension == "method"]
    answers = {item.key: "na" for item in items}
    assert suggest_dimension_score(answers, "method") == 60.0


def test_missing_answer_counts_as_unchecked() -> None:
    items = [i for i in CHECK_ITEMS if i.dimension == "integrity"]
    answers = {items[0].key: "yes"}
    assert suggest_dimension_score(answers, "integrity") < 100.0


def test_prompt_payload_has_output_schema_and_rules() -> None:
    payload = prompt_payload("research", "academic")
    assert payload["rubric_version"] == "5.0"
    assert payload["track"] == "academic"
    assert "output_schema" in payload
    assert "evidence" in payload["output_schema"]["dimensions"]["<dimension_key>"]
    assert len(payload["rules"]) >= 5
    assert payload["weights"] == WEIGHTS["academic"]


def test_prompt_stability_same_answers_same_scores() -> None:
    answers = {item.key: "partial" for item in ACADEMIC_CHECK_ITEMS}
    a = score_answers(answers, "academic")
    b = score_answers(answers, "academic")
    assert {k: v["suggested_score"] for k, v in a.items()} == {
        k: v["suggested_score"] for k, v in b.items()
    }
    absurd_answers = {item.key: "partial" for item in ABSURD_CHECK_ITEMS}
    c = score_answers(absurd_answers, "absurd")
    assert all(v["suggested_score"] == 50.0 for v in c.values())
