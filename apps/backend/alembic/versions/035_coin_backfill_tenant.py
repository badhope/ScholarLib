"""035 — backfill R coins per tenant (RLS-safe).

034 selected ``user_xp_events`` without a tenant GUC, so forced RLS returned
zero rows.  This migration loops every tenant, sets
``app.current_tenant_id`` transaction-locally, then inserts the historical
check-in coins and recomputes the wallet snapshot for that tenant.
"""

from __future__ import annotations

from alembic import op

revision = "035_coin_backfill_tenant"
down_revision = "034_coin_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE t uuid;
        BEGIN
          FOR t IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);

            INSERT INTO point_events
                (tenant_id, user_id, identity, delta, reason, ref_type, ref_id, note, created_at)
            SELECT
                tenant_id, user_id, 'coin', 5, 'checkin.daily', 'checkin', ref_id,
                '历史签到补发', created_at
            FROM user_xp_events
            WHERE tenant_id = t AND action = 'checkin.daily' AND ref_id IS NOT NULL
            ON CONFLICT (tenant_id, user_id, identity, reason, ref_type, ref_id)
            DO NOTHING;

            INSERT INTO point_events
                (tenant_id, user_id, identity, delta, reason, ref_type, ref_id, note, created_at)
            SELECT
                tenant_id, user_id, 'coin', 10, 'checkin.weekly_bonus', 'checkin', ref_id,
                '历史连续签到补发', created_at
            FROM user_xp_events
            WHERE tenant_id = t AND action = 'checkin.weekly_bonus' AND ref_id IS NOT NULL
            ON CONFLICT (tenant_id, user_id, identity, reason, ref_type, ref_id)
            DO NOTHING;

            UPDATE users u
            SET coin_balance = COALESCE(
                (SELECT SUM(p.delta) FROM point_events p
                 WHERE p.tenant_id = t AND p.user_id = u.id AND p.identity = 'coin'),
                0
            )
            WHERE u.tenant_id = t;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # 034's downgrade already owns the destructive path; leave it there.
    pass
