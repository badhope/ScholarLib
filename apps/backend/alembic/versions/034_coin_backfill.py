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
