"""034 — translate historical check-ins into R coins.

Existing accounts already have ``user_xp_events`` check-in rows but the wallet
was introduced with a zero balance.  Backfill one coin row per historical
check-in (and per 7-day bonus) so a long-time user doesn't open the wallet to
"12 次签到 / 0 收入".

Idempotent via the same ``uq_point_event_identity`` conflict target used by the
runtime service; re-running is safe.
"""

from __future__ import annotations

from alembic import op

revision = "034_coin_backfill"
down_revision = "033_profile_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``point_events`` 在部分环境由运行期建表，历史迁移链没有显式建表；
    # 空库跑 alembic 时必须在写入前补上，否则 034 会直接 failed。
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS point_events (
            id SERIAL PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            identity VARCHAR(16) NOT NULL,
            delta INTEGER NOT NULL DEFAULT 0,
            reason VARCHAR(64) NOT NULL,
            ref_type VARCHAR(32) NOT NULL DEFAULT '',
            ref_id VARCHAR(64) NOT NULL DEFAULT '',
            note VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_point_event_identity UNIQUE
                (tenant_id, user_id, identity, reason, ref_type, ref_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_point_events_tenant_user_created "
        "ON point_events (tenant_id, user_id, created_at DESC)"
    )
    op.execute(
        """
        INSERT INTO point_events
            (tenant_id, user_id, identity, delta, reason, ref_type, ref_id, note, created_at)
        SELECT
            tenant_id, user_id, 'coin', 5, 'checkin.daily', 'checkin', ref_id,
            '历史签到补发', created_at
        FROM user_xp_events
        WHERE action = 'checkin.daily' AND ref_id IS NOT NULL
        ON CONFLICT (tenant_id, user_id, identity, reason, ref_type, ref_id)
        DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO point_events
            (tenant_id, user_id, identity, delta, reason, ref_type, ref_id, note, created_at)
        SELECT
            tenant_id, user_id, 'coin', 10, 'checkin.weekly_bonus', 'checkin', ref_id,
            '历史连续签到补发', created_at
        FROM user_xp_events
        WHERE action = 'checkin.weekly_bonus' AND ref_id IS NOT NULL
        ON CONFLICT (tenant_id, user_id, identity, reason, ref_type, ref_id)
        DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE users u
        SET coin_balance = COALESCE(
            (SELECT SUM(p.delta) FROM point_events p
             WHERE p.user_id = u.id AND p.identity = 'coin'),
            0
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM point_events WHERE identity = 'coin'")
    op.execute("UPDATE users SET coin_balance = 0")
