"""036 — scarce R coin (100 R = ¥1), anti-overissue caps, shop admin.

- Rescales existing coin ledger rows by /5 so historical 5-per-checkin becomes
  1-per-checkin; old balances recomputed from the ledger.
- Adds editable currency rules + policy + shop catalog/orders.
- Seeds one policy and one theme-unlock SKU per tenant, plus the new rule set.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "036_coin_scarcity_shop"
down_revision = "035_coin_backfill_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coin_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("daily_cap", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "reason", name="uq_coin_rule_tenant_reason"),
    )
    op.create_table(
        "coin_policy",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("coin_per_yuan", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("daily_earn_cap", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("monthly_issue_cap", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", name="uq_coin_policy_tenant"),
    )
    op.create_table(
        "coin_shop_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_coin", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effect", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("cover_url", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "coin_purchases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=100), nullable=False),
        sa.Column("price_coin", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="paid"),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_coin_shop_items_tenant_active", "coin_shop_items", ["tenant_id", "is_active"]
    )
    op.create_index("ix_coin_purchases_tenant_user", "coin_purchases", ["tenant_id", "user_id"])

    # 四张新表都按 tenant_id 做第二层隔离；漏掉 RLS 会被静态门禁拦住。
    op.execute("ALTER TABLE coin_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE coin_policy ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE coin_shop_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE coin_purchases ENABLE ROW LEVEL SECURITY")
    for table in ("coin_rules", "coin_policy", "coin_shop_items", "coin_purchases"):
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            """
        )

    op.execute(
        """
        DO $$
        DECLARE t uuid;
        BEGIN
          FOR t IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.current_tenant_id', t::text, true);
            UPDATE point_events
            SET delta = GREATEST(1, ROUND(delta / 5.0))::integer
            WHERE tenant_id = t AND identity = 'coin' AND delta > 0;

            UPDATE users u
            SET coin_balance = COALESCE(
              (SELECT SUM(p.delta) FROM point_events p
               WHERE p.tenant_id = t AND p.user_id = u.id AND p.identity = 'coin'),
              0
            )
            WHERE u.tenant_id = t;

            INSERT INTO coin_policy (tenant_id, coin_per_yuan, daily_earn_cap, monthly_issue_cap)
            VALUES (t, 100, 5, 5000)
            ON CONFLICT (tenant_id) DO NOTHING;

            INSERT INTO coin_rules (tenant_id, reason, label, amount, daily_cap, is_active)
            VALUES
              (t, 'checkin.daily', '每日签到', 1, 1, true),
              (t, 'checkin.weekly_bonus', '连续签到 7 天奖励', 2, 2, true),
              (t, 'forum.topic', '发布论坛主题', 1, 1, true),
              (t, 'forum.reply', '论坛回复', 0, 1, false),
              (t, 'claim.approve', '作者认领通过', 10, 1, true),
              (t, 'review.completed', '完成审稿', 5, 2, true),
              (t, 'submission.accepted', '论文录用', 20, 1, true),
              (t, 'editor.decision', '编辑裁决', 3, 3, true)
            ON CONFLICT (tenant_id, reason) DO NOTHING;

            INSERT INTO coin_shop_items
              (tenant_id, name, description, price_coin, stock, is_active, sort_order, effect)
            VALUES
              (t, '自定义主页主题色', '解锁后主页头像、按钮和封面渐变可自选配色，永久有效。', 100, NULL, true, 10, 'accent_unlock'),
              (t, '主页封面模板', '主编人工为你换一套主页封面配色与排版，7 天内生效。', 200, 20, true, 20, 'none'),
              (t, '论坛帖置顶 7 天', '指定一篇自己发布的主题在讨论区置顶 7 天；下单后联系主编。', 500, 10, true, 30, 'none')
            ON CONFLICT DO NOTHING;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_coin_purchases_tenant_user", table_name="coin_purchases")
    op.drop_index("ix_coin_shop_items_tenant_active", table_name="coin_shop_items")
    op.drop_table("coin_purchases")
    op.drop_table("coin_shop_items")
    op.drop_table("coin_policy")
    op.drop_table("coin_rules")
