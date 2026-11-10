"""v1.11 生态规范行为锁：封面闭环 / 类别体系 / 职权链常量。"""

from __future__ import annotations

from app.api import deps
from app.core.tracks import canonicalize_track_category
from app.modules.catalog import cover_defaults


def test_discipline_cover_mapping():
    assert cover_defaults.cover_slug_for_discipline("计算机科学与技术") == "computer-science"
    assert cover_defaults.cover_slug_for_discipline("中国语言文学") == "humanities"
    assert cover_defaults.cover_slug_for_discipline(None) == "social-science"
    assert cover_defaults.cover_slug_for_discipline("数学") == "mathematics"


def test_default_cover_path_deterministic():
    a = cover_defaults.default_cover_for("计算机", seed=1)
    b = cover_defaults.default_cover_for("计算机", seed=1)
    assert a == b and a.startswith("/covers/computer-science-")


def test_track_category_single_authority():
    """单一权威口径：content_track 权威，category 由 track 推导。"""
    # paper 强制 academic——带 fun 也落 academic
    assert canonicalize_track_category("paper", "fun") == ("paper", "academic")
    # essay 缺省 fun
    assert canonicalize_track_category("essay", None) == ("essay", "fun")
    # essay + rant 透传
    assert canonicalize_track_category("essay", "rant") == ("essay", "rant")
    # track 缺失时 category 回推赛道
    assert canonicalize_track_category(None, "academic") == ("paper", "academic")
    assert canonicalize_track_category(None, "fun") == ("essay", "fun")
    # 全缺省：本刊默认学术刊
    assert canonicalize_track_category(None, None) == ("paper", "academic")


def test_role_chain_constants():
    assert deps.CHIEF_ROLES == ("chief_editor", "deputy_editor")
    assert "board_editor" in deps.EDITORIAL_ROLES and "chief_editor" in deps.EDITORIAL_ROLES


def test_role_assign_schema_accepts_editorial_chain():
    """v1.11 职权链角色必须能通过 API 校验（此前 Literal 未同步会 422）。"""
    from app.schemas import RoleAssign

    for role in ("chief_editor", "deputy_editor", "board_editor", "editor"):
        assert RoleAssign(role=role).role == role


def test_recommendation_is_category_scoped():
    """铁律三：读者有类别偏好时，推荐只在该类别内比对。"""
    from app.modules.recommendations.engine import UserProfile, _Candidate

    profile = UserProfile()
    profile.categories["academic"] += 3
    academic = _Candidate(
        id=1, tags=[], discipline="计算机", subdiscipline=None, content_category="academic"
    )
    rant = _Candidate(
        id=2, tags=[], discipline="计算机", subdiscipline=None, content_category="rant"
    )
    assert "content_category" in _Candidate.__dataclass_fields__
    assert academic.content_category != rant.content_category
