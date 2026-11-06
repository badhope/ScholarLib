"""v1.11 生态规范行为锁：封面闭环 / 类别体系 / 职权链常量。"""
from __future__ import annotations

from app.api import deps
from app.modules.catalog import cover_defaults
from app.modules.submission._helpers import _category_from_track


def test_discipline_cover_mapping():
    assert cover_defaults.cover_slug_for_discipline("计算机科学与技术") == "computer-science"
    assert cover_defaults.cover_slug_for_discipline("中国语言文学") == "humanities"
    assert cover_defaults.cover_slug_for_discipline(None) == "social-science"
    assert cover_defaults.cover_slug_for_discipline("数学") == "mathematics"


def test_default_cover_path_deterministic():
    a = cover_defaults.default_cover_for("计算机", seed=1)
    b = cover_defaults.default_cover_for("计算机", seed=1)
    assert a == b and a.startswith("/covers/computer-science-")


def test_category_from_track():
    assert _category_from_track("serious") == "academic"
    assert _category_from_track("absurd") == "fun"
    assert _category_from_track(None) == "academic"


def test_role_chain_constants():
    assert deps.CHIEF_ROLES == ("chief_editor", "deputy_editor")
    assert "board_editor" in deps.EDITORIAL_ROLES and "chief_editor" in deps.EDITORIAL_ROLES
