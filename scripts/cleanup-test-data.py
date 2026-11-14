#!/usr/bin/env python
"""Scan / preview / delete E2E test accounts safely.

The E2E suite creates many throwaway users (``e2e_*``, ``twofa*``,
``journey_*``, ``playwright*``). They are harmless in a test DB, but a
long-lived staging DB can accumulate thousands of rows and make admin
user lists unreadable.

Usage:
    uv run python scripts/cleanup-test-data.py                 # dry run
    uv run python scripts/cleanup-test-data.py --delete        # delete after preview
    uv run python scripts/cleanup-test-data.py --delete --confirm DELETE_TEST_DATA

The script never deletes a user unless the explicit confirmation string is
provided. It prints counts before and after deletion so an operator can
verify the result instead of trusting a silent job.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DEFAULT_PATTERNS = (
    r"e2e[_-]",
    r"twofa",
    r"journey[_-]",
    r"playwright",
    r"testuser",
    r"wb[_-]",
    r"qa[_-]",
    # e2e helpers 还会用这些前缀创建一次性账号；没有它们，
    # 长跑库里的测试用户会整批漏扫。
    r"auth[0-9]*_",
    r"target_",
    r"disable_",
    r"audit_",
    r"noaudit_",
)


@dataclass(frozen=True)
class TestUserRow:
    tenant: str
    user_id: int
    username: str
    email: str
    submissions: int
    assignments: int


def matches(username: str, patterns: tuple[str, ...]) -> bool:
    """Return True when a username matches one of the configured patterns."""
    return any(
        re.search(pattern, username, flags=re.IGNORECASE) for pattern in patterns
    )


async def scan(patterns: tuple[str, ...]) -> list[TestUserRow]:
    from app.core.db import async_session_factory
    from app.core.tenant import TENANT_CONTEXT_VAR
    from app.domain.catalog.models import Resource  # noqa: F401  (mapper 关系需要)
    from app.domain.review.models import ReviewAssignment
    from app.domain.submission.models import Submission
    from app.models import Tenant, User
    from sqlalchemy import func, select

    rows: list[TestUserRow] = []
    async with async_session_factory() as db:
        tenants = (
            (await db.execute(select(Tenant).order_by(Tenant.slug))).scalars().all()
        )
        for tenant in tenants:
            TENANT_CONTEXT_VAR.set(str(tenant.id))
            users = (
                (
                    await db.execute(
                        select(User)
                        .where(User.tenant_id == tenant.id)
                        .order_by(User.id)
                    )
                )
                .scalars()
                .all()
            )
            if not users:
                continue

            user_ids = [u.id for u in users]
            sub_counts = dict(
                (
                    await db.execute(
                        select(
                            Submission.submitted_by, func.count(Submission.id)
                        ).where(
                            Submission.tenant_id == tenant.id,
                            Submission.submitted_by.in_(user_ids),
                        )
                    )
                ).all()
            )
            assignment_counts = dict(
                (
                    await db.execute(
                        select(
                            ReviewAssignment.reviewer_id,
                            func.count(ReviewAssignment.id),
                        ).where(
                            ReviewAssignment.tenant_id == tenant.id,
                            ReviewAssignment.reviewer_id.in_(user_ids),
                        )
                    )
                ).all()
            )
            for user in users:
                if matches(user.username, patterns):
                    rows.append(
                        TestUserRow(
                            tenant=tenant.slug,
                            user_id=user.id,
                            username=user.username,
                            email=user.email,
                            submissions=int(sub_counts.get(user.id, 0)),
                            assignments=int(assignment_counts.get(user.id, 0)),
                        )
                    )
        return rows


async def delete_users(rows: list[TestUserRow]) -> int:
    """Delete the scanned rows tenant-by-tenant; return the deleted count."""
    from app.core.db import async_session_factory
    from app.core.tenant import TENANT_CONTEXT_VAR
    from app.models import Tenant, User
    from sqlalchemy import select

    deleted = 0
    async with async_session_factory() as db:
        tenants = (
            (await db.execute(select(Tenant).order_by(Tenant.slug))).scalars().all()
        )
        by_tenant: dict[str, list[int]] = {}
        for row in rows:
            by_tenant.setdefault(row.tenant, []).append(row.user_id)
        for tenant in tenants:
            ids = by_tenant.get(tenant.slug)
            if not ids:
                continue
            TENANT_CONTEXT_VAR.set(str(tenant.id))
            users = (
                (
                    await db.execute(
                        select(User).where(
                            User.tenant_id == tenant.id,
                            User.id.in_(ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for user in users:
                await db.delete(user)
                deleted += 1
            await db.commit()
    return deleted


def print_rows(rows: list[TestUserRow]) -> None:
    if not rows:
        print("未发现匹配的测试账号。")
        return
    print(
        f"{'tenant':<12} {'id':>6} {'username':<28} {'投稿':>4} {'审稿':>4} {'email'}"
    )
    print("-" * 86)
    for row in rows:
        print(
            f"{row.tenant:<12} {row.user_id:>6} {row.username:<28} "
            f"{row.submissions:>4} {row.assignments:>4} {row.email}"
        )
    print("-" * 86)
    print(f"合计：{len(rows)} 个账号")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        help="额外/覆盖匹配正则；可重复传入。默认匹配 e2e_、twofa、journey_ 等。",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="真正删除；默认只扫描预览。",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="删除时必须传入 DELETE_TEST_DATA，防止误删。",
    )
    args = parser.parse_args()
    patterns = tuple(args.patterns) if args.patterns else DEFAULT_PATTERNS

    rows = await scan(patterns)
    print_rows(rows)
    if not args.delete:
        print("\n干跑完成；要删除请加 --delete --confirm DELETE_TEST_DATA。")
        return 0
    if args.confirm != "DELETE_TEST_DATA":
        print("\n拒绝删除：--confirm 必须是 DELETE_TEST_DATA。", file=sys.stderr)
        return 2
    deleted = await delete_users(rows)
    print(f"\n已删除 {deleted} 个测试账号。")

    remaining = await scan(patterns)
    print_rows(remaining)
    return 0 if not remaining else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
