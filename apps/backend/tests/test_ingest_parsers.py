"""Unit tests for the BibTeX / RIS / CSV parsers (``ingest.parsers``).

The route-level tests in ``test_ingest.py`` cover the happy path through
HTTP. This file drives the parsers directly, because that is where the
awkward inputs live: a single bad entry inside an otherwise valid file
must not sink the whole import, and line numbers in ``ParseError`` must
stay accurate enough for a user to find the offending row.

Parsers are pure (``str -> (resources, errors)``), so no fixtures needed.
"""

from __future__ import annotations

import pytest

from app.domain.ingest.parsers import (
    _format_validation_error,
    _parse_year,
    _split_authors,
    _split_tags,
    parse_bibtex,
    parse_csv,
    parse_ris,
)

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def test_parse_year_variants() -> None:
    assert _parse_year(None) is None
    assert _parse_year("") is None
    assert _parse_year("   ") is None
    assert _parse_year("2024") == 2024
    assert _parse_year(2024) == 2024
    # BibTeX 里常见 "to appear" / "in press"，按未知年份处理而不是报错
    assert _parse_year("to appear") is None


def test_split_authors() -> None:
    assert _split_authors(None) == []
    assert _split_authors("") == []
    assert _split_authors("Alice and Bob") == ["Alice", "Bob"]
    # 空片段必须被丢弃，不能产出空作者名
    assert _split_authors("Alice and  and Bob") == ["Alice", "Bob"]


def test_split_tags_normalizes_commas_and_semicolons() -> None:
    assert _split_tags(None) == []
    assert _split_tags("a, b; c") == ["a", "b", "c"]
    assert _split_tags(" , ; ") == []


def test_format_validation_error_includes_field_path() -> None:
    from pydantic import BaseModel, ValidationError

    class Model(BaseModel):
        year: int

    try:
        Model(year="nope")
    except ValidationError as exc:
        message = _format_validation_error(exc)

    assert message.startswith("year:")
    assert "nope" not in message  # 只报字段与原因，不回显原始值


# ---------------------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------------------

_BIBTEX_OK = """
@article{key1,
  title = {A BibTeX Paper},
  author = {Alice A and Bob B},
  year = {2024},
  journal = { Journal of Testing },
  keywords = {alpha, beta},
  abstract = {An abstract.},
  doi = {10.1000/bibtex}
}
"""


def test_parse_bibtex_happy_path() -> None:
    resources, errors = parse_bibtex(_BIBTEX_OK)

    assert errors == []
    assert len(resources) == 1
    resource = resources[0]
    assert resource.title == "A BibTeX Paper"
    assert resource.authors == ["Alice A", "Bob B"]
    assert resource.year == 2024
    assert resource.venue == "Journal of Testing"
    assert resource.tags == ["alpha", "beta"]
    assert resource.doi == "10.1000/bibtex"


def test_parse_bibtex_venue_falls_back_to_booktitle() -> None:
    content = """
@inproceedings{key1,
  title = {Conference Paper},
  author = {Alice A},
  booktitle = { Proc. of Testing }
}
"""
    resources, errors = parse_bibtex(content)

    assert errors == []
    assert resources[0].venue == "Proc. of Testing"


def test_parse_bibtex_missing_title_or_authors_is_per_entry_error() -> None:
    content = """
@article{noTitle, author = {Alice A}}
@article{noAuthor, title = {T}}
@article{good, title = {OK}, author = {Alice A}}
"""
    resources, errors = parse_bibtex(content)

    # 坏条目不能带走好条目 —— 这是整条导入链路最重要的一条保证
    assert len(resources) == 1
    assert resources[0].title == "OK"
    assert len(errors) == 2
    assert [e.error for e in errors] == ["missing title", "missing authors"]
    # 行号是条目序号（1-based），供用户定位
    assert [e.line for e in errors] == [1, 2]


def test_parse_bibtex_malformed_content_yields_no_entries() -> None:
    """bibtexparser 是宽容解析器：畸形输入不抛异常，而是解析出 0 个条目。

    所以这里断言的是"不炸 + 不产出半成品"，而不是"报一条 parse error"。
    """
    for content in ("@article{unclosed, title = {", "@@@garbage@@@", "not bibtex at all"):
        resources, errors = parse_bibtex(content)

        assert resources == []
        assert errors == []


def test_parse_bibtex_parser_exception_is_reported() -> None:
    """真正的解析异常（非宽容场景）必须被包成 ParseError，而不是冒泡成 500。"""
    import bibtexparser as bibtexparser_mod

    def boom(*_a: object, **_kw: object) -> object:
        raise RuntimeError("parser exploded")

    original = bibtexparser_mod.loads
    bibtexparser_mod.loads = boom  # type: ignore[assignment]
    try:
        resources, errors = parse_bibtex("@article{a, title={T}}")
    finally:
        bibtexparser_mod.loads = original  # type: ignore[assignment]

    assert resources == []
    assert len(errors) == 1
    assert errors[0].line == 1
    assert "BibTeX parse failed" in errors[0].error


# ---------------------------------------------------------------------------
# RIS
# ---------------------------------------------------------------------------

_RIS_OK = """
TY  - JOUR
TI  - A RIS Paper
AU  - Alice A
AU  - Bob B
PY  - 2023
JO  - Journal of RIS
KW  - alpha
KW  - beta
AB  - An abstract.
DO  - 10.1000/ris
ER  -
"""


def test_parse_ris_happy_path() -> None:
    resources, errors = parse_ris(_RIS_OK)

    assert errors == []
    assert len(resources) == 1
    resource = resources[0]
    assert resource.title == "A RIS Paper"
    assert resource.authors == ["Alice A", "Bob B"]
    assert resource.year == 2023
    assert resource.venue == "Journal of RIS"
    assert resource.tags == ["alpha", "beta"]
    assert resource.doi == "10.1000/ris"


def test_parse_ris_venue_falls_back_through_secondary_title_and_publisher() -> None:
    content = """
TY  - JOUR
TI  - T
AU  - Alice A
T2  - Secondary Title
PB  - A Publisher
ER  -
"""
    resources, _errors = parse_ris(content)

    assert resources[0].venue == "Secondary Title"


def test_parse_ris_unknown_type_falls_back_to_paper() -> None:
    content = """
TY  - WEIRD
TI  - T
AU  - Alice A
ER  -
"""
    resources, _errors = parse_ris(content)

    assert resources[0].type == "paper"


def test_parse_ris_missing_title_or_authors_is_per_entry_error() -> None:
    content = "TY  - JOUR\nAU  - Alice A\nER  -\n" + "TY  - JOUR\nTI  - T\nER  -\n"

    resources, errors = parse_ris(content)

    assert resources == []
    assert [e.error for e in errors] == ["missing title", "missing authors"]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

_CSV_OK = (
    "title,authors,year,venue,type,tags,discipline,subdiscipline,abstract,doi\n"
    # 注意 tags 的分隔符是 "; "（分号 + 空格），与 TAG_SEP 常量一致，
    # 也就是 CSV 里需要写成 "alpha; beta"
    'A CSV Paper,Alice A and Bob B,2022,Journal of CSV,paper,"alpha; beta",cs,ml,'
    "An abstract.,10.1000/csv\n"
)


def test_parse_csv_happy_path() -> None:
    resources, errors = parse_csv(_CSV_OK)

    assert errors == []
    assert len(resources) == 1
    resource = resources[0]
    assert resource.title == "A CSV Paper"
    assert resource.authors == ["Alice A", "Bob B"]
    assert resource.year == 2022
    assert resource.venue == "Journal of CSV"
    assert resource.type == "paper"
    assert resource.tags == ["alpha", "beta"]
    assert resource.discipline == "cs"
    assert resource.subdiscipline == "ml"
    assert resource.doi == "10.1000/csv"


def test_parse_csv_without_header_is_rejected() -> None:
    resources, errors = parse_csv("")

    assert resources == []
    assert errors[0].error == "empty CSV: no header row"


def test_parse_csv_defaults_type_and_discipline() -> None:
    content = "title,authors\nA Paper,Alice A\n"

    resources, errors = parse_csv(content)

    assert errors == []
    assert resources[0].type == "paper"
    assert resources[0].discipline == "unknown"
    assert resources[0].subdiscipline is None
    assert resources[0].tags == []


def test_parse_csv_line_numbers_match_file_lines() -> None:
    """报错行号必须是文件里的真实行号（表头占第 1 行）。"""
    content = (
        "title,authors\n"
        "Good,Alice A\n"  # line 2
        ",Bob B\n"  # line 3 — missing title
        "Another,Carol C\n"  # line 4
    )

    resources, errors = parse_csv(content)

    assert [r.title for r in resources] == ["Good", "Another"]
    assert len(errors) == 1
    assert errors[0].line == 3
    assert errors[0].error == "missing title"


def test_parse_csv_rejects_unknown_type() -> None:
    content = "title,authors,type\nA Paper,Alice A,not-a-type\n"

    resources, errors = parse_csv(content)

    assert resources == []
    assert errors[0].error == "invalid type: not-a-type"


def test_parse_csv_reports_missing_authors() -> None:
    content = "title,authors\nA Paper,\n"

    resources, errors = parse_csv(content)

    assert resources == []
    assert errors[0].error == "missing authors"


@pytest.mark.parametrize("resource_type", ["paper", "book", "thesis", "dataset", "tutorial"])
def test_parse_csv_accepts_every_allowed_type(resource_type: str) -> None:
    content = f"title,authors,type\nA Paper,Alice A,{resource_type}\n"

    resources, errors = parse_csv(content)

    assert errors == []
    assert resources[0].type == resource_type
