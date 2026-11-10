"""Gamification service — XP awarding, badge evaluation, profile payload.

All functions take an ``AsyncSession`` and a ``User``; tenant scoping is
explicit on every query (RLS is the second layer in production).
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Role, User, UserRole
from app.modules.gamification.badges import BADGES, badge_payload
from app.modules.gamification.ladder import (
    IDENTITY_RANK,
    identities_payload,
    identity_for_roles,
    identity_payload,
    is_author_eligible,
)
from app.modules.gamification.models import UserAchievement, UserXpEvent
from app.modules.gamification.xp import XP_RULES

# Imported lazily inside functions to avoid a module import cycle:
# comments/reader/submission all depend on the core models only, but the
# catalog module imports deps which imports gamification in route guards.


async def _user_role_names(db: AsyncSession, user: User) -> list[str]:
    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == user.tenant_id,
            Role.tenant_id == user.tenant_id,
        )
    )
    return sorted({r for r in result.scalars() if r})


async def award(
    db: AsyncSession,
    user: User,
    action: str,
    *,
    ref_type: str = "",
    ref_id: str = "",
    points: int | None = None,
    note: str | None = None,
    commit: bool = False,
) -> bool:
    """Append an XP event (idempotent per action+ref). Returns True if new.

    The caller decides the transaction boundary: ``commit=False`` (default)
    lets the caller fold the award into its own transaction so a failed
    business operation never leaves stray points behind.
    """
    value = XP_RULES.get(action, 0) if points is None else points
    if value <= 0 and action != "admin.grant":
        return False
    from app.modules.gamification.xp import DAILY_COMMENT_XP_CAP

    if action == "comment.create":
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        earned_today = (
            await db.execute(
                select(func.coalesce(func.sum(UserXpEvent.points), 0)).where(
                    UserXpEvent.tenant_id == user.tenant_id,
                    UserXpEvent.user_id == user.id,
                    UserXpEvent.action == action,
                    UserXpEvent.created_at >= day_start,
                )
            )
        ).scalar_one()
        if int(earned_today) >= DAILY_COMMENT_XP_CAP:
            return False
    exists = (
        await db.execute(
            select(UserXpEvent.id).where(
                UserXpEvent.tenant_id == user.tenant_id,
                UserXpEvent.user_id == user.id,
                UserXpEvent.action == action,
                UserXpEvent.ref_type == ref_type,
                UserXpEvent.ref_id == ref_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    db.add(
        UserXpEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action=action,
            points=value,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
        )
    )
    user.xp = (user.xp or 0) + value
    if commit:
        await db.commit()
    return True


async def collect_metrics(db: AsyncSession, user: User) -> dict[str, int]:
    """Aggregate the numbers every badge criterion reads."""
    from app.modules.comments.models import Comment
    from app.modules.follows.models import AuthorFollow, DisciplineSubscription
    from app.modules.library.models import ReadingList, ReadingListItem
    from app.modules.reader.models import ReadingHistory
    from app.modules.review.models import ReviewReport
    from app.modules.submission.models import Submission

    tid = user.tenant_id
    uid = user.id

    async def count(stmt: Any) -> int:
        return int((await db.execute(stmt)).scalar_one() or 0)

    completed_reads = await count(
        select(func.count(ReadingHistory.id)).where(
            ReadingHistory.tenant_id == tid,
            ReadingHistory.user_id == uid,
            ReadingHistory.completed.is_(True),
        )
    )
    comments = await count(
        select(func.count(Comment.id)).where(Comment.tenant_id == tid, Comment.user_id == uid)
    )
    reading_lists = await count(
        select(func.count(ReadingList.id)).where(
            ReadingList.tenant_id == tid, ReadingList.user_id == uid
        )
    )
    saved_items = await count(
        select(func.count(ReadingListItem.id))
        .join(ReadingList, ReadingList.id == ReadingListItem.reading_list_id)
        .where(
            ReadingListItem.tenant_id == tid,
            ReadingList.user_id == uid,
        )
    )
    followed_authors = await count(
        select(func.count(AuthorFollow.id)).where(
            AuthorFollow.tenant_id == tid, AuthorFollow.user_id == uid
        )
    )
    subscribed = await count(
        select(func.count(DisciplineSubscription.id)).where(
            DisciplineSubscription.tenant_id == tid,
            DisciplineSubscription.user_id == uid,
        )
    )
    submissions = await count(
        select(func.count(Submission.id)).where(
            Submission.tenant_id == tid, Submission.submitted_by == uid
        )
    )
    accepted = await count(
        select(func.count(Submission.id)).where(
            Submission.tenant_id == tid,
            Submission.submitted_by == uid,
            Submission.status.in_(("accepted", "approved")),
        )
    )
    rejected = await count(
        select(func.count(Submission.id)).where(
            Submission.tenant_id == tid,
            Submission.submitted_by == uid,
            Submission.status == "rejected",
        )
    )
    from app.modules.review.models import ReviewAssignment

    reviews_completed = await count(
        select(func.count(ReviewReport.id))
        .join(ReviewAssignment, ReviewAssignment.id == ReviewReport.assignment_id)
        .where(
            ReviewReport.tenant_id == tid,
            ReviewAssignment.reviewer_id == uid,
        )
    )
    from app.models import AuditLog

    decisions_made = await count(
        select(func.count(AuditLog.id)).where(
            AuditLog.tenant_id == tid,
            AuditLog.actor_user_id == uid,
            AuditLog.action == "submission.decision",
        )
    )

    history_rows = (
        await db.execute(
            select(
                ReadingHistory.last_read_at,
                ReadingHistory.viewed_at,
                ReadingHistory.duration_sec,
                ReadingHistory.page,
                ReadingHistory.progress_percent,
                ReadingHistory.completed,
                ReadingHistory.resource_id,
            ).where(ReadingHistory.tenant_id == tid, ReadingHistory.user_id == uid)
        )
    ).all()
    per_day: dict[str, int] = defaultdict(int)
    night_reads = 0
    early_reads = 0
    for row in history_rows:
        stamp = row[0] or row[1]
        if stamp is None:
            continue
        day = stamp.date().isoformat()
        per_day[day] += int(row[2] or 0)
        if row[5]:
            hour = stamp.hour
            if 2 <= hour < 5:
                night_reads += 1
            if 5 <= hour < 7:
                early_reads += 1
    best_streak = _best_streak(sorted(per_day.keys()))
    max_daily_minutes = max((v // 60 for v in per_day.values()), default=0)

    read_disciplines = await _distinct_disciplines_read(db, user)

    return {
        "completed_reads": completed_reads,
        "comments": comments,
        "reading_lists": reading_lists,
        "saved_items": saved_items,
        "followed_authors": followed_authors,
        "subscribed_disciplines": subscribed,
        "submissions": submissions,
        "accepted_submissions": accepted,
        "rejections_then_resubmit": 1 if (rejected > 0 and submissions > rejected) else 0,
        "reviews_completed": reviews_completed,
        "decisions_made": decisions_made,
        "best_streak_days": best_streak,
        "max_daily_minutes": max_daily_minutes,
        "distinct_disciplines_read": read_disciplines,
        "night_reads": night_reads,
        "early_reads": early_reads,
    }


def _best_streak(days: list[str]) -> int:
    if not days:
        return 0
    best = 1
    run = 1
    parsed = [datetime.fromisoformat(d).date() for d in days]
    for prev, cur in itertools.pairwise(parsed):
        if (cur - prev).days == 1:
            run += 1
            best = max(best, run)
        elif (cur - prev).days > 1:
            run = 1
    return best


async def _distinct_disciplines_read(db: AsyncSession, user: User) -> int:
    from app.modules.catalog.models import Resource
    from app.modules.reader.models import ReadingHistory

    rows = (
        await db.execute(
            select(Resource.discipline)
            .join(ReadingHistory, ReadingHistory.resource_id == Resource.id)
            .where(
                ReadingHistory.tenant_id == user.tenant_id,
                ReadingHistory.user_id == user.id,
                ReadingHistory.completed.is_(True),
            )
            .distinct()
        )
    ).scalars()
    return len({r for r in rows if r})


async def evaluate_badges(db: AsyncSession, user: User) -> list[UserAchievement]:
    """Unlock every badge whose criterion now holds. Returns newly unlocked."""
    metrics = await collect_metrics(db, user)
    owned = set(
        (
            await db.execute(
                select(UserAchievement.badge_key).where(
                    UserAchievement.tenant_id == user.tenant_id,
                    UserAchievement.user_id == user.id,
                )
            )
        ).scalars()
    )
    unlocked: list[UserAchievement] = []
    now = utcnow()
    for spec in BADGES:
        if spec.key in owned:
            continue
        if metrics.get(spec.metric, 0) >= spec.threshold:
            row = UserAchievement(
                tenant_id=user.tenant_id,
                user_id=user.id,
                badge_key=spec.key,
                unlocked_at=now,
            )
            db.add(row)
            unlocked.append(row)
    if unlocked:
        await db.flush()
    return unlocked


async def level_snapshot(db: AsyncSession, user: User, roles: list[str]) -> dict[str, Any]:
    """当前用户的身份快照。

    返回结构保留 ``level`` 键名（前端与外部调用方都在读），但语义已从
    "九级游戏等级"变成"四层身份中的哪一层"。同时给出 ``xp``（纯荣誉
    统计，不参与任何权限判定）与 ``author_eligible``（合规状态）。

    为什么不再有 ``next_level_xp`` / ``progress``：旧体系把"再攒 86 XP
    就能关注作者"当成进步感来源，而关注作者本来就不该有门槛。身份要么
    有（编辑部授予），要么没有（去申请），不存在"攒积分换身份"的路径，
    所以"进度条"这个概念本身就不成立。
    """
    from app.api.levels import CURRENT_RULES_VERSION

    xp = int(user.xp or 0)
    slug = identity_for_roles(roles, is_admin=bool(user.is_admin))
    # 作者身份是合规状态而非角色：已确认当版规范 = 可投稿。
    author_ok = is_author_eligible(user.rules_ack_version, CURRENT_RULES_VERSION)
    # 有审稿/编辑角色的人天然也是作者（他们当然可以投稿）。
    if IDENTITY_RANK[slug] >= IDENTITY_RANK["author"]:
        author_ok = True
    # 读者 + 已确认规范 = 作者身份。不提升 slug 的话，作者会永远显示为
    # "读者"，而 next_identity 又会说"去确认规范"——明明已经确认过了。
    if slug == "reader" and author_ok:
        slug = "author"
    payload = identity_payload(slug)
    payload.update(
        {
            # 兼容旧字段名：外部读 level.level 的地方不用改。
            "level": IDENTITY_RANK[slug] + 1,
            "xp": xp,
            "roles": roles,
            "author_eligible": author_ok,
            # 下一个可争取的身份（读者→作者→审稿人），没有则 None。
            "next_identity": _next_identity(slug, author_ok),
        }
    )
    return payload


def _next_identity(slug: str, author_ok: bool) -> dict[str, str] | None:
    """下一个可争取的身份 + 怎么拿到（前端展示"如何升级"的唯一来源）。"""
    if slug == "reader" and not author_ok:
        return {
            "slug": "author",
            "name": "作者",
            "how": "阅读并确认《投稿与编辑规范》，即可投稿",
        }
    if slug in ("reader", "author"):
        return {
            "slug": "reviewer",
            "name": "审稿人",
            "how": "至少 1 篇稿件被本刊录用且最高 RQS ≥ 60 后，在「身份」页提交申请",
        }
    if slug == "reviewer":
        return {
            "slug": "editor",
            "name": "编辑",
            "how": "由编辑部按贡献提拔，不开放申请",
        }
    return None


async def profile(db: AsyncSession, user: User, *, include_secret: bool) -> dict[str, Any]:
    roles = await _user_role_names(db, user)
    metrics = await collect_metrics(db, user)
    owned_rows = (
        (
            await db.execute(
                select(UserAchievement).where(
                    UserAchievement.tenant_id == user.tenant_id,
                    UserAchievement.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    owned = {row.badge_key: row.unlocked_at for row in owned_rows}
    badges = []
    for spec in BADGES:
        if spec.secret and not include_secret and spec.key not in owned:
            continue
        payload = badge_payload(spec)
        payload["unlocked"] = spec.key in owned
        payload["unlocked_at"] = owned[spec.key].isoformat() if spec.key in owned else None
        payload["current"] = metrics.get(spec.metric, 0)
        badges.append(payload)
    badges.sort(key=lambda b: (not b["unlocked"], b["category"], b["threshold"]))
    recent = (
        (
            await db.execute(
                select(UserXpEvent)
                .where(UserXpEvent.tenant_id == user.tenant_id, UserXpEvent.user_id == user.id)
                .order_by(UserXpEvent.created_at.desc(), UserXpEvent.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return {
        "user_id": user.id,
        "username": user.username,
        "xp": user.xp or 0,
        "level": await level_snapshot(db, user, roles),
        "identities": identities_payload(),
        # 旧键名保留一版：前端/第三方按 ladder 读取的地方不立刻断。
        "ladder": identities_payload(),
        "badges": badges,
        "unlocked_count": len(owned),
        "total_badges": len([b for b in BADGES if include_secret or not b.secret])
        + (len([b for b in BADGES if b.secret]) if include_secret else 0),
        "metrics": metrics,
        "recent_xp": [
            {
                "action": e.action,
                "points": e.points,
                "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in recent
        ],
    }


async def grant_admin_xp(
    db: AsyncSession, *, actor: User, target: User, points: int, note: str
) -> None:
    """Manual grant by L9 operators; ref id keeps repeated grants distinct."""
    stamp = utcnow().strftime("%Y%m%d%H%M%S%f")
    await award(
        db,
        target,
        "admin.grant",
        ref_type="manual",
        ref_id=f"{actor.id}:{stamp}",
        points=points,
        note=note,
        commit=True,
    )


def streak_preview(days: Counter[str]) -> int:  # pragma: no cover - small helper
    return _best_streak(sorted(days))


def window_start(days: int = 30) -> datetime:
    return utcnow() - timedelta(days=days)


# ---------------------------------------------------------------------------
# 每日签到（货币/激励体系的一部分）
# 口径：每天一次 checkin.daily（ref_id=UTC 日期，台账唯一约束天然幂等）；
# 连续天数按「今天或昨天收尾的连续日」计；每满 7 天额外发 checkin.weekly_bonus。
# ---------------------------------------------------------------------------

_CHECKIN_ACTION = "checkin.daily"
_CHECKIN_BONUS_ACTION = "checkin.weekly_bonus"


def _today_str(now: datetime | None = None) -> str:
    return (now or utcnow()).date().isoformat()


def _current_streak(dates: set[str], today: str) -> int:
    """以 today（已签）或 today-1（未签）收尾的连续签到天数。"""
    from datetime import date as _date

    cur = _date.fromisoformat(today)
    if today not in dates:
        cur = cur - timedelta(days=1)
        if cur.isoformat() not in dates:
            return 0
    streak = 0
    while cur.isoformat() in dates:
        streak += 1
        cur -= timedelta(days=1)
    return streak


async def _checkin_dates(db: AsyncSession, user: User) -> set[str]:
    rows = await db.execute(
        select(UserXpEvent.ref_id).where(
            UserXpEvent.tenant_id == user.tenant_id,
            UserXpEvent.user_id == user.id,
            UserXpEvent.action == _CHECKIN_ACTION,
        )
    )
    return {r for r in rows.scalars() if r}


async def checkin_status(db: AsyncSession, user: User) -> dict[str, object]:
    """今日是否已签 + 连续天数 + 累计签到天数。"""
    dates = await _checkin_dates(db, user)
    today = _today_str()
    return {
        "checked_in_today": today in dates,
        "streak": _current_streak(dates, today),
        "total": len(dates),
        "daily_xp": XP_RULES.get(_CHECKIN_ACTION, 0),
        "weekly_bonus_xp": XP_RULES.get(_CHECKIN_BONUS_ACTION, 0),
    }


async def daily_checkin(db: AsyncSession, user: User) -> dict[str, object]:
    """执行每日签到。重复签到不是错误：返回当前状态（awarded=False）。"""
    today = _today_str()
    awarded = await award(db, user, _CHECKIN_ACTION, ref_type="checkin", ref_id=today, commit=False)
    bonus_awarded = False
    if awarded:
        dates = await _checkin_dates(db, user)
        streak = _current_streak(dates, today)
        if streak > 0 and streak % 7 == 0:
            bonus_awarded = await award(
                db,
                user,
                _CHECKIN_BONUS_ACTION,
                ref_type="checkin",
                ref_id=today,
                commit=False,
                note=f"连续签到 {streak} 天奖励",
            )
    await db.commit()
    dates = await _checkin_dates(db, user)
    return {
        "awarded": awarded,
        "bonus_awarded": bonus_awarded,
        "checked_in_today": True,
        "streak": _current_streak(dates, today),
        "total": len(dates),
        "daily_xp": XP_RULES.get(_CHECKIN_ACTION, 0),
        "weekly_bonus_xp": XP_RULES.get(_CHECKIN_BONUS_ACTION, 0),
    }


__all__ = [
    "award",
    "checkin_status",
    "collect_metrics",
    "daily_checkin",
    "evaluate_badges",
    "grant_admin_xp",
    "level_snapshot",
    "profile",
    "window_start",
]
