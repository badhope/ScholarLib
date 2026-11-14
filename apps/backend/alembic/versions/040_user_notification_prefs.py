"""040 — 用户通知偏好

用户级开关：评论/回帖/审稿/投稿的站内与邮件通知。只存显式改过的键，
读取时与默认值合并；默认站内开、邮件关，避免存量用户被邮件轰炸。

Revision ID: 040_user_notification_prefs
Revises: 039_submission_similarity
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "040_user_notification_prefs"
down_revision = "039_submission_similarity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notification_prefs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
