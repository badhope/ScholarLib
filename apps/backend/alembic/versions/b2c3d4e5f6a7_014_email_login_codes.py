"""014 — email_login_codes（邮箱验证码登录）

读者记不住密码，「输邮箱收个码就进」是内容站的标准期待。本表承载
一次性 6 位验证码：

- 只存 SHA-256(email:code:server_secret) 哈希，库泄露不可回用
- 10 分钟有效、一次性消费（consumed_at 置位）
- 每码最多 5 次校验尝试，防 6 位数字空间被在线爆破
- 同邮箱重新请求即作废旧码（request 端点先删旧行）
- 每邮箱每分钟 1 条 / 每天 10 条，防邮件轰炸（应用层限流）

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

_RLS_TABLES = ("email_login_codes",)


def upgrade() -> None:
    op.create_table(
        "email_login_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("email", "code_hash", name="uq_email_login_codes_email_code"),
    )
    op.create_index("ix_email_login_codes_email", "email_login_codes", ["email"])
    op.create_index(
        "ix_email_login_codes_tenant_email_created",
        "email_login_codes",
        ["tenant_id", "email", sa.text("created_at DESC")],
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON email_login_codes")
        op.execute("ALTER TABLE email_login_codes NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE email_login_codes DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_email_login_codes_tenant_email_created", table_name="email_login_codes")
    op.drop_index("ix_email_login_codes_email", table_name="email_login_codes")
    op.drop_table("email_login_codes")
